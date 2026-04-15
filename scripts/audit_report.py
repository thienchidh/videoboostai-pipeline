#!/usr/bin/env python3
"""
scripts/audit_report.py — Human-readable audit log viewer.

Reads runs/YYYY-MM-DD/{run_id}/audit.json and prints a summary.

Usage:
    python scripts/audit_report.py runs/2026-04-15/12345/
    python scripts/audit_report.py runs/2026-04-15/12345/audit.json
    python scripts/audit_report.py --latest

"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def format_ms(ms: int) -> str:
    if ms is None:
        return "n/a"
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.2f}s"


def format_cost(cost: float) -> str:
    if cost == 0:
        return "$0.00"
    return f"${cost:.4f}"


def print_report(audit_path: Path, verbose: bool = False):
    with open(audit_path, encoding="utf-8") as f:
        audit = json.load(f)

    run_id = audit.get("run_id", "?")
    status = audit.get("status", "?")
    started = audit.get("started_at", "?")
    completed = audit.get("completed_at") or "(still running)"
    total_cost = audit.get("total_cost_usd", 0)
    credits = audit.get("total_credits_spent", {})
    errors = audit.get("errors", [])
    steps = audit.get("steps", [])

    # ── Header ────────────────────────────────────────────────
    print()
    print(f"{'═' * 60}")
    status_icon = {"success": "✅", "failed": "❌", "partial": "⚠️", "running": "⏳"}.get(status, "❓")
    print(f"  {status_icon} AUDIT REPORT — run {run_id}")
    print(f"{'═' * 60}")
    print(f"  Status:    {status.upper()}")
    print(f"  Started:   {started}")
    print(f"  Finished:  {completed}")

    # ── Duration ───────────────────────────────────────────────
    if started != "?" and completed != "(still running)":
        try:
            s = datetime.fromisoformat(started.replace("Z", "+00:00"))
            e = datetime.fromisoformat(completed.replace("Z", "+00:00"))
            dur_sec = (e - s).total_seconds()
            print(f"  Duration:  {dur_sec:.1f}s ({format_ms(int(dur_sec * 1000))})")
        except Exception:
            pass

    print(f"  Total cost: {format_cost(total_cost)}")
    if credits:
        print(f"  Credits by provider:")
        for prov, cost in sorted(credits.items()):
            print(f"    {prov}: {format_cost(cost)}")

    # ── Steps ─────────────────────────────────────────────────
    print()
    print(f"{'─' * 60}")
    print(f"  STEPS")
    print(f"{'─' * 60}")

    if not steps:
        print(f"  (no steps recorded)")
    else:
        # Group by step number
        step_rows = []
        for s in steps:
            step = s.get("step")
            name = s.get("name", "?")
            scene_id = s.get("scene_id")
            sc = f"scene_{scene_id}" if scene_id is not None else "—"
            dur = format_ms(s.get("duration_ms"))
            st = s.get("status", "?")
            errs = s.get("errors", [])
            apis = s.get("api_calls", [])

            st_icon = {"success": "✅", "failed": "❌", "skipped": "⏭️", "running": "⏳", "partial": "⚠️"}.get(st, "❓")
            row = f"  {st_icon} [{step:>2}] {name:<20} {sc:<12} {dur:>10}"
            step_rows.append((step, row, st, errs, apis))

        for step, row, st, errs, apis in step_rows:
            print(row)
            if verbose or errs:
                for e in errs:
                    print(f"       🔥 {e.get('type','Error')}: {e.get('message','?')}")
                    if verbose and e.get("traceback"):
                        for line in e["traceback"].strip().split("\n")[-3:]:
                            print(f"          {line.strip()}")
            if verbose and apis:
                for api in apis:
                    cost_str = format_cost(api.get("cost_usd", 0))
                    print(f"       🔗 {api.get('provider','?')}/{api.get('model','?')} "
                          f"latency={format_ms(int(api.get('latency_ms', 0)))} cost={cost_str}")

    # ── Top-level errors ───────────────────────────────────────
    if errors:
        print()
        print(f"{'─' * 60}")
        print(f"  TOP-LEVEL ERRORS ({len(errors)})")
        print(f"{'─' * 60}")
        for i, e in enumerate(errors, 1):
            ctx = e.get("context", "")
            print(f"  {i}. [{e.get('type','Error')}] {e.get('message','?')}"
                  + (f" (in {ctx})" if ctx else ""))
            if verbose and e.get("traceback"):
                for line in e["traceback"].strip().split("\n")[-5:]:
                    print(f"       {line.strip()}")

    print()
    print(f"  Full audit: {audit_path}")
    print()


def find_latest_run(runs_dir: Path) -> Path:
    """Find the most recent audit.json under runs_dir."""
    audit_files = sorted(runs_dir.glob("*/audit.json"), reverse=True)
    if not audit_files:
        raise FileNotFoundError(f"No audit.json found under {runs_dir}")
    return audit_files[0]


def main():
    parser = argparse.ArgumentParser(description="Audit log viewer")
    parser.add_argument("path", nargs="?", help="Path to run directory or audit.json file")
    parser.add_argument("--latest", action="store_true", help="Show latest audit log")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show tracebacks and API call details")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    runs_dir = project_root / "runs"

    if args.latest:
        audit_path = find_latest_run(runs_dir)
    elif args.path:
        p = Path(args.path)
        if p.is_dir():
            audit_path = p / "audit.json"
        else:
            audit_path = p
    else:
        # Default: latest
        audit_path = find_latest_run(runs_dir)

    audit_path = audit_path.resolve()
    if not audit_path.exists():
        print(f"❌ File not found: {audit_path}", file=sys.stderr)
        sys.exit(1)

    try:
        print_report(audit_path, verbose=args.verbose)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in {audit_path}: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error reading {audit_path}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
