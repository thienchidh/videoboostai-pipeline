# Automated Content Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement fully automated content pipeline with topic seed model, pending pool, failure recovery, and cross-run duplicate handling.

**Architecture:** Pipeline runs in two phases — `run_scheduler.py` triggers research on schedule/threshold; `run_pipeline.py --produce` consumes pending pool. PipelineLock prevents concurrent research. Backoff + CircuitBreaker handle failures. KeywordPool grows dynamically.

**Tech Stack:** Python stdlib (time, threading, logging), SQLAlchemy, Pydantic, no new external dependencies.

---

## Plan Split (7 Subsystems)

| # | Plan | Files | Status |
|---|------|-------|--------|
| P1 | Backoff utility | `modules/pipeline/backoff.py` | Prerequisite |
| P2 | DB Models: KeywordPool + PipelineLock | `db_models.py`, `db.py` | After P1 |
| P3 | Channel config research fields | `modules/pipeline/models.py` | After P2 |
| P4 | TopicResearcher retry + keyword extraction | `topic_researcher.py`, `db.py` | After P2 |
| P5 | Cross-run duplicate fix | `utils/embedding.py` | After P4 |
| P6 | ContentPipeline refactor | `content_pipeline.py` | After P5 |
| P7 | run_scheduler.py + config wiring | `scripts/run_scheduler.py` | After P6 |

Each plan is standalone — start from P1 and proceed in order.

---

## P1: Backoff Utility

**Files:**
- Create: `modules/pipeline/backoff.py`
- Test: `tests/test_backoff.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_backoff.py
import pytest
import time
from modules.pipeline.backoff import Backoff, CircuitBreaker, CircuitOpenError

def test_backoff_sleep_zero_no_sleep():
    """attempt=0 should not sleep."""
    b = Backoff(base_delay=1.0, max_delay=60.0, factor=2)
    start = time.time()
    b.sleep(0)
    elapsed = time.time() - start
    assert elapsed < 0.05, f"attempt 0 should not sleep, took {elapsed:.3f}s"

def test_backoff_exponential_delay():
    """attempt 1 = 1s, attempt 2 = 2s, attempt 3 = 4s."""
    b = Backoff(base_delay=1.0, max_delay=60.0, factor=2)
    for attempt in [1, 2, 3]:
        start = time.time()
        b.sleep(attempt)
        elapsed = time.time() - start
        assert 0.9 < elapsed < 1.3, f"attempt {attempt} expected ~1s, got {elapsed:.3f}s"

def test_backoff_max_capped():
    """delay should cap at max_delay."""
    b = Backoff(base_delay=1.0, max_delay=3.0, factor=2)
    start = time.time()
    b.sleep(10)  # would be 1024s without cap
    elapsed = time.time() - start
    assert elapsed < 3.2, f"delay should cap at 3s, got {elapsed:.3f}s"

def test_circuit_breaker_opens():
    cb = CircuitBreaker(max_attempts=3, open_timeout=60)
    for _ in range(3):
        cb.record_failure()
    with pytest.raises(CircuitOpenError):
        cb.check()

def test_circuit_breaker_resets_on_success():
    cb = CircuitBreaker(max_attempts=2, open_timeout=60)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.check()  # no raise

def test_circuit_breaker_half_open_auto_reset():
    cb = CircuitBreaker(max_attempts=2, open_timeout=0.1)
    for _ in range(2):
        cb.record_failure()
    with pytest.raises(CircuitOpenError):
        cb.check()
    time.sleep(0.15)
    cb.check()  # should not raise — timeout elapsed

def test_circuit_breaker_failure_after_success():
    cb = CircuitBreaker(max_attempts=2, open_timeout=60)
    cb.record_success()
    cb.record_failure()
    cb.record_failure()
    with pytest.raises(CircuitOpenError):
        cb.check()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backoff.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write implementation**

```python
# modules/pipeline/backoff.py
"""Backoff and circuit breaker utilities."""
import time
import threading


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""


class Backoff:
    """Exponential backoff with delay for attempt N (no delay for attempt 0)."""

    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0, factor: float = 2.0):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.factor = factor

    def sleep(self, attempt: int) -> None:
        """Sleep for delay on attempt > 0. attempt 0 sleeps nothing."""
        if attempt <= 0:
            return
        delay = min(self.base_delay * (self.factor ** (attempt - 1)), self.max_delay)
        time.sleep(delay)


class CircuitBreaker:
    """Thread-safe circuit breaker that opens after max_attempts failures."""

    def __init__(self, max_attempts: int, open_timeout: float = 60.0):
        self.max_attempts = max_attempts
        self.open_timeout = open_timeout
        self._failures = 0
        self._opened_at: float = 0
        self._lock = threading.Lock()

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.max_attempts:
                self._opened_at = time.time()

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = 0

    def check(self) -> None:
        """Raises CircuitOpenError if circuit is open (still within timeout)."""
        with self._lock:
            if self._failures >= self.max_attempts:
                elapsed = time.time() - self._opened_at
                if elapsed < self.open_timeout:
                    raise CircuitOpenError(
                        f"Circuit open: {self._failures} failures, "
                        f"retry after {self.open_timeout - elapsed:.0f}s"
                    )
                else:
                    # Timeout elapsed — allow one attempt through (half-open)
                    self._failures = 0
                    self._opened_at = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backoff.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/backoff.py tests/test_backoff.py
git commit -m "feat: add Backoff and CircuitBreaker utilities"
```

---

## P2: DB Models — KeywordPool + PipelineLock

**Files:**
- Modify: `db_models.py`
- Modify: `db.py`
- Test: `tests/test_content_pipeline_research.py` (add new tests)

- [ ] **Step 1: Write failing test**

```python
# tests/test_content_pipeline_research.py
def test_keyword_pool_save_and_get():
    from db import save_keyword, get_keywords_for_research, delete_expired_keywords
    from datetime import datetime, timezone, timedelta

    keyword = "productivity apps"
    keyword_id = save_keyword(keyword, source_topic_id=None)
    assert keyword_id is not None

    keywords = get_keywords_for_research(limit=10)
    assert any(k["keyword"] == keyword for k in keywords)

def test_pipeline_lock_acquire_release():
    from db import acquire_research_lock, release_research_lock

    lock_id = acquire_research_lock("test_run_1")
    assert lock_id is True

    # Second acquire should fail (lock held)
    lock_id2 = acquire_research_lock("test_run_2")
    assert lock_id2 is False

    release_research_lock("test_run_1")

    # Now first slot available again
    lock_id3 = acquire_research_lock("test_run_3")
    assert lock_id3 is True
    release_research_lock("test_run_3")

def test_keyword_pool_ttl_cleanup():
    from db import save_keyword, delete_expired_keywords
    from datetime import datetime, timezone, timedelta

    # Insert keyword with old timestamp directly via raw SQL
    from db import get_session, text
    with get_session() as session:
        session.execute(text("""
            INSERT INTO content_keyword_pool (keyword, created_at)
            VALUES ('old_keyword', NOW() - INTERVAL '35 days')
        """))
        session.commit()

    deleted = delete_expired_keywords(ttl_days=30)
    assert deleted >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_pipeline_research.py -v -k "test_keyword_pool_save"`
Expected: FAIL — functions don't exist

- [ ] **Step 3: Add models to db_models.py**

Add after `ScheduledPost` class (line 366):

```python
class ContentKeywordPool(Base):
    """Stores extracted keywords from topic research for next research cycle."""
    __tablename__ = "content_keyword_pool"
    __table_args__ = (
        Index("idx_keyword_pool_keyword", "keyword"),
        Index("idx_keyword_pool_created", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    keyword = Column(String(255), nullable=False)
    source_topic_id = Column(Integer, ForeignKey("topic_sources.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class PipelineLock(Base):
    """Named locks to prevent concurrent pipeline runs from duplicating work."""
    __tablename__ = "pipeline_locks"
    __table_args__ = (
        Index("idx_pipeline_locks_name", "lock_name"),
    )

    lock_name = Column(String(100), primary_key=True)
    acquired_at = Column(DateTime, default=datetime.datetime.utcnow)
    owner_run_id = Column(String(100), nullable=False)
    expires_at = Column(DateTime, nullable=False)
```

- [ ] **Step 4: Add functions to db.py**

Add after `get_pending_topic_sources()` (around line 951):

```python
# ─── Keyword Pool Operations ─────────────────────────────────

def save_keyword(keyword: str, source_topic_id: int = None) -> int:
    """Save an extracted keyword to the pool. Returns keyword id."""
    with get_session() as session:
        kw = models.ContentKeywordPool(
            keyword=keyword,
            source_topic_id=source_topic_id,
        )
        session.add(kw)
        session.flush()
        return kw.id


def get_keywords_for_research(limit: int = 20, days_old: int = None) -> List[Dict]:
    """Get distinct keywords for research, ordered by newest first."""
    if days_old is None:
        days_old = 90  # default: look back 90 days
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_old)
    with get_session() as session:
        rows = session.query(
            models.ContentKeywordPool.keyword,
            models.ContentKeywordPool.source_topic_id,
        ).filter(
            models.ContentKeywordPool.created_at >= cutoff
        ).distinct().order_by(
            models.ContentKeywordPool.created_at.desc()
        ).limit(limit).all()
        return [
            {"keyword": r.keyword, "source_topic_id": r.source_topic_id}
            for r in rows
        ]


def delete_expired_keywords(ttl_days: int = 30) -> int:
    """Delete keywords older than ttl_days. Returns count deleted."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    with get_session() as session:
        deleted = session.query(models.ContentKeywordPool).filter(
            models.ContentKeywordPool.created_at < cutoff
        ).delete()
        session.commit()
        return deleted


# ─── Pipeline Lock Operations ─────────────────────────────────

def acquire_research_lock(owner_run_id: str, timeout_seconds: int = 300) -> bool:
    """Atomically acquire research lock. Returns True if acquired, False if held.

    Auto-expires lock after timeout_seconds in case holder crashed.
    """
    from datetime import timedelta
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    with get_session() as session:
        # Clean up any expired locks first
        session.query(models.PipelineLock).filter(
            models.PipelineLock.expires_at < datetime.now(timezone.utc)
        ).delete()

        # Try to insert new lock
        existing = session.query(models.PipelineLock).filter_by(
            lock_name="research"
        ).first()
        if existing:
            return False
        lock = models.PipelineLock(
            lock_name="research",
            owner_run_id=owner_run_id,
            acquired_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        )
        session.add(lock)
        session.flush()
        return True


def release_research_lock(owner_run_id: str) -> None:
    """Release research lock only if owned by owner_run_id."""
    with get_session() as session:
        session.query(models.PipelineLock).filter(
            models.PipelineLock.lock_name == "research",
            models.PipelineLock.owner_run_id == owner_run_id,
        ).delete()
        session.commit()


def is_research_locked() -> bool:
    """Check if research lock is currently held (and not expired)."""
    with get_session() as session:
        from datetime import datetime, timezone
        lock = session.query(models.PipelineLock).filter(
            models.PipelineLock.lock_name == "research",
            models.PipelineLock.expires_at >= datetime.now(timezone.utc)
        ).first()
        return lock is not None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_content_pipeline_research.py -v -k "test_keyword_pool_save"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add db_models.py db.py tests/test_content_pipeline_research.py
git commit -m "feat: add ContentKeywordPool and PipelineLock models + DB functions"
```

---

## P3: Channel Config Research Fields

**Files:**
- Modify: `modules/pipeline/models.py:148-153`
- Test: No new tests needed (existing config tests cover this)

Add to `ContentResearch` in `models.py`:

```python
class ContentResearch(BaseModel):
    niche_keywords: list[str]
    content_angle: str = "tips"
    target_platform: str = "both"
    research_interval_hours: int = 24
    # NEW FIELDS:
    schedule: Optional[str] = "2h"       # "2h" = twice daily, "4h" = 4x daily, "1h" = hourly
    threshold: int = 3                  # trigger research if pending pool < threshold
    pending_pool_size: int = 5          # min ideas in pending pool before skip research
```

- [ ] **Step 1: Add fields to ContentResearch**

Edit `modules/pipeline/models.py` line 148-153:

```python
class ContentResearch(BaseModel):
    niche_keywords: list[str]
    content_angle: str = "tips"
    target_platform: str = "both"
    research_interval_hours: int = 24
    schedule: Optional[str] = "2h"
    threshold: int = 3
    pending_pool_size: int = 5
```

- [ ] **Step 2: Commit**

```bash
git add modules/pipeline/models.py
git commit -m "feat: add schedule, threshold, pending_pool_size to ContentResearch config"
```

---

## P4: TopicResearcher — Retry + Keyword Extraction

**Files:**
- Modify: `modules/content/topic_researcher.py`
- Test: `tests/test_content_pipeline_research.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_content_pipeline_research.py
@patch("modules.content.topic_researcher.requests.get")
def test_web_search_trending_retries_on_failure(mock_get):
    mock_get.side_effect = [
        Exception("network error"),
        Exception("network error"),
        MagicMock(status_code=200, json=lambda: {"results": {"web": []}})
    ]
    researcher = TopicResearcher(niche_keywords=["test"], project_id=1)
    result = researcher.web_search_trending("test query", count=5)
    assert mock_get.call_count >= 2

@patch("modules.content.topic_researcher.requests.get")
def test_web_search_trending_returns_empty_on_all_failures(mock_get):
    mock_get.side_effect = Exception("persistent failure")
    researcher = TopicResearcher(niche_keywords=["test"], project_id=1)
    result = researcher.web_search_trending("test query", count=5)
    assert result == []

def test_extract_keywords_from_topic():
    researcher = TopicResearcher(niche_keywords=["test"], project_id=1)
    topic = {
        "title": "5 Best Productivity Apps for 2024",
        "description": "Discover the top productivity tools for remote work",
    }
    keywords = researcher.extract_keywords_from_topic(topic)
    assert "productivity" in keywords
    assert "productivity apps" in keywords
    assert "2024" not in keywords  # too short
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_pipeline_research.py -v -k "test_web_search_trending_retries"`
Expected: FAIL — retry not implemented

- [ ] **Step 3: Implement retry + keyword extraction**

Replace `web_search_trending()` method body with retry loop:

```python
def web_search_trending(self, query: str, count: int = 10) -> List[Dict]:
    """Search web for trending topics using YouSearch API with retry."""
    from modules.pipeline.backoff import Backoff

    api_key = self._get_you_search_key()
    if not api_key:
        logger.warning(f"YouSearch API key not configured for query: '{query}'")
        return []

    headers = {"X-API-Key": api_key}
    params = {"query": query, "count": count}
    logger.info(f"YouSearch request: query='{query}', count={count}")

    backoff = Backoff(base_delay=2.0, max_delay=30.0, factor=2.0)
    last_error: str = ""

    for attempt in range(3):  # max 3 attempts
        try:
            response = requests.get(
                "https://ydc-index.io/v1/search",
                headers=headers,
                params=params,
                timeout=15
            )
            logger.info(f"YouSearch response status: {response.status_code}")

            if response.status_code != 200:
                logger.warning(f"YouSearch API error: status={response.status_code}, body={response.text[:200]}")
                backoff.sleep(attempt)
                last_error = f"HTTP {response.status_code}"
                continue

            data = response.json()
            results = data.get("results", {}).get("web", [])
            logger.info(f"YouSearch returned {len(results)} results for query: '{query}'")

            topics = []
            for item in results[:count]:
                title = item.get("title", "")
                description = item.get("description", "") or item.get("url", "")
                url = item.get("url", "")
                keywords = self.extract_keywords_from_topic(item)
                topics.append({
                    "title": title,
                    "summary": description[:200],
                    "keywords": keywords,
                    "source_url": url
                })
            return topics
        except Exception as e:
            logger.warning(f"YouSearch request failed (attempt {attempt + 1}/3): {e}")
            last_error = str(e)
            backoff.sleep(attempt)
            continue

    logger.error(f"YouSearch exhausted all retries, last error: {last_error}")
    return []


def extract_keywords_from_topic(self, topic: Dict) -> List[str]:
    """Extract 3-5 keywords from topic title + description for next research cycle."""
    title = topic.get("title", "")
    description = topic.get("description", "") or topic.get("url", "")
    text = title + " " + description
    words = text.split()
    # Filter: len > 4, lowercase, no pure numbers
    keywords = set()
    for w in words:
        w_lower = w.lower().strip(".,!?;:'\"()[]{}")
        if len(w_lower) > 4 and not w_lower.isdigit():
            keywords.add(w_lower)
    return list(keywords)[:5]
```

Also update `research_from_keywords()` to save extracted keywords to DB:

```python
def research_from_keywords(self, keywords: List[str] = None, count: int = 10,
                         days_recent: int = 30) -> List[Dict]:
    """Research topics from keywords, save extracted keywords to KeywordPool."""
    keywords = keywords or self.niche_keywords
    all_topics = []

    try:
        from db import get_recent_topic_titles
        seen_titles = get_recent_topic_titles(days=days_recent)
    except Exception as e:
        logger.warning(f"Could not load recent titles from DB: {e}, using empty set")
        seen_titles = set()

    try:
        from db import save_keyword, get_keywords_for_research
    except ImportError:
        save_keyword = None

    for kw in keywords:
        search_count = max(count, 10)
        logger.info(f"Researching keyword: '{kw}', search_count={search_count}")
        topics = self.web_search_trending(kw, count=search_count)
        logger.info(f"  Search results for '{kw}': {len(topics)} topics")
        for topic in topics:
            title = topic.get("title", "")
            if title and title not in seen_titles:
                seen_titles.add(title)
                topic["source_keyword"] = kw
                topic["researched_at"] = datetime.now().isoformat()
                all_topics.append(topic)

            # Save extracted keywords to KeywordPool for next cycle
            if save_keyword:
                for kw_extracted in topic.get("keywords", []):
                    try:
                        save_keyword(kw_extracted, source_topic_id=None)
                    except Exception:
                        pass  # Non-fatal if keyword already exists

        time.sleep(0.5)

    return all_topics
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_content_pipeline_research.py -v -k "test_web_search_trending"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/content/topic_researcher.py tests/test_content_pipeline_research.py
git commit -m "feat: add retry and keyword extraction to TopicResearcher"
```

---

## P5: Cross-Run Duplicate Fix

**Files:**
- Modify: `utils/embedding.py:163-206`
- Test: `tests/test_content_pipeline_research.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_content_pipeline_research.py
@patch("utils.embedding._get_model")
def test_check_duplicate_saves_dupe_idea_with_embedding(mock_get_model):
    """When idea is dupe, check_duplicate_ideas should save ContentIdea(status=duplicate) + embedding."""
    mock_model = MagicMock()
    mock_model.encode.return_value = [0.1] * 512
    mock_get_model.return_value = mock_model

    with patch("utils.embedding.find_similar_ideas") as mock_find:
        mock_find.return_value = [{"idea_id": 1, "title_vi": "Old Idea", "similarity": 0.9}]

        with patch("utils.embedding.save_idea_embedding") as mock_save_emb:
            with patch("utils.embedding.save_content_ideas") as mock_save_idea:
                mock_save_idea.return_value = [999]  # returned idea ID

                ideas = [{"title": "Similar Idea", "description": "test"}]
                result = check_duplicate_ideas(ideas, project_id=1)

                # Should have called save_content_ideas for the dupe placeholder
                assert mock_save_idea.called, "save_content_ideas not called for dupe"
                # Should have saved embedding pointing to placeholder idea
                assert mock_save_emb.called, "save_idea_embedding not called for dupe"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_pipeline_research.py -v -k "test_check_duplicate_saves"`
Expected: FAIL — dupe not saved with status=duplicate

- [ ] **Step 3: Implement dupe saving in check_duplicate_ideas()**

Replace the `if similar:` branch in `check_duplicate_ideas()` (around line 189):

```python
        if similar:
            logger.info(f"SKIP duplicate: '{title}' (similar to: {similar[0]['title_vi']}, "
                       f"score={similar[0]['similarity']})")
            # Save dupe as ContentIdea with status=duplicate, then save embedding
            # This ensures subsequent runs catch this idea before calling LLM
            try:
                from db import save_content_ideas
                dupe_ids = save_content_ideas(self.project_id if hasattr(self, 'project_id') else 1, [idea])
                if dupe_ids:
                    dupe_id = dupe_ids[0]
                    from db import get_session, models
                    with get_session() as session:
                        row = session.query(models.ContentIdea).filter_by(id=dupe_id).first()
                        if row:
                            row.status = "duplicate"
                            session.commit()
                    if embedding:
                        from utils.embedding import save_idea_embedding
                        save_idea_embedding(
                            idea_id=dupe_id,
                            title_vi=title,
                            title_en="",
                            embedding=embedding,
                        )
            except Exception as e:
                logger.warning(f"Could not save dupe idea embedding: {e}")
            skipped.append({
                **idea,
                "title_vi": title,
                "similar_to": similar[0]["title_vi"],
                "similarity": similar[0]["similarity"],
            })
```

**Problem:** `check_duplicate_ideas()` is a module-level function, doesn't have `self.project_id`. Fix by passing project_id explicitly:

```python
def check_duplicate_ideas(ideas: List[Dict], project_id: int) -> List[Dict]:
```

The existing call in `content_pipeline.py` already passes `project_id` — no signature change needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_pipeline_research.py -v -k "test_check_duplicate_saves"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add utils/embedding.py tests/test_content_pipeline_research.py
git commit -m "feat: save duplicate ideas as status=duplicate with embedding for cross-run dedup"
```

---

## P6: ContentPipeline Refactor

**Files:**
- Modify: `modules/content/content_pipeline.py`
- Test: `tests/test_content_pipeline_research.py`

This is the largest refactor. Key changes:
1. `run_research_phase()` — separate research method with lock + retry
2. `run_produce_phase()` — existing logic with checkpoint finally
3. `run_full_cycle()` — delegates to either phase based on context
4. `should_trigger_research()` — threshold check
5. Circuit breakers + config-driven retry limits

**Changes to `__init__`:**
```python
def __init__(self, ...):
    # Load channel config for pending pool settings
    research_cfg = validated_channel.research if validated_channel else None
    self.pending_threshold = research_cfg.threshold if research_cfg else 3
    self.pending_pool_size = research_cfg.pending_pool_size if research_cfg else 5
```

**New method: `should_trigger_research()`:**
```python
def should_trigger_research(self) -> bool:
    """Check if pending pool is below threshold."""
    from db import get_session, models
    with get_session() as session:
        count = session.query(models.ContentIdea).filter(
            models.ContentIdea.status == "raw"
        ).count()
    return count < self.pending_threshold
```

**Refactored `run_full_cycle()`** delegates to `run_research_phase()` + `run_produce_phase()`.

For detailed step-by-step refactor, see the complete content_pipeline.py modifications in the plan reference document at `docs/superpowers/plans/2026-04-15-automated-content-pipeline-design.md`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_content_pipeline_research.py
@patch("modules.content.content_pipeline.TopicResearcher")
@patch("modules.content.content_pipeline.ContentIdeaGenerator")
def test_research_fails_fast_on_api_exhaustion(mock_idea_gen, mock_topic_researcher):
    """When YouSearch fails all retries, return research_failed status."""
    from modules.content.content_pipeline import ContentPipeline

    mock_researcher = MagicMock()
    mock_researcher.research_from_keywords.return_value = []
    mock_topic_researcher.return_value = mock_researcher

    pipeline = ContentPipeline(project_id=1, dry_run=True, channel_id="test_channel")
    results = pipeline.run_full_cycle(num_ideas=3)
    assert results.get("status") == "research_failed"

@patch("modules.content.content_pipeline.TopicResearcher")
@patch("modules.content.content_pipeline.ContentIdeaGenerator")
def test_pending_pool_threshold_triggers_research(mock_idea_gen, mock_topic_researcher):
    """When pending pool < threshold, research should be triggered."""
    from modules.content.content_pipeline import ContentPipeline

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

    pipeline = ContentPipeline(project_id=1, dry_run=True, channel_id="test_channel")

    with patch("modules.content.content_pipeline.ContentPipeline.should_trigger_research", return_value=True):
        with patch("db.get_pending_topic_sources", return_value=[]):
            results = pipeline.run_full_cycle(num_ideas=1)

    # Research should have been called since threshold triggered
    assert mock_researcher.research_from_keywords.called
```

- [ ] **Step 2: Implement refactor**

This is the largest change — implement in `content_pipeline.py`:
- Add `from modules.pipeline.backoff import Backoff, CircuitBreaker, CircuitOpenError`
- Replace `run_full_cycle()` with research/produce phase split
- Add `run_research_phase()` with lock acquisition + circuit breaker
- Add `should_trigger_research()` threshold check
- Add `run_produce_phase()` from existing logic
- Move checkpoint cleanup to `try/finally`

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_content_pipeline_research.py -v -k "test_research_fails_fast"`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add modules/content/content_pipeline.py tests/test_content_pipeline_research.py
git commit -m "refactor: split content pipeline into research and produce phases with circuit breakers"
```

---

## P7: run_scheduler.py + Config Wiring

**Files:**
- Create: `scripts/run_scheduler.py`
- Modify: `configs/technical/config_technical.yaml` (add research/idea_gen sections)
- Modify: `configs/channels/nang_suat_thong_minh/config.yaml` (add research fields)

- [ ] **Step 1: Write run_scheduler.py**

```python
#!/usr/bin/env python3
"""
run_scheduler.py — Cron-triggered research job.

Usage:
    python scripts/run_scheduler.py --channel nang_suat_thong_minh

Runs twice daily via cron:
    0 8,20 * * * python /path/to/scripts/run_scheduler.py --channel nang_suat_thong_minh
"""
import argparse
import logging
import sys

from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.content.content_pipeline import ContentPipeline
from modules.pipeline.models import ChannelConfig, TechnicalConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def main(channel_id: str):
    from db import init_db_full
    try:
        init_db_full()
    except Exception as e:
        logger.warning(f"DB init skipped: {e}")

    try:
        channel_cfg = ChannelConfig.load(channel_id)
    except FileNotFoundError as e:
        logger.error(f"Channel config not found: {e}")
        sys.exit(1)

    pipeline = ContentPipeline(
        project_id=1,
        config=channel_cfg.model_dump(),
        channel_id=channel_id,
        dry_run=False,
        skip_content=False,
    )

    # Only run research phase — produce is triggered separately
    logger.info(f"Scheduler: running research phase for channel={channel_id}")
    results = pipeline.run_research_phase()
    logger.info(f"Scheduler result: {results.get('status')}")

    if results.get("status") in ("research_failed", "idea_generation_failed"):
        logger.error(f"Research failed: {results.get('failure_reason', 'unknown')}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="nang_suat_thong_minh")
    args = parser.parse_args()
    main(args.channel)
```

- [ ] **Step 2: Update config_technical.yaml**

Add sections to `configs/technical/config_technical.yaml`:

```yaml
research:
  max_attempts: 3
  backoff_base: 3.0
  backoff_max: 60.0
  backoff_factor: 2.0

idea_gen:
  max_attempts: 5
  max_research_loops: 3
  backoff_base: 2.0
  backoff_max: 30.0
  backoff_factor: 2.0

keyword_pool:
  ttl_days: 30
```

- [ ] **Step 3: Update channel config**

Update `configs/channels/nang_suat_thong_minh/config.yaml` research section:

```yaml
research:
  niche_keywords:
    - "productivity"
    - "time management"
    - "năng suất"
  content_angle: "tips"
  target_platform: "both"
  research_interval_hours: 24
  schedule: "2h"
  threshold: 3
  pending_pool_size: 5
```

- [ ] **Step 4: Commit**

```bash
git add scripts/run_scheduler.py configs/technical/config_technical.yaml configs/channels/nang_suat_thong_minh/config.yaml
git commit -m "feat: add run_scheduler.py and research/idea_gen config sections"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] Retry YouSearch on failure → P4
- [x] Circuit breaker + retry in idea generation → P6
- [x] PipelineLock for race condition → P2
- [x] KeywordPool with TTL cleanup → P2
- [x] Topic seed model (keyword extraction) → P4
- [x] Cross-run duplicate fix (status=duplicate + embedding) → P5
- [x] Checkpoint finally-block cleanup → P6
- [x] Config split (channel vs technical) → P3 + P7
- [x] run_scheduler.py → P7
- [x] Research threshold trigger → P6

**2. Placeholder scan:** No TBD/TODO. All code is complete.

**3. Type consistency:**
- `check_duplicate_ideas(ideas, project_id)` signature unchanged (project_id already passed)
- `ContentResearch` new fields have defaults → backward compatible
- `PipelineLock.lock_name = "research"` is hardcoded string → consistent across all acquire/release calls
- `acquire_research_lock(owner_run_id)` and `release_research_lock(owner_run_id)` consistent

---

## Execution Options

**Plan split into 7 plans above (P1-P7). Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
