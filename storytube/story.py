"""Pipeline truyện: ý tưởng -> kinh thánh -> dàn ý -> beat -> văn xuôi -> kịch bản cảnh.

Model chỉ đề xuất JSON; ở đây mới là nơi kiểm tra, chuẩn hoá và ghi DB (đúng tinh
thần "proposer/harness" của xnovelist).
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import db, llm, prompts
from .config import load_config, project_dir
from .textutil import short, slugify, syllables

LEVELS = {
    0: "Tắt",
    1: "Người đọc",
    2: "Biên tập",
    3: "Đồng tác giả",
    4: "Soạn nháp",
    5: "Tác nhân",
}


class LevelError(RuntimeError):
    pass


def now() -> str:
    return db.now()


def get_project(project_id: str) -> dict:
    project = db.get("projects", project_id)
    if not project:
        raise ValueError("Không tìm thấy truyện")
    return project


def require_level(project: dict, needed: int, tool: str) -> None:
    level = int(project.get("level") or 0)
    if level < needed:
        raise LevelError(
            f"Cấp {level} ({LEVELS.get(level, '?')}) chưa cho phép '{tool}' — cần cấp {needed}. "
            f"Nâng cấp trong phần Cài đặt truyện nếu muốn AI làm bước này."
        )


def _log_run(project_id: str, tool: str, level: int, res: dict | None,
             status: str = "ok", error: str = "") -> None:
    usage = (res or {}).get("usage") or {}
    db.insert("ai_runs", {
        "id": db.new_id("run"),
        "project_id": project_id,
        "tool": tool,
        "level": level,
        "provider": (res or {}).get("provider", ""),
        "model": (res or {}).get("model", ""),
        "prompt_tokens": usage.get("prompt", 0),
        "completion_tokens": usage.get("completion", 0),
        "status": status,
        "error": error[:500],
        "ms": (res or {}).get("ms", 0),
        "created_at": now(),
    })


def create_project(title: str, genre: str = "", idea: str = "", level: int = 4,
                   language: str = "vi") -> dict:
    slug = slugify(title)
    base = slug
    n = 2
    while db.q1("SELECT id FROM projects WHERE slug=?", (slug,)):
        slug = f"{base}-{n}"
        n += 1
    project = {
        "id": db.new_id("prj"),
        "title": title.strip() or "Truyện mới",
        "slug": slug,
        "genre": genre,
        "language": language,
        "logline": "",
        "premise": idea,
        "style": "",
        "level": level,
        "cover": "",
        "status": "draft",
        "meta": db.dumps({}),
        "created_at": now(),
        "updated_at": now(),
    }
    db.insert("projects", project)
    project_dir(slug)
    return project


def update_project(project_id: str, patch: dict) -> dict:
    allowed = {"title", "genre", "logline", "premise", "style", "level", "status", "language", "cover"}
    data = {k: v for k, v in patch.items() if k in allowed}
    if data:
        data["updated_at"] = now()
        db.update("projects", project_id, data)
    return get_project(project_id)


def bible(project_id: str) -> dict:
    rows = db.q("SELECT * FROM entities WHERE project_id=? ORDER BY sort, created_at", (project_id,))
    out: dict[str, Any] = {"characters": [], "locations": [], "rules": [], "style": {}, "items": []}
    for row in rows:
        item = {
            "name": row["name"], "role": row["summary"], "detail": row["details"],
            "aliases": row["aliases"], "kind": row["kind"],
        }
        if row["kind"] == "character":
            out["characters"].append(item)
        elif row["kind"] == "location":
            out["locations"].append(item)
        elif row["kind"] == "item":
            out["items"].append(item)
        else:
            out["rules"].append(row["summary"] or row["name"])
    project = get_project(project_id)
    out["style"] = {"tone": project.get("style") or "", "genre": project.get("genre") or ""}
    return out


def _replace_entities(project_id: str, data: dict) -> int:
    db.x("DELETE FROM entities WHERE project_id=?", (project_id,))
    count = 0
    for idx, char in enumerate(data.get("characters") or []):
        if not isinstance(char, dict) or not char.get("name"):
            continue
        db.insert("entities", {
            "id": db.new_id("ent"), "project_id": project_id, "kind": "character",
            "name": str(char.get("name"))[:80],
            "aliases": ", ".join(char.get("aliases") or []) if isinstance(char.get("aliases"), list) else str(char.get("aliases") or ""),
            "summary": short(str(char.get("role") or char.get("want") or ""), 240),
            "details": db.dumps({k: v for k, v in char.items() if k not in ("name",)}),
            "color": "", "sort": idx, "created_at": now(),
        })
        count += 1
    for idx, loc in enumerate(data.get("locations") or []):
        if not isinstance(loc, dict) or not loc.get("name"):
            continue
        db.insert("entities", {
            "id": db.new_id("ent"), "project_id": project_id, "kind": "location",
            "name": str(loc.get("name"))[:80], "aliases": "",
            "summary": short(str(loc.get("detail") or ""), 240), "details": db.dumps(loc),
            "color": "", "sort": idx, "created_at": now(),
        })
        count += 1
    for idx, rule in enumerate(data.get("rules") or []):
        db.insert("entities", {
            "id": db.new_id("ent"), "project_id": project_id, "kind": "rule",
            "name": short(str(rule), 60), "aliases": "", "summary": str(rule),
            "details": "", "color": "", "sort": idx, "created_at": now(),
        })
        count += 1
    style = data.get("style") or {}
    if isinstance(style, dict) and style:
        desc = ", ".join(f"{k}: {v}" for k, v in style.items() if not isinstance(v, list))
        update_project(project_id, {"style": desc[:400]})
    return count


# --------------------------------------------------------------------------- #
# Các bước AI
# --------------------------------------------------------------------------- #
def gen_premise(project_id: str, idea: str = "") -> dict:
    project = get_project(project_id)
    require_level(project, 4, "dựng ý tưởng")
    idea = idea or project.get("premise") or project.get("title")
    messages = prompts.premise(idea, project.get("genre", ""))
    data, res = llm.chat_json(messages)
    _log_run(project_id, "premise", 4, res)
    patch = {
        "logline": short(str(data.get("logline") or ""), 400),
        "genre": str(data.get("genre") or project.get("genre") or "")[:80],
        "style": short(str(data.get("tone") or ""), 200),
    }
    if data.get("title") and (not project.get("title") or project.get("title") == "Truyện mới"):
        patch["title"] = str(data["title"])[:120]
    update_project(project_id, patch)
    meta = db.loads(project.get("meta"))
    meta["premise"] = data
    db.update("projects", project_id, {"meta": db.dumps(meta), "updated_at": now()})
    return data


def gen_bible(project_id: str, chapters: int = 6) -> dict:
    project = get_project(project_id)
    require_level(project, 4, "dựng kinh thánh truyện")
    messages = prompts.bible({**project, "tone": project.get("style")}, chapters)
    data, res = llm.chat_json(messages)
    _log_run(project_id, "bible", 4, res)
    if not isinstance(data, dict):
        raise ValueError("AI trả dữ liệu kinh thánh không hợp lệ")
    _replace_entities(project_id, data)
    return data


def gen_outline(project_id: str, chapters: int = 6) -> list[dict]:
    project = get_project(project_id)
    require_level(project, 4, "lập dàn ý")
    messages = prompts.outline(project, bible(project_id), chapters)
    data, res = llm.chat_json(messages)
    _log_run(project_id, "outline", 4, res)
    rows = data.get("chapters") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("AI không trả danh sách chương")
    db.x("DELETE FROM chapters WHERE project_id=?", (project_id,))
    for idx, row in enumerate(rows[: max(1, chapters)], start=1):
        chapter = {
            "id": db.new_id("chp"), "project_id": project_id, "idx": idx,
            "title": short(str(row.get("title") or f"Chương {idx}"), 120),
            "synopsis": str(row.get("synopsis") or ""),
            "hook": short(str(row.get("hook") or ""), 240),
            "status": "outline", "created_at": now(), "updated_at": now(),
        }
        db.insert("chapters", chapter)
        for bidx, beat in enumerate(row.get("beats") or [], start=1):
            if not isinstance(beat, dict):
                continue
            db.insert("beats", {
                "id": db.new_id("bet"), "chapter_id": chapter["id"], "project_id": project_id,
                "idx": bidx, "summary": str(beat.get("summary") or "")[:400],
                "intent": str(beat.get("intent") or "")[:300], "prose": "", "words": 0,
                "status": "planned", "created_at": now(), "updated_at": now(),
            })
    return db.q("SELECT * FROM chapters WHERE project_id=? ORDER BY idx", (project_id,))


def gen_beats(chapter_id: str, count: int = 3) -> list[dict]:
    chapter = db.get("chapters", chapter_id)
    if not chapter:
        raise ValueError("Không tìm thấy chương")
    project = get_project(chapter["project_id"])
    require_level(project, 4, "chia beat")
    messages = prompts.beats(project, bible(project["id"]), chapter, count)
    data, res = llm.chat_json(messages)
    _log_run(project["id"], "beats", 4, res)
    rows = data.get("beats") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("AI không trả beat nào")
    db.x("DELETE FROM beats WHERE chapter_id=? AND prose=''", (chapter_id,))
    start = (db.q1("SELECT MAX(idx) m FROM beats WHERE chapter_id=?", (chapter_id,)) or {}).get("m") or 0
    for i, beat in enumerate(rows, start=1):
        db.insert("beats", {
            "id": db.new_id("bet"), "chapter_id": chapter_id, "project_id": project["id"],
            "idx": start + i, "summary": str(beat.get("summary") or "")[:400],
            "intent": str(beat.get("intent") or "")[:300], "prose": "", "words": 0,
            "status": "planned", "created_at": now(), "updated_at": now(),
        })
    return db.q("SELECT * FROM beats WHERE chapter_id=? ORDER BY idx", (chapter_id,))


def clean_prose(text: str) -> str:
    """Bỏ vỏ JSON/markdown nếu model lỡ bọc đoạn văn (DeepSeek hay làm vậy)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            for key in ("content", "text", "prose", "result", "output", "paragraph", "story"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    break
    if text.startswith('"') and text.endswith('"'):
        try:
            decoded = json.loads(text)
            if isinstance(decoded, str):
                text = decoded
        except json.JSONDecodeError:
            pass
    return text.strip()


def gen_prose(beat_id: str, extra: str = "") -> dict:
    beat = db.get("beats", beat_id)
    if not beat:
        raise ValueError("Không tìm thấy beat")
    project = get_project(beat["project_id"])
    chapter = db.get("chapters", beat["chapter_id"])
    require_level(project, 3, "viết văn xuôi")
    previous = db.q(
        "SELECT prose FROM beats WHERE chapter_id=? AND idx<? AND prose<>'' ORDER BY idx DESC LIMIT 1",
        (beat["chapter_id"], beat["idx"]),
    )
    messages = prompts.prose(project, bible(project["id"]), chapter, beat,
                             previous[0]["prose"] if previous else "")
    if extra:
        messages[-1]["content"] += f"\n\nGhi chú thêm của tác giả: {extra}"
    # văn xuôi KHÔNG phải JSON: gọi thẳng chat(), đừng parse JSON
    res = llm.chat(messages, json_mode=False)
    _log_run(project["id"], "prose", 3, res)
    text = clean_prose(res.get("text") or "")
    if not text:
        raise ValueError("AI trả đoạn văn rỗng")
    db.update("beats", beat_id, {
        "prose": text, "words": syllables(text), "status": "written", "updated_at": now(),
    })
    db.update("chapters", beat["chapter_id"], {"status": "writing", "updated_at": now()})
    return db.get("beats", beat_id)


def polish(text: str, instruction: str = "") -> str:
    prompt = prompts.polish(text, instruction or "làm câu chữ gọn và giàu hình ảnh hơn")
    res = llm.chat(prompt, json_mode=False)
    return clean_prose(res.get("text") or "")


def project_prose(project_id: str, limit: int = 12000) -> str:
    rows = db.q(
        "SELECT b.prose, b.idx, c.idx chapter_idx, c.title FROM beats b "
        "JOIN chapters c ON c.id = b.chapter_id WHERE b.project_id=? AND b.prose<>'' "
        "ORDER BY c.idx, b.idx", (project_id,),
    )
    chunks = []
    for row in rows:
        chunks.append(row["prose"].strip())
    text = "\n\n".join(chunks)
    return text[:limit]


def gen_script(
    project_id: str,
    video_id: str | None = None,
    scenes_target: int = 8,
    max_syllables: int = 34,
    source: str = "",
    chapter_id: str | None = None,
    title_hint: str = "",
) -> dict:
    project = get_project(project_id)
    require_level(project, 4, "chuyển thể kịch bản")
    if not source:
        if chapter_id:
            rows = db.q(
                "SELECT prose FROM beats WHERE chapter_id=? AND prose<>'' ORDER BY idx",
                (chapter_id,),
            )
            source = "\n\n".join(r["prose"] for r in rows)
        source = source or project_prose(project_id)
    if not source:
        raise ValueError("Chưa có văn xuôi để chuyển thể. Viết beat trước, hoặc dán văn bản vào ô nguồn.")

    hook = db.loads(project.get("meta")).get("premise", {}).get("hook_line", "")
    messages = prompts.script(project, scenes_target, max_syllables, hook, source)
    data, res = llm.chat_json(messages)
    _log_run(project_id, "script", 4, res)
    scenes = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("AI không trả cảnh nào")

    video = db.get("videos", video_id) if video_id else None
    if not video:
        video = {
            "id": db.new_id("vid"), "project_id": project_id,
            "title": short(title_hint or str(data.get("title") or project["title"]), 90),
            "format": "short", "spec": db.dumps({}), "status": "draft",
            "created_at": now(), "updated_at": now(),
        }
        db.insert("videos", video)

    # mỗi video có danh sách cảnh riêng: xoá cảnh cũ của chính video này
    for row in db.q("SELECT scene_id FROM video_scenes WHERE video_id=?", (video["id"],)):
        db.delete("scenes", row["scene_id"])
    db.x("DELETE FROM video_scenes WHERE video_id=?", (video["id"],))

    created = []
    for idx, row in enumerate(scenes, start=1):
        if not isinstance(row, dict):
            continue
        narration = re.sub(r"\s+", " ", str(row.get("narration") or "")).strip()
        if not narration:
            continue
        narration = narration.strip("\"'“”")
        scene = {
            "id": db.new_id("scn"), "project_id": project_id, "chapter_id": chapter_id,
            "beat_id": "", "idx": idx,
            "title": short(str(row.get("title") or f"Cảnh {idx}"), 60),
            "narration": narration,
            "on_screen": short(str(row.get("on_screen") or "").strip(), 48),
            "visual_prompt": str(row.get("visual_prompt") or "")[:800],
            "mood": str(row.get("mood") or "")[:40],
            "art": "", "duration_ms": 0, "audio_path": "", "words": "[]",
            "status": "draft", "meta": db.dumps({"syllables": syllables(narration)}),
            "created_at": now(), "updated_at": now(),
        }
        db.insert("scenes", scene)
        db.insert("video_scenes", {"video_id": video["id"], "scene_id": scene["id"], "idx": idx})
        created.append(scene)

    spec = db.loads(video.get("spec"))
    spec.update({
        "title": str(data.get("title") or video["title"]),
        "description": str(data.get("description") or ""),
        "hashtags": data.get("hashtags") or [],
        "cover_text": str(data.get("cover_text") or ""),
    })
    db.update("videos", video["id"], {
        "title": short(title_hint or str(data.get("title") or video["title"]), 90),
        "spec": db.dumps(spec), "status": "scripted", "updated_at": now(),
    })
    if chapter_id:
        db.update("chapters", chapter_id, {"status": "scripted", "updated_at": now()})
    return {"video": db.get("videos", video["id"]), "scenes": created, "meta": spec}


def split_verbatim(text: str, target_syllables: int = 32, max_chars: int = 400) -> list[str]:
    """Chia cảnh **giữ nguyên văn**: cắt theo câu, không gọi AI, không mất chữ nào."""
    from .textutil import sentences as split_sentences

    text = (text or "").strip()
    if not text:
        return []
    sentences = split_sentences(text)
    if not sentences:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_syl = 0
    for sentence in sentences:
        size = syllables(sentence)
        too_long = current and (current_syl + size > target_syllables * 1.5 or
                                len(" ".join(current)) + len(sentence) > max_chars)
        if too_long:
            chunks.append(" ".join(current).strip())
            current, current_syl = [sentence], size
        else:
            current.append(sentence)
            current_syl += size
    if current:
        chunks.append(" ".join(current).strip())
    return [c for c in chunks if c]


def video_from_text(
    project_id: str,
    text: str,
    *,
    title: str = "",
    chapter_id: str | None = None,
    split: bool = True,
    target_syllables: int = 32,
    spec: dict | None = None,
    voice_profile: str | None = None,
) -> dict:
    """Tạo bản dựng trực tiếp từ văn bản có sẵn — không gọi AI (0 token).

    split=True: chia thành nhiều cảnh theo câu (giữ nguyên văn).
    split=False: cả truyện thành một cảnh duy nhất.
    """
    project = get_project(project_id)
    text = (text or "").strip()
    if not text:
        raise ValueError("Không có văn bản để dựng video")
    chunks = split_verbatim(text, target_syllables) if split else [text]

    video = {
        "id": db.new_id("vid"),
        "project_id": project_id,
        "title": short(title or f"{project['title']} — bản dựng", 90),
        "format": "short",
        "spec": db.dumps({**(spec or {}), "script_mode": "verbatim",
                          "voice_profile": voice_profile or (spec or {}).get("voice_profile")}),
        "status": "scripted",
        "created_at": now(),
        "updated_at": now(),
    }
    db.insert("videos", video)

    created = []
    for idx, chunk in enumerate(chunks, start=1):
        scene = {
            "id": db.new_id("scn"), "project_id": project_id, "chapter_id": chapter_id,
            "beat_id": "", "idx": idx,
            "title": short(chunk, 40),
            "narration": chunk,
            "on_screen": "", "visual_prompt": "", "mood": "",
            "art": "", "duration_ms": 0, "audio_path": "", "words": "[]",
            "status": "draft", "meta": db.dumps({"syllables": syllables(chunk), "verbatim": True}),
            "created_at": now(), "updated_at": now(),
        }
        db.insert("scenes", scene)
        db.insert("video_scenes", {"video_id": video["id"], "scene_id": scene["id"], "idx": idx})
        created.append(scene)

    if chapter_id:
        db.update("chapters", chapter_id, {"status": "scripted", "updated_at": now()})
    return {"video": db.get("videos", video["id"]), "scenes": created,
            "meta": db.loads(video["spec"])}


def chapter_text(chapter_id: str) -> str:
    rows = db.q("SELECT prose FROM beats WHERE chapter_id=? AND prose<>'' ORDER BY idx", (chapter_id,))
    return "\n\n".join(r["prose"] for r in rows if r["prose"]).strip()


def critique_video(video_id: str) -> dict:
    video = db.get("videos", video_id)
    if not video:
        raise ValueError("Không tìm thấy video")
    project = get_project(video["project_id"])
    require_level(project, 1, "đọc và nhận xét")
    rows = db.q(
        "SELECT s.narration FROM video_scenes vs JOIN scenes s ON s.id=vs.scene_id "
        "WHERE vs.video_id=? ORDER BY vs.idx", (video_id,),
    )
    text = "\n".join(r["narration"] for r in rows)
    data, res = llm.chat_json(prompts.critique(text))
    _log_run(project["id"], "critique", 1, res)
    return data if isinstance(data, dict) else {"score": 0, "problems": [], "fixes": []}
