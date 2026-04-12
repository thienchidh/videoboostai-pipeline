"""
modules/media/video_compile.py — Video compilation utilities.

NOTE: All functions (concat_videos, crop_to_9x16, add_subtitles,
add_background_music, expand_script) have been consolidated into
core/video_utils.py. This module re-exports them for backward compatibility.
"""

from core.video_utils import (
    concat_videos,
    crop_to_9x16,
    add_subtitles,
    add_background_music,
    expand_script,
    log,
    get_video_duration,
    get_audio_duration,
    upload_file,
    wait_for_job,
)
from core.video_utils import log as logger

__all__ = [
    "concat_videos",
    "crop_to_9x16",
    "add_subtitles",
    "add_background_music",
    "expand_script",
    "get_video_duration",
    "get_audio_duration",
    "upload_file",
    "wait_for_job",
]
