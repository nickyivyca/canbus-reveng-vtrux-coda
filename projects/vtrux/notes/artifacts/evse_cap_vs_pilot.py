"""evse_cap_vs_pilot.py -- does the Bel's BELINV_maxAvailableChargingCurrent
follow the EVSE's pilot (BELINV_pilotDuty), i.e. does the charger enforce the
EVSE's limit itself? For the interposer's cap question (user, 2026-10-12: the
cap is there to avoid tripping the EVSE, not the charger's own DC limit).

The DBC (BelInverter-v2.dbc CM_ on maxAvail) says it is the DC-side limit and
NOT the J1772 advertised current, which must be derived from pilotDuty
(J1772: 10-85 % duty -> amps = duty x 0.6).

Phase 1: per session (InfluxDB, powertrain, every query bounded by the
session's upload_manifest window -- tools/tools.md, the 2026-09-27 outage),
the pilot duty while present (> 0) and maxAvail while charging (> 0):
median / min / max. Server-side aggregates only, one session at a time.
Phase 2: for sessions whose pilot offers less than the charger's usual
16-17 A DC would need, a 10 s time series of duty, maxAvail, the charger's
DC output, its AC input current and the VCU's mode.
"""
import sys
sys.path.insert(0, ".")
import base64
import json
import urllib.parse
import urllib.request

OUT1 = "projects/vtrux/notes/artifacts/evse_cap_vs_pilot.txt"
PHASES = set(sys.argv[1:]) or {"1"}


def influx(q, db="canbus-data"):
    url = ("http://localhost:8086/query?" + urllib.parse.urlencode(
        {"db": db, "q": q, "epoch": "ms"}))
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Basic " +
                   base64.b64encode(b"claude:claude").decode())
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode())
    rows, cols = [], None
    for res in d.get("results", []):
        if "error" in res:
            raise RuntimeError(res["error"])
        for se in res.get("series", []):
            cols = se["columns"]
            rows.extend(se["values"])
    return cols, rows


def sessions():
    cols, rows = influx("SHOW TAG VALUES FROM upload_manifest WITH KEY = "
                        "\"session\" WHERE \"vehicle\"='vtrux'")
    return sorted(r[1] for r in rows)


def window_ms(session):
    cols, rows = influx("SELECT uploaded_at, file, t_start_ns, t_end_ns FROM "
                        "upload_manifest WHERE \"vehicle\"='vtrux' AND "
                        "\"session\"='%s'" % session.replace("'", "\\'"))
    newest = {}
    for v in rows:
        r = dict(zip(cols, v))
        f, ua = r.get("file"), r.get("uploaded_at") or 0
        if f not in newest or ua > newest[f][0]:
            newest[f] = (ua, r)
    t0 = [r["t_start_ns"] for _u, r in newest.values() if r.get("t_start_ns")]
    t1 = [r["t_end_ns"] for _u, r in newest.values() if r.get("t_end_ns")]
    if not t0 or not t1:
        return None
    return min(t0) // 10**6, max(t1) // 10**6 + 1000


def agg(session, field, w):
    q = ("SELECT MEDIAN(\"%s\"), MIN(\"%s\"), MAX(\"%s\") FROM signals WHERE "
         "vehicle='vtrux' AND session='%s' AND bus='powertrain' AND "
         "\"%s\" > 0 AND time >= %dms AND time < %dms" % (
             field, field, field, session.replace("'", "\\'"), field,
             w[0], w[1]))
    cols, rows = influx(q)
    return rows[0][1:] if rows else None


def phase1():
    out = ["phase 1: per session, pilotDuty (>0) and maxAvail (>0): median "
           "min max. J1772 amps = duty x 0.6.",
           "session | duty med/min/max | -> A AC (med) | maxAvail med/min/max"]
    for s in sessions():
        w = window_ms(s)
        if w is None:
            continue
        d = agg(s, "BELINV_pilotDuty", w)
        if not d:
            continue
        m = agg(s, "BELINV_maxAvailableChargingCurrent", w)
        out.append("%s | %s/%s/%s | %.1f | %s" % (
            s, d[0], d[1], d[2], (d[0] or 0) * 0.6,
            "-" if not m else "%s/%s/%s" % tuple(m)))
        print(out[-1], flush=True)
    with open(OUT1, "w") as f:
        f.write("\n".join(out) + "\n")


if "1" in PHASES:
    phase1()
