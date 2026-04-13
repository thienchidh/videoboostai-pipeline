"""
modules/pipeline/pipeline_runner.py — Slimmed pipeline coordinator.

Replaces VideoPipelineV3's raw HTTP calls with proper PluginRegistry provider calls.
Orchestrates scene processing via SingleCharSceneProcessor / MultiCharSceneProcessor.
"""

import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import db
from core.paths import PROJECT_ROOT
from core.video_utils import (
    log,
    concat_videos,
    add_subtitles,
    add_background_music,
    add_static_watermark,
    get_video_duration,
)
from core.plugins import get_provider, register_provider
from modules.pipeline.config_loader import PipelineConfig, ConfigLoader, MissingConfigError
from modules.pipeline.scene_processor import SingleCharSceneProcessor, MultiCharSceneProcessor

# Import providers to trigger registration
from modules.media.tts import MiniMaxTTSProvider, EdgeTTSProvider  # noqa: F401
from modules.media.image_gen import MiniMaxImageProvider, WaveSpeedImageProvider  # noqa: F401
from modules.media.lipsync import WaveSpeedLipsyncProvider, KieAIInfinitalkProvider  # noqa: F401
from modules.llm.minimax import MiniMaxLLMProvider  # noqa: F401


class VideoPipelineRunner:
    """Slimmed pipeline runner that wires PluginRegistry providers to scene processing.

    This replaces VideoPipelineV3's monolithic raw-HTTP calls with proper
    provider.generate() calls via PluginRegistry.
    """

    def __init__(self, config: PipelineConfig, dry_run: bool = False,
                 dry_run_tts: bool = False, dry_run_images: bool = False,
                 use_static_lipsync: bool = False, timestamp: Optional[int] = None):
        """
        Args:
            config: Loaded PipelineConfig from ConfigLoader
            dry_run: Mock all API calls
            dry_run_tts: Mock TTS only
            dry_run_images: Mock image gen only
            use_static_lipsync: If True, use static image + TTS audio instead of real lipsync
            timestamp: Optional timestamp (seconds since epoch). If None, will be generated.
                       Pass same timestamp as VideoPipelineV3 to ensure single folder creation.
        """
        self._dry_run = dry_run
        self._dry_run_tts = dry_run_tts
        self._dry_run_images = dry_run_images
        self._force_start = False  # CLI must call runner.run(force_start=True) to enable
        self._use_static_lipsync = use_static_lipsync

        self.config = config
        self.timestamp = timestamp if timestamp is not None else int(time.time())
        self.config.timestamp = self.timestamp  # sync to config for S3 key uniqueness

        # Setup directories
        self.output_dir = config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        date_str = time.strftime("%Y%m%d")
        self.run_dir = self.output_dir / date_str / f"{self.timestamp}_{config.run_id}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir = self.run_dir / "final"
        self.media_dir.mkdir(parents=True, exist_ok=True)

        # Configure database if database section is present in config
        db_cfg = self.config.data.get("storage", {}).get("database")
        if db_cfg:
            db.configure(db_cfg)

        # Configure S3 once (used by lipsync provider for media uploads)
        from modules.media.s3_uploader import configure as configure_s3
        configure_s3({
            'endpoint': self.config.s3_endpoint,
            'access_key': self.config.s3_access_key,
            'secret_key': self.config.s3_secret_key,
            'bucket': self.config.s3_bucket,
            'region': self.config.s3_region,
            'public_url_base': self.config.s3_public_url_base,
        })

        # Instantiate providers via PluginRegistry
        self.tts_provider = self._build_tts_provider()
        self.image_provider = self._build_image_provider()
        self.lipsync_provider = self._build_lipsync_provider()

        # Scene processors
        self.single_processor = SingleCharSceneProcessor(config, self.run_dir)
        self.multi_processor = MultiCharSceneProcessor(config, self.run_dir)

    # ---- Provider builders ----

    def _get_models(self) -> dict:
        """Get models config, checking generation.models first then default_models."""
        models = self.config.get_nested("generation", "models")
        if not models:
            models = self.config.get("default_models", {})
        return models or {}

    def _build_tts_provider(self):
        """Instantiate TTS provider via PluginRegistry."""
        models = self._get_models()
        tts_name = models.get("tts")
        if not tts_name:
            tts_fallback = self.config.get("generation", {}).get("tts", {}).get("provider")
            if tts_fallback:
                tts_name = tts_fallback
        if not tts_name:
            raise MissingConfigError("models.tts provider must be configured")
        provider_cls = get_provider("tts", tts_name)
        if provider_cls is None:
            raise ValueError(f"Unknown TTS provider: {tts_name}")

        if tts_name == "edge":
            return provider_cls(upload_func=None)
        return provider_cls(api_key=self.config.minimax_key)

    def _build_image_provider(self):
        """Instantiate image provider via PluginRegistry."""
        models = self._get_models()
        img_name = models.get("image") or self.config.get("generation", {}).get("image", {}).get("provider")
        if not img_name:
            raise MissingConfigError("models.image provider must be configured")
        provider_cls = get_provider("image", img_name)
        if provider_cls is None:
            raise ValueError(f"Unknown image provider: {img_name}")
        # Use minimax_key for MiniMax provider, wavespeed_key for WaveSpeed provider
        if img_name == "minimax":
            return provider_cls(api_key=self.config.minimax_key)
        return provider_cls(api_key=self.config.wavespeed_key)

    def _build_lipsync_provider(self):
        """Instantiate lipsync provider via PluginRegistry."""
        lipsync_name = self.config.lipsync_provider
        provider_cls = get_provider("lipsync", lipsync_name)
        if provider_cls is None:
            raise ValueError(f"Unknown lipsync provider: {lipsync_name}")

        # S3 is already configured in __init__; use timestamp-based prefix to avoid collisions
        from modules.media.s3_uploader import upload_file as s3_upload_file
        lipsync_prefix = f"lipsync/{self.config.timestamp}"
        upload_fn = lambda fp: s3_upload_file(fp, lipsync_prefix)

        if lipsync_name == "kieai":
            return provider_cls(
                api_key=self.config.kieai_key,
                upload_func=upload_fn,
            )
        return provider_cls(api_key=self.config.wavespeed_key, upload_func=upload_fn)

    # ---- TTS/Image/Lipsync wrappers (with dry-run support) ----

    def tts_generate(self, text: str, voice: str, speed: float, output_path: str):
        """Generate TTS audio, returning (path, timestamps)."""
        if self._dry_run or self._dry_run_tts:
            from core.video_utils import mock_generate_tts
            return mock_generate_tts(text, voice, speed, output_path), None
        return self.tts_provider.generate(text, voice, speed, output_path)

    def image_generate(self, prompt: str, output_path: str):
        """Generate image."""
        if self._dry_run or self._dry_run_images:
            from core.video_utils import mock_generate_image
            return mock_generate_image(prompt, output_path)
        return self.image_provider.generate(prompt, output_path, aspect_ratio="9:16")

    def lipsync_generate(self, image_path: str, audio_path: str, output_path: str,
                        scene_id: int = 0, prompt: str = None):
        """Generate lipsync video.

        Args:
            scene_id: scene number (used for unique S3 key)
            prompt: lipsync prompt from config
        """
        if self._dry_run:
            from core.video_utils import mock_lipsync_video
            return mock_lipsync_video(image_path, audio_path, output_path)

        # S3 upload with scene-specific prefix (upload_fn is per-call, thread-safe)
        from modules.media.s3_uploader import upload_file as s3_upload_file
        lipsync_prefix = f"lipsync/{self.config.timestamp}/scene_{scene_id}"
        upload_fn = lambda fp: s3_upload_file(fp, lipsync_prefix)

        # Check both 'generation.lipsync' (channel config style) and 'lipsync' (legacy)
        lipsync_cfg = self.config.get('generation', {}).get('lipsync') or self.config.get('lipsync')
        if not lipsync_cfg:
            raise MissingConfigError("config.lipsync or config.generation.lipsync is required")
        prompt_val = lipsync_cfg.get('prompt')
        if not prompt_val:
            raise MissingConfigError("config.lipsync.prompt is required")
        resolution_val = lipsync_cfg.get('resolution')
        if not resolution_val:
            raise MissingConfigError("config.lipsync.resolution is required")
        config = {
            'prompt': prompt_val,
            'resolution': resolution_val,
            'max_wait': lipsync_cfg.get('max_wait', 300),
        }

        return self.lipsync_provider.generate(image_path, audio_path, output_path, config=config, upload_func=upload_fn)

    def _make_lipsync_wrapper(self):
        """Create a lipsync wrapper that uses static video when USE_STATIC_LIPSYNC flag is set."""
        from core.video_utils import mock_lipsync_video
        real_lipsync = self.lipsync_generate
        use_static = self._use_static_lipsync

        def lipsync_wrapper(image_path, audio_path, output_path, scene_id=0, prompt=None):
            if use_static:
                log(f"  🖼️ USE_STATIC_LIPSYNC: creating static video from image (image={Path(image_path).name})")
                return mock_lipsync_video(image_path, audio_path, output_path)
            return real_lipsync(image_path, audio_path, output_path, scene_id=scene_id, prompt=prompt)
        return lipsync_wrapper

    # ---- Main run ----

    def run(self, force_start: bool = False) -> tuple[str, list]:
        """Run the full pipeline.

        Returns:
            Tuple of (final_video_path, combined_word_timestamps)
        """
        log(f"\n{'='*60}")
        log(f"🎬 VIDEO PIPELINE RUNNER")
        if self._use_static_lipsync:
            log(f"🖼️  USE_STATIC_LIPSYNC mode: using static image + TTS for video")
        log(f"{'='*60}")

        scenes = self.config.get("scenes")
        if scenes is None:
            raise MissingConfigError("config.scenes is required")
        if not scenes:
            raise MissingConfigError("config.scenes is empty — at least one scene is required")
        log(f"📋 {len(scenes)} scenes loaded")

        if force_start:
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

        # Build wrapped lipsync function
        lipsync_fn = self._make_lipsync_wrapper()

        # Helper function to process a single scene (for parallel execution)
        def process_single_scene(scene: Dict, scene_id: int, tts_text: str, chars: list, scene_output: Path):
            """Process a single scene. Returns (video_path, timestamps, tts_text) or None."""
            scene_output.mkdir(exist_ok=True)

            # Skip if already processed
            existing = scene_output / "video_9x16.mp4"
            if existing.exists():
                log(f"  ✅ scene_{scene_id}: video_9x16.mp4 exists - skipping")
                return (str(existing), [], tts_text)

            if len(chars) == 1:
                return self.single_processor.process(
                    scene, scene_output,
                    tts_fn=self.tts_generate,
                    image_fn=self.image_generate,
                    lipsync_fn=lipsync_fn,
                ) + (tts_text,)
            elif len(chars) == 2:
                return self.multi_processor.process(
                    scene, scene_output,
                    tts_fn=self.tts_generate,
                    image_fn=self.image_generate,
                    lipsync_fn=lipsync_fn,
                ) + (tts_text,)
            return None

        # Process scenes in parallel using ThreadPoolExecutor
        log(f"\n🔄 Processing {len(scenes)} scenes in parallel...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {}
            for scene in scenes:
                scene_id = scene.get("id", 0)
                tts_text = scene.get("tts", scene.get("script", ""))
                chars = scene.get("characters", [])
                scene_output = self.run_dir / f"scene_{scene_id}"

                log(f"\n{'='*40}")
                log(f"🎬 SCENE {scene_id}: {tts_text[:50]}...")
                log(f"   Characters: {chars}")
                log(f"{'='*40}")

                future = executor.submit(process_single_scene, scene, scene_id, tts_text, chars, scene_output)
                futures[future] = scene_id

            # Collect results as they complete (store by scene_id for ordering)
            results_by_scene = {}  # scene_id -> (video_path, timestamps, tts_text) or None
            for future in as_completed(futures):
                scene_id = futures[future]
                try:
                    result = future.result()
                    results_by_scene[scene_id] = result
                except Exception as e:
                    log(f"  ❌ Scene {scene_id} failed: {e}")
                    results_by_scene[scene_id] = None

            # Rebuild scene_videos and scene_scripts in original scene order
            for scene in scenes:
                scene_id = scene.get("id", 0)
                result = results_by_scene.get(scene_id)
                if result:
                    video_path, timestamps, tts_text = result
                    if video_path:
                        scene_videos.append(video_path)
                        scene_scripts.append(tts_text)

        if not scene_videos:
            log(f"\n❌ No scene videos generated")
            return None, []

        log(f"\n{'='*60}")
        log(f"🔗 CONCATENATING {len(scene_videos)} scenes...")
        log(f"{'='*60}")

        concat_output = self.run_dir / "video_concat.mp4"
        final_video = self.media_dir / f"video_v3_{self.timestamp}.mp4"

        if not self.concat_videos(scene_videos, str(concat_output)):
            log(f"\n❌ Pipeline failed at concat")
            return None, []

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
                     str(subtitled_video), font_size=self.config.get("subtitle", {}).get("font_size", 60), run_dir=self.run_dir)

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
        return str(final_output), combined_timestamps

    def concat_videos(self, video_paths: List[str], output_path: str) -> Optional[str]:
        """Concatenate scene videos."""
        return concat_videos(video_paths, output_path, run_dir=self.run_dir)

    def _add_watermark(self, video_path: str, output_path: str) -> str:
        """Add watermark (static or bounce mode)."""
        wm_cfg = self.config.get("watermark", {})
        if not wm_cfg.get("enable", False):
            return video_path

        text = wm_cfg.get("text")
        if not text:
            raise MissingConfigError("config.watermark.text is required when watermark is enabled")
        font_size = wm_cfg.get("font_size")
        if not font_size:
            raise MissingConfigError("config.watermark.font_size is required when watermark is enabled")
        opacity = wm_cfg.get("opacity")
        if not (isinstance(opacity, (int, float)) and opacity >= 0):
            raise MissingConfigError("config.watermark.opacity is required when watermark is enabled")
        motion = wm_cfg.get("motion", "bounce")

        log(f"  💧 Adding watermark: '{text}' (motion={motion})")

        if motion == "bounce":
            from scripts.bounce_watermark import add_bounce_watermark
            font_path = self.config.get("fonts", {}).get("watermark")
            if not font_path:
                raise MissingConfigError("config.fonts.watermark is required for bounce watermark")
            success = add_bounce_watermark(
                str(video_path),
                str(output_path),
                text=text,
                font=font_path,
                font_size=font_size,
                opacity=opacity,
                speed=wm_cfg.get("bounce_speed", 120),
                padding=wm_cfg.get("bounce_padding", 15),
            )
            if success:
                log(f"  ✅ Watermark added (bounce)")
                return output_path
            else:
                log(f"  ⚠️ Bounce watermark failed")

        # Static fallback
        font_path = self.config.get("fonts", {}).get("watermark")
        result = add_static_watermark(
            video_path, output_path,
            text=text, font_size=font_size, opacity=opacity,
            font_path=font_path, run_dir=self.run_dir
        )
        if result != video_path:
            log(f"  ✅ Watermark added (static)")
        return result
