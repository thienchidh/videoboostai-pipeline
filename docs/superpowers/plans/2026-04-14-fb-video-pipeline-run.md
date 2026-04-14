# FB Video Pipeline Run — Operational Plan

> **For agentic workers:** This is an operational runbook, not an implementation plan. Execute steps in order. No TDD needed — this runs the existing pipeline.

**Goal:** Chạy thử pipeline để tạo 1 video Facebook (9:16, có karaoke caption) — skip lipsync để tiết kiệm credits.

**Kiến trúc:** Pipeline 2 giai đoạn: (1) Content tạo script từ topic → (2) Video tạo MP4 từ script với TTS + Image + static video + watermark + karaoke subtitles + BGM.

**Output:** `output/nang_suat_thong_minh/{slug}_{ts}/final/video_v3_{ts}_with_music.mp4`

---

## Pre-Run Checks

### 1. Verify channel config exists

**File:** `configs/channels/nang_suat_thong_minh/config.yaml`

- [ ] Check `text` (watermark text): `"@NangSuatThongMinh"`
- [ ] Check `enable: true` for watermark
- [ ] Check `subtitle.font_size: 60`
- [ ] Check `dimensions.width: 1080`, `height: 1920`
- [ ] Check `characters` defined (Vietnamese voice + description)

### 2. Verify technical config

**File:** `configs/technical/config_technical.yaml`

- [ ] `api_keys.minimax` not empty
- [ ] `api_keys.wavespeed` not empty (for image fallback chain)
- [ ] `api_keys.kie` not empty (for Kie Z Image fallback)
- [ ] `llm.minimax.model` set (e.g., `MiniMax-Text-01`)
- [ ] `tts.edge.voice` not empty
- [ ] `image.aspect_ratio: "9:16"`

### 3. Verify music directory

**Path:** `music/` (repo root hoặc path trong config)

- [ ] Có ít nhất 1 file .mp3 hoặc .ogg > 500KB
- [ ] File không bị corrupt: `ffprobe -v error music/your_file.mp3`

### 4. Verify fonts

**File:** `fonts/LiberationSans-Bold.ttf`

- [ ] File tồn tại

### 5. Verify FFmpeg available

```bash
ffmpeg -version
```
Expected: FFmpeg version x.x.x

---

## Run Pipeline

### Step 1: Run content + video pipeline

```bash
python scripts/run_pipeline.py --channel nang_suat_thong_minh --ideas 1 --produce --skip-lipsync
```

**What happens:**
1. Content pipeline: research topic → generate idea → dedup → generate script YAML
2. Video pipeline: TTS (Edge) + Image (MiniMax → Kie Z fallback) → static video → crop 9:16 → concat → watermark (bounce) → karaoke subtitles → BGM

**Expected duration:** 5-15 phút cho 1 idea

**Logs to watch:**
- `[ContentPipeline]` — topic research + idea generation
- `[SingleCharSceneProcessor]` — per scene: TTS → Image → Static → Crop
- `[VideoPipelineRunner]` — concatenation, watermark, subtitles, BGM

**If error at TTS:** Check `modules/media/tts.py` Edge TTS — may need proxy/network
**If error at Image:** Check `modules/media/image_gen.py` Kie Z fallback chain
**If SceneDurationError:** TTS duration ngoài 5-15s — cần regenerate script

---

## Post-Run: Locate Output

### Step 2: Find timestamped output directory

```bash
ls -dt output/nang_suat_thong_minh/*/ | head -5
```

Or look for newest:
```bash
ls -d output/nang_suat_thong_minh/*/final/
```

### Step 3: Verify final video

**Path:** `output/nang_suat_thong_minh/{slug}_{timestamp}/final/video_v3_{timestamp}_with_music.mp4`

```bash
ffprobe -v error -show_entries format=duration,size,bit_rate -show_entries stream=codec_name,width,height,pix_fmt output/nang_suat_thong_minh/.../final/video_v3_*.mp4
```

**Expected:**
- `codec_name: h264`
- `width: 1080`
- `height: 1920`
- `pix_fmt: yuv420p`
- `duration: ~15-60s` (tùy scene count × 5-15s)

### Step 4: Verify karaoke subtitles burned-in

```bash
ffprobe -v error -select_streams s:0 -show_entries stream=codec_name output/nang_suat_thong_minh/.../final/video_v3_*.mp4
```

If no subtitles stream: subtitles were not added. Check `add_karaoke_subtitles` call in `pipeline_runner.py`.

### Step 5: Verify watermark

Play video manually (or extract frame):
```bash
ffmpeg -ss 00:05 -i output/nang_suat_thong_minh/.../final/video_v3_*.mp4 -frames:v 1 -f image2 frame.jpg
```
Check `frame.jpg` for `@NangSuatThongMinh` watermark.

---

## Extract Caption Text (for FB post)

The karaoke subtitles are **burned-in** video — not a separate SRT file. To get caption text:

### Step 6: Extract subtitle text from YAML script

**Path:** `configs/channels/nang_suat_thong_minh/scenarios/{slug}.yaml`

```bash
cat configs/channels/nang_suat_thong_minh/scenarios/{slug}.yaml | grep -E "^  script:" -A 50
```

Or find the script used:
```bash
ls -dt output/nang_suat_thong_minh/*/ | head -1 | xargs -I{} cat {}/../scenarios/.yaml 2>/dev/null
```

The caption text = full TTS script concatenated. Use this as your FB post caption.

---

## FB Upload Checklist

- [ ] Video: `video_v3_{ts}_with_music.mp4` — MP4 H.264, 1080x1920, 9:16 vertical
- [ ] Caption: Lấy từ scenario YAML script (xem Step 6)
- [ ] hashtags: #NangSuatThongMinh #Vietnamese #Motivation (hoặc custom)
- [ ] Thumbnail: Tự động chọn frame đẹp — có thể extract frame bằng `ffmpeg -ss 00:03 ...`

---

## Rollback / Retry

If pipeline fails midway:

**Content only (no video):**
```bash
python scripts/run_pipeline.py --channel nang_suat_thong_minh --ideas 1
```
(Skip `--produce` — chỉ tạo script YAML, không produce video)

**Fresh video from existing script:**
```bash
# Xóa output directory cũ
rm -rf output/nang_suat_thong_minh/{slug}_{old_ts}/

# Chạy lại video pipeline trực tiếp
python scripts/video_pipeline_v3.py nang_suat_thong_minh
```

**Nếu lipsync quota hết** — Pipeline sẽ tự động fallback sang static video (same as `--skip-lipsync`).
