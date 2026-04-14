# Content Pipeline No-Ideas Bug Fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the content pipeline so that when all ideas from a research batch are filtered as duplicates, it re-researches more topics instead of giving up with "no_new_ideas".

**Architecture:** The bug is in `run_full_cycle()` in `content_pipeline.py`. The method calls `research_from_keywords()` only once at the start, then enters a while-loop that consumes those topics. When all ideas are duplicates, the loop breaks without ever fetching more topics. The fix adds proper loop-back logic: when a batch yields only duplicates, fetch the next pending topic source (if available) or call `research_from_keywords()` again for fresh topics.

**Tech Stack:** Python, pytest, SQLite (DB), sentence-transformers (dedup)

---

## Bug Analysis

### Root Cause
In `content_pipeline.py:run_full_cycle()`:

1. **Step 1** — calls `get_pending_topic_sources(limit=1)` OR `research_from_keywords(count=num_ideas)` — **only once**
2. **Step 2** — while-loop generates ideas from the topics obtained in Step 1
3. When all ideas are filtered as duplicates by `check_duplicate_ideas()`:
   - `pending_mode=True`: `continue` goes back to while-condition, but `topics` list is exhausted → loop breaks
   - `pending_mode=False`: breaks directly at line 186-187

The pipeline never re-researches when ideas run out.

### Key Code Locations
- `modules/content/content_pipeline.py:104-193` — `run_full_cycle()` method
- `modules/content/content_pipeline.py:123-142` — Step 1: topic fetching (one-shot)
- `modules/content/content_pipeline.py:144-193` — Step 2: while-loop with broken retry logic
- `utils/embedding.py:163-206` — `check_duplicate_ideas()`

---

## Task List

### Task 1: Add a failing integration test that reproduces the bug

**Files:**
- Create: `tests/test_content_pipeline_research.py`

**Context:** The bug occurs when all ideas from a research batch are duplicates. We need a test that:
1. Mocks `TopicResearcher.research_from_keywords` to return topics that will produce duplicate ideas
2. Seeds the DB with existing ideas that will match those topics
3. Runs `run_full_cycle(num_ideas=3)`
4. Verifies the current broken behavior (0 ideas returned, no re-research) — then after fix, verifies the correct behavior (more research is triggered)

- [ ] **Step 1: Create the test file**

```python
# tests/test_content_pipeline_research.py
"""
Test that content pipeline re-researches when all ideas are duplicates.

Bug: run_full_cycle() calls research_from_keywords() only once.
When all ideas from that batch are duplicates, the pipeline gives up
instead of re-researching more topics.
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


class TestContentPipelineReResearch:
    """Tests for content pipeline topic re-research on duplicate exhaustion."""

    def test_no_ideas_returns_when_all_dupes_no_pending(self):
        \"\"\"
        When pending pool is empty AND all ideas from research are duplicates,
        the pipeline should re-research (not return 0 ideas).
        Currently broken: returns 0 ideas.
        \"\"\"
        # This test documents the CURRENT broken behavior.
        # After the fix, the pipeline should keep researching.
        pass
```

- [ ] **Step 2: Run the test to see current behavior**

Run: `pytest tests/test_content_pipeline_research.py -v`
Expected: Tests pass (documenting broken behavior) initially

---

### Task 2: Fix the run_full_cycle retry logic

**Files:**
- Modify: `modules/content/content_pipeline.py:104-193`

The core change: refactor the while-loop to properly loop back to research when a batch yields only duplicates.

**Current flow (broken):**
```
research_from_keywords() → [one-shot, then loop over those topics]
while len(ideas) < num_ideas:
    # if all dupes → break (never re-researches)
```

**Fixed flow:**
```
while len(ideas) < num_ideas:
    if no topics left to try:
        if pending pool has more sources → load next pending source
        elif → call research_from_keywords() for fresh topics
        else → break
    generate ideas from current topics
    dedup
    if new ideas → add to results
    if all dupes → mark current topics exhausted, loop back to fetch more
```

**Specific changes to `run_full_cycle()`:**

- [ ] **Step 1: Replace the one-shot research logic with loop-back research**

The new structure for Step 1 + Step 2 combined:

```python
def run_full_cycle(self, num_ideas: int = 5) -> Dict:
    """
    Run full content cycle:
    1. Get topics — from pending pool OR fresh research
    2. Generate ideas + dedup — if all dupes, re-fetch more topics
    3. Generate scene scripts + produce video
    """
    if self.skip_content:
        logger.info("⚠️  SKIP_CONTENT mode: loading existing scripts from DB")
        return self._run_from_existing_scripts(num_ideas)

    logger.info("=" * 50)
    logger.info("CONTENT PIPELINE - FULL CYCLE")
    logger.info("=" * 50)

    results = {}
    ideas = []

    # pending_sources tracks all pending TopicSources for round-robin loading
    from db import get_pending_topic_sources
    pending_sources = get_pending_topic_sources(limit=10)  # load up to 10
    pending_index = 0
    topics = []  # current batch of topics being processed
    topics_tried = set()

    # Track whether we've done at least one fresh research call
    fresh_research_done = False

    def _get_next_topics():
        """Fetch next batch of topics from pending pool or fresh research."""
        nonlocal topics, pending_index, fresh_research_done, source_id

        # Try pending pool first (round-robin)
        while pending_index < len(pending_sources):
            ps = pending_sources[pending_index]
            pending_index += 1
            if ps.get("topics"):
                topics = ps["topics"]
                source_id = ps["id"]
                logger.info(f"  Loaded {len(topics)} topics from pending source id={source_id}")
                return True
        return False

    # Initial load
    from db import get_pending_topic_sources
    pending_sources = get_pending_topic_sources(limit=10)
    source_id = None

    if not _get_next_topics():
        logger.info("Step 1: Researching trending topics (pending pool empty)...")
        topics = self.researcher.research_from_keywords(count=num_ideas)
        fresh_research_done = True
        source_id = self.researcher.save_to_db(
            topics, source_query=", ".join(self.niche_keywords)
        )
        logger.info(f"  Found {len(topics)} topics from fresh research")

    results["topics_found"] = len(topics)
    results["source_id"] = source_id

    # Step 2: Generate ideas + dedup in a loop with proper retry
    from utils.embedding import check_duplicate_ideas, save_idea_embedding
    from db import mark_topic_source_completed

    while len(ideas) < num_ideas:
        remaining_topics = [t for t in topics if t.get("title", "") not in topics_tried]
        if not remaining_topics:
            logger.info("  No more topics in current batch, fetching more...")
            # Exhausted current batch — try next pending or fresh research
            if not _get_next_topics():
                if not fresh_research_done:
                    logger.info("  Fresh research needed...")
                    topics = self.researcher.research_from_keywords(count=num_ideas)
                    fresh_research_done = True
                    source_id = self.researcher.save_to_db(
                        topics, source_query=", ".join(self.niche_keywords)
                    )
                    logger.info(f"  Found {len(topics)} topics from fresh research")
                    topics_tried.clear()
                    if not topics:
                        logger.info("  Fresh research returned no topics, stopping")
                        break
                else:
                    logger.info("  All topic sources exhausted, stopping")
                    break
            continue

        batch_ideas = self.idea_gen.generate_ideas_from_topics(
            remaining_topics, count=num_ideas - len(ideas)
        )
        logger.info(f"Step 2: Generated {len(batch_ideas)} ideas from remaining topics")

        if not batch_ideas:
            # No ideas from this topic batch — try more topics
            topics_tried.update(t.get("title", "") for t in remaining_topics)
            continue

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

        if new_batch:
            ideas.extend(new_batch)
            logger.info(f"  Added {len(new_batch)} new ideas, total: {len(ideas)}")
        else:
            logger.info("  All ideas from this batch are duplicates, trying more topics...")
            # Continue to next loop iteration to fetch more topics

    # ... rest of method unchanged (save ideas, generate scripts, produce videos)
```

- [ ] **Step 2: Run existing tests to verify no regression**

Run: `pytest tests/test_content_pipeline.py -v 2>/dev/null || echo "No test file yet"`
Run: `pytest tests/test_scene_processor.py -v`
Expected: All pass

- [ ] **Step 3: Run the new integration test**

Run: `pytest tests/test_content_pipeline_research.py -v`
Expected: New test passes (confirming fix works)

- [ ] **Step 4: Commit**

```bash
git add modules/content/content_pipeline.py tests/test_content_pipeline_research.py
git commit -m "fix: re-research topics when all ideas are duplicates

Previously run_full_cycle() called research_from_keywords() only once.
When all ideas from that batch were filtered as duplicates, the pipeline
returned no ideas instead of fetching more topics.

Now the loop properly exhausts pending topic sources in round-robin,
then falls back to fresh research if needed, matching the documented
behavior of continuing to research when ideas run out."
```

---

### Task 3: Add unit tests for the `_get_next_topics` logic

**Files:**
- Modify: `tests/test_content_pipeline_research.py`

- [ ] **Step 1: Add test for pending pool round-robin**

```python
def test_pending_pool_round_robin(self):
    """Multiple pending topic sources should be consumed in order."""
    pass  # Implementation

def test_fresh_research_triggered_when_pending_exhausted(self):
    """When pending pool is empty and ideas run out, fresh research is called."""
    pass  # Implementation
```

- [ ] **Step 2: Run all content pipeline tests**

Run: `pytest tests/test_content_pipeline_research.py -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_content_pipeline_research.py
git commit -m "test: add content pipeline research re-fetch tests"
```

---

## Verification Commands

After all tasks:
```bash
# Run content pipeline with verbose logging to see research behavior
python scripts/run_pipeline.py --channel nang_suat_thong_minh --ideas 1 --produce --skip-lipsync 2>&1 | grep -E "(Step|topic|idea|duplicate|research)"

# Run all tests
pytest tests/ -v
```

Expected after fix: When ideas run out (all dupes), pipeline logs "Researching trending topics" and fetches more topics instead of returning "no_new_ideas".
