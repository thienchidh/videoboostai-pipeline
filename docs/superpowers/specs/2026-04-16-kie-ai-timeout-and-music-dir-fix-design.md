# Spec: Kie.ai Timeout + Music Directory Fix

**Date:** 2026-04-16
**Status:** Approved
**Scope:** Two independent bug fixes in the same pipeline run

---

## Bug 1: Kie.ai Infinitalk Polling Timeout

### Root Cause

1. `GenerationLipsync` Pydantic model defaults `max_wait: 300` (5 min), but YAML config has `max_wait: 900` (15 min). If config is not properly threaded through the provider chain, it falls back to the Pydantic default.
2. No quota balance check during polling loop — if quota is exhausted mid-poll, the task stays in `queuing` state indefinitely and times out at whatever the effective `max_wait` is.

**Symptom observed:** 3 scenes all submit successfully (task_ids returned) but poll times out. Quota confirmed sufficient.

### Fix

#### 1a. `configs/technical/config_technical.yaml`

```yaml
lipsync:
  max_wait: 3600   # was 900 — allow up to 60 minutes for slow Kie.ai jobs
```

#### 1b. `modules/pipeline/models.py`

```python
class GenerationLipsync(BaseModel):
    # ...
    max_wait: int = 900   # was 300 — align Pydantic default with YAML reasonable floor
```

#### 1c. `modules/media/kie_ai_client.py` — Mid-poll balance check

Modify `poll_task()` to call `get_balance()` every ~60 seconds while polling. If balance is 0 or credits are exhausted, return a `LipsyncQuotaError`-compatible error immediately instead of waiting for the full timeout.

```python
def poll_task(self, task_id: str, interval: int = 5,
              max_wait: int = 600) -> Dict[str, Any]:
    start = time.time()
    last_balance_check = 0
    while time.time() - start < max_wait:
        result = self.get_task(task_id)
        # ... existing state checks (success, fail) ...

        # Mid-poll balance check every 60s to detect mid-exhaustion
        if time.time() - start - last_balance_check >= 60:
            balance = self.get_balance()
            if balance.get("success") and self._is_zero_balance(balance):
                return {"success": False, "error": "Quota exhausted mid-poll"}
            last_balance_check = time.time()

        time.sleep(interval)
    return {"success": False, "error": "Polling timeout"}

def _is_zero_balance(self, balance_result: Dict) -> bool:
    data = balance_result.get("data", {})
    # Kie.ai returns {"data": {"credits": 0}} or similar — adapt field name
    credits = data.get("credits", data.get("balance", data.get("quota", -1)))
    return credits == 0
```

#### 1d. `modules/media/lipsync.py` — Propagate quota check error

In `KieAIInfinitalkProvider.generate()`, after calling `poll_task()`, check if the error message indicates mid-poll quota exhaustion and raise `LipsyncQuotaError` accordingly so the pipeline can fallback to static video gracefully.

---

## Bug 2: Music Directory Missing

### Root Cause

`add_background_music()` in `core/video_utils.py` falls back to `PROJECT_ROOT / "music"` when `music_dir` is not set. The folder does not exist at the project root, so the function logs a warning and skips music entirely.

### Fix

#### 2a. Create `music/` folder at project root

```bash
mkdir -p music
```

#### 2b. `configs/technical/config_technical.yaml`

Add optional `music_dir` key so users can configure a custom path:

```yaml
storage:
  output_dir: "output"
  music_dir: null   # null = use PROJECT_ROOT/music; set to override
```

#### 2c. `core/video_utils.py` — `add_background_music()`

Read `music_dir` from config when not explicitly passed:

```python
if not music_file or music_file == "random":
    if music_dir is None:
        # Try config, else fallback to PROJECT_ROOT/music
        music_dir = getattr(config, 'music_dir', None) or str(PROJECT_ROOT / "music")
```

---

## Verification

1. Run `pytest tests/test_lipsync.py tests/test_lipsync_config.py -v` — all pass
2. Verify `GenerationLipsync` fields with: `TechnicalConfig.load().generation.lipsync.max_wait` → expect 3600
3. Test music directory: run a pipeline and confirm `WARNING Music dir not found` is gone from logs
4. Verify mid-poll quota check by running with low-balance account (or mocking `get_balance`)

---

## Files to Modify

| File | Change |
|------|--------|
| `configs/technical/config_technical.yaml` | `lipsync.max_wait: 900→3600`, add `storage.music_dir` |
| `modules/pipeline/models.py` | `GenerationLipsync.max_wait` default: `300→900` |
| `modules/media/kie_ai_client.py` | Add mid-poll `get_balance()` check in `poll_task()` |
| `modules/media/lipsync.py` | Catch mid-poll quota error and raise `LipsyncQuotaError` |
| `core/video_utils.py` | Use config `music_dir` with `PROJECT_ROOT/music` fallback |
| `music/` | Create directory at project root |
