#!/usr/bin/python3
"""
run_scheduler.py — Cron-triggered research job.

Usage:
    python scripts/run_scheduler.py --channel nang_suat_thong_minh

Runs twice daily via cron:
    0 8,20 * * * python /path/to/scripts/run_scheduler.py --channel nang_suat_thong_minh
"""
import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.content.content_pipeline import ContentPipeline
from modules.pipeline.models import ChannelConfig, ContentPipelineConfig, PageConfig, PagePlatformConfig, ContentSettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def main(channel_id: str):
    from db import init_db_full
    try:
        init_db_full()
    except Exception as e:
        logger.warning(f"DB init skipped: {e}")

    try:
        channel_cfg = ChannelConfig.load(channel_id)
    except FileNotFoundError as e:
        logger.error(f"Channel config not found: {e}")
        sys.exit(1)

    # Build ContentPipelineConfig from channel config
    cfg = ContentPipelineConfig(
        page=PageConfig(
            facebook=PagePlatformConfig(
                page_name=channel_cfg.social.facebook.page_name if channel_cfg.social else None,
                page_id=channel_cfg.social.facebook.page_id if channel_cfg.social else None,
                auto_publish=channel_cfg.social.facebook.auto_publish if channel_cfg.social else False,
            ),
            tiktok=PagePlatformConfig(
                account_name=channel_cfg.social.tiktok.account_name if channel_cfg.social else None,
                account_id=channel_cfg.social.tiktok.account_id if channel_cfg.social else None,
                auto_publish=channel_cfg.social.tiktok.auto_publish if channel_cfg.social else False,
            ),
        ),
        content=ContentSettings(
            auto_schedule=True,
            niche_keywords=channel_cfg.research.niche_keywords if channel_cfg.research else [],
            content_angle=channel_cfg.research.content_angle if channel_cfg.research else "tips",
            target_platform=channel_cfg.research.target_platform if channel_cfg.research else "both",
        ),
    )

    pipeline = ContentPipeline(
        project_id=1,
        config=cfg,
        channel_id=channel_id,
        dry_run=False,
        skip_content=False,
    )

    logger.info(f"Scheduler: running research phase for channel={channel_id}")
    results = pipeline.run_research_phase()
    logger.info(f"Scheduler result: {results.get('status')}")

    if results.get("status") in ("research_failed", "idea_generation_failed"):
        logger.error(f"Research failed: {results.get('failure_reason', 'unknown')}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="nang_suat_thong_minh")
    args = parser.parse_args()
    main(args.channel)