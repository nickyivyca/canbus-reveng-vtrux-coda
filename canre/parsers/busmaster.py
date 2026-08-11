"""Parser for BUSMASTER CAN log files.

BUSMASTER log format (v3.x):
    - Header lines start with ***
    - Data lines: HH:MM:SS:TTTT Tx/Rx Channel 0xID s/x DLC D0 D1 ... D7
    - Timestamp TTTT is 10 kHz ticks (0.1 ms resolution)
    - Type 's' = standard (11-bit), 'x' = extended (29-bit)
    - Supports mid-file session restarts
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from .base import BaseParser, CANFrame

# Matches a BUSMASTER data line (not a header/metadata line).
# Groups: timestamp, tx/rx, channel, id, type, dlc, remaining data bytes
_DATA_RE = re.compile(
    r"^(\d{1,2}:\d{2}:\d{2}:\d{4})\s+"  # HH:MM:SS:TTTT
    r"(Tx|Rx)\s+"                          # direction
    r"(\d+)\s+"                            # channel
    r"(0x[0-9A-Fa-f]+)\s+"                # arbitration ID
    r"([sx])\s+"                           # s=standard, x=extended
    r"(\d+)\s+"                            # DLC
    r"(.*)",                               # data bytes (space-separated hex)
    re.IGNORECASE,
)

_HEADER_RE = re.compile(r"^\*\*\*")
_SESSION_START_RE = re.compile(r"^\*\*\*\[START LOGGING SESSION\]\*\*\*", re.IGNORECASE)
_SESSION_STOP_RE = re.compile(r"^\*\*\*\[STOP LOGGING SESSION\]\*\*\*", re.IGNORECASE)
_HEX_MODE_RE = re.compile(r"^\*\*\*HEX\*\*\*", re.IGNORECASE)
_DEC_MODE_RE = re.compile(r"^\*\*\*DEC\*\*\*", re.IGNORECASE)
# Parses: ***START DATE AND TIME DD:MM:YYYY HH:MM:SS:TTT***
# We use only HH:MM:SS as the wall-clock epoch (sub-second field omitted to
# avoid ambiguity between ms and 10 kHz ticks across log sources).
_START_TIME_RE = re.compile(
    r"^\*\*\*START DATE AND TIME\s+\d{2}:\d{2}:\d{4}\s+"
    r"(?P<time>\d{1,2}:\d{2}:\d{2}):\d+\*\*\*",
    re.IGNORECASE,
)


def _parse_timestamp(ts_str: str) -> float:
    """Convert HH:MM:SS:TTTT to session-relative seconds.

    BUSMASTER timestamps are session-relative (reset to 0 at logging start),
    not wall-clock time.  TTTT is in 10 kHz ticks (0.1 ms per tick).
    """
    parts = ts_str.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    ticks = int(parts[3])
    return hours * 3600.0 + minutes * 60.0 + seconds + ticks * 0.0001


class BusmasterParser(BaseParser):
    """Parser for BUSMASTER CAN log files."""

    @staticmethod
    def detect(lines: list[str]) -> bool:
        """Return True if sample lines look like a BUSMASTER log.

        We look for the characteristic ***BUSMASTER*** or ***PROTOCOL CAN***
        header lines, or the ***HEX***/***DEC*** marker.
        Also matches truncated-header BUSMASTER files that start with
        ***START DATE AND TIME or ***END CHANNEL BAUD RATE***.
        """
        for line in lines:
            stripped = line.strip()
            if re.match(r"^\*\*\*BUSMASTER", stripped, re.IGNORECASE):
                return True
            if re.match(r"^\*\*\*PROTOCOL CAN\*\*\*", stripped, re.IGNORECASE):
                return True
            if re.match(r"^\*\*\*START DATE AND TIME", stripped, re.IGNORECASE):
                return True
            if re.match(r"^\*\*\*END CHANNEL BAUD RATE\*\*\*", stripped, re.IGNORECASE):
                return True
            if _DATA_RE.match(stripped):
                return True
        return False

    @staticmethod
    def scan_ids(path: Path | str) -> tuple[dict[int, set], dict[int, int], float]:
        """Fast scan path for the influx_upload.scan_log() dual-pass.

        Returns ``(channel_ids, channel_counts, last_ts)`` -- the same shape
        scan_log builds via the full parser, but skips work that scan_log
        does not consume:
          * `_parse_timestamp` per line (~36s tottime in the 535MB benchmark
            across both passes) -- only the last line's timestamp is
            converted, since scan_log only uses last_ts as the
            derive_start_epoch mtime fallback.
          * `bytes(int(b,16) for b in tokens)` data-byte decoding (~63s
            tottime) -- not needed for ID-only counting.
          * `CANFrame` dataclass allocation per line.
          * Tx/Rx, frame_type, dlc, is_extended.

        Hex/Dec mode and session-restart markers are honoured by virtue of
        skipping every ``***`` line; mode flips don't matter because we
        never decode data bytes here.

        Other parsers (CandumpParser, PeakTrcParser, SavvyCANParser,
        VectorAscParser) don't override this -- influx_upload.scan_log
        falls back to the full ``parse_file`` for them. That fallback is
        slower but those formats are rare in this project, so correctness
        beats speed.
        """
        path = Path(path)
        channel_ids: dict[int, set] = {}
        channel_counts: dict[int, int] = {}
        last_ts_str = ""
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                if not raw_line or raw_line[0] == "*":
                    continue
                line = raw_line.strip()
                if not line:
                    continue
                m = _DATA_RE.match(line)
                if not m:
                    continue
                last_ts_str = m.group(1)
                channel = int(m.group(3))
                arb_id = int(m.group(4), 16)
                ids = channel_ids.get(channel)
                if ids is None:
                    ids = set()
                    channel_ids[channel] = ids
                    channel_counts[channel] = 0
                ids.add(arb_id)
                channel_counts[channel] += 1

        last_ts = 0.0
        if last_ts_str:
            parts = last_ts_str.split(":")
            last_ts = (int(parts[0]) * 3600 + int(parts[1]) * 60
                       + int(parts[2]) + int(parts[3]) * 0.0001)
        return channel_ids, channel_counts, last_ts

    def parse_file(self, path: Path | str, *, absolute: bool = False) -> Iterator[CANFrame]:
        """Parse a BUSMASTER log file, yielding CANFrame objects.

        By default the first data frame's timestamp becomes t=0 and all
        subsequent timestamps are relative to that origin.

        If *absolute* is True, each frame's session-relative timestamp is
        offset by the wall-clock HH:MM:SS from the file's
        ``***START DATE AND TIME***`` header.  This gives every T-chunk a
        distinct, non-overlapping time base so that merge_files() can chain
        them correctly with heapq.merge.  Files without the header fall back
        to session-relative time (epoch=0), which is the pre-fix behaviour.
        """
        path = Path(path)
        hex_mode = True  # default; toggled by ***HEX*** / ***DEC***
        t_origin: float | None = None
        session_epoch: float = 0.0  # set from ***START DATE AND TIME*** header

        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue

                # ---- Header / metadata lines ----
                if _HEADER_RE.match(line):
                    if _HEX_MODE_RE.match(line):
                        hex_mode = True
                    elif _DEC_MODE_RE.match(line):
                        hex_mode = False
                    elif absolute:
                        m_st = _START_TIME_RE.match(line)
                        if m_st:
                            h, mn, s = (int(x) for x in m_st.group("time").split(":"))
                            session_epoch = h * 3600.0 + mn * 60.0 + s
                    # Session start/stop are noted but don't reset origin
                    continue

                # ---- Data lines ----
                m = _DATA_RE.match(line)
                if not m:
                    continue

                ts_str, direction, channel, arb_id_str, frame_type, dlc_str, data_str = m.groups()

                rel_time = _parse_timestamp(ts_str)

                if absolute:
                    timestamp = session_epoch + rel_time
                else:
                    if t_origin is None:
                        t_origin = rel_time
                    timestamp = rel_time - t_origin
                    # Handle midnight rollover
                    if timestamp < -1.0:
                        timestamp += 86400.0

                is_tx = direction.upper() == "TX"
                bus = int(channel)
                arb_id = int(arb_id_str, 16)
                is_extended = frame_type.lower() == "x"
                dlc = int(dlc_str)

                # Parse data bytes
                data_tokens = data_str.split()
                if hex_mode:
                    data_bytes = bytes(int(b, 16) for b in data_tokens[:dlc])
                else:
                    data_bytes = bytes(int(b) for b in data_tokens[:dlc])

                yield CANFrame(
                    timestamp=timestamp,
                    arbitration_id=arb_id,
                    data=data_bytes,
                    bus=bus,
                    is_extended=is_extended,
                    dlc=dlc,
                    is_tx=is_tx,
                )
