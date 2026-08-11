"""
Investigate 0x06000001 B5/B6 as candidate generator motor temperature.

0x06000002 B5/B6 confirmed as traction motor temp (9-bit):
  signal = (B6<<4) | ((B5>>6)<<2) | (B5&3)
  scale 0.5 deg C/count, ~0 = inverter init, ~15C at cold soak

Check if 0x06000001 B5/B6 follows the same bit-packing convention.
Expected: rises while generator runs (early log), cools when generator shuts off.
Negative r vs traction motor temp in t=1500-2550s window (already seen: r=-0.607).
"""

import sys, collections
sys.path.insert(0, ".")
from canre.parsers import parse_file
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

LOG    = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"
PT_BUS = 3
AID_TRAC = 0x06000002   # confirmed traction motor temp
AID_GEN  = 0x06000001   # candidate generator motor temp
SCALE    = 0.5          # deg C per 9-bit count (confirmed for traction)

PUMP_OFF = 393.0
CUTBACK  = 1953.0
PUMP_ON  = 2253.0

print("Parsing...", flush=True)
trac_pts = []
gen_pts  = []
gen_torq = []

for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    t   = frame.timestamp
    b   = frame.data
    aid = frame.arbitration_id

    if aid == AID_TRAC and len(b) >= 7:
        b5, b6 = b[5], b[6]
        raw9 = (b6 << 4) | ((b5 >> 6) << 2) | (b5 & 3)
        trac_pts.append((t, b5, b6, raw9))

    elif aid == AID_GEN and len(b) >= 7:
        b5, b6 = b[5], b[6]
        raw9 = (b6 << 4) | ((b5 >> 6) << 2) | (b5 & 3)
        gen_pts.append((t, b5, b6, raw9))

    elif aid == 0x051 and len(b) >= 3:
        val = (b[1] + 256 * b[2]) - 32768
        gen_torq.append((t, val))

print(f"  traction: {len(trac_pts)} frames, generator candidate: {len(gen_pts)} frames")

def arr(pts, col): return np.array([p[col] for p in pts])

# traction
t_ts   = arr(trac_pts, 0)
t_b6   = arr(trac_pts, 2)
t_raw9 = arr(trac_pts, 3)
t_deg  = t_raw9 * SCALE

# generator candidate
g_ts   = arr(gen_pts, 0)
g_b5   = arr(gen_pts, 1)
g_b6   = arr(gen_pts, 2)
g_raw9 = arr(gen_pts, 3)
g_deg  = g_raw9 * SCALE

# generator torque
gt_ts  = np.array([p[0] for p in gen_torq])
gt_val = np.array([p[1] for p in gen_torq])

# --- Print unique B5 values at each B6 for gen candidate ---
print("\n0x06000001: unique B5 values at each B6 level:")
by_b6 = collections.defaultdict(set)
for b5, b6 in zip(g_b5, g_b6):
    by_b6[int(b6)].add(int(b5))
for b6v in sorted(by_b6):
    vals = sorted(by_b6[b6v])
    print(f"  B6={b6v:3d}: B5 = {vals}  ({len(vals)} unique)")

print(f"\n0x06000001 B6 range: {g_b6.min()}-{g_b6.max()}")
print(f"0x06000001 9-bit raw range: {g_raw9.min()}-{g_raw9.max()}")
print(f"0x06000001 deg range (0.5 scale): {g_deg.min():.1f} - {g_deg.max():.1f} deg C")

# --- Plot ---
fig, axes = plt.subplots(5, 1, figsize=(14, 15), sharex=True)
fig.suptitle(
    "0x06000001 B5/B6 -- Generator motor temp candidate\n"
    "(same 9-bit extraction as confirmed traction motor: (B6<<4)|((B5>>6)<<2)|(B5&3), scale 0.5 deg C/count)",
    fontsize=11
)

ev_kw = dict(lw=1.2, alpha=0.8)
def add_ev(ax):
    ax.axvline(PUMP_OFF, color="orange", ls="--", **ev_kw)
    ax.axvline(CUTBACK,  color="red",    ls="--", **ev_kw)
    ax.axvline(PUMP_ON,  color="green",  ls="--", **ev_kw)

# Row 0: generator torque (context - shows when generator runs)
ax = axes[0]
ax.plot(gt_ts, gt_val, lw=0.4, color="purple", alpha=0.7)
ax.axhline(0, color="gray", lw=0.5)
add_ev(ax)
ax.set_ylabel("Gen torque\n(centered)", fontsize=8)
ax.set_title("Generator torque (0x051 B1-B2) -- context: generator active when non-zero", fontsize=9)

# Row 1: 0x06000001 B6 raw
ax = axes[1]
ax.plot(g_ts, g_b6, lw=0.6, color="darkorange", alpha=0.85)
add_ev(ax)
ax.set_ylabel("B6 raw", fontsize=8)
ax.set_title("0x06000001 B6 (coarse, same byte as traction B6 in sister message)", fontsize=9)

# Row 2: 0x06000001 9-bit raw
ax = axes[2]
ax.plot(g_ts, g_raw9, lw=0.5, color="teal", alpha=0.85)
add_ev(ax)
ax.set_ylabel("9-bit raw", fontsize=8)
ax.set_title("0x06000001 9-bit extraction", fontsize=9)

# Row 3: 0x06000001 deg C vs traction deg C overlay
ax = axes[3]
ax.plot(g_ts,  g_deg, lw=0.6, color="teal",    alpha=0.85, label="0x06000001 (gen candidate)")
ax.plot(t_ts,  t_deg, lw=0.6, color="darkred", alpha=0.6,  label="0x06000002 (traction, confirmed)")
ax.axhline(160, color="orange", ls=":", lw=1, alpha=0.7, label="Remy derate start 160 C")
add_ev(ax)
ax.set_ylabel("Provisional deg C\n(0.5 C/count)", fontsize=8)
ax.set_title("Both motors overlaid -- gen should rise early, cool after gen shuts off", fontsize=9)
ax.legend(fontsize=7, loc="upper left")

# Row 4: B5 scatter-like plot -- unique values check
ax = axes[4]
ax.scatter(g_ts, g_b5, s=0.5, alpha=0.3, color="teal")
add_ev(ax)
ax.set_ylabel("B5 raw", fontsize=8)
ax.set_xlabel("Log time (s)", fontsize=9)
ax.set_title("0x06000001 B5 raw values -- expect 4 bands like traction (0,64,128,192) if same packing", fontsize=9)

plt.tight_layout(rect=[0, 0, 1, 0.94])
out = "projects/vtrux/notes/artifacts/gen_motor_temp_candidate.png"
plt.savefig(out, dpi=130)
print(f"\nSaved: {out}")
