"""
Plot generator overheat test signals.
Panels: generator RPM, torque cmd, gen power (direct + computed), drivetrain motor temp, 0x483 B0 candidate.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

from canre.parsers import parse_file

LOG = r'projects/vtrux/logs/vtruxgeneratoroverheattest.log'

# --- collect ---
rpm_t, rpm_v = [], []
torq_t, torq_v = [], []
gen_cur_t, gen_cur_v = [], []
drvtemp_t, drvtemp_v = [], []
b483_t, b483_v = [], []

print('Parsing log...')
for frame in parse_file(LOG):
    t = frame.timestamp
    aid = frame.arbitration_id
    d = frame.data

    if aid == 0x63C:
        b6 = d[6]
        rpm = 16 * b6 - 96
        rpm_t.append(t)
        rpm_v.append(max(rpm, 0))  # floor at 0 for plotting

    elif aid == 0x051:
        raw = (d[2] << 8) | d[1]  # LE B1-B2
        torq_t.append(t)
        torq_v.append(raw - 32768)

    elif aid == 0x598:
        raw = (d[3] << 8) | d[2]  # LE B2-B3
        gen_cur_t.append(t)
        gen_cur_v.append(raw - 32768)

    elif aid == 0x06000002:
        b5 = d[5]
        b6 = d[6]
        raw10 = (b6 << 2) | (b5 >> 6)
        drvtemp_t.append(t)
        drvtemp_v.append(raw10 * 2.0)

    elif aid == 0x483:
        b483_t.append(t)
        b483_v.append(d[0])

print(f'  RPM: {len(rpm_t)} frames')
print(f'  Torque cmd: {len(torq_t)} frames')
print(f'  Gen current: {len(gen_cur_t)} frames')
print(f'  Drivetrain temp: {len(drvtemp_t)} frames')
print(f'  0x483 B0: {len(b483_t)} frames')

# convert to numpy
rpm_t = np.array(rpm_t); rpm_v = np.array(rpm_v)
torq_t = np.array(torq_t); torq_v = np.array(torq_v)
gen_cur_t = np.array(gen_cur_t); gen_cur_v = np.array(gen_cur_v)
drvtemp_t = np.array(drvtemp_t); drvtemp_v = np.array(drvtemp_v)
b483_t = np.array(b483_t); b483_v = np.array(b483_v)

# --- compute RPM x torque (power proxy) ---
# interpolate torque onto RPM timestamps
torq_interp = np.interp(rpm_t, torq_t, torq_v)
# power_computed: only where generating (torque < 0 = generating convention, or RPM > 0)
power_comp = rpm_v * (-torq_interp)  # negate torque: positive = generating power

# scale power_comp to match gen_cur (in normal generating region, t=200-1800s, gen active)
mask = (rpm_t > 200) & (rpm_t < 1700) & (rpm_v > 200) & (torq_interp < -100)
if mask.sum() > 100:
    gen_cur_at_rpm = np.interp(rpm_t[mask], gen_cur_t, gen_cur_v)
    # scale: power_comp ~ k * gen_cur
    # use median ratio (robust to outliers)
    ratios = gen_cur_at_rpm / np.where(power_comp[mask] != 0, power_comp[mask], np.nan)
    k = float(np.nanmedian(ratios))
    print(f'  Power scaling factor k={k:.6f}')
    power_comp_scaled = power_comp * k
else:
    print('  Warning: not enough generating frames for scaling, using raw ratio')
    power_comp_scaled = power_comp * 1.0

# --- plot ---
fig = plt.figure(figsize=(16, 14))
gs = gridspec.GridSpec(5, 1, hspace=0.35)

ax1 = fig.add_subplot(gs[0])
ax2 = fig.add_subplot(gs[1], sharex=ax1)
ax3 = fig.add_subplot(gs[2], sharex=ax1)
ax4 = fig.add_subplot(gs[3], sharex=ax1)
ax5 = fig.add_subplot(gs[4], sharex=ax1)

# mark overheat peak
peak_t = 1857.9

for ax in [ax1, ax2, ax3, ax4, ax5]:
    ax.axvline(peak_t, color='red', linestyle='--', alpha=0.5, linewidth=1.0, label='RPM peak ~10:57 PM')

# Panel 1: Generator RPM
ax1.plot(rpm_t, rpm_v, color='steelblue', linewidth=0.6, label='Gen RPM (0x63C B6)')
ax1.set_ylabel('RPM')
ax1.set_title('Generator RPM')
ax1.legend(loc='upper left', fontsize=8)
ax1.grid(True, alpha=0.3)

# Panel 2: Generator torque command
ax2.plot(torq_t, torq_v, color='darkorange', linewidth=0.6, label='Gen torque cmd (0x051 B1-B2, centered)')
ax2.axhline(0, color='black', linewidth=0.5)
ax2.set_ylabel('Raw - 32768')
ax2.set_title('Generator Torque Command (negative = generating)')
ax2.legend(loc='upper left', fontsize=8)
ax2.grid(True, alpha=0.3)

# Panel 3: Generator power
ax3.plot(gen_cur_t, gen_cur_v, color='green', linewidth=0.6, alpha=0.8, label='Gen power - direct (0x598 B2-B3 current)')
ax3.plot(rpm_t, power_comp_scaled, color='lime', linewidth=0.5, alpha=0.6, label='Gen power - RPM x torque (scaled)')
ax3.axhline(0, color='black', linewidth=0.5)
ax3.set_ylabel('Raw units')
ax3.set_title('Generator Power: Direct vs RPM x Torque')
ax3.legend(loc='upper left', fontsize=8)
ax3.grid(True, alpha=0.3)

# Panel 4: Drivetrain motor temperature
ax4.plot(drvtemp_t, drvtemp_v, color='purple', linewidth=0.8, label='Drivetrain motor temp (0x06000002, 2 deg C/count)')
ax4.set_ylabel('deg C')
ax4.set_title('Drivetrain Motor Winding Temperature')
ax4.legend(loc='upper left', fontsize=8)
ax4.grid(True, alpha=0.3)

# Panel 5: 0x483 B0 candidate
ax5_raw = ax5
ax5_40 = ax5.twinx()
ax5_raw.plot(b483_t, b483_v, color='red', linewidth=1.0, label='0x483 B0 raw')
ax5_40.plot(b483_t, np.array(b483_v) - 40, color='red', linewidth=1.0, linestyle='--', alpha=0.4, label='B0 raw-40 (degC?)')
ax5_raw.set_ylabel('Raw value')
ax5_40.set_ylabel('raw-40 (possible degC)', color='red')
ax5_raw.set_title('0x483 B0 (temperature candidate)')
lines1, labels1 = ax5_raw.get_legend_handles_labels()
lines2, labels2 = ax5_40.get_legend_handles_labels()
ax5_raw.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=8)
ax5_raw.grid(True, alpha=0.3)

ax5.set_xlabel('Log time (s)')

plt.suptitle('Generator Overheat Test — vtruxgeneratoroverheattest.log\nLog start: 22:25:12, RPM peak (red dashed) ~t=1858s (~22:56)', fontsize=11)

out = r'projects/vtrux/notes/artifacts/gen_overheat_overview.png'
plt.savefig(out, dpi=150, bbox_inches='tight')
print(f'Saved: {out}')
