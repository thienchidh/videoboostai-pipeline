def test_tiktok_publisher_uses_context_manager():
    """TikTokPublisher.publish should use context manager for file handle."""
    from functools import wraps
    from unittest.mock import patch, MagicMock, mock_open, PropertyMock
    from modules.social.tiktok import TikTokPublisher
    from modules.pipeline.models import SocialPlatformConfig
    import io

    cfg = SocialPlatformConfig(
        auto_publish=True,
    )
    # Set required attributes via object.__setattr__
    object.__setattr__(cfg, "advertiser_id", "1234567")
    object.__setattr__(cfg, "access_token", "real_tiktok_token")

    publisher = TikTokPublisher(cfg)

    # Replace session with mock directly (like facebook test does)
    mock_session = MagicMock()
    mock_session.request.return_value.json.return_value = {"video_id": "vid_123"}
    mock_session.request.return_value.status_code = 200
    publisher._session = mock_session

    # Create a spy that wraps mock_open to track context manager __exit__
    mock_file = mock_open()
    original_exit = mock_file.return_value.__exit__
    exit_called = False

    def tracked_exit(*args, **kwargs):
        nonlocal exit_called
        exit_called = True
        return original_exit(*args, **kwargs)

    mock_file.return_value.__exit__ = tracked_exit

    # Mock tenacity module so retry decorator actually wraps the function
    class _MockTenacity:
        @staticmethod
        def retry(stop=None, wait=None, before_sleep=None, reraise=True):
            def decorator(func):
                @wraps(func)
                def wrapper(*args, **kwargs):
                    return func(*args, **kwargs)
                return wrapper
            return decorator
        @staticmethod
        def stop_after_attempt(attempts):
            return f"stop_after_attempt({attempts})"
        @staticmethod
        def wait_exponential(multiplier=1, min=1, max=60):
            return f"wait_exponential({multiplier}, {min}, {max})"
        @staticmethod
        def before_sleep_log(logger, log_level):
            return f"before_sleep_log({log_level})"

    with patch.dict("sys.modules", {"tenacity": _MockTenacity()}):
        with patch.object(TikTokPublisher, "is_configured", new_callable=PropertyMock, return_value=True):
            with patch("pathlib.Path.exists") as mock_exists:
                mock_exists.return_value = True
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value = MagicMock(st_size=1024)
                    with patch("builtins.open", mock_file):
                        result = publisher.publish("/tmp/test_video.mp4", "Test", "Desc")

    # Verify file was opened
    assert mock_file.called, "open was never called"

    # Verify upload was attempted
    assert mock_session.request.called, "No HTTP requests made"

    # Verify file was properly closed via context manager
    assert exit_called, "File was not closed via context manager (still open)"
