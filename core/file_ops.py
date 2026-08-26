"""File move/copy operations with conflict resolution."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class ConflictPolicy(Enum):
    SKIP = "Skip"
    OVERWRITE = "Overwrite"
    RENAME = "Rename (keep both)"


class Operation(Enum):
    COPY = "Copy"
    MOVE = "Move"


@dataclass
class OpResult:
    source: str
    destination: Optional[str]
    action: str          # "copied" / "moved" / "skipped" / "error"
    detail: str = ""


def _unique_destination(dest: Path) -> Path:
    """Find a non-colliding filename by appending ' (n)' before the extension."""
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    parent = dest.parent
    n = 1
    while True:
        candidate = parent / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def perform_op(
    source: str,
    target_dir: str,
    operation: Operation,
    conflict_policy: ConflictPolicy,
) -> OpResult:
    src = Path(source)
    dest_dir = Path(target_dir)
    dest = dest_dir / src.name

    try:
        if not src.exists():
            return OpResult(source, None, "error", "Source file no longer exists.")

        dest_dir.mkdir(parents=True, exist_ok=True)

        if dest.exists() and dest.resolve() != src.resolve():
            if conflict_policy is ConflictPolicy.SKIP:
                return OpResult(source, str(dest), "skipped", "Destination already exists.")
            elif conflict_policy is ConflictPolicy.RENAME:
                dest = _unique_destination(dest)
            # OVERWRITE: fall through, dest stays as-is

        if operation is Operation.MOVE:
            shutil.move(str(src), str(dest))
            return OpResult(source, str(dest), "moved")
        else:
            shutil.copy2(str(src), str(dest))
            return OpResult(source, str(dest), "copied")

    except Exception as exc:  # noqa: BLE001
        return OpResult(source, str(dest) if dest else None, "error", str(exc))


def remove_empty_directories(source_dirs, scan_root) -> list:
    """After a Move batch, cleans up directories left empty by files being
    moved out of them.

    For each directory in source_dirs (the immediate parent folder each
    moved file came from), removes it if it's now empty, then checks ITS
    parent, and so on upward -- so a whole chain of now-empty folders
    collapses in one pass, not just the immediate leaf. Two directories
    that shared a parent both get a chance to empty that parent out too:
    each starting directory is walked independently, and since emptiness
    is checked fresh against the real filesystem every time (not a cached
    snapshot), a shared ancestor that's still non-empty after the first
    directory's cleanup will correctly turn up empty once the second one's
    cleanup has also run.

    Stops at (never includes) scan_root -- that's the directory the user
    actually chose to scan, and should never be removed out from under
    them even if it ends up empty. Only ever removes a directory verified
    genuinely empty right before removal; never forces removal of
    anything with content. Silently skips anything outside scan_root
    entirely (shouldn't normally happen; defensive only).

    Returns the list of directories actually removed (as strings), for
    logging. Never raises -- a failure removing one directory (permissions,
    something else touching it in the meantime, etc.) just stops that
    particular branch's upward walk, not the rest of the batch.
    """
    root = Path(scan_root).resolve()
    removed: list = []

    # Deepest first so a chain (grandchild -> child -> parent) collapses
    # correctly within this single pass.
    starting_dirs = sorted(
        {Path(d).resolve() for d in source_dirs},
        key=lambda p: len(p.parts),
        reverse=True,
    )

    for start in starting_dirs:
        current = start
        if current != root and root not in current.parents:
            continue  # outside the scan root -- not ours to touch

        while current != root:
            try:
                if not current.is_dir():
                    break  # already gone (removed via another branch's cascade) or never existed
                if any(current.iterdir()):
                    break  # still has something in it -- stop walking up this branch
                current.rmdir()
                removed.append(str(current))
            except OSError:
                break
            current = current.parent

    return removed
