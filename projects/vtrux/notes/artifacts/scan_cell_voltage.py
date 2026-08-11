"""
scan_cell_voltage.py — Brute-force correlation scan of all PT bus IDs vs V_avg_ref = V_pack/117
Finds candidates that track average cell voltage.
"""
import sys, bisect, math
sys.path.insert(0, '.')
from canre.parsers import parse_file

LOG = 'projects/vtrux/logs/vtruxcurrentlimitingtest.log'
OUT = 'projects/vtrux/notes/artifacts/cell_voltage_scan.txt'

print('Loading...', flush=True)
frames = list(parse_file(LOG))

# Identify PT bus
bus_ids = {}
for f in frames:
    bus_ids.setdefault(f.bus, set()).add(f.arbitration_id)
pt_bus = next(b for b, ids in bus_ids.items() if 0x051 in ids)
print(f'PT bus = Bus {pt_bus}')

# Build 0x482 pack voltage reference (B1-B2 LE, integer V/count)
f482 = [(f.timestamp, f.data) for f in frames
        if f.bus == pt_bus and f.arbitration_id == 0x482 and len(f.data) >= 3]
t_482 = [t for t, _ in f482]
v_avg_arr = [(d[1] + d[2]*256) / 117.0 for _, d in f482]  # V per cell

def nearest_ref(ts):
    idx = bisect.bisect_left(t_482, ts)
    if idx == 0: return v_avg_arr[0]
    if idx >= len(t_482): return v_avg_arr[-1]
    return v_avg_arr[idx-1] if abs(t_482[idx-1]-ts) < abs(t_482[idx]-ts) else v_avg_arr[idx]

def pearson_r(xs, ys):
    n = len(xs)
    if n < 30:
        return float('nan')
    xm = sum(xs)/n
    ym = sum(ys)/n
    cov = sum((x-xm)*(y-ym) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x-xm)**2 for x in xs))
    sy = math.sqrt(sum((y-ym)**2 for y in ys))
    if sx == 0 or sy == 0:
        return float('nan')
    return cov / (sx * sy)

# Group frames by ID
print('Grouping frames by ID...')
by_id = {}
for f in frames:
    if f.bus != pt_bus:
        continue
    by_id.setdefault(f.arbitration_id, []).append((f.timestamp, f.data))

print(f'PT bus: {len(by_id)} IDs. Scanning...')
print()

results = []
for aid, flist in sorted(by_id.items()):
    step = max(1, len(flist) // 3000)
    flist_s = flist[::step]
    dlc = max(len(d) for _, d in flist_s)

    refs_all = [nearest_ref(ts) for ts, _ in flist_s]
    if len(set(int(r*100) for r in refs_all)) < 5:
        continue

    for i in range(min(dlc-1, 7)):
        for endian in ('BE', 'LE'):
            pairs = [(d[i]*256 + d[i+1]) if endian == 'BE' else (d[i] + d[i+1]*256)
                     for _, d in flist_s if len(d) > i+1]
            refs2 = [refs_all[j] for j, (_, d) in enumerate(flist_s) if len(d) > i+1]
            if len(pairs) < 30:
                continue
            if len(set(pairs)) < 10:
                continue
            r = pearson_r(pairs, refs2)
            if math.isnan(r):
                continue
            if abs(r) > 0.70:
                mean_raw = sum(pairs) / len(pairs)
                mean_ref_mv = sum(refs2) / len(refs2) * 1000
                scale_est = mean_ref_mv / mean_raw if mean_raw != 0 else 0
                results.append((abs(r), r, aid, i, endian, mean_raw, mean_ref_mv, len(pairs), scale_est))

results.sort(reverse=True)

lines = []
lines.append("=== PT Bus Brute-Force Cell Voltage Correlation Scan ===")
lines.append(f"Reference: 0x482 B1-B2 LE / 117 cells = V_avg_ref (V)")
lines.append(f"Threshold: |r| > 0.70")
lines.append(f"Candidates found: {len(results)}")
lines.append("")
lines.append(f"  {'ID':<10} {'Bytes':<12} {'r':>8}  {'mean_raw':>10}  {'mean_ref_mV':>12}  {'frames':>8}  scale(mV/cnt)")
lines.append("-" * 90)

for ar, r, aid, i, endian, mr, mref, nf, sc in results[:40]:
    lines.append(f"  0x{aid:03X}      B{i}-B{i+1} {endian:<5}  {r:8.4f}  {mr:10.1f}  {mref:12.1f}  {nf:8}  {sc:.5f}")

out = '\n'.join(lines)
print(out)
with open(OUT, 'w') as fh:
    fh.write(out)
print(f"\nSaved to {OUT}")
