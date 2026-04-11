#!/usr/bin/env python3
"""
karaoke_subtitles.py — Burn karaoke-style pill subtitles into video.

Features:
- Rounded pill background (black, alpha ~200/255 ≈ 78% opacity)
- Yellow text (#FFFF00) with LiberationSans-Bold font, size 60
- Karaoke effect: word brightens from dim gray to yellow as it's spoken
- Words are grouped into lines for clean display

Usage:
    python3 karaoke_subtitles.py <video> <script.txt> <output> \
        [--font-size N] [--timestamps timestamps.json]

The timestamps JSON should be: [{"word": "...", "start": float, "end": float}]
"""
import sys
import os
from pathlib import Path
import json
import subprocess
import tempfile
import argparse
import shutil

# Auto-detect: check .venv in project root first, then linuxbrew, then system
LINUXBREW_PYTHON = "/home/linuxbrew/.linuxbrew/bin/python3"
SYSTEM_PYTHON = sys.executable

FONT_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

# Colors
PILL_COLOR = (0, 0, 0, 200)        # Black with alpha 200/255 ≈ 78%
TEXT_DIM = (128, 128, 128)         # Dim gray for inactive words
TEXT_HL = (255, 255, 0)            # Yellow for highlighted word

# Karaoke animation params
COLOR_FADE_DURATION = 0.15         # Seconds for text to brighten/dim
PILL_FADE_DURATION = 0.15          # Seconds for pill bg to appear/disappear


def get_moviepy_python():
    # Auto-detect Python with moviepy: .venv > linuxbrew > system
    # Check .venv in the same directory as this script (project root)
    script_dir = Path(__file__).parent
    venv_python = script_dir / ".venv" / "bin" / "python3"
    if venv_python.exists():
        return str(venv_python)
    if os.path.exists(LINUXBREW_PYTHON):
        return LINUXBREW_PYTHON
    return SYSTEM_PYTHON


def get_video_info(path):
    """Return (width, height, duration)"""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration", "-of", "json", path],
        capture_output=True, text=True
    )
    try:
        info = json.loads(result.stdout)
        streams = info.get("streams", [{}])
        s = streams[0]
        dur = (float(info.get("format", {}).get("duration", 0))
               or float(s.get("duration", 0)))
        return int(s.get("width", 1080)), int(s.get("height", 1920)), dur
    except Exception:
        return 1080, 1920, 10.0


def build_karaoke_frame(words_data, t, font_pil):
    """
    Build a karaoke frame image at time t using PIL.
    Returns a PIL Image (RGBA) of the minimal bounding box.
    """
    from PIL import Image, ImageDraw

    spacing_factor = 0.22
    padding_x = 30
    padding_y = 12
    radius = 18
    line_gap = 8

    def lerp_color(c1, c2, t_):
        t_ = max(0.0, min(1.0, t_))
        return tuple(int(a + (b - a) * t_) for a, b in zip(c1, c2))

    def rounded_rect(draw, bbox, r, fill):
        x0, y0, x1, y1 = bbox
        r = min(r, (x1 - x0) // 2, (y1 - y0) // 2)
        draw.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
        draw.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
        draw.ellipse([x0, y0, x0 + 2*r, y0 + 2*r], fill=fill)
        draw.ellipse([x1 - 2*r, y0, x1, y0 + 2*r], fill=fill)
        draw.ellipse([x0, y1 - 2*r, x0 + 2*r, y1], fill=fill)
        draw.ellipse([x1 - 2*r, y1 - 2*r, x1, y1], fill=fill)

    # Measure words
    word_sizes = []
    for w in words_data:
        dummy = Image.new("RGBA", (1, 1))
        d = ImageDraw.Draw(dummy)
        bbox = d.textbbox((0, 0), w["word"], font=font_pil)
        ww = bbox[2] - bbox[0]
        wh = bbox[3] - bbox[1]
        word_sizes.append((w["word"], ww, wh, w["start"], w["end"]))

    # Group into lines (~30 chars per line)
    lines = []
    current_line = []
    current_chars = 0
    for ws in word_sizes:
        word = ws[0]
        if current_line and current_chars + len(word) > 30:
            lines.append(current_line)
            current_line = [ws]
            current_chars = len(word) + 1
        else:
            current_line.append(ws)
            current_chars += len(word) + 1
    if current_line:
        lines.append(current_line)

    # Compute frame dimensions
    line_heights = [max(w[2] for w in line) for line in lines]
    line_text_widths = []
    for line in lines:
        tw = (sum(w[1] for w in line)
              + int(spacing_factor * sum(w[1] for w in line) / max(1, len(line))))
        line_text_widths.append(tw)

    total_w = max(line_text_widths) + 2 * padding_x if line_text_widths else 400
    total_h = sum(line_heights) + (len(lines) - 1) * line_gap + 2 * padding_y

    frame_img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(frame_img)

    y = padding_y
    for li, line in enumerate(lines):
        lh = line_heights[li]
        tw = line_text_widths[li]
        x = (total_w - tw) // 2

        for (word, ww, wh, w_start, w_end) in line:
            if t < w_start:
                text_col = TEXT_DIM
                bg_alpha_frac = 0.0
            elif t >= w_start and t < w_start + COLOR_FADE_DURATION:
                frac = (t - w_start) / COLOR_FADE_DURATION
                text_col = lerp_color(TEXT_DIM, TEXT_HL, frac)
                bg_alpha_frac = frac
            elif t >= w_start + COLOR_FADE_DURATION and t < w_end - PILL_FADE_DURATION:
                text_col = TEXT_HL
                bg_alpha_frac = 1.0
            elif t >= w_end - PILL_FADE_DURATION and t < w_end:
                frac = (w_end - t) / PILL_FADE_DURATION
                text_col = lerp_color(TEXT_HL, TEXT_DIM, 1 - frac)
                bg_alpha_frac = frac
            else:
                text_col = TEXT_DIM
                bg_alpha_frac = 0.0

            if bg_alpha_frac > 0.01:
                pill_x0 = x - 8
                pill_y0 = y + (lh - wh) // 2 - 4
                pill_x1 = x + ww + 8
                pill_y1 = pill_y0 + wh + 8
                alpha = int(200 * bg_alpha_frac)
                pill_fill = (PILL_COLOR[0], PILL_COLOR[1], PILL_COLOR[2], alpha)
                rounded_rect(draw, [pill_x0, pill_y0, pill_x1, pill_y1], radius, pill_fill)

            # Black stroke for readability
            stroke_col = (0, 0, 0, 180)
            for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1),
                           (0, -2), (0, 2), (-2, 0), (2, 0)]:
                draw.text((x + dx, y + (lh - wh) // 2 + dy),
                          word, font=font_pil, fill=stroke_col)
            draw.text((x, y + (lh - wh) // 2),
                      word, font=font_pil, fill=text_col + (255,))

            x += ww + int(spacing_factor * ww)

        y += lh + line_gap

    return frame_img


def burn_with_moviepy_karaoke(input_path, output_path, timestamps, font_size=60):
    """
    Burn karaoke pill subtitles using moviepy.
    Pre-renders key frames and concatenates for precise word timing.
    """
    python = get_moviepy_python()
    width, height, duration = get_video_info(input_path)

    # Save timestamps to temp JSON
    fd_ts, ts_path = tempfile.mkstemp(suffix=".json")
    os.close(fd_ts)
    with open(ts_path, "w", encoding="utf-8") as f:
        json.dump(timestamps, f, ensure_ascii=False)

    # Use str() template to avoid f-string brace escaping issues in embedded code
    script_template = """
import sys
import json
import os
from pathlib import Path
import shutil
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoFileClip, ImageClip, CompositeVideoClip
import numpy as np

TS_PATH = "{{ts_path}}"
FONT_PATH = "{{font_path}}"
FONT_SIZE = {{font_size}}
W, H = {{width}}, {{height}}
DURATION = {{duration}}
COLOR_FADE = {{color_fade}}
PILL_FADE = {{pill_fade}}
TEXT_DIM = {{text_dim}}
TEXT_HL = {{text_hl}}
PILL_COLOR = {{pill_color}}

def lerp_color(c1, c2, t_):
    t_ = max(0.0, min(1.0, t_))
    return tuple(int(a + (b - a) * t_) for a, b in zip(c1, c2))

def rounded_rect(draw, bbox, r, fill):
    x0, y0, x1, y1 = bbox
    r = min(r, (x1 - x0) // 2, (y1 - y0) // 2)
    draw.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
    draw.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
    draw.ellipse([x0, y0, x0 + 2*r, y0 + 2*r], fill=fill)
    draw.ellipse([x1 - 2*r, y0, x1, y0 + 2*r], fill=fill)
    draw.ellipse([x0, y1 - 2*r, x0 + 2*r, y1], fill=fill)
    draw.ellipse([x1 - 2*r, y1 - 2*r, x1, y1], fill=fill)

try:
    font_pil = ImageFont.truetype(FONT_PATH, FONT_SIZE)
except:
    font_pil = ImageFont.load_default()

with open(TS_PATH) as f:
    timestamps = json.load(f)

SPACING_FACTOR = 0.22
PADDING_X = 30
PADDING_Y = 12
RADIUS = 18
LINE_GAP = 8

def build_frame(words_data, t):
    word_sizes = []
    for w in words_data:
        dummy = Image.new("RGBA", (1, 1))
        d = ImageDraw.Draw(dummy)
        bbox = d.textbbox((0, 0), w["word"], font=font_pil)
        ww = bbox[2] - bbox[0]
        wh = bbox[3] - bbox[1]
        word_sizes.append((w["word"], ww, wh, w["start"], w["end"]))

    lines = []
    current_line = []
    current_chars = 0
    for ws in word_sizes:
        word = ws[0]
        if current_line and current_chars + len(word) > 30:
            lines.append(current_line)
            current_line = [ws]
            current_chars = len(word) + 1
        else:
            current_line.append(ws)
            current_chars += len(word) + 1
    if current_line:
        lines.append(current_line)

    line_heights = [max(w[2] for w in line) for line in lines]
    line_text_widths = []
    for line in lines:
        tw = (sum(w[1] for w in line)
              + int(SPACING_FACTOR * sum(w[1] for w in line) / max(1, len(line))))
        line_text_widths.append(tw)

    total_w = max(line_text_widths) + 2 * PADDING_X if line_text_widths else 400
    total_h = sum(line_heights) + (len(lines) - 1) * LINE_GAP + 2 * PADDING_Y

    frame_img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(frame_img)

    y = PADDING_Y
    for li, line in enumerate(lines):
        lh = line_heights[li]
        tw = line_text_widths[li]
        x = (total_w - tw) // 2

        for (word, ww, wh, w_start, w_end) in line:
            if t < w_start:
                text_col = TEXT_DIM
                bg_alpha_frac = 0.0
            elif t < w_start + COLOR_FADE:
                frac = (t - w_start) / COLOR_FADE
                text_col = lerp_color(TEXT_DIM, TEXT_HL, frac)
                bg_alpha_frac = frac
            elif t < w_end - PILL_FADE:
                text_col = TEXT_HL
                bg_alpha_frac = 1.0
            elif t >= w_end - PILL_FADE_DURATION and t < w_end:
                frac = (w_end - t) / PILL_FADE
                text_col = lerp_color(TEXT_HL, TEXT_DIM, 1 - frac)
                bg_alpha_frac = frac
            else:
                text_col = TEXT_DIM
                bg_alpha_frac = 0.0

            if bg_alpha_frac > 0.01:
                pill_x0 = x - 8
                pill_y0 = y + (lh - wh) // 2 - 4
                pill_x1 = x + ww + 8
                pill_y1 = pill_y0 + wh + 8
                alpha = int(200 * bg_alpha_frac)
                pill_fill = (PILL_COLOR[0], PILL_COLOR[1], PILL_COLOR[2], alpha)
                rounded_rect(draw, [pill_x0, pill_y0, pill_x1, pill_y1], RADIUS, pill_fill)

            stroke_col = (0, 0, 0, 180)
            for dx, dy in [(-1,-1),(-1,1),(1,-1),(1,1),(0,-2),(0,2),(-2,0),(2,0)]:
                draw.text((x + dx, y + (lh - wh) // 2 + dy), word, font=font_pil, fill=stroke_col)
            draw.text((x, y + (lh - wh) // 2), word, font=font_pil, fill=text_col + (255,))

            x += ww + int(SPACING_FACTOR * ww)

        y += lh + LINE_GAP

    return frame_img

# Collect key timestamps
key_times = set()
for w in timestamps:
    key_times.add(max(0.0, w["start"] - 0.01))
    key_times.add(w["start"])
    key_times.add(min(DURATION, w["end"]))
    if w["end"] - w["start"] > COLOR_FADE * 2:
        key_times.add(w["start"] + COLOR_FADE * 0.5)
        key_times.add(w["end"] - PILL_FADE * 0.5)

key_times = sorted(t for t in key_times if 0 <= t <= DURATION)
if not key_times:
    key_times = [0.0]
if key_times[-1] < DURATION:
    key_times.append(DURATION)

print("Karaoke: " + str(len(timestamps)) + " words, " + str(len(key_times)) + " keyframes, " + str(DURATION) + "s")

frame_cache = {}
for kt in key_times:
    frame_cache[kt] = build_frame(timestamps, kt)

clips = []
sorted_times = sorted(frame_cache.keys())
for i, kt in enumerate(sorted_times):
    img = frame_cache[kt].resize((W, H), Image.LANCZOS)
    arr = np.array(img)
    next_t = sorted_times[i+1] if i+1 < len(sorted_times) else kt + 0.5
    dur = max(0.04, next_t - kt)
    clip = ImageClip(arr).with_duration(dur)
    clips.append(clip)

if not clips:
    shutil.copy("{{input_path}}", "{{output_path}}")
    print("No clips - copied original")
    sys.exit(0)

video = VideoFileClip("{{input_path}}")
subtitle_concat = CompositeVideoClip(clips, size=(W, H)).with_duration(DURATION)
final = CompositeVideoClip([video, subtitle_concat.with_position("center")], size=(W, H))
final = final.with_duration(DURATION)

final.write_videofile(
    "{{output_path}}",
    fps=24,
    codec="libx264",
    audio_codec="aac",
    threads=4,
    preset="fast",
    logger=None
)
print("DONE")
"""

    # Fill template with actual values
    script = (script_template
              .replace("{{ts_path}}", ts_path)
              .replace("{{font_path}}", FONT_PATH)
              .replace("{{font_size}}", str(font_size))
              .replace("{{width}}", str(width))
              .replace("{{height}}", str(height))
              .replace("{{duration}}", str(duration))
              .replace("{{color_fade}}", str(COLOR_FADE_DURATION))
              .replace("{{pill_fade}}", str(PILL_FADE_DURATION))
              .replace("{{text_dim}}", str(TEXT_DIM))
              .replace("{{text_hl}}", str(TEXT_HL))
              .replace("{{pill_color}}", str(PILL_COLOR))
              .replace("{{input_path}}", input_path)
              .replace("{{output_path}}", output_path))

    fd, script_path = tempfile.mkstemp(suffix=".py")
    os.write(fd, script.encode("utf-8"))
    os.close(fd)

    print("[karaoke] Rendering karaoke subtitles (%d words, %.1fs)..." % (len(timestamps), duration))
    result = subprocess.run(
        [python, script_path],
        capture_output=True, text=True, timeout=900
    )
    os.unlink(script_path)
    try:
        os.unlink(ts_path)
    except:
        pass

    if result.returncode == 0:
        print("[karaoke] Success")
        return True
    print("[karaoke] Error: %s" % (result.stderr[-500:] if result.stderr else "no error"))
    return False


def burn_with_ffmpeg_ass(input_path, output_path, timestamps, font_size=60):
    """Fallback: use FFmpeg ASS subtitles filter (basic word-level, no pill)."""
    width, height, _ = get_video_info(input_path)

    def ms_to_ass(ms):
        h = int(ms // 3600000)
        m = int((ms % 3600000) // 60000)
        s = int((ms % 60000) // 1000)
        cs = int((ms % 1000) // 10)
        return "%d:%02d:%02d.%02d" % (h, m, s, cs)

    lines = [
        "[Script Info]",
        "PlayResX: %d" % width,
        "PlayResY: %d" % height,
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
        # Yellow text, black outline, centered bottom
        "Style: Karaoke,/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf,%d,&H00FFFF,&H00000000,-1,2,0,5,20,20,200" % font_size,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Text",
    ]

    for w in timestamps:
        start_str = ms_to_ass(int(w["start"] * 1000))
        end_str = ms_to_ass(int(w["end"] * 1000))
        text = w["word"].replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        lines.append("Dialogue: 0,%s,%s,Karaoke,,0,0,0,,%s" % (start_str, end_str, text))

    fd, ass_path = tempfile.mkstemp(suffix=".ass")
    os.close(fd)
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", "subtitles='%s'" % ass_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "copy",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    try:
        os.unlink(ass_path)
    except:
        pass

    if result.returncode == 0:
        print("[karaoke] FFmpeg ASS burn: success")
        return True
    print("[karaoke] FFmpeg ASS failed: %s" % (result.stderr[:200] if result.stderr else ""))
    return False


def main():
    parser = argparse.ArgumentParser(description="Burn karaoke pill subtitles into video")
    parser.add_argument("video", help="Input video path")
    parser.add_argument("script", help="Script text file")
    parser.add_argument("output", help="Output video path")
    parser.add_argument("--font-size", type=int, default=60,
                        help="Font size (default: 60)")
    parser.add_argument("--timestamps", help="Path to timestamps JSON file")
    args = parser.parse_args()

    # Load timestamps
    if args.timestamps and os.path.exists(args.timestamps):
        with open(args.timestamps) as f:
            timestamps = json.load(f)
    else:
        print("[karaoke] No timestamps file - copying original")
        shutil.copy(args.video, args.output)
        return 0

    if not timestamps:
        print("[karaoke] Empty timestamps - copying original")
        shutil.copy(args.video, args.output)
        return 0

    # Try moviepy (full karaoke + pill effect)
    ok = burn_with_moviepy_karaoke(args.video, args.output, timestamps, args.font_size)

    if not ok:
        # Fallback to FFmpeg ASS
        ok = burn_with_ffmpeg_ass(args.video, args.output, timestamps, args.font_size)

    if not ok:
        shutil.copy(args.video, args.output)
        print("[karaoke] Fallback: copied original")
        return 1

    if os.path.exists(args.output):
        print("[karaoke] Output: %s" % args.output)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
