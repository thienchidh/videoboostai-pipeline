"""
modules/pipeline/backoff.py — Backoff and CircuitBreaker utilities.
"""

import time
import threading


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open."""
    pass


class BackoffCalculator:
    """Calculates retry delays for batch operations with configurable growth."""

    def __init__(self, base_seconds: float = 10.0, cap_seconds: float = 3600.0):
        self.base = base_seconds
        self.cap = cap_seconds

    def delay_for_attempt(self, attempt: int) -> float:
        """Return delay in seconds for given attempt number (1-indexed)."""
        if attempt <= 0:
            return 0
        # Exponential growth with cap
        delay = self.base * (10 ** (attempt - 1))
        return min(delay, self.cap)


BATCH_MAX_RETRIES = 3
BATCH_BACKOFF_BASE_SECONDS = 10.0
BATCH_BACKOFF_CAP_SECONDS = 3600.0


class Backoff:
    """
    Exponential backoff with capped delay.

    sleep(attempt) behavior:
        - attempt <= 0: no sleep
        - attempt > 0: sleeps min(base_delay * factor^(attempt-1), max_delay)
    """

    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0, factor: float = 2.0):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.factor = factor

    def sleep(self, attempt: int) -> None:
        if attempt <= 0:
            return
        delay = min(self.base_delay * (self.factor ** (attempt - 1)), self.max_delay)
        time.sleep(delay)


class CircuitBreaker:
    """
    Thread-safe circuit breaker.

    Opens after max_attempts consecutive failures and stays open until
    open_timeout seconds have elapsed (half-open state allows retry).
    """

    def __init__(self, max_attempts: int, open_timeout: float = 60.0):
        self.max_attempts = max_attempts
        self.open_timeout = open_timeout
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.max_attempts:
                self._opened_at = time.time()

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def check(self) -> None:
        with self._lock:
            if self._failures >= self.max_attempts:
                if self._opened_at is not None:
                    elapsed = time.time() - self._opened_at
                    if elapsed < self.open_timeout:
                        raise CircuitOpenError(
                            f"CircuitBreaker open: {self._failures} failures, "
                            f"opened {elapsed:.2f}s ago (timeout={self.open_timeout}s)"
                        )
                # Timeout elapsed — reset and allow request through (half-open)
                self._failures = 0
                self._opened_at = None