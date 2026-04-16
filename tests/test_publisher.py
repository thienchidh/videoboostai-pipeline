"""
tests/test_publisher.py — Tests for modules/pipeline/publisher.py

Validates video quality checks and SocialPublisher integration.
"""

import pytest
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestValidateVideoQuality:
    """Tests for validate_video_quality()."""

    def test_missing_file_returns_false(self):
        """validate_video_quality returns (False, reason) when file doesn't exist."""
        from modules.pipeline.publisher import validate_video_quality

        valid, reason = validate_video_quality("/nonexistent/video.mp4")
        assert valid is False
        assert "does not exist" in reason

    def test_empty_file_returns_false(self):
        """validate_video_quality returns (False, reason) when file size is 0."""
        from modules.pipeline.publisher import validate_video_quality

        with tempfile.NamedTemporaryFile(delete=True) as tmp:
            valid, reason = validate_video_quality(tmp.name)
            assert valid is False
            assert "empty" in reason

    def test_valid_video_passes_ffprobe_check(self):
        """validate_video_quality passes when ffprobe finds a valid video stream."""
        from modules.pipeline.publisher import validate_video_quality

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout='{"streams": [{"codec_name": "h264", "width": 1280, "height": 720}]}',
                    stderr="",
                )
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value = MagicMock(st_size=1024 * 1024)
                    valid, reason = validate_video_quality(tmp_path)

                assert valid is True
                assert reason == ""
                call_args_list = mock_run.call_args_list
                ffprobe_calls = [c for c in call_args_list if "ffprobe" in c[0][0]]
                assert len(ffprobe_calls) == 1
                ffprobe_call_args = ffprobe_calls[0][0][0]
                assert "-select_streams" in ffprobe_call_args
                assert "v:0" in ffprobe_call_args
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_ffprobe_fails_returns_false(self):
        """validate_video_quality returns (False, reason) when ffprobe returns error."""
        from modules.pipeline.publisher import validate_video_quality

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="Invalid data found",
                )
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value = MagicMock(st_size=1024 * 1024)
                    valid, reason = validate_video_quality(tmp_path)

                assert valid is False
                assert "ffprobe failed" in reason
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_ffmpeg_frame_extraction_fails_returns_false(self):
        """validate_video_quality returns (False, reason) when ffmpeg can't read frames."""
        from modules.pipeline.publisher import validate_video_quality

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            def side_effect(*args, **kwargs):
                cmd = args[0]
                if "ffprobe" in cmd:
                    return MagicMock(
                        returncode=0,
                        stdout='{"streams": [{"codec_name": "h264"}]}',
                        stderr="",
                    )
                else:
                    return MagicMock(
                        returncode=1,
                        stdout="",
                        stderr="Invalid codec",
                    )

            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = side_effect
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value = MagicMock(st_size=1024 * 1024)
                    valid, reason = validate_video_quality(tmp_path)

                assert valid is False
                assert "frame extraction failed" in reason
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_ffmpeg_times_out_returns_false(self):
        """validate_video_quality returns (False, reason) on ffmpeg timeout."""
        from modules.pipeline.publisher import validate_video_quality

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            def side_effect(*args, **kwargs):
                cmd = args[0]
                if "ffprobe" in cmd:
                    return MagicMock(
                        returncode=0,
                        stdout='{"streams": [{"codec_name": "h264"}]}',
                        stderr="",
                    )
                else:
                    raise subprocess.TimeoutExpired(cmd, 60)

            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = side_effect
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value = MagicMock(st_size=1024 * 1024)
                    valid, reason = validate_video_quality(tmp_path)

                assert valid is False
                assert "timed out" in reason
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestSocialPublisherValidation:
    """Tests for SocialPublisher.upload_to_socials() with validation."""

    def test_skips_upload_when_validation_fails(self):
        """SocialPublisher skips all platform uploads when video validation fails."""
        from modules.pipeline.publisher import SocialPublisher, validate_video_quality
        from modules.pipeline.models import SocialConfig, SocialPlatformConfig

        cfg = SocialConfig(
            facebook=SocialPlatformConfig(page_id="123", page_name="Test", auto_publish=True),
            tiktok=SocialPlatformConfig(advertiser_id="456", auto_publish=True),
        )
        object.__setattr__(cfg.facebook, "access_token", "real_token")
        object.__setattr__(cfg.tiktok, "access_token", "real_token")

        with patch("modules.pipeline.publisher.validate_video_quality") as mock_validate:
            mock_validate.return_value = (False, "ffprobe failed: no streams")

            publisher = SocialPublisher(cfg, dry_run=False)

            result = publisher.upload_to_socials("/fake/video.mp4", "Test script")

            assert result.success is False
            assert len(result.results) == 2
            for r in result.results:
                assert r["success"] is False
                assert "video validation failed" in r["error"]
            mock_validate.assert_called_once_with("/fake/video.mp4")

    def test_continues_to_upload_when_validation_passes(self):
        """SocialPublisher proceeds to publish when video validation passes."""
        from modules.pipeline.publisher import SocialPublisher
        from modules.pipeline.models import SocialConfig, SocialPlatformConfig

        cfg = SocialConfig(
            facebook=SocialPlatformConfig(page_id="123", page_name="Test", auto_publish=True),
            tiktok=SocialPlatformConfig(advertiser_id="456", auto_publish=True),
        )
        object.__setattr__(cfg.facebook, "access_token", "real_token")
        object.__setattr__(cfg.tiktok, "access_token", "real_token")

        with patch("modules.pipeline.publisher.validate_video_quality") as mock_validate:
            mock_validate.return_value = (True, "")

            publisher = SocialPublisher(cfg, dry_run=False)

            with patch.object(publisher.fb_publisher, "publish", return_value="https://facebook.com/post/123"):
                with patch.object(publisher.tt_publisher, "publish", return_value="https://tiktok.com/video/456"):
                    result = publisher.upload_to_socials("/fake/video.mp4", "Test script")

            assert result.success is True

    def test_dry_run_still_validates(self):
        """SocialPublisher validates video even in dry_run mode."""
        from modules.pipeline.publisher import SocialPublisher
        from modules.pipeline.models import SocialConfig, SocialPlatformConfig

        cfg = SocialConfig(
            facebook=SocialPlatformConfig(page_id="123", page_name="Test", auto_publish=True),
            tiktok=SocialPlatformConfig(advertiser_id="456", auto_publish=True),
        )
        object.__setattr__(cfg.facebook, "access_token", "real_token")
        object.__setattr__(cfg.tiktok, "access_token", "real_token")

        publisher = SocialPublisher(cfg, dry_run=True)

        with patch("modules.pipeline.publisher.validate_video_quality") as mock_validate:
            mock_validate.return_value = (False, "file is empty")

            result = publisher.upload_to_socials("/fake/video.mp4", "Test script")

            assert result.success is False
            mock_validate.assert_called_once_with("/fake/video.mp4")
