# ContentPipelineConfig Attribute Access Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `ContentPipelineConfig.load().model_dump()` anti-pattern in `content_pipeline.py` — keep Pydantic instance, use direct attribute access instead of dict-style `.get()`.

**Architecture:** Change `self.config` from `dict` (post-`.model_dump()`) to `ContentPipelineConfig` instance. Replace all `self.config.get("x", {})` chains with `self.config.page["x"]` and `self.config.content["x"]` direct attribute access.

**Tech Stack:** Python, Pydantic, Pytest

---

## File Map

| File | Issue | Action |
|------|-------|--------|
| `modules/content/content_pipeline.py` | `ContentPipelineConfig.load().model_dump()` dumps Pydantic to dict; subsequent `.get()` chains bypass type safety | Keep `ContentPipelineConfig` instance; use `.page`, `.content` attributes directly |

---

### Task 1: Refactor `content_pipeline.py` — Keep `ContentPipelineConfig` instance, remove `.model_dump()`

**Files:**
- Modify: `modules/content/content_pipeline.py:62-71`
- Modify: `modules/content/content_pipeline.py:499-500`

- [ ] **Step 1: Read current implementation**

Run: `grep -n "self.config = \|page_cfg\|content_cfg\|fb_page\|tiktok_account\|auto_schedule" modules/content/content_pipeline.py`
Expected:
- Line 62: `self.config = ContentPipelineConfig.load(config_path).model_dump()`
- Lines 66-71: dict-style `.get()` access on `self.config`

- [ ] **Step 2: Replace line 62 — remove `.model_dump()`**

```python
# OLD (line 62):
self.config = ContentPipelineConfig.load(config_path).model_dump()

# NEW:
self.config = ContentPipelineConfig.load(config_path)
```

- [ ] **Step 3: Replace lines 66-71 — use direct attribute access**

```python
# OLD (lines 66-71):
page_cfg = self.config.get("page", {})
content_cfg = self.config.get("content", {})

self.fb_page = page_cfg.get("facebook", {})
self.tiktok_account = page_cfg.get("tiktok", {})
self.auto_schedule = content_cfg.get("auto_schedule", True)

# NEW:
self.fb_page = self.config.page.get("facebook", {})
self.tiktok_account = self.config.page.get("tiktok", {})
self.auto_schedule = self.config.content.get("auto_schedule", True)
```

- [ ] **Step 4: Handle `config_path=None` fallback (line 64)**

When `config_path` is `None`, the current code does `self.config = config or {}` — a raw dict.
Update the fallback to create an empty `ContentPipelineConfig`:

```python
# OLD (line 64):
self.config = config or {}

# NEW:
self.config = config if isinstance(config, ContentPipelineConfig) else ContentPipelineConfig(**config) if config else ContentPipelineConfig(page={}, content={})
```

Or simpler if `config` is always a dict when passed:
```python
# OLD:
self.config = config or {}

# NEW:
self.config = config if config else ContentPipelineConfig(page={}, content={})
```

- [ ] **Step 5: Fix line 499-500 — remove `.model_dump()` in `main()`**

```python
# OLD (line 499-500):
cfg = ContentPipelineConfig.load_or_default(config_path)
config = cfg.model_dump()

# NEW:
cfg = ContentPipelineConfig.load_or_default(config_path)
config = cfg  # Already a ContentPipelineConfig, pass directly
```

- [ ] **Step 6: Update ContentPipeline instantiation (lines 502-507)**

Since `config` is now a `ContentPipelineConfig` (not a dict), the constructor needs updating:

```python
# OLD (lines 502-507):
pipeline = ContentPipeline(
    project_id=1,
    config=config,  # dict passed here
    dry_run=True,
    channel_id="nang_suat_thong_minh"
)

# NEW:
pipeline = ContentPipeline(
    project_id=1,
    config=cfg,  # ContentPipelineConfig instance
    config_path=None,  # config provided directly, no path needed
    dry_run=True,
    channel_id="nang_suat_thong_minh"
)
```

- [ ] **Step 7: Verify yaml import still needed**

Run: `grep -n "yaml" modules/content/content_pipeline.py`
Check if `yaml` is still used after removing raw yaml.load. The only yaml usage is in `ContentPipelineConfig.load()` which uses `yaml.safe_load()` internally — no import change needed in this file.

- [ ] **Step 8: Run tests**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add modules/content/content_pipeline.py
git commit -m "refactor: keep ContentPipelineConfig instance, use direct attribute access"
```

---

## Self-Review Checklist

- [ ] `self.config` is now a `ContentPipelineConfig` instance (not a `dict`)
- [ ] All `self.config.get("page", {})` → `self.config.page.get(...)`
- [ ] All `self.config.get("content", {})` → `self.config.content.get(...)`
- [ ] `main()` passes `ContentPipelineConfig` instance directly (not dumped dict)
- [ ] All tests pass
- [ ] No placeholder content