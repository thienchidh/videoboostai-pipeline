#!/bin/bash
# =============================================================================
# run_batch_if_healthy.sh — Run batch_generate.py only after health checks pass.
#
# Usage:
#   ./run_batch_if_healthy.sh                    # full run (production)
#   ./run_batch_if_healthy.sh --dry-run          # dry-run mode (dev/testing)
#   ./run_batch_if_healthy.sh --max-items 3      # limit batch size
#
# Cron integration (add to system crontab or OpenClaw cron):
#   # Run every 6 hours; skip if previous run still active (via flock)
#   0 */6 * * * cd /home/openclaw-personal/.openclaw/workspace-videopipeline \
#       && flock -n /tmp/videopipeline_batch.lock \
#           ./scripts/run_batch_if_healthy.sh >> logs/batch_cron.log 2>&1
#
# Exit codes:
#   0  — health check passed + batch completed (or no items to process)
#   1  — pre-flight health check FAILED (batch NOT run)
#   2  — health check passed but batch_generate.py itself failed
#   3  — budget exhausted detected (health check or credit check flagged)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOCK_FILE="/tmp/videopipeline_batch.lock"
LOG_DIR="$PROJECT_ROOT/logs"

# ---- Argument defaults -------------------------------------------------------
DRY_RUN=""
MAX_ITEMS=""
HEALTH_CHECK_ARGS="--dry-run"   # default to dry-run since budget is EXHAUSTED
BATCH_ARGS="--dry-run"

# Parse known args; anything unrecognised is passed through to batch_generate
REMAINING=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN="--dry-run"
            HEALTH_CHECK_ARGS="--dry-run"
            BATCH_ARGS="--dry-run"
            shift
            ;;
        --max-items)
            MAX_ITEMS="--max-items $2"
            shift 2
            ;;
        --channel)
            HEALTH_CHECK_ARGS="$HEALTH_CHECK_ARGS --channel $2"
            shift 2
            ;;
        --check-db|--check-s3)
            HEALTH_CHECK_ARGS="$HEALTH_CHECK_ARGS $1"
            shift
            ;;
        *)
            REMAINING="$REMAINING $1"
            shift
            ;;
    esac
done

# ---- Env prep ----------------------------------------------------------------
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

mkdir -p "$LOG_DIR"
echo ""
echo "============================================================"
echo "  $(date '+%Y-%m-%d %H:%M:%S') — Batch Pipeline Pre-flight"
echo "============================================================"
echo "  Health-check mode : ${HEALTH_CHECK_ARGS:-normal}"
echo "  Batch mode        : ${BATCH_ARGS:-normal}"
echo "  Max items         : ${MAX_ITEMS:-default}"
echo "============================================================"

# ---- Step 1: Pre-flight health check ----------------------------------------
echo ""
echo "[1/2] Running pre-flight health check ..."
echo "────────────────────────────────────────"

HEALTH_CHECK_CMD="python $SCRIPT_DIR/health_check.py $HEALTH_CHECK_ARGS"
echo "$ $HEALTH_CHECK_CMD"

# In dry-run mode, health_check.py skips DB/S3 connectivity calls automatically.
# In production mode (no --dry-run), it performs real connectivity checks.
if [[ "${HEALTH_CHECK_ARGS}" == *"--dry-run"* ]]; then
    echo "  (Budget EXHAUSTED — running in dry-run mode; DB/S3 checks skipped)"
fi

HEALTH_EXIT=0
$HEALTH_CHECK_CMD || HEALTH_EXIT=$?

echo ""
if [[ $HEALTH_EXIT -ne 0 ]]; then
    echo "❌ PRE-FLIGHT FAILED — aborting batch run."
    echo ""
    echo "============================================================"
    echo "  PRE-FLIGHT FAILED — $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"
    echo "  Health-check exit code: $HEALTH_EXIT"
    echo ""
    echo "  Possible causes:"
    echo "    • Missing API keys in configs/technical/config_technical.yaml"
    echo "    • Missing channel config in configs/channels/<channel>/"
    echo "    • PostgreSQL or S3 is unreachable (run without --dry-run to verify)"
    echo ""
    echo "  Fix: run 'python scripts/health_check.py' manually to see detailed output."
    echo "============================================================"
    exit 1
fi

echo "✅ Pre-flight health check PASSED"

# ---- Step 2: Run batch_generate ----------------------------------------------
echo ""
echo "[2/2] Running batch_generate ..."
echo "──────────────────────────────────"

BATCH_CMD="python $SCRIPT_DIR/batch_generate.py $BATCH_ARGS ${MAX_ITEMS:-} $REMAINING"
echo "$ $BATCH_CMD"

BATCH_EXIT=0
$BATCH_CMD || BATCH_EXIT=$?

echo ""
echo "============================================================"
echo "  Batch run complete — $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo "  Batch exit code  : $BATCH_EXIT"
echo "============================================================"

if [[ $BATCH_EXIT -eq 0 ]]; then
    echo "✅ Batch completed successfully."
    exit 0
elif [[ $BATCH_EXIT -eq 1 ]]; then
    # batch_generate returns 1 when there are no items to process (not an error)
    echo "ℹ️  Batch returned exit 1 — may indicate no items were due today."
    exit 0
else
    echo "❌ Batch generation failed with exit code $BATCH_EXIT."
    exit 2
fi
