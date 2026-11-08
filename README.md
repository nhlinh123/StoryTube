# StoryTube

Một công cụ duy nhất để **viết truyện → lồng tiếng tiếng Việt → dựng video dọc/ngang** cho TikTok, Reels, Shorts, Facebook, YouTube — và quản lý tất cả truyện, cảnh, video ở cùng một chỗ.

```
Ý tưởng ─► Kinh thánh truyện ─► Dàn ý ─► Beat ─► Văn xuôi ─► Kịch bản cảnh ─► Giọng đọc ─► Video 9:16 / 4:5 / 1:1 / 3:4 / 16:9
   AI          AI                AI       AI        AI           AI              TTS           ffmpeg
```

Chạy tại `C:\Works\MMO\storytube`. Dữ liệu nằm trong `data\` (SQLite + file media), không gửi đi đâu ngoài lời gọi API do bạn chủ động bấm.

---

## 0. Cài từ repo (máy mới)

```powershell
git clone <repo-url> storytube
cd storytube

# 1) ffmpeg bản full (có libass/subtitles). Windows: tải build từ gyan.dev hoặc BtbN,
#    giải nén và trỏ biến môi trường:
$env:STORYTUBE_FFMPEG = "C:\đường\dẫn\ffmpeg.exe"

# 2) thư viện TTS (chỉ cần edge-tts; các provider khác dùng HTTP thuần)
python -m pip install --target vendor edge-tts
#    hoặc: python -m pip install -r requirements.txt

# 3) chạy
python -m storytube demo          # tạo truyện mẫu + chép 3 video nền mẫu
python -m storytube doctor        # kiểm tra ffmpeg / giọng / key
python -m storytube serve --open  # http://127.0.0.1:8790
```

`data\` **tự sinh** ở lần chạy đầu (config.json rỗng key + SQLite). Repo không chứa dữ liệu
chạy thật, không chứa key. Xem mẫu cấu hình đầy đủ ở `config.example.json`.

> `.gitignore` loại `data/`, `vendor/`, `wheels/`, `.tmp/`, `*.log`, `.env`.
> Muốn kiểm tra trước khi push: `python tools/check_secrets.py`.

---

## 1. Chạy nhanh

```powershell
cd C:\Works\MMO\storytube

# kiểm tra môi trường (ffmpeg, giọng đọc, API key)
python -m storytube doctor

# tạo truyện mẫu đã có sẵn 8 cảnh (không cần AI)
python -m storytube demo

# mở giao diện web
python -m storytube serve --open
```

Hoặc chạy file `start.cmd` ở thư mục gốc.

CLI đầy đủ:

```powershell
python -m storytube voice  vid_xxx                          # lồng tiếng toàn bộ cảnh
python -m storytube render vid_xxx --ratios 9:16,1:1,16:9    # dựng nhiều tỉ lệ
python -m storytube script prj_xxx --scenes 10               # AI chia cảnh từ văn xuôi
python -m storytube pipeline prj_xxx --chapters 3 --ratios 9:16
python -m storytube export prj_xxx --out truyen.md
```

---

## 2. Giao diện

Bốn tab, tất cả dữ liệu lưu ngay vào SQLite:

| Tab | Việc bạn làm |
|---|---|
| **Truyện** | Xem kinh thánh (nhân vật/bối cảnh/luật), dàn ý chương, beat; bấm “AI viết” cho từng beat; mỗi chương có nút **Video** để tạo bản dựng riêng |
| **Kịch bản** | Chọn phạm vi (toàn truyện / một chương) → AI chia cảnh; sửa lời đọc, chữ to, mô tả ảnh; chọn giọng cho bản dựng |
| **Video** | Chọn bản dựng, xem cảnh thuộc bản dựng đó, thiết lập giọng/phụ đề/watermark/tỉ lệ, bấm “Lồng tiếng + Dựng” |
| **AI log** | Nhật ký từng lần gọi model: công cụ, cấp, model, token, thời gian |

### 2.1 Ba tab nối với nhau thế nào

```
Truyện:  chương ──[nút Video]──►  tạo bản dựng riêng + gọi AI chia cảnh từ đúng chương đó
                                   (scenes.chapter_id = chương, video_scenes = thứ tự cảnh)

Kịch bản:  chọn phạm vi ──► toàn truyện  = một bản dựng tóm tắt cả sách
                          └ một chương   = một bản dựng mới cho chương đó
           đổi giọng ở đây  ──► ghi thẳng vào spec của bản dựng (tab Video thấy ngay)

Video:  chọn bản dựng ──► thấy đúng số cảnh / giây / cảnh nào có tiếng, có ảnh
        Lồng tiếng + Dựng ──► lồng tiếng các cảnh còn thiếu rồi render từng tỉ lệ
```

- Truyện dài nên đi theo **chương**: 6 chương → 6 video ngắn, mỗi video 3–8 cảnh, thay vì
  nhồi cả 5.000 chữ vào một video 60 giây.
- Mỗi chương hiện badge `N cảnh` / `chưa có cảnh`, nên biết ngay chương nào đã chuyển thể.
- Bản dựng có thể có nhiều (mỗi chương một cái, hoặc nhiều phiên bản tỉ lệ khác nhau) —
  chọn ở dropdown đầu tab Video.
- Thêm cảnh tay (“+ Cảnh”) sẽ gắn luôn vào bản dựng đang chọn, không tạo cảnh mồ côi.

### 2.2 Nút “Phân tích truyện → số cảnh”
Không đoán bằng cảm tính và **không tốn token**: tool đếm âm tiết thật của từng chương
(cộng các beat đã viết), chia cho tốc độ đọc của giọng đang chọn (mặc định 4,15 âm tiết/giây,
có tính `rate` của profile), rồi tính:

- `số cảnh = thời lượng mục tiêu × tốc độ / 30 âm tiết mỗi cảnh`, chặn trong [3, 24] và
  không cho cảnh nào ngắn dưới 2,6 giây;
- `số tập = ceil(thời lượng đọc / thời lượng mục tiêu)` — tức muốn giữ nguyên chi tiết thì
  cần bao nhiêu video.

Kết quả hiện bảng từng chương (chữ, thời lượng đọc, số tập, cảnh/tập) và hai phương án:
**cô đọng** (mỗi chương một video) hoặc **giữ chi tiết** (chia nhỏ). Bấm “Dùng N cảnh” để
điền vào ô số cảnh.

Ví dụ với truyện 4.791 chữ (4.749 âm tiết ≈ 19:52 lời đọc), video 90 giây:
`6 tập cô đọng × 12 cảnh` hoặc `16 tập giữ chi tiết × 12 cảnh`.

CLI:

```powershell
python -m storytube analyze prj_xxx --target 90
python -m storytube analyze prj_xxx --chapter 3 --target 60
```

### 2.3 Giữ nguyên văn hay rút gọn

Tab **Kịch bản** có hai lựa chọn khi tạo cảnh:

| Chế độ | Cách làm | Token |
|---|---|---|
| **Giữ nguyên văn** (mặc định) | cắt cảnh bằng code theo câu, đúng chữ bạn viết | **0** |
| **Rút gọn bằng AI** | AI viết lại kịch bản ngắn hơn, số cảnh theo mục tiêu | tốn token |

Kèm lựa chọn **Chia cảnh / 1 cảnh duy nhất**:
- *Chia cảnh* + giữ nguyên văn → mỗi cảnh ~32 âm tiết (chỉnh được), không mất chữ nào;
- *1 cảnh duy nhất* + giữ nguyên văn → cả truyện thành một cảnh, phụ đề vẫn chia trang theo lời đọc.

Vì vậy không cần bấm “AI viết” cho từng beat nữa: viết (hoặc dán) truyện đầy đủ, rồi để tool
đọc đúng văn bản đó.

### 2.4 Nền video, lớp phủ, vị trí phụ đề

Bỏ video nền vào `data\assets\videos\` (mp4/mov/mkv/webm). Tool tự liệt kê trong ô chọn.

| Tuỳ chọn | Ý nghĩa |
|---|---|
| **Video nền · Ngẫu nhiên** | mỗi cảnh lấy một video khác nhau, xoay vòng theo thứ tự cảnh |
| **Video nền · Cố định** | tất cả cảnh dùng chung một video |
| **Ảnh AI** | tạo ảnh từ `visual_prompt` (ElevenLabs → Pollinations) |
| **Gradient** | nền chuyển động tự sinh, không cần file |

Video nền được **lặp/cắt đúng độ dài cảnh và tắt tiếng gốc** (`-an`), chỉ còn lời đọc của bạn.
**Lớp phủ** (0–90%) + **màu phủ** giúp chữ nổi trên footage sáng. **Vị trí phụ đề**:
TikTok/Reels (trên thanh UI), YouTube (lower-third), giữa khung, phía trên.

### 2.5 Một nút ra cả serie — “⚡ Tự động ra video”

Nút nằm ở tab **Truyện**, cạnh “Lập dàn ý”. Chọn:

- **Nguồn**: tất cả chương / một chương / **dán truyện đầy đủ** (dùng ngay, không cần tạo chương);
- **Xử lý**: giữ nguyên văn (0 token) hoặc rút gọn bằng AI;
- **Chia cảnh** hay 1 cảnh; số âm tiết mỗi cảnh;
- **Nền**: video (random/cố định) / ảnh AI / gradient; độ phủ + màu; vị trí sub;
- **Tỉ lệ**, chất lượng, giọng đọc.

Tool chạy tuần tự: chia cảnh → lồng tiếng → (tạo ảnh nếu chọn) → dựng từng tỉ lệ, mỗi chương
một video, có thanh tiến trình `[2/6]`.

CLI tương đương:

```powershell
python -m storytube autopilot prj_xxx --chapter 1 --bg video --opacity 0.45 --position tiktok
python -m storytube autopilot prj_xxx --text-file truyen.txt --mode verbatim --ratios 9:16,1:1
```

Thanh trạng thái dưới cùng hiện tiến trình job (lồng tiếng / dựng từng tỉ lệ) — chạy nền, không chặn giao diện.

---

## 3. Cấu hình AI (DeepSeek mặc định)

### 3.1 Nạp key nhanh

```powershell
python -m storytube keys --deepseek sk-... --elevenlabs sk_... --test
```

Hoặc mở **Cài đặt** trong web. Key lưu tại `data\config.json` (không gửi đi đâu khác ngoài chính nhà cung cấp).

### 3.2 DeepSeek — đúng đường mà DSH dùng

DSH gọi DeepSeek qua **wire Anthropic**: `https://api.deepseek.com/anthropic/v1/messages` (không phải `chat/completions`). StoryTube dùng đúng endpoint đó (`api_style: "anthropic"`), nên hành vi giống hệt harness: tách `system`, `x-api-key`, `anthropic-version: 2023-06-01`.

> **Quan trọng:** token trong `~/.dsh/.credentials.yaml` là **token phiên đăng nhập**, không phải API key. Đã thử cả `x-api-key` lẫn `Authorization: Bearer` trên `/anthropic` và `/v1` — DeepSeek trả `401 … api key invalid`. Muốn dùng DeepSeek phải lấy key `sk-...` tại <https://platform.deepseek.com/api_keys> rồi dán vào Cài đặt (hoặc `python -m storytube keys --deepseek sk-...`). Tool sẽ tự dùng `DEEPSEEK_API_KEY` nếu bạn đặt biến môi trường.

Các provider khác vẫn dùng được: OpenAI, OpenRouter, Ollama, LM Studio, hoặc bất kỳ endpoint OpenAI-compatible nào (chọn ở dropdown, sửa `base_url` + `model`).

**Cấp AI (0–5)** giới hạn việc AI được làm: cấp 5 mới cho chạy cả pipeline; cấp 3 đủ để viết văn xuôi; cấp 2 chỉ sửa câu; cấp 1 chỉ đọc/nhận xét.

### 3.3 Ảnh nền

| Provider | Điều kiện | Ghi chú |
|---|---|---|
| **ElevenLabs Image** (`/v1/flows/image`) | Cần gói **Pro** | Model `gemini-3.1-flash-image`, `bytedance-seedream-5-lite`, `gpt-image-2`… trả về ảnh 2K đúng tỉ lệ |
| **Pollinations** (flux) | Miễn phí, không key | Tự động dùng khi ElevenLabs trả `402 paid_plan_required`; logo ở đáy được cắt bỏ |

Thứ tự này nằm trong `images.provider_order`. Ảnh lưu ở `data\projects\<slug>\assets\img\`, gắn vào `scenes.art`, renderer tự chạy Ken Burns.

---

## 4. Giọng đọc tiếng Việt

Mặc định ưu tiên **ElevenLabs**, tự rơi về Edge khi chưa có key:

| Profile | Provider | Giọng | Hậu xử lý |
|---|---|---|---|
| `nam-tram-eleven` *(mặc định)* | elevenlabs | Sang Trương `7WNWm0yUcEolHsfg5Bhk` → dự phòng Daniel / Adam | `warm` |
| `nam-tram-eleven-2` | elevenlabs | Trần Thanh `kPNz4WRTiKDplS7jAwHu` → dự phòng Adam | `warm-deep` |
| `nam-tram-am` | edge | `vi-VN-NamMinhNeural`, rate −6%, pitch −14Hz | `warm-deep` |
| `nam-truyen-cam` | edge | Nam Minh, rate −2%, pitch −8Hz | `warm` |
| `nu-nhe-nhang` | edge | `vi-VN-HoaiMyNeural` | `warm` |
| `fpt-minhquan` | fpt | `minhquan` (cần API key) | `warm-deep` |
| `azure-namminh` | azure | Nam Minh qua Azure | `warm-deep` |
| `viet-google` | google | Google Translate TTS | `warm` |

**Về gói ElevenLabs Free:** API chặn voice thư viện (`402 paid_plan_required` — "Free users cannot use library voices via the API"). Tool đã xử lý: thử lần lượt danh sách `voice` → `fallback_voices` trong profile, nên gói Free vẫn ra tiếng bằng voice dựng sẵn (Daniel — nam trầm, giọng Anh, tiếng Việt hơi pha accent). Khi bạn nâng gói, voice Sang Trương tự được dùng lại, không cần sửa gì.

**Vì sao nghe “trầm ấm”?** Ba lớp: (1) chọn giọng nam + `pitch` âm của engine, (2) `asetrate`/`atempo` hạ cao độ ~1 cung mà không đổi tốc độ, (3) EQ nâng 110 Hz, cắt 380 Hz (bớt ù) và 3 kHz (bớt chói), nén nhẹ, chuẩn hoá −14 LUFS. Toàn bộ nằm trong `storytube/media.py → VOICE_POST`.

**Edge TTS hay bị chặn tạm thời.** Tool tự thử lại (mặc định 8 lần, backoff). Nếu cần ổn định mà không muốn trả tiền: dùng **Azure** (cùng giọng Nam Minh) hoặc **FPT.AI**.

### Kết quả mẫu (truyện “Người giữ đèn biển”, 8 cảnh)

Giọng: ElevenLabs `nam-tram-eleven` (gói Free nên rơi về Daniel — nam trầm).
Ảnh: 8 ảnh điện ảnh sinh từ `visual_prompt` (ElevenLabs cần Pro → Pollinations flux).

| Tỉ lệ | File |
|---|---|
| 9:16 · 1080×1920 | `data\projects\nguoi-giu-den-bien\renders\vid_16ce4a26c497\9x16\` |
| 4:5 · 1080×1350 | `...\4x5\` |
| 1:1 · 1080×1080 | `...\1x1\` |
| 16:9 · 1920×1080 | `...\16x9\` |

Mỗi thư mục có `cover.jpg` (ảnh bìa) và `logs\` (log ffmpeg từng cảnh) để debug.

Đổi giọng trong tab **Video** hoặc sửa `tts.default_profile`.

**Vì sao nghe “trầm ấm”?** Ba lớp: (1) chọn giọng nam + `pitch` âm của engine, (2) `asetrate`/`atempo` hạ cao độ ~1 cung mà không đổi tốc độ, (3) EQ nâng 110 Hz, cắt 380 Hz (bớt ù) và 3 kHz (bớt chói), nén nhẹ, chuẩn hoá −14 LUFS. Toàn bộ nằm trong `storytube/media.py → VOICE_POST`.

**Edge TTS hay bị chặn tạm thời.** Tool tự thử lại (mặc định 8 lần, backoff). Nếu máy bạn bị chặn nhiều, dùng **Azure** (cùng giọng Nam Minh, key miễn phí 500k ký tự/tháng) hoặc **FPT.AI** (giọng Việt bản địa, 100k ký tự/tháng miễn phí).

---

## 5. Video & tỉ lệ

| Tỉ lệ | Kích thước | Dùng cho | Vùng an toàn phụ đề (dưới/trái-phải) |
|---|---|---|---|
| `9:16` | 1080×1920 | TikTok, Reels, Shorts | 420 px dưới, 96 px hai bên |
| `4:5` | 1080×1350 | Instagram/Facebook feed | 190 / 64 |
| `1:1` | 1080×1080 | Vuông, carousel | 150 / 64 |
| `3:4` | 1080×1440 | Pinterest, tablet | 220 / 72 |
| `16:9` | 1920×1080 | YouTube, Facebook ngang | 110 / 90 |

Cùng một kịch bản, cùng một file phụ đề — chữ và hook tự canh lại theo từng khung.

Kiểu phụ đề: `karaoke` (từ đang đọc đổi màu), `block` (cả câu), `beast` (to, dằn, có pop), `minimal`.

Hình nền: bỏ ảnh/video vào `data\projects\<slug>\assets\` rồi điền đường dẫn tương đối (`assets/anh.jpg`) vào cột ảnh nền của cảnh. Không có ảnh thì renderer tự tạo nền gradient chuyển động theo `mood` + hạt phim + vignette. Ảnh tĩnh có hiệu ứng Ken Burns.

---

## 6. Cấu trúc dữ liệu

```
data\
  storytube.db          # projects, entities, chapters, beats, scenes, videos, renders, jobs, ai_runs
  config.json           # API key, profile giọng, preset render
  assets\videos\        # video nền dùng chung (random hoặc chọn 1 file)
  projects\<slug>\
    assets\             # ảnh, video, nhạc nền của bạn
    assets\img\         # ảnh AI sinh ra
    audio\<scene_id>\   # scene.wav + từng câu + mốc thời gian từng từ
    renders\<video_id>\<ratio>\   # mp4, cover.jpg, work\, logs\
  logs\                 # log ffmpeg
```

Xoá một truyện là xoá cascade toàn bộ chương, cảnh, render tương ứng trong DB; file media bạn có thể xoá tay trong `data\projects\`.

---

## 7. Kiến trúc mã nguồn

| File | Trách nhiệm |
|---|---|
| `config.py` | mặc định + `config.json` + env, tìm ffmpeg |
| `db.py` | schema SQLite, helper |
| `textutil.py` | chuẩn hoá tiếng Việt cho TTS (đọc số, viết tắt), đếm âm tiết, canh thời gian từ |
| `llm.py` | client OpenAI-compatible, JSON repair, thống kê token |
| `prompts.py` | toàn bộ prompt tiếng Việt (ý tưởng, kinh thánh, dàn ý, beat, văn xuôi, kịch bản) |
| `story.py` | pipeline + kiểm tra cấp AI + ghi DB |
| `tts.py` | 6 provider, retry, ghép câu, mốc thời gian từng từ |
| `media.py` | ffmpeg: wav, pad, concat, trộn nhạc, loudnorm, hậu xử lý giọng |
| `render.py` | dựng cảnh, ghép, burn phụ đề, xuất nhiều tỉ lệ |
| `render_captions.py` | sinh file `.ass` (karaoke, hook, watermark) |
| `jobs.py` | hàng đợi job nền, một worker |
| `api.py` | HTTP API + phục vụ web |
| `cli.py` | dòng lệnh |
| `seed.py` | truyện mẫu “Người giữ đèn biển” |

Không có framework web, không build step: `http.server` + HTML/CSS/JS thuần, `urllib` cho HTTP, `sqlite3` cho dữ liệu. Chỉ phụ thuộc duy nhất là `edge-tts` (đã giải nén sẵn trong `vendor\`).

---

## 8. Sự cố thường gặp

| Hiện tượng | Xử lý |
|---|---|
| Bấm “AI viết” báo `API không tồn tại` | Server đang chạy code cũ: đóng cửa sổ tool, chạy lại `start.cmd`, rồi F5 trình duyệt |
| Lưu key này thì mất key kia | Đã sửa: cấu hình được gộp sâu, field `api_key` rỗng/`***` không bao giờ ghi đè key đã lưu |
| `DeepSeek từ chối token đăng nhập của DSH (401)` | Token trong `~/.dsh` là token phiên, không phải API key. Lấy `sk-...` ở platform.deepseek.com rồi `python -m storytube keys --deepseek sk-...` |
| `ElevenLabs 402 · Free users cannot use library voices` | Gói Free không dùng voice thư viện; tool tự chuyển sang `fallback_voices` (Daniel/Adam). Nâng gói để dùng Sang Trương |
| `ElevenLabs 402 · requires a Pro plan` khi tạo ảnh | Ảnh ElevenLabs chỉ từ gói Pro; tool tự dùng Pollinations miễn phí |
| `Chưa có ffmpeg` | Đặt `STORYTUBE_FFMPEG=C:\đường\dẫn\ffmpeg.exe`, hoặc cài vào `.tools\ffmpeg\bin\` |
| Edge TTS báo “No audio received” | Nút thử lại tự chạy; nếu liên tục, đổi sang `azure-namminh` hoặc `fpt-minhquan` |
| Phụ đề hiện ô vuông | Font thiếu glyph tiếng Việt — dùng `Arial`, `Segoe UI`, `Montserrat` |
| Video dài, máy ì | Chọn chất lượng `draft` (720p) khi thử bố cục, chỉ render `high` bản cuối |
| `Cấp 3 chưa cho phép 'chuyển thể kịch bản'` | Nâng cấp AI của truyện lên 4 trong dropdown góc phải |

---

## 9. Kiểm thử

```powershell
python -m unittest discover -s tests -t .   # 17 test: chuẩn hoá tiếng Việt, timing, LLM (server giả)
node tools\ui_smoke.js                      # 14 kiểm tra render giao diện bằng DOM giả
python -m storytube doctor                  # ffmpeg, giọng Edge, trạng thái key
```

Nếu đã có bản thảo ở nơi khác (kể cả xuất từ xnovelist), có thể dán thẳng vào ô
“Dán văn bản nguồn” trong tab Kịch bản, hoặc:

```powershell
python -m storytube script prj_xxx --file truyen.md --scenes 10
```

---

## 10. Giấy phép & lưu ý

Truyện mẫu và toàn bộ mã trong thư mục này viết cho dự án cá nhân. Giọng đọc lấy từ dịch vụ của Microsoft/FPT/ElevenLabs — đọc kỹ điều khoản thương mại trước khi dùng cho kênh kiếm tiền. Nhạc nền và ảnh do bạn tự cung cấp.
