"""Reliquarium — entry point.

Run with:  python main.py
"""
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from core.resources import resource_path


def main():
    app = QApplication(sys.argv)
    # As of the portable-storage rework, nothing reads these for where to
    # store data anymore -- every persistent file lives under app_data_dir()
    # (see core/portable.py), not the registry or %LOCALAPPDATA%. Set to the
    # real product name now; the one place the OLD "MediaOrganizer" name
    # still matters is core/portable.py's one-time migration, which reads
    # the legacy registry location by its exact old name explicitly (not
    # via these calls) so an existing pre-portable install's data gets
    # copied forward automatically.
    app.setApplicationName("Reliquarium")
    app.setOrganizationName("Reliquarium")

    icon_path = resource_path("assets/icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    from ui.main_window import MainWindow  # imported after QApplication exists

    # Theme is applied inside MainWindow.__init__ (via the same _set_theme
    # method View > Theme uses for live switching), not here -- the window
    # isn't shown until after it fully constructs, so there's no visible
    # flash of the wrong theme either way, and having exactly one code path
    # apply the theme (instead of near-duplicate logic in two places) is
    # what surfaced why switching wasn't working: see _set_theme's docstring.
    window = MainWindow()
    window.resize(1250, 800)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
