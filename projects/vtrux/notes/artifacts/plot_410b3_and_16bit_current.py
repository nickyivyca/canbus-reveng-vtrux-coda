"""
4-panel plot on vtruxcurrentlimitingtest.log:
  Panel 1: DCDC HV voltage (reference)
  Panel 2: 0x410 B3 raw (unknown analog)
  Panel 3: 0x440 B2-B3 BE and 0x410 B4-B5 BE (treating B3/B5 as LSBs)
  Panel 4: 0x598 B0-B1 battery current (reference)
"""
import sys, os, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG = r'<home>\<drive-root>\<library>\My Libraries\Projects\reverse-it\projects\vtrux\logs\vtruxcurrentlimitingtest.log'
OUT = os.path.join(os.path.dirname(__file__), 'plot_410b3_and_16bit_current.png')

dcdc, ts_410b3, ts_440_16, ts_410_16, ts_598 = [], [], [], [], []

for frame in parse_file(LOG):
    fid = frame.arbitration_id
    d = frame.data
    t = frame.timestamp
    if fid == 0x18FFD6B3 and len(d) >= 6:
        v = struct.unpack_from('<h', d, 4)[0] * 0.05
        if v > 300:
            dcdc.append((t, v))
    elif fid == 0x410 and len(d) >= 6:
        ts_410b3.append((t, d[3]))
        ts_410_16.append((t, struct.unpack_from('>H', d, 4)[0]))  # B4-B5 BE
    elif fid == 0x440 and len(d) >= 4:
        ts_440_16.append((t, struct.unpack_from('>H', d, 2)[0]))  # B2-B3 BE
    elif fid == 0x598 and len(d) >= 2:
        ts_598.append((t, struct.unpack_from('<H', d, 0)[0] - 32768))

print(f"DCDC: {len(dcdc)}  0x410 B3: {len(ts_410b3)}  "
      f"0x440 B2-B3 BE: {len(ts_440_16)}  0x410 B4-B5 BE: {len(ts_410_16)}  0x598: {len(ts_598)}")

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(4, 1, figsize=(14, 13), sharex=True)
ax1, ax2, ax3, ax4 = axes

t, v = zip(*dcdc)
ax1.plot(t, v, color='black', lw=1.0)
ax1.set_ylabel('DCDC HV (V)')
ax1.set_title('0x410 B3 and 16-bit combos vs current -- vtruxcurrentlimitingtest.log')
ax1.grid(True, alpha=0.3)

t, v = zip(*ts_410b3)
ax2.plot(t, v, color='tab:purple', lw=0.8)
ax2.set_ylabel('0x410 B3 (raw byte)')
ax2.grid(True, alpha=0.3)

if ts_440_16:
    t, v = zip(*ts_440_16)
    ax3.plot(t, v, color='tab:blue', lw=0.6, alpha=0.85, label='0x440 B2-B3 BE (B3 as LSB)')
if ts_410_16:
    t, v = zip(*ts_410_16)
    ax3.plot(t, v, color='tab:orange', lw=0.6, alpha=0.7, label='0x410 B4-B5 BE (B5 as LSB)')
ax3.set_ylabel('16-bit BE value')
ax3.legend(loc='upper right', fontsize=8)
ax3.grid(True, alpha=0.3)

if ts_598:
    t, v = zip(*ts_598)
    ax4.plot(t, v, color='tab:green', lw=0.8, label='0x598 B0-B1 batt current (raw-32768)')
    ax4.axhline(0, color='gray', lw=0.5, ls='--')
    ax4.set_ylabel('Batt current (counts)')
    ax4.legend(loc='upper right', fontsize=8)
    ax4.grid(True, alpha=0.3)

ax4.set_xlabel('Time (s)')
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"Saved: {OUT}")
