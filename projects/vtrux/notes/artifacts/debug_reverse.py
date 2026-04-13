"""
Raw diagnostics for 0x0C7 and 0x0F9 during Reverse phases.
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

frames_0c7 = []
frames_0f9 = []
t0 = None

with open(LOG_PATH, 'r', errors='replace') as f:
    for line in f:
        m = BUSMASTER_RE.match(line.strip())
        if not m:
            continue
        ts_str, bus_str, id_str, dlc_str, data_str = m.groups()
        if int(bus_str) != 2:
            continue
        msg_id = int(id_str, 16)
        ts = parse_ts(ts_str)
        if t0 is None:
            t0 = ts
        rel = ts - t0
        data = [int(b, 16) for b in data_str.strip().split()]
        if msg_id == 0x0C7:
            frames_0c7.append((rel, data))
        elif msg_id == 0x0F9:
            frames_0f9.append((rel, data))

# --- 0x0C7: show unique B0 values ---
print("=== 0x0C7 B0 unique values (all frames) ===")
b0_counter = Counter(d[0] for _, d in frames_0c7 if d)
for val, cnt in sorted(b0_counter.items()):
    direction = (val >> 6) & 0x3
    valid = (val >> 2) & 0x1
    pulse_msbs = val & 0x3
    print(f"  B0=0x{val:02X} ({val:08b}): direction={direction} valid={'Y' if not valid else 'N'} pulse_msbs={pulse_msbs}  count={cnt}")

print()
print("=== 0x0C7 first 10 frames raw ===")
for t, d in frames_0c7[:10]:
    print(f"  t={t:.3f}  {' '.join(f'{b:02X}' for b in d)}")

print()
print("=== 0x0C7 during Reverse #1 (t=47-53s) - first 20 unique B0 ===")
seen = set()
count = 0
for t, d in frames_0c7:
    if 47.0 <= t <= 53.0:
        if d[0] not in seen:
            direction = (d[0] >> 6) & 0x3
            valid = (d[0] >> 2) & 0x1
            pulse = ((d[0] & 0x3) << 8) | d[1]
            print(f"  t={t:.3f}  B0=0x{d[0]:02X} ({d[0]:08b})  dir={direction} valid={valid} pulse={pulse}  raw={' '.join(f'{b:02X}' for b in d)}")
            seen.add(d[0])
        count += 1
        if count >= 100 and len(seen) >= 4:
            break

# --- 0x0F9: raw during Reverse #1 ---
print()
print("=== 0x0F9 B2 unique values during Drive #1 (t=25-46s) ===")
b2_drive = Counter(d[2] for t, d in frames_0f9 if 25.0 <= t <= 46.0 and len(d) >= 5)
for val, cnt in sorted(b2_drive.items()):
    shaft_valid = (val >> 7) & 0x1
    print(f"  B2=0x{val:02X} ({val:08b}): shaft_valid={shaft_valid}  count={cnt}")

print()
print("=== 0x0F9 B2 unique values during Reverse #1 (t=46.63-53.32s) ===")
b2_rev = Counter(d[2] for t, d in frames_0f9 if 46.63 <= t <= 53.32 and len(d) >= 5)
for val, cnt in sorted(b2_rev.items()):
    shaft_valid = (val >> 7) & 0x1
    print(f"  B2=0x{val:02X} ({val:08b}): shaft_valid={shaft_valid}  count={cnt}")

print()
print("=== 0x0F9 sample frames during Reverse #1 (t=47-52s) - first 15 ===")
count = 0
for t, d in frames_0f9:
    if 47.0 <= t <= 52.0:
        shaft_valid = (d[2] >> 7) & 0x1
        shaft_rpm_raw = (d[3] << 8) | d[4]
        shaft_rpm = shaft_rpm_raw * 0.25
        print(f"  t={t:.3f}  B2=0x{d[2]:02X} valid={shaft_valid}  "
              f"shaft_raw={shaft_rpm_raw} rpm={shaft_rpm:.2f}  raw={' '.join(f'{b:02X}' for b in d)}")
        count += 1
        if count >= 15:
            break

print()
print("=== 0x0F9 sample frames during Reverse #1 at speed peak (t=48-51s) ===")
count = 0
for t, d in frames_0f9:
    if 48.0 <= t <= 51.0:
        shaft_valid = (d[2] >> 7) & 0x1
        shaft_rpm_raw = (d[3] << 8) | d[4]
        shaft_rpm = shaft_rpm_raw * 0.25
        print(f"  t={t:.3f}  B2=0x{d[2]:02X} valid={shaft_valid}  "
              f"B3=0x{d[3]:02X} B4=0x{d[4]:02X} raw_rpm={shaft_rpm_raw} rpm={shaft_rpm:.2f}")
        count += 1
        if count >= 20:
            break

# Check if maybe shaft speed is in different bytes
print()
print("=== During Drive #1 peak speed (t=35-40s): all 0x0F9 bytes ===")
count = 0
for t, d in frames_0f9:
    if 35.0 <= t <= 37.0 and count < 5:
        print(f"  t={t:.3f}  {' '.join(f'{b:02X}' for b in d)}  "
              f"B3B4={((d[3]<<8)|d[4])} -> {((d[3]<<8)|d[4])*0.25:.2f} rpm")
        count += 1
