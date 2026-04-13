#!/usr/bin/env python3
"""
Video Pipeline v3 — thin wrapper around VideoPipelineRunner.

Usage (Python API):
    from scripts.video_pipeline_v3 import VideoPipelineV3

    pipeline = VideoPipelineV3(
        channel_id="nang_suat_thong_minh",
        scenario_path="configs/channels/nang_suat_thong_minh/scenarios/2026-04-13/scenario.yaml"
    )
    video_path = pipeline.run()
"""

import time

from core.video_utils import log


# ==================== GLOBAL FLAGS (shared with pipeline_runner) ====================
DRY_RUN = False
DRY_RUN_TTS = False
DRY_RUN_IMAGES = False
UPLOAD_TO_SOCIALS = False
USE_STATIC_LIPSYNC = False


# ==================== WRAPPER ====================

class VideoPipelineV3:
    """Thin wrapper around VideoPipelineRunner.

    Args:
        channel_id: Channel identifier (e.g., 'nang_suat_thong_minh')
        scenario_path: Full path to scenario YAML file.
    """

    def __init__(self, channel_id: str, scenario_path: str):
        from modules.pipeline.config import PipelineContext
        from modules.pipeline.pipeline_runner import VideoPipelineRunner

        global DRY_RUN, DRY_RUN_TTS, DRY_RUN_IMAGES, USE_STATIC_LIPSYNC

        self.ctx = PipelineContext(channel_id, scenario_path=scenario_path)

        self.timestamp = int(time.time())

        # Instantiate the real runner (handles DB setup + run_id internally)
        self._runner = VideoPipelineRunner(
            self.ctx,
            dry_run=DRY_RUN,
            dry_run_tts=DRY_RUN_TTS,
            dry_run_images=DRY_RUN_IMAGES,
            use_static_lipsync=USE_STATIC_LIPSYNC,
            timestamp=self.timestamp,
        )

        # Mirror key state for external consumers
        self.config = {
            "video": {"title": self.ctx.scenario.title if self.ctx.scenario else "Untitled"},
        }
        self.avatars_dir = self._runner.run_dir / "avatars"
        self.media_dir = self._runner.media_dir

        log(f"Video Pipeline - {self.ctx.scenario.title if self.ctx.scenario else 'Untitled'}")
        log(f"Output: {self._runner.run_dir}")

    @property
    def run_id(self):
        return self._runner.run_id

    @property
    def run_dir(self):
        return self._runner.run_dir

    def run(self):
        video_path, word_timestamps = self._runner.run()
        self.word_timestamps = word_timestamps
        return video_path
