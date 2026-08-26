"""Locates bundled resource files (icons, etc.) whether running from
source or from a PyInstaller-frozen executable.

PyInstaller's --onefile mode extracts bundled data files to a temporary
directory at runtime, exposed as sys._MEIPASS. Running from source, there
is no such thing -- resources just live relative to the project root.
"""
from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative
