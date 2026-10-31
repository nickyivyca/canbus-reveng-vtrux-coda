"""ct_charger_signature.py -- can the garage 14-50 CT tell a Vtrux charge from a
Coda charge by how power follows line voltage? (2026-10-10, BMS SoC plan step 3)

User, 2026-10-10: the Vtrux derates from the EVSE's current limit; the Coda's
limit is a fixed power limit in its charger. So on the ~6.9 kW plateau:
  Vtrux  ~constant current -> power follows line voltage, dP/dV ~ +I (~29 W/V)
  Coda   ~constant power   -> dP/dV ~ 0, current falls as voltage rises.
Infrastructure/vehicle-cost-per-mile.md section 5 found the plateau LEVEL
identical for both; this tests the SHAPE.

  1  CAN-confirmed charging spans in the CT era (from 2025-11-30):
       Vtrux: BELINV_chargerInputCurrent > 20 A for >= 20 min, from the 1 s
              cache of bms_soc_learning.py (both trucks);
       Coda:  ACInPower > 3000 W for >= 20 min, MAX per minute, bounded per
              Coda session (sessions >= 20 min long only).
  2  for each span: CT minute averages (homeassistant W,
     garage_14_50_power_minute_average, forward-filled) and Envoy line voltage
     (V, envoy_..._voltage_net_consumption_ct, ~1 min, forward-filled); plateau
     minutes = span trimmed 5 min at each end, CT > 5 kW. Least-squares
     dP/dV and r, and the spread of P and of I = P / V.
  3  the same for named unattributed blocks (the 06-13 13:30 PDT block).

Query rules: every statement bounded by a session window or block; sequential.
"""
import sys
sys.path.insert(0, ".")
import base64
import datetime as dt
import gzip
import json
import statistics as st
import urllib.parse
import urllib.request

ART = "projects/vtrux/notes/artifacts/"
CT = "garage_14_50_power_minute_average"
VOLT = "envoy_202220094881_voltage_net_consumption_ct"
CT_START = 1764460800
PHASES = {1, 2, 3}
UNATTR = [("06-13 13:30 PDT block (unattributed)", 1781382600, 1781393880),
          ("06-14 13:51 PDT block (Vtrux by CV hold)", 1781470260, 1781474160)]


def q(db, s):
    url = "http://localhost:8086/query?" + urllib.parse.urlencode({"db": db, "q": s, "epoch": "s"})
    r = urllib.request.Request(url)
    r.add_header("Authorization", "Basic " + base64.b64encode(b"claude:claude").decode())
    with urllib.request.urlopen(r, timeout=120) as f:
        d = json.load(f)
    out = []
    for res in d.get("results", []):
        for se in res.get("series", []):
            out.extend(se["values"])
    out.sort()
    return out


def utc(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def spans_from(minutes, thr, min_len=20):
    """minutes: sorted [(t, v)] at 60 s; contiguous runs with v > thr"""
    out, cur = [], None
    for t, v in minutes:
        if v is not None and v > thr:
            if cur and t - cur[1] <= 120:
                cur[1] = t
            else:
                if cur:
                    out.append(cur)
                cur = [t, t]
    if cur:
        out.append(cur)
    return [(a, b + 60) for a, b in out if b + 60 - a >= min_len * 60]


spans = []
if 1 in PHASES:
    ser = json.load(gzip.open(ART + "bms_soc_learning_1s.json.gz", "rt"))
    for s_, d in ser.items():
        ac = d["BELINV_chargerInputCurrent"]
        if not ac:
            continue
        per_min = {}
        for t, v in ac.items():
            if v is not None:
                m = int(t) // 60 * 60
                per_min[m] = max(per_min.get(m, 0), v)
        for a, b in spans_from(sorted(per_min.items()), 20):
            if a >= CT_START:
                spans.append(("vtrux", s_, a, b))
    rows = q("canbus-data", "SELECT session, file, t_start_ns, t_end_ns FROM upload_manifest "
             "WHERE \"vehicle\"='coda'")
    cw = {}
    for _t, sess, _f, a, b in rows:
        if a and b:
            a, b = a // 10**9, b // 10**9 + 1
            w = cw.get(sess)
            cw[sess] = (min(a, w[0]), max(b, w[1])) if w else (a, b)
    cand = [(s_, a, b) for s_, (a, b) in cw.items() if b >= CT_START and b - a >= 1200]
    print("phase1: %d vtrux spans; %d coda sessions to check" % (len(spans), len(cand)), flush=True)
    for s_, a, b in sorted(cand, key=lambda x: x[1]):
        hit = q("canbus-data", "SELECT \"ACInPower\" FROM signals WHERE vehicle='coda' AND "
                "session='%s' AND time >= %ds AND time < %ds AND \"ACInPower\" > 3000 LIMIT 1"
                % (s_, a, b))
        if not hit:
            continue
        mins = q("canbus-data", "SELECT MAX(\"ACInPower\") FROM signals WHERE vehicle='coda' AND "
                 "session='%s' AND time >= %ds AND time < %ds GROUP BY time(60s) fill(none)"
                 % (s_, a, b))
        for x, y in spans_from(mins, 3000):
            spans.append(("coda", s_, x, y))
    json.dump(spans, open(ART + "ct_charger_signature_spans.json", "w"))
else:
    spans = json.load(open(ART + "ct_charger_signature_spans.json"))


def fill(rows, a, b):
    out, k, val = [], 0, None
    for m in range(a, b, 60):
        while k < len(rows) and rows[k][0] <= m:
            val = rows[k][1]
            k += 1
        out.append((m, val))
    return out


def shape(a, b):
    p = q("homeassistant", "SELECT value FROM \"W\" WHERE entity_id='%s' AND time >= %ds AND "
          "time < %ds" % (CT, a - 3600, b))
    v = q("homeassistant", "SELECT value FROM \"V\" WHERE entity_id='%s' AND time >= %ds AND "
          "time < %ds" % (VOLT, a - 3600, b))
    pp, vv = fill(p, a + 300, b - 300), fill(v, a + 300, b - 300)
    xy = [(y[1], x[1]) for x, y in zip(pp, vv) if x[1] and y[1] and x[1] > 5000]
    if len(xy) < 10:
        return None
    vs, ps = [x for x, _ in xy], [y for _, y in xy]
    mv, mp = st.mean(vs), st.mean(ps)
    sxx = sum((x - mv) ** 2 for x in vs)
    sxy = sum((x - mv) * (y - mp) for x, y in xy)
    syy = sum((y - mp) ** 2 for y in ps)
    slope = sxy / sxx if sxx else float("nan")
    r = sxy / (sxx * syy) ** 0.5 if sxx and syy else float("nan")
    cur = [y / x for x, y in xy]
    return {"n": len(xy), "slope": slope, "r": r, "vrange": max(vs) - min(vs), "p": mp,
            "psd": st.pstdev(ps), "i": st.mean(cur), "isd": st.pstdev(cur)}


if 2 in PHASES or 3 in PHASES:
    res = []
    print("\nphase2: plateau shape per CAN-confirmed span (CT > 5 kW, ends trimmed 5 min)")
    print("  car    start (UTC)        min | n   P mean  P sd |  I mean  I sd | V range | dP/dV W/V   r     | session")
    for car, s_, a, b in sorted(spans, key=lambda x: x[2]):
        sh = shape(a, b)
        if not sh:
            continue
        res.append((car, s_, a, sh))
        print("  %-5s  %s  %4d | %3d  %6.0f %5.0f | %6.2f %5.2f | %5.1f V | %+7.1f   %+.2f | %s"
              % (car, utc(a), (b - a) / 60, sh["n"], sh["p"], sh["psd"], sh["i"], sh["isd"],
                 sh["vrange"], sh["slope"], sh["r"], s_[:40]))
    print("\n  summary by car (spans with V range >= 2 V, so the slope is measurable):")
    for car in ("vtrux", "coda"):
        x = [r[3] for r in res if r[0] == car and r[3]["vrange"] >= 2]
        if x:
            sl = sorted(r["slope"] for r in x)
            print("    %-5s n=%2d  dP/dV median %+.1f W/V (q1 %+.1f, q3 %+.1f)  r median %+.2f  I sd median %.2f A  P sd median %.0f W"
                  % (car, len(x), st.median(sl), sl[len(sl) // 4], sl[3 * len(sl) // 4],
                     st.median(r["r"] for r in x), st.median(r["isd"] for r in x),
                     st.median(r["psd"] for r in x)))

if 3 in PHASES:
    print("\nphase3: unattributed blocks")
    for name, a, b in UNATTR:
        sh = shape(a, b)
        if sh:
            print("  %-42s n=%3d  P %6.0f sd %4.0f | I %5.2f sd %.2f | V range %4.1f | dP/dV %+6.1f W/V  r %+.2f"
                  % (name, sh["n"], sh["p"], sh["psd"], sh["i"], sh["isd"], sh["vrange"],
                     sh["slope"], sh["r"]))
