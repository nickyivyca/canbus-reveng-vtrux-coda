"""
plot_483_b1_carry.py

Investigate 0x483 B1 overflow / MSB carry structure.

Panels:
  1. B0  (known coarse temp, raw-100=C)
  2. B1  (raw -- sawtooth overflow)
  3. B2[0]  (carry bit from B1)
  4. B2[7:4] (upper nibble -- zone/wider counter?)
  5. B2 full byte
  6. (B2[0]<<8)|B1  -- 9-bit decode (existing notes)
  7. (B2[7:4]<<9)|(B2[0]<<8)|B1  -- 13-bit hypothesis (B2 upper nibble as higher carry)
  8. B3  (to check if carry from B2 bleeds into B3)
  9. B4, B5, B6, B7 for completeness

Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/plot_483_b1_carry.py
"""

import sys
sys.path.insert(0, '.')
from canre.parsers import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LOG = "projects/vtrux/logs/vtruxgeneratoroverheattest.log"
OUT = "projects/vtrux/notes/artifacts/483_b1_carry.png"

# ---------------------------------------------------------------------------
# Collect 0x483 frames from PT bus
# ---------------------------------------------------------------------------
print("Pass 1: finding PT bus ...")
pt_bus = None
for frame in parse_file(LOG):
    if frame.arbitration_id == 0x051:
        pt_bus = frame.bus
        break
print(f"  PT bus = {pt_bus}")

print("Pass 2: collecting 0x483 frames ...")
frames = []
for frame in parse_file(LOG):
    if frame.bus == pt_bus and frame.arbitration_id == 0x483:
        frames.append((frame.timestamp, bytes(frame.data)))
print(f"  {len(frames)} frames")

ts  = [f[0] for f in frames]
raw = [f[1] for f in frames]

# ---------------------------------------------------------------------------
# Build signals
# ---------------------------------------------------------------------------
b0 = [d[0] for d in raw]
b1 = [d[1] for d in raw]
b2 = [d[2] for d in raw]
b3 = [d[3] for d in raw]
b4 = [d[4] for d in raw]
b5 = [d[5] for d in raw]
b6 = [d[6] for d in raw]
b7 = [d[7] for d in raw]

b2_carry   = [v & 0x01         for v in b2]   # bit 0
b2_nibble  = [(v >> 4) & 0x0F  for v in b2]   # upper nibble [7:4]
b2_mid     = [(v >> 1) & 0x07  for v in b2]   # bits [3:1] -- expected constant

nine_bit   = [(b2[i] & 0x01) << 8 | b1[i]              for i in range(len(ts))]
thirteen_bit = [((b2[i] >> 4) & 0x0F) << 9 | (b2[i] & 0x01) << 8 | b1[i]
                for i in range(len(ts))]

# Verify B2 middle bits are constant
mid_vals = set(b2_mid)
print(f"  B2[3:1] unique values: {sorted(mid_vals)}  (expect {{4}} = always 0b100)")

# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------
panels = [
    (b0,           "B0 raw\n(known temp, raw-100=C)",           '#2ca02c', None),
    (b1,           "B1 raw\n(overflowing fine byte)",            '#d62728', None),
    (b2_carry,     "B2[0] carry bit\n(MSB of 9-bit)",           '#ff7f0e', None),
    (b2_nibble,    "B2[7:4] upper nibble\n(zone / wider carry?)",'#9467bd', None),
    (b2,           "B2 full byte",                               '#8c564b', None),
    (nine_bit,     "9-bit: (B2[0]<<8)|B1\n(existing notes decode)", '#1f77b4', None),
    (thirteen_bit, "13-bit hypothesis:\n(B2[7:4]<<9)|(B2[0]<<8)|B1", '#e377c2', None),
    (b3,           "B3 raw\n(carry from B2 into B3?)",          '#7f7f7f', None),
    (b4,           "B4 raw",                                     '#bcbd22', None),
    (b5,           "B5 raw",                                     '#17becf', None),
    (b6,           "B6 raw",                                     '#aec7e8', None),
    (b7,           "B7 raw\n(4 unique: 13-16)",                  '#ffbb78', None),
]

n = len(panels)
fig, axes = plt.subplots(n, 1, figsize=(22, n * 1.6), sharex=True)
fig.suptitle("0x483 B1 carry structure -- vtruxgeneratoroverheattest.log\n"
             "Investigating MSBs for overflowing B1", fontsize=11)

for i, (vals, label, color, _) in enumerate(panels):
    ax = axes[i]
    ax.plot(ts, vals, color=color, linewidth=0.8, rasterized=True)
    ax.set_ylabel(label, fontsize=7.5, rotation=0, ha='right', va='center', labelpad=4)
    ax.yaxis.set_label_coords(-0.01, 0.5)
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.08 if hi > lo else 0.5
    ax.set_ylim(lo - pad, hi + pad)
    ax.tick_params(axis='y', labelsize=6)
    ax.tick_params(axis='x', labelsize=6)
    ax.grid(axis='x', linestyle=':', linewidth=0.4, alpha=0.5)

    # annotate range
    ax.text(0.995, 0.85, f"range {lo}-{hi}  uniq={len(set(vals))}",
            transform=ax.transAxes, fontsize=6, ha='right', va='top',
            color='#444', style='italic')

axes[-1].set_xlabel("Time (s)", fontsize=8)

plt.tight_layout(rect=[0.14, 0, 1, 0.995])
print(f"Saving {OUT} ...")
fig.savefig(OUT, dpi=120, bbox_inches='tight')
plt.close(fig)
print("Done.")

# Print summary stats
print("\n--- Signal ranges ---")
print(f"9-bit  (B2[0]<<8)|B1:               {min(nine_bit)}-{max(nine_bit)}")
print(f"13-bit (B2[7:4]<<9)|(B2[0]<<8)|B1:  {min(thirteen_bit)}-{max(thirteen_bit)}")
print(f"B2 nibble range: {min(b2_nibble)}-{max(b2_nibble)}")
