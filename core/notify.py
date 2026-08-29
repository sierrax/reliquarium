"""Desktop notifications for long-running operations.

Uses Qt's own QSystemTrayIcon.showMessage(), which is cross-platform
(Windows, Linux via the desktop's own notification daemon, macOS) and
needs no extra dependencies beyond PySide6, which the app already
requires. The tray icon is only shown for the few seconds it takes to
actually dispatch the notification, then hidden again -- this app has no
other use for a persistent tray icon, and showing one indefinitely just
to unlock notifications would be exactly the kind of unnecessary visual
chrome the app avoids elsewhere.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon


class Notifier(QObject):
    def __init__(self, icon_path: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self._tray_icon: Optional[QSystemTrayIcon] = None
        self._icon_path = icon_path

    def notify(self, title: str, message: str, duration_ms: int = 8000) -> bool:
        """Shows a desktop notification, if the platform supports one.
        Returns True if a notification was actually dispatched, False if
        the system tray (and therefore notifications) isn't available on
        this platform/session. Never raises."""
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return False
            if self._tray_icon is None:
                self._tray_icon = QSystemTrayIcon(self)
                if self._icon_path and Path(self._icon_path).exists():
                    self._tray_icon.setIcon(QIcon(str(self._icon_path)))
            self._tray_icon.show()
            self._tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, duration_ms)
            QTimer.singleShot(duration_ms + 500, self._tray_icon.hide)
            return True
        except Exception:
            return False
