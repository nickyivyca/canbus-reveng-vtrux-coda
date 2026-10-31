"""Every VCU flow-on period (chgcmd_enable 1) in InfluxDB, bus=powertrain, that
ended without the Bel charger ever reporting chargingInProgress=1 -- an aborted
start. For each: duration of the flow-on, Bel states / buck-boost / inverter
values seen during it, AC V range, max AC current, and whether the VCM warn lamp
(0x646) came on within 1 s of the flow drop.
InfluxDB is on-change + 1 s heartbeat (values exact, timing to the stored point),
and misses Android T0 channels dropped by identify_buses.
Usage: python3.13 <this>
"""
import json
import urllib.parse
import urllib.request

URL = "http://localhost:8086/query"
BASE = "vehicle='vtrux' AND bus='powertrain'"


def q(s):
    u = URL + "?" + urllib.parse.urlencode({"db": "canbus-data", "q": s, "u": "claude", "p": "claude", "epoch": "ms"})
    r = json.load(urllib.request.urlopen(u))["results"][0].get("series", [])
    return [(t, v) for t, v in r[0]["values"] if v is not None] if r else []


def series(sess, cid, sig, t0=None, t1=None):
    w = f" AND time >= {t0}ms AND time <= {t1}ms" if t0 is not None else ""
    return q(f"SELECT \"{sig}\" FROM signals WHERE {BASE} AND can_id='{cid}' AND session='{sess}'"
             f" AND \"{sig}\" > -1000000000{w}")


sessions = [s["tags"]["session"] for s in json.load(urllib.request.urlopen(URL + "?" + urllib.parse.urlencode({
    "db": "canbus-data", "u": "claude", "p": "claude",
    "q": f"SELECT COUNT(\"chgcmd_enable\") FROM signals WHERE {BASE} AND can_id='0x18EFC000' GROUP BY session"})))
    ["results"][0].get("series", [])]
print(f"{len(sessions)} sessions carry chgcmd_enable\n")
total_on = 0
for sess in sorted(sessions):
    en = series(sess, "0x18EFC000", "chgcmd_enable")
    periods, start, prev = [], None, 0
    for t, v in en:
        if v == 1 and prev != 1:
            start = t
        if v != 1 and prev == 1 and start is not None:
            periods.append((start, t))
        prev = v
    total_on += len(periods)
    for a, b in periods:
        cip = [v for _, v in series(sess, "0x18FFD4C0", "BELINV_chargingInProgress", a, b)]
        if 1 in cip:
            continue
        st = sorted({int(v) for _, v in series(sess, "0x18FFD4C0", "BELINV_state", a, b)})
        bb = sorted({int(v) for _, v in series(sess, "0x18FFD4C0", "BELINV_buckBoostState", a, b)})
        inv = sorted({int(v) for _, v in series(sess, "0x18FFD4C0", "BELINV_inverterState", a, b)})
        acv = [v for _, v in series(sess, "0x18FFD7C0", "BELINV_chargerInputVoltage", a, b)]
        aci = [v for _, v in series(sess, "0x18FFD7C0", "BELINV_chargerInputCurrent", a, b)]
        lamp = [v for _, v in series(sess, "0x646", "via_warn_lamp_state", b - 1000, b + 1000)]
        print(f"{sess:45s} on={(b - a) / 1000:6.1f}s  states={st} bb={bb} inv={inv} "
              f"acV={min(acv, default=0):.0f}-{max(acv, default=0):.0f} acImax={max(aci, default=0):.1f} "
              f"lamp_vals_near_drop={sorted(set(lamp))}")
print(f"\n{total_on} flow-on periods in total")
