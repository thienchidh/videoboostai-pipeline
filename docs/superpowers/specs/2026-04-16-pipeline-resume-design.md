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

Full JSON schemas per step (all paths are absolute):

**RUN-LEVEL: `run_meta.json`** (one per run directory)
```json
{
  "run_id": 42,
  "run_dir": "/path/to/run_dir",
  "channel_id": "nang_suat_thong_minh",
  "scenario_slug": "productivity_tips",
  "scenario_title": "5 Tips Quản Lý Thời Gian",
  "total_scenes": 3,
  "started_at": "2026-04-16T10:00:00",
  "completed_at": null,
  "config_snapshot": {
    "tts": { "model": "speech-2.1-hd", "sample_rate": 32000, "bitrate": 128000, "format": "mp3", "timeout": 60 },
    "image": { "model": "image-01", "aspect_ratio": "9:16", "timeout": 120 },
    "lipsync": { "provider": "kieai", "resolution": "480p", "max_wait": 300, "poll_interval": 10, "retries": 2 }
  }
}
```

**SCENE-LEVEL: `scene_meta.json`** (one per scene directory)
```json
{
  "scene_id": 1,
  "scene_index": 0,
  "title": "Mẹo 1: Lên kế hoạch trước",
  "script": "Hôm nay chúng ta sẽ nói về kỹ năng quản lý thời gian hiệu quả...",
  "characters": ["speaker1"],
  "tts_text": "Hôm nay chúng ta sẽ nói về...",
  "video_prompt": "A female speaker, professional lighting, office background...",
  "created_at": "2026-04-16T10:00:00"
}
```

**STEP 1 — TTS: `step_01_tts.json`**
```json
{
  "step": 1,
  "name": "tts",
  "status": "done",
  "mode": "edge",
  "output": "/path/to/scene_1/audio_tts.mp3",
  "duration_seconds": 12.5,
  "text": "Hôm nay chúng ta sẽ nói về kỹ năng quản lý thời gian hiệu quả...",
  "provider": "edge",
  "voice": "vi-VN-NamMinhNeural",
  "speed": 1.0,
  "model": "edge-tts",
  "sample_rate": 32000,
  "bitrate": "128k",
  "format": "mp3",
  "input_duration": null,
  "error": null,
  "created_at": "2026-04-16T10:30:00"
}
```

**STEP 2 — IMAGE: `step_02_image.json`**
```json
{
  "step": 2,
  "name": "image",
  "status": "done",
  "mode": "minimax",
  "output": "/path/to/scene_1/scene.png",
  "input_text": "/path/to/scene_1/audio_tts.mp3",
  "input_duration": 12.5,
  "prompt": "A female speaker, professional lighting, office background, 4K quality...",
  "provider": "minimax",
  "model": "image-01",
  "aspect_ratio": "9:16",
  "gender": "female",
  "character_name": "NamMinh",
  "timeout": 120,
  "poll_interval": 5,
  "max_polls": 24,
  "error": null,
  "created_at": "2026-04-16T10:30:15"
}
```

**STEP 3 — LIPSYNC: `step_03_lipsync.json`**
```json
{
  "step": 3,
  "name": "lipsync",
  "status": "done",
  "mode": "kieai",
  "output": "/path/to/scene_1/video_raw.mp4",
  "input_image": "/path/to/scene_1/scene.png",
  "input_audio": "/path/to/scene_1/audio_tts.mp3",
  "input_duration": 12.5,
  "prompt": "A person talking confidently about time management...",
  "provider": "kieai",
  "actual_mode": "kieai",
  "attempted_mode": "kieai",
  "fallback_reason": null,
  "resolution": "480p",
  "max_wait": 300,
  "poll_interval": 10,
  "retries": 2,
  "seed": null,
  "task_id": "task_abc123",
  "job_id": null,
  "api_request_payload": { "model": "infinitalk/from-audio", "image_url": "https://...", "audio_url": "https://..." },
  "api_response": { "success": true, "task_id": "task_abc123" },
  "error": null,
  "created_at": "2026-04-16T10:31:00"
}
```

**STEP 3 — LIPSYNC with FALLBACK: `step_03_lipsync.json`**
```json
{
  "step": 3,
  "name": "lipsync",
  "status": "done",
  "mode": "static_fallback",
  "output": "/path/to/scene_1/video_raw.mp4",
  "input_image": "/path/to/scene_1/scene.png",
  "input_audio": "/path/to/scene_1/audio_tts.mp3",
  "input_duration": 12.5,
  "prompt": "A person talking confidently about time management...",
  "provider": "kieai",
  "actual_mode": "static_fallback",
  "attempted_mode": "kieai",
  "fallback_reason": "LipsyncQuotaError: quota exceeded",
  "resolution": "480p",
  "task_id": "task_abc123",
  "api_error": "quota exceeded",
  "error": "LipsyncQuotaError: quota exceeded",
  "created_at": "2026-04-16T10:31:00"
}
```

**STEP 4 — CROP: `step_04_crop.json`**
```json
{
  "step": 4,
  "name": "crop",
  "status": "done",
  "mode": "ffmpeg",
  "output": "/path/to/scene_1/video_9x16.mp4",
  "input": "/path/to/scene_1/video_raw.mp4",
  "input_duration": 12.5,
  "input_width": 1920,
  "input_height": 1080,
  "input_ratio": 1.78,
  "output_width": 1080,
  "output_height": 1920,
  "output_duration": 12.5,
  "crop_filter": "crop=1080:1920:420:0",
  "scale_filter": "scale=1080:1920",
  "ffmpeg_cmd": "ffmpeg -i input -vf crop=1080:1920:420:0,scale=1080:1920 -c:v libx264 -preset fast -crf 23 -c:a aac -y output",
  "codec": "libx264",
  "crf": 23,
  "preset": "fast",
  "error": null,
  "created_at": "2026-04-16T10:31:30"
}
```

**Common fields across all step files:**
- `step`: step number (1-4)
- `name`: step name
- `status`: `"done"` | `"failed"` | `"retry"`
- `mode`: actual execution mode used
- `output`: absolute path to output file
- `created_at`: ISO timestamp
- `error`: error message if failed, null otherwise

**Per-step specific fields:**

| Field | TTS | Image | Lipsync | Crop |
|-------|-----|-------|---------|------|
| `duration_seconds` | ✓ | — | — | — |
| `text` | ✓ | — | — | — |
| `provider` | ✓ | ✓ | ✓ | — |
| `voice` | ✓ | — | — | — |
| `speed` | ✓ | — | — | — |
| `model` | ✓ | ✓ | — | — |
| `sample_rate` | ✓ | — | — | — |
| `bitrate` | ✓ | — | — | — |
| `format` | ✓ | — | — | — |
| `input_text` | — | ✓ | — | — |
| `input_duration` | ✓ | ✓ | ✓ | ✓ |
| `prompt` | — | ✓ | ✓ | — |
| `gender` | — | ✓ | — | — |
| `character_name` | — | ✓ | — | — |
| `aspect_ratio` | — | ✓ | — | — |
| `timeout` | — | ✓ | — | — |
| `poll_interval` | — | ✓ | ✓ | — |
| `max_polls` | — | ✓ | — | — |
| `input_image` | — | — | ✓ | — |
| `input_audio` | — | — | ✓ | — |
| `attempted_mode` | — | — | ✓ | — |
| `actual_mode` | — | — | ✓ | — |
| `fallback_reason` | — | — | ✓ | — |
| `resolution` | — | — | ✓ | — |
| `max_wait` | — | — | ✓ | — |
| `retries` | — | — | ✓ | — |
| `seed` | — | — | ✓ | — |
| `task_id` | — | — | ✓ | — |
| `job_id` | — | — | ✓ | — |
| `api_request_payload` | — | — | ✓ | — |
| `api_response` | — | — | ✓ | — |
| `api_error` | — | — | ✓ | — |
| `input_width` | — | — | — | ✓ |
| `input_height` | — | — | — | ✓ |
| `input_ratio` | — | — | — | ✓ |
| `output_width` | — | — | — | ✓ |
| `output_height` | — | — | — | ✓ |
| `crop_filter` | — | — | — | ✓ |
| `scale_filter` | — | — | — | ✓ |
| `ffmpeg_cmd` | — | — | — | ✓ |
| `codec` | — | — | — | ✓ |
| `crf` | — | — | — | ✓ |
| `preset` | — | — | — | ✓ |

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

- `VideoPipelineRunner.__init__` writes `run_meta.json` at start of `run()`
- `SingleCharSceneProcessor` receives `run_id` and uses it only for `run_meta.json` linkage
- `resume=True` passed to `single_processor` enables step-level file scanning

#### Changes to `retry_from_checkpoint.py`

Rename to `retry_scene.py`:

```
# List current step status
python scripts/retry_scene.py --scene-dir output/.../scene_3

# Re-run specific step
python scripts/retry_scene.py --scene-dir output/.../scene_3 --step 3

# Clear step checkpoint (force re-run from that step)
python scripts/retry_scene.py --scene-dir output/.../scene_3 --step 3 --clear

# Re-run from first failed/incomplete step
python scripts/retry_scene.py --scene-dir output/.../scene_3 --resume
```

The script reads `step_XX_*.json` files and prints a table:

```
scene_3/
  run_meta.json       run_id=42 channel=nang_suat_thong_minh
  scene_meta.json     scene_id=1 title="Mẹo 1..."
  step_01_tts.json    done  edge           12.5s
  step_02_image.json  done  minimax        1920x1080
  step_03_lipsync.json done  static_fallback ⚠️ LipsyncQuotaError
  step_04_crop.json  done  ffmpeg
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

- `scripts/retry_scene.py` — reads step checkpoint files from scene dir, re-runs specific steps, prints status table

### Modified files

- `modules/pipeline/scene_processor.py` — write `step_XX_*.json` and `scene_meta.json` after each step; scan for first incomplete/retry step on resume
- `modules/pipeline/pipeline_runner.py` — write `run_meta.json` at start of `run()`; pass `run_id` to `SingleCharSceneProcessor`
- `core/video_utils.py` — `crop_to_9x16()` returns a dict with crop dimensions (input_w/h, crop_filter, scale_filter, etc.) so caller can record in checkpoint

### Removed/changed

- `CheckpointHelper` from `checkpoint.py` — no longer used for step-level resume (DB checkpoints remain used for scene_run tracking)
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
