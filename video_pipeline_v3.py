#!/usr/bin/env python3
"""
Video Pipeline v3 - ENHANCED
- JSON config driven
- MiniMax TTS + MiniMax Image (with WaveSpeed fallback)
- WaveSpeed LTX Lipsync (requires URL upload)
- Retry mechanisms
- Subtitle generation with karaoke style
- Enhanced resume logic with step tracking
- Dry-run mode for testing without API calls
"""

import os
import sys
import json
import time
import subprocess
import requests
import shutil
from pathlib import Path
import db

from modules.media.lipsync import KieAIInfinitalkProvider


# ==================== DRY RUN FLAGS ====================
DRY_RUN = False          # Full dry-run: mock ALL API calls
DRY_RUN_TTS = False       # Mock only TTS
DRY_RUN_IMAGES = False    # Mock only image generation
FORCE_START = False       # Force fresh start (ignore previous scene cache)
UPLOAD_TO_SOCIALS = False # Upload to FB/TikTok after generation

# Detect best python for karaoke/watermark (needs PIL from venv or linuxbrew)
LINUXBREW_PYTHON = "/home/linuxbrew/.linuxbrew/bin/python3"
VENV_PYTHON = str(Path(__file__).parent / "venv" / "bin" / "python3")
SYSTEM_PYTHON = "/usr/bin/python3"


def get_karaoke_python():
    """Return python with PIL/numpy installed (venv > linuxbrew > system)"""
    if os.path.exists(VENV_PYTHON):
        return VENV_PYTHON
    if os.path.exists(LINUXBREW_PYTHON):
        return LINUXBREW_PYTHON
    return SYSTEM_PYTHON

sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ==================== DRY RUN MOCK FUNCTIONS ====================
def mock_generate_tts(text, voice="female_voice", speed=1.0, output_path=None):
    """Generate fake TTS audio using ffmpeg (silence + tone)"""
    log(f"  🔴 DRY RUN: mock_generate_tts - using placeholder audio")
    if not output_path:
        output_path = f"/tmp/tts_dryrun_{int(time.time()*1000)}.mp3"

    # Use ffmpeg to generate a short audio with a simple tone/silence
    # Estimate duration based on text length (~3 chars per second for Vietnamese)
    estimated_duration = max(2.0, len(text) / 3.0)

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={estimated_duration}",
        "-af", f"atempo={speed}",
        "-ar", "32000", "-ac", "1", "-ab", "128k",
        output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
        if Path(output_path).exists():
            log(f"  🔴 DRY RUN: TTS placeholder created: {Path(output_path).stat().st_size/1024:.1f}KB")
            return output_path
    except Exception as e:
        log(f"  🔴 DRY RUN: TTS fallback error: {e}")

    # Ultimate fallback: create empty file
    Path(output_path).touch()
    return output_path


def mock_generate_image(prompt, output_path):
    """Generate a solid color placeholder image using PIL or ffmpeg fallback"""
    log(f"  🔴 DRY RUN: mock_generate_image - using placeholder image")
    try:
        from PIL import Image
        # Create 1080x1920 (9:16 vertical) solid color image
        img = Image.new('RGB', (1080, 1920), color=(100, 150, 200))
        img.save(output_path)
        log(f"  🔴 DRY RUN: Image placeholder created: {Path(output_path).stat().st_size/1024:.1f}KB")
        return output_path
    except Exception as e:
        log(f"  🔴 DRY RUN: PIL not available ({e}), trying ffmpeg...")

    # Fallback: use ffmpeg to generate a solid color image
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=0x6496C8:s=1080x1920:d=1",
        "-frames:v", "1",
        output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
        if Path(output_path).exists():
            log(f"  🔴 DRY RUN: Image placeholder created (ffmpeg): {Path(output_path).stat().st_size/1024:.1f}KB")
            return output_path
    except Exception as e:
        log(f"  🔴 DRY RUN: Image ffmpeg fallback error: {e}")
    return None


def mock_lipsync_video(image_path, audio_path, output_path):
    """Generate fake lipsync video using ffmpeg (static image + audio)"""
    log(f"  🔴 DRY RUN: mock_lipsync_video - using placeholder video")

    # Get audio duration
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", audio_path],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip() or 5.0)

    # Create video from image + audio using ffmpeg
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60)
        if Path(output_path).exists():
            log(f"  🔴 DRY RUN: Lipsync placeholder created: {Path(output_path).stat().st_size/1024/1024:.1f}MB")
            return output_path
    except Exception as e:
        log(f"  🔴 DRY RUN: Lipsync fallback error: {e}")
    return None

def deep_merge(base, override):
    """Deep merge override into base. Override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

class VideoPipelineV3:
    def __init__(self, config_path):
        global FORCE_START
        # Load config: auto-loads technical base config, then merges business config
        # Business config path relative to configs/business/ or absolute
        config_path = Path(config_path)
        
        # Find technical config
        tech_config_path = Path(__file__).parent / "configs" / "technical" / "config_technical.json"
        if not tech_config_path.exists():
            tech_config_path = Path.home() / ".openclaw/workspace-videopipeline/configs/technical/config_technical.json"
        
        if not tech_config_path.exists():
            log(f"❌ Technical config not found: {tech_config_path}")
            raise FileNotFoundError(f"Technical config not found at {tech_config_path}")
        
        with open(tech_config_path) as f:
            self.config = json.load(f)
        log(f"📋 Technical base config: {tech_config_path}")
        
        # Load and merge business config
        if config_path.name == "config_technical.json":
            # Only technical config provided
            log(f"📋 Using technical config only (no business config)")
        else:
            # Business config path
            if not config_path.exists():
                # Try relative to configs/business/
                biz_path = Path(__file__).parent / "configs" / "business" / config_path
                if biz_path.exists():
                    config_path = biz_path
            
            with open(config_path) as f:
                biz_config = json.load(f)
            self.config = deep_merge(self.config, biz_config)
            log(f"📋 Business config: {config_path}")

        # Load secrets file (API keys)
        # Load API secrets from configs/api/secrets.json (keys only)
        # Falls back to video_config_secrets.json for backward compat
        secrets_path = Path(__file__).parent / "configs" / "api" / "secrets.json"
        if not secrets_path.exists():
            secrets_path = Path(__file__).parent / "video_config_secrets.json"
        if not secrets_path.exists():
            secrets_path = Path.home() / ".openclaw/workspace-videopipeline/configs/api/secrets.json"
        if secrets_path.exists():
            with open(secrets_path) as f:
                secrets_data = json.load(f)
            # Merge secrets directly (not wrapped in {"api":}) to avoid nesting
            self.config = deep_merge(self.config, secrets_data)
            log(f"📋 Secrets loaded from {secrets_path}")
        
        # Handle case where secrets file has placeholder values
        # Handle WaveSpeed key
        if self.config.get("api", {}).get("wavespeed_key") == "REPLACE_WITH_YOUR_WAVESPEED_KEY":
            log(f"⚠️ Using default WaveSpeed key from TOOLS.md")
            self.wsp_key = self._get_wavespeed_key()
        else:
            self.wsp_key = self.config.get("api", {}).get("wavespeed_key", "")
        self.wsp_base = "https://api.wavespeed.ai"

        # Handle Kie.ai key
        self.kieai_key = self.config.get("api", {}).get("kie_ai_key", "")
        self.kieai_webhook_key = self.config.get("api", {}).get("kie_ai_webhook_key", "")
        if self.kieai_key:
            log(f"✅ Kie.ai configured (key: ...{self.kieai_key[-6:]})")

        # Lipsync provider selection: "wavespeed" (default) or "kieai"
        self.lipsync_provider = self.config.get("lipsync", {}).get("provider", "wavespeed")
        if self.lipsync_provider == "kieai" and self.kieai_key:
            log(f"🔀 Using Kie.ai Infinitalk for lipsync")
        elif self.lipsync_provider == "kieai" and not self.kieai_key:
            log(f"⚠️ Kie.ai selected but no kie_ai_key - falling back to WaveSpeed")
            self.lipsync_provider = "wavespeed"

        self.minimax_key = self._load_minimax_key()
        
        self.ws_dir = Path.home() / ".openclaw" / "workspace"
        self.avatars_dir = self.ws_dir / "avatars"
        self.output_dir = self.ws_dir / "video_v3_output"
        self.media_dir = Path.home() / ".openclaw" / "media"
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.avatars_dir.mkdir(parents=True, exist_ok=True)

        self.timestamp = int(time.time())
        import secrets
        self.run_id = secrets.token_hex(4)  # 8-char hex unique ID
        self.run_dir = self.output_dir / f"run_{self.timestamp}_{self.run_id}"
        self.run_dir.mkdir(exist_ok=True)

        # If FORCE_START, clear previous scene cache from all run dirs
        if FORCE_START:
            log(f"🆕 Clearing previous scene cache...")
            base = Path.home() / ".openclaw/workspace/video_v3_output"
            for run_dir in base.glob("run_*"):
                if run_dir == self.run_dir:
                    continue
                for scene_dir in run_dir.glob("scene_*"):
                    for f in scene_dir.glob("*.mp4"):
                        f.unlink(missing_ok=True)
                        log(f"  🗑️ Deleted {f.name} from {scene_dir.name}")

        # Initialize DB and create video_run record
        db.init_db()
        project_name = self.config.get("video", {}).get("title", "default")
        project_id = db.get_or_create_project(project_name)
        config_name = str(config_path)
        self.run_id = db.start_video_run(project_id, config_name)
        log(f"📊 DB video_run started: id={self.run_id}")
        
        log(f"🎬 Video Pipeline v3 - {self.config.get('video', {}).get('title', 'Untitled')}")
        log(f"📁 Output: {self.run_dir}")

    def _get_wavespeed_key(self):
        """Get WaveSpeed key from TOOLS.md"""
        tools_file = Path.home() / ".openclaw/workspace/TOOLS.md"
        if tools_file.exists():
            content = tools_file.read_text()
            import re
            match = re.search(r'wavespeed.*?([a-f0-9]{64})', content, re.IGNORECASE)
            if match:
                return match.group(1)
        return ""

    def _find_previous_scene_output(self, scene_id):
        """Find a scene video from a previous run to reuse (avoids re-generating)."""
        import glob
        base = Path("/home/openclaw-personal/.openclaw/workspace/video_v3_output")
        runs = sorted(base.glob("run_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for run in runs:
            if run == self.run_dir:
                continue  # skip current run
            # Check for scene video
            candidates = [
                run / f"scene_{scene_id}" / "video_9x16.mp4",
                run / f"scene_{scene_id}" / "video_9x16_subtitled.mp4",
            ]
            for candidate in candidates:
                if candidate.exists():
                    age_min = (time.time() - candidate.stat().st_mtime) / 60
                    log(f"  ♻️ Found previous scene_{scene_id}: {candidate} ({age_min:.0f}m old)")
                    return candidate
        return None

    def _reuse_or_generate_scene(self, scene_id, scene_output):
        """Copy scene from previous run if exists, else return False."""
        prev = self._find_previous_scene_output(scene_id)
        if prev:
            import shutil
            dest = scene_output / "video_9x16.mp4"
            shutil.copy2(str(prev), str(dest))
            log(f"  ✅ Copied scene_{scene_id} from previous run: {dest.stat().st_size/1024/1024:.1f}MB")
            return True
        return False


    def _load_config(self):
        """Load and log config"""
        log(f"\n{'='*60}")
        log(f"📋 CONFIG LOADED: {self.config['video']['title']}")
        log(f"{'='*60}")
        log(f"  🎭 Characters: {len(self.config.get('characters', []))}")
        for char in self.config.get('characters', []):
            log(f"    - {char['name']}: avatar={char.get('avatar_file', 'none')}, voice={char.get('tts_voice', '?')}")
        log(f"  🎬 Scenes: {len(self.config.get('scenes', []))}")
        for scene in self.config.get('scenes', []):
            chars = scene.get('characters', [])
            log(f"    - Scene {scene.get('id','?')}: {len(chars)} char(s) - {scene.get('script','')[:40]}...")
        log(f"  📁 Output dir: {self.run_dir}")
        log(f"{'='*60}\n")

    def _load_minimax_key(self):
        auth_file = Path.home() / ".openclaw/agents/main/agent/auth-profiles.json"
        if auth_file.exists():
            with open(auth_file) as f:
                data = json.load(f)
                for k, v in data.get("profiles", {}).items():
                    if v.get("provider") == "minimax":
                        return v.get("key")
        return self.config["api"].get("minimax_key", "")

    # ==================== UPLOAD ====================
    def upload_file(self, file_path):
        """Upload file to WaveSpeedAI"""
        ext = Path(file_path).suffix.lstrip(".")
        content_type = f"audio/{ext}" if ext in ["mp3", "wav", "ogg"] else f"image/{ext}"
        url = f"{self.wsp_base}/api/v3/media/upload/binary?ext={ext}"
        headers = {"Authorization": f"Bearer {self.wsp_key}", "Content-Type": content_type}
        log(f"  🔍 Upload debug: url={url}, key={self.wsp_key[:10]}...")
        try:
            with open(file_path, "rb") as f:
                resp = requests.post(url, headers=headers, data=f, timeout=60)
            log(f"  🔍 Upload resp: status={resp.status_code}, headers={dict(resp.headers)}")
            data = resp.json()
            if data.get("data", {}).get("download_url"):
                return data["data"]["download_url"]
            log(f"  ❌ Upload failed: {data}")
        except Exception as e:
            log(f"  ❌ Upload error: {e}")
        return None

    # ==================== TTS ====================
    def generate_tts_minimax(self, text, voice_key="female_voice", speed=1.0, output_path=None, emotion=None):
        """Generate TTS using MiniMax API

        Args:
            voice_key: voice id - supports female_2, female_voice, male-qn-qingse
            speed: 0.5-2.0 (default 1.0)
            output_path: output file path
            emotion: "happy", "sad", "calm", "neutral" (optional)
        """
        global DRY_RUN, DRY_RUN_TTS
        if DRY_RUN or DRY_RUN_TTS:
            return mock_generate_tts(text, voice_key, speed, output_path)
        if not output_path:
            output_path = f"/tmp/tts_{self.timestamp}_{int(time.time()*1000)}.mp3"

        # Map config voice keys to MiniMax voice IDs
        voice_map = {
            "female_voice": "female_voice",
            "female_2": "female_2",
            "male-qn-qingse": "male-qn-qingse",
            "male": "male-qn-qingse",
            "male_voice": "male-qn-qingse",
            "female": "female_voice",
        }
        voice_id = voice_map.get(voice_key, voice_key)  # fallback to raw key

        voice_setting = {"voice_id": voice_id, "speed": speed, "vol": 1, "pitch": 0}
        if emotion:
            voice_setting["emotion"] = emotion

        url = "https://api.minimax.io/v1/t2a_v2"
        headers = {"Authorization": f"Bearer {self.minimax_key}", "Content-Type": "application/json"}
        payload = {
            "model": "speech-2.8-hd", "text": text, "stream": False, "output_format": "hex",
            "voice_setting": voice_setting,
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
            "language_boost": "Vietnamese"
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            data = resp.json()
            if data.get("base_resp", {}).get("status_code", 0) != 0:
                log(f"  ❌ MiniMax TTS error: {data.get('base_resp', {}).get('status_msg', 'unknown')}")
                return None
            audio_hex = data.get("data", {}).get("audio", "")
            if audio_hex:
                audio_bytes = bytes.fromhex(audio_hex)
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)
                return output_path
        except Exception as e:
            log(f"  ❌ MiniMax TTS error: {e}")
        return None

    def generate_tts_edge(self, text, voice="female_voice", speed=1.0, output_path=None):
        """Generate TTS using Edge TTS + upload to WaveSpeed"""
        if not output_path:
            output_path = f"/tmp/tts_{self.timestamp}_{int(time.time()*1000)}.mp3"
        wav_path = output_path.replace(".mp3", ".wav")
        edge_map = {"female_voice": "vi-VN-HoaiMyNeural", "male-qn-qingse": "vi-VN-NamMinhNeural",
                   "female": "vi-VN-HoaiMyNeural", "male": "vi-VN-NamMinhNeural"}
        edge_voice = edge_map.get(voice, "vi-VN-HoaiMyNeural")
        cmd = ["edge-tts", "--voice", edge_voice, "--rate", f"{'+' if speed >= 1 else '-'}{int(abs(speed - 1) * 100)}%",
               "--text", text, "--write-media", wav_path]
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
            if Path(wav_path).exists():
                url = self.upload_file(wav_path)
                if url:
                    resp = requests.get(url, timeout=60)
                    with open(output_path, "wb") as f:
                        f.write(resp.content)
                    Path(wav_path).unlink()
                    return output_path
                else:
                    import shutil
                    shutil.copy(wav_path, output_path)
                    Path(wav_path).unlink()
                    return output_path
        except Exception as e:
            log(f"  ❌ Edge TTS error: {e}")
        return None

    def generate_tts(self, text, voice="female_voice", speed=1.0, output_path=None):
        """Generate TTS based on configured provider (models.tts in config).

        Returns (audio_path, words_timestamps) tuple or just audio_path if failed.
        """
        if not output_path:
            output_path = f"/tmp/tts_{self.timestamp}_{int(time.time()*1000)}.mp3"

        tts_provider = self.config.get("models", {}).get("tts", "minimax")

        if tts_provider == "edge":
            log(f"  🔊 Edge TTS ({voice})...")
            result = self.generate_tts_edge(text, voice, speed, output_path)
            if result and Path(result).exists():
                log(f"  ✅ TTS done: {Path(result).stat().st_size/1024:.1f}KB")
                return result, None  # Edge doesn't provide word timestamps
            return result, None

        # Try MiniMax first
        log(f"  🔊 MiniMax TTS ({voice})...")
        result = self.generate_tts_minimax(text, voice, speed, output_path)
        if result and Path(result).exists():
            timestamps = self._get_minimax_tts_words(text, voice, speed)
            if timestamps:
                log(f"  ✅ TTS done: {Path(result).stat().st_size/1024:.1f}KB ({len(timestamps)} words)")
                return result, timestamps
            return result, None

        log(f"  🔊 Fallback: Edge TTS...")
        return self.generate_tts_edge(text, voice, speed, output_path), None

    def _get_minimax_tts_words(self, text, voice, speed):
        """Get word timestamps from MiniMax TTS"""
        # female_voice = Vietnamese female voice (verified working)
        voice_map = {"female_voice": "female_voice", "male-qn-qingse": "male-qn-qingse",
                    "female": "female_voice", "male": "male-qn-qingse"}
        voice_id = voice_map.get(voice, "female_voice")
        
        url = "https://api.minimax.io/v1/t2a_v2"
        headers = {"Authorization": f"Bearer {self.minimax_key}", "Content-Type": "application/json"}
        payload = {
            "model": "speech-2.8-hd", "text": text, "stream": False, "output_format": "hex",
            "voice_setting": {"voice_id": voice_id, "speed": speed, "vol": 1, "pitch": 0},
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
            "language_boost": "Vietnamese"
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            data = resp.json()
            words_data = data.get("data", {}).get("words", [])
            if words_data:
                timestamps = []
                for w in words_data:
                    timestamps.append({
                        "word": w.get("text", ""),
                        "start": w.get("start_time", 0) / 1000.0,  # ms to seconds
                        "end": w.get("end_time", 0) / 1000.0
                    })
                return timestamps
        except Exception as e:
            log(f"  ⚠️ Could not get TTS word timestamps: {e}")
        return None

    def _get_whisper_timestamps(self, audio_path, output_dir=None):
        """Get word timestamps from audio using Whisper"""
        if not Path(audio_path).exists():
            return None
        if output_dir is None:
            output_dir = tempfile.mkdtemp()
        else:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        log(f"  🎯 Running Whisper for word timestamps...")
        try:
            # Run whisper with word timestamps
            result = subprocess.run(
                ["whisper", audio_path, "--model", "small", "--word_timestamps", "True",
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
                log(f"  🎯 Whisper got {len(timestamps)} word timestamps")
                return timestamps
        except Exception as e:
            log(f"  ⚠️ Whisper error: {e}")
        return None

    # ==================== IMAGE ====================
    def generate_image_wavespeed(self, prompt, output_path, aspect_ratio="1:1", retries=3):
        """Generate image using WaveSpeed AI with retry
        
        Uses minimax/image-01/text-to-image via WaveSpeed API
        Pricing: ~$0.0035 per image (same as MiniMax direct)
        """
        for attempt in range(retries):
            log(f"  🌊 WaveSpeed Image (attempt {attempt+1}): {prompt[:50]}...")
            submit_url = f"{self.wsp_base}/api/v3/minimax/image-01/text-to-image"
            headers = {"Authorization": f"Bearer {self.wsp_key}", "Content-Type": "application/json"}
            
            # Convert aspect_ratio to size for MiniMax API
            # MiniMax uses size like "1024*1024" (width x height)
            # For 9:16 vertical, use 1080x1920
            if aspect_ratio == "9:16":
                size = "1080*1920"
            elif aspect_ratio == "16:9":
                size = "1920*1080"
            else:
                size = "1024*1024"  # default square
            
            payload = {"prompt": prompt, "size": size}
            # Add seed from config if specified
            if self.config.get("seeds", {}).get("image"):
                payload["seed"] = self.config["seeds"]["image"]
                log(f"  🎲 Using image seed: {payload['seed']}")
            try:
                resp = requests.post(submit_url, headers=headers, json=payload, timeout=30)
                data = resp.json()
                if data.get("code") != 200 or not data.get("data"):
                    log(f"  ❌ WaveSpeed submit failed: {data}")
                    continue
                job_id = data["data"]["id"]
                result_url = data["data"]["urls"]["get"]
                for poll_attempt in range(24):
                    time.sleep(5)
                    resp = requests.get(result_url, headers=headers, timeout=15)
                    result = resp.json()
                    if result.get("code") != 200:
                        break
                    status = result.get("data", {}).get("status", "")
                    if status == "completed":
                        outputs = result.get("data", {}).get("outputs", [])
                        if outputs:
                            img_url = outputs[0]
                            resp = requests.get(img_url, timeout=120)
                            with open(output_path, "wb") as f:
                                f.write(resp.content)
                            log(f"  ✅ WaveSpeed image done")
                            return output_path
                    elif status == "failed":
                        log(f"  ❌ WaveSpeed failed: {result.get('data', {}).get('error', 'unknown')}")
                        break
                log(f"  ⏳ WaveSpeed timeout, retry...")
            except Exception as e:
                log(f"  ❌ WaveSpeed error: {e}")
        return None

    def generate_image(self, prompt, output_path, retries=3):
        """Generate image: MiniMax minimax/image-01 first, fallback to WaveSpeed

        MiniMax image-01 pricing: ~$0.0035 per image
        WaveSpeed google-nano-banana-2: ~$0.0035 per image
        MiniMax has 50 images/day free tier limit
        """
        global DRY_RUN, DRY_RUN_IMAGES
        if DRY_RUN or DRY_RUN_IMAGES:
            return mock_generate_image(prompt, output_path)
        log(f"  🎨 Image Gen: {prompt[:50]}...")
        url = "https://api.minimax.io/v1/image_generation"
        headers = {"Authorization": f"Bearer {self.minimax_key}", "Content-Type": "application/json"}
        payload = {"model": "image-01", "prompt": prompt, "aspect_ratio": "9:16", "num_images": 1}
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=180)
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
                status_msg = data.get("base_resp", {}).get("status_msg", "")
                log(f"  ⚠️ MiniMax limit - trying WaveSpeed...")
                return self.generate_image_wavespeed(prompt, output_path, "9:16", retries=retries)
            resp = requests.get(img_url, timeout=120)
            with open(output_path, "wb") as f:
                f.write(resp.content)
            # Save image to S3 for future reuse
            try:
                from modules.media.s3_uploader import upload_file
                s3_url = upload_file(str(output_path), "images")
                log(f"  ☁️ Image uploaded to S3: {s3_url}")
            except Exception as s3e:
                log(f"  ⚠️ S3 upload failed: {s3e}")
            return output_path
        except Exception as e:
            log(f"  ❌ MiniMax error: {e} - trying WaveSpeed...")
            return self.generate_image_wavespeed(prompt, output_path, "9:16", retries=retries)

    # ==================== VIDEO ====================
    def wait_for_job(self, job_id, max_wait=300):
        """Poll for job completion"""
        url = f"{self.wsp_base}/api/v3/predictions/{job_id}/result"
        headers = {"Authorization": f"Bearer {self.wsp_key}"}
        elapsed = 0
        interval = 10
        while elapsed < max_wait:
            try:
                resp = requests.get(url, headers=headers, timeout=30)
                data = resp.json()
                status = data.get("data", {}).get("status", "processing")
                outputs = data.get("data", {}).get("outputs", [])
                if status == "completed" and outputs:
                    log(f"  ✅ Ready ({elapsed}s)")
                    return outputs[0]
                elif status == "failed":
                    log(f"  ❌ Failed: {data.get('data', {}).get('error', 'unknown')}")
                    return None
                log(f"  ⏳ {status}... ({elapsed}s)")
                time.sleep(interval)
                elapsed += interval
            except Exception as e:
                log(f"  ⚠️ Poll error: {e}")
                time.sleep(interval)
                elapsed += interval
        log(f"  ❌ Timeout")
        return None

    def generate_lipsync_video(self, image_path, audio_path, output_path, retries=2):
        """
        Generate lipsync video using configured provider.
        Supports "wavespeed" (default) or "kieai" via config.lipsync.provider.
        Kie.ai: POST /api/v1/jobs/createTask with infinitalk/from-audio.
        WaveSpeed: POST /api/v3/wavespeed-ai/ltx-2.3/lipsync.
        """
        global DRY_RUN
        if DRY_RUN:
            return mock_lipsync_video(image_path, audio_path, output_path)

        if self.lipsync_provider == "kieai":
            return self._generate_lipsync_kieai(image_path, audio_path, output_path, retries)
        return self._generate_lipsync_wavespeed(image_path, audio_path, output_path, retries)

    def _upload_for_kieai(self, file_path):
        """Upload to our S3 bucket and return public URL for Kie.ai."""
        from modules.media.s3_uploader import upload_file
        ext = Path(file_path).suffix.lstrip(".")
        prefix = "audio" if ext in ["mp3", "wav", "ogg"] else "images"
        try:
            url = upload_file(str(file_path), prefix)
            log(f"  ✅ S3 uploaded: {url}")
            return url
        except Exception as e:
            log(f"  ❌ S3 upload error: {e}")
        return None

    def _generate_lipsync_kieai(self, image_path, audio_path, output_path, retries=2):
        """Generate lipsync via Kie.ai Infinitalk."""
        from modules.media.kie_ai_client import KieAIClient
        client = KieAIClient(api_key=self.kieai_key, webhook_key=self.kieai_webhook_key)
        for attempt in range(retries):
            log(f"  🎬 Kie.ai Infinitalk (attempt {attempt+1})...")
            image_url = self._upload_for_kieai(image_path)
            if not image_url:
                log(f"  ❌ Image upload failed")
                continue
            audio_url = self._upload_for_kieai(audio_path)
            if not audio_url:
                log(f"  ❌ Audio upload failed")
                continue
            result = client.infinitalk(
                image_url=image_url,
                audio_url=audio_url,
                prompt=self.config.get("lipsync", {}).get("prompt", "A person talking"),
                resolution=self.config.get("lipsync", {}).get("resolution", "480p"),
            )
            if not result.get("success"):
                log(f"  ❌ Kie.ai submit failed: {result.get('error')}")
                continue
            task_id = result["task_id"]
            log(f"  ✅ Task: {task_id}")
            poll = client.poll_task(task_id, max_wait=self.config.get("lipsync", {}).get("max_wait", 300))
            if not poll.get("success"):
                error_msg = poll.get('error', '')
                log(f"  ❌ Kie.ai failed: {error_msg}")
                if "nsfw" in error_msg.lower():
                    return "NSFW_RETRY_IMAGE"
                continue
            output_urls = poll.get("output_urls", [])
            if not output_urls:
                log(f"  ❌ No output URL")
                continue
            try:
                resp = requests.get(output_urls[0], timeout=120)
                with open(output_path, "wb") as f:
                    f.write(resp.content)
                log(f"  ✅ Saved: {output_path} ({len(resp.content)/1024/1024:.1f}MB)")
                return output_path
            except Exception as e:
                log(f"  ❌ Download error: {e}")
        return None

    def _generate_lipsync_wavespeed(self, image_path, audio_path, output_path, retries=2):
        """Generate lipsync via WaveSpeed LTX (original logic)."""
        global DRY_RUN
        if DRY_RUN:
            return mock_lipsync_video(image_path, audio_path, output_path)
        for attempt in range(retries):
            log(f"  🎬 LTX Lipsync (attempt {attempt+1})...")
            image_url = self.upload_file(image_path)
            if not image_url:
                log(f"  ❌ Image upload failed")
                continue
            audio_url = self.upload_file(audio_path)
            if not audio_url:
                log(f"  ❌ Audio upload failed")
                continue
            url = f"{self.wsp_base}/api/v3/wavespeed-ai/ltx-2.3/lipsync"
            headers = {"Authorization": f"Bearer {self.wsp_key}", "Content-Type": "application/json"}
            payload = {"image": image_url, "audio": audio_url, "resolution": "480p"}
            # Add seed from config if specified
            if self.config.get("seeds", {}).get("video"):
                payload["seed"] = self.config["seeds"]["video"]
                log(f"  🎲 Using seed: {payload['seed']}")
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
                data = resp.json()
                if not data.get("data", {}).get("id"):
                    log(f"  ❌ Job failed: {data}")
                    continue
                job_id = data["data"]["id"]
                log(f"  ✅ Job: {job_id}")
                result = self.wait_for_job(job_id, max_wait=300)
                if result:
                    resp = requests.get(result, timeout=120)
                    with open(output_path, "wb") as f:
                        f.write(resp.content)
                    return output_path
            except Exception as e:
                log(f"  ❌ LTX error: {e}")
        return None

    def generate_multi_talk_video(self, image_path, audio_left, audio_right, output_path, retries=2):
        """Generate multi-char video using InfiniteTalk"""
        for attempt in range(retries):
            log(f"  🎬 InfiniteTalk Multi (attempt {attempt+1})...")
            image_url = self.upload_file(image_path)
            if not image_url:
                log(f"  ❌ Image upload failed")
                continue
            left_url = self.upload_file(audio_left)
            if not left_url:
                log(f"  ❌ Left audio upload failed")
                continue
            right_url = self.upload_file(audio_right)
            if not right_url:
                log(f"  ❌ Right audio upload failed")
                continue
            url = f"{self.wsp_base}/api/v3/wavespeed-ai/infinitetalk/multi"
            headers = {"Authorization": f"Bearer {self.wsp_key}", "Content-Type": "application/json"}
            payload = {"image": image_url, "left_audio": left_url, "right_audio": right_url,
                      "order": "left_right", "resolution": "480p"}
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
                data = resp.json()
                if not data.get("data", {}).get("id"):
                    log(f"  ❌ Job failed: {data}")
                    continue
                job_id = data["data"]["id"]
                result = self.wait_for_job(job_id, max_wait=300)
                if result:
                    resp = requests.get(result, timeout=120)
                    with open(output_path, "wb") as f:
                        f.write(resp.content)
                    return output_path
            except Exception as e:
                log(f"  ❌ InfiniteTalk error: {e}")
        return None

    # ==================== SCRIPT EXPANSION ====================
    def expand_script(self, script, min_duration=5.0):
        """Ensure script produces TTS audio of at least min_duration seconds
        
        Uses simple word-count based estimation: ~0.3s per word for Vietnamese
        If estimated duration < min_duration, add natural filler phrases
        """
        # Rough estimate: 0.3s per word for Vietnamese TTS
        words = script.split()
        estimated_duration = len(words) * 0.3
        
        if estimated_duration >= min_duration:
            log(f"  📝 Script OK: {len(words)} words, ~{estimated_duration:.1f}s")
            return script
        
        log(f"  📝 Expanding script: {len(words)} words, ~{estimated_duration:.1f}s < {min_duration}s")
        
        # Filler phrases to add natural pauses and expand duration
        fillers = [
            "Ừm... thật là",
            "Ôi... thú vị quá",
            "Bỗng nhiên... nào",
            "Này... nghe này",
            "Thật ra... mà",
            "Đẹp quá... nhỉ",
            "Vui ghê... hic",
            "Hay quá... đi",
            "Kỳ lạ... thật",
            "Lạ lắm... à"
        ]
        
        # Split by sentence-ending punctuation
        import re
        parts = re.split(r'([.!?])', script)
        # Recombine sentences with their punctuation
        sentences = []
        for i in range(0, len(parts)-1, 2):
            sentences.append(parts[i] + parts[i+1])
        if len(parts) % 2 == 1 and parts[-1].strip():
            sentences.append(parts[-1])
        
        current_script = script
        added_phrases = []
        filler_idx = 0
        
        while estimated_duration < min_duration:
            filler = fillers[filler_idx % len(fillers)]
            filler_idx += 1
            
            if len(sentences) > 1:
                # Insert filler as a separate sentence between sentences
                insert_pos = min(len(sentences) // 2, len(sentences) - 1)
                sentences.insert(insert_pos, f" {filler}...")
                current_script = ' '.join(sentences)
            else:
                # Single sentence - prepend filler
                current_script = f"{filler}... {current_script}"
            
            words = current_script.split()
            estimated_duration = len(words) * 0.3
            added_phrases.append(filler)
        
        log(f"  📝 Expanded: {len(words)} words, ~{estimated_duration:.1f}s (+{len(added_phrases)} phrases)")
        return current_script

    # ==================== UTILS ====================
    def crop_to_9x16(self, input_video, output_video):
        """"Crop/convert any video to 9:16 vertical using center crop
        
        Strategy: For horizontal (16:9) input → center crop sides to get 9:16
                   For vertical (9:16) input → scale to fit
        """
        log(f"  📐 Crop to 9:16...")
        
        # First, get input video dimensions
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", input_video],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            dims = result.stdout.strip().split(',')
            if len(dims) == 2:
                w, h = int(dims[0]), int(dims[1])
                input_ratio = w / h
                target_ratio = 9 / 16  # 0.5625
                
                log(f"  📐 Input: {w}x{h} ({input_ratio:.2f}:1), Target: 9:16 ({target_ratio:.2f}:1)")
                
                if input_ratio > target_ratio:
                    # Input is wider than target (e.g., 16:9 input for 9:16 output)
                    # Need to crop sides
                    new_w = int(h * (9/16))
                    x_offset = (w - new_w) // 2
                    crop_filter = f"crop={new_w}:{h}:{x_offset}:0,scale=1080:1920"
                    log(f"  📐 Center crop: crop={new_w}:{h}:{x_offset}:0 → scale=1080:1920")
                elif input_ratio < target_ratio:
                    # Input is taller than target (rare case)
                    new_h = int(w * (16/9))
                    y_offset = (h - new_h) // 2
                    crop_filter = f"crop={w}:{new_h}:0:{y_offset},scale=1080:1920"
                    log(f"  📐 Center crop: crop={w}:{new_h}:0:{y_offset} → scale=1080:1920")
                else:
                    # Already correct ratio
                    crop_filter = "scale=1080:1920"
                
                cmd = ["ffmpeg", "-i", input_video,
                      "-vf", crop_filter,
                      "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                      "-c:a", "aac", "-y", output_video]
                try:
                    subprocess.run(cmd, capture_output=True, timeout=300)
                    if Path(output_video).exists():
                        return output_video
                except Exception as e:
                    log(f"  ❌ Crop error: {e}")
        return None

    def get_character(self, name):
        for char in self.config.get("characters", []):
            if char["name"] == name:
                return char
        return None

    def get_avatar(self, name):
        """Get avatar path - currently not used in scene video generation (kept for future thumbnail/poster)" """
        char = self.get_character(name)
        if not char:
            return None
        avatar_path = self.avatars_dir / char.get("avatar_file", f"{name}.png")
        if avatar_path.exists():
            return str(avatar_path)
        return None

    def build_scene_prompt(self, scene):
        cfg = self.config.get("prompt", {})
        style = cfg.get("style", "3D animated Pixar Disney style, high quality 3D render, detailed, vibrant colors")
        background = scene.get("background", "")
        hints = cfg.get("script_hints", {})
        
        # Find matching script hint based on background keyword
        script_hint = ""
        for key, hint in hints.items():
            if key != "default" and key in background.lower():
                script_hint = hint
                break
        if not script_hint:
            script_hint = hints.get("default", "warm natural lighting, lush environment")
        
        # Build prompt from style + script_hint ONLY (not raw background text)
        prompt = f"{style}, {script_hint}"
        
        # Add character descriptions if specified
        chars = scene.get("characters", [])
        if chars:
            char_prompts = []
            for char_name in chars:
                char = self.get_character(char_name)
                if char and char.get("prompt"):
                    char_prompts.append(char["prompt"])
            if char_prompts:
                prompt = f"{prompt}, featuring: {' '.join(char_prompts)}"
        
        return prompt

    def concat_videos(self, video_paths, output_path):
        """Concatenate multiple videos - re-encode to sync audio properly"""
        if not video_paths:
            return None
        log(f"  🔗 Concatenating {len(video_paths)} videos (re-encoding for sync)...")
        list_file = self.run_dir / "concat_list.txt"
        with open(list_file, "w") as f:
            for path in video_paths:
                log(f"    + {Path(path).name}")
                f.write(f"file '{path}'\n")
        
        # Use concat filter to properly sync video+audio from all files
        # Filtergraph approach handles different-duration streams correctly
        filtergraph = ''
        for i, path in enumerate(video_paths):
            filtergraph += f"[{i}:v][{i}:a]"
        filtergraph += f"concat=n={len(video_paths)}:v=1:a=1[outv][outa]"
        
        input_args = []
        for path in video_paths:
            input_args += ["-i", path]
        cmd = ["ffmpeg", "-y"] + input_args + [
            "-filter_complex", filtergraph,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            output_path
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                log(f"  ❌ Concat error: {result.stderr[:300]}")
                # Fallback: simple concat with stream copy
                log(f"  🔄 Fallback: concat with stream copy...")
                cmd_simple = [
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                    "-c", "copy", "-bsf:a", "aac_adtstoasc", output_path
                ]
                subprocess.run(cmd_simple, capture_output=True, timeout=600)
            if Path(output_path).exists():
                size = Path(output_path).stat().st_size
                log(f"  ✅ Concat done: {size/1024/1024:.1f}MB")
                return output_path
        except Exception as e:
            log(f"  ❌ Concat exception: {e}")
        return None

    def add_subtitles(self, video_path, script_text, output_path):
        """Add karaoke subtitles to video using karaoke_subtitles.py"""
        log(f"  📝 Adding subtitles...")
        script_path = self.run_dir / "current_script.txt"
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_text)
        
        karaoke_script = Path(__file__).parent / ".." / "karaoke_subtitles.py"
        if not karaoke_script.exists():
            karaoke_script = Path(__file__).parent / "karaoke_subtitles.py"
        if not karaoke_script.exists():
            log(f"  ⚠️ karaoke_subtitles.py not found, skipping subtitles")
            return video_path
        
        cmd = [
            get_karaoke_python(), str(karaoke_script),
            video_path,
            str(script_path),
            output_path,
            "--font_size", "60"
        ]
        log(f"  📝 Running karaoke subtitles (font=60)...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                log(f"  ✅ Subtitles added: {output_path}")
                return output_path
            else:
                log(f"  ⚠️ Subtitle error (exit {result.returncode}): {result.stderr[:200]}")
        except Exception as e:
            log(f"  ⚠️ Subtitle exception: {e}")
        return video_path

    def add_subtitles_with_timestamps(self, video_path, timestamps, script_text, output_path):
        """Add karaoke subtitles using pre-calculated TTS word timestamps (accurate)"""
        log(f"  📝 Adding subtitles with {len(timestamps)} pre-calculated timestamps...")
        
        # Check deps
        karaoke_script = Path(__file__).parent / ".." / "karaoke_subtitles.py"
        if not karaoke_script.exists():
            karaoke_script = Path(__file__).parent / "karaoke_subtitles.py"
        
        import tempfile
        temp_dir = tempfile.mkdtemp()
        ts_path = os.path.join(temp_dir, "timestamps.json")
        script_path = os.path.join(temp_dir, "script.txt")
        
        with open(ts_path, "w", encoding="utf-8") as f:
            json.dump(timestamps, f, ensure_ascii=False)
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_text)
        
        cmd = [
            get_karaoke_python(), str(karaoke_script),
            video_path,
            script_path,
            output_path,
            "--font_size", "60",
            "--timestamps", ts_path
        ]
        log(f"  📝 Running karaoke subtitles with timestamps (font=60)...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                log(f"  ✅ Subtitles added: {output_path}")
                return output_path
            else:
                log(f"  ⚠️ Subtitle error: {result.stderr[:200]}")
        except Exception as e:
            log(f"  ⚠️ Subtitle exception: {e}")
        return video_path

    def add_background_music(self, video_path, output_path, music_file=None, volume=0.15):
        """Add background music to video at specified volume (default 15%)
        
        Args:
            video_path: Input video
            output_path: Output video with music
            music_file: Path to music file (from config or default)
            volume: Music volume 0.0-1.0 (default 15%)
        """
        if not music_file:
            # Try to get from config
            music_file = self.config.get("background_music", {}).get("file")
        
        if not music_file or music_file == "random":
            # Randomly select from music pool
            music_dir = Path.home() / ".openclaw/workspace/media/music/"
            if music_dir.exists():
                mp3_files = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.ogg"))
                mp3_files = [f for f in mp3_files if f.stat().st_size > 500000]  # Filter small files
                if mp3_files:
                    import random
                    music_file = str(random.choice(mp3_files))
                    log(f"  🎲 Random music selected: {Path(music_file).name}")
                else:
                    log(f"  ⚠️ No music files found in pool, skipping...")
                    return video_path
            else:
                log(f"  ⚠️ Music directory not found, skipping...")
                return video_path
        
        if not Path(music_file).exists():
            log(f"  ⚠️ Music file not found: {music_file}, skipping...")
            return video_path
        
        # Get volume from config if not specified
        music_config = self.config.get("background_music", {})
        volume = music_config.get("volume", volume)
        fade_duration = music_config.get("fade_duration", 2)  # 2s fade in/out
        
        log(f"  🎵 Adding background music: {Path(music_file).name}")
        log(f"  🎚️ Volume: {volume*100:.0f}%, Fade: {fade_duration}s")
        
        # Get video duration
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True
        )
        video_duration = float(result.stdout.strip() or 0)
        
        # Get music duration
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", music_file],
            capture_output=True, text=True
        )
        music_duration = float(result.stdout.strip() or 0)
        
        # Calculate loop count (loop music to cover full video)
        if music_duration > 0:
            loop_count = int(video_duration / music_duration) + 2
            
            # Build ffmpeg filter for:
            # 1. Loop music to cover video duration
            # 2. Apply fade in/out to music
            # 3. Boost original narration audio (so it stays loud after mixing)
            # 4. Mix with amix (which halves volume by default, so boost to compensate)
            # Note: amix reduces each input by 50%, so we boost original by 2x to preserve volume
            boost_factor = 2.0  # Boost narration to compensate for amix reduction
            filter_str = (
                f"[1:a]aloop=loop=-1:size=0,atrim=0:{video_duration},"
                f"afade=t=in:st=0:d={fade_duration},"
                f"afade=t=out:st={video_duration-fade_duration}:d={fade_duration},"
                f"volume={volume}[music];"
                f"[0:a]volume={boost_factor}[narration];"
                f"[narration][music]amix=inputs=2:duration=first:dropout_transition=2,volume=1.5[a]"
            )
            
            cmd = [
                "ffmpeg", "-y", "-i", video_path, "-i", music_file,
                "-filter_complex", filter_str,
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                output_path
            ]
        else:
            log(f"  ⚠️ Could not get music duration, skipping...")
            return video_path
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0 and Path(output_path).exists():
                orig_size = Path(video_path).stat().st_size
                new_size = Path(output_path).stat().st_size
                log(f"  ✅ Background music added: {Path(output_path).name} ({new_size/1024/1024:.1f}MB)")
                return output_path
            else:
                log(f"  ⚠️ FFmpeg error: {result.stderr[:200] if result.stderr else 'unknown'}")
        except Exception as e:
            log(f"  ⚠️ Music mix error: {e}")
        
        return video_path

    def add_watermark(self, video_path, output_path):
        """Add watermark to video using PIL overlay + FFmpeg.
        
        Supports 'static' and 'bounce' motion modes:
        - static: fixed position at bottom-right
        - bounce: 4-directional physics-based bounce (watermark bounces off walls)
        """
        wm_cfg = self.config.get("watermark", {})
        if not wm_cfg.get("enable", False):
            log(f"  ℹ️ Watermark disabled")
            return video_path
        
        text = wm_cfg.get("text", "@NangSuatThongMinh")
        font_size = wm_cfg.get("font_size", 60)
        opacity = wm_cfg.get("opacity", 0.15)
        motion = wm_cfg.get("motion", "bounce")
        
        log(f"  💧 Adding watermark: '{text}' (motion={motion}, opacity={opacity})")
        
        try:
            if motion == "bounce":
                # Use physics-based bounce watermark script
                bounce_script = Path(__file__).parent / "bounce_watermark.py"
                if bounce_script.exists():
                    python = get_karaoke_python()
                    cmd = [
                        python, str(bounce_script),
                        str(video_path), str(output_path),
                        "--text", text,
                        "--font-size", str(font_size),
                        "--opacity", str(opacity),
                        "--speed", str(wm_cfg.get("bounce_speed", 120)),
                        "--padding", str(wm_cfg.get("bounce_padding", 15))
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                    if result.returncode == 0 and Path(output_path).exists():
                        log(f"  ✅ Watermark added (bounce, font={font_size}, opacity={opacity})")
                        return output_path
                    else:
                        log(f"  ⚠️ Bounce watermark failed: {result.stderr[-300:] if result.stderr else 'unknown error'}")
                else:
                    log(f"  ⚠️ bounce_watermark.py not found, falling back to static")
            
            # --- STATIC MODE (fallback or when motion=static) ---
            # Get video dimensions
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "json", str(video_path)],
                capture_output=True, text=True
            )
            info = json.loads(result.stdout)
            vw = int(info['streams'][0]['width'])
            vh = int(info['streams'][0]['height'])
            
            # Scale font size based on video size
            scale = vh / 1920
            scaled_font_size = int(font_size * scale)
            
            from PIL import Image as PILImage, ImageFont, ImageDraw
            try:
                fnt = ImageFont.truetype('/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf', scaled_font_size)
            except:
                fnt = ImageFont.load_default()
            
            overlay = PILImage.new('RGBA', (vw, vh), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            
            # Position at bottom right
            x = vw - int(280 * scale)
            y = vh - int(70 * scale)
            
            alpha = int(255 * opacity)
            stroke_alpha = int(alpha * 0.8)
            draw.text((x, y), text, font=fnt, fill=(0, 0, 0, stroke_alpha))
            draw.text((x, y), text, font=fnt, fill=(255, 255, 255, alpha))
            
            overlay_path = self.run_dir / "watermark_overlay.png"
            overlay.save(str(overlay_path))
            
            tmp_wm = self.run_dir / "watermark_tmp.mp4"
            
            # Apply overlay: video (0) is base, overlay (1) on top
            cmd = [
                "ffmpeg", "-y", "-i", str(video_path), "-i", str(overlay_path),
                "-filter_complex", "[0:v][1:v]overlay=0:0[out]",
                "-map", "[out]", "-map", "0:a?", "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-c:a", "copy",
                str(tmp_wm)
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0 and tmp_wm.exists():
                import shutil
                shutil.copy(tmp_wm, output_path)
                log(f"  ✅ Watermark added (static)")
                return output_path
            else:
                log(f"  ⚠️ Watermark failed: {result.stderr[:200] if result.stderr else 'unknown error'}")
        except Exception as e:
            log(f"  ⚠️ Watermark error: {e}")
        
        return video_path

    # ==================== MAIN RUN ====================
    def run(self):
        log(f"\n{'='*60}")
        log(f"🎬 VIDEO PIPELINE v3 - DYNAMIC (with subtitles)")
        log(f"{'='*60}")
        
        # Load and display config
        self._load_config()
        
        scenes = self.config.get("scenes", [])
        log(f"📋 {len(scenes)} scenes loaded")
        
        scene_videos = []
        scene_scripts = []  # Track scripts for subtitle step
        
        for scene in scenes:
            scene_id = scene.get("id", 0)
            script = scene["script"]
            chars = scene.get("characters", [])
            
            log(f"\n{'='*40}")
            log(f"🎬 SCENE {scene_id}: {script[:50]}...")
            log(f"   Characters: {chars}")
            log(f"{'='*40}")
            
            scene_output = self.run_dir / f"scene_{scene_id}"
            scene_output.mkdir(exist_ok=True)
            
            # Enhanced resume: check if scene already processed in current or previous run
            existing_cropped = scene_output / "video_9x16.mp4"
            if existing_cropped.exists():
                log(f"  ✅ scene_{scene_id}: video_9x16.mp4 exists - skipping")
                scene_videos.append(str(existing_cropped))
                scene_scripts.append(script)
                continue
            # Try to reuse from a previous run (avoids expensive lipsync re-generation)
            if self._reuse_or_generate_scene(scene_id, scene_output):
                scene_videos.append(str(scene_output / "video_9x16.mp4"))
                scene_scripts.append(script)
                continue
            
            video_raw_exists = (scene_output / "video_raw.mp4").exists()
            video_9x16_exists = (scene_output / "video_9x16.mp4").exists()
            
            if video_9x16_exists:
                log(f"  ✅ video_9x16.mp4 already exists - will add subtitles only")
                scene_videos.append(str(scene_output / "video_9x16.mp4"))
                scene_scripts.append(script)
                continue
            
            prompt = self.build_scene_prompt(scene)
            log(f"  📝 Prompt: {prompt[:80]}...")
            
            if len(chars) == 1:
                char_cfg = self.get_character(chars[0])
                voice = char_cfg.get("tts_voice", "female_voice")
                speed = char_cfg.get("tts_speed", 1.0)
                
                # Expand script to meet minimum duration
                script = self.expand_script(script, min_duration=5.0)
                
                log(f"  🔊 Generating TTS...")
                audio_result = self.generate_tts(script, voice, speed)
                audio = audio_result[0] if isinstance(audio_result, tuple) else audio_result
                word_timestamps = audio_result[1] if isinstance(audio_result, tuple) else None
                if not audio:
                    log(f"  ❌ TTS failed")
                    continue
                log(f"  ✅ TTS done: {Path(audio).stat().st_size/1024:.1f}KB")
                
                # Save TTS audio to scene directory for Whisper processing
                audio_file = scene_output / "audio_tts.mp3"
                shutil.copy(audio, str(audio_file))
                
                # Get word timestamps (from TTS or Whisper)
                if not word_timestamps:
                    # Run Whisper on TTS audio for accurate timestamps
                    word_timestamps = self._get_whisper_timestamps(str(audio_file), str(scene_output))
                
                if word_timestamps:
                    ts_file = scene_output / "words_timestamps.json"
                    with open(ts_file, "w", encoding="utf-8") as f:
                        json.dump(word_timestamps, f, ensure_ascii=False)
                    log(f"  📝 Saved {len(word_timestamps)} word timestamps")
                
                scene_img = scene_output / "scene.png"
                if scene_img.exists():
                    log(f"  ✅ scene.png already exists - skipping image gen")
                else:
                    log(f"  🎨 Generating scene image...")
                    if not self.generate_image(prompt, str(scene_img)):
                        log(f"  ❌ Image gen failed")
                        continue
                    log(f"  ✅ Image done: {scene_img.stat().st_size/1024:.1f}KB")
                
                video_raw = scene_output / "video_raw.mp4"
                if video_raw.exists():
                    log(f"  ✅ video_raw.mp4 already exists - skipping lipsync")
                else:
                    log(f"  🎬 Generating lipsync video...")
                    lipsync_result = self.generate_lipsync_video(str(scene_img), audio, str(video_raw), retries=2)
                    if lipsync_result == "NSFW_RETRY_IMAGE":
                        log(f"  ⚠️ NSFW detected - regenerating image with safer prompt...")
                        scene_img.unlink(missing_ok=True)
                        safe_prompt = prompt + ", modest clothing, professional pose, clean background"
                        if not self.generate_image(safe_prompt, str(scene_img)):
                            log(f"  ❌ Safe image gen failed")
                            continue
                        log(f"  ✅ Safe image done: {scene_img.stat().st_size/1024:.1f}KB")
                        lipsync_result = self.generate_lipsync_video(str(scene_img), audio, str(video_raw), retries=2)
                        if not lipsync_result or lipsync_result == "NSFW_RETRY_IMAGE":
                            log(f"  ❌ Lipsync failed even with safe image")
                            continue
                    elif not lipsync_result:
                        log(f"  ❌ Lipsync failed")
                        continue
                    log(f"  ✅ Lipsync done: {video_raw.stat().st_size/1024/1024:.1f}MB")
                
                video_9x16 = scene_output / "video_9x16.mp4"
                if video_9x16.exists():
                    log(f"  ✅ video_9x16.mp4 already exists - skipping crop")
                else:
                    log(f"  📐 Cropping to 9:16...")
                    if not self.crop_to_9x16(str(video_raw), str(video_9x16)):
                        continue
                    log(f"  ✅ Crop done: {video_9x16.stat().st_size/1024/1024:.1f}MB")
                
                scene_videos.append(str(video_9x16))
                scene_scripts.append(script)
                
            elif len(chars) == 2:
                # Simpler approach: generate two separate lip-sync videos
                # First character
                char0 = self.get_character(chars[0])
                voice0 = char0.get("tts_voice", "female_voice")
                speed0 = char0.get("tts_speed", 1.0)
                
                # Split script ~60/40 for smoother pacing
                words = script.split()
                split_at = max(3, len(words) * 60 // 100)
                left_script = " ".join(words[:split_at])
                right_script = " ".join(words[split_at:])
                
                # Split and expand each script to meet minimum duration
                left_script = self.expand_script(left_script, min_duration=5.0)
                right_script = self.expand_script(right_script, min_duration=5.0)
                
                log(f"  🔊 TTS left ({chars[0]})...")
                audio_left_result = self.generate_tts(left_script, voice0, speed0)
                audio_left = audio_left_result[0] if isinstance(audio_left_result, tuple) else audio_left_result
                if not audio_left:
                    log(f"  ❌ Left TTS failed")
                    continue
                log(f"  ✅ TTS done: {Path(audio_left).stat().st_size/1024:.1f}KB")
                
                scene_img = scene_output / "scene_multi.png"
                if scene_img.exists():
                    log(f"  ✅ scene_multi.png already exists - skipping image gen")
                else:
                    multi_prompt = f"{prompt}, featuring two children characters together"
                    log(f"  🎨 Generating multi scene image...")
                    if not self.generate_image(multi_prompt, str(scene_img)):
                        log(f"  ❌ Multi scene image failed")
                        continue
                    log(f"  ✅ Image done: {scene_img.stat().st_size/1024:.1f}KB")
                
                # Left video
                video_left = scene_output / "video_left.mp4"
                if video_left.exists():
                    log(f"  ✅ video_left.mp4 already exists - skipping left lipsync")
                else:
                    log(f"  🎬 Generating left lipsync...")
                    if not self.generate_lipsync_video(str(scene_img), audio_left, str(video_left), retries=2):
                        log(f"  ❌ Left lipsync failed")
                        continue
                    log(f"  ✅ Left lipsync done: {video_left.stat().st_size/1024/1024:.1f}MB")
                
                # Right character
                char1 = self.get_character(chars[1])
                voice1 = char1.get("tts_voice", "male-qn-qingse")
                speed1 = char1.get("tts_speed", 1.0)
                
                log(f"  🔊 TTS right ({chars[1]})...")
                audio_right_result = self.generate_tts(right_script, voice1, speed1)
                audio_right = audio_right_result[0] if isinstance(audio_right_result, tuple) else audio_right_result
                if not audio_right:
                    log(f"  ❌ Right TTS failed")
                    continue
                log(f"  ✅ TTS done: {Path(audio_right).stat().st_size/1024:.1f}KB")
                
                # Right video
                video_right = scene_output / "video_right.mp4"
                if video_right.exists():
                    log(f"  ✅ video_right.mp4 already exists - skipping right lipsync")
                else:
                    log(f"  🎬 Generating right lipsync...")
                    if not self.generate_lipsync_video(str(scene_img), audio_right, str(video_right), retries=2):
                        log(f"  ❌ Right lipsync failed")
                        continue
                    log(f"  ✅ Right lipsync done: {video_right.stat().st_size/1024/1024:.1f}MB")
                
                # Crop both to 9:16 and concat
                video_left_9x16 = scene_output / "video_left_9x16.mp4"
                if video_left_9x16.exists():
                    log(f"  ✅ video_left_9x16.mp4 exists")
                else:
                    log(f"  📐 Cropping left video...")
                    if not self.crop_to_9x16(str(video_left), str(video_left_9x16)):
                        continue
                
                video_right_9x16 = scene_output / "video_right_9x16.mp4"
                if video_right_9x16.exists():
                    log(f"  ✅ video_right_9x16.mp4 exists")
                else:
                    log(f"  📐 Cropping right video...")
                    if not self.crop_to_9x16(str(video_right), str(video_right_9x16)):
                        continue
                
                log(f"  🔗 Concatenating left + right...")
                video_9x16 = scene_output / "video_9x16.mp4"
                if self.concat_videos([str(video_left_9x16), str(video_right_9x16)], str(video_9x16)):
                    scene_videos.append(str(video_9x16))
                    scene_scripts.append(script)
        
        if not scene_videos:
            log(f"\n❌ No scene videos generated")
            db.fail_video_run(self.run_id, "No scene videos generated")
            return None
        
        log(f"\n{'='*60}")
        log(f"🔗 CONCATENATING {len(scene_videos)} scenes...")
        log(f"{'='*60}")
        
        concat_output = self.run_dir / "video_concat.mp4"
        final_video = self.media_dir / f"video_v3_{self.timestamp}.mp4"
        
        if self.concat_videos(scene_videos, str(concat_output)):
            shutil.copy(str(concat_output), str(final_video))
            log(f"  ✅ Concat copied: {final_video.stat().st_size/1024/1024:.1f}MB")
            
            # Collect word timestamps from all scenes for accurate subtitle timing
            combined_timestamps = []
            offset = 0.0
            for i, scene in enumerate(scenes):
                scene_id = scene.get("id", i+1)
                scene_dir = self.run_dir / f"scene_{scene_id}"
                if i >= len(scene_videos):
                    log(f"  ⚠️ Scene {scene_id}: no video (skipped) - skipping timestamps")
                    continue
                ts_file = scene_dir / "words_timestamps.json"
                if ts_file.exists():
                    with open(ts_file, encoding="utf-8") as f:
                        timestamps = json.load(f)
                    # Adjust timestamps with offset
                    for t in timestamps:
                        combined_timestamps.append({
                            "word": t["word"],
                            "start": t["start"] + offset,
                            "end": t["end"] + offset
                        })
                    log(f"  📝 Loaded {len(timestamps)} timestamps from scene {scene_id}")
                # Update offset with video duration
                vpath = scene_videos[i]
                r = subprocess.run(["ffprobe", "-v", "quiet", "-select_streams", "v:0", 
                                   "-show_entries", "stream=duration", "-of", "json", vpath],
                                  capture_output=True, text=True)
                if r.returncode == 0:
                    import json as j
                    dur = j.loads(r.stdout)['streams'][0]['duration']
                    offset += float(dur)
            
            # Add watermark FIRST (will be below subtitles)
            video_for_subtitles = str(final_video)
            
            # Check if watermark is enabled
            wm_cfg = self.config.get("watermark", {})
            if wm_cfg.get("enable", False):
                watermarked_base = self.media_dir / f"video_v3_{self.timestamp}_watermarked_base.mp4"
                log(f"\n{'='*60}")
                log(f"💧 ADDING WATERMARK (below subtitles)...")
                log(f"{'='*60}")
                wm_result = self.add_watermark(str(final_video), str(watermarked_base))
                if Path(wm_result).exists():
                    video_for_subtitles = wm_result
            
            # Add subtitles SECOND (on TOP of watermark) - karaoke style
            full_script = " ".join(scene_scripts)
            subtitled_video = self.media_dir / f"video_v3_{self.timestamp}_subtitled.mp4"
            log(f"\n{'='*60}")
            log(f"📝 ADDING SUBTITLES (karaoke on TOP)...")
            log(f"{'='*60}")
            
            if combined_timestamps:
                self.add_subtitles_with_timestamps(video_for_subtitles, combined_timestamps, full_script, str(subtitled_video))
            else:
                self.add_subtitles(video_for_subtitles, full_script, str(subtitled_video))
            
            # Check if background music is enabled
            music_enabled = self.config.get("background_music", {}).get("enable", True)
            
            if music_enabled and Path(subtitled_video).exists():
                # Add background music
                final_with_music = self.media_dir / f"video_v3_{self.timestamp}_with_music.mp4"
                log(f"\n{'='*60}")
                log(f"🎵 ADDING BACKGROUND MUSIC...")
                log(f"{'='*60}")
                music_result = self.add_background_music(str(subtitled_video), str(final_with_music))
                final_output = music_result if Path(music_result).exists() else str(subtitled_video)
            else:
                final_output = str(subtitled_video) if Path(subtitled_video).exists() else str(final_video)
            
            log(f"\n✅ DONE: {final_output}")
            db.complete_video_run(self.run_id, "completed")
            return str(final_output)
        
        log(f"\n❌ Pipeline failed")
        db.fail_video_run(self.run_id, "Pipeline failed")
        return None


if __name__ == "__main__":
    import sys
    config_files = []
    resume_run_dir = None

    # Usage:
    #   python video_pipeline_v3.py <config.json>                    # fresh start
    #   python video_pipeline_v3.py --start <config.json>          # fresh start (clear cache)
    #   python video_pipeline_v3.py --resume <config.json>        # resume from recent run
    #   python video_pipeline_v3.py --dry-run <config.json>       # dry run (mock API calls)
    #   python video_pipeline_v3.py --dry-run-tts <config.json>  # dry run TTS only

    # Parse arguments for dry-run flags
    config_flag = None
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--dry-run":
            DRY_RUN = True
            log("🔴 DRY RUN MODE: All API calls will be mocked")
        elif arg == "--dry-run-tts":
            DRY_RUN_TTS = True
            log("🔴 DRY RUN TTS MODE: TTS calls will be mocked")
        elif arg == "--dry-run-images":
            DRY_RUN_IMAGES = True
            log("🔴 DRY RUN IMAGES MODE: Image generation will be mocked")
        elif arg == "--upload-to-socials":
            UPLOAD_TO_SOCIALS = True
            log("📤 SOCIAL UPLOAD MODE: Will upload to FB/TikTok after generation")
        elif arg in ["--config", "-c"] and i+2 < len(sys.argv):
            config_flag = sys.argv[i+2]
        elif arg in ["--start", "--fresh"]:
            FORCE_START = True
            log("🆕 FRESH START MODE: Previous scene cache will be cleared")
        elif arg in ["--resume", "-r"]:
            # Find most recent run with videos
            base = Path.home() / ".openclaw/workspace/video_v3_output"
            run_dirs = sorted(base.glob("run_*"), key=lambda p: p.stat().st_mtime, reverse=True)
            for rd in run_dirs:
                scene_videos = list(rd.glob("scene_*/video_9x16.mp4"))
                if scene_videos:
                    resume_run_dir = rd
                    break
        else:
            config_files.append(arg)

    # Handle config files: pass as tuple if two, single file otherwise
    if config_flag:
        config_path = config_flag
    elif len(config_files) == 2:
        config_path = (config_files[0], config_files[1])
    elif len(config_files) == 1:
        config_path = config_files[0]
    else:
        config_path = Path(__file__).parent / "video_config.json"

    # Validate config files exist
    if isinstance(config_path, tuple):
        if not all(Path(p).exists() for p in config_path):
            print(f"❌ Config files not found: {config_path}")
            sys.exit(1)
    elif not Path(config_path).exists():
        config_path = Path(__file__).parent / "video_config.json"
        if not Path(config_path).exists():
            print(f"❌ Config not found: {config_path}")
            sys.exit(1)

    pipeline = VideoPipelineV3(config_path)

    if resume_run_dir:
        pipeline.run_dir = resume_run_dir
        print(f"📁 Resuming from: {resume_run_dir}")
    
    result = pipeline.run()
    if result:
        print(f"\n🎉 Output: {result}")
        # ── Social media upload (Phase 2 VP-013) ─────────────────
        if UPLOAD_TO_SOCIALS:
            if DRY_RUN:
                print("\n📤 [SOCIAL UPLOAD] Dry-run mode — simulating upload pipeline")
            else:
                print("\n📤 [SOCIAL UPLOAD] Starting upload pipeline...")
            try:
                sys.path.insert(0, str(Path(__file__).parent))
                from modules.pipeline.publisher import get_publisher

                publisher = get_publisher(
                    dry_run=DRY_RUN,
                    video_run_id=pipeline.run_id,
                    config=pipeline.config,
                )
                publish_result = publisher.upload_to_socials(
                    video_path=result,
                    script=pipeline.config.get("video", {}).get("script", ""),
                    word_timestamps=getattr(pipeline, "word_timestamps", None),
                    srt_output_name=Path(result).stem,
                )
                print(f"\n📤 Social upload result: {publish_result.summary()}")
            except Exception as e:
                print(f"\n⚠️  Social upload skipped/error: {e}")
    else:
        print(f"\n💥 Failed")
        sys.exit(1)
