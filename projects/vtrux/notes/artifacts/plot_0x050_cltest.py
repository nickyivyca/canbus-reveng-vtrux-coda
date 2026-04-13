"""
plot_0x050_cltest.py

Plot 0x050 10-bit traction torque signal on the current-limiting test log.
Uses ZERO=292 (user-confirmed offset from plot_0x050_corrected.py).

Panels:
  1. 0x050 10-bit (zero=292)  +  throttle (0x592 B2-B3) overlaid (right axis)
  2. Battery current (0x598 B0-B1) and drivetrain current (0x598 B4-B5) -- power proxies
  3. Traction motor speed (0x5A2 B2-B3)

PT bus auto-detected via 0x051 anchor.

Output: plot_0x050_cltest.png
"""

import sys, os, bisect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

LOG    = 'projects/vtrux/logs/vtruxcurrentlimitingtest.log'
OUTPUT = 'projects/vtrux/notes/artifacts/plot_0x050_cltest3.png'
ZERO   = 292   # user-confirmed zero for 10-bit signal

# Static windows from current-limits-investigation.md
WIN_REGEN_FREE = (30,  72)    # unrestricted regen baseline
WIN_DCL        = (598, None)  # discharge limit active (to end of log)
# WIN_REGEN_LIMIT computed from data below (where 0x050 10-bit < 0)

# ---------------------------------------------------------------------------
# Pass 1: detect PT bus (first bus with 0x051 frames)
# ---------------------------------------------------------------------------
print("Detecting PT bus...")
bus_051 = {}
for frame in parse_file(LOG):
    if frame.arbitration_id == 0x051:
        bus_051[frame.bus] = bus_051.get(frame.bus, 0) + 1
    if sum(bus_051.values()) > 200:
        break

if not bus_051:
    raise RuntimeError("0x051 not found -- is this the right log?")
PT_BUS = max(bus_051, key=bus_051.get)
print(f"PT bus = {PT_BUS}  (0x051 frames: {bus_051})")

# ---------------------------------------------------------------------------
# Pass 2: collect signals
# ---------------------------------------------------------------------------
print("Parsing signals...")
sig10     = []   # (t, val)   0x050 10-bit - ZERO
throttle  = []   # (t, val)   0x592 B2-B3 LE centred 32768
batt_cur  = []   # (t, val)   0x598 B0-B1 LE centred 32768   battery current
drv_cur   = []   # (t, val)   0x598 B4-B5 LE centred 32768   drivetrain current
gen_cur   = []   # (t, val)   0x598 B2-B3 LE centred 32768   generator current
mtr_rpm   = []   # (t, val)   0x5A2 B2-B3 LE centred 32768   traction motor RPM
trq_fb    = []   # (t, val)   0x5A2 B4-B5 LE centred 32768   traction torque fb

for frame in parse_file(LOG):
    if frame.bus != PT_BUS:
        continue
    t = frame.timestamp
    d = frame.data
    aid = frame.arbitration_id

    if aid == 0x050 and len(d) >= 2:
        sig10.append((t, ((d[1] & 0x03) << 8 | d[0]) - ZERO))

    elif aid == 0x592 and len(d) >= 6:
        throttle.append((t, (d[3] << 8) | d[2]))   # raw, no centering

    elif aid == 0x598 and len(d) >= 6:
        batt_cur.append((t, ((d[1] << 8) | d[0]) - 32768))
        gen_cur.append( (t, ((d[3] << 8) | d[2]) - 32768))
        drv_cur.append( (t, ((d[5] << 8) | d[4]) - 32768))

    elif aid == 0x5A2 and len(d) >= 6:
        mtr_rpm.append((t, ((d[3] << 8) | d[2]) - 32768))
        trq_fb.append( (t, ((d[5] << 8) | d[4]) - 32768))

def unzip(pairs):
    if not pairs: return [], []
    t, v = zip(*pairs)
    return list(t), list(v)

print(f"  0x050: {len(sig10)}, throttle: {len(throttle)}, "
      f"current: {len(batt_cur)}, RPM: {len(mtr_rpm)}")

# ---------------------------------------------------------------------------
# Auto-detect regen limit window: first contiguous block where 0x050 < -10
# while vehicle is moving (RPM > 100), merging gaps <= 5s
# ---------------------------------------------------------------------------
NEG_THRESH  = -10   # counts below zero
MERGE_GAP   = 5.0   # seconds

# Build a sorted RPM lookup for fast nearest-neighbor
mtr_rpm_s = sorted(mtr_rpm)
rpm_t = [x[0] for x in mtr_rpm_s]
rpm_v = [x[1] for x in mtr_rpm_s]

def rpm_at(t, tol=0.5):
    import bisect as _b
    idx = _b.bisect_left(rpm_t, t)
    best = None; bd = tol + 1
    for i in (idx-1, idx):
        if 0 <= i < len(rpm_t):
            dt = abs(rpm_t[i] - t)
            if dt < bd: bd = dt; best = rpm_v[i]
    return best

neg_times = sorted(t for t, v in sig10
                   if v < NEG_THRESH and (rpm_at(t) or 0) > 100)

WIN_REGEN_LIMIT = None
if neg_times:
    # Merge into contiguous blocks
    blocks = []
    blk_start = blk_end = neg_times[0]
    for t in neg_times[1:]:
        if t - blk_end <= MERGE_GAP:
            blk_end = t
        else:
            blocks.append((blk_start, blk_end))
            blk_start = blk_end = t
    blocks.append((blk_start, blk_end))
    # Take the first substantial block (duration > 5s)
    for blk_s, blk_e in blocks:
        if blk_e - blk_s > 5.0:
            WIN_REGEN_LIMIT = (blk_s - 2, blk_e + 2)
            break

if WIN_REGEN_LIMIT:
    print(f"Regen limit window (auto): t={WIN_REGEN_LIMIT[0]:.1f} - {WIN_REGEN_LIMIT[1]:.1f}s")
else:
    print("No regen limit window detected from data")

# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------
print("Plotting...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(3, 1, figsize=(20, 12), sharex=True)
fig.suptitle(
    'vtruxcurrentlimitingtest.log -- 0x050 torque command (zero=292)\n'
    'Downhill regen -> discharge current limit -> generator at ~20% SoC',
    fontsize=12)

def hline(ax):
    ax.axhline(0, color='k', lw=0.5, ls='-', alpha=0.4)

def shade_windows(ax):
    t_end = sig10[-1][0] if sig10 else 1800
    t0, t1 = WIN_REGEN_FREE
    ax.axvspan(t0, t1, color='dodgerblue', alpha=0.10,
               label=f'Unrestricted regen (t={t0}-{t1}s)')
    if WIN_REGEN_LIMIT:
        t0, t1 = WIN_REGEN_LIMIT
        ax.axvspan(t0, t1, color='orangered', alpha=0.18,
                   label=f'Regen limit active (auto: t={t0:.0f}-{t1:.0f}s)')
    t0 = WIN_DCL[0]
    ax.axvspan(t0, t_end, color='gold', alpha=0.12,
               label=f'Discharge limit active (t={t0}s+)')

def align_zeros(ax_left, ax_right):
    """Shift ax_right y-limits so y=0 appears at the same height as ax_left's y=0."""
    lo1, hi1 = ax_left.get_ylim()
    lo2, hi2 = ax_right.get_ylim()
    if hi1 == lo1: return
    frac = (0.0 - lo1) / (hi1 - lo1)      # fraction from bottom where 0 sits on left axis
    span2 = hi2 - lo2
    # Expand right axis range symmetrically so 0 lands at same fraction,
    # while keeping all existing data in view.
    new_lo2 = -frac * span2
    new_hi2 = (1.0 - frac) * span2
    # Expand further if data would be clipped
    if new_lo2 > lo2:
        new_lo2 = lo2
        new_hi2 = lo2 / (-frac) * (1.0 - frac) if frac > 0 else hi2
    if new_hi2 < hi2:
        new_hi2 = hi2
        new_lo2 = -hi2 * frac / (1.0 - frac) if frac < 1 else lo2
    ax_right.set_ylim(new_lo2, new_hi2)

# ---- Panel 1: 0x050 + throttle ----
ax1 = axes[0]
ts, vs = unzip(sig10)
shade_windows(ax1)
ax1.plot(ts, vs, color='purple', lw=0.7, label='0x050 10-bit (zero=292)')
hline(ax1)
ax1.set_ylabel('Torque cmd (counts)')
ax1.set_title('0x050 10-bit traction torque command (corrected zero)')

ax1r = ax1.twinx()
tt, tv = unzip(throttle)
ax1r.plot(tt, tv, color='forestgreen', lw=0.6, alpha=0.7, label='Throttle 0x592 B2-B3 (raw)')
ax1r.set_ylabel('Throttle (raw counts)', color='forestgreen')
ax1r.tick_params(axis='y', labelcolor='forestgreen')

lines1, labs1 = ax1.get_legend_handles_labels()
lines2, labs2 = ax1r.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labs1 + labs2, loc='upper left', fontsize=8, ncol=2)
align_zeros(ax1, ax1r)

# ---- Panel 2: battery and drivetrain current (power proxy) ----
ax2 = axes[1]
shade_windows(ax2)
tb, vb = unzip(batt_cur)
td, vd = unzip(drv_cur)
tg, vg = unzip(gen_cur)
ax2.plot(tb, vb, color='steelblue',  lw=0.6, alpha=0.85, label='Battery current  0x598 B0-B1')
ax2.plot(td, vd, color='darkorange', lw=0.6, alpha=0.85, label='Drivetrain current  0x598 B4-B5')
ax2.plot(tg, vg, color='teal',       lw=0.5, alpha=0.65, label='Generator current  0x598 B2-B3')
hline(ax2)
ax2.set_ylabel('Current (counts, centred 32768)\n~power proxy (V approx. constant)')
ax2.set_title('Battery / drivetrain / generator current  (positive = discharge / motoring)')
ax2.legend(loc='upper left', fontsize=8)

# ---- Panel 3: motor RPM ----
ax3 = axes[2]
shade_windows(ax3)
tr, vr = unzip(mtr_rpm)
tf2, vf2 = unzip(trq_fb)
ax3.plot(tr, vr, color='crimson', lw=0.7, label='Motor RPM  0x5A2 B2-B3')
hline(ax3)
ax3.set_ylabel('RPM (counts, centred 32768)')
ax3.set_title('Traction motor speed')

ax3r = ax3.twinx()
ax3r.plot(tf2, vf2, color='slategray', lw=0.5, alpha=0.6, label='Torque feedback  0x5A2 B4-B5')
ax3r.axhline(0, color='k', lw=0.4, ls=':', alpha=0.3)
ax3r.set_ylabel('Torque feedback (counts)', color='slategray')
ax3r.tick_params(axis='y', labelcolor='slategray')
lines3, labs3 = ax3.get_legend_handles_labels()
lines4, labs4 = ax3r.get_legend_handles_labels()
ax3.legend(lines3 + lines4, labs3 + labs4, loc='upper left', fontsize=8)

ax3.set_xlabel('Time (s)')

plt.tight_layout()
plt.savefig(OUTPUT, dpi=130, bbox_inches='tight')
print(f"Saved: {OUTPUT}")
