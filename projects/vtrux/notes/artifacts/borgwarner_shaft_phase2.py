"""
BorgWarner shaft encoder investigation -- Phase 2: Shaft identification
0x308 B1-B2 (16-bit LE counter) vs motor RPM.

Goals:
1. TC neutral test (Vtrux): motor spinning with TC in neutral decouples output shaft.
   Fast counter accumulation during TC neutral -> input shaft.
   Counter stays near parked value during TC neutral -> output shaft.

2. Counts/RPM ratio cross-check: compare Vtrux vs Coda.
   Same ratio -> same shaft type (both input or both output scaled by same factor).
   Different ratio -> one possible explanation is different gearbox reductions (2.68:1 for Vtrux 32-01).

TC test sequence (from notes):
  4H -> 2H -> neutral -> 4Lo -> neutral (revved motor) -> 2H

Motor RPM: 0x5A2 B2-B3 LE uint16 centered at 32768 (Vtrux PT bus)
Counter:   0x308 B1-B2 LE uint16 (B1=low byte, B2=high byte), centered at 32128 (0x7D80)

Coda motor speed: 0x1C0 B6-B7 LE uint16, scale 0.5, offset -16064
Coda counter:     0x308 B1-B2 LE uint16, same encoding
"""
import sys, statistics
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

import bisect

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


print("=" * 70)
print("PHASE 2A: TC NEUTRAL TEST (Vtrux)")
print("=" * 70)

tc_path = 'projects/vtrux/logs/vtrux_transfer_case_test.log'
frames_308, frames_5a2 = [], []
for f in parse_file(tc_path):
    if f.arbitration_id == ID_308:
        frames_308.append(f)
    elif f.arbitration_id == ID_5A2:
        frames_5a2.append(f)

rpm_t = [f.timestamp for f in frames_5a2]
rpm_v = [trac_rpm(f) for f in frames_5a2]

print(f"0x308 frames: {len(frames_308)},  0x5A2 RPM frames: {len(frames_5a2)}")
print(f"Log span: {frames_308[0].timestamp:.1f} - {frames_308[-1].timestamp:.1f} s")

print("\n--- Full counter timeline (B1 change events) with motor RPM ---")
print(f"{'t(s)':>9}  {'B0':>4}  {'B1':>3}  {'B2':>3}  {'counter':>7}  {'offset':>7}  {'rpm':>7}  {'pin'}")

prev_b1 = None
prev_counter = None
prev_t = None
events = []
for f in frames_308:
    b0, b1, b2 = f.data[0], f.data[1], f.data[2]
    ctr = counter_val(f)
    if b1 != prev_b1:
        rpm = nearest_val(rpm_t, rpm_v, f.timestamp)
        pin_s = 'Park' if b0 == 0x20 else ('NotPark' if b0 == 0x40 else f'0x{b0:02X}')
        offset = ctr - COUNTER_ZERO
        delta_c = (ctr - prev_counter) if prev_counter is not None else 0
        delta_t = (f.timestamp - prev_t) if prev_t is not None else 0
        rate = delta_c / delta_t if delta_t > 0.001 else 0
        events.append((f.timestamp, b0, b1, b2, ctr, offset, rpm, pin_s, delta_c, rate))
        prev_b1 = b1
        prev_counter = ctr
        prev_t = f.timestamp

for t, b0, b1, b2, ctr, offset, rpm, pin_s, dc, rate in events:
    rpm_s = f'{rpm:+7.0f}' if rpm is not None else '    ---'
    print(f"{t:9.2f}  0x{b0:02X}  {b1:3d}  {b2:3d}  {ctr:7d}  {offset:+7d}  {rpm_s}  {pin_s}  dc={dc:+5d}  rate={rate:+7.1f}cnt/s")

print("\n--- RPM-binned counter rate (notPark frames only, Vtrux TC test) ---")
print("Bins counter delta-rate (counts/s) by RPM range, to see if counter moves proportionally to motor RPM")
if len(frames_308) > 1 and rpm_t:
    bins = {(0, 200): [], (200, 500): [], (500, 1000): [], (1000, 3000): [], (3000, 9999): []}
    for i in range(1, len(frames_308)):
        f_prev, f_cur = frames_308[i-1], frames_308[i]
        if f_cur.data[0] != 0x40:
            continue
        dt = f_cur.timestamp - f_prev.timestamp
        if dt < 0.005 or dt > 0.5:
            continue
        dc = counter_val(f_cur) - counter_val(f_prev)
        rpm = nearest_val(rpm_t, rpm_v, f_cur.timestamp)
        if rpm is None:
            continue
        abs_rpm = abs(rpm)
        for (lo, hi) in bins:
            if lo <= abs_rpm < hi:
                bins[(lo, hi)].append(abs(dc) / dt)
                break
    for (lo, hi), rates in sorted(bins.items()):
        if rates:
            print(f"  RPM {lo:4d}-{hi:4d}: n={len(rates):4d}  mean_rate={statistics.mean(rates):7.1f} cnt/s  "
                  f"median={statistics.median(rates):7.1f}")
        else:
            print(f"  RPM {lo:4d}-{hi:4d}: no data")


print("\n" + "=" * 70)
print("PHASE 2B: COUNTS/RPM RATIO CROSS-CHECK (Vtrux vs Coda)")
print("=" * 70)
print("If the encoder is on the input shaft (motor side), ratio should be ~same for both vehicles.")
print("If on output shaft, ratio should differ by gearbox reduction ratio difference.")

def ratio_for_log(path, is_coda):
    frames_308, frames_rpm = [], []
    for f in parse_file(path):
        if f.arbitration_id == ID_308:
            frames_308.append(f)
        elif f.arbitration_id == (ID_1C0 if is_coda else ID_5A2):
            frames_rpm.append(f)
    if not frames_308 or not frames_rpm:
        return None
    rpm_ts = [f.timestamp for f in frames_rpm]
    rpm_vs = [coda_rpm(f) if is_coda else trac_rpm(f) for f in frames_rpm]

    pairs = []
    for i in range(1, len(frames_308)):
        f_prev, f_cur = frames_308[i-1], frames_308[i]
        if f_cur.data[0] != 0x40:
            continue
        dt = f_cur.timestamp - f_prev.timestamp
        if dt < 0.005 or dt > 0.5:
            continue
        dc = counter_val(f_cur) - counter_val(f_prev)
        if dc == 0:
            continue
        rpm = nearest_val(rpm_ts, rpm_vs, f_cur.timestamp)
        if rpm is None or abs(rpm) < 50:
            continue
        cnt_per_rev_per_s = dc / (rpm / 60.0) if dt > 0 else 0
        pairs.append((abs(dc) / dt, abs(rpm), cnt_per_rev_per_s))
    return pairs

vtrux_logs = [
    ('projects/vtrux/logs/vtruxevapdrivelog4.log', False),
]
coda_logs = [
    ('projects/coda/logs/frombonnydoon.log', True),
    ('projects/coda/logs/codadriveslowturnonwithdefroster2.log', True),
]

for label, logs in [('VTRUX', vtrux_logs), ('CODA', coda_logs)]:
    all_cnt_per_rpm = []
    for path, is_coda in logs:
        pairs = ratio_for_log(path, is_coda)
        if pairs:
            cnt_per_rev = [abs(dc) / rpm_abs * 60 for dc, rpm_abs, _ in pairs if rpm_abs > 0]
            all_cnt_per_rpm.extend(cnt_per_rev)
            print(f"\n  {label} {path.split('/')[-1]}: n={len(pairs)} update-events")
            print(f"    mean cnt/rev = {statistics.mean(cnt_per_rev):.2f}  median cnt/rev = {statistics.median(cnt_per_rev):.2f}")
        else:
            print(f"\n  {label} {path.split('/')[-1]}: no usable data")
    if all_cnt_per_rpm:
        print(f"\n  {label} OVERALL: mean={statistics.mean(all_cnt_per_rpm):.2f} cnt/rev  "
              f"median={statistics.median(all_cnt_per_rpm):.2f} cnt/rev  n={len(all_cnt_per_rpm)}")
