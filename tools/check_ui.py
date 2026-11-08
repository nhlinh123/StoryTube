import pathlib
import re

root = pathlib.Path(__file__).resolve().parent.parent
js = (root / "storytube/web/app.js").read_text(encoding="utf-8")
html = (root / "storytube/web/index.html").read_text(encoding="utf-8")

used = set(re.findall(r'data-act="([\w-]+)"', js + html))
defined = set(re.findall(r"^  (?:async )?'([\w-]+)'\(", js, flags=re.M))
print("used     :", sorted(used))
print("defined  :", sorted(defined))
print("MISSING  :", sorted(used - defined))
print("unused   :", sorted(defined - used))
