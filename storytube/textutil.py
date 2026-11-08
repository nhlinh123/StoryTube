"""Xử lý tiếng Việt: chuẩn hoá cho TTS, đếm âm tiết, canh thời gian phụ đề."""

from __future__ import annotations

import math
import re
import unicodedata

_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
_SCALES = ["", "nghìn", "triệu", "tỷ"]

ABBREVIATIONS = {
    "tp.hcm": "thành phố Hồ Chí Minh",
    "tp.hcm)": "thành phố Hồ Chí Minh",
    "tphcm": "thành phố Hồ Chí Minh",
    "hcm": "Hồ Chí Minh",
    "hn": "Hà Nội",
    "tp": "thành phố",
    "tx": "thị xã",
    "q.": "quận",
    "q": "quận",
    "p.": "phường",
    "nxb": "nhà xuất bản",
    "gs": "giáo sư",
    "pgs": "phó giáo sư",
    "ts": "tiến sĩ",
    "ths": "thạc sĩ",
    "bs": "bác sĩ",
    "km": "ki lô mét",
    "kg": "ki lô gam",
    "cm": "xen ti mét",
    "mm": "mi li mét",
    "m2": "mét vuông",
    "m3": "mét khối",
    "kw": "ki lô oát",
    "vnd": "đồng",
    "usd": "đô la",
    "&": "và",
    "vs": "với",
    "etc": "vân vân",
    "mr": "ông",
    "mrs": "bà",
    "ms": "cô",
}

_EMOJI = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F1E6-\U0001F1FF" "\U0000FE0F" "]+"
)


def _three(n: int, full: bool = False) -> list[str]:
    out: list[str] = []
    hundred, rest = divmod(n, 100)
    if hundred or full:
        out += [_DIGITS[hundred], "trăm"]
    if rest == 0:
        return out
    if rest < 10:
        if hundred or full:
            out.append("linh")
        out.append(_DIGITS[rest])
        return out
    tens, unit = divmod(rest, 10)
    out.append("mười" if tens == 1 else f"{_DIGITS[tens]} mươi")
    if unit:
        if unit == 1 and tens > 1:
            out.append("mốt")
        elif unit == 5:
            out.append("lăm")
        elif unit == 4 and tens > 1:
            out.append("tư")
        else:
            out.append(_DIGITS[unit])
    return out


def read_integer(n: int) -> str:
    """1500 -> 'một nghìn năm trăm'."""
    if n == 0:
        return "không"
    if n < 0:
        return "âm " + read_integer(-n)
    groups: list[int] = []
    while n:
        n, rem = divmod(n, 1000)
        groups.append(rem)
    words: list[str] = []
    for idx in range(len(groups) - 1, -1, -1):
        g = groups[idx]
        if g == 0:
            continue
        chunk = _three(g, full=bool(words) and g < 100)
        scale = _SCALES[idx % 4] if idx % 4 else ("tỷ" if idx else "")
        words += chunk + ([scale] if scale else [])
    return " ".join(words)


def _read_decimal(raw: str) -> str:
    whole, frac = raw.split(",", 1) if "," in raw else raw.split(".", 1)
    return f"{read_integer(int(whole or 0))} phẩy " + " ".join(_DIGITS[int(d)] for d in frac)


def _number_token(match: re.Match) -> str:
    raw = match.group(0)
    if re.fullmatch(r"\d{1,2}:\d{2}", raw):
        h, m = raw.split(":")
        return f"{read_integer(int(h))} giờ {read_integer(int(m))}" if m != "00" else f"{read_integer(int(h))} giờ"
    if re.search(r"[,.]\d", raw) and not re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
        return _read_decimal(raw)
    digits = raw.replace(".", "").replace(",", "")
    try:
        return read_integer(int(digits))
    except ValueError:
        return raw


def strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"(\*\*|__|\*|_|~~)", "", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)
    return text


def normalize_for_tts(text: str) -> str:
    """Chuẩn hoá văn bản để đọc: bỏ markdown, đọc số, mở viết tắt, gọn khoảng trắng."""
    text = strip_markdown(text or "")
    text = _EMOJI.sub(" ", text)
    text = unicodedata.normalize("NFC", text)
    text = text.replace("…", "...").replace("–", "-").replace("—", "-")
    text = re.sub(r"[“”«»\"]", "", text)
    text = re.sub(r"[‘’']", "", text)
    text = re.sub(r"\s*\.{3,}\s*", ", ", text)

    # viết tắt (so khớp theo từ, không phân biệt hoa thường)
    def abbr(m: re.Match) -> str:
        tok = m.group(0)
        key = tok.lower()
        return ABBREVIATIONS.get(key, tok)

    text = re.sub(r"\b[\w.&]+\b", abbr, text)

    text = re.sub(r"(\d+)\s*%", lambda m: f"{read_integer(int(m.group(1)))} phần trăm", text)
    text = re.sub(r"(\d+)\s*°C", lambda m: f"{read_integer(int(m.group(1)))} độ xê", text)
    text = re.sub(r"\d+([.,]\d+)?", _number_token, text)
    text = re.sub(r"\s*-\s*", ", ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return text.strip(" ,")


def sentences(text: str) -> list[str]:
    """Tách câu theo dấu kết câu, giữ dấu."""
    text = strip_markdown(text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?…])\s+|\n{2,}", text)
    out = [p.strip() for p in parts if p and p.strip()]
    # gộp câu quá ngắn vào câu trước để TTS không bị ngắt vụn
    merged: list[str] = []
    for part in out:
        if merged and len(part) < 12 and not part.endswith((".", "!", "?", "…")):
            merged[-1] = merged[-1] + " " + part
        else:
            merged.append(part)
    return merged


def syllables(text: str) -> int:
    """Tiếng Việt: mỗi âm tiết cách nhau bởi khoảng trắng."""
    return len([w for w in re.split(r"\s+", strip_markdown(text or "")) if re.search(r"\w", w)])


def estimate_speech_ms(text: str, rate_pct: float = 0.0) -> int:
    """Ước lượng thời lượng đọc. NamMinh ~ 4.15 âm tiết/giây ở tốc độ gốc."""
    syl = max(1, syllables(text))
    speed = 4.15 * max(0.6, 1.0 + rate_pct / 100.0)
    pause_ms = 140 * max(0, text.count(".") + text.count(",") - 1)
    return int(syl / speed * 1000 + pause_ms)


def words_of(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", strip_markdown(text or "").strip()) if w]


def word_timings(text: str, duration_ms: int) -> list[dict]:
    """Chia thời lượng câu cho từng từ theo trọng số ký tự (đủ tốt cho karaoke)."""
    words = words_of(text)
    if not words or duration_ms <= 0:
        return []
    weights = [max(1.0, len(re.sub(r"\W", "", w)) * 0.55 + len(w) * 0.45) for w in words]
    total = sum(weights)
    t = 0
    out = []
    for word, weight in zip(words, weights):
        span = int(duration_ms * weight / total)
        out.append({"w": word, "s": t, "e": t + span})
        t += span
    out[-1]["e"] = duration_ms
    return out


def caption_pages(
    words: list[dict], max_words: int = 4, max_chars: int = 26
) -> list[list[dict]]:
    """Gom từ thành trang phụ đề ngắn, chia đều để không có trang lẻ một từ."""
    if not words:
        return []
    count = max(1, math.ceil(len(words) / max(1, max_words)))
    size = max(1, math.ceil(len(words) / count))
    pages: list[list[dict]] = []
    for start in range(0, len(words), size):
        chunk = words[start : start + size]
        cur: list[dict] = []
        for word in chunk:
            candidate = " ".join(w["w"] for w in cur + [word])
            if cur and len(candidate) > max_chars:
                pages.append(cur)
                cur = [word]
            else:
                cur.append(word)
        if cur:
            pages.append(cur)
    return pages


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "truyen"


def short(text: str, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def chunk_text(text: str, max_chars: int = 280) -> list[str]:
    """Chia đoạn dài thành câu vừa cho một lần gọi TTS."""
    out, buf = [], ""
    for sent in sentences(text):
        if buf and len(buf) + len(sent) + 1 > max_chars:
            out.append(buf)
            buf = sent
        else:
            buf = f"{buf} {sent}".strip()
    if buf:
        out.append(buf)
    return out or ([text.strip()] if text and text.strip() else [])


def fmt_duration(ms: int) -> str:
    total = max(0, int(ms // 1000))
    return f"{total // 60}:{total % 60:02d}"


def ass_time(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, msec = divmod(rem, 1000)
    return f"{h:d}:{m:02d}:{s:02d}.{msec // 10:02d}"


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def spread(total_ms: int, count: int) -> list[int]:
    if count <= 0:
        return []
    base = total_ms / count
    return [int(math.floor(base * (i + 1))) for i in range(count)]
