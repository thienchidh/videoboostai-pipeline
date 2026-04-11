#!/home/linuxbrew/.linuxbrew/bin/python3
"""
Bounce watermark: realistic physics-based bounce around screen edges.
Watermark moves in a direction, bounces off walls.
"""
import argparse
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import tempfile
import shutil
import math
import sys

FONT_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

def get_video_info(path):
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", 
         "stream=width,height,r_frame_rate:format=duration",
         "-of", "json", path],
        capture_output=True, text=True
    )
    info = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", 
                          "stream=width,height,r_frame_rate:format=duration",
                          "-of", "json", path], capture_output=True, text=True)
    import json
    data = json.loads(result.stdout)
    v = data["streams"][0]
    fps_parts = v["r_frame_rate"].split("/")
    fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) > 1 else float(fps_parts[0])
    w = int(v.get("width", 1080))
    h = int(v.get("height", 1920))
    dur = float(data["format"]["duration"])
    return w, h, fps, dur

def main():
    parser = argparse.ArgumentParser(description="Bouncing watermark video")
    parser.add_argument("input_video")
    parser.add_argument("output_video")
    parser.add_argument("--text", default="@NangSuatThongMinh")
    parser.add_argument("--font-size", type=int, default=28)
    parser.add_argument("--opacity", type=float, default=0.15)
    parser.add_argument("--speed", type=float, default=120.0)  # pixels per second
    parser.add_argument("--padding", type=int, default=15)  # from edges
    args = parser.parse_args()
    
    w, h, fps, duration = get_video_info(args.input_video)
    print(f"[bounce] Video: {w}x{h}, {fps:.1f}fps, {duration:.1f}s")
    
    # Load font
    try:
        font = ImageFont.truetype(FONT_PATH, args.font_size)
    except:
        font = ImageFont.load_default()
    
    # Measure text
    dummy = Image.new("RGBA", (1, 1))
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), args.text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    print(f"[bounce] Text: '{args.text}' size={tw}x{th}")
    
    # Physics bounds
    pad = args.padding
    min_x = pad
    max_x = w - tw - pad
    min_y = pad
    max_y = h - th - pad
    
    # Initial position (center)
    x = (w - tw) // 2
    y = (h - th) // 2
    
    # Random initial direction (normalized)
    angle = np.random.uniform(0, 2 * math.pi)
    vx = math.cos(angle) * args.speed  # pixels per second
    vy = math.sin(angle) * args.speed
    
    # Alpha
    alpha = int(255 * args.opacity)
    
    print(f"[bounce] Bouncing in {w}x{h} area, speed={args.speed} px/s")
    
    # Generate frames
    tmpdir = Path(tempfile.mkdtemp())
    num_frames = int(duration * fps)
    
    print(f"[bounce] Generating {num_frames} frames...")
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
        draw.text((int(x), int(y)), args.text, font=font, fill=(0, 0, 0, stroke_alpha))  # stroke
        draw.text((int(x), int(y)), args.text, font=font, fill=(255, 255, 255, alpha))  # fill
        
        frame.save(tmpdir / f"frame_{i+1:06d}.png")
        
        if (i + 1) % 100 == 0:
            print(f"[bounce] Frame {i+1}/{num_frames}")
    
    print(f"[bounce] Building video...")
    
    # Build video: video as base (0), watermark frames overlaid on top (1)
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
        "-crf", "20",
        "-c:a", "copy",
        "-shortest",
        args.output_video
    ], capture_output=True, text=True)
    
    shutil.rmtree(tmpdir)
    
    if result.returncode != 0:
        print(f"[bounce] Error: {result.stderr[-300:]}")
        return 1
    
    print(f"[bounce] Success: {args.output_video}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
