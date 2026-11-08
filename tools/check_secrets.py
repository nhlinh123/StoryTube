"""Quét key/credentials lọt vào mã nguồn trước khi đẩy repo lên git.

    python tools/check_secrets.py
"""

from __future__ import annotations

import pathlib
import re
import sys

PATTERNS = [
    ("deepseek/api key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("elevenlabs key", re.compile(r"sk_[A-Za-z0-9]{20,}")),
    ("bearer", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{24,}")),
    ("xi-api-key", re.compile(r"xi-api-key[\"']?\s*[:=]\s*[\"'][^\"']{12,}")),
    ("generic token", re.compile(r"\b(?:api[_-]?key|token|secret)\b\s*[:=]\s*[\"'][A-Za-z0-9._\-]{24,}[\"']", re.I)),
]

SKIP_DIRS = {"vendor", "wheels", "data", "__pycache__", ".git", ".venv", "node_modules"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".wav", ".mp3", ".zip", ".whl", ".db", ".ico"}

ALLOW = re.compile(r"(xxx|your[-_]?key|sk-\.\.\.|placeholder|<.*>|\.\.\.)")


def scan(root: pathlib.Path) -> list[tuple[str, str, str]]:
    hits: list[tuple[str, str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_EXT:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0)
                if ALLOW.search(value):
                    continue
                hits.append((str(path.relative_to(root)), label, value[:14] + "…"))
    return hits


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    hits = scan(root)
    if not hits:
        print("Không tìm thấy key/token nào trong mã nguồn.")
        return 0
    print(f"CẢNH BÁO: {len(hits)} chỗ có thể là credential:")
    for path, label, preview in hits:
        print(f"  {path}: {label} = {preview}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
