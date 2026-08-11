"""
Graph showing 0x308 counter vs motor RPM to illustrate that the counter
tracks motor torque direction (up=motoring, down=regen), not shaft rotation.
"""
import sys
sys.path.insert(0, '.')
from canre.parsers.autodetect import parse_file
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

ID_308 = 0x308
ID_5A2 = 0x5A2

frames_308 = []
frames_rpm = []
for f in parse_file('projects/vtrux/logs/vtruxevapdrivelog4.log'):
    if f.arbitration_id == ID_308:
        frames_308.append(f)
    elif f.arbitration_id == ID_5A2:
        frames_rpm.append(f)

t0 = frames_308[0].timestamp

ts_ctr = [(f.timestamp - t0, (f.data[2] << 8) | f.data[1]) for f in frames_308 if f.data[0] == 0x40]
ts_rpm = [(f.timestamp - t0, ((f.data[3] << 8) | f.data[2]) - 32768) for f in frames_rpm]

# Clip to first 310 seconds (covers full accel + cruise + decel back to stop)
ts_ctr = [(t, c) for t, c in ts_ctr if t <= 310]
ts_rpm = [(t, r) for t, r in ts_rpm if t <= 310]

t_ctr, v_ctr = zip(*ts_ctr)
t_rpm, v_rpm = zip(*ts_rpm)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
fig.suptitle('0x308 B1-B2 Counter vs Motor RPM -- Vtrux evap drive log\n'
             'Counter goes UP during motoring, DOWN during regen -- even though RPM stays positive throughout',
             fontsize=11)

ax1.plot(t_rpm, v_rpm, color='steelblue', linewidth=0.8, label='Motor RPM (0x5A2)')
ax1.set_ylabel('Motor RPM')
ax1.axhline(0, color='gray', linestyle='--', linewidth=0.5)
ax1.legend(loc='upper right', fontsize=9)
ax1.set_ylim(-500, 7000)
# Shade regen periods (RPM > 500 but counter trending down) -- approximate
ax1.annotate('RPM always\npositive here', xy=(250, 4000), fontsize=8, color='steelblue')

ax2.plot(t_ctr, v_ctr, color='darkorange', linewidth=0.8, label='Counter (0x308 B1-B2)')
ax2.axhline(32128, color='gray', linestyle='--', linewidth=0.8, label='Baseline (32128 = park reset)')
ax2.set_ylabel('Counter value (16-bit LE)')
ax2.set_xlabel('Time (s)')
ax2.legend(loc='upper right', fontsize=9)

# Annotate key phases
ax2.annotate('', xy=(44, 38500), xytext=(44, 32200),
             arrowprops=dict(arrowstyle='->', color='green', lw=1.5))
ax2.text(45, 35000, 'Accel\n(motoring)', fontsize=8, color='green')

ax2.annotate('', xy=(216, 40000), xytext=(216, 44500),
             arrowprops=dict(arrowstyle='->', color='red', lw=1.5))
ax2.text(218, 42000, 'Decel\n(regen)', fontsize=8, color='red')

ax2.annotate('back to\nbaseline', xy=(290, 32146), fontsize=8, color='gray',
             xytext=(255, 33800),
             arrowprops=dict(arrowstyle='->', color='gray', lw=1.2))

plt.tight_layout()
plt.savefig('projects/vtrux/notes/artifacts/borgwarner_shaft_counter_vs_rpm.png', dpi=150)
print('Saved: projects/vtrux/notes/artifacts/borgwarner_shaft_counter_vs_rpm.png')
plt.show()
