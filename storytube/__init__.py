"""StoryTube — xưởng truyện tranh ảnh: viết truyện, lồng tiếng, dựng video đa tỉ lệ.

Gói này tự bổ sung thư mục ``vendor/`` (wheel giải nén sẵn) vào ``sys.path`` để
chạy được trên máy không cài được pip (sandbox chặn pip ghi file tạm).
"""

from __future__ import annotations

import pathlib
import sys

__version__ = "0.1.0"

_VENDOR = pathlib.Path(__file__).resolve().parent.parent / "vendor"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))
