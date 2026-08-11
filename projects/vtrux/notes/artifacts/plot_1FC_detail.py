#!/usr/bin/env python3
"""
Plot 0x1FC detail: B5 alone vs B4<<8|B5 (BE 16-bit) vs EBCM + pedal.
Driveway log: Bus2=Vehicle (has 0x1FC, 0x2F9), Bus3=PT (pedal 0x592)
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

PEDAL_ID        = 0x592
PEDAL_PRESS_THR = 200
PEDAL_MIN_PEAK  = 500

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

# EBCM 0x2F9 B5
raw_ebcm = sorted(
    (t, d[5]) for t, d in bus_data[GM_BUS1].get(0x2F9, []) if len(d) > 5
)
ebcm_times = [x[0] for x in raw_ebcm]
ebcm_vals  = [x[1] for x in raw_ebcm]

# 0x1FC: B5, B4, and B4<<8|B5
entries_1FC = bus_data[GM_BUS1].get(0x1FC, [])
raw_b5    = sorted((t, d[5])            for t, d in entries_1FC if len(d) > 5)
raw_b4    = sorted((t, d[4])            for t, d in entries_1FC if len(d) > 5)
raw_b4b5  = sorted((t, (d[4] << 8) | d[5]) for t, d in entries_1FC if len(d) > 5)

press_events, release_events = find_brake_events(ped_times, ped_vals)
print(f"Press events: {len(press_events)}, Releases: {len(release_events)}", flush=True)
print(f"0x1FC B4<<8|B5  range: {min(v for _,v in raw_b4b5)} - {max(v for _,v in raw_b4b5)}", flush=True)

t0 = ped_times[0] if ped_times else 0
t1 = ped_times[-1] if ped_times else 1

fig, axes = plt.subplots(4, 1, figsize=(18, 14), sharex=True)

labels = [
    ("0x1FC B5 (byte only)",    raw_b5,   "steelblue"),
    ("0x1FC B4 (MSB candidate)", raw_b4,   "purple"),
    ("0x1FC B4<<8|B5 (BE 16-bit)", raw_b4b5, "darkorange"),
    ("EBCM 0x2F9 B5 (reference)", [(t, v) for t, v in zip(ebcm_times, ebcm_vals)], "green"),
]

for ax, (lbl, data, color) in zip(axes, labels):
    times = [x[0] for x in data]
    vals  = [x[1] for x in data]

    for onset, end in press_events:
        ax.axvspan(onset, end, alpha=0.10, color="red", zorder=0)
    for onset, _ in press_events:
        ax.axvline(onset, color="red",   linewidth=0.7, alpha=0.7, linestyle="--")
    for rt in release_events:
        ax.axvline(rt,    color="green", linewidth=0.7, alpha=0.7, linestyle=":")

    ax.plot(times, vals, color=color, linewidth=0.9, label=lbl)
    ax.set_ylabel(lbl, fontsize=8)
    ax.legend(loc="upper right", fontsize=7)
    ax.tick_params(labelsize=7)

    # Pedal on twin axis
    ax2 = ax.twinx()
    ax2.plot(ped_times, ped_vals, color="red", alpha=0.30, linewidth=0.5)
    ax2.set_ylim(-100, 5500)
    ax2.set_ylabel("Pedal", color="red", fontsize=7)
    ax2.tick_params(axis="y", labelcolor="red", labelsize=7)

axes[-1].set_xlabel("Time (s)", fontsize=8)
axes[0].set_title("0x1FC detail: B5 / B4 / B4<<8|B5 vs EBCM + pedal -- driveway log",
                  fontsize=10, fontweight="bold")
axes[0].set_xlim(t0, t1)

plt.tight_layout()
out = ARTIFACT_DIR / "brake_detail_0x1FC.png"
fig.savefig(out, dpi=120, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {out}", flush=True)
