# canre.parsers Reference


## COMMON MISTAKES — Read before writing any script

| Wrong (do NOT use) | Correct |
|--------------------|---------|
| `from canre.parsers import parse_log` | `from canre.parsers import parse_file` |
| `frame.can_id` | `frame.arbitration_id` |
| `frame.id` | `frame.arbitration_id` |
| `frame.msg_id` | `frame.arbitration_id` |

The function is `parse_file`, not `parse_log`. The ID field is `arbitration_id`, not `can_id`. These are the two most frequent mistakes in generated scripts — double-check every new script before running it.

## base.py — Core Data Types

### `CANFrame` dataclass

```python
@dataclass(slots=True)
class CANFrame:
    timestamp: float       # seconds (relative to capture start or absolute)
    arbitration_id: int    # 11-bit or 29-bit CAN ID
    data: bytes            # payload, 0–8 bytes
    bus: int               # channel/bus number
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
- **absolute=False** (default): first frame's timestamp becomes t=0; all others are relative to it. Midnight rollover handled (adds 86400 s if delta < -1 s).
- **absolute=True**: each frame's session-relative time is offset by the wall-clock `HH:MM:SS` from the file's `***START DATE AND TIME DD:MM:YYYY HH:MM:SS:TTT***` header (sub-second field ignored to avoid ms/ticks ambiguity). This gives every T-chunk a unique, non-overlapping time base so `merge_files()` can chain them correctly. Files without the header fall back to session-relative time (epoch=0).

**HEX/DEC mode:**
- Tracks `***HEX***` and `***DEC***` markers mid-file. Default assumption is HEX mode.
- Data byte tokens are clipped to `DLC` count (extra trailing tokens ignored).

**Data line fields:** timestamp, direction (Tx/Rx), channel, arb ID (with 0x), frame type (`s`=standard, `x`=extended), DLC, data bytes.

**Caveat:** Session start/stop markers do **not** reset the time origin. Multiple sessions in one file produce monotonically increasing timestamps from the first data frame.

---

## candump.py — candump / SocketCAN Parser

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
