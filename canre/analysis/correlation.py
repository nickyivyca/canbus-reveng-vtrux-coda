"""Cross-signal correlation detection across CAN IDs.

Finds byte positions in different CAN IDs that change in sync (high
Pearson correlation), useful for identifying related signals spread
across multiple messages.

Uses only Python stdlib -- no numpy required.
"""
from __future__ import annotations

import math
from typing import Iterator

from canre.parsers.base import CANFrame


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Compute Pearson correlation coefficient between two equal-length series.

    Returns None if either series has zero variance (constant signal).
    """
    n = len(xs)
    if n < 2:
        return None

    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xx = sum(x * x for x in xs)
    sum_yy = sum(y * y for y in ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))

    denom_x = n * sum_xx - sum_x * sum_x
    denom_y = n * sum_yy - sum_y * sum_y

    if denom_x <= 0 or denom_y <= 0:
        return None

    numerator = n * sum_xy - sum_x * sum_y
    denominator = math.sqrt(denom_x * denom_y)

    if denominator == 0:
        return None

    return numerator / denominator


def find_correlations(
    frames: Iterator[CANFrame],
    bus_filter: int | None = None,
    sample_every: int = 10,
    min_samples: int = 50,
    threshold: float = 0.8,
    max_ids: int = 200,
) -> dict:
    """Find byte-level cross-ID correlations in a CAN bus capture.

    To limit memory, only every *sample_every*-th frame per ID is kept.
    Only IDs that accumulate at least *min_samples* samples are considered.
    At most *max_ids* highest-traffic IDs are analysed (to keep the O(n^2)
    pair comparison tractable).

    Parameters
    ----------
    frames:
        Iterator of CANFrame objects.
    bus_filter:
        If set, only consider frames on this bus.
    sample_every:
        Keep every Nth frame per ID to limit memory.
    min_samples:
        Minimum number of samples required for an ID to be included.
    threshold:
        Minimum absolute Pearson correlation to report.
    max_ids:
        Maximum number of IDs to include in pairwise comparison.

    Returns
    -------
    dict with structure::

        {
            "pairs": [
                {
                    "id_a": str,   # hex
                    "byte_a": int,
                    "id_b": str,   # hex
                    "byte_b": int,
                    "correlation": float,
                    "samples": int,
                },
                ...
            ],
            "ids_analyzed": int,
            "threshold": float,
        }
    """
    # ---- Phase 1: Collect sampled time-series per (ID, byte) ----
    # Keyed by arb_id -> {frame_counter, byte_series: {pos: [vals]}}
    id_data: dict[int, dict] = {}

    for frame in frames:
        if bus_filter is not None and frame.bus != bus_filter:
            continue

        aid = frame.arbitration_id
        entry = id_data.get(aid)
        if entry is None:
            entry = {"counter": 0, "series": {}}
            id_data[aid] = entry

        entry["counter"] += 1

        if entry["counter"] % sample_every != 0:
            continue

        dlc = min(frame.dlc, len(frame.data))
        for i in range(dlc):
            series_list = entry["series"].get(i)
            if series_list is None:
                series_list = []
                entry["series"][i] = series_list
            series_list.append(float(frame.data[i]))

    # ---- Phase 2: Filter to IDs with enough samples ----
    qualified: list[tuple[int, dict[int, list[float]]]] = []
    for aid, entry in id_data.items():
        # Check if any byte has enough samples.
        has_enough = any(
            len(vals) >= min_samples for vals in entry["series"].values()
        )
        if has_enough:
            qualified.append((aid, entry["series"]))

    # Sort by total samples descending and cap at max_ids.
    qualified.sort(
        key=lambda t: sum(len(v) for v in t[1].values()), reverse=True
    )
    qualified = qualified[:max_ids]

    # ---- Phase 3: Pairwise correlation ----
    # Build flat list of (id_hex, byte_pos, values).
    signals: list[tuple[str, int, list[float]]] = []
    for aid, series_map in qualified:
        id_hex = f"0x{aid:03X}"
        for pos, vals in sorted(series_map.items()):
            if len(vals) < min_samples:
                continue
            # Skip constant signals (zero variance).
            if min(vals) == max(vals):
                continue
            signals.append((id_hex, pos, vals))

    pairs: list[dict] = []

    for i in range(len(signals)):
        id_a, byte_a, vals_a = signals[i]
        for j in range(i + 1, len(signals)):
            id_b, byte_b, vals_b = signals[j]

            # Only correlate across different IDs.
            if id_a == id_b:
                continue

            # Align series to the same length (truncate the longer one).
            min_len = min(len(vals_a), len(vals_b))
            if min_len < min_samples:
                continue

            r = _pearson(vals_a[:min_len], vals_b[:min_len])
            if r is not None and abs(r) >= threshold:
                pairs.append({
                    "id_a": id_a,
                    "byte_a": byte_a,
                    "id_b": id_b,
                    "byte_b": byte_b,
                    "correlation": round(r, 4),
                    "samples": min_len,
                })

    # Sort by descending absolute correlation.
    pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)

    return {
        "pairs": pairs,
        "ids_analyzed": len(qualified),
        "threshold": threshold,
    }
