# Content Pipeline: Fix Pending Source Exhausted Without Fresh Research Fallback

**Date:** 2026-04-17
**Status:** Approved
**Type:** Bug fix

## Problem

When `run_full_cycle()` processes ideas in `pending_mode=True` and all pending topic sources are exhausted (all topics produced duplicate ideas), the pipeline breaks out of the loop and returns `status=no_new_ideas` without ever attempting fresh research.

**Log from 2026-04-17:**
```
All pending sources exhausted (all topics were duplicates)
WARNING No new ideas after dedup. All topics were duplicates of recent content.
Content cycle found no new ideas — falling back to existing script_ready ideas from DB
```

The bug is at `content_pipeline.py:360-362`. When pending source round-robin is exhausted, the code `break`s and returns `no_new_ideas`. Fresh research (via `research_from_keywords()`) is **never called** in `pending_mode`.

Compare with the non-pending path (lines 402-413): when all ideas are duplicates, it calls `research_from_keywords()` for fresh topics. This fallback is unreachable in `pending_mode` because line 399 `continue` → next iteration → `remaining` is empty → line 332 fires → exhausts `pending_sources` round-robin → line 362 `break`.

## Desired Behavior

When all pending topic sources are exhausted AND all ideas were duplicates:
1. Attempt fresh research via `research_from_keywords()` — exactly once
2. If fresh research returns topics with non-duplicate ideas → continue pipeline
3. If fresh research also returns only duplicates → raise `ContentPipelineExhaustedError`

This exception propagates to `run_pipeline.py` which already has fallback logic to use `script_ready` ideas.

## Design

### New Exception

**File:** `modules/pipeline/exceptions.py`

```python
class ContentPipelineExhaustedError(Exception):
    """Raised when all topic sources (pending + fresh research) are exhausted
    and no new non-duplicate ideas can be generated."""
    pass
```

### `_get_next_topics()` Helper Method

**File:** `modules/content/content_pipeline.py`
**Location:** Inside `ContentPipeline` class, alongside existing methods.

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

    # 1. Try round-robin pending sources (skip current_source_id)
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
    raise ContentPipelineExhaustedError(
        "All topic sources exhausted (pending + fresh research)"
    )
```

### Changes to `run_full_cycle()`

**Before (lines 331-362):**
```python
if not remaining:
    logger.info("  Current topic batch exhausted, trying next pending source...")
    if current_topics_source_id:
        mark_topic_source_completed(current_topics_source_id)
    while pending_index < len(pending_sources):
        ps = pending_sources[pending_index]
        pending_index += 1
        if ps.get("topics"):
            topics = ps["topics"]
            current_topics_source_id = ps["id"]
            source_id = ps["id"]
            break
        mark_topic_source_completed(ps["id"])
    else:
        logger.info("  All pending sources exhausted (all topics were duplicates)")
        break  # BUG: no fresh research fallback
```

**After:**
```python
if not remaining:
    logger.info("  Current topic batch exhausted, trying next topic source...")
    if current_topics_source_id:
        try:
            mark_topic_source_completed(current_topics_source_id)
        except Exception as e:
            logger.warning(f"  Could not mark source {current_topics_source_id} completed: {e}")

    if results.get("pending_mode"):
        # pending_mode: use helper to get next topics (round-robin pending, then fresh research)
        topics, source_id, pending_index, fresh_research_done = self._get_next_topics(
            pending_sources, pending_index, current_topics_source_id, fresh_research_done, num_ideas
        )
        topics_tried = set()
        results["pending_mode"] = False  # after fresh research, no longer pending_mode
        continue
    else:
        # non-pending: nothing left to try
        break
```

The non-pending branch at lines 402-413 (fresh research in non-pending mode) remains unchanged.

### Flow After Fix

```
while len(ideas) < num_ideas:
    remaining = [t for t in topics if t.get("title") not in topics_tried]

    if not remaining:
        if results.get("pending_mode"):
            → mark previous source completed
            → _get_next_topics() returns (new topics, source_id, ...) OR raises ContentPipelineExhaustedError
            → topics_tried cleared
            → pending_mode = False
            → continue
        else:
            → break (no more topics)

    generate ideas, dedup, add to results

    if new ideas found → continue
    if all dupes in pending_mode → continue → next iteration hits "not remaining" → _get_next_topics() called
    if all dupes in non-pending_mode → break (existing behavior)
```

## Files Changed

| File | Change |
|------|--------|
| `modules/pipeline/exceptions.py` | Add `ContentPipelineExhaustedError` |
| `modules/content/content_pipeline.py` | Add `_get_next_topics()` helper; simplify while-loop at lines 331-362 |

## Testing

1. **Unit test**: `_get_next_topics()` raises `ContentPipelineExhaustedError` when pending sources empty and `fresh_research_done=True`
2. **Unit test**: `_get_next_topics()` returns fresh research topics when pending sources exhausted and `fresh_research_done=False`
3. **Integration test**: All ideas from pending sources are duplicates → fresh research is triggered → non-duplicate ideas found → pipeline succeeds

## Verification

```bash
# Run all tests
pytest tests/ -v

# Run content pipeline with verbose logging
python scripts/run_pipeline.py --ideas 1 --produce 2>&1 | grep -E "(pending|source|research|duplicate|ContentPipelineExhausted)"
```

After fix: when pending sources exhausted and ideas are duplicates, pipeline logs "attempting fresh research" and continues instead of returning `no_new_ideas`.
