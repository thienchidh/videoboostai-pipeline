#!/usr/bin/env python3
"""
content_pipeline.py - Orchestrator for content research → production → social upload
"""
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
from modules.pipeline.models import ChannelConfig, ContentPipelineConfig


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
                 dry_run: bool = True,
                 channel_id: str = "nang_suat_thong_minh"):
        """
        Args:
            project_id: project ID
            config: config dict
            config_path: path to config JSON file
            dry_run: if True, don't actually produce/upload videos
            channel_id: channel ID for scenario output (default: nang_suat_thong_minh)
        """
        self.project_id = project_id
        self.dry_run = dry_run
        self.project_root = PROJECT_ROOT
        self.channel_id = channel_id

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

        # Load channel config via ChannelConfig.load() with fallback to None
        try:
            validated_channel = ChannelConfig.load(self.channel_id)
        except FileNotFoundError:
            validated_channel = None

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
        # Pass ChannelConfig as dict for ContentIdeaGenerator validation
        channel_cfg_dict = validated_channel.model_dump() if validated_channel else None
        self.idea_gen = ContentIdeaGenerator(
            project_id=project_id,
            content_angle=self.content_angle,
            target_platform=self.target_platform,
            niche_keywords=self.niche_keywords,
            channel_config=channel_cfg_dict,
        )
        self.calendar = ContentCalendar(project_id=project_id)

    def run_full_cycle(self, num_ideas: int = 5) -> Dict:
        """
        Run full content cycle:
        1. Check pending pool → use pending topics or research new
        2. Generate content ideas
        3. Generate scene scripts + produce video
        """
        logger.info("=" * 50)
        logger.info("CONTENT PIPELINE - FULL CYCLE")
        logger.info("=" * 50)

        results = {}

        # Step 1: Get topics — from pending pool OR fresh research
        from db import get_pending_topic_sources
        pending = get_pending_topic_sources(limit=1)

        if pending:
            ps = pending[0]
            logger.info("Step 1: Using pending topic source id={}".format(ps["id"]))
            topics = ps.get("topics", [])
            source_id = ps["id"]
            results["topics_found"] = len(topics)
            results["source_id"] = source_id
            results["pending_mode"] = True
            logger.info(f"  Loaded {len(topics)} topics from pending pool")
        else:
            logger.info("Step 1: Researching trending topics (pending pool empty)...")
            topics = self.researcher.research_from_keywords(count=num_ideas)
            results["topics_found"] = len(topics)
            logger.info(f"  Found {len(topics)} topics")
            source_id = self.researcher.save_to_db(topics, source_query=", ".join(self.niche_keywords))
            results["source_id"] = source_id
            results["pending_mode"] = False

        # Step 2: Generate ideas + dedup in a loop
        # Keep loading topics until we get non-duplicate ideas or run out
        from utils.embedding import check_duplicate_ideas, save_idea_embedding

        ideas = []
        topics_tried = set()  # track by title to avoid re-checking same topics

        while len(ideas) < num_ideas:
            # Generate ideas from remaining topics
            remaining_topics = [t for t in topics if t.get("title", "") not in topics_tried]
            if not remaining_topics:
                logger.info("  No more topics to try from current batch")
                break

            batch_ideas = self.idea_gen.generate_ideas_from_topics(remaining_topics, count=num_ideas - len(ideas))
            logger.info(f"Step 2: Generated {len(batch_ideas)} ideas from remaining topics")

            if not batch_ideas:
                break

            # Dedup against all existing ideas in DB
            try:
                new_batch = check_duplicate_ideas(batch_ideas, self.project_id)
                skipped = len(batch_ideas) - len(new_batch)
                logger.info(f"Step 2b: Dedup: {skipped} duplicates skipped, {len(new_batch)} new ideas")
            except Exception as e:
                logger.warning(f"Embedding dedup failed: {e}, using batch without dedup")
                new_batch = batch_ideas

            # Mark topics as tried
            for t in batch_ideas:
                topics_tried.add(t.get("title", ""))

            ideas.extend(new_batch)

            # If pending_mode and all from this batch were dupes, try more topics from same source
            if not new_batch and results.get("pending_mode"):
                logger.info("  All ideas from this batch are duplicates, trying more topics from pending pool...")
                continue
            elif not new_batch:
                # Fresh research: if all dupes and no more topics, stop
                if len(topics_tried) >= len(topics):
                    logger.info("  No more topics to try")
                    break

        if not ideas:
            logger.warning("No new ideas after dedup. All topics were duplicates of recent content.")
            results["scripts_generated"] = 0
            results["status"] = "no_new_ideas"
            return results

        ideas = ideas[:num_ideas]  # respect requested count
        results["ideas_generated"] = len(ideas)

        # Save ideas to DB (only new ones)
        idea_ids = self.idea_gen.save_ideas_to_db(ideas, source_id=source_id)

        # Save embeddings for new ideas
        try:
            from utils.embedding import save_idea_embedding
            for i, idea_id in enumerate(idea_ids):
                idea = ideas[i]
                embedding = idea.get("_embedding")
                if embedding:
                    save_idea_embedding(
                        idea_id=idea_id,
                        title_vi=idea.get("title", ""),
                        title_en="",  # No translation needed with multilingual model
                        embedding=embedding,
                    )
        except Exception as e:
            logger.warning(f"Could not save embeddings: {e}")

        results["idea_ids"] = idea_ids

        # Step 3: Generate scripts + produce videos
        logger.info("Step 3: Generating scripts and producing videos...")
        produced = []
        scheduled = []

        for i, idea_id in enumerate(idea_ids):
            idea = ideas[i]
            script = self.idea_gen.generate_script_from_idea(idea, num_scenes=3)
            self.idea_gen.update_idea_script(idea_id, script)

            # Save script to file
            config_path = self._save_script_config(idea_id, script)
            logger.info(f"  Script saved for idea {idea_id}: {idea.get('title', '')[:50]}")

            # Produce video immediately for this just-generated script
            logger.info(f"  Producing video for idea {idea_id}...")
            prod_result = self.produce_video(idea_id)
            produced.append({
                "idea_id": idea_id,
                "config_path": str(config_path),
                "result": prod_result,
            })
            logger.info(f"  Production result: {prod_result.get('success')}")

            # Schedule for social posting (if not dry_run and auto_schedule)
            if self.auto_schedule and prod_result.get("success") and not self.dry_run:
                platforms = ["facebook", "tiktok"] if self.idea_gen.target_platform == "both" else [self.idea_gen.target_platform]
                start_date = date.today()
                for platform in platforms:
                    cal_id = self.calendar.schedule_idea(
                        idea_id=idea_id,
                        platform=platform,
                        scheduled_date=start_date,
                        scheduled_time=time(9, 0),
                        priority="medium"
                    )
                    scheduled.append({"idea_id": idea_id, "platform": platform, "calendar_id": cal_id})
                    logger.info(f"  Scheduled {idea_id} for {platform}")

        # Mark topic source as completed after all YAML files are saved successfully
        if source_id:
            from db import mark_topic_source_completed
            try:
                mark_topic_source_completed(source_id)
                logger.info(f"  Topic source {source_id} marked as completed")
            except Exception as e:
                logger.warning(f"Could not mark topic source completed: {e}")

        results["produced"] = produced
        results["scheduled"] = scheduled

        results["scripts_generated"] = len(idea_ids)

        logger.info("✅ Full cycle complete!")
        return results

    def _save_script_config(self, idea_id: int, script: Dict):
        """Save scene script as YAML scenario file for video_pipeline.

        Output path: configs/channels/{channel_id}/scenarios/{YYYY-MM-DD}/{slugified_title}.yaml
        Only 'scenes' and 'title' keys are included (PipelineContext filter).
        """
        import re
        from datetime import date
        from unidecode import unidecode

        title = script.get("title", f"idea_{idea_id}")
        scenes = script.get("scenes", [])

        # Slugify title: unidecode (VI→EN) + keep only a-z0-9 + limit length
        slug = unidecode(title)
        slug = re.sub(r'[^a-zA-Z0-9\s]', ' ', slug)  # Remove special chars
        slug = re.sub(r'\s+', '-', slug.strip().lower())  # hyphen-separated lowercase
        slug = slug[:50].strip('-')  # limit length, remove trailing hyphens

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

    def produce_video(self, idea_id: int, config_path: Optional[str] = None) -> Dict:
        """
        Trigger video_pipeline for a scheduled idea.
        If config_path is not provided, saves YAML from DB first.
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

        # Save config (YAML scenario file) only if not provided by caller
        if not config_path:
            config_path = str(self._save_script_config(idea_id, script_json))

        if self.dry_run:
            logger.info(f"DRY RUN: would run pipeline with {config_path}")
            return {
                "success": True,
                "dry_run": True,
                "config_path": str(config_path),
                "idea_id": idea_id
            }

        # Run pipeline directly
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

            # Get output video from runner's media_dir (VideoPipelineRunner manages its own directory structure)
            output_video = None
            if result:
                media_dir = pipeline._runner.media_dir
                for f in media_dir.glob("*.mp4"):
                    output_video = str(f)
                    break

            return {
                "success": result is not None,
                "output_video": output_video,
                "run_dir": str(pipeline._runner.run_dir),
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

    # Initialize DB schema if not exists
    from db import init_db_full
    try:
        init_db_full()
        logger.info("DB schema ready")
    except Exception as e:
        logger.warning(f"DB init skipped (may already exist): {e}")

    # Load config from project root via Pydantic
    config_path = PROJECT_ROOT / "configs/business/video_scenario.yaml.example"
    cfg = ContentPipelineConfig.load_or_default(config_path)
    config = cfg.model_dump()

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
