"""Persistent named collections.

A collection groups one or more catalog CSVs under a single name, used both
for output path organization (<base>\\<collection name>\\<csv name>\\...) and
for scanning several CSVs as one combined catalog at once.

Only the source-of-truth pointers are stored (name, member CSV paths) --
derived numbers like "total files expected" are intentionally NOT persisted
here, since they're cheap to recompute from the CSVs themselves and storing
them would risk going stale if a CSV changes without the collection being
re-saved.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from core.portable import app_data_dir


def default_collections_path() -> Path:
    return app_data_dir() / "collections.json"


@dataclass
class Collection:
    id: str
    name: str
    csvs: List[str] = field(default_factory=list)
    archived_csvs: List[str] = field(default_factory=list)  # subset of csvs marked
                                       # Archived: complete but no longer physically
                                       # present in the live Base Collections
                                       # Directory (e.g. burned to disc). Verification
                                       # skips these entirely and they're always
                                       # reported as complete rather than missing.
    created: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Collection":
        return Collection(
            id=d.get("id") or str(uuid.uuid4()),
            name=d.get("name", ""),
            csvs=list(d.get("csvs", [])),
            archived_csvs=list(d.get("archived_csvs", [])),  # absent in older files -> none archived
            created=d.get("created", ""),
        )

    def is_archived(self, csv_path: str) -> bool:
        return csv_path in self.archived_csvs


class CollectionsStore:
    """Loads/saves collections.json and provides simple CRUD. Every
    mutating call saves immediately -- this is a small, infrequently-edited
    file, not a performance-sensitive path."""

    def __init__(self, path: Path):
        self.path = path
        self._collections: Dict[str, Collection] = {}
        self.load()

    def load(self) -> None:
        self._collections = {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("collections", []):
                c = Collection.from_dict(item)
                self._collections[c.id] = c
        except (OSError, ValueError):
            pass  # missing/corrupt file -> start empty, never fatal

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {"version": 1, "collections": [c.to_dict() for c in self._collections.values()]}
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            tmp.replace(self.path)
        except OSError:
            pass

    def all(self) -> List[Collection]:
        return sorted(self._collections.values(), key=lambda c: c.name.lower())

    def get(self, collection_id: str) -> Optional[Collection]:
        return self._collections.get(collection_id)

    def add(self, name: str, csvs: Optional[List[str]] = None) -> Collection:
        c = Collection(
            id=str(uuid.uuid4()),
            name=name,
            csvs=list(csvs or []),
            created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._collections[c.id] = c
        self.save()
        return c

    def update(self, collection: Collection) -> None:
        self._collections[collection.id] = collection
        self.save()

    def delete(self, collection_id: str) -> None:
        self._collections.pop(collection_id, None)
        self.save()
