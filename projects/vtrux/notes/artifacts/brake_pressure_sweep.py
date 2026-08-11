#!/usr/bin/env python3
"""
Brake booster pressure signal search.
Correlates all bytes/pairs on all buses against two brake references:
  REF1 = PT bus 0x592 B4 (brake pedal position, raw uint8)
  REF2 = Vehicle bus 0x2F9 B5 (EBCM brake applied pressure, raw uint8)

Usage:
  py -3.12 projects/vtrux/notes/artifacts/brake_pressure_sweep.py
"""
import sys
import math
import struct
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from canre.parsers import parse_file

LOG = "projects/vtrux/logs/movingaroundindriveway.log"

# Bus numbers from survey: Bus1=OBD, Bus2=Vehicle, Bus3=PT
PT_BUS = 3
GM_BUS = 2

# References
REF_PT_ID   = 0x592   # B4 = brake pedal
REF_GM_ID   = 0x2F9   # B5 = EBCM brake pressure

MIN_FRAMES = 50       # skip IDs with too few frames
ABS_R_THRESH = 0.40   # report anything above this

def pearson(x, y):
    n = len(x)
    if n < MIN_FRAMES:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sx = math.sqrt(max(1e-12, sum((a - mx)**2 for a in x)))
    sy = math.sqrt(max(1e-12, sum((b - my)**2 for b in y)))
    return sxy / (sx * sy)

def nearest_val(ref_times, cand_ts_vals, max_dt=0.15):
    """For each ref timestamp, find nearest candidate value within max_dt."""
    if not cand_ts_vals or not ref_times:
        return [], []
    ci = 0
    rv, cv = [], []
    for rt in ref_times:
        while ci < len(cand_ts_vals)-1 and \
              abs(cand_ts_vals[ci+1][0] - rt) < abs(cand_ts_vals[ci][0] - rt):
            ci += 1
        if abs(cand_ts_vals[ci][0] - rt) <= max_dt:
            rv.append(rt)
            cv.append(cand_ts_vals[ci][1])
    return rv, cv

# ---- collect data ----
print(f"Parsing {LOG} ...")
# Store per-bus, per-ID: list of (timestamp, bytes)
bus_data = defaultdict(lambda: defaultdict(list))
for frame in parse_file(LOG):
    bus_data[frame.bus][frame.arbitration_id].append(
        (frame.timestamp, frame.data)
    )
print("Parse complete.")

def build_ref(bus, can_id, byte_idx):
    """Build (times, values) reference from single byte."""
    entries = bus_data[bus].get(can_id, [])
    times = [t for t, d in entries if len(d) > byte_idx]
    vals  = [d[byte_idx] for t, d in entries if len(d) > byte_idx]
    return times, vals

# Build references
ref_pt_times, ref_pt_vals = build_ref(PT_BUS, REF_PT_ID, 4)   # 0x592 B4
ref_gm_times, ref_gm_vals = build_ref(GM_BUS, REF_GM_ID, 5)   # 0x2F9 B5

print(f"REF1 (PT 0x592 B4): {len(ref_pt_times)} frames, range {min(ref_pt_vals)}-{max(ref_pt_vals)}")
print(f"REF2 (GM 0x2F9 B5): {len(ref_gm_times)} frames, range {min(ref_gm_vals)}-{max(ref_gm_vals)}")
print()

def sweep_bus(bus_num, ref_times, ref_vals, ref_label):
    results = []
    for can_id, entries in sorted(bus_data[bus_num].items()):
        if can_id == (REF_PT_ID if bus_num == PT_BUS else REF_GM_ID):
            continue  # skip self
        if len(entries) < MIN_FRAMES:
            continue
        dlc = max(len(d) for _, d in entries)

        # Per-byte correlation
        for bi in range(dlc):
            cand_ts_vals = [(t, d[bi]) for t, d in entries if len(d) > bi]
            if len(set(v for _, v in cand_ts_vals)) < 3:
                continue  # constant byte
            _, cv = nearest_val(ref_times, cand_ts_vals)
            if len(cv) < MIN_FRAMES:
                continue
            # align lengths
            n = min(len(ref_vals), len(cv))
            r = pearson(ref_vals[:n], cv[:n])
            if abs(r) >= ABS_R_THRESH:
                results.append((abs(r), r, f"0x{can_id:03X} B{bi}", min(v for _,v in cand_ts_vals), max(v for _,v in cand_ts_vals)))

        # LE16 pairs
        for bi in range(dlc-1):
            cand_ts_vals = [(t, d[bi] | (d[bi+1]<<8)) for t, d in entries if len(d) > bi+1]
            if len(set(v for _, v in cand_ts_vals)) < 10:
                continue
            _, cv = nearest_val(ref_times, cand_ts_vals)
            if len(cv) < MIN_FRAMES:
                continue
            n = min(len(ref_vals), len(cv))
            r = pearson(ref_vals[:n], cv[:n])
            if abs(r) >= ABS_R_THRESH:
                results.append((abs(r), r, f"0x{can_id:03X} B{bi}-{bi+1} LE16", min(v for _,v in cand_ts_vals), max(v for _,v in cand_ts_vals)))

        # BE16 pairs
        for bi in range(dlc-1):
            cand_ts_vals = [(t, (d[bi]<<8) | d[bi+1]) for t, d in entries if len(d) > bi+1]
            if len(set(v for _, v in cand_ts_vals)) < 10:
                continue
            _, cv = nearest_val(ref_times, cand_ts_vals)
            if len(cv) < MIN_FRAMES:
                continue
            n = min(len(ref_vals), len(cv))
            r = pearson(ref_vals[:n], cv[:n])
            if abs(r) >= ABS_R_THRESH:
                results.append((abs(r), r, f"0x{can_id:03X} B{bi}-{bi+1} BE16", min(v for _,v in cand_ts_vals), max(v for _,v in cand_ts_vals)))

    results.sort(reverse=True)
    print(f"=== Bus {bus_num} vs {ref_label} (|r| >= {ABS_R_THRESH}) ===")
    if not results:
        print("  No correlators found above threshold.")
    for absr, r, label, mn, mx in results[:40]:
        print(f"  r={r:+.4f}  {label}  range={mn}-{mx}")
    print()

# Sweep PT bus vs REF1 (brake pedal)
sweep_bus(PT_BUS, ref_pt_times, ref_pt_vals, "PT 0x592 B4 (brake pedal)")

# Sweep Vehicle bus vs REF1 (brake pedal)
sweep_bus(GM_BUS, ref_pt_times, ref_pt_vals, "PT 0x592 B4 (brake pedal)")

# Sweep PT bus vs REF2 (EBCM pressure)
sweep_bus(PT_BUS, ref_gm_times, ref_gm_vals, "GM 0x2F9 B5 (EBCM pressure)")

# Also show what 0x2F9 B5 looks like to confirm it's active
print("=== 0x2F9 B5 (EBCM Brake Pressure) stats ===")
vals_2f9 = ref_gm_vals
print(f"  Frames: {len(vals_2f9)}, min={min(vals_2f9)}, max={max(vals_2f9)}, mean={sum(vals_2f9)/len(vals_2f9):.1f}")
nonzero = [v for v in vals_2f9 if v > 0]
print(f"  Non-zero frames: {len(nonzero)} ({100*len(nonzero)/len(vals_2f9):.1f}%)")
print(f"  When non-zero: min={min(nonzero) if nonzero else 0}, max={max(nonzero) if nonzero else 0}")
