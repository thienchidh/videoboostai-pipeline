# Skip Content + Scenario Re-run + Resume Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm cờ `--skip-content` để skip content generation, chạy video production từ 1 scenario YAML có sẵn, và implement resume mechanism cho cả content và video pipeline.

**Architecture:**
- Thêm `--scenario <path>` flag để chỉ định scenario YAML cụ thể khi `--skip-content`
- ContentIdea update `status='re_run'` khi re-run để track lịch sử
- Video resume: kiểm tra existing output files trong run_dir → skip completed scenes
- Content resume: dùng lại `pending_topic_sources` pool, không re-research topics đã load

**Tech Stack:** Python, argparse, existing pipeline infrastructure

---

## File Structure

- **Modify:** `scripts/run_pipeline.py` — thêm `--scenario` CLI flag, logic chọn giữa DB ideas vs scenario file
- **Modify:** `modules/content/content_pipeline.py` — respect `skip_content`, thêm re-run status tracking
- **Modify:** `modules/pipeline/scene_processor.py` — kiểm tra existing output files để skip completed scenes
- **Modify:** `modules/pipeline/pipeline_runner.py` — resume logic cho video pipeline
- **Modify:** `modules/content/content_idea_generator.py` — thêm method để update idea status thành `re_run`

---

## Task 1: Add `--scenario` CLI Flag to `run_pipeline.py`

**Files:**
- Modify: `scripts/run_pipeline.py:247-283`

- [ ] **Step 1: Add `--scenario` argument**

```python
parser.add_argument("--scenario", type=str, default=None,
    help="Path to scenario YAML file. When used with --skip-content, runs video production for this specific scenario.")
```

- [ ] **Step 2: Pass scenario to run_full_pipeline**

Trong `run_full_pipeline()` signature thêm `scenario_path: str = None`.

Khi `skip_content=True` và `scenario_path` được chỉ định:
- Gọi `run_video_pipeline(channel_id, scenario_path)` thay vì content cycle
- Không gọi `run_full_cycle()`

```python
def run_full_pipeline(channel_id: str, ideas_count: int = 1, produce: bool = True,
                       skip_lipsync: bool = False, skip_content: bool = False,
                       scenario_path: str = None) -> dict:
    # ...
    if skip_content and scenario_path:
        # Run video only for specified scenario
        video_path, timestamps = run_video_pipeline(
            channel_id=channel_id,
            scenario_path=scenario_path,
            dry_run=False,
            dry_run_tts=False,
            dry_run_images=False,
        )
        return {"videos": [{"scenario": scenario_path, "video_path": video_path}]}
```

- [ ] **Step 3: Update CLI dispatch logic**

```python
if args.produce:
    if args.skip_content and args.scenario:
        # Skip content, run specific scenario
        result = run_full_pipeline(
            channel_id=ch,
            ideas_count=args.ideas,
            produce=True,
            skip_lipsync=args.skip_lipsync,
            skip_content=True,
            scenario_path=args.scenario,
        )
    elif args.skip_content:
        # Skip content, run video for all script_ready ideas from DB
        result = run_full_pipeline(
            channel_id=ch,
            ideas_count=args.ideas,
            produce=True,
            skip_lipsync=args.skip_lipsync,
            skip_content=True,
        )
    else:
        result = run_full_pipeline(
            channel_id=ch,
            ideas_count=args.ideas,
            produce=True,
            skip_lipsync=args.skip_lipsync,
            skip_content=False,
        )
```

- [ ] **Step 4: Test CLI help**

Run: `python scripts/run_pipeline.py --help`
Expected: `--scenario` flag visible in help output

- [ ] **Step 5: Commit**

```bash
git add scripts/run_pipeline.py
git commit -m "feat: add --scenario flag for specifying YAML scenario path"
```

---

## Task 2: Respect `skip_content` in `run_full_cycle()`

**Files:**
- Modify: `modules/content/content_pipeline.py:104-268`

- [ ] **Step 1: Add skip_content guard at start of run_full_cycle()**

```python
def run_full_cycle(self, num_ideas: int = 5) -> Dict:
    logger.info("=" * 50)
    logger.info("CONTENT PIPELINE - FULL CYCLE")
    logger.info("=" * 50)

    results = {}

    # If skip_content, we still run content cycle but skip research step
    if self.skip_content:
        logger.info("⚠️  SKIP_CONTENT mode: using existing scripts from DB")
        # Fall through to load existing ideas
```

**However**, the current `skip_content` logic in `run_full_cycle()` doesn't actually skip — it always runs research. The intent is:
- When `skip_content=True`: skip the entire `run_full_cycle()` and directly call `produce_video()` from existing DB ideas or from a specified scenario YAML.

So restructure:
- If `skip_content=True` and `scenario_path` is provided → call `produce_video()` directly with that scenario YAML
- If `skip_content=True` and no `scenario_path` → load all `script_ready` ideas from DB and produce videos for them

- [ ] **Step 2: Implement skip_content path in run_full_cycle()**

Add at the beginning of `run_full_cycle()`:

```python
if self.skip_content:
    logger.info("⚠️  SKIP_CONTENT mode: loading existing scripts from DB")
    results = self._run_from_existing_scripts(num_ideas)
    return results
```

Add new method `_run_from_existing_scripts()`:

```python
def _run_from_existing_scripts(self, num_ideas: int = 5) -> Dict:
    """Load existing script_ready ideas from DB and produce videos."""
    from db import get_content_idea

    ideas = self.idea_gen.get_ideas_by_status(status="script_ready", limit=num_ideas)
    logger.info(f"  Found {len(ideas)} existing script_ready ideas")

    produced = []
    for idea in ideas:
        idea_id = idea.get("id")
        script_json = idea.get("script_json")

        if not script_json:
            logger.warning(f"  Idea {idea_id} has no script_json, skipping")
            continue

        # Save config path for this idea
        config_path = str(self._save_script_config(idea_id, script_json))

        # Mark as re_run in DB
        self.idea_gen.update_idea_status(idea_id, status="re_run")

        # Produce video
        logger.info(f"  Producing video for existing idea {idea_id}: {idea.get('title', '')[:50]}")
        prod_result = self.produce_video(idea_id, config_path=config_path)
        produced.append({
            "idea_id": idea_id,
            "config_path": config_path,
            "result": prod_result,
        })
        logger.info(f"  Production result: {prod_result.get('success')}")

    return {
        "produced": produced,
        "scripts_generated": 0,  # No new scripts generated
        "ideas_generated": 0,
        "status": "re_run_from_existing",
    }
```

- [ ] **Step 3: Add update_idea_status() to ContentIdeaGenerator**

Modify: `modules/content/content_idea_generator.py`

```python
def update_idea_status(self, idea_id: int, status: str) -> bool:
    """Update status of a content idea."""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE content_ideas SET status = ? WHERE id = ?",
        (status, idea_id)
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0
```

- [ ] **Step 4: Verify existing test for content_pipeline**

Run: `pytest tests/ -v -k content_pipeline --collect-only 2>/dev/null || echo "No content_pipeline tests found"`
Expected: List of test names or "No content_pipeline tests found"

- [ ] **Step 5: Run existing tests**

Run: `pytest tests/ -v`
Expected: All tests pass (no regressions)

- [ ] **Step 6: Commit**

```bash
git add modules/content/content_pipeline.py modules/content/content_idea_generator.py
git commit -m "feat: respect skip_content flag, load existing scripts from DB for re-run"
```

---

## Task 3: Resume Video Production — Skip Completed Scenes

**Files:**
- Modify: `modules/pipeline/scene_processor.py` — check existing output before processing
- Modify: `modules/pipeline/pipeline_runner.py` — add resume flag and pass to scene_processor

- [ ] **Step 1: Add resume capability to SceneProcessor**

In `SceneProcessor.process_scene()`, at the start of each major step (TTS, image, lipsync), check if output file already exists:

```python
def process_scene(self, scene_index: int, script: Dict) -> Dict:
    """Process a single scene: TTS → Image → Lipsync → Crop.

    Args:
        scene_index: Scene index within the script (0-based)
        script: Scene script dict

    Returns:
        Dict with scene outputs: tts_path, image_path, lipsync_path, crop_path
    """
    from modules.pipeline.exceptions import SceneDurationError

    scene_num = scene_index + 1
    logger.info(f"  Processing scene {scene_num}/{len(self.scripts)}")

    media_dir = self.media_dir
    tts_path = media_dir / f"tts_{scene_num:03d}.mp3"
    image_path = media_dir / f"image_{scene_num:03d}.png"
    lipsync_path = media_dir / f"lipsync_{scene_num:03d}.mp4"
    crop_path = media_dir / f"crop_{scene_num:03d}.mp4"
    alpha_path = media_dir / f"alpha_{scene_num:03d}.mp4"

    # Resume: skip already-completed steps
    if self.resume and crop_path.exists():
        logger.info(f"    Resume: crop already exists, skipping scene {scene_num}")
        return {
            "tts_path": str(tts_path),
            "image_path": str(image_path),
            "lipsync_path": str(lipsync_path),
            "crop_path": str(crop_path),
        }
```

Add `resume` parameter to `SceneProcessor.__init__()`:

```python
def __init__(self, channel_id: str, scenario_path: str,
             dry_run: bool = False, dry_run_tts: bool = False,
             dry_run_images: bool = False, resume: bool = False):
    # ...
    self.resume = resume
```

- [ ] **Step 2: Pass resume flag from PipelineRunner to SceneProcessor**

In `modules/pipeline/pipeline_runner.py`, add `resume` to `SceneProcessor` instantiation:

```python
scene_processor = SceneProcessor(
    channel_id=self.channel_id,
    scenario_path=self.scenario_path,
    dry_run=dry_run or self.DRY_RUN,
    dry_run_tts=dry_run_tts or self.DRY_RUN_TTS,
    dry_run_images=dry_run_images or self.DRY_RUN_IMAGES,
    resume=self.resume,  # NEW
)
```

Add `resume` to `PipelineRunner.__init__()`:

```python
def __init__(self, channel_id: str, scenario_path: str,
             resume: bool = False, ...):
    # ...
    self.resume = resume
```

- [ ] **Step 3: Pass resume flag from VideoPipelineV3 to PipelineRunner**

In `scripts/video_pipeline_v3.py`, update `VideoPipelineV3.__init__()` and `VideoPipelineV3.run()` to accept and pass `resume`:

```python
class VideoPipelineV3:
    def __init__(self, channel_id: str, scenario_path: str,
                 resume: bool = False, ...):
        # ...
        self.resume = resume
        self._runner = PipelineRunner(
            channel_id=channel_id,
            scenario_path=scenario_path,
            resume=resume,
            # ... other args
        )
```

- [ ] **Step 4: Add --resume CLI flag to run_pipeline.py**

In `run_pipeline.py` CLI section:

```python
parser.add_argument("--resume", action="store_true",
    help="Resume video production from last checkpoint (skip completed scenes)")
```

Pass `resume=args.resume` to `VideoPipelineV3` and `run_full_pipeline`.

- [ ] **Step 5: Test resume logic**

Run: `python scripts/run_pipeline.py --skip-content --scenario configs/channels/nang_suat_thong_minh/scenarios/productivity-wikipedia.yaml --resume`
Expected: Video production resumes from existing output files

- [ ] **Step 6: Commit**

```bash
git add scripts/video_pipeline_v3.py modules/pipeline/pipeline_runner.py modules/pipeline/scene_processor.py scripts/run_pipeline.py
git commit -m "feat: add resume capability for video production - skip completed scenes"
```

---

## Task 4: Resume Content Pipeline

**Files:**
- Modify: `modules/content/content_pipeline.py` — use pending pool more effectively on resume

- [ ] **Step 1: Add resume content mode**

In `run_full_cycle()` when `skip_content=False` (normal content mode), detect if we're resuming from an interrupted run. The current pending pool logic already handles this — if there are pending topics, it uses them instead of fresh research.

However, the issue is `run_full_cycle()` always resets and doesn't track "where we left off". We can improve this by:

1. If `skip_content=False` and `pending_topic_sources` exist with some ideas already generated but not fully processed → continue from where interrupted
2. Track progress in a lightweight checkpoint file

Actually, the existing pending pool + `status` tracking already covers most resume needs. The improvement is:
- When content cycle is interrupted mid-way through `generate_script_from_idea()` for some ideas, on resume it should:
  - Not re-generate ideas that already have `script_json`
  - Continue producing videos for ideas that have scripts but no video output

- [ ] **Step 2: Add progress checkpoint for content cycle**

In `run_full_cycle()`, add checkpoint after each idea is processed:

```python
# After producing video for idea i:
checkpoint = {
    "last_processed_idea_index": i,
    "source_id": source_id,
    "idea_ids_processed": idea_ids[:i+1],
}
checkpoint_path = self.project_root / ".content_pipeline_checkpoint.json"
with open(checkpoint_path, "w") as f:
    json.dump(checkpoint, f)
```

At the start of `run_full_cycle()`, check for checkpoint:

```python
checkpoint_path = self.project_root / ".content_pipeline_checkpoint.json"
if checkpoint_path.exists():
    with open(checkpoint_path) as f:
        checkpoint = json.load(f)
    # Resume from checkpoint
    logger.info(f"📍 Resume: found checkpoint, last processed idea index: {checkpoint.get('last_processed_idea_index')}")
    # Skip ideas already processed
```

After successful completion, delete checkpoint:

```python
if checkpoint_path.exists():
    checkpoint_path.unlink()  # Clean up on success
```

- [ ] **Step 3: Commit**

```bash
git add modules/content/content_pipeline.py
git commit -m "feat: add content pipeline resume checkpoint"
```

---

## Task 5: Integration Test

**Files:**
- Test: Manual integration test

- [ ] **Step 1: Test skip_content with scenario path**

```bash
python scripts/run_pipeline.py --channel nang_suat_thong_minh --skip-content --scenario configs/channels/nang_suat_thong_minh/scenarios/productivity-wikipedia.yaml --produce
```

Expected: Video generated for the specified scenario without content generation.

- [ ] **Step 2: Test resume with existing output**

Run the same command again with `--resume`. Expected: Scenes with existing output files are skipped.

- [ ] **Step 3: Test full pipeline without skip**

```bash
python scripts/run_pipeline.py --channel nang_suat_thong_minh --ideas 1 --produce
```

Expected: Normal content + video pipeline runs.

---

## Summary of Changes

| Task | What | Files |
|------|------|-------|
| 1 | `--scenario` CLI flag | `scripts/run_pipeline.py` |
| 2 | `skip_content` respected in `run_full_cycle()` + re-run status | `content_pipeline.py`, `content_idea_generator.py` |
| 3 | Resume video: skip completed scenes | `scene_processor.py`, `pipeline_runner.py`, `video_pipeline_v3.py` |
| 4 | Resume content: checkpoint + continue from interrupted | `content_pipeline.py` |