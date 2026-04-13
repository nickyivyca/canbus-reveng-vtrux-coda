"""
Bit-level analysis of 0x06000002 B5 and B6 to find the true signal packing.

Approach:
  1. Scatter plot: B5 vs B6 (what values does B5 take at each B6 step?)
  2. Per-bit timeseries of B5 alongside B6 (which B5 bits track thermally?)
  3. Try candidate extractions: B5>>N, (B6<<N)|B5>>(8-N), etc.
     Score each by smoothness (mean absolute delta between sorted adjacent samples).
  4. Plot the best extraction vs B6 reference.
"""

import sys, collections, math
sys.path.insert(0, ".")
from canre.parsers import parse_file
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

LOG    = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"
PT_BUS = 3
AID    = 0x06000002

print("Parsing log...", flush=True)
pts = []  # (t, b5, b6)
for frame in parse_file(LOG):
    if frame.bus != PT_BUS or frame.arbitration_id != AID:
        continue
    if len(frame.data) < 7:
        continue
    pts.append((frame.timestamp, frame.data[5], frame.data[6]))

print(f"  {len(pts)} frames of 0x{AID:X}", flush=True)

ts_arr = np.array([p[0] for p in pts])
b5_arr = np.array([p[1] for p in pts])
b6_arr = np.array([p[2] for p in pts])

# ---------------------------------------------------------------
# Figure 1: B5 scatter vs B6 + per-bit B5 timeseries
# ---------------------------------------------------------------
fig = plt.figure(figsize=(16, 18))
fig.suptitle("0x06000002 B5/B6 bit-level analysis\n(drivetrain overheat test, PT Bus 3)", fontsize=12)
gs = gridspec.GridSpec(11, 2, figure=fig, hspace=0.55, wspace=0.3)

# Left column: per-bit timeseries (B6 + each bit of B5)
ax_b6 = fig.add_subplot(gs[0, 0])
ax_b6.plot(ts_arr, b6_arr, lw=0.5, color="brown")
ax_b6.set_title("B6 (reference, coarse)", fontsize=8)
ax_b6.set_ylabel("raw", fontsize=7)

colors = ["steelblue","darkorange","green","red","purple","deeppink","gold","gray"]
for bit in range(8):
    ax = fig.add_subplot(gs[bit+1, 0], sharex=ax_b6)
    bval = (b5_arr >> bit) & 1
    ax.plot(ts_arr, bval, lw=0.3, color=colors[bit], alpha=0.7)
    ax.set_title(f"B5 bit {bit}  (unique vals: {len(set(bval))})", fontsize=7)
    ax.set_ylabel("0/1", fontsize=6)
    ax.set_yticks([0,1])

axes_left_last = fig.add_subplot(gs[9:, 0], sharex=ax_b6)
axes_left_last.plot(ts_arr, b5_arr, lw=0.5, color="navy")
axes_left_last.set_title("B5 raw value", fontsize=8)
axes_left_last.set_ylabel("raw", fontsize=7)
axes_left_last.set_xlabel("Log time (s)", fontsize=8)

# Right column: scatter B5 vs B6 + candidate extractions
ax_sc = fig.add_subplot(gs[0:3, 1])
ax_sc.scatter(b6_arr, b5_arr, s=0.5, alpha=0.2, color="steelblue")
ax_sc.set_xlabel("B6", fontsize=8)
ax_sc.set_ylabel("B5", fontsize=8)
ax_sc.set_title("B5 vs B6 scatter (all frames)", fontsize=8)

# Candidate extractions to test
# Format: (label, fn(b5, b6))
candidates = [
    ("B6 only (ref)",            lambda b5,b6: b6.astype(float)),
    ("B5>>5 (upper 3 bits)",     lambda b5,b6: (b5>>5).astype(float)),
    ("B5>>4 (upper 4 bits)",     lambda b5,b6: (b5>>4).astype(float)),
    ("B5>>3 (upper 5 bits)",     lambda b5,b6: (b5>>3).astype(float)),
    ("B5>>2 (upper 6 bits)",     lambda b5,b6: (b5>>2).astype(float)),
    ("B5 raw",                   lambda b5,b6: b5.astype(float)),
    ("B6<<2 | B5>>6",            lambda b5,b6: ((b6.astype(int)<<2)|(b5>>6)).astype(float)),
    ("B6<<3 | B5>>5",            lambda b5,b6: ((b6.astype(int)<<3)|(b5>>5)).astype(float)),
    ("B6<<4 | B5>>4",            lambda b5,b6: ((b6.astype(int)<<4)|(b5>>4)).astype(float)),
    ("B6<<5 | B5>>3",            lambda b5,b6: ((b6.astype(int)<<5)|(b5>>3)).astype(float)),
    ("B6<<6 | B5>>2",            lambda b5,b6: ((b6.astype(int)<<6)|(b5>>2)).astype(float)),
    ("B6<<8 | B5 (full LE16)",   lambda b5,b6: (b6.astype(int)*256+b5.astype(int)).astype(float)),
]

# Smoothness score: mean |delta| on the full timeseries (lower = smoother)
def smoothness(vals):
    d = np.diff(vals)
    return np.mean(np.abs(d))

print("\nCandidate extraction smoothness scores (lower = smoother):")
print(f"{'Label':<35}  {'range':>7}  {'unique':>7}  {'smoothness':>10}")
scores = []
for label, fn in candidates:
    vals = fn(b5_arr, b6_arr)
    rng = int(vals.max() - vals.min())
    uniq = len(set(vals.astype(int)))
    sm = smoothness(vals)
    scores.append((sm, label, fn, rng, uniq))
    print(f"  {label:<33}  {rng:>7}  {uniq:>7}  {sm:>10.4f}")

# Plot top 6 by smoothness
scores.sort(key=lambda x: x[0])
ax_cands = fig.add_subplot(gs[3:, 1])
cmap = plt.cm.tab10
for i, (sm, label, fn, rng, uniq) in enumerate(scores[:6]):
    vals = fn(b5_arr, b6_arr)
    # normalise 0-1 for overlay
    vmin, vmax = vals.min(), vals.max()
    norm = (vals - vmin) / (vmax - vmin + 1e-9)
    ax_cands.plot(ts_arr, norm + i*1.1, lw=0.4, color=cmap(i),
                  label=f"{label}  (rng={rng}, sm={sm:.3f})")
ax_cands.set_title("Top 6 extractions (normalised, stacked, lower=smoother)", fontsize=8)
ax_cands.set_xlabel("Log time (s)", fontsize=8)
ax_cands.set_yticks([])
ax_cands.legend(fontsize=6, loc="upper left")

plt.savefig("projects/vtrux/notes/artifacts/b5b6_bit_analysis.png", dpi=130)
print("\nSaved: projects/vtrux/notes/artifacts/b5b6_bit_analysis.png")

# ---------------------------------------------------------------
# Also print unique B5 values at each B6 step
# ---------------------------------------------------------------
print("\nUnique B5 values at each B6 level:")
by_b6 = collections.defaultdict(set)
for b5, b6 in zip(b5_arr, b6_arr):
    by_b6[int(b6)].add(int(b5))

for b6v in sorted(by_b6):
    vals = sorted(by_b6[b6v])
    print(f"  B6={b6v:3d}: B5 = {vals}  ({len(vals)} unique)")
