# Pipeline Resume System Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement comprehensive resume at every pipeline granularity with human-editable checkpoint files that support fallback re-run (e.g., lipsync fails → static fallback → user fixes lipsync URL → retry from step).

**Architecture:** Step checkpoint files (`step_01_tts.json`, `step_02_image.json`, etc.) written after each step completes. Files are human-readable and editable. Retry script reads files and re-runs steps where user has edited the `mode` field.

**Tech Stack:** Step checkpoint JSON files per scene, no new DB tables.

---

## Current State

### Content Pipeline Phases

| Phase | Resume Mechanism | Works? |
|-------|-----------------|--------|
| Research | Distributed lock with 2hr timeout | Partial |
| Ideas generation | DB status `raw` → `script_ready` | Yes |
| Script generation | JSON checkpoint file per run | Partial |
| Produce video | `produce_video` checks DB status | Yes |

### Video Pipeline Phases

| Phase | Resume Mechanism | Works? |
|-------|-----------------|--------|
| Scene-level skip | `video_9x16.mp4` exists + `resume=True` | Yes |
| Step-level within scene | `CheckpointHelper` defined in `checkpoint.py` | **No — never called** |
| Retry script | `retry_from_checkpoint.py` | **Not wired to scene_processor** |

---

## Design

### Layer 1: Content Pipeline — Idea-Level (No Changes)

Each idea's script is saved to DB immediately. `produce_video` skips ideas with `status = script_ready`. No changes needed.

### Layer 2: Video Pipeline — Scene-Level (No Changes)

`scene_processor.process()` skips entire scene if `video_9x16.mp4` exists + `resume=True`. Already works.

### Layer 3: Video Pipeline — Step-Level (New)

#### Step Checkpoint Files

After each step completes, write a JSON file to the scene directory:

```
scene_1/
  step_01_tts.json        # TTS done
  step_02_image.json      # image done
  step_03_lipsync.json    # lipsync done (or fallback)
  step_04_crop.json       # crop done
  video_9x16.mp4         # final output
```

#### File naming

Files use 2-digit step numbers (01-04) matching execution order:

| File | Step | Output |
|------|------|--------|
| `step_01_tts.json` | TTS | `audio_tts.mp3` |
| `step_02_image.json` | Image gen | `scene.png` |
| `step_03_lipsync.json` | Lipsync | `video_raw.mp4` |
| `step_04_crop.json` | Crop to 9:16 | `video_9x16.mp4` |

#### Checkpoint JSON format

```json
{
  "step": 1,
  "name": "tts",
  "status": "done",
  "mode": "edge",
  "output": "audio_tts.mp3",
  "created_at": "2026-04-16T10:30:00",
  "error": null
}
```

**Fields:**
- `step`: step number (1-4)
- `name`: step name (tts, image, lipsync, crop)
- `status`: `"done"` | `"failed"` | `"retry"`
- `mode`: how the step was executed:
  - TTS: `"edge"` | `"minimax"` | `"mock"`
  - Image: `"minimax"` | `"kie"` | `"wavespeed"` | `"mock"`
  - Lipsync: `"kieai"` | `"wavespeed"` | `"static_fallback"` | `"mock"`
  - Crop: `"ffmpeg"`
- `output`: filename written by the step
- `created_at`: ISO timestamp
- `error`: error message if status is `"failed"`, null otherwise

#### Fallback recording

When a step falls back (e.g., lipsync → static image):

```json
{
  "step": 3,
  "name": "lipsync",
  "status": "done",
  "mode": "static_fallback",
  "output": "video_raw.mp4",
  "created_at": "2026-04-16T10:35:00",
  "error": "LipsyncQuotaError: quota exceeded"
}
```

#### Changes to `scene_processor.py`

`SingleCharSceneProcessor.process()` new flow:

```
1. Scene-level skip check (unchanged — video_9x16.mp4 exists + resume)
2. Scan step files 01-04 in scene dir to find first missing or retry-marked step
3. For each step to run:
   a. Run step
   b. Write step_XX_{name}.json with mode + status
   c. If step fails and fallback available:
      - Run fallback
      - Write step_XX_{name}.json with mode="static_fallback" and error field
4. If final video exists after all steps: scene done
```

Key behavior:
- If `step_03_lipsync.json` exists with `"status": "done"` → skip lipsync step
- If user edits it to `"status": "retry"` and fixes the config → lipsync re-runs
- If user edits it to `"status": "done"` and `"mode": "retry_lipsync"` → lipsync re-runs with new mode

#### Step skip logic

```python
def _get_first_incomplete_step(scene_dir: Path) -> int:
    """Return 1-based step number of first step not yet done, or 5 if all done."""
    for step_num in range(1, 5):  # steps 1-4
        step_file = scene_dir / f"step_{step_num:02d}_{STEP_NAMES[step_num]}.json"
        if not step_file.exists():
            return step_num
        with open(step_file) as f:
            data = json.load(f)
        if data.get("status") == "retry":
            return step_num
        if data.get("status") != "done":
            return step_num
    return 5  # all done
```

#### Changes to `pipeline_runner.py`

- `SingleCharSceneProcessor` no longer needs `run_id` (files are in scene_dir, no DB)
- `CheckpointHelper` from `checkpoint.py` is **not used** — replaced by file-based approach
- `resume=True` passed to `single_processor` enables step-level file scanning

#### Changes to `retry_from_checkpoint.py`

Rename to `retry_scene.py` or extend with new flags:

```
# Re-run from a specific step within a scene
python scripts/retry_scene.py --scene-dir output/.../scene_3 --step 3

# Clear step checkpoint (force re-run from that step)
python scripts/retry_scene.py --scene-dir output/.../scene_3 --step 3 --clear

# List current step status
python scripts/retry_scene.py --scene-dir output/.../scene_3 --list
```

The script reads `step_XX_*.json` files from the scene directory and prints a table:

```
scene_3/
  step_01_tts.json       done  edge
  step_02_image.json     done  minimax
  step_03_lipsync.json   done  static_fallback  ⚠️ LipsyncQuotaError
  step_04_crop.json     done  ffmpeg
```

User sees `static_fallback` with error → edits `step_03_lipsync.json` to set `"status": "retry"` → fixes config → re-runs.

---

## Data Flow

### Happy path (no failures)

```
scene_1/ (empty)
  → run TTS → write step_01_tts.json {"status": "done", "mode": "edge"}
  → run image → write step_02_image.json {"status": "done", "mode": "minimax"}
  → run lipsync → write step_03_lipsync.json {"status": "done", "mode": "kieai"}
  → run crop → write step_04_crop.json {"status": "done", "mode": "ffmpeg"}
scene_1/ (all done)
```

### Lipsync falls back to static

```
scene_1/ (after step 02)
  → run lipsync → LIPSYNC FAILS (quota exceeded)
    → catch LipsyncQuotaError → run static fallback
    → write step_03_lipsync.json {"status": "done", "mode": "static_fallback", "error": "LipsyncQuotaError"}
  → run crop → write step_04_crop.json {"status": "done", "mode": "ffmpeg"}
scene_1/ (done but using static fallback)
```

### User retries lipsync with fixed config

```
User edits step_03_lipsync.json:
  {"status": "done", "mode": "static_fallback", ...}
  → changed to:
  {"status": "retry", "mode": "kieai", ...}

User fixes kieai URL in config

User runs: python scripts/retry_scene.py --scene-dir scene_3 --step 3

Script reads step_03 → sees status=retry → re-runs lipsync with new config
→ write step_03_lipsync.json {"status": "done", "mode": "kieai"}
```

---

## File Changes

### New files

- `scripts/retry_scene.py` — reads step checkpoint files from scene dir, re-runs specific steps

### Modified files

- `modules/pipeline/scene_processor.py` — write `step_XX_*.json` after each step; scan for first incomplete/retry step on resume
- `modules/pipeline/pipeline_runner.py` — pass `run_id` no longer needed; `resume` param still passed

### Removed/changed

- `CheckpointHelper` from `checkpoint.py` — no longer used for step-level resume (DB checkpoints remain used for other purposes if any)
- `retry_from_checkpoint.py` — superseded by `retry_scene.py` focused on file-based step retry

---

## Edge Cases

### Step output file deleted but checkpoint file exists

Checkpoint file says step is `"done"`. Step output (e.g., `audio_tts.mp3`) was manually deleted. On resume, step is skipped (checkpoint is authoritative). If user wants to re-run, they must edit the checkpoint file to set `"status": "retry"`.

### Step checkpoint file deleted but output exists

No checkpoint file but `audio_tts.mp3` exists. Treat as step done — skip. (Checkpoint file would be re-created on next complete run.)

### Crash during step N (checkpoint not written)

Step N starts running but crashes before completing → checkpoint file for step N is NOT written. On retry, `_get_first_incomplete_step` finds step N (no file = incomplete) → step N re-runs. Step N-1's checkpoint exists → skipped. Correct.

### Concurrent retry

Two processes retry the same scene simultaneously. Both could overwrite the same step output file. Acceptable — last write wins. Distributed locking can be added later if needed.

---

## Testing

1. Run scene with partial failure → verify step checkpoint files written with correct `mode` and `error` fields
2. Run with `resume=True` after partial → verify only incomplete steps re-run
3. Simulate lipsync fallback → edit checkpoint to `"status": "retry"` → verify lipsync re-runs
4. `retry_scene.py --list` shows correct step status table
5. `retry_scene.py --step 3 --clear` wipes step 3 checkpoint → re-run from step 3

---

## Verification

- [ ] Each step writes `step_XX_{name}.json` after completion
- [ ] `mode` field reflects actual provider/fallback used
- [ ] `error` field populated when step falls back or fails
- [ ] `_get_first_incomplete_step()` returns correct step on resume
- [ ] Editing `status` to `"retry"` causes step to re-run
- [ ] `retry_scene.py --list` shows readable status table
- [ ] All 286 existing tests pass
