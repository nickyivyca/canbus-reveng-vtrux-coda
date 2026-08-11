"""
Plot 0x483 B0, B1, B2, and combined LE uint16 (B1 + B2*256) to find the correct encoding.
B0 confirmed: raw - 100 = degC.
Testing whether B1 + B2*256 gives a cleaner/higher-resolution temperature.
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

t_dcdc, v_dcdc   = load("projects/vtrux/notes/artifacts/overheat_dcdc_temp.csv")
t_b0,   v_b0     = load("projects/vtrux/notes/artifacts/overheat_0x483_B0.csv")
t_b1,   v_b1     = load("projects/vtrux/notes/artifacts/overheat_0x483_B1.csv")
t_b2,   v_b2     = load("projects/vtrux/notes/artifacts/overheat_0x483_B2.csv")
t_pump, v_pump   = load("projects/vtrux/notes/artifacts/overheat_pump_speed.csv")

temp_c = v_dcdc * 0.1
pump_reconnect = t_pump[0]

# key-off gap
gaps = np.diff(t_dcdc)
big  = np.where(gaps > 2.0)[0]
gap_start = t_dcdc[big[0]]   if len(big) else None
gap_end   = t_dcdc[big[0]+1] if len(big) else None

# combined LE uint16 (B1=low, B2=high)
combined_le = v_b1 + v_b2 * 256.0

# print unique B2 values and transitions
b2_vals, b2_counts = np.unique(v_b2, return_counts=True)
print("B2 unique values:", list(zip(b2_vals.astype(int), b2_counts)))

# find B2 step times
b2_steps = np.where(np.diff(v_b2) != 0)[0]
print("B2 step timestamps:")
for i in b2_steps:
    print("  t=%.2f  B2: %d -> %d  (B1 at that point: %d  combined: %d)" % (
        t_b2[i], int(v_b2[i]), int(v_b2[i+1]), int(v_b1[i]), int(combined_le[i])))

print()
print("B0 (raw-100 degC): start=%.1f  end=%.1f" % (v_b0[0]-100, v_b0[-1]-100))
print("B1:  start=%d  min=%d  max=%d  end=%d" % (v_b1[0], v_b1.min(), v_b1.max(), v_b1[-1]))
print("B2:  start=%d  min=%d  max=%d  end=%d" % (v_b2[0], v_b2.min(), v_b2.max(), v_b2[-1]))
print("LE16 (B1+B2*256): start=%d  min=%d  max=%d  end=%d" % (
    combined_le[0], combined_le.min(), combined_le.max(), combined_le[-1]))

fig = plt.figure(figsize=(13, 12))
gs  = gridspec.GridSpec(5, 1, hspace=0.10)

axs = [fig.add_subplot(gs[i], sharex=fig.add_subplot(gs[0]) if i>0 else None) for i in range(5)]
axs = [fig.add_subplot(gs[0])]
for i in range(1, 5):
    axs.append(fig.add_subplot(gs[i], sharex=axs[0]))

def annotate(ax):
    if gap_start:
        ax.axvspan(gap_start, gap_end, alpha=0.12, color="gray")
    ax.axvline(pump_reconnect, color="#27ae60", lw=1.2, ls="--", alpha=0.8)

# DCDC reference
axs[0].plot(t_dcdc, temp_c, color="#c0392b", lw=1.2, label="DCDC temp (degC)")
axs[0].set_ylabel("DCDC temp (degC)", fontsize=9)
axs[0].set_title("0x483 B0/B1/B2 decomposition -- raw and combined LE uint16\n"
                 "green dashed = pump reconnect  |  gray = key-off", fontsize=9)
annotate(axs[0])

# B0 decoded
axs[1].plot(t_b0, v_b0 - 100, color="#8e44ad", lw=1.1, marker=".", markersize=2)
axs[1].set_ylabel("B0 - 100 (degC)", fontsize=9)
axs[1].text(0.01, 0.92, "start=%.0f  end=%.0f degC" % (v_b0[0]-100, v_b0[-1]-100),
            transform=axs[1].transAxes, fontsize=8, va="top")
annotate(axs[1])

# B1 raw
axs[2].plot(t_b1, v_b1, color="#e67e22", lw=1.1, marker=".", markersize=2)
axs[2].set_ylabel("B1 (raw)", fontsize=9)
axs[2].text(0.01, 0.92, "start=%d  min=%d  max=%d  end=%d" % (
    v_b1[0], v_b1.min(), v_b1.max(), v_b1[-1]),
    transform=axs[2].transAxes, fontsize=8, va="top")
annotate(axs[2])

# B2 raw (zone steps)
axs[3].plot(t_b2, v_b2, color="#2980b9", lw=1.1, marker=".", markersize=2)
axs[3].set_ylabel("B2 (raw)", fontsize=9)
axs[3].text(0.01, 0.92, "start=%d  min=%d  max=%d  end=%d" % (
    v_b2[0], v_b2.min(), v_b2.max(), v_b2[-1]),
    transform=axs[3].transAxes, fontsize=8, va="top")
annotate(axs[3])

# Combined LE uint16
axs[4].plot(t_b1, combined_le, color="#16a085", lw=1.1, marker=".", markersize=2)
axs[4].set_ylabel("B1+B2*256 (LE16)", fontsize=9)
axs[4].set_xlabel("Time (s)", fontsize=9)
axs[4].text(0.01, 0.92, "start=%d  min=%d  max=%d  end=%d" % (
    combined_le[0], combined_le.min(), combined_le.max(), combined_le[-1]),
    transform=axs[4].transAxes, fontsize=8, va="top")
annotate(axs[4])

for ax in axs[:4]:
    plt.setp(ax.get_xticklabels(), visible=False)

axs[0].set_xlim(0, t_dcdc[-1] + 5)

out = "projects/vtrux/notes/artifacts/overheat_0x483_combined.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print("Saved:", out)
