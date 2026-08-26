"""Opens a file with the operating system's default handler for its type
(e.g. the default text editor for a .txt report).

This app's primary target is Windows, where os.startfile() is the correct,
standard mechanism -- it's the same thing double-clicking the file in
Explorer does. macOS/Linux fallbacks are included on a best-effort basis
since nothing about the rest of the app is Windows-only at the code level,
but they haven't been exercised the way the Windows path has.
"""
from __future__ import annotations

import os
import subprocess
import sys


def open_with_default_app(path) -> bool:
    """Returns True if the OS was asked to open the file (not a guarantee
    the associated app actually launched successfully -- just that the
    request didn't immediately fail). Never raises."""
    path = str(path)
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]  -- Windows-only attribute
            return True
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
            return True
        else:
            subprocess.Popen(["xdg-open", path])
            return True
    except OSError:
        return False
