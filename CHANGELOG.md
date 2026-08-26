# Changelog

All notable changes to Reliquarium are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.0.0] — First public release

Reliquarium replaces slow, single-threaded catalog-checking tools like
PicCheck, without the sprawling complexity of do-everything alternatives
like Hunter: scan a directory, match files against CSV catalogs by CRC32,
sort matches into place.

### Core matching and sorting
- Multi-threaded CRC32 hashing with a persistent hash cache (path + size +
  mtime → checksum), so repeat scans only re-hash files that actually changed.
- Four source modes: a single CSV, a folder of CSVs, one saved Collection,
  or **All Collections** at once — a single scan can check an ingest batch
  against every saved collection simultaneously, sorting each matched file
  into whichever collection it actually belongs to.
- Copy or Move, with Skip / Overwrite / Rename-and-keep-both conflict
  handling, and a selective results table (checkbox per matched row,
  filter by Matched / Unmatched / Error, search by filename).
- "Bad" detection (right filename, wrong content) that's careful about
  collections using generic sequential filenames across many discs' worth
  of catalogs — a name claimed by more than one catalog entry falls back
  to "Missing" rather than a possibly-wrong "Bad".

### Collections
- Named Collections group several CSVs together and persist across
  sessions, with a dedicated management dialog (create, rename, delete,
  add/remove CSVs).
- **Archived CSV status** — mark a CSV as complete but no longer
  physically present (e.g. burned to disc and removed locally). Archived
  CSVs always report as complete, are never re-verified, and are excluded
  from ingest matching so nothing gets offered for sorting into a folder
  that's deliberately not there anymore.

### Reporting and verification
- Summary-only completeness reports (CSV / Total / Correct / Archived /
  Bad / Missing / % Complete), generated only alongside an actual
  verification pass — never from a plain scan alone, so the numbers are
  never misleading.
- Collection-directory verification persists to disk per (collection,
  CSV) pair, so a post-move check only re-walks what actually changed,
  and restarting the app doesn't force a full re-check. A collection with
  no prior verification history automatically gets a full check the first
  time it's touched, so nothing gets silently stranded as "missing".
- A separate Collection Status window per collection for an on-demand
  full completeness check, independent of any particular scan.
- All Collections mode reports split per collection rather than combining
  into one report, so a move touching several collections produces
  separately-named, separately-readable results for each.
- Configurable report retention (keep the last N auto-generated reports
  per collection) and an option to automatically open a report with your
  default text editor right after processing finishes.

### Preferences
- A lightweight first-run wizard for default directories; a fuller
  Preferences window (opened later) adds default behavior (Copy vs. Move,
  recursive scanning, and optional automatic cleanup of directories a
  Move leaves empty behind it) and reporting settings — grouped plainly
  in one window, deliberately not a multi-page settings screen.

### Portability
- Fully portable storage: hash cache, collections, verification history,
  and settings all live in a `data/` folder next to the app itself — no
  registry, no `%LOCALAPPDATA%`. Existing installs migrate automatically
  and transparently on first launch of a version with this change.
- Cross-platform path handling — catalog directory values normalize
  correctly regardless of host OS, tested against both Windows and POSIX
  path semantics directly rather than assumed.
- Light/Dark theming, with graceful degradation across different
  generations of the underlying theming package's API.

### Distribution
- Windows: portable, no-install `.exe` (and a onedir build), built with
  PyInstaller.
- Linux: AppImage, built against an older glibc baseline for broad
  compatibility with systems that aren't running the newest release.
