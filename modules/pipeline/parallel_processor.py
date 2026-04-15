"""
modules/pipeline/parallel_processor.py — Phase-aware parallel scene processor.

Architecture (4 phases):
  Phase 1 (parallel): TTS for ALL scenes simultaneously
  Phase 2 (parallel): Image gen for ALL scenes (after Phase 1 TTS completes)
  Phase 3 (sequential per scene): Lipsync (depends on both TTS+image for same scene)
  Phase 4 (parallel): Subtitle generation + timestamp collection

Each scene runs: TTS → Image → Lipsync (sequential within scene).
But different scenes' TTS and Image calls overlap — cutting wall-clock time ~60-70%.

Config options:
  parallel_scene_processing:
    enabled: true
    max_workers: 3        # max concurrent API calls (TTS or image)
    sequential_lipsync: true  # always true (lipsync is I/O bound, sequential is safer)
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
    create_static_video_with_audio,
)
from core.video_utils import LipsyncQuotaError  # noqa: F401
from modules.pipeline.config import PipelineContext
from modules.pipeline.models import SceneConfig
from modules.pipeline.exceptions import SceneDurationError
from modules.pipeline.checkpoint import (
    CheckpointHelper, STEP_TTS, STEP_IMAGE, STEP_LIPSYNC, STEP_CROP, STEP_DONE
)


class ParallelSceneProcessor:
    """Phase-aware parallel scene processor.

    Processes multiple scenes in 4 phases:
      1. Parallel TTS for all scenes
      2. Parallel image generation for all scenes (after TTS)
      3. Sequential lipsync per scene (requires TTS+image)
      4. Parallel timestamp collection
    """

    def __init__(self, ctx: PipelineContext, run_dir: Path, max_workers: int = 3, checkpoint_helper=None):
        self.ctx = ctx
        self.run_dir = run_dir
        self.project_root = PROJECT_ROOT
        self.timestamp = int(time.time())
        self.max_workers = max_workers
        self.checkpoint = checkpoint_helper

    # ─── Public API ─────────────────────────────────────────

    def process_scenes(
        self,
        scenes: List[Dict[str, Any]],
        tts_fn,
        image_fn,
        lipsync_fn,
    ) -> List[Tuple[Optional[str], List[Dict], str]]:
        """Process all scenes in phase order.

        Args:
            scenes: list of scene dicts
            tts_fn:  callable(text, voice, speed, output_path) -> (audio_path, timestamps)
            image_fn: callable(prompt, output_path) -> image_path or None
            lipsync_fn: callable(image_path, audio_path, output_path, scene_id, prompt) -> video_path or None

        Returns:
            List of (video_path, timestamps, tts_text) in scene order
        """
        if not scenes:
            return []

        log(f"\n🔄 ParallelSceneProcessor: {len(scenes)} scenes, max_workers={self.max_workers}")
        log(f"   Phases: [1] TTS → [2] Image → [3] Lipsync(sequential) → [4] Subtitle")

        # ── Filter scenes: skip fully-done scenes via checkpoint ─────────
        if self.checkpoint:
            remaining = []
            for s in scenes:
                sid = s.get("id") or 0
                nxt = self.checkpoint.get_next_step(sid)
                if nxt == 99:
                    scene_output = self.run_dir / f"scene_{sid}"
                    existing = scene_output / "video_9x16.mp4"
                    if existing.exists():
                        log(f"  ⏭  scene_{sid}: fully done (checkpoint) - skipping all phases")
                        continue
                    else:
                        # Stale checkpoint - file was deleted; clear and reprocess
                        self.checkpoint.clear(sid)
                remaining.append(s)
            scenes = remaining
            if not scenes:
                log(f"  ✅ All scenes fully done from checkpoints")
                return []

        # ── Phase 1: Parallel TTS ──────────────────────────────
        tts_results = self._phase1_tts(scenes, tts_fn, save_checkpoints=True)
        if not tts_results:
            log(f"  ❌ Phase 1 failed: no TTS results")
            return [(None, [], "") for _ in scenes]

        # ── Phase 2: Parallel Image Gen ───────────────────────
        image_results = self._phase2_image_gen(scenes, image_fn, save_checkpoints=True)
        if not image_results:
            log(f"  ❌ Phase 2 failed: no image results")
            return [(None, [], "") for _ in scenes]

        # ── Phase 3: Sequential Lipsync ───────────────────────
        lipsync_results = self._phase3_lipsync(
            scenes, tts_results, image_results, lipsync_fn, save_checkpoints=True
        )

        # ── Phase 4: Parallel Subtitle/Whisper ─────────────────
        self._phase4_subtitles(scenes, tts_results)

        # ── Assemble ordered results ──────────────────────────
        ordered = []
        for i, scene in enumerate(scenes):
            scene_id = scene.get("id") or i
            lr = lipsync_results.get(scene_id, {})
            video_path = lr.get("video_path")
            timestamps = lr.get("timestamps", [])
            tts_text = tts_results.get(scene_id, {}).get("text", "")
            ordered.append((video_path, timestamps, tts_text))

        return ordered

    # ─── Phase 1: Parallel TTS ────────────────────────────────

    def _phase1_tts(self, scenes: List[Dict[str, Any]],
                    tts_fn, save_checkpoints: bool = False) -> Dict[int, Dict[str, Any]]:
        """Generate TTS for all scenes in parallel.

        Returns:
            {scene_id: {"audio_path": str, "timestamps": list, "text": str}}
        """
        log(f"\n  📡 Phase 1: TTS for {len(scenes)} scenes in parallel (workers={self.max_workers})")
        t_start = time.time()
        results = {}

        def tts_for_scene(scene: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
            scene_id = scene.get("id") or 0
            tts_text = scene.get("tts") or scene.get("script") or ""
            chars = scene.get("characters") or []
            if not chars:
                return scene_id, {"audio_path": None, "timestamps": [], "text": tts_text}

            char_name = chars[0].get("name") if isinstance(chars[0], dict) else chars[0]
            char_cfg = self._get_character(char_name)
            if not char_cfg:
                log(f"  ❌ Phase1: Character '{char_name}' not found for scene {scene_id}")
                return scene_id, {"audio_path": None, "timestamps": [], "text": tts_text}

            provider, voice, speed, gender = self._resolve_voice(char_cfg, scene)
            scene_output = self.run_dir / f"scene_{scene_id}"
            scene_output.mkdir(parents=True, exist_ok=True)
            audio_output = scene_output / f"audio_tts_{self.timestamp}.mp3"
            audio_file = scene_output / "audio_tts.mp3"

            # Check checkpoint: skip if TTS already done
            if self.checkpoint and self.checkpoint.is_step_done(scene_id, STEP_TTS):
                if audio_file.exists():
                    log(f"  ⏭  TTS scene_{scene_id} (checkpoint) - skipping")
                    audio_result = tts_fn(tts_text, voice, speed, str(audio_output))
                    audio = audio_result[0] if isinstance(audio_result, tuple) else audio_result
                    timestamps = audio_result[1] if isinstance(audio_result, tuple) else None
                    return scene_id, {
                        "audio_path": str(audio_file),
                        "timestamps": timestamps or [],
                        "text": tts_text,
                        "duration": get_audio_duration(str(audio_file)),
                    }
                else:
                    # Checkpoint exists but file missing — clear and regenerate
                    self.checkpoint.clear(scene_id)

            log(f"  🔊 TTS scene_{scene_id}...")
            audio_result = tts_fn(tts_text, voice, speed, str(audio_output))
            audio = audio_result[0] if isinstance(audio_result, tuple) else audio_result
            timestamps = audio_result[1] if isinstance(audio_result, tuple) else None

            if audio and Path(audio).exists():
                # Save named copy + checkpoint
                shutil.copy(audio, str(audio_file))
                if save_checkpoints and self.checkpoint:
                    self.checkpoint.save_step(scene_id, STEP_TTS, str(audio_file))
                log(f"  ✅ TTS scene_{scene_id}: {Path(audio).stat().st_size/1024:.1f}KB")
                return scene_id, {
                    "audio_path": str(audio_file),
                    "timestamps": timestamps or [],
                    "text": tts_text,
                    "duration": get_audio_duration(str(audio_file)),
                }
            log(f"  ❌ TTS scene_{scene_id} failed")
            return scene_id, {"audio_path": None, "timestamps": [], "text": tts_text}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(tts_for_scene, s): s for s in scenes}
            for future in as_completed(futures):
                scene_id, data = future.result()
                results[scene_id] = data

        elapsed = time.time() - t_start
        ok = sum(1 for r in results.values() if r["audio_path"])
        log(f"  ⏱ Phase 1 done in {elapsed:.1f}s ({ok}/{len(scenes)} scenes OK)")
        return results

    # ─── Phase 2: Parallel Image Gen ─────────────────────────

    def _phase2_image_gen(self, scenes: List[Dict[str, Any]],
                         image_fn, save_checkpoints: bool = False) -> Dict[int, Dict[str, Any]]:
        """Generate images for all scenes in parallel (runs after Phase 1).

        Returns:
            {scene_id: {"image_path": str, "gender": str, "prompt": str}}
        """
        log(f"\n  🎨 Phase 2: Image gen for {len(scenes)} scenes in parallel (workers={self.max_workers})")
        t_start = time.time()
        results = {}

        def image_for_scene(scene: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
            scene_id = scene.get("id") or 0
            chars = scene.get("characters") or []
            if not chars:
                return scene_id, {"image_path": None, "gender": "female", "prompt": ""}

            char_name = chars[0].get("name") if isinstance(chars[0], dict) else chars[0]
            char_cfg = self._get_character(char_name)
            if not char_cfg:
                return scene_id, {"image_path": None, "gender": "female", "prompt": ""}

            _, _, _, gender = self._resolve_voice(char_cfg, scene)
            prompt = self._get_video_prompt(scene)
            img_prompt = f"{gender} {char_name}, {prompt}"

            scene_output = self.run_dir / f"scene_{scene_id}"
            scene_output.mkdir(parents=True, exist_ok=True)
            scene_img = scene_output / "scene.png"

            # Check checkpoint: skip if image already done
            if self.checkpoint and self.checkpoint.is_step_done(scene_id, STEP_IMAGE):
                if scene_img.exists():
                    log(f"  ⏭  Image scene_{scene_id} (checkpoint) - skipping")
                    return scene_id, {"image_path": str(scene_img), "gender": gender, "prompt": prompt}
                else:
                    self.checkpoint.clear(scene_id)  # stale checkpoint, regenerate

            # Skip if already exists (file-based recovery for mid-phase crashes)
            if scene_img.exists():
                log(f"  ✅ Image scene_{scene_id} (cached): {scene_img.stat().st_size/1024:.1f}KB")
                if save_checkpoints and self.checkpoint:
                    self.checkpoint.save_step(scene_id, STEP_IMAGE, str(scene_img))
                return scene_id, {"image_path": str(scene_img), "gender": gender, "prompt": prompt}

            log(f"  🎨 Image scene_{scene_id}...")
            img_result = image_fn(img_prompt, str(scene_img))
            if img_result and Path(img_result).exists():
                log(f"  ✅ Image scene_{scene_id}: {Path(img_result).stat().st_size/1024:.1f}KB")
                if save_checkpoints and self.checkpoint:
                    self.checkpoint.save_step(scene_id, STEP_IMAGE, str(scene_img))
                return scene_id, {"image_path": img_result, "gender": gender, "prompt": prompt}
            log(f"  ❌ Image scene_{scene_id} failed")
            return scene_id, {"image_path": None, "gender": gender, "prompt": prompt}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(image_for_scene, s): s for s in scenes}
            for future in as_completed(futures):
                scene_id, data = future.result()
                results[scene_id] = data

        elapsed = time.time() - t_start
        ok = sum(1 for r in results.values() if r["image_path"])
        log(f"  ⏱ Phase 2 done in {elapsed:.1f}s ({ok}/{len(scenes)} scenes OK)")
        return results

    # ─── Phase 3: Sequential Lipsync ─────────────────────────

    def _phase3_lipsync(self, scenes: List[Dict[str, Any]],
                        tts_results: Dict[int, Dict],
                        image_results: Dict[int, Dict],
                        lipsync_fn, save_checkpoints: bool = False) -> Dict[int, Dict]:
        """Run lipsync per scene (sequential to avoid rate-limiting).

        Returns:
            {scene_id: {"video_path": str, "timestamps": list}}
        """
        log(f"\n  🎬 Phase 3: Lipsync (sequential, {len(scenes)} scenes)")
        t_start = time.time()
        results = {}

        for scene in scenes:
            scene_id = scene.get("id") or 0
            tts_data = tts_results.get(scene_id, {})
            img_data = image_results.get(scene_id, {})

            audio_path = tts_data.get("audio_path")
            image_path = img_data.get("image_path")

            if not audio_path or not image_path:
                log(f"  ⚠️ scene_{scene_id}: missing audio or image, skipping lipsync")
                results[scene_id] = {"video_path": None, "timestamps": tts_data.get("timestamps", [])}
                continue

            scene_output = self.run_dir / f"scene_{scene_id}"
            scene_output.mkdir(parents=True, exist_ok=True)

            # Duration validation
            tts_cfg = self.ctx.channel.tts
            min_tts = tts_cfg.min_duration
            max_tts = tts_cfg.max_duration
            actual_duration = get_audio_duration(audio_path)
            if actual_duration > max_tts or actual_duration < min_tts:
                raise SceneDurationError(
                    scene_id=scene_id,
                    actual_duration=actual_duration,
                    min_duration=min_tts,
                    max_duration=max_tts,
                    script=tts_data.get("text", ""),
                )

            # Copy audio to named file for downstream use (already done in phase1 for non-checkpoint runs)
            audio_file = scene_output / "audio_tts.mp3"
            if not audio_file.exists() and Path(audio_path).exists():
                shutil.copy(audio_path, str(audio_file))

            video_raw = scene_output / "video_raw.mp4"
            prompt = img_data.get("prompt", "")

            # Check checkpoint: skip lipsync + crop if already done
            if self.checkpoint and self.checkpoint.is_step_done(scene_id, STEP_CROP):
                video_9x16 = scene_output / "video_9x16.mp4"
                if video_9x16.exists():
                    log(f"  ⏭  Lipsync+Crop scene_{scene_id} (checkpoint) - skipping")
                    results[scene_id] = {
                        "video_path": str(video_9x16),
                        "timestamps": tts_data.get("timestamps", []),
                    }
                    continue
                else:
                    self.checkpoint.clear(scene_id)  # stale checkpoint, file deleted

            # ── Lipsync step ────────────────────────────────────
            if not video_raw.exists():
                if self.checkpoint and self.checkpoint.is_step_done(scene_id, STEP_LIPSYNC):
                    if video_raw.exists():
                        log(f"  ⏭  Lipsync scene_{scene_id} (checkpoint) - skipping")
                    else:
                        self.checkpoint.clear(scene_id)  # stale

                log(f"  🎬 Lipsync scene_{scene_id}...")
                try:
                    lipsync_result = lipsync_fn(image_path, audio_path, str(video_raw),
                                                scene_id=scene_id, prompt=prompt)
                except LipsyncQuotaError as e:
                    log(f"  ⚠️ Lipsync quota exceeded: {e} — fallback to static")
                    lipsync_result = None

                if not lipsync_result:
                    log(f"  ⚠️ Lipsync failed — fallback to static image + audio")
                    lipsync_result = create_static_video_with_audio(image_path, audio_path, str(video_raw))

                if not lipsync_result:
                    log(f"  ❌ Lipsync + static fallback both failed for scene_{scene_id}")
                    results[scene_id] = {"video_path": None, "timestamps": tts_data.get("timestamps", [])}
                    continue

                if save_checkpoints and self.checkpoint:
                    self.checkpoint.save_step(scene_id, STEP_LIPSYNC, str(video_raw))
                log(f"  ✅ Lipsync done: {video_raw.stat().st_size/1024/1024:.1f}MB")
            else:
                log(f"  ⏭  Lipsync scene_{scene_id} (cached) - skipping")

            # ── Crop step ───────────────────────────────────────
            video_9x16 = scene_output / "video_9x16.mp4"
            if not video_9x16.exists():
                log(f"  📐 Cropping scene_{scene_id} to 9:16...")
                if not crop_to_9x16(str(video_raw), str(video_9x16)):
                    video_raw.unlink(missing_ok=True)
                    results[scene_id] = {"video_path": None, "timestamps": tts_data.get("timestamps", [])}
                    continue
                log(f"  ✅ Crop done: {video_9x16.stat().st_size/1024/1024:.1f}MB")

            if save_checkpoints and self.checkpoint and video_9x16.exists():
                self.checkpoint.save_step(scene_id, STEP_CROP, str(video_9x16))
                self.checkpoint.save_step(scene_id, STEP_DONE, str(video_9x16))

            results[scene_id] = {
                "video_path": str(video_9x16),
                "timestamps": tts_data.get("timestamps", []),
            }

        elapsed = time.time() - t_start
        ok = sum(1 for r in results.values() if r["video_path"])
        log(f"  ⏱ Phase 3 done in {elapsed:.1f}s ({ok}/{len(scenes)} scenes OK)")
        return results

    # ─── Phase 4: Parallel Subtitle/Whisper ─────────────────

    def _phase4_subtitles(self, scenes: List[Dict[str, Any]],
                           tts_results: Dict[int, Dict]):
        """Run Whisper timestamps for all scenes in parallel (where timestamps not already available).

        Returns:
            Updates timestamps in tts_results in-place.
        """
        log(f"\n  🎯 Phase 4: Whisper timestamps for {len(scenes)} scenes in parallel")
        t_start = time.time()

        def whisper_scene(scene: Dict[str, Any]) -> Tuple[int, List[Dict]]:
            scene_id = scene.get("id") or 0
            scene_output = self.run_dir / f"scene_{scene_id}"
            audio_file = scene_output / "audio_tts.mp3"

            if not audio_file.exists():
                return scene_id, []

            timestamps = self._get_whisper_timestamps(str(audio_file), scene_output)
            if timestamps:
                ts_file = scene_output / "words_timestamps.json"
                with open(ts_file, "w", encoding="utf-8") as f:
                    json.dump(timestamps, f, ensure_ascii=False)
                log(f"  ✅ Whisper scene_{scene_id}: {len(timestamps)} words")
            return scene_id, timestamps or []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(whisper_scene, s): s for s in scenes}
            for future in as_completed(futures):
                scene_id, timestamps = future.result()
                if scene_id in tts_results and timestamps:
                    tts_results[scene_id]["timestamps"] = timestamps

        elapsed = time.time() - t_start
        log(f"  ⏱ Phase 4 done in {elapsed:.1f}s")

    # ─── Helpers ─────────────────────────────────────────────

    def _get_character(self, name: str) -> Optional[Dict[str, Any]]:
        chars = self.ctx.channel.characters or []
        for char in chars:
            if char.name == name:
                return char
        return None

    def _get_voice(self, voice_id: str) -> Optional[Dict[str, Any]]:
        voices = self.ctx.channel.voices or []
        for voice in voices:
            if voice.id == voice_id:
                return voice
        return None

    def _resolve_voice(self, character, scene: Dict[str, Any]) -> Tuple[str, str, float, str]:
        voice_id = character.voice_id
        voice = self._get_voice(voice_id) if voice_id else None

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

        return "edge", getattr(character, 'tts_voice', "female_voice"), \
               getattr(character, 'tts_speed', 1.0), "female"

    def _get_video_prompt(self, scene: Dict[str, Any]) -> str:
        explicit = scene.get("video_prompt") or scene.get("background") or "a person talking"

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

    def _get_whisper_timestamps(self, audio_path: str,
                                output_dir: Optional[Path] = None) -> Optional[List[Dict]]:
        if not Path(audio_path).exists():
            return None
        output_dir = output_dir or Path(tempfile.mkdtemp())
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            result = subprocess.run(
                [str(get_whisper()), audio_path, "--model", "small",
                 "--word_timestamps",
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
                return timestamps
        except Exception as e:
            log(f"  ⚠️ Whisper error: {e}")
        return None
