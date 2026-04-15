# Automated Content Pipeline — Design Specification

> **Date:** 2026-04-15
> **Status:** Draft for review
> **Goal:** Fully automated content pipeline — research → pending pool → scripts → calendar → produce

---

## Overview

The pipeline runs fully automated on a schedule without human intervention. It uses a **Topic Seed Model** where keywords are dynamically extracted from search results and fed into the next research cycle — no hardcoded keyword exhaustion problem.

```
Seed Keywords (channel config)
    ↓
YouSearch API → Topics → Extract keywords → KeywordPool
    ↓
TopicSource (pending) → Ideas (raw) → LLM → Scripts (script_ready)
    ↓
Calendar → Produce → Videos
```

---

## Architecture

### Components

| Component | Responsibility |
|-----------|----------------|
| `TopicResearcher` | Search YouSearch, extract keywords, save TopicSources |
| `KeywordPool` | Store extracted keywords for next research cycle |
| `ContentIdeaGenerator` | Generate ideas from topics, create scripts via LLM |
| `ContentPipeline` | Orchestrator: pending pool logic, research trigger, checkpoint |
| `ContentCalendar` | Schedule script_ready ideas for production |
| `run_scheduler.py` | Cron job: trigger research on schedule |
| `run_pipeline.py --produce` | Consume pending pool, produce videos |

### Pipeline Flow

```
┌─────────────────────────────────────────────────────────┐
│ run_scheduler.py (cron, 2x/day)                         │
│   → ContentPipeline.run_research_phase()                │
│       → Check PipelineLock (acquire or skip)            │
│       → Research topics from KeywordPool               │
│       → Extract keywords → save to KeywordPool          │
│       → Save TopicSource (status=pending)               │
│       → Generate ideas → pending pool (status=raw)      │
│       → Release PipelineLock                            │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ run_pipeline.py --produce                              │
│   → ContentPipeline.run_produce_phase()                 │
│       → Load ideas (status=script_ready) from DB        │
│       → Produce videos                                 │
│       → Schedule next run in calendar                  │
└─────────────────────────────────────────────────────────┘
```

---

## Channel Configuration

Each channel has its own config at `configs/channels/{channel_id}/config.yaml`.

```yaml
# configs/channels/nang_suat_thong_minh/config.yaml
research:
  niche_keywords:           # seed keywords — starting point for research
    - productivity
    - time management
    - năng suất
  schedule: "2h"            # research trigger: twice daily
  threshold: 3              # trigger research if pending pool < 3 ideas
  pending_pool_size: 5      # min ideas in pending pool before skipping research

content:
  target_platform: "both"
  content_angle: "tips"
  auto_schedule: true
```

Shared config at `configs/technical/config_technical.yaml`:

```yaml
# Shared research retry / circuit breaker settings
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
  ttl_days: 30             # delete keywords older than 30 days
```

---

## Database Schema

### New Table: `content_keyword_pool`

```sql
CREATE TABLE content_keyword_pool (
    id SERIAL PRIMARY KEY,
    keyword VARCHAR(255) NOT NULL,
    source_topic_id INTEGER REFERENCES topic_sources(id),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_keyword_pool_keyword ON content_keyword_pool(keyword);
```

### New Table: `pipeline_locks`

Prevents concurrent research runs from duplicating work.

```sql
CREATE TABLE pipeline_locks (
    lock_name VARCHAR(100) PRIMARY KEY,
    acquired_at TIMESTAMP,
    owner_run_id VARCHAR(100),
    expires_at TIMESTAMP
);
```

### New Table: `content_idea_embedding` (existing, reused)

No schema change. Behavior changes:
- When `check_duplicate_ideas()` finds a dupe: save ContentIdea with `status=duplicate` + save embedding pointing to it
- Next run: embedding check catches dupe before LLM is called

### Existing Tables Used

| Table | Usage |
|-------|-------|
| `topic_sources` | Store researched topics with status=pending/completed |
| `content_idea` | Store ideas (status: raw, script_ready, duplicate, re_run) |
| `content_calendar` | Schedule ideas for production |

---

## Research Phase

### Research Trigger Conditions (OR logic)

1. **Schedule trigger** — `run_scheduler.py` cron chạy 2 lần/ngày, mỗi lần gọi `run_research_phase()`
2. **Threshold trigger** — nếu pending pool (ideas với status=raw, chưa có script) < `threshold` từ channel config → tự động trigger research

### Research Flow

```
1. Acquire PipelineLock("research") — nếu fail, skip research, fallback vào pending pool
2. Load keywords from KeywordPool (distinct, newest first) — fallback to channel seed keywords if empty
3. For each keyword:
   a. web_search_trending(keyword, count=10)
   b. Retry up to research.max_attempts with Backoff
   c. Extract keywords from topic titles/descriptions
   d. Insert extracted keywords into KeywordPool
   e. Save topics to TopicSource (status=pending)
   f. Generate ideas from topics → save to ContentIdea (status=raw)
4. Release PipelineLock("research")
```

### Keyword Extraction

From each topic result:
```python
title = "5 Best Productivity Apps for 2024"
description = "Discover the top productivity apps..."
# Extract: split words, filter len > 4, lowercase, unique
# Result: ["productivity apps", "2024", "discover", "productivity", "apps"]
```

Extracted keywords saved to `content_keyword_pool` for next research cycle.

---

## Failure Handling

### Research Failures

| Failure | Handling |
|---------|----------|
| YouSearch API returns HTTP error | Retry up to `max_attempts` (3) with exponential backoff |
| All retries fail | `status=research_failed`, release lock, return error |
| No topics found | `status=no_topics_from_api`, same retry behavior |
| Empty keyword pool | Fall back to channel seed keywords |

### Idea Generation Failures

| Failure | Handling |
|---------|----------|
| `generate_ideas_from_topics()` returns empty | Retry up to `max_attempts` (5) per cycle |
| Circuit breaker opens (max failures reached) | `status=idea_generation_failed`, exit research phase |
| All ideas are duplicates | Re-research with new keywords, max `max_research_loops` (3) times |

### Race Conditions

| Scenario | Solution |
|----------|----------|
| Two runs trigger research simultaneously | `PipelineLock("research")` — atomic acquire, only winner runs research |
| Run crashes while holding lock | Lock has `expires_at` — auto-release after 5 minutes |
| Produce while research is writing ideas | Produce only consumes `status=script_ready` ideas — raw ideas untouched |

---

## Cross-Run Duplicate Handling

When `check_duplicate_ideas()` detects a semantic duplicate (cosine similarity > 0.75):

```python
# In check_duplicate_ideas():
if similar:
    # Save dupe as ContentIdea with status=duplicate
    dupe_idea_id = save_content_idea(project_id, idea, source_id=None)
    dupe_idea_id.status = "duplicate"
    # Save embedding pointing to this dupe idea
    save_idea_embedding(
        idea_id=dupe_idea_id,
        title_vi=title,
        title_en="",
        embedding=embedding,
    )
    skipped.append(...)
```

**Why it works:** `find_similar_ideas()` joins `IdeaEmbedding → ContentIdea`. Since the dupe has a valid `content_idea_id`, the next run finds its embedding via the normal query and flags it as dupe before calling LLM.

---

## Checkpoint Behavior

| Exit condition | Checkpoint |
|---------------|-----------|
| ≥1 idea processed successfully | Keep checkpoint — next run resumes from next idea |
| 0 ideas processed (any failure path) | Delete checkpoint — next run starts fresh |

Implementation: `try/finally` block in `run_full_cycle()` ensures checkpoint cleanup on all exit paths.

---

## Status Values

| Status | Meaning |
|--------|---------|
| `"research_failed"` | All research retries exhausted, no topics found |
| `"idea_generation_failed"` | idea_gen circuit breaker open |
| `"no_new_ideas"` | All ideas were semantic duplicates |
| `"partial_success"` | Some ideas produced before failure |
| `"no_topics"` | Research returned empty list |
| `"re_run_from_existing"` | skip_content mode — loading existing scripts |
| `"re_search_loop_exhausted"` | Max re-research cycles reached, giving up |

---

## Files Changed

| File | Change |
|------|--------|
| `configs/technical/config_technical.yaml` | Add `research`, `idea_gen`, `keyword_pool` sections |
| `configs/channels/{channel_id}/config.yaml` | Add `research.schedule`, `research.threshold`, `research.pending_pool_size` |
| `db_models.py` | Add `ContentKeywordPool`, `PipelineLock` models |
| `db.py` | Add keyword pool CRUD, lock acquire/release, `save_content_ideas` with status |
| `modules/pipeline/backoff.py` | Create: Backoff + CircuitBreaker utilities |
| `modules/content/topic_researcher.py` | Add retry loop to `web_search_trending()`, keyword extraction |
| `modules/content/content_pipeline.py` | Refactor: pending pool logic, research trigger, lock acquisition, checkpoint finally |
| `utils/embedding.py` | Save dupe ideas with `status=duplicate` + embeddings |
| `scripts/run_scheduler.py` | Create: cron job for scheduled research |
| `tests/test_content_pipeline_research.py` | Add tests for failure modes, pending pool, lock |
| `tests/test_backoff.py` | Create: Backoff + CircuitBreaker tests |

---

## Spec Self-Review

1. **Placeholder scan:** No TBD/TODO found — all sections have specific values
2. **Internal consistency:** Channel config and technical config split matches user requirement (per-channel vs shared). PipelineLock prevents race condition. Checkpoint finally-block handles all exit paths.
3. **Scope:** Focused on research automation + failure handling + cross-run dedup. Calendar + produce phase unchanged (existing behavior).
4. **Ambiguity:** "schedule: 2h" — means twice daily. Clarified as "run_scheduler.py cron 2x/day". `threshold` checked against ideas with `status=raw` (pending pool). All values specific.
