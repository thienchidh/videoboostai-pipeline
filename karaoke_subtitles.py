#!/usr/bin/env python3
"""
karaoke_subtitles.py — Burn karaoke-style subtitles into video using word timestamps.
Used by video_pipeline_v3.py (via add_subtitles_with_timestamps).

Usage:
    python3 karaoke_subtitles.py <video> <script.txt> <output> [--font-size N] [--timestamps timestamps.json]

The timestamps JSON should be a list of: {"word": "...", "start": float, "end": float}
"""
import sys
import os
import json
import subprocess
import tempfile
import argparse
from pathlib import Path

# Try to use moviepy from linuxbrew
LINUXBREW_PYTHON = "/home/linuxbrew/.linuxbrew/bin/python3"
SYSTEM_PYTHON = sys.executable

def get_moviepy_python():
    if os.path.exists(LINUXBREW_PYTHON):
        return LINUXBREW_PYTHON
    return SYSTEM_PYTHON

def ms_to_ass(ms):
    """Convert milliseconds to ASS time format (H:MM:SS.CS)"""
    h = int(ms // 3600000)
    m = int((ms % 3600000) // 60000)
    s = int((ms % 60000) // 1000)
    cs = int((ms % 1000) // 10)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def create_ass_file(timestamps, output_path, font_size=80, width=1080, height=1920):
    """Create an ASS subtitle file from word timestamps."""
    
    # Color: yellow = &H00FFFF (ASS BGR format)
    # Position: centered, bottom marginv = 200 (below center)
    lines = [
        "[Script Info]",
        "PlayResX: " + str(width),
        "PlayResY: " + str(height),
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
        f"Style: Default,/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf,{font_size},&H00FFFF,&H00000000,-1,2,0,5,20,20,200",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Text",
    ]
    
    for w in timestamps:
        start = ms_to_ass(w["start"] * 1000)
        end = ms_to_ass(w["end"] * 1000)
        text = w["word"].replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def burn_with_ffmpeg_ass(input_path, output_path, ass_path):
    """Try ffmpeg with subtitles filter (requires libass)."""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", f"subtitles='{ass_path}'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "copy",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return result.returncode == 0, result.stderr

def burn_with_moviepy(input_path, output_path, timestamps_json_path, font_size=80):
    """Burn subtitles using moviepy (fallback when ffmpeg libass unavailable)."""
    python = get_moviepy_python()
    script = f"""
import sys
import json
from moviepy import VideoFileClip, TextClip, CompositeVideoClip

with open("{timestamps_json_path}") as f:
    timestamps = json.load(f)

clip = VideoFileClip("{input_path}")
W, H = clip.size

sub_clips = []
for w in timestamps:
    start = w["start"]
    duration = w["end"] - start
    text = w["word"]
    txt = TextClip(
        text=text,
        font="/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        font_size={font_size},
        color="yellow",
        stroke_color="black",
        stroke_width=2,
        duration=duration,
        size=(W - 80, None),
    )
    txt = txt.with_start(start)
    txt = txt.with_position(("center", 0.90), relative=True)
    sub_clips.append(txt)

final = CompositeVideoClip([clip] + sub_clips, size=(W, H))
final.write_videofile(
    "{output_path}",
    fps=24,
    codec="libx264",
    audio_codec="aac",
    threads=4,
    preset="fast",
    logger=None
)
print("DONE")
"""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(script)
        script_path = f.name
    
    result = subprocess.run([python, script_path], capture_output=True, text=True, timeout=600)
    os.unlink(script_path)
    return result.returncode == 0, result.stdout + result.stderr

def main():
    parser = argparse.ArgumentParser(description="Burn karaoke subtitles into video")
    parser.add_argument("video", help="Input video path")
    parser.add_argument("script", help="Script text file (unused, timestamps used)")
    parser.add_argument("output", help="Output video path")
    parser.add_argument("--font-size", type=int, default=80, help="Font size")
    parser.add_argument("--timestamps", help="Path to timestamps JSON file")
    args = parser.parse_args()

    # Load timestamps
    if args.timestamps and os.path.exists(args.timestamps):
        with open(args.timestamps) as f:
            timestamps = json.load(f)
    else:
        # Try to find timestamps in temp dir
        print("No timestamps file provided, creating dummy subtitles")
        timestamps = []

    # Get video dimensions
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", args.video],
        capture_output=True, text=True
    )
    try:
        info = json.loads(result.stdout)
        width = int(info["streams"][0]["width"])
        height = int(info["streams"][0]["height"])
    except:
        width, height = 1080, 1920

    # Create ASS file in temp dir
    fd, ass_path = tempfile.mkstemp(suffix=".ass")
    os.close(fd)
    create_ass_file(timestamps, ass_path, args.font_size, width, height)
    print(f"Created ASS file: {ass_path}")

    # Determine timestamps path for moviepy fallback
    timestamps_json_path = args.timestamps if args.timestamps else None

    # Try ffmpeg subtitles filter first
    print(f"Trying ffmpeg subtitles filter...")
    ok, err = burn_with_ffmpeg_ass(args.video, args.output, ass_path)
    
    if not ok:
        print(f"ffmpeg subtitles filter failed ({err[:100] if err else 'no error'}), trying moviepy...")
        if not timestamps_json_path:
            # Save timestamps to a temp JSON for moviepy
            fd2, ts_tmp = tempfile.mkstemp(suffix=".json")
            os.close(fd2)
            with open(ts_tmp, "w") as f:
                json.dump(timestamps, f)
            timestamps_json_path = ts_tmp
        ok, msg = burn_with_moviepy(args.video, args.output, timestamps_json_path, args.font_size)
        if not ok:
            print(f"moviepy failed: {msg[:200]}")
            # Final fallback: just copy video
            import shutil
            shutil.copy(args.video, args.output)
            print(f"Copied original video as fallback")
    
    try:
        os.unlink(ass_path)
    except:
        pass
    
    if os.path.exists(args.output):
        print(f"✅ Output: {args.output}")
        return 0
    return 1

if __name__ == "__main__":
    sys.exit(main())
