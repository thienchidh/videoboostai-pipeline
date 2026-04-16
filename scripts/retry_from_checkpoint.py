#!/usr/bin/env python3
"""
scripts/retry_from_checkpoint.py — Resume a failed video pipeline run from the last checkpoint.

Usage:
    # Resume a specific run directory
    python scripts/retry_from_checkpoint.py --run-dir output/20260415/1748231234_nangsuat

    # Resume from a run_id (looks up the most recent run)
    python scripts/retry_from_checkpoint.py --run-id 42

    # List checkpoints for a run
    python scripts/retry_from_checkpoint.py --run-dir output/20260415/1748231234_nangsuat --list

    # Clear checkpoints and force full re-run
    python scripts/retry_from_checkpoint.py --run-dir output/20260415/1748231234_nangsuat --clear

    # Use with specific config
    python scripts/retry_from_checkpoint.py --run-dir output/20260415/1748231234_nangsuat \\
        --config configs/business/nangsuat_tips_3scene.json
"""

import argparse
import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

import db
from modules.pipeline.checkpoint import STEP_NAMES, STEP_DONE
from typing import Optional


def resolve_run_id_from_db(run_dir: Path) -> Optional[int]:
    """Resolve run_id from run_dir by querying DB for matching output_video path.

    Queries VideoRun rows where output_video contains the run_dir name.
    Returns the run_id if found, None otherwise.
    """
    import db_models as models
    with db.get_session() as session:
        run = session.query(models.VideoRun).filter(
            models.VideoRun.output_video.like(f"%{run_dir.name}%")
        ).first()
        return run.id if run else None


def _build_scene_id(run_id: int, scene_num: int) -> str:
    return f"run_{run_id}_scene_{scene_num}"


def list_checkpoints(run_id: int, run_dir: Path):
    """List all checkpoints for a run."""
    import db_models as models

    print(f"\n📋 Checkpoints for run_id={run_id}")
    print(f"   Run dir: {run_dir}")
    print("-" * 60)

    with db.get_session() as session:
        # Get all scene checkpoints for this run
        rows = session.query(models.SceneCheckpoint).filter(
            models.SceneCheckpoint.scene_id.like(f"run_{run_id}_scene_%")
        ).order_by(models.SceneCheckpoint.scene_id, models.SceneCheckpoint.step).all()

        if not rows:
            print("   No checkpoints found.")
            return

        current_scene = None
        for row in rows:
            scene_label = row.scene_id
            if scene_label != current_scene:
                if current_scene is not None:
                    print()
                current_scene = scene_label
                scene_num = scene_label.split("_scene_")[-1]
                print(f"  scene_{scene_num}:")

            step_name = STEP_NAMES.get(row.step, f"step_{row.step}")
            path_short = Path(row.output_path).name if row.output_path else "(none)"
            print(f"    step {row.step} ({step_name}): {path_short}  @ {row.completed_at}")


def clear_checkpoints(run_id: int, scene_num: int = None):
    """Clear checkpoints for a run (optionally a specific scene)."""
    import db_models as models

    if scene_num is not None:
        scene_id = _build_scene_id(run_id, scene_num)
        with db.get_session() as session:
            deleted = session.query(models.SceneCheckpoint).filter_by(scene_id=scene_id).delete()
            session.commit()
        print(f"   Cleared {deleted} checkpoint(s) for {scene_id}")
    else:
        with db.get_session() as session:
            deleted = session.query(models.SceneCheckpoint).filter(
                models.SceneCheckpoint.scene_id.like(f"run_{run_id}_scene_%")
            ).delete()
            session.commit()
        print(f"   Cleared {deleted} checkpoint(s) for run {run_id}")


def get_run_summary(run_id: int) -> dict:
    """Get run summary from DB."""
    run = db.get_video_run(run_id)
    if not run:
        return {}
    scenes = db.get_scenes_by_run(run_id)
    return {"run": run, "scenes": scenes}


def retry_from_run(run_id: int, run_dir: Path, config_path: str = None, dry_run: bool = False):
    """Retry pipeline from the last checkpoint for a given run_id."""
    from modules.pipeline.config import PipelineContext
    from modules.pipeline.pipeline_runner import VideoPipelineRunner
    from core.video_utils import log

    print(f"\n🔄 RETRY FROM CHECKPOINT — run_id={run_id}")
    print(f"   Run dir: {run_dir}")
    if dry_run:
        print("   ⚠️  DRY RUN MODE (no real API calls)")

    # List what will be retried
    print("\n📊 Checkpoint summary:")
    _print_checkpoint_summary(run_id)

    if not dry_run:
        confirm = input("\n▶️  Continue with retry? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    # Build the PipelineContext from the scenario in the run_dir
    # Try to find the scenario YAML
    scenario_candidates = list(run_dir.glob("**/*.yaml")) + list(run_dir.glob("**/*.yml"))
    if not scenario_candidates and config_path:
        scenario_candidates = [Path(config_path)]

    if not scenario_candidates:
        print("❌ Could not find scenario YAML in run_dir.")
        print("   Please provide --config to specify the pipeline config.")
        sys.exit(1)

    scenario_path = scenario_candidates[0]
    # Extract channel_id from run_dir name (last segment)
    channel_id = run_dir.name.split("_", 1)[-1] if "_" in run_dir.name else run_dir.name

    # Init DB connection
    db.init_db()

    # Build PipelineContext
    ctx = PipelineContext(channel_id, scenario_path=str(scenario_path))

    # Instantiate runner with existing run_id context
    runner = VideoPipelineRunner(
        ctx,
        dry_run=dry_run,
        timestamp=int(run_dir.name.split("_")[0]) if run_dir.name[0].isdigit() else None,
        parallel_scenes=True,
    )
    # Override the auto-generated run_id to resume the existing one
    runner.run_id = run_id

    print(f"\n🚀 Starting pipeline from checkpoint...")
    print(f"   channel_id={channel_id}")
    print(f"   scenario={scenario_path}")
    print(f"   run_id={runner.run_id} (resuming)")
    print(f"   run_dir={runner.run_dir}")

    try:
        video_path, timestamps = runner.run()
        if video_path:
            print(f"\n✅ Retry successful: {video_path}")
        else:
            print(f"\n⚠️  Pipeline returned no video (may be partial)")
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def _print_checkpoint_summary(run_id: int):
    """Print a summary of what will be retried."""
    import db_models as models

    with db.get_session() as session:
        rows = session.query(models.SceneCheckpoint).filter(
            models.SceneCheckpoint.scene_id.like(f"run_{run_id}_scene_%")
        ).order_by(models.SceneCheckpoint.scene_id, models.SceneCheckpoint.step.desc()).all()

        if not rows:
            print("   No checkpoints — full re-run will happen")
            return

        # Group by scene, show highest completed step
        by_scene = {}
        for row in rows:
            scene_id = row.scene_id
            if scene_id not in by_scene:
                by_scene[scene_id] = {"step": row.step, "output": row.output_path, "at": row.completed_at}

        for scene_id, info in sorted(by_scene.items()):
            scene_num = scene_id.split("_scene_")[-1]
            step_name = STEP_NAMES.get(info["step"], f"step_{info['step']}")
            status = "✅ DONE" if info["step"] >= STEP_DONE else f"⏳ step {info['step']}/{STEP_DONE} ({step_name})"
            path = Path(info["output"]).name if info["output"] else "—"
            print(f"   scene_{scene_num}: {status}  ({path})")


def main():
    parser = argparse.ArgumentParser(
        description="Resume a failed video pipeline run from the last checkpoint.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List checkpoints for a run
  python scripts/retry_from_checkpoint.py --run-dir output/20260415/1748231234_nangsuat --list

  # Clear checkpoints for a specific scene and force re-run
  python scripts/retry_from_checkpoint.py --run-dir output/20260415/1748231234_nangsuat \\
       --clear-scene 2

  # Full re-run from scratch
  python scripts/retry_from_checkpoint.py --run-dir output/20260415/1748231234_nangsuat --clear

  # Retry (with dry-run first to see what would happen)
  python scripts/retry_from_checkpoint.py --run-dir output/20260415/1748231234_nangsuat --dry-run
        """
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-dir", type=Path, metavar="PATH",
                        help="Path to the run directory (e.g. output/20260415/1748231234_channelid)")
    group.add_argument("--run-id", type=int, metavar="ID",
                        help="Video run ID from the database")

    parser.add_argument("--config", type=str, metavar="PATH",
                        help="Path to config YAML (auto-discovered if not given)")
    parser.add_argument("--list", action="store_true",
                        help="List checkpoints and exit")
    parser.add_argument("--clear", action="store_true",
                        help="Clear all checkpoints for the run and exit (force full re-run)")
    parser.add_argument("--clear-scene", type=int, metavar="N",
                        help="Clear checkpoints for a specific scene number only")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be retried without running the pipeline")
    parser.add_argument("--db-host", type=str, default=os.getenv("POSTGRES_HOST", "localhost"))
    parser.add_argument("--db-port", type=int, default=int(os.getenv("POSTGRES_PORT", "5432")))
    parser.add_argument("--db-name", type=str, default=os.getenv("POSTGRES_DB", "videopipeline"))
    parser.add_argument("--db-user", type=str, default=os.getenv("POSTGRES_USER", "videopipeline"))
    parser.add_argument("--db-password", type=str, default=os.getenv("POSTGRES_PASSWORD", "videopipeline123"))

    args = parser.parse_args()

    # Configure DB
    db.configure({
        "host": args.db_host,
        "port": args.db_port,
        "database": args.db_name,
        "user": args.db_user,
        "password": args.db_password,
    })
    db.init_db()

    # ── Resolve run_id and run_dir ───────────────────────────────────
    if args.run_id:
        run_id = args.run_id
        run = db.get_video_run(run_id)
        if not run:
            print(f"❌ No video run found with id={run_id}")
            sys.exit(1)
        run_dir = Path(run["run_dir"]) if run["run_dir"] else None
        if not run_dir:
            print(f"❌ Run {run_id} has no run_dir set in DB.")
            sys.exit(1)
        if not run_dir.exists():
            print(f"❌ Run dir not found: {run_dir}")
            sys.exit(1)
    elif args.run_dir:
        run_dir = args.run_dir.resolve()
        if not run_dir.exists():
            print(f"❌ Run dir not found: {run_dir}")
            sys.exit(1)
        # Use DB query to resolve run_id from run_dir (not fragile checkpoint parsing)
        run_id = resolve_run_id_from_db(run_dir)

        if run_id is None:
            print(f"❌ Could not determine run_id for: {run_dir}")
            print(f"   Please provide --run-id explicitly, or ensure run_dir is set in DB for the run.")
            sys.exit(1)

    print(f"Resolved: run_id={run_id}, run_dir={run_dir}")

    # ── List checkpoints ────────────────────────────────────────────
    if args.list:
        list_checkpoints(run_id, run_dir)
        return

    # ── Clear checkpoints ────────────────────────────────────────────
    if args.clear:
        clear_checkpoints(run_id)
        return

    if args.clear_scene:
        clear_checkpoints(run_id, args.clear_scene)
        return

    # ── Retry pipeline ───────────────────────────────────────────────
    retry_from_run(run_id, run_dir, config_path=args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
