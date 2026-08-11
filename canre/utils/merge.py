"""Merge multi-file captures.

Two naming conventions are supported:

    <prefix>_M{bus}_T{chunk}.log  -- BUSMASTER multi-bus sessions
    <prefix>_T{chunk}.log         -- timestamp-keyed single-bus sessions

Why two patterns?  BUSMASTER assigns a new M number each time you click
"Start Logging" within a project whose base filename is fixed in settings
(e.g. ``highway_cruise``).  Multiple physical CAN buses logged at the same
time each get their own M number (M0, M1, ...), so M encodes which bus a
chunk belongs to and T encodes time order within that bus.

When log files are keyed by a timestamp instead of a fixed base name (e.g.
``coda_20260328_101624_T0.log``, ``coda_20260328_101624_T1.log``) there is
no M number -- each session gets a unique prefix and T numbers are just
time-ordered chunks of a single-bus capture.  Bus numbers come from the
frame data as recorded; no bus override is applied.

Example groups::

    # M_T style (multi-bus)
    highway_cruise_M0_T0.log
    highway_cruise_M0_T1.log
    highway_cruise_M1_T0.log

    # T-only style (timestamp-keyed single-bus)
    coda_20260328_101624_T0.log
    coda_20260328_101624_T1.log
"""
from __future__ import annotations

import heapq
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterator

from canre.parsers import parse_file
from canre.parsers.base import CANFrame

# Regex for BUSMASTER multi-bus sessions: <prefix>_M{bus}_T{chunk}.ext
_MBUS_TCHUNK_RE = re.compile(
    r"^(?P<prefix>.+?)_M(?P<bus>\d+)_T(?P<chunk>\d+)(?P<ext>\.[^.]+)$",
    re.IGNORECASE,
)

# Regex for timestamp-keyed single-bus sessions: <prefix>_T{chunk}.ext
# Used when there is no M number (session prefix already encodes identity).
_TCHUNK_RE = re.compile(
    r"^(?P<prefix>.+?)_T(?P<chunk>\d+)(?P<ext>\.[^.]+)$",
    re.IGNORECASE,
)


def detect_capture_groups(
    paths_or_dir: list[Path | str] | Path | str,
) -> dict[str, list[Path]]:
    """Group files by capture session.

    Parameters
    ----------
    paths_or_dir:
        Either a list of file paths, or a single directory path.

    Returns
    -------
    dict mapping session prefix (str) to a list of Paths, sorted by
    (bus, chunk) so that iterating in order yields time-sorted streams
    per bus.
    """
    if isinstance(paths_or_dir, (str, Path)):
        paths_or_dir = Path(paths_or_dir)
        if paths_or_dir.is_dir():
            paths = list(paths_or_dir.iterdir())
        else:
            paths = [paths_or_dir]
    else:
        paths = [Path(p) for p in paths_or_dir]

    groups: dict[str, list[tuple[int, int, Path]]] = defaultdict(list)

    for p in paths:
        if not p.is_file():
            continue
        m = _MBUS_TCHUNK_RE.match(p.name)
        if m:
            prefix = m.group("prefix")
            bus = int(m.group("bus"))
            chunk = int(m.group("chunk"))
            groups[prefix].append((bus, chunk, p))
        else:
            # Fall back to T-only pattern (no bus number).
            m2 = _TCHUNK_RE.match(p.name)
            if m2:
                prefix = m2.group("prefix")
                chunk = int(m2.group("chunk"))
                # bus=0 used as sort key only; no bus override is applied
                # (frames keep the bus number recorded in the file).
                groups[prefix].append((0, chunk, p))
        # Files matching neither pattern are ignored.

    # Sort each group by (bus, chunk) and return just the paths.
    result: dict[str, list[Path]] = {}
    for prefix, entries in sorted(groups.items()):
        entries.sort(key=lambda t: (t[0], t[1]))
        result[prefix] = [p for _, _, p in entries]

    return result


def _extract_bus_from_filename(path: Path) -> int | None:
    """Return the M-number (bus override) from a filename, or None."""
    m = _MBUS_TCHUNK_RE.match(path.name)
    if m:
        return int(m.group("bus"))
    return None


# ---------------------------------------------------------------------------
# Timestamp-validated session detection
# ---------------------------------------------------------------------------
# detect_capture_groups() keys purely off filenames, which is unsafe: it assumes
# (a) the M number is a bus, and (b) T numbers run in time order within a prefix.
# Both assumptions are violated by real logs in this repo:
#
#   Vtrux  truklog_M0/M1/M2  start 13:27, 15:27, 16:32 the same day
#                            -> M is a SEPARATE SESSION, not a bus
#   Coda   17_drive_M1_T15 / _M2_T15  start 12 s apart
#                            -> M really is a simultaneous BUS here
#   Coda   17_drive_M0_T12 = 2024-12-11, _M0_T13 = 2024-12-19
#                            -> one M spans unrelated captures 8 days apart
#   Coda   partsdrive_M0_T0 = 2025-07-29, _M0_T1 = 2026-01-25, _M0_T2 = 2025-08-21
#                            -> T ORDER IS NOT TIME ORDER
#
# So neither convention can be inferred from names alone. detect_capture_sessions()
# reads each chunk's start time and groups on evidence instead.

_START_DATE_RE = re.compile(
    r"START DATE AND TIME\s+(\d+):(\d+):(\d+)\s+(\d+):(\d+):(\d+)(?::(\d+))?"
)


def read_chunk_start(path: Path | str) -> float | None:
    """Absolute start time of a capture chunk, as a POSIX-ish epoch float.

    Reads the BUSMASTER ``***START DATE AND TIME DD:MM:YYYY HH:MM:SS:mmm***``
    header (date is day-first in this toolchain).  For candump-style files the
    first frame already carries an absolute epoch, so that is used instead.

    Returns None if neither is available.
    """
    import datetime

    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for _ in range(40):
                line = fh.readline()
                if not line:
                    break
                m = _START_DATE_RE.search(line)
                if m:
                    dd, mo, yy, hh, mi, ss, ms = m.groups()
                    try:
                        dt = datetime.datetime(
                            int(yy), int(mo), int(dd),
                            int(hh), int(mi), int(ss),
                            int((ms or "0").ljust(3, "0")[:3]) * 1000,
                        )
                    except ValueError:
                        return None
                    return dt.timestamp()
                s = line.strip()
                if s.startswith("("):
                    try:
                        return float(s[1:s.index(")")])
                    except (ValueError, IndexError):
                        pass
    except OSError:
        return None
    return None


def detect_capture_sessions(
    paths_or_dir: list[Path | str] | Path | str,
    *,
    split_gap_s: float = 3600.0,
    merge_simultaneous_m: bool = True,
    simultaneous_tol_s: float = 60.0,
) -> dict[str, list[Path]]:
    """Group files into capture sessions using chunk start times, not names.

    Safer replacement for :func:`detect_capture_groups`. Fixes three defects:

    1. **M is not always a bus.** M-groups are kept separate unless their start
       times show they ran concurrently (see ``merge_simultaneous_m``).
    2. **T order is not time order.** Chunks are sorted by actual start time.
    3. **One prefix can span unrelated captures.** A session is split wherever
       consecutive chunks are more than ``split_gap_s`` apart.

    Parameters
    ----------
    paths_or_dir:
        List of file paths, or a directory.
    split_gap_s:
        Wall-clock gap between consecutive chunks that starts a new session.
        Default 1 h. Set to ``float('inf')`` to disable splitting.
    merge_simultaneous_m:
        If True, M-groups whose first chunks start within ``simultaneous_tol_s``
        of each other are treated as concurrent buses of one session and merged.
        If False, every M is always its own session.
    simultaneous_tol_s:
        Tolerance for the concurrency test above.

    Returns
    -------
    dict mapping session key to time-ordered list of Paths. Keys look like
    ``"<prefix>_M0"`` or, when several M's are merged as concurrent buses,
    ``"<prefix>_M0+M1"``; a ``"#2"`` suffix is appended for each extra session
    produced by gap-splitting.

    Chunks with no readable start time are appended after the timed ones, in
    T order, so they are never silently dropped.
    """
    if isinstance(paths_or_dir, (str, Path)):
        p0 = Path(paths_or_dir)
        paths = list(p0.iterdir()) if p0.is_dir() else [p0]
    else:
        paths = [Path(p) for p in paths_or_dir]

    # prefix -> m -> list of (chunk, start_or_None, path)
    by_pm: dict[str, dict[int | None, list[tuple[int, float | None, Path]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for p in paths:
        if not p.is_file():
            continue
        m = _MBUS_TCHUNK_RE.match(p.name)
        if m:
            key, mnum, chunk = m.group("prefix"), int(m.group("bus")), int(m.group("chunk"))
        else:
            m2 = _TCHUNK_RE.match(p.name)
            if not m2:
                continue
            key, mnum, chunk = m2.group("prefix"), None, int(m2.group("chunk"))
        by_pm[key][mnum].append((chunk, read_chunk_start(p), p))

    result: dict[str, list[Path]] = {}
    for prefix, mmap in sorted(by_pm.items()):
        # Decide which M-groups (if any) are concurrent buses of one session.
        clusters: list[list[int | None]]
        firsts: dict[int | None, float | None] = {}
        for mnum, entries in mmap.items():
            timed = [e[1] for e in entries if e[1] is not None]
            firsts[mnum] = min(timed) if timed else None
        if merge_simultaneous_m and len(mmap) > 1:
            clusters = []
            for mnum in sorted(mmap, key=lambda x: (x is None, x)):
                placed = False
                for cl in clusters:
                    ref = firsts[cl[0]]
                    if (ref is not None and firsts[mnum] is not None
                            and abs(firsts[mnum] - ref) <= simultaneous_tol_s):
                        cl.append(mnum)
                        placed = True
                        break
                if not placed:
                    clusters.append([mnum])
        else:
            clusters = [[mnum] for mnum in sorted(mmap, key=lambda x: (x is None, x))]

        for cl in clusters:
            entries: list[tuple[int, float | None, Path]] = []
            for mnum in cl:
                entries.extend(mmap[mnum])
            timed = sorted((e for e in entries if e[1] is not None), key=lambda e: e[1])
            untimed = sorted((e for e in entries if e[1] is None), key=lambda e: e[0])

            label = "+".join("M%s" % ("?" if m is None else m) for m in cl)
            base = prefix if all(m is None for m in cl) else "%s_%s" % (prefix, label)

            # Split on large wall-clock gaps between consecutive chunks.
            runs: list[list[tuple[int, float | None, Path]]] = []
            cur: list[tuple[int, float | None, Path]] = []
            for e in timed:
                if cur and (e[1] - cur[-1][1]) > split_gap_s:
                    runs.append(cur)
                    cur = []
                cur.append(e)
            if cur:
                runs.append(cur)
            if not runs:
                runs = [[]]
            runs[-1].extend(untimed)

            for i, run in enumerate(runs):
                if not run:
                    continue
                key = base if i == 0 else "%s#%d" % (base, i + 1)
                result[key] = [e[2] for e in run]

    return result


def merge_files(paths: list[Path | str]) -> Iterator[CANFrame]:
    """Parse multiple files and yield frames sorted by timestamp.

    Uses absolute timestamps internally so that T-chunk files from the
    same capture chain correctly.  The first frame's timestamp becomes
    t=0 in the output (re-zeroed after merging).

    The bus number on each frame is overridden by the _M{bus} value in
    the filename (if present).

    Parameters
    ----------
    paths:
        Ordered list of log file paths to merge.

    Yields
    ------
    CANFrame, sorted by timestamp across all input files, starting at t=0.
    """
    paths = [Path(p) for p in paths]

    # Build per-file iterators using absolute timestamps so T-chunks chain.
    def _decorate_stream(filepath: Path) -> Iterator[tuple[float, int, CANFrame]]:
        bus_override = _extract_bus_from_filename(filepath)
        idx = 0  # tie-breaker for heap ordering
        for frame in parse_file(filepath, absolute=True):
            if bus_override is not None:
                frame = CANFrame(
                    timestamp=frame.timestamp,
                    arbitration_id=frame.arbitration_id,
                    data=frame.data,
                    bus=bus_override,
                    is_extended=frame.is_extended,
                    dlc=frame.dlc,
                    is_tx=frame.is_tx,
                )
            yield (frame.timestamp, idx, frame)
            idx += 1

    streams = [_decorate_stream(p) for p in paths]

    # Re-zero: subtract the first frame's absolute timestamp so output
    # starts at t=0.
    t_origin = None
    for ts, _idx, frame in heapq.merge(*streams, key=lambda t: (t[0], t[1])):
        if t_origin is None:
            t_origin = ts
        yield CANFrame(
            timestamp=ts - t_origin,
            arbitration_id=frame.arbitration_id,
            data=frame.data,
            bus=frame.bus,
            is_extended=frame.is_extended,
            dlc=frame.dlc,
            is_tx=frame.is_tx,
        )
