"""Extract signal values over time from CAN bus frames.

Provides utilities to pull a specific byte range from a CAN ID's payload
as a time-series of integer values, supporting both big- and little-endian
byte orders and signed interpretation.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

from canre.parsers.base import CANFrame


def extract_timeseries(
    frames: Iterator[CANFrame],
    target_id: int,
    byte_start: int,
    byte_count: int = 1,
    endian: str = "big",
    signed: bool = False,
    bus_filter: int | None = None,
) -> list[tuple[float, int]]:
    """Extract a multi-byte signal from a CAN ID over time.

    Parameters
    ----------
    frames:
        Iterator of CANFrame objects.
    target_id:
        The arbitration ID to extract from.
    byte_start:
        Starting byte position (0-indexed).
    byte_count:
        Number of bytes to combine (1, 2, 3, or 4).
    endian:
        "big" or "little" byte order for multi-byte values.
    signed:
        If True, interpret the combined value as a signed integer
        (two's complement).
    bus_filter:
        If set, only consider frames on this bus.

    Returns
    -------
    list of (timestamp, value) tuples.
    """
    if endian not in ("big", "little"):
        raise ValueError(f"endian must be 'big' or 'little', got {endian!r}")

    result: list[tuple[float, int]] = []
    byte_end = byte_start + byte_count

    for frame in frames:
        if frame.arbitration_id != target_id:
            continue
        if bus_filter is not None and frame.bus != bus_filter:
            continue

        dlc = min(frame.dlc, len(frame.data))
        if byte_end > dlc:
            continue

        # Extract the relevant bytes.
        raw = frame.data[byte_start:byte_end]

        # Combine according to endianness.
        if endian == "big":
            value = int.from_bytes(raw, byteorder="big", signed=False)
        else:
            value = int.from_bytes(raw, byteorder="little", signed=False)

        # Apply signed interpretation if requested.
        if signed:
            bit_width = byte_count * 8
            if value >= (1 << (bit_width - 1)):
                value -= (1 << bit_width)

        result.append((frame.timestamp, value))

    return result


def save_timeseries_csv(
    data: list[tuple[float, int]],
    path: Path | str,
    header: str = "timestamp,value",
) -> None:
    """Save a time-series to a CSV file.

    Parameters
    ----------
    data:
        List of (timestamp, value) tuples.
    path:
        Output file path.
    header:
        CSV header line.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        # Write header.
        writer.writerow(header.split(","))
        for ts, val in data:
            writer.writerow([f"{ts:.6f}", val])
