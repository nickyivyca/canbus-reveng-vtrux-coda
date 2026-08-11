"""Settle 0x598 power-channel encoding: unsigned-centered-at-32768 vs signed-int16-zero-at-0.

DBL_ESSPwrAvg (B0-B1) and DBL_TracPwrAvg (B4-B5).
- If 'centered at 32768' (notes): raw uint16 clusters near 0x8000; the high byte sits near 0x80.
- If 'signed int16, zero at 0' (EPRI decompile): raw clusters near 0x0000 / 0xFFFF;
  the high byte sits near 0x00 (small +) or 0xFF (small -).
"""
import sys
sys.path.insert(0, ".")
from canre.parsers import parse_file
from collections import defaultdict

path = sys.argv[1]
TARGET = 0x598
ids_per_bus = defaultdict(set)
le_b01 = defaultdict(list)
le_b45 = defaultdict(list)
byte_sums = defaultdict(lambda: [0] * 6)
counts = defaultdict(int)

for f in parse_file(path):
    ids_per_bus[f.bus].add(f.arbitration_id)
    if f.arbitration_id == TARGET and len(f.data) >= 6:
        d = f.data
        le_b01[f.bus].append(d[0] | (d[1] << 8))
        le_b45[f.bus].append(d[4] | (d[5] << 8))
        for i in range(6):
            byte_sums[f.bus][i] += d[i]
        counts[f.bus] += 1

print("buses found:", sorted(ids_per_bus))
for bus in sorted(ids_per_bus):
    print(f"  bus {bus}: {len(ids_per_bus[bus])} ids  0x051={'Y' if 0x051 in ids_per_bus[bus] else 'N'}  0x598 frames={counts.get(bus,0)}")


def summarize(name, vals):
    if not vals:
        print(f"  {name}: no data")
        return
    vs = sorted(vals)
    mean = sum(vals) / len(vals)
    near_8000 = sum(1 for v in vals if 0x6000 <= v <= 0xA000)
    near_zero = sum(1 for v in vals if v <= 0x2000 or v >= 0xE000)
    print(f"  {name}: n={len(vals)} min=0x{vs[0]:04X} max=0x{vs[-1]:04X} "
          f"mean=0x{int(mean):04X} median=0x{vs[len(vs)//2]:04X}")
    print(f"     near 0x8000 (CENTERED): {100*near_8000/len(vals):5.1f}%   "
          f"near 0x0000/0xFFFF (SIGNED): {100*near_zero/len(vals):5.1f}%")


for bus in sorted(le_b01):
    if not le_b01[bus]:
        continue
    print(f"\n=== bus {bus} 0x598 (LE uint16) ===")
    summarize("B0-B1 (DBL_ESSPwrAvg)", le_b01[bus])
    summarize("B4-B5 (DBL_TracPwrAvg)", le_b45[bus])
    n = counts[bus]
    avg_bytes = [byte_sums[bus][i] / n for i in range(6)]
    print("  mean bytes B0..B5: " + " ".join(f"0x{int(b):02X}" for b in avg_bytes))
    print("  (centered->high byte ~0x80; signed-near-0->high byte ~0x00 or ~0xFF)")
