"""Deep per-ID analysis: byte histograms, bit toggle rates, entropy, byte-pair stats."""
from __future__ import annotations

import math
from collections import Counter
from typing import Iterator

from canre.parsers.base import CANFrame


def analyze_id(
    frames: Iterator[CANFrame],
    target_id: int,
    bus_filter: int | None = None,
) -> dict:
    """Deep-dive analysis for a single arbitration ID.

    Parameters
    ----------
    frames:
        Iterator of CANFrame objects.
    target_id:
        The arbitration ID to analyse.
    bus_filter:
        If set, only consider frames on this bus.

    Returns
    -------
    dict with structure::

        {
            "id": int,
            "id_hex": str,
            "frame_count": int,
            "first_seen": float,
            "last_seen": float,
            "frequency": float | None,
            "byte_stats": {
                "0": {"histogram": {val: count}, "min": int, "max": int,
                       "mean": float, "std_dev": float, "entropy": float,
                       "unique_count": int},
                ...
            },
            "bit_stats": {
                "0": {"toggle_rate": float, "stuck_0": int, "stuck_1": int},
                ...  # bit positions 0-63
            },
            "byte_pairs": {
                "0-1": {"min": int, "max": int, "unique_count": int},
                ...
            },
            "sample_frames": [repr strings of first 10 frames],
        }
    """
    # ---- Accumulators ----
    byte_histograms: dict[int, Counter] = {}  # pos -> Counter(val -> count)
    byte_sums: dict[int, float] = {}
    byte_sum_sq: dict[int, float] = {}

    # Bit-level: previous 64-bit payload and counters.
    prev_bits: int | None = None
    bit_toggle_count: list[int] = [0] * 64
    bit_stuck_0: list[int] = [0] * 64
    bit_stuck_1: list[int] = [0] * 64

    # Byte-pair tracking (adjacent bytes, big-endian 16-bit).
    pair_stats: dict[str, dict] = {}

    sample_frames: list[str] = []
    frame_count = 0
    first_seen: float | None = None
    last_seen: float | None = None
    observed_dlc = 0

    for frame in frames:
        if frame.arbitration_id != target_id:
            continue
        if bus_filter is not None and frame.bus != bus_filter:
            continue

        frame_count += 1
        ts = frame.timestamp

        if first_seen is None or ts < first_seen:
            first_seen = ts
        if last_seen is None or ts > last_seen:
            last_seen = ts

        if len(sample_frames) < 10:
            sample_frames.append(repr(frame))

        dlc = min(frame.dlc, len(frame.data))
        if dlc > observed_dlc:
            observed_dlc = dlc

        # ---- Byte-level stats ----
        for i in range(dlc):
            val = frame.data[i]
            if i not in byte_histograms:
                byte_histograms[i] = Counter()
                byte_sums[i] = 0.0
                byte_sum_sq[i] = 0.0
            byte_histograms[i][val] += 1
            byte_sums[i] += val
            byte_sum_sq[i] += val * val

        # ---- Byte-pair stats (adjacent bytes, big-endian) ----
        for i in range(dlc - 1):
            pair_val = (frame.data[i] << 8) | frame.data[i + 1]
            key = f"{i}-{i + 1}"
            ps = pair_stats.get(key)
            if ps is None:
                pair_stats[key] = {
                    "min": pair_val,
                    "max": pair_val,
                    "uniques": {pair_val},
                }
            else:
                if pair_val < ps["min"]:
                    ps["min"] = pair_val
                if pair_val > ps["max"]:
                    ps["max"] = pair_val
                if len(ps["uniques"]) <= 65536:
                    ps["uniques"].add(pair_val)

        # ---- Bit-level stats ----
        # Pack data into a 64-bit int (MSB = bit 63, data[0] bit 7).
        bits = 0
        for i in range(dlc):
            bits |= frame.data[i] << (8 * (7 - i))

        for b in range(64):
            bit_val = (bits >> (63 - b)) & 1
            if bit_val == 0:
                bit_stuck_0[b] += 1
            else:
                bit_stuck_1[b] += 1

            if prev_bits is not None:
                prev_val = (prev_bits >> (63 - b)) & 1
                if bit_val != prev_val:
                    bit_toggle_count[b] += 1

        prev_bits = bits

    # ---- Build output ----
    if frame_count == 0:
        return {
            "id": target_id,
            "id_hex": f"0x{target_id:03X}",
            "frame_count": 0,
            "first_seen": None,
            "last_seen": None,
            "frequency": None,
            "byte_stats": {},
            "bit_stats": {},
            "byte_pairs": {},
            "sample_frames": [],
        }

    span = (last_seen - first_seen) if first_seen is not None and last_seen is not None else 0.0
    frequency = frame_count / span if span > 0 and frame_count > 1 else None

    # Byte stats with entropy.
    byte_stats_out: dict[str, dict] = {}
    for pos in sorted(byte_histograms):
        hist = byte_histograms[pos]
        total = sum(hist.values())
        mean = byte_sums[pos] / total
        variance = (byte_sum_sq[pos] / total) - (mean * mean)
        std_dev = math.sqrt(max(variance, 0.0))

        # Shannon entropy (bits).
        entropy = 0.0
        for cnt in hist.values():
            p = cnt / total
            if p > 0:
                entropy -= p * math.log2(p)

        vals = list(hist.keys())
        byte_stats_out[str(pos)] = {
            "histogram": dict(hist),
            "min": min(vals),
            "max": max(vals),
            "mean": round(mean, 2),
            "std_dev": round(std_dev, 2),
            "entropy": round(entropy, 4),
            "unique_count": len(vals),
        }

    # Bit stats.
    bit_stats_out: dict[str, dict] = {}
    transitions_possible = max(frame_count - 1, 1)
    for b in range(64):
        toggle_rate = bit_toggle_count[b] / transitions_possible if transitions_possible > 0 else 0.0
        bit_stats_out[str(b)] = {
            "toggle_rate": round(toggle_rate, 4),
            "stuck_0": bit_stuck_0[b],
            "stuck_1": bit_stuck_1[b],
        }

    # Byte-pair output.
    byte_pairs_out: dict[str, dict] = {}
    for key in sorted(pair_stats):
        ps = pair_stats[key]
        byte_pairs_out[key] = {
            "min": ps["min"],
            "max": ps["max"],
            "unique_count": len(ps["uniques"]),
        }

    return {
        "id": target_id,
        "id_hex": f"0x{target_id:03X}",
        "frame_count": frame_count,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "frequency": frequency,
        "byte_stats": byte_stats_out,
        "bit_stats": bit_stats_out,
        "byte_pairs": byte_pairs_out,
        "sample_frames": sample_frames,
    }


def format_bitstats(results: dict) -> str:
    """Pretty-print deep ID analysis results."""
    lines: list[str] = []

    lines.append(f"Analysis for ID {results['id_hex']}")
    lines.append(f"  Frames: {results['frame_count']:,}")
    if results["first_seen"] is not None:
        lines.append(f"  Time span: {results['first_seen']:.4f} - {results['last_seen']:.4f}s")
    if results["frequency"] is not None:
        lines.append(f"  Frequency: {results['frequency']:.1f} Hz")
    lines.append("")

    # ---- Byte statistics table ----
    byte_stats = results.get("byte_stats", {})
    if byte_stats:
        lines.append("Byte Statistics:")
        header = f"  {'Pos':>3s}  {'Min':>4s}  {'Max':>4s}  {'Mean':>6s}  {'StdDev':>6s}  {'Entropy':>7s}  {'Uniq':>5s}"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for pos in sorted(byte_stats, key=int):
            bs = byte_stats[pos]
            lines.append(
                f"  {pos:>3s}  {bs['min']:>4d}  {bs['max']:>4d}  "
                f"{bs['mean']:>6.1f}  {bs['std_dev']:>6.2f}  "
                f"{bs['entropy']:>7.3f}  {bs['unique_count']:>5d}"
            )
        lines.append("")

    # ---- Byte-pair statistics ----
    byte_pairs = results.get("byte_pairs", {})
    if byte_pairs:
        lines.append("Byte-Pair Statistics (big-endian 16-bit):")
        header = f"  {'Pair':>5s}  {'Min':>6s}  {'Max':>6s}  {'Uniq':>6s}"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for key in sorted(byte_pairs):
            bp = byte_pairs[key]
            lines.append(
                f"  {key:>5s}  {bp['min']:>6d}  {bp['max']:>6d}  {bp['unique_count']:>6d}"
            )
        lines.append("")

    # ---- Bit toggle rates (show only active bits) ----
    bit_stats = results.get("bit_stats", {})
    if bit_stats:
        lines.append("Bit Toggle Rates (active bits only, bit 0 = MSB of byte 0):")
        header = f"  {'Bit':>3s}  {'Byte.Bit':>8s}  {'Toggle':>7s}  {'0-count':>8s}  {'1-count':>8s}"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for b in range(64):
            bs = bit_stats.get(str(b), {})
            toggle = bs.get("toggle_rate", 0.0)
            s0 = bs.get("stuck_0", 0)
            s1 = bs.get("stuck_1", 0)
            # Only show bits that actually toggle.
            if s0 > 0 and s1 > 0:
                byte_pos = b // 8
                bit_pos = 7 - (b % 8)
                lines.append(
                    f"  {b:>3d}  {byte_pos:>3d}.{bit_pos:<4d}  {toggle:>7.3f}  {s0:>8d}  {s1:>8d}"
                )
        lines.append("")

    # ---- Sample frames ----
    samples = results.get("sample_frames", [])
    if samples:
        lines.append(f"Sample Frames (first {len(samples)}):")
        for s in samples:
            lines.append(f"  {s}")
        lines.append("")

    return "\n".join(lines)
