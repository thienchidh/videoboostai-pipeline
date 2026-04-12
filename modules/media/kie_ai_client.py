#!/usr/bin/env python3
"""
kie_ai_client.py - Kie.ai Infinitalk API client (audio-driven lip-sync)

API: https://api.kie.ai/api/v1/
Docs: https://docs.kie.ai/market/infinitalk/from-audio

Endpoint:
  POST /api/v1/jobs/createTask
  Body: {"model": "infinitalk/from-audio", "input": {"image_url", "audio_url", "prompt", "resolution"}}
  Returns: {"code":200,"data":{"taskId":"..."}}

Poll:
  GET /api/v1/jobs/recordInfo?taskId=xxx
  Returns: {state: "waiting"|"queuing"|"generating"|"success"|"fail", resultJson: "{\"resultUrls\":[...]}"}

States: waiting, queuing, generating, success, fail
"""
import json
import time
import logging
import requests
from typing import Optional, Dict, Any
from pathlib import Path

from modules.pipeline.config_loader import MissingConfigError

logger = logging.getLogger(__name__)


class KieAIClient:
    """Kie.ai API client for Infinitalk audio-driven lip-sync."""

    BASE_URL = "https://api.kie.ai/api/v1"

    def __init__(self, api_key: str = None, webhook_key: str = None,
                 webhook_url: str = None, timeout: int = 30):
        if not api_key:
            raise MissingConfigError("KieAI api_key is required")
        self.api_key = api_key
        self.webhook_key = webhook_key if webhook_key else ""
        self.webhook_url = webhook_url if webhook_url else ""
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        logger.info(f"KieAIClient init: api_key={api_key[:10] if api_key else 'NONE'}..., base_url={self.BASE_URL}")

    # ─── Infinitalk (audio-driven lip-sync) ───────────────────────

    def infinitalk(self, image_url: str, audio_url: str,
                   prompt: str = "A person talking",
                   resolution: str = "480p",
                   callback_url: str = None) -> Dict[str, Any]:
        """
        Submit Infinitalk lip-sync job (image + audio → talking head video).

        Args:
            image_url: Public URL of reference image (jpeg/png/webp, max 10MB)
            audio_url: Public URL of audio file (mpeg/wav/aac/mp4/ogg, max 10MB)
            prompt: Text prompt to guide generation
            resolution: "480p" or "720p"
            callback_url: Optional webhook for async notification

        Returns:
            {"success": True, "task_id": "...", "data": {...}}
            or {"success": False, "error": "..."}
        """
        url = f"{self.BASE_URL}/jobs/createTask"
        payload = {
            "model": "infinitalk/from-audio",
            "input": {
                "image_url": image_url,
                "audio_url": audio_url,
                "prompt": prompt,
                "resolution": resolution,
            }
        }
        if callback_url or self.webhook_url:
            payload["callBackUrl"] = callback_url or self.webhook_url

        auth_hdr = self.session.headers.get('Authorization', '')
        logger.info(f"Kie.ai Infinitalk request: url={url}, auth={auth_hdr[:30]}, payload={payload}")
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            data = resp.json()
            logger.info(f"Kie.ai Infinitalk response: status={resp.status_code}, body={data}")

            if resp.status_code == 200 and data.get("code") == 200:
                task_id = data.get("data", {}).get("taskId") or data.get("data", {}).get("recordId")
                logger.info(f"Kie.ai Infinitalk task submitted: {task_id}")
                return {"success": True, "task_id": task_id, "data": data}
            else:
                logger.error(f"Kie.ai Infinitalk failed: {resp.status_code} {data}")
                return {"success": False, "error": data, "status_code": resp.status_code}

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Request timeout"}
        except Exception as e:
            logger.error(f"Kie.ai Infinitalk error: {e}")
            return {"success": False, "error": str(e)}

    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Get task status and result."""
        url = f"{self.BASE_URL}/jobs/recordInfo?taskId={task_id}"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            data = resp.json()
            if resp.status_code == 200:
                return {"success": True, "data": data.get("data", {})}
            return {"success": False, "error": data, "status_code": resp.status_code}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def poll_task(self, task_id: str, interval: int = 5,
                  max_wait: int = 600) -> Dict[str, Any]:
        """
        Poll task until completion.

        Returns:
            {"success": True, "data": {...}, "output_urls": [...]}
            or {"success": False, "error": "..."}
        """
        start = time.time()
        while time.time() - start < max_wait:
            result = self.get_task(task_id)
            if not result["success"]:
                return result

            task_data = result.get("data", {})
            state = task_data.get("state", "")

            if state == "success":
                result_json_str = task_data.get("resultJson", "")
                if isinstance(result_json_str, str):
                    try:
                        result_json = json.loads(result_json_str)
                    except Exception:
                        result_json = {}
                else:
                    result_json = result_json_str

                output_urls = result_json.get("resultUrls", [])
                logger.info(f"Task {task_id} completed: {len(output_urls)} output(s)")
                return {
                    "success": True,
                    "data": task_data,
                    "output_urls": output_urls,
                    "result_json": result_json,
                }

            if state in ("fail", "failed"):
                fail_msg = task_data.get("failMsg", "Unknown error")
                logger.error(f"Task {task_id} failed: {fail_msg}")
                return {"success": False, "error": fail_msg, "data": task_data}

            logger.debug(f"Task {task_id}: {state} ({int(time.time()-start)}s)")
            time.sleep(interval)

        return {"success": False, "error": "Polling timeout"}

    # ─── Account ─────────────────────────────────────────────────

    def get_balance(self) -> Dict[str, Any]:
        """Get account balance/credits."""
        url = f"{self.BASE_URL}/account/balance"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            data = resp.json()
            if resp.status_code == 200:
                return {"success": True, "data": data}
            return {"success": False, "error": data, "status_code": resp.status_code}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ─── CLI test ────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.environ.get("KIE_AI_API_KEY", "")
    if not api_key:
        print("Set KIE_AI_API_KEY")
        sys.exit(1)

    client = KieAIClient()
    print("Balance:", json.dumps(client.get_balance(), indent=2))