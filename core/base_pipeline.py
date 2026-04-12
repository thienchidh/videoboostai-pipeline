"""
core/base_pipeline.py — Abstract base class for video pipelines.

Provides common methods for scene processing, concatenation,
watermark, and subtitle steps. DRY_RUN flags are shared here.

NOTE: All video processing utilities (crop_to_9x16, concat_videos, add_subtitles,
add_background_music, expand_script, etc.) have been consolidated into
core/video_utils.py. This module re-exports them for backward compatibility.
"""

import os
import sys
import time
import shutil
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.paths import PROJECT_ROOT, get_karaoke_python as _resolve_karaoke_python, get_font_path, get_ffmpeg, get_ffprobe
from core.video_utils import (
    log,
    deep_merge,
    crop_to_9x16,
    concat_videos,
    add_subtitles,
    add_background_music,
    expand_script,
    get_video_duration,
    get_audio_duration,
    upload_file,
    wait_for_job,
    mock_generate_tts,
    mock_generate_image,
    mock_lipsync_video,
    DRY_RUN as _DRY_RUN,
    DRY_RUN_TTS as _DRY_RUN_TTS,
    DRY_RUN_IMAGES as _DRY_RUN_IMAGES,
)

logger = logging.getLogger(__name__)

# ==================== DRY RUN FLAGS (shared global) ====================
DRY_RUN: bool = False
DRY_RUN_TTS: bool = False
DRY_RUN_IMAGES: bool = False


def get_karaoke_python() -> str:
    """Return python with moviepy installed (wrapper for core.paths)."""
    return str(_resolve_karaoke_python())


# Re-export everything from video_utils for backward compatibility
__all__ = [
    "DRY_RUN", "DRY_RUN_TTS", "DRY_RUN_IMAGES",
    "get_karaoke_python", "log", "deep_merge",
    "crop_to_9x16", "concat_videos", "add_subtitles",
    "add_background_music", "expand_script",
    "get_video_duration", "get_audio_duration",
    "upload_file", "wait_for_job",
    "mock_generate_tts", "mock_generate_image", "mock_lipsync_video",
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
            config: Full merged config dict (from ConfigLoader)
            run_dir: Override run output directory
        """
        self.config = config
        self.timestamp = int(time.time())
        self.project_root = PROJECT_ROOT
        date_str = time.strftime("%Y%m%d")  # YYYYMMDD format

        if run_dir:
            self.run_dir = Path(run_dir)
            self.output_dir = self.run_dir.parent
        else:
            self.output_dir = self.project_root / "output"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.run_dir = self.output_dir / date_str / f"{self.timestamp}"
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

        text = wm_cfg.get("text", "@NangSuatThongMinh")
        font_size = wm_cfg.get("font_size", 36)
        opacity = wm_cfg.get("opacity", 0.35)

        log(f"  💧 Adding watermark: '{text}' (opacity={opacity})")

        try:
            result = subprocess.run(
                [str(get_ffprobe()), "-v", "quiet", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "json", str(video_path)],
                capture_output=True, text=True
            )
            info = json.loads(result.stdout)
            vw = int(info['streams'][0]['width'])
            vh = int(info['streams'][0]['height'])

            scale = vh / 1920
            scaled_font_size = int(font_size * scale)

            from PIL import Image, ImageDraw, ImageFont
            overlay = Image.new('RGBA', (vw, vh), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            try:
                font_path = self.config.get("fonts", {}).get("watermark") or get_font_path()
                fnt = ImageFont.truetype(font_path, scaled_font_size)
            except Exception:
                fnt = ImageFont.load_default()

            x = vw - int(280 * scale)
            y = vh - int(70 * scale)
            alpha = int(255 * opacity)
            draw.text((x, y), text, font=fnt, fill=(0, 0, 0, int(alpha * 0.8)))
            draw.text((x, y), text, font=fnt, fill=(255, 255, 255, alpha))

            overlay_path = self.run_dir / "watermark_overlay.png"
            overlay.save(str(overlay_path))

            tmp_wm = self.run_dir / "watermark_tmp.mp4"
            cmd = [
                str(get_ffmpeg()), "-y", "-i", str(video_path), "-i", str(overlay_path),
                "-filter_complex", "[0:v][1:v]overlay=0:0[out]",
                "-map", "[out]", "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-c:a", "copy",
                str(tmp_wm)
            ]
            result2 = subprocess.run(cmd, capture_output=True, timeout=300)
            if result2.returncode == 0 and tmp_wm.exists():
                shutil.copy(tmp_wm, output_path)
                log(f"  ✅ Watermark added")
                return output_path
            else:
                log(f"  ⚠️ Watermark failed: {result2.stderr[:200] if result2.stderr else 'unknown'}")
        except Exception as e:
            log(f"  ⚠️ Watermark error: {e}")
        return video_path
