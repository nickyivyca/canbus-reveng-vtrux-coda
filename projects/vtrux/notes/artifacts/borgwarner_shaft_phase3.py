"""
BorgWarner shaft encoder -- Phase 3: Scale calibration

Goals:
1. Find stable-speed windows (RPM variance < 5% over >= 5 s) and compute
   total counter displacement / total motor revolutions -> tight cnt/rev.
2. Infer encoder PPR (step size confirmed 2 counts/pulse -> PPR = cnt/rev / 2).
3. Check whether Coda B1 also takes only even values, or all values.

Vtrux motor RPM: 0x5A2 B2-B3 LE uint16 centered at 32768
Coda motor speed: 0x1C0 B6-B7 LE uint16, scale 0.5, offset -16064
Counter: 0x308 B1-B2 LE uint16, zero=32128 (0x7D80)
Vtrux counter update rate: 10 Hz (same value broadcast 10x at 100 Hz)
"""
import sys, statistics, bisect
sys.path.insert(0, '.')
from canre.parsers.autodetect import parse_file

ID_308 = 0x308
ID_5A2 = 0x5A2
ID_1C0 = 0x1C0
COUNTER_ZERO = 32128

def counter_val(f):
    return (f.data[2] << 8) | f.data[1]

def trac_rpm(f):
    return ((f.data[3] << 8) | f.data[2]) - 32768

def coda_rpm(f):
    return ((f.data[7] << 8) | f.data[6]) * 0.5 - 16064.0

def nearest_val(ts_list, val_list, t, max_dt=0.15):
    i = bisect.bisect_left(ts_list, t)
    best, best_dt = None, max_dt
    for j in (i - 1, i):
        if 0 <= j < len(ts_list):
            dt = abs(ts_list[j] - t)
            if dt < best_dt:
                best_dt = dt
                best = val_list[j]
    return best


def stable_speed_ratio(path, is_coda, min_rpm=500, rpm_var_pct=5.0, window_s=5.0, stride_s=1.0):
    """
    Slide a window of window_s seconds across the log.
    In each window where RPM is stable (stdev/mean < rpm_var_pct/100 and mean > min_rpm),
    compute total counter displacement / total motor revolutions.
    Returns list of (mean_rpm, cnt_per_rev, window_start_t) tuples.
    """
    frames_308, frames_rpm = [], []
    for f in parse_file(path):
        if f.arbitration_id == ID_308:
            frames_308.append(f)
        elif f.arbitration_id == (ID_1C0 if is_coda else ID_5A2):
            frames_rpm.append(f)
    if not frames_308 or not frames_rpm:
        return []

    rpm_ts = [f.timestamp for f in frames_rpm]
    rpm_vs = [coda_rpm(f) if is_coda else trac_rpm(f) for f in frames_rpm]

    t0 = frames_308[0].timestamp
    t_end = frames_308[-1].timestamp
    results = []
    t_win = t0
    while t_win + window_s <= t_end:
        win_308 = [f for f in frames_308 if t_win <= f.timestamp <= t_win + window_s and f.data[0] == 0x40]
        if len(win_308) < 5:
            t_win += stride_s
            continue
        rpms_in_win = [nearest_val(rpm_ts, rpm_vs, f.timestamp) for f in win_308]
        rpms_in_win = [r for r in rpms_in_win if r is not None]
        if len(rpms_in_win) < 5:
            t_win += stride_s
            continue
        mean_rpm = statistics.mean(rpms_in_win)
        if abs(mean_rpm) < min_rpm:
            t_win += stride_s
            continue
        stdev_rpm = statistics.stdev(rpms_in_win)
        if stdev_rpm / abs(mean_rpm) > rpm_var_pct / 100.0:
            t_win += stride_s
            continue
        update_events = [(win_308[i-1], win_308[i]) for i in range(1, len(win_308))
                         if counter_val(win_308[i]) != counter_val(win_308[i-1])]
        if len(update_events) < 3:
            t_win += stride_s
            continue
        dcs = [counter_val(b) - counter_val(a) for a, b in update_events]
        park_reset_threshold = 500
        if any(abs(d) > park_reset_threshold for d in dcs):
            t_win += stride_s
            continue
        net_dc = counter_val(win_308[-1]) - counter_val(win_308[0])
        dt_total = win_308[-1].timestamp - win_308[0].timestamp
        total_revs = abs(mean_rpm) / 60.0 * dt_total
        if total_revs < 1.0:
            t_win += stride_s
            continue
        cnt_per_rev = abs(net_dc) / total_revs
        results.append((abs(mean_rpm), cnt_per_rev, t_win))
        t_win += stride_s
    return results


def b1_parity_check(path, label):
    frames = [f for f in parse_file(path) if f.arbitration_id == ID_308]
    b1_vals = [f.data[1] for f in frames]
    odd_count = sum(1 for v in b1_vals if v % 2 != 0)
    even_count = sum(1 for v in b1_vals if v % 2 == 0)
    print(f"  {label}: B1 even={even_count} ({100*even_count/len(b1_vals):.1f}%)  "
          f"odd={odd_count} ({100*odd_count/len(b1_vals):.1f}%)")


print("=" * 70)
print("PHASE 3A: STABLE-SPEED COUNTS/REV (Vtrux)")
print("=" * 70)

vtrux_results = stable_speed_ratio(
    'projects/vtrux/logs/vtruxevapdrivelog4.log', is_coda=False,
    min_rpm=500, rpm_var_pct=5.0, window_s=5.0, stride_s=1.0
)
if vtrux_results:
    cprs = [r[1] for r in vtrux_results]
    rpms = [r[0] for r in vtrux_results]
    print(f"  Windows found: {len(vtrux_results)}")
    print(f"  RPM range across windows: {min(rpms):.0f} - {max(rpms):.0f}")
    print(f"  cnt/rev: mean={statistics.mean(cprs):.2f}  median={statistics.median(cprs):.2f}  "
          f"stdev={statistics.stdev(cprs):.2f}  min={min(cprs):.2f}  max={max(cprs):.2f}")
    print(f"  Implied PPR (step=2): mean={statistics.mean(cprs)/2:.1f}  median={statistics.median(cprs)/2:.1f}")
    print(f"\n  Sample windows (first 15):")
    print(f"  {'t_win':>7}  {'RPM':>6}  {'cnt/rev':>8}  {'PPR':>5}")
    for rpm, cpr, t in sorted(vtrux_results, key=lambda x: x[2])[:15]:
        print(f"  {t:7.1f}s  {rpm:6.0f}  {cpr:8.2f}  {cpr/2:5.1f}")
else:
    print("  No stable-speed windows found.")

print("\n" + "=" * 70)
print("PHASE 3B: STABLE-SPEED COUNTS/REV (Coda)")
print("=" * 70)

coda_results = stable_speed_ratio(
    'projects/coda/logs/frombonnydoon.log', is_coda=True,
    min_rpm=500, rpm_var_pct=5.0, window_s=5.0, stride_s=1.0
)
if coda_results:
    cprs = [r[1] for r in coda_results]
    rpms = [r[0] for r in coda_results]
    print(f"  Windows found: {len(coda_results)}")
    print(f"  RPM range across windows: {min(rpms):.0f} - {max(rpms):.0f}")
    print(f"  cnt/rev: mean={statistics.mean(cprs):.2f}  median={statistics.median(cprs):.2f}  "
          f"stdev={statistics.stdev(cprs):.2f}  min={min(cprs):.2f}  max={max(cprs):.2f}")
    print(f"  Implied PPR (step=2): mean={statistics.mean(cprs)/2:.1f}  median={statistics.median(cprs)/2:.1f}")
    print(f"\n  Sample windows (first 15):")
    print(f"  {'t_win':>8}  {'RPM':>6}  {'cnt/rev':>8}  {'PPR':>5}")
    for rpm, cpr, t in sorted(coda_results, key=lambda x: x[2])[:15]:
        print(f"  {t:8.1f}s  {rpm:6.0f}  {cpr:8.2f}  {cpr/2:5.1f}")
else:
    print("  No stable-speed windows found.")

print("\n" + "=" * 70)
print("PHASE 3C: B1 PARITY CHECK (even-only or all values?)")
print("=" * 70)
b1_parity_check('projects/vtrux/logs/vtruxevapdrivelog4.log', 'Vtrux evap')
b1_parity_check('projects/coda/logs/frombonnydoon.log', 'Coda frombonnydoon')
b1_parity_check('projects/coda/logs/codadriveslowturnonwithdefroster2.log', 'Coda slowturnon2')
