"""
modules/pipeline/checkpoint.py — Scene-level step checkpointing for crash-resilient pipeline.

Step map (must match db.CHECKPOINT_STEPS):
    1 = tts      → audio_tts.mp3 written
    2 = image    → scene.png written
    3 = lipsync  → video_raw.mp4 written
    4 = crop     → video_9x16.mp4 written
    5 = done     → scene fully complete

Usage in scene processors:
    from modules.pipeline.checkpoint import CheckpointHelper, STEP_TTS, STEP_IMAGE, STEP_LIPSYNC, STEP_CROP, STEP_DONE

    helper = CheckpointHelper(run_id, run_dir)
    next_step = helper.get_next_step(scene_num)

    if next_step == 99:
        return existing_video  # fully done, skip

    # Before each step:
    if next_step > STEP_NUM:
        skip this step (already done)

    # After each step completes successfully:
    helper.save_step(scene_num, STEP_NUM, output_path)
"""

from pathlib import Path
from typing import Optional, Dict

import db

# Step constants (must stay in sync with db.CHECKPOINT_STEPS)
STEP_TTS = 1
STEP_IMAGE = 2
STEP_LIPSYNC = 3
STEP_CROP = 4
STEP_DONE = 5


class CheckpointHelper:
    """Per-run checkpoint helper — creates scene_id strings and proxies to db functions."""

    def __init__(self, run_id: int, run_dir: Path):
        self.run_id = run_id
        self.run_dir = Path(run_dir)

    def _scene_id(self, scene_num: int) -> str:
        """Build the scene_id key used in DB checkpoints."""
        return f"run_{self.run_id}_scene_{scene_num}"

    def get_next_step(self, scene_num: int) -> int:
        """Return the next incomplete step number (1-5), or 99 if fully done."""
        return db.get_next_incomplete_step(self._scene_id(scene_num))

    def is_step_done(self, scene_num: int, step: int) -> bool:
        """Return True if a specific step has a completed checkpoint."""
        cp = db.get_checkpoint_for_step(self._scene_id(scene_num), step)
        return cp is not None

    def save_step(self, scene_num: int, step: int, output_path: str = None) -> None:
        """Save a completed step checkpoint."""
        scene_id = self._scene_id(scene_num)
        db.save_checkpoint(scene_id, step, output_path)

    def load_step(self, scene_num: int) -> Optional[Dict]:
        """Load the highest completed checkpoint for a scene."""
        return db.load_checkpoint(self._scene_id(scene_num))

    def clear(self, scene_num: int) -> None:
        """Delete all checkpoints for a scene."""
        db.clear_checkpoints(self._scene_id(scene_num))

    def get_scene_dir(self, scene_num: int) -> Path:
        """Return the scene output directory path."""
        return self.run_dir / f"scene_{scene_num}"
