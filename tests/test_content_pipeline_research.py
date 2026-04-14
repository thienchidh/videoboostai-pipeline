#!/usr/bin/env python3
"""
tests/test_content_pipeline_research.py — Integration test for content pipeline
re-research behavior when all ideas from a research batch are duplicates.

Bug: In run_full_cycle(), if research_from_keywords returns topics whose
ideas are ALL duplicates, the pipeline breaks without re-researching more topics.

Expected behavior after fix: pipeline should call research_from_keywords
AGAIN when all ideas from the first batch are duplicates.
"""
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

logging.getLogger("modules.content").setLevel(logging.WARNING)


class TestContentPipelineReResearch:
    """Tests for content pipeline topic re-research on duplicate exhaustion."""

    def test_research_called_again_when_all_dupes(self, tmp_path):
        """
        When all ideas from a research batch are duplicates,
        the pipeline should re-research more topics.

        Setup:
        - No pending topic sources (fresh research path)
        - First research call returns 2 topics → ideas generated
        - check_duplicate_ideas returns [] (all ideas are dupes)
        - Pipeline exhausts first batch → should call research_from_keywords AGAIN
        - Second research call returns 2 new topics
        - check_duplicate_ideas on second batch returns non-empty → ideas found

        Before fix: research only called once → results["status"] == "no_new_ideas"
        After fix:  research called twice → ideas found
        """
        # ─── Shared state for mock side effects ────────────────────
        research_call_count = 0
        dedup_call_count = 0

        def mock_research_from_keywords(count):
            nonlocal research_call_count
            research_call_count += 1
            if research_call_count == 1:
                return [
                    {"title": "Topic A - Productivity Tips", "summary": "Desc A", "keywords": ["productivity"]},
                    {"title": "Topic B - Time Management", "summary": "Desc B", "keywords": ["time"]},
                ]
            else:
                return [
                    {"title": "Topic C - Morning Routine", "summary": "Desc C", "keywords": ["morning"]},
                    {"title": "Topic D - Healthy Habits", "summary": "Desc D", "keywords": ["health"]},
                ]

        def mock_check_dup(ideas, project_id):
            nonlocal dedup_call_count
            dedup_call_count += 1
            if dedup_call_count == 1:
                return []  # first batch: all dupes
            return ideas  # second batch: not dupes

        def mock_generate_ideas(topics, count):
            return [
                {
                    "title": t.get("title", ""),
                    "description": t.get("summary", ""),
                    "topic_keywords": t.get("keywords", []),
                    "content_angle": "tips",
                    "target_platform": "both",
                    "source": "research",
                }
                for t in topics
            ]

        # ─── Mock instances ─────────────────────────────────────────
        mock_researcher_instance = MagicMock()
        mock_researcher_instance.research_from_keywords.side_effect = mock_research_from_keywords
        mock_researcher_instance.save_to_db.return_value = 999
        mock_researcher_instance.niche_keywords = ["productivity"]

        mock_idea_gen_instance = MagicMock()
        mock_idea_gen_instance.generate_ideas_from_topics.side_effect = mock_generate_ideas
        mock_idea_gen_instance.save_ideas_to_db.return_value = [1, 2, 3, 4]
        mock_idea_gen_instance.update_idea_script = MagicMock()
        mock_idea_gen_instance.target_platform = "both"

        mock_channel_instance = MagicMock()
        mock_channel_instance.name = "test_channel"
        mock_channel_instance.watermark = MagicMock(text="@test")
        mock_channel_instance.style = "viral"
        mock_channel_instance.voices = []
        mock_channel_instance.characters = []
        mock_channel_instance.tts = MagicMock(min_duration=2.0, max_duration=15.0)
        mock_research_cfg = MagicMock()
        mock_research_cfg.niche_keywords = ["productivity"]
        mock_research_cfg.content_angle = "tips"
        mock_research_cfg.target_platform = "both"
        mock_channel_instance.research = mock_research_cfg

        mock_calendar_instance = MagicMock()
        mock_caption_instance = MagicMock()
        mock_vp3_instance = MagicMock()
        mock_vp3_instance.run.return_value = True
        mock_vp3_instance._runner = MagicMock()
        mock_vp3_instance._runner.media_dir = tmp_path / "media"
        mock_vp3_instance._runner.run_dir = tmp_path / "run"

        # ─── Patch at point-of-use in content_pipeline ───────────────
        # This replaces the class references that ContentPipeline.__init__
        # imports from the top of content_pipeline.py
        with \
            patch("modules.content.content_pipeline.TopicResearcher",
                  return_value=mock_researcher_instance), \
            patch("modules.content.content_pipeline.ContentIdeaGenerator",
                  return_value=mock_idea_gen_instance), \
            patch("modules.content.content_pipeline.ContentCalendar",
                  return_value=mock_calendar_instance), \
            patch("modules.content.content_pipeline.CaptionGenerator",
                  return_value=mock_caption_instance), \
            patch("modules.content.content_pipeline.PROJECT_ROOT", tmp_path), \
            patch("scripts.video_pipeline_v3.VideoPipelineV3",
                  return_value=mock_vp3_instance) as MockVP3, \
            patch("core.paths.PROJECT_ROOT", tmp_path), \
            patch("modules.pipeline.models.ChannelConfig.load",
                  return_value=mock_channel_instance), \
            patch("modules.content.content_pipeline.ContentPipelineConfig.load",
                  return_value=MagicMock(page={"facebook": {}, "tiktok": {}}, content={"auto_schedule": False})), \
            patch("db.get_pending_topic_sources", return_value=[]), \
            patch("utils.embedding.check_duplicate_ideas", side_effect=mock_check_dup), \
            patch("utils.embedding.save_idea_embedding"), \
            patch("db.mark_topic_source_completed"):\

            from modules.content.content_pipeline import ContentPipeline

            pipeline = ContentPipeline(
                project_id=1,
                config={},
                channel_id="test_channel",
                dry_run=True,
                skip_lipsync=True,
                skip_content=False,
            )

            with patch.object(pipeline, "_save_script_config", return_value=tmp_path / "test.yaml"):
                results = pipeline.run_full_cycle(num_ideas=2)

        # ─── Assertions ─────────────────────────────────────────────
        assert research_call_count >= 2, (
            f"Expected research to be called at least 2× (initial + re-research when all dupes), "
            f"but was called only {research_call_count}×. "
            f"This reproduces the bug: pipeline breaks without re-researching when first batch "
            f"ideas are all duplicates. After fix, research should be called again."
        )

        assert results.get("status") != "no_new_ideas", (
            f"Pipeline returned 'no_new_ideas' but after re-research, ideas should have been found. "
            f"results={results}"
        )

        assert results.get("ideas_generated", 0) > 0, (
            f"Expected ideas to be generated after re-research, but got ideas_generated=0. "
            f"results={results}"
        )

        assert dedup_call_count >= 2, (
            f"check_duplicate_ideas should be called at least twice (once per research batch), "
            f"but was called {dedup_call_count}×"
        )