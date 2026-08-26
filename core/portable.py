"""Portable-storage support.

Everything Reliquarium persists (hash cache, collections, verification
cache, settings) lives in a `data/` folder next to the app itself -- not
%LOCALAPPDATA% or the Windows registry -- so the whole thing can be copied,
moved, or zipped up as one self-contained unit and just keep working.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def app_dir() -> Path:
    """The directory the app itself lives in.

    When frozen by PyInstaller, this is the folder containing the actual
    .exe on disk (sys.executable) -- deliberately NOT PyInstaller's
    --onefile extraction temp dir (sys._MEIPASS), which is recreated fresh
    and deleted again on every single launch. Writing persistent data there
    would silently lose everything between runs, defeating the entire
    point of portable storage. sys.executable points to the real, stable
    .exe location in both --onefile and --onedir builds.

    Running from source, this is just the project root (the folder
    containing main.py).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def app_data_dir() -> Path:
    """Where all persistent app data lives: <app_dir>/data."""
    return app_dir() / "data"


def migrate_legacy_data(data_dir: Path) -> list:
    """One-time migration from the old %LOCALAPPDATA%\\MediaOrganizer
    location into the new portable data/ folder, so an existing install's
    hash cache, collections, and verification cache aren't orphaned by the
    switch to portable storage. Only runs if the new location doesn't
    already have data in it -- never overwrites anything real, and never
    raises (migration is a convenience, not something that should ever
    block startup). Returns the list of filenames actually migrated (empty
    if nothing was migrated), so the caller can tell the user what happened
    instead of it occurring silently."""
    migrated = []
    try:
        if data_dir.exists() and any(data_dir.iterdir()):
            return migrated
        legacy_base = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "MediaOrganizer"
        if not legacy_base.is_dir():
            return migrated
        data_dir.mkdir(parents=True, exist_ok=True)
        for name in ("hash_cache.json", "collections.json", "verification_cache.json"):
            src = legacy_base / name
            if src.exists():
                shutil.copy2(src, data_dir / name)
                migrated.append(name)
    except OSError:
        pass
    return migrated
