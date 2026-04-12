#!/usr/bin/env python3
"""
content_pipeline.py - Orchestrator for content research → production → social upload
"""
import os
import sys
import json
import logging
import subprocess
from datetime import datetime, date, time
from pathlib import Path
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from modules.content.topic_researcher import TopicResearcher
from modules.content.content_idea_generator import ContentIdeaGenerator
from modules.content.content_calendar import ContentCalendar


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
                 output_dir: str = None, dry_run: bool = True):
        """
        Args:
            project_id: project ID
            config: config dict
            config_path: path to config JSON file
            output_dir: where to save generated configs/scripts
            dry_run: if True, don't actually produce/upload videos
        """
        self.project_id = project_id
        self.dry_run = dry_run
        self.project_root = Path(__file__).parent.parent.parent  # project root
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
        self.niche_keywords = content_cfg.get("niche_keywords", ["productivity", "time management"])
        self.cadence = content_cfg.get("cadence", {"facebook": "daily", "tiktok": "daily"})
        self.auto_schedule = content_cfg.get("auto_schedule", True)

        # Initialize components
        self.researcher = TopicResearcher(
            niche_keywords=self.niche_keywords,
            project_id=project_id
        )
        self.idea_gen = ContentIdeaGenerator(
            project_id=project_id,
            content_angle="tips",
            niche_keywords=self.niche_keywords
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
        """Save scene script as JSON config file for video_pipeline."""
        script_config = {
            "video": {
                "title": script.get("title", ""),
                "aspect_ratio": "9:16",
                "style": script.get("style", "3D animated Pixar Disney style"),
                "resolution": "480p",
                "fps": 25
            },
            "subtitle": {
                "enable": True,
                "font": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "font_size": 60,
                "color": "yellow",
                "language": "vi"
            },
            "background_music": {
                "enable": True,
                "file": "random",
                "volume": 0.15,
                "fade_duration": 2
            },
            "watermark": {
                "enable": True,
                "text": "@NangSuatThongMinh",
                "font": "LiberationSans-Bold",
                "font_size": 64,
                "opacity": 15,
                "shadow_opacity": 12,
                "stroke_opacity": 50,
                "velocity_x": 1.2,
                "velocity_y": 0.8,
                "margin": 5
            },
            "prompt": {
                "style": script.get("style", ""),
                "script_hints": {
                    "default": "modern office, productive workspace, Pixar Disney quality"
                }
            },
            "characters": [
                {
                    "name": "GiaoVien",
                    "description": "friendly female professional",
                    "prompt": "3D animated Pixar Disney style friendly professional woman, modern office attire, warm smile",
                    "avatar_file": "GiaoVien.png",
                    "tts_voice": "Vietnamese_kindhearted_girl",
                    "tts_speed": 1.0,
                    "auto_create": True
                }
            ],
            "scenes": script.get("scenes", [])
        }

        config_path = self.output_dir / f"idea_{idea_id}_config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(script_config, f, ensure_ascii=False, indent=2)

        logger.info(f"  Config saved: {config_path}")

    def produce_video(self, idea_id: int, run_dir: str = None) -> Dict:
        """
        Trigger video_pipeline_v3.py for a scheduled idea.
        Returns pipeline result dict.
        """
        from db import get_db
        from psycopg2.extras import RealDictCursor

        # Get idea and script
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM content_ideas WHERE id = %s", (idea_id,))
                idea = cur.fetchone()

        if not idea:
            return {"success": False, "error": f"Idea {idea_id} not found"}

        script_json = idea.get("script_json")
        if not script_json:
            return {"success": False, "error": f"Idea {idea_id} has no script"}

        # Save config
        idea_id_val = idea_id
        self._save_script_config(idea_id_val, script_json)
        config_path = self.output_dir / f"idea_{idea_id_val}_config.json"

        if self.dry_run:
            logger.info(f"DRY RUN: would run video_pipeline_v3.py with {config_path}")
            return {
                "success": True,
                "dry_run": True,
                "config_path": str(config_path),
                "idea_id": idea_id
            }

        # Run pipeline
        run_output_dir = run_dir or str(self.output_dir / f"run_{idea_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}")
        os.makedirs(run_output_dir, exist_ok=True)

        try:
            project_root = Path(__file__).parent.parent.parent
            pipeline_path = project_root / "video_pipeline_v3.py"
            secrets_path = project_root / "configs" / "business" / "secrets.json"
            if not pipeline_path.exists():
                pipeline_path = project_root / "video_config_secrets.json"
            if not secrets_path.exists():
                secrets_path = project_root / "video_config_secrets.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(pipeline_path),
                    str(config_path),
                    str(secrets_path),
                    "--output-dir", run_output_dir
                ],
                capture_output=True,
                text=True,
                timeout=900
            )

            success = result.returncode == 0

            # Find output video
            output_video = None
            if success:
                for f in Path(run_output_dir).rglob("*.mp4"):
                    if "final" in f.name or "video_concat" in f.name:
                        output_video = str(f)
                        break

            return {
                "success": success,
                "returncode": result.returncode,
                "output_video": output_video,
                "run_dir": run_output_dir,
                "stdout": result.stdout[-500:],
                "stderr": result.stderr[-500:]
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Pipeline timeout (>15 min)"}
        except Exception as e:
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
            from modules.social.facebook_publisher import FacebookPublisher
            page_id = self.fb_page.get("page_id")
            if not page_id:
                return {"success": False, "error": "Facebook page_id not configured"}

            publisher = FacebookPublisher()
            post_result = publisher.publish(
                video_path=video_path,
                title=caption or "Video from NangSuatThongMinh",
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
            from modules.social.tiktok_publisher import TikTokPublisher
            account_id = self.tiktok_account.get("account_id")
            if not account_id:
                return {"success": False, "error": "TikTok account_id not configured"}

            publisher = TikTokPublisher()
            post_result = publisher.publish(
                video_path=video_path,
                title=caption or "Video from NangSuatThongMinh",
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
    project_root = Path(__file__).parent.parent.parent
    config_path = project_root / "video_config_content.json"
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
    else:
        config = {
            "page": {
                "facebook": {"page_id": "YOUR_PAGE_ID", "page_name": "NangSuatThongMinh"},
                "tiktok": {"account_id": "YOUR_TIKTOK_ACCOUNT_ID", "account_name": "@NangSuatThongMinh"}
            },
            "content": {
                "niche_keywords": ["productivity", "time management", "năng suất"],
                "auto_schedule": True
            }
        }

    pipeline = ContentPipeline(
        project_id=1,
        config=config,
        dry_run=True
    )

    print("🚀 Running full content cycle (dry-run)...")
    results = pipeline.run_full_cycle(num_ideas=3)
    print(json.dumps(results, indent=2))
