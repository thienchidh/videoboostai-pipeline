# Prose Script Format - Video Pipeline Refactor

## Status
- Date: 2026-04-19
- Type: Refactor
- Root cause: Video views declining due to scene-based script format vs prose storytelling

## Problem

Video đầu dùng script prose/storytelling format → 500 views
Video gần dùng script scene-based format → <100 views

Script format khác biệt:
- Prose: personal, conversational, emoji, CTA trực tiếp
- Scene-based: narrator, declarative, AI-generated feel, structured

## Solution

Refactor content pipeline + video pipeline để output và xử lý prose format thay vì scene-based.

## Architecture

```
ContentPipeline (Stage 1)
├── generate_prose_script() → single prose script + video_message
└── saves: {title, script, video_message, hashtags} → YAML

VideoPipeline (Stage 2)
├── receives prose script + video_message
├── prose-to-segments converter (split by paragraphs/emoji markers)
├── TTS + Image (parallel per segment)
├── Lipsync + Concatenate + Watermark + Subtitles + BGM
└── outputs: final video
```

## File Changes

### 1. `modules/pipeline/models.py`

`ScriptOutput` - thay `scenes: List[SceneConfig]` bằng `script: str`:

```python
class ScriptOutput(BaseModel):
    title: str
    script: str  # single prose script, replaces scenes[]
    video_message: str
    keywords: List[str] = []
    content_angle: str = "tips"
    style: str = ""
    watermark: str = ""
    generated_at: str = ""
    # Removed: scenes: List[SceneConfig]
```

### 2. `content_idea_generator.py`

- `_build_prose_prompt()` → outputs single prose script (storytelling format)
- `_parse_prose()` → returns `script: str` (not scene array)
- `generate_script_from_idea()` → returns `ScriptOutput` với `script` field

Prose prompt structure:
- Hook: provocative question/story opener
- Body: 2-3 tips/techniques với concrete numbers
- CTA: direct call-to-action
- Emoji: 📌🔔💪 cho visual markers
- Personal tone: "Mình từng", "bạn cũng nên"

### 3. `content_pipeline.py`

`_save_script_config()`:
- Output YAML với `script:` field thay vì `scenes:`
- `video_message` field giữ nguyên
- Thêm `hashtags` array

### 4. `modules/pipeline/scene_processor.py`

Refactor input:
- Nhận prose script thay vì scenes array
- `ProseSegmenter` class: split prose into logical segments
- Per-segment: TTS + Image + Lipsync
- Concatenate all segments

### 5. `modules/pipeline/pipeline_runner.py`

- `PipelineRunner` thêm prose-aware logic
- `run()` method: detect prose format, call segmenter

### 6. `core/video_utils.py`

- `generate_subtitles_from_prose()` — subtitle generation từ prose script
- `extract_hashtags()` — extract hashtags from prose for caption

## Prose-to-Segments Logic

Segment splitting dựa trên:
1. Paragraph breaks (`\n\n`)
2. Emoji markers (📌 = new tip, 🔔 = CTA, 💪 = closing)
3. Keyword patterns (Phương pháp 1/2/3, Tip 1/2/3)

Example:
```
Input:
"Đã bao giờ bạn cảm thấy một ngày có quá ít giờ...?\n\n📌 Phương pháp 1: Time Blocking..."

Segments:
1. Hook: "Đã bao giờ bạn cảm thấy...?"
2. Tip 1: "📌 Phương pháp 1: Time Blocking..."
3. Tip 2: "📌 Phương pháp 2: Quy tắc 2 phút..."
4. CTA: "Mình đã thử và thấy nó thay đổi hoàn toàn..."
```

## Breaking Changes

- All existing scene-based YAML files in `configs/channels/*/scenarios/` need regeneration
- No backward compatibility — regenerate all scripts

## Testing Plan

1. Run content pipeline để generate prose scripts
2. Run video pipeline để produce videos
3. Monitor view metrics sau 1 tuần
4. Compare với scene-based baseline