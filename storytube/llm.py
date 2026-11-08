"""Client LLM: DeepSeek (wire Anthropic, giống DSH) + mọi endpoint OpenAI Chat Completions.

Nguyên tắc (học từ xnovelist): model là "người đề xuất" không trạng thái — nó chỉ
trả JSON, harness quyết định chạy bước nào và ghi gì vào DB.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

from .config import load_config, read_dsh_token


class LLMError(RuntimeError):
    pass


def resolve_key(conf: dict) -> tuple[str, str]:
    """Trả (key, nguồn). Thứ tự: config -> biến môi trường -> token đăng nhập DSH.

    ``auto`` **không** lấy token của DSH: đó là token phiên đăng nhập, API công
    khai của DeepSeek trả 401. Muốn thử token đó thì đặt ``key_source: "dsh"``.
    """
    explicit = conf.get("api_key") or ""
    env_name = conf.get("api_key_env") or ""
    from_env = os.environ.get(env_name, "") if env_name else ""
    source = conf.get("key_source") or "auto"
    if source == "config":
        return explicit, "config"
    if source == "env":
        return from_env, (f"env:{env_name}" if from_env else "")
    if source == "dsh":
        token = read_dsh_token()
        return token, ("dsh" if token else "")
    if explicit:
        return explicit, "config"
    if from_env:
        return from_env, f"env:{env_name}"
    return "", ""


def provider_conf(cfg: dict | None = None, name: str | None = None) -> tuple[str, dict]:
    cfg = cfg or load_config()
    llm = cfg.get("llm", {})
    key_name = name or llm.get("default") or "deepseek"
    providers = llm.get("providers", {})
    if key_name not in providers:
        raise LLMError(f"Không có provider LLM '{key_name}' trong config")
    conf = dict(providers[key_name])
    conf["name"] = key_name
    key, key_source = resolve_key(conf)
    conf["api_key"] = key
    conf["key_source_used"] = key_source
    conf["api_style"] = conf.get("api_style") or (
        "anthropic" if "/anthropic" in str(conf.get("base_url", "")) else "openai"
    )
    if not conf.get("base_url"):
        raise LLMError(f"Provider '{key_name}' chưa có base_url")
    return key_name, conf


def _is_local(conf: dict) -> bool:
    return str(conf.get("base_url", "")).startswith(("http://localhost", "http://127.0.0.1"))


def is_ready(cfg: dict | None = None, name: str | None = None) -> bool:
    try:
        _, conf = provider_conf(cfg, name)
    except LLMError:
        return False
    if _is_local(conf):
        return True
    return bool(conf.get("api_key"))


def _post(url: str, payload: dict, headers: dict, timeout: int = 240) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _auth_error(name: str, conf: dict, detail: str) -> LLMError:
    if conf.get("key_source_used") == "dsh":
        return LLMError(
            "DeepSeek từ chối token đăng nhập của DSH (token phiên, không phải API key). "
            "Mở https://platform.deepseek.com/api_keys tạo key sk-... rồi dán vào Cài đặt "
            "(hoặc chạy: python -m storytube keys --deepseek sk-...)."
        )
    return LLMError(f"Xác thực thất bại với {name}: {detail[:300]}")


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    return "\n\n".join(system_parts), rest


def _call_anthropic(conf: dict, messages: list[dict], temperature: float, max_tokens: int) -> dict:
    system, rest = _split_system(messages)
    payload: dict[str, Any] = {
        "model": conf.get("model"),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {"role": m.get("role", "user"), "content": m.get("content", "")} for m in rest
        ],
    }
    if system:
        payload["system"] = system
    headers = {"x-api-key": conf.get("api_key", ""), "anthropic-version": "2023-06-01"}
    data = _post(conf["base_url"].rstrip("/") + "/v1/messages", payload, headers)
    text = ""
    for block in data.get("content") or []:
        if block.get("type") == "text":
            text += block.get("text", "")
    usage = data.get("usage") or {}
    return {
        "text": text,
        "model": data.get("model") or conf.get("model"),
        "usage": {
            "prompt": usage.get("input_tokens", 0),
            "completion": usage.get("output_tokens", 0),
        },
    }


def _call_openai(conf: dict, messages: list[dict], temperature: float, max_tokens: int,
                 use_json: bool) -> dict:
    payload: dict[str, Any] = {
        "model": conf.get("model"),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if use_json:
        payload["response_format"] = {"type": "json_object"}
    headers = {}
    if conf.get("api_key"):
        headers["Authorization"] = f"Bearer {conf['api_key']}"
    data = _post(conf["base_url"].rstrip("/") + "/chat/completions", payload, headers)
    choice = (data.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    return {
        "text": text,
        "model": data.get("model") or conf.get("model"),
        "usage": {
            "prompt": usage.get("prompt_tokens", 0),
            "completion": usage.get("completion_tokens", 0),
        },
    }


def chat(
    messages: list[dict],
    *,
    cfg: dict | None = None,
    provider: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    json_mode: bool | None = None,
    retries: int = 3,
) -> dict[str, Any]:
    cfg = cfg or load_config()
    name, conf = provider_conf(cfg, provider)
    if not conf.get("api_key") and not _is_local(conf):
        dsh = read_dsh_token()
        hint = (
            " Token DSH tìm thấy trong ~/.dsh/.credentials.yaml là token đăng nhập, "
            "DeepSeek API công khai không chấp nhận."
            if dsh else ""
        )
        raise LLMError(
            f"Provider '{name}' chưa có API key. Vào Cài đặt để nhập, hoặc đặt biến "
            f"{conf.get('api_key_env') or 'API key'}.{hint}"
        )

    style = conf["api_style"]
    use_json = conf.get("json_mode", True) if json_mode is None else json_mode
    temp = conf.get("temperature", 0.9) if temperature is None else temperature
    max_tok = max_tokens or conf.get("max_tokens", 4096)

    last_error: Exception | None = None
    for attempt in range(retries):
        started = time.time()
        try:
            if style == "anthropic":
                result = _call_anthropic(conf, messages, temp, max_tok)
            else:
                result = _call_openai(conf, messages, temp, max_tok, use_json)
            result.update({"provider": name, "data": None, "ms": int((time.time() - started) * 1000)})
            return result
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:600]
            except Exception:  # noqa: BLE001
                pass
            if exc.code in (401, 403):
                raise _auth_error(name, conf, detail) from exc
            last_error = LLMError(f"HTTP {exc.code} từ {name}: {detail or exc.reason}")
            if exc.code in (400, 404, 422):
                raise last_error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = LLMError(f"Lỗi gọi {name}: {exc}")
        time.sleep(1.5 * (attempt + 1))
    raise last_error or LLMError("Gọi LLM thất bại")


def extract_json(text: str) -> Any:
    """Lấy JSON từ câu trả lời (bỏ ``` fences, cắt phần thừa)."""
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.S)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = min([i for i in (raw.find("{"), raw.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise LLMError(f"Model không trả JSON: {text[:300]}")
    opening = raw[start]
    closing = "}" if opening == "{" else "]"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return json.loads(raw[start : i + 1])
    raise LLMError("JSON bị cắt cụt từ model")


def chat_json(messages: list[dict], **kwargs) -> tuple[Any, dict]:
    result = chat(messages, **kwargs)
    try:
        data = extract_json(result["text"])
    except LLMError:
        repair = messages + [
            {"role": "assistant", "content": result["text"][:2000]},
            {"role": "user", "content": "Câu trả lời trên không phải JSON hợp lệ. Chỉ trả lại đúng một object JSON, không giải thích."},
        ]
        result = chat(repair, **kwargs)
        data = extract_json(result["text"])
    result["data"] = data
    return data, result


def test_connection(cfg: dict | None = None, provider: str | None = None) -> tuple[bool, str]:
    cfg = cfg or load_config()
    try:
        name, conf = provider_conf(cfg, provider)
    except LLMError as exc:
        return False, str(exc)
    try:
        res = chat(
            [{"role": "user", "content": "Trả lời đúng một chữ: OK"}],
            cfg=cfg,
            provider=provider,
            max_tokens=16,
            json_mode=False,
            retries=1,
        )
        return True, f"{name}/{res['model']} · key từ {conf.get('key_source_used') or '?'}: {(res['text'] or '').strip()[:60]}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:400]


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text or "") / 3.8))
