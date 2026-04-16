# Prompt Quality Pipeline — Full Redesign

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Improve quality of prompts for image and lipsync by having the LLM generate complete, ready-to-use prompts directly from script content — no assembly, no fallbacks, no defaults.

**Architecture:** LLM generates complete `image_prompt` and `lipsync_prompt` strings directly in one pass. `PromptBuilder` becomes a **style validator** that checks generated prompts against channel style constraints. `SceneConfig` gains `image_prompt` and `lipsync_prompt` fields. Backward-compatible — these fields are optional.

---

## 1. New Data Models

### `SceneConfig.image_prompt` and `lipsync_prompt` — `modules/pipeline/models.py`

**Removed:** `SceneMetadata` model and `metadata` field.

**Added:** Two new optional fields to `SceneConfig`:

```python
class SceneConfig(BaseModel):
    """Một scene từ scenario YAML file."""
    id: int = 0
    tts: Optional[str] = None
    script: Optional[str] = None
    characters: List["SceneCharacter | str"] = []
    video_prompt: Optional[str] = None   # legacy fallback for YAML scenes
    background: Optional[str] = None    # legacy fallback for YAML scenes
    image_prompt: Optional[str] = None  # NEW — LLM-generated, ready to use
    lipsync_prompt: Optional[str] = None # NEW — LLM-generated, ready to use
```

**Why no `metadata` model:** The LLM generates complete prompts directly. No need to assemble from parts.

---

## 2. PromptBuilder — `modules/media/prompt_builder.py` (NEW)

**Role changed:** PromptBuilder is now a **style validator** — not a prompt composer. It checks whether a generated `image_prompt` or `lipsync_prompt` violates channel style constraints. Returns `(is_valid, violations_list)`.

For YAML scenes without generated prompts: simple fallback — `scene.video_prompt` used directly as both image and lipsync prompt.

### Class

```python
class PromptBuilder:
    def __init__(self, channel_style: Optional[ImageStyleConfig] = None, brand_tone: Optional[str] = None):
        self.channel_style = channel_style
        self.brand_tone = brand_tone

    def validate_image_prompt(self, image_prompt: Optional[str]) -> tuple[bool, list[str]]:
        """Validate image_prompt against channel style constraints.

        Returns (is_valid, violations):
          - is_valid: True if no violations found
          - violations: list of constraint names that were not found in the prompt
        """

    def validate_lipsync_prompt(self, lipsync_prompt: Optional[str], character_name: Optional[str] = None) -> tuple[bool, list[str]]:
        """Validate lipsync_prompt. Returns (is_valid, violations)."""

    def get_image_prompt(self, scene: SceneConfig) -> str:
        """Get image prompt: use scene.image_prompt if present, else scene.video_prompt as fallback."""

    def get_lipsync_prompt(self, scene: SceneConfig) -> str:
        """Get lipsync prompt: use scene.lipsync_prompt if present, else scene.video_prompt as fallback."""
```

### Validation Logic

`validate_image_prompt` checks that the prompt string contains all channel style constraint keywords:

```python
def validate_image_prompt(self, image_prompt: Optional[str]) -> tuple[bool, list[str]]:
    if not image_prompt:
        return False, ["image_prompt missing"]
    if not self.channel_style:
        return True, []  # no constraints to check

    violations = []
    prompt_lower = image_prompt.lower()

    constraints = {
        "lighting": getattr(self.channel_style, "lighting", None),
        "camera": getattr(self.channel_style, "camera", None),
        "art_style": getattr(self.channel_style, "art_style", None),
        "environment": getattr(self.channel_style, "environment", None),
        "composition": getattr(self.channel_style, "composition", None),
    }
    for name, value in constraints.items():
        if value and value.lower() not in prompt_lower:
            violations.append(name)

    return len(violations) == 0, violations
```

`validate_lipsync_prompt` checks that lipsync prompt is non-empty and mentions the character voice:

```python
def validate_lipsync_prompt(self, lipsync_prompt: Optional[str], character_name: Optional[str] = None) -> tuple[bool, list[str]]:
    if not lipsync_prompt:
        return False, ["lipsync_prompt missing"]
    violations = []
    if character_name and character_name.lower() not in lipsync_prompt.lower():
        violations.append("character_name_missing")
    return len(violations) == 0, violations
```

### Prompt Access (no fallbacks)

```python
def get_image_prompt(self, scene: SceneConfig) -> str:
    return scene.image_prompt or scene.video_prompt or ""

def get_lipsync_prompt(self, scene: SceneConfig) -> str:
    return scene.lipsync_prompt or scene.video_prompt or ""
```

If both are empty → no prompt is used → image/lipsync generation will receive empty string (upstream to handle).

---

## 3. Updated Scene Generation — `content_idea_generator.py`

### `_build_scene_prompt` — LLM generates complete prompts directly

**Key change:** The LLM writes complete `image_prompt` and `lipsync_prompt` strings — it does NOT output individual metadata fields to be assembled later.

**Character voice context** is still passed so the LLM can write appropriate lipsync prompts:

```python
# Build character list with voice context for LLM
char_lines = []
for c in cfg.characters:
    voice_info = getattr(c, 'voice_id', '') or ""
    char_lines.append(f"- {c.name}: {voice_info}")
char_list_str = "\n".join(char_lines)
```

Example:
```
- NamMinh: vi-VN-NamMinhNeural
- HoaiMy: vi-VN-HoaiMyNeural
```

**System prompt — RÀNG BUỘC PHONG CÁCH (constraints embedded, not assembled):**

```
PHONG CÁCH HÌNH ẢNH CỦA KÊNH (phải TUÂN THỦ tuyệt đối):
- Lighting: {img_style.lighting or 'warm'}
- Camera: {img_style.camera or 'eye-level'}
- Art style: {img_style.art_style or '3D render'}
- Environment: {img_style.environment or 'modern office'}
- Composition: {img_style.composition or 'professional'}

PHONG CÁCH KÊNH (brand tone):
{cfg.style}
```

**JSON output format — LLM writes complete prompts directly:**

**OLD:**
```json
[{"id": 1, "script": "...", "background": "...", "character": "NamMinh"}]
```

**NEW:**
```json
[{
  "id": 1,
  "script": "Hãy bắt đầu với kế hoạch hôm nay...",
  "background": "văn phòng hiện đại",
  "character": "NamMinh",
  "image_prompt": "A confident professional speaker in modern office, warm lighting, eye-level camera, 3D render style, professional and knowledgeable atmosphere, gesturing naturally while speaking Vietnamese",
  "lipsync_prompt": "Friendly speaker, NamMinh, vi-VN-NamMinhNeural, smiling warmly, gesturing while explaining, slight lean forward, steady and measured pace, Vietnamese language naturally"
}]
```

**System prompt instruction — replace metadata field list with:**

```
VIẾT TRỰC TIẾP image_prompt VÀ lipsync_prompt — KHÔNG cần metadata từng trường:

MỖI SCENE CẦN CÓ:
- id, script, background, character (như hiện tại)
- image_prompt: PROMPT HOÀN CHỈNH cho image gen. VIẾT LUÔN một chuỗi đầy đủ, không liệt kê từng trường.
  Phải CHỨA các ràng buộc phong cách hình ảnh ở trên.
- lipsync_prompt: PROMPT HOÀN CHỈNH cho lipsync. VIẾT LUÔN một chuỗi mô tả người nói.
  Phải mô tả: phong cách người nói (phù hợp brand tone), character name + voice_id, biểu cảm, hành động, tư thế, pace.

NHÂN VẬT VÀ GIỌNG NÓI:
{char_list_str}

Mỗi scene chỉ chọn MỘT nhân vật. Lời thoại phải PHÙ HỢP với giọng nói của nhân vật được chọn.
```

### `_parse_scenes` — updated to parse image_prompt and lipsync_prompt

```python
def _parse_scenes(self, text: str) -> List[Dict]:
    # Existing JSON parsing logic...
    scenes = json.loads(text)
    if isinstance(scenes, dict):
        scenes = scenes.get("scenes", [scenes])
    if isinstance(scenes, list) and scenes:
        scenes = self._validate_scenes(scenes)
    return scenes

def _validate_scenes(self, scenes: List[Dict]) -> List[Dict]:
    for s in scenes:
        # Normalize: ensure image_prompt and lipsync_prompt are present (or None)
        s["image_prompt"] = s.get("image_prompt") or None
        s["lipsync_prompt"] = s.get("lipsync_prompt") or None
    return scenes
```

---

## 4. Updated `scene_processor.py`

### Image prompt — use `PromptBuilder.get_image_prompt()`

```python
prompt_builder = PromptBuilder(
    channel_style=self.ctx.channel.image_style,
    brand_tone=getattr(self.ctx.channel, 'style', '') or ''
)

img_prompt = prompt_builder.get_image_prompt(scene)
is_valid, violations = prompt_builder.validate_image_prompt(img_prompt)
if not is_valid:
    logger.warning(f"  ⚠️ image_prompt violations: {violations}")
```

### Lipsync prompt — use `PromptBuilder.get_lipsync_prompt()`

```python
char = scene.characters[0] if scene.characters else None
char_name = char.name if (char and hasattr(char, 'name')) else (str(char) if char else None)
voice_id = getattr(char, 'tts', None) if char else None

lipsync_prompt = prompt_builder.get_lipsync_prompt(scene)
is_valid, violations = prompt_builder.validate_lipsync_prompt(lipsync_prompt, character_name=char_name)
if not is_valid:
    logger.warning(f"  ⚠️ lipsync_prompt violations: {violations}")
```

### Backward compatibility for YAML scenes

If `scene.image_prompt` is `None` and `scene.video_prompt` is `None`:
- `get_image_prompt()` returns `""` → image generation uses empty/fallback prompt
- Same for lipsync

`get_video_prompt()` method is kept as alias for any external callers using it directly.

---

## 5. Files Summary

| File | Action |
|------|--------|
| `modules/pipeline/models.py` | Add `image_prompt` and `lipsync_prompt` to `SceneConfig`; remove `metadata` |
| `modules/media/prompt_builder.py` | **CREATE NEW** — `PromptBuilder` as style validator + simple getter |
| `modules/content/content_idea_generator.py` | Update `_build_scene_prompt` LLM instruction + `_parse_scenes` |
| `modules/pipeline/scene_processor.py` | Use `PromptBuilder.get_image_prompt()` + `validate_image_prompt()` |
| `configs/channels/{channel}/config.yaml` | No changes required |

---

## 6. Backward Compatibility

- `image_prompt` and `lipsync_prompt` are optional — YAML scenes without them use `video_prompt` as fallback via `get_image_prompt()`/`get_lipsync_prompt()`
- `ImageStyleConfig` unchanged — existing channel configs work
- `get_video_prompt()` kept for any external callers
- No new required fields anywhere

---

## 7. Error Handling

- `image_prompt` missing → `get_image_prompt()` returns `video_prompt` → if that's also `None`, returns `""`
- `lipsync_prompt` missing → same fallback chain
- Style validation violations → `validate_image_prompt()` returns `violations` list → logged as warning (not blocking)
- Validation is **advisory** — prompts are used even if they violate style constraints

---

## 8. Testing

1. `test_validate_image_prompt_all_constraints_met` — prompt contains all style keywords → valid
2. `test_validate_image_prompt_missing_constraint` — missing one constraint → violations list
3. `test_validate_image_prompt_no_style_config` → always valid
4. `test_validate_lipsync_prompt_with_character` — character name in prompt → valid
5. `test_validate_lipsync_prompt_missing_character` → violations
6. `test_get_image_prompt_uses_scene_field` — scene.image_prompt returned when present
7. `test_get_image_prompt_fallback_to_video_prompt` — falls back correctly
8. Integration test: LLM generates scenes with `image_prompt` and `lipsync_prompt` fields
9. All existing tests pass (302+)
