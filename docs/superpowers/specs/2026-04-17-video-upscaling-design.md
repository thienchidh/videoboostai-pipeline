# Video Upscaling Design

## Context

Kie lipsync provider generates video at ~480p (854x480 equivalent), producing 9:16 vertical videos. The output is visibly lower quality compared to the 1080x1920 images from the image generator. Goal: upscale lipsync video to 2K (1920x3408) using FFmpeg-only approach, since no GPU is available.

Pipeline context: CPU 16 cores / 32GB RAM. Real-ESRGAN/AI upscaling too slow on CPU (~4-8 hours per 30s video). FFmpeg approach targets ~5-10 minutes per video.

## Design

### Position in Pipeline

```
Lipsync (9:16, ~480p) → Concatenate → UPSCALE → Watermark → Subtitles → BGM
```

Upscale step inserted **after concat, before watermark**. This avoids per-scene upscaling (only upscale once) and preserves quality through subsequent post-processing steps.

### Function Location

New function in `core/video_utils.py`:
- `upscale_video(input_path, output_path, crf=18, preset="slow")`

### FFmpeg Filter Chain

```
scale=1920:3408:flags=lanczos+accurate_rnd,unsharp=5:5:0.5:5:5:0.0,minterpolate=fps=60:mi_mode=mci
```

| Filter | Purpose |
|--------|---------|
| `scale=1920:3408` | 4x upscale from ~480p to 2K vertical |
| `lanczos+accurate_rnd` | Sharpest available scaling algorithm |
| `unsharp=5:5:0.5:5:5:0.0` | Light sharpen to enhance edges without artifacts |
| `minterpolate=fps=60:mi_mode=mci` | Motion-compensated interpolation to 60fps for smoother motion |

### Encoding Settings

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| CRF | 18 | Nearly lossless (23=default, 18=visually indistinguishable from source) |
| Preset | slow | Better compression per quality, CPU has 16 cores to compensate |
| Pixel format | yuv420p | Standard for compatibility |
| Codec | libx264 | Universal compatibility |

### Config Integration

In `configs/technical/config_technical.yaml`:

```yaml
video:
  upscale: true           # enable/disable upscaling
  upscale_res: "1920x3408" # output resolution
  upscale_crf: 18          # quality level
  upscale_preset: "slow"   # encoding speed
```

### Pipeline Runner Integration

In `modules/pipeline/pipeline_runner.py`, after `concat_videos()` call and before `add_watermark()`:

```python
if self.technical_config.video.get("upscale", False):
    temp_no_upscale = output_path
    output_path = temp_dir / "video_upscale.mp4"
    upscale_video(temp_no_upscale, output_path,
                  crf=self.technical_config.video.get("upscale_crf", 18),
                  preset=self.technical_config.video.get("upscale_preset", "slow"))
```

### Error Handling

- If upscale fails (FFmpeg error), log warning and continue with non-upscaled video
- Do not fail the entire pipeline for upscaling issues

## Performance Estimate

For 30s video at ~480p, 9:16:
- ~900 frames to process
- `minterpolate` is the bottleneck (motion compensation)
- Estimated: **8-15 minutes** on 16-core CPU

## Scope

- Upscaling only (no audio processing — audio passed through as copy)
- No changes to lipsync provider
- No changes to image generation pipeline

## Out of Scope

- GPU-based upscaling (Real-ESRGAN, RIFE)
- Resolution options other than 1920x3408
- Per-scene upscaling (not needed since lipsync scenes are short and concat happens anyway)
