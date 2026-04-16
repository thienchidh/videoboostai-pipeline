# Hasattr Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all unnecessary `hasattr`/`getattr` patterns across the pipeline by ensuring objects are properly typed Pydantic models. Code accesses `.field` directly — no defensive hasattr checks needed.

**Architecture:** Coerce raw data (dicts, strings, DB floats) to Pydantic objects at the earliest entry point. Once coerced, downstream code uses direct attribute access. Keep `hasattr` only where truly dynamic (e.g., `TechnicalConfig.get()` traversing arbitrary nested keys).

**Tech Stack:** Python, Pydantic, pytest

---

## Files Modified

| File | Change |
|------|--------|
| `modules/pipeline/models.py` | `SceneConfig.characters` type hint — remove `\| str` |
| `modules/pipeline/scene_processor.py` | Remove `getattr`/`hasattr` for scene fields and characters |
| `modules/content/content_idea_generator.py` | Return `List[SceneConfig]` from `_validate_scenes`; direct `.tts`, `.id` access |
| `modules/content/optimal_post_time.py` | Remove `hasattr` after CTRData normalize |
| `scripts/batch_generate.py` | `isinstance` for date instead of `hasattr` |

---

## Task 1: `models.py` — Remove `| str` from `SceneConfig.characters`

**Files:**
- Modify: `modules/pipeline/models.py:398`

- [ ] **Step 1: Change type hint**

```python
# Line 398 — Before:
characters: List["SceneCharacter | str"] = []

# After:
characters: List[SceneCharacter] = []
```

Run: `grep -n "SceneCharacter | str" modules/pipeline/models.py` to verify only one occurrence.

---

## Task 2: `scene_processor.py` — Remove `hasattr` for characters and `getattr` for scene fields

**Files:**
- Modify: `modules/pipeline/scene_processor.py:251-257`

- [ ] **Step 1: Fix line 255 — remove hasattr for character names**

```python
# Before:
"characters": [c.name if hasattr(c, 'name') else str(c) for c in chars],

# After:
"characters": [c.name for c in chars],
```

- [ ] **Step 2: Fix lines 251-257 — replace getattr with direct SceneConfig field access**

```python
# Before (lines 251-257):
"scene_index": getattr(scene, 'scene_index', 0),
"title": getattr(scene, 'title', None),
"script": getattr(scene, 'script', None) or getattr(scene, 'tts', ''),
"tts_text": getattr(scene, 'tts', '') or getattr(scene, 'script', ''),
"characters": [c.name for c in chars],
"video_prompt": getattr(scene, 'video_prompt', None),
"creative_brief": getattr(scene, 'creative_brief', None),

# After:
"scene_index": scene.id or 0,
"title": None,  # title lives on ScenarioConfig, not SceneConfig
"script": scene.script or scene.tts or "",
"tts_text": scene.tts or scene.script or "",
"characters": [c.name for c in chars],
"video_prompt": scene.video_prompt,
"creative_brief": scene.creative_brief,
```

Verify `SceneConfig` fields: `id`, `script`, `tts`, `video_prompt`, `creative_brief` — all exist in models.py.

- [ ] **Step 3: Commit**

```bash
git add modules/pipeline/scene_processor.py
git commit -m "fix(scene_processor): use SceneConfig fields directly, remove getattr/hasattr"
```

---

## Task 3: `content_idea_generator.py` — Return `List[SceneConfig]` from `_validate_scenes`

**Files:**
- Modify: `modules/content/content_idea_generator.py:163,166,170,175`
- Modify: `modules/content/content_idea_generator.py:322,422`

- [ ] **Step 1: Update `_parse_scenes` return type (line 322)**

```python
# Before:
def _parse_scenes(self, text: str) -> List[Dict]:

# After:
def _parse_scenes(self, text: str) -> List[SceneConfig]:
```

- [ ] **Step 2: Update `_validate_scenes` return type and body (line 422)**

```python
# Before:
def _validate_scenes(self, scenes: List[Dict]) -> List[Dict]:
    ...
    return validated

# After:
def _validate_scenes(self, scenes: List[Dict]) -> List[SceneConfig]:
    ...
    return [SceneConfig.from_dict(s) for s in validated]
```

The `validated` list at line 460 already contains normalized dicts — just wrap each with `SceneConfig.from_dict()`.

- [ ] **Step 3: Fix `wps` assignment — line 163 (remove getattr)**

```python
# Before:
wps = getattr(gen_cfg.tts, 'words_per_second', 2.5)

# After:
wps = gen_cfg.tts.words_per_second
```

`GenerationTTS` always has `words_per_second: float = 2.5` — field always exists.

- [ ] **Step 4: Fix `scene.get("tts", "")` — line 166**

```python
# Before:
tts_text = scene.get("tts", "")

# After:
tts_text = scene.tts or ""
```

- [ ] **Step 5: Fix `scene.get('id', 0)` — line 170**

```python
# Before:
logger.warning(f"  ⚠️ Scene {scene.get('id', 0)} TTS out of bounds ")

# After:
logger.warning(f"  ⚠️ Scene {scene.id or 0} TTS out of bounds ")
```

- [ ] **Step 6: Fix `scene["tts"] = regenerated` — line 175**

```python
# Before:
scene["tts"] = regenerated

# After:
scene.tts = regenerated
```

`SceneConfig` is a Pydantic model — its fields are mutable when accessed via instance attributes.

- [ ] **Step 7: Add missing import if not present**

Check top of `content_idea_generator.py` for `from modules.pipeline.models import SceneConfig`. If not present, add it.

- [ ] **Step 8: Commit**

```bash
git add modules/content/content_idea_generator.py
git commit -m "fix(content_idea_generator): return List[SceneConfig], use .tts/.id directly"
```

---

## Task 4: `optimal_post_time.py` — Remove `hasattr` after CTRData normalize

**Files:**
- Modify: `modules/content/optimal_post_time.py:237`

- [ ] **Step 1: Fix line 237 — remove hasattr**

```python
# Before:
ctr = float(ctr_data.ctr if hasattr(ctr_data, 'ctr') else ctr_data or 0)

# After:
ctr = float(ctr_data.ctr)
```

`CTRData.model_validate()` already ran at line 236 — `.ctr` always exists.

- [ ] **Step 2: Commit**

```bash
git add modules/content/optimal_post_time.py
git commit -m "fix(optimal_post_time): use CTRData.ctr directly after model_validate"
```

---

## Task 5: `batch_generate.py` — Use `isinstance` for date parsing

**Files:**
- Modify: `scripts/batch_generate.py:373-377`

- [ ] **Step 1: Check imports at top of file**

Ensure `datetime` is imported from `datetime`. If only `date` is imported, add `datetime`.

- [ ] **Step 2: Fix lines 373-377 — replace hasattr with isinstance**

```python
# Before:
scheduled_date = item.get("scheduled_date", date.today())
if hasattr(scheduled_date, "strftime"):
    date_str = scheduled_date.strftime("%Y-%m-%d")
else:
    date_str = str(scheduled_date)

# After:
scheduled_date = item.get("scheduled_date", date.today())
if isinstance(scheduled_date, (date, datetime)):
    date_str = scheduled_date.strftime("%Y-%m-%d")
else:
    date_str = str(scheduled_date)
```

- [ ] **Step 3: Commit**

```bash
git add scripts/batch_generate.py
git commit -m "fix(batch_generate): use isinstance for date vs str check"
```

---

## Task 6: Verify tests still pass

- [ ] **Step 1: Run scene_processor tests**

```bash
pytest tests/test_scene_processor.py -v
```

Expected: PASS

- [ ] **Step 2: Run models tests**

```bash
pytest tests/test_models.py -v
```

Expected: PASS

- [ ] **Step 3: Run optimal_post_time tests**

```bash
pytest tests/test_optimal_post_time.py -v
```

Expected: PASS

---

## Self-Review Checklist

- [ ] `SceneConfig.characters` — `| str` removed, only `List[SceneCharacter]` remains
- [ ] `scene_processor.py` — no `getattr(scene, ...)` calls remain for SceneConfig fields
- [ ] `scene_processor.py` — no `hasattr(c, 'name')` for `SceneCharacter` objects
- [ ] `content_idea_generator.py` — `_parse_scenes` returns `List[SceneConfig]`
- [ ] `content_idea_generator.py` — `scene.get("tts")` replaced with `scene.tts`
- [ ] `content_idea_generator.py` — `scene["tts"] =` replaced with `scene.tts =`
- [ ] `optimal_post_time.py` — no `hasattr(ctr_data, 'ctr')` remains
- [ ] `batch_generate.py` — `hasattr(scheduled_date, "strftime")` replaced with `isinstance`
- [ ] `TechnicalConfig.get()` — `hasattr` kept intact (valid dynamic traversal)
- [ ] All tests pass
