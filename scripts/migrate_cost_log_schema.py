#!/usr/bin/env python3
"""
scripts/migrate_cost_log_schema.py — Fix cost_log column names + cost_usd storage

DB columns (old): video_run_id, provider, operation_type, units_used, cost_usd(FLOAT)
Model wants:      run_id,       provider, operation,    units,     cost_usd(INTEGER cents)

This migration:
  1. Renames columns to match the SQLAlchemy CostLog model
  2. Converts cost_usd from float dollars → integer cents
  3. Adds NOT NULL constraints + indexes
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import db
from sqlalchemy import text


def migrate():
    db.init_db()
    with db.get_session() as s:
        # ── Step 1: check current schema ──────────────────────────────────────
        result = s.execute(text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'cost_log'
            ORDER BY ordinal_position
        """))
        cols = {r[0]: r[1] for r in result.fetchall()}
        print("Current cost_log schema:", cols)

        if 'run_id' in cols and 'operation' in cols:
            print("Schema already migrated. Nothing to do.")
            return

        # ── Step 2: add new columns (run_id, operation, units) ────────────────
        print("\nAdding new columns...")
        if 'run_id' not in cols:
            s.execute(text("ALTER TABLE cost_log ADD COLUMN run_id INTEGER"))
        if 'operation' not in cols:
            s.execute(text("ALTER TABLE cost_log ADD COLUMN operation VARCHAR(50)"))
        if 'units' not in cols:
            s.execute(text("ALTER TABLE cost_log ADD COLUMN units INTEGER DEFAULT 1"))

        # ── Step 3: backfill new columns from old ones ─────────────────────────
        print("Backfilling run_id, operation, units...")
        s.execute(text("""
            UPDATE cost_log
            SET run_id = video_run_id,
                operation = operation_type,
                units = CASE
                    WHEN units_used ~ '^[0-9]+$' THEN units_used::int
                    WHEN units_used ~ '^[0-9.]+ *chars?$' THEN regexp_replace(units_used, '[^0-9]', '', 'g')::int
                    ELSE 1
                END
            WHERE run_id IS NULL OR operation IS NULL
        """))

        # ── Step 4: convert cost_usd from float to integer cents ───────────────
        print("Converting cost_usd: float dollars → integer cents...")
        s.execute(text("""
            UPDATE cost_log
            SET cost_usd = CASE
                WHEN cost_usd >= 0 THEN (cost_usd * 100)::int
                ELSE 0
            END
            WHERE cost_usd IS NOT NULL AND cost_usd < 100
        """))

        # ── Step 5: drop old columns ──────────────────────────────────────────
        print("Dropping old columns...")
        if 'video_run_id' in cols:
            s.execute(text("ALTER TABLE cost_log DROP COLUMN video_run_id"))
        if 'operation_type' in cols:
            s.execute(text("ALTER TABLE cost_log DROP COLUMN operation_type"))
        if 'units_used' in cols:
            s.execute(text("ALTER TABLE cost_log DROP COLUMN units_used"))

        # ── Step 6: add NOT NULL + defaults ───────────────────────────────────
        print("Setting constraints...")
        s.execute(text("ALTER TABLE cost_log ALTER COLUMN run_id DROP NOT NULL"))
        s.execute(text("ALTER TABLE cost_log ALTER COLUMN operation SET NOT NULL"))
        s.execute(text("ALTER TABLE cost_log ALTER COLUMN units SET DEFAULT 1"))
        s.execute(text("ALTER TABLE cost_log ALTER COLUMN units SET DEFAULT 1"))
        s.execute(text("ALTER TABLE cost_log ALTER COLUMN cost_usd SET DEFAULT 0"))
        s.execute(text("ALTER TABLE cost_log ALTER COLUMN cost_usd SET NOT NULL"))

        s.commit()

        # ── Step 7: verify ───────────────────────────────────────────────────
        result = s.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'cost_log'
            ORDER BY ordinal_position
        """))
        print("\nFinal schema:")
        for row in result.fetchall():
            print(f"  {row[0]}: {row[1]} nullable={row[2]}")

        # Sample data
        result2 = s.execute(text("SELECT id, run_id, provider, operation, units, cost_usd FROM cost_log LIMIT 5"))
        print("\nSample rows:")
        for row in result2.fetchall():
            print(f"  {row}")

        print("\nMigration complete.")


if __name__ == "__main__":
    migrate()
