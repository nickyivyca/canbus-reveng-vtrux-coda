#!/usr/bin/env python3
"""Correlate OBD RPM timeseries against 0x63C CAN candidate byte pairs.

Both input CSVs must have columns: timestamp, value
(matching the format from extract_timeseries.py and extract_obd_rpm.py)

Usage:
    python correlate_rpm.py <obd_rpm.csv> <candidate1.csv> [<candidate2.csv> ...]

Outputs a ranked table of Pearson r, linear scale (RPM/count), and offset.
"""
import csv
import math
import sys
from pathlib import Path


def load_csv(path):
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((float(row["timestamp"]), float(row["value"])))
    rows.sort(key=lambda x: x[0])
    return rows


def interpolate(series, t):
    """Linear interpolation of sorted (time, value) list at time t."""
    if not series:
        return None
    if t <= series[0][0]:
        return series[0][1]
    if t >= series[-1][0]:
        return series[-1][1]
    lo, hi = 0, len(series) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if series[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    t0, v0 = series[lo]
    t1, v1 = series[hi]
    if t1 == t0:
        return v0
    return v0 + (v1 - v0) * (t - t0) / (t1 - t0)


def nearest_gap(series, t):
    """Return the time gap to the nearest sample in series."""
    lo, hi = 0, len(series) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if series[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    return min(abs(series[lo][0] - t), abs(series[hi][0] - t))


def pearson_and_fit(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return 0.0, 0.0, my
    r = sxy / math.sqrt(sxx * syy)
    slope = sxy / sxx          # RPM per raw count
    intercept = my - slope * mx
    return r, slope, intercept


def correlate(obd_series, cand_series, label, max_gap=0.15):
    xs, ys = [], []
    for t_obd, rpm in obd_series:
        gap = nearest_gap(cand_series, t_obd)
        if gap > max_gap:
            continue
        raw = interpolate(cand_series, t_obd)
        if raw is None:
            continue
        xs.append(raw)
        ys.append(rpm)
    r, slope, intercept = pearson_and_fit(xs, ys)
    rpm_min = min(ys) if ys else 0
    rpm_max = max(ys) if ys else 0
    raw_min = min(xs) if xs else 0
    raw_max = max(xs) if xs else 0
    return {
        "label": label,
        "r": r,
        "slope": slope,
        "intercept": intercept,
        "n": len(xs),
        "rpm_range": (rpm_min, rpm_max),
        "raw_range": (raw_min, raw_max),
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: correlate_rpm.py <obd_rpm.csv> <candidate.csv> [...]")
        sys.exit(1)

    obd_path = sys.argv[1]
    cand_paths = sys.argv[2:]

    obd = load_csv(obd_path)
    rpm_vals = [r for _, r in obd]
    print(f"OBD RPM: {len(obd)} samples")
    print(f"  range: {min(rpm_vals):.0f} – {max(rpm_vals):.0f} RPM")
    print(f"  time:  {obd[0][0]:.1f}s – {obd[-1][0]:.1f}s")
    print()

    results = []
    for cp in cand_paths:
        cand = load_csv(cp)
        label = Path(cp).stem
        res = correlate(obd, cand, label)
        results.append(res)

    results.sort(key=lambda x: abs(x["r"]), reverse=True)

    print(f"{'Candidate':<35} {'r':>8}  {'slope(RPM/cnt)':>14}  {'offset':>10}  {'n':>6}")
    print("-" * 80)
    for res in results:
        print(
            f"{res['label']:<35} {res['r']:>8.4f}  {res['slope']:>14.4f}  "
            f"{res['intercept']:>10.2f}  {res['n']:>6}"
        )
        print(
            f"  raw range: {res['raw_range'][0]:.0f}–{res['raw_range'][1]:.0f}  "
            f"rpm range: {res['rpm_range'][0]:.0f}–{res['rpm_range'][1]:.0f}"
        )
    print()

    if results:
        best = results[0]
        print(f"Best candidate: {best['label']}")
        print(f"  r = {best['r']:.4f}")
        print(f"  RPM = {best['slope']:.6f} * raw_value + {best['intercept']:.2f}")
        if best["slope"] != 0:
            zero_rpm_raw = -best["intercept"] / best["slope"]
            print(f"  raw value at 0 RPM ~= {zero_rpm_raw:.0f}  (0x{int(zero_rpm_raw):04X})")


if __name__ == "__main__":
    main()
