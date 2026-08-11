"""
plot_598_balance.py

Test the balance equation hypothesis for 0x598:
  B0-B1 (battery) + B2-B3 (generator) + B4-B5 (drivetrain) =?= constant

All three channels: LE uint16, centered at 32768.

Panels:
  1. Battery   (B0-B1 - 32768)
  2. Generator (B2-B3 - 32768)
  3. Drivetrain(B4-B5 - 32768)
  4. Sum of all three -- should be flat/zero if balance equation holds

Log: logs/vtruxevapdrivelog4.log
Output: artifacts/598_balance_plot.png
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxevapdrivelog4.log"
OUT = Path(__file__).parent / "598_balance_plot.png"

GEN_START = 431.7

ts, batt, gen, drv = [], [], [], []

print("Parsing 0x598 frames...")
for frame in parse_file(str(LOG)):
    if frame.arbitration_id != 0x598:
        continue
    d = frame.data
    if len(d) < 6:
        continue
    ts.append(frame.timestamp)
    batt.append(((d[1] << 8) | d[0]) - 32768)
    gen.append( ((d[3] << 8) | d[2]) - 32768)
    drv.append( ((d[5] << 8) | d[4]) - 32768)

# Hypothesis: battery = drivetrain - generator
# Residual = battery - (drivetrain - generator) = battery - drivetrain + generator
# Should be flat/zero if the balance holds.
# Also plot drivetrain - generator directly to compare against battery.
residual  = [b - dr + g  for b, g, dr in zip(batt, gen, drv)]
drv_minus_gen = [dr - g for g, dr in zip(gen, drv)]

print(f"  Samples: {len(ts)}")
print(f"  Residual (batt - drv + gen) stats: min={min(residual)}  max={max(residual)}  mean={sum(residual)/len(residual):.1f}")

fig, axes = plt.subplots(5, 1, figsize=(18, 13), sharex=True)
fig.suptitle(
    '0x598 balance check: battery =?= drivetrain - generator\n'
    'Log: vtruxevapdrivelog4.log    All channels: LE uint16 - 32768\n'
    'Green shading = generator ON (t > 431.7s)',
    fontsize=11
)

log_end = max(ts)
panels = [
    (batt,         '0x598 B0-B1\nbattery',                        'steelblue'),
    (gen,          '0x598 B2-B3\ngenerator',                      'darkorange'),
    (drv,          '0x598 B4-B5\ndrivetrain',                     'green'),
    (drv_minus_gen,'drivetrain - generator\n[compare to battery]', 'purple'),
    (residual,     'residual: batt - drv + gen\n[flat = balance holds]', 'crimson'),
]

for ax, (vs, label, color) in zip(axes, panels):
    ax.plot(ts, vs, linewidth=0.7, color=color, rasterized=True)
    ax.set_ylabel(label, fontsize=8, labelpad=4)
    ax.axvspan(GEN_START, log_end, color='green', alpha=0.07, zorder=0)
    ax.axvline(GEN_START, color='green', linewidth=0.8, linestyle='--', alpha=0.6)
    ax.axhline(0, color='black', linewidth=0.4, linestyle=':')
    ax.tick_params(labelsize=7)
    ax.grid(True, linewidth=0.3, alpha=0.5)

axes[-1].set_xlabel('Time (s)', fontsize=9)
plt.tight_layout()
fig.savefig(str(OUT), dpi=150, bbox_inches='tight')
print(f"Saved: {OUT}")
