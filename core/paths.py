"""core/paths.py — Centralized project root and path utilities.

Eliminates repeated Path(__file__).parent.parent.parent traversal.
All path computations flow through PROJECT_ROOT, computed once at import time.
"""

from pathlib import Path

# Compute PROJECT_ROOT once.  __file__ = core/paths.py → parent = core/ → parent = repo root
PROJECT_ROOT = Path(__file__).parent.parent

# ─── Derived directories ─────────────────────────────────────────────────────

CONFIG_DIR       = PROJECT_ROOT / "configs"
TECHNICAL_CONFIG = CONFIG_DIR / "technical" / "config_technical.yaml"
OUTPUT_DIR       = PROJECT_ROOT / "output"
MUSIC_DIR        = PROJECT_ROOT / "music"
FONTS_DIR        = PROJECT_ROOT / "fonts"

# ─── Karaoke python resolver ──────────────────────────────────────────────────

LINUXBREW_PYTHON = "/home/linuxbrew/.linuxbrew/bin/python3"
VENV_PYTHON      = PROJECT_ROOT / "venv" / "bin" / "python3"
SYSTEM_PYTHON    = "/usr/bin/python3"


def get_karaoke_python() -> Path:
    """Return Path to python with PIL/numpy (venv > linuxbrew > system)."""
    if VENV_PYTHON.exists():
        return VENV_PYTHON
    if Path(LINUXBREW_PYTHON).exists():
        return Path(LINUXBREW_PYTHON)
    return Path(SYSTEM_PYTHON)


def repo_file(relative: str) -> Path:
    """Resolve a path relative to PROJECT_ROOT."""
    return PROJECT_ROOT / relative