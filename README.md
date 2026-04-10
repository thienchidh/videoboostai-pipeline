# VideoBoostAI Pipeline

## Mục lục
- [Giới thiệu](#giới-thiệu)
- [Cài đặt](#cài-đặt)
- [Sử dụng](#sử-dụng)
- [Config](#config)

## Giới thiệu

Video generation pipeline tự động:
1. TTS (Text-to-Speech) với MiniMax
2. Whisper timestamps cho karaoke subtitles
3. Image generation (3D Pixar style)
4. Lipsync video với WaveSpeed/LTX
5. Karaoke subtitles
6. Watermark động (MoviePy bounce)
7. Background music

## Cài đặt

```bash
# Clone repo
git clone <repo-url>
cd videoboostai-workspace

# Install dependencies
pip install moviepy pillow edge-tts openai-whisper requests

# Setup fonts (optional)
sudo apt-get install fonts-dejavu fonts-liberation
```

## Sử dụng

```bash
# Copy secrets template
cp video_config_secrets.json.template video_config_secrets.json
# Edit video_config_secrets.json with your API keys

# Run pipeline
python3 video_pipeline_v3.py video_config_productivity.json video_config_secrets.json
```

## Config

### video_config_productivity.json (Business)
- Video settings, scenes, characters, prompts
- Subtitle settings
- Watermark settings

### video_config_secrets.json (API Keys)
- WaveSpeed API key
- MiniMax API key

## Watermark Config

```json
{
  "enable": true,
  "text": "@NangSuatThongMinh",
  "font": "DejaVuSans-Bold",
  "font_size": 64,
  "opacity": 15,
  "shadow_opacity": 12,
  "stroke_opacity": 50,
  "velocity_x": 1.2,
  "velocity_y": 0.8,
  "margin": 8
}
```

## Pipeline Flow

```
1. Load configs
2. Generate TTS per scene
3. Whisper timestamps
4. Generate images
5. Lipsync videos
6. Concatenate scenes
7. Add watermark (MoviePy)
8. Add karaoke subtitles
9. Add background music
10. Output MP4
```
