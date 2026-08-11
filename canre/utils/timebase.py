"""Resolve the absolute instant of a BUSMASTER log's FIRST FRAME.

`BusmasterParser.parse_file()` re-bases every file so its first data frame is
`t=0`, so a caller never sees the file's raw time base. What a caller needs is
therefore the true instant of that first frame -- which is not simply the
header time, because the header states when *logging started*, not when the
first frame arrived.

Two loggers write these files differently:

    Android logger (CANLogs/), coda_20260505_192535_T0..T3
      T0  hdr 19:25:35  first 00:00:00  last 00:04:59   <- resets every chunk
      T1  hdr 19:30:35  first 00:00:00  last 00:05:00

    Laptop BUSMASTER, debuglog_M1_T8..T10
      T8  hdr 12:07:43  first 11:04:39  last 12:12:43   <- wall clock, header time WRONG
      T9  hdr 12:12:43  first 12:12:43  last 12:17:43   <- wall clock, header exact

RELATIVE  -- raw timestamps count from the logging-start marker, so the header
             supplies the base and `first_T` is the real pre-roll gap.
             `vtruxinterlocktest2.log` has header 22:03:23.980 and first data
             line `00:00:23:2276`: its first frame is 23.2 s after the header.
             279 relative files have a gap of a second or more, up to ~6.5 min.
WALLCLOCK -- raw timestamps are a time of day, so only the header's DATE is
             trusted and a wrong header TIME becomes recoverable. 324 of 3,156
             files in the corpus.

Both reduce to `base + first_T`; only the base differs.

BUSMASTER does NOT wrap the hour at midnight -- `charge_M0_T52.log` literally
contains `24:01:29:4480` -- so a day rollover needs no special handling. It
falls out of the `floor(first_T / 86400)` term below.

Classification is per SESSION, never per file. A single file can be
undecidable: `debuglog_M1_T8`'s own header disagrees with its own data, and it
is only resolvable because its last timestamp meets `T9`'s first exactly.
Sessions are grouped with `detect_capture_sessions()` rather than by filename.

Typical use::

    from canre.utils.timebase import TimebaseIndex
    idx = TimebaseIndex()
    anchor_ns = idx.anchor_ns(path, tz)          # integer nanoseconds
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from canre.utils.merge import detect_capture_sessions

__all__ = ["TimebaseIndex", "classify_session", "read_data_bounds",
           "read_header_datetime", "WALLCLOCK", "RELATIVE"]

WALLCLOCK = "wallclock"
RELATIVE = "relative"

NS_PER_S = 1_000_000_000
SECONDS_PER_DAY = 86400

_HEADER_RE = re.compile(
    r'START DATE AND TIME\s+(\d{1,2}):(\d{1,2}):(\d{4})\s+'
    r'(\d{1,2}):(\d{1,2}):(\d{1,2}):(\d+)')
_DATA_RE = re.compile(r'^(\d+):(\d+):(\d+):(\d+)\s+(?:Rx|Tx)\s')

# A chunk whose first frame is this close to zero is counted from the chunk's
# own start, not from a time of day.
_RESET_TOL_S = 60.0
# How far a chunk's first frame may sit from its header's time of day and still
# count as agreeing. Generous because the logging-start marker can precede the
# first frame by minutes (coda_dlcm_flash5: 878 s of pre-roll).
_TOD_MATCH_TOL_S = 300.0
# Chunk N's last frame meeting chunk N+1's first frame.
_CONTINUITY_TOL_S = 60.0


def read_header_datetime(path: Path | str) -> datetime | None:
    """Naive datetime from ***START DATE AND TIME DD:MM:YYYY HH:MM:SS:mmm***.

    The header's sub-second field is **milliseconds**, unlike the data lines,
    whose trailing field is 10 kHz ticks (0.1 ms). Measured across 1,062
    headers the value never exceeds 998, while data-line values reach 9999 --
    so the two fields genuinely use different units despite looking alike.
    `canre.utils.merge.read_chunk_start` has always read it as milliseconds and
    is correct.
    """
    path = Path(path)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for _ in range(64):
                line = fh.readline()
                if not line:
                    break
                m = _HEADER_RE.search(line)
                if m:
                    d, mo, y, h, mi, s, tk = (int(x) for x in m.groups())
                    try:
                        # Milliseconds -> exact integer microseconds;
                        # timedelta(seconds=tk*1e-3) would round.
                        return datetime(y, mo, d, h, mi, s,
                                        microsecond=(tk % 1000) * 1000)
                    except ValueError:
                        return None
    except OSError:
        pass
    return None


def read_data_bounds(path: Path | str, tail_bytes: int = 65536):
    """(first_T, last_T) in seconds for a BUSMASTER file, or None.

    Reads the head for the first data line and seeks to the tail for the last,
    so cost is independent of file size.
    """
    path = Path(path)
    first = last = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for _ in range(4000):
                line = fh.readline()
                if not line:
                    break
                if line[:1] == "*":
                    continue
                m = _DATA_RE.match(line.strip())
                if m:
                    h, mi, s, tk = (int(x) for x in m.groups())
                    first = h * 3600 + mi * 60 + s + tk * 1e-4
                    break
        if first is None:
            return None
        size = path.stat().st_size
        with open(path, "rb") as fb:
            fb.seek(max(0, size - tail_bytes))
            chunk = fb.read().decode("utf-8", errors="replace")
        for line in reversed(chunk.splitlines()):
            m = _DATA_RE.match(line.strip())
            if m:
                h, mi, s, tk = (int(x) for x in m.groups())
                last = h * 3600 + mi * 60 + s + tk * 1e-4
                break
    except OSError:
        return None
    return (first, last if last is not None else first)


def classify_session(paths) -> str:
    """WALLCLOCK or RELATIVE for one capture session.

    Evidence, in order of strength:

    1. **Chunks reset.** Every chunk starting within `_RESET_TOL_S` of zero is
       the Android logger writing per-chunk offsets -> RELATIVE. This is the
       cleanest discriminator, because a wall-clock chunk can only start near
       zero if it began within a minute of midnight.
    2. **Header agreement.** A chunk whose first frame lands near its header's
       time of day (compared mod 86400, so a >24 h session still matches) is
       evidence of wall clock. A majority decides.
    3. **Continuity.** Chunk N's last frame meeting chunk N+1's first means the
       chunks share one running clock rather than each restarting. Combined
       with a single agreeing header this carries a session whose other headers
       are unreliable -- the `debuglog_M1_T8` case.

    Falls back to RELATIVE, which is the pre-existing behaviour, so an
    unrecognised layout is left exactly as it was rather than newly displaced.
    """
    info = []
    for p in paths:
        hdr = read_header_datetime(p)
        bounds = read_data_bounds(p)
        if bounds is None:
            continue
        info.append((p, hdr, bounds[0], bounds[1]))
    if not info:
        return RELATIVE

    if all(first < _RESET_TOL_S for _p, _h, first, _l in info):
        return RELATIVE

    matches = 0
    checked = 0
    for _p, hdr, first, _last in info:
        if hdr is None:
            continue
        checked += 1
        hdr_tod = hdr.hour * 3600 + hdr.minute * 60 + hdr.second + hdr.microsecond / 1e6
        delta = abs((first % SECONDS_PER_DAY) - hdr_tod)
        delta = min(delta, SECONDS_PER_DAY - delta)   # wrap-around distance
        if delta <= _TOD_MATCH_TOL_S:
            matches += 1
    if checked and matches * 2 >= checked:
        return WALLCLOCK

    ordered = sorted(info, key=lambda r: r[2])
    continuous = len(ordered) > 1 and all(
        abs(ordered[i + 1][2] - ordered[i][3]) <= _CONTINUITY_TOL_S
        for i in range(len(ordered) - 1))
    if continuous and matches:
        return WALLCLOCK

    return RELATIVE


class TimebaseIndex:
    """Per-directory session classification, cached.

    Sessions are discovered over a file's whole directory rather than over
    whatever subset the caller passed, so uploading a single chunk still gets
    the verdict its siblings imply. Only headers and two lines per file are
    read, so the scan is cheap even for the 1,869-file Android folders.
    """

    def __init__(self):
        self._by_dir: dict[Path, dict[Path, str]] = {}

    def kind(self, path: Path | str) -> str:
        path = Path(path).resolve()
        table = self._by_dir.get(path.parent)
        if table is None:
            table = self._scan_dir(path.parent)
            self._by_dir[path.parent] = table
        return table.get(path, RELATIVE)

    @staticmethod
    def _scan_dir(folder: Path) -> dict[Path, str]:
        files = [p for p in folder.iterdir()
                 if p.is_file() and p.suffix.lower() in {".log", ".asc", ".txt"}]
        if not files:
            return {}
        try:
            sessions = detect_capture_sessions(files)
        except Exception:
            sessions = {p.name: [p] for p in files}
        out: dict[Path, str] = {}
        for _key, members in sessions.items():
            verdict = classify_session(members)
            for m in members:
                out[Path(m).resolve()] = verdict
        return out

    def anchor_ns(self, path: Path | str, tz=timezone.utc) -> int | None:
        """Integer-nanosecond epoch of the file's FIRST FRAME.

        `BusmasterParser.parse_file()` re-bases every file so its first data
        frame is t=0, which erases the raw time base before any caller sees it.
        So the anchor a caller needs is not "what the timestamps count from" in
        the file, it is the absolute instant of the first frame.

        Both kinds are `base + first_T`; only the base differs.

        RELATIVE  -> base is the header instant, because the raw timestamps
                     count from the logging-start marker. `first_T` is then the
                     real gap between "start logging" and the first frame, and
                     it is often not zero: `vtruxinterlocktest2.log` has header
                     22:03:23.980 and first data line `00:00:23:2276`, so its
                     first frame is 23.2 s later than the header. 279 relative
                     files in the corpus have a gap of a second or more, up to
                     ~6.5 min.
        WALLCLOCK -> base is midnight of the header's date, stepped back by
                     floor(first_T / 86400) days (a session past midnight
                     started the previous day). Here the DATA carries the true
                     time of day, so only the header's DATE is trusted -- which
                     is what fixes files whose header TIME is wrong
                     (debuglog_M1_T8 claims 12:07:43 for data starting
                     11:04:39).

        Returns None when there is no usable header, leaving the caller on its
        existing filename/mtime fallbacks.
        """
        path = Path(path)
        hdr = read_header_datetime(path)
        if hdr is None:
            return None
        bounds = read_data_bounds(path)
        if bounds is None:
            return None
        first_T = bounds[0]

        if self.kind(path) == RELATIVE:
            # Whole seconds via int(timestamp()) then microseconds added as an
            # integer: timestamp() on a sub-second datetime returns a float
            # around 1.7e9 whose mantissa cannot hold nanoseconds.
            whole = hdr.replace(microsecond=0, tzinfo=tz)
            base_ns = int(whole.timestamp()) * NS_PER_S + hdr.microsecond * 1000
        else:
            days = int(first_T // SECONDS_PER_DAY)
            midnight = datetime(hdr.year, hdr.month, hdr.day) - timedelta(days=days)
            base_ns = int(midnight.replace(tzinfo=tz).timestamp()) * NS_PER_S

        return base_ns + round(first_T * NS_PER_S)
