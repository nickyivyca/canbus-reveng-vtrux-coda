"""
plot_0x430_b1b3.py -- Plot 0x430 B0-B1 BE and B2-B3 BE vs DCDC HV voltage and battery current
across Windows A (t=401-503s, regen) and B (t=598-700s, discharge).

Layout: 4 rows x 2 columns (one column per window).
  Row 1: DCDC HV voltage (0x18FFD6B3 B4-B5 LE x0.05)
  Row 2: Battery current (0x598 B0-B1 LE, centred at 32768, scale 0.04124 A/cnt; + = discharge)
  Row 3: 0x430 B0-B1 BE (B0 as MSB, B1 as LSB)
  Row 4: 0x430 B2-B3 BE (B2 as MSB, B3 as LSB)
"""
import sys
sys.path.insert(0, '.')
from canre.parsers import parse_file
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LOG = 'projects/vtrux/logs/vtruxcurrentlimitingtest.log'
OUT = 'projects/vtrux/notes/artifacts/plot_0x430_12bit.png'

WINDOWS = {
    'A  regen (t=401-503s)':     (395.0, 510.0),
    'B  discharge (t=598-700s)': (592.0, 707.0),
}
CONTEXT = 6.0   # seconds of extra context outside each window boundary

CURRENT_SCALE  = 0.04124   # A per count (calibrated from signal_scaling.py)
CURRENT_CENTRE = 32768     # raw zero-current value

print('Loading log...', flush=True)
frames = list(parse_file(LOG))
print(f'  {len(frames):,} frames')

bus_ids = {}
for f in frames:
    bus_ids.setdefault(f.bus, set()).add(f.arbitration_id)
pt_bus = next(b for b, ids in bus_ids.items() if 0x051 in ids)
print(f'  PT bus = {pt_bus}')

# ---- extract signals --------------------------------------------------------
dcdc_t, dcdc_v   = [], []
curr_t, curr_v   = [], []
b01_t,  b01_v    = [], []   # B0-B1 BE
b23_t,  b23_v    = [], []   # B2-B3 BE

for f in frames:
    t = f.timestamp
    if f.arbitration_id == 0x18FFD6B3 and len(f.data) >= 6:
        dcdc_t.append(t)
        dcdc_v.append((f.data[4] + f.data[5] * 256) * 0.05)
    if f.bus == pt_bus and f.arbitration_id == 0x598 and len(f.data) >= 2:
        raw = f.data[0] + f.data[1] * 256
        curr_t.append(t)
        curr_v.append((raw - CURRENT_CENTRE) * CURRENT_SCALE)
    if f.bus == pt_bus and f.arbitration_id == 0x430 and len(f.data) >= 4:
        b01_t.append(t)
        b01_v.append((f.data[0] & 0x0F) * 256 + f.data[1])   # 12-bit: B0 lower nibble + B1
        b23_t.append(t)
        b23_v.append((f.data[2] & 0x0F) * 256 + f.data[3])   # 12-bit: B2 lower nibble + B3

print(f'  DCDC: {len(dcdc_t)} samples')
print(f'  Current: {len(curr_t)} samples')
print(f'  0x430 pairs: {len(b01_t)} samples')

# ---- plot -------------------------------------------------------------------
win_labels = list(WINDOWS.keys())
win_ranges = list(WINDOWS.values())
n_wins = len(WINDOWS)

fig, axes = plt.subplots(2, n_wins, figsize=(14, 7))
fig.suptitle('0x430 12-bit masked fields vs DCDC Voltage and Battery Current\n'
             'climit log -- Windows A (regen) and B (discharge)',
             fontsize=12)

# Convert DCDC to per-cell mV
dcdc_cell_v = [v * 1000.0 / 117.0 for v in dcdc_v]

voltage_signals = [
    (dcdc_t,  dcdc_cell_v, 'steelblue',  'DCDC/117 (mV/cell)'),
    (b01_t,   b01_v,       'darkorange', '0x430 (B0&0xF)<<8|B1'),
    (b23_t,   b23_v,       'darkgreen',  '0x430 (B2&0xF)<<8|B3'),
]

for col, (label, (t0, t1)) in enumerate(WINDOWS.items()):
    lo = t0 - CONTEXT
    hi = t1 + CONTEXT

    # Row 0: all three voltage signals overlaid
    ax = axes[0][col]
    for ts, vs, color, lbl in voltage_signals:
        seg = [(t, v) for t, v in zip(ts, vs) if lo <= t <= hi]
        if seg:
            st, sv = zip(*seg)
            ax.plot(st, sv, color=color, linewidth=0.9, label=lbl, alpha=0.85)
    ax.axvspan(t0, t1, alpha=0.10, color='gold')
    ax.set_xlim(lo, hi)
    ax.margins(y=0.05)
    ax.autoscale(enable=True, axis='y', tight=False)
    if col == 0:
        ax.set_ylabel('Cell voltage (mV)', fontsize=8)
        ax.legend(fontsize=7, loc='upper left')
    ax.set_title(label, fontsize=9)
    ax.tick_params(labelsize=7)
    ax.grid(True, linewidth=0.4, alpha=0.5)

    # Row 1: battery current
    ax = axes[1][col]
    seg = [(t, v) for t, v in zip(curr_t, curr_v) if lo <= t <= hi]
    if seg:
        st, sv = zip(*seg)
        ax.plot(st, sv, color='firebrick', linewidth=0.9)
    ax.axvspan(t0, t1, alpha=0.10, color='gold')
    ax.axhline(0, color='black', linewidth=0.4, linestyle='--')
    ax.set_xlim(lo, hi)
    ax.margins(y=0.05)
    ax.autoscale(enable=True, axis='y', tight=False)
    if col == 0:
        ax.set_ylabel('Battery current (A)\n+= discharge', fontsize=8)
    ax.set_xlabel('Time (s)', fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, linewidth=0.4, alpha=0.5)

plt.tight_layout()
plt.savefig(OUT, dpi=150, bbox_inches='tight')
print(f'Saved: {OUT}')
