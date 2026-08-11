"""
plot_discharge_zoom.py

Zoomed view of the discharge limit event: t=568-658s.

6 panels:
  1. Throttle demand
  2. Motor speed           (0x5A2 B2-B3, |signed|)
  3. Torque feedback       (0x5A2 B4-B5)
  4. Drivetrain power      (I x V_pack, kW)
  5. 0x600 B4 and B5       (bit-scan candidates -- normalized, step-style)
  6. 0x589 B7 nibble       (bits 3-6 = (B7>>3)&0x0F, normalized, step-style)

Red shading: throttle > FULL_THROTTLE_THRESH AND speed > FLUX_WEAKENING_RPM
             AND power < FULL_POWER_KW (DCL-constrained region, excl. accel).
Thresholds manually set from per-second data table at t=596-609s.
"""

import sys, bisect
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"

T_MIN  = 568.0
T_MAX  = 658.0

I_SCALE = 0.04124   # A/count  (0x598)
V_SCALE = 0.015031  # V/count  (0x440 B3-B4)

# ---------- collect ---------------------------------------------------------
throttle_ts   = []
torque_ts     = []
speed_ts      = []
idrive_ts     = []
vpack_ts      = []

d_600_b4_ts   = []   # 0x600 B4  (bit-scan DCL candidate)
d_600_b5_ts   = []   # 0x600 B5  (bit-scan DCL candidate)
d_589_b7n_ts  = []   # 0x589 B7 nibble = (B7>>3)&0x0F  (bit-scan CCL+DCL candidate)

print("Parsing log...")
for frame in parse_file(str(LOG)):
    t, d, aid = frame.timestamp, frame.data, frame.arbitration_id

    if aid == 0x592 and len(d) >= 4:
        throttle_ts.append((t, d[2] | d[3] << 8))
    elif aid == 0x5A2 and len(d) >= 6:
        torque_ts.append((t, (d[4] | d[5] << 8) - 32768))
        speed_ts.append ((t, abs((d[2] | d[3] << 8) - 32768)))
    elif aid == 0x598 and len(d) >= 6:
        idrive_ts.append((t, (d[4] | d[5] << 8) - 32768))
    elif aid == 0x440 and len(d) >= 5:
        vpack_ts.append ((t, d[3] | d[4] << 8))
    elif aid == 0x600 and len(d) >= 6:
        d_600_b4_ts.append((t, d[4]))
        d_600_b5_ts.append((t, d[5]))
    elif aid == 0x589 and len(d) >= 8:
        d_589_b7n_ts.append((t, (d[7] >> 3) & 0x0F))

print(f"  0x5A2: {len(torque_ts)}  0x598: {len(idrive_ts)}  0x440: {len(vpack_ts)}")
print(f"  0x600 B4: {len(d_600_b4_ts)}  0x600 B5: {len(d_600_b5_ts)}  "
      f"0x589 B7 nibble: {len(d_589_b7n_ts)}")

# ---------- lookup helpers --------------------------------------------------
def make_lookup(ts_list):
    times = [t for t, _ in ts_list]
    vals  = [v for _, v in ts_list]
    def lookup(t_q):
        i = bisect.bisect_left(times, t_q)
        if i == 0: return vals[0]
        if i >= len(times): return vals[-1]
        return vals[i] if abs(times[i]-t_q) < abs(times[i-1]-t_q) else vals[i-1]
    return lookup

get_vpack    = make_lookup(vpack_ts)
get_throttle = make_lookup(throttle_ts)
get_speed    = make_lookup(speed_ts)

# ---------- drivetrain power (1 Hz from 0x598) ------------------------------
power_ts = []
for t, i_cts in idrive_ts:
    power_ts.append((t, i_cts * I_SCALE * get_vpack(t) * V_SCALE / 1000.0))

# ---------- highlight thresholds --------------------------------------------
FULL_THROTTLE_THRESH = 8500
FLUX_WEAKENING_RPM   = 4500
FULL_POWER_KW        = 150.0

# ---------- clip to zoom window ---------------------------------------------
def clip(ts_list):
    return [(t, v) for t, v in ts_list if T_MIN <= t <= T_MAX]

throttle_z    = clip(throttle_ts)
torque_z      = clip(torque_ts)
speed_z       = clip(speed_ts)
power_z       = clip(power_ts)

d_600_b4_z    = clip(d_600_b4_ts)
d_600_b5_z    = clip(d_600_b5_ts)
d_589_b7n_z   = clip(d_589_b7n_ts)

def unzip(data):
    if not data: return [], []
    t, v = zip(*data)
    return list(t), list(v)

def normalize(vals):
    """Scale to [0, 1] based on range within the provided list."""
    mn, mx = min(vals), max(vals)
    if mx == mn:
        return [0.5] * len(vals)
    return [(v - mn) / (mx - mn) for v in vals]

# ---------- highlight spans -------------------------------------------------
highlight_spans = []
in_span = False
span_start = None
for t, kw in power_z:
    cond = (get_throttle(t) >= FULL_THROTTLE_THRESH and
            get_speed(t)    >= FLUX_WEAKENING_RPM   and
            kw              <  FULL_POWER_KW)
    if cond and not in_span:
        span_start = t; in_span = True
    elif not cond and in_span:
        highlight_spans.append((span_start, t)); in_span = False
if in_span:
    highlight_spans.append((span_start, T_MAX))
print(f"\nHighlight spans: {highlight_spans}")

# ---------- plot ------------------------------------------------------------
fig, axes = plt.subplots(6, 1, figsize=(15, 22), sharex=True)
fig.suptitle(
    f"Discharge limit zoom  t={T_MIN:.0f}-{T_MAX:.0f}s  [bit-scan: 0x600 B4/B5 + 0x589 B7 nibble]\n"
    f"Red = full throttle + speed > {FLUX_WEAKENING_RPM} RPM + power < "
    f"{FULL_POWER_KW:.0f} kW  (DCL region; span A excluded = normal accel)",
    fontsize=11)

LIMIT_LINE = 598.0

def add_highlights(ax):
    ax.axvline(LIMIT_LINE, color='white', lw=1.2, ls='--', alpha=0.6,
               label='Limit onset (598s)')
    for t0, t1 in highlight_spans:
        ax.axvspan(t0, t1, color='red', alpha=0.22, zorder=0)

# ----- Panel 1: Throttle -----
ax = axes[0]
add_highlights(ax)
tt, vt = unzip(throttle_z)
ax.plot(tt, vt, color='deepskyblue', lw=1.0)
ax.axhline(FULL_THROTTLE_THRESH, color='deepskyblue', lw=0.8, ls=':',
           alpha=0.7, label=f'Full-throttle thresh ({FULL_THROTTLE_THRESH})')
ax.set_ylabel('Counts')
ax.set_title('Throttle demand  (0x592 B2-B3)')
ax.legend(loc='upper left', fontsize=8)
ax.grid(True, alpha=0.2)

# ----- Panel 2: Motor speed -----
ax = axes[1]
add_highlights(ax)
ts2, vs = unzip(speed_z)
ax.plot(ts2, vs, color='limegreen', lw=0.9)
ax.axhline(FLUX_WEAKENING_RPM, color='limegreen', lw=1.0, ls='--',
           alpha=0.8, label=f'Flux-weakening est. ({FLUX_WEAKENING_RPM} RPM)')
ax.set_ylabel('RPM (abs)')
ax.set_title('Motor speed  (0x5A2 B2-B3, |signed|)')
ax.legend(loc='upper left', fontsize=8)
ax.grid(True, alpha=0.2)

# ----- Panel 3: Torque feedback -----
ax = axes[2]
add_highlights(ax)
tq, vq = unzip(torque_z)
ax.plot(tq, vq, color='violet', lw=0.9)
ax.axhline(0, color='white', lw=0.5, ls='--', alpha=0.4)
ax.set_ylabel('Signed counts\n(- = regen)')
ax.set_title('Motor torque feedback  (0x5A2 B4-B5)')
ax.grid(True, alpha=0.2)

# ----- Panel 4: Drivetrain power -----
ax = axes[3]
add_highlights(ax)
tp, vp = unzip(power_z)
ax.plot(tp, vp, color='gold', lw=1.1)
ax.axhline(FULL_POWER_KW, color='red', lw=1.0, ls='--', alpha=0.8,
           label=f'Full-power thresh ({FULL_POWER_KW:.0f} kW)')
ax.axhline(0, color='white', lw=0.5, ls='--', alpha=0.4)
ax.set_ylabel('kW  (- = regen)')
ax.set_title('Drivetrain power  (I x V_pack)')
ax.legend(loc='upper left', fontsize=8)
ax.grid(True, alpha=0.2)

# ----- Panel 5: 0x600 B4 and B5 -----
ax = axes[4]
add_highlights(ax)

PANEL5 = [
    (d_600_b4_z, '0x600 B4', 'cyan'),
    (d_600_b5_z, '0x600 B5', 'orange'),
]
for data, label, color in PANEL5:
    t_s, v_s = unzip(data)
    if not v_s:
        continue
    mn, mx = min(v_s), max(v_s)
    label_full = f'{label}  [{mn}-{mx}]'
    ax.plot(t_s, normalize(v_s), color=color, lw=1.2,
            drawstyle='steps-post', label=label_full, alpha=0.88)

ax.set_ylabel('Normalized\n0=lo  1=hi')
ax.set_ylim(-0.1, 1.15)
ax.set_title('0x600 B4 and B5  (bit-scan DCL candidates, normalized)')
ax.legend(loc='upper left', fontsize=8)
ax.grid(True, alpha=0.2)

# ----- Panel 6: 0x589 B7 nibble -----
ax = axes[5]
add_highlights(ax)

t_s, v_s = unzip(d_589_b7n_z)
if v_s:
    mn, mx = min(v_s), max(v_s)
    ax.plot(t_s, normalize(v_s), color='magenta', lw=1.2,
            drawstyle='steps-post',
            label=f'0x589 B7 nibble = (B7>>3)&0x0F  [{mn}-{mx}]', alpha=0.88)

ax.set_ylabel('Normalized\n0=lo  1=hi')
ax.set_xlabel('Time (s)')
ax.set_ylim(-0.1, 1.15)
ax.set_title('0x589 B7 nibble  (bits 3-6, bit-scan CCL+DCL candidate, normalized)')
ax.legend(loc='upper left', fontsize=8)
ax.grid(True, alpha=0.2)

plt.tight_layout(rect=[0, 0, 1, 0.96])
out = Path(__file__).parent / "plot_discharge_zoom.png"
plt.savefig(out, dpi=140, bbox_inches='tight')
print(f"\nSaved: {out}")
