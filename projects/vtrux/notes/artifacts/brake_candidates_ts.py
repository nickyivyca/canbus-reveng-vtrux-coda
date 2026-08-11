#!/usr/bin/env python3
"""
Print aligned timeseries for brake pressure candidates.
Shows: timestamp, brake pedal (0x592 B4), EBCM pressure (0x2F9 B5),
and top candidate signals, to visually inspect asymmetric recovery.
"""
import sys
import math
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from canre.parsers import parse_file

LOG = "projects/vtrux/logs/movingaroundindriveway.log"
PT_BUS = 3
GM_BUS = 2

# Collect per-bus per-ID timeseries
bus_data = defaultdict(lambda: defaultdict(list))
for frame in parse_file(LOG):
    bus_data[frame.bus][frame.arbitration_id].append(
        (frame.timestamp, bytes(frame.data))
    )

def ts(bus, can_id, *byte_indices):
    """Return (times, values_tuple_per_frame) for given bytes."""
    entries = bus_data[bus].get(can_id, [])
    result = []
    for t, d in entries:
        if all(bi < len(d) for bi in byte_indices):
            result.append((t, tuple(d[bi] for bi in byte_indices)))
    return result

def nearest(ref_t, src_ts, max_dt=0.2):
    """Find nearest value in src_ts for a given ref_t."""
    if not src_ts:
        return None
    best = min(src_ts, key=lambda x: abs(x[0] - ref_t))
    if abs(best[0] - ref_t) <= max_dt:
        return best[1]
    return None

# Build reference tables
pedal_ts   = ts(PT_BUS, 0x592, 4)           # brake pedal B4
ebcm_ts    = ts(GM_BUS, 0x2F9, 5)           # EBCM brake pressure B5
id483_ts   = ts(PT_BUS, 0x483, 0, 1, 2, 3)  # 0x483 B0-B3
id375_ts   = ts(PT_BUS, 0x375, 4)            # 0x375 B4
pump_ts    = ts(PT_BUS, 0x18FF0320, 3, 4)    # PE pump B3-B4

print(f"0x483 frames: {len(id483_ts)}")
print(f"0x375 frames: {len(id375_ts)}")
print(f"PE pump frames: {len(pump_ts)}")
print()

# Show full aligned timeseries at EBCM pressure rate (20 Hz, 2302 frames)
# Downsample to 4 Hz to keep output manageable
print("=== Aligned timeseries (4 Hz decimated) ===")
print(f"{'Time':>7}  {'Pedal':>5}  {'EBCM-P':>6}  {'483-B0':>6}  {'483-B1':>6}  {'375-B4':>6}  {'Pump-B3':>7}")
print("-" * 65)

last_t = -999
for t, (pedal,) in pedal_ts:
    if t - last_t < 0.24:  # ~4 Hz
        continue
    last_t = t
    ebcm = nearest(t, ebcm_ts)
    p483 = nearest(t, id483_ts)
    p375 = nearest(t, id375_ts)
    ppump = nearest(t, pump_ts)
    ebcm_str = f"{ebcm[0]:6}" if ebcm else "     -"
    b0_str   = f"{p483[0]:6}" if p483 else "     -"
    b1_str   = f"{p483[1]:6}" if p483 else "     -"
    p375_str = f"{p375[0]:6}" if p375 else "     -"
    pump_str = f"{ppump[0]:7}" if ppump else "      -"
    print(f"{t:7.2f}  {pedal:5}  {ebcm_str}  {b0_str}  {b1_str}  {p375_str}  {pump_str}")

print()
print("=== 0x483 all bytes (all frames) ===")
print(f"{'Time':>7}  {'B0':>4}  {'B1':>4}  {'B2':>4}  {'B3':>4}  {'B4':>4}  {'B5':>4}  {'B6':>4}  {'B7':>4}  | pedal")
print("-" * 80)
for t, vals in id483_ts:
    ped = nearest(t, pedal_ts)
    ped_str = f"{ped[0]:5}" if ped else "    -"
    ebcm = nearest(t, ebcm_ts)
    ebcm_str = f"{ebcm[0]:5}" if ebcm else "    -"
    all_bytes = ts(PT_BUS, 0x483)
    # Get full frame
    entry = next(((tt, d) for tt, d in bus_data[PT_BUS][0x483] if abs(tt-t) < 0.01), None)
    if entry:
        d = entry[1]
        print(f"{t:7.2f}  " + "  ".join(f"{b:4}" for b in d) + f"  | ped={ped_str} ebcm={ebcm_str}")

print()
print("=== 0x375 all frames (BMS message) ===")
frames_375 = bus_data[PT_BUS].get(0x375, [])
print(f"{'Time':>7}  " + "  ".join(f"{'B'+str(i):>4}" for i in range(8)))
for t, d in frames_375:
    print(f"{t:7.2f}  " + "  ".join(f"{b:4}" for b in d))
