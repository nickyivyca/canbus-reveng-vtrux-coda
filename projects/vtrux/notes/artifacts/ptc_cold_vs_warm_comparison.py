"""
Compare PTC behavior: cold engine (evap4 pre-engine window) vs warm engine residual (anotherevap Part 4).
Engine oil temp (0x4D1 B1) is dead (all zeros) in both logs -- not plotted.

Left column: vtruxevapdrivelog4 -- cold start, EV-only ~432s before engine-on
             Blower runs the whole time, coolant flat at 17C despite HV discharge -> PTC
             not routing heat through engine coolant loop.

Right column: vtruxanotherevaplogpart4-batteryonly -- warm engine residual (~68C start),
              EV-only ~30min, coolant declines throughout. Heater extracts residual engine
              heat through the coolant loop.

Hypothesis: VCM uses different valve/pump config depending on engine thermal state.
  Cold:  PTC heats cabin directly (air-side) or separate loop -- coolant unaffected.
  Warm:  Coolant circulated through heater core -- residual heat extracted, coolant declines.
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


# --- evap4 (cold engine) ---
bl4_t,  bl4_raw  = load_csv("blower_evap4.csv")
ct4_t,  ct4_raw  = load_csv("coolant_temp_evap4.csv")
ic4_t,  ic4_raw  = load_csv("batt_current_evap4.csv")
gr4_t,  gr4_raw  = load_csv("gen_rpm_evap4.csv")

bl4_pct = [v * DBC_SCALE for v in bl4_raw]
ct4_c   = [v + COOLANT_OFFSET for v in ct4_raw]
ic4_cen = [v - CURRENT_CENTER for v in ic4_raw]

# Engine-on marker
gen_on_t = None
for i, (t, v) in enumerate(zip(gr4_t, gr4_raw)):
    if v > 6 and all(gr4_raw[j] > 6 for j in range(i, min(i + 5, len(gr4_raw)))):
        gen_on_t = t
        break

# Clip to pre-engine window + small buffer
clip_end = gen_on_t + 60 if gen_on_t else max(bl4_t)

def clip(ts, vals, end):
    return zip(*[(t, v) for t, v in zip(ts, vals) if t <= end]) or ([], [])

bl4_tc, bl4_vc = zip(*[(t, v) for t, v in zip(bl4_t, bl4_pct) if t <= clip_end])
ct4_tc, ct4_vc = zip(*[(t, v) for t, v in zip(ct4_t, ct4_c)   if t <= clip_end])
ic4_tc, ic4_vc = zip(*[(t, v) for t, v in zip(ic4_t, ic4_cen)  if t <= clip_end])

# --- anotherevap Part 4 (warm engine) ---
blp4_t,  blp4_raw  = load_csv("blower_part4.csv")
ctp4_t,  ctp4_raw  = load_csv("coolant_temp_part4.csv")
icp4_t,  icp4_raw  = load_csv("batt_current_le_part4.csv")

blp4_pct = [v * DBC_SCALE for v in blp4_raw]
ctp4_c   = [v + COOLANT_OFFSET for v in ctp4_raw]
icp4_cen = [v - CURRENT_CENTER for v in icp4_raw]

# --- Plot ---
fig, axes = plt.subplots(3, 2, figsize=(16, 11), sharey="row")
fig.suptitle(
    "PTC behavior: cold engine (evap4) vs warm engine residual (anotherevap Part 4)\n"
    "Note: Engine Oil Temp (0x4D1 B1) dead in both logs -- not available",
    fontsize=12
)

LEFT_COLOR_BL = "steelblue"
LEFT_COLOR_CT = "firebrick"
LEFT_COLOR_IC = "darkorange"
GEN_COLOR = "green"

titles_left = [
    "evap4 -- COLD ENGINE (pre-engine + 60s)\nBlower on from t=0, coolant flat 17C",
    "",
    "",
]

# Row 0: Blower
ax = axes[0, 0]
ax.plot(bl4_tc, bl4_vc, color=LEFT_COLOR_BL, lw=0.8)
ax.set_ylabel("Blower speed (%)")
ax.set_ylim(bottom=0)
ax.set_title("evap4 -- COLD ENGINE (pre-engine + 60s)\nBlower on from t=0, coolant flat at 17C")
if gen_on_t:
    ax.axvline(gen_on_t, color=GEN_COLOR, ls="--", lw=1.5, label=f"Engine on ({gen_on_t:.0f}s)")
    ax.legend(fontsize=8)

ax = axes[0, 1]
ax.plot(blp4_t, blp4_pct, color=LEFT_COLOR_BL, lw=0.8)
ax.set_ylim(bottom=0)
ax.set_title("anotherevap Part 4 -- EV-only (battery only)\nCoolant cycles 39->68->44->68->38C (two thermal cycles)")

# Row 1: Coolant temp
ax = axes[1, 0]
ax.plot(ct4_tc, ct4_vc, color=LEFT_COLOR_CT, lw=1.2)
ax.set_ylabel("Coolant temp (degC)")
if gen_on_t:
    ax.axvline(gen_on_t, color=GEN_COLOR, ls="--", lw=1.5)

ax = axes[1, 1]
ax.plot(ctp4_t, ctp4_c, color=LEFT_COLOR_CT, lw=1.2)

# Row 2: HV battery current
ax = axes[2, 0]
ax.plot(ic4_tc, ic4_vc, color=LEFT_COLOR_IC, lw=0.6, alpha=0.8)
ax.set_ylabel("HV batt current\n(centered counts)")
ax.set_xlabel("Elapsed time (s)")
ax.axhline(0, color="black", lw=0.5, ls=":")
if gen_on_t:
    ax.axvline(gen_on_t, color=GEN_COLOR, ls="--", lw=1.5)

ax = axes[2, 1]
ax.plot(icp4_t, icp4_cen, color=LEFT_COLOR_IC, lw=0.6, alpha=0.8)
ax.axhline(0, color="black", lw=0.5, ls=":")
ax.set_xlabel("Elapsed time (s)")

plt.tight_layout()
plt.savefig("ptc_cold_vs_warm_comparison.png", dpi=150)
print("Saved ptc_cold_vs_warm_comparison.png")

# Summary stats
print(f"\nevap4 pre-engine window: {gen_on_t:.0f}s" if gen_on_t else "\nevap4: no engine-on found")
pre_bl  = [v for t, v in zip(bl4_t, bl4_pct)  if gen_on_t and t < gen_on_t]
pre_ct  = [v for t, v in zip(ct4_t, ct4_c)    if gen_on_t and t < gen_on_t]
pre_ic  = [v for t, v in zip(ic4_t, ic4_cen)  if gen_on_t and t < gen_on_t]
if pre_bl:
    print(f"  Blower:  {min(pre_bl):.1f}-{max(pre_bl):.1f}%  (all nonzero: {all(v>0 for v in pre_bl)})")
    print(f"  Coolant: {min(pre_ct):.0f}-{max(pre_ct):.0f}C")
    print(f"  HV curr: mean={sum(pre_ic)/len(pre_ic):.0f} counts, max={max(pre_ic):.0f}")

print(f"\nanotherevap Part 4 (full log):")
print(f"  Blower:  {min(blp4_pct):.1f}-{max(blp4_pct):.1f}%")
print(f"  Coolant: {ctp4_c[0]:.0f}C start, max={max(ctp4_c):.0f}C, end={ctp4_c[-1]:.0f}C  (NOTE: non-monotonic -- two thermal cycles)")
icp4_mean = sum(icp4_cen) / len(icp4_cen)
print(f"  HV curr: mean={icp4_mean:.0f} counts")
