# API Retry Design

## Overview

Add automatic retry with exponential backoff for all API calls in the pipeline to handle transient 5xx errors, connection failures, and rate limits.

## Strategy

**Library:** `tenacity` (already in requirements.txt)

**Configuration:**
- Max attempts: 5
- Backoff: exponential, multiplier=2, min=2s, max=120s
- Retry conditions: 5xx errors, connection errors (timeout, DNS, refused), 429 rate limit

**Quota errors (LipsyncQuotaError, quota keywords) are NOT retried** — they trigger fallback logic.

## Implementation

### New File: `core/retry.py`

```python
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
import requests

logger = logging.getLogger(__name__)

def is_retryable(exc):
    """Retry on 5xx, connection errors, rate limit (429), quota errors"""
    if isinstance(exc, requests.exceptions.RequestException):
        return True  # connection timeout, DNS, etc.
    if hasattr(exc, 'response'):
        status = exc.response.status_code
        if status == 429:
            return True  # rate limit
        if status >= 500:
            return True  # server error
    return False

def retry_on_500():
    return retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=120),
        retry=retry_if_exception(is_retryable),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
```

### Files to Modify

Apply `@retry_on_500()` decorator to API call methods in:

| File | Provider |
|------|----------|
| `modules/media/tts.py` | MiniMax TTS, Edge TTS `_call_api()` |
| `modules/media/image_gen.py` | MiniMax, WaveSpeed, Kie Z Image |
| `modules/media/lipsync.py` | WaveSpeed, Kie Infinitalk |
| `modules/media/music_gen.py` | MiniMax Music |
| `modules/llm/minimax.py` | MiniMax LLM `_send_request()` |

### Pattern for Providers

Wrap actual HTTP call in a private method with decorator:

```python
@retry_on_500()
def _call_api(self, url, headers, payload):
    resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
    resp.raise_for_status()
    return resp
```

Existing polling loops (Kie, WaveSpeed) can use session's request directly — retry handles transient failures on each poll attempt.

### What is NOT Retried

- `LipsyncQuotaError` — triggers fallback to static video
- Quota keyword errors (credit, insufficient, etc.) — handled by existing logic
- Config errors, validation errors

## Testing

- Unit test `is_retryable()` logic
- Integration test: verify retry on mock 500 response
- Verify quota errors bypass retry
