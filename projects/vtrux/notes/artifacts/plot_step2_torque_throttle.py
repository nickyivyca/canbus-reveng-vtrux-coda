"""
Step 2 plot: throttle pedal + 0x5A2 torque signal vs time.
Key events marked: pump disconnect, cutback onset, pump reconnect.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from canre.parsers import parse_file

LOG = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"

# Wall-clock anchor: log start 20:12:27 => events at these log offsets
PUMP_OFF  = 393   # 8:19 PM
CUTBACK   = 1953  # ~8:45 PM
PUMP_ON   = 2253  # ~8:50 PM

throttle_t, throttle_v = [], []   # 0x592 B2-B3 LE uint16
torq_b23_t, torq_b23_v = [], []   # 0x5A2 B2-B3  (offset binary, center=32768)
torq_b45_t, torq_b45_v = [], []   # 0x5A2 B4-B5  (offset binary, center=32768)

for frame in parse_file(LOG):
    t = frame.timestamp
    b = frame.data

    if frame.arbitration_id == 0x592 and frame.bus == 3:
        val = b[2] | (b[3] << 8)
        throttle_t.append(t)
        throttle_v.append(val)

    elif frame.arbitration_id == 0x5A2 and frame.bus == 3:
        b23 = (b[2] | (b[3] << 8)) - 32768
        b45 = (b[4] | (b[5] << 8)) - 32768
        torq_b23_t.append(t)
        torq_b23_v.append(b23)
        torq_b45_t.append(t)
        torq_b45_v.append(b45)

print(f"Throttle samples: {len(throttle_t)}")
print(f"0x5A2 B2-B3 samples: {len(torq_b23_t)}")
print(f"0x5A2 B4-B5 samples: {len(torq_b45_t)}")

# Downsample for plotting (every 5th point to keep file manageable)
def ds(t, v, n=5):
    return t[::n], v[::n]

fig, axes = plt.subplots(3, 1, figsize=(18, 10), sharex=True)
fig.suptitle("Drivetrain Overheat Test -- Throttle and 0x5A2 Torque Signals\n"
             "(log start 8:12:27 PM; pump off @393s, cutback @1953s, pump on @2253s)",
             fontsize=11)

events = [
    (PUMP_OFF,  "pump off",   "orange"),
    (CUTBACK,   "cutback",    "red"),
    (PUMP_ON,   "pump on",    "green"),
]

# --- subplot 1: throttle ---
ax = axes[0]
tt, tv = ds(throttle_t, throttle_v)
ax.plot(tt, tv, color="steelblue", linewidth=0.6, label="Throttle (0x592 B2-B3 LE)")
for x, lbl, c in events:
    ax.axvline(x, color=c, linewidth=1.2, linestyle="--", label=lbl)
ax.set_ylabel("Raw counts")
ax.set_title("Throttle Position (0x592 B2-B3 LE uint16)")
ax.legend(fontsize=8, loc="upper right")
ax.grid(True, alpha=0.3)

# --- subplot 2: 0x5A2 B2-B3 ---
ax = axes[1]
t23, v23 = ds(torq_b23_t, torq_b23_v)
ax.plot(t23, v23, color="darkgreen", linewidth=0.6, label="0x5A2 B2-B3 offset-binary (center=0)")
for x, lbl, c in events:
    ax.axvline(x, color=c, linewidth=1.2, linestyle="--")
ax.axhline(0, color="gray", linewidth=0.5)
ax.set_ylabel("Signed counts")
ax.set_title("0x5A2 B2-B3 (offset binary, 0=center)")
ax.legend(fontsize=8, loc="upper right")
ax.grid(True, alpha=0.3)

# --- subplot 3: 0x5A2 B4-B5 ---
ax = axes[2]
t45, v45 = ds(torq_b45_t, torq_b45_v)
ax.plot(t45, v45, color="firebrick", linewidth=0.6, label="0x5A2 B4-B5 offset-binary (center=0)")
for x, lbl, c in events:
    ax.axvline(x, color=c, linewidth=1.2, linestyle="--")
ax.axhline(0, color="gray", linewidth=0.5)
ax.set_ylabel("Signed counts")
ax.set_xlabel("Log time (seconds from start; 0s = 8:12:27 PM)")
ax.set_title("0x5A2 B4-B5 (offset binary, 0=center)")
ax.legend(fontsize=8, loc="upper right")
ax.grid(True, alpha=0.3)

plt.tight_layout()
out = "projects/vtrux/notes/artifacts/step2_torque_throttle.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved: {out}")
