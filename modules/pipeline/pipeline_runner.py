"""
modules/pipeline/pipeline_runner.py — Slimmed pipeline coordinator.

Replaces VideoPipelineV3's raw HTTP calls with proper PluginRegistry provider calls.
Orchestrates scene processing via SingleCharSceneProcessor.
"""

import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

import db
from modules.media.s3_uploader import configure as configure_s3, upload_file as s3_upload_file
from core.video_utils import (
    log,
    concat_videos,
    add_subtitles,
    add_background_music,
    add_static_watermark,
    get_video_duration,
    mock_generate_tts,
    mock_generate_image,
    create_static_video_with_audio,
)
from core.plugins import get_provider
from core.paths import PROJECT_ROOT
from modules.pipeline.config import PipelineContext
from modules.pipeline.exceptions import SceneDurationError
from modules.pipeline.scene_processor import SingleCharSceneProcessor

# Import observer (lazy to avoid circular import)
from modules.ops.pipeline_observer import PipelineObserver, register_run, update_run_progress

# Import providers to trigger PluginRegistry registration (side-effect).
# Also needed by tests that reference pipeline_runner.MiniMaxMusicProvider etc.
from modules.media.tts import MiniMaxTTSProvider, EdgeTTSProvider  # noqa: F401
from modules.media.image_gen import MiniMaxImageProvider, WaveSpeedImageProvider, KieImageProvider  # noqa: F401
from modules.media.lipsync import WaveSpeedLipsyncProvider, WaveSpeedMultiTalkProvider, KieAIInfinitalkProvider  # noqa: F401
from modules.media.music_gen import MiniMaxMusicProvider  # noqa: F401
from modules.llm.minimax import MiniMaxLLMProvider  # noqa: F401


class VideoPipelineRunner:
    """Slimmed pipeline runner that wires PluginRegistry providers to scene processing.

    This replaces VideoPipelineV3's monolithic raw-HTTP calls with proper
    provider.generate() calls via PluginRegistry.
    """

    def __init__(self, ctx: PipelineContext, dry_run: bool = False,
                 dry_run_tts: bool = False, dry_run_images: bool = False,
                 use_static_lipsync: bool = False, timestamp: Optional[int] = None,
                 resume: bool = False):
        """
        Args:
            ctx: PipelineContext with loaded technical, channel, and scenario configs
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
        self._resume = resume
        self.ctx = ctx

        self.timestamp = timestamp if timestamp is not None else int(time.time())

        # Read output_dir and max_workers from config
        self.output_dir = PROJECT_ROOT / (ctx.technical.storage.output_dir if ctx.technical.storage else "output")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir = self.output_dir / ctx.channel_id / f"{ctx.scenario.slug}_{self.timestamp}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir = self.run_dir / "final"
        self.media_dir.mkdir(parents=True, exist_ok=True)

        # Read max_workers from config
        self.max_workers = ctx.technical.generation.parallel_scene_processing.max_workers

        # Configure database if database section is present in config
        db_cfg = ctx.technical.storage.database
        if db_cfg:
            from modules.pipeline.db_config import DatabaseConnectionConfig
            db.configure(DatabaseConnectionConfig(
                host=db_cfg.host,
                port=db_cfg.port,
                name=db_cfg.name,
                user=db_cfg.user,
                password=db_cfg.password,
            ))

        # Init DB and create run record
        db.init_db()
        project_name = ctx.scenario.title if ctx.scenario else "default"
        project_id = db.get_or_create_project(project_name)
        self.run_id = db.start_video_run(project_id, str(ctx.channel_id))
        self._project_id = project_id

        # Wire pipeline observer if enabled
        self._observer = None
        obs_cfg = ctx.technical.observer
        if obs_cfg and obs_cfg.enabled:
            self._observer = PipelineObserver(host=obs_cfg.host, port=obs_cfg.port)
            self._observer.start()
            register_run(self.run_id)
            log(f"🌐 Pipeline observer started on {obs_cfg.host}:{obs_cfg.port}")

        # Configure S3 once (used by lipsync provider for media uploads)
        s3 = ctx.technical.storage.s3
        configure_s3(s3)

        # Instantiate providers via PluginRegistry
        self.tts_provider = self._build_tts_provider()
        self.image_provider = self._build_image_provider()
        self.lipsync_provider = self._build_lipsync_provider()
        self.music_provider = self._build_music_provider()

        # Scene processors
        self.single_processor = SingleCharSceneProcessor(ctx, self.run_dir, resume=self._resume)

    # ---- Provider builders ----

    def _build_tts_provider(self):
        """Instantiate TTS provider via PluginRegistry."""
        tts_name = self.ctx.channel.generation.models.tts
        if not tts_name:
            raise ValueError("models.tts provider must be configured")
        provider_cls = get_provider("tts", tts_name)
        if provider_cls is None:
            raise ValueError(f"Unknown TTS provider: {tts_name}")

        if tts_name == "edge":
            return provider_cls(config=self.ctx.technical, upload_func=None)
        return provider_cls(config=self.ctx.technical, api_key=self.ctx.technical.api_keys.minimax)

    def _build_image_provider(self):
        """Instantiate image provider via PluginRegistry."""
        img_name = self.ctx.channel.generation.models.image
        if not img_name:
            raise ValueError("models.image provider must be configured")
        provider_cls = get_provider("image", img_name)
        if provider_cls is None:
            raise ValueError(f"Unknown image provider: {img_name}")
        # Use minimax_key for MiniMax, kie_key for Kie, wavespeed_key for WaveSpeed
        if img_name == "minimax":
            return provider_cls(config=self.ctx.technical, api_key=self.ctx.technical.api_keys.minimax)
        if img_name == "kieai":
            return provider_cls(config=self.ctx.technical, api_key=self.ctx.technical.api_keys.kie_ai)
        return provider_cls(config=self.ctx.technical, api_key=self.ctx.technical.api_keys.wavespeed)

    def _build_lipsync_provider(self):
        """Instantiate lipsync provider via PluginRegistry."""
        # Prefer channel lipsync config, fall back to technical
        if self.ctx.channel and self.ctx.channel.lipsync:
            lipsync_name = self.ctx.channel.lipsync.provider
        elif self.ctx.technical and self.ctx.technical.generation and self.ctx.technical.generation.lipsync:
            lipsync_name = self.ctx.technical.generation.lipsync.provider
        else:
            lipsync_name = "kieai"  # Default if nothing configured

        provider_cls = get_provider("lipsync", lipsync_name)
        if provider_cls is None:
            raise ValueError(f"Unknown lipsync provider: {lipsync_name}")

        # S3 is already configured in __init__; use timestamp-based prefix to avoid collisions
        lipsync_prefix = f"lipsync/{self.timestamp}"
        upload_fn = lambda fp: s3_upload_file(fp, lipsync_prefix)

        if lipsync_name == "kieai":
            return provider_cls(
                config=self.ctx.technical,
                api_key=self.ctx.technical.api_keys.kie_ai,
                upload_func=upload_fn,
            )
        return provider_cls(config=self.ctx.technical, api_key=self.ctx.technical.api_keys.wavespeed, upload_func=upload_fn)

    def _build_music_provider(self):
        """Instantiate music provider via PluginRegistry."""
        # Use minimax_key for music generation
        return MiniMaxMusicProvider(api_key=self.ctx.technical.api_keys.minimax)

    # ---- TTS/Image/Lipsync wrappers (with dry-run support) ----

    def tts_generate(self, text: str, voice: str, speed: float, output_path: str):
        """Generate TTS audio, returning (path, timestamps)."""
        if self._dry_run or self._dry_run_tts:
            return mock_generate_tts(text, voice, speed, output_path), None
        return self.tts_provider.generate(text, voice, speed, output_path)

    def image_generate(self, prompt: str, output_path: str):
        """Generate image with primary provider, then fallback providers from config."""
        if self._dry_run or self._dry_run_images:
            return mock_generate_image(prompt, output_path)

        # Get aspect_ratio from channel config (required)
        aspect_ratio = self.ctx.channel.video.aspect_ratio if self.ctx.channel.video else "9:16"
        if not aspect_ratio:
            raise ValueError("channel config video.aspect_ratio is required")

        # Primary provider
        try:
            result = self.image_provider.generate(prompt, output_path, aspect_ratio=aspect_ratio)
        except Exception as e:
            log(f"  ⚠️ Image provider raised: {type(e).__name__}: {e}")
            result = None

        if result:
            return result

        # Fallback: read from ctx.technical.generation.image.fallback_providers
        fallback_providers = []
        if self.ctx.technical and self.ctx.technical.generation and self.ctx.technical.generation.image:
            fallback_providers = self.ctx.technical.generation.image.fallback_providers
        if not fallback_providers:
            return result

        log(f"  ⚠️ Primary image failed, trying fallback providers: {fallback_providers}")
        for fb_name in fallback_providers:
            fb_name = fb_name.strip()
            if not fb_name:
                continue
            fb_cls = get_provider("image", fb_name)
            if not fb_cls:
                log(f"  ⚠️ Fallback provider '{fb_name}' not registered")
                continue
            # Pick API key + config for provider
            fb_config = self.ctx.technical
            if fb_name == "minimax":
                fb_provider = fb_cls(config=fb_config, api_key=self.ctx.technical.api_keys.minimax)
            elif fb_name == "kieai":
                fb_provider = fb_cls(config=fb_config, api_key=self.ctx.technical.api_keys.kie_ai)
            else:
                fb_provider = fb_cls(config=fb_config, api_key=self.ctx.technical.api_keys.wavespeed)
            log(f"  → Trying fallback provider: {fb_name}")
            try:
                fb_result = fb_provider.generate(prompt, output_path, aspect_ratio=aspect_ratio)
            except Exception as e:
                log(f"  ⚠️ Fallback '{fb_name}' error: {type(e).__name__}: {e}")
                fb_result = None
            if fb_result:
                log(f"  ✓ Fallback provider '{fb_name}' succeeded")
                return fb_result

        return result

    def lipsync_generate(self, image_path: str, audio_path: str, output_path: str,
                        scene_id: int = 0, prompt: str = None):
        """Generate lipsync video.

        Args:
            scene_id: scene number (used for unique S3 key)
            prompt: lipsync prompt from config
        """
        if self._dry_run:
            return create_static_video_with_audio(image_path, audio_path, output_path)

        # S3 upload with scene-specific prefix (upload_fn is per-call, thread-safe)
        lipsync_prefix = f"lipsync/{self.timestamp}/scene_{scene_id}"
        upload_fn = lambda fp: s3_upload_file(fp, lipsync_prefix)

        # Get lipsync config from channel.generation (preferred) or technical
        lipsync_cfg = None
        if self.ctx.channel and self.ctx.channel.generation and self.ctx.channel.generation.lipsync:
            lipsync_cfg = self.ctx.channel.generation.lipsync
        elif self.ctx.technical and self.ctx.technical.generation and self.ctx.technical.generation.lipsync:
            lipsync_cfg = self.ctx.technical.generation.lipsync

        if lipsync_cfg is None:
            log(f"  ⚠️ No lipsync config found — using static video fallback")
            return create_static_video_with_audio(image_path, audio_path, output_path)

        return self.lipsync_provider.generate(image_path, audio_path, output_path, config=lipsync_cfg)

    def _make_lipsync_wrapper(self):
        """Create a lipsync wrapper that uses static video when USE_STATIC_LIPSYNC flag is set."""
        real_lipsync = self.lipsync_generate
        use_static = self._use_static_lipsync

        def lipsync_wrapper(image_path, audio_path, output_path, scene_id=0, prompt=None):
            if use_static:
                log(f"  🖼️ USE_STATIC_LIPSYNC: creating static video from image (image={Path(image_path).name})")
                return create_static_video_with_audio(image_path, audio_path, output_path)
            return real_lipsync(image_path, audio_path, output_path, scene_id=scene_id, prompt=prompt)
        return lipsync_wrapper

    # ---- Main run ----

    def run(self, force_start: bool = False) -> tuple[str, list]:
        """Run the full pipeline.

        Returns:
            Tuple of (final_video_path, combined_word_timestamps)
        """
        try:
            log(f"\n{'='*60}")
            log(f"🎬 VIDEO PIPELINE RUNNER")
            if self._use_static_lipsync:
                log(f"🖼️  USE_STATIC_LIPSYNC mode: using static image + TTS for video")
            log(f"{'='*60}")

            scenes = self.ctx.scenario.scenes
            if not scenes:
                raise ValueError("Scenario has no scenes — at least one scene is required")
            log(f"📋 {len(scenes)} scenes loaded")

            if force_start:
                log(f"🆕 Clearing previous scene cache...")
                for channel_dir in self.output_dir.glob("*"):
                    if not channel_dir.is_dir():
                        continue
                    for run_dir in channel_dir.glob("*"):
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

                # Skip if already processed (only in resume mode)
                existing = scene_output / "video_9x16.mp4"
                if self._resume and existing.exists():
                    log(f"  ✅ scene_{scene_id}: video_9x16.mp4 exists - skipping (resume mode)")
                    return (str(existing), [], tts_text)

                if len(chars) != 1:
                    log(f"  ❌ Scene {scene_id}: expected 1 character, got {len(chars)}")
                    return None
                return self.single_processor.process(
                    scene, scene_output,
                    tts_fn=self.tts_generate,
                    image_fn=self.image_generate,
                    lipsync_fn=lipsync_fn,
                ) + (tts_text,)

            # Process scenes in parallel using ThreadPoolExecutor
            log(f"\n🔄 Processing {len(scenes)} scenes in parallel...")
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {}
                for scene in scenes:
                    scene_id = scene.id or 0
                    tts_text = scene.tts or scene.script or ""
                    chars = scene.characters or []
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
                    except SceneDurationError:
                        # Re-raise duration errors so caller can regenerate script
                        log(f"  ⚠️ Scene {scene_id} duration error, will retry with new script")
                        raise
                    except Exception as e:
                        log(f"  ❌ Scene {scene_id} failed: {e}")
                        results_by_scene[scene_id] = None

                # Rebuild scene_videos and scene_scripts in original scene order
                for scene in scenes:
                    scene_id = scene.id or 0
                    result = results_by_scene.get(scene_id)
                    if result:
                        video_path, timestamps, tts_text = result
                        if video_path:
                            scene_videos.append(video_path)
                            scene_scripts.append(tts_text)

            if not scene_videos:
                log(f"\n❌ No scene videos generated")
                raise RuntimeError("No scene videos were generated")

            log(f"\n{'='*60}")
            log(f"🔗 CONCATENATING {len(scene_videos)} scenes...")
            log(f"{'='*60}")

            concat_output = self.run_dir / "video_concat.mp4"
            final_video = self.media_dir / f"video_v3_{self.timestamp}.mp4"

            if not self.concat_videos(scene_videos, str(concat_output)):
                log(f"\n❌ Pipeline failed at concat")
                raise RuntimeError("Video concatenation failed")

            shutil.copy(str(concat_output), str(final_video))
            log(f"  ✅ Concat copied: {final_video.stat().st_size/1024/1024:.1f}MB")

            # Build combined timestamps with offset
            combined_timestamps = []
            offset = 0.0
            for i, scene in enumerate(scenes):
                scene_id = scene.id or (i + 1)
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

            # Save SRT subtitle file
            if combined_timestamps:
                from modules.media.subtitle_srt import save_srt
                srt_path = self.media_dir / f"subtitles_v3_{self.timestamp}.srt"
                save_srt(combined_timestamps, str(srt_path))
                log(f"  📝 SRT saved: {srt_path}")

            # Add watermark
            video_for_subtitles = str(final_video)
            wm_cfg = self.ctx.channel.watermark
            if wm_cfg and wm_cfg.enable:
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

            subtitle_cfg = self.ctx.channel.subtitle
            sub_font_size = subtitle_cfg.font_size if subtitle_cfg and subtitle_cfg.font_size else 60
            add_subtitles(video_for_subtitles, full_script, combined_timestamps or None,
                         str(subtitled_video), font_size=sub_font_size, run_dir=self.run_dir)

            # Add background music
            bg_music = self.ctx.channel.background_music
            music_enabled = bg_music.enable if bg_music else True
            final_output = str(subtitled_video)
            if music_enabled and Path(subtitled_video).exists():
                final_with_music = self.media_dir / f"video_v3_{self.timestamp}_with_music.mp4"
                log(f"\n{'='*60}")
                log(f"🎵 ADDING BACKGROUND MUSIC...")
                log(f"{'='*60}")
                music_result = add_background_music(str(subtitled_video), str(final_with_music), music_provider=self.music_provider)
                final_output = music_result if Path(music_result).exists() else str(subtitled_video)

            log(f"\n✅ DONE: {final_output}")

            if self.run_id:
                db.complete_video_run(self.run_id, status="completed")

            return str(final_output), combined_timestamps
        except Exception as e:
            log(f"\n❌ Pipeline failed: {e}")
            if self.run_id:
                db.fail_video_run(self.run_id, error=str(e))
            raise

    def concat_videos(self, video_paths: List[str], output_path: str) -> Optional[str]:
        """Concatenate scene videos."""
        return concat_videos(video_paths, output_path, run_dir=self.run_dir)

    def _add_watermark(self, video_path: str, output_path: str) -> str:
        """Add watermark (static or bounce mode)."""
        wm_cfg = self.ctx.channel.watermark
        if not wm_cfg or not wm_cfg.enable:
            return video_path

        text = wm_cfg.text
        if not text:
            raise ValueError("watermark.text is required when watermark is enabled")
        font_size = wm_cfg.font_size
        if not font_size:
            raise ValueError("watermark.font_size is required when watermark is enabled")
        opacity = wm_cfg.opacity
        if not (isinstance(opacity, (int, float)) and opacity >= 0):
            raise ValueError("watermark.opacity is required when watermark is enabled")
        motion = wm_cfg.motion or "bounce"

        log(f"  💧 Adding watermark: '{text}' (motion={motion})")

        if motion == "bounce":
            from scripts.bounce_watermark import add_bounce_watermark
            fonts_cfg = self.ctx.channel.fonts
            font_path = fonts_cfg.watermark if fonts_cfg else None
            if not font_path:
                raise ValueError("fonts.watermark is required for bounce watermark")
            success = add_bounce_watermark(
                str(video_path),
                str(output_path),
                text=text,
                font=font_path,
                font_size=font_size,
                opacity=opacity,
                speed=wm_cfg.bounce_speed or 80,
                padding=wm_cfg.bounce_padding or 20,
            )
            if success:
                log(f"  ✅ Watermark added (bounce)")
                return output_path
            else:
                log(f"  ⚠️ Bounce watermark failed")

        # Static fallback
        fonts_cfg = self.ctx.channel.fonts
        font_path = fonts_cfg.watermark if fonts_cfg else None
        result = add_static_watermark(
            video_path, output_path,
            text=text, font_size=font_size, opacity=opacity,
            font_path=font_path, run_dir=self.run_dir
        )
        if result != video_path:
            log(f"  ✅ Watermark added (static)")
        return result
