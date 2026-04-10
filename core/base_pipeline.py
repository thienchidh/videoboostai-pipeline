"""
core/base_pipeline.py — Abstract base class for video pipelines

Provides common methods for scene processing, concatenation,
watermark, and subtitle steps. DRY_RUN flags are shared here.
"""

import os
import sys
import time
import subprocess
import shutil
import tempfile
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import json

logger = logging.getLogger(__name__)

# ==================== DRY RUN FLAGS (shared global) ====================
DRY_RUN: bool = False
DRY_RUN_TTS: bool = False
DRY_RUN_IMAGES: bool = False


def get_karaoke_python() -> str:
    """Return python with moviepy installed."""
    LINUXBREW_PYTHON = "/home/linuxbrew/.linuxbrew/bin/python3"
    SYSTEM_PYTHON = "/usr/bin/python3"
    if os.path.exists(LINUXBREW_PYTHON):
        return LINUXBREW_PYTHON
    return SYSTEM_PYTHON


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ==================== DRY RUN MOCK FUNCTIONS ====================

def mock_generate_tts(text: str, voice: str = "female_voice",
                       speed: float = 1.0, output_path: Optional[str] = None) -> str:
    """Generate fake TTS audio using ffmpeg (sine tone)."""
    log(f"  🔴 DRY RUN: mock_generate_tts - using placeholder audio")
    if not output_path:
        output_path = f"/tmp/tts_dryrun_{int(time.time()*1000)}.mp3"

    estimated_duration = max(2.0, len(text) / 3.0)
    cmd = [
        "ffmpeg", "-y",
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
        "ffmpeg", "-y",
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


def mock_lipsync_video(image_path: str, audio_path: str, output_path: str) -> Optional[str]:
    """Generate fake lipsync video using ffmpeg (static image + audio)."""
    log(f"  🔴 DRY RUN: mock_lipsync_video - using placeholder video")

    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", audio_path],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip() or 5.0)

    cmd = [
        "ffmpeg", "-y",
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


# ==================== BASE PIPELINE ====================

class BasePipeline(ABC):
    """Abstract base class for video pipelines.

    Subclasses must implement:
    - _process_single_scene() — generate TTS, image, lipsync for one scene
    - get_character() — return character config dict by name
    - build_scene_prompt() — build image generation prompt for a scene
    """

    def __init__(self, config: Dict[str, Any], run_dir: Optional[Path] = None):
        """
        Args:
            config: Full merged config dict (from ConfigLoader)
            run_dir: Override run output directory
        """
        self.config = config
        self.timestamp = int(time.time())
        self.ws_dir = Path.home() / ".openclaw" / "workspace"
        self.media_dir = Path.home() / ".openclaw" / "media"

        if run_dir:
            self.run_dir = Path(run_dir)
        else:
            self.output_dir = self.ws_dir / "video_v3_output"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.run_dir = self.output_dir / f"run_{self.timestamp}"
            self.run_dir.mkdir(exist_ok=True)

        log(f"🎬 BasePipeline initialized — output: {self.run_dir}")

    # ---- Step tracking (resume logic) ----

    def _check_step(self, scene_id: int, step: str) -> bool:
        state_file = self.run_dir / f"scene_{scene_id}" / f".step_{step}"
        return state_file.exists()

    def _mark_step(self, scene_id: int, step: str) -> None:
        scene_dir = self.run_dir / f"scene_{scene_id}"
        scene_dir.mkdir(exist_ok=True)
        state_file = scene_dir / f".step_{step}"
        state_file.touch()
        log(f"  ✅ Step [{step}] marked complete")

    # ---- Scene processing (to be implemented by subclass) ----

    @abstractmethod
    def _process_single_scene(self, scene: Dict[str, Any]) -> Optional[str]:
        """Process a single scene end-to-end. Return path to 9:16 cropped video."""
        ...

    @abstractmethod
    def get_character(self, name: str) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def build_scene_prompt(self, scene: Dict[str, Any]) -> str:
        ...

    # ---- Orchestration ----

    def run_scene(self, scene_idx: int) -> Optional[str]:
        """Process one scene by index. Returns video path or None."""
        scenes = self.config.get("scenes", [])
        if scene_idx < 0 or scene_idx >= len(scenes):
            log(f"❌ Scene index {scene_idx} out of range")
            return None
        scene = scenes[scene_idx]
        return self._process_single_scene(scene)

    def concatenate_scenes(self, video_paths: List[str], output_path: str) -> Optional[str]:
        """Concatenate multiple scene videos into one."""
        if not video_paths:
            return None
        log(f"  🔗 Concatenating {len(video_paths)} videos...")

        list_file = self.run_dir / "concat_list.txt"
        with open(list_file, "w") as f:
            for path in video_paths:
                log(f"    + {Path(path).name}")
                f.write(f"file '{path}'\n")

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
                log(f"  ❌ Concat error: {result.stderr[:300]}")
                # Fallback: stream copy
                cmd_simple = [
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
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

    def apply_watermark(self, video_path: str, output_path: str) -> str:
        """Add watermark overlay to video using PIL + FFmpeg."""
        wm_cfg = self.config.get("watermark", {})
        if not wm_cfg.get("enable", False):
            log(f"  ℹ️ Watermark disabled")
            return video_path

        text = wm_cfg.get("text", "@NangSuatThongMinh")
        font_size = wm_cfg.get("font_size", 36)
        opacity = wm_cfg.get("opacity", 0.35)

        log(f"  💧 Adding watermark: '{text}' (opacity={opacity})")

        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "json", str(video_path)],
                capture_output=True, text=True
            )
            info = json.loads(result.stdout)
            vw = int(info['streams'][0]['width'])
            vh = int(info['streams'][0]['height'])

            scale = vh / 1920
            scaled_font_size = int(font_size * scale)

            from PIL import Image, ImageDraw, ImageFont
            overlay = Image.new('RGBA', (vw, vh), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            try:
                fnt = ImageFont.truetype('/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf', scaled_font_size)
            except Exception:
                fnt = ImageFont.load_default()

            x = vw - int(280 * scale)
            y = vh - int(70 * scale)
            alpha = int(255 * opacity)
            draw.text((x, y), text, font=fnt, fill=(0, 0, 0, int(alpha * 0.8)))
            draw.text((x, y), text, font=fnt, fill=(255, 255, 255, alpha))

            overlay_path = self.run_dir / "watermark_overlay.png"
            overlay.save(str(overlay_path))

            tmp_wm = self.run_dir / "watermark_tmp.mp4"
            cmd = [
                "ffmpeg", "-y", "-i", str(video_path), "-i", str(overlay_path),
                "-filter_complex", "[0:v][1:v]overlay=0:0[out]",
                "-map", "[out]", "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-c:a", "copy",
                str(tmp_wm)
            ]
            result2 = subprocess.run(cmd, capture_output=True, timeout=300)
            if result2.returncode == 0 and tmp_wm.exists():
                shutil.copy(tmp_wm, output_path)
                log(f"  ✅ Watermark added")
                return output_path
            else:
                log(f"  ⚠️ Watermark failed: {result2.stderr[:200] if result2.stderr else 'unknown'}")
        except Exception as e:
            log(f"  ⚠️ Watermark error: {e}")
        return video_path

    def add_subtitles(self, video_path: str, script_text: str,
                      timestamps: Optional[List[Dict]] = None,
                      output_path: Optional[str] = None) -> str:
        """Add karaoke subtitles to video using karaoke_subtitles.py."""
        log(f"  📝 Adding subtitles...")

        if output_path is None:
            output_path = video_path  # overwrite

        karaoke_script = Path(__file__).parent.parent / "karaoke_subtitles.py"
        if not karaoke_script.exists():
            karaoke_script = Path(__file__).parent / "karaoke_subtitles.py"
        if not karaoke_script.exists():
            log(f"  ⚠️ karaoke_subtitles.py not found, skipping subtitles")
            return video_path

        temp_dir = tempfile.mkdtemp()
        script_path = os.path.join(temp_dir, "script.txt")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_text)

        cmd = [
            get_karaoke_python(), str(karaoke_script),
            video_path,
            script_path,
            output_path,
            "--font-size", "80"
        ]
        if timestamps:
            ts_path = os.path.join(temp_dir, "timestamps.json")
            with open(ts_path, "w", encoding="utf-8") as f:
                json.dump(timestamps, f, ensure_ascii=False)
            cmd += ["--timestamps", ts_path]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                log(f"  ✅ Subtitles added: {output_path}")
                return output_path
            else:
                log(f"  ⚠️ Subtitle error (exit {result.returncode}): {result.stderr[:200]}")
        except Exception as e:
            log(f"  ⚠️ Subtitle exception: {e}")
        return video_path

    # ---- Utility methods ----

    def crop_to_9x16(self, input_video: str, output_video: str) -> Optional[str]:
        """Crop/convert any video to 9:16 vertical."""
        log(f"  📐 Crop to 9:16...")

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
                    log(f"  ❌ Crop error: {e}")
        return None

    def get_video_duration(self, video_path: str) -> float:
        """Get video duration in seconds using ffprobe."""
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True
        )
        return float(result.stdout.strip() or 0)
