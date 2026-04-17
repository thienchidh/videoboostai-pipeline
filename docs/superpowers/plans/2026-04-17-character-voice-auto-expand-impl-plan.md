# Character Voice Auto-Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-create character + voice when LLM generates scenes with character names not in channel config, using explicit gender from LLM to pick correct voice model.

**Architecture:** When LLM outputs a scene with unknown character name + gender, SceneProcessor auto-creates a VoiceConfig + CharacterConfig in-memory with correct TTS model (NamMinhNeural for male, HoaiMyNeural for female). Characters are created per-run only (no config file persistence).

---

## File Map

| File | Change |
|------|--------|
| `modules/pipeline/models.py` | Add `gender` to `SceneCharacter`; update `from_dict` to pass gender |
| `modules/content/content_idea_generator.py` | Add gender to LLM prompt; fix `_validate_scenes` to pass gender in characters list |
| `modules/pipeline/scene_processor.py` | Add `_ensure_character()`, `_default_voice_model()`; update `resolve_voice()` |

---

## Task 1: Add `gender` to `SceneCharacter` model

**Files:**
- Modify: `modules/pipeline/models.py:388-399`

- [ ] **Step 1: Write failing test**

```python
# tests/test_scene_processor.py — add after existing character tests
def test_scene_character_has_gender():
    """SceneCharacter should accept gender field."""
    from modules.pipeline.models import SceneCharacter
    char = SceneCharacter(name="Teacher", gender="male")
    assert char.name == "Teacher"
    assert char.gender == "male"

def test_scene_character_gender_optional():
    """gender defaults to None for backward compat."""
    from modules.pipeline.models import SceneCharacter
    char = SceneCharacter(name="Mentor")
    assert char.gender is None
```

Run: `pytest tests/test_scene_processor.py::test_scene_character_has_gender tests/test_scene_processor.py::test_scene_character_gender_optional -v`
Expected: FAIL — AttributeError: unexpected attribute 'gender'

- [ ] **Step 2: Run test to verify it fails**

```
FAILED — AttributeError: SceneCharacter does not accept gender
```

- [ ] **Step 3: Add gender to SceneCharacter model**

```python
class SceneCharacter(BaseModel):
    """Character trong scene — hỗ trợ cả string (name) và dict với overrides."""
    name: str
    tts: Optional[str] = None
    speed: Optional[float] = None
    gender: Optional[str] = None  # NEW: male|female from LLM

    @classmethod
    def from_yaml(cls, data: "str | dict") -> "SceneCharacter":
        """Parse từ YAML — chấp nhận string (name) hoặc dict."""
        if isinstance(data, str):
            return cls(name=data)
        return cls(**data)  # gender passed via dict if present
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scene_processor.py::test_scene_character_has_gender tests/test_scene_processor.py::test_scene_character_gender_optional -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/models.py
git commit -m "feat(models): add gender field to SceneCharacter"
```

---

## Task 2: Update LLM prompt and `_validate_scenes` to capture and pass gender

**Files:**
- Modify: `modules/content/content_idea_generator.py:296-322` (prompt example)
- Modify: `modules/content/content_idea_generator.py:558-598` (_validate_scenes)

- [ ] **Step 1: Write failing test**

```python
# tests/test_content_idea_generator.py
def test_validate_scenes_captures_gender():
    """_validate_scenes should pass gender through to SceneConfig.characters."""
    from modules.content.content_idea_generator import ContentIdeaGenerator
    gen = ContentIdeaGenerator(project_id=1, channel_config=MagicMock(
        characters=[MagicMock(name="Mentor", voice_id="mentor_female")],
        voices=[]
    ))
    raw_scenes = [
        {"id": 1, "character": "Teacher", "gender": "male", "tts": "Hello"},
    ]
    result = gen._validate_scenes(raw_scenes)
    assert len(result) == 1
    assert result[0].characters[0].name == "Teacher"
    assert result[0].characters[0].gender == "male"  # NEW
```

Run: `pytest tests/test_content_idea_generator.py::test_validate_scenes_captures_gender -v`
Expected: FAIL — gender not in SceneCharacter

- [ ] **Step 2: Run test to verify it fails**

```
AssertionError: assert None == 'male'
```

- [ ] **Step 3: Fix _validate_scenes to pass gender in characters list**

In `_validate_scenes`, replace the line `scene["character"] = char` with this logic that sets `characters` (list) instead:

```python
        # Build characters list with gender preserved for SceneConfig.from_dict
        char_gender = scene.get("gender")  # from LLM output
        scene["characters"] = [{"name": char, "gender": char_gender}]
        # Remove singular 'character' key to avoid confusion
        scene.pop("character", None)
```

Also update the `scene["character"] = char` line that appears earlier in the loop — it should be removed since we now set `characters` instead.

The relevant section of `_validate_scenes` (around lines 575-596):

```python
        validated = []
        for scene in scenes:
            # Normalize: extract first from 'characters' array, or use 'character' string
            char = scene.get("character") or scene.get("characters")
            original_chars = char if isinstance(char, list) else None
            if isinstance(char, list):
                if len(char) > 1:
                    logger.warning(
                        f"Scene {scene.get('id', 0)} has {len(char)} characters "
                        f"({char}), expected 1. Using first: {char[0]}"
                    )
                char = char[0] if char else default_char
            elif not isinstance(char, str) or not char:
                char = default_char

            # Capture gender from LLM output (NEW)
            char_gender = scene.get("gender")
            # Set 'characters' list format that SceneConfig.from_dict expects
            scene["characters"] = [{"name": char, "gender": char_gender}]
            # Remove singular 'character' key to avoid confusion in from_dict
            scene.pop("character", None)

            # Normalize: ensure image_prompt and lipsync_prompt are present (or None)
            scene["image_prompt"] = scene.get("image_prompt") or None
            scene["lipsync_prompt"] = scene.get("lipsync_prompt") or None
            scene["creative_brief"] = scene.get("creative_brief") or None
            validated.append(scene)

        return [SceneConfig.from_dict(s) for s in validated]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_idea_generator.py::test_validate_scenes_captures_gender -v`
Expected: PASS

- [ ] **Step 5: Update LLM prompt to require gender**

In `_build_scene_prompt()` around line 296, update the JSON example:

```python
      "image_prompt": "3D Pixar Disney style, [visual_concept], [emotion], warm lighting, eye-level camera, professional composition",
      "lipsync_prompt": "...",
      "gender": "female"   # NEW — must be "male" or "female"
    },
```

And in the prompt instructions (around line 278), add:

```
- MỖI SCENE phải có `gender` field: "male" hoặc "female" (bắt buộc)
```

- [ ] **Step 6: Commit**

```bash
git add modules/content/content_idea_generator.py
git commit -m "feat(content_idea_generator): add gender to LLM prompt and _validate_scenes"
```

---

## Task 3: Add `_ensure_character()` and `_default_voice_model()` to SceneProcessor

**Files:**
- Modify: `modules/pipeline/scene_processor.py:57-100`

- [ ] **Step 1: Write failing test**

```python
# tests/test_scene_processor.py
def test_ensure_character_creates_voice_and_character():
    """_ensure_character should create VoiceConfig and CharacterConfig when character doesn't exist."""
    from unittest.mock import MagicMock, patch
    from modules.pipeline.scene_processor import SceneProcessor
    from modules.pipeline.config import PipelineContext

    ctx = MagicMock(spec=PipelineContext)
    ctx.channel.characters = []  # empty — character doesn't exist
    ctx.channel.voices = []
    ctx.channel.generation = MagicMock()
    ctx.channel.generation.models.tts = "edge"

    processor = SceneProcessor.__new__(SceneProcessor)
    processor.ctx = ctx

    processor._ensure_character("Teacher", "male")

    # Should have created one voice and one character
    assert len(ctx.channel.voices) == 1
    assert len(ctx.channel.characters) == 1
    assert ctx.channel.voices[0].gender == "male"
    assert ctx.channel.voices[0].providers[0].model == "vi-VN-NamMinhNeural"
    assert ctx.channel.characters[0].name == "Teacher"

def test_ensure_character_idempotent():
    """Calling _ensure_character twice with same name should not duplicate."""
    from unittest.mock import MagicMock
    from modules.pipeline.scene_processor import SceneProcessor
    from modules.pipeline.config import PipelineContext

    existing_char = MagicMock()
    existing_char.name = "Teacher"
    existing_char.voice_id = "existing_voice"

    ctx = MagicMock(spec=PipelineContext)
    ctx.channel.characters = [existing_char]
    ctx.channel.voices = []

    processor = SceneProcessor.__new__(SceneProcessor)
    processor.ctx = ctx

    processor._ensure_character("Teacher", "male")

    # Should not add anything since Teacher already exists
    assert len(ctx.channel.voices) == 0
    assert len(ctx.channel.characters) == 1  # original only
```

Run: `pytest tests/test_scene_processor.py::test_ensure_character_creates_voice_and_character tests/test_scene_processor.py::test_ensure_character_idempotent -v`
Expected: FAIL — method doesn't exist

- [ ] **Step 2: Run test to verify it fails**

```
AttributeError: 'SceneProcessor' object has no attribute '_ensure_character'
```

- [ ] **Step 3: Add _ensure_character and _default_voice_model methods**

Add these methods to `SceneProcessor` class in `scene_processor.py`, after `get_voice()` (around line 70):

```python
    def _default_voice_model(self, gender: str) -> str:
        """Return appropriate Edge TTS model for gender."""
        if gender == "male":
            return "vi-VN-NamMinhNeural"
        return "vi-VN-HoaiMyNeural"  # female as default

    def _ensure_character(self, char_name: str, gender: str):
        """Create CharacterConfig + VoiceConfig if character doesn't exist in channel.

        Args:
            char_name: Name from LLM output (e.g., "Teacher", "Expert")
            gender: "male" or "female" from LLM output
        """
        # Check if character already exists (idempotent)
        existing = self.get_character(char_name)
        if existing:
            return

        # Create safe voice_id from char_name
        voice_id = f"auto_{char_name.lower().replace(' ', '_')}"

        # Determine TTS model based on gender
        model = self._default_voice_model(gender)

        from modules.pipeline.models import VoiceConfig, VoiceProvider, CharacterConfig

        voice = VoiceConfig(
            id=voice_id,
            name=char_name,
            gender=gender,
            providers=[VoiceProvider(provider="edge", model=model, speed=1.0)],
        )
        char = CharacterConfig(name=char_name, voice_id=voice_id)

        self.ctx.channel.voices.append(voice)
        self.ctx.channel.characters.append(char)
        logger.info(f"Auto-created character '{char_name}' (gender={gender}, voice_id={voice_id})")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scene_processor.py::test_ensure_character_creates_voice_and_character tests/test_scene_processor.py::test_ensure_character_idempotent -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/scene_processor.py
git commit -m "feat(scene_processor): add _ensure_character and _default_voice_model"
```

---

## Task 4: Update `resolve_voice()` to use auto-creation

**Files:**
- Modify: `modules/pipeline/scene_processor.py:72-100`

- [ ] **Step 1: Write failing test**

```python
# tests/test_scene_processor.py
def test_resolve_voice_auto_creates_unknown_character_with_gender():
    """resolve_voice should auto-create character when name unknown but gender is provided."""
    from unittest.mock import MagicMock
    from modules.pipeline.scene_processor import SceneProcessor
    from modules.pipeline.config import PipelineContext
    from modules.pipeline.models import SceneConfig, SceneCharacter

    ctx = MagicMock(spec=PipelineContext)
    ctx.channel.characters = []  # Teacher doesn't exist
    ctx.channel.voices = []
    ctx.channel.generation = MagicMock()
    ctx.channel.generation.models.tts = "edge"

    processor = SceneProcessor.__new__(SceneProcessor)
    processor.ctx = ctx

    # Scene with Teacher character and male gender
    scene_char = SceneCharacter(name="Teacher", voice_id="auto_teacher", gender="male")
    scene = SceneConfig(id=1, characters=[scene_char], tts="Hello")

    provider, model, speed, gender = processor.resolve_voice(scene_char, scene)

    assert provider == "edge"
    assert model == "vi-VN-NamMinhNeural"  # male model
    assert gender == "male"
    # Character should be auto-created
    assert len(ctx.channel.characters) == 1
    assert len(ctx.channel.voices) == 1
```

Run: `pytest tests/test_scene_processor.py::test_resolve_voice_auto_creates_unknown_character_with_gender -v`
Expected: FAIL — auto-creation not integrated yet

- [ ] **Step 2: Run test to verify it fails**

```
AssertionError: assert 'female_voice' == 'vi-VN-NamMinhNeural'
```

- [ ] **Step 3: Update resolve_voice to call _ensure_character**

Replace the `resolve_voice` method (lines 72-100):

```python
    def resolve_voice(self, character, scene: SceneConfig) -> Tuple[str, str, float, str]:
        """Resolve (provider, model, speed, gender) from voice_id or fallback to channel config.

        Returns:
            (provider_name, model_name, speed, gender)
        """
        voice_id = character.voice_id
        voice = self.get_voice(voice_id) if voice_id else None

        if voice and voice.providers:
            primary = voice.providers[0]
            return (
                primary.provider,
                primary.model,
                primary.speed,
                voice.gender or "female",
            )

        # Character's voice_id not found in voice catalog
        # Try auto-creation if gender is available from scene
        char_name = character.name
        gender = getattr(character, 'gender', None) if character else None

        if gender in ("male", "female"):
            self._ensure_character(char_name, gender)
            # Retry lookup with auto-generated voice_id
            auto_voice_id = f"auto_{char_name.lower().replace(' ', '_')}"
            voice = self.get_voice(auto_voice_id)
            if voice and voice.providers:
                primary = voice.providers[0]
                return (primary.provider, primary.model, primary.speed, gender)

        # Final fallback: use channel config's generation.models.tts as provider
        fallback_provider = self.ctx.channel.generation.models.tts if self.ctx.channel.generation else None
        # Fallback: use first voice from catalog as voice_id
        fallback_voice_id = "female_voice"
        voices = self.ctx.channel.voices or []
        if voices:
            fallback_voice_id = voices[0].id
        return fallback_provider or "edge", fallback_voice_id, 1.0, "female"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scene_processor.py::test_resolve_voice_auto_creates_unknown_character_with_gender -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/scene_processor.py
git commit -m "feat(scene_processor): integrate _ensure_character into resolve_voice"
```

---

## Task 5: Run full test suite

- [ ] **Step 1: Run all related tests**

```bash
pytest tests/test_scene_processor.py tests/test_content_idea_generator.py -v --tb=short 2>&1 | tail -40
```

Expected: All tests pass

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "feat: character voice auto-expansion — auto-create characters with correct gender from LLM

Automatically creates VoiceConfig + CharacterConfig when LLM outputs
character names not in channel config. Gender from LLM determines which
Edge TTS model to use (NamMinhNeural=male, HoaiMyNeural=female).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Verification Checklist

- [ ] `SceneCharacter.gender` exists and defaults to None
- [ ] `_validate_scenes` passes gender through to `SceneConfig.characters[0].gender`
- [ ] `_ensure_character("Teacher", "male")` creates voice with `vi-VN-NamMinhNeural`
- [ ] `_ensure_character("Teacher", "female")` creates voice with `vi-VN-HoaiMyNeural`
- [ ] `_ensure_character("Teacher", ...)` called twice does not duplicate
- [ ] `resolve_voice` with unknown character but gender="male" returns male model
- [ ] `resolve_voice` with unknown character and no gender falls back to female
- [ ] All existing tests still pass
