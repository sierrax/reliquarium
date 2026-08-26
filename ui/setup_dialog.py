"""First-run setup / "change defaults" dialog.

Asks for three default directories: where CSVs usually live, where files
usually get scanned from (ingest), and where the organized collection should
land (output base). All three are optional and everything can still be
overridden per-scan in the main window -- this dialog only controls what
the main window's fields are pre-filled with on startup.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QPushButton,
    QLabel, QFileDialog, QDialogButtonBox, QWidget,
)


class SetupDialog(QDialog):
    def __init__(self, parent=None, initial: Optional[dict] = None, first_run: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Reliquarium" if first_run else "Change Default Directories")
        self.setMinimumWidth(560)
        self._build_ui(initial or {}, first_run)

    def _build_ui(self, initial: dict, first_run: bool):
        root = QVBoxLayout(self)

        if first_run:
            intro = QLabel(
                "Set up your usual folders once and Reliquarium "
                "will default to them every time it starts. Everything below "
                "is optional, can still be overridden per-scan, and can be "
                "revisited later from File → Change Default Directories."
            )
            intro.setWordWrap(True)
            root.addWidget(intro)

        form = QFormLayout()

        self.csv_dir_edit = QLineEdit(initial.get("csv_dir", ""))
        self.csv_dir_edit.setPlaceholderText("Folder where your catalog CSVs usually live...")
        form.addRow("CSV Directory:", self._row_with_browse(self.csv_dir_edit))

        self.scan_dir_edit = QLineEdit(initial.get("scan_dir", ""))
        self.scan_dir_edit.setPlaceholderText("Folder to scan for files by default...")
        form.addRow("Ingest Directory:", self._row_with_browse(self.scan_dir_edit))

        self.output_dir_edit = QLineEdit(initial.get("output_dir", ""))
        self.output_dir_edit.setPlaceholderText("Where organized collections should land by default...")
        form.addRow("Collection Base Directory:", self._row_with_browse(self.output_dir_edit))

        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText("Skip" if first_run else "Cancel")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _row_with_browse(self, line_edit: QLineEdit) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda: self._browse_into(line_edit))
        row.addWidget(line_edit)
        row.addWidget(browse)
        return container

    def _browse_into(self, line_edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Select Directory", line_edit.text())
        if path:
            line_edit.setText(path)

    def values(self) -> dict:
        return {
            "csv_dir": self.csv_dir_edit.text().strip(),
            "scan_dir": self.scan_dir_edit.text().strip(),
            "output_dir": self.output_dir_edit.text().strip(),
        }
