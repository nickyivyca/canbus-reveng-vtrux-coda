"""Correlate 0x0870A047 B2 vs DCDC HV (0x18FFD6B3 B4-B5 LE) on climit log."""
import csv, statistics, sys
sys.path.insert(0, '.')
from canre.parsers import parse_file

# Load B2 CSV
b2_ts = []
b2_vals = []
with open("projects/vtrux/notes/artifacts/climit_0x0870A047_B2.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        b2_ts.append(float(row['timestamp']))
        b2_vals.append(int(row['value']))

print(f"B2 samples: {len(b2_vals)}, range {min(b2_vals)}-{max(b2_vals)}")

# Extract DCDC HV from log directly - correct LE byte order
dcdc_ts = []
dcdc_vals = []
log_path = "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
target_id = 0x18FFD6B3

for frame in parse_file(log_path):
    if frame.arbitration_id == target_id and len(frame.data) >= 6:
        b4 = frame.data[4]
        b5 = frame.data[5]
        raw_le = b4 + b5 * 256  # Little-endian uint16
        volts = raw_le * 0.05
        dcdc_ts.append(frame.timestamp)
        dcdc_vals.append(volts)

print(f"DCDC HV samples: {len(dcdc_vals)}")
print(f"DCDC HV range: {min(dcdc_vals):.1f}--{max(dcdc_vals):.1f} V")
print(f"DCDC HV mean: {statistics.mean(dcdc_vals):.1f} V, stddev: {statistics.stdev(dcdc_vals):.1f} V")

# Nearest-neighbor match by timestamp (within 0.15s)
pairs_b2 = []
pairs_dcdc = []
j = 0
for i, t_b2 in enumerate(b2_ts):
    while j < len(dcdc_ts) - 1 and abs(dcdc_ts[j+1] - t_b2) < abs(dcdc_ts[j] - t_b2):
        j += 1
    if abs(dcdc_ts[j] - t_b2) < 0.15:
        pairs_b2.append(b2_vals[i])
        pairs_dcdc.append(dcdc_vals[j])

print(f"\nMatched pairs: {len(pairs_b2)}")

# Pearson r
n = len(pairs_b2)
mean_b2 = sum(pairs_b2) / n
mean_dcdc = sum(pairs_dcdc) / n
cov = sum((pairs_b2[i] - mean_b2) * (pairs_dcdc[i] - mean_dcdc) for i in range(n)) / n
std_b2 = (sum((x - mean_b2)**2 for x in pairs_b2) / n)**0.5
std_dcdc = (sum((x - mean_dcdc)**2 for x in pairs_dcdc) / n)**0.5
r = cov / (std_b2 * std_dcdc)
print(f"Pearson r (B2 vs DCDC_V): {r:.4f}")

# Regression: DCDC_V = a * B2 + b
a = cov / (std_b2**2)
b_int = mean_dcdc - a * mean_b2
print(f"Regression: DCDC_V = {a:.4f} * B2 + {b_int:.4f}")
print(f"Expected slope if B2=V_cell (33.9mV/count * 117 cells / 1000): {33.9*117/1000:.4f} V/count")
print(f"Expected slope if B2=V_pack/33.9 (direct HV): 33.9 * 117 / 1000 same = {33.9*117/1000:.4f} V/count")

# Check residuals: pack_V_from_B2 vs DCDC
pack_v_from_b2 = [v * 33.9 * 117 / 1000 for v in pairs_b2]
diffs = [pack_v_from_b2[i] - pairs_dcdc[i] for i in range(n)]
mean_diff = sum(diffs) / n
std_diff = (sum((d - mean_diff)**2 for d in diffs) / n)**0.5
print(f"\nPack_V_from_B2 - DCDC_V: mean={mean_diff:.2f} V, stddev={std_diff:.2f} V")
print(f"(If B2 is V_cell, DCDC should read ~7V below pack => expected mean ~+7)")
print(f"(If B2 is V_pack/33.9/117*1000, same expectation)")
print(f"\nNote: In balanced pack, V_cell vs V_pack/117 are indistinguishable.")
print(f"The T0 precharge behavior (B2 non-zero before contactors close) is the key discriminant.")
