#!/usr/bin/env python3
"""
Video Pipeline v3 — CLI entry point.

The heavy lifting is now in modules.pipeline.VideoPipelineRunner.
This file provides backward compatibility for existing callers
and handles CLI argument parsing.
"""

import os
import sys
import time
from pathlib import Path

from core.paths import PROJECT_ROOT
from core.video_utils import log


# ==================== GLOBAL FLAGS (shared with pipeline_runner) ====================
DRY_RUN = False
DRY_RUN_TTS = False
DRY_RUN_IMAGES = False
FORCE_START = False
UPLOAD_TO_SOCIALS = False
USE_STATIC_LIPSYNC = False


# ==================== BACKWARD-COMPATIBLE WRAPPER ====================

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


# ==================== CLI ====================

if __name__ == "__main__":
    config_files = []
    resume_run_dir = None

    # Parse arguments
    config_flag = None
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--dry-run":
            DRY_RUN = True
            log("🔴 DRY RUN MODE: All API calls will be mocked")
        elif arg == "--dry-run-tts":
            DRY_RUN_TTS = True
            log("🔴 DRY RUN TTS MODE: TTS calls will be mocked")
        elif arg == "--dry-run-images":
            DRY_RUN_IMAGES = True
            log("🔴 DRY RUN IMAGES MODE: Image generation will be mocked")
        elif arg == "--upload-to-socials":
            UPLOAD_TO_SOCIALS = True
            log("📤 SOCIAL UPLOAD MODE: Will upload to FB/TikTok after generation")
        elif arg == "--static-lipsync":
            USE_STATIC_LIPSYNC = True
            log("🖼️  STATIC LIPSYNC: Will use static image + TTS audio for video")
        elif arg in ["--config", "-c"] and i + 2 < len(sys.argv):
            config_flag = sys.argv[i + 2]
        elif arg in ["--start", "--fresh"]:
            FORCE_START = True
            log("🆕 FRESH START MODE: Previous scene cache will be cleared")
        elif arg in ["--resume", "-r"]:
            output_base = PROJECT_ROOT / "output"
            for run_folder in sorted(output_base.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
                for rd in sorted(run_folder.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
                    scene_videos = list(rd.glob("scene_*/video_9x16.mp4"))
                    if scene_videos:
                        resume_run_dir = rd
                        break
        else:
            config_files.append(arg)

    # CLI args: channel_id and scenario_path (full path to YAML)
    if len(config_files) >= 2:
        channel_id = config_files[0]
        scenario_path = config_files[1]
    elif len(config_files) == 1:
        # Backward compat: single arg = channel_id only (no scenario, no run)
        print(f"Usage: python video_pipeline_v3.py <channel_id> <scenario_path>")
        print(f"  For direct Python API, use: from scripts.run_pipeline import run_video_pipeline")
        sys.exit(1)
    else:
        print(f"Usage: python video_pipeline_v3.py <channel_id> <scenario_path>")
        sys.exit(1)

    if not Path(scenario_path).exists():
        print(f"Scenario file not found: {scenario_path}")
        sys.exit(1)

    pipeline = VideoPipelineV3(channel_id, scenario_path)

    if resume_run_dir:
        pipeline._runner.run_dir = resume_run_dir
        print(f"Resuming from: {resume_run_dir}")

    result = pipeline.run()
    if result:
        print(f"\n🎉 Output: {result}")
        if UPLOAD_TO_SOCIALS:
            if DRY_RUN:
                print("\n📤 [SOCIAL UPLOAD] Dry-run mode — simulating upload pipeline")
            else:
                print("\n📤 [SOCIAL UPLOAD] Starting upload pipeline...")
            try:
                sys.path.insert(0, str(PROJECT_ROOT))
                from modules.pipeline.publisher import get_publisher
                publisher = get_publisher(
                    dry_run=DRY_RUN,
                    video_run_id=pipeline.run_id,
                    config=pipeline.config,
                )
                publish_result = publisher.upload_to_socials(
                    video_path=result,
                    script=pipeline.config.get("video", {}).get("script", ""),
                    word_timestamps=getattr(pipeline, "word_timestamps", None),
                    srt_output_name=Path(result).stem,
                )
                print(f"\n📤 Social upload result: {publish_result.summary()}")
            except Exception as e:
                print(f"\n⚠️  Social upload skipped/error: {e}")
    else:
        print(f"\n💥 Failed")
        sys.exit(1)
