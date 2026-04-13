#!/usr/bin/env python3
"""Scan all CAN buses for signals that are flat before generator start then count down to ~0.

This is the evap canister load signal finder for vtruxevapdrivelog4.log.

Algorithm:
1. Parse the log and identify bus channels using anchor IDs.
2. Find generator start time: first frame on PT bus with ID=0x63C and B6 > 6.
3. For each (bus, ID, byte_pos):
   - Compute std of values in the pre-generator window.
   - If pre_std < 1.5 AND pre_mean > 2 (not already near zero):
     - Compute Pearson r between post-generator values and a linear countdown ramp.
     - Record: bus, ID, byte, pre_mean, post_min, post_mean, r, n_pre, n_post.
4. Sort by r (most negative = best countdown correlation) and print top candidates.

Bus identification anchors:
  PT bus:           0x051 (generator torque, ~100 Hz)
  OBD bus:       0x040-0x044
  Vehicle:    0x1E5, 0x500

Usage:
    python find_evap_countdown.py <log_file> [--output file.txt]
"""
import argparse
import array
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from canre.parsers import parse_file

BUS_LABELS = {}   # bus_number -> label string (set during detection)

# Anchor IDs for bus classification
PT_ANCHORS = {0x051}
GM_OBD_ANCHORS = {0x040, 0x041, 0x042, 0x043, 0x044}
GM_UNF_ANCHORS = {0x1E5, 0x500}


def detect_buses(log_path, max_scan=500_000):
    """Scan up to max_scan frames to identify bus channel numbers."""
    found = {}  # label -> bus_number
    for frame in parse_file(log_path):
        cid = frame.arbitration_id
        b = frame.bus
        if cid in PT_ANCHORS and "PT" not in found:
            found["PT"] = b
        if cid in GM_OBD_ANCHORS and "GM_OBD" not in found:
            found["GM_OBD"] = b
        if cid in GM_UNF_ANCHORS and "GM_UNF" not in found:
            found["GM_UNF"] = b
        if len(found) == 3:
            break
        max_scan -= 1
        if max_scan <= 0:
            break
    return found


def pearson_r(xs, ys):
    """Compute Pearson correlation coefficient between two equal-length sequences."""
    n = len(xs)
    if n < 3:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if denom_x < 1e-9 or denom_y < 1e-9:
        return None
    return num / (denom_x * denom_y)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log", help="Path to BUSMASTER log file (part 1)")
    ap.add_argument("--output", "-o", default=None,
                    help="Write results to this file instead of stdout")
    ap.add_argument("--pre-std-max", type=float, default=1.5,
                    help="Max allowed std in pre-generator window (default: 1.5)")
    ap.add_argument("--pre-mean-min", type=float, default=2.0,
                    help="Min required mean in pre-generator window (default: 2.0)")
    ap.add_argument("--top", type=int, default=30,
                    help="Number of top candidates to report (default: 30)")
    args = ap.parse_args()

    log_path = args.log
    print(f"Detecting bus channels in {log_path}...", file=sys.stderr)
    bus_map = detect_buses(log_path)

    if "PT" not in bus_map:
        print("ERROR: PT bus (0x051) not found. Is this the correct log?", file=sys.stderr)
        sys.exit(1)

    pt_bus = bus_map["PT"]
    gm_obd_bus = bus_map.get("GM_OBD")
    gm_unf_bus = bus_map.get("GM_UNF")

    bus_label = {pt_bus: "PT"}
    if gm_obd_bus is not None:
        bus_label[gm_obd_bus] = "GM_OBD"
    if gm_unf_bus is not None:
        bus_label[gm_unf_bus] = "GM_UNF"

    print(f"  PT bus: {pt_bus}", file=sys.stderr)
    print(f"  OBD bus: {gm_obd_bus}", file=sys.stderr)
    print(f"  Vehicle bus: {gm_unf_bus}", file=sys.stderr)

    # Pass 1: Find generator start time and accumulate pre-gen stats.
    # Pass is streaming; once t_gen_start is found we switch to post-gen accumulation.
    #
    # Pre-gen storage: running stats only (memory efficient)
    #   pre_n[key], pre_sum[key], pre_ss[key]  (sum of squares)
    # Post-gen storage: compact arrays
    #   post_ts[key]: array('d', ...)   -- timestamps
    #   post_val[key]: array('B', ...)  -- byte values

    pre_n = defaultdict(int)
    pre_sum = defaultdict(float)
    pre_ss = defaultdict(float)
    post_ts = defaultdict(lambda: array.array('d'))
    post_val = defaultdict(lambda: array.array('B'))

    t_gen_start = None
    frame_count = 0

    print("Scanning log...", file=sys.stderr)

    for frame in parse_file(log_path):
        ts = frame.timestamp
        bus = frame.bus
        cid = frame.arbitration_id
        data = frame.data
        dlc = frame.dlc

        frame_count += 1
        if frame_count % 1_000_000 == 0:
            elapsed = f"t_gen_start={t_gen_start:.1f}s" if t_gen_start else "gen not started"
            print(f"  {frame_count//1_000_000}M frames... {elapsed}", file=sys.stderr)

        # Detect generator start: PT bus, ID=0x63C, B6 > 6
        if t_gen_start is None and bus == pt_bus and cid == 0x63C and dlc >= 7:
            if data[6] > 6:
                t_gen_start = ts
                print(f"  Generator start detected at t={t_gen_start:.3f}s", file=sys.stderr)

        for byte_pos in range(min(dlc, 8)):
            val = data[byte_pos]
            key = (bus, cid, byte_pos)
            if t_gen_start is None or ts < t_gen_start:
                # Pre-generator window
                pre_n[key] += 1
                pre_sum[key] += val
                pre_ss[key] += val * val
            else:
                # Post-generator window
                post_ts[key].append(ts)
                post_val[key].append(val)

    print(f"Total frames: {frame_count:,}", file=sys.stderr)
    if t_gen_start is None:
        print("ERROR: Generator never started in this log!", file=sys.stderr)
        sys.exit(1)

    t_gen_start_found = t_gen_start

    # Compute candidates: filter by pre_std and pre_mean, then correlate post-gen with ramp.
    print("Computing candidates...", file=sys.stderr)
    candidates = []

    all_keys = set(pre_n.keys()) | set(post_ts.keys())
    for key in all_keys:
        bus, cid, byte_pos = key
        n = pre_n.get(key, 0)
        if n < 10:
            continue  # Not enough pre-gen samples

        s = pre_sum.get(key, 0.0)
        ss = pre_ss.get(key, 0.0)
        pre_mean = s / n
        variance = ss / n - pre_mean * pre_mean
        pre_std = math.sqrt(max(variance, 0.0))

        if pre_std > args.pre_std_max:
            continue  # Too variable before generator starts
        if pre_mean < args.pre_mean_min:
            continue  # Already at/near zero — not a countdown

        post_t = list(post_ts.get(key, array.array('d')))
        post_v = list(post_val.get(key, array.array('B')))
        n_post = len(post_t)
        if n_post < 50:
            continue  # Not enough post-gen data

        post_mean = sum(post_v) / n_post
        post_min = min(post_v)
        post_max = max(post_v)

        # For countdown: values should decrease. Skip if post_max == post_min (flat post too).
        if post_max == post_min:
            continue

        # Build linear ramp reference: t0 to tN → 0 to -1 (countdown direction)
        t0 = post_t[0]
        tN = post_t[-1]
        if tN <= t0:
            continue
        ramp = [-(t - t0) / (tN - t0) for t in post_t]

        r = pearson_r(post_v, ramp)
        if r is None:
            continue

        candidates.append({
            "bus": bus_label.get(bus, f"bus{bus}"),
            "id": cid,
            "byte": byte_pos,
            "pre_mean": pre_mean,
            "pre_std": pre_std,
            "pre_n": n,
            "post_mean": post_mean,
            "post_min": post_min,
            "post_max": post_max,
            "post_n": n_post,
            "r": r,
        })

    # Ramp is 0→-1; a DECREASING signal (countdown) has r > 0 with this ramp.
    # An INCREASING signal has r < 0.
    # Sort by r DESCENDING so the true countdowns (highest positive r) appear first.
    candidates.sort(key=lambda c: c["r"], reverse=True)

    # Build output
    lines = []
    lines.append(f"Evap Countdown Signal Scan")
    lines.append(f"Log: {log_path}")
    lines.append(f"Generator start: t={t_gen_start_found:.3f}s")
    lines.append(f"Pre-gen window: 0 – {t_gen_start_found:.1f}s")
    lines.append(f"Post-gen window: {t_gen_start_found:.1f}s – end")
    lines.append(f"Total candidates checked: {len(all_keys):,}")
    lines.append(f"Candidates passing pre_std < {args.pre_std_max} and pre_mean > {args.pre_mean_min}: {len(candidates)}")
    lines.append("")
    lines.append("=== Top COUNTDOWN candidates (r > 0 = value decreases after generator start) ===")
    lines.append("")
    lines.append(f"{'Bus':<12} {'ID':>8} {'B':>3}  {'pre_mean':>9} {'pre_std':>8} {'post_min':>9} {'post_max':>9} {'r':>8}  {'n_pre':>7} {'n_post':>7}")
    lines.append("-" * 90)

    top_n = args.top
    # Show top countdown candidates (positive r, descending)
    shown = candidates[:top_n]
    for c in shown:
        lines.append(
            f"{c['bus']:<12} {hex(c['id']):>8} {c['byte']:>3}"
            f"  {c['pre_mean']:>9.2f} {c['pre_std']:>8.3f}"
            f"  {c['post_min']:>9.1f} {c['post_max']:>9.1f}"
            f"  {c['r']:>8.4f}"
            f"  {c['pre_n']:>7,} {c['post_n']:>7,}"
        )

    # Also show per-bus top 5 countdown candidates
    lines.append("")
    lines.append("=== Top 5 COUNTDOWN candidates per bus ===")
    for bus_name in ["PT", "GM_OBD", "GM_UNF"]:
        bus_cands = [c for c in candidates if c["bus"] == bus_name and c["r"] > 0]
        lines.append(f"\n{bus_name} (top 5 of {len(bus_cands)} countdown-correlated):")
        if not bus_cands:
            lines.append("  (none — no decreasing signals found)")
            continue
        lines.append(f"  {'ID':>8} {'B':>3}  {'pre_mean':>9} {'pre_std':>8} {'post_min':>9} {'r':>8}")
        for c in bus_cands[:5]:
            lines.append(
                f"  {hex(c['id']):>8} {c['byte']:>3}"
                f"  {c['pre_mean']:>9.2f} {c['pre_std']:>8.3f}"
                f"  {c['post_min']:>9.1f}  {c['r']:>8.4f}"
            )

    lines.append("")
    lines.append("=== Top 10 RAMP-UP candidates (r < 0, for reference) ===")
    ramp_up = [c for c in candidates if c["r"] < 0]
    ramp_up_sorted = sorted(ramp_up, key=lambda c: c["r"])
    for c in ramp_up_sorted[:10]:
        lines.append(
            f"{c['bus']:<12} {hex(c['id']):>8} {c['byte']:>3}"
            f"  {c['pre_mean']:>9.2f} {c['pre_std']:>8.3f}"
            f"  {c['post_min']:>9.1f} {c['post_max']:>9.1f}"
            f"  {c['r']:>8.4f}"
            f"  {c['pre_n']:>7,} {c['post_n']:>7,}"
        )

    output_text = "\n".join(lines) + "\n"

    if args.output:
        Path(args.output).write_text(output_text)
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_text)


if __name__ == "__main__":
    main()
