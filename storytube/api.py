"""HTTP API + phục vụ giao diện web (thuần stdlib, không phụ thuộc framework)."""

from __future__ import annotations

import copy
import json
import mimetypes
import os
import re
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import analyze, db, images, jobs, llm, media, story, tts
from .config import DATA_DIR, load_config, masked, save_config, ensure_config
from .textutil import fmt_duration

WEB_DIR = Path(__file__).resolve().parent / "web"

ROUTES: list[tuple[str, str, str]] = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, pattern, fn.__name__))
        return fn

    return deco


class Api:
    """Gom handler thành method, tra cứu theo (method, pattern)."""

    def __init__(self) -> None:
        self.handlers = {}

    def add(self, method: str, pattern: str):
        regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")

        def deco(fn):
            self.handlers[(method, regex)] = fn
            return fn

        return deco

    def dispatch(self, method: str, path: str):
        for (m, regex), fn in self.handlers.items():
            if m != method:
                continue
            match = regex.match(path)
            if match:
                return fn, match.groupdict()
        return None, None


api = Api()


def media_url(path: str) -> str:
    """Đường dẫn tuyệt đối -> URL /media/... (chỉ trong thư mục dữ liệu)."""
    if not path:
        return ""
    try:
        rel = Path(path).resolve().relative_to(DATA_DIR.resolve())
        return "/media/" + rel.as_posix()
    except (ValueError, OSError):
        return ""


def ok(data, status: int = 200):
    return status, data


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def project_summary(row: dict) -> dict:
    counts = db.q1(
        "SELECT (SELECT COUNT(*) FROM scenes WHERE project_id=?) scenes,"
        " (SELECT COUNT(*) FROM videos WHERE project_id=?) videos,"
        " (SELECT COUNT(*) FROM renders r JOIN videos v ON v.id=r.video_id WHERE v.project_id=? AND r.status='done') renders",
        (row["id"], row["id"], row["id"]),
    ) or {}
    return {**row, "counts": counts}


@api.add("GET", "/api/state")
def state(_params, _body):
    cfg = load_config()
    rows = db.q("SELECT * FROM projects ORDER BY updated_at DESC")
    profiles = [
        {"name": k, "label": v.get("label", k), "provider": v.get("provider", ""),
         "voice": v.get("voice", "")}
        for k, v in cfg["tts"]["profiles"].items()
    ]
    ratios = [
        {"key": k, "label": v.get("label", k), "w": v["w"], "h": v["h"]}
        for k, v in cfg["render"]["ratios"].items()
    ]
    return ok({
        "projects": [project_summary(r) for r in rows],
        "config": {
            "level": cfg["ui"].get("level", 4),
            "default_voice": cfg["tts"].get("default_profile"),
            "voices": profiles,
            "ratios": ratios,
            "llm_ready": llm.is_ready(cfg),
            "llm_default": cfg["llm"].get("default"),
            "ffmpeg": bool(media.find_ffmpeg(cfg)["ffmpeg"]),
            "eleven_ready": images.has_key(cfg),
            "image_models": cfg["images"]["providers"]["elevenlabs"].get("models", []),
            "image_model": cfg["images"].get("model"),
        },
        "jobs": jobs.recent(12),
        "version": "0.1.0",
    })


@api.add("POST", "/api/projects")
def create_project(_params, body):
    title = (body.get("title") or "").strip()
    if not title:
        return 400, {"error": "Thiếu tên truyện"}
    project = story.create_project(title, body.get("genre", ""), body.get("idea", ""),
                                   int(body.get("level", load_config()["ui"].get("level", 4))))
    return ok({"project": project})


@api.add("GET", "/api/projects/{pid}")
def get_project(params, _body):
    project = db.get("projects", params["pid"])
    if not project:
        return 404, {"error": "Không tìm thấy truyện"}
    chapters = db.q("SELECT * FROM chapters WHERE project_id=? ORDER BY idx", (project["id"],))
    beats = db.q("SELECT * FROM beats WHERE project_id=? ORDER BY chapter_id, idx", (project["id"],))
    by_chapter: dict[str, list] = {}
    for beat in beats:
        by_chapter.setdefault(beat["chapter_id"], []).append(beat)
    scene_by_chapter = {
        row["chapter_id"]: row["c"] for row in db.q(
            "SELECT chapter_id, COUNT(*) c FROM scenes WHERE project_id=? AND chapter_id IS NOT NULL "
            "GROUP BY chapter_id", (project["id"],))
    }
    for chapter in chapters:
        chapter["beats"] = by_chapter.get(chapter["id"], [])
        chapter["scene_count"] = scene_by_chapter.get(chapter["id"], 0)
    videos = db.q("SELECT * FROM videos WHERE project_id=? ORDER BY created_at DESC", (project["id"],))
    for video in videos:
        video["renders"] = db.q(
            "SELECT * FROM renders WHERE video_id=? ORDER BY created_at DESC", (video["id"],)
        )
        for render in video["renders"]:
            render["url"] = media_url(render.get("path", ""))
            render["thumb_url"] = media_url(render.get("thumb", ""))
        video["spec"] = db.loads(video.get("spec"))
        video["scene_count"] = (db.q1(
            "SELECT COUNT(*) c FROM video_scenes WHERE video_id=?", (video["id"],)) or {}).get("c", 0)
        video["scene_ids"] = [
            r["scene_id"] for r in db.q(
                "SELECT scene_id FROM video_scenes WHERE video_id=? ORDER BY idx", (video["id"],))
        ]
    scenes = db.q("SELECT * FROM scenes WHERE project_id=? ORDER BY idx", (project["id"],))
    for scene in scenes:
        scene["words"] = db.loads(scene.get("words"), [])
    entities = db.q("SELECT * FROM entities WHERE project_id=? ORDER BY sort", (project["id"],))
    runs = db.q("SELECT * FROM ai_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 30",
                (project["id"],))
    return ok({
        "project": project,
        "entities": entities,
        "chapters": chapters,
        "scenes": scenes,
        "videos": videos,
        "runs": runs,
        "stats": {
            "words": sum(b.get("words") or 0 for b in beats),
            "chapters": len(chapters),
            "scenes": len(scenes),
            "duration": sum(s.get("duration_ms") or 0 for s in scenes),
            "duration_text": fmt_duration(sum(s.get("duration_ms") or 0 for s in scenes)),
        },
    })


@api.add("PATCH", "/api/projects/{pid}")
def patch_project(params, body):
    project = story.get_project(params["pid"])
    updated = story.update_project(project["id"], body)
    return ok({"project": updated})


@api.add("DELETE", "/api/projects/{pid}")
def delete_project(params, _body):
    project = db.get("projects", params["pid"])
    if project:
        db.delete("projects", project["id"])
    return ok({"deleted": bool(project)})


# --------------------------------------------------------------------------- #
# AI steps
# --------------------------------------------------------------------------- #
@api.add("POST", "/api/projects/{pid}/ai/premise")
def ai_premise(params, body):
    return ok({"premise": story.gen_premise(params["pid"], body.get("idea", ""))})


@api.add("POST", "/api/projects/{pid}/analyze")
def analyze_project(params, body):
    """Đề xuất số cảnh / số tập dựa trên độ dài thật của truyện (không tốn token)."""
    return ok({"analysis": analyze.analyze_project(
        params["pid"],
        chapter_id=body.get("chapter_id") or None,
        target_seconds=int(body["target_seconds"]) if body.get("target_seconds") else None,
        voice_profile=body.get("voice_profile") or None,
    )})


@api.add("POST", "/api/projects/{pid}/ai/bible")
def ai_bible(params, body):
    return ok({"bible": story.gen_bible(params["pid"], int(body.get("chapters", 6)))})


@api.add("POST", "/api/projects/{pid}/ai/outline")
def ai_outline(params, body):
    return ok({"chapters": story.gen_outline(params["pid"], int(body.get("chapters", 6)))})


@api.add("POST", "/api/chapters/{cid}/beats")
def ai_beats(params, body):
    return ok({"beats": story.gen_beats(params["cid"], int(body.get("count", 3)))})


@api.add("POST", "/api/beats/{bid}/write")
def ai_write(params, body):
    return ok({"beat": story.gen_prose(params["bid"], body.get("note", ""))})


@api.add("POST", "/api/beats/{bid}/polish")
def polish_beat(params, body):
    beat = db.get("beats", params["bid"])
    if not beat or not beat.get("prose"):
        return 400, {"error": "Beat chưa có văn xuôi để mài"}
    project = story.get_project(beat["project_id"])
    story.require_level(project, 2, "mài câu")
    text = story.polish(beat["prose"], body.get("instruction", ""))
    return ok({"text": text})


@api.add("PATCH", "/api/beats/{bid}")
def patch_beat(params, body):
    allowed = {"prose", "summary", "intent", "status"}
    data = {k: v for k, v in body.items() if k in allowed}
    if "prose" in data:
        from .textutil import syllables

        data["words"] = syllables(data["prose"])
        data["status"] = "written"
    if data:
        data["updated_at"] = db.now()
        db.update("beats", params["bid"], data)
    return ok({"beat": db.get("beats", params["bid"])})


@api.add("POST", "/api/projects/{pid}/pipeline")
def run_pipeline(params, body):
    project = story.get_project(params["pid"])
    level = int(project.get("level") or 0)
    if level < 5:
        return 403, {"error": f"Pipeline tự động cần Cấp 5 (đang cấp {level})."}
    payload = {
        "project_id": project["id"],
        "chapters": int(body.get("chapters", 4)),
        "beats": int(body.get("beats", 2)),
        "scenes": int(body.get("scenes", 8)),
        "ratios": body.get("ratios") or ["9:16"],
        "voice_profile": body.get("voice_profile"),
        "quality": body.get("quality", "high"),
        "idea": body.get("idea", ""),
    }
    return ok({"job": jobs.submit("story", payload)})


# --------------------------------------------------------------------------- #
# Scenes
# --------------------------------------------------------------------------- #
@api.add("POST", "/api/projects/{pid}/scenes")
def create_scene(params, body):
    project = story.get_project(params["pid"])
    idx = (db.q1("SELECT MAX(idx) m FROM scenes WHERE project_id=?", (project["id"],)) or {}).get("m", 0) + 1
    scene = {
        "id": db.new_id("scn"), "project_id": project["id"], "chapter_id": body.get("chapter_id"),
        "beat_id": body.get("beat_id"), "idx": idx,
        "title": body.get("title") or f"Cảnh {idx}",
        "narration": body.get("narration") or "",
        "on_screen": body.get("on_screen") or "",
        "visual_prompt": body.get("visual_prompt") or "",
        "mood": body.get("mood") or "", "art": "", "duration_ms": 0,
        "audio_path": "", "words": "[]", "status": "draft", "meta": "{}",
        "created_at": db.now(), "updated_at": db.now(),
    }
    db.insert("scenes", scene)
    # gắn ngay vào bản dựng để không thành cảnh mồ côi
    video_id = body.get("video_id")
    if video_id:
        pos = (db.q1("SELECT MAX(idx) m FROM video_scenes WHERE video_id=?", (video_id,)) or {}).get("m", 0) + 1
        video_scene = {"video_id": video_id, "scene_id": scene["id"], "idx": pos}
        try:
            db.insert("video_scenes", video_scene)
        except Exception:  # noqa: BLE001 - video không tồn tại
            pass
    return ok({"scene": scene})


@api.add("POST", "/api/chapters/{cid}/video")
def chapter_video(params, body):
    """Tạo bản dựng cho một chương: giữ nguyên văn (0 token) hoặc rút gọn bằng AI."""
    chapter = db.get("chapters", params["cid"])
    if not chapter:
        return 404, {"error": "Không tìm thấy chương"}
    project = story.get_project(chapter["project_id"])
    title = f"Chương {chapter['idx']} — {chapter['title']}"
    mode = body.get("mode") or "verbatim"
    voice = body.get("voice_profile")
    spec = {k: body[k] for k in ("background", "overlay", "caption", "ratios") if k in body}
    spec["voice_profile"] = voice

    if mode == "shorten":
        video = {
            "id": db.new_id("vid"), "project_id": project["id"], "title": title,
            "format": "short", "spec": db.dumps({**spec, "script_mode": "shorten"}),
            "status": "draft", "created_at": db.now(), "updated_at": db.now(),
        }
        db.insert("videos", video)
        result = story.gen_script(
            project["id"], video_id=video["id"],
            scenes_target=int(body.get("scenes", 6)),
            max_syllables=int(body.get("max_syllables", 34)),
            chapter_id=chapter["id"], title_hint=title,
        )
        return ok(result)

    text = story.chapter_text(chapter["id"]) or (chapter.get("synopsis") or "")
    if not text:
        return 400, {"error": "Chương chưa có văn xuôi để dựng (viết beat trước, hoặc dùng chế độ rút gọn)."}
    return ok(story.video_from_text(
        project["id"], text, title=title, chapter_id=chapter["id"],
        split=bool(body.get("split", True)),
        target_syllables=int(body.get("target_syllables") or 32),
        spec=spec, voice_profile=voice,
    ))


@api.add("POST", "/api/projects/{pid}/video-from-text")
def video_from_text(params, body):
    """TTS + ghép video từ một mẩu truyện có sẵn — không gọi AI."""
    project = story.get_project(params["pid"])
    text = (body.get("text") or "").strip()
    if not text:
        return 400, {"error": "Chưa dán văn bản nào"}
    spec = {k: body[k] for k in ("background", "overlay", "caption", "ratios") if k in body}
    return ok(story.video_from_text(
        project["id"], text,
        title=body.get("title") or f"{project['title']} — bản dựng",
        split=bool(body.get("split", True)),
        target_syllables=int(body.get("target_syllables") or 32),
        spec=spec, voice_profile=body.get("voice_profile"),
    ))


@api.add("POST", "/api/projects/{pid}/autopilot")
def autopilot(params, body):
    """Tự chạy cả serie: phân tích → (chia cảnh | AI rút gọn) → lồng tiếng → dựng."""
    project = story.get_project(params["pid"])
    scope = body.get("scope") or "all"
    chapter_ids = body.get("chapter_ids") or []
    if scope == "chapter" and body.get("chapter_id"):
        chapter_ids = [body["chapter_id"]]
    if scope == "all" and not body.get("source_text"):
        chapter_ids = [c["id"] for c in db.q(
            "SELECT id FROM chapters WHERE project_id=? ORDER BY idx", (project["id"],))]
    if not chapter_ids and not body.get("source_text"):
        return 400, {"error": "Chưa chọn chương nào"}
    payload = {
        "project_id": project["id"],
        "chapter_ids": chapter_ids,
        "source_text": (body.get("source_text") or "").strip(),
        "title": body.get("title", ""),
        "target_seconds": int(body.get("target_seconds") or 90),
        "script_mode": body.get("script_mode") or "verbatim",
        "split": bool(body.get("split", True)),
        "target_syllables": int(body.get("target_syllables") or 32),
        "background": body.get("background") or {},
        "overlay": body.get("overlay") or {},
        "caption": body.get("caption") or {},
        "ratios": body.get("ratios") or ["9:16"],
        "quality": body.get("quality", "high"),
        "voice_profile": body.get("voice_profile"),
        "watermark": body.get("watermark", ""),
    }
    return ok({"job": jobs.submit("autopilot", payload)})


@api.add("GET", "/api/assets/videos")
def list_background_videos(_params, _body):
    cfg = load_config()
    from . import render as render_mod

    items = []
    for path in render_mod.background_videos(cfg):
        info = media.probe(path)
        items.append({
            "name": path.name, "bytes": path.stat().st_size,
            "duration_ms": info.get("duration_ms", 0),
            "width": info.get("width", 0), "height": info.get("height", 0),
        })
    return ok({"videos": items, "dir": cfg["background"].get("videos_dir", "assets/videos")})


@api.add("PATCH", "/api/scenes/{sid}")
def patch_scene(params, body):
    allowed = {"narration", "on_screen", "visual_prompt", "mood", "art", "title", "duration_ms"}
    data = {k: v for k, v in body.items() if k in allowed}
    if data:
        data["updated_at"] = db.now()
        if "narration" in data or "art" in data:
            data["status"] = "draft"
            data["audio_path"] = ""
            data["words"] = "[]"
        db.update("scenes", params["sid"], data)
    return ok({"scene": db.get("scenes", params["sid"])})


@api.add("DELETE", "/api/scenes/{sid}")
def delete_scene(params, _body):
    db.delete("scenes", params["sid"])
    return ok({"deleted": True})


# --------------------------------------------------------------------------- #
# Videos
# --------------------------------------------------------------------------- #
@api.add("POST", "/api/projects/{pid}/videos")
def create_video(params, body):
    project = story.get_project(params["pid"])
    scene_ids = body.get("scene_ids") or [
        s["id"] for s in db.q("SELECT id FROM scenes WHERE project_id=? ORDER BY idx", (project["id"],))
    ]
    video = {
        "id": db.new_id("vid"), "project_id": project["id"],
        "title": body.get("title") or project["title"], "format": body.get("format", "short"),
        "spec": db.dumps(body.get("spec") or {}), "status": "draft",
        "created_at": db.now(), "updated_at": db.now(),
    }
    db.insert("videos", video)
    for idx, sid in enumerate(scene_ids, start=1):
        db.insert("video_scenes", {"video_id": video["id"], "scene_id": sid, "idx": idx})
    return ok({"video": video})


@api.add("PATCH", "/api/videos/{vid}")
def patch_video(params, body):
    video = db.get("videos", params["vid"])
    if not video:
        return 404, {"error": "Không tìm thấy video"}
    data = {}
    if "title" in body:
        data["title"] = body["title"]
    if "spec" in body:
        spec = db.loads(video.get("spec"))
        spec.update(body["spec"] or {})
        data["spec"] = db.dumps(spec)
    if "scene_ids" in body:
        db.x("DELETE FROM video_scenes WHERE video_id=?", (video["id"],))
        for idx, sid in enumerate(body["scene_ids"], start=1):
            db.insert("video_scenes", {"video_id": video["id"], "scene_id": sid, "idx": idx})
    if data:
        data["updated_at"] = db.now()
        db.update("videos", video["id"], data)
    return ok({"video": db.get("videos", video["id"])})


@api.add("POST", "/api/videos/{vid}/script")
def video_script(params, body):
    video = db.get("videos", params["vid"])
    if not video:
        return 404, {"error": "Không tìm thấy video"}
    if body.get("voice_profile"):
        spec = db.loads(video.get("spec"))
        spec["voice_profile"] = body["voice_profile"]
        db.update("videos", video["id"], {"spec": db.dumps(spec), "updated_at": db.now()})
    result = story.gen_script(
        video["project_id"], video_id=video["id"],
        scenes_target=int(body.get("scenes", 8)),
        max_syllables=int(body.get("max_syllables", 34)),
        source=body.get("source", ""),
        chapter_id=body.get("chapter_id"),
    )
    return ok(result)


@api.add("POST", "/api/videos/{vid}/voice")
def video_voice(params, body):
    payload = {
        "video_id": params["vid"],
        "voice_profile": body.get("voice_profile"),
        "force": bool(body.get("force")),
    }
    return ok({"job": jobs.submit("voice", payload)})


@api.add("POST", "/api/videos/{vid}/render")
def video_render(params, body):
    ratios = body.get("ratios") or ["9:16"]
    payload = {"video_id": params["vid"], "ratios": ratios, "quality": body.get("quality", "high")}
    return ok({"job": jobs.submit("render", payload)})


@api.add("POST", "/api/videos/{vid}/full")
def video_full(params, body):
    payload = {
        "video_id": params["vid"],
        "ratios": body.get("ratios") or ["9:16"],
        "voice_profile": body.get("voice_profile"),
        "quality": body.get("quality", "high"),
    }
    return ok({"job": jobs.submit("full", payload)})


@api.add("POST", "/api/videos/{vid}/critique")
def video_critique(params, _body):
    return ok({"critique": story.critique_video(params["vid"])})


# --------------------------------------------------------------------------- #
# Ảnh nền (ElevenLabs Image)
# --------------------------------------------------------------------------- #
@api.add("POST", "/api/videos/{vid}/images")
def video_images(params, body):
    payload = {
        "video_id": params["vid"],
        "model": body.get("model"),
        "resolution": body.get("resolution"),
        "force": bool(body.get("force")),
    }
    if body.get("aspect"):
        payload["aspect"] = body["aspect"]
    return ok({"job": jobs.submit("images", payload)})


@api.add("POST", "/api/scenes/{sid}/image")
def scene_image(params, body):
    cfg = load_config()
    info = images.generate_for_scene(
        params["sid"], cfg=cfg, model=body.get("model"),
        aspect=body.get("aspect"), resolution=body.get("resolution"),
        force=bool(body.get("force")),
    )
    return ok({"image": info})


@api.add("GET", "/api/images/status")
def images_status(_params, _body):
    cfg = load_config()
    return ok({
        "ready": images.has_key(cfg),
        "model": cfg["images"].get("model"),
        "models": cfg["images"]["providers"]["elevenlabs"].get("models", []),
        "aspect": cfg["images"].get("aspect_ratio"),
        "resolution": cfg["images"].get("resolution"),
    })


# --------------------------------------------------------------------------- #
# TTS / settings / jobs
# --------------------------------------------------------------------------- #
@api.add("GET", "/api/voices")
def voices(_params, _body):
    cfg = load_config()
    return ok({
        "profiles": [
            {"name": k, **{kk: vv for kk, vv in v.items() if kk != "post"}}
            for k, v in cfg["tts"]["profiles"].items()
        ],
        "providers": list(cfg["tts"]["providers"].keys()),
        "edge": tts.list_edge_voices(),
    })


@api.add("POST", "/api/tts/preview")
def tts_preview(_params, body):
    text = (body.get("text") or "Đêm ấy, trời mưa rất to.").strip()[:400]
    profile = body.get("voice_profile")
    out_dir = DATA_DIR / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = tts.synthesize_scene(text, out_dir, profile_name=profile)
    rel = Path(result.path).relative_to(DATA_DIR).as_posix()
    return ok({"url": f"/media/{rel}", "duration_ms": result.duration_ms,
               "words": result.words[:40], "provider": result.provider})


@api.add("GET", "/api/settings")
def get_settings(_params, _body):
    return ok({"config": masked(load_config())})


def merge_settings(base: dict, incoming: dict) -> dict:
    """Gộp cấu hình gửi từ UI vào config hiện tại, **giữ nguyên key đã lưu**.

    Quy tắc:
    - dict lồng nhau thì đệ quy (không thay cả object, tránh xoá field khác);
    - field `*api_key` gửi lên rỗng hoặc "***" thì giữ key cũ;
    - còn lại thì ghi đè.
    """
    out = copy.deepcopy(base)

    def walk(dst: dict, src: dict) -> None:
        for key, value in src.items():
            if isinstance(value, dict) and isinstance(dst.get(key), dict):
                walk(dst[key], value)
                continue
            if str(key).endswith("api_key") and (value in ("", None, "***") or value == ""):
                continue
            dst[key] = value

    walk(out, incoming or {})
    return out


@api.add("POST", "/api/settings")
def post_settings(_params, body):
    incoming = body.get("config") or {}
    cfg = merge_settings(load_config(), incoming)
    save_config(cfg)
    return ok({"config": masked(cfg)})


@api.add("POST", "/api/settings/test-llm")
def test_llm(_params, body):
    provider = body.get("provider")
    ok_flag, msg = llm.test_connection(load_config(), provider)
    return ok({"ok": ok_flag, "message": msg})


@api.add("POST", "/api/settings/test-eleven")
def test_eleven(_params, _body):
    """Kiểm tra key ElevenLabs: quyền đọc quota + gọi thử TTS 1 từ."""
    ok_flag, msg = images.check_key(load_config())
    return ok({"ok": ok_flag, "message": msg})


@api.add("GET", "/api/jobs")
def list_jobs(_params, _body):
    return ok({"jobs": jobs.recent(30)})


@api.add("GET", "/api/jobs/{jid}")
def get_job(params, _body):
    job = db.get("jobs", params["jid"])
    return (200, {"job": job}) if job else (404, {"error": "Không có job"})


@api.add("POST", "/api/jobs/{jid}/cancel")
def cancel_job(params, _body):
    return ok({"job": jobs.cancel(params["jid"])})


@api.add("GET", "/api/doctor")
def doctor(_params, _body):
    return ok(jobs.doctor())


@api.add("GET", "/api/events/{pid}")
def events(params, _body):
    return ok({"runs": db.q(
        "SELECT * FROM ai_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 50",
        (params["pid"],))})


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "StoryTube/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        if os.environ.get("STORYTUBE_VERBOSE"):
            super().log_message(fmt, *args)

    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path, download: bool = False) -> None:
        if not path.exists() or not path.is_file():
            self._send_json(404, {"error": "Không có file"})
            return
        size = path.stat().st_size
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if range_header:
            match = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if match:
                if match.group(1):
                    start = int(match.group(1))
                if match.group(2):
                    end = min(int(match.group(2)), size - 1)
                status = 206
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Cache-Control", "public, max-age=60")
        self.end_headers()
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        if path.startswith("/api/"):
            handler, params = api.dispatch("GET", path)
            if handler:
                try:
                    status, payload = handler(params or {}, {})
                except Exception as exc:  # noqa: BLE001
                    status, payload = 500, {"error": str(exc)}
                return self._send_json(status, payload)
            return self._send_json(404, {"error": "API không tồn tại"})
        if path.startswith("/media/"):
            rel = path[len("/media/"):]
            target = (DATA_DIR / rel).resolve()
            if not str(target).startswith(str(DATA_DIR.resolve())):
                return self._send_json(403, {"error": "Ngoài vùng dữ liệu"})
            return self._serve_file(target, download="download=1" in parsed.query)
        return self._serve_static(path)

    def _serve_static(self, path: str) -> None:
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())):
            return self._send_json(403, {"error": "Cấm"})
        if target.is_dir():
            target = target / "index.html"
        if target.exists():
            return self._serve_file(target)
        # SPA fallback
        index = WEB_DIR / "index.html"
        if index.exists():
            return self._serve_file(index)
        self._send_json(404, {"error": "Chưa có giao diện"})

    def do_POST(self) -> None:  # noqa: N802
        self._handle_write("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle_write("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle_write("DELETE")

    def _handle_write(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return self._send_json(400, {"error": "JSON không hợp lệ"})
        handler, params = api.dispatch(method, path)
        if not handler:
            return self._send_json(404, {"error": "API không tồn tại"})
        try:
            status, payload = handler(params or {}, body)
        except story.LevelError as exc:
            status, payload = 403, {"error": str(exc)}
        except (ValueError, KeyError) as exc:
            status, payload = 400, {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            status, payload = 500, {"error": str(exc)}
        self._send_json(status, payload)


def serve(host: str | None = None, port: int | None = None, open_browser: bool = False) -> None:
    ensure_config()
    db.init_db()
    db.cleanup_stale()
    cfg = load_config()
    host = host or cfg["server"]["host"]
    port = port or int(cfg["server"]["port"])
    jobs.ensure_worker()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    url = f"http://{host}:{port}"
    print(f"StoryTube đang chạy: {url}")
    print(f"Dữ liệu: {DATA_DIR}")
    if open_browser:
        import webbrowser

        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDừng.")
    finally:
        httpd.server_close()
