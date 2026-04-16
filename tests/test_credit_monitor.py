#!/usr/bin/env python3
"""Unit tests for modules/ops/credit_monitor.py"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Ensure project root in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.ops.credit_monitor import (
    CreditMonitor,
    CreditBalanceProvider,
    KieAIBalanceProvider,
    MiniMaxBalanceProvider,
    WaveSpeedBalanceProvider,
    UNKNOWN_BALANCE,
    DEFAULT_THRESHOLDS,
)


# ─── Provider Tests ───────────────────────────────────────────────────────────

class TestCreditBalanceProviders(unittest.TestCase):
    """Test individual provider classes."""

    @patch('modules.ops.credit_monitor.requests.Session')
    def test_kie_ai_balance_success(self, MockSession):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"code": 200, "data": {"balance": "25.50"}}
        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_resp
        MockSession.return_value = mock_session_instance

        provider = KieAIBalanceProvider("test-key")
        balance = provider.get_balance()
        self.assertEqual(balance, 25.50)

    @patch('modules.ops.credit_monitor.requests.Session')
    def test_kie_ai_balance_unknown_on_error(self, MockSession):
        mock_session_instance = MagicMock()
        mock_session_instance.get.side_effect = Exception("network error")
        MockSession.return_value = mock_session_instance

        provider = KieAIBalanceProvider("test-key")
        balance = provider.get_balance()
        self.assertEqual(balance, UNKNOWN_BALANCE)

    @patch('modules.ops.credit_monitor.requests.get')
    def test_minimax_balance_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"balance": 150.75}}
        mock_get.return_value = mock_resp

        provider = MiniMaxBalanceProvider("test-key")
        balance = provider.get_balance()
        self.assertEqual(balance, 150.75)

    @patch('modules.ops.credit_monitor.requests.get')
    def test_minimax_balance_fallback(self, mock_get):
        mock_get.side_effect = [
            Exception("first fail"),
            MagicMock(status_code=200, json=lambda: {"data": {"remaining": 99.0}})
        ]
        provider = MiniMaxBalanceProvider("test-key")
        balance = provider.get_balance()
        self.assertEqual(balance, 99.0)

    @patch('modules.ops.credit_monitor.requests.Session')
    def test_wavespeed_balance_success(self, MockSession):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"balance": 300.0}}
        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_resp
        MockSession.return_value = mock_session_instance

        provider = WaveSpeedBalanceProvider("test-key")
        balance = provider.get_balance()
        self.assertEqual(balance, 300.0)


# ─── CreditMonitor Init Tests ─────────────────────────────────────────────────

class TestCreditMonitorInit(unittest.TestCase):
    """Test CreditMonitor.__init__()."""

    def test_default_thresholds(self):
        m = CreditMonitor()
        self.assertEqual(m.thresholds, DEFAULT_THRESHOLDS)

    def test_custom_thresholds(self):
        m = CreditMonitor(thresholds={"kieai": 0.30, "minimax": 0.10})
        self.assertEqual(m.thresholds["kieai"], 0.30)
        self.assertEqual(m.thresholds["minimax"], 0.10)

    def test_dry_run_mode(self):
        m = CreditMonitor(dry_run=True)
        self.assertTrue(m.dry_run)

    def test_providers_registered(self):
        m = CreditMonitor(kie_api_key="kie-key", minimax_api_key="mm-key", wavespeed_api_key="ws-key")
        self.assertIn("kieai", m._providers)
        self.assertIn("minimax", m._providers)
        self.assertIn("wavespeed", m._providers)

    def test_no_providers_when_no_keys(self):
        m = CreditMonitor()
        self.assertEqual(len(m._providers), 0)


# ─── CreditMonitor.check_balance Tests ────────────────────────────────────────

class TestCreditMonitorCheckBalance(unittest.TestCase):
    """Test CreditMonitor.check_balance()."""

    @patch.object(CreditMonitor, '_log_to_db')
    def test_check_balance_returns_value(self, mock_log):
        m = CreditMonitor(kie_api_key="kie-key")
        m._providers["kieai"] = MagicMock()
        m._providers["kieai"].get_balance = lambda: 50.0

        balance = m.check_balance("kieai")
        self.assertEqual(balance, 50.0)
        mock_log.assert_called_once_with("kieai", 50.0)

    @patch.object(CreditMonitor, '_log_to_db')
    def test_check_balance_unknown_not_logged(self, mock_log):
        m = CreditMonitor(kie_api_key="kie-key")
        m._providers["kieai"] = MagicMock()
        m._providers["kieai"].get_balance = lambda: UNKNOWN_BALANCE

        balance = m.check_balance("kieai")
        self.assertEqual(balance, UNKNOWN_BALANCE)

    def test_check_balance_unknown_provider(self):
        m = CreditMonitor()
        balance = m.check_balance("nonexistent")
        self.assertEqual(balance, UNKNOWN_BALANCE)


# ─── CreditMonitor.check_all Tests ────────────────────────────────────────────

class TestCreditMonitorCheckAll(unittest.TestCase):
    """Test CreditMonitor.check_all()."""

    @patch.object(CreditMonitor, 'check_balance', side_effect=[25.0, 100.0])
    def test_check_all_returns_all_providers(self, mock_check):
        m = CreditMonitor(kie_api_key="kie-key", minimax_api_key="mm-key")
        m._providers = {"kieai": MagicMock(), "minimax": MagicMock()}

        results = m.check_all()
        self.assertIn("kieai", results)
        self.assertIn("minimax", results)
        self.assertEqual(results["kieai"], 25.0)
        self.assertEqual(results["minimax"], 100.0)
        self.assertEqual(mock_check.call_count, 2)


# ─── CreditMonitor.alert_if_low Tests ─────────────────────────────────────────

class TestCreditMonitorAlertIfLow(unittest.TestCase):
    """Test CreditMonitor.alert_if_low()."""

    @patch.object(CreditMonitor, '_send_alert')
    @patch.object(CreditMonitor, '_save_debounce')
    @patch.object(CreditMonitor, '_load_debounce', return_value={})
    def test_alert_sent_when_low(self, mock_load, mock_save, mock_send):
        m = CreditMonitor(kie_api_key="kie-key", thresholds={"kieai": 0.20})
        m._last_alert = {}
        # 50 out of 1000 = 5% < 20% threshold
        m.alert_if_low("kieai", 50.0, initial_balance=1000.0)
        mock_send.assert_called_once()

    @patch.object(CreditMonitor, '_send_alert')
    @patch.object(CreditMonitor, '_load_debounce', return_value={})
    def test_alert_skipped_when_above_threshold(self, mock_load, mock_send):
        m = CreditMonitor(kie_api_key="kie-key", thresholds={"kieai": 0.20})
        m._last_alert = {}
        # 500 out of 1000 = 50% >= 20% threshold
        m.alert_if_low("kieai", 500.0, initial_balance=1000.0)
        mock_send.assert_not_called()

    @patch.object(CreditMonitor, '_send_alert')
    def test_alert_skipped_when_unknown_balance(self, mock_send):
        m = CreditMonitor()
        m.alert_if_low("kieai", UNKNOWN_BALANCE, initial_balance=1000.0)
        mock_send.assert_not_called()

    @patch.object(CreditMonitor, '_send_alert')
    @patch.object(CreditMonitor, '_save_debounce')
    @patch.object(CreditMonitor, '_load_debounce', return_value={})
    def test_alert_debounced_within_30min(self, mock_load, mock_save, mock_send):
        m = CreditMonitor(kie_api_key="kie-key")
        m._last_alert = {"kieai": time.time()}  # triggered just now
        m.alert_if_low("kieai", 50.0, initial_balance=1000.0)
        mock_send.assert_not_called()  # still in debounce window


# ─── CreditMonitor._send_alert Tests ──────────────────────────────────────────

class TestCreditMonitorSendAlert(unittest.TestCase):
    """Test CreditMonitor._send_alert()."""

    def _make_mock_module(self, send_fn):
        mock_mod = MagicMock()
        mock_mod.message.send = send_fn
        return mock_mod

    def test_send_alert_dry_run(self):
        mock_send = MagicMock()
        m = CreditMonitor(dry_run=True)
        with patch.dict('sys.modules', {
            'openclaw_personal_utilities': self._make_mock_module(mock_send)
        }):
            m._send_alert("kieai", 50.0, 0.05)
        mock_send.assert_not_called()

    def test_send_alert_live(self):
        mock_send = MagicMock()
        m = CreditMonitor(dry_run=False)
        with patch.dict('sys.modules', {
            'openclaw_personal_utilities': self._make_mock_module(mock_send)
        }):
            m._send_alert("kieai", 50.0, 0.05)
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs["action"], "send")
        self.assertIn("kieai", call_kwargs["message"])
        self.assertIn("5.0%", call_kwargs["message"])

    def test_send_alert_import_error(self):
        m = CreditMonitor(dry_run=False)
        with patch.dict('sys.modules', {'openclaw_personal_utilities': None}):
            from modules.ops import credit_monitor as cm
            with patch.object(cm, 'logger') as mock_logger:
                m._send_alert("kieai", 50.0, 0.05)  # must not raise
                mock_logger.warning.assert_called()

    def test_send_alert_failure_logged(self):
        m = CreditMonitor(dry_run=False)
        mock_send = MagicMock(side_effect=Exception("telegram error"))
        with patch.dict('sys.modules', {
            'openclaw_personal_utilities': self._make_mock_module(mock_send)
        }):
            from modules.ops import credit_monitor as cm
            with patch.object(cm, 'logger') as mock_logger:
                m._send_alert("kieai", 50.0, 0.05)  # must not raise
                mock_logger.warning.assert_called()


# ─── CreditMonitor Debounce Tests ─────────────────────────────────────────────

class TestCreditMonitorDebounce(unittest.TestCase):
    """Test debounce persistence."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.debounce_file = Path(self.temp_dir) / ".last_credit_alert"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_debounce_empty_file(self):
        with patch.object(CreditMonitor, '_debounce_file', return_value=self.debounce_file):
            m = CreditMonitor()
            result = m._load_debounce()
            self.assertEqual(result, {})

    def test_save_and_load_debounce(self):
        with patch.object(CreditMonitor, '_debounce_file', return_value=self.debounce_file):
            m = CreditMonitor()
            m._last_alert = {"kieai": 1234567890.0, "minimax": 9876543210.0}
            m._save_debounce()
            loaded = m._load_debounce()
            self.assertEqual(loaded, {"kieai": 1234567890.0, "minimax": 9876543210.0})

    def test_load_debounce_corrupt_file(self):
        self.debounce_file.write_text("not valid json{")
        with patch.object(CreditMonitor, '_debounce_file', return_value=self.debounce_file):
            m = CreditMonitor()
            result = m._load_debounce()
            self.assertEqual(result, {})


# ─── CreditMonitor _log_to_db Tests ───────────────────────────────────────────

class TestCreditMonitorLogToDb(unittest.TestCase):
    """Test _log_to_db() with mocked db module."""

    def test_log_to_db_called(self):
        m = CreditMonitor(kie_api_key="kie-key")
        db_mock = MagicMock()
        with patch.dict('sys.modules', {'db': db_mock}):
            db_mock.log_credit = MagicMock()
            from modules.ops import credit_monitor
            credit_monitor.CreditMonitor._log_to_db(m, "kieai", 50.0)
            db_mock.log_credit.assert_called_once()

    def test_log_to_db_skips_unknown_balance(self):
        m = CreditMonitor()
        db_mock = MagicMock()
        with patch.dict('sys.modules', {'db': db_mock}):
            db_mock.log_credit = MagicMock()
            from modules.ops import credit_monitor
            credit_monitor.CreditMonitor._log_to_db(m, "kieai", UNKNOWN_BALANCE)
            db_mock.log_credit.assert_not_called()


# ─── CreditMonitor run_daemon Tests ───────────────────────────────────────────

class TestCreditMonitorRunDaemon(unittest.TestCase):
    """Test run_daemon()."""

    @patch.object(CreditMonitor, 'check_balance', return_value=50.0)
    @patch.object(CreditMonitor, 'alert_if_low')
    @patch.object(CreditMonitor, '_load_debounce', return_value={})
    def test_run_daemon_calls_check_all_providers(self, mock_load, mock_alert, mock_check):
        m = CreditMonitor(kie_api_key="kie-key", minimax_api_key="mm-key")
        m._providers = {"kieai": MagicMock(), "minimax": MagicMock()}

        with patch.object(time, 'sleep', side_effect=KeyboardInterrupt):
            try:
                m.run_daemon(interval=300, providers=["kieai", "minimax"])
            except KeyboardInterrupt:
                pass

        # Each provider should be checked once
        self.assertEqual(mock_check.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)