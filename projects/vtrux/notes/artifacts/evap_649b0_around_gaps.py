"""
Check 0x649 B0 values before and after the 12V battery disconnect gaps
in the partstruck testdrive_part2 log.
Also show what VCM key-on sequence looks like (0x600 B3 boot sequence).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from canre.parsers import parse_file

LOG = r"projects\vtrux\logs\vtrux_partstruck_testdrive_part2.log"
GAP_THRESHOLD_S = 3.0
WINDOW_S = 15.0

p = Path(LOG)
print(f"Loading {p.name}...")
frames = list(parse_file(str(p)))
print(f"  {len(frames):,} frames, {frames[0].timestamp:.1f}s - {frames[-1].timestamp:.1f}s")

gaps = []
prev_t = None
for f in frames:
    if prev_t is not None and f.timestamp - prev_t > GAP_THRESHOLD_S:
        gaps.append((prev_t, f.timestamp, f.timestamp - prev_t))
    prev_t = f.timestamp

print(f"\nGaps: {len(gaps)}")
for i, (gs, ge, gd) in enumerate(gaps):
    print(f"  Gap {i+1}: {gs:.3f}s -> {ge:.3f}s ({gd:.1f}s)")

for gap_idx, (gap_start, gap_end, gap_dur) in enumerate(gaps):
    print(f"\n{'='*55}")
    print(f"Gap {gap_idx+1}: {gap_start:.3f}s -> {gap_end:.3f}s ({gap_dur:.1f}s)")

    print(f"\n  0x649 B0 in last {WINDOW_S}s before gap ({gap_start-WINDOW_S:.3f}s - {gap_start:.3f}s):")
    pre_vals = [(f.timestamp, f.data[0]) for f in frames
                if f.arbitration_id == 0x649 and len(f.data) >= 1
                and gap_start - WINDOW_S <= f.timestamp <= gap_start]
    shown = 0
    last_b0 = None
    for t, b0 in pre_vals:
        if b0 != last_b0:
            print(f"    {t:.3f}s  B0=0x{b0:02X}  bit7={'SET' if b0 & 0x80 else 'clear'}")
            last_b0 = b0
        shown += 1
        if shown >= 20:
            break
    if not pre_vals:
        print("    (none)")

    print(f"\n  0x649 B0 in first {WINDOW_S}s after gap ({gap_end:.3f}s - {gap_end+WINDOW_S:.3f}s):")
    post_vals = [(f.timestamp, f.data[0]) for f in frames
                 if f.arbitration_id == 0x649 and len(f.data) >= 1
                 and gap_end <= f.timestamp <= gap_end + WINDOW_S]
    last_b0 = None
    for t, b0 in post_vals:
        if b0 != last_b0:
            rel = t - gap_end
            print(f"    +{rel:.3f}s  B0=0x{b0:02X}  bit7={'SET' if b0 & 0x80 else 'clear'}")
            last_b0 = b0
    if not post_vals:
        print("    (none)")

    print(f"\n  0x600 B3 boot sequence after gap (first 5s):")
    boot_vals = [(f.timestamp, f.data[3]) for f in frames
                 if f.arbitration_id == 0x600 and len(f.data) >= 4
                 and gap_end <= f.timestamp <= gap_end + 5.0]
    last_b3 = None
    for t, b3 in boot_vals[:30]:
        if b3 != last_b3:
            rel = t - gap_end
            print(f"    +{rel:.3f}s  0x600 B3=0x{b3:02X} ({b3})")
            last_b3 = b3
    if not boot_vals:
        print("    (none - 0x600 not broadcasting yet)")

print("\nDone.")
