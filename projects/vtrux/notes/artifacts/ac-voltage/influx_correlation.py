"""Correlate Vtrux charge sessions against panel-side data from InfluxDB.

Purpose: separate GRID-side voltage shifts from HOUSE-side wiring resistance.

The truck measures AC voltage at the end of everything (utility transformer ->
service drop -> panel -> garage run -> EVSE -> cord). The Enphase Envoy measures
voltage at the service panel. The difference between them, divided by the charge
current, is the resistance of the house-side run alone:

    R_total  = (V_open_circuit - V_truck) / I          (from CAN alone)
    R_house  = (V_panel        - V_truck) / I          (needs Influx)
    R_utility= R_total - R_house

It also answers whether the ~20% gap between the whole-session regression and the
drift-immune step estimator is caused by grid drift: if it is, panel voltage
should trend upward over a charge while the truck's current tapers.

Sources:
  envoy_202220094881_voltage_net_consumption_ct  ("V")  panel voltage
  garage_14_50_power_minute_average              ("W")  the EVSE circuit

Connection details from ../Infrastructure/ha-claude-connection/notes.md.
Log timestamps are LOCAL (America/Los_Angeles); InfluxDB is UTC.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/ac-voltage/influx_correlation.py
"""

import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, ".")

ART = "projects/vtrux/notes/artifacts/ac-voltage"
SESSIONS = os.path.join(ART, "sessions.csv")

INFLUX = "http://localhost:8086/query"
USER, PASSWORD, DB = "claude", "claude", "homeassistant"
V_PANEL = "envoy_202220094881_voltage_net_consumption_ct"
P_EVSE = "garage_14_50_power_minute_average"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")
EVSE_ON_W = 3000.0     # circuit is considered actively charging above this
MIN_OVERLAP = 5        # minutes of EVSE-on data needed to use a session


def influx(q):
    url = INFLUX + "?" + urllib.parse.urlencode(
        {"u": USER, "p": PASSWORD, "db": DB, "q": q})
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def series(resp):
    """Flatten an Influx response into [(datetime_utc, value), ...]."""
    out = []
    for res in resp.get("results", []):
        for s in res.get("series", []):
            for t, v in s["values"]:
                if v is None:
                    continue
                out.append((datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S"), v))
    return out


def to_utc(local_str):
    """'YYYY-MM-DD HH:MM' local -> naive UTC datetime (handles PST/PDT)."""
    dt = datetime.strptime(local_str, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def fetch(entity, measurement, t0, t1):
    q = ("SELECT mean(value) FROM \"%s\" WHERE entity_id='%s' "
         "AND time >= '%sZ' AND time <= '%sZ' GROUP BY time(1m) fill(none)"
         % (measurement, entity, t0.strftime("%Y-%m-%dT%H:%M:%S"),
            t1.strftime("%Y-%m-%dT%H:%M:%S")))
    return series(influx(q))


def main():
    rows = list(csv.DictReader(open(SESSIONS, encoding="utf-8")))
    # 240 V sessions with a usable duration and a known wall-clock start
    cand = []
    for r in rows:
        if not r["when"].strip('"'):
            continue
        try:
            vmed = float(r["v_med"])
            imed = float(r["i_med"])
            dur = float(r["dur_s"])
        except ValueError:
            continue
        if vmed < 225.0 or dur < 300 or imed < 5.0:
            continue
        cand.append((r, vmed, imed, dur))
    print("%d candidate 240 V sessions (>=5 min, >=5 A) from %d total\n"
          % (len(cand), len(rows)))

    matched = []
    for r, vmed, imed, dur in cand:
        when = r["when"].strip('"')
        try:
            t0 = to_utc(when)
        except ValueError:
            continue
        t1 = t0 + timedelta(seconds=dur)
        try:
            pw = fetch(P_EVSE, "W", t0 - timedelta(minutes=2), t1 + timedelta(minutes=2))
        except Exception as exc:
            print("  query failed for %s: %s" % (when, exc))
            continue
        on = [(t, v) for t, v in pw if v >= EVSE_ON_W]
        if len(on) < MIN_OVERLAP:
            continue
        try:
            vp = fetch(V_PANEL, "V", t0 - timedelta(minutes=2), t1 + timedelta(minutes=2))
        except Exception as exc:
            print("  voltage query failed for %s: %s" % (when, exc))
            continue
        if len(vp) < MIN_OVERLAP:
            continue

        # Pair panel voltage with EVSE-on minutes only
        on_times = set(t.replace(second=0) for t, _ in on)
        vp_on = [v for t, v in vp if t.replace(second=0) in on_times]
        if len(vp_on) < MIN_OVERLAP:
            continue

        v_panel = sum(vp_on) / len(vp_on)
        p_evse = sum(v for _t, v in on) / len(on)
        i_evse = p_evse / v_panel if v_panel else float("nan")

        drop = v_panel - vmed
        r_house = drop / imed if imed else float("nan")

        # grid drift over the session, measured at the panel
        vp_sorted = sorted(vp, key=lambda p: p[0])
        n = len(vp_sorted)
        first = sum(v for _t, v in vp_sorted[:max(1, n // 4)]) / max(1, n // 4)
        last = sum(v for _t, v in vp_sorted[-max(1, n // 4):]) / max(1, n // 4)

        matched.append({
            "when": when, "file": r["file"].strip('"'), "dur": dur,
            "v_truck": vmed, "i_truck": imed, "v_panel": v_panel,
            "p_evse": p_evse, "i_evse": i_evse, "drop": drop,
            "r_house": r_house, "lr": r["lr"], "drift": last - first,
            "n_on": len(on),
        })

    if not matched:
        print("No sessions overlapped the garage 14-50 circuit.")
        return

    print("=" * 118)
    print("HOME EVSE SESSIONS: TRUCK vs PANEL")
    print("=" * 118)
    print("%-16s %-26s %5s %8s %8s %8s %8s %8s %9s %8s"
          % ("when (local)", "file", "min", "V truck", "V panel", "drop V",
             "I truck", "I evse", "R house", "drift V"))
    for m in sorted(matched, key=lambda d: d["when"]):
        print("%-16s %-26s %5.0f %8.1f %8.1f %8.2f %8.1f %8.1f %9.3f %+8.2f"
              % (m["when"], m["file"][:26], m["dur"] / 60.0, m["v_truck"],
                 m["v_panel"], m["drop"], m["i_truck"], m["i_evse"],
                 m["r_house"], m["drift"]))

    # The truck's median current covers the WHOLE session including CV taper,
    # while the Emporia average covers only EVSE-on minutes. When a session is
    # mostly taper the two describe different things and R_house is meaningless
    # (it can even go negative). Require the two current figures to agree.
    ok = [m for m in matched if abs(m["i_evse"] - m["i_truck"]) <= 3.0]
    bad = [m for m in matched if m not in ok]
    print("\n%d of %d sessions have truck and Emporia current agreeing within 3 A;"
          % (len(ok), len(matched)))
    print("%d dropped as taper/window mismatches: %s"
          % (len(bad), ", ".join(m["when"] for m in bad)))

    rh = sorted(m["r_house"] for m in ok)
    k = len(rh) // 2
    print("\nR_house (panel -> truck: garage run + EVSE + cord), agreeing sessions only:")
    print("  n=%d  min %.3f  median %.3f  max %.3f ohm" % (len(rh), rh[0], rh[k], rh[-1]))

    R_TOTAL_STEPS = 0.413   # 240 V / 31 A bucket, settled step estimator
    print("\n  Decomposition against the CAN-only total (%.3f ohm, step estimator):"
          % R_TOTAL_STEPS)
    print("    R_house   (panel -> truck)      = %.3f ohm" % rh[k])
    print("    R_utility (transformer -> panel) = %.3f ohm" % (R_TOTAL_STEPS - rh[k]))

    di = sorted(m["i_evse"] - m["i_truck"] for m in ok)
    print("\nCurrent cross-check (Emporia vs charger-reported), agreeing sessions:")
    print("  median difference %.2f A. Emporia reads the whole circuit (EVSE overhead,"
          % di[len(di) // 2])
    print("  power-factor assumption), so a small positive bias is expected.")

    dr = sorted(m["drift"] for m in ok)
    print("\nPanel voltage drift over a session (last quarter - first quarter):")
    print("  n=%d  min %+.2f  median %+.2f  max %+.2f V"
          % (len(dr), dr[0], dr[len(dr) // 2], dr[-1]))
    print("  A positive median means grid voltage RISES during a charge. Combined with")
    print("  a tapering current that inflates whole-session regression estimates of R.")

    out = os.path.join(ART, "influx_correlation.csv")
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(matched[0].keys()))
        w.writeheader()
        w.writerows(matched)
    print("\nWrote %s (%d sessions)" % (out, len(matched)))


if __name__ == "__main__":
    main()
