# TOOLS.md — Video Pipeline Agent

## ⚠️ PRODUCTION VIDEO GENERATION DISABLED

Budget exhausted. DO NOT use these for production video generation:
- `video_pipeline_v3.py` — for video generation ONLY
- `minimax_tts.py` — TTS API calls cost money

## ✅ AVAILABLE (development/testing)

### Local Testing
- Run pipeline with `--dry-run` or mock mode if available
- Test individual functions without API calls
- Use local video processing (ffmpeg) for testing

### Pipeline Structure
```
video_pipeline_v3.py
├── Scene generation (MiniMax Image API)
├── TTS audio (MiniMax TTS API) ← DISABLED
├── Video composition (ffmpeg/local)
├── Lipsync (WaveSpeed) ← DISABLED if paid
└── Karaoke subtitles (moviepy)
```

### Config Files
- `video_config_productivity.json` — business config
- `video_config_seafood.json` — niche config  
- `video_config_secrets.json` — API keys (DO NOT COMMIT)

## Workflow

1. **Plan** → Research and design
2. **Code** → Write/improve code locally
3. **Test** → Use dry-run or local ffmpeg tests
4. **Deploy** → Push to GitHub for review
