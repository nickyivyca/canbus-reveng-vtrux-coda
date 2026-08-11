#!/usr/bin/env python3
"""
Detailed timeseries view of top PT bus brake candidates aligned with brake events.
Focus: 0x390 (all bytes), 0x053 (all bytes), 0x479, looking for pressure-like shape.
"""
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from canre.parsers import parse_file

LOG    = "projects/vtrux/logs/movingaroundindriveway.log"
PT_BUS = 3
GM_BUS = 2

bus_data = defaultdict(lambda: defaultdict(list))
for frame in parse_file(LOG):
    bus_data[frame.bus][frame.arbitration_id].append(
        (frame.timestamp, bytes(frame.data))
    )

def nearest_at(ref_t, src, max_dt=0.25):
    if not src: return None
    best = min(src, key=lambda x: abs(x[0]-ref_t))
    return best[1] if abs(best[0]-ref_t) <= max_dt else None

def all_ts(bus, can_id):
    return sorted(bus_data[bus].get(can_id, []))

pedal_ts = all_ts(PT_BUS, 0x592)
pedal_ts_b4 = [(t, d[4]) for t,d in pedal_ts if len(d)>4]

ts_390  = all_ts(PT_BUS, 0x390)
ts_053  = all_ts(PT_BUS, 0x053)
ts_479  = all_ts(PT_BUS, 0x479)
ts_2f9  = all_ts(GM_BUS, 0x2F9)   # EBCM pressure reference (B5)

# Print 0x390 full bytes aligned with pedal + EBCM
print("=== 0x390 full frame vs brake pedal + EBCM pressure ===")
print(f"{'t':>7}  {'Pedal':>5}  {'EBCM':>5}  " + "  ".join(f"{'B'+str(i):>4}" for i in range(8)))
print("-" * 70)
for t, d in ts_390:
    pedal = nearest_at(t, pedal_ts_b4)
    ebcm  = nearest_at(t, [(tt, dd[5]) for tt,dd in ts_2f9 if len(dd)>5])
    pedal_s = f"{pedal:5}" if pedal is not None else "    -"
    ebcm_s  = f"{ebcm:5}"  if ebcm  is not None else "    -"
    print(f"{t:7.2f}  {pedal_s}  {ebcm_s}  " + "  ".join(f"{b:4}" for b in d))

print()
print("=== 0x053 full frame vs brake pedal ===")
print(f"{'t':>7}  {'Pedal':>5}  " + "  ".join(f"{'B'+str(i):>4}" for i in range(6)))
print("-" * 55)
for t, d in ts_053:
    pedal = nearest_at(t, pedal_ts_b4)
    pedal_s = f"{pedal:5}" if pedal is not None else "    -"
    print(f"{t:7.2f}  {pedal_s}  " + "  ".join(f"{b:4}" for b in d))

print()
print("=== 0x479 full frame vs brake pedal ===")
print(f"{'t':>7}  {'Pedal':>5}  " + "  ".join(f"{'B'+str(i):>4}" for i in range(4)))
print("-" * 40)
for t, d in ts_479:
    pedal = nearest_at(t, pedal_ts_b4)
    pedal_s = f"{pedal:5}" if pedal is not None else "    -"
    print(f"{t:7.2f}  {pedal_s}  " + "  ".join(f"{b:4}" for b in d[:4]))
