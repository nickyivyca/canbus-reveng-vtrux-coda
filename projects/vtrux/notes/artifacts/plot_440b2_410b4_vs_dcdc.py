"""
Plot 0x440 B2 and 0x410 B4 against DCDC HV reference.
Left axis: DCDC voltage (V). Right axis: raw byte value.
"""
import sys, os, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG = r'<home>\<drive-root>\<library>\My Libraries\Projects\reverse-it\projects\vtrux\logs\vtruxcurrentlimitingtest.log'
OUT = os.path.join(os.path.dirname(__file__), 'plot_440b2_410b4_vs_dcdc_climit.png')

dcdc, ts_440b2, ts_410b4, ts_598batt = [], [], [], []

for frame in parse_file(LOG):
    fid = frame.arbitration_id
    d = frame.data
    t = frame.timestamp
    if fid == 0x18FFD6B3 and len(d) >= 6:
        v = struct.unpack_from('<h', d, 4)[0] * 0.05
        if v > 300:  # clip to operating range; key-off HV drop excluded (scale/role TBD)
            dcdc.append((t, v))
    elif fid == 0x440 and len(d) >= 3:
        ts_440b2.append((t, d[2]))
    elif fid == 0x410 and len(d) >= 5:
        ts_410b4.append((t, d[4]))
    elif fid == 0x598 and len(d) >= 2:
        raw = struct.unpack_from('<H', d, 0)[0]
        ts_598batt.append((t, raw - 32768))

print(f"DCDC: {len(dcdc)}  0x440 B2: {len(ts_440b2)}  0x410 B4: {len(ts_410b4)}  0x598 batt: {len(ts_598batt)}")

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

t, v = zip(*dcdc)
ax1.plot(t, v, color='black', lw=1.2)
ax1.set_ylabel('DCDC HV (V)')
ax1.set_title('0x440 B2 / 0x410 B4 vs DCDC HV -- vtruxevapdrivelog4part2.log')
ax1.grid(True, alpha=0.3)

t, r = zip(*ts_440b2)
ax2.plot(t, r, color='tab:blue', lw=0.8, alpha=0.9, label='0x440 B2 (raw byte)')
t, r = zip(*ts_410b4)
ax2.plot(t, r, color='tab:orange', lw=0.8, alpha=0.7, label='0x410 B4 (raw byte)')
ax2.set_ylabel('Raw byte (0-255)')
ax2.legend(loc='upper right', fontsize=8)
ax2.grid(True, alpha=0.3)

if ts_598batt:
    t, r = zip(*ts_598batt)
    ax3.plot(t, r, color='tab:green', lw=0.8, label='0x598 B0-B1 batt current (raw-32768)')
    ax3.axhline(0, color='gray', lw=0.5, ls='--')
    ax3.set_ylabel('Batt current (counts, 0=neutral)')
    ax3.legend(loc='upper right', fontsize=8)
    ax3.grid(True, alpha=0.3)

ax3.set_xlabel('Time (s)')
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"Saved: {OUT}")
