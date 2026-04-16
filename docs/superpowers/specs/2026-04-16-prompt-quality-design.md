# Prompt Quality Pipeline — Full Redesign

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Improve quality of prompts for TTS (script tone), image (visual detail), and lipsync (speaker expressiveness) through structured scene metadata and a dedicated PromptBuilder class.

**Architecture:** `SceneMetadata` model attached to each scene at generation time (LLM-extracted). `PromptBuilder` class composes all 3 prompts from `SceneMetadata` + `ChannelStyleProfile`. Backward-compatible — all new fields are optional.

---

## 1. New Data Models

### `SceneMetadata` — `modules/pipeline/models.py`

Extracted by LLM at scene script generation time. All fields optional (backward-compatible).

```python
class SceneMetadata(BaseModel):
    """Structured metadata extracted from scene at script generation time."""
    mood: Optional[str] = None          # e.g. "confident", "curious", "urgent"
    emotion: Optional[str] = None         # e.g. "friendly", "serious", "enthusiastic"
    dominant_action: Optional[str] = None  # e.g. "gestures while explaining"
    facial_expression: Optional[str] = None  # e.g. "smiling warmly", "focused look"
    upper_body_pose: Optional[str] = None  # e.g. "slight lean forward", "upright posture"
    pace: Optional[str] = None           # e.g. "steady and measured", "fast-paced excitement"
```

### `ChannelStyleProfile` — extends existing `ImageStyleConfig`

Existing `ImageStyleConfig` fields are renamed/mapped into a style profile:

| Field | Type | Default | Example |
|-------|------|---------|---------|
| `lighting_mood` | str | `"warm"` | `"warm"`, `"cool"`, `"dramatic"` |
| `expression` | str | `"friendly"` | `"friendly"`, `"professional"` |
| `composition` | str | `"professional"` | `"professional"`, `"cinematic"` |
| `art_style` | str | `"3D render"` | `"3D render"`, `"photorealistic"` |
| `camera` | str | `"eye-level"` | `"eye-level"`, `"low angle"` |
| `environment` | str | `"modern office"` | `"modern office"`, `"cozy cafe"` |

These replace/augment the existing `ImageStyleConfig` fields. Existing channel configs continue to work — missing fields fall back to defaults.

### `SceneConfig.metadata` field

```python
class SceneConfig(BaseModel):
    """Một scene từ scenario YAML file."""
    id: int = 0
    tts: Optional[str] = None
    script: Optional[str] = None
    characters: List["SceneCharacter | str"] = []
    video_prompt: Optional[str] = None
    background: Optional[str] = None
    metadata: Optional["SceneMetadata"] = None  # NEW
```

---

## 2. PromptBuilder — `modules/media/prompt_builder.py` (NEW)

Single responsibility: compose image, lipsync, and TTS guidance prompts from scene + channel data.

### Class

```python
class PromptBuilder:
    def __init__(self, channel_style: Optional[ImageStyleConfig] = None):
        self.channel_style = channel_style or ImageStyleConfig()

    def build_image_prompt(
        self,
        scene: SceneConfig,
        metadata: Optional[SceneMetadata] = None,
    ) -> str:
        """Compose image generation prompt from scene topic + metadata + channel style."""

    def build_lipsync_prompt(
        self,
        scene: SceneConfig,
        metadata: Optional[SceneMetadata] = None,
    ) -> str:
        """Compose lipsync prompt describing speaker's expression, action, and tone."""

    def build_tts_guidance(
        self,
        scene: SceneConfig,
        metadata: Optional[SceneMetadata] = None,
    ) -> str:
        """Build TTS style guidance hint from metadata (for TTS provider or voice selection)."""
```

### Prompt Templates

**`build_image_prompt`:**
```
"{scene.video_prompt or scene.background or 'A person speaking'},
{mood or 'engaged'} atmosphere,
{facial_expression or 'natural expression'},
{dominant_action or 'slight movement'},
{lighting_mood or channel_style.lighting_mood} lighting,
{camera or channel_style.camera} camera angle,
{art_style or channel_style.art_style} style,
{environment or channel_style.environment},
{composition or channel_style.composition} composition,
{emotion or 'natural'} mood"
```

Example output:
> "Time management tips, confident atmosphere, smiling warmly, gesturing while explaining, warm lighting, eye-level camera angle, 3D render style, modern office, professional composition, natural mood"

**`build_lipsync_prompt`:**
```
"A {emotion or 'natural'} speaker,
{facial_expression or 'natural expression'},
{dominant_action or 'subtle movement'},
{upper_body_pose or 'upright posture'},
{pace or 'steady pace'} speaking,
Vietnamese language naturally,
{scene.video_prompt or scene.background or 'topic'}"
```

Example output:
> "A friendly speaker, smiling warmly, gesturing while explaining, slight lean forward, steady pace speaking, Vietnamese language naturally, Time management tips"

**`build_tts_guidance`:**
```
"Style: {mood or 'natural'}. Tone: {emotion or 'conversational'}. Pace: {pace or 'normal'}."
```

Example output:
> "Style: confident. Tone: friendly. Pace: steady and measured."

### Helper: metadata-aware field resolution

```python
def _resolve(scene_metadata, style_config, scene_field, style_field, default=None):
    """Return scene metadata value if present, else style config, else default."""
    val = getattr(scene_metadata, scene_field, None) if scene_metadata else None
    if val:
        return val
    val = getattr(style_config, style_field, None) if style_config else None
    return val or default
```

---

## 3. Updated Scene Generation — `content_idea_generator.py`

### `_build_scene_prompt` — updated system prompt

The LLM is instructed to extract and output `SceneMetadata` alongside each scene's script. The JSON output format is updated:

**OLD output format (scene array):**
```json
[{"id": 1, "script": "...", "background": "...", "character": "NamMinh"}]
```

**NEW output format:**
```json
[{
  "id": 1,
  "script": "Hãy bắt đầu với kế hoạch hôm nay...",
  "background": "văn phòng hiện đại",
  "character": "NamMinh",
  "mood": "confident",
  "emotion": "friendly",
  "dominant_action": "gestures while explaining",
  "facial_expression": "smiling warmly",
  "upper_body_pose": "slight lean forward",
  "pace": "steady and measured"
}]
```

System prompt additions (to existing prompt in `_build_scene_prompt`):

```
VỚI MỖI SCENE, TRẢ VỀ THÊM METADATA:
- mood: cảm xúc chủ đạo của nhân vật (confident | curious | urgent | calm | enthusiastic)
- emotion: biểu cảm khuôn mặt (friendly | serious | enthusiastic | warm | focused)
- dominant_action: hành động chính của nhân vật (gestures while explaining | hand movements | slight nod | confident stance)
- facial_expression: biểu cảm (smiling warmly | serious | excited | calm | thoughtful)
- upper_body_pose: tư thế (slight lean forward | upright posture | relaxed posture | straight back)
- pace: tốc độ nói (steady and measured | fast-paced excitement | slow and deliberate | conversational)
```

### `_parse_scenes` — updated to parse metadata

Update `_parse_scenes` → `_validate_scenes` to parse metadata fields:

```python
def _validate_scenes(self, scenes: List[Dict]) -> List[Dict]:
    for s in scenes:
        s["metadata"] = {
            "mood": s.get("mood"),
            "emotion": s.get("emotion"),
            "dominant_action": s.get("dominant_action"),
            "facial_expression": s.get("facial_expression"),
            "upper_body_pose": s.get("upper_body_pose"),
            "pace": s.get("pace"),
        }
    return scenes
```

---

## 4. Updated `scene_processor.py`

### Image prompt — replace concatenation with PromptBuilder

**OLD (existing `get_video_prompt`):**
```python
explicit = scene.video_prompt
# Append channel image_style parts...
```

**NEW:**
```python
from modules.media.prompt_builder import PromptBuilder

prompt_builder = PromptBuilder(channel_style=self.ctx.channel.image_style)
img_prompt = prompt_builder.build_image_prompt(scene, metadata=scene.metadata)
```

### Lipsync prompt — use PromptBuilder

**OLD:**
```python
prompt = self.get_video_prompt(scene)  # same as image prompt
```

**NEW:**
```python
lipsync_prompt = prompt_builder.build_lipsync_prompt(scene, metadata=scene.metadata)
```

### TTS guidance — optional enhancement

```python
tts_guidance = prompt_builder.build_tts_guidance(scene, metadata=scene.metadata)
# Optional: pass to TTS provider or use as voice selection hint
```

---

## 5. Channel Config — `ImageStyleConfig` field additions

Existing `ImageStyleConfig` (defaults already defined):

```yaml
image_style:
  lighting: warm          # existing
  camera: eye-level      # existing
  art_style: 3D render    # existing
  environment: modern office  # existing
  composition: professional  # existing (renamed from composition field)
```

No YAML changes required — all new fields have defaults. Channels with existing `image_style` continue to work.

---

## 6. Files Summary

| File | Action |
|------|--------|
| `modules/pipeline/models.py` | Add `SceneMetadata`, add `metadata` to `SceneConfig` |
| `modules/media/prompt_builder.py` | **CREATE NEW** — `PromptBuilder` class |
| `modules/content/content_idea_generator.py` | Update `_build_scene_prompt` to extract metadata; update `_parse_scenes` to parse it |
| `modules/pipeline/scene_processor.py` | Replace `get_video_prompt` with `PromptBuilder`; add lipsync + TTS guidance calls |
| `configs/channels/{channel}/config.yaml` | No changes required (all fields have defaults) |

---

## 7. Backward Compatibility

- `SceneConfig.metadata` is optional — scenes without metadata use `PromptBuilder` with `None` metadata (falls back to defaults)
- `ImageStyleConfig` fields have defaults — existing channel configs work unchanged
- Old scenario YAML files without metadata continue to work — `PromptBuilder` degrades gracefully
- `get_video_prompt()` method kept as alias for backward compatibility in any code that calls it directly

---

## 8. Error Handling

- If LLM doesn't return metadata fields → `_validate_scenes` leaves them `None`, `PromptBuilder` degrades gracefully to defaults
- If `scene.video_prompt` is None and `scene.background` is None → `PromptBuilder` falls back to `"A person speaking"`
- If `channel.image_style` is None → `PromptBuilder` uses `ImageStyleConfig()` defaults

---

## 9. Testing

1. Unit test `PromptBuilder` with all combinations of metadata + style config
2. Integration test: generate a scene and verify all 3 prompts are non-empty and contain expected terms
3. Backward compatibility: existing scenarios without metadata still produce valid prompts
4. All existing tests pass (302+)
