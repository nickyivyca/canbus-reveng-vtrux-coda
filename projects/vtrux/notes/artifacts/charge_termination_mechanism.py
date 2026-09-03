"""
Charge termination mechanism study (for the CAN interposer project).

Phases:
  1  inventory  - for every charge-bearing session, summarise SoC range, charger
                  state path, shutdown source, and BMS charge-permission signals.
  2  timeline   - per-session dense timeline of the termination window.
  3  topvolt    - top-of-charge voltage control: vmax/vmin/chg_max/current vs SoC.

Usage:
    python3.13 projects/vtrux/notes/artifacts/charge_termination_mechanism.py <phase> [session ...]
"""

import sys
import json
import urllib.parse
import urllib.request

sys.path.insert(0, ".")

INFLUX = "http://localhost:8086/query"
AUTH = ("<influx-user>", "<influx-password>")
DB = "canbus-data"

ART = "projects/vtrux/notes/artifacts"


def q(query):
    url = INFLUX + "?" + urllib.parse.urlencode({"db": DB, "q": query, "epoch": "ms"})
    req = urllib.request.Request(url)
    import base64
    tok = base64.b64encode(("%s:%s" % AUTH).encode()).decode()
    req.add_header("Authorization", "Basic " + tok)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def series(res):
    """Yield (name, columns, values) for every series in every result."""
    for r in res.get("results", []):
        for s in r.get("series", []):
            yield s.get("name"), s["columns"], s["values"]


def one(res):
    for _n, cols, vals in series(res):
        return cols, vals
    return None, []


# Signals grouped by the CAN ID they live on, so each SELECT hits one series.
GROUPS = {
    "0x18FFD4C0": [
        "BELINV_state", "BELINV_shutdownSource", "BELINV_stateBeforeLastShutdown",
        "BELINV_chargingInProgress", "BELINV_chargerEnergyFlowEnable",
        "BELINV_inverterFault", "BELINV_buckBoostFault", "BELINV_hvBatteryOverVoltage",
        "BELINV_unitReady", "BELINV_s2Switch", "BELINV_evseConnected",
    ],
    "0x18FFD7C0": [
        "BELINV_hvBatteryVoltage", "BELINV_hvBatteryCurrent",
        "BELINV_chargerInputVoltage", "BELINV_chargerInputCurrent",
    ],
    "0x18FFD9C0": ["BELINV_maxAvailableChargingCurrent", "BELINV_vehicleState"],
    "0x410": [
        "bcm_soc", "bcm_ibat", "bcm_vbat", "bcm_chg_done", "bcm_cpwr_cmd",
        "bcm_chgc_stat", "bcm_mainc_stat", "bcm_on_plug", "bcm_ready",
        "bcm_epo", "bcm_alarm",
    ],
    "0x420": ["bcm_chg_max", "bcm_dis_max", "bcm_cell_overvolt", "bcm_cell_undervolt"],
    "0x430": ["bcm_cell_vmax", "bcm_cell_vmin", "bcm_chga_ena", "bcm_chga_mon", "bcm_mod_ena"],
    "0x440": ["bcm_balancing", "bcm_balancing_cnt", "bcm_vbus_pos"],
    "0x411": ["bms_soc_hires"],
}


def sel(session, can_id, fields, agg=None, group=None, extra=""):
    cols = ", ".join('%s("%s") AS "%s"' % (agg, f, f) for f in fields) if agg \
        else ", ".join('"%s"' % f for f in fields)
    w = "vehicle='vtrux' AND can_id='%s' AND session='%s'" % (can_id, session)
    g = (" GROUP BY %s" % group) if group else ""
    return 'SELECT %s FROM signals WHERE %s%s%s' % (cols, w, extra, g)


def session_bounds(session):
    res = q("SELECT FIRST(\"bcm_soc\"), LAST(\"bcm_soc\") FROM signals "
            "WHERE vehicle='vtrux' AND can_id='0x410' AND session='%s'" % session)
    cols, vals = one(res)
    if not vals:
        return None
    res2 = q("SELECT \"bcm_soc\" FROM signals WHERE vehicle='vtrux' AND can_id='0x410' "
             "AND session='%s' ORDER BY time ASC LIMIT 1" % session)
    _c, v2 = one(res2)
    res3 = q("SELECT \"bcm_soc\" FROM signals WHERE vehicle='vtrux' AND can_id='0x410' "
             "AND session='%s' ORDER BY time DESC LIMIT 1" % session)
    _c, v3 = one(res3)
    if not v2 or not v3:
        return None
    return v2[0][0], v3[0][0], v2[0][1], v3[0][1]


def phase_inventory(sessions):
    hdr = ("%-46s %10s %10s %7s %7s %7s %7s %6s %6s %6s %6s"
           % ("session", "dur_min", "socRange", "vmaxMax", "chgMaxF", "stateF",
              "sdSrc", "chgDone", "ovolt", "balMax", "vehSt"))
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for s in sessions:
        b = session_bounds(s)
        if not b:
            continue
        t0, t1, soc0, soc1 = b
        dur = (t1 - t0) / 60000.0
        if dur < 5:
            continue

        def last(cid, f):
            r = q("SELECT \"%s\" FROM signals WHERE vehicle='vtrux' AND can_id='%s' "
                  "AND session='%s' ORDER BY time DESC LIMIT 1" % (f, cid, s))
            _c, v = one(r)
            return v[0][1] if v else None

        def mx(cid, f):
            r = q("SELECT MAX(\"%s\") FROM signals WHERE vehicle='vtrux' AND can_id='%s' "
                  "AND session='%s'" % (f, cid, s))
            _c, v = one(r)
            return v[0][1] if v else None

        vmax = mx("0x430", "bcm_cell_vmax")
        chgmax_f = last("0x420", "bcm_chg_max")
        state_f = last("0x18FFD4C0", "BELINV_state")
        sdsrc = last("0x18FFD4C0", "BELINV_shutdownSource")
        chgdone = mx("0x410", "bcm_chg_done")
        ovolt = mx("0x420", "bcm_cell_overvolt")
        balmax = mx("0x440", "bcm_balancing_cnt")
        vehst = last("0x18FFD9C0", "BELINV_vehicleState")
        socmax = mx("0x410", "bcm_soc")

        def fmt(x, n=1):
            return "-" if x is None else ("%.*f" % (n, x))

        row = ("%-46s %10.1f %10s %7s %7s %7s %7s %6s %6s %6s %6s"
               % (s, dur, "%.0f-%.0f" % (soc0, socmax if socmax else soc1),
                  fmt(vmax, 3), fmt(chgmax_f), fmt(state_f, 0), fmt(sdsrc, 0),
                  fmt(chgdone, 0), fmt(ovolt, 0), fmt(balmax, 0), fmt(vehst, 0)))
        print(row)
        rows.append(row)
    return rows


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "inventory"
    args = sys.argv[2:]
    if phase == "inventory":
        if args:
            sessions = args
        else:
            res = q("SHOW TAG VALUES FROM signals WITH KEY=session WHERE vehicle='vtrux'")
            _c, vals = one(res)
            allses = [v[1] for v in vals]
            sessions = [s for s in allses
                        if any(k in s.lower() for k in ("charge", "charg", "partstruck",
                                                        "evap", "export"))]
        phase_inventory(sessions)
    elif phase == "scan":
        phase_scan()
    else:
        print("unknown phase: %s" % phase)




# --------------------------------------------------------------------------
# Phase: scan  -- every session in which bcm_chg_done ever goes high, plus the
# SoC / vmax at the moment it latches.
# --------------------------------------------------------------------------

def phase_scan():
    res = q("SHOW TAG VALUES FROM signals WITH KEY=session WHERE vehicle='vtrux'")
    _c, vals = one(res)
    sessions = [v[1] for v in vals]
    print("%-40s %8s %8s %8s %8s %8s %8s" %
          ("session", "done@t_s", "soc", "vmax_mV", "vmin_mV", "chgmax", "ibat"))
    print("-" * 96)
    for s in sessions:
        r = q("SELECT MAX(\"bcm_chg_done\") FROM signals WHERE vehicle='vtrux' "
              "AND can_id='0x410' AND session='%s'" % s)
        _cc, v = one(r)
        if not v or not v[0][1]:
            continue
        # first time it is 1
        r2 = q("SELECT \"bcm_chg_done\", \"bcm_soc\" FROM signals WHERE vehicle='vtrux' "
               "AND can_id='0x410' AND session='%s' AND \"bcm_chg_done\" > 0 "
               "ORDER BY time ASC LIMIT 1" % s)
        _cc, v2 = one(r2)
        if not v2:
            continue
        t_done = v2[0][0]
        soc = v2[0][2]
        r3 = q("SELECT \"bcm_soc\" FROM signals WHERE vehicle='vtrux' AND can_id='0x410' "
               "AND session='%s' ORDER BY time ASC LIMIT 1" % s)
        _cc, v3 = one(r3)
        t0 = v3[0][0] if v3 else t_done

        def at(cid, f):
            rr = q("SELECT \"%s\" FROM signals WHERE vehicle='vtrux' AND can_id='%s' "
                   "AND session='%s' AND time <= %dms ORDER BY time DESC LIMIT 1"
                   % (f, cid, s, t_done))
            _c2, vv = one(rr)
            return vv[0][1] if vv else None

        vmax = at("0x430", "bcm_cell_vmax")
        vmin = at("0x430", "bcm_cell_vmin")
        chgmax = at("0x420", "bcm_chg_max")
        ibat = at("0x410", "bcm_ibat")

        def f(x, sc=1.0, n=1):
            return "-" if x is None else ("%.*f" % (n, x * sc))

        print("%-40s %8.0f %8s %8s %8s %8s %8s" %
              (s, (t_done - t0) / 1000.0, f(soc), f(vmax, 1000, 0), f(vmin, 1000, 0),
               f(chgmax), f(ibat)))


if __name__ == "__main__":
    main()
