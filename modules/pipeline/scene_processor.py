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
    get_audio_duration,
    crop_to_9x16,
    add_subtitles,
    add_background_music,
    upload_file,
    wait_for_job,
    create_static_video_with_audio,
)
from core.video_utils import LipsyncQuotaError  # noqa: F401
from modules.pipeline.config import PipelineContext
from modules.pipeline.models import SceneConfig
from modules.pipeline.exceptions import SceneDurationError


class SceneProcessor:
    """Base class for scene processors."""

    def __init__(self, ctx: PipelineContext, run_dir: Path, resume: bool = False):
        self.ctx = ctx
        self.run_dir = run_dir
        self.resume = resume
        self.project_root = PROJECT_ROOT
        self.timestamp = int(time.time())

        # Read max_workers from config (strict: require key to exist)
        max_workers = ctx.technical.generation.parallel_scene_processing.max_workers
        self.max_workers = max_workers

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

    def resolve_voice(self, character, scene: Dict[str, Any]) -> Tuple[str, str, float, str]:
        """Resolve (provider, model, speed, gender) from voice_id or fallback to channel config.

        Returns:
            (provider_name, model_name, speed, gender)
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
                    primary.speed,
                    voice.gender or "female",
                )

        # Fallback: use channel config's generation.models.tts as provider
        fallback_provider = self.ctx.channel.generation.models.tts if self.ctx.channel.generation else None
        # Fallback: use first voice from catalog as voice_id
        fallback_voice_id = "female_voice"
        voices = self.ctx.channel.voices or []
        if voices:
            fallback_voice_id = voices[0].id

        return fallback_provider or "edge", getattr(character, 'tts_voice', fallback_voice_id), getattr(character, 'tts_speed', 1.0), "female"

    def get_video_prompt(self, scene: SceneConfig) -> str:
        """Get video prompt from scene config, with image_style appended from channel config."""
        explicit = scene.video_prompt
        if not explicit:
            # Fallback: use channel config's generation.lipsync.prompt
            if self.ctx.channel.generation and self.ctx.channel.generation.lipsync:
                explicit = self.ctx.channel.generation.lipsync.prompt
            else:
                explicit = "A person talking"

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
        """Build scene prompt from scene background and channel config."""
        # Use channel config's generation.lipsync.prompt as fallback
        if scene.background:
            return scene.background
        if self.ctx.channel.generation and self.ctx.channel.generation.lipsync:
            return self.ctx.channel.generation.lipsync.prompt
        return "A person talking"

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
                [str(get_whisper()), audio_path, "--model", "small", "--word_timestamps",
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


def align_word_timestamps(whisper_timestamps: List[Dict], script_words: List[str]) -> List[Dict]:
    """Replace Whisper words with script words when count matches.

    Args:
        whisper_timestamps: [{"word": "...", "start": 0.0, "end": 0.5}, ...] from Whisper
        script_words: [word, ...] from scenario script (already split by whitespace)

    Returns:
        Aligned timestamps with script words + Whisper timestamps if count matches,
        otherwise original Whisper timestamps unchanged.
    """
    if not whisper_timestamps:
        return whisper_timestamps
    if not script_words:
        return whisper_timestamps

    n_whisper = len(whisper_timestamps)
    n_script = len(script_words)

    if n_whisper == n_script:
        return [
            {
                "word": script_words[i],
                "start": whisper_timestamps[i]["start"],
                "end": whisper_timestamps[i]["end"]
            }
            for i in range(n_whisper)
        ]
    else:
        return whisper_timestamps


class SingleCharSceneProcessor(SceneProcessor):
    """Processes a single-character scene.

    Flow per scene:
    1. TTS → validate duration → Whisper timestamps
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
        if self.resume and existing.exists():
            log(f"  ✅ scene_{scene_id}: video_9x16.mp4 exists - skipping (resume mode)")
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
        provider, voice, speed, gender = self.resolve_voice(char_cfg, scene)

        # Per-scene character override (speed)
        if hasattr(chars[0], 'speed') and chars[0].speed:
            speed = chars[0].speed

        prompt = self.get_video_prompt(scene)
        log(f"  📝 Prompt: {prompt[:80]}...")

        # Build image prompt: include character name + gender so image matches TTS voice
        img_prompt = f"{gender} {char_name}, {prompt}"

        # 1. TTS and Image in PARALLEL
        audio_output = scene_output / f"audio_tts_{self.timestamp}.mp3"
        scene_img = scene_output / "scene.png"

        with ThreadPoolExecutor(max_workers=2) as executor:
            # Submit TTS task
            tts_future = executor.submit(self._run_tts, tts_fn, tts_text, voice, speed, str(audio_output))
            # Submit Image task (if not exists) - use img_prompt with character
            img_future = executor.submit(image_fn, img_prompt, str(scene_img)) if not scene_img.exists() else None

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
        tts_cfg = self.get_tts_config()
        min_tts = tts_cfg.min_duration
        max_tts = tts_cfg.max_duration
        actual_duration = get_audio_duration(str(audio))
        if actual_duration > max_tts or actual_duration < min_tts:
            raise SceneDurationError(
                scene_id=scene_id,
                actual_duration=actual_duration,
                min_duration=min_tts,
                max_duration=max_tts,
                script=tts_text
            )

        # 4. Whisper timestamps
        audio_file = scene_output / "audio_tts.mp3"
        shutil.copy(audio, str(audio_file))
        if not word_timestamps:
            word_timestamps = self.get_whisper_timestamps(str(audio_file), scene_output)
        if word_timestamps:
            # Align Whisper words with script words when counts match
            script_words = tts_text.split()
            word_timestamps = align_word_timestamps(word_timestamps, script_words)
            ts_file = scene_output / "words_timestamps.json"
            with open(ts_file, "w", encoding="utf-8") as f:
                json.dump(word_timestamps, f, ensure_ascii=False)
            log(f"  📝 Saved {len(word_timestamps)} word timestamps (aligned)")

        # 5. Lipsync (depends on both audio and image)
        video_raw = scene_output / "video_raw.mp4"
        if not video_raw.exists():
            log(f"  🎬 Generating lipsync video...")
            try:
                lipsync_result = lipsync_fn(str(scene_img), audio, str(video_raw),
                                             scene_id=scene_id, prompt=prompt)
            except LipsyncQuotaError as e:
                log(f"  ⚠️ Lipsync quota exceeded: {e} — falling back to static image + audio")
                lipsync_result = None
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


