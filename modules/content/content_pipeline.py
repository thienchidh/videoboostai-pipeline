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
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

from core.paths import PROJECT_ROOT, get_font_path

from modules.content.topic_researcher import TopicResearcher
from modules.content.content_idea_generator import ContentIdeaGenerator
from modules.content.content_calendar import ContentCalendar
from modules.content.caption_generator import CaptionGenerator
from modules.pipeline.models import (
    TechnicalConfig,
    ChannelConfig,
    ScenarioConfig,
    SocialConfig,
    ContentPipelineConfig,
    CheckpointData,
)
from modules.pipeline.backoff import Backoff, CircuitBreaker, CircuitOpenError


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

    def __init__(self, project_id: int, config: ContentPipelineConfig = None,
                 dry_run: bool = True,
                 channel_id: str = "nang_suat_thong_minh",
                 skip_lipsync: bool = False,
                 skip_content: bool = False,
                 skip_image: bool = False):
        """
        Args:
            project_id: project ID
            config: ContentPipelineConfig Pydantic model (uses defaults if None)
            dry_run: if True, don't actually produce/upload videos
            channel_id: channel ID for scenario output (default: nang_suat_thong_minh)
            skip_lipsync: if True, use static image + audio instead of lipsync (saves API costs)
            skip_content: if True, skip content generation and use existing scripts in DB (for testing production separately or re-running failed items)
            skip_image: if True, skip image generation (use placeholder image + static video to save API costs)
        """
        self.project_id = project_id
        self.dry_run = dry_run
        self.project_root = PROJECT_ROOT
        self.channel_id = channel_id
        self.skip_lipsync = skip_lipsync
        self.skip_content = skip_content
        self.skip_image = skip_image

        if config is None:
            config = ContentPipelineConfig()
        if not isinstance(config, ContentPipelineConfig):
            raise TypeError(
                f"ContentPipeline.__init__ expects a ContentPipelineConfig Pydantic model "
                f"for config=, got {type(config).__name__}. "
                f"Use ContentPipelineConfig() for defaults or ContentPipelineConfig.load(path) to load from file."
            )
        self.config = config
        self.fb_page = self.config.page.facebook
        self.tiktok_account = self.config.page.tiktok
        self.auto_schedule = self.config.content.auto_schedule

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

        # Research threshold settings
        research_cfg = validated_channel.research if validated_channel else None
        self.pending_threshold = research_cfg.threshold if research_cfg else 3
        self.pending_pool_size = research_cfg.pending_pool_size if research_cfg else 5

        # Load technical config for content generation settings
        try:
            self.technical_config = TechnicalConfig.load()
        except Exception as e:
            logger.warning(f"Could not load TechnicalConfig: {e}")
            self.technical_config = None

        # Read content settings from technical config
        if self.technical_config:
            self.scene_count = self.technical_config.generation.content.scene_count
            self.checkpoint_path = self.project_root / self.technical_config.generation.content.checkpoint_path
            schedule_hour = self.technical_config.generation.research.schedule_hour
            schedule_minute = self.technical_config.generation.research.schedule_minute
            self.schedule_time = time(schedule_hour, schedule_minute)
        else:
            self.scene_count = 3
            self.checkpoint_path = self.project_root / ".content_pipeline_checkpoint.json"
            self.schedule_time = time(9, 0)

        # Initialize components
        self.researcher = TopicResearcher(
            niche_keywords=self.niche_keywords,
            project_id=project_id
        )
        # Pass ChannelConfig directly to ContentIdeaGenerator
        self.idea_gen = ContentIdeaGenerator(
            project_id=project_id,
            content_angle=self.content_angle,
            target_platform=self.target_platform,
            niche_keywords=self.niche_keywords,
            channel_config=validated_channel,
            technical_config=self.technical_config,
        )
        self.calendar = ContentCalendar(project_id=project_id)

    def should_trigger_research(self) -> bool:
        """Check if pending pool is below threshold AND below pending_pool_size."""
        from db import get_session, models
        with get_session() as session:
            count = session.query(models.ContentIdea).filter(
                models.ContentIdea.status == "raw"
            ).count()
        # Skip research if pool is large enough (>= pending_pool_size)
        if count >= self.pending_pool_size:
            return False
        # Trigger research if pool is small (< threshold)
        return count < self.pending_threshold

    def run_research_phase(self, num_ideas: int = 5) -> Dict:
        """Run research phase: acquire lock, research topics, generate ideas, save to pending pool."""
        import uuid
        run_id = f"research_{uuid.uuid4().hex[:8]}"
        from db import acquire_research_lock, release_research_lock, is_research_locked

        if is_research_locked():
            logger.info("Research lock held by another run, skipping research")
            return {"status": "skipped_locked", "researched": 0}

        if not acquire_research_lock(run_id):
            logger.info("Could not acquire research lock, skipping")
            return {"status": "skipped_locked", "researched": 0}

        try:
            # Check threshold
            if not self.should_trigger_research():
                logger.info(f"Pending pool above threshold ({self.pending_threshold}), skipping research")
                return {"status": "skipped_threshold", "researched": 0}

            # Get keywords from pool, fallback to channel seeds
            from db import get_keywords_for_research
            keywords_data = get_keywords_for_research(limit=20)
            if keywords_data:
                keywords = [k["keyword"] for k in keywords_data]
            else:
                keywords = self.niche_keywords  # fallback to seed keywords

            # Research with circuit breaker
            cb = CircuitBreaker(max_attempts=3, open_timeout=120)
            backoff = Backoff(base_delay=3.0, max_delay=60.0, factor=2.0)

            topics = []
            for attempt in range(3):
                try:
                    cb.check()
                except CircuitOpenError as e:
                    logger.error(f"Circuit breaker open: {e}")
                    return {"status": "research_failed", "failure_reason": "circuit_breaker_open"}

                topics = self.researcher.research_from_keywords(keywords=keywords, count=num_ideas)
                if topics:
                    cb.record_success()
                    break
                else:
                    cb.record_failure()
                    logger.warning(f"Research returned empty (attempt {attempt+1}/3)")
                    if attempt < 2:
                        backoff.sleep(attempt + 1)
                    continue

            if not topics:
                return {"status": "research_failed", "failure_reason": "no_topics_from_api"}

            # Save to DB
            source_id = self.researcher.save_to_db(topics, source_query=", ".join(keywords))

            # Generate ideas from topics
            ideas = self.idea_gen.generate_ideas_from_topics(topics, count=num_ideas)

            # Save ideas to DB (status=raw — pending pool)
            idea_ids = self.idea_gen.save_ideas_to_db(ideas, source_id=source_id)

            return {
                "status": "success",
                "topics_found": len(topics),
                "ideas_generated": len(idea_ids),
                "source_id": source_id,
            }
        finally:
            release_research_lock(run_id)

    def run_full_cycle(self, num_ideas: int = 5) -> Dict:
        """
        Run full content cycle:
        1. Check pending pool → use pending topics or research new
        2. Generate content ideas
        3. Generate scene scripts + produce video
        """
        if self.skip_content:
            logger.info("⚠️  SKIP_CONTENT mode: loading existing scripts from DB")
            results = self._run_from_existing_scripts(num_ideas)
            return results

        logger.info("=" * 50)
        logger.info("CONTENT PIPELINE - FULL CYCLE")
        logger.info("=" * 50)

        results = {}

        # Check for checkpoint to resume from
        checkpoint_path = self.checkpoint_path
        checkpoint = None
        start_idea_index = 0
        if checkpoint_path.exists():
            try:
                with open(checkpoint_path) as f:
                    checkpoint = CheckpointData.model_validate_json(f.read())
                last_idx = checkpoint.last_processed_idea_index
                if last_idx >= 0:
                    start_idea_index = last_idx + 1
                    logger.info(f"📍 Resume: found checkpoint, last processed idea index: {last_idx}, starting from {start_idea_index}")
            except (json.JSONDecodeError, IOError, ValueError) as e:
                logger.warning(f"Could not load checkpoint: {e}")

        # Step 1: Run research phase if pending pool is below threshold
        from db import get_pending_topic_sources
        pending = get_pending_topic_sources(limit=1)

        if not pending and self.should_trigger_research():
            logger.info("Step 1: Pending pool below threshold, running research phase...")
            research_result = self.run_research_phase(num_ideas=num_ideas)
            results["research"] = research_result
            if research_result.get("status") == "research_failed":
                logger.warning(f"Research phase failed: {research_result.get('failure_reason')}")
            # Refresh pending pool after research
            pending = get_pending_topic_sources(limit=1)

        if pending:
            ps = pending[0]
            logger.info("Step 1b: Using pending topic source id={}".format(ps["id"]))
            topics = ps.get("topics", [])
            source_id = ps["id"]
            results["topics_found"] = len(topics)
            results["source_id"] = source_id
            results["pending_mode"] = True
            logger.info(f"  Loaded {len(topics)} topics from pending pool")
        else:
            # No pending topic sources — check for existing raw ideas in DB
            logger.info("Step 1b: No pending topics, checking for raw ideas in DB...")
            from db import get_ideas_by_status
            raw_ideas = get_ideas_by_status(project_id=self.project_id, status="raw", limit=num_ideas)
            if raw_ideas:
                logger.info(f"  Found {len(raw_ideas)} raw ideas in DB — will convert to scripts")
                # Convert raw ideas to topic format for Step 2 processing
                topics = [{"title": i.get("title", ""), "summary": i.get("description", ""),
                           "keywords": i.get("topic_keywords", []), "source_keyword": i.get("source", "")}
                          for i in raw_ideas]
                source_id = None
                results["pending_mode"] = False
                results["topics_found"] = len(topics)
                results["raw_mode"] = True
            else:
                logger.info("Step 1b: No pending topics and research not triggered, skipping research")
                topics = []
                source_id = None
                results["pending_mode"] = False

        # Step 2: Generate ideas + dedup in a loop
        # Keep loading topics until we get non-duplicate ideas or run out
        from utils.embedding import check_duplicate_ideas, save_idea_embedding

        ideas = []
        topics_tried = set()  # track by title to avoid re-checking same topics
        pending_sources = []   # round-robin list of pending sources loaded on demand
        pending_index = 0
        pending_sources_loaded = False
        # Track the source we're currently consuming (so we can mark it completed when exhausted)
        current_topics_source_id = source_id

        while len(ideas) < num_ideas:
            # Load pending sources on first iteration (after initial topics are set)
            if not pending_sources_loaded and results.get("pending_mode"):
                # Load ALL pending sources EXCEPT the current one (already in `topics`)
                # so round-robin starts from the NEXT source
                current_source_id = source_id
                all_pending = get_pending_topic_sources(limit=99)
                pending_sources = [ps for ps in all_pending if ps["id"] != current_source_id]
                pending_sources_loaded = True
                pending_index = 0
                logger.info(f"  Loaded {len(pending_sources)} pending sources for round-robin "
                            f"(current id={current_source_id} excluded)")

            # Build remaining topics from current batch
            remaining = [t for t in topics if t.get("title", "") not in topics_tried]

            # If current batch exhausted, try next pending source
            if not remaining:
                logger.info("  Current topic batch exhausted, trying next pending source...")
                # Mark the PREVIOUS source as completed (all its topics were exhausted)
                from db import mark_topic_source_completed
                if current_topics_source_id:
                    try:
                        mark_topic_source_completed(current_topics_source_id)
                        logger.info(f"  Marked pending source id={current_topics_source_id} as completed "
                                   f"(all topics tried, all duplicates)")
                    except Exception as e:
                        logger.warning(f"  Could not mark source {current_topics_source_id} completed: {e}")
                # Advance to next pending source in round-robin
                while pending_index < len(pending_sources):
                    ps = pending_sources[pending_index]
                    pending_index += 1
                    if ps.get("topics"):
                        topics = ps["topics"]
                        current_topics_source_id = ps["id"]
                        source_id = ps["id"]
                        logger.info(f"  Switched to pending source id={source_id}, {len(topics)} topics")
                        break
                    # Empty source — mark completed and skip (nothing to process)
                    logger.info(f"  Skipping empty pending source id={ps['id']} — marking completed")
                    try:
                        mark_topic_source_completed(ps["id"])
                    except Exception:
                        pass
                else:
                    # All pending sources exhausted — no more topics to try
                    logger.info("  All pending sources exhausted (all topics were duplicates)")
                    break

            # Determine how many topics to request this iteration (fill the quota)
            quota = num_ideas - len(ideas)
            topics_this_iter = remaining[:quota]

            # Track which topic titles we are about to consume
            topics_to_consume = set(t.get("title", "") for t in topics_this_iter)

            batch_ideas = self.idea_gen.generate_ideas_from_topics(topics_this_iter, count=quota)
            logger.info(f"Step 2: Generated {len(batch_ideas)} ideas from {len(topics_this_iter)} topics")

            if not batch_ideas:
                # Mark consumed topics as tried and continue
                topics_tried.update(topics_to_consume)
                continue

            # Dedup against all existing ideas in DB
            try:
                new_batch = check_duplicate_ideas(batch_ideas, self.project_id, self.technical_config)
                skipped = len(batch_ideas) - len(new_batch)
                logger.info(f"Step 2b: Dedup: {skipped} duplicates skipped, {len(new_batch)} new ideas")
            except (RuntimeError, IOError) as e:
                logger.warning(f"Embedding dedup failed: {e}, using batch without dedup")
                new_batch = batch_ideas

            # Mark topics as consumed
            topics_tried.update(topics_to_consume)

            ideas.extend(new_batch)

            if new_batch:
                # Some new ideas found — keep going to fill quota
                continue
            elif results.get("pending_mode"):
                # All ideas from this batch were duplicates in pending_mode
                # Continue to next iteration (will try next pending source if batch exhausted)
                logger.info("  All ideas from this batch are duplicates (pending_mode), continuing to next batch...")
                continue
            else:
                # Not in pending_mode: try fresh research
                if len(topics_tried) >= len(topics):
                    logger.info("  All ideas from this batch are duplicates, re-researching more topics...")
                    topics = self.researcher.research_from_keywords(count=num_ideas)
                    results["topics_found"] = len(topics)
                    topics_tried = set()  # reset - we have new topics
                    source_id = self.researcher.save_to_db(topics, source_query=", ".join(self.niche_keywords))
                    results["source_id"] = source_id
                    if not topics:
                        logger.info("  No more topics to try")
                        break
                    continue

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
        except (RuntimeError, IOError) as e:
            logger.warning(f"Could not save embeddings: {e}")

        results["idea_ids"] = idea_ids

        # Step 3: Generate scripts + produce videos
        logger.info("Step 3: Generating scripts and producing videos...")
        produced = []
        scheduled = []

        # ---- Phase 1: Generate all scripts in parallel ----
        logger.info("Step 3a: Generating all scripts in parallel...")
        script_results = []  # list of (i, idea_id, script, config_path) for non-skipped ideas

        def generate_one_script(args):
            """Generate script for one idea. Returns (i, idea_id, script, config_path) or None if skipped."""
            i, idea_id = args
            if i < start_idea_index:
                return None  # already processed
            idea = ideas[i]
            script = self.idea_gen.generate_script_from_idea(idea, num_scenes=self.scene_count)
            self.idea_gen.update_idea_script(idea_id, script)
            config_path = str(self._save_script_config(idea_id, script))
            logger.info(f"  Script generated for idea {idea_id}: {idea.get('title', '')[:50]}")
            return (i, idea_id, script, config_path)

        # Run in parallel using ThreadPoolExecutor (max_workers=3 to limit API pressure)
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(generate_one_script, (i, idea_ids[i])): i
                for i in range(len(idea_ids))
            }
            for future in as_completed(futures):
                result = future.result()
                if result:
                    script_results.append(result)

        # Sort by original index to maintain order
        script_results.sort(key=lambda x: x[0])
        logger.info(f"  Generated {len(script_results)} scripts in parallel")

        # ---- Phase 2: Produce videos sequentially (avoid disk/DB contention) ----
        logger.info("Step 3b: Producing videos sequentially...")
        for idx, (i, idea_id, script, config_path) in enumerate(script_results):
            logger.info(f"  Producing video for idea {idea_id}...")
            prod_result = self.produce_video(idea_id)
            produced.append({
                "idea_id": idea_id,
                "config_path": config_path,
                "result": prod_result,
            })
            logger.info(f"  Production result: {prod_result.get('success')}")

            # Write checkpoint after each idea is processed
            checkpoint = {
                "last_processed_idea_index": i,
                "source_id": source_id,
                "idea_ids_processed": idea_ids[:i+1],
                "timestamp": datetime.now().isoformat(),
            }
            with open(checkpoint_path, "w") as f:
                json.dump(checkpoint, f)

            # Schedule for social posting (if not dry_run and auto_schedule)
            if self.auto_schedule and prod_result.get("success") and not self.dry_run:
                platforms = ["facebook", "tiktok"] if self.idea_gen.target_platform == "both" else [self.idea_gen.target_platform]
                start_date = date.today()
                for platform in platforms:
                    cal_id = self.calendar.schedule_idea(
                        idea_id=idea_id,
                        platform=platform,
                        scheduled_date=start_date,
                        scheduled_time=self.schedule_time,
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
                # Clear checkpoint so next run starts fresh (stale checkpoint from previous
                # source would skip script generation for unrelated new ideas)
                if checkpoint_path.exists():
                    checkpoint_path.unlink()
                    logger.info(f"  Cleared content pipeline checkpoint")
            except (RuntimeError, IOError) as e:
                logger.warning(f"Could not mark topic source completed: {e}")

        results["produced"] = produced
        results["scheduled"] = scheduled

        results["scripts_generated"] = len(idea_ids)

        logger.info("✅ Full cycle complete!")
        return results

    def _save_script_config(self, idea_id: int, script: Dict):
        """Save scene script as YAML scenario file for video_pipeline.

        Output path: configs/channels/{channel_id}/scenarios/{slugified_title}.yaml
        Only 'scenes' and 'title' keys are included (PipelineContext filter).
        """
        import re
        from unidecode import unidecode

        title = script.get("title", f"idea_{idea_id}")
        scenes = script.get("scenes", [])

        # Slugify title: unidecode (VI→EN) + keep only a-z0-9 + limit length
        slug = unidecode(title)
        slug = re.sub(r'[^a-zA-Z0-9\s]', ' ', slug)  # Remove special chars
        slug = re.sub(r'\s+', '-', slug.strip().lower())  # hyphen-separated lowercase
        slug = slug[:50].strip('-')  # limit length, remove trailing hyphens

        # Build scenario output (title + video_message + scenes)
        video_message = script.get("video_message")
        scenario_data = {
            "title": title,
            "video_message": video_message,
            "scenes": scenes,
        }

        # Ensure directory exists
        scenario_dir = self.project_root / "configs" / "channels" / self.channel_id / "scenarios"
        scenario_dir.mkdir(parents=True, exist_ok=True)

        config_path = scenario_dir / f"{slug}.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(scenario_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        logger.info(f"  Scenario saved: {config_path}")
        return config_path

    def _run_from_existing_scripts(self, num_ideas: int = 5) -> Dict:
        """Load existing script_ready ideas from DB and produce videos."""
        from db import get_content_idea

        ideas = self.idea_gen.get_ideas_by_status(status="script_ready", limit=num_ideas)
        logger.info(f"  Found {len(ideas)} existing script_ready ideas")

        produced = []
        for idea in ideas:
            idea_id = idea.get("id")
            script_json = idea.get("script_json")

            if not script_json:
                logger.warning(f"  Idea {idea_id} has no script_json, skipping")
                continue

            # Save config path for this idea
            config_path = str(self._save_script_config(idea_id, script_json))

            # Mark as re_run in DB
            self.idea_gen.update_idea_status(idea_id, status="re_run")

            # Produce video
            logger.info(f"  Producing video for existing idea {idea_id}: {idea.get('title', '')[:50]}")
            prod_result = self.produce_video(idea_id, config_path=config_path)
            produced.append({
                "idea_id": idea_id,
                "config_path": config_path,
                "result": prod_result,
            })
            logger.info(f"  Production result: {prod_result.get('success')}")

        return {
            "produced": produced,
            "scripts_generated": 0,  # No new scripts generated
            "ideas_generated": 0,
            "status": "re_run_from_existing",
        }

    def produce_video(self, idea_id: int, config_path: Optional[str] = None) -> Dict:
        """
        Trigger video_pipeline for a scheduled idea.
        If config_path is not provided, saves YAML from DB first.
        Returns pipeline result dict.
        """
        import db as db_module
        from db import get_content_idea

        # Get idea and script
        idea = get_content_idea(idea_id)

        if not idea:
            return {"success": False, "error": f"Idea {idea_id} not found"}

        script_json = idea.get("script_json")
        if not script_json:
            return {"success": False, "error": f"Idea {idea_id} has no script"}

        # Generate captions for social posts
        caption_gen = CaptionGenerator(technical_config=self.technical_config)
        script_text = " ".join(
            s.get("tts", "") or s.get("script", "") for s in script_json.get("scenes", [])
        )
        full_script = f"{script_json.get('title', '')} {script_text}".strip()

        fb_caption = caption_gen.generate(full_script, platform="facebook")
        tt_caption = caption_gen.generate(full_script, platform="tiktok")

        # Save config (YAML scenario file) only if not provided by caller
        if not config_path:
            config_path = str(self._save_script_config(idea_id, script_json))

        # Extract channel_id from path: configs/channels/{channel_id}/scenarios/...
        config_path_obj = Path(config_path)
        rel_parts = config_path_obj.relative_to(self.project_root / "configs" / "channels").parts
        channel_id = rel_parts[0]

        # Acquire video production lock (prevents concurrent runs on same channel)
        video_lock_id = f"video_lock_{channel_id}_{idea_id}"
        lock_acquired = db_module.acquire_research_lock(video_lock_id, timeout_seconds=7200)
        if not lock_acquired:
            return {"success": False, "error": "Another video production is in progress for this channel"}

        try:
            if self.dry_run:
                logger.info(f"DRY RUN: would run pipeline with {config_path}")
                return {
                    "success": True,
                    "dry_run": True,
                    "config_path": str(config_path),
                    "idea_id": idea_id,
                    "captions": {
                        "facebook": fb_caption.for_facebook() if fb_caption else None,
                        "tiktok": tt_caption.for_tiktok() if tt_caption else None,
                    },
                }

            # Import VideoPipelineV3 directly
            from scripts.video_pipeline_v3 import VideoPipelineV3
            import scripts.video_pipeline_v3 as vp_module

            # Set global flags from content_pipeline state
            vp_module.DRY_RUN = False
            vp_module.DRY_RUN_TTS = False
            vp_module.DRY_RUN_IMAGES = False
            vp_module.UPLOAD_TO_SOCIALS = False
            vp_module.USE_STATIC_LIPSYNC = self.skip_lipsync

            # Run pipeline with channel_id + full YAML path (explicit flags to avoid global timing race)
            pipeline = VideoPipelineV3(
                channel_id,
                str(config_path),
                dry_run=False,
                dry_run_tts=False,
                dry_run_images=False,
                use_static_lipsync=self.skip_lipsync,
                skip_image=self.skip_image,
            )
            result = pipeline.run()

            # Get output video from runner's media_dir (VideoPipelineRunner manages its own directory structure)
            _runner = getattr(pipeline, '_runner', None)
            output_video = None
            if result and _runner is not None:
                media_dir = _runner.media_dir
                if media_dir is not None:
                    for f in media_dir.glob("*.mp4"):
                        output_video = str(f)
                        break

            # Save captions to final/ folder
            run_dir = _runner.run_dir if _runner is not None else None
            if run_dir:
                final_dir = run_dir / "final"
                fb_text = fb_caption.for_facebook() if fb_caption else ""
                tt_text = tt_caption.for_tiktok() if tt_caption else ""
                if fb_text:
                    (final_dir / "caption_facebook.txt").write_text(fb_text, encoding="utf-8")
                if tt_text:
                    (final_dir / "caption_tiktok.txt").write_text(tt_text, encoding="utf-8")

            return {
                "success": result is not None,
                "output_video": output_video,
                "run_dir": str(_runner.run_dir) if _runner is not None else None,
                "captions": {
                    "facebook": fb_caption.for_facebook() if fb_caption else None,
                    "tiktok": tt_caption.for_tiktok() if tt_caption else None,
                },
            }

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            return {"success": False, "error": str(e) if e else "unknown error"}
        finally:
            db_module.release_research_lock(video_lock_id)

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
        except (RuntimeError, IOError) as e:
            logger.error(f"Facebook upload failed: {e}", exc_info=True)
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
        except (RuntimeError, IOError) as e:
            logger.error(f"TikTok upload failed: {e}", exc_info=True)
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

    pipeline = ContentPipeline(
        project_id=1,
        config=cfg,
        config_path=None,
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
