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
        scenario_path="configs/channels/nang_suat_thong_minh/scenarios/2026-04-13/productivity-wikipedia.yaml"
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
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

    config = _load_content_config()

    pipeline = ContentPipeline(
        project_id=1,
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


def _load_content_config(channel_id: str = None):
    """Load business config for content pipeline."""
    import yaml
    config_path = PROJECT_ROOT / "configs/business/video_scenario.yaml.example"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


# ==================== VIDEO PIPELINE ====================

def run_video_pipeline(channel_id: str, scenario_path: str,
                      dry_run: bool = False, dry_run_tts: bool = False,
                      dry_run_images: bool = False) -> tuple:
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

    pipeline = VideoPipelineV3(channel_id, scenario_path)
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

def run_full_pipeline(channel_id: str, ideas_count: int = 1, produce: bool = True) -> dict:
    """Run full pipeline: content generation + video production.

    Args:
        channel_id: Channel identifier
        ideas_count: Number of ideas to generate
        produce: If True, run video production after content generation

    Returns:
        Dict with:
            - ideas: list of idea dicts
            - videos: list of video result dicts (if produce=True)
    """
    from modules.content.content_pipeline import ContentPipeline

    config = _load_content_config()
    pipeline = ContentPipeline(
        project_id=1,
        config=config,
        dry_run=False,
        channel_id=channel_id,
    )

    logger.info("=" * 60)
    logger.info("FULL PIPELINE - Content + Video")
    logger.info("=" * 60)
    logger.info(f"  Channel: {channel_id}")
    logger.info(f"  Ideas count: {ideas_count}")
    logger.info(f"  Produce: {produce}")

    # Step 1: Content Generation
    logger.info("")
    logger.info("STEP 1: Content Generation")
    logger.info(f"  Running content cycle for {ideas_count} ideas...")

    results = pipeline.run_full_cycle(num_ideas=ideas_count)
    logger.info(f"  Content cycle done: {results}")

    ideas = pipeline.idea_gen.get_ideas_by_status(status="script_ready", limit=ideas_count)
    logger.info(f"  Found {len(ideas)} ideas ready for production")

    if not ideas:
        logger.warning("  No ideas with scripts found!")
        return {"ideas": [], "videos": []}

    if not produce:
        logger.info("  Skipping video production (produce=False)")
        return {"ideas": ideas, "videos": []}

    # Step 2: Video Production for each idea
    logger.info("")
    logger.info("STEP 2: Video Production")
    logger.info(f"  Producing {len(ideas)} videos...")

    video_results = []
    success_count = 0
    fail_count = 0

    for idea in ideas:
        idea_id = idea.get("id")
        script_json = idea.get("script_json")
        if not script_json:
            logger.warning(f"  Idea {idea_id} has no script, skipping")
            continue

        title = idea.get("title", f"idea_{idea_id}")
        logger.info("")
        logger.info(f"  [{len(video_results)+1}/{len(ideas)}] Producing: {title[:50]}...")

        try:
            prod_result = pipeline.produce_video(idea_id)

            if prod_result.get("success"):
                video_path = prod_result.get("output_video")
                run_dir = prod_result.get("run_dir", "N/A")
                logger.info(f"    SUCCESS: {video_path}")
                logger.info(f"    Run dir: {run_dir}")
                video_results.append({
                    "idea_id": idea_id,
                    "title": title,
                    "video_path": video_path,
                })
                success_count += 1
            else:
                error = prod_result.get('error', 'Unknown error')
                logger.error(f"    FAILED: {error}")
                video_results.append({
                    "idea_id": idea_id,
                    "title": title,
                    "failed": True,
                    "error": error,
                })
                fail_count += 1
        except Exception as e:
            logger.error(f"    ERROR: {e}")
            video_results.append({
                "idea_id": idea_id,
                "title": title,
                "failed": True,
                "error": str(e),
            })
            fail_count += 1

    logger.info("")
    logger.info("=" * 60)
    logger.info("FULL PIPELINE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Total ideas: {len(ideas)}")
    logger.info(f"  Videos produced: {success_count}")
    logger.info(f"  Videos failed: {fail_count}")

    return {"ideas": ideas, "videos": video_results}


# ==================== CLI ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Unified Pipeline")
    parser.add_argument("--channel", default="nang_suat_thong_minh", help="Channel ID")
    parser.add_argument("--ideas", type=int, default=1, help="Number of ideas")
    parser.add_argument("--produce", action="store_true", help="Run video production")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    parser.add_argument("--dry-run-tts", action="store_true", help="Dry run TTS")
    parser.add_argument("--dry-run-images", action="store_true", help="Dry run images")

    args = parser.parse_args()

    if args.produce:
        result = run_full_pipeline(
            channel_id=args.channel,
            ideas_count=args.ideas,
            produce=True,
        )
        print(f"\nResult: {result}")
    else:
        ideas = run_content_pipeline(
            channel_id=args.channel,
            ideas_count=args.ideas,
            dry_run=args.dry_run,
        )
        print(f"\nGot {len(ideas)} ideas")
