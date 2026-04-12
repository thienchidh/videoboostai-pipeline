"""
modules/pipeline/scene_processor.py — Scene processing logic extracted from VideoPipelineV3.

Handles per-scene processing for both single-character and multi-character scenes.
"""

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

    def get_character(self, name: str) -> Optional[Dict[str, Any]]:
        for char in self.config.get("characters", []):
            if char["name"] == name:
                return char
        return None

    def build_scene_prompt(self, scene: Dict[str, Any]) -> str:
        cfg = self.config.get("prompt", {})
        style = cfg.get("style", "3D animated Pixar Disney style, high quality 3D render, detailed, vibrant colors")
        background = scene.get("background", "")
        hints = cfg.get("script_hints", {})

        script_hint = ""
        for key, hint in hints.items():
            if key != "default" and key in background.lower():
                script_hint = hint
                break
        if not script_hint:
            script_hint = hints.get("default", "warm natural lighting, lush environment")

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
                capture_output=True, text=True, timeout=120
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
        script = scene["script"]
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

        char_cfg = self.get_character(chars[0])
        if not char_cfg:
            log(f"  ❌ Character '{chars[0]}' not found")
            return None, []
        voice = char_cfg.get("tts_voice", "female_voice")
        speed = char_cfg.get("tts_speed", 1.0)
        prompt = self.build_scene_prompt(scene)
        log(f"  📝 Prompt: {prompt[:80]}...")

        # 1. Expand script
        script = expand_script(script,
                               min_duration=self.get_tts_config().get("min_duration", 5.0),
                               max_duration=self.get_tts_config().get("max_duration", 15.0),
                               words_per_second=self.get_tts_config().get("words_per_second", 2.5))

        # 2. TTS
        audio_output = scene_output / f"audio_tts_{self.timestamp}.mp3"
        log(f"  🔊 Generating TTS...")
        audio_result = tts_fn(script, voice, speed, str(audio_output))
        audio = audio_result[0] if isinstance(audio_result, tuple) else audio_result
        word_timestamps = audio_result[1] if isinstance(audio_result, tuple) else None
        if not audio:
            log(f"  ❌ TTS failed")
            return None, []
        log(f"  ✅ TTS done: {Path(audio).stat().st_size/1024:.1f}KB")

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

        # 5. Image gen
        scene_img = scene_output / "scene.png"
        if not scene_img.exists():
            log(f"  🎨 Generating scene image...")
            if not image_fn(prompt, str(scene_img)):
                log(f"  ❌ Image gen failed")
                return None, []
            log(f"  ✅ Image done: {scene_img.stat().st_size/1024:.1f}KB")

        # 6. Lipsync
        video_raw = scene_output / "video_raw.mp4"
        if not video_raw.exists():
            log(f"  🎬 Generating lipsync video...")
            lipsync_result = lipsync_fn(str(scene_img), audio, str(video_raw),
                                         scene_id=scene_id, prompt=prompt)
            if not lipsync_result:
                log(f"  ❌ Lipsync failed")
                return None, []
            log(f"  ✅ Lipsync done: {video_raw.stat().st_size/1024/1024:.1f}MB")

        # 7. Crop to 9:16
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
        script = scene["script"]
        chars = scene.get("characters", [])

        scene_output.mkdir(parents=True, exist_ok=True)
        existing = scene_output / "video_9x16.mp4"
        if existing.exists():
            log(f"  ✅ scene_{scene_id}: video_9x16.mp4 exists - skipping")
            return str(existing), []

        char0 = self.get_character(chars[0])
        if not char0:
            log(f"  ❌ Character '{chars[0]}' not found")
            return None, []
        char1 = self.get_character(chars[1])
        if not char1:
            log(f"  ❌ Character '{chars[1]}' not found")
            return None, []

        voice0 = char0.get("tts_voice", "female_voice")
        speed0 = char0.get("tts_speed", 1.0)
        voice1 = char1.get("tts_voice", "male-qn-qingse")
        speed1 = char1.get("tts_speed", 1.0)

        # Split script 60/40
        words = script.split()
        split_at = max(3, len(words) * 60 // 100)
        left_script = " ".join(words[:split_at])
        right_script = " ".join(words[split_at:])

        left_script = expand_script(left_script,
                                    min_duration=self.get_tts_config().get("min_duration", 5.0),
                                    max_duration=self.get_tts_config().get("max_duration", 15.0),
                                    words_per_second=self.get_tts_config().get("words_per_second", 2.5))
        right_script = expand_script(right_script,
                                     min_duration=self.get_tts_config().get("min_duration", 5.0),
                                     max_duration=self.get_tts_config().get("max_duration", 15.0),
                                     words_per_second=self.get_tts_config().get("words_per_second", 2.5))

        max_tts = self.get_tts_config().get("max_duration", 15.0)

        # Left TTS
        audio_left_output = scene_output / f"audio_left_{self.timestamp}.mp3"
        log(f"  🔊 TTS left ({chars[0]})...")
        left_result = tts_fn(left_script, voice0, speed0, str(audio_left_output))
        audio_left = left_result[0] if isinstance(left_result, tuple) else left_result
        if not audio_left:
            log(f"  ❌ Left TTS failed")
            return None, []
        log(f"  ✅ TTS done: {Path(audio_left).stat().st_size/1024:.1f}KB")

        left_duration = get_audio_duration(str(audio_left))
        if left_duration > max_tts:
            log(f"  ❌ Left TTS {left_duration:.1f}s > {max_tts}s limit!")
            return None, []

        # Right TTS
        audio_right_output = scene_output / f"audio_right_{self.timestamp}.mp3"
        log(f"  🔊 TTS right ({chars[1]})...")
        right_result = tts_fn(right_script, voice1, speed1, str(audio_right_output))
        audio_right = right_result[0] if isinstance(right_result, tuple) else right_result
        if not audio_right:
            log(f"  ❌ Right TTS failed")
            return None, []
        log(f"  ✅ TTS done: {Path(audio_right).stat().st_size/1024:.1f}KB")

        right_duration = get_audio_duration(str(audio_right))
        if right_duration > max_tts:
            log(f"  ❌ Right TTS {right_duration:.1f}s > {max_tts}s limit!")
            return None, []

        # Shared image
        scene_img = scene_output / "scene_multi.png"
        if not scene_img.exists():
            prompt = self.build_scene_prompt(scene)
            multi_prompt = f"{prompt}, featuring two children characters together"
            log(f"  🎨 Generating multi scene image...")
            if not image_fn(multi_prompt, str(scene_img)):
                log(f"  ❌ Multi scene image failed")
                return None, []
            log(f"  ✅ Image done: {scene_img.stat().st_size/1024:.1f}KB")

        # Left lipsync
        video_left = scene_output / "video_left.mp4"
        if not video_left.exists():
            log(f"  🎬 Generating left lipsync...")
            if not lipsync_fn(str(scene_img), audio_left, str(video_left),
                              scene_id=scene_id, prompt=f"Character 1 talking"):
                log(f"  ❌ Left lipsync failed")
                return None, []
            log(f"  ✅ Left lipsync done: {video_left.stat().st_size/1024/1024:.1f}MB")

        # Right lipsync
        video_right = scene_output / "video_right.mp4"
        if not video_right.exists():
            log(f"  🎬 Generating right lipsync...")
            if not lipsync_fn(str(scene_img), audio_right, str(video_right),
                              scene_id=scene_id, prompt=f"Character 2 talking"):
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
