#!/usr/bin/env python3
"""
Unified Pipeline Entry Point — Content Generation + Video Production.

Can be called directly from Python without CLI:

    from scripts.run_pipeline import run_content_pipeline, run_video_pipeline, run_full_pipeline

    # Content generation only
    result = run_content_pipeline(channel_id="nang_suat_thong_minh", topics=["productivity"])

    # Video production only
    video_path, timestamps = run_video_pipeline(
        channel_id="nang_suat_thong_minh",
        scenario_path="configs/channels/nang_suat_thong_minh/scenarios/2026-04-13/productivity-wikipedia.yaml"
    )

    # Full pipeline (content + video)
    result = run_full_pipeline(channel_id="nang_suat_thong_minh", topics=["productivity"])
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

def run_content_pipeline(channel_id: str, topics: list[str] = None, ideas_count: int = 3, dry_run: bool = False):
    """Run content generation cycle: research → ideas → scripts.

    Args:
        channel_id: Channel identifier (e.g., 'nang_suat_thong_minh')
        topics: List of topic keywords to research
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
    logger.info("CONTENT PIPELINE — Content Generation")
    logger.info("=" * 60)

    results = pipeline.run_full_cycle(num_ideas=ideas_count)
    logger.info(f"Content cycle results: {results}")

    ideas = pipeline.idea_gen.get_ideas_by_status(status="script_ready", limit=ideas_count)
    logger.info(f"Ideas ready for production: {len(ideas)}")

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
                      dry_run_images: bool = False) -> tuple[str, list]:
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

    # Update global flags
    DRY_RUN = dry_run
    DRY_RUN_TTS = dry_run_tts
    DRY_RUN_IMAGES = dry_run_images

    from scripts.video_pipeline_v3 import VideoPipelineV3

    logger.info("=" * 60)
    logger.info("VIDEO PIPELINE")
    logger.info("=" * 60)

    pipeline = VideoPipelineV3(channel_id, scenario_path)
    video_path = pipeline.run()

    return video_path, getattr(pipeline, 'word_timestamps', [])


# ==================== FULL PIPELINE ====================

def run_full_pipeline(channel_id: str, topics: list[str] = None,
                     ideas_count: int = 3, produce: bool = True) -> dict:
    """Run full pipeline: content generation + video production.

    Args:
        channel_id: Channel identifier
        topics: List of topic keywords to research
        ideas_count: Number of ideas to generate
        produce: If True, run video production after content generation

    Returns:
        Dict with:
            - ideas: list of idea dicts
            - videos: list of video result dicts (if produce=True)
    """
    from modules.content.content_pipeline import ContentPipeline
    from scripts.video_pipeline_v3 import VideoPipelineV3

    config = _load_content_config()
    pipeline = ContentPipeline(
        project_id=1,
        config=config,
        dry_run=False,
        channel_id=channel_id,
    )

    logger.info("=" * 60)
    logger.info("FULL PIPELINE — Content + Video")
    logger.info("=" * 60)

    # Step 1: Content Generation
    logger.info("STEP 1: Content Generation")
    results = pipeline.run_full_cycle(num_ideas=ideas_count)
    ideas = pipeline.idea_gen.get_ideas_by_status(status="script_ready", limit=ideas_count)
    logger.info(f"Got {len(ideas)} ideas ready for production")

    if not produce:
        return {"ideas": ideas, "videos": []}

    # Step 2: Video Production for each idea
    logger.info("STEP 2: Video Production")
    video_results = []

    for idea in ideas:
        idea_id = idea.get("id")
        script_json = idea.get("script_json")
        if not script_json:
            logger.warning(f"  Idea {idea_id} has no script, skipping")
            continue

        title = idea.get("title", f"idea_{idea_id}")
        logger.info(f"  Producing video for idea {idea_id}: {title[:50]}...")

        try:
            # produce_video saves the YAML and runs VideoPipelineV3
            prod_result = pipeline.produce_video(idea_id)

            if prod_result.get("success"):
                video_path = prod_result.get("output_video")
                logger.info(f"    Video: {video_path}")
                video_results.append({
                    "idea_id": idea_id,
                    "title": title,
                    "video_path": video_path,
                })
            else:
                logger.error(f"    Failed: {prod_result.get('error')}")
                video_results.append({
                    "idea_id": idea_id,
                    "title": title,
                    "failed": True,
                    "error": prod_result.get("error"),
                })
        except Exception as e:
            logger.error(f"    Error: {e}")
            video_results.append({
                "idea_id": idea_id,
                "title": title,
                "failed": True,
                "error": str(e),
            })

    return {"ideas": ideas, "videos": video_results}


# ==================== CLI ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Unified Pipeline")
    parser.add_argument("--channel", default="nang_suat_thong_minh", help="Channel ID")
    parser.add_argument("--topics", nargs="+", help="Topic keywords")
    parser.add_argument("--ideas", type=int, default=3, help="Number of ideas")
    parser.add_argument("--produce", action="store_true", help="Run video production")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    parser.add_argument("--dry-run-tts", action="store_true", help="Dry run TTS")
    parser.add_argument("--dry-run-images", action="store_true", help="Dry run images")

    args = parser.parse_args()

    global DRY_RUN, DRY_RUN_TTS, DRY_RUN_IMAGES
    DRY_RUN = args.dry_run
    DRY_RUN_TTS = args.dry_run_tts
    DRY_RUN_IMAGES = args.dry_run_images

    if args.produce:
        result = run_full_pipeline(
            channel_id=args.channel,
            topics=args.topics,
            ideas_count=args.ideas,
            produce=True,
        )
        print(f"\nResult: {result}")
    else:
        ideas = run_content_pipeline(
            channel_id=args.channel,
            topics=args.topics,
            ideas_count=args.ideas,
            dry_run=args.dry_run,
        )
        print(f"\nGot {len(ideas)} ideas")
