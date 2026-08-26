"""Sanitizing free-text names (collection names, folder names) for safe use
as a single Windows path segment (a folder name -- not a full path)."""
from __future__ import annotations

_INVALID_CHARS = set('<>:"/\\|?*')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_windows_name(name: str, fallback: str = "unnamed") -> str:
    """Make `name` safe to use as one path segment on Windows:

    - strips characters Windows disallows in filenames, plus control chars
    - trims leading/trailing whitespace and trailing dots (Windows silently
      drops trailing dots/spaces, which otherwise causes confusing mismatches
      between the name you typed and the folder that actually gets created)
    - renames the handful of reserved device names (CON, PRN, COM1, ...) by
      prefixing an underscore, since Windows can't create folders with those
      names at all
    - falls back to a safe default if nothing usable is left
    """
    cleaned = "".join(c for c in name if c not in _INVALID_CHARS and ord(c) >= 32)
    cleaned = cleaned.strip().rstrip(". ").strip()
    if not cleaned:
        return fallback
    if cleaned.upper() in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned
