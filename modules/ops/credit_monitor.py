#!/usr/bin/env python3
"""
modules/ops/credit_monitor.py — Credit Usage Tracking & Real-Time Alerting System.

Classes:
  CreditMonitor — polls Kie.ai, MiniMax, WaveSpeed balance APIs, logs to DB,
                  and sends Telegram alerts when balance drops below threshold.

Usage:
  from modules.ops.credit_monitor import CreditMonitor
  monitor = CreditMonitor(kie_api_key="...", minimax_api_key="...", wavespeed_api_key="...")
  results = monitor.check_all()          # {'kieai': 123.45, 'minimax': 678.90, ...}
  monitor.run_daemon(interval=300)       # continuous mode
"""
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import requests

PROJECT_ROOT = Path(__file__).parent.parent.parent

logger = logging.getLogger(__name__)


# ─── Constants ────────────────────────────────────────────────────────────────────

DEBOUNCE_FILE = Path(__file__).parent.parent.parent / ".tasks" / ".last_credit_alert"
DEFAULT_THRESHOLDS = {
    "kieai": 0.20,       # 20% remaining
    "minimax": 0.20,
    "wavespeed": 0.20,
}
# Sentinel for providers that don't expose a balance API
UNKNOWN_BALANCE = -1.0


# ─── Provider Interface ───────────────────────────────────────────────────────

class CreditBalanceProvider(ABC):
    """Abstract base for a credit-balance provider."""

    @abstractmethod
    def get_balance(self) -> float:
        """Return current credit balance (float), or UNKNOWN_BALANCE if unavailable."""
        raise NotImplementedError


# ─── Kie.ai ───────────────────────────────────────────────────────────────────

class KieAIBalanceProvider(CreditBalanceProvider):
    """Query Kie.ai /account/balance endpoint."""

    BASE_URL = "https://api.kie.ai/api/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {api_key}"
        self._session.headers["Content-Type"] = "application/json"

    def get_balance(self) -> float:
        url = f"{self.BASE_URL}/account/balance"
        try:
            resp = self._session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                # Response shape: {"code":200,"data":{"balance": "123.45"}} or similar
                balance = data.get("data", {}).get("balance")
                if balance is not None:
                    return float(balance)
            logger.warning(f"Kie.ai balance check failed: {resp.status_code} {resp.text[:200]}")
            return UNKNOWN_BALANCE
        except Exception as e:
            logger.warning(f"Kie.ai balance error: {e}")
            return UNKNOWN_BALANCE


# ─── MiniMax ───────────────────────────────────────────────────────────────────

class MiniMaxBalanceProvider(CreditBalanceProvider):
    """Query MiniMax account info / groups balance endpoint."""

    # MiniMax group balance endpoint
    BALANCE_URL = "https://api.minimax.io/anthropic/v1/messages"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_balance(self) -> float:
        # Try MiniMax account info endpoint
        try:
            resp = requests.get(
                "https://api.minimax.io/api/v1/me",
                headers={"x-api-key": self.api_key},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                balance = data.get("data", {}).get("balance") or data.get("balance")
                if balance is not None:
                    return float(balance)
        except Exception as e:
            logger.debug(f"MiniMax /me balance error: {e}")

        # Fallback: try quota endpoint
        try:
            resp = requests.get(
                "https://api.minimax.io/api/v1/quota",
                headers={"x-api-key": self.api_key},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                balance = (data.get("data") or data or {}).get("balance") or \
                          (data.get("data") or data or {}).get("remaining")
                if balance is not None:
                    return float(balance)
        except Exception as e:
            logger.debug(f"MiniMax quota balance error: {e}")

        logger.warning("MiniMax balance could not be determined, using sentinel")
        return UNKNOWN_BALANCE


# ─── WaveSpeed ────────────────────────────────────────────────────────────────

class WaveSpeedBalanceProvider(CreditBalanceProvider):
    """Query WaveSpeed account balance endpoint."""

    BASE_URL = "https://api.wavespeed.ai/api/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {api_key}"
        self._session.headers["Content-Type"] = "application/json"

    def get_balance(self) -> float:
        url = f"{self.BASE_URL}/account/balance"
        try:
            resp = self._session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                balance = (data.get("data") or data or {}).get("balance") or \
                          (data.get("data") or data or {}).get("credits")
                if balance is not None:
                    return float(balance)
            logger.warning(f"WaveSpeed balance check failed: {resp.status_code} {resp.text[:200]}")
            return UNKNOWN_BALANCE
        except Exception as e:
            logger.warning(f"WaveSpeed balance error: {e}")
            return UNKNOWN_BALANCE


# ─── Refill Detection ───────────────────────────────────────────────────────

# Balance (USD) at which a provider is considered "resumed" after being exhausted.
# Set low enough to catch real refills, high enough to avoid noise.
REFILL_RESUME_THRESHOLD = 5.0   # $5 minimum to trigger resume notification

# File storing previous-balance snapshot for refill detection
_REFILL_STATE_FILE = Path(__file__).parent.parent.parent / ".tasks" / ".credit_refill_state"


def _load_refill_state() -> Dict[str, float]:
    """Load previous-balance snapshot from disk."""
    _REFILL_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _REFILL_STATE_FILE.exists():
        try:
            return json.loads(_REFILL_STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_refill_state(state: Dict[str, float]):
    """Persist previous-balance snapshot to disk."""
    try:
        _REFILL_STATE_FILE.write_text(json.dumps(state))
    except Exception as e:
        logger.warning(f"Failed to save refill state: {e}")


# ─── CreditMonitor ────────────────────────────────────────────────────────────

class CreditMonitor:
    """
    Poll provider balance APIs, log to DB credits_log, and send Telegram
    alerts when any provider drops below its configured threshold.

    Attributes:
        thresholds: dict[str, float] — fraction of initial balance considered low.
                    Default 0.20 (20%%).
    """

    def __init__(self,
                 kie_api_key: str = "",
                 minimax_api_key: str = "",
                 wavespeed_api_key: str = "",
                 thresholds: Optional[Dict[str, float]] = None,
                 dry_run: bool = False):
        self.dry_run = dry_run
        self.thresholds = thresholds or dict(DEFAULT_THRESHOLDS)

        self._providers: Dict[str, CreditBalanceProvider] = {}
        if kie_api_key:
            self._providers["kieai"] = KieAIBalanceProvider(kie_api_key)
        if minimax_api_key:
            self._providers["minimax"] = MiniMaxBalanceProvider(minimax_api_key)
        if wavespeed_api_key:
            self._providers["wavespeed"] = WaveSpeedBalanceProvider(wavespeed_api_key)

        # Load debounce state
        self._last_alert: Dict[str, float] = self._load_debounce()

    # ─── Public API ────────────────────────────────────────────────────────────

    def check_balance(self, provider: str) -> float:
        """
        Call provider's balance API and return balance.
        Logs result to DB credits_log. Returns UNKNOWN_BALANCE on failure.
        """
        if provider not in self._providers:
            logger.warning(f"No provider '{provider}' configured")
            return UNKNOWN_BALANCE

        balance = self._providers[provider].get_balance()

        # Log to DB
        try:
            self._log_to_db(provider, balance)
        except Exception as e:
            logger.warning(f"Failed to log credit to DB: {e}")

        return balance

    def check_all(self) -> Dict[str, float]:
        """Check all configured providers, return {provider: balance}."""
        return {provider: self.check_balance(provider)
                for provider in self._providers}

    def alert_if_low(self, provider: str, balance: float, initial_balance: float = 1000.0):
        """
        Check if balance is below threshold. If so, send Telegram alert (debounced).
        Skipped entirely if balance == UNKNOWN_BALANCE.
        """
        if balance == UNKNOWN_BALANCE:
            return

        threshold = self.thresholds.get(provider, DEFAULT_THRESHOLDS.get(provider, 0.20))
        remaining_pct = balance / initial_balance if initial_balance > 0 else 0.0

        if remaining_pct >= threshold:
            return

        # Debounce: max 1 alert per provider per 30 min
        last_ts = self._last_alert.get(provider, 0.0)
        if time.time() - last_ts < 1800:   # 30 minutes
            logger.debug(f"Alert debounced for {provider} (last: {last_ts})")
            return

        self._send_alert(provider, balance, remaining_pct)
        self._last_alert[provider] = time.time()
        self._save_debounce()

    # ─── Refill Detection ──────────────────────────────────────────────────────

    def check_refill_event(self, provider: str, current_balance: float) -> bool:
        """
        Detect a credit refill event for a provider.

        A refill event fires when a provider's balance transitions from
        exhausted/near-zero to above REFILL_RESUME_THRESHOLD.

        Returns True if a refill is detected, False otherwise.
        Logs the new balance to DB and persists state.
        """
        if current_balance == UNKNOWN_BALANCE:
            return False

        previous = _load_refill_state()
        prev_balance = previous.get(provider, -1.0)  # -1 = never seen

        # Only fire when: we had a real reading AND balance rose above threshold
        was_exhausted = (prev_balance >= 0 and prev_balance < REFILL_RESUME_THRESHOLD)
        is_resumed = (current_balance >= REFILL_RESUME_THRESHOLD)

        if was_exhausted and is_resumed:
            logger.info(f"💉 [{provider}] REFILL DETECTED: {prev_balance:.2f} → {current_balance:.2f}")
            self._notify_refill(provider, prev_balance, current_balance)
            # Update state to prevent re-triggering
            previous[provider] = current_balance
            _save_refill_state(previous)
            return True

        # Update persisted state regardless
        previous[provider] = current_balance
        _save_refill_state(previous)
        return False

    def check_all_refill_events(self) -> Dict[str, bool]:
        """
        Check all configured providers for refill events.

        Returns dict of {provider: True if refill detected}.
        Logs new balances to DB and sends Telegram notification on first refill.
        """
        results: Dict[str, bool] = {}
        for provider in self._providers:
            balance = self.check_balance(provider)
            results[provider] = self.check_refill_event(provider, balance)
        return results

    def watch_for_refill(self,
                        interval: int = 300,
                        on_refill_callback=None,
                        providers: Optional[list] = None):
        """
        Long-running daemon that polls for credit refills and optionally
        triggers a callback when any provider is refilled.

        Args:
            interval: polling interval in seconds (default 300 = 5 min)
            on_refill_callback: callable(provider, balance) invoked on each refill.
                                If None, uses default: trigger_batch_generate().
            providers: list of provider names to watch (default: all configured)

        Usage:
            monitor.watch_for_refill(
                interval=300,
                on_refill_callback=lambda p, b: print(f"Refill: {p}@{b}")
            )
        """
        import importlib

        def default_callback(provider: str, balance: float):
            """Default: trigger batch_generate via subprocess."""
            logger.info(f"Triggering batch_generate after {provider} refill...")
            try:
                import subprocess, sys
                # Run batch_generate in a subprocess; skip credit check since we just refilled
                proc = subprocess.Popen(
                    [sys.executable, "-m", "scripts.batch_generate",
                     "--skip-credit-check", "--dry-run"],
                    cwd=PROJECT_ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                stdout, _ = proc.communicate(timeout=120)
                logger.info(f"batch_generate output:\n{stdout.decode()[:500]}")
            except Exception as e:
                logger.error(f"Failed to trigger batch_generate: {e}")

        callback = on_refill_callback or default_callback
        providers = providers or list(self._providers.keys())

        logger.info(f"Budget refill watcher started (interval={interval}s, providers={providers})")
        while True:
            for provider in providers:
                try:
                    balance = self.check_balance(provider)
                    logger.debug(f"[{provider}] balance: {balance}")
                    if self.check_refill_event(provider, balance):
                        logger.info(f"✅ Refill detected for {provider} — invoking callback")
                        try:
                            callback(provider, balance)
                        except Exception as cb_err:
                            logger.error(f"Refill callback error: {cb_err}")
                except Exception as e:
                    logger.warning(f"Error checking {provider}: {e}")
            time.sleep(interval)

    # ─── Telegram Refill Notification ──────────────────────────────────────────

    def _notify_refill(self, provider: str, prev_balance: float, new_balance: float):
        """Send Telegram notification when credits are refilled."""
        if self.dry_run:
            logger.info(
                f"[DRY-RUN] Would notify refill: {provider} "
                f"({prev_balance:.2f} → {new_balance:.2f})"
            )
            return

        import urllib.request, urllib.parse
        msg = (
            f"💉 [videopipeline] Credits Restored!\n"
            f"`{provider}` balance: ${prev_balance:.2f} -> ${new_balance:.2f}\n"
            f"Batch generate loop resumed automatically."
        )
        try:
            encoded = urllib.parse.quote_plus(msg)
            # Try message tool first (async, proper Telegram integration)
            try:
                from openclaw_personal_utilities import message
                message.send(
                    action="send",
                    target=self.TELEGRAM_CHANNEL,
                    message=msg,
                    threadId=self.TELEGRAM_TOPIC_ID,
                )
                logger.info(f"Refill Telegram notification sent for {provider}")
            except ImportError:
                # Fallback: direct HTTP to Telegram bot
                tech_path = PROJECT_ROOT / "configs" / "technical" / "config_technical.yaml"
                if tech_path.exists():
                    import yaml
                    data = yaml.safe_load(tech_path.read_text())
                    bot_token = (
                        data.get("telegram", {})
                        .get("bot_token")
                    )
                    chat_id = data["telegram"]["chat_id"]
                    if bot_token and chat_id:
                        url = (
                            f"https://api.telegram.org/bot{bot_token}"
                            f"/sendMessage?chat_id={chat_id}"
                            f"&text={encoded}&parse_mode=Markdown"
                        )
                        with urllib.request.urlopen(url, timeout=10) as resp:
                            if resp.status == 200:
                                logger.info(f"Refill Telegram notification sent for {provider}")
                                return
            logger.warning("Telegram not configured for refill notification")
        except Exception as e:
            logger.warning(f"Failed to send refill Telegram notification: {e}")

    def run_daemon(self, interval: int = 300, providers: Optional[list] = None,
                   check_refill: bool = True):
        """
        Continuously poll providers every `interval` seconds.
        Logs to DB on each check, sends low-credit alerts on threshold breach,
        and detects refill events (if check_refill=True).
        """
        providers = providers or list(self._providers.keys())
        logger.info(f"CreditMonitor daemon started (interval={interval}s, check_refill={check_refill})")
        while True:
            for provider in providers:
                balance = self.check_balance(provider)
                logger.info(f"[{provider}] balance: {balance}")
                if not self.dry_run and balance != UNKNOWN_BALANCE:
                    self.alert_if_low(provider, balance)
                    if check_refill:
                        self.check_refill_event(provider, balance)
            time.sleep(interval)

    # ─── DB Logging ────────────────────────────────────────────────────────────

    def _log_to_db(self, provider: str, balance: float):
        """Log a balance check to credits_log table."""
        # Import here to avoid circular imports at module load time
        import db as _db
        if balance != UNKNOWN_BALANCE:
            _db.log_credit(
                provider=provider,
                amount=0,               # 0 = balance check, not a deduction
                balance_after=balance,
                reason="balance_check",
            )
            logger.debug(f"Logged {provider} balance {balance} to DB")

    # ─── Telegram Alert ────────────────────────────────────────────────────────

    # Telegram channel topic routing (from HEARTBEAT.md)
    TELEGRAM_CHANNEL = "-1003736681617"
    TELEGRAM_TOPIC_ID = "12147"

    def _send_alert(self, provider: str, balance: float, remaining_pct: float):
        """Send low-credit Telegram alert via message tool to channel topic."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would alert: {provider} credits low: {remaining_pct*100:.1f}% ({balance})")
            return

        try:
            from openclaw_personal_utilities import message
            message.send(
                action="send",
                target=self.TELEGRAM_CHANNEL,
                message=f"⚠️ [videopipeline] {provider} credits low: {remaining_pct*100:.1f}% ({balance:.2f})",
                threadId=self.TELEGRAM_TOPIC_ID,
            )
            logger.info(f"Sent Telegram alert for {provider} (balance={balance:.2f}) to topic {self.TELEGRAM_TOPIC_ID}")
        except ImportError:
            logger.warning("openclaw_personal_utilities.message not available; alert not sent")
        except Exception as e:
            logger.warning(f"Failed to send Telegram alert: {e}")

    # ─── Debounce Persistence ──────────────────────────────────────────────────

    def _debounce_file(self) -> Path:
        DEBOUNCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        return DEBOUNCE_FILE

    def _load_debounce(self) -> Dict[str, float]:
        path = self._debounce_file()
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
        return {}

    def _save_debounce(self):
        path = self._debounce_file()
        try:
            path.write_text(json.dumps(self._last_alert))
        except Exception as e:
            logger.warning(f"Failed to save debounce state: {e}")


# ─── DB helper ─────────────────────────────────────────────────────────────────

def get_credit_balance(provider: str) -> float:
    """
    Get the most recent known credit balance for a provider from DB.
    Returns 0.0 if no record found.
    """
    import db as _db
    return _db.get_credits_balance(provider)


# ─── Quick smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)

    kie_key = os.environ.get("KIE_AI_API_KEY", "")
    mm_key  = os.environ.get("MINIMAX_API_KEY", "")
    ws_key  = os.environ.get("WAVESPEED_API_KEY", "")

    monitor = CreditMonitor(kie_api_key=kie_key, minimax_api_key=mm_key,
                            wavespeed_api_key=ws_key, dry_run=True)
    results = monitor.check_all()
    for p, b in results.items():
        print(f"  {p}: {b}")
