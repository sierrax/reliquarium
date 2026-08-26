"""Post-scan reporting.

Classifies each catalog entry as Archived / Correct / Bad / Missing against
the files found during a single scan, then formats both a human-readable
report and per-CSV "-needed" CSVs listing what's missing or bad.

Nothing here is persisted. Everything is computed fresh from one scan's
results plus the catalog that was loaded for it -- rerunning a scan and
regenerating the report/needed-CSVs always reflects current reality, with
no stored numbers that could go stale.

Classification rules:
  - Archived: the entry's CSV is marked Archived (see
             core/collections_store.Collection.archived_csvs) -- complete,
             but deliberately no longer physically present in the live
             Base Collections Directory (e.g. burned to disc). Always
             reported as complete regardless of what was scanned; checked
             first, before anything else, and short-circuits the rest of
             this function for that entry.
  - Correct: some scanned file has this entry's exact (filesize, crc32).
  - Bad:     no scanned file matches by content, but a scanned file with
             this entry's filename exists somewhere in the scan (wrong
             content -- corrupted or a different version) -- AND that
             filename isn't also claimed by some other catalog entry. Many
             collections reuse generic sequential names (001.jpg, 002.jpg,
             ...) across every disc's catalog on purpose; without this
             guard, scanning even one disc would make every other disc's
             same-named entries look "Bad" purely from a name collision,
             even though none of their actual files were ever scanned.
  - Missing: neither of the above -- genuinely absent from the scan, or a
             same-named-but-ambiguous case that can't be safely called Bad.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from core.csv_loader import CatalogEntry

OVERALL_KEY = "__OVERALL__"


@dataclass
class EntryStatus:
    entry: CatalogEntry
    status: str  # "Archived" / "Correct" / "Bad" / "Missing"


def classify_entries(
    entries: List[CatalogEntry],
    scanned: Iterable[Tuple[str, int, str]],
) -> List[EntryStatus]:
    """scanned: iterable of (filename, filesize, crc32) for every
    successfully-hashed scanned file, regardless of whether it matched
    anything during the scan itself."""
    scanned = list(scanned)
    correct_keys = {(size, crc.upper()) for (_name, size, crc) in scanned}

    # Filenames present anywhere in the scan (case-insensitive, matching
    # Windows filesystem semantics), used only for the Bad check below.
    scanned_by_filename: Dict[str, set] = defaultdict(set)
    for name, size, crc in scanned:
        scanned_by_filename[name.lower()].add((size, crc.upper()))

    # How many catalog entries (across every loaded CSV) claim each
    # filename. Collections that use generic sequential names (001.jpg,
    # 002.jpg, ...) repeat the same filename across many different discs'
    # catalogs on purpose -- if a name is claimed by more than one entry,
    # a same-named scanned file can't be reliably attributed to any one of
    # them, so filename-based "Bad" detection is skipped for that name and
    # those entries fall back to "Missing" instead of a confident-looking
    # but potentially wrong "Bad". Names unique to a single entry are
    # unaffected and still get precise Bad detection.
    filename_claim_count: Dict[str, int] = defaultdict(int)
    for entry in entries:
        filename_claim_count[entry.filename.lower()] += 1

    results: List[EntryStatus] = []
    for entry in entries:
        if entry.archived:
            results.append(EntryStatus(entry, "Archived"))
            continue
        key = (entry.filesize, entry.crc32)
        if key in correct_keys:
            results.append(EntryStatus(entry, "Correct"))
            continue
        name_key = entry.filename.lower()
        unambiguous_name = filename_claim_count[name_key] == 1
        if unambiguous_name and scanned_by_filename.get(name_key):
            results.append(EntryStatus(entry, "Bad"))
        else:
            results.append(EntryStatus(entry, "Missing"))
    return results


def group_key(entry: CatalogEntry) -> str:
    """Display/grouping key for one entry's CSV: 'Collection/CSV' when it
    belongs to a collection, just 'CSV' for an ad hoc CSV with none. Using
    the collection name here (not just the bare CSV name) matters once more
    than one collection can be loaded into a single scan -- two different
    collections can easily have a same-named CSV (e.g. both call one "CD1"),
    and without the collection prefix their entries would wrongly merge
    into a single reported group."""
    return f"{entry.source_collection}/{entry.source_csv}" if entry.source_collection else entry.source_csv


def split_by_collection(statuses: List[EntryStatus]) -> Dict[str, List[EntryStatus]]:
    """Groups classified entries by their source_collection (empty string
    for ad hoc entries with none). For every scan mode except "All
    Collections" this always produces exactly one group -- every entry in
    those scans shares the same source_collection by construction -- so
    splitting is a no-op there. In "All Collections" mode it's what lets
    each collection get its own separate report instead of one combined
    report covering everything."""
    groups: Dict[str, List[EntryStatus]] = defaultdict(list)
    for s in statuses:
        groups[s.entry.source_collection].append(s)
    return dict(groups)


def per_csv_summary(statuses: List[EntryStatus], key_fn=group_key) -> Dict[str, dict]:
    """Groups classified entries by key_fn(entry) (group_key by default:
    collection+CSV) and computes counts plus percent-complete for each,
    with an additional OVERALL_KEY group covering every entry across all
    groups. Pass key_fn=lambda e: e.source_csv when the statuses have
    already been split by collection (via split_by_collection) -- at that
    point every entry shares the same collection, so repeating it in every
    row label would just be redundant noise."""
    groups: Dict[str, List[EntryStatus]] = defaultdict(list)
    for s in statuses:
        groups[key_fn(s.entry)].append(s)

    def _summarize(items: List[EntryStatus]) -> dict:
        archived = [i for i in items if i.status == "Archived"]
        correct = [i for i in items if i.status == "Correct"]
        bad = [i for i in items if i.status == "Bad"]
        missing = [i for i in items if i.status == "Missing"]
        total = len(items)
        # Archived counts toward completeness -- that's the whole point of
        # marking something Archived: it's trusted complete even though
        # it's no longer physically there to verify.
        pct = ((len(correct) + len(archived)) / total * 100) if total else 0.0
        return {
            "archived": archived, "correct": correct, "bad": bad, "missing": missing,
            "total": total, "percent_complete": pct,
        }

    summary: Dict[str, dict] = {name: _summarize(items) for name, items in groups.items()}
    summary[OVERALL_KEY] = _summarize(statuses)
    return summary


def format_report_text(summary: Dict[str, dict], title: str = "Collection Report") -> str:
    """A compact, summary-only report: one line per CSV plus an overall
    total. Deliberately does NOT list individual filenames -- for large
    collections that made the report balloon in size for little benefit,
    and the actual missing/bad files are exactly what
    format_needed_csv()/"Generate Missing/Bad CSVs..." is for."""
    lines: List[str] = [title, f"Generated: {datetime.now().isoformat(timespec='seconds')}", ""]

    csv_names = sorted(k for k in summary if k != OVERALL_KEY)
    name_width = max([len("CSV")] + [len(n) for n in csv_names]) if csv_names else len("CSV")

    header = (
        f"{'CSV'.ljust(name_width)}  {'Total':>7}  {'Correct':>7}  {'Archived':>8}  "
        f"{'Bad':>5}  {'Missing':>7}  {'Complete':>8}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for csv_name in csv_names:
        data = summary[csv_name]
        lines.append(
            f"{csv_name.ljust(name_width)}  {data['total']:>7}  {len(data['correct']):>7}  "
            f"{len(data['archived']):>8}  {len(data['bad']):>5}  {len(data['missing']):>7}  "
            f"{data['percent_complete']:>7.1f}%"
        )
    lines.append("-" * len(header))

    overall = summary[OVERALL_KEY]
    lines.append(
        f"{'OVERALL'.ljust(name_width)}  {overall['total']:>7}  {len(overall['correct']):>7}  "
        f"{len(overall['archived']):>8}  {len(overall['bad']):>5}  {len(overall['missing']):>7}  "
        f"{overall['percent_complete']:>7.1f}%"
    )
    lines.append("")
    return "\n".join(lines)


def format_needed_csv(items: List[EntryStatus]) -> str:
    """Formats Bad/Missing entries for one CSV as needed-CSV text: the same
    4 columns the app reads back in (filename,filesize,crc32,directory),
    plus a 'status' column that's informative for a human but ignored by
    the app's own CSV loader (extra columns are tolerated)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["filename", "filesize", "crc32", "directory", "status"])
    for item in sorted(items, key=lambda i: i.entry.filename.lower()):
        writer.writerow([
            item.entry.filename, item.entry.filesize, item.entry.crc32,
            item.entry.directory, item.status,
        ])
    return buf.getvalue()


def prune_old_reports(reports_dir: Path, collection_name: str, keep: int) -> List[str]:
    """Deletes older auto-generated reports for one collection, keeping
    only the `keep` most recent. Auto-generated report filenames are
    always "<collection>_<YYYYMMDD_HHMMSS>.txt" -- that timestamp format
    sorts correctly as plain text, so sorting filenames is enough; no need
    to touch file modification times. keep <= 0 means unlimited (nothing
    is pruned). The glob pattern requires the actual 8-digit-underscore-
    6-digit timestamp shape, not just "starts with the collection name" --
    a bare wildcard would also match a manually-saved report using the
    same default filename (e.g. "MetArt_report.txt" from the Generate
    Report... save dialog), which must never be touched by this. Only
    ever touches files matching that exact pattern in this one directory.
    Returns the paths actually deleted (as strings), for logging. Never
    raises; a deletion failure for one file is just skipped, not fatal to
    the rest."""
    if keep <= 0:
        return []
    safe_name = collection_name or "collection"
    digit = "[0-9]"
    timestamp_pattern = digit * 8 + "_" + digit * 6  # YYYYMMDD_HHMMSS
    try:
        matches = sorted(
            reports_dir.glob(f"{safe_name}_{timestamp_pattern}.txt"), key=lambda p: p.name, reverse=True
        )
    except OSError:
        return []
    deleted: List[str] = []
    for p in matches[keep:]:
        try:
            p.unlink()
            deleted.append(str(p))
        except OSError:
            pass
    return deleted
