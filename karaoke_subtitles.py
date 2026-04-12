"""
karaoke_subtitles.py — Simple word-by-word karaoke subtitle burner.
Each word appears one at a time in a rounded pill at 85% from top.
"""
import argparse
import json
import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import tempfile
import shutil

# Auto-detect Python with PIL
import sys
LINUXBREW_PYTHON = "/home/linuxbrew/.linuxbrew/bin/python3"
def get_pil_python():
    script_dir = Path(__file__).parent
    venv_python = script_dir / ".venv" / "bin" / "python3"
    if venv_python.exists():
        return str(venv_python)
    if Path(LINUXBREW_PYTHON).exists():
        return LINUXBREW_PYTHON
    return sys.executable

FONT_PATH = os.environ.get("PIPELINE_FONT_PATH",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")
FONT_SIZE = 60
PILL_COLOR = (0, 0, 0, 200)   # Black with alpha
TEXT_COLOR = (255, 255, 0)     # Yellow
TEXT_DIM = (128, 128, 128)     # Dim gray
COLOR_FADE = 0.15              # Fade duration

def get_video_info(path):
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", 
         "stream=width,height,r_frame_rate:format=duration",
         "-of", "json", path],
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

def get_word_color_state(t, w_start, w_end, fade=0.15):
    """Returns (state, text_color, bg_alpha_frac)"""
    if t < w_start - fade:
        return None, None, 0
    elif t < w_start:
        frac = (t - (w_start - fade)) / fade
        return "FADE_IN", TEXT_COLOR, frac
    elif t < w_end - fade:
        return "HIGHLIGHTED", TEXT_COLOR, 1.0
    elif t < w_end:
        frac = (t - (w_end - fade)) / fade
        return "FADE_OUT", TEXT_COLOR, 1.0 - frac
    else:
        return None, None, 0

def render_frame(timestamps, t, w, h, font):
    """Render a single full-size frame with the active word in a rounded pill at 85%."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Find active word
    active_word = None
    for w_data in timestamps:
        state, _, _ = get_word_color_state(t, w_data["start"], w_data["end"])
        if state and state != "FADE_OUT":
            active_word = w_data
            break
    
    if not active_word:
        return img
    
    word = active_word["word"]
    state, text_col, bg_frac = get_word_color_state(t, active_word["start"], active_word["end"])
    
    # Get word size (accounting for PIL baseline)
    try:
        bbox = font.getbbox(word)
        ww = bbox[2] - bbox[0]
        wh = bbox[3] - bbox[1]
        baseline_offset = -bbox[1]
    except Exception:
        ww, wh = font.getsize(word)
        baseline_offset = wh * 0.2
    
    # Position at 85% from top - y is TEXT BASELINE
    x = (w - ww) // 2
    y = int(h * 0.85)  # baseline at 85% down
    
    # Pill is centered around text visual center
    if bg_frac > 0.01:
        pill_pad_x = 30
        pill_pad_y = 15
        visual_center_y = y - baseline_offset + wh // 2
        pill_y0 = visual_center_y - wh // 2 - pill_pad_y
        pill_y1 = visual_center_y + wh // 2 + pill_pad_y
        pill_x0 = x - pill_pad_x
        pill_x1 = x + ww + pill_pad_x
        alpha = int(220 * bg_frac)
        
        # Draw rounded rectangle
        r = 20
        draw.rectangle([pill_x0 + r, pill_y0, pill_x1 - r, pill_y1], fill=(0, 0, 0, alpha))
        draw.rectangle([pill_x0, pill_y0 + r, pill_x1, pill_y1 - r], fill=(0, 0, 0, alpha))
        draw.ellipse([pill_x0, pill_y0, pill_x0 + 2*r, pill_y0 + 2*r], fill=(0, 0, 0, alpha))
        draw.ellipse([pill_x1 - 2*r, pill_y0, pill_x1, pill_y0 + 2*r], fill=(0, 0, 0, alpha))
        draw.ellipse([pill_x0, pill_y1 - 2*r, pill_x0 + 2*r, pill_y1], fill=(0, 0, 0, alpha))
        draw.ellipse([pill_x1 - 2*r, pill_y1 - 2*r, pill_x1, pill_y1], fill=(0, 0, 0, alpha))
    
    # Draw text at baseline
    draw.text((x, y), word, font=font, fill=text_col + (255,))
    
    return img

def main():
    parser = argparse.ArgumentParser(description="Simple word-by-word karaoke subtitles")
    parser.add_argument("input_video")
    parser.add_argument("script_text")
    parser.add_argument("output_video")
    parser.add_argument("--timestamps", help="JSON file with word timestamps")
    parser.add_argument("--font", default=FONT_PATH)
    parser.add_argument("--font_size", type=int, default=FONT_SIZE)
    args = parser.parse_args()
    
    # Get video info
    w, h, fps, duration = get_video_info(args.input_video)
    print(f"[karaoke] Video: {w}x{h}, {fps:.1f}fps, {duration}s")
    
    # Load timestamps
    if args.timestamps and Path(args.timestamps).exists():
        with open(args.timestamps) as f:
            timestamps = json.load(f)
    else:
        # Generate simple timing from script
        with open(args.script_text) as f:
            script = f.read().strip()
        words = script.split()
        avg_duration = duration / len(words) if words else 1.0
        timestamps = []
        t = 0.0
        for word in words:
            timestamps.append({"word": word, "start": t, "end": min(t + avg_duration * 0.7, duration)})
            t += avg_duration
    
    print(f"[karaoke] Rendering karaoke subtitles ({len(timestamps)} words, {duration}s)...")
    
    # Load font
    try:
        font = ImageFont.truetype(args.font, args.font_size)
    except Exception:
        print(f"[karaoke] Warning: font {args.font} not found, using default")
        font = ImageFont.load_default()
    
    # Create temp directory for frames
    tmpdir = Path(tempfile.mkdtemp())

    # Generate full-size frames
    num_frames = int(duration * fps)
    print(f"[karaoke] Generating {num_frames} frames at {w}x{h}...")

    try:
        for i in range(num_frames):
            t = i / fps
            frame = render_frame(timestamps, t, w, h, font)
            frame.save(tmpdir / f"frame_{i+1:06d}.png")
            if (i + 1) % 50 == 0:
                print(f"[karaoke] Frame {i+1}/{num_frames}")

        print(f"[karaoke] Frames generated: {num_frames}")

        # Build video: video as base, karaoke frames overlaid on top
        print(f"[karaoke] Building video...")
        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", args.input_video,
            "-framerate", str(fps),
            "-i", str(tmpdir / "frame_%06d.png"),
            "-filter_complex", "[0:v][1:v]overlay=0:0[out]",
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "copy",
            "-shortest",
            args.output_video
        ], capture_output=True, text=True)

        if result.returncode != 0:
            print(f"[karaoke] Error: {result.stderr[:300]}")
            return 1

        print(f"[karaoke] Success: {args.output_video}")
    finally:
        shutil.rmtree(tmpdir)

    return 0
    return 0

if __name__ == "__main__":
    sys.exit(main())
