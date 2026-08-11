"""
plot_ccl_trigger_zoom.py

Zoomed plot of CCL trigger candidates:
  - 0x411 B0: multi-bit transition at t=344.4s (6s before CCL step 1) -- possible BMS trigger
  - 0x420 B1: staircase 4->2->0->2->4 during deep CCL dip
  - 0x420 B4: original BMS binary candidate (for comparison)
  - 0x411 B1: alongside B0 for context

Window: t=335-375s, inflection lines at t=344.4s, 350.8s, 357.8s, 362.0s
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG    = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                      '..', '..', 'logs',
                                      'vtruxcurrentlimitingtest.log'))
OUTPUT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                      'plot_ccl_trigger_zoom.png'))

T_PLOT_S = 335.0
T_PLOT_E = 375.0

# Known timing
T_PRECURSOR = 344.4   # 0x411 B0 multi-bit flip
T_STEP1     = 350.8   # CCL first drop (305->187)
T_STEP2     = 357.8   # CCL deep drop (187->42)
T_RECOV     = 362.0   # CCL recovery onset

print("Detecting PT bus ...")
bus_051 = {}
for frame in parse_file(LOG):
    if frame.arbitration_id == 0x051:
        bus_051[frame.bus] = bus_051.get(frame.bus, 0) + 1
    if sum(bus_051.values()) > 200:
        break
PT_BUS = max(bus_051, key=bus_051.get)
print(f"PT bus = {PT_BUS}")

print("Collecting signals ...")
ccl     = []   # (t, raw)
b411_b0 = []   # (t, val)
b411_b1 = []
b420_b1 = []
b420_b2 = []
b420_b4 = []
b410_b3 = []

for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    t   = frame.timestamp
    if not (T_PLOT_S - 5 <= t <= T_PLOT_E + 5):
        continue
    aid = frame.arbitration_id
    d   = frame.data

    if aid == 0x050 and len(d) >= 2:
        ccl.append((t, (d[1] & 0x03) << 8 | d[0]))
    elif aid == 0x411 and len(d) >= 2:
        b411_b0.append((t, d[0]))
        b411_b1.append((t, d[1]))
    elif aid == 0x420 and len(d) >= 5:
        b420_b1.append((t, d[1]))
        b420_b2.append((t, d[2]))
        b420_b4.append((t, d[4]))
    elif aid == 0x410 and len(d) >= 4:
        b410_b3.append((t, d[3]))

def filt(pairs):
    return [(t, v) for t, v in pairs if T_PLOT_S <= t <= T_PLOT_E]

def unzip(pairs):
    if not pairs: return [], []
    t, v = zip(*pairs)
    return list(t), list(v)

print(f"  ccl:{len(ccl)}  0x411B0:{len(b411_b0)}  0x420B1:{len(b420_b1)}  0x420B4:{len(b420_b4)}")

print("Plotting ...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(5, 1, figsize=(14, 18), sharex=True)

def vlines(ax):
    ax.axvline(T_PRECURSOR, color='gold',     lw=1.4, ls='--', alpha=0.9, label=f'0x411 B0 flip @{T_PRECURSOR}s')
    ax.axvline(T_STEP1,     color='orangered', lw=1.2, ls='--', alpha=0.7, label=f'CCL step1 @{T_STEP1}s')
    ax.axvline(T_STEP2,     color='red',       lw=1.2, ls='-',  alpha=0.7, label=f'CCL step2 @{T_STEP2}s')
    ax.axvline(T_RECOV,     color='steelblue', lw=1.0, ls=':',  alpha=0.6, label=f'CCL recov @{T_RECOV}s')

# Panel 1: CCL
ax = axes[0]
tc, vc = unzip(filt(ccl))
ax.plot(tc, vc, color='purple', lw=1.2)
vlines(ax)
ax.set_ylabel('CCL raw')
ax.set_title('0x050 CCL (raw) -- two-step dip t=350-363s')
ax.legend(loc='lower left', fontsize=7, ncol=2)

# Panel 2: 0x411 B0 (multi-bit state transition at t=344.4s)
ax = axes[1]
t0, v0 = unzip(filt(b411_b0))
t1, v1 = unzip(filt(b411_b1))
ax.step(t0, v0, where='post', color='goldenrod', lw=1.5, label='0x411 B0 (state byte: 95->97 at t=344.4s)')
ax.step(t1, v1, where='post', color='gray', lw=1.0, alpha=0.6, label='0x411 B1')
vlines(ax)
ax.set_ylabel('Byte value')
ax.set_title('0x411 B0 -- multi-bit flip at t=344.4s (6s before CCL step1, possible BMS trigger)')
ax.legend(loc='upper left', fontsize=8)

# Panel 3: 0x420 B1 (staircase 4->2->0->2->4)
ax = axes[2]
t1, v1b = unzip(filt(b420_b1))
t2, v2 = unzip(filt(b420_b2))
ax.step(t1, v1b, where='post', color='crimson', lw=1.5, label='0x420 B1 (4->2->0->2->4 staircase)')
ax2r = ax.twinx()
ax2r.step(t2, v2, where='post', color='saddlebrown', lw=1.0, alpha=0.6, label='0x420 B2 (right)')
ax2r.set_ylabel('0x420 B2', color='saddlebrown')
ax2r.tick_params(axis='y', labelcolor='saddlebrown')
vlines(ax)
ax.set_ylabel('0x420 B1 value')
ax.set_title('0x420 B1 -- staircase during CCL deep dip (steps DOWN with CCL, recovers)')
lines_a, labs_a = ax.get_legend_handles_labels()
lines_b, labs_b = ax2r.get_legend_handles_labels()
ax.legend(lines_a + lines_b, labs_a + labs_b, loc='upper left', fontsize=8)

# Panel 4: 0x420 B4 (original binary candidate, for comparison)
ax = axes[3]
t4, v4 = unzip(filt(b420_b4))
ax.step(t4, v4, where='post', color='steelblue', lw=1.2, label='0x420 B4 (original binary candidate: 190->0->94)')
vlines(ax)
ax.set_ylabel('0x420 B4 value')
ax.set_title('0x420 B4 -- original BMS binary candidate (for comparison)')
ax.legend(loc='upper left', fontsize=8)

# Panel 5: 0x410 B3 (bit2 flips at t=348.1s)
ax = axes[4]
t3, v3 = unzip(filt(b410_b3))
ax.step(t3, v3, where='post', color='teal', lw=1.2, label='0x410 B3 (bit2 flip at t=348.1s)')
vlines(ax)
ax.set_ylabel('0x410 B3 value')
ax.set_title('0x410 B3 -- bit2 flip 2.7s before CCL step1')
ax.legend(loc='upper left', fontsize=8)

axes[-1].set_xlabel('Time (s)')
axes[-1].set_xlim(T_PLOT_S, T_PLOT_E)

fig.suptitle(
    'vtruxcurrentlimitingtest.log -- CCL trigger candidates (zoomed t=335-375s)\n'
    'Gold dashed = 0x411 B0 precursor; Orange/Red = CCL step times; Blue = recovery',
    fontsize=10)
plt.tight_layout()
plt.savefig(OUTPUT, dpi=130, bbox_inches='tight')
print(f"Saved: {OUTPUT}")
