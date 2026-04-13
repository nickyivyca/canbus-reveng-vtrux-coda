"""Compare two CAN bus captures to find differences.

Useful for identifying which IDs/bytes change when a specific vehicle
condition is different between the two captures (e.g. engine on vs off,
AC on vs off, different gear, etc.).
"""
from __future__ import annotations

from typing import Iterator

from canre.parsers.base import CANFrame
from canre.analysis.survey import run_survey


def diff_captures(
    frames_a: Iterator[CANFrame],
    frames_b: Iterator[CANFrame],
    bus_filter: int | None = None,
) -> dict:
    """Compare two captures and report differences.

    Parameters
    ----------
    frames_a:
        Iterator of CANFrame objects from capture A.
    frames_b:
        Iterator of CANFrame objects from capture B.
    bus_filter:
        If set, only consider frames on this bus.

    Returns
    -------
    dict with structure::

        {
            "only_a": list[str],         # IDs present only in capture A
            "only_b": list[str],         # IDs present only in capture B
            "shared": {
                "<bus>:<hex_id>": {
                    "id_hex": str,
                    "bus": int,
                    "count_a": int,
                    "count_b": int,
                    "freq_a": float | None,
                    "freq_b": float | None,
                    "freq_diff": float | None,
                    "byte_diffs": {
                        "0": {
                            "min_a": int, "max_a": int,
                            "min_b": int, "max_b": int,
                            "range_changed": bool,
                        },
                        ...
                    }
                },
                ...
            },
            "summary": {
                "total_ids_a": int,
                "total_ids_b": int,
                "shared_ids": int,
                "only_a_count": int,
                "only_b_count": int,
                "ids_with_byte_diffs": int,
                "ids_with_freq_diffs": int,
            },
        }
    """
    survey_a = run_survey(frames_a, bus_filter=bus_filter)
    survey_b = run_survey(frames_b, bus_filter=bus_filter)

    ids_a = set(survey_a["ids"].keys())
    ids_b = set(survey_b["ids"].keys())

    only_a = sorted(ids_a - ids_b)
    only_b = sorted(ids_b - ids_a)
    common = sorted(ids_a & ids_b)

    shared: dict[str, dict] = {}
    ids_with_byte_diffs = 0
    ids_with_freq_diffs = 0
    freq_diff_threshold = 1.0  # Hz

    for label in common:
        ea = survey_a["ids"][label]
        eb = survey_b["ids"][label]

        freq_a = ea.get("frequency")
        freq_b = eb.get("frequency")

        freq_diff: float | None = None
        if freq_a is not None and freq_b is not None:
            freq_diff = freq_b - freq_a
            if abs(freq_diff) > freq_diff_threshold:
                ids_with_freq_diffs += 1

        # Compare byte-level ranges.
        byte_diffs: dict[str, dict] = {}
        all_positions = sorted(
            set(ea.get("bytes", {}).keys()) | set(eb.get("bytes", {}).keys()),
            key=int,
        )
        has_byte_diff = False

        for pos in all_positions:
            ba = ea.get("bytes", {}).get(pos)
            bb = eb.get("bytes", {}).get(pos)

            if ba is None:
                ba = {"min": 0, "max": 0}
            if bb is None:
                bb = {"min": 0, "max": 0}

            range_changed = (ba["min"] != bb["min"]) or (ba["max"] != bb["max"])
            if range_changed:
                has_byte_diff = True

            byte_diffs[pos] = {
                "min_a": ba["min"],
                "max_a": ba["max"],
                "min_b": bb["min"],
                "max_b": bb["max"],
                "range_changed": range_changed,
            }

        if has_byte_diff:
            ids_with_byte_diffs += 1

        shared[label] = {
            "id_hex": ea["id_hex"],
            "bus": ea["bus"],
            "count_a": ea["count"],
            "count_b": eb["count"],
            "freq_a": freq_a,
            "freq_b": freq_b,
            "freq_diff": freq_diff,
            "byte_diffs": byte_diffs,
        }

    return {
        "only_a": only_a,
        "only_b": only_b,
        "shared": shared,
        "summary": {
            "total_ids_a": len(ids_a),
            "total_ids_b": len(ids_b),
            "shared_ids": len(common),
            "only_a_count": len(only_a),
            "only_b_count": len(only_b),
            "ids_with_byte_diffs": ids_with_byte_diffs,
            "ids_with_freq_diffs": ids_with_freq_diffs,
        },
    }


def format_diff(results: dict, ids_only: bool = False) -> str:
    """Pretty-print capture diff results."""
    lines: list[str] = []
    summary = results.get("summary", {})

    lines.append("=== Capture Comparison ===")
    lines.append(
        f"  Capture A: {summary.get('total_ids_a', 0)} IDs  |  "
        f"Capture B: {summary.get('total_ids_b', 0)} IDs"
    )
    lines.append(
        f"  Shared: {summary.get('shared_ids', 0)}  |  "
        f"Only A: {summary.get('only_a_count', 0)}  |  "
        f"Only B: {summary.get('only_b_count', 0)}"
    )
    lines.append(
        f"  IDs with byte-range diffs: {summary.get('ids_with_byte_diffs', 0)}  |  "
        f"IDs with freq diffs: {summary.get('ids_with_freq_diffs', 0)}"
    )
    lines.append("")

    # ---- IDs unique to A ----
    only_a = results.get("only_a", [])
    if only_a:
        lines.append(f"IDs only in Capture A ({len(only_a)}):")
        for label in only_a:
            lines.append(f"  {label}")
        lines.append("")

    # ---- IDs unique to B ----
    only_b = results.get("only_b", [])
    if only_b:
        lines.append(f"IDs only in Capture B ({len(only_b)}):")
        for label in only_b:
            lines.append(f"  {label}")
        lines.append("")

    if ids_only:
        return "\n".join(lines)

    # ---- Shared IDs with differences ----
    shared = results.get("shared", {})
    changed_ids = {
        label: info
        for label, info in shared.items()
        if any(bd["range_changed"] for bd in info.get("byte_diffs", {}).values())
    }

    if changed_ids:
        lines.append(f"Shared IDs with byte-range changes ({len(changed_ids)}):")
        header = (
            f"  {'ID':>12s}  {'Cnt-A':>8s}  {'Cnt-B':>8s}  "
            f"{'Hz-A':>7s}  {'Hz-B':>7s}  Changed Bytes"
        )
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))

        for label in sorted(changed_ids):
            info = changed_ids[label]
            freq_a_str = f"{info['freq_a']:.1f}" if info["freq_a"] is not None else "-"
            freq_b_str = f"{info['freq_b']:.1f}" if info["freq_b"] is not None else "-"

            changed_bytes: list[str] = []
            for pos, bd in sorted(info.get("byte_diffs", {}).items(), key=lambda x: int(x[0])):
                if bd["range_changed"]:
                    changed_bytes.append(
                        f"B{pos}[{bd['min_a']:02X}-{bd['max_a']:02X} -> "
                        f"{bd['min_b']:02X}-{bd['max_b']:02X}]"
                    )

            row = (
                f"  {info['id_hex']:>12s}  {info['count_a']:>8,}  {info['count_b']:>8,}  "
                f"{freq_a_str:>7s}  {freq_b_str:>7s}  {', '.join(changed_bytes)}"
            )
            lines.append(row)

        lines.append("")

    return "\n".join(lines)
