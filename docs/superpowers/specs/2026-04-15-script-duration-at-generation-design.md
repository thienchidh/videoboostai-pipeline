# Fix Script Duration at Generation Time

## Context

When `ContentIdeaGenerator._generate_scenes()` calls LLM to generate scene scripts, the prompt says "mỗi scene 3-8 câu" — but sentence length varies wildly in Vietnamese. A 3-sentence scene can be 2 seconds or 60 seconds. The result: after TTS runs, `SceneDurationError` is raised and `_regenerate_script_with_llm` attempts to fix it, but that fallback has its own circular-wps problem (fixed separately in commit `2ac793a`).

## Goal

Generate scene scripts that fit TTS duration bounds on the **first pass** — so the post-TTS validation loop in `scene_processor.py` rarely triggers.

## Approach B: Pre-validate + Regenerate in ContentIdeaGenerator

### Where

`modules/content/content_idea_generator.py` — `_generate_scenes()` and `_validate_scene_duration()`

### Architecture

```
LLM generate scenes → parse JSON → validate each scene word count → if too long → regenerate that scene → retry (up to N times)
```

### Components

**1. `_estimate_tts_duration(scene_tts_text)`**
- Uses `words_per_second` from channel config (default 2.5 wps)
- Returns `len(text.split()) / wps`
- No API calls — pure computation

**2. `_validate_scene_duration(scene_tts: str, channel_tts_config)`**
- Reads `channel.tts.min_duration` and `channel.tts.max_duration` from the validated `ChannelConfig`
- Estimates duration via `_estimate_tts_duration()`
- Returns `True` if within bounds, `False` if exceeds

**3. `_generate_scenes()` — modified flow**
```
LLM generate → parse JSON → for each scene:
    if scene["tts"] fits bounds:
        continue
    else:
        call LLM to shorten/expand this scene's TTS (target = middle of min/max)
        replace scene["tts"] with result
        retry up to 3x per scene
→ return scenes
```

**4. Prompt update** — replace vague "3-8 câu" with explicit word count guidance:
```
Mỗi scene TTS phải có 25-35 từ tiếng Việt (tương đương 10-14 giây đọc).
Câu ngắn gọn, mỗi câu không quá 10 từ.
```

### Data Flow

```
ContentPipeline.run_full_cycle()
  → idea_gen.generate_script_from_idea(idea)
    → _generate_scenes()  [modification here]
        → LLM prompt includes duration guidance
        → parse JSON scenes
        → for each scene: _validate_scene_duration()
            → if fails: regenerate TTS text only (not full scene JSON)
            → retry 3x, then keep best effort (log warning)
    → return script dict
  → save to DB
  → produce video
```

### Error Handling

- If LLM regeneration fails after 3 retries → keep original scene (log warning) — don't block entire pipeline
- If `ChannelConfig` has no `tts` config → skip validation (log info) — backward compatible
- If `_validate_scene_duration()` raises → skip and log debug

### Testing

1. `test_scene_duration_validation()` — mocks LLM response, verifies too-long scenes are flagged
2. `test_regenerate_shortens_long_scene()` — mocks LLM regeneration, verifies word count reduced
3. `test_validation_skipped_when_no_tts_config()` — backward compat
4. `test_idea_generator_respects_channel_tts_bounds()` — integration: generate script with known channel config, count words per scene, assert all within bounds

### Files Affected

| File | Change |
|------|--------|
| `modules/content/content_idea_generator.py` | Add `_estimate_tts_duration`, `_validate_scene_duration`, modify `_generate_scenes`, update prompt |
| `tests/test_content_idea_generator.py` (new) | Unit tests for duration validation and regeneration |

### Out of Scope

- Changes to `video_pipeline_v3.py` retry mechanism (already works, just rare now)
- Changes to `scene_processor.py` duration validation (stays as last-resort guard)
- Changes to TTS provider configuration

### Why Approach B

Approach A (rich prompt) depends on LLM following word count guidance — no guarantee. Approach C adds metadata coupling between layers. Approach B validates before leaving content generation layer, catches bad scripts before TTS credits are spent, reuses existing retry pattern, and keeps the pipeline flow intact.