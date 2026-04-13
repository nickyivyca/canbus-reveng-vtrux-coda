"""
Verify top motor RPM candidates from find_motor_rpm.py.
Print raw values, scaled values, and compare to motor RPM proxy at key moments.
"""

import re
import numpy as np

LOG_PATH = r"projects/vtrux/logs/movingaroundindriveway.log"

BUSMASTER_RE = re.compile(
    r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+((?:[0-9A-Fa-f]{2}\s*)+)'
)

MOTOR_RATIO = 64.3

def parse_ts(ts_str):
    h, m, s, t = ts_str.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001

# Targets: (msg_id, label, extractor_fn)
# extractor returns a raw value; we'll show it centered at 32768 where applicable
CANDIDATES = [
    (0x5A2,     '0x5A2  B2-3(LE)-32768',   lambda d: ((d[3]<<8)|d[2]) - 32768 if len(d)>=4 else None),
    (0x308,     '0x308  B1-2(LE)',           lambda d: (d[2]<<8)|d[1] if len(d)>=3 else None),
    (0x308,     '0x308  B2-3(BE)-32768',    lambda d: ((d[2]<<8)|d[3]) - 32768 if len(d)>=4 else None),
    (0x6000001, '0x6000001 B6-7(BE)-32768', lambda d: ((d[6]<<8)|d[7]) - 32768 if len(d)>=8 else None),
    (0x594,     '0x594  B0-1(BE)-32768',    lambda d: ((d[0]<<8)|d[1]) - 32768 if len(d)>=2 else None),
    (0x6000002, '0x6000002 B2-3(LE)-32768', lambda d: ((d[3]<<8)|d[2]) - 32768 if len(d)>=4 else None),
]

frames = {cid: [] for cid, _, _ in CANDIDATES}
frames_3e9 = []
frames_1f5 = []
t0 = None

with open(LOG_PATH, 'r', errors='replace') as f:
    for line in f:
        m = BUSMASTER_RE.match(line.strip())
        if not m:
            continue
        ts_str, bus_str, id_str, dlc_str, data_str = m.groups()
        bus = int(bus_str)
        msg_id = int(id_str, 16)
        ts = parse_ts(ts_str)
        if t0 is None:
            t0 = ts
        rel = ts - t0
        data = [int(b, 16) for b in data_str.strip().split()]

        if bus == 2:
            if msg_id == 0x3E9 and len(data) >= 2:
                vv = (data[0] >> 7) & 0x1
                if vv == 0:
                    vspd = ((data[0] & 0x7F) << 8 | data[1]) * 0.015625
                    frames_3e9.append((rel, vspd))
            elif msg_id == 0x1F5 and len(data) >= 4:
                frames_1f5.append((rel, data[3] & 0xF))
        elif bus == 3:
            if msg_id in frames:
                frames[msg_id].append((rel, data))

def get_lever(t):
    lever = 1
    for ft, lp in frames_1f5:
        if ft <= t:
            lever = lp
        else:
            break
    return lever

def motor_rpm_at(t):
    # Find nearest 3e9 frame
    best = min(frames_3e9, key=lambda x: abs(x[0]-t))
    spd = best[1]
    sign = -1 if get_lever(t) == 2 else 1
    return sign * spd * MOTOR_RATIO

# Key moments to sample
moments = [
    (5.0,   "Park (idle)"),
    (30.0,  "Drive #1 accel"),
    (37.0,  "Drive #1 peak"),
    (44.0,  "Drive #1 decel"),
    (46.5,  "Entering Reverse #1"),
    (49.0,  "Reverse #1 peak"),
    (52.0,  "Reverse #1 decel"),
    (60.0,  "Drive #2 mid"),
    (68.0,  "Drive #2 peak"),
    (86.5,  "Reverse #3 start"),
    (89.0,  "Reverse #3 peak"),
    (100.0, "Park (end)"),
]

def nearest_val(ts_list, t, extractor):
    best = None
    best_dt = 9999
    for ft, d in ts_list:
        dt = abs(ft - t)
        if dt < best_dt:
            v = extractor(d)
            if v is not None:
                best_dt = dt
                best = v
    return best

print("=" * 100)
print("CANDIDATE SIGNAL VALUES AT KEY MOMENTS vs MOTOR RPM PROXY")
print("=" * 100)

# Header
header = f"{'Time':>7}  {'Phase':<22}  {'MotorRPM':>9}"
for _, label, _ in CANDIDATES:
    header += f"  {label[:18]:>18}"
print(header)
print("-" * (42 + 20 * len(CANDIDATES)))

for t, phase in moments:
    mrpm = motor_rpm_at(t)
    row = f"{t:7.1f}  {phase:<22}  {mrpm:9.1f}"
    for cid, label, extractor in CANDIDATES:
        v = nearest_val(frames[cid], t, extractor)
        if v is None:
            row += f"  {'N/A':>18}"
        else:
            row += f"  {v:18.1f}"
    print(row)

# Now show value range for each candidate
print()
print("=" * 80)
print("CANDIDATE VALUE RANGES AND ESTIMATED SCALING")
print("=" * 80)
print(f"  Motor RPM proxy range: {min(v for _,v in frames_3e9)*-MOTOR_RATIO:.0f} to {max(v for _,v in frames_3e9)*MOTOR_RATIO:.0f} RPM (signed)")
print()

for cid, label, extractor in CANDIDATES:
    vals = [extractor(d) for _, d in frames[cid] if extractor(d) is not None]
    if not vals:
        print(f"  {label}: NO DATA")
        continue
    lo, hi = min(vals), max(vals)
    span = hi - lo
    # Estimate scale factor: if this were motor RPM, what is counts/RPM?
    # Peak motor RPM magnitude is ~1000 RPM, so span/(2*1000) = counts per RPM
    if span > 0:
        scale = span / (max(abs(v) for v in [motor_rpm_at(t) for t, _ in moments if motor_rpm_at(t) != 0]) * 2)
    else:
        scale = float('nan')
    print(f"  {label}")
    print(f"    Range: {lo:.0f} to {hi:.0f}  (span={span:.0f})")
    print(f"    Estimated scale if this = motor RPM: ~{scale:.4f} counts/RPM  (~{1/scale:.1f} RPM/count)" if scale > 0 else "    (constant signal)")
    print()

# Show raw byte layout for 0x5A2 and 0x308 (our top signed candidates)
print("=" * 80)
print("RAW BYTE LAYOUT: 0x5A2 at key moments")
print("=" * 80)
print(f"{'Time':>7}  {'Phase':<22}  B0   B1   B2   B3   B4   B5   B6   B7   | B2-3(LE)-32768")
for t, phase in moments:
    best = min(frames[0x5A2], key=lambda x: abs(x[0]-t), default=None)
    if best is None:
        continue
    _, d = best
    val = ((d[3]<<8)|d[2]) - 32768 if len(d)>=4 else None
    raw = '  '.join(f'{b:02X}' for b in d[:8])
    print(f"{t:7.1f}  {phase:<22}  {raw}   | {val}")

print()
print("=" * 80)
print("RAW BYTE LAYOUT: 0x308 at key moments")
print("=" * 80)
print(f"{'Time':>7}  {'Phase':<22}  B0   B1   B2   B3   B4   B5   B6   B7   | B1-2(LE)  B2-3(BE)-32768")
for t, phase in moments:
    best = min(frames[0x308], key=lambda x: abs(x[0]-t), default=None)
    if best is None:
        continue
    _, d = best
    le = (d[2]<<8)|d[1] if len(d)>=3 else None
    be = ((d[2]<<8)|d[3]) - 32768 if len(d)>=4 else None
    raw = '  '.join(f'{b:02X}' for b in d[:8])
    print(f"{t:7.1f}  {phase:<22}  {raw}   | {le}  {be}")
