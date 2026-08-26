"""Table model backing the scan/match results view."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor


@dataclass
class RowRecord:
    status: str            # "Matched" / "Unmatched" / "Error"
    filename: str
    source_path: str
    filesize: int
    crc32: str
    target_dir: str = ""
    result: str = ""       # populated after move/copy
    checked: bool = False
    source_csv: str = ""   # which CSV this match came from (empty for Unmatched/Error)
    source_collection: str = ""  # which collection that CSV belongs to (empty if none)


COLUMNS = ["", "Status", "Filename", "Size", "CRC32", "Target Directory", "Result"]

_MATCHED_COLOR = QColor("#4caf50")
_UNMATCHED_COLOR = QColor("#f44336")
_ERROR_COLOR = QColor("#ff9800")


def human_size(n: int) -> str:
    if n < 0:
        return "?"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{n} B"


class ResultsTableModel(QAbstractTableModel):
    checkedCountChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[RowRecord] = []

    # -- Qt model interface --------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0:
            row = self._rows[index.row()]
            if row.status == "Matched":
                return base | Qt.ItemIsUserCheckable
            return base
        return base

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.CheckStateRole and col == 0:
            if row.status == "Matched":
                return Qt.Checked if row.checked else Qt.Unchecked
            return None

        if role == Qt.DisplayRole:
            if col == 1:
                return row.status
            if col == 2:
                return row.filename
            if col == 3:
                return human_size(row.filesize)
            if col == 4:
                return row.crc32
            if col == 5:
                return row.target_dir
            if col == 6:
                return row.result

        if role == Qt.ToolTipRole and col == 2:
            return row.source_path

        if role == Qt.ForegroundRole and col == 1:
            if row.status == "Matched":
                return _MATCHED_COLOR
            if row.status == "Unmatched":
                return _UNMATCHED_COLOR
            if row.status == "Error":
                return _ERROR_COLOR

        return None

    def setData(self, index: QModelIndex, value, role=Qt.EditRole):
        if role == Qt.CheckStateRole and index.column() == 0:
            self._rows[index.row()].checked = value == Qt.Checked
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            self.checkedCountChanged.emit(self.checked_count())
            return True
        return False

    # -- Convenience API --------------------------------------------------
    def clear(self):
        self.beginResetModel()
        self._rows = []
        self.endResetModel()
        self.checkedCountChanged.emit(0)

    def set_rows(self, rows: list[RowRecord]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        self.checkedCountChanged.emit(self.checked_count())

    def add_row(self, row: RowRecord):
        n = len(self._rows)
        self.beginInsertRows(QModelIndex(), n, n)
        self._rows.append(row)
        self.endInsertRows()

    def row_at(self, i: int) -> RowRecord:
        return self._rows[i]

    def all_rows(self) -> list[RowRecord]:
        return self._rows

    def checked_count(self) -> int:
        return sum(1 for r in self._rows if r.checked)

    def status_counts(self) -> dict[str, int]:
        counts = {"Matched": 0, "Unmatched": 0, "Error": 0}
        for r in self._rows:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts

    def set_all_checked(self, checked: bool, only_status: Optional[str] = None):
        if not self._rows:
            return
        for r in self._rows:
            if only_status is None or r.status == only_status:
                r.checked = checked
        top_left = self.index(0, 0)
        bottom_right = self.index(len(self._rows) - 1, 0)
        self.dataChanged.emit(top_left, bottom_right, [Qt.CheckStateRole])
        self.checkedCountChanged.emit(self.checked_count())

    def set_result(self, row_index: int, result_text: str):
        self._rows[row_index].result = result_text
        idx = self.index(row_index, 6)
        self.dataChanged.emit(idx, idx, [Qt.DisplayRole])


class StatusFilterProxyModel(QSortFilterProxyModel):
    """Filters rows by status ('All'/'Matched'/'Unmatched'/'Error') AND a
    case-insensitive filename search, combined."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = "Matched"
        self._search = ""
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)

    def set_status_filter(self, status: str):
        self._status = status
        self.invalidateFilter()

    def set_search_text(self, text: str):
        self._search = text.lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if self._status != "All":
            status_idx = model.index(source_row, 1, source_parent)
            if model.data(status_idx, Qt.DisplayRole) != self._status:
                return False
        if self._search:
            name_idx = model.index(source_row, 2, source_parent)
            name = (model.data(name_idx, Qt.DisplayRole) or "").lower()
            if self._search not in name:
                return False
        return True
