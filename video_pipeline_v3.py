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


# ==================== BACKWARD-COMPATIBLE WRAPPER ====================

class VideoPipelineV3:
    """Backward-compatible wrapper around VideoPipelineRunner.

    Accepts the same config_path argument as before, loads and merges
    the config, then delegates to VideoPipelineRunner.
    """

    def __init__(self, config_path):
        from modules.pipeline.config_loader import ConfigLoader
        from modules.pipeline.pipeline_runner import VideoPipelineRunner

        global DRY_RUN, DRY_RUN_TTS, DRY_RUN_IMAGES, FORCE_START

        config_path = Path(config_path)

        # Load config via ConfigLoader
        self.cfg = ConfigLoader.load(config_path)

        # Set run directories
        import secrets as _secrets
        self.timestamp = int(time.time())
        self.output_dir = self.cfg.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        date_str = time.strftime("%Y%m%d")

        # Init DB (lazy import to avoid hard psycopg2 dep at module load time)
        import db as _db
        _db.init_db()
        project_name = self.cfg.get("video", {}).get("title", "default")
        project_id = _db.get_or_create_project(project_name)
        config_name = str(config_path)
        self.run_id = _db.start_video_run(project_id, config_name)

        self.run_dir = self.output_dir / date_str / f"{self.timestamp}_{self.run_id}"
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # Update cfg with run info
        self.cfg.run_id = self.run_id
        self.cfg.timestamp = self.timestamp
        self.cfg.run_dir = self.run_dir
        self.cfg.media_dir = self.run_dir / "final"
        self.cfg.media_dir.mkdir(parents=True, exist_ok=True)

        # Instantiate the real runner
        self._runner = VideoPipelineRunner(
            self.cfg,
            dry_run=DRY_RUN,
            dry_run_tts=DRY_RUN_TTS,
            dry_run_images=DRY_RUN_IMAGES,
        )

        # Mirror key state for external consumers
        self.config = self.cfg.data
        self.avatars_dir = self.cfg.avatars_dir
        self.media_dir = self.cfg.media_dir

        log(f"🎬 Video Pipeline v3 - {self.cfg.get('video', {}).get('title', 'Untitled')}")
        log(f"📁 Output: {self.run_dir}")

    def run(self):
        return self._runner.run()


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

    if config_flag:
        config_path = config_flag
    elif len(config_files) == 2:
        config_path = (config_files[0], config_files[1])
    elif len(config_files) == 1:
        config_path = config_files[0]
    else:
        config_path = "configs/business/video_scenario.yaml.example"

    if isinstance(config_path, tuple):
        if not all(Path(p).exists() for p in config_path):
            print(f"❌ Config files not found: {config_path}")
            sys.exit(1)
    elif not Path(config_path).exists():
        # Fallback: try configs/business/{name}.yaml
        name = Path(config_path).name
        fallback = PROJECT_ROOT / "configs" / "business" / f"{name}.yaml"
        if fallback.exists():
            config_path = str(fallback)
        else:
            print(f"❌ Config not found: {config_path}")
            sys.exit(1)

    pipeline = VideoPipelineV3(config_path)

    if resume_run_dir:
        pipeline.run_dir = resume_run_dir
        print(f"📁 Resuming from: {resume_run_dir}")

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
