"""Dựng video: cảnh -> khung hình -> phụ đề -> trộn tiếng -> nhiều tỉ lệ."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from pathlib import Path

from . import db, media
from .config import load_config, project_dir
from .render_captions import CaptionStyle, build_ass, load_words, write_ass
from .textutil import estimate_speech_ms

MOODS = {
    "lanh": ("0x1b2f4a", "0x0d1622", "0x24405e", "0x05080e"),
    "toi": ("0x1a2029", "0x0b0f14", "0x232b36", "0x050608"),
    "am": ("0x3a2412", "0x1a0f07", "0x54331a", "0x0a0503"),
    "nong": ("0x451810", "0x1e0906", "0x5e2415", "0x0f0403"),
    "buon": ("0x202c40", "0x0f1622", "0x2c3d56", "0x06080d"),
    "tinh": ("0x24404a", "0x101c22", "0x2f515c", "0x070d0f"),
    "hung": ("0x3d1018", "0x1a0508", "0x56161f", "0x0c0203"),
    "mo": ("0x332a4d", "0x171226", "0x453a66", "0x0a0711"),
}
DEFAULT_MOOD = ("0x1a2740", "0x0b1119", "0x223451", "0x05070c")


def mood_colors(mood: str) -> tuple[str, ...]:
    text = (mood or "").lower()
    for key, value in MOODS.items():
        if key in text:
            return value
    return DEFAULT_MOOD


def dims(ratio: dict, quality: str = "high") -> tuple[int, int]:
    w, h = int(ratio["w"]), int(ratio["h"])
    if quality == "draft":
        return media.even(int(w * 0.66)), media.even(int(h * 0.66))
    if quality == "4k":
        return media.even(int(w * 1.5)), media.even(int(h * 1.5))
    return media.even(w), media.even(h)


def scene_timing(scenes: list[dict], cfg: dict, rate_pct: float = 0.0) -> list[dict]:
    """Gắn start_ms/duration_ms cho từng cảnh dựa trên audio thật (hoặc ước lượng)."""
    tail = int(cfg["render"].get("tail_ms", 380))
    min_ms = int(cfg["render"].get("min_scene_ms", 1800))
    out, cursor = [], 0
    for idx, scene in enumerate(scenes):
        audio_ms = 0
        if scene.get("audio_path"):
            path = Path(scene["audio_path"])
            if path.exists():
                audio_ms = media.duration_ms(path)
        if not audio_ms:
            audio_ms = estimate_speech_ms(scene.get("narration", ""), rate_pct)
        duration = max(min_ms, audio_ms + tail)
        words = load_words(scene.get("words"))
        if words:
            last = max(int(w.get("e", 0)) for w in words)
            duration = max(duration, last + 260)
        else:
            # chưa có audio: rải từ theo ước lượng để xem trước phụ đề
            from .textutil import word_timings

            words = word_timings(scene.get("narration", ""), audio_ms)
        out.append({
            "id": scene.get("id") or f"s{idx}",
            "idx": idx,
            "start_ms": cursor,
            "duration_ms": duration,
            "audio_ms": audio_ms,
            "words": words,
            "narration": scene.get("narration", ""),
            "on_screen": scene.get("on_screen", ""),
            "mood": scene.get("mood", ""),
            "art": scene.get("art", ""),
            "title": scene.get("title", ""),
            "audio_path": scene.get("audio_path", ""),
        })
        cursor += duration
    return out


def _art_path(project: dict, scene: dict) -> Path | None:
    art = (scene.get("art") or "").strip()
    if not art:
        return None
    path = Path(art)
    if not path.is_absolute():
        path = project_dir(project["slug"]) / art
    return path if path.exists() else None


VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v")


def background_videos(cfg: dict | None = None) -> list[Path]:
    """Danh sách video nền trong thư mục data/assets/videos (hoặc cấu hình khác)."""
    cfg = cfg or load_config()
    rel = (cfg.get("background") or {}).get("videos_dir") or "assets/videos"
    root = Path(rel)
    if not root.is_absolute():
        from .config import DATA_DIR

        root = DATA_DIR / root
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT)


def pick_background(spec: dict, scene: dict, cfg: dict, videos: list[Path] | None = None) -> Path | None:
    """Chọn video nền cho cảnh: cố định một file, hoặc random nhưng ổn định theo id cảnh."""
    bg = spec.get("background") or {}
    if (bg.get("mode") or "gradient") != "video":
        return None
    videos = videos if videos is not None else background_videos(cfg)
    if not videos:
        return None
    if bg.get("source") == "fixed" and bg.get("file"):
        for path in videos:
            if path.name == bg["file"]:
                return path
        return None
    # xoay vòng theo số thứ tự cảnh: luôn khác cảnh trước, và ổn định khi render lại
    idx = int(scene.get("idx") or 0)
    digest = int(hashlib.md5(str(spec.get("_seed") or "").encode("utf-8")).hexdigest(), 16) if spec.get("_seed") else 0
    return videos[(idx + digest) % len(videos)]


def _overlay_filter(spec: dict) -> str:
    """Lớp phủ màu (tối/sáng) để chữ nổi trên video nền."""
    overlay = spec.get("overlay") or {}
    try:
        opacity = float(overlay.get("opacity", 0))
    except (TypeError, ValueError):
        opacity = 0.0
    if opacity <= 0:
        return ""
    color = str(overlay.get("color") or "#000000").lstrip("#")
    if len(color) != 6:
        color = "000000"
    return f",drawbox=x=0:y=0:w=iw:h=ih:color=0x{color}@{min(opacity, 1):.2f}:t=fill"


def _scene_visual(scene: dict, project: dict, out: Path, w: int, h: int, fps: int,
                  quality: str, log: Path, spec: dict | None = None,
                  cfg: dict | None = None) -> str:
    """Một cảnh im lặng, đúng độ dài, đúng khung."""
    cfg = cfg or load_config()
    spec = spec or {}
    ffmpeg, _ = media.paths()
    dur = scene["duration_ms"] / 1000.0
    preset = "veryfast" if quality == "draft" else cfg["render"]["preset"]
    crf = 26 if quality == "draft" else cfg["render"]["crf"]
    art = _art_path(project, scene)
    mode = (spec.get("background") or {}).get("mode") or ("image" if art else "gradient")
    overlay = _overlay_filter(spec)
    bg_video = pick_background({**spec, "background": {**(spec.get("background") or {}), "mode": mode}}, scene, cfg) \
        if mode == "video" else None

    common_out = [
        "-an", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-r", str(fps), "-t", f"{dur:.3f}",
        "-movflags", "+faststart", str(out),
    ]

    if bg_video:
        # video nền: lặp/cắt đúng độ dài cảnh, tắt tiếng gốc, phủ màu nếu có
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,fps={fps}{overlay}"
        )
        media.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-stream_loop", "-1", "-i", str(bg_video),
            "-vf", vf, *common_out,
        ], log_path=log)
        return str(out)

    is_video = bool(art and art.suffix.lower() in VIDEO_EXT and mode != "gradient")
    if art and is_video:
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,fps={fps}{overlay}"
        )
        media.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-stream_loop", "-1", "-i", str(art),
            "-vf", vf, *common_out,
        ], log_path=log)
        return str(out)

    if art and mode != "gradient":
        # ảnh: Ken Burns xen kẽ phóng to / thu nhỏ
        zoom_in = scene["idx"] % 2 == 0
        if zoom_in:
            zexpr = "'min(1.001+0.00035*on,1.14)'"
        else:
            zexpr = "'max(1.14-0.00035*on,1.001)'"
        big_w, big_h = int(w * 1.16), int(h * 1.16)
        vf = (
            f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase,"
            f"crop={big_w}:{big_h},fps={fps},"
            f"zoompan=z={zexpr}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={w}x{h}:fps={fps},setsar=1{overlay}"
        )
        media.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-i", str(art), "-vf", vf, *common_out,
        ], log_path=log)
        return str(out)

    # không có ảnh: nền gradient chuyển động + vignette (không thêm noise:
    # hạt phim làm bitrate tăng 100 lần mà gần như không thấy trên điện thoại)
    colors = mood_colors(scene.get("mood", ""))
    color_args = ":".join(f"c{i}={c}" for i, c in enumerate(colors))
    vf = (
        f"gradients=s={w}x{h}:{color_args}:x0=0:y0=0:x1={w}:y1={h}:"
        f"nb_colors={len(colors)}:speed=0.014:d={dur:.3f},"
        f"fps={fps},"
        f"zoompan=z='1+0.00028*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={w}x{h}:fps={fps},"
        f"vignette=PI/4.6,setsar=1{overlay},format=yuv420p"
    )
    media.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", vf, *common_out,
    ], log_path=log)
    return str(out)


def _concat_videos(parts: list[Path], out: Path, workdir: Path) -> str:
    ffmpeg, _ = media.paths()
    listfile = workdir / "concat-video.txt"
    listfile.write_text(
        "\n".join(f"file '{p.name}'" for p in parts), encoding="utf-8"
    )
    try:
        media.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", listfile.name,
            "-c", "copy", "-movflags", "+faststart", str(out),
        ], cwd=workdir)
    except media.MediaError:
        media.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", listfile.name,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", str(out),
        ], cwd=workdir)
    return str(out)


def _narration_track(timeline: list[dict], workdir: Path, total_ms: int) -> Path:
    parts: list[Path] = []
    for scene in timeline:
        target = workdir / f"vo-{scene['idx']:03d}.wav"
        audio = Path(scene["audio_path"]) if scene.get("audio_path") else None
        if audio and audio.exists():
            media.pad_to(audio, target, scene["duration_ms"])
        else:
            media.silence(scene["duration_ms"], target)
        parts.append(target)
    narration = workdir / "narration.wav"
    media.concat_wav(parts, narration, workdir=workdir)
    return narration


def _write_captions(timeline: list[dict], ratio: dict, style: CaptionStyle, workdir: Path,
                    watermark: str, show_hook: bool, progress_bar: bool = True) -> Path:
    content = build_ass(
        timeline, ratio, style, watermark=watermark, show_hook=show_hook,
        progress_bar=progress_bar,
    )
    return Path(write_ass(workdir / "captions.ass", content))


def render_video(
    video_id: str,
    ratio_key: str,
    *,
    quality: str = "high",
    progress=None,
    cfg: dict | None = None,
) -> dict:
    """Dựng một tỉ lệ. Trả bản ghi render (dict)."""
    cfg = cfg or load_config()
    video = db.get("videos", video_id)
    if not video:
        raise ValueError(f"Không có video {video_id}")
    project = db.get("projects", video["project_id"])
    spec = db.loads(video.get("spec"))
    ratio = cfg["render"]["ratios"].get(ratio_key)
    if not ratio:
        raise ValueError(f"Tỉ lệ không hỗ trợ: {ratio_key}")

    rows = db.q(
        "SELECT s.* FROM video_scenes vs JOIN scenes s ON s.id = vs.scene_id "
        "WHERE vs.video_id=? ORDER BY vs.idx", (video_id,)
    )
    if not rows:
        raise ValueError("Video chưa có cảnh nào")

    from .tts import profile_of

    _, prof = profile_of(cfg, spec.get("voice_profile"))
    from .tts import _pct

    timeline = scene_timing(rows, cfg, _pct(prof.get("rate")))
    total_ms = sum(s["duration_ms"] for s in timeline)

    out_dir = project_dir(project["slug"]) / "renders" / video_id / ratio_key.replace(":", "x")
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"
    work.mkdir(exist_ok=True)
    logs = out_dir / "logs"
    logs.mkdir(exist_ok=True)

    w, h = dims(ratio, quality)
    fps = int(cfg["render"].get("fps", 30))

    def report(pct: int, msg: str) -> None:
        if progress:
            progress(pct, msg)

    # 1) từng cảnh
    visual_parts: list[Path] = []
    for i, scene in enumerate(timeline):
        report(4 + int(58 * i / len(timeline)), f"Dựng cảnh {i + 1}/{len(timeline)}")
        part = work / f"scene-{i:03d}.mp4"
        _scene_visual(scene, project, part, w, h, fps, quality, logs / f"scene-{i:03d}.log",
                      spec=spec, cfg=cfg)
        visual_parts.append(part)

    # 2) ghép hình
    report(66, "Ghép cảnh")
    visual = work / "visual.mp4"
    _concat_videos(visual_parts, visual, work)

    # 3) tiếng
    report(72, "Trộn lời đọc")
    narration = _narration_track(timeline, work, total_ms)
    bgm = (spec.get("bgm") or {}).get("path") or spec.get("bgm_path") or ""
    if bgm and not Path(bgm).is_absolute():
        bgm = str(project_dir(project["slug"]) / bgm)
    mix = work / "mix.wav"
    media.soundtrack(
        narration, total_ms, mix,
        bgm=bgm if bgm and Path(bgm).exists() else None,
        bgm_gain=float((spec.get("bgm") or {}).get("gain", cfg["render"]["bgm_gain"])),
    )

    # 4) phụ đề + thanh tiến trình + mux
    report(80, "Burn phụ đề")
    style = CaptionStyle.from_dict(spec.get("caption"))
    ass_path = _write_captions(
        timeline, ratio, style, work,
        watermark=spec.get("watermark", ""),
        show_hook=bool(spec.get("hook", True)),
        progress_bar=bool(spec.get("progress_bar", True)),
    )
    ffmpeg, _ = media.paths()
    safe_title = re.sub(r"[^\w\-.]+", "-", video["title"], flags=re.UNICODE).strip("-") or "video"
    final = out_dir / f"{safe_title[:60]}-{ratio_key.replace(':', 'x')}.mp4"
    vf = f"subtitles={ass_path.name},format=yuv420p"
    preset = "veryfast" if quality == "draft" else cfg["render"]["preset"]
    crf = 26 if quality == "draft" else cfg["render"]["crf"]
    try:
        media.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", visual.name, "-i", mix.name,
            "-vf", vf,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", cfg["render"]["audio_bitrate"], "-ac", "2",
            "-shortest", "-movflags", "+faststart", str(final),
        ], cwd=work, log_path=logs / "final.log")
        used_final = final
    except media.MediaError:
        # thử lại với fontsdir tường minh (một số bản libass không tự tìm font hệ thống)
        fonts = str(cfg["render"].get("fontsdir") or "")
        vf2 = vf
        if fonts:
            escaped = fonts.replace("\\", "/").replace(":", "\\:")
            vf2 = vf.replace(
                f"subtitles={ass_path.name}",
                f"subtitles={ass_path.name}:fontsdir='{escaped}'",
            )
        media.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", visual.name, "-i", mix.name,
            "-vf", vf2,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", cfg["render"]["audio_bitrate"], "-ac", "2",
            "-shortest", "-movflags", "+faststart", str(final),
        ], cwd=work, log_path=logs / "final-retry.log")
        used_final = final

    report(94, "Ảnh bìa")
    thumb = out_dir / "cover.jpg"
    try:
        media.thumbnail(used_final, thumb, at_ms=min(1500, max(600, total_ms // 4)))
    except media.MediaError:
        thumb = Path("")

    info = media.probe(used_final)
    result = {
        "path": str(used_final),
        "thumb": str(thumb) if thumb else "",
        "duration_ms": info.get("duration_ms") or total_ms,
        "bytes": used_final.stat().st_size if used_final.exists() else 0,
        "settings": {
            "ratio": ratio_key, "w": info.get("width", w), "h": info.get("height", h),
            "quality": quality, "fps": fps, "scenes": len(timeline),
        },
        "timeline": [
            {"idx": s["idx"], "start_ms": s["start_ms"], "duration_ms": s["duration_ms"],
             "words": len(s["words"]), "title": s["title"]}
            for s in timeline
        ],
    }
    report(100, "Xong")
    return result


def render_cover_frame(video_id: str, ratio_key: str, at_ms: int = 1000) -> str:
    """Xuất một khung hình PNG để kiểm tra bố cục nhanh."""
    cfg = load_config()
    video = db.get("videos", video_id)
    project = db.get("projects", video["project_id"])
    rows = db.q(
        "SELECT s.* FROM video_scenes vs JOIN scenes s ON s.id = vs.scene_id "
        "WHERE vs.video_id=? ORDER BY vs.idx", (video_id,)
    )
    timeline = scene_timing(rows, cfg)
    ratio = cfg["render"]["ratios"][ratio_key]
    w, h = dims(ratio, "high")
    out_dir = project_dir(project["slug"]) / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    style = CaptionStyle.from_dict(db.loads(video.get("spec")).get("caption"))
    ass_path = _write_captions(timeline, ratio, style, out_dir, "", True)
    target = out_dir / f"frame-{ratio_key.replace(':', 'x')}.png"
    # dùng cảnh đầu làm nền
    scene = timeline[0]
    tmp = out_dir / "frame-base.mp4"
    _scene_visual(scene, project, tmp, w, h, 30, "high", out_dir / "frame.log",
                  spec=db.loads(video.get("spec")), cfg=cfg)
    ffmpeg, _ = media.paths()
    media.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", tmp.name,
        "-vf", f"subtitles={ass_path.name}", "-frames:v", "1", str(target.name),
    ], cwd=out_dir)
    return str(target)
