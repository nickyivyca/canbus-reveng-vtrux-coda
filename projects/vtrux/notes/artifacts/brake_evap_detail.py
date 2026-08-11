#!/usr/bin/env python3
"""
Detailed timeseries of brake booster candidates from evap drive log.
Focus: 0x0BE (full frame), 0x0F1 (full frame), 0x651 B4, 0x3F9 B2
Bus assignments for vtruxanotherevaplogpart1.log:
  Bus 1 = Vehicle, Bus 2 = OBD, Bus 3 = PT
"""
import sys, bisect
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from canre.parsers import parse_file

LOG     = "projects/vtrux/logs/vtruxanotherevaplogpart1.log"
PT_BUS  = 3
GM_BUS1 = 1
GM_BUS2 = 2

print("Parsing ...", flush=True)
bus_data = defaultdict(lambda: defaultdict(list))
for frame in parse_file(LOG):
    bus_data[frame.bus][frame.arbitration_id].append(
        (frame.timestamp, bytes(frame.data))
    )
print("Done.", flush=True)

def sorted_ts(bus, can_id):
    return sorted(bus_data[bus].get(can_id, []))

def nearest(ref_t, times, vals, max_dt=0.25):
    if not times: return None
    i = bisect.bisect_left(times, ref_t)
    best_i, best_d = None, max_dt + 1
    for j in [i-1, i]:
        if 0 <= j < len(times):
            d = abs(times[j] - ref_t)
            if d < best_d:
                best_d, best_i = d, j
    return vals[best_i] if best_i is not None and best_d <= max_dt else None

# Reference signals
pedal_raw = sorted_ts(PT_BUS, 0x592)
pedal_ts  = [(t, d[4]) for t,d in pedal_raw if len(d)>4]
ped_times = [x[0] for x in pedal_ts]
ped_vals  = [x[1] for x in pedal_ts]

ebcm_raw  = sorted_ts(GM_BUS1, 0x2F9)
ebcm_ts   = [(t, d[5]) for t,d in ebcm_raw if len(d)>5]
ebcm_times= [x[0] for x in ebcm_ts]
ebcm_vals = [x[1] for x in ebcm_ts]

# Find brake press intervals (pedal >= 30, peak >= 60)
PRESS_THR = 30
MIN_PEAK  = 60
press_intervals = []  # (start_t, peak_t, end_t, peak_v)
i = 0
while i < len(ped_times):
    if ped_vals[i] >= PRESS_THR:
        j = i
        while j < len(ped_times) and ped_vals[j] >= PRESS_THR:
            j += 1
        seg_v = ped_vals[i:j]
        pk = max(seg_v)
        if pk >= MIN_PEAK:
            pki = seg_v.index(pk)
            press_intervals.append((ped_times[i], ped_times[i+pki], ped_times[j-1], pk))
        i = j
    else:
        i += 1

print(f"Brake press intervals: {len(press_intervals)}")

# ----- 0x0BE full frame (Vehicle, Bus1) -----
ts_0be_b1 = sorted_ts(GM_BUS1, 0x0BE)
ts_0be_b2 = sorted_ts(GM_BUS2, 0x0BE)
ts_0be = ts_0be_b1 if len(ts_0be_b1) >= len(ts_0be_b2) else ts_0be_b2
bus_0be = GM_BUS1 if len(ts_0be_b1) >= len(ts_0be_b2) else GM_BUS2
dlc_0be = max((len(d) for _,d in ts_0be), default=0)

print()
print(f"=== 0x0BE full frame (Bus{bus_0be}) vs Pedal + EBCM ===")
print(f"DLC={dlc_0be}, {len(ts_0be)} frames")
print(f"{'t':>8}  {'Pedal':>5}  {'EBCM':>5}  " +
      "  ".join(f"{'B'+str(i):>4}" for i in range(dlc_0be)))
print("-" * (8+5+5+dlc_0be*6+20))
# Print only near brake events (+/- 6 seconds)
shown = set()
for start_t, peak_t, end_t, pk in press_intervals:
    window_start = start_t - 2.0
    window_end   = end_t + 7.0
    for t, d in ts_0be:
        if window_start <= t <= window_end:
            key = round(t, 2)
            if key in shown: continue
            shown.add(key)
            ped = nearest(t, ped_times, ped_vals)
            ebc = nearest(t, ebcm_times, ebcm_vals)
            ps = f"{ped:5}" if ped is not None else "    -"
            es = f"{ebc:5}" if ebc is not None else "    -"
            marker = " <PRESS" if start_t <= t <= end_t else ""
            print(f"{t:8.2f}  {ps}  {es}  " +
                  "  ".join(f"{b:4}" for b in d[:dlc_0be]) + marker)
    print("---")

# ----- 0x0F1 full frame (Vehicle, Bus1) -----
ts_0f1 = sorted_ts(GM_BUS1, 0x0F1)
dlc_0f1 = max((len(d) for _,d in ts_0f1), default=0)

print()
print(f"=== 0x0F1 full frame (Bus{GM_BUS1}) vs Pedal + EBCM ===")
print(f"DLC={dlc_0f1}, {len(ts_0f1)} frames")
print(f"{'t':>8}  {'Pedal':>5}  {'EBCM':>5}  " +
      "  ".join(f"{'B'+str(i):>4}" for i in range(dlc_0f1)))
print("-" * (8+5+5+dlc_0f1*6+20))
shown = set()
for start_t, peak_t, end_t, pk in press_intervals:
    window_start = start_t - 2.0
    window_end   = end_t + 7.0
    for t, d in ts_0f1:
        if window_start <= t <= window_end:
            key = round(t, 2)
            if key in shown: continue
            shown.add(key)
            ped = nearest(t, ped_times, ped_vals)
            ebc = nearest(t, ebcm_times, ebcm_vals)
            ps = f"{ped:5}" if ped is not None else "    -"
            es = f"{ebc:5}" if ebc is not None else "    -"
            marker = " <PRESS" if start_t <= t <= end_t else ""
            print(f"{t:8.2f}  {ps}  {es}  " +
                  "  ".join(f"{b:4}" for b in d[:dlc_0f1]) + marker)
    print("---")

# ----- 0x3F9 B2 (Vehicle, Bus1) -----
ts_3f9 = sorted_ts(GM_BUS1, 0x3F9)
dlc_3f9 = max((len(d) for _,d in ts_3f9), default=0)

print()
print(f"=== 0x3F9 full frame (Bus{GM_BUS1}) vs Pedal ===")
print(f"DLC={dlc_3f9}, {len(ts_3f9)} frames")
print(f"{'t':>8}  {'Pedal':>5}  " +
      "  ".join(f"{'B'+str(i):>4}" for i in range(dlc_3f9)))
print("-" * (8+5+dlc_3f9*6+10))
shown = set()
for start_t, peak_t, end_t, pk in press_intervals[:20]:  # first 20 events only
    window_start = start_t - 2.0
    window_end   = end_t + 7.0
    for t, d in ts_3f9:
        if window_start <= t <= window_end:
            key = round(t, 2)
            if key in shown: continue
            shown.add(key)
            ped = nearest(t, ped_times, ped_vals)
            ps = f"{ped:5}" if ped is not None else "    -"
            marker = " <PRESS" if start_t <= t <= end_t else ""
            print(f"{t:8.2f}  {ps}  " +
                  "  ".join(f"{b:4}" for b in d[:dlc_3f9]) + marker)
    print("---")

# ----- 0x651 B4 (PT Bus, Bus3) -----
ts_651 = sorted_ts(PT_BUS, 0x651)
dlc_651 = max((len(d) for _,d in ts_651), default=0)

print()
print(f"=== 0x651 full frame (PT Bus{PT_BUS}) vs Pedal ===")
print(f"DLC={dlc_651}, {len(ts_651)} frames")
print(f"{'t':>8}  {'Pedal':>5}  " +
      "  ".join(f"{'B'+str(i):>4}" for i in range(dlc_651)))
print("-" * (8+5+dlc_651*6+10))
shown = set()
for start_t, peak_t, end_t, pk in press_intervals[:20]:
    window_start = start_t - 2.0
    window_end   = end_t + 7.0
    for t, d in ts_651:
        if window_start <= t <= window_end:
            key = round(t, 2)
            if key in shown: continue
            shown.add(key)
            ped = nearest(t, ped_times, ped_vals)
            ps = f"{ped:5}" if ped is not None else "    -"
            marker = " <PRESS" if start_t <= t <= end_t else ""
            print(f"{t:8.2f}  {ps}  " +
                  "  ".join(f"{b:4}" for b in d[:dlc_651]) + marker)
    print("---")
