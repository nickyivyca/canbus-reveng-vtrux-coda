"""
Verify whether B5[1:0] of 0x06000002 are temperature fine bits or a rolling counter.

If rolling counter: consecutive frames will cycle 0->1->2->3->0 at message rate.
If temperature: values will hold steady or change slowly with B6.

Also check B5[7:6] as the actual fine temperature bits straddling B6.
"""

import sys
sys.path.insert(0, ".")
from canre.parsers import parse_file
import numpy as np
import collections

LOG    = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"
PT_BUS = 3
AID    = 0x06000002

pts = []
for frame in parse_file(LOG):
    if frame.bus != PT_BUS or frame.arbitration_id != AID:
        continue
    if len(frame.data) < 7:
        continue
    b5, b6 = frame.data[5], frame.data[6]
    pts.append((frame.timestamp, b5, b6))

print(f"Total frames: {len(pts)}")

ts  = np.array([p[0] for p in pts])
b5  = np.array([p[1] for p in pts])
b6  = np.array([p[2] for p in pts])

lsbs  = b5 & 0x03          # B5[1:0]
msbs  = (b5 >> 6) & 0x03   # B5[7:6]

# --- 1. Delta histogram for B5[1:0] ---
deltas_lsb = np.diff(lsbs.astype(int))
# wrap-around: treat mod-4 increments
deltas_mod4 = deltas_lsb % 4  # rolling counter would show all +1 increments
cnt_lsb = collections.Counter(deltas_lsb.tolist())
cnt_mod4 = collections.Counter(deltas_mod4.tolist())

print("\nB5[1:0] frame-to-frame delta histogram (raw):")
for k in sorted(cnt_lsb):
    print(f"  delta={k:+3d}: {cnt_lsb[k]} times")

print("\nB5[1:0] frame-to-frame delta mod 4 (rolling counter signature = all +1):")
for k in sorted(cnt_mod4):
    print(f"  delta mod4={k}: {cnt_mod4[k]} times")

frac_plus1 = cnt_mod4.get(1, 0) / max(len(deltas_mod4), 1)
print(f"\n  Fraction of consecutive frames where lsb increments by +1 mod4: {frac_plus1:.3f}")
print(f"  (>0.9 strongly suggests rolling counter; <0.3 suggests temperature fine bits)")

# --- 2. Delta histogram for B5[7:6] (should show slow thermal steps) ---
deltas_msb = np.diff(msbs.astype(int))
cnt_msb = collections.Counter(deltas_msb.tolist())
print("\nB5[7:6] frame-to-frame delta histogram:")
for k in sorted(cnt_msb):
    print(f"  delta={k:+3d}: {cnt_msb[k]} times")

# --- 3. How many consecutive frames have the same B5[1:0] value? ---
run_lengths = []
run = 1
for i in range(1, len(lsbs)):
    if lsbs[i] == lsbs[i-1]:
        run += 1
    else:
        run_lengths.append(run)
        run = 1
run_lengths.append(run)
run_arr = np.array(run_lengths)
print(f"\nB5[1:0] run-length stats (how many consecutive frames hold the same value):")
print(f"  mean={run_arr.mean():.2f}, median={np.median(run_arr):.1f}, max={run_arr.max()}, min={run_arr.min()}")
print(f"  (counter: mean~1; temperature: mean could be many frames)")

# --- 4. Print first 40 frames of B5[1:0] and B5[7:6] to see pattern ---
print("\nFirst 40 frames (t, B6, B5[7:6], B5[1:0]):")
for i in range(min(40, len(pts))):
    print(f"  t={ts[i]:7.2f}  B6={b6[i]:3d}  B5[7:6]={msbs[i]}  B5[1:0]={lsbs[i]}")

# --- 5. Check if B5[1:0] unique values at each (B6, B5[7:6]) combination ---
print("\nUnique B5[1:0] values at each (B6, B5[7:6]) level (first 15 combos):")
by_b6_msb = collections.defaultdict(set)
for b5v, b6v in zip(b5, b6):
    key = (int(b6v), (int(b5v)>>6)&3)
    by_b6_msb[key].add(int(b5v) & 3)
shown = 0
for key in sorted(by_b6_msb)[:15]:
    vals = sorted(by_b6_msb[key])
    print(f"  (B6={key[0]}, B5[7:6]={key[1]}): B5[1:0] = {vals}")
    shown += 1
