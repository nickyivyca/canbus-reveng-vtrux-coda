"""
flat_section_roadload.py

Road-load extraction (Crr, CdA) from the long flat sections of the
2026-07-24/26 weekend trip -- the attempt that failed on the earlier five-log
sample (see notes/energy-consumption.md "What did not work").

Two things are different this time:
  1. The sections are genuinely flat -- constant barometric altitude -- so grade,
     which dominated every earlier attempt, is largely removed by selection
     rather than by a coarse correction.
  2. Air density is computed per-window from CAN (0x2C3 ambient pressure +
     0x4C1 outside air temperature) instead of assumed, so the aero regressor
     is rho*v^2 and its coefficient is directly CdA/2.

WIND. These are one-way runs, not out-and-back, so wind cannot be cancelled by
direction pairing. Instead it is ESTIMATED: fitting the general form

    F = F0 + F1*v + c*(rho*v^2)

against a road-load model with a steady headwind w

    F = F0_true + c*rho*(v+w)^2
      = [F0_true + c*rho*w^2] + [2*c*rho*w]*v + c*rho*v^2

identifies w = F1 / (2*c*rho) PROVIDED the physical F1 (tyre and driveline
speed-dependent losses) is negligible. That is an assumption, not a
measurement, but it is testable in one direction: the recovered w must come out
a plausible wind speed. A w of 30 m/s means the model is wrong, not that it was
windy.

Forces are "apparent at the DC bus": derived from traction inverter DC power
(0x462), so they include inverter, motor and gearbox losses. CdA and Crr
reported here are therefore inflated by roughly 1/eta relative to true
mechanical values.

Usage:
  python3.13 projects/vtrux/notes/artifacts/flat_section_roadload.py [chars|fit]
"""

import sys
import math
from pathlib import Path

sys.path.insert(0, ".")
_argv = list(sys.argv)
sys.argv = ["x"]
exec(Path("projects/vtrux/notes/artifacts/wh_per_mile_estimate.py")
     .read_text().split("if __name__ ==")[0])
sys.argv = _argv

R_AIR = 287.05
RHO_REF = 1.225

# (session, t_start, t_end, label) -- windows chosen from the phase table in
# notes/weekend-trip-2026-07-24.md
# Session-relative time bounds taken from the phase table in
# notes/weekend-trip-2026-07-24.md. These MUST exclude the climbs and descents:
# passing the whole session lets the +418 m / -424 m legs in and the fit becomes
# meaningless (a 45 km/h window on a climb shows 7200 N of "road load").
SECTIONS = [
    # 14:26:28 -> 15:05:35, all phases dh = 0, at -97 m. Ends where GEN-CLIMB starts.
    ("@20260726_142628", 0, 2340, "Sun 14:26-15:05 flat at -97 m"),
    # 16:42:42 -> 17:08:55, dh = 0/-41, incl. the 17.9 mi @ 97 km/h run.
    # Ends before the 17:15 GEN-CLIMB (+418 m).
    ("@20260726_160923", 2000, 3570, "Sun 16:42-17:09 flat, incl 17.9 mi @ 97 km/h"),
]

WIN = 10.0          # s per cruise window
V_MIN = 40.0        # km/h
V_SPREAD = 2.0      # km/h max-min inside the window
V_DRIFT = 1.0       # km/h |end-start|


def ambient(F, S):
    """Constant ambient pressure (Pa) for the section, from engine-off MAP."""
    n = len(F["t"])
    mapk = S.get("map_obd") or S.get("map_veh")
    if not mapk:
        return None
    f, _ = zoh(mapk)
    mv = [f(t) for t in F["t"]]
    off = 0
    vals = []
    for i in range(n):
        off = off + 1 if not F["eng_on"][i] else 0
        if off >= 10:
            vals.append(mv[i])
    if len(vals) < 60:
        return None
    vals.sort()
    return vals[int(0.9 * (len(vals) - 1))] * 1000.0


def windows(F, S, p_amb, t0=None, t1=None):
    """Steady-cruise windows with per-window force and air density."""
    n = len(F["t"])
    dt = F["dt"]
    W = int(WIN / dt)
    f_oat = zoh(S["oat"])[0] if "oat" in S else None
    f_cru = zoh(S["cruise_mode"])[0] if "cruise_mode" in S else None
    out = []
    i = 0 if t0 is None else max(0, int((t0 - F["t"][0]) / dt))
    n = n if t1 is None else min(n, int((t1 - F["t"][0]) / dt))
    while i + W < n:
        v = F["kph"][i:i + W]
        if min(v) >= V_MIN and (max(v) - min(v)) <= V_SPREAD \
                and abs(v[-1] - v[0]) <= V_DRIFT:
            vm = sum(v) / W / 3.6                       # m/s
            p = sum(F["trac"][i:i + W]) / W             # W at the DC bus
            oat = f_oat(F["t"][i]) if f_oat else 20.0
            rho = p_amb / (R_AIR * (oat + 273.15))
            out.append({"v": vm, "F": p / vm, "rho": rho, "oat": oat,
                        "t": F["t"][i], "i": i, "p": p,
                        "eng": sum(1 for x in F["eng_on"][i:i + W] if x) > W / 2,
                        "cruise": f_cru(F["t"][i]) if f_cru else None})
            i += W
        else:
            i += 1
    return out


def fit(rows, cols, label):
    A = [[r[c] for c in cols] for r in rows]
    y = [r["F"] for r in rows]
    b = lstsq(A, y)
    if not b:
        print("    %-34s singular" % label)
        return None
    pred = [sum(A[i][j] * b[j] for j in range(len(cols))) for i in range(len(A))]
    ssr = sum((y[i] - pred[i]) ** 2 for i in range(len(y)))
    ybar = sum(y) / len(y)
    sst = sum((t - ybar) ** 2 for t in y)
    r2 = 1 - ssr / sst if sst else 0
    rmse = (ssr / len(y)) ** 0.5
    print("    %-34s n=%-4d R2=%.3f RMSE=%5.0f N   %s"
          % (label, len(rows), r2, rmse,
             "  ".join("%s=%+.4f" % (c, v) for c, v in zip(cols, b))))
    return b


def report_curve(F0, c, label, w=0.0):
    print("\n    %s" % label)
    print("      Crr(apparent) = %.4f at %.0f kg   CdA(apparent) = %.2f m^2"
          % (F0 / (MASS_KG * G), MASS_KG, 2 * c))
    print("      %6s %7s %9s %9s" % ("km/h", "mph", "force N", "Wh/mi"))
    for kph in (40, 56, 72, 88, 104, 112):
        v = kph / 3.6
        f = F0 + c * RHO_REF * v * v
        print("      %6d %7.0f %9.0f %9.0f" % (kph, kph / KM_PER_MI, f, f * 0.44704))


def main(what):
    allw = []
    for spec, t0, t1, label in SECTIONS:
        S = load(spec)
        F = build(spec)
        p_amb = ambient(F, S)
        if p_amb is None:
            print("%s: no ambient pressure" % spec)
            continue
        alt = -H_SCALE * math.log((p_amb / 1000.0) / 101.325)
        w = windows(F, S, p_amb, t0, t1)
        for x in w:
            x["spec"] = spec
        allw.extend(w)
        oats = [x["oat"] for x in w]
        rhos = [x["rho"] for x in w]
        print("=" * 78)
        print("%s  --  %s" % (spec, label))
        print("  ambient %.1f kPa (alt %+.0f m)  OAT %.0f-%.0f C  rho %.3f-%.3f kg/m3"
              % (p_amb / 1000, alt, min(oats), max(oats), min(rhos), max(rhos))
              if w else "  no windows")
        print("  %d steady windows (%.0f s of cruise), engine on in %d of them"
              % (len(w), len(w) * WIN, sum(1 for x in w if x["eng"])))
        if w:
            sv = sorted(x["v"] * 3.6 for x in w)
            print("  speed range %.0f-%.0f km/h (p10 %.0f, p50 %.0f, p90 %.0f)"
                  % (sv[0], sv[-1], sv[len(sv) // 10], sv[len(sv) // 2],
                     sv[len(sv) * 9 // 10]))
            neg = sum(1 for x in w if x["p"] < 0)
            print("  windows with NEGATIVE traction power (downhill): %d" % neg)
            cru = [x["cruise"] for x in w if x["cruise"] is not None]
            if cru:
                from collections import Counter
                print("  cruise_mode histogram: %s" % dict(Counter(cru)))

    if what == "chars" or not allw:
        return

    print("\n" + "=" * 78)
    print("ROAD-LOAD FIT   (F = force at the DC bus = P_trac / v)")
    print("=" * 78)
    for r in allw:
        r["one"] = 1.0
        r["rv2"] = r["rho"] * r["v"] * r["v"]
    pos = [r for r in allw if r["p"] > 0]
    print("\n  Using %d windows with positive traction power" % len(pos))
    b2 = fit(pos, ["one", "rv2"], "2-param  F0 + c*rho*v^2")
    b3 = fit(pos, ["one", "v", "rv2"], "3-param  F0 + F1*v + c*rho*v^2")

    if b3:
        F0f, F1, c = b3
        rho_bar = sum(r["rho"] for r in pos) / len(pos)
        if c > 0:
            w_est = F1 / (2 * c * rho_bar)
            F0_true = F0f - c * rho_bar * w_est * w_est
            print("\n  Wind identification from the linear term:")
            print("    F1 = %+.2f N/(m/s)  ->  headwind w = F1/(2*c*rho) = %+.2f m/s"
                  " (%+.0f km/h)" % (F1, w_est, w_est * 3.6))
            print("    still-air F0 = F0_fit - c*rho*w^2 = %.0f - %.0f = %.0f N"
                  % (F0f, c * rho_bar * w_est ** 2, F0_true))
            report_curve(F0_true, c, "STILL-AIR curve (wind removed)")
        else:
            print("\n  c <= 0: aero term still unphysical, wind cannot be identified")

    if b2:
        report_curve(b2[0], b2[1], "2-param curve (no wind term)")

    # --- split-half consistency: a direction change or wind shift shows here --
    print("\n  Split-half check (first vs second half of the window sequence):")
    half = len(pos) // 2
    for nm, sub in (("first half", pos[:half]), ("second half", pos[half:])):
        fit(sub, ["one", "v", "rv2"], nm)

    # --- residual structure vs speed -----------------------------------------
    if b3:
        print("\n  Residuals vs speed (3-param fit) -- structure here means the")
        print("  model shape is wrong, not just noisy:")
        print("      %8s %5s %9s %9s" % ("km/h bin", "n", "mean res", "sd"))
        for lo in range(40, 120, 10):
            b = [r for r in pos if lo <= r["v"] * 3.6 < lo + 10]
            if len(b) < 5:
                continue
            res = [r["F"] - (b3[0] + b3[1] * r["v"] + b3[2] * r["rv2"]) for r in b]
            m = sum(res) / len(res)
            sd = (sum((x - m) ** 2 for x in res) / len(res)) ** 0.5
            print("      %5d-%-3d %5d %9.0f %9.0f" % (lo, lo + 10, len(b), m, sd))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "fit")


def bins(allw):
    """Empirical F vs v, no model. Median is grade-robust if grade is
    zero-mean within the bin."""
    print("\n" + "=" * 78)
    print("EMPIRICAL binned force (no fitting)")
    print("  %8s %5s %8s %8s %8s %8s %9s" % ("km/h", "n", "q1 N", "med N",
                                             "q3 N", "IQR N", "med Wh/mi"))
    pts = []
    for lo in range(40, 120, 10):
        b = sorted(r["F"] for r in allw if lo <= r["v"] * 3.6 < lo + 10)
        if len(b) < 5:
            continue
        q1, med, q3 = b[len(b) // 4], median(b), b[len(b) * 3 // 4]
        print("  %5d-%-3d %5d %8.0f %8.0f %8.0f %8.0f %9.0f"
              % (lo, lo + 10, len(b), q1, med, q3, q3 - q1, med * 0.44704))
        pts.append((lo + 5, med, len(b)))
    return pts
