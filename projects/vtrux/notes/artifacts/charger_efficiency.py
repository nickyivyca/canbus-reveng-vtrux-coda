"""
charger_efficiency.py

Bel on-board charger efficiency vs power, and from-grid Wh/mile.

All four quantities needed come from ONE message, 0x18FFD7C0
(BELINV_hvBatteryAndCharger), so AC input and DC output are sampled
simultaneously and no cross-message time alignment is needed:

    B0:B1  hvBatteryVoltage      x0.05  V DC out
    B2:B3  hvBatteryCurrent      x0.05  A DC out (signed, + = charging)
    B4:B5  chargerInputVoltage   x0.05  V AC RMS in
    B6:B7  chargerInputCurrent   x0.05  A AC RMS in

Sample validity follows notes/ac-resistance.md: 0xFFFF is a no-data sentinel
that decodes to 3276.75 and MUST be filtered, or a handful of samples dominate
every statistic. Accept only 80 <= Vac <= 300 and 0 <= Iac <= 60.

CAVEAT ON P_ac: the charger reports V_RMS and I_RMS, so V*I is apparent power
(VA), not real power (W). The Bel unit is power-factor-corrected so PF is
typically 0.98-0.99 at load, but at LOW power PF degrades, which means the
low-power efficiency computed here is a LOWER BOUND on true efficiency (real
watts drawn are less than VA). This matters precisely where the question is
most interesting, and is flagged in the output.

Usage:
  python3.13 projects/vtrux/notes/artifacts/charger_efficiency.py [sessions|curve|grid]
"""

import sys
import json
import math
from pathlib import Path

sys.path.insert(0, ".")
_argv = list(sys.argv)
sys.argv = ["x"]
exec(Path("projects/vtrux/notes/artifacts/wh_per_mile_estimate.py")
     .read_text().split("if __name__ ==")[0])
sys.argv = _argv

SESSIONS = [
    "vtruxchargeblueevse.log",
    "vtruxchargeafterscottsvalley.log",
    "vtruxchargeafterexportchargetest-80pctcv.log",
    "vtruxchargeafteroverheattest-16asetpoint.log",
    "vtruxchargeafteroverheattest-32asetpoint.log",
    "vtruxchargeafterscottsvalley2-16asetpoint.log",
    "vtruxchargemegearevse.log",
    # Android-logger sessions carrying charger frames, found by scanning the
    # library for 0x18FFD7C0. These roughly triple the sample and, critically,
    # add low-power charging from days OTHER than the post-overheat-test one
    # that the 2-4 kW bins otherwise rest on.
    "@20260627_164210", "@20260726_191901", "@20260714_161319",
    "@20260503_192242", "@20260513_180408", "@20260719_190019",
    "@20260503_171127", "@20260714_102812", "@20260725_102722",
    "@20260714_112312",
]

# Bel unit replaced 2026-05-03 (vtrux_newcharger.log starts 15:52 that day).
# Everything before is the ORIGINAL unit, everything after the REPLACEMENT.
# This matters: all Ixxat charge logs are March (old) and all Android charge
# sessions are May-July (new), so era and logger are perfectly confounded and
# any pooled comparison silently mixes two different devices.
SWAP_DATE = "20260503"

SESSION_DATE = {
    "vtruxchargeblueevse.log": "20260305",
    "vtruxchargeafterscottsvalley.log": "20260305",
    "vtruxchargeafterexportchargetest-80pctcv.log": "20260303",
    "vtruxchargeafteroverheattest-16asetpoint.log": "20260311",
    "vtruxchargeafteroverheattest-32asetpoint.log": "20260311",
    "vtruxchargeafterscottsvalley2-16asetpoint.log": "20260305",
    "vtruxchargemegearevse.log": "20260305",
}


def era(name):
    d = SESSION_DATE.get(name) or (name.lstrip("@").split("_")[0]
                                   if name.startswith("@") else None)
    if not d:
        return "?"
    if d < SWAP_DATE:
        return "OLD"
    return "SWAPDAY" if d == SWAP_DATE else "NEW"


V_MIN, V_MAX = 80.0, 300.0
I_MIN, I_MAX = 0.0, 60.0
P_ON = 200.0        # W of AC draw below which the charger is not really running
I_DC_MIN = 3.0      # A DC below which the charger is holding, not charging


def samples(S):
    """Time-aligned (t, Pac, Pdc, Vac, Iac, Vdc, Idc) with sentinels removed."""
    need = ("ac_v", "ac_i", "dc_v", "dc_i")
    if not all(k in S for k in need):
        return []
    av, ai = dict(S["ac_v"]), dict(S["ac_i"])
    dv, di = dict(S["dc_v"]), dict(S["dc_i"])
    out = []
    for t, vv in S["ac_v"]:
        if t not in ai or t not in dv or t not in di:
            continue
        va, ia, vd, idc = vv, ai[t], dv[t], di[t]
        if not (V_MIN <= va <= V_MAX):
            continue
        if not (I_MIN <= ia <= I_MAX):
            continue
        if not (100.0 <= vd <= 500.0) or abs(idc) > 400.0:
            continue
        # SIGN: BelInverter-v2.dbc comments hvBatteryCurrent as "positive =
        # charging", but the logged value is NEGATIVE throughout every charge
        # session while the pack is demonstrably gaining energy. The magnitude
        # is right (|E_dc|/E_ac lands at 90-93%, a sane charger efficiency), so
        # only the documented sign is wrong. Negated here; DBC comment needs
        # correcting.
        out.append((t, va * ia, vd * (-idc), va, ia, vd, -idc))
    return out


def trapz(ts, vs):
    tot = 0.0
    for i in range(1, len(ts)):
        dt = ts[i] - ts[i - 1]
        if 0 < dt <= 10.0:
            tot += 0.5 * (vs[i] + vs[i - 1]) * dt
    return tot


def do_sessions():
    rows = []
    for name in SESSIONS:
        try:
            S = load(name)
        except Exception:
            print("%-46s (not extracted)" % name)
            continue
        sm = samples(S)
        on = [x for x in sm if x[1] > P_ON]
        if len(on) < 100:
            print("%-46s no charging samples" % name)
            continue
        ts = [x[0] for x in on]
        e_ac = trapz(ts, [x[1] for x in on]) / 3.6e6
        e_dc = trapz(ts, [x[2] for x in on]) / 3.6e6
        # ACTUAL charging time, not first-to-last span: the charger cycles and
        # sessions contain long idle tails, so the span overstates badly.
        dur = trapz(ts, [1.0] * len(ts)) / 3600.0
        span = (ts[-1] - ts[0]) / 3600.0
        pac = sorted(x[1] for x in on)
        vac = sorted(x[3] for x in on)
        # pack-side cross-check from the BMS, independent of the charger
        e_pack = None
        if "vbat" in S and "ibat" in S:
            ib = dict(S["ibat"])
            # Restrict to times the charger was actually ON. Integrating across
            # the whole span counts the pack DISCHARGING into HV aux during idle
            # gaps, which silently wrecks wall-to-pack on any session where
            # charging is intermittent (20260714_161319: 3.28 h of charging
            # inside a 5.63 h span).
            on_t = sorted(ts)
            def charging_at(t, _o=on_t):
                import bisect
                i = bisect.bisect_left(_o, t)
                for j in (i - 1, i):
                    if 0 <= j < len(_o) and abs(_o[j] - t) <= 5.0:
                        return True
                return False
            pk = [(t, v * ib[t]) for t, v in S["vbat"]
                  if t in ib and ts[0] <= t <= ts[-1] and charging_at(t)]
            if pk:
                e_pack = trapz([p[0] for p in pk], [p[1] for p in pk]) / 3.6e6
        soc = None
        if "soc_hires" in S:
            sv = [v for t, v in S["soc_hires"] if ts[0] <= t <= ts[-1]]
            if sv:
                soc = (sv[0], sv[-1])
        # --- truck identity, per notes/specific-trucks/battery-degradation-tracking.md
        # Main >= 90,000 km; Parts ~44,000 km (0x625 B0:B2).
        odo = None
        truck = "?"
        if "odo_km_625" in S:
            ov = [v for _, v in S["odo_km_625"] if 1000 < v < 500000]
            if ov:
                odo = median(ov)
                truck = "MAIN" if odo >= 90000 else ("PARTS" if odo < 60000 else "?")
        # --- 12 V load via the DCDC, the channel the parts truck's free-running
        # PE pump shows up on
        lv_w = None
        if "dcdc_lv_v" in S and "dcdc_lv_i" in S:
            li = dict(S["dcdc_lv_i"])
            lv = [(t, v * li[t]) for t, v in S["dcdc_lv_v"]
                  if t in li and ts[0] <= t <= ts[-1] and charging_at(t)
                  and 8.0 < v < 18.0 and 0 <= li[t] < 300]
            if len(lv) > 50:
                lv_w = median([x[1] for x in lv])
        pilot = None
        if "pilot_duty" in S:
            pd = [v for t, v in S["pilot_duty"] if ts[0] <= t <= ts[-1] and 5 < v < 96]
            if pd:
                pilot = median(pd) * 0.6
        rows.append({"name": name, "truck": truck, "odo": odo, "lv_w": lv_w,
                     "e_ac": e_ac, "e_dc": e_dc, "e_pack": e_pack,
                     "hours": dur, "pac_med": median(pac), "pac_p95": pac[len(pac) * 95 // 100],
                     "vac": median(vac), "soc": soc, "pilot": pilot, "n": len(on)})
        print("=" * 96)
        print("%s   [%s truck, odo %s km]"
              % (name, truck, ("%.0f" % odo) if odo else "?"))
        print("  %.2f h charging (span %.2f h) | AC %.1f V | EVSE %s | P_ac median %.2f kW, p95 %.2f kW"
              % (dur, span, median(vac), ("%.0f A" % pilot) if pilot else "n/a",
                 median(pac) / 1000, pac[len(pac) * 95 // 100] / 1000))
        print("  E_ac %6.2f kWh -> E_dc(charger) %6.2f kWh   eta_charger = %.1f%%"
              % (e_ac, e_dc, 100 * e_dc / e_ac if e_ac else 0))
        if e_pack is not None:
            print("  E_dc %6.2f kWh -> E_pack(BMS)    %6.2f kWh   HV aux during charge"
                  " = %.2f kWh (%.0f W avg)"
                  % (e_dc, e_pack, e_dc - e_pack, (e_dc - e_pack) * 1000 / dur))
            print("  WALL-TO-PACK = %.1f%%%s" % (100 * e_pack / e_ac if e_ac else 0,
                  ("   | 12V load via DCDC = %.0f W (%.1f A)" % (lv_w, lv_w / 14.2))
                  if lv_w else ""))
        if soc:
            print("  SoC %.1f%% -> %.1f%%" % soc)
    (ART / "charger_sessions.json").write_text(json.dumps(rows, indent=1))
    return rows


def do_curve():
    allx = []
    for name in SESSIONS:
        try:
            S = load(name)
        except Exception:
            continue
        for x in samples(S):
            if x[1] > P_ON and x[6] >= I_DC_MIN:
                allx.append(x + (name,))
    if not allx:
        print("no data")
        return
    print("=" * 96)
    print("CHARGER EFFICIENCY vs AC INPUT POWER   (n = %d samples pooled)" % len(allx))
    print("  eta = P_dc / P_ac.  P_ac is V_RMS x I_RMS = apparent power, so at low")
    print("  power (where PF degrades) these are LOWER BOUNDS on true efficiency.")
    print("  CV-HOLD EXCLUDED (Idc < %.0f A): the 80pctcv session sits for hours at" % I_DC_MIN)
    print("  ~1.9 kVA in / 0.95 kW out with only 2.45 A DC -- that is the charger")
    print("  idling against its setpoint, not charging at low power, and pooling it")
    print("  produced a fake 49%% efficiency bin.")
    print("  %10s %7s %9s %9s %9s %9s %9s"
          % ("P_ac kW", "n", "eta q1", "eta med", "eta q3", "loss W", "V_ac"))
    edges = [0.2, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0]
    pts = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i] * 1000, edges[i + 1] * 1000
        b = [x for x in allx if lo <= x[1] < hi]
        if len(b) < 20:
            continue
        eta = sorted(x[2] / x[1] for x in b)
        pac = median([x[1] for x in b])
        loss = median([x[1] - x[2] for x in b])
        vac = median([x[3] for x in b])
        print("  %4.1f-%-5.1f %7d %9.3f %9.3f %9.3f %9.0f %9.0f"
              % (edges[i], edges[i + 1], len(b), eta[len(eta) // 4],
                 median(eta), eta[len(eta) * 3 // 4], loss, vac))
        pts.append((pac, median(eta), loss, len(b)))

    # NO LOSS MODEL FITTED. P_loss falls monotonically from 646 W to 425 W as
    # power rises, which no switching converter does -- conduction loss rises
    # with current. That shape is the signature of power factor: P_ac here is
    # V_RMS x I_RMS (apparent), and if PF degrades at light load the apparent
    # loss inflates even when real conversion loss is flat. A linear fit to
    # these medians returns a NEGATIVE proportional term and extrapolates to
    # -72% efficiency at 0.5 kW, which is meaningless. The bins above are the
    # measurement; the decomposition into PF and conversion loss is not
    # available from CAN.
    print("\n  Session provenance of each bin (low-power bins rest on few sessions):")
    for lo, hi in ((2000, 3000), (3000, 4000), (4000, 5000), (6000, 7000)):
        b = [x for x in allx if lo <= x[1] < hi]
        if not b:
            continue
        from collections import Counter
        c = Counter(x[7] for x in b)
        top = "; ".join("%s %.0f%%" % (k.replace("vtruxcharge", "").replace(".log", "")[:26],
                                       100 * v / len(b)) for k, v in c.most_common(3))
        print("    %.0f-%.0f kW: %s" % (lo / 1000, hi / 1000, top))


def do_era():
    """Efficiency vs power, split by charger unit."""
    buckets = {}
    for name in SESSIONS:
        try:
            S = load(name)
        except Exception:
            continue
        e = era(name)
        for x in samples(S):
            if x[1] > P_ON and x[6] >= I_DC_MIN:
                buckets.setdefault(e, []).append(x)
    edges = [1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    print("=" * 96)
    print("CHARGER EFFICIENCY BY UNIT   (Bel unit replaced %s)" % SWAP_DATE)
    print("  %-9s" % "P_ac kW", end="")
    order = [e for e in ("OLD", "SWAPDAY", "NEW") if e in buckets]
    for e in order:
        print(" | %-22s" % ("%s (n=%d)" % (e, len(buckets[e]))), end="")
    print()
    for i in range(len(edges) - 1):
        lo, hi = edges[i] * 1000, edges[i + 1] * 1000
        print("  %3.1f-%-5.1f" % (edges[i], edges[i + 1]), end="")
        for e in order:
            b = [x for x in buckets[e] if lo <= x[1] < hi]
            if len(b) < 20:
                print(" | %-22s" % "        -", end="")
            else:
                print(" | n=%6d eta=%.3f    " % (len(b), median([x[2] / x[1] for x in b])), end="")
        print()
    print("\n  Median conversion loss (W) in the same bins:")
    print("  %-9s" % "P_ac kW", end="")
    for e in order:
        print(" | %-22s" % e, end="")
    print()
    for i in range(len(edges) - 1):
        lo, hi = edges[i] * 1000, edges[i + 1] * 1000
        print("  %3.1f-%-5.1f" % (edges[i], edges[i + 1]), end="")
        for e in order:
            b = [x for x in buckets[e] if lo <= x[1] < hi]
            print(" | %-22s" % (("%.0f W" % median([x[1] - x[2] for x in b]))
                                if len(b) >= 20 else "-"), end="")
        print()


def do_grid(whmi_bus=531.0):
    rows = json.loads((ART / "charger_sessions.json").read_text())
    good = [r for r in rows if r["e_pack"]]
    if not good:
        print("run `sessions` first")
        return
    e_ac = sum(r["e_ac"] for r in good)
    e_dc = sum(r["e_dc"] for r in good)
    e_pk = sum(r["e_pack"] for r in good)
    print("=" * 96)
    print("FROM-GRID Wh/mile")
    print("  Pooled over %d charge sessions: E_ac %.1f kWh -> E_dc %.1f -> E_pack %.1f"
          % (len(good), e_ac, e_dc, e_pk))
    eta_chg = e_dc / e_ac
    eta_w2p = e_pk / e_ac
    print("  eta_charger (AC->DC)   = %.1f%%" % (100 * eta_chg))
    print("  wall-to-pack (AC->pack)= %.1f%%   (difference is HV aux running"
          " during the charge)" % (100 * eta_w2p))
    print()
    print("  Driving consumption at the HV bus (energy OUT of the pack): %.0f Wh/mi"
          % whmi_bus)
    for eta_pack, lbl in ((1.00, "no pack loss (upper bound)"),
                          (0.95, "95% pack round-trip (likely)"),
                          (0.92, "92% pack round-trip (conservative)")):
        print("    with %-32s -> %4.0f Wh/mi from the wall"
              % (lbl, whmi_bus / (eta_w2p * eta_pack)))


if __name__ == "__main__":
    what = _argv[1] if len(_argv) > 1 else "sessions"
    if what == "sessions":
        do_sessions()
    elif what == "curve":
        do_curve()
    elif what == "grid":
        do_grid()
    elif what == "all":
        do_sessions()
        do_curve()
        do_grid()


# ---------------------------------------------------------------------------
# Export mode: independent handle on the fixed loss
# ---------------------------------------------------------------------------
#
# In export the same power stage runs backwards: HV pack -> inverter -> 240 V
# split-phase AC. That gives a THIRD measurement point (0x18FFD6C0 leg V/I) on
# top of the two we have when charging, and lets the fixed overhead be read
# almost directly -- at near-zero AC output, whatever the pack is still
# supplying IS the standing loss.
#
# NOTE on what this does and does not separate. Writing D = Idc(charger) -
# Ibat(BMS): a real HV auxiliary load L and an additive sensor zero-offset d
# BOTH give a constant positive D in BOTH directions, so reversing current does
# not discriminate them. What export does add is (a) an independent value for
# the fixed conversion loss, and (b) a GAIN error test -- a gain error scales
# with current and flips sign with direction, a zero offset does not.

EXPORT_SESSIONS = ["vtruxexporttest.log", "exportpowerattempt.log",
                   "vtruxexportafterucsc.log", "vtruxchargeafterafterucscexport.log"]


def export_samples(S):
    """(t, Pac_out, Pdc_in, Ipack, Idc) while inverting."""
    need = ("inv_v1", "inv_i1", "dc_v", "dc_i")
    if not all(k in S for k in need):
        return []
    v1, v2 = dict(S["inv_v1"]), dict(S.get("inv_v2", []))
    i1, i2 = dict(S["inv_i1"]), dict(S.get("inv_i2", []))
    dv, di = dict(S["dc_v"]), dict(S["dc_i"])
    ib = dict(S.get("ibat", []))
    out = []
    for t, a in sorted(v1.items()):
        if t not in i1 or t not in dv or t not in di:
            continue
        b = v2.get(t, 0.0)
        c, d = i1[t], i2.get(t, 0.0)
        if not (80 <= a <= 300) or not (0 <= c <= 100):
            continue
        vd, idc = dv[t], di[t]
        if not (100 <= vd <= 500) or abs(idc) > 400:
            continue
        pac = a * c + (b * d if 80 <= b <= 300 and 0 <= d <= 100 else 0.0)
        # exporting: battery current is negative in the corrected convention
        out.append((t, pac, -(vd * -idc), ib.get(t), -idc, vd))
    return out


def do_export():
    print("=" * 96)
    print("EXPORT MODE -- inverter running backwards (HV pack -> 240 V AC)")
    allx = []
    for name in EXPORT_SESSIONS:
        try:
            S = load(name)
        except Exception:
            print("  %-42s (not extracted)" % name)
            continue
        sm = export_samples(S)
        act = [x for x in sm if x[1] > 100]
        if len(act) < 100:
            print("  %-42s no export activity (%d samples)" % (name, len(sm)))
            continue
        pac = sorted(x[1] for x in act)
        print("  %-42s n=%6d  P_ac_out median %.2f kW  p95 %.2f kW"
              % (name, len(act), median(pac) / 1000, pac[len(pac) * 95 // 100] / 1000))
        allx.extend(act)
    if not allx:
        return
    print("\n  Inverter efficiency vs AC OUTPUT power")
    print("  %10s %8s %10s %10s %10s" % ("P_ac kW", "n", "eta med", "loss W", "P_dc kW"))
    edges = [0.1, 0.3, 0.6, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 9.0]
    pts = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i] * 1000, edges[i + 1] * 1000
        b = [x for x in allx if lo <= x[1] < hi]
        if len(b) < 20:
            continue
        eta = median([x[1] / x[2] for x in b if x[2] > 50])
        loss = median([x[2] - x[1] for x in b])
        pdc = median([x[2] for x in b])
        print("  %4.1f-%-5.1f %8d %10.3f %10.0f %10.2f"
              % (edges[i], edges[i + 1], len(b), eta, loss, pdc / 1000))
        pts.append((median([x[1] for x in b]), loss))
    if len(pts) >= 3:
        A = [[1.0, p[0]] for p in pts]
        ab = lstsq(A, [p[1] for p in pts])
        if ab:
            print("\n  Loss vs OUTPUT power:  P_loss = %.0f W + %.3f x P_ac_out" % (ab[0], ab[1]))
            print("  -> zero-output intercept = %.0f W standing draw" % ab[0])
    # gain-vs-offset test on the two current sensors, now with reversed current
    d = [x[4] - (-x[3]) for x in allx if x[3] is not None and x[1] > 500]
    if len(d) > 200:
        ds = sorted(d)
        print("\n  Current-sensor difference while EXPORTING (Idc - |Ipack|):")
        print("    median %+.2f A  (q1 %+.2f, q3 %+.2f, n=%d)"
              % (median(ds), ds[len(ds) // 4], ds[len(ds) * 3 // 4], len(ds)))
        print("    Charging gave +1.13 A. Same sign and similar magnitude with current")
        print("    REVERSED rules out a gain error (which would flip sign); consistent")
        print("    with either a fixed HV load or an additive sensor zero-offset.")
