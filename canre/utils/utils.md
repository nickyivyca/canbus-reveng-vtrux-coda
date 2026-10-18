# canre.utils Reference

> **Staleness check:** Each section shows a `Source last modified` timestamp. If the `.py` file's mtime is newer than the timestamp shown here, re-read the source before relying on this documentation.

Shared utilities for file I/O, multi-file merging, and session discovery.

---

## io.py — Streaming File Reading
*Source last modified: 2026-02-15 12:38:32*

Low-level line streaming and line counting for large CAN log files. Handles encoding detection automatically.

### `stream_lines(path) -> Iterator[str]`

Yields lines from a file with trailing newlines stripped.

**Encoding strategy**: Opens as UTF-8 first. If a `UnicodeDecodeError` occurs (at open time or mid-stream), falls back to Latin-1, which accepts every byte value and never raises a decode error. If the error occurs mid-stream, the file is reopened from the beginning in Latin-1, meaning some lines may be yielded twice in the rare case of a mid-file encoding failure.

### `count_lines(path) -> int`

Counts lines quickly using binary reads (1 MiB buffer). Counts `\n` bytes directly, avoiding encoding overhead. Useful for progress bars on large files.

---

## merge.py — Multi-File Capture Merging
*Source last modified: 2026-09-27 16:49:21*

> ### Use `detect_capture_sessions()`, not `detect_capture_groups()`
>
> `detect_capture_groups()` keys purely off filenames and assumes (a) `_M{n}` is a
> **bus** and (b) `_T{n}` runs in **time order** within a prefix. Real logs in this repo
> violate both, in both vehicles:
>
> | Evidence | What it breaks |
> |---|---|
> | Vtrux `truklog_M0/M1/M2` start 13:27, 15:27, 16:32 same day | M is a **separate session**, not a bus |
> | Coda `17_drive_M1_T15` / `_M2_T15` start **12 s apart** | here M really **is** a simultaneous bus |
> | Coda `17_drive_M0_T12` = 2024-12-11, `_M0_T13` = 2024-12-19 | one M spans unrelated captures 8 days apart |
> | Coda `partsdrive_M0_T0` = 2025-07-29, `_T1` = **2026-01-25** | **T order is not time order** |
>
> Because both M conventions occur, neither can be inferred from names.
> `detect_capture_groups()` returns all of `truklog_M0/M1/M2` as **one** group, so
> merging it produces a single stream spanning three unrelated charge sessions — which
> silently corrupts any "time into session" reasoning.
>
> `detect_capture_groups()` is retained for backward compatibility only.

Merges multi-file captures into a single time-sorted frame stream. Two naming conventions are supported:

### Naming Conventions

**`_M{bus}_T{chunk}` style** (BUSMASTER multi-bus):
```
<prefix>_M{bus}_T{chunk}.log
```
Used when BUSMASTER is configured with a fixed base filename. Each new logging start = new M number; M encodes which physical bus the chunk belongs to. Frames get their bus number overridden by the M value from the filename.

**`_T{chunk}` style** (timestamp-keyed sessions):
```
<prefix>_T{chunk}.log
```
Used when the session prefix already encodes identity (e.g. timestamp-keyed files like `coda_20260328_101624_T0.log`). No M number means no bus override — frames keep the bus number recorded in the file.

### `detect_capture_sessions(paths_or_dir, *, split_gap_s=3600.0, merge_simultaneous_m=True, simultaneous_tol_s=60.0) -> dict[str, list[Path]]`

**Preferred.** Groups files into capture sessions using each chunk's actual start time rather than trusting the filename. Fixes the three defects listed in the box above:

1. **M is not assumed to be a bus.** Each `_M{n}` is its own session *unless* the start times prove the M-groups ran concurrently.
2. **Chunks are sorted by real start time**, not by T number.
3. **Sessions split on wall-clock gaps** larger than `split_gap_s`, so one prefix spanning unrelated captures yields separate sessions.

- `split_gap_s` (default 3600) — gap between consecutive chunks that starts a new session. `float('inf')` disables splitting.
- `merge_simultaneous_m` (default True) — M-groups whose first chunks start within `simultaneous_tol_s` are treated as concurrent buses of one session and merged.
- `simultaneous_tol_s` (default 60) — tolerance for that concurrency test.
- Returns: dict mapping session key → time-ordered `Path` list. Keys look like `"<prefix>_M0"`, or `"<prefix>_M1+M2"` when M's are merged as concurrent buses; a `#2`, `#3`… suffix marks each extra session produced by gap-splitting.
- Chunks with no readable start time are appended after the timed ones in T order — never dropped.

Verified against all three real conventions:

| Input | `detect_capture_groups` | `detect_capture_sessions` |
|---|---|---|
| Vtrux `truklog_M0/M1` (hours apart) | 1 group | `truklog_M0`, `truklog_M1` |
| Coda `17_drive` (M1/M2 concurrent + M0 across two dates) | 1 group | `17_drive_M0`, `17_drive_M0#2`, `17_drive_M1+M2`, `17_drive_M1+M2#2` |
| Coda `partsdrive` (T order ≠ time order) | 1 group, wrong order | 2 sessions, time-ordered (`partsdrive_M0`, `partsdrive_M0#2`) |

> **Note (2026-09-21):** this row used to read "4 sessions". Two of the four
> `partsdrive_*` files were Vtrux Powertrain captures misfiled under Coda and
> have been moved to the Vtrux log folder (log folders are internal-only
> and not part of the public repo).
> The row above is the re-measured result on the files that remain; the
> behaviour being demonstrated is unchanged.

### `read_chunk_start(path) -> float | None`

Absolute start time of a capture chunk as an epoch float. Reads the BUSMASTER `***START DATE AND TIME DD:MM:YYYY HH:MM:SS:mmm***` header (**day-first**); for candump files uses the first frame's epoch. Returns `None` if neither is present.

### `detect_capture_groups(paths_or_dir) -> dict[str, list[Path]]`

**Deprecated — see the warning box above.** Groups files by filename prefix only. Tries `_M{bus}_T{chunk}` first; falls back to `_T{chunk}`.

- Returns: dict mapping prefix to `Path` list ordered by `(bus, chunk)`
- Files matching neither pattern are silently ignored
- Retained for backward compatibility; new code should use `detect_capture_sessions()`

### `merge_files(paths, bus_map=None) -> Iterator[CANFrame]`

Parses multiple log files and yields frames sorted by timestamp using a heap merge.

- Uses `absolute=True` so T-chunk files chain correctly on a shared timeline (requires `busmaster.py` to parse the `***START DATE AND TIME***` header for the wall-clock epoch)
- **Bus number** on each frame is overridden by `_M{bus}` from the filename only if `_M{bus}_T{chunk}` pattern matches; T-only files are not overridden
- **`bus_map`** (optional, from `buses.resolve_files()`): per-file `{raw channel: bus name or None}`. When given, `frame.bus` becomes the bus **name** (a `str`), frames on channels mapped to `None` are dropped, and the `_M` override is not applied. Use it whenever a tool needs "the PT bus" of an Android capture — see `buses.py` below.
- Heap merge uses `(timestamp, index)` as key; index is a per-file counter for tie-breaking
- All timestamps shifted so earliest frame becomes `t=0`

---

## buses.py — Channel -> Bus Resolution
*Source last modified: 2026-09-25 17:05:49*

Resolves raw logger channel numbers to named buses **per file**, for tools that
analyse a merged multi-file stream. Written 2026-09-25 after two tools locked to the
first channel carrying `0x051` and discarded a whole Android session.

**Why neither older rule works.** Android T0 chunks re-number one bus several times
**in sequence** — `vtrux_20260925_155857_T0` carries powertrain on ch 8 (0-22.8 s),
10 (31.4-33.0 s), 14 (48.3-54.3 s), 16 (75.7-77.1 s) and 18 (97.5 s on), with disjoint
spans. "First channel with the anchor" keeps only ch 8; "highest-count claimant wins"
(`tools/influx_upload.identify_buses`) keeps only ch 18 and drops ch 14, which held the
event being investigated.

**Rule.** Each channel gets the bus whose anchor set it matches by the highest
*fraction* (identify_buses' step 1). Among channels with the same name, every
claimant is kept unless its time span overlaps a busier claimant's by more than
`OVERLAP_TOLERANCE_S` (1 s) — only then is it concurrent duplicate traffic. Channels
matching no anchor map to `None`.

### `scan_channels(path) -> dict[int, ChannelSpan]`
One full parse: per raw channel, `count`, `first_ts`, `last_ts` (file-relative) and
`ids`. ~3.6 s per 50 MB BUSMASTER chunk on `the Linux box`.

### `resolve_channels(spans, bus_anchors, tolerance_s=1.0) -> dict[int, str | None]`
`bus_anchors` is a list of `(name, {ids})`, same shape as `influx_upload.VEHICLE_PROFILES[...]["bus_anchors"]`.

### `resolve_files(paths, bus_anchors) -> dict[Path, dict[int, str | None]]`
`scan_channels` + `resolve_channels` for each file; pass the result to
`merge_files(paths, bus_map=...)`.

### `describe(bus_map) -> list[str]`
One report line per file, e.g. `..._T0.log: obd=ch7+9+13+15+17, powertrain=ch8+10+14+16+18`.

**Users:** `projects/vtrux/tools/diagnose_vtrux.py`,
`projects/vtrux/tools/vtrux_charge_failure_analysis.py`.

---

## sessions.py — Session Grouping
*Source last modified: 2026-02-16 19:32:51*

Higher-level session discovery that groups log files by the `_M#_T#` pattern and splits on filesystem timestamp gaps.

### `group_files_by_session(folder) -> dict[str, list[Path]]`

Groups `.log` files in a directory into sessions.

**Grouping rules:**
1. Files matching `_M#_T#` are grouped by M number
2. Within each M group, sorted by mtime then T number
3. Mtime gap > **1 hour (3600 seconds)** splits into sub-sessions (`M0_a`, `M0_b`, etc.)
4. Within each sub-session, re-sorted by T number for correct chaining
5. Non-matching files become single-file sessions keyed by filename stem

**Example return value:**
```python
{
    "M0": [path_M0_T0, path_M0_T1, path_M0_T2],
    "M1_a": [path_M1_T0, path_M1_T1],
    "M1_b": [path_M1_T3, path_M1_T4],
    "full charge then fail": [path_standalone],
}
```

### `list_session_files(folder) -> tuple[dict[str, list[Path]], list[Path]]`

Convenience wrapper. Returns:
- `grouped_sessions`: dict of sessions with multiple files or `_M` prefix
- `standalone_files`: flat list of single-file sessions that didn't match the pattern

---

## timebase.py — BUSMASTER Anchor Resolution
*Source last modified: 2026-09-27 16:40:16*

Decides the absolute instant a log file's **first frame** occurred, which is the anchor
callers need because `BusmasterParser.parse_file()` re-bases every file so its first data
frame is `t=0`.

Two loggers in this project write BUSMASTER files differently:

```
Android logger (CANLogs), coda_20260505_192535_T0..T3
  T0  hdr 19:25:35  first 00:00:00  last 00:04:59   <- resets every chunk
  T1  hdr 19:30:35  first 00:00:00  last 00:05:00

Laptop BUSMASTER, debuglog_M1_T8..T10
  T8  hdr 12:07:43  first 11:04:39  last 12:12:43   <- wall clock, HEADER TIME IS WRONG
  T9  hdr 12:12:43  first 12:12:43  last 12:17:43   <- wall clock, header exact
```

- `relative` — data starts at 0, so only the header can say what time of day it was.
- `wallclock` — the data carries the true time of day, so only the header's **date** is
  trusted and a wrong header *time* is recoverable.

Measured over the corpus: 324 of 3,156 files are wall clock.

**BUSMASTER does not wrap the hour at midnight** — `charge_M0_T52.log` contains
`24:01:29:4480`. Day rollover falls out of the `floor(first_T / 86400)` term; no rollover
counter exists or is needed.

### `TimebaseIndex()`

Caches classification per directory. Sessions come from `detect_capture_sessions()`.

- `kind(path) -> "wallclock" | "relative"`
- `anchor_ns(path, tz=timezone.utc) -> int | None` — integer-nanosecond epoch of the first
  frame. Returns `None` when there is no usable header so callers can keep their own
  filename/mtime fallbacks.

Sessions are discovered over the file's whole directory, not just the paths the caller
passed, so uploading a single chunk still gets the verdict its siblings imply. Only headers
and two lines per file are read.

### `classify_session(paths) -> str`

**Classification is per session, never per file.** `debuglog_M1_T8`'s own header disagrees
with its own data and is only decidable because its last timestamp meets `T9`'s first
exactly (`12:12:43:2001` both).

Evidence, strongest first:
1. **Chunks reset** — every chunk starting within 60 s of zero is the Android logger writing
   per-chunk offsets → `relative`.
2. **Header agreement** — first frame near its header's time of day, compared mod 86400 so a
   >24 h session still matches. Majority decides.
3. **Continuity** — chunk N's last frame meeting chunk N+1's first means one running clock;
   combined with a single agreeing header this carries a session whose other headers are
   unreliable.

Defaults to `relative` (the pre-existing behaviour), so an unrecognised layout is never
newly displaced.

### `read_header_datetime(path) -> datetime | None`

Parses `***START DATE AND TIME DD:MM:YYYY HH:MM:SS:mmm***`, day-first.

> The header's sub-second field is **milliseconds**, unlike the data lines, whose trailing
> field is 10 kHz ticks (0.1 ms). Measured across 1,062 headers the value never exceeds 998,
> while data-line values reach 9999 — the two fields use different units despite looking
> alike. `merge.read_chunk_start()` has always read it as milliseconds and is correct.

### `read_data_bounds(path, tail_bytes=65536) -> tuple[float, float] | None`

First and last data-line timestamps in seconds. Reads the head for the first and seeks to
the tail for the last, so cost is independent of file size.
