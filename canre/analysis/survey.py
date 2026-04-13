"""Full bus survey -- the most important analysis module.

Streams through all frames and accumulates per-(bus, arbitration_id) statistics
without storing raw frames, making it suitable for multi-GB captures.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from canre.parsers.base import CANFrame

# Cap on how many unique byte values we individually track per position.
_UNIQUE_CAP = 256


def run_survey(
    frames: Iterator[CANFrame],
    bus_filter: int | None = None,
) -> dict:
    """Run a full bus survey over a frame stream.

    Parameters
    ----------
    frames:
        Iterator of CANFrame objects (streaming -- only iterated once).
    bus_filter:
        If set, only consider frames on this bus number.

    Returns
    -------
    dict with structure::

        {
            "ids": {
                "<bus>:<hex_id>": {
                    "bus": int,
                    "arbitration_id": int,
                    "id_hex": str,
                    "count": int,
                    "first_seen": float,
                    "last_seen": float,
                    "frequency": float | None,
                    "dlc": list[int],          # sorted unique DLCs
                    "is_extended": bool,
                    "bytes": {                  # keyed by str(position)
                        "0": {"min": int, "max": int, "unique_count": int},
                        ...
                    }
                },
                ...
            },
            "total_frames": int,
            "duration": float,
        }
    """
    # Accumulators keyed by (bus, arb_id).
    stats: dict[tuple[int, int], dict] = {}
    total_frames = 0
    global_first: float | None = None
    global_last: float | None = None

    for frame in frames:
        if bus_filter is not None and frame.bus != bus_filter:
            continue

        total_frames += 1
        ts = frame.timestamp

        if global_first is None or ts < global_first:
            global_first = ts
        if global_last is None or ts > global_last:
            global_last = ts

        key = (frame.bus, frame.arbitration_id)
        entry = stats.get(key)

        if entry is None:
            # Initialise a new accumulator.
            byte_stats: dict[int, dict] = {}
            for i in range(min(frame.dlc, len(frame.data))):
                val = frame.data[i]
                byte_stats[i] = {
                    "min": val,
                    "max": val,
                    "uniques": {val},
                    "unique_count": 1,
                }

            entry = {
                "bus": frame.bus,
                "arbitration_id": frame.arbitration_id,
                "count": 1,
                "first_seen": ts,
                "last_seen": ts,
                "dlc_set": {frame.dlc},
                "is_extended": frame.is_extended,
                "bytes": byte_stats,
            }
            stats[key] = entry
        else:
            entry["count"] += 1
            if ts < entry["first_seen"]:
                entry["first_seen"] = ts
            if ts > entry["last_seen"]:
                entry["last_seen"] = ts
            entry["dlc_set"].add(frame.dlc)

            for i in range(min(frame.dlc, len(frame.data))):
                val = frame.data[i]
                bs = entry["bytes"].get(i)
                if bs is None:
                    entry["bytes"][i] = {
                        "min": val,
                        "max": val,
                        "uniques": {val},
                        "unique_count": 1,
                    }
                else:
                    if val < bs["min"]:
                        bs["min"] = val
                    if val > bs["max"]:
                        bs["max"] = val
                    if bs["uniques"] is not None:
                        bs["uniques"].add(val)
                        bs["unique_count"] = len(bs["uniques"])
                        if len(bs["uniques"]) > _UNIQUE_CAP:
                            # Stop tracking individual values.
                            bs["uniques"] = None
                    else:
                        # Already exceeded cap; just keep count estimate.
                        # We can't know the true count without storing all
                        # values, so unique_count stays at _UNIQUE_CAP+.
                        bs["unique_count"] = _UNIQUE_CAP + 1

    # ---- Build output dict ----
    ids_out: dict[str, dict] = {}
    for (bus, arb_id), entry in stats.items():
        id_hex = (
            f"0x{arb_id:03X}" if not entry["is_extended"] else f"0x{arb_id:08X}"
        )
        label = f"{bus}:{id_hex}"

        span = entry["last_seen"] - entry["first_seen"]
        frequency = entry["count"] / span if span > 0 and entry["count"] > 1 else None

        byte_info: dict[str, dict] = {}
        for pos in sorted(entry["bytes"]):
            bs = entry["bytes"][pos]
            byte_info[str(pos)] = {
                "min": bs["min"],
                "max": bs["max"],
                "unique_count": bs["unique_count"],
            }

        ids_out[label] = {
            "bus": bus,
            "arbitration_id": arb_id,
            "id_hex": id_hex,
            "count": entry["count"],
            "first_seen": entry["first_seen"],
            "last_seen": entry["last_seen"],
            "frequency": frequency,
            "dlc": sorted(entry["dlc_set"]),
            "is_extended": entry["is_extended"],
            "bytes": byte_info,
        }

    duration = (global_last - global_first) if global_first is not None and global_last is not None else 0.0

    return {
        "ids": ids_out,
        "total_frames": total_frames,
        "duration": duration,
    }


def format_survey(results: dict) -> str:
    """Pretty-print survey results as a formatted table string.

    Output is grouped by bus, sorted by ID within each bus.
    Columns: ID | Count | Freq(Hz) | DLC | Ext | B0 | B1 | ... | B7
    Byte columns show "min-max" if varying, or a constant hex value.
    """
    ids_data = results.get("ids", {})
    if not ids_data:
        return "(no frames captured)\n"

    # Group entries by bus.
    by_bus: dict[int, list[dict]] = {}
    for entry in ids_data.values():
        bus = entry["bus"]
        by_bus.setdefault(bus, []).append(entry)

    lines: list[str] = []
    lines.append(
        f"Total frames: {results['total_frames']:,}  "
        f"Duration: {results['duration']:.2f}s  "
        f"Unique IDs: {len(ids_data)}"
    )
    lines.append("")

    for bus in sorted(by_bus):
        entries = sorted(by_bus[bus], key=lambda e: e["arbitration_id"])
        lines.append(f"=== Bus {bus} ({len(entries)} IDs) ===")

        # Header
        header = f"{'ID':>12s}  {'Count':>8s}  {'Freq':>8s}  {'DLC':>5s}  {'Ext':>3s}"
        for b in range(8):
            header += f"  {'B'+str(b):>7s}"
        lines.append(header)
        lines.append("-" * len(header))

        for e in entries:
            freq_str = f"{e['frequency']:.1f}" if e["frequency"] is not None else "-"
            dlc_str = (
                str(e["dlc"][0])
                if len(e["dlc"]) == 1
                else ",".join(str(d) for d in e["dlc"])
            )
            ext_str = "X" if e["is_extended"] else ""

            row = f"{e['id_hex']:>12s}  {e['count']:>8,}  {freq_str:>8s}  {dlc_str:>5s}  {ext_str:>3s}"

            byte_info = e.get("bytes", {})
            for b in range(8):
                bs = byte_info.get(str(b))
                if bs is None:
                    row += f"  {'':>7s}"
                elif bs["min"] == bs["max"]:
                    row += f"  {bs['min']:02X}     "
                else:
                    row += f"  {bs['min']:02X}-{bs['max']:02X} "
            lines.append(row)

        lines.append("")

    return "\n".join(lines)


def save_survey_json(results: dict, path: Path | str) -> None:
    """Save survey results to a JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, default=str)
