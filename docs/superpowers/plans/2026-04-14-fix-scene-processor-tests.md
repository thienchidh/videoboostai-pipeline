# Fix SceneProcessor Test Failures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 failing tests in `test_scene_processor.py` caused by type mismatch — code expects `SceneConfig` Pydantic objects but tests pass raw `dict`.

**Architecture:** Make `build_scene_prompt()` and `process()` accept `Dict[str, Any]` (matching what tests pass) instead of `SceneConfig`. Scenes flow through pipeline as dicts from YAML loading before conversion to `SceneConfig`.

**Tech Stack:** pytest, Pydantic models, scene_processor.py

---

## Root Cause

`SingleCharSceneProcessor.process()` and `SceneProcessor.build_scene_prompt()` use `SceneConfig` type hints but the pipeline actually calls them with `Dict[str, Any]` (raw dicts from YAML). Tests pass raw dicts matching reality.

- `scene_processor.py:111`: `scene.background` — dict has no `.background` attr
- `scene_processor.py:176`: `scene.id` — dict has no `.id` attr

**Fix:** Change type hints from `SceneConfig` to `Dict[str, Any]` and access dict keys with `[]` / `.get()`.

---

## Task 1: Fix `build_scene_prompt()` to accept dict

**Files:**
- Modify: `modules/pipeline/scene_processor.py:108-111`

- [ ] **Step 1: Update build_scene_prompt signature and body**

Change:
```python
def build_scene_prompt(self, scene: SceneConfig) -> str:
    return scene.background or "a person talking"
```

To:
```python
def build_scene_prompt(self, scene: Dict[str, Any]) -> str:
    return scene.get("background") or "a person talking"
```

- [ ] **Step 2: Run tests to verify fix**

Run: `pytest tests/test_scene_processor.py::TestSceneProcessorHelpers::test_build_scene_prompt_returns_background tests/test_scene_processor.py::TestSceneProcessorHelpers::test_build_scene_prompt_returns_default_when_no_background -v`
Expected: PASS

---

## Task 2: Fix `SingleCharSceneProcessor.process()` to access dict properly

**Files:**
- Modify: `modules/pipeline/scene_processor.py:162-203`

- [ ] **Step 1: Update process() signature and scene_id access**

Type hint change: `scene: SceneConfig` → `scene: Dict[str, Any]`
Line 176: `scene_id = scene.id or 0` → `scene_id = scene.get("id") or 0`

- [ ] **Step 2: Update tts_text access**

Line 177: `scene.tts or scene.script or ""` → `scene.get("tts") or scene.get("script") or ""`

- [ ] **Step 3: Update chars access**

Line 178: `scene.characters or []` → `scene.get("characters") or []`

- [ ] **Step 4: Verify all tests pass**

Run: `pytest tests/test_scene_processor.py -v`
Expected: ALL PASS (61/61)

---

## Verification

Final check:
```
pytest tests/ -v
```
All 61 tests must pass.
