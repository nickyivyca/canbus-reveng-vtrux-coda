"""
single_byte_scan.py -- Single-byte correlation scan of all PT bus IDs vs V_avg_ref.
The brute-force pair scan missed single-byte encodings of cell voltage.
Also tests 3-byte LE/BE combinations and checks 0x63A B6 delta specifically.

Threshold: |r| > 0.70
Scale target for cell voltage: B * scale = V_avg_mV where scale in 1-30 mV/count range.
"""
import sys, bisect, math
sys.path.insert(0, '.')
from canre.parsers import parse_file

LOG = 'projects/vtrux/logs/vtruxcurrentlimitingtest.log'
OUT = 'projects/vtrux/notes/artifacts/single_byte_scan.txt'

print('Loading...', flush=True)
frames = list(parse_file(LOG))
bus_ids = {}
for f in frames:
    bus_ids.setdefault(f.bus, set()).add(f.arbitration_id)
pt_bus = next(b for b, ids in bus_ids.items() if 0x051 in ids)
print(f'PT bus = Bus {pt_bus}')

# V_avg_ref from 0x482
f482 = [(f.timestamp, f.data) for f in frames
        if f.bus == pt_bus and f.arbitration_id == 0x482 and len(f.data) >= 3]
t_482 = [t for t, _ in f482]
v_avg_arr = [(d[1] + d[2]*256) / 117.0 * 1000 for _, d in f482]

def nearest_ref(ts):
    idx = bisect.bisect_left(t_482, ts)
    if idx == 0: return v_avg_arr[0]
    if idx >= len(t_482): return v_avg_arr[-1]
    return v_avg_arr[idx-1] if abs(t_482[idx-1]-ts) < abs(t_482[idx]-ts) else v_avg_arr[idx]

def pearson_r(xs, ys):
    n = len(xs)
    if n < 30: return float('nan')
    xm = sum(xs)/n; ym = sum(ys)/n
    cov = sum((x-xm)*(y-ym) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x-xm)**2 for x in xs))
    sy = math.sqrt(sum((y-ym)**2 for y in ys))
    if sx == 0 or sy == 0: return float('nan')
    return cov / (sx * sy)

# Group frames by ID on PT bus
print('Grouping frames...')
by_id = {}
for f in frames:
    if f.bus != pt_bus: continue
    by_id.setdefault(f.arbitration_id, []).append((f.timestamp, f.data))

results = []
print(f'Scanning {len(by_id)} IDs for single-byte cell voltage signals...')

for aid, flist in sorted(by_id.items()):
    step = max(1, len(flist) // 3000)
    flist_s = flist[::step]
    dlc = max(len(d) for _, d in flist_s)

    refs_all = [nearest_ref(ts) for ts, _ in flist_s]
    if len(set(int(r*10) for r in refs_all)) < 5:
        continue

    # Test single bytes
    for i in range(min(dlc, 8)):
        raw = [d[i] for _, d in flist_s if len(d) > i]
        refs = [refs_all[j] for j, (_, d) in enumerate(flist_s) if len(d) > i]
        if len(raw) < 30: continue
        if len(set(raw)) < 5: continue
        r = pearson_r(raw, refs)
        if math.isnan(r): continue
        if abs(r) > 0.70:
            mean_raw = sum(raw)/len(raw)
            mean_ref = sum(refs)/len(refs)
            scale = mean_ref / mean_raw if mean_raw != 0 else 0
            results.append((abs(r), r, aid, f'B{i}', mean_raw, mean_ref, len(raw), scale))

    # Test 3-byte combinations (LE only, for broader cell voltage search)
    for i in range(min(dlc-2, 6)):
        raw_le = [d[i] + d[i+1]*256 + d[i+2]*65536
                  for _, d in flist_s if len(d) > i+2]
        refs = [refs_all[j] for j, (_, d) in enumerate(flist_s) if len(d) > i+2]
        if len(raw_le) < 30: continue
        if len(set(raw_le)) < 10: continue
        r = pearson_r(raw_le, refs)
        if math.isnan(r): continue
        if abs(r) > 0.70:
            mean_raw = sum(raw_le)/len(raw_le)
            mean_ref = sum(refs)/len(refs)
            scale = mean_ref / mean_raw if mean_raw != 0 else 0
            results.append((abs(r), r, aid, f'B{i}-B{i+2} LE', mean_raw, mean_ref, len(raw_le), scale))

results.sort(reverse=True)

lines = []
lines.append('=== PT Bus Single-Byte + 3-Byte Correlation Scan vs V_avg_ref ===')
lines.append(f'Reference: 0x482 B1-B2 LE / 117 = V_avg_ref (mV)')
lines.append(f'Threshold: |r| > 0.70')
lines.append(f'Candidates found: {len(results)}')
lines.append('')
lines.append(f'  {"ID":<12} {"Signal":<14} {"r":>8}  {"mean_raw":>10}  {"mean_ref_mV":>12}  {"frames":>8}  scale(mV/cnt)')
lines.append('-' * 95)

KNOWN_PACK_VOLTAGE = {0x482, 0x470, 0x440}
for ar, r, aid, sig, mr, mref, nf, sc in results[:60]:
    note = ' [PKV]' if aid in KNOWN_PACK_VOLTAGE else ''
    lines.append(f'  0x{aid:08X}  {sig:<14}  {r:8.4f}  {mr:10.1f}  {mref:12.1f}  {nf:8}  {sc:.5f}{note}')

lines.append('')
lines.append('=== Scale filter: only show candidates where scale in [1, 30] mV/count ===')
lines.append('(Plausible range for direct single-byte cell voltage encoding)')
lines.append(f'  {"ID":<12} {"Signal":<14} {"r":>8}  {"mean_raw":>10}  {"mean_V_mV":>12}  {"frames":>8}  scale(mV/cnt)')
lines.append('-' * 95)
for ar, r, aid, sig, mr, mref, nf, sc in results:
    if 1.0 <= abs(sc) <= 30.0 and aid not in KNOWN_PACK_VOLTAGE:
        lines.append(f'  0x{aid:08X}  {sig:<14}  {r:8.4f}  {mr:10.1f}  {mref:12.1f}  {nf:8}  {sc:.5f}')

lines.append('')
lines.append('=== 0x63A Byte Analysis During High-Current Event (t=580-640s, V_pack~341V) ===')
f63a = [(f.timestamp, f.data) for f in frames
        if f.bus == pt_bus and f.arbitration_id == 0x63A and len(f.data) >= 8]
lines.append(f'  Time     V_pack  V_avg_mV  B0  B1  B2  B3  B4  B5  B6  B7')
for ts, data in f63a:
    if 570 <= ts <= 660:
        vp = by_id[0x482][bisect.bisect_left([t for t, _ in f482], ts)][1] if f482 else [0]*8
        va = nearest_ref(ts)
        vp_val = int(va * 117 / 1000)
        b = list(data)
        while len(b) < 8: b.append(0)
        lines.append(f'  {ts:7.1f}  {vp_val:6d}  {va:8.1f}  {b[0]:3d} {b[1]:3d} {b[2]:3d} {b[3]:3d} {b[4]:3d} {b[5]:3d} {b[6]:3d} {b[7]:3d}')

out = '\n'.join(lines)
print(out)
with open(OUT, 'w') as fh:
    fh.write(out)
print(f'\nSaved to {OUT}')
