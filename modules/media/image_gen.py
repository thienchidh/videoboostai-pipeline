"""
modules/media/image_gen.py — Image generation providers

Provides:
- MiniMaxImageProvider: MiniMax image-01 API
- WaveSpeedImageProvider: WaveSpeed AI fallback
- MockImageProvider: dry-run placeholder
"""

import json
import os
import time
import requests
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from core.base_pipeline import log
from core.plugins import ImageProvider, register_provider


# ==================== MINIMAX IMAGE ====================

class MiniMaxImageProvider(ImageProvider):
    """MiniMax image generation (image-01 model)."""

    DEFAULT_URL = "https://api.minimax.io/v1/image_generation"

    def __init__(self, api_key: str, api_url: Optional[str] = None):
        self.api_key = api_key
        self.api_url = api_url or self.DEFAULT_URL

    def generate(self, prompt: str, output_path: str,
                 aspect_ratio: str = "9:16") -> Optional[str]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": "image-01", "prompt": prompt, "aspect_ratio": aspect_ratio, "num_images": 1}
        logger.info(f"MiniMax image request: aspect_ratio={aspect_ratio}, prompt_len={len(prompt)}")
        payload_str = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(payload_str) > 1500:
            logger.info(f"MiniMax image payload (truncated): {payload_str[:1500]}... [truncated]")
        else:
            logger.info(f"MiniMax image payload: {payload_str}")
        try:
            resp = requests.post(self.api_url, headers=headers, json=payload, timeout=180)
            logger.info(f"MiniMax image response status: {resp.status_code}")
            data = resp.json()
            logger.info(f"MiniMax image response: {json.dumps(data, ensure_ascii=False, indent=2)[:500]}")
            img_url = None
            if isinstance(data.get("data"), dict):
                urls = data["data"].get("image_urls", [])
                if urls:
                    img_url = urls[0]
            if not img_url:
                urls = data.get("image_urls", [])
                if urls:
                    img_url = urls[0]
            if not img_url:
                logger.warning(f"MiniMax image: no URL in response — {data}")
                return None
            resp = requests.get(img_url, timeout=120)
            with open(output_path, "wb") as f:
                f.write(resp.content)
            return output_path
        except Exception as e:
            logger.warning(f"MiniMax image error: {e}")
        return None


# ==================== WAVESPEED IMAGE ====================

class WaveSpeedImageProvider(ImageProvider):
    """WaveSpeed AI image generation via MiniMax image-01."""

    def __init__(self, api_key: str, base_url: str = "https://api.wavespeed.ai"):
        self.api_key = api_key
        self.base_url = base_url
        self.submit_url = f"{base_url}/api/v3/minimax/image-01/text-to-image"

    def _submit_job(self, prompt: str, size: str) -> Optional[str]:
        """Submit image job, return job_id or None."""
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"prompt": prompt, "size": size}
        try:
            resp = requests.post(self.submit_url, headers=headers, json=payload, timeout=30)
            data = resp.json()
            if data.get("code") == 200 and data.get("data"):
                return data["data"]["id"]
            logger.warning(f"WaveSpeed submit failed: {data}")
        except Exception as e:
            logger.warning(f"WaveSpeed submit error: {e}")
        return None

    def _poll_job(self, job_id: str) -> Optional[str]:
        """Poll for job completion, return image URL or None."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        get_url = f"{self.base_url}/api/v3/predictions/{job_id}/result"
        for attempt in range(24):
            time.sleep(5)
            try:
                resp = requests.get(get_url, headers=headers, timeout=15)
                result = resp.json()
                if result.get("code") != 200:
                    break
                status = result.get("data", {}).get("status", "")
                if status == "completed":
                    outputs = result.get("data", {}).get("outputs", [])
                    if outputs:
                        return outputs[0]
                elif status == "failed":
                    logger.warning(f"WaveSpeed failed: {result.get('data', {}).get('error', 'unknown')}")
                    break
            except Exception as e:
                logger.warning(f"WaveSpeed poll error: {e}")
        return None

    def generate(self, prompt: str, output_path: str,
                 aspect_ratio: str = "9:16") -> Optional[str]:
        if aspect_ratio == "9:16":
            size = "1080*1920"
        elif aspect_ratio == "16:9":
            size = "1920*1080"
        else:
            size = "1024*1024"

        logger.debug(f"WaveSpeed image: {prompt[:50]}...")
        job_id = self._submit_job(prompt, size)
        if not job_id:
            return None

        img_url = self._poll_job(job_id)
        if not img_url:
            return None

        try:
            resp = requests.get(img_url, timeout=120)
            with open(output_path, "wb") as f:
                f.write(resp.content)
            return output_path
        except Exception as e:
            logger.warning(f"WaveSpeed download error: {e}")
        return None


# ==================== KIE Z IMAGE ====================

class KieImageProvider(ImageProvider):
    """Kie.ai Z Image API - async image generation.

    API: POST https://api.kie.ai/api/v1/jobs/createTask (model=z-image)
         GET  https://api.kie.ai/api/v1/jobs/recordInfo?taskId=xxx
    """

    BASE_URL = "https://api.kie.ai/api/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

    def generate(self, prompt: str, output_path: str,
                 aspect_ratio: str = "9:16") -> Optional[str]:
        """Generate image via Z Image API with polling."""
        # Map aspect ratio to Z Image format
        ratio_map = {"9:16": "9:16", "16:9": "16:9", "1:1": "1:1", "4:3": "4:3", "3:4": "3:4"}
        z_ratio = ratio_map.get(aspect_ratio, "9:16")

        payload = {
            "model": "z-image",
            "input": {
                "prompt": prompt[:1000],  # Z Image max 1000 chars
                "aspect_ratio": z_ratio,
                "nsfw_checker": False,
            }
        }
        logger.info(f"Kie Z Image request: aspect_ratio={z_ratio}, prompt_len={len(prompt)}")
        payload_str = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(payload_str) > 1500:
            logger.info(f"Kie Z Image payload (truncated): {payload_str[:1500]}... [truncated]")
        else:
            logger.info(f"Kie Z Image payload: {payload_str}")

        # Step 1: Create task
        try:
            resp = self.session.post(
                f"{self.BASE_URL}/jobs/createTask",
                json=payload,
                timeout=30,
            )
            data = resp.json()
            logger.info(f"Kie Z Image create response: {resp.status_code}, {json.dumps(data, ensure_ascii=False)[:300]}")
            if resp.status_code != 200 or data.get("code") != 200:
                logger.warning(f"Kie Z Image create failed: {data}")
                return None
            task_id = data.get("data", {}).get("taskId")
            if not task_id:
                logger.warning(f"Kie Z Image: no taskId in response: {data}")
                return None
            logger.info(f"Kie Z Image task submitted: {task_id}")
        except Exception as e:
            logger.warning(f"Kie Z Image create error: {e}")
            return None

        # Step 2: Poll for completion
        img_url = self._poll_task(task_id)
        if not img_url:
            return None

        # Step 3: Download
        try:
            resp = requests.get(img_url, timeout=120)
            with open(output_path, "wb") as f:
                f.write(resp.content)
            logger.info(f"Kie Z Image downloaded: {output_path} ({Path(output_path).stat().st_size} bytes)")
            return output_path
        except Exception as e:
            logger.warning(f"Kie Z Image download error: {e}")
        return None

    def _poll_task(self, task_id: str, interval: int = 5,
                   max_wait: int = 300) -> Optional[str]:
        """Poll task until success, return image URL or None."""
        start = time.time()
        while time.time() - start < max_wait:
            try:
                resp = self.session.get(
                    f"{self.BASE_URL}/jobs/recordInfo?taskId={task_id}",
                    timeout=30,
                )
                data = resp.json()
                if resp.status_code != 200:
                    logger.warning(f"Kie Z Image poll status {resp.status_code}: {data}")
                    time.sleep(interval)
                    continue

                task_data = data.get("data", {})
                state = task_data.get("state", "")

                if state == "success":
                    result_json_str = task_data.get("resultJson", "")
                    if isinstance(result_json_str, str):
                        try:
                            result_json = json.loads(result_json_str)
                        except Exception:
                            result_json = {}
                    else:
                        result_json = result_json_str or {}
                    urls = result_json.get("resultUrls", [])
                    if urls:
                        logger.info(f"Kie Z Image task {task_id} completed: {urls[0]}")
                        return urls[0]
                    logger.warning(f"Kie Z Image task {task_id} success but no URLs: {result_json}")
                    return None

                if state in ("fail", "failed"):
                    fail_msg = task_data.get("failMsg", "Unknown error")
                    fail_code = task_data.get("failCode", "")
                    logger.warning(f"Kie Z Image task {task_id} failed: {fail_code} {fail_msg}")
                    return None

                logger.debug(f"Kie Z Image task {task_id}: {state} ({int(time.time()-start)}s)")
                time.sleep(interval)

            except Exception as e:
                logger.warning(f"Kie Z Image poll error: {e}")
                time.sleep(interval)

        logger.warning(f"Kie Z Image task {task_id} polling timeout after {max_wait}s")
        return None


# ==================== REGISTER PROVIDERS ====================

def register_image_providers():
    register_provider("image", "minimax", MiniMaxImageProvider)
    register_provider("image", "wavespeed", WaveSpeedImageProvider)
    register_provider("image", "kieai", KieImageProvider)


register_image_providers()
