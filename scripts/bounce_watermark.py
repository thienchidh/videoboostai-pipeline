"""
Bounce watermark: realistic physics-based bounce around screen edges.
Watermark moves in a direction, bounces off walls.

Can be used as:
  - CLI: python bounce_watermark.py input.mp4 output.mp4 [options]
  - Module: from scripts.bounce_watermark import add_bounce_watermark
"""

import argparse
import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import tempfile
import shutil
import math
import sys

# Add project root to path for imports (only needed when running as script)
_SCRIPT_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.paths import get_font_path, get_ffmpeg, get_ffprobe
from core.video_utils import get_video_info

FONT_PATH = get_font_path()


def add_bounce_watermark(
    input_video: str,
    output_video: str,
    text: str = "@NangSuatThongMinh",
    font: str = None,
    font_size: int = 60,
    opacity: float = 0.15,
    speed: float = 120.0,
    padding: int = 15,
) -> bool:
    """
    Add bouncing watermark to video.

    Args:
        input_video: Path to input video
        output_video: Path to output video
        text: Watermark text
        font: Path to font file (default: system font)
        font_size: Font size
        opacity: Opacity (0.0-1.0)
        speed: Speed in pixels per second
        padding: Padding from screen edges

    Returns:
        True if successful, False otherwise
    """
    font = font or FONT_PATH

    w, h, fps, duration = get_video_info(input_video)
    print(f"[bounce] Video: {w}x{h}, {fps:.1f}fps, {duration:.1f}s")

    # Load font
    try:
        font_obj = ImageFont.truetype(font, font_size)
    except Exception:
        font_obj = ImageFont.load_default()

    # Measure text
    dummy = Image.new("RGBA", (1, 1))
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), text, font=font_obj)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    print(f"[bounce] Text: '{text}' size={tw}x{th}")

    # Physics bounds
    pad = padding
    min_x = pad
    max_x = w - tw - pad
    min_y = pad
    max_y = h - th - pad

    # Initial position (center)
    x = (w - tw) // 2
    y = (h - th) // 2

    # Random initial direction (normalized)
    angle = np.random.uniform(0, 2 * math.pi)
    vx = math.cos(angle) * speed
    vy = math.sin(angle) * speed

    # Alpha
    alpha = int(255 * opacity)

    print(f"[bounce] Bouncing in {w}x{h} area, speed={speed} px/s")

    # Generate frames
    tmpdir = Path(tempfile.mkdtemp())
    num_frames = int(duration * fps)

    print(f"[bounce] Generating {num_frames} frames...")
    try:
        for i in range(num_frames):
            t = i / fps

            # Move
            x += vx / fps
            y += vy / fps

            # Bounce off walls
            if x < min_x:
                x = min_x
                vx = abs(vx)
            elif x > max_x:
                x = max_x
                vx = -abs(vx)

            if y < min_y:
                y = min_y
                vy = abs(vy)
            elif y > max_y:
                y = max_y
                vy = -abs(vy)

            # Create frame
            frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(frame)

            # Draw text with stroke for readability
            stroke_alpha = int(alpha * 0.6)
            draw.text((int(x), int(y)), text, font=font_obj, fill=(0, 0, 0, stroke_alpha))
            draw.text((int(x), int(y)), text, font=font_obj, fill=(255, 255, 255, alpha))

            frame.save(tmpdir / f"frame_{i+1:06d}.png")

        print(f"[bounce] Building video...")

        # Build video: video as base (0), watermark frames overlaid on top (1)
        result = subprocess.run([
            str(get_ffmpeg()), "-y",
            "-i", input_video,
            "-framerate", str(fps),
            "-i", str(tmpdir / "frame_%06d.png"),
            "-filter_complex", "[0:v][1:v]overlay=0:0[out]",
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "copy",
            "-shortest",
            output_video
        ], capture_output=True, text=True)

        if result.returncode != 0:
            print(f"[bounce] Error: {result.stderr[-300:]}")
            return False

        print(f"[bounce] Success: {output_video}")
        return True

    finally:
        shutil.rmtree(tmpdir)


def main():
    parser = argparse.ArgumentParser(description="Bouncing watermark video")
    parser.add_argument("input_video")
    parser.add_argument("output_video")
    parser.add_argument("--text", default="@NangSuatThongMinh")
    parser.add_argument("--font", default=None)
    parser.add_argument("--font-size", type=int, default=60)
    parser.add_argument("--opacity", type=float, default=0.15)
    parser.add_argument("--speed", type=float, default=120.0)
    parser.add_argument("--padding", type=int, default=15)
    args = parser.parse_args()

    success = add_bounce_watermark(
        args.input_video,
        args.output_video,
        text=args.text,
        font=args.font,
        font_size=args.font_size,
        opacity=args.opacity,
        speed=args.speed,
        padding=args.padding,
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
