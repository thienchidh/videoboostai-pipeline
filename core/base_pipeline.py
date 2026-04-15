"""
core/base_pipeline.py — Abstract base class for video pipelines.

Provides common methods for scene processing, concatenation,
watermark, and subtitle steps. DRY_RUN flags are shared here.

NOTE: All video processing utilities (crop_to_9x16, concat_videos, add_subtitles,
add_background_music) have been consolidated into
core/video_utils.py. This module re-exports them for backward compatibility.
"""

import os
import sys
import time
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.paths import PROJECT_ROOT
from core.video_utils import (
    log,
    deep_merge,
    crop_to_9x16,
    concat_videos,
    add_subtitles,
    add_background_music,
    add_static_watermark,
    get_video_duration,
    get_audio_duration,
    get_video_info,
    upload_file,
    wait_for_job,
    mock_generate_tts,
    mock_generate_image,
    create_static_video_with_audio,
)

logger = logging.getLogger(__name__)


# Re-export everything from video_utils for backward compatibility
__all__ = [
    "log", "deep_merge",
    "crop_to_9x16", "concat_videos", "add_subtitles",
    "add_background_music",
    "get_video_duration", "get_audio_duration",
    "upload_file", "wait_for_job",
    "mock_generate_tts", "mock_generate_image", "create_static_video_with_audio",
]


# ==================== BASE PIPELINE ====================

class BasePipeline(ABC):
    """Abstract base class for video pipelines.

    Subclasses must implement:
    - _process_single_scene() — generate TTS, image, lipsync for one scene
    - get_character() — return character config dict by name
    - build_scene_prompt() — build image generation prompt for a scene
    """

    def __init__(self, config: Dict[str, Any], run_dir: Optional[Path] = None):
        """
        Args:
            config: Full merged config dict (from PipelineContext)
            run_dir: Override run output directory
        """
        self.config = config
        self.timestamp = int(time.time())
        self.project_root = PROJECT_ROOT

        if run_dir:
            self.run_dir = Path(run_dir)
            self.output_dir = self.run_dir.parent
        else:
            self.output_dir = self.project_root / "output"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            # Extract channel_id and slug from config for new output dir structure
            channel_id = self.config.get("channel_id", "default")
            slug = self.config.get("slug") or self.config.get("scenario", {}).get("slug") or "run"
            self.run_dir = self.output_dir / channel_id / f"{slug}_{self.timestamp}"
            self.run_dir.mkdir(parents=True, exist_ok=True)

        log(f"🎬 BasePipeline initialized — output: {self.run_dir}")

    # ---- Step tracking (resume logic) ----

    def _check_step(self, scene_id: int, step: str) -> bool:
        state_file = self.run_dir / f"scene_{scene_id}" / f".step_{step}"
        return state_file.exists()

    def _mark_step(self, scene_id: int, step: str) -> None:
        scene_dir = self.run_dir / f"scene_{scene_id}"
        scene_dir.mkdir(exist_ok=True)
        state_file = scene_dir / f".step_{step}"
        state_file.touch()
        log(f"  ✅ Step [{step}] marked complete")

    # ---- Scene processing (to be implemented by subclass) ----

    @abstractmethod
    def _process_single_scene(self, scene: Dict[str, Any]) -> Optional[str]:
        """Process a single scene end-to-end. Return path to 9:16 cropped video."""
        ...

    @abstractmethod
    def get_character(self, name: str) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def build_scene_prompt(self, scene: Dict[str, Any]) -> str:
        ...

    # ---- Orchestration ----

    def run_scene(self, scene_idx: int) -> Optional[str]:
        """Process one scene by index. Returns video path or None."""
        scenes = self.config.get("scenes", [])
        if scene_idx < 0 or scene_idx >= len(scenes):
            log(f"❌ Scene index {scene_idx} out of range")
            return None
        scene = scenes[scene_idx]
        return self._process_single_scene(scene)

    # ---- Video utilities (delegated to video_utils) ----
    # These methods are re-exports from core/video_utils.py for convenience.
    # The canonical implementations live in core/video_utils.py.

    def concatenate_scenes(self, video_paths: List[str], output_path: str) -> Optional[str]:
        """Concatenate multiple scene videos into one."""
        return concat_videos(video_paths, output_path, run_dir=self.run_dir)

    def apply_watermark(self, video_path: str, output_path: str) -> str:
        """Add watermark overlay to video (static mode only).

        For bounce mode, use bounce_watermark.py directly.
        Note: bounce mode is implemented in VideoPipelineV3.add_watermark().
        """
        wm_cfg = self.config.get("watermark", {})
        if not wm_cfg.get("enable", False):
            log(f"  ℹ️ Watermark disabled")
            return video_path

        text = wm_cfg.get("text")
        if not text:
            raise ValueError("config.watermark.text is required when watermark is enabled")
        font_size = wm_cfg.get("font_size")
        if not font_size:
            raise ValueError("config.watermark.font_size is required when watermark is enabled")
        opacity = wm_cfg.get("opacity")
        if not (isinstance(opacity, (int, float)) and opacity >= 0):
            raise ValueError("config.watermark.opacity is required when watermark is enabled")
        font_path = self.config.get("fonts", {}).get("watermark")

        log(f"  💧 Adding watermark: '{text}' (opacity={opacity})")
        return add_static_watermark(
            video_path, output_path,
            text=text, font_size=font_size, opacity=opacity,
            font_path=font_path, run_dir=self.run_dir
        )
