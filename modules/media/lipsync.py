"""
modules/media/lipsync.py — Video lipsync providers

Provides:
- WaveSpeedLipsyncProvider: WaveSpeed LTX lipsync
- WaveSpeedMultiTalkProvider: WaveSpeed InfiniteTalk multi-character video
- KieAIInfinitalkProvider: Kie.ai Infinitalk lip-sync
- mock_lipsync_video: dry-run placeholder (called by pipeline, not provider)
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from core.video_utils import LipsyncQuotaError
from core.plugins import LipsyncProvider, register_provider
from modules.pipeline.models import GenerationLipsync, LipsyncRequest

logger = logging.getLogger(__name__)


# ==================== WAVESPEED LIPSYNC ====================

class WaveSpeedLipsyncProvider(LipsyncProvider):
    """WaveSpeed AI LTX lipsync video generation."""

    def __init__(self, config=None, api_key=None, upload_func=None):
        self.config = config
        base_url = config.get("api.urls.wavespeed") if config else None
        if not base_url:
            from modules.pipeline.exceptions import ConfigMissingKeyError
            raise ConfigMissingKeyError("api.urls.wavespeed", "WaveSpeedLipsyncProvider")
        self.base_url = base_url
        self.api_key = api_key or (config.get("api.keys.wavespeed") if config else None)
        self.upload_func = upload_func
        self.poll_interval = config.get("generation.lipsync.poll_interval") if config else 10
        self.max_wait = config.get("generation.lipsync.max_wait") if config else 300

    def upload_file(self, file_path: str) -> Optional[str]:
        """Upload file to WaveSpeed media storage."""
        if self.upload_func:
            return self.upload_func(file_path)

        ext = Path(file_path).suffix.lstrip(".")
        content_type = f"audio/{ext}" if ext in ["mp3", "wav", "ogg"] else f"image/{ext}"
        url = f"{self.base_url}/api/v3/media/upload/binary?ext={ext}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": content_type}
        try:
            with open(file_path, "rb") as f:
                resp = requests.post(url, headers=headers, data=f, timeout=60)
            data = resp.json()
            if data.get("data", {}).get("download_url"):
                return data["data"]["download_url"]
            logger.warning(f"Upload failed: {data}")
        except Exception as e:
            logger.warning(f"Upload error: {e}")
        return None

    def wait_for_job(self, job_id: str, max_wait: int = None) -> Optional[str]:
        """Poll for job completion. Return output URL or None."""
        url = f"{self.base_url}/api/v3/predictions/{job_id}/result"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        elapsed = 0
        interval = self.poll_interval
        max_wait = max_wait or self.max_wait
        while elapsed < max_wait:
            try:
                resp = requests.get(url, headers=headers, timeout=30)
                data = resp.json()
                status = data.get("data", {}).get("status", "processing")
                outputs = data.get("data", {}).get("outputs", [])
                if status == "completed" and outputs:
                    logger.debug(f"  ✅ Ready ({elapsed}s)")
                    return outputs[0]
                elif status == "failed":
                    logger.warning(f"  ❌ Failed: {data.get('data', {}).get('error', 'unknown')}")
                    return None
                logger.debug(f"  ⏳ {status}... ({elapsed}s)")
                time.sleep(interval)
                elapsed += interval
            except Exception as e:
                logger.warning(f"  ⚠️ Poll error: {e}")
                time.sleep(interval)
                elapsed += interval
        logger.warning(f"  ❌ Timeout")
        return None

    def generate(self, image_path: str, audio_path: str,
                 output_path: str, config: Optional[GenerationLipsync] = None) -> Optional[str]:
        cfg = config or {}
        default_retries = self.config.get("generation.lipsync.retries", 2) if self.config else 2
        retries = cfg.get("retries", default_retries)

        for attempt in range(retries):
            logger.debug(f"  🎬 LTX Lipsync (attempt {attempt+1})...")
            image_url = self.upload_file(image_path)
            if not image_url:
                logger.warning(f"  ❌ Image upload failed")
                continue
            audio_url = self.upload_file(audio_path)
            if not audio_url:
                logger.warning(f"  ❌ Audio upload failed")
                continue

            url = f"{self.base_url}/api/v3/wavespeed-ai/ltx-2.3/lipsync"
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            payload = {
                "image": image_url,
                "audio": audio_url,
                "resolution": cfg.get("resolution", "480p")
            }
            if cfg.get("seed"):
                payload["seed"] = cfg["seed"]

            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
                data = resp.json()
                # Detect quota/credits errors
                status_code = resp.status_code
                error_msg = str(data.get("error", "") or data.get("message", "") or "").lower()
                quota_keywords = ("quota", "credit", "insufficient", "exceed", "limit", "429",
                                 "rate limit", "monthly", "free tier", "余额", "配额", "额度")
                if status_code == 429 or any(k in error_msg for k in quota_keywords):
                    logger.error(f"  ❌ LTX Lipsync QUOTA EXHAUSTED: {data}")
                    raise LipsyncQuotaError(f"WaveSpeed LTX quota exceeded: {data}")
                if not data.get("data", {}).get("id"):
                    logger.warning(f"  ❌ Job failed: {data}")
                    continue
                job_id = data["data"]["id"]
                logger.debug(f"  ✅ Job: {job_id}")
                result_url = self.wait_for_job(job_id)
                if result_url:
                    resp = requests.get(result_url, timeout=120)
                    with open(output_path, "wb") as f:
                        f.write(resp.content)
                    return output_path
            except LipsyncQuotaError:
                raise
            except Exception as e:
                logger.warning(f"  ❌ LTX error: {e}")
        return None


# ==================== MULTI-TALK ====================

class WaveSpeedMultiTalkProvider(LipsyncProvider):
    """WaveSpeed InfiniteTalk multi-character video."""

    def __init__(self, config=None, api_key=None, upload_func=None):
        self.config = config
        base_url = config.get("api.urls.wavespeed") if config else None
        if not base_url:
            from modules.pipeline.exceptions import ConfigMissingKeyError
            raise ConfigMissingKeyError("api.urls.wavespeed", "WaveSpeedMultiTalkProvider")
        self.base_url = base_url
        self.api_key = api_key or (config.get("api.keys.wavespeed") if config else None)
        self.upload_func = upload_func
        self.poll_interval = config.get("generation.lipsync.poll_interval") if config else 10
        self.max_wait = config.get("generation.lipsync.max_wait") if config else 300

    def upload_file(self, file_path: str) -> Optional[str]:
        if self.upload_func:
            return self.upload_func(file_path)
        ext = Path(file_path).suffix.lstrip(".")
        content_type = f"audio/{ext}" if ext in ["mp3", "wav", "ogg"] else f"image/{ext}"
        url = f"{self.base_url}/api/v3/media/upload/binary?ext={ext}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": content_type}
        try:
            with open(file_path, "rb") as f:
                resp = requests.post(url, headers=headers, data=f, timeout=60)
            data = resp.json()
            return data.get("data", {}).get("download_url")
        except Exception as e:
            logger.warning(f"Upload error: {e}")
        return None

    def wait_for_job(self, job_id: str, max_wait: int = None) -> Optional[str]:
        url = f"{self.base_url}/api/v3/predictions/{job_id}/result"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        elapsed = 0
        interval = self.poll_interval
        max_wait = max_wait or self.max_wait
        while elapsed < max_wait:
            try:
                resp = requests.get(url, headers=headers, timeout=30)
                data = resp.json()
                status = data.get("data", {}).get("status", "processing")
                outputs = data.get("data", {}).get("outputs", [])
                if status == "completed" and outputs:
                    return outputs[0]
                elif status == "failed":
                    return None
                time.sleep(interval)
                elapsed += interval
            except Exception:
                time.sleep(interval)
                elapsed += interval
        return None

    def generate(self, image_path: str, audio_path: str,
                 output_path: str, config: Optional[GenerationLipsync] = None) -> Optional[str]:
        """Multi-talk: audio_path can be a LipsyncRequest with left_audio/right_audio."""
        cfg = config or {}
        default_retries = self.config.get("generation.lipsync.retries", 2) if self.config else 2
        retries = cfg.get("retries", default_retries) if isinstance(cfg, dict) else default_retries

        # Handle multi-audio: audio_path can be a LipsyncRequest with left/right
        if isinstance(audio_path, LipsyncRequest):
            left_audio = audio_path.left_audio
            right_audio = audio_path.right_audio
            lip_config = audio_path.config
        else:
            left_audio = audio_path
            right_audio = None
            lip_config = config

        for attempt in range(retries):
            image_url = self.upload_file(image_path)
            if not image_url:
                continue
            left_url = self.upload_file(left_audio) if left_audio else None
            right_url = self.upload_file(right_audio) if right_audio else None

            if not left_url or not right_url:
                continue

            url = f"{self.base_url}/api/v3/wavespeed-ai/infinitetalk/multi"
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            payload = {
                "image": image_url,
                "left_audio": left_url,
                "right_audio": right_url,
                "order": "left_right",
                "resolution": cfg.get("resolution", "480p")
            }
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
                data = resp.json()
                # Detect quota/credits errors
                status_code = resp.status_code
                error_msg = str(data.get("error", "") or data.get("message", "") or "").lower()
                quota_keywords = ("quota", "credit", "insufficient", "exceed", "limit", "429",
                                 "rate limit", "monthly", "free tier", "余额", "配额", "额度")
                if status_code == 429 or any(k in error_msg for k in quota_keywords):
                    logger.error(f"  ❌ InfiniteTalk QUOTA EXHAUSTED: {data}")
                    raise LipsyncQuotaError(f"WaveSpeed InfiniteTalk quota exceeded: {data}")
                if not data.get("data", {}).get("id"):
                    continue
                result_url = self.wait_for_job(data["data"]["id"])
                if result_url:
                    resp = requests.get(result_url, timeout=120)
                    with open(output_path, "wb") as f:
                        f.write(resp.content)
                    return output_path
            except LipsyncQuotaError:
                raise
            except Exception as e:
                logger.warning(f"  ❌ InfiniteTalk error: {e}")
        return None


# ==================== KIE.AI INFINITALK ====================

from modules.media.kie_ai_client import KieAIClient


class KieAIInfinitalkProvider(LipsyncProvider):
    """
    Kie.ai Infinitalk - audio-driven lip-sync (image + audio → talking head video).

    API: POST /api/v1/jobs/createTask  (model: infinitalk/from-audio)
    Poll: GET /api/v1/jobs/recordInfo?taskId=xxx

    Supports webhook callbacks via x-webhook-key header.
    """

    def __init__(self, config=None, api_key=None, webhook_key=None, upload_func=None):
        self.config = config
        base_url = config.get("api.urls.kie_ai") if config else None
        if not base_url:
            from modules.pipeline.exceptions import ConfigMissingKeyError
            raise ConfigMissingKeyError("api.urls.kie_ai", "KieAIInfinitalkProvider")
        self.base_url = base_url
        self.api_key = api_key or (config.get("api.keys.kie_ai") if config else None)
        self.webhook_key = webhook_key if webhook_key else ""
        self.upload_func = upload_func
        self.poll_interval = config.get("generation.lipsync.poll_interval") if config else 10
        self.max_wait = config.get("generation.lipsync.max_wait") if config else 300
        self._client = KieAIClient(
            api_key=self.api_key,
            webhook_key=self.webhook_key,
        )

    def generate(self, image_path: str, audio_path: str,
                 output_path: str, config: Optional[GenerationLipsync] = None) -> Optional[str]:
        """
        Kie.ai Infinitalk lip-sync: image_url + audio_url → video.

        Args:
            image_path: Local path to reference image
            audio_path: Local path to audio file (mp3/wav/etc)
            output_path: Path to save output video
            config: Optional GenerationLipsync {
                prompt: str,       # text prompt for generation
                resolution: str,    # "480p" or "720p"
                max_wait: int,      # polling timeout in seconds
            }
        """
        cfg = config or {}
        prompt = cfg.get("prompt", "A person talking")
        resolution = cfg.get("resolution", "480p")
        default_max_wait = self.max_wait if self.config else 300
        max_wait = cfg.get("max_wait", default_max_wait)
        default_poll_interval = self.poll_interval if self.config else 10

        # Upload image and audio if upload_func provided
        image_url = None
        audio_url = None

        if self.upload_func:
            image_url = self.upload_func(image_path)
            audio_url = self.upload_func(audio_path)
        if not image_url:
            image_url = cfg.get("image_url")
        if not audio_url:
            audio_url = cfg.get("audio_url")

        if not image_url or not audio_url:
            logger.warning(
                f"Kie.ai Infinitalk: missing URLs image_url={bool(image_url)} "
                f"audio_url={bool(audio_url)}. Need upload_func or config URLs."
            )
            return None

        # Submit task
        result = self._client.infinitalk(
            image_url=image_url,
            audio_url=audio_url,
            prompt=prompt,
            resolution=resolution,
        )
        if not result.get("success"):
            error_str = str(result.get("error", "")).lower()
            quota_keywords = ("quota", "credit", "insufficient", "exceed", "limit", "429",
                             "rate limit", "monthly", "free tier", "余额", "配额", "额度")
            if any(k in error_str for k in quota_keywords):
                logger.error(f"Kie.ai Infinitalk QUOTA EXHAUSTED: {result.get('error')}")
                raise LipsyncQuotaError(f"Kie.ai Infinitalk quota exceeded: {result.get('error')}")
            logger.error(f"Kie.ai Infinitalk submit failed: {result.get('error')}")
            return None

        task_id = result["task_id"]
        logger.info(f"Kie.ai Infinitalk task: {task_id}")

        # Poll for completion
        poll_result = self._client.poll_task(task_id, max_wait=max_wait, interval=default_poll_interval)
        if not poll_result.get("success"):
            error_str = str(poll_result.get("error", "")).lower()
            quota_keywords = ("quota", "credit", "insufficient", "exceed", "limit", "429",
                             "rate limit", "monthly", "free tier", "余额", "配额", "额度")
            if any(k in error_str for k in quota_keywords):
                logger.error(f"Kie.ai Infinitalk QUOTA EXHAUSTED: {poll_result.get('error')}")
                raise LipsyncQuotaError(f"Kie.ai Infinitalk quota exceeded: {poll_result.get('error')}")
            logger.error(f"Kie.ai Infinitalk failed: {poll_result.get('error')}")
            return None

        # Download output
        output_urls = poll_result.get("output_urls", [])
        if not output_urls:
            logger.error(f"Kie.ai Infinitalk: no output URLs in result")
            return None

        output_url = output_urls[0]
        try:
            resp = requests.get(output_url, timeout=120)
            with open(output_path, "wb") as f:
                f.write(resp.content)
            logger.info(f"Kie.ai Infinitalk output saved: {output_path} ({len(resp.content)/1024/1024:.1f}MB)")
            return output_path
        except Exception as e:
            logger.error(f"Kie.ai Infinitalk download error: {e}")
            return None


# ==================== REGISTER ====================

def register_lipsync_providers():
    register_provider("lipsync", "wavespeed", WaveSpeedLipsyncProvider)
    register_provider("lipsync", "multitalk", WaveSpeedMultiTalkProvider)
    register_provider("lipsync", "kieai", KieAIInfinitalkProvider)


register_lipsync_providers()
