"""TTS đa nhà cung cấp + hồ sơ giọng "trầm ấm" cho tiếng Việt.

Mỗi cảnh được tổng hợp theo từng câu rồi ghép lại: giọng tự nhiên hơn khi đọc cả
đoạn, nhưng vẫn có mốc thời gian chính xác cho phụ đề karaoke.

Provider: edge (miễn phí) · azure · fpt · elevenlabs · openai · viettts (local).
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import media
from .config import load_config
from .textutil import chunk_text, word_timings, words_of


class TTSError(RuntimeError):
    pass


@dataclass
class SynthResult:
    path: str
    duration_ms: int
    provider: str
    voice: str
    words: list[dict] = field(default_factory=list)
    text: str = ""
    meta: dict = field(default_factory=dict)


def _pct(value: str | float | int | None) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return float(re.sub(r"[^0-9.+-]", "", str(value)) or 0)


def _hz(value: str | float | int | None) -> float:
    return _pct(value)


def profile_of(cfg: dict, name: str | None = None) -> tuple[str, dict]:
    tts = cfg.get("tts", {})
    key = name or tts.get("default_profile") or "nam-tram-eleven"
    profiles = tts.get("profiles", {})
    if key not in profiles:
        raise TTSError(f"Không có hồ sơ giọng '{key}'")
    prof = dict(profiles[key])
    prof["name"] = key
    prof.setdefault("provider", "edge")
    # nếu provider chưa có key thì rơi về hồ sơ dự phòng (vd ElevenLabs -> Edge)
    if not provider_ready(cfg, prof["provider"]):
        fallback = prof.get("fallback")
        if fallback and fallback in profiles:
            original = key
            key = fallback
            prof = dict(profiles[fallback])
            prof["name"] = key
            prof.setdefault("provider", "edge")
            prof["_fallback_from"] = original
    return key, prof


def provider_ready(cfg: dict, provider: str) -> bool:
    if provider in ("edge", "google", "viettts"):
        return True
    try:
        return bool(provider_conf(cfg, provider).get("api_key"))
    except Exception:  # noqa: BLE001
        return False


def provider_conf(cfg: dict, provider: str) -> dict:
    conf = dict(cfg.get("tts", {}).get("providers", {}).get(provider, {}))
    api_key = conf.get("api_key") or ""
    if not api_key and conf.get("api_key_env"):
        api_key = os.environ.get(conf["api_key_env"], "")
    conf["api_key"] = api_key
    return conf


def _retry(fn, attempts: int, base_delay: float, label: str):
    last: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            # lỗi quyền/key thì thử lại bao nhiêu lần cũng vô ích
            text = str(exc)
            if "từ chối key" in text or "chưa có API key" in text or "missing the permission" in text:
                break
            if i + 1 >= attempts:
                break
            delay = base_delay * (1.6**i) + random.uniform(0, 0.6)
            time.sleep(min(delay, 12))
    raise TTSError(f"{label} thất bại: {last}") from last


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
def _edge_synth(text: str, voice: str, rate: float, pitch: float, volume: float, dst: Path) -> None:
    import edge_tts

    async def go() -> None:
        kwargs = {}
        if rate:
            kwargs["rate"] = f"{rate:+.0f}%"
        if pitch:
            kwargs["pitch"] = f"{pitch:+.0f}Hz"
        if volume:
            kwargs["volume"] = f"{volume:+.0f}%"
        comm = edge_tts.Communicate(text, voice, **kwargs)
        audio = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        if not audio:
            raise TTSError("Edge TTS không trả âm thanh")
        dst.write_bytes(bytes(audio))

    asyncio.run(go())


def _ssml(text: str, voice: str, rate: float, pitch: float, volume: float) -> str:
    esc = (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return (
        f"<speak version='1.0' xml:lang='vi-VN'>"
        f"<voice name='{voice}'>"
        f"<prosody rate='{rate:+.0f}%' pitch='{pitch:+.0f}Hz' volume='{volume:+.0f}%'>{esc}</prosody>"
        f"</voice></speak>"
    )


def _http_post(url: str, data: bytes, headers: dict, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _azure_synth(cfg: dict, text: str, voice: str, rate: float, pitch: float, volume: float, dst: Path) -> None:
    conf = provider_conf(cfg, "azure")
    if not conf.get("api_key"):
        raise TTSError("Azure chưa có API key")
    region = conf.get("region") or "southeastasia"
    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": conf["api_key"],
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
        "User-Agent": "storytube",
    }
    dst.write_bytes(_http_post(url, _ssml(text, voice, rate, pitch, volume).encode("utf-8"), headers))


def _fpt_synth(cfg: dict, text: str, voice: str, rate: float, dst: Path) -> None:
    conf = provider_conf(cfg, "fpt")
    if not conf.get("api_key"):
        raise TTSError("FPT.AI chưa có API key")
    endpoint = conf.get("endpoint") or "https://api.fpt.ai/hmi/tts/v5"
    speed = max(0, int(round(0 - rate)))  # FPT: speed âm = chậm hơn (-3..3)
    headers = {
        "api_key": conf["api_key"],
        "voice": voice or "minhquan",
        "speed": str(speed),
        "Content-Type": "text/plain; charset=utf-8",
    }
    raw = _http_post(endpoint, text.encode("utf-8"), headers, timeout=60)
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise TTSError(f"FPT trả dữ liệu lạ: {raw[:120]!r}") from exc
    url = payload.get("async") or payload.get("message")
    if not url or not str(url).startswith("http"):
        raise TTSError(f"FPT không trả link audio: {payload}")
    for _ in range(30):
        time.sleep(1.0)
        try:
            with urllib.request.urlopen(url, timeout=45) as resp:
                body = resp.read()
            if body and len(body) > 2048:
                dst.write_bytes(body)
                return
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 429):
                continue
            raise
    raise TTSError("FPT TTS quá thời gian chờ file")


def _eleven_synth(cfg: dict, text: str, voice: str, dst: Path, language: str = "vi",
                  voices: list[str] | None = None) -> str:
    """Trả về voice_id thực sự dùng được (gói Free không dùng được voice thư viện)."""
    conf = provider_conf(cfg, "elevenlabs")
    if not conf.get("api_key"):
        raise TTSError("ElevenLabs chưa có API key")
    model = conf.get("model") or "eleven_v3"
    out_format = conf.get("output_format") or "mp3_44100_128"
    candidates = [voice] + [v for v in (voices or []) if v and v != voice]
    candidates = [c for c in candidates if c] or ["onwK4e9ZLuTAKqWW03F9"]
    body = json.dumps({
        "text": text,
        "model_id": model,
        "language_code": language or "vi",
        "voice_settings": {
            "stability": 0.42,
            "similarity_boost": 0.85,
            "style": 0.22,
            "use_speaker_boost": True,
            "speed": 1.0,
        },
    }).encode("utf-8")

    last_error: Exception | None = None
    for candidate in candidates:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{candidate}?output_format={out_format}"
        try:
            dst.write_bytes(_http_post(url, body, {
                "xi-api-key": conf["api_key"], "Content-Type": "application/json",
            }, timeout=180))
            return candidate
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            last_error = exc
            if exc.code in (401, 403):
                raise TTSError(f"ElevenLabs từ chối key ({exc.code}): {detail}") from exc
            # 402 = voice thư viện cần gói trả phí -> thử voice kế tiếp
            if exc.code == 402 or "library" in detail.lower() or "paid_plan" in detail:
                continue
            raise TTSError(f"ElevenLabs lỗi HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    raise TTSError(
        "ElevenLabs không dùng được voice nào trong danh sách. Nếu đang ở gói Free, "
        "voice thư viện bị chặn — thêm voice dự phòng trong config (fallback_voices). "
        f"Lỗi cuối: {last_error}"
    )


def _openai_synth(cfg: dict, text: str, voice: str, dst: Path) -> None:
    conf = provider_conf(cfg, "openai")
    if not conf.get("api_key"):
        raise TTSError("OpenAI TTS chưa có API key")
    base = (conf.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    body = json.dumps({
        "model": conf.get("model") or "gpt-4o-mini-tts",
        "voice": voice or "onyx",
        "input": text,
        "response_format": "mp3",
        "instructions": "Đọc chậm rãi, trầm, ấm, như kể chuyện đêm khuya cho một người nghe.",
    }).encode("utf-8")
    dst.write_bytes(_http_post(base + "/audio/speech", body, {
        "Authorization": f"Bearer {conf['api_key']}", "Content-Type": "application/json",
    }))


def _viettts_synth(cfg: dict, text: str, voice: str, dst: Path) -> None:
    conf = provider_conf(cfg, "viettts")
    base = (conf.get("base_url") or "http://127.0.0.1:8298").rstrip("/")
    body = json.dumps({"model": "tts-1", "input": text, "voice": voice or "cdteam"}).encode("utf-8")
    dst.write_bytes(_http_post(base + "/v1/audio/speech", body, {
        "Authorization": "Bearer viet-tts", "Content-Type": "application/json",
    }, timeout=180))


def _google_synth(text: str, dst: Path) -> None:
    """Google Translate TTS: miễn phí, không key, chất lượng thấp hơn neural.

    Dùng làm đường dự phòng khi Edge bị chặn. Giới hạn ~180 ký tự mỗi lần gọi.
    """
    pieces, buf = [], ""
    for word in text.split():
        if len(buf) + len(word) + 1 > 170:
            pieces.append(buf)
            buf = word
        else:
            buf = f"{buf} {word}".strip()
    if buf:
        pieces.append(buf)
    audio = bytearray()
    for piece in pieces or [text]:
        query = urllib.parse.quote(piece)
        url = (
            "https://translate.google.com/translate_tts"
            f"?ie=UTF-8&client=tw-ob&tl=vi&ttsspeed=1&q={query}"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://translate.google.com/",
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            audio.extend(resp.read())
    if not audio:
        raise TTSError("Google TTS không trả âm thanh")
    dst.write_bytes(bytes(audio))


def _synth_once(cfg: dict, text: str, prof: dict, dst: Path) -> None:
    provider = prof["provider"]
    voice = prof.get("voice") or ""
    rate = _pct(prof.get("rate"))
    pitch = _hz(prof.get("pitch"))
    volume = _pct(prof.get("volume"))
    if provider == "edge":
        _edge_synth(text, voice or "vi-VN-NamMinhNeural", rate, pitch, volume, dst)
    elif provider == "azure":
        _azure_synth(cfg, text, voice or "vi-VN-NamMinhNeural", rate, pitch, volume, dst)
    elif provider == "fpt":
        _fpt_synth(cfg, text, voice or "minhquan", rate, dst)
    elif provider == "elevenlabs":
        prof["_voice_used"] = _eleven_synth(
            cfg, text, voice, dst, prof.get("language") or "vi",
            prof.get("fallback_voices") or [],
        )
    elif provider == "openai":
        _openai_synth(cfg, text, voice, dst)
    elif provider == "viettts":
        _viettts_synth(cfg, text, voice, dst)
    elif provider == "google":
        _google_synth(text, dst)
    else:
        raise TTSError(f"Provider TTS chưa hỗ trợ: {provider}")


def _adjust(src: Path, dst: Path, rate: float, pitch: float) -> Path:
    """Áp tốc độ/ cao độ cho provider không hỗ trợ (giữ nguyên thời lượng nếu chỉ đổi pitch)."""
    if not rate and not pitch:
        return src
    sr = 48000
    chain = []
    if pitch:
        factor = 2 ** (pitch / 12.0 / 12.0)  # Hz -> xấp xỉ nửa cung
        factor = max(0.85, min(1.15, factor))
        chain.append(f"asetrate={sr}*{factor:.5f},aresample={sr},atempo={1 / factor:.5f}")
    if rate:
        chain.append(f"atempo={max(0.5, min(2.0, 1 + rate / 100)):.5f}")
    ffmpeg, _ = media.paths()
    media.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
               "-af", ",".join(chain), "-ar", str(sr), "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
    return dst


# --------------------------------------------------------------------------- #
# Scene-level synthesis
# --------------------------------------------------------------------------- #
def synthesize_scene(
    text: str,
    out_dir: Path,
    profile_name: str | None = None,
    cfg: dict | None = None,
    gap_ms: int = 70,
) -> SynthResult:
    """Đọc cả một cảnh: tách câu -> synth từng câu -> ghép + mốc thời gian từng từ."""
    cfg = cfg or load_config()
    name, prof = profile_of(cfg, profile_name)
    tts_conf = cfg.get("tts", {})
    attempts = int(tts_conf.get("max_attempts", 8))
    delay = float(tts_conf.get("retry_delay", 2.0))

    out_dir.mkdir(parents=True, exist_ok=True)
    parts = chunk_text(text, 260) or [text]

    def render_parts(profile: dict) -> tuple[list[Path], list[dict], int]:
        wavs: list[Path] = []
        collected: list[dict] = []
        cursor = 0
        total_raw = 0
        for idx, part in enumerate(parts):
            raw = out_dir / f"part{idx:02d}.raw"
            _retry(
                lambda p=part, r=raw: _synth_once(cfg, p, profile, r),
                attempts, delay, f"TTS {profile['provider']}",
            )
            wav = out_dir / f"part{idx:02d}.wav"
            media.to_wav(raw, wav)
            raw_dur = media.duration_ms(wav)
            if not raw_dur:
                raise TTSError(f"File TTS rỗng ở câu {idx + 1}")
            adjusted = _adjust(
                wav, out_dir / f"part{idx:02d}.adj.wav", _pct(profile.get("rate")),
                _hz(profile.get("pitch")) if profile["provider"] not in ("edge", "azure") else 0,
            )
            if adjusted != wav:
                wav = adjusted
                raw_dur = media.duration_ms(wav)
            wavs.append(wav)
            for item in word_timings(part, raw_dur):
                collected.append({"w": item["w"], "s": item["s"] + cursor, "e": item["e"] + cursor})
            cursor += raw_dur + gap_ms
            total_raw += raw_dur
        return wavs, collected, total_raw

    fallback_note = ""
    try:
        wav_parts, words, raw_total = render_parts(prof)
    except TTSError as exc:
        fb = prof.get("fallback")
        if not fb or fb == name:
            raise
        fb_name, fb_prof = profile_of(cfg, fb)
        wav_parts, words, raw_total = render_parts(fb_prof)
        fallback_note = f"{name} lỗi ({str(exc)[:120]}) → dùng {fb_name}"
        name, prof = fb_name, fb_prof

    final = out_dir / "scene.wav"
    media.concat_wav(wav_parts, final, workdir=out_dir)
    total = media.duration_ms(final) or raw_total

    # hậu xử lý giọng (trầm ấm) sau khi ghép để nhất quán toàn cảnh
    post = prof.get("post") or "warm"
    if post != "none":
        processed = out_dir / "scene.post.wav"
        try:
            media.post_voice(final, processed, post)
            final = processed
        except media.MediaError:
            pass

    total = media.duration_ms(final) or total
    for w in words:
        w["e"] = min(w["e"], total)
    (out_dir / "scene.words.json").write_text(
        json.dumps(words, ensure_ascii=False), encoding="utf-8"
    )
    from .textutil import estimate_speech_ms

    return SynthResult(
        path=str(final),
        duration_ms=total,
        provider=prof["provider"],
        voice=prof.get("_voice_used") or prof.get("voice", ""),
        words=words,
        text=text,
        meta={"profile": name, "sentences": len(parts),
              "estimate_ms": estimate_speech_ms(text, _pct(prof.get("rate"))),
              "fallback": fallback_note},
    )


def list_edge_voices() -> list[dict]:
    import edge_tts

    async def go():
        return await edge_tts.list_voices()

    try:
        voices = asyncio.run(go())
    except Exception:  # noqa: BLE001
        return []
    return [
        {"name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"]}
        for v in voices
        if v["Locale"].startswith("vi")
    ]


def preview(text: str, dst: Path, profile: str | None = None) -> SynthResult:
    return synthesize_scene(text, dst.parent, profile_name=profile)
