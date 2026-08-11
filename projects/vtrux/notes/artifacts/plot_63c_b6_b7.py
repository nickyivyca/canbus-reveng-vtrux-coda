"""
Plot 0x63C B6 and B7 alongside OBD RPM (t=1700-2000s).
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
b7_t, b7_v = [], []
obd_t, obd_v = [], []

for frame in parse_file(LOG):
    t = frame.timestamp
    if t < T0: continue
    if t > T1: break
    aid = frame.arbitration_id
    d = frame.data
    if aid == 0x63C:
        b6_t.append(t); b6_v.append(d[6])
        b7_t.append(t); b7_v.append(d[7])
    elif aid == 0x0C9:
        rpm = ((d[1] << 8) | d[2]) * 0.25
        if rpm > 1500:
            obd_t.append(t); obd_v.append(rpm)

b6_t = np.array(b6_t); b6_v = np.array(b6_v)
b7_t = np.array(b7_t); b7_v = np.array(b7_v)
obd_t = np.array(obd_t); obd_v = np.array(obd_v)

fig = plt.figure(figsize=(14, 8))
gs = gridspec.GridSpec(3, 1, hspace=0.35)

ax1 = fig.add_subplot(gs[0])
ax2 = fig.add_subplot(gs[1], sharex=ax1)
ax3 = fig.add_subplot(gs[2], sharex=ax1)

for ax in [ax1, ax2, ax3]:
    ax.axvline(1858.1, color='red', linestyle='--', alpha=0.4, linewidth=0.8, label='wrap1 t=1858')
    ax.axvline(1921.4, color='orange', linestyle='--', alpha=0.4, linewidth=0.8, label='wrap2 t=1921')
    ax.axvline(1935.5, color='green', linestyle='--', alpha=0.4, linewidth=0.8, label='unwrap t=1935')

ax1.plot(obd_t, obd_v, color='steelblue', linewidth=0.8, label='OBD RPM (0x0C9, Bus1)')
ax1.set_ylabel('RPM')
ax1.set_title('OBD Engine RPM (ground truth)')
ax1.legend(loc='upper left', fontsize=7)
ax1.grid(True, alpha=0.3)

ax2.plot(b6_t, b6_v, color='darkorange', linewidth=0.6, label='0x63C B6 raw (RPM = 16*B6 - 96)')
ax2.axhline(255, color='gray', linewidth=0.5, linestyle=':')
ax2.set_ylabel('B6 raw')
ax2.set_title('0x63C B6 (wraps at 255)')
ax2.legend(loc='upper left', fontsize=7)
ax2.grid(True, alpha=0.3)

ax3.plot(b7_t, b7_v, color='purple', linewidth=0.6, label='0x63C B7 raw')
ax3.set_ylabel('B7 raw')
ax3.set_title('0x63C B7')
ax3.legend(loc='upper left', fontsize=7)
ax3.grid(True, alpha=0.3)
ax3.set_xlabel('Log time (s)')

plt.suptitle('0x63C B6 / B7 vs OBD RPM  (t=1700-2000s)\nRed/orange dashed = wrap events', fontsize=10)

out = r'projects/vtrux/notes/artifacts/63c_b6_b7_vs_obd.png'
plt.savefig(out, dpi=150, bbox_inches='tight')
print(f'Saved: {out}')
