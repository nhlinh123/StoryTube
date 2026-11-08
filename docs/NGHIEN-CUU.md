# Nghiên cứu & thiết kế StoryTube

Tài liệu này ghi lại những gì đã đọc, những gì đã chọn và lý do — để sau này sửa
tool vẫn biết vì sao nó như hiện tại.

---

## 1. xnovelist: luồng viết truyện đáng bê nguyên tắc

Repo: <https://github.com/giapnguyen74/xnovelist> (Next.js 15 static export, React 19,
Tiptap, IndexedDB, BYOAI).

### 1.1 Nó là gì

Ứng dụng viết tiểu thuyết **chạy hoàn toàn phía client**, không backend, bản thảo nằm
trong IndexedDB. AI là tùy chọn: cắm key của bạn (OpenAI/OpenRouter/Anthropic) hoặc
trỏ vào Ollama/LM Studio. Không có proxy, không thuê bao.

Điểm đáng học nhất không phải công nghệ, mà là **cách kiểm soát AI**:

| Cơ chế | Nội dung |
|---|---|
| Cấp AI 0–5 | 0 tắt · 1 chỉ đọc/nhận xét · 2 sửa đoạn bôi đen · 3 viết trong beat · 4 soạn cảnh · 5 tác nhân chạy nhiều bước |
| "Proposer / harness" | Model là hàm thuần: prompt vào, JSON ra. **Không** function-calling, **không** để model quyết định bước tiếp theo. Harness (code) xếp lịch từng bước. |
| Accept / Reject | Mọi kết quả AI là một đề xuất trong Agent panel; chỉ khi người dùng bấm Accept mới ghi vào bản thảo |
| Story Bible | Nhân vật, địa điểm, giọng văn, mạch liên tục — context nhỏ nhưng chất, được lọc theo tên xuất hiện trong đoạn đang xét |
| Prompt theo ngôn ngữ truyện | UI một ngôn ngữ, prompt theo ngôn ngữ tác phẩm (`prompts/packs/{lang}.json`) |
| Kiểm tra hậu kỳ cục bộ | Giữ tên nhân vật/địa điểm, giữ đại từ, Jaccard chống lạc đề, cắt theo length policy |
| Audit | Mọi lần gọi ghi tool, model, token; reasoning bị tách khỏi output |

### 1.2 Những gì StoryTube giữ

1. **Đúng pipeline**: ý tưởng → kinh thánh → dàn ý chương → beat → văn xuôi → (mở rộng) kịch bản cảnh.
2. **Đúng phân tách**: model chỉ trả JSON; `story.py` kiểm tra schema, chuẩn hoá, ghi SQLite.
3. **Đúng cấp AI**: mỗi tool khai báo cấp tối thiểu; `require_level()` chặn ở một chỗ duy nhất.
4. **Đúng audit**: bảng `ai_runs` ghi mọi lần gọi — không có bước chạy ngầm.

### 1.3 Những gì phải đổi

| xnovelist | StoryTube | Vì sao |
|---|---|---|
| IndexedDB trong trình duyệt | SQLite + file trên đĩa | Cần lưu audio, video, render; cần worker chạy ffmpeg |
| Browser gọi thẳng LLM | Python gọi LLM (urllib) | Không vướng CORS, giữ key khỏi localStorage |
| Accept/Reject từng diff | Sửa trực tiếp + audit log | Người dùng là một mình bạn; diff làm chậm vòng lặp video |
| Chỉ có chữ | Thêm tầng "kịch bản cảnh" | Video cần đơn vị ngắn: 1 cảnh = 1 ý = 1 lần đọc |

---

## 2. Luồng build của StoryTube

```
[người dùng]  ý tưởng thô
     │
     ├─(AI, cấp 4) premise      → logline, twist, hook_line        → projects.meta
     ├─(AI, cấp 4) bible        → nhân vật/bối cảnh/luật/giọng     → entities
     ├─(AI, cấp 4) outline      → chương + beat tóm tắt             → chapters, beats
     ├─(AI, cấp 3) prose        → 180-320 chữ / beat                → beats.prose
     ├─(AI, cấp 4) script       → cảnh: lời đọc, chữ to, mood, ảnh  → scenes, video_scenes
     │
     ├─(TTS)       voice        → scene.wav + mốc thời gian từng từ → scenes.audio_path
     └─(ffmpeg)    render       → mp4 theo từng tỉ lệ + cover.jpg    → renders
```

**Ranh giới quyết định**: 6 bước đầu là "đề xuất" (có thể sửa tay từng chữ). Ba bước
cuối là "thực thi" (tất định): cùng một cảnh + cùng một profile giọng luôn ra cùng
một file. Đây là lý do có thể render lại 5 tỉ lệ mà không gọi AI lần nào.

### 2.1 Vì sao kịch bản cảnh tách khỏi văn xuôi

Văn xuôi để đọc bằng mắt: câu dài, nhiều mệnh đề, ẩn dụ chồng. Lời đọc để nghe bằng tai:
1 ý/câu, 25–35 âm tiết, không số, không viết tắt, không ngoặc kép. Nếu TTS đọc thẳng văn
xuôi, video sẽ dài, rời rạc và khó giữ chân. Bước `script` là nơi chuyển hoá đó, có luật
riêng trong `prompts.script()`:

- cảnh 1 là hook (câu hỏi/tình huống bất thường), không giới thiệu lai lịch;
- mỗi cảnh một ý, không lặp, không "tiếp theo", "sau đó";
- cảnh cuối lửng hoặc lật, mời bình luận;
- `on_screen` ≤ 7 chữ, không trùng nguyên văn lời đọc.

---

## 3. TTS tiếng Việt

### 3.1 Các lựa chọn đã khảo sát

| Giải pháp | Giọng tiếng Việt | Chi phí | Offline | Ghi chú |
|---|---|---|---|---|
| **Edge TTS** (endpoint đọc của Edge) | `vi-VN-NamMinhNeural` (nam), `vi-VN-HoaiMyNeural` (nữ) | 0đ, không cần key | Không | Chất lượng neural của Azure; endpoint công khai hay bị chặn/ngắt kết nối tùy mạng — phải retry |
| **Azure Speech** | cùng 2 giọng trên | 500k ký tự/tháng miễn phí (F0), sau đó ~$15/1M | Không | Ổn định, chính thức, có SSML đầy đủ |
| **FPT.AI TTS v5** | `minhquan`, `leminh`, `banmai`, `thuminh`… | 100k ký tự/tháng miễn phí; gói từ 500kđ | Không | Giọng Việt bản địa, trả link audio bất đồng bộ |
| **ElevenLabs** | multilingual v2 (clone được) | Trả phí theo ký tự | Không | Cảm xúc tốt nhất; hợp khi cần giọng riêng của kênh |
| **OpenAI TTS** | `gpt-4o-mini-tts` | Trả phí | Không | Điều khiển được phong cách bằng `instructions` |
| **Google Translate TTS** | một giọng vi duy nhất | 0đ, không key | Không | Máy móc hơn neural nhưng rất bền kết nối — dùng làm đường dự phòng |
| **VietTTS** (mã nguồn mở, CosyVoice-based) | 24 giọng mẫu + clone từ file | 0đ | Có | Cần Python 3.10 + torch + GPU; **model CC BY-NC**, không dùng thương mại |
| **Piper** | vài giọng vi_VN cộng đồng | 0đ | Có | Nhẹ, nhanh, chất lượng thấp hơn neural |

Kết luận: **mặc định Edge** (0đ, chất lượng tốt) + **Azure** làm đường ổn định (cùng
giọng, chỉ khác endpoint) + **FPT** khi cần giọng Việt bản địa. VietTTS/Piper để dành
cho ai muốn offline hoàn toàn.

### 3.2 Công thức "giọng trầm ấm"

Không có giọng nam trầm nào dựng sẵn cho tiếng Việt ở các dịch vụ phổ thông, nên phải
ghép ba lớp:

1. **Chọn giọng gốc nam**: `NamMinh` (Edge/Azure) hoặc `minhquan` (FPT).
2. **Hạ cao độ bằng engine**: `pitch=-14Hz` (Edge/Azure hiểu trực tiếp).
3. **Hạ cao độ bằng ffmpeg** (cho provider không hỗ trợ pitch):
   `asetrate=48000*0.93 → aresample → atempo=1.0753` — hạ ~1,2 cung nhưng trả lại tốc độ,
   nên không bị "chậm như rùa".
4. **EQ + nén** (`VOICE_POST["warm-deep"]`):
   - `highpass=55` cắt ù dưới;
   - `+4,5 dB @110 Hz` cho phần ngực;
   - `−2 dB @380 Hz` bớt "ù mũi";
   - `−1,5 dB @3 kHz` bớt chói;
   - `acompressor` 3.2:1 để giọng đều;
   - `loudnorm I=−14 LUFS` chuẩn nền tảng.

Đây là mức "trầm ấm để kể chuyện đêm", không phải giọng nam trầm kiểu MC. Nếu muốn
trầm hơn nữa, hạ `pitch` xuống −20 Hz và tăng `g=6` ở 100 Hz — nhưng dưới −20 Hz giọng
bắt đầu méo và mất phụ âm cuối.

### 3.3 Chuẩn hoá tiếng Việt trước khi đọc

TTS đọc sai nếu gặp: số (`15` → "mười lăm"), viết tắt (`TP.HCM`, `GS`, `km`), ký hiệu
(`%`, `&`), markdown, emoji, ngoặc kép. `textutil.normalize_for_tts()` xử lý tất cả,
gồm cả đọc số thành chữ có "linh/mốt/tư/lăm" đúng chuẩn và đọc giờ (`19:30` → "mười
chín giờ ba mươi").

### 3.4 Canh thời gian cho phụ đề

Cách làm hiện tại: **tách câu → synth từng câu → đo thời lượng thật → chia thời lượng
đó cho các từ theo trọng số ký tự**. Ưu điểm: mốc neo theo câu là thật, sai số chỉ
trong một câu (thường < 150 ms). Nhược điểm: không phải mốc từng từ chính xác tuyệt đối.

Đường nâng cấp khi cần khớp tuyệt đối: dùng forced alignment (WhisperX / Montreal
Forced Aligner) trên chính file `scene.wav` để lấy mốc từng từ, thay cho hàm
`word_timings()`. Không dùng `WordBoundary` của Edge vì khi synth theo câu, sự kiện này
trả về không ổn định.

---

### 3.5 DeepSeek: dùng đúng wire mà DSH dùng

DSH (DeepSeek Harness) không gọi `chat/completions` mà gọi **Anthropic Messages**:
`https://api.deepseek.com/anthropic/v1/messages`, header `x-api-key` +
`anthropic-version: 2023-06-01`, system tách riêng, trả về `content[].text`.
Vì vậy `llm.py` có hai wire: `api_style: "openai"` và `"anthropic"` (tự suy ra từ
base_url nếu chứa `/anthropic`).

**Bài học đo được:** token trong `~/.dsh/.credentials.yaml` là token phiên đăng nhập
(issuer `platform.deepseek.com`, 64 ký tự, không phải `sk-…`). Thử cả `x-api-key` lẫn
`Authorization: Bearer` trên cả hai endpoint → `401 {"message":"Authentication Fails,
Your api key: ****xxxx is invalid"}`. Nên tool **không** tự lấy token đó (chỉ dùng khi
đặt `key_source: "dsh"` để debug) và báo rõ cần key `sk-…`.

### 3.6 ElevenLabs: những gì gói Free chặn (đo thực tế)

| Endpoint | Free tier | Ghi chú |
|---|---|---|
| `POST /v1/text-to-speech/{voice_id}` với voice **thư viện** | `402 paid_plan_required` "Free users cannot use library voices via the API" | Sang Trương, Trần Thanh, cả Rachel |
| `POST /v1/text-to-speech/{voice_id}` với voice **dựng sẵn** | OK | Adam `pNInz6obpgDQGcFmaJgB`, Daniel `onwK4e9ZLuTAKqWW03F9`, Sarah |
| `eleven_v3`, `eleven_flash_v2_5`, `eleven_turbo_v2_5` | OK | `eleven_multilingual_v2` trả 400 (đã bị thay) |
| `GET /v1/user`, `GET /v1/voices` | `401 missing_permissions` | key thiếu scope `user_read` / `voices_read` |
| `POST /v1/flows/image` | `402` "requires a Pro plan or above" | ảnh ElevenLabs chỉ từ Pro |

Vì vậy profile giọng có `fallback_voices` (thử lần lượt), và ảnh có
`provider_order: ["elevenlabs", "pollinations"]` — ElevenLabs trước, nếu bị chặn thì
Pollinations (flux, miễn phí, không key) và cắt logo ở đáy.



## 4. Video: tỉ lệ, vùng an toàn, encode

### 4.1 Thông số nền tảng (2026, ước lượng — UI các nền tảng đổi liên tục)

| Nền tảng | Tỉ lệ chuẩn | Kích thước | Ghi chú |
|---|---|---|---|
| TikTok | 9:16 | 1080×1920 | Nội dung dọc; chừa đáy cho caption/UI, chừa phải cho nút tương tác |
| Instagram Reels | 9:16 | 1080×1920 | Vùng UI dày hơn TikTok ở đáy |
| YouTube Shorts | 9:16 | 1080×1920 | Chừa đáy ít hơn |
| Instagram / Facebook feed | 4:5 | 1080×1350 | Chiếm nhiều diện tích feed nhất |
| Pinterest | 3:4 / 2:3 | 1080×1440 | |
| YouTube / Facebook ngang | 16:9 | 1920×1080 | |
| Ảnh bìa / carousel | 1:1 | 1080×1080 | |

StoryTube khai báo vùng an toàn theo pixel trong `config.json → render.ratios[].safe`
(`top`, `bottom`, `side`). Phụ đề luôn được neo theo vùng này, nên cùng một file `.ass`
dùng cho mọi tỉ lệ mà không bị UI che.

> Các con số an toàn nên kiểm tra lại mỗi quý: TikTok/IG thay đổi chiều cao thanh caption
> khá thường xuyên. Cách kiểm tra nhanh: render một cảnh, mở trên app thật, xem chữ có bị
> che không, rồi chỉnh `safe.bottom`.

### 4.2 Kiến trúc render (3 lượt)

```
cảnh 1..N ──► [lượt 1] mỗi cảnh: nền + Ken Burns/gradient  → scene-000.mp4 (im lặng, đúng độ dài)
                     └──► [lượt 2] concat -c copy            → visual.mp4
audio cảnh ──► pad đúng độ dài từng cảnh ──► concat          → narration.wav ──► mix.wav (+ BGM ducking, loudnorm)
                     └──► [lượt 3] subtitles + mux audio     → <tên>-<tỉ lệ>.mp4
```

Vì sao tách lượt:

- Đổi phụ đề/watermark **không phải render lại cảnh** — lượt 3 rất nhanh.
- Đổi tỉ lệ chỉ cần chạy lại cả 3 lượt cho tỉ lệ đó; cảnh được cache theo thư mục.
- Lượt 2 dùng `-c copy` nên gần như tức thời.

### 4.3 Encode

`libx264`, `yuv420p`, 30 fps, CRF 20 (draft CRF 26), preset `medium`, AAC 192 kbps
48 kHz stereo, `+faststart` để phát ngay khi tải. Loudness chuẩn hoá −14 LUFS / −1,5 dBTP
(mức các nền tảng tự chuẩn hoá về, nên đặt trước sẽ không bị hụt tiếng).

### 4.4 Phụ đề

Sinh file `.ass` với `PlayResX/Y` = kích thước chuẩn của tỉ lệ, nên khi render 720p hay
1080p chữ vẫn đúng tỉ lệ. Bốn kiểu:

- **karaoke**: 3–4 từ/trang, từ đang đọc đổi màu bằng `\k` (libass tự chạy);
- **block**: cả câu, 2 dòng, fade;
- **beast**: chữ to, in hoa, pop scale;
- **minimal**: nhỏ, không viền dày.

Chữ hook dùng `\t` để pop nhẹ trong 0,3 s. Thanh tiến trình vẽ bằng ASS drawing
(`\p1`) 120 bước — không tốn thêm filter, không tăng bitrate.

### 4.5 Vì sao dùng ffmpeg thay vì Remotion (đã có sẵn trong `C:\Works\MMO\remotion-videos`)

Remotion rất mạnh khi cần **template động phức tạp** (component React, animation theo
frame, hiệu ứng đồ hoạ). Nhưng với video kể chuyện, 90% công việc là: cắt/ghép ảnh, chạy
Ken Burns, burn phụ đề theo mốc thời gian, trộn tiếng. Những việc đó:

- ffmpeg làm trong **một tiến trình**, không cần Node/Chromium, không cần build;
- render 80 giây video 1080p mất ~1–2 phút thay vì 5–10 phút với headless browser;
- phụ đề `.ass` do libass xử lý, đúng chuẩn broadcast;
- cùng một lệnh chạy được trên server Linux không có GUI.

Đánh đổi: không có animation đồ hoạ tuỳ biến. Nếu sau này cần intro/outro "xịn", có thể
render riêng đoạn đó bằng Remotion rồi để StoryTube ghép vào như một `art` video của cảnh.

Ngoài ra, bản ffmpeg đi kèm Remotion bị build `--disable-filters`, thiếu `subtitles`,
`drawtext`, `overlay` — nên dự án tải thêm bản full vào `.tools\ffmpeg\`.

---

## 5. Quản lý tập trung

- Một file `data/storytube.db` chứa: `projects`, `entities`, `chapters`, `beats`,
  `scenes`, `videos`, `video_scenes`, `renders`, `jobs`, `ai_runs`, `assets`.
- Một job worker duy nhất: TTS dễ bị rate-limit, ffmpeg ăn CPU — chạy song song chỉ làm
  chậm và hỏng thời gian chờ. Job lưu DB nên tắt app mở lại vẫn thấy lịch sử.
- Mỗi video có danh sách cảnh riêng (`video_scenes`) → một truyện dài có thể cắt thành
  nhiều video ngắn, mỗi video một bộ cảnh, dùng chung kinh thánh.
- File media nằm cạnh DB theo `projects/<slug>/{assets,audio,renders}` — copy nguyên
  thư mục `data/` là mang cả xưởng đi.

---

## 6. Giới hạn hiện tại & hướng nâng cấp

| Giới hạn | Hướng xử lý |
|---|---|
| Mốc từng từ là ước lượng trong câu | Thêm bước forced alignment (WhisperX) tuỳ chọn |
| Chưa sinh ảnh từ `visual_prompt` | Cắm ComfyUI/Flux/SD API hoặc dịch vụ ảnh; đã có sẵn trường prompt mỗi cảnh |
| Chưa tự đăng TikTok | API TikTok hạn chế; hiện xuất file + tiêu đề/mô tả/hashtag để đăng tay |
| Chấm điểm hook bằng AI | `critique_video()` đã có, nên đưa lên UI thành nút "chấm độ giữ chân" |
| Chưa có A/B thumbnail | Sinh 3 cover từ 3 mốc thời gian khác nhau, chọn theo CTR |
| Edge TTS chập chờn | Đã có retry; thêm provider fallback tự động khi fail N lần |
| Chưa có phụ đề nhiều ngôn ngữ | Dịch `scenes.narration` rồi TTS bằng giọng ngôn ngữ đó |

---

## 7. Nguồn tham khảo

- xnovelist — <https://github.com/giapnguyen74/xnovelist> (đặc biệt `docs/AI.md`, `docs/AI_LEVELS.md`)
- edge-tts — <https://github.com/rany2/edge-tts>
- Azure Speech (giọng vi-VN) — <https://learn.microsoft.com/azure/ai-services/speech-service/language-support>
- FPT.AI TTS & bảng giá — <https://docs.fpt.ai/docs/vi/speech/documentation/tts-pricing/>
- VietTTS — <https://github.com/dangvansam/viet-tts>, <https://huggingface.co/dangvansam/viet-tts>
- WhisperX (forced alignment) — <https://github.com/m-bain/whisperX>
- ffmpeg filters dùng trong dự án: `gradients`, `zoompan`, `vignette`, `subtitles` (libass),
  `sidechaincompress`, `loudnorm`, `acompressor`, `equalizer`
