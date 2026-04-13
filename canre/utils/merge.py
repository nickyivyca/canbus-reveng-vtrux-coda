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
