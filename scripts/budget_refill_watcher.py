#!/usr/bin/env python3
"""
scripts/budget_refill_watcher.py — Budget Refill Detection & Auto-Resume Daemon.

Watches for credit refill events and automatically resumes the batch_generate loop.

Usage:
    # Run as a long-lived daemon (polls every 5 minutes by default)
    python scripts/budget_refill_watcher.py

    # Dry-run mode (no Telegram messages, no batch_generate trigger)
    python scripts/budget_refill_watcher.py --dry-run

    # Custom poll interval
    python scripts/budget_refill_watcher.py --interval 600

    # Cron-friendly: single-shot check + exit (for cron-based polling)
    python scripts/budget_refill_watcher.py --once

Cron setup example (every 5 minutes):
    */5 * * * * cd /home/openclaw-personal/.openclaw/workspace-videopipeline && \
        python scripts/budget_refill_watcher.py --once >> /var/log/budget_refill.log 2>&1
"""
import argparse
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("budget_refill_watcher")


def trigger_batch_generate(dry_run: bool = False, skip_credit_check: bool = True):
    """
    Trigger batch_generate.py via subprocess.
    Uses --skip-credit-check since we just confirmed credits are available.
    """
    import subprocess

    cmd = [
        sys.executable, "-m", "scripts.batch_generate",
    ]
    if dry_run:
        cmd.append("--dry-run")
    if skip_credit_check:
        cmd.append("--skip-credit-check")

    logger.info(f"Triggering batch_generate: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout
        )
        if result.returncode == 0:
            logger.info("batch_generate completed successfully")
        else:
            logger.warning(f"batch_generate exited with code {result.returncode}")
            if result.stdout:
                logger.warning(f"stdout: {result.stdout[:500]}")
            if result.stderr:
                logger.warning(f"stderr: {result.stderr[:500]}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("batch_generate timed out after 5 minutes")
        return False
    except Exception as e:
        logger.error(f"Failed to run batch_generate: {e}")
        return False


def send_refill_telegram(provider: str, prev_balance: float, new_balance: float,
                          dry_run: bool = False):
    """Send Telegram notification via message tool."""
    if dry_run:
        logger.info(f"[DRY-RUN] Telegram refill alert: {provider} {prev_balance:.2f} → {new_balance:.2f}")
        return

    try:
        from openclaw_personal_utilities import message
        msg = (
            f"💉 [videopipeline] Credits Restored! "
            f"`{provider}` balance: ${prev_balance:.2f} -> ${new_balance:.2f}. "
            f"Batch generate loop resumed automatically."
        )
        # Channel + topic from credit_monitor constants
        message.send(
            action="send",
            target="-1003736681617",
            message=msg,
            threadId="12147",
        )
        logger.info(f"Sent Telegram refill notification for {provider}")
    except ImportError:
        logger.warning("openclaw_personal_utilities.message not available")
    except Exception as e:
        logger.warning(f"Failed to send Telegram refill notification: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Budget refill watcher — auto-resume batch_generate on credit refill"
    )
    parser.add_argument(
        "--interval", type=int, default=300,
        help="Poll interval in seconds (default: 300 = 5 minutes)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Dry-run mode: log what would happen but don't send Telegram or trigger batch_generate"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Single-shot check: poll once, detect refills, exit (good for cron)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG logging"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        for handler in logging.root.handlers:
            handler.setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")

    logger.info("=" * 60)
    logger.info("BUDGET REFILL WATCHER — Credit Refill Auto-Resume")
    logger.info("=" * 60)
    logger.info(f"  Interval  : {args.interval}s")
    logger.info(f"  Dry run   : {args.dry_run}")
    logger.info(f"  Mode      : {'once' if args.once else 'daemon'}")

    # ── Load API keys from TechnicalConfig ─────────────────────────────────────
    try:
        from modules.pipeline.models import TechnicalConfig
        tech = TechnicalConfig.load()
        kie_key = tech.api_keys.get("kie_ai") or tech.api_keys.get("kieai") or ""
        mm_key  = tech.api_keys.get("minimax") or ""
        ws_key  = tech.api_keys.get("wavespeed") or ""
        logger.info(f"API keys loaded: kieai={'✓' if kie_key else '✗'}, "
                    f"minimax={'✓' if mm_key else '✗'}, wavespeed={'✓' if ws_key else '✗'}")
    except Exception as e:
        logger.error(f"Failed to load TechnicalConfig: {e}")
        logger.info("Hint: set POSTGRES_HOST etc., or check configs/technical/config_technical.yaml")
        sys.exit(1)

    # ── Refill callback ────────────────────────────────────────────────────────
    def on_refill(provider: str, balance: float):
        """Called when a refill is detected. Sends Telegram + triggers batch_generate."""
        # Reload previous balance from state file for the notification
        try:
            from modules.ops.credit_monitor import _load_refill_state, _save_refill_state
            state = _load_refill_state()
            prev = state.get(provider, 0.0)
        except Exception:
            prev = 0.0

        send_refill_telegram(provider, prev, balance, dry_run=args.dry_run)

        if not args.dry_run:
            logger.info(f"Triggering batch_generate after {provider} refill (balance=${balance:.2f})")
            trigger_batch_generate(dry_run=False, skip_credit_check=True)
        else:
            logger.info(f"[DRY-RUN] Would trigger batch_generate after {provider} refill")

    # ── Create CreditMonitor ────────────────────────────────────────────────────
    from modules.ops.credit_monitor import CreditMonitor

    monitor = CreditMonitor(
        kie_api_key=kie_key,
        minimax_api_key=mm_key,
        wavespeed_api_key=ws_key,
        dry_run=args.dry_run,
    )

    # ── Run ───────────────────────────────────────────────────────────────────
    if args.once:
        # Single-shot: poll all providers once, check for refills, exit
        logger.info("Running single-shot refill check...")
        results = monitor.check_all_refill_events()
        refills_detected = [p for p, fired in results.items() if fired]
        if refills_detected:
            logger.info(f"Refill events detected: {refills_detected}")
            for provider in refills_detected:
                on_refill(provider, results.get(provider, 0.0))
        else:
            logger.info("No refill events detected.")
        logger.info("Single-shot check complete.")
    else:
        # Daemon mode: poll continuously
        logger.info(f"Starting refill watcher daemon (interval={args.interval}s)...")
        try:
            monitor.watch_for_refill(
                interval=args.interval,
                on_refill_callback=on_refill,
            )
        except KeyboardInterrupt:
            logger.info("Budget refill watcher stopped by user.")
            sys.exit(0)


if __name__ == "__main__":
    main()
