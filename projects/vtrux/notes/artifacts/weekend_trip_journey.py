"""
weekend_trip_journey.py

Deep dive on the 2026-07-24/26 weekend trip: reconstruct the journey as an
ordered sequence of PHASES and EVENTS from CAN alone.

Reuses the extraction and helpers from wh_per_mile_estimate.py; run its
`extract` phase for the weekend sessions first.

Phase classification is driven by three state variables:
  * moving        -- speed > 2 km/h
  * engine_on     -- engine RPM > 300 (0x0C9, else 0x054 generator RPM)
  * charging      -- pack taking >1 kW while stationary with the engine off
and, for driving phases, the net elevation change over the phase.

ELEVATION CAVEAT: the 0x2C3 MAP altimeter only reads ambient with the engine
OFF. Engine-on stretches therefore have no direct altitude, and altitude across
them is linearly interpolated *against distance* between the bracketing
engine-off fixes. Interpolated phases are flagged `~` in the output. Net dh
across an engine-on window is still real (both endpoints are measured); only
the shape within it is assumed.

Usage:
  python3.13 projects/vtrux/notes/artifacts/weekend_trip_journey.py [phases|events|all]
"""

import sys
import json
import math
from pathlib import Path

sys.path.insert(0, ".")
sys.argv_backup = list(sys.argv)
sys.argv = ["x"]
_SRC = Path("projects/vtrux/notes/artifacts/wh_per_mile_estimate.py").read_text()
exec(_SRC.split('if __name__ ==')[0])
sys.argv = sys.argv_backup

ART = Path("projects/vtrux/notes/artifacts")
SESSIONS = [
    "@20260724_160300", "@20260724_160330", "@20260724_162517",
    "@20260724_172621", "@20260724_211556",
    "@20260725_102702", "@20260725_102722", "@20260725_110930",
    "@20260725_115341", "@20260725_120147", "@20260725_170050",
    "@20260725_181009",
    "@20260726_124205", "@20260726_142628", "@20260726_160923",
    "@20260726_191901",
]

GRADE_CLIMB = 0.010      # >= +1.0% average over the phase
MIN_PHASE_S = 60.0       # merge anything shorter into its neighbour
CHG_W = 1000.0           # pack charge power that counts as "charging"


def session_epoch(spec):
    """Wall-clock seconds-since-Friday-midnight from the session name."""
    s = spec.lstrip("@")
    d, t = s.split("_")
    day = int(d[6:8])
    return (day - 24) * 86400 + int(t[:2]) * 3600 + int(t[2:4]) * 60 + int(t[4:6])


def clock(sec):
    d = int(sec // 86400)
    r = sec - d * 86400
    return "%s %02d:%02d:%02d" % (["Fri", "Sat", "Sun", "Mon"][d],
                                  int(r // 3600), int(r % 3600 // 60), int(r % 60))


def raw_alt(F):
    """Altitude with genuine gaps.

    wh_per_mile_estimate.build() HOLDS the last altitude through engine-on
    stretches, which silently attributes a climb to whenever MAP resumes rather
    than to when it happened. For phase-level work we need real Nones, so this
    recomputes from 0x2C3 with the engine-off gate and leaves gaps as None.
    """
    S = F["S"]
    n = len(F["t"])
    mapk = S.get("map_obd") or S.get("map_veh")
    if not mapk:
        return [None] * n
    f, _ = zoh(mapk)
    mv = [f(t) for t in F["t"]]
    off_run = 0
    raw = []
    for i in range(n):
        off_run = off_run + 1 if not F["eng_on"][i] else 0
        raw.append(mv[i] if off_run >= 10 else None)
    out = []
    for i in range(n):
        w = sorted(x for x in raw[max(0, i - 60):i + 61] if x is not None)
        # Require a real body of ambient samples AND low spread. A lone
        # contaminated reading (manifold vacuum that slipped past the engine-off
        # gate) otherwise survives any quantile and injects a huge altitude
        # spike -- two such samples produced a bogus +1237 m in 20260724_172621.
        # Better to report NO altitude than a wrong one; gaps get interpolated.
        if len(w) >= 20 and (w[-1] - w[0]) <= 2.0:
            out.append(-H_SCALE * math.log(w[int(0.9 * (len(w) - 1))] / 101.325))
        else:
            out.append(None)
    return out


def interp_alt(F):
    """Altitude on the grid, gap-filled against distance. Returns (alt, is_interp)."""
    n = len(F["t"])
    raw = raw_alt(F)
    known = [(i, raw[i]) for i in range(n) if raw[i] is not None]
    if not known:
        return [None] * n, [True] * n
    out = [None] * n
    interp = [False] * n
    d = F["dist_m"]
    for k in range(len(known) - 1):
        i0, a0 = known[k]
        i1, a1 = known[k + 1]
        out[i0] = a0
        span = d[i1] - d[i0]
        for i in range(i0 + 1, i1):
            out[i] = a0 + (a1 - a0) * ((d[i] - d[i0]) / span if span > 1 else
                                       (i - i0) / (i1 - i0))
            interp[i] = True
    out[known[-1][0]] = known[-1][1]
    for i in range(0, known[0][0]):
        out[i] = known[0][1]
        interp[i] = True
    for i in range(known[-1][0] + 1, n):
        out[i] = known[-1][1]
        interp[i] = True
    return out, interp


def classify(F, alt, i0, i1):
    dt = F["dt"]
    kph = F["kph"][i0:i1]
    moving = sum(1 for k in kph if k > 2.0) / max(1, len(kph)) > 0.5
    eng = sum(1 for x in F["eng_on"][i0:i1] if x) / max(1, i1 - i0) > 0.5
    dist = F["dist_m"][i1 - 1] - F["dist_m"][i0]
    pack = F["pack"][i0:i1]
    if not moving:
        if eng:
            return "GEN-IDLE"
        if sum(pack) / max(1, len(pack)) > CHG_W:
            return "CHARGING"
        return "PARKED"
    grade = 0.0
    if alt[i0] is not None and alt[i1 - 1] is not None and dist > 50:
        grade = (alt[i1 - 1] - alt[i0]) / dist
    tag = "GEN" if eng else "EV"
    if grade >= GRADE_CLIMB:
        return tag + "-CLIMB"
    if grade <= -GRADE_CLIMB:
        return tag + "-DESCENT"
    return tag + "-CRUISE"


def segment(F, alt):
    """Split the grid into runs of constant (moving, engine, charging) state."""
    n = len(F["t"])
    dt = F["dt"]
    st = []
    for i in range(n):
        mv = F["kph"][i] > 2.0
        en = F["eng_on"][i]
        ch = (not mv) and (not en) and F["pack"][i] > CHG_W
        st.append((mv, en, ch))
    # median filter the state to suppress 1-sample chatter
    W = 15
    sm = []
    for i in range(n):
        w = st[max(0, i - W):i + W + 1]
        sm.append(tuple(sum(1 for x in w if x[j]) > len(w) / 2 for j in range(3)))
    bounds = [0]
    for i in range(1, n):
        if sm[i] != sm[i - 1]:
            bounds.append(i)
    bounds.append(n)
    segs = []
    for k in range(len(bounds) - 1):
        i0, i1 = bounds[k], bounds[k + 1]
        if (i1 - i0) * dt < MIN_PHASE_S and segs:
            segs[-1] = (segs[-1][0], i1)
        else:
            segs.append((i0, i1))
    return segs


def phase_stats(F, alt, interp, i0, i1):
    dt = F["dt"]
    sl = slice(i0, i1)
    dur = (i1 - i0) * dt
    dist = F["dist_m"][i1 - 1] - F["dist_m"][i0]
    mi = dist / 1000.0 / KM_PER_MI
    e_bus = (-integ(F["pack"][sl], dt) + integ(F["gene"][sl], dt)) / 3.6e6
    e_gen = integ(F["gene"][sl], dt) / 3.6e6
    e_trac = integ(F["trac"][sl], dt) / 3.6e6
    e_out = integ([max(p, 0) for p in F["trac"][sl]], dt) / 3.6e6
    e_reg = -integ([min(p, 0) for p in F["trac"][sl]], dt) / 3.6e6
    dh = None
    if alt[i0] is not None and alt[i1 - 1] is not None:
        dh = alt[i1 - 1] - alt[i0]
    return {"dur": dur, "mi": mi, "kph": dist / 1000 / (dur / 3600) if dur else 0,
            "vmax": max(F["kph"][sl]) if i1 > i0 else 0,
            "e_bus": e_bus, "e_gen": e_gen, "e_trac": e_trac,
            "regen": e_reg / (e_out + e_reg) if (e_out + e_reg) > 0.01 else None,
            "whmi": e_bus * 1000 / mi if mi > 0.2 else None,
            "dh": dh, "interp": any(interp[i0:i1]),
            "alt0": alt[i0], "alt1": alt[i1 - 1]}


def build_journey():
    out = []
    for spec in SESSIONS:
        try:
            S = load(spec)
        except Exception:
            continue
        if "vbat" not in S:
            continue
        F = build(spec)
        F["epoch"] = session_epoch(spec)
        F["spec"] = spec
        F["S"] = S
        alt, interp = interp_alt(F)
        F["alt_i"] = alt
        F["interp_i"] = interp
        out.append(F)
    out.sort(key=lambda f: f["epoch"])
    return out


def do_phases(J):
    print("=" * 100)
    print("WEEKEND JOURNEY -- PHASES   (2026-07-24 Fri .. 2026-07-26 Sun)")
    print("  `~` = altitude interpolated across an engine-on stretch")
    print("=" * 100)
    tot = {"mi": 0.0, "e_bus": 0.0, "e_gen": 0.0}
    for F in J:
        segs = segment(F, F["alt_i"])
        real = [s for s in segs if (s[1] - s[0]) * F["dt"] >= MIN_PHASE_S]
        if not real:
            continue
        dur = (F["t"][-1] - F["t"][0]) / 60
        print("\n--- %s   session %s   (%.0f min) ---"
              % (clock(F["epoch"]), F["spec"], dur))
        print("  %-11s %-13s %7s %7s %7s %7s %8s %8s %7s %6s"
              % ("start", "phase", "mins", "miles", "km/h", "vmax", "dh m",
                 "Wh/mi", "gen kWh", "regen"))
        for i0, i1 in real:
            cls = classify(F, F["alt_i"], i0, i1)
            st = phase_stats(F, F["alt_i"], F["interp_i"], i0, i1)
            if st["dur"] < MIN_PHASE_S:
                continue
            if cls.startswith(("EV-", "GEN-")) and not cls.endswith("IDLE"):
                tot["mi"] += st["mi"]
                tot["e_bus"] += st["e_bus"]
                tot["e_gen"] += st["e_gen"]
            print("  %-11s %-13s %7.1f %7.2f %7.1f %7.1f %8s %8s %7.2f %6s"
                  % (clock(F["epoch"] + F["t"][i0]), cls,
                     st["dur"] / 60, st["mi"], st["kph"], st["vmax"],
                     ("%+.0f%s" % (st["dh"], "~" if st["interp"] else "")
                      if st["dh"] is not None else "n/a"),
                     ("%.0f" % st["whmi"]) if st["whmi"] else "-",
                     st["e_gen"],
                     ("%.0f%%" % (100 * st["regen"])) if st["regen"] else "-"))
    print("\n" + "=" * 100)
    print("JOURNEY TOTAL (driving phases only; charging and idling excluded):")
    print("  %.1f mi, %.1f kWh at the HV bus (%.1f kWh from the"
          " generator = %.0f%%), %.0f Wh/mi"
          % (tot["mi"], tot["e_bus"], tot["e_gen"],
             100 * tot["e_gen"] / tot["e_bus"] if tot["e_bus"] else 0,
             tot["e_bus"] * 1000 / tot["mi"] if tot["mi"] else 0))


def do_events(J):
    """Journey events: engine runs, real refuels, blend adaptation, charging,
    and elevation extrema."""
    print("\n" + "=" * 100)
    print("WEEKEND JOURNEY -- EVENTS")
    print("=" * 100)
    ev = []
    for F in J:
        S = F["S"]
        e0 = F["epoch"]
        dt = F["dt"]
        alt = F["alt_i"]
        n = len(F["t"])
        f_lph = zoh(S["fuel_lph"])[0] if "fuel_lph" in S else None

        ev.append((e0 + F["t"][0], 0, "session start",
                   "alt %s, SoC %.1f%%"
                   % (("%+.0f m" % alt[0]) if alt[0] is not None else "n/a",
                      F["soc"][0])))

        # --- engine RUNS (not individual transitions) ---------------------
        i = 0
        while i < n:
            if not F["eng_on"][i]:
                i += 1
                continue
            j = i
            while j < n and F["eng_on"][j]:
                j += 1
            dur = (j - i) * dt
            if dur >= 30:
                gen = integ(F["gene"][i:j], dt) / 3.6e6
                lit = (sum(f_lph(F["t"][k]) for k in range(i, j)) * dt / 3600.0
                       if f_lph else 0.0)
                dh = (alt[j - 1] - alt[i]) if (alt[i] is not None
                                               and alt[j - 1] is not None) else None
                ev.append((e0 + F["t"][i], 1, "ENGINE RUN %.0f min" % (dur / 60),
                           "%.2f kWh gen, %.2f gal, dh %s, start %s -> end %s"
                           % (gen, lit / L_PER_GAL,
                              ("%+.0f m" % dh) if dh is not None else "n/a",
                              ("%+.0f m" % alt[i]) if alt[i] is not None else "?",
                              ("%+.0f m" % alt[j - 1]) if alt[j - 1] is not None else "?")))
            i = j

        # --- REAL refuels: sustained tank rise while stationary ------------
        if "fuel_pct" in S:
            p = S["fuel_pct"]
            f_kph = zoh([(t, k) for t, k in zip(F["t"], F["kph"])])[0]
            k = 0
            while k < len(p) - 1:
                # compare a settled level before vs after
                t0, v0 = p[k]
                nxt = [(t, v) for t, v in p if t0 < t <= t0 + 900]
                if nxt:
                    vmax = max(v for _, v in nxt)
                    # 15% of tank, not 8%: overnight gauge settling at the
                    # destination produced two false +8/+9% "refuels".
                    if vmax - v0 > 15.0 and f_kph(t0) < 2.0:
                        tend = [t for t, v in nxt if v == vmax][0]
                        ev.append((e0 + t0, 2, "REFUEL",
                                   "tank %.0f%% -> %.0f%% (+%.0f%% of tank)"
                                   % (v0, vmax, vmax - v0)))
                        k = next((x for x in range(len(p)) if p[x][0] > tend), len(p))
                        continue
                k += 1

        # --- flex-sensor adaptation after a fill ---------------------------
        if "eth_pct" in S:
            e = S["eth_pct"]
            first, last = e[0][1], e[-1][1]
            if abs(last - first) > 8.0:
                ev.append((e0 + e[0][0], 3, "fuel blend adapts",
                           "E%.0f -> E%.0f over the session" % (first, last)))

        # --- charging ------------------------------------------------------
        chg = [(F["kph"][i] <= 2.0) and (not F["eng_on"][i])
               and F["pack"][i] > CHG_W for i in range(n)]
        i = 0
        while i < n:
            if not chg[i]:
                i += 1
                continue
            j = i
            while j < n and chg[j]:
                j += 1
            if (j - i) * dt > 600:
                kwh = integ(F["pack"][i:j], dt) / 3.6e6
                ev.append((e0 + F["t"][i], 4, "CHARGE %.0f min" % ((j - i) * dt / 60),
                           "SoC %.1f%% -> %.1f%%, +%.2f kWh"
                           % (F["soc"][i], F["soc"][j - 1], kwh)))
            i = j

        # --- elevation extrema with >150 m prominence -----------------------
        va = [(i, alt[i]) for i in range(0, n, 30) if alt[i] is not None]
        for k in range(1, len(va) - 1):
            i, a = va[k]
            lo = min(x for _, x in va[max(0, k - 40):k])
            hi = max(x for _, x in va[max(0, k - 40):k])
            lo2 = min(x for _, x in va[k + 1:k + 41])
            hi2 = max(x for _, x in va[k + 1:k + 41])
            if a >= hi and a >= hi2 and (a - min(lo, lo2)) > 150:
                ev.append((e0 + F["t"][i], 5, "SUMMIT", "alt %+.0f m" % a))
            if a <= lo and a <= lo2 and (max(hi, hi2) - a) > 150:
                ev.append((e0 + F["t"][i], 5, "low point", "alt %+.0f m" % a))

    ev.sort()
    # collapse repeated summit/low markers within 10 min
    out = []
    for t, pr, lbl, detail in ev:
        if out and lbl in ("SUMMIT", "low point") and out[-1][2] == lbl \
                and t - out[-1][0] < 600:
            continue
        out.append((t, pr, lbl, detail))
    for t, pr, lbl, detail in out:
        print("  %-12s  %-22s %s" % (clock(t), lbl, detail))


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    J = build_journey()
    print("loaded %d sessions with data\n" % len(J))
    if what in ("phases", "all"):
        do_phases(J)
    if what in ("events", "all"):
        do_events(J)
