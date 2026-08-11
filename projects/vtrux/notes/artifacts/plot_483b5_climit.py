"""
plot_483b5_climit.py

Plot 0x483 B5 vs battery current and motor speed over the regen-limit through
discharge-limit window in vtruxcurrentlimitingtest.log.

Time range: t=380s to t=800s (covers regen limit at 401-503s, transition, and
discharge limit at 598s+).

Signals:
  - 0x598 B0-B1 LE-32768  battery current, scale 0.04124 A/count
  - 0x5A2 B2-B3 LE-32768  motor RPM (~1 RPM/count)
  - 0x483 B5               raw counts (CCL/DCL candidate)
"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

LOG    = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
T_MIN  = 380.0
T_MAX  = 800.0

SCALE_I = 0.04124   # A per count (battery current)

batt_i  = []   # (t, A)
motor_s = []   # (t, RPM)
b5_483  = []   # (t, raw)

print("Parsing log...")
for frame in parse_file(str(LOG)):
    t = frame.timestamp
    if t < T_MIN or t > T_MAX:
        continue
    d   = frame.data
    aid = frame.arbitration_id

    if aid == 0x598 and len(d) >= 2:
        raw = d[0] | (d[1] << 8)
        batt_i.append((t, (raw - 32768) * SCALE_I))

    elif aid == 0x5A2 and len(d) >= 4:
        raw = d[2] | (d[3] << 8)
        motor_s.append((t, raw - 32768))

    elif aid == 0x483 and len(d) >= 6:
        b5_483.append((t, d[5]))

print(f"  batt_I: {len(batt_i)},  motor_speed: {len(motor_s)},  0x483 B5: {len(b5_483)}")

def ts(data):
    if not data:
        return [], []
    t, v = zip(*data)
    return list(t), list(v)

# ── event regions ─────────────────────────────────────────────────────────────
EVENTS = [
    (401, 503, 'Regen limit',      'gold',       0.18),
    (598, 700, 'Discharge limit',  'darkorange',  0.18),
]

def shade(ax):
    for t0, t1, lbl, col, alpha in EVENTS:
        ax.axvspan(t0, t1, color=col, alpha=alpha, zorder=0)

# ── plot ──────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
fig.suptitle("vtruxcurrentlimitingtest — 0x483 B5 vs Current & Speed\n"
             "(regen limit + transition + discharge limit window)", fontsize=12)

# --- subplot 1: battery current ---
ax = axes[0]
shade(ax)
ti, vi = ts(batt_i)
ax.plot(ti, vi, color='deepskyblue', lw=1.0, label='Battery current (A)')
ax.axhline(0, color='white', lw=0.5, ls='--', alpha=0.5)
ax.set_ylabel('Current (A)')
ax.legend(loc='upper right', fontsize=9)
ax.set_title('Battery current  [+ = discharge, - = regen]')
ax.grid(True, alpha=0.2)

# --- subplot 2: motor speed ---
ax = axes[1]
shade(ax)
tm, vm = ts(motor_s)
ax.plot(tm, vm, color='limegreen', lw=1.0, label='Motor speed (RPM)')
ax.axhline(0, color='white', lw=0.5, ls='--', alpha=0.5)
ax.set_ylabel('RPM')
ax.legend(loc='upper right', fontsize=9)
ax.set_title('Motor speed (0x5A2 B2-B3)')
ax.grid(True, alpha=0.2)

# --- subplot 3: 0x483 B5 ---
ax = axes[2]
shade(ax)
tb, vb = ts(b5_483)
ax.plot(tb, vb, color='orange', lw=1.2, label='0x483 B5 (raw counts)')
ax.set_ylabel('Raw counts')
ax.set_xlabel('Time (s)')
ax.legend(loc='upper right', fontsize=9)
ax.set_title('0x483 B5 — CCL/DCL candidate')
ax.grid(True, alpha=0.2)

# ── event legend ──────────────────────────────────────────────────────────────
patches = [mpatches.Patch(color=c, alpha=a + 0.3, label=l)
           for _, _, l, c, a in EVENTS]
fig.legend(handles=patches, loc='upper left', fontsize=9, bbox_to_anchor=(0.01, 0.97))

plt.tight_layout(rect=[0, 0, 1, 0.95])
out = Path(__file__).parent / "plot_483b5_climit.png"
plt.savefig(out, dpi=140, bbox_inches='tight')
print(f"\nSaved: {out}")
