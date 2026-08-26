"""Main window for Reliquarium."""
from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QSettings
from PySide6.QtGui import QIcon, QActionGroup
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLineEdit, QLabel, QCheckBox, QSpinBox, QProgressBar,
    QTableView, QHeaderView, QComboBox, QPlainTextEdit, QFileDialog,
    QMessageBox, QRadioButton, QButtonGroup, QSplitter, QAbstractItemView,
    QGroupBox, QStatusBar, QStackedWidget, QDialog, QApplication,
)

from core.csv_loader import load_multiple_csvs, load_all_collections, build_index, CsvLoadError
from core.scanner import EnumerateThread, HashWorker, WorkerSignals, ScanResult
from core.file_ops import ConflictPolicy, Operation
from core.hash_cache import default_cache_path, load_cache, save_cache, clear_cache_file
from core.verification_cache import default_verification_cache_path, load_verification_cache, save_verification_cache
from core.collections_store import CollectionsStore, default_collections_path
from core.path_sanitize import sanitize_windows_name
from core.report import classify_entries, per_csv_summary, split_by_collection, format_report_text, format_needed_csv, prune_old_reports, OVERALL_KEY
from core.os_open import open_with_default_app
from core.portable import app_data_dir, migrate_legacy_data
from core.resources import resource_path
from core.version import __version__
from ui.results_model import ResultsTableModel, RowRecord, StatusFilterProxyModel
from ui.processing_thread import ProcessingThread
from ui.collections_dialog import CollectionsDialog
from ui.setup_dialog import SetupDialog
from ui.collection_status_window import CollectionStatusWindow

try:
    import qdarktheme
except ImportError:  # theme is optional; app still runs with the default Qt style
    qdarktheme = None


def _migrate_legacy_qsettings(new_path: Path) -> bool:
    """One-time migration of the old registry-backed QSettings (org
    "MediaOrganizer", app "Media Collection Organizer") into the new
    portable settings.ini file, so an existing install's saved defaults
    and setup-complete flag aren't lost by the switch to portable, no-
    registry storage. Only runs if the new file doesn't exist yet, and
    never raises -- migration is a convenience, not something that should
    ever block startup. Returns True if anything was actually migrated."""
    if new_path.exists():
        return False
    try:
        old = QSettings("MediaOrganizer", "Media Collection Organizer")
        keys = old.allKeys()
        if not keys:
            return False
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new = QSettings(str(new_path), QSettings.IniFormat)
        for key in keys:
            new.setValue(key, old.value(key))
        new.sync()
        return True
    except Exception:
        return False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reliquarium")
        icon_path = resource_path("assets/icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._catalog_index: dict = {}
        self._catalog_entries: list = []   # full entry list from the last scan's CSV(s), for reporting
        self._scanned_files: list = []     # (filename, filesize, crc32) from the ingest scan itself
        self._collection_scanned_files_by_key: dict = {}  # (source_collection, source_csv) -> [(filename, filesize, crc32), ...]
                                                     # working copy for the CURRENTLY loaded catalog's
                                                     # collections, seeded from self._verification_cache
                                                     # (below) before any new walk results are layered on.
                                                     # Keyed by (collection, csv) rather than just csv name
                                                     # so scanning against multiple collections at once
                                                     # (which can easily share a CSV name, e.g. two
                                                     # different collections both having a "CD1") never
                                                     # conflates their data.
        self._verification_cache_path = default_verification_cache_path()
        self._verification_cache: dict = load_verification_cache(self._verification_cache_path)
                                                     # {root: {csv_name: [[filename, size, crc], ...]}} --
                                                     # persisted to disk, so a scoped verification right
                                                     # after launching the app can still trust whatever was
                                                     # confirmed in a PAST session, not just this one. This
                                                     # is a "trust it, refresh occasionally" cache like the
                                                     # hash cache: if files change outside the app between
                                                     # verifications, a full check (Collection Status
                                                     # window, or the manual report buttons) is how that
                                                     # gets caught -- worth doing occasionally regardless.
                                                     # One root per collection (or per ad hoc base), so this
                                                     # naturally supports many collections being tracked at
                                                     # once without any format change.
        self._scan_generation = 0
        self._collection_scan_generation = 0
        self._pending_verify_callback = None
        self._pending_verify_queue: list = []   # [(source_collection, csv_name, folder_path), ...] still to walk
        self._current_verify_key = ("", "")     # (source_collection, csv_name) the in-flight walk's results belong to
        self._process_success_count = 0
        self._process_touched_keys: set = set()  # (source_collection, source_csv) pairs actually moved/copied this run
        self._hash_total = 0
        self._hash_completed = 0
        self._collection_hash_total = 0
        self._collection_hash_completed = 0
        self._worker_signals: WorkerSignals | None = None
        self._collection_worker_signals: WorkerSignals | None = None
        self._enum_thread: EnumerateThread | None = None
        self._collection_enum_thread: EnumerateThread | None = None
        self._processing_thread: ProcessingThread | None = None
        self._output_base_dir: str = ""
        self._active_collection_name: str = ""  # LABEL only now (report titles, default filenames) --
                                                     # sanitized collection name, "AllCollections" for the
                                                     # scan-every-collection mode, or empty for a single ad
                                                     # hoc CSV. Target-directory resolution no longer reads
                                                     # this: it uses each matched entry's own
                                                     # source_collection instead, since a single scan can
                                                     # now span more than one collection at once.
        self._cache_hits = 0

        data_dir = app_data_dir()
        migrated_files = migrate_legacy_data(data_dir)  # one-time copy from %LOCALAPPDATA%, if present

        settings_path = data_dir / "settings.ini"
        migrated_settings = _migrate_legacy_qsettings(settings_path)  # one-time copy from the old registry
        self.settings = QSettings(str(settings_path), QSettings.IniFormat)
        self._cache_path = default_cache_path()
        self._hash_cache: dict = load_cache(self._cache_path)
        self.collections_store = CollectionsStore(default_collections_path())
        self._status_windows: list = []  # keeps open CollectionStatusWindow instances alive

        self.model = ResultsTableModel(self)
        self.proxy = StatusFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)

        self._build_ui()
        self._wire_signals()
        self._set_theme(self.settings.value("theme", "dark", type=str), persist=False)
        self._log(f"Data directory: {data_dir}")
        if migrated_files or migrated_settings:
            migrated_desc = ", ".join(migrated_files + (["settings"] if migrated_settings else []))
            self._log(f"Migrated existing data from the old storage location: {migrated_desc}")
        self._load_persisted_defaults()
        self._maybe_run_first_time_setup()
        self._update_status_bar()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        self._build_menu_bar()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addWidget(self._build_source_group())

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._build_results_group())
        splitter.addWidget(self._build_action_group())
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, stretch=1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def _build_menu_bar(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        change_defaults_action = file_menu.addAction("Change Default Directories...")
        change_defaults_action.triggered.connect(self._open_change_defaults)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

        collections_menu = menu_bar.addMenu("&Collections")
        manage_collections_menu_action = collections_menu.addAction("Manage Collections...")
        manage_collections_menu_action.triggered.connect(self._open_manage_collections)

        if qdarktheme is not None:
            view_menu = menu_bar.addMenu("&View")
            theme_menu = view_menu.addMenu("Theme")
            self.theme_action_group = QActionGroup(self)
            self.theme_action_group.setExclusive(True)

            dark_action = theme_menu.addAction("Dark")
            dark_action.setCheckable(True)
            dark_action.setData("dark")
            self.theme_action_group.addAction(dark_action)

            light_action = theme_menu.addAction("Light")
            light_action.setCheckable(True)
            light_action.setData("light")
            self.theme_action_group.addAction(light_action)

            current_theme = self.settings.value("theme", "dark", type=str)
            (light_action if current_theme == "light" else dark_action).setChecked(True)

            self.theme_action_group.triggered.connect(
                lambda action: self._set_theme(action.data())
            )

        help_menu = menu_bar.addMenu("&Help")
        about_action = help_menu.addAction("About Reliquarium")
        about_action.triggered.connect(self._show_about_dialog)

    def _set_theme(self, theme_name: str, persist: bool = True):
        """Applies a theme and logs what actually happened. Supports two
        generations of the qdarktheme package's API, since installed
        versions vary:

        - Newer versions expose setup_theme(theme_name), an all-in-one call.
        - Older versions only have load_stylesheet(theme_name), which
          returns a QSS string that has to be applied manually via
          QApplication.setStyleSheet(). This install turned out to be one
          of those -- setup_theme() didn't exist for EITHER "dark" or
          "light", which is why nothing was ever actually being themed by
          qdarktheme at all; what looked like "dark mode working" was just
          Qt's default style picking up Windows' own dark mode setting.

        Used for both the initial theme application at startup (called
        from __init__, before the window is shown, so there's no flash
        either way) and live switching from View > Theme -- one code path
        for both, so they can't silently diverge from each other."""
        applied = False
        if qdarktheme is not None:
            try:
                if hasattr(qdarktheme, "setup_theme"):
                    qdarktheme.setup_theme(theme_name)
                    applied = True
                elif hasattr(qdarktheme, "load_stylesheet"):
                    stylesheet = qdarktheme.load_stylesheet(theme_name)
                    app = QApplication.instance()
                    if app is not None:
                        app.setStyleSheet(stylesheet)
                        applied = True
            except Exception as exc:
                self._log(
                    f"Could not apply '{theme_name}' theme ({type(exc).__name__}: {exc}) "
                    f"-- falling back to the default Qt style."
                )

        if applied:
            self._log(f"Theme applied: {theme_name}")
        elif qdarktheme is not None:
            self._log(
                "Theme switching unavailable (installed qdarktheme package exposes neither "
                "setup_theme() nor load_stylesheet()) -- using the default Qt style."
            )
        else:
            self._log("Theme switching unavailable (qdarktheme package not installed) -- using the default Qt style.")

        if persist:
            self.settings.setValue("theme", theme_name)
            self.settings.sync()  # force an immediate write rather than relying on Qt's own flush timing

    def _show_about_dialog(self):
        icon_path = resource_path("assets/icon.png")
        icon_html = f'<img src="{icon_path}" width="64" height="64"><br>' if icon_path.exists() else ""
        QMessageBox.about(
            self, "About Reliquarium",
            f"<div style='text-align:center'>{icon_html}"
            f"<h3>Reliquarium</h3>"
            f"<p>Version {__version__}</p></div>"
            f"<p>A modern, multi-threaded collection-verification tool: matches "
            f"files against CSV catalogs by CRC32 checksum and organizes them "
            f"into place.</p>"
            f"<p>Built to replace slow, single-threaded tools like PicCheck "
            f"without the sprawling complexity of do-everything alternatives "
            f"like Hunter.</p>"
        )

    def _build_source_group(self) -> QGroupBox:
        group = QGroupBox("Source")
        form = QFormLayout(group)

        source_mode_row = QHBoxLayout()
        source_mode_row.addWidget(QLabel("Source:"))
        self.mode_single_radio = QRadioButton("Single CSV")
        self.mode_folder_radio = QRadioButton("Folder of CSVs")
        self.mode_collection_radio = QRadioButton("Saved Collection")
        self.mode_all_collections_radio = QRadioButton("All Collections")
        self.mode_single_radio.setChecked(True)
        self.source_mode_group = QButtonGroup(self)
        self.source_mode_group.addButton(self.mode_single_radio, 0)
        self.source_mode_group.addButton(self.mode_folder_radio, 1)
        self.source_mode_group.addButton(self.mode_collection_radio, 2)
        self.source_mode_group.addButton(self.mode_all_collections_radio, 3)
        self.source_mode_group.idClicked.connect(self._on_source_mode_changed)
        source_mode_row.addWidget(self.mode_single_radio)
        source_mode_row.addWidget(self.mode_folder_radio)
        source_mode_row.addWidget(self.mode_collection_radio)
        source_mode_row.addWidget(self.mode_all_collections_radio)
        source_mode_row.addStretch(1)
        form.addRow(source_mode_row)

        self.source_stack = QStackedWidget()

        page_single = QWidget()
        page_single_layout = QHBoxLayout(page_single)
        page_single_layout.setContentsMargins(0, 0, 0, 0)
        self.csv_path_edit = QLineEdit()
        self.csv_path_edit.setPlaceholderText("Path to collection catalog CSV...")
        csv_browse = QPushButton("Browse...")
        csv_browse.clicked.connect(self._browse_csv)
        page_single_layout.addWidget(self.csv_path_edit)
        page_single_layout.addWidget(csv_browse)
        self.source_stack.addWidget(page_single)

        page_folder = QWidget()
        page_folder_layout = QHBoxLayout(page_folder)
        page_folder_layout.setContentsMargins(0, 0, 0, 0)
        self.csv_folder_edit = QLineEdit()
        self.csv_folder_edit.setPlaceholderText("Folder containing multiple catalog CSVs...")
        folder_browse = QPushButton("Browse...")
        folder_browse.clicked.connect(self._browse_csv_folder)
        page_folder_layout.addWidget(self.csv_folder_edit)
        page_folder_layout.addWidget(folder_browse)
        self.source_stack.addWidget(page_folder)

        page_collection = QWidget()
        page_collection_layout = QHBoxLayout(page_collection)
        page_collection_layout.setContentsMargins(0, 0, 0, 0)
        self.collection_combo = QComboBox()
        self.collection_combo.setMinimumWidth(220)
        self.collection_combo.currentIndexChanged.connect(self._on_collection_combo_changed)
        manage_collections_button = QPushButton("Manage Collections...")
        manage_collections_button.clicked.connect(self._open_manage_collections)
        self.view_collection_status_button = QPushButton("View Collection Status...")
        self.view_collection_status_button.setEnabled(False)
        self.view_collection_status_button.clicked.connect(self._open_collection_status)
        page_collection_layout.addWidget(self.collection_combo, stretch=1)
        page_collection_layout.addWidget(manage_collections_button)
        page_collection_layout.addWidget(self.view_collection_status_button)
        self.source_stack.addWidget(page_collection)

        page_all_collections = QWidget()
        page_all_layout = QHBoxLayout(page_all_collections)
        page_all_layout.setContentsMargins(0, 0, 0, 0)
        self.all_collections_label = QLabel(
            "Every saved collection will be scanned and sorted in one pass "
            "(0 collections saved yet)."
        )
        self.all_collections_label.setWordWrap(True)
        page_all_layout.addWidget(self.all_collections_label, stretch=1)
        manage_collections_button_all = QPushButton("Manage Collections...")
        manage_collections_button_all.clicked.connect(self._open_manage_collections)
        page_all_layout.addWidget(manage_collections_button_all)
        self.source_stack.addWidget(page_all_collections)

        form.addRow(self.source_stack)
        self._refresh_collection_combo()

        dir_row = QHBoxLayout()
        self.scan_dir_edit = QLineEdit()
        self.scan_dir_edit.setPlaceholderText("Directory to scan for media files...")
        dir_browse = QPushButton("Browse...")
        dir_browse.clicked.connect(self._browse_scan_dir)
        dir_row.addWidget(self.scan_dir_edit)
        dir_row.addWidget(dir_browse)
        form.addRow("Scan Directory:", dir_row)

        output_row = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText(
            "Optional — base collections folder; files go under "
            "<this>\\[collection name\\]\\<CSV name>\\<relative dir from CSV>..."
        )
        output_browse = QPushButton("Browse...")
        output_browse.clicked.connect(self._browse_output_dir)
        output_row.addWidget(self.output_dir_edit)
        output_row.addWidget(output_browse)
        form.addRow("Base Collections Directory:", output_row)

        options_row = QHBoxLayout()
        self.recursive_check = QCheckBox("Scan subdirectories")
        self.recursive_check.setChecked(True)
        options_row.addWidget(self.recursive_check)

        options_row.addSpacing(20)
        options_row.addWidget(QLabel("Hashing threads:"))
        self.thread_spin = QSpinBox()
        self.thread_spin.setRange(1, 64)
        self.thread_spin.setValue(max(1, os.cpu_count() or 4))
        options_row.addWidget(self.thread_spin)

        self.clear_cache_button = QPushButton("Clear Hash Cache")
        self.clear_cache_button.setToolTip(
            "Discards remembered CRC32 values so the next scan re-hashes every file from scratch."
        )
        self.clear_cache_button.clicked.connect(self._clear_hash_cache)
        options_row.addWidget(self.clear_cache_button)

        options_row.addStretch(1)

        self.scan_button = QPushButton("Start Scan")
        self.scan_button.setMinimumWidth(120)
        self.scan_button.clicked.connect(self._start_scan)
        options_row.addWidget(self.scan_button)

        self.cancel_scan_button = QPushButton("Cancel")
        self.cancel_scan_button.setEnabled(False)
        self.cancel_scan_button.clicked.connect(self._cancel_scan)
        options_row.addWidget(self.cancel_scan_button)

        form.addRow(options_row)

        progress_row = QHBoxLayout()
        self.scan_progress = QProgressBar()
        self.scan_progress.setValue(0)
        self.scan_status_label = QLabel("Idle")
        progress_row.addWidget(self.scan_progress, stretch=1)
        progress_row.addWidget(self.scan_status_label)
        form.addRow(progress_row)

        return group

    def _build_results_group(self) -> QGroupBox:
        group = QGroupBox("Results")
        layout = QVBoxLayout(group)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["Matched", "All", "Unmatched", "Error"])
        self.filter_combo.currentTextChanged.connect(self._apply_filter)
        filter_row.addWidget(self.filter_combo)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search filename...")
        self.search_edit.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.search_edit, stretch=1)
        layout.addLayout(filter_row)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, stretch=1)

        report_row = QHBoxLayout()
        report_row.addWidget(QLabel("Per-CSV completeness (correct/bad/missing, % complete):"))
        report_row.addStretch(1)
        self.generate_report_button = QPushButton("Generate Report...")
        self.generate_report_button.setEnabled(False)
        self.generate_report_button.clicked.connect(self._generate_report)
        report_row.addWidget(self.generate_report_button)
        self.generate_needed_button = QPushButton("Generate Missing/Bad CSVs...")
        self.generate_needed_button.setEnabled(False)
        self.generate_needed_button.clicked.connect(self._generate_needed_csvs)
        report_row.addWidget(self.generate_needed_button)
        layout.addLayout(report_row)

        verify_row = QHBoxLayout()
        self.verify_collection_dir_check = QCheckBox(
            "Also verify Base Collections Directory for reports (catches files already sorted in past runs)"
        )
        self.verify_collection_dir_check.setChecked(True)
        self.verify_collection_dir_check.setToolTip(
            "Without this, a completeness report only reflects files found in THIS scan's ingest "
            "directory -- a disc that's already 100% sorted from a previous run would wrongly show "
            "as entirely missing if none of its files happen to be in today's ingest folder. "
            "Uses the same hash cache, so repeat verification passes are fast after the first one."
        )
        verify_row.addWidget(self.verify_collection_dir_check)
        verify_row.addStretch(1)
        layout.addLayout(verify_row)

        report_settings_row = QHBoxLayout()
        self.auto_open_report_check = QCheckBox("Automatically open report after processing")
        self.auto_open_report_check.setToolTip(
            "Opens the report(s) generated after Process Selected with your default text editor, "
            "same as double-clicking the file. If a move touched more than one collection, each "
            "one's report opens separately."
        )
        report_settings_row.addWidget(self.auto_open_report_check)
        report_settings_row.addSpacing(20)
        report_settings_row.addWidget(QLabel("Keep last"))
        self.report_retention_spin = QSpinBox()
        self.report_retention_spin.setRange(0, 9999)
        self.report_retention_spin.setSpecialValueText("unlimited")
        self.report_retention_spin.setToolTip(
            "Older auto-generated reports for a collection are deleted once more than this many "
            "exist for it, keeping the most recent. Set to 0 for unlimited (never auto-delete). "
            "Only ever affects auto-generated, timestamped reports -- never anything you've "
            "manually saved via Generate Report...'s save dialog."
        )
        report_settings_row.addWidget(self.report_retention_spin)
        report_settings_row.addWidget(QLabel("auto-generated reports per collection"))
        report_settings_row.addStretch(1)
        layout.addLayout(report_settings_row)

        return group

    def _build_action_group(self) -> QGroupBox:
        group = QGroupBox("Move / Copy")
        layout = QVBoxLayout(group)

        controls_row = QHBoxLayout()

        self.copy_radio = QRadioButton("Copy")
        self.move_radio = QRadioButton("Move")
        self.copy_radio.setChecked(True)
        op_group = QButtonGroup(self)
        op_group.addButton(self.copy_radio)
        op_group.addButton(self.move_radio)
        controls_row.addWidget(self.copy_radio)
        controls_row.addWidget(self.move_radio)

        controls_row.addSpacing(20)
        controls_row.addWidget(QLabel("If file exists:"))
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItems([p.value for p in ConflictPolicy])
        controls_row.addWidget(self.conflict_combo)
        controls_row.addStretch(1)

        self.select_all_matched_button = QPushButton("Select All Matched")
        self.select_all_matched_button.clicked.connect(
            lambda: self.model.set_all_checked(True, only_status="Matched")
        )
        controls_row.addWidget(self.select_all_matched_button)

        self.clear_selection_button = QPushButton("Clear Selection")
        self.clear_selection_button.clicked.connect(lambda: self.model.set_all_checked(False))
        controls_row.addWidget(self.clear_selection_button)

        self.selected_count_label = QLabel("0 selected")
        controls_row.addWidget(self.selected_count_label)

        layout.addLayout(controls_row)

        process_row = QHBoxLayout()
        self.process_button = QPushButton("Process Selected")
        self.process_button.setMinimumWidth(150)
        self.process_button.clicked.connect(self._start_processing)
        process_row.addWidget(self.process_button)

        self.cancel_process_button = QPushButton("Cancel")
        self.cancel_process_button.setEnabled(False)
        self.cancel_process_button.clicked.connect(self._cancel_processing)
        process_row.addWidget(self.cancel_process_button)

        self.process_progress = QProgressBar()
        process_row.addWidget(self.process_progress, stretch=1)

        self.export_log_button = QPushButton("Export Log...")
        self.export_log_button.clicked.connect(self._export_log)
        process_row.addWidget(self.export_log_button)

        layout.addLayout(process_row)

        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(5000)
        layout.addWidget(self.log_edit, stretch=1)

        return group

    def _wire_signals(self):
        self.model.checkedCountChanged.connect(
            lambda n: self.selected_count_label.setText(f"{n} selected")
        )

        self.auto_open_report_check.setChecked(self.settings.value("auto_open_report", False, type=bool))
        self.auto_open_report_check.toggled.connect(
            lambda checked: self.settings.setValue("auto_open_report", checked)
        )

        self.report_retention_spin.setValue(self.settings.value("report_retention_count", 10, type=int))
        self.report_retention_spin.valueChanged.connect(
            lambda value: self.settings.setValue("report_retention_count", value)
        )

    # ------------------------------------------------------------------
    # Browsing
    # ------------------------------------------------------------------
    def _browse_csv(self):
        start_dir = self.settings.value("last_csv_dir", "", type=str) or self.settings.value("default_csv_dir", "", type=str)
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Catalog CSV", start_dir, "CSV Files (*.csv);;All Files (*)"
        )
        if path:
            self.csv_path_edit.setText(path)
            self.settings.setValue("last_csv_dir", str(Path(path).parent))

    def _browse_scan_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Directory to Scan", self.scan_dir_edit.text())
        if path:
            self.scan_dir_edit.setText(path)

    def _browse_csv_folder(self):
        start_dir = self.settings.value("last_csv_folder_dir", "", type=str) or self.settings.value("default_csv_dir", "", type=str)
        path = QFileDialog.getExistingDirectory(self, "Select Folder Containing CSVs", start_dir)
        if path:
            self.csv_folder_edit.setText(path)
            self.settings.setValue("last_csv_folder_dir", path)

    def _on_source_mode_changed(self, mode_id: int):
        self.source_stack.setCurrentIndex(mode_id)

    def _refresh_collection_combo(self):
        current_id = self.collection_combo.currentData() if self.collection_combo.count() else None
        self.collection_combo.clear()
        all_collections = self.collections_store.all()
        for c in all_collections:
            self.collection_combo.addItem(f"{c.name}  ({len(c.csvs)} CSV{'s' if len(c.csvs) != 1 else ''})", c.id)
        if current_id:
            idx = self.collection_combo.findData(current_id)
            if idx >= 0:
                self.collection_combo.setCurrentIndex(idx)
        self._on_collection_combo_changed()

        total_csvs = sum(len(c.csvs) for c in all_collections)
        if all_collections:
            self.all_collections_label.setText(
                f"Every saved collection will be scanned and sorted in one pass "
                f"({len(all_collections)} collection{'s' if len(all_collections) != 1 else ''}, "
                f"{total_csvs} CSV{'s' if total_csvs != 1 else ''} total)."
            )
        else:
            self.all_collections_label.setText(
                "No collections saved yet -- create one first via Manage Collections "
                "(switch to \"Saved Collection\" mode to reach it)."
            )

    def _on_collection_combo_changed(self, *_args):
        self.view_collection_status_button.setEnabled(self.collection_combo.currentData() is not None)

    def _open_manage_collections(self):
        dialog = CollectionsDialog(self.collections_store, self)
        dialog.exec()
        self._refresh_collection_combo()  # names/CSV counts may have changed

    def _open_collection_status(self):
        collection_id = self.collection_combo.currentData()
        if not collection_id:
            return
        collection = self.collections_store.get(collection_id)
        if not collection:
            return
        output_base_dir = self.output_dir_edit.text().strip()
        window = CollectionStatusWindow(
            collection, output_base_dir, self._hash_cache, self._cache_path,
            verification_cache=self._verification_cache,
            verification_cache_path=self._verification_cache_path,
            reports_dir=self._reports_dir(),
            report_retention_count=self.report_retention_spin.value(),
            parent=self,
        )
        self._status_windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()

    def _browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Base Collections Directory", self.output_dir_edit.text())
        if path:
            self.output_dir_edit.setText(path)

    # ------------------------------------------------------------------
    # Persistent default directories / first-run setup
    #
    # These are separate from the "last used" folders remembered for each
    # browse dialog (see _browse_csv / _browse_csv_folder): the defaults
    # here are what the Ingest Directory and Base Collections Directory
    # fields are pre-filled with on every startup. They only change when
    # explicitly set via the setup dialog (first run, or File > Change
    # Default Directories...) -- browsing to a different folder during a
    # normal session overrides that run without touching the saved default.
    # ------------------------------------------------------------------
    def _current_defaults(self) -> dict:
        return {
            "csv_dir": self.settings.value("default_csv_dir", "", type=str),
            "scan_dir": self.settings.value("default_scan_dir", "", type=str),
            "output_dir": self.settings.value("default_output_dir", "", type=str),
        }

    def _reports_dir(self):
        """<default CSV directory>/reports, or None if no default CSV
        directory has been set (via first-run setup or File > Change
        Default Directories)."""
        base = self.settings.value("default_csv_dir", "", type=str)
        return Path(base) / "reports" if base else None

    def _needed_dir(self):
        """<default CSV directory>/needed, or None if no default CSV
        directory has been set."""
        base = self.settings.value("default_csv_dir", "", type=str)
        return Path(base) / "needed" if base else None

    def _save_defaults(self, values: dict):
        self.settings.setValue("default_csv_dir", values.get("csv_dir", ""))
        self.settings.setValue("default_scan_dir", values.get("scan_dir", ""))
        self.settings.setValue("default_output_dir", values.get("output_dir", ""))

    def _load_persisted_defaults(self):
        defaults = self._current_defaults()
        if defaults["scan_dir"]:
            self.scan_dir_edit.setText(defaults["scan_dir"])
        if defaults["output_dir"]:
            self.output_dir_edit.setText(defaults["output_dir"])

    def _maybe_run_first_time_setup(self):
        if self.settings.value("setup_complete", False, type=bool):
            return
        dialog = SetupDialog(self, initial=self._current_defaults(), first_run=True)
        if dialog.exec() == QDialog.Accepted:
            self._save_defaults(dialog.values())
            self._load_persisted_defaults()
        self.settings.setValue("setup_complete", True)

    def _open_change_defaults(self):
        dialog = SetupDialog(self, initial=self._current_defaults(), first_run=False)
        if dialog.exec() == QDialog.Accepted:
            self._save_defaults(dialog.values())
            self._load_persisted_defaults()

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------
    def _start_scan(self):
        mode = self.source_mode_group.checkedId()

        if mode == 3:  # scan against every saved collection at once
            entries, warnings, source_label = self._gather_all_collections_source()
            if entries is None:
                return
            label_name = "AllCollections"
        else:
            csv_paths, collection_name, source_label, archived_paths = self._gather_source_csvs()
            if csv_paths is None:
                return  # validation already showed a message box
            try:
                entries, warnings = load_multiple_csvs(
                    csv_paths, source_collection=collection_name, archived_paths=archived_paths
                )
            except CsvLoadError as exc:
                QMessageBox.critical(self, "CSV Error", str(exc))
                return
            label_name = collection_name

        scan_dir = self.scan_dir_edit.text().strip()
        if not scan_dir or not os.path.isdir(scan_dir):
            QMessageBox.warning(self, "Missing Directory", "Please choose a valid directory to scan.")
            return

        self._catalog_index = build_index(entries)
        self._catalog_entries = entries
        self._log(f"Loaded {len(entries)} catalog entries from {source_label}")
        for w in warnings:
            self._log(f"  Warning: {w}")

        self._active_collection_name = label_name
        self._output_base_dir = self.output_dir_edit.text().strip()
        if self._output_base_dir:
            if mode == 3:
                collection_note = " (each file sorts into its own collection's folder)"
            else:
                collection_note = f", collection folder: {label_name}" if label_name else ""
            self._log(f"Output base directory: {self._output_base_dir}{collection_note}")

        self.model.clear()
        self._scan_generation += 1
        self._hash_total = 0
        self._hash_completed = 0
        self._cache_hits = 0
        self._scanned_files = []
        # NOTE: self._collection_scanned_files_by_key is intentionally NOT
        # reset here -- it should persist across scans of the same
        # collection(s) and only be cleared/refreshed by
        # _verify_collection_directory, not on every scan.
        self.scan_button.setEnabled(False)
        self.cancel_scan_button.setEnabled(True)
        self.generate_report_button.setEnabled(False)
        self.generate_needed_button.setEnabled(False)
        self.scan_progress.setValue(0)
        self.scan_status_label.setText("Enumerating files...")

        self._enum_thread = EnumerateThread(scan_dir, self.recursive_check.isChecked(), self)
        self._enum_thread.countUpdate.connect(
            lambda n: self.scan_status_label.setText(f"Enumerating files... {n} found")
        )
        self._enum_thread.failed.connect(self._on_enumeration_failed)
        self._enum_thread.done.connect(self._on_enumeration_done)
        self._enum_thread.start()

    def _gather_all_collections_source(self):
        """For 'All Collections' mode: returns (entries, warnings,
        source_label), or (None, None, None) after showing a validation
        message if there's nothing to scan against yet."""
        collections_with_csvs = [c for c in self.collections_store.all() if c.csvs]
        if not collections_with_csvs:
            QMessageBox.warning(
                self, "No Collections",
                "No saved collections with CSVs yet -- create one via Manage Collections first."
            )
            return None, None, None
        try:
            entries, warnings = load_all_collections(collections_with_csvs)
        except CsvLoadError as exc:
            QMessageBox.critical(self, "CSV Error", str(exc))
            return None, None, None
        total_csvs = sum(len(c.csvs) for c in collections_with_csvs)
        label = f"{len(collections_with_csvs)} collection(s), {total_csvs} CSV(s) total"
        return entries, warnings, label

    def _gather_source_csvs(self):
        """Returns (csv_paths, collection_name, source_label, archived_paths)
        for whichever source mode is active, or (None, None, None, None)
        after showing a validation message if the current selection isn't
        usable yet. archived_paths is a set of paths (subset of csv_paths)
        that should be marked Archived -- always empty for ad hoc modes
        (single CSV / folder of CSVs), which have no collection to carry
        that status on."""
        mode = self.source_mode_group.checkedId()

        if mode == 0:  # single CSV, ad hoc -- no collection subfolder
            csv_path = self.csv_path_edit.text().strip()
            if not csv_path:
                QMessageBox.warning(self, "Missing CSV", "Please choose a catalog CSV file.")
                return None, None, None, None
            return [csv_path], "", csv_path, set()

        if mode == 1:  # folder of CSVs, ad hoc -- folder name becomes the collection subfolder
            folder = self.csv_folder_edit.text().strip()
            if not folder or not os.path.isdir(folder):
                QMessageBox.warning(self, "Missing Folder", "Please choose a valid folder containing CSVs.")
                return None, None, None, None
            csv_paths = sorted(str(p) for p in Path(folder).glob("*.csv"))
            if not csv_paths:
                QMessageBox.warning(self, "No CSVs Found", f"No .csv files were found directly in:\n{folder}")
                return None, None, None, None
            collection_name = sanitize_windows_name(Path(folder).name)
            return csv_paths, collection_name, f"{len(csv_paths)} CSV(s) in {folder}", set()

        # mode == 2: saved collection -- collection's name becomes the subfolder
        collection_id = self.collection_combo.currentData()
        if not collection_id:
            QMessageBox.warning(self, "No Collection Selected", "Please select or create a collection first.")
            return None, None, None, None
        collection = self.collections_store.get(collection_id)
        if not collection or not collection.csvs:
            QMessageBox.warning(self, "Empty Collection", "This collection has no CSVs. Add some via Manage Collections.")
            return None, None, None, None
        collection_name = sanitize_windows_name(collection.name)
        return list(collection.csvs), collection_name, f"collection '{collection.name}'", set(collection.archived_csvs)

    def _clear_hash_cache(self):
        if not self._hash_cache and not self._verification_cache:
            self._log("Hash cache is already empty.")
            return
        confirm = QMessageBox.question(
            self, "Clear Hash Cache",
            f"This will discard {len(self._hash_cache)} cached file hashes and all saved "
            "collection-verification history. The next scan and the next collection "
            "verification will both start from scratch. Continue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self._hash_cache.clear()
        clear_cache_file(self._cache_path)
        self._verification_cache.clear()
        clear_cache_file(self._verification_cache_path)
        self._collection_scanned_files_by_key = {}
        self._log("Hash cache and collection-verification history cleared.")

    def _cancel_scan(self):
        self._scan_generation += 1  # invalidate any in-flight results
        if self._enum_thread and self._enum_thread.isRunning():
            self._enum_thread.stop()
        self.scan_status_label.setText("Cancelled")
        self.scan_button.setEnabled(True)
        self.cancel_scan_button.setEnabled(False)

    def _on_enumeration_failed(self, message: str):
        QMessageBox.critical(self, "Scan Error", f"Could not read directory: {message}")
        self.scan_button.setEnabled(True)
        self.cancel_scan_button.setEnabled(False)
        self.scan_status_label.setText("Error")

    def _on_enumeration_done(self, paths: list):
        if not paths:
            self.scan_status_label.setText("No files found")
            self.scan_button.setEnabled(True)
            self.cancel_scan_button.setEnabled(False)
            return

        self._hash_total = len(paths)
        self._hash_completed = 0
        self.scan_progress.setRange(0, self._hash_total)
        self.scan_status_label.setText(f"Hashing 0 / {self._hash_total}")

        QThreadPool.globalInstance().setMaxThreadCount(self.thread_spin.value())

        self._worker_signals = WorkerSignals()
        self._worker_signals.finished.connect(self._on_hash_result)

        generation = self._scan_generation
        for path in paths:
            worker = HashWorker(path, generation, self._worker_signals, self._hash_cache)
            QThreadPool.globalInstance().start(worker)

    def _on_hash_result(self, result: ScanResult):
        if result.generation != self._scan_generation:
            return  # stale result from a cancelled scan

        self._hash_completed += 1
        self.scan_progress.setValue(self._hash_completed)
        self.scan_status_label.setText(f"Hashing {self._hash_completed} / {self._hash_total}")

        filename = os.path.basename(result.path)

        if result.error:
            row = RowRecord(
                status="Error", filename=filename, source_path=result.path,
                filesize=result.filesize, crc32="", target_dir="", result=result.error,
            )
        else:
            if result.cache_hit:
                self._cache_hits += 1
            else:
                self._hash_cache[result.path] = {
                    "size": result.filesize,
                    "mtime_ns": result.mtime_ns,
                    "crc32": result.crc32,
                }

            key = (result.filesize, result.crc32)
            self._scanned_files.append((filename, result.filesize, result.crc32))
            matches = self._catalog_index.get(key)
            if matches:
                row = RowRecord(
                    status="Matched", filename=filename, source_path=result.path,
                    filesize=result.filesize, crc32=result.crc32,
                    target_dir=self._resolve_target_dir(
                        matches[0].directory, matches[0].source_csv, matches[0].source_collection
                    ),
                    source_csv=matches[0].source_csv,
                    source_collection=matches[0].source_collection,
                )
            else:
                row = RowRecord(
                    status="Unmatched", filename=filename, source_path=result.path,
                    filesize=result.filesize, crc32=result.crc32, target_dir="",
                )

        self.model.add_row(row)

        if self._hash_completed >= self._hash_total:
            self._on_scan_finished()

    def _resolve_target_dir(self, csv_directory: str, source_csv: str, source_collection: str) -> str:
        """Build the final destination directory for a matched file:

            <output base dir> / [source_collection] / <CSV name> / <CSV's relative directory>

        source_collection comes from the matched catalog entry itself, NOT
        from any scan-wide "active collection" -- this is what lets a
        single scan (in "All Collections" mode) sort different matches into
        different collections' folders correctly. For the other three
        modes, every entry in a given scan happens to share the same
        source_collection, so this produces identical results to before.
        A single ad hoc CSV has an empty source_collection, giving the
        flatter <output base dir> / <CSV name> / <relative dir> shape.

        If no base directory is set, the CSV value is used unchanged. If
        the CSV's directory value is a genuinely absolute path (drive letter
        or UNC), it's respected as-is. Otherwise, any leading slash/backslash
        is stripped first -- without this, a "rooted but driveless" value
        like "\\Movies\\Action" gets treated by Path's / operator as an
        anchor that resets to the drive root, silently discarding everything
        to its left (this was the bug behind files landing at the drive root).
        """
        if not self._output_base_dir:
            return csv_directory
        candidate = csv_directory.strip()
        if Path(candidate).is_absolute():
            return candidate
        candidate = candidate.lstrip("\\/")
        target = Path(self._output_base_dir)
        if source_collection:
            target = target / source_collection
        target = target / source_csv / candidate
        return str(target)

    def _on_scan_finished(self):
        self.scan_button.setEnabled(True)
        self.cancel_scan_button.setEnabled(False)
        counts = self.model.status_counts()
        self.scan_status_label.setText(
            f"Done — {counts.get('Matched', 0)} matched, "
            f"{counts.get('Unmatched', 0)} unmatched, {counts.get('Error', 0)} errors"
        )
        self._log(
            f"Scan complete: {counts.get('Matched', 0)} matched, "
            f"{counts.get('Unmatched', 0)} unmatched, {counts.get('Error', 0)} errors "
            f"({self._cache_hits}/{self._hash_total} served from cache)"
        )
        save_cache(self._cache_path, self._hash_cache)
        if self._catalog_entries:
            self.generate_report_button.setEnabled(True)
            self.generate_needed_button.setEnabled(True)
        # NOTE: deliberately no report generation here. A plain scan never
        # verifies the collection directory (see _verify_collection_directory's
        # docstring), so a report at this point would only reflect whatever was
        # last verified -- often nothing yet -- which reads as a real
        # completeness number when it isn't one. Reports are only ever
        # produced alongside an actual verification: after a successful
        # Process Selected run, from the Collection Status window, or via
        # the manual Generate Report button (which forces a fresh verify).
        self._update_status_bar()

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------
    def _apply_filter(self):
        self.proxy.set_search_text(self.search_edit.text())
        self.proxy.set_status_filter(self.filter_combo.currentText())

    # ------------------------------------------------------------------
    # Processing (move/copy)
    # ------------------------------------------------------------------
    def _start_processing(self):
        rows = self.model.all_rows()
        jobs = [
            (i, r.source_path, r.target_dir)
            for i, r in enumerate(rows)
            if r.checked and r.status == "Matched"
        ]
        if not jobs:
            QMessageBox.information(self, "Nothing to do", "No matched files are selected.")
            return

        operation = Operation.MOVE if self.move_radio.isChecked() else Operation.COPY
        conflict_policy = ConflictPolicy(self.conflict_combo.currentText())

        if operation is Operation.MOVE:
            confirm = QMessageBox.question(
                self, "Confirm Move",
                f"This will MOVE {len(jobs)} file(s) out of the scan directory. Continue?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return

        self.process_button.setEnabled(False)
        self.cancel_process_button.setEnabled(True)
        self.process_progress.setRange(0, len(jobs))
        self.process_progress.setValue(0)
        self._process_success_count = 0
        self._process_touched_keys = set()

        self._processing_thread = ProcessingThread(jobs, operation, conflict_policy, self)
        self._processing_thread.progress.connect(
            lambda done, total: self.process_progress.setValue(done)
        )
        self._processing_thread.fileDone.connect(self._on_file_processed)
        self._processing_thread.finishedAll.connect(self._on_processing_finished)
        self._processing_thread.start()

    def _cancel_processing(self):
        if self._processing_thread and self._processing_thread.isRunning():
            self._processing_thread.stop()
        self.cancel_process_button.setEnabled(False)

    def _on_file_processed(self, row_index: int, result):
        self.model.set_result(row_index, f"{result.action}" + (f" ({result.detail})" if result.detail else ""))
        if result.action in ("moved", "copied"):
            self._process_success_count += 1
            row = self.model.row_at(row_index)
            if row.source_csv:
                self._process_touched_keys.add((row.source_collection, row.source_csv))
        dest_str = f" -> {result.destination}" if result.destination else ""
        self._log(f"[{result.action.upper()}] {result.source}{dest_str}"
                   + (f" — {result.detail}" if result.detail else ""))

    def _on_processing_finished(self):
        self.process_button.setEnabled(True)
        self.cancel_process_button.setEnabled(False)
        self._log("Processing complete.")
        if self._process_success_count > 0:
            # At least one file actually moved/copied -- but only into the
            # specific (collection, CSV) folder(s) those particular files
            # belonged to. Everything else is untouched by this run, so only
            # re-verify what could have actually changed (see
            # _verify_collection_directory's docstring for the full
            # reasoning -- re-walking an entire large collection, or every
            # OTHER collection in an "All Collections" run, over a handful
            # of moved files would be pure overhead for zero new
            # information about anything that wasn't touched).
            self._verify_collection_directory(self._auto_generate_report, only_keys=self._process_touched_keys)
        self._update_status_bar()

    # ------------------------------------------------------------------
    # Logging / export / status
    # ------------------------------------------------------------------
    def _log(self, message: str):
        self.log_edit.appendPlainText(message)

    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Results", "results.csv", "CSV Files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["status", "filename", "source_path", "filesize", "crc32", "target_directory", "result"])
                for r in self.model.all_rows():
                    writer.writerow([r.status, r.filename, r.source_path, r.filesize, r.crc32, r.target_dir, r.result])
            self._log(f"Exported results to {path}")
        except OSError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))

    # ------------------------------------------------------------------
    # Reporting -- classifies the loaded catalog against known scan results
    # (correct / bad / missing). Nothing here is persisted; it's recomputed
    # fresh from self._catalog_entries + self._scanned_files (+ any verified
    # collection-directory contents) every time.
    #
    # A completeness report is only ever generated alongside an actual
    # verification of the collection directory -- never from a plain scan
    # alone, since a scan doesn't touch that directory and a report at that
    # point would misleadingly look like a real completeness number when
    # it's really just "here's what this one ingest batch covers." The
    # three points where a real verification (and therefore a report) can
    # happen are: a Process Selected run that actually moved/copied
    # something, opening or refreshing the Collection Status window, and
    # the manual Generate Report / Generate Missing-Bad CSVs buttons (which
    # force a fresh verify before doing anything else). The -needed CSVs
    # stay manual-only regardless -- deciding when to act on missing/bad
    # files is a user decision, not a side effect of anything automatic.
    #
    # Verification walks each relevant (collection, CSV)'s own output
    # subfolder separately rather than one big combined walk. This matters
    # for the post-move trigger specifically: moving files only ever
    # changes the folder(s) those particular files landed in, so after
    # processing, only THOSE (collection, CSV) pairs get re-walked
    # (only_keys) -- re-walking every other, untouched one (potentially
    # across several collections at once, in "All Collections" mode) would
    # be pure overhead for zero new information. The manual buttons and
    # Collection Status window still request a full verification (every
    # CSV in the current context), since those are explicit "give me
    # ground truth" actions. Verified data is
    # tracked per-CSV so a scoped walk only replaces the touched CSVs'
    # entries and leaves everything already known about every other CSV
    # untouched. Uses the shared hash cache everywhere, so repeat passes
    # are fast after the first one.
    # ------------------------------------------------------------------
    def _verify_collection_directory(self, on_done, only_keys=None):
        """Kicks off a fresh verification walk, then calls on_done(). By
        default verifies every (collection, CSV) pair present in the
        current catalog -- which may span more than one collection's root
        at once (e.g. "All Collections" mode); pass only_keys (an iterable
        of (source_collection, source_csv) tuples) to scope it to just
        those instead. Safe to do at any time, since untouched CSVs' last-
        known state always comes fresh from the shared, persistent on-disk
        cache (not a locally-cached snapshot), so this picks up
        verifications done elsewhere too -- another session, or the
        Collection Status window, which shares the same cache object and
        writes through it. This is a "trust it, refresh occasionally"
        cache, same as the hash cache: if files change outside the app
        between verifications, it won't know until something actually
        re-walks that folder -- a full check via the Collection Status
        window or the manual report buttons is how that gets caught, and
        is worth doing occasionally regardless. If verification is skipped
        entirely (no base dir, checkbox off, nothing to walk), on_done()
        is still called immediately.

        CSVs marked Archived are never walked here at all -- they're always
        reported as complete regardless of what's physically present (see
        core/report.py's classify_entries), so there's nothing a walk could
        usefully tell us about them.

        A scoped request for a root that has NEVER been persisted at all
        (checked directly against self._verification_cache, not session
        state) is upgraded to a full check of every CSV in that collection.
        Without this, a collection that's never had an explicit full check
        would permanently show every CSV except whichever one a move
        happened to touch as entirely missing -- not because anything's
        actually wrong, but because nothing had ever looked at the rest of
        it. Once a root has ANY persisted data (from this session or a past
        one), scoped requests go back to being properly scoped and fast."""
        self.generate_report_button.setEnabled(False)
        self.generate_needed_button.setEnabled(False)
        self._collection_scan_generation += 1
        self._pending_verify_callback = on_done

        # Always reload from the shared persisted cache before layering any
        # new walk results on top -- covers every root the current catalog
        # touches, since a scan can now span more than one collection.
        self._collection_scanned_files_by_key = self._load_all_cached_verification()

        if not self._output_base_dir or not self.verify_collection_dir_check.isChecked():
            self._run_pending_verify_callback()
            return

        all_keys = {(e.source_collection, e.source_csv) for e in self._catalog_entries}
        archived_keys = {(e.source_collection, e.source_csv) for e in self._catalog_entries if e.archived}

        if only_keys:
            target_keys = set()
            upgraded_roots = set()
            for collection, csv_name in only_keys:
                root = self._root_for(collection)
                if root and root not in self._verification_cache and root not in upgraded_roots:
                    upgraded_roots.add(root)
                    # First-ever check of this collection -- pull in every
                    # CSV it has in the current catalog, not just the one
                    # that was actually touched by the move.
                    target_keys.update(
                        (e.source_collection, e.source_csv)
                        for e in self._catalog_entries
                        if e.source_collection == collection
                    )
                else:
                    target_keys.add((collection, csv_name))
            if upgraded_roots:
                self._log(
                    f"First-ever check of {len(upgraded_roots)} collection(s) touched by this "
                    f"move -- running a full verification for those instead of a scoped one."
                )
        else:
            target_keys = all_keys

        queue = []
        for collection, csv_name in sorted(target_keys):
            if (collection, csv_name) in archived_keys:
                continue  # Archived -- trusted complete, never walked
            folder = self._csv_output_dir(collection, csv_name)
            if folder is not None and folder.is_dir():
                queue.append((collection, csv_name, str(folder)))

        if not queue:
            self._run_pending_verify_callback()
            return

        for collection, csv_name, _folder in queue:
            self._collection_scanned_files_by_key[(collection, csv_name)] = []  # fresh data incoming

        self._pending_verify_queue = queue
        self._walk_next_verify_csv()

    def _load_all_cached_verification(self) -> dict:
        """Loads persisted verification data for every (collection, CSV)
        pair present in the current catalog, across however many roots
        that spans (one root per distinct collection, or the output base
        dir itself for ad hoc entries with no collection). Returns
        {(source_collection, source_csv): [(filename, size, crc), ...]}."""
        result: dict = {}
        distinct_collections = {e.source_collection for e in self._catalog_entries}
        for collection in distinct_collections:
            root = self._root_for(collection)
            if not root:
                continue
            cached = self._verification_cache.get(root, {})
            for csv_name, files in cached.items():
                result[(collection, csv_name)] = [tuple(item) for item in files]
        return result

    def _root_for(self, source_collection: str):
        """The verification-cache root for one collection context:
        <output base dir>/<source_collection>, or the output base dir
        itself when source_collection is empty -- matches
        _csv_output_dir's flat layout for ad hoc CSVs with no collection.
        Returns None if there's no base directory configured."""
        if not self._output_base_dir:
            return None
        base = Path(self._output_base_dir)
        return str(base / source_collection) if source_collection else str(base)

    def _csv_output_dir(self, source_collection: str, csv_name: str):
        """The specific output subfolder for one CSV:
        <output base dir>/[source_collection]/<csv_name>. Returns None if
        no base directory is configured."""
        if not self._output_base_dir:
            return None
        base = Path(self._output_base_dir)
        if source_collection:
            return base / source_collection / csv_name
        return base / csv_name

    def _walk_next_verify_csv(self):
        if not self._pending_verify_queue:
            save_cache(self._cache_path, self._hash_cache)
            self._persist_all_verification()
            self._log("Collection directory verification complete.")
            self._run_pending_verify_callback()
            return
        collection, csv_name, folder = self._pending_verify_queue.pop(0)
        self._current_verify_key = (collection, csv_name)
        self._log(f"Verifying: {folder}")
        self._collection_enum_thread = EnumerateThread(folder, True, self)
        self._collection_enum_thread.failed.connect(self._on_collection_verify_failed)
        self._collection_enum_thread.done.connect(self._on_collection_enum_done)
        self._collection_enum_thread.start()

    def _persist_all_verification(self):
        """Groups the flat (collection, csv)-keyed working data back into
        the on-disk root-keyed format and saves it. One write covers every
        root the current catalog touches, not just one -- a single
        verification pass (e.g. "All Collections") can span more than one
        collection's root at once. Roots not present in the current
        catalog (from other collections, past sessions) are left exactly
        as they already were in the cache -- this only ever overwrites
        keys it actually has data for."""
        by_root: dict = {}
        for (collection, csv_name), files in self._collection_scanned_files_by_key.items():
            root = self._root_for(collection)
            if not root:
                continue
            by_root.setdefault(root, {})[csv_name] = [list(item) for item in files]
        for root, csv_map in by_root.items():
            self._verification_cache[root] = csv_map
        save_verification_cache(self._verification_cache_path, self._verification_cache)

    def _on_collection_verify_failed(self, message: str):
        self._log(f"Could not verify {self._current_verify_key[1]} ({message}).")
        self._walk_next_verify_csv()

    def _on_collection_enum_done(self, paths: list):
        if not paths:
            self._walk_next_verify_csv()
            return

        self._collection_hash_total = len(paths)
        self._collection_hash_completed = 0

        self._collection_worker_signals = WorkerSignals()
        self._collection_worker_signals.finished.connect(self._on_collection_hash_result)

        generation = self._collection_scan_generation
        for path in paths:
            worker = HashWorker(path, generation, self._collection_worker_signals, self._hash_cache)
            QThreadPool.globalInstance().start(worker)

    def _on_collection_hash_result(self, result: ScanResult):
        if result.generation != self._collection_scan_generation:
            return  # stale -- a newer verification pass already superseded this one

        self._collection_hash_completed += 1
        if not result.error:
            filename = os.path.basename(result.path)
            bucket = self._collection_scanned_files_by_key.setdefault(self._current_verify_key, [])
            bucket.append((filename, result.filesize, result.crc32))
            if not result.cache_hit:
                self._hash_cache[result.path] = {
                    "size": result.filesize,
                    "mtime_ns": result.mtime_ns,
                    "crc32": result.crc32,
                }

        if self._collection_hash_completed >= self._collection_hash_total:
            self._walk_next_verify_csv()  # moves on to the next queued (collection, CSV), or finishes

    def _run_pending_verify_callback(self):
        callback = self._pending_verify_callback
        self._pending_verify_callback = None
        if self._catalog_entries:
            self.generate_report_button.setEnabled(True)
            self.generate_needed_button.setEnabled(True)
        if callback:
            callback()

    def _compute_report_summary(self):
        # self._collection_scanned_files_by_key is always freshly prepared by
        # this point -- every caller of this method is an on_done callback
        # passed to _verify_collection_directory, which always reloads from
        # the shared persisted cache and applies any new walk results before
        # invoking that callback. No separate reload needed here.
        combined = list(self._scanned_files)
        for files in self._collection_scanned_files_by_key.values():
            combined.extend(files)
        statuses = classify_entries(self._catalog_entries, combined)
        return per_csv_summary(statuses)

    def _compute_report_summaries_by_collection(self) -> dict:
        """Returns {collection_name: per_csv_summary(...)} -- one summary
        per distinct collection present in the current catalog, with bare
        CSV names as row keys (not the "Collection/CSV" composite, which
        would be redundant once already split per collection). Every mode
        except "All Collections" always produces exactly one entry here
        (every entry in those scans shares one collection by construction),
        so this is what lets All Collections mode generate a separate
        report per collection instead of one combined report covering
        everything under a generic label."""
        combined = list(self._scanned_files)
        for files in self._collection_scanned_files_by_key.values():
            combined.extend(files)
        statuses = classify_entries(self._catalog_entries, combined)
        groups = split_by_collection(statuses)
        return {
            name: per_csv_summary(items, key_fn=lambda e: e.source_csv)
            for name, items in groups.items()
        }

    def _generate_report(self):
        if not self._catalog_entries:
            QMessageBox.information(self, "Nothing to Report", "Run a scan first.")
            return
        self._verify_collection_directory(self._do_generate_report)

    def _do_generate_report(self):
        summaries = self._compute_report_summaries_by_collection()
        if not summaries:
            summaries = {"": per_csv_summary([])}

        if len(summaries) == 1:
            # The common case (every mode except All Collections touching
            # more than one collection): keep the familiar single-file save
            # dialog, letting the user pick the exact name/location.
            collection_name, summary = next(iter(summaries.items()))
            title = f"Collection Report — {collection_name or 'Ad Hoc Scan'}"
            text = format_report_text(summary, title=title)

            default_name = f"{collection_name or 'collection'}_report.txt"
            reports_dir = self._reports_dir()
            if reports_dir:
                try:
                    reports_dir.mkdir(parents=True, exist_ok=True)
                    default_name = str(reports_dir / default_name)
                except OSError:
                    pass  # fall back to just the filename if it can't be created

            path, _ = QFileDialog.getSaveFileName(self, "Save Collection Report", default_name, "Text Files (*.txt)")
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                overall = summary[OVERALL_KEY]
                self._log(
                    f"Collection report saved to {path} "
                    f"({overall['percent_complete']:.1f}% complete overall)"
                )
            except OSError as exc:
                QMessageBox.critical(self, "Save Failed", str(exc))
            return

        # More than one collection (All Collections mode touching several)
        # -- one popup per collection would be obnoxious, so pick a folder
        # once and write one report per collection into it instead.
        reports_dir = self._reports_dir()
        start_dir = ""
        if reports_dir:
            try:
                reports_dir.mkdir(parents=True, exist_ok=True)
                start_dir = str(reports_dir)
            except OSError:
                pass
        out_dir = QFileDialog.getExistingDirectory(self, "Select Folder to Save Collection Reports", start_dir)
        if not out_dir:
            return

        written = []
        for collection_name, summary in summaries.items():
            title = f"Collection Report — {collection_name or 'Ad Hoc Scan'}"
            text = format_report_text(summary, title=title)
            path = Path(out_dir) / f"{collection_name or 'collection'}_report.txt"
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                written.append(str(path))
            except OSError as exc:
                self._log(f"Failed to write {path}: {exc}")
        if written:
            self._log(f"Wrote {len(written)} collection report(s) to {out_dir}:")
            for w in written:
                self._log(f"  {w}")

    def _auto_generate_report(self):
        """Called only after a successful Process Selected run (as the
        on_done callback passed to _verify_collection_directory) -- NOT
        after a plain scan, since a scan alone never verifies the
        collection directory and a report at that point would misleadingly
        look like a real completeness number. Silent (log-only) unless
        something actually goes wrong -- this is a background convenience,
        not an action the user asked for on this specific run.

        Writes one report per collection touched (see
        _compute_report_summaries_by_collection) rather than one combined
        report -- a move in "All Collections" mode that touched two
        different collections gets two separate, correctly-named reports,
        not one report under a generic "AllCollections" label.

        After each report is written, older auto-generated reports for
        that same collection are pruned down to the configured retention
        count (0 = unlimited), and if "Automatically open report after
        processing" is checked, the freshly-written report is opened with
        the OS default handler for .txt files."""
        if not self._catalog_entries:
            return
        reports_dir = self._reports_dir()
        if not reports_dir:
            self._log("Skipping automatic report (no default CSV directory set -- see File > Change Default Directories).")
            return
        try:
            reports_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._log(f"Could not create reports directory {reports_dir}: {exc}")
            return

        summaries = self._compute_report_summaries_by_collection()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        retention = self.report_retention_spin.value()
        auto_open = self.auto_open_report_check.isChecked()
        for collection_name, summary in summaries.items():
            title = f"Collection Report — {collection_name or 'Ad Hoc Scan'}"
            text = format_report_text(summary, title=title)
            name = f"{collection_name or 'collection'}_{stamp}.txt"
            path = reports_dir / name
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                overall = summary[OVERALL_KEY]
                self._log(f"Report auto-saved to {path} ({overall['percent_complete']:.1f}% complete overall)")
            except OSError as exc:
                self._log(f"Failed to auto-save report to {path}: {exc}")
                continue

            deleted = prune_old_reports(reports_dir, collection_name, retention)
            if deleted:
                self._log(f"Pruned {len(deleted)} older report(s) for {collection_name or 'collection'} (keeping last {retention}).")

            if auto_open:
                if not open_with_default_app(path):
                    self._log(f"Could not open {path} with the default app.")

    def _generate_needed_csvs(self):
        if not self._catalog_entries:
            QMessageBox.information(self, "Nothing to Generate", "Run a scan first.")
            return
        self._verify_collection_directory(self._do_generate_needed_csvs)

    def _do_generate_needed_csvs(self):
        summary = self._compute_report_summary()

        needed_dir = self._needed_dir()
        start_dir = ""
        if needed_dir:
            try:
                needed_dir.mkdir(parents=True, exist_ok=True)
                start_dir = str(needed_dir)
            except OSError:
                pass

        out_dir = QFileDialog.getExistingDirectory(self, "Select Folder to Save -needed CSVs", start_dir)
        if not out_dir:
            return

        written = []
        for csv_name, data in summary.items():
            if csv_name == OVERALL_KEY:
                continue
            needed_items = data["bad"] + data["missing"]
            if not needed_items:
                continue
            text = format_needed_csv(needed_items)
            # csv_name may be a composite "Collection/CSV" key -- flatten it
            # for the filename itself, since a literal slash would otherwise
            # be read as a path separator.
            safe_name = csv_name.replace("/", "_").replace("\\", "_")
            out_path = Path(out_dir) / f"{safe_name}-needed.csv"
            try:
                with open(out_path, "w", encoding="utf-8", newline="") as f:
                    f.write(text)
                written.append(str(out_path))
            except OSError as exc:
                self._log(f"Failed to write {out_path}: {exc}")

        if written:
            self._log(f"Wrote {len(written)} -needed CSV(s) to {out_dir}:")
            for w in written:
                self._log(f"  {w}")
        else:
            self._log("Nothing missing or bad in this scan — no -needed CSVs were necessary.")
            QMessageBox.information(self, "All Good", "No missing or bad files found — nothing to write.")

    def _update_status_bar(self):
        counts = self.model.status_counts()
        self.status_bar.showMessage(
            f"Matched: {counts.get('Matched', 0)}   "
            f"Unmatched: {counts.get('Unmatched', 0)}   "
            f"Errors: {counts.get('Error', 0)}"
        )

    def closeEvent(self, event):
        if self._processing_thread and self._processing_thread.isRunning():
            confirm = QMessageBox.question(
                self, "Operation in progress",
                "A move/copy operation is still running. Quit anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                event.ignore()
                return
            self._processing_thread.stop()
            self._processing_thread.wait(2000)
        if self._enum_thread and self._enum_thread.isRunning():
            self._enum_thread.stop()
            self._enum_thread.wait(2000)
        save_cache(self._cache_path, self._hash_cache)
        self._persist_all_verification()
        event.accept()
