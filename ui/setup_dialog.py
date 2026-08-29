"""First-run setup / Preferences dialog.

First run: asks for three default directories only (where CSVs usually
live, where files usually get scanned from, where the organized collection
should land) -- a brand new user needs these to do anything useful, but has
no basis yet to judge the behavior preferences below, so those are left at
sensible hardcoded starting points until the user's actually used the tool
a bit.

Opened later (via the Preferences menu item), the full dialog also shows
Default Behavior and Reporting sections -- things that are genuinely
"set once and forget" for how someone actually uses the tool (confirmed
directly with the primary user: Copy-vs-Move default, whether to clean up
emptied directories, recursive-scan default, and the reporting toggles are
all things they set once and never touch again), so they don't need to
live on the main window taking up space every single session. Deliberately
NOT a multi-page/tabbed settings UI -- the app's scope doesn't justify
that; a handful of plain grouped sections in one window is the right size.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QPushButton,
    QLabel, QFileDialog, QDialogButtonBox, QWidget, QGroupBox, QRadioButton,
    QButtonGroup, QCheckBox, QSpinBox,
)


class SetupDialog(QDialog):
    def __init__(self, parent=None, initial: Optional[dict] = None, first_run: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Reliquarium" if first_run else "Preferences")
        self.setMinimumWidth(560)
        self._build_ui(initial or {}, first_run)

    def _build_ui(self, initial: dict, first_run: bool):
        root = QVBoxLayout(self)

        if first_run:
            intro = QLabel(
                "Set up your usual folders once and Reliquarium "
                "will default to them every time it starts. Everything below "
                "is optional, can still be overridden per-scan, and can be "
                "revisited later -- along with more behavior preferences -- "
                "from Preferences in the File menu."
            )
            intro.setWordWrap(True)
            root.addWidget(intro)

        dirs_group = QGroupBox("Default Directories")
        form = QFormLayout(dirs_group)

        self.csv_dir_edit = QLineEdit(initial.get("csv_dir", ""))
        self.csv_dir_edit.setPlaceholderText("Folder where your catalog CSVs usually live...")
        form.addRow("CSV Directory:", self._row_with_browse(self.csv_dir_edit))

        self.scan_dir_edit = QLineEdit(initial.get("scan_dir", ""))
        self.scan_dir_edit.setPlaceholderText("Folder to scan for files by default...")
        form.addRow("Ingest Directory:", self._row_with_browse(self.scan_dir_edit))

        self.output_dir_edit = QLineEdit(initial.get("output_dir", ""))
        self.output_dir_edit.setPlaceholderText("Where organized collections should land by default...")
        form.addRow("Collection Base Directory:", self._row_with_browse(self.output_dir_edit))

        root.addWidget(dirs_group)

        # Behavior and reporting preferences: ALWAYS constructed AND
        # ALWAYS added to the layout, so their widgets always have a
        # stable Qt parent (this dialog) -- just hidden, not omitted,
        # during first-run. A widget that's constructed but never added
        # to any layout has no Qt-level parent and no surviving Python
        # reference once this method returns, which gives it undefined
        # lifetime: PySide6/shiboken may destroy the underlying C++
        # object at any point after that, including before values() gets
        # a chance to read it after the dialog closes. That's exactly
        # what conditionally SKIPPING addWidget() here used to do, and
        # it's not something that was ever actually safe -- it just
        # happened not to get garbage-collected in time on Windows.
        # setVisible(False) keeps them properly parented (and correctly
        # takes no layout space) while still being invisible/inert during
        # first-run, without the lifetime risk.
        behavior_group = self._build_behavior_group(initial)
        reporting_group = self._build_reporting_group(initial)
        root.addWidget(behavior_group)
        root.addWidget(reporting_group)
        if first_run:
            behavior_group.setVisible(False)
            reporting_group.setVisible(False)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText("Skip" if first_run else "Cancel")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_behavior_group(self, initial: dict) -> QGroupBox:
        group = QGroupBox("Default Behavior")
        layout = QVBoxLayout(group)

        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("Default action:"))
        self.default_copy_radio = QRadioButton("Copy")
        self.default_move_radio = QRadioButton("Move")
        self._default_op_group = QButtonGroup(self)
        self._default_op_group.addButton(self.default_copy_radio)
        self._default_op_group.addButton(self.default_move_radio)
        if initial.get("default_operation", "copy") == "move":
            self.default_move_radio.setChecked(True)
        else:
            self.default_copy_radio.setChecked(True)
        op_row.addWidget(self.default_copy_radio)
        op_row.addWidget(self.default_move_radio)
        op_row.addStretch(1)
        layout.addLayout(op_row)

        self.default_delete_empty_dirs_check = QCheckBox("Delete empty directories left behind after Move")
        self.default_delete_empty_dirs_check.setToolTip(
            "After a Move, removes any directory a moved file's parent folder(s) left "
            "empty -- walking upward until a folder still has something in it, or the "
            "Scan Directory itself is reached (which is never removed). Has no effect "
            "when the action is Copy, since Copy never empties the source."
        )
        self.default_delete_empty_dirs_check.setChecked(bool(initial.get("default_delete_empty_dirs", False)))
        layout.addWidget(self.default_delete_empty_dirs_check)

        self.default_recursive_check = QCheckBox("Scan subdirectories by default")
        self.default_recursive_check.setChecked(bool(initial.get("default_recursive", True)))
        layout.addWidget(self.default_recursive_check)

        return group

    def _build_reporting_group(self, initial: dict) -> QGroupBox:
        group = QGroupBox("Reporting")
        layout = QVBoxLayout(group)

        self.verify_collection_dir_check = QCheckBox(
            "Also verify Base Collections Directory for reports (catches files already sorted in past runs)"
        )
        self.verify_collection_dir_check.setToolTip(
            "Without this, a completeness report only reflects files found in THIS scan's ingest "
            "directory -- a disc that's already 100% sorted from a previous run would wrongly show "
            "as entirely missing if none of its files happen to be in today's ingest folder. "
            "Uses the same hash cache, so repeat verification passes are fast after the first one."
        )
        self.verify_collection_dir_check.setChecked(bool(initial.get("verify_collection_dir", True)))
        layout.addWidget(self.verify_collection_dir_check)

        self.auto_open_report_check = QCheckBox("Automatically open report after processing")
        self.auto_open_report_check.setToolTip(
            "Opens the report(s) generated after Process Selected with your default text editor, "
            "same as double-clicking the file. If a move touched more than one collection, each "
            "one's report opens separately."
        )
        self.auto_open_report_check.setChecked(bool(initial.get("auto_open_report", False)))
        layout.addWidget(self.auto_open_report_check)

        self.notify_long_operations_check = QCheckBox("Show a desktop notification after long scans or moves")
        self.notify_long_operations_check.setToolTip(
            "Fires a system notification when a Scan or a Process Selected (move + verification) "
            "finishes, but only if that operation actually ran long enough to plausibly step away "
            "from -- a quick scan of a handful of files won't trigger one, so the ones you do get "
            "stay meaningful instead of becoming background noise."
        )
        self.notify_long_operations_check.setChecked(bool(initial.get("notify_long_operations", False)))
        layout.addWidget(self.notify_long_operations_check)

        retention_row = QHBoxLayout()
        retention_row.addWidget(QLabel("Keep last"))
        self.report_retention_spin = QSpinBox()
        self.report_retention_spin.setRange(0, 9999)
        self.report_retention_spin.setSpecialValueText("unlimited")
        self.report_retention_spin.setToolTip(
            "Older auto-generated reports for a collection are deleted once more than this many "
            "exist for it, keeping the most recent. Set to 0 for unlimited (never auto-delete). "
            "Only ever affects auto-generated, timestamped reports -- never anything you've "
            "manually saved via Generate Report...'s save dialog."
        )
        self.report_retention_spin.setValue(int(initial.get("report_retention_count", 10)))
        retention_row.addWidget(self.report_retention_spin)
        retention_row.addWidget(QLabel("auto-generated reports per collection"))
        retention_row.addStretch(1)
        layout.addLayout(retention_row)

        return group

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
            "default_operation": "move" if self.default_move_radio.isChecked() else "copy",
            "default_delete_empty_dirs": self.default_delete_empty_dirs_check.isChecked(),
            "default_recursive": self.default_recursive_check.isChecked(),
            "verify_collection_dir": self.verify_collection_dir_check.isChecked(),
            "auto_open_report": self.auto_open_report_check.isChecked(),
            "notify_long_operations": self.notify_long_operations_check.isChecked(),
            "report_retention_count": self.report_retention_spin.value(),
        }
