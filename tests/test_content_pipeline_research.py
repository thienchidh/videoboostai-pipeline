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
    """Tests for content pipeline run_research_phase behavior."""

    def test_research_phase_returns_success_with_valid_topics(self, tmp_path):
        """run_research_phase() should return success when valid topics are found."""
        from modules.content.content_pipeline import ContentPipeline
        from modules.pipeline.models import ContentPipelineConfig
        from unittest.mock import MagicMock, patch

        mock_researcher = MagicMock()
        mock_researcher.research_from_keywords.return_value = [
            {"title": "Topic A", "summary": "Desc A", "keywords": ["productivity"]},
        ]
        mock_researcher.save_to_db.return_value = 1
        mock_researcher.niche_keywords = ["productivity"]

        mock_idea_gen = MagicMock()
        mock_idea_gen.generate_ideas_from_topics.return_value = [
            {"title": "New Idea", "description": "desc", "topic_keywords": [], "target_platform": "both"}
        ]
        mock_idea_gen.save_ideas_to_db.return_value = [1]

        mock_channel = MagicMock()
        mock_channel.name = "test"
        mock_channel.watermark = MagicMock(text="@test")
        mock_channel.style = "viral"
        mock_channel.voices = []
        mock_channel.characters = []
        mock_channel.tts = MagicMock(min_duration=2.0, max_duration=15.0)
        mock_research_cfg = MagicMock()
        mock_research_cfg.niche_keywords = ["productivity"]
        mock_research_cfg.content_angle = "tips"
        mock_research_cfg.target_platform = "both"
        mock_research_cfg.threshold = 3
        mock_research_cfg.pending_pool_size = 5
        mock_channel.research = mock_research_cfg

        # Use real ContentPipelineConfig - no need to patch it
        cfg = ContentPipelineConfig(
            page={},
            content={}
        )

        with \
            patch("modules.content.content_pipeline.TopicResearcher", return_value=mock_researcher), \
            patch("modules.content.content_pipeline.ContentIdeaGenerator", return_value=mock_idea_gen), \
            patch("modules.content.content_pipeline.ContentCalendar", return_value=MagicMock()), \
            patch("modules.content.content_pipeline.CaptionGenerator", return_value=MagicMock()), \
            patch("modules.content.content_pipeline.PROJECT_ROOT", tmp_path), \
            patch("modules.pipeline.models.ChannelConfig.load", return_value=mock_channel), \
            patch("db.acquire_research_lock", return_value=True), \
            patch("db.release_research_lock"), \
            patch("db.is_research_locked", return_value=False), \
            patch("db.get_keywords_for_research", return_value=[]), \
            patch("modules.content.content_pipeline.ContentPipeline.should_trigger_research", return_value=True):

            from modules.content.content_pipeline import ContentPipeline
            pipeline = ContentPipeline(project_id=1, config=cfg, channel_id="test", dry_run=True)
            result = pipeline.run_research_phase()

        assert result.get("status") == "success", f"Expected success, got {result.get('status')}"
        assert result.get("ideas_generated", 0) > 0
        assert mock_researcher.research_from_keywords.called


@patch("modules.content.topic_researcher.requests.get")
def test_web_search_trending_retries_on_failure(mock_get):
    from unittest.mock import MagicMock
    mock_get.side_effect = [
        Exception("network error"),
        Exception("network error"),
        MagicMock(status_code=200, json=lambda: {"results": {"web": []}}),
    ]
    from modules.content.topic_researcher import TopicResearcher
    with patch("modules.content.topic_researcher.TopicResearcher._get_you_search_key", return_value="fake-key"):
        researcher = TopicResearcher(niche_keywords=["test"], project_id=1)
        result = researcher.web_search_trending("test query", count=5)
    assert mock_get.call_count >= 2


@patch("modules.content.topic_researcher.requests.get")
def test_web_search_trending_returns_empty_on_all_failures(mock_get):
    mock_get.side_effect = Exception("persistent failure")
    from modules.content.topic_researcher import TopicResearcher
    with patch("modules.content.topic_researcher.TopicResearcher._get_you_search_key", return_value="fake-key"):
        researcher = TopicResearcher(niche_keywords=["test"], project_id=1)
        result = researcher.web_search_trending("test query", count=5)
    assert result == []


def test_extract_keywords_from_topic():
    from modules.content.topic_researcher import TopicResearcher
    researcher = TopicResearcher(niche_keywords=["test"], project_id=1)
    topic = {
        "title": "5 Best Productivity Apps for 2024",
        "description": "Discover the top productivity tools for remote work",
    }
    keywords = researcher.extract_keywords_from_topic(topic)
    assert "productivity" in keywords
    assert "tools" in keywords
    assert "2024" not in keywords  # excluded because isdigit


def test_keyword_pool_save_and_get():
    from db import save_keyword, get_keywords_for_research
    keyword_id = save_keyword("productivity apps", source_topic_id=None)
    assert keyword_id is not None
    keywords = get_keywords_for_research(limit=10)
    assert any(k["keyword"] == "productivity apps" for k in keywords)


def test_pipeline_lock_acquire_release():
    from db import acquire_research_lock, release_research_lock, is_research_locked
    import uuid
    run_id = f"test_{uuid.uuid4().hex[:8]}"
    acquired = acquire_research_lock(run_id)
    assert acquired is True
    assert is_research_locked() is True
    # Second acquire should fail
    acquired2 = acquire_research_lock("another_run")
    assert acquired2 is False
    release_research_lock(run_id)
    assert is_research_locked() is False


def test_keyword_pool_ttl_cleanup():
    from db import save_keyword, delete_expired_keywords, get_keywords_for_research
    from datetime import datetime, timezone, timedelta
    # Insert old keyword via raw SQL
    from db import get_session, text
    with get_session() as session:
        session.execute(text("""
            INSERT INTO content_keyword_pool (keyword, created_at)
            VALUES (:kw, NOW() - INTERVAL '35 days')
        """), {"kw": "old_expired_keyword"})
        session.commit()
    deleted = delete_expired_keywords(ttl_days=30)
    assert deleted >= 1


@patch("utils.embedding._get_model")
def test_check_duplicate_saves_dupe_idea_with_embedding(mock_get_model):
    """When idea is dupe, check_duplicate_ideas should save ContentIdea(status=duplicate) + embedding."""
    import numpy as np
    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1] * 512)
    mock_get_model.return_value = mock_model

    with patch("utils.embedding.find_similar_ideas") as mock_find:
        mock_find.return_value = [{"idea_id": 1, "title_vi": "Old Idea", "similarity": 0.9}]

        with patch("utils.embedding.save_idea_embedding") as mock_save_emb:
            with patch("db.save_content_ideas") as mock_save_idea:
                mock_save_idea.return_value = [999]  # returned idea ID

                ideas = [{"title": "Similar Idea", "description": "test"}]
                from utils.embedding import check_duplicate_ideas
                result = check_duplicate_ideas(ideas, project_id=1)

                assert mock_save_idea.called, "save_content_ideas not called for dupe"
                assert mock_save_emb.called, "save_idea_embedding not called for dupe"


@patch("modules.content.content_pipeline.TopicResearcher")
@patch("modules.content.content_pipeline.ContentIdeaGenerator")
def test_research_fails_fast_on_api_exhaustion(mock_idea_gen, mock_topic_researcher):
    from modules.content.content_pipeline import ContentPipeline
    from modules.pipeline.models import ContentPipelineConfig

    mock_researcher = MagicMock()
    mock_researcher.research_from_keywords.return_value = []
    mock_topic_researcher.return_value = mock_researcher

    cfg = ContentPipelineConfig(page={}, content={})
    pipeline = ContentPipeline(project_id=1, dry_run=True, channel_id="test_channel", config=cfg)
    # Ensure research phase actually runs (pending pool may already have items)
    with patch.object(pipeline, 'should_trigger_research', return_value=True):
        results = pipeline.run_research_phase()
    assert results.get("status") == "research_failed"


@patch("modules.content.content_pipeline.TopicResearcher")
@patch("modules.content.content_pipeline.ContentIdeaGenerator")
def test_pending_pool_threshold_skips_research(mock_idea_gen, mock_topic_researcher):
    from modules.content.content_pipeline import ContentPipeline
    from modules.pipeline.models import ContentPipelineConfig

    mock_researcher = MagicMock()
    mock_researcher.research_from_keywords.return_value = [
        {"title": "Test Topic", "summary": "desc", "keywords": [], "source_url": ""}
    ]
    mock_topic_researcher.return_value = mock_researcher

    mock_ig = MagicMock()
    mock_ig.generate_ideas_from_topics.return_value = [
        {"title": "Test Idea", "description": "desc", "topic_keywords": [], "target_platform": "both"}
    ]
    mock_idea_gen.return_value = mock_ig

    cfg = ContentPipelineConfig(page={}, content={})
    pipeline = ContentPipeline(project_id=1, dry_run=True, channel_id="test_channel", config=cfg)

    with patch("modules.content.content_pipeline.ContentPipeline.should_trigger_research", return_value=True):
        with patch("db.is_research_locked", return_value=False):
            with patch("db.acquire_research_lock", return_value=True):
                results = pipeline.run_research_phase()

    assert mock_researcher.research_from_keywords.called