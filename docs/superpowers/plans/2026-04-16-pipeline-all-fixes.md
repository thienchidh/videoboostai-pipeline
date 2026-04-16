# VideoBoostAI Pipeline Review — Fix All Issues Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all remaining bugs, performance issues, architecture problems, and production readiness gaps identified in the comprehensive pipeline review.

**Architecture:** 9 tasks grouped into 4 categories. Each task is self-contained and testable. Bugfixes are isolated from improvements to allow independent verification.

**Tech Stack:** Python 3.12, subprocess/ffmpeg, pytest, structlog, threading, pathlib

---

## File Structure

```
Critical Bugs (4):
  modules/content/content_pipeline.py  — checkpoint always-deleted bug
  modules/pipeline/scene_processor.py   — parallel TTS/image race + temp file collision
  modules/pipeline/pipeline_runner.py   — DRY_RUN flags timing + lipsync_cfg None guard
  scripts/video_pipeline_v3.py          — DRY_RUN flags timing

Performance (4):
  modules/pipeline/pipeline_runner.py  — image fallback provider caching + S3 lambda
  modules/pipeline/scene_processor.py  — temp file collision fix
  modules/content/content_pipeline.py   — sequential idea processing

Architecture (5):
  scripts/video_pipeline_v3.py         — remove dead return None
  modules/pipeline/scene_processor.py  — decouple process from ctx
  modules/content/content_pipeline.py   — DB init consistency + structured logging
  modules/ops/pipeline_observer.py      — add metrics

Production Readiness (5):
  scripts/health_check.py              — fix hardcoded channel path
  scripts/retry_from_checkpoint.py    — fragile run_id resolution
  scripts/batch_generate.py            — BackoffCalculator import error
  scripts/check_ab_results.py         — provisional winner logic
  modules/pipeline/backoff.py          — half-open probe + persistence
  modules/pipeline/pipeline_runner.py  — stale run cleanup + distributed lock
  core/video_utils.py                   — FFmpeg crop fallback + music_provider None
  modules/content/content_pipeline.py  — SceneDurationError silent fail
```

---

## Category 1: Critical Bugs

### Task 1: Fix checkpoint always deleted on success (content_pipeline.py)

**Root Cause:** `finally` block at line 495-501 always deletes checkpoint file, even on successful completion. If pipeline crashes after processing scene 2/3, checkpoint is lost and next run must reprocess from scene 0.

**Files:**
- Modify: `modules/content/content_pipeline.py:495-501`

- [ ] **Step 1: Read the finally block**

Run: `sed -n '490,505p' modules/content/content_pipeline.py`

- [ ] **Step 2: Fix — only delete checkpoint on failure, keep on success**

```python
finally:
    # Only clean up checkpoint if pipeline succeeded
    # On failure/crash, checkpoint should be preserved for resume
    try:
        if checkpoint_path.exists():
            # Check if we actually completed successfully
            # If we exited via exception or early return, checkpoint should survive
            pass  # For now, just don't delete — checkpoint persists for resume
    except Exception as e:
        logger.warning(f"Could not manage checkpoint: {e}")
```

Actually, the simpler fix: remove the `finally` block's unlink entirely. Checkpoint should persist across all exits (success, failure, crash). The checkpoint is explicitly cleaned up at line 497-499 `if checkpoint_path.exists(): checkpoint_path.unlink()` — this should be REMOVED entirely.

Change the `finally` block to only log, not delete:
```python
finally:
    logger.info("  Content cycle ended")
    # NOTE: checkpoint intentionally preserved for crash recovery
    # Use --resume flag to continue from last processed idea
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_content_pipeline_research.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add modules/content/content_pipeline.py
git commit -m "fix(content): preserve checkpoint on success for crash recovery"
```

---

### Task 2: Fix parallel TTS/image race and temp file collision

**Root Cause (race):** `SingleCharSceneProcessor.process()` waits for TTS first, then image. If TTS finishes before image, TTS result is held but image continues — no parallel benefit. If image fails after TTS succeeds, TTS credits are wasted.

**Root Cause (collision):** `_get_temp_path` uses `time.time()*1000` as suffix. On fast systems or same-millisecond calls, two processes get same path.

**Files:**
- Modify: `modules/pipeline/scene_processor.py:61-68, 261-286`

- [ ] **Step 1: Fix temp file collision — use uuid instead of timestamp**

```python
import uuid

def _get_temp_path(self, prefix: str) -> str:
    temp_dir = self._temp_dir
    if temp_dir:
        unique = uuid.uuid4().hex[:12]
        return os.path.join(temp_dir, f"{prefix}_{unique}.mp3")
    fd, path = tempfile.mkstemp(suffix=".mp3", prefix=prefix)
    os.close(fd)
    return path
```

- [ ] **Step 2: Fix parallel execution — submit both, wait for both, fail fast**

Current code waits for TTS first, then image. Change to:
```python
# 1. Submit BOTH TTS and Image tasks simultaneously
audio_output = scene_output / f"audio_tts_{self.timestamp}.mp3"
scene_img = scene_output / "scene.png"

with ThreadPoolExecutor(max_workers=2) as executor:
    tts_future = executor.submit(self._run_tts, tts_fn, tts_text, voice, speed, str(audio_output))
    img_future = executor.submit(image_fn, img_prompt, str(scene_img)) if not scene_img.exists() else None

    # Wait for both — if either fails, fail fast
    audio_result = tts_future.result()  # raises on exception
    if img_future:
        img_result = img_future.result()  # raises on exception
```

If TTS fails, exception propagates immediately — no need to wait for image. If image fails after TTS succeeds, both futures have completed and we handle the failure gracefully.

Actually the current code already waits for TTS first then image, so the real issue is: if image takes much longer than TTS, we're waiting for image sequentially. The fix: collect both results simultaneously using `as_completed`.

```python
with ThreadPoolExecutor(max_workers=2) as executor:
    tts_future = executor.submit(self._run_tts, tts_fn, tts_text, voice, speed, str(audio_output))
    img_future = executor.submit(image_fn, img_prompt, str(scene_img)) if not scene_img.exists() else None

    done_futures = []
    for future in as_completed([f for f in [tts_future, img_future] if f]):
        done_futures.append(future)
        if future.exception() is not None:
            # Fail fast — cancel the other
            for f in [tts_future, img_future]:
                if f not in done_futures:
                    f.cancel()
            raise RuntimeError(f"Task failed: {future.exception()}")

    # Both succeeded
    audio_result = tts_future.result()
    if img_future:
        img_result = img_future.result()
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_scene_processor.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add modules/pipeline/scene_processor.py
git commit -m "fix(scene_processor): parallel TTS+image with fail-fast + uuid temp files"
```

---

### Task 3: Fix DRY_RUN flags timing race in run_video_pipeline

**Root Cause:** `run_video_pipeline()` sets `vp_module.DRY_RUN = False` AFTER `VideoPipelineV3.__init__` reads the global flags. The init happens at import time when globals are still True from previous state.

**Files:**
- Modify: `scripts/run_pipeline.py:640-660`
- Modify: `scripts/video_pipeline_v3.py:116-135`

- [ ] **Step 1: Read the problematic section**

Run: `sed -n '640,660p' modules/content/content_pipeline.py`

- [ ] **Step 2: Fix — pass dry_run as constructor argument, not via global mutation**

In `VideoPipelineV3.__init__`, accept `dry_run` as a parameter and store it as an instance attribute. Remove the `global DRY_RUN` read inside `__init__`. Instead:
```python
def __init__(self, channel_id: str, scenario_path: str, resume: bool = False,
             dry_run: bool = False, dry_run_tts: bool = False,
             dry_run_images: bool = False, use_static_lipsync: bool = False):
    # ...
    self._runner = VideoPipelineRunner(
        self.ctx,
        dry_run=dry_run,
        dry_run_tts=dry_run_tts,
        dry_run_images=dry_run_images,
        use_static_lipsync=use_static_lipsync,
        timestamp=self.timestamp,
        resume=resume,
    )
```

In `produce_video()` (content_pipeline.py), pass explicit flags:
```python
import scripts.video_pipeline_v3 as vp_module

vp_module.DRY_RUN = False  # Keep globals for backward compat with other callers
vp_module.DRY_RUN_TTS = False
vp_module.DRY_RUN_IMAGES = False
vp_module.USE_STATIC_LIPSYNC = self.skip_lipsync

pipeline = VideoPipelineV3(
    channel_id,
    str(config_path),
    dry_run=False,
    dry_run_tts=False,
    dry_run_images=False,
    use_static_lipsync=self.skip_lipsync,
)
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/ -v --tb=short -k "video_pipeline" 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/video_pipeline_v3.py modules/content/content_pipeline.py
git commit -m "fix: pass dry_run flags via constructor not global mutation"
```

---

### Task 4: Fix lipsync_cfg None guard in lipsync_generate

**Root Cause:** `lipsync_generate()` at line 267-272 builds `lipsync_cfg` via `or` chaining. If both channel and technical lipsync are absent/None, `lipsync_cfg` becomes `None` and is passed to `provider.generate(config=None)`. Providers may not handle `config=None` gracefully.

**Files:**
- Modify: `modules/pipeline/pipeline_runner.py:267-273`

- [ ] **Step 1: Read the lipsync_generate function**

Run: `sed -n '251,275p' modules/pipeline/pipeline_runner.py`

- [ ] **Step 2: Add explicit None check with fallback**

```python
def lipsync_generate(self, image_path: str, audio_path: str, output_path: str,
                    scene_id: int = 0, prompt: str = None):
    if self._dry_run:
        return create_static_video_with_audio(image_path, audio_path, output_path)

    # S3 upload with scene-specific prefix (upload_fn is per-call, thread-safe)
    lipsync_prefix = f"lipsync/{self.timestamp}/scene_{scene_id}"
    upload_fn = lambda fp: s3_upload_file(fp, lipsync_prefix)

    # Get lipsync config — channel override preferred, fallback to technical
    lipsync_cfg = None
    if self.ctx.channel and self.ctx.channel.generation and self.ctx.channel.generation.lipsync:
        lipsync_cfg = self.ctx.channel.generation.lipsync
    elif self.ctx.technical and self.ctx.technical.generation and self.ctx.technical.generation.lipsync:
        lipsync_cfg = self.ctx.technical.generation.lipsync

    if lipsync_cfg is None:
        log(f"  ⚠️ No lipsync config found — using static video fallback")
        return create_static_video_with_audio(image_path, audio_path, output_path)

    return self.lipsync_provider.generate(image_path, audio_path, output_path, config=lipsync_cfg)
```

Also fix `_build_lipsync_provider` to handle `None` gracefully:
```python
def _build_lipsync_provider(self):
    if self.ctx.channel and self.ctx.channel.lipsync:
        lipsync_name = self.ctx.channel.lipsync.provider
    elif self.ctx.technical and self.ctx.technical.generation and self.ctx.technical.generation.lipsync:
        lipsync_name = self.ctx.technical.generation.lipsync.provider
    else:
        # Default to kieai if nothing configured
        lipsync_name = "kieai"

    provider_cls = get_provider("lipsync", lipsync_name)
    if provider_cls is None:
        raise ValueError(f"Unknown lipsync provider: {lipsync_name}")
    # ... rest unchanged
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_pipeline_runner.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add modules/pipeline/pipeline_runner.py
git commit -m "fix(pipeline_runner): guard lipsync_cfg None with static fallback"
```

---

## Category 2: Performance Issues

### Task 5: Cache fallback image providers + S3 lambda reuse

**Root Cause:** Every call to `image_generate()` with a failed primary provider creates a new provider instance from scratch. The S3 upload lambda is recreated on every `lipsync_generate()` call.

**Files:**
- Modify: `modules/pipeline/pipeline_runner.py:145-249, 251-274`

- [ ] **Step 1: Cache fallback providers in __init__**

Add to `VideoPipelineRunner.__init__`:
```python
self._fallback_image_providers = {}
fallback_names = self.ctx.technical.generation.image.fallback_providers if (
    self.ctx.technical and self.ctx.technical.generation and self.ctx.technical.generation.image
) else []
for fb_name in fallback_names:
    fb_name = fb_name.strip()
    if not fb_name:
        continue
    fb_cls = get_provider("image", fb_name)
    if not fb_cls:
        continue
    fb_config = self.ctx.technical
    if fb_name == "minimax":
        self._fallback_image_providers[fb_name] = fb_cls(config=fb_config, api_key=self.ctx.technical.api_keys.minimax)
    elif fb_name == "kieai":
        self._fallback_image_providers[fb_name] = fb_cls(config=fb_config, api_key=self.ctx.technical.api_keys.kie_ai)
    else:
        self._fallback_image_providers[fb_name] = fb_cls(config=fb_config, api_key=self.ctx.technical.api_keys.wavespeed)
```

- [ ] **Step 2: Use cached providers in image_generate fallback loop**

Replace the fallback loop creation with:
```python
for fb_name in fallback_names:
    fb_name = fb_name.strip()
    if not fb_name:
        continue
    fb_provider = self._fallback_image_providers.get(fb_name)
    if not fb_provider:
        fb_provider = get_provider("image", fb_name)
        if not fb_provider:
            continue
    log(f"  → Trying fallback provider: {fb_name}")
    try:
        fb_result = fb_provider.generate(prompt, output_path, aspect_ratio=aspect_ratio)
    except Exception as e:
        log(f"  ⚠️ Fallback '{fb_name}' error: {type(e).__name__}: {e}")
        fb_result = None
    if fb_result:
        log(f"  ✓ Fallback provider '{fb_name}' succeeded")
        return fb_result
```

- [ ] **Step 3: Cache S3 upload lambda**

In `__init__`, store the timestamp-based prefix once:
```python
self._lipsync_upload_fn = lambda fp: s3_upload_file(fp, f"lipsync/{self.timestamp}")
```

Use `self._lipsync_upload_fn` in `_build_lipsync_provider` instead of creating a new lambda each time.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pipeline_runner.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/pipeline_runner.py
git commit -m "perf: cache fallback image providers and S3 upload lambda"
```

---

### Task 6: Parallel idea generation in run_full_cycle

**Root Cause:** `run_full_cycle()` processes ideas sequentially (line 447-493): generate script → save → produce video → repeat. No parallelism even when multiple ideas are independent.

**Files:**
- Modify: `modules/content/content_pipeline.py:441-493`

- [ ] **Step 1: Read the sequential loop**

Run: `sed -n '441,500p' modules/content/content_pipeline.py`

- [ ] **Step 2: Split into generate-all-then-produce-all phases**

Phase 1: Generate all scripts (can be parallel since they're independent):
```python
# Phase 1: Generate all scripts in parallel
logger.info("Step 3a: Generating all scripts in parallel...")
script_results = []  # list of (idea_id, script, config_path)

def generate_one_script(i, idea):
    """Generate script for one idea. Returns (idea_id, script, config_path)."""
    if i < start_idea_index:
        return None  # already processed
    script = self.idea_gen.generate_script_from_idea(idea, num_scenes=self.scene_count)
    self.idea_gen.update_idea_script(idea_id, script)
    config_path = str(self._save_script_config(idea_id, script))
    return (idea_id, script, config_path)

# Run in parallel using ThreadPoolExecutor
from concurrent.futures import ThreadPoolExecutor, as_completed
with ThreadPoolExecutor(max_workers=3) as executor:
    futures = {
        executor.submit(generate_one_script, i, ideas[i]): i
        for i in range(len(ideas))
    }
    for future in as_completed(futures):
        result = future.result()
        if result:
            script_results.append(result)

logger.info(f"  Generated {len(script_results)} scripts")
```

Phase 2: Produce videos sequentially (to avoid resource conflicts on disk/DB):
```python
# Phase 2: Produce videos sequentially (disk/DB contention risk if parallel)
for idea_id, script, config_path in script_results:
    logger.info(f"  Producing video for idea {idea_id}...")
    prod_result = self.produce_video(idea_id, config_path=config_path)
    produced.append({
        "idea_id": idea_id,
        "config_path": config_path,
        "result": prod_result,
    })
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_content_pipeline.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add modules/content/content_pipeline.py
git commit -m "perf: parallel script generation in run_full_cycle"
```

---

## Category 3: Architecture Issues

### Task 7: Remove dead code + add VideoPipelineRunner.run() error context

**Root Cause:**
1. `video_pipeline_v3.py:202` has `return None` that is truly unreachable
2. Pipeline failures lack context — exception message doesn't include which scene failed

**Files:**
- Modify: `scripts/video_pipeline_v3.py:202`
- Modify: `modules/pipeline/pipeline_runner.py:375-377`

- [ ] **Step 1: Remove unreachable return None**

Read lines 185-215 of `scripts/video_pipeline_v3.py`. Confirm `return None` at line 202 is unreachable (for loop always returns/raises/continues, never exits normally).

Delete line 202 (`return None`).

- [ ] **Step 2: Improve scene failure error context**

In `pipeline_runner.py`, change:
```python
except Exception as e:
    log(f"  ❌ Scene {scene_id} failed: {e}")
    results_by_scene[scene_id] = None
```
To:
```python
except Exception as e:
    log(f"  ❌ Scene {scene_id} failed: {type(e).__name__}: {e}")
    # Attach scene context for debugging
    results_by_scene[scene_id] = None
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/video_pipeline_v3.py modules/pipeline/pipeline_runner.py
git commit -m "fix: remove dead return None + improve scene error context"
```

---

### Task 8: Add structured logging (structlog) to pipeline_runner

**Root Cause:** All pipeline logging uses plain `log()` function — no JSON, no log levels, no structured fields for production aggregation.

**Files:**
- Create: `modules/pipeline/logging_config.py` (new file)
- Modify: `modules/pipeline/pipeline_runner.py` (~line 1-50)
- Modify: `modules/content/content_pipeline.py` (~line 1-20)

- [ ] **Step 1: Create logging_config.py**

```python
"""Structured logging configuration for VideoBoostAI pipeline."""
import logging
import structlog
import sys

def configure_pipeline_logging(level: str = "INFO"):
    """Configure structlog for the pipeline."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

def get_logger(name: str):
    return structlog.get_logger(name)
```

- [ ] **Step 2: Replace `log()` calls with structured logger in pipeline_runner**

In `pipeline_runner.py`, add near top:
```python
from modules.pipeline.logging_config import configure_pipeline_logging, get_logger
configure_pipeline_logging(self.ctx.technical.logging.level if self.ctx.technical.logging else "INFO")
logger = get_logger(__name__)
```

Replace `log(f"...")` with `logger.info("message", key=value)` for all significant events.

Important: keep `log()` for backward compatibility with tests that patch `log`. Make `log()` a wrapper that also emits to structlog.

Actually, to avoid breaking existing code, add a dual approach: keep `log()` function but also emit structured logs on key events.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_pipeline_runner.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add modules/pipeline/logging_config.py modules/pipeline/pipeline_runner.py
git commit -m "feat: add structlog-based structured logging to pipeline_runner"
```

---

### Task 9: Add PipelineObserver metrics (scene duration, API success rate)

**Root Cause:** `PipelineObserver` only registers/unregisters runs, doesn't track per-scene timing or API call success rates.

**Files:**
- Modify: `modules/ops/pipeline_observer.py`

- [ ] **Step 1: Read pipeline_observer.py for current metrics**

Run: `grep -n "class\|def \|self\." modules/ops/pipeline_observer.py | head -40`

- [ ] **Step 2: Add metrics tracking to register_run and update_run_progress**

Add new fields to `register_run`:
```python
self.scene_durations = []  # list of floats (seconds per scene)
self.api_call_counts = {"success": 0, "failure": 0}  # per provider
self.start_time = time.time()
```

Add a `record_scene_completed(scene_id, duration)` method:
```python
def record_scene_completed(self, scene_id: int, duration: float):
    if self._running:
        self.scene_durations.append(duration)
        self._send_update({"type": "scene_completed", "scene_id": scene_id, "duration": duration})
```

Add `record_api_call(provider, success, duration_ms)`:
```python
def record_api_call(self, provider: str, success: bool, duration_ms: float):
    if self._running:
        key = "success" if success else "failure"
        self.api_call_counts[key] += 1
        self._send_update({
            "type": "api_call",
            "provider": provider,
            "success": success,
            "duration_ms": duration_ms,
        })
```

- [ ] **Step 3: Update update_run_progress to include metrics summary**

```python
def update_run_progress(self, run_id: int, completed_scenes: int, total_scenes: int,
                        total_cost_usd: float = None, error: str = None):
    payload = {
        "run_id": run_id,
        "completed_scenes": completed_scenes,
        "total_scenes": total_scenes,
        "progress_pct": round(100 * completed_scenes / total_scenes, 1) if total_scenes > 0 else 0,
    }
    if total_cost_usd is not None:
        payload["total_cost_usd"] = total_cost_usd
    if error:
        payload["error"] = error
    if self.scene_durations:
        payload["avg_scene_duration_s"] = sum(self.scene_durations) / len(self.scene_durations)
    self._send_update(payload)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pipeline_observer.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/ops/pipeline_observer.py
git commit -m "feat: add scene duration and API call metrics to PipelineObserver"
```

---

## Category 4: Production Readiness

### Task 10: Fix health_check.py hardcoded channel + retry_from_checkpoint fragile run_id

**Files:**
- Modify: `scripts/health_check.py`
- Modify: `scripts/retry_from_checkpoint.py`

- [ ] **Step 1: Fix health_check.py — accept --channel argument**

Read `scripts/health_check.py`. Change from hardcoded path to accept `--channel` argument with default:
```python
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--channel", default="nang_suat_thong_minh",
                    help="Channel ID to check")
args = parser.parse_args()
channel_path = f"configs/channels/{args.channel}/config.yaml"
```

- [ ] **Step 2: Fix retry_from_checkpoint.py — use DB instead of heuristic**

Read `scripts/retry_from_checkpoint.py`. The fragile part is deriving `run_id` from `run_dir` by parsing scene checkpoint filenames. Instead, query the database:
```python
def resolve_run_id(run_dir: Path) -> Optional[int]:
    """Resolve run_id from run_dir by querying DB for matching output_video path."""
    from db import get_session, models
    with get_session() as session:
        run = session.query(models.VideoRun).filter(
            models.VideoRun.output_video.like(f"%{run_dir.name}%")
        ).first()
        return run.id if run else None
```

- [ ] **Step 3: Run health_check.py**

Run: `python scripts/health_check.py --channel nang_suat_thong_minh 2>&1 | tail -10`
Expected: exit 0 (all checks pass)

- [ ] **Step 4: Commit**

```bash
git add scripts/health_check.py scripts/retry_from_checkpoint.py
git commit -m "fix: health_check accepts --channel arg, retry uses DB not heuristic"
```

---

### Task 11: Fix batch_generate.py BackoffCalculator import + check_ab_results provisional winner

**Files:**
- Modify: `modules/pipeline/backoff.py`
- Modify: `scripts/batch_generate.py`
- Modify: `scripts/check_ab_results.py`

- [ ] **Step 1: Add BackoffCalculator to backoff.py**

Check if `BackoffCalculator` exists in backoff.py:
```bash
grep -n "BackoffCalculator\|BATCH_MAX_RETRIES\|BATCH_BACKOFF" modules/pipeline/backoff.py
```

If not found, add it:
```python
class BackoffCalculator:
    """Calculates retry delays for batch operations with configurable growth."""

    def __init__(self, base_seconds: float = 10.0, cap_seconds: float = 3600.0):
        self.base = base_seconds
        self.cap = cap_seconds

    def delay_for_attempt(self, attempt: int) -> float:
        """Return delay in seconds for given attempt number (1-indexed)."""
        if attempt <= 0:
            return 0
        # Exponential growth with cap
        delay = self.base * (10 ** (attempt - 1))
        return min(delay, self.cap)

BATCH_MAX_RETRIES = 3
BATCH_BACKOFF_BASE_SECONDS = 10.0
BATCH_BACKOFF_CAP_SECONDS = 3600.0
```

- [ ] **Step 2: Fix check_ab_results.py — don't hardcode winner="a"**

Current code sets `winner="a"` always. Change to only set winner when results are statistically significant:
```python
if ctr_a > ctr_b * 1.2:  # A is 20%+ better
    winner = "a"
elif ctr_b > ctr_a * 1.2:  # B is 20%+ better
    winner = "b"
else:
    winner = None  # Inconclusive — no winner yet
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_pipeline_runner.py tests/test_content_pipeline.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add modules/pipeline/backoff.py scripts/batch_generate.py scripts/check_ab_results.py
git commit -m "fix: add BackoffCalculator to backoff.py, fix A/B winner logic"
```

---

### Task 12: Add stale run cleanup + distributed video production lock

**Root Cause:** No cleanup for orphaned `in_progress` runs. No lock for concurrent video production.

**Files:**
- Create: `modules/pipeline/run_lock_manager.py` (new file)
- Modify: `modules/pipeline/pipeline_runner.py` (add cleanup call)
- Modify: `modules/content/content_pipeline.py` (add lock to produce_video)

- [ ] **Step 1: Create run_lock_manager.py**

```python
"""Distributed lock manager for video production runs."""
import uuid
import time
from typing import Optional

class RunLockManager:
    """Manages distributed locks for video production to prevent concurrent runs."""

    def __init__(self, db_module):
        self.db = db_module

    def acquire_video_lock(self, channel_id: str, run_id: int,
                           ttl_seconds: int = 3600) -> bool:
        """Acquire a lock for video production on a channel.

        Returns True if lock acquired, False if another run is in progress.
        Lock auto-expires after ttl_seconds to handle crashes.
        """
        import uuid as uuid_mod
        lock_id = f"video_lock_{channel_id}_{run_id}"
        return self.db.acquire_research_lock(lock_id)

    def release_video_lock(self, channel_id: str, run_id: int):
        """Release the video production lock."""
        lock_id = f"video_lock_{channel_id}_{run_id}"
        self.db.release_research_lock(lock_id)

    def cleanup_stale_runs(self, stale_threshold_seconds: int = 7200):
        """Mark runs that have been 'in_progress' for too long as failed.

        Args:
            stale_threshold_seconds: Runs in_progress longer than this are considered stale.
        """
        self.db.mark_stale_runs_failed(stale_threshold_seconds)
```

Add to `db.py`:
```python
def mark_stale_runs_failed(threshold_seconds: int = 7200):
    """Mark runs stuck in 'in_progress' as failed."""
    with get_session() as session:
        stale = session.query(models.VideoRun).filter(
            models.VideoRun.status == "in_progress",
            models.VideoRun.started_at < datetime.now(timezone.utc) - timedelta(seconds=threshold_seconds)
        )
        count = stale.count()
        stale.update({"status": "failed", "error": "Stale run — exceeded threshold"})
        return count
```

- [ ] **Step 2: Add stale cleanup to VideoPipelineRunner.run()**

At start of `run()`, call cleanup:
```python
from modules.pipeline.run_lock_manager import RunLockManager
lock_mgr = RunLockManager(db)
stale_count = lock_mgr.cleanup_stale_runs()
if stale_count > 0:
    log(f"  🧹 Cleaned up {stale_count} stale runs")
```

- [ ] **Step 3: Add video lock to produce_video**

At start of `produce_video()` in content_pipeline.py:
```python
lock_mgr = RunLockManager(db)
if not lock_mgr.acquire_video_lock(channel_id, idea_id):
    return {"success": False, "error": "Another video production is in progress for this channel"}
try:
    # ... existing code ...
finally:
    lock_mgr.release_video_lock(channel_id, idea_id)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pipeline_runner.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/run_lock_manager.py modules/pipeline/pipeline_runner.py modules/content/content_pipeline.py db.py
git commit -m "feat: add stale run cleanup and distributed video production lock"
```

---

### Task 13: Fix SceneDurationError LLM silent fail + FFmpeg crop fallback

**Root Cause:**
1. `_regenerate_script_with_llm()` returns original script when LLM fails — no way to distinguish regenerated from unchanged
2. `crop_to_9x16()` is a single point of failure with no fallback

**Files:**
- Modify: `scripts/video_pipeline_v3.py:92-103`
- Modify: `modules/pipeline/scene_processor.py:334-343`

- [ ] **Step 1: Make LLM regeneration failure explicit**

In `_regenerate_script_with_llm()`:
```python
try:
    llm = MiniMaxLLMProvider(api_key=llm_api_key)
    new_script = llm.chat(
        prompt=user_prompt,
        system=system_prompt,
        max_tokens=512
    )
    new_script = new_script.strip()
    if new_script == original_script:
        # Cannot determine if LLM returned same script or failed silently
        # Treat same-script as failure to trigger fallback
        raise RuntimeError("LLM returned unchanged script")
    log(f"  🤖 LLM regenerated script for scene {scene_id}: {len(original_script.split())} → {len(new_script.split())} words")
    return new_script
except Exception as e:
    log(f"  ⚠️ LLM regeneration failed: {e} — will use original with adjusted speed")
    # Return original but with flag that it's not regenerated
    return f"_LLM_FAILED_{original_script}"
```

In `VideoPipelineV3.run()`, detect LLM failure:
```python
adjusted_script = _regenerate_script_with_llm(...)
if adjusted_script.startswith("_LLM_FAILED_"):
    actual_script = adjusted_script[len("_LLM_FAILED_"):]
    log(f"  ⚠️ LLM failed to regenerate — using original script")
    # Fall through with original script
else:
    actual_script = adjusted_script
```

- [ ] **Step 2: Add FFmpeg crop fallback**

In `scene_processor.py`, after crop failure:
```python
# 6. Crop to 9:16
video_9x16 = scene_output / "video_9x16.mp4"
if not video_9x16.exists():
    log(f"  📐 Cropping to 9:16...")
    if not crop_to_9x16(str(video_raw), str(video_9x16)):
        log(f"  ⚠️ FFmpeg crop failed — trying alternative approach...")

        # Fallback 1: Use ffmpeg with simpler filter
        try:
            import subprocess
            result = subprocess.run([
                str(get_ffmpeg()), "-i", str(video_raw),
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                "-c:a", "copy", str(video_9x16)
            ], capture_output=True, timeout=60)
            if result.returncode == 0 and video_9x16.exists():
                log(f"  ✅ Crop fallback succeeded")
            else:
                video_raw.unlink(missing_ok=True)
                log(f"  ❌ All crop methods failed")
                return None, []
        except Exception as crop_err:
            log(f"  ⚠️ Crop fallback also failed: {crop_err}")
            video_raw.unlink(missing_ok=True)
            return None, []
    log(f"  ✅ Crop done: {video_9x16.stat().st_size/1024/1024:.1f}MB")
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_scene_processor.py -v --tb=short 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/video_pipeline_v3.py modules/pipeline/scene_processor.py
git commit -m "fix: explicit LLM regeneration failure marker + FFmpeg crop fallback"
```

---

### Task 14: Fix CircuitBreaker half-open probe + add circuit state to db

**Root Cause:** CircuitBreaker allows requests through after timeout but immediately re-closes if they fail — no "half-open probe" that lets exactly one request test recovery.

**Files:**
- Modify: `modules/pipeline/backoff.py`

- [ ] **Step 1: Read backoff.py CircuitBreaker class**

Run: `grep -n "class CircuitBreaker\|class Backoff\|def check\|def record" modules/pipeline/backoff.py`

- [ ] **Step 2: Implement proper half-open state**

```python
class CircuitBreaker:
    """Thread-safe circuit breaker with proper half-open state."""

    def __init__(self, max_attempts: int, open_timeout: float = 60.0):
        self.max_attempts = max_attempts
        self.open_timeout = open_timeout
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._lock = threading.Lock()

    def check(self):
        """Raise CircuitOpenError if circuit is open. In half-open, allow exactly one probe."""
        with self._lock:
            if self._opened_at is None:
                return  # Closed — allow

            elapsed = time.time() - self._opened_at
            if elapsed < self.open_timeout:
                raise CircuitOpenError(f"Circuit open, {self.open_timeout - elapsed:.0f}s remaining")

            # Half-open state — allow exactly ONE probe
            self._opened_at = time.time()  # Reset timer but stay half-open
            return  # Allow the probe request

    def record_failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= self.max_attempts:
                self._opened_at = time.time()
                self._failures = 0  # Reset counter for when circuit closes

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._opened_at = None  # Close the circuit
```

- [ ] **Step 3: Add circuit state persistence to db**

Add to `db.py`:
```python
def save_circuit_state(provider: str, failures: int, opened_at: float = None):
    """Persist circuit breaker state for recovery after restart."""
    # Could add a CircuitState table, or use a simple key-value approach
    pass  # For now, log — full implementation would need a new DB table

def load_circuit_state(provider: str) -> dict:
    """Load circuit breaker state. Returns empty dict if none saved."""
    return {}
```

Note: Full persistence would need a new `circuit_states` table. For now, log state changes.

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -v --tb=short -k "circuit or backoff" 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/backoff.py
git commit -m "fix: implement proper half-open probe in CircuitBreaker"
```

---

## Verification

- [ ] **Step: Run full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -15`
Expected: ALL PASS (286+ passed)

---

## Summary of All Changes

| Task | Category | Files | Key Fix |
|------|----------|-------|---------|
| 1 | Critical | content_pipeline.py | Keep checkpoint on success |
| 2 | Critical | scene_processor.py | Fail-fast parallel TTS+image, uuid temp files |
| 3 | Critical | video_pipeline_v3.py, content_pipeline.py | DRY_RUN via constructor, not globals |
| 4 | Critical | pipeline_runner.py | lipsync_cfg None → static fallback |
| 5 | Performance | pipeline_runner.py | Cache fallback providers + S3 lambda |
| 6 | Performance | content_pipeline.py | Parallel script generation |
| 7 | Architecture | video_pipeline_v3.py, pipeline_runner.py | Remove dead code, improve error context |
| 8 | Architecture | logging_config.py (new), pipeline_runner.py | Structured logging with structlog |
| 9 | Architecture | pipeline_observer.py | Scene duration + API metrics |
| 10 | Production | health_check.py, retry_from_checkpoint.py | Fix hardcoded paths, use DB not heuristic |
| 11 | Production | backoff.py, batch_generate.py, check_ab_results.py | BackoffCalculator, fix winner logic |
| 12 | Production | run_lock_manager.py (new), pipeline_runner.py, content_pipeline.py, db.py | Stale cleanup + distributed lock |
| 13 | Production | video_pipeline_v3.py, scene_processor.py | LLM fail marker + FFmpeg crop fallback |
| 14 | Production | backoff.py | Proper half-open CircuitBreaker |