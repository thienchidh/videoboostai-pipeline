"""
modules/pipeline/backoff.py — Exponential backoff calculator for batch_generate.py retries (VP-032).

Formula:
    delay = min(BACKOFF_BASE * (BACKOFF_FACTOR ^ (attempt - 1)), BACKOFF_CAP)

Defaults:
    BASE  = 30s
    CAP   = 1800s (30min)
    FACTOR = 10x

Sequence: 30s → 5min → 30min (capped)

Usage:
    from modules.pipeline.backoff import BackoffCalculator

    calc = BackoffCalculator(base_seconds=30, cap_seconds=1800, factor=10)
    delay = calc.delay_for_attempt(1)   # 30
    delay = calc.delay_for_attempt(2)   # 300
    delay = calc.delay_for_attempt(3)   # 1800 (capped)
    next_time = calc.next_retry_at(attempt=2, delay_seconds=300)  # datetime
    is_exhausted = calc.is_exhausted(attempt=3, max_retries=3)   # True
"""

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional


# ─── Configuration from env / defaults ───────────────────────────────────────

def _env_int(key: str, default: int) -> int:
    try:
        val = os.getenv(key)
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


BATCH_MAX_RETRIES = _env_int("BATCH_MAX_RETRIES", 3)
BATCH_BACKOFF_BASE_SECONDS = _env_int("BATCH_BACKOFF_BASE_SECONDS", 30)
BATCH_BACKOFF_CAP_SECONDS = _env_int("BATCH_BACKOFF_CAP_SECONDS", 1800)
# factor > 1 means each attempt waits longer. factor=10 gives: 30s → 300s → 1800s
BATCH_BACKOFF_FACTOR = float(os.getenv("BATCH_BACKOFF_FACTOR", "10"))


class BackoffCalculator:
    """
    Exponential backoff calculator.

    delay(attempt) = min(base * (factor ^ (attempt - 1)), cap)
    """

    def __init__(self, base_seconds: int = BATCH_BACKOFF_BASE_SECONDS,
                 cap_seconds: int = BATCH_BACKOFF_CAP_SECONDS,
                 factor: float = BATCH_BACKOFF_FACTOR):
        self.base = base_seconds
        self.cap = cap_seconds
        self.factor = factor

    def delay_for_attempt(self, attempt: int) -> int:
        """
        Compute sleep delay (seconds) for a given 1-based attempt number.

        Examples (base=30, cap=1800, factor=10):
            attempt=1 → 30s
            attempt=2 → 300s
            attempt=3 → 1800s (capped)
        """
        if attempt <= 0:
            return self.base
        delay = self.base * (self.factor ** (attempt - 1))
        return int(min(delay, self.cap))

    def next_retry_at(self, attempt: int, delay_seconds: int = None) -> datetime:
        """
        Return the datetime after which the next retry should be attempted.

        Args:
            attempt: 1-based attempt number for the NEXT retry (so attempt=2 means
                     we're computing the schedule after 2 failures, before the 3rd try)
            delay_seconds: optional override delay; if None, computed from attempt
        """
        if delay_seconds is None:
            delay_seconds = self.delay_for_attempt(attempt)
        return datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)

    def is_exhausted(self, attempt: int, max_retries: int = BATCH_MAX_RETRIES) -> bool:
        """Return True when all retry attempts have been used up."""
        return attempt > max_retries

    def sleep_for_attempt(self, attempt: int) -> None:
        """Sleep for the appropriate backoff delay for the given attempt."""
        delay = self.delay_for_attempt(attempt)
        if delay > 0:
            time.sleep(delay)
