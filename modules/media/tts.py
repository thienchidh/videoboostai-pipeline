"""
modules/media/tts.py — Text-to-Speech generation

Provides:
- MiniMaxTTSProvider: MiniMax API TTS
- EdgeTTSProvider: Edge TTS fallback
- MockTTSProvider: dry-run placeholder
"""

import json
import os
import time
import subprocess
import requests
import shutil
import tempfile
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from core.base_pipeline import (
    log
)
from core.paths import get_edge_tts, get_whisper
from core.plugins import TTSProvider, register_provider
from modules.pipeline.exceptions import ConfigMissingKeyError
from modules.pipeline.models import TechnicalConfig


# ==================== MINIMAX TTS ====================

class MiniMaxTTSProvider(TTSProvider):
    """MiniMax API text-to-speech provider."""

    def __init__(self, config: TechnicalConfig, api_key: str = None):
        """Initialize TTS provider with TechnicalConfig Pydantic model.

        Args:
            config: TechnicalConfig instance. Raises TypeError if not.
            api_key: Override API key. If not provided, read from config.api_keys.
        """
        if not isinstance(config, TechnicalConfig):
            raise TypeError(
                f"MiniMaxTTSProvider.__init__ requires a TechnicalConfig Pydantic model, "
                f"got {type(config).__name__} instead."
            )
        self._config: TechnicalConfig = config
        self._api_key = api_key or config.api_keys.minimax
        self.base_url = config.api_urls.minimax_tts
        self.model = config.generation.tts.model
        self.sample_rate = getattr(config.generation.tts, 'sample_rate', 32000)
        self.timeout = config.generation.tts.timeout
        self.bitrate = config.generation.tts.bitrate
        self.format = config.generation.tts.format
        self.channel = config.generation.tts.channel
        self._temp_dir = config.storage.temp_dir

    def _get_temp_path(self, prefix: str) -> str:
        """Get platform-aware temp file path."""
        temp_dir = self._temp_dir
        if temp_dir:
            return os.path.join(temp_dir, f"{prefix}_{int(time.time()*1000)}.mp3")
        fd, path = tempfile.mkstemp(suffix=".mp3", prefix=prefix)
        os.close(fd)
        return path

    def generate(self, text: str, voice: str = "female_voice",
                 speed: float = 1.0, output_path: Optional[str] = None) -> Optional[str]:
        """Generate TTS using MiniMax API. Returns (audio_path, word_timestamps) or (path, None)."""
        if not output_path:
            output_path = self._get_temp_path("tts_minimax")

        logger.debug(f"MiniMax TTS: voice={voice}, speed={speed}")

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "text": text,
            "stream": False,
            "output_format": "hex",
            "voice_setting": {"voice_id": voice, "speed": speed, "vol": 1, "pitch": 0},
            "audio_setting": {"sample_rate": self.sample_rate, "bitrate": self.bitrate, "format": self.format, "channel": self.channel},
            "language_boost": "Vietnamese"
        }
        logger.info(f"MiniMax TTS request: voice={voice}, speed={speed}, text_len={len(text)}")
        payload_str = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(payload_str) > 1500:
            logger.info(f"MiniMax TTS payload (truncated): {payload_str[:1500]}... [truncated]")
        else:
            logger.info(f"MiniMax TTS payload: {payload_str}")
        try:
            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=self.timeout)
            logger.info(f"MiniMax TTS response status: {resp.status_code}")
            data = resp.json()
            logger.info(f"MiniMax TTS response: {json.dumps(data, ensure_ascii=False, indent=2)[:500]}")
            if data.get("base_resp", {}).get("status_code", 0) != 0:
                logger.warning(f"MiniMax TTS error: {data.get('base_resp', {}).get('status_msg', 'unknown')}")
                return None
            audio_hex = data.get("data", {}).get("audio", "")
            if audio_hex:
                audio_bytes = bytes.fromhex(audio_hex)
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)
                return output_path
        except Exception as e:
            logger.warning(f"MiniMax TTS error: {e}")
        return None

    def get_word_timestamps(self, text: str, voice: str,
                            speed: float) -> Optional[List[Dict[str, Any]]]:
        """Get word timestamps from MiniMax TTS API."""
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "text": text,
            "stream": False,
            "output_format": "hex",
            "voice_setting": {"voice_id": voice, "speed": speed, "vol": 1, "pitch": 0},
            "audio_setting": {"sample_rate": self.sample_rate, "bitrate": self.bitrate, "format": self.format, "channel": self.channel},
            "language_boost": "Vietnamese"
        }
        word_timestamp_timeout = getattr(self._config.generation.tts, 'word_timestamp_timeout', 120)
        if word_timestamp_timeout is None:
            word_timestamp_timeout = 120
        try:
            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=word_timestamp_timeout)
            data = resp.json()
            words_data = data.get("data", {}).get("words", [])
            if words_data:
                return [
                    {"word": w.get("text", ""),
                     "start": w.get("start_time", 0) / 1000.0,
                     "end": w.get("end_time", 0) / 1000.0}
                    for w in words_data
                ]
        except Exception as e:
            logger.warning(f"Could not get MiniMax word timestamps: {e}")
        return None


# ==================== EDGE TTS ====================

class EdgeTTSProvider(TTSProvider):
    """Edge TTS provider using Python API (edge-tts package)."""

    def __init__(self, config: TechnicalConfig = None, upload_func=None):
        """Initialize Edge TTS provider with TechnicalConfig Pydantic model.

        Args:
            config: TechnicalConfig instance. Optional for backward compatibility.
            upload_func: callable(file_path) -> download_url for audio upload
        """
        self._config = config
        self.upload_func = upload_func

        # Edge TTS requires model name from config (e.g., "speech-2.8-hd")
        # Model name is stored in GenerationModels.tts, NOT in GenerationTTS
        if config and isinstance(config, TechnicalConfig):
            # model is in GenerationModels.tts (e.g., "edge" or "speech-2.8-hd")
            self._model = config.models.tts if config.models else "edge"
            self._temp_dir = config.storage.temp_dir
        else:
            self._model = "edge"
            self._temp_dir = None

    def _get_temp_path(self, prefix: str) -> str:
        """Get platform-aware temp file path."""
        temp_dir = self._temp_dir
        if temp_dir:
            return os.path.join(temp_dir, f"{prefix}_{int(time.time()*1000)}.mp3")
        fd, path = tempfile.mkstemp(suffix=".mp3", prefix=prefix)
        os.close(fd)
        return path

    def generate(self, text: str, voice: str = "female_voice",
                 speed: float = 1.0, output_path: Optional[str] = None
                 ) -> tuple[str, Optional[List[Dict[str, Any]]]] | None:
        """Generate TTS using Edge TTS. Returns (path, timestamps) tuple or None on error."""
        import asyncio
        import edge_tts

        # Edge voice mapping from config or use default
        voice_map = {
            "female_voice": "vi-VN-HoaiMyNeural",
            "male-qn-qingse": "vi-VN-NamMinhNeural",
            "female": "vi-VN-HoaiMyNeural",
            "male": "vi-VN-NamMinhNeural",
        }
        edge_voice = voice_map.get(voice, "vi-VN-HoaiMyNeural")

        if not output_path:
            output_path = self._get_temp_path("tts_edge")

        async def _generate():
            # Use Python API directly - same as test code
            comm = edge_tts.Communicate(text, edge_voice)
            await comm.save(output_path)

        try:
            # Run async generate with proper event loop policy for Windows
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            asyncio.run(_generate())

            # Verify file was created with content
            if not Path(output_path).exists() or Path(output_path).stat().st_size < 100:
                logger.warning("Edge TTS: output file missing or too small")
                return None

            # Get word timestamps
            timestamps = get_whisper_timestamps(output_path, config=self._config)

            # Upload if func provided
            if self.upload_func:
                url = self.upload_func(output_path)
                if not url:
                    logger.warning("Edge TTS: upload_func returned None")

            return (output_path, timestamps)

        except Exception as e:
            logger.warning(f"Edge TTS error: {e}")
            return None


# ==================== WHISPER TIMESTAMPS ====================

def get_whisper_timestamps(audio_path: str, output_dir: Optional[str] = None, config=None) -> Optional[List[Dict]]:
    """Get word timestamps from audio using Whisper CLI."""
    if not Path(audio_path).exists():
        return None
    if output_dir is None:
        output_dir = tempfile.mkdtemp()
    else:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    logger.debug(f"Running Whisper for word timestamps...")
    word_timestamp_timeout = config.generation.tts.word_timestamp_timeout if config and config.generation and config.generation.tts else 120

    try:
        result = subprocess.run(
            [str(get_whisper()), audio_path, "--model", "small", "--word_timestamps", "True",
             "--output_format", "json", "--output_dir", output_dir],
            capture_output=True, encoding="utf-8", errors="replace", timeout=word_timestamp_timeout
        )
        json_path = Path(output_dir) / f"{Path(audio_path).stem}.json"
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
            logger.info(f"Whisper got {len(timestamps)} word timestamps")
            return timestamps
    except Exception as e:
        logger.warning(f"Whisper error: {e}")
    return None


# ==================== REGISTER PROVIDERS ====================

def register_tts_providers():
    """Register TTS providers with the plugin registry."""
    # Note: actual API keys are injected at provider instantiation
    # This registers the classes for later use
    register_provider("tts", "minimax", MiniMaxTTSProvider)
    register_provider("tts", "edge", EdgeTTSProvider)


# Auto-register on import
register_tts_providers()