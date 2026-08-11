"""
Dump raw 0x0C1 frames to understand the actual byte layout.
Show frames around gear transitions to see what changes.
"""

import re

LOG_PATH = r"<home>\<drive-root>\<library>\My Libraries\Projects\reverse-it\projects\vtrux\threebus-investigation\movingaroundindriveway.log"

BUSMASTER_RE = re.compile(
    r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+((?:[0-9A-Fa-f]{2}\s*)+)'
)

def parse_ts(ts_str):
    h, m, s, t = ts_str.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001

t0 = None
frames = []

with open(LOG_PATH, 'r', errors='replace') as f:
    for line in f:
        m = BUSMASTER_RE.match(line.strip())
        if not m:
            continue
        ts_str, bus_str, id_str, dlc_str, data_str = m.groups()
        if int(bus_str) != 2:
            continue
        msg_id = int(id_str, 16)
        if msg_id != 0x0C1:
            continue
        ts = parse_ts(ts_str)
        if t0 is None:
            t0 = ts
        rel = ts - t0
        data = [int(b, 16) for b in data_str.strip().split()]
        frames.append((rel, data))

# Print raw frames in windows of interest
windows = [
    (23.0, 26.0, "Park->Reverse->Drive transition"),
    (44.0, 48.0, "Drive->Neutral->Reverse"),
    (51.0, 55.0, "Reverse->Neutral->Drive"),
]

for (t_start, t_end, label) in windows:
    print(f"\n{'='*70}")
    print(f"{label}  (t={t_start}-{t_end}s)")
    print(f"{'='*70}")
    print(f"{'Time':>8}  B0   B1   B2   B3   | B4   B5   B6   B7")
    print(f"{'':>8}  [------Left------]   [-----Right------]")
    print("-"*65)
    prev = None
    for (t, d) in frames:
        if not (t_start <= t <= t_end):
            continue
        if len(d) < 8:
            continue
        # Only print if something changed from previous
        if prev is not None and d == prev:
            continue
        marker = " <-- CHANGED" if prev is not None and d != prev else ""
        print(f"{t:8.3f}  {d[0]:02X}   {d[1]:02X}   {d[2]:02X}   {d[3]:02X}   | {d[4]:02X}   {d[5]:02X}   {d[6]:02X}   {d[7]:02X}{marker}")
        prev = d

# Also print some stats on what values each byte takes
print(f"\n{'='*70}")
print("BYTE VALUE RANGES across all frames (bus 2, 0x0C1)")
print(f"{'='*70}")
from collections import Counter
byte_vals = [Counter() for _ in range(8)]
for (t, d) in frames:
    for i, b in enumerate(d[:8]):
        byte_vals[i][b] += 1

for i in range(8):
    vals = sorted(byte_vals[i].keys())
    print(f"B{i}: {len(vals)} unique values, range [{min(vals):02X}, {max(vals):02X}]  "
          f"-- sample: {[f'{v:02X}' for v in vals[:8]]} ...")

# Print first 20 frames to see initial pattern
print(f"\n{'='*70}")
print("FIRST 30 FRAMES (raw)")
print(f"{'='*70}")
print(f"{'Time':>8}  B0   B1   B2   B3   | B4   B5   B6   B7")
for (t, d) in frames[:30]:
    if len(d) >= 8:
        print(f"{t:8.3f}  {d[0]:02X}   {d[1]:02X}   {d[2]:02X}   {d[3]:02X}   | {d[4]:02X}   {d[5]:02X}   {d[6]:02X}   {d[7]:02X}")
