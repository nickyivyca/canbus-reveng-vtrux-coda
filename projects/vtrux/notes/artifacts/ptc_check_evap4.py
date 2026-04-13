"""
vtruxevapdrivelog4 PTC check: blower speed, coolant temp, HV battery current, gen flag.
Long EV-only section (93% -> 80% SoC) before engine starts -- good window for PTC detection.
"""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DBC_SCALE = 0.392157
COOLANT_OFFSET = -40
CURRENT_CENTER = 32768


def load_csv(path):
    ts, vals = [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            ts.append(float(row["timestamp"]))
            vals.append(float(row["value"]))
    return ts, vals


bl_t,  bl_raw  = load_csv("blower_evap4.csv")
ct_t,  ct_raw  = load_csv("coolant_temp_evap4.csv")
ic_t,  ic_raw  = load_csv("batt_current_evap4.csv")
gr_t,  gr_raw  = load_csv("gen_rpm_evap4.csv")

bl_pct = [v * DBC_SCALE for v in bl_raw]
ct_c   = [v + COOLANT_OFFSET for v in ct_raw]
ic_cen = [v - CURRENT_CENTER for v in ic_raw]
gr_rpm = [16 * v - 96 for v in gr_raw]

# Engine-on = first frame where B6 > 6 (positive RPM) that holds for >=5 consecutive frames
gen_on_t = None
for i, (t, v) in enumerate(zip(gr_t, gr_raw)):
    if v > 6 and all(gr_raw[j] > 6 for j in range(i, min(i + 5, len(gr_raw)))):
        gen_on_t = t
        break

fig, axes = plt.subplots(3, 1, figsize=(16, 10), sharex=True)
fig.suptitle("vtruxevapdrivelog4 -- PTC check (blower / coolant / HV current)", fontsize=13)

ax = axes[0]
ax.plot(bl_t, bl_pct, color="steelblue", lw=0.8)
ax.set_ylabel("Blower speed (%)")
ax.set_ylim(bottom=0)
if gen_on_t:
    ax.axvline(gen_on_t, color="green", ls="--", lw=1.5, label=f"Engine on (t={gen_on_t:.0f}s)")
    ax.legend(fontsize=9)

ax = axes[1]
ax.plot(ct_t, ct_c, color="firebrick", lw=1.2)
ax.set_ylabel("Coolant temp (degC)")
if gen_on_t:
    ax.axvline(gen_on_t, color="green", ls="--", lw=1.5)

ax = axes[2]
ax2 = ax.twinx()
ax.plot(ic_t, ic_cen, color="darkorange", lw=0.6, alpha=0.8, label="HV batt current")
ax2.plot(gr_t, gr_rpm, color="purple", lw=1.0, alpha=0.7, label="Gen RPM")
ax.set_ylabel("HV batt current (centered counts)", color="darkorange")
ax2.set_ylabel("Generator RPM", color="purple")
ax.set_xlabel("Elapsed time (s)")
ax.axhline(0, color="black", lw=0.5, ls=":")
if gen_on_t:
    ax.axvline(gen_on_t, color="green", ls="--", lw=1.5)
ax.legend(loc="upper left", fontsize=8)
ax2.legend(loc="upper right", fontsize=8)

plt.tight_layout()
plt.savefig("ptc_check_evap4.png", dpi=150)
print("Saved ptc_check_evap4.png")

if gen_on_t:
    pre_bl  = [v for t, v in zip(bl_t,  bl_pct) if t < gen_on_t]
    pre_ct  = [v for t, v in zip(ct_t,  ct_c)   if t < gen_on_t]
    pre_ic  = [v for t, v in zip(ic_t,  ic_cen)  if t < gen_on_t]
    print(f"\nEngine-on at t={gen_on_t:.1f}s  (pre-engine window: {gen_on_t:.0f}s)")
    print(f"Pre-engine blower:  min={min(pre_bl):.1f}%  max={max(pre_bl):.1f}%  nonzero_frames={sum(1 for v in pre_bl if v>0)}/{len(pre_bl)}")
    print(f"Pre-engine coolant: min={min(pre_ct):.0f}C  max={max(pre_ct):.0f}C  first={pre_ct[0]:.0f}C  last={pre_ct[-1]:.0f}C")
    print(f"Pre-engine HV curr: min={min(pre_ic):.0f}  max={max(pre_ic):.0f}  mean={sum(pre_ic)/len(pre_ic):.0f}")

    # Look for sustained elevated current (PTC signature: steady +ve load, not drive spikes)
    window = 20  # seconds
    import statistics
    sustained = []
    for i, (t, v) in enumerate(zip(ic_t, ic_cen)):
        if t >= gen_on_t:
            break
        window_vals = [vv for tt, vv in zip(ic_t, ic_cen) if t <= tt < t + window]
        if len(window_vals) >= 5:
            sustained.append((t, statistics.mean(window_vals)))
    if sustained:
        peak_t, peak_v = max(sustained, key=lambda x: x[1])
        print(f"\nPeak 20s-window mean HV current before engine: {peak_v:.0f} counts at t={peak_t:.0f}s")
