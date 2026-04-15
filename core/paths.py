"""core/paths.py — Centralized project root and auto-detection utilities.

Eliminates repeated Path(__file__).parent.parent traversal.
All path computations flow through PROJECT_ROOT, computed once at import time.

Auto-detection functions:
- get_python()         — current Python interpreter
- find_font(name)      — search common font directories for a font file
- get_font_path()      — LiberationSans-Bold auto-detected (default)
- get_ffmpeg()         — ffmpeg on PATH
- get_edge_tts()       — edge-tts on PATH
- get_whisper()        — whisper on PATH
- get_config_path()    — ~/.openclaw/<relative>
"""

import os
import subprocess
import sys
import shutil
from pathlib import Path

# ── Project root ─────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent

# ── Derived directories ────────────────────────────────────────────────────────

CONFIG_DIR       = PROJECT_ROOT / "configs"
TECHNICAL_CONFIG = CONFIG_DIR / "technical" / "config_technical.yaml"
OUTPUT_DIR       = PROJECT_ROOT / "output"
MUSIC_DIR        = PROJECT_ROOT / "music"
FONTS_DIR        = PROJECT_ROOT / "fonts"

# ── Python detection ───────────────────────────────────────────────────────────

def get_python() -> Path:
    """Return Path to the currently running Python interpreter."""
    return Path(sys.executable)


# ── Font detection ─────────────────────────────────────────────────────────────

def _font_search_dirs() -> list[Path]:
    """Return platform-appropriate list of font directories to search."""
    dirs = []
    if sys.platform == "win32":
        windir = Path(os.environ.get("WINDIR", "C:\\Windows"))
        dirs.extend([
            windir / "Fonts",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts",
        ])
    elif sys.platform == "darwin":
        dirs.extend([
            Path("/Library/Fonts"),
            Path.home() / "Library" / "Fonts",
            Path("/System/Library/Fonts"),
        ])
    else:  # Linux and others
        dirs.extend([
            Path("/usr/share/fonts/truetype"),
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".fonts",
            Path.home() / ".local" / "share" / "fonts",
        ])
    return [d for d in dirs if d.is_dir()]


def find_font(name: str) -> Path:
    """Find font file. Checks FONTS_DIR first (bundled), then system font directories."""
    if not name:
        raise FileNotFoundError("Font name cannot be empty")

    # Normalize: ensure .ttf extension
    if not Path(name).suffix:
        name = name + ".ttf"

    # 1. Check bundled fonts directory first
    bundled = FONTS_DIR / name
    if bundled.is_file():
        return bundled

    # 2. Fall back to system font directories
    for dir_path in _font_search_dirs():
        candidate = dir_path / name
        if candidate.is_file():
            return candidate

    searched = [str(FONTS_DIR)] + [str(d) for d in _font_search_dirs()]
    raise FileNotFoundError(
        f"Font '{name}' not found. Checked: {', '.join(searched)}"
    )


def get_font_path(config_override: str | None = None) -> Path:
    """Return font path: user override or auto-detected LiberationSans-Bold.

    Args:
        config_override: If provided and file exists, use it instead of auto-detecting.
    """
    if config_override:
        p = Path(config_override)
        if p.is_file():
            return p
    return find_font("LiberationSans-Bold")


# ── External tool detection ────────────────────────────────────────────────────

def _get_tool(name: str) -> Path:
    """Return Path to `name` on PATH. Raises FileNotFoundError if not found."""
    found = shutil.which(name)
    if not found:
        raise FileNotFoundError(
            f"'{name}' not found on PATH. "
            f"Ensure {name} is installed and added to your system PATH. "
            f"See TOOLS.md for installation instructions."
        )
    return Path(found)


def get_ffmpeg() -> Path:
    """Return Path to ffmpeg executable."""
    return _get_tool("ffmpeg")


def get_ffprobe() -> Path:
    """Return Path to ffprobe executable (comes with ffmpeg)."""
    return _get_tool("ffprobe")


def get_edge_tts() -> Path:
    """Return Path to edge-tts executable."""
    return _get_tool("edge-tts")


def get_whisper() -> Path:
    """Return Path to whisper CLI executable."""
    return _get_tool("whisper")


# ── Config path helper ─────────────────────────────────────────────────────────

def get_config_path(relative: str) -> Path:
    """Resolve ~/.openclaw/<relative> using Path.home()."""
    return Path.home() / ".openclaw" / relative


# ── Repository file helper ─────────────────────────────────────────────────────

def repo_file(relative: str) -> Path:
    """Resolve a path relative to PROJECT_ROOT."""
    return PROJECT_ROOT / relative
