# VideoBoostAI Pipeline

Một pipeline tự động tạo video ngắn (TikTok/Reels) từ kịch bản đến video hoàn chỉnh.

## Mục lục
- [Quick Start](#quick-start)
- [Cài đặt](#cài-đặt)
- [Cấu trúc Project](#cấu-trúc-project)
- [Config](#cấu-trúc-config)
- [Chạy Pipeline](#chạy-pipeline)
- [Dry Run / Test Local](#dry-run--test-local)
- [Tính năng chính](#tính-năng-chính)
- [Fallback khi hết credits](#fallback-khi-hết-credits)
- [API Providers](#api-providers)
- [Testing](#testing)

---

## Quick Start

```bash
# 1. Clone repo
git clone https://github.com/thienchidh/videoboostai-pipeline.git
cd videoboostai-pipeline

# 2. Tạo virtual environment và cài dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Copy và edit config
cp configs/technical/config_technical.yaml.example configs/technical/config_technical.yaml
# Edit configs/technical/config_technical.yaml thêm API keys

# 4. Tạo channel + scenario
# Xem mẫu: configs/channels/nang_suat_thong_minh/

# 5. Chạy pipeline
./venv/bin/python scripts/video_pipeline_v3.py nang_suat_thong_minh
```

---

## Cài đặt

### Requirements
- Python 3.12+
- ffmpeg (`sudo apt install ffmpeg`)
- Virtual environment (python3 -m venv venv)

### Cài đặt dependencies
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Cài đặt font cho karaoke subtitles
```bash
sudo apt-get install fonts-dejavu fonts-liberation
# Hoặc copy font vào fonts/
```

---

## Cấu trúc Project

```
videoboostai-pipeline/
├── configs/
│   ├── technical/
│   │   └── config_technical.yaml     # API keys, endpoints, model config
│   └── channels/
│       └── {channel_id}/
│           ├── config.yaml            # Channel settings (watermark, style...)
│           └── scenarios/
│               └── YYYY-MM-DD/
│                   └── {scenario}.yaml  # Kịch bản video
├── modules/
│   ├── pipeline/
│   │   ├── config_loader.py          # Load + merge configs
│   │   ├── pipeline_runner.py         # Điều phối pipeline
│   │   ├── scene_processor.py         # Xử lý từng scene
│   │   └── publisher.py             # Upload lên social
│   ├── media/
│   │   ├── tts.py                   # TTS providers (Edge, MiniMax)
│   │   ├── image_gen.py              # Image generation (MiniMax, WaveSpeed)
│   │   ├── lipsync.py                # Lipsync (Kie.ai, WaveSpeed)
│   │   └── s3_uploader.py           # Upload media lên S3
│   ├── content/
│   │   ├── content_calendar.py      # Lên lịch content
│   │   ├── content_idea_generator.py # Generate content ideas
│   │   └── topic_researcher.py      # Research topics
│   ├── social/
│   │   ├── facebook.py              # Facebook Page API
│   │   └── tiktok.py                # TikTok API
│   └── llm/
│       └── minimax.py                # MiniMax LLM provider
├── scripts/
│   ├── video_pipeline_v3.py         # CLI entry point
│   ├── bounce_watermark.py          # Watermark bounce effect
│   └── karaoke_subtitles.py         # Karaoke subtitles
├── core/
│   ├── paths.py                     # Path constants
│   ├── video_utils.py               # Video utilities (ffmpeg wrappers)
│   └── plugins.py                   # Provider registry
├── tests/                           # Pytest tests
└── db.py                            # Database models
```

---

## Cấu trúc Config

### 1. Technical Config (`configs/technical/config_technical.yaml`)

```yaml
# API Keys
api:
  keys:
    wavespeed: "your_wavespeed_key"
    minimax: "your_minimax_key"
    kie_ai: "your_kieai_key"
  urls:
    wavespeed: "https://api.wavespeed.ai"
    minimax_tts: "https://api.minimax.io/v1/t2a_v2"
    minimax_image: "https://api.minimax.io/v1/image_generation"
    kie_ai: "https://api.kie.ai/api/v1"

# Model selection
generation:
  models:
    tts: "edge"      # edge | minimax
    image: "minimax" # minimax | wavespeed
    video: "kieai"   # kieai | wavespeed
  tts:
    max_duration: 15.0    # seconds - kie.ai limit
    min_duration: 5.0

# Storage (S3)
storage:
  s3:
    endpoint: "https://s3.yoursite.com"
    bucket: "videopipeline"
```

### 2. Channel Config (`configs/channels/{channel_id}/config.yaml`)

```yaml
channel:
  id: "nang_suat_thong_minh"
  name: "Năng Suất Thông Minh"

watermark:
  enable: true
  text: "@NangSuatThongMinh"
  font_size: 60
  opacity: 0.15
  motion: "bounce"

style:
  character_prompt: "3D animated Pixar Disney style, high quality 3D render"
  background_hint: "modern workspace, bright colorful setting"
```

### 3. Scenario (`configs/channels/{channel_id}/scenarios/YYYY-MM-DD/{scenario}.yaml`)

```yaml
title: "3 Mẹo Tăng Năng Suất"

characters:
  - name: "GiaoVien"
    prompt: "3D animated Pixar Disney style friendly professional woman"
    tts_voice: "Vietnamese_kindhearted_girl"

scenes:
  - id: 1
    script: "Bạn có biết 80% công việc chỉ cần 20% thời gian không?"
    characters: ["GiaoVien"]
  - id: 2
    script: "Mẹo thứ nhất: Quy tắc 2 phút..."
    characters: ["GiaoVien"]
```

---

## Chạy Pipeline

### Chạy đầy đủ
```bash
./venv/bin/python scripts/video_pipeline_v3.py nang_suat_thong_minh
```

### Chạy với scenario cụ thể
```bash
./venv/bin/python scripts/video_pipeline_v3.py nang_suat_thong_minh/2026-04-13/3-meo-tang-nangsuat
```

### Dry run (không gọi API)
```bash
./venv/bin/python scripts/video_pipeline_v3.py nang_suat_thong_minh --dry-run
```

### Chỉ mock TTS
```bash
./venv/bin/python scripts/video_pipeline_v3.py nang_suat_thong_minh --dry-run-tts
```

### Stop trước lipsync (tiết kiệm credits)
```bash
./venv/bin/python scripts/video_pipeline_v3.py nang_suat_thong_minh --stop-before-lipsync
```

### Upload lên social sau khi tạo xong
```bash
./venv/bin/python scripts/video_pipeline_v3.py nang_suat_thong_minh --upload
```

---

## Dry Run & Test Local

```bash
# Chạy tests
./venv/bin/pytest tests/ -v

# Chạy specific test file
./venv/bin/pytest tests/test_config_loader.py -v

# Test với coverage
./venv/bin/pytest tests/ --cov=. --cov-report=term-missing
```

---

## Tính năng chính

### 1. TTS (Text-to-Speech)
- **Edge TTS** (free, Vietnamese tốt) - default
- **MiniMax TTS** (paid, chất lượng cao)

### 2. Image Generation
- **MiniMax Image** (chất lượng cao, aspect ratio 9:16)
- **WaveSpeed Image** (fallback)

### 3. Lipsync Video
- **Kie.ai Infinitalk** (đang dùng) - lipsync từ ảnh + audio
- **WaveSpeed LTX** (fallback)

### 4. Karaoke Subtitles
- Highlight từng từ theo thời gian phát âm
- Font + size configurable
- Fade in/out effects

### 5. Watermark Bounce
- Text watermark di chuyển trên video
- Bounce physics: velocity, walls collision
- Opacity + font size configurable

### 6. Background Music
- Thêm nhạc nền vào video
- Volume ducking khi có speech

---

## Fallback khi hết credits

Khi đang chạy full flow mà hết credits lipsync (Kie.ai/WaveSpeed), pipeline tự động fallback:

1. **Phát hiện hết credits** → Kie.ai/WaveSpeed API trả về lỗi hết quota
2. **Fallback mode** → Tạo video tĩnh từ ảnh đã gen + audio TTS đã gen
   - Ảnh gốc → resize thành video (loop)
   - Audio TTS → ghép vào
   - Không cần lipsync nữa
3. **Kết quả** → Video vẫn có TTS + subtitles, watermark, background music
4. **Chất lượng** → Thấp hơn lipsync nhưng vẫn xuất bản được

Điều này đảm bảo pipeline không bị dừng giữa chừng vì hết credits.

---

## API Providers

### MiniMax
- Image generation: `https://api.minimax.io/v1/image_generation`
- TTS: `https://api.minimax.io/v1/t2a_v2`

### Kie.ai
- Lipsync: `https://api.kie.ai/api/v1`
- Cần upload ảnh + audio lên S3 trước

### WaveSpeed
- Lipsync + Image: `https://api.wavespeed.ai`
- API key và upload required

### S3 Storage
- Dùng MinIO/S3 để lưu media files
- Ảnh/audio upload lên S3 → dùng URL cho Kie.ai API

---

## Testing

```bash
# Chạy tất cả tests
./venv/bin/pytest tests/ -v

# Tests pass: 89/89 ✅

# Structure tests
./venv/bin/pytest tests/test_config_loader.py -v

# Pipeline runner tests
./venv/bin/pytest tests/test_pipeline_runner.py -v

# Video utils tests
./venv/bin/pytest tests/test_video_utils.py -v
```

---

## Database

Pipeline lưu trữ state vào PostgreSQL:
- Video runs ( timestamps, status, output path)
- Content calendar (scheduled content)
- Credentials (encrypted API keys)

```bash
# Database config (trong config_technical.yaml)
storage:
  database:
    host: "localhost"
    port: 5432
    name: "videopipeline"
```

---

## Pipeline Flow

```
1. Load configs (technical + channel + scenario)
2. Tạo run directories
3. Loop qua từng scene:
   a. Generate TTS (Edge/MiniMax)
   b. Generate image (MiniMax/WaveSpeed)
   c. Upload lên S3 (cho Kie.ai)
   d. Lipsync video (Kie.ai/WaveSpeed)
   e. Nếu hết credits → fallback: ảnh tĩnh + audio
4. Concatenate scenes
5. Add watermark bounce
6. Add karaoke subtitles
7. Add background music
8. Upload lên social (Facebook/TikTok)
9. Update database
```

---

## Troubleshooting

### Lỗi "ModuleNotFoundError: No module named 'yaml'"
```bash
pip install pyyaml
```

### Lỗi "ffmpeg not found"
```bash
sudo apt install ffmpeg
```

### Hết credits Kie.ai
→ Pipeline tự động fallback sang chế độ ảnh tĩnh + audio
→ Hoặc dùng WaveSpeed thay thế

### Tests fail
```bash
# Kiểm tra xem có thiếu fixtures không
ls tests/fixtures/

# Chạy với verbose để xem chi tiết
./venv/bin/pytest tests/ -vv --tb=long
```
