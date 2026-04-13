"""
plot_0x412_vs_ccl.py

Verify 0x412 B2 as the BMS-side CCL source in another_M0 charge session.

Panels:
  1. 0x050 CCL vs 0x412 B2 overlaid (both vs time, right axis for B2)
  2. Scatter: 0x412 B2 (x) vs 0x050 CCL (y) with linear regression line
  3. 0x420 B1 (5-level stepped signal, r=0.983) vs CCL for comparison

Output: plot_0x412_vs_ccl.png
"""

import os, sys, glob, math, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       '..', '..', 'logs',
                                       'after-battery-swap-charges'))
FILES   = sorted(glob.glob(os.path.join(LOG_DIR, 'another_M0_T*.log')))
OUTPUT  = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       'plot_0x412_vs_ccl.png'))
T_COLLECT_END = 4500.0

print(f"Found {len(FILES)} chunks")
bus_051 = {}
for frame in parse_file(FILES[0]):
    if frame.arbitration_id == 0x051:
        bus_051[frame.bus] = bus_051.get(frame.bus, 0) + 1
PT_BUS = max(bus_051, key=bus_051.get)
print(f"PT bus = {PT_BUS}")

ccl_ts    = []   # (t, raw)
b412_b2   = []   # (t, val)
b412_b1   = []
b412_b3   = []
b420_b1   = []
b420_b4   = []

chunk_offset = 0.0
for fpath in FILES:
    if chunk_offset > T_COLLECT_END: break
    frames = list(parse_file(fpath))
    if not frames: continue
    last_ts = frames[-1].timestamp
    for f in frames:
        t = chunk_offset + f.timestamp
        if t > T_COLLECT_END: break
        aid = f.arbitration_id
        d   = f.data
        if aid == 0x050 and f.bus == PT_BUS and len(d) >= 2:
            ccl_ts.append((t, (d[1] & 0x03) << 8 | d[0]))
        elif aid == 0x412 and f.bus == PT_BUS and len(d) >= 4:
            b412_b1.append((t, d[1]))
            b412_b2.append((t, d[2]))
            b412_b3.append((t, d[3]))
        elif aid == 0x420 and f.bus == PT_BUS and len(d) >= 5:
            b420_b1.append((t, d[1]))
            b420_b4.append((t, d[4]))
    chunk_offset += last_ts

print(f"CCL frames: {len(ccl_ts)}  0x412: {len(b412_b2)}  0x420B1: {len(b420_b1)}")

# Auto-detect ramp window
def first_sustained_below(ts_vals, threshold, hold):
    below = None
    for t, v in ts_vals:
        if v < threshold:
            if below is None: below = t
            elif t - below >= hold: return below
        else: below = None
    return None

T_RAMP_START = first_sustained_below(ccl_ts, 290, 120) or 400.0
T_RAMP_END   = first_sustained_below(ccl_ts, 15,   60) or 3700.0
print(f"Ramp window: t={T_RAMP_START:.0f}-{T_RAMP_END:.0f}s")

# Interpolate CCL at arbitrary t
def ccl_at(t):
    if not ccl_ts: return None
    lo, hi = 0, len(ccl_ts)-1
    if t <= ccl_ts[lo][0]: return ccl_ts[lo][1]
    if t >= ccl_ts[hi][0]: return ccl_ts[hi][1]
    while hi - lo > 1:
        mid = (lo+hi)//2
        if ccl_ts[mid][0] <= t: lo = mid
        else: hi = mid
    t0,v0 = ccl_ts[lo]; t1,v1 = ccl_ts[hi]
    return v0 + (t-t0)/(t1-t0)*(v1-v0) if t1>t0 else v0

# Linear regression (x predicts y)
def linreg(xs, ys):
    n = len(xs)
    mx = sum(xs)/n; my = sum(ys)/n
    sxx = sum((x-mx)**2 for x in xs)
    sxy = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    if sxx < 1e-9: return None, None, None
    slope = sxy/sxx
    intercept = my - slope*mx
    yhat = [slope*x+intercept for x in xs]
    ss_res = sum((y-yh)**2 for y,yh in zip(ys,yhat))
    ss_tot = sum((y-my)**2 for y in ys)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    return slope, intercept, r2

# Build scatter pairs (0x412 B2 vs CCL) over ramp window
scatter_b2_ccl = [(v, ccl_at(t)) for t, v in b412_b2
                  if T_RAMP_START <= t <= T_RAMP_END and ccl_at(t) is not None]
if scatter_b2_ccl:
    xs_b2, ys_ccl = zip(*scatter_b2_ccl)
    slope_b2, icept_b2, r2_b2 = linreg(list(xs_b2), list(ys_ccl))
    print(f"\n0x412 B2 -> CCL linear fit:")
    print(f"  slope={slope_b2:.4f}  intercept={icept_b2:.2f}  R2={r2_b2:.6f}")
    print(f"  Implied encoding: CCL = {slope_b2:.4f} * B2 + {icept_b2:.2f}")

# Build scatter for 0x420 B1
scatter_b1_ccl = [(v, ccl_at(t)) for t, v in b420_b1
                  if T_RAMP_START <= t <= T_RAMP_END and ccl_at(t) is not None]

# ---- Plot ----
print("\nPlotting ...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(3, 1, figsize=(14, 14))

def shade(ax):
    ax.axvspan(T_RAMP_START, T_RAMP_END, color='orangered', alpha=0.06, label='Ramp window')

# Panel 1: CCL and 0x412 B2 vs time
ax1 = axes[0]
tc, vc = zip(*[(t,v) for t,v in ccl_ts if 0 <= t <= T_COLLECT_END])
ax1.plot(tc, vc, color='purple', lw=0.8, label='0x050 CCL (raw)')
shade(ax1)
ax1.set_ylabel('CCL raw', color='purple')
ax1.tick_params(axis='y', labelcolor='purple')
ax1.set_title('0x050 CCL (purple) vs 0x412 B2 (teal, right axis) -- another_M0 charge session')

ax1r = ax1.twinx()
t2, v2 = zip(*[(t,v) for t,v in b412_b2 if 0 <= t <= T_COLLECT_END])
ax1r.plot(t2, v2, color='teal', lw=0.8, alpha=0.85, label='0x412 B2')
ax1r.set_ylabel('0x412 B2 value', color='teal')
ax1r.tick_params(axis='y', labelcolor='teal')
lines1, labs1 = ax1.get_legend_handles_labels()
lines2, labs2 = ax1r.get_legend_handles_labels()
ax1.legend(lines1+lines2, labs1+labs2, loc='upper right', fontsize=8)
ax1.set_xlabel('Time (s)')

# Panel 2: scatter B2 vs CCL with regression
ax2 = axes[1]
if scatter_b2_ccl:
    xs_plot = list(xs_b2); ys_plot = list(ys_ccl)
    ax2.scatter(xs_plot, ys_plot, s=1, alpha=0.3, color='teal', label='(B2, CCL) pairs')
    x_min, x_max = min(xs_plot), max(xs_plot)
    if slope_b2 is not None:
        xl = [x_min, x_max]
        yl = [slope_b2*x+icept_b2 for x in xl]
        ax2.plot(xl, yl, color='red', lw=2,
                 label=f'Fit: CCL = {slope_b2:.3f}*B2 + {icept_b2:.1f}  (R2={r2_b2:.4f})')
ax2.set_xlabel('0x412 B2 value')
ax2.set_ylabel('0x050 CCL raw')
ax2.set_title('0x412 B2 vs CCL -- scatter and linear regression (ramp window)')
ax2.legend(fontsize=8)

# Panel 3: 0x420 B1 vs CCL (for comparison -- discrete stepped)
ax3 = axes[2]
tc2, vc2 = zip(*[(t,v) for t,v in ccl_ts if 0 <= t <= T_COLLECT_END])
ax3.plot(tc2, vc2, color='purple', lw=0.8, alpha=0.6, label='0x050 CCL')
shade(ax3)
ax3.set_ylabel('CCL raw', color='purple')
ax3.tick_params(axis='y', labelcolor='purple')
ax3.set_title('0x420 B1 (red, right axis, r=0.983, 5 unique values) vs CCL -- discrete tier comparison')

ax3r = ax3.twinx()
t1b, v1b = zip(*[(t,v) for t,v in b420_b1 if 0 <= t <= T_COLLECT_END])
ax3r.step(t1b, v1b, where='post', color='crimson', lw=1.2, alpha=0.85, label='0x420 B1')
ax3r.set_ylabel('0x420 B1 value', color='crimson')
ax3r.tick_params(axis='y', labelcolor='crimson')
lines3, labs3 = ax3.get_legend_handles_labels()
lines4, labs4 = ax3r.get_legend_handles_labels()
ax3.legend(lines3+lines4, labs3+labs4, loc='upper right', fontsize=8)
ax3.set_xlabel('Time (s)')

plt.tight_layout()
plt.savefig(OUTPUT, dpi=130, bbox_inches='tight')
print(f"Saved: {OUTPUT}")
