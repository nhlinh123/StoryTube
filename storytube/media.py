"""Lớp mỏng quanh ffmpeg/ffprobe: mọi thứ chạy qua file log, không dùng pipe.

Sandbox của DSH chặn pipe stdio của tiến trình con, nên ở đây luôn redirect
stdout/stderr ra file và đọc lại — chạy được cả trong lẫn ngoài sandbox.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

from .config import DATA_DIR, find_ffmpeg, load_config


def log_dir() -> Path:
    """Thư mục log đi theo DATA_DIR (đổi STORYTUBE_DATA là đổi luôn chỗ ghi log)."""
    path = DATA_DIR / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


class MediaError(RuntimeError):
    pass


def paths() -> tuple[str, str]:
    cfg = load_config()
    found = find_ffmpeg(cfg)
    if not found["ffmpeg"]:
        raise MediaError("Chưa có ffmpeg (đặt STORYTUBE_FFMPEG hoặc .tools/ffmpeg/bin/ffmpeg.exe)")
    return found["ffmpeg"], found["ffprobe"]


def run(args: list[str], log_path: Path | None = None, cwd: Path | None = None, timeout: int = 3600) -> str:
    """Chạy ffmpeg, trả về log. Ném MediaError nếu exit code != 0."""
    log_path = log_path or (log_dir() / f"ffmpeg-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        log.write(" ".join(args) + "\n\n")
        log.flush()
        try:
            proc = subprocess.run(
                args,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=str(cwd) if cwd else None,
                timeout=timeout,
            )
            code = proc.returncode
        except subprocess.TimeoutExpired as exc:
            raise MediaError(f"ffmpeg quá thời gian ({timeout}s): {exc}") from exc
    text = log_path.read_text(encoding="utf-8", errors="replace")
    text += f"\n[exit {code} in {time.time() - started:.1f}s]"
    if code != 0:
        tail = "\n".join(text.strip().splitlines()[-25:])
        raise MediaError(f"ffmpeg lỗi (xem {log_path.name}):\n{tail}")
    return text


def probe(path: str | Path) -> dict:
    """Trả {duration_ms, width, height, fps, has_audio, audio_rate}."""
    _, ffprobe = paths()
    target = Path(path)
    if not target.exists():
        return {"duration_ms": 0, "width": 0, "height": 0, "fps": 0.0, "has_audio": False}
    log = log_dir() / f"probe-{os.getpid()}.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    args = [
        ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(target),
    ]
    with open(log, "w", encoding="utf-8") as fh:
        subprocess.run(args, stdout=fh, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=120)
    try:
        data = json.loads(log.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {"duration_ms": 0, "width": 0, "height": 0, "fps": 0.0, "has_audio": False}
    out: dict = {"duration_ms": 0, "width": 0, "height": 0, "fps": 0.0, "has_audio": False, "audio_rate": 0}
    fmt = data.get("format") or {}
    if fmt.get("duration"):
        out["duration_ms"] = int(float(fmt["duration"]) * 1000)
    for stream in data.get("streams") or []:
        if stream.get("codec_type") == "video" and not out["width"]:
            out["width"] = int(stream.get("width") or 0)
            out["height"] = int(stream.get("height") or 0)
            rate = stream.get("avg_frame_rate") or "0/1"
            try:
                num, den = rate.split("/")
                out["fps"] = round(float(num) / float(den), 3) if float(den) else 0.0
            except (ValueError, ZeroDivisionError):
                out["fps"] = 0.0
            if not out["duration_ms"] and stream.get("duration"):
                out["duration_ms"] = int(float(stream["duration"]) * 1000)
        elif stream.get("codec_type") == "audio":
            out["has_audio"] = True
            out["audio_rate"] = int(stream.get("sample_rate") or 0)
    return out


def duration_ms(path: str | Path) -> int:
    return probe(path)["duration_ms"]


def _cfg():
    return load_config()


def to_wav(src: str | Path, dst: str | Path, sr: int | None = None, channels: int = 1) -> str:
    sr = sr or _cfg()["render"]["sample_rate"]
    ffmpeg, _ = paths()
    run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-vn", "-ar", str(sr), "-ac", str(channels), "-c:a", "pcm_s16le", str(dst),
    ])
    return str(dst)


def silence(duration_ms_value: int, dst: str | Path, sr: int | None = None) -> str:
    sr = sr or _cfg()["render"]["sample_rate"]
    ffmpeg, _ = paths()
    run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=r={sr}:cl=mono",
        "-t", f"{max(1, duration_ms_value) / 1000:.3f}", "-c:a", "pcm_s16le", str(dst),
    ])
    return str(dst)


VOICE_POST = {
    # hạ giọng ~1,2 cung rồi trả lại tốc độ, thêm hơi ấm ở 110Hz và bớt "ù" ở 400Hz
    "warm-deep": (
        "asetrate={sr}*0.930,aresample={sr},atempo=1.0753,"
        "highpass=f=55,"
        "equalizer=f=110:width_type=o:width=1.4:g=4.5,"
        "equalizer=f=380:width_type=o:width=1.0:g=-2.0,"
        "equalizer=f=3000:width_type=o:width=1.2:g=-1.5,"
        "acompressor=threshold=0.10:ratio=3.2:attack=8:release=180:makeup=1.4"
    ),
    "warm": (
        "highpass=f=60,"
        "equalizer=f=150:width_type=o:width=1.5:g=2.6,"
        "equalizer=f=3200:width_type=o:width=1.4:g=-1.2,"
        "acompressor=threshold=0.12:ratio=2.6:attack=10:release=200:makeup=1.3"
    ),
    "bright": (
        "highpass=f=70,equalizer=f=2500:width_type=o:width=1.2:g=2.0,"
        "acompressor=threshold=0.14:ratio=2.2:attack=10:release=160"
    ),
    "none": "",
}


def post_voice(src: str | Path, dst: str | Path, preset: str = "warm-deep") -> str:
    chain = VOICE_POST.get(preset, "")
    ffmpeg, _ = paths()
    sr = _cfg()["render"]["sample_rate"]
    if not chain:
        return to_wav(src, dst, sr=sr)
    chain = chain.format(sr=sr) + f",aresample={sr}"
    run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-vn", "-af", chain, "-ar", str(sr), "-ac", "1", "-c:a", "pcm_s16le", str(dst),
    ])
    return str(dst)


def pad_to(src: str | Path, dst: str | Path, target_ms: int, lead_ms: int = 120) -> str:
    """Đệm im lặng đầu/cuối để cảnh khớp timeline."""
    sr = _cfg()["render"]["sample_rate"]
    ffmpeg, _ = paths()
    total = max(1, target_ms) / 1000
    lead = max(0, lead_ms) / 1000
    run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-af", f"adelay={int(lead * 1000)}|{int(lead * 1000)},apad,atrim=0:{total:.3f}",
        "-ar", str(sr), "-ac", "1", "-c:a", "pcm_s16le", str(dst),
    ])
    return str(dst)


def concat_wav(files: list[str | Path], dst: str | Path, workdir: Path | None = None) -> str:
    if not files:
        raise MediaError("Không có file âm thanh để ghép")
    sr = _cfg()["render"]["sample_rate"]
    ffmpeg, _ = paths()
    workdir = workdir or Path(dst).parent
    listfile = Path(workdir) / f"concat-{int(time.time() * 1000)}.txt"
    listfile.write_text(
        "\n".join(f"file '{Path(f).resolve().as_posix()}'" for f in files), encoding="utf-8"
    )
    run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-ar", str(sr), "-ac", "1", "-c:a", "pcm_s16le", str(dst),
    ])
    return str(dst)


def soundtrack(
    voice_wav: str | Path,
    total_ms: int,
    dst: str | Path,
    bgm: str | Path | None = None,
    bgm_gain: float = 0.14,
) -> str:
    """Ghép giọng + nhạc nền (ducking) + chuẩn hoá loudness."""
    cfg = _cfg()
    sr = cfg["render"]["sample_rate"]
    loud = cfg["render"]["loudness"]
    ffmpeg, _ = paths()
    norm = f"loudnorm=I={loud['I']}:TP={loud['TP']}:LRA={loud['LRA']}"
    if bgm and Path(bgm).exists():
        filt = (
            f"[0:a]aresample={sr},aformat=channel_layouts=mono[voice];"
            f"[1:a]aresample={sr},aformat=channel_layouts=mono,volume={bgm_gain}[bg];"
            f"[bg][voice]sidechaincompress=threshold=0.03:ratio=12:attack=15:release=350[duck];"
            f"[voice][duck]amix=inputs=2:duration=first:dropout_transition=0,{norm}[out]"
        )
        run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(voice_wav), "-stream_loop", "-1", "-i", str(bgm),
            "-filter_complex", filt, "-map", "[out]", "-t", f"{total_ms / 1000:.3f}",
            "-ar", str(sr), "-ac", "1", "-c:a", "pcm_s16le", str(dst),
        ])
    else:
        run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(voice_wav), "-af", f"aresample={sr},{norm}",
            "-ar", str(sr), "-ac", "1", "-c:a", "pcm_s16le", str(dst),
        ])
    return str(dst)


def thumbnail(video: str | Path, dst: str | Path, at_ms: int = 1200) -> str:
    ffmpeg, _ = paths()
    run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{at_ms / 1000:.2f}",
        "-i", str(video), "-frames:v", "1", "-q:v", "2", str(dst),
    ])
    return str(dst)


def which_ffmpeg_version() -> str:
    try:
        ffmpeg, _ = paths()
    except MediaError:
        return ""
    log = log_dir() / "version.log"
    with open(log, "w", encoding="utf-8") as fh:
        subprocess.run([ffmpeg, "-version"], stdout=fh, stderr=subprocess.STDOUT,
                       stdin=subprocess.DEVNULL, timeout=30)
    first = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return first[0] if first else ""


def copy_or_link(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dst.resolve():
        shutil.copyfile(src, dst)
    return dst


def rms_peak(path: str | Path) -> float:
    """Đo peak đơn giản bằng ffmpeg volumedetect (dùng cho cảnh báo)."""
    ffmpeg, _ = paths()
    log = log_dir() / f"vol-{os.getpid()}.log"
    with open(log, "w", encoding="utf-8") as fh:
        subprocess.run([ffmpeg, "-hide_banner", "-i", str(path), "-af", "volumedetect",
                        "-f", "null", "-"], stdout=fh, stderr=subprocess.STDOUT,
                       stdin=subprocess.DEVNULL, timeout=120)
    text = log.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if "max_volume" in line:
            try:
                return float(line.split("max_volume:")[1].split("dB")[0].strip())
            except (IndexError, ValueError):
                return 0.0
    return 0.0


def seconds(ms: int) -> float:
    return round(max(0, ms) / 1000.0, 3)


def even(value: int) -> int:
    return int(value) - (int(value) % 2)


def fit_cover(src_w: int, src_h: int, dst_w: int, dst_h: int) -> tuple[int, int]:
    """Tỉ lệ crop cover để lấp đầy khung."""
    scale = max(dst_w / max(1, src_w), dst_h / max(1, src_h))
    return math.ceil(src_w * scale), math.ceil(src_h * scale)
