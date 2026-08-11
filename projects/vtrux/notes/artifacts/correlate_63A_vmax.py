"""
correlate_63A_vmax.py

Verify that 0x63A B1-B2 LE * 0.1 mV = V_max cell voltage.

Approach:
  1. Load V_avg timeseries from climit_0x440_vpack_LE.csv
     (raw LE int * 0.0156 V / 117 cells * 1000 mV/V)
  2. Load 0x63A B1-B2 LE from climit_0x63A_B12_LE.csv
     (raw LE int * 0.1 mV = candidate V_max)
  3. Bisect-match timestamps, compute Pearson r and offset stats.
  4. Compare discharge window (V_avg < 3050 mV) behaviour vs V_min.

Expected: r > 0, mean offset > 0 (signal above V_avg), smaller
divergence from V_avg than V_min (0x410 B4, slope=6.370, intercept=2248).
"""
import csv, bisect, statistics, os

ARTIFACTS = os.path.dirname(__file__)
VPACK_CSV = os.path.join(ARTIFACTS, 'climit_0x440_vpack_LE.csv')
VMAX_CSV  = os.path.join(ARTIFACTS, 'climit_0x63A_B12_LE.csv')
VMIN_CSV  = os.path.join(ARTIFACTS, 'climit_0x410_B4.csv')
OUT       = os.path.join(ARTIFACTS, 'correlate_63A_vmax_output.txt')

VPACK_SCALE = 0.0156   # V per count
CELLS       = 117
VMAX_SCALE  = 0.1      # mV per count
VMIN_SLOPE  = 6.370
VMIN_INTER  = 2248.0
DISCH_THRESH = 3050.0  # mV -- heavy discharge window


def load_csv(path):
    ts, vals = [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            ts.append(float(row['timestamp']))
            vals.append(float(row['value']))
    return ts, vals


def nearest(ts_ref, vals_ref, t, max_dt=0.15):
    pos = bisect.bisect_left(ts_ref, t)
    best_j, best_dt = None, float('inf')
    for j in [pos - 1, pos]:
        if 0 <= j < len(ts_ref):
            dt = abs(ts_ref[j] - t)
            if dt < best_dt:
                best_dt, best_j = dt, j
    if best_j is not None and best_dt <= max_dt:
        return vals_ref[best_j]
    return None


def pearson(xs, ys):
    n = len(xs)
    if n < 10:
        return 0.0, 0.0, 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sx = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
    if sx < 1e-9 or sy < 1e-9:
        return 0.0, 0.0, 0.0
    r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n * sx * sy)
    slope = r * sy / sx
    intercept = my - slope * mx
    return r, slope, intercept


def main():
    lines = []
    lines.append('=== 0x63A B1-B2 LE * 0.1 mV as V_max -- Correlation Check ===')
    lines.append('')

    ts_vp, raw_vp = load_csv(VPACK_CSV)
    ts_vm, raw_vm = load_csv(VMAX_CSV)
    ts_b4, raw_b4 = load_csv(VMIN_CSV)

    vavg_ts  = ts_vp
    vavg_mv  = [v * VPACK_SCALE / CELLS * 1000.0 for v in raw_vp]

    lines.append(f'V_avg (0x440): n={len(vavg_mv)}, '
                 f'range {min(vavg_mv):.0f}-{max(vavg_mv):.0f} mV')
    lines.append(f'V_max cand (0x63A B1-B2 LE): n={len(ts_vm)} raw samples')
    lines.append('')

    # --- Match 0x63A against V_avg ---
    pairs_vm = []  # (vmax_mv, vavg_mv)
    for t, rv in zip(ts_vm, raw_vm):
        va = nearest(vavg_ts, vavg_mv, t)
        if va is None:
            continue
        pairs_vm.append((rv * VMAX_SCALE, va))

    lines.append(f'Matched pairs (0x63A vs V_avg): {len(pairs_vm)}')
    if not pairs_vm:
        lines.append('ERROR: no matched pairs')
        print('\n'.join(lines))
        return

    xs_vm = [p[0] for p in pairs_vm]
    ys_vm = [p[1] for p in pairs_vm]
    offsets_vm = [x - y for x, y in pairs_vm]

    r_vm, slope_vm, intercept_vm = pearson(xs_vm, ys_vm)
    mean_off_vm = statistics.mean(offsets_vm)

    disch_vm = [(x, y) for x, y in pairs_vm if y < DISCH_THRESH]
    disch_off_vm = statistics.mean(x - y for x, y in disch_vm) if disch_vm else float('nan')

    lines.append(f'  Pearson r vs V_avg     : {r_vm:+.4f}')
    lines.append(f'  slope (mV/mV)          : {slope_vm:.4f}  intercept: {intercept_vm:.1f} mV')
    lines.append(f'  Mean offset (V_max-V_avg): {mean_off_vm:+.1f} mV')
    lines.append(f'  Discharge offset (<3050): {disch_off_vm:+.1f} mV  (n={len(disch_vm)})')
    lines.append(f'  V_max range            : {min(xs_vm):.0f} - {max(xs_vm):.0f} mV')
    lines.append(f'  V_max mean             : {statistics.mean(xs_vm):.1f} mV')
    lines.append('')

    # --- Match 0x410 B4 (V_min) for comparison ---
    pairs_b4 = []
    for t, rv in zip(ts_b4, raw_b4):
        va = nearest(vavg_ts, vavg_mv, t)
        if va is None:
            continue
        vmin_est = VMIN_SLOPE * rv + VMIN_INTER
        pairs_b4.append((vmin_est, va))

    if pairs_b4:
        offsets_b4 = [x - y for x, y in pairs_b4]
        mean_off_b4 = statistics.mean(offsets_b4)
        disch_b4 = [(x, y) for x, y in pairs_b4 if y < DISCH_THRESH]
        disch_off_b4 = statistics.mean(x - y for x, y in disch_b4) if disch_b4 else float('nan')
        lines.append(f'V_min (0x410 B4, via regression) for comparison:')
        lines.append(f'  Mean offset (V_min-V_avg): {mean_off_b4:+.1f} mV')
        lines.append(f'  Discharge offset (<3050) : {disch_off_b4:+.1f} mV  (n={len(disch_b4)})')
        lines.append('')

    # --- Discharge event zoom: show 0x63A and V_min side by side ---
    lines.append('Discharge event zoom (t=595-610s):')
    lines.append(f'  {"t":7s}  {"V_max_mV":9s}  {"V_avg_mV":9s}  {"V_max-Vavg":11s}  '
                 f'{"V_min_mV":9s}  {"V_min-Vavg":11s}')
    lines.append('  ' + '-' * 68)

    t_start, t_end = 590.0, 620.0
    # Precompute V_avg at t for range
    zoom_vmax = [(t, rv * VMAX_SCALE) for t, rv in zip(ts_vm, raw_vm)
                 if t_start <= t <= t_end]
    zoom_b4   = [(t, rv) for t, rv in zip(ts_b4, raw_b4)
                 if t_start <= t <= t_end]

    prev_s = -1
    for t, vmax in zoom_vmax[::3]:  # sample every 3rd to avoid clutter
        va = nearest(vavg_ts, vavg_mv, t)
        if va is None:
            continue
        # find nearest B4 for same time
        pos = bisect.bisect_left([r[0] for r in zoom_b4], t)
        vmin = None
        for j in [pos - 1, pos]:
            if 0 <= j < len(zoom_b4):
                if abs(zoom_b4[j][0] - t) < 0.2:
                    vmin = VMIN_SLOPE * zoom_b4[j][1] + VMIN_INTER
                    break
        vmin_s = f'{vmin:9.1f}  {vmin - va:+10.1f}' if vmin is not None else '      n/a        n/a'
        if int(t) > prev_s:
            lines.append('')
            prev_s = int(t)
        lines.append(f'  {t:7.2f}  {vmax:9.1f}  {va:9.1f}  {vmax - va:+10.1f}  {vmin_s}')

    output = '\n'.join(lines)
    print(output)
    with open(OUT, 'w') as f:
        f.write(output + '\n')
    print(f'\nOutput written to: {OUT}')


if __name__ == '__main__':
    main()
