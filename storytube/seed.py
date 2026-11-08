"""Dữ liệu mẫu: một truyện ngắn viết tay để chạy thử toàn bộ pipeline (không cần AI)."""

from __future__ import annotations

from . import db, story
from .config import project_dir
from .textutil import syllables

CHAPTERS = [
    {
        "title": "Người lên đèn",
        "synopsis": "Đêm mưa thứ ba, ông Bảy leo lên hải đăng và phát hiện một cô gái ngồi ở bậc thang cuối, ướt sũng, đến tìm cha.",
        "hook": "Cô gái nói tên mình là Linh.",
        "beats": [
            "Đêm thứ ba mưa không tắt. Ông Bảy vẫn leo một trăm hai mươi bậc đá lên ngọn hải đăng, tay xách can dầu, vai quàng chiếc khăn cũ đã sờn. Biển bên dưới đen như mực, chỉ có tiếng sóng đập vào chân đá là còn rõ. Ông đếm bậc theo thói quen, đếm đến bậc bốn mươi thì dừng, vì trên bậc thang cuối có một cái bóng người.",
            "Cô gái ngồi co ro, tóc ướt dính vào mặt, tay ôm chiếc ba lô rách. Cô ngẩng lên, mắt đỏ, giọng khàn: “Chú ơi, cháu tìm cha.” Ông Bảy đứng im, can dầu trong tay nặng như đá. Mười năm rồi mới có người nói câu đó với ông.",
        ],
    },
    {
        "title": "Lá thư trong ngăn kéo",
        "synopsis": "Ông Bảy đưa Linh vào phòng đá, pha trà. Trong ngăn kéo có một lá thư ông viết nhưng chưa từng gửi.",
        "hook": "Người nhận là Linh.",
        "beats": [
            "Ông mở cửa, đưa cô vào căn phòng đá. Ông pha trà, tay run đến mức nước tràn ra mặt bàn. Cô kể: cha cô tên Sơn, mười năm trước đi tàu, không về. Người ta bảo ông ấy từng giữ ngọn đèn này. Ông Bảy nghe, chỉ gật đầu, không nói rằng ông biết rõ hơn ai hết.",
            "Trong ngăn kéo dưới bàn có một lá thư ông chưa từng gửi. Phong bì đã ố, nét chữ nguệch ngoạc vì viết trong đêm. Người nhận là Linh. Người viết là ông. Ông đóng ngăn kéo lại, rồi mở ra lần nữa, như thể tự thuyết phục mình rằng nó vẫn còn ở đó.",
        ],
    },
    {
        "title": "Thì cũng là thư",
        "synopsis": "Ông Bảy đưa lá thư. Linh đọc và nhận ra giọng văn không phải của cha. Sáng hôm sau cô rời đi, ông đứng nhìn con tàu.",
        "hook": "Ông tự nhủ: ừ, thì cũng là thư.",
        "beats": [
            "Ông đưa lá thư cho cô. Cô đọc rất chậm, ngón tay lần theo từng dòng. Rồi cô hỏi, giọng không trách móc: “Chú viết giọng cha cháu à?” Ông không trả lời. Ngọn đèn ngoài kia quay, chiếu một vòng sáng qua cửa sổ rồi lại tối.",
            "Sáng hôm sau, ông tiễn cô ra bến. Cô không quay lại. Ông đứng đó, nghe tiếng còi tàu kéo dài, và tự nhủ: ừ, thì cũng là thư.",
        ],
    },
]

SCENES = [
    {
        "title": "Mưa đêm",
        "narration": "Đêm thứ ba, mưa không tắt. Ông Bảy vẫn leo một trăm hai mươi bậc đá lên ngọn hải đăng.",
        "on_screen": "Đêm thứ ba",
        "mood": "lanh",
        "visual_prompt": "A lone lighthouse on a rocky island at night, heavy rain, black sea, cinematic wide shot, cold blue tones, 35mm, film grain",
    },
    {
        "title": "Có người",
        "narration": "Trên bậc thang cuối, ông thấy một cô gái ngồi co ro, tóc ướt dính vào mặt, tay ôm chiếc ba lô rách.",
        "on_screen": "Có người ở đó",
        "mood": "toi",
        "visual_prompt": "Silhouette of a young woman sitting on wet stone stairs at night, rain, dim warm lamp light from above, cinematic, shallow depth of field",
    },
    {
        "title": "Tìm cha",
        "narration": "Cô nói mình tên Linh, đến tìm cha. Người ta bảo cha cô từng giữ ngọn đèn này, rồi biến mất mười năm trước.",
        "on_screen": "Tìm cha",
        "mood": "buon",
        "visual_prompt": "Close up of a soaked young Vietnamese woman looking up, rain drops on face, warm lantern light, emotional, cinematic portrait",
    },
    {
        "title": "Tách trà",
        "narration": "Ông Bảy mở cửa, đưa cô vào căn phòng đá. Ông pha trà, tay run đến mức nước tràn ra bàn.",
        "on_screen": "Tay ông run",
        "mood": "am",
        "visual_prompt": "Old stone room, two cups of tea on a wooden table, trembling hands, warm tungsten light, steam, cinematic still life",
    },
    {
        "title": "Ngăn kéo",
        "narration": "Trong ngăn kéo có một lá thư ông chưa từng gửi. Người nhận là Linh. Người viết là ông.",
        "on_screen": "Lá thư chưa gửi",
        "mood": "toi",
        "visual_prompt": "Extreme close up of an old yellowed envelope in a wooden drawer, handwriting, dust in a beam of light, cinematic macro",
    },
    {
        "title": "Đã hứa",
        "narration": "Mười năm trước, cha cô lên con tàu cuối cùng và không quay lại. Ông Bảy đã hứa sẽ viết thư, nhưng ông viết mãi không xong.",
        "on_screen": "Đã hứa",
        "mood": "buon",
        "visual_prompt": "Old cargo ship leaving a small island pier at dawn, fog, muted colors, wide cinematic shot, melancholic",
    },
    {
        "title": "Chú viết à",
        "narration": "Ông đưa lá thư cho cô. Cô đọc, rồi hỏi: chú viết giọng cha cháu à? Ông không trả lời. Ngọn đèn quay, chiếu sáng rồi lại tối.",
        "on_screen": "Chú viết à?",
        "mood": "lanh",
        "visual_prompt": "Lighthouse beam sweeping across a dark window, two silhouettes inside, one holding a letter, high contrast, cinematic",
    },
    {
        "title": "Bến tàu",
        "narration": "Sáng hôm sau, ông tiễn cô ra bến. Cô không quay lại. Ông đứng đó, nghe tiếng còi tàu, và tự nhủ: ừ, thì cũng là thư.",
        "on_screen": "Không quay lại",
        "mood": "tinh",
        "visual_prompt": "Old man standing alone on a small pier at sunrise, boat departing, soft golden haze, wide shot from behind, cinematic",
    },
]


def copy_sample_assets() -> int:
    """Chép video nền mẫu (samples/videos) vào data/assets/videos nếu thư mục còn trống."""
    from .config import APP_ROOT, DATA_DIR

    source = APP_ROOT / "samples" / "videos"
    target = DATA_DIR / "assets" / "videos"
    if not source.exists():
        return 0
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        return 0
    copied = 0
    for path in source.iterdir():
        if path.is_file() and path.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm"):
            (target / path.name).write_bytes(path.read_bytes())
            copied += 1
    return copied


def seed_demo(force: bool = False) -> dict:
    existing = db.q1("SELECT id FROM projects WHERE slug='nguoi-giu-den-bien'")
    if existing and not force:
        return {"project_id": existing["id"], "created": False}
    if existing:
        db.delete("projects", existing["id"])

    project = story.create_project("Người giữ đèn biển", "tâm lý - kỳ bí", level=4)
    story.update_project(project["id"], {
        "logline": "Một người giữ hải đăng viết thay lá thư của người bạn đã mất, để rồi phải đối diện với cô con gái đến tìm cha sau mười năm.",
        "style": "lạnh, day dứt, như lời kể đêm khuya",
    })
    db.update("projects", project["id"], {
        "meta": db.dumps({"premise": {
            "title": "Người giữ đèn biển",
            "logline": "Một người giữ hải đăng viết thay lá thư của người bạn đã mất, để rồi phải đối diện với cô con gái đến tìm cha sau mười năm.",
            "themes": ["sự thật", "tội lỗi nhỏ bé", "lòng tốt muộn màng"],
            "tone": "lạnh, day dứt, như lời kể đêm khuya",
            "hook_line": "Đêm thứ ba, có người đứng trên bậc thang cuối",
            "twist": "Lá thư là do ông Bảy tự viết, không phải của cha cô.",
        }}),
        "updated_at": db.now(),
    })

    chars = [
        ("Ông Bảy", "Người giữ đèn biển sáu mươi hai tuổi, sống một mình trong căn nhà đá dưới chân hải đăng."),
        ("Linh", "Cô gái hai mươi bốn tuổi, về đảo tìm cha sau mười năm mất liên lạc."),
        ("Sơn", "Cha của Linh, bạn thân của ông Bảy, mất tích trên chuyến tàu cuối cùng."),
    ]
    for name, summary in chars:
        db.insert("entities", {
            "id": db.new_id("ent"), "project_id": project["id"], "kind": "character",
            "name": name, "aliases": "", "summary": summary, "details": "{}",
            "color": "", "sort": 0, "created_at": db.now(),
        })
    for name, detail in [
        ("Hải đăng Côn Đảo", "Tháp đá trắng, một trăm hai mươi bậc, ngọn đèn quay mỗi hai mươi giây."),
        ("Phòng đá", "Nơi ông Bảy ở: bàn gỗ, ấm trà, ngăn kéo đựng thư."),
        ("Bến tàu cũ", "Bến nhỏ, mỗi tuần một chuyến, còi tàu dài."),
    ]:
        db.insert("entities", {
            "id": db.new_id("ent"), "project_id": project["id"], "kind": "location",
            "name": name, "aliases": "", "summary": detail, "details": "{}",
            "color": "", "sort": 0, "created_at": db.now(),
        })

    for idx, chapter in enumerate(CHAPTERS, start=1):
        chapter_id = db.new_id("chp")
        db.insert("chapters", {
            "id": chapter_id, "project_id": project["id"], "idx": idx,
            "title": chapter["title"], "synopsis": chapter["synopsis"], "hook": chapter["hook"],
            "status": "done", "created_at": db.now(), "updated_at": db.now(),
        })
        for bidx, text in enumerate(chapter["beats"], start=1):
            db.insert("beats", {
                "id": db.new_id("bet"), "chapter_id": chapter_id, "project_id": project["id"],
                "idx": bidx, "summary": text.split(".")[0][:160], "intent": "",
                "prose": text.strip(), "words": syllables(text),
                "status": "written", "created_at": db.now(), "updated_at": db.now(),
            })

    video = {
        "id": db.new_id("vid"), "project_id": project["id"], "title": "Người giữ đèn biển",
        "format": "short",
        "spec": db.dumps({
            "voice_profile": "nam-tram-am",
            "caption": {"name": "karaoke", "font": "Arial", "max_words": 4, "uppercase": False},
            "watermark": "@nguoigiu-den",
            "hook": True,
            "progress_bar": True,
            "ratios": ["9:16", "1:1", "16:9"],
        }),
        "status": "scripted", "created_at": db.now(), "updated_at": db.now(),
    }
    db.insert("videos", video)
    for idx, data in enumerate(SCENES, start=1):
        scene_id = db.new_id("scn")
        db.insert("scenes", {
            "id": scene_id, "project_id": project["id"], "chapter_id": None, "beat_id": None,
            "idx": idx, "title": data["title"], "narration": data["narration"],
            "on_screen": data["on_screen"], "visual_prompt": data["visual_prompt"],
            "mood": data["mood"], "art": "", "duration_ms": 0, "audio_path": "",
            "words": "[]", "status": "draft",
            "meta": db.dumps({"syllables": syllables(data["narration"])}),
            "created_at": db.now(), "updated_at": db.now(),
        })
        db.insert("video_scenes", {"video_id": video["id"], "scene_id": scene_id, "idx": idx})

    project_dir(project["slug"])
    return {"project_id": project["id"], "video_id": video["id"], "created": True}
