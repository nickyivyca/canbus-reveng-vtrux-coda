"""
Blower speed (0x451 B4) vs coolant temp (0x4C1 B2) -- Part 2 and Part 4.
Part 2: HVAC on/off events at end of log (t~1833s off, t~1985s on).
Part 4: battery-only 2h session, heater running throughout coolant decline.
"""

import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DBC_SCALE = 0.392157  # Climate_Control_Front_Blower_Fan_Speed pct/count
COOLANT_OFFSET = -40  # degC offset (GM convention)


def load_csv(path):
    ts, vals = [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts.append(float(row["timestamp"]))
            vals.append(float(row["value"]))
    return ts, vals


# Load Part 2
bl2_t, bl2_raw = load_csv("blower_part2.csv")
ct2_t, ct2_raw = load_csv("coolant_temp_part2.csv")
bl2_pct = [v * DBC_SCALE for v in bl2_raw]
ct2_c = [v + COOLANT_OFFSET for v in ct2_raw]

# Load Part 4
bl4_t, bl4_raw = load_csv("blower_part4.csv")
ct4_t, ct4_raw = load_csv("coolant_temp_part4.csv")
bl4_pct = [v * DBC_SCALE for v in bl4_raw]
ct4_c = [v + COOLANT_OFFSET for v in ct4_raw]

fig, axes = plt.subplots(2, 2, figsize=(16, 10))
fig.suptitle("Blower Speed vs Coolant Temp -- Part 2 and Part 4", fontsize=14)

# --- Part 2: full log ---
ax = axes[0, 0]
ax2 = ax.twinx()
ax.plot(bl2_t, bl2_pct, color="steelblue", lw=0.8, label="Blower %")
ax2.plot(ct2_t, ct2_c, color="firebrick", lw=1.2, label="Coolant degC")
ax.set_xlabel("Elapsed time (s)")
ax.set_ylabel("Blower speed (%)", color="steelblue")
ax2.set_ylabel("Coolant temp (degC)", color="firebrick")
ax.set_title("Part 2 -- Full log")
ax.axvline(1668.9, color="green", ls="--", lw=1, label="Gen shutoff")
ax.axvline(1833, color="orange", ls="--", lw=1, label="HVAC off")
ax.axvline(1985, color="purple", ls="--", lw=1, label="HVAC on")
ax.legend(loc="upper left", fontsize=8)
ax2.legend(loc="upper right", fontsize=8)
ax.set_ylim(bottom=0)

# --- Part 2: zoomed to HVAC events ---
ax = axes[0, 1]
ax2 = ax.twinx()
t_start, t_end = 1600, max(bl2_t)
bl2_z = [(t, v) for t, v in zip(bl2_t, bl2_pct) if t_start <= t <= t_end]
ct2_z = [(t, v) for t, v in zip(ct2_t, ct2_c) if t_start <= t <= t_end]
if bl2_z:
    ax.plot(*zip(*bl2_z), color="steelblue", lw=1.0, label="Blower %")
if ct2_z:
    ax2.plot(*zip(*ct2_z), color="firebrick", lw=1.5, label="Coolant degC")
ax.set_xlabel("Elapsed time (s)")
ax.set_ylabel("Blower speed (%)", color="steelblue")
ax2.set_ylabel("Coolant temp (degC)", color="firebrick")
ax.set_title("Part 2 -- Zoomed (t=1600s to end)")
ax.axvline(1668.9, color="green", ls="--", lw=1, label="Gen shutoff")
ax.axvline(1833, color="orange", ls="--", lw=1, label="HVAC off")
ax.axvline(1985, color="purple", ls="--", lw=1, label="HVAC on")
ax.legend(loc="upper left", fontsize=8)
ax2.legend(loc="upper right", fontsize=8)
ax.set_ylim(bottom=0)

# --- Part 4: full log ---
ax = axes[1, 0]
ax2 = ax.twinx()
ax.plot(bl4_t, bl4_pct, color="steelblue", lw=0.8, label="Blower %")
ax2.plot(ct4_t, ct4_c, color="firebrick", lw=1.2, label="Coolant degC")
ax.set_xlabel("Elapsed time (s)")
ax.set_ylabel("Blower speed (%)", color="steelblue")
ax2.set_ylabel("Coolant temp (degC)", color="firebrick")
ax.set_title("Part 4 -- Battery-only (~2h, heater on)")
ax.legend(loc="upper left", fontsize=8)
ax2.legend(loc="upper right", fontsize=8)
ax.set_ylim(bottom=0)

# --- Part 4: unique blower values over time (transitions) ---
ax = axes[1, 1]
# Find transitions
prev = None
trans_t, trans_v = [], []
for t, v in zip(bl4_t, bl4_pct):
    if v != prev:
        trans_t.append(t)
        trans_v.append(v)
        prev = v
ax.step(trans_t, trans_v, where="post", color="steelblue", lw=1.5)
ax.set_xlabel("Elapsed time (s)")
ax.set_ylabel("Blower speed (%)")
ax.set_title("Part 4 -- Blower transitions only")
ax.set_ylim(bottom=0)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig("notes/plots/blower_plot.png", dpi=150)
print("Saved blower_plot.png")

# Print summary stats
print("\nPart 2 blower: min={:.1f}% max={:.1f}% unique raw={}".format(
    min(bl2_pct), max(bl2_pct), len(set(bl2_raw))))
print("Part 4 blower: min={:.1f}% max={:.1f}% unique raw={}".format(
    min(bl4_pct), max(bl4_pct), len(set(bl4_raw))))
print("Part 4 blower transitions: {}".format(len(trans_t)))
