"""Every entry into Bel state 8 (STANDBY) in InfluxDB (bus=powertrain), with the
state before it and, in +/-5 s, the first-seen values/changes of: VCU flow bit
and mode (0x18EFC000), shutdownSource, buck-boost / inverter states, DC current,
chargingInProgress. InfluxDB is on-change + 1 s heartbeat: values exact, timing
to the stored point only.
Usage: python3.13 <this>
"""
import json
import urllib.parse
import urllib.request

URL = "http://localhost:8086/query"


def q(s):
    u = URL + "?" + urllib.parse.urlencode({"db": "canbus-data", "q": s, "u": "claude", "p": "claude", "epoch": "ms"})
    return json.load(urllib.request.urlopen(u))["results"][0].get("series", [])


BASE = "vehicle='vtrux' AND bus='powertrain'"
sessions = [s["tags"]["session"] for s in q(
    f"SELECT COUNT(\"BELINV_state\") FROM signals WHERE {BASE} AND can_id='0x18FFD4C0' "
    f"AND \"BELINV_state\" = 8 GROUP BY session")]
SIG = [("0x18EFC000", "chgcmd_enable"), ("0x18EFC000", "chgcmd_mode"),
       ("0x18FFD4C0", "BELINV_shutdownSource"), ("0x18FFD4C0", "BELINV_buckBoostState"),
       ("0x18FFD4C0", "BELINV_inverterState"), ("0x18FFD4C0", "BELINV_chargingInProgress"),
       ("0x18FFD7C0", "BELINV_hvBatteryCurrent"), ("0x18FFD7C0", "BELINV_chargerInputVoltage")]
for sess in sorted(sessions):
    rows = q(f"SELECT \"BELINV_state\" FROM signals WHERE {BASE} AND can_id='0x18FFD4C0' "
             f"AND session='{sess}' AND \"BELINV_state\" >= 0")
    vals = [(t, v) for t, v in rows[0]["values"] if v is not None] if rows else []
    prev = None
    for t, v in vals:
        if v == 8 and prev is not None and prev != 8:
            print(f"\n=== {sess}  t={t}  state {prev} -> 8")
            for cid, sig in SIG:
                r = q(f"SELECT \"{sig}\" FROM signals WHERE {BASE} AND can_id='{cid}' AND session='{sess}' "
                      f"AND time >= {t - 5000}ms AND time <= {t + 5000}ms AND \"{sig}\" > -1000000000")
                pts = [(pt - t, x) for pt, x in (r[0]["values"] if r else []) if x is not None]
                chg, lastx = [], object()
                for dt, x in pts:
                    if x != lastx:
                        chg.append(f"{dt/1000:+.1f}s={x:g}")
                        lastx = x
                print(f"   {sig:28s} " + " ".join(chg[:14]))
        prev = v
