"""
Verify 0x6000001 as motor torque COMMAND in T7 log.
T7 has active Reverse throttle, so we can see if B0 encodes negative torque
(or uses a different encoding for reverse direction).
Also check 0x597 vs 0x5A2 for mirroring.
"""

import re
from collections import defaultdict

LOG_PATH = r"projects/vtrux/logs/debuglog_M0_T7.log"
BUSMASTER_RE = re.compile(
    r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+((?:[0-9A-Fa-f]{2}\s*)+)'
)


def parse_ts(ts):
    h, m, s, t = ts.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001


frames_6000001 = []
frames_5A2 = []
frames_597 = []
frames_592 = []
t0 = None

with open(LOG_PATH, errors='replace') as f:
    for line in f:
        m = BUSMASTER_RE.match(line.strip())
        if not m:
            continue
        ts_str, bus_str, id_str, _, data_str = m.groups()
        bus = int(bus_str)
        mid = int(id_str, 16)
        ts = parse_ts(ts_str)
        if t0 is None:
            t0 = ts
        rel = ts - t0
        data = [int(b, 16) for b in data_str.strip().split()]

        if bus == 1:
            if mid == 0x6000001:
                frames_6000001.append((rel, data))
            elif mid == 0x5A2:
                frames_5A2.append((rel, data))
            elif mid == 0x597:
                frames_597.append((rel, data))
            elif mid == 0x592:
                frames_592.append((rel, data))


def nearest(fl, t):
    if not fl:
        return None
    return min(fl, key=lambda x: abs(x[0] - t))[1]


# Print full timeseries for key signals, focused on reverse throttle period
print("=" * 90)
print("T7 log: Motor torque command candidate 0x6000001 B0 vs RPM/torque (0x5A2)")
print("T7: decelerates from highway speed, briefly reverses with throttle, then parks")
print("=" * 90)
print()
print(f"  {'Time':>7}  {'0x6000001':>12}  {'0x5A2':>16}  {'Throttle':>10}")
print(f"  {'':>7}  {'B0':>4} {'B3':>4} {'B4':>4}  {'RPM(w23)':>8} {'Torq(w45)':>8}  {'B23-LE':>10}")
print("-" * 90)

# Print every 0.5 seconds
t = 0.0
while t <= 50:
    d6 = nearest(frames_6000001, t)
    d5 = nearest(frames_5A2, t)
    d592 = nearest(frames_592, t)

    if d6 and d5:
        b0 = d6[0]
        b3 = d6[3] if len(d6) > 3 else None
        b4 = d6[4] if len(d6) > 4 else None
        rpm = ((d5[3] << 8) | d5[2]) - 32768 if len(d5) >= 4 else None
        torq = ((d5[5] << 8) | d5[4]) - 32768 if len(d5) >= 6 else None
        thr = ((d592[3] << 8) | d592[2]) if d592 and len(d592) >= 4 else None

        print(f"  {t:7.1f}  {b0:4d} {b3:4d} {b4:4d}  {rpm:8d} {torq:8d}  {thr:10d}")
    t += 0.5

# Also show the B0 unique values in T7
print()
b0_vals = sorted(set(d[0] for _, d in frames_6000001 if len(d) > 0))
b3_vals = sorted(set(d[3] for _, d in frames_6000001 if len(d) > 3))
print(f"B0 unique values ({len(b0_vals)}): {b0_vals[:40]}")
print(f"B3 unique values ({len(b3_vals)}): {b3_vals}")

# Show 0x597 vs 0x5A2 to see if 597 mirrors 5A2
print()
print("=" * 90)
print("0x597 vs 0x5A2 — checking for mirror relationship")
print("=" * 90)
print(f"  {'Time':>7}  {'0x597':>24}  {'0x5A2':>16}")
print(f"  {'':>7}  {'B1-2(LE)-32768':>14} {'B5-6(LE)-32768':>14}  {'w23(RPM)':>8} {'w45(Torq)':>8}")
print("-" * 90)

for t in [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20]:
    d597 = nearest(frames_597, t)
    d5A2 = nearest(frames_5A2, t)
    if d597 and d5A2:
        w12_597 = ((d597[2] << 8) | d597[1]) - 32768 if len(d597) >= 3 else None
        w56_597 = ((d597[6] << 8) | d597[5]) - 32768 if len(d597) >= 7 else None
        rpm_5A2 = ((d5A2[3] << 8) | d5A2[2]) - 32768 if len(d5A2) >= 4 else None
        torq_5A2 = ((d5A2[5] << 8) | d5A2[4]) - 32768 if len(d5A2) >= 6 else None
        print(f"  {t:7.1f}  {w12_597:14d} {w56_597:14d}  {rpm_5A2:8d} {torq_5A2:8d}")
