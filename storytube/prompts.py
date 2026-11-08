"""Bộ prompt tiếng Việt cho pipeline truyện -> video.

Mỗi hàm trả về `messages` cho Chat Completions và luôn yêu cầu JSON đúng schema.
Model chỉ đề xuất; `story.py` kiểm tra rồi mới ghi vào DB.
"""

from __future__ import annotations

import json

SYSTEM_STORY = """Bạn là biên kịch và nhà văn Việt Nam, viết truyện ngắn để đọc thành video dọc.
Bạn viết văn xuôi tiếng Việt tự nhiên, giàu hình ảnh, câu ngắn, nhịp nhanh, thoại đời thường.
Bạn tôn trọng "kinh thánh truyện" (nhân vật, bối cảnh, giọng văn) đã có: không đổi tên, không đổi lai lịch, không thêm nhân vật lạ nếu không được yêu cầu.
Bạn chỉ trả về JSON hợp lệ đúng schema, không thêm giải thích, không dùng markdown."""

SYSTEM_SCRIPT = """Bạn là đạo diễn chuyển thể truyện thành video ngắn cho TikTok/Reels/Shorts.
Bạn chia truyện thành các cảnh ngắn, mỗi cảnh một ý, lời đọc viết cho TAI NGHE (không phải để đọc bằng mắt).
Bạn chỉ trả về JSON hợp lệ đúng schema, không thêm giải thích, không dùng markdown."""

SYSTEM_PROSE = """Bạn là nhà văn Việt Nam, viết truyện ngắn giàu hình ảnh, câu ngắn, nhịp nhanh, thoại đời thường.
Bạn chỉ trả về đúng đoạn văn xuôi cần viết: không JSON, không markdown, không tiêu đề, không ghi chú, không mở bài bằng lời dẫn."""

RULES_VI = """Quy tắc tiếng Việt:
- Xưng hô nhất quán theo nhân vật (anh/em, hắn/nàng, tôi/bạn...), không đổi giữa chừng.
- Không dùng từ ngữ hành chính, không dùng "và" liên tiếp, tránh câu bị động nặng.
- Số viết bằng chữ khi xuất hiện trong lời đọc (mười lăm, không viết 15).
- Không đặt tiêu đề chương trong lời đọc."""


def _u(content: str) -> dict:
    return {"role": "user", "content": content}


def _compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def premise(idea: str, genre: str = "", audience: str = "", length_hint: str = "") -> list[dict]:
    ask = f"""Ý tưởng thô: {idea}
Thể loại mong muốn: {genre or "tự chọn thể loại phù hợp, ưu tiên tâm lý - kỳ bí - đời thường"}
Khán giả: {audience or "người Việt 18-35 xem TikTok"}
Độ dài dự kiến: {length_hint or "truyện ngắn 1.200-2.000 chữ"}

Hãy thiết kế phần "xương sống" của truyện. Trả JSON:
{{
  "title": "tên truyện, 4-9 chữ, gợi tò mò",
  "logline": "một câu 20-35 chữ, có mâu thuẫn và cái giá phải trả",
  "genre": "thể loại cụ thể",
  "themes": ["2-3 chủ đề"],
  "tone": "giọng kể, ví dụ: lạnh, day dứt, như lời kể đêm khuya",
  "audience": "chân dung người xem",
  "promise": "cảm giác người xem nhận được khi xem hết",
  "twist": "cú lật ở cuối, một câu",
  "hook_line": "câu mở đầu tối đa 14 âm tiết, dùng được làm chữ to 2 giây đầu"
}}
{RULES_VI}"""
    return [{"role": "system", "content": SYSTEM_STORY}, _u(ask)]


def bible(project: dict, chapters: int = 6) -> list[dict]:
    ask = f"""Truyện: {project.get('title')}
Logline: {project.get('logline')}
Thể loại: {project.get('genre')}
Giọng kể: {project.get('tone') or project.get('style')}
Cú lật: {project.get('twist')}
Số chương dự kiến: {chapters}

Dựng "kinh thánh truyện" đủ để viết 6 chương mà không mâu thuẫn. Trả JSON:
{{
  "characters": [
    {{"name":"tên", "role":"vai trò", "age":"tuổi", "look":"ngoại hình 1 câu", "want":"điều muốn", "wound":"vết thương lòng", "arc":"thay đổi qua truyện", "voice":"cách nói, ví dụ: nói trống không, hay nuốt chữ"}}
  ],
  "locations": [{{"name":"", "detail":"không gian, mùi, ánh sáng, âm thanh"}}],
  "rules": ["luật của thế giới truyện, 2-4 điều"],
  "style": {{"pov":"ngôi kể", "tense":"thì", "diction":"từ ngữ", "pace":"nhịp", "motifs":["hình ảnh lặp"]}}
}}
Tối đa 5 nhân vật, 3 địa điểm. Tên người Việt, không trùng âm tiết với nhau."""
    return [{"role": "system", "content": SYSTEM_STORY}, _u(ask)]


def outline(project: dict, bible: dict, chapters: int = 6) -> list[dict]:
    ask = f"""Truyện: {project.get('title')}
Logline: {project.get('logline')}
Cú lật: {project.get('twist')}
Kinh thánh truyện: {_compact(bible)[:3500]}

Lập dàn ý {chapters} chương cho truyện ngắn. Mỗi chương 2-3 beat. Trả JSON:
{{
  "chapters": [
    {{
      "title": "tên chương, 2-6 chữ, không lộ nội dung",
      "synopsis": "3-4 câu tóm tắt diễn biến",
      "hook": "câu móc cuối chương, tối đa 20 chữ",
      "beats": [{{"summary":"một câu sự việc", "intent":"mục đích của beat này"}}]
    }}
  ]
}}
Chương 1 phải mở bằng một tình huống đang xảy ra, không hồi tưởng. Chương cuối phải trả cú lật."""
    return [{"role": "system", "content": SYSTEM_STORY}, _u(ask)]


def beats(project: dict, bible: dict, chapter: dict, count: int = 3) -> list[dict]:
    ask = f"""Truyện: {project.get('title')} — Chương {chapter.get('idx')}: {chapter.get('title')}
Tóm tắt chương: {chapter.get('synopsis')}
Kinh thánh truyện: {_compact(bible)[:2500]}

Chia chương thành {count} beat liền mạch, mỗi beat 150-350 chữ khi viết. Trả JSON:
{{"beats":[{{"summary":"sự việc chính trong 1 câu", "intent":"beat này làm gì cho người đọc", "pov_note":"ai nhìn, cảm giác gì"}}]}}"""
    return [{"role": "system", "content": SYSTEM_STORY}, _u(ask)]


def prose(project: dict, bible: dict, chapter: dict, beat: dict, previous: str = "") -> list[dict]:
    ask = f"""Truyện: {project.get('title')} — Chương {chapter.get('idx')}: {chapter.get('title')}
Giọng kể: {project.get('tone') or 'lạnh, day dứt'}
Kinh thánh truyện: {_compact(bible)[:2200]}
Đoạn văn ngay trước (để nối mạch): {previous[-900:] or '(đầu chương)'}

Viết beat sau thành văn xuôi 180-320 chữ:
- Sự việc: {beat.get('summary')}
- Mục đích: {beat.get('intent')}
- Góc nhìn: {beat.get('pov_note') or 'theo nhân vật chính'}

Yêu cầu: câu ngắn, có ít nhất một chi tiết giác quan (mùi, tiếng, nhiệt độ), có thoại nếu tự nhiên, kết beat bằng một câu mở sang beat sau. Không viết tiêu đề, không ghi chú, chỉ trả về đoạn văn."""
    return [{"role": "system", "content": SYSTEM_PROSE}, _u(ask)]


def script(
    project: dict,
    scenes_target: int,
    max_syllables: int,
    hook: str,
    source: str,
) -> list[dict]:
    ask = f"""Truyện: {project.get('title')}
Logline: {project.get('logline')}
Cú lật: {project.get('twist')}
Hook có sẵn: {hook}

Chuyển thể đoạn truyện sau thành {scenes_target} cảnh video dọc (mỗi cảnh 3-6 giây):
---
{source[:6000]}
---

Trả JSON:
{{
  "title": "tiêu đề video, tối đa 60 ký tự, có từ khoá tìm kiếm",
  "description": "2-3 câu mô tả đăng kèm, có câu hỏi cho người xem",
  "hashtags": ["#truyen", "#..."],
  "cover_text": "chữ trên ảnh bìa, tối đa 6 chữ",
  "scenes": [
    {{
      "title": "nhãn nội bộ 2-4 chữ",
      "narration": "lời đọc, tối đa {max_syllables} âm tiết, viết như đang nói, không markdown, không emoji",
      "on_screen": "chữ to hiện trên hình, 2-7 chữ, in hoa được, có thể để trống",
      "visual_prompt": "mô tả hình ảnh bằng tiếng Anh cho AI tạo ảnh: subject, setting, light, lens, mood, cinematic",
      "mood": "một từ: lạnh ấm dữ dội tĩnh lặng..."
    }}
  ]
}}

Quy tắc:
- Cảnh 1 là hook: câu hỏi hoặc tình huống bất thường, không giới thiệu lai lịch.
- Mỗi cảnh chỉ một ý; không lặp ý; không dùng từ nối kiểu "tiếp theo", "sau đó".
- Cảnh cuối kết bằng một câu lửng hoặc cú lật, mời bình luận.
- narration phải đọc trôi: không viết số, không viết tắt, không ngoặc kép.
- on_screen không trùng lặp nguyên văn narration.
{RULES_VI}"""
    return [{"role": "system", "content": SYSTEM_SCRIPT}, _u(ask)]


def polish(text: str, instruction: str = "làm câu chữ gọn và giàu hình ảnh hơn, giữ nguyên sự việc") -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROSE},
        _u(f"""Sửa đoạn văn sau: {instruction}. Giữ nguyên độ dài ±15%, giữ tên riêng và ngôi kể.
Chỉ trả về đoạn văn đã sửa, không giải thích, không JSON.

---
{text}
---"""),
    ]


def critique(text: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_SCRIPT},
        _u(f"""Đánh giá độ giữ chân của kịch bản video ngắn sau. Trả JSON:
{{"score": 0-100, "problems": ["..."], "fixes": ["..."]}}

---
{text[:4000]}
---"""),
    ]
