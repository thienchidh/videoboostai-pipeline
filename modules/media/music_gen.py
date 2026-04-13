"""
modules/media/music_gen.py — Music generation providers

Provides:
- MiniMaxMusicProvider: MiniMax Music API generation
- MockMusicProvider: dry-run placeholder
"""

import os
import time
import tempfile
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from core.base_pipeline import DRY_RUN, log

# ==================== MUSIC PROVIDER BASE ====================

class MusicProvider:
    """Base class for music generation providers."""

    def generate(self, prompt: str, duration: int = 30,
                 output_path: Optional[str] = None) -> Optional[str]:
        """Generate music from text prompt. Returns path to audio file or None."""
        raise NotImplementedError


# ==================== MINIMAX MUSIC ====================

class MiniMaxMusicProvider(MusicProvider):
    """MiniMax Music API provider.

    API docs: https://platform.minimaxi.com/document/Music
    Endpoint: https://api.minimax.io/v1/music_generation
    Auth: Bearer token (same API key as TTS/Image)
    """

    def __init__(self, api_key: str, api_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = api_url or "https://api.minimax.io/v1/music_generation"

    def generate(self, prompt: str, duration: int = 30,
                 output_path: Optional[str] = None) -> Optional[str]:
        """Generate music using MiniMax Music API. Returns path to MP3 file."""
        global DRY_RUN
        if DRY_RUN:
            return mock_generate_music(prompt, duration, output_path)

        if not output_path:
            output_path = f"/tmp/music_{int(time.time()*1000)}.mp3"

        import requests
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "music-01",
            "prompt": prompt,
            "duration": duration,
        }

        try:
            logger.info(f"MiniMax Music: generating {duration}s, prompt={prompt[:80]}")
            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=120)
            data = resp.json()

            # Check for API error
            if data.get("base_resp", {}).get("status_code", 0) != 0:
                logger.warning(f"MiniMax Music API error: {data.get('base_resp', {}).get('status_msg', 'unknown')}")
                return None

            # Response structure: { data: { audio_file: { ... } } }
            # Audio returned as URL or base64
            audio_url = data.get("data", {}).get("audio_file", {}).get("url")
            if audio_url:
                # Download the audio file
                audio_resp = requests.get(audio_url, timeout=60)
                if audio_resp.status_code == 200:
                    with open(output_path, "wb") as f:
                        f.write(audio_resp.content)
                    logger.info(f"MiniMax Music saved to {output_path}")
                    return output_path

            # Alternative: base64 audio
            audio_b64 = data.get("data", {}).get("audio")
            if audio_b64:
                import base64
                audio_bytes = base64.b64decode(audio_b64)
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)
                logger.info(f"MiniMax Music saved (b64) to {output_path}")
                return output_path

            logger.warning(f"MiniMax Music: no audio in response: {data}")
            return None

        except Exception as e:
            logger.warning(f"MiniMax Music error: {e}")
            return None


# ==================== MOCK MUSIC ====================

def mock_generate_music(prompt: str, duration: int = 30,
                        output_path: Optional[str] = None) -> Optional[str]:
    """Mock music generation for dry-run mode. Creates silent audio placeholder."""
    if not output_path:
        output_path = f"/tmp/music_mock_{int(time.time()*1000)}.mp3"

    # Generate a short silent audio using ffmpeg (for testing only)
    from core.paths import get_ffmpeg
    cmd = [
        str(get_ffmpeg()), "-y",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-q:a", "9",
        output_path,
    ]
    try:
        import subprocess
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and Path(output_path).exists():
            log(f"  🎵 [MOCK] Music generated: {Path(output_path).name} ({duration}s)")
            return output_path
    except Exception as e:
        logger.warning(f"Mock music generation failed: {e}")

    log(f"  ⚠️ Mock music generation failed, skipping")
    return None


# ==================== PROVIDER REGISTRATION ====================

def register_music_providers():
    """Register music providers with the plugin registry."""
    from core.plugins import register_provider
    register_provider("music", "minimax", MiniMaxMusicProvider)
    register_provider("music", "mock", MusicProvider)  # placeholder class


# Auto-register on import
register_music_providers()
