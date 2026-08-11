"""
HVAC Investigation Analysis Script
- Analyze coolant temp and battery current timeseries
- Find heater on/off events (Part 2 end)
- Compare dT/dt heater-on vs heater-off
- Analyze Part 3 PTC investigation
"""

import csv
import sys

COOLANT_OFFSET = -40  # raw - 40 = degC
CURRENT_CENTER = 32768
CURRENT_SCALE = 0.04  # A/count

def read_csv(path):
    rows = []
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((float(row['timestamp']), int(row['value'])))
    return rows

def decode_coolant(raw):
    return raw + COOLANT_OFFSET

def decode_current_a(raw_u16):
    """Battery current in Amperes. Positive = discharge."""
    # raw_u16 is already B0+(B1*256) little-endian
    return (raw_u16 - CURRENT_CENTER) * CURRENT_SCALE

def print_window(label, ct_data, ba_data, t_start, t_end):
    """Print stats for a time window."""
    ct_window = [(t, decode_coolant(v)) for t, v in ct_data if t_start <= t < t_end]
    ba_window = [(t, decode_current_a(v)) for t, v in ba_data if t_start <= t < t_end and 20000 < v < 50000]

    if len(ct_window) < 2:
        print(f"  {label}: not enough coolant data ({len(ct_window)} points)")
        return

    t0_ct, v0_ct = ct_window[0]
    t1_ct, v1_ct = ct_window[-1]
    dt_ct = t1_ct - t0_ct
    dv_ct = v1_ct - v0_ct
    dt_dt = (dv_ct / dt_ct * 60) if dt_ct > 0 else 0  # degC/min

    ba_vals = [v for _, v in ba_window]
    ba_mean = sum(ba_vals) / len(ba_vals) if ba_vals else float('nan')

    print(f"  {label} (t={t_start:.0f}-{t_end:.0f}s):")
    print(f"    Coolant: {v0_ct:.0f} -> {v1_ct:.0f} degC over {dt_ct:.0f}s | dT/dt = {dt_dt:+.3f} degC/min")
    print(f"    Battery current: {ba_mean:.1f} A mean ({len(ba_vals)} samples)")

print("=" * 60)
print("PART 2: Coolant Temp and Battery Current")
print("=" * 60)

ct2 = read_csv("notes/artifacts/coolant_temp_part2.csv")
ba2 = read_csv("notes/artifacts/batt_current_part2.csv")

print(f"Coolant temp Part 2: {len(ct2)} samples, t={ct2[0][0]:.1f} to {ct2[-1][0]:.1f}s")
print(f"Battery current Part 2: {len(ba2)} samples, t={ba2[0][0]:.1f} to {ba2[-1][0]:.1f}s")

# Show coolant temp at key moments
ct2_raw = [(t, v) for t, v in ct2]
print(f"\nCoolant temp start of Part 2: raw={ct2[0][1]}, degC={decode_coolant(ct2[0][1])}")
print(f"Coolant temp end of Part 2:   raw={ct2[-1][1]}, degC={decode_coolant(ct2[-1][1])}")
print(f"Coolant temp max: raw={max(v for _,v in ct2)}, degC={decode_coolant(max(v for _,v in ct2))}")
print(f"Coolant temp min: raw={min(v for _,v in ct2)}, degC={decode_coolant(min(v for _,v in ct2))}")

# Show last 600s in 30s buckets to find the heater event
total_dur = ct2[-1][0]
print(f"\nTotal Part 2 duration: {total_dur:.0f}s")
print(f"\nLast 700s of Part 2 (30s buckets, coolant temp + battery current):")
print(f"  {'t_start':>8}  {'t_end':>8}  {'CT_start':>10}  {'CT_end':>10}  {'dT/dt(degC/min)':>17}  {'I_batt_A':>10}")

bucket = 30
for t_start in range(int(total_dur) - 700, int(total_dur), bucket):
    t_end = t_start + bucket
    ct_win = [(t, decode_coolant(v)) for t, v in ct2 if t_start <= t < t_end]
    ba_win = [(t, decode_current_a(v)) for t, v in ba2 if t_start <= t < t_end and 20000 < v < 50000]

    if len(ct_win) < 2:
        continue

    v0 = ct_win[0][1]
    v1 = ct_win[-1][1]
    dv = v1 - v0
    dt_sec = ct_win[-1][0] - ct_win[0][0]
    rate = (dv / dt_sec * 60) if dt_sec > 5 else float('nan')
    i_mean = sum(v for _, v in ba_win) / len(ba_win) if ba_win else float('nan')

    print(f"  {t_start:8.0f}  {t_end:8.0f}  {v0:10.1f}  {v1:10.1f}  {rate:17.3f}  {i_mean:10.1f}")

# Battery current in last 700s: look for step changes
print(f"\nBattery current last 700s (valid range only):")
ba2_last = [(t, decode_current_a(v)) for t, v in ba2 if t >= total_dur - 700 and 20000 < v < 50000]
if ba2_last:
    for t, i in ba2_last:
        print(f"  t={t:8.1f}s  I={i:8.1f} A")
else:
    print("  No valid samples in this window")

print("\n" + "=" * 60)
print("PART 3: Coolant Temp and Battery Current")
print("=" * 60)

ct3 = read_csv("notes/artifacts/coolant_temp_part3.csv")
ba3 = read_csv("notes/artifacts/batt_current_part3.csv")

print(f"Coolant temp Part 3: {len(ct3)} samples, t={ct3[0][0]:.1f} to {ct3[-1][0]:.1f}s")
print(f"Battery current Part 3: {len(ba3)} samples, t={ba3[0][0]:.1f} to {ba3[-1][0]:.1f}s")

print(f"\nCoolant temp start: raw={ct3[0][1]}, degC={decode_coolant(ct3[0][1])}")
print(f"Coolant temp end:   raw={ct3[-1][1]}, degC={decode_coolant(ct3[-1][1])}")

print(f"\nPart 3 full timeline (60s buckets, coolant temp + battery current):")
print(f"  {'t_start':>8}  {'t_end':>8}  {'CT_start':>10}  {'CT_end':>10}  {'dT/dt':>12}  {'I_batt_A':>10}")

total_dur3 = ct3[-1][0]
for t_start in range(0, int(total_dur3), 60):
    t_end = t_start + 60
    ct_win = [(t, decode_coolant(v)) for t, v in ct3 if t_start <= t < t_end]
    ba_win = [(t, decode_current_a(v)) for t, v in ba3 if t_start <= t < t_end and 20000 < v < 50000]

    if len(ct_win) < 2:
        continue

    v0 = ct_win[0][1]
    v1 = ct_win[-1][1]
    dv = v1 - v0
    dt_sec = ct_win[-1][0] - ct_win[0][0]
    rate = (dv / dt_sec * 60) if dt_sec > 5 else float('nan')
    i_mean = sum(v for _, v in ba_win) / len(ba_win) if ba_win else float('nan')

    print(f"  {t_start:8.0f}  {t_end:8.0f}  {v0:10.1f}  {v1:10.1f}  {rate:12.3f}  {i_mean:10.1f}")

# Also look for generator-on events in Part 3 using 0x600 B0 (but we don't have that timeseries)
# Use battery current step changes as proxy
print(f"\nAll Part 3 battery current samples (valid range only):")
ba3_valid = [(t, decode_current_a(v)) for t, v in ba3 if 20000 < v < 50000]
for t, i in ba3_valid:
    print(f"  t={t:8.1f}s  I={i:8.1f} A  raw={next(v for tt,v in ba3 if tt==t)}")
