# Config Attribute Access — Remaining Items Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace remaining raw YAML/JSON file I/O and dict-style config access with proper typed config model loaders.

**Architecture:** Replace direct `yaml.safe_load()` / `json.load()` calls with existing Pydantic model `.load()` classmethods. Remove triple-nested `.get()` chains in favor of typed attribute access.

**Tech Stack:** Python, Pydantic, Pytest

---

## File Map

| File | Issue | Action |
|------|-------|--------|
| `utils/embedding.py` | Raw `yaml.safe_load()` + triple-nested `.get()` chain | Use `TechnicalConfig.load()` |
| `modules/content/content_pipeline.py` | Raw `json.load()` bypassing `ContentPipelineConfig.load()` | Use `ContentPipelineConfig.load()` |
| `modules/media/s3_uploader.py` | Raw dict config access with hardcoded region fallback | Add `S3Config` validation layer |

---

### Task 1: Fix `utils/embedding.py` — Replace raw YAML + triple `.get()` with `TechnicalConfig.load()`

**Files:**
- Modify: `utils/embedding.py:40-42`

- [ ] **Step 1: Read the current implementation**

Run: `grep -n "tech_cfg_path\|yaml.safe_load\|cfg.get\|api_key" utils/embedding.py`
Expected: Line 40-42 has raw YAML load + triple-nested API key access

- [ ] **Step 2: Replace raw YAML load with TechnicalConfig.load()**

```python
# OLD (lines 40-42):
with open(tech_cfg_path, encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
...
api_key = cfg.get("api", {}).get("keys", {}).get("minimax", "")

# NEW:
from modules.pipeline.models import TechnicalConfig
cfg = TechnicalConfig.load()
api_key = cfg.api_keys.minimax
```

- [ ] **Step 3: Remove yaml import if no longer needed**

Run: `grep -n "yaml" utils/embedding.py`
If only usage was line 40-42, remove the import.

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -v -k embedding`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add utils/embedding.py
git commit -m "refactor: use TechnicalConfig.load() instead of raw yaml + nested .get()"
```

---

### Task 2: Fix `content_pipeline.py` — Replace raw `json.load()` with `ContentPipelineConfig.load()`

**Files:**
- Modify: `modules/content/content_pipeline.py`

- [ ] **Step 1: Find the ContentPipelineConfig model**

Run: `grep -n "class ContentPipelineConfig" modules/pipeline/models.py`
Expected: Line 337

- [ ] **Step 2: Read the ContentPipelineConfig.load() method**

Run: `grep -A 20 "class ContentPipelineConfig" modules/pipeline/models.py`
Verify it has a `.load(path)` classmethod.

- [ ] **Step 3: Replace raw json.load() with ContentPipelineConfig.load()**

Line 62 currently:
```python
with open(config_path) as f:
    self.config = json.load(f)
```

Replace with:
```python
self.config = ContentPipelineConfig.load(config_path)
```

- [ ] **Step 4: Add import**

```python
from modules.pipeline.models import ContentPipelineConfig
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add modules/content/content_pipeline.py
git commit -m "refactor: use ContentPipelineConfig.load() instead of raw json.load()"
```

---

### Task 3: Fix `s3_uploader.py` — Add S3Config validation layer

**Files:**
- Modify: `modules/media/s3_uploader.py`

- [ ] **Step 1: Read s3_uploader.py configure() method**

Run: `grep -n "def configure\|config: dict\|config.get" modules/media/s3_uploader.py`
Expected: Lines 20-35 contain raw dict access

- [ ] **Step 2: Check if S3Config model exists**

Run: `grep -n "class S3Config" modules/pipeline/models.py`
Expected: Found

- [ ] **Step 3: Replace raw dict access with S3Config validation**

```python
# OLD:
def configure(config: dict) -> None:
    self._enabled = config.get("enabled", False)
    self._bucket = config.get("bucket")
    self._endpoint = config.get("endpoint")
    self._region = config.get("region", "us-east-1")

# NEW:
def configure(self, config: dict) -> None:
    from modules.pipeline.models import S3Config
    validated = S3Config(**config)
    self._enabled = validated.enabled
    self._bucket = validated.bucket
    self._endpoint = validated.endpoint
    self._region = validated.region
```

Note: `S3Config` is likely already imported in `models.py`. Verify it has `enabled`, `bucket`, `endpoint`, `region` fields.

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add modules/media/s3_uploader.py
git commit -m "refactor: use S3Config model for validated config access"
```

---

## Self-Review Checklist

- [ ] `utils/embedding.py` uses `TechnicalConfig.load()` instead of raw YAML + nested `.get()`
- [ ] `content_pipeline.py` uses `ContentPipelineConfig.load()` instead of raw `json.load()`
- [ ] `s3_uploader.py` uses `S3Config` Pydantic model for validated config
- [ ] All tests pass
- [ ] No placeholder content
