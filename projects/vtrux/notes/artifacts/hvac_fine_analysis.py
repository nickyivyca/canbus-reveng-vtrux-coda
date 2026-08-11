"""
Fine-grained analysis of the last 400s of Part 2 and the heater event.
Show raw battery current (no filter) and coolant temp at fine resolution.
"""
import csv

COOLANT_OFFSET = -40
CURRENT_CENTER = 32768
CURRENT_SCALE = 0.04

def read_csv(path):
    rows = []
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((float(row['timestamp']), int(row['value'])))
    return rows

ct2 = read_csv("notes/artifacts/coolant_temp_part2.csv")
ba2 = read_csv("notes/artifacts/batt_current_part2.csv")

total_dur = ct2[-1][0]
print(f"Part 2 duration: {total_dur:.1f}s")
print()

# Show raw battery current in last 300s (no range filter)
print("=== Battery current raw values, last 300s of Part 2 ===")
ba2_last300 = [(t, v) for t, v in ba2 if t >= total_dur - 300]
print(f"{'timestamp':>12}  {'raw_u16':>8}  {'current_A':>10}  {'note'}")
for t, v in ba2_last300:
    i_a = (v - CURRENT_CENTER) * CURRENT_SCALE
    note = ""
    if v < 1000 or v > 64000:
        note = "<-- SENTINEL/INVALID"
    elif abs(i_a) > 400:
        note = "<-- LARGE"
    print(f"{t:12.1f}  {v:8d}  {i_a:10.1f}  {note}")

print()
# Show coolant temp in last 300s at full resolution (every unique reading)
print("=== Coolant temp last 300s of Part 2 (deduplicated) ===")
ct2_last = [(t, v) for t, v in ct2 if t >= total_dur - 300]
prev_v = None
for t, v in ct2_last:
    if v != prev_v:
        print(f"  t={t:8.1f}s  raw={v:3d}  degC={v+COOLANT_OFFSET:4d}")
        prev_v = v

print()
# Show Part 3 coolant in first 60s at full resolution
ct3 = read_csv("notes/artifacts/coolant_temp_part3.csv")
ba3 = read_csv("notes/artifacts/batt_current_part3.csv")
print("=== Part 3 coolant temp first 60s (full resolution) ===")
ct3_first = [(t, v) for t, v in ct3 if t <= 60]
prev_v = None
for t, v in ct3_first:
    if v != prev_v:
        print(f"  t={t:8.1f}s  raw={v:3d}  degC={v+COOLANT_OFFSET:4d}")
        prev_v = v

print()
print("=== Part 3 battery current, raw, first 60s ===")
ba3_first = [(t, v) for t, v in ba3 if t <= 60]
for t, v in ba3_first:
    i_a = (v - CURRENT_CENTER) * CURRENT_SCALE
    print(f"  t={t:8.1f}s  raw={v:8d}  I={i_a:8.1f}A")
