"""
modules/media/image_gen.py — Image generation providers

Provides:
- MiniMaxImageProvider: MiniMax image-01 API
- WaveSpeedImageProvider: WaveSpeed AI fallback
- MockImageProvider: dry-run placeholder
"""

import os
import sys
import time
import requests
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.base_pipeline import DRY_RUN, DRY_RUN_IMAGES, log, mock_generate_image
from core.plugins import ImageProvider, register_provider


# ==================== MINIMAX IMAGE ====================

class MiniMaxImageProvider(ImageProvider):
    """MiniMax image generation (image-01 model)."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = "https://api.minimax.io/v1/image_generation"

    def generate(self, prompt: str, output_path: str,
                 aspect_ratio: str = "9:16") -> Optional[str]:
        global DRY_RUN, DRY_RUN_IMAGES
        if DRY_RUN or DRY_RUN_IMAGES:
            return mock_generate_image(prompt, output_path)

        logger.debug(f"MiniMax image: {prompt[:50]}...")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": "image-01", "prompt": prompt, "aspect_ratio": aspect_ratio, "num_images": 1}

        try:
            resp = requests.post(self.url, headers=headers, json=payload, timeout=180)
            data = resp.json()
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
        global DRY_RUN, DRY_RUN_IMAGES
        if DRY_RUN or DRY_RUN_IMAGES:
            return mock_generate_image(prompt, output_path)

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


# ==================== REGISTER PROVIDERS ====================

def register_image_providers():
    register_provider("image", "minimax", MiniMaxImageProvider)
    register_provider("image", "wavespeed", WaveSpeedImageProvider)


register_image_providers()
