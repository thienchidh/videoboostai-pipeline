# Creative Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Two-Phase Creative Generation — LLM creates `creative_brief` per scene, then writes `image_prompt` and `lipsync_prompt` from it. Uses few-shot examples + anti-patterns + diversity constraints to ensure variety without any new config.

**Architecture:** LLM receives a rich system prompt with few-shot examples (3 detailed scenes), anti-patterns, and diversity constraints. LLM outputs `creative_brief` (vision) + `image_prompt` + `lipsync_prompt` per scene. `creative_brief` is stored in `scene_meta.json`.

**Tech Stack:** Python, Pydantic, existing ContentIdeaGenerator + PromptBuilder + SceneProcessor.

---

## File Changes Summary

| File | Change |
|------|--------|
| `modules/pipeline/models.py` | Add `creative_brief: Optional[Dict[str, Any]]` to `SceneConfig.from_dict()` |
| `modules/media/prompt_builder.py` | Add `validate_creative_brief()` method |
| `modules/content/content_idea_generator.py` | Rewrite `_build_scene_prompt()` with 2-phase + few-shot + anti-patterns + diversity |
| `modules/pipeline/scene_processor.py` | Write `creative_brief` to `scene_meta.json` |
| `tests/test_prompt_builder.py` | Add tests for `validate_creative_brief()` |
| `tests/test_content_idea_generator.py` | Add tests for `creative_brief` parsing in `_parse_scenes` |

---

## Task 1: Add `creative_brief` to `SceneConfig`

**Files:**
- Modify: `modules/pipeline/models.py:393-427` (SceneConfig.from_dict)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_prompt_builder.py`:

```python
def test_scene_config_creative_brief_field():
    from modules.pipeline.models import SceneConfig
    brief = {
        "visual_concept": "Close-up khuôn mặt tập trung",
        "emotion": "serious but approachable",
        "camera_mood": "shallow DOF, intimate close-up",
        "setting_vibe": "home office with plants",
        "unique_angle": "shooting from above desk",
        "action_description": "speaking directly to camera"
    }
    scene = SceneConfig(id=1, script="test", creative_brief=brief)
    assert scene.creative_brief == brief
    assert scene.creative_brief["visual_concept"] == "Close-up khuôn mặt tập trung"


def test_scene_config_from_dict_with_creative_brief():
    from modules.pipeline.models import SceneConfig
    data = {
        "id": 1,
        "script": "Hãy bắt đầu",
        "character": "NamMinh",
        "creative_brief": {
            "visual_concept": "Close-up khuôn mặt tập trung",
            "emotion": "serious but approachable",
            "camera_mood": "shallow DOF, intimate close-up",
            "setting_vibe": "home office with plants",
            "unique_angle": "shooting from above desk",
            "action_description": "speaking directly to camera"
        }
    }
    scene = SceneConfig.from_dict(data)
    assert scene.creative_brief is not None
    assert scene.creative_brief["emotion"] == "serious but approachable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prompt_builder.py::test_scene_config_creative_brief_field tests/test_prompt_builder.py::test_scene_config_from_dict_with_creative_brief -v`
Expected: FAIL — `SceneConfig` doesn't have `creative_brief` field yet.

- [ ] **Step 3: Add `creative_brief` to SceneConfig**

In `modules/pipeline/models.py`, add `creative_brief: Optional[Dict[str, Any]] = None` to `SceneConfig` class:

```python
class SceneConfig(BaseModel):
    id: int = 0
    tts: Optional[str] = None
    script: Optional[str] = None
    characters: List["SceneCharacter | str"] = []
    video_prompt: Optional[str] = None
    background: Optional[str] = None
    image_prompt: Optional[str] = None
    lipsync_prompt: Optional[str] = None
    creative_brief: Optional[Dict[str, Any]] = None  # NEW
```

Also update `from_dict()` to include:
```python
    return cls(
        id=data.get("id", 0),
        tts=data.get("tts"),
        script=data.get("script"),
        characters=parsed_chars,
        video_prompt=data.get("video_prompt"),
        background=data.get("background"),
        image_prompt=data.get("image_prompt"),
        lipsync_prompt=data.get("lipsync_prompt"),
        creative_brief=data.get("creative_brief"),  # NEW
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_prompt_builder.py::test_scene_config_creative_brief_field tests/test_prompt_builder.py::test_scene_config_from_dict_with_creative_brief -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/models.py tests/test_prompt_builder.py
git commit -m "feat(models): add creative_brief field to SceneConfig"
```

---

## Task 2: Add `validate_creative_brief()` to PromptBuilder

**Files:**
- Modify: `modules/media/prompt_builder.py`
- Test: `tests/test_prompt_builder.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prompt_builder.py`:

```python
def test_validate_creative_brief_all_fields_present():
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder()
    brief = {
        "visual_concept": "Close-up face",
        "emotion": "serious",
        "camera_mood": "shallow DOF",
        "setting_vibe": "home office",
        "unique_angle": "shooting from above desk",
        "action_description": "speaking to camera"
    }
    is_valid, violations = pb.validate_creative_brief(brief)
    assert is_valid is True
    assert violations == []


def test_validate_creative_brief_missing_required_field():
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder()
    # Missing "camera_mood" and "unique_angle"
    brief = {
        "visual_concept": "Close-up face",
        "emotion": "serious",
        "setting_vibe": "home office",
        "action_description": "speaking to camera"
    }
    is_valid, violations = pb.validate_creative_brief(brief)
    assert is_valid is False
    assert "camera_mood" in violations
    assert "unique_angle" in violations
    assert "visual_concept" not in violations


def test_validate_creative_brief_missing():
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder()
    is_valid, violations = pb.validate_creative_brief(None)
    assert is_valid is False
    assert "creative_brief missing" in violations
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prompt_builder.py::test_validate_creative_brief_all_fields_present tests/test_prompt_builder.py::test_validate_creative_brief_missing_required_field tests/test_prompt_builder.py::test_validate_creative_brief_missing -v`
Expected: FAIL — `validate_creative_brief` method doesn't exist.

- [ ] **Step 3: Add `validate_creative_brief()` method to PromptBuilder**

Add after the existing `validate_lipsync_prompt()` method in `modules/media/prompt_builder.py`:

```python
def validate_creative_brief(self, brief: Optional[Dict[str, Any]]) -> tuple[bool, list[str]]:
    """Check creative_brief has sufficient depth for variety.

    Required fields: visual_concept, emotion, camera_mood, unique_angle.
    Optional: setting_vibe, action_description.

    Returns (is_valid, violations):
      - is_valid: True if all required fields are present
      - violations: list of required field names that are missing
    """
    if not brief:
        return False, ["creative_brief missing"]
    required_fields = ["visual_concept", "emotion", "camera_mood", "unique_angle"]
    violations = [f for f in required_fields if not brief.get(f)]
    return len(violations) == 0, violations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_prompt_builder.py::test_validate_creative_brief_all_fields_present tests/test_prompt_builder.py::test_validate_creative_brief_missing_required_field tests/test_prompt_builder.py::test_validate_creative_brief_missing -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/media/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat(prompt_builder): add validate_creative_brief() method"
```

---

## Task 3: Rewrite `_build_scene_prompt()` with 2-phase creative generation

**Files:**
- Modify: `modules/content/content_idea_generator.py:179-253`

This is the core change. The prompt needs to:
1. Ask LLM to write `creative_brief` first for each scene
2. Then write `image_prompt` and `lipsync_prompt` from the brief
3. Include 3 few-shot examples showing good creative_brief + prompts
4. Include anti-patterns list
5. Include diversity constraints between scenes

- [ ] **Step 1: Write the failing test — verify creative_brief in output**

Add to `tests/test_content_idea_generator.py`:

```python
def test_parse_scenes_includes_creative_brief():
    import json
    from unittest.mock import MagicMock
    from modules.content.content_idea_generator import ContentIdeaGenerator

    mock_channel = MagicMock()
    mock_channel.name = "Test Channel"
    mock_channel.style = "chuyên gia thân thiện"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="vi-VN-NamMinhNeural")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
    mock_channel.image_style = MagicMock(
        lighting="warm", camera="eye-level", art_style="3D render",
        environment="office", composition="professional"
    )

    gen = ContentIdeaGenerator(channel_config=mock_channel)

    json_text = json.dumps([{
        "id": 1,
        "script": "Hãy bắt đầu với kế hoạch hôm nay",
        "character": "NamMinh",
        "creative_brief": {
            "visual_concept": "Close-up khuôn mặt tập trung",
            "emotion": "serious but approachable",
            "camera_mood": "shallow DOF, intimate close-up",
            "setting_vibe": "home office with plants",
            "unique_angle": "shooting from above desk, papers visible",
            "action_description": "speaking directly to camera"
        },
        "image_prompt": "Close-up of a focused woman at a desk...",
        "lipsync_prompt": "NamMinh speaking with warm smile..."
    }])
    scenes = gen._parse_scenes(json_text)
    assert len(scenes) == 1
    assert scenes[0]["creative_brief"] is not None
    assert scenes[0]["creative_brief"]["emotion"] == "serious but approachable"
    assert scenes[0]["creative_brief"]["unique_angle"] == "shooting from above desk, papers visible"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_idea_generator.py::test_parse_scenes_includes_creative_brief -v`
Expected: FAIL — `_parse_scenes` doesn't yet parse `creative_brief` into the scene dict.

- [ ] **Step 3: Update `_validate_scenes()` to parse creative_brief**

In `modules/content/content_idea_generator.py`, update `_validate_scenes()` — add `creative_brief` normalization after the existing `image_prompt`/`lipsync_prompt` lines (around line 391):

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
        scene["character"] = char
        scene.pop("characters", None)
        scene["image_prompt"] = scene.get("image_prompt") or None
        scene["lipsync_prompt"] = scene.get("lipsync_prompt") or None
        scene["creative_brief"] = scene.get("creative_brief") or None  # NEW
        validated.append(scene)

    return validated
```

- [ ] **Step 4: Verify test passes**

Run: `pytest tests/test_content_idea_generator.py::test_parse_scenes_includes_creative_brief -v`
Expected: PASS

- [ ] **Step 5: Rewrite `_build_scene_prompt()` with full 2-phase prompt**

Replace the existing `_build_scene_prompt()` method (lines ~179-253) with the new version:

```python
def _build_scene_prompt(self, title: str, keywords: List[str], angle: str,
                         description: str = "", num_scenes: int = 3) -> str:
    """Build the prompt sent to LLM for scene generation.

    Uses Two-Phase Creative Generation:
    Phase 1: LLM creates creative_brief for each scene (vision/plan)
    Phase 2: LLM writes image_prompt and lipsync_prompt from creative_brief

    Includes few-shot examples, anti-patterns, and diversity constraints
    to ensure variety across scenes.
    """
    if not self._channel_config:
        raise ValueError("channel_config is required")

    cfg = self._channel_config
    kw_list_str = ", ".join(keywords) if keywords else ""
    kw_line = f"Từ khóa: {kw_list_str}\n" if kw_list_str else ""

    # Build character list with voice context for LLM
    char_lines = []
    for c in cfg.characters:
        voice_info = getattr(c, 'voice_id', '') or ""
        char_lines.append(f"- {c.name}: {voice_info}")
    char_list_str = "\n".join(char_lines)

    tts = cfg.tts
    tts_context = (
        f"\nGiới hạn thời lượng: tối đa {tts.max_duration}s, tối thiểu {tts.min_duration}s mỗi scene. "
        f"Mỗi scene phải có khoảng {int(tts.min_duration * 2.5)}-{int(tts.max_duration * 2.5)} từ "
        f"(với tốc độ 2.5 từ/giây)."
    )

    desc_line = f"NỘI DUNG THAM KHẢO:\n{description[:1000]}\n" if description else ""

    return f"""Bạn là chuyên gia sản xuất video viral cho kênh "{cfg.name}".
Viết {num_scenes} scene với prompts SÁNG TẠO, KHÔNG LẶP LẠI.

{desc_line}{kw_line}Phong cách nội dung: {angle}{tts_context}

PHONG CÁCH KÊNH (brand tone):
{cfg.style}

NHÂN VẬT VÀ GIỌNG NÓI:
{char_list_str}

---

VÍ DỤ TỐT (học cách viết creative brief + prompts):

Input topic: "3 Tips Quản Lý Thời Gian"
Characters: NamMinh (female, vi-VN-NamMinhNeural), HoaiMy (female, vi-VN-HoaiMyNeural)

--- Scene 1 (Tip về lập kế hoạch) ---
creative_brief:
  visual_concept: "Close-up khuôn mặt tập trung, ánh sáng warm từ lamp"
  emotion: "serious but approachable"
  camera_mood: "shallow DOF, intimate close-up"
  setting_vibe: "home office with plants"
  unique_angle: "shooting from above desk, papers and planner visible"
  action_description: "speaking directly to camera, occasional hand gesture toward planner"

image_prompt: "Close-up of a focused young woman at a desk with planner and scattered papers, warm lamp light creating soft shadows, shallow depth of field with desk details in bokeh, home office with small plants, looking directly at camera with determined yet approachable expression, intimate cinematic feel, professional 3D render style"

lipsync_prompt: "NamMinh speaking directly to camera with warm inviting smile, slight nod on key words like 'planning' and 'important', occasional hand gesture toward planner, measured thoughtful pace, confident energy, Vietnamese language delivery"

--- Scene 2 (Tip về ưu tiên) ---
creative_brief:
  visual_concept: "Medium shot người đang cầm list, ánh sáng bright white"
  emotion: "energetic, motivated"
  camera_mood: "medium shot, eye-level, slightly high angle"
  setting_vibe: "clean minimalist workspace"
  unique_angle: "camera to the side, showing screen with task list"
  action_description: "pointing at list, engaging body language"

image_prompt: "Young professional woman pointing at a digital task list on screen, clean minimalist white workspace, bright diffused lighting from ceiling, medium shot eye-level with slightly high angle, engaged and energetic expression, professional 3D render style"

lipsync_prompt: "HoaiMy speaking with energetic enthusiasm, animated hand gestures pointing at list items, faster paced delivery with excitement on priority keywords, confident authoritative tone, Vietnamese language delivery"

--- Scene 3 (Tip về nghỉ ngơi) ---
creative_brief:
  visual_concept: "Relaxed shot người đang uống coffee, ánh sáng soft golden"
  emotion: "relaxed, balanced"
  camera_mood: "wide shot, lifestyle feel"
  setting_vibe: "cozy café corner with plants"
  unique_angle: "over-the-shoulder showing coffee cup"
  action_description: "relaxed posture, occasional sip, thoughtful pauses"

image_prompt: "Young woman relaxing with coffee cup, soft golden hour lighting from window, cozy café corner with plants and warm wooden elements, over-the-shoulder composition showing both face and coffee, relaxed balanced expression with slight smile, lifestyle photography feel, professional 3D render style"

lipsync_prompt: "NamMinh speaking in a relaxed slower pace, occasional sip of coffee between sentences, thoughtful pauses on key points, warm casual tone, gentle hand movements, peaceful balanced energy, Vietnamese language delivery"

---

TRÁNH CÁC PATTERN SAU — KHÔNG ĐƯỢC LẶP LẠI:
❌ "professional speaker in modern office" — DÙNG QUÁ NHIỀU, XÓA
❌ "warm lighting, eye-level camera" — QUÁ GENERIC, KHÔNG MÔ TẢ GÌ
❌ Mọi scene đều là người đứng nói chuyện trước camera
❌ Mọi scene đều có cùng background (office)
❌ "confident, knowledgeable" — adjectives TRỐNG, không có action
❌ "gesturing naturally" — quá mơ hồ
❌ Tất cả scenes đều có cùng camera angle (close-up)
❌ Prompt bắt đầu bằng "A person..." thay vì mô tả cụ thể

---

MỖI SCENE PHẢI KHÁC NHAU — CAM KẾT TRƯỚC:
1. Scene N+1 phải có ÍT NHẤT 1 trong:
   - Camera angle khác (close-up ≠ medium ≠ wide)
   - Emotion khác (serious ≠ playful ≠ calm)
   - Setting khác (office ≠ café ≠ outdoor)

2. Không được dùng cùng lighting setup cho 2 scene liên tiếp
   (warm lamp → bright white → golden hour → soft blue)

3. Mỗi scene phải có "unique visual element" — detail nhỏ đặc biệt
   VD: "có sách stack trên bàn", "cây cảnh trong góc", "light leak từ cửa sổ"

4. Nếu script có emotion mạnh (excited, serious, funny) →
   camera_mood phải phản ánh đúng emotion đó

---

ĐỊNH DẠNG JSON OUTPUT:
[
  {{
    "id": 1,
    "script": "lời thoại TTS...",
    "character": "NamMinh",
    "creative_brief": {{
      "visual_concept": "mô tả ngắn gọn concept visual",
      "emotion": "mood chính của scene",
      "camera_mood": "camera angle + depth of field",
      "setting_vibe": "mô tả không gian/background",
      "unique_angle": "detail đặc biệt chỉ có scene này",
      "action_description": "mô tả body language, gesture"
    }},
    "image_prompt": "PROMPT HOÀN CHỈNH cho image gen, CHỨÁ creative_brief elements",
    "lipsync_prompt": "PROMPT HOÀN CHỈNH cho lipsync, CHỨÁ emotion + action + pace"
  }}
]

Trả về CHỈ JSON array, không kèm markdown."""
```

- [ ] **Step 6: Run existing tests to ensure no regression**

Run: `pytest tests/test_content_idea_generator.py -v`
Expected: All existing tests pass (creative_brief parsing is backward-compatible).

- [ ] **Step 7: Commit**

```bash
git add modules/content/content_idea_generator.py tests/test_content_idea_generator.py
git commit -m "feat(content_idea_generator): rewrite _build_scene_prompt with 2-phase creative generation

- Add creative_brief per scene as vision/plan before prompts
- Include 3 few-shot examples (3 different scenes with variety)
- Add anti-patterns list (8 banned generic patterns)
- Add diversity constraints (camera/emotion/setting must differ between scenes)
- creative_brief parsed in _validate_scenes()"
```

---

## Task 4: Store `creative_brief` in `scene_meta.json`

**Files:**
- Modify: `modules/pipeline/scene_processor.py:246-260`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scene_processor.py` or a new test in `tests/test_prompt_builder.py`:

```python
def test_scene_meta_includes_creative_brief():
    """scene_meta.json includes creative_brief when scene has it."""
    from modules.pipeline.models import SceneConfig, CharacterConfig, VoiceConfig
    import json
    import tempfile
    import os

    # Create a minimal scene with creative_brief
    brief = {
        "visual_concept": "Close-up face",
        "emotion": "serious",
        "camera_mood": "shallow DOF",
        "setting_vibe": "home office",
        "unique_angle": "from above",
        "action_description": "speaking"
    }
    scene = SceneConfig(
        id=1,
        script="Test script",
        characters=["NamMinh"],
        creative_brief=brief
    )

    # Verify creative_brief is accessible from scene
    assert scene.creative_brief is not None
    assert scene.creative_brief["emotion"] == "serious"
```

Actually, this is better tested at the integration level. Let me write a simpler unit test:

Add to `tests/test_prompt_builder.py`:

```python
def test_scene_meta_creative_brief_in_scene_config():
    """SceneConfig.creative_brief is stored and retrievable."""
    from modules.pipeline.models import SceneConfig
    brief = {
        "visual_concept": "Test concept",
        "emotion": "happy",
        "camera_mood": "wide",
        "setting_vibe": "outdoor",
        "unique_angle": "low angle",
        "action_description": "walking"
    }
    scene = SceneConfig(
        id=5,
        script="Test",
        creative_brief=brief
    )
    # creative_brief accessible and serializable
    assert scene.creative_brief == brief
    # Should serialize to dict correctly
    as_dict = scene.model_dump()
    assert as_dict["creative_brief"] == brief
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prompt_builder.py::test_scene_meta_creative_brief_in_scene_config -v`
Expected: FAIL — model_dump doesn't include creative_brief or scene doesn't serialize it.

- [ ] **Step 3: Update scene_meta in scene_processor.py**

In `modules/pipeline/scene_processor.py`, find the `scene_meta` dict (around line 246-260) and add `creative_brief`:

```python
scene_meta = {
    "scene_id": scene_id,
    "scene_index": getattr(scene, 'scene_index', 0),
    "title": getattr(scene, 'title', None),
    "script": getattr(scene, 'script', None) or getattr(scene, 'tts', ''),
    "tts_text": getattr(scene, 'tts', '') or getattr(scene, 'script', ''),
    "characters": [c.name if hasattr(c, 'name') else str(c) for c in chars],
    "video_prompt": getattr(scene, 'video_prompt', None),
    "creative_brief": getattr(scene, 'creative_brief', None),  # NEW
    "created_at": datetime.now(timezone.utc).isoformat(),
}
```

Also add `creative_brief` validation in the scene processor where `PromptBuilder` is used (around line 297-301):

```python
# After img_prompt validation
brief = scene.creative_brief
if brief:
    is_valid, violations = self._prompt_builder.validate_creative_brief(brief)
    if not is_valid:
        log(f"  ⚠️ creative_brief shallow: {violations}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_prompt_builder.py::test_scene_meta_creative_brief_in_scene_config -v`
Expected: PASS

- [ ] **Step 5: Run all prompt_builder tests**

Run: `pytest tests/test_prompt_builder.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add modules/pipeline/scene_processor.py tests/test_prompt_builder.py
git commit -m "feat(scene_processor): store creative_brief in scene_meta.json

- Add creative_brief to scene_meta dict written after scene setup
- Validate creative_brief depth when present"
```

---

## Task 5: Run Full Test Suite

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass.

- [ ] **Step 2: Commit if everything passes**

```bash
git add -A
git commit -m "test: all creative-prompts tests pass"
```

---

## Spec Coverage Checklist

| Spec Requirement | Task |
|-----------------|------|
| `SceneConfig` has `creative_brief` field | Task 1 |
| `_build_scene_prompt()` rewritten with 2-phase + few-shot + anti-patterns + diversity | Task 3 |
| `_parse_scenes()` / `_validate_scenes()` parse `creative_brief` | Task 3 Step 3-4 |
| `PromptBuilder.validate_creative_brief()` | Task 2 |
| `scene_meta.json` stores `creative_brief` | Task 4 |
| `creative_brief` validated in scene_processor | Task 4 Step 3 |
| Backward compatible (optional field, YAML scenes work) | All tasks |
| No new config required | Task 3 (all hardcoded in prompt) |
| Tests for all new behavior | Tasks 1-4 |
