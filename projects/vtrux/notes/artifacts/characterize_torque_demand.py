"""
characterize_torque_demand.py

Pass 1a -- Regen brake demand model (t=100-300s, brake > BRAKE_IDLE_THRESHOLD only):
  Idle brake values (0/39/78/117/156 = multiples of 39, sensor floor) are excluded.
  The ~245 genuine brake-press frames give a sparse but real demand model.

Pass 1b -- Speed-stratified regen envelope (t=100-300s, unrestricted):
  For each motor-speed bin, show median and 90th pct of |regen torque| separately for:
    - Lift-off regen  (brake <= BRAKE_IDLE_THRESHOLD, no pedal pressed)
    - Brake-pressed   (brake >  BRAKE_IDLE_THRESHOLD)
  Overlay the regen limit window (t=401-503s) on the same chart to show where
  the CCL ceiling drops.

Pass 2 -- Discharge characterization (t>720s, post-limit highway):
  throttle demand (0x592 B2-B3 LE) vs actual discharge torque (0x5A2 B4-B5 LE-32768).

Outputs:
  characterize_torque_demand.png   -- 3-panel figure
  characterize_torque_demand.txt   -- numeric summary
"""

import sys, statistics
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"

# Brake idle threshold: values <= this are sensor floor (multiples of 39 when unpressed)
BRAKE_IDLE_THRESHOLD = 156

T_REGEN_START  = 100.0
T_REGEN_END    = 300.0
T_LIMIT_START  = 401.0
T_LIMIT_END    = 503.0
T_DISCH_START  = 720.0
T_DISCH_END    = 1800.0

# ---------- collect raw timeseries -------------------------------------------
raw_592 = []   # (t, throttle, brake)
raw_5A2 = []   # (t, torque_signed, speed_signed)

print("Parsing log...")
for frame in parse_file(str(LOG)):
    t, d, aid = frame.timestamp, frame.data, frame.arbitration_id
    if aid == 0x592 and len(d) >= 6:
        thr  = d[2] | d[3] << 8
        brk  = d[4] | d[5] << 8
        raw_592.append((t, thr, brk))
    elif aid == 0x5A2 and len(d) >= 6:
        torq = (d[4] | d[5] << 8) - 32768
        spd  = (d[2] | d[3] << 8) - 32768
        raw_5A2.append((t, torq, spd))

print(f"  0x592: {len(raw_592)}  0x5A2: {len(raw_5A2)}")

# ---------- nearest-time join ------------------------------------------------
import bisect

t_592    = [r[0] for r in raw_592]
thr_arr  = [r[1] for r in raw_592]
brk_arr  = [r[2] for r in raw_592]

def get_592(t_q):
    i = bisect.bisect_left(t_592, t_q)
    if i == 0: return thr_arr[0], brk_arr[0]
    if i >= len(t_592): return thr_arr[-1], brk_arr[-1]
    if abs(t_592[i] - t_q) < abs(t_592[i-1] - t_q):
        return thr_arr[i], brk_arr[i]
    return thr_arr[i-1], brk_arr[i-1]

# ---------- Pass 1a: regen brake demand model --------------------------------
# Only frames with genuine brake press (brake > BRAKE_IDLE_THRESHOLD)
regen_brake_pts  = []   # (brake, |torque|, speed) -- genuine press
regen_liftoff_pts = []  # (speed, |torque|)         -- lift-off, for envelope
regen_limit_press = []  # same as above but from limit window
regen_limit_lift  = []

for t, torq, spd in raw_5A2:
    if torq >= -50:
        continue  # not regen
    abs_torq = -torq
    abs_spd  = abs(spd)
    thr, brk = get_592(t)

    if T_REGEN_START <= t <= T_REGEN_END:
        if brk > BRAKE_IDLE_THRESHOLD:
            regen_brake_pts.append((brk, abs_torq, abs_spd))
        else:
            regen_liftoff_pts.append((abs_spd, abs_torq))

    elif T_LIMIT_START <= t <= T_LIMIT_END:
        if brk > BRAKE_IDLE_THRESHOLD:
            regen_limit_press.append((abs_spd, abs_torq))
        else:
            regen_limit_lift.append((abs_spd, abs_torq))

print(f"\nPass 1a -- unrestricted regen brake-press frames:  {len(regen_brake_pts)}")
print(f"           unrestricted lift-off frames:            {len(regen_liftoff_pts)}")
print(f"           limit-window brake-press frames:         {len(regen_limit_press)}")
print(f"           limit-window lift-off frames:            {len(regen_limit_lift)}")

# Fit brake demand model (sparse genuine-press data only)
slope_r = intercept_r = r2_r = None
if len(regen_brake_pts) >= 5:
    brk_x  = [p[0] for p in regen_brake_pts]
    torq_y = [p[1] for p in regen_brake_pts]
    spd_c  = [p[2] for p in regen_brake_pts]
    mx = statistics.mean(brk_x);  my = statistics.mean(torq_y)
    ssxy = sum((x-mx)*(y-my) for x,y in zip(brk_x, torq_y))
    ssxx = sum((x-mx)**2 for x in brk_x)
    slope_r = ssxy / ssxx if ssxx else 0
    intercept_r = my - slope_r * mx
    ss_res = sum((y-(slope_r*x+intercept_r))**2 for x,y in zip(brk_x, torq_y))
    ss_tot = sum((y-my)**2 for y in torq_y)
    r2_r = 1 - ss_res/ss_tot if ss_tot else 0
    print(f"  Brake demand model: slope={slope_r:.4f}  intercept={intercept_r:.1f}  R2={r2_r:.4f}")
    print(f"  Brake range: {min(brk_x)}-{max(brk_x)}  Torque range: {min(torq_y):.0f}-{max(torq_y):.0f}")

# ---------- Pass 1b: speed-stratified regen envelope ------------------------
# Build speed bins from unrestricted window (both categories combined for bin edges)
all_unrestr_spd = [p[0] for p in regen_liftoff_pts] + [p[2] for p in regen_brake_pts]
if all_unrestr_spd:
    spd_min = min(all_unrestr_spd)
    spd_max = max(all_unrestr_spd)
    N_BINS  = 8
    bin_w   = (spd_max - spd_min) / N_BINS
    bin_edges = [spd_min + i * bin_w for i in range(N_BINS + 1)]
    bin_centers = [(bin_edges[i] + bin_edges[i+1]) / 2 for i in range(N_BINS)]

    def bin_idx(spd):
        i = int((spd - spd_min) / bin_w)
        return min(i, N_BINS - 1)

    def pct(lst, p):
        if not lst: return float('nan')
        s = sorted(lst)
        idx = (len(s) - 1) * p / 100
        lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
        return s[lo] + (s[hi] - s[lo]) * (idx - lo)

    # Accumulate torques per bin for each series
    bins_lift_unr  = defaultdict(list)
    bins_press_unr = defaultdict(list)
    bins_lift_lim  = defaultdict(list)
    bins_press_lim = defaultdict(list)

    for spd, torq in regen_liftoff_pts:
        bins_lift_unr[bin_idx(spd)].append(torq)
    for brk, torq, spd in regen_brake_pts:
        bins_press_unr[bin_idx(spd)].append(torq)
    for spd, torq in regen_limit_lift:
        bins_lift_lim[bin_idx(spd)].append(torq)
    for spd, torq in regen_limit_press:
        bins_press_lim[bin_idx(spd)].append(torq)

    # Per-bin stats
    def bin_stats(bins_dict):
        meds, p90s, ns = [], [], []
        for i in range(N_BINS):
            vals = bins_dict.get(i, [])
            meds.append(pct(vals, 50) if vals else float('nan'))
            p90s.append(pct(vals, 90) if vals else float('nan'))
            ns.append(len(vals))
        return meds, p90s, ns

    med_lu, p90_lu, n_lu  = bin_stats(bins_lift_unr)
    med_pu, p90_pu, n_pu  = bin_stats(bins_press_unr)
    med_ll, p90_ll, n_ll  = bin_stats(bins_lift_lim)
    med_pl, p90_pl, n_pl  = bin_stats(bins_press_lim)

    print(f"\nPass 1b -- speed bins  (spd_min={spd_min:.0f}  spd_max={spd_max:.0f}  bin_w={bin_w:.0f})")
    print(f"{'Bin center':>12}  {'LiftOff-Unr n':>13}  {'p50':>6}  {'p90':>6}  "
          f"{'Press-Unr n':>11}  {'p50':>6}  {'p90':>6}  "
          f"{'LiftOff-Lim n':>13}  {'p50':>6}  {'p90':>6}")
    for i in range(N_BINS):
        print(f"  {bin_centers[i]:8.0f}    "
              f"{n_lu[i]:4d}  {med_lu[i]:8.0f}  {p90_lu[i]:8.0f}  "
              f"{n_pu[i]:4d}  {med_pu[i]:8.0f}  {p90_pu[i]:8.0f}  "
              f"{n_ll[i]:4d}  {med_ll[i]:8.0f}  {p90_ll[i]:8.0f}")

# ---------- Pass 2: discharge characterization -------------------------------
disch_pts = []
for t, torq, spd in raw_5A2:
    if T_DISCH_START <= t <= T_DISCH_END and torq > 50:
        thr, brk = get_592(t)
        if thr > 0 and abs(spd) > 200:
            disch_pts.append((thr, torq, abs(spd)))

print(f"\nPass 2 -- discharge frames: {len(disch_pts)}")

slope_d = intercept_d = r2_d = None
if len(disch_pts) >= 5:
    thr_x  = [p[0] for p in disch_pts]
    torq_y = [p[1] for p in disch_pts]
    spd_c  = [p[2] for p in disch_pts]
    mx = statistics.mean(thr_x); my = statistics.mean(torq_y)
    ssxy = sum((x-mx)*(y-my) for x,y in zip(thr_x, torq_y))
    ssxx = sum((x-mx)**2 for x in thr_x)
    slope_d = ssxy / ssxx if ssxx else 0
    intercept_d = my - slope_d * mx
    ss_res = sum((y-(slope_d*x+intercept_d))**2 for x,y in zip(thr_x, torq_y))
    ss_tot = sum((y-my)**2 for y in torq_y)
    r2_d = 1 - ss_res/ss_tot if ss_tot else 0
    print(f"  Discharge model: slope={slope_d:.4f}  intercept={intercept_d:.1f}  R2={r2_d:.4f}")

# ---------- figure -----------------------------------------------------------
fig = plt.figure(figsize=(17, 12))
fig.suptitle("Torque-Demand Characterization -- vtruxcurrentlimitingtest.log", fontsize=13)

# Layout: top row = Pass 1a (regen brake model) + Pass 2 (discharge)
#         bottom row = Pass 1b (speed envelope, full width)
gs = fig.add_gridspec(2, 2, hspace=0.38, wspace=0.3)
ax1a = fig.add_subplot(gs[0, 0])
ax2  = fig.add_subplot(gs[0, 1])
ax1b = fig.add_subplot(gs[1, :])

# -- Pass 1a: regen brake demand (sparse genuine-press data) ------------------
if regen_brake_pts:
    norm_r = mcolors.Normalize(vmin=min(p[2] for p in regen_brake_pts),
                                vmax=max(p[2] for p in regen_brake_pts))
    sc = ax1a.scatter([p[0] for p in regen_brake_pts],
                      [p[1] for p in regen_brake_pts],
                      c=[p[2] for p in regen_brake_pts],
                      cmap='plasma', norm=norm_r, s=12, alpha=0.8, zorder=3)
    plt.colorbar(sc, ax=ax1a, label='Motor speed (RPM)')
    if slope_r is not None:
        x_fit = [BRAKE_IDLE_THRESHOLD, max(p[0] for p in regen_brake_pts)]
        ax1a.plot(x_fit, [slope_r*x + intercept_r for x in x_fit],
                  'w--', lw=1.5, label=f'Fit  slope={slope_r:.3f}  R2={r2_r:.3f}')
        ax1a.legend(fontsize=8)
ax1a.set_xlabel('Brake demand (raw counts, > idle threshold only)')
ax1a.set_ylabel('|Regen torque| (counts)')
ax1a.set_title(f'Pass 1a: Regen brake model  t={T_REGEN_START:.0f}-{T_REGEN_END:.0f}s\n'
               f'(brake > {BRAKE_IDLE_THRESHOLD} only -- {len(regen_brake_pts)} frames)')
ax1a.grid(True, alpha=0.25)

# -- Pass 2: discharge --------------------------------------------------------
if disch_pts:
    norm_d = mcolors.Normalize(vmin=min(p[2] for p in disch_pts),
                                vmax=max(p[2] for p in disch_pts))
    sc2 = ax2.scatter([p[0] for p in disch_pts],
                      [p[1] for p in disch_pts],
                      c=[p[2] for p in disch_pts],
                      cmap='plasma', norm=norm_d, s=6, alpha=0.5, zorder=3)
    plt.colorbar(sc2, ax=ax2, label='Motor speed (RPM)')
    if slope_d is not None:
        x2 = [min(p[0] for p in disch_pts), max(p[0] for p in disch_pts)]
        ax2.plot(x2, [slope_d*x + intercept_d for x in x2],
                 'w--', lw=1.5, label=f'Fit  slope={slope_d:.3f}  R2={r2_d:.3f}')
        ax2.legend(fontsize=8)
ax2.set_xlabel('Throttle demand (counts)')
ax2.set_ylabel('Discharge torque (counts)')
ax2.set_title(f'Pass 2: Discharge  t>{T_DISCH_START:.0f}s  ({len(disch_pts)} frames)')
ax2.grid(True, alpha=0.25)

# -- Pass 1b: speed-stratified regen envelope ---------------------------------
def plot_series(ax, centers, meds, p90s, ns, color, label_prefix, ls='-', marker='o'):
    valid = [(c, m, p, n) for c, m, p, n in zip(centers, meds, p90s, ns)
             if not (m != m) and n > 0]  # drop nan / empty bins
    if not valid:
        return
    cx = [v[0] for v in valid]
    my = [v[1] for v in valid]
    py = [v[2] for v in valid]
    ax.plot(cx, my, color=color, ls=ls, marker=marker, ms=5, lw=1.5,
            label=f'{label_prefix} median (n={sum(v[3] for v in valid)})')
    ax.plot(cx, py, color=color, ls=':', marker=marker, ms=4, lw=1.0, alpha=0.7,
            label=f'{label_prefix} p90')

if all_unrestr_spd:
    plot_series(ax1b, bin_centers, med_lu, p90_lu, n_lu,
                'deepskyblue', 'Unrestricted lift-off')
    plot_series(ax1b, bin_centers, med_pu, p90_pu, n_pu,
                'limegreen', 'Unrestricted brake-press')
    plot_series(ax1b, bin_centers, med_ll, p90_ll, n_ll,
                'orange', 'LIMIT lift-off', ls='--', marker='s')
    plot_series(ax1b, bin_centers, med_pl, p90_pl, n_pl,
                'red', 'LIMIT brake-press', ls='--', marker='s')

ax1b.set_xlabel('Motor speed (RPM, absolute)')
ax1b.set_ylabel('|Regen torque| (counts)')
ax1b.set_title(f'Pass 1b: Speed-stratified regen envelope\n'
               f'Unrestricted t={T_REGEN_START:.0f}-{T_REGEN_END:.0f}s  vs  '
               f'Limit window t={T_LIMIT_START:.0f}-{T_LIMIT_END:.0f}s')
ax1b.legend(fontsize=8, ncol=2)
ax1b.grid(True, alpha=0.25)

out_png = Path(__file__).parent / "characterize_torque_demand.png"
plt.savefig(out_png, dpi=140, bbox_inches='tight')
print(f"\nPlot saved: {out_png}")

# ---------- text summary -----------------------------------------------------
out_txt = Path(__file__).parent / "characterize_torque_demand.txt"
with open(out_txt, 'w') as f:
    f.write("=== Torque-Demand Characterization ===\n\n")
    f.write(f"Brake idle threshold: {BRAKE_IDLE_THRESHOLD} "
            f"(sensor floor multiples of 39 when unpressed)\n\n")
    f.write("--- Pass 1a: Regen brake demand model ---\n")
    f.write(f"  Window  : t={T_REGEN_START}-{T_REGEN_END}s  (unrestricted)\n")
    f.write(f"  Frames  : {len(regen_brake_pts)} genuine-press  +  "
            f"{len(regen_liftoff_pts)} lift-off (excluded from model)\n")
    if slope_r is not None:
        f.write(f"  Model   : |torque| = {slope_r:.4f} * brake + {intercept_r:.1f}\n")
        f.write(f"  R2      : {r2_r:.4f}\n")
        f.write(f"  Brake range  : {min(p[0] for p in regen_brake_pts)}-"
                f"{max(p[0] for p in regen_brake_pts)}\n")
        f.write(f"  Torque range : {min(p[1] for p in regen_brake_pts):.0f}-"
                f"{max(p[1] for p in regen_brake_pts):.0f}\n")
    f.write("\n--- Pass 1b: Speed-stratified regen envelope ---\n")
    if all_unrestr_spd:
        f.write(f"  {'SpeedBin':>10}  {'n_LO_unr':>8}  {'p50':>6}  {'p90':>6}  "
                f"{'n_BP_unr':>8}  {'p50':>6}  {'p90':>6}  "
                f"{'n_LO_lim':>8}  {'p50':>6}  {'p90':>6}\n")
        for i in range(N_BINS):
            f.write(f"  {bin_centers[i]:10.0f}  "
                    f"{n_lu[i]:8d}  {med_lu[i]:6.0f}  {p90_lu[i]:6.0f}  "
                    f"{n_pu[i]:8d}  {med_pu[i]:6.0f}  {p90_pu[i]:6.0f}  "
                    f"{n_ll[i]:8d}  {med_ll[i]:6.0f}  {p90_ll[i]:6.0f}\n")
    f.write("\n--- Pass 2: Discharge model ---\n")
    f.write(f"  Window  : t>{T_DISCH_START}s  (post-limit highway)\n")
    f.write(f"  Frames  : {len(disch_pts)}\n")
    if slope_d is not None:
        f.write(f"  Model   : torque = {slope_d:.4f} * throttle + {intercept_d:.1f}\n")
        f.write(f"  R2      : {r2_d:.4f}\n")
print(f"Text summary: {out_txt}")
