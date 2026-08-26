"""Persistent cache of collection-directory verification results.

Unlike the CRC32 hash cache (per-file hashes keyed by path), this stores
the last known *file listing* per CSV output folder -- i.e. "as of the
last time we actually walked this CSV's folder, here's what was found
there." This is what lets a scoped (post-move) verification trust that
untouched CSVs are still in the state they were last confirmed to be in,
even across app restarts, instead of needing a fresh full walk every time
the app launches.

This is deliberately a "trust it, refresh when something's actually
suspect" cache, the same trust model as the hash cache itself: if files
are added, removed, or changed outside the app between verifications, this
won't know until something re-walks that folder (a full check via the
Collection Status window or the manual report buttons, or a move touching
that CSV again). Users are expected to run a full check occasionally as a
sanity pass, same as with any local cache -- this file doesn't try to
detect external changes on its own.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from core.portable import app_data_dir


def default_verification_cache_path() -> Path:
    return app_data_dir() / "verification_cache.json"


def load_verification_cache(path: Path) -> Dict[str, Dict[str, List[list]]]:
    """Returns {root: {csv_name: [[filename, size, crc], ...]}}. Never
    raises -- a missing or corrupt cache just means starting fresh."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        roots = data.get("roots", {})
        if isinstance(roots, dict):
            return roots
    except (OSError, ValueError):
        pass
    return {}


def save_verification_cache(path: Path, roots: Dict[str, Dict[str, List[list]]]) -> None:
    """Saves atomically. Never raises -- this cache is a convenience/speed
    optimization, never load-bearing for correctness."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "roots": roots}
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        tmp.replace(path)
    except OSError:
        pass
