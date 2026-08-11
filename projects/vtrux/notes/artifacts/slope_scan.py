"""
slope_scan.py -- Single-byte cell voltage scan using regression slope + intercept.

The previous scan's "scale" filter (mean_ref / mean_raw) is biased by fixed offsets.
If the signal encodes  V_cell = offset + count * scale, then:
    mean_ref / mean_raw  =  scale + offset/mean_raw   <-- inflated when offset is large

The regression slope is offset-invariant:
    slope  = cov(raw, ref) / var(raw)  =  r * std_ref / std_raw   [mV per count]
    intercept = mean_ref - slope * mean_raw                        [mV at count=0]

Physical filter (LFP A123 cells, useful range ~2800-3650 mV):
  |r|        > 0.65
  |slope|    in [1, 60] mV/cnt   -- 1-cnt resolution over at least 255 mV; 60-cnt for tight 4V range
  intercept  in [-500, 4500] mV  -- offset at count=0 must be physically sane
  V at observed min/max raw:     at least one end >= 1000 mV, other end <= 5500 mV

Output columns:
  ID, Byte, r, slope (mV/cnt), intercept (mV), V@min_raw, V@max_raw,
  observed raw range (cnt), n frames
"""
import sys, bisect, math
sys.path.insert(0, '.')
from canre.parsers import parse_file

LOG = 'projects/vtrux/logs/vtruxcurrentlimitingtest.log'
OUT = 'projects/vtrux/notes/artifacts/slope_scan.txt'

print('Loading...', flush=True)
frames = list(parse_file(LOG))
bus_ids = {}
for f in frames:
    bus_ids.setdefault(f.bus, set()).add(f.arbitration_id)
pt_bus = next(b for b, ids in bus_ids.items() if 0x051 in ids)
print(f'PT bus = Bus {pt_bus}')

# V_avg_ref from 0x482 B1-B2 LE / 117 * 1000 mV
f482 = [(f.timestamp, f.data) for f in frames
        if f.bus == pt_bus and f.arbitration_id == 0x482 and len(f.data) >= 3]
t_482 = [t for t, _ in f482]
v_avg_arr = [(d[1] + d[2]*256) / 117.0 * 1000 for _, d in f482]

def nearest_ref(ts):
    idx = bisect.bisect_left(t_482, ts)
    if idx == 0: return v_avg_arr[0]
    if idx >= len(t_482): return v_avg_arr[-1]
    return v_avg_arr[idx-1] if abs(t_482[idx-1]-ts) < abs(t_482[idx]-ts) else v_avg_arr[idx]

def regression(xs, ys):
    """Returns (r, slope, intercept, min_x, max_x) or all nan if insufficient data."""
    n = len(xs)
    if n < 30:
        return (float('nan'),) * 5
    xm = sum(xs) / n
    ym = sum(ys) / n
    cov  = sum((x - xm) * (y - ym) for x, y in zip(xs, ys))
    varx = sum((x - xm) ** 2 for x in xs)
    vary = sum((y - ym) ** 2 for y in ys)
    if varx == 0 or vary == 0:
        return (float('nan'),) * 5
    r         = cov / math.sqrt(varx * vary)
    slope     = cov / varx          # mV per count
    intercept = ym - slope * xm    # mV at count=0
    return r, slope, intercept, min(xs), max(xs)

# Group frames by ID on PT bus
print('Grouping frames...')
by_id = {}
for f in frames:
    if f.bus != pt_bus: continue
    by_id.setdefault(f.arbitration_id, []).append((f.timestamp, f.data))

PACK_VOLTAGE_IDS = {0x482, 0x470, 0x440}

results = []
print(f'Scanning {len(by_id)} IDs...')

for aid, flist in sorted(by_id.items()):
    step = max(1, len(flist) // 3000)
    flist_s = flist[::step]
    dlc = max(len(d) for _, d in flist_s)

    refs_all = [nearest_ref(ts) for ts, _ in flist_s]
    # Skip IDs where V_avg reference barely varies (e.g. constant-output or keyed-off periods)
    if len(set(int(rv * 10) for rv in refs_all)) < 5:
        continue

    for i in range(min(dlc, 8)):
        raw  = [d[i]         for _, d in flist_s if len(d) > i]
        refs = [refs_all[j]  for j, (_, d) in enumerate(flist_s) if len(d) > i]
        if len(raw) < 30: continue
        if len(set(raw)) < 5: continue

        r, slope, intercept, min_raw, max_raw = regression(raw, refs)
        if math.isnan(r): continue
        if abs(r) < 0.65: continue

        v_at_min = intercept + min_raw * slope
        v_at_max = intercept + max_raw * slope

        results.append(dict(
            r=r, slope=slope, intercept=intercept,
            aid=aid, sig=f'B{i}',
            mean_raw=sum(raw)/len(raw), mean_ref=sum(refs)/len(refs),
            n=len(raw),
            min_raw=int(min_raw), max_raw=int(max_raw),
            v_at_min=v_at_min, v_at_max=v_at_max,
            is_pkv=(aid in PACK_VOLTAGE_IDS),
        ))

results.sort(key=lambda x: -abs(x['r']))

HDR = (f'  {"ID":<12} {"Sig":<5} {"r":>8}  {"slope":>8}  {"intercept":>11}'
       f'  {"V@min":>7}  {"V@max":>7}  {"raw_range":>13}  {"n":>6}')
SEP = '-' * 112

def fmt(d):
    span = d['max_raw'] - d['min_raw']
    pkv  = ' [PKV]' if d['is_pkv'] else ''
    return (f'  0x{d["aid"]:08X}  {d["sig"]:<5}  {d["r"]:8.4f}  {d["slope"]:8.3f}'
            f'  {d["intercept"]:11.1f}  {d["v_at_min"]:7.0f}  {d["v_at_max"]:7.0f}'
            f'  {d["min_raw"]:3d}-{d["max_raw"]:3d} ({span:3d}cnt)  {d["n"]:6}{pkv}')

lines = []
lines.append('=== PT Bus Single-Byte Slope/Intercept Scan vs V_avg_ref ===')
lines.append('Reference: 0x482 B1-B2 LE / 117 * 1000 = V_avg_ref (mV)')
lines.append('Threshold: |r| > 0.65, all single bytes on PT bus')
lines.append(f'Candidates: {len(results)}')
lines.append('')
lines.append(HDR)
lines.append(SEP)
for d in results:
    lines.append(fmt(d))

lines.append('')
lines.append('=== Physical filter: plausible LFP single-byte cell voltage encoding ===')
lines.append('  |slope| in [1, 60] mV/cnt')
lines.append('  intercept in [-500, 4500] mV')
lines.append('  observed V range overlaps [1000, 5500] mV')
lines.append('  PKV IDs (0x482, 0x470, 0x440) excluded')
lines.append('')
lines.append(HDR)
lines.append(SEP)

for d in results:
    if d['is_pkv']: continue
    if not (1.0 <= abs(d['slope']) <= 60.0): continue
    if not (-500 <= d['intercept'] <= 4500): continue
    v_lo = min(d['v_at_min'], d['v_at_max'])
    v_hi = max(d['v_at_min'], d['v_at_max'])
    if v_hi < 1000 or v_lo > 5500: continue
    lines.append(fmt(d))

out = '\n'.join(lines)
print(out)
with open(OUT, 'w') as fh:
    fh.write(out)
print(f'\nSaved to {OUT}')
