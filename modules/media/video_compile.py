"""
modules/media/video_compile.py — Video compilation utilities

Provides:
- concat_videos(): concatenate multiple scene videos
- crop_to_9x16(): convert any video to 9:16 vertical
- add_subtitles(): karaoke subtitle wrapper
- add_background_music(): mix background music into video
- expand_script(): expand short scripts to minimum duration
"""

import os
import re
import shutil
import subprocess
import tempfile
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.paths import PROJECT_ROOT, get_karaoke_python
from core.base_pipeline import log as base_log

logger = logging.getLogger(__name__)


def log(msg: str) -> None:
    base_log(msg)


# ==================== CONCATENATION ====================

def concat_videos(video_paths: List[str], output_path: str,
                  run_dir: Optional[Path] = None,
                  use_filtergraph: bool = True) -> Optional[str]:
    """Concatenate multiple videos using filtergraph (proper A/V sync).

    Args:
        video_paths: list of input video paths
        output_path: destination path
        run_dir: working directory for temp files
        use_filtergraph: if True use filter_complex (proper sync), else stream copy
    """
    if not video_paths:
        return None

    if run_dir is None:
        run_dir = Path(output_path).parent

    logger.debug(f"Concatenating {len(video_paths)} videos...")
    list_file = run_dir / "concat_list.txt"
    with open(list_file, "w") as f:
        for path in video_paths:
            logger.debug(f"  + {Path(path).name}")
            f.write(f"file '{path}'\n")

    if use_filtergraph:
        filtergraph = ""
        for i in range(len(video_paths)):
            filtergraph += f"[{i}:v][{i}:a]"
        filtergraph += f"concat=n={len(video_paths)}:v=1:a=1[outv][outa]"

        input_args = []
        for path in video_paths:
            input_args += ["-i", path]

        cmd = ["ffmpeg", "-y"] + input_args + [
            "-filter_complex", filtergraph,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            output_path
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                logger.warning(f"  ❌ Concat filtergraph error: {result.stderr[:300]}")
            elif Path(output_path).exists():
                size = Path(output_path).stat().st_size
                logger.debug(f"  ✅ Concat done: {size/1024/1024:.1f}MB")
                return output_path
        except Exception as e:
            logger.warning(f"  ❌ Concat exception: {e}")

    # Fallback: stream copy
    cmd_simple = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", "-bsf:a", "aac_adtstoasc", output_path
    ]
    try:
        subprocess.run(cmd_simple, capture_output=True, timeout=600)
        if Path(output_path).exists():
            return output_path
    except Exception as e:
        logger.warning(f"  ❌ Concat fallback error: {e}")
    return None


# ==================== CROP TO 9:16 ====================

def crop_to_9x16(input_video: str, output_video: str) -> Optional[str]:
    """Crop/convert any video to 9:16 vertical using center crop."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", input_video],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        dims = result.stdout.strip().split(',')
        if len(dims) == 2:
            w, h = int(dims[0]), int(dims[1])
            input_ratio = w / h
            target_ratio = 9 / 16

            if input_ratio > target_ratio:
                new_w = int(h * (9 / 16))
                x_offset = (w - new_w) // 2
                crop_filter = f"crop={new_w}:{h}:{x_offset}:0,scale=1080:1920"
            elif input_ratio < target_ratio:
                new_h = int(w * (16 / 9))
                y_offset = (h - new_h) // 2
                crop_filter = f"crop={w}:{new_h}:0:{y_offset},scale=1080:1920"
            else:
                crop_filter = "scale=1080:1920"

            cmd = ["ffmpeg", "-i", input_video,
                   "-vf", crop_filter,
                   "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                   "-c:a", "aac", "-y", output_video]
            try:
                subprocess.run(cmd, capture_output=True, timeout=300)
                if Path(output_video).exists():
                    return output_video
            except Exception as e:
                logger.warning(f"Crop error: {e}")
    return None


# ==================== SCRIPT EXPANSION ====================

def expand_script(script: str, min_duration: float = 5.0, words_per_second: float = 2.5) -> str:
    """Ensure script produces TTS audio of at least min_duration seconds.

    Args:
        script: Input script text
        min_duration: Minimum audio duration in seconds
        words_per_second: TTS speed (default 2.5 words/sec for Vietnamese)
    """
    words = script.split()
    estimated_duration = len(words) / words_per_second
    if estimated_duration >= min_duration:
        return script

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
    filler_idx = 0
    while len(current_script.split()) / words_per_second < min_duration:
        filler = fillers[filler_idx % len(fillers)]
        filler_idx += 1
        if len(sentences) > 1:
            insert_pos = min(len(sentences) // 2, len(sentences) - 1)
            sentences.insert(insert_pos, f" {filler}...")
            current_script = ' '.join(sentences)
        else:
            current_script = f"{filler}... {current_script}"

    return current_script


# ==================== KARAOKE SUBTITLES ====================

def add_subtitles(video_path: str, script_text: str,
                  timestamps: Optional[List[Dict]] = None,
                  output_path: Optional[str] = None,
                  karaoke_script_path: Optional[str] = None,
                  font_size: int = 80,
                  run_dir: Optional[Path] = None) -> str:
    """Add karaoke subtitles to video using karaoke_subtitles.py."""
    if output_path is None:
        output_path = video_path

    if run_dir is None:
        run_dir = Path(video_path).parent

    karaoke_script = karaoke_script_path
    if not karaoke_script:
        karaoke_candidate = PROJECT_ROOT / "karaoke_subtitles.py"
        if karaoke_candidate.exists():
            karaoke_script = str(karaoke_candidate)

    if not karaoke_script:
        logger.warning("karaoke_subtitles.py not found, skipping subtitles")
        return video_path

    temp_dir = tempfile.mkdtemp()
    script_path = os.path.join(temp_dir, "script.txt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_text)

    cmd = [
        get_karaoke_python(), karaoke_script,
        video_path,
        script_path,
        output_path,
        "--font-size", str(font_size)
    ]
    if timestamps:
        ts_path = os.path.join(temp_dir, "timestamps.json")
        import json
        with open(ts_path, "w", encoding="utf-8") as f:
            json.dump(timestamps, f, ensure_ascii=False)
        cmd += ["--timestamps", ts_path]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            logger.debug(f"Subtitles added: {output_path}")
            return output_path
        else:
            logger.warning(f"Subtitle error (exit {result.returncode}): {result.stderr[:200]}")
    except Exception as e:
        logger.warning(f"Subtitle exception: {e}")
    return video_path


# ==================== BACKGROUND MUSIC ====================

def add_background_music(video_path: str,
                         output_path: str,
                         music_file: Optional[str] = None,
                         music_dir: Optional[str] = None,
                         volume: float = 0.15,
                         fade_duration: float = 2.0) -> str:
    """Add background music to video.

    Args:
        video_path: input video
        output_path: output video
        music_file: explicit music file path, or "random" / None for random
        music_dir: directory to pick random music from
        volume: music volume 0.0-1.0
        fade_duration: fade in/out seconds
    """
    if not music_file or music_file == "random":
        if music_dir is None:
            music_dir = str(PROJECT_ROOT / "music")
        music_path = Path(music_dir)
        if music_path.exists():
            mp3_files = [f for f in music_path.glob("*.mp3") + music_path.glob("*.ogg")
                         if f.stat().st_size > 500000]
            if mp3_files:
                music_file = str(random.choice(mp3_files))
                logger.debug(f"Random music: {Path(music_file).name}")
            else:
                logger.warning("No music files found, skipping")
                return video_path
        else:
            logger.warning(f"Music dir not found: {music_dir}, skipping")
            return video_path

    if not Path(music_file).exists():
        logger.warning(f"Music file not found: {music_file}, skipping")
        return video_path

    # Get video duration
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", video_path],
        capture_output=True, text=True
    )
    video_duration = float(result.stdout.strip() or 0)

    # Get music duration
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", music_file],
        capture_output=True, text=True
    )
    music_duration = float(result.stdout.strip() or 0)

    if music_duration <= 0:
        logger.warning("Could not get music duration, skipping")
        return video_path

    boost_factor = 2.0
    filter_str = (
        f"[1:a]aloop=loop=-1:size=0,atrim=0:{video_duration},"
        f"afade=t=in:st=0:d={fade_duration},"
        f"afade=t=out:st={video_duration-fade_duration}:d={fade_duration},"
        f"volume={volume}[music];"
        f"[0:a]volume={boost_factor}[narration];"
        f"[narration][music]amix=inputs=2:duration=first:dropout_transition=2,volume=1.5[a]"
    )

    cmd = [
        "ffmpeg", "-y", "-i", video_path, "-i", music_file,
        "-filter_complex", filter_str,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path
    ]
    try:
        result2 = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result2.returncode == 0 and Path(output_path).exists():
            logger.debug(f"Background music added: {Path(output_path).name}")
            return output_path
        else:
            logger.warning(f"Music mix error: {result2.stderr[:200] if result2.stderr else 'unknown'}")
    except Exception as e:
        logger.warning(f"Music mix exception: {e}")
    return video_path
