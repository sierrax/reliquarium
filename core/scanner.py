"""Directory scanning and CRC32 computation, parallelized via QThreadPool."""
from __future__ import annotations

import os
import zlib
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThread, Signal, Slot

CHUNK_SIZE = 1024 * 1024  # 1 MB
ENUM_UPDATE_INTERVAL = 250


@dataclass
class ScanResult:
    path: str
    filesize: int
    crc32: str
    generation: int = 0
    mtime_ns: int = 0
    cache_hit: bool = False
    error: Optional[str] = None


def compute_crc32(path: str) -> tuple[int, str]:
    """Return (filesize, normalized 8-char hex crc32) for a file."""
    crc = 0
    size = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
            size += len(chunk)
    return size, f"{crc & 0xFFFFFFFF:08X}"


def hash_or_cached(path: str, cache: dict) -> tuple[int, str, int, bool]:
    """Return (filesize, crc32, mtime_ns, cache_hit).

    Checks the file's current size/mtime (a cheap stat call) against a
    previously cached entry for this path. Only reads and hashes the full
    file if there's no cache entry or the file has changed since it was
    cached.
    """
    st = os.stat(path)
    cached = cache.get(path)
    if cached is not None and cached.get("size") == st.st_size and cached.get("mtime_ns") == st.st_mtime_ns:
        return st.st_size, cached["crc32"], st.st_mtime_ns, True
    size, crc = compute_crc32(path)
    return size, crc, st.st_mtime_ns, False


def iter_files(root: str, recursive: bool):
    """Yield file paths under root."""
    if recursive:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                yield os.path.join(dirpath, name)
    else:
        with os.scandir(root) as it:
            for entry in it:
                if entry.is_file():
                    yield entry.path


class EnumerateThread(QThread):
    """Walks the target directory off the GUI thread and reports progress."""

    countUpdate = Signal(int)
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, root: str, recursive: bool, parent=None):
        super().__init__(parent)
        self.root = root
        self.recursive = recursive
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        paths: list[str] = []
        try:
            for p in iter_files(self.root, self.recursive):
                if self._stop:
                    break
                paths.append(p)
                if len(paths) % ENUM_UPDATE_INTERVAL == 0:
                    self.countUpdate.emit(len(paths))
        except OSError as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(paths)


class WorkerSignals(QObject):
    """Shared signal hub — one instance is passed to every HashWorker in a batch
    so results can be connected to a single GUI-thread slot."""
    finished = Signal(object)  # ScanResult


class HashWorker(QRunnable):
    """Computes CRC32 for a single file (or reuses a cached value if the
    file's size/mtime haven't changed) and emits the result via shared
    signals."""

    def __init__(self, path: str, generation: int, signals: WorkerSignals, cache: dict):
        super().__init__()
        self.path = path
        self.generation = generation
        self.signals = signals
        self.cache = cache  # read-only from this thread; main thread owns writes
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        try:
            size, crc, mtime_ns, hit = hash_or_cached(self.path, self.cache)
            self.signals.finished.emit(
                ScanResult(
                    path=self.path, filesize=size, crc32=crc,
                    generation=self.generation, mtime_ns=mtime_ns, cache_hit=hit,
                )
            )
        except Exception as exc:  # noqa: BLE001 - surface any read error per-file
            self.signals.finished.emit(
                ScanResult(path=self.path, filesize=-1, crc32="", generation=self.generation, error=str(exc))
            )
