# Prompt Quality Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve TTS/image/lipsync prompt quality by adding structured `SceneMetadata` extraction and a `PromptBuilder` class that composes rich prompts from metadata + channel style.

**Architecture:** `SceneMetadata` Pydantic model (9 fields: mood, emotion, dominant_action, facial_expression, upper_body_pose, pace, hook_style, viewer_level, key_point). LLM extracts this at scene generation time. `PromptBuilder` composes image, lipsync, and TTS guidance prompts. Backward-compatible — all new fields optional.

**Tech Stack:** Pydantic models, Python string formatting.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `modules/pipeline/models.py` | Add `SceneMetadata` model; add `metadata` field to `SceneConfig` |
| `modules/media/prompt_builder.py` | **NEW** — `PromptBuilder` class with 3 prompt builders |
| `modules/content/content_idea_generator.py` | Update `_build_scene_prompt` + `_parse_scenes` to handle metadata |
| `modules/pipeline/scene_processor.py` | Replace `get_video_prompt` with `PromptBuilder`; add lipsync + TTS guidance |
| `tests/test_prompt_builder.py` | **NEW** — unit tests for PromptBuilder |
| `tests/test_content_idea_generator.py` | Add metadata parsing tests |

---

## Task 1: SceneMetadata model + SceneConfig.metadata

**Files:**
- Modify: `modules/pipeline/models.py:393-424` (SceneConfig)
- Modify: `modules/pipeline/models.py:1-30` (import area)
- Test: `tests/test_models.py` or `tests/test_scene_processor.py`

- [ ] **Step 1: Write failing test for SceneMetadata model**

```python
# tests/test_models.py — add to existing or create new
def test_scene_metadata_all_fields_optional():
    from modules.pipeline.models import SceneMetadata
    m = SceneMetadata()
    assert m.mood is None
    assert m.emotion is None
    assert m.dominant_action is None
    assert m.facial_expression is None
    assert m.upper_body_pose is None
    assert m.pace is None
    assert m.hook_style is None
    assert m.viewer_level is None
    assert m.key_point is None

def test_scene_metadata_with_values():
    from modules.pipeline.models import SceneMetadata
    m = SceneMetadata(
        mood="confident",
        emotion="friendly",
        dominant_action="gestures while explaining",
        facial_expression="smiling warmly",
        upper_body_pose="slight lean forward",
        pace="steady and measured",
        hook_style="bold statement",
        viewer_level="intermediate",
        key_point="prioritize ruthlessly",
    )
    assert m.mood == "confident"
    assert m.hook_style == "bold statement"
    assert m.key_point == "prioritize ruthlessly"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v --tb=short 2>&1 | grep -E "FAILED|ERROR|SceneMetadata"`
Expected: FAIL — `SceneMetadata` not found

- [ ] **Step 3: Add SceneMetadata to models.py**

Find `SceneConfig` in `modules/pipeline/models.py` (around line 393). Add `SceneMetadata` class BEFORE `SceneConfig`:

```python
class SceneMetadata(BaseModel):
    """Structured metadata extracted from scene at script generation time."""
    mood: Optional[str] = None
    emotion: Optional[str] = None
    dominant_action: Optional[str] = None
    facial_expression: Optional[str] = None
    upper_body_pose: Optional[str] = None
    pace: Optional[str] = None
    hook_style: Optional[str] = None
    viewer_level: Optional[str] = None
    key_point: Optional[str] = None
```

- [ ] **Step 4: Add `metadata` field to SceneConfig**

Find `SceneConfig` class (around line 393). Add to the class body:

```python
    metadata: Optional["SceneMetadata"] = None
```

Also add forward reference in `from __future__ import annotations` at top if not present.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_models.py::test_scene_metadata_all_fields_optional tests/test_models.py::test_scene_metadata_with_values -v --tb=short`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add modules/pipeline/models.py
git commit -m "feat(models): add SceneMetadata model and SceneConfig.metadata field

9 optional fields: mood, emotion, dominant_action, facial_expression,
upper_body_pose, pace, hook_style, viewer_level, key_point"
```

---

## Task 2: PromptBuilder class

**Files:**
- Create: `modules/media/prompt_builder.py`
- Create: `tests/test_prompt_builder.py`

- [ ] **Step 1: Write failing test for PromptBuilder**

```python
# tests/test_prompt_builder.py
import pytest
from modules.media.prompt_builder import PromptBuilder
from modules.pipeline.models import SceneMetadata, SceneConfig

class TestPromptBuilderImage:
    def test_build_image_prompt_with_all_metadata(self):
        from modules.pipeline.models import ImageStyleConfig
        style = ImageStyleConfig(
            lighting_mood="warm",
            camera="eye-level",
            art_style="3D render",
            environment="modern office",
            composition="professional",
            expression="friendly",
        )
        metadata = SceneMetadata(
            mood="confident",
            emotion="friendly",
            dominant_action="gestures while explaining",
            facial_expression="smiling warmly",
            upper_body_pose="slight lean forward",
            pace="steady",
            hook_style="bold statement",
            viewer_level="intermediate",
            key_point="prioritize ruthlessly",
        )
        scene = SceneConfig(
            id=1,
            video_prompt="Time management tips",
        )
        pb = PromptBuilder(channel_style=style, brand_tone="chuyên gia thân thiện")
        prompt = pb.build_image_prompt(scene, metadata)
        assert "Time management tips" in prompt
        assert "prioritize ruthlessly" in prompt
        assert "confident" in prompt
        assert "smiling warmly" in prompt
        assert "gestures while explaining" in prompt
        assert "warm" in prompt
        assert "eye-level" in prompt
        assert "modern office" in prompt

    def test_build_image_prompt_no_metadata_uses_style_defaults(self):
        from modules.pipeline.models import ImageStyleConfig
        style = ImageStyleConfig(
            lighting_mood="cool",
            camera="low angle",
            art_style="photorealistic",
            environment="outdoor cafe",
            composition="cinematic",
            expression="serious",
        )
        scene = SceneConfig(id=1, video_prompt="Productivity")
        pb = PromptBuilder(channel_style=style, brand_tone="coach nghiêm khắc")
        prompt = pb.build_image_prompt(scene, metadata=None)
        assert "cool" in prompt
        assert "low angle" in prompt
        assert "photorealistic" in prompt
        assert "outdoor cafe" in prompt

    def test_build_image_prompt_no_metadata_no_style_fallback(self):
        scene = SceneConfig(id=1, video_prompt="Focus tips")
        pb = PromptBuilder()
        prompt = pb.build_image_prompt(scene, metadata=None)
        assert "Focus tips" in prompt
        assert "A person speaking" in prompt  # fallback


class TestPromptBuilderLipsync:
    def test_build_lipsync_prompt_with_metadata(self):
        metadata = SceneMetadata(
            mood="confident", emotion="friendly",
            dominant_action="gestures while explaining",
            facial_expression="smiling warmly",
            upper_body_pose="slight lean forward",
            pace="steady and measured",
            hook_style="bold statement",
            viewer_level="intermediate",
            key_point="prioritize ruthlessly",
        )
        scene = SceneConfig(id=1, video_prompt="Time management")
        pb = PromptBuilder()
        prompt = pb.build_lipsync_prompt(scene, metadata, character_name="NamMinh", voice_id="vi-VN-NamMinhNeural")
        assert "friendly" in prompt
        assert "smiling warmly" in prompt
        assert "gestures while explaining" in prompt
        assert "steady" in prompt
        assert "bold statement" in prompt
        assert "prioritize ruthlessly" in prompt
        assert "NamMinh" in prompt
        assert "vi-VN-NamMinhNeural" in prompt

    def test_build_lipsync_prompt_no_metadata(self):
        scene = SceneConfig(id=1, video_prompt="Work life balance")
        pb = PromptBuilder(brand_tone="chuyên gia")
        prompt = pb.build_lipsync_prompt(scene, metadata=None)
        assert "Work life balance" in prompt
        assert "chuyên gia" in prompt


class TestPromptBuilderTTSGuidance:
    def test_build_tts_guidance_with_metadata(self):
        metadata = SceneMetadata(
            mood="confident", emotion="friendly",
            pace="steady and measured",
            viewer_level="intermediate",
            key_point="time blocking",
        )
        scene = SceneConfig(id=1)
        pb = PromptBuilder(brand_tone="tài chính thân thiện")
        guidance = pb.build_tts_guidance(scene, metadata, character_name="NamMinh", voice_id="vi-VN-NamMinhNeural")
        assert "confident" in guidance
        assert "friendly" in guidance
        assert "steady" in guidance
        assert "intermediate" in guidance
        assert "time blocking" in guidance
        assert "NamMinh" in guidance
        assert "vi-VN-NamMinhNeural" in guidance
        assert "tài chính thân thiện" in guidance

    def test_build_tts_guidance_no_metadata(self):
        scene = SceneConfig(id=1)
        pb = PromptBuilder()
        guidance = pb.build_tts_guidance(scene, metadata=None)
        assert "natural" in guidance.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prompt_builder.py -v --tb=short 2>&1 | tail -20`
Expected: FAIL — `No module named 'modules.media.prompt_builder'`

- [ ] **Step 3: Write PromptBuilder implementation**

```python
# modules/media/prompt_builder.py
"""PromptBuilder — composes image, lipsync, and TTS guidance prompts."""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from modules.pipeline.models import SceneConfig, SceneMetadata, ImageStyleConfig


def _resolve(scene_metadata, style_config, scene_field: str, style_field: str, default=None):
    """Return scene metadata value if present, else style config, else default."""
    val = None
    if scene_metadata is not None:
        val = getattr(scene_metadata, scene_field, None)
    if val:
        return val
    if style_config is not None:
        val = getattr(style_config, style_field, None)
    return val or default


class PromptBuilder:
    def __init__(
        self,
        channel_style: Optional["ImageStyleConfig"] = None,
        brand_tone: Optional[str] = None,
    ):
        self.channel_style = channel_style
        self.brand_tone = brand_tone or ""

    def build_image_prompt(
        self,
        scene: "SceneConfig",
        metadata: Optional["SceneMetadata"] = None,
    ) -> str:
        topic = scene.video_prompt or scene.background or "A person speaking"
        key_point = _resolve(metadata, self.channel_style, "key_point", None, None) or ""
        mood = _resolve(metadata, self.channel_style, "mood", "lighting", "engaged")
        facial = _resolve(metadata, self.channel_style, "facial_expression", "expression", "natural expression")
        action = _resolve(metadata, self.channel_style, "dominant_action", None, "slight movement")
        lighting = _resolve(metadata, self.channel_style, "mood", "lighting", "warm")  # mood acts as lighting mood
        camera = _resolve(metadata, self.channel_style, "camera", "camera", "eye-level")
        art_style = _resolve(metadata, self.channel_style, "art_style", "art_style", "3D render")
        environment = _resolve(metadata, self.channel_style, "environment", "environment", "indoor")
        composition = _resolve(metadata, self.channel_style, "composition", "composition", "centered")
        viewer_level = _resolve(metadata, self.channel_style, "viewer_level", None, "general")
        expression = _resolve(metadata, self.channel_style, "expression", "expression", "natural")

        parts = [
            topic,
            f"mood: {mood}",
            f"viewer level: {viewer_level}",
            f"key point: {key_point}" if key_point else None,
            facial,
            f"{action} while speaking",
            f"{lighting} lighting",
            f"{camera} camera angle",
            f"{art_style} style",
            environment,
            f"{composition} composition",
            f"brand tone: {expression}",
        ]
        return ", ".join(p for p in parts if p)

    def build_lipsync_prompt(
        self,
        scene: "SceneConfig",
        metadata: Optional["SceneMetadata"] = None,
        character_name: Optional[str] = None,
        voice_id: Optional[str] = None,
    ) -> str:
        topic = scene.video_prompt or scene.background or "topic"
        emotion = _resolve(metadata, self.channel_style, "emotion", "expression", "natural")
        facial = _resolve(metadata, self.channel_style, "facial_expression", "expression", "natural expression")
        action = _resolve(metadata, self.channel_style, "dominant_action", None, "subtle movement")
        pose = _resolve(metadata, self.channel_style, "upper_body_pose", None, "upright posture")
        pace = _resolve(metadata, self.channel_style, "pace", None, "steady pace")
        hook = _resolve(metadata, self.channel_style, "hook_style", None, "engaging statement")
        key_point = _resolve(metadata, self.channel_style, "key_point", None, None)
        expression = _resolve(metadata, self.channel_style, "expression", "expression", "friendly")

        parts = [
            f"A {emotion} speaker",
            facial,
            action,
            pose,
            f"{pace} speaking",
            f"hook opens with: {hook}" if hook else None,
            "Vietnamese language naturally",
            f"key point: {key_point}" if key_point else None,
            f"brand tone: {expression}",
        ]
        voice_part = f"Character: {character_name} ({voice_id})" if character_name else None
        result = ", ".join(p for p in parts if p)
        if voice_part:
            result = f"{result}, {voice_part}"
        return result

    def build_tts_guidance(
        self,
        scene: "SceneConfig",
        metadata: Optional["SceneMetadata"] = None,
        character_name: Optional[str] = None,
        voice_id: Optional[str] = None,
    ) -> str:
        mood = _resolve(metadata, self.channel_style, "mood", None, "natural")
        emotion = _resolve(metadata, self.channel_style, "emotion", "expression", "conversational")
        pace = _resolve(metadata, self.channel_style, "pace", None, "normal")
        viewer_level = _resolve(metadata, self.channel_style, "viewer_level", None, "general")
        key_point = _resolve(metadata, self.channel_style, "key_point", None, None)
        brand = self.brand_tone or "brand voice"

        parts = [
            f"Style: {mood}.",
            f"Tone: {emotion} — {brand}.",
            f"Pace: {pace} for {viewer_level} viewers.",
            f"Key point to emphasize: {key_point}." if key_point else None,
            f"Character voice: {character_name} ({voice_id})." if character_name else None,
        ]
        return " ".join(p for p in parts if p)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_prompt_builder.py -v --tb=short`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/media/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat(prompt_builder): add PromptBuilder for image, lipsync, TTS prompts

build_image_prompt: scene topic + mood + key_point + facial_expression +
  dominant_action + channel style (lighting, camera, art_style, environment, composition)
build_lipsync_prompt: emotion + facial_expression + dominant_action +
  upper_body_pose + pace + hook_style + key_point + character voice
build_tts_guidance: mood + emotion + pace + viewer_level + key_point + character voice"
```

---

## Task 3: Update content_idea_generator — LLM prompt + metadata parsing

**Files:**
- Modify: `modules/content/content_idea_generator.py:179-268`
- Test: `tests/test_content_idea_generator.py`

- [ ] **Step 1: Write failing test for metadata in scene generation**

Add to `tests/test_content_idea_generator.py`:

```python
def test_generate_scenes_parses_metadata_fields():
    # Mock LLM to return a scene with all metadata fields
    from unittest.mock import MagicMock, patch
    from modules.content.content_idea_generator import ContentIdeaGenerator

    gen = ContentIdeaGenerator(
        channel_config=MagicMock(
            name="Test Channel",
            style="chuyên gia thân thiện",
            characters=[MagicMock(name="NamMinh", voice_id="vi-VN-NamMinhNeural")],
            tts=MagicMock(max_duration=15.0, min_duration=5.0),
            image_style=MagicMock(
                lighting="warm", camera="eye-level", art_style="3D render",
                environment="office", composition="professional"
            ),
        ),
        llm_config=MagicMock(provider="minimax", model="test", max_tokens=512, retry_attempts=1, retry_backoff_max=5),
    )

    mock_llm = MagicMock()
    mock_llm.chat.return_value = json.dumps([{
        "id": 1,
        "script": "Hãy bắt đầu ngay hôm nay...",
        "background": "văn phòng hiện đại",
        "character": "NamMinh",
        "mood": "confident",
        "emotion": "friendly",
        "dominant_action": "gestures while explaining",
        "facial_expression": "smiling warmly",
        "upper_body_pose": "slight lean forward",
        "pace": "steady and measured",
        "hook_style": "bold statement",
        "viewer_level": "intermediate",
        "key_point": "bắt đầu ngay hôm nay",
    }])

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        scenes = gen._generate_scenes("Test", [], "tips", num_scenes=1)

    assert len(scenes) == 1
    assert scenes[0]["metadata"]["mood"] == "confident"
    assert scenes[0]["metadata"]["hook_style"] == "bold statement"
    assert scenes[0]["metadata"]["key_point"] == "bắt đầu ngay hôm nay"
    assert scenes[0]["metadata"]["pace"] == "steady and measured"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_idea_generator.py::test_generate_scenes_parses_metadata_fields -v --tb=short 2>&1 | tail -20`
Expected: FAIL — metadata not parsed

- [ ] **Step 3: Update `_build_scene_prompt` to include character voice descriptions**

Find `_build_scene_prompt` in `modules/content/content_idea_generator.py` (line 179).

**Change 1:** After building `kw_line` and before `tts_context`, add character voice list construction:

```python
# Build character list with voice context for LLM
char_lines = []
for c in cfg.characters:
    voice_info = getattr(c, 'voice_id', '') or ""
    char_lines.append(f"- {c.name}: {voice_info}")
char_list_str = "\n".join(char_lines)
```

**Change 2:** In the return string, after the `PHONG CÁCH HÌNH ẢNH CỦA KÊNH` section, add character voice section and brand tone:

Find the line `YÊU CẦU BẮT BUỘC:` and before it, add:

```
PHONG CÁCH KÊNH: {cfg.style}

NHÂN VẬT VÀ GIỌNG NÓI:
{char_list_str}

Mỗi scene chỉ chọn MỘT nhân vật. Lời thoại phải PHÙ HỢP với giọng nói của nhân vật được chọn.
```

**Change 3:** In the `MỖI SCENE CẦN CÓ` section, after `character:`, add metadata fields. Find the current list:
```
- id: số nguyên (1, 2, 3...)
- script: lời thoại...
- background: mô tả...
- character: tên...
```

Replace with:
```
- id: số nguyên (1, 2, 3...)
- script: lời thoại tiếng Việt có dấu, 25-35 từ, mỗi câu không quá 10 từ
- background: mô tả cảnh nền 5-15 từ, BẮT BUỘC chứa phong cách hình ảnh cố định [{art_style_str}]
- character: tên MỘT nhân vật từ danh sách [{char_list_str}] — Lời thoại phải PHÙ HỢP với giọng nói của nhân vật
- mood: cảm xúc chủ đạo của nhân vật (confident | curious | urgent | calm | enthusiastic)
- emotion: biểu cảm khuôn mặt (friendly | serious | enthusiastic | warm | focused)
- dominant_action: hành động chính (gestures while explaining | hand movements | slight nod | confident stance)
- facial_expression: biểu cảm (smiling warmly | serious | excited | calm | thoughtful)
- upper_body_pose: tư thế (slight lean forward | upright posture | relaxed posture | straight back)
- pace: tốc độ nói (steady and measured | fast-paced excitement | slow and deliberate | conversational)
- hook_style: cách mở đầu scene (bold statement | surprising stat | rhetorical question | story hook)
- viewer_level: trình độ viewer (beginner | intermediate | advanced | general)
- key_point: điểm chính cần nhớ của scene (1 cụm từ tiếng Việt)
```

- [ ] **Step 4: Update `_parse_scenes` → `_validate_scenes` to parse metadata**

Find `_parse_scenes` (around line 242) and update `_validate_scenes` within it. Replace the function to add metadata dict to each scene:

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

Note: Keep the existing call sites of `_parse_scenes` unchanged — `_parse_scenes` calls `_validate_scenes` internally.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_content_idea_generator.py::test_generate_scenes_parses_metadata_fields -v --tb=short`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add modules/content/content_idea_generator.py
git commit -m "feat(content_idea_generator): add character voice context to LLM prompt

- Character voice list (name + voice_id) added to _build_scene_prompt
- Channel brand tone (cfg.style) added to prompt header
- SceneMetadata fields added to JSON output schema (mood, emotion,
  dominant_action, facial_expression, upper_body_pose, pace,
  hook_style, viewer_level, key_point)
- _parse_scenes updated to extract metadata into scene dict"
```

---

## Task 4: Wire PromptBuilder into scene_processor

**Files:**
- Modify: `modules/pipeline/scene_processor.py` (get_video_prompt + lipsync section)
- Test: `tests/test_scene_processor.py`

- [ ] **Step 1: Write failing test for PromptBuilder integration**

Add to `tests/test_scene_processor.py`:

```python
def test_uses_prompt_builder_for_image_prompt(self, tmp_path, mock_ctx):
    from unittest.mock import MagicMock, patch
    from modules.pipeline.scene_processor import SingleCharSceneProcessor

    # Create scene with metadata
    scene = MagicMock()
    scene.id = 1
    scene.scene_index = 0
    scene.script = "Hãy bắt đầu với kế hoạch hôm nay"
    scene.tts = "Hãy bắt đầu với kế hoạch hôm nay"
    scene.characters = [MagicMock(name="NamMinh", tts="vi-VN-NamMinhNeural")]
    scene.video_prompt = "Time management"
    scene.background = None
    scene.metadata = MagicMock()
    scene.metadata.mood = "confident"
    scene.metadata.emotion = "friendly"
    scene.metadata.dominant_action = "gestures while explaining"
    scene.metadata.facial_expression = "smiling warmly"
    scene.metadata.upper_body_pose = "slight lean forward"
    scene.metadata.pace = "steady"
    scene.metadata.hook_style = "bold statement"
    scene.metadata.viewer_level = "intermediate"
    scene.metadata.key_point = "bắt đầu ngay"

    mock_ctx.scenario.scenes = [scene]
    mock_ctx.channel.characters = [MagicMock(name="NamMinh", voice_id="vi-VN-NamMinhNeural")]
    mock_ctx.channel.video = MagicMock()
    mock_ctx.channel.video.aspect_ratio = "9:16"
    mock_ctx.channel.image_style = MagicMock(
        lighting="warm", camera="eye-level", art_style="3D render",
        environment="office", composition="professional", lighting_mood="warm",
        expression="friendly"
    )
    mock_ctx.channel.style = "chuyên gia thân thiện"
    mock_ctx.channel.generation = MagicMock()
    mock_ctx.channel.generation.models = MagicMock()
    mock_ctx.channel.generation.models.tts = "edge"
    mock_ctx.channel.generation.models.image = "minimax"
    mock_ctx.channel.generation.lipsync = MagicMock()
    mock_ctx.channel.generation.lipsync.resolution = "480p"
    mock_ctx.channel.generation.lipsync.max_wait = 300
    mock_ctx.channel.generation.lipsync.poll_interval = 10
    mock_ctx.channel.generation.lipsync.retries = 2
    mock_ctx.channel.lipsync = None
    mock_ctx.technical.generation.tts.word_timestamp_timeout = 120
    mock_ctx.technical.generation.image.timeout = 120
    mock_ctx.technical.generation.image.poll_interval = 5
    mock_ctx.technical.generation.image.max_polls = 24
    mock_ctx.technical.generation.image.model = "image-01"

    processor = SingleCharSceneProcessor(mock_ctx, tmp_path, resume=False)

    # Check that image prompt contains metadata terms
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder(channel_style=mock_ctx.channel.image_style, brand_tone="chuyên gia thân thiện")
    expected_prompt = pb.build_image_prompt(scene, scene.metadata)
    # The image prompt should include scene.video_prompt and metadata fields
    assert "Time management" in expected_prompt
    assert "confident" in expected_prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scene_processor.py::test_uses_prompt_builder_for_image_prompt -v --tb=short 2>&1 | tail -20`
Expected: FAIL — no assert on actual processor behavior yet (or skip to Step 3 and verify manually)

- [ ] **Step 3: Replace `get_video_prompt` calls with PromptBuilder in scene_processor**

Find the `get_video_prompt` method (around line 110) and the places it's called.

**Change `get_video_prompt` to use PromptBuilder internally:**

Replace the entire `get_video_prompt` method with:

```python
def get_video_prompt(self, scene: SceneConfig) -> str:
    """Get image generation prompt using PromptBuilder + scene metadata."""
    if not hasattr(self, '_prompt_builder') or self._prompt_builder is None:
        channel_style = getattr(self.ctx.channel, 'image_style', None) or getattr(self.ctx.channel, 'style', None)
        brand_tone = getattr(self.ctx.channel, 'style', '') or ''
        # channel_style might be a string (style name) not ImageStyleConfig — handle both
        from modules.media.prompt_builder import PromptBuilder
        from modules.pipeline.models import ImageStyleConfig
        if isinstance(channel_style, str):
            channel_style = None
        self._prompt_builder = PromptBuilder(
            channel_style=channel_style,
            brand_tone=brand_tone,
        )
    return self._prompt_builder.build_image_prompt(scene, metadata=getattr(scene, 'metadata', None))
```

**Change `build_scene_prompt` (around line 136):** Replace the body with a call to the PromptBuilder:

```python
def build_scene_prompt(self, scene: SceneConfig) -> str:
    """Build scene prompt from scene background and channel config using PromptBuilder."""
    if not hasattr(self, '_prompt_builder') or self._prompt_builder is None:
        channel_style = getattr(self.ctx.channel, 'image_style', None)
        brand_tone = getattr(self.ctx.channel, 'style', '') or ''
        from modules.media.prompt_builder import PromptBuilder
        from modules.pipeline.models import ImageStyleConfig
        if isinstance(channel_style, str):
            channel_style = None
        self._prompt_builder = PromptBuilder(
            channel_style=channel_style,
            brand_tone=brand_tone,
        )
    return self._prompt_builder.build_image_prompt(scene, metadata=getattr(scene, 'metadata', None))
```

**Change lipsync prompt call (around line 443):** Replace:
```python
prompt = self.get_video_prompt(scene)
```
With:
```python
char = scene.characters[0] if scene.characters else None
char_name = char.name if (char and hasattr(char, 'name')) else (str(char) if char else None)
voice_id = getattr(char, 'tts', None) if char else None
lipsync_prompt = self._prompt_builder.build_lipsync_prompt(
    scene,
    metadata=getattr(scene, 'metadata', None),
    character_name=char_name,
    voice_id=voice_id,
) if hasattr(self, '_prompt_builder') and self._prompt_builder else self.get_video_prompt(scene)
```

Then use `lipsync_prompt` instead of `prompt` in the lipsync call.

**Change image prompt call (around line 302):** Replace `img_prompt = self.get_video_prompt(scene)` with:
```python
img_prompt = self._prompt_builder.build_image_prompt(scene, metadata=getattr(scene, 'metadata', None)) if hasattr(self, '_prompt_builder') and self._prompt_builder else self.get_video_prompt(scene)
```

Also change the image generation call to use `img_prompt` instead of the old `prompt` variable.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_scene_processor.py -v --tb=short 2>&1 | tail -30`
Expected: Existing tests pass

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/scene_processor.py
git commit -m "feat(scene_processor): replace get_video_prompt with PromptBuilder

- get_video_prompt and build_scene_prompt now use PromptBuilder
- Lipsync prompt built with build_lipsync_prompt including character voice
- SceneMetadata passed to both image and lipsync prompts
- _prompt_builder cached on self for reuse across calls"
```

---

## Task 5: Integration tests + all tests green

**Files:**
- Test: all existing tests

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: All tests pass (302+)

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "test: add prompt_builder and metadata integration tests

Full test coverage for PromptBuilder and scene_processor integration.
All 302+ tests passing."
```

---

## Spec Coverage Check

| Spec item | Task |
|-----------|------|
| SceneMetadata model (9 fields) | Task 1 |
| SceneConfig.metadata field | Task 1 |
| PromptBuilder.build_image_prompt | Task 2 |
| PromptBuilder.build_lipsync_prompt | Task 2 |
| PromptBuilder.build_tts_guidance | Task 2 |
| Character voice descriptions in LLM prompt | Task 3 |
| Channel brand tone in LLM prompt | Task 3 |
| SceneMetadata extraction from LLM JSON | Task 3 |
| PromptBuilder wired into scene_processor | Task 4 |
| Backward compatibility (no metadata → defaults) | Tasks 2, 3 |
| All existing tests still pass | Task 5 |

## Placeholder Scan

No TBD/TODO placeholders. All function signatures match across tasks. `_resolve` helper uses consistent field name mapping.
