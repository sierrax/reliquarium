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

    Checked in order:

    1. $APPIMAGE, if set -- this is how a running AppImage is meant to
       find its own real, persistent location. AppImages mount themselves
       into a temporary location via FUSE on every launch (typically
       under /tmp/.mount_XXXXXXX/...), and sys.executable from inside a
       running AppImage points INTO that ephemeral mount, not to the
       actual .AppImage file sitting on real disk. That mount is torn
       down the moment the app exits, taking anything written there with
       it -- so using sys.executable here would silently lose all
       portable data on every single run. This is a different problem
       from PyInstaller's own --onefile extraction temp dir (handled
       below): AppImage does its own separate temporary mounting, one
       layer above whatever PyInstaller build mode sits underneath it.
    2. sys.executable, when frozen by PyInstaller but NOT running as an
       AppImage (a plain Windows .exe, or a Linux onedir/onefile build
       not wrapped in an AppImage) -- this is the folder containing the
       actual .exe/executable on disk, deliberately not
       PyInstaller's --onefile extraction temp dir (sys._MEIPASS), which
       has the same "recreated and deleted every launch" problem.
    3. The project root (the folder containing main.py), when running
       from source.
    """
    appimage_path = os.environ.get("APPIMAGE")
    if appimage_path:
        return Path(appimage_path).resolve().parent
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
