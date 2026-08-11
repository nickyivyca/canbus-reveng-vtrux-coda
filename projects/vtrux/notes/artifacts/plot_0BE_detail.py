#!/usr/bin/env python3
"""
Plot 0x0BE detail: all active bytes, color-coded by MUX key (B0 in {0,4,8,12}).
Driveway log: Bus1=OBD (has 0x0BE DLC=6), Bus2=Vehicle, Bus3=PT (pedal)
B5 is top brake correlator (drops from ~255 on press). B0 is 2-bit MUX counter.
"""
import sys, bisect
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
from canre.parsers import parse_file

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

ARTIFACT_DIR = Path(__file__).parent
LOG     = "projects/vtrux/logs/movingaroundindriveway.log"
PT_BUS  = 3
GM_BUS1 = 2   # Vehicle (has 0x2F9 EBCM)
GM_BUS2 = 1   # OBD (has 0x0BE DLC=6)

PEDAL_ID        = 0x592
PEDAL_PRESS_THR = 200
PEDAL_MIN_PEAK  = 500

MUX_COLORS = {0: "#1f77b4", 4: "#ff7f0e", 8: "#2ca02c", 12: "#d62728"}

def find_brake_events(ped_times, ped_vals):
    press_events = []
    release_events = []
    i = 0
    while i < len(ped_times):
        if ped_vals[i] >= PEDAL_PRESS_THR:
            j = i
            while j < len(ped_times) and ped_vals[j] >= PEDAL_PRESS_THR:
                j += 1
            pk = max(ped_vals[i:j])
            if pk >= PEDAL_MIN_PEAK:
                press_events.append((ped_times[i], ped_times[j - 1]))
                k = j
                while k < len(ped_times) and ped_vals[k] > PEDAL_PRESS_THR:
                    k += 1
                if k < len(ped_times):
                    release_events.append(ped_times[k])
            i = j
        else:
            i += 1
    return press_events, release_events

print("Parsing ...", flush=True)
bus_data = defaultdict(lambda: defaultdict(list))
for frame in parse_file(LOG):
    bus_data[frame.bus][frame.arbitration_id].append(
        (frame.timestamp, bytes(frame.data))
    )
print("Done.", flush=True)

# Pedal 16-bit
raw_ped = sorted(
    (t, d[4] | d[5] << 8)
    for t, d in bus_data[PT_BUS].get(PEDAL_ID, [])
    if len(d) > 5
)
ped_times = [x[0] for x in raw_ped]
ped_vals  = [x[1] for x in raw_ped]

# EBCM 0x2F9 B5 on Vehicle bus
raw_ebcm = sorted(
    (t, d[5]) for t, d in bus_data[GM_BUS1].get(0x2F9, []) if len(d) > 5
)
ebcm_times = [x[0] for x in raw_ebcm]
ebcm_vals  = [x[1] for x in raw_ebcm]

# 0x0BE from OBD bus (DLC=6 frames only)
entries_0BE = [(t, d) for t, d in bus_data[GM_BUS2].get(0x0BE, []) if len(d) >= 6]
print(f"0x0BE DLC>=6 frames: {len(entries_0BE)}", flush=True)

# Split by MUX key (B0) — active bytes: B1, B4, B5
mux_vals = set(d[0] for _, d in entries_0BE)
print(f"B0 (MUX key) unique values: {sorted(mux_vals)}", flush=True)

# Build per-byte timeseries, colored by MUX key
# Bytes to plot: 1, 4, 5 (B2=0-3 sparse, B3=always 0 — skip)
BYTES_TO_PLOT = [1, 4, 5]

press_events, release_events = find_brake_events(ped_times, ped_vals)
print(f"Press events: {len(press_events)}, Releases: {len(release_events)}", flush=True)

t0 = ped_times[0] if ped_times else 0
t1 = ped_times[-1] if ped_times else 1

fig, axes = plt.subplots(len(BYTES_TO_PLOT) + 1, 1, figsize=(18, 4 * (len(BYTES_TO_PLOT) + 1)), sharex=True)

# Reference panel: EBCM + pedal
ax_ref = axes[0]
for onset, end in press_events:
    ax_ref.axvspan(onset, end, alpha=0.10, color="red", zorder=0)
for onset, _ in press_events:
    ax_ref.axvline(onset, color="red",   linewidth=0.7, alpha=0.7, linestyle="--")
for rt in release_events:
    ax_ref.axvline(rt,    color="green", linewidth=0.7, alpha=0.7, linestyle=":")
ax_ref.plot(ebcm_times, ebcm_vals, color="green", linewidth=0.9, label="EBCM 0x2F9 B5")
ax_ref.set_ylabel("EBCM pressure\n(0-255)", fontsize=8)
ax_ref.legend(loc="upper right", fontsize=7)
ax_ref2 = ax_ref.twinx()
ax_ref2.plot(ped_times, ped_vals, color="red", alpha=0.35, linewidth=0.5)
ax_ref2.set_ylim(-100, 5500)
ax_ref2.set_ylabel("Pedal", color="red", fontsize=7)
ax_ref2.tick_params(axis="y", labelcolor="red", labelsize=7)
ax_ref.set_title("0x0BE detail (OBD bus, DLC=6) -- driveway log\nMUX key B0 in {0,4,8,12}",
                 fontsize=10, fontweight="bold")
ax_ref.tick_params(labelsize=7)

# Per-byte panels, scatter-colored by MUX key
for ax, bi in zip(axes[1:], BYTES_TO_PLOT):
    for onset, end in press_events:
        ax.axvspan(onset, end, alpha=0.10, color="red", zorder=0)
    for onset, _ in press_events:
        ax.axvline(onset, color="red",   linewidth=0.7, alpha=0.7, linestyle="--")
    for rt in release_events:
        ax.axvline(rt,    color="green", linewidth=0.7, alpha=0.7, linestyle=":")

    for mux_key in sorted(mux_vals):
        pts = sorted((t, d[bi]) for t, d in entries_0BE if d[0] == mux_key)
        if not pts:
            continue
        ts = [x[0] for x in pts]
        vs = [x[1] for x in pts]
        color = MUX_COLORS.get(mux_key, "gray")
        ax.scatter(ts, vs, s=1.5, color=color, alpha=0.6, label=f"B0={mux_key}", zorder=2)

    ax.set_ylabel(f"B{bi}", fontsize=8)
    ax.legend(loc="upper right", fontsize=7, markerscale=5)
    ax.tick_params(labelsize=7)

    ax2 = ax.twinx()
    ax2.plot(ped_times, ped_vals, color="red", alpha=0.25, linewidth=0.5)
    ax2.set_ylim(-100, 5500)
    ax2.set_ylabel("Pedal", color="red", fontsize=7)
    ax2.tick_params(axis="y", labelcolor="red", labelsize=7)

axes[-1].set_xlabel("Time (s)", fontsize=8)
axes[0].set_xlim(t0, t1)

plt.tight_layout()
out = ARTIFACT_DIR / "brake_detail_0x0BE.png"
fig.savefig(out, dpi=120, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {out}", flush=True)
