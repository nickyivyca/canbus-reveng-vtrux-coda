"""Full evap purge history for the Vtrux, from InfluxDB + raw-log OBD.

Context: `evap_manual_start_20260815.py` established, on two sessions, that

  * the ECM's own purge-solenoid command is readable as OBD-II mode 01 PID 0x2E
    (Commanded Evaporative Purge), polled on the OBD bus while the engine runs;
  * `vcm_evap_counter` starts some seconds AFTER the ECM actually opens the
    valve, so the VCM counter is a lagging proxy for the purge, not the purge;
  * two candidate rules fit both sessions -- a ~204 s fixed delay from engine
    start to valve-open, and counter-start ~3.4 s after commanded purge first
    crosses ~25 %.

Two data points is not a history. This script tests those rules against every
purge the corpus contains.

DATA SOURCE SPLIT (this is the reason for the phase layout)
    InfluxDB holds `vcm_evap_active` / `vcm_evap_counter` for the whole corpus,
    decoded against the DBC -- so the purge *history* is one query per session
    rather than a re-parse of 85 GB. It does NOT hold PID 0x2E: `0x7xx`
    diagnostic traffic is excluded from upload by policy (data-sources.md S3,
    "What is not in there"), and 0x2E has no DBC entry to decode against.
    So: Influx for which/when/how-far, raw logs for the ECM duty.

    Influx caveat that matters here: points are written on change plus a 1 s
    heartbeat. Values are exact and forward-fill exactly, so counter levels and
    transition times are trustworthy to ~1 s. Frame counts and rates are not.
    Every rate in this script is therefore computed from value deltas over
    wall-clock, never from point counts.

Phases (toggle with --phases):
    1  Influx: per-session evap summary (counter min/max, active, time bounds)
    2  Influx: full counter/active series for every session that shows purge
       activity; detect completion events and terminal counter values
    3  Raw logs: PID 0x2E + engine-start + coolant for every Android session
       that contains a purge onset; test both candidate rules
    4  Synthesis: the cross-session tables

Usage:  python3.13 projects/vtrux/notes/artifacts/evap_purge_history.py
        python3.13 ... .py --phases 3,4
"""

import sys
import os
import re
import csv
import glob
import json
import urllib.parse
import urllib.request
import subprocess
import multiprocessing as mp
from collections import defaultdict

sys.path.insert(0, ".")

PHASES = {1, 2, 3, 4}

OUTDIR = "projects/vtrux/notes/artifacts"
LOGDIR = "../../CANLogs/VtruxLogs"
GMLAN_DBC = "projects/vtrux/GMW8762_PPEI_GMLAN.dbc"

INFLUX = "http://localhost:8086/query"
INFLUX_AUTH = ("<influx-user>", "<influx-password>")
DB = "canbus-data"
VEHICLE = "vtrux"
ID_649 = "0x649"

SUMMARY_JSON = os.path.join(OUTDIR, "evap_history_summary.json")
CYCLES_JSON = os.path.join(OUTDIR, "evap_history_cycles.json")
ONSET_JSON = os.path.join(OUTDIR, "evap_history_onsets.json")
REPORT = os.path.join(OUTDIR, "evap_history_report.txt")

NWORKERS = 8


# ---------------------------------------------------------------- influx

def influx(q, epoch="ms"):
    """One InfluxQL query. Always scoped by vehicle+can_id to bound the scan."""
    data = urllib.parse.urlencode({"db": DB, "q": q, "epoch": epoch})
    req = urllib.request.Request("%s?%s" % (INFLUX, data))
    auth = "%s:%s" % INFLUX_AUTH
    import base64
    req.add_header("Authorization",
                   "Basic " + base64.b64encode(auth.encode()).decode())
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def series_of(resp):
    out = []
    for res in resp.get("results", []):
        for s in res.get("series", []):
            out.append(s)
    return out


# ---------------------------------------------------------------- phase 1

def phase1():
    print("phase 1: per-session evap summary from InfluxDB")
    q = ('SELECT MAX("vcm_evap_counter") AS mx, MIN("vcm_evap_counter") AS mn, '
         'MAX("vcm_evap_active") AS amx, MIN("vcm_evap_active") AS amn, '
         'COUNT("vcm_evap_counter") AS n '
         "FROM signals WHERE vehicle='%s' AND can_id='%s' GROUP BY session"
         % (VEHICLE, ID_649))
    rows = {}
    for s in series_of(influx(q)):
        sess = s["tags"]["session"]
        cols = s["columns"]
        v = dict(zip(cols, s["values"][0]))
        rows[sess] = {"cmax": v.get("mx"), "cmin": v.get("mn"),
                      "amax": v.get("amx"), "amin": v.get("amn"),
                      "n": v.get("n")}

    # time bounds, one query for all sessions
    q2 = ('SELECT FIRST("vcm_evap_counter") AS f, LAST("vcm_evap_counter") AS l '
          "FROM signals WHERE vehicle='%s' AND can_id='%s' GROUP BY session"
          % (VEHICLE, ID_649))
    for s in series_of(influx(q2)):
        sess = s["tags"]["session"]
        if sess in rows:
            rows[sess]["t_first"] = s["values"][0][0]

    # LAST() carries its own timestamp only via a separate ordered query
    for sess in list(rows):
        q3 = ('SELECT "vcm_evap_counter" FROM signals '
              "WHERE vehicle='%s' AND can_id='%s' AND session='%s' "
              "ORDER BY time DESC LIMIT 1" % (VEHICLE, ID_649, sess))
        ss = series_of(influx(q3))
        rows[sess]["t_last"] = ss[0]["values"][0][0] if ss else None

    with open(SUMMARY_JSON, "w") as f:
        json.dump(rows, f, indent=1, sort_keys=True)

    act = [k for k, v in rows.items() if (v["cmax"] or 0) > 0]
    print("  %d sessions carry 0x649; %d show purge activity (counter > 0)"
          % (len(rows), len(act)))
    print("  wrote %s" % os.path.basename(SUMMARY_JSON))


# ---------------------------------------------------------------- phase 2

def fetch_series(sess):
    """Full counter/active series for one session, from Influx."""
    q = ('SELECT "vcm_evap_counter" AS c, "vcm_evap_active" AS a '
         "FROM signals WHERE vehicle='%s' AND can_id='%s' AND session='%s'"
         % (VEHICLE, ID_649, sess))
    ss = series_of(influx(q))
    if not ss:
        return []
    cols = ss[0]["columns"]
    ic, ia = cols.index("c"), cols.index("a")
    out = []
    for v in ss[0]["values"]:
        if v[ic] is None and v[ia] is None:
            continue
        out.append((v[0], v[ic], v[ia]))
    return out


def phase2():
    with open(SUMMARY_JSON) as f:
        summary = json.load(f)
    active = sorted(k for k, v in summary.items() if (v["cmax"] or 0) > 0)
    print("phase 2: pulling counter series for %d sessions" % len(active))

    cycles = {}
    for i, sess in enumerate(active, 1):
        rows = fetch_series(sess)
        # forward-fill: Influx stores on change, so a row may carry only one of
        # the two fields. Levels are exact once filled.
        c = a = None
        filled = []
        for t, cc, aa in rows:
            if cc is not None:
                c = int(cc)
            if aa is not None:
                a = int(aa)
            if c is not None:
                filled.append((t, c, a))

        # events of interest
        first_nz = next((r for r in filled if r[1] > 0), None)
        completions = []
        for j in range(1, len(filled)):
            pt, pc, pa = filled[j - 1]
            t, cc, aa = filled[j]
            # a completion is the counter collapsing from a high value to 0
            if pc >= 100 and cc == 0:
                completions.append({"t": t, "terminal": pc,
                                    "active_before": pa, "active_after": aa})
        cycles[sess] = {
            "n_points": len(filled),
            "t_start": filled[0][0] if filled else None,
            "t_end": filled[-1][0] if filled else None,
            "cmin": min(r[1] for r in filled) if filled else None,
            "cmax": max(r[1] for r in filled) if filled else None,
            "first_nonzero_t": first_nz[0] if first_nz else None,
            "first_nonzero_c": first_nz[1] if first_nz else None,
            "completions": completions,
        }
        print("  [%2d/%2d] %-34s pts=%-6d max=%-5s completions=%d"
              % (i, len(active), sess, len(filled),
                 cycles[sess]["cmax"], len(completions)), flush=True)

    with open(CYCLES_JSON, "w") as f:
        json.dump(cycles, f, indent=1, sort_keys=True)
    print("  wrote %s" % os.path.basename(CYCLES_JSON))


# ---------------------------------------------------------------- phase 3

HDR = re.compile(r"START DATE AND TIME (\d+):(\d+):(\d+) (\d+):(\d+):(\d+):(\d+)")
ID_600 = 0x600
ID_63C = 0x63C
ID_4C1 = 0x4C1
GREP3 = r" (0x7E8|0x600|0x63C|0x4C1|0x649) "

_GM = None


def _gm():
    global _GM
    if _GM is None:
        import cantools
        _GM = cantools.database.load_file(GMLAN_DBC)
    return _GM


def header_start(path):
    with open(path, "r", errors="replace") as f:
        for _ in range(80):
            line = f.readline()
            if not line:
                break
            m = HDR.search(line)
            if m:
                dd, mo, yy, hh, mm, ss, ms = (int(x) for x in m.groups())
                return dd * 86400 + hh * 3600 + mm * 60 + ss + ms / 1000.0
    return None


def scan_onset_chunk(path):
    """Per-chunk: PID 0x2E samples, GEN_ON/OFF edges, evap counter, coolant."""
    base = header_start(path)
    if base is None:
        return None
    gm = _gm()

    purge = []          # (t, duty_pct)
    genedges = []       # (t, old, new)
    counter = []        # (t, evap_counter)
    ect = []            # (t, degC)
    rpm = []            # (t, 0x63C B6)
    prev600 = None
    prev_ect = None
    prev_cnt = None

    p = subprocess.Popen(["grep", "-E", GREP3, path],
                         stdout=subprocess.PIPE, text=True, errors="replace")
    for line in p.stdout:
        f = line.split()
        if len(f) < 7:
            continue
        try:
            ts = f[0].split(":")
            t = (base + int(ts[0]) * 3600 + int(ts[1]) * 60
                 + int(ts[2]) + int(ts[3]) / 10000.0)
            cid = int(f[3], 16)
            data = bytes(int(x, 16) for x in f[6:])
        except (ValueError, IndexError):
            continue

        if cid == 0x7E8:
            if len(data) >= 4 and data[1] == 0x41 and data[2] == 0x2E:
                purge.append((round(t, 3), data[3] * 100.0 / 255.0))
        elif cid == ID_600 and len(data) >= 4:
            if prev600 is not None and (data[0] & 0x10) != (prev600 & 0x10):
                genedges.append((round(t, 3), prev600, data[0]))
            prev600 = data[0]
        elif cid == ID_63C and len(data) >= 7:
            rpm.append((round(t, 1), data[6]))
        elif cid == ID_4C1 and len(data) >= 8:
            try:
                v = gm.decode_message(
                    ID_4C1, data,
                    decode_choices=False)["Engine_Coolant_Temperature"]
            except Exception:
                v = None
            if v is not None and v != prev_ect:
                ect.append((round(t, 1), v))
                prev_ect = v
        elif cid == 0x649 and len(data) >= 8:
            c = ((data[2] & 0x0F) << 8) | data[3]
            if c != prev_cnt:
                counter.append((round(t, 3), c))
                prev_cnt = c
    p.stdout.close()
    p.wait()
    return {"purge": purge, "gen": genedges, "counter": counter,
            "ect": ect, "rpm": rpm[::20]}


def android_sessions_with_purge():
    """Android sessions whose Influx record shows purge activity."""
    with open(CYCLES_JSON) as f:
        cycles = json.load(f)
    out = []
    for sess, c in cycles.items():
        if not re.match(r"^vtrux_\d{8}_\d{6}$", sess):
            continue
        if not c["first_nonzero_t"]:
            continue
        if glob.glob(os.path.join(LOGDIR, "%s_T*.log" % sess)):
            out.append(sess)
    return sorted(out)


def phase3():
    sessions = android_sessions_with_purge()
    print("phase 3: OBD purge-duty scan over %d Android purge sessions"
          % len(sessions))
    onsets = {}
    for i, sess in enumerate(sessions, 1):
        paths = sorted(glob.glob(os.path.join(LOGDIR, "%s_T*.log" % sess)),
                       key=lambda p: int(re.search(r"_T(\d+)\.log$", p).group(1)))
        with mp.Pool(min(NWORKERS, max(1, len(paths)))) as pool:
            parts = [r for r in pool.map(scan_onset_chunk, paths) if r]
        agg = {k: sorted(v for part in parts for v in part[k])
               for k in ("purge", "gen", "counter", "ect", "rpm")}
        onsets[sess] = agg
        print("  [%2d/%2d] %-28s 0x2E=%-6d gen_edges=%d counter_pts=%d"
              % (i, len(sessions), sess, len(agg["purge"]),
                 len(agg["gen"]), len(agg["counter"])), flush=True)

    with open(ONSET_JSON, "w") as f:
        json.dump(onsets, f)
    print("  wrote %s" % os.path.basename(ONSET_JSON))


# ---------------------------------------------------------------- phase 4

DUTY_THRESH = 25.0


def clock(t):
    r = t % 86400
    return "%02d:%02d:%05.2f" % (r // 3600, (r % 3600) // 60, r % 60)


def phase4():
    with open(ONSET_JSON) as f:
        onsets = json.load(f)
    with open(CYCLES_JSON) as f:
        cycles = json.load(f)
    with open(SUMMARY_JSON) as f:
        summary = json.load(f)

    out = []

    def emit(s=""):
        out.append(s)
        print(s)

    emit("=" * 84)
    emit("Vtrux evap purge history -- InfluxDB corpus + OBD PID 0x2E")
    emit("=" * 84)

    # ---- A. terminal counter values across every completion in the corpus
    emit("\n--- A. Completion events (counter collapses to 0) ---")
    emit("%-34s %-14s %10s %8s" % ("session", "time", "terminal", "flag"))
    terms = []
    for sess in sorted(cycles):
        for c in cycles[sess]["completions"]:
            terms.append(c["terminal"])
            emit("%-34s %-14s %10d %4s->%s"
                 % (sess, clock(c["t"] / 1000.0), c["terminal"],
                    c["active_before"], c["active_after"]))
    if terms:
        emit("\n   %d completions; terminal values: %s"
             % (len(terms), sorted(set(terms))))
        if len(set(terms)) == 1:
            emit("   -> the terminal count is CONSTANT at %d across the corpus."
                 % terms[0])
            emit("      That contradicts the current DBC comment, which says the")
            emit("      terminal value varies (901/901/856) and so cannot drive a")
            emit("      progress bar. Re-check before acting on it.")
        else:
            emit("   -> terminal count varies; spread %d..%d"
                 % (min(terms), max(terms)))

    # ---- B. max counter reached per session, purge sessions only
    emit("\n--- B. Purge activity by session ---")
    emit("%-34s %8s %8s %9s" % ("session", "cmin", "cmax", "completions"))
    for sess in sorted(cycles, key=lambda s: -(cycles[s]["cmax"] or 0)):
        c = cycles[sess]
        emit("%-34s %8s %8s %9d"
             % (sess, c["cmin"], c["cmax"], len(c["completions"])))

    # ---- C. the two candidate rules, tested on every onset with OBD data
    #
    # A session only supplies a usable onset if the transition happens INSIDE
    # the log. Most captures start with the truck already mid-cycle, where
    # "first counter > 0" is just the first frame and "first duty > 0" is the
    # middle of a purge already under way. Comparing those produces negative
    # lags, which is the tell. Each anchor below is therefore required to be a
    # genuine edge, not merely the earliest sample.
    emit("\n--- C. Engine start -> ECM valve open -> VCM counter start ---")
    emit("(only sessions where the counter genuinely rises from 0 in-log)")
    emit("%-24s %11s %11s %11s %8s %8s %8s %8s"
         % ("session", "gen_on", "valve_open", "cnt_start",
            "eng->vlv", "vlv->cnt", "x25->cnt", "ect@vlv"))
    rows, skipped = [], []
    for sess in sorted(onsets):
        d = onsets[sess]
        purge = sorted(d["purge"])
        counter = sorted(d["counter"])
        if not purge or not counter:
            skipped.append((sess, "no 0x2E or no counter"))
            continue
        if counter[0][1] != 0:
            skipped.append((sess, "counter already %d at log start"
                            % counter[0][1]))
            continue
        t_cnt = next((t for t, c in counter if c > 0), None)
        if t_cnt is None:
            skipped.append((sess, "counter never leaves 0"))
            continue

        # valve open = start of the contiguous nonzero-duty run that is live at
        # t_cnt (walk back from t_cnt through samples that stayed above zero)
        idx = [i for i, (t, v) in enumerate(purge) if t <= t_cnt]
        if not idx:
            skipped.append((sess, "no 0x2E before counter start"))
            continue
        i = idx[-1]
        if purge[i][1] <= 0:
            skipped.append((sess, "duty was zero when the counter started"))
            continue
        while i > 0 and purge[i - 1][1] > 0:
            i -= 1
        t_valve = purge[i][0]
        if i == 0:
            skipped.append((sess, "purge run starts at log start"))
            continue

        # 25% crossing inside that same run
        t_cross = next((t for t, v in purge[i:] if v >= DUTY_THRESH and t <= t_cnt),
                       None)

        # engine start = last GEN_ON before the valve opened, with no GEN_OFF
        # in between
        edges = [(t, o, n) for t, o, n in d["gen"] if t <= t_valve]
        t_gen = None
        if edges:
            last_t, last_o, last_n = edges[-1]
            if (last_n & 0x10) and not (last_o & 0x10):
                t_gen = last_t
        ect_at = None
        for t, v in d["ect"]:
            if t <= t_valve:
                ect_at = v

        rows.append({"sess": sess, "gen": t_gen, "valve": t_valve,
                     "cnt": t_cnt, "ect": ect_at, "cross": t_cross})
        emit("%-24s %11s %11s %11s %8s %8.1f %8s %8s"
             % (sess,
                "n/a" if t_gen is None else clock(t_gen),
                clock(t_valve), clock(t_cnt),
                "n/a" if t_gen is None else "%.1f" % (t_valve - t_gen),
                t_cnt - t_valve,
                "n/a" if t_cross is None else "%.1f" % (t_cnt - t_cross),
                "n/a" if ect_at is None else "%.0f" % ect_at))

    if skipped:
        emit("\n   excluded (%d):" % len(skipped))
        for s, why in skipped:
            emit("      %-26s %s" % (s, why))

    lags = sorted(r["valve"] - r["gen"] for r in rows if r["gen"] is not None)
    emit("\n   RULE 1 -- fixed delay from engine start to valve open:")
    if lags:
        emit("      n=%d  values: %s"
             % (len(lags), " ".join("%.0f" % x for x in lags)))
        emit("      min=%.0fs  median=%.0fs  max=%.0fs  spread=%.0fs"
             % (lags[0], lags[len(lags) // 2], lags[-1], lags[-1] - lags[0]))
        ects = sorted(r["ect"] for r in rows
                      if r["ect"] is not None and r["gen"] is not None)
        if ects:
            emit("      coolant temp at valve open, same sessions: %s C"
                 % " ".join("%.0f" % e for e in ects))
            emit("      -> a wide coolant spread against a tight delay favours a")
            emit("         timer; the reverse would favour a temperature gate.")
    else:
        emit("      no session captured both an engine start and its valve open")

    offs = sorted(r["cnt"] - r["cross"] for r in rows if r["cross"] is not None)
    emit("\n   RULE 2 -- counter starts a fixed lag after duty crosses %.0f%%:"
         % DUTY_THRESH)
    if offs:
        emit("      n=%d  values: %s"
             % (len(offs), " ".join("%.1f" % x for x in offs)))
        emit("      min=%.1fs  median=%.1fs  max=%.1fs"
             % (offs[0], offs[len(offs) // 2], offs[-1]))
    else:
        emit("      no usable crossing")

    vlv = sorted(r["cnt"] - r["valve"] for r in rows)
    emit("\n   For contrast -- counter start measured from VALVE OPEN instead:")
    emit("      n=%d  values: %s" % (len(vlv), " ".join("%.1f" % x for x in vlv)))
    emit("      spread %.1fs vs %.1fs for the 25%%-crossing anchor"
         % (vlv[-1] - vlv[0] if vlv else 0, offs[-1] - offs[0] if offs else 0))

    with open(REPORT, "w") as f:
        f.write("\n".join(out) + "\n")
    print("\nwrote %s" % os.path.basename(REPORT))


# ---------------------------------------------------------------- phase 5

SWEEP_TXT = os.path.join(OUTDIR, "evap_history_duty_gate.txt")

# duty level above which vcm_evap_counter advances, located by the 5a sweep
GATE = 30


def onset_events(d):
    """Every 0 -> >0 transition in commanded purge duty, with its run extent."""
    purge = sorted(d["purge"])
    runs = []
    i = 0
    while i < len(purge):
        if purge[i][1] > 0 and (i == 0 or purge[i - 1][1] <= 0):
            j = i
            while j + 1 < len(purge) and purge[j + 1][1] > 0:
                j += 1
            if i > 0:                      # require a real edge, not log start
                runs.append((i, j))
            i = j + 1
        else:
            i += 1
    return purge, runs


def phase5():
    with open(ONSET_JSON) as f:
        onsets = json.load(f)

    out = []

    def emit(s=""):
        out.append(s)
        print(s)

    emit("=" * 84)
    emit("Is vcm_evap_counter gated on the ECM's commanded purge duty?")
    emit("=" * 84)

    # ---- 5a. threshold sweep: which duty level best predicts counter start?
    #
    # If the counter really is triggered by duty crossing some level, the lag
    # from that crossing to the counter start should be near-constant AT the
    # right level and scattered elsewhere. Minimising the spread over candidate
    # thresholds locates the level without assuming it.
    # Same strict filter as phase 4C: the counter must rise from 0 in-log, and
    # the purge run that is live at that moment must have started in-log too.
    # Otherwise "first crossing" is just wherever the log happened to open.
    starts = []
    for sess in sorted(onsets):
        d = onsets[sess]
        counter = sorted(d["counter"])
        purge = sorted(d["purge"])
        if not counter or not purge or counter[0][1] != 0:
            continue
        t_cnt = next((t for t, c in counter if c > 0), None)
        if t_cnt is None:
            continue
        idx = [i for i, (t, v) in enumerate(purge) if t <= t_cnt]
        if not idx:
            continue
        i = idx[-1]
        if purge[i][1] <= 0:
            continue
        while i > 0 and purge[i - 1][1] > 0:
            i -= 1
        if i == 0:
            continue                    # run began before the log did
        starts.append((sess, t_cnt, purge[i:]))

    emit("\n--- 5a. Duty-threshold sweep (%d clean in-log counter starts) ---"
         % len(starts))
    emit("   sessions: %s" % ", ".join(s for s, _, _ in starts))
    emit("%8s %6s %9s %9s %9s   %s"
         % ("thresh%", "n", "min_lag", "median", "max_lag", "spread"))
    best = None
    for th in [2, 5, 8, 10, 12, 15, 18, 20, 22, 25, 28, 30, 35, 40, 50, 60]:
        lags = []
        for sess, t_cnt, run in starts:
            cross = next((t for t, v in run if v >= th and t <= t_cnt), None)
            if cross is not None:
                lags.append(t_cnt - cross)
        if not lags:
            continue
        lags.sort()
        spread = lags[-1] - lags[0]
        emit("%8d %6d %9.1f %9.1f %9.1f   %.1f%s"
             % (th, len(lags), lags[0], lags[len(lags) // 2], lags[-1], spread,
                "" if len(lags) == len(starts) else "   (partial)"))
        # only a threshold every onset reaches can be the trigger
        if len(lags) == len(starts) and (best is None or spread < best[1]):
            best = (th, spread, lags[len(lags) // 2])
    if best:
        emit("\n   tightest alignment: duty >= %d%%, spread %.1f s, median lag %.1f s"
             % best)

    # ---- 5b. FIRST valve-open after each engine start.
    #
    # Rule 1 is a claim about how long the ECM waits after the engine starts
    # before it first opens the valve. Later re-openings within the same engine
    # run are the purge cycling, not a fresh wait, so only the first opening
    # after each GEN_ON edge counts. Including the rest inflates n with
    # measurements of a different quantity.
    emit("\n--- 5b. FIRST valve-open after each engine start ---")
    emit("%-24s %11s %11s %9s %8s %8s %9s"
         % ("session", "gen_on", "valve_open", "delay_s", "ect@gen", "ect@vlv",
            "cnt@gen"))
    delays = []
    for sess in sorted(onsets):
        d = onsets[sess]
        purge, runs = onset_events(d)
        counter = sorted(d["counter"])
        gen_on = [t for t, o, n in d["gen"] if (n & 0x10) and not (o & 0x10)]
        gen_off = [t for t, o, n in d["gen"] if (o & 0x10) and not (n & 0x10)]
        for t_gen in gen_on:
            nxt_off = next((t for t in gen_off if t > t_gen), float("inf"))
            first = next((purge[i][0] for i, j in runs
                          if t_gen < purge[i][0] < nxt_off), None)
            if first is None:
                continue
            e_gen = e_vlv = None
            for t, v in d["ect"]:
                if t <= t_gen:
                    e_gen = v
                if t <= first:
                    e_vlv = v
            c_gen = 0
            for t, c in counter:
                if t <= t_gen:
                    c_gen = c
            delays.append(first - t_gen)
            emit("%-24s %11s %11s %9.1f %8s %8s %9d"
                 % (sess, clock(t_gen), clock(first), first - t_gen,
                    "n/a" if e_gen is None else "%.0f" % e_gen,
                    "n/a" if e_vlv is None else "%.0f" % e_vlv, c_gen))
    if delays:
        ds = sorted(delays)
        emit("\n   n=%d  values: %s" % (len(ds), " ".join("%.0f" % x for x in ds)))
        emit("   min=%.0fs  median=%.0fs  max=%.0fs" % (ds[0], ds[len(ds) // 2], ds[-1]))

    # ---- 5c. does the counter advance ONLY while duty is high?
    #
    # The decisive test. Forward-fill the counter onto the duty samples, then
    # bin counter advance rate by duty. If the counter is gated on duty, the
    # low-duty bins must show ~zero advance even though the engine is running.
    emit("\n--- 5c. Counter advance rate binned by commanded duty ---")
    bins = defaultdict(lambda: [0.0, 0.0])     # bin -> [seconds, counts]
    for sess in sorted(onsets):
        d = onsets[sess]
        counter = sorted(d["counter"])
        purge = sorted(d["purge"])
        if not counter or not purge:
            continue
        ci = 0
        cval = counter[0][1]
        prev_t = prev_c = None
        for t, v in purge:
            while ci < len(counter) and counter[ci][0] <= t:
                cval = counter[ci][1]
                ci += 1
            if prev_t is not None:
                dt = t - prev_t
                dc = cval - prev_c
                # skip log-chunk seams and counter resets
                if 0 < dt < 5 and dc >= 0:
                    b = min(int(v // 10) * 10, 90)
                    bins[b][0] += dt
                    bins[b][1] += dc
            prev_t, prev_c = t, cval
    emit("%10s %12s %12s %14s" % ("duty band", "seconds", "counts", "counts/s"))
    for b in sorted(bins):
        sec, cnt = bins[b]
        if sec < 5:
            continue
        emit("%7d-%-3d %12.0f %12.0f %14.3f"
             % (b, b + 9, sec, cnt, cnt / sec if sec else 0))
    lo = sum(bins[b][1] for b in bins if b < 20)
    hi = sum(bins[b][1] for b in bins if b >= 20)
    emit("\n   counts accumulated below 20%% duty: %.0f" % lo)
    emit("   counts accumulated at or above 20%% duty: %.0f" % hi)
    if lo + hi:
        emit("   -> %.1f%% of all purge progress happens at duty >= 20%%"
             % (100.0 * hi / (lo + hi)))

    # ---- 5d. per-session count rate while the gate is open.
    #
    # 5c pools everything and so is dragged down by time spent purging AFTER a
    # cycle completes -- the ECM keeps the valve open, but the counter has
    # reset to 0 and no longer advances. Excluding post-completion time is the
    # difference between "roughly 0.7-0.9 c/s" and the real number.
    emit("\n--- 5d. Count rate while duty >= %d%%, excluding post-completion ---"
         % GATE)
    emit("%-24s %9s %8s %10s %9s"
         % ("session", "sec_gate", "counts", "counts/s", "s/count"))
    tot_s = tot_c = 0.0
    for sess in sorted(onsets):
        d = onsets[sess]
        purge = sorted(d["purge"])
        counter = sorted(d["counter"])
        if not purge or not counter:
            continue
        t_comp = None
        for i in range(1, len(counter)):
            if counter[i - 1][1] >= 100 and counter[i][1] == 0:
                t_comp = counter[i][0]
                break
        ci, cval = 0, counter[0][1]
        prev_t = prev_c = None
        sec = cnt = 0.0
        for t, v in purge:
            if t_comp and t >= t_comp:
                break
            while ci < len(counter) and counter[ci][0] <= t:
                cval = counter[ci][1]
                ci += 1
            if prev_t is not None:
                dt, dc = t - prev_t, cval - prev_c
                if 0 < dt < 5 and dc >= 0 and v >= GATE:
                    sec += dt
                    cnt += dc
            prev_t, prev_c = t, cval
        if sec > 60 and cnt:
            tot_s += sec
            tot_c += cnt
            emit("%-24s %9.0f %8.0f %10.3f %9.2f"
                 % (sess, sec, cnt, cnt / sec, sec / cnt))
    if tot_c:
        rate = tot_c / tot_s
        emit("\n   POOLED %.0f s / %.0f counts -> %.4f counts/s (%.3f s per count)"
             % (tot_s, tot_c, rate, 1.0 / rate))
        emit("   -> the counter is a 1 Hz timer gated on purge duty, not an")
        emit("      opaque VCM state. Terminal 901 counts = %.0f s = %.1f min"
             % (901 / rate, 901 / rate / 60))
        emit("      of qualifying purge. Progress = counter/901 is therefore a")
        emit("      legitimate completion fraction, and 901 - counter is the")
        emit("      seconds of qualifying purge still required.")

    with open(SWEEP_TXT, "w") as f:
        f.write("\n".join(out) + "\n")
    print("\nwrote %s" % os.path.basename(SWEEP_TXT))


# ---------------------------------------------------------------- phase 6

BASE_TXT = os.path.join(OUTDIR, "evap_history_base_rate.txt")
RPM_RUNNING = 400.0


def phase6():
    """Corpus-wide base rate: what share of engine-running time is evap-active?

    This exists because the first attempt at the figure was computed only over
    the sessions that had OBD purge data -- and those were selected BECAUSE
    they contain purge activity, which makes the answer circular. Any statement
    of the form "N of M stalls were evap-active, versus a base rate of X" is
    only meaningful if X comes from the whole corpus.

    Method: 1 s buckets from InfluxDB for Engine_Speed (OBD-bus copy, the real
    ECM value) and vcm_evap_active, joined on the bucket. Buckets are seconds,
    not point counts, so the on-change write policy does not distort the total.
    """
    ss = series_of(influx("SELECT COUNT(\"Engine_Speed\") FROM signals "
                          "WHERE vehicle='%s' AND can_id='0x0C9' AND bus='obd' "
                          "GROUP BY session" % VEHICLE))
    sessions = sorted(s["tags"]["session"] for s in ss)
    print("phase 6: base rate over %d sessions with OBD engine speed"
          % len(sessions))

    rows = []
    tot = {0: 0, 1: 0, None: 0}
    for i, sess in enumerate(sessions, 1):
        a = series_of(influx(
            "SELECT MAX(\"Engine_Speed\") AS v FROM signals WHERE vehicle='%s' "
            "AND can_id='0x0C9' AND bus='obd' AND session='%s' "
            "GROUP BY time(1s) fill(none)" % (VEHICLE, sess), epoch="s"))
        if not a:
            continue
        b = series_of(influx(
            "SELECT MAX(\"vcm_evap_active\") AS v FROM signals WHERE "
            "vehicle='%s' AND can_id='0x649' AND session='%s' "
            "GROUP BY time(1s) fill(none)" % (VEHICLE, sess), epoch="s"))
        evap = {t: int(v) for t, v in b[0]["values"] if v is not None} if b else {}

        run = {0: 0, 1: 0, None: 0}
        last = None
        for t, v in a[0]["values"]:
            if v is None or v <= RPM_RUNNING:
                continue
            if t in evap:
                last = evap[t]
            run[last] += 1
        for k in run:
            tot[k] += run[k]
        if sum(run.values()):
            rows.append((sess, run[1], run[0], run[None]))
        if i % 25 == 0:
            print("  %d/%d" % (i, len(sessions)), flush=True)

    out = []

    def em(s=""):
        out.append(s)
        print(s)

    em("=" * 78)
    em("Corpus base rate: engine-running seconds by evap state")
    em("=" * 78)
    em("\nEngine running = OBD Engine_Speed > %.0f rpm, counted in 1 s buckets."
       % RPM_RUNNING)
    em("Sessions with OBD engine speed: %d; with engine actually running: %d"
       % (len(sessions), len(rows)))
    known = tot[0] + tot[1]
    em("\n   evap ACTIVE : %8d s  (%.1f h)" % (tot[1], tot[1] / 3600.0))
    em("   evap IDLE   : %8d s  (%.1f h)" % (tot[0], tot[0] / 3600.0))
    em("   unknown     : %8d s  (no 0x649 in that session)" % tot[None])
    if known:
        em("\n   -> %.1f%% of classifiable engine-running time is evap-active"
           % (100.0 * tot[1] / known))

    em("\n--- Per session (engine-running seconds) ---")
    em("%-34s %10s %10s %10s" % ("session", "evap_act", "evap_idle", "unknown"))
    for sess, a1, a0, an in sorted(rows, key=lambda r: -(r[1] + r[2] + r[3])):
        em("%-34s %10d %10d %10d" % (sess, a1, a0, an))

    with open(BASE_TXT, "w") as f:
        f.write("\n".join(out) + "\n")
    print("\nwrote %s" % os.path.basename(BASE_TXT))


# ---------------------------------------------------------------- phase 7

STALL_TXT = os.path.join(OUTDIR, "evap_history_stalls_corpuswide.txt")


def phase7():
    """Stall search over the WHOLE corpus, not just purge-heavy sessions.

    Why this phase exists: the stall/dip events in
    `evap_duty_vs_engine_state.py` were found only in the 13 sessions that
    carry OBD PID 0x2E, and those were chosen because they contain purge
    activity. Within them, evap-active is 87% of engine-running time; across
    the corpus it is 29%. So that search had almost no non-purge engine time
    to find a counterexample in (1,696 s vs 40,744 s corpus-wide), and could
    not have answered "do stalls also happen outside evap?" either way.

    Detecting a stall needs only engine speed and the evap flag, both of which
    InfluxDB holds for every session -- PID 0x2E is not required. So the search
    can cover all 58 sessions in which the engine actually ran.

    Criterion (the one that does not depend on a tuned threshold): the engine
    was running (>900 rpm), collapsed to <100 rpm, and then ran again within
    60 s. A restart means the VCM still wanted the engine, so the stop was
    involuntary. Collapses with no restart are left unclassified -- there is no
    way to tell a stall from a deliberate shutdown when nothing restarts.
    """
    ss = series_of(influx("SELECT COUNT(\"Engine_Speed\") FROM signals "
                          "WHERE vehicle='%s' AND can_id='0x0C9' AND bus='obd' "
                          "GROUP BY session" % VEHICLE))
    sessions = sorted(s["tags"]["session"] for s in ss)
    print("phase 7: corpus-wide stall search over %d sessions" % len(sessions))

    events = []
    run_secs = {0: 0, 1: 0}
    for i, sess in enumerate(sessions, 1):
        a = series_of(influx(
            "SELECT MIN(\"Engine_Speed\") AS lo, MAX(\"Engine_Speed\") AS hi "
            "FROM signals WHERE vehicle='%s' AND can_id='0x0C9' AND bus='obd' "
            "AND session='%s' GROUP BY time(1s) fill(none)"
            % (VEHICLE, sess), epoch="s"))
        if not a:
            continue
        b = series_of(influx(
            "SELECT MAX(\"vcm_evap_active\") AS v FROM signals WHERE "
            "vehicle='%s' AND can_id='0x649' AND session='%s' "
            "GROUP BY time(1s) fill(none)" % (VEHICLE, sess), epoch="s"))
        evap = {t: int(v) for t, v in b[0]["values"] if v is not None} if b else {}

        rows = [(t, lo, hi) for t, lo, hi in a[0]["values"]
                if lo is not None and hi is not None]
        ea = None
        state = []
        for t, lo, hi in rows:
            if t in evap:
                ea = evap[t]
            state.append((t, lo, hi, ea))
            if hi > 400 and ea is not None:
                run_secs[ea] += 1

        n = len(state)
        k = 0
        while k < n:
            t, lo, hi, ea = state[k]
            if lo >= 100:
                k += 1
                continue
            # was it genuinely running in the previous 30 s?
            prior = [x for x in state[max(0, k - 30):k] if x[2] > 900]
            if not prior:
                k += 1
                continue
            # did it run again within 60 s?
            later = [x for x in state[k + 1:k + 61] if x[2] > 900]
            restart = (later[0][0] - t) if later else None
            # sag: contiguous seconds below 700 immediately before
            j = k - 1
            while j >= 0 and state[j][2] < 700:
                j -= 1
            sag = t - state[j + 1][0] if j + 1 < k else 0
            events.append({"sess": sess, "t": t, "evap": ea, "sag": sag,
                           "restart": restart})
            while k < n and state[k][1] < 100:
                k += 1
        if i % 25 == 0:
            print("  %d/%d" % (i, len(sessions)), flush=True)

    out = []

    def em(s=""):
        out.append(s)
        print(s)

    em("=" * 84)
    em("Corpus-wide stall search (engine speed + evap flag, all sessions)")
    em("=" * 84)
    known = run_secs[0] + run_secs[1]
    em("\nEngine-running time in the searched population:")
    em("   evap ACTIVE %7d s   evap IDLE %7d s   -> base rate %.1f%% active"
       % (run_secs[1], run_secs[0], 100.0 * run_secs[1] / known if known else 0))

    stalls = [e for e in events if e["restart"] is not None]
    noresta = [e for e in events if e["restart"] is None]
    em("\n%d engine collapses found: %d restarted (involuntary), "
       "%d did not (unclassifiable)" % (len(events), len(stalls), len(noresta)))

    em("\n--- Collapses that restarted = involuntary stalls ---")
    em("%-34s %12s %6s %7s %9s" % ("session", "time", "evap", "sag_s",
                                   "restart_s"))
    for e in sorted(stalls, key=lambda x: (x["sess"], x["t"])):
        em("%-34s %12s %6s %7d %9d"
           % (e["sess"], clock(e["t"]), e["evap"], e["sag"], e["restart"]))
    na = sum(1 for e in stalls if e["evap"] == 1)
    ni = sum(1 for e in stalls if e["evap"] == 0)
    em("\n   %d with evap ACTIVE, %d with evap IDLE" % (na, ni))
    if known and stalls:
        p = run_secs[1] / float(known)
        em("   base rate is %.1f%%, so %d of %d evap-active has p = %.4f "
           "if stalls were independent of evap" % (100 * p, na, len(stalls),
                                                   p ** na if ni == 0 else -1))

    em("\n--- Collapses with no restart (cannot separate stall from shutdown) ---")
    em("%-34s %12s %6s %7s" % ("session", "time", "evap", "sag_s"))
    for e in sorted(noresta, key=lambda x: (x["sess"], x["t"])):
        em("%-34s %12s %6s %7d" % (e["sess"], clock(e["t"]), e["evap"], e["sag"]))
    na = sum(1 for e in noresta if e["evap"] == 1)
    ni = sum(1 for e in noresta if e["evap"] == 0)
    em("\n   %d with evap ACTIVE, %d with evap IDLE" % (na, ni))

    with open(STALL_TXT, "w") as f:
        f.write("\n".join(out) + "\n")
    print("\nwrote %s" % os.path.basename(STALL_TXT))


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--phases" in argv:
        i = argv.index("--phases")
        PHASES = {int(x) for x in argv[i + 1].split(",")}
    if 1 in PHASES:
        phase1()
    if 2 in PHASES:
        phase2()
    if 3 in PHASES:
        phase3()
    if 4 in PHASES:
        phase4()
    if 5 in PHASES:
        phase5()
    if 6 in PHASES:
        phase6()
    if 7 in PHASES:
        phase7()
