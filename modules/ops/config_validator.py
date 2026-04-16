#!/usr/bin/env python3
"""
Config Validator — validates channel + technical config files.

Usage:
    python -m modules.ops.config_validator --channel <channel_name>
    python -m modules.ops.config_validator --channel productivity --verbose

Exit codes:
    0 = valid
    1 = validation errors found
"""

import argparse
import os
import sys
from pathlib import Path
from typing import List, Tuple

import yaml


# ── Resolve project root ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = PROJECT_ROOT / "configs"

# ── Required field definitions ────────────────────────────────────────────────

# technical config
TECH_REQUIRED = {
    ("api", "keys", "minimax"): "minimax API key",
    ("api", "keys", "wavespeed"): "wavespeed API key",
    ("api", "urls", "minimax_tts"): "minimax_tts URL",
    ("api", "urls", "minimax_image"): "minimax_image URL",
    ("storage", "s3", "bucket"): "S3 bucket name",
    ("storage", "s3", "endpoint"): "S3 endpoint",
    ("storage", "s3", "access_key"): "S3 access key",
    ("storage", "s3", "secret_key"): "S3 secret key",
    ("storage", "database", "host"): "database host",
    ("storage", "database", "port"): "database port",
    ("storage", "database", "name"): "database name",
    ("storage", "database", "user"): "database user",
    ("storage", "database", "password"): "database password",
}

# channel config
CHANNEL_REQUIRED = {
    ("channel_id",): "channel_id",
    ("name",): "channel name",
    ("video",): "video section",
    ("video", "aspect_ratio"): "video aspect_ratio",
    ("video", "resolution"): "video resolution",
    ("generation",): "generation section",
    ("generation", "models", "tts"): "generation.models.tts",
    ("generation", "models", "image"): "generation.models.image",
    ("generation", "models", "video"): "generation.models.video",
    ("llm",): "llm section",
    ("llm", "provider"): "llm provider",
    ("llm", "model"): "llm model",
}

# scenario config (first scenario is validated, rest are checked for structural integrity)
SCENARIO_REQUIRED = {
    ("title",): "scenario title",
    ("scenes",): "scenes list",
}

SCENE_REQUIRED = {
    ("id",): "scene id",
    ("script",): "scene script",
    ("background",): "scene background",
    ("character",): "scene character",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_nested(data: dict, path: Tuple[str, ...]):
    """Traverse a nested dict by path parts. Returns None if any part is missing."""
    node = data
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
        if node is None:
            return None
    return node


def validate_not_empty(value, field_path: str, errors: List[str]) -> bool:
    """Check that a value is not None, not empty string, and not empty container."""
    if value is None:
        errors.append(f"  Missing / empty: {'.'.join(field_path)}")
        return False
    if isinstance(value, (str, list, dict)) and len(value) == 0:
        errors.append(f"  Empty value: {'.'.join(field_path)}")
        return False
    return True


def validate_technical(config: dict) -> List[str]:
    errors = []
    for path, label in TECH_REQUIRED.items():
        value = get_nested(config, path)
        # Allow placeholder strings that look real
        placeholder_values = {"", "your-key-here", "CHANGE-ME", "minio-password-change-me"}
        if isinstance(value, str) and value in placeholder_values:
            errors.append(f"  Placeholder detected: {'.'.join(path)} ({label})")
        elif not validate_not_empty(value, path, errors):
            pass  # validate_not_empty already appended
    return errors


def validate_channel(config: dict) -> List[str]:
    errors = []
    for path, label in CHANNEL_REQUIRED.items():
        value = get_nested(config, path)
        if not validate_not_empty(value, path, errors):
            pass
    return errors


def validate_scenario(scenario_path: Path) -> List[str]:
    errors = []
    try:
        with open(scenario_path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        errors.append(f"  YAML parse error in {scenario_path.name}: {e}")
        return errors

    # Top-level required fields
    for path, label in SCENARIO_REQUIRED.items():
        value = get_nested(data, path)
        if not validate_not_empty(value, path, errors):
            pass

    # Each scene
    scenes = data.get("scenes", [])
    if not isinstance(scenes, list):
        errors.append(f"  scenes is not a list in {scenario_path.name}")
    else:
        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                errors.append(f"  scene[{i}] is not a dict in {scenario_path.name}")
                continue
            for path, label in SCENE_REQUIRED.items():
                value = get_nested(scene, path)
                if not validate_not_empty(value, [f"scenes[{i}]"] + list(path), errors):
                    pass

    return errors


def find_channel_dir(channel_name: str) -> Path:
    """Return the channel config directory, or None."""
    channels_root = CONFIG_ROOT / "channels"
    # Normalise name for directory matching
    candidates = [channel_name, channel_name.replace("_", "-")]
    for candidate in candidates:
        for child in sorted(channels_root.iterdir()):
            if child.is_dir() and child.name == candidate:
                return child
            # Fuzzy match: strip common prefixes/suffixes
            if child.name.replace("_", "-") == candidate.replace("_", "-"):
                return child
    return None


# ── Main validator ────────────────────────────────────────────────────────────

def validate(channel_name: str, verbose: bool = False) -> Tuple[int, List[str]]:
    """
    Returns (exit_code, error_lines).
    exit_code: 0 = valid, 1 = errors found
    """
    all_errors = []
    summary = {}

    # ── Technical config ───────────────────────────────────────────────────────
    tech_path = CONFIG_ROOT / "technical" / "config_technical.yaml"
    if not tech_path.exists():
        all_errors.append(f"ERROR: Technical config not found at {tech_path}")
        summary["technical"] = "FILE MISSING"
    else:
        with open(tech_path) as f:
            tech_config = yaml.safe_load(f) or {}
        tech_errors = validate_technical(tech_config)
        if tech_errors:
            all_errors.append("=== Technical Config Errors ===")
            all_errors.extend(tech_errors)
            summary["technical"] = f"{len(tech_errors)} error(s)"
        else:
            if verbose:
                print("✓ Technical config: OK")
            summary["technical"] = "OK"

    # ── Channel config ──────────────────────────────────────────────────────────
    channel_dir = find_channel_dir(channel_name)
    if channel_dir is None:
        all_errors.append(f"ERROR: Channel directory not found: {channel_name}")
        all_errors.append(f"  Searched in: {CONFIG_ROOT / 'channels'}")
        summary["channel"] = "DIR MISSING"
    else:
        channel_config_path = channel_dir / "config.yaml"
        if not channel_config_path.exists():
            all_errors.append(f"ERROR: Channel config not found: {channel_config_path}")
            summary["channel"] = "FILE MISSING"
        else:
            with open(channel_config_path) as f:
                channel_config = yaml.safe_load(f) or {}
            ch_errors = validate_channel(channel_config)
            if ch_errors:
                all_errors.append(f"=== Channel Config Errors [{channel_dir.name}] ===")
                all_errors.extend(ch_errors)
                summary["channel"] = f"{len(ch_errors)} error(s)"
            else:
                if verbose:
                    print(f"✓ Channel config: {channel_dir.name}/config.yaml — OK")
                summary["channel"] = "OK"

        # ── Scenario files ───────────────────────────────────────────────────────
        scenarios_dir = channel_dir / "scenarios"
        if scenarios_dir.exists():
            scenario_files = sorted(scenarios_dir.glob("*.yaml")) + sorted(scenarios_dir.glob("*.yml"))
            if not scenario_files:
                all_errors.append(f"  WARNING: No scenario files found in {scenarios_dir}")
                summary["scenarios"] = "0 files"
            else:
                scenario_errors = []
                scenario_counts = {"ok": 0, "errors": 0}
                for sf in scenario_files:
                    s_errors = validate_scenario(sf)
                    if s_errors:
                        scenario_errors.append(f"=== Scenario Errors: {sf.name} ===")
                        scenario_errors.extend(s_errors)
                        scenario_counts["errors"] += 1
                    else:
                        scenario_counts["ok"] += 1

                if scenario_errors:
                    all_errors.append("=== Scenario Errors ===")
                    all_errors.extend(scenario_errors)
                    summary["scenarios"] = f"{scenario_counts['ok']} ok, {scenario_counts['errors']} with errors"
                else:
                    if verbose:
                        print(f"✓ Scenarios: {scenario_counts['ok']} file(s) — OK")
                    summary["scenarios"] = f"{scenario_counts['ok']} ok"
        else:
            all_errors.append(f"  WARNING: No scenarios/ directory in {channel_dir.name}")
            summary["scenarios"] = "DIR MISSING"

    # ── Print summary ────────────────────────────────────────────────────────────
    print("Config Validation Summary")
    print("=" * 50)
    for section, status in summary.items():
        ok = "✓" if status == "OK" or status.startswith("ok") else "✗"
        print(f"  {ok} {section}: {status}")

    if all_errors:
        print()
        print("Validation FAILED — details:")
        print()
        for err in all_errors:
            print(err)
        return 1, all_errors
    else:
        print()
        print("All configs are valid ✓")
        return 0, []


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Validate channel + technical config files for the video pipeline."
    )
    parser.add_argument(
        "--channel",
        required=True,
        help="Channel name (directory name under configs/channels/)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each section pass/fail detail",
    )
    args = parser.parse_args()

    exit_code, _ = validate(args.channel, verbose=args.verbose)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()