"""
Investigate motor torque command candidates:
- 0x5A0-0x5AF range (neighbors of confirmed 0x5A2 motor RPM/torque)
- 0x597 (appears in correlation results at r~0.8)
- 0x6000001 B0 (appears at r=0.9998 - very high)
"""

import re
from collections import defaultdict

LOG_PATH = r"projects/vtrux/logs/movingaroundindriveway.log"
BUSMASTER_RE = re.compile(
    r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+((?:[0-9A-Fa-f]{2}\s*)+)'
)


def parse_ts(ts):
    h, m, s, t = ts.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001


frames_597 = []
frames_6000001 = []
frames_5A = defaultdict(list)
frames_1f5 = []
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

        if bus == 2 and mid == 0x1F5 and len(data) >= 4:
            frames_1f5.append((rel, data[3] & 0xF))
        elif bus == 3:
            if mid == 0x597:
                frames_597.append((rel, data))
            elif mid == 0x6000001:
                frames_6000001.append((rel, data))
            elif 0x5A0 <= mid <= 0x5AF:
                frames_5A[mid].append((rel, data))


def get_lever(t):
    lever = 1
    for ft, lp in frames_1f5:
        if ft <= t:
            lever = lp
        else:
            break
    return lever


def nearest(fl, t):
    return min(fl, key=lambda x: abs(x[0] - t))[1]


moments = [
    (5.0,  'Park'),
    (37.0, 'Drive#1 peak'),
    (49.0, 'Rev#1 peak'),
    (60.0, 'Drive#2 mid'),
    (68.0, 'Drive#2 peak'),
    (89.0, 'Rev#3 peak'),
]

# --- 0x5A0-0x5AF ---
print('=== 0x5A0-0x5AF IDs present ===')
for mid in sorted(frames_5A.keys()):
    fl = frames_5A[mid]
    print(f'  0x{mid:03X}: {len(fl)} frames')
    max_b = max(len(d) for _, d in fl)
    byte_info = ' '.join(
        f'B{i}:{len(set(d[i] for _, d in fl if len(d) > i))}'
        for i in range(min(max_b, 8))
    )
    print(f'  Unique/byte: {byte_info}')
    print(f'  {"Time":>6}  {"Phase":<16}  B0   B1   B2   B3   B4   B5   B6   B7   | w23  w45')
    for t, phase in moments:
        d = nearest(fl, t)
        raw = '  '.join(f'{b:02X}' for b in d[:8])
        w23 = ((d[3] << 8) | d[2]) - 32768 if len(d) >= 4 else None
        w45 = ((d[5] << 8) | d[4]) - 32768 if len(d) >= 6 else None
        print(f'  {t:6.1f}  {phase:<16}  {raw}   | {w23}  {w45}')
    print()

# --- 0x597 ---
print('=== 0x597 ===')
if frames_597:
    print(f'  {len(frames_597)} frames')
    max_b = max(len(d) for _, d in frames_597)
    byte_info = ' '.join(
        f'B{i}:{len(set(d[i] for _, d in frames_597 if len(d) > i))}'
        for i in range(min(max_b, 8))
    )
    print(f'  Unique/byte: {byte_info}')
    print(f'  {"Time":>6}  {"Phase":<16}  B0   B1   B2   B3   B4   B5   B6   B7   | w12  w56  w67')
    for t, phase in moments:
        d = nearest(frames_597, t)
        raw = '  '.join(f'{b:02X}' for b in d[:8])
        w12 = ((d[2] << 8) | d[1]) - 32768 if len(d) >= 3 else None
        w56 = ((d[6] << 8) | d[5]) - 32768 if len(d) >= 7 else None
        w67 = ((d[7] << 8) | d[6]) - 32768 if len(d) >= 8 else None
        print(f'  {t:6.1f}  {phase:<16}  {raw}   | w12={w12}  w56={w56}  w67={w67}')
    print()
    # Unique values of key bytes
    for i in [5, 6, 7]:
        vals = sorted(set(d[i] for _, d in frames_597 if len(d) > i))
        print(f'  B{i} unique values: {vals[:20]}')
else:
    print('  NO DATA')
print()

# --- 0x6000001 ---
print('=== 0x6000001 detail ===')
if frames_6000001:
    print(f'  {len(frames_6000001)} frames')
    max_b = max(len(d) for _, d in frames_6000001)
    byte_info = ' '.join(
        f'B{i}:{len(set(d[i] for _, d in frames_6000001 if len(d) > i))}'
        for i in range(min(max_b, 8))
    )
    print(f'  Unique/byte: {byte_info}')
    print(f'  {"Time":>6}  {"Phase":<16}  B0   B1   B2   B3   B4   B5   B6   B7   Lever')
    for t, phase in moments:
        d = nearest(frames_6000001, t)
        lever = get_lever(t)
        raw = '  '.join(f'{b:02X}' for b in d[:8])
        print(f'  {t:6.1f}  {phase:<16}  {raw}   Lev={lever}')

    # B0 full range and B3 unique values
    b0_vals = sorted(set(d[0] for _, d in frames_6000001))
    b3_vals = sorted(set(d[3] for _, d in frames_6000001))
    print(f'\n  B0 unique ({len(b0_vals)}): {b0_vals[:30]}')
    print(f'  B3 unique ({len(b3_vals)}): {b3_vals}')

    # Show B0 timeseries at a few key moments with finer resolution
    print('\n  B0 timeseries (t=25-45s, Drive#1 region with throttle):')
    for t_rel, d in frames_6000001:
        if 25 <= t_rel <= 45:
            lever = get_lever(t_rel)
            print(f'    t={t_rel:6.2f}  B0={d[0]:3d}  B3={d[3]}  Lev={lever}')
