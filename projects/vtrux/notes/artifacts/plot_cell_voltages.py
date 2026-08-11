"""
Plot vmin / vmax / vavg cell voltages for the "full charge then fail" session.

Sources:
  0x430 B0-B1  : V_max cell (12-bit masked LE uint16, 1 mV/cnt)
  0x430 B2-B3  : V_min cell (12-bit masked LE uint16, 1 mV/cnt)
  0x18FFD6B3 B4-B5 : DCDC HV input (LE signed int16, x0.05 V) / 117 cells = V_avg
"""

import sys
import struct
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

REPO = r'<home>\<drive-root>\<library>\My Libraries\Projects\reverse-it'
sys.path.insert(0, REPO)
from canre.parsers import parse_file

LOG = os.path.join(REPO, 'projects', 'vtrux', 'logs', 'full charge then fail.log')
OUT = os.path.join(REPO, 'projects', 'vtrux', 'notes', 'artifacts', 'cell_voltages_full_charge_fail.png')

t_vmax, v_vmax = [], []
t_vmin, v_vmin = [], []
t_vavg, v_vavg = [], []

print("Parsing log (16M frames, this will take a minute)...")
n = 0
for frame in parse_file(LOG):
    aid = frame.arbitration_id
    d = frame.data
    t = frame.timestamp
    n += 1
    if n % 2_000_000 == 0:
        print(f"  {n//1_000_000}M frames processed, t={t:.0f}s")

    if aid == 0x430 and len(d) >= 4:
        # Motorola 12-bit: lower nibble of B0 = upper 4 bits, B1 = lower 8 bits
        # Upper nibble of B0/B2 is segment tag, not voltage
        vmax_mv = ((d[0] & 0x0F) << 8) | d[1]
        vmin_mv = ((d[2] & 0x0F) << 8) | d[3]
        if 2500 < vmax_mv < 4300 and 2500 < vmin_mv < 4300:  # valid LFP range, exclude 0xFE sentinel
            t_vmax.append(t)
            v_vmax.append(vmax_mv / 1000.0)
            t_vmin.append(t)
            v_vmin.append(vmin_mv / 1000.0)

    elif aid == 0x18FFD6B3 and len(d) >= 6:
        raw = struct.unpack_from('<h', bytes(d[4:6]))[0]
        hv_v = raw * 0.05
        if 300.0 < hv_v < 500.0:              # sanity: valid pack voltage range
            t_vavg.append(t)
            v_vavg.append(hv_v / 117.0)

print(f"Done. vmax:{len(t_vmax)} vmin:{len(t_vmin)} vavg:{len(t_vavg)} points")

if not t_vmax:
    print("ERROR: no 0x430 frames found -- check bus ID / log path")
    sys.exit(1)

# ---- Plot ----
fig, ax = plt.subplots(figsize=(16, 6))

ax.plot(t_vmax, v_vmax, color='red',   lw=0.6, alpha=0.85, label='V_max cell (0x430 B0-B1)')
ax.plot(t_vmin, v_vmin, color='blue',  lw=0.6, alpha=0.85, label='V_min cell (0x430 B2-B3)')
ax.plot(t_vavg, v_vavg, color='green', lw=0.6, alpha=0.85, label='V_avg = HV/117 (0x18FFD6B3 B4-B5)')

ax.set_xlabel('Time (s)')
ax.set_ylabel('Cell Voltage (V)')
ax.set_title('Vtrux -- Cell Voltages During Full Charge Then Fail\n(vmin/vmax from BMS 0x430; vavg from DCDC HV input / 117 cells)')
ax.legend(loc='upper left')
ax.grid(True, alpha=0.3)

# Mark the failure at ~7243s
ax.axvline(x=7243, color='black', lw=1.5, linestyle='--', label='Failure (t=7243s)')
ax.legend(loc='upper left')

plt.tight_layout()
plt.savefig(OUT, dpi=150)
print(f"Saved: {OUT}")
