"""
core/video_utils.py — Single source of truth for FFmpeg video utilities.

Consolidates duplicate implementations from:
- scripts/video_pipeline_v3.py  (main pipeline)
- core/base_pipeline.py (abstract base)
- modules/media/video_compile.py (compile utils)

Functions here should NOT depend on any pipeline instance state.
All functions are standalone or accept explicit parameters.
"""

import os
import re
import shutil
import subprocess
import tempfile
import random
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.paths import PROJECT_ROOT, get_karaoke_python, get_ffmpeg, get_ffprobe, get_font_path


# ==================== LOGGING ====================

def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ==================== DEEP MERGE ====================

def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base. Override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ==================== VIDEO INFO ====================

def get_video_info(video_path: str) -> tuple:
    """Get video dimensions, fps, and duration using ffprobe.

    Returns:
        tuple: (width, height, fps, duration)
    """
    result = subprocess.run(
        [str(get_ffprobe()), "-v", "quiet", "-show_entries",
         "stream=width,height,r_frame_rate:format=duration",
         "-of", "json", video_path],
        capture_output=True, text=True
    )
    info = json.loads(result.stdout)
    video = info["streams"][0]
    fps_parts = video["r_frame_rate"].split("/")
    fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) > 1 else float(fps_parts[0])
    w = int(video.get("width", 1080))
    h = int(video.get("height", 1920))
    duration = float(info["format"]["duration"])
    return w, h, fps, duration


# ==================== DURATION HELPERS ====================

def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    result = subprocess.run(
        [str(get_ffprobe()), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", video_path],
        capture_output=True, text=True
    )
    return float(result.stdout.strip() or 0)


def get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    result = subprocess.run(
        [str(get_ffprobe()), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", audio_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {audio_path}: {result.stderr}")
    duration_str = result.stdout.strip()
    if not duration_str:
        raise RuntimeError(f"ffprobe returned empty duration for {audio_path}")
    return float(duration_str)


# ==================== WAVESPEED UPLOAD ====================

def upload_file(file_path: str, wsp_base: str, wsp_key: str) -> Optional[str]:
    """Upload file to WaveSpeedAI. Returns download URL or None."""
    ext = Path(file_path).suffix.lstrip(".")
    content_type = f"audio/{ext}" if ext in ["mp3", "wav", "ogg"] else f"image/{ext}"
    url = f"{wsp_base}/api/v3/media/upload/binary?ext={ext}"
    headers = {"Authorization": f"Bearer {wsp_key}", "Content-Type": content_type}
    import requests
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(url, headers=headers, data=f, timeout=60)
        data = resp.json()
        if data.get("data", {}).get("download_url"):
            return data["data"]["download_url"]
        log(f"  ❌ Upload failed: {data}")
    except Exception as e:
        log(f"  ❌ Upload error: {e}")
    return None


def wait_for_job(job_id: str, wsp_base: str, wsp_key: str, max_wait: int = 300) -> Optional[str]:
    """Poll WaveSpeed job until completion. Returns output URL or None."""
    import requests
    url = f"{wsp_base}/api/v3/predictions/{job_id}/result"
    headers = {"Authorization": f"Bearer {wsp_key}"}
    elapsed = 0
    interval = 10
    while elapsed < max_wait:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            data = resp.json()
            status = data.get("data", {}).get("status", "processing")
            outputs = data.get("data", {}).get("outputs", [])
            if status == "completed" and outputs:
                log(f"  ✅ Ready ({elapsed}s)")
                return outputs[0]
            elif status == "failed":
                log(f"  ❌ Failed: {data.get('data', {}).get('error', 'unknown')}")
                return None
            log(f"  ⏳ {status}... ({elapsed}s)")
            time.sleep(interval)
            elapsed += interval
        except Exception as e:
            log(f"  ⚠️ Poll error: {e}")
            time.sleep(interval)
            elapsed += interval
    log(f"  ❌ Timeout")
    return None


# ==================== CROP TO 9:16 ====================

def crop_to_9x16(input_video: str, output_video: str) -> Optional[str]:
    """Crop/convert any video to 9:16 vertical using center crop.

    Strategy:
    - Horizontal (16:9) input → center crop sides → scale to 1080x1920
    - Vertical (9:16) input → scale to fit
    - Square → scale to fit
    """
    log(f"  📐 Crop to 9:16...")

    result = subprocess.run(
        [str(get_ffprobe()), "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", input_video],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        dims = result.stdout.strip().split(',')
        if len(dims) == 2:
            w, h = int(dims[0]), int(dims[1])
            input_ratio = w / h
            target_ratio = 9 / 16  # 0.5625

            log(f"  📐 Input: {w}x{h} ({input_ratio:.2f}:1), Target: 9:16 ({target_ratio:.2f}:1)")

            if input_ratio > target_ratio:
                new_w = int(h * (9 / 16))
                x_offset = (w - new_w) // 2
                crop_filter = f"crop={new_w}:{h}:{x_offset}:0,scale=1080:1920"
                log(f"  📐 Center crop: crop={new_w}:{h}:{x_offset}:0 → scale=1080:1920")
            elif input_ratio < target_ratio:
                new_h = int(w * (16 / 9))
                y_offset = (h - new_h) // 2
                crop_filter = f"crop={w}:{new_h}:0:{y_offset},scale=1080:1920"
                log(f"  📐 Center crop: crop={w}:{new_h}:0:{y_offset} → scale=1080:1920")
            else:
                crop_filter = "scale=1080:1920"

            cmd = [str(get_ffmpeg()), "-i", input_video,
                  "-vf", crop_filter,
                  "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                  "-c:a", "aac", "-y", output_video]
            try:
                subprocess.run(cmd, capture_output=True, timeout=300)
                if Path(output_video).exists():
                    return output_video
            except Exception as e:
                log(f"  ❌ Crop error: {e}")
    return None


# ==================== CONCAT VIDEOS ====================

def concat_videos(video_paths: List[str], output_path: str,
                  run_dir: Optional[Path] = None) -> Optional[str]:
    """Concatenate multiple videos using concat filtergraph (proper A/V sync).

    Uses filter_complex approach for proper video+audio synchronization.
    Falls back to stream-copy concat on filtergraph failure.
    """
    if not video_paths:
        return None
    log(f"  🔗 Concatenating {len(video_paths)} videos (re-encoding for sync)...")

    if run_dir is None:
        run_dir = Path(output_path).parent

    list_file = run_dir / "concat_list.txt"
    with open(list_file, "w") as f:
        for path in video_paths:
            log(f"    + {Path(path).name}")
            f.write(f"file '{path}'\n")

    # Filtergraph approach (handles different-duration streams correctly)
    filtergraph = ''
    for i, path in enumerate(video_paths):
        filtergraph += f"[{i}:v][{i}:a]"
    filtergraph += f"concat=n={len(video_paths)}:v=1:a=1[outv][outa]"

    input_args = []
    for path in video_paths:
        input_args += ["-i", path]

    cmd = [str(get_ffmpeg()), "-y"] + input_args + [
        "-filter_complex", filtergraph,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        output_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            log(f"  ❌ Concat error: {result.stderr[:300]}")
            log(f"  🔄 Fallback: concat with stream copy...")
            cmd_simple = [
                str(get_ffmpeg()), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-c", "copy", "-bsf:a", "aac_adtstoasc", output_path
            ]
            subprocess.run(cmd_simple, capture_output=True, timeout=600)
        if Path(output_path).exists():
            size = Path(output_path).stat().st_size
            log(f"  ✅ Concat done: {size/1024/1024:.1f}MB")
            return output_path
    except Exception as e:
        log(f"  ❌ Concat exception: {e}")
    return None


# ==================== ADD SUBTITLES (KARAOKE) ====================

def add_subtitles(video_path: str, script_text: str,
                  timestamps: Optional[List[Dict]] = None,
                  output_path: Optional[str] = None,
                  font_size: int = 60,
                  run_dir: Optional[Path] = None) -> str:
    """Add karaoke subtitles to video.

    Args:
        video_path: input video
        script_text: text of the script/song
        timestamps: optional word-level timestamps from TTS for karaoke sync
        output_path: output video path (overwrites if None)
        font_size: font size for subtitle text (default 60, matches main pipeline)
        run_dir: working directory for temp files
    """
    from scripts.karaoke_subtitles import add_karaoke_subtitles

    if output_path is None:
        output_path = video_path

    log(f"  📝 Running karaoke subtitles (font={font_size})...")
    try:
        success = add_karaoke_subtitles(
            video_path,
            script_text,
            output_path,
            timestamps=timestamps,
            font_size=font_size,
        )
        if success:
            log(f"  ✅ Subtitles added: {output_path}")
            return output_path
        else:
            log(f"  ⚠️ Subtitles failed")
    except Exception as e:
        log(f"  ⚠️ Subtitle exception: {e}")
    return video_path


# ==================== ADD BACKGROUND MUSIC ====================

def add_background_music(video_path: str,
                         output_path: str,
                         music_file: Optional[str] = None,
                         music_dir: Optional[str] = None,
                         volume: float = 0.15,
                         fade_duration: float = 2.0,
                         music_provider: Optional[Any] = None,
                         music_prompt: Optional[str] = None,
                         music_duration: int = 30) -> str:
    """Add background music to video.

    Args:
        video_path: input video
        output_path: output video
        music_file: explicit music file path, or "random" / None for random
        music_dir: directory to pick random music from
        volume: music volume 0.0-1.0 (default 0.15 = 15%)
        fade_duration: fade in/out seconds (default 2.0)
        music_provider: MusicProvider instance for generated music (e.g. MiniMaxMusicProvider)
        music_prompt: text prompt for music generation (used with music_provider)
        music_duration: duration in seconds for generated music (default 30)
    """
    # Try provider-based music generation first
    if music_provider and music_prompt:
        import tempfile
        tmp_music = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
        generated = music_provider.generate(music_prompt, duration=music_duration, output_path=tmp_music)
        if generated and Path(generated).exists():
            music_file = generated
            log(f"  🎵 Generated music from prompt: {music_prompt[:60]}")
        else:
            log(f"  ⚠️ Music generation failed, falling back to local files")

    if not music_file or music_file == "random":
        if music_dir is None:
            music_dir = str(PROJECT_ROOT / "music")
        music_path = Path(music_dir)
        if music_path.exists():
            mp3_files = [f for f in music_path.glob("*.mp3") + music_path.glob("*.ogg")
                         if f.stat().st_size > 500000]
            if mp3_files:
                music_file = str(random.choice(mp3_files))
                log(f"  🎲 Random music selected: {Path(music_file).name}")
            else:
                log(f"  ⚠️ No music files found, skipping")
                return video_path
        else:
            log(f"  ⚠️ Music dir not found: {music_dir}, skipping")
            return video_path

    if not Path(music_file).exists():
        log(f"  ⚠️ Music file not found: {music_file}, skipping")
        return video_path

    # Get video duration
    result = subprocess.run(
        [str(get_ffprobe()), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", video_path],
        capture_output=True, text=True
    )
    video_duration = float(result.stdout.strip() or 0)

    # Get music duration
    result = subprocess.run(
        [str(get_ffprobe()), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", music_file],
        capture_output=True, text=True
    )
    music_duration = float(result.stdout.strip() or 0)

    if music_duration <= 0:
        log(f"  ⚠️ Could not get music duration, skipping")
        return video_path

    boost_factor = 2.0  # Boost narration to compensate for amix halving
    filter_str = (
        f"[1:a]aloop=loop=-1:size=0,atrim=0:{video_duration},"
        f"afade=t=in:st=0:d={fade_duration},"
        f"afade=t=out:st={video_duration-fade_duration}:d={fade_duration},"
        f"volume={volume}[music];"
        f"[0:a]volume={boost_factor}[narration];"
        f"[narration][music]amix=inputs=2:duration=first:dropout_transition=2,volume=1.5[a]"
    )

    cmd = [
        str(get_ffmpeg()), "-y", "-i", video_path, "-i", music_file,
        "-filter_complex", filter_str,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path
    ]
    try:
        result2 = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result2.returncode == 0 and Path(output_path).exists():
            orig_size = Path(video_path).stat().st_size
            new_size = Path(output_path).stat().st_size
            log(f"  ✅ Background music added: {Path(output_path).name} ({new_size/1024/1024:.1f}MB)")
            return output_path
        else:
            log(f"  ⚠️ FFmpeg error: {result2.stderr[:200] if result2.stderr else 'unknown'}")
    except Exception as e:
        log(f"  ⚠️ Music mix error: {e}")
    return video_path


# ==================== STATIC WATERMARK ====================

def add_static_watermark(video_path: str, output_path: str,
                        text: str, font_size: int = 36,
                        opacity: float = 0.35,
                        font_path: Optional[str] = None,
                        run_dir: Optional[Path] = None) -> str:
    """Add static watermark overlay to video using PIL + FFmpeg.

    Args:
        video_path: Input video path
        output_path: Output video path
        text: Watermark text
        font_size: Font size (default 36)
        opacity: Opacity 0.0-1.0 (default 0.35)
        font_path: Optional font path; uses system default if None
        run_dir: Working directory for temp files

    Returns:
        Path to watermarked video, or original if failed
    """
    from PIL import Image as PILImage, ImageFont, ImageDraw

    if run_dir is None:
        run_dir = Path(output_path).parent

    w, h, fps, duration = get_video_info(video_path)
    scale = h / 1920
    scaled_font_size = int(font_size * scale)

    try:
        fnt = ImageFont.truetype(font_path or get_font_path(), scaled_font_size)
    except Exception:
        fnt = ImageFont.load_default()

    overlay = PILImage.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    x = w - int(280 * scale)
    y = h - int(70 * scale)
    alpha = int(255 * opacity)
    draw.text((x, y), text, font=fnt, fill=(0, 0, 0, int(alpha * 0.8)))
    draw.text((x, y), text, font=fnt, fill=(255, 255, 255, alpha))

    overlay_path = run_dir / "watermark_overlay.png"
    overlay.save(str(overlay_path))

    tmp_wm = run_dir / "watermark_tmp.mp4"
    cmd = [
        str(get_ffmpeg()), "-y", "-i", str(video_path), "-i", str(overlay_path),
        "-filter_complex", "[0:v][1:v]overlay=0:0[out]",
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "copy",
        str(tmp_wm)
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode == 0 and tmp_wm.exists():
        shutil.copy(tmp_wm, output_path)
        log(f"  ✅ Static watermark added")
        return output_path
    log(f"  ⚠️ Static watermark failed: {result.stderr[:200] if result.stderr else 'unknown'}")
    return video_path


# ==================== DRY RUN FLAGS (shared global) ====================
DRY_RUN = False
DRY_RUN_TTS = False
DRY_RUN_IMAGES = False


# ==================== DRY RUN MOCK FUNCTIONS ====================

def mock_generate_tts(text: str, voice: str = "female_voice",
                      speed: float = 1.0, output_path: Optional[str] = None) -> str:
    """Generate fake TTS audio using ffmpeg (sine tone)."""
    log(f"  🔴 DRY RUN: mock_generate_tts - using placeholder audio")
    if not output_path:
        output_path = f"/tmp/tts_dryrun_{int(time.time()*1000)}.mp3"

    estimated_duration = max(3.0, len(text.split()) / 2.5)
    # Cap at 14s to stay under kie.ai max_duration=15s limit
    estimated_duration = min(estimated_duration, 14.0)
    cmd = [
        str(get_ffmpeg()), "-y",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={estimated_duration}",
        "-af", f"atempo={speed}",
        "-ar", "32000", "-ac", "1", "-ab", "128k",
        output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
        if Path(output_path).exists():
            log(f"  🔴 DRY RUN: TTS placeholder created: {Path(output_path).stat().st_size/1024:.1f}KB")
            return output_path
    except Exception as e:
        log(f"  🔴 DRY RUN: TTS fallback error: {e}")

    Path(output_path).touch()
    return output_path


def mock_generate_image(prompt: str, output_path: str) -> Optional[str]:
    """Generate a solid color placeholder image."""
    log(f"  🔴 DRY RUN: mock_generate_image - using placeholder image")
    try:
        from PIL import Image
        img = Image.new('RGB', (1080, 1920), color=(100, 150, 200))
        img.save(output_path)
        log(f"  🔴 DRY RUN: Image placeholder created: {Path(output_path).stat().st_size/1024:.1f}KB")
        return output_path
    except Exception as e:
        log(f"  🔴 DRY RUN: PIL not available ({e}), trying ffmpeg...")

    cmd = [
        str(get_ffmpeg()), "-y",
        "-f", "lavfi", "-i", "color=c=0x6496C8:s=1080x1920:d=1",
        "-frames:v", "1",
        output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
        if Path(output_path).exists():
            log(f"  🔴 DRY RUN: Image placeholder created (ffmpeg): {Path(output_path).stat().st_size/1024:.1f}KB")
            return output_path
    except Exception as e:
        log(f"  🔴 DRY RUN: Image ffmpeg fallback error: {e}")
    return None


# ==================== LIPSYNC QUOTA ERROR ====================

class LipsyncQuotaError(Exception):
    """Raised when lipsync API runs out of quota/credits."""
    pass


# ==================== CREATE STATIC VIDEO WITH AUDIO ====================

def create_static_video_with_audio(
    image_path: str,
    audio_path: str,
    output_path: str,
    resolution: str = "480p",
) -> Optional[str]:
    """
    Create a static image video with audio track using ffmpeg.
    Used as fallback when lipsync API quota is exhausted.

    Args:
        image_path: Path to source image (jpg/png)
        audio_path: Path to audio file (mp3/wav)
        output_path: Path to save output video
        resolution: "480p" (1080x1920) or "720p" (1280x1920)


    Returns:
        Path to output video, or None on failure.
    """
    res_map = {
        "480p": "1080:1920",
        "720p": "1280:1920",
        "540p": "1080:1920",  # treat 540p same as 480p
    }
    scale = res_map.get(resolution, "1080:1920")

    log(f"  📸 Creating static video (image + TTS audio) → {Path(output_path).name}")
    cmd = [
        str(get_ffmpeg()), "-y",
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-vf", f"scale={scale},setsar=1:1",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=300)
        if Path(output_path).exists():
            size_mb = Path(output_path).stat().st_size / 1024 / 1024
            log(f"  ✅ Static video created: {size_mb:.1f}MB")
            return output_path
        else:
            log(f"  ❌ Static video not created")
    except Exception as e:
        log(f"  ❌ Static video error: {e}")
    return None


# ==================== MOCK LIPSYNC VIDEO ====================

def mock_lipsync_video(image_path: str, audio_path: str, output_path: str) -> Optional[str]:
    """Generate fake lipsync video using ffmpeg (static image + audio)."""
    log(f"  🔴 DRY RUN: mock_lipsync_video - using placeholder video")

    result = subprocess.run(
        [str(get_ffprobe()), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", audio_path],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip() or 5.0)

    cmd = [
        str(get_ffmpeg()), "-y",
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60)
        if Path(output_path).exists():
            log(f"  🔴 DRY RUN: Lipsync placeholder created: {Path(output_path).stat().st_size/1024/1024:.1f}MB")
            return output_path
    except Exception as e:
        log(f"  🔴 DRY RUN: Lipsync fallback error: {e}")
    return None


# ==================== EXPAND SCRIPT ====================

def expand_script(script: str,
                 min_duration: float = 5.0,
                 max_duration: float = 15.0,
                 words_per_second: float = 2.5) -> str:
    """Ensure script produces TTS audio between min and max duration seconds.

    Uses word-count based estimation (~2.5 words/sec for Vietnamese).
    - If estimated < min_duration: add filler phrases to expand
    - If estimated > max_duration: truncate to fit within max_duration

    Args:
        script: Input script text
        min_duration: Minimum audio duration in seconds (default 5.0)
        max_duration: Maximum audio duration in seconds (default 15.0)
        words_per_second: TTS speed estimate (default 2.5 words/sec for Vietnamese)

    Returns:
        Expanded, truncated, or original script
    """
    words = script.split()
    estimated_duration = len(words) / words_per_second

    if estimated_duration >= min_duration and estimated_duration <= max_duration:
        log(f"  📝 Script OK: {len(words)} words, ~{estimated_duration:.1f}s")
        return script

    log(f"  📝 Script: {len(words)} words, ~{estimated_duration:.1f}s (min={min_duration}s, max={max_duration}s)")

    # If too LONG, truncate to max_duration
    if estimated_duration > max_duration:
        max_words = int(max_duration * words_per_second)
        truncated = ' '.join(words[:max_words])
        # Try to end at sentence boundary
        m = re.search(r'^(.*?)([.!?])\s*[.!?]?$', truncated.strip())
        if m:
            truncated = m.group(1) + m.group(2)
        log(f"  📝 Truncated to {len(truncated.split())} words, ~{len(truncated.split())/words_per_second:.1f}s")
        return truncated

    # If too SHORT, add filler phrases
    log(f"  📝 Expanding script...")

    fillers = [
        "Ừm... thật là",
        "Ôi... thú vị quá",
        "Bỗng nhiên... nào",
        "Này... nghe này",
        "Thật ra... mà",
        "Đẹp quá... nhỉ",
        "Vui ghê... hic",
        "Hay quá... đi",
        "Kỳ lạ... thật",
        "Lạ lắm... à"
    ]

    parts = re.split(r'([.!?])', script)
    sentences = []
    for i in range(0, len(parts) - 1, 2):
        sentences.append(parts[i] + parts[i + 1])
    if len(parts) % 2 == 1 and parts[-1].strip():
        sentences.append(parts[-1])

    current_script = script
    added_phrases = []
    filler_idx = 0

    while estimated_duration < min_duration:
        filler = fillers[filler_idx % len(fillers)]
        filler_idx += 1

        if len(sentences) > 1:
            insert_pos = min(len(sentences) // 2, len(sentences) - 1)
            sentences.insert(insert_pos, f" {filler}...")
            current_script = ' '.join(sentences)
        else:
            current_script = f"{filler}... {current_script}"

        words = current_script.split()
        estimated_duration = len(words) / words_per_second
        added_phrases.append(filler)

    log(f"  📝 Expanded: {len(words)} words, ~{estimated_duration:.1f}s (+{len(added_phrases)} phrases)")
    return current_script
