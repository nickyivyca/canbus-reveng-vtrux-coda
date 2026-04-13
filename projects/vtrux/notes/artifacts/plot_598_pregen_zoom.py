"""
plot_598_pregen_zoom.py

Zoom into the pre-generator window (t=50-431s) of 0x598 to investigate
whether B2-B3 (generator) oscillations are a residual of the battery-drivetrain
balance equation.

If the balance holds: gen = battery - drivetrain
  => B2-B3 should track (B0-B1 - B4-B5)

Panels (pre-generator window only, shared x-axis):
  1. All three channels raw (batt, gen, drv)
  2. B2-B3 (actual gen) vs (B0-B1 - B4-B5) (predicted gen from balance)
  3. Residual: B2-B3 - (B0-B1 - B4-B5)
  4. B2-B3 vs -B4-B5 (gen vs inverted drivetrain -- simpler hypothesis: gen = -drv)

Log: logs/vtruxevapdrivelog4.log
Output: artifacts/598_pregen_zoom_plot.png
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxevapdrivelog4.log"
OUT = Path(__file__).parent / "598_pregen_zoom_plot.png"

T_MIN = 50.0
T_MAX = 431.7

ts, batt, gen, drv = [], [], [], []

for frame in parse_file(str(LOG)):
    if frame.arbitration_id != 0x598:
        continue
    t = frame.timestamp
    if t < T_MIN or t > T_MAX:
        continue
    d = frame.data
    if len(d) < 6:
        continue
    ts.append(t)
    batt.append(((d[1] << 8) | d[0]) - 32768)
    gen.append( ((d[3] << 8) | d[2]) - 32768)
    drv.append( ((d[5] << 8) | d[4]) - 32768)

print(f"Pre-generator samples: {len(ts)}")
print(f"  batt: min={min(batt)}  max={max(batt)}  mean={sum(batt)/len(batt):.1f}")
print(f"  gen:  min={min(gen)}   max={max(gen)}   mean={sum(gen)/len(gen):.1f}")
print(f"  drv:  min={min(drv)}   max={max(drv)}   mean={sum(drv)/len(drv):.1f}")

pred_gen = [b - d for b, d in zip(batt, drv)]   # balance: gen = batt - drv
resid    = [g - p for g, p in zip(gen, pred_gen)]
neg_drv  = [-d for d in drv]

fig, axes = plt.subplots(4, 1, figsize=(16, 12), sharex=True)
fig.suptitle(
    '0x598 pre-generator window (t=50-431s): are B2-B3 oscillations a balance residual?\n'
    'Hypothesis: gen = battery - drivetrain',
    fontsize=11
)

axes[0].plot(ts, batt, linewidth=0.8, color='steelblue', label='B0-B1 battery')
axes[0].plot(ts, gen,  linewidth=0.8, color='darkorange', label='B2-B3 generator')
axes[0].plot(ts, drv,  linewidth=0.8, color='green',     label='B4-B5 drivetrain')
axes[0].set_ylabel('all three channels\n(LE uint16 - 32768)', fontsize=8)
axes[0].axhline(0, color='black', linewidth=0.4, linestyle=':')
axes[0].legend(fontsize=7)

axes[1].plot(ts, gen,      linewidth=0.8, color='darkorange', label='B2-B3 gen (actual)')
axes[1].plot(ts, pred_gen, linewidth=0.8, color='crimson', linestyle='--',
             label='B0-B1 - B4-B5 (predicted gen from balance)')
axes[1].set_ylabel('gen actual vs\nbatt - drv predicted', fontsize=8)
axes[1].axhline(0, color='black', linewidth=0.4, linestyle=':')
axes[1].legend(fontsize=7)

axes[2].plot(ts, resid, linewidth=0.8, color='crimson',
             label='residual: gen - (batt - drv)')
axes[2].set_ylabel('balance residual', fontsize=8)
axes[2].axhline(0, color='black', linewidth=0.4, linestyle=':')
axes[2].legend(fontsize=7)

axes[3].plot(ts, gen,     linewidth=0.8, color='darkorange', label='B2-B3 gen (actual)')
axes[3].plot(ts, neg_drv, linewidth=0.8, color='green', linestyle='--',
             label='-B4-B5 drivetrain (simpler: gen = -drv?)')
axes[3].set_ylabel('gen vs -drivetrain', fontsize=8)
axes[3].axhline(0, color='black', linewidth=0.4, linestyle=':')
axes[3].legend(fontsize=7)

for ax in axes:
    ax.tick_params(labelsize=7)
    ax.grid(True, linewidth=0.3, alpha=0.5)

axes[-1].set_xlabel('Time (s)', fontsize=9)
plt.tight_layout()
fig.savefig(str(OUT), dpi=150, bbox_inches='tight')
print(f"Saved: {OUT}")
