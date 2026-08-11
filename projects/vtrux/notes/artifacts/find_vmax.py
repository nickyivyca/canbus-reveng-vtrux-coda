"""
find_vmax.py

V_max cell voltage search. Strategy:
  1. Build V_avg timeseries from 0x440 B3-B4 LE in the climit log.
  2. For every byte of every BMS-originated ID, fit a linear regression
     against V_avg (bisect-based timestamp matching).
  3. Report: r, slope, intercept, and -- crucially --
       mean_offset  = mean(predicted - V_avg)   (positive = above average = V_max candidate)
       disch_offset = mean(predicted - V_avg) filtered to heavy discharge windows
                      (V_avg < 3050 mV, i.e. pack voltage below ~357V)
  4. Sort by disch_offset descending. Signals that stay ABOVE V_avg during
     heavy discharge while having positive r are V_max candidates.
  5. Cross-check candidate bytes on the truk1log T0: if V_max, the value
     should read significantly above V_avg (3324 mV) -- the 26 OV cells
     are at 3.4-3.6 V, giving expected V_max gap of +276 mV.

Known reference:
  V_min = 0x410 B4   r=0.9071, slope=6.370 mV/cnt, intercept=2248 mV
  V_avg = V_pack / 117  (0x440 B3-B4 LE * 0.0156 / 117 * 1000 mV)

Usage:
  py -3.12 find_vmax.py
"""
import sys, os, bisect, statistics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

CLIMIT_LOG  = os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                            'vtruxcurrentlimitingtest.log')
TRUK_LOG    = os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                            'truk1log_M1_T0.log')
OUT_FILE    = os.path.join(os.path.dirname(__file__), 'find_vmax_output.txt')

# BMS-originated IDs to scan (confirmed BMS source)
BMS_IDS = [0x410, 0x412, 0x420, 0x430, 0x440, 0x460, 0x506, 0x507,
           0x63A, 0x63D]  # also 0x63A/0x63D as cell-cluster candidates

VPACK_SCALE = 0.0156    # V per count for 0x440 B3-B4 LE
CELLS       = 117
DISCH_THRESH_MV = 3050  # V_avg < this = heavy discharge window

# Known V_min for reference
VMIN_SLOPE = 6.370
VMIN_INTER = 2248.0


def pearson(xs, ys):
    n = len(xs)
    if n < 10:
        return 0.0, 0.0, 0.0
    mx, my = sum(xs)/n, sum(ys)/n
    sx = (sum((x-mx)**2 for x in xs)/n)**0.5
    sy = (sum((y-my)**2 for y in ys)/n)**0.5
    if sx < 1e-9 or sy < 1e-9:
        return 0.0, 0.0, 0.0
    r = sum((x-mx)*(y-my) for x,y in zip(xs,ys)) / (n*sx*sy)
    slope = r * sy / sx
    intercept = my - slope * mx
    return r, slope, intercept


def load_vavg(log_path):
    """Returns sorted (timestamps, vavg_mV) lists from 0x440 B3-B4 LE."""
    ts, vals = [], []
    t_offset, last_t = 0.0, None
    for frame in parse_file(log_path):
        t = frame.timestamp
        if last_t is not None and t < last_t - 1.0:
            t_offset += last_t
        last_t = t
        cum_t = t + t_offset
        if frame.arbitration_id == 0x440 and len(frame.data) >= 5:
            le = frame.data[3] + frame.data[4] * 256
            vp = le * VPACK_SCALE
            if 200 < vp < 500:   # sanity filter
                ts.append(cum_t)
                vals.append(vp / CELLS * 1000.0)
    return ts, vals


def nearest(ts_b, vals_b, t):
    pos = bisect.bisect_left(ts_b, t)
    best_j, best_dt = None, float('inf')
    for j in [pos-1, pos]:
        if 0 <= j < len(ts_b):
            dt = abs(ts_b[j] - t)
            if dt < best_dt:
                best_dt, best_j = dt, j
    return (vals_b[best_j], best_dt) if best_j is not None else (None, float('inf'))


def scan_log(log_path, ts_vavg, vals_vavg, max_dt=0.12):
    """
    For each (ID, byte_position), collect matched (byte_val, vavg_mV) pairs.
    Returns dict: (id_hex, byte_pos) -> {'xy': [(b,v),...]}
    """
    data = {}
    t_offset, last_t = 0.0, None
    for frame in parse_file(log_path):
        t = frame.timestamp
        if last_t is not None and t < last_t - 1.0:
            t_offset += last_t
        last_t = t
        cum_t = t + t_offset

        if frame.arbitration_id not in BMS_IDS:
            continue

        vavg, dt = nearest(ts_vavg, vals_vavg, cum_t)
        if vavg is None or dt > max_dt:
            continue

        for pos, bval in enumerate(frame.data):
            key = (frame.arbitration_id, pos)
            if key not in data:
                data[key] = []
            data[key].append((bval, vavg))

    return data


def analyze(data):
    results = []
    for (aid, pos), pairs in data.items():
        if len(pairs) < 200:
            continue
        bvals = [p[0] for p in pairs]
        vavgs = [p[1] for p in pairs]

        uniq = len(set(bvals))
        if uniq < 4:
            continue   # skip constant bytes

        r, slope, intercept = pearson(bvals, vavgs)
        if abs(r) < 0.30:
            continue   # skip uncorrelated bytes

        # Predicted cell voltage for this byte using its own regression
        # pred_mV = slope * b + intercept  (this maps b -> V_avg estimate)
        # But we want: byte's implied V_cell = a*b + c where a,c from physical calibration.
        # Since we don't know that, use the regression offset trick:
        # offset = (regression_prediction_at_b) - V_avg_at_same_time
        # For a perfect V_avg tracker: offset = 0
        # For V_min: offset < 0 (signal is below average)
        # For V_max: offset > 0 (signal is above average)
        #
        # If r > 0: predicted = slope*b + intercept
        #   predicted - V_avg = slope*b + intercept - V_avg
        #   At each matched pair: pred - vavg = slope*bval + intercept - vavg
        offsets     = [slope*b + intercept - v for b, v in pairs]
        disch_pairs = [(b, v) for b, v in pairs if v < DISCH_THRESH_MV]
        disch_off   = ([slope*b + intercept - v for b, v in disch_pairs]
                       if disch_pairs else [float('nan')])

        mean_off   = statistics.mean(offsets)
        disch_mean = statistics.mean(disch_off) if disch_off[0] == disch_off[0] else float('nan')
        n_disch    = len(disch_pairs)

        results.append({
            'id': aid, 'pos': pos,
            'r': r, 'slope': slope, 'intercept': intercept,
            'uniq': uniq, 'n': len(pairs),
            'mean_off': mean_off,
            'disch_off': disch_mean,
            'n_disch': n_disch,
            'bmin': min(bvals), 'bmax': max(bvals),
        })

    # Sort: positively-correlated first, then by disch_off descending
    pos_r = sorted([r for r in results if r['r'] > 0], key=lambda x: -x['disch_off'])
    neg_r = sorted([r for r in results if r['r'] < 0], key=lambda x:  x['disch_off'])
    return pos_r + neg_r


def truk_check(candidates, truk_log, ts_vavg_t, vals_vavg_t):
    """For top candidates, report their mean value in truk1log and implied offset vs truk V_avg."""
    # Collect per-ID byte means in truk1log
    byte_data = {}
    for frame in parse_file(truk_log):
        if frame.arbitration_id not in BMS_IDS:
            continue
        for pos, bval in enumerate(frame.data):
            key = (frame.arbitration_id, pos)
            if key not in byte_data:
                byte_data[key] = []
            byte_data[key].append(bval)

    truk_vavg = statistics.median(vals_vavg_t) if vals_vavg_t else float('nan')

    lines = []
    lines.append(f'\nTruk1log T0 cross-check (V_avg = {truk_vavg:.1f} mV):')
    lines.append(f'  {"ID":8s} {"B":3s} {"b_med":6s} {"pred_mV":8s} {"offset_mV":10s}  (pred uses climit regression)')
    lines.append('  ' + '-'*55)

    for cand in candidates[:20]:
        key = (cand['id'], cand['pos'])
        if key not in byte_data or len(byte_data[key]) < 10:
            continue
        b_med = statistics.median(byte_data[key])
        pred = cand['slope'] * b_med + cand['intercept']
        offset = pred - truk_vavg
        flag = ' <<< V_MAX?' if offset > 50 else (' <<< V_min?' if offset < -50 else '')
        lines.append(f'  0x{cand["id"]:04X}   B{cand["pos"]}  {b_med:6.1f}  {pred:8.1f}  {offset:+10.1f}{flag}')

    return '\n'.join(lines)


def main():
    lines = []
    lines.append('=== V_max Cell Voltage Search ===')
    lines.append(f'Climit log: {CLIMIT_LOG}')
    lines.append(f'Truk1log:   {TRUK_LOG}')
    lines.append('')

    print('Loading V_avg from climit 0x440...')
    ts_c, va_c = load_vavg(CLIMIT_LOG)
    lines.append(f'V_avg climit: {len(ts_c)} samples, range {min(va_c):.0f}-{max(va_c):.0f} mV')
    lines.append(f'Heavy discharge (V_avg < {DISCH_THRESH_MV} mV): '
                 f'{sum(1 for v in va_c if v < DISCH_THRESH_MV)} samples')
    lines.append('')

    print('Scanning climit BMS bytes...')
    raw = scan_log(CLIMIT_LOG, ts_c, va_c)
    results = analyze(raw)

    lines.append('--- Positive r, sorted by discharge offset (highest = most above V_avg during discharge) ---')
    lines.append(f'{"ID":8s} {"B":3s} {"r":7s} {"slope":8s} {"intercept":10s} '
                 f'{"mean_off":9s} {"disch_off":9s} {"n_disch":7s} {"uniq":5s}')
    lines.append('-' * 80)

    for res in results:
        sign = '+' if res['r'] > 0 else '-'
        doff = f'{res["disch_off"]:+8.1f}' if res['disch_off'] == res['disch_off'] else '     n/a'
        flag = ''
        if res['r'] > 0:
            if res['disch_off'] > 30:
                flag = ' <<< V_MAX?'
            elif res['disch_off'] < -30:
                flag = ' <<< V_min?'
        lines.append(f'0x{res["id"]:04X}  B{res["pos"]}  {res["r"]:+6.3f}  '
                     f'{res["slope"]:8.3f}  {res["intercept"]:10.1f}  '
                     f'{res["mean_off"]:+8.1f}  {doff}  {res["n_disch"]:7d}  '
                     f'{res["uniq"]:5d}{flag}')

    # Known reference
    lines.append('')
    lines.append('Known reference (from previous correlation):')
    lines.append('  0x410 B4  r=+0.9071  slope=6.370  intercept=2248  (V_min)')

    print('Loading truk1log T0 V_avg...')
    ts_t, va_t = load_vavg(TRUK_LOG)

    pos_candidates = [r for r in results if r['r'] > 0.4]
    lines.append(truk_check(pos_candidates, TRUK_LOG, ts_t, va_t))
    lines.append(f'\nTruk expected: V_avg={statistics.median(va_t):.1f} mV, '
                 f'V_max(OV cells)~3500-3600 mV (+176 to +276 mV offset)')

    output = '\n'.join(lines)
    print(output)
    with open(OUT_FILE, 'w') as f:
        f.write(output + '\n')
    print(f'\nOutput written to: {OUT_FILE}')


if __name__ == '__main__':
    main()
