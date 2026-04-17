"""Tests for content pipeline pending source exhaustion and fresh research fallback."""
import pytest
from unittest.mock import patch, MagicMock
from modules.content.content_pipeline import ContentPipeline
from modules.pipeline.exceptions import ContentPipelineExhaustedError
from modules.pipeline.models import ContentPipelineConfig


class TestGetNextTopics:
    """Tests for _get_next_topics() helper."""

    def _make_pipeline(self, project_id=1):
        """Create a ContentPipeline with mocked config."""
        cfg = ContentPipelineConfig(
            page={"facebook": {}, "tiktok": {}},
            content={"niche_keywords": ["productivity"], "auto_schedule": False}
        )
        return ContentPipeline(project_id=project_id, config=cfg, dry_run=True)

    def test_raises_when_pending_empty_and_fresh_done(self):
        """
        _get_next_topics() raises ContentPipelineExhaustedError when:
        - pending_sources is empty
        - fresh_research_done is True
        """
        pipeline = self._make_pipeline()

        with pytest.raises(ContentPipelineExhaustedError) as exc_info:
            pipeline._get_next_topics(
                pending_sources=[],
                pending_index=0,
                current_source_id=None,
                fresh_research_done=True,
                num_ideas=3,
            )
        assert "exhausted" in str(exc_info.value).lower()

    def test_calls_fresh_research_when_pending_exhausted(self):
        """
        _get_next_topics() returns fresh research topics when:
        - pending_sources is empty
        - fresh_research_done is False
        """
        pipeline = self._make_pipeline()
        mock_topics = [{"title": "New Topic 1"}, {"title": "New Topic 2"}]

        with patch.object(pipeline.researcher, "research_from_keywords", return_value=mock_topics) as mock_research:
            with patch.object(pipeline.researcher, "save_to_db", return_value=99) as mock_save:
                topics, source_id, new_index, fresh_done = pipeline._get_next_topics(
                    pending_sources=[],
                    pending_index=0,
                    current_source_id=None,
                    fresh_research_done=False,
                    num_ideas=3,
                )

        assert topics == mock_topics
        assert source_id == 99
        assert fresh_done is True
        mock_research.assert_called_once()
        mock_save.assert_called_once()

    def test_returns_next_pending_source(self):
        """
        _get_next_topics() returns the next pending source in round-robin.
        """
        pipeline = self._make_pipeline()
        pending_sources = [
            {"id": 10, "topics": [{"title": "Topic A"}, {"title": "Topic B"}]},
            {"id": 11, "topics": [{"title": "Topic C"}]},
        ]

        topics, source_id, new_index, fresh_done = pipeline._get_next_topics(
            pending_sources=pending_sources,
            pending_index=0,
            current_source_id=None,  # not excluded since we're starting fresh
            fresh_research_done=False,
            num_ideas=3,
        )

        assert topics == [{"title": "Topic A"}, {"title": "Topic B"}]
        assert source_id == 10
        assert fresh_done is False  # unchanged since we used pending source

    def test_skips_current_source_id(self):
        """
        _get_next_topics() skips sources matching current_source_id.
        """
        pipeline = self._make_pipeline()
        pending_sources = [
            {"id": 10, "topics": [{"title": "Topic A"}]},
            {"id": 11, "topics": [{"title": "Topic B"}]},
        ]

        # current_source_id=10 should be skipped, starting from index 0 means 10 is first
        # Since we start at index 0 and current_source_id=10 is in the list,
        # it should be skipped and we get id=11
        topics, source_id, new_index, fresh_done = pipeline._get_next_topics(
            pending_sources=pending_sources,
            pending_index=0,
            current_source_id=10,
            fresh_research_done=False,
            num_ideas=3,
        )

        assert source_id == 11
        assert topics == [{"title": "Topic B"}]


class TestPendingSourceExhaustedIntegration:
    """Integration test: all pending ideas are duplicates → fresh research is triggered."""

    def _make_pipeline(self, project_id=1):
        cfg = ContentPipelineConfig(
            page={"facebook": {}, "tiktok": {}},
            content={"niche_keywords": ["productivity"], "auto_schedule": False}
        )
        return ContentPipeline(project_id=project_id, config=cfg, dry_run=True)

    def test_fresh_research_triggered_when_all_pending_dupes(self):
        """
        When all pending sources produce only duplicate ideas,
        _get_next_topics() is called and returns fresh research topics.
        """
        pipeline = self._make_pipeline()
        mock_fresh_topics = [{"title": "Fresh Research Topic"}]

        with patch.object(pipeline.researcher, "research_from_keywords", return_value=mock_fresh_topics) as mock_research:
            with patch.object(pipeline.researcher, "save_to_db", return_value=55) as mock_save:
                topics, source_id, new_index, fresh_done = pipeline._get_next_topics(
                    pending_sources=[],  # no pending sources left
                    pending_index=0,
                    current_source_id=47,
                    fresh_research_done=False,
                    num_ideas=1,
                )

        assert topics == mock_fresh_topics
        assert fresh_done is True
        mock_research.assert_called_once()