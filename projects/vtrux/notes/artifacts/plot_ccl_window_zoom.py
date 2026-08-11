"""
plot_ccl_window_zoom.py

Zoomed plot of the CCL regen-limit window (t=348.6-365.6s) in
vtruxcurrentlimitingtest.log, with 10-second buffers on each side.

Panels:
  1. 0x050 CCL (zero=292)
  2. 0x598 battery/drivetrain/generator current  +  0x420 B4 (BMS candidate, right axis)
  3. 0x5A2 motor RPM  +  torque feedback (right axis)
  4. 0x592 throttle (B2-B3) + brake (B4-B5, right axis)

Highlights:
  Orange shading: t=348.6-365.6s (regen limit active)

Output: plot_ccl_window_zoom.png
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG    = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                      '..', '..', 'logs',
                                      'vtruxcurrentlimitingtest.log'))
OUTPUT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                      'plot_ccl_window_zoom.png'))

ZERO         = 292
T_PLOT_START = 338.6
T_PLOT_END   = 375.6
T_LIM_START  = 348.6
T_LIM_END    = 365.6

# ---------------------------------------------------------------------------
# Detect PT bus
# ---------------------------------------------------------------------------
print("Detecting PT bus ...")
bus_051 = {}
for frame in parse_file(LOG):
    if frame.arbitration_id == 0x051:
        bus_051[frame.bus] = bus_051.get(frame.bus, 0) + 1
    if sum(bus_051.values()) > 200:
        break
if not bus_051:
    raise RuntimeError("0x051 not found")
PT_BUS = max(bus_051, key=bus_051.get)
print(f"PT bus = {PT_BUS}")

# ---------------------------------------------------------------------------
# Collect signals (only within plot window for speed)
# ---------------------------------------------------------------------------
print("Parsing signals ...")
ccl      = []   # (t, val)  0x050 centered at ZERO
b420b4   = []   # (t, val)  0x420 B4 raw
batt_cur = []   # (t, val)  0x598 B0-B1 centred 32768
gen_cur  = []   # (t, val)  0x598 B2-B3 centred 32768
drv_cur  = []   # (t, val)  0x598 B4-B5 centred 32768
mtr_rpm  = []   # (t, val)  0x5A2 B2-B3 centred 32768
trq_fb   = []   # (t, val)  0x5A2 B4-B5 centred 32768
throttle = []   # (t, val)  0x592 B2-B3 raw
brake    = []   # (t, val)  0x592 B4-B5 raw

for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    t = frame.timestamp
    if t < T_PLOT_START - 5 or t > T_PLOT_END + 5:
        continue
    d   = frame.data
    aid = frame.arbitration_id

    if aid == 0x050 and len(d) >= 2:
        ccl.append((t, ((d[1] & 0x03) << 8 | d[0]) - ZERO))

    elif aid == 0x420 and len(d) >= 5:
        b420b4.append((t, d[4]))

    elif aid == 0x598 and len(d) >= 6:
        batt_cur.append((t, ((d[1] << 8) | d[0]) - 32768))
        gen_cur.append( (t, ((d[3] << 8) | d[2]) - 32768))
        drv_cur.append( (t, ((d[5] << 8) | d[4]) - 32768))

    elif aid == 0x5A2 and len(d) >= 6:
        mtr_rpm.append((t, ((d[3] << 8) | d[2]) - 32768))
        trq_fb.append( (t, ((d[5] << 8) | d[4]) - 32768))

    elif aid == 0x592 and len(d) >= 6:
        throttle.append((t, (d[3] << 8) | d[2]))
        brake.append(   (t, (d[5] << 8) | d[4]))

def unzip(pairs):
    if not pairs: return [], []
    t, v = zip(*pairs)
    return list(t), list(v)

print(f"  ccl:{len(ccl)}  0x420B4:{len(b420b4)}  current:{len(batt_cur)}"
      f"  rpm:{len(mtr_rpm)}  throttle:{len(throttle)}")

# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------
print("Plotting ...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(4, 1, figsize=(14, 16), sharex=True)
fig.suptitle(
    'vtruxcurrentlimitingtest.log -- CCL regen-limit window (zoomed)\n'
    't=338.6-375.6s, orange shading = limit active (t=348.6-365.6s)',
    fontsize=11)

def shade(ax):
    ax.axvspan(T_LIM_START, T_LIM_END, color='orangered', alpha=0.15,
               label=f'Limit active ({T_LIM_START}-{T_LIM_END}s)')

def hline(ax):
    ax.axhline(0, color='k', lw=0.5, alpha=0.4)

# ---- Panel 1: CCL ----
ax1 = axes[0]
shade(ax1); hline(ax1)
tc, vc = unzip(ccl)
ax1.plot(tc, vc, color='purple', lw=1.0, label='0x050 CCL (zero=292)')
ax1.set_ylabel('CCL (counts)')
ax1.set_title('0x050 CCL -- regen current limit (negative = below zero-point)')
ax1.legend(loc='lower right', fontsize=8)

# ---- Panel 2: currents + 0x420 B4 ----
ax2 = axes[1]
shade(ax2); hline(ax2)
tb, vb = unzip(batt_cur)
td, vd = unzip(drv_cur)
tg, vg = unzip(gen_cur)
ax2.plot(tb, vb, color='steelblue',  lw=0.7, alpha=0.9,  label='Battery current  0x598 B0-B1')
ax2.plot(td, vd, color='darkorange', lw=0.7, alpha=0.9,  label='Drivetrain current  0x598 B4-B5')
ax2.plot(tg, vg, color='teal',       lw=0.6, alpha=0.65, label='Generator current  0x598 B2-B3')
ax2.set_ylabel('Current (counts, centred 32768)')
ax2.set_title('Battery / drivetrain / generator current  +  0x420 B4 (BMS candidate, right axis)')

ax2r = ax2.twinx()
t4, v4 = unzip(b420b4)
ax2r.plot(t4, v4, color='crimson', lw=1.2, alpha=0.85, label='0x420 B4 (BMS raw)')
ax2r.set_ylabel('0x420 B4 (raw byte 0-255)', color='crimson')
ax2r.tick_params(axis='y', labelcolor='crimson')

lines2a, labs2a = ax2.get_legend_handles_labels()
lines2b, labs2b = ax2r.get_legend_handles_labels()
ax2.legend(lines2a + lines2b, labs2a + labs2b, loc='lower right', fontsize=8)

# ---- Panel 3: RPM + torque feedback ----
ax3 = axes[2]
shade(ax3); hline(ax3)
tr, vr = unzip(mtr_rpm)
tf2, vf2 = unzip(trq_fb)
ax3.plot(tr, vr, color='royalblue', lw=0.8, label='Motor RPM  0x5A2 B2-B3')
ax3.set_ylabel('RPM (counts, centred 32768)')
ax3.set_title('Traction motor RPM + torque feedback')

ax3r = ax3.twinx()
ax3r.plot(tf2, vf2, color='slategray', lw=0.7, alpha=0.75, label='Torque feedback  0x5A2 B4-B5')
ax3r.axhline(0, color='k', lw=0.3, ls=':', alpha=0.3)
ax3r.set_ylabel('Torque fb (counts)', color='slategray')
ax3r.tick_params(axis='y', labelcolor='slategray')
lines3a, labs3a = ax3.get_legend_handles_labels()
lines3b, labs3b = ax3r.get_legend_handles_labels()
ax3.legend(lines3a + lines3b, labs3a + labs3b, loc='lower right', fontsize=8)

# ---- Panel 4: throttle + brake ----
ax4 = axes[3]
shade(ax4)
tt, tv = unzip(throttle)
tbr, vbr = unzip(brake)
ax4.plot(tt, tv, color='forestgreen', lw=0.8, label='Throttle  0x592 B2-B3 (raw)')
ax4.set_ylabel('Throttle (raw counts)', color='forestgreen')
ax4.tick_params(axis='y', labelcolor='forestgreen')
ax4.set_title('Throttle + brake pedal')

ax4r = ax4.twinx()
ax4r.plot(tbr, vbr, color='saddlebrown', lw=0.8, alpha=0.8, label='Brake  0x592 B4-B5 (raw)')
ax4r.set_ylabel('Brake (raw counts)', color='saddlebrown')
ax4r.tick_params(axis='y', labelcolor='saddlebrown')
lines4a, labs4a = ax4.get_legend_handles_labels()
lines4b, labs4b = ax4r.get_legend_handles_labels()
ax4.legend(lines4a + lines4b, labs4a + labs4b, loc='upper right', fontsize=8)

ax4.set_xlabel('Time (s)')
ax4.set_xlim(T_PLOT_START, T_PLOT_END)

plt.tight_layout()
plt.savefig(OUTPUT, dpi=130, bbox_inches='tight')
print(f"Saved: {OUTPUT}")
