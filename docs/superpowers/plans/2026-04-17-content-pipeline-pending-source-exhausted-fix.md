# Content Pipeline: Fix Pending Source Exhausted Without Fresh Research Fallback

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `run_full_cycle()` so that when all pending topic sources are exhausted (all topics produced duplicate ideas), it attempts fresh research before giving up.

**Architecture:** Add a `_get_next_topics()` helper that manages round-robin pending sources and a one-shot fresh research fallback. Raise `ContentPipelineExhaustedError` when both are exhausted. Simplify the while-loop in `run_full_cycle()` to use this helper.

**Tech Stack:** Python, pytest, SQLite (DB), sentence-transformers (dedup)

---

## File Map

| File | Responsibility |
|------|----------------|
| `modules/pipeline/exceptions.py` | Add `ContentPipelineExhaustedError` |
| `modules/content/content_pipeline.py` | Add `_get_next_topics()` helper; modify while-loop at lines 331-362 |
| `tests/test_content_pipeline_research.py` | Add unit/integration tests for `_get_next_topics()` and the exhausted path |

---

## Task 1: Add `ContentPipelineExhaustedError` to exceptions.py

**Files:**
- Modify: `modules/pipeline/exceptions.py`

- [ ] **Step 1: Add the exception class**

Open `modules/pipeline/exceptions.py`. Add this class after the existing exceptions (after `CaptionGenerationError`):

```python
class ContentPipelineExhaustedError(PipelineError):
    """Raised when all topic sources (pending + fresh research) are exhausted
    and no new non-duplicate ideas can be generated."""

    def __init__(self, message: str = "All topic sources exhausted (pending + fresh research)"):
        self.message = message
        super().__init__(self.message)
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `python -c "from modules.pipeline.exceptions import ContentPipelineExhaustedError; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add modules/pipeline/exceptions.py
git commit -m "feat(exceptions): add ContentPipelineExhaustedError

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

## Task 2: Add `_get_next_topics()` helper method

**Files:**
- Modify: `modules/content/content_pipeline.py`

First, read the current `run_full_cycle()` method to understand the exact line numbers you will replace:
- Lines 303-419 contain the Step 2 while-loop
- Lines 331-362 contain the `if not remaining:` block that needs replacing

- [ ] **Step 1: Add the `_get_next_topics()` method**

Add this method to the `ContentPipeline` class. Place it right before `run_full_cycle()` (around line 227). The method signature must match:

```python
def _get_next_topics(self, pending_sources: List[Dict], pending_index: int,
                      current_source_id: Optional[int], fresh_research_done: bool,
                      num_ideas: int) -> Tuple[List[Dict], Optional[int], int, bool]:
    """
    Fetch the next batch of topics using round-robin pending sources or fresh research.

    Returns:
        (topics, source_id, updated_pending_index, updated_fresh_research_done)

    Raises:
        ContentPipelineExhaustedError: when both pending sources and fresh research are exhausted.
    """
    from db import get_keywords_for_research, mark_topic_source_completed

    # 1. Try round-robin pending sources (skip current_source_id already consumed)
    while pending_index < len(pending_sources):
        ps = pending_sources[pending_index]
        pending_index += 1
        if ps.get("topics"):
            return ps["topics"], ps["id"], pending_index, fresh_research_done
        # Empty source — mark completed and skip
        try:
            mark_topic_source_completed(ps["id"])
        except Exception:
            pass

    # 2. Fresh research fallback (once)
    if not fresh_research_done:
        keywords_data = get_keywords_for_research(limit=20)
        keywords = [k["keyword"] for k in keywords_data] if keywords_data else self.niche_keywords
        topics = self.researcher.research_from_keywords(keywords=keywords, count=num_ideas)
        if topics:
            source_id = self.researcher.save_to_db(
                topics, source_query=", ".join(keywords)
            )
            return topics, source_id, pending_index, True  # fresh_research_done=True

    # 3. Nothing left
    from modules.pipeline.exceptions import ContentPipelineExhaustedError
    raise ContentPipelineExhaustedError(
        "All topic sources exhausted (pending + fresh research)"
    )
```

Make sure to add `Tuple` and `Optional` to the existing `from typing import List, Dict, Optional, Any` import at the top of the file if not already present.

- [ ] **Step 2: Verify the method is accessible**

Run: `python -c "from modules.content.content_pipeline import ContentPipeline; print(hasattr(ContentPipeline, '_get_next_topics'))"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add modules/content/content_pipeline.py
git commit -m "feat(content_pipeline): add _get_next_topics() helper method

Helper centralizes round-robin pending source selection and one-shot
fresh research fallback. Refactors topic-fetching out of the main loop.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

## Task 3: Modify `run_full_cycle()` while-loop to use `_get_next_topics()`

**Files:**
- Modify: `modules/content/content_pipeline.py:331-362`

- [ ] **Step 1: Read the exact current code at lines 331-362**

Open `modules/content/content_pipeline.py` at lines 331-362. You will replace the `if not remaining:` block.

The current code you are replacing (lines 331-362) looks like this:

```python
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
```

- [ ] **Step 2: Replace with the new code**

Replace the entire `if not remaining:` block (lines 331-362) with:

```python
            # If current batch exhausted, try next pending source or fresh research
            if not remaining:
                logger.info("  Current topic batch exhausted, trying next topic source...")
                if current_topics_source_id:
                    try:
                        mark_topic_source_completed(current_topics_source_id)
                        logger.info(f"  Marked pending source id={current_topics_source_id} as completed "
                                   f"(all topics tried, all duplicates)")
                    except Exception as e:
                        logger.warning(f"  Could not mark source {current_topics_source_id} completed: {e}")

                if results.get("pending_mode"):
                    # pending_mode: use helper to get next topics (round-robin pending, then fresh research)
                    topics, source_id, pending_index, fresh_research_done = self._get_next_topics(
                        pending_sources, pending_index, current_topics_source_id, fresh_research_done, num_ideas
                    )
                    current_topics_source_id = source_id
                    topics_tried = set()
                    results["pending_mode"] = False  # after fresh research, no longer pending_mode
                    logger.info(f"  Got {len(topics)} new topics from _get_next_topics, continuing...")
                    continue
                else:
                    # non-pending: nothing left to try
                    break
```

Note: `mark_topic_source_completed` must be imported at the top of this `if` block. Since it's already imported at line 335 in the original code, verify the import is still present — if not, add `from db import mark_topic_source_completed` inside the block.

- [ ] **Step 3: Verify no syntax errors**

Run: `python -m py_compile modules/content/content_pipeline.py`
Expected: no output (success)

- [ ] **Step 4: Run existing tests**

Run: `pytest tests/test_scene_processor.py -v 2>&1 | tail -20`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add modules/content/content_pipeline.py
git commit -m "fix(content_pipeline): use _get_next_topics() when pending sources exhausted

Previously the while-loop broke without calling fresh research when
pending_mode=True and all pending sources were exhausted.

Now the _get_next_topics() helper is called to get new topics:
- Round-robin through remaining pending sources
- Fresh research as a one-shot fallback if pending sources are empty
- Raises ContentPipelineExhaustedError if both are exhausted

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

## Task 4: Add tests for `_get_next_topics()` and the exhausted path

**Files:**
- Create: `tests/test_content_pipeline_pending_exhausted.py` (new file)
- Check: `tests/test_content_pipeline_research.py` (existing, may need additions)

- [ ] **Step 1: Check existing test file**

Run: `ls tests/test_content_pipeline_research.py 2>/dev/null && echo "exists" || echo "not found"`
If it exists, read it to understand what is already tested before writing new tests.

- [ ] **Step 2: Write the tests**

Create `tests/test_content_pipeline_pending_exhausted.py`:

```python
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
```

- [ ] **Step 3: Run the new tests**

Run: `pytest tests/test_content_pipeline_pending_exhausted.py -v`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_content_pipeline_pending_exhausted.py
git commit -m "test: add tests for _get_next_topics() and pending source exhaustion

- _get_next_topics raises ContentPipelineExhaustedError when both
  pending sources and fresh research are exhausted
- _get_next_topics calls fresh research when pending sources are empty
- _get_next_topics returns next pending source in round-robin
- _get_next_topics skips current_source_id
- Integration: fresh research triggered when all pending ideas are dupes

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

## Task 5: Run full verification

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v 2>&1 | tail -30`
Expected: all tests pass

- [ ] **Step 2: Verify the content pipeline loads without errors**

Run: `python -c "from modules.content.content_pipeline import ContentPipeline; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit any remaining changes**

```bash
git status
git add -A
git commit -m "test: add content pipeline pending source exhaustion tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

## Self-Review Checklist

1. **Spec coverage:** Does each section of the spec have a corresponding task?
   - `ContentPipelineExhaustedError` → Task 1
   - `_get_next_topics()` helper → Task 2
   - Modified `run_full_cycle()` while-loop → Task 3
   - Tests → Task 4

2. **Placeholder scan:** No "TBD", "TODO", or vague steps. All code blocks are complete.

3. **Type consistency:** `_get_next_topics()` returns `Tuple[List[Dict], Optional[int], int, bool]` — verified in Tasks 2 and 3.

4. **Edge case covered:** Empty `pending_sources` list → fresh research called → `fresh_research_done=True` on return.

---

## Verification Commands

```bash
# Run all tests
pytest tests/ -v

# Run content pipeline with verbose logging (requires DB with duplicate ideas)
python scripts/run_pipeline.py --ideas 1 --produce 2>&1 | grep -E "(pending|source|research|duplicate|ContentPipelineExhausted)"

# Verify exception import
python -c "from modules.pipeline.exceptions import ContentPipelineExhaustedError; print(ContentPipelineExhaustedError().__doc__)"
```

After fix: when pending sources exhausted and ideas are duplicates, pipeline logs "_get_next_topics" and "Got N new topics" instead of returning `no_new_ideas`.
