# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VideoBoostAI is an automated pipeline for generating short TikTok/Reels videos in Vietnamese — from script to finished video with TTS, image generation, lipsync video, karaoke subtitles, and watermark.

## Commands

### Running the Pipeline

```bash
# Full pipeline for a channel
./venv/bin/python scripts/video_pipeline_v3.py nang_suat_thong_minh

# Specific scenario
./venv/bin/python scripts/video_pipeline_v3.py nang_suat_thong_minh/2026-04-13/3-meo-tang-nangsuat

# Dry-run (no API calls)
./venv/bin/python scripts/video_pipeline_v3.py nang_suat_thong_minh --dry-run

# Dry-run TTS only
./venv/bin/python scripts/video_pipeline_v3.py nang_suat_thong_minh --dry-run-tts

# Skip lipsync (save credits)
./venv/bin/python scripts/video_pipeline_v3.py nang_suat_thong_minh --stop-before-lipsync

# Upload to social after generation
./venv/bin/python scripts/video_pipeline_v3.py nang_suat_thong_minh --upload
```

### Testing

```bash
# All tests
./venv/bin/pytest tests/ -v

# Single test file
./venv/bin/pytest tests/test_scene_processor.py -v

# With coverage
./venv/bin/pytest tests/ --cov=. --cov-report=term-missing
```

## Architecture

### Provider Plugin System (`core/plugins.py`)

All media providers are registered via `PluginRegistry` and follow abstract base classes:
- `TTSProvider` — text-to-speech (Edge, MiniMax)
- `ImageProvider` — image generation (MiniMax, WaveSpeed, Kie)
- `LipsyncProvider` — talking-head video (WaveSpeed, Kie.ai)
- `MusicProvider` — background music generation
- `LLMProvider` — chat/LLM (MiniMax)

Providers are imported in `pipeline_runner.py` to trigger registration. Add new providers by creating a module and importing it there.

### Pipeline Flow (`modules/pipeline/`)

1. `PipelineContext` — loads and holds technical + channel + scenario config for one run
2. `VideoPipelineRunner` — orchestrates the full pipeline, delegates to providers
3. `SingleCharSceneProcessor` — processes one scene: TTS → image → S3 upload → lipsync

Scene processing:
```
TTS (text → audio) → Image Gen (prompt → image) → S3 Upload → Lipsync (image+audio → video)
```

If lipsync fails due to exhausted credits, pipeline falls back to static image + audio video.

### Config Hierarchy (`configs/`)

- `configs/technical/config_technical.yaml` — API keys, endpoints, model selection
- `configs/channels/{channel_id}/config.yaml` — per-channel settings (watermark, style, social)
- `configs/channels/{channel_id}/scenarios/YYYY-MM-DD/{scenario}.yaml` — scene scripts and characters

### Media Modules (`modules/media/`)

- `tts.py` — TTS providers with `generate()` and `get_word_timestamps()` for karaoke
- `image_gen.py` — Image generation providers
- `lipsync.py` — Video lipsync providers (WaveSpeed, Kie.ai Infinitalk)
- `s3_uploader.py` — MinIO/S3 upload for media files
- `music_gen.py` — Background music generation

### Social Modules (`modules/social/`)

- `facebook.py` — Facebook Page API for publishing
- `tiktok.py` — TikTok API for publishing

## Key Files

| File | Purpose |
|------|---------|
| `scripts/video_pipeline_v3.py` | CLI entry point |
| `modules/pipeline/pipeline_runner.py` | Main pipeline orchestration |
| `modules/pipeline/scene_processor.py` | Single scene processing |
| `modules/pipeline/config.py` | `PipelineContext` config holder |
| `core/plugins.py` | Provider registry and ABCs |
| `core/video_utils.py` | ffmpeg wrappers, subtitle/watermark/bgm utilities |
| `db.py` | Database models and connection |