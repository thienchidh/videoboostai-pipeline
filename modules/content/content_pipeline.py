#!/usr/bin/env python3
"""
content_pipeline.py - Orchestrator for content research → production → social upload
"""
import os
import sys
import json
import yaml
import logging
from datetime import datetime, date, time
from pathlib import Path
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

from core.paths import PROJECT_ROOT, get_font_path

from modules.content.topic_researcher import TopicResearcher
from modules.content.content_idea_generator import ContentIdeaGenerator
from modules.content.content_calendar import ContentCalendar
from modules.pipeline.models import ChannelConfig


class ContentPipeline:
    """
    Orchestrator: Research → Ideas → Scripts → Schedule → Produce → Upload

    Config format (JSON):
    {
        "page": {
            "facebook": {"page_id": "...", "page_name": "..."},
            "tiktok": {"account_id": "...", "account_name": "..."}
        },
        "content": {
            "niche_keywords": ["productivity", "time management"],
            "cadence": {"facebook": "daily", "tiktok": "daily"},
            "research_interval_hours": 24,
            "auto_schedule": true
        }
    }
    """

    def __init__(self, project_id: int, config: Dict = None, config_path: str = None,
                 output_dir: str = None, dry_run: bool = True,
                 channel_id: str = "nang_suat_thong_minh"):
        """
        Args:
            project_id: project ID
            config: config dict
            config_path: path to config JSON file
            output_dir: where to save generated configs/scripts
            dry_run: if True, don't actually produce/upload videos
            channel_id: channel ID for scenario output (default: nang_suat_thong_minh)
        """
        self.project_id = project_id
        self.dry_run = dry_run
        self.project_root = PROJECT_ROOT
        self.channel_id = channel_id
        self.output_dir = Path(output_dir or self.project_root / "output" / "content_pipeline")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Load config
        if config_path:
            with open(config_path) as f:
                self.config = json.load(f)
        else:
            self.config = config or {}

        page_cfg = self.config.get("page", {})
        content_cfg = self.config.get("content", {})

        self.fb_page = page_cfg.get("facebook", {})
        self.tiktok_account = page_cfg.get("tiktok", {})
        self.auto_schedule = content_cfg.get("auto_schedule", True)

        # Load channel config for content generation context
        channel_cfg = {}
        channel_cfg_path = self.project_root / "configs" / "channels" / self.channel_id / "config.yaml"
        if channel_cfg_path.exists():
            with open(channel_cfg_path, encoding="utf-8") as f:
                channel_cfg = yaml.safe_load(f) or {}

        # Validate and read content research params from channel config
        validated_channel = ChannelConfig(**channel_cfg) if channel_cfg else None
        research = validated_channel.research if validated_channel else None
        self.niche_keywords = research.niche_keywords if research else []
        self.content_angle = research.content_angle if research else "tips"
        self.target_platform = research.target_platform if research else "both"

        # Store channel name for social upload fallback
        self.channel_name = validated_channel.name if validated_channel else ""

        # Initialize components
        self.researcher = TopicResearcher(
            niche_keywords=self.niche_keywords,
            project_id=project_id
        )
        self.idea_gen = ContentIdeaGenerator(
            project_id=project_id,
            content_angle=self.content_angle,
            target_platform=self.target_platform,
            niche_keywords=self.niche_keywords,
            channel_config=channel_cfg,
        )
        self.calendar = ContentCalendar(project_id=project_id)

    def run_full_cycle(self, num_ideas: int = 5) -> Dict:
        """
        Run full content cycle:
        1. Research trending topics
        2. Generate content ideas
        3. Generate scene scripts
        4. Schedule content
        """
        logger.info("=" * 50)
        logger.info("CONTENT PIPELINE - FULL CYCLE")
        logger.info("=" * 50)

        results = {}

        # Step 1: Research
        logger.info("Step 1: Researching trending topics...")
        topics = self.researcher.research_from_keywords(count=num_ideas)
        results["topics_found"] = len(topics)
        logger.info(f"  Found {len(topics)} topics")

        # Save topics to DB
        source_id = self.researcher.save_to_db(topics, source_query=", ".join(self.niche_keywords))
        results["topic_source_id"] = source_id

        # Step 2: Generate ideas
        logger.info("Step 2: Generating content ideas...")
        ideas = self.idea_gen.generate_ideas_from_topics(topics, count=num_ideas)
        results["ideas_generated"] = len(ideas)
        logger.info(f"  Generated {len(ideas)} ideas")

        idea_ids = self.idea_gen.save_ideas_to_db(ideas, source_id=source_id)
        results["idea_ids"] = idea_ids

        # Step 3: Generate scripts
        logger.info("Step 3: Generating scene scripts...")
        for idea_id in idea_ids:
            idea = ideas[idea_ids.index(idea_id)]
            script = self.idea_gen.generate_script_from_idea(idea, num_scenes=3)
            self.idea_gen.update_idea_script(idea_id, script)

            # Save script to file
            self._save_script_config(idea_id, script)
            logger.info(f"  Script saved for idea {idea_id}: {idea.get('title', '')[:50]}")

        results["scripts_generated"] = len(idea_ids)

        # Step 4: Schedule
        if self.auto_schedule:
            logger.info("Step 4: Scheduling content...")
            start_date = date.today()
            for i, idea_id in enumerate(idea_ids):
                platforms = ["facebook", "tiktok"] if self.idea_gen.target_platform == "both" else [self.idea_gen.target_platform]
                for platform in platforms:
                    cal_id = self.calendar.schedule_idea(
                        idea_id=idea_id,
                        platform=platform,
                        scheduled_date=start_date,
                        scheduled_time=time(9, 0),
                        priority="medium"
                    )
                    logger.info(f"  Scheduled idea {idea_id} for {platform} on {start_date}")
            results["scheduled"] = True

        logger.info("✅ Full cycle complete!")
        return results

    def _save_script_config(self, idea_id: int, script: Dict):
        """Save scene script as YAML scenario file for video_pipeline.

        Output path: configs/channels/{channel_id}/scenarios/{YYYY-MM-DD}/{slugified_title}.yaml
        Only 'scenes' and 'title' keys are included (PipelineContext filter).
        """
        import re
        from datetime import date

        title = script.get("title", f"idea_{idea_id}")
        scenes = script.get("scenes", [])

        # Slugify title for filename
        slug = re.sub(r'[^a-zA-Z0-9\s]', '', title)
        slug = re.sub(r'\s+', '-', slug.lower())
        slug = slug[:50]  # limit length

        # Use today's date
        scenario_date = date.today().strftime("%Y-%m-%d")

        # Build scenario output (only title + scenes for PipelineContext filter)
        scenario_data = {
            "title": title,
            "scenes": scenes,
        }

        # Ensure directory exists
        scenario_dir = self.project_root / "configs" / "channels" / self.channel_id / "scenarios" / scenario_date
        scenario_dir.mkdir(parents=True, exist_ok=True)

        config_path = scenario_dir / f"{slug}.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(scenario_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        logger.info(f"  Scenario saved: {config_path}")
        return config_path

    def produce_video(self, idea_id: int, run_dir: str = None) -> Dict:
        """
        Trigger video_pipeline for a scheduled idea.
        Returns pipeline result dict.
        """
        from db import get_content_idea

        # Get idea and script
        idea = get_content_idea(idea_id)

        if not idea:
            return {"success": False, "error": f"Idea {idea_id} not found"}

        script_json = idea.get("script_json")
        if not script_json:
            return {"success": False, "error": f"Idea {idea_id} has no script"}

        # Save config (YAML scenario file)
        idea_id_val = idea_id
        config_path = self._save_script_config(idea_id_val, script_json)

        if self.dry_run:
            logger.info(f"DRY RUN: would run pipeline with {config_path}")
            return {
                "success": True,
                "dry_run": True,
                "config_path": str(config_path),
                "idea_id": idea_id
            }

        # Run pipeline directly
        run_output_dir = run_dir or str(self.output_dir / f"run_{idea_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}")
        os.makedirs(run_output_dir, exist_ok=True)

        try:
            # Import VideoPipelineV3 directly
            from scripts.video_pipeline_v3 import VideoPipelineV3
            import scripts.video_pipeline_v3 as vp_module

            # Set global flags from content_pipeline state
            vp_module.DRY_RUN = False
            vp_module.DRY_RUN_TTS = False
            vp_module.DRY_RUN_IMAGES = False
            vp_module.UPLOAD_TO_SOCIALS = False

            # Extract channel_id from path: configs/channels/{channel_id}/scenarios/...
            config_path_obj = Path(config_path)
            rel_parts = config_path_obj.relative_to(self.project_root / "configs" / "channels").parts
            # rel_parts = (channel_id, "scenarios", date, slug.yaml)
            channel_id = rel_parts[0]

            # Run pipeline with channel_id + full YAML path
            pipeline = VideoPipelineV3(channel_id, str(config_path))
            result = pipeline.run()

            # Find output video
            output_video = None
            if result:
                for f in Path(run_output_dir).rglob("*.mp4"):
                    if "final" in f.name or "video_concat" in f.name:
                        output_video = str(f)
                        break

            return {
                "success": result is not None,
                "output_video": output_video,
                "run_dir": run_output_dir,
            }

        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            return {"success": False, "error": str(e)}

    def produce_due_items(self, platform: str = None) -> List[Dict]:
        """
        Find all due calendar items and produce videos for them.
        """
        due_items = self.calendar.get_due_items(platform=platform)
        results = []

        for item in due_items:
            idea_id = item["idea_id"]
            calendar_id = item["id"]

            logger.info(f"Producing calendar item {calendar_id}: idea {idea_id}")

            # Mark in production
            self.calendar.mark_in_production(calendar_id)

            # Run production
            prod_result = self.produce_video(idea_id)

            if prod_result["success"]:
                self.calendar.update_status(
                    calendar_id, "produced",
                    notes=f"Output: {prod_result.get('output_video', 'N/A')}"
                )
                results.append({
                    "calendar_id": calendar_id,
                    "idea_id": idea_id,
                    "result": prod_result
                })
            else:
                self.calendar.mark_failed(calendar_id, error=prod_result.get("error", "Unknown error"))
                results.append({
                    "calendar_id": calendar_id,
                    "idea_id": idea_id,
                    "result": prod_result,
                    "failed": True
                })

        return results

    def upload_to_socials(self, video_path: str, idea_id: int = None,
                        platforms: List[str] = None,
                        caption: str = None) -> List[Dict]:
        """
        Upload video to social platforms.
        """
        platforms = platforms or ["facebook", "tiktok"]
        results = []

        for platform in platforms:
            if platform == "facebook":
                result = self._upload_facebook(video_path, idea_id, caption)
            elif platform == "tiktok":
                result = self._upload_tiktok(video_path, idea_id, caption)
            else:
                result = {"success": False, "error": f"Unknown platform: {platform}"}
            results.append({"platform": platform, **result})

        return results

    def _upload_facebook(self, video_path: str, idea_id: int = None, caption: str = None) -> Dict:
        """Upload to Facebook Page."""
        if self.dry_run:
            logger.info(f"DRY RUN: would upload to Facebook: {video_path}")
            return {"success": True, "dry_run": True, "post_id": "dry_run_fb"}

        try:
            from modules.social.facebook import FacebookPublisher
            page_id = self.fb_page.get("page_id")
            if not page_id:
                return {"success": False, "error": "Facebook page_id not configured"}

            publisher = FacebookPublisher()
            post_result = publisher.publish(
                video_path=video_path,
                title=caption or f"Video from {self.channel_name}",
                description=caption or "",
                page_id=page_id,
                page_access_token=self.fb_page.get("access_token")
            )
            return post_result
        except Exception as e:
            logger.error(f"Facebook upload failed: {e}")
            return {"success": False, "error": str(e)}

    def _upload_tiktok(self, video_path: str, idea_id: int = None, caption: str = None) -> Dict:
        """Upload to TikTok."""
        if self.dry_run:
            logger.info(f"DRY RUN: would upload to TikTok: {video_path}")
            return {"success": True, "dry_run": True, "post_id": "dry_run_tt"}

        try:
            from modules.social.tiktok import TikTokPublisher
            account_id = self.tiktok_account.get("account_id")
            if not account_id:
                return {"success": False, "error": "TikTok account_id not configured"}

            publisher = TikTokPublisher()
            post_result = publisher.publish(
                video_path=video_path,
                title=caption or f"Video from {self.channel_name}",
                description=caption or "",
                account_id=account_id
            )
            return post_result
        except Exception as e:
            logger.error(f"TikTok upload failed: {e}")
            return {"success": False, "error": str(e)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Load config from project root
    config_path = PROJECT_ROOT / "configs/business/video_scenario.yaml.example"
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = yaml.safe_load(f)
    else:
        config = {
            "page": {
                "facebook": {"page_id": "YOUR_PAGE_ID", "page_name": "NangSuatThongMinh"},
                "tiktok": {"account_id": "YOUR_TIKTOK_ACCOUNT_ID", "account_name": "@NangSuatThongMinh"}
            },
            "content": {
                "auto_schedule": True
            }
        }

    pipeline = ContentPipeline(
        project_id=1,
        config=config,
        dry_run=True,
        channel_id="nang_suat_thong_minh"
    )

    print("🚀 Running full content cycle (dry-run)...")
    results = pipeline.run_full_cycle(num_ideas=3)
    print(json.dumps(results, indent=2))

    if not pipeline.dry_run:
        print("\n🎬 Producing videos for due items...")
        prod_results = pipeline.produce_due_items()
        print(json.dumps(prod_results, indent=2, default=str))
