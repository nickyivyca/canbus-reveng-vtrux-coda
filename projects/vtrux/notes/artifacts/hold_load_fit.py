"""hold_load_fit.py -- rough fit of the truck's HV-side load during charging,
for the interposer's P3a question (reviewer, 2026-10-09).

Question (user): the full-charge hold shows ~2 A of HV load beyond the 12 V
side on both trucks. Is that a fixed load that grows at low charger current?
And what DC-DC efficiency does the data imply?

Source: InfluxDB (canbus-data), powertrain bus only, forward-filled to a 1 s
grid (values exact under the on-change + 1 s heartbeat policy), averaged over
60 s windows.

  HV load  = Vdc * (Idc - ibat)   charger DC out minus what reaches the pack
  P12      = DCDC_LV_Curr * DCDC_LV_Volt
  charger loss = Vac * Iac - Vdc * Idc   (apparent AC power: an upper bound
                 on loss at low power, see charger_efficiency.py)

Idc is BELINV_hvBatteryCurrent NEGATED (the DBC sign is backwards, see
charger_efficiency.py). bcm_ibat is + when charging.

Phases:
  1  pull and window every session (cached to hold_load_fit_windows.json)
  2  fit HV load = a + b * P12 on main-truck hold windows; DC-DC eff = 1/b
  3  base load (HV load - b * P12) against charger current, both trucks
  4  charger AC->DC loss against DC power
  6  time series across the Low Power command; "total" = Pac (VA) - Vdc*ibat
     - 1.6*P12, everything that reaches neither the pack nor the 12 V side.
     It does not depend on the charger's own DC current reading.
  7  total against Pac, hold windows vs every other charging window
  8  the garage 14-50 CT (homeassistant DB, real W) across the Low Power
     command: real AC power against the charger's VA and its reported DC
     (Infrastructure/vehicle-cost-per-mile.md 6.2 measured the hold at 569 W)

Every query against `signals` carries a time bound (tools/tools.md, the
2026-09-27 outage); phases 1 and 5 were first run without one, and are now
bounded by the session's upload_manifest window.
  5  DC-DC efficiency WITHIN the main truck: bulk-charge windows (Idc >= 12 A)
     of the main-truck sessions whose 12 V load varies 3-21 A
     (charger-efficiency-and-grid-consumption.md), HV load = a + b * P12
"""
import sys
sys.path.insert(0, ".")
import json
import os
import statistics as st
import urllib.parse
import urllib.request
import base64

OUT = "projects/vtrux/notes/artifacts/hold_load_fit_windows.json"
PHASES = {8}

MAIN = ["another_M0", "charge_M0", "full-charge-then-fail",
        "vtrux_20260503_192242", "vtrux_20260726_191901",
        "vtrux_20260816_111915", "vtrux_20260912_192748", "vtrux_charge_M1",
        "vtruxchargeafterexportchargetest-80pctcv"]
PARTS = ["vtrux_partstruck_charge"]
FIELDS = ["BELINV_hvBatteryCurrent", "BELINV_hvBatteryVoltage",
          "BELINV_chargerInputVoltage", "BELINV_chargerInputCurrent",
          "bcm_ibat", "bcm_soc", "bcm_chg_max", "DCDC_LV_Curr", "DCDC_LV_Volt"]
WIN_S = 60


def influx(q, db="canbus-data"):
    url = ("http://localhost:8086/query?" + urllib.parse.urlencode(
        {"db": db, "q": q, "epoch": "ms", "chunked": "true",
         "chunk_size": "20000"}))
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Basic " +
                   base64.b64encode(b"claude:claude").decode())
    rows, cols = [], None
    with urllib.request.urlopen(req, timeout=600) as r:
        for line in r.read().decode().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            for res in d.get("results", []):
                for se in res.get("series", []):
                    cols = se["columns"]
                    rows.extend(se["values"])
    return cols, rows


def stored_window_s(session):
    """(t0_s, t1_s) from upload_manifest, as tools/influx_upload.py's
    stored_window_ns does. Every read of `signals` is bounded by it: the
    2026-09-27 outage rule (tools/tools.md), reads included."""
    cols, rows = influx("SELECT uploaded_at, file, t_start_ns, t_end_ns FROM "
                        "upload_manifest WHERE \"vehicle\"='vtrux' AND "
                        "\"session\"='%s'" % session)
    newest = {}
    for v in rows:
        r = dict(zip(cols, v))
        f, ua = r.get("file"), r.get("uploaded_at") or 0
        if f not in newest or ua > newest[f][0]:
            newest[f] = (ua, r)
    t0 = [r["t_start_ns"] for _u, r in newest.values() if r.get("t_start_ns")]
    t1 = [r["t_end_ns"] for _u, r in newest.values() if r.get("t_end_ns")]
    if not t0 or not t1:
        raise RuntimeError("no manifest window for %s" % session)
    return min(t0) // 10**9, max(t1) // 10**9 + 1


def windows(session):
    sel = ", ".join('"%s"' % f for f in FIELDS)
    w0, w1 = stored_window_s(session)
    cols, rows = influx("SELECT %s FROM signals WHERE vehicle='vtrux' AND "
                        "session='%s' AND bus='powertrain' AND time >= %ds AND "
                        "time < %ds" % (sel, session, w0, w1))
    if not rows:
        return []
    rows.sort(key=lambda r: r[0])
    idx = {c: i for i, c in enumerate(cols)}
    cur = dict.fromkeys(FIELDS)
    t0 = rows[0][0] // 1000
    grid = {}
    k = 0
    tend = rows[-1][0] // 1000
    for s in range(t0, tend + 1):
        while k < len(rows) and rows[k][0] // 1000 <= s:
            for f in FIELDS:
                v = rows[k][idx[f]]
                if v is not None:
                    cur[f] = v
            k += 1
        grid[s] = dict(cur)
    out = []
    for w0 in range(t0, tend + 1 - WIN_S, WIN_S):
        acc = {f: [] for f in FIELDS}
        for s in range(w0, w0 + WIN_S):
            g = grid[s]
            for f in FIELDS:
                if g[f] is not None:
                    acc[f].append(g[f])
        if any(len(acc[f]) < WIN_S for f in FIELDS):
            continue
        vac = st.mean(acc["BELINV_chargerInputVoltage"])
        iac = st.mean(acc["BELINV_chargerInputCurrent"])
        if not (80 <= max(acc["BELINV_chargerInputVoltage"]) <= 300
                and max(acc["BELINV_chargerInputCurrent"]) <= 60):
            continue
        vdc = st.mean(acc["BELINV_hvBatteryVoltage"])
        idc = -st.mean(acc["BELINV_hvBatteryCurrent"])
        if not (100 <= vdc <= 500) or idc < 0.3:
            continue
        ibat = st.mean(acc["bcm_ibat"])
        p12 = st.mean(a * b for a, b in zip(acc["DCDC_LV_Curr"],
                                            acc["DCDC_LV_Volt"]))
        out.append({"t": w0, "vdc": vdc, "idc": idc, "ibat": ibat,
                    "vac": vac, "iac": iac, "p12": p12,
                    "i12": st.mean(acc["DCDC_LV_Curr"]),
                    "soc": st.mean(acc["bcm_soc"]),
                    "chgmax": max(acc["bcm_chg_max"]),
                    "idc_sd": st.pstdev([-x for x in acc["BELINV_hvBatteryCurrent"]])})
    return out


def is_hold(w):
    return w["soc"] >= 99.5 and w["chgmax"] <= 0.01 and w["idc"] < 5


def linfit(xs, ys):
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    res = [y - (a + b * x) for x, y in zip(xs, ys)]
    rmse = (sum(r * r for r in res) / len(res)) ** 0.5
    ss = sum((y - my) ** 2 for y in ys)
    r2 = 1 - sum(r * r for r in res) / ss if ss else float("nan")
    return a, b, rmse, r2


def hvload(w):
    return w["vdc"] * (w["idc"] - w["ibat"])


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


if 1 in PHASES:
    data = {}
    for s in MAIN + PARTS:
        ws = windows(s)
        data[s] = ws
        print("phase1 %-42s windows %5d  hold %5d" %
              (s, len(ws), sum(1 for w in ws if is_hold(w))))
    with open(OUT, "w") as f:
        json.dump(data, f)
else:
    data = json.load(open(OUT))

b_fit = None
if 2 in PHASES:
    print("\nphase2: HV load = a + b * P12, full-charge hold windows")
    for label, sess in (("main", MAIN), ("parts", PARTS)):
        hw = [w for s in sess for w in data[s] if is_hold(w)]
        if len(hw) < 3:
            print("  %s: %d hold windows, no fit" % (label, len(hw)))
            continue
        a, b, rmse, r2 = linfit([w["p12"] for w in hw], [hvload(w) for w in hw])
        print("  %-5s n=%4d  P12 %4.0f..%4.0f W  a=%5.0f W  b=%.3f (DC-DC eff "
              "%.2f)  rmse %3.0f W  r2 %.2f" %
              (label, len(hw), min(w["p12"] for w in hw),
               max(w["p12"] for w in hw), a, b, 1 / b if b else float("nan"),
               rmse, r2))
        if label == "main":
            b_fit, a_fit = b, a
    print("  per session (hold windows): median P12, HV load, Idc, ibat, residual vs main fit")
    for s in MAIN + PARTS:
        hw = [w for w in data[s] if is_hold(w)]
        if not hw:
            continue
        med = lambda k: st.median(w[k] for w in hw)
        hl = st.median(hvload(w) for w in hw)
        p12 = med("p12")
        print("   %-42s n=%4d P12 %4.0f W (%5.2f A)  HV load %5.0f W  Idc %.2f  "
              "ibat %+.2f  resid %+5.0f W" %
              (s, len(hw), p12, med("i12"), hl, med("idc"), med("ibat"),
               hl - (a_fit + b_fit * p12)))
    # 12 V varies little inside the main holds; fit on ALL main windows too
    aw = [w for s in MAIN for w in data[s]]
    a2, b2, rmse2, r22 = linfit([w["p12"] for w in aw], [hvload(w) for w in aw])
    print("  main, ALL charging windows n=%d: a=%.0f W b=%.3f (eff %.2f) rmse %.0f r2 %.2f"
          % (len(aw), a2, b2, 1 / b2, rmse2, r22))

if 3 in PHASES and b_fit:
    print("\nphase3: base = HV load - b*P12 (b=%.3f from main holds) by charger Idc" % b_fit)
    bins = [(0.3, 1.5), (1.5, 2.5), (2.5, 3.5), (3.5, 5), (5, 8), (8, 12), (12, 25)]
    for label, sess in (("main", MAIN), ("parts", PARTS)):
        print("  %s" % label)
        for lo, hi in bins:
            ws = [w for s in sess for w in data[s] if lo <= w["idc"] < hi]
            if not ws:
                continue
            base = [hvload(w) - b_fit * w["p12"] for w in ws]
            print("    Idc %4.1f-%4.1f A  n=%5d  base q1/med/q3 %5.0f %5.0f %5.0f W"
                  "   P12 med %4.0f W" %
                  (lo, hi, len(ws), q(base, .25), st.median(base), q(base, .75),
                   st.median(w["p12"] for w in ws)))

if 4 in PHASES:
    print("\nphase4: charger AC->DC loss (apparent AC power) by DC power")
    bins = [(0, 0.6), (0.6, 1.0), (1.0, 1.5), (1.5, 3), (3, 5), (5, 8)]
    for label, sess in (("main", MAIN), ("parts", PARTS)):
        print("  %s" % label)
        for lo, hi in bins:
            ws = [w for s in sess for w in data[s]
                  if lo <= w["vdc"] * w["idc"] / 1000 < hi]
            if not ws:
                continue
            loss = [w["vac"] * w["iac"] - w["vdc"] * w["idc"] for w in ws]
            eta = [w["vdc"] * w["idc"] / (w["vac"] * w["iac"]) for w in ws
                   if w["iac"] > 0]
            print("    P_dc %3.1f-%3.1f kW n=%5d  loss med %5.0f W (q1 %5.0f q3 %5.0f)"
                  "  eta med %.2f" %
                  (lo, hi, len(ws), st.median(loss), q(loss, .25), q(loss, .75),
                   st.median(eta) if eta else float("nan")))


EXTRA = ["vtrux_20260719_190019", "vtrux_20260513_180408",
         "vtrux_20260627_164210", "vtrux_20260714_161319",
         "vtruxchargeblueevse", "vtrux_20260714_112312",
         "vtrux_20260714_102812", "vtruxchargemegearevse"]
OUT5 = "projects/vtrux/notes/artifacts/hold_load_fit_bulk_windows.json"
if 5 in PHASES:
    if os.path.exists(OUT5):
        bulk = json.load(open(OUT5))
    else:
        bulk = {s: windows(s) for s in EXTRA}
        with open(OUT5, "w") as f:
            json.dump(bulk, f)
    print("\nphase5: main truck, bulk windows (Idc >= 12 A), HV load vs P12")
    meds = []
    for s in EXTRA:
        ws = [w for w in bulk[s] if w["idc"] >= 12]
        if not ws:
            print("   %-28s no bulk windows" % s)
            continue
        m = (st.median(w["p12"] for w in ws), st.median(hvload(w) for w in ws))
        meds.append((s, m[0], m[1]))
        print("   %-28s n=%4d  P12 med %4.0f W (%5.2f A)  HV load med %5.0f W  "
              "Idc %5.2f  ibat %5.2f" % (s, len(ws), m[0],
              st.median(w["i12"] for w in ws), m[1],
              st.median(w["idc"] for w in ws), st.median(w["ibat"] for w in ws)))
    for label, keep in (("all sessions", lambda s: True),
                        ("without 20260714_102812 (2090 W outlier)",
                         lambda s: "102812" not in s)):
        ws = [w for s in EXTRA if keep(s) for w in bulk[s] if w["idc"] >= 12]
        a, b, rmse, r2 = linfit([w["p12"] for w in ws], [hvload(w) for w in ws])
        print("  windows, %s: n=%d a=%.0f W b=%.2f (eff %.2f) rmse %.0f r2 %.2f"
              % (label, len(ws), a, b, 1 / b, rmse, r2))
        mm = [x for x in meds if keep(x[0])]
        a, b, rmse, r2 = linfit([x[1] for x in mm], [x[2] for x in mm])
        print("  session medians, %s: n=%d a=%.0f W b=%.2f (eff %.2f) rmse %.0f r2 %.2f"
              % (label, len(mm), a, b, 1 / b, rmse, r2))


# phase 6: the HV load across the Low Power command. Entry times (UTC) come
# from vcu_hold_character.txt (raw logs on madhouse, page 00 mode 3 flow 1).
# Alignment check: the charger's DC current must fall within seconds of the
# entry (spec 4: in Low Power mode it caps at ~6 A at once).
if 6 in PHASES:
    import re
    import datetime as dt
    txt = open("projects/vtrux/notes/artifacts/interposer-review-2026-09-22/"
               "vcu_hold_character.txt").read()
    entries = re.findall(r"^== (\S+) .*?\n  LOW POWER stretch from (\S+ \S+) UTC",
                         txt, re.M)
    print("\nphase6: around the Low Power command (t=0), 30 s medians")
    for name, ts in entries:
        t0 = int(dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=dt.timezone.utc).timestamp())
        lo, hi = t0 - 900, t0 + 2400
        sel = ", ".join('"%s"' % f for f in FIELDS)
        cols, rows = influx(
            "SELECT %s FROM signals WHERE vehicle='vtrux' AND session='%s' AND "
            "bus='powertrain' AND time >= %ds AND time < %ds"
            % (sel, name, lo - 120, hi))
        rows.sort(key=lambda r: r[0])
        idx = {c: i for i, c in enumerate(cols)} if cols else {}
        cur = dict.fromkeys(FIELDS)
        k = 0
        per = {}
        for s in range(lo - 120, hi):
            while k < len(rows) and rows[k][0] // 1000 <= s:
                for f in FIELDS:
                    v = rows[k][idx[f]]
                    if v is not None:
                        cur[f] = v
                k += 1
            if s < lo or any(cur[f] is None for f in FIELDS):
                continue
            b = (s - t0) // 30 * 30
            idc = -cur["BELINV_hvBatteryCurrent"]
            vdc = cur["BELINV_hvBatteryVoltage"]
            per.setdefault(b, []).append((
                idc, cur["bcm_ibat"], vdc * (idc - cur["bcm_ibat"]),
                cur["DCDC_LV_Curr"] * cur["DCDC_LV_Volt"],
                cur["BELINV_chargerInputVoltage"] * cur["BELINV_chargerInputCurrent"]
                - vdc * idc, cur["bcm_soc"], cur["bcm_chg_max"],
                cur["BELINV_chargerInputVoltage"] * cur["BELINV_chargerInputCurrent"],
                cur["BELINV_chargerInputVoltage"] * cur["BELINV_chargerInputCurrent"]
                - vdc * cur["bcm_ibat"]
                - 1.6 * cur["DCDC_LV_Curr"] * cur["DCDC_LV_Volt"]))
        print("\n  %s  entry %s UTC" % (name, ts))
        print("     t s |   Idc |  ibat | HV load W |  P12 W | base W (HVload-1.6*P12) | AC loss W |  SoC | chgmax |  Pac VA | total W")
        show = [-900, -600, -300, -120, -60, -30, 0, 30, 60, 120, 180, 300, 600,
                900, 1200, 1800, 2370]
        for b in show:
            v = per.get(b)
            if not v:
                print("  %6d | no data" % b)
                continue
            m = [st.median(x[i] for x in v) for i in range(9)]
            print("  %6d | %5.2f | %5.2f | %9.0f | %6.0f | %23.0f | %9.0f | %4.1f | %6.1f | %7.0f | %7.0f"
                  % (b, m[0], m[1], m[2], m[3], m[2] - 1.6 * m[3], m[4], m[5], m[6], m[7], m[8]))


# phase 7: is "total" a function of AC input alone, whatever the mode?
# hold = SoC >= 99.5, chg_max 0, Idc < 5 (Low Power); other = everything else
if 7 in PHASES:
    data = json.load(open(OUT))
    bulk = json.load(open(OUT5))
    allw = [(s, w) for d in (data, bulk) for s, ws in d.items() for w in ws
            if "161319" not in s]
    tot = lambda w: w["vac"] * w["iac"] - w["vdc"] * w["ibat"] - 1.6 * w["p12"]
    print("\nphase7: total (W) by AC input (VA); main truck and parts truck apart")
    for label, keep in (("main", lambda s: "partstruck" not in s),
                        ("parts", lambda s: "partstruck" in s)):
        print("  %s" % label)
        print("    Pac kVA  | hold n, total med (q1-q3) | other n, total med (q1-q3) | 80pct LP n, total")
        for lo in (1.5, 1.75, 2.0, 2.25, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0):
            hi = {1.5: 1.75, 1.75: 2.0, 2.0: 2.25, 2.25: 2.5, 2.5: 3.0, 3.0: 3.5,
                  3.5: 4.0, 4.0: 5.0, 5.0: 6.0, 6.0: 8.0}[lo]
            sel = [(s, w) for s, w in allw if keep(s)
                   and lo <= w["vac"] * w["iac"] / 1000 < hi]
            h = [tot(w) for s, w in sel if is_hold(w)]
            lp80 = [tot(w) for s, w in sel if "80pct" in s and w["idc"] < 7]
            o = [tot(w) for s, w in sel if not is_hold(w) and not ("80pct" in s and w["idc"] < 7)]
            f = lambda xs: ("%5d %5.0f (%4.0f-%4.0f)" % (len(xs), st.median(xs), q(xs, .25), q(xs, .75))) if xs else "%5d %17s" % (0, "")
            print("    %4.2f-%4.2f | %s | %s | %s" % (lo, hi, f(h), f(o), f(lp80)))


# phase 8: real AC power from the garage 14-50 CT around each Low Power entry.
# Emporia minute averages, written on change: forward-filled to a minute grid.
# CT coverage starts 2025-11-30, so full-charge-then-fail (2025-08) has none.
CT = "garage_14_50_power_minute_average"
if 8 in PHASES:
    import re
    import datetime as dt
    txt = open("projects/vtrux/notes/artifacts/interposer-review-2026-09-22/"
               "vcu_hold_character.txt").read()
    entries = re.findall(r"^== (\S+) .*?\n  LOW POWER stretch from (\S+ \S+) UTC",
                         txt, re.M)
    print("\nphase8: garage 14-50 CT (real W) against CAN, minute grid, t=0 at the Low Power command")
    summary = []
    for name, ts in entries:
        t0 = int(dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=dt.timezone.utc).timestamp())
        lo, hi = t0 - 900, t0 + 2400
        _c, ctrows = influx("SELECT value FROM \"W\" WHERE entity_id='%s' AND "
                            "time >= %ds AND time < %ds" % (CT, lo - 3600, hi),
                            db="homeassistant")
        ctrows.sort(key=lambda r: r[0])
        sel = ", ".join('"%s"' % f for f in FIELDS)
        cols, rows = influx(
            "SELECT %s FROM signals WHERE vehicle='vtrux' AND session='%s' AND "
            "bus='powertrain' AND time >= %ds AND time < %ds"
            % (sel, name, lo - 120, hi))
        rows.sort(key=lambda r: r[0])
        if not ctrows or not rows:
            print("\n  %s  entry %s UTC: CT rows %d, CAN rows %d -- skipped"
                  % (name, ts, len(ctrows), len(rows)))
            continue
        idx = {c: i for i, c in enumerate(cols)}
        cur = dict.fromkeys(FIELDS)
        k = kc = 0
        ctv = None
        per = {}
        for s_ in range(lo - 120, hi):
            while k < len(rows) and rows[k][0] // 1000 <= s_:
                for f in FIELDS:
                    v = rows[k][idx[f]]
                    if v is not None:
                        cur[f] = v
                k += 1
            while kc < len(ctrows) and ctrows[kc][0] // 1000 <= s_:
                ctv = ctrows[kc][1]
                kc += 1
            if s_ < lo or ctv is None or any(cur[f] is None for f in FIELDS):
                continue
            m = (s_ - t0) // 60
            idc = -cur["BELINV_hvBatteryCurrent"]
            vdc = cur["BELINV_hvBatteryVoltage"]
            per.setdefault(m, []).append((
                ctv,
                cur["BELINV_chargerInputVoltage"] * cur["BELINV_chargerInputCurrent"],
                vdc * idc, vdc * cur["bcm_ibat"],
                cur["DCDC_LV_Curr"] * cur["DCDC_LV_Volt"], idc, cur["bcm_ibat"]))
        print("\n  %s  entry %s UTC" % (name, ts))
        print("    min |  CT W |  CAN VA | W/VA | rep DC W | pack W | P12 W | rep DC - CT | Idc  | ibat")
        for m in (-15, -10, -5, -2, -1, 0, 1, 2, 3, 5, 10, 15, 20, 30, 39):
            v = per.get(m)
            if not v:
                continue
            md = [st.median(x[i] for x in v) for i in range(7)]
            print("   %4d | %5.0f | %7.0f | %4.2f | %8.0f | %6.0f | %5.0f | %11.0f | %4.2f | %5.2f"
                  % (m, md[0], md[1], md[0] / md[1] if md[1] else float("nan"),
                     md[2], md[3], md[4], md[2] - md[0], md[5], md[6]))
        hold = [x for m, v in per.items() if m >= 20 for x in v]
        if hold:
            summary.append((name, [st.median(x[i] for x in hold) for i in range(7)]))
    print("\n  hold (t >= 20 min) per session: CT real W, CAN VA, reported DC W, pack W, P12 W;"
          " 'unaccounted' = CT - pack - P12 (charger + DC-DC + HV aux, real)")
    for name, md in summary:
        print("   %-42s CT %4.0f W  VA %5.0f  W/VA %.2f  repDC %4.0f W  pack %+4.0f W  "
              "P12 %3.0f W  unaccounted %4.0f W  repDC/CT %.2f"
              % (name, md[0], md[1], md[0] / md[1], md[2], md[3], md[4],
                 md[0] - md[3] - md[4], md[2] / md[0] if md[0] else float("nan")))
