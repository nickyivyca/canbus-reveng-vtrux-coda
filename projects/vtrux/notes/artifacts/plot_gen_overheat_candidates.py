"""
Plot thermal candidates against vtruxgeneratoroverheattest.log.

Top panel: OBD RPM (ground truth, replaces 0x63C B6 which overflows at peak).
Subsequent panels: one per candidate.
Vertical markers:
  t=1858.1  RPM peak W1 (first brief overflow)
  t=1921.4  RPM overflow W2 start
  t=1930.9  OBD peak RPM (~4686)
  t=1935.5  RPM overflow end / RPM declining

Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/plot_gen_overheat_candidates.py
"""
import sys
sys.path.insert(0, '.')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from canre.parsers import parse_file

LOG = r'projects/vtrux/logs/vtruxgeneratoroverheattest.log'
OUT = r'projects/vtrux/notes/artifacts/gen_overheat_candidates.png'

KEY_TIMES = [
    (1858.1, 'RPM peak W1'),
    (1921.4, 'overflow W2'),
    (1930.9, 'OBD peak'),
    (1935.5, 'unwrap'),
]

# (arb_id, byte_idx_or_spec, label, color)
# spec: ('raw', b) or ('9bit', b0, b1_carry_bit)  9bit = (B1[bit]<<8)|B0
CANDIDATES = [
    (0x483,      ('raw',  0),        '0x483 B0 raw  [previously graphed; user thinks not correct]', 'gray'),
    (0x484,      ('9bit', 0, 1, 0),  '0x484 9-bit (B1[bit0]<<8|B0)  [carry confirmed; inverter temp?]', 'darkgreen'),
    (0x594,      ('raw',  4),        '0x594 B4  [r=0.895 vs DCDC in PE overheat test]', 'steelblue'),
    (0x595,      ('raw',  2),        '0x595 B2  [PE glycol loop candidate, 1 Hz]', 'orange'),
    (0x390,      ('raw',  2),        '0x390 B2  [r=0.352 vs 0x483 B0 in gen test]', 'purple'),
    (0x625,      ('raw',  2),        '0x625 B2  [r=-0.480 vs 0x483 B0 in gen test]', 'red'),
    (0x0870A047, ('raw',  3),        '0x0870A047 B3  [r=0.964 but flat/monotone in gen test]', 'brown'),
]

# Collect data
obd_t, obd_v = [], []
data = {tid: {'t': [], 'v': []} for tid, _, _, _ in CANDIDATES}

for frame in parse_file(LOG):
    t = frame.timestamp
    aid = frame.arbitration_id
    d = frame.data
    if aid == 0x0C9:
        rpm = ((d[1] << 8) | d[2]) * 0.25
        if rpm > 1500:
            obd_t.append(t); obd_v.append(rpm)
    for tid, spec, _, _ in CANDIDATES:
        if aid == tid:
            if spec[0] == 'raw':
            	_, bi = spec[1], spec[2] if len(spec) > 2 else None
            	bi = spec[1]
            	data[tid]['t'].append(t)
            	data[tid]['v'].append(d[bi])
            elif spec[0] == '9bit':
            	_, b0i, b1i, carry_bit = spec
            	data[tid]['t'].append(t)
            	data[tid]['v'].append(((d[b1i] >> carry_bit) & 1) << 8 | d[b0i])

n_panels = 1 + len(CANDIDATES)
fig, axes = plt.subplots(n_panels, 1, figsize=(16, 2.5 * n_panels), sharex=True)
fig.subplots_adjust(hspace=0.35)

# OBD RPM panel
ax0 = axes[0]
ax0.plot(obd_t, obd_v, color='steelblue', linewidth=0.7, label='OBD Engine_Speed')
ax0.set_ylabel('RPM')
ax0.set_title('OBD Engine RPM (ground truth)')
ax0.legend(loc='upper left', fontsize=7)
ax0.grid(True, alpha=0.3)

for ax, (tid, spec, label, color) in zip(axes[1:], CANDIDATES):
    t_arr = data[tid]['t']
    v_arr = data[tid]['v']
    if t_arr:
        ax.plot(t_arr, v_arr, color=color, linewidth=0.7)
    else:
        ax.text(0.5, 0.5, 'no data', transform=ax.transAxes, ha='center')
    ax.set_title(label, fontsize=8, loc='left', pad=2)
    ax.grid(True, alpha=0.3)

for ax in axes:
    for kt, klabel in KEY_TIMES:
        ax.axvline(kt, color='red', linestyle='--', linewidth=0.7, alpha=0.5)

axes[-1].set_xlabel('Log time (s)')
fig.suptitle('Generator overheat test -- thermal candidates\nvtruxgeneratoroverheattest.log  |  red dashed = RPM peak/overflow events',
             fontsize=10)

plt.savefig(OUT, dpi=130, bbox_inches='tight')
print(f'Saved: {OUT}')
