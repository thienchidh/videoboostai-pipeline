"""Scene step checkpoint writer for pipeline resume support.

Writes step_XX_*.json files after each pipeline step completes,
enabling resume from the first incomplete step on re-run.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

STEP_NAMES = {
    1: "tts",
    2: "image",
    3: "lipsync",
    4: "crop",
}


def _step_file(scene_dir: Path, step_num: int) -> Path:
    """Return path to step checkpoint file for given step number."""
    name = STEP_NAMES[step_num]
    return scene_dir / f"step_{step_num:02d}_{name}.json"


def _get_first_incomplete_step(scene_dir: Path) -> int:
    """Return first incomplete step number (1-5), where 5 means all done.

    Scans step files 1-4 and returns the first step that is:
    - missing
    - has status "retry"
    - has any status other than "done"

    Returns 5 if all 4 steps are "done".
    """
    for step_num in range(1, 5):
        step_path = _step_file(scene_dir, step_num)
        if not step_path.exists():
            return step_num
        try:
            data = json.loads(step_path.read_text(encoding="utf-8"))
            status = data.get("status", "")
            if status != "done":
                return step_num
        except (json.JSONDecodeError, OSError):
            return step_num
    return 5


def _now_iso() -> str:
    """Return UTC ISO timestamp string."""
    return datetime.now(timezone.utc).isoformat()


class StepCheckpointWriter:
    """Writes step-level checkpoint JSON files for scene processing resume."""

    def __init__(self, scene_dir: Path, scene_id: str) -> None:
        """Initialize writer, creating scene_dir if needed."""
        self.scene_dir = Path(scene_dir)
        self.scene_id = scene_id
        self.scene_dir.mkdir(parents=True, exist_ok=True)

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
        """Write step_01_tts.json checkpoint."""
        fields = {
            "step": 1,
            "name": "tts",
            "status": "done",
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
            "created_at": _now_iso(),
        }
        self._write(1, fields)

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
        """Write step_02_image.json checkpoint."""
        fields = {
            "step": 2,
            "name": "image",
            "status": "done",
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
            "created_at": _now_iso(),
        }
        self._write(2, fields)

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
        """Write step_03_lipsync.json checkpoint with fallback fields."""
        fields = {
            "step": 3,
            "name": "lipsync",
            "status": "done",
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
            "created_at": _now_iso(),
        }
        self._write(3, fields)

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
        """Write step_04_crop.json checkpoint."""
        fields = {
            "step": 4,
            "name": "crop",
            "status": "done",
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
            "created_at": _now_iso(),
        }
        self._write(4, fields)

    def _write(self, step_num: int, fields: dict) -> None:
        """Internal helper: write fields dict to step checkpoint file."""
        step_path = _step_file(self.scene_dir, step_num)
        step_path.write_text(json.dumps(fields, indent=2, ensure_ascii=False), encoding="utf-8")
