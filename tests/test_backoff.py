"""
tests/test_backoff.py — VP-032 backoff + failure queue tests.

Tests:
1. BackoffCalculator.delay_for_attempt() — exponential backoff sequence
2. BackoffCalculator.is_exhausted()
3. BackoffCalculator.next_retry_at() — returns datetime
4. BackoffCalculator.sleep_for_attempt() — no exception
5. BackoffCalculator respects cap
6. BATCH_MAX_RETRIES, BATCH_BACKOFF_BASE_SECONDS, BATCH_BACKOFF_CAP_SECONDS defaults
7. FailedStep DB model fields
8. DB helpers: create_failed_step, update_failed_step, resolve_failed_step, get_pending_failed_steps
"""

import os
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

# ─── BackoffCalculator tests ──────────────────────────────────────────────────

class TestBackoffCalculatorDefaults:
    """Test that env var fallbacks resolve correctly."""

    def test_default_max_retries(self):
        from modules.pipeline.backoff import BATCH_MAX_RETRIES
        assert BATCH_MAX_RETRIES == 3

    def test_default_backoff_base(self):
        from modules.pipeline.backoff import BATCH_BACKOFF_BASE_SECONDS
        assert BATCH_BACKOFF_BASE_SECONDS == 30

    def test_default_backoff_cap(self):
        from modules.pipeline.backoff import BATCH_BACKOFF_CAP_SECONDS
        assert BATCH_BACKOFF_CAP_SECONDS == 1800


class TestBackoffDelaySequence:
    """Test delay_for_attempt() with base=30, cap=1800, factor=10."""

    @pytest.fixture
    def calc(self):
        from modules.pipeline.backoff import BackoffCalculator
        return BackoffCalculator(base_seconds=30, cap_seconds=1800, factor=10)

    def test_attempt_1(self, calc):
        assert calc.delay_for_attempt(1) == 30

    def test_attempt_2(self, calc):
        assert calc.delay_for_attempt(2) == 300   # 30 * 10^1 = 300

    def test_attempt_3(self, calc):
        assert calc.delay_for_attempt(3) == 1800  # 30 * 10^2 = 3000 → capped at 1800

    def test_attempt_4_capped(self, calc):
        assert calc.delay_for_attempt(4) == 1800  # still capped

    def test_attempt_0_defaults_to_base(self, calc):
        assert calc.delay_for_attempt(0) == 30    # base as floor

    def test_negative_attempt(self, calc):
        assert calc.delay_for_attempt(-1) == 30   # base as floor


class TestBackoffExhausted:
    @pytest.fixture
    def calc(self):
        from modules.pipeline.backoff import BackoffCalculator
        return BackoffCalculator(base_seconds=30, cap_seconds=1800, factor=10)

    def test_attempt_3_not_exhausted(self, calc):
        assert calc.is_exhausted(attempt=3, max_retries=3) is False

    def test_attempt_4_is_exhausted(self, calc):
        assert calc.is_exhausted(attempt=4, max_retries=3) is True

    def test_attempt_5_is_exhausted(self, calc):
        assert calc.is_exhausted(attempt=5, max_retries=3) is True

    def test_attempt_2_not_exhausted(self, calc):
        assert calc.is_exhausted(attempt=2, max_retries=3) is False


class TestBackoffNextRetryAt:
    @pytest.fixture
    def calc(self):
        from modules.pipeline.backoff import BackoffCalculator
        return BackoffCalculator(base_seconds=30, cap_seconds=1800, factor=10)

    def test_next_retry_at_is_datetime(self, calc):
        result = calc.next_retry_at(attempt=1)
        assert isinstance(result, datetime)

    def test_next_retry_at_is_utc(self, calc):
        result = calc.next_retry_at(attempt=1)
        assert result.tzinfo is not None  # aware datetime

    def test_next_retry_at_is_in_future(self, calc):
        before = datetime.now(timezone.utc)
        result = calc.next_retry_at(attempt=1)
        after = datetime.now(timezone.utc)
        # delay for attempt 1 = 30s, so result should be ~30s in the future
        assert result > before
        assert result > after
        delta = (result - before).total_seconds()
        assert 29 <= delta <= 31  # within 1s tolerance

    def test_delay_override(self, calc):
        before = datetime.now(timezone.utc)
        result = calc.next_retry_at(attempt=1, delay_seconds=5)
        after = datetime.now(timezone.utc)
        delta = (result - before).total_seconds()
        assert 4 <= delta <= 6


class TestBackoffSleepForAttempt:
    @pytest.fixture
    def calc(self):
        from modules.pipeline.backoff import BackoffCalculator
        return BackoffCalculator(base_seconds=1, cap_seconds=2, factor=2)

    def test_sleep_for_attempt_no_exception(self, calc):
        # Should complete without raising
        calc.sleep_for_attempt(1)  # 1s sleep
        # If we get here, test passes

    def test_sleep_for_attempt_short(self, calc):
        # Using tiny base=1ms would be ideal but simplest is just to verify no crash
        calc.sleep_for_attempt(1)


class TestBackoffCustomConfig:
    """Test custom base/cap/factor values."""

    def test_custom_base_60(self):
        from modules.pipeline.backoff import BackoffCalculator
        calc = BackoffCalculator(base_seconds=60, cap_seconds=3600, factor=5)
        assert calc.delay_for_attempt(1) == 60
        assert calc.delay_for_attempt(2) == 300  # 60 * 5
        assert calc.delay_for_attempt(3) == 1500  # 60 * 25 = 1500

    def test_no_cap(self):
        from modules.pipeline.backoff import BackoffCalculator
        # Very large cap effectively disables it
        calc = BackoffCalculator(base_seconds=10, cap_seconds=1_000_000, factor=2)
        assert calc.delay_for_attempt(3) == 40  # 10 * 4 = 40 (below cap)


# ─── FailedStep DB model tests ────────────────────────────────────────────────

class TestFailedStepModel:
    def test_model_fields(self):
        from db_models import FailedStep
        from sqlalchemy import inspect

        columns = [c.key for c in FailedStep.__table__.columns]
        required = ["id", "run_id", "scene_index", "step_name", "attempts",
                    "last_error", "next_retry_at", "resolved_at", "status",
                    "created_at", "updated_at"]
        for field in required:
            assert field in columns, f"Missing field: {field}"

    def test_status_default(self):
        from db_models import FailedStep
        # SQLAlchemy default
        assert FailedStep.status.default.arg == "pending"

    def test_scene_index_nullable(self):
        from db_models import FailedStep
        col = FailedStep.__table__.columns["scene_index"]
        assert col.nullable is True  # pipeline-level failures have no scene


# ─── DB helper tests (mocked session) ────────────────────────────────────────

class TestFailedStepsDBHelpers:
    """Test DB helper functions with mocked get_session."""

    @pytest.fixture
    def mock_session(self):
        """Return a MagicMock SQLAlchemy session."""
        session = MagicMock()
        return session

    @pytest.fixture
    def mock_models(self):
        from unittest.mock import MagicMock
        import db_models as models
        m = MagicMock()
        m.FailedStep = models.FailedStep
        return m

    def test_create_failed_step(self, mock_session, mock_models):
        """create_failed_step() should add and flush a FailedStep."""
        # Patch get_session to return our mock
        with patch("db.get_session") as mock_gs:
            mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_gs.return_value.__exit__ = MagicMock(return_value=False)

            from db import create_failed_step
            import datetime

            next_retry = datetime.datetime(2026, 4, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
            fid = create_failed_step(
                run_id=42,
                step_name="pipeline",
                scene_index=None,
                last_error="connection refused",
                next_retry_at=next_retry,
            )

            mock_session.add.assert_called_once()
            mock_session.flush.assert_called_once()
            # Check the object passed to add
            added_obj = mock_session.add.call_args[0][0]
            assert added_obj.run_id == 42
            assert added_obj.step_name == "pipeline"
            assert added_obj.attempts == 1
            assert added_obj.last_error == "connection refused"
            assert added_obj.status == "pending"

    def test_update_failed_step(self, mock_session):
        """update_failed_step() should update only provided fields."""
        from db_models import FailedStep
        mock_entry = MagicMock(spec=FailedStep)
        mock_entry.id = 5
        mock_entry.attempts = 1
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_entry

        with patch("db.get_session") as mock_gs:
            mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_gs.return_value.__exit__ = MagicMock(return_value=False)

            from db import update_failed_step
            import datetime

            new_next = datetime.datetime(2026, 4, 15, 12, 5, 0, tzinfo=datetime.timezone.utc)
            update_failed_step(
                failed_step_id=5,
                attempts=2,
                last_error="timeout",
                next_retry_at=new_next,
                status="retrying",
            )

            assert mock_entry.attempts == 2
            assert mock_entry.last_error == "timeout"
            assert mock_entry.next_retry_at == new_next
            assert mock_entry.status == "retrying"

    def test_resolve_failed_step(self, mock_session):
        """resolve_failed_step() should set resolved_at and status='resolved'."""
        from db_models import FailedStep
        mock_entry = MagicMock(spec=FailedStep)
        mock_entry.id = 7
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_entry

        with patch("db.get_session") as mock_gs:
            mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_gs.return_value.__exit__ = MagicMock(return_value=False)

            from db import resolve_failed_step
            resolve_failed_step(7)

            assert mock_entry.resolved_at is not None
            assert mock_entry.status == "resolved"

    def test_get_pending_failed_steps(self, mock_session):
        """get_pending_failed_steps() returns unresolved entries ordered by next_retry_at."""
        from db_models import FailedStep
        mock_entry = MagicMock(spec=FailedStep)
        mock_entry.id = 3
        mock_entry.run_id = 42
        mock_entry.step_name = "pipeline"
        mock_entry.scene_index = None
        mock_entry.attempts = 2
        mock_entry.last_error = "error"
        mock_entry.next_retry_at = None
        mock_entry.resolved_at = None
        mock_entry.status = "exhausted"
        mock_entry.created_at = None
        mock_entry.updated_at = None

        mock_q = MagicMock()
        mock_session.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.filter_by.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.all.return_value = [mock_entry]

        with patch("db.get_session") as mock_gs:
            mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_gs.return_value.__exit__ = MagicMock(return_value=False)

            from db import get_pending_failed_steps
            results = get_pending_failed_steps()

            mock_session.query.assert_called_once()
            assert len(results) == 1
            assert results[0]["id"] == 3
            assert results[0]["status"] == "exhausted"


# ─── Integration: batch_generate uses backoff ──────────────────────────────────

class TestBatchGeneratorBackoffIntegration:
    """Verify BatchGenerator wires backoff correctly."""

    def test_batch_generator_accepts_backoff_params(self):
        from scripts.batch_generate import BatchGenerator

        gen = BatchGenerator(
            max_retries=5,
            backoff_base_seconds=60,
            backoff_cap_seconds=3600,
        )

        assert gen.max_retries == 5
        assert gen.backoff_base_seconds == 60
        assert gen.backoff_cap_seconds == 3600
        assert gen.backoff.base == 60
        assert gen.backoff.cap == 3600

    def test_batch_generator_uses_defaults(self):
        from scripts.batch_generate import BatchGenerator
        from modules.pipeline.backoff import BATCH_MAX_RETRIES, BATCH_BACKOFF_BASE_SECONDS, BATCH_BACKOFF_CAP_SECONDS

        gen = BatchGenerator()

        assert gen.max_retries == BATCH_MAX_RETRIES
        assert gen.backoff_base_seconds == BATCH_BACKOFF_BASE_SECONDS
        assert gen.backoff_cap_seconds == BATCH_BACKOFF_CAP_SECONDS

    def test_backoff_calculator_produces_expected_sequence(self):
        from modules.pipeline.backoff import BackoffCalculator

        # Standard sequence: 30s → 5min → 30min (capped)
        calc = BackoffCalculator(base_seconds=30, cap_seconds=1800, factor=10)

        delays = [calc.delay_for_attempt(i) for i in [1, 2, 3, 4, 5]]
        assert delays == [30, 300, 1800, 1800, 1800]

    def test_failure_queue_helper_creates_entry(self):
        """Verify _create_or_update_failure_queue calls db.create_failed_step."""
        from scripts.batch_generate import BatchGenerator
        from unittest.mock import patch, MagicMock

        gen = BatchGenerator()

        with patch("db.create_failed_step") as mock_create:
            mock_create.return_value = 99
            fid = gen._create_or_update_failure_queue(
                run_id=1,
                step_name="pipeline",
                scene_index=None,
                attempt=1,
                last_error="test error",
                next_retry_at=None,
                status="pending",
            )
            mock_create.assert_called_once()
            assert fid == 99

    def test_failure_queue_helper_updates_entry(self):
        """Verify _create_or_update_failure_queue calls db.update_failed_step when existing_id is given."""
        from scripts.batch_generate import BatchGenerator
        from unittest.mock import patch, MagicMock

        gen = BatchGenerator()

        with patch("db.update_failed_step") as mock_update:
            gen._create_or_update_failure_queue(
                run_id=1,
                step_name="pipeline",
                scene_index=None,
                attempt=2,
                last_error="test error 2",
                next_retry_at=None,
                status="retrying",
                existing_id=5,
            )
            mock_update.assert_called_once()
            call_kwargs = mock_update.call_args[1]
            assert call_kwargs["failed_step_id"] == 5
            assert call_kwargs["attempts"] == 2
            assert call_kwargs["status"] == "retrying"

    def test_resolve_failure_queue_calls_resolve(self):
        """Verify _resolve_failure_queue_entry calls db.resolve_failed_step."""
        from scripts.batch_generate import BatchGenerator
        from unittest.mock import patch

        gen = BatchGenerator()

        with patch("db.resolve_failed_step") as mock_resolve:
            gen._resolve_failure_queue_entry(failed_step_id=7)
            mock_resolve.assert_called_once_with(7)
