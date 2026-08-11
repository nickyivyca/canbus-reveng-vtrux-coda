"""Check DCDC HV timing in climit log - find 152V event."""
import sys
sys.path.insert(0, '.')
from canre.parsers import parse_file

log_path = "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
dcdc_id = 0x18FFD6B3
b2_id = 0x0870A047

dcdc_rows = []
b2_rows = []

for frame in parse_file(log_path):
    if frame.arbitration_id == dcdc_id and len(frame.data) >= 6:
        b4 = frame.data[4]
        b5 = frame.data[5]
        raw_le = b4 + b5 * 256
        volts = raw_le * 0.05
        dcdc_rows.append((frame.timestamp, volts))
    elif frame.arbitration_id == b2_id and len(frame.data) >= 3:
        b2_rows.append((frame.timestamp, frame.data[2]))

# Find DCDC events below 300V (abnormal for a driving log)
print("DCDC HV events below 300V:")
count = 0
for t, v in dcdc_rows:
    if v < 300:
        count += 1
        if count <= 20:
            print(f"  t={t:.2f}s  DCDC={v:.1f}V")
print(f"  Total: {count} frames")

# Show first 10 and last 10 frames
print("\nFirst 5 DCDC frames:")
for t, v in dcdc_rows[:5]:
    print(f"  t={t:.4f}s  DCDC={v:.1f}V")
print("\nLast 5 DCDC frames:")
for t, v in dcdc_rows[-5:]:
    print(f"  t={t:.4f}s  DCDC={v:.1f}V")

# Show B2 around time of first low DCDC
if count > 0:
    low_t = next(t for t, v in dcdc_rows if v < 300)
    print(f"\nB2 around t={low_t:.2f}s (first <300V DCDC event):")
    for t, b2 in b2_rows:
        if abs(t - low_t) < 2.0:
            print(f"  t={t:.4f}s  B2={b2}  (implied_cell={b2*33.9:.0f}mV)")
