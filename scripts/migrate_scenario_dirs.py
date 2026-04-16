#!/usr/bin/python3
"""Migrate scenario YAML files from date-grouped to flat structure.

Usage: python scripts/migrate_scenario_dirs.py [--dry-run]
"""
import argparse
from pathlib import Path
import re

DATE_DIR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def migrate_channel(channel_path: Path, dry_run: bool = False):
    scenarios_dir = channel_path / "scenarios"
    if not scenarios_dir.exists():
        return 0

    migrated = 0
    date_dirs = sorted(d for d in scenarios_dir.iterdir() if d.is_dir() and DATE_DIR_PATTERN.match(d.name))

    for date_dir in date_dirs:
        date_str = date_dir.name
        for yaml_file in date_dir.glob("*.yaml"):
            target = scenarios_dir / yaml_file.name

            if target.exists():
                # Collision: same slug from a different date
                collision_name = f"{yaml_file.stem}_{date_str.replace('-', '')}.yaml"
                target = scenarios_dir / collision_name

            if dry_run:
                print(f"[DRY-RUN] Would move: {yaml_file} → {target}")
            else:
                print(f"Moving: {yaml_file} → {target}")
                yaml_file.rename(target)
            migrated += 1

        # Remove empty date directory
        if not any(date_dir.iterdir()):
            if dry_run:
                print(f"[DRY-RUN] Would remove empty dir: {date_dir}")
            else:
                date_dir.rmdir()

    return migrated

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    channels_dir = Path("configs/channels")
    total = 0
    for channel_dir in sorted(channels_dir.iterdir()):
        if channel_dir.is_dir():
            count = migrate_channel(channel_dir, args.dry_run)
            if count > 0:
                print(f"  → {channel_dir.name}: {count} file(s) migrated")
                total += count

    if args.dry_run:
        print(f"\n[DRY-RUN] Total: {total} files would be migrated")
    else:
        print(f"\n✅ Migration complete: {total} files moved")

if __name__ == "__main__":
    main()