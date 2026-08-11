"""
Part 1 cold-start check: blower speed, coolant temp, HV battery current, gen flag.
Goal: see if blower is running and PTC (HV current) active before engine turns on.
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


bl_t,  bl_raw  = load_csv("blower_part1.csv")
ct_t,  ct_raw  = load_csv("coolant_temp_part1.csv")
ic_t,  ic_raw  = load_csv("batt_current_part1.csv")
gf_t,  gf_raw  = load_csv("gen_flag_part1.csv")

bl_pct = [v * DBC_SCALE for v in bl_raw]
ct_c   = [v + COOLANT_OFFSET for v in ct_raw]
ic_cen = [v - CURRENT_CENTER for v in ic_raw]  # centered; positive = discharging

# Find first gen-active frame (0x34)
gen_on_t = next((t for t, v in zip(gf_t, gf_raw) if v == 0x34), None)

fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
fig.suptitle("Part 1 cold start -- PTC check (blower / coolant / HV current)", fontsize=13)

ax = axes[0]
ax.plot(bl_t, bl_pct, color="steelblue", lw=1.0)
ax.set_ylabel("Blower speed (%)")
ax.set_ylim(bottom=0)
if gen_on_t:
    ax.axvline(gen_on_t, color="green", ls="--", lw=1.2, label=f"Engine on ({gen_on_t:.1f}s)")
    ax.legend(fontsize=9)

ax = axes[1]
ax.plot(ct_t, ct_c, color="firebrick", lw=1.2)
ax.set_ylabel("Coolant temp (degC)")
if gen_on_t:
    ax.axvline(gen_on_t, color="green", ls="--", lw=1.2)

ax = axes[2]
ax.plot(ic_t, ic_cen, color="darkorange", lw=0.8)
ax.set_ylabel("HV batt current (centered counts)")
ax.set_xlabel("Elapsed time (s)")
ax.axhline(0, color="black", lw=0.5, ls=":")
if gen_on_t:
    ax.axvline(gen_on_t, color="green", ls="--", lw=1.2)

plt.tight_layout()
plt.savefig("ptc_check_part1.png", dpi=150)
print("Saved ptc_check_part1.png")

# Quick pre-engine stats
if gen_on_t:
    pre_bl  = [v for t, v in zip(bl_t,  bl_pct) if t < gen_on_t]
    pre_ct  = [v for t, v in zip(ct_t,  ct_c)   if t < gen_on_t]
    pre_ic  = [v for t, v in zip(ic_t,  ic_cen)  if t < gen_on_t]
    print(f"\nEngine-on at t={gen_on_t:.1f}s")
    print(f"Pre-engine blower:  min={min(pre_bl):.1f}%  max={max(pre_bl):.1f}%  nonzero_frames={sum(1 for v in pre_bl if v>0)}/{len(pre_bl)}")
    print(f"Pre-engine coolant: min={min(pre_ct):.0f}C  max={max(pre_ct):.0f}C")
    print(f"Pre-engine HV curr: min={min(pre_ic):.0f}  max={max(pre_ic):.0f}  mean={sum(pre_ic)/len(pre_ic):.0f}")
