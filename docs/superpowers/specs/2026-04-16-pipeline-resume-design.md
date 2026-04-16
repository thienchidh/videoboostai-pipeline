# Pipeline Resume System Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement comprehensive resume at every pipeline granularity: idea-level (content), scene-level (video), and step-level (video scene processing).

**Architecture:** 3-layer checkpoint system — (1) DB status as implicit checkpoint for content ideas, (2) file existence for scene-level video skip, (3) wired `CheckpointHelper` for step-level within-scene resume.

**Tech Stack:** Existing `CheckpointHelper` + `SceneCheckpoint` DB table, no new files.

---

## Current State

### Content Pipeline Phases

| Phase | Resume Mechanism | Works? |
|-------|-----------------|--------|
| Research | Distributed lock with 2hr timeout | Partial — lock auto-expires but no per-topic checkpoint |
| Ideas generation | DB status `raw` → `script_ready` | Yes — scripts saved individually to DB |
| Script generation | JSON checkpoint file per run | Partial — checkpoint only at idea boundaries |
| Produce video | `produce_video` checks DB status | Yes — skips ideas already `script_ready` |

### Video Pipeline Phases

| Phase | Resume Mechanism | Works? |
|-------|-----------------|--------|
| Scene-level skip | `video_9x16.mp4` exists + `resume=True` | Yes — entire scene skipped |
| Step-level within scene | `CheckpointHelper` defined in `checkpoint.py` | **No — never called from scene_processor** |
| Retry script | `retry_from_checkpoint.py` lists/clears DB steps | **No — DB steps never written during processing** |

The step-level checkpoint system (5 steps per scene: TTS→image→lipsync→crop→done) is dead code.

---

## Design

### Layer 1: Content Pipeline — Idea-Level (Implicit via DB)

**No code changes needed.** Each idea's script is saved to DB as JSON immediately after generation (`ContentIdea.script_json`). The `produce_video` method checks `status = script_ready` and skips ideas that already have scripts.

The JSON checkpoint file (`checkpoint_path` in `run_full_cycle`) is retained for the multi-idea batch loop — it tracks `last_processed_idea_index` so that if the batch crashes between ideas, the next run starts from the next idea. This is already implemented.

### Layer 2: Video Pipeline — Scene-Level (Already Works)

**No code changes needed.** `scene_processor.process()` checks for `video_9x16.mp4` existence when `resume=True`. If the final output exists, the entire scene is skipped. Already implemented.

### Layer 3: Video Pipeline — Step-Level (Wire CheckpointHelper)

**This is the primary implementation work.**

#### Changes to `scene_processor.py`

`SingleCharSceneProcessor.process()` currently:
1. Checks `resume` + `video_9x16.mp4` exists → skip scene entirely
2. If not skipping: runs all 4 steps sequentially (TTS → image → lipsync → crop)

**New flow:**
1. Same scene-level skip check (unchanged)
2. If not skipping: use `CheckpointHelper` to find first incomplete step
3. For each step, check if already done via `helper.is_step_done()` — skip if yes
4. After each step completes: call `helper.save_step()` to persist to DB
5. If a step fails mid-way: exception propagates, DB row for that step is NOT written (partial completion is safe — step N-1 is committed, step N will be retried)

#### CheckpointHelper integration

```python
# In SingleCharSceneProcessor.__init__:
self._checkpoint_helper = CheckpointHelper(run_id, run_dir)

# In process(), before each step:
if self._checkpoint_helper.is_step_done(scene_num, STEP_TTS):
    log(f"  ⏭️  TTS step already done — skipping")
else:
    # run TTS
    helper.save_step(scene_num, STEP_TTS, audio_path)
```

#### Step constants (already defined in checkpoint.py)

```python
STEP_TTS = 1    # audio_tts.mp3 written
STEP_IMAGE = 2   # scene.png written
STEP_LIPSYNC = 3 # video_raw.mp4 written
STEP_CROP = 4   # video_9x16.mp4 written
STEP_DONE = 5   # scene complete
```

#### `retry_from_checkpoint.py` integration

The `retry_from_checkpoint.py` script already lists/clears step-level checkpoints. After wiring `CheckpointHelper` into `scene_processor`, the script will show real data. No changes needed to the script itself.

#### Passing `run_id` to `SingleCharSceneProcessor`

`VideoPipelineRunner.__init__` creates `SingleCharSceneProcessor(ctx, self.run_dir, resume=self._resume)`. Currently does not pass `run_id`. The `CheckpointHelper` needs `run_id` to build scene_id keys (`run_{run_id}_scene_{num}`).

**Change:** `VideoPipelineRunner` passes `self.run_id` to `SingleCharSceneProcessor` → `CheckpointHelper` is initialized with `run_id`.

---

## Data Flow

### Video Scene Processing with Checkpoints

```
process_scene(scene_id=3):
  helper = CheckpointHelper(run_id=42, run_dir)

  next_step = helper.get_next_step(3)
  if next_step == 99:  # fully done
    return existing_video

  if next_step > STEP_TTS:     → skip TTS (already done)
  if next_step > STEP_IMAGE:    → skip image (already done)
  if next_step > STEP_LIPSYNC: → skip lipsync (already done)
  if next_step > STEP_CROP:    → skip crop (already done)

  # Run first incomplete step
  run_step_n()
  helper.save_step(3, STEP_n, output_path)
  # Continue to next step...
```

### Resume at Different Granularities

| Failure point | Resume behavior |
|--------------|-----------------|
| Crash after TTS, before image | Image step re-runs, TTS skipped |
| Crash after image, before lipsync | Lipsync step re-runs, TTS+image skipped |
| Crash after lipsync, before crop | Crop step re-runs, TTS+image+lipsync skipped |
| Crash after crop, before done | STEP_DONE written, scene fully complete |
| Entire scene output deleted | Scene re-processed from step 1 (DB checkpoints still exist — use `--clear` to wipe them) |

---

## Edge Cases

### Step output file deleted but DB checkpoint exists

If `audio_tts.mp3` is deleted from disk but DB shows `STEP_TTS` done, the step will be skipped (DB is authoritative). This is correct behavior — the file can be regenerated from TTS API if needed.

### DB checkpoint exists but step output file also exists

Both TTS output and DB checkpoint exist — skip the step. No regeneration needed.

### Crash during step N (DB not yet updated)

Step N-1 is committed to DB. Step N is not. On retry, `get_next_step()` returns N (first incomplete) — correct.

### Concurrent retry on same scene

`retry_from_checkpoint.py` has no locking. If two processes retry the same scene simultaneously, both could re-run the same step. Acceptable for MVP — the output file would be overwritten. Distributed locking per scene can be added later if needed.

### Scene number vs scene_id confusion

`scene.id` (from config) is used as the scene number for checkpointing. This is already how `scene_processor` uses it. Consistent throughout.

---

## Files to Modify

- `modules/pipeline/scene_processor.py` — wire `CheckpointHelper`, pass `run_id`
- `modules/pipeline/pipeline_runner.py` — pass `run_id` to `SingleCharSceneProcessor`
- No new files, no new DB tables (schema already exists)
- `retry_from_checkpoint.py` works automatically once checkpoints are written

---

## Testing

1. Run a scene with `resume=True` after partial completion — verify only incomplete steps re-run
2. Verify DB step checkpoints are written after each step
3. Verify `retry_from_checkpoint.py --list` shows correct step state after partial run
4. Verify `retry_from_checkpoint.py --clear` + re-run re-executes from step 1

---

## Verification

- [ ] `CheckpointHelper` is instantiated in `SingleCharSceneProcessor` with `run_id`
- [ ] Each step (TTS, image, lipsync, crop) checks `is_step_done()` before running
- [ ] Each step calls `save_step()` after successful completion
- [ ] `VideoPipelineRunner` passes `run_id` to `SingleCharSceneProcessor`
- [ ] `retry_from_checkpoint.py --list` shows step-level data after a partial run
- [ ] All 286 existing tests pass
