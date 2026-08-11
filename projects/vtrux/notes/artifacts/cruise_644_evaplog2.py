"""
cruise_644_evaplog2.py

Plot 0x644 B2-B3 (BE16 - 32768) from vtruxanotherevaplogpart2.log
with vertical lines for all 0x1E1 B5 cruise button events.

Bus assignments in this log:
  Bus 1: Vehicle (0x1E5 present) -- has 0x1E1 cruise events
  Bus 3: Powertrain    (0x051 present) -- has 0x644

Output: cruise_644_evaplog2.png
"""

import sys, os, math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

LOG    = 'projects/vtrux/logs/vtruxanotherevaplogpart2.log'
PT_BUS = 3
GM_BUS = 1

OUTPUT = 'projects/vtrux/notes/artifacts/cruise_644_evaplog2.png'

# Collect ALL non-baseline B5 values (not just known tiers) so we see every button event
BASELINE_LO, BASELINE_HI = 16, 28   # tier 1 rolling counter -- ignore these

print("Parsing...")
from canre.parsers import parse_file

ts_644b2 = []; vs_644b2 = []   # 0x644 B2 uint8
ts_b5    = []; vs_b5    = []   # 0x1E1 B5 ALL values (full 33Hz trace)
ts_b5ev  = []; vs_b5ev  = []   # 0x1E1 B5 non-baseline only (button events)

total = 0
for frame in parse_file(LOG):
    total += 1
    t = frame.timestamp
    aid = frame.arbitration_id
    data = frame.data

    if frame.bus == PT_BUS and aid == 0x644 and len(data) >= 3:
        ts_644b2.append(t)
        vs_644b2.append(data[2])   # raw uint8

    elif frame.bus == GM_BUS and aid == 0x1E1 and len(data) >= 6:
        b5 = data[5]
        ts_b5.append(t)
        vs_b5.append(b5)
        if not (BASELINE_LO <= b5 <= BASELINE_HI):
            ts_b5ev.append(t)
            vs_b5ev.append(b5)

    if total % 1000000 == 0:
        print(f"  {total:,} frames...")

print(f"Total frames: {total:,}")
print(f"0x644 B2 samples: {len(ts_644b2)}")
print(f"0x1E1 B5 samples: {len(ts_b5)}  non-baseline events: {len(ts_b5ev)}")

# Print non-baseline B5 unique values seen
b5_ev_vals = sorted(set(vs_b5ev))
print(f"Non-baseline B5 values: {b5_ev_vals}")


def collapse_bursts(ts_vals, gap=0.5):
    """Collapse (t, v) pairs into bursts: [(t_start, t_end, dominant_value)]"""
    if not ts_vals:
        return []
    bursts, start, prev_t, vals = [], ts_vals[0][0], ts_vals[0][0], [ts_vals[0][1]]
    for t, v in ts_vals[1:]:
        if t - prev_t > gap:
            dom = max(set(vals), key=vals.count)
            bursts.append((start, prev_t, dom))
            start, vals = t, []
        vals.append(v)
        prev_t = t
    dom = max(set(vals), key=vals.count)
    bursts.append((start, prev_t, dom))
    return bursts

ev_bursts = collapse_bursts(list(zip(ts_b5ev, vs_b5ev)))

print(f"\nNon-baseline B5 bursts ({len(ev_bursts)}):")
for b in ev_bursts:
    print(f"  t={b[0]:.2f}-{b[1]:.2f}s  dominant_B5={b[2]}")

# Colour by value range
def ev_color(v):
    if 48 <= v <= 60:  return '#E87722'   # tier 3: orange
    if 80 <= v <= 92:  return '#CC2222'   # tier 5: red
    if 64 <= v <= 76:  return '#2288CC'   # tier 4 (Speed+?): blue
    return '#888888'                       # other: grey

print("\nBuilding plot...")

import bisect

def nearest_644b2(t, after=True, offset=0.15):
    idx = bisect.bisect_left(ts_644b2, t + (offset if after else 0))
    if idx < len(ts_644b2):
        return vs_644b2[idx]
    return None

fig, axes = plt.subplots(3, 1, figsize=(22, 11), sharex=True)
fig.suptitle('0x644 B2 (uint8) and 0x1E1 B5 button events -- vtruxanotherevaplogpart2.log',
             fontsize=12)

# --- Panel 1: 0x644 B2 uint8, full log ---
ax = axes[0]
ax.plot(ts_644b2, vs_644b2, color='steelblue', linewidth=0.6)
for (t0, t1, dom) in ev_bursts:
    c = ev_color(dom)
    ax.axvspan(t0, max(t1, t0+0.05), color=c, alpha=0.35, linewidth=0)
    ax.axvline(t0, color=c, linewidth=1.2, linestyle='--', alpha=0.85)
    v = nearest_644b2(t1)
    if v is not None:
        ax.annotate(str(v), xy=(t0, v), xytext=(t0+2, v+0.3),
                    fontsize=7, color='navy',
                    arrowprops=dict(arrowstyle='->', color='navy', lw=0.7))
ax.set_ylabel('0x644 B2\n(uint8)', fontsize=9)
ax.set_title('Full log -- annotated value after each button event', fontsize=9, loc='left')
ax.grid(True, alpha=0.25)

# --- Panel 2: zoom ---
ax2 = axes[1]
ax2.plot(ts_644b2, vs_644b2, color='steelblue', linewidth=0.9)
for (t0, t1, dom) in ev_bursts:
    c = ev_color(dom)
    ax2.axvspan(t0, max(t1, t0+0.05), color=c, alpha=0.35, linewidth=0)
    ax2.axvline(t0, color=c, linewidth=1.2, linestyle='--', alpha=0.85)
    v = nearest_644b2(t1)
    if v is not None:
        ax2.annotate(str(v), xy=(t0, v), xytext=(t0+3, v+0.4),
                     fontsize=8, color='navy',
                     arrowprops=dict(arrowstyle='->', color='navy', lw=0.8))
ax2.set_ylabel('0x644 B2\n(uint8)', fontsize=9)
ax2.grid(True, alpha=0.25)
all_ev_t = [b[0] for b in ev_bursts]
if all_ev_t:
    t_lo = max(0, min(all_ev_t) - 60)
    t_hi = max(all_ev_t) + 90
    ax2.set_xlim(t_lo, t_hi)
    ax2.set_title(f'Zoomed: t={t_lo:.0f}-{t_hi:.0f}s', fontsize=9, loc='left')

# --- Panel 3: raw B5 (non-baseline only) as scatter ---
ax3 = axes[2]
colors3 = [ev_color(v) for v in vs_b5ev]
ax3.scatter(ts_b5ev, vs_b5ev, c=colors3, s=6, linewidths=0)
ax3.set_ylabel('0x1E1 B5\n(non-baseline)', fontsize=9)
ax3.set_title('All non-baseline B5 events (tier 1 = 16-28 filtered out)', fontsize=9, loc='left')
ax3.grid(True, alpha=0.25)
ax3.set_xlabel('Time (s)', fontsize=10)
if all_ev_t:
    ax3.set_xlim(t_lo, t_hi)

patch_t3 = mpatches.Patch(color='#E87722', alpha=0.7, label='B5 48-60 (tier 3, Speed-)')
patch_t4 = mpatches.Patch(color='#2288CC', alpha=0.7, label='B5 64-76 (tier 4, Speed+?)')
patch_t5 = mpatches.Patch(color='#CC2222', alpha=0.7, label='B5 80-92 (tier 5, engage/cancel)')
patch_ot = mpatches.Patch(color='#888888', alpha=0.7, label='B5 other')
fig.legend(handles=[patch_t3, patch_t4, patch_t5, patch_ot],
           loc='lower center', ncol=4, fontsize=9, bbox_to_anchor=(0.5, 0.005))

plt.tight_layout(rect=[0, 0.04, 1, 1])
plt.savefig(OUTPUT, dpi=150, bbox_inches='tight')
plt.close()
print(f"\nSaved -> {OUTPUT}")
