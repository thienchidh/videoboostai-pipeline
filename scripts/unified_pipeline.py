#!/usr/bin/env python3
"""
Unified Pipeline — Content Generation + Video Production in one flow.

Entry point: python -m scripts.unified_pipeline [options]

Options:
  --dry-run              Content cycle only, no video production
  --dry-run-tts          TTS calls will be mocked in video production
  --dry-run-images       Image generation will be mocked
  --channel CHANNEL_ID   Channel to use (default: nang_suat_thong_minh)
  --ideas N              Number of ideas to generate (default: 3)
  --produce              Run video production after content cycle
  --upload               Upload to socials after production
  --skip-research        Skip research step (use existing ideas)
"""
import os
import sys
import json
import time
import logging
from pathlib import Path

# Ensure project root in path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.paths import PROJECT_ROOT as _PR
from core.video_utils import log

# Global flags for video pipeline
DRY_RUN = False
DRY_RUN_TTS = False
DRY_RUN_IMAGES = False
UPLOAD_TO_SOCIALS = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_content_config(channel_id: str):
    """Load business config for content pipeline."""
    import yaml
    config_path = _PR / "configs/business/video_scenario.yaml.example"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def run_content_cycle(channel_id: str, num_ideas: int, dry_run: bool, skip_research: bool):
    """Run content generation cycle: research → ideas → scripts → schedule."""
    from modules.content.content_pipeline import ContentPipeline

    config = load_content_config(channel_id)

    pipeline = ContentPipeline(
        project_id=1,
        config=config,
        dry_run=dry_run,
        channel_id=channel_id,
    )

    logger.info("=" * 60)
    logger.info("CONTENT CYCLE — Content Generation")
    logger.info("=" * 60)

    if skip_research:
        logger.info("⏭️  SKIP RESEARCH: Getting existing ideas with scripts...")
        ideas = pipeline.idea_gen.get_ideas_by_status(status="script_ready", limit=num_ideas)
        logger.info(f"  Found {len(ideas)} script-ready ideas")
    else:
        results = pipeline.run_full_cycle(num_ideas=num_ideas)
        logger.info(f"Content cycle results: {json.dumps(results, indent=2)}")
        # After run_full_cycle, ideas are saved as "script_ready"
        ideas = pipeline.idea_gen.get_ideas_by_status(status="script_ready", limit=num_ideas)
    logger.info(f"📋 Ideas ready for production: {len(ideas)}")

    return pipeline, ideas


def run_video_production(pipeline, ideas, channel_id: str,
                         dry_run: bool, dry_run_tts: bool, dry_run_images: bool,
                         upload_to_socials: bool):
    """Run video production for ideas that have scripts."""
    import scripts.video_pipeline_v3 as vp_module

    # Set global flags before importing pipeline_runner
    vp_module.DRY_RUN = dry_run
    vp_module.DRY_RUN_TTS = dry_run_tts
    vp_module.DRY_RUN_IMAGES = dry_run_images
    vp_module.UPLOAD_TO_SOCIALS = upload_to_socials

    results = []

    for idea in ideas:
        idea_id = idea.get("id")
        script_json = idea.get("script_json")

        if not script_json:
            logger.warning(f"  ⏭️  Idea {idea_id} has no script, skipping production")
            continue

        title = idea.get("title", f"idea_{idea_id}")
        logger.info(f"\n🎬 Producing video for idea {idea_id}: {title[:50]}")

        # produce_video saves the YAML and runs VideoPipelineV3
        prod_result = pipeline.produce_video(idea_id)

        if prod_result.get("success"):
            video_path = prod_result.get("output_video")
            logger.info(f"  ✅ Video produced: {video_path}")
            results.append({
                "idea_id": idea_id,
                "title": title,
                "video_path": video_path,
                "dry_run": prod_result.get("dry_run", False),
            })

            if upload_to_socials and video_path and not dry_run:
                upload_results = pipeline.upload_to_socials(video_path, idea_id)
                logger.info(f"  📤 Upload results: {json.dumps(upload_results, indent=2)}")
        else:
            logger.error(f"  ❌ Production failed: {prod_result.get('error')}")
            results.append({
                "idea_id": idea_id,
                "title": title,
                "failed": True,
                "error": prod_result.get("error"),
            })

    return results


def main():
    global DRY_RUN, DRY_RUN_TTS, DRY_RUN_IMAGES, UPLOAD_TO_SOCIALS

    channel_id = "nang_suat_thong_minh"
    num_ideas = 3
    run_production = False
    skip_research = False

    # Parse CLI args
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--dry-run":
            DRY_RUN = True
            logger.info("🔴 DRY RUN MODE")
        elif arg == "--dry-run-tts":
            DRY_RUN_TTS = True
            logger.info("🔴 DRY RUN TTS MODE")
        elif arg == "--dry-run-images":
            DRY_RUN_IMAGES = True
            logger.info("🔴 DRY RUN IMAGES MODE")
        elif arg == "--upload":
            UPLOAD_TO_SOCIALS = True
            logger.info("📤 SOCIAL UPLOAD MODE ENABLED")
        elif arg == "--channel" and i + 1 < len(args):
            channel_id = args[i + 1]
            i += 1
        elif arg == "--ideas" and i + 1 < len(args):
            num_ideas = int(args[i + 1])
            i += 1
        elif arg == "--produce":
            run_production = True
        elif arg == "--skip-research":
            skip_research = True
        i += 1

    if not run_production:
        logger.info("💡 Tip: use --produce to run video production after content cycle")

    # ── Step 1: Content Cycle ──────────────────────────────────────
    pipeline, ideas = run_content_cycle(
        channel_id=channel_id,
        num_ideas=num_ideas,
        dry_run=DRY_RUN,
        skip_research=skip_research,
    )

    if not ideas:
        logger.warning("No ideas found for production. Run without --skip-research first.")
        return

    # ── Step 2: Video Production ───────────────────────────────────
    if run_production:
        logger.info("\n" + "=" * 60)
        logger.info("VIDEO PRODUCTION — Scene Processing → Final Video")
        logger.info("=" * 60)

        video_results = run_video_production(
            pipeline=pipeline,
            ideas=ideas,
            channel_id=channel_id,
            dry_run=DRY_RUN,
            dry_run_tts=DRY_RUN_TTS,
            dry_run_images=DRY_RUN_IMAGES,
            upload_to_socials=UPLOAD_TO_SOCIALS,
        )

        logger.info("\n" + "=" * 60)
        logger.info("UNIFIED PIPELINE COMPLETE")
        logger.info("=" * 60)
        logger.info(f"📊 Total ideas processed: {len(ideas)}")
        successful = [r for r in video_results if not r.get("failed")]
        failed = [r for r in video_results if r.get("failed")]
        logger.info(f"  ✅ Successful: {len(successful)}")
        if failed:
            logger.info(f"  ❌ Failed: {len(failed)}")
            for f in failed:
                logger.info(f"      - {f.get('title')}: {f.get('error')}")
    else:
        logger.info("\n✅ Content cycle complete. Use --produce to generate videos.")


if __name__ == "__main__":
    main()