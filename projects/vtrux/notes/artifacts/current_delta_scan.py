"""
current_delta_scan.py -- Scan PT bus bytes for correlation with |battery current|.

Cell voltage delta (V_max - V_min) grows with |I| because cells have different
internal resistances: V_delta ≈ |I| * delta_R. So any cell-spread/delta signal
should correlate positively with |I|.

Also: any cell voltage (min, max, avg) that changes with SOC will also correlate
with |I| during dynamic events, but with a different character (sign may flip
between charge/discharge, and correlation is weaker over the full log).

Current reference: 0x598 B0-B1 LE uint16, centered at 32768.
  I_raw = B0 + B1*256 - 32768   (positive = discharging)
  |I|   = abs(I_raw)             (what we correlate against)

Scale of 0x598 is 0.04 A/count (UNCONFIRMED) — we don't need actual amperes
for correlation purposes; raw counts work fine.

Threshold: |r| > 0.40  (delta signals may be weaker than voltage signals)

Output also shows the regression slope vs |I| for physical plausibility.
"""
import sys, bisect, math
sys.path.insert(0, '.')
from canre.parsers import parse_file

LOG = 'projects/vtrux/logs/vtruxcurrentlimitingtest.log'
OUT = 'projects/vtrux/notes/artifacts/current_delta_scan.txt'

print('Loading...', flush=True)
frames = list(parse_file(LOG))
bus_ids = {}
for f in frames:
    bus_ids.setdefault(f.bus, set()).add(f.arbitration_id)
pt_bus = next(b for b, ids in bus_ids.items() if 0x051 in ids)
print(f'PT bus = Bus {pt_bus}')

# Battery current reference: 0x598 B0-B1 LE, offset 32768
f598 = [(f.timestamp, f.data) for f in frames
        if f.bus == pt_bus and f.arbitration_id == 0x598 and len(f.data) >= 4]
if not f598:
    print('ERROR: 0x598 not found on PT bus')
    sys.exit(1)
t_598 = [t for t, _ in f598]
# I_raw (signed, positive=discharge), and |I| in raw counts
i_signed_arr = [d[0] + d[1]*256 - 32768 for _, d in f598]
iabs_arr     = [abs(v) for v in i_signed_arr]
print(f'  0x598: {len(f598)} frames, I_raw range: {min(i_signed_arr):.0f} to {max(i_signed_arr):.0f} counts')
print(f'  |I| range: {min(iabs_arr):.0f} to {max(iabs_arr):.0f} counts')

def nearest_iabs(ts):
    idx = bisect.bisect_left(t_598, ts)
    if idx == 0: return iabs_arr[0]
    if idx >= len(t_598): return iabs_arr[-1]
    return iabs_arr[idx-1] if abs(t_598[idx-1]-ts) < abs(t_598[idx]-ts) else iabs_arr[idx]

def nearest_isigned(ts):
    idx = bisect.bisect_left(t_598, ts)
    if idx == 0: return i_signed_arr[0]
    if idx >= len(t_598): return i_signed_arr[-1]
    return i_signed_arr[idx-1] if abs(t_598[idx-1]-ts) < abs(t_598[idx]-ts) else i_signed_arr[idx]

def regression(xs, ys):
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
    slope     = cov / varx
    intercept = ym - slope * xm
    return r, slope, intercept, min(xs), max(xs)

# Group frames by ID on PT bus
print('Grouping frames...')
by_id = {}
for f in frames:
    if f.bus != pt_bus: continue
    by_id.setdefault(f.arbitration_id, []).append((f.timestamp, f.data))

results_iabs   = []  # correlation vs |I|
results_isigned = []  # correlation vs I_signed (for sanity-checking sign)

THRESHOLD = 0.40
print(f'Scanning {len(by_id)} IDs vs |I| (threshold |r| > {THRESHOLD})...')

for aid, flist in sorted(by_id.items()):
    if aid == 0x598: continue   # skip the reference itself
    step = max(1, len(flist) // 3000)
    flist_s = flist[::step]
    dlc = max(len(d) for _, d in flist_s)

    iabs_ref  = [nearest_iabs(ts)    for ts, _ in flist_s]
    isign_ref = [nearest_isigned(ts) for ts, _ in flist_s]

    # Skip if |I| barely varies (mostly idle frames)
    if max(iabs_ref) - min(iabs_ref) < 100:
        continue

    for i in range(min(dlc, 8)):
        raw = [d[i] for _, d in flist_s if len(d) > i]
        ia  = [iabs_ref[j]  for j, (_, d) in enumerate(flist_s) if len(d) > i]
        isg = [isign_ref[j] for j, (_, d) in enumerate(flist_s) if len(d) > i]
        if len(raw) < 30: continue
        if len(set(raw)) < 5: continue

        r_abs, sl_abs, ic_abs, min_i, max_i = regression(ia, raw)
        r_sgn, sl_sgn, ic_sgn, _, _         = regression(isg, raw)
        if math.isnan(r_abs): continue
        if abs(r_abs) < THRESHOLD: continue

        results_iabs.append(dict(
            r=r_abs, r_signed=r_sgn,
            slope=sl_abs, intercept=ic_abs,
            aid=aid, sig=f'B{i}',
            mean_raw=sum(raw)/len(raw),
            n=len(raw),
            min_raw=int(min(raw)), max_raw=int(max(raw)),
        ))

results_iabs.sort(key=lambda x: -abs(x['r']))

HDR = (f'  {"ID":<12} {"Sig":<5} {"r_|I|":>8}  {"r_I":>7}  {"slope":>9}'
       f'  {"intercept":>10}  {"raw_range":>13}  {"n":>6}')
SEP = '-' * 100

lines = []
lines.append('=== PT Bus Single-Byte Correlation vs |Battery Current| ===')
lines.append('Reference: 0x598 B0-B1 LE - 32768 = I_battery (positive=discharge)')
lines.append('|I| = abs(I_battery).  slope units: raw_counts per |I|_count')
lines.append(f'Threshold: |r_|I|| > {THRESHOLD}')
lines.append(f'  0x598 I_raw range: {min(i_signed_arr):.0f} to {max(i_signed_arr):.0f} counts')
lines.append(f'  0x598 |I| range:   {min(iabs_arr):.0f} to {max(iabs_arr):.0f} counts')
lines.append(f'Candidates: {len(results_iabs)}')
lines.append('')
lines.append('Columns: r_|I| = correlation vs |I|,  r_I = correlation vs signed I')
lines.append('  r_|I| > 0 and r_I ~= 0: grows with current magnitude regardless of sign -> delta signal')
lines.append('  r_|I| > 0 and r_I > 0: grows with discharge current -> asymmetric')
lines.append('  r_|I| > 0 and r_I < 0: grows with regen current -> asymmetric')
lines.append('')
lines.append(HDR)
lines.append(SEP)

for d in results_iabs:
    span = d['max_raw'] - d['min_raw']
    lines.append(
        f'  0x{d["aid"]:08X}  {d["sig"]:<5}  {d["r"]:8.4f}  {d["r_signed"]:7.4f}'
        f'  {d["slope"]:9.5f}  {d["intercept"]:10.3f}'
        f'  {d["min_raw"]:3d}-{d["max_raw"]:3d} ({span:3d}cnt)  {d["n"]:6}'
    )

out = '\n'.join(lines)
print(out)
with open(OUT, 'w') as fh:
    fh.write(out)
print(f'\nSaved to {OUT}')
