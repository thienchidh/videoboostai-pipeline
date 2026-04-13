"""
modules/media/lipsync.py — Video lipsync providers

Provides:
- WaveSpeedLipsyncProvider: WaveSpeed LTX lipsync
- MockLipsyncProvider: dry-run placeholder
"""

import os
import time
import requests
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from core.base_pipeline import log
from core.plugins import LipsyncProvider, register_provider


# ==================== WAVESPEED LIPSYNC ====================

class WaveSpeedLipsyncProvider(LipsyncProvider):
    """WaveSpeed AI LTX lipsync video generation."""

    def __init__(self, api_key: str, base_url: str = "https://api.wavespeed.ai",
                 upload_func: Optional[callable] = None):
        self.api_key = api_key
        self.base_url = base_url
        self.upload_func = upload_func

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

    def wait_for_job(self, job_id: str, max_wait: int = 300) -> Optional[str]:
        """Poll for job completion. Return output URL or None."""
        url = f"{self.base_url}/api/v3/predictions/{job_id}/result"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        elapsed = 0
        interval = 10
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
                 output_path: str, config: Optional[Dict] = None,
                 upload_func: Optional[callable] = None) -> Optional[str]:
        from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

        cfg = config or {}
        resolution = cfg.get("resolution", "480p")
        effective_upload = upload_func if upload_func is not None else self.upload_file

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _do_lipsync() -> str:
            image_url = effective_upload(image_path)
            if not image_url:
                raise ValueError("Image upload failed")
            audio_url = effective_upload(audio_path)
            if not audio_url:
                raise ValueError("Audio upload failed")

            url = f"{self.base_url}/api/v3/wavespeed-ai/ltx-2.3/lipsync"
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            payload = {"image": image_url, "audio": audio_url, "resolution": resolution}
            if cfg.get("seed"):
                payload["seed"] = cfg["seed"]

            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            data = resp.json()
            if not data.get("data", {}).get("id"):
                raise ValueError(f"Job failed: {data}")
            job_id = data["data"]["id"]
            logger.debug(f"  ✅ Job: {job_id}")
            result_url = self.wait_for_job(job_id, max_wait=300)
            if not result_url:
                raise ValueError("Lipsync job timed out")
            resp = requests.get(result_url, timeout=120)
            with open(output_path, "wb") as f:
                f.write(resp.content)
            return output_path

        try:
            return _do_lipsync()
        except Exception as e:
            logger.error(f"  ❌ LTX Lipsync failed after 3 attempts: {e}")
            return None


# ==================== KIE.AI INFINITALK ====================

import requests
from modules.media.kie_ai_client import KieAIClient


class KieAIInfinitalkProvider(LipsyncProvider):
    """
    Kie.ai Infinitalk - audio-driven lip-sync (image + audio → talking head video).

    API: POST /api/v1/jobs/createTask  (model: infinitalk/from-audio)
    Poll: GET /api/v1/jobs/recordInfo?taskId=xxx

    Supports webhook callbacks via x-webhook-key header.
    """

    def __init__(self, api_key: str, webhook_key: str = None,
                 base_url: str = "https://api.kie.ai/api/v1",
                 upload_func: Optional[callable] = None):
        self.api_key = api_key
        self.webhook_key = webhook_key if webhook_key else ""
        self.base_url = base_url
        self.upload_func = upload_func
        self._client = KieAIClient(
            api_key=self.api_key,
            webhook_key=self.webhook_key,
        )

    def generate(self, image_path: str, audio_path: str,
                 output_path: str, config: Optional[Dict] = None,
                 upload_func: Optional[callable] = None) -> Optional[str]:
        """
        Kie.ai Infinitalk lip-sync: image_url + audio_url → video.

        Args:
            image_path: Local path to reference image
            audio_path: Local path to audio file (mp3/wav/etc)
            output_path: Path to save output video
            config: Optional {
                prompt: str,       # text prompt for generation
                resolution: str,    # "480p" or "720p"
                max_wait: int,      # polling timeout in seconds
            }
            upload_func: Optional callable to use for file uploads instead of instance's
        """
        cfg = config or {}
        prompt = cfg.get("prompt", "A person talking")
        resolution = cfg.get("resolution", "480p")
        max_wait = cfg.get("max_wait", 300)

        # Upload image and audio if upload_func provided
        image_url = None
        audio_url = None
        effective_upload = upload_func if upload_func is not None else self.upload_func

        if effective_upload:
            image_url = effective_upload(image_path)
            audio_url = effective_upload(audio_path)
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
            logger.error(f"Kie.ai Infinitalk submit failed: {result.get('error')}")
            return None

        task_id = result["task_id"]
        logger.info(f"Kie.ai Infinitalk task: {task_id}")

        # Poll for completion
        poll_result = self._client.poll_task(task_id, max_wait=max_wait)
        if not poll_result.get("success"):
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
    register_provider("lipsync", "kieai", KieAIInfinitalkProvider)


register_lipsync_providers()
