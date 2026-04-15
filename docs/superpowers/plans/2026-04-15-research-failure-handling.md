# Content Pipeline Research Failure Handling - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add retry logic, circuit breakers, and alerting when the content research phase produces no results. Handle API failures gracefully instead of silent exits.

**Architecture:** Wrap the research and idea generation phases with retry/backoff logic, add a circuit breaker to prevent infinite loops, and emit structured status that caller can act on. Checkpoint cleanup moved to a finally block.

**Tech Stack:** Python stdlib (time, logging), no new dependencies.

---

## File Structure

```
modules/content/content_pipeline.py   # Modify: add retry + circuit breaker + checkpoint cleanup
modules/content/topic_researcher.py  # Modify: add retry to web_search_trending()
modules/content/backoff.py           # Create: shared backoff utility
tests/test_content_pipeline_research.py  # Modify: add tests for failure modes
tests/test_backoff.py               # Create: backoff utility tests
```

---

## Task 1: Create backoff utility

**Files:**
- Create: `modules/pipeline/backoff.py`
- Test: `tests/test_backoff.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_backoff.py
import pytest
from modules.pipeline.backoff import Backoff, CircuitBreaker, CircuitOpenError

def test_backoff_sleep_times():
    """Exponential backoff sleeps for expected duration."""
    import time
    b = Backoff(base_delay=0.1, max_delay=1.0, factor=2)
    start = time.time()
    b.sleep(0)  # first attempt: no delay
    b.sleep(1)  # second: 0.1s
    b.sleep(2)  # third: 0.2s
    elapsed = time.time() - start
    assert 0.28 < elapsed < 0.40, f"Expected ~0.3s, got {elapsed:.2f}s"

def test_backoff_max_delay_capped():
    import time
    b = Backoff(base_delay=0.1, max_delay=0.3, factor=2)
    start = time.time()
    b.sleep(5)  # would be 3.2s without cap
    elapsed = time.time() - start
    assert elapsed < 0.35, f"Delay should be capped at 0.3s, got {elapsed:.2f}s"

def test_circuit_breaker_opens_after_max_attempts():
    cb = CircuitBreaker(max_attempts=3, open_timeout=60)
    for i in range(3):
        cb.record_failure()
    with pytest.raises(CircuitOpenError):
        cb.check()

def test_circuit_breaker_resets_on_success():
    cb = CircuitBreaker(max_attempts=2, open_timeout=60)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()  # resets counter
    cb.check()  # should not raise

def test_circuit_breaker_stays_open():
    cb = CircuitBreaker(max_attempts=2, open_timeout=0.1)
    for _ in range(2):
        cb.record_failure()
    with pytest.raises(CircuitOpenError):
        cb.check()
    import time
    time.sleep(0.15)
    cb.check()  # should not raise after timeout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backoff.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write minimal implementation**

```python
# modules/pipeline/backoff.py
"""Backoff and circuit breaker utilities."""
import time
import threading


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""


class Backoff:
    """Exponential backoff with jitter-free delays."""

    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0, factor: float = 2.0):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.factor = factor
        self._attempt = 0

    def sleep(self, attempt: int) -> None:
        """Sleep for the backoff delay corresponding to attempt number."""
        delay = min(self.base_delay * (self.factor ** attempt), self.max_delay)
        if attempt > 0:  # no sleep before first attempt
            time.sleep(delay)
        self._attempt = attempt

    @property
    def attempt(self) -> int:
        return self._attempt


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
        """Raises CircuitOpenError if circuit is open."""
        with self._lock:
            if self._failures >= self.max_attempts:
                if time.time() - self._opened_at < self.open_timeout:
                    raise CircuitOpenError(
                        f"Circuit open: {self._failures} failures, retry after {self.open_timeout:.0f}s"
                    )
                else:
                    # Timeout elapsed — allow one attempt through
                    self._failures = 0
                    self._opened_at = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backoff.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/backoff.py tests/test_backoff.py
git commit -m "feat: add backoff and circuit breaker utilities"
```

---

## Task 2: Add retry logic to TopicResearcher.web_search_trending()

**Files:**
- Modify: `modules/content/topic_researcher.py:31-77`
- Test: `tests/test_content_pipeline_research.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_content_pipeline_research.py — add these tests
import pytest
from unittest.mock import patch, MagicMock
from modules.content.topic_researcher import TopicResearcher

@patch("modules.content.topic_researcher.requests.get")
def test_web_search_trending_retries_on_failure(mock_get):
    """web_search_trending retries up to 3 times on API failure."""
    mock_get.side_effect = [Exception("network error"), Exception("network error"), MagicMock(status_code=200, json=lambda: {"results": {"web": []}})]
    researcher = TopicResearcher(niche_keywords=["test"], project_id=1)
    # The function should not raise — it catches exceptions internally
    result = researcher.web_search_trending("test query", count=5)
    assert mock_get.call_count >= 2  # at least 2 attempts made

@patch("modules.content.topic_researcher.requests.get")
def test_web_search_trending_returns_empty_on_all_failures(mock_get):
    """web_search_trending returns empty list when all retries exhausted."""
    mock_get.side_effect = Exception("persistent failure")
    researcher = TopicResearcher(niche_keywords=["test"], project_id=1)
    result = researcher.web_search_trending("test query", count=5)
    assert result == []

def test_research_from_keywords_empty_niche_keywords():
    """research_from_keywords raises if niche_keywords empty."""
    researcher = TopicResearcher(niche_keywords=[], project_id=1)
    with pytest.raises(ValueError, match="niche_keywords is required"):
        researcher.research_from_keywords()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_pipeline_research.py -v -k "test_web_search_trending_retries"`
Expected: FAIL — retry logic not implemented

- [ ] **Step 3: Implement retry in web_search_trending()**

Replace `web_search_trending()` body with:

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
                words = (title + " " + description).split()
                keywords = list(set(w.lower() for w in words if len(w) > 4))[:5]
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content_pipeline_research.py -v -k "test_web_search_trending"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/content/topic_researcher.py tests/test_content_pipeline_research.py
git commit -m "feat: add retry logic to TopicResearcher.web_search_trending()"
```

---

## Task 3: Add circuit breaker + retry to ContentPipeline.run_full_cycle()

**Files:**
- Modify: `modules/content/content_pipeline.py:104-316`
- Test: `tests/test_content_pipeline_research.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_content_pipeline_research.py
@patch("modules.content.content_pipeline.TopicResearcher")
@patch("modules.content.content_pipeline.ContentIdeaGenerator")
def test_run_full_cycle_alerts_on_no_topics(mock_idea_gen, mock_topic_researcher):
    """When research returns empty, pipeline should return status='research_failed' not silently return."""
    from modules.content.content_pipeline import ContentPipeline

    mock_researcher = MagicMock()
    mock_researcher.research_from_keywords.return_value = []  # empty research
    mock_topic_researcher.return_value = mock_researcher

    mock_ig = MagicMock()
    mock_ig.generate_ideas_from_topics.return_value = []
    mock_idea_gen.return_value = mock_ig

    pipeline = ContentPipeline(
        project_id=1,
        dry_run=True,
        channel_id="test_channel",
    )
    results = pipeline.run_full_cycle(num_ideas=3)

    # Should have a distinct status, not just empty produced list
    assert results.get("status") in ("research_failed", "no_new_ideas", "no_topics")
    assert results.get("topics_found", 0) == 0

@patch("modules.content.content_pipeline.TopicResearcher")
@patch("modules.content.content_pipeline.ContentIdeaGenerator")
def test_run_full_cycle_circuit breaker_prevents_infinite_loop(mock_idea_gen, mock_topic_researcher):
    """When idea_gen keeps returning dupes, circuit breaker should stop after max retries."""
    from modules.content.content_pipeline import ContentPipeline

    mock_researcher = MagicMock()
    mock_researcher.research_from_keywords.return_value = [
        {"title": f"Topic {i}", "summary": "desc", "keywords": [], "source_url": ""}
        for i in range(5)
    ]
    mock_topic_researcher.return_value = mock_researcher

    mock_ig = MagicMock()
    # All ideas are dupes
    mock_ig.generate_ideas_from_topics.return_value = []
    mock_idea_gen.return_value = mock_ig

    pipeline = ContentPipeline(
        project_id=1,
        dry_run=True,
        channel_id="test_channel",
    )
    # Should not loop forever — with circuit breaker should stop after max idea_gen calls
    results = pipeline.run_full_cycle(num_ideas=3)
    assert mock_researcher.research_from_keywords.call_count <= 3  # circuit breaker limits retries
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content_pipeline_research.py -v -k "test_run_full_cycle_alerts_on_no_topics"`
Expected: FAIL — no status='research_failed'

- [ ] **Step 3: Implement circuit breaker + improved status handling**

Replace the `run_full_cycle()` method body (lines 104-316) with retry-wrapped logic. Key changes:

**a) Add import at top of file:**
```python
from modules.pipeline.backoff import Backoff, CircuitBreaker, CircuitOpenError
```

**b) Replace research section (lines 137-158):**
```python
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

    # Retry research with circuit breaker
    research_cb = CircuitBreaker(max_attempts=3, open_timeout=120)
    research_backoff = Backoff(base_delay=3.0, max_delay=60.0, factor=2.0)

    research_topics = []
    research_attempt = 0

    while research_attempt < 3:
        try:
            research_cb.check()  # raises if circuit open
        except CircuitOpenError as e:
            logger.error(f"Circuit breaker open: {e}")
            results["status"] = "research_failed"
            results["failure_reason"] = "circuit_breaker_open"
            return results

        topics = self.researcher.research_from_keywords(count=num_ideas)
        research_attempt += 1

        if topics:
            logger.info(f"  Found {len(topics)} topics (attempt {research_attempt})")
            research_topics = topics
            research_cb.record_success()
            break
        else:
            logger.warning(f"  Research returned empty (attempt {research_attempt}/3)")
            research_cb.record_failure()
            if research_attempt < 3:
                research_backoff.sleep(research_attempt)
            continue

    if not research_topics:
        logger.error("Research exhausted all attempts, no topics found")
        results["status"] = "research_failed"
        results["failure_reason"] = "no_topics_from_api"
        results["topics_found"] = 0
        return results

    topics = research_topics
    source_id = self.researcher.save_to_db(topics, source_query=", ".join(self.niche_keywords))
    results["source_id"] = source_id
    results["pending_mode"] = False
    results["topics_found"] = len(topics)
```

**c) Add circuit breaker around idea_gen call:**
In the while loop (line 166), wrap the `generate_ideas_from_topics()` call:

```python
while len(ideas) < num_ideas:
    remaining_topics = [t for t in topics if t.get("title", "") not in topics_tried]
    if not remaining_topics:
        logger.info("  No more topics to try from current batch")
        break

    idea_gen_cb = CircuitBreaker(max_attempts=5, open_timeout=180)
    idea_gen_backoff = Backoff(base_delay=2.0, max_delay=30.0, factor=2.0)

    idea_attempt = 0
    batch_ideas = []

    while idea_attempt < 5:
        try:
            idea_gen_cb.check()
        except CircuitOpenError as e:
            logger.error(f"Circuit breaker open for idea_gen: {e}")
            results["status"] = "idea_generation_failed"
            results["failure_reason"] = "circuit_breaker_open"
            return results

        batch_ideas = self.idea_gen.generate_ideas_from_topics(remaining_topics, count=num_ideas - len(ideas))
        idea_attempt += 1

        if batch_ideas:
            idea_gen_cb.record_success()
            logger.info(f"Step 2: Generated {len(batch_ideas)} ideas (attempt {idea_attempt})")
            break
        else:
            logger.warning(f"  Idea generation returned empty (attempt {idea_attempt}/5)")
            idea_gen_cb.record_failure()
            if idea_attempt < 5:
                idea_gen_backoff.sleep(idea_attempt)
            continue

    if not batch_ideas:
        logger.error("Idea generation exhausted all attempts")
        results["status"] = "idea_generation_failed"
        results["failure_reason"] = "no_ideas_from_llm"
        break
```

**d) Move checkpoint cleanup to finally block** (replace lines 295-298):
```python
# Delete checkpoint on successful completion
try:
    if checkpoint_path.exists():
        checkpoint_path.unlink()
        logger.info("  Checkpoint deleted on successful completion")
except Exception as e:
    logger.warning(f"Could not delete checkpoint: {e}")
```

Add a try/finally around the main processing loop to ensure checkpoint is cleaned even on failure:
```python
checkpoint_cleaned = False
try:
    for i, idea_id in enumerate(idea_ids):
        # ... existing processing loop ...
finally:
    # Always clean up checkpoint on exit
    try:
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            checkpoint_cleaned = True
            logger.info("  Checkpoint cleaned up")
    except Exception as e:
        logger.warning(f"Could not delete checkpoint: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_content_pipeline_research.py -v -k "test_run_full_cycle_alerts"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/content/content_pipeline.py tests/test_content_pipeline_research.py
git commit -m "feat: add retry, circuit breaker, and checkpoint cleanup to content pipeline"
```

---

## Task 4: Verify plan covers all failure modes

**Spec coverage check:**

| Requirement | Task |
|-------------|------|
| Retry YouSearch API on failure | Task 2 |
| Return distinct status when research fails | Task 3 |
| Circuit breaker prevents infinite re-research loop | Task 3 |
| Circuit breaker prevents infinite idea_gen loop | Task 3 |
| Checkpoint cleaned even on failure path | Task 3 |

**Placeholder scan:** No TBD/TODO found — all steps have actual code.

**Type consistency:** All method signatures match existing code — `research_from_keywords()` unchanged except retry wrapper, `web_search_trending()` signature unchanged.

---

## Execution Options

**Plan complete and saved to `docs/superpowers/plans/2026-04-15-research-failure-handling.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
