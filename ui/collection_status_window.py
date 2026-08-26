"""Collection Status window.

A per-CSV completeness dashboard for a saved collection, independent of
any particular ingest scan -- "how healthy is what's already sorted?"
Modeless (non-blocking): runs its own verification pass against the
collection's own directory tree using the shared hash cache, and stays
open while you keep working in the main window.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThreadPool, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableView, QHeaderView, QProgressBar, QStatusBar, QAbstractItemView,
)

from core.csv_loader import load_multiple_csvs, CsvLoadError
from core.scanner import EnumerateThread, HashWorker, WorkerSignals, ScanResult
from core.report import classify_entries, per_csv_summary, format_report_text, prune_old_reports, OVERALL_KEY
from core.hash_cache import save_cache
from core.verification_cache import save_verification_cache
from core.path_sanitize import sanitize_windows_name
from core.collections_store import Collection

COLUMNS = ["CSV", "Total", "Correct", "Archived", "Bad", "Missing", "% Complete"]


class CollectionStatusModel(QAbstractTableModel):
    """rows: list of (csv_name, total, correct, archived, bad, missing, percent_complete)"""

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
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 6:
                return f"{row[6]:.1f}%"
            return row[col]

        if role == Qt.TextAlignmentRole and col != 0:
            return Qt.AlignRight | Qt.AlignVCenter

        if role == Qt.ForegroundRole and col == 6:
            pct = row[6]
            if pct >= 99.999:
                return QColor("#4caf50")
            if pct <= 0.001:
                return QColor("#f44336")
            return QColor("#ff9800")

        return None

    # Sort by the underlying numeric/string value, not the formatted display text
    def sort_key(self, row_index: int, col: int):
        return self._rows[row_index][col]

    def set_rows(self, rows: list):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_at(self, i: int):
        return self._rows[i]


class _NumericSortProxy(QSortFilterProxyModel):
    """Sorts numeric columns numerically instead of alphabetically as text."""

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        col = left.column()
        if col == 0:
            return str(left.data()).lower() < str(right.data()).lower()
        source = self.sourceModel()
        return source.sort_key(left.row(), col) < source.sort_key(right.row(), col)


class CollectionStatusWindow(QMainWindow):
    def __init__(self, collection: Collection, output_base_dir: str,
                 hash_cache: dict, cache_path: Path,
                 verification_cache: Optional[dict] = None,
                 verification_cache_path: Optional[Path] = None,
                 reports_dir: Optional[Path] = None,
                 report_retention_count: int = 0, parent=None):
        super().__init__(parent)
        self.collection = collection
        self.output_base_dir = output_base_dir
        self.hash_cache = hash_cache  # shared reference with the main window
        self.cache_path = cache_path
        self.verification_cache = verification_cache  # shared reference with the main window --
                                                         # writes here are immediately visible there too
        self.verification_cache_path = verification_cache_path
        self.reports_dir = reports_dir  # where to auto-save a report after each verification
        self.report_retention_count = report_retention_count  # 0 = unlimited, matching the main
                                                         # window's own setting at the time this
                                                         # window was opened (a live snapshot, not
                                                         # re-read afterward -- consistent with how
                                                         # the rest of this window's config works)

        self.setWindowTitle(f"Collection Status — {collection.name}")
        self.resize(760, 480)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self._catalog_entries: list = []
        self._scanned_files_by_csv: dict = {}  # csv_name -> [(filename, filesize, crc32), ...]
        self._verify_root: Optional[str] = None
        self._pending_verify_queue: list = []
        self._current_verify_csv_name = ""
        self._enum_thread: Optional[EnumerateThread] = None
        self._worker_signals: Optional[WorkerSignals] = None
        self._hash_total = 0
        self._hash_completed = 0
        self._generation = 0

        self._build_ui()
        self._start_verification()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        header_row = QHBoxLayout()
        header_label = QLabel(f"<b>{self.collection.name}</b> — {len(self.collection.csvs)} CSV(s)")
        header_row.addWidget(header_label)
        header_row.addStretch(1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._start_verification)
        header_row.addWidget(self.refresh_button)
        layout.addLayout(header_row)

        self.model = CollectionStatusModel(self)
        self.proxy = _NumericSortProxy(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, stretch=1)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Starting verification...")

    # ------------------------------------------------------------------
    def _start_verification(self):
        self.refresh_button.setEnabled(False)
        self.progress.setRange(0, 0)  # busy indicator until we know a total
        self.progress.setValue(0)
        self.status_bar.showMessage("Loading CSVs...")
        self._generation += 1

        try:
            entries, warnings = load_multiple_csvs(
                self.collection.csvs,
                source_collection=sanitize_windows_name(self.collection.name),
                archived_paths=set(self.collection.archived_csvs),
            )
        except CsvLoadError as exc:
            self.status_bar.showMessage(f"Could not load CSVs: {exc}")
            self.refresh_button.setEnabled(True)
            return
        self._catalog_entries = entries
        self._scanned_files_by_csv = {}  # this is always a full check -- replaces everything for this root

        collection_folder = sanitize_windows_name(self.collection.name)
        self._verify_root = str(Path(self.output_base_dir) / collection_folder) if self.output_base_dir else None

        if not self._verify_root:
            self.status_bar.showMessage(
                "No Base Collections Directory configured -- showing catalog-only totals (everything Missing)."
            )
            self._finish_verification()
            return

        # Archived CSVs are always reported as complete regardless of what's
        # physically present (see core/report.py), so there's no point
        # walking their folders at all.
        all_csv_names = sorted({e.source_csv for e in entries if not e.archived})
        queue = []
        for csv_name in all_csv_names:
            folder = Path(self._verify_root) / csv_name
            if folder.is_dir():
                queue.append((csv_name, str(folder)))

        if not queue:
            if entries and not all_csv_names:
                # Every CSV in this collection is Archived -- nothing needed
                # verifying, and that's not a problem to report as if it were.
                self.status_bar.showMessage(
                    "Every CSV in this collection is Archived -- nothing to verify."
                )
            else:
                self.status_bar.showMessage(
                    "Collection directory not found yet under the Base Collections Directory "
                    "-- showing catalog-only totals (everything Missing)."
                )
            self._finish_verification()
            return

        self._pending_verify_queue = queue
        self.status_bar.showMessage(f"Verifying {len(queue)} CSV folder(s)...")
        self._walk_next_verify_csv()

    def _walk_next_verify_csv(self):
        if not self._pending_verify_queue:
            save_cache(self.cache_path, self.hash_cache)
            self._finish_verification()
            return
        csv_name, folder = self._pending_verify_queue.pop(0)
        self._current_verify_csv_name = csv_name
        self.status_bar.showMessage(f"Enumerating {csv_name}...")
        self._enum_thread = EnumerateThread(folder, True, self)
        self._enum_thread.failed.connect(self._on_enum_failed)
        self._enum_thread.done.connect(self._on_enum_done)
        self._enum_thread.start()

    def _on_enum_failed(self, message: str):
        self.status_bar.showMessage(f"Could not read {self._current_verify_csv_name} ({message}).")
        self._scanned_files_by_csv[self._current_verify_csv_name] = []
        self._walk_next_verify_csv()

    def _on_enum_done(self, paths: list):
        if not paths:
            self._scanned_files_by_csv[self._current_verify_csv_name] = []
            self._walk_next_verify_csv()
            return

        self._hash_total = len(paths)
        self._hash_completed = 0
        self.progress.setRange(0, self._hash_total)
        self.status_bar.showMessage(f"Hashing {self._current_verify_csv_name}: 0 / {self._hash_total}")

        self._worker_signals = WorkerSignals()
        self._worker_signals.finished.connect(self._on_hash_result)

        generation = self._generation
        for path in paths:
            worker = HashWorker(path, generation, self._worker_signals, self.hash_cache)
            QThreadPool.globalInstance().start(worker)

    def _on_hash_result(self, result: ScanResult):
        if result.generation != self._generation:
            return  # stale, from a verification pass a Refresh click already superseded

        self._hash_completed += 1
        self.progress.setValue(self._hash_completed)
        self.status_bar.showMessage(
            f"Hashing {self._current_verify_csv_name}: {self._hash_completed} / {self._hash_total}"
        )

        if not result.error:
            filename = os.path.basename(result.path)
            bucket = self._scanned_files_by_csv.setdefault(self._current_verify_csv_name, [])
            bucket.append((filename, result.filesize, result.crc32))
            if not result.cache_hit:
                self.hash_cache[result.path] = {
                    "size": result.filesize,
                    "mtime_ns": result.mtime_ns,
                    "crc32": result.crc32,
                }

        if self._hash_completed >= self._hash_total:
            self._walk_next_verify_csv()  # moves to the next queued CSV, or finishes if none left

    def _finish_verification(self):
        combined = []
        for files in self._scanned_files_by_csv.values():
            combined.extend(files)
        summary = per_csv_summary(classify_entries(self._catalog_entries, combined))
        rows = []
        for csv_name, data in summary.items():
            if csv_name == OVERALL_KEY:
                continue
            rows.append((
                csv_name, data["total"], len(data["correct"]), len(data["archived"]),
                len(data["bad"]), len(data["missing"]), data["percent_complete"],
            ))
        rows.sort(key=lambda r: r[0].lower())
        self.model.set_rows(rows)

        overall = summary.get(
            OVERALL_KEY,
            {"total": 0, "correct": [], "archived": [], "bad": [], "missing": [], "percent_complete": 0.0},
        )
        archived_note = f", {len(overall['archived'])} archived" if overall["archived"] else ""
        status_text = (
            f"{len(rows)} CSV(s) — overall: {len(overall['correct'])}/{overall['total']} correct"
            f"{archived_note} ({overall['percent_complete']:.1f}% complete)"
        )

        self._persist_verification()
        report_note = self._save_report(summary)
        self.status_bar.showMessage(status_text + report_note)
        self.refresh_button.setEnabled(True)

    def _persist_verification(self):
        """Writes this full verification's results into the SAME shared,
        disk-persisted cache the main window's post-move scoped checks
        read from. This is the piece that used to be missing entirely --
        without it, a full check here looked correct on screen but the
        main window never learned about it, so its next scoped check would
        see nothing for any CSV except whichever one it happened to touch."""
        if self.verification_cache is None or self.verification_cache_path is None or not self._verify_root:
            return
        self.verification_cache[self._verify_root] = {
            csv_name: [list(item) for item in files]
            for csv_name, files in self._scanned_files_by_csv.items()
        }
        save_verification_cache(self.verification_cache_path, self.verification_cache)

    def _save_report(self, summary: dict) -> str:
        """Auto-saves a timestamped report from this verification pass,
        same convention as the main window's post-move auto-report. Opening
        or refreshing this window IS a real verification of the collection
        directory, so -- per the same rule everywhere else in the app -- a
        report belongs here too, not just after a move. Returns a short
        status-bar suffix describing what happened (empty string if there's
        nothing to report, e.g. no reports directory configured)."""
        if not self.reports_dir:
            return ""
        try:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return f"  (could not create reports directory: {exc})"

        title = f"Collection Report — {self.collection.name}"
        text = format_report_text(summary, title=title)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        collection_folder = sanitize_windows_name(self.collection.name)
        name = f"{collection_folder}_{stamp}.txt"
        path = self.reports_dir / name
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as exc:
            return f"  (report save failed: {exc})"

        deleted = prune_old_reports(self.reports_dir, collection_folder, self.report_retention_count)
        prune_note = f", pruned {len(deleted)} older" if deleted else ""
        return f"  — report saved to {path.name}{prune_note}"
