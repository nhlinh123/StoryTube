"""Phân tích truyện để đề xuất số cảnh / số tập — dựa trên số liệu thật, không gọi AI.

Ý tưởng: một video ngắn chỉ chứa được ~45–180 giây lời đọc. Truyện 5.000 chữ đọc hết
là ~25 phút, nên không thể nhồi vào một video. Hàm ở đây đo từng chương rồi chia thành
các tập vừa độ dài mục tiêu, mỗi cảnh ~30 âm tiết (6–8 giây) để phụ đề karaoke còn đọc kịp.
"""

from __future__ import annotations

import math

from . import db
from .config import load_config
from .textutil import syllables

DEFAULTS = {
    "target_seconds": 90,
    "syllables_per_second": 4.15,
    "syllables_per_scene": 30,
    "min_scenes": 3,
    "max_scenes": 24,
    "min_scene_seconds": 2.6,
}


def _speed(cfg: dict, voice_profile: str | None) -> float:
    """Tốc độ đọc (âm tiết/giây) sau khi áp rate của hồ sơ giọng."""
    conf = {**DEFAULTS, **(cfg.get("analysis") or {})}
    speed = float(conf["syllables_per_second"])
    try:
        from .tts import profile_of, _pct

        _, prof = profile_of(cfg, voice_profile)
        speed *= max(0.6, 1 + _pct(prof.get("rate")) / 100)
    except Exception:  # noqa: BLE001
        pass
    return max(2.0, speed)


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def analyze_project(
    project_id: str,
    chapter_id: str | None = None,
    target_seconds: int | None = None,
    voice_profile: str | None = None,
    cfg: dict | None = None,
) -> dict:
    cfg = cfg or load_config()
    conf = {**DEFAULTS, **(cfg.get("analysis") or {})}
    speed = _speed(cfg, voice_profile)
    target = int(target_seconds or conf["target_seconds"])
    syl_per_scene = int(conf["syllables_per_scene"])
    target_syl = target * speed

    chapters = db.q(
        "SELECT id, idx, title, synopsis FROM chapters WHERE project_id=? ORDER BY idx",
        (project_id,),
    )
    per_chapter: list[dict] = []
    for chapter in chapters:
        rows = db.q(
            "SELECT prose FROM beats WHERE chapter_id=? AND prose<>'' ORDER BY idx",
            (chapter["id"],),
        )
        text = "\n".join(r["prose"] for r in rows).strip()
        source = "prose"
        if not text:
            text = (chapter.get("synopsis") or "").strip()
            source = "synopsis" if text else "empty"
        syl = syllables(text) if text else 0
        read_seconds = round(syl / speed, 1) if syl else 0
        episodes = max(1, math.ceil(read_seconds / target)) if read_seconds else 0
        # cảnh cho một tập: đủ chứa phần lời đọc của tập, nhưng không ngắn hơn 2,6 giây/cảnh
        per_ep_syl = min(syl, target_syl) if syl else 0
        scenes = _clamp(math.ceil(per_ep_syl / syl_per_scene), conf["min_scenes"], conf["max_scenes"])
        if read_seconds:
            scenes = min(scenes, max(conf["min_scenes"], int(read_seconds // conf["min_scene_seconds"])))
        per_chapter.append({
            "id": chapter["id"],
            "idx": chapter["idx"],
            "title": chapter["title"],
            "words": len(text.split()) if text else 0,
            "syllables": syl,
            "read_seconds": read_seconds,
            "episodes": episodes,
            "scenes_per_episode": scenes if syl else 0,
            "source": source,
        })

    total_syl = sum(c["syllables"] for c in per_chapter)
    total_seconds = round(total_syl / speed, 1) if total_syl else 0
    total_words = sum(c["words"] for c in per_chapter)

    if chapter_id:
        chosen = [c for c in per_chapter if c["id"] == chapter_id]
        scope = chosen[0] if chosen else None
        episodes = scope["episodes"] if scope else 0
        scenes = scope["scenes_per_episode"] if scope else 0
    else:
        scope = None
        episodes = sum(c["episodes"] for c in per_chapter)
        # gộp cả truyện vào 1 video là quá dài -> lấy theo tập
        scenes = _clamp(math.ceil(target_syl / syl_per_scene), conf["min_scenes"], conf["max_scenes"])
        if total_syl:
            # nhưng không đề xuất nhiều cảnh hơn lượng chữ thật sự có
            scenes = min(scenes, max(conf["min_scenes"], math.ceil(total_syl / syl_per_scene)))
        elif not per_chapter:
            scenes = 0

    message = _message(per_chapter, target, episodes, total_seconds, chapter_id, scope, scenes)
    chapters_with_text = [c for c in per_chapter if c["syllables"]]
    return {
        "target_seconds": target,
        "speed_syllables_per_second": round(speed, 2),
        "totals": {
            "chapters": len(per_chapter),
            "words": total_words,
            "syllables": total_syl,
            "read_seconds": total_seconds,
            "read_text": _mmss(total_seconds),
            "episodes": sum(c["episodes"] for c in per_chapter),
        },
        "scope": {
            "chapter_id": chapter_id,
            "episodes": episodes,
            "scenes_per_episode": scenes,
            "suggested_scenes": scenes,
        },
        "plans": {
            "condensed": {
                "label": "Mỗi chương một video (cô đọng)",
                "episodes": len(chapters_with_text),
                "scenes_per_episode": scenes,
                "note": "giữ mạch truyện, AI lược bớt chi tiết cho vừa thời lượng",
            },
            "full": {
                "label": "Giữ chi tiết (chia nhỏ)",
                "episodes": sum(c["episodes"] for c in per_chapter),
                "scenes_per_episode": scenes,
                "note": "gần như đọc hết, mỗi chương 2–3 tập",
            },
        },
        "per_chapter": per_chapter,
        "message": message,
    }


def _mmss(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _message(chapters, target, episodes, total_seconds, chapter_id, scope, scenes) -> str:
    if not chapters:
        return "Truyện chưa có chương nào — lập dàn ý trước rồi hãy phân tích."
    if total_seconds <= 0:
        return "Chưa có văn xuôi trong các beat — viết beat hoặc dùng tóm tắt chương để ước lượng."

    read_text = _mmss(total_seconds)
    if chapter_id and scope:
        if scope["episodes"] > 1:
            return (
                f"Chương {scope['idx']} đọc hết khoảng {_mmss(scope['read_seconds'])} — dài hơn video "
                f"{target}s. Nên cắt thành {scope['episodes']} tập, mỗi tập ~{scope['scenes_per_episode']} cảnh "
                f"(hoặc để AI cô đọng lại còn ~{target}s)."
            )
        return (
            f"Chương {scope['idx']} đọc hết khoảng {scope['read_seconds']:.0f}s — vừa một video {target}s. "
            f"Đề xuất {scope['scenes_per_episode']} cảnh."
        )
    if total_seconds <= target * 1.2:
        return (
            f"Toàn truyện đọc hết khoảng {read_text} — vừa một video {target}s. "
            f"Đề xuất {scenes} cảnh."
        )
    return (
        f"Toàn truyện đọc hết khoảng {read_text} ({total_seconds / 60:.1f} phút) — không vừa một video "
        f"{target}s. Hai cách: (a) mỗi chương một video {target}s, AI cô đọng lại = {len([c for c in chapters if c['syllables']])} tập; "
        f"(b) giữ chi tiết = {episodes} tập. Mỗi tập ~{scenes} cảnh."
    )


def _scenes_for(target: int) -> int:
    return max(3, math.ceil(target * 4.15 / 30))
