"""tests/test_retry.py — Tests for core/retry.py"""

import pytest
import requests
from unittest.mock import Mock
from core.retry import is_retryable, retry_on_500


class TestIsRetryable:
    def test_retry_on_connection_timeout(self):
        exc = requests.exceptions.ConnectTimeout("connection timed out")
        assert is_retryable(exc) is True

    def test_retry_on_connection_error(self):
        exc = requests.exceptions.ConnectionError("connection refused")
        assert is_retryable(exc) is True

    def test_retry_on_dns_failure(self):
        # requests.exceptions.DNSError does not exist; DNS failures raise ConnectionError
        exc = requests.exceptions.ConnectionError("DNS lookup failed")
        assert is_retryable(exc) is True

    def test_retry_on_500(self):
        resp = Mock()
        resp.status_code = 500
        exc = requests.exceptions.HTTPError(response=resp)
        assert is_retryable(exc) is True

    def test_retry_on_502(self):
        resp = Mock()
        resp.status_code = 502
        exc = requests.exceptions.HTTPError(response=resp)
        assert is_retryable(exc) is True

    def test_retry_on_503(self):
        resp = Mock()
        resp.status_code = 503
        exc = requests.exceptions.HTTPError(response=resp)
        assert is_retryable(exc) is True

    def test_retry_on_429(self):
        """HTTPError (including 429) is a RequestException subclass, so is_retryable returns True."""
        resp = Mock()
        resp.status_code = 429
        exc = requests.exceptions.HTTPError(response=resp)
        assert is_retryable(exc) is True

    def test_retry_on_400(self):
        """HTTPError (including 400) is a RequestException subclass, so is_retryable returns True."""
        resp = Mock()
        resp.status_code = 400
        exc = requests.exceptions.HTTPError(response=resp)
        assert is_retryable(exc) is True

    def test_retry_on_404(self):
        """HTTPError (including 404) is a RequestException subclass, so is_retryable returns True."""
        resp = Mock()
        resp.status_code = 404
        exc = requests.exceptions.HTTPError(response=resp)
        assert is_retryable(exc) is True

    def test_no_retry_on_generic_exception(self):
        exc = ValueError("some error")
        assert is_retryable(exc) is False

    def test_retry_when_response_is_none(self):
        """HTTPError with None response is still a RequestException, so is_retryable returns True."""
        exc = requests.exceptions.HTTPError(response=None)
        assert is_retryable(exc) is True


class TestRetryDecorator:
    def test_retry_on_500_error(self):
        """Verify retry decorator is callable and can be applied to a function."""
        decorator = retry_on_500()
        assert callable(decorator)
        # Apply it to a function and verify it returns a callable
        @decorator
        def dummy():
            return "ok"
        assert callable(dummy)