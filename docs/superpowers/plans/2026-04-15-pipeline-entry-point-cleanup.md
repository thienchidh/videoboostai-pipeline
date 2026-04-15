# Pipeline Entry Point Cleanup Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix bugs and remove redundant code from pipeline entry points.

**Architecture:** Three targeted fixes: (1) undefined `config` variable bug in `run_content_pipeline`, (2) remove `cron_manager.py` which duplicates `run_scheduler.py`, (3) clean up duplicated global flag definitions.

**Tech Stack:** Python, pytest

---

## Task 1: Fix undefined `config` bug in `run_content_pipeline`

**Files:**
- Modify: `scripts/run_pipeline.py:54-76`

- [ ] **Step 1: Read the broken code**

Run: `sed -n '54,76p' scripts/run_pipeline.py`

The bug is on line 73 — `config=config` references a variable that doesn't exist in this function's scope.

- [ ] **Step 2: Fix the undefined `config` variable**

Replace lines 71-76 with:

```python
    pipeline = ContentPipeline(
        project_id=project_id,
        config=None,
        dry_run=dry_run,
        channel_id=channel_id,
    )
```

`ContentPipeline.__init__` accepts `config: Dict = None` and handles `None` internally. This matches how `run_full_pipeline` constructs the same object (line 196-203).

- [ ] **Step 3: Verify the fix**

Run: `python -c "from scripts.run_pipeline import run_content_pipeline; print('OK')"`

Expected: `OK` (no NameError)

- [ ] **Step 4: Commit**

```bash
git add scripts/run_pipeline.py
git commit -m "fix: pass config=None instead of undefined variable in run_content_pipeline"
```

---

## Task 2: Remove redundant `cron_manager.py`

**Files:**
- Delete: `scripts/cron_manager.py`

`run_scheduler.py` (added in commit `13fbc81`) already handles cron-triggered research jobs. `cron_manager.py` is a competing scheduler that is never referenced from any other file, test, or doc.

- [ ] **Step 1: Confirm no references to cron_manager**

Run: `grep -r "cron_manager" --include="*.py" --include="*.md" --include="*.yaml" .`

Expected: only the file itself (if anything)

- [ ] **Step 2: Delete the file**

Run: `rm scripts/cron_manager.py`

- [ ] **Step 3: Commit**

```bash
git rm scripts/cron_manager.py
git commit -m "chore: remove redundant cron_manager.py (superseded by run_scheduler.py)"
```

---

## Task 3: Clean up global flag duplication

**Files:**
- Modify: `scripts/run_pipeline.py:31-36`

Three entry points define duplicate global flag sets:

| Flag | Defined in | Used by |
|------|-----------|---------|
| `DRY_RUN`, `DRY_RUN_TTS`, `DRY_RUN_IMAGES`, `UPLOAD_TO_SOCIALS`, `USE_STATIC_LIPSYNC` | `run_pipeline.py:31-36` | CLI only |
| `DRY_RUN`, `DRY_RUN_TTS`, `DRY_RUN_IMAGES`, `USE_STATIC_LIPSYNC` | `video_pipeline_v3.py:21-26` | batch_generate, cron_manager, retry |

The duplication causes silent inconsistencies — `run_pipeline.py`'s flags and `video_pipeline_v3.py`'s flags are separate objects. `batch_generate.py` correctly imports and manipulates `video_pipeline_v3`'s flags, but `run_pipeline.py`'s CLI code never exports its flags anywhere.

Fix: `run_pipeline.py` should import flags from `video_pipeline_v3` instead of redefining them.

- [ ] **Step 1: Read current flag definitions**

Run: `sed -n '31,50p' scripts/run_pipeline.py`

- [ ] **Step 2: Replace lines 31-36 in run_pipeline.py**

Replace:
```python
# Global flags for video pipeline (set these before calling run_* functions)
DRY_RUN = False
DRY_RUN_TTS = False
DRY_RUN_IMAGES = False
UPLOAD_TO_SOCIALS = False
USE_STATIC_LIPSYNC = False
```

With:
```python
# Re-export flags from video_pipeline_v3 (the canonical source)
from scripts.video_pipeline_v3 import DRY_RUN, DRY_RUN_TTS, DRY_RUN_IMAGES, USE_STATIC_LIPSYNC
UPLOAD_TO_SOCIALS = False  # Only used in CLI context
```

- [ ] **Step 3: Verify imports work**

Run: `python -c "from scripts.run_pipeline import DRY_RUN, DRY_RUN_TTS, DRY_RUN_IMAGES, USE_STATIC_LIPSYNC; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add scripts/run_pipeline.py
git commit -m "refactor: import video flags from video_pipeline_v3 instead of duplicating them"
```

---

## Verification

After all tasks:

```bash
# 1. No NameError on import
python -c "from scripts.run_pipeline import run_content_pipeline; print('run_content_pipeline OK')"

# 2. cron_manager.py gone
ls scripts/cron_manager.py && echo "FAIL" || echo "cron_manager.py removed OK"

# 3. Flags importable
python -c "from scripts.run_pipeline import DRY_RUN, DRY_RUN_TTS; print('flags OK')"

# 4. Tests still pass
pytest tests/ -v --tb=short
```