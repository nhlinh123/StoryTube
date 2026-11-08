"""Fetch wheels straight from a PyPI mirror (no pip downloader involved).

Why this exists: on some Windows sandbox setups `pip install` fails while writing
its temporary download file (PermissionError on `pip-unpack-*/*.whl`), even though
the same directory is writable by plain Python. Downloading the wheels ourselves
and then letting pip resolve them from `--find-links` sidesteps that entirely.

Usage:
    python tools/wheel_fetch.py edge-tts --dest wheels --index https://mirrors.aliyun.com/pypi/simple/
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import urllib.request
from pathlib import Path

DEFAULT_INDEX = "https://mirrors.aliyun.com/pypi/simple/"
PY, ABI = "cp314", "cp314"


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "storytube-wheel-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pkg_name(spec: str) -> str:
    """`aiohttp<4,>=3.8 ; extra == "x"` -> `aiohttp`."""
    return re.split(r"[<>=!~;\[(\s]", spec.strip(), maxsplit=1)[0]


def _vkey(v: str):
    parts = re.split(r"[._-]", v)
    out = []
    for p in parts:
        out.append((0, int(p), "") if p.isdigit() else (1, 0, p))
    return out


def _wheel_ok(fname: str) -> bool:
    m = re.match(r"^[^-]+-[^-]+(-[^-]+)?-([^-]+)-([^-]+)-([^-]+)\.whl$", fname)
    if not m:
        return False
    py, abi, plat = m.group(2), m.group(3), m.group(4)
    if plat not in ("any", "win_amd64", "win32"):
        return False
    if py in ("py3", "py2.py3") and abi == "none":
        return True
    if abi == "abi3" and py.startswith("cp3"):
        minor = py[3:]
        return minor.isdigit() and int(minor) <= 14
    return py == PY and abi == ABI


def _metadata_deps(whl: Path) -> list[str]:
    import zipfile

    with zipfile.ZipFile(whl) as z:
        meta = [n for n in z.namelist() if n.endswith(".dist-info/METADATA")]
        if not meta:
            return []
        text = z.read(meta[0]).decode("utf-8", "replace")
    deps = []
    for line in text.splitlines():
        if not line.startswith("Requires-Dist:"):
            continue
        spec = line.split(":", 1)[1].strip()
        name, _, rest = spec.partition(";")
        marker = rest.strip()
        if "extra ==" in marker:
            continue
        deps.append(name.strip())
    return deps


def fetch(name: str, dest: Path, index: str) -> Path | None:
    last_err: Exception | None = None
    body = ""
    page = ""
    for cand in dict.fromkeys([_norm(name), name.replace("-", "_")]):
        page = index.rstrip("/") + "/" + cand + "/"
        try:
            body = _get(page).decode("utf-8", "replace")
            break
        except Exception as e:  # noqa: BLE001 - try the next spelling
            last_err = e
    if not body:
        raise last_err  # type: ignore[misc]
    links = re.findall(r'href="([^"#]+\.whl)(?:#[^"]*)?"', body)
    cands = []
    for href in links:
        fname = urllib.parse.unquote(href.rsplit("/", 1)[-1])
        if not _wheel_ok(fname):
            continue
        ver = fname.split("-")[1]
        cands.append((_vkey(ver), href, fname))
    if not cands:
        print(f"  !! no compatible wheel for {name}", file=sys.stderr)
        return None
    stable = [c for c in cands if not re.search(r"(rc|a|b|alpha|beta|dev|pre)\d*$", c[0][-1][2])]
    if stable:
        cands = stable
    cands.sort(key=lambda c: c[0])
    _, href, fname = cands[-1]
    url = href if href.startswith("http") else urllib.parse.urljoin(page, href)
    target = dest / fname
    if target.exists() and target.stat().st_size > 0:
        return target
    target.write_bytes(_get(url, timeout=120))
    print(f"  + {fname} ({target.stat().st_size // 1024} KB)")
    return target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("packages", nargs="+")
    ap.add_argument("--dest", default="wheels")
    ap.add_argument("--index", default=DEFAULT_INDEX)
    args = ap.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    seen: dict[str, Path] = {}
    queue = list(args.packages)
    while queue:
        name = queue.pop(0)
        key = _norm(_pkg_name(name))
        if key in seen:
            continue
        print(f"resolving {key}")
        whl = fetch(key, dest, args.index)
        if whl is None:
            continue
        seen[key] = whl
        queue.extend(_metadata_deps(whl))
    print(f"\n{len(seen)} wheel(s) in {dest.resolve()}")
    return 0


if __name__ == "__main__":
    import urllib.parse  # noqa: F401  (used via module attribute above)

    raise SystemExit(main())
