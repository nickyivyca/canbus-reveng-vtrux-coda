"""
Two-window comparison to find evap-specific signals.

Compares byte values during two engine-running windows in vtruxanotherevaplogpart2.log:
  Window A: engine running + evap active     t=12.31 - 1388.0s
  Window B: engine running + M mode (no evap) t=1455.66 - 1669.86s

For each (bus, msg_id, byte_pos) signal, computes the modal value and stability
(fraction of samples at the mode) in each window.

Candidates: stability_A > STABLE_THRESH  AND  stability_B > STABLE_THRESH
            AND  modal_A != modal_B

This filters out rolling counters (many values), continuous analog signals, and
oscillating bits -- and retains signals that are stable at different values
between the two windows.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from canre.parsers import parse_file
from collections import Counter

LOG = "projects/vtrux/logs/vtruxanotherevaplogpart2.log"
OUT = "projects/vtrux/notes/artifacts/evap_two_window_results.txt"

# Windows
A_LO, A_HI = 12.31, 1388.0    # engine running + evap active
B_LO, B_HI = 1455.66, 1669.86 # engine running + M mode, no evap

# Tuning
STABLE_THRESH = 0.90   # require 90% of samples at modal value
MIN_SAMPLES   = 200    # minimum samples in each window

print("Scanning", LOG)
print(f"Window A (evap active):   t={A_LO}-{A_HI}s")
print(f"Window B (M mode, no evap): t={B_LO}-{B_HI}s")

counts_A = {}  # (bus, mid, byte) -> Counter
counts_B = {}

frame_count = 0
for frame in parse_file(LOG):
    t = frame.timestamp
    frame_count += 1

    in_A = A_LO <= t <= A_HI
    in_B = B_LO <= t <= B_HI
    if not (in_A or in_B):
        continue

    for i, b in enumerate(frame.data):
        key = (frame.bus, frame.arbitration_id, i)
        if in_A:
            if key not in counts_A:
                counts_A[key] = Counter()
            counts_A[key][b] += 1
        if in_B:
            if key not in counts_B:
                counts_B[key] = Counter()
            counts_B[key][b] += 1

    if frame_count % 2_000_000 == 0:
        print(f"  {frame_count:,} frames, t={t:.1f}s ...")

print(f"Done. {frame_count:,} frames parsed.")

# --- Analysis ---
all_keys = set(counts_A) & set(counts_B)

candidates = []
stable_both_same = []

for key in sorted(all_keys):
    ca = counts_A[key]
    cb = counts_B[key]
    total_a = sum(ca.values())
    total_b = sum(cb.values())
    if total_a < MIN_SAMPLES or total_b < MIN_SAMPLES:
        continue

    mode_a, cnt_a = ca.most_common(1)[0]
    mode_b, cnt_b = cb.most_common(1)[0]
    stab_a = cnt_a / total_a
    stab_b = cnt_b / total_b

    if stab_a >= STABLE_THRESH and stab_b >= STABLE_THRESH:
        if mode_a != mode_b:
            candidates.append((key, mode_a, stab_a, total_a, mode_b, stab_b, total_b))
        else:
            stable_both_same.append((key, mode_a, stab_a, total_a, stab_b, total_b))

# Sort candidates by stability (both windows), prefer highest combined stability
candidates.sort(key=lambda x: -(x[2] + x[5]))

def fmt_key(key):
    bus, mid, byte = key
    return f"Bus{bus} 0x{mid:03X} B{byte}"

lines = []
lines.append("=" * 70)
lines.append("TWO-WINDOW EVAP COMPARISON -- vtruxanotherevaplogpart2.log")
lines.append("=" * 70)
lines.append(f"Window A (evap active):    t={A_LO}-{A_HI}s")
lines.append(f"Window B (M mode, no evap): t={B_LO}-{B_HI}s")
lines.append(f"Stability threshold: {STABLE_THRESH:.0%}  Min samples: {MIN_SAMPLES}")
lines.append(f"")
lines.append(f"Signals with stable values in both windows:   {len(candidates) + len(stable_both_same)}")
lines.append(f"  ...same value both windows (engine-state):  {len(stable_both_same)}")
lines.append(f"  ...DIFFERENT value between windows (candidates): {len(candidates)}")
lines.append("")

lines.append("=" * 70)
lines.append("CANDIDATES -- stable in both windows, different value")
lines.append("=" * 70)
for key, ma, sa, na, mb, sb, nb in candidates:
    lines.append(f"\n  {fmt_key(key)}")
    lines.append(f"    Window A (evap):   0x{ma:02X} = {ma:3d}  ({sa:.1%} of {na:,} samples)")
    lines.append(f"    Window B (M mode): 0x{mb:02X} = {mb:3d}  ({sb:.1%} of {nb:,} samples)")
    lines.append(f"    Delta: {mb - ma:+d} counts")

lines.append("")
lines.append("=" * 70)
lines.append(f"STABLE + SAME VALUE (no difference, {len(stable_both_same)} signals -- engine-state confirmed)")
lines.append("=" * 70)
for key, ma, sa, na, sb, nb in stable_both_same[:30]:
    lines.append(f"  {fmt_key(key)}  0x{ma:02X}={ma:3d}  A:{sa:.1%}/{na:,}  B:{sb:.1%}/{nb:,}")
if len(stable_both_same) > 30:
    lines.append(f"  ... and {len(stable_both_same) - 30} more")

out_text = "\n".join(lines)
print(out_text)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(out_text)
print("\nResults saved to", OUT)
