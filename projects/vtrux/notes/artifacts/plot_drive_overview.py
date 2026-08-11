"""
plot_drive_overview.py

4-panel plot of the climit log from t=0 to t=778s (discharge limit + 3 min):
  1. Brake demand   (0x592 B4-B5 LE, raw counts)
  2. Throttle demand (0x592 B2-B3 LE, raw counts)
  3. Motor torque feedback (0x5A2 B4-B5 LE-32768, signed counts; - = regen)
  4. Drivetrain power (kW): I_drive × V_pack
       I_drive = (0x598 B4-B5 LE-32768) × 0.04124 A/count
       V_pack  = 0x440 B3-B4 LE uint16 × V_SCALE (auto-calibrated below)

Event shading:
  t=30-72s     downhill unrestricted regen
  t=100-300s   regen characterization reference window
  t=401-503s   regen limit active
  t=598-778s   discharge limit + 3-min tail
"""

import sys
from pathlib import Path
from collections import defaultdict
import bisect

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

LOG   = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
T_MAX = 778.0   # discharge limit start (598s) + 3 min

I_SCALE = 0.04124   # A per count for 0x598 channels

# ---------- collect ---------------------------------------------------------
brake_ts   = []   # (t, counts)
throttle_ts= []   # (t, counts)
torque_ts  = []   # (t, signed counts)
i_drive_ts = []   # (t, signed counts)  0x598 B4-B5
vpack_ts   = []   # (t, raw LE uint16)  0x440 B3-B4

print("Parsing log...")
for frame in parse_file(str(LOG)):
    t = frame.timestamp
    if t > T_MAX:
        continue
    d   = frame.data
    aid = frame.arbitration_id

    if aid == 0x592 and len(d) >= 6:
        brake_ts.append   ((t,  d[4] | d[5] << 8))
        throttle_ts.append((t,  d[2] | d[3] << 8))

    elif aid == 0x5A2 and len(d) >= 6:
        torque_ts.append((t, (d[4] | d[5] << 8) - 32768))

    elif aid == 0x598 and len(d) >= 6:
        i_drive_ts.append((t, (d[4] | d[5] << 8) - 32768))

    elif aid == 0x440 and len(d) >= 5:
        vpack_ts.append((t, d[3] | d[4] << 8))

print(f"  brake: {len(brake_ts)}  throttle: {len(throttle_ts)}  "
      f"torque: {len(torque_ts)}  i_drive: {len(i_drive_ts)}  vpack: {len(vpack_ts)}")

# ---------- auto-calibrate V_pack scale -------------------------------------
# Nominal pack voltage for LFP 117S at ~60% SoC: ~374V
# Sample median of raw vpack values during a quiet mid-drive period (t=200-400s)
vpack_sample = [v for t, v in vpack_ts if 200 <= t <= 400]
if vpack_sample:
    vpack_median_raw = sorted(vpack_sample)[len(vpack_sample) // 2]
    # Expect ~370-380V. Find scale that maps median_raw -> 374V
    V_NOMINAL = 374.0   # LFP 117S at ~60% SoC
    V_SCALE = V_NOMINAL / vpack_median_raw if vpack_median_raw else 1.0
    print(f"\nV_pack: median_raw={vpack_median_raw}  assumed_V={V_NOMINAL:.0f}V  "
          f"=> V_SCALE={V_SCALE:.6f} V/count")
    print(f"  (spot-check: raw range {min(vpack_sample)}-{max(vpack_sample)} "
          f"-> {min(vpack_sample)*V_SCALE:.1f}-{max(vpack_sample)*V_SCALE:.1f} V)")
else:
    V_SCALE = 0.1
    print("WARNING: no vpack data in calibration window, using V_SCALE=0.1")

# ---------- compute power timeseries ----------------------------------------
# Join i_drive to nearest vpack by time
vt = [t for t, _ in vpack_ts]
vv = [v for _, v in vpack_ts]

def nearest_vpack(t_q):
    i = bisect.bisect_left(vt, t_q)
    if i == 0:    return vv[0]
    if i >= len(vt): return vv[-1]
    return vv[i] if abs(vt[i]-t_q) < abs(vt[i-1]-t_q) else vv[i-1]

power_ts = []   # (t, kW)
for t, i_cts in i_drive_ts:
    v_raw = nearest_vpack(t)
    v_V   = v_raw * V_SCALE
    i_A   = i_cts * I_SCALE
    power_ts.append((t, i_A * v_V / 1000.0))   # kW

# ---------- unzip helpers ---------------------------------------------------
def ts(data):
    if not data: return [], []
    t, v = zip(*data)
    return list(t), list(v)

# ---------- event shading ---------------------------------------------------
EVENTS = [
    ( 30,  72,  'Unrestricted regen (ref)',  'limegreen',   0.12),
    (100, 300,  'Regen charact. window',     'dodgerblue',  0.08),
    (401, 503,  'Regen limit active',        'gold',        0.20),
    (598, 778,  'Discharge limit + tail',    'darkorange',  0.15),
]

def shade(ax):
    for t0, t1, lbl, col, alpha in EVENTS:
        ax.axvspan(t0, t1, color=col, alpha=alpha, zorder=0)

# ---------- plot ------------------------------------------------------------
fig, axes = plt.subplots(4, 1, figsize=(16, 14), sharex=True)
fig.suptitle("vtruxcurrentlimitingtest — Drive overview  t=0 to 778s", fontsize=13)

# Panel 1: Brake
ax = axes[0]
shade(ax)
tb, vb = ts(brake_ts)
ax.plot(tb, vb, color='orangered', lw=0.9, label='Brake demand')
ax.axhline(156, color='white', lw=0.7, ls=':', alpha=0.6, label='Idle threshold (156)')
ax.set_ylabel('Counts')
ax.legend(loc='upper right', fontsize=8)
ax.set_title('Brake demand  (0x592 B4-B5)')
ax.grid(True, alpha=0.2)

# Panel 2: Throttle
ax = axes[1]
shade(ax)
tt, vt2 = ts(throttle_ts)
ax.plot(tt, vt2, color='deepskyblue', lw=0.9, label='Throttle demand')
ax.set_ylabel('Counts')
ax.legend(loc='upper right', fontsize=8)
ax.set_title('Throttle demand  (0x592 B2-B3)')
ax.grid(True, alpha=0.2)

# Panel 3: Motor torque feedback
ax = axes[2]
shade(ax)
tq, vq = ts(torque_ts)
ax.plot(tq, vq, color='violet', lw=0.8, label='Motor torque feedback')
ax.axhline(0, color='white', lw=0.5, ls='--', alpha=0.5)
ax.set_ylabel('Signed counts\n(- = regen)')
ax.legend(loc='upper right', fontsize=8)
ax.set_title('Drivetrain motor torque feedback  (0x5A2 B4-B5 LE-32768)')
ax.grid(True, alpha=0.2)

# Panel 4: Drivetrain power
ax = axes[3]
shade(ax)
tp, vp = ts(power_ts)
ax.plot(tp, vp, color='gold', lw=0.9, label='Drivetrain power (kW)')
ax.axhline(0, color='white', lw=0.5, ls='--', alpha=0.5)
ax.set_ylabel('kW  (- = regen)')
ax.set_xlabel('Time (s)')
ax.legend(loc='upper right', fontsize=8)
ax.set_title(f'Drivetrain power  (I x V_pack,  V_scale={V_SCALE:.4f} V/count)')
ax.grid(True, alpha=0.2)

# Event legend
patches = [mpatches.Patch(color=c, alpha=a+0.3, label=l)
           for _, _, l, c, a in EVENTS]
fig.legend(handles=patches, loc='upper left', fontsize=8, bbox_to_anchor=(0.01, 0.99))

plt.tight_layout(rect=[0, 0, 1, 0.97])
out = Path(__file__).parent / "plot_drive_overview.png"
plt.savefig(out, dpi=140, bbox_inches='tight')
print(f"\nSaved: {out}")
