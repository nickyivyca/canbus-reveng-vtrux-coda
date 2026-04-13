"""
signal_scaling.py

Step 1: Identify roles of the three 0x598 slots (battery / generator / drivetrain)
        and 0x597 using the energy balance identity and segmented correlation.

In a series hybrid, the three channels should satisfy:
    battery + generator + drivetrain = 0  (sign convention TBD)

Approach:
  A) Current limiting test (pure EV, generator idle):
       - One slot near-zero => generator slot
       - Anti-correlated pair => battery + drivetrain
       - Balance check: try all sign combos of A+/-B+/-C; find smallest residual

  B) Evap drive log (generator on during EVAP purge):
       - Segment by generator torque (0x051) on/off
       - During gen-off:  battery ~= -drivetrain  (same as EV mode)
       - During gen-on:   slot that changes most  => generator slot
       - Verify with pairwise r vs gen_trq (0x051) and motor RPM (0x5A2)
       - Balance check over full log and per-segment

Step 2 (separate run): once roles are confirmed, calibrate A/count scale
        using known power operating points.

Usage:
    python signal_scaling.py > signal_scaling_output.txt
"""

import math
from pathlib import Path
import sys

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from canre.parsers.autodetect import parse_file

LOGS_DIR   = PROJECT_ROOT / "projects" / "vtrux" / "logs"
CLIMIT_LOG = LOGS_DIR / "vtruxcurrentlimitingtest.log"
EVAP_LOG   = LOGS_DIR / "vtruxevapdrivelog4.log"
EVAP_LOG2  = LOGS_DIR / "vtruxevapdrivelog4part2.log"

# Generator torque threshold: 0x051 raw - 32768; generating = negative
GEN_TORQUE_ON_THRESH = -50   # counts below neutral = generator clearly on

# Current limiting test: drop last N seconds (non-EV segment at end of log)
CLIMIT_TRIM_END_S = 120   # seconds to trim from the end

# Known power references for Step 2 scale calibration
P_REGEN     = 100_000.0   # W — regen power cap during current limiting test
P_DISCHARGE = 180_000.0   # W — peak discharge power during current limiting test
P_GEN_MID   =  47_500.0   # W — mid-estimate of peak generator power during evap purge (~45-50 kW)

# Charging cross-check constants (from vi_disambiguation A2b CC-phase analysis)
# 0x598 B0-B1 (battery slot) raw counts seen during CC-phase AC charging
CHARGING_BATTERY_COUNTS = 10.5   # counts
# Actual charger output current during CC phase (from CAN ground-truth signal)
CHARGER_CURRENT_KNOWN_A = 12.9   # A


# ---------- helpers ----------------------------------------------------------

def u16_le(data, b):
    if len(data) < b + 2:
        return None
    return data[b] | (data[b + 1] << 8)

def s16_le(data, b):
    v = u16_le(data, b)
    return None if v is None else (v - 0x10000 if v >= 0x8000 else v)

def nearest(ts_vals, t, max_dt=2.0):
    """Binary search for nearest sample within max_dt."""
    if not ts_vals:
        return None
    lo, hi = 0, len(ts_vals) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if ts_vals[mid][0] < t:
            lo = mid + 1
        else:
            hi = mid
    best_i, best_dt = lo, abs(ts_vals[lo][0] - t)
    for i in (lo - 1, lo + 1):
        if 0 <= i < len(ts_vals):
            dt = abs(ts_vals[i][0] - t)
            if dt < best_dt:
                best_dt, best_i = dt, i
    return ts_vals[best_i][1] if best_dt <= max_dt else None

def stats(vals):
    n = len(vals)
    if n == 0:
        return 0, 0, 0, 0
    mu = sum(vals) / n
    sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / n)
    return mu, sd, min(vals), max(vals)

def pearson(xs, ys):
    n = len(xs)
    if n < 10:
        return None
    mx = sum(xs) / n;  my = sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / n)
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / n)
    if sx == 0 or sy == 0:
        return None
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / n / (sx * sy)

def balance_check(A, B, C):
    """Try all sign combos of A +/- B +/- C; return the one with smallest residual stddev."""
    best = None
    for sa, sb, sc, label in [
        (+1, +1, +1, "A+B+C"),
        (+1, +1, -1, "A+B-C"),
        (+1, -1, +1, "A-B+C"),
        (-1, +1, +1, "-A+B+C"),
    ]:
        sums = [sa * a + sb * b + sc * c for a, b, c in zip(A, B, C)]
        mu, sd, _, _ = stats(sums)
        mag = sum(abs(a) + abs(b) + abs(c) for a, b, c in zip(A, B, C)) / len(A)
        resid = sd / mag if mag > 0 else 999
        if best is None or resid < best[0]:
            best = (resid, label, mu, sd, sums)
    return best   # (residual_frac, label, mean, stddev, sums)


# ---------- collection -------------------------------------------------------

def collect(log_paths):
    """Single pass. Returns dict of sorted (t, value) lists."""
    d = {
        "s597":    [],   # 0x597 B1-B2 LE u16-32768
        "s598a":   [],   # 0x598 B0-B1 LE u16-32768  (slot A)
        "s598b":   [],   # 0x598 B2-B3 LE u16-32768  (slot B)
        "s598c":   [],   # 0x598 B4-B5 LE u16-32768  (slot C)
        "hv_dcdc": [],   # 0x18FFD6B3 B4-B5 LE s16 x0.05 V
        "hv_482":  [],   # 0x482 B1-B2 LE u16 V
        "hv_440":  [],   # 0x440 B3-B4 LE u16 V
        "gen_trq": [],   # 0x051 B1-B2 LE u16-32768 (negative=generating)
        "mtr_rpm": [],   # 0x5A2 B2-B3 LE u16-32768 (motor RPM)
        "mtr_trq": [],   # 0x5A2 B4-B5 LE u16-32768 (motor torque feedback)
    }
    for log_path in log_paths:
        print(f"  Reading {log_path.name} ...", file=sys.stderr)
        for frame in parse_file(str(log_path)):
            t   = frame.timestamp
            cid = frame.arbitration_id
            dat = frame.data

            if cid == 0x597:
                v = u16_le(dat, 1)
                if v is not None:
                    d["s597"].append((t, v - 32768))

            elif cid == 0x598 and len(dat) >= 6:
                a = u16_le(dat, 0)
                b = u16_le(dat, 2)
                c = u16_le(dat, 4)
                if a is not None: d["s598a"].append((t, a - 32768))
                if b is not None: d["s598b"].append((t, b - 32768))
                if c is not None: d["s598c"].append((t, c - 32768))

            elif cid == 0x18FFD6B3:
                v = s16_le(dat, 4)
                if v is not None:
                    d["hv_dcdc"].append((t, v * 0.05))

            elif cid == 0x482 and len(dat) >= 3:
                v = u16_le(dat, 1)
                if v is not None:
                    d["hv_482"].append((t, float(v)))

            elif cid == 0x440 and len(dat) >= 5:
                v = u16_le(dat, 3)
                if v is not None:
                    d["hv_440"].append((t, float(v)))

            elif cid == 0x051:
                v = u16_le(dat, 1)
                if v is not None:
                    d["gen_trq"].append((t, v - 32768))

            elif cid == 0x5A2 and len(dat) >= 6:
                r = u16_le(dat, 2)
                q = u16_le(dat, 4)
                if r is not None: d["mtr_rpm"].append((t, r - 32768))
                if q is not None: d["mtr_trq"].append((t, q - 32768))

    return d


def hv_best(data, t):
    """Best HV bus voltage at time t."""
    for key in ("hv_dcdc", "hv_482", "hv_440"):
        v = nearest(data[key], t)
        if v is not None and v > 100:
            return v, key
    return None, None


# ---------- analysis A: current limiting test --------------------------------

def analysis_climit():
    print("=" * 68)
    print("=== Analysis A: Current Limiting Test ===")
    print(f"    Log: {CLIMIT_LOG.name}")
    print()

    data = collect([CLIMIT_LOG])

    # Determine time window and apply end-trim
    all_times = [t for key in data for t, _ in data[key]]
    t_log_end = max(all_times) if all_times else 0
    t_log_start = min(all_times) if all_times else 0
    t_cutoff = t_log_end - CLIMIT_TRIM_END_S
    print(f"  Log time range: {t_log_start:.1f} - {t_log_end:.1f} s  (duration {t_log_end - t_log_start:.0f} s)")
    print(f"  Trimming last {CLIMIT_TRIM_END_S} s (non-EV segment): using t <= {t_cutoff:.1f} s")
    for key in data:
        data[key] = [(t, v) for t, v in data[key] if t <= t_cutoff]
    print()

    print("  Samples after trim:")
    for k, v in data.items():
        if v:
            print(f"    {k:<10}: {len(v)}")
    print()

    # HV voltage
    for key in ("hv_dcdc", "hv_482", "hv_440"):
        vs = [x[1] for x in data[key] if x[1] > 100]
        if vs:
            print(f"  HV ({key}): {min(vs):.1f} - {max(vs):.1f} V")
    print()

    # Generator torque range -> is gen running?
    if data["gen_trq"]:
        tv = [x[1] for x in data["gen_trq"]]
        print(f"  Gen torque 0x051: {min(tv):+.0f} to {max(tv):+.0f} counts")
        if min(tv) < GEN_TORQUE_ON_THRESH:
            print(f"  -> Generator WAS running at some point during this log.")
        else:
            print(f"  -> Generator appears IDLE throughout (all torque near 0).")
    print()

    # Signal statistics
    print("  Signal statistics:")
    print(f"  {'Signal':<12}  {'mean':>8}  {'stddev':>8}  {'min':>8}  {'max':>8}")
    print("  " + "-" * 50)
    sigs = [("s597","0x597 B1-B2"), ("s598a","0x598 B0-B1 (A)"),
            ("s598b","0x598 B2-B3 (B)"), ("s598c","0x598 B4-B5 (C)")]
    for key, label in sigs:
        if not data[key]:
            print(f"  {label:<12}  (no data)")
            continue
        vs = [x[1] for x in data[key]]
        mu, sd, lo, hi = stats(vs)
        print(f"  {label:<12}  {mu:>8.1f}  {sd:>8.1f}  {lo:>8.0f}  {hi:>8.0f}")
    print()

    # Pairwise Pearson r between all four signals
    # Use 0x598 timestamps as anchor (lowest rate ~1 Hz), nearest-lookup for others
    if not data["s598a"]:
        print("  No 0x598 data.")
        return

    # Build paired array: for each 0x598 frame, get nearest sample of each signal
    paired = {"s598a": [], "s598b": [], "s598c": [], "s597": []}
    for t, va in data["s598a"]:
        vb = nearest(data["s598b"], t)
        vc = nearest(data["s598c"], t)
        v7 = nearest(data["s597"],  t)
        if vb is None or vc is None or v7 is None:
            continue
        paired["s598a"].append(va)
        paired["s598b"].append(vb)
        paired["s598c"].append(vc)
        paired["s597"].append(v7)

    n_paired = len(paired["s598a"])
    print(f"  Paired samples (0x598 anchor): {n_paired}")
    print()

    # Pairwise r matrix
    keys  = ["s597", "s598a", "s598b", "s598c"]
    names = ["0x597", "0x598A", "0x598B", "0x598C"]
    print("  Pairwise Pearson r (all four signals):")
    print(f"  {'':14}", end="")
    for nm in names:
        print(f"  {nm:>8}", end="")
    print()
    print("  " + "-" * 50)
    for i, (ki, ni) in enumerate(zip(keys, names)):
        print(f"  {ni:<14}", end="")
        for j, (kj, nj) in enumerate(zip(keys, names)):
            if j < i:
                print(f"  {'':>8}", end="")
            elif j == i:
                print(f"  {'1.0000':>8}", end="")
            else:
                r = pearson(paired[ki], paired[kj])
                rs = f"{r:+.4f}" if r is not None else "   N/A"
                print(f"  {rs:>8}", end="")
        print()
    print()

    # Balance check across all sign combos of the three 0x598 slots
    A = paired["s598a"]
    B = paired["s598b"]
    C = paired["s598c"]
    mag_avg = sum(abs(a) + abs(b) + abs(c) for a, b, c in zip(A, B, C)) / n_paired

    print("  Balance check: A+/-B+/-C (find sign combo that sums to ~0)")
    print(f"  Mean signal magnitude: {mag_avg:.1f} counts/slot")
    print(f"  {'Combo':<12}  {'mean(sum)':>10}  {'std(sum)':>10}  {'std/mag':>10}")
    print("  " + "-" * 50)
    for sa, sb, sc, label in [
        (+1, +1, +1, "A+B+C"),
        (+1, +1, -1, "A+B-C"),
        (+1, -1, +1, "A-B+C"),
        (-1, +1, +1, "-A+B+C"),
    ]:
        sums = [sa * a + sb * b + sc * c for a, b, c in zip(A, B, C)]
        mu, sd, _, _ = stats(sums)
        resid = sd / mag_avg if mag_avg > 0 else 999
        marker = " <-- best" if resid < 0.3 else ""
        print(f"  {label:<12}  {mu:>10.1f}  {sd:>10.1f}  {resid:>10.3f}{marker}")
    print()

    # Also check if 0x597 pairs with any 0x598 slot (could be a copy of one slot)
    print("  Does 0x597 copy any 0x598 slot?  (r > 0.99 = likely copy)")
    for k, nm in [("s598a","0x598A"), ("s598b","0x598B"), ("s598c","0x598C")]:
        r = pearson(paired["s597"], paired[k])
        rs = f"{r:+.4f}" if r is not None else "N/A"
        print(f"    r(0x597, {nm}) = {rs}")
    print()


# ---------- analysis B: evap drive log (generator on/off) --------------------

def analysis_evap():
    print("=" * 68)
    print("=== Analysis B: Evap Drive Log -- Generator On/Off Segmentation ===")
    logs = [EVAP_LOG]
    if EVAP_LOG2.exists():
        logs.append(EVAP_LOG2)
    print(f"    Logs: {', '.join(p.name for p in logs)}")
    print()

    data = collect(logs)

    print("  Samples collected:")
    for k, v in data.items():
        if v:
            print(f"    {k:<10}: {len(v)}")
    print()

    # HV voltage
    for key in ("hv_dcdc", "hv_482", "hv_440"):
        vs = [x[1] for x in data[key] if x[1] > 100]
        if vs:
            print(f"  HV ({key}): {min(vs):.1f} - {max(vs):.1f} V")
    print()

    # Generator torque overview
    if data["gen_trq"]:
        tv = [x[1] for x in data["gen_trq"]]
        print(f"  Gen torque 0x051:  {min(tv):+.0f} to {max(tv):+.0f} counts")
        print(f"  Gen-on threshold:  < {GEN_TORQUE_ON_THRESH} counts")
        n_on = sum(1 for v in tv if v < GEN_TORQUE_ON_THRESH)
        print(f"  Gen-on frames:     {n_on} of {len(tv)}")
    if data["mtr_rpm"]:
        rv = [x[1] for x in data["mtr_rpm"]]
        print(f"  Motor RPM 0x5A2:   {min(rv):+.0f} to {max(rv):+.0f} counts")
    print()

    if not data["s598a"]:
        print("  No 0x598 data.")
        return

    # Build paired array anchored on 0x598 (1 Hz), with nearest-lookup for others
    rows = []   # each row: (t, s598a, s598b, s598c, s597, gen_trq, mtr_rpm, mtr_trq)
    for t, va in data["s598a"]:
        vb   = nearest(data["s598b"],   t)
        vc   = nearest(data["s598c"],   t)
        v7   = nearest(data["s597"],    t)
        vgt  = nearest(data["gen_trq"], t)
        vmr  = nearest(data["mtr_rpm"], t)
        vmt  = nearest(data["mtr_trq"], t)
        if vb is None or vc is None or v7 is None or vgt is None:
            continue
        rows.append((t, va, vb, vc, v7, vgt,
                     vmr if vmr is not None else 0,
                     vmt if vmt is not None else 0))

    print(f"  Paired samples: {len(rows)}")
    print()

    # Split into gen-off and gen-on segments
    gen_off = [r for r in rows if r[5] >= GEN_TORQUE_ON_THRESH]
    gen_on  = [r for r in rows if r[5] <  GEN_TORQUE_ON_THRESH]
    print(f"  Gen-off samples (gen_trq >= {GEN_TORQUE_ON_THRESH}): {len(gen_off)}")
    print(f"  Gen-on  samples (gen_trq <  {GEN_TORQUE_ON_THRESH}): {len(gen_on)}")
    print()

    def segment_analysis(label, segment):
        if len(segment) < 10:
            print(f"  [{label}] insufficient samples ({len(segment)})")
            return
        A  = [r[1] for r in segment]
        B  = [r[2] for r in segment]
        C  = [r[3] for r in segment]
        S7 = [r[4] for r in segment]
        GT = [r[5] for r in segment]
        MR = [r[6] for r in segment]
        MT = [r[7] for r in segment]

        print(f"  [{label}]  ({len(segment)} samples)")

        # Stats per slot
        print(f"  {'Signal':<12}  {'mean':>8}  {'stddev':>8}  {'min':>8}  {'max':>8}")
        print("  " + "-" * 50)
        for vals, nm in [(A,"0x598A"),(B,"0x598B"),(C,"0x598C"),(S7,"0x597")]:
            mu, sd, lo, hi = stats(vals)
            print(f"  {nm:<12}  {mu:>8.1f}  {sd:>8.1f}  {lo:>8.0f}  {hi:>8.0f}")
        print()

        # Correlations vs gen torque and motor RPM
        print(f"  Correlations vs physical references:")
        print(f"  {'Signal':<12}  {'r vs gen_trq':>14}  {'r vs mtr_rpm':>14}  {'r vs mtr_trq':>14}")
        print("  " + "-" * 58)
        for vals, nm in [(A,"0x598A"),(B,"0x598B"),(C,"0x598C"),(S7,"0x597")]:
            rg = pearson(vals, GT)
            rm = pearson(vals, MR)
            rt = pearson(vals, MT)
            rgs = f"{rg:+.4f}" if rg is not None else "   N/A"
            rms = f"{rm:+.4f}" if rm is not None else "   N/A"
            rts = f"{rt:+.4f}" if rt is not None else "   N/A"
            print(f"  {nm:<12}  {rgs:>14}  {rms:>14}  {rts:>14}")
        print()

        # Balance check
        mag_avg = sum(abs(a) + abs(b) + abs(c) for a, b, c in zip(A, B, C)) / len(A)
        print(f"  Balance check (A +/- B +/- C), mean magnitude/slot = {mag_avg:.1f}:")
        print(f"  {'Combo':<12}  {'mean(sum)':>10}  {'std(sum)':>10}  {'std/mag':>10}")
        print("  " + "-" * 48)
        for sa, sb, sc, lbl in [
            (+1, +1, +1, "A+B+C"),
            (+1, +1, -1, "A+B-C"),
            (+1, -1, +1, "A-B+C"),
            (-1, +1, +1, "-A+B+C"),
        ]:
            sums = [sa*a + sb*b + sc*c for a, b, c in zip(A, B, C)]
            mu, sd, _, _ = stats(sums)
            resid = sd / mag_avg if mag_avg > 0 else 999
            marker = " <-- best" if resid < 0.35 else ""
            print(f"  {lbl:<12}  {mu:>10.1f}  {sd:>10.1f}  {resid:>10.3f}{marker}")
        print()

        # Pairwise r
        pairs = [("A+B","0x598A","0x598B",A,B),
                 ("A+C","0x598A","0x598C",A,C),
                 ("B+C","0x598B","0x598C",B,C),
                 ("A+597","0x598A","0x597",A,S7),
                 ("B+597","0x598B","0x597",B,S7),
                 ("C+597","0x598C","0x597",C,S7)]
        print(f"  Pairwise r:")
        for lbl, na, nb, va2, vb2 in pairs:
            r = pearson(va2, vb2)
            rs = f"{r:+.4f}" if r is not None else "N/A"
            print(f"    r({na}, {nb}) = {rs}")
        print()

    # Run segment analysis for each period
    segment_analysis("GEN OFF (pure EV)", gen_off)
    segment_analysis("GEN ON  (hybrid)",  gen_on)

    # Overall correlations across full log
    segment_analysis("FULL LOG", rows)

    # Peak generator moment
    if data["gen_trq"]:
        peak_gen = min(data["gen_trq"], key=lambda x: x[1])
        t_pk, trq_pk = peak_gen
        print(f"  Peak generating moment: t = {t_pk:.1f} s,  gen_trq = {trq_pk:+.0f} counts")
        v_hv, vsrc = hv_best(data, t_pk)
        if v_hv:
            print(f"  HV voltage: {v_hv:.1f} V [{vsrc}]")
        gen_rpm_pk = nearest(data["mtr_rpm"], t_pk)   # note: we don't collect gen_rpm separately here
        # use 0x63C via raw -- not yet collected in this pass; note it
        print(f"  Signal values at peak gen moment:")
        for key, label in [("s597","0x597 B1-B2"),("s598a","0x598A"),
                            ("s598b","0x598B"),("s598c","0x598C")]:
            v = nearest(data[key], t_pk, max_dt=10.0)
            vs = f"{v:+.0f}" if v is not None else "N/A"
            print(f"    {label:<16}: {vs} counts")
        print()


# ---------- analysis C: scale calibration ------------------------------------

def analysis_scale():
    """Step 2: Calibrate A/count scale using known power operating points.

    Reference moments:
      1. Peak regen in current limiting test   → P_REGEN     (battery = most positive A slot)
      2. Peak discharge in current limiting test → P_DISCHARGE (battery = most negative A slot)
         (tried in EV portion first; falls back to full log if EV portion lacks a deep discharge)
      3. Peak generator in evap log             → P_GEN_MID   (generator = most positive B slot
                                                               during a gen-on period)

    For each moment: scale_A [A/count] = P / V_hv / |raw|
                     scale_W [W/count] = P / |raw|

    Charging cross-check:
      At the derived mean scale, how much battery current does the small charging
      signal (~10.5 counts) imply?  The remainder vs the known charger current
      is an estimate of the DCDC/aux fixed loss.
    """
    print("=" * 68)
    print("=== Analysis C: Scale Calibration ===")
    print()

    # ---- collect current limiting test (full log for discharge peak search) ----
    print("  Collecting current limiting test (full log) ...", file=sys.stderr)
    climit_full = collect([CLIMIT_LOG])

    all_times = [t for key in climit_full for t, _ in climit_full[key]]
    if not all_times:
        print("  ERROR: no data from current limiting log.")
        return
    t_log_end = max(all_times)
    t_cutoff  = t_log_end - CLIMIT_TRIM_END_S

    # EV-only subset (same trim as Analysis A)
    climit_ev = {k: [(t, v) for t, v in climit_full[k] if t <= t_cutoff]
                 for k in climit_full}

    # ---- collect evap drive log -----------------------------------------------
    evap_logs = [EVAP_LOG]
    if EVAP_LOG2.exists():
        evap_logs.append(EVAP_LOG2)
    print("  Collecting evap drive log(s) ...", file=sys.stderr)
    evap_data = collect(evap_logs)
    print(file=sys.stderr)

    results = []   # list of dicts for printing

    # ---- 1. Peak regen (battery most positive = highest s598a in EV portion) ----
    ev_a = climit_ev["s598a"]
    if ev_a:
        t_pk, raw_pk = max(ev_a, key=lambda x: x[1])
        v_hv, vsrc   = hv_best(climit_ev, t_pk)
        if v_hv and raw_pk > 100:
            scale_a = P_REGEN / v_hv / raw_pk
            scale_w = P_REGEN / raw_pk
            results.append(dict(
                label   = "Regen peak  (A=battery +)",
                raw     = raw_pk,
                v_hv    = v_hv,
                vsrc    = vsrc,
                scale_a = scale_a,
                scale_w = scale_w,
                notes   = f"t={t_pk:.1f}s  P={P_REGEN/1000:.0f} kW ref",
            ))
        else:
            print(f"  Regen peak: raw={raw_pk}, V_hv={v_hv} — skipping (no HV or too small)")

    # ---- 2. Peak discharge (battery most negative = lowest s598a) ---------------
    #  Try EV-only portion first; fall back to full log
    discharge_found = False
    for suffix, dataset in [("EV portion", climit_ev), ("full log", climit_full)]:
        da = dataset["s598a"]
        if not da:
            continue
        t_pk, raw_pk = min(da, key=lambda x: x[1])
        if raw_pk < -200:
            v_hv, vsrc = hv_best(dataset, t_pk)
            if v_hv:
                scale_a = P_DISCHARGE / v_hv / abs(raw_pk)
                scale_w = P_DISCHARGE / abs(raw_pk)
                results.append(dict(
                    label   = f"Discharge pk (A=battery, dischg, {suffix})",
                    raw     = raw_pk,
                    v_hv    = v_hv,
                    vsrc    = vsrc,
                    scale_a = scale_a,
                    scale_w = scale_w,
                    notes   = f"t={t_pk:.1f}s  P={P_DISCHARGE/1000:.0f} kW ref",
                ))
                discharge_found = True
                break
    if not discharge_found:
        print("  Discharge peak: no usable negative s598a found in either EV portion or full log")

    # ---- 3. Peak generator current (s598b most positive during gen-on period) ---
    eb = evap_data["s598b"]
    if eb:
        t_pk, raw_pk = max(eb, key=lambda x: x[1])
        vgt = nearest(evap_data["gen_trq"], t_pk, max_dt=5.0)
        gen_on = (vgt is not None and vgt < GEN_TORQUE_ON_THRESH)
        if raw_pk > 200 and gen_on:
            v_hv, vsrc = hv_best(evap_data, t_pk)
            if v_hv:
                scale_a = P_GEN_MID / v_hv / raw_pk
                scale_w = P_GEN_MID / raw_pk
                results.append(dict(
                    label   = "Gen peak    (B=generator +)",
                    raw     = raw_pk,
                    v_hv    = v_hv,
                    vsrc    = vsrc,
                    scale_a = scale_a,
                    scale_w = scale_w,
                    notes   = f"t={t_pk:.1f}s  P≈{P_GEN_MID/1000:.1f} kW est",
                ))
            else:
                print(f"  Gen peak: raw={raw_pk} but no HV voltage nearby — skipping")
        else:
            print(f"  Gen peak: raw={raw_pk}, gen_on={gen_on} (vgt={vgt}) — check gen state")

    if not results:
        print("  No calibration reference points found — cannot compute scale.")
        return

    # ---- print scale table -------------------------------------------------------
    print("  Scale calibration results:")
    hdr = f"  {'Moment':<44}  {'raw':>7}  {'V_hv':>6}  {'src':>8}  {'A/count':>9}  {'W/count':>8}  Notes"
    print(hdr)
    print("  " + "-" * 110)
    scale_a_vals = []
    for r in results:
        print(f"  {r['label']:<44}  {r['raw']:>7.0f}  {r['v_hv']:>6.1f}  {r['vsrc']:>8}"
              f"  {r['scale_a']:>9.5f}  {r['scale_w']:>8.2f}  {r['notes']}")
        scale_a_vals.append(r["scale_a"])
    print()

    mean_scale_a = sum(scale_a_vals) / len(scale_a_vals)
    spread_pct   = (max(scale_a_vals) - min(scale_a_vals)) / mean_scale_a * 100 if len(scale_a_vals) > 1 else 0.0
    print(f"  Mean A/count scale : {mean_scale_a:.5f} A/count")
    if len(scale_a_vals) > 1:
        print(f"  Spread             : {spread_pct:.1f}% of mean  ({min(scale_a_vals):.5f} – {max(scale_a_vals):.5f})")
    print()

    # ---- charging cross-check ----------------------------------------------------
    print("  Charging cross-check (fixed-loss hypothesis):")
    print(f"    Battery signal during CC charging : {CHARGING_BATTERY_COUNTS:.1f} counts  (0x598 B0-B1)")
    print(f"    Known charger output current      : {CHARGER_CURRENT_KNOWN_A:.1f} A")
    i_batt_implied = CHARGING_BATTERY_COUNTS * mean_scale_a
    i_loss         = CHARGER_CURRENT_KNOWN_A - i_batt_implied
    # Use nominal 400 V for charging HV (typical during AC charging)
    v_charge_nom   = 400.0
    p_loss         = i_loss * v_charge_nom
    print(f"    Implied battery current (driving scale): {i_batt_implied:.2f} A")
    print(f"    Implied DCDC/aux loss current           : {i_loss:.2f} A  ({p_loss:.0f} W at {v_charge_nom:.0f} V)")
    if i_loss < 0:
        print(f"    -> Negative loss: driving scale implies MORE battery current than charger supplies.")
        print(f"       Scale may be over-estimated, or charging signal counts are higher than assumed.")
    elif p_loss < 500:
        print(f"    -> Loss very small (<500 W): scales appear self-consistent but DCDC load seems low.")
    elif p_loss <= 3000:
        print(f"    -> Loss in 500–3000 W range: plausible for DCDC converter + minor aux loads.")
    elif p_loss <= 6000:
        print(f"    -> Loss in 3–6 kW range: plausible if AC compressor or large aux loads are on.")
    else:
        print(f"    -> Loss > 6 kW: large — possible scale offset or non-linearity at low currents.")
    print()


# ---------- main -------------------------------------------------------------

if __name__ == "__main__":
    analysis_climit()
    print()
    analysis_evap()
    print()
    analysis_scale()
