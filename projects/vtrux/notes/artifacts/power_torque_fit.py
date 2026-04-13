"""
power_torque_fit.py

Test whether 0x598 B2-B3 (generator) and B4-B5 (drivetrain) encode
mechanical power (P = torque x omega) rather than measured current.

For each channel, compute P_est = torque * RPM at the 0x598 timestamps
(nearest-neighbour interpolation), then do a least-squares (slope + intercept)
fit and plot the overlay and residual.

Generator:
  torque  -- 0x051 B1-B2  LE uint16, centered at 32768 (neg corr with gen power)
  RPM     -- 0x63C B5-B6  BE uint16 raw

Drivetrain:
  torque  -- 0x5A2 B4-B5  LE uint16, centered at 32768
  RPM     -- 0x5A2 B2-B3  LE uint16, centered at 32768

Diagnostic: if P_est fits well during gen-ON but 0x598 has residual oscillations
during gen-OFF (where RPM=0 forces P_est=0), that rules out the pure T*omega
hypothesis and supports the balance-equation (residual) hypothesis.

Log: logs/vtruxevapdrivelog4.log
Output: artifacts/power_torque_fit_plot.png
"""

import sys
import bisect
import math
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxevapdrivelog4.log"
OUT = Path(__file__).parent / "power_torque_fit_plot.png"

GEN_START = 431.7


# ---------- helpers -----------------------------------------------------------

def interp_nearest(sorted_ts, sorted_vs, t):
    i = bisect.bisect_left(sorted_ts, t)
    if i == 0:
        return sorted_vs[0]
    if i >= len(sorted_ts):
        return sorted_vs[-1]
    if abs(sorted_ts[i] - t) <= abs(sorted_ts[i-1] - t):
        return sorted_vs[i]
    return sorted_vs[i-1]


def ols(xs, ys):
    """Ordinary least squares: y = slope*x + intercept. Returns (slope, intercept, r)."""
    n = len(xs)
    if n < 2:
        return float('nan'), float('nan'), float('nan')
    mx = sum(xs) / n
    my = sum(ys) / n
    ss_xy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    ss_xx = sum((x - mx) ** 2 for x in xs)
    ss_yy = sum((y - my) ** 2 for y in ys)
    if ss_xx == 0:
        return 0.0, my, 0.0
    slope = ss_xy / ss_xx
    intercept = my - slope * mx
    r = ss_xy / math.sqrt(ss_xx * ss_yy) if ss_xx > 0 and ss_yy > 0 else 0.0
    return slope, intercept, r


# ---------- collect data ------------------------------------------------------

print("Parsing log...")

# 0x598 timestamps + all three channels
ref_ts  = []
ref_gen = []   # B2-B3 LE, centered
ref_drv = []   # B4-B5 LE, centered

# 0x051 B1-B2 LE, centered (gen torque cmd)
gen_torq_ts, gen_torq_vs = [], []

# 0x63C B5-B6 BE raw (gen RPM)
gen_rpm_ts, gen_rpm_vs = [], []

# 0x5A2 B2-B3 LE centered (drv RPM) and B4-B5 LE centered (drv torque)
drv_ts, drv_rpm_vs, drv_torq_vs = [], [], []

frame_count = 0
WANTED = {0x598, 0x051, 0x63C, 0x5A2}

for frame in parse_file(str(LOG)):
    aid = frame.arbitration_id
    if aid not in WANTED:
        continue
    t = frame.timestamp
    d = frame.data
    frame_count += 1

    if aid == 0x598 and len(d) >= 6:
        ref_ts.append(t)
        ref_gen.append(((d[3] << 8) | d[2]) - 32768)
        ref_drv.append(((d[5] << 8) | d[4]) - 32768)

    elif aid == 0x051 and len(d) >= 3:
        gen_torq_ts.append(t)
        gen_torq_vs.append(((d[2] << 8) | d[1]) - 32768)

    elif aid == 0x63C and len(d) >= 7:
        gen_rpm_ts.append(t)
        gen_rpm_vs.append((d[5] << 8) | d[6])   # BE16

    elif aid == 0x5A2 and len(d) >= 6:
        drv_ts.append(t)
        drv_rpm_vs.append(((d[3] << 8) | d[2]) - 32768)   # B2-B3 centered
        drv_torq_vs.append(((d[5] << 8) | d[4]) - 32768)  # B4-B5 centered

print(f"  0x598 samples:  {len(ref_ts)}")
print(f"  0x051 samples:  {len(gen_torq_ts)}")
print(f"  0x63C samples:  {len(gen_rpm_ts)}")
print(f"  0x5A2 samples:  {len(drv_ts)}")


# ---------- interpolate to 0x598 timestamps ----------------------------------

def interp_series(src_ts, src_vs, query_ts):
    return [interp_nearest(src_ts, src_vs, t) for t in query_ts]

gen_torq_at_ref  = interp_series(gen_torq_ts, gen_torq_vs, ref_ts)
gen_rpm_at_ref   = interp_series(gen_rpm_ts,  gen_rpm_vs,  ref_ts)
drv_rpm_at_ref   = interp_series(drv_ts,      drv_rpm_vs,  ref_ts)
drv_torq_at_ref  = interp_series(drv_ts,      drv_torq_vs, ref_ts)

# P_est = torque * RPM  (proportional to mechanical power; sign from torque)
# Generator torque cmd has negative correlation with gen current/power, so negate.
p_gen_est = [(-t_) * r_ for t_, r_ in zip(gen_torq_at_ref, gen_rpm_at_ref)]
p_drv_est = [t_ * r_ for t_, r_ in zip(drv_torq_at_ref, drv_rpm_at_ref)]


# ---------- least-squares fit -------------------------------------------------

slope_g, intercept_g, r_g = ols(p_gen_est, ref_gen)
slope_d, intercept_d, r_d = ols(p_drv_est, ref_drv)

print(f"\nGenerator fit:")
print(f"  slope={slope_g:.6f}  intercept={intercept_g:.1f}  r={r_g:+.4f}")
print(f"Drivetrain fit:")
print(f"  slope={slope_d:.6f}  intercept={intercept_d:.1f}  r={r_d:+.4f}")

gen_fit    = [slope_g * p + intercept_g for p in p_gen_est]
drv_fit    = [slope_d * p + intercept_d for p in p_drv_est]
gen_resid  = [ref - fit for ref, fit in zip(ref_gen, gen_fit)]
drv_resid  = [ref - fit for ref, fit in zip(ref_drv, drv_fit)]


# ---------- plot --------------------------------------------------------------

fig, axes = plt.subplots(6, 1, figsize=(18, 16), sharex=True)
fig.suptitle(
    'P = torque x RPM best-fit vs 0x598 generator and drivetrain channels\n'
    'Log: vtruxevapdrivelog4.log    Green shading = generator ON (t > 431.7s)',
    fontsize=11
)

log_end = max(ref_ts)

panels = [
    # (timeseries_list, label, color)  -- multiple traces per panel handled below
]

def shade(ax):
    ax.axvspan(GEN_START, log_end, color='green', alpha=0.07, zorder=0)
    ax.axvline(GEN_START, color='green', linewidth=0.8, linestyle='--', alpha=0.6)
    ax.axhline(0, color='black', linewidth=0.4, linestyle=':')
    ax.tick_params(labelsize=7)
    ax.grid(True, linewidth=0.3, alpha=0.5)

# Panel 0: raw gen torque (centered) and gen RPM
axes[0].plot(gen_torq_ts, gen_torq_vs, linewidth=0.5, color='darkorange', label='0x051 B1-B2 gen torque cmd (centered)')
axes[0].set_ylabel('0x051 B1-B2\ngen torque cmd', fontsize=8)
shade(axes[0])
axes[0].legend(fontsize=7)

axes[1].plot(gen_rpm_ts, gen_rpm_vs, linewidth=0.5, color='olive', label='0x63C B5-B6 gen RPM (BE16 raw)')
axes[1].set_ylabel('0x63C B5-B6\ngen RPM', fontsize=8)
shade(axes[1])
axes[1].legend(fontsize=7)

# Panel 2: generator channel vs fit
axes[2].plot(ref_ts, ref_gen, linewidth=0.8, color='steelblue', label='0x598 B2-B3 gen (measured)')
axes[2].plot(ref_ts, gen_fit, linewidth=0.8, color='crimson', linestyle='--', label=f'T*omega fit (r={r_g:+.3f})')
axes[2].set_ylabel('0x598 B2-B3\ngenerator', fontsize=8)
shade(axes[2])
axes[2].legend(fontsize=7)

# Panel 3: generator residual
axes[3].plot(ref_ts, gen_resid, linewidth=0.7, color='crimson', label='gen residual (measured - fit)')
axes[3].set_ylabel('gen residual', fontsize=8)
shade(axes[3])
axes[3].legend(fontsize=7)

# Panel 4: drivetrain channel vs fit
axes[4].plot(ref_ts, ref_drv, linewidth=0.8, color='steelblue', label='0x598 B4-B5 drv (measured)')
axes[4].plot(ref_ts, drv_fit, linewidth=0.8, color='crimson', linestyle='--', label=f'T*omega fit (r={r_d:+.3f})')
axes[4].set_ylabel('0x598 B4-B5\ndrivetrain', fontsize=8)
shade(axes[4])
axes[4].legend(fontsize=7)

# Panel 5: drivetrain residual
axes[5].plot(ref_ts, drv_resid, linewidth=0.7, color='crimson', label='drv residual (measured - fit)')
axes[5].set_ylabel('drv residual', fontsize=8)
shade(axes[5])
axes[5].legend(fontsize=7)

axes[-1].set_xlabel('Time (s)', fontsize=9)
plt.tight_layout()
fig.savefig(str(OUT), dpi=150, bbox_inches='tight')
print(f"\nSaved: {OUT}")
