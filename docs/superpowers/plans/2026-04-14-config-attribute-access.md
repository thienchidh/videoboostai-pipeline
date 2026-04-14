# Config Attribute Access Refactor Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all dict-style `.get()` accesses on Pydantic model instances with direct attribute access, and remove unnecessary fallback patterns across the pipeline codebase.

**Architecture:** Two-phase approach: (1) Fix scene_processor.py and pipeline_runner.py where Pydantic model instances are accessed via `.get()`, (2) Clean up unnecessary fallback patterns. YAML loading in `models.py` remains unchanged as it necessarily parses raw dicts before Pydantic validation.

**Tech Stack:** Python, Pydantic, Pytest

---

## File Map

| File | Issue | Action |
|------|-------|--------|
| `modules/pipeline/scene_processor.py` | `scene.get("id")`, `scene.get("tts")`, etc. on `SceneConfig` Pydantic model | Replace with `scene.id`, `scene.tts`, etc. |
| `modules/pipeline/pipeline_runner.py` | `models.get("tts")`, `models.get("image")` on `GenerationModels` Pydantic model | Replace with `models.tts`, `models.image` |
| `modules/content/content_idea_generator.py` | Unnecessary `if self._llm_config` checks before `.get()` | Remove redundant conditionals |
| `modules/pipeline/scene_processor.py` | `isinstance(chars[0], dict) and chars[0].get("speed")` | `chars[0]` is `CharacterConfig` Pydantic, use `chars[0].speed` |

---

### Task 1: Fix `scene_processor.py` — SceneConfig attribute access

**Files:**
- Modify: `modules/pipeline/scene_processor.py`

- [ ] **Step 1: Read the file to find all scene.get() calls**

Run: `grep -n "\.get(" modules/pipeline/scene_processor.py`
Expected: Lines 87, 90, 111, 176, 177, 178, 201 contain scene dict access

- [ ] **Step 2: Write a test verifying direct attribute access works**

Create test in `tests/test_scene_processor.py`:
```python
def test_scene_config_direct_attribute_access():
    """SceneConfig is a Pydantic model — access should be via attributes, not .get()"""
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(
        id=1,
        tts="Hello world",
        script="Hello world",
        video_prompt="a person talking",
        background="studio",
        characters=[]
    )
    # These should work the same as .get() but with direct attribute access
    assert scene.id == 1
    assert scene.tts == "Hello world"
    assert scene.script == "Hello world"
    assert scene.video_prompt == "a person talking"
    assert scene.background == "studio"
```

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/test_scene_processor.py::test_scene_config_direct_attribute_access -v`
Expected: PASS

- [ ] **Step 4: Replace scene.get() calls with direct attributes in scene_processor.py**

Lines 87, 90, 111 (in `expand_script`):
```python
# OLD (lines 87, 90, 111):
explicit = scene.get("video_prompt")
explicit = scene.get("background") or "a person talking"
return scene.get("background") or "a person talking"

# NEW:
explicit = scene.video_prompt
explicit = scene.background or "a person talking"
return scene.background or "a person talking"
```

Lines 176-178 (in `process`):
```python
# OLD:
scene_id = scene.get("id") or 0
tts_text = scene.get("tts") or scene.get("script") or ""
chars = scene.get("characters") or []

# NEW:
scene_id = scene.id or 0
tts_text = scene.tts or scene.script or ""
chars = scene.characters or []
```

Line 201 (character speed check):
```python
# OLD:
if isinstance(chars[0], dict) and chars[0].get("speed"):

# NEW:
if chars[0].speed:
```
Note: `chars[0]` is already a `CharacterConfig` Pydantic model from `ctx.channel.characters`, so direct attribute access works.

- [ ] **Step 5: Run tests to verify changes pass**

Run: `pytest tests/test_scene_processor.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add modules/pipeline/scene_processor.py
git commit -m "refactor: use direct SceneConfig attribute access instead of .get()"
```

---

### Task 2: Fix `pipeline_runner.py` — GenerationModels attribute access

**Files:**
- Modify: `modules/pipeline/pipeline_runner.py`

- [ ] **Step 1: Read the file to find models.get() calls**

Run: `grep -n "\.get(" modules/pipeline/pipeline_runner.py | head -30`
Expected: Lines 127, 141 contain `models.get("tts")` and `models.get("image")`

- [ ] **Step 2: Write a test verifying direct attribute access on GenerationModels**

Add to `tests/test_scene_processor.py`:
```python
def test_generation_models_direct_attribute_access():
    """GenerationModels is a Pydantic model — access should be via attributes"""
    from modules.pipeline.models import GenerationModels
    models = GenerationModels(tts="minimax", image="minimax")
    assert models.tts == "minimax"
    assert models.image == "minimax"
```

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/test_scene_processor.py::test_generation_models_direct_attribute_access -v`
Expected: PASS

- [ ] **Step 4: Replace models.get() calls in pipeline_runner.py**

Lines 127, 141:
```python
# OLD (line 127):
tts_name = models.get("tts")

# NEW:
tts_name = models.tts
```
```python
# OLD (line 141):
img_name = models.get("image")

# NEW:
img_name = models.image
```

- [ ] **Step 5: Run tests to verify changes pass**

Run: `pytest tests/test_scene_processor.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add modules/pipeline/pipeline_runner.py
git commit -m "refactor: use direct GenerationModels attribute access instead of .get()"
```

---

### Task 3: Fix `content_idea_generator.py` — Remove unnecessary conditionals

**Files:**
- Modify: `modules/content/content_idea_generator.py`

- [ ] **Step 1: Read the file to find redundant if checks before .get()**

Run: `grep -n "if self._llm_config" modules/content/content_idea_generator.py`
Expected: Lines around 107, 116, 118

- [ ] **Step 2: Verify self._llm_config default value**

Check line 48 or nearby for `self._llm_config = ...`
Expected: `self._llm_config = {}` or similar default

- [ ] **Step 3: Remove redundant if-checks**

```python
# OLD (line 107):
api_key = self._llm_config.get("api_key", "") if self._llm_config else ""

# NEW:
api_key = self._llm_config.get("api_key", "")
```

```python
# OLD (line 116):
name=self._llm_config.get("provider", "minimax") if self._llm_config else "minimax",

# NEW:
name=self._llm_config.get("provider", "minimax"),
```

```python
# OLD (line 118):
model=self._llm_config.get("model", "MiniMax-M2.7") if self._llm_config else "MiniMax-M2.7",

# NEW:
model=self._llm_config.get("model", "MiniMax-M2.7"),
```

- [ ] **Step 4: Run tests to verify changes pass**

Run: `pytest tests/ -v -k content_idea`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/content/content_idea_generator.py
git commit -m "refactor: remove redundant if-checks before .get() in LLM config access"
```

---

### Task 4: Audit for remaining unnecessary fallback patterns

**Files:**
- Review: `modules/pipeline/scene_processor.py`
- Review: `modules/pipeline/pipeline_runner.py`
- Review: `modules/content/content_pipeline.py`

- [ ] **Step 1: Search for fallback patterns that could be simplified**

Run: `grep -rn "\.get.*or os\.getenv" modules/`
Expected: db.py lines 43-47 (intentional env var fallback — leave as-is)

Run: `grep -rn "\.get.*or \"\|or '" modules/`
Expected: Any unnecessary `or "default"` after `.get()` where None check already handled

- [ ] **Step 2: Fix any unnecessary fallbacks found**

If any found, document in commit message and apply minimal fix.

- [ ] **Step 3: Commit if changes found, otherwise note "no changes needed"**

---

## Self-Review Checklist

- [ ] All `.get()` calls on Pydantic model instances replaced with direct attribute access
- [ ] SceneConfig scene.get() calls → scene.id, scene.tts, scene.script, scene.background, scene.characters
- [ ] GenerationModels models.get() → models.tts, models.image
- [ ] Unnecessary `if self._llm_config` conditionals removed
- [ ] All tests pass
- [ ] No placeholder content (TBD, TODO)
