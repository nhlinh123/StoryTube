"""Hàng đợi job nền: lồng tiếng, dựng video, chạy cả pipeline.

Một worker duy nhất: TTS dễ bị giới hạn tốc độ và ffmpeg đã dùng hết CPU, chạy
song song chỉ làm hỏng thời gian chờ.
"""

from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path
from typing import Callable

from . import analyze, db, images, llm, media, render, story, tts
from .config import load_config, project_dir

QUEUE: "queue.Queue[str]" = queue.Queue()
_STARTED = threading.Event()
_LOCK = threading.Lock()
_CURRENT: str | None = None


def _update(job_id: str, **fields) -> None:
    if fields:
        db.update("jobs", job_id, fields)


def submit(kind: str, payload: dict) -> dict:
    job = {
        "id": db.new_id("job"),
        "kind": kind,
        "payload": db.dumps(payload),
        "status": "queued",
        "progress": 0,
        "message": "Trong hàng đợi",
        "result": "{}",
        "error": "",
        "created_at": db.now(),
    }
    db.insert("jobs", job)
    QUEUE.put(job["id"])
    ensure_worker()
    return job


def ensure_worker() -> None:
    with _LOCK:
        if _STARTED.is_set():
            return
        thread = threading.Thread(target=_loop, name="storytube-worker", daemon=True)
        thread.start()
        _STARTED.set()


def _loop() -> None:
    global _CURRENT
    while True:
        job_id = QUEUE.get()
        job = db.get("jobs", job_id)
        if not job or job["status"] == "canceled":
            QUEUE.task_done()
            continue
        _CURRENT = job_id
        _update(job_id, status="running", started_at=db.now(), message="Bắt đầu")
        try:
            handler = HANDLERS.get(job["kind"])
            if not handler:
                raise ValueError(f"Job lạ: {job['kind']}")
            result = handler(db.loads(job["payload"]), job_id)
            _update(job_id, status="done", progress=100, message="Xong",
                    result=db.dumps(result or {}), finished_at=db.now())
        except Exception as exc:  # noqa: BLE001
            trace = traceback.format_exc(limit=8)
            _update(job_id, status="error", message=str(exc)[:400],
                    error=trace[-3000:], finished_at=db.now())
        finally:
            _CURRENT = None
            QUEUE.task_done()


def _progress(job_id: str) -> Callable[[int, str], None]:
    def report(pct: int, message: str = "") -> None:
        _update(job_id, progress=max(0, min(100, int(pct))), message=message[:300])

    return report


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
def voice_scenes(payload: dict, job_id: str) -> dict:
    cfg = load_config()
    report = _progress(job_id)
    video_id = payload.get("video_id")
def _voice_video(video_id: str, profile: str | None, cfg: dict, report,
                 force: bool = False) -> list[dict]:
    """Lồng tiếng toàn bộ cảnh của một video. Dùng chung cho voice/full/autopilot."""
    rows = db.q(
        "SELECT s.* FROM video_scenes vs JOIN scenes s ON s.id=vs.scene_id "
        "WHERE vs.video_id=? ORDER BY vs.idx", (video_id,),
    )
    if not rows:
        raise ValueError("Không có cảnh nào để lồng tiếng")
    done = []
    for i, scene in enumerate(rows):
        report(int(92 * i / len(rows)), f"Lồng tiếng cảnh {i + 1}/{len(rows)}")
        if scene.get("audio_path") and not force and Path(scene["audio_path"]).exists():
            done.append({"scene_id": scene["id"], "skipped": True})
            continue
        project = db.get("projects", scene["project_id"])
        out_dir = project_dir(project["slug"]) / "audio" / scene["id"]
        result = tts.synthesize_scene(
            scene["narration"], out_dir, profile_name=profile, cfg=cfg,
        )
        db.update("scenes", scene["id"], {
            "audio_path": result.path,
            "duration_ms": result.duration_ms,
            "words": db.dumps(result.words),
            "status": "voiced",
            "updated_at": db.now(),
        })
        done.append({"scene_id": scene["id"], "duration_ms": result.duration_ms,
                     "provider": result.provider, "voice": result.voice,
                     "fallback": (result.meta or {}).get("fallback", "")})
    report(100, f"Đã lồng tiếng {len(done)} cảnh")
    return done


def voice_scenes(payload: dict, job_id: str) -> dict:
    cfg = load_config()
    report = _progress(job_id)
    video_id = payload.get("video_id")
    if not video_id:
        rows = db.q("SELECT * FROM scenes WHERE project_id=? ORDER BY idx",
                    (payload["project_id"],))
        if not rows:
            raise ValueError("Không có cảnh nào để lồng tiếng")
        video_id = rows[0]["id"]
        # lồng tiếng rời từng cảnh (không qua video)
        done = []
        for i, scene in enumerate(rows):
            report(int(92 * i / len(rows)), f"Lồng tiếng cảnh {i + 1}/{len(rows)}")
            if scene.get("audio_path") and not payload.get("force") and Path(scene["audio_path"]).exists():
                done.append({"scene_id": scene["id"], "skipped": True})
                continue
            project = db.get("projects", scene["project_id"])
            out_dir = project_dir(project["slug"]) / "audio" / scene["id"]
            result = tts.synthesize_scene(scene["narration"], out_dir,
                                          profile_name=payload.get("voice_profile"), cfg=cfg)
            db.update("scenes", scene["id"], {
                "audio_path": result.path, "duration_ms": result.duration_ms,
                "words": db.dumps(result.words), "status": "voiced", "updated_at": db.now(),
            })
            done.append({"scene_id": scene["id"], "duration_ms": result.duration_ms,
                         "provider": result.provider, "voice": result.voice})
        report(100, "Đã lồng tiếng")
        return {"scenes": done, "count": len(done)}
    done = _voice_video(video_id, payload.get("voice_profile"), cfg, report,
                        force=bool(payload.get("force")))
    return {"scenes": done, "count": len(done)}


def _render_ratios(video_id: str, ratios: list[str], quality: str, cfg: dict, report) -> list[dict]:
    results = []
    for i, ratio in enumerate(ratios):
        base = int(90 * i / len(ratios))
        def per_ratio(pct: int, msg: str, base=base, ratio=ratio, n=len(ratios)) -> None:
            report(base + int(pct * 0.9 / n), f"[{ratio}] {msg}")

        record = {
            "id": db.new_id("rnd"), "video_id": video_id, "ratio": ratio,
            "status": "running", "created_at": db.now(), "updated_at": db.now(),
            "settings": db.dumps({"quality": quality}),
        }
        db.insert("renders", record)
        try:
            info = render.render_video(video_id, ratio, quality=quality, progress=per_ratio, cfg=cfg)
            db.update("renders", record["id"], {
                "path": info["path"], "thumb": info["thumb"],
                "duration_ms": info["duration_ms"], "bytes": info["bytes"],
                "status": "done", "updated_at": db.now(),
                "settings": db.dumps(info.get("settings", {})),
            })
            # mỗi tỉ lệ chỉ có một file cuối: bỏ các bản ghi cũ cùng tỉ lệ
            db.x("DELETE FROM renders WHERE video_id=? AND ratio=? AND id<>?",
                 (video_id, ratio, record["id"]))
            results.append({"ratio": ratio, **info, "render_id": record["id"]})
        except Exception as exc:  # noqa: BLE001
            db.update("renders", record["id"], {
                "status": "error", "error": str(exc)[:2000], "updated_at": db.now(),
            })
            raise
    db.update("videos", video_id, {"status": "rendered", "updated_at": db.now()})
    report(100, "Đã dựng xong")
    return results


def render_ratios(payload: dict, job_id: str) -> dict:
    cfg = load_config()
    report = _progress(job_id)
    results = _render_ratios(payload["video_id"], payload.get("ratios") or ["9:16"],
                             payload.get("quality", "high"), cfg, report)
    return {"renders": results}


AUTOPILOT_MODES = ("video", "image", "gradient")


def autopilot(payload: dict, job_id: str) -> dict:
    """Tự làm cả serie: phân tích chương → kịch bản → (ảnh) → lồng tiếng → dựng."""
    cfg = load_config()
    report = _progress(job_id)
    project = db.get("projects", payload["project_id"])
    if not project:
        raise ValueError("Không tìm thấy truyện")
    level = int(project.get("level") or 0)
    if level < 4:
        raise ValueError(f"Tự động làm video cần Cấp 4 (đang cấp {level}) vì phải gọi AI viết kịch bản.")

    chapter_ids = payload.get("chapter_ids") or []
    chapters = [db.get("chapters", cid) for cid in chapter_ids]
    chapters = [c for c in chapters if c]
    source_text = (payload.get("source_text") or "").strip()
    if not chapters and not source_text:
        raise ValueError("Chưa chọn chương nào")

    target = int(payload.get("target_seconds") or 90)
    voice = payload.get("voice_profile")
    ratios = payload.get("ratios") or ["9:16"]
    quality = payload.get("quality", "high")
    background = payload.get("background") or dict(cfg["background"])
    if background.get("mode") not in AUTOPILOT_MODES:
        background["mode"] = "video"
    overlay = payload.get("overlay") or {
        "color": cfg["background"].get("overlay_color", "#000000"),
        "opacity": cfg["background"].get("overlay_opacity", 0.55),
    }
    caption = payload.get("caption") or dict(cfg["caption"])
    scenes_override = payload.get("scenes")
    script_mode = payload.get("script_mode") or "verbatim"   # verbatim | shorten
    split = bool(payload.get("split", True))
    target_syllables = int(payload.get("target_syllables") or 32)
    spec_base = {
        "voice_profile": voice, "background": background, "overlay": overlay,
        "caption": caption, "ratios": ratios, "watermark": payload.get("watermark", ""),
        "script_mode": script_mode,
    }

    def finish(video: dict, title: str, scenes_n: int, analysis_scope: dict | None,
               sub) -> dict:
        sub(58, "lồng tiếng")
        _voice_video(video["id"], voice, cfg, lambda pct, msg: sub(58 + pct * 0.15, msg))
        sub(75, "dựng video")
        _render_ratios(video["id"], ratios, quality, cfg,
                       lambda pct, msg: sub(75 + pct * 0.23, msg))
        return {"id": video["id"], "title": title, "scenes": scenes_n,
                "analysis": analysis_scope}

    created: list[dict] = []

    # 0) chế độ "dán truyện có sẵn": một video, không cần chương, không gọi AI
    if source_text:
        report(2, "Dựng video từ văn bản dán")
        result = story.video_from_text(
            project["id"], source_text, title=payload.get("title") or f"{project['title']} — bản dựng",
            split=split, target_syllables=target_syllables, spec=spec_base, voice_profile=voice,
        )
        video = result["video"]
        created.append(finish(video, video["title"], len(result["scenes"]), None,
                              lambda pct, msg: report(int(2 + pct * 0.96), msg)))
        report(100, "Xong 1 video")
        return {"videos": created}

    total = len(chapters)
    for i, chapter in enumerate(chapters):
        base = i * 100.0 / total
        span = 100.0 / total

        def sub(pct: float, msg: str, base=base, span=span, i=i) -> None:
            report(int(base + max(0.0, min(100.0, pct)) * span / 100.0),
                   f"[{i + 1}/{total}] {msg}")

        title = f"Chương {chapter['idx']} — {chapter['title']}"

        if script_mode == "shorten":
            # rút gọn bằng AI: cần phân tích để chọn số cảnh
            sub(1, f"Chương {chapter['idx']}: phân tích độ dài")
            analysis = analyze.analyze_project(
                project["id"], chapter_id=chapter["id"],
                target_seconds=target, voice_profile=voice, cfg=cfg,
            )
            scenes_n = int(scenes_override or analysis["scope"]["suggested_scenes"] or 6)
            video = {
                "id": db.new_id("vid"), "project_id": project["id"], "title": title,
                "format": "short", "spec": db.dumps({**spec_base, "script_mode": "shorten"}),
                "status": "draft", "created_at": db.now(), "updated_at": db.now(),
            }
            db.insert("videos", video)
            sub(6, f"viết kịch bản {scenes_n} cảnh (AI)")
            story.gen_script(project["id"], video_id=video["id"], scenes_target=scenes_n,
                             chapter_id=chapter["id"], title_hint=title)
            analysis_scope = analysis["scope"]
        else:
            # giữ nguyên văn: chia cảnh bằng code, 0 token
            sub(2, f"Chương {chapter['idx']}: chia cảnh giữ nguyên văn")
            text = story.chapter_text(chapter["id"]) or (chapter.get("synopsis") or "")
            if not text:
                report(0, f"Bỏ qua chương {chapter['idx']}: chưa có văn xuôi")
                continue
            result = story.video_from_text(
                project["id"], text, title=title, chapter_id=chapter["id"],
                split=split, target_syllables=target_syllables,
                spec=spec_base, voice_profile=voice,
            )
            video = result["video"]
            scenes_n = len(result["scenes"])
            analysis_scope = None

        if background.get("mode") == "image":
            rows = db.q(
                "SELECT s.id FROM video_scenes vs JOIN scenes s ON s.id=vs.scene_id "
                "WHERE vs.video_id=? ORDER BY vs.idx", (video["id"],))
            sub(40, "tạo ảnh nền")
            images.generate_for_scenes(
                [r["id"] for r in rows], cfg=cfg, aspect=ratios[0],
                progress=lambda pct, msg: sub(40 + pct * 0.15, msg),
            )

        created.append(finish(video, title, scenes_n, analysis_scope, sub))

    report(100, f"Xong {len(created)} video")
    return {"videos": created}


def full_video(payload: dict, job_id: str) -> dict:
    report = _progress(job_id)
    report(2, "Lồng tiếng")
    voiced = voice_scenes(payload, job_id)
    report(45, "Dựng video")
    rendered = render_ratios(payload, job_id)
    return {"voice": voiced, "render": rendered}


def story_pipeline(payload: dict, job_id: str) -> dict:
    report = _progress(job_id)
    project_id = payload["project_id"]
    chapters = int(payload.get("chapters", 4))
    beats_per_chapter = int(payload.get("beats", 2))
    scenes = int(payload.get("scenes", 8))
    report(4, "Dựng ý tưởng")
    story.gen_premise(project_id, payload.get("idea", ""))
    report(16, "Dựng kinh thánh truyện")
    story.gen_bible(project_id, chapters)
    report(30, "Lập dàn ý")
    story.gen_outline(project_id, chapters)
    rows = db.q("SELECT id FROM chapters WHERE project_id=? ORDER BY idx", (project_id,))[:chapters]
    total_beats = max(1, len(rows) * beats_per_chapter)
    written = 0
    for chapter in rows:
        beats = story.gen_beats(chapter["id"], beats_per_chapter)
        for beat in beats[:beats_per_chapter]:
            written += 1
            report(30 + int(30 * written / total_beats),
                   f"Viết beat {written}/{total_beats}")
            try:
                story.gen_prose(beat["id"])
            except Exception as exc:  # noqa: BLE001 - một beat lỗi không nên chặn cả mẻ
                _update(job_id, message=f"Bỏ qua một beat: {exc}"[:300])
    report(64, "Chuyển thể kịch bản")
    script = story.gen_script(project_id, scenes_target=scenes, max_syllables=payload.get("max_syllables", 34))
    video_id = script["video"]["id"]
    report(70, "Lồng tiếng")
    voice_scenes({"video_id": video_id, "voice_profile": payload.get("voice_profile")}, job_id)
    report(84, "Dựng video")
    rendered = render_ratios({
        "video_id": video_id,
        "ratios": payload.get("ratios") or ["9:16"],
        "quality": payload.get("quality", "high"),
    }, job_id)
    report(100, "Xong")
    return {"video_id": video_id, "script": script.get("meta", {}), "render": rendered}


def image_scenes(payload: dict, job_id: str) -> dict:
    cfg = load_config()
    report = _progress(job_id)
    video_id = payload.get("video_id")
    if video_id:
        rows = db.q(
            "SELECT s.* FROM video_scenes vs JOIN scenes s ON s.id=vs.scene_id "
            "WHERE vs.video_id=? ORDER BY vs.idx", (video_id,),
        )
        video = db.get("videos", video_id)
        spec = db.loads(video.get("spec")) if video else {}
        aspect = payload.get("aspect") or images.videos_aspect(spec)
    else:
        rows = db.q("SELECT * FROM scenes WHERE project_id=? ORDER BY idx", (payload["project_id"],))
        aspect = payload.get("aspect") or cfg["images"].get("aspect_ratio", "9:16")
    force = bool(payload.get("force"))
    scene_ids = [r["id"] for r in rows if force or not r.get("art")]
    if not scene_ids:
        report(100, "Mọi cảnh đã có ảnh")
        return {"images": [], "errors": [], "skipped": len(rows)}
    report(2, f"Tạo {len(scene_ids)} ảnh bằng ElevenLabs")
    result = images.generate_for_scenes(
        scene_ids,
        cfg=cfg,
        model=payload.get("model"),
        aspect=aspect,
        resolution=payload.get("resolution"),
        force=force,
        progress=report,
    )
    report(100, "Đã tạo ảnh")
    result["skipped"] = len(rows) - len(scene_ids)
    return result


HANDLERS = {
    "voice": voice_scenes,
    "render": render_ratios,
    "full": full_video,
    "story": story_pipeline,
    "images": image_scenes,
    "autopilot": autopilot,
}


def recent(limit: int = 20) -> list[dict]:
    return db.q("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))


def cancel(job_id: str) -> dict:
    job = db.get("jobs", job_id)
    if job and job["status"] == "queued":
        db.update("jobs", job_id, {"status": "canceled", "message": "Đã huỷ"})
    return db.get("jobs", job_id) or {}


def current_job() -> str | None:
    return _CURRENT


def doctor() -> dict:
    cfg = load_config()
    info: dict = {"ffmpeg": "", "version": "", "data": str(db.DB_PATH)}
    try:
        info["version"] = media.which_ffmpeg_version()
        info["ffmpeg"] = media.paths()[0]
    except media.MediaError:
        pass
    try:
        info["edge_voices"] = tts.list_edge_voices()
    except Exception:  # noqa: BLE001
        info["edge_voices"] = []
    info["llm_ready"] = llm.is_ready(cfg)
    try:
        name, conf = llm.provider_conf(cfg)
        info["llm"] = {
            "provider": name,
            "model": conf.get("model"),
            "base_url": conf.get("base_url"),
            "api_style": conf.get("api_style"),
            "key_source": conf.get("key_source_used") or "",
            "has_key": bool(conf.get("api_key")),
        }
    except Exception:  # noqa: BLE001
        info["llm"] = {}
    info["elevenlabs_ready"] = images.has_key(cfg)
    info["image_model"] = cfg.get("images", {}).get("model")
    info["default_voice"] = cfg.get("tts", {}).get("default_profile")
    try:
        voice_key, voice = tts.profile_of(cfg)
        info["voice_resolved"] = {"profile": voice_key, "provider": voice.get("provider"),
                                  "fallback_from": voice.get("_fallback_from", "")}
    except Exception:  # noqa: BLE001
        info["voice_resolved"] = {}
    return info
