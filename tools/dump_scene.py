import json
import sqlite3
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "data/storytube.db"
con = sqlite3.connect(path)
con.row_factory = sqlite3.Row
row = con.execute("select id, narration, words, duration_ms from scenes order by idx limit 1").fetchone()
print(row["id"], row["duration_ms"], "ms")
print(row["narration"])
for w in json.loads(row["words"]):
    print(f"  {w['w']:14s} {w['s']:6d} -> {w['e']:6d}")
