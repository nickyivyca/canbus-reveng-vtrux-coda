"""Does the ECM's purge ramp-down lag the airflow collapse during wind-down?

This is the open mechanism left by `evap_duty_vs_engine_state.py`. Commanded
purge duty (PID 0x2E) is always LOW at the moment of a stall -- 12-25%, having
been 100% about 30 s earlier -- so a wide-open valve is not present when the
engine dies. But duty is a *valve command*, not a vapour flow. The same duty
passes far more vapour at high manifold vacuum, and the vapour matters only
relative to the air being ingested. During a wind-down both of those move
against the engine at once: manifold vacuum rises and airflow collapses. If the
ECM's duty ramp-down lags that, the purge fraction of the charge can spike at
exactly the marginal-idle point, which is where the stalls happen.

Neither fuel trim nor MAF is available -- fuel trim is not in GMW8762 at all,
and Mass_Air_Flow is defined (0x1EF) but never transmitted by this ECM (zero
points corpus-wide). What IS broadcast, and already in InfluxDB for every
session, is:

    Engine_Manifold_Absolute_Pressure   0x2C3, 0.5 kPa   (load / vacuum)
    Instantaneous_Fuel_Consumption_Rate 0x3D1, 0.025 L   (fuelling response)

Speed-density gives airflow ~ MAP * RPM, and purge vapour flow through the
valve ~ duty * sqrt(Patm - MAP), so

    purge_index = duty * sqrt(max(0, Patm - MAP)) / (MAP * RPM / 1e5)

is proportional to purge vapour per unit of ingested air. Absolute units are
meaningless; only the comparison between events is.

THE CONTROL IS THE POINT
    Describing what happens during a stall proves nothing on its own -- the
    ECM ramps purge down in every wind-down. The test is stalls against
    wind-downs that did NOT kill the engine. The 14 recovered dips (engine
    sagged below idle during purge, then recovered) are the natural control:
    same manoeuvre, different outcome.

Phases:
    1  build the event list from the cached series, fetch MAP + fuel rate
       windows from InfluxDB, cache to JSON
    2  compare stalls against recovered dips on the purge index and on the
       MAP-fall / duty-fall lag

Usage:  python3.13 projects/vtrux/notes/artifacts/evap_stall_map_fuelrate.py
"""

import sys
import os
import json
import math
import base64
import urllib.parse
import urllib.request

sys.path.insert(0, ".")

PHASES = {1, 2}

OUTDIR = "projects/vtrux/notes/artifacts"
SERIES_JSON = os.path.join(OUTDIR, "evap_duty_state_series.json")
WINDOWS_JSON = os.path.join(OUTDIR, "evap_stall_map_windows.json")
REPORT = os.path.join(OUTDIR, "evap_stall_map_fuelrate_report.txt")

INFLUX = "http://localhost:8086/query"
DB = "canbus-data"
VEHICLE = "vtrux"

PATM = 101.3        # kPa, sea-level reference for the vacuum term
PRE, POST = 90.0, 20.0     # window around each event, seconds


def influx(q, epoch="ms"):
    data = urllib.parse.urlencode({"db": DB, "q": q, "epoch": epoch})
    req = urllib.request.Request("%s?%s" % (INFLUX, data))
    req.add_header("Authorization",
                   "Basic " + base64.b64encode(b"claude:claude").decode())
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def series_of(resp):
    out = []
    for res in resp.get("results", []):
        for s in res.get("series", []):
            out.append(s)
    return out


def at(seq, t, default=None):
    v = default
    for tt, vv in seq:
        if tt > t:
            break
        v = vv
    return v


def clock(t):
    r = t % 86400
    return "%02d:%02d:%05.2f" % (r // 3600, (r % 3600) // 60, r % 60)


# ---------------------------------------------------------------- phase 1

def find_events(data):
    """Re-derive stalls and recovered dips from the cached raw-log series.

    Same criteria as evap_duty_vs_engine_state.py, restated here so this script
    stands alone: a stall is a sag of >=5 s below idle that ends in RPM ~0 and
    a restart; a dip is a sag below 500 rpm that recovers without dying.
    """
    events = []
    for sess in sorted(data):
        d = data[sess]
        rpm = d["rpm"]
        gen = d["gen"]
        if not rpm or not d["duty"]:
            continue
        gen_on = [t for t, o, n in gen if (n & 0x10) and not (o & 0x10)]

        i = 0
        while i < len(rpm):
            t, v = rpm[i]
            if v >= 100:
                i += 1
                continue
            hi = [x for x in rpm[:i] if t - 40 <= x[0] < t and x[1] >= 900]
            j = i
            while j + 1 < len(rpm) and rpm[j + 1][1] < 900:
                j += 1
            if hi:
                k = i - 1
                while k >= 0 and rpm[k][1] < 700:
                    k -= 1
                sag = t - rpm[k + 1][0] if k + 1 < i else 0.0
                restart = next((x - t for x in gen_on if t < x <= t + 60), None)
                if sag >= 5.0 and restart is not None:
                    events.append({"sess": sess, "t": t, "kind": "STALL",
                                   "sag": sag})
            i = j + 1

        i = 0
        while i < len(rpm):
            t, v = rpm[i]
            if v >= 500 or v < 100:
                i += 1
                continue
            j = i
            lo = v
            while j + 1 < len(rpm) and rpm[j + 1][1] < 900:
                j += 1
                lo = min(lo, rpm[j][1])
            hi = [x for x in rpm[:i] if t - 30 <= x[0] < t and x[1] >= 900]
            recovered = j + 1 < len(rpm) and rpm[j + 1][1] >= 900
            if hi and recovered and lo >= 100 and rpm[j][0] - t < 60:
                events.append({"sess": sess, "t": t, "kind": "dip",
                               "sag": rpm[j][0] - t})
            i = j + 1
    return events


def phase1():
    with open(SERIES_JSON) as f:
        data = json.load(f)
    events = find_events(data)
    print("phase 1: %d events (%d stalls, %d dips)"
          % (len(events),
             sum(1 for e in events if e["kind"] == "STALL"),
             sum(1 for e in events if e["kind"] == "dip")))

    # The cached raw-log series use the BUSMASTER header time base -- day of
    # month * 86400 plus time of day -- not Unix epoch, and possibly local
    # rather than UTC. InfluxDB stores real epoch. Align per session from the
    # engine-speed series both sides share, and verify the durations agree
    # before trusting the offset.
    offsets = {}
    for sess in sorted({e["sess"] for e in events}):
        raw = data[sess]["rpm"]
        # NOT FIRST()/LAST(): an ungrouped aggregate in InfluxQL returns epoch 0
        # as its timestamp, which silently produces a nonsense offset. Take the
        # actual boundary rows instead.
        ss = series_of(influx(
            "SELECT \"Engine_Speed\" FROM signals WHERE vehicle='%s' AND "
            "bus='obd' AND can_id='0x0C9' AND session='%s' ORDER BY time ASC "
            "LIMIT 1" % (VEHICLE, sess)))
        s2 = series_of(influx(
            "SELECT \"Engine_Speed\" FROM signals WHERE vehicle='%s' AND "
            "bus='obd' AND can_id='0x0C9' AND session='%s' ORDER BY time DESC "
            "LIMIT 1" % (VEHICLE, sess)))
        if not ss or not s2 or not raw:
            continue
        inf_first = ss[0]["values"][0][0] / 1000.0
        inf_last = s2[0]["values"][0][0] / 1000.0
        off = inf_first - raw[0][0]
        drift = (inf_last - inf_first) - (raw[-1][0] - raw[0][0])
        offsets[sess] = off
        print("  align %-26s offset %+.1f s, duration drift %+.1f s%s"
              % (sess, off, drift, "  <-- CHECK" if abs(drift) > 5 else ""))

    out = []
    for i, e in enumerate(events, 1):
        sess, t = e["sess"], e["t"]
        off = offsets.get(sess)
        if off is None:
            print("  skip %s -- no time alignment" % sess)
            continue
        te = t + off
        lo, hi = int((te - PRE) * 1000), int((te + POST) * 1000)
        w = {}
        for name, cid, field in (
                ("map", "0x2C3", "Engine_Manifold_Absolute_Pressure"),
                ("fuel", "0x3D1", "Instantaneous_Fuel_Consumption_Rate"),
                # engine speed is fetched purely to validate the alignment:
                # it exists in BOTH sources, so disagreement in the window
                # means the per-session offset does not hold there
                ("irpm", "0x0C9", "Engine_Speed")):
            ss = series_of(influx(
                "SELECT \"%s\" AS v FROM signals WHERE vehicle='%s' AND "
                "bus='obd' AND can_id='%s' AND session='%s' AND time>=%dms "
                "AND time<=%dms" % (field, VEHICLE, cid, sess, lo, hi)))
            # bring Influx samples back onto the raw-log time base so every
            # series in the window shares one clock
            w[name] = [(v[0] / 1000.0 - off, v[1]) for v in ss[0]["values"]
                       if v[1] is not None] if ss else []
        d = data[sess]
        w["duty"] = [(x, v) for x, v in d["duty"] if t - PRE <= x <= t + POST]
        w["rpm"] = [(x, v) for x, v in d["rpm"] if t - PRE <= x <= t + POST]
        w["tps"] = [(x, v) for x, v in d["tps"] if t - PRE <= x <= t + POST]
        # alignment residual: compare the two independent engine-speed series
        res = []
        for tt, vv in w["irpm"]:
            r = at(w["rpm"], tt)
            if r is not None:
                res.append(abs(r - vv))
        e["align_err"] = (sum(res) / len(res)) if res else None
        e["w"] = w
        out.append(e)
        print("  [%2d/%2d] %-26s %s %-6s map=%d fuel=%d duty=%d rpm_err=%s"
              % (i, len(events), sess, clock(t), e["kind"],
                 len(w["map"]), len(w["fuel"]), len(w["duty"]),
                 "n/a" if e["align_err"] is None else "%.0f" % e["align_err"]),
              flush=True)

    with open(WINDOWS_JSON, "w") as f:
        json.dump(out, f)
    print("  wrote %s" % os.path.basename(WINDOWS_JSON))


# ---------------------------------------------------------------- phase 2

OUT = []


def em(s=""):
    OUT.append(s)
    print(s)


def purge_index(duty, mapkpa, rpm):
    if not duty or not mapkpa or not rpm or mapkpa <= 0 or rpm <= 0:
        return None
    vac = max(0.0, PATM - mapkpa)
    return duty * math.sqrt(vac) / (mapkpa * rpm / 1e5)


def fall_time(seq, frac=0.5):
    """Time at which a series first drops below frac of its window maximum."""
    if not seq:
        return None
    mx = max(v for _, v in seq)
    if mx <= 0:
        return None
    for t, v in seq:
        if v <= frac * mx:
            return t
    return None


def phase2():
    with open(WINDOWS_JSON) as f:
        events = json.load(f)

    em("=" * 86)
    em("MAP and fuel rate through stalls vs recovered dips")
    em("=" * 86)
    em("\npurge_index = duty * sqrt(%.1f - MAP) / (MAP * RPM / 1e5)" % PATM)
    em("Proportional to purge vapour per unit ingested air. Arbitrary units;")
    em("only the stall-vs-dip comparison is meaningful.")

    em("\n--- Per event, at the moment of the collapse/low point ---")
    em("%-26s %10s %-6s %7s %7s %7s %8s %9s %9s"
       % ("session", "time", "kind", "rpm", "MAP", "duty%", "fuel", "p_index",
          "lag_s"))
    rows = []
    for e in events:
        w, t = e["w"], e["t"]
        rpm = at(w["rpm"], t)
        mp = at(w["map"], t)
        du = at(w["duty"], t)
        fu = at(w["fuel"], t)
        pi = purge_index(du, mp, rpm)
        # lag: MAP falls to half its window max, duty follows
        t_map = fall_time(w["map"])
        t_duty = fall_time(w["duty"])
        lag = (t_duty - t_map) if (t_map and t_duty) else None
        rows.append({"kind": e["kind"], "pi": pi, "lag": lag, "map": mp,
                     "duty": du, "rpm": rpm, "fuel": fu, "sess": e["sess"],
                     "t": t})
        em("%-26s %10s %-6s %7s %7s %7s %8s %9s %9s"
           % (e["sess"], clock(t), e["kind"],
              "n/a" if rpm is None else "%.0f" % rpm,
              "n/a" if mp is None else "%.1f" % mp,
              "n/a" if du is None else "%.1f" % du,
              "n/a" if fu is None else "%.2f" % fu,
              "n/a" if pi is None else "%.1f" % pi,
              "n/a" if lag is None else "%+.1f" % lag))

    def stats(key, kind):
        v = sorted(r[key] for r in rows
                   if r["kind"] == kind and r.get(key) is not None)
        if not v:
            return None
        return v[0], v[len(v) // 2], v[-1], len(v)

    em("\n--- Comparison ---")
    em("%-14s %8s %10s %10s %10s" % ("metric", "kind", "min", "median", "max"))
    for key, label in (("pi", "purge_index"), ("map", "MAP kPa"),
                       ("duty", "duty %"), ("rpm", "rpm"),
                       ("fuel", "fuel rate"), ("lag", "MAP->duty lag")):
        for kind in ("STALL", "dip"):
            s = stats(key, kind)
            if s:
                em("%-14s %8s %10.2f %10.2f %10.2f   (n=%d)"
                   % (label, kind, s[0], s[1], s[2], s[3]))
        em()

    # ---- RPM-matched comparison.
    #
    # Comparing "at the moment of the event" is invalid: for a stall that
    # moment is RPM ~0, where the engine is already dead, fuel rate is 0 and
    # the purge index divides by ~0; for a dip it is RPM ~500 with the engine
    # still running. The two populations must be sampled at the SAME point in
    # the manoeuvre. Both pass through the same descending RPM levels -- stalls
    # continue through them to zero, dips turn round -- so evaluate each event
    # where its RPM first falls through each level.
    LEVELS = (700, 600, 500, 400, 300, 200)

    def crossing(w, level):
        prev = None
        for t, v in w["rpm"]:
            if prev is not None and prev >= level > v:
                return t
            prev = v
        return None

    em("\n--- RPM-matched: state as each event descends through a given RPM ---")
    em("%6s %-6s %4s %8s %8s %8s %10s"
       % ("rpm", "kind", "n", "MAP", "duty%", "fuel", "p_index"))
    matched = {}
    for level in LEVELS:
        for kind in ("STALL", "dip"):
            vals = {"map": [], "duty": [], "fuel": [], "pi": []}
            for e in events:
                if e["kind"] != kind:
                    continue
                w = e["w"]
                tc = crossing(w, level)
                if tc is None:
                    continue
                mp, du = at(w["map"], tc), at(w["duty"], tc)
                fu = at(w["fuel"], tc)
                pi = purge_index(du, mp, level)
                if mp is not None:
                    vals["map"].append(mp)
                if du is not None:
                    vals["duty"].append(du)
                if fu is not None:
                    vals["fuel"].append(fu)
                if pi is not None:
                    vals["pi"].append(pi)
            if not vals["map"]:
                continue
            med = lambda a: sorted(a)[len(a) // 2] if a else float("nan")
            matched[(level, kind)] = vals
            em("%6d %-6s %4d %8.1f %8.1f %8.2f %10.0f"
               % (level, kind, len(vals["map"]), med(vals["map"]),
                  med(vals["duty"]), med(vals["fuel"]), med(vals["pi"])))
        em()

    # ---- the controlled version of the same comparison.
    #
    # Some dips happen in windows where the purge valve was never open (the
    # warm-up sags before the ECM first opens it). Including those makes the
    # medians separate trivially -- it compares purge-on against purge-off, not
    # stall against recovery. Restrict to events where commanded duty exceeded
    # 50% somewhere in the window, and list every value rather than a median,
    # because with three stalls a median hides more than it shows.
    em("\n--- Controlled: duty at matched rpm, purge-on events only ---")
    for kind in ("STALL", "dip"):
        for level in (700, 600, 500):
            vals = []
            for e in events:
                if e["kind"] != kind:
                    continue
                w = e["w"]
                if max([v for _, v in w["duty"]] or [0]) <= 50:
                    continue
                tc = crossing(w, level)
                if tc is None:
                    continue
                d = at(w["duty"], tc)
                if d is not None:
                    vals.append(d)
            if vals:
                em("   %-6s duty at %d rpm: n=%-3d %s"
                   % (kind, level, len(vals),
                      " ".join("%.0f" % v for v in sorted(vals))))
        em()

    em("   Read down each RPM level: if purge fraction decided the outcome,")
    em("   the STALL row should sit clearly above the dip row at the same rpm.")
    for level in LEVELS:
        a = matched.get((level, "STALL"))
        b = matched.get((level, "dip"))
        if not a or not b or not a["pi"] or not b["pi"]:
            continue
        sa = sorted(a["pi"])
        sb = sorted(b["pi"])
        sep = "STALL above" if sa[0] > sb[-1] else (
            "dip above" if sb[0] > sa[-1] else "OVERLAP")
        em("      %4d rpm: stall %.0f-%.0f (n=%d) vs dip %.0f-%.0f (n=%d) -> %s"
           % (level, sa[0], sa[-1], len(sa), sb[0], sb[-1], len(sb), sep))

    ps = stats("pi", "STALL")
    pd = stats("pi", "dip")
    if False and ps and pd:
        em("Purge index: stalls median %.1f vs dips median %.1f -- ratio %.2fx"
           % (ps[1], pd[1], ps[1] / pd[1] if pd[1] else float("nan")))
        if ps[0] > pd[2]:
            em("   Stall range sits entirely ABOVE the dip range: separates cleanly.")
        elif ps[2] < pd[0]:
            em("   Stall range sits entirely BELOW the dip range.")
        else:
            em("   Ranges OVERLAP -- the index does not separate the two outcomes,")
            em("   so purge fraction is not what decides whether the engine dies.")

    # trajectory of the deepest stall, for the record
    st = [e for e in events if e["kind"] == "STALL"]
    for e in st:
        w, t = e["w"], e["t"]
        em("\n--- Trajectory: %s %s ---" % (e["sess"], clock(t)))
        em("%8s %8s %8s %8s %8s %8s %9s"
           % ("t_rel", "rpm", "MAP", "duty%", "tps%", "fuel", "p_index"))
        marks = [t - x for x in (75, 60, 45, 30, 20, 15, 10, 7, 5, 3, 2, 1, 0)]
        for tt in marks:
            rpm = at(w["rpm"], tt)
            mp = at(w["map"], tt)
            du = at(w["duty"], tt)
            fu = at(w["fuel"], tt)
            pi = purge_index(du, mp, rpm)
            em("%8.0f %8s %8s %8s %8s %8s %9s"
               % (tt - t,
                  "n/a" if rpm is None else "%.0f" % rpm,
                  "n/a" if mp is None else "%.1f" % mp,
                  "n/a" if du is None else "%.1f" % du,
                  "n/a" if at(w["tps"], tt) is None else "%.1f" % at(w["tps"], tt),
                  "n/a" if fu is None else "%.2f" % fu,
                  "n/a" if pi is None else "%.1f" % pi))

    with open(REPORT, "w") as f:
        f.write("\n".join(OUT) + "\n")
    print("\nwrote %s" % os.path.basename(REPORT))


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--phases" in argv:
        PHASES = {int(x) for x in argv[argv.index("--phases") + 1].split(",")}
    if 1 in PHASES:
        phase1()
    if 2 in PHASES:
        phase2()
