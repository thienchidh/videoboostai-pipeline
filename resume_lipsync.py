"""
Resume pipeline from lipsync step — NO API calls.

Usage:
    python resume_lipsync.py

Replaces scene_1 and scene_2 video_raw.mp4 with downloaded lipsync videos,
then re-runs: crop → concat → watermark → subtitles → BGM → bounce_watermark.
"""

import sys
import json
import shutil
import tempfile
import subprocess
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).parent))

from core.video_utils import crop_to_9x16, add_subtitles, add_background_music, add_static_watermark
from core.paths import get_ffmpeg, get_ffprobe
from scripts.bounce_watermark import add_bounce_watermark

# ============ CONFIG ============

RUN_DIR = Path(__file__).parent / "output" / "nang_suat_thong_minh" / "productivity-explainer-education-rba_1776348750"

LIPSYNC_VIDEOS = {
    "scene_1": "https://tempfile.aiquickdraw.com/h/2cfa4bbed604071c1b25cf5596bc6d29_1776349464.mp4",
    "scene_2": "https://tempfile.aiquickdraw.com/h/d916c9868836c5101a51777d4e7827e9_1776349612.mp4",
}

WATERMARK_TEXT = "@NangSuatThongMinh"
BGM_VOLUME = 0.15
BGM_FADE = 2.0

# ============================================================


def log(msg):
    print(f"  {msg}")


def download_file(url: str, output_path: Path) -> bool:
    """Download file from URL to output_path. No API key needed."""
    log(f"Downloading {url}")
    log(f"  -> {output_path}")
    try:
        req = Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        with urlopen(req, timeout=60) as response:
            data = response.read()
        with open(output_path, "wb") as f:
            f.write(data)
        size_mb = len(data) / 1024 / 1024
        log(f"  ✅ Downloaded {size_mb:.1f}MB")
        return True
    except URLError as e:
        log(f"  ❌ Download failed: {e}")
        return False


def crop_scene(scene_name: str) -> bool:
    """Crop scene_raw.mp4 → scene_9x16.mp4 (overwrite)."""
    scene_dir = RUN_DIR / scene_name
    raw = scene_dir / "video_raw.mp4"
    cropped = scene_dir / "video_9x16.mp4"
    log(f"Cropping {scene_name}: {raw} → {cropped}")
    result = crop_to_9x16(str(raw), str(cropped))
    if result:
        size_mb = cropped.stat().st_size / 1024 / 1024
        log(f"  ✅ Crop done: {size_mb:.1f}MB")
        return True
    else:
        log(f"  ❌ Crop failed")
        return False


def concat_scenes() -> Path:
    """Concat scene_1 + scene_2 + scene_3 → video_concat.mp4."""
    concat_list = RUN_DIR / "concat_list.txt"
    concat_out = RUN_DIR / "video_concat.mp4"

    # Write concat list (Windows paths with escaped backslashes for ffmpeg)
    with open(concat_list, "w", encoding="utf-8") as f:
        for scene in ["scene_1", "scene_2", "scene_3"]:
            video = RUN_DIR / scene / "video_9x16.mp4"
            # ffmpeg concat demuxer needs literal backslash on Windows
            path_str = str(video).replace("\\", "\\\\")
            f.write(f"file '{path_str}'\n")

    log(f"Concatenating 3 scenes → {concat_out}")
    cmd = [
        str(get_ffmpeg()), "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(concat_out),
    ]
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode == 0 and concat_out.exists():
        size_mb = concat_out.stat().st_size / 1024 / 1024
        log(f"  ✅ Concat done: {size_mb:.1f}MB")
        return concat_out
    else:
        log(f"  ❌ Concat failed: {result.stderr[:300] if result.stderr else 'unknown'}")
        return None


def get_full_script() -> str:
    """Concatenate all scene scripts for subtitle generation."""
    parts = []
    for scene in ["scene_1", "scene_2", "scene_3"]:
        meta_path = RUN_DIR / scene / "scene_meta.json"
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        parts.append(meta.get("script", ""))
    return " ".join(parts)


def get_all_timestamps():
    """Collect timestamps from all 3 scenes."""
    all_ts = []
    for scene in ["scene_1", "scene_2", "scene_3"]:
        ts_path = RUN_DIR / scene / "words_timestamps.json"
        if ts_path.exists():
            with open(ts_path, encoding="utf-8") as f:
                ts = json.load(f)
                if ts:
                    all_ts.extend(ts)
    return all_ts


def run():
    print("=" * 60)
    print("RESUME: Lipsync → Final Video (NO API calls)")
    print("=" * 60)
    print(f"Run dir: {RUN_DIR}")
    print()

    # ============================================================
    # STEP 1: Download lipsync videos → scene_1/ and scene_2/
    # ============================================================
    print("[1/6] Downloading lipsync videos...")
    for scene_name, url in LIPSYNC_VIDEOS.items():
        raw_path = RUN_DIR / scene_name / "video_raw.mp4"
        ok = download_file(url, raw_path)
        if not ok:
            print(f"  ⚠️  Download failed for {scene_name}, keeping existing video_raw.mp4")

    print()

    # ============================================================
    # STEP 2: Crop scene_1 and scene_2 to 9x16
    # ============================================================
    print("[2/6] Cropping scenes to 9:16...")
    crop_scene("scene_1")
    crop_scene("scene_2")
    # scene_3 already has static video_9x16.mp4 — no change needed
    print()

    # ============================================================
    # STEP 3: Concat 3 scenes
    # ============================================================
    print("[3/6] Concatenating scenes...")
    concat_out = concat_scenes()
    if not concat_out:
        print("❌ Concat failed, aborting.")
        return
    print()

    # ============================================================
    # STEP 4: Static watermark
    # ============================================================
    print("[4/6] Adding static watermark...")
    wm_base = RUN_DIR / "final" / "video_v3_1776348750_watermarked_base.mp4"
    wm_base.parent.mkdir(parents=True, exist_ok=True)
    result_wm = add_static_watermark(
        str(concat_out),
        str(wm_base),
        text=WATERMARK_TEXT,
        font_size=30,
        opacity=0.15,
        run_dir=wm_base.parent,
    )
    print(f"  Watermark: {wm_base}")
    print()

    # ============================================================
    # STEP 5: Karaoke subtitles
    # ============================================================
    print("[5/6] Adding karaoke subtitles...")
    srt_out = RUN_DIR / "final" / "subtitles_v3_1776348750.srt"
    full_script = get_full_script()
    all_ts = get_all_timestamps()

    subtitled = RUN_DIR / "final" / "video_v3_1776348750_subtitled.mp4"
    result_sub = add_subtitles(
        str(wm_base),
        script_text=full_script,
        timestamps=all_ts if all_ts else None,
        output_path=str(subtitled),
        font_size=60,
        run_dir=subtitled.parent,
    )
    print(f"  Subtitled: {subtitled}")
    print()

    # ============================================================
    # STEP 6: BGM + Bounce watermark → final
    # ============================================================
    print("[6/6] Adding BGM and bounce watermark...")
    music_dir = str(Path(__file__).parent / "music")

    tmp_with_bgm = subtitled.parent / "tmp_with_bgm.mp4"
    bgm_result = add_background_music(
        str(subtitled),
        str(tmp_with_bgm),
        music_file="random",
        music_dir=music_dir,
        volume=BGM_VOLUME,
        fade_duration=BGM_FADE,
    )

    final_out = RUN_DIR / "final" / "video_v3_1776348750.mp4"
    final_out.parent.mkdir(parents=True, exist_ok=True)

    bounce_ok = add_bounce_watermark(
        str(tmp_with_bgm) if Path(tmp_with_bgm).exists() else str(subtitled),
        str(final_out),
        text=WATERMARK_TEXT,
        font_size=60,
        opacity=0.15,
        speed=80.0,
        padding=20,
    )

    # Cleanup tmp
    if tmp_with_bgm.exists():
        tmp_with_bgm.unlink()

    if bounce_ok:
        size_mb = final_out.stat().st_size / 1024 / 1024
        print(f"  ✅ Final video done: {final_out} ({size_mb:.1f}MB)")
    else:
        print(f"  ⚠️ Bounce watermark failed — final still at {subtitled}")

    print()
    print("=" * 60)
    print("DONE!")
    print(f"  Final: {final_out}")
    print("=" * 60)


if __name__ == "__main__":
    run()
