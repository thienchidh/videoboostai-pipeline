# Strict Image Prompt Validation with Retry — Design

**Date:** 2026-04-17
**Status:** Approved

## Problem

The LLM generates `image_prompt` fields that violate channel style constraints (`art_style`, `environment`, etc.) because the constraints aren't embedded forcefully enough in the scene generation prompt. Current advisory logging (warnings) doesn't prevent invalid prompts from being used.

## Solution

Post-generation validation with retry + strict enforcement. If `image_prompt` is missing any constraint keyword after generation, regenerate the full scene with explicit feedback. After max retries, block the pipeline.

---

## 1. Prompt Redesign — `_build_scene_prompt`

**Location:** `modules/content/content_idea_generator.py`

### Add strict constraint rules

After the existing IMAGE STYLE CONSTRAINTS section, add:

```
QUY TẮC NGHIÊM NGẶT — image_prompt PHẢI CHỨA ĐỦ:
- "{img_style.art_style}" — đây là bắt buộc, KHÔNG được bỏ qua
- "{img_style.environment}" — đây là bắt buộc, KHÔNG được bỏ qua
- "{img_style.lighting}" — đây là bắt buộc, KHÔNG được bỏ qua
- "{img_style.camera}" — đây là bắt buộc, KHÔNG được bỏ qua
- "{img_style.composition}" — đây là bắt buộc, KHÔNG được bỏ qua

NẾU thiếu bất kỳ constraint nào → scene sẽ bị REJECT và yêu cầu regenerate.
```

### Update JSON example to show actual constraint values

Change the JSON example from:
```
"image_prompt": "3D Pixar Disney style, [visual_concept], [emotion], warm lighting, eye-level camera, professional composition"
```

To:
```
"image_prompt": "{img_style.art_style}, {img_style.environment}, {img_style.lighting} lighting, {img_style.camera} camera, {img_style.composition} composition, [visual_concept]"
```

This makes the constraint values explicit in the example the LLM reads.

---

## 2. Post-Generation Validation — `generate_script_from_idea`

**Location:** `modules/content/content_idea_generator.py`

Add retry logic after scene parsing:

```python
def generate_script_from_idea(self, idea: ContentIdea, num_scenes: Optional[int] = None) -> List[SceneConfig]:
    # ... existing generation ...

    scenes = self._parse_scenes(text)
    if not scenes:
        raise ValueError("No scenes parsed from LLM response")

    # Validate with retry
    validated_scenes = []
    for scene_dict in scenes:
        scene = self._validate_and_fix_scene(scene_dict, attempt=1)
        validated_scenes.append(scene)

    return validated_scenes

def _validate_and_fix_scene(self, scene_dict: dict, attempt: int, max_attempts: int = 3) -> SceneConfig:
    prompt_builder = PromptBuilder(
        channel_style=self._channel_config.image_style if self._channel_config else None,
        brand_tone=getattr(self._channel_config, 'style', '') or ''
    )

    image_prompt = scene_dict.get('image_prompt') or ""
    is_valid, violations = prompt_builder.validate_image_prompt(image_prompt)

    if is_valid:
        return self._dict_to_scene(scene_dict)

    if attempt >= max_attempts:
        raise SceneValidationError(
            scene_id=scene_dict.get('id', 0),
            violations=violations
        )

    # Retry: regenerate full scene with feedback
    retry_prompt = self._build_retry_prompt(scene_dict, violations, attempt)
    retry_text = self._call_llm(retry_prompt)
    retry_scenes = self._parse_scenes(retry_text)
    if retry_scenes:
        return self._validate_and_fix_scene(retry_scenes[0], attempt + 1, max_attempts)
    raise SceneValidationError(scene_id=scene_dict.get('id', 0), violations=violations)

def _build_retry_prompt(self, scene_dict: dict, violations: list[str], attempt: int) -> str:
    # Include the original scene context + what was missing
    return f"""Regenerate this scene. Image prompt was MISSING constraints: {violations}.
Original scene:
- script: {scene_dict.get('script', '')}
- character: {scene_dict.get('character', '')}
- creative_brief: {scene_dict.get('creative_brief', '')}

IMPORTANT: The new image_prompt MUST contain all of: {', '.join(violations)}"""
```

---

## 3. New Exception — `SceneValidationError`

**Location:** `modules/pipeline/exceptions.py`

```python
class SceneValidationError(Exception):
    """Raised when scene fails validation after max retries."""
    def __init__(self, scene_id: int, violations: list[str]):
        self.scene_id = scene_id
        self.violations = violations
        super().__init__(f"Scene {scene_id} failed validation: missing {violations}")
```

---

## 4. Pipeline Integration — `scene_processor.py`

**No changes required** — `SceneValidationError` is already caught in `pipeline_runner.py` and re-raised to trigger script regeneration (existing behavior for `SceneDurationError`).

The retry logic happens inside `content_idea_generator.py` before the YAML is ever saved, so the pipeline won't see invalid prompts.

---

## 5. Edge Cases

| Case | Behavior |
|------|----------|
| Channel config without `image_style` | `PromptBuilder.validate_image_prompt()` returns valid (no constraints) |
| `image_prompt` is `None` or empty | Treated as violation → retry |
| Lipsync prompt violations | Same validation + retry flow, separate `validate_lipsync_prompt()` |
| All retries exhausted | `SceneValidationError` → pipeline catches and regenerates script |
| `creative_brief` violations | Log warning but don't block (advisory only, not strict) |

---

## 6. Testing

1. `test_validate_image_prompt_missing_constraint_triggers_retry` — mock LLM to return prompt missing art_style → verify retry is called
2. `test_validate_image_prompt_all_present_no_retry` — valid prompt → no retry
3. `test_scene_validation_error_raised_after_max_attempts` — verify exception after 3 failures
4. `test_retry_prompt_contains_violations` — verify feedback includes missing constraint names
5. `test_lipsync_validation_same_retry_flow` — same logic for lipsync prompt
6. Integration test: full scene generation with constraints

---

## Files Summary

| File | Action |
|------|--------|
| `modules/content/content_idea_generator.py` | Add constraint rules to prompt, add `_validate_and_fix_scene()` with retry, add `_build_retry_prompt()` |
| `modules/pipeline/exceptions.py` | Add `SceneValidationError` |
| `tests/test_content_idea_generator.py` | Add retry validation tests |