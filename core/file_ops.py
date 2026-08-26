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
