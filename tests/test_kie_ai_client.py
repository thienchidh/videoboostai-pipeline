"""
tests/test_kie_ai_client.py — VP-032

Unit tests for modules/media/kie_ai_client.py
- KieAIClient init and auth headers
- create_task() / infinitalk() success + error paths
- get_task() with pending/completed/failed states
- poll_task() with pending/completed/failed states
- Quota/credit exhaustion detection → poll_task returns error dict (caller raises LipsyncQuotaError)
- All HTTP calls are mocked (no real API calls)
"""

import json
import time
from unittest.mock import patch, MagicMock, call

import pytest

from modules.media.kie_ai_client import KieAIClient


# ─── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture
def api_key():
    return "test_kie_api_key_12345"


@pytest.fixture
def client(api_key):
    from modules.media.kie_ai_client import KieAIClient
    return KieAIClient(api_key=api_key, timeout=30)


@pytest.fixture
def mock_session(client):
    """Patch the client's internal requests session."""
    with patch.object(client, "session") as mock_sess:
        yield mock_sess


# ─── Init tests ───────────────────────────────────────────────────────────────

class TestKieAIClientInit:
    def test_init_sets_api_key(self, api_key):
        from modules.media.kie_ai_client import KieAIClient
        c = KieAIClient(api_key=api_key)
        assert c.api_key == api_key

    def test_init_sets_base_url(self, client):
        assert client.BASE_URL == "https://api.kie.ai/api/v1"

    def test_init_sets_timeout(self):
        from modules.media.kie_ai_client import KieAIClient
        c = KieAIClient(api_key="foo", timeout=60)
        assert c.timeout == 60

    def test_init_sets_webhook_key(self):
        from modules.media.kie_ai_client import KieAIClient
        c = KieAIClient(api_key="foo", webhook_key="wh_abc123")
        assert c.webhook_key == "wh_abc123"

    def test_init_sets_webhook_url(self):
        from modules.media.kie_ai_client import KieAIClient
        c = KieAIClient(api_key="foo", webhook_url="https://example.com/cb")
        assert c.webhook_url == "https://example.com/cb"

    def test_init_default_webhook_key_empty_string(self, api_key):
        from modules.media.kie_ai_client import KieAIClient
        c = KieAIClient(api_key=api_key)
        assert c.webhook_key == ""

    def test_init_default_webhook_url_empty_string(self, api_key):
        from modules.media.kie_ai_client import KieAIClient
        c = KieAIClient(api_key=api_key)
        assert c.webhook_url == ""

    def test_init_raises_missing_config_error_if_no_api_key(self):
        from modules.media.kie_ai_client import KieAIClient
        from modules.pipeline.exceptions import MissingConfigError
        with pytest.raises(MissingConfigError):
            KieAIClient(api_key=None)

    def test_init_raises_missing_config_error_if_empty_string(self):
        from modules.media.kie_ai_client import KieAIClient
        from modules.pipeline.exceptions import MissingConfigError
        with pytest.raises(MissingConfigError):
            KieAIClient(api_key="")

    def test_auth_headers_include_bearer_token(self, client):
        auth = client.session.headers.get("Authorization")
        assert auth == "Bearer test_kie_api_key_12345"

    def test_auth_headers_content_type_json(self, client):
        ct = client.session.headers.get("Content-Type")
        assert ct == "application/json"


# ─── infinitalk() / create_task tests ─────────────────────────────────────────

class TestInfinitalkSuccess:
    def test_infinitalk_returns_success_with_task_id(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "code": 200,
            "data": {"taskId": "task_abc123"}
        }
        mock_session.post.return_value = mock_resp

        result = client.infinitalk(
            image_url="https://example.com/img.jpg",
            audio_url="https://example.com/audio.mp3",
            prompt="A person talking",
            resolution="480p",
        )

        assert result["success"] is True
        assert result["task_id"] == "task_abc123"
        mock_session.post.assert_called_once()
        call_kwargs = mock_session.post.call_args
        assert call_kwargs.kwargs["timeout"] == 30
        # payload check
        payload = call_kwargs.kwargs["json"]
        assert payload["model"] == "infinitalk/from-audio"
        assert payload["input"]["image_url"] == "https://example.com/img.jpg"
        assert payload["input"]["audio_url"] == "https://example.com/audio.mp3"

    def test_infinitalk_uses_record_id_when_task_id_absent(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "code": 200,
            "data": {"recordId": "rec_xyz789"}
        }
        mock_session.post.return_value = mock_resp

        result = client.infinitalk(
            image_url="https://img.com/a.png",
            audio_url="https://audio.com/b.mp3",
        )

        assert result["success"] is True
        assert result["task_id"] == "rec_xyz789"

    def test_infinitalk_includes_callback_url_when_provided(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"code": 200, "data": {"taskId": "t1"}}
        mock_session.post.return_value = mock_resp

        client.infinitalk(
            image_url="https://img.com/a.png",
            audio_url="https://audio.com/b.mp3",
            callback_url="https://example.com/callback",
        )

        payload = mock_session.post.call_args.kwargs["json"]
        assert payload["callBackUrl"] == "https://example.com/callback"

    def test_infinitalk_uses_instance_webhook_url_when_no_callback(self, client, mock_session):
        from modules.media.kie_ai_client import KieAIClient
        c = KieAIClient(api_key="key", webhook_url="https://example.com/hook")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"code": 200, "data": {"taskId": "t1"}}
        with patch.object(c, "session") as mock_sess:
            mock_sess.post.return_value = mock_resp
            c.infinitalk(
                image_url="https://img.com/a.png",
                audio_url="https://audio.com/b.mp3",
            )
        payload = mock_sess.post.call_args.kwargs["json"]
        assert payload["callBackUrl"] == "https://example.com/hook"


class TestInfinitalkErrors:
    def test_infinitalk_returns_error_on_non_200_status(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"code": 401, "msg": "unauthorized"}
        mock_session.post.return_value = mock_resp

        result = client.infinitalk(
            image_url="https://img.com/a.png",
            audio_url="https://audio.com/b.mp3",
        )

        assert result["success"] is False
        assert result["status_code"] == 401
        assert result["error"]["code"] == 401

    def test_infinitalk_returns_error_on_nonzero_code(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"code": 400, "msg": "bad request"}
        mock_session.post.return_value = mock_resp

        result = client.infinitalk(
            image_url="https://img.com/a.png",
            audio_url="https://audio.com/b.mp3",
        )

        assert result["success"] is False
        assert result["status_code"] == 200

    def test_infinitalk_returns_error_on_timeout(self, client, mock_session):
        import requests
        mock_session.post.side_effect = requests.exceptions.Timeout("Connection timed out")

        result = client.infinitalk(
            image_url="https://img.com/a.png",
            audio_url="https://audio.com/b.mp3",
        )

        assert result["success"] is False
        assert result["error"] == "Request timeout"

    def test_infinitalk_returns_error_on_exception(self, client, mock_session):
        mock_session.post.side_effect = RuntimeError("Unexpected error")

        result = client.infinitalk(
            image_url="https://img.com/a.png",
            audio_url="https://audio.com/b.mp3",
        )

        assert result["success"] is False
        assert "Unexpected error" in result["error"]


# ─── get_task() tests ────────────────────────────────────────────────────────

class TestGetTask:
    def test_get_task_success_returns_data(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {"state": "success", "resultJson": '{"resultUrls": ["https://v.com/v.mp4"]}'}
        }
        mock_session.get.return_value = mock_resp

        result = client.get_task("task_123")

        assert result["success"] is True
        assert result["data"]["state"] == "success"
        mock_session.get.assert_called_once()
        call_args_str = mock_session.get.call_args.args[0]
        assert "taskId=task_123" in call_args_str

    def test_get_task_returns_error_on_non_200(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"code": 500}
        mock_session.get.return_value = mock_resp

        result = client.get_task("task_123")

        assert result["success"] is False
        assert result["status_code"] == 500

    def test_get_task_returns_error_on_exception(self, client, mock_session):
        mock_session.get.side_effect = RuntimeError("Network error")

        result = client.get_task("task_123")

        assert result["success"] is False
        assert "Network error" in result["error"]


# ─── poll_task() tests ────────────────────────────────────────────────────────

class TestPollTaskSuccess:
    def test_poll_task_returns_output_urls_on_success(self, client, mock_session):
        # First poll → waiting, second poll → success
        mock_waiting = MagicMock()
        mock_waiting.status_code = 200
        mock_waiting.json.return_value = {
            "data": {"state": "waiting"}
        }
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {
            "data": {
                "state": "success",
                "resultJson": json.dumps({"resultUrls": ["https://v.com/v1.mp4", "https://v.com/v2.mp4"]})
            }
        }
        mock_session.get.side_effect = [mock_waiting, mock_success]

        with patch("modules.media.kie_ai_client.time.sleep"):
            result = client.poll_task("task_123", interval=2, max_wait=60)

        assert result["success"] is True
        assert result["output_urls"] == ["https://v.com/v1.mp4", "https://v.com/v2.mp4"]
        assert len(result["output_urls"]) == 2

    def test_poll_task_handles_result_json_already_parsed(self, client, mock_session):
        """resultJson may already be a dict, not a string."""
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {
            "data": {
                "state": "success",
                "resultJson": {"resultUrls": ["https://v.com/v.mp4"]}  # already a dict
            }
        }
        mock_session.get.return_value = mock_success

        result = client.poll_task("task_123", interval=5, max_wait=60)

        assert result["success"] is True
        assert result["output_urls"] == ["https://v.com/v.mp4"]

    def test_poll_task_returns_error_on_fail_state(self, client, mock_session):
        mock_fail = MagicMock()
        mock_fail.status_code = 200
        mock_fail.json.return_value = {
            "data": {
                "state": "fail",
                "failMsg": "Quota exhausted"
            }
        }
        mock_session.get.return_value = mock_fail

        result = client.poll_task("task_123", interval=5, max_wait=60)

        assert result["success"] is False
        assert result["error"] == "Quota exhausted"

    def test_poll_task_returns_error_on_failed_state(self, client, mock_session):
        mock_fail = MagicMock()
        mock_fail.status_code = 200
        mock_fail.json.return_value = {
            "data": {
                "state": "failed",
                "failMsg": "Credits insufficient"
            }
        }
        mock_session.get.return_value = mock_fail

        result = client.poll_task("task_123", interval=5, max_wait=60)

        assert result["success"] is False
        assert result["error"] == "Credits insufficient"

    def test_poll_task_returns_error_on_get_task_failure(self, client, mock_session):
        mock_err = MagicMock()
        mock_err.status_code = 500
        mock_err.json.return_value = {"code": 500}
        mock_session.get.return_value = mock_err

        result = client.poll_task("task_123", interval=5, max_wait=60)

        assert result["success"] is False
        assert result["status_code"] == 500

    def test_poll_task_returns_timeout_after_max_wait(self, client, mock_session):
        # Always return "queuing" → never reaches success
        mock_queuing = MagicMock()
        mock_queuing.status_code = 200
        mock_queuing.json.return_value = {"data": {"state": "queuing"}}
        mock_session.get.return_value = mock_queuing

        with patch("modules.media.kie_ai_client.time.sleep"):
            result = client.poll_task("task_123", interval=1, max_wait=3)

        assert result["success"] is False
        assert result["error"] == "Polling timeout"

    def test_poll_task_includes_result_json_in_return(self, client, mock_session):
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {
            "data": {
                "state": "success",
                "resultJson": json.dumps({"resultUrls": ["https://v.com/v.mp4"], "extra": "data"})
            }
        }
        mock_session.get.return_value = mock_success

        result = client.poll_task("task_123", interval=5, max_wait=60)

        assert result["success"] is True
        assert "result_json" in result
        assert result["result_json"]["extra"] == "data"


# ─── Quota exhaustion tests ───────────────────────────────────────────────────

class TestQuotaErrorDetection:
    """Test that quota/credit exhaustion is detected and poll_task returns error dict."""

    def test_poll_task_quota_exhaustion_returns_error(self, client, mock_session):
        """
        When the API returns fail/failed state with quota-related failMsg,
        poll_task returns an error dict (caller lipsync.py raises LipsyncQuotaError).
        """
        mock_fail = MagicMock()
        mock_fail.status_code = 200
        mock_fail.json.return_value = {
            "data": {
                "state": "failed",
                "failMsg": "Quota or credits exhausted"
            }
        }
        mock_session.get.return_value = mock_fail

        result = client.poll_task("task_quota_123", interval=5, max_wait=60)
        assert result["success"] is False
        assert "quota" in result["error"].lower() or "credit" in result["error"].lower()

    def test_poll_task_insufficient_credits_returns_error(self, client, mock_session):
        mock_fail = MagicMock()
        mock_fail.status_code = 200
        mock_fail.json.return_value = {
            "data": {
                "state": "failed",
                "failMsg": "Insufficient credits"
            }
        }
        mock_session.get.return_value = mock_fail

        result = client.poll_task("task_quota_456", interval=5, max_wait=60)
        assert result["success"] is False
        assert "credit" in result["error"].lower()

    def test_poll_task_generic_failure_not_quota_error(self, client, mock_session):
        """Generic failure messages should NOT trigger quota-style errors."""
        mock_fail = MagicMock()
        mock_fail.status_code = 200
        mock_fail.json.return_value = {
            "data": {
                "state": "failed",
                "failMsg": "Model temporarily unavailable"
            }
        }
        mock_session.get.return_value = mock_fail

        result = client.poll_task("task_gen_789", interval=5, max_wait=60)
        assert result["success"] is False
        assert result["error"] == "Model temporarily unavailable"


class TestIsZeroBalance:
    """Tests for _is_zero_balance() helper."""

    def test_zero_credits_returns_true(self):
        """Should return True when credits is 0."""
        client = KieAIClient(api_key="test-key")
        result = {"success": True, "data": {"credits": 0}}
        assert client._is_zero_balance(result) is True

    def test_nonzero_credits_returns_false(self):
        """Should return False when credits > 0."""
        client = KieAIClient(api_key="test-key")
        result = {"success": True, "data": {"credits": 50}}
        assert client._is_zero_balance(result) is False

    def test_balance_field_zero_returns_true(self):
        """Should return True when balance field is 0 (alternative field name)."""
        client = KieAIClient(api_key="test-key")
        result = {"success": True, "data": {"balance": 0}}
        assert client._is_zero_balance(result) is True

    def test_missing_data_returns_false(self):
        """Should return False when data field is absent."""
        client = KieAIClient(api_key="test-key")
        result = {"success": True, "data": {}}
        assert client._is_zero_balance(result) is False


class TestPollTaskMidBalanceCheck:
    """Tests for mid-poll balance check in poll_task()."""

    def test_mid_poll_quota_exhaustion_returns_error(self):
        """Should return error dict immediately when balance hits zero mid-poll."""
        client = KieAIClient(api_key="test-key")

        # Mock get_task to return "queuing" forever, get_balance to return zero balance
        queuing_response = {"success": True, "data": {"state": "queuing"}}
        zero_balance = {"success": True, "data": {"credits": 0}}

        def mock_get_task(task_id):
            return queuing_response

        def mock_get_balance():
            return zero_balance

        client.get_task = mock_get_task
        client.get_balance = mock_get_balance

        # Patch time so 60+ seconds elapse quickly (balance check fires at ~60s)
        start_time = [100.0]

        def mock_time():
            start_time[0] += 65  # Advance past 60s threshold
            return start_time[0]

        with patch("modules.media.kie_ai_client.time.time", side_effect=mock_time):
            with patch("modules.media.kie_ai_client.time.sleep"):
                result = client.poll_task(task_id="fake-task-id", interval=1, max_wait=120)

        assert result["success"] is False
        assert "quota" in result["error"].lower() or "exhausted" in result["error"].lower()


# ─── get_balance() tests ──────────────────────────────────────────────────────

class TestGetBalance:
    def test_get_balance_success(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # API returns {"credits": 500} directly; get_balance returns {"success":True,"data":<api_response>}
        mock_resp.json.return_value = {"credits": 500}
        mock_session.get.return_value = mock_resp

        result = client.get_balance()

        assert result["success"] is True
        assert result["data"]["credits"] == 500
        call_url = mock_session.get.call_args.args[0]
        assert "account/balance" in call_url

    def test_get_balance_error(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"code": 401}
        mock_session.get.return_value = mock_resp

        result = client.get_balance()

        assert result["success"] is False
        assert result["status_code"] == 401
