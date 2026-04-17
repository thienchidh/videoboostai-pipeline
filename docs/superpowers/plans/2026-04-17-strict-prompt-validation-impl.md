# Strict Image Prompt Validation with Retry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Block pipeline when `image_prompt` is missing channel style constraints (`art_style`, `environment`, etc.) after scene generation. LLM prompt updated to embed constraints forcefully; validation with retry added.

**Architecture:** After scene generation, each scene's `image_prompt` is validated via `PromptBuilder.validate_image_prompt()`. If violations exist, the full scene is regenerated with explicit feedback. After 3 failures, `SceneValidationError` is raised → caught by pipeline → script regeneration triggered.

**Tech Stack:** Python 3, pytest, existing `PromptBuilder`, existing `@retry` (tenacity) decorator in `_generate_scenes`.

---

## File Structure

- `modules/pipeline/exceptions.py` — Add `SceneValidationError`
- `modules/content/content_idea_generator.py` — Add constraint rules to `_build_scene_prompt`, update JSON example, add `_validate_and_fix_scene()` with retry, add `_build_retry_prompt()`
- `modules/media/prompt_builder.py` — No changes (already has `validate_image_prompt`)
- `tests/test_prompt_builder.py` — Add validation tests
- `tests/test_content_idea_generator.py` — Add retry validation tests

---

## Tasks

### Task 1: Add `SceneValidationError` to exceptions

**Files:**
- Modify: `modules/pipeline/exceptions.py:81-82` (append after `ContentPipelineExhaustedError`)

- [ ] **Step 1: Add the exception class**

```python
class SceneValidationError(Exception):
    """Raised when scene fails validation after max retries.

    Attributes:
        scene_id: ID of the scene
        violations: list of constraint names that were missing
    """
    def __init__(self, scene_id: int, violations: list[str]):
        self.scene_id = scene_id
        self.violations = violations
        msg = f"Scene {scene_id} failed validation after 3 retries: missing {violations}"
        super().__init__(msg)
```

- [ ] **Step 2: Verify file still imports correctly**

Run: `python -c "from modules.pipeline.exceptions import SceneValidationError; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add modules/pipeline/exceptions.py
git commit -m "feat(exceptions): add SceneValidationError for strict prompt validation"
```

---

### Task 2: Add constraint rules to `_build_scene_prompt`

**Files:**
- Modify: `modules/content/content_idea_generator.py:244` (after IMAGE STYLE CONSTRAINTS section)

- [ ] **Step 1: Read current `_build_scene_prompt` IMAGE STYLE CONSTRAINTS section**

Run: `grep -n "IMAGE STYLE CONSTRAINTS" modules/content/content_idea_generator.py`
Expected output shows line number

- [ ] **Step 2: Update the prompt section**

In `_build_scene_prompt` (line ~221-230), replace the existing `img_style_str` block with the new constraint rules added after it:

After line 228-230 (the `else: img_style_str = "(không có constraints cụ thể)"` block), add the strict rules:

```python
        return f"""Bạn là chuyên gia sản xuất video viral cho kênh "{cfg.name}".
Viết {num_scenes} scene với prompts SÁNG TẠO, KHÔNG LẶP LẠI.

{desc_line}{kw_line}Phong cách nội dung: {angle}{tts_context}

PHONG CÁCH KÊNH (brand tone):
{cfg.style}

IMAGE STYLE CONSTRAINTS (phải include trong image_prompt):
{img_style_str}

QUY TẮC NGHIÊM NGẶT — image_prompt PHẢI CHỨA ĐỦ:
- "{img_style.art_style}" — đây là bắt buộc, KHÔNG được bỏ qua
- "{img_style.environment}" — đây là bắt buộc, KHÔNG được bỏ qua
- "{img_style.lighting}" — đây là bắt buộc, KHÔNG được bỏ qua
- "{img_style.camera}" — đây là bắt buộc, KHÔNG được bỏ qua
- "{img_style.composition}" — đây là bắt buộc, KHÔNG được bỏ qua

NẾU thiếu bất kỳ constraint nào → scene sẽ bị REJECT và yêu cầu regenerate.
"""
```

Note: The f-string body starts at line 232. You need to replace lines 232-261 (the entire prompt string) with the updated version that includes the strict rules AND the updated JSON example.

- [ ] **Step 3: Update JSON example to show actual constraint values**

In the JSON example (line ~317), change:
```
"image_prompt": "3D Pixar Disney style, [visual_concept], [emotion], warm lighting, eye-level camera, professional composition",
```
To:
```
"image_prompt": "{img_style.art_style}, {img_style.environment}, {img_style.lighting} lighting, {img_style.camera} camera, {img_style.composition} composition, [visual_concept]",
```

Since we're inside an f-string, `{{` and `}}` are literal braces in the output. Use actual placeholders like `{img_style.art_style}` which will be filled in at prompt-building time.

Actually, wait — `img_style.art_style` etc. are Python variables available in the scope of `_build_scene_prompt`. So they will be interpolated by the f-string correctly. The JSON example is inside the f-string, so it will show actual values like "3D render", "modern office", etc. in the prompt the LLM sees.

- [ ] **Step 4: Run existing tests to verify prompt still works**

Run: `pytest tests/test_content_idea_generator.py -v -k "test_generate" --tb=short 2>&1 | head -50`
Expected: Tests pass

- [ ] **Step 5: Commit**

```bash
git add modules/content/content_idea_generator.py
git commit -m "feat(content): embed strict constraint rules in scene prompt"
```

---

### Task 3: Add `_validate_and_fix_scene()` with retry to `content_idea_generator.py`

**Files:**
- Modify: `modules/content/content_idea_generator.py` (add methods after `_regenerate_scene_tts`)

First locate where `_regenerate_scene_tts` ends:

Run: `grep -n "def _regenerate_scene_tts" modules/content/content_idea_generator.py`
Expected output shows starting line

- [ ] **Step 1: Read the end of `_regenerate_scene_tts` to find insertion point**

Run: `grep -n "def _validate_scenes\|def _regenerate_scene_tts" modules/content/content_idea_generator.py`
Expected output shows both method names. `_validate_scenes` starts at 560, `_regenerate_scene_tts` ends around 558.

Insert the new methods before `_validate_scenes` (before line 560).

- [ ] **Step 2: Add `_validate_and_fix_scene` and `_build_retry_prompt` methods**

Add these methods right before `_validate_scenes` (around line 559):

```python
    def _validate_and_fix_scene(self, scene_dict: dict, attempt: int,
                                  max_attempts: int = 3) -> SceneConfig:
        """Validate scene image_prompt against channel style constraints.

        If violations found and attempt < max_attempts: regenerate full scene with feedback.
        If attempt >= max_attempts: raise SceneValidationError.
        """
        from modules.media.prompt_builder import PromptBuilder

        prompt_builder = PromptBuilder(
            channel_style=self._channel_config.image_style if self._channel_config else None,
            brand_tone=getattr(self._channel_config, 'style', '') or ''
        )

        image_prompt = scene_dict.get('image_prompt') or ""
        is_valid, violations = prompt_builder.validate_image_prompt(image_prompt)

        if is_valid:
            return self._dict_to_scene(scene_dict)

        logger.warning(f"  ⚠️ Scene {scene_dict.get('id', 0)} image_prompt violations "
                      f"[attempt {attempt}/{max_attempts}]: {violations}")

        if attempt >= max_attempts:
            raise SceneValidationError(
                scene_id=scene_dict.get('id', 0),
                violations=violations
            )

        # Retry: regenerate full scene with feedback
        retry_prompt = self._build_retry_prompt(scene_dict, violations, attempt)
        retry_text = self._call_llm_for_retry(retry_prompt)
        retry_scenes = self._parse_scenes(retry_text)
        if retry_scenes:
            return self._validate_and_fix_scene(retry_scenes[0], attempt + 1, max_attempts)
        raise SceneValidationError(scene_id=scene_dict.get('id', 0), violations=violations)

    def _build_retry_prompt(self, scene_dict: dict, violations: list[str],
                            attempt: int) -> str:
        """Build a prompt to regenerate a scene that failed validation."""
        scene_id = scene_dict.get('id', 0)
        script = scene_dict.get('script', '')
        character = scene_dict.get('character', '')
        creative_brief = scene_dict.get('creative_brief', {})

        return f"""Regenerate scene {scene_id}. Image prompt was MISSING constraints: {violations}.
The image_prompt MUST contain all of these exact keywords: {', '.join(violations)}

Original scene context:
- script: {script}
- character: {character}
- creative_brief: {creative_brief}

Return a JSON object with the full scene (same format as before). The new image_prompt must include all the missing constraints."""

    def _call_llm_for_retry(self, prompt: str) -> str:
        """Call LLM for retry prompt (separate from main generation)."""
        from modules.llm import get_llm_provider
        from modules.pipeline.models import TechnicalConfig

        tech_cfg = self._technical_config if self._technical_config else TechnicalConfig.load()
        api_key = tech_cfg.api_keys.minimax

        llm = get_llm_provider(
            name=self._llm.provider if self._llm else "minimax",
            api_key=api_key,
            model=self._llm.model if self._llm else "MiniMax-M2.7",
        )
        return llm.chat(prompt, max_tokens=self._llm.max_tokens if self._llm else 1536)

    def _dict_to_scene(self, scene_dict: dict) -> "SceneConfig":
        """Convert a dict to SceneConfig after validation passes."""
        char = scene_dict.get("character") or scene_dict.get("characters")
        if isinstance(char, list):
            char = char[0] if char else "Narrator"
        elif not isinstance(char, str) or not char:
            char = "Narrator"

        scene_dict["character"] = char
        char_gender = scene_dict.get("gender")
        scene_dict["characters"] = [{"name": char, "gender": char_gender}]
        scene_dict.pop("character", None)
        scene_dict["image_prompt"] = scene_dict.get("image_prompt") or None
        scene_dict["lipsync_prompt"] = scene_dict.get("lipsync_prompt") or None
        scene_dict["creative_brief"] = scene_dict.get("creative_brief") or None

        return SceneConfig.from_dict(scene_dict)
```

- [ ] **Step 3: Import `SceneValidationError` at top of file**

Check existing imports in `content_idea_generator.py` (around line 17). Add to the import from `modules.pipeline.exceptions`:

```python
from modules.pipeline.exceptions import ConfigMissingKeyError, SceneValidationError
```

- [ ] **Step 4: Run tests to verify no import/syntax errors**

Run: `python -c "from modules.content.content_idea_generator import ContentIdeaGenerator; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add modules/content/content_idea_generator.py
git commit -m "feat(content): add strict image prompt validation with retry"
```

---

### Task 4: Wire `_validate_and_fix_scene` into `_generate_scenes`

**Files:**
- Modify: `modules/content/content_idea_generator.py:163-184` (the TTS validation loop section)

- [ ] **Step 1: Read the current post-generation validation section**

The TTS validation happens in `_generate_scenes` at lines 163-184. After the TTS loop, add image_prompt validation with retry.

- [ ] **Step 2: Add image prompt validation after TTS validation**

After the TTS validation loop (after line 182-183, before `return scenes, video_message`):

```python
        # Validate image_prompt constraints and retry if violations found
        if self._channel_config and self._channel_config.image_style:
            validated_scenes = []
            for scene in scenes:
                try:
                    validated = self._validate_and_fix_scene(
                        {"id": scene.id, "script": getattr(scene, 'tts', '') or getattr(scene, 'script', ''),
                         "character": scene.characters[0].name if scene.characters else None,
                         "image_prompt": scene.image_prompt,
                         "creative_brief": getattr(scene, 'creative_brief', None)},
                        attempt=1
                    )
                    validated_scenes.append(validated)
                except SceneValidationError as e:
                    logger.error(f"  ❌ Scene validation exhausted after 3 retries: {e}")
                    raise
            scenes = validated_scenes

        return scenes, video_message
```

Actually, `_validate_and_fix_scene` expects a dict from the LLM raw output. The scene is already a `SceneConfig` after `_parse_scenes`. We need to pass a dict representation. Let me refine:

```python
        # Validate image_prompt constraints and retry if violations found
        if self._channel_config and self._channel_config.image_style:
            validated_scenes = []
            for scene in scenes:
                scene_dict = {
                    "id": scene.id,
                    "script": getattr(scene, 'tts', '') or getattr(scene, 'script', ''),
                    "character": scene.characters[0].name if scene.characters else None,
                    "image_prompt": scene.image_prompt,
                    "lipsync_prompt": scene.lipsync_prompt,
                    "creative_brief": getattr(scene, 'creative_brief', None),
                    "scene_type": getattr(scene, 'scene_type', None),
                    "delivers": getattr(scene, 'delivers', None),
                }
                try:
                    validated = self._validate_and_fix_scene(scene_dict, attempt=1)
                    validated_scenes.append(validated)
                except SceneValidationError as e:
                    logger.error(f"  ❌ Scene validation exhausted: {e}")
                    raise
            scenes = validated_scenes
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_content_idea_generator.py -v --tb=short 2>&1 | head -80`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add modules/content/content_idea_generator.py
git commit -m "feat(content): wire strict image prompt validation into scene generation"
```

---

### Task 5: Add tests for `SceneValidationError`

**Files:**
- Modify: `tests/test_content_idea_generator.py`

- [ ] **Step 1: Test exception attributes**

Add to `TestContentIdeaGenerator` class:

```python
    def test_scene_validation_error_has_attributes(self):
        """SceneValidationError stores scene_id and violations."""
        from modules.pipeline.exceptions import SceneValidationError
        err = SceneValidationError(scene_id=5, violations=["art_style", "environment"])
        assert err.scene_id == 5
        assert err.violations == ["art_style", "environment"]
        assert "Scene 5" in str(err)
        assert "art_style" in str(err)
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_content_idea_generator.py::TestContentIdeaGenerator::test_scene_validation_error_has_attributes -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_content_idea_generator.py
git commit -m "test: add SceneValidationError attribute test"
```

---

### Task 6: Add tests for `_validate_and_fix_scene` retry behavior

**Files:**
- Modify: `tests/test_content_idea_generator.py`

- [ ] **Step 1: Write test — violation triggers retry**

Add after existing tests:

```python
    def test_validate_and_fix_scene_triggers_retry_on_violation(self):
        """When image_prompt is missing constraints, _validate_and_fix_scene retries."""
        import json
        from unittest.mock import MagicMock, patch, call
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import GenerationLLM

        mock_channel = MagicMock()
        mock_channel.name = "Test"
        mock_channel.style = "friendly"
        mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
        mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
        mock_channel.watermark = MagicMock(text="@test")
        mock_channel.image_style = MagicMock(
            lighting="warm", camera="eye-level", art_style="3D render",
            environment="office", composition="professional"
        )

        gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
        gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7",
                                max_tokens=1536, retry_attempts=3, retry_backoff_max=10)

        # First call returns scene missing art_style and environment
        invalid_scene = json.dumps([{
            "id": 1, "script": "Test script", "character": "NamMinh",
            "scene_type": "hook", "delivers": "test",
            "creative_brief": {"visual_concept": "test", "emotion": "friendly",
                              "camera_mood": "close-up", "unique_angle": "desk"},
            "image_prompt": "warm lighting, eye-level camera, professional composition",
            "lipsync_prompt": "NamMinh speaking"
        }])
        # Second call (retry) returns valid scene
        valid_scene = json.dumps([{
            "id": 1, "script": "Test script", "character": "NamMinh",
            "scene_type": "hook", "delivers": "test",
            "creative_brief": {"visual_concept": "test", "emotion": "friendly",
                              "camera_mood": "close-up", "unique_angle": "desk"},
            "image_prompt": "3D render style, office environment, warm lighting, eye-level camera, professional composition",
            "lipsync_prompt": "NamMinh speaking"
        }])

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [invalid_scene, valid_scene]

        with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
            scene_dict = {
                "id": 1, "script": "Test script", "character": "NamMinh",
                "image_prompt": "warm lighting, eye-level camera, professional composition",
                "lipsync_prompt": "NamMinh speaking",
                "creative_brief": {"visual_concept": "test", "emotion": "friendly",
                                  "camera_mood": "close-up", "unique_angle": "desk"}
            }
            result = gen._validate_and_fix_scene(scene_dict, attempt=1)

        assert mock_llm.chat.call_count == 2, f"expected 2 calls (initial + retry), got {mock_llm.chat.call_count}"
        assert result.image_prompt is not None
        # The valid_scene's image_prompt contains "3D render" (art_style) and "office" (environment)
        assert "3D render" in result.image_prompt
        assert "office" in result.image_prompt
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_content_idea_generator.py::TestContentIdeaGenerator::test_validate_and_fix_scene_triggers_retry_on_violation -v --tb=short`
Expected: PASS

- [ ] **Step 3: Write test — valid prompt doesn't retry**

```python
    def test_validate_and_fix_scene_no_retry_when_valid(self):
        """When image_prompt has all constraints, no retry needed."""
        from unittest.mock import MagicMock
        from modules.content.content_idea_generator import ContentIdeaGenerator

        mock_channel = MagicMock()
        mock_channel.name = "Test"
        mock_channel.style = "friendly"
        mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
        mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
        mock_channel.image_style = MagicMock(
            lighting="warm", camera="eye-level", art_style="3D render",
            environment="office", composition="professional"
        )

        gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)

        scene_dict = {
            "id": 1, "script": "Test script", "character": "NamMinh",
            "image_prompt": "3D render style, office environment, warm lighting, eye-level camera, professional composition",
            "lipsync_prompt": "NamMinh speaking",
            "creative_brief": {"visual_concept": "test", "emotion": "friendly",
                              "camera_mood": "close-up", "unique_angle": "desk"}
        }
        # No mock needed — validation should pass without calling LLM
        result = gen._validate_and_fix_scene(scene_dict, attempt=1)
        assert result.image_prompt == scene_dict["image_prompt"]
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_content_idea_generator.py::TestContentIdeaGenerator::test_validate_and_fix_scene_no_retry_when_valid -v --tb=short`
Expected: PASS

- [ ] **Step 5: Write test — max retries raises error**

```python
    def test_validate_and_fix_scene_raises_after_max_attempts(self):
        """After 3 failed attempts, raises SceneValidationError."""
        import json
        from unittest.mock import MagicMock, patch
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.exceptions import SceneValidationError

        mock_channel = MagicMock()
        mock_channel.name = "Test"
        mock_channel.style = "friendly"
        mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
        mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
        mock_channel.image_style = MagicMock(
            lighting="warm", camera="eye-level", art_style="3D render",
            environment="office", composition="professional"
        )

        gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
        gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7",
                                max_tokens=1536, retry_attempts=3, retry_backoff_max=10)

        # LLM always returns invalid prompt
        invalid_scene = json.dumps([{
            "id": 1, "script": "Test script", "character": "NamMinh",
            "creative_brief": {}, "image_prompt": "only lighting",
            "lipsync_prompt": "NamMinh speaking"
        }])

        mock_llm = MagicMock()
        mock_llm.chat.return_value = invalid_scene

        with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
            scene_dict = {"id": 1, "script": "Test", "character": "NamMinh",
                         "image_prompt": "only lighting", "lipsync_prompt": "NamMinh speaking",
                         "creative_brief": {}}
            with pytest.raises(SceneValidationError) as exc_info:
                gen._validate_and_fix_scene(scene_dict, attempt=1)
        assert exc_info.value.scene_id == 1
        assert "art_style" in exc_info.value.violations
        assert "environment" in exc_info.value.violations
```

- [ ] **Step 6: Run test**

Run: `pytest tests/test_content_idea_generator.py::TestContentIdeaGenerator::test_validate_and_fix_scene_raises_after_max_attempts -v --tb=short`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tests/test_content_idea_generator.py
git commit -m "test: add strict image prompt validation retry tests"
```

---

### Task 7: Run full test suite

**Files:**
- None (verification only)

- [ ] **Step 1: Run all content idea generator tests**

Run: `pytest tests/test_content_idea_generator.py -v --tb=short 2>&1 | tail -30`
Expected: All pass

- [ ] **Step 2: Run prompt builder tests**

Run: `pytest tests/test_prompt_builder.py -v --tb=short 2>&1 | tail -20`
Expected: All pass

- [ ] **Step 3: Run scene processor tests (integration check)**

Run: `pytest tests/test_scene_processor.py -v --tb=short 2>&1 | tail -20`
Expected: All pass

---

## Self-Review Checklist

- [ ] `SceneValidationError` added to `exceptions.py` with `scene_id` and `violations` attrs
- [ ] `_build_scene_prompt` updated with strict constraint rules (5 bullet points + rejection warning)
- [ ] JSON example shows actual constraint values (`{img_style.art_style}`, etc.)
- [ ] `_validate_and_fix_scene()` method added with 3-retry logic
- [ ] `_build_retry_prompt()` includes missing constraint names in feedback
- [ ] `_call_llm_for_retry()` uses same LLM provider pattern
- [ ] `_dict_to_scene()` converts validated dict to SceneConfig
- [ ] Image prompt validation wired into `_generate_scenes` after TTS validation
- [ ] No placeholder text (TBD, TODO, etc.)
- [ ] All 7 tasks covered with actual code, not descriptions