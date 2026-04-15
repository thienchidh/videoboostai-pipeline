# Pydantic-Only Config System — Design Spec

**Date:** 2026-04-15
**Status:** Draft
**Approach:** Big Bang (all-at-once refactor, single branch, all call sites updated together)

---

## Goal

Remove all dict-like config from the entire codebase. Every config object is a Pydantic model. No `isinstance(config, dict)` checks. No `config: Dict` parameters. No `**config` unpacking into Pydantic constructors. Fail fast with `TypeError` if a dict slips through.

---

## Principles

1. **Fail fast** — If a dict is passed where a Pydantic model is expected, raise `TypeError` immediately. No coercion, no backward-compat guards.
2. **Single Pydantic path** — Every constructor/function has exactly one accepted type for each config parameter.
3. **No roundtrip serialization** — Don't convert Pydantic → dict → Pydantic. Pass Pydantic objects directly.
4. **Entry points own loading** — Scripts (`run_pipeline.py`, `run_scheduler.py`) handle YAML/JSON loading. Internal modules receive already-validated Pydantic objects.

---

## New Pydantic Models

### File: `modules/pipeline/models.py`

#### `PagePlatformConfig`
```python
class PagePlatformConfig(BaseModel):
    page_id: Optional[str] = None
    page_name: Optional[str] = None
    account_name: Optional[str] = None
    account_id: Optional[str] = None
    auto_publish: bool = False
    access_token: Optional[str] = None
```

#### `PageConfig`
```python
class PageConfig(BaseModel):
    facebook: PagePlatformConfig = PagePlatformConfig()
    tiktok: PagePlatformConfig = PagePlatformConfig()
```

#### `ContentSettings`
```python
class ContentSettings(BaseModel):
    auto_schedule: bool = True
    niche_keywords: list[str] = []
    content_angle: str = "tips"
    target_platform: str = "both"
    research_interval_hours: int = 24
    schedule: str = "2h"
    threshold: int = 3
    pending_pool_size: int = 5
```

#### `CheckpointData`
```python
class CheckpointData(BaseModel):
    last_processed_idea_index: int = -1
    source_id: Optional[int] = None
    idea_ids_processed: list[int] = []
    timestamp: Optional[str] = None
```

#### `LipsyncRequest`
```python
class LipsyncRequest(BaseModel):
    left_audio: Optional[str] = None
    right_audio: Optional[str] = None
    config: Optional["GenerationLipsync"] = None
```

#### `CTRData`
```python
class CTRData(BaseModel):
    ctr: float = 0.0
    impressions: int = 0
    clicks: int = 0
```

### File: `modules/pipeline/db_config.py` (NEW)

```python
class DatabaseConnectionConfig(BaseModel):
    host: str
    port: int = 5432
    name: str
    user: str
    password: str
```

---

## ContentPipelineConfig Changes

**Before:**
```python
class ContentPipelineConfig(BaseModel):
    page: Dict[str, Dict[str, Any]]
    content: Dict[str, Any]
```

**After:**
```python
class ContentPipelineConfig(BaseModel):
    page: PageConfig = PageConfig()
    content: ContentSettings = ContentSettings()
```

**Access changes:**
- `self.config.page.get("facebook", {})` → `self.config.page.facebook` (type: `PagePlatformConfig`)
- `self.config.content.get("auto_schedule", True)` → `self.config.content.auto_schedule`

---

## Changes by File

### `modules/content/content_pipeline.py`

1. `__init__` signature:
   - `config: Dict = None` → `config: ContentPipelineConfig = None`
   - Remove `isinstance(config, dict)` guard — raise `TypeError` if not `ContentPipelineConfig`
   - If `config is None`, create `ContentPipelineConfig()` with defaults

2. Replace all `.get()` access:
   - `self.fb_page = self.config.page.get("facebook", {})` → `self.fb_page = self.config.page.facebook`
   - `self.tiktok_account = self.config.page.get("tiktok", {})` → `self.tiktok_account = self.config.page.tiktok`
   - `self.auto_schedule = self.config.content.get("auto_schedule", True)` → `self.auto_schedule = self.config.content.auto_schedule`

3. Remove `model_dump()` roundtrip:
   - `channel_cfg_dict = validated_channel.model_dump()` → pass `validated_channel: ChannelConfig` directly
   - `ContentIdeaGenerator` parameter `channel_config` now typed as `Optional[ChannelConfig]`
   - `llm_config` parameter typed as `Optional[GenerationLLM]` — pass `self.technical_config.generation.llm` directly

4. Checkpoint loading:
   - `json.load(f)` → `CheckpointData.model_validate_json(f.read())`

5. Remove `config_path` param fallback logic — script entry point handles loading

---

### `modules/content/content_idea_generator.py`

1. `__init__` signature:
   - `llm_config: Optional[Dict] = None` → `llm_config: Optional[GenerationLLM] = None`
   - `channel_config: Optional[Dict] = None` → `channel_config: Optional[ChannelConfig] = None`

2. Remove `self._llm_config: Dict = {}` — replace with `self._llm: GenerationLLM`
3. Remove re-validation `ChannelConfig(**channel_config)` — accept `ChannelConfig` directly
4. Remove per-scene `TechnicalConfig.load()` fallback (line 133-139) — config always passed in constructor
5. Replace all `_llm_config.get("key")` with `_llm.key` attribute access

---

### `modules/media/tts.py`

1. Remove dual-path `hasattr(config, 'generation')` / `hasattr(config, 'get')` branching
2. `__init__` signature: `config` → typed as `TechnicalConfig`
3. Single code path: `base_url = config.api_urls.minimax_tts`
4. Remove all `self._config.get(...)` calls — use typed attributes

Same pattern applies to `modules/media/image_gen.py`.

---

### `modules/media/lipsync.py`

1. `generate()` signature: `config: Optional[Dict] = None` → `config: Optional[GenerationLipsync] = None`
2. Remove `isinstance(audio_path, dict)` check (line 210) — `LipsyncRequest` Pydantic model handles it
3. Update abstract method in `core/plugins.py` accordingly

---

### `modules/pipeline/pipeline_runner.py`

1. `db.configure({'host': ..., 'port': ...})` → `db.configure(db_cfg)` where `db_cfg: DatabaseConnectionConfig`
2. `configure_s3({'endpoint': ...})` → `configure_s3(s3)` where `s3: S3Config`
3. `lipsync_provider.generate(..., config={'prompt': ..., 'resolution': ...})` → pass `lipsync_cfg: GenerationLipsync` directly

---

### `db.py` và `db/config.py`

1. New file `modules/pipeline/db_config.py` with `DatabaseConnectionConfig`
2. `db.configure(config: dict = None)` → `db.configure(config: DatabaseConnectionConfig)`
3. Remove `DB_CONFIG = {}` global dict — replace with module-level `db._config: DatabaseConnectionConfig`
4. Remove all `config.get("key")` calls — use typed attribute access
5. `db/config.py` delegates to `db.py` — no separate model needed

---

### `modules/pipeline/parallel_processor.py`

1. Remove `isinstance(chars[0], dict)` checks (lines 162, 241)
2. Always use `SceneCharacter.from_yaml()` — already handles both `str` and `dict` input

---

### `core/base_pipeline.py`

1. `__init__` signature: `config: Dict[str, Any]` → receives `PipelineContext` directly
2. Remove all `.get()` calls on config dict — use `self.ctx.technical`, `self.ctx.channel`, etc.

---

### `scripts/run_pipeline.py`

1. Self-loads all config — `config=None` no longer accepted from CLI
2. Build `ContentPipelineConfig` from channel config + technical config internally
3. Remove `config` parameter from `ContentPipeline` instantiation
4. Keep only `channel_id`, `dry_run`, `skip_lipsync`, `skip_content`, `ideas`, `produce` as CLI args

---

### `scripts/run_scheduler.py`

1. **Fix bug**: `ChannelConfig.model_dump()` was being passed as `config=` to `ContentPipeline` — wrong type
2. After fix: construct proper `ContentPipelineConfig` and pass it

---

### `scripts/video_pipeline_v3.py`

1. Remove `self.config = {"video": {"Title": ...}}` local dict state
2. Expose `self.ctx.scenario.title` directly as a property if needed by external consumers

---

### `modules/content/optimal_post_time.py`

1. `isinstance(ctr_data, dict)` → use `CTRData` model: `CTRData.model_validate(ctr_data)` or pass `CTRData` directly

---

### `db/helpers.py`

1. `isinstance(t.ctr_a, dict)` → use `CTRData` model consistently

---

## Test Updates

| Test File | Change |
|-----------|--------|
| `tests/test_content_pipeline_research.py:72` | `config={}` → `config=ContentPipelineConfig()` |
| All tests passing `config={}` or `config=dict(...)` | Use appropriate Pydantic model |
| `tests/test_content_pipeline.py` | Already uses correct pattern — verify no dict |

---

## Breaking Changes (external API)

- `ContentPipeline.__init__` — `config` param must be `ContentPipelineConfig`, not `Dict` or `None` (creates empty default)
- `ContentIdeaGenerator.__init__` — `llm_config` and `channel_config` must be Pydantic models
- `db.configure()` — `config` param must be `DatabaseConnectionConfig`
- `lipsync.generate()` — `config` param must be `GenerationLipsync`
- `s3_uploader.configure()` — `config` param must be `S3Config`
- `BasePipeline.__init__` — `config` replaced by `PipelineContext`

---

## Scope Summary

| Finding | File | Change |
|---------|------|--------|
| F1 | `core/base_pipeline.py:64` | `config: Dict` → `PipelineContext` |
| F2 | `content_pipeline.py:43` | `config: Dict` → `ContentPipelineConfig` |
| F3 | `content_pipeline.py:69` | Remove `isinstance` guard, fail fast |
| F4 | `content_pipeline.py:119` | Pass `ChannelConfig` directly, remove `model_dump()` |
| F5 | `content_pipeline.py:240` | `json.load` → `CheckpointData.model_validate_json` |
| F6 | `run_scheduler.py:44` | Build proper `ContentPipelineConfig`, not `ChannelConfig.model_dump()` |
| F7 | `tts.py:36-66` | Single `TechnicalConfig` path, no `hasattr` branching |
| F8 | `lipsync.py:210` | `isinstance(audio_path, dict)` → `LipsyncRequest` |
| F9 | `parallel_processor.py:162,241` | Remove `isinstance(chars[0], dict)` |
| F10 | `content_idea_generator.py:31-33` | Dict params → Pydantic params |
| F11 | `content_idea_generator.py:133-139` | Remove per-scene `TechnicalConfig.load()` |
| F12 | `db.py:31` | `config: dict` → `DatabaseConnectionConfig` |
| F13 | `db/config.py:29` | Same as F12 |
| F14 | `db/helpers.py:998-1001` | `isinstance(ctr_a, dict)` → `CTRData` |
| F15 | `optimal_post_time.py:234` | `isinstance(ctr_data, dict)` → `CTRData` |
| F16 | `video_utils.py:39` | Out of scope — not config |
| F17 | `image_gen.py:58` | Out of scope — not config |
| F18 | `content_pipeline.py:71-73` | Covered by ContentPipelineConfig redesign |
| F19 | `run_pipeline.py:67-72` | Entry point self-loads config |
| F20 | `models.py` | New models above |
| F21 | `tests/` | Update dict literals to Pydantic |

---

## Implementation Order

1. Add new Pydantic models to `models.py` (`PageConfig`, `ContentSettings`, `CheckpointData`, `LipsyncRequest`, `CTRData`)
2. Create `modules/pipeline/db_config.py` with `DatabaseConnectionConfig`
3. Update `db.py` and `db/config.py` to use `DatabaseConnectionConfig`
4. Update `ContentPipelineConfig` in `models.py` to use new sub-models
5. Update `ContentIdeaGenerator` to accept Pydantic params
6. Update `ContentPipeline` to use new config types + fail fast
7. Update `run_scheduler.py` to pass correct types
8. Update `run_pipeline.py` entry point
9. Update media providers (`tts.py`, `image_gen.py`, `lipsync.py`)
10. Update `pipeline_runner.py` configure calls
11. Update `core/base_pipeline.py`
12. Update `parallel_processor.py`
13. Update `optimal_post_time.py` and `db/helpers.py` for CTRData
14. Update `video_pipeline_v3.py`
15. Update all tests
16. Run full test suite

---

## Verification

After implementation:
```bash
pytest tests/ -v
```
All tests pass. No `isinstance(..., dict)` in config-related code. No `config: Dict` in function signatures. All config access through typed Pydantic attributes.
