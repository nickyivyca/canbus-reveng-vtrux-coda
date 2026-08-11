#!/usr/bin/env python3
"""
Full-log plots of top brake booster candidates from movingaroundindriveway.log.
Bus 1=OBD, Bus 2=Vehicle, Bus 3=PT
Candidates: 0x0F1 B0, 0x0BE B5, 0x0BE B1, 0x651 B4, 0x050 B0, 0x390 B3, 0x1C7 B3, 0x1E9 B0
"""
import sys, bisect
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from canre.parsers import parse_file

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ARTIFACT_DIR = Path(__file__).parent
LOG     = "projects/vtrux/logs/movingaroundindriveway.log"
PT_BUS  = 3
GM_BUS1 = 2   # Vehicle
GM_OBD  = 1   # OBD

PEDAL_ID   = 0x592
PEDAL_BYTE = 4
PRESS_THR  = 30
MIN_PEAK   = 60

# (bus, can_id, byte, label)
CANDIDATES = [
    (GM_OBD,  0x0F1, 0, "0x0F1 B0 (OBD)   RecSc=1.00"),
    (GM_BUS1, 0x0BE, 5, "0x0BE B5 (GM Veh) r_ebcm=-0.80 [evap]"),
    (GM_BUS1, 0x0BE, 1, "0x0BE B1 (GM Veh) r_ebcm=+0.57 [evap]"),
    (PT_BUS,  0x651, 4, "0x651 B4 (PT)     RecSc=1.00"),
    (PT_BUS,  0x050, 0, "0x050 B0 (PT)     RecSc=0.93"),
    (GM_BUS1, 0x1E9, 0, "0x1E9 B0 (GM Veh) Pr_ped=0.50"),
    (GM_BUS1, 0x1C7, 3, "0x1C7 B3 (GM Veh) RecSc=1.00"),
    (PT_BUS,  0x390, 3, "0x390 B3 (PT)     RecSc=0.82"),
]

print("Parsing ...", flush=True)
bus_data = defaultdict(lambda: defaultdict(list))
for frame in parse_file(LOG):
    bus_data[frame.bus][frame.arbitration_id].append(
        (frame.timestamp, bytes(frame.data))
    )
print("Done.", flush=True)

def sorted_ts(bus, can_id):
    return sorted(bus_data[bus].get(can_id, []))

def get_byte_ts(bus, can_id, bi):
    raw = sorted_ts(bus, can_id)
    ts = [(t, d[bi]) for t,d in raw if len(d) > bi]
    return [x[0] for x in ts], [x[1] for x in ts]

# Pedal
raw_ped   = sorted_ts(PT_BUS, PEDAL_ID)
ped_times = [t for t,d in raw_ped if len(d) > PEDAL_BYTE]
ped_vals  = [d[PEDAL_BYTE] for t,d in raw_ped if len(d) > PEDAL_BYTE]

# EBCM pressure (0x2F9 B5, Vehicle bus)
raw_ebcm   = sorted_ts(GM_BUS1, 0x2F9)
ebcm_times = [t for t,d in raw_ebcm if len(d) > 5]
ebcm_vals  = [d[5] for t,d in raw_ebcm if len(d) > 5]

# Brake press intervals
press_intervals = []
i = 0
while i < len(ped_times):
    if ped_vals[i] >= PRESS_THR:
        j = i
        while j < len(ped_times) and ped_vals[j] >= PRESS_THR:
            j += 1
        if max(ped_vals[i:j]) >= MIN_PEAK:
            k = j
            while k < len(ped_times) and ped_vals[k] > 5:
                k += 1
            press_intervals.append((ped_times[i], ped_times[k] if k < len(ped_times) else ped_times[j-1]))
        i = j
    else:
        i += 1

t0 = ped_times[0]
t1 = ped_times[-1]

ncols = 2
# +1 row for shared pedal+EBCM panel at top
n_cand_rows = (len(CANDIDATES) + ncols - 1) // ncols
nrows = n_cand_rows + 1

fig = plt.figure(figsize=(20, 2.5 + 3.0 * n_cand_rows))
# top row spans both columns: pedal + EBCM reference
ax_ref = fig.add_subplot(nrows, 1, 1)
ax_ref.plot(ped_times, ped_vals, color="red", linewidth=0.8, label="Brake pedal (0x592 B4)")
if ebcm_times:
    ax_ref2 = ax_ref.twinx()
    ax_ref2.plot(ebcm_times, ebcm_vals, color="green", linewidth=0.8, alpha=0.8,
                 label="EBCM pressure (0x2F9 B5, x75 kPa)")
    ax_ref2.set_ylim(-2, 85)
    ax_ref2.set_ylabel("EBCM (x75 kPa)", color="green", fontsize=8)
    ax_ref2.tick_params(axis="y", labelcolor="green", labelsize=7)
# mark brake onsets as thin vertical lines
for ws, we in press_intervals:
    ax_ref.axvline(ws, color="red",   linewidth=0.5, alpha=0.5, zorder=2)
    ax_ref.axvline(we, color="orange", linewidth=0.5, alpha=0.5, zorder=2)
ax_ref.set_xlim(t0, t1)
ax_ref.set_ylabel("Pedal raw", color="red", fontsize=8)
ax_ref.tick_params(axis="y", labelcolor="red", labelsize=7)
ax_ref.tick_params(axis="x", labelsize=7)
ax_ref.set_title("Reference: brake pedal (red) + EBCM pressure (green) | "
                 "red tick=onset, orange tick=release", fontsize=8)
ax_ref.legend(loc="upper right", fontsize=7)

# candidate subplots
for idx, (bus, can_id, bi, clabel) in enumerate(CANDIDATES):
    row = idx // ncols + 1   # offset by 1 for ref row
    col = idx % ncols
    # use gridspec-style positioning
    ax = fig.add_subplot(nrows, ncols, ncols * row + col + 1)

    ctimes, cvals = get_byte_ts(bus, can_id, bi)

    # thin vertical lines at brake events (not filled spans)
    for ws, we in press_intervals:
        ax.axvline(ws, color="salmon", linewidth=0.5, alpha=0.6, zorder=1)
        ax.axvline(we, color="bisque", linewidth=0.5, alpha=0.8, zorder=1)

    if ctimes:
        ax.plot(ctimes, cvals, color="steelblue", linewidth=1.0, zorder=3)
    else:
        ax.text(0.5, 0.5, "NO DATA IN THIS LOG", transform=ax.transAxes,
                ha="center", va="center", color="gray", fontsize=9)

    ax.set_xlim(t0, t1)
    ax.set_title(clabel, fontsize=8)
    ax.tick_params(labelsize=7)
    if col == 0:
        ax.set_ylabel("Value", fontsize=8)
    if row == nrows - 1:
        ax.set_xlabel("Time (s)", fontsize=8)

fig.suptitle("Brake booster candidates -- movingaroundindriveway.log\n"
             "red tick=brake onset, orange tick=brake release",
             fontsize=10, fontweight="bold")
plt.tight_layout(rect=[0, 0, 1, 0.97])
out = ARTIFACT_DIR / "brake_driveway_candidates.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {out}", flush=True)
