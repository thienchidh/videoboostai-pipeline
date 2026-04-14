#!/usr/bin/env python3
"""
Video Pipeline v3 — thin wrapper around VideoPipelineRunner.

Usage (Python API):
    from scripts.video_pipeline_v3 import VideoPipelineV3

    pipeline = VideoPipelineV3(
        channel_id="nang_suat_thong_minh",
        scenario_path="configs/channels/nang_suat_thong_minh/scenarios/scenario.yaml"
    )
    video_path = pipeline.run()
"""

import time

from core.video_utils import log
from modules.pipeline.exceptions import SceneDurationError


# ==================== GLOBAL FLAGS (shared with pipeline_runner) ====================
DRY_RUN = False
DRY_RUN_TTS = False
DRY_RUN_IMAGES = False
UPLOAD_TO_SOCIALS = False
USE_STATIC_LIPSYNC = False


# ==================== SCRIPT ADJUSTMENT WITH LLM ====================

def _regenerate_script_with_llm(original_script: str, scene_id: int,
                                actual_duration: float,
                                min_duration: float, max_duration: float,
                                llm_api_key: str) -> str:
    """Regenerate script using MiniMax LLM to fit duration bounds.
    
    Calculates real words-per-second from actual TTS output.
    
    Args:
        original_script: The original TTS script that was too short/long
        scene_id: ID of the scene (for logging)
        actual_duration: Actual TTS duration in seconds
        min_duration: Minimum allowed duration (5.0s)
        max_duration: Maximum allowed duration (15.0s)
        llm_api_key: MiniMax API key for LLM calls
    
    Returns:
        New script that fits within duration bounds
    """
    from modules.llm.minimax import MiniMaxLLMProvider
    
    # Calculate real wps from actual TTS output
    original_word_count = len(original_script.split())
    real_wps = actual_duration / original_word_count if original_word_count > 0 else 2.5
    
    if actual_duration < min_duration:
        target_duration = (min_duration + max_duration) / 2  # Aim for middle
        direction = "expand"
        issue = "too short"
    else:
        target_duration = max_duration * 0.9  # Aim for 90% of max
        direction = "shorten"
        issue = "too long"
    
    target_words = int(target_duration / real_wps)  # Use real wps for accurate target
    
    system_prompt = f"""Bạn là một chuyên gia viết kịch bản video TikTok/Reels tiếng Việt.
Nhiệm vụ: Viết lại kịch bản TTS cho một scene video.

YÊU CẦU:
- VIẾT TIẾNG VIỆT CÓ DẤU
- Kịch bản phải tự nhiên, hấp dẫn, phù hợp với nội dung gốc
- Độ dài: CHÍNH XÁC khoảng {target_words} từ (tương đương {target_duration:.0f} giây TTS)
- Nếu cần expand: Thêm chi tiết, giải thích, ví dụ cụ thể
- Nếu cần shorten: Cắt bớt phần ít quan trọng, giữ ý chính
- KHÔNG thêm lời chào mở đầu như "Xin chào", "Hôm nay"
- KHÔNG thêm kết luận kiểu "Cảm ơn đã xem"

Output: Chỉ output kịch bản TTS thuần túy, không có mở đầu hay kết thúc."""
    
    user_prompt = f"""Kịch bản gốc (bị đánh giá là {issue}, {actual_duration:.1f}s):
"{original_script}"

Hãy viết lại kịch bản này để có độ dài phù hợp."""
    
    try:
        llm = MiniMaxLLMProvider(api_key=llm_api_key)
        new_script = llm.chat(
            prompt=user_prompt,
            system=system_prompt,
            max_tokens=512
        )
        new_script = new_script.strip()
        log(f"  🤖 LLM regenerated script for scene {scene_id}: {len(original_script.split())} → {len(new_script.split())} words")
        return new_script
    except Exception as e:
        log(f"  ⚠️ LLM call failed: {e}, falling back to original script")
        return original_script


# ==================== WRAPPER ====================

class VideoPipelineV3:
    """Thin wrapper around VideoPipelineRunner.

    Args:
        channel_id: Channel identifier (e.g., 'nang_suat_thong_minh')
        scenario_path: Full path to scenario YAML file.
    """

    def __init__(self, channel_id: str, scenario_path: str, resume: bool = False):
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
            resume=resume,
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
                
                # Regenerate script using LLM to fit duration bounds
                adjusted_script = _regenerate_script_with_llm(
                    original_script=e.script,
                    scene_id=e.scene_id,
                    actual_duration=e.actual_duration,
                    min_duration=e.min_duration,
                    max_duration=e.max_duration,
                    llm_api_key=self.ctx.technical.api_keys.minimax
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
