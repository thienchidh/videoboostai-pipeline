# Skip Image + Skip Lipsync Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--skip-image` CLI flag + `skip_image` parameter so the pipeline runs: TTS → static video (no image gen, no lipsync) → subtitles → concat → watermark.

**Architecture:** Add `skip_image` parameter through the call chain: CLI arg → `run_full_pipeline()` → `ContentPipeline` → `VideoPipelineV3` → `ParallelSceneProcessor` → `_phase2_image_gen()` returns placeholder image path → `_phase3_lipsync()` uses `create_static_video_with_audio` directly without lipsync call.

**Tech Stack:** Python, ffmpeg, VideoBoostAI pipeline (run_pipeline.py, parallel_processor.py)

---

## File Structure

```
scripts/run_pipeline.py                    # Add --skip-image CLI arg, pass to run_full_pipeline()
scripts/video_pipeline_v3.py               # Add skip_image param to VideoPipelineV3.__init__, set USE_STATIC_LIPSYNC + SKIP_IMAGE flag
modules/content/content_pipeline.py        # Add skip_image param, propagate to VideoPipelineV3
modules/pipeline/parallel_processor.py     # Add skip_image to ParallelSceneProcessor; Phase 2 returns placeholder image; Phase 3 skips lipsync call entirely and uses static directly
modules/pipeline/scene_processor.py         # Add skip_image param to SceneProcessor (for non-parallel path)
```

---

## Task 1: Add `skip_image` to `ParallelSceneProcessor`

**Files:**
- Modify: `modules/pipeline/parallel_processor.py:55-61` (constructor)
- Modify: `modules/pipeline/parallel_processor.py:224-288` (`_phase2_image_gen`)
- Modify: `modules/pipeline/parallel_processor.py:290-409` (`_phase3_lipsync`)

- [ ] **Step 1: Write the failing test**

In `tests/test_parallel_processor.py` (create if not exists):

```python
def test_skip_image_uses_placeholder_image():
    """When skip_image=True, phase 2 returns a placeholder image path."""
    # Setup: create a temp run_dir with a placeholder image file
    import tempfile, shutil
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    placeholder = tmp / "placeholder_scene.png"
    placeholder.write_text("fake png")

    # Mock context and processor with skip_image=True
    from unittest.mock import MagicMock
    from modules.pipeline.parallel_processor import ParallelSceneProcessor

    ctx = MagicMock()
    ctx.channel.tts.min_duration = 1.0
    ctx.channel.tts.max_duration = 30.0
    proc = ParallelSceneProcessor(ctx, tmp, max_workers=2, skip_image=True)

    # Call _phase2_image_gen with a mock image_fn
    scenes = [{"id": 1, "characters": ["TestChar"]}]

    def fake_image_fn(prompt, path):
        return None  # Should not be called when skip_image=True

    results = proc._phase2_image_gen(scenes, fake_image_fn)
    # Result for scene 1 should have image_path pointing to placeholder (not calling image_fn)
    assert results[1]["image_path"] == str(placeholder), f"Expected placeholder path, got {results[1]['image_path']}"

    shutil.rmtree(tmp)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parallel_processor.py::test_skip_image_uses_placeholder_image -v`
Expected: FAIL — `ParallelSceneProcessor.__init__() got an unexpected keyword argument 'skip_image'`

- [ ] **Step 3: Add `skip_image` to ParallelSceneProcessor constructor**

In `modules/pipeline/parallel_processor.py:55-61`, add:

```python
def __init__(self, ctx: PipelineContext, run_dir: Path, max_workers: int = 3,
             checkpoint_helper=None, skip_image: bool = False):
    # ... existing init lines 55-61 ...
    self.skip_image = skip_image
```

- [ ] **Step 4: Run test to verify it fails (different error)**

Run: `pytest tests/test_parallel_processor.py::test_skip_image_uses_placeholder_image -v`
Expected: FAIL — `TypeError: _phase2_image_gen() missing required argument: 'image_fn'`

- [ ] **Step 5: Update `_phase2_image_gen` to handle skip_image**

In `modules/pipeline/parallel_processor.py:224-288`, replace `_phase2_image_gen` with:

```python
def _phase2_image_gen(self, scenes: List[Dict[str, Any]],
                       image_fn, save_checkpoints: bool = False) -> Dict[int, Dict[str, Any]]:
    """Generate images for all scenes in parallel (runs after Phase 1).

    When skip_image=True, returns a placeholder image path for every scene
    without calling image_fn.

    Returns:
        {scene_id: {"image_path": str, "gender": str, "prompt": str}}
    """
    if self.skip_image:
        log(f"\n  🎨 Phase 2: SKIPPED (skip_image=True) — using placeholder image for {len(scenes)} scenes")
        results = {}
        for scene in scenes:
            scene_id = scene.get("id") or 0
            chars = scene.get("characters") or []
            if chars:
                char_name = chars[0].name if isinstance(chars[0], SceneCharacter) else chars[0]
                char_cfg = self._get_character(char_name)
                _, _, _, gender = self._resolve_voice(char_cfg, scene) if char_cfg else ("minimax", "t2a-02", 1.0, "female")
            else:
                gender = "female"
            prompt = self._get_video_prompt(scene)
            scene_output = self.run_dir / f"scene_{scene_id}"
            scene_output.mkdir(parents=True, exist_ok=True)
            placeholder_img = scene_output / "scene.png"
            # Create placeholder if not exists (1x1 transparent PNG via ffmpeg)
            if not placeholder_img.exists():
                subprocess.run([
                    str(get_ffmpeg()),
                    "-f", "lavfi", "-i", "color=c=black:s=512x512:d=1",
                    "-frames:v", "1", str(placeholder_img)
                ], capture_output=True)
            results[scene_id] = {"image_path": str(placeholder_img), "gender": gender, "prompt": prompt}
        return results

    log(f"\n  🎨 Phase 2: Image gen for {len(scenes)} scenes in parallel (workers={self.max_workers})")
    # ... rest of existing implementation (lines 231-288) ...
```

- [ ] **Step 6: Update `_phase3_lipsync` to handle skip_image (skip lipsync call entirely)**

In `modules/pipeline/parallel_processor.py:356-386`, replace the lipsync step:

```python
            # ── Lipsync step ────────────────────────────────────
            if not video_raw.exists():
                if self.checkpoint and self.checkpoint.is_step_done(scene_id, STEP_LIPSYNC):
                    if video_raw.exists():
                        log(f"  ⏭  Lipsync scene_{scene_id} (checkpoint) - skipping")
                    else:
                        self.checkpoint.clear(scene_id)  # stale

                if self.skip_image:
                    # No image gen + no lipsync → create static video directly from placeholder
                    log(f"  🎬 Static video (skip_image=True) scene_{scene_id}...")
                    lipsync_result = create_static_video_with_audio(
                        image_path, audio_path, str(video_raw)
                    )
                else:
                    log(f"  🎬 Lipsync scene_{scene_id}...")
                    try:
                        lipsync_result = lipsync_fn(image_path, audio_path, str(video_raw),
                                                    scene_id=scene_id, prompt=prompt)
                    except LipsyncQuotaError as e:
                        log(f"  ⚠️ Lipsync quota exceeded: {e} — fallback to static")
                        lipsync_result = None

                    if not lipsync_result:
                        log(f"  ⚠️ Lipsync failed — fallback to static image + audio")
                        lipsync_result = create_static_video_with_audio(image_path, audio_path, str(video_raw))

                if not lipsync_result:
                    log(f"  ❌ Lipsync + static fallback both failed for scene_{scene_id}")
                    results[scene_id] = {"video_path": None, "timestamps": tts_data.get("timestamps", [])}
                    continue

                if save_checkpoints and self.checkpoint:
                    self.checkpoint.save_step(scene_id, STEP_LIPSYNC, str(video_raw))
                log(f"  ✅ Lipsync done: {video_raw.stat().st_size/1024/1024:.1f}MB")
            else:
                log(f"  ⏭  Lipsync scene_{scene_id} (cached) - skipping")
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_parallel_processor.py::test_skip_image_uses_placeholder_image -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add modules/pipeline/parallel_processor.py tests/test_parallel_processor.py
git commit -m "feat(parallel_processor): add skip_image mode for static-only video generation"
```

---

## Task 2: Add `skip_image` to `SceneProcessor`

**Files:**
- Modify: `modules/pipeline/scene_processor.py:40-46` (constructor)
- Modify: `modules/pipeline/scene_processor.py:process_scene()` (around line 140+ — find the image gen call)

- [ ] **Step 1: Write the failing test**

```python
def test_scene_processor_skip_image():
    """SceneProcessor with skip_image=True skips image generation and uses placeholder."""
    from unittest.mock import MagicMock
    from pathlib import Path
    import tempfile, shutil

    tmp = Path(tempfile.mkdtemp())

    ctx = MagicMock()
    ctx.channel.tts.min_duration = 1.0
    ctx.channel.tts.max_duration = 30.0
    ctx.channel.characters = []
    ctx.channel.voices = []

    from modules.pipeline.scene_processor import SceneProcessor
    proc = SceneProcessor(ctx, tmp, resume=False, skip_image=True)

    # Verify skip_image is set
    assert proc.skip_image == True

    shutil.rmtree(tmp)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scene_processor.py::test_scene_processor_skip_image -v`
Expected: FAIL — `TypeError: SceneProcessor.__init__() got an unexpected keyword argument 'skip_image'`

- [ ] **Step 3: Add `skip_image` to SceneProcessor constructor**

In `modules/pipeline/scene_processor.py:40-46`, update:

```python
    def __init__(self, ctx: PipelineContext, run_dir: Path, resume: bool = False, skip_image: bool = False):
        self.ctx = ctx
        self.run_dir = run_dir
        self.resume = resume
        self.project_root = PROJECT_ROOT
        self.timestamp = int(time.time())
        # Read max_workers from config (strict: require key to exist)
        max_workers = ctx.technical.generation.parallel_scene_processing.max_workers
        self.max_workers = max_workers
        self.skip_image = skip_image
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scene_processor.py::test_scene_processor_skip_image -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/scene_processor.py tests/test_scene_processor.py
git commit -m "feat(scene_processor): add skip_image parameter"
```

---

## Task 3: Add `skip_image` to `VideoPipelineV3` and propagate through call chain

**Files:**
- Modify: `scripts/video_pipeline_v3.py` — add `use_static_lipsync` + new `skip_image` param
- Modify: `modules/content/content_pipeline.py` — add `skip_image` param, pass to VideoPipelineV3
- Modify: `scripts/run_pipeline.py` — add `--skip-image` CLI arg

- [ ] **Step 1: Write the failing test (propagation test)**

In `tests/test_video_pipeline_v3.py`, add:

```python
def test_video_pipeline_v3_skip_image_attr():
    """VideoPipelineV3 accepts skip_image and passes to ParallelSceneProcessor."""
    import tempfile, shutil
    from pathlib import Path

    # Create minimal YAML scenario for testing
    tmp = Path(tempfile.mkdtemp())
    scenario_yaml = tmp / "test_scenario.yaml"
    scenario_yaml.write_text("""
title: Test Skip Image
scenes:
  - id: 1
    tts_text: "Hello world"
    duration: 5
    characters:
      - name: TestChar
        voice_id: default
""")

    # Patch all external calls
    with patch('scripts.video_pipeline_v3.VideoPipelineV3._init_providers'), \
         patch('scripts.video_pipeline_v3.VideoPipelineV3._load_scenario'), \
         patch.object(VideoPipelineV3, 'run', return_value=None):

        vp = VideoPipelineV3("test_channel", str(scenario_yaml), skip_image=True)
        assert vp.skip_image == True

    shutil.rmtree(tmp)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_video_pipeline_v3.py::test_video_pipeline_v3_skip_image_attr -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'skip_image'`

- [ ] **Step 3: Add `skip_image` to VideoPipelineV3.__init__**

Read `scripts/video_pipeline_v3.py` `__init__` method (around line 50-90), then add `skip_image=False` parameter and store it:

```python
def __init__(self, channel_id: str, scenario_path: str,
             dry_run: bool = False, dry_run_tts: bool = False,
             dry_run_images: bool = False,
             resume: bool = False,
             use_static_lipsync: bool = False,
             skip_image: bool = False):
    # ... existing init (set USE_STATIC_LIPSYNC, DRY_RUN, etc.) ...
    self.skip_image = skip_image
```

- [ ] **Step 4: Pass `skip_image` to `ParallelSceneProcessor` instantiation**

Find where `ParallelSceneProcessor` is instantiated in `VideoPipelineV3` (likely in `_run_pipeline()` or similar), and add:

```python
self._parallel_processor = ParallelSceneProcessor(
    self.ctx, self.run_dir,
    max_workers=max_workers,
    checkpoint_helper=cp,
    skip_image=self.skip_image,  # NEW
)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_video_pipeline_v3.py::test_video_pipeline_v3_skip_image_attr -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/video_pipeline_v3.py tests/test_video_pipeline_v3.py
git commit -m "feat(video_pipeline_v3): add skip_image param and propagate to ParallelSceneProcessor"
```

---

## Task 4: Add `skip_image` to `ContentPipeline` and `run_full_pipeline`

**Files:**
- Modify: `modules/content/content_pipeline.py` — `__init__` + `produce_video()` call
- Modify: `scripts/run_pipeline.py` — add `--skip-image` arg + pass to functions

- [ ] **Step 1: Write the failing test**

```python
def test_content_pipeline_skip_image_propagation():
    """ContentPipeline.skip_image is passed to VideoPipelineV3."""
    from unittest.mock import MagicMock, patch

    with patch('modules.content.content_pipeline.get_or_create_project', return_value=1), \
         patch('modules.content.content_pipeline.init_db_full'):
        from modules.content.content_pipeline import ContentPipeline
        cp = ContentPipeline(project_id=1, channel_id="test", skip_image=True)
        assert cp.skip_image == True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_pipeline.py::test_content_pipeline_skip_image_propagation -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'skip_image'`

- [ ] **Step 3: Add `skip_image` to ContentPipeline.__init__**

Read `modules/content/content_pipeline.py:51-74` (the `__init__`). Add `skip_image: bool = False` parameter and `self.skip_image = skip_image`.

- [ ] **Step 4: Pass `skip_image` to VideoPipelineV3 in `produce_video()`**

Find where `VideoPipelineV3` is instantiated in `ContentPipeline.produce_video()`. Add `skip_image=self.skip_image`.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_content_pipeline.py::test_content_pipeline_skip_image_propagation -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add modules/content/content_pipeline.py tests/test_content_pipeline.py
git commit -m "feat(content_pipeline): add skip_image param and pass to VideoPipelineV3"
```

---

## Task 5: Add `--skip-image` CLI arg to `run_pipeline.py`

**Files:**
- Modify: `scripts/run_pipeline.py:327-341` (argparse section)

- [ ] **Step 1: Add CLI argument**

In the argparse section (around line 334), add:

```python
parser.add_argument("--skip-image", action="store_true",
    help="Skip image generation (use placeholder image + static video to save API costs)")
```

- [ ] **Step 2: Pass `skip_image` to `run_content_pipeline()` and `run_full_pipeline()` calls**

Find all calls to `run_content_pipeline()` (line 392-398) and `run_full_pipeline()` (lines 362-389) and add `skip_image=args.skip_image`.

- [ ] **Step 3: Add `skip_image` to `run_full_pipeline()` function signature**

Update `run_full_pipeline()` at line 197 to accept `skip_image: bool = False`.

- [ ] **Step 4: Add `skip_image` to `run_content_pipeline()` function signature**

Update `run_content_pipeline()` at line 101 to accept `skip_image: bool = False` (even if not used yet, for API consistency).

- [ ] **Step 5: Verify the CLI flag appears**

Run: `python scripts/run_pipeline.py --help`
Expected: `--skip-image` appears in the help output.

- [ ] **Step 6: Commit**

```bash
git add scripts/run_pipeline.py
git commit -m "feat(run_pipeline): add --skip-image CLI flag"
```

---

## Task 6: Verify end-to-end with a dry run

- [ ] **Step 1: Run with skip-image and skip-lipsync on a single idea**

```bash
python scripts/run_pipeline.py --channel nang_suat_thong_minh --ideas 1 --produce --skip-image --skip-lipsync --dry-run
```

Expected output should show:
- Content pipeline runs (generates script)
- Video pipeline shows: `Phase 2: SKIPPED (skip_image=True)`
- Phase 3 shows: `Static video (skip_image=True) scene_N...`

- [ ] **Step 2: Run without dry-run (real API calls)**

```bash
python scripts/run_pipeline.py --channel nang_suat_thong_minh --ideas 1 --produce --skip-image --skip-lipsync
```

Expected: TTS runs, no image gen API calls, no lipsync API calls, static video created from placeholder image.