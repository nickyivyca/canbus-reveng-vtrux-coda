"""Phase 6: trace candidate battery-cooling / high-SoC signals across the whole
2026-07-14 session to find first-activation and correlate with the evening charge.

Candidates surfaced by the early-vs-late clean diff (both windows plugged in,
GM bus asleep):
  0x505 B0 : 0 (early charge) -> 150 (late charge)   <- strongest "turned on" byte
  0x506 B0 : 15 -> 47
  0x508    : present ONLY in late window
  0x410 bcm_cpwr_cmd : 1-bit cooling-power command (from cache)

Reads raw bytes for 0x505/0x506/0x507/0x508; reports per-byte transition
timeline (coalesced) so we can see exactly when each first steps and whether it
tracks SoC / the evening charge rather than firing every charge.
"""
import sys
sys.path.insert(0, ".")

import os
import subprocess
from datetime import datetime, timedelta

from battery_fan_signature import (chunk_files, parse_header_time, decode_line,
                                    load_410, fmt)

TARGET = {0x505, 0x506, 0x507, 0x508}


def trace():
    files = chunk_files()
    t0 = None
    series = {aid: {} for aid in TARGET}   # aid -> {byte_index -> list[(t, val)]}
    present = {aid: [] for aid in TARGET}  # aid -> list[t] (coalesced ranges later)
    for path in files:
        base = parse_header_time(path)
        if base is None:
            continue
        pat = " 0x(505|506|507|508) "
        out = subprocess.run(["grep", "-hE", pat, path],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            dec = decode_line(line, base)
            if dec is None:
                continue
            t, arb, data = dec
            if arb not in TARGET:
                continue
            if t0 is None:
                t0 = t
            present[arb].append(t)
            for bi, bv in enumerate(data):
                series[arb].setdefault(bi, []).append((t, bv))
    return t0, series, present


def coalesce_presence(times, gap=120):
    if not times:
        return []
    times = sorted(times)
    segs = [[times[0], times[0]]]
    for t in times[1:]:
        if (t - segs[-1][1]).total_seconds() > gap:
            segs.append([t, t])
        else:
            segs[-1][1] = t
    return segs


def transitions(pts, min_dwell=10):
    """Coalesced value transitions: emit when value changes and holds >=min_dwell."""
    out = []
    prev = None
    for t, v in pts:
        if v != prev:
            out.append((t, v))
            prev = v
    return out


if __name__ == "__main__":
    t0, series, present = trace()
    print(f"session t0 = {t0}")
    for aid in sorted(TARGET):
        segs = coalesce_presence(present[aid])
        print(f"\n=== {hex(aid)} presence ({len(present[aid])} frames) ===")
        for a, b in segs:
            print(f"  {fmt(a,t0)} -> {fmt(b,t0)}  ({(b-a).total_seconds()/60:.1f}m)")
        for bi in sorted(series[aid]):
            trs = transitions(series[aid][bi])
            vals = set(v for _, v in series[aid][bi])
            if len(vals) <= 1:
                continue
            if len(trs) > 60:
                print(f"  {hex(aid)} B{bi}: {len(vals)} vals, {len(trs)} transitions (noisy)"
                      f" range {min(vals)}..{max(vals)}")
                continue
            print(f"  {hex(aid)} B{bi} transitions ({len(vals)} vals):")
            for t, v in trs:
                print(f"      {fmt(t,t0)}  = {v}")

    print("\n=== 0x410 bcm_cpwr_cmd transitions (from cache) ===")
    rows = load_410()
    prev = None
    for t, ibat, soc, cool, plug, chgc, cpwr in rows:
        if cpwr is None:
            continue
        if cpwr != prev:
            print(f"  {fmt(t,t0)}  cpwr_cmd -> {cpwr}  soc={soc} ibat={ibat:.0f}")
            prev = cpwr
