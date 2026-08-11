"""
cruise_644_bytes_zoom.py

Zoom into t=900-1500s of vtruxanotherevaplogpart2.log.
Plots all 0x644 bytes (B0-B5) individually PLUS nibble decompositions of B1-B3
to check: is B2 a speed command (increments with +/-) or just a mode byte,
and is there a 12-bit speed field hiding across adjacent bytes?

Bus assignments (evaplog2):
  PT_BUS = 3  (0x051, 0x644, 0x592)
  GM_BUS = 1  (0x1E1)
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
OUTPUT = 'projects/vtrux/notes/artifacts/cruise_644_bytes_zoom.png'

WIN_LO, WIN_HI = 900.0, 1500.0
BASELINE_LO, BASELINE_HI = 16, 28

print("Parsing...")
from canre.parsers import parse_file

# 0x644 bytes B0-B5 individually
N_BYTES = 6
ts_b  = [[] for _ in range(N_BYTES)]
vs_b  = [[] for _ in range(N_BYTES)]

# Derived: nibbles and multi-byte fields from B1/B2/B3
# B2 high nibble (bits 7-4) and low nibble (bits 3-0)
ts_b2hi, vs_b2hi = [], []
ts_b2lo, vs_b2lo = [], []

# B1 low nibble + B2 high nibble = 8-bit field (B1[3:0] << 4 | B2[7:4])
# B2 low nibble + B3 = 12-bit field (B2[3:0] << 8 | B3) -- possible speed word
ts_b2lo_b3, vs_b2lo_b3 = [], []  # (B2 & 0x0F) << 8 | B3

# All 0x1E1 B5 non-baseline events
ts_b5ev, vs_b5ev = [], []

total = 0
for frame in parse_file(LOG):
    total += 1
    t = frame.timestamp
    if t < WIN_LO - 5 or t > WIN_HI + 5:
        continue
    aid  = frame.arbitration_id
    data = frame.data

    if frame.bus == PT_BUS and aid == 0x644 and len(data) >= N_BYTES:
        for i in range(N_BYTES):
            ts_b[i].append(t)
            vs_b[i].append(data[i])
        b1 = data[1]; b2 = data[2]; b3 = data[3]
        ts_b2hi.append(t); vs_b2hi.append((b2 >> 4) & 0x0F)
        ts_b2lo.append(t); vs_b2lo.append(b2 & 0x0F)
        ts_b2lo_b3.append(t); vs_b2lo_b3.append(((b2 & 0x0F) << 8) | b3)

    elif frame.bus == GM_BUS and aid == 0x1E1 and len(data) >= 6:
        b5 = data[5]
        if not (BASELINE_LO <= b5 <= BASELINE_HI):
            ts_b5ev.append(t); vs_b5ev.append(b5)

    if total % 1000000 == 0:
        print(f"  {total:,}...")

print(f"Total frames: {total:,}")
print(f"0x644 samples in window: {len(ts_b[0])}")
print(f"B5 events in window: {len(ts_b5ev)}")

# Print unique B2 values and their high/low nibbles
b2_vals = sorted(set(vs_b[2]))
print(f"\nUnique B2 values: {b2_vals}")
print(f"  {'B2':>4}  {'hex':>4}  {'hi_nib':>6}  {'lo_nib':>6}  {'hi_meaning?':}")
for v in b2_vals:
    print(f"  {v:>4}  0x{v:02X}  {(v>>4)&0xF:>6}  {v&0xF:>6}")

print(f"\nUnique B2lo_B3 (12-bit) values seen: {len(set(vs_b2lo_b3))}")
vals_12 = sorted(set(vs_b2lo_b3))
print(f"  range: {min(vals_12)} - {max(vals_12)}")

print("\nB5 events in window:")
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

def draw_ev(ax, ypos_frac=0.92):
    yl = ax.get_ylim()
    yspan = yl[1] - yl[0]
    for t, v in zip(ts_b5ev, vs_b5ev):
        if WIN_LO <= t <= WIN_HI:
            c = ev_color(v)
            ax.axvline(t, color=c, linewidth=1.2, linestyle='--', alpha=0.85)

print("\nBuilding plot...")

# 8 panels: B0-B5 (6), B2 nibbles (2), 12-bit B2lo_B3 (1)
fig, axes = plt.subplots(9, 1, figsize=(22, 22), sharex=True)
fig.suptitle(
    '0x644 byte anatomy -- vtruxanotherevaplogpart2.log  (t=900-1500s)\n'
    'Checking: which byte/nibble encodes speed command vs mode state?',
    fontsize=11)

colors = ['#444444','#1a6fb0','#cc3311','#117733','#aa4499','#ddcc77']
for i in range(N_BYTES):
    ax = axes[i]
    ax.plot(ts_b[i], vs_b[i], color=colors[i], linewidth=0.8, marker='.', markersize=1)
    ax.set_ylabel(f'B{i}\n(uint8)', fontsize=8)
    ax.set_xlim(WIN_LO, WIN_HI)
    ax.grid(True, alpha=0.25)
    ax.set_ylim(min(vs_b[i]) - 2, max(vs_b[i]) + 5) if vs_b[i] else None
    draw_ev(ax)

# Panel 6: B2 high nibble
ax6 = axes[6]
ax6.plot(ts_b2hi, vs_b2hi, color='#9933aa', linewidth=0.8, marker='.', markersize=1)
ax6.set_ylabel('B2 hi\nnibble (7-4)', fontsize=8)
ax6.set_xlim(WIN_LO, WIN_HI)
ax6.grid(True, alpha=0.25)
ax6.set_ylim(-0.5, 16.5)
ax6.set_yticks(range(17))
draw_ev(ax6)

# Panel 7: B2 low nibble
ax7 = axes[7]
ax7.plot(ts_b2lo, vs_b2lo, color='#0077bb', linewidth=0.8, marker='.', markersize=1)
ax7.set_ylabel('B2 lo\nnibble (3-0)', fontsize=8)
ax7.set_xlim(WIN_LO, WIN_HI)
ax7.grid(True, alpha=0.25)
ax7.set_ylim(-0.5, 16.5)
ax7.set_yticks(range(17))
draw_ev(ax7)

# Panel 8: 12-bit field B2[3:0]<<8 | B3
ax8 = axes[8]
ax8.plot(ts_b2lo_b3, vs_b2lo_b3, color='#228833', linewidth=0.9)
ax8.set_ylabel('B2[3:0]<<8|B3\n(12-bit)', fontsize=8)
ax8.set_xlabel('Time (s)', fontsize=10)
ax8.set_xlim(WIN_LO, WIN_HI)
ax8.grid(True, alpha=0.25)
draw_ev(ax8)

patch_set = mpatches.Patch(color='#E87722', alpha=0.8, label='B5 48-60: Set/decrement')
patch_ec  = mpatches.Patch(color='#CC2222', alpha=0.8, label='B5 80-92: Engage/Cancel')
patch_sp  = mpatches.Patch(color='#2288CC', alpha=0.8, label='B5 32-44: Speed+?')
fig.legend(handles=[patch_set, patch_ec, patch_sp],
           loc='lower center', ncol=3, fontsize=9, bbox_to_anchor=(0.5, 0.005))

plt.tight_layout(rect=[0, 0.02, 1, 1])
plt.savefig(OUTPUT, dpi=130, bbox_inches='tight')
plt.close()
print(f"Saved -> {OUTPUT}")
