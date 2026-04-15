import pytest, time
from modules.pipeline.backoff import Backoff, CircuitBreaker, CircuitOpenError


def test_backoff_sleep_zero_no_sleep():
    b = Backoff(base_delay=1.0, max_delay=60.0, factor=2)
    start = time.time(); b.sleep(0); elapsed = time.time() - start
    assert elapsed < 0.05


def test_backoff_exponential_delay():
    b = Backoff(base_delay=1.0, max_delay=60.0, factor=2)
    # attempt=1 -> 1.0s, attempt=2 -> 2.0s, attempt=3 -> 4.0s
    expected = {1: (0.9, 1.3), 2: (1.9, 2.3), 3: (3.9, 4.3)}
    for attempt in [1, 2, 3]:
        start = time.time(); b.sleep(attempt); elapsed = time.time() - start
        lo, hi = expected[attempt]
        assert lo < elapsed < hi, f"attempt {attempt}: expected {lo}<{elapsed}<{hi}"


def test_backoff_max_capped():
    b = Backoff(base_delay=1.0, max_delay=3.0, factor=2)
    start = time.time(); b.sleep(10); elapsed = time.time() - start
    assert elapsed < 3.2


def test_circuit_breaker_opens():
    cb = CircuitBreaker(max_attempts=3, open_timeout=60)
    for _ in range(3): cb.record_failure()
    with pytest.raises(CircuitOpenError): cb.check()


def test_circuit_breaker_resets_on_success():
    cb = CircuitBreaker(max_attempts=2, open_timeout=60)
    cb.record_failure(); cb.record_failure(); cb.record_success()
    cb.check()  # no raise


def test_circuit_breaker_half_open_auto_reset():
    cb = CircuitBreaker(max_attempts=2, open_timeout=0.1)
    for _ in range(2): cb.record_failure()
    with pytest.raises(CircuitOpenError): cb.check()
    time.sleep(0.15)
    cb.check()  # should not raise after timeout


def test_circuit_breaker_failure_after_success():
    cb = CircuitBreaker(max_attempts=2, open_timeout=60)
    cb.record_success()
    cb.record_failure()
    cb.record_failure()
    with pytest.raises(CircuitOpenError):
        cb.check()