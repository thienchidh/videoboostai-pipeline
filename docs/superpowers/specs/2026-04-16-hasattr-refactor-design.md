# Spec: Replace dict/hasattr patterns with typed Pydantic objects

## Goal

Remove all unnecessary `hasattr` and `getattr(obj, 'field', default)` patterns across the pipeline by ensuring objects are properly typed Pydantic models from the point they're created. Code should access `.field` directly — no defensive hasattr checks needed.

## Principles

1. **Coerce at the boundary** — normalize raw data (dicts, strings, DB floats) to Pydantic objects at the earliest entry point.
2. **Enforce types downstream** — once coerced, downstream code uses direct attribute access.
3. **No redundant defensive checks** — if a field is guaranteed to exist on a Pydantic model, don't check for it.

---

## Changes

### 1. `models.py` — `SceneConfig.characters`: remove `| str` union

**File:** `modules/pipeline/models.py`

**Before:**
```python
characters: List["SceneCharacter | str"] = []
```

**After:**
```python
characters: List[SceneCharacter] = []
```

**Why:** `SceneCharacter.from_yaml()` already coerces strings to `SceneCharacter(name=string)`. The `| str` union was a legacy safety net that's no longer needed.

**Validation:** `SceneConfig.from_dict()` calls `SceneCharacter.from_yaml(c)` for each item — strings are handled at that point.

---

### 2. `scene_processor.py` — use `SceneConfig` fields directly

**File:** `modules/pipeline/scene_processor.py`

**Line 255 — remove hasattr for character name:**
```python
# Before
"characters": [c.name if hasattr(c, 'name') else str(c) for c in chars],

# After
"characters": [c.name for c in chars],
```

**Why:** `chars` is `List[SceneCharacter]` — `.name` always exists.

**Lines 251-257 — remove getattr fallback for scene fields:**
```python
# Before
"scene_index": getattr(scene, 'scene_index', 0),
"title": getattr(scene, 'title', None),
"script": getattr(scene, 'script', None) or getattr(scene, 'tts', ''),
"tts_text": getattr(scene, 'tts', '') or getattr(scene, 'script', ''),
"video_prompt": getattr(scene, 'video_prompt', None),
"creative_brief": getattr(scene, 'creative_brief', None),

# After — scene is a SceneConfig, access fields directly:
"scene_index": scene.id or 0,
"title": None,   # title lives on ScenarioConfig, not SceneConfig — was always None in practice
"script": scene.script or scene.tts or "",
"tts_text": scene.tts or scene.script or "",
"video_prompt": scene.video_prompt,
"creative_brief": scene.creative_brief,
```

---

### 3. `content_idea_generator.py` — return `List[SceneConfig]` from `_validate_scenes()`

**File:** `modules/content/content_idea_generator.py`

**Change `_validate_scenes()` return type and implementation:**

```python
# Before
def _validate_scenes(self, scenes: List[Dict]) -> List[Dict]:
    ...
    return validated  # List[Dict]

# After
def _validate_scenes(self, scenes: List[Dict]) -> List[SceneConfig]:
    ...
    return [SceneConfig.from_dict(s) for s in validated]
```

**Update `_parse_scenes()` return type accordingly:**

```python
# Before
def _parse_scenes(self, text: str) -> List[Dict]:

# After
def _parse_scenes(self, text: str) -> List[SceneConfig]:
```

**Line 166 — `scene.get("tts")` → `scene.tts`:**
```python
# Before
tts_text = scene.get("tts", "")

# After
tts_text = scene.tts or ""
```

**Line 170 — `scene.get('id', 0)` → `scene.id`:**
```python
# Before
logger.warning(f"  ⚠️ Scene {scene.get('id', 0)} TTS out of bounds")

# After
logger.warning(f"  ⚠️ Scene {scene.id or 0} TTS out of bounds")
```

**Line 175 — `scene["tts"] = regenerated` → `scene.tts = regenerated`:**
```python
# Before
scene["tts"] = regenerated

# After
scene.tts = regenerated  # scene is SceneConfig, attrs are mutable
```

**Line 163 — remove unnecessary getattr fallback:**
```python
# Before
wps = getattr(gen_cfg.tts, 'words_per_second', 2.5)

# After
wps = gen_cfg.tts.words_per_second  # GenerationTTS always has this field
```

**Why:** `gen_cfg.tts` is `GenerationTTS` which has `words_per_second: float = 2.5` — always exists.

---

### 4. `optimal_post_time.py` — normalize CTRData earlier

**File:** `modules/content/optimal_post_time.py`

**Before:**
```python
if isinstance(ctr_data, dict):
    ctr_data = CTRData.model_validate(ctr_data)
ctr = float(ctr_data.ctr if hasattr(ctr_data, 'ctr') else ctr_data or 0)
```

**After:**
```python
if isinstance(ctr_data, dict):
    ctr_data = CTRData.model_validate(ctr_data)
ctr = float(ctr_data.ctr)  # CTRData.ctr is always float
```

**Why:** `CTRData` Pydantic model has `ctr: float = 0.0` — field always exists after normalization.

---

### 5. `batch_generate.py` — use isinstance for date parsing

**File:** `scripts/batch_generate.py`

**Before:**
```python
scheduled_date = item.get("scheduled_date", date.today())
if hasattr(scheduled_date, "strftime"):
    date_str = scheduled_date.strftime("%Y-%m-%d")
else:
    date_str = str(scheduled_date)
```

**After:**
```python
from datetime import date, datetime

scheduled_date = item.get("scheduled_date", date.today())
if isinstance(scheduled_date, (date, datetime)):
    date_str = scheduled_date.strftime("%Y-%m-%d")
else:
    date_str = str(scheduled_date)
```

**Why:** `date` objects have `strftime`, `datetime` objects have `strftime`, strings don't. Clearer and faster than `hasattr`.

---

### 6. `TechnicalConfig.get()` — keep hasattr (valid use case)

**File:** `modules/pipeline/models.py`

The `hasattr` in `TechnicalConfig.get()` (line 196) is **valid** — it does dynamic attribute traversal on a nested key path where intermediate values may be `None`. This pattern is appropriate and should remain unchanged.

---

## What does NOT change

- `db.py:1082` — `hasattr(emb.embedding, 'tolist')` — valid, embedding can be numpy array or list
- `utils/embedding.py:159` — same reason
- `tests/test_*.py` — test assertions using `hasattr` to verify model structure are correct
- `models.py:196` in `TechnicalConfig.get()` — dynamic key traversal, valid

---

## Files modified

| File | Change |
|------|--------|
| `modules/pipeline/models.py` | `SceneConfig.characters` type hint |
| `modules/pipeline/scene_processor.py` | Remove `getattr`/`hasattr` for scene fields and characters |
| `modules/content/content_idea_generator.py` | Return `List[SceneConfig]`; direct `.tts`, `.id` access |
| `modules/content/optimal_post_time.py` | Remove `hasattr` after CTRData normalize |
| `scripts/batch_generate.py` | `isinstance` for date instead of `hasattr` |

---

## Test plan

1. `pytest tests/test_scene_processor.py -v` — scene_processor logic unchanged in behavior
2. `pytest tests/test_models.py -v` — Pydantic models still validate correctly
3. `python scripts/run_pipeline.py --ideas 1` — smoke test content pipeline
4. Manual: check `scene_meta.json` output — `characters` should be `[{name: "...", ...}]` not raw strings
