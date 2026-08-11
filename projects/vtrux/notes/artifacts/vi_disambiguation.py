"""
Voltage/power/current disambiguation for Vtrux powertrain signals.

Analysis A1: Charging log -- identify 0x598 channel roles (battery/generator/drivetrain)
             by comparing mean, stddev, and r vs confirmed battery current (0x639).

Analysis A2: Highway log -- disambiguate power vs current in 0x597 and 0x598
             by computing P_batt = V \xd7 I and comparing each candidate against both.

Analysis B:  Highway + charging logs -- test whether 0x420 B3/B4 track intI dt
             (coulomb counter hypothesis).
"""

import sys
import math
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from canre.parsers.autodetect import parse_file

# \u2500\u2500 Log paths \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

LOGS_DIR   = PROJECT_ROOT / "projects" / "vtrux" / "logs"
CHARGE_LOG = LOGS_DIR / "full charge then fail.log"
DRIVE_LOG  = LOGS_DIR / "debuglog_M0.log"

# \u2500\u2500 Extraction helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def u16_le(data, byte_start):
    if len(data) < byte_start + 2:
        return None
    return data[byte_start] | (data[byte_start + 1] << 8)

def u16_be(data, byte_start):
    if len(data) < byte_start + 2:
        return None
    return (data[byte_start] << 8) | data[byte_start + 1]

def s16_le(data, byte_start):
    v = u16_le(data, byte_start)
    return None if v is None else (v - 0x10000 if v >= 0x8000 else v)

# \u2500\u2500 Statistics helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def pearson_r(xs, ys):
    n = len(xs)
    if n < 10:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / n)
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / n)
    if sx == 0 or sy == 0:
        return None
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / n
    return cov / (sx * sy)

def mean_std(vals):
    n = len(vals)
    if n == 0:
        return None, None
    m = sum(vals) / n
    s = math.sqrt(sum((v - m) ** 2 for v in vals) / n)
    return m, s

def trapz(ts_vals):
    """Trapezoidal integration of a sorted (t, y) list. Returns total area."""
    total = 0.0
    for i in range(1, len(ts_vals)):
        dt = ts_vals[i][0] - ts_vals[i - 1][0]
        avg = (ts_vals[i][1] + ts_vals[i - 1][1]) / 2.0
        total += avg * dt
    return total

# \u2500\u2500 Interpolation helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def resample(ts_vals, t_start, t_end, hz=10):
    """
    Linearly interpolate a sorted (t, y) list onto a uniform grid from
    t_start to t_end at the given sample rate.  Returns [(t, y), ...].
    Only emits grid points inside the data's actual span.
    """
    if not ts_vals:
        return []
    n_pts = int((t_end - t_start) * hz) + 1
    result = []
    j = 0
    for i in range(n_pts):
        t = t_start + i / hz
        if t < ts_vals[0][0] or t > ts_vals[-1][0]:
            continue
        # Advance bracket pointer (monotone scan -- valid because t increases)
        while j + 1 < len(ts_vals) - 1 and ts_vals[j + 1][0] <= t:
            j += 1
        if j + 1 >= len(ts_vals):
            result.append((t, ts_vals[-1][1]))
        else:
            t0, y0 = ts_vals[j]
            t1, y1 = ts_vals[j + 1]
            frac = (t - t0) / (t1 - t0) if t1 != t0 else 0.0
            result.append((t, y0 + frac * (y1 - y0)))
    return result

def nearest_lookup(ts_sorted, t, max_dt=0.2):
    """Binary-search nearest sample within max_dt. ts_sorted = sorted (t, v) list."""
    if not ts_sorted:
        return None
    lo, hi = 0, len(ts_sorted) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if ts_sorted[mid][0] < t:
            lo = mid + 1
        else:
            hi = mid
    best = lo
    if best > 0 and abs(ts_sorted[best - 1][0] - t) < abs(ts_sorted[best][0] - t):
        best -= 1
    if abs(ts_sorted[best][0] - t) <= max_dt:
        return ts_sorted[best][1]
    return None

# \u2500\u2500 Analysis A1: Channel Role Identification (charging log) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def analysis_a1():
    print("=" * 65)
    print("=== Analysis A1: Channel Role Identification (charging log) ===")
    print(f"    Log: {CHARGE_LOG.name}")
    print()

    i639_ts = []   # (t, amps)  -- confirmed battery current reference
    s597_ts = []   # (t, raw centred)
    s598a_ts = []  # 0x598 B0-B1
    s598b_ts = []  # 0x598 B2-B3
    s598c_ts = []  # 0x598 B4-B5

    t_first = None
    for frame in parse_file(str(CHARGE_LOG)):
        t = frame.timestamp
        if t_first is None:
            t_first = t
        if t - t_first < 60:
            continue  # skip first 60 s startup transient

        d   = frame.data
        aid = frame.arbitration_id

        if aid == 0x639:
            raw = u16_be(d, 5)
            if raw is not None:
                i639_ts.append((t, (raw - 32768) * 0.1))

        elif aid == 0x597:
            raw = u16_le(d, 1)
            if raw is not None:
                s597_ts.append((t, raw - 32768))

        elif aid == 0x598:
            ra = u16_le(d, 0)
            rb = u16_le(d, 2)
            rc = u16_le(d, 4)
            if ra is not None:
                s598a_ts.append((t, ra - 32768))
            if rb is not None:
                s598b_ts.append((t, rb - 32768))
            if rc is not None:
                s598c_ts.append((t, rc - 32768))

    print(f"  Samples collected (after 60 s skip):")
    print(f"    0x639 B5-B6  : {len(i639_ts)}")
    print(f"    0x597 B1-B2  : {len(s597_ts)}")
    print(f"    0x598 B0-B1  : {len(s598a_ts)}")
    print(f"    0x598 B2-B3  : {len(s598b_ts)}")
    print(f"    0x598 B4-B5  : {len(s598c_ts)}")
    print()

    if not i639_ts:
        print("  ERROR: No 0x639 samples -- cannot compute correlations.")
        return

    i639_sorted = sorted(i639_ts)

    rows = []
    for label, sig_ts in [
        ("0x597 B1-B2",  s597_ts),
        ("0x598 B0-B1",  s598a_ts),
        ("0x598 B2-B3",  s598b_ts),
        ("0x598 B4-B5",  s598c_ts),
    ]:
        if not sig_ts:
            rows.append((label, None, None, None))
            continue
        paired_ref, paired_sig = [], []
        for t, v in sig_ts:
            ref = nearest_lookup(i639_sorted, t)
            if ref is not None:
                paired_ref.append(ref)
                paired_sig.append(v)
        if len(paired_sig) < 10:
            rows.append((label, None, None, None))
            continue
        m, s = mean_std(paired_sig)
        r = pearson_r(paired_ref, paired_sig)
        rows.append((label, m, s, r))

    # Assign roles: lowest stddev \u2192 drivetrain; highest |r| among remaining \u2192 battery
    stds = [(row[0], row[2]) for row in rows if row[2] is not None]
    if stds:
        drv_label = min(stds, key=lambda x: x[1])[0]
        remaining = [row for row in rows if row[0] != drv_label and row[3] is not None]
        batt_label = max(remaining, key=lambda row: abs(row[3]))[0] if remaining else None
    else:
        drv_label = batt_label = None

    print(f"  {'Signal':<22}  {'mean':>10}  {'stddev':>8}  {'r vs 0x639':>12}  Role")
    print("  " + "-" * 70)
    for label, m, s, r in rows:
        if m is None:
            print(f"  {label:<22}  N/A -- no paired samples")
            continue
        r_str = f"{r:+.4f}" if r is not None else "   N/A"
        if label == drv_label:
            role = "drivetrain (lowest stddev)"
        elif label == batt_label:
            role = "battery (highest |r|)"
        else:
            role = "generator"
        print(f"  {label:<22}  {m:>10.1f}  {s:>8.1f}  {r_str:>12}  {role}")
    print()

# \u2500\u2500 Analysis A2: Power vs Current Disambiguation (highway log) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def analysis_a2():
    print("=" * 65)
    print("=== Analysis A2: Power vs Current Disambiguation (highway log) ===")
    print(f"    Log: {DRIVE_LOG.name}")
    print()

    ts = defaultdict(list)

    for frame in parse_file(str(DRIVE_LOG)):
        t   = frame.timestamp
        d   = frame.data
        aid = frame.arbitration_id

        if aid == 0x18FFD6B3:
            v = s16_le(d, 4)
            if v is not None:
                ts['hv_v'].append((t, v * 0.05))

        elif aid == 0x639:
            raw = u16_be(d, 5)
            if raw is not None:
                ts['i639'].append((t, (raw - 32768) * 0.1))

        elif aid == 0x592:
            raw = u16_le(d, 0)
            if raw is not None:
                ts['i592'].append((t, raw - 32768))

        elif aid == 0x597:
            raw = u16_le(d, 1)
            if raw is not None:
                ts['s597'].append((t, raw - 32768))

        elif aid == 0x598:
            ra = u16_le(d, 0)
            rb = u16_le(d, 2)
            rc = u16_le(d, 4)
            if ra is not None:
                ts['s598a'].append((t, ra - 32768))
            if rb is not None:
                ts['s598b'].append((t, rb - 32768))
            if rc is not None:
                ts['s598c'].append((t, rc - 32768))

    for k in ts:
        ts[k].sort()

    print("  Samples collected:")
    for k, v in sorted(ts.items()):
        print(f"    {k:<10}: {len(v)}")
    print()

    if not ts['hv_v'] or not ts['i639']:
        print("  ERROR: Missing reference signals (hv_v or i639).")
        return

    # Common window: intersection of both reference timespans
    t_start = max(ts['hv_v'][0][0], ts['i639'][0][0])
    t_end   = min(ts['hv_v'][-1][0], ts['i639'][-1][0])
    span    = t_end - t_start
    print(f"  Common window: {span:.1f} s  [{t_start:.2f} - {t_end:.2f}]")

    # Resample references to 10 Hz common grid
    hv_grid   = resample(ts['hv_v'],  t_start, t_end, hz=10)
    i639_grid = resample(ts['i639'], t_start, t_end, hz=10)
    n         = min(len(hv_grid), len(i639_grid))
    hv_grid   = hv_grid[:n]
    i639_grid = i639_grid[:n]

    hv_vals   = [x[1] for x in hv_grid]
    i639_vals = [x[1] for x in i639_grid]

    # Filter to HV-active periods only (contactors closed, excludes startup/idle).
    # Without this filter, V spans 0-410V while I varies only ~5A, making
    # P_batt ~ k*V and all candidates falsely appear as POWER.
    HV_MIN = 300.0
    active_idx = [i for i in range(n) if hv_vals[i] >= HV_MIN]
    if len(active_idx) < 50:
        print(f"  WARNING: only {len(active_idx)} samples with V >= {HV_MIN} V; "
              f"using full window.")
        active_idx = list(range(n))

    hv_active   = [hv_vals[i]   for i in active_idx]
    i639_active = [i639_vals[i] for i in active_idx]
    p_batt      = [hv_active[k] * i639_active[k] for k in range(len(active_idx))]

    print(f"  HV-active samples: {len(active_idx)} of {n} (V >= {HV_MIN} V)")
    print(f"  HV voltage (active):  {min(hv_active):.1f} - {max(hv_active):.1f} V  "
          f"(spread {max(hv_active) - min(hv_active):.1f} V)")
    print(f"  I_639 (active):       {min(i639_active):.1f} - {max(i639_active):.1f} A  "
          f"(spread {max(i639_active) - min(i639_active):.1f} A)")
    print(f"  P_batt (active):      {min(p_batt):.0f} - {max(p_batt):.0f} W")
    print()

    # Sanity check (use full grid, not filtered, since we just need r(592,639))
    if ts['i592']:
        i592_grid = resample(ts['i592'], t_start, t_end, hz=10)[:n]
        i592_vals_act = [i592_grid[i][1] for i in active_idx if i < len(i592_grid)]
        r_sanity = pearson_r(i639_active[:len(i592_vals_act)], i592_vals_act)
        print(f"  Sanity: r(0x592 B0-B1, 0x639 B5-B6) = "
              f"{r_sanity:+.4f}  (expect ~0.99)")
    else:
        print("  Sanity: 0x592 not found in log")
    print()

    print(f"  {'Signal':<24}  {'r vs I_639':>12}  {'r vs P_batt':>12}  Conclusion")
    print("  " + "-" * 68)

    n_act = len(active_idx)
    for label, key in [
        ("0x597 B1-B2",       's597'),
        ("0x598 B0-B1 (A)",   's598a'),
        ("0x598 B2-B3 (B)",   's598b'),
        ("0x598 B4-B5 (C)",   's598c'),
    ]:
        if not ts[key]:
            print(f"  {label:<24}  N/A - not in log")
            continue
        sig_grid = resample(ts[key], t_start, t_end, hz=10)
        # Pull active-window subset
        sig_active = [sig_grid[i][1] for i in active_idx if i < len(sig_grid)]
        if len(sig_active) < 50:
            print(f"  {label:<24}  too few active samples ({len(sig_active)})")
            continue
        m = min(len(sig_active), n_act)
        r_i = pearson_r(i639_active[:m], sig_active[:m])
        r_p = pearson_r(p_batt[:m],      sig_active[:m])
        ri_s = f"{r_i:+.4f}" if r_i is not None else "   N/A"
        rp_s = f"{r_p:+.4f}" if r_p is not None else "   N/A"
        if r_i is not None and r_p is not None:
            conclusion = "POWER" if abs(r_p) > abs(r_i) else "CURRENT"
        else:
            conclusion = "?"
        print(f"  {label:<24}  {ri_s:>12}  {rp_s:>12}  {conclusion}")
    print()

# -- Analysis A2b: Power vs Current Disambiguation (charging log, charger GT) --

def analysis_a2b():
    """
    Use the charging log with charger DC voltage + current ground truth
    (0x18FFD7C0) to separate power from current in 0x597 and 0x598.

    During AC charging the EVSE limits input AC current, so DC output power
    is roughly constant while DC voltage slowly rises and DC current drifts
    slightly downward (I = P/V).  Near end-of-charge the charger enters CV
    and current tapers noticeably.

    Across the full session P and I diverge enough to discriminate:
      - signal tracking I_charger  -> current
      - signal tracking P_charger  -> power
    """
    print("=" * 65)
    print("=== Analysis A2b: Power vs Current (charging log, charger GT) ===")
    print(f"    Log: {CHARGE_LOG.name}")
    print()

    # Charger GT: 0x18FFD7C0
    #   B0-B1 LE signed * 0.05 -> DC voltage (V)
    #   B2-B3 LE signed * 0.05 -> DC current (A)
    CHARGER_ID = 0x18FFD7C0
    V_MIN_FILTER = 350.0   # exclude pre-charge startup
    T_MAX        = 7242.0  # exclude voltage-collapse failure event (per context-voltage-current.md)

    ts = defaultdict(list)

    for frame in parse_file(str(CHARGE_LOG)):
        t   = frame.timestamp
        d   = frame.data
        aid = frame.arbitration_id

        if aid == CHARGER_ID:
            vraw = s16_le(d, 0)
            iraw = s16_le(d, 2)
            if vraw is not None:
                ts['chr_v'].append((t, vraw * 0.05))
            if iraw is not None:
                ts['chr_i'].append((t, iraw * 0.05))

        elif aid == 0x597:
            raw = u16_le(d, 1)
            if raw is not None:
                ts['s597'].append((t, raw - 32768))

        elif aid == 0x598:
            ra = u16_le(d, 0)
            rb = u16_le(d, 2)
            rc = u16_le(d, 4)
            if ra is not None:
                ts['s598a'].append((t, ra - 32768))
            if rb is not None:
                ts['s598b'].append((t, rb - 32768))
            if rc is not None:
                ts['s598c'].append((t, rc - 32768))

    for k in ts:
        ts[k].sort()

    print("  Samples collected:")
    for k, v in sorted(ts.items()):
        print(f"    {k:<10}: {len(v)}")
    print()

    if not ts['chr_v'] or not ts['chr_i']:
        print("  ERROR: No charger GT found in log.")
        return

    # Common window over both charger channels
    t_start = max(ts['chr_v'][0][0], ts['chr_i'][0][0])
    t_end   = min(ts['chr_v'][-1][0], ts['chr_i'][-1][0])

    # Resample charger V and I to 2 Hz grid (charger GT rate is low)
    HZ = 2
    chr_v_grid = resample(ts['chr_v'], t_start, t_end, hz=HZ)
    chr_i_grid = resample(ts['chr_i'], t_start, t_end, hz=HZ)
    n = min(len(chr_v_grid), len(chr_i_grid))
    chr_v_grid = chr_v_grid[:n]
    chr_i_grid = chr_i_grid[:n]

    # Filter: V > V_MIN (exclude pre-charge) AND t <= T_MAX (exclude failure event)
    # Also require I < 0 (charging direction only; positive I = backfeed during fault)
    active_idx = [
        i for i in range(n)
        if chr_v_grid[i][1] >= V_MIN_FILTER
        and chr_v_grid[i][0] <= T_MAX
        and chr_i_grid[i][1] < 0
    ]

    # CC-phase subset: samples where I is within 15% of the peak (most negative) value.
    # In this window V varies while I is roughly flat, cleanly separating power from current.
    i_vals_all = [chr_i_grid[i][1] for i in active_idx]
    i_peak     = min(i_vals_all)          # most negative = highest charge current
    i_cc_thresh = i_peak * (1 - 0.15)    # 15% above peak (less negative threshold)
    cc_idx = [active_idx[k] for k, iv in enumerate(i_vals_all) if iv <= i_cc_thresh]
    if len(active_idx) < 50:
        print(f"  WARNING: only {len(active_idx)} samples with V >= {V_MIN_FILTER} V")
        active_idx = list(range(n))

    v_act = [chr_v_grid[i][1] for i in active_idx]
    i_act = [chr_i_grid[i][1] for i in active_idx]
    p_act = [v_act[k] * i_act[k] for k in range(len(active_idx))]

    v_cc  = [chr_v_grid[i][1] for i in cc_idx]
    i_cc  = [chr_i_grid[i][1] for i in cc_idx]
    p_cc  = [v_cc[k] * i_cc[k] for k in range(len(cc_idx))]

    r_vi_full = pearson_r(v_act, i_act)
    r_vi_cc   = pearson_r(v_cc, i_cc) if cc_idx else None

    print(f"  Full active window (V >= {V_MIN_FILTER} V, t <= {T_MAX} s, I < 0):")
    print(f"    Samples : {len(active_idx)}")
    print(f"    V range : {min(v_act):.1f} - {max(v_act):.1f} V  (spread {max(v_act)-min(v_act):.1f} V)")
    print(f"    I range : {min(i_act):.1f} - {max(i_act):.1f} A  (spread {max(i_act)-min(i_act):.1f} A)")
    print(f"    P range : {min(p_act):.0f} - {max(p_act):.0f} W  (spread {max(p_act)-min(p_act):.0f} W)")
    print(f"    r(V, I) : {r_vi_full:+.4f}  (near +1 = taper-dominated; near -1 = CC-dominated)")
    print()
    print(f"  CC-phase window (I within 15% of peak {i_peak:.1f} A, thresh {i_cc_thresh:.1f} A):")
    print(f"    Samples : {len(cc_idx)}")
    if cc_idx:
        print(f"    V range : {min(v_cc):.1f} - {max(v_cc):.1f} V  (spread {max(v_cc)-min(v_cc):.1f} V)")
        print(f"    I range : {min(i_cc):.1f} - {max(i_cc):.1f} A  (spread {max(i_cc)-min(i_cc):.1f} A)")
        print(f"    P range : {min(p_cc):.0f} - {max(p_cc):.0f} W  (spread {max(p_cc)-min(p_cc):.0f} W)")
        print(f"    r(V, I) : {r_vi_cc:+.4f}  (should be near 0 if I is truly flat in CC)")
    print()

    # r(V_charger, I_charger) expected to be negative for constant-power charging.
    # Positive means the taper phase dominates (V pinned, I falling).
    # Discriminator: r(signal, V_charger) in the CC-phase window.
    # In CC: V varies, I flat -> power signal tracks V (r > 0), current signal flat (r ~ 0).
    # Full-window results shown for reference; CC-phase is the definitive test.
    def corr_row(label, key, ref_idx, vref, iref, pref):
        if not ts[key]:
            return None, None, None, "N/A"
        sig_grid = resample(ts[key], t_start, t_end, hz=HZ)
        sig_vals = [sig_grid[i][1] for i in ref_idx if i < len(sig_grid)]
        if len(sig_vals) < 20:
            return None, None, None, f"only {len(sig_vals)} samples"
        m   = min(len(sig_vals), len(ref_idx))
        r_v = pearson_r(vref[:m], sig_vals[:m])
        r_i = pearson_r(iref[:m], sig_vals[:m])
        r_p = pearson_r(pref[:m], sig_vals[:m])
        if r_v is not None:
            conc = "POWER" if r_v > 0.10 else ("CURRENT" if r_v < -0.10 else "AMBIGUOUS")
        else:
            conc = "?"
        return r_v, r_i, r_p, conc

    signals = [
        ("0x597 B1-B2",       's597'),
        ("0x598 B0-B1 (A)",   's598a'),
        ("0x598 B2-B3 (B)",   's598b'),
        ("0x598 B4-B5 (C)",   's598c'),
    ]

    print(f"  Full session correlations:")
    print(f"  {'Signal':<24}  {'r vs V_chr':>12}  {'r vs I_chr':>12}  {'r vs P_chr':>12}  Conclusion")
    print("  " + "-" * 84)
    for label, key in signals:
        r_v, r_i, r_p, conc = corr_row(label, key, active_idx, v_act, i_act, p_act)
        rv_s = f"{r_v:+.4f}" if r_v is not None else "   N/A"
        ri_s = f"{r_i:+.4f}" if r_i is not None else "   N/A"
        rp_s = f"{r_p:+.4f}" if r_p is not None else "   N/A"
        print(f"  {label:<24}  {rv_s:>12}  {ri_s:>12}  {rp_s:>12}  {conc}")
    print()

    if cc_idx:
        print(f"  CC-phase correlations (I flat, V varying -- clean discriminator):")
        print(f"  {'Signal':<24}  {'r vs V_chr':>12}  {'r vs I_chr':>12}  {'r vs P_chr':>12}  Conclusion")
        print("  " + "-" * 84)
        for label, key in signals:
            r_v, r_i, r_p, conc = corr_row(label, key, cc_idx, v_cc, i_cc, p_cc)
            rv_s = f"{r_v:+.4f}" if r_v is not None else "   N/A"
            ri_s = f"{r_i:+.4f}" if r_i is not None else "   N/A"
            rp_s = f"{r_p:+.4f}" if r_p is not None else "   N/A"
            print(f"  {label:<24}  {rv_s:>12}  {ri_s:>12}  {rp_s:>12}  {conc}")
    print()

# -- Analysis B: 0x420 B3/B4 Coulomb Counter ----------------------------------

def analysis_b_log(log_path, discharge):
    """
    Test whether 0x420 B3 and B4 track intI dt since last BMS boot.

    discharge=True  \u2192 compare against -intI dt  (B3/B4 count down as current flows out)
    discharge=False \u2192 compare against +intI dt  (B3/B4 count up as current flows in)
    """
    b3_ts   = []
    b4_ts   = []
    i639_ts = []

    t_first = None
    for frame in parse_file(str(log_path)):
        t = frame.timestamp
        if t_first is None:
            t_first = t
        d   = frame.data
        aid = frame.arbitration_id

        if aid == 0x420 and len(d) >= 5:
            b3_ts.append((t, d[3]))
            b4_ts.append((t, d[4]))

        elif aid == 0x639:
            raw = u16_be(d, 5)
            if raw is not None:
                i639_ts.append((t, (raw - 32768) * 0.1))

    print(f"    0x420 B3/B4 samples : {len(b3_ts)}")
    print(f"    0x639 samples       : {len(i639_ts)}")

    if not i639_ts or not b3_ts:
        print("    ERROR: Missing signals.")
        return

    for lst in (b3_ts, b4_ts, i639_ts):
        lst.sort()

    # Filter to active window: drop samples where |I| < 1 A (contactors open)
    THRESH = 1.0
    i_active = [(t, v) for t, v in i639_ts if abs(v) > THRESH]
    if len(i_active) < 20:
        i_active = i639_ts
        print(f"    Warning: few non-zero current samples; using all {len(i_active)}")
    else:
        print(f"    Active current samples (|I| > {THRESH} A): {len(i_active)}")

    total_ah = trapz(i_active) / 3600.0
    duration = i_active[-1][0] - i_active[0][0]
    sign_str = "-" if discharge else "+"
    print(f"    Active window: {duration:.1f} s    int(I dt) = {total_ah:.2f} Ah  "
          f"(sanity for highway: 10-50 Ah)")

    # Build cumulative integral timeseries
    cumul_ts = []
    running  = 0.0
    for i, (t, v) in enumerate(i_active):
        if i > 0:
            dt = t - i_active[i - 1][0]
            running += (v + i_active[i - 1][1]) / 2.0 * dt
        cumul_ts.append((t, running))

    # Apply sign convention
    sign = -1.0 if discharge else 1.0
    cumul_signed = [(t, sign * v) for t, v in cumul_ts]

    def corr_byte(byte_ts, label):
        if not byte_ts:
            print(f"    {label}: no samples")
            return
        pairs_c, pairs_b = [], []
        for t, v in byte_ts:
            cv = nearest_lookup(cumul_signed, t, max_dt=0.5)
            if cv is not None:
                pairs_c.append(cv)
                pairs_b.append(v)
        if len(pairs_c) < 10:
            print(f"    {label}: too few paired samples ({len(pairs_c)})")
            return
        r = pearson_r(pairs_c, pairs_b)
        r_str = f"{r:+.4f}" if r is not None else "  N/A"
        b_min, b_max = min(pairs_b), max(pairs_b)
        byte_range = b_max - b_min
        scale = f"{byte_range / abs(total_ah):.2f} counts/Ah" if total_ah != 0 else "N/A"
        print(f"    r({label}, {sign_str}cumul) = {r_str}    "
              f"byte range = {b_min}-{b_max}    scale ~ {scale}")

    corr_byte(b3_ts, "B3")
    corr_byte(b4_ts, "B4")

def analysis_b():
    print("=" * 65)
    print("=== Analysis B: 0x420 B3/B4 Coulomb Counter ===")
    print()
    print(f"  Discharge log: {DRIVE_LOG.name}")
    analysis_b_log(DRIVE_LOG, discharge=True)
    print()
    print(f"  Charge log: {CHARGE_LOG.name}")
    analysis_b_log(CHARGE_LOG, discharge=False)
    print()

# \u2500\u2500 Main \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def main():
    analysis_a1()
    analysis_a2()
    analysis_a2b()
    analysis_b()

if __name__ == "__main__":
    main()
