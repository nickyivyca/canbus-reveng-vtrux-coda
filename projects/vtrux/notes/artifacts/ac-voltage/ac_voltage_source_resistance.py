"""AC input voltage and source-resistance analysis for the Vtrux Bel charger.

Data source: 0x18FFD7C0 (BELINV_hvBatteryAndCharger)
  B0:B1 LE unsigned x0.05 -> hvBatteryVoltage (V)
  B2:B3 LE signed   x0.05 -> hvBatteryCurrent (A, positive = charging)
  B4:B5 LE unsigned x0.05 -> chargerInputVoltage (AC RMS, V)
  B6:B7 LE unsigned x0.05 -> chargerInputCurrent (AC RMS, A)
Encoding authority: projects/vtrux/BelInverter-v2.dbc + projects/vtrux/README.md line 209.

Input is the grep-extracted line dump (raw_primary.txt / raw_android.txt), produced by
  grep -RH "18FFD7C0" <logroot> --include="*.log" > raw_<set>.txt

Phases:
  1  read each matched log's ***START DATE AND TIME*** header for an absolute epoch
  2  parse the raw dumps into per-file frame lists on an absolute timeline
  3  group T-chunks into capture sessions (canre.utils.merge.detect_capture_groups),
     then split on wall-clock gaps
  4  per-session AC voltage stats + source-resistance fit R = -dV/dI
  5  report

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/ac-voltage/ac_voltage_source_resistance.py
"""

import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from canre.utils.merge import detect_capture_groups

ART = "projects/vtrux/notes/artifacts/ac-voltage"
RAW = {
    "primary": os.path.join(ART, "raw_primary.txt"),
    "android": os.path.join(ART, "raw_android.txt"),
}
PILOT_RAW = os.path.join(ART, "raw_pilot.txt")

# J1772 control pilot: for 10-85% duty the EVSE advertises I = duty% * 0.6 A.
# This is the authoritative EVSE rating, independent of what the truck draws.
PILOT_RE = re.compile(
    r"^(?P<path>.+?):\d{2}:\d{2}:\d{2}:\d{4}\s+\S+\s+\d+\s+0x18FFD8C0\s+x\s+8\s+"
    r"(?P<data>(?:[0-9A-Fa-f]{2}\s+){7}[0-9A-Fa-f]{2})"
)

# grep -RH output:  <path>:HH:MM:SS:TTTT Rx <ch> 0x18FFD7C0 x 8 B0 .. B7
LINE_RE = re.compile(
    r"^(?P<path>.+?):(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2}):(?P<t>\d{4})\s+"
    r"\S+\s+(?P<ch>\d+)\s+0x18FFD7C0\s+x\s+8\s+"
    r"(?P<data>(?:[0-9A-Fa-f]{2}\s+){7}[0-9A-Fa-f]{2})"
)

# Lenient: BUSMASTER writes D:M:YYYY without zero-padding in some versions.
HDR_RE = re.compile(
    r"^\*\*\*START DATE AND TIME\s+(?P<d>\d{1,2}):(?P<mo>\d{1,2}):(?P<y>\d{4})\s+"
    r"(?P<h>\d{1,2}):(?P<mi>\d{1,2}):(?P<s>\d{1,2}):(?P<ms>\d+)",
    re.IGNORECASE,
)

GAP_S = 60.0           # wall-clock gap that separates two charge sessions
MIN_FIT_CURRENT_A = 2.0  # below this the charger is idling; V is ~open-circuit
MIN_CURRENT_SPAN_A = 3.0  # need real current swing for the slope to mean anything
# 40 was too aggressive: it silently discarded capture vtrux_20260714_151732,
# which holds the only clean LOAD DUMP in the dataset (23.4 A -> 0 A in 0.6 s,
# giving a directly measured 190.1 V open circuit at the 40 A site). Only two
# capture groups fall in the 1-39 sample range, so lowering this costs nothing.
MIN_FIT_SAMPLES = 10
MIN_FIT_R = -0.3         # V must actually fall with I for the fit to be physical

# Sample validity. 0xFFFF (-> 3276.75) is a no-data sentinel; a handful of other
# wild samples appear too (~33 in 2.84M). They are rare but extreme enough to
# dominate a least-squares fit, so they are dropped before any statistics.
V_AC_MIN, V_AC_MAX = 80.0, 300.0
I_AC_MAX = 60.0

# Step-based fit: the charger runs at pilot-limited current plateaus (~7.7 / 13 /
# 19 / 26 A). Comparing the median voltage at each plateau within one capture
# group gives a far cleaner dV/dI than fitting the noise inside a single plateau.
LEVEL_BIN_A = 1.0
MIN_LEVEL_SAMPLES = 20
MIN_LEVEL_SPAN_A = 5.0


def read_header(path):
    """Return (datetime_of_session_start, seconds_of_day) or (None, None)."""
    try:
        with open(path, "r", errors="replace") as fh:
            for _ in range(15):
                line = fh.readline()
                if not line:
                    break
                mo = HDR_RE.match(line.strip())
                if mo:
                    dt = datetime(
                        int(mo.group("y")), int(mo.group("mo")), int(mo.group("d")),
                        int(mo.group("h")), int(mo.group("mi")), int(mo.group("s")),
                    )
                    return dt, dt.hour * 3600 + dt.minute * 60 + dt.second
    except OSError:
        pass
    return None, None


def parse_raw(path):
    """Yield (logpath, seconds_of_day, v_ac, i_ac, v_hv, i_hv)."""
    bad = 0
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            mo = LINE_RE.match(line)
            if not mo:
                bad += 1
                continue
            b = [int(x, 16) for x in mo.group("data").split()]
            sod = (
                int(mo.group("h")) * 3600.0
                + int(mo.group("m")) * 60.0
                + int(mo.group("s"))
                + int(mo.group("t")) * 1e-4
            )
            raw_ihv = b[2] | (b[3] << 8)
            if raw_ihv >= 0x8000:
                raw_ihv -= 0x10000
            yield (
                mo.group("path"), sod,
                (b[4] | (b[5] << 8)) * 0.05,   # v_ac
                (b[6] | (b[7] << 8)) * 0.05,   # i_ac
                (b[0] | (b[1] << 8)) * 0.05,   # v_hv
                raw_ihv * 0.05,                # i_hv
            )
    if bad:
        print("  %d unparsed lines in %s" % (bad, path))


def load_pilot():
    """Map log file -> most common advertised EVSE current from pilot duty."""
    per_file = defaultdict(Counter)
    if not os.path.exists(PILOT_RAW):
        return {}
    with open(PILOT_RAW, "r", errors="replace") as fh:
        for line in fh:
            mo = PILOT_RE.match(line)
            if not mo:
                continue
            duty = [int(x, 16) for x in mo.group("data").split()][2]
            if 10 <= duty <= 85:
                per_file[mo.group("path")][duty] += 1
    out = {}
    for path, ctr in per_file.items():
        duty, _ = ctr.most_common(1)[0]
        out[path] = duty * 0.6
    return out


def valid(v_ac, i_ac):
    return V_AC_MIN <= v_ac <= V_AC_MAX and 0.0 <= i_ac <= I_AC_MAX


def level_fit(loaded, min_level_samples=None):
    """Fit V vs I across pilot-current plateaus.

    Bins samples by current, keeps well-populated bins, and regresses the
    per-bin median voltage against the per-bin median current. Returns
    (r_source, v_open_circuit, pearson_r, levels) or (None,)*4.
    """
    min_n = MIN_LEVEL_SAMPLES if min_level_samples is None else min_level_samples
    bins = defaultdict(list)
    for v, i, _hv, _hi in loaded:
        bins[round(i / LEVEL_BIN_A)].append((i, v))
    levels = []
    for _, pts in bins.items():
        if len(pts) < min_n:
            continue
        iv = sorted(p[0] for p in pts)
        vv = sorted(p[1] for p in pts)
        levels.append((pct(iv, 0.5), pct(vv, 0.5), len(pts)))
    levels.sort()
    if len(levels) < 2:
        return None, None, None, levels
    if levels[-1][0] - levels[0][0] < MIN_LEVEL_SPAN_A:
        return None, None, None, levels
    slope, icept, r = linfit([l[0] for l in levels], [l[1] for l in levels])
    if slope is None:
        return None, None, None, levels
    return -slope, icept, r, levels


def fixed_effects_fit(groups):
    """Within-group (fixed-effects) regression of V on I.

    `groups` is a list of [(v, i), ...] lists, one per session. Each session's
    own mean V and mean I are subtracted before a single shared slope is fitted,
    so a session that happened to start at 202 V and one that started at 208 V
    contribute only their internal V-vs-I variation. Between-session baseline
    differences -- different days, different grid conditions -- cannot leak into
    the slope. Returns (r_source, pearson_r, n_sessions, n_samples).
    """
    xs, ys = [], []
    used = 0
    for g in groups:
        if len(g) < MIN_FIT_SAMPLES:
            continue
        n = len(g)
        mi = sum(p[1] for p in g) / n
        mv = sum(p[0] for p in g) / n
        if max(p[1] for p in g) - min(p[1] for p in g) < MIN_CURRENT_SPAN_A:
            continue
        used += 1
        for p in g:
            xs.append(p[1] - mi)
            ys.append(p[0] - mv)
    if used < 1 or len(xs) < MIN_FIT_SAMPLES:
        return None, None, used, len(xs)
    slope, _icept, r = linfit(xs, ys)
    if slope is None:
        return None, None, used, len(xs)
    return -slope, r, used, len(xs)


def step_estimates(series, min_step_a=3.0, settle_s=10.0, max_gap_s=60.0):
    """R from fast current steps: R = -dV/dI across a single transition.

    Compares the median V and I in a short window immediately before a current
    step against the window immediately after. Because both windows sit within
    tens of seconds of each other, slow grid drift over a long charge cannot
    bias the result -- unlike a whole-session regression, where a baseline that
    sags over hours aliases directly into the slope.
    """
    out = []
    n = len(series)
    if n < 20:
        return out
    i = 1
    while i < n:
        t0, _v0, i0 = series[i - 1]
        t1, _v1, i1 = series[i]
        if t1 - t0 > max_gap_s or abs(i1 - i0) < min_step_a:
            i += 1
            continue
        before = [(v, c) for t, v, c in series
                  if t0 - settle_s <= t <= t0 and abs(c - i0) < 1.0]
        after = [(v, c) for t, v, c in series
                 if t1 <= t <= t1 + settle_s and abs(c - i1) < 1.0]
        if len(before) >= 5 and len(after) >= 5:
            vb = pct(sorted(p[0] for p in before), 0.5)
            ib = pct(sorted(p[1] for p in before), 0.5)
            va = pct(sorted(p[0] for p in after), 0.5)
            ia = pct(sorted(p[1] for p in after), 0.5)
            if abs(ia - ib) >= min_step_a:
                r_src = -(va - vb) / (ia - ib)
                if 0.0 < r_src < 5.0:
                    out.append((r_src, abs(ia - ib), t1))
            # skip past this transition so one step is not counted repeatedly
            i += int(settle_s * 10) + 1
            continue
        i += 1
    return out


def plateau_segments(series, tol_a=1.0, min_dur_s=20.0, min_n=20):
    """Split a session into runs of near-constant current.

    Returns [(t_mid, i_med, v_med, n, t_start, t_end), ...]. A new segment starts
    whenever the current leaves the current run's band, so both the abrupt pilot
    steps and the slow CV taper get broken into stable plateaus.
    """
    segs = []
    cur = []
    ref = None
    for t, v, i in series:
        if ref is None or abs(i - ref) <= tol_a:
            if ref is None:
                ref = i
            cur.append((t, v, i))
        else:
            if cur and cur[-1][0] - cur[0][0] >= min_dur_s and len(cur) >= min_n:
                iv = sorted(p[2] for p in cur)
                vv = sorted(p[1] for p in cur)
                segs.append((0.5 * (cur[0][0] + cur[-1][0]), pct(iv, 0.5),
                             pct(vv, 0.5), len(cur), cur[0][0], cur[-1][0]))
            cur = [(t, v, i)]
            ref = i
    if cur and cur[-1][0] - cur[0][0] >= min_dur_s and len(cur) >= min_n:
        iv = sorted(p[2] for p in cur)
        vv = sorted(p[1] for p in cur)
        segs.append((0.5 * (cur[0][0] + cur[-1][0]), pct(iv, 0.5), pct(vv, 0.5),
                     len(cur), cur[0][0], cur[-1][0]))
    return segs


def plateau_pair_estimates(series, min_step_a=3.0, max_sep_s=1200.0):
    """R from pairs of stable plateaus that are close together in time.

    Generalises the instantaneous-step estimator: the transition between the two
    plateaus may take minutes (a CV taper stepping down) rather than happening
    between consecutive samples. Capping the separation keeps slow grid drift
    from contaminating the pair, while still using the ramp-DOWN side of the
    charge, which the abrupt-step detector alone never sees.

    Returns [(r_source, delta_i, direction, gap_s), ...] where direction is
    'up' or 'down'.
    """
    segs = plateau_segments(series)
    out = []
    for a, b in zip(segs, segs[1:]):
        di = b[1] - a[1]
        gap = b[0] - a[0]
        if abs(di) < min_step_a or gap > max_sep_s or gap <= 0:
            continue
        r_src = -(b[2] - a[2]) / di
        if 0.0 < r_src < 5.0:
            out.append((r_src, abs(di), "up" if di > 0 else "down", gap))
    return out


def load_dump_anchor(series, max_i=0.5, min_n=3, settle_v=1.0):
    """Measured open-circuit voltage from a charge shutdown ("load dump").

    When a charge stops, current falls to zero while the charger keeps reporting
    for a second or so before powering down. The voltage during that window is
    the supply's open-circuit voltage -- measured, not extrapolated from a fitted
    intercept, and immune to drift because it happens in under a second.

    Returns (voc, i_at, n_samples) or (None, None, 0). Samples below `max_i` are
    collected and the p95 taken: the charger's own power-down collapses the
    reading toward zero afterwards, so the settled value is the ceiling, not the
    mean. `settle_v` rejects a window whose spread is too wide to be settled.
    """
    lows = [(i, v) for _t, v, i in series if i <= max_i and v >= V_AC_MIN]
    if len(lows) < min_n:
        return None, None, 0
    vs = sorted(v for _i, v in lows)
    voc = pct(vs, 0.95)
    # Require a tight cluster near the top; a wide spread means we caught the
    # collapse, not the settled open-circuit plateau.
    tight = [v for v in vs if v >= voc - settle_v]
    if len(tight) < min_n:
        return None, None, 0
    return voc, pct(sorted(i for i, _v in lows), 0.5), len(tight)


def lowest_current_anchor(series, bin_a=0.5, min_n=3):
    """Voltage at the lowest current bin that has data, whether or not it is 0 A.

    Fallback for outlets that never captured a shutdown. Returns
    (i_low, v_at_low, n) or (None, None, 0).
    """
    bins = defaultdict(list)
    for _t, v, i in series:
        if v >= V_AC_MIN:
            bins[round(i / bin_a)].append(v)
    for b in sorted(bins):
        if len(bins[b]) >= min_n:
            return b * bin_a, pct(sorted(bins[b]), 0.95), len(bins[b])
    return None, None, 0


def absolutize(logpath, frames):
    """Map per-line timestamps onto an absolute timeline.

    BUSMASTER logs in this project use two conventions: line timestamps that are
    already wall-clock time-of-day, and line timestamps relative to the header
    time. Detect which by comparing the first frame to the header.
    """
    hdr_dt, hdr_sod = read_header(logpath)
    if hdr_dt is None:
        return None, [(f[1], f[2], f[3], f[4], f[5]) for f in frames]

    first = frames[0][1]
    delta = abs(first - hdr_sod)
    wall_clock = min(delta, 86400 - delta) <= 300.0

    out = []
    prev = None
    day = 0
    for f in frames:
        t = f[1]
        if prev is not None and t < prev - 1.0:
            day += 1  # midnight rollover within the file
        prev = t
        abs_s = (t if wall_clock else hdr_sod + t) + day * 86400.0
        out.append((abs_s, f[2], f[3], f[4], f[5]))

    base = hdr_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return base, out


def session_key(logpath, groups_index):
    return groups_index.get(os.path.normpath(logpath), os.path.dirname(logpath))


def linfit(xs, ys):
    """Least-squares y = a + b*x. Returns (slope, intercept, pearson_r)."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None, None, None
    b = sxy / sxx
    return b, my - b * mx, sxy / (sxx * syy) ** 0.5


def pct(vals, p):
    if not vals:
        return float("nan")
    k = (len(vals) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def main():
    # ---- Phase 1-2: parse raw dumps, per log file ----
    per_file = defaultdict(list)
    file_source = {}
    for source, rawpath in RAW.items():
        if not os.path.exists(rawpath):
            print("MISSING %s -- skipping" % rawpath)
            continue
        print("Reading %s ..." % rawpath)
        n = 0
        for fr in parse_raw(rawpath):
            per_file[fr[0]].append(fr)
            file_source[fr[0]] = source
            n += 1
        print("  %d frames across %d files" % (n, len(per_file)))

    if not per_file:
        print("No AC frames found.")
        return

    # ---- Phase 3: group T-chunks into capture sessions ----
    paths = sorted(per_file)
    groups = detect_capture_groups(paths)
    groups_index = {}
    for prefix, plist in groups.items():
        for p in plist:
            groups_index[os.path.normpath(str(p))] = prefix
    print("\n%d log files with AC frames -> %d capture groups" % (len(paths), len(groups)))

    by_group = defaultdict(list)
    for logpath, frames in per_file.items():
        frames.sort(key=lambda f: f[1])
        base_day, abs_frames = absolutize(logpath, frames)
        key = (file_source[logpath], session_key(logpath, groups_index))
        for af in abs_frames:
            by_group[key].append((base_day, af[0], af[1], af[2], af[3], af[4], logpath))

    # ---- Phase 4: split on gaps, compute stats and resistance fit ----
    rows = []
    for (source, gkey), frames in by_group.items():
        frames.sort(key=lambda f: (f[0] or datetime(1970, 1, 1), f[1]))
        sessions, cur, prev = [], [], None
        for fr in frames:
            if prev is not None:
                same_day = fr[0] == prev[0]
                gap = (fr[1] - prev[1]) if same_day else GAP_S + 1
                if gap > GAP_S or gap < -GAP_S:
                    sessions.append(cur)
                    cur = []
            cur.append(fr)
            prev = fr
        if cur:
            sessions.append(cur)

        for sess in sessions:
            dur = sess[-1][1] - sess[0][1]

            loaded = [(f[2], f[3], f[4], f[5]) for f in sess
                      if f[3] >= MIN_FIT_CURRENT_A and valid(f[2], f[3])]
            if len(loaded) < MIN_FIT_SAMPLES:
                continue

            lv = sorted(x[0] for x in loaded)
            li = [x[1] for x in loaded]
            li_s = sorted(li)

            slope, icept, r = linfit(li, [x[0] for x in loaded])
            span = max(li) - min(li)
            r_src = -slope if slope is not None else None
            fit_ok = (
                r_src is not None and r is not None
                and span >= MIN_CURRENT_SPAN_A
                and r < MIN_FIT_R
                and r_src > 0
            )
            lr, lvoc, lcorr, levels = level_fit(loaded)

            when = ""
            if sess[0][0] is not None:
                when = (sess[0][0] + timedelta(seconds=sess[0][1])).strftime("%Y-%m-%d %H:%M")

            rows.append({
                "source": source, "group": gkey, "when": when,
                "file": os.path.basename(sess[0][6]),
                "paths": set(f[6] for f in sess),
                "dur_s": dur, "n": len(sess), "n_loaded": len(loaded),
                "v_min": min(lv), "v_p05": pct(lv, 0.05), "v_med": pct(lv, 0.50),
                "v_p95": pct(lv, 0.95), "v_max": max(lv),
                "i_med": pct(li_s, 0.5), "i_max": max(li), "i_span": span,
                "hv_med": pct(sorted(x[2] for x in loaded), 0.5),
                "kw_med": pct(li_s, 0.5) * pct(lv, 0.5) / 1000.0,
                "voc": icept, "r_src": r_src, "r_corr": r, "fit_ok": fit_ok,
                "lr": lr, "lvoc": lvoc, "lcorr": lcorr, "nlevels": len(levels),
                "levels": levels, "loaded": loaded,
                "series": [(f[1], f[2], f[3]) for f in sess
                           if valid(f[2], f[3])],
            })

    rows.sort(key=lambda d: d["v_med"])
    cols = ["source", "group", "when", "file", "dur_s", "n", "n_loaded",
            "v_min", "v_p05", "v_med", "v_p95", "v_max", "i_med", "i_max",
            "i_span", "hv_med", "kw_med", "voc", "r_src", "r_corr", "fit_ok",
            "lr", "lvoc", "lcorr", "nlevels"]
    out = os.path.join(ART, "sessions.csv")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(",".join(cols) + "\n")
        for d in rows:
            fh.write(",".join('"%s"' % d[c] if isinstance(d[c], str) else str(d[c])
                              for c in cols) + "\n")
    print("Wrote %s (%d charge sessions)\n" % (out, len(rows)))

    def fmt(d):
        return ("%-7s %-16s %-16s dur=%5.0fs n=%6d | Vac med=%6.1f min=%6.1f max=%6.1f | "
                "Iac med=%5.1f max=%5.1f span=%5.1f | %5.1fkW | Voc=%s R=%s r=%s%s"
                % (d["source"], d["when"] or "?", d["group"][-16:], d["dur_s"], d["n"],
                   d["v_med"], d["v_min"], d["v_max"], d["i_med"], d["i_max"],
                   d["i_span"], d["kw_med"],
                   ("%6.1f" % d["voc"]) if d["voc"] is not None else "   n/a",
                   ("%6.3f" % d["r_src"]) if d["r_src"] is not None else "   n/a",
                   ("%5.2f" % d["r_corr"]) if d["r_corr"] is not None else "  n/a",
                   "  FIT" if d["fit_ok"] else ""))

    print("=== 30 LOWEST-VOLTAGE CHARGE SESSIONS (by median loaded Vac) ===")
    for d in rows[:30]:
        print(fmt(d))

    print("\n=== 15 HIGHEST-VOLTAGE CHARGE SESSIONS ===")
    for d in rows[-15:]:
        print(fmt(d))

    print("\n=== MOST RECENT 20 SESSIONS (by log date) ===")
    dated = sorted([d for d in rows if d["when"]], key=lambda d: d["when"])
    for d in dated[-20:]:
        print(fmt(d))

    # ---- Phase 5: step-based source resistance, per charge session ----
    # A session is one contiguous stretch of charging, so the outlet and wiring
    # are fixed for its duration. Pooling wider (per capture group) mixes
    # different outlets and produces meaningless slopes.
    print("\n" + "=" * 104)
    print("STEP-BASED SOURCE RESISTANCE (per charge session, across pilot-current plateaus)")
    print("Regresses median Vac at each current plateau within one contiguous session.")
    print("Accepted when >=3 plateaus, current span >=%.0f A, and r <= -0.8." % MIN_LEVEL_SPAN_A)
    print("=" * 104)

    step = [d for d in rows
            if d["lr"] is not None and d["lr"] > 0 and d["nlevels"] >= 3
            and d["lcorr"] is not None and d["lcorr"] <= -0.8]
    step.sort(key=lambda d: d["lr"])

    for d in step:
        print("%-7s %-16s %-20s n=%6d | Vac med=%6.1f | R=%6.3f ohm  Voc=%6.1f V  "
              "r=%5.2f  (%d plateaus, %.1f-%.1f A)"
              % (d["source"], d["when"] or "?", str(d["group"])[-20:], d["n_loaded"],
                 d["v_med"], d["lr"], d["lvoc"], d["lcorr"], d["nlevels"],
                 d["levels"][0][0], d["levels"][-1][0]))

    print("\n--- Step-based R summary (%d of %d sessions usable) ---" % (len(step), len(rows)))
    if step:
        rs = sorted(d["lr"] for d in step)
        for label, p in (("min", 0.0), ("p25", 0.25), ("median", 0.5),
                         ("p75", 0.75), ("max", 1.0)):
            print("  R %-6s = %.3f ohm" % (label, pct(rs, p)))
        vocs = sorted(d["lvoc"] for d in step)
        print("  implied open-circuit Voc: min=%.1f median=%.1f max=%.1f V"
              % (vocs[0], pct(vocs, 0.5), vocs[-1]))

    # ---- Phase 5b: deep dive on the lowest-voltage sessions ----
    print("\n" + "=" * 104)
    print("LOW-VOLTAGE DEEP DIVE: plateau ladders for the 6 lowest-Vac sessions")
    print("=" * 104)
    for d in rows[:6]:
        print("\n%-7s %s  %s  (median Vac %.1f V, %.1f kW)"
              % (d["source"], d["when"] or "?", d["file"], d["v_med"], d["kw_med"]))
        if d["lr"] is not None:
            print("   fit: R=%.3f ohm  Voc=%.1f V  r=%.2f" % (d["lr"], d["lvoc"], d["lcorr"]))
        for i_lvl, v_lvl, cnt in d["levels"]:
            print("   plateau %5.1f A -> %6.1f V   (%5.2f kW, n=%d)"
                  % (i_lvl, v_lvl, i_lvl * v_lvl / 1000.0, cnt))

    good = [d for d in rows if d["fit_ok"]]
    print("\n=== SOURCE RESISTANCE (per-session within-plateau fit, for comparison) ===")
    print("%d of %d sessions have a usable V-vs-I fit "
          "(current span >= %.1f A, r < %.1f)" % (len(good), len(rows),
                                                  MIN_CURRENT_SPAN_A, MIN_FIT_R))
    if good:
        rs = sorted(d["r_src"] for d in good)
        for label, p in (("min", 0.0), ("p25", 0.25), ("median", 0.5),
                         ("p75", 0.75), ("max", 1.0)):
            print("  R %-6s = %.3f ohm" % (label, pct(rs, p)))
        print("\n  Per-session fits, sorted by R:")
        for d in sorted(good, key=lambda x: x["r_src"]):
            print("  " + fmt(d))

    # ---- Phase 6: classify sessions by EVSE rating and supply class ----
    # Per operator notes: the Vtrux derates the EVSE pilot limit, so a 32 A EVSE
    # settles around 27-28 A and a 40 A EVSE around 36 A. Supply classes seen are
    # 240 V nominal residential and 208 V nominal industrial.
    print("\n" + "=" * 104)
    print("SUPPLY CLASSIFICATION")
    print("EVSE rating inferred from peak sustained current (derated ~15%% by the truck);")
    print("supply class from the session's lightly-loaded / extrapolated open-circuit voltage.")
    print("=" * 104)

    pilot = load_pilot()
    print("Pilot duty available for %d log files.\n" % len(pilot))

    def evse_rating(d):
        """Prefer the J1772 pilot advertisement; fall back to observed current."""
        vals = [pilot[p] for p in d["paths"] if p in pilot]
        if vals:
            adv = sorted(vals)[len(vals) // 2]
            return "%.0f A EVSE (pilot)" % adv, adv
        i_max = d["i_max"]
        if i_max >= 33.0:
            return "40 A EVSE (inferred)", None
        if i_max >= 22.0:
            return "32 A EVSE (inferred)", None
        if i_max >= 15.0:
            return "~24 A EVSE (inferred)", None
        if i_max >= 10.0:
            return "~16 A EVSE (inferred)", None
        return "low-current (inferred)", None

    def supply_class(v_ref):
        if v_ref >= 230.0:
            return "240 V nominal"
        if v_ref >= 200.0:
            return "208 V nominal"
        return "208 V nominal (weak / low site voltage)"

    # Reference voltage for supply classification must approximate OPEN-CIRCUIT
    # voltage. Using a loaded voltage misclassifies: capture 20260715_202222 is a
    # duty-cycled logger whose 5 s fragments each sit at a single current, so no
    # fragment fits on its own and v_p95 (228.6 V, loaded at 23.5 A) fell just
    # under the 240 V cutoff -- despite the same outlet reading 241.9 V at 7.6 A.
    #
    # Fix: pool fragments per OUTLET, where an outlet is (capture event, pilot
    # advertised current). That keeps the two different EVSEs inside capture
    # 20260714_161319 apart (40 A at ~190 V vs 29 A at ~208 V) while joining the
    # fragments that really do share a supply.
    outlet_pool = defaultdict(list)
    for d in rows:
        d["evse"], d["evse_adv"] = evse_rating(d)
        d["outlet"] = (d["source"], d["group"], round(d["evse_adv"] or 0, 1))
        outlet_pool[d["outlet"]].extend(d["loaded"])

    outlet_voc = {}
    for key, pool in outlet_pool.items():
        lr, lvoc, lcorr, levels = level_fit(pool, min_level_samples=5)
        if (lr is not None and lr > 0 and lcorr is not None and lcorr <= -0.8
                and len(levels) >= 3):
            outlet_voc[key] = (lvoc, lr)

    # Measured open-circuit anchors take precedence over fitted intercepts.
    # A load dump gives the supply voltage directly; a fitted intercept is an
    # extrapolation. Anchors are computed per outlet over all its sessions.
    outlet_series = defaultdict(list)
    for d in rows:
        outlet_series[d["outlet"]].extend(d["series"])
    outlet_anchor = {}
    for key, ser in outlet_series.items():
        voc, i_at, n = load_dump_anchor(ser)
        if voc is None:
            i_at, voc, n = lowest_current_anchor(ser)
            if voc is None:
                continue
        outlet_anchor[key] = (voc, i_at, n)
    n_dump = sum(1 for k, s in outlet_series.items()
                 if load_dump_anchor(s)[0] is not None)
    print("Open-circuit anchors: %d of %d outlets, of which %d from a true "
          "load dump (<=0.5 A)." % (len(outlet_anchor), len(outlet_series), n_dump))

    R_TYP = 0.49  # dataset median, used only when nothing better is available

    buckets = defaultdict(list)
    for d in rows:
        # Priority: measured anchor > outlet-pooled fit > session fit >
        # load-compensated guess. Keying the supply class off the MEASURED
        # open-circuit voltage also stops one physical outlet splitting across
        # two buckets when different captures of it are caught at different
        # points in the ramp (the 40 A site did exactly that).
        if d["outlet"] in outlet_anchor:
            v_ref = outlet_anchor[d["outlet"]][0]
            d["v_ref_src"] = "measured"
        elif d["outlet"] in outlet_voc:
            v_ref = outlet_voc[d["outlet"]][0]
            d["v_ref_src"] = "outlet fit"
        elif d["lvoc"] is not None and d["lcorr"] is not None and d["lcorr"] <= -0.8:
            v_ref = d["lvoc"]
            d["v_ref_src"] = "session fit"
        else:
            v_ref = d["v_p95"] + R_TYP * d["i_med"]
            d["v_ref_src"] = "compensated"
        d["v_ref"] = v_ref
        d["supply"] = supply_class(v_ref)
        d["derate"] = (d["i_max"] / d["evse_adv"]) if d["evse_adv"] else None
        buckets[(d["supply"], d["evse"])].append(d)

    for key in sorted(buckets, key=lambda k: (k[0], k[1])):
        grp = buckets[key]
        vmed = sorted(d["v_med"] for d in grp)
        imax = sorted(d["i_max"] for d in grp)
        fits = sorted(d["lr"] for d in grp
                      if d["lr"] is not None and d["lr"] > 0 and d["nlevels"] >= 3
                      and d["lcorr"] is not None and d["lcorr"] <= -0.8)
        print("\n%-42s %-20s  %d sessions" % (key[0], key[1], len(grp)))
        print("   Vac under load : min %.1f  median %.1f  max %.1f"
              % (vmed[0], pct(vmed, 0.5), vmed[-1]))
        print("   peak Iac       : median %.1f A" % pct(imax, 0.5))
        if fits:
            print("   source R       : median %.3f ohm  (n=%d good fits, range %.3f-%.3f)"
                  % (pct(fits, 0.5), len(fits), fits[0], fits[-1]))
        else:
            print("   source R       : no session in this bucket has enough current spread")
        der = [d["derate"] for d in grp if d["derate"]]
        if der:
            print("   truck derate   : draws %.0f%% of the pilot-advertised current"
                  % (100.0 * pct(sorted(der), 0.5)))
        for d in sorted(grp, key=lambda x: x["when"] or "")[:4]:
            print("      e.g. %s  %-28s Vac med %.1f, Imax %.1f"
                  % (d["when"] or "?", d["file"][:28], d["v_med"], d["i_max"]))

    # ---- Phase 7: resistance per supply/EVSE bucket ----
    # Each (nominal supply voltage, EVSE advertised current) pairing is its own
    # bucket. Individual sessions often sit at a single plateau and cannot be
    # fitted alone, so the bucket's samples are also pooled and fitted together.
    print("\n" + "=" * 104)
    print("SOURCE RESISTANCE PER EVSE BUCKET")
    print("=" * 104)

    def nominal(v_ref):
        if v_ref >= 230.0:
            return 240
        if v_ref >= 196.0:
            return 208
        return 190  # measurably below a healthy 208 V service

    bkt = defaultdict(list)
    for d in rows:
        adv = d["evse_adv"]
        adv_lbl = "%.0f A" % adv if adv else "unknown"
        bkt[(nominal(d["v_ref"]), adv_lbl)].append(d)

    print("%-8s %-8s %8s %8s %7s %14s %8s %13s %13s %13s"
          % ("nominal", "EVSE", "sessions", "capture", "outlets", "Vac med(range)",
             "Iac typ", "R per-sess", "R fixed-eff", "R steps"))
    print("%-8s %-8s %8s %8s %7s %14s %8s %13s %13s %13s"
          % ("supply", "advert", "", "events", "", "", "",
             "median (n)", "slope (n)", "median (n)"))
    print("-" * 124)
    for key in sorted(bkt, key=lambda k: (-k[0], k[1])):
        grp = bkt[key]
        vmed = sorted(d["v_med"] for d in grp)
        imed = sorted(d["i_med"] for d in grp)
        groups = set(d["group"] for d in grp)
        outlets = set(d["outlet"] for d in grp)

        # Median of the individually-valid per-session fits.
        sfits = sorted(d["lr"] for d in grp
                       if d["lr"] is not None and d["lr"] > 0 and d["nlevels"] >= 3
                       and d["lcorr"] is not None and d["lcorr"] <= -0.8)
        sess_txt = "%.3f (%d)" % (pct(sfits, 0.5), len(sfits)) if sfits else "-"

        # Within-session-centred pooled fit: shares one slope across the bucket
        # but gives every session its own intercept, so day-to-day differences
        # in the supply's baseline voltage cannot bias the resistance.
        fe_r, fe_corr, fe_n, _fe_s = fixed_effects_fit([d["loaded"] for d in grp])
        fe_txt = ("%.3f (%d)" % (fe_r, fe_n)
                  if fe_r and fe_r > 0 and fe_corr is not None and fe_corr <= -0.3
                  else "-")

        # Fast-step estimates: immune to slow drift as well as baseline offset.
        # settle_s=30: the sweep below shows the estimate converges past ~20 s;
        # shorter windows measure a voltage that has not finished settling.
        steps = [s for d in grp for s in step_estimates(d["series"], settle_s=30.0)]
        st_txt = ("%.3f (%d)" % (pct(sorted(s[0] for s in steps), 0.5), len(steps))
                  if len(steps) >= 3 else "-")

        print("%-8s %-8s %8d %8d %7d %14s %8s %13s %13s %13s"
              % ("%d V" % key[0], key[1], len(grp), len(groups), len(outlets),
                 "%.0f (%.0f-%.0f)" % (pct(vmed, 0.5), vmed[0], vmed[-1]),
                 "%.1f A" % pct(imed, 0.5), sess_txt, fe_txt, st_txt))

    # Why is the step estimator lower than the regression estimators? Either the
    # voltage has not settled within the comparison window (an artifact, which
    # would shrink as the window grows), or the whole-session regressions are
    # inflated by slow grid drift correlated with the charge profile (real, and
    # the window length would not matter). Sweep the window to tell them apart.
    # Does the ramp-DOWN (CV taper) side agree with the ramp-UP side? If the
    # supply is ohmic they must match; a systematic difference would mean one
    # side is picking up something else (heating, or drift over the charge).
    print("\nPlateau-pair estimator, ramp-UP vs ramp-DOWN (all buckets):")
    print("  %-16s %8s %9s %9s %9s %9s"
          % ("bucket", "pairs", "up n", "up R", "down n", "down R"))
    for key in sorted(bkt, key=lambda k: (-k[0], k[1])):
        pr = [p for d in bkt[key] for p in plateau_pair_estimates(d["series"])]
        up = sorted(p[0] for p in pr if p[2] == "up")
        dn = sorted(p[0] for p in pr if p[2] == "down")
        if not pr:
            continue
        print("  %-16s %8d %9d %9s %9d %9s"
              % ("%d V / %s" % (key[0], key[1]), len(pr),
                 len(up), ("%.3f" % pct(up, 0.5)) if len(up) >= 3 else "-",
                 len(dn), ("%.3f" % pct(dn, 0.5)) if len(dn) >= 3 else "-"))

    allpairs = [p for d in rows for p in plateau_pair_estimates(d["series"])]
    up_all = sorted(p[0] for p in allpairs if p[2] == "up")
    dn_all = sorted(p[0] for p in allpairs if p[2] == "down")
    print("  ALL: %d pairs -- up n=%d median %.3f | down n=%d median %.3f"
          % (len(allpairs), len(up_all), pct(up_all, 0.5) if up_all else float("nan"),
             len(dn_all), pct(dn_all, 0.5) if dn_all else float("nan")))

    # ---- Extension-cord A/B ----
    # Two captures at what appears to be the same outlet (near-identical fitted
    # open-circuit voltage), one charging through an extension cord and one after
    # repositioning so the EVSE cable reached directly.
    print("\n" + "=" * 104)
    print("EXTENSION CORD A/B")
    print("=" * 104)
    ab = [("WITH extension", "vtruxextensioncabletest"),
          ("WITHOUT extension", "chargingafterturningaroundandnotusingextension")]
    ab_res = {}
    for label, needle in ab:
        for d in rows:
            if needle.lower() in d["file"].lower():
                steps = step_estimates(d["series"], settle_s=30.0)
                pairs = plateau_pair_estimates(d["series"])
                ab_res[label] = (d, steps, pairs)
                print("\n%s -- %s  (%s)" % (label, d["file"], d["when"]))
                print("   plateau ladder fit : R=%.3f ohm  Voc=%.1f V  r=%.4f  (%d levels)"
                      % (d["lr"], d["lvoc"], d["lcorr"], d["nlevels"]))
                print("   fast steps         : %s"
                      % ("%.3f ohm (n=%d)" % (pct(sorted(s[0] for s in steps), 0.5),
                                              len(steps)) if steps else "none"))
                print("   plateau pairs      : %s"
                      % ("%.3f ohm (n=%d)" % (pct(sorted(p[0] for p in pairs), 0.5),
                                              len(pairs)) if pairs else "none"))
                print("   Iac %.1f-%.1f A, Vac med %.1f V"
                      % (min(x[1] for x in d["loaded"]),
                         max(x[1] for x in d["loaded"]), d["v_med"]))
                for i_lvl, v_lvl, cnt in d["levels"]:
                    print("      plateau %5.1f A -> %6.1f V (n=%d)" % (i_lvl, v_lvl, cnt))
                break
    if len(ab_res) == 2:
        a = ab_res["WITH extension"][0]
        b = ab_res["WITHOUT extension"][0]
        print("\n   DELTA: R %.3f -> %.3f ohm  (extension adds %+.3f ohm)"
              % (a["lr"], b["lr"], a["lr"] - b["lr"]))
        print("   Voc %.1f vs %.1f V (%.1f V apart -- consistent with the same supply)"
              % (a["lvoc"], b["lvoc"], abs(a["lvoc"] - b["lvoc"])))
        dr = a["lr"] - b["lr"]
        print("   For reference, %.3f ohm round-trip is about %.0f ft of 12 AWG"
              % (dr, dr / (2 * 0.001588)))
        print("   or about %.0f ft of 10 AWG copper." % (dr / (2 * 0.000999)))

    print("\nStep-estimator sensitivity to settle window (240 V / 31 A bucket):")
    big = None
    for key, grp in bkt.items():
        if key[0] == 240 and key[1] == "31 A":
            big = grp
    if big:
        print("  %-10s %-12s %-10s %s" % ("settle s", "min step A", "n steps", "R median"))
        for settle in (5.0, 10.0, 20.0, 40.0, 90.0):
            for mstep in (3.0, 6.0):
                st = [s for d in big
                      for s in step_estimates(d["series"], min_step_a=mstep,
                                              settle_s=settle)]
                if len(st) >= 3:
                    print("  %-10.0f %-12.0f %-10d %.3f"
                          % (settle, mstep, len(st),
                             pct(sorted(s[0] for s in st), 0.5)))

    print("\n" + "=" * 104)
    print("OPEN-CIRCUIT ANCHORS PER BUCKET (measured, not extrapolated)")
    print("V @ min I is the p95 voltage at the lowest current bin with data.")
    print("=" * 104)
    print("%-8s %-8s %8s %8s %10s %8s %9s %9s %8s"
          % ("supply", "EVSE", "outlets", "min I A", "V @ minI", "src",
             "max I A", "V @ maxI", "drop V"))
    for key in sorted(bkt, key=lambda k: (-k[0], k[1])):
        grp = bkt[key]
        outs = set(d["outlet"] for d in grp)
        anch = [(outlet_anchor[o][1], outlet_anchor[o][0]) for o in outs
                if o in outlet_anchor]
        if not anch:
            continue
        i_lo = min(a[0] for a in anch)
        v_at = max(a[1] for a in anch if a[0] == i_lo)
        dump = any(o in outlet_anchor and outlet_anchor[o][1] <= 0.5 for o in outs)
        i_hi = max(d["i_max"] for d in grp)
        v_hi = pct(sorted(d["v_med"] for d in grp if d["i_max"] >= i_hi - 1.5), 0.5)
        print("%-8s %-8s %8d %8.1f %10.1f %8s %9.1f %9.1f %8.2f"
              % ("%d V" % key[0], key[1], len(outs), i_lo, v_at,
                 "dump" if dump else "low-I", i_hi, v_hi, v_at - v_hi))

    print("\nBucket detail (capture events and dates):")
    for key in sorted(bkt, key=lambda k: (-k[0], k[1])):
        grp = bkt[key]
        dates = sorted(set((d["when"] or "?")[:10] for d in grp))
        groups = sorted(set(str(d["group"]) for d in grp))
        print("  %d V / %s : %d sessions over %d capture event(s)"
              % (key[0], key[1], len(grp), len(groups)))
        print("      dates : %s" % ", ".join(dates[:8]))
        print("      capture: %s" % ", ".join(g[-28:] for g in groups[:4]))

    print("\n--- Is the 180-190 V range a single event? ---")
    lowv = sorted([d for d in rows if d["v_med"] < 196.0], key=lambda d: d["v_med"])
    print("%d of %d sessions have median Vac < 196 V:" % (len(lowv), len(rows)))
    for d in lowv:
        print("   %-7s %-16s %-30s Vac med %.1f  Imax %.1f  (%s)"
              % (d["source"], d["when"] or "?", d["file"][:30], d["v_med"],
                 d["i_max"], d["evse"]))
    print("   distinct capture events: %s"
          % ", ".join(sorted(set(str(d["group"]) for d in lowv))))

    print("\n=== SESSION-MEDIAN Vac DISTRIBUTION (all %d sessions) ===" % len(rows))
    allv = sorted(d["v_med"] for d in rows)
    for label, p in (("min", 0.0), ("p05", 0.05), ("p25", 0.25), ("median", 0.5),
                     ("p75", 0.75), ("p95", 0.95), ("max", 1.0)):
        print("  Vac %-6s = %.1f V" % (label, pct(allv, p)))


if __name__ == "__main__":
    main()
