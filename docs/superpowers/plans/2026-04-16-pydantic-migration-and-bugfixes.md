# Pydantic Migration & Bugfixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `self.api_key` typo bug in TTS and migrate dict-based `.get()`/`hasattr` patterns to direct Pydantic attribute access throughout the pipeline modules.

**Architecture:** Changes are isolated per file. No architectural changes — purely mechanical refactors to use Pydantic models correctly where they already exist, and to properly validate raw dicts (LLM JSON output) through `SceneConfig.from_dict()`.

**Tech Stack:** Pydantic v2, pytest, Python 3.14

---

## File Map

| File | Change |
|------|--------|
| `modules/media/tts.py` | Fix `self.api_key` → `self._api_key` typo (Bug) |
| `modules/pipeline/scene_processor.py` | Remove `hasattr` checks; use `SceneConfig` properly; type method signatures |
| `modules/content/content_idea_generator.py` | Remove `hasattr` on Pydantic; validate LLM JSON through `SceneConfig.from_dict()` |
| `modules/content/content_pipeline.py` | Remove `hasattr` for `_runner` attribute |
| `modules/media/image_gen.py` | Remove `hasattr` for guaranteed `GenerationImage.model` |
| `modules/media/lipsync.py` | Remove `isinstance(config, dict)` backward compat fallback |

---

## Task 1: Fix `self.api_key` typo in MiniMaxTTSProvider

**Files:**
- Modify: `modules/media/tts.py:77,114`

- [ ] **Step 1: Write failing test that exposes the bug**

The bug: `MiniMaxTTSProvider.generate()` references `self.api_key` at line 77, but the attribute is named `self._api_key`. No test currently catches this because the actual API call is mocked in all tests.

```python
# tests/test_tts_config.py
def test_minimax_tts_uses_correct_api_key_attribute():
    """Regression: self.api_key should be self._api_key."""
    from unittest.mock import patch, MagicMock
    from modules.pipeline.models import TechnicalConfig

    mock_config = MagicMock(spec=TechnicalConfig)
    mock_config.api_keys.minimax = "test-key"
    mock_config.api_urls.minimax_tts = "https://api.minimax.io/v1/t2a_v2"
    mock_config.generation.tts.model = "speech-2.1-hd"
    mock_config.generation.tts.sample_rate = 32000
    mock_config.generation.tts.timeout = 60
    mock_config.generation.tts.bitrate = 128000
    mock_config.generation.tts.format = "mp3"
    mock_config.generation.tts.channel = 1
    mock_config.storage.temp_dir = None

    provider = MiniMaxTTSProvider(config=mock_config)

    # Verify the attribute is named _api_key, not api_key
    assert hasattr(provider, '_api_key'), "Provider should have _api_key attribute"
    assert provider._api_key == "test-key"
    assert not hasattr(provider, 'api_key') or provider.__dict__.get('api_key') is None, \
        "api_key should not be a separate attribute (it's _api_key)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tts_config.py::test_minimax_tts_uses_correct_api_key_attribute -v`
Expected: PASS (both assertions should pass even before fix since the attribute is `_api_key`)

Actually, since the test above passes on current code, let me write a test that actually triggers the `generate()` method path which has the bug:

```python
# Add to tests/test_tts_config.py
def test_minimax_tts_generate_calls_correct_api_key():
    """Regression: generate() uses self._api_key not self.api_key."""
    import requests
    from unittest.mock import patch, MagicMock
    from modules.pipeline.models import TechnicalConfig

    mock_config = MagicMock(spec=TechnicalConfig)
    mock_config.api_keys.minimax = "test-key-123"
    mock_config.api_urls.minimax_tts = "https://api.minimax.io/v1/t2a_v2"
    mock_config.generation.tts.model = "speech-2.1-hd"
    mock_config.generation.tts.sample_rate = 32000
    mock_config.generation.tts.timeout = 5
    mock_config.generation.tts.bitrate = 128000
    mock_config.generation.tts.format = "mp3"
    mock_config.generation.tts.channel = 1
    mock_config.storage.temp_dir = "/tmp"

    provider = MiniMaxTTSProvider(config=mock_config)

    # Patch requests.post to capture the call
    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "base_resp": {"status_code": 0},
            "data": {"audio": ""}
        }
        mock_post.return_value = mock_response

        provider.generate("test text", "female_voice", 1.0, "/tmp/test_output.mp3")

        # Check the Authorization header used the correct key
        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get('headers', {})
        auth_header = headers.get('Authorization', '')
        assert auth_header == "Bearer test-key-123", \
            f"Expected 'Bearer test-key-123', got '{auth_header}' — bug: using self.api_key instead of self._api_key"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_tts_config.py::test_minimax_tts_generate_calls_correct_api_key -v`
Expected: FAIL — `self.api_key` raises `AttributeError`

- [ ] **Step 4: Fix the typo in both occurrences**

```python
# modules/media/tts.py line 77
-             headers = {"Authorization": f"Bearer {self.api_key}", ...
+             headers = {"Authorization": f"Bearer {self._api_key}", ...

# modules/media/tts.py line 114 (get_word_timestamps)
-         headers = {"Authorization": f"Bearer {self.api_key}", ...
+         headers = {"Authorization": f"Bearer {self._api_key}", ...
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_tts_config.py::test_minimax_tts_generate_calls_correct_api_key -v`
Expected: PASS

- [ ] **Step 6: Run full TTS test suite**

Run: `pytest tests/test_tts_config.py tests/test_tts.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add modules/media/tts.py tests/test_tts_config.py
git commit -m "fix(tts): use self._api_key instead of self.api_key in MiniMaxTTSProvider.generate()"
```

---

## Task 2: Migrate `scene_processor.py` to use Pydantic directly

**Files:**
- Modify: `modules/pipeline/scene_processor.py:244,252,59-65,97-131`

### 2a. Fix `hasattr` for `SceneCharacter.name` (line 244)

The `SceneConfig.characters` is `List["SceneCharacter | str"]`. When a string is passed, `hasattr(string, 'name')` is False. This is correctly handled, but the real fix is to **normalize all characters to `SceneCharacter` objects** upstream in `SceneConfig.from_dict()` so the union is never needed downstream.

Currently `SceneConfig.from_dict()` already normalizes to `SceneCharacter`, so downstream code should never receive a bare string. However, `SingleCharSceneProcessor.process()` is typed as receiving `Dict[str, Any]` — it needs to accept `SceneConfig`.

**Changes:**
- `SingleCharSceneProcessor.process(scene: Dict[str, Any], ...)` → `process(scene: SceneConfig, ...)`
- `SceneProcessor.get_character(name: str) -> Optional[Dict[str, Any]]` → `-> Optional[CharacterConfig]`
- `SceneProcessor.get_voice(voice_id: str) -> Optional[Dict[str, Any]]` → `-> Optional[VoiceConfig]`
- `SceneProcessor.resolve_voice(character, scene)` → use proper types

- [ ] **Step 1: Add/update tests for new type signatures**

```python
# tests/test_scene_processor.py
def test_process_accepts_scene_config_not_dict():
    """SingleCharSceneProcessor.process should accept SceneConfig, not raw dict."""
    from modules.pipeline.models import SceneConfig, SceneCharacter, CharacterConfig, VoiceConfig, VoiceProvider

    ctx = MagicMock(spec=PipelineContext)
    ctx.channel.characters = [
        CharacterConfig(name="Anchor", voice_id="female_voice")
    ]
    ctx.channel.voices = [
        VoiceConfig(
            id="female_voice",
            name="Female Voice",
            gender="female",
            providers=[VoiceProvider(provider="edge", model="vi-VN-HoaiMyNeural", speed=1.0)]
        )
    ]
    ctx.channel.tts = MagicMock(spec=[])  # empty — skip duration check
    ctx.channel.generation = None
    ctx.channel.image_style = None
    ctx.technical.generation.parallel_scene_processing.max_workers = 2
    ctx.technical.storage.output_dir = "/tmp"

    processor = SingleCharSceneProcessor(ctx, Path("/tmp/sp_test"))

    scene = SceneConfig(
        id=1,
        tts="Xin chào các bạn",
        characters=[SceneCharacter(name="Anchor")],
    )

    # This should work without converting scene to dict
    with patch.object(processor, '_run_tts', return_value=("/tmp/audio.mp3", [])):
        with patch.object(processor, 'get_whisper_timestamps', return_value=[]):
            with patch('modules.pipeline.scene_processor.crop_to_9x16', return_value="/tmp/out.mp4"):
                with patch('modules.pipeline.scene_processor.create_static_video_with_audio', return_value="/tmp/static.mp4"):
                    # If process() expects Dict, this fails TypeError
                    # After fix, it should accept SceneConfig
                    result = processor.process(scene, Path("/tmp/scene_out"),
                        tts_fn=lambda *a, **k: ("/tmp/audio.mp3", []),
                        image_fn=lambda *a, **k: "/tmp/img.png",
                        lipsync_fn=lambda *a, **k: "/tmp/vid.mp4")
                    assert result is not None
```

- [ ] **Step 2: Run test — verify it fails (type error or AttributeError)**

Run: `pytest tests/test_scene_processor.py::test_process_accepts_scene_config_not_dict -v 2>&1 | head -30`
Expected: FAIL — likely TypeError or AttributeError since `process()` still expects `Dict`

- [ ] **Step 3: Fix `process()` signature and internal dict access**

Change `process()` first arg from `Dict[str, Any]` to `SceneConfig`:

```python
# modules/pipeline/scene_processor.py

def process(self, scene: SceneConfig, scene_output: Path,
           tts_fn, image_fn, lipsync_fn) -> Tuple[Optional[str], List[Dict]]:
```

Update internal accesses:
```python
# Before (line 228):
tts_text = scene.tts or scene.script or ""
chars = scene.characters or []

# Before (line 244):
char_name = first_char.name if hasattr(first_char, 'name') else first_char

# After:
tts_text = scene.tts or scene.script or ""
chars = scene.characters or []

# SceneCharacter always has .name; chars is List[SceneCharacter]
# so first_char is always SceneCharacter
first_char = chars[0]
char_name = first_char.name  # no hasattr needed

# Before (line 252):
if hasattr(chars[0], 'speed') and chars[0].speed:
    speed = chars[0].speed

# After:
if chars[0].speed:  # None is falsy
    speed = chars[0].speed
```

- [ ] **Step 4: Fix `get_character()` return type**

```python
# Before:
def get_character(self, name: str) -> Optional[Dict[str, Any]]:

# After:
def get_character(self, name: str) -> Optional[CharacterConfig]:
    chars = self.ctx.channel.characters or []
    for char in chars:
        if char.name == name:
            return char
    return None
```

- [ ] **Step 5: Fix `get_voice()` return type and eliminate hasattr**

```python
# Before:
def get_voice(self, voice_id: str) -> Optional[Dict[str, Any]]:
    voices = self.ctx.channel.voices or []
    for voice in voices:
        if voice.id == voice_id:
            return voice
    return None

# After (already correct — just ensure no hasattr):
def get_voice(self, voice_id: str) -> Optional[VoiceConfig]:
    voices = self.ctx.channel.voices or []
    for voice in voices:
        if voice.id == voice_id:
            return voice
    return None
```

- [ ] **Step 6: Fix `resolve_voice()` — remove hasattr checks**

```python
# Before (lines 74-95):
voice = self.get_voice(voice_id) if voice_id else None
if voice:
    providers = voice.providers or []
    if providers:
        primary = providers[0]
        return (
            primary.provider,
            primary.model,
            primary.speed,
            voice.gender or "female",
        )
fallback_provider = self.ctx.channel.generation.models.tts if self.ctx.channel.generation else None

# After: (already mostly correct, just remove redundant hasattr)
voice = self.get_voice(voice_id) if voice_id else None
if voice and voice.providers:
    primary = voice.providers[0]
    return (
        primary.provider,
        primary.model,
        primary.speed,
        voice.gender or "female",
    )
# ...rest unchanged
```

Note: `self.ctx.channel.generation.models.tts` — `models.tts` comes from `GenerationModels` which always exists on `GenerationSettings`. But `GenerationSettings` is Optional in `ChannelConfig`. The hasattr guards this. Keep the `hasattr` for `generation` (Optional chain) but remove the others.

Actually, the hasattr at line 88 (`self.ctx.channel.generation`) is valid since `generation` is `Optional[GenerationSettings]`. Keep it. Just clean up the other hasattr calls.

- [ ] **Step 7: Run scene processor tests**

Run: `pytest tests/test_scene_processor.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add modules/pipeline/scene_processor.py
git commit -m "refactor(scene_processor): use Pydantic SceneConfig directly, remove dict/hasattr patterns"
```

---

## Task 3: Fix `content_idea_generator.py` — remove `hasattr` on Pydantic, validate LLM JSON

**Files:**
- Modify: `modules/content/content_idea_generator.py:160-162,166,170,361-385`

- [ ] **Step 1: Write test for `hasattr` on Pydantic fields**

```python
# tests/test_content_idea_generator.py
def test_words_per_second_read_directly_from_pydantic():
    """wps should be read directly from GenerationConfig.tts.words_per_second, not via hasattr."""
    from unittest.mock import MagicMock
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import GenerationConfig, GenerationTTS

    tech_cfg = MagicMock(spec=TechnicalConfig)
    gen_cfg = GenerationConfig(
        tts=GenerationTTS(words_per_second=3.5)
    )
    tech_cfg.generation = gen_cfg

    gen = ContentIdeaGenerator(
        project_id=1,
        content_config=MagicMock(),
        technical_config=tech_cfg,
    )

    # Access _technical_config directly to verify it's set
    assert gen._technical_config is tech_cfg
    assert gen._technical_config.generation.tts.words_per_second == 3.5
```

- [ ] **Step 2: Fix `hasattr` on Pydantic fields (lines 160-162)**

```python
# Before:
if self._technical_config and hasattr(self._technical_config, 'generation'):
    gen_cfg = self._technical_config.generation
    if hasattr(gen_cfg, 'tts') and gen_cfg.tts and hasattr(gen_cfg.tts, 'words_per_second'):
        wps = gen_cfg.tts.words_per_second

# After: Pydantic fields always exist; use getattr with default
if self._technical_config and self._technical_config.generation:
    gen_cfg = self._technical_config.generation
    if gen_cfg.tts:
        wps = getattr(gen_cfg.tts, 'words_per_second', 2.5)
```

- [ ] **Step 3: Fix scene dict `.get()` calls — validate through SceneConfig.from_dict()**

After LLM JSON parsing (line 244-249), scenes are raw dicts. The `_validate_scenes` method (line 358-374) normalizes them but still returns dicts. We need `SceneConfig.from_dict()` to be used properly.

```python
# Before (lines 358-374):
validated = []
for scene in scenes:
    char = scene.get("character") or scene.get("characters")
    ...
    validated.append(scene)  # returns dict, not SceneConfig

# After:
validated = []
for scene in scenes:
    try:
        cfg = SceneConfig.from_dict(scene)
    except Exception:
        # Fall back to dict normalization for backward compat
        char = scene.get("character") or scene.get("characters")
        ...
        validated.append(scene)
        continue

    # Now use cfg.tts, cfg.characters directly — no .get()
    # But _validate_scenes returns List[Dict] for downstream code compatibility
    # So convert back to dict for now (or update all callers)
    validated.append({
        "id": cfg.id,
        "tts": cfg.tts,
        "script": cfg.script,
        "characters": [c.name for c in cfg.characters],
    })

# Actually, since downstream code (line 166: scene.get("tts")) still expects dicts,
# let's just fix the hasattr and .get calls within the existing dict-based flow.
# The proper SceneConfig migration is a larger change — scope it to a separate task.

# For now, fix the hasattr in _validate_scenes:
```

**Decision:** The SceneConfig validation-after-LLM migration is a larger breaking change (callers expect dicts). Fix the immediate `hasattr` issues now and plan the larger migration separately.

Fix the `hasattr` in `_validate_scenes` for `scene.get('id')`:
```python
# Before (line 366):
f"Scene {scene.get('id', '?')} has {len(char)} characters "

# After — the 'id' field always exists in validated scenes (defaults to 0):
f"Scene {scene.get('id', 0)} has {len(char)} characters "
```

- [ ] **Step 4: Run content_idea_generator tests**

Run: `pytest tests/test_content_idea_generator.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add modules/content/content_idea_generator.py
git commit -m "fix(content_idea_generator): remove hasattr checks on Pydantic fields"
```

---

## Task 4: Fix `content_pipeline.py` — remove `hasattr` for `_runner`

**Files:**
- Modify: `modules/content/content_pipeline.py:664,672,685`

```python
# Before (line 664):
if result and hasattr(pipeline, '_runner') and pipeline._runner is not None:

# After — _runner always exists on VideoPipelineV3 instance:
if result and getattr(pipeline, '_runner', None) is not None:

# Similarly for lines 672, 685
```

Actually `getattr(pipeline, '_runner', None)` is the same as `hasattr + getattr`. But the cleaner fix is to recognize `VideoPipelineV3` always has `_runner`:

```python
# After:
if result and hasattr(pipeline, '_runner') and pipeline._runner is not None:
```
becomes:
```python
if result and pipeline._runner is not None:
```

Since `VideoPipelineV3.__init__` always sets `self._runner`, we can safely remove the `hasattr` check. But to be defensive (in case someone passes a different object), use `getattr`:

```python
_runner = getattr(pipeline, '_runner', None)
if result and _runner is not None:
    media_dir = _runner.media_dir
```

- [ ] **Step 1: Apply fix to 3 locations**

- [ ] **Step 2: Run content_pipeline tests**

Run: `pytest tests/test_content_pipeline.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add modules/content/content_pipeline.py
git commit -m "fix(content_pipeline): use getattr for _runner access instead of hasattr"
```

---

## Task 5: Fix `image_gen.py` — remove `hasattr` for guaranteed field

**Files:**
- Modify: `modules/media/image_gen.py:47`

```python
# Before:
self.model = config.generation.image.model if hasattr(config.generation.image, 'model') else "image-01"

# After:
self.model = getattr(config.generation.image, 'model', "image-01")
```

Or simply (since `model` is a non-optional str with default in `GenerationImage`):
```python
self.model = config.generation.image.model
```

- [ ] **Step 1: Run image_gen tests**

Run: `pytest tests/test_image_config.py -v`
Expected: ALL PASS

- [ ] **Step 2: Commit**

```bash
git add modules/media/image_gen.py
git commit -m "fix(image_gen): remove hasattr check for guaranteed GenerationImage.model field"
```

---

## Task 6: Fix `lipsync.py` — remove `isinstance(config, dict)` backward compat

**Files:**
- Modify: `modules/media/lipsync.py:330-333`

The dict fallback exists because some callers pass raw dicts instead of `GenerationLipsync`. The correct fix is to **enforce Pydantic in the provider signatures** and remove the dict path.

```python
# Before (KieAIInfinitalkProvider.generate, lines 329-333):
if not image_url and config and isinstance(config, dict):
    image_url = config.get("image_url")
if not audio_url and config and isinstance(config, dict):
    audio_url = config.get("audio_url")

# After — remove dict path, require proper config:
if not image_url and config:
    image_url = getattr(config, 'image_url', None)
if not audio_url and config:
    audio_url = getattr(config, 'audio_url', None)
```

Actually, `image_url` and `audio_url` are local vars, not config fields. These are set from `upload_func` or passed directly. The dict fallback is for a case that should never happen with correct usage. Just remove it:

```python
# After: remove the isinstance(config, dict) blocks entirely
# The image_url and audio_url should come from upload_func only
if not image_url or not audio_url:
    logger.warning(
        f"Kie.ai Infinitalk: missing URLs image_url={bool(image_url)} "
        f"audio_url={bool(audio_url)}. Need upload_func."
    )
    return None
```

- [ ] **Step 1: Run lipsync tests**

Run: `pytest tests/test_lipsync.py tests/test_lipsync_config.py -v`
Expected: ALL PASS

- [ ] **Step 2: Commit**

```bash
git add modules/media/lipsync.py
git commit -m "fix(lipsync): remove isinstance(config, dict) backward compat in KieAIInfinitalkProvider"
```

---

## Task 7: Run full test suite

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -50`
Expected: 278+ PASS (same as before; no new regressions). The 5 DB-schema failures and 1 EdgeTTS failure remain (out of scope).

---

## Self-Review Checklist

- [ ] Task 1: `self._api_key` typo fixed — is it in both `generate()` and `get_word_timestamps()`?
  - Yes: `generate()` line 77 and `get_word_timestamps()` line 114 both use `self.api_key`
  - Fix both!
- [ ] Task 2: `SceneProcessor` methods — are return types consistent with callers?
  - `process()` is called from `pipeline_runner.py` with `scene` objects — callers pass `scene` from `ctx.scenario.scenes` (List[SceneConfig]), so the type change is correct
- [ ] Task 3: `content_idea_generator.py` `_validate_scenes` returns dicts — callers at line 166 use `scene.get("tts")` — the dict structure is preserved, no breaking change
- [ ] All `hasattr` patterns reviewed — no remaining unnecessary `hasattr` on Pydantic fields in pipeline modules
