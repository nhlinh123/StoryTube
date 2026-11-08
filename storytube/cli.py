"""CLI: storytube serve | demo | list | doctor | voices | tts | script | voice | render | pipeline"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import config, db, jobs, llm, media, seed, story, tts
from .config import DATA_DIR, ensure_config, load_config


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _print_job(job_id: str) -> dict:
    last = ""
    while True:
        job = db.get("jobs", job_id) or {}
        line = f"[{job.get('progress', 0):3d}%] {job.get('message', '')}"
        if line != last:
            print("\r" + line.ljust(90), end="", flush=True)
            last = line
        if job.get("status") in ("done", "error", "canceled"):
            print()
            if job["status"] == "error":
                print(job.get("error") or job.get("message"), file=sys.stderr)
            return job
        time.sleep(0.8)


def _run(kind: str, payload: dict) -> dict:
    job = jobs.submit(kind, payload)
    jobs.ensure_worker()
    return _print_job(job["id"])


def cmd_serve(args) -> int:
    from .api import serve

    serve(host=args.host, port=args.port, open_browser=args.open)
    return 0


def cmd_demo(args) -> int:
    result = seed.seed_demo(force=args.force)
    copied = seed.copy_sample_assets()
    print(("Đã tạo" if result["created"] else "Đã có") + " truyện mẫu: Người giữ đèn biển")
    if copied:
        print(f"Đã chép {copied} video nền mẫu vào data/assets/videos")
    print(f"  project: {result['project_id']}")
    print(f"  video:   {result.get('video_id', '-')}")
    print("\nChạy tiếp:")
    print(f"  python -m storytube voice {result.get('video_id')}")
    print(f"  python -m storytube render {result.get('video_id')} --ratios 9:16,1:1,16:9")
    return 0


def cmd_list(_args) -> int:
    rows = db.q("SELECT * FROM projects ORDER BY updated_at DESC")
    if not rows:
        print("Chưa có truyện nào. Tạo bằng: python -m storytube demo")
        return 0
    for row in rows:
        counts = db.q1(
            "SELECT (SELECT COUNT(*) FROM scenes WHERE project_id=?) scenes,"
            " (SELECT COUNT(*) FROM videos WHERE project_id=?) videos,"
            " (SELECT COUNT(*) FROM renders r JOIN videos v ON v.id=r.video_id WHERE v.project_id=?) renders",
            (row["id"], row["id"], row["id"]),
        )
        print(f"{row['id']}  {row['title'][:38]:38s}  cấp {row['level']}  "
              f"{counts['scenes']} cảnh  {counts['videos']} bản dựng  {counts['renders']} file video")
    return 0


def cmd_analyze(args) -> int:
    from . import analyze as analyze_mod

    project = db.get("projects", args.project)
    if not project:
        print("Không thấy project", file=sys.stderr)
        return 1
    chapter_id = None
    if args.chapter:
        chapter_id = (db.q1("SELECT id FROM chapters WHERE project_id=? AND idx=?",
                            (project["id"], args.chapter)) or {}).get("id")
        if not chapter_id:
            print(f"Không có chương {args.chapter}", file=sys.stderr)
            return 1
    result = analyze_mod.analyze_project(project["id"], chapter_id=chapter_id,
                                         target_seconds=args.target)
    print(result["message"])
    print(f"\n{'#':>2}  {'chương':32s} {'chữ':>5} {'lời đọc':>8} {'tập':>3} {'cảnh/tập':>8}")
    for c in result["per_chapter"]:
        print(f"{c['idx']:>2}  {c['title'][:32]:32s} {c['words']:>5} "
              f"{c['read_seconds']:>7.0f}s {c['episodes']:>3} {c['scenes_per_episode']:>8}")
    scope = result["scope"]
    print(f"\nĐề xuất cho phạm vi đang chọn: {scope['suggested_scenes']} cảnh"
          f" ({scope['episodes']} tập nếu chia theo độ dài)")
    return 0


def cmd_autopilot(args) -> int:
    project = db.get("projects", args.project)
    if not project:
        print("Không thấy project", file=sys.stderr)
        return 1
    chapter_ids = []
    if args.chapter:
        cid = (db.q1("SELECT id FROM chapters WHERE project_id=? AND idx=?",
                     (project["id"], args.chapter)) or {}).get("id")
        if not cid:
            print(f"Không có chương {args.chapter}", file=sys.stderr)
            return 1
        chapter_ids = [cid]
    elif not args.text_file:
        chapter_ids = [c["id"] for c in db.q(
            "SELECT id FROM chapters WHERE project_id=? ORDER BY idx", (project["id"],))]

    source_text = ""
    if args.text_file:
        source_text = Path(args.text_file).read_text(encoding="utf-8")

    payload = {
        "project_id": project["id"],
        "chapter_ids": chapter_ids,
        "source_text": source_text,
        "target_seconds": args.target,
        "script_mode": args.mode,
        "split": not args.no_split,
        "target_syllables": args.syllables,
        "background": {"mode": args.bg, "source": args.bg_source, "file": args.bg_file},
        "overlay": {"color": args.overlay_color, "opacity": args.opacity},
        "caption": {"name": "karaoke", "position": args.position},
        "ratios": [r.strip() for r in args.ratios.split(",") if r.strip()],
        "quality": args.quality,
        "voice_profile": args.voice,
    }
    job = _run("autopilot", payload)
    if job.get("status") != "done":
        return 1
    result = db.loads(job.get("result"), {})
    for video in result.get("videos") or []:
        print(f"  {video['title']} · {video['scenes']} cảnh · id {video['id']}")
    return 0


def cmd_doctor(_args) -> int:
    info = jobs.doctor()
    print(f"ffmpeg : {info.get('ffmpeg') or '(chưa có)'}")
    print(f"version: {info.get('version') or '-'}")
    print(f"data   : {info.get('data')}")
    llm_info = info.get("llm") or {}
    print(f"LLM    : {llm_info.get('provider')}/{llm_info.get('model')} "
          f"({llm_info.get('api_style')}) key từ {llm_info.get('key_source') or '—'} "
          f"→ {'sẵn sàng' if info.get('llm_ready') else 'CHƯA DÙNG ĐƯỢC'}")
    print(f"ElevenLabs: {'có key' if info.get('elevenlabs_ready') else 'chưa có key'} "
          f"· model ảnh {info.get('image_model')}")
    voice = info.get("voice_resolved") or {}
    extra = f" (đang rơi về từ {voice.get('fallback_from')})" if voice.get("fallback_from") else ""
    print(f"giọng mặc định: {voice.get('profile')} · {voice.get('provider')}{extra}")
    voices = info.get("edge_voices") or []
    print(f"giọng Edge tiếng Việt: {', '.join(v['name'] for v in voices) or '(không lấy được danh sách)'}")
    return 0


def cmd_keys(args) -> int:
    keys = config.save_keys(args.deepseek or "", args.elevenlabs or "", args.elevenlabs or "")
    print("Đã lưu key vào data/config.json")
    for name, conf in keys["llm"]["providers"].items():
        if conf.get("api_key"):
            print(f"  llm.{name}: {conf['api_key'][:6]}…{conf['api_key'][-4:]}")
    elf = keys["tts"]["providers"]["elevenlabs"].get("api_key")
    if elf:
        print(f"  elevenlabs: {elf[:6]}…{elf[-4:]}")
    if args.test:
        ok_llm, msg = llm.test_connection(keys)
        print(f"  test LLM: {'OK' if ok_llm else 'LỖI'} — {msg}")
        if elf:
            from . import images

            ok_el, msg_el = images.check_key(keys)
            print(f"  test ElevenLabs: {'OK' if ok_el else 'LỖI'} — {msg_el}")
    return 0


def cmd_image(args) -> int:
    payload = {
        "video_id": args.video,
        "model": args.model or None,
        "resolution": args.resolution or None,
        "force": args.force,
    }
    if args.aspect:
        payload["aspect"] = args.aspect
    job = _run("images", payload)
    if job.get("status") != "done":
        return 1
    result = db.loads(job.get("result"), {})
    print(f"Đã tạo {len(result.get('images') or [])} ảnh, {len(result.get('errors') or [])} lỗi")
    for err in result.get("errors") or []:
        print("  lỗi:", err)
    return 0


def cmd_voices(args) -> int:
    rows = tts.list_edge_voices()
    if not rows:
        print("Không lấy được danh sách giọng (mạng?).")
    for row in rows:
        print(f"{row['name']:28s} {row['gender']:8s} {row['locale']}")
    cfg = load_config()
    print("\nHồ sơ giọng có sẵn:")
    for key, prof in cfg["tts"]["profiles"].items():
        print(f"  {key:16s} {prof.get('label', ''):32s} {prof['provider']}/{prof['voice']}")
    return 0


def cmd_tts(args) -> int:
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    result = tts.synthesize_scene(args.text, out.parent, profile_name=args.voice)
    print(f"{result.path}  {result.duration_ms} ms  {len(result.words)} từ  ({result.provider}/{result.voice})")
    return 0


def cmd_script(args) -> int:
    project = db.get("projects", args.project)
    if not project:
        print("Không thấy project", file=sys.stderr)
        return 1
    source = ""
    if args.file:
        source = Path(args.file).read_text(encoding="utf-8")
    data = story.gen_script(project["id"], scenes_target=args.scenes,
                            max_syllables=args.max_syllables, source=source)
    print(f"Đã tạo {len(data['scenes'])} cảnh cho video {data['video']['id']}")
    print(f"Tiêu đề: {data['meta'].get('title')}")
    return 0


def cmd_voice(args) -> int:
    job = _run("voice", {"video_id": args.video, "voice_profile": args.voice, "force": args.force})
    return 0 if job.get("status") == "done" else 1


def cmd_render(args) -> int:
    ratios = [r.strip() for r in args.ratios.split(",") if r.strip()]
    job = _run("render", {"video_id": args.video, "ratios": ratios, "quality": args.quality})
    if job.get("status") != "done":
        return 1
    rows = db.q("SELECT * FROM renders WHERE video_id=? AND status='done' ORDER BY created_at DESC LIMIT ?",
                (args.video, len(ratios)))
    for row in rows:
        print(f"  {row['ratio']:6s} {media.seconds(row['duration_ms']):6.1f}s  {row['path']}")
    return 0


def cmd_pipeline(args) -> int:
    ratio_list = [r.strip() for r in args.ratios.split(",") if r.strip()]
    job = _run("story", {
        "project_id": args.project, "chapters": args.chapters, "beats": args.beats,
        "scenes": args.scenes, "ratios": ratio_list, "quality": args.quality,
    })
    return 0 if job.get("status") == "done" else 1


def cmd_export(args) -> int:
    project = db.get("projects", args.project)
    if not project:
        print("Không thấy project", file=sys.stderr)
        return 1
    lines = [f"# {project['title']}", "", f"*{project.get('logline') or ''}*", ""]
    chapters = db.q("SELECT * FROM chapters WHERE project_id=? ORDER BY idx", (project["id"],))
    for chapter in chapters:
        lines += [f"## Chương {chapter['idx']}: {chapter['title']}", "", chapter.get("synopsis") or "", ""]
        beats = db.q("SELECT * FROM beats WHERE chapter_id=? ORDER BY idx", (chapter["id"],))
        for beat in beats:
            if beat.get("prose"):
                lines += [beat["prose"].strip(), ""]
    out = Path(args.out)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Đã xuất {out} ({len(lines)} dòng)")
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8()
    ensure_config()
    db.init_db()
    parser = argparse.ArgumentParser(
        prog="storytube",
        description="StoryTube — viết truyện, lồng tiếng tiếng Việt, dựng video dọc/ngang.",
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("serve", help="mở giao diện web")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--open", action="store_true", help="tự mở trình duyệt")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("demo", help="tạo truyện mẫu để thử")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("list", help="liệt kê truyện")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("doctor", help="kiểm tra ffmpeg, TTS, LLM")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("analyze", help="đề xuất số cảnh / số tập theo độ dài truyện")
    p.add_argument("project")
    p.add_argument("--chapter", type=int, default=0, help="chỉ phân tích chương N (1-based)")
    p.add_argument("--target", type=int, default=90, help="độ dài video mục tiêu (giây)")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("autopilot", help="tự làm video: chia cảnh → lồng tiếng → dựng")
    p.add_argument("project")
    p.add_argument("--chapter", type=int, default=0, help="chỉ làm chương N (bỏ trống = tất cả)")
    p.add_argument("--text-file", default="", help="dùng file .txt/.md làm nguồn (truyện có sẵn)")
    p.add_argument("--mode", default="verbatim", choices=["verbatim", "shorten"])
    p.add_argument("--no-split", action="store_true", help="cả truyện thành một cảnh")
    p.add_argument("--syllables", type=int, default=32)
    p.add_argument("--target", type=int, default=90)
    p.add_argument("--bg", default="video", choices=["video", "image", "gradient"])
    p.add_argument("--bg-source", default="random", choices=["random", "fixed"])
    p.add_argument("--bg-file", default="")
    p.add_argument("--opacity", type=float, default=0.5)
    p.add_argument("--overlay-color", default="#000000")
    p.add_argument("--position", default="tiktok", choices=["tiktok", "youtube", "center", "upper"])
    p.add_argument("--ratios", default="9:16")
    p.add_argument("--quality", default="high", choices=["high", "draft"])
    p.add_argument("--voice", default=None)
    p.set_defaults(func=cmd_autopilot)

    p = sub.add_parser("keys", help="lưu API key (DeepSeek / ElevenLabs)")
    p.add_argument("--deepseek", default="", help="key sk-... của platform.deepseek.com")
    p.add_argument("--elevenlabs", default="", help="key ElevenLabs (dùng cho cả giọng đọc và tạo ảnh)")
    p.add_argument("--test", action="store_true", help="gọi thử ngay sau khi lưu")
    p.set_defaults(func=cmd_keys)

    p = sub.add_parser("image", help="tạo ảnh nền cho các cảnh bằng ElevenLabs")
    p.add_argument("video")
    p.add_argument("--model", default="", help="gemini-3.1-flash-image | bytedance-seedream-5-lite | ...")
    p.add_argument("--aspect", default="", help="9:16 | 4:5 | 1:1 | 16:9")
    p.add_argument("--resolution", default="", help="1K | 2K | 4K")
    p.add_argument("--force", action="store_true", help="tạo lại cả cảnh đã có ảnh")
    p.set_defaults(func=cmd_image)

    p = sub.add_parser("voices", help="liệt kê giọng đọc")
    p.set_defaults(func=cmd_voices)

    p = sub.add_parser("tts", help="đọc thử một câu")
    p.add_argument("text")
    p.add_argument("--out", default=str(DATA_DIR / "preview" / "test.wav"))
    p.add_argument("--voice", default=None)
    p.set_defaults(func=cmd_tts)

    p = sub.add_parser("script", help="AI chuyển thể văn xuôi thành cảnh")
    p.add_argument("project")
    p.add_argument("--scenes", type=int, default=8)
    p.add_argument("--max-syllables", type=int, default=34)
    p.add_argument("--file", default="", help="dùng file .md/.txt làm nguồn thay vì văn xuôi trong DB")
    p.set_defaults(func=cmd_script)

    p = sub.add_parser("voice", help="lồng tiếng toàn bộ cảnh của video")
    p.add_argument("video")
    p.add_argument("--voice", default=None)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_voice)

    p = sub.add_parser("render", help="dựng video theo tỉ lệ")
    p.add_argument("video")
    p.add_argument("--ratios", default="9:16")
    p.add_argument("--quality", default="high", choices=["high", "draft"])
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("pipeline", help="chạy cả pipeline bằng AI (cần cấp 5)")
    p.add_argument("project")
    p.add_argument("--chapters", type=int, default=3)
    p.add_argument("--beats", type=int, default=2)
    p.add_argument("--scenes", type=int, default=8)
    p.add_argument("--ratios", default="9:16")
    p.add_argument("--quality", default="high")
    p.set_defaults(func=cmd_pipeline)

    p = sub.add_parser("export", help="xuất bản thảo ra markdown")
    p.add_argument("project")
    p.add_argument("--out", default="story.md")
    p.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
