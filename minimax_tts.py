#!/usr/bin/env python3
"""
MiniMax Text to Speech via API
Usage: python3 minimax_tts.py "text to speak" [voice_id] [speed]
"""

import requests
import json
import sys
import os
import base64
from pathlib import Path

# Add project root for core.paths import
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from core.paths import get_config_path

# Load API key from auth-profiles.json
def get_api_key():
    auth_file = get_config_path("agents/main/agent/auth-profiles.json")
    if auth_file.exists():
        with open(auth_file) as f:
            data = json.load(f)
            profiles = data.get("profiles", {})
            for k, v in profiles.items():
                if v.get("type") == "api_key" and v.get("provider") == "minimax":
                    return v.get("key")
    return None

API_KEY = get_api_key()
BASE_URL = "https://api.minimax.io/v1/t2a_v2"

# Voice options - verified working voices
VOICES = {
    "en_us": "English_expressive_narrator",
    "male": "male-qn-qingse",
    "female": "female_voice",
    "narrator": "Narrator",
    "default": "male-qn-qingse",
    "vi_female": "female_voice",
    "speech-01": "speech-01",
}

# Languages that benefit from language_boost
LANGUAGE_BOOST_LANGS = ["vietnamese", "vi", "vn", "tieng viet"]

def text_to_speech(text, voice_id="English_expressive_narrator", speed=1.0, stream=False, language=None):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "speech-2.8-hd",
        "text": text,
        "stream": stream,
        "output_format": "hex",
        "voice_setting": {
            "voice_id": voice_id,
            "speed": speed,
            "vol": 1,
            "pitch": 0
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1
        }
    }
    
    # Add language_boost for Vietnamese
    if language:
        payload["language_boost"] = language
    else:
        # Auto-detect Vietnamese in text
        text_lower = text.lower()
        for lang in LANGUAGE_BOOST_LANGS:
            if lang in text_lower:
                payload["language_boost"] = "Vietnamese"
                break
    
    print(f"🎤 Đang chuyển text sang giọng nói...", file=sys.stderr)
    print(f" Voice: {voice_id}, Speed: {speed}x", file=sys.stderr)
    
    resp = requests.post(BASE_URL, headers=headers, json=payload, timeout=60)
    data = resp.json()
    
    if data.get("base_resp", {}).get("status_code") != 0:
        err = data.get("base_resp", {})
        print(f"❌ Lỗi {err.get('status_code')}: {err.get('status_msg')}", file=sys.stderr)
        return None
    
    return data

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 minimax_tts.py 'text to speak' [voice] [speed]")
        print(f"Available voices: {', '.join(VOICES.keys())}")
        print("Default: en_us, Speed: 1.0")
        sys.exit(1)
    
    text = sys.argv[1]
    voice_key = sys.argv[2] if len(sys.argv) > 2 else "en_us"
    speed = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    
    voice_id = VOICES.get(voice_key, voice_key)
    
    result = text_to_speech(text, voice_id, speed)
    
    if result:
        audio_hex = result.get("data", {}).get("audio", "")
        extra = result.get("extra_info", {})
        
        if audio_hex:
            # Convert hex to binary
            audio_bytes = bytes.fromhex(audio_hex)
            
            # Save as mp3
            out_dir = Path.home() / "workspace" / "downloads"
            out_dir.mkdir(parents=True, exist_ok=True)
            fname = out_dir / "tts_output.mp3"
            with open(fname, "wb") as f:
                f.write(audio_bytes)
            
            print(f"✅ Audio saved: {fname}", file=sys.stderr)
            print(f" Duration: {extra.get('audio_length', 0)/1000:.1f}s", file=sys.stderr)
            print(f" Size: {extra.get('audio_size', 0)/1024:.1f} KB", file=sys.stderr)
            print(str(fname))
        else:
            print("No audio returned", file=sys.stderr)
