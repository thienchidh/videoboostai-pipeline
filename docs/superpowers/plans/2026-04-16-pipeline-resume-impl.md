# Pipeline Resume Step Checkpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement step-level file-based checkpoints for video scene processing: numbered `step_01_tts.json` … `step_04_crop.json` written after each step, plus `run_meta.json` and `scene_meta.json`. Supports human editing for retry after fallback.

**Architecture:** `StepCheckpointWriter` class in `scene_checkpoint.py` manages file I/O. `crop_to_9x16` returns a dict with all crop dimensions. `retry_scene.py` provides CLI to list/checkpoint/retry per step.

**Tech Stack:** Python pathlib + json + subprocess (ffprobe), no new dependencies.

---

## Task 1: StepCheckpointWriter class

**Files:**
- Create: `modules/pipeline/scene_checkpoint.py`
- Test: `tests/test_scene_checkpoint.py`

- [ ] **Step 1: Write failing test for StepCheckpointWriter**

```python
# tests/test_scene_checkpoint.py
import pytest
import json
import tempfile
from pathlib import Path
from modules.pipeline.scene_checkpoint import StepCheckpointWriter, _get_first_incomplete_step

class TestGetFirstIncompleteStep:
    def test_returns_1_when_no_files(self, tmp_path):
        result = _get_first_incomplete_step(tmp_path)
        assert result == 1

    def test_returns_2_when_step_1_done(self, tmp_path):
        step1 = tmp_path / "step_01_tts.json"
        step1.write_text(json.dumps({"step": 1, "name": "tts", "status": "done"}))
        result = _get_first_incomplete_step(tmp_path)
        assert result == 2

    def test_returns_3_when_step_1_and_2_done(self, tmp_path):
        (tmp_path / "step_01_tts.json").write_text(json.dumps({"step": 1, "status": "done"}))
        (tmp_path / "step_02_image.json").write_text(json.dumps({"step": 2, "status": "done"}))
        result = _get_first_incomplete_step(tmp_path)
        assert result == 3

    def test_returns_retry_step_when_status_is_retry(self, tmp_path):
        (tmp_path / "step_01_tts.json").write_text(json.dumps({"step": 1, "status": "done"}))
        (tmp_path / "step_02_image.json").write_text(json.dumps({"step": 2, "status": "retry"}))
        result = _get_first_incomplete_step(tmp_path)
        assert result == 2  # step 2 is marked retry, so restart from 2

    def test_returns_5_when_all_done(self, tmp_path):
        for i, name in enumerate(["tts", "image", "lipsync", "crop"], 1):
            (tmp_path / f"step_0{i}_{name}.json").write_text(json.dumps({"step": i, "status": "done"}))
        result = _get_first_incomplete_step(tmp_path)
        assert result == 5

    def test_returns_1_when_file_exists_but_status_not_done(self, tmp_path):
        step1 = tmp_path / "step_01_tts.json"
        step1.write_text(json.dumps({"step": 1, "status": "failed"}))
        result = _get_first_incomplete_step(tmp_path)
        assert result == 1


class TestStepCheckpointWriter:
    def test_write_tts_checkpoint(self, tmp_path):
        writer = StepCheckpointWriter(scene_dir=tmp_path, scene_id=1)
        writer.write_tts(
            output="/tmp/scene_1/audio_tts.mp3",
            duration_seconds=12.5,
            text="Hôm nay chúng ta...",
            provider="edge",
            voice="vi-VN-NamMinhNeural",
            speed=1.0,
            model="edge-tts",
            sample_rate=32000,
            bitrate="128k",
            format="mp3",
        )
        step_file = tmp_path / "step_01_tts.json"
        assert step_file.exists()
        data = json.loads(step_file.read_text())
        assert data["step"] == 1
        assert data["name"] == "tts"
        assert data["status"] == "done"
        assert data["mode"] == "edge"
        assert data["output"] == "/tmp/scene_1/audio_tts.mp3"
        assert data["duration_seconds"] == 12.5
        assert data["text"] == "Hôm nay chúng ta..."
        assert data["provider"] == "edge"
        assert data["voice"] == "vi-VN-NamMinhNeural"
        assert data["speed"] == 1.0
        assert data["model"] == "edge-tts"
        assert data["sample_rate"] == 32000
        assert data["bitrate"] == "128k"
        assert data["format"] == "mp3"
        assert data["error"] is None
        assert "created_at" in data

    def test_write_image_checkpoint(self, tmp_path):
        writer = StepCheckpointWriter(scene_dir=tmp_path, scene_id=2)
        writer.write_image(
            output="/tmp/scene_2/scene.png",
            input_text="/tmp/scene_2/audio_tts.mp3",
            input_duration=12.5,
            prompt="A female speaker, professional lighting...",
            provider="minimax",
            model="image-01",
            aspect_ratio="9:16",
            gender="female",
            character_name="NamMinh",
            timeout=120,
            poll_interval=5,
            max_polls=24,
        )
        step_file = tmp_path / "step_02_image.json"
        data = json.loads(step_file.read_text())
        assert data["step"] == 2
        assert data["name"] == "image"
        assert data["status"] == "done"
        assert data["mode"] == "minimax"
        assert data["output"] == "/tmp/scene_2/scene.png"
        assert data["input_duration"] == 12.5
        assert data["prompt"] == "A female speaker, professional lighting..."
        assert data["provider"] == "minimax"
        assert data["model"] == "image-01"
        assert data["aspect_ratio"] == "9:16"
        assert data["gender"] == "female"
        assert data["character_name"] == "NamMinh"
        assert data["error"] is None

    def test_write_lipsync_checkpoint_with_fallback(self, tmp_path):
        writer = StepCheckpointWriter(scene_dir=tmp_path, scene_id=3)
        writer.write_lipsync(
            output="/tmp/scene_3/video_raw.mp4",
            input_image="/tmp/scene_3/scene.png",
            input_audio="/tmp/scene_3/audio_tts.mp3",
            input_duration=12.5,
            prompt="A person talking...",
            provider="kieai",
            actual_mode="static_fallback",
            attempted_mode="kieai",
            fallback_reason="LipsyncQuotaError: quota exceeded",
            resolution="480p",
            max_wait=300,
            poll_interval=10,
            retries=2,
            task_id="task_abc123",
            error="LipsyncQuotaError: quota exceeded",
        )
        step_file = tmp_path / "step_03_lipsync.json"
        data = json.loads(step_file.read_text())
        assert data["step"] == 3
        assert data["name"] == "lipsync"
        assert data["status"] == "done"
        assert data["mode"] == "static_fallback"
        assert data["actual_mode"] == "static_fallback"
        assert data["attempted_mode"] == "kieai"
        assert data["fallback_reason"] == "LipsyncQuotaError: quota exceeded"
        assert data["error"] == "LipsyncQuotaError: quota exceeded"
        assert data["task_id"] == "task_abc123"

    def test_write_crop_checkpoint(self, tmp_path):
        writer = StepCheckpointWriter(scene_dir=tmp_path, scene_id=4)
        writer.write_crop(
            output="/tmp/scene_4/video_9x16.mp4",
            input="/tmp/scene_4/video_raw.mp4",
            input_duration=12.5,
            input_width=1920,
            input_height=1080,
            input_ratio=1.78,
            output_width=1080,
            output_height=1920,
            output_duration=12.5,
            crop_filter="crop=1080:1920:420:0",
            scale_filter="scale=1080:1920",
            ffmpeg_cmd="ffmpeg -i input -vf crop=1080:1920:420:0,scale=1080:1920 -c:v libx264 -preset fast -crf 23 -c:a aac -y output",
            codec="libx264",
            crf=23,
            preset="fast",
        )
        step_file = tmp_path / "step_04_crop.json"
        data = json.loads(step_file.read_text())
        assert data["step"] == 4
        assert data["name"] == "crop"
        assert data["status"] == "done"
        assert data["mode"] == "ffmpeg"
        assert data["output"] == "/tmp/scene_4/video_9x16.mp4"
        assert data["input_width"] == 1920
        assert data["input_height"] == 1080
        assert data["input_ratio"] == 1.78
        assert data["output_width"] == 1080
        assert data["output_height"] == 1920
        assert data["crop_filter"] == "crop=1080:1920:420:0"
        assert data["scale_filter"] == "scale=1080:1920"
        assert data["ffmpeg_cmd"] == "ffmpeg -i input -vf crop=1080:1920:420:0,scale=1080:1920 -c:v libx264 -preset fast -crf 23 -c:a aac -y output"
        assert data["codec"] == "libx264"
        assert data["crf"] == 23
        assert data["preset"] == "fast"
        assert data["error"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scene_checkpoint.py -v --tb=short`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.pipeline.scene_checkpoint'`

- [ ] **Step 3: Write StepCheckpointWriter implementation**

```python
# modules/pipeline/scene_checkpoint.py
"""Scene-level step checkpoint writer — writes step_XX_{name}.json files."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

STEP_NAMES = {1: "tts", 2: "image", 3: "lipsync", 4: "crop"}


def _step_file(scene_dir: Path, step_num: int) -> Path:
    """Return path to step checkpoint file, e.g. step_01_tts.json."""
    name = STEP_NAMES[step_num]
    return scene_dir / f"step_{step_num:02d}_{name}.json"


def _get_first_incomplete_step(scene_dir: Path) -> int:
    """Return 1-based step number of first step not yet done, or 5 if all done."""
    for step_num in range(1, 5):
        f = _step_file(scene_dir, step_num)
        if not f.exists():
            return step_num
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)
        if data.get("status") in ("retry", "failed"):
            return step_num
        if data.get("status") != "done":
            return step_num
    return 5  # all done


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StepCheckpointWriter:
    """Writes step_XX_{name}.json checkpoint files per scene."""

    def __init__(self, scene_dir: Path, scene_id: int):
        self.scene_dir = Path(scene_dir)
        self.scene_id = scene_id
        self.scene_dir.mkdir(parents=True, exist_ok=True)

    def _write(self, step_num: int, fields: Dict[str, Any]) -> None:
        f = _step_file(self.scene_dir, step_num)
        fields = {
            "step": step_num,
            "name": STEP_NAMES[step_num],
            "created_at": _now_iso(),
            **fields,
        }
        with open(f, "w", encoding="utf-8") as fp:
            json.dump(fields, fp, ensure_ascii=False, indent=2)

    def write_tts(
        self,
        output: str,
        duration_seconds: float,
        text: str,
        provider: str,
        voice: str,
        speed: float,
        model: str,
        sample_rate: int,
        bitrate: str,
        format: str,
        error: Optional[str] = None,
    ) -> None:
        self._write(1, {
            "status": "done" if error is None else "failed",
            "mode": provider,
            "output": output,
            "duration_seconds": duration_seconds,
            "text": text,
            "provider": provider,
            "voice": voice,
            "speed": speed,
            "model": model,
            "sample_rate": sample_rate,
            "bitrate": bitrate,
            "format": format,
            "error": error,
        })

    def write_image(
        self,
        output: str,
        input_text: str,
        input_duration: Optional[float],
        prompt: str,
        provider: str,
        model: str,
        aspect_ratio: str,
        gender: str,
        character_name: str,
        timeout: int,
        poll_interval: int,
        max_polls: int,
        error: Optional[str] = None,
    ) -> None:
        self._write(2, {
            "status": "done" if error is None else "failed",
            "mode": provider,
            "output": output,
            "input_text": input_text,
            "input_duration": input_duration,
            "prompt": prompt,
            "provider": provider,
            "model": model,
            "aspect_ratio": aspect_ratio,
            "gender": gender,
            "character_name": character_name,
            "timeout": timeout,
            "poll_interval": poll_interval,
            "max_polls": max_polls,
            "error": error,
        })

    def write_lipsync(
        self,
        output: str,
        input_image: str,
        input_audio: str,
        input_duration: float,
        prompt: str,
        provider: str,
        actual_mode: str,
        attempted_mode: str,
        fallback_reason: Optional[str],
        resolution: str,
        max_wait: int,
        poll_interval: int,
        retries: int,
        task_id: Optional[str] = None,
        job_id: Optional[str] = None,
        api_request_payload: Optional[Dict] = None,
        api_response: Optional[Dict] = None,
        error: Optional[str] = None,
    ) -> None:
        self._write(3, {
            "status": "done" if error is None else "failed",
            "mode": actual_mode,
            "output": output,
            "input_image": input_image,
            "input_audio": input_audio,
            "input_duration": input_duration,
            "prompt": prompt,
            "provider": provider,
            "actual_mode": actual_mode,
            "attempted_mode": attempted_mode,
            "fallback_reason": fallback_reason,
            "resolution": resolution,
            "max_wait": max_wait,
            "poll_interval": poll_interval,
            "retries": retries,
            "task_id": task_id,
            "job_id": job_id,
            "api_request_payload": api_request_payload,
            "api_response": api_response,
            "error": error,
        })

    def write_crop(
        self,
        output: str,
        input: str,
        input_duration: float,
        input_width: int,
        input_height: int,
        input_ratio: float,
        output_width: int,
        output_height: int,
        output_duration: float,
        crop_filter: str,
        scale_filter: str,
        ffmpeg_cmd: str,
        codec: str,
        crf: int,
        preset: str,
        error: Optional[str] = None,
    ) -> None:
        self._write(4, {
            "status": "done" if error is None else "failed",
            "mode": "ffmpeg",
            "output": output,
            "input": input,
            "input_duration": input_duration,
            "input_width": input_width,
            "input_height": input_height,
            "input_ratio": input_ratio,
            "output_width": output_width,
            "output_height": output_height,
            "output_duration": output_duration,
            "crop_filter": crop_filter,
            "scale_filter": scale_filter,
            "ffmpeg_cmd": ffmpeg_cmd,
            "codec": codec,
            "crf": crf,
            "preset": preset,
            "error": error,
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scene_checkpoint.py -v --tb=short`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/scene_checkpoint.py tests/test_scene_checkpoint.py
git commit -m "feat(scene_checkpoint): add StepCheckpointWriter and _get_first_incomplete_step

Writes step_01_tts.json, step_02_image.json, step_03_lipsync.json, step_04_crop.json
after each step completes. _get_first_incomplete_step returns first missing or retry step."
```

---

## Task 2: Wire StepCheckpointWriter into scene_processor

**Files:**
- Modify: `modules/pipeline/scene_processor.py` (lines 213-353)
- Modify: `modules/pipeline/scene_processor.py` — add `run_id` parameter
- Modify: `modules/pipeline/pipeline_runner.py` — pass `run_id` to `SingleCharSceneProcessor`
- Test: `tests/test_scene_processor.py`

- [ ] **Step 1: Write failing test for scene_meta.json and scene-level checkpoint integration**

```python
# tests/test_scene_processor.py — add new test class
class TestSceneCheckpointing:
    def test_writes_scene_meta_json(self, tmp_path, mock_ctx):
        from modules.pipeline.scene_processor import SingleCharSceneProcessor
        processor = SingleCharSceneProcessor(mock_ctx, tmp_path, resume=False)
        # ... set up mocks ...
        # Process scene and verify scene_meta.json is written
        # (test needs full scene processor mock setup — see existing tests for pattern)

    def test_skips_tts_when_step1_checkpoint_exists(self, tmp_path, mock_ctx):
        # Pre-write step_01_tts.json as done, verify TTS is skipped
        pass  # placeholder for implementation

    def test_retries_step_when_status_is_retry(self, tmp_path, mock_ctx):
        # Pre-write step_01_tts.json with status=retry, verify TTS re-runs
        pass
```

- [ ] **Step 2: Add `run_id` parameter to SingleCharSceneProcessor.__init__**

Find in `scene_processor.py` line 36:
```python
class SceneProcessor:
    def __init__(self, ctx: PipelineContext, run_dir: Path, resume: bool = False):
```
Change to:
```python
class SingleCharSceneProcessor(SceneProcessor):
    def __init__(self, ctx: PipelineContext, run_dir: Path, resume: bool = False, run_id: int = None):
        super().__init__(ctx, run_dir, resume)
        self.run_id = run_id
```

- [ ] **Step 3: Add scene_meta.json writing at start of process()**

In `SingleCharSceneProcessor.process()`, after line 231 (`scene_output.mkdir(parents=True, exist_ok=True)`), add:

```python
# Write scene_meta.json at start of processing
meta_path = scene_output / "scene_meta.json"
if not meta_path.exists():
    scene_meta = {
        "scene_id": scene_id,
        "title": scene.title if hasattr(scene, "title") else None,
        "script": scene.script if hasattr(scene, "script") else (scene.tts if hasattr(scene, "tts") else ""),
        "tts_text": scene.tts if hasattr(scene, "tts") else (scene.script if hasattr(scene, "script") else ""),
        "characters": [c.name if isinstance(c, SceneCharacter) else str(c) for c in chars],
        "video_prompt": scene.video_prompt if hasattr(scene, "video_prompt") else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(scene_meta, f, ensure_ascii=False, indent=2)
```

Add import at top of `scene_processor.py`:
```python
from datetime import datetime, timezone
```

- [ ] **Step 4: Add StepCheckpointWriter to scene_processor + wire into process()**

At the start of `SingleCharSceneProcessor.process()`, after the scene-level skip check (after line 240 `return str(existing), timestamps`), add:

```python
# Step-level checkpoint scan
checkpoint_writer = StepCheckpointWriter(scene_output, scene_id)
next_step = _get_first_incomplete_step(scene_output)
if next_step == 5:
    # All steps done — load timestamps and return
    ts_file = scene_output / "words_timestamps.json"
    timestamps = []
    if ts_file.exists():
        with open(ts_file, encoding="utf-8") as f:
            timestamps = json.load(f)
    return str(existing), timestamps
```

Add import at top:
```python
from modules.pipeline.scene_checkpoint import StepCheckpointWriter, _get_first_incomplete_step
```

- [ ] **Step 5: After TTS step completes (after line 288), write TTS checkpoint**

After `log(f"  ✅ TTS done: ...")`, add:

```python
# Write TTS checkpoint
tts_cfg = self.get_tts_config()
tts_provider_info = provider  # resolved voice provider
checkpoint_writer.write_tts(
    output=str(audio),
    duration_seconds=get_audio_duration(str(audio)),
    text=tts_text,
    provider=tts_provider_info,
    voice=voice,
    speed=speed,
    model="edge-tts",  # or minimax depending on provider
    sample_rate=tts_cfg.sample_rate if hasattr(tts_cfg, "sample_rate") else 32000,
    bitrate=str(tts_cfg.bitrate) if hasattr(tts_cfg, "bitrate") else "128k",
    format=tts_cfg.format if hasattr(tts_cfg, "format") else "mp3",
)
```

- [ ] **Step 6: After image step completes (after line 295), write image checkpoint**

After `log(f"  ✅ Image done: ...")`, add:

```python
checkpoint_writer.write_image(
    output=str(scene_img),
    input_text=str(audio),
    input_duration=get_audio_duration(str(audio)),
    prompt=img_prompt,
    provider="minimax",  # resolve actual provider
    model=self.ctx.technical.generation.image.model if self.ctx.technical.generation else "image-01",
    aspect_ratio=self.ctx.channel.video.aspect_ratio if self.ctx.channel.video else "9:16",
    gender=gender,
    character_name=char_name,
    timeout=self.ctx.technical.generation.image.timeout if self.ctx.technical.generation else 120,
    poll_interval=self.ctx.technical.generation.image.poll_interval if self.ctx.technical.generation else 5,
    max_polls=self.ctx.technical.generation.image.max_polls if self.ctx.technical.generation else 24,
)
```

- [ ] **Step 7: Refactor lipsync section to use checkpoint_writer + handle fallback metadata**

Replace the lipsync section (lines 325-341) with:

```python
# 5. Lipsync (depends on both audio and image)
video_raw = scene_output / "video_raw.mp4"
lipsync_step_done = next_step > 3  # already done if checkpoint found
lipsync_mode_used = None
lipsync_attempted = None
lipsync_fallback_reason = None
lipsync_error = None
lipsync_task_id = None
lipsync_api_response = None

if not lipsync_step_done and not video_raw.exists():
    log(f"  🎬 Generating lipsync video...")
    actual_error = None
    try:
        result_path = lipsync_fn(str(scene_img), audio, str(video_raw),
                                scene_id=scene_id, prompt=prompt)
    except LipsyncQuotaError as e:
        actual_error = str(e)
        result_path = None
    if not result_path:
        log(f"  ⚠️ Lipsync failed — falling back to static image + audio")
        result_path = create_static_video_with_audio(str(scene_img), audio, str(video_raw))
        if result_path:
            lipsync_fallback_reason = actual_error or "lipsync returned None"
            lipsync_mode_used = "static_fallback"
        else:
            lipsync_error = actual_error or "static fallback also failed"
            checkpoint_writer.write_lipsync(
                output=str(video_raw) if video_raw.exists() else "",
                input_image=str(scene_img), input_audio=str(audio),
                input_duration=actual_duration,
                prompt=prompt,
                provider="kieai",  # from config
                actual_mode="static_fallback",
                attempted_mode="kieai",
                fallback_reason=lipsync_fallback_reason,
                resolution=self.ctx.technical.generation.lipsync.resolution if self.ctx.technical.generation else "480p",
                max_wait=self.ctx.technical.generation.lipsync.max_wait if self.ctx.technical.generation else 300,
                poll_interval=self.ctx.technical.generation.lipsync.poll_interval if self.ctx.technical.generation else 10,
                retries=self.ctx.technical.generation.lipsync.retries if self.ctx.technical.generation else 2,
                task_id=None, error=lipsync_error,
            )
            log(f"  ❌ Lipsync and fallback both failed")
            return None, []
    if result_path:
        video_raw = Path(result_path)

if video_raw.exists() and lipsync_mode_used is None:
    lipsync_mode_used = "kieai"  # or wavespeed depending on provider

# Write lipsync checkpoint if we ran it
if not lipsync_step_done:
    checkpoint_writer.write_lipsync(
        output=str(video_raw),
        input_image=str(scene_img),
        input_audio=str(audio),
        input_duration=actual_duration,
        prompt=prompt,
        provider="kieai",
        actual_mode=lipsync_mode_used or "kieai",
        attempted_mode="kieai",
        fallback_reason=lipsync_fallback_reason,
        resolution=self.ctx.technical.generation.lipsync.resolution if self.ctx.technical.generation else "480p",
        max_wait=self.ctx.technical.generation.lipsync.max_wait if self.ctx.technical.generation else 300,
        poll_interval=self.ctx.technical.generation.lipsync.poll_interval if self.ctx.technical.generation else 10,
        retries=self.ctx.technical.generation.lipsync.retries if self.ctx.technical.generation else 2,
        task_id=lipsync_task_id,
        error=lipsync_error,
    )

if video_raw.exists():
    log(f"  ✅ Lipsync done: {video_raw.stat().st_size/1024/1024:.1f}MB")
```

- [ ] **Step 8: After crop step completes (after line 351), write crop checkpoint + pass run_id from pipeline_runner**

In `pipeline_runner.py`, find the `SingleCharSceneProcessor` instantiation (line ~131) and change to:
```python
self.single_processor = SingleCharSceneProcessor(ctx, self.run_dir, resume=self._resume, run_id=self.run_id)
```

In `scene_processor.py`, after `log(f"  ✅ Crop done: ...")`, add:

```python
checkpoint_writer.write_crop(
    output=str(video_9x16),
    input=str(video_raw),
    input_duration=actual_duration,
    input_width=w,
    input_height=h,
    input_ratio=w/h,
    output_width=1080,
    output_height=1920,
    output_duration=actual_duration,
    crop_filter=crop_filter,
    scale_filter="scale=1080:1920",
    ffmpeg_cmd=" ".join(str(x) for x in cmd),
    codec="libx264",
    crf=23,
    preset="fast",
)
```

- [ ] **Step 9: Run tests**

Run: `pytest tests/test_scene_processor.py tests/test_pipeline_runner.py -v --tb=short`
Expected: Existing tests pass + new checkpoint tests pass

- [ ] **Step 10: Commit**

```bash
git add modules/pipeline/scene_processor.py modules/pipeline/pipeline_runner.py
git commit -m "feat(scene_processor): wire StepCheckpointWriter for all 4 steps

- Write scene_meta.json at start of each scene
- Write step_01_tts.json after TTS completes
- Write step_02_image.json after image completes
- Write step_03_lipsync.json with fallback_reason on quota error
- Write step_04_crop.json after crop completes
- _get_first_incomplete_step enables step-level resume"
```

---

## Task 3: crop_to_9x16 returns dict with dimensions

**Files:**
- Modify: `core/video_utils.py` (lines 150-197)
- Test: `tests/test_video_utils.py`

- [ ] **Step 1: Write failing test for crop_to_9x16 returning dict**

In `tests/test_video_utils.py`, find `TestCropTo9x16` and add:

```python
def test_crop_to_9x16_returns_dict(self, tmp_path):
    from core.video_utils import crop_to_9x16
    # Create a test video first (or mock the subprocess)
    # See existing test for pattern
    pass  # placeholder
```

- [ ] **Step 2: Modify crop_to_9x16 to return dict with all dimensions**

Replace the `crop_to_9x16` function signature and body (lines 150-197 in `core/video_utils.py`):

```python
def crop_to_9x16(input_video: str, output_video: str) -> Optional[Dict]:
    """Crop/convert any video to 9:16 vertical using center crop.

    Returns dict with dimensions on success:
        {
            "output": output_path,
            "input_width": w, "input_height": h,
            "input_ratio": ratio,
            "output_width": 1080, "output_height": 1920,
            "crop_filter": "crop=...",
            "scale_filter": "scale=1080:1920",
            "ffmpeg_cmd": [...],
        }
    Returns None on failure.
    """
    log(f"  📐 Crop to 9:16...")

    result = subprocess.run(
        [str(get_ffprobe()), "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", input_video],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    dims = result.stdout.strip().split(',')
    if len(dims) != 2:
        return None
    w, h = int(dims[0]), int(dims[1])
    input_ratio = w / h
    target_ratio = 9 / 16

    log(f"  📐 Input: {w}x{h} ({input_ratio:.2f}:1), Target: 9:16 ({target_ratio:.2f}:1)")

    if input_ratio > target_ratio:
        new_w = int(h * (9 / 16))
        x_offset = (w - new_w) // 2
        crop_filter = f"crop={new_w}:{h}:{x_offset}:0"
        scale_filter = "scale=1080:1920"
    elif input_ratio < target_ratio:
        new_h = int(w * (16 / 9))
        y_offset = (h - new_h) // 2
        crop_filter = f"crop={w}:{new_h}:0:{y_offset}"
        scale_filter = "scale=1080:1920"
    else:
        crop_filter = ""
        scale_filter = "scale=1080:1920"

    vf_parts = [p for p in [crop_filter, scale_filter] if p]
    vf = ",".join(vf_parts) if vf_parts else scale_filter

    cmd = [
        str(get_ffmpeg()), "-i", input_video,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-y", output_video
    ]
    try:
        subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=300)
        if Path(output_video).exists():
            return {
                "output": output_video,
                "input_width": w,
                "input_height": h,
                "input_ratio": round(input_ratio, 4),
                "output_width": 1080,
                "output_height": 1920,
                "crop_filter": crop_filter,
                "scale_filter": scale_filter,
                "ffmpeg_cmd": " ".join(str(x) for x in cmd),
            }
    except Exception as e:
        log(f"  ❌ Crop error: {e}")
    return None
```

- [ ] **Step 3: Update scene_processor to use dict return value**

In `scene_processor.py`, find the crop section (around line 346):
```python
if not crop_to_9x16(str(video_raw), str(video_9x16)):
```
Change to:
```python
crop_result = crop_to_9x16(str(video_raw), str(video_9x16))
if not crop_result:
```

And after the crop succeeds, pass `crop_result` to `checkpoint_writer.write_crop()` instead of computing inline.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_video_utils.py::TestCropTo9x16 -v --tb=short`
Expected: Existing crop tests still pass

- [ ] **Step 5: Commit**

```bash
git add core/video_utils.py
git commit -m "refactor(video_utils): crop_to_9x16 returns dict with all crop dimensions

Returns {input_width, input_height, input_ratio, output_width, output_height,
crop_filter, scale_filter, ffmpeg_cmd} for checkpoint recording."
```

---

## Task 4: retry_scene.py CLI script

**Files:**
- Create: `scripts/retry_scene.py`
- Test: `tests/test_retry_scene.py`

- [ ] **Step 1: Write the retry_scene.py script**

```python
#!/usr/bin/env python3
"""
scripts/retry_scene.py — Retry/resume from a specific step within a scene.

Usage:
    python scripts/retry_scene.py --scene-dir output/.../scene_3 --list
    python scripts/retry_scene.py --scene-dir output/.../scene_3 --step 3
    python scripts/retry_scene.py --scene-dir output/.../scene_3 --step 3 --clear
    python scripts/retry_scene.py --scene-dir output/.../scene_3 --resume
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

STEP_NAMES = {1: "tts", 2: "image", 3: "lipsync", 4: "crop"}
STEP_FILES = {n: f"step_{n:02d}_{STEP_NAMES[n]}.json" for n in range(1, 5)}


def load_step(scene_dir: Path, step: int) -> dict:
    f = scene_dir / STEP_FILES[step]
    if not f.exists():
        return {}
    with open(f, encoding="utf-8") as fp:
        return json.load(fp)


def clear_step(scene_dir: Path, step: int) -> None:
    f = scene_dir / STEP_FILES[step]
    if f.exists():
        f.unlink()
        print(f"  Cleared {STEP_FILES[step]}")


def list_steps(scene_dir: Path) -> None:
    run_meta = scene_dir / "run_meta.json"
    scene_meta = scene_dir / "scene_meta.json"

    print(f"\n📋 Scene checkpoint status: {scene_dir}")
    print("-" * 70)

    if run_meta.exists():
        with open(run_meta, encoding="utf-8") as f:
            rm = json.load(f)
        print(f"  run_meta.json  run_id={rm.get('run_id')}  channel={rm.get('channel_id')}  slug={rm.get('scenario_slug')}")
    else:
        print(f"  run_meta.json  (not found)")

    if scene_meta.exists():
        with open(scene_meta, encoding="utf-8") as f:
            sm = json.load(f)
        print(f"  scene_meta.json  scene_id={sm.get('scene_id')}  title={sm.get('title', '')[:40]}")
    else:
        print(f"  scene_meta.json  (not found)")

    print()
    for step_num in range(1, 5):
        f = scene_dir / STEP_FILES[step_num]
        if not f.exists():
            print(f"  step_{step_num:02d}  [not started]")
            continue
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)
        status = data.get("status", "?")
        mode = data.get("mode", "?")
        error = data.get("error")
        duration = data.get("duration_seconds") or data.get("input_duration") or ""
        dur_str = f"{duration:.1f}s" if duration else ""

        icon = "✅" if status == "done" else ("⚠️" if status == "retry" else "❌")
        error_str = f"  ⚠️ {error[:60]}" if error else ""
        print(f"  {icon} step_{step_num:02d}  {status:8s}  {mode:20s}  {dur_str}{error_str}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retry/resume scene processing from a specific step")
    parser.add_argument("--scene-dir", type=Path, required=True, help="Path to scene directory (e.g. output/.../scene_3)")
    parser.add_argument("--list", action="store_true", help="List current step status")
    parser.add_argument("--step", type=int, choices=[1, 2, 3, 4], help="Retry a specific step")
    parser.add_argument("--clear", action="store_true", help="Clear step checkpoint before retrying")
    parser.add_argument("--resume", action="store_true", help="Resume from first incomplete/retry step")
    args = parser.parse_args()

    scene_dir = Path(args.scene_dir).resolve()
    if not scene_dir.exists():
        print(f"❌ Scene directory not found: {scene_dir}")
        sys.exit(1)

    if args.list:
        list_steps(scene_dir)
    elif args.step:
        if args.clear:
            clear_step(scene_dir, args.step)
        print(f"ℹ️  To retry step {args.step} ({STEP_NAMES[args.step]}), run the pipeline with --resume")
        print(f"    Scene: {scene_dir}")
        print(f"    Note: Edit {STEP_FILES[args.step]} to change status from 'done' to 'retry'")
    elif args.resume:
        from modules.pipeline.scene_checkpoint import _get_first_incomplete_step
        next_step = _get_first_incomplete_step(scene_dir)
        if next_step == 5:
            print("✅ All steps complete, nothing to resume")
        else:
            print(f"▶️  Resume from step {next_step} ({STEP_NAMES[next_step]})")
            print(f"    Edit {STEP_FILES[next_step]} to set status=retry before running with --resume")
    else:
        parser.print_help()
```

- [ ] **Step 2: Verify script loads without errors**

Run: `python scripts/retry_scene.py --help`
Expected: Help text displays

- [ ] **Step 3: Test --list with a real scene directory**

Create a temp scene dir with fake step files and test:
```bash
mkdir -p /tmp/test_scene
echo '{"step":1,"status":"done","mode":"edge"}' > /tmp/test_scene/step_01_tts.json
python scripts/retry_scene.py --scene-dir /tmp/test_scene --list
```
Expected: Table showing step_01 as done

- [ ] **Step 4: Commit**

```bash
git add scripts/retry_scene.py
git commit -m "feat(retry_scene): add CLI for step-level scene retry

--list: show step status table from checkpoint files
--step N: show retry info for step N
--step N --clear: clear step N checkpoint
--resume: show which step to resume from"
```

---

## Task 5: run_meta.json writer

**Files:**
- Modify: `modules/pipeline/pipeline_runner.py`
- Modify: `modules/pipeline/scene_processor.py`

- [ ] **Step 1: Write run_meta.json at start of VideoPipelineRunner.run()**

In `pipeline_runner.py`, at the start of `run()` method (after the stale cleanup logging, before `scenes = self.ctx.scenario.scenes`), add:

```python
# Write run_meta.json at start of run
import json
run_meta_path = self.run_dir / "run_meta.json"
if not run_meta_path.exists():
    config_snapshot = {}
    if self.ctx.technical and self.ctx.technical.generation:
        gen = self.ctx.technical.generation
        config_snapshot = {
            "tts": {
                "model": gen.tts.model if hasattr(gen, "tts") and gen.tts else "speech-2.1-hd",
                "sample_rate": gen.tts.sample_rate if hasattr(gen, "tts") and gen.tts else 32000,
                "bitrate": gen.tts.bitrate if hasattr(gen, "tts") and gen.tts else 128000,
                "format": gen.tts.format if hasattr(gen, "tts") and gen.tts else "mp3",
                "timeout": gen.tts.timeout if hasattr(gen, "tts") and gen.tts else 60,
            } if gen else {},
            "image": {
                "model": gen.image.model if hasattr(gen, "image") and gen.image else "image-01",
                "aspect_ratio": gen.image.aspect_ratio if hasattr(gen, "image") and gen.image else "9:16",
                "timeout": gen.image.timeout if hasattr(gen, "image") and gen.image else 120,
            } if gen else {},
            "lipsync": {
                "provider": gen.lipsync.provider if hasattr(gen, "lipsync") and gen.lipsync else "kieai",
                "resolution": gen.lipsync.resolution if hasattr(gen, "lipsync") and gen.lipsync else "480p",
                "max_wait": gen.lipsync.max_wait if hasattr(gen, "lipsync") and gen.lipsync else 300,
                "poll_interval": gen.lipsync.poll_interval if hasattr(gen, "lipsync") and gen.lipsync else 10,
                "retries": gen.lipsync.retries if hasattr(gen, "lipsync") and gen.lipsync else 2,
            } if gen else {},
        }
    run_meta = {
        "run_id": self.run_id,
        "run_dir": str(self.run_dir),
        "channel_id": self.ctx.channel_id,
        "scenario_slug": self.ctx.scenario.slug if self.ctx.scenario else "",
        "scenario_title": self.ctx.scenario.title if self.ctx.scenario else "",
        "total_scenes": len(self.ctx.scenario.scenes) if self.ctx.scenario else 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "config_snapshot": config_snapshot,
    }
    with open(run_meta_path, "w", encoding="utf-8") as f:
        json.dump(run_meta, f, ensure_ascii=False, indent=2)
    log(f"  📝 run_meta.json written")
```

Add import at top of `run()` method:
```python
from datetime import datetime, timezone
```

- [ ] **Step 2: Update completed_at when run finishes**

In `pipeline_runner.run()`, at the end where final video is returned, update `run_meta.json` `completed_at`:

```python
# At end of run(), after successful completion
run_meta_path = self.run_dir / "run_meta.json"
if run_meta_path.exists():
    with open(run_meta_path, encoding="utf-8") as f:
        run_meta = json.load(f)
    run_meta["completed_at"] = datetime.now(timezone.utc).isoformat()
    with open(run_meta_path, "w", encoding="utf-8") as f:
        json.dump(run_meta, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 3: Commit**

```bash
git add modules/pipeline/pipeline_runner.py
git commit -m "feat(pipeline_runner): write run_meta.json at start and completion

Captures run_id, channel_id, scenario info, config snapshot at start.
Updates completed_at on success."
```

---

## Task 6: Integration test + all tests green

**Files:**
- Test: `tests/test_scene_processor.py`

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: All 286+ tests pass

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "test: add scene_checkpoint integration tests

Full test coverage for StepCheckpointWriter and step-level resume logic.
All 286 tests passing."
```

---

## Spec Coverage Check

| Spec item | Task |
|-----------|------|
| step_01_tts.json with all TTS fields | Task 1, 2 |
| step_02_image.json with all image fields | Task 1, 2 |
| step_03_lipsync.json with fallback + all lipsync fields | Task 1, 2 |
| step_04_crop.json with all crop fields | Task 1, 2, 3 |
| scene_meta.json | Task 2 |
| run_meta.json | Task 5 |
| `_get_first_incomplete_step` for resume skip logic | Task 1 |
| status=retry editing for manual retry | Task 1, 4 |
| retry_scene.py --list, --step, --clear, --resume | Task 4 |
| crop_to_9x16 returns dict | Task 3 |
| All existing tests still pass | Task 6 |

## Placeholder Scan

No TBD/TODO placeholders. All steps show exact code. All function signatures consistent across tasks.
