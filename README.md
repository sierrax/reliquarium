# Reliquarium

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Build](https://github.com/sierrax/reliquarium/actions/workflows/build.yml/badge.svg)](https://github.com/sierrax/reliquarium/actions/workflows/build.yml)
[![Platform: Windows | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-informational)](#cross-platform-status)

**Got a big disc-based media collection (DVDs, CDs, whatever) with a CSV
catalog of what's supposed to be in it? Reliquarium tells you exactly
what's correct, what's corrupted, and what's still missing — then sorts
the good files into place for you.** Built to replace slow,
single-threaded tools like PicCheck without the sprawl of do-everything
alternatives like Hunter. Matches files by CRC32 checksum rather than
filename, so renamed or relocated files are still recognized correctly.

## Features

- **Four ways to pick a source**, for a single scan or building out a full
  library: a single CSV, an entire folder of CSVs at once, a saved, named
  **Collection** grouping several CSVs together (e.g. "MetArt" containing
  CD1/CD2/CD3 catalogs), or **All Collections** at once — see
  **Collections** below.
- **Light or Dark theme**, defaulting to Dark — switch anytime from
  **View → Theme**; applies immediately and remembers your choice across
  restarts.
- **Multi-threaded CRC32 hashing** — uses all your CPU cores (configurable
  thread count) instead of hashing one file at a time.
- **Persistent hash cache** — remembers each file's CRC32 alongside its size
  and modification time in `data\hash_cache.json`, right next to the app
  itself (see **Portable Storage** below). On a later scan, if a file's size and mtime haven't changed, its hash is
  reused instantly instead of re-reading the whole file — this matters far
  more than thread count for repeat scans of large media collections, since
  CRC32 requires reading every byte. Edited/replaced files are detected and
  re-hashed automatically. A "Clear Hash Cache" button is available if you
  ever want to force a full re-hash.
- **Non-blocking UI** — directory enumeration and hashing both run on
  background threads, so the window never freezes even on huge collections.
- **CSV catalog matching** — matches scanned files against your catalog by
  `(filesize, crc32)`, which is far more reliable than matching by filename.
- **First-run setup** for default folders (CSV / Ingest / Base Collections
  Directory), plus a fuller **Preferences** window for behavior defaults
  (Copy vs. Move, deleting empty directories after a move, recursive
  scanning, and reporting settings) — see **Preferences** below.
- **Remembers your last CSV/folder picks** — the browse dialogs reopen
  wherever you last picked from.
- **Sortable/filterable results table** — filter by Matched / Unmatched /
  Error, or search by filename.
- **Copy or Move** with conflict handling: Skip, Overwrite, or Rename-and-keep-both,
  and an opt-in setting to clean up directories a Move leaves empty behind it.
- **Selective processing** — checkbox per matched row, "Select All Matched"
  for bulk action.
- **Activity log** with CSV export of full results (status, path, target, outcome).
- **Collection completeness report and "-needed" CSVs** — after a scan,
  generate a per-CSV rundown (# correct / bad / missing, % complete) and/or
  regenerate CSVs listing exactly what's missing or wrong, per CSV — see
  **Reporting** below.

## CSV Catalog Format

```
filename,filesize,crc32,directory
Some Movie.mkv,734003200,A1B2C3D4,Movies\Action
Some Show S01E01.mkv,419430400,DEADBEEF,\TV\Some Show\Season 1
```

- `crc32` is expected as hex (with or without leading zeros / `0x` prefix).
- Extra trailing columns/commas in the header are tolerated and ignored.
- `directory` can be a relative path (`Movies\Action`) or a full absolute
  path (`D:\Movies\Action`) — see **Base Collections Directory** below for
  how relative paths are resolved. A leading slash or backslash on an
  otherwise-relative value (like `\TV\Some Show\Season 1` above) is treated
  the same as no leading slash — it's still relative, not anchored to a
  drive root.
- Matching is done by **filesize + crc32 together** — filename does not need
  to match, so renamed files still get identified correctly.
- **The header row is optional.** If the first line looks like
  `filename,filesize,crc32,directory` (case-insensitive) it's treated as a
  header and skipped; if it doesn't, the file is assumed to have no header
  at all and that first line is parsed as real data instead. This is
  detected independently per CSV, so a mix of headered and headerless
  files in the same folder/collection works fine.

## Setup (Windows)

1. Install Python 3.10 or newer from [python.org](https://python.org) (check
   "Add python.exe to PATH" during install).
2. Open a terminal in this folder and install dependencies:

   ```
   pip install -r requirements.txt
   ```

   On Python 3.12+, `requirements.txt` installs `PyQtDarkTheme-fork`
   instead of the original `pyqtdarktheme` package — the original project
   was abandoned in 2022 and caps out at Python <3.12, so pip has nothing
   modern to offer there under that name. The fork uses the same
   `qdarktheme` import name and the same API, so this is handled
   automatically; nothing extra to install by hand. If theming somehow
   ends up unavailable anyway, the app still runs fine without it (falls
   back to the default Qt style, which often already looks reasonably
   dark if your OS is set to dark mode).

3. Run it:

   ```
   python main.py
   ```

## Cross-Platform Status

Windows is the primary, most-tested target — everything above assumes it.
That said, nothing in the code is deliberately Windows-only, and the one
confirmed platform-specific bug has been fixed: catalog CSVs' `directory`
column is typically written with Windows-style backslash separators (e.g.
`Scenes\001`), and only Windows' own path handling understands backslash
as a separator at all. Elsewhere, that string would either get mangled
into one garbled folder name, or — worse, on Linux/macOS specifically,
where *any* leading slash means "absolute path" (there's no drive-letter
concept to require) — get misread as a deliberate absolute path override,
silently discarding the Base Collections Directory entirely. Path
resolution now normalizes separators and judges "is this really meant to
be absolute" using Windows conventions specifically, regardless of which
OS is actually running the app, so the same CSV resolves identically on
either platform.

What that means practically: the app *should* run and organize collections
correctly on Linux and macOS, using the same `pip install -r
requirements.txt` / `python main.py` steps as Windows (a couple of the
`pip install` details, like the theming package, may differ by platform).
But actual real-world use on Linux/macOS is much newer and far less
battle-tested than the Windows path, which has been through months of
testing against a real 198-DVD collection. If you're trying it there,
treat it with the same "smoke test on a small folder first" caution as
anywhere else in this README, and more so.

## Usage

1. **Source** — choose one of four modes:
   - **Single CSV** — browse to one catalog CSV (the classic, simplest case).
   - **Folder of CSVs** — browse to a folder; every `.csv` file directly
     inside it is loaded and combined into one catalog for this scan.
   - **Saved Collection** — pick a previously-created Collection from the
     dropdown (see **Collections** below), or click **Manage Collections...**
     to create one first.
   - **All Collections** — scan against every saved collection at once;
     each matched file sorts into whichever collection it actually belongs
     to. Also has its own **Manage Collections...** button, since there's
     no dropdown here to hang it off of. See **Collections** below for
     details.
2. **Scan Directory** — browse to the folder you want to scan (whether this
   is recursive is set in **Preferences** — see below).
3. **Base Collections Directory** *(optional)* — see **Output Path
   Structure** below for exactly how this is used.
4. Set **Hashing threads** if you want to tune parallelism (defaults to your
   CPU core count).
5. Click **Start Scan**. Files are enumerated, then hashed in parallel; the
   results table fills in live as matches are found.
6. The results table shows **Matched rows by default** — switch the
   **Filter** dropdown to All / Unmatched / Error if you want to see
   everything else, or use the search box to narrow by filename.
7. Check the rows you want to act on (or click **Select All Matched**),
   choose **Copy** or **Move** and a conflict policy, then click
   **Process Selected**.
8. Review the activity log at the bottom, and optionally **Export Log...**
   to save a CSV record of what happened, or generate a completeness
   report / "-needed" CSVs — see **Reporting** below.

## Preferences

The first time you run the app, a lightweight setup dialog asks for three
optional default directories — **CSV Directory** (where the CSV browse
dialogs start out before you've picked anything yet), **Ingest Directory**
(pre-fills Scan Directory), and **Collection Base Directory** (pre-fills
Base Collections Directory). Skip any/all of it if you'd rather set things
up as you go. That's deliberately *all* the first-run wizard asks — a
brand-new user needs directories to do anything useful at all, but has no
real basis yet to judge the behavior preferences below; those start at
sensible defaults and are there to discover once you've actually used the
tool a bit.

**File → Preferences...** opens the fuller version any time after that,
with everything grouped into a few plain sections in one window (not a
multi-page or tabbed settings screen — the app's scope doesn't call for
that):

- **Default Directories** — the same three fields from first-run setup.
  These are *defaults*, not locks — the Scan Directory and Base
  Collections Directory fields on the main window can still be changed
  freely for any individual run without affecting what they default to
  next time. Once you've actually browsed to a CSV or folder-of-CSVs at
  least once, that most-recently-used location takes over as the browse
  dialog's starting point (this was already true before defaults
  existed) — the CSV Directory default is only the starting point before
  that first pick.
- **Default Behavior**:
  - **Default action** (Copy or Move) — sets which one is pre-selected on
    the main window each time the app starts. Unlike everything else in
    Preferences, Copy/Move stays a live control on the main window itself,
    not something tucked away here — it's a genuine per-run judgment call
    as often as it's a fixed preference, so it needs to stay one click
    away during actual use, not two.
  - **Delete empty directories left behind after Move** (off by default)
    — see below.
  - **Scan subdirectories by default** — whether a scan recurses into
    subfolders. This one *did* used to live on the main window as its own
    checkbox; it moved here because for most people it's genuinely a
    "set once and never touch again" choice, freeing up main-window space
    for the controls that actually vary run to run.
- **Reporting** — "Also verify Base Collections Directory for reports",
  "Automatically open report after processing", and "Keep last N
  auto-generated reports per collection" — see **Reporting** below for
  what each one does. These also used to be main-window checkboxes; same
  reasoning as recursive scan.

### Delete empty directories after Move

When enabled, a **Move** batch also cleans up afterward: for every file
that got moved, its original parent folder is removed if that move left
it empty — then *its* parent is checked too, and so on upward, so a whole
chain of now-hollowed-out folders collapses in one pass rather than just
the innermost one. Two folders that shared a parent both get a chance to
empty that parent out, even though they're cleaned up independently.
Never removes anything that still has content in it, and never removes
the Scan Directory itself, no matter how empty it ends up. Off by
default, since it's still a destructive filesystem operation even though
it's scoped tightly to just what the batch actually touched — turning it
on is a deliberate opt-in, not an assumption. The confirmation dialog
before a Move mentions it explicitly whenever it's enabled, so it's never
a surprise after the fact. Has no effect when the action is Copy, since
Copy never empties anything out of the source to begin with.

## Collections

A **Collection** is a named group of CSVs, saved so you can come back to it
later without re-picking files (example: a collection called `MetArt`
containing `CD1.csv`, `CD2.csv`, `CD3.csv`).

- Click **Manage Collections...** to create, rename, delete collections,
  and add/remove CSVs from them. Available from three places: the
  **Collections** menu (always there, regardless of which source mode is
  selected), a button next to the dropdown in "Saved Collection" mode, and
  a button on the "All Collections" page too — that mode has no dropdown to
  hang a button off of, but still needs quick access to manage what it's
  about to scan against.
- Collections are stored in `data\collections.json` (next to the app —
  see **Portable Storage** below) as a small JSON file — human-readable if
  you ever need to inspect or hand-edit it. Only the collection name and
  the list of CSV file paths are stored; nothing is copied, and nothing
  derived (like file counts) is cached there, so it can't go stale.
- If a CSV referenced by a collection has been moved or deleted, it's
  flagged as `[missing]` in the Manage Collections dialog and skipped (with
  a warning in the activity log) rather than aborting the whole scan.
- **Archived CSVs** — select one or more CSVs in the Manage Collections
  dialog and click **Archive Selected** to mark them Archived: complete,
  but deliberately no longer physically present in the live Base
  Collections Directory (the common case is burning a disc's worth of
  files and removing them locally afterward). An Archived CSV:
  - Is always reported as **100% complete**, in reports and the Collection
    Status window alike, regardless of whether its folder exists at all —
    nothing is ever checked against disk for it.
  - Is **never walked during verification** — there's no point checking a
    folder whose contents are deliberately not there.
  - Is **excluded from ingest matching entirely** — a scanned file whose
    content matches something in an Archived CSV shows up as Unmatched
    instead of being offered for sorting, since that slot is considered
    complete and present already. (If the exact same content is *also*
    expected somewhere non-archived, it still matches that live location
    normally — archiving one copy doesn't hide a genuinely-needed one.)
  Click **Unarchive Selected** to reverse it — the CSV goes back to being
  checked and sortable-to normally. Archived status is stored per-CSV in
  the collection's own entry in `collections.json`, so it survives
  renames, moves, and restarts along with everything else.
- **"Folder of CSVs"** mode is the same underlying mechanism without saving
  anything — point it at a folder, every `.csv` directly inside is loaded
  as one combined catalog for that scan only.
- **"All Collections"** mode scans against every saved collection at once —
  matching PicCheck/Hunter's "sort to all collections" behavior. One scan
  of your ingest folder checks it against every collection's catalog
  simultaneously, and each matched file sorts into the specific collection
  it actually belongs to (`<Base Collections Directory>\<that file's own
  Collection>\<its own CSV>\<relative dir>`) — a single mixed batch with
  files from several different collections in it gets split correctly
  without needing separate passes. Reports split the same way: a move that
  touched two different collections produces two separate, correctly-named
  reports (e.g. `MetArt_<timestamp>.txt` and `OtherSite_<timestamp>.txt`),
  not one combined report under a generic "AllCollections" label — see
  **Reporting** below. If two different collections happen to have a CSV
  with the same name (two collections both having a "CD1", say), needed-CSVs
  distinguish them as `CollectionA_CD1-needed.csv` and
  `CollectionB_CD1-needed.csv` rather than merging their numbers together.

### Collection Status window

With a Collection selected, **View Collection Status...** opens a separate,
non-blocking window: a per-CSV table (CSV, Total, Correct, Bad, Missing,
% Complete) for that collection, independent of any ingest scan — "how
healthy is what's already sorted, right now." Click a column header to
sort; sorting by % Complete is the fastest way to see exactly where the
gaps in a large collection are.

It runs its own verification pass, one CSV subfolder at a time (same
approach the main window uses), against `<Base Collections
Directory>\<Collection Name>` using the same shared hash cache as
everything else in the app, so opening it the first time on a large,
already-organized collection takes a while, and **Refresh** afterward is
fast. If that folder doesn't exist yet (nothing's been sorted there yet),
it just shows every CSV at 0% rather than erroring. You can open status
windows for more than one collection at once if you want to compare them
side by side.

A full check here also writes into the same persisted verification cache
the main window's post-move checks read from — so verifying a collection
here, then later moving files into it from the main window, correctly
combines both: the freshly-moved files plus everything this window already
confirmed, not just the freshly-moved files alone.

Every time this window verifies (on open and on each **Refresh**), it also
silently saves a timestamped report to `<default CSV directory>\reports\`
— see **Reporting** below for why reports are always tied to an actual
verification like this one, rather than generated from a plain scan.

## Output Path Structure

Given a **Base Collections Directory**, matched files are placed at:

```
<Base Collections Directory>\[Collection Name]\<CSV name>\<relative dir from that CSV>\<file>
```

The `[Collection Name]` segment only appears when scanning a folder of CSVs,
a saved Collection, or in All Collections mode — it's the folder's name or
the collection's name, sanitized for Windows (invalid characters stripped,
reserved names like `CON` avoided). A single ad hoc CSV (no collection
involved) skips that segment entirely. In **All Collections mode
specifically**, this is resolved per matched file rather than once for the
whole scan — each file's `[Collection Name]` is whichever collection its
own matching catalog entry actually came from, so one mixed ingest batch
correctly splits across multiple collections' folders in a single pass.

**Example** — collection `MetArt`, containing `CD1.csv` with a row
`directory = Scenes\001`, base directory `D:\Collections`:

```
D:\Collections\MetArt\CD1\Scenes\001\
```

If a CSV row's `directory` is already a full absolute path, it's used as-is
and this whole structure is skipped for that row. Leave the base directory
field blank to use every CSV's `directory` values completely unchanged.

## Reporting

**A completeness report is only ever generated alongside an actual
verification of the collection directory — never from a plain scan by
itself.** A scan just finds matches in your ingest folder; it doesn't touch
the collection directory, so a report at that point would only reflect
whatever was last verified (often nothing yet) while looking exactly like a
real completeness number. There are three places verification (and
therefore a report) actually happens:

1. **A Process Selected run that actually moved/copied at least one file**
   — this is the only thing that can really change what's in the
   collection directory, and only for the specific CSV folder(s) those
   particular files landed in. Once a collection has an established
   baseline for the current session (see below), only those touched CSVs
   get re-verified — moving 3 files into disc 46 of a 46-disc collection
   re-walks just disc 46's folder, not the other 45 that couldn't possibly
   have changed. Saved silently (noted in the activity log) to
   `<default CSV directory>\reports\<collection name>_<timestamp>.txt`.
2. **Opening or clicking Refresh in the Collection Status window** — this
   one always does a *full* check of every CSV, since that window's whole
   purpose is "give me complete ground truth right now." Every time it
   runs, it saves a report the same way.
3. **Clicking Generate Report... or Generate Missing/Bad CSVs... manually**
   — both also force a full fresh verification (every CSV in the current
   context) before acting on the result, same reasoning as #2.

If no default CSV directory has been set (see **Preferences** above),
automatic saves (1 and 2) are skipped with a log note rather than
failing; the manual button still works and lets you choose a location.

**In "All Collections" mode, this produces one report per collection
touched, not one combined report.** A move that touched files belonging to
two different collections writes two separate files sharing one timestamp
(`MetArt_<timestamp>.txt`, `OtherSite_<timestamp>.txt`, ...) rather than a
single report under a generic "AllCollections" label — each collection's
report only lists its own CSVs, same as if you'd scanned that collection on
its own. The manual **Generate Report...** button follows the same rule: if
the current catalog spans only one collection (every mode except All
Collections, or All Collections when it only actually touched one), it's
the familiar single-file save dialog; if it spans more than one, it asks
for a folder once and writes one report per collection into it, rather
than popping up a save dialog for each collection in turn.

**The verification itself** is tracked per CSV and scoped to just that
CSV's own subfolder — `<Base Collections Directory>\[Collection
Name]\<CSV name>` (or `<Base Collections Directory>\<CSV name>` for a
single ad hoc CSV with no collection) — never the whole Base Collections
Directory, and (for the post-move case) never CSVs that weren't actually
touched, **except the very first time a given collection is touched by a
move.** A brand new collection (or one that's simply never had an explicit
full check yet) has nothing in the persisted cache at all — a scoped touch
of just one of its CSVs would otherwise leave every *other* CSV in that
same collection looking permanently missing, not because anything's wrong
but because nothing had ever looked at them. So the first time a move
touches a collection with no cache entry for it whatsoever, that one
collection's check is automatically upgraded to a full one (every CSV it
has), and the activity log says so. Once that collection has any persisted
data at all — from that upgrade, a manual full check, or a past session —
later scoped touches go back to being fast and properly scoped.

Verified results for each CSV are kept separately and **persisted
to disk** (`data\verification_cache.json`, next to the app — see
**Portable Storage** below), so a
scoped walk after a move only replaces the touched CSV(s)' data and trusts
whatever was already known about every other CSV — including from a
*previous session*. Restarting the app doesn't force a full re-check; the
first post-move verification after launch can go straight to being scoped
and fast, as long as that collection has been checked before. It uses the
same hash cache as everything else, so a genuinely first-ever pass over a
large existing collection takes a while, but every pass after that — this
session or a future one — is fast (only new or changed files get
re-hashed, and post-move passes only touch the CSVs that could have
changed at all). **Preferences → Reporting** has an "Also verify Base
Collections Directory for reports" setting (on by default) that lets you
skip verification entirely if you'd rather only ever see completeness for
what's in the current ingest batch.

**Two more report-related settings live in that same Preferences section:**

- **"Keep last N auto-generated reports per collection"** (default 10, 0 =
  unlimited) — auto-generated, timestamped reports for a collection older
  than the N most recent are deleted automatically right after a new one
  is written, for both the post-move auto-report and the Collection Status
  window's own auto-save. This only ever touches files matching the exact
  `<collection>_<timestamp>.txt` naming pattern in the reports folder —
  it never touches a different collection's reports, and it never touches
  anything you've manually saved via **Generate Report...**'s save dialog
  (even one using the same collection name as a filename prefix), since
  those don't have the timestamp shape this looks for.
- **"Automatically open report after processing"** (off by default) —
  opens each report with your OS's default handler for `.txt` files (the
  same thing double-clicking it would do) right after **Process Selected**
  finishes and its report is written. If a move touched more than one
  collection, each one's report opens separately. This is specifically
  about the post-move report — opening/refreshing the Collection Status
  window doesn't trigger it, since that's a different, on-demand action.

**This is a "trust it, refresh occasionally" cache, same as the hash
cache** — it does not detect changes made outside the app. If you
manually move, delete, or replace files in the collection directory
without going through Reliquarium, the verification cache won't know until
something actually re-walks that CSV's folder again: a full check (the
Collection Status window, or the manual report buttons) is how that gets
caught. Worth running one of those occasionally regardless, the same way
you'd periodically double-check any cache. Clearing the hash cache also
clears this verification cache, forcing the next checks of both kinds to
start fresh.

If nothing's ever been moved into a given collection yet, verification
correctly shows 0% complete rather than needing some "first verification"
to establish a baseline — an unverified collection and a verified-but-empty
one look identical, because until something's actually been moved in, they
*are* identical. And if you switch to a different collection between
actions, stale data from whatever was previously verified is automatically
cleared rather than leaking into the new collection's numbers.

Two buttons above the results table give you on-demand control, both
working per-CSV since a "collection" of CD1/CD2/CD3 usually needs to be
tracked separately per disc:

- **Generate Report...** — forces a fresh verification, then lets you pick
  the filename/location yourself (defaults into
  `<default CSV directory>\reports` too) rather than just dropping a
  timestamped file silently. Useful for a report you want to keep
  permanently, or for checking right now without waiting on a move.
  **Summary only** — one line per CSV (Total / Correct / Bad / Missing /
  % Complete) plus an overall total; it deliberately does not list
  individual filenames, so it stays a manageable size even for a collection
  with hundreds of CSVs. If you need to know exactly *which* files are
  missing or bad, that's what the next button is for.
- **Generate Missing/Bad CSVs...** — also forces a fresh verification, then
  writes one `<CSV name>-needed.csv` per CSV that has anything wrong,
  listing only the Bad/Missing rows in the same 4-column format the app
  reads back in (plus a `status` column noting which), so it can be handed
  off to whoever's filling the gaps or fed back into the app later.
  Defaults into `<default CSV directory>\needed`. **This one is never
  automatic** — regenerating -needed CSVs is a deliberate action you take
  when you're ready to act on gaps, not a side effect of anything else.

A file counts as:
- **Archived** — the entry's CSV is marked Archived (see **Collections**
  above). Always counts as complete, checked before anything else below,
  regardless of what was or wasn't found during scanning.
- **Correct** — some scanned file (from the ingest scan, or a collection-
  directory verification pass) has that exact
  `(filesize, crc32)`.
- **Bad** — no scanned file matches by content, but a file with that exact
  **filename** exists somewhere in the scan (wrong content — corrupted or
  a different version) — *and* that filename isn't also used by some other
  catalog entry. Collections built around generic sequential names
  (`001.jpg`, `002.jpg`, ...) reuse the same filename across every disc's
  catalog on purpose; without this check, scanning even one disc would make
  every *other* disc's same-named entries look "Bad" from a pure name
  collision, despite none of their real files ever being scanned. When a
  name is ambiguous like that, the entry falls back to Missing instead.
- **Missing** — neither of the above.

`% Complete` counts **Correct + Archived** entries against the total.

Nothing about this is persisted anywhere. Both are computed fresh from the
most recent scan's results plus the catalog that was loaded for it, so
rerunning a scan and regenerating either one always reflects current
reality — there's no separate tracked state that could drift out of sync.

## Building a standalone .exe (optional)

**The easiest option is to just grab a pre-built release** — pushing a
`v*` tag triggers `.github/workflows/build.yml`, which builds both a
Windows (onedir) package and a Linux AppImage (built against an Ubuntu
24.04 base — see **Cross-Platform Status** above) and attaches them to a
GitHub Release automatically.

To build it yourself instead, if you'd rather not require Python on the
machine you run this on:

```
pip install pyinstaller
pyinstaller --noconsole --onefile --name Reliquarium --icon assets\icon.ico --add-data "assets\icon.ico;assets" main.py
```

`--icon` sets the `.exe` file's own icon (what you see in File Explorer);
`--add-data` bundles the icon file itself so the app can also set it as the
window/taskbar icon at runtime — both are needed, they do different things.
(The CI build above uses `--onedir` instead of `--onefile` — faster startup,
no temp-extraction step — but either works fine for local use.)

The resulting `.exe`'s `data\` folder (hash cache, collections, etc.) is
created next to wherever the `.exe` itself ends up living, not inside
PyInstaller's temporary extraction folder — so the whole portable-storage
behavior described in **Portable Storage** above works exactly the same
for the built `.exe` as it does running from source.

### Building the Linux AppImage yourself

The CI workflow (`.github/workflows/build.yml`) is the reference
implementation and the easiest way to see the exact steps — in short:
`pyinstaller --onedir`, assemble an `AppDir` using
`packaging/linux/reliquarium.desktop` and `assets/icon.png`, then run
[linuxdeploy](https://github.com/linuxdeploy/linuxdeploy) (its Qt plugin
is deliberately **not** used — PyInstaller's own PySide6 hooks already
correctly bundle everything Qt-related, including the platform plugins
needed to actually open a window on Linux; linuxdeploy's Qt plugin
expects a conventional Qt SDK layout that a PyInstaller build doesn't
have, and running it on top of an already-bundled build is redundant at
best) to resolve any remaining non-Qt shared library dependencies and
produce the final `.AppImage`. Building inside a pinned base (the
workflow uses an `ubuntu:24.04` container via Docker, not a GitHub-hosted
runner image — those don't go back nearly that far anymore) matters for
compatibility: glibc is forward-compatible but not backward-compatible,
so a binary built against a newer glibc than a user's system has will
simply refuse to run there. 24.04 is a deliberate choice rather than
reaching for the oldest possible baseline — this tool's actual audience
skews toward people already on something newer than what PicCheck/Hunter
get along with (Windows 11, say), so a couple-years-back Linux baseline
is a reasonable bet on who's really running this, not an attempt at
maximum-possible compatibility with very old systems.

The resulting `.exe` will be in `dist/`.

## Project Structure

```
main.py                       entry point
core/csv_loader.py            CSV parsing + normalization + lookup index (multi-CSV and multi-collection combining)
core/scanner.py                directory enumeration + parallel CRC32 hashing (cache-aware)
core/hash_cache.py             persistent CRC32 cache (path+size+mtime -> hash)
core/verification_cache.py     persistent per-CSV collection-verification results (survives app restarts)
core/collections_store.py      persistent named collections (JSON)
core/path_sanitize.py          Windows-safe name sanitizing for collection/folder names
core/report.py                 correct/bad/missing classification + report & needed-CSV formatting
core/resources.py               locates bundled read-only files (icon) whether run from source or a frozen .exe
core/portable.py                 locates the app's own persistent data/ directory + migrates legacy %LOCALAPPDATA% data
core/version.py                 single source of truth for the version number
assets/icon.ico, icon.png       app icon
core/file_ops.py               move/copy with conflict resolution + empty-directory cleanup after Move
ui/main_window.py              main window / application logic
ui/collections_dialog.py       Manage Collections dialog
ui/collection_status_window.py per-collection completeness dashboard (separate window)
ui/setup_dialog.py             first-run wizard / Preferences dialog (directories + behavior + reporting)
ui/results_model.py            Qt table model + status/search filter proxy
ui/processing_thread.py        background thread for move/copy jobs
LICENSE                        MIT
CHANGELOG.md                   what changed, release by release
.github/workflows/build.yml    CI: builds the Windows package + Linux AppImage, attaches to Releases on a v* tag
packaging/linux/reliquarium.desktop   desktop entry used when assembling the AppImage
```

## Non-Goals (Deliberately Out of Scope, Forever)

This tool exists specifically to be the un-bloated alternative to PicCheck
and Hunter — that only stays true if it says no to things. Recorded here so
the boundary doesn't quietly erode one "just a small addition" at a time:

- **No built-in file explorer / "browse this collection" view.** Your OS
  file manager is already better at this than anything built here would
  be. The Collection Status window shows *numbers*, not a file tree, on
  purpose.
- **No built-in image/media viewer.** There are excellent, dedicated,
  actively-maintained free tools for viewing images and media already.
  Reliquarium's job ends at telling you what's correct, missing, or bad —
  not at showing it to you.
- **No built-in duplicate-finder.** A different problem (identical content
  under different names/locations within a single tree) from what this
  tool solves (matching known-good files against a catalog); a real
  dedicated dupe-finder will always do it better.
- **No thumbnail previews in the results table.** Turns a fast, scriptable
  list into a slow image gallery for no functional benefit — again, that's
  what an actual file manager or image viewer is for.
- **No scheduler / watch-folder daemon.** This is a tool you run when you
  decide to run it, not a background service silently doing things to your
  files. If automation is ever wanted, that's a job for the OS's own task
  scheduler calling this tool, not a feature built into it.

If a feature request would only make sense by re-implementing something a
dedicated tool already does well, the answer is to shell out to that tool
(or just tell the user to use it directly), not to build a worse version
of it here.

## Roadmap

Still ahead, once everything above has had some real-world mileage on it:

- **Repository-managed CSVs** — an option to import/copy CSVs into a
  dedicated folder owned by the tool (rather than only referencing them
  where they already live), for collections you want fully self-contained.

## Known Issues (Might-Fix)

Minor, low-priority polish items — noted so they don't get lost, not
urgent enough to interrupt real work for:

- On a scan with large file counts, the live "Hashing X / Y" count next to
  the progress bar can get clipped at the right edge of the window instead
  of wrapping or truncating gracefully.

## Portable Storage

Everything Reliquarium persists — the hash cache, saved collections, the
verification cache, and your saved defaults/settings — lives in a `data\`
folder created right next to the app itself:

```
<wherever Reliquarium.exe or main.py lives>\data\hash_cache.json
                                          \data\collections.json
                                          \data\verification_cache.json
                                          \data\settings.ini
```

Nothing is written to `%LOCALAPPDATA%`, `%APPDATA%`, or the Windows
registry anymore. This means the whole app — code (or `.exe`) plus its
`data\` folder — is a single self-contained unit: copy the folder to a USB
drive, a different machine, a synced cloud folder, wherever, and it keeps
working with everything intact. Delete the folder and it's like it was
never installed, with nothing left behind elsewhere on the system.

**If you're upgrading from an older version** that stored data in
`%LOCALAPPDATA%\MediaOrganizer\`, that data is migrated automatically the
first time you run the new version — your existing hash cache,
collections, verification history, and saved defaults all carry forward
into the new `data\` folder. The activity log shows the data directory
path and, if anything was carried forward, exactly what — this isn't
silent, so you can confirm it actually happened rather than just hoping.
The migration only ever copies (never deletes the original) and only runs
if the new `data\` folder doesn't already have its own data in it, so it's
safe even if something about your setup is unusual.

## Notes

- This code was written and syntax-checked in a sandbox without network
  access, so it could not be run end-to-end against a live Qt display before
  handing it to you. It's built from well-established PySide6 patterns
  (QThreadPool for hashing, QThread for enumeration/processing, a proper
  QAbstractTableModel for the results view) and passes `py_compile` cleanly,
  plus targeted logic tests for the CRC32 cache, path resolution, CSV
  combining, name sanitizing, collections persistence, and the
  correct/bad/missing classification + report formatting (all pass) — but
  please do a smoke test on a small test folder/CSV first before pointing it
  at your real collection, especially before using **Move**.
- "Move" is intentionally guarded behind a confirmation dialog since it's
  destructive to the source location.
