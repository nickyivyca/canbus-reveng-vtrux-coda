"""
Plot MSB and LSB of 0x63C B5 and B7 vs B6 raw and OBD RPM.
Overflow windows:
  W1: t=1858.1 (brief)
  W2: t=1921.4 - 1922.8 (short)
  W3: t=1923.3 - 1935.5 (long)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

from canre.parsers import parse_file

LOG = r'projects/vtrux/logs/vtruxgeneratoroverheattest.log'
T0, T1 = 1700, 2000

b6_t, b6_v = [], []
b7_lsb_t, b7_lsb_v = [], []
b5_lsb_t, b5_lsb_v = [], []
obd_t, obd_v = [], []

for frame in parse_file(LOG):
    t = frame.timestamp
    if t < T0: continue
    if t > T1: break
    aid = frame.arbitration_id
    d = frame.data
    if aid == 0x63C:
        b6_t.append(t); b6_v.append(d[6])
        b7_lsb_t.append(t); b7_lsb_v.append(d[7] & 1)
        b5_lsb_t.append(t); b5_lsb_v.append(d[5] & 1)
    elif aid == 0x0C9:
        rpm = ((d[1] << 8) | d[2]) * 0.25
        if rpm > 1500:
            obd_t.append(t); obd_v.append(rpm)

fig = plt.figure(figsize=(14, 9))
gs = gridspec.GridSpec(3, 1, hspace=0.4)

ax1 = fig.add_subplot(gs[0])
ax2 = fig.add_subplot(gs[1], sharex=ax1)
ax3 = fig.add_subplot(gs[2], sharex=ax1)

# Mark overflow windows
ovf_spans = [(1858.10, 1858.35), (1921.40, 1922.76), (1923.32, 1935.50)]
for ax in [ax1, ax2, ax3]:
    for i, (ta, tb) in enumerate(ovf_spans):
        ax.axvspan(ta, tb, color='red', alpha=0.15, label=f'OVF W{i+1}' if i == 0 else None)

ax1.plot(obd_t, obd_v, color='steelblue', linewidth=0.8, label='OBD RPM')
ax1.set_ylabel('RPM'); ax1.set_title('OBD RPM (ground truth)')
ax1.legend(loc='upper left', fontsize=7); ax1.grid(True, alpha=0.3)

ax2.plot(b6_t, b6_v, color='darkorange', linewidth=0.6, label='B6 raw')
ax2.axhline(255, color='gray', linewidth=0.5, linestyle=':')
ax2.set_ylabel('B6 raw'); ax2.set_title('0x63C B6 raw')
ax2.legend(loc='upper left', fontsize=7); ax2.grid(True, alpha=0.3)

ax3.step(b7_lsb_t, b7_lsb_v, color='purple', linewidth=0.8, label='B7 LSB (bit0)', where='post')
ax3.step(b5_lsb_t, [v + 2 for v in b5_lsb_v], color='green', linewidth=0.8,
         linestyle='--', label='B5 LSB (bit0, offset+2)', where='post')
ax3.set_yticks([0, 1, 2, 3]); ax3.set_yticklabels(['0', '1', '0', '1'])
ax3.set_ylabel('bit value'); ax3.set_title('0x63C B7 LSB and B5 LSB')
ax3.legend(loc='upper left', fontsize=7); ax3.grid(True, alpha=0.3)
ax3.set_xlabel('Log time (s)')

plt.suptitle('0x63C B7/B5 LSB vs B6 raw and OBD RPM\nRed shading = overflow windows W1/W2/W3', fontsize=10)

out = r'projects/vtrux/notes/artifacts/63c_bits_ovf.png'
plt.savefig(out, dpi=150, bbox_inches='tight')
print(f'Saved: {out}')
