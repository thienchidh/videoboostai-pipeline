#!/usr/bin/env python3
"""
scripts/analytics.py — Cost analytics & ROI dashboard

Provides:
  - per_video_cost(run_id)        — aggregated cost per video run
  - per_provider_cost(start, end)  — cost breakdown by provider over date range
  - per_platform_cost()            — Facebook vs TikTok spend
  - cost_per_video_trend(days)     — cost trend over last N days
  - generate_report(format)        — formatted text report + JSON export
  - /cost-report Telegram command — sends summary to Telegram topic

Usage:
  python scripts/analytics.py                    # full report to stdout
  python scripts/analytics.py --video RUN_ID      # single video cost
  python scripts/analytics.py --provider 7         # last 7 days by provider
  python scripts/analytics.py --platform          # FB vs TikTok
  python scripts/analytics.py --trend 30          # 30-day cost trend
  python scripts/analytics.py --telegram           # send to Telegram topic
  python scripts/analytics.py --json               # JSON export to stdout
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import db

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ─── Telegram Topic ID for cost reports ──────────────────────────────────────
TELEGRAM_TOPIC_ID = "-1002381931352"


def fmt_currency(amount: float) -> str:
    return f"${amount:.4f}"


def fmt_large(amount: float) -> str:
    """Format currency for human readability (no trailing zeros beyond cents)."""
    return f"${amount:.2f}"


# ─── Analytics API ─────────────────────────────────────────────────────────────

def per_video_cost_report(run_id: int) -> dict:
    """Return formatted cost report for a single video run."""
    info = db.per_video_cost(run_id)
    lines = [f"=== Cost Report: Video Run #{info['run_id']} ==="]
    lines.append(f"  Total: {fmt_large(info['total_usd'])}")
    if info['by_provider']:
        lines.append("  By Provider:")
        for prov, cost in sorted(info['by_provider'].items(), key=lambda x: -x[1]):
            lines.append(f"    {prov}: {fmt_large(cost)}")
    if info['by_operation']:
        lines.append("  By Operation:")
        for op, cost in sorted(info['by_operation'].items(), key=lambda x: -x[1]):
            lines.append(f"    {op}: {fmt_large(cost)}")
    return {"text": "\n".join(lines), "data": info}


def per_provider_report(days: int = 30) -> dict:
    """Return formatted cost report by provider over last N days."""
    end = date.today()
    start = end - timedelta(days=days - 1)
    info = db.per_provider_cost(start_date=start, end_date=end)
    lines = [f"=== Provider Cost Report ({info['period']['start']} → {info['period']['end']}) ==="]
    lines.append(f"  Total: {fmt_large(info['total_usd'])}")
    for prov, prov_info in info['providers'].items():
        lines.append(f"  [{prov}] {fmt_large(prov_info['total_usd'])} ({prov_info['count']} calls)")
        for op, op_info in prov_info['operations'].items():
            lines.append(f"    {op}: {fmt_large(op_info['cost_usd'])} ({op_info['count']} calls)")
    return {"text": "\n".join(lines), "data": info}


def per_platform_report() -> dict:
    """Return formatted Facebook vs TikTok spend report."""
    info = db.per_platform_cost()
    lines = ["=== Platform Cost Report ==="]
    lines.append(f"  Total: {fmt_large(info['total_usd'])}")
    for plat, plat_info in info['platforms'].items():
        lines.append(f"  {plat}: {fmt_large(plat_info['total_usd'])} ({plat_info['post_count']} posts)")
    if info.get('by_provider'):
        lines.append("\n  Platform costs by provider:")
        for plat, providers in info['by_provider'].items():
            for prov, prov_info in providers.items():
                lines.append(f"    {plat}/{prov}: {fmt_large(prov_info['cost_usd'])} ({prov_info['count']} calls)")
    return {"text": "\n".join(lines), "data": info}


def cost_trend_report(days: int = 30) -> dict:
    """Return daily cost trend over last N days."""
    end = date.today()
    start = end - timedelta(days=days - 1)
    # Materialize rows inside the session block to avoid DetachedInstanceError
    with db.get_session() as session:
        from db_models import CostLog
        from datetime import datetime
        start_dt = datetime.combine(start, datetime.min.time())
        end_dt = datetime.combine(end, datetime.max.time())
        rows = session.query(CostLog).filter(
            CostLog.created_at >= start_dt,
            CostLog.created_at <= end_dt,
        ).order_by(CostLog.created_at).all()
        # Extract needed fields while still attached to session
        row_data = [
            {"created_at": row.created_at, "cost_usd": row.cost_usd}
            for row in rows
        ]

    daily: dict[str, float] = {}
    for row in row_data:
        day = str(row["created_at"].date())
        cost = float(row["cost_usd"]) if row["cost_usd"] else 0.0
        daily[day] = daily.get(day, 0.0) + cost

    if not daily:
        return {"text": "No cost data in the last 30 days.", "data": {"trend": {}}}

    lines = [f"=== Cost Per Video Trend (last {days} days) ==="]
    for day, cost in sorted(daily.items()):
        lines.append(f"  {day}: {fmt_large(cost)}")
    avg = sum(daily.values()) / len(daily) if daily else 0
    lines.append(f"\n  Daily avg: {fmt_large(avg)}")
    lines.append(f"  Total: {fmt_large(sum(daily.values()))}")

    return {"text": "\n".join(lines), "data": {"trend": daily, "avg_daily": avg, "total": sum(daily.values())}}


def full_report() -> dict:
    """Generate full cost report: 30-day provider + platform + recent runs."""
    end = date.today()
    start = end - timedelta(days=29)

    # Provider summary
    prov_info = db.per_provider_cost(start_date=start, end_date=end)

    # Platform breakdown
    plat_info = db.per_platform_cost()

    # Recent runs
    with db.get_session() as session:
        from db_models import VideoRun
        runs = session.query(VideoRun).filter(
            VideoRun.status.in_(["completed", "failed"])
        ).order_by(VideoRun.started_at.desc()).limit(10).all()
        run_rows = []
        for r in runs:
            cost = r.total_cost / 100.0 if r.total_cost else 0.0
            run_rows.append({
                "id": r.id, "status": r.status, "cost": cost,
                "scenes": f"{r.completed_scenes or 0}/{r.total_scenes or 0}",
                "started": str(r.started_at.date()) if r.started_at else "N/A",
            })

    # Build text
    lines = [
        "========================================",
        "   VIDEO PIPELINE COST REPORT",
        f"   Period: {start} → {end}",
        "========================================",
        f"\nTotal spend (30d): {fmt_large(prov_info['total_usd'])}",
        "\nBy Provider:",
    ]
    for prov, pdata in sorted(prov_info['providers'].items(), key=lambda x: -x[1]['total_usd']):
        lines.append(f"  {prov:<28} {fmt_large(pdata['total_usd']):>10}  ({pdata['count']} calls)")

    lines.append(f"\nBy Platform (all time):")
    for plat, pdata in plat_info['platforms'].items():
        lines.append(f"  {plat:<28} {fmt_large(pdata['total_usd']):>10}  ({pdata['post_count']} posts)")

    lines.append("\nRecent Video Runs:")
    if not run_rows:
        lines.append("  No completed runs yet.")
    else:
        for r in run_rows:
            lines.append(f"  Run #{r['id']:<5} status={r['status']:<12} cost={fmt_large(r['cost']):>10}  scenes={r['scenes']}  started={r['started']}")

    lines.append("\n========================================")

    return {
        "text": "\n".join(lines),
        "data": {
            "provider": prov_info,
            "platform": plat_info,
            "recent_runs": run_rows,
        },
    }


def generate_report(fmt: str = "text") -> dict:
    """Generate full report. fmt='text' returns text, fmt='json' returns dict."""
    report = full_report()
    if fmt == "json":
        return report["data"]
    return report


# ─── Telegram Command ──────────────────────────────────────────────────────────

def send_telegram_report(topic_id: str = TELEGRAM_TOPIC_ID) -> bool:
    """Send cost report to Telegram topic. Returns True on success."""
    report = full_report()
    text = report["text"]

    # Telegram message limit is 4096 chars; split if needed
    MAX_MSG = 4000
    if len(text) <= MAX_MSG:
        parts = [text]
    else:
        parts = []
        current = []
        current_len = 0
        for line in text.split("\n"):
            line_len = len(line) + 1
            if current_len + line_len > MAX_MSG:
                parts.append("\n".join(current))
                current = [line]
                current_len = line_len
            else:
                current.append(line)
                current_len += line_len
        if current:
            parts.append("\n".join(current))

    try:
        from modules.pipeline.models import TechnicalConfig
        tech = TechnicalConfig.load()
        bot_token = tech.telegram.get("bot_token")
        chat_id = tech.telegram.get("chat_id")
        if not bot_token or not chat_id:
            logger.warning("Telegram not configured; printing message instead")
            print(text)
            return False
        import urllib.request, urllib.parse
        for i, part in enumerate(parts):
            encoded = urllib.parse.quote_plus(part)
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={chat_id}&text={encoded}&parse_mode=Markdown"
            with urllib.request.urlopen(url, timeout=10) as resp:
                if resp.status != 200:
                    logger.warning(f"Telegram returned {resp.status}")
                    return False
        logger.info(f"Sent {len(parts)} Telegram message(s)")
        return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Cost analytics & ROI report")
    parser.add_argument("--video", type=int, help="Show cost for a specific video run ID")
    parser.add_argument("--provider", type=int, default=None,
                        help="Show provider breakdown for last N days (default: 30)")
    parser.add_argument("--platform", action="store_true", help="Show Facebook vs TikTok spend")
    parser.add_argument("--trend", type=int, default=None,
                        help="Show cost trend for last N days")
    parser.add_argument("--telegram", action="store_true",
                        help="Send report to Telegram topic (default: -1002381931352)")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of text")
    args = parser.parse_args()

    # Init DB
    try:
        db.init_db()
    except Exception as e:
        logger.warning(f"DB init warning: {e}")

    if args.video:
        result = per_video_cost_report(args.video)
    elif args.platform:
        result = per_platform_report()
    elif args.trend:
        result = cost_trend_report(args.trend)
    elif args.provider is not None:
        result = per_provider_report(args.provider)
    elif args.telegram:
        ok = send_telegram_report()
        print("OK" if ok else "FAILED")
        return
    else:
        result = full_report()

    if args.json:
        print(json.dumps(result.get("data", {}), indent=2, default=str))
    else:
        print(result["text"])


if __name__ == "__main__":
    main()
