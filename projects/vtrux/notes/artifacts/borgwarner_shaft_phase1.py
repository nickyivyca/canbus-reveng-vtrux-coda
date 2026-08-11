"""
BorgWarner shaft sensor investigation -- Phase 1: Signal characterization
0x308 B1 vs confirmed motor RPM (0x5A2 B2-B3).

Goals:
- Characterize at-Park vs at-speed B1 values
- Check if B1 is ever zero
- Compute r vs motor RPM
- Check TC neutral window in tc test log (Phase 2 preview)
"""
import sys, statistics
sys.path.insert(0, '.')
from canre.parsers.autodetect import parse_file

LOGS = {
    'driveway':    'projects/vtrux/logs/movingaroundindriveway.log',
    'gen_on_off':  'projects/vtrux/logs/generator on then off.log',
    'tc_test':     'projects/vtrux/logs/vtrux_transfer_case_test.log',
}

ID_308 = 0x308
ID_5A2 = 0x5A2

def rpm_5a2(frame):
    b2, b3 = frame.data[2], frame.data[3]
    return ((b3 << 8) | b2) - 32768

import bisect

def nearest(ts_list, val_list, t, max_dt=0.1):
    i = bisect.bisect_left(ts_list, t)
    best = None
    best_dt = max_dt
    for j in (i - 1, i):
        if 0 <= j < len(ts_list):
            dt = abs(ts_list[j] - t)
            if dt < best_dt:
                best_dt = dt
                best = val_list[j]
    return best

def analyze(label, path):
    print(f'\n{"="*60}')
    print(f'LOG: {label}  ({path})')
    print('='*60)
    frames_308 = []
    frames_5a2 = []
    try:
        for f in parse_file(path):
            if f.arbitration_id == ID_308:
                frames_308.append(f)
            elif f.arbitration_id == ID_5A2:
                frames_5a2.append(f)
    except Exception as e:
        print(f'  ERROR: {e}')
        return

    if not frames_308:
        print('  No 0x308 frames')
        return
    if not frames_5a2:
        print('  No 0x5A2 frames')

    rpm_ts_t = [f.timestamp for f in frames_5a2]
    rpm_ts_v = [rpm_5a2(f) for f in frames_5a2]

    print(f'\n  0x308 frames: {len(frames_308)}, span {frames_308[0].timestamp:.1f}-{frames_308[-1].timestamp:.1f}s')
    print(f'  0x5A2 frames: {len(frames_5a2)}')

    b1_vals = [f.data[1] for f in frames_308]
    print(f'\n  B1 overall: min={min(b1_vals)}  max={max(b1_vals)}  '
          f'mean={statistics.mean(b1_vals):.1f}  zeros={b1_vals.count(0)}')

    park_b1 = []
    notpark_b1 = []
    for f in frames_308:
        pin = f.data[0]
        b1 = f.data[1]
        if pin == 0x20:
            park_b1.append(b1)
        elif pin == 0x40:
            notpark_b1.append(b1)

    if park_b1:
        print(f'\n  B1 when Park pin locked (0x20): n={len(park_b1)}  '
              f'min={min(park_b1)}  max={max(park_b1)}  mean={statistics.mean(park_b1):.2f}')
    if notpark_b1:
        print(f'  B1 when Park pin released (0x40): n={len(notpark_b1)}  '
              f'min={min(notpark_b1)}  max={max(notpark_b1)}  mean={statistics.mean(notpark_b1):.2f}')

    if rpm_ts:
        pairs = []
        for f in frames_308:
            rpm = nearest(rpm_ts_t, rpm_ts_v, f.timestamp)
            if rpm is not None:
                pairs.append((f.data[1], rpm))

        if len(pairs) > 10:
            b1s = [p[0] for p in pairs]
            rpms = [p[1] for p in pairs]
            n = len(pairs)
            mb1 = statistics.mean(b1s)
            mrpm = statistics.mean(rpms)
            cov = sum((b - mb1) * (r - mrpm) for b, r in pairs) / n
            sb1 = statistics.pstdev(b1s)
            srpm = statistics.pstdev(rpms)
            r_val = cov / (sb1 * srpm) if sb1 > 0 and srpm > 0 else float('nan')
            print(f'\n  Pearson r(B1, motor_RPM): {r_val:.4f}  (n={n})')

            zero_rpm_b1 = [b for b, r in pairs if abs(r) < 10]
            if zero_rpm_b1:
                print(f'  B1 when motor RPM ~0 (abs<10): n={len(zero_rpm_b1)}  '
                      f'mean={statistics.mean(zero_rpm_b1):.2f}  '
                      f'min={min(zero_rpm_b1)}  max={max(zero_rpm_b1)}')

    print(f'\n  B1 transitions (unique consecutive values):')
    prev = None
    count = 0
    for f in frames_308:
        b1 = f.data[1]
        pin = f.data[0]
        if b1 != prev:
            rpm_here = nearest(rpm_ts_t, rpm_ts_v, f.timestamp) if rpm_ts else None
            rpm_str = f'  RPM={rpm_here:+6d}' if rpm_here is not None else ''
            pin_str = 'Park' if pin == 0x20 else ('NotPark' if pin == 0x40 else f'0x{pin:02X}')
            print(f'    t={f.timestamp:7.2f}s  B1={b1:3d}  pin={pin_str}{rpm_str}')
            prev = b1
            count += 1
            if count >= 40:
                print('    ... (truncated)')
                break

analyze('driveway', LOGS['driveway'])
analyze('gen_on_off', LOGS['gen_on_off'])
analyze('tc_test', LOGS['tc_test'])
