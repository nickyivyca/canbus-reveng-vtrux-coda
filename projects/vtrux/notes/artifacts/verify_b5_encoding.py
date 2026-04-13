"""
Determine whether the traction motor temp signal is:
  (A) 10-bit LE at startbit 46: value = (B6<<2)|(B5>>6), scale ~2.0 C/count
      B5[1:0] is a separate/unrelated signal
  (B) Full 9-bit non-contiguous: (B6<<4)|((B5>>6)<<2)|(B5&3), scale 0.5 C/count
      B5[1:0] are genuine fine temp bits

Test: look at B5[1:0] when the 10-bit coarse value is CONSTANT for an extended
period. If B5[1:0] sweeps steadily (0->1->2->3 or reverse) that is fine temp.
If B5[1:0] is random or constant while coarse is constant, it is unrelated.

Also check: does B5[1:0] ever change WITHOUT B5[7:6] or B6 changing?
If yes, does it do so monotonically?
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

ts  = np.array([p[0] for p in pts])
b5  = np.array([p[1] for p in pts])
b6  = np.array([p[2] for p in pts])

lsbs  = b5 & 0x03
msbs  = (b5 >> 6) & 0x03
coarse = (b6.astype(int) << 2) | msbs.astype(int)  # 10-bit LE startbit 46 value

# --- Find windows where coarse is constant but lsbs changes ---
# These are the key diagnostic windows
print("=== Windows where coarse (B5[7:6]+B6) is constant but B5[1:0] changes ===")
print("Format: coarse_val  time_start  B5[1:0] sequence (first 20 frames)")
print()

i = 0
examples_shown = 0
while i < len(pts) and examples_shown < 8:
    # find a run where coarse is constant
    j = i
    while j < len(pts) and coarse[j] == coarse[i]:
        j += 1
    run_len = j - i
    if run_len >= 5:
        lsb_run = lsbs[i:j]
        if len(set(lsb_run.tolist())) > 1:
            # coarse is constant but lsbs varies - show this window
            seq = lsb_run[:20].tolist()
            delta_lsb = np.diff(lsb_run[:20].astype(int)).tolist()
            print(f"coarse={coarse[i]:4d}  t={ts[i]:.2f}-{ts[j-1]:.2f}s  len={run_len}")
            print(f"  B5[1:0] sequence: {seq}")
            print(f"  deltas:           {delta_lsb}")
            print()
            examples_shown += 1
    i = j

# --- Check if B5[1:0] transitions are monotonic within a coarse band ---
print("=== B5[1:0] transition directions while coarse is constant ===")
up = 0
down = 0
random_changes = 0
for i in range(1, len(pts)):
    if coarse[i] == coarse[i-1] and lsbs[i] != lsbs[i-1]:
        d = int(lsbs[i]) - int(lsbs[i-1])
        if d == 1:
            up += 1
        elif d == -1:
            down += 1
        else:
            random_changes += 1

print(f"When coarse is constant and B5[1:0] changes:")
print(f"  +1 (up):   {up}")
print(f"  -1 (down): {down}")
print(f"  other:     {random_changes}")
print(f"  up/(up+down) = {up/(up+down+0.001):.3f} (0.5 = random/jitter; near 1 = monotonic rising; near 0 = monotonic falling)")

# --- Verify: when temperature is definitively rising (B6 increasing),
#     does B5[1:0] also trend upward? ---
print()
print("=== B5[1:0] behavior during the heating phase (t=393-1953s) ===")
mask = (ts >= 393) & (ts <= 1953)
ts_h   = ts[mask]
lsbs_h = lsbs[mask]
b6_h   = b6[mask]

# look at segments where B6 is stable and B5[1:0] changes
# find first and last B5[1:0] at each B6 level during heating
by_b6 = collections.defaultdict(list)
for i in range(len(ts_h)):
    by_b6[int(b6_h[i])].append(int(lsbs_h[i]))

print("B6 level : first B5[1:0] seen -> last B5[1:0] seen (during heating t=393-1953s)")
for bv in sorted(by_b6):
    seq = by_b6[bv]
    if len(seq) >= 3:
        print(f"  B6={bv:3d}: first={seq[0]}  last={seq[-1]}  unique={sorted(set(seq))}  count={len(seq)}")

# --- Verify: during cooling phase (t=2253+), does B5[1:0] trend downward? ---
print()
print("=== B5[1:0] behavior during cooling phase (t=2253-3500s) ===")
mask2 = (ts >= 2253) & (ts <= 3500)
ts_c   = ts[mask2]
lsbs_c = lsbs[mask2]
b6_c   = b6[mask2]

by_b6_c = collections.defaultdict(list)
for i in range(len(ts_c)):
    by_b6_c[int(b6_c[i])].append(int(lsbs_c[i]))

print("B6 level : first B5[1:0] seen -> last B5[1:0] seen (during cooling t=2253-3500s)")
for bv in sorted(by_b6_c, reverse=True):
    seq = by_b6_c[bv]
    if len(seq) >= 3:
        print(f"  B6={bv:3d}: first={seq[0]}  last={seq[-1]}  unique={sorted(set(seq))}  count={len(seq)}")
