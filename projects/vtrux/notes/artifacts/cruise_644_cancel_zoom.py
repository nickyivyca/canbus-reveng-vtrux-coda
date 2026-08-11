"""
cruise_644_cancel_zoom.py

Zoomed view of the cruise cancel window in vtruxanotherevaplogpart2.log.
Shows:
  - 0x644 B2 (uint8) -- suspected cruise setpoint
  - 0x592 B2-B3 LE   -- throttle pedal (centered at 32768)
  - 0x1E1 B5 non-baseline events (button presses)

Window: t=1370-1445s (covers throttle application + cancel)

Bus assignments:
  PT bus = 3  (0x051, 0x644, 0x592)
  GM bus = 1  (0x1E1)
"""

import sys, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

LOG    = 'projects/vtrux/logs/vtruxanotherevaplogpart2.log'
PT_BUS = 3
GM_BUS = 1
OUTPUT = 'projects/vtrux/notes/artifacts/cruise_644_cancel_zoom.png'

WIN_LO, WIN_HI = 1370.0, 1445.0
BASELINE_LO, BASELINE_HI = 16, 28

print("Parsing (collecting window only)...")
from canre.parsers import parse_file

ts_b2, vs_b2     = [], []   # 0x644 B2
ts_thr, vs_thr   = [], []   # 0x592 B2-B3 LE throttle
ts_b5ev, vs_b5ev = [], []   # 0x1E1 B5 non-baseline

total = 0
for frame in parse_file(LOG):
    total += 1
    t = frame.timestamp
    if t < WIN_LO - 5 or t > WIN_HI + 5:
        continue
    aid  = frame.arbitration_id
    data = frame.data

    if frame.bus == PT_BUS:
        if aid == 0x644 and len(data) >= 3:
            ts_b2.append(t); vs_b2.append(data[2])
        if aid == 0x592 and len(data) >= 4:
            raw = (data[3] << 8) | data[2]
            ts_thr.append(t); vs_thr.append(raw - 32768)

    elif frame.bus == GM_BUS and aid == 0x1E1 and len(data) >= 6:
        b5 = data[5]
        if not (BASELINE_LO <= b5 <= BASELINE_HI):
            ts_b5ev.append(t); vs_b5ev.append(b5)

    if total % 1000000 == 0:
        print(f"  {total:,}...")

print(f"Total frames scanned: {total:,}")
print(f"0x644 B2 samples in window: {len(ts_b2)}")
print(f"Throttle samples in window: {len(ts_thr)}")
print(f"B5 events in window: {len(ts_b5ev)}")
for t, v in zip(ts_b5ev, vs_b5ev):
    tier = ('Set/dec' if 48<=v<=60 else
            'Eng/Cxl' if 80<=v<=92 else
            'Speed+?' if 32<=v<=44 else 'other')
    print(f"  t={t:.3f}  B5={v}  ({tier})")


def ev_color(v):
    if 48 <= v <= 60:  return '#E87722'
    if 80 <= v <= 92:  return '#CC2222'
    if 32 <= v <= 44:  return '#2288CC'
    return '#888888'

def draw_events(ax):
    for t, v in zip(ts_b5ev, vs_b5ev):
        if WIN_LO <= t <= WIN_HI:
            c = ev_color(v)
            ax.axvline(t, color=c, linewidth=1.5, linestyle='--', alpha=0.9)
            ax.text(t + 0.3, ax.get_ylim()[1] * 0.97, f'B5={v}',
                    fontsize=7, color=c, rotation=90, va='top')

print("\nBuilding plot...")

fig, axes = plt.subplots(2, 1, figsize=(16, 8), sharex=True)
fig.suptitle(
    'Cruise cancel window -- vtruxanotherevaplogpart2.log  (t=1370-1445s)\n'
    'Throttle applied before cancel: does 0x644 B2 step at throttle onset?',
    fontsize=11)

# Panel 1: 0x644 B2
ax = axes[0]
ax.plot(ts_b2, vs_b2, color='steelblue', linewidth=1.2, marker='.', markersize=2)
ax.set_ylabel('0x644 B2 (uint8)', fontsize=9)
ax.set_xlim(WIN_LO, WIN_HI)
ax.grid(True, alpha=0.3)
# Draw events after setting ylim
ax.set_ylim(min(vs_b2) - 2, max(vs_b2) + 5) if vs_b2 else None
for t, v in zip(ts_b5ev, vs_b5ev):
    if WIN_LO <= t <= WIN_HI:
        c = ev_color(v)
        ax.axvline(t, color=c, linewidth=1.5, linestyle='--', alpha=0.9)
        if ax.get_ylim()[1] > ax.get_ylim()[0]:
            ax.text(t + 0.2, ax.get_ylim()[0] + (ax.get_ylim()[1]-ax.get_ylim()[0])*0.05,
                    f'B5={v}', fontsize=7, color=c, rotation=90, va='bottom')

# Panel 2: throttle
ax2 = axes[1]
ax2.plot(ts_thr, vs_thr, color='firebrick', linewidth=1.2)
ax2.axhline(0, color='black', linewidth=0.5, linestyle=':')
ax2.set_ylabel('Throttle pedal\n0x592 B2-B3 (centered)', fontsize=9)
ax2.set_xlabel('Time (s)', fontsize=10)
ax2.set_xlim(WIN_LO, WIN_HI)
ax2.grid(True, alpha=0.3)
for t, v in zip(ts_b5ev, vs_b5ev):
    if WIN_LO <= t <= WIN_HI:
        c = ev_color(v)
        ax2.axvline(t, color=c, linewidth=1.5, linestyle='--', alpha=0.9)

patch_set = mpatches.Patch(color='#E87722', alpha=0.8, label='B5 48-60: Set/decrement')
patch_ec  = mpatches.Patch(color='#CC2222', alpha=0.8, label='B5 80-92: Engage/Cancel')
patch_sp  = mpatches.Patch(color='#2288CC', alpha=0.8, label='B5 32-44: Speed+?')
fig.legend(handles=[patch_set, patch_ec, patch_sp],
           loc='lower center', ncol=3, fontsize=9, bbox_to_anchor=(0.5, 0.01))

plt.tight_layout(rect=[0, 0.06, 1, 1])
plt.savefig(OUTPUT, dpi=150, bbox_inches='tight')
plt.close()
print(f"Saved -> {OUTPUT}")
