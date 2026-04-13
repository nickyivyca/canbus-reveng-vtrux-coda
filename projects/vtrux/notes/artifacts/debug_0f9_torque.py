"""
Check if 0x0F9 torque ratio truly is constant, and look at what changes in Reverse.
"""
import re
from collections import Counter

LOG_PATH = r"projects/vtrux/logs/movingaroundindriveway.log"
BUSMASTER_RE = re.compile(
    r'(\d+:\d+:\d+:\d+)\s+(?:Rx|Tx)\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+[sx]\s+(\d+)\s+((?:[0-9A-Fa-f]{2}\s*)+)'
)

def parse_ts(ts_str):
    h, m, s, t = ts_str.split(':')
    return int(h)*3600 + int(m)*60 + int(s) + int(t)*0.0001

frames = []
t0 = None

with open(LOG_PATH, 'r', errors='replace') as f:
    for line in f:
        m = BUSMASTER_RE.match(line.strip())
        if not m:
            continue
        ts_str, bus_str, id_str, dlc_str, data_str = m.groups()
        if int(bus_str) != 2:
            continue
        if int(id_str, 16) != 0x0F9:
            continue
        ts = parse_ts(ts_str)
        if t0 is None:
            t0 = ts
        rel = ts - t0
        data = [int(b, 16) for b in data_str.strip().split()]
        frames.append((rel, data))

print(f"Total 0x0F9 frames: {len(frames)}")
print()

# Count unique B0B1 combinations
b01_counter = Counter((d[0], d[1]) for _, d in frames if len(d) >= 2)
print(f"Unique B0-B1 values: {len(b01_counter)}")
for (b0, b1), cnt in sorted(b01_counter.items(), key=lambda x: -x[1])[:10]:
    raw = (b0 & 0x7F) << 8 | b1
    ratio = raw / 256.0
    print(f"  B0=0x{b0:02X} B1=0x{b1:02X}  raw={raw}  ratio={ratio:.4f}  count={cnt}")

print()
# Count unique B3B4 (shaft RPM) values — non-zero ones
b34_counter = Counter((d[3], d[4]) for _, d in frames if len(d) >= 5 and (d[3] or d[4]))
print(f"Non-zero B3-B4 (shaft RPM) unique values: {len(b34_counter)}")
for (b3, b4), cnt in sorted(b34_counter.items(), key=lambda x: -x[1])[:10]:
    raw = (b3 << 8) | b4
    rpm = raw * 0.25
    print(f"  B3=0x{b3:02X} B4=0x{b4:02X}  raw={raw}  rpm={rpm:.2f}  count={cnt}")

print()
# Show B5 and B6 during Reverse #1 — these are changing
print("=== B5, B6 during Reverse #1 (t=47-52s), first 15 ===")
count = 0
for t, d in frames:
    if 47.0 <= t <= 52.0:
        print(f"  t={t:.3f}  B5=0x{d[5]:02X}={d[5]}  B6=0x{d[6]:02X}={d[6]}  "
              f"B7=0x{d[7]:02X}  full={' '.join(f'{b:02X}' for b in d)}")
        count += 1
        if count >= 15:
            break

print()
# During Drive, what does B5/B6 look like?
print("=== B5, B6 during Drive #1 peak (t=35-36s), first 10 ===")
count = 0
for t, d in frames:
    if 35.0 <= t <= 36.0:
        print(f"  t={t:.3f}  B5=0x{d[5]:02X}={d[5]}  B6=0x{d[6]:02X}={d[6]}  "
              f"shaft_rpm={(d[3]<<8|d[4])*0.25:.2f}  full={' '.join(f'{b:02X}' for b in d)}")
        count += 1
        if count >= 10:
            break
