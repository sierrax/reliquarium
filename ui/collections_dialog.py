"""Dialog for creating, editing, and deleting named collections."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QFileDialog, QMessageBox, QInputDialog,
    QAbstractItemView,
)

from core.collections_store import CollectionsStore, Collection


class CollectionsDialog(QDialog):
    """Modal dialog: left side lists collections, right side edits the
    selected one's name and member CSVs. Every change is saved to disk
    immediately via the CollectionsStore -- there's no separate Save button
    because there's nothing to lose by closing early."""

    def __init__(self, store: CollectionsStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Manage Collections")
        self.resize(680, 420)
        self._current: Optional[Collection] = None
        self._build_ui()
        self._reload_list()

    def _build_ui(self):
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        left.addWidget(QLabel("Collections:"))
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_select)
        left.addWidget(self.list_widget, stretch=1)

        list_btn_row = QHBoxLayout()
        self.new_button = QPushButton("New...")
        self.new_button.clicked.connect(self._new_collection)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self._delete_collection)
        self.delete_button.setEnabled(False)
        list_btn_row.addWidget(self.new_button)
        list_btn_row.addWidget(self.delete_button)
        left.addLayout(list_btn_row)
        root.addLayout(left, stretch=1)

        right = QVBoxLayout()
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setEnabled(False)
        self.name_edit.editingFinished.connect(self._rename_current)
        name_row.addWidget(self.name_edit)
        right.addLayout(name_row)

        right.addWidget(QLabel(
            "CSVs in this collection (each gets its own subfolder under the collection):"
        ))
        self.csv_list = QListWidget()
        self.csv_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        right.addWidget(self.csv_list, stretch=1)

        csv_btn_row = QHBoxLayout()
        self.add_csv_button = QPushButton("Add CSV(s)...")
        self.add_csv_button.clicked.connect(self._add_csvs)
        self.add_csv_button.setEnabled(False)
        self.remove_csv_button = QPushButton("Remove Selected")
        self.remove_csv_button.clicked.connect(self._remove_selected_csvs)
        self.remove_csv_button.setEnabled(False)
        csv_btn_row.addWidget(self.add_csv_button)
        csv_btn_row.addWidget(self.remove_csv_button)
        right.addLayout(csv_btn_row)

        archive_btn_row = QHBoxLayout()
        self.archive_csv_button = QPushButton("Archive Selected")
        self.archive_csv_button.setToolTip(
            "Mark the selected CSV(s) as Archived: complete, but no longer\n"
            "physically present in the live Base Collections Directory\n"
            "(e.g. burned to disc). Archived CSVs are always reported as\n"
            "complete and are never re-verified."
        )
        self.archive_csv_button.clicked.connect(self._archive_selected_csvs)
        self.archive_csv_button.setEnabled(False)
        self.unarchive_csv_button = QPushButton("Unarchive Selected")
        self.unarchive_csv_button.setToolTip(
            "Un-mark the selected CSV(s) as Archived -- they'll be treated\n"
            "as a normal, live part of the collection again and verified\n"
            "the next time something checks this collection."
        )
        self.unarchive_csv_button.clicked.connect(self._unarchive_selected_csvs)
        self.unarchive_csv_button.setEnabled(False)
        archive_btn_row.addWidget(self.archive_csv_button)
        archive_btn_row.addWidget(self.unarchive_csv_button)
        right.addLayout(archive_btn_row)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        right.addLayout(close_row)

        root.addLayout(right, stretch=2)

    # -- list management -------------------------------------------------
    def _reload_list(self, select_id: Optional[str] = None):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        selected_item = None
        for c in self.store.all():
            item = QListWidgetItem(c.name)
            item.setData(Qt.UserRole, c.id)
            self.list_widget.addItem(item)
            if select_id and c.id == select_id:
                selected_item = item
        self.list_widget.blockSignals(False)
        if selected_item is not None:
            self.list_widget.setCurrentItem(selected_item)
        else:
            self._on_select(self.list_widget.currentItem(), None)

    def _on_select(self, current, _previous):
        if current is None:
            self._current = None
            self.name_edit.setEnabled(False)
            self.name_edit.clear()
            self.csv_list.clear()
            self.add_csv_button.setEnabled(False)
            self.remove_csv_button.setEnabled(False)
            self.archive_csv_button.setEnabled(False)
            self.unarchive_csv_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return
        collection_id = current.data(Qt.UserRole)
        self._current = self.store.get(collection_id)
        self.name_edit.setEnabled(True)
        self.name_edit.setText(self._current.name)
        self.add_csv_button.setEnabled(True)
        self.remove_csv_button.setEnabled(True)
        self.archive_csv_button.setEnabled(True)
        self.unarchive_csv_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self._refresh_csv_list()

    def _refresh_csv_list(self):
        self.csv_list.clear()
        if not self._current:
            return
        for csv_path in self._current.csvs:
            label = csv_path
            tags = []
            if not Path(csv_path).exists():
                tags.append("missing")
            if self._current.is_archived(csv_path):
                tags.append("Archived")
            if tags:
                label += "   [" + ", ".join(tags) + "]"
            self.csv_list.addItem(label)

    # -- actions -----------------------------------------------------------
    def _new_collection(self):
        name, ok = QInputDialog.getText(self, "New Collection", "Collection name:")
        name = name.strip()
        if not ok or not name:
            return
        c = self.store.add(name)
        self._reload_list(select_id=c.id)

    def _rename_current(self):
        if not self._current:
            return
        new_name = self.name_edit.text().strip()
        if not new_name or new_name == self._current.name:
            return
        self._current.name = new_name
        self.store.update(self._current)
        self._reload_list(select_id=self._current.id)

    def _delete_collection(self):
        if not self._current:
            return
        confirm = QMessageBox.question(
            self, "Delete Collection",
            f"Delete collection '{self._current.name}'? "
            "This only removes it from Reliquarium -- the "
            "CSV files themselves are untouched.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.store.delete(self._current.id)
        self._current = None
        self._reload_list()

    def _add_csvs(self):
        if not self._current:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Add CSV(s)", "", "CSV Files (*.csv);;All Files (*)")
        if not paths:
            return
        existing = set(self._current.csvs)
        for p in paths:
            if p not in existing:
                self._current.csvs.append(p)
                existing.add(p)
        self.store.update(self._current)
        self._refresh_csv_list()

    def _remove_selected_csvs(self):
        if not self._current:
            return
        selected_rows = {self.csv_list.row(item) for item in self.csv_list.selectedItems()}
        if not selected_rows:
            return
        removed_paths = {p for i, p in enumerate(self._current.csvs) if i in selected_rows}
        self._current.csvs = [p for i, p in enumerate(self._current.csvs) if i not in selected_rows]
        # A removed CSV shouldn't leave a stale entry in archived_csvs behind.
        self._current.archived_csvs = [p for p in self._current.archived_csvs if p not in removed_paths]
        self.store.update(self._current)
        self._refresh_csv_list()

    def _archive_selected_csvs(self):
        self._set_archived_for_selected(True)

    def _unarchive_selected_csvs(self):
        self._set_archived_for_selected(False)

    def _set_archived_for_selected(self, archived: bool):
        if not self._current:
            return
        selected_rows = {self.csv_list.row(item) for item in self.csv_list.selectedItems()}
        if not selected_rows:
            return
        changed = False
        for i in selected_rows:
            if i >= len(self._current.csvs):
                continue
            path = self._current.csvs[i]
            already_archived = path in self._current.archived_csvs
            if archived and not already_archived:
                self._current.archived_csvs.append(path)
                changed = True
            elif not archived and already_archived:
                self._current.archived_csvs.remove(path)
                changed = True
        if changed:
            self.store.update(self._current)
            self._refresh_csv_list()
