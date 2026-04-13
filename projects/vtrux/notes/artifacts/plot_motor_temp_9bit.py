"""
Plot the 9-bit motor temperature signal extracted from 0x06000002 B5/B6.

Encoding confirmed by bit-level analysis:
  signal = (B6 << 4) | ((B5 >> 6) << 2) | (B5 & 3)
         = B6*16 + (B5>>6)*4 + (B5&3)

  B5 bits [5:2] are constant (always 001x pattern: bit5=1, bits4-2=0).
  Only B5[7:6] and B5[1:0] carry temperature data.

Scale (provisional): B6 alone ~10 deg C/count => 9-bit ~0.625 deg C/count.
"""

import sys
sys.path.insert(0, ".")
from canre.parsers import parse_file
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

LOG    = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"
PT_BUS = 3
AID    = 0x06000002

PUMP_OFF = 393.0
CUTBACK  = 1953.0
PUMP_ON  = 2253.0

# Remy derate thresholds (from motor manual)
DERATE_START_C = 160.0
DERATE_FULL_C  = 180.0

SCALE_DEG_PER_COUNT = 0.5   # provisional

print("Parsing...", flush=True)
pts = []
for frame in parse_file(LOG):
    if frame.bus != PT_BUS or frame.arbitration_id != AID:
        continue
    if len(frame.data) < 7:
        continue
    b5, b6 = frame.data[5], frame.data[6]
    raw9 = (b6 << 4) | ((b5 >> 6) << 2) | (b5 & 3)
    pts.append((frame.timestamp, b6, raw9))

ts  = np.array([p[0] for p in pts])
b6  = np.array([p[1] for p in pts])
raw = np.array([p[2] for p in pts])
deg = raw * SCALE_DEG_PER_COUNT

print(f"  {len(pts)} frames", flush=True)
print(f"  B6 range: {b6.min()}-{b6.max()}")
print(f"  9-bit raw range: {raw.min()}-{raw.max()}  ({raw.min()*SCALE_DEG_PER_COUNT:.1f} - {raw.max()*SCALE_DEG_PER_COUNT:.1f} deg C provisional)")

fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)
fig.suptitle(
    "0x06000002 B5/B6 Motor Temperature -- 9-bit extraction\n"
    "signal = (B6<<4) | ((B5>>6)<<2) | (B5&3)    scale 0.5 deg C/count (provisional)",
    fontsize=11
)

ev_kw = dict(lw=1.2, alpha=0.85, zorder=5)

def add_events(ax):
    ax.axvline(PUMP_OFF, color="orange", ls="--", lw=1.2, alpha=0.8, label=f"pump off (t={PUMP_OFF:.0f}s)")
    ax.axvline(CUTBACK,  color="red",    ls="--", lw=1.2, alpha=0.8, label=f"torque cutback (t={CUTBACK:.0f}s)")
    ax.axvline(PUMP_ON,  color="green",  ls="--", lw=1.2, alpha=0.8, label=f"pump on (t={PUMP_ON:.0f}s)")

# --- Row 0: B6 coarse for comparison ---
ax = axes[0]
ax.plot(ts, b6, lw=0.6, color="brown", alpha=0.8, label="B6 (coarse, ~10 deg C/count)")
add_events(ax)
ax.set_ylabel("B6 raw (counts)", fontsize=9)
ax.set_title("B6 alone (reference, low-res)", fontsize=9)
ax.legend(fontsize=7, loc="upper left")

# --- Row 1: 9-bit raw ---
ax = axes[1]
ax.plot(ts, raw, lw=0.5, color="steelblue", alpha=0.85, label="9-bit signal (raw counts)")
add_events(ax)
ax.set_ylabel("9-bit raw (counts)", fontsize=9)
ax.set_title("9-bit extraction: (B6<<4)|((B5>>6)<<2)|(B5&3)  -- range ~0-335", fontsize=9)
ax.legend(fontsize=7, loc="upper left")

# --- Row 2: scaled to degrees (provisional) ---
ax = axes[2]
ax.plot(ts, deg, lw=0.5, color="darkred", alpha=0.85, label="9-bit x 0.625 deg C/count (provisional)")
ax.axhline(DERATE_START_C, color="orange", ls=":", lw=1.2, alpha=0.9, label=f"Remy derate start ({DERATE_START_C:.0f} deg C)")
ax.axhline(DERATE_FULL_C,  color="red",    ls=":", lw=1.2, alpha=0.9, label=f"Remy derate full ({DERATE_FULL_C:.0f} deg C)")
add_events(ax)
ax.set_ylabel("Provisional temp (deg C)", fontsize=9)
ax.set_xlabel("Log time (s)", fontsize=9)
ax.set_title("Scaled to deg C -- scale UNCONFIRMED; shown to check plausibility vs Remy derate thresholds", fontsize=9)
ax.legend(fontsize=7, loc="upper left")

plt.tight_layout(rect=[0, 0, 1, 0.94])
out = "projects/vtrux/notes/artifacts/motor_temp_9bit.png"
plt.savefig(out, dpi=130)
print(f"Saved: {out}")
