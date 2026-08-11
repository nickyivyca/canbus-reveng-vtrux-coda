"""
voltage_corr_windows.py -- Broad voltage-correlation sweep during dynamic windows.

Scans ALL IDs on the PT bus (all single bytes + adjacent 16-bit pairs LE and BE) against
the Bel DCDC HV input voltage (0x18FFD6B3 B4-B5 LE x0.05) within two windows:
  Window A -- Regen limiting:    t=401-503s
  Window B -- Discharge limiting: t=598-700s

Reports all entries with |r| >= 0.70 in either window, sorted by |r| descending.
Results split into BMS-originated vs non-BMS-originated; known signals flagged.
"""
import sys, bisect, math, csv
sys.path.insert(0, '.')
from canre.parsers import parse_file

LOG     = 'projects/vtrux/logs/vtruxcurrentlimitingtest.log'
OUT_TXT = 'projects/vtrux/notes/artifacts/voltage_corr_windows.txt'
OUT_CSV = 'projects/vtrux/notes/artifacts/voltage_corr_windows.csv'

WINDOWS = {
    'A_regen':     (401.0, 503.0),
    'B_discharge': (598.0, 700.0),
}
THRESHOLD = 0.70
MIN_N     = 20

# Known BMS-originated IDs (disappear when HV battery LV connector unplugged)
BMS_IDS = {0x410, 0x412, 0x420, 0x430, 0x440, 0x460, 0x506, 0x507}
BMS_IDS |= set(range(0x639, 0x64C))   # 0x639-0x64B inclusive

# Known voltage signals (id, field_str) -> description
KNOWN = {
    (0x18FFD6B3, 'B4-B5_LE'): 'DCDC HV input (reference)',
    (0x482,      'B1-B2_LE'): 'Pack voltage 1V/cnt r=0.9974',
    (0x470,      'B1-B2_LE'): 'Pack voltage 1V/cnt (GMLAN mirror) r=0.9974',
    (0x440,      'B3-B4_LE'): 'Pack voltage 0.0156V/cnt r=0.9818',
    (0x410,      'B4'):       'V_min candidate r=0.9071',
    (0x0870A047, 'B2'):       'Low-res HV bus voltage (ruled out as per-cell)',
}

# ---- helpers ----------------------------------------------------------------

def pearson(xs, ys):
    """Return (r, slope [ref/cnt], intercept [ref units at cnt=0]) or all nan."""
    n = len(xs)
    if n < MIN_N:
        return float('nan'), float('nan'), float('nan')
    xm = sum(xs) / n
    ym = sum(ys) / n
    cov  = sum((x - xm) * (y - ym) for x, y in zip(xs, ys))
    varx = sum((x - xm) ** 2 for x in xs)
    vary = sum((y - ym) ** 2 for y in ys)
    if varx < 1e-12 or vary < 1e-12:
        return float('nan'), float('nan'), float('nan')
    r         = cov / math.sqrt(varx * vary)
    slope     = cov / varx
    intercept = ym - slope * xm
    return r, slope, intercept

def nearest(ts_sorted, vals, t):
    idx = bisect.bisect_left(ts_sorted, t)
    if idx == 0:       return vals[0]
    if idx >= len(ts_sorted): return vals[-1]
    if abs(ts_sorted[idx-1] - t) <= abs(ts_sorted[idx] - t):
        return vals[idx-1]
    return vals[idx]

# ---- load log ---------------------------------------------------------------
print('Loading log...', flush=True)
frames = list(parse_file(LOG))
print(f'  {len(frames):,} frames total')

bus_ids = {}
for f in frames:
    bus_ids.setdefault(f.bus, set()).add(f.arbitration_id)
pt_bus = next(b for b, ids in bus_ids.items() if 0x051 in ids)
print(f'  PT bus = Bus {pt_bus}')

# ---- build DCDC reference for each window -----------------------------------
DCDC_ID = 0x18FFD6B3
ref_ts   = {w: [] for w in WINDOWS}
ref_vals = {w: [] for w in WINDOWS}

for f in frames:
    if f.arbitration_id != DCDC_ID or len(f.data) < 6:
        continue
    volts = (f.data[4] + f.data[5] * 256) * 0.05
    for wname, (t0, t1) in WINDOWS.items():
        if t0 <= f.timestamp <= t1:
            ref_ts[wname].append(f.timestamp)
            ref_vals[wname].append(volts)

for wname in WINDOWS:
    n = len(ref_ts[wname])
    if n == 0:
        print(f'  WARNING: no DCDC reference frames in window {wname}')
        continue
    vlo = min(ref_vals[wname])
    vhi = max(ref_vals[wname])
    std = (sum((v - sum(ref_vals[wname])/n)**2 for v in ref_vals[wname])/n)**0.5
    print(f'  DCDC ref {wname}: {n} samples, {vlo:.1f}-{vhi:.1f} V, stddev={std:.2f} V')

# ---- bucket PT bus frames by window -----------------------------------------
print('Bucketing PT bus frames...', flush=True)
buckets = {}   # (aid, wname) -> [(timestamp, data)]
for f in frames:
    if f.bus != pt_bus:
        continue
    for wname, (t0, t1) in WINDOWS.items():
        if t0 <= f.timestamp <= t1:
            buckets.setdefault((f.arbitration_id, wname), []).append(
                (f.timestamp, bytes(f.data))
            )

unique_ids = {k[0] for k in buckets}
print(f'  {len(unique_ids)} unique IDs seen in windows')

# ---- scan -------------------------------------------------------------------
results = []

for (aid, wname), flist in sorted(buckets.items()):
    if wname not in ref_ts or len(ref_ts[wname]) < MIN_N:
        continue

    rts  = ref_ts[wname]
    rvs  = ref_vals[wname]
    ref_std = (sum((v - sum(rvs)/len(rvs))**2 for v in rvs)/len(rvs))**0.5
    if ref_std < 0.05:   # reference barely moving in this window -- skip
        continue

    dlc = max(len(d) for _, d in flist)

    # Build matched reference for each frame in this window
    ref_m = [nearest(rts, rvs, ts) for ts, _ in flist]

    def try_field(raw_vals, field_name):
        """raw_vals: list of int|None, same length as flist."""
        paired = [(raw_vals[i], ref_m[i])
                  for i in range(len(flist))
                  if raw_vals[i] is not None]
        if len(paired) < MIN_N:
            return
        xs = [p[0] for p in paired]
        ys = [p[1] for p in paired]
        if len(set(xs)) < 3:
            return
        r, slope, intercept = pearson(xs, ys)
        if math.isnan(r) or abs(r) < THRESHOLD:
            return
        results.append(dict(
            aid=aid, field=field_name, window=wname,
            r=r, slope=slope, intercept=intercept,
            n=len(paired),
            is_bms=aid in BMS_IDS,
            known=KNOWN.get((aid, field_name), ''),
        ))

    # Single bytes
    for i in range(min(dlc, 8)):
        raw = [d[i] if len(d) > i else None for _, d in flist]
        try_field(raw, f'B{i}')

    # Adjacent 16-bit pairs, LE and BE
    for i in range(min(dlc - 1, 7)):
        raw_le = [d[i] + d[i+1]*256 if len(d) > i+1 else None for _, d in flist]
        raw_be = [d[i]*256 + d[i+1]  if len(d) > i+1 else None for _, d in flist]
        try_field(raw_le, f'B{i}-B{i+1}_LE')
        try_field(raw_be, f'B{i}-B{i+1}_BE')

results.sort(key=lambda x: -abs(x['r']))
print(f'  {len(results)} candidates found (|r| >= {THRESHOLD})')

# ---- format text output -----------------------------------------------------
lines = []
lines.append('=== Voltage Correlation Window Sweep ===')
lines.append(f'Log: {LOG}')
lines.append('Reference: 0x18FFD6B3 B4-B5 LE x0.05 (Bel DCDC HV input voltage)')
lines.append(f'Threshold: |r| >= {THRESHOLD},  min_n = {MIN_N}')
lines.append('')
lines.append('Windows:')
for wname, (t0, t1) in WINDOWS.items():
    n = len(ref_ts.get(wname, []))
    lines.append(f'  {wname}: t={t0:.0f}-{t1:.0f}s  ({n} DCDC ref samples)')
lines.append('')

total  = len(results)
n_bms  = sum(1 for r in results if r['is_bms'])
lines.append(f'Total candidates: {total}  (BMS-originated: {n_bms},  non-BMS: {total-n_bms})')
lines.append('')

HDR = (f'  {"ID":<14} {"Field":<14} {"Win":<14} {"r":>8}  '
       f'{"slope":>10}  {"intercept":>10}  {"n":>6}')
SEP = '-' * 100

for is_bms, label in [(True, 'BMS-ORIGINATED'), (False, 'NON-BMS-ORIGINATED')]:
    subset = [d for d in results if d['is_bms'] == is_bms]
    if not subset:
        continue
    lines.append(f'--- {label} ({len(subset)} entries) ---')
    lines.append(HDR)
    lines.append(SEP)
    prev_aid = None
    for d in subset:
        if d['aid'] != prev_aid and prev_aid is not None:
            lines.append('')
        prev_aid = d['aid']
        known_tag = f'  [KNOWN: {d["known"]}]' if d['known'] else ''
        lines.append(
            f'  0x{d["aid"]:08X}  {d["field"]:<14} {d["window"]:<14} '
            f'{d["r"]:8.4f}  {d["slope"]:10.5f}  {d["intercept"]:10.2f}  '
            f'{d["n"]:6}{known_tag}'
        )
    lines.append('')

txt = '\n'.join(lines)
print('\n' + txt)

with open(OUT_TXT, 'w', encoding='ascii', errors='replace') as fh:
    fh.write(txt)
print(f'Saved: {OUT_TXT}')

# ---- CSV output -------------------------------------------------------------
with open(OUT_CSV, 'w', newline='', encoding='ascii') as fh:
    writer = csv.DictWriter(fh, fieldnames=[
        'aid_hex', 'field', 'window', 'r', 'slope', 'intercept', 'n', 'is_bms', 'known'
    ])
    writer.writeheader()
    for d in results:
        writer.writerow({
            'aid_hex':   f'0x{d["aid"]:08X}',
            'field':     d['field'],
            'window':    d['window'],
            'r':         f'{d["r"]:.6f}',
            'slope':     f'{d["slope"]:.6f}',
            'intercept': f'{d["intercept"]:.4f}',
            'n':         d['n'],
            'is_bms':    d['is_bms'],
            'known':     d['known'],
        })
print(f'Saved: {OUT_CSV}')
