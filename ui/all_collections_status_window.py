"""All Collections status window.

Shows every saved collection's completion at a glance. Opening this window
reads purely from the persisted verification cache -- no disk walking, no
hashing -- so it's instant regardless of how many collections exist,
matching how the rest of the app treats that cache as trustworthy until
something actually changes it. A collection whose verification root has
never been persisted at all (nobody has ever run a full check on it)
shows as "unverified" rather than a plain 0% -- those are genuinely
different situations (nothing known, vs. checked and confirmed empty)
that would otherwise look identical and read as more alarming than
warranted. "Refresh all" is the manual escape hatch: walks every saved
collection for real, skipping Archived CSVs (same as everywhere else),
and writes through to the same shared cache the main window and
individual Collection Status windows use.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThreadPool, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTableView, QHeaderView,
    QPushButton, QLabel, QAbstractItemView, QStatusBar,
)

from core.csv_loader import load_multiple_csvs, CsvLoadError
from core.scanner import EnumerateThread, HashWorker, WorkerSignals, ScanResult
from core.report import classify_entries, per_csv_summary, OVERALL_KEY
from core.hash_cache import save_cache
from core.verification_cache import save_verification_cache
from core.path_sanitize import sanitize_windows_name

COLUMNS = ["Collection", "CSVs", "Archived", "% complete"]


class AllCollectionsStatusModel(QAbstractTableModel):
    """rows: list of (collection, name, total_csvs, archived_count, percent_complete, verified)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        _collection, name, total_csvs, archived, pct, verified = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return name
            if col == 1:
                return total_csvs
            if col == 2:
                return archived
            if col == 3:
                return f"{pct:.1f}% (unverified)" if not verified else f"{pct:.1f}%"

        if role == Qt.TextAlignmentRole and col != 0:
            return Qt.AlignRight | Qt.AlignVCenter

        if role == Qt.ForegroundRole and col == 3:
            if not verified:
                return QColor("#888880")  # neutral gray: "unknown", not "checked and broken"
            if pct >= 99.999:
                return QColor("#4caf50")
            if pct <= 0.001:
                return QColor("#f44336")
            return QColor("#ff9800")

        return None

    def sort_key(self, row_index: int, col: int):
        _collection, name, total_csvs, archived, pct, verified = self._rows[row_index]
        if col == 0:
            return name.lower()
        if col == 1:
            return total_csvs
        if col == 2:
            return archived
        if col == 3:
            # Unverified sorts as its own distinct bucket, never mixed in
            # with real percentages -- a confirmed 0% and an unchecked
            # collection shouldn't land next to each other just because
            # they display the same number.
            return (1 if verified else 0, pct)
        return 0

    def set_rows(self, rows: list):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_at(self, i: int):
        return self._rows[i]


class _NumericSortProxy(QSortFilterProxyModel):
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        model = self.sourceModel()
        return model.sort_key(left.row(), left.column()) < model.sort_key(right.row(), right.column())


class AllCollectionsStatusWindow(QMainWindow):
    def __init__(self, collections_store, output_base_dir: str,
                 hash_cache: dict, cache_path: Path,
                 verification_cache: dict, verification_cache_path: Path,
                 parent=None):
        super().__init__(parent)
        self.collections_store = collections_store
        self.output_base_dir = output_base_dir
        self.hash_cache = hash_cache                        # shared reference with the main window
        self.cache_path = cache_path
        self.verification_cache = verification_cache        # shared reference -- writes here are
        self.verification_cache_path = verification_cache_path  # immediately visible everywhere else too

        self.setWindowTitle("All Collections Status")
        self.resize(640, 420)

        self._generation = 0
        self._pending_refresh_queue: list = []   # [(collection, collection_name, csv_name, folder), ...]
        self._current_walk_entries: dict = {}    # collection.id -> entries, needed once the walk finishes
        self._current_walk_key = None            # (collection, collection_name, csv_name) in-flight
        self._scanned_by_key: dict = {}          # (collection.id, csv_name) -> [(filename, size, crc), ...]
        self._refresh_total = 0
        self._refresh_done = 0
        self._hash_total = 0
        self._hash_completed = 0
        self._enum_thread: Optional[EnumerateThread] = None
        self._worker_signals: Optional[WorkerSignals] = None

        self._build_ui()
        self._refresh_from_cache()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Every saved collection's completion, read from the last known check."))
        top_row.addStretch(1)
        self.refresh_button = QPushButton("Refresh all")
        self.refresh_button.setToolTip(
            "Walks every saved collection for real (skipping Archived CSVs) and updates the "
            "persisted verification cache -- the same one the main window and individual "
            "Collection Status windows use. This is the only thing in this window that touches "
            "disk; opening it and re-sorting are always instant, reading only what's already known."
        )
        self.refresh_button.clicked.connect(self._start_refresh_all)
        top_row.addWidget(self.refresh_button)
        layout.addLayout(top_row)

        self.model = AllCollectionsStatusModel(self)
        self.proxy = _NumericSortProxy(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    # ------------------------------------------------------------------
    # Instant read from the persisted cache -- no disk access at all
    # ------------------------------------------------------------------
    def _refresh_from_cache(self):
        collections = self.collections_store.all()
        rows = [self._compute_row_from_cache(c) for c in collections]
        self.model.set_rows(rows)
        total_csvs = sum(r[2] for r in rows)
        self.status_bar.showMessage(
            f"{len(rows)} collection(s), {total_csvs} CSV(s) total -- reading from the last known check"
        )

    def _compute_row_from_cache(self, collection) -> tuple:
        if not collection.csvs:
            return (collection, collection.name, 0, 0, 0.0, False)

        collection_name = sanitize_windows_name(collection.name)
        try:
            entries, _warnings = load_multiple_csvs(
                collection.csvs, source_collection=collection_name,
                archived_paths=set(collection.archived_csvs),
            )
        except CsvLoadError:
            return (collection, collection.name, len(collection.csvs), len(collection.archived_csvs), 0.0, False)

        root = str(Path(self.output_base_dir) / collection_name) if self.output_base_dir else None
        verified = bool(root and root in self.verification_cache)

        combined = []
        if root:
            cached = self.verification_cache.get(root, {})
            for files in cached.values():
                combined.extend(tuple(item) for item in files)

        statuses = classify_entries(entries, combined)
        overall = per_csv_summary(statuses)[OVERALL_KEY]
        total_csvs = len({e.source_csv for e in entries})
        archived_count = len({e.source_csv for e in entries if e.archived})
        return (collection, collection.name, total_csvs, archived_count, overall["percent_complete"], verified)

    # ------------------------------------------------------------------
    # "Refresh all" -- a real walk across every collection
    # ------------------------------------------------------------------
    def _start_refresh_all(self):
        self.refresh_button.setEnabled(False)
        self.status_bar.showMessage("Loading CSVs for every collection...")
        self._generation += 1
        self._scanned_by_key = {}
        self._current_walk_entries = {}

        queue = []
        for collection in self.collections_store.all():
            if not collection.csvs or not self.output_base_dir:
                continue
            collection_name = sanitize_windows_name(collection.name)
            try:
                entries, _warnings = load_multiple_csvs(
                    collection.csvs, source_collection=collection_name,
                    archived_paths=set(collection.archived_csvs),
                )
            except CsvLoadError:
                continue
            self._current_walk_entries[collection.id] = entries
            # Archived CSVs are always reported as complete regardless of
            # what's physically present -- no point walking their folders.
            csv_names = sorted({e.source_csv for e in entries if not e.archived})
            root = Path(self.output_base_dir) / collection_name
            for csv_name in csv_names:
                folder = root / csv_name
                if folder.is_dir():
                    queue.append((collection, collection_name, csv_name, str(folder)))

        self._pending_refresh_queue = queue
        self._refresh_total = len(queue)
        self._refresh_done = 0

        if not queue:
            self.status_bar.showMessage(
                "Nothing to verify -- set a Base Collections Directory, or nothing's been sorted into any collection yet."
            )
            self.refresh_button.setEnabled(True)
            return

        self.status_bar.showMessage(f"Verifying {len(queue)} CSV folder(s) across every collection...")
        self._walk_next()

    def _walk_next(self):
        if not self._pending_refresh_queue:
            save_cache(self.cache_path, self.hash_cache)
            self._persist_all_and_finish()
            return
        collection, collection_name, csv_name, folder = self._pending_refresh_queue.pop(0)
        self._current_walk_key = (collection, collection_name, csv_name)
        self._refresh_done += 1
        self.status_bar.showMessage(
            f"Verifying {collection_name}/{csv_name} ({self._refresh_done}/{self._refresh_total})..."
        )
        self._enum_thread = EnumerateThread(folder, True, self)
        self._enum_thread.failed.connect(self._on_enum_failed)
        self._enum_thread.done.connect(self._on_enum_done)
        self._enum_thread.start()

    def _on_enum_failed(self, message: str):
        collection, _collection_name, csv_name = self._current_walk_key
        self._scanned_by_key[(collection.id, csv_name)] = []
        self._walk_next()

    def _on_enum_done(self, paths: list):
        collection, _collection_name, csv_name = self._current_walk_key
        if not paths:
            self._scanned_by_key[(collection.id, csv_name)] = []
            self._walk_next()
            return

        self._hash_total = len(paths)
        self._hash_completed = 0

        self._worker_signals = WorkerSignals()
        self._worker_signals.finished.connect(self._on_hash_result)

        generation = self._generation
        for path in paths:
            worker = HashWorker(path, generation, self._worker_signals, self.hash_cache)
            QThreadPool.globalInstance().start(worker)

    def _on_hash_result(self, result: ScanResult):
        if result.generation != self._generation:
            return  # stale -- a newer Refresh all click already superseded this one

        collection, collection_name, csv_name = self._current_walk_key
        self._hash_completed += 1
        self.status_bar.showMessage(
            f"Verifying {collection_name}/{csv_name}: {self._hash_completed} / {self._hash_total} "
            f"({self._refresh_done}/{self._refresh_total} CSVs)"
        )

        if not result.error:
            filename = os.path.basename(result.path)
            bucket = self._scanned_by_key.setdefault((collection.id, csv_name), [])
            bucket.append((filename, result.filesize, result.crc32))
            if not result.cache_hit:
                self.hash_cache[result.path] = {
                    "size": result.filesize,
                    "mtime_ns": result.mtime_ns,
                    "crc32": result.crc32,
                }

        if self._hash_completed >= self._hash_total:
            self._walk_next()

    def _persist_all_and_finish(self):
        # Group the flat (collection.id, csv)-keyed results back into the
        # on-disk root-keyed format -- one write covers every collection
        # this refresh touched, not just one.
        by_root: dict = {}
        collections_by_id = {c.id: c for c in self.collections_store.all()}
        for (collection_id, csv_name), files in self._scanned_by_key.items():
            collection = collections_by_id.get(collection_id)
            if not collection:
                continue
            root = str(Path(self.output_base_dir) / sanitize_windows_name(collection.name))
            by_root.setdefault(root, {})[csv_name] = [list(item) for item in files]
        for root, csv_map in by_root.items():
            self.verification_cache[root] = csv_map
        save_verification_cache(self.verification_cache_path, self.verification_cache)

        self._refresh_from_cache()
        self.refresh_button.setEnabled(True)
