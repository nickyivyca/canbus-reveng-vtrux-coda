"""bms_soc_learning.py -- plan notes/plans/bms-soc-learning.md (2026-10-10).

Does the A123 BMS count SoC against a fixed ~60 Ah, or learn capacity per
pack? Phased; run from the project root on the Linux box.

  1  session inventory: per Vtrux session in InfluxDB (powertrain bus), start
     and end time, odometer (0x625 VehicleOdometer, 1 km), bms_soc_hires
     (0x411, 0.01 %), bcm_soc, cell vmin/vmax at both ends (the 8.19 V
     no-data sentinel is stored in Influx and is filtered with < 3.8 V), and whether the
     charger drew AC current. Truck by odometer (main >= 90,000 km, parts
     < 60,000 km); pack by truck + the 2025-12-09 swap. Cached to
     bms_soc_learning_inventory.json.
  2  chain sessions per truck in time order and classify each transition:
       clean-flat / clean-up / clean-down   odometer unchanged; |dSoC| < 1 %,
                or SoC rose / fell. Odometer-unchanged is NOT rest: an unlogged
                charge (or stationary use) does not move the odometer either
       untracked odometer moved: unlogged use
       overlap  next session starts before the previous ends (two loggers)
       ambiguous a field is missing at one end
     and list the low-SoC and large SoC-jump wakes (the ~10 % event).

  3  for every clean-up / clean-down transition: garage 14-50 CT energy over
     the gap (homeassistant, bounded per gap, minute averages forward-filled),
     split into charging blocks (> 300 W). Each block is attributed to the Coda
     if a Coda session shows ACInPower > 500 W inside it (the Coda shares the
     outlet and is near-fully logged), to the OTHER Vtrux if one of its
     sessions shows charger AC current inside it, else to this truck. Expected
     SoC rise = block kWh x 0.75 wall-to-pack / (0.225 kWh per %) -- a rough
     scale (58.8 Ah x ~383 V nominal), only to judge whether home charging
     explains the jump. A 550-1100 W plateau is the Vtrux hold signature.
     Charging away from home is invisible to the CT.

  4  (step 2) per session: 1 s series from InfluxDB, server-side GROUP BY
     time(1s) bounded by the session window -- mean bcm_ibat, mean bcm_vbat,
     last bms_soc_hires, max charger AC current. Cached gzipped to
     bms_soc_learning_1s.json.gz. Segments break at any missing second of
     ibat or soc (both are ~20 Hz messages, so a missing 1 s bin is > 20 frame
     periods). Within a segment, Ah = sum(ibat)/3600 (ibat + = charging), kWh
     likewise with vbat. Band traversals: Ah between the first crossing of
     each 10 % SoC edge and the next edge in the same direction, per pack,
     mode (charge = charger AC > 2 A throughout, drive = none) and band.
     SoC steps: |dSoC| >= 0.3 % within one second (0.3 % ~= 0.18 Ah, which
     would need ~650 A for a second) are listed as unexplained by current.

  5  (step 2) startup frame: the first bms_soc_hires value after a BMS
     power-on is a fixed fraction k of the value one second later. k per
     session and pack, over time (no queries; uses the 1 s cache).
  6  (step 2) is the startup frame a 12 V-reset marker? Per session: was the
     BMS power-on captured (one-off bcm_cell_vmin > 8 V sentinel frame within
     30 s of the first SoC point) and was there a startup frame, by month.
     Output bms_soc_learning_bootframes.json.
  7-12 (step 3) -- see the comment block at each phase: wake/end cell data
     and 8.19 V frames (7); transitions and mid-session power-ons (8); holds
     at 100 % and charge after the display reaches 100 % (9); per-pack
     timeline with 1 s weakest cell below 40 % (10); pack current to the end
     of charge (11); SoC rises vs home charging with the CT end-of-charge
     rules (12; one car per block assumed -- a swap inside a block, as on
     2026-06-13, is not detected).

Query rules (tools/tools.md, 2026-09-27): every `signals` statement is bounded
by the session's upload_manifest window and is a single-field LIMIT read --
no COUNT, no unbounded scan, queries strictly sequential. "Start" and "end"
values are medians of the first / last 30 stored points of each field (values
are exact under the on-change + 1 s heartbeat policy; point counts are not
frame counts and are not used).
"""
import sys
sys.path.insert(0, ".")
import base64
import datetime as dt
import json
import os
import statistics as st
import urllib.parse
import urllib.request

PHASES = {13}
ART = "projects/vtrux/notes/artifacts/"
INV = ART + "bms_soc_learning_inventory.json"
SWAP = dt.datetime(2025, 12, 9, tzinfo=dt.timezone.utc).timestamp()
RIG = {"vtrux_20260617_193900", "vtrux_20260617_215641", "vtrux_20260617_220758",
       "vtrux_20260617_221447", "vtrux_20260617_222323", "vtrux_20260618_002023"}
FIELDS = ["VehicleOdometer", "bms_soc_hires", "bcm_soc", "bcm_cell_vmin",
          "bcm_cell_vmax", "bcm_vbat"]
N = 30


def influx(q):
    url = "http://localhost:8086/query?" + urllib.parse.urlencode(
        {"db": "canbus-data", "q": q, "epoch": "ms"})
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Basic " +
                   base64.b64encode(b"claude:claude").decode())
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    rows, cols = [], None
    for res in d.get("results", []):
        for se in res.get("series", []):
            cols = se["columns"]
            rows.extend(se["values"])
    return cols, rows


def manifest_windows():
    cols, rows = influx("SELECT session, file, uploaded_at, t_start_ns, t_end_ns "
                        "FROM upload_manifest WHERE \"vehicle\"='vtrux'")
    newest = {}
    for v in rows:
        r = dict(zip(cols, v))
        k = (r["session"], r["file"])
        if r.get("t_start_ns") and r.get("t_end_ns") and (
                k not in newest or r["uploaded_at"] > newest[k]["uploaded_at"]):
            newest[k] = r
    win = {}
    for (s, _f), r in newest.items():
        a, b = r["t_start_ns"] // 10**9, r["t_end_ns"] // 10**9 + 1
        w = win.get(s)
        win[s] = (min(a, w[0]), max(b, w[1])) if w else (a, b)
    return win


def ends(session, field, w0, w1):
    base = ("SELECT \"%s\" FROM signals WHERE vehicle='vtrux' AND session='%s' "
            "AND bus='powertrain' AND time >= %ds AND time < %ds"
            % (field, session, w0, w1))
    if field in ("bcm_cell_vmin", "bcm_cell_vmax"):
        base += " AND \"%s\" < 3.8" % field
    _c, a = influx(base + " ORDER BY time ASC LIMIT %d" % N)
    _c, b = influx(base + " ORDER BY time DESC LIMIT %d" % N)
    a = [r for r in a if r[1] is not None]
    b = [r for r in b if r[1] is not None]
    if not a or not b:
        return None
    return {"t0": a[0][0] / 1000, "t1": b[0][0] / 1000,
            "v0": st.median(r[1] for r in a), "v1": st.median(r[1] for r in b)}


def charged(session, w0, w1):
    _c, r = influx("SELECT \"BELINV_chargerInputCurrent\" FROM signals WHERE "
                   "vehicle='vtrux' AND session='%s' AND bus='powertrain' AND "
                   "time >= %ds AND time < %ds AND \"BELINV_chargerInputCurrent\" "
                   "> 2 AND \"BELINV_chargerInputCurrent\" < 60 LIMIT 1"
                   % (session, w0, w1))
    return bool(r)


def utc(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


if 1 in PHASES:
    win = manifest_windows()
    print("phase1: %d sessions with a manifest window" % len(win), flush=True)
    inv = {}
    for i, (s, (w0, w1)) in enumerate(sorted(win.items())):
        rec = {"w0": w0, "w1": w1, "f": {}}
        for f in FIELDS:
            rec["f"][f] = ends(s, f, w0, w1)
        rec["chg"] = charged(s, w0, w1)
        inv[s] = rec
        if i % 25 == 0:
            print("  %d/%d" % (i, len(win)), flush=True)
    with open(INV, "w") as fh:
        json.dump(inv, fh)
else:
    inv = json.load(open(INV))


def truck(rec):
    o = rec["f"]["VehicleOdometer"]
    if not o:
        return None
    v = o["v0"]
    return "main" if v >= 90000 else ("parts" if v < 60000 else "unknown")


def pack(tr, t):
    if tr is None or tr == "unknown":
        return None
    pre = t < SWAP
    return {("main", True): "main-orig", ("main", False): "parts-orig",
            ("parts", True): "parts-orig", ("parts", False): "main-orig"}[(tr, pre)]


if 2 in PHASES:
    rows = []
    for s, rec in inv.items():
        ts = [x["t0"] for x in rec["f"].values() if x]
        te = [x["t1"] for x in rec["f"].values() if x]
        if not ts:
            continue
        tr = truck(rec)
        g = lambda f, k: rec["f"][f][k] if rec["f"][f] else None
        rows.append({"s": s, "t0": min(ts), "t1": max(te), "truck": tr,
                     "pack": pack(tr, min(ts)), "odo0": g("VehicleOdometer", "v0"),
                     "odo1": g("VehicleOdometer", "v1"), "soc0": g("bms_soc_hires", "v0"),
                     "soc1": g("bms_soc_hires", "v1"), "isoc0": g("bcm_soc", "v0"),
                     "isoc1": g("bcm_soc", "v1"), "vmin0": g("bcm_cell_vmin", "v0"),
                     "vmin1": g("bcm_cell_vmin", "v1"), "vmax0": g("bcm_cell_vmax", "v0"),
                     "vmax1": g("bcm_cell_vmax", "v1"), "chg": rec["chg"],
                     "rig": s in RIG})
    rows.sort(key=lambda r: r["t0"])
    f = lambda x, fmt: (fmt % x) if x is not None else "-"
    print("\nphase2: %d sessions with powertrain data" % len(rows))
    for tr in ("main", "parts", "unknown", None):
        rr = [r for r in rows if r["truck"] == tr]
        print("  truck %-7s %3d sessions  %s" % (tr, len(rr), ", ".join(
            "%s %d" % (p, sum(1 for r in rr if r["pack"] == p))
            for p in ("main-orig", "parts-orig", None))))
    print("\n  sessions with no odometer (no truck):")
    for r in rows:
        if r["truck"] is None:
            print("    %-46s %s  soc %s -> %s  chg %s" % (r["s"], utc(r["t0"]),
                  f(r["soc0"], "%.2f"), f(r["soc1"], "%.2f"), r["chg"]))

    trans = []
    for tr in ("main", "parts"):
        rr = [r for r in rows if r["truck"] == tr]
        print("\n  ===== %s truck: sessions in time order =====" % tr)
        print("    %-46s %-16s %-10s %7s %7s | %6s->%6s | %5s->%5s | %5s->%5s | chg rig | gap h  dodo  dsoc  class"
              % ("session", "start UTC", "pack", "odo0", "dodo", "soc0", "soc1",
                 "vmin0", "vmin1", "vmax0", "vmax1"))
        prev = None
        for r in rr:
            cl = gap = dodo = dsoc = None
            if prev:
                gap = (r["t0"] - prev["t1"]) / 3600
                if r["t0"] < prev["t1"] - 60:
                    cl = "overlap"
                elif None in (r["odo0"], prev["odo1"], r["soc0"], prev["soc1"]):
                    cl = "ambiguous"
                else:
                    dodo = r["odo0"] - prev["odo1"]
                    dsoc = r["soc0"] - prev["soc1"]
                    if dodo != 0:
                        cl = "untracked"
                    elif abs(dsoc) < 1:
                        cl = "clean-flat"
                    else:
                        cl = "clean-up" if dsoc > 0 else "clean-down"
                trans.append({"truck": tr, "a": prev["s"], "b": r["s"], "gap_h": gap,
                              "dodo": dodo, "dsoc": dsoc, "cls": cl,
                              "pack_a": prev["pack"], "pack_b": r["pack"],
                              "soc_a": prev["soc1"], "soc_b": r["soc0"],
                              "vmin_a": prev["vmin1"], "vmin_b": r["vmin0"],
                              "t_b": r["t0"]})
            print("    %-46s %-16s %-10s %7s %7s | %6s->%6s | %5s->%5s | %5s->%5s | %-3s %-3s | %s"
                  % (r["s"][:46], utc(r["t0"]), r["pack"], f(r["odo0"], "%.0f"),
                     f((r["odo1"] - r["odo0"]) if r["odo0"] is not None and r["odo1"] is not None else None, "%+.0f"),
                     f(r["soc0"], "%.2f"), f(r["soc1"], "%.2f"), f(r["vmin0"], "%.3f"),
                     f(r["vmin1"], "%.3f"), f(r["vmax0"], "%.3f"), f(r["vmax1"], "%.3f"),
                     "Y" if r["chg"] else "", "RIG" if r["rig"] else "",
                     ("%6.1f %5s %5s  %s" % (gap, f(dodo, "%+.0f"), f(dsoc, "%+.2f"), cl))
                     if prev else ""))
            prev = r
    with open(ART + "bms_soc_learning_transitions.json", "w") as fh:
        json.dump({"sessions": rows, "transitions": trans}, fh)

    print("\n  transition classes per truck / pack-at-wake:")
    for tr in ("main", "parts"):
        for p in ("main-orig", "parts-orig"):
            tt = [t for t in trans if t["truck"] == tr and t["pack_b"] == p]
            if tt:
                print("    %-5s %-10s %s" % (tr, p, ", ".join(
                    "%s %d" % (c, sum(1 for t in tt if t["cls"] == c))
                    for c in ("clean-flat", "clean-up", "clean-down", "untracked", "overlap", "ambiguous"))))
    print("\n  wakes at low SoC (start soc_hires < 18 %) or with |dSoC| >= 3 % across a clean rest:")
    for t in trans:
        if (t["soc_b"] is not None and t["soc_b"] < 18) or (
                t["cls"] in ("clean-up", "clean-down") and abs(t["dsoc"]) >= 3):
            print("    %-5s %s  %-40s -> %-40s %s  gap %.1f h  soc %s -> %s  vmin %s -> %s  dodo %s"
                  % (t["truck"], utc(t["t_b"]), t["a"][:40], t["b"][:40], t["cls"],
                     t["gap_h"], f(t["soc_a"], "%.2f"), f(t["soc_b"], "%.2f"),
                     f(t["vmin_a"], "%.3f"), f(t["vmin_b"], "%.3f"), f(t["dodo"], "%+.0f")))


CT = "garage_14_50_power_minute_average"


def ha(q):
    url = "http://localhost:8086/query?" + urllib.parse.urlencode(
        {"db": "homeassistant", "q": q, "epoch": "s"})
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Basic " +
                   base64.b64encode(b"claude:claude").decode())
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    out = []
    for res in d.get("results", []):
        for se in res.get("series", []):
            out.extend(se["values"])
    out.sort()
    return out


def coda_windows():
    cols, rows = influx("SELECT session, file, uploaded_at, t_start_ns, t_end_ns "
                        "FROM upload_manifest WHERE \"vehicle\"='coda'")
    win = {}
    for v in rows:
        r = dict(zip(cols, v))
        if not (r.get("t_start_ns") and r.get("t_end_ns")):
            continue
        a, b = r["t_start_ns"] // 10**9, r["t_end_ns"] // 10**9 + 1
        w = win.get(r["session"])
        win[r["session"]] = (min(a, w[0]), max(b, w[1])) if w else (a, b)
    return win


def any_row(q):
    _c, r = influx(q + " LIMIT 1")
    return bool(r)


if 3 in PHASES:
    tr = json.load(open(ART + "bms_soc_learning_transitions.json"))
    sess = {r["s"]: r for r in tr["sessions"]}
    cw = coda_windows()
    vw = {r["s"]: (r["t0"], r["t1"], r["truck"]) for r in tr["sessions"]}
    print("\nphase3: garage CT over each odometer-unchanged gap with |dSoC| >= 1 %%"
          " (coda sessions known: %d)" % len(cw))
    res = []
    for t in tr["transitions"]:
        if t["cls"] not in ("clean-up", "clean-down"):
            continue
        g0, g1 = int(sess[t["a"]]["t1"]), int(sess[t["b"]]["t0"])
        rows = ha("SELECT value FROM \"W\" WHERE entity_id='%s' AND time >= %ds AND "
                  "time < %ds" % (CT, g0 - 3600, g1 + 60))
        if g0 < 1764460800:
            cov = "no CT (before 2025-11-30)"
        elif not rows:
            cov = "no CT rows"
        else:
            cov = "CT"
        blocks, cur, val = [], None, 0.0
        k = 0
        for m in range(g0, g1, 60):
            while k < len(rows) and rows[k][0] <= m:
                val = rows[k][1]
                k += 1
            if val > 300:
                if cur is None:
                    cur = [m, m, 0.0, 0.0]
                cur[1] = m + 60
                cur[2] += val / 60000
                cur[3] = max(cur[3], val)
            elif cur is not None:
                blocks.append(cur)
                cur = None
        if cur is not None:
            blocks.append(cur)
        att = []
        for b0, b1, kwh, pk in blocks:
            who = None
            for cs, (c0, c1) in cw.items():
                if c0 < b1 and b0 < c1 and any_row(
                        "SELECT \"ACInPower\" FROM signals WHERE vehicle='coda' AND "
                        "session='%s' AND time >= %ds AND time < %ds AND "
                        "\"ACInPower\" > 500" % (cs, max(b0, c0), min(b1, c1))):
                    who = "coda:" + cs
                    break
            if who is None:
                for vs, (v0, v1, vt) in vw.items():
                    if vt != t["truck"] and v0 < b1 and b0 < v1 and any_row(
                            "SELECT \"BELINV_chargerInputCurrent\" FROM signals WHERE "
                            "vehicle='vtrux' AND session='%s' AND time >= %ds AND "
                            "time < %ds AND \"BELINV_chargerInputCurrent\" > 2 AND "
                            "\"BELINV_chargerInputCurrent\" < 60"
                            % (vs, max(b0, int(v0)), min(b1, int(v1)) + 1)):
                        who = "other-vtrux:" + vs
                        break
            att.append((b0, b1, kwh, pk, who or "this truck (no other logged charger)"))
        mine = sum(a[2] for a in att if a[4].startswith("this"))
        exp = mine * 0.75 / 0.225
        res.append((t, cov, att, mine, exp))
        print("\n  %s  %-5s %-10s %s -> %s  gap %.1f h  soc %.2f -> %.2f (%+.2f)  [%s]"
              % (utc(t["t_b"]), t["truck"], t["pack_b"], t["a"], t["b"], t["gap_h"],
                 t["soc_a"], t["soc_b"], t["dsoc"], cov))
        for b0, b1, kwh, pk, who in att:
            print("      block %s .. %s  %5.1f min  %6.2f kWh  peak %5.0f W  -> %s"
                  % (utc(b0), utc(b1)[11:], (b1 - b0) / 60, kwh, pk, who))
        if cov == "CT":
            print("      this-truck home energy %.2f kWh -> expected dSoC ~%+.1f %%  (observed %+.2f)"
                  % (mine, exp, t["dsoc"]))
    print("\n  summary (odometer-unchanged gaps, |dSoC| >= 1 %):")
    for t, cov, att, mine, exp in res:
        if cov != "CT":
            verdict = "no CT coverage"
        elif t["dsoc"] > 0:
            verdict = ("home charge explains it" if mine > 0 and abs(exp - t["dsoc"]) < max(5, 0.5 * t["dsoc"])
                       else "home charge, size mismatch" if mine > 0
                       else "NO home charge: away charging or upward correction")
        else:
            verdict = ("no charge in gap" if mine == 0 else "charger drew %.2f kWh (hold?)" % mine)
        print("    %s %-10s %+7.2f %%  %-26s %s" % (utc(t["t_b"]), t["pack_b"], t["dsoc"],
              cov[:26], verdict))


OUT1S = ART + "bms_soc_learning_1s.json.gz"
if 4 in PHASES:
    import gzip
    tr = json.load(open(ART + "bms_soc_learning_transitions.json"))
    sess = [r for r in tr["sessions"] if r["pack"]]
    inv = json.load(open(INV))
    if os.path.exists(OUT1S):
        ser = json.load(gzip.open(OUT1S, "rt"))
    else:
        ser = {}
        for i, r in enumerate(sess):
            w0, w1 = inv[r["s"]]["w0"], inv[r["s"]]["w1"]
            out = {}
            for f, agg in (("bcm_ibat", "MEAN"), ("bcm_vbat", "MEAN"),
                           ("bms_soc_hires", "LAST"),
                           ("BELINV_chargerInputCurrent", "MAX")):
                extra = (" AND \"bcm_ibat\" > -500 AND \"bcm_ibat\" < 500" if f == "bcm_ibat" else
                         " AND \"BELINV_chargerInputCurrent\" < 60" if f.startswith("BELINV") else "")
                _c, rows = influx("SELECT %s(\"%s\") FROM signals WHERE vehicle='vtrux' AND "
                                  "session='%s' AND bus='powertrain' AND time >= %ds AND "
                                  "time < %ds%s GROUP BY time(1s) fill(none)"
                                  % (agg, f, r["s"], w0, w1, extra))
                out[f] = {str(t // 1000): v for t, v in rows if v is not None}
            ser[r["s"]] = out
            if i % 20 == 0:
                print("  pulled %d/%d" % (i, len(sess)), flush=True)
        with gzip.open(OUT1S, "wt") as fh:
            json.dump(ser, fh)

    BANDS = list(range(0, 101, 10))
    trav = []
    steps = []
    signchk = {"chg_up": 0, "chg_down": 0}
    seginfo = []
    for r in sess:
        d = ser.get(r["s"])
        if not d:
            continue
        ib, vb, sc, ac = (d["bcm_ibat"], d["bcm_vbat"], d["bms_soc_hires"],
                          d["BELINV_chargerInputCurrent"])
        ts = sorted(int(t) for t in ib if t in sc)
        segs, cur = [], []
        for t in ts:
            if cur and t - cur[-1] > 1:
                segs.append(cur)
                cur = []
            cur.append(t)
        if cur:
            segs.append(cur)
        for seg in segs:
            if len(seg) < 60:
                continue
            ah = 0.0
            kwh = 0.0
            cum = []
            for k, t in enumerate(seg):
                if k:
                    i = ib[str(t)]
                    ah += i / 3600
                    v = vb.get(str(t))
                    if v:
                        kwh += v * i / 3.6e6
                cum.append((t, sc[str(t)], ah, kwh, ac.get(str(t), 0) or 0))
            for (t0, s0, a0, _k0, _), (t1, s1, a1, _k1, _) in zip(cum, cum[1:]):
                if abs(s1 - s0) >= 0.3:
                    steps.append((r["s"], r["pack"], t1, s0, s1, a1 - a0))
            dso = cum[-1][1] - cum[0][1]
            dah = cum[-1][2]
            if abs(dso) >= 5:
                chg = sum(1 for x in cum if x[4] > 2) / len(cum)
                seginfo.append((r["s"], r["pack"], seg[0], dso, dah, cum[-1][3], chg))
                if chg > 0.9 and dso > 0:
                    signchk["chg_up"] += dah > 0
                    signchk["chg_down"] += dah <= 0
            for up in (True, False):
                edges = BANDS if up else BANDS[::-1]
                hit = {}
                for t, so, a, k, acx in cum:
                    for e in edges:
                        if e not in hit and ((up and so >= e) or (not up and so <= e)):
                            if (up and cum[0][1] < e) or (not up and cum[0][1] > e):
                                hit[e] = (t, a, k, so)
                for e0, e1 in zip(edges, edges[1:]):
                    if e0 in hit and e1 in hit and hit[e1][0] > hit[e0][0]:
                        t0, a0, k0, _ = hit[e0]
                        t1, a1, k1, _ = hit[e1]
                        accs = [x[4] for x in cum if t0 <= x[0] <= t1]
                        mode = ("charge" if accs and min(accs) > 2 else
                                "drive" if accs and max(accs) <= 2 else "mixed")
                        trav.append((r["s"], r["pack"], t0, min(e0, e1), mode,
                                     (a1 - a0) / 10, (k1 - k0) / 10, (t1 - t0) / 60))
    print("\nphase4 (step 2): %d sessions with 1 s data, %d band traversals, %d segments with |dSoC| >= 5 %%"
          % (len(ser), len(trav), len(seginfo)))
    print("  sign check, charging segments with SoC rising: integrated Ah > 0 in %d, <= 0 in %d"
          % (signchk["chg_up"], signchk["chg_down"]))
    print("\n  Ah per %% SoC by band (|Ah|/10 per 10 %% band; 0.588 = 58.8 Ah, 0.600 = 60 Ah)")
    print("    pack        mode    band   |   n | Ah/%% med (q1..q3)      | Wh/%% med | min/%% med")
    for p in ("main-orig", "parts-orig"):
        for mode in ("charge", "drive", "mixed"):
            for lo in BANDS[:-1]:
                x = [t for t in trav if t[1] == p and t[4] == mode and t[3] == lo]
                if not x:
                    continue
                a = sorted(abs(t[5]) for t in x)
                k = sorted(abs(t[6]) for t in x)
                m = sorted(t[7] for t in x)
                print("    %-10s  %-6s  %3d-%-3d| %3d | %.3f (%.3f..%.3f) | %7.1f  | %6.1f"
                      % (p, mode, lo, lo + 10, len(x), st.median(a), a[len(a) // 4],
                         a[3 * len(a) // 4], st.median(k) * 1000, st.median(m)))
    print("\n  per-segment overall Ah per %% (|dSoC| >= 5 %%), in time order")
    print("    date        pack        session                                   dSoC     Ah     Ah/%%  chg-frac")
    for s_, p, t0, dso, dah, dk, chg in sorted(seginfo, key=lambda x: x[2]):
        print("    %s  %-10s  %-40s %+7.2f %+7.2f  %.3f  %.2f"
              % (utc(t0)[:10], p, s_[:40], dso, dah, abs(dah / dso), chg))
    print("\n  SoC steps >= 0.3 %% within 1 s (unexplained by current): %d" % len(steps))
    for s_, p, t1, s0, s1, da in steps:
        print("    %s  %-10s  %-40s  %6.2f -> %6.2f  (Ah in that second %+.4f)"
              % (utc(t1), p, s_[:40], s0, s1, da))
    with open(ART + "bms_soc_learning_step2.json", "w") as fh:
        json.dump({"traversals": trav, "segments": seginfo, "steps": steps}, fh)


def startup_step(sc):
    ts = sorted(int(t) for t in sc)
    if len(ts) < 10:
        return None
    v = [sc[str(t)] for t in ts[:15]]
    for i in range(min(10, len(v) - 1)):
        a, b = v[i], v[i + 1]
        if b > 1 and a > 1 and abs(b - a) >= 1 and 0.6 < a / b < 0.95:
            return ts[0], a, b, a / b
    return None


if 5 in PHASES or 6 in PHASES:
    import gzip
    ser = json.load(gzip.open(OUT1S, "rt"))
    tr = json.load(open(ART + "bms_soc_learning_transitions.json"))
    pk = {r["s"]: r["pack"] for r in tr["sessions"]}

if 5 in PHASES:
    print("\nphase5: startup frame ratio k = first / settled bms_soc_hires")
    for p in ("main-orig", "parts-orig"):
        x = sorted((startup_step(d["bms_soc_hires"]) + (s_,)) for s_, d in ser.items()
                   if pk.get(s_) == p and startup_step(d["bms_soc_hires"]))
        ks = [v[3] for v in x]
        print("  %s: n=%d  k median %.4f (min %.4f max %.4f)  58.8 Ah x k = %.1f Ah"
              % (p, len(x), st.median(ks), min(ks), max(ks), 58.8 * st.median(ks)))
        for t0, a, b, k, s_ in x:
            print("    %s  %6.2f -> %6.2f  k=%.4f  %s" % (utc(t0)[:10], a, b, k, s_))

if 6 in PHASES:
    import collections
    rows = []
    for r in tr["sessions"]:
        d = ser.get(r["s"]) if r["pack"] else None
        if not d or len(d["bms_soc_hires"]) < 10:
            continue
        t0 = min(int(t) for t in d["bms_soc_hires"])
        _c, sent = influx("SELECT \"bcm_cell_vmin\" FROM signals WHERE vehicle='vtrux' AND "
                          "session='%s' AND bus='powertrain' AND time >= %ds AND time < %ds "
                          "AND \"bcm_cell_vmin\" > 8 LIMIT 1" % (r["s"], t0 - 30, t0 + 30))
        rows.append((r["t0"], r["pack"], r["s"], bool(sent),
                     bool(startup_step(d["bms_soc_hires"]))))
    by = collections.defaultdict(lambda: [0, 0, 0, 0])
    for t, p, s_, sent, step in rows:
        x = by[utc(t)[:7] + " " + p]
        x[0] += 1; x[1] += sent; x[2] += step; x[3] += sent and step
    print("\nphase6: month / pack | sessions | power-on captured | startup frame | both")
    for m in sorted(by):
        print("  %-20s %4d %6d %6d %6d" % ((m,) + tuple(by[m])))
    json.dump(rows, open(ART + "bms_soc_learning_bootframes.json", "w"))


# ---------------------------------------------------------------- step 3
# 7  pull, per session (powertrain bus, bounded by the session window):
#      - every BMS power-on inside the window: bcm_cell_vmin > 8 (the stored
#        8.19 V no-data frame), clustered at 10 s;
#      - the first and last WIN s of bcm_cell_vmin / vmax (< 3.8) and
#        bcm_cell_tmin / tmax, as raw stored points.
#    Cached to bms_soc_learning_wakeend.json.
# 8  analysis: each odometer-unchanged transition, end of A -> wake of B.
#    Wake values are taken after the startup frame. "Settled" voltage = the
#    median vmin over seconds with |ibat| < 2 A in the window. A wake
#    correction = the SoC moving >= 0.3 % in the first WIN s by more than
#    the Ah integrated over the same seconds explains (at the pack's Ah/%).
WIN = 180
WE = ART + "bms_soc_learning_wakeend.json"

if 7 in PHASES:
    import gzip
    tr = json.load(open(ART + "bms_soc_learning_transitions.json"))
    inv = json.load(open(INV))
    out = json.load(open(WE)) if os.path.exists(WE) else {}
    sess = [r for r in tr["sessions"] if r["pack"] and r["s"] not in out]
    print("\nphase7: pulling %d sessions" % len(sess), flush=True)
    for i, r in enumerate(sess):
        w0, w1 = inv[r["s"]]["w0"], inv[r["s"]]["w1"]
        base = ("FROM signals WHERE vehicle='vtrux' AND session='%s' AND "
                "bus='powertrain' AND time >= %%ds AND time < %%ds" % r["s"])
        _c, boots = influx(("SELECT \"bcm_cell_vmin\" " + base + " AND \"bcm_cell_vmin\" > 8 "
                            "LIMIT 500") % (w0, w1))
        on = []
        for t, _v in boots:
            if not on or t / 1000 - on[-1] > 10:
                on.append(t / 1000)
        rec = {"boots": on}
        a0, a1 = int(r["t0"]), int(r["t1"]) + 1
        for tag, (q0, q1) in (("wake", (a0, a0 + WIN)), ("end", (a1 - WIN, a1))):
            for f in ("bcm_cell_vmin", "bcm_cell_vmax", "bcm_cell_tmin", "bcm_cell_tmax"):
                lim = " AND \"%s\" < 3.8" % f if "_v" in f else ""
                _c, rows = influx(("SELECT \"%s\" " % f + base + lim + " LIMIT 5000")
                                  % (q0, q1))
                rec[tag + ":" + f] = [(t / 1000, v) for t, v in rows if v is not None]
        out[r["s"]] = rec
        if i % 20 == 0:
            print("  %d/%d" % (i, len(sess)), flush=True)
            json.dump(out, open(WE, "w"))
    json.dump(out, open(WE, "w"))

if 8 in PHASES:
    import gzip
    ser = json.load(gzip.open(OUT1S, "rt"))
    tr = json.load(open(ART + "bms_soc_learning_transitions.json"))
    we = json.load(open(WE))
    sess = {r["s"]: r for r in tr["sessions"]}
    ERA = dt.datetime(2026, 6, 17, 7, tzinfo=dt.timezone.utc).timestamp()
    AHP = {"main-orig": 0.486, "parts-orig": 0.464}

    def ffill(pts, t):
        v = None
        for tp, x in pts:
            if tp > t:
                break
            v = x
        return v

    def settled(s_, tag):
        """median vmin / vmax / tmin over seconds with |ibat| < 2 A in the window"""
        d, w = ser.get(s_), we.get(s_)
        if not d or not w:
            return None
        ib = d["bcm_ibat"]
        vmn = sorted(w[tag + ":bcm_cell_vmin"])
        vmx = sorted(w[tag + ":bcm_cell_vmax"])
        tmn = sorted(x for x in w[tag + ":bcm_cell_tmin"] if x[1] < 80)  # 87 C = no-data
        if not vmn:
            return None
        t0, t1 = int(vmn[0][0]), int(vmn[-1][0]) + 1
        if tag == "end":
            t0 = max(t0, int(sess[s_]["t1"]) - WIN)
        a, b, c, cur = [], [], [], []
        for t in range(t0, t1 + 1):
            i = ib.get(str(t))
            if i is None:
                continue
            cur.append(i)
            if abs(i) < 2:
                a.append(ffill(vmn, t + .99))
                b.append(ffill(vmx, t + .99))
                c.append(ffill(tmn, t + .99))
        a = [x for x in a if x]
        if not a:
            return {"vmin": None, "imed": st.median(cur) if cur else None,
                    "tmin": st.median([x for _t, x in tmn]) if tmn else None}
        return {"vmin": st.median(a), "vmax": st.median([x for x in b if x]),
                "tmin": st.median([x for x in c if x is not None]) if any(
                    x is not None for x in c) else None,
                "n": len(a), "imed": st.median(cur)}

    def wake_soc(s_):
        """first settled SoC (after any startup frame), SoC at +WIN, Ah in between"""
        d = ser.get(s_)
        if not d:
            return None
        sc, ib = d["bms_soc_hires"], d["bcm_ibat"]
        ts = sorted(int(t) for t in sc)
        if len(ts) < 10:
            return None
        su = startup_step(sc)
        i0 = 0
        if su:
            while i0 < len(ts) - 1 and abs(sc[str(ts[i0])] - su[1]) < 1e-6:
                i0 += 1
        t0 = ts[i0]
        first = sc[str(t0)]
        win = [t for t in ts if t0 <= t <= t0 + WIN]
        last = sc[str(win[-1])]
        lo = min(sc[str(t)] for t in win)
        ah = sum(ib.get(str(t), 0) for t in range(t0 + 1, win[-1] + 1)) / 3600
        return {"t0": t0, "first": first, "last": last, "min": lo, "ah": ah,
                "startup": bool(su), "dt": win[-1] - t0}

    def end_soc(s_):
        d = ser.get(s_)
        if not d or not d["bms_soc_hires"]:
            return None
        sc = d["bms_soc_hires"]
        t = max(int(x) for x in sc)
        return {"t": t, "soc": sc[str(t)]}

    print("\nphase8 (step 3): odometer-unchanged transitions, end of A -> wake of B")
    print("  boot = BMS power-on captured at B's start (8.19 V frame within 30 s of the"
          " first SoC point); corr = SoC change in B's first %d s not explained by Ah" % WIN)
    hdr = ("    %-16s %-10s %-5s %6s | %6s -> %6s (%6s) | %-4s first %6s +%3ds %6s corr %+6.2f |"
           " vmin %5s -> %5s  vmax %5s -> %5s | T %4s -> %4s | %s")
    rows = []
    for t in tr["transitions"]:
        if t["cls"] not in ("clean-flat", "clean-down", "clean-up") or not t["pack_b"]:
            continue
        a, b = t["a"], t["b"]
        ea, wb = end_soc(a), wake_soc(b)
        if not ea or not wb:
            continue
        sa, sb = settled(a, "end"), settled(b, "wake")
        w = we.get(b, {})
        boot = any(abs(x - wb["t0"]) < 30 for x in w.get("boots", []))
        corr = (wb["last"] - wb["first"]) - wb["ah"] / AHP[t["pack_b"]]
        rest_h = (wb["t0"] - ea["t"]) / 3600
        rows.append({"t": t, "ea": ea, "wb": wb, "sa": sa, "sb": sb, "boot": boot,
                     "corr": corr, "rest_h": rest_h, "era": "pre" if wb["t0"] < ERA else "post"})
    f = lambda x, fmt: (fmt % x) if x is not None else "  -  "
    for p in ("main-orig", "parts-orig"):
        rr = [r for r in rows if r["t"]["pack_b"] == p]
        print("\n  ===== %s (%d transitions) =====" % (p, len(rr)))
        print("    wake (UTC)       cls        era   rest h | SoC end A -> first B (diff)  | boot"
              "        SoC at +WIN       | settled cell V end A -> wake B | Tmin | session B")
        for r in sorted(rr, key=lambda r: r["wb"]["t0"]):
            t, sa, sb = r["t"], r["sa"] or {}, r["sb"] or {}
            print(hdr % (utc(r["wb"]["t0"]), t["cls"], r["era"], f(r["rest_h"], "%6.1f"),
                         f(r["ea"]["soc"], "%6.2f"), f(r["wb"]["first"], "%6.2f"),
                         f(r["wb"]["first"] - r["ea"]["soc"], "%+6.2f"), "BOOT" if r["boot"] else "",
                         f(r["wb"]["first"], "%6.2f"), r["wb"]["dt"], f(r["wb"]["last"], "%6.2f"),
                         r["corr"], f(sa.get("vmin"), "%.3f"), f(sb.get("vmin"), "%.3f"),
                         f(sa.get("vmax"), "%.3f"), f(sb.get("vmax"), "%.3f"),
                         f(sa.get("tmin"), "%4.1f"), f(sb.get("tmin"), "%4.1f"), t["b"][:40]))

    print("\n  wake corrections >= 0.3 %% in the first %d s (not explained by Ah):" % WIN)
    for r in sorted(rows, key=lambda r: r["wb"]["t0"]):
        if abs(r["corr"]) >= 0.3:
            print("    %s %-10s %-4s boot=%-5s SoC first %.2f -> +%ds %.2f (min %.2f) corr %+.2f"
                  "  end-A %.2f  rest %.1f h  %s" % (utc(r["wb"]["t0"]), r["t"]["pack_b"], r["era"],
                  r["boot"], r["wb"]["first"], r["wb"]["dt"], r["wb"]["last"], r["wb"]["min"],
                  r["corr"], r["ea"]["soc"], r["rest_h"], r["t"]["b"]))

    print("\n  per pack / era: rests, the wake-vs-end difference (first B - end A), and"
          " boots captured")
    for p in ("main-orig", "parts-orig"):
        for era in ("pre", "post"):
            rr = [r for r in rows if r["t"]["pack_b"] == p and r["era"] == era]
            if not rr:
                continue
            d = sorted(r["wb"]["first"] - r["ea"]["soc"] for r in rr)
            print("    %-10s %-4s n=%3d  boots %3d | diff med %+.2f  q1 %+.2f  q3 %+.2f  min %+.2f"
                  " max %+.2f | |diff|>=1 %%: %d  | corrections >= 0.3 %%: %d"
                  % (p, era, len(rr), sum(r["boot"] for r in rr), st.median(d), d[len(d) // 4],
                     d[3 * len(d) // 4], d[0], d[-1], sum(1 for x in d if abs(x) >= 1),
                     sum(1 for r in rr if abs(r["corr"]) >= 0.3)))

    print("\n  settled vmin at wake (|ibat| < 2 A) against wake SoC, by pack and 10 %% band:")
    for p in ("main-orig", "parts-orig"):
        for lo in range(10, 100, 10):
            x = [(r["sb"]["vmin"], r["sb"]["vmax"], r["era"]) for r in rows
                 if r["t"]["pack_b"] == p and r["sb"] and r["sb"].get("vmin")
                 and lo <= r["wb"]["last"] < lo + 10]
            if x:
                v = sorted(y[0] for y in x)
                print("    %-10s %2d-%-3d n=%3d  vmin med %.3f (%.3f..%.3f)  vmax med %.3f"
                      % (p, lo, lo + 10, len(x), st.median(v), v[0], v[-1],
                         st.median(y[1] for y in x)))

    print("\n  rest drift on clean-flat rests (first B - end A) against rest length, by era:")
    for p in ("main-orig", "parts-orig"):
        for era in ("pre", "post"):
            for lo, hi in ((0, 2), (2, 12), (12, 48), (48, 1e9)):
                x = [r["wb"]["first"] - r["ea"]["soc"] for r in rows
                     if r["t"]["pack_b"] == p and r["era"] == era and r["t"]["cls"] == "clean-flat"
                     and lo <= r["rest_h"] < hi]
                if x:
                    print("    %-10s %-4s rest %3s-%-4s h  n=%3d  med %+.3f  min %+.3f  max %+.3f"
                          % (p, era, lo, "inf" if hi > 1e8 else int(hi), len(x), st.median(x),
                             min(x), max(x)))

    mid = []
    print("\n  every 8.19 V cell-voltage frame inside a session, excluding the session start:")
    for s_ in sorted(we, key=lambda s: sess[s]["t0"]):
        sc = ser.get(s_, {}).get("bms_soc_hires", {})
        t0 = min((int(t) for t in sc), default=None)
        for bt in we[s_]["boots"]:
            if t0 is not None and bt - t0 < 30:
                continue
            ts = sorted(int(t) for t in sc)
            pre = [sc[str(t)] for t in ts if bt - 60 <= t < bt - 1]
            post = [sc[str(t)] for t in ts if bt - 1 <= t <= bt + 90]
            ref = pre[-1] if pre else None
            stp = [v for v in post[:6] if ref and 0.6 < v / ref < 0.95]
            after = [v for v in post[:12] if not ref or not 0.6 < v / ref < 0.95]
            kind = ("POWER-ON (startup frame k=%.4f)" % (stp[0] / ref)) if stp else (
                "startup frame, no SoC before" if not ref and post and any(
                    0.6 < a / b < 0.95 for a, b in zip(post, post[1:6]) if b > 1) else "sentinel only")
            mid.append((s_, bt, kind, ref, after[1] if len(after) > 1 else None))
            print("    %s %-10s %-40s  SoC before %s  after (90 s): %s   [%s]" % (
                utc(bt), sess[s_]["pack"], s_[:40], f(ref, "%.2f"),
                " ".join("%.2f" % v for v in post[:12]), kind))

    pw = [m for m in mid if m[2].startswith("POWER-ON")]
    print("\n  mid-session 8.19 V frames: %d; with a startup frame (power-on) %d, sentinel only %d"
          % (len(mid), len(pw), sum(1 for m in mid if m[2] == "sentinel only")))
    dd = [m[4] - m[3] for m in pw if m[4] is not None]
    print("  power-ons with SoC before: settled SoC after - before: n=%d, max |diff| %.2f"
          % (len(dd), max(abs(x) for x in dd)))
    json.dump([{"a": r["t"]["a"], "b": r["t"]["b"], "cls": r["t"]["cls"], "pack": r["t"]["pack_b"],
                "era": r["era"], "rest_h": r["rest_h"], "end": r["ea"], "wake": r["wb"],
                "set_end": r["sa"], "set_wake": r["sb"], "boot": r["boot"], "corr": r["corr"]}
               for r in rows], open(ART + "bms_soc_learning_step3.json", "w"))


# 9  (step 3, user lead 2026-10-10: "the needle stayed at ~100 % for a long
#    time before it started dropping") -- for every discharge that starts at
#    an indicated 100.00 %, the Ah drawn (bcm_ibat < 0, 1 s cache) while SoC
#    stays >= 99.99 (net, so regen counts), the Ah/% from leaving 100 to 90 / 80 / segment end, and
#    the whole-run Ah/% including the held Ah. Charging seconds (charger AC
#    > 2 A) end a run.
if 9 in PHASES:
    import gzip
    ser = json.load(gzip.open(OUT1S, "rt"))
    tr = json.load(open(ART + "bms_soc_learning_transitions.json"))
    pk = {r["s"]: r["pack"] for r in tr["sessions"]}
    print("\nphase9: discharges starting at an indicated 100.00 %")
    print("  date (UTC)        pack        session                                  held Ah  held min | Ah/%% 100->90  100->80 | to end: dSoC  Ah/%% excl. held  incl. held")
    out = []
    for s_, d in sorted(ser.items(), key=lambda x: min((int(t) for t in x[1]["bms_soc_hires"]), default=0)):
        p = pk.get(s_)
        sc, ib, ac = d["bms_soc_hires"], d["bcm_ibat"], d["BELINV_chargerInputCurrent"]
        ts = sorted(int(t) for t in sc)
        if not p or not ts:
            continue
        i = 0
        while i < len(ts):
            t = ts[i]
            if sc[str(t)] < 99.99:
                i += 1
                continue
            # at 100: walk forward while not charging; run ends at charging, a gap > 5 s, or session end
            held, hsec, ah, t_leave, e90, e80 = 0.0, 0, 0.0, None, None, None
            j, prev = i, t
            while j < len(ts):
                tj = ts[j]
                if tj - prev > 5 or (ac.get(str(tj)) or 0) > 2:
                    break
                x = ib.get(str(tj), 0)
                ah += x / 3600  # net: regen and generator charge included
                v = sc[str(tj)]
                if t_leave is None:
                    if v >= 99.99:
                        held += x / 3600
                        hsec += x < -0.5
                    else:
                        t_leave, ah_leave = tj, ah
                elif e90 is None and v <= 90:
                    e90 = (ah - ah_leave) / -10
                elif e80 is None and v <= 80:
                    e80 = (ah - ah_leave) / -20
                prev = tj
                j += 1
            end = sc[str(ts[j - 1])]
            if t_leave is not None and 100 - end >= 3:
                out.append((s_, p, t, held, hsec, e90, e80, 100 - end, (ah - ah_leave) / (end - 100), ah / (end - 100)))
                print("  %s  %-10s  %-40s %7.2f  %7.1f  | %7s   %7s  | %6.2f    %.3f            %.3f"
                      % (utc(t), p, s_[:40], -held, hsec / 60, "%.3f" % e90 if e90 else "-",
                         "%.3f" % e80 if e80 else "-", 100 - end, (ah - ah_leave) / (end - 100), ah / (end - 100)))
            elif t_leave is None and held < -0.5:
                print("  %s  %-10s  %-40s %7.2f  %7.1f  | never left 100 in this run" % (utc(t), p, s_[:40], -held, hsec / 60))
            i = max(j, i + 1)
    json.dump(out, open(ART + "bms_soc_learning_hold100.json", "w"))

    # 9b  every logged charge that reaches 100.00 %: Ah/% over the last 30 %
    #     before 100, net Ah into the pack after the display reached 100 (until
    #     charging stops), and vmax when it reached 100 and at the end.
    print("\n  charges that reach an indicated 100 %%: net Ah after the display hit 100")
    print("  reached 100 (UTC)  pack        session                                  Ah/%% 70->100  Ah after 100   min after 100")
    for s_, d in sorted(ser.items(), key=lambda x: min((int(t) for t in x[1]["bms_soc_hires"]), default=0)):
        p = pk.get(s_)
        sc, ib, ac = d["bms_soc_hires"], d["bcm_ibat"], d["BELINV_chargerInputCurrent"]
        ts = sorted(int(t) for t in sc)
        if not p or len(ts) < 60:
            continue
        hit = next((t for t in ts if sc[str(t)] >= 99.99 and (ac.get(str(t)) or 0) > 2), None)
        if hit is None or sc[str(ts[0])] >= 99.99:
            continue
        t70 = max((t for t in ts if t < hit and sc[str(t)] <= 70), default=None)
        r = None
        if t70:
            a = sum(ib.get(str(t), 0) for t in range(t70 + 1, hit + 1)) / 3600
            r = a / (100 - sc[str(t70)])
        a2, last = 0.0, hit
        for t in range(hit + 1, ts[-1] + 1):
            if (ac.get(str(t)) or 0) <= 2 and str(t) in ac:
                break
            a2 += ib.get(str(t), 0) / 3600
            last = t
        print("  %s   %-10s  %-40s %8s      %7.2f      %7.1f" % (utc(hit), p, s_[:40],
              "%.3f" % r if r else "-", a2, (last - hit) / 60))


# 10 (step 3) timeline per pack, to see when corrections happen (user,
#    2026-10-10: after a rest, when the BMS can score on cell voltage? or only
#    at the low end, once cells leave the LFP plateau?). Per session: start /
#    end / lowest SoC; excess charged after the display reached 100 (9b); Ah
#    held at 100 on discharge (9a); wake corrections (step 3 json); in-session
#    SoC moves not explained by Ah (startup frames excluded); and for sessions
#    that reach < 40 %: 1 s MIN(bcm_cell_vmin) (< 3.8, bounded per session,
#    cached in bms_soc_learning_vmin1s.json.gz), the vmin at the indicated
#    30 / 25 / 20 % crossings with the current at that second, and the Ah/%
#    per 5 % band below 40 % (does the count bend while the weak cell leaves
#    the plateau?).
VM1S = ART + "bms_soc_learning_vmin1s.json.gz"
if 10 in PHASES:
    import gzip
    ser = json.load(gzip.open(OUT1S, "rt"))
    tr = json.load(open(ART + "bms_soc_learning_transitions.json"))
    inv = json.load(open(INV))
    s3 = {r["b"]: r for r in json.load(open(ART + "bms_soc_learning_step3.json"))}
    sess = sorted([r for r in tr["sessions"] if r["pack"] and r["s"] in ser], key=lambda r: r["t0"])
    vm = json.load(gzip.open(VM1S, "rt")) if os.path.exists(VM1S) else {}
    low = [r for r in sess if ser[r["s"]]["bms_soc_hires"] and
           min(ser[r["s"]]["bms_soc_hires"].values()) < 40 and r["s"] not in vm]
    for i, r in enumerate(low):
        w0, w1 = inv[r["s"]]["w0"], inv[r["s"]]["w1"]
        _c, rows = influx("SELECT MIN(\"bcm_cell_vmin\") FROM signals WHERE vehicle='vtrux' AND "
                          "session='%s' AND bus='powertrain' AND time >= %ds AND time < %ds AND "
                          "\"bcm_cell_vmin\" < 3.8 GROUP BY time(1s) fill(none)" % (r["s"], w0, w1))
        vm[r["s"]] = {str(t // 1000): v for t, v in rows if v is not None}
        if i % 10 == 0:
            print("  vmin pull %d/%d" % (i, len(low)), flush=True)
    with gzip.open(VM1S, "wt") as fh:
        json.dump(vm, fh)

    def excess_after_100(d):
        sc, ib, ac = d["bms_soc_hires"], d["bcm_ibat"], d["BELINV_chargerInputCurrent"]
        ts = sorted(int(t) for t in sc)
        hit = next((t for t in ts if sc[str(t)] >= 99.99 and (ac.get(str(t)) or 0) > 2), None)
        if hit is None:
            return None
        a = 0.0
        for t in range(hit + 1, ts[-1] + 1):
            if str(t) in ac and (ac.get(str(t)) or 0) <= 2:
                break
            a += ib.get(str(t), 0) / 3600
        return a

    def held_at_100(d):
        sc, ib, ac = d["bms_soc_hires"], d["bcm_ibat"], d["BELINV_chargerInputCurrent"]
        ts = sorted(int(t) for t in sc)
        best = 0.0
        i = 0
        while i < len(ts):
            if sc[str(ts[i])] < 99.99:
                i += 1
                continue
            h, j, prev = 0.0, i, ts[i]
            while j < len(ts) and sc[str(ts[j])] >= 99.99 and ts[j] - prev <= 5:
                if (ac.get(str(ts[j])) or 0) > 2:
                    h = 0.0
                else:
                    h += ib.get(str(ts[j]), 0) / 3600
                prev = ts[j]
                j += 1
            if j < len(ts) and sc[str(ts[j])] < 99.99:
                best = min(best, h)
            i = j + 1
        return -best

    def in_session_steps(d, ahp):
        """SoC moves over 10 s windows not explained by Ah (|resid| >= 0.5 %), startup frames removed"""
        sc, ib = d["bms_soc_hires"], d["bcm_ibat"]
        ts = sorted(int(t) for t in sc)
        out = []
        k = 0
        while k + 10 < len(ts):
            a, b = ts[k], ts[k + 10]
            if b - a > 12:
                k += 1
                continue
            vals = [sc[str(t)] for t in ts[k:k + 11]]
            ds = vals[-1] - vals[0]
            ah = sum(ib.get(str(t), 0) for t in range(a + 1, b + 1)) / 3600
            res = ds - ah / ahp
            spike = any(0.6 < v / max(vals[0], vals[-1], 1e-6) < 0.95 for v in vals[1:-1])
            if abs(res) >= 0.5 and not spike:
                out.append((a, vals[0], vals[-1], res))
                k += 10
            else:
                k += 1
        return out

    def low_end(s_):
        d, v = ser[s_], vm.get(s_)
        if not v:
            return None
        sc, ib = d["bms_soc_hires"], d["bcm_ibat"]
        ts = sorted(int(t) for t in sc if t in v)
        out = {}
        for edge in (30, 25, 20):
            t = next((t for t in ts if sc[str(t)] <= edge), None)
            if t:
                out[edge] = (v[str(t)], ib.get(str(t)))
        mv = min(v.values()) if v else None
        bands = {}
        for lo in (35, 30, 25, 20, 15):
            hi = lo + 5
            th = next((t for t in ts if sc[str(t)] <= hi), None)
            tl = next((t for t in ts if sc[str(t)] <= lo), None)
            if th and tl and tl > th:
                ah = sum(ib.get(str(t), 0) for t in range(th + 1, tl + 1)) / 3600
                bands[lo] = -ah / 5
        return out, mv, bands

    AHP = {"main-orig": 0.486, "parts-orig": 0.464}
    f = lambda x, fmt: (fmt % x) if x is not None else "-"
    for pk_ in ("parts-orig", "main-orig"):
        print("\n===== timeline %s =====" % pk_)
        print("  start (UTC)       soc0 -> soc1 (min)        | events")
        for r in sess:
            if r["pack"] != pk_:
                continue
            d = ser[r["s"]]
            sc = d["bms_soc_hires"]
            if not sc:
                continue
            ts = sorted(int(t) for t in sc)
            ev = []
            w = s3.get(r["s"])
            if w and abs(w["corr"]) >= 0.3:
                ev.append("WAKE-CORR %+.2f (rest %.1f h, set vmin %s)" % (
                    w["corr"], w["rest_h"], f((w["set_wake"] or {}).get("vmin"), "%.3f")))
            if w and abs(w["wake"]["first"] - w["end"]["soc"]) >= 1 and w["cls"] != "clean-up":
                ev.append("GAP %+.2f vs prev end (rest %.1f h)" % (w["wake"]["first"] - w["end"]["soc"], w["rest_h"]))
            ex = excess_after_100(d)
            if ex is not None and ex >= 1:
                ev.append("EXCESS +%.2f Ah after display 100" % ex)
            h = held_at_100(d)
            if h >= 1:
                ev.append("HELD %.2f Ah at 100" % h)
            for a, v0, v1, res in in_session_steps(d, AHP[pk_]):
                ev.append("STEP %s %.2f->%.2f (resid %+.2f)" % (utc(a)[11:], v0, v1, res))
            le = low_end(r["s"])
            if le:
                cr, mv, bands = le
                ev.append("LOW vmin@30/25/20: %s | min vmin %.3f | Ah/%% 40..15 by 5: %s" % (
                    " ".join("%d:%.3f(%+.0fA)" % (e, cr[e][0], cr[e][1] or 0) for e in cr),
                    mv, " ".join("%d:%.3f" % (lo, bands[lo]) for lo in sorted(bands, reverse=True))))
            if ev or min(sc.values()) < 30:
                print("  %s  %6.2f -> %6.2f (%6.2f) %s %s" % (
                    utc(ts[0]), sc[str(ts[0])], sc[str(ts[-1])], min(sc.values()),
                    "RIG" if r["rig"] else "   ", r["s"][:38]))
                for e in ev[:8]:
                    print("        " + e)


# 11 (step 3, user 2026-10-10: the 100 % hold "seems to be triggered by
#    leaving the truck charging for extended periods after it is full"; the
#    interposer spec notes the truck's own hold puts +0.85 to +2.55 A into the
#    pack for the first hour with bcm_chg_max at 0). Per logged charge that
#    reaches an indicated 100 %: integrate bcm_ibat from the first 100.00 %
#    second until the charge ends -- the first of: 30 s of ibat < -3 A (driving
#    away), a gap > 60 s, or the session end. Charger AC is NOT used to end it
#    (9b stopped at AC <= 2 A, i.e. at the Low Power hold, and missed it).
#    Report net and positive-only Ah, duration, mean ibat in the first 60 min
#    and after, and the Ah held at 100 on the next discharge in the same
#    session. Cell vmax at the end of the session comes from the phase 7
#    end window.
if 11 in PHASES:
    import gzip
    ser = json.load(gzip.open(OUT1S, "rt"))
    tr = json.load(open(ART + "bms_soc_learning_transitions.json"))
    we = json.load(open(WE))
    pk = {r["s"]: r["pack"] for r in tr["sessions"]}
    print("\nphase11: Ah into the pack after the display reached 100 %, to the end of charge")
    print("  reached 100 (UTC)  pack        session                                   dur min | net Ah  pos Ah | mean A 1st h  after | held next | vmax end")
    rows = []
    for s_, d in sorted(ser.items(), key=lambda x: min((int(t) for t in x[1]["bms_soc_hires"]), default=0)):
        p = pk.get(s_)
        sc, ib, ac = d["bms_soc_hires"], d["bcm_ibat"], d["BELINV_chargerInputCurrent"]
        ts = sorted(int(t) for t in sc)
        if not p or len(ts) < 60:
            continue
        hit = next((t for t in ts if sc[str(t)] >= 99.99 and (ac.get(str(t)) or 0) > 2), None)
        if hit is None:
            continue
        net = pos = 0.0
        h1, h2 = [], []
        neg_run, prev, end = 0, hit, hit
        for t in range(hit, ts[-1] + 1):
            if str(t) not in ib:
                if t - prev > 60:
                    break
                continue
            x = ib[str(t)]
            neg_run = neg_run + 1 if x < -3 else 0
            if neg_run >= 30:
                end = t - 30
                break
            net += x / 3600
            pos += max(x, 0) / 3600
            (h1 if t - hit < 3600 else h2).append(x)
            prev = end = t
        # held on the next discharge in this session
        held = 0.0
        j = [t for t in ts if t > end]
        for t in j:
            if sc[str(t)] < 99.99:
                break
            held += ib.get(str(t), 0) / 3600
        vx = [v for _t, v in sorted(we.get(s_, {}).get("end:bcm_cell_vmax", []))]
        rows.append((s_, p, hit, end, net, pos, held))
        print("  %s   %-10s  %-40s %7.0f  | %6.2f  %6.2f | %6.2f     %6s | %8s | %s"
              % (utc(hit), p, s_[:40], (end - hit) / 60, net, pos,
                 st.mean(h1) if h1 else float("nan"), "%.2f" % st.mean(h2) if h2 else "-",
                 "%.2f" % -held if j and held < -0.05 else "-",
                 "%.3f" % vx[-1] if vx else "-"))
    json.dump(rows, open(ART + "bms_soc_learning_hold_charge.json", "w"))


# 12 (step 3) SoC rises with the odometer unchanged, re-attributed with the
#    user's end-of-charge rules (2026-10-10): a Coda charge ends abruptly
#    (minute averages straight to ~0) and is followed by ~4-min top-ups at
#    ~6.9 kW every ~90 min; a Vtrux charge tapers and then holds at ~550 W
#    (350-1,400 W). An abrupt end with no top-up after it is ambiguous (Coda,
#    or a Vtrux unplugged in bulk). > 7.3 kW is the 914. Needed Ah = dSoC x
#    the pack's Ah/% + the Ah held at 100 % at the start of session B. Vtrux
#    supply = (kWh of the block above 1,400 W) x 0.795 wall-to-pack / 0.37 kV
#    (charger-efficiency note, 32 A; rough, +/-15 %); hold minutes deliver ~0.
if 12 in PHASES:
    import gzip
    ser = json.load(gzip.open(OUT1S, "rt"))
    tr = json.load(open(ART + "bms_soc_learning_transitions.json"))
    sess = {r["s"]: r for r in tr["sessions"]}
    AHP = {"main-orig": 0.486, "parts-orig": 0.464}

    def held_start(s_):
        d = ser.get(s_)
        if not d:
            return 0.0
        sc, ib = d["bms_soc_hires"], d["bcm_ibat"]
        ts = sorted(int(t) for t in sc)
        su = startup_step(sc)
        h = 0.0
        for t in ts:
            v = sc[str(t)]
            if su and abs(v - su[1]) < 1e-6:
                continue
            if v < 99.99:
                break
            h += ib.get(str(t), 0) / 3600
        return max(-h, 0.0)

    def blocks_of(g0, g1):
        rows = ha("SELECT value FROM \"W\" WHERE entity_id='%s' AND time >= %ds AND time < %ds"
                  % (CT, g0 - 3600, g1 + 600))
        mins, k, val = [], 0, 0.0
        for m in range(g0, g1 + 600, 60):
            while k < len(rows) and rows[k][0] <= m:
                val = rows[k][1]
                k += 1
            mins.append((m, val or 0.0))
        out, cur = [], None
        for m, v in mins:
            if v > 300:
                if cur is None:
                    cur = []
                cur.append((m, v))
            elif cur is not None:
                out.append(cur)
                cur = None
        if cur:
            out.append(cur)
        res = []
        for i, b in enumerate(out):
            vs = [v for _m, v in b]
            bulk = [v for v in vs if v > 1400]
            hold = sum(1 for v in vs if 350 <= v <= 1400)
            p90 = sorted(vs)[int(0.9 * (len(vs) - 1))]
            dur = len(b)
            tail = vs[-6:]
            abrupt = bool(bulk) and vs[-1] > 5000 or (len(vs) >= 2 and vs[-2] > 5000)
            taper = bool(bulk) and any(1400 < v < 5000 for v in tail) and not abrupt
            nxt = out[i + 1] if i + 1 < len(out) else None
            topup_after = nxt is not None and len(nxt) <= 8 and max(v for _m, v in nxt) > 5000 and \
                nxt[0][0] - b[-1][0] < 3 * 3600
            if dur <= 8 and max(vs) > 5000:
                who = "top-up (Coda)"
            elif p90 > 7300:
                who = "914"
            elif hold >= 25 and bulk:
                who = "VTRUX (hold)"
            elif taper:
                who = "VTRUX (taper)"
            elif abrupt and topup_after:
                who = "Coda (abrupt + top-ups)"
            elif abrupt:
                who = "ambiguous (abrupt, no top-up)"
            else:
                who = "unknown"
            res.append({"t0": b[0][0], "t1": b[-1][0] + 60, "kwh": sum(vs) / 60000,
                        "bulk_kwh": sum(bulk) / 60000, "hold_min": hold, "who": who})
        return res

    print("\nphase12: odometer-unchanged SoC rises vs Vtrux-attributable home charging")
    for t in tr["transitions"]:
        if t["cls"] != "clean-up" or not t["pack_b"]:
            continue
        a, b = sess[t["a"]], sess[t["b"]]
        g0, g1 = int(a["t1"]), int(b["t0"])
        need_soc = t["dsoc"] * AHP[t["pack_b"]]
        held = held_start(t["b"])
        need = need_soc + held
        print("\n  %s -> %s  %-10s gap %.1f h  SoC %.2f -> %.2f  need %.1f Ah (+%.1f held at 100 on B) = %.1f Ah"
              % (utc(g0), utc(g1), t["pack_b"], t["gap_h"], t["soc_a"], t["soc_b"], need_soc, held, need))
        if g0 < CT_START if False else g0 < 1764460800:
            print("      no CT (before 2025-11-30)")
            continue
        sup = 0.0
        amb = 0.0
        for bl in blocks_of(g0, g1):
            ah = bl["bulk_kwh"] * 0.795 / 0.37
            if bl["who"].startswith("VTRUX"):
                sup += ah
            elif bl["who"].startswith("ambiguous"):
                amb += ah
            print("      %s .. %s  %6.2f kWh (bulk %5.2f)  hold %3d min  -> %-30s %s"
                  % (utc(bl["t0"]), utc(bl["t1"])[11:], bl["kwh"], bl["bulk_kwh"], bl["hold_min"],
                     bl["who"], "~%.1f Ah" % ah if bl["bulk_kwh"] else ""))
        print("      Vtrux-attributable ~%.1f Ah, ambiguous ~%.1f Ah  vs needed %.1f Ah  -> shortfall %.1f Ah (%.0f %% of SoC)"
              % (sup, amb, need, need - sup - amb, (need - sup - amb) / AHP[t["pack_b"]]))


# 13 (step 4) usable capacity, the low end after holds, and the origin of E.
#    No queries; caches only.
#    a  per-pack merged 1 s timeline: every session's bcm_ibat and
#       bms_soc_hires on one clock (overlapping loggers counted once).
#       Startup frames are removed by a general rule: a run of one value
#       lasting <= 3 s whose ratio to the largest of the next 5 values is
#       0.6-0.95 (catches session-start and mid-session power-ons and the
#       end-of-hold blips). Gaps inside a session <= 5 s are filled with the
#       previous current; longer ones with dSoC x Ah/% ("filled"; fills
#       > 1 Ah are listed). Between sessions the chain BREAKS if the odometer
#       moved or SoC rose > 1 %; otherwise the gap is a rest with 0 Ah and an
#       SoC change across it is listed as a rest jump.
#    b  ledger from each logged full charge (phase 11 rows, the charge end):
#       cumulative net Ah; E_full = displayed - (100 + cumAh / Ah-per-%).
#       NB this is referenced to the top, not to empty.
#    c  low end: per session below 40 %, the weakest cell per 5 % band,
#       fitted vmin = V0 + R * I over discharge seconds (-200 < I < -10 A);
#       and the median of vmin + R_pack * |I|, R_pack = the pack's median R
#       over bands >= 40 %.
#    d  charges starting below 50 %: Ah to the end of charge.
#    e  startup frames taken while the display reads >= 99.9 %: internal =
#       frame / k (k = the pack's median startup ratio), against the Ah that
#       went in after the display reached 100 and the Ah held on the next
#       discharge.
#    f  ledger anchored at EMPTY: from the 2026-03-04 cut (weak cell empty,
#       BMS opened the contactor at an indicated 17.30 %), forward through the
#       next full charge. cumAh at the full charge = Ah from weak-cell empty to
#       full, if the chain is unbroken.
if 13 in PHASES:
    import gzip
    ser = json.load(gzip.open(OUT1S, "rt"))
    vm = json.load(gzip.open(VM1S, "rt"))
    we = json.load(open(WE))
    tr = json.load(open(ART + "bms_soc_learning_transitions.json"))
    hc = json.load(open(ART + "bms_soc_learning_hold_charge.json"))
    AHP = {"main-orig": 0.486, "parts-orig": 0.464}
    KP = {"main-orig": 0.8257, "parts-orig": 0.7885}
    sess = sorted([r for r in tr["sessions"] if r["pack"] and r["s"] in ser and
                   ser[r["s"]]["bms_soc_hires"]], key=lambda r: r["t0"])
    owner = {r["s"]: r for r in sess}
    f = lambda x, fmt: (fmt % x) if x is not None else "-"
    FRAMES = []

    def clean_soc(sc, s_=None):
        ts = sorted(int(t) for t in sc)
        v = [sc[str(t)] for t in ts]
        runs, i = [], 0
        while i < len(ts):
            j = i
            while j + 1 < len(ts) and v[j + 1] == v[i] and ts[j + 1] - ts[j] <= 2:
                j += 1
            runs.append((i, j))
            i = j + 1
        drop = set()
        for a, b in runs:
            if ts[b] - ts[a] > 3:
                continue
            nxt = [x for x, t in zip(v[b + 1:b + 6], ts[b + 1:b + 6]) if t - ts[b] <= 10]
            if not nxt or v[a] <= 1:
                continue
            w = max(nxt)
            if 0.6 < v[a] / w < 0.95:
                drop.update(ts[a:b + 1])
                prev = v[a - 1] if a > 0 and ts[a] - ts[a - 1] <= 10 else None
                if s_:
                    FRAMES.append((s_, ts[a], v[a], prev, w))
        return {t: x for t, x in zip(ts, v) if t not in drop}

    M, CS = {}, {}
    for r in sess:
        p, d = r["pack"], ser[r["s"]]
        sc = clean_soc(d["bms_soc_hires"], r["s"])
        CS[r["s"]] = sc
        ib = {int(t): x for t, x in d["bcm_ibat"].items() if x is not None}
        ac = {int(t): x for t, x in d["BELINV_chargerInputCurrent"].items() if x is not None}
        m = M.setdefault(p, {})
        last = None
        for t in sorted(set(sc) | set(ib)):
            if t in sc:
                last = sc[t]
            if t in m or last is None:
                continue
            m[t] = (ib.get(t), last, r["s"], ac.get(t, 0))

    def chain_break(sa, sb, soc_a, soc_b):
        a, b = owner[sa], owner[sb]
        if a["odo1"] is not None and b["odo0"] is not None and b["odo0"] - a["odo1"] >= 1:
            return "odometer +%d km" % (b["odo0"] - a["odo1"])
        if soc_b - soc_a > 1:
            return "SoC rose %.2f -> %.2f off-log" % (soc_a, soc_b)
        return None

    def ledger(p, t_start, ref, stop_at_full=True, t_stop=None):
        """walk the merged timeline from t_start; ref = the true SoC (% of the
        BMS scale) at t_start. Returns rows and why it stopped."""
        m, ahp = M[p], AHP[p]
        ts = sorted(t for t in m if t >= t_start and (t_stop is None or t <= t_stop))
        cum, filled, prev, rows, why = 0.0, 0.0, None, [], "end of data"
        left100, edges, ei, lowv = None, [50, 45, 40, 35, 30, 25, 20, 15], 0, (9, None, None)
        imp = lambda c: ref + c / ahp
        for t in ts:
            ib_, soc, sn, ac_ = m[t]
            if prev is not None:
                pib, psoc, psn, pac = m[prev]
                gap = t - prev
                if sn != psn:
                    rows.append(("end", prev, psoc, cum, psn))
                    br = chain_break(psn, sn, psoc, soc)
                    if br:
                        why = "break: " + br
                        break
                    if abs(soc - psoc) >= 0.3:
                        rows.append(("rest-jump", t, soc, cum, "%+.2f across a %.1f h rest" % (soc - psoc, gap / 3600)))
                elif gap > 5:
                    fa = (soc - psoc) * ahp
                    filled += fa
                    cum += fa
                    if abs(fa) > 1:
                        rows.append(("fill", t, soc, cum, "%+.2f Ah filled over a %d s gap" % (fa, gap)))
                elif pib is not None:
                    cum += pib * (gap - 1) / 3600
            if stop_at_full and ac_ and ac_ > 2 and soc >= 99.99 and t > t_start + 60 and \
                    (prev is None or m[prev][1] < 99.99):
                rows.append(("FULL", t, soc, cum, "display reached 100 on charge (%s)" % sn))
                why = "reached 100 on charge"
                break
            if ib_ is not None:
                cum += ib_ / 3600
            if left100 is None and soc < 99.99:
                left100 = (t, cum)
            while ei < len(edges) and soc <= edges[ei]:
                v = vm.get(sn, {}).get(str(t))
                rows.append(("edge", t, soc, cum, "%d%% vmin %s at %+.0f A" % (edges[ei], f(v, "%.3f"), ib_ or 0)))
                ei += 1
            v = vm.get(sn, {}).get(str(t))
            if v is not None and v < lowv[0]:
                lowv = (v, t, soc)
            prev = t
        else:
            if prev is not None:
                rows.append(("end", prev, m[prev][1], cum, m[prev][2]))
        return {"rows": rows, "why": why, "left100": left100, "lowv": lowv, "filled": filled, "imp": imp}

    def show(L, p, label, ref_name):
        print("\n  %s -> %s" % (label, L["why"]))
        if L["left100"] and L["left100"][1] < -0.05:
            print("      display left 100 at %s after %.2f Ah net" % (utc(L["left100"][0]), -L["left100"][1]))
        for kind, t, soc, c, note in L["rows"]:
            print("      %-9s %s  disp %6.2f  cumAh %+7.2f  %s %6.2f  E %+6.2f  %s"
                  % (kind, utc(t), soc, c, ref_name, L["imp"](c), soc - L["imp"](c), note[:46]))
        if L["filled"]:
            print("      (filled across in-session gaps from dSoC: %+.2f Ah in total)" % L["filled"])
        if L["lowv"][1]:
            print("      lowest weakest-cell %.3f V at disp %.2f (%s)" % (L["lowv"][0], L["lowv"][2], utc(L["lowv"][1])))

    # b
    print("\nphase13b: ledger from each logged full charge (implied = 100 + cumAh / Ah-per-%; E = displayed - implied, top-referenced)")
    ledgers = []
    for s_, p, hit, end, net, pos, held in hc:
        if p not in M:
            continue
        L = ledger(p, end, 100.0)
        L.update({"s": s_, "p": p, "end": end, "held_charge": net})
        ledgers.append(L)
        lows = [r[2] for r in L["rows"] if r[0] in ("end", "edge")]
        if not lows or min(lows) > 90:
            continue
        show(L, p, "FULL %s  %-10s %-34s (Ah in after display 100: %.2f)" % (utc(end), p, s_[:34], net), "implied")

    # e
    print("\nphase13e: startup frames taken while the display read >= 99.9 %")
    print("  time (UTC)        pack        session                                  frame   next  | internal %  over 100 Ah | Ah in after 100 (same session) | held next drive")
    hcs = {h[0]: h for h in hc}
    for s_, t, v, prev, w in sorted(FRAMES, key=lambda x: x[1]):
        p = owner[s_]["pack"]
        if w < 99.9:
            continue
        internal = v / KP[p]
        h = hcs.get(s_)
        sc = CS[s_]
        held, after = 0.0, sorted(x for x in sc if x > t)
        ib = ser[s_]["bcm_ibat"]
        for x in after:
            if sc[x] < 99.99:
                break
            held += (ib.get(str(x)) or 0) / 3600
        print("  %s  %-10s  %-40s %6.2f  %6.2f | %8.2f   %+7.2f     | %8s | %+.2f"
              % (utc(t), p, s_[:40], v, w, internal, (internal - 100) * AHP[p],
                 f(h[4] if h and h[3] <= t + 600 else None, "%.2f"), -held))
    print("  (k used: %s; k scatter within a pack is ~0.1 %%, i.e. ~0.15 internal %% at 100)" % KP)
    print("\n  all startup frames: internal (frame/k) minus displayed next value, by displayed band")
    bands = {}
    for s_, t, v, prev, w in FRAMES:
        p = owner[s_]["pack"]
        bands.setdefault((p, min(int(w // 10) * 10, 90) if w < 99.9 else 100), []).append(v / KP[p] - w)
    for k_ in sorted(bands):
        x = bands[k_]
        print("    %-10s %3d%%: n=%3d  median %+.2f  range %+.2f .. %+.2f" % (k_[0], k_[1], len(x), st.median(x), min(x), max(x)))

    # f
    print("\nphase13f: ledger anchored at EMPTY (2026-03-04 BMS cut, weak cell empty; true = 0 + cumAh / 0.464)")
    cut = None
    for t in sorted(t for t, x in M["parts-orig"].items() if x[2] == "vtruxexporttest"):
        ib_ = M["parts-orig"][t][0]
        if ib_ is not None and abs(ib_ + 1.725) < 0.01:
            cut = t
            break
    print("  cut (first second of the frozen -1.725 A): %s" % (utc(cut) if cut else "not found"))
    if cut:
        L = ledger("parts-orig", cut + 1, 0.0, stop_at_full=False, t_stop=cut + 4 * 86400)
        show(L, "parts-orig", "EMPTY %s parts-orig vtruxexporttest" % utc(cut), "true")
        json.dump(L["rows"], open(ART + "bms_soc_learning_ledger_empty.json", "w"))

    # c
    def fit(xy):
        if len(xy) < 20:
            return None
        xs, ys = [x for x, _ in xy], [y for _, y in xy]
        if max(xs) - min(xs) < 30:
            return None
        mx, my = st.mean(xs), st.mean(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        b = sum((x - mx) * (y - my) for x, y in xy) / sxx
        return my - b * mx, b
    Rp, per = {}, []
    for r in sess:
        s_ = r["s"]
        if s_ not in vm:
            continue
        sc, v, ib = CS[s_], vm[s_], ser[s_]["bcm_ibat"]
        band = {}
        for t, soc in sc.items():
            x, y = ib.get(str(t)), v.get(str(t))
            if x is None or y is None or not (-200 < x < -10):
                continue
            lo = int(soc // 5) * 5
            if 10 <= lo <= 65:
                band.setdefault(lo, []).append((x, y))
        fits = {lo: fit(xy) for lo, xy in band.items()}
        pl = [fb[1] for lo, fb in fits.items() if fb and lo >= 40 and fb[1] > 0]
        if pl:
            Rp.setdefault(r["pack"], []).append(st.median(pl))
        per.append((r, band, fits))
    Rmed = {p: st.median(x) for p, x in Rp.items()}
    print("\nphase13c: weakest cell at the low end, load-corrected")
    print("  pack median R over bands >= 40 %% (V per A of pack current): %s"
          % ", ".join("%s %.5f (n=%d)" % (p, Rmed[p], len(Rp[p])) for p in Rmed))
    print("  per indicated band: V0 = fitted no-load vmin [R mV/A] | med = median(vmin + R_pack*|I|) [median I]")
    for r, band, fits in per:
        R = Rmed.get(r["pack"], 0.0008)
        cells = []
        for lo in sorted(band, reverse=True):
            if lo > 45:
                continue
            xy = band[lo]
            fb = fits.get(lo)
            cells.append("%2d: %-18s med %.3f [%4.0fA, n=%d]" % (
                lo, ("V0 %.3f[%.2f]" % (fb[0], fb[1] * 1000)) if fb else "V0 -",
                st.median(y - R * x for x, y in xy), st.median(x for x, _ in xy), len(xy)))
        if not cells:
            continue
        prior = [L for L in ledgers if L["p"] == r["pack"] and L["end"] < r["t0"]]
        pr = max(prior, key=lambda L: L["end"]) if prior else None
        ctx = "no logged full charge before"
        if pr:
            inside = [x for x in pr["rows"] if r["t0"] <= x[1] <= r["t1"]]
            ctx = "last logged FULL %s (Ah in after 100: %.1f); %s" % (
                utc(pr["end"])[:10], pr["held_charge"],
                "chain reaches here: E_top %+.1f" % (inside[-1][2] - pr["imp"](inside[-1][3])) if inside else "chain broken before here")
        print("\n  %s %-10s %-36s %s" % (utc(r["t0"]), r["pack"], r["s"][:36], ctx))
        for c in cells:
            print("      " + c)

    # d
    print("\nphase13d: charges starting below 50 %: Ah to the end of charge")
    print("  start (UTC)       pack        session                              soc0 -> soc1   net Ah  Ah/%%  | Ah after 100 | vmin start  vmax end")
    for r in sess:
        d = ser[r["s"]]
        sc = CS[r["s"]]
        ib, ac = d["bcm_ibat"], d["BELINV_chargerInputCurrent"]
        ts = sorted(sc)
        chg = [t for t in ts if (ac.get(str(t)) or 0) > 2]
        if not chg or sc[chg[0]] >= 50:
            continue
        t0, s0 = chg[0], sc[chg[0]]
        hrow = hcs.get(r["s"])
        t1 = hrow[3] if hrow else chg[-1]
        s1 = sc[max(t for t in ts if t <= t1)]
        ah = sum(ib.get(str(t), 0) or 0 for t in range(t0, t1 + 1)) / 3600
        vs = [x for _t, x in sorted(we.get(r["s"], {}).get("wake:bcm_cell_vmin", [])) if x < 3.8]
        vx = [x for _t, x in sorted(we.get(r["s"], {}).get("end:bcm_cell_vmax", [])) if x < 3.8]
        print("  %s  %-10s  %-36s %6.2f -> %6.2f  %6.2f  %.3f | %12s | %s  %s"
              % (utc(t0), r["pack"], r["s"][:36], s0, s1, ah, ah / (s1 - s0) if s1 > s0 else float("nan"),
                 f(hrow[4] if hrow else None, "%.2f"), f(vs[0] if vs else None, "%.3f"), f(vx[-1] if vx else None, "%.3f")))


# 14 (step 4) what the BMS itself does at the ends: 0x420 bcm_dis_max /
#    bcm_chg_max (MEAN per 10 s) and bcm_cell_undervolt / overvolt (MAX per
#    10 s), plus 0x430 MIN vmin / MAX vmax (< 3.8, per 10 s), for chosen
#    sessions, each bounded by its session window. Printed where a limit moves
#    by >= 5 A or a flag changes, with SoC and pack current from the 1 s cache.
#    Cached to bms_soc_learning_limits.json.
LIM = ART + "bms_soc_learning_limits.json"
if 14 in PHASES:
    import gzip
    ser = json.load(gzip.open(OUT1S, "rt"))
    inv = json.load(open(INV))
    PICK = ["vtruxexporttest", "vtruxanotherevaplogpart4-batteryonly", "vtrux_20260617_193900",
            "vtruxchargeblueevse", "vtrux_20260912_192748", "vtrux_20260816_111915",
            "partsdrive_20260802", "vtrux_20260513_174225",  # parts-truck session re-tagged 2026-10-21; cached JSONs keep the old name
            "charge_M0", "vtrux_20260714_161319", "another_M0", "vtrux_20260503_192242"]
    lim = json.load(open(LIM)) if os.path.exists(LIM) else {}
    for s_ in PICK:
        if s_ in lim:
            continue
        w0, w1 = inv[s_]["w0"], inv[s_]["w1"]
        base = ("FROM signals WHERE vehicle='vtrux' AND session='%s' AND bus='powertrain' AND "
                "time >= %ds AND time < %ds" % (s_, w0, w1))
        _c, a = influx("SELECT MEAN(\"bcm_dis_max\"), MEAN(\"bcm_chg_max\"), MAX(\"bcm_cell_undervolt\"), "
                       "MAX(\"bcm_cell_overvolt\") %s GROUP BY time(10s) fill(none)" % base)
        _c, b = influx("SELECT MIN(\"bcm_cell_vmin\"), MAX(\"bcm_cell_vmax\") %s AND \"bcm_cell_vmin\" < 3.8 "
                       "AND \"bcm_cell_vmax\" < 3.8 GROUP BY time(10s) fill(none)" % base)
        lim[s_] = {"lim": a, "v": b}
        print("  pulled %s: %d / %d rows" % (s_, len(a), len(b)), flush=True)
    json.dump(lim, open(LIM, "w"))
    print("\nphase14: BMS limits and flags at the ends (10 s bins; printed on change)")
    for s_ in PICK:
        d = ser.get(s_, {})
        sc, ib = d.get("bms_soc_hires", {}), d.get("bcm_ibat", {})
        vv = {r[0] // 1000: r[1:] for r in lim[s_]["v"]}
        print("\n  %s" % s_)
        print("    time (UTC)           SoC     ibat(10s mean) | dis_max chg_max  UV OV | vmin  vmax")
        last = None
        for t, dm, cm, uv, ov in lim[s_]["lim"]:
            t //= 1000
            if dm is None:
                continue
            key = (dm, cm, uv, ov)
            if last is None or abs(dm - last[0]) >= 5 or abs((cm or 0) - (last[1] or 0)) >= 5 or uv != last[2] or ov != last[3]:
                socs = [sc[str(x)] for x in range(t, t + 10) if str(x) in sc]
                ibs = [ib[str(x)] for x in range(t, t + 10) if str(x) in ib and ib[str(x)] is not None]
                v = vv.get(t, (None, None))
                print("    %s  %6s  %7s        | %6.1f  %6.1f   %s  %s  | %s  %s"
                      % (utc(t) + ":%02d" % (t % 60), "%.2f" % socs[-1] if socs else "-",
                         "%+.1f" % st.mean(ibs) if ibs else "-", dm, cm or 0, int(uv or 0), int(ov or 0),
                         "%.3f" % v[0] if v[0] else "-", "%.3f" % v[1] if v[1] else "-"))
                last = key

# 13g (step 4) largest unbroken Ah swing per pack: walk each pack's merged
#    timeline (same chain rules as 13a); within each unbroken chain, the
#    largest drop of cumulative net Ah from a running maximum (discharge
#    swing) and the largest rise from a running minimum (charge swing).
if 13 in PHASES:
    print("\nphase13g: largest unbroken Ah swings per pack (lower bounds on usable Ah)")
    for p, m in M.items():
        ts = sorted(m)
        best_d, best_c = (0, None), (0, None)
        cum, hi, lo, prev = 0.0, (0.0, ts[0], m[ts[0]][1]), (0.0, ts[0], m[ts[0]][1]), None
        for t in ts:
            ib_, soc, sn, ac_ = m[t]
            if prev is not None:
                pib, psoc, psn, pac = m[prev]
                if sn != psn and chain_break(psn, sn, psoc, soc):
                    cum, hi, lo = 0.0, (0.0, t, soc), (0.0, t, soc)
                elif sn == psn and t - prev > 5:
                    cum += (soc - psoc) * AHP[p]
                elif sn == psn and pib is not None:
                    cum += pib * (t - prev - 1) / 3600
            if ib_ is not None:
                cum += ib_ / 3600
            if cum > hi[0]:
                hi = (cum, t, soc)
            if cum < lo[0]:
                lo = (cum, t, soc)
            if len(hi) == 3 and hi[0] - cum > best_d[0]:
                best_d = (hi[0] - cum, (hi[1], hi[2], t, soc))
            if len(lo) == 3 and cum - lo[0] > best_c[0]:
                best_c = (cum - lo[0], (lo[1], lo[2], t, soc))
            prev = t
        for name, (ah, w) in (("discharge", best_d), ("charge", best_c)):
            if w:
                print("  %-10s %-9s %5.1f Ah  %s (disp %.2f) -> %s (disp %.2f)  = %.1f %% of the BMS scale"
                      % (p, name, ah, utc(w[0]), w[1], utc(w[2]), w[3], 100 * ah / (AHP[p] * 100)))
