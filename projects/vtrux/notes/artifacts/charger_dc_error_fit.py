"""charger_dc_error_fit.py -- follow-up to hold_load_fit.py phase 8 (2026-10-10).

hold_load_fit phase 8 found that at the Low Power hold the Bel charger's
reported DC output (Vdc * BELINV_hvBatteryCurrent) exceeds the real AC power
measured by the garage 14-50 Emporia CT by 300-430 W. That rests on the CT
being right at ~600 W and PF ~0.3, where vehicle-cost-per-mile.md 6.1 only
validated it at ~6.8 kW (against the Coda). This script:

  1  cross-checks the CT against an INDEPENDENT meter: the Enphase consumption
     CTs on the main panel (own CTs, own voltage reference). Every step where
     the garage CT falls from a stable plateau to ~0 (a charge ending) is
     matched to the Enphase consumption step in the same minutes. Hold ends
     (plateau 400-1300 W) are the test; full-power ends (> 5 kW) the control.
  2  the shape of the DC reading error across the taper. Assumes the HV aux
     load other than the DC-DC is constant within a session and takes it from
     that session's own bulk windows (Idc >= 10 A), where the export-mode check
     (charger-efficiency-and-grid-consumption.md) found the two sensors agree:
         true Idc = ibat + (aux_ref + P12 / ETA_DCDC) / Vdc
         error    = reported Idc - true Idc
     then fits reported vs true as offset, gain + offset, and quadrature
     (rep^2 = true^2 + c^2).
  3  with the CT added, per stable window: real charger loss = CT - true DC,
     and wall-to-pack = pack W / CT, binned by CT real power.

Inputs: hold_load_fit_windows.json and hold_load_fit_bulk_windows.json (60 s
windows from InfluxDB canbus-data, built by hold_load_fit.py phases 1 and 5).
Every homeassistant query is time-bounded (tools/tools.md, 2026-09-27 rule).
"""
import sys
sys.path.insert(0, ".")
import base64
import datetime as dt
import json
import statistics as st
import urllib.parse
import urllib.request

PHASES = {1, 2, 3}
ART = "projects/vtrux/notes/artifacts/"
CT = "garage_14_50_power_minute_average"
EN = "enphase_current_power_consumption"
ETA_DCDC = 0.90
CT_START = dt.datetime(2025, 11, 30, tzinfo=dt.timezone.utc)


def influx(q, db):
    url = "http://localhost:8086/query?" + urllib.parse.urlencode(
        {"db": db, "q": q, "epoch": "s"})
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Basic " +
                   base64.b64encode(b"claude:claude").decode())
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.load(r)
    rows = []
    for res in d.get("results", []):
        for se in res.get("series", []):
            rows.extend(se["values"])
    rows.sort()
    return rows


def ha_series(entity, t0, t1):
    return influx("SELECT value FROM \"W\" WHERE entity_id='%s' AND time >= %ds "
                  "AND time < %ds" % (entity, t0, t1), "homeassistant")


def ffill(rows, t):
    lo, hi = 0, len(rows)
    while lo < hi:
        m = (lo + hi) // 2
        if rows[m][0] <= t:
            lo = m + 1
        else:
            hi = m
    return rows[lo - 1][1] if lo else None


if 1 in PHASES:
    print("phase1: garage CT steps to ~0 against the Enphase consumption step")
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    t, ctrows = int(CT_START.timestamp()), []
    while t < now:
        ctrows += ha_series(CT, t, min(t + 30 * 86400, now))
        t += 30 * 86400
    print("  CT rows %d" % len(ctrows))
    events = []
    for i in range(1, len(ctrows)):
        tt, v = ctrows[i]
        if v > 60:
            continue
        before = []
        j = i - 1
        while j >= 0 and ctrows[j][0] >= tt - 900:
            if ctrows[j][0] < tt - 60:
                before.append(ctrows[j][1])
            j -= 1
        if len(before) < 4 or ctrows[i - 1][1] < 300:
            continue
        lvl = st.median(before)
        if max(before) - min(before) > 0.15 * lvl:
            continue
        if events and tt - events[-1][0] < 1800:
            continue
        events.append((tt, lvl, ctrows[i][1]))
    print("  stable-plateau ends: %d" % len(events))
    res = []
    for tt, lvl, after in events:
        en = ha_series(EN, tt - 1200, tt + 1200)
        if len(en) < 20:
            continue
        pre = [v for t_, v in en if tt - 660 <= t_ < tt - 180]
        post = [v for t_, v in en if tt + 60 <= t_ < tt + 540]
        if len(pre) < 4 or len(post) < 4:
            continue
        step = st.median(pre) - st.median(post)
        ctstep = lvl - after
        res.append((tt, lvl, ctstep, step, st.pstdev(pre)))
        print("   %s  CT plateau %5.0f W  CT step %5.0f  Enphase step %5.0f  "
              "ratio %.2f  (Enphase pre-sd %3.0f)"
              % (dt.datetime.fromtimestamp(tt, dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                 lvl, ctstep, step, step / ctstep, st.pstdev(pre)))
    for label, lo, hi in (("hold ends (400-1300 W)", 400, 1300),
                          ("mid (1300-5000 W)", 1300, 5000),
                          ("full-power ends (>5000 W)", 5000, 99999)):
        for quiet in (False, True):
            r = [x for x in res if lo <= x[1] < hi and (not quiet or x[4] < 100)]
            if quiet:
                label = label.split(" (")[0] + ", quiet house (Enphase pre-sd < 100 W)"
            if not r:
                continue
            print("  %-50s n=%2d  Enphase/CT step ratio median %.2f (q1 %.2f q3 %.2f)  "
                  "sum-ratio %.3f" % (label, len(r), st.median(x[3] / x[2] for x in r),
                  sorted(x[3] / x[2] for x in r)[len(r) // 4],
                  sorted(x[3] / x[2] for x in r)[3 * len(r) // 4],
                  sum(x[3] for x in r) / sum(x[2] for x in r)))


data = json.load(open(ART + "hold_load_fit_windows.json"))
bulk = json.load(open(ART + "hold_load_fit_bulk_windows.json"))
HOLD_SESS = list(data)


def aux_ref(ws):
    b = [w["vdc"] * (w["idc"] - w["ibat"]) - w["p12"] / ETA_DCDC
         for w in ws if w["idc"] >= 10]
    return st.median(b) if len(b) >= 5 else None


if 2 in PHASES:
    print("\nphase2: reported vs implied-true Idc, aux from each session's own bulk")
    pts = []
    for s in HOLD_SESS:
        ws = data[s]
        a = aux_ref(ws)
        if a is None:
            print("   %-42s no bulk reference" % s)
            continue
        print("   %-42s aux_ref (non-DC-DC HV load at Idc>=10 A) %4.0f W" % (s, a))
        for w in ws:
            true = w["ibat"] + (a + w["p12"] / ETA_DCDC) / w["vdc"]
            pts.append((s, w["idc"], true, w))
    bins = [(2.0, 2.5), (2.5, 3.0), (3.0, 3.5), (3.5, 4.0), (4.0, 5.0), (5.0, 6.0),
            (6.0, 8.0), (8.0, 10.0), (10.0, 13.0), (13.0, 16.0)]
    print("   reported Idc bin |    n | true med | error med (q1..q3) A | error W med")
    rows = []
    for lo, hi in bins:
        b = [(r, t, w) for s, r, t, w in pts if lo <= r < hi and "partstruck" not in s]
        if not b:
            continue
        e = sorted(r - t for r, t, w in b)
        rows.append((st.median(r for r, t, w in b), st.median(t for r, t, w in b)))
        print("   %4.1f-%4.1f        | %4d | %8.2f | %5.2f (%5.2f..%5.2f)    | %5.0f"
              % (lo, hi, len(b), st.median(t for r, t, w in b), st.median(e),
                 e[len(e) // 4], e[3 * len(e) // 4],
                 st.median((r - t) * w["vdc"] for r, t, w in b)))
    pp = [(s, r, t) for s, r, t, w in pts if "partstruck" in s]
    if pp:
        print("   parts truck:")
        for lo, hi in bins:
            b = [(r, t) for s, r, t in pp if lo <= r < hi]
            if b:
                print("   %4.1f-%4.1f        | %4d | %8.2f | %5.2f"
                      % (lo, hi, len(b), st.median(t for r, t in b),
                         st.median(r - t for r, t in b)))
    main = [(r, t) for s, r, t, w in pts if "partstruck" not in s and t > 0.2]
    best = None
    for c in [x / 100 for x in range(0, 400, 2)]:
        e1 = sum((r - (t + c)) ** 2 for r, t in main)
        e3 = sum((r - (t * t + c * c) ** 0.5) ** 2 for r, t in main)
        if best is None:
            best = {"off": (e1, c), "quad": (e3, c)}
        if e1 < best["off"][0]:
            best["off"] = (e1, c)
        if e3 < best["quad"][0]:
            best["quad"] = (e3, c)
    n = len(main)
    mt, mr = st.mean(t for r, t in main), st.mean(r for r, t in main)
    g = sum((t - mt) * (r - mr) for r, t in main) / sum((t - mt) ** 2 for r, t in main)
    c0 = mr - g * mt
    e2 = sum((r - (g * t + c0)) ** 2 for r, t in main)
    print("   fits over %d main-truck windows (reported = f(true)):" % n)
    print("     offset      rep = true + %.2f          rmse %.3f A"
          % (best["off"][1], (best["off"][0] / n) ** 0.5))
    print("     gain+offset rep = %.3f*true + %.2f     rmse %.3f A" % (g, c0, (e2 / n) ** 0.5))
    print("     quadrature  rep = sqrt(true^2 + %.2f^2) rmse %.3f A"
          % (best["quad"][1], (best["quad"][0] / n) ** 0.5))
    print("   residual by bin, quadrature fit:")
    c = best["quad"][1]
    for lo, hi in bins:
        b = [(r, t) for r, t in main if lo <= r < hi]
        if b:
            print("     %4.1f-%4.1f  n=%4d  resid med %+5.2f A  offset-fit resid %+5.2f A"
                  % (lo, hi, len(b), st.median(r - (t * t + c * c) ** 0.5 for r, t in b),
                     st.median(r - (t + best["off"][1]) for r, t in b)))


if 3 in PHASES:
    print("\nphase3: CT-referenced, stable windows (CAN VA within 3 %% over +/-3 min)")
    allw = []
    for src in (data, bulk):
        for s, ws in src.items():
            if not ws or ws[0]["t"] < CT_START.timestamp():
                continue
            a = aux_ref(ws)
            ctr = ha_series(CT, ws[0]["t"] - 3600, ws[-1]["t"] + 600)
            if not ctr:
                print("   %-42s no CT rows" % s)
                continue
            byt = {w["t"]: w for w in ws}
            for w in ws:
                va = w["vac"] * w["iac"]
                nb = [byt.get(w["t"] + k * 60) for k in (-3, -2, -1, 1, 2, 3)]
                if any(x is None for x in nb) or any(
                        abs(x["vac"] * x["iac"] - va) > 0.03 * va for x in nb):
                    continue
                ctv = ffill(ctr, w["t"] + 90)
                if not ctv or ctv < 100:
                    continue
                allw.append((s, w, ctv, a))
    print("   stable windows with CT: %d over %d sessions"
          % (len(allw), len({x[0] for x in allw})))
    bins = [(300, 800), (800, 1300), (1300, 2000), (2000, 3000), (3000, 4000),
            (4000, 5000), (5000, 6000), (6000, 7500)]
    for label, keep in (("main", lambda s: "partstruck" not in s and "161319" not in s),
                        ("parts", lambda s: "partstruck" in s)):
        print("  %s  (aux_ref sessions only for the loss columns)" % label)
        print("    CT W bin   |    n | CT/VA | wall-to-pack | rep DC - CT W | "
              "charger real loss W (CT - true DC) | real eff | VA-based eff")
        for lo, hi in bins:
            b = [x for x in allw if keep(x[0]) and lo <= x[2] < hi]
            if not b:
                continue
            w2p = sum(x[1]["vdc"] * x[1]["ibat"] for x in b) / sum(x[2] for x in b)
            ratio = st.median(x[2] / (x[1]["vac"] * x[1]["iac"]) for x in b)
            gap = st.median(x[1]["vdc"] * x[1]["idc"] - x[2] for x in b)
            la = [x for x in b if x[3] is not None]
            if la:
                tdc = [x[1]["vdc"] * x[1]["ibat"] + x[3] + x[1]["p12"] / ETA_DCDC for x in la]
                loss = st.median(x[2] - t for x, t in zip(la, tdc))
                eff = st.median(t / x[2] for x, t in zip(la, tdc))
                lc = "%6.0f (n=%4d)" % (loss, len(la))
                ec = "%.2f" % eff
            else:
                lc, ec = "%13s" % "-", "  - "
            vaeff = st.median(x[1]["vdc"] * x[1]["idc"] / (x[1]["vac"] * x[1]["iac"]) for x in b)
            print("    %4d-%4d  | %4d | %5.2f | %12.3f | %13.0f | %34s | %8s | %.2f"
                  % (lo, hi, len(b), ratio, w2p, gap, lc, ec, vaeff))
