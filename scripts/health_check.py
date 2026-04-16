#!/usr/bin/python3
"""
health_check.py — Pipeline pre-flight health check.

Validates:
1. API keys (MiniMax, Kie.ai, WaveSpeed, S3) are non-empty
2. Database connectivity (PostgreSQL via db.py)
3. S3 connectivity (MinIO/S3 via boto3)
4. Config file existence and required fields

Exit codes:
  0 — all checks passed
  1 — one or more checks failed (descriptive message printed)

--dry-run mode:
  Skips real DB/S3 connectivity checks (no API calls).
  Only validates config files exist and API keys are non-empty.
  Use this when budget is exhausted or running in dev mode.
"""

import sys
import os
import argparse

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import yaml
import boto3
from sqlalchemy import text
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError, NoCredentialsError

# Import db.py to use its configure() and session
import db as pipeline_db
from db_models import Base  # noqa: F401 — needed for ORM metadata


# ─── Config paths ──────────────────────────────────────────────────────────────

TECHNICAL_CONFIG = "configs/technical/config_technical.yaml"


def _get_channel_config_path(channel_id: str) -> str:
    return f"configs/channels/{channel_id}/config.yaml"


# ─── Check helpers ─────────────────────────────────────────────────────────────

class CheckResult:
    __slots__ = ("name", "ok", "message")

    def __init__(self, name: str, ok: bool, message: str = ""):
        self.name = name
        self.ok = ok
        self.message = message

    def __str__(self):
        status = "✅ PASS" if self.ok else "❌ FAIL"
        return f"{status}  [{self.name}]  {self.message}"


def check_api_keys(config: dict) -> CheckResult:
    """Verify all required API keys are present and non-empty."""
    checks = []
    missing = []

    keys = config.get("api", {}).get("keys", {})
    for key_name in ("wavespeed", "minimax", "kie_ai"):
        value = keys.get(key_name, "")
        if not value or not value.strip():
            missing.append(key_name)
        checks.append(f"  {key_name}: {'✓' if value and value.strip() else '✗ MISSING'}")

    s3_keys = config.get("storage", {}).get("s3", {})
    for key_name in ("access_key", "secret_key"):
        value = s3_keys.get(key_name, "")
        if not value or not value.strip():
            missing.append(f"s3.{key_name}")
        checks.append(f"  s3.{key_name}: {'✓' if value and value.strip() else '✗ MISSING'}")

    if missing:
        return CheckResult("API keys", False, f"Missing: {', '.join(missing)}")
    return CheckResult("API keys", True, "All keys present")


def check_config_files(channel_id: str = "nang_suat_thong_minh") -> CheckResult:
    """Verify technical config and channel config exist with required fields."""
    required_fields = [
        ("api", "keys", "wavespeed"),
        ("api", "keys", "minimax"),
        ("api", "keys", "kie_ai"),
        ("storage", "s3", "endpoint"),
        ("storage", "s3", "bucket"),
        ("storage", "database", "host"),
        ("storage", "database", "name"),
    ]

    if not os.path.exists(TECHNICAL_CONFIG):
        return CheckResult("Config files", False, f"Missing: {TECHNICAL_CONFIG}")

    with open(TECHNICAL_CONFIG) as f:
        config = yaml.safe_load(f)

    missing_fields = []
    for *path, leaf in required_fields:
        cur = config
        try:
            for step in path:
                cur = cur[step]
            val = cur[leaf]
            if val is None or (isinstance(val, str) and not val.strip()):
                missing_fields.append(".".join(path) + "." + leaf)
        except (KeyError, TypeError):
            missing_fields.append(".".join(path + [leaf]))

    if missing_fields:
        return CheckResult(
            "Config files", False,
            f"Missing config fields: {', '.join(missing_fields)}"
        )

    # Check channel config exists
    channel_config_path = _get_channel_config_path(channel_id)
    if not os.path.exists(channel_config_path):
        return CheckResult(
            "Config files", False,
            f"Missing channel config: {channel_config_path}"
        )

    return CheckResult("Config files", True, f"{TECHNICAL_CONFIG} + channel config OK")


def check_database(dry_run: bool = False) -> CheckResult:
    """Verify DB connectivity by running a simple SELECT query."""
    if dry_run:
        return CheckResult("Database", True, "[DRY-RUN] DB check skipped")
    try:
        pipeline_db._ensure_configured()
        with pipeline_db.get_session() as session:
            result = session.execute(text("SELECT 1 AS health_check"))
            row = result.fetchone()
            if row and row[0] == 1:
                return CheckResult("Database", True, "PostgreSQL connection OK")
            return CheckResult("Database", False, f"Unexpected query result: {row}")
    except Exception as e:
        return CheckResult("Database", False, f"Connection failed: {e}")


def check_s3(config: dict, dry_run: bool = False) -> CheckResult:
    """Verify S3/MinIO connectivity by listing buckets or checking a known bucket."""
    if dry_run:
        return CheckResult("S3", True, "[DRY-RUN] S3 check skipped")
    try:
        s3_cfg = config.get("storage", {}).get("s3", {})
        endpoint = s3_cfg.get("endpoint", "")
        access_key = s3_cfg.get("access_key", "")
        secret_key = s3_cfg.get("secret_key", "")
        bucket = s3_cfg.get("bucket", "")

        if not endpoint:
            return CheckResult("S3", False, "S3 endpoint not configured")

        session_cfg = BotoConfig(
            connect_timeout=10,
            read_timeout=15,
            retries={"max_attempts": 2},
        )
        s3 = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        ).client("s3", endpoint_url=endpoint, config=session_cfg)

        # Try head_bucket first (lightweight)
        s3.head_bucket(Bucket=bucket)
        return CheckResult("S3", True, f"Connected to bucket '{bucket}' @ {endpoint}")

    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        return CheckResult("S3", False, f"S3 error ({code}): {e}")
    except NoCredentialsError:
        return CheckResult("S3", False, "No credentials provided")
    except Exception as e:
        return CheckResult("S3", False, f"S3 check failed: {e}")


# ─── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline pre-flight health check")
    parser.add_argument(
        "--channel",
        default="nang_suat_thong_minh",
        help="Channel ID to check (default: nang_suat_thong_minh)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run mode: skip DB/S3 connectivity checks (no real API calls). "
             "Use when budget is exhausted or running in dev mode.",
    )
    parser.add_argument(
        "--check-db",
        action="store_true",
        help="Force-enable DB connectivity check even in dry-run (default: skipped in dry-run).",
    )
    parser.add_argument(
        "--check-s3",
        action="store_true",
        help="Force-enable S3 connectivity check even in dry-run (default: skipped in dry-run).",
    )
    args = parser.parse_args()

    channel_id = args.channel
    dry_run = args.dry_run
    # Allow --check-db / --check-s3 to override dry-run skip
    do_db = not dry_run or args.check_db
    do_s3 = not dry_run or args.check_s3

    print("=" * 60)
    print("  Video Pipeline — Pre-flight Health Check")
    print("=" * 60)
    print(f"  Channel    : {channel_id}")
    print(f"  Dry-run    : {dry_run}")

    results: list[CheckResult] = []

    # ── 1. Config files ──────────────────────────────────────────────
    print("\n[1/4] Checking config files ...")
    result = check_config_files(channel_id=channel_id)
    results.append(result)
    print(result)

    # Load technical config for subsequent checks
    technical_config = {}
    if os.path.exists(TECHNICAL_CONFIG):
        with open(TECHNICAL_CONFIG) as f:
            technical_config = yaml.safe_load(f) or {}

    # ── 2. API keys ──────────────────────────────────────────────────
    print("\n[2/4] Checking API keys ...")
    result = check_api_keys(technical_config)
    results.append(result)
    print(result)

    # ── 3. Database ─────────────────────────────────────────────────
    if do_db:
        print("\n[3/4] Checking database connectivity ...")
        result = check_database(dry_run=False)
    else:
        print("\n[3/4] Checking database connectivity ...")
        result = check_database(dry_run=True)
    results.append(result)
    print(result)

    # ── 4. S3 ───────────────────────────────────────────────────────
    if do_s3:
        print("\n[4/4] Checking S3 connectivity ...")
        result = check_s3(technical_config, dry_run=False)
    else:
        print("\n[4/4] Checking S3 connectivity ...")
        result = check_s3(technical_config, dry_run=True)
    results.append(result)
    print(result)

    # ── Summary ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r.ok)
    failed = [r for r in results if not r.ok]

    if not failed:
        print(f"  ✅ All {passed} checks passed — pipeline is ready to run.")
        print("=" * 60)
        return 0
    else:
        print(f"  ❌ {len(failed)}/{len(results)} checks FAILED:")
        for r in failed:
            print(f"       • [{r.name}] {r.message}")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
