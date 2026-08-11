"""
Battery degradation characterization for Vtrux A123 pack (post-swap tracking).

For a charge/drive session it extracts time-aligned samples of:
  - bcm_ibat   pack current (A, +charge / -discharge)   [0x410]
  - bcm_vbat   pack voltage (V)                          [0x410]
  - bcm_soc    state of charge (%)                       [0x410]
  - vmax/vmin  extreme cell voltages (mV)                [0x430]
  - tmax/tmin  extreme cell temps (degC)                 [0x430]
and characterizes vmin, vmax, and average-cell (vbat/116) vs load, then
estimates per-cell internal resistance for the min, max, and average cell
two independent ways:

  R_reg   : coefficient on current in OLS  V_mV ~ a + b*SoC + R*I
            (controls for OCV drift with SoC). mOhm/cell.
  R_step  : median dV/dI over fast current steps (|dI|>=ISTEP_A within DT_MAX s,
            SoC ~ constant so OCV ~ constant). mOhm/cell.

Run from project root:  py -3.12 projects/vtrux/notes/artifacts/battery_degradation_characterize.py
"""
import sys
sys.path.insert(0, ".")
import cantools
from canre.parsers import parse_file

DBC = "projects/vtrux/epri-pt-bus.dbc"
N_CELLS = 116
ISTEP_A = 8.0      # min current step magnitude for delta-R method
DT_MAX = 0.5       # max dt between samples for a valid current step (s)

db = cantools.database.load_file(DBC)
M410 = db.get_message_by_name("EPRI_BCM_Status_0410")
M430 = db.get_message_by_name("EPRI_BCM_Data1_0430")


def solve3(A, b):
    """Solve 3x3 linear system by Gaussian elimination (stdlib only)."""
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    n = 3
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            return None
        M[c], M[p] = M[p], M[c]
        piv = M[c][c]
        M[c] = [v / piv for v in M[c]]
        for r in range(n):
            if r != c:
                f = M[r][c]
                M[r] = [M[r][k] - f * M[c][k] for k in range(n + 1)]
    return [M[i][n] for i in range(n)]


def ols_R(soc, cur, v):
    """OLS  v ~ a + b*soc + R*cur ; return (R, b, r2, n)."""
    n = len(v)
    if n < 10:
        return None
    sx = [sum(soc), sum(cur)]
    Sxx = [[n, sx[0], sx[1]],
           [sx[0], sum(s * s for s in soc), sum(soc[i] * cur[i] for i in range(n))],
           [sx[1], sum(soc[i] * cur[i] for i in range(n)), sum(c * c for c in cur)]]
    Xy = [sum(v),
          sum(soc[i] * v[i] for i in range(n)),
          sum(cur[i] * v[i] for i in range(n))]
    beta = solve3(Sxx, Xy)
    if beta is None:
        return None
    a, b, R = beta
    vbar = sum(v) / n
    ss_tot = sum((vi - vbar) ** 2 for vi in v)
    ss_res = sum((v[i] - (a + b * soc[i] + R * cur[i])) ** 2 for i in range(n))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return R, b, r2, n


def median(xs):
    s = sorted(xs)
    k = len(s)
    if k == 0:
        return float("nan")
    return s[k // 2] if k % 2 else 0.5 * (s[k // 2 - 1] + s[k // 2])


def step_R(samples, key):
    """Median dV/dI over fast current steps. key picks the voltage field."""
    rs = []
    for i in range(1, len(samples)):
        a, b = samples[i - 1], samples[i]
        dt = b["t"] - a["t"]
        di = b["ibat"] - a["ibat"]
        if 0 < dt <= DT_MAX and abs(di) >= ISTEP_A:
            dv = b[key] - a[key]          # mV
            rs.append(dv / di)            # mV/A = mOhm
    return median(rs), len(rs)


def simple_slope(cur, v):
    """OLS slope of v ~ a + R*cur."""
    n = len(cur)
    mc = sum(cur) / n
    den = sum((c - mc) ** 2 for c in cur)
    if den <= 0:
        return None
    mv = sum(v) / n
    return sum((cur[i] - mc) * (v[i] - mv) for i in range(n)) / den


def window_R(samples, key, win_s=20.0, soc_span=0.6, imin_range=12.0, nmin=8):
    """Cross-check: in short windows where SoC is ~constant, regress V~I and
    take the median slope. Immune to OCV drift without needing a SoC term."""
    rs = []
    i = 0
    n = len(samples)
    while i < n:
        j = i
        s0 = samples[i]["soc"]
        t0 = samples[i]["t"]
        while (j < n and samples[j]["t"] - t0 <= win_s
               and abs(samples[j]["soc"] - s0) <= soc_span):
            j += 1
        seg = samples[i:j]
        if len(seg) >= nmin:
            cur = [x["ibat"] for x in seg]
            if max(cur) - min(cur) >= imin_range:
                slope = simple_slope(cur, [x[key] for x in seg])
                if slope is not None:
                    rs.append(slope)
        i = j if j > i else i + 1
    return median(rs), len(rs)


CACHE_DIR = "projects/vtrux/notes/artifacts/_degr_cache"


def collect(logfiles):
    """Return time-aligned sample dicts across the given chunk files (one session).
    Caches parsed samples by (filenames+sizes) so re-analysis skips the parse."""
    import os as _os, pickle, hashlib
    key = hashlib.md5(
        ("|".join(f"{f}:{_os.path.getsize(f)}" for f in logfiles)).encode()
    ).hexdigest()
    _os.makedirs(CACHE_DIR, exist_ok=True)
    cpath = _os.path.join(CACHE_DIR, key + ".pkl")
    if _os.path.exists(cpath):
        with open(cpath, "rb") as fh:
            return pickle.load(fh)

    last_vmax = last_vmin = last_tmax = last_tmin = None
    samples = []
    for fn in logfiles:
        for fr in parse_file(fn, absolute=True):
            aid = fr.arbitration_id & 0x7FF
            if aid == 0x430:
                try:
                    d = M430.decode(fr.data, decode_choices=False, allow_truncated=True)
                except Exception:
                    continue
                vx, vn = d.get("bcm_cell_vmax"), d.get("bcm_cell_vmin")
                if vx is not None and vx < 8.0:
                    last_vmax = vx * 1000.0
                if vn is not None and vn < 8.0:
                    last_vmin = vn * 1000.0
                if d.get("bcm_cell_tmax") is not None:
                    last_tmax = d["bcm_cell_tmax"]
                if d.get("bcm_cell_tmin") is not None:
                    last_tmin = d["bcm_cell_tmin"]
            elif aid == 0x410:
                try:
                    d = M410.decode(fr.data, decode_choices=False, allow_truncated=True)
                except Exception:
                    continue
                ib, vb, soc = d.get("bcm_ibat"), d.get("bcm_vbat"), d.get("bcm_soc")
                if ib is None or vb is None or soc is None:
                    continue
                if not (150.0 < vb < 500.0) or abs(ib) > 700:
                    continue
                if last_vmax is None or last_vmin is None:
                    continue
                samples.append({
                    "t": fr.timestamp, "ibat": ib, "vpack": vb, "soc": soc,
                    "vmax": last_vmax, "vmin": last_vmin,
                    "avg": vb * 1000.0 / N_CELLS,
                    "tmax": last_tmax, "tmin": last_tmin,
                })
    with open(cpath, "wb") as fh:
        pickle.dump(samples, fh)
    return samples


def spread_analysis(s):
    """Decompose vmax-vmin spread into resting (OCV imbalance) + load-induced
    (differential resistance between the extreme cells)."""
    cur = [x["ibat"] for x in s]
    spr = [x["vmax"] - x["vmin"] for x in s]
    n = len(s)

    print("\n  spread (vmax-vmin) vs load:")
    edges = [0, 10, 25, 50, 100, 200, 300, 400, 2000]
    print(f"    {'|I| bin (A)':<14}{'n':>8}{'mean|I|':>9}{'meanSpread':>12}{'maxSpread':>11}")
    for lo, hi in zip(edges, edges[1:]):
        idx = [i for i in range(n) if lo <= abs(cur[i]) < hi]
        if not idx:
            continue
        mi = sum(abs(cur[i]) for i in idx) / len(idx)
        ms = sum(spr[i] for i in idx) / len(idx)
        mx = max(spr[i] for i in idx)
        print(f"    {lo:>4}-{hi:<8}{len(idx):>8}{mi:>9.0f}{ms:>12.1f}{mx:>11.0f}")

    rest = [spr[i] for i in range(n) if abs(cur[i]) < 10]
    rest_med = median(rest) if rest else float("nan")
    print(f"    resting spread (|I|<10A): median={rest_med:.1f} mV  (OCV/SoC imbalance floor)")

    # differential resistance: slope of spread vs |I| (charge and discharge separately)
    def diff_R(mask_sign):
        xs, ys = [], []
        for i in range(n):
            if mask_sign > 0 and cur[i] > 20:
                xs.append(cur[i]); ys.append(spr[i])
            elif mask_sign < 0 and cur[i] < -20:
                xs.append(-cur[i]); ys.append(spr[i])  # use |I|
        if len(xs) < 30:
            return None, 0
        sl = simple_slope(xs, ys)
        return sl, len(xs)

    rd_c, nc = diff_R(+1)
    rd_d, nd = diff_R(-1)
    print(f"    differential R (extreme-cell delta): "
          f"charge={rd_c if rd_c is None else round(rd_c,3)} mOhm (n={nc}), "
          f"discharge={rd_d if rd_d is None else round(rd_d,3)} mOhm (n={nd})")
    if rd_d:
        print(f"    -> at 400A the weak/strong extreme cells differ by ~{rd_d*400:.0f} mV "
              f"on top of the {rest_med:.0f} mV resting imbalance")


def characterize(label, logfiles):
    s = collect(logfiles)
    if len(s) < 30:
        print(f"\n### {label}: only {len(s)} samples -- skipped")
        return None
    soc = [x["soc"] for x in s]
    cur = [x["ibat"] for x in s]
    n = len(s)

    # collinearity diagnostic between SoC and current
    msoc, mcur = sum(soc) / n, sum(cur) / n
    num = sum((soc[i] - msoc) * (cur[i] - mcur) for i in range(n))
    den = (sum((x - msoc) ** 2 for x in soc) * sum((x - mcur) ** 2 for x in cur)) ** 0.5
    r_soc_i = num / den if den else float("nan")

    print(f"\n{'='*78}\n### {label}")
    print(f"samples={n}  duration={s[-1]['t']-s[0]['t']:.0f}s")
    print(f"SoC: {min(soc):.1f}..{max(soc):.1f}%   current: {min(cur):.1f}..{max(cur):.1f}A "
          f"(mean {mcur:.1f})")
    tmaxs = [x['tmax'] for x in s if x['tmax'] is not None]
    tmins = [x['tmin'] for x in s if x['tmin'] is not None]
    if tmaxs:
        print(f"cell temp: tmin {min(tmins):.0f}..{max(tmins):.0f}C  tmax {min(tmaxs):.0f}..{max(tmaxs):.0f}C")
    vmax = [x['vmax'] for x in s]; vmin = [x['vmin'] for x in s]; avg = [x['avg'] for x in s]
    spread = [vmax[i]-vmin[i] for i in range(n)]
    print(f"vmax(mV): {min(vmax):.0f}..{max(vmax):.0f}   vmin(mV): {min(vmin):.0f}..{max(vmin):.0f}"
          f"   avg(mV): {min(avg):.0f}..{max(avg):.0f}")
    print(f"spread vmax-vmin(mV): {min(spread):.0f}..{max(spread):.0f} (mean {sum(spread)/n:.1f})")
    print(f"corr(SoC,current)={r_soc_i:+.2f}  (|r|->1 weakens regression R separation)")

    print(f"\n  per-cell internal resistance (mOhm):")
    print(f"  {'cell':<8}{'R_reg':>8}{'R2':>7}{'dOCV/dSoC':>11}{'R_win':>8}{'n_win':>7}{'R_step':>9}{'n_step':>8}")
    rows = {}
    for name, vseries in (("max", vmax), ("min", vmin), ("avg", avg)):
        key = {"max": "vmax", "min": "vmin", "avg": "avg"}[name]
        reg = ols_R(soc, cur, vseries)
        rwin, nwin = window_R(s, key)
        rstep, nstep = step_R(s, key)
        if reg:
            R, b, r2, _ = reg
            print(f"  {name:<8}{R:>8.2f}{r2:>7.2f}{b:>11.2f}{rwin:>8.2f}{nwin:>7d}{rstep:>9.2f}{nstep:>8d}")
            rows[name] = {"R_reg": R, "r2": r2, "dOCV_dSoC": b,
                          "R_win": rwin, "n_win": nwin, "R_step": rstep, "n_step": nstep}
    print(f"  R_reg : OLS coeff on I in  V~a+b*SoC+R*I  (primary)")
    print(f"  R_win : median V~I slope in SoC-constant {20:.0f}s windows (cross-check)")
    print(f"  R_step: median dV/dI over |dI|>={ISTEP_A:.0f}A steps within {DT_MAX}s (sparse on smooth charge)")
    print(f"  pack R ~ R_avg * {N_CELLS}")
    spread_analysis(s)
    return {"label": label, "n": n, "soc": (min(soc), max(soc)),
            "cur": (min(cur), max(cur)), "spread_mean": sum(spread)/n, "R": rows}


import os, re, glob


def discover_sessions(logdir, date_prefix):
    """Group vtrux_<date>_<time>_T<n>.log files into sessions, chunks T-ordered."""
    pat = re.compile(r"(vtrux_" + date_prefix + r"_\d{6})_T(\d+)\.log$")
    sessions = {}
    for p in glob.glob(os.path.join(logdir, f"vtrux_{date_prefix}_*.log")):
        m = pat.search(os.path.basename(p))
        if not m:
            continue
        sessions.setdefault(m.group(1), []).append((int(m.group(2)), p))
    out = []
    for sess in sorted(sessions):
        chunks = [p for _, p in sorted(sessions[sess])]
        out.append((sess, chunks))
    return out


if __name__ == "__main__":
    LOGDIR = "../../CANLogs/VtruxLogs"
    DATE = "20260617"
    sessions = discover_sessions(LOGDIR, DATE)
    print(f"Discovered {len(sessions)} sessions for {DATE}:")
    for sess, chunks in sessions:
        tot = sum(os.path.getsize(c) for c in chunks)
        print(f"  {sess}: {len(chunks)} chunks, {tot/1e6:.0f} MB")

    results = []
    for sess, chunks in sessions:
        r = characterize(sess, chunks)
        if r:
            results.append(r)

    print(f"\n{'='*78}\n### TODAY SUMMARY ({DATE}) -- per-cell R_reg (mOhm)")
    print(f"  {'session':<22}{'n':>7}{'SoC%':>12}{'I(A)':>14}{'spread':>8}"
          f"{'Rmax':>7}{'Rmin':>7}{'Ravg':>7}")
    for r in results:
        R = r["R"]
        print(f"  {r['label']:<22}{r['n']:>7}"
              f"{r['soc'][0]:>6.1f}-{r['soc'][1]:<5.1f}"
              f"{r['cur'][0]:>7.0f}-{r['cur'][1]:<6.0f}{r['spread_mean']:>8.1f}"
              f"{R.get('max',{}).get('R_reg',float('nan')):>7.2f}"
              f"{R.get('min',{}).get('R_reg',float('nan')):>7.2f}"
              f"{R.get('avg',{}).get('R_reg',float('nan')):>7.2f}")
