#!/usr/bin/env python3
"""
Video Pipeline v3 — thin wrapper around VideoPipelineRunner.

Usage (Python API):
    from scripts.video_pipeline_v3 import VideoPipelineV3

    pipeline = VideoPipelineV3(
        channel_id="nang_suat_thong_minh",
        scenario_path="configs/channels/nang_suat_thong_minh/scenarios/2026-04-13/scenario.yaml"
    )
    video_path = pipeline.run()
"""

import time
import random

from core.video_utils import log
from modules.pipeline.exceptions import SceneDurationError


# ==================== GLOBAL FLAGS (shared with pipeline_runner) ====================
DRY_RUN = False
DRY_RUN_TTS = False
DRY_RUN_IMAGES = False
UPLOAD_TO_SOCIALS = False
USE_STATIC_LIPSYNC = False


# ==================== SCRIPT ADJUSTMENT HELPER ====================

def _adjust_script_to_duration(script: str, actual_duration: float,
                                min_duration: float, max_duration: float,
                                wps: float = 2.5) -> str:
    """Adjust script to fit within duration bounds.
    
    Args:
        script: Original script text
        actual_duration: Actual TTS duration in seconds
        min_duration: Minimum allowed duration
        max_duration: Maximum allowed duration
        wps: Words per second (default 2.5 for Vietnamese TTS)
    
    Returns:
        Adjusted script that fits within duration bounds
    """
    if actual_duration < min_duration:
        # Too short - expand by adding filler
        deficit_seconds = min_duration - actual_duration
        deficit_words = int(deficit_seconds * wps)
        
        # Common Vietnamese filler phrases (each ~0.5-1s)
        fillers = [
            "Và điều quan trọng là bạn cần nhớ rằng.",
            "Hãy cùng tôi tìm hiểu sâu hơn.",
            "Đây là một nguyên tắc mà nhiều người thường bỏ qua.",
            "Bạn sẽ thấy được sự khác biệt khi áp dụng ngay.",
            "Đây là bí quyết mà các chuyên gia thường dùng.",
            "Và điều này sẽ thay đổi cách bạn làm việc.",
            "Bạn có biết rằng điều này có thể giúp bạn tiết kiệm thời gian?",
        ]
        
        # Build filler text
        filler_text = ""
        words_added = 0
        random.seed(hash(script) % 2**32)  # Reproducible randomness
        while words_added < deficit_words:
            filler = random.choice(fillers)
            filler_text += " " + filler
            words_added += len(filler.split())
        
        adjusted = script.strip() + filler_text
        log(f"  📝 Script expanded: {len(script.split())} → {len(adjusted.split())} words")
        return adjusted
        
    elif actual_duration > max_duration:
        # Too long - truncate at sentence boundary
        max_words = int(max_duration * wps)
        words = script.split()
        
        # Find truncation point at sentence boundary
        truncated = []
        word_count = 0
        for word in words:
            truncated.append(word)
            word_count += 1
            if word_count >= max_words:
                break
            # Check if this looks like end of sentence
            if word and word[-1] in '.!?:;':
                # Check if next word would push us over
                if word_count + 1 > max_words * 0.95:
                    break
        
        adjusted = ' '.join(truncated)
        # Ensure it ends with proper punctuation
        if adjusted and adjusted[-1] not in '.!?':
            adjusted += '.'
        
        log(f"  📝 Script truncated: {len(script.split())} → {len(adjusted.split())} words")
        return adjusted
    
    return script


# ==================== WRAPPER ====================

class VideoPipelineV3:
    """Thin wrapper around VideoPipelineRunner.

    Args:
        channel_id: Channel identifier (e.g., 'nang_suat_thong_minh')
        scenario_path: Full path to scenario YAML file.
    """

    def __init__(self, channel_id: str, scenario_path: str):
        from modules.pipeline.config import PipelineContext
        from modules.pipeline.pipeline_runner import VideoPipelineRunner

        global DRY_RUN, DRY_RUN_TTS, DRY_RUN_IMAGES, USE_STATIC_LIPSYNC

        self.ctx = PipelineContext(channel_id, scenario_path=scenario_path)

        self.timestamp = int(time.time())

        # Instantiate the real runner (handles DB setup + run_id internally)
        self._runner = VideoPipelineRunner(
            self.ctx,
            dry_run=DRY_RUN,
            dry_run_tts=DRY_RUN_TTS,
            dry_run_images=DRY_RUN_IMAGES,
            use_static_lipsync=USE_STATIC_LIPSYNC,
            timestamp=self.timestamp,
        )

        # Mirror key state for external consumers
        self.config = {
            "video": {"title": self.ctx.scenario.title if self.ctx.scenario else "Untitled"},
        }
        self.avatars_dir = self._runner.run_dir / "avatars"
        self.media_dir = self._runner.media_dir

        log(f"Video Pipeline - {self.ctx.scenario.title if self.ctx.scenario else 'Untitled'}")
        log(f"Output: {self._runner.run_dir}")

    @property
    def run_id(self):
        return self._runner.run_id

    @property
    def run_dir(self):
        return self._runner.run_dir

    def run(self):
        """Run the pipeline. Auto-retries with script adjustment on duration errors."""
        import shutil
        
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                video_path, word_timestamps = self._runner.run()
                self.word_timestamps = word_timestamps
                return video_path
                
            except SceneDurationError as e:
                if attempt >= max_retries:
                    log(f"❌ Max retries ({max_retries}) reached for scene {e.scene_id}")
                    raise
                
                log(f"⚠️ Scene {e.scene_id} duration error: {e.actual_duration:.1f}s "
                    f"(min={e.min_duration:.1f}s, max={e.max_duration:.1f}s)")
                
                # Adjust script to fit duration bounds
                adjusted_script = _adjust_script_to_duration(
                    script=e.script,
                    actual_duration=e.actual_duration,
                    min_duration=e.min_duration,
                    max_duration=e.max_duration
                )
                
                # Find and update the scene in ctx.scenario.scenes
                updated = False
                for scene in self.ctx.scenario.scenes:
                    if scene.id == e.scene_id:
                        old_tts = scene.tts
                        scene.tts = adjusted_script
                        log(f"  🔄 Scene {e.scene_id} script updated: "
                            f"'{old_tts[:50]}...' → '{adjusted_script[:50]}...'")
                        updated = True
                        break
                
                if not updated:
                    log(f"❌ Could not find scene {e.scene_id} in scenario")
                    raise
                
                # Delete scene output to force re-processing
                scene_output_dir = self._runner.run_dir / f"scene_{e.scene_id}"
                if scene_output_dir.exists():
                    shutil.rmtree(scene_output_dir)
                    log(f"  🗑️ Deleted scene output: {scene_output_dir}")
                
                log(f"  🔄 Retrying scene {e.scene_id} ({attempt}/{max_retries})")
        
        return None  # Should not reach here
