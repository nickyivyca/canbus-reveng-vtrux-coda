"""
epri_verify_open_items.py

Resolves several PARTIAL items from epri-verification.md:

PHASE 1 -- 0x0598 power vs current (open item 2)
  Correlates 0x0598 B2-B3 (generator channel) against:
    (a) GENE_HighPwr_Curr from 0x0482       -- current hypothesis
    (b) GENE_HighPwr_Curr * GENE_HighPwr_Volt -- power hypothesis
  Better r wins.  Also derives the scale (A/count or W/count).
  Log: vtruxevapdrivelog2.log (uphill, active generator).
  Also re-checks balance B4-B5 = B0-B1 + B2-B3.

PHASE 2 -- DCDC_LV_Volt / DCDC_LV_Curr vs bcm_lvbat (open item 3)
  Compares 0x18FFD6B3 B0-B1 and B6-B7 (0.05 V/count, LE signed)
  against 0x0430 B7 (0.1 V/count, bcm_lvbat) across startup rise
  and EPO shutdown decay.
  Log: vtruxisolationtest.log.

PHASE 3 -- 0x063A presence check (open item 5)
  Reports whether 0x063A appears in any of the standard drive logs,
  and if so what values iVehCfg_ess_md and iVehCfg_chgr_md take.
  Logs: oghighwaydrive.log, vtruxevapdrivelog2.log, vtruxisolationtest.log.

Usage:
    python epri_verify_open_items.py [phase]   (default: all)
    python epri_verify_open_items.py 1
    python epri_verify_open_items.py 2
    python epri_verify_open_items.py 3
"""

import sys
import math
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from canre.parsers.autodetect import parse_file

LOGS = PROJECT_ROOT / "projects" / "vtrux" / "logs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def u16_le(data, b):
    if len(data) < b + 2:
        return None
    return data[b] | (data[b + 1] << 8)

def s16_le(data, b):
    v = u16_le(data, b)
    return None if v is None else (v - 0x10000 if v >= 0x8000 else v)

def pearson_r(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    num   = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mx)**2 for x in xs))
    den_y = math.sqrt(sum((y - my)**2 for y in ys))
    if den_x < 1e-12 or den_y < 1e-12:
        return float("nan")
    return num / (den_x * den_y)

def linreg(xs, ys):
    """Return (slope, intercept, r)."""
    n = len(xs)
    if n < 2:
        return float("nan"), float("nan"), float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    ss_xy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    ss_xx = sum((x - mx)**2 for x in xs)
    slope = ss_xy / ss_xx if ss_xx > 1e-12 else float("nan")
    intercept = my - slope * mx
    r = pearson_r(xs, ys)
    return slope, intercept, r

def nearest(series, t, max_dt=2.0):
    """Binary-search nearest-time value in a sorted (t, v) list."""
    if not series:
        return None
    lo, hi = 0, len(series) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if series[mid][0] < t:
            lo = mid + 1
        else:
            hi = mid
    best_i, best_dt = lo, abs(series[lo][0] - t)
    for i in (lo - 1, lo + 1):
        if 0 <= i < len(series):
            dt = abs(series[i][0] - t)
            if dt < best_dt:
                best_dt, best_i = dt, i
    return series[best_i][1] if best_dt <= max_dt else None

def stats_list(vals):
    if not vals:
        return 0, float("nan"), float("nan"), float("nan"), float("nan")
    n = len(vals)
    mu = sum(vals) / n
    sd = math.sqrt(sum((v - mu)**2 for v in vals) / n)
    return n, mu, sd, min(vals), max(vals)


# ---------------------------------------------------------------------------
# Phase 1 -- power vs current
# ---------------------------------------------------------------------------

def phase1():
    log_path = LOGS / "vtruxevapdrivelog4part2.log"
    print("=" * 70)
    print("PHASE 1: 0x0598 power vs current  |  log:", log_path.name)
    print("=" * 70)
    if not log_path.exists():
        print("  ERROR: log not found:", log_path)
        return

    # Collect raw series
    s598a, s598b, s598c = [], [], []   # B0-B1, B2-B3, B4-B5 signed centred at 0
    gene_curr, gene_volt = [], []      # 0x0482 current (A) and voltage (V)
    gen_trq = []                       # 0x051 B1-B2 LE - 32768 (torque command)

    for frame in parse_file(str(log_path)):
        t   = frame.timestamp
        cid = frame.arbitration_id
        dat = frame.data

        if cid == 0x0598 and len(dat) >= 6:
            a = u16_le(dat, 0)
            b = u16_le(dat, 2)
            c = u16_le(dat, 4)
            if a is not None: s598a.append((t, a - 32768))
            if b is not None: s598b.append((t, b - 32768))
            if c is not None: s598c.append((t, c - 32768))

        elif cid == 0x0482 and len(dat) >= 5:
            # GENE_HighPwr_Volt: 11-bit LE, start byte 1, mask 0x07FF, scale 1 V/count
            v_raw = u16_le(dat, 1)
            if v_raw is not None:
                gene_volt.append((t, float(v_raw & 0x07FF)))
            # GENE_HighPwr_Curr: 14-bit LE, start byte 3, mask 0x3FFF,
            #                    scale 0.25 A/count, offset -2048 A
            c_raw = u16_le(dat, 3)
            if c_raw is not None:
                gene_curr.append((t, (c_raw & 0x3FFF) * 0.25 - 2048.0))

        elif cid == 0x051 and len(dat) >= 3:
            v = u16_le(dat, 1)
            if v is not None:
                gen_trq.append((t, v - 32768))

    print(f"  Frames: 0x0598={len(s598b)}, 0x0482-curr={len(gene_curr)}, "
          f"0x0482-volt={len(gene_volt)}, 0x051={len(gen_trq)}")
    if not s598b or not gene_curr or not gene_volt:
        print("  ERROR: missing data streams.")
        return

    t_min = min(s598b[0][0], gene_curr[0][0])
    t_max = max(s598b[-1][0], gene_curr[-1][0])
    print(f"  Time span: {t_min:.1f} - {t_max:.1f} s  ({(t_max-t_min)/60:.1f} min)")

    # ---- overview of GENE_HighPwr values ----
    curr_vals = [v for _, v in gene_curr]
    volt_vals = [v for _, v in gene_volt]
    print(f"\n  GENE_HighPwr_Curr range: {min(curr_vals):+.1f} to {max(curr_vals):+.1f} A")
    print(f"  GENE_HighPwr_Volt range: {min(volt_vals):.1f} to {max(volt_vals):.1f} V")

    # ---- aligned triplets: (s598b, gene_curr, gene_volt) ----
    triplets = []
    for t, b_raw in s598b:
        c = nearest(gene_curr, t)
        v = nearest(gene_volt, t)
        if c is None or v is None:
            continue
        triplets.append((t, b_raw, c, v))

    if len(triplets) < 20:
        print("  ERROR: too few aligned triplets.")
        return

    print(f"\n  Aligned triplets: {len(triplets)}")

    # ---- filter to generator-active frames ----
    # Generator active when gen_trq < -50 (generating, pulling negative torque command)
    GEN_ON_THRESH = -50
    gen_on_trips  = [(t, b, c, v) for t, b, c, v in triplets
                     if (gt := nearest(gen_trq, t)) is not None and gt < GEN_ON_THRESH]
    gen_off_trips = [(t, b, c, v) for t, b, c, v in triplets
                     if (gt := nearest(gen_trq, t)) is not None and gt >= GEN_ON_THRESH]
    print(f"  Gen-on  frames: {len(gen_on_trips)}")
    print(f"  Gen-off frames: {len(gen_off_trips)}")

    for seg_label, seg in [("ALL", triplets), ("GEN-ON", gen_on_trips),
                            ("GEN-OFF", gen_off_trips)]:
        if len(seg) < 10:
            continue
        b_vals = [x[1] for x in seg]
        c_vals = [x[2] for x in seg]   # amps
        v_vals = [x[3] for x in seg]   # volts
        p_vals = [c * v for c, v in zip(c_vals, v_vals)]  # watts

        r_curr  = pearson_r(b_vals, c_vals)
        r_power = pearson_r(b_vals, p_vals)

        slope_curr,  ic,  _ = linreg(b_vals, c_vals)
        slope_power, ip, _  = linreg(b_vals, p_vals)

        # If 0x0598 encodes current, scale_A = slope_curr (A per count)
        # If 0x0598 encodes power,   scale_W = slope_power (W per count)
        #                            scale_kW = slope_power / 1000
        b_min, b_max = min(b_vals), max(b_vals)
        n = len(seg)

        print(f"\n  [{seg_label}]  n={n}  0x0598-B2B3 range: {b_min:.0f} to {b_max:.0f} counts")
        print(f"    vs GENE_HighPwr_Curr  (A):  r = {r_curr:+.4f}  |  scale = {slope_curr:.5f} A/count")
        print(f"    vs GENE_Curr*Volt     (W):  r = {r_power:+.4f}  |  scale = {slope_power:.4f} W/count"
              f"  ({slope_power/1000:.6f} kW/count)")

    # ---- Balance check: C = A + B ----
    print("\n  BALANCE CHECK (B4-B5 = B0-B1 + B2-B3):")
    bal_rows = []
    for t, a_raw in s598a:
        b = nearest(s598b, t)
        c = nearest(s598c, t)
        if b is None or c is None:
            continue
        bal_rows.append((a_raw, b, c, a_raw + b - c))

    if bal_rows:
        residuals = [r[3] for r in bal_rows]
        n, mu, sd, mn, mx = stats_list(residuals)
        c_mean = sum(r[2] for r in bal_rows) / len(bal_rows)
        rel_sd = sd / abs(c_mean) * 100 if c_mean != 0 else float("nan")
        print(f"    Residual (A+B-C): mean={mu:.1f}  std={sd:.1f}  min={mn:.0f}  max={mx:.0f}")
        print(f"    Relative std vs mean C: {rel_sd:.1f}%")


# ---------------------------------------------------------------------------
# Phase 2 -- DCDC_LV_Volt / DCDC_LV_Curr vs bcm_lvbat
# ---------------------------------------------------------------------------

def phase2():
    log_path = LOGS / "vtruxisolationtest.log"
    print("\n" + "=" * 70)
    print("PHASE 2: DCDC LV vs bcm_lvbat  |  log:", log_path.name)
    print("=" * 70)
    if not log_path.exists():
        print("  ERROR: log not found:", log_path)
        return

    # 0x18FFD6B3: LE signed int16 x 0.05
    #   B0-B1: DCDC_LV_Volt (setpoint/target)
    #   B2-B3: DCDC_LV_Curr
    #   B4-B5: DCDC_HV_Volt (confirmed reference, used to detect DCDC active)
    #   B6-B7: 12V measured output (from powertrain-messages.md -- not in EPRI DBC)
    # 0x0430 B7: bcm_lvbat x 0.1 V

    dcdc_lv_set  = []   # B0-B1 x 0.05  V
    dcdc_lv_curr = []   # B2-B3 x 0.05  A
    dcdc_hv      = []   # B4-B5 x 0.05  V  (reference for DCDC active state)
    dcdc_lv_meas = []   # B6-B7 x 0.05  V  (measured output, not in EPRI DBC)
    bcm_lvbat    = []   # 0x0430 B7 x 0.1 V

    for frame in parse_file(str(log_path)):
        t   = frame.timestamp
        cid = frame.arbitration_id
        dat = frame.data

        if cid == 0x18FFD6B3 and len(dat) >= 8:
            b01 = s16_le(dat, 0)
            b23 = s16_le(dat, 2)
            b45 = s16_le(dat, 4)
            b67 = s16_le(dat, 6)
            if b01 is not None: dcdc_lv_set.append((t, b01 * 0.05))
            if b23 is not None: dcdc_lv_curr.append((t, b23 * 0.05))
            if b45 is not None: dcdc_hv.append((t, b45 * 0.05))
            if b67 is not None: dcdc_lv_meas.append((t, b67 * 0.05))

        elif cid == 0x0430 and len(dat) >= 8:
            bcm_lvbat.append((t, dat[7] * 0.1))

    print(f"  Frames: DCDC_0x18FFD6B3={len(dcdc_lv_set)}, bcm_lvbat={len(bcm_lvbat)}")
    if not dcdc_lv_set or not bcm_lvbat:
        print("  ERROR: missing data streams.")
        return

    all_t = [t for t, _ in dcdc_lv_set]
    print(f"  Time span: {all_t[0]:.1f} - {all_t[-1]:.1f} s  ({(all_t[-1]-all_t[0])/60:.1f} min)")

    # Ranges
    def vrange(series):
        if not series:
            return "no data"
        vals = [v for _, v in series]
        return f"{min(vals):.2f} - {max(vals):.2f}"

    print(f"\n  DCDC_LV_Volt  B0-B1 (V):              {vrange(dcdc_lv_set)}")
    print(f"  DCDC_LV_Curr  B2-B3 (A):              {vrange(dcdc_lv_curr)}")
    print(f"  DCDC_HV_Volt  B4-B5 (V):              {vrange(dcdc_hv)}")
    print(f"  DCDC_B6B7 as temp (x0.1 degC):        {vrange([(t,v/0.05*0.1) for t,v in dcdc_lv_meas])}")
    print(f"    (Note: EPRI says B6-B7 = DCDCunitinternaltemperature x0.1 degC signed,")
    print(f"     NOT a 12V voltage. powertrain-messages.md 'B6-B7 12V measured output' is WRONG.)")
    print(f"  bcm_lvbat  0x0430 B7 (V):             {vrange(bcm_lvbat)}")

    # Look for startup rise: first 30s of log
    t0 = all_t[0]
    startup_end = t0 + 30.0

    print(f"\n  --- Startup window ({t0:.1f} - {startup_end:.1f} s) ---")
    for label, series in [("DCDC_LV_Volt (B0-B1)", dcdc_lv_set),
                           ("DCDC_LV_meas (B6-B7)", dcdc_lv_meas),
                           ("bcm_lvbat          ", bcm_lvbat)]:
        window = [(t, v) for t, v in series if t0 <= t <= startup_end]
        if not window:
            print(f"  {label}: no data in window")
            continue
        v0 = window[0][1]
        v1 = window[-1][1]
        dv = v1 - v0
        print(f"  {label}: {v0:.2f}V -> {v1:.2f}V  (delta {dv:+.2f}V,  {len(window)} samples)")

    # Correlation (full log): dcdc_lv_set and dcdc_lv_meas vs bcm_lvbat
    aligned_set  = []
    aligned_meas = []
    for t, lv in bcm_lvbat:
        s = nearest(dcdc_lv_set,  t, max_dt=2.0)
        m = nearest(dcdc_lv_meas, t, max_dt=2.0)
        if s is not None:
            aligned_set.append((lv, s))
        if m is not None:
            aligned_meas.append((lv, m))

    if aligned_set:
        xs = [x[0] for x in aligned_set]
        ys = [x[1] for x in aligned_set]
        slope, icpt, r = linreg(xs, ys)
        print(f"\n  Correlation bcm_lvbat vs DCDC_LV_Volt (B0-B1):  r={r:+.4f}  "
              f"slope={slope:.4f}  intercept={icpt:.2f}")

    if aligned_meas:
        xs = [x[0] for x in aligned_meas]
        ys = [x[1] for x in aligned_meas]
        slope, icpt, r = linreg(xs, ys)
        print(f"  Correlation bcm_lvbat vs DCDC_LV_meas (B6-B7):  r={r:+.4f}  "
              f"slope={slope:.4f}  intercept={icpt:.2f}")

    # Find EPO event: sudden drop in HV or bcm_lvbat
    # Proxy: look for bcm_lvbat starting to fall after being stable at >13V
    if bcm_lvbat:
        high_t  = [t for t, v in bcm_lvbat if v > 13.5]
        low_t   = [t for t, v in bcm_lvbat if v < 12.5]
        if high_t and low_t and min(low_t) > min(high_t):
            fault_approx = min(low_t)
            window_start = fault_approx - 30.0
            window_end   = fault_approx + 60.0
            print(f"\n  --- EPO / fault window (approx t={fault_approx:.1f}s): "
                  f"{window_start:.1f} - {window_end:.1f} s ---")
            for label, series in [("DCDC_LV_Volt (B0-B1)", dcdc_lv_set),
                                   ("DCDC_LV_meas (B6-B7)", dcdc_lv_meas),
                                   ("DCDC_LV_Curr (B2-B3)", dcdc_lv_curr),
                                   ("bcm_lvbat          ", bcm_lvbat)]:
                window = [(t, v) for t, v in series if window_start <= t <= window_end]
                if not window:
                    print(f"  {label}: no data in window")
                    continue
                t_pk  = min(window, key=lambda x: x[1])[0]
                v_pk  = min(x[1] for x in window)
                v_pre = max((v for t, v in window if t < fault_approx), default=None)
                v_post = min((v for t, v in window if t > fault_approx + 5), default=None)
                pre_s  = f"{v_pre:.2f}V" if v_pre is not None else "N/A"
                post_s = f"{v_post:.2f}V" if v_post is not None else "N/A"
                print(f"  {label}: pre={pre_s}  post={post_s}  "
                      f"min={v_pk:.2f}V @ t={t_pk:.1f}s")
        else:
            print("\n  NOTE: No clear high->low transition found in bcm_lvbat for EPO detection.")
            # Just print last 60s of log
            t_end = all_t[-1]
            window_start = t_end - 60
            print(f"  Last 60s window ({window_start:.1f} - {t_end:.1f} s):")
            for label, series in [("DCDC_LV_Volt (B0-B1)", dcdc_lv_set),
                                   ("DCDC_LV_meas (B6-B7)", dcdc_lv_meas),
                                   ("bcm_lvbat          ", bcm_lvbat)]:
                window = [(t, v) for t, v in series if t >= window_start]
                if window:
                    print(f"  {label}: {window[0][1]:.2f} -> {window[-1][1]:.2f}V")


# ---------------------------------------------------------------------------
# Phase 3 -- 0x063A presence check
# ---------------------------------------------------------------------------

def phase3():
    print("\n" + "=" * 70)
    print("PHASE 3: 0x063A VehicleConfig presence check")
    print("=" * 70)

    logs_to_check = [
        ("oghighwaydrive",  LOGS / "oghighwaydrive.log"),
        ("evap2",           LOGS / "vtruxevapdrivelog2.log"),
        ("isolationtest",   LOGS / "vtruxisolationtest.log"),
        ("truck1log_M0",    LOGS / "truck1log_M0_T0.log"),
    ]

    for name, log_path in logs_to_check:
        if not log_path.exists():
            print(f"  {name:<22}: NOT FOUND")
            continue
        count = 0
        seen = {}
        for frame in parse_file(str(log_path)):
            if frame.arbitration_id == 0x063A:
                count += 1
                key = bytes(frame.data)
                seen[key] = seen.get(key, 0) + 1
        if count == 0:
            print(f"  {name:<22}: 0 frames")
        else:
            print(f"  {name:<22}: {count} frames,  unique payloads:")
            for payload, n in sorted(seen.items(), key=lambda x: -x[1]):
                # Decode iVehCfg_chgr_md (B7 bit 0) and iVehCfg_ess_md (B7 bit 1)
                if len(payload) >= 8:
                    b7 = payload[7]
                    chgr_md = b7 & 0x01
                    ess_md  = (b7 >> 1) & 0x01
                    chgr_s  = "DRS" if chgr_md else "POWERONE"
                    ess_s   = "Lithium(1)" if ess_md else "A123(0)"
                    print(f"    {payload.hex():<20} x{n:<6}  B7={b7:#04x}  "
                          f"chgr_md={chgr_md}({chgr_s})  ess_md={ess_md}({ess_s})")
                else:
                    print(f"    {payload.hex():<20} x{n}")


# ---------------------------------------------------------------------------
# Phase 4 -- DCDC_LV_Curr pump load comparison
#   Parts truck (truk1log_M1): pump disconnected, runs full speed = higher 12V load
#   Main truck reference charge sessions: normal pump speed
#   Compare mean DCDC power = LV_Volt * LV_Curr during CC charging phase
# ---------------------------------------------------------------------------

def collect_dcdc_charge(log_paths):
    """Collect (t, lv_volt, lv_curr, lv_pwr, ac_curr) across one or more log files."""
    rows = []
    for log_path in log_paths:
        if not log_path.exists():
            print(f"    NOT FOUND: {log_path}")
            continue
        dcdc = {}    # t -> (lv_volt, lv_curr)
        ac   = {}    # t -> ac_curr
        for frame in parse_file(str(log_path)):
            t   = frame.timestamp
            cid = frame.arbitration_id
            dat = frame.data
            if cid == 0x18FFD6B3 and len(dat) >= 6:
                lv_v = s16_le(dat, 0)
                lv_c = s16_le(dat, 2)
                if lv_v is not None and lv_c is not None:
                    dcdc[t] = (lv_v * 0.05, lv_c * 0.05)
            elif cid == 0x18FFD7C0 and len(dat) >= 8:
                # INVCH_Chg_Iin_RMS (AC input current) at B6-B7
                iin_raw = u16_le(dat, 6)
                if iin_raw is not None:
                    ac[t] = iin_raw * 0.05
        # Align dcdc to ac timestamps
        ac_list = sorted(ac.items())
        for t, (lv_v, lv_c) in sorted(dcdc.items()):
            ac_c = nearest(ac_list, t, max_dt=2.0)
            if ac_c is None:
                continue
            rows.append((t, lv_v, lv_c, lv_v * lv_c, ac_c))
    return rows

def phase4():
    print("\n" + "=" * 70)
    print("PHASE 4: DCDC_LV_Curr pump load comparison (parts truck vs main truck)")
    print("=" * 70)

    # Parts truck: truk1log M1 session (all T chunks)
    parts_logs = sorted(LOGS.glob("truk1log_M1_*.log"))
    # Main truck reference charge sessions
    ref_logs = [
        LOGS / "rainychargedebug.log",
        LOGS / "vtruxchargeafterscottsvalley.log",
        LOGS / "vtruxchargeafterucsc.log",
    ]
    ref_logs = [p for p in ref_logs if p.exists()]

    print(f"\n  Parts truck logs (truk1log_M1): {len(parts_logs)} files")
    print(f"  Reference charge logs: {[p.name for p in ref_logs]}")

    # CC phase filter: AC input current > 5A and stable (use 5A threshold)
    AC_MIN = 5.0

    for label, logs in [("PARTS TRUCK (truk1log_M1)", parts_logs),
                        ("MAIN TRUCK reference",       ref_logs)]:
        if not logs:
            print(f"\n  [{label}]: no logs found")
            continue
        print(f"\n  Collecting {label}...")
        rows = collect_dcdc_charge(logs)
        print(f"    Total aligned frames: {len(rows)}")
        if not rows:
            continue

        # Filter to CC phase (AC current present)
        cc = [(lv_v, lv_c, lv_p) for _, lv_v, lv_c, lv_p, ac in rows if ac >= AC_MIN]
        all_rows = [(lv_v, lv_c, lv_p) for _, lv_v, lv_c, lv_p, ac in rows]
        print(f"    CC-phase frames (AC >= {AC_MIN}A): {len(cc)}")

        for seg_label, seg in [("ALL frames", all_rows), ("CC phase only", cc)]:
            if len(seg) < 5:
                continue
            vs = [r[0] for r in seg]
            cs = [r[1] for r in seg]
            ps = [r[2] for r in seg]
            nv, mv, sdv, mnv, mxv = stats_list(vs)
            nc, mc, sdc, mnc, mxc = stats_list(cs)
            np_, mp, sdp, mnp, mxp = stats_list(ps)
            print(f"    [{seg_label}]  n={nv}")
            print(f"      LV_Volt (V): mean={mv:.2f}  std={sdv:.2f}  range={mnv:.2f}-{mxv:.2f}")
            print(f"      LV_Curr (A): mean={mc:.2f}  std={sdc:.2f}  range={mnc:.2f}-{mxc:.2f}")
            print(f"      LV_Pwr  (W): mean={mp:.1f}  std={sdp:.1f}  range={mnp:.1f}-{mxp:.1f}")


# ---------------------------------------------------------------------------
# Phase 5 -- bcm_vbat vs HV bus references (open item 4)
# ---------------------------------------------------------------------------

def phase5():
    log_path = LOGS / "oghighwaydrive.log"
    print("\n" + "=" * 70)
    print("PHASE 5: bcm_vbat vs GENE_HighPwr_Volt (HV cross-check)  |  log:", log_path.name)
    print("=" * 70)
    if not log_path.exists():
        print("  ERROR: log not found:", log_path)
        return

    # bcm_vbat: 0x0410 B6[3:0]:B7, 12-bit Motorola, 0.25 V/count
    #   raw = (B6 & 0x0F) * 256 + B7
    bcm_vbat_series = []
    # GENE_HighPwr_Volt: 0x0482, 11-bit LE masked 0x07FF, 1 V/count
    gene_volt_series = []
    # DCDC_HV_Volt: 0x18FFD6B3 B4-B5 LE signed x0.05 V
    dcdc_hv_series = []

    for frame in parse_file(str(log_path)):
        t   = frame.timestamp
        cid = frame.arbitration_id
        dat = frame.data

        if cid == 0x0410 and len(dat) >= 8:
            raw = (dat[6] & 0x0F) * 256 + dat[7]
            bcm_vbat_series.append((t, raw * 0.25))

        elif cid == 0x0482 and len(dat) >= 3:
            v_raw = u16_le(dat, 1)
            if v_raw is not None:
                gene_volt_series.append((t, float(v_raw & 0x07FF)))

        elif cid == 0x18FFD6B3 and len(dat) >= 6:
            b45 = s16_le(dat, 4)
            if b45 is not None:
                dcdc_hv_series.append((t, b45 * 0.05))

    print(f"  Frames: 0x0410={len(bcm_vbat_series)}, 0x0482={len(gene_volt_series)}, "
          f"0x18FFD6B3={len(dcdc_hv_series)}")

    if not bcm_vbat_series or not gene_volt_series:
        print("  ERROR: missing required series.")
        return

    vbat_vals = [v for _, v in bcm_vbat_series]
    gene_vals = [v for _, v in gene_volt_series]
    print(f"\n  bcm_vbat range:        {min(vbat_vals):.2f} - {max(vbat_vals):.2f} V")
    print(f"  GENE_HighPwr_Volt:     {min(gene_vals):.2f} - {max(gene_vals):.2f} V")
    if dcdc_hv_series:
        dcdc_vals = [v for _, v in dcdc_hv_series]
        print(f"  DCDC_HV_Volt:          {min(dcdc_vals):.2f} - {max(dcdc_vals):.2f} V")

    # Align bcm_vbat to GENE_HighPwr_Volt timestamps
    pairs_gene = []
    for t, vbat in bcm_vbat_series:
        gv = nearest(gene_volt_series, t, max_dt=1.0)
        if gv is not None:
            pairs_gene.append((vbat, gv))

    if pairs_gene:
        xs = [p[0] for p in pairs_gene]
        ys = [p[1] for p in pairs_gene]
        slope, icpt, r = linreg(xs, ys)
        print(f"\n  bcm_vbat vs GENE_HighPwr_Volt:  r={r:+.4f}  "
              f"slope={slope:.4f}  intercept={icpt:.2f}")
        print(f"    (If bcm_vbat is HV pack, expect r~1, slope~1, intercept~contactor drop)")

    # Align bcm_vbat to DCDC_HV_Volt if available
    if dcdc_hv_series:
        pairs_dcdc = []
        for t, vbat in bcm_vbat_series:
            dv = nearest(dcdc_hv_series, t, max_dt=1.0)
            if dv is not None:
                pairs_dcdc.append((vbat, dv))
        if pairs_dcdc:
            xs = [p[0] for p in pairs_dcdc]
            ys = [p[1] for p in pairs_dcdc]
            slope, icpt, r = linreg(xs, ys)
            print(f"  bcm_vbat vs DCDC_HV_Volt:       r={r:+.4f}  "
                  f"slope={slope:.4f}  intercept={icpt:.2f}")

    # Print a few sample aligned pairs to spot-check values
    print(f"\n  Sample aligned pairs (t, bcm_vbat_V, GENE_HighPwr_Volt_V):")
    step = max(1, len(bcm_vbat_series) // 8)
    for i, (t, vbat) in enumerate(bcm_vbat_series[::step][:8]):
        gv = nearest(gene_volt_series, t, max_dt=1.0)
        diff = (vbat - gv) if gv is not None else None
        diff_s = f"  diff={diff:+.2f}V" if diff is not None else ""
        gv_s = f"{gv:.1f}" if gv is not None else "N/A"
        print(f"    t={t:7.1f}s  bcm_vbat={vbat:.2f}V  GENE={gv_s}V{diff_s}")


# ---------------------------------------------------------------------------
# Phase 6 -- DCDC_LV_Volt vs bcm_lvbat on normal charge log
#            + per-chunk LV_Curr breakdown for truk1log_M1
# ---------------------------------------------------------------------------

def phase6():
    print("\n" + "=" * 70)
    print("PHASE 6: DCDC_LV_Volt vs bcm_lvbat (normal charge)  +  LV_Curr per-chunk")
    print("=" * 70)

    # --- Part A: normal charge log correlation ---
    charge_logs = [
        LOGS / "rainychargedebug.log",
        LOGS / "debuglog_M0_T0.log",
    ]
    chosen = None
    for p in charge_logs:
        if p.exists():
            chosen = p
            break

    if chosen is None:
        print("  Part A: no charge log found, skipping.")
    else:
        print(f"\n  Part A: DCDC_LV_Volt vs bcm_lvbat  |  log: {chosen.name}")
        dcdc_lv = []
        bcm_lv  = []
        for frame in parse_file(str(chosen)):
            t   = frame.timestamp
            cid = frame.arbitration_id
            dat = frame.data
            if cid == 0x18FFD6B3 and len(dat) >= 2:
                b01 = s16_le(dat, 0)
                if b01 is not None:
                    dcdc_lv.append((t, b01 * 0.05))
            elif cid == 0x0430 and len(dat) >= 8:
                bcm_lv.append((t, dat[7] * 0.1))

        print(f"  Frames: 0x18FFD6B3={len(dcdc_lv)}, 0x0430={len(bcm_lv)}")
        if dcdc_lv and bcm_lv:
            dv = [v for _, v in dcdc_lv]
            bv = [v for _, v in bcm_lv]
            print(f"  DCDC_LV_Volt range: {min(dv):.2f} - {max(dv):.2f} V")
            print(f"  bcm_lvbat range:    {min(bv):.2f} - {max(bv):.2f} V")

            pairs = []
            for t, lv in bcm_lv:
                d = nearest(dcdc_lv, t, max_dt=2.0)
                if d is not None:
                    pairs.append((lv, d))
            if pairs:
                xs = [p[0] for p in pairs]
                ys = [p[1] for p in pairs]
                slope, icpt, r = linreg(xs, ys)
                print(f"  Correlation bcm_lvbat vs DCDC_LV_Volt:  r={r:+.4f}  "
                      f"slope={slope:.4f}  intercept={icpt:.2f}")
                print(f"    (Expect r~+1, slope~1 if both measure 12V bus)")

    # --- Part B: per-chunk LV_Curr for truk1log_M1 ---
    print(f"\n  Part B: truk1log_M1 per-chunk LV_Curr comparison")
    parts_chunks = sorted(LOGS.glob("truk1log_M1_*.log"))
    print(f"  Found {len(parts_chunks)} truk1log_M1 chunks")

    if not parts_chunks:
        print("  No truk1log_M1 chunks found.")
        return

    AC_MIN = 5.0
    print(f"  {'Chunk':<28}  {'CC frames':>10}  {'LV_Volt mean':>13}  "
          f"{'LV_Curr mean':>13}  {'LV_Pwr mean':>12}")
    print("  " + "-" * 82)
    for chunk in parts_chunks:
        rows = collect_dcdc_charge([chunk])
        cc = [(lv_v, lv_c, lv_p) for _, lv_v, lv_c, lv_p, ac in rows if ac >= AC_MIN]
        if len(cc) < 5:
            print(f"  {chunk.name:<28}  {'<5 CC frames':>10}")
            continue
        vs = [r[0] for r in cc]
        cs = [r[1] for r in cc]
        ps = [r[2] for r in cc]
        _, mv, _, _, _ = stats_list(vs)
        _, mc, _, _, _ = stats_list(cs)
        _, mp, _, _, _ = stats_list(ps)
        print(f"  {chunk.name:<28}  {len(cc):>10}  {mv:>13.2f}  {mc:>13.2f}  {mp:>12.1f}")


# ---------------------------------------------------------------------------
# Phase 7 -- DCDC_LV_Curr vs blower fan speed (HVAC Part 2)
#   HVAC blower (0x451 B4 x0.392%) drops to 0 at t~1833s, resumes t~1985s.
#   If B2-B3 is real 12V output current, mean LV_Curr should be lower
#   during the blower-off window.
# ---------------------------------------------------------------------------

def phase7():
    log_path = LOGS / "vtruxanotherevaplogpart2.log"
    print("\n" + "=" * 70)
    print("PHASE 7: DCDC_LV_Curr vs blower fan  |  log:", log_path.name)
    print("=" * 70)
    if not log_path.exists():
        print("  ERROR: log not found:", log_path)
        return

    # 0x451 B4: blower speed x0.392157 %
    blower = []
    # 0x18FFD6B3: LV_Volt (B0-B1), LV_Curr (B2-B3)
    lv_volt = []
    lv_curr = []

    for frame in parse_file(str(log_path)):
        t   = frame.timestamp
        cid = frame.arbitration_id
        dat = frame.data
        if cid == 0x451 and len(dat) >= 5:
            blower.append((t, dat[4] * 0.392157))
        elif cid == 0x18FFD6B3 and len(dat) >= 4:
            b01 = s16_le(dat, 0)
            b23 = s16_le(dat, 2)
            if b01 is not None: lv_volt.append((t, b01 * 0.05))
            if b23 is not None: lv_curr.append((t, b23 * 0.05))

    print(f"  Frames: blower={len(blower)}, DCDC={len(lv_curr)}")
    if not blower or not lv_curr:
        print("  ERROR: missing data.")
        return

    bvals = [v for _, v in blower]
    cvals = [v for _, v in lv_curr]
    print(f"  Blower range:    {min(bvals):.1f} - {max(bvals):.1f} %")
    print(f"  DCDC LV_Volt:    {min(v for _,v in lv_volt):.2f} - {max(v for _,v in lv_volt):.2f} V")
    print(f"  DCDC LV_Curr:    {min(cvals):.2f} - {max(cvals):.2f} A")

    # Find blower-off window automatically: contiguous stretch where blower~0
    # Use transitions: look for blower going from >5% to <1% and back
    blower_zero_spans = []
    in_zero = False
    span_start = None
    for t, v in blower:
        if not in_zero and v < 1.0:
            in_zero = True
            span_start = t
        elif in_zero and v > 5.0:
            blower_zero_spans.append((span_start, t))
            in_zero = False
    if in_zero:
        blower_zero_spans.append((span_start, blower[-1][0]))

    print(f"\n  Blower-off spans detected: {len(blower_zero_spans)}")
    for s, e in blower_zero_spans:
        dur = e - s
        print(f"    t={s:.1f} - {e:.1f} s  ({dur:.0f} s)")

    # Per-span LV_Curr stats
    def mean_in_window(series, t0, t1):
        vals = [v for t, v in series if t0 <= t <= t1]
        return stats_list(vals)

    if blower_zero_spans:
        # Analyse each blower-off span (skip spans that start at t=0: no pre-window)
        print(f"\n  {'Window':<28}  {'n':>6}  {'mean A':>8}  {'std A':>7}  {'mean W':>8}")
        print("  " + "-" * 62)
        for span_start, span_end in blower_zero_spans:
            pre_start = max(lv_curr[0][0], span_start - 120.0)
            post_end  = min(lv_curr[-1][0], span_end + 120.0)
            for label, t0, t1 in [
                (f"pre-on  ({pre_start:.0f}-{span_start:.0f}s)",  pre_start, span_start),
                (f"off     ({span_start:.0f}-{span_end:.0f}s)",    span_start, span_end),
                (f"post-on ({span_end:.0f}-{post_end:.0f}s)",      span_end, post_end),
            ]:
                n, mu, sd, mn, mx = mean_in_window(lv_curr, t0, t1)
                nv, mv, _, _, _   = mean_in_window(lv_volt, t0, t1)
                pwr = mu * mv if nv > 0 and not math.isnan(mu) else float("nan")
                pwr_s = f"{pwr:>8.1f}" if not math.isnan(pwr) else "     N/A"
                print(f"  {label:<28}  {n:>6}  {mu:>8.3f}  {sd:>7.3f}  {pwr_s}")
            print()

    # Overall: blower on vs off alignment
    on_curr, off_curr = [], []
    for t, c in lv_curr:
        b = nearest(blower, t, max_dt=1.0)
        if b is None:
            continue
        if b < 1.0:
            off_curr.append(c)
        else:
            on_curr.append(c)

    print(f"\n  Blower-ON  frames: {len(on_curr)}")
    if on_curr:
        _, mu, sd, mn, mx = stats_list(on_curr)
        print(f"    LV_Curr: mean={mu:.3f}A  std={sd:.3f}  range={mn:.2f}-{mx:.2f}")
    print(f"  Blower-OFF frames: {len(off_curr)}")
    if off_curr:
        _, mu, sd, mn, mx = stats_list(off_curr)
        print(f"    LV_Curr: mean={mu:.3f}A  std={sd:.3f}  range={mn:.2f}-{mx:.2f}")

    if on_curr and off_curr:
        _, mu_on, _, _, _  = stats_list(on_curr)
        _, mu_off, _, _, _ = stats_list(off_curr)
        delta = mu_on - mu_off
        _, mv_all, _, _, _ = stats_list([v for _, v in lv_volt])
        delta_w = delta * mv_all
        print(f"\n  Delta (ON - OFF): {delta:+.3f} A  (~{delta_w:+.1f} W at mean LV_Volt={mv_all:.2f}V)")
        print(f"  (Positive delta = more current when blower running, as expected)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    phases_arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    run_all = (phases_arg == "all")

    if run_all or phases_arg == "1":
        phase1()
    if run_all or phases_arg == "2":
        phase2()
    if run_all or phases_arg == "3":
        phase3()
    if run_all or phases_arg == "4":
        phase4()
    if run_all or phases_arg == "5":
        phase5()
    if run_all or phases_arg == "6":
        phase6()
    if run_all or phases_arg == "7":
        phase7()


if __name__ == "__main__":
    main()
