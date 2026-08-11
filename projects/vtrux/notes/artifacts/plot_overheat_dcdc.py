"""
Plot DCDC temperature arc from the PE pump overheat test.
Log: vtruxunpluggedpumpoverheattest.log

Signals:
  0x18FFD6B3 B6-B7 LE signed x0.1 degC -- DCDC temperature
  0x18FF0320 B5 -- pump speed feedback (0=off, 237=fast)
"""

import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ---- load data ----
def load_csv(path):
    rows = list(csv.DictReader(open(path)))
    t = np.array([float(r["timestamp"]) for r in rows])
    v = np.array([float(r["value"]) for r in rows])
    return t, v

t_dcdc, v_raw = load_csv("projects/vtrux/notes/artifacts/overheat_dcdc_temp.csv")
t_pump, v_pump = load_csv("projects/vtrux/notes/artifacts/overheat_pump_speed.csv")

temp_c = v_raw * 0.1   # LE signed x0.1 degC

# ---- find key-off gap in DCDC stream ----
# Normal interval ~0.11s at 9 Hz; a gap >2s is key-off
gaps = np.diff(t_dcdc)
big_gap_idx = np.where(gaps > 2.0)[0]
if len(big_gap_idx) > 0:
    gap_start = t_dcdc[big_gap_idx[0]]
    gap_end   = t_dcdc[big_gap_idx[0] + 1]
    gap_mid   = 0.5 * (gap_start + gap_end)
else:
    gap_start = gap_end = gap_mid = None

pump_reconnect = t_pump[0]   # first pump frame = reconnect

# ---- plot ----
fig, ax1 = plt.subplots(figsize=(12, 5))

# DCDC temperature
ax1.plot(t_dcdc, temp_c, color="#c0392b", linewidth=1.2, label="DCDC temp (0x18FFD6B3 B6-B7)")
ax1.set_xlabel("Time (s)")
ax1.set_ylabel("DCDC Temperature (degC)", color="#c0392b")
ax1.tick_params(axis="y", labelcolor="#c0392b")
ax1.set_ylim(14, 28)

# pump speed on secondary axis
ax2 = ax1.twinx()
ax2.fill_between(t_pump, v_pump, alpha=0.25, color="#2980b9", step="post", label="Pump speed B5")
ax2.plot(t_pump, v_pump, color="#2980b9", linewidth=0.8, drawstyle="steps-post")
ax2.set_ylabel("Pump speed feedback (B5 raw)", color="#2980b9")
ax2.tick_params(axis="y", labelcolor="#2980b9")
ax2.set_ylim(-10, 260)

# annotate key events
ax1.axvline(pump_reconnect, color="#27ae60", linewidth=1.5, linestyle="--")
ax1.text(pump_reconnect + 3, 27.2, "Pump reconnect\nt=%.0fs" % pump_reconnect,
         color="#27ae60", fontsize=8, va="top")

if gap_start is not None:
    ax1.axvspan(gap_start, gap_end, alpha=0.15, color="gray")
    ax1.text(gap_mid, 14.4, "Key off", ha="center", fontsize=8, color="gray", style="italic")
    ax1.text(gap_start * 0.5, 14.4, "Key-on cycle 1\n(no pump)", ha="center", fontsize=8, color="#555")
    ax1.text(0.5 * (gap_end + t_dcdc[-1]), 14.4, "Key-on cycle 2\n(pump active)", ha="center", fontsize=8, color="#555")
else:
    # no gap found -- just label pump-off vs pump-on regions
    ax1.text(pump_reconnect * 0.5, 14.4, "Cycle 1 -- no pump", ha="center", fontsize=8, color="#555")
    ax1.text(0.5 * (pump_reconnect + t_dcdc[-1]), 14.4, "Cycle 2 -- pump active", ha="center", fontsize=8, color="#555")

# mark peak
peak_idx = np.argmax(temp_c)
ax1.scatter([t_dcdc[peak_idx]], [temp_c[peak_idx]], color="#c0392b", zorder=5, s=40)
ax1.annotate("Peak %.1fC @ t=%.0fs" % (temp_c[peak_idx], t_dcdc[peak_idx]),
             xy=(t_dcdc[peak_idx], temp_c[peak_idx]),
             xytext=(t_dcdc[peak_idx] - 80, temp_c[peak_idx] + 0.8),
             arrowprops=dict(arrowstyle="->", color="#c0392b"),
             fontsize=8, color="#c0392b")

# mark cold start
start_idx = np.argmin(temp_c)
ax1.scatter([t_dcdc[start_idx]], [temp_c[start_idx]], color="#8e44ad", zorder=5, s=40, marker="v")
ax1.annotate("Cold start %.1fC @ t=%.0fs" % (temp_c[start_idx], t_dcdc[start_idx]),
             xy=(t_dcdc[start_idx], temp_c[start_idx]),
             xytext=(t_dcdc[start_idx] + 20, temp_c[start_idx] + 0.8),
             arrowprops=dict(arrowstyle="->", color="#8e44ad"),
             fontsize=8, color="#8e44ad")

ax1.set_title("DCDC Temperature -- PE Pump Overheat Test\nvtruxunpluggedpumpoverheattest.log  |  0x18FFD6B3 B6-B7  |  LE signed x0.1 degC")
ax1.set_xlim(0, t_dcdc[-1] + 5)

# combined legend
lines1 = [mpatches.Patch(color="#c0392b", label="DCDC temperature"),
          mpatches.Patch(color="#2980b9", alpha=0.5, label="Pump speed (B5 raw)"),
          mpatches.Patch(color="#27ae60", label="Pump reconnect"),
          mpatches.Patch(color="gray", alpha=0.3, label="Key-off gap")]
ax1.legend(handles=lines1, loc="upper left", fontsize=8)

plt.tight_layout()
out = "projects/vtrux/notes/artifacts/overheat_dcdc_temp.png"
plt.savefig(out, dpi=150)
print("Saved:", out)

# print summary stats
print()
print("DCDC temperature summary:")
print("  Cold start (min): %.1f degC at t=%.1f s" % (temp_c[start_idx], t_dcdc[start_idx]))
print("  Peak:             %.1f degC at t=%.1f s" % (temp_c[peak_idx], t_dcdc[peak_idx]))
print("  End:              %.1f degC at t=%.1f s" % (temp_c[-1], t_dcdc[-1]))
print("  Rise (cycle 1):   %.1f degC over %.0f s (%.3f degC/min)" % (
    temp_c[peak_idx] - min(temp_c[:peak_idx+1]),
    t_dcdc[peak_idx] - t_dcdc[0],
    (temp_c[peak_idx] - min(temp_c[:peak_idx+1])) / (t_dcdc[peak_idx] - t_dcdc[0]) * 60))
print("  Pump reconnect:   t=%.1f s" % pump_reconnect)
if gap_start is not None:
    print("  Key-off gap:      t=%.1f to %.1f s (%.1f s)" % (gap_start, gap_end, gap_end - gap_start))
print()
print("Pump speed range:", int(v_pump.min()), "to", int(v_pump.max()))
