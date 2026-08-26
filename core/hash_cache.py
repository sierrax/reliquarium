"""Persistent CRC32 hash cache so re-scanning unchanged files is instant.

Keyed by absolute file path, storing the size and modification time seen
last time alongside the computed CRC32. On a later scan, if a file's size
and mtime still match, the (expensive) full read-and-hash is skipped
entirely and the cached CRC32 is reused. This matters far more than
thread count for repeat scans: CRC32 requires reading every byte of every
file, so skipping unchanged multi-gigabyte media files outright saves much
more time than parallelizing the read would.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from core.portable import app_data_dir


def default_cache_path() -> Path:
    return app_data_dir() / "hash_cache.json"


def load_cache(path: Path) -> Dict[str, dict]:
    """Load the cache from disk. Never raises -- a missing or corrupt cache
    just means starting fresh (equivalent to a cold cache)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def save_cache(path: Path, cache: Dict[str, dict]) -> None:
    """Save the cache to disk atomically. Never raises -- the cache is a
    convenience/speed optimization, never load-bearing for correctness."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        tmp.replace(path)
    except OSError:
        pass


def clear_cache_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
