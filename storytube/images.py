"""Tạo ảnh nền cho cảnh: ElevenLabs Image (cần gói Pro) -> Pollinations (miễn phí) -> gradient.

ElevenLabs: POST /v1/flows/image -> {id,status}; GET /v1/flows/image/{id} -> content_url.
Pollinations: GET image.pollinations.ai/prompt/<prompt>?width=&height=&model=flux (không cần key).
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import db
from .config import load_config, project_dir


class ImageError(RuntimeError):
    pass


def provider_conf(cfg: dict, name: str = "elevenlabs") -> dict:
    conf = dict(cfg.get("images", {}).get("providers", {}).get(name, {}))
    api_key = conf.get("api_key") or ""
    if not api_key and conf.get("api_key_env"):
        api_key = os.environ.get(conf["api_key_env"], "")
    if not api_key:
        # cùng một key ElevenLabs dùng cho cả giọng đọc và tạo ảnh
        tts_conf = cfg.get("tts", {}).get("providers", {}).get("elevenlabs", {})
        api_key = tts_conf.get("api_key") or ""
        if not api_key and tts_conf.get("api_key_env"):
            api_key = os.environ.get(tts_conf["api_key_env"], "")
    conf["api_key"] = api_key
    conf["name"] = name
    return conf


def has_key(cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    return bool(provider_conf(cfg).get("api_key"))


def check_key(cfg: dict | None = None) -> tuple[bool, str]:
    """Kiểm tra key ElevenLabs thật sự dùng được (không chỉ tồn tại)."""
    cfg = cfg or load_config()
    conf = provider_conf(cfg)
    key = conf.get("api_key") or ""
    if not key:
        return False, "chưa có ElevenLabs key"
    base = (conf.get("base_url") or "https://api.elevenlabs.io/v1").rstrip("/")

    quota = ""
    try:
        with urllib.request.urlopen(
            urllib.request.Request(base + "/user", headers={"xi-api-key": key}), timeout=30
        ) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        sub = data.get("subscription") or {}
        quota = f" · {sub.get('character_count', 0):,}/{sub.get('character_limit', 0):,} ký tự ({sub.get('tier', '?')})"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        if exc.code == 401 and "missing_permissions" in body:
            quota = " · key thiếu scope user_read nên không xem được quota"
        elif exc.code in (401, 403):
            return False, f"key bị từ chối: {body[:200]}"
    except Exception:  # noqa: BLE001
        pass

    # gọi thử 1 từ bằng voice dựng sẵn (rẻ nhất, kiểm tra đúng quyền text_to_speech)
    body = json.dumps({
        "text": "Chào.", "model_id": "eleven_v3", "language_code": "vi",
    }).encode("utf-8")
    req = urllib.request.Request(
        base + "/text-to-speech/onwK4e9ZLuTAKqWW03F9?output_format=mp3_22050_32",
        data=body, headers={"xi-api-key": key, "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            audio = resp.read()
        if len(audio) < 200:
            return False, "TTS trả dữ liệu rỗng"
        return True, f"key hợp lệ · TTS OK{quota}"
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        return False, f"TTS lỗi {exc.code}: {detail}"
    except Exception as exc:  # noqa: BLE001
        return False, f"không gọi được ElevenLabs: {exc}"


# --------------------------------------------------------------------------- #
# ElevenLabs
# --------------------------------------------------------------------------- #
def _eleven_request(url: str, api_key: str, payload: dict | None = None, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"xi-api-key": api_key, "Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _download(url: str, dst: Path, timeout: int = 240) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "storytube/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if len(data) < 512:
        raise ImageError("File ảnh tải về quá nhỏ")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    return len(data)


ASPECTS = {"9:16", "4:5", "1:1", "3:4", "16:9", "4:3", "3:2", "2:3", "auto"}


def _aspect(value: str) -> str:
    return value if value in ASPECTS else "9:16"


def _eleven_generate(prompt: str, dst: Path, cfg: dict, model: str, aspect: str,
                     resolution: str, poll_timeout: int = 240) -> dict:
    conf = provider_conf(cfg)
    if not conf.get("api_key"):
        raise ImageError("Chưa có ElevenLabs API key")
    base = (conf.get("base_url") or "https://api.elevenlabs.io/v1").rstrip("/")
    body = {"model_id": model, "prompt": prompt, "aspect_ratio": _aspect(aspect),
            "resolution": resolution}
    try:
        created = _eleven_request(base + "/flows/image", conf["api_key"], body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if exc.code in (401, 403, 402):
            raise ImageError(f"ElevenLabs không cho tạo ảnh ({exc.code}): {detail}") from exc
        raise ImageError(f"Tạo ảnh lỗi HTTP {exc.code}: {detail}") from exc

    generation_id = created.get("id")
    if not generation_id:
        raise ImageError(f"ElevenLabs không trả id: {created}")
    status = created.get("status", "pending")
    payload: dict = created
    deadline = time.time() + poll_timeout
    while status not in ("completed", "failed") and time.time() < deadline:
        time.sleep(2.5)
        try:
            payload = _eleven_request(f"{base}/flows/image/{generation_id}", conf["api_key"])
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                time.sleep(3)
                continue
            raise ImageError(f"Poll ảnh lỗi HTTP {exc.code}") from exc
        status = payload.get("status", "generating")
    if status != "completed":
        raise ImageError(f"Tạo ảnh thất bại: {payload.get('error_message') or status}")
    url = payload.get("content_url")
    if not url:
        raise ImageError("Ảnh xong nhưng không có content_url")
    mime = payload.get("content_mime_type") or "image/png"
    ext = mimetypes.guess_extension(mime) or ".png"
    if dst.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        dst = dst.with_suffix(ext)
    size = _download(url, dst)
    return {"path": str(dst), "bytes": size, "provider": "elevenlabs",
            "model": model, "generation_id": generation_id, "mime": mime}


# --------------------------------------------------------------------------- #
# Pollinations (miễn phí, không cần key)
# --------------------------------------------------------------------------- #
POLL_SIZES = {
    "9:16": (864, 1536),
    "4:5": (1024, 1280),
    "1:1": (1024, 1024),
    "3:4": (960, 1280),
    "16:9": (1536, 864),
    "4:3": (1280, 960),
    "3:2": (1280, 853),
    "2:3": (853, 1280),
}


def _strip_logo(path: Path) -> None:
    """Pollinations luôn đóng dấu logo ở góc dưới-phải: cắt 7% đáy cho sạch khung."""
    try:
        from . import media

        ffmpeg, _ = media.paths()
        raw = path.with_name(path.stem + ".raw" + path.suffix)
        path.rename(raw)
        media.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw),
            "-vf", "crop=iw:ih*0.93:0:0", "-q:v", "3", str(path),
        ])
        raw.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - cắt lỗi thì giữ ảnh gốc
        raw = path.with_name(path.stem + ".raw" + path.suffix)
        if raw.exists() and not path.exists():
            raw.rename(path)


def _pollinations_generate(prompt: str, dst: Path, aspect: str, model: str = "flux",
                           seed: int | None = None) -> dict:
    width, height = POLL_SIZES.get(_aspect(aspect), (864, 1536))
    params = {
        "width": width, "height": height, "model": model,
        "nologo": "true", "enhance": "false", "safe": "false",
    }
    if seed is not None:
        params["seed"] = seed
    url = (
        "https://image.pollinations.ai/prompt/"
        + urllib.parse.quote(prompt[:1200])
        + "?" + urllib.parse.urlencode(params)
    )
    last: Exception | None = None
    for attempt in range(3):
        try:
            dst = dst.with_suffix(".jpg")
            size = _download(url, dst, timeout=240)
            _strip_logo(dst)
            return {"path": str(dst), "bytes": dst.stat().st_size, "provider": "pollinations",
                    "model": model, "mime": "image/jpeg"}
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(3 + attempt * 3)
    raise ImageError(f"Pollinations lỗi: {last}")


# --------------------------------------------------------------------------- #
# API chung
# --------------------------------------------------------------------------- #
def generate(
    prompt: str,
    dst: Path,
    *,
    cfg: dict | None = None,
    model: str | None = None,
    aspect: str = "9:16",
    resolution: str = "2K",
    provider_order: list[str] | None = None,
) -> dict:
    cfg = cfg or load_config()
    order = provider_order or cfg.get("images", {}).get("provider_order") or ["elevenlabs", "pollinations"]
    model = model or cfg["images"].get("model") or "gemini-3.1-flash-image"
    errors: list[str] = []
    for provider in order:
        try:
            if provider == "elevenlabs":
                return _eleven_generate(prompt, dst, cfg, model, aspect, resolution)
            if provider == "pollinations":
                return _pollinations_generate(prompt, dst, aspect)
            if provider == "gradient":
                raise ImageError("chuyển sang nền gradient")
        except Exception as exc:  # noqa: BLE001 - thử provider kế tiếp
            errors.append(f"{provider}: {exc}")
            continue
    raise ImageError("Không tạo được ảnh. " + " | ".join(errors)[:600])


def build_prompt(scene: dict, project: dict, cfg: dict, aspect: str = "9:16") -> str:
    core = (scene.get("visual_prompt") or "").strip()
    if not core:
        core = (scene.get("narration") or "").strip()
    mood = (scene.get("mood") or "").strip()
    suffix = cfg.get("images", {}).get("style_suffix", "")
    parts = [core]
    if mood:
        parts.append(f"mood: {mood}")
    genre = (project.get("genre") or "").strip()
    if genre:
        parts.append(f"genre: {genre}")
    if aspect == "9:16":
        parts.append("vertical composition with clear negative space in the lower third")
    if suffix:
        parts.append(suffix)
    return ", ".join(p for p in parts if p)


def generate_for_scene(
    scene_id: str,
    *,
    cfg: dict | None = None,
    model: str | None = None,
    aspect: str | None = None,
    resolution: str | None = None,
    force: bool = False,
) -> dict:
    cfg = cfg or load_config()
    scene = db.get("scenes", scene_id)
    if not scene:
        raise ImageError("Không tìm thấy cảnh")
    project = db.get("projects", scene["project_id"])
    if scene.get("art") and not force:
        return {"scene_id": scene_id, "skipped": True, "art": scene["art"]}

    aspect = aspect or cfg["images"].get("aspect_ratio", "9:16")
    resolution = resolution or cfg["images"].get("resolution", "2K")
    prompt = build_prompt(scene, project, cfg, aspect)
    out_dir = project_dir(project["slug"]) / "assets" / "img"
    out_path = out_dir / f"scene-{scene['idx']:02d}-{int(time.time())}.png"
    info = generate(prompt, out_path, cfg=cfg, model=model, aspect=aspect, resolution=resolution)

    rel = Path(info["path"]).relative_to(project_dir(project["slug"])).as_posix()
    db.update("scenes", scene_id, {"art": rel, "updated_at": db.now()})
    db.insert("assets", {
        "id": db.new_id("ast"), "project_id": project["id"], "kind": "image",
        "path": rel, "label": f"cảnh {scene['idx']}",
        "meta": db.dumps({"prompt": prompt, "provider": info.get("provider"),
                          "model": info.get("model"), "mime": info.get("mime")}),
        "created_at": db.now(),
    })
    return {"scene_id": scene_id, "art": rel, "bytes": info["bytes"],
            "provider": info.get("provider"), "model": info.get("model"), "prompt": prompt}


def generate_for_scenes(
    scene_ids: list[str],
    *,
    cfg: dict | None = None,
    model: str | None = None,
    aspect: str | None = None,
    resolution: str | None = None,
    force: bool = False,
    progress=None,
) -> dict:
    cfg = cfg or load_config()
    done, errors = [], []
    for i, sid in enumerate(scene_ids):
        if progress:
            progress(int(95 * i / max(1, len(scene_ids))), f"Tạo ảnh cảnh {i + 1}/{len(scene_ids)}")
        try:
            done.append(generate_for_scene(
                sid, cfg=cfg, model=model, aspect=aspect, resolution=resolution, force=force
            ))
        except Exception as exc:  # noqa: BLE001 - một cảnh lỗi không chặn cả loạt
            errors.append({"scene_id": sid, "error": str(exc)[:300]})
    return {"images": done, "errors": errors}


def videos_aspect(spec: dict) -> str:
    ratios = spec.get("ratios") or ["9:16"]
    return ratios[0] if ratios else "9:16"
