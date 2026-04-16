#!/usr/bin/python3
"""
credit_monitor.py - Credit Usage Tracking & Real-Time Alerting System.

Supports:
  - Kie.ai  : GET /account/balance via KieAIClient
  - MiniMax : account info API
  - WaveSpeed: account API

Polls providers, logs to DB (credits_log), and sends Telegram alerts
when balance drops below configurable threshold per provider.
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.ops.credit_monitor import CreditMonitor
from modules.ops.db import init_db

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    parser = argparse.ArgumentParser(description="Credit Monitor Daemon")
    parser.add_argument("--check-once", action="store_true",
                        help="Check balances once (for cron), then exit")
    parser.add_argument("--daemon", action="store_true",
                        help="Run continuously as a daemon")
    parser.add_argument("--poll-interval", type=int, default=300,
                        help="Poll interval in seconds (default: 300 = 5 min)")
    parser.add_argument("--providers", nargs="+",
                        default=["kieai", "minimax", "wavespeed"],
                        help="Providers to check (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check and log but do NOT send Telegram alerts")
    args = parser.parse_args()

    # Initialise DB
    try:
        init_db()
        logger.info("Database initialized OK")
    except Exception as e:
        logger.warning(f"DB init failed (may already be initialized): {e}")

    # Resolve API keys from env / DB credentials store
    kie_api_key = os.environ.get("KIE_AI_API_KEY", "")
    minimax_api_key = os.environ.get("MINIMAX_API_KEY", "")
    wavespeed_api_key = os.environ.get("WAVESPEED_API_KEY", "")

    monitor = CreditMonitor(
        kie_api_key=kie_api_key,
        minimax_api_key=minimax_api_key,
        wavespeed_api_key=wavespeed_api_key,
        dry_run=args.dry_run,
    )

    if args.check_once:
        logger.info("Running check-once mode")
        results = monitor.check_all()
        for provider, balance in results.items():
            logger.info(f"  {provider}: {balance}")
        return

    if args.daemon:
        logger.info(f"Starting daemon mode (poll every {args.poll_interval}s)")
        monitor.run_daemon(interval=args.poll_interval, providers=args.providers)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
