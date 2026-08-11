"""
plot_0x050_corrected.py

Re-plot 0x050 10-bit traction torque signal with corrected zero at raw=192.
  Signal = (B1 & 0x03) << 8 | B0  -- centered at 192 (not 512)
  Traction feedback = 0x5A2 B4-B5 LE, centered 32768

Two panels:
  1. 10-bit signal alone (zero = 192)
  2. Overlay: 10-bit signal vs traction feedback scaled to match

Output: plot_0x050_corrected.png
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG    = 'projects/vtrux/logs/vtruxevapdrivelog4.log'
PT_BUS = 2
OUTPUT = 'projects/vtrux/notes/artifacts/plot_0x050_corrected2.png'
ZERO   = 292   # confirmed true zero from startup data

MARKERS = {431: ('gen start',   'green'),
           720: ('cruise start','blue'),
           1103:('exit',        'orange'),
           1108:('brake',       'red')}

print("Parsing...")
sig10 = []
tract_fb = []

for frame in parse_file(LOG):
    if frame.bus != PT_BUS: continue
    t = frame.timestamp; d = frame.data; aid = frame.arbitration_id
    if aid == 0x050 and len(d) >= 2:
        val = ((d[1] & 0x03) << 8 | d[0]) - ZERO
        sig10.append((t, val))
    elif aid == 0x5A2 and len(d) >= 6:
        tract_fb.append((t, ((d[5] << 8) | d[4]) - 32768))

print(f"0x050 frames: {len(sig10)}  traction samples: {len(tract_fb)}")

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

ts, vs   = zip(*sig10)
tf_t, tf_v = zip(*tract_fb)

# Scale factor: match traction feedback range to signal range
sig_max = max(abs(v) for v in vs)
tf_max  = max(abs(v) for v in tf_v)
scale   = sig_max / tf_max if tf_max else 1.0

fig, axes = plt.subplots(2, 1, figsize=(18, 9), sharex=True)
fig.suptitle('0x050 10-bit traction torque command -- zero corrected to raw=192\n'
             'Signal = (B1 & 0x03) << 8 | B0  -- 192', fontsize=12)

def mlines(ax):
    for tm, (lb, col) in MARKERS.items():
        ax.axvline(tm, color=col, lw=1.0, ls='--', alpha=0.7, label=f't={tm}: {lb}')
    ax.axhline(0, color='k', lw=0.6, ls='-', alpha=0.5)

# Panel 1: signal alone
ax = axes[0]
ax.plot(ts, vs, color='purple', lw=0.7, label='10-bit (zero=192)')
mlines(ax)
ax.set_ylabel('Torque command (counts above zero)')
ax.set_title('10-bit signal with corrected zero (positive = drive, negative = regen)')
ax.legend(loc='upper left', fontsize=8, ncol=3)

# Panel 2: overlay with traction feedback
ax = axes[1]
ax.plot(ts, vs, color='purple', lw=0.7, label='0x050 10-bit (zero=192)')
ax.plot(tf_t, [v * scale for v in tf_v], color='steelblue', lw=0.5, alpha=0.65,
        label=f'Traction feedback 0x5A2 B4-B5 (x{scale:.4f})')
mlines(ax)
ax.set_ylabel('Counts (feedback rescaled to match)')
ax.set_xlabel('Time (s)')
ax.set_title('10-bit command vs traction torque feedback (scaled to overlay)')
ax.legend(loc='upper left', fontsize=8, ncol=3)

plt.tight_layout()
plt.savefig(OUTPUT, dpi=130, bbox_inches='tight')
print(f"Saved: {OUTPUT}")
