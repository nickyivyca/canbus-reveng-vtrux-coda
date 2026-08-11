#!/usr/bin/env python3
"""
Two-part brake booster recovery analysis -- driveway log.

Part 1: 0x0F1 full-log detail (B0, B1 vs reference)
Part 2: Release-event superposition for top candidates.
  For each candidate, all 11 release events are overlaid, time-aligned to
  the moment the pedal drops below threshold. This reveals slow recovery curves.

Candidates compared:
  - 0x0F1 B0  (Bus2/Vehicle, highest recovery score 0.700, coarse quantized)
  - 0x1FC BE16 B4<<8|B5  (Bus2/Vehicle, applied pressure)
  - 0x0BE B5  (Bus1/OBD, inverted -- drops on press)
  - Pedal 16-bit (reference)

Driveway log bus assignments: Bus1=OBD, Bus2=Vehicle, Bus3=PT
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
GM_BUS2 = 1   # OBD

PEDAL_ID        = 0x592
PEDAL_PRESS_THR = 200
PEDAL_MIN_PEAK  = 500

ZOOM_PRE  = 3.0   # seconds before release to show
ZOOM_POST = 8.0   # seconds after release to show

def values_in_window(start_t, end_t, times, vals):
    lo = bisect.bisect_left(times, start_t)
    hi = bisect.bisect_right(times, end_t)
    return times[lo:hi], vals[lo:hi]

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
                    release_events.append((ped_times[i], ped_times[k]))  # (onset_t, release_t)
            i = j
        else:
            i += 1
    return press_events, release_events

# ------------------------------------------------------------------ parse

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

# EBCM
raw_ebcm = sorted(
    (t, d[5]) for t, d in bus_data[GM_BUS1].get(0x2F9, []) if len(d) > 5
)
ebcm_times = [x[0] for x in raw_ebcm]
ebcm_vals  = [x[1] for x in raw_ebcm]

# 0x0F1 B0, B1 -- Vehicle bus
entries_0F1 = bus_data[GM_BUS1].get(0x0F1, [])
raw_0F1_b0 = sorted((t, d[0]) for t, d in entries_0F1 if len(d) > 0)
raw_0F1_b1 = sorted((t, d[1]) for t, d in entries_0F1 if len(d) > 1)
raw_0F1_b2 = sorted((t, d[2]) for t, d in entries_0F1 if len(d) > 2)
f1b0_t, f1b0_v = [x[0] for x in raw_0F1_b0], [x[1] for x in raw_0F1_b0]
f1b1_t, f1b1_v = [x[0] for x in raw_0F1_b1], [x[1] for x in raw_0F1_b1]
f1b2_t, f1b2_v = [x[0] for x in raw_0F1_b2], [x[1] for x in raw_0F1_b2]

# 0x1FC B4<<8|B5 BE16 -- Vehicle bus
entries_1FC = bus_data[GM_BUS1].get(0x1FC, [])
raw_1FC = sorted((t, (d[4] << 8) | d[5]) for t, d in entries_1FC if len(d) > 5)
fc_t, fc_v = [x[0] for x in raw_1FC], [x[1] for x in raw_1FC]

# 0x0BE B5 -- OBD bus
entries_0BE = [(t, d) for t, d in bus_data[GM_BUS2].get(0x0BE, []) if len(d) >= 6]
raw_0BE = sorted((t, d[5]) for t, d in entries_0BE)
be_t, be_v = [x[0] for x in raw_0BE], [x[1] for x in raw_0BE]

press_events, release_events = find_brake_events(ped_times, ped_vals)
print(f"Press events: {len(press_events)}, Releases with window: {len(release_events)}", flush=True)

t0 = ped_times[0]
t1 = ped_times[-1]

# ======================================================== Part 1: 0x0F1 detail

fig1, axes1 = plt.subplots(3, 1, figsize=(18, 10), sharex=True)

for ax in axes1:
    for onset, end in press_events:
        ax.axvspan(onset, end, alpha=0.10, color="red", zorder=0)
    for onset, _ in press_events:
        ax.axvline(onset, color="red",   linewidth=0.7, alpha=0.6, linestyle="--")
    for _, rel in release_events:
        ax.axvline(rel,   color="green", linewidth=0.7, alpha=0.6, linestyle=":")

    ax2 = ax.twinx()
    ax2.plot(ped_times, ped_vals, color="red", alpha=0.25, linewidth=0.5)
    ax2.set_ylim(-100, 5500)
    ax2.set_ylabel("Pedal", color="red", fontsize=7)
    ax2.tick_params(axis="y", labelcolor="red", labelsize=7)
    ax.tick_params(labelsize=7)

axes1[0].plot(f1b0_t, f1b0_v, color="#1f77b4", linewidth=0.9, label="B0 (0-126, 12 unique)")
axes1[0].set_ylabel("B0", fontsize=8)
axes1[0].legend(loc="upper right", fontsize=7)
axes1[0].set_title("0x0F1 detail (Bus2/Vehicle) -- driveway log\nRed dashes=press onset, green dots=pedal release",
                   fontsize=10, fontweight="bold")

axes1[1].plot(f1b1_t, f1b1_v, color="#ff7f0e", linewidth=0.9, label="B1 (0-105, 105 unique)")
axes1[1].set_ylabel("B1", fontsize=8)
axes1[1].legend(loc="upper right", fontsize=7)

axes1[2].plot(f1b2_t, f1b2_v, color="#2ca02c", linewidth=0.9, label="B2 (0-9, 10 unique)")
axes1[2].set_ylabel("B2", fontsize=8)
axes1[2].legend(loc="upper right", fontsize=7)
axes1[2].set_xlabel("Time (s)", fontsize=8)
axes1[0].set_xlim(t0, t1)

plt.tight_layout()
out1 = ARTIFACT_DIR / "brake_detail_0x0F1.png"
fig1.savefig(out1, dpi=120, bbox_inches="tight")
plt.close(fig1)
print(f"Saved: {out1}", flush=True)

# ======================================================== Part 2: release superposition

# Candidate timeseries: (times_list, vals_list, label, color, invert)
# invert=True means plot (max - val) so all signals rise on press for easy comparison
cands = [
    (ped_times, ped_vals,  "Pedal 16-bit",            "red",       False),
    (f1b0_t,   f1b0_v,    "0x0F1 B0 (Vehicle bus)",  "#1f77b4",   False),
    (f1b1_t,   f1b1_v,    "0x0F1 B1 (Vehicle bus)",  "#ff7f0e",   False),
    (fc_t,     fc_v,      "0x1FC B4<<8|B5 BE16",     "darkorange", False),
    (be_t,     be_v,      "0x0BE B5 (OBD, inverted)", "purple",    True),
]

n_cands = len(cands)
n_events = len(release_events)

if n_events == 0:
    print("No release events to plot.", flush=True)
else:
    fig2, axes2 = plt.subplots(n_cands, 1, figsize=(18, 3.5 * n_cands), sharex=True)
    if n_cands == 1:
        axes2 = [axes2]

    cmap = plt.cm.viridis
    colors = [cmap(i / max(1, n_events - 1)) for i in range(n_events)]

    for ax, (sig_t, sig_v, label, base_color, invert) in zip(axes2, cands):
        sig_max = max(sig_v) if sig_v else 1
        sig_min = min(sig_v) if sig_v else 0
        sig_range = max(1, sig_max - sig_min)

        for ei, (onset_t, rel_t) in enumerate(release_events):
            # find when the next press starts (if any) within the window
            next_press = None
            for oi, (next_onset, _) in enumerate(release_events):
                if next_onset > rel_t + 0.5:
                    next_press = next_onset
                    break
            # truncate window at next press onset
            win_start = rel_t - ZOOM_PRE
            win_end   = min(rel_t + ZOOM_POST, next_press - 0.05) if next_press else rel_t + ZOOM_POST
            clean = (next_press is None) or (next_press > rel_t + ZOOM_POST)

            wt, wv = values_in_window(win_start, win_end, sig_t, sig_v)
            if not wt:
                continue
            normed = [(v - sig_min) / sig_range for v in wv]
            if invert:
                normed = [1.0 - n for n in normed]
            rel_times = [t - rel_t for t in wt]
            lw    = 1.2 if clean else 0.7
            alpha = 0.95 if clean else 0.35
            ax.plot(rel_times, normed, color=colors[ei], linewidth=lw, alpha=alpha,
                    solid_capstyle="butt")

        ax.axvline(0, color="green", linewidth=1.2, linestyle="--", label="pedal release")
        ax.axvspan(-ZOOM_PRE, 0, alpha=0.05, color="red")
        ax.set_ylabel(label, fontsize=8)
        ax.legend(loc="upper right", fontsize=7)
        ax.set_ylim(-0.05, 1.15)
        ax.tick_params(labelsize=7)
        ax.grid(axis="x", alpha=0.3)

    axes2[-1].set_xlabel("Time relative to pedal release (s)", fontsize=8)
    axes2[0].set_title(
        "Release-event superposition -- all 11 events overlaid, normalized 0-1\n"
        "Green line = moment pedal drops below threshold. Slow recovery = vacuum pump refill.",
        fontsize=10, fontweight="bold"
    )
    axes2[0].set_xlim(-ZOOM_PRE, ZOOM_POST)

    plt.tight_layout()
    out2 = ARTIFACT_DIR / "brake_recovery_superposition.png"
    fig2.savefig(out2, dpi=120, bbox_inches="tight")
    plt.close(fig2)
    print(f"Saved: {out2}", flush=True)

print("Done.", flush=True)
