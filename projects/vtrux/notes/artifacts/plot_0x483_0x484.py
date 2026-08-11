"""
Plot 0x483 B0/B1 and 0x484 B0 raw byte values alongside DCDC temperature.
Raw values shown (no encoding applied) so the shape reveals the encoding.
"""
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

def load(path):
    rows = list(csv.DictReader(open(path)))
    return (np.array([float(r["timestamp"]) for r in rows]),
            np.array([float(r["value"])     for r in rows]))

t_dcdc,  v_dcdc  = load("projects/vtrux/notes/artifacts/overheat_dcdc_temp.csv")
t_pump,  v_pump  = load("projects/vtrux/notes/artifacts/overheat_pump_speed.csv")
t_483b0, v_483b0 = load("projects/vtrux/notes/artifacts/overheat_0x483_B0.csv")
t_483b1, v_483b1 = load("projects/vtrux/notes/artifacts/overheat_0x483_B1.csv")
t_484b0, v_484b0 = load("projects/vtrux/notes/artifacts/overheat_0x484_B0.csv")

temp_c   = v_dcdc * 0.1
pump_reconnect = t_pump[0]

# find key-off gap
gaps = np.diff(t_dcdc)
big  = np.where(gaps > 2.0)[0]
gap_start = t_dcdc[big[0]]     if len(big) else None
gap_end   = t_dcdc[big[0]+1]   if len(big) else None

# quick stats for title
for label, t, v in [("0x483 B0", t_483b0, v_483b0),
                     ("0x483 B1", t_483b1, v_483b1),
                     ("0x484 B0", t_484b0, v_484b0)]:
    print("%s  start=%.0f  min=%.0f  max=%.0f  end=%.0f" % (
        label, v[0], v.min(), v.max(), v[-1]))

fig = plt.figure(figsize=(13, 10))
gs  = gridspec.GridSpec(4, 1, hspace=0.12)

ax_dcdc  = fig.add_subplot(gs[0])
ax_483b0 = fig.add_subplot(gs[1], sharex=ax_dcdc)
ax_483b1 = fig.add_subplot(gs[2], sharex=ax_dcdc)
ax_484b0 = fig.add_subplot(gs[3], sharex=ax_dcdc)

def annotate_ax(ax, color="#c0392b"):
    if gap_start:
        ax.axvspan(gap_start, gap_end, alpha=0.12, color="gray")
    ax.axvline(pump_reconnect, color="#27ae60", linewidth=1.2, linestyle="--", alpha=0.8)

# --- DCDC temperature (reference) ---
ax_dcdc.plot(t_dcdc, temp_c, color="#c0392b", linewidth=1.2)
annotate_ax(ax_dcdc)
ax2 = ax_dcdc.twinx()
ax2.fill_between(t_pump, v_pump, alpha=0.2, color="#2980b9", step="post")
ax2.set_ylim(-10, 260); ax2.set_ylabel("pump B5", color="#2980b9", fontsize=8)
ax2.tick_params(axis="y", labelcolor="#2980b9", labelsize=7)
ax_dcdc.set_ylabel("DCDC temp (degC)", fontsize=9)
ax_dcdc.set_title("0x483 B0/B1 and 0x484 B0 -- raw byte values vs DCDC temperature reference\n"
                  "vtruxunpluggedpumpoverheattest.log  |  green dashed = pump reconnect  |  gray = key-off",
                  fontsize=9)

# --- 0x483 B0 ---
ax_483b0.plot(t_483b0, v_483b0, color="#8e44ad", linewidth=1.1, marker=".", markersize=2)
annotate_ax(ax_483b0, "#8e44ad")
ax_483b0.set_ylabel("0x483 B0 (raw)", fontsize=9)
ax_483b0.text(0.01, 0.92, "start=%.0f  min=%.0f  max=%.0f  end=%.0f" % (
    v_483b0[0], v_483b0.min(), v_483b0.max(), v_483b0[-1]),
    transform=ax_483b0.transAxes, fontsize=8, va="top")

# --- 0x483 B1 ---
ax_483b1.plot(t_483b1, v_483b1, color="#e67e22", linewidth=1.1, marker=".", markersize=2)
annotate_ax(ax_483b1, "#e67e22")
ax_483b1.set_ylabel("0x483 B1 (raw)", fontsize=9)
ax_483b1.text(0.01, 0.92, "start=%.0f  min=%.0f  max=%.0f  end=%.0f" % (
    v_483b1[0], v_483b1.min(), v_483b1.max(), v_483b1[-1]),
    transform=ax_483b1.transAxes, fontsize=8, va="top")

# --- 0x484 B0 ---
ax_484b0.plot(t_484b0, v_484b0, color="#16a085", linewidth=1.1, marker=".", markersize=2)
annotate_ax(ax_484b0, "#16a085")
ax_484b0.set_ylabel("0x484 B0 (raw)", fontsize=9)
ax_484b0.set_xlabel("Time (s)", fontsize=9)
ax_484b0.text(0.01, 0.92, "start=%.0f  min=%.0f  max=%.0f  end=%.0f" % (
    v_484b0[0], v_484b0.min(), v_484b0.max(), v_484b0[-1]),
    transform=ax_484b0.transAxes, fontsize=8, va="top")

# hide x tick labels on all but bottom
for ax in [ax_dcdc, ax_483b0, ax_483b1]:
    plt.setp(ax.get_xticklabels(), visible=False)

ax_dcdc.set_xlim(0, t_dcdc[-1] + 5)

out = "projects/vtrux/notes/artifacts/overheat_0x483_0x484_raw.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print("Saved:", out)
