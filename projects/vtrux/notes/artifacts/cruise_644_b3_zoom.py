"""
cruise_644_b3_zoom.py

Focused view of 0x644 B2 and B3 across the cruise window in evaplog2.
B2 has only 5 unique values -- high nibble appears to be mode (8=idle, 9=override,
10=active cruise). B3 is the active-variation byte during cruise.

Also plots the 12-bit field B2[3:0]<<8 | B3.

Bus assignments (evaplog2):
  PT_BUS = 3   GM_BUS = 1
"""

import sys, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import bisect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

LOG    = 'projects/vtrux/logs/vtruxanotherevaplogpart2.log'
PT_BUS = 3
GM_BUS = 1
OUTPUT = 'projects/vtrux/notes/artifacts/cruise_644_b3_zoom.png'

WIN_LO, WIN_HI = 960.0, 1250.0   # tight cruise window
BASELINE_LO, BASELINE_HI = 16, 28

print("Parsing...")
from canre.parsers import parse_file

ts_b2, vs_b2     = [], []
ts_b3, vs_b3     = [], []
ts_b2hi, vs_b2hi = [], []
ts_b2lo, vs_b2lo = [], []
ts_12,   vs_12   = [], []   # B2[3:0]<<8 | B3
ts_b5ev, vs_b5ev = [], []

total = 0
for frame in parse_file(LOG):
    total += 1
    t = frame.timestamp
    if t < WIN_LO - 5 or t > WIN_HI + 5:
        continue
    aid  = frame.arbitration_id
    data = frame.data

    if frame.bus == PT_BUS and aid == 0x644 and len(data) >= 4:
        b2 = data[2]; b3 = data[3]
        ts_b2.append(t); vs_b2.append(b2)
        ts_b3.append(t); vs_b3.append(b3)
        ts_b2hi.append(t); vs_b2hi.append((b2 >> 4) & 0xF)
        ts_b2lo.append(t); vs_b2lo.append(b2 & 0xF)
        ts_12.append(t);   vs_12.append(((b2 & 0xF) << 8) | b3)

    elif frame.bus == GM_BUS and aid == 0x1E1 and len(data) >= 6:
        b5 = data[5]
        if not (BASELINE_LO <= b5 <= BASELINE_HI):
            ts_b5ev.append(t); vs_b5ev.append(b5)

    if total % 2000000 == 0:
        print(f"  {total:,}...")

print(f"Frames: {total:,}  |  0x644: {len(ts_b2)}  |  B5 events: {len(ts_b5ev)}")

# Collapse B5 into bursts, then print B2/B3 before+after each burst
from collections import defaultdict

def collapse_bursts(pairs, gap=0.5):
    if not pairs: return []
    bursts, start, prev_t, vals = [], pairs[0][0], pairs[0][0], [pairs[0][1]]
    for t, v in pairs[1:]:
        if t - prev_t > gap:
            dom = max(set(vals), key=vals.count)
            bursts.append((start, prev_t, dom))
            start, vals = t, []
        vals.append(v); prev_t = t
    dom = max(set(vals), key=vals.count)
    bursts.append((start, prev_t, dom))
    return bursts

bursts = collapse_bursts(list(zip(ts_b5ev, vs_b5ev)))

def nearest_644(t, before=True, offset=0.3):
    idx = bisect.bisect_left(ts_b2, t - offset if before else t + offset)
    idx = max(0, min(idx, len(ts_b2)-1))
    if before and idx > 0: idx -= 1
    if 0 <= idx < len(ts_b2):
        return vs_b2[idx], vs_b3[idx]
    return None, None

print("\nB2/B3 at each event burst:")
print(f"  {'t_start':>10}  {'tier':>10}  {'B2_before':>10}  {'B3_before':>10}  {'B2_after':>10}  {'B3_after':>10}  {'12bit_before':>12}  {'12bit_after':>12}")
for (t0, t1, dom) in bursts:
    tier = ('Set' if 48<=dom<=60 else 'Eng/Cxl' if 80<=dom<=92 else 'Speed+' if 32<=dom<=44 else 'other')
    b2b, b3b = nearest_644(t0, before=True)
    b2a, b3a = nearest_644(t1, before=False)
    f12b = ((b2b & 0xF) << 8 | b3b) if b2b is not None else None
    f12a = ((b2a & 0xF) << 8 | b3a) if b2a is not None else None
    print(f"  {t0:>10.3f}  {tier:>10}  {str(b2b):>10}  {str(b3b):>10}  {str(b2a):>10}  {str(b3a):>10}  {str(f12b):>12}  {str(f12a):>12}")


def ev_color(v):
    if 48 <= v <= 60:  return '#E87722'
    if 80 <= v <= 92:  return '#CC2222'
    if 32 <= v <= 44:  return '#2288CC'
    return '#888888'

def draw_ev(ax, label_b2=None, label_b3=None):
    yl = ax.get_ylim()
    yspan = yl[1] - yl[0]
    prev_t = -9999
    for (t0, t1, dom) in bursts:
        if not (WIN_LO <= t0 <= WIN_HI): continue
        c = ev_color(dom)
        ax.axvline(t0, color=c, linewidth=1.5, linestyle='--', alpha=0.85)
        # Label with B2 and B3 after the burst
        if label_b2 is not None and label_b3 is not None:
            b2a, b3a = nearest_644(t1, before=False)
            if b2a is not None and t0 - prev_t > 3:
                lbl = f'B2={b2a}\nB3={b3a}'
                ax.text(t0 + 0.4, yl[0] + yspan * 0.55, lbl,
                        fontsize=7, color=c, va='bottom')
                prev_t = t0

print("\nBuilding plot...")

fig, axes = plt.subplots(4, 1, figsize=(22, 14), sharex=True)
fig.suptitle(
    '0x644 B2 and B3 detail -- evaplog2 cruise window (t=960-1250s)\n'
    'B2 hi nibble = mode, B3 = suspected speed command byte',
    fontsize=11)

# Panel 0: B2 full byte
ax0 = axes[0]
ax0.plot(ts_b2, vs_b2, color='#cc3311', linewidth=1.0, marker='.', markersize=2)
ax0.set_ylabel('B2 (uint8)', fontsize=9)
ax0.set_xlim(WIN_LO, WIN_HI)
ax0.grid(True, alpha=0.25)
if vs_b2: ax0.set_ylim(min(vs_b2)-2, max(vs_b2)+5)
for (t0, t1, dom) in bursts:
    if WIN_LO <= t0 <= WIN_HI:
        ax0.axvline(t0, color=ev_color(dom), linewidth=1.5, linestyle='--', alpha=0.85)

# Panel 1: B2 hi nibble (mode) and lo nibble overlaid
ax1 = axes[1]
ax1.plot(ts_b2hi, vs_b2hi, color='#9933aa', linewidth=1.2, label='B2[7:4] hi nibble (mode)')
ax1.plot(ts_b2lo, vs_b2lo, color='#0077bb', linewidth=1.2, linestyle=':', label='B2[3:0] lo nibble')
ax1.set_ylabel('B2 nibbles', fontsize=9)
ax1.set_xlim(WIN_LO, WIN_HI)
ax1.set_ylim(-0.5, 16)
ax1.set_yticks([0,2,3,4,6,8,9,10,12,14,15])
ax1.yaxis.set_tick_params(labelsize=7)
ax1.grid(True, alpha=0.25)
ax1.legend(fontsize=8, loc='upper left')
for (t0, t1, dom) in bursts:
    if WIN_LO <= t0 <= WIN_HI:
        ax1.axvline(t0, color=ev_color(dom), linewidth=1.5, linestyle='--', alpha=0.85)

# Panel 2: B3 (the active byte)
ax2 = axes[2]
ax2.plot(ts_b3, vs_b3, color='#117733', linewidth=1.0, marker='.', markersize=1)
ax2.set_ylabel('B3 (uint8)', fontsize=9)
ax2.set_xlim(WIN_LO, WIN_HI)
ax2.grid(True, alpha=0.25)
if vs_b3: ax2.set_ylim(min(vs_b3)-2, max(vs_b3)+10)
# annotate B3 value after each burst
yl2 = (min(vs_b3) if vs_b3 else 0, max(vs_b3) if vs_b3 else 255)
prev_t = -9999
for (t0, t1, dom) in bursts:
    if WIN_LO <= t0 <= WIN_HI:
        c = ev_color(dom)
        ax2.axvline(t0, color=c, linewidth=1.5, linestyle='--', alpha=0.85)
        b2a, b3a = nearest_644(t1, before=False)
        if b3a is not None and t0 - prev_t > 5:
            yspan2 = yl2[1]-yl2[0] if yl2[1]!=yl2[0] else 1
            ax2.text(t0 + 0.5, yl2[0] + yspan2*0.5 + (20 if (b3a > (yl2[0]+yl2[1])/2) else -20),
                     str(b3a), fontsize=8, color=c, fontweight='bold')
            prev_t = t0

# Panel 3: 12-bit field
ax3 = axes[3]
ax3.plot(ts_12, vs_12, color='#aa4400', linewidth=1.0)
ax3.set_ylabel('B2[3:0]<<8|B3\n(12-bit speed?)', fontsize=9)
ax3.set_xlabel('Time (s)', fontsize=10)
ax3.set_xlim(WIN_LO, WIN_HI)
ax3.grid(True, alpha=0.25)
for (t0, t1, dom) in bursts:
    if WIN_LO <= t0 <= WIN_HI:
        ax3.axvline(t0, color=ev_color(dom), linewidth=1.5, linestyle='--', alpha=0.85)

patch_set = mpatches.Patch(color='#E87722', alpha=0.8, label='B5 48-60: Set/dec')
patch_ec  = mpatches.Patch(color='#CC2222', alpha=0.8, label='B5 80-92: Engage/Cancel')
patch_sp  = mpatches.Patch(color='#2288CC', alpha=0.8, label='B5 32-44: Speed+')
fig.legend(handles=[patch_set, patch_ec, patch_sp],
           loc='lower center', ncol=3, fontsize=9, bbox_to_anchor=(0.5, 0.005))

plt.tight_layout(rect=[0, 0.04, 1, 1])
plt.savefig(OUTPUT, dpi=150, bbox_inches='tight')
plt.close()
print(f"Saved -> {OUTPUT}")
