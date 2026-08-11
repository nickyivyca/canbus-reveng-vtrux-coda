"""
Plot motor temperature candidates from the drivetrain overheat test.
Candidates: 0x06000002 B6 (ref), 0x06000002 B5:6 LE (16-bit pair),
            0x63F B3, 0x0C0CA040 LE 2:3 (negative corr)
Context:    Generator torque (0x051 B1-B2 LE centered), drive torque (0x5A2 B4-B5 LE centered)
"""

import sys, collections
sys.path.insert(0, ".")
from canre.parsers import parse_file
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

LOG    = "projects/vtrux/logs/vtruxdrivetrainoverheattest.log"
PT_BUS = 3

# Event markers (seconds from log start)
PUMP_OFF      = 393.0   # pump physically unplugged
CUTBACK       = 1953.0  # torque cutback onset
PUMP_ON       = 2253.0  # pump reconnected

print("Parsing log...", flush=True)

# Accumulators  {signal_key: [(t, value), ...]}
data = collections.defaultdict(list)

for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    t  = frame.timestamp
    b  = frame.data
    aid = frame.arbitration_id

    if aid == 0x06000002 and len(b) >= 7:
        data["B6_ref"].append((t, b[6]))
        le56 = b[5] + 256 * b[6]
        data["B5B6_LE16"].append((t, le56))

    elif aid == 0x0000063F and len(b) >= 4:
        data["63F_B3"].append((t, b[3]))

    elif aid == 0x0C0CA040 and len(b) >= 4:
        le23 = b[2] + 256 * b[3]
        data["0C0CA040_LE23"].append((t, le23))

    # Context signals
    elif aid == 0x051 and len(b) >= 3:
        val = (b[1] + 256 * b[2]) - 32768
        data["gen_torque"].append((t, val))

    elif aid == 0x5A2 and len(b) >= 6:
        val = (b[4] + 256 * b[5]) - 32768
        data["drive_torque"].append((t, val))

print("Plotting...", flush=True)

def ts(key):
    pts = data[key]
    return [p[0] for p in pts], [p[1] for p in pts]

fig, axes = plt.subplots(6, 1, figsize=(14, 18), sharex=True)
fig.suptitle("Drivetrain Overheat Test -- Motor Temp Candidates\n(vtruxdrivetrainoverheattest.log, PT Bus 3)", fontsize=12)

ev_kw = dict(lw=1.2, alpha=0.8)

def add_events(ax):
    ax.axvline(PUMP_OFF,  color="orange", ls="--", label="pump off",  **ev_kw)
    ax.axvline(CUTBACK,   color="red",    ls="--", label="cutback",   **ev_kw)
    ax.axvline(PUMP_ON,   color="green",  ls="--", label="pump on",   **ev_kw)

# --- 0: generator torque (context) ---
ax = axes[0]
tx, ty = ts("gen_torque")
ax.plot(tx, ty, lw=0.4, color="purple", alpha=0.6)
ax.axhline(0, color="gray", lw=0.5)
add_events(ax)
ax.set_ylabel("Gen torque\n(0x051 B1-B2\ncentered)", fontsize=8)
ax.set_title("Generator torque (context -- >0 = backdriving, <0 = generating)", fontsize=9)

# --- 1: drive torque (context) ---
ax = axes[1]
tx, ty = ts("drive_torque")
ax.plot(tx, ty, lw=0.4, color="teal", alpha=0.6)
ax.axhline(0, color="gray", lw=0.5)
add_events(ax)
ax.set_ylabel("Drive torque\n(0x5A2 B4-B5\ncentered)", fontsize=8)
ax.set_title("Traction torque feedback (context -- cutback should appear here as ceiling)", fontsize=9)

# --- 2: B6 reference ---
ax = axes[2]
tx, ty = ts("B6_ref")
ax.plot(tx, ty, lw=0.8, color="brown")
add_events(ax)
ax.set_ylabel("raw (counts)", fontsize=8)
ax.set_title("0x06000002 B6  -- low-res motor temp reference (~10 deg C/count)", fontsize=9)

# --- 3: B5:B6 LE 16-bit ---
ax = axes[3]
tx, ty = ts("B5B6_LE16")
ax.plot(tx, ty, lw=0.8, color="darkorange")
add_events(ax)
ax.set_ylabel("raw (counts)", fontsize=8)
ax.set_title("0x06000002 B5:B6 LE uint16  (r=0.9981 vs B6 in window; B5 mostly constant ~160)", fontsize=9)

# --- 4: 0x63F B3 ---
ax = axes[4]
tx, ty = ts("63F_B3")
ax.plot(tx, ty, lw=0.8, color="steelblue")
add_events(ax)
ax.set_ylabel("raw (counts)", fontsize=8)
ax.set_title("0x63F B3  (r=0.9428 vs B6 in post-gen window t=1500-2550s)", fontsize=9)

# --- 5: 0x0C0CA040 LE 2:3 ---
ax = axes[5]
tx, ty = ts("0C0CA040_LE23")
ax.plot(tx, ty, lw=0.8, color="navy")
add_events(ax)
ax.set_ylabel("raw (counts)", fontsize=8)
ax.set_title("0x0C0CA040 LE B2:B3  (r=-0.8340 vs B6 in window; negative corr)", fontsize=9)
ax.set_xlabel("Log time (s)", fontsize=9)

# Shared legend
handles = [
    mpatches.Patch(color="orange", label="pump off (t=393s)"),
    mpatches.Patch(color="red",    label="torque cutback (t=1953s)"),
    mpatches.Patch(color="green",  label="pump reconnected (t=2253s)"),
]
fig.legend(handles=handles, loc="upper right", fontsize=8, framealpha=0.8)

plt.tight_layout(rect=[0, 0, 1, 0.96])
out = "projects/vtrux/notes/artifacts/motor_temp_candidates.png"
plt.savefig(out, dpi=130)
print(f"Saved: {out}")
