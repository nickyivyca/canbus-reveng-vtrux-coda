"""
find_current_limits.py

Plot BMS current limit candidates alongside battery current and motor torque
for vtruxcurrentlimitingtest.log.

Reference event windows (confirmed by user from plot inspection):
  t=30-72s    Downhill unrestricted regen (reference: full regen available)
  t=401-503s  Regen current limit active (battery current capped)
  t=598s+     Highway discharge limit active (~half full power)

Candidates:
  - 0x440 B0  (6 unique values, 44-120; starts at min=44 at t=0 -- CCL hypothesis)
  - 0x440 B2  (115 unique, 77-191; r_I=-0.83 -- DCL hypothesis)
  - 0x440 B4  (22 unique -- discrete field)
  - 0x460 PT bus DLC=8, mux slot B0=0 and B0=1 -- extract each slot separately
  - 0x639 bytes (unanalyzed in drive context; described as "BMS limits")

Reference signals:
  - 0x598 B0-B1 LE-32768  battery current (positive=discharge, negative=regen)
  - 0x5A2 B4-B5 LE-32768  motor torque feedback (negative=regen)
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

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"

# ── collect signals ──────────────────────────────────────────────────────────

batt_I   = []   # 0x598 B0-B1 LE-32768
torque   = []   # 0x5A2 B4-B5 LE-32768

x440_B0  = []
x440_B2  = []
x440_B4  = []
x440_B5  = []

# 0x460: separate mux slots (PT bus DLC=8 only)
x460_s0  = defaultdict(list)   # slot B0=0 -> {byte_idx: [(t,v)]}
x460_s1  = defaultdict(list)   # slot B0=1

# 0x639: all 8 bytes
x639     = defaultdict(list)

print("Parsing log...")
for frame in parse_file(str(LOG)):
    t = frame.timestamp
    d = frame.data
    aid = frame.arbitration_id

    if aid == 0x598 and len(d) >= 2:
        batt_I.append((t, (d[0] | d[1] << 8) - 32768))

    elif aid == 0x5A2 and len(d) >= 6:
        torque.append((t, (d[4] | d[5] << 8) - 32768))

    elif aid == 0x440 and len(d) >= 6:
        x440_B0.append((t, d[0]))
        x440_B2.append((t, d[2]))
        x440_B4.append((t, d[4]))
        x440_B5.append((t, d[5]))

    elif aid == 0x460 and len(d) == 8 and not frame.is_extended:
        slot = d[0]
        target = x460_s0 if slot == 0 else x460_s1
        for i in range(1, 8):
            target[i].append((t, d[i]))

    elif aid == 0x639 and len(d) >= 7:
        for i in range(8):
            if i < len(d):
                x639[i].append((t, d[i]))

print(f"  batt_I: {len(batt_I)}, torque: {len(torque)}")
print(f"  0x440 B0: {len(x440_B0)}, B2: {len(x440_B2)}")
print(f"  0x460 slot0 bytes: {sum(len(v) for v in x460_s0.values())}, "
      f"slot1: {sum(len(v) for v in x460_s1.values())}")
print(f"  0x639 bytes: {[f'B{i}:{len(x639[i])}' for i in range(8)]}")

# Print unique values to help identify limit fields
print("\n0x440 unique values:")
print(f"  B0: {sorted(set(v for _,v in x440_B0))} (n={len(set(v for _,v in x440_B0))})")
print(f"  B2: range {min(v for _,v in x440_B2)}-{max(v for _,v in x440_B2)}, "
      f"n_unique={len(set(v for _,v in x440_B2))}")
print(f"  B4: {sorted(set(v for _,v in x440_B4))} (n={len(set(v for _,v in x440_B4))})")
print(f"  B5: {sorted(set(v for _,v in x440_B5))} (n={len(set(v for _,v in x440_B5))})")

print("\n0x460 slot-0 unique values per byte:")
for i in sorted(x460_s0):
    vals = sorted(set(v for _,v in x460_s0[i]))
    print(f"  B{i}: {vals} (n={len(vals)})")

print("\n0x460 slot-1 unique values per byte:")
for i in sorted(x460_s1):
    vals = sorted(set(v for _,v in x460_s1[i]))
    print(f"  B{i}: {vals} (n={len(vals)})")

print("\n0x639 unique values per byte:")
for i in range(8):
    vals = sorted(set(v for _,v in x639[i]))
    rng = f"{min(vals)}-{max(vals)}" if vals else "empty"
    print(f"  B{i}: n_unique={len(vals)}, range={rng}  "
          f"{'<< few unique -- LIMIT CANDIDATE' if 2 < len(vals) <= 30 else ''}")

# ── helper: unzip timeseries ─────────────────────────────────────────────────
def ts(data):
    if not data:
        return [], []
    t, v = zip(*data)
    return list(t), list(v)

# ── plot ─────────────────────────────────────────────────────────────────────
event_regions = [
    (30,  72,  'Downhill unrestricted regen', 'lime',   0.10),
    (401, 503, 'Regen limit active',           'yellow', 0.12),
    (598, 650, 'Highway discharge limit',      'orange', 0.10),
]

fig, axes = plt.subplots(4, 1, figsize=(18, 16), sharex=True)
fig.suptitle("vtruxcurrentlimitingtest — BMS Current Limit Candidates", fontsize=13)

def shade_events(ax):
    for t0, t1, label, color, alpha in event_regions:
        ax.axvspan(t0, t1, color=color, alpha=alpha, zorder=0)

# ── subplot 1: battery current + motor torque (reference) ────────────────────
ax = axes[0]
shade_events(ax)
t_I, v_I = ts(batt_I)
t_T, v_T = ts(torque)
ax.plot(t_I, [v * 0.04 for v in v_I], color='cyan',   lw=1.0, label='Batt I (A, x0.04)')
ax.plot(t_T, [v / 30   for v in v_T], color='magenta', lw=0.7, alpha=0.7, label='Motor torque /30')
ax.axhline(0, color='white', lw=0.5, ls='--')
ax.set_ylabel('Current (A) / Torque/30')
ax.legend(loc='upper right', fontsize=8)
ax.set_title('Reference signals')

# ── subplot 2: 0x440 candidates ──────────────────────────────────────────────
ax = axes[1]
shade_events(ax)
t0, v0 = ts(x440_B0)
t2, v2 = ts(x440_B2)
t4, v4 = ts(x440_B4)
t5, v5 = ts(x440_B5)
ax.plot(t0, v0, color='yellow',  lw=1.2, label='0x440 B0 (CCL hyp, 6-value)')
ax.plot(t2, v2, color='orange',  lw=1.0, label='0x440 B2 (DCL hyp, slow-vary)')
ax.plot(t4, v4, color='cyan',    lw=0.8, alpha=0.7, label='0x440 B4 (discrete)')
ax.plot(t5, v5, color='lime',    lw=0.8, alpha=0.7, label='0x440 B5 (discrete)')
ax.set_ylabel('Raw counts')
ax.legend(loc='upper right', fontsize=8)
ax.set_title('0x440 candidates')

# ── subplot 3: 0x460 slot-1 bytes ────────────────────────────────────────────
ax = axes[2]
shade_events(ax)
colors_s1 = ['red', 'orange', 'yellow', 'lime', 'cyan', 'violet', 'white']
for i, color in zip(sorted(x460_s1.keys()), colors_s1):
    tt, vv = ts(x460_s1[i])
    ax.plot(tt, vv, color=color, lw=0.9, label=f'0x460 slot1 B{i}')
ax.set_ylabel('Raw counts')
ax.legend(loc='upper right', fontsize=8)
ax.set_title('0x460 mux slot-1 bytes')

# ── subplot 4: 0x639 bytes (low-unique-count only) ───────────────────────────
ax = axes[3]
shade_events(ax)
colors_639 = ['red', 'orange', 'yellow', 'lime', 'cyan', 'blue', 'violet', 'white']
for i, color in zip(range(8), colors_639):
    if not x639[i]:
        continue
    n_uniq = len(set(v for _, v in x639[i]))
    tt, vv = ts(x639[i])
    lw = 1.2 if n_uniq <= 30 else 0.6
    label = f'0x639 B{i} ({n_uniq}u)'
    ax.plot(tt, vv, color=color, lw=lw, alpha=0.9 if n_uniq <= 30 else 0.5, label=label)
ax.set_ylabel('Raw counts')
ax.set_xlabel('Time (s)')
ax.legend(loc='upper right', fontsize=8)
ax.set_title('0x639 bytes (brighter/thicker = few unique values)')

# shade legend
patches = [mpatches.Patch(color=c, alpha=a+0.3, label=l)
           for _, _, l, c, a in event_regions]
fig.legend(handles=patches, loc='upper left', fontsize=8, bbox_to_anchor=(0.01, 0.99))

plt.tight_layout(rect=[0, 0, 1, 0.97])
out = Path(__file__).parent / "climit_candidates_plot.png"
plt.savefig(out, dpi=130, bbox_inches='tight')
print(f"\nPlot saved to {out}")
