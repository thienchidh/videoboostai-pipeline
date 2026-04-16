#!/usr/bin/python3
"""scripts/retry_scene.py — Retry/resume from a specific step within a scene."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from modules.pipeline.scene_checkpoint import _get_first_incomplete_step

STEP_NAMES = {1: "tts", 2: "image", 3: "lipsync", 4: "crop"}
STEP_FILES = {n: f"step_{n:02d}_{STEP_NAMES[n]}.json" for n in range(1, 5)}


def _step_file(scene_dir: Path, step: int) -> Path:
    """Return path to step checkpoint file for given step number."""
    return scene_dir / STEP_FILES[step]


def load_step(scene_dir: Path, step: int) -> dict:
    """Load step checkpoint data as dict. Returns empty dict if file doesn't exist."""
    step_path = _step_file(scene_dir, step)
    if not step_path.exists():
        return {}
    try:
        return json.loads(step_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def clear_step(scene_dir: Path, step: int) -> None:
    """Delete the step checkpoint file if it exists."""
    step_path = _step_file(scene_dir, step)
    if step_path.exists():
        step_path.unlink()


def list_steps(scene_dir: Path) -> None:
    """Print a table of all step checkpoint statuses."""
    scene_dir = Path(scene_dir)

    # Show run metadata if available
    run_meta = scene_dir / "run_meta.json"
    if run_meta.exists():
        try:
            meta = json.loads(run_meta.read_text(encoding="utf-8"))
            print(f"Run ID:    {meta.get('run_id', 'N/A')}")
            print(f"Channel:   {meta.get('channel_id', 'N/A')}")
            print(f"Slug:      {meta.get('slug', 'N/A')}")
        except (json.JSONDecodeError, OSError):
            pass

    # Show scene metadata if available
    scene_meta = scene_dir / "scene_meta.json"
    if scene_meta.exists():
        try:
            meta = json.loads(scene_meta.read_text(encoding="utf-8"))
            print(f"Scene ID:  {meta.get('scene_id', 'N/A')}")
            print(f"Title:     {meta.get('title', 'N/A')}")
        except (json.JSONDecodeError, OSError):
            pass

    if run_meta.exists() or scene_meta.exists():
        print()

    # Print step table header
    print(f"{'Step':<8} {'Status':<10} {'Mode/Provider':<15} {'Duration':<10} {'Error'}")
    print("-" * 70)

    for step_num in range(1, 5):
        step_path = _step_file(scene_dir, step_num)
        step_name = STEP_NAMES[step_num]

        if not step_path.exists():
            status_icon = "⚪"
            status_str = "not started"
            mode_str = ""
            duration_str = ""
            error_str = ""
        else:
            try:
                data = json.loads(step_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                status_icon = "⚠️"
                status_str = "corrupt"
                mode_str = ""
                duration_str = ""
                error_str = "JSON parse error"
                print(f"{step_num} ({step_name:<6}) {status_icon} {status_str:<10} {error_str}")
                continue

            status = data.get("status", "")

            if status == "done":
                status_icon = "✅"
            elif status == "retry":
                status_icon = "⚠️"
            elif status == "failed":
                status_icon = "❌"
            else:
                status_icon = "⚠️"

            status_str = status if status else "unknown"
            mode_str = data.get("mode", "") or data.get("provider", "")
            duration = data.get("duration_seconds", "")
            duration_str = f"{duration:.2f}s" if duration else ""

            error_str = data.get("error", "") or ""

        print(f"{step_num} ({step_name:<6}) {status_icon} {status_str:<10} {mode_str:<15} {duration_str:<10} {error_str}")


def show_retry_info(scene_dir: Path, step: int) -> None:
    """Print information about retrying step N."""
    data = load_step(scene_dir, step)
    step_name = STEP_NAMES[step]

    if not data:
        print(f"Step {step} ({step_name}) — no checkpoint file found. Nothing to retry.")
        print(f"Run the pipeline to start this step fresh.")
        return

    status = data.get("status", "unknown")
    print(f"Step {step} ({step_name}) — status: {status}")
    print()

    # Print relevant fields based on step
    if step == 1:  # tts
        print(f"  Provider:   {data.get('provider', 'N/A')}")
        print(f"  Voice:      {data.get('voice', 'N/A')}")
        print(f"  Speed:      {data.get('speed', 'N/A')}")
        print(f"  Model:      {data.get('model', 'N/A')}")
        print(f"  Output:     {data.get('output', 'N/A')}")
        print(f"  Duration:   {data.get('duration_seconds', 'N/A')}s")
        print(f"  Text len:   {len(data.get('text', ''))} chars")
        if data.get("error"):
            print(f"  Error:      {data['error']}")

    elif step == 2:  # image
        print(f"  Provider:   {data.get('provider', 'N/A')}")
        print(f"  Model:      {data.get('model', 'N/A')}")
        print(f"  Aspect:     {data.get('aspect_ratio', 'N/A')}")
        print(f"  Output:     {data.get('output', 'N/A')}")
        print(f"  Character:  {data.get('character_name', 'N/A')}")
        if data.get("error"):
            print(f"  Error:      {data['error']}")

    elif step == 3:  # lipsync
        print(f"  Provider:   {data.get('provider', 'N/A')}")
        print(f"  Actual mode: {data.get('actual_mode', 'N/A')}")
        print(f"  Attempted:  {data.get('attempted_mode', 'N/A')}")
        print(f"  Output:     {data.get('output', 'N/A')}")
        print(f"  Duration:   {data.get('input_duration', 'N/A')}s")
        if data.get("fallback_reason"):
            print(f"  Fallback:   {data['fallback_reason']}")
        if data.get("error"):
            print(f"  Error:      {data['error']}")

    elif step == 4:  # crop
        print(f"  Input:      {data.get('input', 'N/A')}")
        print(f"  Output:     {data.get('output', 'N/A')}")
        print(f"  Dimensions: {data.get('input_width', 'N/A')}x{data.get('input_height', 'N/A')} -> {data.get('output_width', 'N/A')}x{data.get('output_height', 'N/A')}")
        print(f"  Duration:   {data.get('output_duration', 'N/A')}s")
        print(f"  Codec:      {data.get('codec', 'N/A')}")
        if data.get("error"):
            print(f"  Error:      {data['error']}")

    print()
    if status == "done":
        print(f"To re-run step {step}, use --clear first, then run the pipeline.")
    elif status == "retry":
        print(f"To retry this step, run the pipeline — it will auto-retry.")
    elif status == "failed":
        print(f"To re-run this failed step, use --clear first, then run the pipeline.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retry/resume from a specific step within a scene. "
                    "Shows step checkpoint status, retry info, and can clear checkpoints.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --scene-dir /path/to/scene --list
  %(prog)s --scene-dir /path/to/scene --step 2
  %(prog)s --scene-dir /path/to/scene --step 3 --clear
  %(prog)s --scene-dir /path/to/scene --resume
        """,
    )
    parser.add_argument(
        "--scene-dir",
        type=Path,
        required=True,
        help="Path to the scene directory containing step checkpoint files",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Show table of all step checkpoint statuses",
    )
    parser.add_argument(
        "--step",
        type=int,
        choices=[1, 2, 3, 4],
        help="Show retry info for step N (1=tts, 2=image, 3=lipsync, 4=crop)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear the checkpoint file for the specified step (use with --step)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Show which step to resume from",
    )

    args = parser.parse_args()

    if args.clear and args.step is None:
        parser.error("--clear requires --step N")

    if args.list:
        list_steps(args.scene_dir)
    elif args.step is not None:
        if args.clear:
            clear_step(args.scene_dir, args.step)
            print(f"Cleared step {args.step} ({STEP_NAMES[args.step]}) checkpoint.")
        else:
            show_retry_info(args.scene_dir, args.step)
    elif args.resume:
        next_step = _get_first_incomplete_step(args.scene_dir)
        if next_step == 5:
            print("All steps completed — nothing to resume.")
        else:
            print(f"Resume from step {next_step} ({STEP_NAMES[next_step]})")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
