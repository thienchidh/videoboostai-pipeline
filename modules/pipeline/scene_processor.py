"""
modules/pipeline/scene_processor.py — Scene processing logic extracted from VideoPipelineV3.

Handles per-scene processing for single-character scenes only.
"""

import json
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.paths import PROJECT_ROOT, get_whisper, get_ffmpeg, get_ffprobe
from core.video_utils import (
    log,
    expand_script,
    get_audio_duration,
    crop_to_9x16,
    add_subtitles,
    add_background_music,
    upload_file,
    wait_for_job,
    create_static_video_with_audio,
)
from modules.pipeline.config import PipelineContext
from modules.pipeline.models import SceneConfig


class SceneProcessor:
    """Base class for scene processors."""

    def __init__(self, ctx: PipelineContext, run_dir: Path):
        self.ctx = ctx
        self.run_dir = run_dir
        self.project_root = PROJECT_ROOT
        self.timestamp = int(time.time())

    def _run_tts(self, tts_fn, tts_text: str, voice, speed: float, audio_output: str):
        """Helper to run TTS generation (for parallel execution)."""
        log(f"  🔊 Generating TTS...")
        return tts_fn(tts_text, voice, speed, audio_output)

    def get_character(self, name: str) -> Optional[Dict[str, Any]]:
        chars = self.ctx.channel.characters or []
        for char in chars:
            if char.name == name:
                return char
        return None

    def get_voice(self, voice_id: str) -> Optional[Dict[str, Any]]:
        """Get voice config by id from voices catalog."""
        voices = self.ctx.channel.voices or []
        for voice in voices:
            if voice.id == voice_id:
                return voice
        return None

    def resolve_voice(self, character, scene: Dict[str, Any]) -> Tuple[str, str, float]:
        """Resolve (provider, model, speed) from voice_id or fallback to character tts_voice.

        Returns:
            (provider_name, model_name, speed)
        """
        voice_id = character.voice_id
        voice = self.get_voice(voice_id) if voice_id else None

        if voice:
            providers = voice.providers or []
            if providers:
                primary = providers[0]
                return (
                    primary.provider,
                    primary.model,
                    primary.speed
                )

        # Fallback: use character tts_voice/tts_speed directly (backward compat)
        return "edge", getattr(character, 'tts_voice', "female_voice"), getattr(character, 'tts_speed', 1.0)

    def get_video_prompt(self, scene: SceneConfig) -> str:
        """Get video prompt from scene config, with image_style appended from channel config."""
        explicit = scene.video_prompt
        if not explicit:
            # Fallback: use scene background directly
            explicit = scene.background or "a person talking"

        # Append image_style from channel config for consistent visual style
        image_style = self.ctx.channel.image_style
        if image_style:
            style_parts = [
                image_style.lighting or "",
                image_style.camera or "",
                image_style.art_style or "",
                image_style.environment or "",
                image_style.composition or "",
            ]
            style_str = ", ".join(part for part in style_parts if part)
            if style_str:
                return f"{explicit}, {style_str}"

        return explicit

    def build_scene_prompt(self, scene: SceneConfig) -> str:
        """Build scene prompt from scene background and channel prompt config."""
        # prompt config is not in standard config - use scene background directly
        return scene.background or "a person talking"

    def get_tts_config(self):
        return self.ctx.channel.tts

    def get_whisper_timestamps(self, audio_path: str, output_dir: Optional[Path] = None) -> Optional[List[Dict]]:
        """Get word timestamps from audio using Whisper."""
        if not Path(audio_path).exists():
            return None
        if output_dir is None:
            output_dir = Path(tempfile.mkdtemp())
        else:
            output_dir.mkdir(parents=True, exist_ok=True)

        log(f"  🎯 Running Whisper for word timestamps...")
        try:
            result = subprocess.run(
                [str(get_whisper()), audio_path, "--model", "small", "--word_timestamps", "True",
                 "--output_format", "json", "--output_dir", str(output_dir)],
                capture_output=True, encoding="utf-8", errors="replace", timeout=120
            )
            json_path = output_dir / f"{Path(audio_path).stem}.json"
            if json_path.exists():
                with open(json_path, encoding="utf-8") as f:
                    data = json.load(f)
                timestamps = []
                for seg in data.get("segments", []):
                    for w in seg.get("words", []):
                        word = w.get("word", "").strip()
                        if word:
                            timestamps.append({
                                "word": word,
                                "start": w["start"],
                                "end": w["end"]
                            })
                log(f"  🎯 Whisper got {len(timestamps)} word timestamps")
                return timestamps
        except Exception as e:
            log(f"  ⚠️ Whisper error: {e}")
        return None


class SingleCharSceneProcessor(SceneProcessor):
    """Processes a single-character scene.

    Flow per scene:
    1. expand_script → TTS → validate duration → Whisper timestamps
    2. image gen → lipsync → crop to 9:16
    3. Return (video_path, timestamps)
    """

    def process(self, scene: Dict[str, Any], scene_output: Path,
               tts_fn, image_fn, lipsync_fn) -> Tuple[Optional[str], List[Dict]]:
        """Process a single-character scene.

        Args:
            scene: scene dict from config
            scene_output: Path to scene output directory
            tts_fn: callable(text, voice, speed, output_path) -> (audio_path, timestamps)
            image_fn: callable(prompt, output_path) -> image_path or None
            lipsync_fn: callable(image_path, audio_path, output_path, scene_id, prompt) -> video_path or None

        Returns:
            (video_path, timestamps)
        """
        scene_id = scene.id or 0
        tts_text = scene.tts or scene.script or ""
        chars = scene.characters or []

        scene_output.mkdir(parents=True, exist_ok=True)
        existing = scene_output / "video_9x16.mp4"
        if existing.exists():
            log(f"  ✅ scene_{scene_id}: video_9x16.mp4 exists - skipping")
            ts_file = scene_output / "words_timestamps.json"
            timestamps = []
            if ts_file.exists():
                with open(ts_file, encoding="utf-8") as f:
                    timestamps = json.load(f)
            return str(existing), timestamps

        # Get character name from SceneCharacter or string
        first_char = chars[0]
        char_name = first_char.name if hasattr(first_char, 'name') else first_char
        char_cfg = self.get_character(char_name)
        if not char_cfg:
            log(f"  ❌ Character '{chars[0]}' not found")
            return None, []
        provider, voice, speed = self.resolve_voice(char_cfg, scene)

        # Per-scene character override (speed)
        if isinstance(chars[0], dict) and chars[0].get("speed"):
            speed = chars[0]["speed"]

        prompt = self.get_video_prompt(scene)
        log(f"  📝 Prompt: {prompt[:80]}...")

        # 1. Expand script
        tts_cfg = self.get_tts_config()
        if not tts_cfg:
            raise ValueError("channel.tts config is required")
        min_dur = tts_cfg.min_duration
        max_dur = tts_cfg.max_duration
        # words_per_second from technical generation config
        wps = self.ctx.technical.generation.tts.words_per_second
        tts_text = expand_script(tts_text, min_duration=min_dur, max_duration=max_dur, words_per_second=wps)

        # 2. TTS and Image in PARALLEL (both independent after expand_script)
        audio_output = scene_output / f"audio_tts_{self.timestamp}.mp3"
        scene_img = scene_output / "scene.png"

        with ThreadPoolExecutor(max_workers=2) as executor:
            # Submit TTS task
            tts_future = executor.submit(self._run_tts, tts_fn, tts_text, voice, speed, str(audio_output))
            # Submit Image task (if not exists)
            img_future = executor.submit(image_fn, prompt, str(scene_img)) if not scene_img.exists() else None

            # Wait for TTS first to validate
            audio_result = tts_future.result()
            audio = audio_result[0] if isinstance(audio_result, tuple) else audio_result
            word_timestamps = audio_result[1] if isinstance(audio_result, tuple) else None
            if not audio:
                log(f"  ❌ TTS failed")
                return None, []
            log(f"  ✅ TTS done: {Path(audio).stat().st_size/1024:.1f}KB")

            # Wait for Image
            if img_future:
                img_result = img_future.result()
                if not img_result:
                    log(f"  ❌ Image gen failed")
                    return None, []
                log(f"  ✅ Image done: {scene_img.stat().st_size/1024:.1f}KB")

        # 3. Validate duration
        max_tts = self.get_tts_config().max_duration
        actual_duration = get_audio_duration(str(audio))
        if actual_duration > max_tts:
            log(f"  ❌ TTS duration {actual_duration:.1f}s > {max_tts}s limit!")
            return None, []

        # 4. Whisper timestamps
        audio_file = scene_output / "audio_tts.mp3"
        shutil.copy(audio, str(audio_file))
        if not word_timestamps:
            word_timestamps = self.get_whisper_timestamps(str(audio_file), scene_output)
        if word_timestamps:
            ts_file = scene_output / "words_timestamps.json"
            with open(ts_file, "w", encoding="utf-8") as f:
                json.dump(word_timestamps, f, ensure_ascii=False)
            log(f"  📝 Saved {len(word_timestamps)} word timestamps")

        # 5. Lipsync (depends on both audio and image)
        video_raw = scene_output / "video_raw.mp4"
        if not video_raw.exists():
            log(f"  🎬 Generating lipsync video...")
            lipsync_result = lipsync_fn(str(scene_img), audio, str(video_raw),
                                         scene_id=scene_id, prompt=prompt)
            if not lipsync_result:
                log(f"  ⚠️ Lipsync failed - falling back to static image + audio")
                lipsync_result = create_static_video_with_audio(str(scene_img), audio, str(video_raw))
            if not lipsync_result:
                log(f"  ❌ Static video fallback also failed")
                return None, []
            log(f"  ✅ Lipsync done: {video_raw.stat().st_size/1024/1024:.1f}MB")

        # 6. Crop to 9:16
        video_9x16 = scene_output / "video_9x16.mp4"
        if not video_9x16.exists():
            log(f"  📐 Cropping to 9:16...")
            if not crop_to_9x16(str(video_raw), str(video_9x16)):
                video_raw.unlink(missing_ok=True)
                log(f"  ❌ Crop failed")
                return None, []
            log(f"  ✅ Crop done: {video_9x16.stat().st_size/1024/1024:.1f}MB")

        return str(video_9x16), word_timestamps or []


