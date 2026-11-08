"""Sinh phụ đề .ass: karaoke từng từ, khối câu, hook chữ to, watermark.

Toạ độ tính theo pixel của từng tỉ lệ khung (PlayRes = kích thước video) nên cùng
một kịch bản dựng được 9:16, 4:5, 1:1, 3:4, 16:9 mà chữ vẫn nằm trong vùng an toàn.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .textutil import ass_time, caption_pages

COL = {
    "white": "&H00FFFFFF",
    "black": "&H00000000",
    "yellow": "&H0000D4FF",   # #FFD400
    "green": "&H0059FF9A",
    "red": "&H002020F0",
    "grey": "&H00C0C0C0",
}


@dataclass
class CaptionStyle:
    name: str = "karaoke"          # karaoke | block | beast | minimal
    font: str = "Arial"
    font_bold: bool = True
    uppercase: bool = False
    max_words: int = 4
    highlight: str = "yellow"
    base_color: str = "white"
    outline: float = 5.0
    shadow: float = 2.0
    scale: float = 1.0
    hook_color: str = "yellow"
    position: str = "tiktok"       # tiktok | youtube | center | upper

    @classmethod
    def from_dict(cls, data: dict | None) -> "CaptionStyle":
        data = data or {}
        return cls(
            name=data.get("name", "karaoke"),
            font=data.get("font", "Arial"),
            font_bold=bool(data.get("font_bold", True)),
            uppercase=bool(data.get("uppercase", False)),
            max_words=int(data.get("max_words", 4)),
            highlight=data.get("highlight", "yellow"),
            base_color=data.get("base_color", "white"),
            outline=float(data.get("outline", 5.0)),
            shadow=float(data.get("shadow", 2.0)),
            scale=float(data.get("scale", 1.0)),
            hook_color=data.get("hook_color", "yellow"),
            position=data.get("position", "tiktok"),
        )


# vị trí dòng phụ đề tính theo % chiều cao khung (neo đáy chữ)
POSITIONS = {
    "tiktok": 0.74,    # trên thanh UI TikTok/Reels
    "youtube": 0.86,   # lower-third cổ điển
    "center": 0.55,
    "upper": 0.34,
}


HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
Title: StoryTube

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{primary},{secondary},{outline_c},&H80000000,{bold},0,0,0,100,100,{spacing},0,1,{outline},{shadow},2,40,40,40,1
Style: Hook,{hfont},{hsize},{hook},{hook},{outline_c},&H80000000,{bold},0,0,0,100,100,{spacing},0,1,{houtline},{hshadow},5,40,40,40,1
Style: Mark,{font},{msize},{grey},{grey},{outline_c},&H80000000,0,0,0,0,100,100,0,0,1,2,1,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _color(name: str) -> str:
    return COL.get(name, name if name.startswith("&H") else COL["white"])


def _wrap(text: str, max_chars: int, max_lines: int = 2) -> str:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        if cur and len(cur) + 1 + len(word) > max_chars:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        merged = lines[: max_lines - 1]
        merged.append(" ".join(lines[max_lines - 1 :]))
        lines = merged
    return "\\N".join(lines)


def _event(start: int, end: int, style: str, text: str, layer: int = 0) -> str:
    return (
        f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{text}\n"
    )


def _progress_events(total_ms: int, w: int, h: int, style: CaptionStyle,
                     steps: int = 120) -> list[str]:
    """Thanh tiến trình vẽ bằng ASS (không cần filter drawbox, không tốn encode)."""
    bar_h = max(4, round(h * 0.006))
    y = h - bar_h
    color = _color(style.highlight).replace("&H00", "&H00")
    events = []
    step_ms = max(1, total_ms // steps)
    for k in range(1, steps + 1):
        frac = k / steps
        width = max(2, int(w * frac))
        start = (k - 1) * step_ms
        end = min(total_ms, k * step_ms) if k < steps else total_ms
        drawing = (
            f"{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\c{color}}}"
            f"m 0 {y} l {width} {y} l {width} {h} l 0 {h}{{\\p0}}"
        )
        events.append(_event(start, end, "Cap", drawing, layer=0))
    return events


def build_ass(
    scenes: list[dict],
    ratio: dict,
    style: CaptionStyle | None = None,
    *,
    hook_hold_ms: int = 2200,
    watermark: str = "",
    show_hook: bool = True,
    progress_bar: bool = False,
) -> str:
    """scenes: [{words, start_ms, duration_ms, on_screen, title}] theo timeline video."""
    style = style or CaptionStyle()
    w, h = int(ratio["w"]), int(ratio["h"])
    safe = ratio.get("safe", {"top": 100, "bottom": 300, "side": 60})
    # cỡ chữ theo chiều rộng nhưng chặn theo chiều cao: khung ngang không bị chữ khổng lồ
    font_size = max(28, round(min(w * 0.058, h * 0.052) * style.scale))
    usable = w - 2 * int(safe["side"])
    max_chars = max(10, int(usable / (font_size * 0.52)))
    pos_key = style.position if style.position in POSITIONS else "tiktok"
    bottom_y = int(h * POSITIONS[pos_key])
    hook_size = max(38, round(min(w * 0.082, h * 0.072) * style.scale))
    hook_y = int(safe["top"] + h * 0.10)

    header = HEADER.format(
        w=w, h=h,
        font=style.font, size=font_size,
        hfont=style.font, hsize=hook_size,
        msize=max(20, round(min(w * 0.030, h * 0.032))),
        primary=_color(style.highlight), secondary=_color(style.base_color),
        hook=_color(style.hook_color), grey=COL["grey"],
        outline_c=COL["black"],
        bold=-1 if style.font_bold else 0,
        spacing=0,
        outline=round(style.outline * min(w, h) / 1080, 1),
        shadow=round(style.shadow * min(w, h) / 1080, 1),
        houtline=round((style.outline + 3) * min(w, h) / 1080, 1),
        hshadow=round((style.shadow + 2) * min(w, h) / 1080, 1),
    )
    body: list[str] = []
    total_ms = sum(int(s.get("duration_ms", 0)) for s in scenes)
    if watermark:
        body.append(_event(
            0, total_ms,
            "Mark", f"{{\\an7\\pos(48,40)\\alpha&H60&}}{_esc(watermark)}", layer=1,
        ))
    if progress_bar and total_ms > 0:
        body.extend(_progress_events(total_ms, w, h, style))

    for scene in scenes:
        start = int(scene.get("start_ms", 0))
        dur = int(scene.get("duration_ms", 0))
        words = scene.get("words") or []
        on_screen = (scene.get("on_screen") or "").strip()

        if show_hook and on_screen:
            text = on_screen.upper() if style.uppercase else on_screen
            hold = min(hook_hold_ms, max(900, dur - 200))
            anim = (
                f"{{\\an5\\pos({w // 2},{hook_y})\\fad(140,240)"
                f"\\fscx90\\fscy90\\t(0,180,\\fscx104\\fscy104)\\t(180,320,\\fscx100\\fscy100)}}"
            )
            body.append(_event(start + 60, start + hold, "Hook", anim + _wrap(text, 14), layer=3))

        if not words:
            continue
        pages = caption_pages(words, style.max_words, max_chars)
        for page in pages:
            page_start = start + int(page[0]["s"])
            page_end = start + int(page[-1]["e"])
            if page_end <= page_start:
                page_end = page_start + 300
            text = " ".join(w["w"] for w in page)
            upper = text.upper() if style.uppercase else text
            if style.name == "block":
                line = _wrap(upper, max_chars)
                anim = "{\\an2\\pos(%d,%d)\\fad(90,70)}" % (w // 2, bottom_y)
                body.append(_event(page_start, page_end + 120, "Cap", anim + line, layer=2))
                continue
            if style.name == "beast":
                anim = (
                    "{\\an2\\pos(%d,%d)\\fad(40,40)\\fscx112\\fscy112"
                    "\\t(0,110,\\fscx100\\fscy100)}" % (w // 2, bottom_y)
                )
                line = _wrap(upper, max(9, max_chars - 4))
                body.append(_event(page_start, page_end + 90, "Cap", anim + line, layer=2))
                continue
            if style.name == "minimal":
                anim = "{\\an2\\pos(%d,%d)\\fad(120,120)\\fs%d}" % (w // 2, bottom_y, round(font_size * 0.72))
                line = _wrap(text, max_chars)
                body.append(_event(page_start, page_end + 150, "Cap", anim + line, layer=2))
                continue

            # karaoke: từ đang đọc đổi màu, chạy từ trái sang phải
            parts = []
            cursor = page_start
            for word in page:
                span = max(1, int(word["e"]) - int(word["s"]))
                text_word = word["w"].upper() if style.uppercase else word["w"]
                parts.append(f"{{\\k{max(1, round(span / 10))}}}{_esc(text_word)} ")
                cursor += span
            anim = "{\\an2\\pos(%d,%d)\\fad(60,50)}" % (w // 2, bottom_y)
            body.append(_event(page_start, page_end + 100, "Cap", anim + "".join(parts).strip(), layer=2))

    return header + "".join(body)


def write_ass(path: str | Path, content: str) -> str:
    Path(path).write_text(content, encoding="utf-8-sig")
    return str(path)


def load_words(raw: str | list | None) -> list[dict]:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []
