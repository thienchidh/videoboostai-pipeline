# Config Hardcode Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all hardcoded values from codebase, move them to config files (technical + channel), enforce strict validation where missing config = raise error.

**Architecture:** 5 sequential PRs, each covering one domain (TTS → Image → Lipsync → Content → Pipeline). Each PR: add missing config keys to YAML → update code to read from config → remove hardcoded fallbacks. Strict mode: missing required key raises `ConfigMissingKeyError`.

**Tech Stack:** Python, PyYAML (config), existing pydantic/validation patterns

---

## Config Files to Update

### Technical Config Additions (`configs/technical/config_technical.yaml`)

Add these NEW keys that are currently missing:

```yaml
generation:
  tts:
    model: "speech-2.8-hd"                    # NEW
    sample_rate: 32000                         # NEW
    bitrate: 128000                            # NEW
    format: "mp3"                              # NEW
    channel: 1                                 # NEW
    timeout: 60                                # NEW
    word_timestamp_timeout: 120                # NEW
  image:
    timeout: 120                               # NEW
    poll_interval: 5                            # NEW
    max_polls: 24                             # NEW
  lipsync:
    poll_interval: 10                          # NEW
    retries: 2                                 # NEW

embedding:
  model: "distiluse-base-multilingual-cased-v2"  # NEW
  similarity_threshold: 0.75                    # NEW
  translation_max_tokens: 200                    # NEW

storage:
  temp_dir: "/tmp"                              # NEW (platform-aware at runtime)
  output_dir: "output"                          # NEW

db:
  pool_size: 1                                  # NEW
  max_overflow: 10                              # NEW
  pool_timeout: 30                             # NEW
```

---

## PR #1: TTS — `modules/media/tts.py`

### Files

- Modify: `configs/technical/config_technical.yaml` (add missing keys)
- Modify: `modules/media/tts.py`
- Test: `tests/test_tts_config.py` (create new)

### Tasks

**Task 1: Add TTS config keys to technical config**

- [ ] **Step 1: Add missing TTS keys to technical config**

```yaml
# In configs/technical/config_technical.yaml, under generation.tts:
generation:
  tts:
    model: "speech-2.8-hd"
    sample_rate: 32000
    bitrate: 128000
    format: "mp3"
    channel: 1
    timeout: 60
    word_timestamp_timeout: 120
```

Run: `grep -n "generation:" configs/technical/config_technical.yaml`
Expected: find the generation section

- [ ] **Step 2: Commit**

```bash
git add configs/technical/config_technical.yaml
git commit -m "feat(config): add missing TTS keys to technical config"
```

---

**Task 2: Add ConfigMissingKeyError exception class**

- [ ] **Step 1: Create exceptions module with ConfigMissingKeyError**

Create `modules/pipeline/exceptions.py` if it doesn't exist, or add to existing:

```python
# modules/pipeline/exceptions.py

class PipelineError(Exception):
    """Base exception for pipeline errors"""
    pass

class ConfigMissingKeyError(PipelineError):
    """Raised when required config key is missing"""
    def __init__(self, key_path: str, provider: str = None):
        self.key_path = key_path
        self.provider = provider
        msg = f"Required config key missing: '{key_path}'"
        if provider:
            msg += f" (required by {provider})"
        super().__init__(msg)
```

- [ ] **Step 2: Verify file exists and import works**

Run: `python -c "from modules.pipeline.exceptions import ConfigMissingKeyError; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add modules/pipeline/exceptions.py
git commit -m "feat: add ConfigMissingKeyError exception"
```

---

**Task 3: Update MiniMaxTTSProvider to use config URLs**

- [ ] **Step 1: Write test for TTS config URL loading**

Create `tests/test_tts_config.py`:

```python
import pytest
from unittest.mock import MagicMock
from modules.media.tts import MiniMaxTTSProvider
from modules.pipeline.exceptions import ConfigMissingKeyError

class TestMiniMaxTTSConfig:
    def test_uses_config_url_when_provided(self):
        """MiniMaxTTSProvider should read base_url from config"""
        mock_config = MagicMock()
        mock_config.get.return_value = "https://custom.api.minimax.io/v1/t2a_v2"
        mock_config.get.return_value = None  # for missing keys
        mock_config.get.side_effect = lambda key: {
            "api.urls.minimax_tts": "https://custom.api.minimax.io/v1/t2a_v2",
            "generation.tts.model": "speech-2.8-hd",
            "generation.tts.timeout": 60,
        }.get(key)

        provider = MiniMaxTTSProvider(config=mock_config)
        assert provider.base_url == "https://custom.api.minimax.io/v1/t2a_v2"

    def test_raises_error_when_url_missing(self):
        """Should raise ConfigMissingKeyError when api.urls.minimax_tts is missing"""
        mock_config = MagicMock()
        mock_config.get.return_value = None

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            MiniMaxTTSProvider(config=mock_config)
        assert "api.urls.minimax_tts" in str(exc_info.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tts_config.py -v`
Expected: FAIL (provider doesn't use config yet)

- [ ] **Step 3: Update MiniMaxTTSProvider.__init__ to read from config**

In `modules/media/tts.py`, update `__init__`:

```python
def __init__(self, config: TechnicalConfig = None, api_key: str = None):
    self.config = config
    base_url = config.get("api.urls.minimax_tts") if config else None
    if not base_url:
        raise ConfigMissingKeyError("api.urls.minimax_tts", "MiniMaxTTSProvider")
    self.base_url = base_url
    self.api_key = api_key or (config.get("api.keys.minimax") if config else None)
    if not self.api_key:
        raise ConfigMissingKeyError("api.keys.minimax", "MiniMaxTTSProvider")

    # Load TTS settings from config
    self.model = config.get("generation.tts.model") if config else "speech-2.8-hd"
    self.timeout = config.get("generation.tts.timeout") if config else 60
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tts_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/media/tts.py tests/test_tts_config.py
git commit -m "feat(tts): read URL and model from config, raise on missing keys"
```

---

**Task 4: Update MiniMaxTTSProvider.generate to use config audio settings**

- [ ] **Step 1: Write test for audio settings from config**

```python
def test_uses_config_audio_settings(self):
    """TTS audio settings (sample_rate, bitrate, format, channel) should come from config"""
    mock_config = MagicMock()
    mock_config.get.side_effect = lambda key: {
        "api.urls.minimax_tts": "https://api.minimax.io/v1/t2a_v2",
        "api.keys.minimax": "test-key",
        "generation.tts.model": "speech-2.8-hd",
        "generation.tts.timeout": 60,
        "generation.tts.sample_rate": 48000,
        "generation.tts.bitrate": 256000,
        "generation.tts.format": "mp3",
        "generation.tts.channel": 2,
    }.get(key)

    provider = MiniMaxTTSProvider(config=mock_config)
    # The generate method builds payload - verify it uses config values
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tts_config.py::TestMiniMaxTTSConfig::test_uses_config_audio_settings -v`
Expected: FAIL (settings not yet in config)

- [ ] **Step 3: Add audio settings to config and update generate payload**

In `configs/technical/config_technical.yaml`, under `generation.tts`:
```yaml
sample_rate: 32000
bitrate: 128000
format: "mp3"
channel: 1
```

In `MiniMaxTTSProvider.generate()`, update the payload:

```python
payload = {
    "model": self.model,  # from config
    "input_text": text,
    "voice_settings": {
        "sample_rate": self.config.get("generation.tts.sample_rate", 32000),
        "bitrate": self.config.get("generation.tts.bitrate", 128000),
        "format": self.config.get("generation.tts.format", "mp3"),
        "channel": self.config.get("generation.tts.channel", 1),
    },
    "request_type": "to_speech",
    "audio_type": self.config.get("generation.tts.format", "mp3"),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tts_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/media/tts.py configs/technical/config_technical.yaml tests/test_tts_config.py
git commit -m "feat(tts): audio settings (sample_rate, bitrate, format, channel) from config"
```

---

**Task 5: Remove hardcoded voice_map, use channel config voice catalog**

- [ ] **Step 1: Write test verifying voice_map is not used**

```python
def test_no_hardcoded_voice_map(self):
    """Voice mappings should come from channel config, not hardcoded voice_map"""
    # This test verifies the old hardcoded voice_map is gone
    import inspect
    from modules.media.tts import MiniMaxTTSProvider
    source = inspect.getsource(MiniMaxTTSProvider)
    assert "female_voice" not in source or "voice_map" not in source
```

- [ ] **Step 2: Run test to verify current state**

Run: `pytest tests/test_tts_config.py::TestMiniMaxTTSConfig::test_no_hardcoded_voice_map -v`
Expected: FAIL (voice_map still exists)

- [ ] **Step 3: Remove voice_map from MiniMaxTTSProvider, update get_voice method**

Remove the hardcoded `voice_map` dict. The `get_voice` method should read from channel config's `voices` catalog. Update:

```python
def get_voice(self, voice_id: str, config: TechnicalConfig) -> str:
    """Get voice ID from channel config voice catalog"""
    voices = config.get("voices", [])
    for voice in voices:
        if voice.get("id") == voice_id:
            providers = voice.get("providers", [])
            for prov in providers:
                if prov.get("provider") == "minimax":
                    return prov.get("model", voice_id)
    # fallback
    return voice_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tts_config.py::TestMiniMaxTTSConfig::test_no_hardcoded_voice_map -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/media/tts.py
git commit -m "feat(tts): remove hardcoded voice_map, read from channel config voice catalog"
```

---

**Task 6: Update EdgeTTSProvider similarly**

- [ ] **Step 1: Write similar tests for EdgeTTSProvider**

```python
def test_edge_uses_config_url(self):
    mock_config = MagicMock()
    mock_config.get.return_value = None
    # Should raise ConfigMissingKeyError if api.urls.edge_tts missing
    with pytest.raises(ConfigMissingKeyError):
        EdgeTTSProvider(config=mock_config)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tts_config.py -v`
Expected: FAIL

- [ ] **Step 3: Update EdgeTTSProvider to read from config**

```python
class EdgeTTSProvider:
    def __init__(self, config: TechnicalConfig = None, voice: str = None, speed: float = 1.0):
        self.config = config
        # For Edge, base_url isn't needed (Microsoft endpoint is fixed)
        # But validate required config exists
        if config and not config.get("generation.tts.model"):
            raise ConfigMissingKeyError("generation.tts.model", "EdgeTTSProvider")
        self.model = config.get("generation.tts.model") if config else None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_tts_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/media/tts.py tests/test_tts_config.py
git commit -m "feat(tts): EdgeTTSProvider also reads from config"
```

---

**Task 7: Update timeout values to use config**

- [ ] **Step 1: Write test for timeout from config**

```python
def test_timeout_from_config(self):
    mock_config = MagicMock()
    mock_config.get.side_effect = lambda key: {
        "api.urls.minimax_tts": "https://api.minimax.io/v1/t2a_v2",
        "api.keys.minimax": "test-key",
        "generation.tts.model": "speech-2.8-hd",
        "generation.tts.timeout": 120,  # custom timeout
    }.get(key)

    provider = MiniMaxTTSProvider(config=mock_config)
    assert provider.timeout == 120
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tts_config.py::TestMiniMaxTTSConfig::test_timeout_from_config -v`
Expected: FAIL

- [ ] **Step 3: Update code to use self.timeout**

In `MiniMaxTTSProvider.__init__` (already done in Task 3):
```python
self.timeout = config.get("generation.tts.timeout") if config else 60
```

Update `generate()` to use `self.timeout`:
```python
response = requests.post(
    self.base_url,
    headers=headers,
    json=payload,
    timeout=self.timeout  # use instance variable
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tts_config.py::TestMiniMaxTTSConfig::test_timeout_from_config -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add modules/media/tts.py
git commit -m "feat(tts): timeout values from config instead of hardcoded"
```

---

**Task 8: Update word_timestamp_timeout and /tmp paths**

- [ ] **Step 1: Write test for word_timestamp_timeout**

```python
def test_word_timestamp_timeout_from_config(self):
    mock_config = MagicMock()
    mock_config.get.side_effect = lambda key: {
        "api.urls.minimax_tts": "https://api.minimax.io/v1/t2a_v2",
        "api.keys.minimax": "test-key",
        "generation.tts.model": "speech-2.8-hd",
        "generation.tts.timeout": 60,
        "generation.tts.word_timestamp_timeout": 180,
    }.get(key)

    provider = MiniMaxTTSProvider(config=mock_config)
    # get_word_timestamps method should use config timeout
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update get_word_timestamps to use config timeout**

```python
def get_word_timestamps(self, audio_path: str, config: TechnicalConfig = None) -> List[dict]:
    timeout = (config.get("generation.tts.word_timestamp_timeout") if config else None) or 120
    # ... use timeout in subprocess call
```

- [ ] **Step 4: Update /tmp paths to use platform-aware tempfile**

```python
import tempfile
import os

def _get_temp_path(self, prefix: str) -> str:
    """Get platform-aware temp file path"""
    temp_dir = self.config.get("storage.temp_dir") if self.config else None
    if temp_dir:
        return os.path.join(temp_dir, f"{prefix}_{int(time.time()*1000)}.mp3")
    # Fallback to system temp dir
    fd, path = tempfile.mkstemp(suffix=".mp3", prefix=prefix)
    os.close(fd)
    return path
```

- [ ] **Step 5: Run tests and commit**

---

**Task 9: PR #1 — Final verification and cleanup**

- [ ] **Step 1: Run all TTS tests**

Run: `pytest tests/test_tts_config.py -v`
Expected: ALL PASS

- [ ] **Step 2: Verify no hardcoded values remain in tts.py**

Run: `grep -n "60\|120\|speech-2.8-hd\|32000\|128000\|mp3" modules/media/tts.py`
Expected: Only in comments or docstrings (acceptable), not in code logic

- [ ] **Step 3: Final commit for PR #1**

```bash
git add -A
git commit -m "feat(config): PR#1 TTS - all hardcoded values moved to config

- MiniMaxTTSProvider and EdgeTTSProvider now read from config
- API URL from api.urls.minimax_tts
- Model, audio settings, timeouts from generation.tts.*
- Voice mappings read from channel config voice catalog
- /tmp paths replaced with platform-aware tempfile
- ConfigMissingKeyError raised when required keys missing"
```

---

## PR #2: Image — `modules/media/image_gen.py`

### Files

- Modify: `modules/media/image_gen.py`
- Modify: `configs/technical/config_technical.yaml` (already partially done in PR #1)
- Test: `tests/test_image_config.py` (create new)

### Tasks

**Task 1: Add Image config keys to technical config**

- [ ] **Step 1: Add missing Image keys to technical config**

```yaml
generation:
  image:
    timeout: 120
    poll_interval: 5
    max_polls: 24
```

- [ ] **Step 2: Commit**

```bash
git add configs/technical/config_technical.yaml
git commit -m "feat(config): add missing Image keys to technical config"
```

---

**Task 2: Update MiniMaxImageProvider to use config**

- [ ] **Step 1: Write test for MiniMaxImageProvider config**

Create `tests/test_image_config.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from modules.media.image_gen import MiniMaxImageProvider
from modules.pipeline.exceptions import ConfigMissingKeyError

class TestMiniMaxImageConfig:
    def test_uses_config_url(self):
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.minimax_image": "https://custom.image.api.io",
            "api.keys.minimax": "test-key",
            "generation.image.timeout": 120,
        }.get(key)

        provider = MiniMaxImageProvider(config=mock_config)
        assert provider.base_url == "https://custom.image.api.io"

    def test_raises_error_when_url_missing(self):
        mock_config = MagicMock()
        mock_config.get.return_value = None

        with pytest.raises(ConfigMissingKeyError):
            MiniMaxImageProvider(config=mock_config)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_image_config.py::TestMiniMaxImageConfig::test_uses_config_url -v`
Expected: FAIL

- [ ] **Step 3: Update MiniMaxImageProvider to use config**

```python
class MiniMaxImageProvider(ImageProvider):
    DEFAULT_URL = None  # Remove hardcoded

    def __init__(self, config: TechnicalConfig = None, api_key: str = None):
        self.config = config
        base_url = config.get("api.urls.minimax_image") if config else None
        if not base_url:
            raise ConfigMissingKeyError("api.urls.minimax_image", "MiniMaxImageProvider")
        self.base_url = base_url
        self.api_key = api_key or (config.get("api.keys.minimax") if config else None)
        self.timeout = config.get("generation.image.timeout") if config else 120
        self.model = config.get("generation.image.model") if config else "image-01"
```

- [ ] **Step 4: Update generate() to use self.timeout and self.model**

```python
payload = {
    "model": self.model,  # from config
    "prompt": prompt,
    "aspect_ratio": aspect_ratio,
    "response_format": "url",
}
response = requests.post(
    f"{self.base_url}",
    headers=headers,
    json=payload,
    timeout=self.timeout
)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_image_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add modules/media/image_gen.py tests/test_image_config.py
git commit -m "feat(image): MiniMaxImageProvider reads URL, timeout, model from config"
```

---

**Task 3: Update WaveSpeedImageProvider**

- [ ] **Step 1: Write test for WaveSpeedImageProvider config**

```python
def test_wavespeed_uses_config_url(self):
    mock_config = MagicMock()
    mock_config.get.side_effect = lambda key: {
        "api.urls.wavespeed": "https://custom.wavespeed.io",
        "api.keys.wavespeed": "test-key",
        "generation.image.timeout": 120,
        "generation.image.poll_interval": 5,
        "generation.image.max_polls": 24,
    }.get(key)

    provider = WaveSpeedImageProvider(config=mock_config)
    assert provider.base_url == "https://custom.wavespeed.io"
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update WaveSpeedImageProvider to use config**

```python
class WaveSpeedImageProvider(ImageProvider):
    def __init__(self, config: TechnicalConfig = None, api_key: str = None):
        self.config = config
        base_url = config.get("api.urls.wavespeed") if config else None
        if not base_url:
            raise ConfigMissingKeyError("api.urls.wavespeed", "WaveSpeedImageProvider")
        self.base_url = base_url
        self.api_key = api_key or (config.get("api.keys.wavespeed") if config else None)
        self.timeout = config.get("generation.image.timeout") if config else 120
        self.poll_interval = config.get("generation.image.poll_interval") if config else 5
        self.max_polls = config.get("generation.image.max_polls") if config else 24
```

- [ ] **Step 4: Update wait_for_job to use config poll_interval and max_polls**

```python
def wait_for_job(self, task_id: str) -> dict:
    max_wait = self.config.get("generation.image.max_polls", 24) * self.poll_interval
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(self.poll_interval)
        elapsed += self.poll_interval
        # ... poll logic
```

- [ ] **Step 5: Run tests and commit**

---

**Task 4: Update KieImageProvider**

- [ ] **Step 1: Update KieImageProvider similarly**

```python
class KieImageProvider(ImageProvider):
    def __init__(self, config: TechnicalConfig = None, api_key: str = None):
        self.config = config
        base_url = config.get("api.urls.kie_ai") if config else None
        if not base_url:
            raise ConfigMissingKeyError("api.urls.kie_ai", "KieImageProvider")
        self.base_url = base_url
        self.api_key = api_key or (config.get("api.keys.kie_ai") if config else None)
        self.timeout = config.get("generation.image.timeout") if config else 120
        self.poll_interval = config.get("generation.image.poll_interval") if config else 5
        self.max_polls = config.get("generation.image.max_polls") if config else 24
```

- [ ] **Step 2: Update wait_for_task similarly**

- [ ] **Step 3: Commit**

---

**Task 5: Update download timeouts to use config**

- [ ] **Step 1: Update image download method to use config timeout**

```python
def download_image(self, url: str, output_path: str = None) -> str:
    download_timeout = self.config.get("generation.image.timeout") if self.config else 120
    # ... use download_timeout in requests.get
```

- [ ] **Step 2: Commit**

---

**Task 6: PR #2 — Final verification**

- [ ] **Step 1: Run all Image tests**

Run: `pytest tests/test_image_config.py -v`
Expected: ALL PASS

- [ ] **Step 2: Verify no hardcoded URLs remain in image_gen.py**

Run: `grep -n "https://api.minimax.io\|https://api.wavespeed.ai\|https://api.kie.ai" modules/media/image_gen.py`
Expected: No matches (URLs should only be in config)

- [ ] **Step 3: Final commit for PR #2**

---

## PR #3: Lipsync — `modules/media/lipsync.py`

### Files

- Modify: `modules/media/lipsync.py`
- Modify: `configs/technical/config_technical.yaml` (add missing keys)
- Test: `tests/test_lipsync_config.py` (create new)

### Tasks

**Task 1: Add Lipsync config keys to technical config**

```yaml
generation:
  lipsync:
    poll_interval: 10
    retries: 2
```

Commit: `git add configs/technical/config_technical.yaml && git commit -m "feat(config): add missing Lipsync keys"`

---

**Task 2: Update WaveSpeedLipsyncProvider to use config**

- [ ] **Step 1: Write tests for WaveSpeedLipsyncProvider config**

Create `tests/test_lipsync_config.py`:

```python
class TestWaveSpeedLipsyncConfig:
    def test_uses_config_base_url(self):
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.wavespeed": "https://custom.wavespeed.io",
            "api.keys.wavespeed": "test-key",
            "generation.lipsync.max_wait": 300,
            "generation.lipsync.poll_interval": 10,
            "generation.lipsync.retries": 3,
        }.get(key)

        provider = WaveSpeedLipsyncProvider(config=mock_config)
        assert provider.base_url == "https://custom.wavespeed.io"

    def test_raises_error_when_url_missing(self):
        mock_config = MagicMock()
        mock_config.get.return_value = None

        with pytest.raises(ConfigMissingKeyError):
            WaveSpeedLipsyncProvider(config=mock_config)
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update WaveSpeedLipsyncProvider.__init__**

```python
class WaveSpeedLipsyncProvider(LipsyncProvider):
    def __init__(self, config: TechnicalConfig = None, api_key: str = None):
        self.config = config
        base_url = config.get("api.urls.wavespeed") if config else None
        if not base_url:
            raise ConfigMissingKeyError("api.urls.wavespeed", "WaveSpeedLipsyncProvider")
        self.base_url = base_url
        self.api_key = api_key or (config.get("api.keys.wavespeed") if config else None)
        self.poll_interval = config.get("generation.lipsync.poll_interval") if config else 10
        self.max_wait = config.get("generation.lipsync.max_wait") if config else 300
```

- [ ] **Step 4: Update wait_for_job to use config values**

```python
def wait_for_job(self, job_id: str) -> dict:
    elapsed = 0
    interval = self.poll_interval  # from config
    max_wait = self.max_wait  # from config
    while elapsed < max_wait:
        time.sleep(interval)
        elapsed += interval
        # ... poll logic
```

- [ ] **Step 5: Update retries in generate()**

```python
def generate(self, image_path: str, audio_path: str, cfg: dict = None) -> str:
    cfg = cfg or {}
    retries = cfg.get("retries", self.config.get("generation.lipsync.retries", 2) if self.config else 2)
    # ... use retries
```

- [ ] **Step 6: Run tests and commit**

---

**Task 3: Update WaveSpeedMultiTalkProvider**

- [ ] **Step 1: Same pattern as WaveSpeedLipsyncProvider**
- [ ] **Step 2: Commit**

---

**Task 4: Update KieAIInfinitalkProvider**

- [ ] **Step 1: Same pattern, use `api.urls.kie_ai` for base_url**
- [ ] **Step 2: Commit**

---

**Task 5: Update default resolution to use channel config**

- [ ] **Step 1: Write test for resolution from config**

```python
def test_resolution_from_config_or_channel(self):
    mock_config = MagicMock()
    mock_config.get.side_effect = lambda key: {
        "api.urls.kie_ai": "https://api.kie.ai/api/v1",
        "api.keys.kie_ai": "test-key",
        "generation.lipsync.poll_interval": 10,
        "generation.lipsync.retries": 2,
        "video.resolution": "720p",
    }.get(key)

    provider = KieAIInfinitalkProvider(config=mock_config)
    # Resolution comes from channel config, provider just uses cfg.get("resolution", default)
```

- [ ] **Step 2: The resolution default is already in channel config at `video.resolution` - no code change needed if scene_processor passes channel config**
- [ ] **Step 3: Commit**

---

**Task 6: PR #3 — Final verification**

- [ ] **Step 1: Run all Lipsync tests**

Run: `pytest tests/test_lipsync_config.py -v`
Expected: ALL PASS

- [ ] **Step 2: Verify no hardcoded URLs remain**

Run: `grep -n "https://api.wavespeed.ai\|https://api.kie.ai" modules/media/lipsync.py`
Expected: No matches

- [ ] **Step 3: Final commit for PR #3**

---

## PR #4: Content — `modules/content/*.py`, `utils/embedding.py`

### Files

- Modify: `modules/content/content_pipeline.py`
- Modify: `modules/content/content_idea_generator.py`
- Modify: `utils/embedding.py`
- Modify: `configs/technical/config_technical.yaml` (add missing keys)
- Modify: `configs/channels/*/config.yaml` (add missing per-channel keys)
- Test: `tests/test_content_config.py` (create new)

### Tasks

**Task 1: Add Content/Embedding config keys to technical config**

```yaml
generation:
  llm:
    retry_attempts: 3
    retry_backoff_max: 10
  content:
    scene_count: 3
    checkpoint_path: ".content_pipeline_checkpoint.json"

embedding:
  model: "distiluse-base-multilingual-cased-v2"
  similarity_threshold: 0.75
  translation_max_tokens: 200
```

Commit: `git add configs/technical/config_technical.yaml && git commit -m "feat(config): add Content and Embedding keys"`

---

**Task 2: Update ContentIdeaGenerator to use config**

- [ ] **Step 1: Write test for ContentIdeaGenerator config**

Create `tests/test_content_config.py`:

```python
class TestContentIdeaGeneratorConfig:
    def test_uses_config_model_and_tokens(self):
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "generation.llm.model": "custom-llm-model",
            "generation.llm.max_tokens": 2048,
            "generation.llm.retry_attempts": 5,
        }.get(key)

        generator = ContentIdeaGenerator(config=mock_config)
        assert generator._llm_config.get("model") == "custom-llm-model"
        assert generator._llm_config.get("max_tokens") == 2048

    def test_raises_error_when_llm_config_missing(self):
        mock_config = MagicMock()
        mock_config.get.return_value = None

        with pytest.raises(ConfigMissingKeyError):
            ContentIdeaGenerator(config=mock_config)
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update ContentIdeaGenerator.__init__**

```python
class ContentIdeaGenerator:
    def __init__(self, config: TechnicalConfig = None):
        self.config = config
        self._llm_config = {}
        if config:
            model = config.get("generation.llm.model")
            if not model:
                raise ConfigMissingKeyError("generation.llm.model", "ContentIdeaGenerator")
            self._llm_config["model"] = model
            self._llm_config["max_tokens"] = config.get("generation.llm.max_tokens", 1536)
            self._llm_config["retry_attempts"] = config.get("generation.llm.retry_attempts", 3)
```

- [ ] **Step 4: Update generate_ideas_from_topics to use config retry**

```python
@retry(
    stop=stop_after_attempt(self._llm_config.get("retry_attempts", 3)),
    wait=wait_exponential(multiplier=1, min=1, max=config.get("generation.llm.retry_backoff_max", 10))
)
def generate_ideas_from_topics(self, topics: List[str], channel_id: str) -> List[dict]:
    max_tokens = self._llm_config.get("max_tokens", 1536)
    # ... use max_tokens in llm.chat call
```

- [ ] **Step 5: Run tests and commit**

---

**Task 3: Update ContentPipeline to use config for scene_count, checkpoint, schedule**

- [ ] **Step 1: Write test for ContentPipeline config**

```python
class TestContentPipelineConfig:
    def test_uses_config_scene_count(self):
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "generation.content.scene_count": 5,
            "generation.content.checkpoint_path": ".custom_checkpoint.json",
        }.get(key)

        pipeline = ContentPipeline(config=mock_config)
        assert pipeline.scene_count == 5
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update ContentPipeline.__init__ and methods**

```python
class ContentPipeline:
    def __init__(self, config: TechnicalConfig = None, channel_id: str = None):
        self.config = config
        self.scene_count = config.get("generation.content.scene_count", 3) if config else 3
        self.checkpoint_path = config.get("generation.content.checkpoint_path", ".content_pipeline_checkpoint.json") if config else ".content_pipeline_checkpoint.json"

    def _get_schedule_time(self) -> time:
        schedule_hour = self.config.get("research.schedule_hour", 9) if self.config else 9
        schedule_minute = self.config.get("research.schedule_minute", 0) if self.config else 0
        return time(schedule_hour, schedule_minute)
```

- [ ] **Step 4: Run tests and commit**

---

**Task 4: Update embedding.py to use config**

- [ ] **Step 1: Write test for embedding config**

```python
class TestEmbeddingConfig:
    def test_uses_config_model_and_threshold(self):
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "embedding.model": "custom-embedding-model",
            "embedding.similarity_threshold": 0.85,
        }.get(key)

        # embedding.py uses global singleton or class
        from utils.embedding import load_embedding_model
        model = load_embedding_model(config=mock_config)
        assert model is not None
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update embedding.py**

```python
EMBED_DIM = 512
SIMILARITY_THRESHOLD = 0.75  # Default, can be overridden by config

def load_embedding_model(config: TechnicalConfig = None):
    global SIMILARITY_THRESHOLD
    model_name = "distiluse-base-multilingual-cased-v2"
    if config:
        model_name = config.get("embedding.model", model_name)
        SIMILARITY_THRESHOLD = config.get("embedding.similarity_threshold", SIMILARITY_THRESHOLD)
    return SentenceTransformer(model_name)
```

- [ ] **Step 4: Update translate_to_english to use config max_tokens**

```python
def translate_to_english(text: str, config: TechnicalConfig = None) -> str:
    max_tokens = config.get("embedding.translation_max_tokens", 200) if config else 200
    # ... use max_tokens in llm.chat call
```

- [ ] **Step 5: Run tests and commit**

---

**Task 5: PR #4 — Final verification**

- [ ] **Step 1: Run all Content tests**

Run: `pytest tests/test_content_config.py -v`
Expected: ALL PASS

- [ ] **Step 2: Final commit for PR #4**

---

## PR #5: Pipeline — `modules/pipeline/scene_processor.py`, `modules/pipeline/pipeline_runner.py`, `scripts/*.py`

### Files

- Modify: `modules/pipeline/scene_processor.py`
- Modify: `modules/pipeline/pipeline_runner.py`
- Modify: `scripts/run_pipeline.py`
- Modify: `scripts/video_pipeline_v3.py`
- Modify: `configs/technical/config_technical.yaml` (add missing keys)
- Test: `tests/test_pipeline_config.py` (create new)

### Tasks

**Task 1: Add Pipeline config keys to technical config**

```yaml
generation:
  pipeline:
    max_retries: 3

storage:
  output_dir: "output"
```

Commit: `git add configs/technical/config_technical.yaml && git commit -m "feat(config): add Pipeline and Storage keys"`

---

**Task 2: Update SceneProcessor to use config for max_workers and fallbacks**

- [ ] **Step 1: Write test for SceneProcessor config**

Create `tests/test_pipeline_config.py`:

```python
class TestSceneProcessorConfig:
    def test_uses_config_max_workers(self):
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "generation.parallel_scene_processing.max_workers": 4,
        }.get(key)

        processor = SceneProcessor(config=mock_config)
        assert processor.max_workers == 4

    def test_uses_config_fallback_voice(self):
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "generation.models.tts": "edge",
            "voices": [{"id": "female_voice", ...}]  # voice catalog
        }.get(key)

        # Test _get_tts_provider returns edge from config
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update SceneProcessor.__init__**

```python
class SceneProcessor:
    def __init__(self, config: PipelineContext):
        self.config = config
        self.max_workers = config.technical.get("generation.parallel_scene_processing.max_workers", 3) if config.technical else 3
```

- [ ] **Step 4: Update _get_tts_provider to use config fallback provider**

```python
def _get_tts_provider(self, character):
    provider_name = character.tts_provider if hasattr(character, 'tts_provider') else None
    if not provider_name:
        provider_name = self.config.channel.get("generation.models.tts", "edge")
    voice_id = getattr(character, 'tts_voice', None)
    if not voice_id:
        voice_id = self.config.channel.get("voices", [{}])[0].get("id", "female_voice") if self.config.channel.get("voices") else "female_voice"
    speed = getattr(character, 'tts_speed', 1.0)
    return provider_name, voice_id, speed
```

- [ ] **Step 5: Update _get_background to use config default**

```python
def _get_background(self, scene):
    background = scene.background if hasattr(scene, 'background') else None
    if not background:
        background = self.config.channel.get("generation.lipsync.prompt", "a person talking")
    return background
```

- [ ] **Step 6: Run tests and commit**

---

**Task 3: Update PipelineRunner to use config for output_dir, max_workers**

- [ ] **Step 1: Write test for PipelineRunner config**

```python
class TestPipelineRunnerConfig:
    def test_uses_config_output_dir(self):
        mock_config = MagicMock()
        mock_config.technical.get.side_effect = lambda key, default=None: {
            "storage.output_dir": "/custom/output",
            "generation.parallel_scene_processing.max_workers": 4,
        }.get(key, default)

        runner = PipelineRunner(config=mock_config)
        assert runner.output_dir == "/custom/output"
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update PipelineRunner.__init__**

```python
class PipelineRunner:
    def __init__(self, config: PipelineContext):
        self.config = config
        self.output_dir = config.technical.get("storage.output_dir", "output") if config.technical else "output"
        self.max_workers = config.technical.get("generation.parallel_scene_processing.max_workers", 3) if config.technical else 3
```

- [ ] **Step 4: Update ThreadPoolExecutor to use max_workers**

```python
self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
```

- [ ] **Step 5: Update aspect_ratio usage to use channel config**

```python
# In pipeline_runner.py, wherever aspect_ratio="9:16" is hardcoded:
aspect_ratio = self.config.channel.get("video.aspect_ratio", "9:16") if self.config.channel else "9:16"
```

- [ ] **Step 6: Update subtitle font_size fallback to use config**

```python
font_size = subtitle_cfg.font_size if subtitle_cfg else (
    self.config.channel.get("subtitle.font_size", 60) if self.config.channel else 60
)
```

- [ ] **Step 7: Run tests and commit**

---

**Task 4: Update run_pipeline.py to use config for default channel**

- [ ] **Step 1: Write test for run_pipeline config**

```python
def test_default_channel_from_config():
    # run_pipeline.py reads from config or uses CLI argument
    # No hardcoded default should exist
    import inspect
    from scripts import run_pipeline
    source = inspect.getsource(run_pipeline)
    # Check no hardcoded "nang_suat_thong_minh" default
```

- [ ] **Step 2: Update run_pipeline.py argument parser**

```python
# Remove hardcoded default channel
parser.add_argument("--channel", default=None, help="Channel ID (required if not in config)")
```

- [ ] **Step 3: Commit**

---

**Task 5: Update video_pipeline_v3.py to use config for max_retries, wps**

- [ ] **Step 1: Write test for video_pipeline_v3 config**

```python
class TestVideoPipelineConfig:
    def test_max_retries_from_config(self):
        mock_config = MagicMock()
        mock_config.technical.get.side_effect = lambda key, default=None: {
            "generation.pipeline.max_retries": 5,
            "generation.tts.words_per_second": 3.0,
        }.get(key, default)

        # Test video_pipeline_v3 respects these config values
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update video_pipeline_v3.py**

```python
# At top of script or in main():
max_retries = technical_cfg.get("generation.pipeline.max_retries", 3) if technical_cfg else 3
wps = technical_cfg.get("generation.tts.words_per_second", 2.5) if technical_cfg else 2.5

# Use max_retries in retry logic
# Use wps in duration calculation
```

- [ ] **Step 4: Run tests and commit**

---

**Task 6: PR #5 — Final verification**

- [ ] **Step 1: Run all Pipeline tests**

Run: `pytest tests/test_pipeline_config.py -v`
Expected: ALL PASS

- [ ] **Step 2: Final commit for PR #5**

```bash
git add -A
git commit -m "feat(config): PR#5 Pipeline - all hardcoded values moved to config

- SceneProcessor reads max_workers, fallback provider/voice from config
- PipelineRunner reads output_dir, max_workers from config
- run_pipeline.py and video_pipeline_v3.py use config for defaults
- Subtitle font_size and watermark settings from channel config
- All config keys validated, missing keys raise ConfigMissingKeyError"
```

---

## Final Verification

**After all 5 PRs:**

1. Run full test suite:
```bash
pytest tests/ -v
```

2. Verify no hardcoded values remain:
```bash
# Check for common hardcoded patterns
grep -rn "timeout=60\|timeout=120\|timeout=180" modules/ --include="*.py" | grep -v test | grep -v "#"
grep -rn "\"9:16\"" modules/ --include="*.py" | grep -v test | grep -v "#"
grep -rn "/tmp/" modules/ --include="*.py" | grep -v test | grep -v "#"
```

3. Verify all config keys are used:
```bash
# After PRs complete, verify config values are actually consumed
grep -rn "config.get\|config\[" configs/technical/config_technical.yaml | head -50
```

---

## Rollback Plan

If any PR causes issues:
```bash
# Revert a specific PR
git revert <pr-commit-hash>

# Or reset to before PR
git reset --hard <before-pr-commit>
git push --force
```

---

## Notes

- ConfigMissingKeyError is added in PR #1 Task 2, used by all subsequent PRs
- All PRs are backward compatible: existing config files with all keys present = no behavior change
- New strict validation only kicks in when keys are missing
- Channel configs (per-channel) are NOT modified by this refactoring (they already have the right structure)
