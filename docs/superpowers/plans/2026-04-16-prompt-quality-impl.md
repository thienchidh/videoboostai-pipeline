# Prompt Quality — LLM Generates Complete Prompts

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve prompt quality by having the LLM generate complete, ready-to-use `image_prompt` and `lipsync_prompt` strings directly — no assembly, no fallback defaults. `PromptBuilder` becomes a style validator only.

**Architecture:** LLM generates complete `image_prompt` and `lipsync_prompt` strings in one pass. `PromptBuilder` validates generated prompts against channel style constraints. `SceneConfig` gains optional `image_prompt` and `lipsync_prompt` fields. Backward-compatible via simple fallback (`scene.image_prompt or scene.video_prompt or ""`).

**Tech Stack:** Pydantic, existing `ImageStyleConfig`, `ChannelConfig.style`

---

## File Structure

- **Create:** `modules/media/prompt_builder.py` — `PromptBuilder` class (style validator + simple getters)
- **Modify:** `modules/pipeline/models.py` — add `image_prompt`, `lipsync_prompt` to `SceneConfig`
- **Modify:** `modules/content/content_idea_generator.py:179-240,242-257` — update `_build_scene_prompt` + `_parse_scenes`
- **Modify:** `modules/pipeline/scene_processor.py` — use `PromptBuilder` methods
- **Create:** `tests/test_prompt_builder.py` — validation + getter tests

---

### Task 1: Add `image_prompt` and `lipsync_prompt` to `SceneConfig`

**Files:**
- Modify: `modules/pipeline/models.py:393-424` (SceneConfig + from_dict)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prompt_builder.py — new file
def test_scene_config_image_prompt_field():
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=1, script="test", image_prompt="A speaker in office")
    assert scene.image_prompt == "A speaker in office"
    assert scene.lipsync_prompt is None

def test_scene_config_lipsync_prompt_field():
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=2, script="test", lipsync_prompt="NamMinh speaking clearly")
    assert scene.lipsync_prompt == "NamMinh speaking clearly"

def test_scene_config_from_dict_with_prompts():
    from modules.pipeline.models import SceneConfig
    data = {
        "id": 1,
        "script": "Hãy bắt đầu",
        "image_prompt": "A confident speaker in modern office",
        "lipsync_prompt": "Friendly speaker, NamMinh, vi-VN-NamMinhNeural"
    }
    scene = SceneConfig.from_dict(data)
    assert scene.image_prompt == "A confident speaker in modern office"
    assert scene.lipsync_prompt == "Friendly speaker, NamMinh, vi-VN-NamMinhNeural"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prompt_builder.py::test_scene_config_image_prompt_field tests/test_prompt_builder.py::test_scene_config_lipsync_prompt_field tests/test_prompt_builder.py::test_scene_config_from_dict_with_prompts -v`
Expected: FAIL (image_prompt/lipsync_prompt not defined)

- [ ] **Step 3: Modify SceneConfig in models.py**

In `SceneConfig` class (line ~393), add after `background: Optional[str] = None`:

```python
image_prompt: Optional[str] = None  # LLM-generated, ready to use
lipsync_prompt: Optional[str] = None # LLM-generated, ready to use
```

In `from_dict` method (line ~403), add after the existing field mappings:

```python
image_prompt=data.get("image_prompt"),
lipsync_prompt=data.get("lipsync_prompt"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_prompt_builder.py::test_scene_config_image_prompt_field tests/test_prompt_builder.py::test_scene_config_lipsync_prompt_field tests/test_prompt_builder.py::test_scene_config_from_dict_with_prompts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/models.py tests/test_prompt_builder.py
git commit -m "feat(models): add image_prompt and lipsync_prompt to SceneConfig"
```

---

### Task 2: Create `PromptBuilder` as Style Validator

**Files:**
- Create: `modules/media/prompt_builder.py`
- Test: `tests/test_prompt_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
# Continue tests/test_prompt_builder.py

def test_validate_image_prompt_all_constraints_met():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import ImageStyleConfig
    style = ImageStyleConfig(
        lighting="warm",
        camera="eye-level",
        art_style="3D render",
        environment="modern office",
        composition="professional"
    )
    pb = PromptBuilder(channel_style=style)
    prompt = "A professional speaker in modern office with warm lighting, eye-level camera, 3D render style"
    is_valid, violations = pb.validate_image_prompt(prompt)
    assert is_valid is True
    assert violations == []

def test_validate_image_prompt_missing_constraint():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import ImageStyleConfig
    style = ImageStyleConfig(
        lighting="warm",
        camera="eye-level",
        art_style="3D render",
        environment="modern office",
        composition="professional"
    )
    pb = PromptBuilder(channel_style=style)
    # Missing "warm", "eye-level", "modern office", "professional"
    prompt = "Speaker in studio with 3D render style"
    is_valid, violations = pb.validate_image_prompt(prompt)
    assert is_valid is False
    assert "lighting" in violations
    assert "camera" in violations
    assert "art_style" not in violations  # present
    assert "environment" in violations
    assert "composition" in violations

def test_validate_image_prompt_no_style_config():
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder(channel_style=None)
    is_valid, violations = pb.validate_image_prompt("any prompt")
    assert is_valid is True
    assert violations == []

def test_validate_image_prompt_missing():
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder()
    is_valid, violations = pb.validate_image_prompt(None)
    assert is_valid is False
    assert "image_prompt missing" in violations

def test_validate_lipsync_prompt_with_character():
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder()
    prompt = "Friendly speaker, NamMinh, vi-VN-NamMinhNeural, smiling warmly"
    is_valid, violations = pb.validate_lipsync_prompt(prompt, character_name="NamMinh")
    assert is_valid is True
    assert violations == []

def test_validate_lipsync_prompt_missing_character():
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder()
    prompt = "Friendly speaker talking clearly"
    is_valid, violations = pb.validate_lipsync_prompt(prompt, character_name="NamMinh")
    assert is_valid is False
    assert "character_name_missing" in violations

def test_validate_lipsync_prompt_missing():
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder()
    is_valid, violations = pb.validate_lipsync_prompt(None)
    assert is_valid is False
    assert "lipsync_prompt missing" in violations

def test_get_image_prompt_uses_scene_field():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=1, image_prompt="A confident speaker in modern office")
    pb = PromptBuilder()
    assert pb.get_image_prompt(scene) == "A confident speaker in modern office"

def test_get_image_prompt_fallback_to_video_prompt():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=1, video_prompt="A studio background")
    pb = PromptBuilder()
    assert pb.get_image_prompt(scene) == "A studio background"

def test_get_image_prompt_empty_when_both_none():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=1)
    pb = PromptBuilder()
    assert pb.get_image_prompt(scene) == ""

def test_get_lipsync_prompt_uses_scene_field():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=1, lipsync_prompt="NamMinh speaking with warm smile")
    pb = PromptBuilder()
    assert pb.get_lipsync_prompt(scene) == "NamMinh speaking with warm smile"

def test_get_lipsync_prompt_fallback_to_video_prompt():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=1, video_prompt="A person talking")
    pb = PromptBuilder()
    assert pb.get_lipsync_prompt(scene) == "A person talking"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prompt_builder.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write the implementation**

Create `modules/media/prompt_builder.py`:

```python
"""
modules/media/prompt_builder.py — Style validator for generated prompts.

PromptBuilder checks whether image_prompt and lipsync_prompt strings
violate channel style constraints. It does NOT compose prompts.
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from modules.pipeline.models import SceneConfig, ImageStyleConfig


class PromptBuilder:
    """Validate generated prompts against channel style constraints.

    Does NOT assemble prompts — LLM generates complete prompt strings.
    Simple fallback for YAML scenes without generated prompts:
        scene.image_prompt or scene.video_prompt or ""
    """

    def __init__(self, channel_style: Optional["ImageStyleConfig"] = None,
                 brand_tone: Optional[str] = None):
        self.channel_style = channel_style
        self.brand_tone = brand_tone

    def validate_image_prompt(self, image_prompt: Optional[str]) -> tuple[bool, list[str]]:
        """Validate image_prompt against channel style constraints.

        Returns (is_valid, violations):
          - is_valid: True if no violations found
          - violations: list of constraint names NOT found in the prompt
        """
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

    def validate_lipsync_prompt(self, lipsync_prompt: Optional[str],
                                character_name: Optional[str] = None) -> tuple[bool, list[str]]:
        """Validate lipsync_prompt. Returns (is_valid, violations)."""
        if not lipsync_prompt:
            return False, ["lipsync_prompt missing"]
        violations = []
        if character_name and character_name.lower() not in lipsync_prompt.lower():
            violations.append("character_name_missing")
        return len(violations) == 0, violations

    def get_image_prompt(self, scene: "SceneConfig") -> str:
        """Get image prompt: use scene.image_prompt if present, else scene.video_prompt as fallback."""
        return scene.image_prompt or scene.video_prompt or ""

    def get_lipsync_prompt(self, scene: "SceneConfig") -> str:
        """Get lipsync prompt: use scene.lipsync_prompt if present, else scene.video_prompt as fallback."""
        return scene.lipsync_prompt or scene.video_prompt or ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_prompt_builder.py -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add modules/media/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat: add PromptBuilder as style validator for generated prompts"
```

---

### Task 3: Update `content_idea_generator.py` — LLM Generates Complete Prompts

**Files:**
- Modify: `modules/content/content_idea_generator.py:179-240,242-257`

- [ ] **Step 1: Write the failing test**

```python
# Continue tests/test_prompt_builder.py

def test_parse_scenes_includes_image_and_lipsync_prompts():
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import ChannelConfig
    channel_cfg = ChannelConfig.load("nang_suat_thong_minh")
    gen = ContentIdeaGenerator(channel_config=channel_cfg)

    json_text = '''[{
      "id": 1,
      "script": "Hãy bắt đầu với kế hoạch hôm nay",
      "background": "văn phòng hiện đại",
      "character": "NamMinh",
      "image_prompt": "A confident professional speaker in modern office, warm lighting, eye-level camera, 3D render style, professional atmosphere",
      "lipsync_prompt": "Friendly speaker, NamMinh, vi-VN-NamMinhNeural, smiling warmly, gesturing while explaining"
    }]'''
    scenes = gen._parse_scenes(json_text)
    assert len(scenes) == 1
    assert scenes[0]["image_prompt"] == "A confident professional speaker in modern office, warm lighting, eye-level camera, 3D render style, professional atmosphere"
    assert scenes[0]["lipsync_prompt"] == "Friendly speaker, NamMinh, vi-VN-NamMinhNeural, smiling warmly, gesturing while explaining"

def test_validate_scenes_normalizes_image_and_lipsync_prompts():
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import ChannelConfig
    channel_cfg = ChannelConfig.load("nang_suat_thong_minh")
    gen = ContentIdeaGenerator(channel_config=channel_cfg)

    # Scene with None values should normalize to None
    scenes = gen._validate_scenes([{
        "id": 1,
        "script": "Test",
        "character": "NamMinh",
        "image_prompt": None,
        "lipsync_prompt": None
    }])
    assert scenes[0]["image_prompt"] is None
    assert scenes[0]["lipsync_prompt"] is None

    # Scene missing both keys entirely
    scenes = gen._validate_scenes([{
        "id": 2,
        "script": "Test 2",
        "character": "NamMinh"
    }])
    # Missing keys should NOT cause KeyError — normalize to None
    assert scenes[0]["image_prompt"] is None
    assert scenes[0]["lipsync_prompt"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prompt_builder.py::test_parse_scenes_includes_image_and_lipsync_prompts tests/test_prompt_builder.py::test_validate_scenes_normalizes_image_and_lipsync_prompts -v`
Expected: FAIL (image_prompt/lipsync_prompt not parsed)

- [ ] **Step 3: Update `_build_scene_prompt`**

Replace the `_build_scene_prompt` method body (lines 179-240). The key changes:

**Add after `kw_line` and before `tts_context` — character voice context:**
```python
# Build character list with voice context for LLM
char_lines = []
for c in cfg.characters:
    voice_info = getattr(c, 'voice_id', '') or ""
    char_lines.append(f"- {c.name}: {voice_info}")
char_list_str = "\n".join(char_lines)
```

**In the return string, replace the `MỖI SCENE CẦN CÓ` section with:**

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
```

**Example JSON output format in the prompt:**
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

**Also update the end-of-prompt instruction** (the `Trả về CHỉ JSON array...` line) to reference the new fields.

- [ ] **Step 4: Update `_validate_scenes` to normalize image_prompt and lipsync_prompt**

In `_validate_scenes` (around line 342), add at the start of the loop over scenes:

```python
# Normalize: ensure image_prompt and lipsync_prompt are present (or None)
s["image_prompt"] = s.get("image_prompt") or None
s["lipsync_prompt"] = s.get("lipsync_prompt") or None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_prompt_builder.py::test_parse_scenes_includes_image_and_lipsync_prompts tests/test_prompt_builder.py::test_validate_scenes_normalizes_image_and_lipsync_prompts -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add modules/content/content_idea_generator.py tests/test_prompt_builder.py
git commit -m "feat(content): LLM generates complete image_prompt and lipsync_prompt strings"
```

---

### Task 4: Wire `PromptBuilder` into `scene_processor.py`

**Files:**
- Modify: `modules/pipeline/scene_processor.py`

- [ ] **Step 1: Read scene_processor.py to find existing prompt usage**

Run: `grep -n "video_prompt\|get_video_prompt\|image_prompt\|lipsync_prompt\|prompt_builder\|PromptBuilder" modules/pipeline/scene_processor.py`

- [ ] **Step 2: Add PromptBuilder instantiation**

In `SingleCharSceneProcessor.__init__`, add:
```python
from modules.media.prompt_builder import PromptBuilder
self._prompt_builder = PromptBuilder(
    channel_style=getattr(self.ctx.channel, 'image_style', None),
    brand_tone=getattr(self.ctx.channel, 'style', '') or ''
)
```

- [ ] **Step 3: Replace image prompt access**

Find where `img_prompt` or `prompt` is set for image generation. Replace with:
```python
img_prompt = self._prompt_builder.get_image_prompt(scene)
is_valid, violations = self._prompt_builder.validate_image_prompt(img_prompt)
if not is_valid:
    logger.warning(f"  ⚠️ image_prompt violations: {violations}")
```

- [ ] **Step 4: Replace lipsync prompt access**

Find where lipsync prompt is set. Replace with:
```python
char = scene.characters[0] if scene.characters else None
char_name = char.name if (char and hasattr(char, 'name')) else (str(char) if char else None)

lipsync_prompt = self._prompt_builder.get_lipsync_prompt(scene)
is_valid, violations = self._prompt_builder.validate_lipsync_prompt(lipsync_prompt, character_name=char_name)
if not is_valid:
    logger.warning(f"  ⚠️ lipsync_prompt violations: {violations}")
```

- [ ] **Step 5: Run existing scene_processor tests**

Run: `pytest tests/test_scene_processor.py -v --tb=short`
Expected: PASS (all existing tests)

- [ ] **Step 6: Commit**

```bash
git add modules/pipeline/scene_processor.py
git commit -m "feat(scene_processor): use PromptBuilder for prompt access and validation"
```

---

### Task 5: Full test suite

**Files:**
- Test: all existing tests

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: All 302+ tests pass

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "feat: prompt quality pipeline - LLM generates complete prompts, PromptBuilder validates"
```

---

## Self-Review Checklist

- [ ] `SceneConfig.image_prompt` and `lipsync_prompt` fields added (Task 1)
- [ ] `PromptBuilder.validate_image_prompt()` checks all 5 style constraints (Task 2)
- [ ] `PromptBuilder.validate_lipsync_prompt()` checks non-empty + character name (Task 2)
- [ ] `PromptBuilder.get_image_prompt()` uses `scene.image_prompt or scene.video_prompt or ""` (Task 2)
- [ ] `PromptBuilder.get_lipsync_prompt()` uses `scene.lipsync_prompt or scene.video_prompt or ""` (Task 2)
- [ ] LLM system prompt instructs to write complete `image_prompt` and `lipsync_prompt` strings directly (Task 3)
- [ ] `_parse_scenes` + `_validate_scenes` preserve `image_prompt` and `lipsync_prompt` from LLM JSON (Task 3)
- [ ] Character voice context (`name: voice_id`) passed to LLM (Task 3)
- [ ] `scene_processor.py` uses `PromptBuilder` for prompt access + validation (Task 4)
- [ ] Backward compatible: YAML scenes without `image_prompt`/`lipsync_prompt` use `video_prompt` fallback (Task 2, 4)
- [ ] No `SceneMetadata` model added (per spec — removed from design)
- [ ] All 302+ existing tests pass (Task 5)
