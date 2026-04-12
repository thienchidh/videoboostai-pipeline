"""
modules/media/tts.py — Text-to-Speech generation

Provides:
- MiniMaxTTSProvider: MiniMax API TTS
- EdgeTTSProvider: Edge TTS fallback
- MockTTSProvider: dry-run placeholder
"""

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
    DRY_RUN, DRY_RUN_TTS, log, mock_generate_tts
)
from core.paths import get_edge_tts, get_whisper
from core.plugins import TTSProvider, register_provider


# ==================== MINIMAX TTS ====================

class MiniMaxTTSProvider(TTSProvider):
    """MiniMax API text-to-speech provider."""

    def __init__(self, api_key: str, voice_map: Optional[Dict[str, str]] = None):
        self.api_key = api_key
        self.voice_map = voice_map or {
            "female_voice": "female_voice",
            "male-qn-qingse": "male-qn-qingse",
            "female": "female_voice",
            "male": "male-qn-qingse",
        }
        self.base_url = "https://api.minimax.io/v1/t2a_v2"

    def generate(self, text: str, voice: str = "female_voice",
                 speed: float = 1.0, output_path: Optional[str] = None) -> Optional[str]:
        """Generate TTS using MiniMax API. Returns (audio_path, word_timestamps) or (path, None)."""
        global DRY_RUN, DRY_RUN_TTS
        if DRY_RUN or DRY_RUN_TTS:
            return mock_generate_tts(text, voice, speed, output_path)

        if not output_path:
            output_path = f"/tmp/tts_{int(time.time()*1000)}.mp3"

        voice_id = self.voice_map.get(voice, "female_voice")
        logger.debug(f"MiniMax TTS: voice={voice_id}, speed={speed}")

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "speech-2.8-hd",
            "text": text,
            "stream": False,
            "output_format": "hex",
            "voice_setting": {"voice_id": voice_id, "speed": speed, "vol": 1, "pitch": 0},
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
            "language_boost": "Vietnamese"
        }
        try:
            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
            data = resp.json()
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
        voice_id = self.voice_map.get(voice, "female_voice")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "speech-2.8-hd",
            "text": text,
            "stream": False,
            "output_format": "hex",
            "voice_setting": {"voice_id": voice_id, "speed": speed, "vol": 1, "pitch": 0},
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
            "language_boost": "Vietnamese"
        }
        try:
            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
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
    """Edge TTS provider with WaveSpeed upload fallback."""

    VOICE_MAP = {
        "female_voice": "vi-VN-HoaiMyNeural",
        "male-qn-qingse": "vi-VN-NamMinhNeural",
        "female": "vi-VN-HoaiMyNeural",
        "male": "vi-VN-NamMinhNeural",
    }

    def __init__(self, upload_func=None):
        """
        Args:
            upload_func: callable(file_path) -> download_url for audio upload
        """
        self.upload_func = upload_func

    def generate(self, text: str, voice: str = "female_voice",
                 speed: float = 1.0, output_path: Optional[str] = None) -> Optional[str]:
        if not output_path:
            output_path = f"/tmp/tts_edge_{int(time.time()*1000)}.mp3"
        wav_path = output_path.replace(".mp3", ".wav")

        edge_voice = self.VOICE_MAP.get(voice, "vi-VN-HoaiMyNeural")
        rate_str = f"{'+' if speed >= 1 else '-'}{int(abs(speed - 1) * 100)}%"

        cmd = [
            str(get_edge_tts()), "--voice", edge_voice,
            "--rate", rate_str,
            "--text", text,
            "--write-media", wav_path
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
            if Path(wav_path).exists():
                if self.upload_func:
                    url = self.upload_func(wav_path)
                    if url:
                        resp = requests.get(url, timeout=60)
                        with open(output_path, "wb") as f:
                            f.write(resp.content)
                        Path(wav_path).unlink()
                        return output_path
                # Fallback: just copy wav as mp3
                shutil.copy(wav_path, output_path)
                Path(wav_path).unlink()
                return output_path
        except Exception as e:
            logger.warning(f"Edge TTS error: {e}")
        return None


# ==================== WHISPER TIMESTAMPS ====================

def get_whisper_timestamps(audio_path: str, output_dir: Optional[str] = None) -> Optional[List[Dict]]:
    """Get word timestamps from audio using Whisper CLI."""
    if not Path(audio_path).exists():
        return None
    if output_dir is None:
        output_dir = tempfile.mkdtemp()
    else:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    logger.debug(f"Running Whisper for word timestamps...")
    try:
        result = subprocess.run(
            [str(get_whisper()), audio_path, "--model", "small", "--word_timestamps", "True",
             "--output_format", "json", "--output_dir", output_dir],
            capture_output=True, text=True, timeout=120
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
