"""
cruise_phase7_plot.py

Full-log overview plot for cruise control investigation.
Signals plotted (all from PT bus / Bus 2 unless noted):
  - 0x5A2 B2-B3 LE: motor speed (reference)
  - 0x594 B0:       speed-echo byte (VCU source)
  - 0x308 B2:       speed-echo byte (BorgWarner TCM shaft)
  - 0x639 B2:       BMS byte (locks during cruise)
  - 0x639 B3:       BMS byte (locks during cruise)

Vertical lines from 0x1E1 B5 on Bus 3 (Vehicle):
  - Tier 3 (48-60): setpoint decrement events  [orange dashed]
  - Tier 5 (80-92): engagement / cancel events [red dashed]

Output: cruise_phase7_overview.png
"""

import sys
import os
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

LOG    = 'projects/vtrux/logs/vtruxevapdrivelog4.log'
PT_BUS = 2
GM_BUS = 3   # Vehicle -- has 0x1E1

OUTPUT = 'projects/vtrux/notes/artifacts/cruise_phase7_overview.png'

print("Parsing log...")

from canre.parsers import parse_file

# Timeseries storage
ts_speed = []    # (t, val) motor speed 0x5A2 B2-B3 LE - 32768
ts_594b0 = []    # (t, val) 0x594 B0 raw uint8
ts_308b2 = []    # (t, val) 0x308 B2 raw uint8
ts_639b2 = []    # (t, val) 0x639 B2 raw uint8
ts_639b3 = []    # (t, val) 0x639 B3 raw uint8

# Cruise events from 0x1E1 B5 (GM bus)
# We record every frame where B5 is in tier 3 or tier 5
# Then collapse into burst start/end groups
ev_t3 = []    # tier 3 timestamps (48-60)
ev_t5 = []    # tier 5 timestamps (80-92)

TIER3_LO, TIER3_HI = 48, 60
TIER5_LO, TIER5_HI = 80, 92

frame_count = 0
for frame in parse_file(LOG):
    t = frame.timestamp
    aid = frame.arbitration_id
    data = frame.data

    if frame.bus == PT_BUS:
        if aid == 0x5A2 and len(data) >= 4:
            raw = (data[3] << 8) | data[2]
            ts_speed.append((t, raw - 32768))
        if aid == 0x594 and len(data) >= 1:
            ts_594b0.append((t, data[0]))
        if aid == 0x308 and len(data) >= 3:
            ts_308b2.append((t, data[2]))
        if aid == 0x639 and len(data) >= 4:
            ts_639b2.append((t, data[2]))
            ts_639b3.append((t, data[3]))

    elif frame.bus == GM_BUS:
        if aid == 0x1E1 and len(data) >= 6:
            b5 = data[5]
            if TIER3_LO <= b5 <= TIER3_HI:
                ev_t3.append(t)
            elif TIER5_LO <= b5 <= TIER5_HI:
                ev_t5.append(t)

    frame_count += 1
    if frame_count % 500000 == 0:
        print(f"  {frame_count:,} frames...")

print(f"Total frames parsed: {frame_count:,}")
print(f"Motor speed samples: {len(ts_speed)}")
print(f"0x594 B0 samples:    {len(ts_594b0)}")
print(f"0x308 B2 samples:    {len(ts_308b2)}")
print(f"0x639 B2 samples:    {len(ts_639b2)}")
print(f"Tier-3 frames (0x1E1 B5 48-60): {len(ev_t3)}")
print(f"Tier-5 frames (0x1E1 B5 80-92): {len(ev_t5)}")


def collapse_bursts(ts, gap=0.5):
    """Return list of (burst_start, burst_end) from a list of timestamps."""
    if not ts:
        return []
    bursts = []
    start = ts[0]
    prev  = ts[0]
    for t in ts[1:]:
        if t - prev > gap:
            bursts.append((start, prev))
            start = t
        prev = t
    bursts.append((start, prev))
    return bursts


bursts_t3 = collapse_bursts(ev_t3)
bursts_t5 = collapse_bursts(ev_t5)

print(f"\nTier-3 bursts: {len(bursts_t3)}")
for b in bursts_t3:
    print(f"  t={b[0]:.2f}-{b[1]:.2f}s")
print(f"Tier-5 bursts: {len(bursts_t5)}")
for b in bursts_t5:
    print(f"  t={b[0]:.2f}-{b[1]:.2f}s")


# ------------------------------------------------------------------
# Plot
# ------------------------------------------------------------------
print("\nBuilding plot...")

def unzip(pairs):
    if not pairs:
        return [], []
    ts, vs = zip(*pairs)
    return list(ts), list(vs)

t_speed, v_speed = unzip(ts_speed)
t_594,   v_594   = unzip(ts_594b0)
t_308,   v_308   = unzip(ts_308b2)
t_639b2_t, v_639b2 = unzip(ts_639b2)
t_639b3_t, v_639b3 = unzip(ts_639b3)

fig, axes = plt.subplots(4, 1, figsize=(20, 14), sharex=True)
fig.suptitle('Cruise Control Investigation -- vtruxevapdrivelog4.log (full log)', fontsize=13)

# Colours
C_T3 = '#E87722'   # orange -- tier 3 (setpoint decrement)
C_T5 = '#CC2222'   # red    -- tier 5 (engage/cancel)
ALPHA_LINE = 0.75

def draw_events(ax):
    for (t0, t1) in bursts_t3:
        ax.axvspan(t0, max(t1, t0 + 0.05), color=C_T3, alpha=0.35, linewidth=0)
        ax.axvline(t0, color=C_T3, linewidth=1.2, alpha=ALPHA_LINE, linestyle='--')
    for (t0, t1) in bursts_t5:
        ax.axvspan(t0, max(t1, t0 + 0.05), color=C_T5, alpha=0.35, linewidth=0)
        ax.axvline(t0, color=C_T5, linewidth=1.2, alpha=ALPHA_LINE, linestyle='--')

# Panel 1: motor speed
ax = axes[0]
ax.plot(t_speed, v_speed, color='steelblue', linewidth=0.6, label='0x5A2 B2-B3 (speed)')
draw_events(ax)
ax.set_ylabel('Motor speed\n(counts centered)', fontsize=9)
ax.legend(loc='upper left', fontsize=8)
ax.grid(True, alpha=0.25)

# Panel 2: 0x594 B0
ax = axes[1]
ax.plot(t_594, v_594, color='purple', linewidth=0.6, label='0x594 B0')
draw_events(ax)
ax.set_ylabel('0x594 B0\n(raw uint8)', fontsize=9)
ax.legend(loc='upper left', fontsize=8)
ax.grid(True, alpha=0.25)

# Panel 3: 0x308 B2
ax = axes[2]
ax.plot(t_308, v_308, color='darkgreen', linewidth=0.6, label='0x308 B2')
draw_events(ax)
ax.set_ylabel('0x308 B2\n(raw uint8)', fontsize=9)
ax.legend(loc='upper left', fontsize=8)
ax.grid(True, alpha=0.25)

# Panel 4: 0x639 B2 and B3
ax = axes[3]
ax.plot(t_639b2_t, v_639b2, color='darkorange', linewidth=0.6, label='0x639 B2')
ax.plot(t_639b3_t, v_639b3, color='crimson',    linewidth=0.6, label='0x639 B3', alpha=0.7)
draw_events(ax)
ax.set_ylabel('0x639 B2 / B3\n(raw uint8)', fontsize=9)
ax.legend(loc='upper left', fontsize=8)
ax.grid(True, alpha=0.25)
ax.set_xlabel('Time (s)', fontsize=10)

# Legend for event lines
patch_t3 = mpatches.Patch(color=C_T3, alpha=0.6, label='0x1E1 B5 tier 3 (48-60) -- setpoint decrement')
patch_t5 = mpatches.Patch(color=C_T5, alpha=0.6, label='0x1E1 B5 tier 5 (80-92) -- engage/cancel')
fig.legend(handles=[patch_t3, patch_t5], loc='lower center', ncol=2, fontsize=9,
           bbox_to_anchor=(0.5, 0.01))

plt.tight_layout(rect=[0, 0.04, 1, 1])
plt.savefig(OUTPUT, dpi=150, bbox_inches='tight')
plt.close()

print(f"\nPlot saved to {OUTPUT}")
