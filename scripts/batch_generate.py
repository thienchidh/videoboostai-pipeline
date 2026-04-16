#!/usr/bin/python3
"""
batch_generate.py — Cron-friendly batch video generation from content calendar.

Usage:
    # Process today's scheduled content (all platforms)
    python scripts/batch_generate.py

    # Process a specific calendar item only
    python scripts/batch_generate.py --content-calendar-id 42

    # Dry-run mode (no real API calls, no Telegram messages)
    python scripts/batch_generate.py --dry-run

    # Process only Facebook or TikTok
    python scripts/batch_generate.py --platform facebook

    # Max 5 videos per run (safety cap for budget control)
    python scripts/batch_generate.py --max-items 5

Python API:
    from scripts.batch_generate import BatchGenerator
    gen = BatchGenerator()
    results = gen.run()          # returns list of result dicts
    gen.report_to_telegram()     # sends summary to Telegram
"""

import sys
import time
import logging
import argparse
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.video_utils import log

# ── A/B caption generator (lazy import to avoid hard LLM dependency) ───────────
_ab_gen = None

def _get_ab_generator():
    global _ab_gen
    if _ab_gen is None:
        from modules.content.ab_caption_generator import ABCaptionGenerator
        _ab_gen = ABCaptionGenerator()
    return _ab_gen

# ── Logging ───────────────────────────────────────────────────────────────────
_log_cfg = None
try:
    from modules.pipeline.models import TechnicalConfig
    _tech = TechnicalConfig.load()
    _log_level = getattr(logging, _tech.logging.level.upper(), logging.INFO)
except Exception:
    _log_level = logging.INFO

logging.basicConfig(level=_log_level, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ── Default config ─────────────────────────────────────────────────────────────
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "business" / "video_config_productivity.json"
MAX_RETRIES = 3


class BatchGenerator:
    """
    Batch video generator from content calendar.

    Flow per calendar item:
        1. Mark calendar item as 'in_production'
        2. Load content idea's script_json
        3. Generate A/B caption variants (VP-030)
        4. Save as scenario YAML
        5. Run VideoPipelineV3 (with retry on failure)
        6. Post to social platforms with Variant-A caption
        7. Create ab_caption_tests + social_posts DB records
        8. Mark calendar item as 'produced' or 'failed'
    """

    def __init__(self, platform: str = None, max_items: int = 20,
                 dry_run: bool = False, content_calenar_id: int = None,
                 config_path: str = None, upload_to_socials: bool = False,
                 max_retries: int = None, backoff_base_seconds: int = None,
                 backoff_cap_seconds: int = None):
        """
        Args:
            platform: 'facebook', 'tiktok', or None (all)
            max_items: safety cap on number of videos to process per run
            dry_run: if True, mock all API calls
            content_calenar_id: if set, process only this calendar item
            config_path: path to video config JSON (default: configs/business/video_config_productivity.json)
            upload_to_socials: if True, post to FB/TT with Variant-A after video gen
            max_retries: max retry attempts per item (default: BATCH_MAX_RETRIES)
            backoff_base_seconds: initial backoff delay in seconds (default: BATCH_BACKOFF_BASE_SECONDS)
            backoff_cap_seconds: max backoff delay cap in seconds (default: BATCH_BACKOFF_CAP_SECONDS)
        """
        from modules.pipeline.backoff import (
            BATCH_MAX_RETRIES, BATCH_BACKOFF_BASE_SECONDS, BATCH_BACKOFF_CAP_SECONDS,
            BackoffCalculator,
        )
        self.platform = platform
        self.max_items = max_items
        self.dry_run = dry_run
        self.specific_calendar_id = content_calenar_id
        self.config_path = config_path or str(DEFAULT_CONFIG)
        self.upload_to_socials = upload_to_socials
        self.max_retries = max_retries if max_retries is not None else BATCH_MAX_RETRIES
        self.backoff_base_seconds = backoff_base_seconds if backoff_base_seconds is not None else BATCH_BACKOFF_BASE_SECONDS
        self.backoff_cap_seconds = backoff_cap_seconds if backoff_cap_seconds is not None else BATCH_BACKOFF_CAP_SECONDS
        self.backoff = BackoffCalculator(
            base_seconds=self.backoff_base_seconds,
            cap_seconds=self.backoff_cap_seconds,
            factor=10,
        )
        self.results: List[Dict] = []
        self._publisher = None

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> List[Dict]:
        """
        Main entry point. Queries DB, processes each calendar item, returns results.
        """
        self._init_db()
        today = date.today()

        if self.specific_calendar_id:
            items = self._get_specific_calendar_item(self.specific_calendar_id)
            if not items:
                logger.warning(f"Calendar item {self.specific_calendar_id} not found")
                return []
        else:
            items = self._get_due_items(today)
            if not items:
                logger.info(f"No due calendar items for today ({today})")
                return []

        items = items[:self.max_items]
        logger.info(f"BatchGenerate: {len(items)} items to process (platform={self.platform or 'all'})")

        for item in items:
            result = self._process_item(item)
            self.results.append(result)

        return self.results

    def report_to_telegram(self, silent: bool = None) -> None:
        """
        Send summary report to Telegram.
        Does nothing in --dry-run mode.
        """
        if self.dry_run:
            logger.info("[DRY-RUN] Telegram report skipped")
            return

        ok = [r for r in self.results if r.get("success")]
        failed = [r for r in self.results if not r.get("success")]

        today_str = date.today().strftime("%Y-%m-%d")
        total = len(self.results)

        if total == 0:
            msg = f"📅 *Batch Generate* — {today_str}\n\nNo items scheduled for today."
        else:
            lines = [f"📅 *Batch Generate* — {today_str}\n"]
            lines.append(f"✅ OK: {len(ok)}/{total}")
            if failed:
                lines.append(f"❌ Failed: {len(failed)}")
            lines.append("")
            for r in self.results:
                status = "✅" if r.get("success") else "❌"
                title = r.get("title", "Unknown")[:40]
                platform = r.get("platform", "?")
                if r.get("success"):
                    video = r.get("video_path", "N/A")
                    video_short = Path(video).name if video else "N/A"
                    lines.append(f"{status} [{platform}] {title}")
                    lines.append(f"   → {video_short}")
                else:
                    error = str(r.get("error", ""))[:60]
                    lines.append(f"{status} [{platform}] {title}")
                    lines.append(f"   → {error}")

            msg = "\n".join(lines)

        self._send_telegram(msg)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _init_db(self):
        try:
            from db import init_db_full
            init_db_full()
        except Exception as e:
            logger.warning(f"DB init skipped: {e}")

    def _get_due_items(self, as_of_date) -> List[Dict]:
        """Fetch due calendar items from DB."""
        from db import get_due_calendar_items
        items = get_due_calendar_items(as_of_date, platform=self.platform)
        return items

    def _get_specific_calendar_item(self, calendar_id: int) -> List[Dict]:
        """Fetch a single calendar item by ID."""
        from db import get_session
        import db_models as models

        with get_session() as session:
            row = session.query(
                models.ContentCalendar,
                models.ContentIdea.title,
                models.ContentIdea.topic_keywords
            ).join(
                models.ContentIdea,
                models.ContentCalendar.idea_id == models.ContentIdea.id
            ).filter(models.ContentCalendar.id == calendar_id).first()

        if not row:
            return []
        cal, title, topic_keywords = row
        return [{
            "id": cal.id,
            "idea_id": cal.idea_id,
            "platform": cal.platform,
            "scheduled_date": cal.scheduled_date,
            "scheduled_time": cal.scheduled_time,
            "status": cal.status,
            "priority": cal.priority,
            "notes": cal.notes,
            "video_run_id": cal.video_run_id,
            "title": title,
            "topic_keywords": topic_keywords,
        }]

    def _process_item(self, item: Dict) -> Dict:
        """Process a single calendar item: produce video + log to DB."""
        calendar_id = item["id"]
        idea_id = item["idea_id"]
        platform = item.get("platform", "both")
        title = item.get("title", f"idea_{idea_id}")
        scheduled_date = item.get("scheduled_date", "?")

        logger.info(f"─── Processing calendar_id={calendar_id}, idea_id={idea_id}, "
                    f"platform={platform}, title={title[:40]} ───")

        # ── Step 1: Mark in production ───────────────────────────────────────
        self._update_calendar_status(calendar_id, "in_production")

        # ── Step 2: Load idea's script_json ───────────────────────────────────
        from db import get_content_idea
        idea = get_content_idea(idea_id)
        if not idea:
            return self._fail_item(item, f"Content idea {idea_id} not found in DB")

        script_json = idea.get("script_json")
        if not script_json:
            return self._fail_item(item, f"Content idea {idea_id} has no script_json")

        # ── Step 3: Save scenario YAML ─────────────────────────────────────────
        scenario_path = self._save_scenario_yaml(idea_id, script_json, item)

        # ── Step 4: Run video pipeline with retry ──────────────────────────────
        video_path, run_id, error = self._run_pipeline_with_retry(
            scenario_path, item, max_retries=MAX_RETRIES
        )

        if not video_path:
            self._update_calendar_status(calendar_id, "failed", notes=error)
            return {
                **item,
                "success": False,
                "error": error,
                "calendar_id": calendar_id,
                "idea_id": idea_id,
                "run_id": run_id,
            }

        # ── Step 5: Generate A/B caption variants ────────────────────────────
        ab_result = self._generate_ab_captions(script_json, platform)

        # ── Step 6: Post to social platforms with Variant-A ──────────────────
        post_results = self._post_to_socials(run_id, video_path, ab_result, platform)

        # ── Step 7: Log to social_posts + ab_caption_tests ────────────────────
        self._log_social_post_and_ab_test(
            run_id=run_id,
            platform=platform,
            video_path=video_path,
            ab_result=ab_result,
            post_results=post_results,
            calendar_id=calendar_id,
        )

        # ── Step 8: Mark calendar item as produced ─────────────────────────────
        self._update_calendar_status(
            calendar_id, "produced",
            video_run_id=run_id,
            notes=f"Output: {Path(video_path).name}"
        )

        logger.info(f"✅ Calendar {calendar_id} produced: {video_path}")
        return {
            **item,
            "success": True,
            "video_path": video_path,
            "run_id": run_id,
            "calendar_id": calendar_id,
            "idea_id": idea_id,
        }

    def _run_pipeline_with_retry(self, scenario_path: str, item: Dict,
                                  max_retries: int = 3) -> tuple:
        """
        Run VideoPipelineV3 with retry on failure.
        Returns (video_path, run_id, error_msg).
        """
        from scripts.video_pipeline_v3 import VideoPipelineV3
        import scripts.video_pipeline_v3 as vp_module

        # Extract channel_id from scenario path: configs/channels/{channel_id}/scenarios/...
        scenario_path_obj = Path(scenario_path)
        try:
            rel_parts = scenario_path_obj.relative_to(PROJECT_ROOT / "configs" / "channels").parts
            channel_id = rel_parts[0]
        except Exception:
            channel_id = "nang_suat_thong_minh"

        for attempt in range(1, max_retries + 1):
            try:
                # Reset global flags per attempt
                vp_module.DRY_RUN = self.dry_run
                vp_module.DRY_RUN_TTS = self.dry_run
                vp_module.DRY_RUN_IMAGES = self.dry_run
                vp_module.UPLOAD_TO_SOCIALS = False

                pipeline = VideoPipelineV3(channel_id, str(scenario_path))
                video_path = pipeline.run()
                run_id = pipeline.run_id

                if video_path:
                    return video_path, run_id, None

                error = f"Attempt {attempt}: pipeline returned None"
                logger.warning(f"Attempt {attempt}/{max_retries} failed: {error}")

            except Exception as e:
                error = f"Attempt {attempt}: {e}"
                logger.warning(f"Attempt {attempt}/{max_retries} error: {e}")
                if attempt == max_retries:
                    return None, None, error

        return None, None, f"All {max_retries} attempts failed"

    def _save_scenario_yaml(self, idea_id: int, script_json: Dict, item: Dict) -> str:
        """Save script_json as a YAML scenario file. Returns path to saved file."""
        import yaml
        import re
        from unidecode import unidecode

        title = script_json.get("title") or item.get("title", f"idea_{idea_id}")
        scenes = script_json.get("scenes", [])

        # Slugify title
        slug = unidecode(title)
        slug = re.sub(r'[^a-zA-Z0-9\s]', ' ', slug)
        slug = re.sub(r'\s+', '-', slug.strip().lower())
        slug = slug[:50].strip('-')

        scheduled_date = item.get("scheduled_date", date.today())
        if isinstance(scheduled_date, (date, datetime)):
            date_str = scheduled_date.strftime("%Y-%m-%d")
        else:
            date_str = str(scheduled_date)

        scenario_dir = PROJECT_ROOT / "configs" / "channels" / "batch" / "scenarios" / date_str
        scenario_dir.mkdir(parents=True, exist_ok=True)

        config_path = scenario_dir / f"{slug}.yaml"
        scenario_data = {
            "title": title,
            "scenes": scenes,
        }

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(scenario_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        logger.info(f"  Scenario saved: {config_path}")
        return str(config_path)

    def _generate_ab_captions(self, script_json: Dict, platform: str):
        """Generate A/B caption variants from script_json. Returns ABCaptionResult."""
        try:
            from modules.content.ab_caption_generator import ABCaptionGenerator

            # Combine title + scene scripts for richer caption context
            title = script_json.get("title", "")
            scenes = script_json.get("scenes", [])
            scene_scripts = [s.get("script", "") for s in scenes if s.get("script")]
            combined_script = f"{title}. " + " ".join(scene_scripts)

            # Normalise platform for caption generator
            cap_platform = "tiktok" if platform == "tiktok" else "facebook"
            gen = ABCaptionGenerator()
            result = gen.generate_ab_captions(combined_script, platform=cap_platform)

            logger.info(f"  [AB] Variant-A: {result.variant_a.headline[:50]}")
            logger.info(f"  [AB] Variant-B: {result.variant_b.headline[:50]}")
            return result
        except Exception as e:
            logger.warning(f"  [AB] Caption generation failed: {e} — using empty fallback")
            from modules.content.caption_generator import GeneratedCaption
            from modules.content.ab_caption_generator import ABCaptionResult
            dummy = GeneratedCaption(
                headline="Video thu vi",
                body="Xem ngay!",
                hashtags=["#vietnam", "#fyp"],
                cta="Like va follow nhe!",
                full_caption="Video thu vi. Xem ngay! #vietnam #fyp",
            )
            return ABCaptionResult(variant_a=dummy, variant_b=dummy)

    def _get_publisher(self):
        """Lazily build SocialPublisher from channel config."""
        if self._publisher is not None:
            return self._publisher
        try:
            from modules.pipeline.models import ChannelConfig
            from modules.pipeline.publisher import get_publisher
            channel_id = "nang_suat_thong_minh"
            try:
                channel_cfg = ChannelConfig.load(channel_id)
            except Exception:
                logger.warning(f"  Channel config '{channel_id}' not found - social posting disabled")
                self._publisher = None
                return None
            if channel_cfg.social is None:
                logger.warning("  No social config in channel - social posting disabled")
                self._publisher = None
                return None
            self._publisher = get_publisher(social=channel_cfg.social, dry_run=self.dry_run)
            return self._publisher
        except Exception as e:
            logger.warning(f"  Failed to initialise SocialPublisher: {e}")
            self._publisher = None
            return None

    def _post_to_socials(self, run_id: int, video_path: str,
                         ab_result, platform: str) -> Dict:
        """
        Post video to social platforms with Variant-A caption.
        Returns dict of {platform: {success, post_id, post_url}}.
        """
        results: Dict = {}

        if not self.upload_to_socials:
            logger.info("  [SOCIAL] upload_to_socials=False - skipping post")
            platforms = ["facebook", "tiktok"] if platform == "both" else [platform]
            for p in platforms:
                results[p] = {"success": True, "dry_run": True, "post_id": None, "post_url": None}
            return results

        publisher = self._get_publisher()
        if publisher is None:
            logger.warning("  [SOCIAL] Publisher not configured - skipping post")
            return results

        variant_a_caption = ab_result.variant_a.full_caption

        try:
            pr = publisher.upload_to_socials(video_path=video_path, script=variant_a_caption)
            for r in pr.results:
                p = r.get("platform", "unknown")
                success = r.get("success", False)
                post_url = r.get("post_url", "")
                # Extract numeric post_id from URL if not separately returned
                post_id_val = r.get("post_id") or (post_url.split("/")[-1] if post_url else None)
                results[p] = {"success": success, "post_id": post_id_val, "post_url": post_url}
                if success:
                    logger.info(f"  [SOCIAL] {p} posted: {post_url}")
                else:
                    logger.warning(f"  [SOCIAL] {p} failed: {r.get('error', 'unknown')}")
        except Exception as e:
            logger.error(f"  [SOCIAL] Posting error: {e}")
            for p in (["facebook", "tiktok"] if platform == "both" else [platform]):
                results[p] = {"success": False, "post_id": None, "post_url": None, "error": str(e)}

        return results

    def _log_social_post_and_ab_test(self, run_id: int, platform: str,
                                       video_path: str, ab_result,
                                       post_results: Dict,
                                       calendar_id: int):
        """
        Create social_post entries with Variant-A caption + ab_caption_tests record.
        """
        if self.dry_run or not run_id:
            return
        try:
            from db import (
                create_social_post, update_social_post,
                create_ab_caption_test, update_ab_caption_test,
            )
            from datetime import datetime

            platforms = ["facebook", "tiktok"] if platform == "both" else [platform]
            for p in platforms:
                post_result = post_results.get(p, {})
                is_dry = post_result.get("dry_run", False)
                post_id_val = post_result.get("post_id")
                post_url = post_result.get("post_url")

                # Create social_post with Variant-A caption
                sp_id = create_social_post(
                    run_id=run_id,
                    platform=p,
                    video_path=video_path,
                    caption=ab_result.variant_a.full_caption,
                    srt_path=None,
                )

                if is_dry:
                    update_social_post(sp_id, status="dry_run")
                    logger.info(f"  [AB] social_post (dry-run) id={sp_id}, platform={p}")
                elif post_result.get("success"):
                    update_social_post(
                        sp_id,
                        status="posted",
                        post_id=post_id_val,
                        post_url=post_url,
                        posted_at=datetime.now(timezone.utc),
                    )
                    logger.info(f"  [AB] social_post id={sp_id}, platform={p}, post_id={post_id_val}")
                else:
                    update_social_post(sp_id, status="failed", error=post_result.get("error"))
                    logger.warning(f"  [AB] social_post id={sp_id}, platform={p} - posting failed")

                # Create ab_caption_tests record (one per platform)
                test_id = create_ab_caption_test(
                    calendar_item_id=calendar_id,
                    platform=p,
                    variant_a=ab_result.variant_a.full_caption,
                    variant_b=ab_result.variant_b.full_caption,
                    post_id=post_id_val if not is_dry else None,
                )

                if not is_dry and post_result.get("success"):
                    update_ab_caption_test(
                        test_id,
                        status="pending",
                        posted_at=datetime.now(timezone.utc),
                    )
                    logger.info(f"  [AB] ab_caption_tests created: id={test_id}, platform={p}")
                else:
                    logger.info(f"  [AB] ab_caption_tests (dry/fail) id={test_id}, platform={p}")

        except Exception as e:
            logger.error(f"  [AB] Failed to log social_post/ab_caption_tests: {e}")

    def _update_calendar_status(self, calendar_id: int, status: str,
                                 video_run_id: int = None, notes: str = None):
        """Update calendar item status in DB."""
        try:
            from db import update_calendar_status
            update_calendar_status(calendar_id, status,
                                   video_run_id=video_run_id, notes=notes)
            logger.info(f"  Calendar {calendar_id} → {status}")
        except Exception as e:
            logger.error(f"  Failed to update calendar status: {e}")

    def _create_or_update_failure_queue(self, run_id: int, step_name: str,
                                         scene_index: int = None, attempt: int = 1,
                                         last_error: str = None, next_retry_at=None,
                                         status: str = "pending",
                                         existing_id: int = None) -> int:
        """Create or update a FailedStep DB entry. Returns failed_step id."""
        from db import create_failed_step, update_failed_step
        if existing_id is not None:
            update_failed_step(
                failed_step_id=existing_id,
                attempts=attempt,
                last_error=last_error,
                next_retry_at=next_retry_at,
                status=status,
            )
            return existing_id
        else:
            fid = create_failed_step(
                run_id=run_id,
                step_name=step_name,
                scene_index=scene_index,
                last_error=last_error,
                next_retry_at=next_retry_at,
            )
            return fid

    def _resolve_failure_queue_entry(self, failed_step_id: int) -> None:
        """Mark a FailedStep entry as resolved."""
        from db import resolve_failed_step
        resolve_failed_step(failed_step_id)

    def _fail_item(self, item: Dict, error: str) -> Dict:
        """Mark item as failed and return error result dict."""
        calendar_id = item["id"]
        self._update_calendar_status(calendar_id, "failed", notes=error)
        return {
            **item,
            "success": False,
            "error": error,
            "calendar_id": calendar_id,
            "idea_id": item.get("idea_id"),
        }

    def _send_telegram(self, message: str):
        """Send message to Telegram via the configured channel."""
        try:
            # Get Telegram config from TechnicalConfig
            from modules.pipeline.models import TechnicalConfig
            tech = TechnicalConfig.load()
            bot_token = tech.telegram.get("bot_token")
            chat_id = tech.telegram.get("chat_id")

            if not bot_token or not chat_id:
                logger.warning("Telegram bot_token or chat_id not configured; skipping notification")
                print(message)
                return

            import urllib.request
            import urllib.parse

            encoded_msg = urllib.parse.quote_plus(message)
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={chat_id}&text={encoded_msg}&parse_mode=Markdown"

            with urllib.request.urlopen(url, timeout=10) as resp:
                if resp.status == 200:
                    logger.info("Telegram notification sent")
                else:
                    logger.warning(f"Telegram returned status {resp.status}")

        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")
            print(message)  # Fallback: print to stdout


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Batch video generation from content calendar"
    )
    parser.add_argument(
        "--content-calendar-id", type=int, default=None,
        help="Process only this specific calendar item ID"
    )
    parser.add_argument(
        "--platform", choices=["facebook", "tiktok", "both"], default=None,
        help="Filter by platform (default: all)"
    )
    parser.add_argument(
        "--max-items", type=int, default=20,
        help="Maximum number of videos to process per run (default: 20)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Mock all API calls; do not send Telegram messages"
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to video config JSON (default: configs/business/video_config_productivity.json)"
    )
    parser.add_argument(
        "--telegram-only", action="store_true",
        help="Skip processing; only send Telegram report for last results"
    )
    parser.add_argument(
        "--upload-to-socials", action="store_true",
        help="Post to Facebook/TikTok with Variant-A caption after video generation (VP-030 A/B testing)"
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("BATCH GENERATE — Content Calendar → Video Pipeline")
    logger.info("=" * 60)
    logger.info(f"  Calendar ID : {args.content_calendar_id or 'all due today'}")
    logger.info(f"  Platform    : {args.platform or 'all'}")
    logger.info(f"  Max items   : {args.max_items}")
    logger.info(f"  Dry run     : {args.dry_run}")
    logger.info(f"  Upload     : {args.upload_to_socials}")
    logger.info(f"  Config      : {args.config or 'configs/business/video_config_productivity.json'}")

    if args.telegram_only:
        logger.info("--telegram-only: skipping processing")
        gen = BatchGenerator()
        gen.report_to_telegram()
        sys.exit(0)

    gen = BatchGenerator(
        platform=args.platform,
        max_items=args.max_items,
        dry_run=args.dry_run,
        content_calenar_id=args.content_calendar_id,
        config_path=args.config,
        upload_to_socials=args.upload_to_socials,
    )

    results = gen.run()

    # Summary
    ok = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    logger.info("")
    logger.info("=" * 60)
    logger.info("BATCH SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total : {len(results)}")
    logger.info(f"  OK     : {len(ok)}")
    logger.info(f"  Failed : {len(failed)}")
    for r in results:
        status = "✅" if r.get("success") else "❌"
        title = r.get("title", "?")[:40]
        platform = r.get("platform", "?")
        if r.get("success"):
            vp = Path(r.get("video_path", "")).name
            logger.info(f"  {status} [{platform}] {title} → {vp}")
        else:
            err = str(r.get("error", ""))[:50]
            logger.info(f"  {status} [{platform}] {title} → {err}")

    # Send Telegram report
    gen.report_to_telegram()
