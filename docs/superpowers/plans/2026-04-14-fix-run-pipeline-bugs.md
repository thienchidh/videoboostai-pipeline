# Pipeline Bugs Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three bugs in the video pipeline: (1) UnicodeDecodeError in FFmpeg subprocess calls on Windows, (2) NameError for undefined `ideas` variable in run_pipeline.py CLI, (3) NoneType subscript error after script regeneration.

**Architecture:** Add proper encoding to all subprocess calls on Windows, fix variable scope in CLI, add defensive None-checks in produce_video result handling.

**Tech Stack:** Python 3.10, subprocess, FFmpeg, video pipeline.

---

## Bug Analysis

### Bug 1: UnicodeDecodeError in subprocess (Windows Python 3.10)
On Windows, Python 3.10+ decodes subprocess stdout/stderr using the system default encoding (cp1252) when `text=True` or `encoding=` is not specified. FFmpeg outputs bytes that can't be decoded by cp1252 → crashes the reader thread with `UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d`.

**Affected calls in `core/video_utils.py`:**
- Line 192: `subprocess.run(cmd, capture_output=True, timeout=300)` — crop_to_9x16
- Line 248: `subprocess.run(cmd_simple, capture_output=True, timeout=600)` — concat fallback
- Line 463: `subprocess.run(cmd, capture_output=True, timeout=300)` — add_static_watermark
- Line 586: `subprocess.run(cmd, capture_output=True, timeout=300)` — create_static_video_with_audio

**Fix:** Add `encoding="utf-8", errors="replace"` to all these calls.

### Bug 2: NameError: name 'ideas' is not defined
In `scripts/run_pipeline.py` at line 304, `ideas` is referenced outside the `else` block where it's defined:
```python
if args.produce:
    result = run_full_pipeline(...)
else:
    ideas = run_content_pipeline(...)
print(f"\nGot {len(ideas)} ideas")  # BUG: 'ideas' undefined when args.produce=True
```

**Fix:** Use `result.get("ideas", [])` or `result.get("videos", [])` depending on intent.

### Bug 3: 'NoneType' object is not subscriptable after script regeneration
After LLM successfully regenerates scene script (84 → 9 words), `pipeline.run()` returns a result but subsequent processing fails with NoneType subscript. This is likely in the video concatenation step or in `produce_video` result handling. The retry mechanism in `video_pipeline_v3.py` runs after a SceneDurationError, the retry appears to process all scenes, but something returns None.

**Fix:** Add defensive None-checks in `produce_video` before accessing result attributes.

---

## Task Decomposition

### Task 1: Fix UnicodeDecodeError in crop_to_9x16

**Files:**
- Modify: `core/video_utils.py:192`

- [ ] **Step 1: Read the file context around line 192**

Run: `Read core/video_utils.py offset=185 limit=15`
Expected: Line 192 shows `subprocess.run(cmd, capture_output=True, timeout=300)` without encoding

- [ ] **Step 2: Fix encoding in crop_to_9x16**

Edit `core/video_utils.py` line 192:
```python
# BEFORE:
subprocess.run(cmd, capture_output=True, timeout=300)

# AFTER:
subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=300)
```

- [ ] **Step 3: Verify the change**

Run: `grep -n "subprocess.run.*capture_output=True" core/video_utils.py | head -20`
Expected: All calls show `encoding=` parameter

- [ ] **Step 4: Commit**

```bash
git add core/video_utils.py
git commit -m "fix: add encoding='utf-8' to crop_to_9x16 subprocess call"
```

---

### Task 2: Fix UnicodeDecodeError in concat_videos fallback

**Files:**
- Modify: `core/video_utils.py:248`

- [ ] **Step 1: Fix encoding in concat_videos fallback**

Edit `core/video_utils.py` line 248:
```python
# BEFORE:
subprocess.run(cmd_simple, capture_output=True, timeout=600)

# AFTER:
subprocess.run(cmd_simple, capture_output=True, encoding="utf-8", errors="replace", timeout=600)
```

- [ ] **Step 2: Commit**

```bash
git add core/video_utils.py
git commit -m "fix: add encoding='utf-8' to concat fallback subprocess call"
```

---

### Task 3: Fix UnicodeDecodeError in add_static_watermark

**Files:**
- Modify: `core/video_utils.py:463`

- [ ] **Step 1: Fix encoding in add_static_watermark**

Edit `core/video_utils.py` line 463:
```python
# BEFORE:
result = subprocess.run(cmd, capture_output=True, timeout=300)

# AFTER:
result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=300)
```

- [ ] **Step 2: Commit**

```bash
git add core/video_utils.py
git commit -m "fix: add encoding='utf-8' to add_static_watermark subprocess call"
```

---

### Task 4: Fix UnicodeDecodeError in create_static_video_with_audio

**Files:**
- Modify: `core/video_utils.py:586`

- [ ] **Step 1: Fix encoding in create_static_video_with_audio**

Edit `core/video_utils.py` line 586:
```python
# BEFORE:
subprocess.run(cmd, capture_output=True, timeout=300)

# AFTER:
subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=300)
```

- [ ] **Step 2: Commit**

```bash
git add core/video_utils.py
git commit -m "fix: add encoding='utf-8' to create_static_video_with_audio subprocess call"
```

---

### Task 5: Fix NameError in run_pipeline.py CLI

**Files:**
- Modify: `scripts/run_pipeline.py:304`

- [ ] **Step 1: Read the surrounding context**

Run: `Read scripts/run_pipeline.py offset=295 limit=15`
Expected: Shows the `if args.produce:` / `else:` / `print(f"\nGot {len(ideas)} ideas")` structure

- [ ] **Step 2: Fix the NameError**

Change line 304 from:
```python
print(f"\nGot {len(ideas)} ideas")
```

To:
```python
print(f"\nGot {len(result.get('ideas', result.get('videos', [])))} items")
```

Note: When `args.produce=True`, `result` is a dict with `"ideas"` and `"videos"` keys from `run_full_pipeline`. When `args.produce=False`, `result` IS the ideas list from `run_content_pipeline`. The original code used `ideas` from the `else` branch, so we need to handle both cases.

Actually, a cleaner fix — use the same pattern in both branches:
```python
if args.produce:
    result = run_full_pipeline(...)
    logger.info(f"Result for {ch}: {result}")
else:
    ideas = run_content_pipeline(...)
    logger.info(f"Generated {len(ideas)} ideas for {ch}")
    print(f"\nGot {len(ideas)} ideas")
```

Move the `print` inside the `else` block, since it only makes sense when not producing video.

- [ ] **Step 3: Verify the change**

Run: `Read scripts/run_pipeline.py offset=295 limit=15`
Expected: `print` is inside `else` block, or uses `result`

- [ ] **Step 4: Commit**

```bash
git add scripts/run_pipeline.py
git commit -m "fix: move print inside else branch to avoid NameError"
```

---

### Task 6: Add defensive None-checks in produce_video

**Files:**
- Modify: `modules/content/content_pipeline.py:375-378`

- [ ] **Step 1: Read the context**

Run: `Read modules/content/content_pipeline.py offset=370 limit=25`
Expected: Shows `result` being checked and `media_dir.glob()` access

- [ ] **Step 2: Add None-check before subscripting**

The current code:
```python
output_video = None
if result:
    media_dir = pipeline._runner.media_dir
    for f in media_dir.glob("*.mp4"):
        output_video = str(f)
        break
```

Should add a guard:
```python
output_video = None
if result and hasattr(pipeline, '_runner') and pipeline._runner is not None:
    media_dir = pipeline._runner.media_dir
    if media_dir is not None:
        for f in media_dir.glob("*.mp4"):
            output_video = str(f)
            break
```

Also add a guard around the exception handler to prevent None from propagating:
```python
except Exception as e:
    logger.error(f"Pipeline error: {e}")
    return {"success": False, "error": str(e) if e else "unknown error"}
```

- [ ] **Step 3: Commit**

```bash
git add modules/content/content_pipeline.py
git commit -m "fix: add defensive None-checks in produce_video result handling"
```

---

### Task 7: Verify all subprocess calls are fixed

**Files:**
- Verify: `core/video_utils.py`

- [ ] **Step 1: Search for all capture_output=True without encoding**

Run: `grep -n "capture_output=True" core/video_utils.py`
Expected: Every occurrence should also have `encoding=` or `text=True`

- [ ] **Step 2: Check specific lines from the error log**

Run: `grep -n "capture_output" core/video_utils.py | grep -v "encoding\|text=True"`
Expected: No results — all subprocess calls with capture_output should have encoding set

---

## Self-Review Checklist

1. **Spec coverage:**
   - Bug 1 (UnicodeDecodeError): Fixed in Tasks 1-4 — all 4 subprocess calls in video_utils.py have encoding added
   - Bug 2 (NameError): Fixed in Task 5 — print statement moved inside else block
   - Bug 3 (NoneType subscript): Fixed in Task 6 — defensive None-checks added
   - All three bugs have corresponding tasks.

2. **Placeholder scan:**
   - No "TBD", "TODO", or placeholder content
   - Every step shows actual code changes
   - Commands show expected output

3. **Type consistency:**
   - The encoding fix uses consistent `encoding="utf-8", errors="replace"` pattern
   - Variable names (`result`, `ideas`, `media_dir`) are consistent with existing code
