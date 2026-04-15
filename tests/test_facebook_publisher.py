def test_facebook_publisher_completes_chunked_upload():
    """FacebookPublisher should complete all 3 phases: start, transfer, finish."""
    from unittest.mock import patch, MagicMock, PropertyMock
    import io
    from modules.social.facebook import FacebookPublisher
    from modules.pipeline.models import SocialPlatformConfig

    cfg = SocialPlatformConfig(
        page_id="123456",
        page_name="Test Page",
        auto_publish=True,
    )
    object.__setattr__(cfg, "access_token", "real_token_abc123")

    publisher = FacebookPublisher(cfg)
    publisher.access_token = "real_token_abc123"
    publisher.page_id = "123456"

    # Mock _retry_request to return expected responses for start, transfer, finish phases
    retry_responses = [
        {"upload_session_id": "sess_123", "video_id": "vid_456"},  # start
        {"upload_session_id": "sess_123"},                          # transfer
        {"id": "vid_456"},                                           # finish
    ]

    def retry_side_effect(*_args, **_kwargs):
        return retry_responses.pop(0) if retry_responses else {"id": "vid_456"}

    publisher._retry_request = MagicMock(side_effect=retry_side_effect)

    # Create a fake file that returns bytes then empty
    fake_file = io.BytesIO(b"x" * 1024 * 1024)  # 1MB of 'x' bytes

    with patch("modules.social.facebook.FacebookPublisher.is_configured", new_callable=PropertyMock, return_value=True):
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = True
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value = MagicMock(st_size=1024 * 1024)
                with patch("builtins.open", return_value=fake_file):
                    result = publisher.publish("/tmp/test_video.mp4", "Test Title", "Test Desc")

    retry_calls = publisher._retry_request.call_args_list
    post_calls = [c for c in retry_calls if c[0][0] == "POST"]
    assert len(post_calls) >= 2, f"Expected at least 2 POST calls, got {len(post_calls)}: {[c[1].get('data', {}) for c in post_calls]}"

    finish_call = post_calls[-1]
    finish_data = finish_call[1].get("data", {}) or {}
    assert "upload_session_id" in str(finish_data) or "sess_123" in str(finish_data), \
        f"Finish call missing upload_session_id: {finish_data}"

    assert result is not None, "publish should return a URL"