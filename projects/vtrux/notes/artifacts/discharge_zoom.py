"""
discharge_zoom.py

Zoom into the heavy discharge event (t=595-610s) in the climit log.
For every relevant BMS byte, show the raw value and implied voltage
relative to V_avg at the same moment.

Purpose: directly identify which signals stay ABOVE V_avg (V_max candidates)
vs BELOW V_avg (V_min candidates) vs track V_avg (neither).

Also checks 0x63A in truk1log T0 to see if any byte encodes ~3400-3600 mV
(the 26 OV cells far above V_avg=3324 mV).
"""
import sys, os, bisect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

CLIMIT = os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                      'vtruxcurrentlimitingtest.log')
TRUK0  = os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
                      'truk1log_M1_T0.log')
OUT    = os.path.join(os.path.dirname(__file__), 'discharge_zoom_output.txt')

VPACK_SCALE = 0.0156
CELLS       = 117
ZOOM_START  = 590.0
ZOOM_END    = 620.0

# Regressions from find_vmax / previous bisect correlation (all vs V_avg)
REGS = {
    (0x410, 3): (1.569, 3052.3,  '0x410 B3 (temp?)'),
    (0x410, 4): (6.298, 2254.1,  '0x410 B4 (V_min)'),
    (0x410, 6): None,  # fault flag, skip
    (0x420, 3): (1.764, 2951.9,  '0x420 B3 (candidate)'),
    (0x440, 2): (6.105, 2285.1,  '0x440 B2 (V_min-like?)'),
    (0x440, 4): (33.30, 94.9,    '0x440 B4 (V_avg proxy)'),
}


def cum_ts(log_path, target_ids):
    """Collect (cum_t, id, data) for frames from target_ids."""
    out = []
    t_off, last_t = 0.0, None
    for frame in parse_file(log_path):
        t = frame.timestamp
        if last_t is not None and t < last_t - 1.0:
            t_off += last_t
        last_t = t
        ct = t + t_off
        if frame.arbitration_id in target_ids:
            out.append((ct, frame.arbitration_id, bytes(frame.data)))
    return out


def build_vavg(frames):
    ts, vs = [], []
    for ct, aid, data in frames:
        if aid == 0x440 and len(data) >= 5:
            le = data[3] + data[4] * 256
            vp = le * VPACK_SCALE
            if 200 < vp < 500:
                ts.append(ct)
                vs.append(vp / CELLS * 1000.0)
    return ts, vs


def nearest_vavg(ts_v, vs, t):
    pos = bisect.bisect_left(ts_v, t)
    best_j, best_dt = None, float('inf')
    for j in [pos-1, pos]:
        if 0 <= j < len(ts_v):
            dt = abs(ts_v[j] - t)
            if dt < best_dt:
                best_dt, best_j = dt, j
    return (vs[best_j] if best_j is not None else None)


def climit_zoom(lines):
    lines.append('=== Climit Discharge Zoom (t=595-610s) ===')
    lines.append('')

    ids = {0x410, 0x420, 0x440}
    frames = cum_ts(CLIMIT, ids)
    ts_v, vs_v = build_vavg(frames)

    # Print table header
    hdr = f'{"t":7s} {"ID":7s} {"Byte":5s} {"RawVal":7s} {"Pred_mV":8s} {"Vavg_mV":8s} {"Offset":8s}  Label'
    lines.append(hdr)
    lines.append('-' * len(hdr))

    zoom_frames = [(ct, aid, data) for ct, aid, data in frames
                   if ZOOM_START <= ct <= ZOOM_END and aid in (0x410, 0x420)]

    prev_t = -999
    for ct, aid, data in zoom_frames:
        vavg = nearest_vavg(ts_v, vs_v, ct)
        if vavg is None:
            continue
        # Print a blank line at each new second
        if int(ct) > int(prev_t):
            lines.append('')
        prev_t = ct

        for pos in range(len(data)):
            key = (aid, pos)
            if key not in REGS or REGS[key] is None:
                continue
            slope, intercept, label = REGS[key]
            bval = data[pos]
            pred = slope * bval + intercept
            offset = pred - vavg
            flag = ' <<< V_MAX?' if offset > 50 else (' <<< V_min?' if offset < -50 else '')
            lines.append(f'{ct:7.2f} 0x{aid:04X}  B{pos}    {bval:4d}    {pred:8.1f}  {vavg:8.1f}  '
                         f'{offset:+8.1f}  {label}{flag}')


def truk_63A(lines):
    lines.append('')
    lines.append('=== 0x63A in truk1log T0 (seeking V_max ~3400-3600 mV) ===')
    lines.append('')
    lines.append('Pack state: V_avg=3324 mV, V_min~3245 mV, V_max(OV cells)~3500-3600 mV')
    lines.append('')

    # Collect all 0x63A frames from truk T0
    frames_63a = [(ct, data)
                  for ct, aid, data in cum_ts(TRUK0, {0x63A})
                  if ct <= 200.0]  # first 200s sample

    if not frames_63a:
        lines.append('  No 0x63A frames found.')
        return

    # Stats per byte
    from statistics import mean, median, stdev
    n = len(frames_63a)
    byte_vals = [[] for _ in range(8)]
    for _, data in frames_63a:
        for i, b in enumerate(data[:8]):
            byte_vals[i].append(b)

    lines.append(f'Frames sampled: {n} (first 200s)')
    lines.append(f'{"Pos":4s} {"Min":5s} {"Max":5s} {"Median":7s} {"Mean":7s} {"Uniq":5s}  '
                 f'{"BE-pair prediction (x0.1 mV)":30s}  V_avg_ref=3324 mV')
    lines.append('-' * 90)
    for i, vals in enumerate(byte_vals):
        if not vals:
            continue
        uniq = len(set(vals))
        if uniq < 2:
            lines.append(f'  B{i}   {min(vals):4d}  {max(vals):4d}   {median(vals):6.1f}   '
                         f'{mean(vals):6.1f}   {uniq:3d}   (constant)')
            continue
        med = median(vals)
        # Show BE pair interpretation (adjacent bytes) if applicable
        be_note = ''
        if i < 7 and byte_vals[i+1]:
            be_val = int(med) * 256 + int(median(byte_vals[i+1]))
            be_mv  = be_val * 0.1
            offset = be_mv - 3324.3
            be_note = f'  B{i}-B{i+1} BE x0.1mV -> {be_mv:.0f} mV  ({offset:+.0f} mV vs V_avg)'
        lines.append(f'  B{i}   {min(vals):4d}  {max(vals):4d}   {med:6.1f}   '
                     f'{mean(vals):6.1f}   {uniq:3d}{be_note}')

    # Show sample frames
    lines.append('')
    lines.append('Sample 0x63A frames from truk1log T0:')
    for ct, data in frames_63a[:5]:
        lines.append(f'  t={ct:.2f}s  ' + ' '.join(f'{b:02X}' for b in data))
    lines.append('  ...')
    for ct, data in frames_63a[-5:]:
        lines.append(f'  t={ct:.2f}s  ' + ' '.join(f'{b:02X}' for b in data))


def main():
    lines = []
    print('Loading climit log...')
    climit_zoom(lines)
    print('Loading truk1log T0...')
    truk_63A(lines)

    output = '\n'.join(lines)
    print(output)
    with open(OUT, 'w') as f:
        f.write(output + '\n')
    print(f'\nOutput written to: {OUT}')


if __name__ == '__main__':
    main()
