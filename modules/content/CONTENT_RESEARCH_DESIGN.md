# Content Topic Research Module - Design

## Overview

Research trending topics → Generate content ideas → Schedule content → Produce videos → Upload to FB + TikTok

## Architecture

```
ContentResearcher  →  ContentIdeaGenerator  →  ContentCalendar
       ↓                      ↓                       ↓
 topic_sources        content_ideas           content_calendar
       ↓                      ↓                       ↓
 Web Search             Script Gen            Video Pipeline
                       scene_scripts              → SocialPost
```

## Database Schema

### Table: topic_sources
```sql
CREATE TABLE topic_sources (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR(50) NOT NULL,     -- 'web_search', 'hashtag', 'competitor', 'manual'
    source_query VARCHAR(500),             -- search query or hashtag
    source_url VARCHAR(1000),
    results JSONB,                         -- raw results from source
    topics_found JSONB,                   -- extracted topics/keywords
    last_fetched TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: content_ideas
```sql
CREATE TABLE content_ideas (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    topic_keywords JSONB,                  -- ['productivity', 'time management', ...]
    content_angle VARCHAR(200),            -- 'tips', 'story', 'educational', 'motivational'
    target_platform VARCHAR(20),          -- 'facebook', 'tiktok', 'both'
    source_id INTEGER REFERENCES topic_sources(id) ON DELETE SET NULL,
    status VARCHAR(50) DEFAULT 'raw',      -- 'raw', 'refined', 'script_ready', 'scheduled', 'posted'
    script_json JSONB,                    -- generated scene scripts
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: content_calendar
```sql
CREATE TABLE content_calendar (
    id SERIAL PRIMARY KEY,
    idea_id INTEGER REFERENCES content_ideas(id) ON DELETE CASCADE,
    platform VARCHAR(20) NOT NULL,         -- 'facebook', 'tiktok', 'both'
    scheduled_date DATE,
    scheduled_time TIME,
    status VARCHAR(50) DEFAULT 'scheduled', -- 'scheduled', 'in_production', 'posted', 'failed'
    video_run_id INTEGER REFERENCES video_runs(id) ON DELETE SET NULL,
    social_post_id INTEGER REFERENCES social_posts(id) ON DELETE SET NULL,
    priority VARCHAR(20) DEFAULT 'medium',  -- 'high', 'medium', 'low'
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Module Structure

```
modules/content/
├── topic_researcher.py   # TopicResearcher - research trending topics
├── content_idea_generator.py  # ContentIdeaGenerator - generate ideas from topics
├── content_calendar.py    # ContentCalendar - schedule and track
└── content_pipeline.py    # ContentPipeline - orchestrator
```

## Features

### 1. TopicResearcher
- **Web Search**: Search trending topics via web search API (ollama web search)
- **Keyword Analysis**: Extract keywords from topics
- **Hashtag Research**: Get trending hashtags from TikTok/FB
- **Competitor Analysis**: Analyze top posts from similar pages
- **Scheduled Research**: Auto-run periodic topic research

### 2. ContentIdeaGenerator
- **Idea Generation**: Generate content ideas from research results
- **Script Generation**: Convert ideas into scene scripts (matching video_pipeline format)
- **Template-based**: Use templates for consistent format
- **Scene Scripts**: Output scene scripts ready for video_pipeline_v3.py

### 3. ContentCalendar
- **Scheduling**: Schedule content for specific dates/times
- **Platform Assignment**: Assign content to FB page, TikTok, or both
- **Production Tracking**: Track status through production pipeline
- **Auto-scheduling**: Schedule next content based on cadence

### 4. ContentPipeline (Orchestrator)
- **Research → Ideas → Scripts → Schedule → Produce → Upload**
- **Auto-pipeline**: When new idea is script-ready, auto-schedule
- **Config-driven**: Read page config (FB page ID, TikTok account)
- **Dry-run mode**: Test without actual posting

## Page Configuration
```json
{
  "page": {
    "facebook": {
      "page_id": "...",
      "page_name": "Năng Suất Thông Minh"
    },
    "tiktok": {
      "account_id": "...",
      "account_name": "@NangSuatThongMinh"
    }
  },
  "content": {
    "niche": "productivity|năng suất|quản lý thời gian",
    "cadence": {
      "facebook": "daily",
      "tiktok": "daily"
    },
    "topics": ["time management", "productivity tips", "work life balance"]
  }
}
```

## Social Account Config (DB credentials)
- Platform: `facebook` → page access token
- Platform: `tiktok` → refresh token / access token

## Content Ideas → Video Pipeline Flow
1. ContentPipeline generates scene scripts from ideas
2. Scripts saved to `scene_scripts/` directory
3. Auto-trigger video_pipeline_v3.py with generated config
4. Output video tracked via video_run_id
5. Social posts created and uploaded
