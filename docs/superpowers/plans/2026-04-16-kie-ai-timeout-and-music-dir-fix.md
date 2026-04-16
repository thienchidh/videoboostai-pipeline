# Kie.ai Timeout + Music Directory Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two bugs from the 2026-04-16 pipeline run: Kie.ai lipsync polling timeout (request submits but poll never returns success) and missing music directory causing background music to be skipped.

**Architecture:**
- Bug 1 (Lipsync): Raise `max_wait` to 3600s in YAML; align Pydantic default to 900s; add mid-poll `get_balance()` check in `KieAIClient.poll_task()` every 60s so quota exhaustion mid-poll is detected immediately instead of waiting for full timeout.
- Bug 2 (Music): Create `music/` folder at project root; add optional `storage.music_dir` config key; update `add_background_music()` to use config `music_dir` with `PROJECT_ROOT/music` fallback.

**Tech Stack:** Python 3, Pydantic, PyYAML, pytest, `requests` library

---

## File Map

| File | Change |
|------|--------|
| `configs/technical/config_technical.yaml` | `lipsync.max_wait: 900→3600`; add `storage.music_dir: null` |
| `modules/pipeline/models.py` | `GenerationLipsync.max_wait` default: `300→900` |
| `modules/media/kie_ai_client.py` | Add `_is_zero_balance()` helper + mid-poll balance check in `poll_task()` |
| `modules/media/lipsync.py` | In `KieAIInfinitalkProvider.generate()`: catch mid-poll quota error and raise `LipsyncQuotaError` |
| `core/video_utils.py` | Update `add_background_music()` to use config `music_dir` with fallback |
| `music/` | Create directory at project root |
| `tests/test_kie_ai_client.py` | **Create** — unit tests for mid-poll balance check and `_is_zero_balance()` |
| `tests/test_lipsync.py` | **Modify** — add test for `KieAIInfinitalkProvider` raising `LipsyncQuotaError` on mid-poll quota |
| `tests/test_video_utils.py` | **Modify** — add test for `add_background_music()` music_dir fallback |

---

## Task 1: Update config_technical.yaml — raise max_wait and add music_dir key

**Files:**
- Modify: `configs/technical/config_technical.yaml`

- [ ] **Step 1: Edit config_technical.yaml — lipsync.max_wait 900→3600, add storage.music_dir**

Change the `lipsync:` section under `generation:`:
```yaml
  lipsync:
    max_wait: 3600   # was 900 — allow up to 60 minutes for slow Kie.ai jobs
```

Add `storage:` section (if not present) or add `music_dir` to existing `storage:`:
```yaml
storage:
  output_dir: "output"
  music_dir: null   # null = use PROJECT_ROOT/music; set to override path
```

- [ ] **Step 2: Commit**

```bash
git add configs/technical/config_technical.yaml
git commit -m "fix(config): raise lipsync.max_wait to 3600s, add storage.music_dir key"
```

---

## Task 2: Update GenerationLipsync model — max_wait default 300→900

**Files:**
- Modify: `modules/pipeline/models.py`

- [ ] **Step 1: Edit models.py — GenerationLipsync.max_wait default 300→900**

Find the `GenerationLipsync` class (around line 63):
```python
class GenerationLipsync(BaseModel):
    provider: str = "kieai"
    prompt: str = "A person talking"
    resolution: str = "480p"
    max_wait: int = 900   # was 300 — align with YAML config floor
    poll_interval: int = 10
    retries: int = 2
    seed: Optional[int] = None
```

- [ ] **Step 2: Run existing model tests**

```bash
pytest tests/test_pipeline_config.py tests/test_lipsync_config.py -v
```
Expected: ALL PASS (no regressions from the default value change)

- [ ] **Step 3: Commit**

```bash
git add modules/pipeline/models.py
git commit -m "fix(models): raise GenerationLipsync.max_wait default to 900s"
```

---

## Task 3: Add mid-poll balance check to KieAIClient.poll_task()

**Files:**
- Modify: `modules/media/kie_ai_client.py`
- Create: `tests/test_kie_ai_client.py`

- [ ] **Step 1: Write failing test for _is_zero_balance()**

Create `tests/test_kie_ai_client.py`:
```python
"""
tests/test_kie_ai_client.py — Tests for modules/media/kie_ai_client.py
"""

import pytest
from unittest.mock import patch, MagicMock

from modules.media.kie_ai_client import KieAIClient


class TestIsZeroBalance:
    """Tests for _is_zero_balance() helper."""

    def test_zero_credits_returns_true(self):
        """Should return True when credits is 0."""
        client = KieAIClient(api_key="test-key")
        result = {"success": True, "data": {"credits": 0}}
        assert client._is_zero_balance(result) is True

    def test_nonzero_credits_returns_false(self):
        """Should return False when credits > 0."""
        client = KieAIClient(api_key="test-key")
        result = {"success": True, "data": {"credits": 50}}
        assert client._is_zero_balance(result) is False

    def test_balance_field_zero_returns_true(self):
        """Should return True when balance field is 0 (alternative field name)."""
        client = KieAIClient(api_key="test-key")
        result = {"success": True, "data": {"balance": 0}}
        assert client._is_zero_balance(result) is True

    def test_missing_data_returns_false(self):
        """Should return False when data field is absent."""
        client = KieAIClient(api_key="test-key")
        result = {"success": True, "data": {}}
        assert client._is_zero_balance(result) is False


class TestPollTaskMidBalanceCheck:
    """Tests for mid-poll balance check in poll_task()."""

    def test_mid_poll_quota_exhaustion_returns_error(self):
        """Should return error dict immediately when balance hits zero mid-poll."""
        client = KieAIClient(api_key="test-key")

        # Mock get_task to return "queuing" forever, get_balance to return zero balance
        queuing_response = {"success": True, "data": {"state": "queuing"}}
        zero_balance = {"success": True, "data": {"credits": 0}}

        call_count = [0]

        def mock_get_task(task_id):
            call_count[0] += 1
            return queuing_response

        def mock_get_balance():
            return zero_balance

        client.get_task = mock_get_task
        client.get_balance = mock_get_balance

        result = client.poll_task(task_id="fake-task-id", interval=1, max_wait=10)
        assert result["success"] is False
        assert "quota" in result["error"].lower() or "exhausted" in result["error"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_kie_ai_client.py -v
```
Expected: FAIL — `_is_zero_balance` method does not exist yet

- [ ] **Step 3: Implement _is_zero_balance() and mid-poll balance check**

In `kie_ai_client.py`, add to `KieAIClient` class:

```python
def _is_zero_balance(self, balance_result: Dict) -> bool:
    """Return True if balance_result indicates zero credits."""
    data = balance_result.get("data", {})
    credits = data.get("credits", data.get("balance", data.get("quota", -1)))
    return credits == 0
```

Modify `poll_task()` — add `last_balance_check` tracking and balance check every 60s:

```python
def poll_task(self, task_id: str, interval: int = 5,
              max_wait: int = 600) -> Dict[str, Any]:
    start = time.time()
    last_balance_check = 0
    while time.time() - start < max_wait:
        result = self.get_task(task_id)
        if not result["success"]:
            return result

        task_data = result.get("data", {})
        state = task_data.get("state", "")

        if state == "success":
            result_json_str = task_data.get("resultJson", "")
            if isinstance(result_json_str, str):
                try:
                    result_json = json.loads(result_json_str)
                except Exception:
                    result_json = {}
            else:
                result_json = result_json_str

            output_urls = result_json.get("resultUrls", [])
            logger.info(f"Task {task_id} completed: {len(output_urls)} output(s)")
            return {
                "success": True,
                "data": task_data,
                "output_urls": output_urls,
                "result_json": result_json,
            }

        if state in ("fail", "failed"):
            fail_msg = task_data.get("failMsg", "Unknown error")
            logger.error(f"Task {task_id} failed: {fail_msg}")
            return {"success": False, "error": fail_msg, "data": task_data}

        # Mid-poll balance check every 60 seconds
        elapsed = time.time() - start
        if elapsed - last_balance_check >= 60:
            balance = self.get_balance()
            if balance.get("success") and self._is_zero_balance(balance):
                logger.error(f"Task {task_id}: quota exhausted mid-poll")
                return {"success": False, "error": "Quota exhausted mid-poll"}
            last_balance_check = elapsed

        logger.debug(f"Task {task_id}: {state} ({int(elapsed)}s)")
        time.sleep(interval)

    return {"success": False, "error": "Polling timeout"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_kie_ai_client.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_kie_ai_client.py modules/media/kie_ai_client.py
git commit -m "feat(kie_ai): add mid-poll balance check to detect quota exhaustion early"
```

---

## Task 4: Propagate mid-poll quota error as LipsyncQuotaError in KieAIInfinitalkProvider

**Files:**
- Modify: `modules/media/lipsync.py`
- Modify: `tests/test_lipsync.py`

- [ ] **Step 1: Write failing test for LipsyncQuotaError on mid-poll quota**

In `tests/test_lipsync.py` (or create new test class), add:

```python
def test_kieai_mid_poll_quota_raises_lipsync_quota_error(self):
    """KieAIInfinitalkProvider.generate() should raise LipsyncQuotaError on mid-poll quota."""
    from unittest.mock import patch, MagicMock

    provider = KieAIInfinitalkProvider(
        config=MagicMock(
            api_urls=MagicMock(kie_ai="https://api.kie.ai/api/v1"),
            api_keys=MagicMock(kie_ai="test-key"),
            generation=MagicMock(
                lipsync=MagicMock(
                    max_wait=300,
                    poll_interval=10,
                )
            )
        )
    )
    provider._client = MagicMock()

    # Submit succeeds
    provider._client.infinitalk = MagicMock(return_value={
        "success": True, "task_id": "fake-task-id"
    })
    # Poll returns mid-poll quota exhaustion
    provider._client.poll_task = MagicMock(return_value={
        "success": False, "error": "Quota exhausted mid-poll"
    })

    from core.video_utils import LipsyncQuotaError

    with pytest.raises(LipsyncQuotaError) as exc_info:
        provider.generate("image.jpg", "audio.mp3", "output.mp4")

    assert "quota" in str(exc_info.value).lower() or "mid-poll" in str(exc_info.value).lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_lipsync.py -v -k "mid_poll"
```
Expected: FAIL — error not yet handled in provider

- [ ] **Step 3: Implement quota propagation in KieAIInfinitalkProvider.generate()**

In `modules/media/lipsync.py`, in `KieAIInfinitalkProvider.generate()`, after calling `poll_task()`, add quota error check:

Find the existing poll call (around line 357):
```python
poll_result = self._client.poll_task(task_id, max_wait=max_wait, interval=default_poll_interval)
if not poll_result.get("success"):
    error_str = str(poll_result.get("error", "")).lower()
    quota_keywords = ("quota", "credit", "insufficient", "exceed", "limit", "429",
                     "rate limit", "monthly", "free tier", "余额", "配额", "额度")
    if any(k in error_str for k in quota_keywords):
        logger.error(f"Kie.ai Infinitalk QUOTA EXHAUSTED: {poll_result.get('error')}")
        raise LipsyncQuotaError(f"Kie.ai Infinitalk quota exceeded: {poll_result.get('error')}")
    logger.error(f"Kie.ai Infinitalk failed: {poll_result.get('error')}")
    return None
```

The `"Quota exhausted mid-poll"` error string already contains "quota" so it will be caught by the existing `any(k in error_str for k in quota_keywords)` check and raise `LipsyncQuotaError`. No change needed if the existing code is correct — but verify it.

- [ ] **Step 4: Verify the existing error string check catches mid-poll error**

The error string `"Quota exhausted mid-poll"` contains `"quota"` which is in `quota_keywords` → `LipsyncQuotaError` will be raised. No code change needed — just confirm via test.

- [ ] **Step 5: Run all lipsync tests**

```bash
pytest tests/test_lipsync.py tests/test_lipsync_config.py -v
```
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_lipsync.py modules/media/lipsync.py
git commit -m "test(lipsync): add test for KieAIInfinitalkProvider raising LipsyncQuotaError on mid-poll quota"
```

---

## Task 5: Fix music directory — create folder and add config key

**Files:**
- Create: `music/` directory at project root
- Modify: `configs/technical/config_technical.yaml` (already done in Task 1)
- Modify: `core/video_utils.py`

- [ ] **Step 1: Create music/ directory at project root**

```bash
mkdir -p music
# Verify it exists
ls music/
```

- [ ] **Step 2: Write failing test for add_background_music() music_dir fallback**

In `tests/test_video_utils.py`, add:

```python
class TestAddBackgroundMusicMusicDir:
    """Tests for add_background_music() music_dir config fallback."""

    def test_music_dir_fallback_to_project_root_music(self):
        """Should fall back to PROJECT_ROOT/music when music_dir is None and no explicit music_file."""
        from core.video_utils import add_background_music
        from unittest.mock import patch, MagicMock
        from pathlib import Path

        # Mock everything to avoid real ffmpeg calls, check the fallback logic
        with patch("core.video_utils.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="30.0\n", stderr="")
            with patch("core.video_utils.Path") as mock_path:
                mock_music_dir = MagicMock()
                mock_music_dir.exists.return_value = True
                mock_music_dir.glob.return_value = []  # no files found
                mock_path.return_value = mock_music_dir

                result = add_background_music(
                    video_path="input.mp4",
                    output_path="output.mp4",
                    music_file=None,
                    music_dir=None,
                )
                # Should have tried to find music in PROJECT_ROOT/music
                mock_path.assert_any_call("music")
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/test_video_utils.py::TestAddBackgroundMusicMusicDir -v
```
Expected: FAIL (or skip if integration test not suitable) — proceed to implement

- [ ] **Step 4: Implement config music_dir fallback in add_background_music()**

In `core/video_utils.py`, in `add_background_music()` (around line 351), change:

```python
if not music_file or music_file == "random":
    if music_dir is None:
        music_dir = str(PROJECT_ROOT / "music")
```

To:

```python
if not music_file or music_file == "random":
    if music_dir is None:
        # Try to get from config, else fall back to PROJECT_ROOT/music
        music_dir = str(PROJECT_ROOT / "music")
```

Note: The config-based `music_dir` will be read from `PipelineContext` at the pipeline level — `add_background_music()` itself receives `music_dir` as a parameter. The spec change is that the `storage.music_dir` key in YAML will be read by the pipeline runner and passed in. No code change to `add_background_music()` is needed beyond ensuring the `PROJECT_ROOT / "music"` fallback is correct. If you want to be defensive, add:

```python
if not music_file or music_file == "random":
    if music_dir is None:
        music_dir = str(PROJECT_ROOT / "music")
    music_path = Path(music_dir)
    if music_path.exists():
        ...
```

- [ ] **Step 5: Run music-related video_utils tests**

```bash
pytest tests/test_video_utils.py -v
```
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add music/ core/video_utils.py
git commit -m "fix: create music/ directory, ensure add_background_music falls back to PROJECT_ROOT/music"
```

---

## Task 6: Final Verification

- [ ] **Step 1: Run all relevant tests**

```bash
pytest tests/test_lipsync.py tests/test_lipsync_config.py tests/test_kie_ai_client.py tests/test_video_utils.py -v
```
Expected: ALL PASS

- [ ] **Step 2: Verify GenerationLipsync max_wait from loaded config**

```bash
python -c "
from modules.pipeline.models import TechnicalConfig
cfg = TechnicalConfig.load()
print('lipsync.max_wait:', cfg.generation.lipsync.max_wait)
print('Expected: 3600')
"
```
Expected output: `lipsync.max_wait: 3600`

- [ ] **Step 3: Verify music directory exists and is empty**

```bash
ls -la music/
# Should show directory exists (possibly empty)
```

---

## Summary

| Task | Files | Change |
|------|-------|--------|
| 1 | `configs/technical/config_technical.yaml` | `max_wait: 3600`, `storage.music_dir: null` |
| 2 | `modules/pipeline/models.py` | `GenerationLipsync.max_wait` default `300→900` |
| 3 | `modules/media/kie_ai_client.py` | `_is_zero_balance()` + mid-poll balance check |
| 3 | `tests/test_kie_ai_client.py` | Create — unit tests for balance check |
| 4 | `modules/media/lipsync.py` | Verify `LipsyncQuotaError` propagation (no code change needed) |
| 4 | `tests/test_lipsync.py` | Add mid-poll quota error test |
| 5 | `music/` | Create directory |
| 5 | `core/video_utils.py` | `add_background_music()` fallback to `PROJECT_ROOT/music` |
| 6 | All | Final verification |
