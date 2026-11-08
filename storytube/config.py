"""Cấu hình: mặc định -> data/config.json -> biến môi trường."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("STORYTUBE_DATA") or APP_ROOT / "data")
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    "server": {"host": "127.0.0.1", "port": 8790},
    "llm": {
        "default": "deepseek",
        "providers": {
            "deepseek": {
                "label": "DeepSeek (như DSH dùng)",
                # DSH gọi DeepSeek qua wire Anthropic Messages; endpoint này cũng
                # nhận key sk-... chuẩn của platform.deepseek.com
                "base_url": "https://api.deepseek.com/anthropic",
                "api_style": "anthropic",
                "key_source": "auto",      # auto | config | env | dsh
                "api_key": "",
                "api_key_env": "DEEPSEEK_API_KEY",
                "model": "deepseek-chat",
                "temperature": 0.9,
                "max_tokens": 4096,
                "json_mode": True,
            },
            "deepseek-openai": {
                "label": "DeepSeek (wire OpenAI)",
                "base_url": "https://api.deepseek.com/v1",
                "api_style": "openai",
                "key_source": "auto",
                "api_key": "",
                "api_key_env": "DEEPSEEK_API_KEY",
                "model": "deepseek-chat",
                "temperature": 0.9,
                "max_tokens": 4096,
                "json_mode": True,
            },
            "openai": {
                "label": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "api_key": "",
                "api_key_env": "OPENAI_API_KEY",
                "model": "gpt-4.1-mini",
                "temperature": 0.9,
                "max_tokens": 4096,
                "json_mode": True,
            },
            "openrouter": {
                "label": "OpenRouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "",
                "api_key_env": "OPENROUTER_API_KEY",
                "model": "deepseek/deepseek-chat",
                "temperature": 0.9,
                "max_tokens": 4096,
                "json_mode": True,
            },
            "ollama": {
                "label": "Ollama (local)",
                "base_url": "http://localhost:11434/v1",
                "api_key": "",
                "api_key_env": "",
                "model": "qwen3:8b",
                "temperature": 0.9,
                "max_tokens": 4096,
                "json_mode": False,
            },
            "custom": {
                "label": "OpenAI-compatible khác",
                "base_url": "",
                "api_key": "",
                "api_key_env": "",
                "model": "",
                "temperature": 0.9,
                "max_tokens": 4096,
                "json_mode": True,
            },
        },
    },
    "tts": {
        "default_profile": "nam-tram-eleven",
        "profiles": {
            "nam-tram-eleven": {
                "label": "ElevenLabs · Sang Trương (nam trầm, kể chuyện)",
                "provider": "elevenlabs",
                "voice": "7WNWm0yUcEolHsfg5Bhk",
                "fallback_voices": ["onwK4e9ZLuTAKqWW03F9", "pNInz6obpgDQGcFmaJgB"],
                "rate": "-4%",
                "pitch": "0",
                "volume": "+0%",
                "post": "warm",
                "language": "vi",
                "fallback": "nam-tram-am",
                "provider_voice": "7WNWm0yUcEolHsfg5Bhk",
            },
            "nam-tram-eleven-2": {
                "label": "ElevenLabs · Trần Thanh (nam trầm, chậm)",
                "provider": "elevenlabs",
                "voice": "kPNz4WRTiKDplS7jAwHu",
                "fallback_voices": ["pNInz6obpgDQGcFmaJgB", "onwK4e9ZLuTAKqWW03F9"],
                "rate": "-6%",
                "pitch": "0",
                "volume": "+0%",
                "post": "warm-deep",
                "language": "vi",
                "fallback": "nam-tram-am",
                "provider_voice": "kPNz4WRTiKDplS7jAwHu",
            },
            "nam-tram-am" : {
                "label": "Nam trầm ấm (Edge, miễn phí)",
                "provider": "edge",
                "voice": "vi-VN-NamMinhNeural",
                "rate": "-6%",
                "pitch": "-14Hz",
                "volume": "+0%",
                "post": "warm-deep",
                "provider_voice": "",
            },
            "nam-truyen-cam": {
                "label": "Nam truyền cảm (kể chuyện)",
                "provider": "edge",
                "voice": "vi-VN-NamMinhNeural",
                "rate": "-2%",
                "pitch": "-8Hz",
                "volume": "+0%",
                "post": "warm",
                "provider_voice": "",
            },
            "nu-nhe-nhang": {
                "label": "Nữ nhẹ nhàng",
                "provider": "edge",
                "voice": "vi-VN-HoaiMyNeural",
                "rate": "-4%",
                "pitch": "-4Hz",
                "volume": "+0%",
                "post": "warm",
                "provider_voice": "",
            },
            "fpt-minhquan": {
                "label": "FPT Minh Quân (nam trầm)",
                "provider": "fpt",
                "voice": "minhquan",
                "rate": "0",
                "pitch": "0",
                "volume": "+0%",
                "post": "warm-deep",
                "provider_voice": "minhquan",
            },
            "azure-namminh": {
                "label": "Azure Nam Minh",
                "provider": "azure",
                "voice": "vi-VN-NamMinhNeural",
                "rate": "-6%",
                "pitch": "-12Hz",
                "volume": "+0%",
                "post": "warm-deep",
                "provider_voice": "vi-VN-NamMinhNeural",
            },
            "viet-google": {
                "label": "Google TTS (dự phòng, không cần key)",
                "provider": "google",
                "voice": "vi",
                "rate": "-8%",
                "pitch": "-10Hz",
                "volume": "+0%",
                "post": "warm",
                "provider_voice": "",
            },
        },
        "providers": {
            "edge": {"label": "Microsoft Edge (miễn phí)", "api_key": "", "region": "southeastasia"},
            "azure": {"label": "Azure Speech", "api_key": "", "api_key_env": "AZURE_SPEECH_KEY",
                      "region": "southeastasia"},
            "fpt": {"label": "FPT.AI", "api_key": "", "api_key_env": "FPT_TTS_KEY",
                    "endpoint": "https://api.fpt.ai/hmi/tts/v5"},
            "elevenlabs": {"label": "ElevenLabs", "api_key": "", "api_key_env": "ELEVENLABS_API_KEY",
                           "model": "eleven_v3", "output_format": "mp3_44100_128"},
            "openai": {"label": "OpenAI TTS", "api_key": "", "api_key_env": "OPENAI_API_KEY",
                       "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini-tts"},
            "viettts": {"label": "VietTTS (local server)", "base_url": "http://127.0.0.1:8298"},
            "google": {"label": "Google Translate TTS (miễn phí, dự phòng)"},
        },
        "max_attempts": 8,
        "retry_delay": 2.0,
    },
    "images": {
        "provider": "elevenlabs",
        "provider_order": ["elevenlabs", "pollinations"],
        "model": "gemini-3.1-flash-image",
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "style_suffix": (
            "cinematic film still, 35mm, shallow depth of field, volumetric light, "
            "moody color grade, subtle film grain, Vietnamese setting, no text, no watermark"
        ),
        "providers": {
            "elevenlabs": {
                "label": "ElevenLabs Image (Flows)",
                "base_url": "https://api.elevenlabs.io/v1",
                "api_key": "",
                "api_key_env": "ELEVENLABS_API_KEY",
                "models": [
                    "gemini-3.1-flash-image",
                    "gemini-3-pro-image",
                    "bytedance-seedream-5-lite",
                    "gpt-image-2",
                ],
            }
        },
    },
    "render": {
        "fps": 30,
        "crf": 20,
        "preset": "medium",
        "pix_fmt": "yuv420p",
        "audio_bitrate": "192k",
        "sample_rate": 48000,
        "scene_gap_ms": 260,
        "min_scene_ms": 1800,
        "tail_ms": 380,
        "bgm_gain": 0.14,
        "loudness": {"I": -14.0, "TP": -1.5, "LRA": 11.0},
        "fontsdir": "C:\\Windows\\Fonts",
        "ratios": {
            "9:16": {"w": 1080, "h": 1920, "label": "TikTok / Reels / Shorts",
                     "safe": {"top": 150, "bottom": 420, "side": 96}},
            "4:5": {"w": 1080, "h": 1350, "label": "Instagram feed",
                    "safe": {"top": 90, "bottom": 190, "side": 64}},
            "1:1": {"w": 1080, "h": 1080, "label": "Vuông",
                    "safe": {"top": 80, "bottom": 150, "side": 64}},
            "3:4": {"w": 1080, "h": 1440, "label": "Pinterest / Tablet",
                    "safe": {"top": 110, "bottom": 220, "side": 72}},
            "16:9": {"w": 1920, "h": 1080, "label": "YouTube / Facebook",
                     "safe": {"top": 70, "bottom": 110, "side": 90}},
        },
    },
    "background": {
        # thư mục chứa video nền (tương đối so với DATA_DIR)
        "videos_dir": "assets/videos",
        "mode": "video",          # video | image | gradient
        "source": "random",       # random | fixed
        "file": "",
        "overlay_color": "#000000",
        "overlay_opacity": 0.55,
        "force": True,            # video nền thắng ảnh cảnh (nếu mode=video)
    },
    "caption": {
        "name": "karaoke",
        "position": "tiktok",     # tiktok | youtube | center | upper
        "font": "Arial",
    },
    "analysis": {
        "target_seconds": 90,
        "syllables_per_second": 4.15,
        "syllables_per_scene": 30,
        "min_scenes": 3,
        "max_scenes": 24,
        "min_scene_seconds": 2.6,
    },
    "ui": {"level": 3, "language": "vi"},
}

_ENV_KEYS = {
    "STORYTUBE_PORT": ("server", "port", int),
    "STORYTUBE_HOST": ("server", "host", str),
    "STORYTUBE_LEVEL": ("ui", "level", int),
}


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> dict[str, Any]:
    cfg = copy.deepcopy(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg = _deep_merge(cfg, json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:  # pragma: no cover - config typo
            raise SystemExit(f"config.json lỗi JSON: {exc}") from exc
    for env, (section, key, cast) in _ENV_KEYS.items():
        if os.environ.get(env):
            cfg[section][key] = cast(os.environ[env])
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def ensure_config() -> dict[str, Any]:
    """Tạo config.json lần đầu để người dùng thấy chỗ điền API key."""
    if not CONFIG_PATH.exists():
        save_config(DEFAULTS)
    return load_config()


def masked(cfg: dict[str, Any]) -> dict[str, Any]:
    """Bản config an toàn để trả về UI (không lộ key)."""
    out = copy.deepcopy(cfg)
    for provider in out.get("llm", {}).get("providers", {}).values():
        if provider.get("api_key"):
            provider["has_key"] = True
            provider["api_key"] = "***"
    for provider in out.get("tts", {}).get("providers", {}).values():
        if provider.get("api_key"):
            provider["has_key"] = True
            provider["api_key"] = "***"
    for provider in out.get("images", {}).get("providers", {}).values():
        if provider.get("api_key"):
            provider["has_key"] = True
            provider["api_key"] = "***"
    bad = _bad_keys(cfg)
    if bad:
        out["_warnings"] = bad
    return out


def _bad_keys(cfg: dict) -> list[str]:
    out = []
    dsh = read_dsh_token()
    for name, conf in cfg.get("llm", {}).get("providers", {}).items():
        key = conf.get("api_key") or ""
        if key and dsh and key == dsh:
            out.append(
                f"Provider LLM '{name}' đang dùng token đăng nhập của DeepSeek Harness — "
                "DeepSeek API công khai từ chối token này (401). Dán key sk-... của "
                "platform.deepseek.com vào Cài đặt."
            )
    return out


def read_dsh_token() -> str:
    """Đọc token đăng nhập DeepSeek mà DSH đang dùng (nếu có).

    Token này là phiên đăng nhập của app, KHÔNG phải API key của
    platform.deepseek.com — API công khai sẽ trả 401. Hàm vẫn đọc để hiển thị
    và để người dùng biết vì sao cần dán key riêng.
    """
    path = Path(os.environ.get("DSH_CREDENTIALS") or Path.home() / ".dsh" / ".credentials.yaml")
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = re.search(r"^\s*token:\s*(\S+)\s*$", text, re.MULTILINE)
    return match.group(1) if match else ""


def save_keys(deepseek: str = "", elevenlabs: str = "", image: str = "") -> dict:
    cfg = load_config()
    if deepseek:
        for name in ("deepseek", "deepseek-openai"):
            cfg["llm"]["providers"][name]["api_key"] = deepseek
        cfg["llm"]["default"] = "deepseek"
    if elevenlabs:
        cfg["tts"]["providers"]["elevenlabs"]["api_key"] = elevenlabs
        cfg["images"]["providers"]["elevenlabs"]["api_key"] = elevenlabs
        cfg["tts"]["default_profile"] = "nam-tram-eleven"
    if image:
        cfg["images"]["providers"]["elevenlabs"]["api_key"] = image
    save_config(cfg)
    return cfg


def find_ffmpeg(cfg: dict[str, Any] | None = None) -> dict[str, str]:
    """Tìm ffmpeg/ffprobe: env -> .tools -> PATH. Trả {'ffmpeg','ffprobe','version'}."""
    cfg = cfg or load_config()
    explicit = os.environ.get("STORYTUBE_FFMPEG") or cfg.get("paths", {}).get("ffmpeg", "")
    candidates: list[Path] = []
    if explicit:
        p = Path(explicit)
        candidates.append(p if p.suffix.lower() == ".exe" else p / "ffmpeg.exe")
    candidates += [
        APP_ROOT.parent / ".tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
        APP_ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
    ]
    for name in ("ffmpeg", "ffmpeg.exe"):
        hit = shutil.which(name)
        if hit:
            candidates.append(Path(hit))
    for cand in candidates:
        if cand.exists():
            probe = cand.with_name("ffprobe.exe")
            if not probe.exists():
                alt = shutil.which("ffprobe")
                probe = Path(alt) if alt else probe
            return {"ffmpeg": str(cand), "ffprobe": str(probe)}
    return {"ffmpeg": "", "ffprobe": ""}


def require_ffmpeg(cfg: dict[str, Any] | None = None) -> tuple[str, str]:
    paths = find_ffmpeg(cfg)
    if not paths["ffmpeg"]:
        raise RuntimeError(
            "Không tìm thấy ffmpeg. Đặt biến STORYTUBE_FFMPEG trỏ tới ffmpeg.exe "
            "hoặc cài vào C:\\Works\\MMO\\.tools\\ffmpeg\\bin\\ffmpeg.exe"
        )
    return paths["ffmpeg"], paths["ffprobe"]


def project_dir(slug: str) -> Path:
    d = DATA_DIR / "projects" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d
