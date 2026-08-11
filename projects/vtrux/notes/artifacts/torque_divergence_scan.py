"""
torque_divergence_scan.py  --  DCL detection via torque/power divergence

Approach: build a reference model of expected torque (or power) given throttle
and RPM from confirmed DCL-free driving, then find frames where actual torque/
power falls significantly below the model.  The first moment of sustained
divergence is the DCL onset.  A byte scan around that onset looks for signals
that step at the limit boundary.

Section A -- Reference model (t=720-1200s, confirmed DCL-free highway)
  Low-RPM regime  (|RPM| < RPM_FW_ONSET): fit torque = a*throttle + b
  High-RPM regime (|RPM| >= RPM_FW_ONSET, flux-weakening): collect power at
    full throttle; P_ref = 85th-percentile of that distribution.

Section B -- Divergence timeseries (t=560-720s, covers merge event)
  Per 0x5A2 frame, join nearest throttle (0x592) and power (0x598+0x440):
    Low-RPM:  div_torque = model(throttle) - torque_actual        [counts]
    High-RPM: div_power  = P_ref*(throttle/10000) - power_actual  [kW]
  Only frames with throttle > THR_MIN and positive torque are evaluated.
  Divergence clamped to 0 below (i.e. negative residual = not constrained).

Section C -- Onset detection
  3s rolling median of divergence.  Find the first contiguous block where
  smoothed divergence exceeds ONSET_THRESH for >= ONSET_SECS seconds.
  Report onset time of each such block.

Section D -- Byte scan around onset
  PRE:  (t_onset - 40s, t_onset - 5s)
  POST: (t_onset, t_onset + 20s)
  Report all bytes whose mode changes between windows, ranked by |delta_mode|.
  Filters: require >= 5 frames in each window; mark BMS cluster with *.

Section E -- Plot
  4-panel: (1) throttle + RPM  (2) torque actual vs model  (3) divergence with
  onset shading  (4) top byte candidates vs time

Output: torque_divergence_scan.txt  torque_divergence_scan.png
"""

import sys, bisect
from pathlib import Path
from collections import defaultdict, Counter

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"
OUT_TXT = Path(__file__).parent / "torque_divergence_scan.txt"
OUT_PNG = Path(__file__).parent / "torque_divergence_scan.png"

# ---- model / detection parameters -------------------------------------------
T_REF_START  = 720.0    # confirmed DCL-free highway start
T_REF_END    = 1200.0   # end of reference window
T_SCAN_START = 560.0    # start of divergence scan (covers stop-sign approach)
T_SCAN_END   = 720.0    # end of scan (joins reference window)

RPM_FW_ONSET = 3500     # flux-weakening onset (RPM counts, signed abs)
THR_MIN      = 3000     # minimum throttle to evaluate (ignore coasting)
THR_FULL     = 9000     # "full throttle" threshold for P_ref characterisation

ONSET_THRESH_TQ = 300   # torque divergence threshold [counts] for onset
ONSET_THRESH_PW = 15.0  # power divergence threshold [kW] for onset
ONSET_SECS   = 2.0      # minimum sustained seconds to declare onset

I_SCALE = 0.04124       # A/count
V_SCALE = 0.015031      # V/count

lines = []
def p(s=''):
    print(s)
    lines.append(s)

# ---- collect signals in one pass --------------------------------------------
ALL_MIN = min(T_REF_START, T_SCAN_START)
ALL_MAX = max(T_REF_END, T_SCAN_END) + 5

# timeseries: (t, value)
ts_592  = []   # (t, throttle)
ts_5A2  = []   # (t, torque_signed, rpm_signed)
ts_I    = []   # (t, I_drive_counts)  -- 0x598 B4-B5
ts_V    = []   # (t, V_pack_counts)   -- 0x440 B3-B4

# byte store for onset scan: all_bytes[aid][byte_idx] = [(t, val)]
all_bytes = defaultdict(lambda: defaultdict(list))

fulllog_b6_ts  = []   # (t, nibble)     -- 0x483 B6 upper nibble, full log
fulllog_b3_ts  = []   # (t, raw)        -- 0x483 B3 raw, full log
fulllog_b4_ts  = []   # (t, raw)        -- 0x483 B4 raw, full log
fulllog_b5_ts  = []   # (t, raw)        -- 0x483 B5 raw, full log
fulllog_ccl_ts = []   # (t, ccl_10bit)  -- 0x050 CCL, full log

print("Parsing log (full scan)...")
frame_count = 0
for frame in parse_file(str(LOG)):
    t   = frame.timestamp
    d   = frame.data
    aid = frame.arbitration_id
    frame_count += 1

    if aid == 0x592 and len(d) >= 6:
        ts_592.append((t, d[2] | d[3] << 8))
    if aid == 0x5A2 and len(d) >= 6:
        torq = (d[4] | d[5] << 8) - 32768
        rpm  = (d[2] | d[3] << 8) - 32768
        ts_5A2.append((t, torq, rpm))
    if aid == 0x598 and len(d) >= 6:
        ts_I.append((t, (d[4] | d[5] << 8) - 32768))
    if aid == 0x440 and len(d) >= 5:
        ts_V.append((t, d[3] | d[4] << 8))

    if aid == 0x483 and len(d) >= 7:
        fulllog_b6_ts.append((t, (d[6] >> 4) & 0xF))
        fulllog_b3_ts.append((t, d[3]))
        fulllog_b4_ts.append((t, d[4]))
        fulllog_b5_ts.append((t, d[5]))
    if aid == 0x050 and len(d) >= 2:
        fulllog_ccl_ts.append((t, ((d[1] & 0x03) << 8) | d[0]))

    if ALL_MIN <= t <= ALL_MAX:
        for i, b in enumerate(d):
            all_bytes[aid][i].append((t, b))

    if t > ALL_MAX:
        break

print(f"  Frames: {frame_count}  0x592: {len(ts_592)}  0x5A2: {len(ts_5A2)}"
      f"  0x598: {len(ts_I)}  0x440: {len(ts_V)}")

# ---- interpolation helpers --------------------------------------------------
def make_interp(ts_list):
    ts = [x[0] for x in ts_list]
    vs = [x[1] for x in ts_list]
    def lookup(t_q):
        i = bisect.bisect_left(ts, t_q)
        if i == 0: return vs[0]
        if i >= len(ts): return vs[-1]
        return vs[i] if abs(ts[i]-t_q) < abs(ts[i-1]-t_q) else vs[i-1]
    return lookup

get_throttle = make_interp(ts_592)
get_I        = make_interp(ts_I)

V_ts = [x[0] for x in ts_V]; V_vs = [x[1] for x in ts_V]
def get_power(t_q):
    i_cts = get_I(t_q)
    v_cts = (ts_V[bisect.bisect_left(V_ts, t_q)][1]
             if V_ts and bisect.bisect_left(V_ts, t_q) < len(V_ts)
             else (V_vs[-1] if V_vs else 1))
    # nearest V
    j = bisect.bisect_left(V_ts, t_q)
    if j == 0: v_cts = V_vs[0]
    elif j >= len(V_ts): v_cts = V_vs[-1]
    else: v_cts = V_vs[j] if abs(V_ts[j]-t_q) < abs(V_ts[j-1]-t_q) else V_vs[j-1]
    return i_cts * I_SCALE * v_cts * V_SCALE / 1000.0  # kW

# ---- Section A: reference model ---------------------------------------------
ref_tq_pts = []    # (throttle, torque) for low-RPM model
ref_pw_full = []   # power_kW at full throttle, high-RPM

for t, torq, rpm in ts_5A2:
    if not (T_REF_START <= t <= T_REF_END): continue
    if torq <= 100: continue  # not motoring
    thr = get_throttle(t)
    if thr < THR_MIN: continue
    abs_rpm = abs(rpm)
    if abs_rpm < RPM_FW_ONSET:
        ref_tq_pts.append((thr, torq))
    else:
        if thr >= THR_FULL:
            pw = get_power(t)
            if pw > 0:
                ref_pw_full.append(pw)

p("=" * 68)
p("SECTION A  --  Reference model (t=720-1200s, DCL-free)")
p()

# Linear fit: torque = slope*throttle + intercept
slope_m = intercept_m = r2_m = None
if len(ref_tq_pts) >= 20:
    xs = [p2[0] for p2 in ref_tq_pts]; ys = [p2[1] for p2 in ref_tq_pts]
    mx = sum(xs)/len(xs); my = sum(ys)/len(ys)
    ssxy = sum((x-mx)*(y-my) for x,y in zip(xs, ys))
    ssxx = sum((x-mx)**2 for x in xs)
    slope_m = ssxy/ssxx if ssxx else 0
    intercept_m = my - slope_m*mx
    ss_res = sum((y-(slope_m*x+intercept_m))**2 for x,y in zip(xs,ys))
    ss_tot = sum((y-my)**2 for y in ys)
    r2_m = 1 - ss_res/ss_tot if ss_tot else 0
    p(f"  Low-RPM model (|RPM| < {RPM_FW_ONSET}):")
    p(f"    torque = {slope_m:.4f} * throttle + {intercept_m:.1f}  (R2={r2_m:.4f})")
    p(f"    Training frames: {len(ref_tq_pts)}")
else:
    p(f"  WARNING: only {len(ref_tq_pts)} low-RPM ref frames -- using Step 2 fallback")
    slope_m = 0.609; intercept_m = 10.0; r2_m = 0.957

def torque_model(thr):
    return slope_m * thr + intercept_m

# P_ref: 85th percentile of full-throttle high-RPM power in reference window
P_ref = None
if ref_pw_full:
    ref_pw_full_sorted = sorted(ref_pw_full)
    idx85 = int(0.85 * len(ref_pw_full_sorted))
    P_ref = ref_pw_full_sorted[idx85]
    p()
    p(f"  High-RPM P_ref (85th pct at throttle>={THR_FULL}): {P_ref:.1f} kW")
    p(f"  (min={min(ref_pw_full):.1f}  max={max(ref_pw_full):.1f}  n={len(ref_pw_full)})")
else:
    P_ref = 170.0   # fallback from known peak discharge
    p(f"  WARNING: no high-RPM ref frames; using fallback P_ref={P_ref:.1f} kW")

# ---- Section B: divergence timeseries ---------------------------------------
p()
p("=" * 68)
p("SECTION B  --  Divergence timeseries (t=560-720s)")
p()

# Each entry: (t, div, regime, torq_act, torq_exp_or_pexp, thr, rpm, power)
div_series = []

for t, torq, rpm in ts_5A2:
    if not (T_SCAN_START <= t <= T_SCAN_END): continue
    if torq <= 50: continue
    thr = get_throttle(t)
    if thr < THR_MIN: continue
    abs_rpm = abs(rpm)

    if abs_rpm < RPM_FW_ONSET:
        t_exp = torque_model(thr)
        div = max(0.0, t_exp - torq)   # positive = constrained
        div_series.append((t, div, 'TQ', torq, t_exp, thr, abs_rpm, None))
    else:
        pw = get_power(t)
        p_exp = P_ref * min(1.0, thr / 10000.0)
        div = max(0.0, p_exp - pw)
        div_series.append((t, div, 'PW', torq, p_exp, thr, abs_rpm, pw))

p(f"  Frames evaluated in scan window: {len(div_series)}")
if div_series:
    tq_frames = [(t,d) for t,d,r,*_ in div_series if r=='TQ']
    pw_frames = [(t,d) for t,d,r,*_ in div_series if r=='PW']
    p(f"  Low-RPM (TQ regime): {len(tq_frames)}"
      f"   High-RPM (PW regime): {len(pw_frames)}")

# ---- Section C: onset detection ---------------------------------------------
p()
p("=" * 68)
p("SECTION C  --  Onset detection (rolling 3s median > threshold)")
p()

# Build smooth divergence: for each t, rolling 3s median
# Work separately for TQ and PW regimes (different units)
# Convert PW div to normalised units: div_norm = div / ONSET_THRESH_*

norm_series = []
for entry in div_series:
    t = entry[0]; div = entry[1]; regime = entry[2]
    if regime == 'TQ':
        norm = div / ONSET_THRESH_TQ
    else:
        norm = div / ONSET_THRESH_PW
    norm_series.append((t, norm))

norm_series.sort(key=lambda x: x[0])
norm_t = [x[0] for x in norm_series]
norm_v = [x[1] for x in norm_series]

def rolling_median(ts_, vs_, window_s=3.0):
    result = []
    for i, (t, v) in enumerate(zip(ts_, vs_)):
        lo = bisect.bisect_left(ts_, t - window_s/2)
        hi = bisect.bisect_right(ts_, t + window_s/2)
        bucket = sorted(vs_[lo:hi])
        if bucket:
            n = len(bucket)
            med = bucket[n//2] if n % 2 else (bucket[n//2-1]+bucket[n//2])/2
        else:
            med = v
        result.append(med)
    return result

smooth_v = rolling_median(norm_t, norm_v, window_s=3.0)

# Detect spans where smooth > 1.0 (i.e. above threshold) for >= ONSET_SECS
constrained_spans = []
in_span = False; span_start = None
for i, (t, sn) in enumerate(zip(norm_t, smooth_v)):
    if sn >= 1.0 and not in_span:
        in_span = True; span_start = t
    elif sn < 1.0 and in_span:
        span_end = norm_t[i-1]
        if span_end - span_start >= ONSET_SECS:
            constrained_spans.append((span_start, span_end))
        in_span = False
if in_span and (norm_t[-1] - span_start >= ONSET_SECS):
    constrained_spans.append((span_start, norm_t[-1]))

if constrained_spans:
    p(f"  {len(constrained_spans)} constrained span(s) detected:")
    for i, (t0, t1) in enumerate(constrained_spans):
        # Report first div value in span
        span_entries = [e for e in div_series if t0 <= e[0] <= t1]
        max_div_entry = max(span_entries, key=lambda x: x[1]) if span_entries else None
        regime = max_div_entry[2] if max_div_entry else '?'
        max_div = max_div_entry[1] if max_div_entry else 0
        p(f"    Span {i+1}: t={t0:.1f}s -- t={t1:.1f}s  (dur={t1-t0:.1f}s)"
          f"  regime={regime}  peak_div={max_div:.0f}"
          f"  {'counts' if regime=='TQ' else 'kW'}")
else:
    p("  No sustained constrained spans detected above threshold.")
    p(f"  (TQ threshold={ONSET_THRESH_TQ} counts, PW threshold={ONSET_THRESH_PW} kW,"
      f" min duration={ONSET_SECS}s)")
    # Still show where divergence is highest
    if div_series:
        top = sorted(div_series, key=lambda x: -x[1])[:5]
        p()
        p("  Top 5 divergence frames:")
        for t, div, regime, torq, exp, thr, rpm, pw in top:
            p(f"    t={t:.1f}s  div={div:.1f}  regime={regime}"
              f"  throttle={thr:.0f}  rpm={rpm:.0f}  torq={torq:.0f}"
              f"  exp={exp:.1f}  {'power='+f'{pw:.1f}kW' if pw is not None else ''}")

# ---- Section D: byte scan around onset(s) -----------------------------------
p()
p("=" * 68)
p("SECTION D  --  Byte scan around each onset")
p()

def mode_of(vals):
    return Counter(vals).most_common(1)[0][0] if vals else None

def bms(aid):
    return '*' if 0x400 <= aid <= 0x507 else ' '

if not constrained_spans:
    # Fall back to the manually confirmed span from Step 4
    p("  No auto-detected spans; using manually confirmed t=614-622s as POST window.")
    constrained_spans = [(614.0, 622.0)]
    scan_pairs = [(614.0, 574.0, 609.0, 614.0, 634.0)]  # (onset, pre_lo, pre_hi, post_lo, post_hi)
else:
    scan_pairs = []

for span_start, span_end in constrained_spans:
    t_onset = span_start
    pre_lo  = t_onset - 40.0
    pre_hi  = t_onset - 5.0
    post_lo = t_onset
    post_hi = t_onset + 20.0

    p(f"--- Onset at t={t_onset:.1f}s ---")
    p(f"  PRE:  t={pre_lo:.0f}-{pre_hi:.0f}s    POST: t={post_lo:.0f}-{post_hi:.0f}s")
    p()

    pre_vals  = defaultdict(list)
    post_vals = defaultdict(list)
    for aid in all_bytes:
        for bi in all_bytes[aid]:
            for t_f, val in all_bytes[aid][bi]:
                if pre_lo <= t_f <= pre_hi:
                    pre_vals[(aid, bi)].append(val)
                if post_lo <= t_f <= post_hi:
                    post_vals[(aid, bi)].append(val)

    common = set(pre_vals.keys()) & set(post_vals.keys())
    changed = []
    for key in sorted(common):
        pv = pre_vals[key]; pov = post_vals[key]
        if len(pv) < 5 or len(pov) < 5: continue
        pm = mode_of(pv); dm = mode_of(pov)
        if pm == dm: continue
        aid, bi = key
        changed.append((aid, bi, pm, dm, abs(dm-pm), len(pv), len(pov),
                        len(set(pv)), len(set(pov))))

    changed.sort(key=lambda x: -x[4])

    hdr = (f"{'F':1} {'ID':>8}  {'B':>2}  {'pre_mode':>9}  {'post_mode':>9}  "
           f"{'delta':>7}  {'pre_uq':>6}  {'post_uq':>6}  {'n_pre':>5}  {'n_post':>5}")
    p(hdr); p("-" * len(hdr))
    for aid, bi, pm, dm, delta, npre, npost, puq, duq in changed[:50]:
        p(f"{bms(aid)} 0x{aid:06X}  B{bi}  {pm:>9}  {dm:>9}  "
          f"{dm-pm:>+7}  {puq:>6}  {duq:>6}  {npre:>5}  {npost:>5}")
    if not changed:
        p("  (no bytes changed mode between PRE and POST windows)")
    p()

# ---- Section E: plot --------------------------------------------------------
PLOT_XMIN = 300.0
PLOT_XMAX = 730.0

fig, axes = plt.subplots(6, 1, figsize=(16, 22), sharex=True)
fig.suptitle("Torque Divergence Scan -- vtruxcurrentlimitingtest.log"
             f"  t={PLOT_XMIN:.0f}-{PLOT_XMAX:.0f}s", fontsize=11)

scan_t5a2   = [(t, torq, rpm) for t, torq, rpm in ts_5A2
               if PLOT_XMIN <= t <= PLOT_XMAX]
scan_t_arr  = [x[0] for x in scan_t5a2]
scan_tq_arr = [x[1] for x in scan_t5a2]
scan_rp_arr = [abs(x[2]) for x in scan_t5a2]

scan_592 = [(t, v) for t, v in ts_592 if PLOT_XMIN <= t <= PLOT_XMAX]

# Drivetrain power timeseries (0x598 rate ~1 Hz)
scan_power_pts = [(t, get_power(t)) for t, _ in ts_I
                  if PLOT_XMIN <= t <= PLOT_XMAX]

# Panel 1: throttle + RPM
ax = axes[0]
if scan_592:
    t592 = [x[0] for x in scan_592]; v592 = [x[1] for x in scan_592]
    ax.plot(t592, v592, color='steelblue', lw=0.8, label='Throttle (0x592)')
ax2_0 = ax.twinx()
if scan_t5a2:
    ax2_0.plot(scan_t_arr, scan_rp_arr, color='orange', lw=0.8, alpha=0.7,
               label='|RPM| (0x5A2)')
    ax2_0.axhline(RPM_FW_ONSET, color='red', lw=0.7, ls='--',
                  label=f'FW onset ({RPM_FW_ONSET})')
ax.set_ylabel('Throttle (counts)', color='steelblue')
ax2_0.set_ylabel('|RPM|', color='orange')
ax.set_title('Throttle demand + motor RPM')
ax.grid(True, alpha=0.2)
lines0, labels0 = ax.get_legend_handles_labels()
lines1, labels1 = ax2_0.get_legend_handles_labels()
ax.legend(lines0+lines1, labels0+labels1, fontsize=7, loc='upper left')

# Panel 2: actual torque vs model torque
ax = axes[1]
if scan_t5a2:
    ax.plot(scan_t_arr, scan_tq_arr, color='royalblue', lw=0.7, alpha=0.8,
            label='Torque actual')
    thr_at_scan = [get_throttle(t) for t in scan_t_arr]
    tq_model_at_scan = [torque_model(th) if abs(scan_rp_arr[i]) < RPM_FW_ONSET
                        else None for i, th in enumerate(thr_at_scan)]
    model_t = [scan_t_arr[i] for i in range(len(scan_t_arr))
               if tq_model_at_scan[i] is not None]
    model_v = [tq_model_at_scan[i] for i in range(len(tq_model_at_scan))
               if tq_model_at_scan[i] is not None]
    if model_t:
        ax.plot(model_t, model_v, color='limegreen', lw=0.8, ls='--',
                alpha=0.8, label='Torque model (RPM<3500)')
ax.set_ylabel('Torque (counts)')
ax.set_title('Actual torque vs model (low-RPM) -- gap = constraint')
ax.grid(True, alpha=0.2)
ax.legend(fontsize=7, loc='upper left')

# Panel 3: drivetrain power + 0x050 limits (right axis)
ax = axes[2]
if scan_power_pts:
    tp = [x[0] for x in scan_power_pts]; pp = [x[1] for x in scan_power_pts]
    ax.plot(tp, pp, color='darkorange', lw=1.2, marker='o', ms=3,
            label='Drivetrain power (kW)')
    ax.axhline(P_ref, color='green', lw=0.8, ls='--',
               label=f'P_ref={P_ref:.0f} kW')
    ax.axhline(0, color='black', lw=0.5, ls=':')
ax.set_ylabel('Power (kW)')
ax.set_title('Drivetrain power + 0x050 CCL (right axis)')
ax.grid(True, alpha=0.2)
ax3r = ax.twinx()
if fulllog_ccl_ts:
    ccl3_t = [x[0] for x in fulllog_ccl_ts if PLOT_XMIN <= x[0] <= PLOT_XMAX]
    ccl3_v = [x[1] for x in fulllog_ccl_ts if PLOT_XMIN <= x[0] <= PLOT_XMAX]
    ax3r.step(ccl3_t, ccl3_v, where='post', color='royalblue', lw=0.8, alpha=0.85,
              label='0x050 CCL (10-bit)')
ax3r.set_ylabel('CCL (counts)', color='royalblue')
lines3l, labels3l = ax.get_legend_handles_labels()
lines3r, labels3r = ax3r.get_legend_handles_labels()
ax.legend(lines3l + lines3r, labels3l + labels3r, fontsize=7, loc='upper left')

# Panel 4: divergence (normalised)
ax = axes[3]
if norm_t:
    ax.plot(norm_t, norm_v, color='gray', lw=0.5, alpha=0.6, label='Raw div (norm)')
    ax.plot(norm_t, smooth_v, color='crimson', lw=1.2, label='3s smooth')
    ax.axhline(1.0, color='black', lw=0.8, ls='--', label='Onset threshold')
for sp_start, sp_end in constrained_spans:
    ax.axvspan(sp_start, sp_end, color='red', alpha=0.15)
ax.set_ylabel('Divergence (normalised)')
ax.set_title(f'Divergence: TQ threshold={ONSET_THRESH_TQ} cts, '
             f'PW threshold={ONSET_THRESH_PW} kW')
ax.grid(True, alpha=0.2)
ax.legend(fontsize=7, loc='upper left')

# ---- Drop scan: signals that DECREASE at the DCL onset (~t=610s) -------------
# Real onset is ~610s: before that, throttle goes 0->2500->10000 with no torque
# response, confirming DCL already active.  Span 1 at t=593s is a model artefact
# (stop-sign deceleration), not the true onset.
# PRE  = t=580-600s  (pre-stop-sign driving, no DCL)
# POST = t=608-625s  (DCL active: gap + confirmed span 2)
DROP_PRE_LO  = 580.0; DROP_PRE_HI  = 600.0
DROP_POST_LO = 608.0; DROP_POST_HI = 625.0

pre_drop  = defaultdict(list)
post_drop = defaultdict(list)
for aid in all_bytes:
    for bi in all_bytes[aid]:
        for t_f, val in all_bytes[aid][bi]:
            if DROP_PRE_LO  <= t_f <= DROP_PRE_HI:  pre_drop[(aid, bi)].append(val)
            if DROP_POST_LO <= t_f <= DROP_POST_HI: post_drop[(aid, bi)].append(val)

drops = []
for key in sorted(set(pre_drop.keys()) & set(post_drop.keys())):
    pv = pre_drop[key]; dv = post_drop[key]
    if len(pv) < 3 or len(dv) < 3: continue
    pm = mode_of(pv); dm = mode_of(dv)
    if dm >= pm: continue   # only drops
    aid, bi = key
    drops.append((aid, bi, pm, dm, pm - dm, len(set(pv)), len(set(dv)),
                  len(pv), len(dv)))
drops.sort(key=lambda x: (-x[4], x[5]))  # largest drop first

p()
p("=" * 68)
p("SECTION D2  --  Drop scan: pre-stop (580-600s) vs DCL-active (608-625s)")
p("  Signals whose mode DECREASES at the ~610s DCL onset.")
p()
hdr_d2 = (f"{'F':1} {'ID':>8}  {'B':>2}  {'pre_mode':>9}  {'dcl_mode':>9}  "
          f"{'drop':>6}  {'pre_uq':>6}  {'dcl_uq':>6}  {'n_pre':>5}  {'n_dcl':>5}")
p(hdr_d2); p("-" * len(hdr_d2))
for aid, bi, pm, dm, drop, puq, duq, npre, ndv in drops[:50]:
    p(f"{bms(aid)} 0x{aid:06X}  B{bi}  {pm:>9}  {dm:>9}  "
      f"{-drop:>+6}  {puq:>6}  {duq:>6}  {npre:>5}  {ndv:>5}")
if not drops:
    p("  (no bytes decreased)")
p()

# Panel 5: top drop candidates (BMS-first, lowest unique count, 0x460 excluded)
ax = axes[4]
ax.set_title('Top DROP candidates near DCL onset ~t=610s  (BMS preferred, 0x460 excluded)')
ax.set_ylabel('Byte value')
ax.grid(True, alpha=0.2)

PLOT_EXCLUDE = {0x460}
top_aids = []
drop_cand = []
for aid, bi, pm, dm, drop, puq, duq, npre, ndv in drops:
    if aid in PLOT_EXCLUDE: continue
    is_bms = 1 if 0x400 <= aid <= 0x507 else 0
    drop_cand.append((is_bms, -max(puq, duq), drop, aid, bi))
drop_cand.sort(reverse=True)
top_aids = [(aid, bi) for _, _, _, aid, bi in drop_cand[:4]]

colors_top = ['darkorange', 'mediumpurple', 'teal', 'steelblue']
for ci, (aid, bi) in enumerate(top_aids):
    tv = sorted(all_bytes[aid][bi])
    ts_ = [x[0] for x in tv if T_SCAN_START <= x[0] <= T_SCAN_END]
    vs_ = [x[1] for x in tv if T_SCAN_START <= x[0] <= T_SCAN_END]
    if ts_:
        ax.plot(ts_, vs_, lw=1.0, color=colors_top[ci],
                label=f'0x{aid:X} B{bi}{" *" if 0x400<=aid<=0x507 else ""}')

if not top_aids:
    ax.text(0.5, 0.5, '(no drop candidates found)', transform=ax.transAxes,
            ha='center', va='center', fontsize=9, color='gray')
else:
    ax.legend(fontsize=7, loc='upper left')

# Panel 6: 0x483 all interesting bytes + 0x050 CCL -- full log view
ax = axes[5]
ax.set_title('0x483 bytes (left) + 0x050 CCL (right) -- B6 nibble *16 to rescale; '
             'CCL period shaded blue')
ax.set_ylabel('0x483 byte values (B6 nibble *16)')
ax.axvspan(345, 365, color='royalblue', alpha=0.15, label='CCL period (~345-365s)')
if fulllog_b6_ts:
    b6_t = [x[0] for x in fulllog_b6_ts]
    b6_v = [x[1] * 16 for x in fulllog_b6_ts]   # scale nibble 0-15 -> 0-240
    ax.step(b6_t, b6_v, where='post', color='darkorange', lw=1.4,
            label='B6 nibble*16 (DCL level)')
if fulllog_b3_ts:
    b3_t = [x[0] for x in fulllog_b3_ts]
    b3_v = [x[1]   for x in fulllog_b3_ts]
    ax.step(b3_t, b3_v, where='post', color='seagreen', lw=0.9, alpha=0.8,
            label='B3 raw')
if fulllog_b4_ts:
    b4_t = [x[0] for x in fulllog_b4_ts]
    b4_v = [x[1]   for x in fulllog_b4_ts]
    ax.step(b4_t, b4_v, where='post', color='mediumpurple', lw=0.9, alpha=0.8,
            label='B4 raw')
if fulllog_b5_ts:
    b5_t = [x[0] for x in fulllog_b5_ts]
    b5_v = [x[1]   for x in fulllog_b5_ts]
    ax.step(b5_t, b5_v, where='post', color='crimson', lw=0.9, alpha=0.8,
            label='B5 raw')
ax6r = ax.twinx()
if fulllog_ccl_ts:
    ccl_t = [x[0] for x in fulllog_ccl_ts]
    ccl_v = [x[1] for x in fulllog_ccl_ts]
    ax6r.step(ccl_t, ccl_v, where='post', color='royalblue', lw=0.8, alpha=0.8,
              label='0x050 CCL (10-bit)')
ax6r.set_ylabel('CCL (counts)', color='royalblue')
lines6l, labels6l = ax.get_legend_handles_labels()
lines6r, labels6r = ax6r.get_legend_handles_labels()
ax.legend(lines6l + lines6r, labels6l + labels6r, fontsize=7, loc='upper right')
ax.grid(True, alpha=0.2)

# Mark constrained spans + set xlim on all panels
for ax_ in axes:
    for sp_start, sp_end in constrained_spans:
        ax_.axvspan(sp_start, sp_end, color='red', alpha=0.08)
    ax_.set_xlim(PLOT_XMIN, PLOT_XMAX)

axes[-1].set_xlabel('Time (s)')
plt.tight_layout()
plt.savefig(OUT_PNG, dpi=140, bbox_inches='tight')
p(f"Plot saved: {OUT_PNG.name}")

# ---- save text output --------------------------------------------------------
OUT_TXT.write_text('\n'.join(lines), encoding='utf-8')
print(f"Saved: {OUT_TXT}")
