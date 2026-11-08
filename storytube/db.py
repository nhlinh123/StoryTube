"""SQLite: một file duy nhất cho toàn bộ truyện, cảnh, video và job."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Iterable

from .config import DATA_DIR

DB_PATH = DATA_DIR / "storytube.db"

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    genre TEXT DEFAULT '',
    language TEXT DEFAULT 'vi',
    logline TEXT DEFAULT '',
    premise TEXT DEFAULT '',
    style TEXT DEFAULT '',
    level INTEGER DEFAULT 3,
    cover TEXT DEFAULT '',
    status TEXT DEFAULT 'draft',
    meta TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,              -- character | location | item | rule | theme
    name TEXT NOT NULL,
    aliases TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    details TEXT DEFAULT '',
    color TEXT DEFAULT '',
    sort INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapters (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    title TEXT NOT NULL,
    synopsis TEXT DEFAULT '',
    hook TEXT DEFAULT '',
    status TEXT DEFAULT 'outline',   -- outline | writing | done
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS beats (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    summary TEXT NOT NULL,
    intent TEXT DEFAULT '',
    prose TEXT DEFAULT '',
    words INTEGER DEFAULT 0,
    status TEXT DEFAULT 'planned',   -- planned | written | approved
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_id TEXT,
    beat_id TEXT,
    idx INTEGER NOT NULL,
    title TEXT DEFAULT '',
    narration TEXT NOT NULL,          -- lời đọc (TTS)
    on_screen TEXT DEFAULT '',        -- chữ to hiện trên hình (hook)
    visual_prompt TEXT DEFAULT '',
    mood TEXT DEFAULT '',
    art TEXT DEFAULT '',              -- ảnh/video nền (đường dẫn tương đối)
    duration_ms INTEGER DEFAULT 0,
    audio_path TEXT DEFAULT '',
    words TEXT DEFAULT '[]',          -- [{t,start,end}]
    status TEXT DEFAULT 'draft',      -- draft | voiced | rendered
    meta TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    format TEXT DEFAULT 'short',      -- short | long
    spec TEXT DEFAULT '{}',
    status TEXT DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_scenes (
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    PRIMARY KEY (video_id, scene_id)
);

CREATE TABLE IF NOT EXISTS renders (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    ratio TEXT NOT NULL,
    path TEXT DEFAULT '',
    thumb TEXT DEFAULT '',
    duration_ms INTEGER DEFAULT 0,
    bytes INTEGER DEFAULT 0,
    status TEXT DEFAULT 'queued',     -- queued | running | done | error
    error TEXT DEFAULT '',
    log_path TEXT DEFAULT '',
    settings TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload TEXT DEFAULT '{}',
    status TEXT DEFAULT 'queued',
    progress INTEGER DEFAULT 0,
    message TEXT DEFAULT '',
    result TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS ai_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    level INTEGER DEFAULT 0,
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    status TEXT DEFAULT 'ok',
    error TEXT DEFAULT '',
    ms INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    kind TEXT DEFAULT 'image',        -- image | video | music | voice | font
    path TEXT NOT NULL,
    label TEXT DEFAULT '',
    meta TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entities_project ON entities(project_id, kind);
CREATE INDEX IF NOT EXISTS idx_chapters_project ON chapters(project_id, idx);
CREATE INDEX IF NOT EXISTS idx_beats_chapter ON beats(chapter_id, idx);
CREATE INDEX IF NOT EXISTS idx_scenes_project ON scenes(project_id, idx);
CREATE INDEX IF NOT EXISTS idx_renders_video ON renders(video_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def cleanup_stale() -> int:
    """Đánh dấu job/render còn treo từ lần chạy trước (chỉ gọi lúc khởi động server)."""
    changed = 0
    with connect() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status='error', message='Bị gián đoạn', "
            "error='Ứng dụng tắt khi job đang chạy' WHERE status IN ('running','queued')"
        )
        changed += cur.rowcount
        cur = conn.execute(
            "UPDATE renders SET status='error', error='Bị gián đoạn khi đang dựng' "
            "WHERE status IN ('running','queued')"
        )
        changed += cur.rowcount
        # dọn cảnh rỗng, không thuộc bản dựng nào (do bấm "Thêm cảnh" rồi bỏ)
        conn.execute(
            "DELETE FROM scenes WHERE narration='' AND audio_path='' AND art='' "
            "AND id NOT IN (SELECT scene_id FROM video_scenes)"
        )
        conn.commit()
    return changed


def q(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def q1(sql: str, params: Iterable[Any] = ()) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def x(sql: str, params: Iterable[Any] = ()) -> None:
    with connect() as conn:
        conn.execute(sql, tuple(params))
        conn.commit()


def insert(table: str, data: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(data.values()))
        conn.commit()
    return data


def update(table: str, row_id: str, data: dict[str, Any]) -> None:
    if not data:
        return
    sets = ", ".join(f"{k}=?" for k in data)
    with connect() as conn:
        conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*data.values(), row_id))
        conn.commit()


def get(table: str, row_id: str) -> dict | None:
    return q1(f"SELECT * FROM {table} WHERE id=?", (row_id,))


def delete(table: str, row_id: str) -> None:
    x(f"DELETE FROM {table} WHERE id=?", (row_id,))


def loads(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default if default is not None else {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default if default is not None else {}


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
