"""
Focused analysis around the M-shift attempt (~33s) during fuse-out.
1. Check if 0x050/0x051/0x052 ever appear in 0-102s
2. Decode 0x1F5 gear transitions (B3 values at shift event)
3. Check all PT bus state changes in the 30-40s window
"""
import re
from collections import defaultdict

LOG = "projects/vtrux/logs/vtrux_no_gene_inv_fuse.log"

def parse_time(t):
    h, m, s, ticks = t.split(":")
    return int(h)*3600 + int(m)*60 + int(s) + int(ticks)*0.0001

line_re = re.compile(r'^(\d{2}:\d{2}:\d{2}:\d{4})\s+\S+\s+(\d+)\s+(0x[0-9A-Fa-f]+)\s+\S+\s+(\d+)((?:\s+[0-9A-Fa-f]{2})*)')

SHIFT_WINDOW = (28.0, 42.0)
FULL_WINDOW = (0.0, 102.5)

records = defaultdict(list)

with open(LOG, encoding="latin-1") as f:
    for line in f:
        m = line_re.match(line)
        if not m:
            continue
        t = parse_time(m.group(1))
        if t > FULL_WINDOW[1]:
            break
        if t < FULL_WINDOW[0]:
            continue
        arb_id = m.group(3).upper()
        data = [int(x, 16) for x in m.group(5).split()]
        ch = int(m.group(2))
        records[arb_id].append((t, ch, data))

def le16(data, offset):
    return data[offset] | (data[offset+1] << 8)

print("=== 0x050/0x051/0x052 presence in fuse-out window (0-102s) ===")
for fid in ["0X050", "0X051", "0X052"]:
    recs = records[fid]
    if not recs:
        print(f"  {fid}: ABSENT (0 frames)")
    else:
        print(f"  {fid}: {len(recs)} frames, first={recs[0][0]:.3f}s last={recs[-1][0]:.3f}s")
        for t, ch, data in recs[:5]:
            print(f"    {t:.4f}s ch={ch}  " + " ".join(f"{b:02X}" for b in data))

print()
print(f"=== 0x1F5 gear transitions in shift window ({SHIFT_WINDOW[0]}-{SHIFT_WINDOW[1]}s) ===")
prev = None
for t, ch, data in records["0X1F5"]:
    if not (SHIFT_WINDOW[0] <= t <= SHIFT_WINDOW[1]):
        continue
    key = tuple(data)
    if key != prev:
        print(f"  {t:.4f}s  " + " ".join(f"B{i}={data[i]:02X}" for i in range(len(data))))
        prev = key

print()
print(f"=== 0x592 (HCU sensor) around shift window ===")
prev_b0 = None
for t, ch, data in records["0X592"]:
    if not (SHIFT_WINDOW[0] - 2 <= t <= SHIFT_WINDOW[1] + 2):
        continue
    b0 = data[0]
    brake = le16(data, 4) * 0.01 if len(data) >= 6 else -1
    ign = (b0 >> 4) & 1
    if b0 != prev_b0:
        print(f"  {t:.4f}s  ign={ign}  brake={brake:.1f}%  b0=0x{b0:02X}")
        prev_b0 = b0

print()
print(f"=== ALL PT bus IDs with ANY change in {SHIFT_WINDOW[0]}-{SHIFT_WINDOW[1]}s ===")
changed_ids = []
for arb_id, recs_list in sorted(records.items()):
    window_recs = [(t, ch, d) for t, ch, d in recs_list if SHIFT_WINDOW[0] <= t <= SHIFT_WINDOW[1]]
    if len(window_recs) < 2:
        continue
    first_data = window_recs[0][2]
    for t, ch, data in window_recs[1:]:
        if data != first_data:
            changed_ids.append(arb_id)
            break

print(f"  IDs with byte-level changes: {', '.join(changed_ids)}")

print()
print("=== 0x051 B3-B4 RPM ref check at exact M-shift time (25-45s) ===")
r051 = [(t, ch, d) for t, ch, d in records.get("0X051", []) if 25 <= t <= 45]
if not r051:
    print("  0x051 completely absent in 25-45s window")
else:
    for t, ch, data in r051[:20]:
        rpm_raw = le16(data, 3)
        rpm_str = "NULL" if rpm_raw == 0x7FFF else str(rpm_raw - 32767)
        torque = le16(data, 1) - 32768
        print(f"  {t:.4f}s  torque={torque:+6d}  rpm={rpm_str}")

print()
print("=== Check all IDs on each channel during fuse-out ===")
ch_ids = defaultdict(set)
for arb_id, recs_list in records.items():
    for t, ch, d in recs_list:
        ch_ids[ch].add(arb_id)
for ch in sorted(ch_ids):
    print(f"  ch={ch}: {len(ch_ids[ch])} IDs")
