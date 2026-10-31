"""partstruck_top_of_charge.py -- the BMS's chg_max walk, the pack current and
the 12 V load at the parts truck's genuine top of charge
(vtrux_partstruck_charge), for the interposer tester's P3 stall question
(reviewer, 2026-10-10). Companion to partstruck_top_setpoint.py, which gives
the VCU's page-01 setpoint from the raw log.

Source: InfluxDB canbus-data, powertrain bus, bounded by the session's
upload_manifest window (tools/tools.md, the 2026-09-27 outage rule).
Forward-filled to a 1 s grid, then 30 s bins. Times are seconds from the
log's first frame (manifest t_start), the same base as the raw log.

Idc is BELINV_hvBatteryCurrent NEGATED (DBC sign backwards). bcm_ibat is +
when charging. P12 = DCDC_LV_Curr * DCDC_LV_Volt.
"""
import sys
sys.path.insert(0, ".")
import base64
import json
import urllib.parse
import urllib.request

SESSION = "vtrux_partstruck_charge"
FIELDS = ["bcm_chg_max", "bcm_ibat", "bcm_cell_vmax", "bcm_cell_vmin",
          "bcm_soc", "BELINV_hvBatteryCurrent", "BELINV_hvBatteryVoltage",
          "DCDC_LV_Curr", "DCDC_LV_Volt", "bcm_bal_count"]
REL0, REL1 = 4800, 6900
BIN = 30
OUT = "projects/vtrux/notes/artifacts/partstruck_top_of_charge.txt"


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
                if "error" in res:
                    raise RuntimeError(res["error"])
                for se in res.get("series", []):
                    cols = se["columns"]
                    rows.extend(se["values"])
    return cols, rows


def stored_window_ms():
    cols, rows = influx("SELECT uploaded_at, file, t_start_ns, t_end_ns FROM "
                        "upload_manifest WHERE \"vehicle\"='vtrux' AND "
                        "\"session\"='%s'" % SESSION)
    newest = {}
    for v in rows:
        r = dict(zip(cols, v))
        f, ua = r.get("file"), r.get("uploaded_at") or 0
        if f not in newest or ua > newest[f][0]:
            newest[f] = (ua, r)
    t0 = min(r["t_start_ns"] for _u, r in newest.values())
    t1 = max(r["t_end_ns"] for _u, r in newest.values())
    return t0 // 10**6, t1 // 10**6, sorted(newest)


def main():
    m0, m1, files = stored_window_ms()
    q0 = m0 + (REL0 - 60) * 1000
    q1 = min(m1, m0 + REL1 * 1000)
    have = set()
    cols, keys = influx("SHOW FIELD KEYS FROM signals")
    for v in keys:
        have.add(v[0])
    fields = [f for f in FIELDS if f in have]
    sel = ", ".join('"%s"' % f for f in fields)
    cols, rows = influx("SELECT %s FROM signals WHERE vehicle='vtrux' AND "
                        "session='%s' AND bus='powertrain' AND time >= %dms "
                        "AND time < %dms" % (sel, SESSION, q0, q1))
    rows.sort(key=lambda r: r[0])
    idx = {c: i for i, c in enumerate(cols)}
    cur = dict.fromkeys(fields)
    bins = {}
    k = 0
    for s in range(REL0 - 60, REL1):
        tms = m0 + s * 1000
        while k < len(rows) and rows[k][0] <= tms:
            for f in fields:
                v = rows[k][idx[f]]
                if v is not None:
                    cur[f] = v
            k += 1
        if s < REL0 or any(cur[f] is None for f in fields):
            continue
        b = bins.setdefault(s // BIN * BIN, {f: [] for f in fields})
        for f in fields:
            b[f].append(cur[f])
    out = []
    out.append("session %s, manifest files %s" % (SESSION, files))
    out.append("fields: %s" % fields)
    out.append("t_rel  chgmax(min/max)  ibat  Idc_rep  vmax   vmin   "
               "spread_mV  soc  P12_W  Vpack")
    for b0 in sorted(bins):
        g = bins[b0]
        mean = lambda f: sum(g[f]) / len(g[f])
        p12 = mean("DCDC_LV_Curr") * mean("DCDC_LV_Volt")
        out.append("%5d  %6.2f (%5.2f/%5.2f)  %5.2f  %5.2f  %.3f  %.3f  %5.0f  "
                   "%5.1f  %4.0f  %5.1f" % (
                       b0, mean("bcm_chg_max"), min(g["bcm_chg_max"]),
                       max(g["bcm_chg_max"]), mean("bcm_ibat"),
                       -mean("BELINV_hvBatteryCurrent"), mean("bcm_cell_vmax"),
                       mean("bcm_cell_vmin"),
                       1000 * (mean("bcm_cell_vmax") - mean("bcm_cell_vmin")),
                       mean("bcm_soc"), p12, mean("BELINV_hvBatteryVoltage")))
    text = "\n".join(out) + "\n"
    with open(OUT, "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__" and len(sys.argv) == 1:
    main()


# ---------------------------------------------------------------------------
# Phase 2 (added 2026-10-10): the same question on all four genuine tops of
# charge (evap_gate_evidence.txt: Low Power at SoC 100 %, chg_max 0 A). For
# each: when chg_max first fell to <= 3.0 A and stayed there, when it first
# read 0, and when the VCU commanded Low Power (chgcmd_mode 3, the last
# transition into it), with the pack current, the charger's reported DC, the
# cells and the 12 V load at each, and the charge that reached the pack
# (integral of bcm_ibat) from the <= 3.0 A point to the Low Power.
TOPS = ["charge_M0", "full-charge-then-fail", "vtrux_20260503_192242",
        "vtrux_partstruck_charge"]
F2 = ["bcm_chg_max", "bcm_ibat", "bcm_cell_vmax", "bcm_cell_vmin",
      "bms_soc_hires", "chgcmd_mode", "BELINV_hvBatteryCurrent",
      "DCDC_LV_Curr", "DCDC_LV_Volt"]
OUT2 = "projects/vtrux/notes/artifacts/partstruck_top_of_charge_p2.txt"


def window_for(session):
    cols, rows = influx("SELECT uploaded_at, file, t_start_ns, t_end_ns FROM "
                        "upload_manifest WHERE \"vehicle\"='vtrux' AND "
                        "\"session\"='%s'" % session)
    newest = {}
    for v in rows:
        r = dict(zip(cols, v))
        f, ua = r.get("file"), r.get("uploaded_at") or 0
        if f not in newest or ua > newest[f][0]:
            newest[f] = (ua, r)
    t0 = min(r["t_start_ns"] for _u, r in newest.values())
    t1 = max(r["t_end_ns"] for _u, r in newest.values())
    return t0 // 10**6, t1 // 10**6


def grid_for(session):
    m0, m1 = window_for(session)
    sel = ", ".join('"%s"' % f for f in F2)
    cols, rows = influx("SELECT %s FROM signals WHERE vehicle='vtrux' AND "
                        "session='%s' AND bus='powertrain' AND time >= %dms "
                        "AND time < %dms" % (sel, session, m0, m1 + 1000))
    rows.sort(key=lambda r: r[0])
    idx = {c: i for i, c in enumerate(cols)}
    cur = dict.fromkeys(F2)
    g = []
    k = 0
    for s in range(0, (m1 - m0) // 1000 + 1):
        tms = m0 + s * 1000
        while k < len(rows) and rows[k][0] <= tms:
            for f in F2:
                v = rows[k][idx[f]]
                if v is not None:
                    cur[f] = v
            k += 1
        g.append(dict(cur))
    return g


def phase2():
    out = ["phase 2: genuine tops of charge. t = s from the session's first "
           "stored point. ibat + = charging; Idc = charger's reported DC "
           "(negated). <=3.0 = first second from which chg_max stays <= 3.0 A "
           "up to the Low Power."]
    for sess in TOPS:
        g = grid_for(sess)
        n = len(g)
        lp = None
        for s in range(1, n):
            if g[s]["chgcmd_mode"] == 3 and g[s - 1]["chgcmd_mode"] != 3 \
                    and (g[s]["bms_soc_hires"] or 0) >= 95:
                lp = s
        if lp is None:
            out.append("%s: no Low Power at SoC >= 95 found" % sess)
            continue
        le3 = lp
        while le3 > 0 and g[le3 - 1]["bcm_chg_max"] is not None \
                and g[le3 - 1]["bcm_chg_max"] <= 3.0:
            le3 -= 1
        z = next((s for s in range(le3, lp + 1)
                  if g[s]["bcm_chg_max"] == 0), None)
        out.append("")
        out.append("%s  (%d s stored)" % (sess, n))
        for name, s in (("<=3.0", le3), ("=0", z), ("LowPwr", lp)):
            if s is None:
                out.append("  %-6s  never" % name)
                continue
            r = g[s]
            p12 = (r["DCDC_LV_Curr"] or 0) * (r["DCDC_LV_Volt"] or 0)
            out.append("  %-6s t=%6d  chgmax=%5.2f soc=%6.2f vmax=%.3f "
                       "vmin=%.3f ibat=%5.2f Idc=%5.2f P12=%4.0f W" % (
                           name, s, r["bcm_chg_max"], r["bms_soc_hires"],
                           r["bcm_cell_vmax"], r["bcm_cell_vmin"],
                           r["bcm_ibat"], -(r["BELINV_hvBatteryCurrent"] or 0),
                           p12))
        seg = g[le3:lp]
        if seg:
            ah = sum(r["bcm_ibat"] for r in seg) / 3600.0
            out.append("  <=3.0 -> LowPwr: %d s, mean ibat %.2f A, mean Idc "
                       "%.2f A, %.2f Ah into the pack, vmax %.3f -> %.3f" % (
                           len(seg), sum(r["bcm_ibat"] for r in seg) / len(seg),
                           -sum(r["BELINV_hvBatteryCurrent"] for r in seg)
                           / len(seg), ah, seg[0]["bcm_cell_vmax"],
                           g[lp]["bcm_cell_vmax"]))
        # chg_max walk: one line per 60 s over the 900 s before <= 3.0
        for s in range(max(0, le3 - 900), le3 + 1, 60):
            r = g[s]
            out.append("    t=%6d chgmax=%6.2f soc=%6.2f vmax=%.3f "
                       "spread=%3.0f mV ibat=%5.2f" % (
                           s, r["bcm_chg_max"], r["bms_soc_hires"],
                           r["bcm_cell_vmax"],
                           1000 * (r["bcm_cell_vmax"] - r["bcm_cell_vmin"]),
                           r["bcm_ibat"]))
    text = "\n".join(out) + "\n"
    with open(OUT2, "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__" and "p2" in sys.argv:
    phase2()


# ---------------------------------------------------------------------------
# Phase 3 (added 2026-10-10): the VCU's page-01 setpoint (from
# partstruck_top_setpoint.txt, the raw log's every change, same time base as
# the manifest window: log-relative seconds) joined to the BMS on a 1 s grid,
# 20 s bins, around the parts truck's top of charge. What does the VCU's
# setpoint track: chg_max, the leader cell, the pack current?
SETPT = "projects/vtrux/notes/artifacts/partstruck_top_setpoint.txt"
OUT3 = "projects/vtrux/notes/artifacts/partstruck_top_of_charge_p3.txt"


def phase3(r0=4900, r1=6800, binw=20):
    ch = []
    with open(SETPT) as f:
        for line in f:
            p = line.split()
            ch.append((float(p[0]), float(p[1].split("=")[1])))
    g = grid_for("vtrux_partstruck_charge")
    k, cur = 0, None
    out = ["phase 3: vtrux_partstruck_charge, %d s bins. setpt = VCU page-01 "
           "Ilim (mean, min-max); mode = chgcmd_mode at bin end" % binw,
           " t_rel  setpt (min-max)     chgmax  vmax   vmin  ibat  Idc  mode"]
    for b0 in range(r0, r1, binw):
        sp = []
        for s in range(b0, b0 + binw):
            while k < len(ch) and ch[k][0] <= s:
                cur = ch[k][1]
                k += 1
            if cur is not None:
                sp.append(cur)
        rows = g[b0:b0 + binw]
        m = lambda f: sum(r[f] for r in rows) / len(rows)
        out.append("%6d  %5.2f (%5.2f-%5.2f)  %6.2f  %.3f  %.3f  %5.2f %5.2f  %s"
                   % (b0, sum(sp) / len(sp), min(sp), max(sp), m("bcm_chg_max"),
                      m("bcm_cell_vmax"), m("bcm_cell_vmin"), m("bcm_ibat"),
                      -m("BELINV_hvBatteryCurrent"), rows[-1]["chgcmd_mode"]))
    text = "\n".join(out) + "\n"
    with open(OUT3, "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__" and "p3" in sys.argv:
    phase3()


# ---------------------------------------------------------------------------
# Phase 4 (added 2026-10-12): around the parts truck's Low Power command, the
# charger's maxAvailableChargingCurrent against the EVSE's pilot duty and the
# VCU's page-01 setpoint. Question (user): was the 6.00 A reading in mode 3 an
# EVSE limit change, and did the VCU send setpoints above it after it fell?
# Per 1 s: mode, pilotDuty, maxAvail, the setpoint in force, Idc (negated).
OUT4 = "projects/vtrux/notes/artifacts/partstruck_top_of_charge_p4.txt"


def phase4(r0=6540, r1=6900):
    sess = "vtrux_partstruck_charge"
    m0, m1 = window_for(sess)
    f4 = ["chgcmd_mode", "BELINV_pilotDuty", "BELINV_maxAvailableChargingCurrent",
          "BELINV_hvBatteryCurrent", "BELINV_state"]
    sel = ", ".join('"%s"' % f for f in f4)
    cols, rows = influx("SELECT %s FROM signals WHERE vehicle='vtrux' AND "
                        "session='%s' AND bus='powertrain' AND time >= %dms "
                        "AND time < %dms" % (sel, sess, m0 + (r0 - 60) * 1000,
                                             m0 + r1 * 1000))
    rows.sort(key=lambda r: r[0])
    idx = {c: i for i, c in enumerate(cols)}
    ch = []
    with open(SETPT) as f:
        for line in f:
            p = line.split()
            ch.append((float(p[0]), float(p[1].split("=")[1])))
    cur = dict.fromkeys(f4)
    k = j = 0
    sp = None
    out = ["phase 4: %s, 1 s, t_rel  mode  pilotDuty  maxAvail  setpt  Idc  state" % sess]
    prev = None
    for s in range(r0 - 60, r1):
        tms = m0 + s * 1000
        while k < len(rows) and rows[k][0] <= tms:
            for f in f4:
                v = rows[k][idx[f]]
                if v is not None:
                    cur[f] = v
            k += 1
        while j < len(ch) and ch[j][0] <= s:
            sp = ch[j][1]
            j += 1
        if s < r0:
            continue
        line = "%5d  %s  %s  %s  %s  %s  %s" % (
            s, cur["chgcmd_mode"], cur["BELINV_pilotDuty"],
            cur["BELINV_maxAvailableChargingCurrent"], sp,
            None if cur["BELINV_hvBatteryCurrent"] is None
            else round(-cur["BELINV_hvBatteryCurrent"], 2),
            cur["BELINV_state"])
        key = line.split(None, 1)[1]
        if key != prev or s % 30 == 0:
            out.append(line)
        prev = key
    text = "\n".join(out) + "\n"
    with open(OUT4, "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__" and "p4" in sys.argv:
    phase4()
