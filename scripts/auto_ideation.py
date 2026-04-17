#!/usr/bin/env python3
"""
auto_ideation.py — Automated content ideation pipeline.

Scheduled by cron to:
  1. Research trending topics from configured keywords
  2. Generate 3-5 content ideas
  3. Generate scene scripts for new ideas
  4. Auto-schedule ideas to content calendar (ready for batch_generate.py)

Usage:
    # Dry-run (no real API calls, no DB writes)
    python scripts/auto_ideation.py --dry-run

    # Production run
    python scripts/auto_ideation.py

    # Custom idea count
    python scripts/auto_ideation.py --ideas-per-run 5

    # Cron: run every 6 hours (as part of run_batch_if_healthy.sh)
    #   0 */6 * * * cd ... && python scripts/auto_ideation.py >> logs/auto_ideation.log 2>&1

Python API:
    from scripts.auto_ideation import AutoIdeation
    ai = AutoIdeation(channel_id="nang_suat_thong_minh", dry_run=True)
    results = ai.run()
"""

import sys
import logging
import argparse
from datetime import date, datetime, time
from pathlib import Path
from typing import List, Dict, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.content.topic_researcher import TopicResearcher
from modules.content.content_idea_generator import ContentIdeaGenerator
from modules.content.content_calendar import ContentCalendar
from modules.pipeline.models import ChannelConfig, TechnicalConfig, ContentPipelineConfig


# ── Logging ───────────────────────────────────────────────────────────────────────

_log_level = logging.INFO
try:
    from modules.pipeline.models import TechnicalConfig
    _tech = TechnicalConfig.load()
    _log_level = getattr(logging, _tech.logging.level.upper(), logging.INFO)
except Exception:
    pass

logging.basicConfig(level=_log_level, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ── Default config ────────────────────────────────────────────────────────────

DEFAULT_CHANNEL = "nang_suat_thong_minh"
DEFAULT_IDEAS_PER_RUN = 4
MIN_IDEAS = 3
MAX_IDEAS = 5
DEFAULT_SCENE_COUNT = 3


class AutoIdeation:
    """
    Automated content ideation: research → ideas → scripts → schedule.

    Does NOT produce videos — that step is handled by batch_generate.py
    once ideas are script_ready in the calendar.
    """

    def __init__(self, channel_id: str = DEFAULT_CHANNEL,
                 ideas_per_run: int = DEFAULT_IDEAS_PER_RUN,
                 dry_run: bool = False,
                 skip_credit_check: bool = False):
        """
        Args:
            channel_id: channel ID for config loading
            ideas_per_run: number of ideas to generate per run (3-5)
            dry_run: if True, mock all API calls and skip DB writes
            skip_credit_check: if True, skip credit balance check
        """
        if ideas_per_run < MIN_IDEAS:
            ideas_per_run = MIN_IDEAS
        elif ideas_per_run > MAX_IDEAS:
            ideas_per_run = MAX_IDEAS

        self.channel_id = channel_id
        self.ideas_per_run = ideas_per_run
        self.dry_run = dry_run
        self.skip_credit_check = skip_credit_check
        self.results: Dict = {}

        # Load technical config first (needed for schedule_hour/minute + scene_count)
        try:
            self.technical_config = TechnicalConfig.load()
        except Exception as e:
            logger.warning(f"Could not load TechnicalConfig: {e}")
            self.technical_config = None

        # Load channel config
        try:
            self.channel_cfg = ChannelConfig.load(channel_id)
        except FileNotFoundError:
            logger.error(f"Channel config not found: {channel_id}")
            raise ValueError(f"Channel config not found: {channel_id}")

        research_cfg = self.channel_cfg.research
        self.niche_keywords = research_cfg.niche_keywords if research_cfg else []
        self.content_angle = research_cfg.content_angle if research_cfg else "tips"
        self.target_platform = research_cfg.target_platform if research_cfg else "both"

        # Scheduling: schedule_hour/minute lives in TechnicalConfig.generation.research
        if self.technical_config and self.technical_config.generation and \
           self.technical_config.generation.research:
            gen_research = self.technical_config.generation.research
            self.schedule_time = time(
                gen_research.schedule_hour,
                gen_research.schedule_minute,
            )
        else:
            self.schedule_time = time(9, 0)

        self.scene_count = (
            self.technical_config.generation.content.scene_count
            if self.technical_config and self.technical_config.generation and
               self.technical_config.generation.content
            else DEFAULT_SCENE_COUNT
        )

        # Init components
        self.researcher = TopicResearcher(
            niche_keywords=self.niche_keywords,
            project_id=1,
        )
        self.idea_gen = ContentIdeaGenerator(
            project_id=1,
            content_angle=self.content_angle,
            target_platform=self.target_platform,
            niche_keywords=self.niche_keywords,
            channel_config=self.channel_cfg,
            technical_config=self.technical_config,
        )
        self.calendar = ContentCalendar(project_id=1)

    def _parse_schedule(self, research_cfg) -> tuple:
        """Parse schedule_hour/minute from research config."""
        schedule_hour = getattr(research_cfg, 'schedule_hour', 9)
        schedule_minute = getattr(research_cfg, 'schedule_minute', 0)
        return schedule_hour, schedule_minute

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self) -> Dict:
        """
        Run full auto-ideation cycle:
          1. Credit check
          2. Research topics (TopicResearcher)
          3. Generate ideas (ContentIdeaGenerator)
          4. Generate scripts (ContentIdeaGenerator.generate_script_from_idea)
          5. Auto-schedule to calendar

        Returns dict with results summary.
        """
        self._init_db()

        # Step 0: Credit check
        if not self.skip_credit_check:
            exhausted, balances = self._check_credits()
            if exhausted:
                logger.error("[CREDIT] Budget exhausted — aborting ideation")
                return {"status": "aborted_credit_exhausted", "ideas_generated": 0}

        # Step 1: Check if pending pool already has enough ideas
        if not self._should_run_ideation():
            logger.info("Pending pool above threshold — skipping ideation this run")
            return {"status": "skipped_threshold", "ideas_generated": 0}

        # Step 2: Research topics
        logger.info("Step 1: Researching trending topics...")
        topics = self.researcher.research_from_keywords(
            keywords=self.niche_keywords,
            count=self.ideas_per_run * 3,  # fetch more to allow dedup
        )
        if not topics:
            logger.warning("No topics found from research")
            return {"status": "no_topics", "ideas_generated": 0}
        logger.info(f"  Found {len(topics)} topics")

        # Step 3: Save topics to DB
        source_id = self.researcher.save_to_db(topics, source_query=", ".join(self.niche_keywords))

        # Step 4: Generate content ideas
        logger.info("Step 2: Generating content ideas...")
        ideas = self.idea_gen.generate_ideas_from_topics(topics, count=self.ideas_per_run)
        if not ideas:
            return {"status": "no_ideas", "ideas_generated": 0}
        logger.info(f"  Generated {len(ideas)} ideas")

        # Dedup (check against existing ideas in DB)
        ideas = self._deduplicate_ideas(ideas)
        logger.info(f"  After dedup: {len(ideas)} ideas")

        if not ideas:
            return {"status": "all_duplicates", "ideas_generated": 0}

        ideas = ideas[:self.ideas_per_run]

        # Step 5: Save ideas to DB
        idea_ids = self.idea_gen.save_ideas_to_db(ideas, source_id=source_id)
        logger.info(f"  Saved {len(idea_ids)} ideas to DB")

        # Step 6: Generate scripts for each idea
        logger.info("Step 3: Generating scene scripts...")
        script_results = self._generate_scripts_parallel(idea_ids, ideas)

        # Step 7: Auto-schedule script_ready ideas to calendar
        logger.info("Step 4: Auto-scheduling to calendar...")
        scheduled = self._auto_schedule(script_results)

        self.results = {
            "status": "success",
            "topics_found": len(topics),
            "ideas_generated": len(idea_ids),
            "scripts_generated": len(script_results),
            "idea_ids": idea_ids,
            "scheduled": scheduled,
            "channel_id": self.channel_id,
        }
        return self.results

    def report_to_telegram(self) -> None:
        """Send summary report to Telegram."""
        if self.dry_run:
            logger.info("[DRY-RUN] Telegram report skipped")
            return

        r = self.results
        status = r.get("status", "unknown")
        today_str = date.today().strftime("%Y-%m-%d")

        lines = [
            f"🧠 *Auto Ideation* — {today_str}",
            f"Status: `{status}`",
            f"Ideas generated: {r.get('ideas_generated', 0)}",
            f"Scripts created: {r.get('scripts_generated', 0)}",
            f"Scheduled to calendar: {len(r.get('scheduled', []))}",
        ]

        scheduled = r.get("scheduled", [])
        if scheduled:
            lines.append("")
            for s in scheduled[:5]:
                platform = s.get("platform", "?")
                idea_title = s.get("title", "?")[:40]
                cal_id = s.get("calendar_id")
                lines.append(f"  📅 [{platform}] {idea_title} (cal_id={cal_id})")

        msg = "\n".join(lines)
        self._send_telegram(msg)

    # ── Internal ────────────────────────────────────────────────────────────────

    def _init_db(self):
        try:
            from db import init_db_full
            init_db_full()
        except Exception as e:
            logger.warning(f"DB init skipped: {e}")

    def _should_run_ideation(self) -> bool:
        """Return True if pending pool is below threshold."""
        from db import get_session, models
        with get_session() as session:
            count = session.query(models.ContentIdea).filter(
                models.ContentIdea.status == "raw"
            ).count()
        threshold = (
            self.channel_cfg.research.threshold
            if self.channel_cfg and self.channel_cfg.research
            else 3
        )
        pool_size = (
            self.channel_cfg.research.pending_pool_size
            if self.channel_cfg and self.channel_cfg.research
            else 5
        )
        if count >= pool_size:
            return False
        return count < threshold

    def _check_credits(self) -> tuple:
        """Check credit balances. Returns (exhausted, balances)."""
        from modules.ops.credit_monitor import DEFAULT_THRESHOLDS
        from db import get_credits_balance

        providers = ["kieai", "minimax", "wavespeed"]
        balances: Dict[str, float] = {}
        exhausted_providers: List[str] = []

        for provider in providers:
            balance = get_credits_balance(provider)
            balances[provider] = balance
            if balance <= 0.0:
                exhausted_providers.append(provider)
                logger.warning(f"[CREDIT] {provider}: balance={balance} — EXHAUSTED")

        if exhausted_providers:
            logger.error(f"[CREDIT] Exhausted: {exhausted_providers} — aborting ideation")
            return True, balances
        return False, balances

    def _deduplicate_ideas(self, ideas: List[Dict]) -> List[Dict]:
        """Deduplicate ideas against existing ideas in DB."""
        try:
            from utils.embedding import check_duplicate_ideas
            return check_duplicate_ideas(ideas, project_id=1, config=self.technical_config)
        except (RuntimeError, IOError, ImportError) as e:
            logger.warning(f"Embedding dedup failed: {e} — skipping dedup")
            return ideas

    def _generate_scripts_parallel(self, idea_ids: List[int],
                                   ideas: List[Dict]) -> List[Dict]:
        """
        Generate scene scripts for each idea in parallel.
        Returns list of {idea_id, title, config_path, success}.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = []

        def generate_one(i: int) -> Dict:
            idea_id = idea_ids[i]
            idea = ideas[i]
            try:
                script = self.idea_gen.generate_script_from_idea(
                    idea, num_scenes=self.scene_count
                )
                self.idea_gen.update_idea_script(idea_id, script)
                config_path = self._save_scenario_yaml(idea_id, script, idea)
                return {
                    "idea_id": idea_id,
                    "title": idea.get("title", ""),
                    "config_path": config_path,
                    "success": True,
                }
            except Exception as e:
                logger.warning(f"Script generation failed for idea {idea_id}: {e}")
                return {
                    "idea_id": idea_id,
                    "title": idea.get("title", ""),
                    "success": False,
                    "error": str(e),
                }

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(generate_one, i): i
                for i in range(len(idea_ids))
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                idea_title = result.get("title", "?")[:40]
                status = "✅" if result.get("success") else "❌"
                logger.info(f"  {status} Script for {idea_title}: success={result.get('success')}")

        return results

    def _save_scenario_yaml(self, idea_id: int, script: Dict,
                             idea: Dict) -> str:
        """Save script as YAML scenario file. Returns path."""
        import re
        import yaml
        from unidecode import unidecode

        title = script.get("title", f"idea_{idea_id}")
        scenes = script.get("scenes", [])

        slug = unidecode(title)
        slug = re.sub(r'[^a-zA-Z0-9\s]', ' ', slug)
        slug = re.sub(r'\s+', '-', slug.strip().lower())
        slug = slug[:50].strip('-')

        today_str = date.today().strftime("%Y-%m-%d")
        scenario_dir = (
            PROJECT_ROOT / "configs" / "channels" / self.channel_id /
            "scenarios" / today_str
        )
        scenario_dir.mkdir(parents=True, exist_ok=True)

        config_path = scenario_dir / f"{slug}.yaml"
        scenario_data = {
            "title": title,
            "scenes": scenes,
        }

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(scenario_data, f, allow_unicode=True,
                      default_flow_style=False, sort_keys=False)

        logger.info(f"  Scenario saved: {config_path}")
        return str(config_path)

    def _auto_schedule(self, script_results: List[Dict]) -> List[Dict]:
        """
        Auto-schedule script_ready ideas to content calendar.
        Creates calendar entries for each platform (facebook, tiktok).
        Returns list of {idea_id, platform, calendar_id, title}.
        """
        scheduled = []
        platforms = (
            ["facebook", "tiktok"]
            if self.target_platform == "both"
            else [self.target_platform]
        )

        today = date.today()
        for result in script_results:
            if not result.get("success"):
                continue

            idea_id = result["idea_id"]
            title = result.get("title", "")

            for platform in platforms:
                cal_id = self.calendar.schedule_idea(
                    idea_id=idea_id,
                    platform=platform,
                    scheduled_date=today,
                    scheduled_time=self.schedule_time,
                    priority="medium",
                    notes=f"[auto-ideation] {title[:80]}",
                )
                scheduled.append({
                    "idea_id": idea_id,
                    "platform": platform,
                    "calendar_id": cal_id,
                    "title": title,
                })
                logger.info(f"  📅 Scheduled idea {idea_id} for {platform} "
                           f"on {today} → cal_id={cal_id}")

        return scheduled

    def _send_telegram(self, message: str):
        """Send message to Telegram via configured bot."""
        try:
            from modules.pipeline.models import TechnicalConfig
            tech = TechnicalConfig.load()
            bot_token = tech.telegram.get("bot_token")
            chat_id = tech.telegram.get("chat_id")

            if not bot_token or not chat_id:
                logger.warning("Telegram not configured; skipping notification")
                print(message)
                return

            import urllib.request
            import urllib.parse

            encoded = urllib.parse.quote_plus(message)
            url = (f"https://api.telegram.org/bot{bot_token}/sendMessage"
                   f"?chat_id={chat_id}&text={encoded}&parse_mode=Markdown")
            with urllib.request.urlopen(url, timeout=10) as resp:
                if resp.status == 200:
                    logger.info("Telegram notification sent")
                else:
                    logger.warning(f"Telegram returned {resp.status}")

        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")
            print(message)


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Automated content ideation pipeline"
    )
    parser.add_argument(
        "--channel", default=DEFAULT_CHANNEL,
        help=f"Channel ID (default: {DEFAULT_CHANNEL})"
    )
    parser.add_argument(
        "--ideas-per-run", type=int, default=DEFAULT_IDEAS_PER_RUN,
        help=f"Number of ideas to generate per run, {MIN_IDEAS}-{MAX_IDEAS} "
             f"(default: {DEFAULT_IDEAS_PER_RUN})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Mock all API calls and skip DB writes"
    )
    parser.add_argument(
        "--skip-credit-check", action="store_true",
        help="Skip credit balance check before running"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose (DEBUG) logging"
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("AUTO IDEATION — Content Research → Ideas → Scripts → Schedule")
    logger.info("=" * 60)
    logger.info(f"  Channel    : {args.channel}")
    logger.info(f"  Ideas/run  : {args.ideas_per_run}")
    logger.info(f"  Dry run    : {args.dry_run}")
    logger.info(f"  Skip credit: {args.skip_credit_check}")

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    ai = AutoIdeation(
        channel_id=args.channel,
        ideas_per_run=args.ideas_per_run,
        dry_run=args.dry_run,
        skip_credit_check=args.skip_credit_check,
    )

    results = ai.run()

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("IDEATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Status           : {results.get('status')}")
    logger.info(f"  Topics found     : {results.get('topics_found', 0)}")
    logger.info(f"  Ideas generated : {results.get('ideas_generated', 0)}")
    logger.info(f"  Scripts created : {results.get('scripts_generated', 0)}")
    logger.info(f"  Scheduled        : {len(results.get('scheduled', []))}")

    for s in results.get("scheduled", []):
        cal = s.get("calendar_id")
        platform = s.get("platform", "?")
        title = s.get("title", "?")[:40]
        logger.info(f"  📅 [{platform}] {title} → cal_id={cal}")

    ai.report_to_telegram()
