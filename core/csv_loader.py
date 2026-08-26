"""CSV loading and normalization for the media collection catalog.

Expected CSV format (header required):
    filename,filesize,crc32,directory

Extra trailing columns/commas are tolerated and ignored.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Union


@dataclass(frozen=True)
class CatalogEntry:
    filename: str
    filesize: int
    crc32: str        # normalized: 8-char uppercase hex, no 0x prefix
    directory: str
    row_number: int   # line number in source CSV, for diagnostics
    source_csv: str   # stem of the CSV this entry came from (e.g. "CD1"),
                       # used as the per-CSV output subfolder name
    source_collection: str = ""  # sanitized owning collection's name (or ad
                       # hoc folder name), used as the output subfolder ABOVE
                       # source_csv. Empty for a single ad hoc CSV with no
                       # collection wrapper. Together with source_csv this is
                       # what makes "scan against every saved collection at
                       # once" possible -- each entry carries its own output
                       # location instead of the whole scan sharing one.
    archived: bool = False  # this CSV is marked Archived: complete but no
                       # longer physically present in the live Base
                       # Collections Directory (e.g. burned to disc).
                       # Archived entries are always reported as complete
                       # and skip verification entirely -- see core/report.py


class CsvLoadError(Exception):
    pass


def normalize_crc32(value: str) -> str:
    """Normalize a CRC32 string to 8-character uppercase hex, no prefix."""
    v = value.strip().upper()
    if v.startswith("0X"):
        v = v[2:]
    if not v:
        raise ValueError("empty crc32")
    int(v, 16)  # validate it's actually hex
    v = v.lstrip("0") or "0"
    return v.zfill(8)


def load_collection_csv(
    path: Union[str, Path], source_collection: str = "", archived: bool = False
) -> tuple[list[CatalogEntry], list[str]]:
    """
    Load a collection CSV with columns: filename,filesize,crc32,directory
    Returns (entries, warnings). Raises CsvLoadError if the file can't be
    read at all or contains no usable rows. source_collection and archived
    are stamped onto every entry as-is (the caller is responsible for
    sanitizing source_collection and looking up the correct archived state).
    """
    path = Path(path)
    entries: list[CatalogEntry] = []
    warnings: list[str] = []
    source_csv = path.stem

    if not path.exists():
        raise CsvLoadError(f"File not found: {path}")

    try:
        f = path.open("r", newline="", encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise CsvLoadError(f"Could not open CSV: {exc}") from exc

    def parse_row(row: list, line_num: int) -> tuple:
        """Returns (CatalogEntry or None, warning or None) for one data row."""
        if not row or all(not c.strip() for c in row):
            return None, None
        if len(row) < 4:
            return None, f"Row {line_num}: expected at least 4 columns, got {len(row)}. Skipped."

        filename, filesize_raw, crc32_raw, directory = row[0], row[1], row[2], row[3]

        try:
            filesize = int(filesize_raw.strip())
        except ValueError:
            return None, f"Row {line_num}: invalid filesize '{filesize_raw}'. Skipped."

        crc32_raw = crc32_raw.strip()
        try:
            crc32 = normalize_crc32(crc32_raw)
        except Exception:
            return None, f"Row {line_num}: invalid crc32 '{crc32_raw}'. Skipped."

        directory = directory.strip()
        if not directory:
            return None, f"Row {line_num}: missing target directory. Skipped."

        return CatalogEntry(
            filename=filename.strip(), filesize=filesize, crc32=crc32,
            directory=directory, row_number=line_num, source_csv=source_csv,
            source_collection=source_collection, archived=archived,
        ), None

    with f:
        reader = csv.reader(f)
        try:
            first_row = next(reader)
        except StopIteration:
            raise CsvLoadError("CSV file is empty.")

        header_lower = [h.strip().lower() for h in first_row]
        expected = ["filename", "filesize", "crc32", "directory"]
        looks_like_header = header_lower[:4] == expected

        if not looks_like_header:
            # This CSV has no header row -- the first line is actual data.
            # Parse it instead of silently discarding it (this used to be a
            # real bug: every headerless CSV lost its first row, since the
            # loader always assumed line 1 was a header to skip).
            warnings.append(
                "No header row detected (first row didn't match "
                "'filename,filesize,crc32,directory') -- treated as data."
            )
            entry, warning = parse_row(first_row, 1)
            if entry:
                entries.append(entry)
            if warning:
                warnings.append(warning)

        for line_num, row in enumerate(reader, start=2):
            entry, warning = parse_row(row, line_num)
            if entry:
                entries.append(entry)
            if warning:
                warnings.append(warning)

    if not entries:
        raise CsvLoadError("No valid rows found in CSV.")

    return entries, warnings


def load_multiple_csvs(paths: list, source_collection: str = "", archived_paths=None) -> tuple[list[CatalogEntry], list[str]]:
    """Load and combine several catalog CSVs into one entry list, all
    stamped with the same source_collection (use this when every CSV in
    the batch shares one output collection folder -- for CSVs that belong
    to DIFFERENT collections in one combined load, call load_collection_csv
    directly per CSV with each one's own source_collection instead).
    archived_paths, if given, is a set/container of paths (matching the
    exact strings in `paths`) that should be marked Archived.

    Unlike load_collection_csv, a single unreadable/empty CSV in the batch
    does not abort the whole operation -- it's recorded as a warning and the
    rest are still loaded. Raises CsvLoadError only if none of the CSVs
    could be loaded at all.
    """
    archived_paths = archived_paths or ()
    all_entries: list[CatalogEntry] = []
    all_warnings: list[str] = []
    any_loaded = False

    for p in paths:
        try:
            entries, warnings = load_collection_csv(
                p, source_collection=source_collection, archived=(p in archived_paths)
            )
        except CsvLoadError as exc:
            all_warnings.append(f"{p}: {exc}")
            continue
        any_loaded = True
        all_entries.extend(entries)
        all_warnings.extend(f"[{Path(p).stem}] {w}" for w in warnings)

    if not any_loaded:
        raise CsvLoadError("None of the selected CSVs could be loaded.")

    return all_entries, all_warnings


def load_all_collections(collections: list) -> tuple[list[CatalogEntry], list[str]]:
    """Load every CSV from every given collection into one combined entry
    list, each entry stamped with its OWN owning collection's sanitized
    name (not a single shared one) -- this is what lets a single scan sort
    matched files into the correct collection each belongs to, rather than
    assuming one collection for the whole run. Tolerant of individual
    collection/CSV failures, same as load_multiple_csvs. Raises
    CsvLoadError only if nothing at all could be loaded."""
    from core.path_sanitize import sanitize_windows_name  # local import: avoids a
                                                             # module-load-order dependency
                                                             # for the common case where this
                                                             # function is never called
    all_entries: list[CatalogEntry] = []
    all_warnings: list[str] = []
    any_loaded = False

    for collection in collections:
        collection_name = sanitize_windows_name(collection.name)
        if not collection.csvs:
            all_warnings.append(f"[{collection.name}] has no CSVs, skipped.")
            continue
        for p in collection.csvs:
            try:
                entries, warnings = load_collection_csv(
                    p, source_collection=collection_name, archived=collection.is_archived(p)
                )
            except CsvLoadError as exc:
                all_warnings.append(f"[{collection.name}] {p}: {exc}")
                continue
            any_loaded = True
            all_entries.extend(entries)
            all_warnings.extend(f"[{collection.name}/{Path(p).stem}] {w}" for w in warnings)

    if not any_loaded:
        raise CsvLoadError("None of the CSVs in any collection could be loaded.")

    return all_entries, all_warnings


def build_index(entries: list[CatalogEntry]) -> dict[tuple[int, str], list[CatalogEntry]]:
    """Index catalog entries by (filesize, crc32) for O(1) matching during
    an ingest scan. Archived entries are deliberately excluded from this
    index: they're treated as complete and still (logically) present, so
    a scanned file matching one shouldn't be offered for sorting into that
    CSV's folder (which, per the whole point of archiving, may no longer
    even exist). This only affects ingest matching -- reporting and
    verification (core/report.py's classify_entries) work from the full
    entry list directly and still correctly count archived entries as
    complete regardless of this index."""
    index: dict[tuple[int, str], list[CatalogEntry]] = {}
    for e in entries:
        if e.archived:
            continue
        index.setdefault((e.filesize, e.crc32), []).append(e)
    return index
