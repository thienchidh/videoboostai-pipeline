#!/usr/bin/env python3
"""
Unified Pipeline Entry Point - Content Generation + Video Production.

Can be called directly from Python without CLI:

    from scripts.run_pipeline import run_content_pipeline, run_video_pipeline, run_full_pipeline

    # Content generation only
    result = run_content_pipeline(channel_id="nang_suat_thong_minh", ideas_count=3)

    # Video production only
    video_path, timestamps = run_video_pipeline(
        channel_id="nang_suat_thong_minh",
        scenario_path="configs/channels/nang_suat_thong_minh/scenarios/productivity-wikipedia.yaml"
    )

    # Full pipeline (content + video)
    result = run_full_pipeline(channel_id="nang_suat_thong_minh", ideas_count=3)
"""

import sys
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.video_utils import log

# Global flags for video pipeline (set these before calling run_* functions)
DRY_RUN = False
DRY_RUN_TTS = False
DRY_RUN_IMAGES = False
UPLOAD_TO_SOCIALS = False
USE_STATIC_LIPSYNC = False

# Load log level from TechnicalConfig
_log_cfg = None
try:
    from modules.pipeline.models import TechnicalConfig
    _tech = TechnicalConfig.load()
    _log_cfg = _tech.logging.level
except Exception:
    _log_cfg = "INFO"

_log_level = getattr(logging, _log_cfg.upper(), logging.INFO)
logging.basicConfig(level=_log_level, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ==================== CONTENT PIPELINE ====================

def run_content_pipeline(channel_id: str, ideas_count: int = 3, dry_run: bool = False):
    """Run content generation cycle: research -> ideas -> scripts.

    Args:
        channel_id: Channel identifier (e.g., 'nang_suat_thong_minh')
        ideas_count: Number of ideas to generate
        dry_run: If True, skip actual API calls

    Returns:
        List of idea dicts with script_json ready for video production
    """
    from modules.content.content_pipeline import ContentPipeline

    project_id = get_or_create_project(
        name=channel_id.replace("_", " ").title(),
        config_file=f"configs/channels/{channel_id}/config.yaml"
    )
    pipeline = ContentPipeline(
        project_id=project_id,
        config=config,
        dry_run=dry_run,
        channel_id=channel_id,
    )

    logger.info("=" * 60)
    logger.info("CONTENT PIPELINE - Content Generation")
    logger.info("=" * 60)
    logger.info(f"  Channel: {channel_id}")
    logger.info(f"  Ideas count: {ideas_count}")
    logger.info(f"  Dry run: {dry_run}")

    logger.info("Starting content cycle...")
    results = pipeline.run_full_cycle(num_ideas=ideas_count)
    logger.info(f"Content cycle done: {results}")

    ideas = pipeline.idea_gen.get_ideas_by_status(status="script_ready", limit=ideas_count)
    logger.info(f"Found {len(ideas)} ideas with scripts")
    for i, idea in enumerate(ideas):
        title = idea.get("title", "Untitled")
        idea_id = idea.get("id")
        logger.info(f"  [{i+1}] ID={idea_id}: {title[:50]}")

    return ideas


# ==================== VIDEO PIPELINE ====================

def run_video_pipeline(channel_id: str, scenario_path: str,
                      dry_run: bool = False, dry_run_tts: bool = False,
                      dry_run_images: bool = False, resume: bool = False) -> tuple:
    """Run video production from a scenario YAML file.

    Args:
        channel_id: Channel identifier (e.g., 'nang_suat_thong_minh')
        scenario_path: Full path to scenario YAML file
        dry_run: Mock all API calls
        dry_run_tts: Mock TTS only
        dry_run_images: Mock image gen only

    Returns:
        Tuple of (video_path, word_timestamps)
    """
    global DRY_RUN, DRY_RUN_TTS, DRY_RUN_IMAGES, USE_STATIC_LIPSYNC

    DRY_RUN = dry_run
    DRY_RUN_TTS = dry_run_tts
    DRY_RUN_IMAGES = dry_run_images

    from scripts.video_pipeline_v3 import VideoPipelineV3

    logger.info("=" * 60)
    logger.info("VIDEO PIPELINE")
    logger.info("=" * 60)
    logger.info(f"  Channel: {channel_id}")
    logger.info(f"  Scenario: {scenario_path}")
    logger.info(f"  Dry run: {dry_run}, TTS: {dry_run_tts}, Images: {dry_run_images}")

    pipeline = VideoPipelineV3(channel_id, scenario_path, resume=resume)
    logger.info(f"  Title: {pipeline.ctx.scenario.title}")
    logger.info(f"  Scenes: {len(pipeline.ctx.scenario.scenes)}")
    logger.info(f"  Run ID: {pipeline.run_id}")
    logger.info(f"  Output: {pipeline.run_dir}")

    logger.info("Starting video generation...")
    video_path = pipeline.run()

    if video_path:
        logger.info(f"Video generated: {video_path}")
    else:
        logger.error("Video generation failed")

    return video_path, getattr(pipeline, 'word_timestamps', [])


# ==================== FULL PIPELINE ====================

def run_full_pipeline(channel_id: str, ideas_count: int = 1, produce: bool = True,
                       skip_lipsync: bool = False, skip_content: bool = False,
                       scenario_path: str = None, resume: bool = False) -> dict:
    """Run full pipeline: content generation + video production.

    Args:
        channel_id: Channel identifier
        ideas_count: Number of ideas to generate
        produce: If True, run video production after content generation
        skip_lipsync: If True, use static image + audio (skip lipsync API to save costs)
        skip_content: If True, skip content generation and use existing scripts
        scenario_path: Path to scenario YAML file. When skip_content=True and this is set,
                       run video production for this specific scenario instead of querying DB.

    Returns:
        Dict with:
            - ideas: list of idea dicts
            - videos: list of video result dicts (if produce=True)
    """
    # When skip_content=True and scenario_path is provided, run video for specific scenario
    if skip_content and scenario_path:
        logger.info("=" * 60)
        logger.info("FULL PIPELINE - Video Only (specific scenario)")
        logger.info("=" * 60)
        logger.info(f"  Channel: {channel_id}")
        logger.info(f"  Scenario: {scenario_path}")

        video_path, timestamps = run_video_pipeline(
            channel_id=channel_id,
            scenario_path=scenario_path,
            dry_run=False,
            dry_run_tts=False,
            dry_run_images=False,
            resume=resume,
        )
        return {"videos": [{"scenario": scenario_path, "video_path": video_path}]}

    from modules.content.content_pipeline import ContentPipeline

    from db import get_or_create_project

    project_id = get_or_create_project(
        name=channel_id.replace("_", " ").title(),
        config_file=f"configs/channels/{channel_id}/config.yaml"
    )

    pipeline = ContentPipeline(
        project_id=project_id,
        config=None,
        dry_run=False,
        channel_id=channel_id,
        skip_lipsync=skip_lipsync,
        skip_content=skip_content,
    )

    logger.info("=" * 60)
    logger.info("FULL PIPELINE - Content + Video")
    logger.info("=" * 60)
    logger.info(f"  Channel: {channel_id}")
    logger.info(f"  Ideas count: {ideas_count}")
    logger.info(f"  Produce: {produce}")
    if skip_lipsync:
        logger.info(f"  ⚠️  SKIP LIPSYNC: using static image + audio (saves API costs)")

    # Step 1: Content Generation + Production
    logger.info("")
    logger.info("STEP 1: Content Generation")
    logger.info(f"  Running content cycle for {ideas_count} ideas...")

    results = pipeline.run_full_cycle(num_ideas=ideas_count)
    logger.info(f"  Content cycle done: {results}")

    # run_full_cycle already produced videos — use its results directly
    video_results = results.get("produced", [])
    success_count = sum(1 for v in video_results if v.get("result", {}).get("success"))
    fail_count = len(video_results) - success_count

    ideas = pipeline.idea_gen.get_ideas_by_status(status="script_ready", limit=ideas_count)
    logger.info(f"  Found {len(ideas)} ideas ready for production")

    if not ideas and not video_results:
        logger.warning("  No ideas generated and no videos produced!")
        return {"ideas": [], "videos": []}

    logger.info("")
    logger.info("=" * 60)
    logger.info("FULL PIPELINE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Total ideas generated: {results.get('ideas_generated', 0)}")
    logger.info(f"  Scripts generated: {results.get('scripts_generated', 0)}")
    logger.info(f"  Videos produced: {success_count}")
    logger.info(f"  Videos failed: {fail_count}")

    return {"ideas": ideas, "videos": video_results, "cycle_results": results}


# ==================== CLI ====================

if __name__ == "__main__":
    import argparse

    # Initialize DB schema if not exists
    from db import init_db_full, get_or_create_project
    try:
        init_db_full()
        logger.info("DB schema ready")
    except Exception as e:
        logger.warning(f"DB init skipped (may already exist): {e}")

    parser = argparse.ArgumentParser(description="Unified Pipeline")
    parser.add_argument("--channel", default=None, help="Channel ID (default: all channels)")
    parser.add_argument("--all", action="store_true", help="Run for all channels in configs/channels/")
    parser.add_argument("--ideas", type=int, default=1, help="Number of ideas")
    parser.add_argument("--produce", action="store_true", help="Run video production")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    parser.add_argument("--dry-run-tts", action="store_true", help="Dry run TTS")
    parser.add_argument("--dry-run-images", action="store_true", help="Dry run images")
    parser.add_argument("--skip-lipsync", action="store_true", help="Skip lipsync (use static image + audio to save API costs)")
    parser.add_argument("--skip-content", action="store_true", help="Skip content generation, only run video production (requires existing script_json in DB)")
    parser.add_argument("--scenario", type=str, default=None,
        help="Path to scenario YAML file. When used with --skip-content, runs video production for this specific scenario.")
    parser.add_argument("--resume", action="store_true",
        help="Resume video production from last checkpoint (skip completed scenes)")

    args = parser.parse_args()

    # Get list of channels to process
    if args.all:
        channels_dir = Path(__file__).parent.parent / "configs" / "channels"
        channels = [d.name for d in channels_dir.iterdir() if d.is_dir()]
        logger.info(f"Found {len(channels)} channels: {', '.join(channels)}")
    elif args.channel:
        channels = [args.channel]
    else:
        raise ValueError("No channel specified: use --channel or --all")

    for ch in channels:
        logger.info(f"\n{'='*50}")
        logger.info(f"Processing channel: {ch}")
        logger.info(f"{'='*50}")
        
        if args.produce:
            if args.skip_content and args.scenario:
                # Skip content, run specific scenario
                result = run_full_pipeline(
                    channel_id=ch,
                    ideas_count=args.ideas,
                    produce=True,
                    skip_lipsync=args.skip_lipsync,
                    skip_content=True,
                    scenario_path=args.scenario,
                    resume=args.resume,
                )
            elif args.skip_content:
                # Skip content, run video for all script_ready ideas from DB
                result = run_full_pipeline(
                    channel_id=ch,
                    ideas_count=args.ideas,
                    produce=True,
                    skip_lipsync=args.skip_lipsync,
                    skip_content=True,
                    resume=args.resume,
                )
            else:
                result = run_full_pipeline(
                    channel_id=ch,
                    ideas_count=args.ideas,
                    produce=True,
                    skip_lipsync=args.skip_lipsync,
                    skip_content=False,
                    resume=args.resume,
                )
            logger.info(f"Result for {ch}: {result}")
        else:
            ideas = run_content_pipeline(
                channel_id=ch,
                ideas_count=args.ideas,
                dry_run=args.dry_run,
            )
            logger.info(f"Generated {len(ideas)} ideas for {ch}")
            print(f"\nGot {len(ideas)} ideas")
