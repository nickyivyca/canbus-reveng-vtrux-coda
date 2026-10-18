# canre.parsers Reference

> **Staleness check:** Each section shows a `Source last modified` timestamp. If the `.py` file's mtime is newer than the timestamp shown here, re-read the source before relying on this documentation. Timestamps MUST include both date and time (`YYYY-MM-DD HH:MM:SS`) — a date-only timestamp is invalid and must be corrected before the next session.

## COMMON MISTAKES — Read before writing any script

### sys.path bootstrap (required in every scratchpad)

Scripts in `projects/<vehicle>/notes/artifacts/` are not on the Python path by default — Python adds the script's own directory, not the project root, so `canre` is invisible without this at the top of every scratchpad:

```python
import sys
sys.path.insert(0, ".")
```

All scratchpads are invoked via the Bash tool from the project root, so `"."` reliably resolves to the project root where `canre/` lives. Do **not** use the `Path(__file__).resolve().parent...` form — the required depth varies by script location and is easy to get wrong (a script in `artifacts/` needs five `.parent` calls to reach project root, not four).

### Wrong import names

| Wrong (do NOT use) | Correct |
|--------------------|---------|
| `from canre.parsers.parsers import parse_log` | `from canre.parsers import parse_file` |
| `from canre.parsers.parsers import parse_file` | `from canre.parsers import parse_file` |
| `from canre.parsers import parse_log` | `from canre.parsers import parse_file` |
| `frame.arb_id` | `frame.arbitration_id` |
| `frame.can_id` | `frame.arbitration_id` |
| `frame.id` | `frame.arbitration_id` |
| `frame.msg_id` | `frame.arbitration_id` |
| `frame.channel` | `frame.bus` |

There is no `canre.parsers.parsers` submodule. The function is `parse_file`, not `parse_log`. The ID field is `arbitration_id` and the bus field is `bus`.

## base.py — Core Data Types
*Source last modified: 2026-09-25 17:06:04*

### `CANFrame` dataclass

```python
@dataclass(slots=True)
class CANFrame:
    timestamp: float       # seconds (relative to capture start or absolute)
    arbitration_id: int    # 11-bit or 29-bit CAN ID
    data: bytes            # payload, 0–8 bytes
    bus: int               # channel/bus number (a bus-name str after merge_files(bus_map=...))
    is_extended: bool      # True = 29-bit extended ID
    dlc: int               # data length code
    is_tx: bool = False    # True = transmitted frame
```

All parsers produce `CANFrame` objects. Timestamps are always in **seconds**. The BUSMASTER parser converts from `HH:MM:SS:TTTT` (TTTT = 10 kHz ticks, 0.1 ms resolution).

### `BaseParser` ABC

```python
class BaseParser(ABC):
    @staticmethod
    @abstractmethod
    def detect(lines: list[str]) -> bool: ...

    @abstractmethod
    def parse_file(path, *, absolute: bool = False) -> list[CANFrame]: ...
```

- `detect(lines)` — given the first few lines of a file, returns True if this parser can handle it
- `parse_file(path, absolute=False)` — parse the file, returns list of CANFrame. When `absolute=True`, timestamps are not zeroed to the first frame (needed for stitching T-chunk files that share a timeline)

---

## busmaster.py — BUSMASTER `.log` Parser
*Source last modified: 2026-09-27 16:40:16*

**Changed 2026-09-26 — midnight rollover was measured against the wrong frame.**
The check was `rel_time - t_origin < -1.0`, i.e. against the **first frame in the
file**, adding a day to anything more than a second earlier. Captures are not always
written in timestamp order — the Android logger emits a few seconds of frames out of
order at the start of a chunk — so a benign 4-second backwards write became a 24-hour
jump. **36 of 1069 Coda captures** parsed to a span of `-1.0..86399.0 s` against headers
only minutes long (`coda_20260508_191742_T0`: 6-minute header, 24-hour parsed span);
1 of 2031 Vtrux captures. The comparison is now against the **previous** frame with a
12-hour threshold (`_ROLLOVER_BACKSTEP`), since a real rollover steps back by nearly a
full day while an out-of-order write steps back by seconds. Verified: the 36 captures
now parse to their true length, and 0 of 33 laptop time-of-day captures regressed.

Two consequences beyond the timestamps. This was the real cause of the
"T0 spans 24 h with later chunks nested inside it" overlap that
`influx_sync.overlapping_files()` was added to work around on 2026-08-26 — the note in
`tools/tools.md` attributing that to the Android logger is wrong. And it manufactured
phantom multi-module dropout events in gap-based analysis.

**Changed 2026-09-27 — `_DATA_RE` could not match a negative timestamp component,
so it was discarding data lines.** The Android logger stamps a frame received before
the file's origin with negative components (`00:00:-2:-3130`, `00:-1:-26:-150`), which
the pattern rejected, and `parse_file` dropped the line with no warning and no counter.
Across 3,674 files and 2.379 bn data lines, **4,827,795 lines (0.203 %) in 1,715 files**
were being lost; the worst capture lost 447,123 lines, 44 % of itself, all from its start.
The groups are now `-?\d{1,2}` and `-?\d{1,4}`, since `%02d`/`%04d` widen rather than
truncate a negative. `_parse_timestamp` needed no change — summing the signed components
reproduces the offset exactly (round-tripped 4,010 values against a reimplementation of
the logger's Kotlin formatter, 0 mismatches). The hour field stays at two digits: the one
corpus line that exceeds it is `50224:01:46:2870`, which is corruption.

**Frames can carry a negative timestamp, and that is correct.** The first frame *in file
order* is still t=0 under `absolute=False`, so a frame stamped before the origin keeps
its true earlier time. The pre-origin block reaches **-7.0 s**, and clock-step-repaired
captures reach **-186 s** — the earlier "observed down to about -4 s" was one file. Do
not clamp or filter negatives.

**A second, separate defect is repaired in the logs, not here.** In 55 captures the
phone's wall clock stepped backwards mid-file by 8–216 s, leaving two blocks whose stamped
ranges overlap. It is independent of the dropped lines — several rewinding captures drop
none — so the regex fix does not touch it. Those files were repaired on disk, with the
originals kept in a `pre-clockstep-repair/` folder in each log root. See
`projects/coda/notes/android-log-timestamp-defects.md`.

Parser for BUSMASTER CAN log files (v3.x). This is the primary log format for the project and the first parser tried during auto-detection.

### `BusmasterParser` class

Inherits from `BaseParser`.

#### `detect(lines: list[str]) -> bool` (static)

Returns `True` if any sample line matches `***BUSMASTER` or `***PROTOCOL CAN***` (case-insensitive).

#### `parse_file(path, *, absolute: bool = False) -> Iterator[CANFrame]`

Streams through a BUSMASTER log, yielding one `CANFrame` per data line. Skips header/metadata lines (those starting with `***`).

**Timestamp handling:**
- Frame timestamps in the file are **session-relative** (reset to 0 at logging start), in `HH:MM:SS:TTTT` format where TTTT = 10 kHz ticks (0.1 ms, NOT milliseconds).
- Converted to seconds via: `H*3600 + M*60 + S + TTTT*0.0001`.
- **absolute=False** (default): first frame's timestamp becomes t=0; all others are relative to it. Midnight rollover is detected against the **previous** frame, not the first: a step back of more than `_ROLLOVER_BACKSTEP` (12 h) adds a day. Smaller backward steps are out-of-order writes and are left alone, so they yield slightly negative timestamps — see the 2026-09-26 note above.
- **absolute=True**: each frame's session-relative time is offset by the wall-clock `HH:MM:SS` from the file's `***START DATE AND TIME DD:MM:YYYY HH:MM:SS:TTT***` header (sub-second field ignored to avoid ms/ticks ambiguity). This gives every T-chunk a unique, non-overlapping time base so `merge_files()` can chain them correctly. Files without the header fall back to session-relative time (epoch=0).

**HEX/DEC mode:**
- Tracks `***HEX***` and `***DEC***` markers mid-file. Default assumption is HEX mode.
- Data byte tokens are clipped to `DLC` count (extra trailing tokens ignored).

**Data line fields:** timestamp, direction (Tx/Rx), channel, arb ID (with 0x), frame type (`s`=standard, `x`=extended), DLC, data bytes.

**Caveat:** Session start/stop markers do **not** reset the time origin. Multiple sessions in one file produce monotonically increasing timestamps from the first data frame.

---

## candump.py — candump / SocketCAN Parser
*Source last modified: 2026-02-16 00:41:49*

Parser for `candump` (SocketCAN) log format. Each line has the form `(epoch.usec) canX ID#DATA`.

### `CandumpParser` class

Inherits from `BaseParser`.

#### `detect(lines: list[str]) -> bool` (static)

Returns `True` if at least 2 non-comment lines match the candump pattern `(timestamp) interface ID#data`.

#### `parse_file(path, *, absolute: bool = False) -> Iterator[CANFrame]`

**Timestamp handling:** Unix epoch seconds with microsecond precision, made relative to the first frame. The `absolute` parameter is accepted but **not currently implemented** — timestamps are always relative.

**Bus number:** Extracted from trailing digits of the interface name (e.g. `can0` → bus 0, `vcan1` → bus 1). Defaults to bus 0.

**Extended ID:** Inferred from value (ID > `0x7FF`). No explicit flag in candump format.

**Data payload:** Contiguous hex after `#` (no spaces). `##` indicates CAN FD with a flags byte prefix.

**Caveat:** `is_tx` is always `False` — candump does not distinguish Tx from Rx.

---

## peak_trc.py — PEAK PCAN TRC Parser
*Source last modified: 2026-02-16 00:42:14*

Parser for PEAK PCAN Trace (`.trc`) log files. Supports both version 1.1 and version 2.0 formats, auto-detecting from the `;$FILEVERSION=` header.

### `PeakTrcParser` class

Inherits from `BaseParser`.

#### `detect(lines: list[str]) -> bool` (static)

Returns `True` if any line matches `;$FILEVERSION=X.X`. Fallback: returns `True` if the sample has both `;`-prefixed headers and numbered data lines.

#### `parse_file(path, *, absolute: bool = False) -> Iterator[CANFrame]`

Selects v1.1 vs v2.0 regex based on header. Falls back to the other version's regex if primary fails.

**Timestamps:** Relative to capture start. The `absolute` parameter is accepted but not implemented.

**Extended ID:** Inferred from value (ID > `0x7FF`).

**Bus number:** Always 0 — TRC files do not indicate channel.

**Error handling:** Malformed lines are silently skipped.

---

## savvycan.py — SavvyCAN CSV Parser
*Source last modified: 2026-02-16 00:42:22*

Parser for SavvyCAN CSV log files. Handles both header-row format (`Time Stamp,ID,Extended,Bus,LEN,D1,...,D8`) and a headerless positional variant.

### `SavvyCANParser` class

Inherits from `BaseParser`.

#### `detect(lines: list[str]) -> bool` (static)

Two heuristics (either sufficient):
1. **Header detection:** Line containing "time", "id", and a comma with ≥3 of the tokens `{"time", "stamp", "id", "bus", "len", "d1"}`.
2. **Data-only detection:** At least 3 lines match CSV data pattern (starts with float, comma, hex ID, comma).

#### `parse_file(path, *, absolute: bool = False) -> Iterator[CANFrame]`

Auto-detects header vs headerless by checking if the first non-empty line starts with a digit.

**Header variant:** Normalises header tokens (lowercase, no spaces), maps to column indices. Required columns: `time`, `id`, `len`. Optional: `extended`, `bus`.

**Headerless variant:** Assumed column order: timestamp, id, [extended], [bus], len, d1, d2, ... Uses heuristics to detect whether column 2 is an extended flag or bus number.

**Integer parsing:** All integer fields accept both `0x`-prefixed hex and plain decimal.

**Extended ID:** From `Extended` column if present, or inferred from ID > `0x7FF`.

**Caveat:** `is_tx` is always `False` — SavvyCAN CSV has no direction column.

---

## vector_asc.py — Vector CANalyzer ASC Parser
*Source last modified: 2026-03-05 13:35:56*

Parser for Vector CANalyzer / CANdb++ `.asc` log files. Used by CODACAN and other
Vector-based loggers.

### `VectorAscParser` class

Inherits from `BaseParser`.

#### `detect(lines: list[str]) -> bool` (static)

Returns `True` if any sample line starts with `base hex`, `base dec`, `date `, or
`no internal events` (case-insensitive). These are characteristic ASC header lines.

#### `parse_file(path, *, absolute: bool = False) -> Iterator[CANFrame]`

**Format:** `<float_ts> <channel> <id_hex> <dir> d <dlc> [byte ...]`

Example: `3824324055.7855 1      215                Rx  d 7 00 00 00 57 00 50 8F`

**Timestamp handling:** Absolute large float (epoch-like). Made relative to first frame
unless `absolute=True`.

**Channel:** Integer (typically 1-based). Stored directly as `bus` field.

**ID:** Hex without `0x` prefix.

**Extended ID:** Inferred from value > `0x7FF` (no explicit flag in standard ASC).

**Skipped lines:** Header lines (`date`, `base`, `no internal events`, `//`, `begin`,
`end`) and any line not matching the data line pattern. Remote frames (`r`) and error
frames are silently skipped.

---

## autodetect.py — Format Auto-Detection & Convenience Entry Point
*Source last modified: 2026-02-16 00:38:08*

Automatic format detection and the primary public entry point for all log parsing.

### `detect_format(path) -> BaseParser`

Reads the first ~20 non-empty lines and tries each parser's `detect()` in priority order:
1. `BusmasterParser` (tried first — highly distinctive `***BUSMASTER` header)
2. `CandumpParser`
3. `PeakTrcParser`
4. `SavvyCANParser`

Returns the first matching parser instance. Raises `ValueError` if none match.

### `parse_file(path, *, absolute: bool = False) -> Iterator[CANFrame]`

One-step convenience: detects format, then delegates to the matched parser's `parse_file`.

```python
from canre.parsers.autodetect import parse_file

for frame in parse_file("capture.log"):
    print(frame)
```

This is the intended entry point — callers never need to choose a parser manually.
