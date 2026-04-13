"""Validate DBC files against actual CAN bus traffic."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterator

import cantools

from canre.parsers.base import CANFrame


def validate_dbc(
    dbc_path: str | Path,
    frames: Iterator[CANFrame],
    bus_filter: int | None = None,
) -> dict:
    """Validate a DBC file against actual CAN traffic.

    Returns dict with coverage metrics and per-message decode stats.
    """
    db = cantools.database.load_file(str(dbc_path))

    defined_ids: dict[int, str] = {}
    for msg in db.messages:
        defined_ids[msg.frame_id] = msg.name

    observed: dict[int, int] = defaultdict(int)  # id -> count
    matched_frames = 0
    total_frames = 0
    decode_errors: dict[int, list[str]] = defaultdict(list)
    signal_ranges: dict[int, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"min": None, "max": None, "count": 0}))

    for frame in frames:
        if bus_filter is not None and frame.bus != bus_filter:
            continue
        total_frames += 1
        observed[frame.arbitration_id] += 1

        if frame.arbitration_id in defined_ids:
            matched_frames += 1
            try:
                msg = db.get_message_by_frame_id(frame.arbitration_id)
                decoded = msg.decode(frame.data, decode_choices=False)
                for sig_name, value in decoded.items():
                    if isinstance(value, (int, float)):
                        sr = signal_ranges[frame.arbitration_id][sig_name]
                        sr["count"] += 1
                        if sr["min"] is None or value < sr["min"]:
                            sr["min"] = value
                        if sr["max"] is None or value > sr["max"]:
                            sr["max"] = value
            except Exception as e:
                errors = decode_errors[frame.arbitration_id]
                msg_str = str(e)
                if len(errors) < 5 and msg_str not in errors:
                    errors.append(msg_str)

    observed_ids = set(observed.keys())
    defined_id_set = set(defined_ids.keys())
    matched_ids = observed_ids & defined_id_set

    id_coverage = len(matched_ids) / len(observed_ids) * 100 if observed_ids else 0
    traffic_coverage = matched_frames / total_frames * 100 if total_frames else 0

    return {
        "id_coverage_pct": round(id_coverage, 1),
        "traffic_coverage_pct": round(traffic_coverage, 1),
        "total_frames": total_frames,
        "matched_frames": matched_frames,
        "defined_ids": sorted(defined_id_set),
        "observed_ids": sorted(observed_ids),
        "matched_ids": sorted(matched_ids),
        "unmatched_observed": sorted(observed_ids - defined_id_set),
        "unmatched_defined": sorted(defined_id_set - observed_ids),
        "observed_counts": dict(observed),
        "decode_errors": dict(decode_errors),
        "signal_ranges": {
            aid: dict(sigs) for aid, sigs in signal_ranges.items()
        },
    }


def format_validation(results: dict) -> str:
    """Pretty-print validation results."""
    lines: list[str] = []
    lines.append("=== DBC Validation Report ===\n")
    lines.append(f"Total frames analyzed: {results['total_frames']:,}")
    lines.append(f"ID coverage:      {results['id_coverage_pct']:.1f}% ({len(results['matched_ids'])} of {len(results['observed_ids'])} observed IDs)")
    lines.append(f"Traffic coverage: {results['traffic_coverage_pct']:.1f}% ({results['matched_frames']:,} of {results['total_frames']:,} frames)")

    if results["matched_ids"]:
        lines.append(f"\nMatched IDs ({len(results['matched_ids'])}):")
        for aid in results["matched_ids"]:
            count = results["observed_counts"].get(aid, 0)
            lines.append(f"  0x{aid:X}  ({count:,} frames)")
            if aid in results["signal_ranges"]:
                for sig, rng in results["signal_ranges"][aid].items():
                    lines.append(f"    {sig}: {rng['min']} .. {rng['max']}  ({rng['count']} samples)")
            if aid in results["decode_errors"]:
                for err in results["decode_errors"][aid]:
                    lines.append(f"    ERROR: {err}")

    if results["unmatched_observed"]:
        lines.append(f"\nObserved but not in DBC ({len(results['unmatched_observed'])}):")
        for aid in results["unmatched_observed"]:
            count = results["observed_counts"].get(aid, 0)
            lines.append(f"  0x{aid:X}  ({count:,} frames)")

    if results["unmatched_defined"]:
        lines.append(f"\nIn DBC but not observed ({len(results['unmatched_defined'])}):")
        for aid in results["unmatched_defined"]:
            lines.append(f"  0x{aid:X}")

    return "\n".join(lines)
