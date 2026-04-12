"""
modules/pipeline/pipeline_runner.py — Slimmed pipeline coordinator.

Replaces VideoPipelineV3's raw HTTP calls with proper PluginRegistry provider calls.
Orchestrates scene processing via SingleCharSceneProcessor / MultiCharSceneProcessor.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import db
from core.paths import PROJECT_ROOT, get_ffmpeg, get_ffprobe
from core.video_utils import (
    log,
    concat_videos,
    add_subtitles,
    add_background_music,
    get_video_duration,
    upload_file,
)
from core.plugins import get_provider, register_provider
from modules.pipeline.config_loader import PipelineConfig, ConfigLoader
from modules.pipeline.scene_processor import SingleCharSceneProcessor, MultiCharSceneProcessor

# Import providers to trigger registration
from modules.media.tts import MiniMaxTTSProvider, EdgeTTSProvider  # noqa: F401
from modules.media.image_gen import MiniMaxImageProvider, WaveSpeedImageProvider  # noqa: F401
from modules.media.lipsync import WaveSpeedLipsyncProvider, KieAIInfinitalkProvider  # noqa: F401
from modules.llm.minimax import MiniMaxLLMProvider  # noqa: F401


# Global flags (mirrored from video_pipeline_v3.py for CLI compatibility)
DRY_RUN = False
DRY_RUN_TTS = False
DRY_RUN_IMAGES = False
FORCE_START = False
UPLOAD_TO_SOCIALS = False


class VideoPipelineRunner:
    """Slimmed pipeline runner that wires PluginRegistry providers to scene processing.

    This replaces VideoPipelineV3's monolithic raw-HTTP calls with proper
    provider.generate() calls via PluginRegistry.
    """

    def __init__(self, config: PipelineConfig, dry_run: bool = False,
                 dry_run_tts: bool = False, dry_run_images: bool = False):
        """
        Args:
            config: Loaded PipelineConfig from ConfigLoader
            dry_run: Mock all API calls
            dry_run_tts: Mock TTS only
            dry_run_images: Mock image gen only
        """
        global DRY_RUN, DRY_RUN_TTS, DRY_RUN_IMAGES, FORCE_START
        DRY_RUN = dry_run
        DRY_RUN_TTS = dry_run_tts
        DRY_RUN_IMAGES = dry_run_images

        self.config = config
        self.timestamp = int(time.time())

        # Setup directories
        self.output_dir = config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        date_str = time.strftime("%Y%m%d")
        self.run_dir = self.output_dir / date_str / f"{self.timestamp}_{config.run_id}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir = self.run_dir / "final"
        self.media_dir.mkdir(parents=True, exist_ok=True)

        # Instantiate providers via PluginRegistry
        self.tts_provider = self._build_tts_provider()
        self.image_provider = self._build_image_provider()
        self.lipsync_provider = self._build_lipsync_provider()

        # Scene processors
        self.single_processor = SingleCharSceneProcessor(config, self.run_dir)
        self.multi_processor = MultiCharSceneProcessor(config, self.run_dir)

    # ---- Provider builders ----

    def _build_tts_provider(self):
        """Instantiate TTS provider via PluginRegistry."""
        tts_name = self.config.get("models", {}).get("tts", "minimax")
        provider_cls = get_provider("tts", tts_name)
        if provider_cls is None:
            raise ValueError(f"Unknown TTS provider: {tts_name}")

        if tts_name == "edge":
            return provider_cls(upload_func=lambda fp: upload_file(fp, self.config.wavespeed_base, self.config.wavespeed_key))
        return provider_cls(api_key=self.config.minimax_key)

    def _build_image_provider(self):
        """Instantiate image provider via PluginRegistry."""
        img_name = self.config.get("models", {}).get("image", "minimax")
        provider_cls = get_provider("image", img_name)
        if provider_cls is None:
            raise ValueError(f"Unknown image provider: {img_name}")
        return provider_cls(api_key=self.config.wavespeed_key)

    def _build_lipsync_provider(self):
        """Instantiate lipsync provider via PluginRegistry."""
        lipsync_name = self.config.lipsync_provider
        provider_cls = get_provider("lipsync", lipsync_name)
        if provider_cls is None:
            raise ValueError(f"Unknown lipsync provider: {lipsync_name}")

        upload_fn = lambda fp: upload_file(fp, self.config.wavespeed_base, self.config.wavespeed_key)
        if lipsync_name == "kieai":
            return provider_cls(
                api_key=self.config.kieai_key,
                webhook_key=self.config.kieai_webhook_key,
                upload_func=upload_fn,
            )
        return provider_cls(api_key=self.config.wavespeed_key, upload_func=upload_fn)

    # ---- TTS/Image/Lipsync wrappers (with dry-run support) ----

    def tts_generate(self, text: str, voice: str, speed: float, output_path: str):
        """Generate TTS audio, returning (path, timestamps)."""
        global DRY_RUN, DRY_RUN_TTS
        if DRY_RUN or DRY_RUN_TTS:
            from core.video_utils import mock_generate_tts
            return mock_generate_tts(text, voice, speed, output_path), None
        return self.tts_provider.generate(text, voice, speed, output_path)

    def image_generate(self, prompt: str, output_path: str):
        """Generate image."""
        global DRY_RUN, DRY_RUN_IMAGES
        if DRY_RUN or DRY_RUN_IMAGES:
            from core.video_utils import mock_generate_image
            return mock_generate_image(prompt, output_path)
        return self.image_provider.generate(prompt, output_path, aspect_ratio="9:16")

    def lipsync_generate(self, image_path: str, audio_path: str, output_path: str):
        """Generate lipsync video."""
        global DRY_RUN
        if DRY_RUN:
            from core.video_utils import mock_lipsync_video
            return mock_lipsync_video(image_path, audio_path, output_path)
        return self.lipsync_provider.generate(image_path, audio_path, output_path)

    # ---- Main run ----

    def run(self) -> Optional[str]:
        """Run the full pipeline."""
        global DRY_RUN, DRY_RUN_TTS, DRY_RUN_IMAGES, FORCE_START

        log(f"\n{'='*60}")
        log(f"🎬 VIDEO PIPELINE RUNNER")
        log(f"{'='*60}")

        scenes = self.config.get("scenes", [])
        log(f"📋 {len(scenes)} scenes loaded")

        if FORCE_START:
            log(f"🆕 Clearing previous scene cache...")
            for run_folder in self.output_dir.glob("*"):
                if not run_folder.is_dir():
                    continue
                for run_dir in run_folder.glob("*"):
                    if run_dir == self.run_dir:
                        continue
                    for scene_dir in run_dir.glob("scene_*"):
                        for f in scene_dir.glob("*.mp4"):
                            f.unlink(missing_ok=True)

        scene_videos = []
        scene_scripts = []

        for scene in scenes:
            scene_id = scene.get("id", 0)
            script = scene["script"]
            chars = scene.get("characters", [])
            scene_output = self.run_dir / f"scene_{scene_id}"

            log(f"\n{'='*40}")
            log(f"🎬 SCENE {scene_id}: {script[:50]}...")
            log(f"   Characters: {chars}")
            log(f"{'='*40}")

            scene_output.mkdir(exist_ok=True)

            # Skip if already processed
            existing = scene_output / "video_9x16.mp4"
            if existing.exists():
                log(f"  ✅ scene_{scene_id}: video_9x16.mp4 exists - skipping")
                scene_videos.append(str(existing))
                scene_scripts.append(script)
                continue

            if len(chars) == 1:
                video_path, timestamps = self.single_processor.process(
                    scene, scene_output,
                    tts_fn=self.tts_generate,
                    image_fn=self.image_generate,
                    lipsync_fn=self.lipsync_generate,
                )
                if video_path:
                    scene_videos.append(video_path)
                    scene_scripts.append(script)
            elif len(chars) == 2:
                video_path, timestamps = self.multi_processor.process(
                    scene, scene_output,
                    tts_fn=self.tts_generate,
                    image_fn=self.image_generate,
                    lipsync_fn=self.lipsync_generate,
                )
                if video_path:
                    scene_videos.append(video_path)
                    scene_scripts.append(script)

        if not scene_videos:
            log(f"\n❌ No scene videos generated")
            return None

        log(f"\n{'='*60}")
        log(f"🔗 CONCATENATING {len(scene_videos)} scenes...")
        log(f"{'='*60}")

        concat_output = self.run_dir / "video_concat.mp4"
        final_video = self.media_dir / f"video_v3_{self.timestamp}.mp4"

        if not self.concat_videos(scene_videos, str(concat_output)):
            log(f"\n❌ Pipeline failed at concat")
            return None

        shutil.copy(str(concat_output), str(final_video))
        log(f"  ✅ Concat copied: {final_video.stat().st_size/1024/1024:.1f}MB")

        # Build combined timestamps with offset
        combined_timestamps = []
        offset = 0.0
        for i, scene in enumerate(scenes):
            scene_id = scene.get("id", i + 1)
            scene_dir = self.run_dir / f"scene_{scene_id}"
            if i >= len(scene_videos):
                continue
            ts_file = scene_dir / "words_timestamps.json"
            if ts_file.exists():
                with open(ts_file, encoding="utf-8") as f:
                    timestamps = json.load(f)
                for t in timestamps:
                    combined_timestamps.append({
                        "word": t["word"],
                        "start": t["start"] + offset,
                        "end": t["end"] + offset
                    })
            vpath = scene_videos[i]
            dur = get_video_duration(vpath)
            offset += dur

        # Add watermark
        video_for_subtitles = str(final_video)
        wm_cfg = self.config.get("watermark", {})
        if wm_cfg.get("enable", False):
            watermarked_base = self.media_dir / f"video_v3_{self.timestamp}_watermarked_base.mp4"
            log(f"\n{'='*60}")
            log(f"💧 ADDING WATERMARK...")
            log(f"{'='*60}")
            wm_result = self._add_watermark(str(final_video), str(watermarked_base))
            if Path(wm_result).exists():
                video_for_subtitles = wm_result

        # Add subtitles
        full_script = " ".join(scene_scripts)
        subtitled_video = self.media_dir / f"video_v3_{self.timestamp}_subtitled.mp4"
        log(f"\n{'='*60}")
        log(f"📝 ADDING SUBTITLES...")
        log(f"{'='*60}")

        add_subtitles(video_for_subtitles, full_script, combined_timestamps or None,
                     str(subtitled_video), font_size=60, run_dir=self.run_dir)

        # Add background music
        music_enabled = self.config.get("background_music", {}).get("enable", True)
        final_output = str(subtitled_video)
        if music_enabled and Path(subtitled_video).exists():
            final_with_music = self.media_dir / f"video_v3_{self.timestamp}_with_music.mp4"
            log(f"\n{'='*60}")
            log(f"🎵 ADDING BACKGROUND MUSIC...")
            log(f"{'='*60}")
            music_result = add_background_music(str(subtitled_video), str(final_with_music))
            final_output = music_result if Path(music_result).exists() else str(subtitled_video)

        log(f"\n✅ DONE: {final_output}")
        return str(final_output)

    def concat_videos(self, video_paths: List[str], output_path: str) -> Optional[str]:
        """Concatenate scene videos."""
        return concat_videos(video_paths, output_path, run_dir=self.run_dir)

    def _add_watermark(self, video_path: str, output_path: str) -> str:
        """Add watermark (static or bounce mode)."""
        wm_cfg = self.config.get("watermark", {})
        if not wm_cfg.get("enable", False):
            return video_path

        text = wm_cfg.get("text", "@NangSuatThongMinh")
        font_size = wm_cfg.get("font_size", 60)
        opacity = wm_cfg.get("opacity", 0.15)
        motion = wm_cfg.get("motion", "bounce")

        log(f"  💧 Adding watermark: '{text}' (motion={motion})")

        if motion == "bounce":
            from core.paths import get_karaoke_python
            bounce_script = PROJECT_ROOT / "scripts" / "bounce_watermark.py"
            if bounce_script.exists():
                python = get_karaoke_python()
                font_path = self.config.get("fonts", {}).get("watermark") or ""
                cmd = [
                    python, str(bounce_script),
                    str(video_path), str(output_path),
                    "--text", text,
                    "--font", font_path,
                    "--font-size", str(font_size),
                    "--opacity", str(opacity),
                    "--speed", str(wm_cfg.get("bounce_speed", 120)),
                    "--padding", str(wm_cfg.get("bounce_padding", 15))
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                if result.returncode == 0 and Path(output_path).exists():
                    log(f"  ✅ Watermark added (bounce)")
                    return output_path
                else:
                    log(f"  ⚠️ Bounce watermark failed: {result.stderr[-300:] if result.stderr else 'unknown'}")

        # Static fallback
        return self._add_static_watermark(video_path, output_path, text, font_size, opacity)

    def _add_static_watermark(self, video_path, output_path, text, font_size, opacity):
        """Add static watermark using PIL + FFmpeg."""
        from core.paths import get_font_path
        from PIL import Image as PILImage, ImageFont, ImageDraw

        result = subprocess.run(
            [str(get_ffprobe()), "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(video_path)],
            capture_output=True, text=True
        )
        info = json.loads(result.stdout)
        vw = int(info['streams'][0]['width'])
        vh = int(info['streams'][0]['height'])

        scale = vh / 1920
        scaled_font_size = int(font_size * scale)

        try:
            font_path = self.config.get("fonts", {}).get("watermark") or get_font_path()
            fnt = ImageFont.truetype(font_path, scaled_font_size)
        except Exception:
            fnt = ImageFont.load_default()

        overlay = PILImage.new('RGBA', (vw, vh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        x = vw - int(280 * scale)
        y = vh - int(70 * scale)
        alpha = int(255 * opacity)
        draw.text((x, y), text, font=fnt, fill=(0, 0, 0, int(alpha * 0.8)))
        draw.text((x, y), text, font=fnt, fill=(255, 255, 255, alpha))

        overlay_path = self.run_dir / "watermark_overlay.png"
        overlay.save(str(overlay_path))

        tmp_wm = self.run_dir / "watermark_tmp.mp4"
        cmd = [
            str(get_ffmpeg()), "-y", "-i", str(video_path), "-i", str(overlay_path),
            "-filter_complex", "[0:v][1:v]overlay=0:0[out]",
            "-map", "[out]", "-map", "0:a?", "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "copy",
            str(tmp_wm)
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode == 0 and tmp_wm.exists():
            shutil.copy(tmp_wm, output_path)
            log(f"  ✅ Watermark added (static)")
            return output_path
        return video_path
