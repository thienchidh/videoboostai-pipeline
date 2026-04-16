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
    hook_style: Optional[str] = None     # e.g. "bold statement", "surprising stat", "rhetorical question"
    viewer_level: Optional[str] = None    # e.g. "beginner", "intermediate", "advanced"
    key_point: Optional[str] = None      # e.g. "prioritize ruthlessly", "time blocking method"
```

**New fields:**
- `hook_style` — how the scene opens. Affects lipsync prompt energy at the start of the scene.
- `viewer_level` — who the viewer is. Affects image tone and TTS pace (beginner = slower, more explanatory).
- `key_point` — the single takeaway. Enables much richer prompts: image can show the concept visually, lipsync prompt can emphasize the main point.

### `ChannelStyleProfile` — extends existing `ImageStyleConfig`

Existing `ImageStyleConfig` fields are renamed/mapped into a style profile. Additionally, `ChannelConfig.style` (the brand tone string, e.g. `"chuyên gia tài chính thân thiện"`) is passed separately to `PromptBuilder` as `brand_tone`.

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
    def __init__(self, channel_style: Optional[ImageStyleConfig] = None, brand_tone: Optional[str] = None):
        self.channel_style = channel_style or ImageStyleConfig()
        self.brand_tone = brand_tone  # e.g. "chuyên gia tài chính thân thiện"

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
        character_name: Optional[str] = None,
        voice_id: Optional[str] = None,
    ) -> str:
        """Compose lipsync prompt describing speaker's expression, action, tone, and character voice."""

    def build_tts_guidance(
        self,
        scene: SceneConfig,
        metadata: Optional[SceneMetadata] = None,
        character_name: Optional[str] = None,
        voice_id: Optional[str] = None,
    ) -> str:
        """Build TTS style guidance hint from metadata + character voice for provider/voice selection."""
```

### Prompt Templates

**`build_image_prompt`:**
```
"{scene.video_prompt or scene.background or 'A person speaking'},
{key_point or scene topic},
mood: {mood or 'engaged'},
viewer level: {viewer_level or 'general'},
{facial_expression or 'natural expression'},
{dominant_action or 'slight movement'} while speaking,
{lighting_mood or channel_style.lighting_mood} lighting,
{camera or channel_style.camera} camera angle,
{art_style or channel_style.art_style} style,
{environment or channel_style.environment},
{composition or channel_style.composition} composition,
brand tone: {channel_style.expression or 'natural'}"
```

Example output:
> "Time management tips, prioritize ruthlessly, mood: confident, viewer level: working professionals, smiling warmly, gesturing while explaining, warm lighting, eye-level camera angle, 3D render style, modern office, professional composition, brand tone: friendly"

**`build_lipsync_prompt`:**
```
"A {emotion or 'natural'} speaker,
{facial_expression or 'natural expression'},
{dominant_action or 'subtle movement'}},
{upper_body_pose or 'upright posture'},
{pace or 'steady pace'} speaking,
hook opens with: {hook_style or 'engaging statement'},
Vietnamese language naturally,
key point: {key_point or scene.topic},
brand tone: {channel_style.expression or 'friendly'}"
```

Example output:
> "A friendly speaker, smiling warmly, gesturing while explaining, slight lean forward, steady pace speaking, hook opens with: bold statement, Vietnamese language naturally, key point: prioritize ruthlessly, brand tone: friendly"

**`build_tts_guidance`:**
```
"Style: {mood or 'natural'}.
Tone: {emotion or 'conversational'} — {channel_style.expression or 'brand voice'}.
Pace: {pace or 'normal'} for {viewer_level or 'general'} viewers.
Key point to emphasize: {key_point or 'main idea'}.
Character voice: {character_name} ({voice_id or 'default'})."
```

Example output:
> "Style: confident. Tone: friendly — chuyên gia tài chính thân thiện. Pace: steady and measured for intermediate viewers. Key point to emphasize: prioritize ruthlessly. Character voice: NamMinh (vi-VN-NamMinhNeural)."

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

**Additional context now passed to the LLM:**

1. **Character voice descriptions** — for each character, include their `voice_id` (e.g., `"NamMinh: vi-VN-NamMinhNeural, style=chuyên gia tài chính"`). This tells the LLM how the character sounds so it can write dialogue appropriate to the voice model.

2. **Channel brand tone** — `cfg.style` (e.g., `"chuyên gia tài chính thân thiện"`) added to all prompt guidance so visuals and tone match brand.

3. **Character-per-scene voice binding** — each scene names one character; the LLM must write dialogue that matches that character's voice quality.

**Character voice list construction (in `_build_scene_prompt`):**

```python
# Build character list with voice context for LLM
char_lines = []
for c in cfg.characters:
    voice_info = c.voice_id if hasattr(c, 'voice_id') else ""
    char_lines.append(f"- {c.name}: {voice_info}")
char_list_str = "\n".join(char_lines)
```

Example output:
```
- NamMinh: vi-VN-NamMinhNeural, chuyên gia tài chính
- HoaiMy: vi-VN-HoaiMyNeural, diễn giả truyền cảm hứng
```

**Channel brand tone** is also included in the prompt header:
```
PHONG CÁCH KÊNH: {cfg.style}
```
This is separate from image style and is used by `PromptBuilder` to inform the brand tone in all 3 prompts.

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
- hook_style: cách mở đầu scene (bold statement | surprising stat | rhetorical question | story hook)
- viewer_level: trình độ viewer (beginner | intermediate | advanced | general)
- key_point: điểm chính cần nhớ của scene (1 cụm từ)
```

Character voice binding section added to system prompt:
```
NHÂN VẬT VÀ GIỌNG NÓI:
{char_list_str_with_voice_ids}

Mỗi scene chỉ chọn MỘT nhân vật. Lời thoại phải PHÙ HỢP với giọng nói của nhân vật được chọn.
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
            "hook_style": s.get("hook_style"),
            "viewer_level": s.get("viewer_level"),
            "key_point": s.get("key_point"),
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

brand_tone = getattr(self.ctx.channel, 'style', None) or ""
prompt_builder = PromptBuilder(
    channel_style=self.ctx.channel.image_style,
    brand_tone=brand_tone
)
img_prompt = prompt_builder.build_image_prompt(scene, metadata=scene.metadata)
```

### Lipsync prompt — use PromptBuilder with character voice

```python
char_name = char.name if hasattr(char, 'name') else str(char)
voice_id = char.tts if hasattr(char, 'tts') else None  # voice_id from SceneCharacter
lipsync_prompt = prompt_builder.build_lipsync_prompt(
    scene, metadata=scene.metadata,
    character_name=char_name, voice_id=voice_id
)
```

### TTS guidance — optional enhancement with character voice

```python
tts_guidance = prompt_builder.build_tts_guidance(
    scene, metadata=scene.metadata,
    character_name=char_name, voice_id=voice_id
)
# Optional: pass to TTS provider or use as voice selection hint
```

**Note:** `scene.metadata` is populated by `ContentIdeaGenerator._generate_scenes` after LLM extraction. `scene.metadata` is None for scenarios loaded directly from YAML (backward-compatible — `PromptBuilder` degrades to defaults).

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
