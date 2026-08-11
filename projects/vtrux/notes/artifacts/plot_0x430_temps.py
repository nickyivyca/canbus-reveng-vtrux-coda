"""
plot_0x430_temps.py -- Plot 0x430 B4 (T_max) and B5 (T_min) temperatures
alongside battery current over t=250-750s of vtruxcurrentlimitingtest.log.

Window covers both the regen-limiting (t=401-503s) and discharge-limiting
(t=598-700s) events to show thermal response to I^2R loading.
"""
import sys
sys.path.insert(0, '.')
from canre.parsers import parse_file
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LOG = 'projects/vtrux/logs/vtruxcurrentlimitingtest.log'
OUT = 'projects/vtrux/notes/artifacts/plot_0x430_temps.png'

T0, T1 = 250.0, 750.0

CURRENT_SCALE  = 0.04124
CURRENT_CENTRE = 32768

print('Loading log...', flush=True)
frames = list(parse_file(LOG))
print(f'  {len(frames):,} frames')

bus_ids = {}
for f in frames:
    bus_ids.setdefault(f.bus, set()).add(f.arbitration_id)
pt_bus = next(b for b, ids in bus_ids.items() if 0x051 in ids)

temp_t, tmax_v, tmin_v = [], [], []
curr_t, curr_v = [], []

for f in frames:
    t = f.timestamp
    if not (T0 <= t <= T1):
        continue
    if f.bus == pt_bus and f.arbitration_id == 0x430 and len(f.data) >= 6:
        b4, b5 = f.data[4], f.data[5]
        if b4 != 0xFE and b5 != 0xFE:
            temp_t.append(t)
            tmax_v.append(b4 - 100)
            tmin_v.append(b5 - 100)
    if f.bus == pt_bus and f.arbitration_id == 0x598 and len(f.data) >= 2:
        raw = f.data[0] + f.data[1] * 256
        curr_t.append(t)
        curr_v.append((raw - CURRENT_CENTRE) * CURRENT_SCALE)

print(f'  Temperature samples: {len(temp_t)}')
print(f'  Current samples: {len(curr_t)}')

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
fig.suptitle('0x430 B4/B5 Cell Temperatures (T_max, T_min) and Battery Current\n'
             'vtruxcurrentlimitingtest.log -- t=250-750s',
             fontsize=12)

# Shade the two event windows
for ax in (ax1, ax2):
    ax.axvspan(401, 503, alpha=0.10, color='dodgerblue',  label='Regen window')
    ax.axvspan(598, 700, alpha=0.10, color='orangered', label='Discharge window')

# Temperature panel
ax1.fill_between(temp_t, tmax_v, tmin_v, alpha=0.20, color='salmon', label='T_max - T_min spread')
ax1.plot(temp_t, tmax_v, color='firebrick', linewidth=1.0, label='T_max (B4)')
ax1.plot(temp_t, tmin_v, color='steelblue', linewidth=1.0, label='T_min (B5)')
ax1.set_ylabel('Cell temperature (degC)\nraw - 100, provisional', fontsize=9)
ax1.legend(fontsize=8, loc='upper left')
ax1.grid(True, linewidth=0.4, alpha=0.5)
ax1.tick_params(labelsize=8)
ax1.margins(y=0.1)

# Current panel
ax2.plot(curr_t, curr_v, color='darkgreen', linewidth=0.8, label='Battery current (A)')
ax2.axhline(0, color='black', linewidth=0.4, linestyle='--')
ax2.set_ylabel('Battery current (A)\n+ = discharge', fontsize=9)
ax2.set_xlabel('Time (s)', fontsize=9)
ax2.legend(fontsize=8, loc='upper left')
ax2.grid(True, linewidth=0.4, alpha=0.5)
ax2.tick_params(labelsize=8)
ax2.margins(y=0.05)

plt.tight_layout()
plt.savefig(OUT, dpi=150, bbox_inches='tight')
print(f'Saved: {OUT}')
