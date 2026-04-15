"""
tests/test_optimal_post_time.py — Tests for OptimalPostTimeEngine + scheduled_posts DB.

Covers:
- compute_best_hour() with mocked CTR data
- schedule_upload() creates correct DB record
- Fallback to default hour when not enough data
- scheduled_posts table population
"""

import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Mock DB setup ──────────────────────────────────────────────────────────────
# Patch DB configure before importing anything that calls it


class MockSession:
    """Fake SQLAlchemy session for isolated testing."""

    def __init__(self):
        self._committed = False
        self._data = {}  # model_class -> [list of objects]

    def add(self, obj):
        key = type(obj)
        if key not in self._data:
            self._data[key] = []
        self._data[key].append(obj)

    def flush(self):
        pass

    def commit(self):
        self._committed = True

    def rollback(self):
        pass

    def close(self):
        pass

    def query(self, model_cls):
        return MockQuery(self._data, model_cls)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockQuery:
    def __init__(self, data, model_cls):
        self._data = data
        self._model_cls = model_cls
        self._filters = []

    def filter(self, *args, **kwargs):
        return self

    def filter_by(self, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def order_by(self, *args):
        return self

    def limit(self, n):
        return self

    def first(self):
        key = self._model_cls
        if key not in self._data or not self._data[key]:
            return None
        return self._data[key][0]

    def all(self):
        key = self._model_cls
        return self._data.get(key, [])


class TestOptimalPostTimeEngine(unittest.TestCase):

    def setUp(self):
        self.mock_session = MockSession()
        self.patch_session = patch("modules.content.optimal_post_time.get_session")
        self.mock_get_session = self.patch_session.start()
        self.mock_get_session.return_value = self.mock_session

    def tearDown(self):
        self.patch_session.stop()

    # ── compute_best_hour() tests ─────────────────────────────────────────────

    def test_compute_best_hour_falls_back_when_no_data(self):
        """When ab_caption_tests table is empty, should return default hour."""
        from modules.content.optimal_post_time import OptimalPostTimeEngine

        # No rows returned
        with patch.object(OptimalPostTimeEngine, "_get_hourly_ctr", return_value={}):
            engine = OptimalPostTimeEngine(min_posts=3, min_ctr_threshold=0.01)
            hour = engine.compute_best_hour("facebook")
            self.assertEqual(hour, 20)  # FB default

    def test_compute_best_hour_falls_back_when_insufficient_posts(self):
        """When no hour has ≥ min_posts entries, fall back to default."""
        from modules.content.optimal_post_time import OptimalPostTimeEngine

        hourly_ctr = {
            10: {"avg_ctr": 0.05, "count": 1},  # too few
            14: {"avg_ctr": 0.07, "count": 2},  # too few
            20: {"avg_ctr": 0.02, "count": 5},  # meets min_posts but below threshold
        }
        with patch.object(OptimalPostTimeEngine, "_get_hourly_ctr", return_value=hourly_ctr):
            engine = OptimalPostTimeEngine(min_posts=3, min_ctr_threshold=0.03)
            hour = engine.compute_best_hour("facebook")
            self.assertEqual(hour, 20)  # only one meeting min_posts but CTR too low

    def test_compute_best_hour_returns_highest_ctr_hour(self):
        """Should return the hour with the highest average CTR."""
        from modules.content.optimal_post_time import OptimalPostTimeEngine

        hourly_ctr = {
            9:  {"avg_ctr": 0.010, "count": 3},
            12: {"avg_ctr": 0.025, "count": 5},
            15: {"avg_ctr": 0.018, "count": 4},
            20: {"avg_ctr": 0.041, "count": 6},  # highest CTR
            22: {"avg_ctr": 0.030, "count": 3},
        }
        with patch.object(OptimalPostTimeEngine, "_get_hourly_ctr", return_value=hourly_ctr):
            engine = OptimalPostTimeEngine(min_posts=3, min_ctr_threshold=0.01)
            hour = engine.compute_best_hour("tiktok")
            self.assertEqual(hour, 20)

    def test_compute_best_hour_filters_by_min_ctr_threshold(self):
        """Hours with CTR below min_ctr_threshold should be excluded."""
        from modules.content.optimal_post_time import OptimalPostTimeEngine

        hourly_ctr = {
            9:  {"avg_ctr": 0.005, "count": 5},  # below threshold → excluded
            12: {"avg_ctr": 0.025, "count": 5},  # above threshold → valid
            15: {"avg_ctr": 0.030, "count": 5},  # above threshold → valid (count also ok)
        }
        with patch.object(OptimalPostTimeEngine, "_get_hourly_ctr", return_value=hourly_ctr):
            engine = OptimalPostTimeEngine(min_posts=3, min_ctr_threshold=0.01)
            hour = engine.compute_best_hour("facebook")
            self.assertEqual(hour, 15)  # highest CTR among valid hours

    def test_compute_best_hour_tiktok_default(self):
        """TikTok should have its own default hour."""
        from modules.content.optimal_post_time import OptimalPostTimeEngine

        with patch.object(OptimalPostTimeEngine, "_get_hourly_ctr", return_value={}):
            engine = OptimalPostTimeEngine()
            hour = engine.compute_best_hour("tiktok")
            self.assertEqual(hour, 21)

    def test_compute_best_hour_normalises_platform(self):
        """Platform strings 'fb', 'tiktok', 'both' should be normalised."""
        from modules.content.optimal_post_time import OptimalPostTimeEngine

        with patch.object(OptimalPostTimeEngine, "_get_hourly_ctr", return_value={}):
            engine = OptimalPostTimeEngine()
            self.assertEqual(engine.compute_best_hour("fb"), 20)
            self.assertEqual(engine.compute_best_hour("FACEBOOK"), 20)
            self.assertEqual(engine.compute_best_hour("tt"), 21)

    # ── schedule_upload() tests ───────────────────────────────────────────────

    def test_schedule_upload_creates_scheduled_post(self):
        """schedule_upload() should create a ScheduledPost DB record."""
        from modules.content.optimal_post_time import OptimalPostTimeEngine
        import db_models as models

        engine = OptimalPostTimeEngine()

        with self.mock_session as session:
            schedule_id = engine.schedule_upload(
                video_id=42,
                platform="facebook",
                target_hour=20,
                caption="Test caption",
                video_path="/path/to/video.mp4",
            )

            # Verify record was created
            self.assertEqual(len(self.mock_session._data[models.ScheduledPost]), 1)
            post = self.mock_session._data[models.ScheduledPost][0]
            self.assertEqual(post.video_id, 42)
            self.assertEqual(post.platform, "facebook")
            self.assertEqual(post.caption, "Test caption")
            self.assertEqual(post.video_path, "/path/to/video.mp4")
            self.assertEqual(post.status, "pending")
            self.assertIsNotNone(post.scheduled_at)

    def test_schedule_upload_idempotent(self):
        """Second call for same video_id+platform should update existing record."""
        from modules.content.optimal_post_time import OptimalPostTimeEngine
        import db_models as models

        engine = OptimalPostTimeEngine()

        with self.mock_session as session:
            engine.schedule_upload(
                video_id=42,
                platform="facebook",
                target_hour=20,
                caption="First caption",
            )
            schedule_id = engine.schedule_upload(
                video_id=42,
                platform="facebook",
                target_hour=21,
                caption="Updated caption",
            )

            # Should still be 1 record (updated, not created)
            self.assertEqual(len(self.mock_session._data[models.ScheduledPost]), 1)
            post = self.mock_session._data[models.ScheduledPost][0]
            self.assertEqual(post.caption, "Updated caption")

    # ── scheduled datetime logic ───────────────────────────────────────────────

    def test_make_scheduled_datetime_future_hour(self):
        """If target hour is in the future today, schedule for today."""
        from modules.content.optimal_post_time import OptimalPostTimeEngine

        engine = OptimalPostTimeEngine()
        now = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

        # 20:00 > 10:00 today — schedule today
        with patch("modules.content.optimal_post_time.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = engine._make_scheduled_datetime(20)

        self.assertEqual(result.day, 1)  # today
        self.assertEqual(result.hour, 20)

    def test_make_scheduled_datetime_past_hour_skips_to_tomorrow(self):
        """If target hour has already passed today, schedule for tomorrow."""
        from modules.content.optimal_post_time import OptimalPostTimeEngine

        engine = OptimalPostTimeEngine()
        now = datetime(2025, 1, 1, 22, 0, 0, tzinfo=timezone.utc)

        with patch("modules.content.optimal_post_time.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = engine._make_scheduled_datetime(9)  # 9am already passed

        self.assertEqual(result.day, 2)  # tomorrow
        self.assertEqual(result.hour, 9)


class TestScheduledPostsDBModel(unittest.TestCase):
    """Test the ScheduledPost SQLAlchemy model structure."""

    def test_scheduled_post_fields(self):
        """Verify ScheduledPost model has all required fields."""
        import db_models as models

        # Check columns exist
        self.assertTrue(hasattr(models.ScheduledPost, "id"))
        self.assertTrue(hasattr(models.ScheduledPost, "video_id"))
        self.assertTrue(hasattr(models.ScheduledPost, "platform"))
        self.assertTrue(hasattr(models.ScheduledPost, "scheduled_at"))
        self.assertTrue(hasattr(models.ScheduledPost, "caption"))
        self.assertTrue(hasattr(models.ScheduledPost, "video_path"))
        self.assertTrue(hasattr(models.ScheduledPost, "status"))
        self.assertTrue(hasattr(models.ScheduledPost, "error"))
        self.assertTrue(hasattr(models.ScheduledPost, "posted_at"))
        self.assertTrue(hasattr(models.ScheduledPost, "created_at"))

        # Check status default value (ScalarElementColumnDefault wraps the string)
        col = models.ScheduledPost.status.property.columns[0]
        self.assertEqual(col.default.arg, "pending")


if __name__ == "__main__":
    unittest.main()
