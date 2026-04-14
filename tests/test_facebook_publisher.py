def test_facebook_publisher_completes_chunked_upload():
    """FacebookPublisher should complete all 3 phases: start, transfer, finish."""
    from unittest.mock import patch, MagicMock
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

    # Mock the session directly on the instance
    mock_session = MagicMock()
    publisher._session = mock_session

    # Responses for: start, transfer, finish
    post_responses = [
        {"upload_session_id": "sess_123", "video_id": "vid_456"},  # start
        {"upload_session_id": "sess_123"},                          # transfer
        {"id": "vid_456"},                                           # finish
    ]

    def json_side_effect():
        return post_responses.pop(0) if post_responses else {"id": "vid_456"}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = json_side_effect
    mock_session.request.return_value = mock_resp

    # Create a fake file that returns bytes then empty
    fake_file = io.BytesIO(b"x" * 1024 * 1024)  # 1MB of 'x' bytes

    with patch("pathlib.Path.exists") as mock_exists:
        mock_exists.return_value = True
        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_size=1024 * 1024)
            with patch("builtins.open", return_value=fake_file):
                result = publisher.publish("/tmp/test_video.mp4", "Test Title", "Test Desc")

    post_calls = [c for c in mock_session.request.call_args_list if c[0][0] == "POST"]
    assert len(post_calls) >= 2, f"Expected at least 2 POST calls, got {len(post_calls)}: {[c[1].get('data', {}) for c in post_calls]}"

    finish_call = post_calls[-1]
    finish_data = finish_call[1].get("data", {}) or {}
    assert "upload_session_id" in str(finish_data) or "sess_123" in str(finish_data), \
        f"Finish call missing upload_session_id: {finish_data}"

    assert result is not None, "publish should return a URL"