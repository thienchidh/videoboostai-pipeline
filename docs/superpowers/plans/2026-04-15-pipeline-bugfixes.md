# Pipeline Bugfixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 8 real bugs found in the VideoBoostAI pipeline codebase.

**Architecture:** Each bug is fixed in isolation. Most are in `video_utils.py`, `pipeline_runner.py`, `scene_processor.py`, `pipeline_observer.py`, and `run_pipeline.py`.

**Tech Stack:** Python 3.12, subprocess/ffmpeg, sqlite3, threading, pytest

---

## File Structure

- `scripts/run_pipeline.py` — Bug 1: undefined variable
- `modules/pipeline/scene_processor.py` — Bug 2: deprecated Whisper flag
- `modules/media/tts.py` — Bug 2b: same Whisper flag
- `modules/pipeline/parallel_processor.py` — Bug 2c: same Whisper flag
- `core/video_utils.py` — Bug 3: resolution ignored, Bug 4: get_video_info error handling, Bug 5: music_provider None silent skip
- `modules/pipeline/pipeline_runner.py` — Bug 6: lipsync_cfg None, Bug 7: TTS return type docstring mismatch
- `modules/ops/pipeline_observer.py` — Bug 8: test thread pollution

---

## Task 1: Fix `run_content_pipeline()` undefined `config` variable

**Root Cause:** `scripts/run_pipeline.py` line 73 passes `config` to `ContentPipeline` but `config` is never defined in `run_content_pipeline()` — it should be `None`.

**Files:**
- Modify: `scripts/run_pipeline.py:73`

- [ ] **Step 1: Fix the undefined variable**

Change `config=config,` to `config=None,`

Run: `python -c "from scripts.run_pipeline import run_content_pipeline; print('import ok')"`
Expected: No NameError

- [ ] **Step 2: Run tests**

Run: `pytest tests/ -v --tb=short -k "content_pipeline or run_pipeline" 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add scripts/run_pipeline.py
git commit -m "fix: pass config=None in run_content_pipeline (was undefined variable)"
```

---

## Task 2: Fix Whisper deprecated `--word_timestamps True` flag (3 locations)

**Root Cause:** Whisper CLI changed from `--word_timestamps True` to `--word_timestamps` (no value). The deprecated form silently fails on newer whisper versions, causing empty word timestamps and broken karaoke subtitles.

**Files:**
- Modify: `modules/pipeline/scene_processor.py:129`
- Modify: `modules/media/tts.py:195`
- Modify: `modules/pipeline/parallel_processor.py:510`

- [ ] **Step 1: Fix scene_processor.py**

Change:
```python
[ str(get_whisper()), audio_path, "--model", "small", "--word_timestamps", "True",
```
To:
```python
[ str(get_whisper()), audio_path, "--model", "small", "--word_timestamps",
```

- [ ] **Step 2: Fix tts.py**

Same change at line 195.

- [ ] **Step 3: Fix parallel_processor.py**

Same change at line 510.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_scene_processor.py tests/test_tts.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/scene_processor.py modules/media/tts.py modules/pipeline/parallel_processor.py
git commit -m "fix: remove deprecated 'True' from whisper --word_timestamps flag"
```

---

## Task 3: Fix `create_static_video_with_audio` ignoring `resolution` parameter

**Root Cause:** `core/video_utils.py` has `res_map` that maps resolution names to dimensions, but the FFmpeg command at line ~579 uses hardcoded `1080:1920` instead of looking up from `res_map`. The `resolution` parameter is accepted but never used.

**Files:**
- Modify: `core/video_utils.py` (~line 570-590)

- [ ] **Step 1: Read the relevant section**

Run: `grep -n "create_static_video_with_audio\|res_map\|scale=" core/video_utils.py | head -20`

- [ ] **Step 2: Fix the FFmpeg command to use the resolution**

The `res_map` dict maps e.g. `"480p"` → `"854:480"`. The FFmpeg command should use `vf` filter with the resolved resolution instead of hardcoded `1080:1920`.

Change the FFmpeg command to look up from `res_map`:
```python
scale_filter = res_map.get(resolution, "1080:1920")
vf_arg = f"scale={scale_filter.replace(':', ':')},setsar=1"
```

And use `vf_arg` instead of the hardcoded scale in the filtergraph.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_video_utils.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add core/video_utils.py
git commit -m "fix: apply resolution param in create_static_video_with_audio"
```

---

## Task 4: Fix `get_video_info()` graceful error handling for missing streams

**Root Cause:** `core/video_utils.py` calls `info["streams"][0]` without checking if streams exist. If ffprobe returns no streams (malformed video or ffprobe error), this raises `IndexError`.

**Files:**
- Modify: `core/video_utils.py` (~line 48-67)

- [ ] **Step 1: Read get_video_info function**

Run: `sed -n '48,67p' core/video_utils.py`

- [ ] **Step 2: Add stream existence check**

After `info = json.loads(...)`, add:
```python
if not info.get("streams"):
    return None
```

And update the return type annotation to `-> tuple | None`.

- [ ] **Step 3: Update callers to handle None**

Find all callers: `grep -n "get_video_info(" core/video_utils.py modules/`

Wrap each call site to handle `None` return:
```python
info = get_video_info(video_path)
if info is None:
    log(f"⚠️ Could not read video info for {video_path}, using defaults")
    w, h, fps, duration = 1080, 1920, 30, 5.0
else:
    w, h, fps, duration = info
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_video_utils.py::TestGetVideoInfo -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/video_utils.py
git commit -m "fix: handle missing streams in get_video_info gracefully"
```

---

## Task 5: Fix `add_background_music()` silent skip when music_provider returns None

**Root Cause:** `core/video_utils.py` calls `music_provider.generate(...)` and if it returns `None`, the music addition is silently skipped without warning. There's no fallback to local `music_dir` when the provider fails.

**Files:**
- Modify: `core/video_utils.py` (~line 320-340)

- [ ] **Step 1: Read the music generation section**

Run: `sed -n '320,350p' core/video_utils.py`

- [ ] **Step 2: Add logging and fallback when generate returns None**

After `generated_music = music_provider.generate(...)`:
```python
if generated_music is None:
    logger.warning("⚠️ Music provider returned None, falling back to music_dir")
    music_file = _find_local_music(music_dir, music_duration) if music_dir else None
else:
    music_file = generated_music
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_video_utils.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add core/video_utils.py
git commit -m "fix: fallback to local music_dir when music_provider returns None"
```

---

## Task 6: Fix `lipsync_cfg` may be None causing AttributeError

**Root Cause:** `modules/pipeline/pipeline_runner.py` uses `or` chaining to pick lipsync config but if both `channel.lipsync` and `technical.generation.lipsync` are `None` or have missing attributes, accessing `lipsync_cfg.prompt` etc. will raise `AttributeError`.

**Files:**
- Modify: `modules/pipeline/pipeline_runner.py` (~line 262-273)

- [ ] **Step 1: Read lipsync_generate function**

Run: `sed -n '247,285p' modules/pipeline/pipeline_runner.py`

- [ ] **Step 2: Add None guard**

```python
lipsync_cfg = self.ctx.channel.lipsync if self.ctx.channel.lipsync else None
if not lipsync_cfg:
    lipsync_cfg = getattr(self.ctx.technical.generation, 'lipsync', None)

if not lipsync_cfg:
    log("⚠️ No lipsync config found, using static video fallback")
    # Fall through to static video creation
    return None
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_pipeline_runner.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add modules/pipeline/pipeline_runner.py
git commit -m "fix: guard against None lipsync_cfg in lipsync_generate"
```

---

## Task 7: Fix PipelineObserver thread TypeError in test context

**Root Cause:** `modules/ops/pipeline_observer.py` line 574 calls `sock.bind((self.host, actual_port))`. In test context, `self.host` is a `MagicMock` (from test mocking), causing `TypeError: str/bytes expected, not MagicMock`. The thread exception is unhandled and causes `PytestUnhandledThreadExceptionWarning`.

**Files:**
- Modify: `modules/ops/pipeline_observer.py` (~line 570-580)

- [ ] **Step 1: Read the _run_server method**

Run: `sed -n '560,590p' modules/ops/pipeline_observer.py`

- [ ] **Step 2: Add type guard before bind**

```python
if not isinstance(self.host, (str, bytes, bytearray)):
    log(f"⚠️ PipelineObserver: invalid host type {type(self.host)}, skipping server start")
    return
sock.bind((self.host, actual_port))
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_pipeline_observer.py -v --tb=short 2>&1 | tail -10`
Expected: PASS (no more thread exception warnings)

- [ ] **Step 4: Commit**

```bash
git add modules/ops/pipeline_observer.py
git commit -m "fix: guard against non-string host in PipelineObserver._run_server"
```

---

## Task 8: Remove dead code `return None` in video_pipeline_v3.py

**Root Cause:** `scripts/video_pipeline_v3.py` line 202 has `return None` that is unreachable — the for loop always either returns from inside, raises at max retries, or exits via exception.

**Files:**
- Modify: `scripts/video_pipeline_v3.py:202`

- [ ] **Step 1: Confirm the dead code**

Read lines 185-210 to trace all code paths through the for loop.

Paths through loop:
1. `run()` succeeds inside try → returns from inside loop → never reaches line 202
2. `SceneDurationError` and attempt < max_retries → continue → loop again
3. `SceneDurationError` and attempt >= max_retries → raises → never reaches line 202
4. Other exception → propagates → never reaches line 202

Conclusion: `return None` at line 202 is truly unreachable.

- [ ] **Step 2: Remove the dead code**

Delete `return None` at line 202.

- [ ] **Step 3: Run tests**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/video_pipeline_v3.py
git commit -m "fix: remove unreachable return None in VideoPipelineV3.run()"
```

---

## Verification

- [ ] **Step: Run full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -10`
Expected: ALL PASS (207+ passed)
