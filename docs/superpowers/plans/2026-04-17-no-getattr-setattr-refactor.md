# No getattr/setattr — Direct Property Access Refactor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all `getattr`/`setattr` for class attribute access in production code with direct property access, per the rule in CLAUDE.md.

**Architecture:** Each file is refactored independently. Pydantic models already have defaults — direct `.field` access replaces `getattr(model, 'field', default)`. Tests are unaffected (use `object.__setattr__` for frozen models).

**Tech Stack:** Python, Pydantic, pytest

---

## Task 1: Refactor `modules/media/tts.py`

**Files:**
- Modify: `modules/media/tts.py:78,157`
- Test: `tests/test_tts.py` (verify TTS generation works with direct access)

- [ ] **Step 1: Read the file to confirm current state**

Run: `head -n 160 modules/media/tts.py | tail -n 90`

- [ ] **Step 2: Edit line 78 — replace `getattr` with direct access**

```python
# Before (line ~78):
self.sample_rate = getattr(config.generation.tts, 'sample_rate', 32000)

# After:
self.sample_rate = config.generation.tts.sample_rate
```

- [ ] **Step 3: Edit line 157 — replace `getattr` with direct access**

```python
# Before (line ~157):
word_timestamp_timeout = getattr(self._config.generation.tts, 'word_timestamp_timeout', 120)

# After:
word_timestamp_timeout = self._config.generation.tts.word_timestamp_timeout
```

- [ ] **Step 4: Run TTS tests to verify nothing broke**

Run: `pytest tests/test_tts.py -v`
Expected: PASS (or skip if no test_tts.py — verify imports work instead)

- [ ] **Step 5: Commit**

```bash
git add modules/media/tts.py
git commit -m "refactor(tts): replace getattr with direct property access"
```

---

## Task 2: Refactor `modules/media/image_gen.py`

**Files:**
- Modify: `modules/media/image_gen.py:114-115,211-212`
- Test: `tests/test_image_gen.py` (if exists)

- [ ] **Step 1: Read lines 100-130 to find the first getattr pattern**

- [ ] **Step 2: Edit lines 114-115 — replace `getattr` with direct access**

```python
# Before (lines ~114-115):
self.poll_interval = getattr(config.generation.image, 'poll_interval', 5)
self.max_polls = getattr(config.generation.image, 'max_polls', 24)

# After:
self.poll_interval = config.generation.image.poll_interval
self.max_polls = config.generation.image.max_polls
```

- [ ] **Step 3: Read lines 200-220 to find the second getattr pattern**

- [ ] **Step 4: Edit lines 211-212 — replace `getattr` with direct access**

```python
# Before (lines ~211-212):
self.poll_interval = getattr(config.generation.image, 'poll_interval', 5)
self.max_polls = getattr(config.generation.image, 'max_polls', 24)

# After:
self.poll_interval = config.generation.image.poll_interval
self.max_polls = config.generation.image.max_polls
```

Note: These appear in two different class `__init__` methods — `MiniMaxImageProvider` and `KieImageProvider`. Apply the same fix to both.

- [ ] **Step 5: Run image_gen tests**

Run: `pytest tests/test_image_gen.py -v 2>/dev/null || echo "no test file"`
Expected: PASS or "no test file"

- [ ] **Step 6: Commit**

```bash
git add modules/media/image_gen.py
git commit -m "refactor(image_gen): replace getattr with direct property access"
```

---

## Task 3: Refactor `modules/media/prompt_builder.py`

**Files:**
- Modify: `modules/media/prompt_builder.py:43-47`
- Test: `tests/test_prompt_builder.py` (if exists)

- [ ] **Step 1: Read lines 30-55 to see the full context**

- [ ] **Step 2: Edit lines 43-47 — replace all 5 `getattr` calls**

```python
# Before (lines ~43-47):
"lighting": getattr(self.channel_style, "lighting", None),
"camera": getattr(self.channel_style, "camera", None),
"art_style": getattr(self.channel_style, "art_style", None),
"environment": getattr(self.channel_style, "environment", None),
"composition": getattr(self.channel_style, "composition", None),

# After:
"lighting": self.channel_style.lighting,
"camera": self.channel_style.camera,
"art_style": self.channel_style.art_style,
"environment": self.channel_style.environment,
"composition": self.channel_style.composition,
```

Note: `self.channel_style` is `ImageStyleConfig` — all 5 fields have defaults in the model (lines 288-293 of models.py), so direct access is safe.

- [ ] **Step 3: Verify `ImageStyleConfig` defaults exist**

Run: `grep -n "class ImageStyleConfig" modules/pipeline/models.py`
Expected: Confirms the class exists with all 5 fields defaulted

- [ ] **Step 4: Run prompt_builder tests**

Run: `pytest tests/test_prompt_builder.py -v 2>/dev/null || echo "no test file"`
Expected: PASS or "no test file"

- [ ] **Step 5: Commit**

```bash
git add modules/media/prompt_builder.py
git commit -m "refactor(prompt_builder): replace getattr with direct property access"
```

---

## Task 4: Refactor `modules/content/content_idea_generator.py`

**Files:**
- Modify: `modules/content/content_idea_generator.py:208`
- Test: `tests/test_content_idea_generator.py` (if exists)

- [ ] **Step 1: Read line 200-220 to see context**

- [ ] **Step 2: Edit line 208 — replace `getattr` with direct access**

```python
# Before (line ~208):
voice_info = getattr(c, 'voice_id', '') or ""

# After:
voice_info = c.voice_id or ""
```

Here `c` is a `CharacterConfig` object — `voice_id` is a required field (no default), so direct access is safe.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_content_idea_generator.py -v 2>/dev/null || echo "no test file"`
Expected: PASS or "no test file"

- [ ] **Step 4: Commit**

```bash
git add modules/content/content_idea_generator.py
git commit -m "refactor(content_idea_generator): replace getattr with direct property access"
```

---

## Task 5: Refactor `modules/content/content_pipeline.py`

**Files:**
- Modify: `modules/content/content_pipeline.py:761`
- Test: `tests/test_content_pipeline.py` (if exists)

- [ ] **Step 1: Read line 755-770 to see context**

- [ ] **Step 2: Edit line 761 — replace `getattr` with direct access**

```python
# Before (line ~761):
_runner = getattr(pipeline, '_runner', None)

# After:
_runner = pipeline._runner if hasattr(pipeline, '_runner') else None
```

`pipeline` here is a `ContentPipeline` instance. `_runner` is an internal attribute that may or may not exist depending on initialization state — using `hasattr` is appropriate here.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_content_pipeline.py -v 2>/dev/null || echo "no test file"`
Expected: PASS or "no test file"

- [ ] **Step 4: Commit**

```bash
git add modules/content/content_pipeline.py
git commit -m "refactor(content_pipeline): replace getattr with direct property access"
```

---

## Task 6: Refactor `modules/pipeline/scene_processor.py`

**Files:**
- Modify: `modules/pipeline/scene_processor.py:114,129,234,235,323,393,397,512`
- Test: `tests/test_scene_processor.py`

- [ ] **Step 1: Read lines 110-135 to see `getattr` for character fields**

- [ ] **Step 2: Edit lines 114 and 129 — replace character field getattr**

```python
# Before (lines ~114,129):
voice_id = getattr(character, 'voice_id', None) if character else None
gender = getattr(character, 'gender', None) if character else None

# After:
voice_id = character.voice_id if character else None
gender = character.gender if character else None
```

- [ ] **Step 3: Read lines 228-240 to see channel style getattr**

- [ ] **Step 4: Edit lines 234-235 — replace channel getattr**

```python
# Before (lines ~234-235):
channel_style=getattr(self.ctx.channel, 'image_style', None),
brand_tone=getattr(self.ctx.channel, 'style', '') or ''

# After:
channel_style=self.ctx.channel.image_style if self.ctx.channel else None,
brand_tone=self.ctx.channel.style or '',
```

- [ ] **Step 5: Read lines 318-330 to see scene getattr**

- [ ] **Step 6: Edit line 323 — replace scene getattr**

```python
# Before (line ~323):
brief = getattr(scene, 'creative_brief', None)

# After:
brief = scene.creative_brief if scene else None
```

- [ ] **Step 7: Read lines 388-405 to see ctx getattr**

- [ ] **Step 8: Edit lines 393,397 — replace ctx getattr**

```python
# Before (lines ~393,397):
img_gen = getattr(self.ctx.technical, 'generation', None)
chan_video = getattr(self.ctx.channel, 'video', None)

# After:
img_gen = self.ctx.technical.generation if self.ctx.technical else None
chan_video = self.ctx.channel.video if self.ctx.channel else None
```

- [ ] **Step 9: Read line 510-515 to see lip_gen getattr**

- [ ] **Step 10: Edit line 512 — replace lip_gen getattr**

```python
# Before (line ~512):
lip_gen = getattr(self.ctx.technical, 'generation', None)

# After:
lip_gen = self.ctx.technical.generation if self.ctx.technical else None
```

- [ ] **Step 11: Run scene_processor tests**

Run: `pytest tests/test_scene_processor.py -v`
Expected: PASS

- [ ] **Step 12: Commit**

```bash
git add modules/pipeline/scene_processor.py
git commit -m "refactor(scene_processor): replace 8 getattr calls with direct property access"
```

---

## Task 7: Refactor `modules/pipeline/pipeline_runner.py`

**Files:**
- Modify: `modules/pipeline/pipeline_runner.py:352-353`
- Test: `tests/test_pipeline_runner.py` (if exists)

- [ ] **Step 1: Read lines 348-358 to see context**

- [ ] **Step 2: Edit lines 352-353 — replace scenario getattr**

```python
# Before (lines ~352-353):
"scenario_slug": getattr(self.ctx.scenario, 'slug', ''),
"scenario_title": getattr(self.ctx.scenario, 'title', ''),

# After:
"scenario_slug": self.ctx.scenario.slug if self.ctx.scenario else '',
"scenario_title": self.ctx.scenario.title if self.ctx.scenario else '',
```

`self.ctx.scenario` is a property that raises `RuntimeError` if no scenario loaded (see config.py:55-63). The hasattr check handles the None case.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_pipeline_runner.py -v 2>/dev/null || echo "no test file"`
Expected: PASS or "no test file"

- [ ] **Step 4: Commit**

```bash
git add modules/pipeline/pipeline_runner.py
git commit -m "refactor(pipeline_runner): replace getattr with direct property access"
```

---

## Task 8: Refactor `modules/pipeline/models.py` — `TechnicalConfig.get()`

**Files:**
- Modify: `modules/pipeline/models.py:179-209` (the `get` method), plus find/update all callers
- Test: Run full test suite to verify

**Finding all callers of `TechnicalConfig.get()`:**

- [ ] **Step 1: Search for all callers of `config.get(` or `technical.get(`**

Run: `grep -rn "\.get('" modules/ --include="*.py" | grep -v "data\.get\|dict\.get\|\.get(\""`
Expected: List any calls to `.get('api.'`, `.get('generation.` etc.

- [ ] **Step 2: Based on search results, decide:**
- If **no callers found**: Remove the `get()` method entirely (lines 179-209)
- If **callers found**: Replace each with direct attribute access, then remove the method

For this project, the `get()` method is used for backward-compatible config access. If callers exist, they should be replaced with:
- `config.api_keys.minimax` instead of `config.get('api.keys.minimax')`
- `config.generation.tts.sample_rate` instead of `config.get('generation.tts.sample_rate')`

- [ ] **Step 3: If removing the method, also remove the `get` method from TechnicalConfig (lines 179-209)**

```python
# Remove this entire method from TechnicalConfig:
def get(self, key: str, default=None):
    """Dict-like access for backward compatibility..."""
    parts = key.split('.')
    ...
```

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -n 30`
Expected: PASS (no regressions from removing the get method)

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/models.py
git commit -m "refactor(models): remove TechnicalConfig.get(), use direct attribute access"
```

---

## Task 9: Refactor `db.py` and `db/helpers.py` — ORM-style setattr

**Files:**
- Modify: `db.py:240,360,614,1126`, `db/helpers.py:124,223,458,649,689,690,708,809`
- Test: `pytest tests/` (full suite)

- [ ] **Step 1: Read db.py lines 235-245 to see the context of the setattr calls**

- [ ] **Step 2: Edit db.py line 240 — refactor ORM setattr pattern**

```python
# Before (line ~240):
setattr(run, k, v)

# After (with hasattr guard):
if hasattr(run, k):
    setattr(run, k, v)
```

The `hasattr` guard ensures we only set attributes that actually exist on the model — prevents silent failures from typos in field names.

Apply the same pattern to lines 360, 614, 1126 in db.py.

- [ ] **Step 3: Read db/helpers.py lines 120-130, 218-228, 453-463, 644-655, 685-695, 704-712, 804-814**

- [ ] **Step 4: Edit db/helpers.py — apply same hasattr guard pattern**

```python
# Before:
setattr(run, k, v)

# After:
if hasattr(run, k):
    setattr(run, k, v)
```

Apply to all setattr calls (lines 124, 223, 458, 649, 809).

For `getattr(row, "error", None)` and `getattr(row, "published_at", None)` (lines 689-690, 708): these access dataclass/database row attributes, not Pydantic models. These can stay as-is OR be replaced with direct access if the row type supports it. Check the row type first — if it's a plain dataclass, direct access is fine.

```python
# Before (lines ~689-690):
"error": getattr(row, "error", None),
"published_at": getattr(row, "published_at", None),

# After (if row is a dataclass with these fields):
"error": row.error,
"published_at": row.published_at,
```

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -n 40`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add db.py db/helpers.py
git commit -m "refactor(db): add hasattr guards to setattr calls, replace getattr with direct access"
```

---

## Verification

After all tasks complete:

- [ ] **Step 1: Final grep for remaining getattr/setattr in production code**

Run: `grep -rn "getattr\|setattr" modules/ --include="*.py" | grep -v "object.__setattr__\|getattr(logging\|getattr(type"`
Expected: Empty output (no matches in production modules/)

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -n 20`
Expected: All tests PASS

- [ ] **Step 3: Final commit with all remaining changes**

```bash
git add -A
git commit -m "refactor: eliminate all getattr/setattr for class attribute access

Rule from CLAUDE.md: no getattr/setattr for class attributes.
All production code now uses direct property access."
```

---

## Summary

| Task | File | Changes |
|------|------|---------|
| 1 | modules/media/tts.py | 2 replacements |
| 2 | modules/media/image_gen.py | 4 replacements |
| 3 | modules/media/prompt_builder.py | 5 replacements |
| 4 | modules/content/content_idea_generator.py | 1 replacement |
| 5 | modules/content/content_pipeline.py | 1 replacement |
| 6 | modules/pipeline/scene_processor.py | 8 replacements |
| 7 | modules/pipeline/pipeline_runner.py | 2 replacements |
| 8 | modules/pipeline/models.py | Remove `TechnicalConfig.get()` |
| 9 | db.py + db/helpers.py | 8 setattr + 3 getattr replacements |
| Verification | all | Final grep + full test suite |