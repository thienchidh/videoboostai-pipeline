"""
core/retry.py — Centralized retry configuration for API calls.
"""

import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception, before_sleep_log
import requests

logger = logging.getLogger(__name__)


def is_retryable(exc):
    """Return True for retryable errors: 5xx, connection errors."""
    if hasattr(exc, 'response') and exc.response is not None:
        status = exc.response.status_code
        if status >= 500:
            return True  # server error
        if status == 429:
            return False  # fail fast on quota/rate-limit
        return False  # 4xx client errors
    if isinstance(exc, requests.exceptions.RequestException):
        return True  # connection timeout, DNS failure, connection refused, etc.
    return False


def retry_on_500():
    """Decorator: retry up to 5 times with exponential backoff (2-120s).

    Retries on: 5xx errors, connection errors.
    """
    return retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=120),
        retry=retry_if_exception(is_retryable),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
