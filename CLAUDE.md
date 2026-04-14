# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VideoBoostAI is an automated pipeline for generating short TikTok/Reels videos in Vietnamese — from content research → script → finished video with TTS, image generation, lipsync video, karaoke subtitles, and watermark.

## Commands

### Running the Pipeline

```bash
# Full pipeline (content + video) via unified entry point
python scripts/run_pipeline.py --ideas 1 --produce

# Content generation only
python scripts/run_pipeline.py --ideas 3

# With lipsync skipped (static image + audio, saves credits)
python scripts/run_pipeline.py --ideas 1 --produce --skip-lipsync

# Old video-only entry point
python scripts/video_pipeline_v3.py nang_suat_thong_minh
```

### Testing

```bash
pytest tests/ -v
pytest tests/test_scene_processor.py -v
```

## Architecture

### Two-Stage Pipeline

**Stage 1 — Content Pipeline** (`modules/content/content_pipeline.py`):
```
Research topics → Generate ideas → Dedup (sentence-transformers) → Generate scripts → Save YAML
```

**Stage 2 — Video Pipeline** (`scripts/video_pipeline_v3.py` → `modules/pipeline/pipeline_runner.py`):
```
Load YAML → TTS + Image (parallel) → Lipsync → Concatenate → Watermark + Subtitles + BGM
```

### Provider Plugin System (`core/plugins.py`)

All providers registered via `PluginRegistry` with abstract base classes:
- `TTSProvider` — Edge (free), MiniMax
- `ImageProvider` — MiniMax, WaveSpeed, **Kie Z Image** (async polling)
- `LipsyncProvider` — WaveSpeed, Kie.ai Infinitalk (async polling)
- `MusicProvider` — MiniMax
- `LLMProvider` — MiniMax (Anthropic-compatible API)

### Image Fallback Chain

When primary image provider fails → automatic fallback:
- **MiniMax image** fails → try **Kie Z Image** (async: createTask → poll → download)
- Kie Z Image registered as `"kie"` in provider registry

### Lipsync Fallback

When lipsync credits exhausted → `LipsyncQuotaError` raised → automatic fallback to static video (image + TTS audio).

### Config Hierarchy

```
configs/technical/config_technical.yaml     # API keys, URLs, generation models, storage
configs/channels/{channel_id}/config.yaml  # Per-channel: characters, watermark, style, voices
configs/channels/{channel_id}/scenarios/
  YYYY-MM-DD/{slug}.yaml                    # Scene scripts (title, scenes, characters)
```

Config loading:
- `TechnicalConfig.load()` → merged from YAML
- `ChannelConfig.load(channel_id)` → validates required fields, raises if missing
- `ScenarioConfig.load(path)` → scenes and title

### PipelineContext (`modules/pipeline/config.py`)

Holds config for one run: `technical`, `channel`, `scenario`. Thread-safe (one instance per run).

### SceneDurationError (`modules/pipeline/exceptions.py`)

Raised when TTS duration exceeds channel limits. Caught in `pipeline_runner.py` and re-raised to trigger script regeneration.

## Key Files

| File | Purpose |
|------|---------|
| `scripts/run_pipeline.py` | Unified entry point (content + video), `--ideas N --produce` |
| `scripts/video_pipeline_v3.py` | Legacy video-only entry point |
| `modules/content/content_pipeline.py` | Stage 1: research → ideas → scripts → YAML |
| `modules/content/content_idea_generator.py` | LLM-powered script generation with scene prompts |
| `modules/pipeline/pipeline_runner.py` | Stage 2 orchestrator: TTS → Image → Lipsync → Concatenate |
| `modules/pipeline/scene_processor.py` | Single scene: expand_script → TTS → Image → Lipsync → Crop |
| `core/plugins.py` | PluginRegistry + provider ABCs |
| `core/video_utils.py` | FFmpeg wrappers, subtitle/bgm/watermark utilities, `LipsyncQuotaError` |
| `modules/media/image_gen.py` | MiniMax, WaveSpeed, **Kie Z Image** providers |
| `modules/media/lipsync.py` | Lipsync providers with `LipsyncQuotaError` |
| `utils/embedding.py` | sentence-transformers dedup (512-dim, cosine sim > 0.75) |
| `db.py` | `TopicSource` (status: pending/completed), `ContentIdea`, `IdeaEmbedding` |

## Content Pipeline Flow

1. `ContentPipeline.run_full_cycle()` checks **pending topic sources** first
2. If none pending → `TopicResearcher.research_from_keywords()` gets fresh topics from YouSearch API
3. `ContentIdeaGenerator.generate_ideas_from_topics()` converts topics to ideas
4. `check_duplicate_ideas()` uses sentence-transformers to filter semantically similar ideas (threshold 0.75 cosine similarity)
5. For each non-duplicate idea → `generate_script_from_idea()` calls MiniMax LLM with scene prompt
6. Script saved to YAML in `configs/channels/{channel_id}/scenarios/YYYY-MM-DD/{slug}.yaml`
7. TopicSource marked `completed` after YAML saved

**Pending Pool**: `get_pending_topic_sources(limit=1)` returns topics not yet processed. Subsequent runs pick up from pending pool instead of re-researching.

## Database Models (`db.py`)

- `TopicSource` — research topics with `status` (pending/completed), `topics` JSON field
- `ContentIdea` — content ideas with `script_json`, `status` (raw/script_ready)
- `IdeaEmbedding` — 512-dim vector per idea for semantic dedup
- `get_recent_topic_titles(days=30)` — queries non-completed topic titles for dedup
- `mark_topic_source_completed(source_id)` — sets status='completed'

## Logging for API Debugging

All API calls log full request/response payloads:
- LLM (`modules/llm/minimax.py`): model, max_tokens, payload, response status + body
- TTS (`modules/media/tts.py`): voice, speed, text length, payload, response
- Image (`modules/media/image_gen.py`): aspect_ratio, prompt length, payload, response

Run with `INFO` level to see payloads: `logging.basicConfig(level=logging.INFO)`.

## API Providers

| Provider | Endpoint | Auth |
|-----------|----------|------|
| MiniMax Image | `https://api.minimax.io/v1/image_generation` | Bearer token |
| MiniMax TTS | `https://api.minimax.io/v1/t2a_v2` | Bearer token |
| Kie Z Image | `POST /api/v1/jobs/createTask`, `GET /api/v1/jobs/recordInfo` | Bearer token |
| Kie Infinitalk | Same base URL | Bearer token |
| WaveSpeed | `https://api.wavespeed.ai` | Bearer token |
| YouSearch | `https://ydc-index.io/v1/search` | X-API-Key header |

## Testing

Tests use pytest fixtures and mock providers. Key test files:
- `tests/test_scene_processor.py` — scene processing logic
- `tests/test_video_utils.py` — FFmpeg wrappers