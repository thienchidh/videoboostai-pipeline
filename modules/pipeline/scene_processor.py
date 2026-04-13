"""
modules/pipeline/scene_processor.py — Scene processing logic extracted from VideoPipelineV3.

Handles per-scene processing for both single-character and multi-character scenes.
"""

import json
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Tuple

from core.paths import PROJECT_ROOT, get_whisper, get_ffmpeg, get_ffprobe, get_config_path
from core.video_utils import (
    log,
    expand_script,
    get_audio_duration,
    crop_to_9x16,
    concat_videos,
    add_subtitles,
    add_background_music,
    upload_file,
    wait_for_job,
)


class SceneProcessor:
    """Base class for scene processors."""

    def __init__(self, config: "PipelineConfig", run_dir: Path):
        self.config = config
        self.run_dir = run_dir
        self.project_root = PROJECT_ROOT
        self.timestamp = int(time.time())

    def _run_tts(self, tts_fn, tts_text: str, voice, speed: float, audio_output: str):
        """Helper to run TTS generation (for parallel execution)."""
        log(f"  🔊 Generating TTS...")
        return tts_fn(tts_text, voice, speed, audio_output)

    def get_character(self, name: str) -> Optional[Dict[str, Any]]:
        for char in self.config.get("characters", []):
            if char["name"] == name:
                return char
        return None

    def get_voice(self, voice_id: str) -> Optional[Dict[str, Any]]:
        """Get voice config by id from voices catalog."""
        for voice in self.config.get("voices", []):
            if voice["id"] == voice_id:
                return voice
        return None

    def resolve_voice(self, character: Dict[str, Any], scene: Dict[str, Any]) -> Tuple[str, str, float]:
        """Resolve (provider, model, speed) from voice_id or fallback to character tts_voice.

        Returns:
            (provider_name, model_name, speed)
        """
        voice_id = character.get("voice_id")
        voice = self.get_voice(voice_id) if voice_id else None

        if voice:
            providers = voice.get("providers", [])
            if providers:
                primary = providers[0]
                return (
                    primary.get("provider", "edge"),
                    primary.get("model", ""),
                    primary.get("speed", 1.0)
                )

        # Fallback: use character tts_voice/tts_speed directly (backward compat)
        return "edge", character.get("tts_voice", "female_voice"), character.get("tts_speed", 1.0)

    def get_video_prompt(self, scene: Dict[str, Any]) -> str:
        """Get video prompt from scene config, with image_style appended from channel config."""
        explicit = scene.get("video_prompt")
        if not explicit:
            # Fallback for backward compat
            explicit = self.build_scene_prompt(scene)

        # Append image_style from channel config for consistent visual style
        image_style = self.config.get("image_style", {})
        if image_style:
            style_parts = [
                image_style.get("lighting", ""),
                image_style.get("camera", ""),
                image_style.get("art_style", ""),
                image_style.get("environment", ""),
                image_style.get("composition", ""),
            ]
            style_str = ", ".join(part for part in style_parts if part)
            if style_str:
                return f"{explicit}, {style_str}"

        return explicit

    def build_scene_prompt(self, scene: Dict[str, Any]) -> str:
        cfg = self.config.get("prompt", {})
        style = cfg.get("style")
        if not style:
            raise MissingConfigError("config.prompt.style is required")
        background = scene.get("background", "")
        hints = cfg.get("script_hints", {})

        script_hint = ""
        for key, hint in hints.items():
            if key != "default" and key in background.lower():
                script_hint = hint
                break
        if not script_hint:
            script_hint = hints.get("default")
            if not script_hint:
                raise MissingConfigError("config.prompt.script_hints.default is required")

        prompt = f"{style}, {script_hint}"

        chars = scene.get("characters", [])
        if chars:
            char_prompts = []
            for char_name in chars:
                char = self.get_character(char_name)
                if char and char.get("prompt"):
                    char_prompts.append(char["prompt"])
            if char_prompts:
                prompt = f"{prompt}, featuring: {' '.join(char_prompts)}"

        return prompt

    def get_tts_config(self) -> Dict[str, Any]:
        return self.config.get("tts", {})

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
        scene_id = scene.get("id", 0)
        tts_text = scene.get("tts", scene.get("script", ""))
        chars = scene.get("characters", [])

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

        char_cfg = self.get_character(chars[0]["name"] if isinstance(chars[0], dict) else chars[0])
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
        min_dur = tts_cfg.get("min_duration")
        max_dur = tts_cfg.get("max_duration")
        wps = tts_cfg.get("words_per_second")
        if min_dur is None or max_dur is None or wps is None:
            raise MissingConfigError("config.tts.min_duration, max_duration, and words_per_second are all required")
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
        max_tts = self.get_tts_config().get("max_duration", 15.0)
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
                log(f"  ❌ Lipsync failed")
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


class MultiCharSceneProcessor(SceneProcessor):
    """Processes a two-character scene.

    Flow per scene:
    1. Split script ~60/40 → expand each half
    2. TTS for each character + duration validation
    3. Single shared image → lipsync for each audio
    4. Crop both → concat side by side
    5. Return (video_path, timestamps)
    """

    def process(self, scene: Dict[str, Any], scene_output: Path,
               tts_fn, image_fn, lipsync_fn) -> Tuple[Optional[str], List[Dict]]:
        """Process a two-character scene."""
        scene_id = scene.get("id", 0)
        scene_tts = scene.get("tts", scene.get("script", ""))
        chars = scene.get("characters", [])

        scene_output.mkdir(parents=True, exist_ok=True)
        existing = scene_output / "video_9x16.mp4"
        if existing.exists():
            log(f"  ✅ scene_{scene_id}: video_9x16.mp4 exists - skipping")
            return str(existing), []

        char0_cfg = chars[0] if isinstance(chars[0], dict) else {"name": chars[0]}
        char1_cfg = chars[1] if isinstance(chars[1], dict) else {"name": chars[1]}

        char0 = self.get_character(char0_cfg["name"])
        if not char0:
            log(f"  ❌ Character '{char0_cfg['name']}' not found")
            return None, []
        char1 = self.get_character(char1_cfg["name"])
        if not char1:
            log(f"  ❌ Character '{char1_cfg['name']}' not found")
            return None, []

        _, voice0, speed0 = self.resolve_voice(char0, scene)
        _, voice1, speed1 = self.resolve_voice(char1, scene)

        # Per-scene overrides
        if char0_cfg.get("speed"):
            speed0 = char0_cfg["speed"]
        if char1_cfg.get("speed"):
            speed1 = char1_cfg["speed"]

        # Determine TTS text per character
        char0_tts = char0_cfg.get("tts")
        char1_tts = char1_cfg.get("tts")

        if not char0_tts or not char1_tts:
            # Auto-split scene tts 60/40
            words = scene_tts.split()
            split_at = max(3, len(words) * 60 // 100)
            left_words = " ".join(words[:split_at])
            right_words = " ".join(words[split_at:])
            if not char0_tts:
                char0_tts = left_words
            if not char1_tts:
                char1_tts = right_words

        tts_cfg = self.get_tts_config()
        min_dur = tts_cfg.get("min_duration")
        max_dur = tts_cfg.get("max_duration")
        wps = tts_cfg.get("words_per_second")
        if min_dur is None or max_dur is None or wps is None:
            raise MissingConfigError("config.tts.min_duration, max_duration, and words_per_second are all required")

        char0_tts = expand_script(char0_tts,
                                  min_duration=min_dur,
                                  max_duration=max_dur,
                                  words_per_second=wps)
        char1_tts = expand_script(char1_tts,
                                   min_duration=min_dur,
                                   max_duration=max_dur,
                                   words_per_second=wps)

        video_prompt = self.get_video_prompt(scene)
        scene_img = scene_output / "scene_multi.png"
        audio_left_output = scene_output / f"audio_left_{self.timestamp}.mp3"
        audio_right_output = scene_output / f"audio_right_{self.timestamp}.mp3"

        # TTS left || TTS right || Image (all parallel after expand_script)
        with ThreadPoolExecutor(max_workers=3) as executor:
            # Left TTS
            left_tts_future = executor.submit(self._run_tts, tts_fn, char0_tts, voice0, speed0, str(audio_left_output))
            # Right TTS
            right_tts_future = executor.submit(self._run_tts, tts_fn, char1_tts, voice1, speed1, str(audio_right_output))
            # Image (if not exists)
            img_future = executor.submit(image_fn, f"{video_prompt}, featuring two characters together", str(scene_img)) if not scene_img.exists() else None

            # Wait for Left TTS
            left_result = left_tts_future.result()
            audio_left = left_result[0] if isinstance(left_result, tuple) else left_result
            if not audio_left:
                log(f"  ❌ Left TTS failed")
                return None, []
            log(f"  ✅ TTS done: {Path(audio_left).stat().st_size/1024:.1f}KB")
            left_duration = get_audio_duration(str(audio_left))
            if left_duration > max_dur:
                log(f"  ❌ Left TTS {left_duration:.1f}s > {max_dur}s limit!")
                return None, []

            # Wait for Right TTS
            right_result = right_tts_future.result()
            audio_right = right_result[0] if isinstance(right_result, tuple) else right_result
            if not audio_right:
                log(f"  ❌ Right TTS failed")
                return None, []
            log(f"  ✅ TTS done: {Path(audio_right).stat().st_size/1024:.1f}KB")
            right_duration = get_audio_duration(str(audio_right))
            if right_duration > max_dur:
                log(f"  ❌ Right TTS {right_duration:.1f}s > {max_dur}s limit!")
                return None, []

            # Wait for Image
            if img_future:
                img_result = img_future.result()
                if not img_result:
                    log(f"  ❌ Multi scene image failed")
                    return None, []
                log(f"  ✅ Image done: {scene_img.stat().st_size/1024:.1f}KB")

        # Left lipsync || Right lipsync (parallel after image and audio)
        video_left = scene_output / "video_left.mp4"
        video_right = scene_output / "video_right.mp4"

        with ThreadPoolExecutor(max_workers=2) as executor:
            left_lipsync_future = executor.submit(lipsync_fn, str(scene_img), audio_left, str(video_left),
                                                  scene_id=scene_id, prompt=f"{video_prompt}, character on the left, talking") if not video_left.exists() else None
            right_lipsync_future = executor.submit(lipsync_fn, str(scene_img), audio_right, str(video_right),
                                                   scene_id=scene_id, prompt=f"{video_prompt}, character on the right, talking") if not video_right.exists() else None

            if left_lipsync_future:
                log(f"  🎬 Generating left lipsync...")
                if not left_lipsync_future.result():
                    log(f"  ❌ Left lipsync failed")
                    return None, []
                log(f"  ✅ Left lipsync done: {video_left.stat().st_size/1024/1024:.1f}MB")

            if right_lipsync_future:
                log(f"  🎬 Generating right lipsync...")
                if not right_lipsync_future.result():
                    log(f"  ❌ Right lipsync failed")
                    return None, []
                log(f"  ✅ Right lipsync done: {video_right.stat().st_size/1024/1024:.1f}MB")

        # Crop and concat
        video_left_9x16 = scene_output / "video_left_9x16.mp4"
        if not video_left_9x16.exists():
            if not crop_to_9x16(str(video_left), str(video_left_9x16)):
                video_left.unlink(missing_ok=True)
                log(f"  ❌ Left crop failed")
                return None, []

        video_right_9x16 = scene_output / "video_right_9x16.mp4"
        if not video_right_9x16.exists():
            if not crop_to_9x16(str(video_right), str(video_right_9x16)):
                video_right.unlink(missing_ok=True)
                log(f"  ❌ Right crop failed")
                return None, []

        log(f"  🔗 Concatenating left + right...")
        video_9x16 = scene_output / "video_9x16.mp4"
        if not concat_videos([str(video_left_9x16), str(video_right_9x16)], str(video_9x16)):
            return None, []

        return str(video_9x16), []
