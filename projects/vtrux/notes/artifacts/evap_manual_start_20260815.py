"""Evap purge start lag after a MANUAL engine start -- session 2026-08-15 19:52.

User report: driving with evap indicated as pending, started the engine manually
(M mode) to bring the purge forward, and the display did not move to PURGE until
"a few minutes later" despite the engine running the whole time.

Two questions this script serves:

  Q1  Does that observation change the Phase 5 reading of the evap bits
      (0x649 B4 bit 7 = vcm_evap_active, 0x649 B2[3:0]:B3 = vcm_evap_counter)?
      -> measure the exact lag between engine start and the counter leaving 0,
         and compare it against the lags already on record.

  Q2  Is there any ECM-sourced telemetry for the tank/canister purge solenoid
      that could be cross-referenced?
      -> this session is an unusually good discriminator for that. In every
         previously analysed evap log the engine started *because* of the evap
         cycle, so "engine running" and "purge running" were the same window and
         nothing could separate an ECM purge signal from an ECM engine signal.
         Here the engine ran for minutes with the purge provably not running, so
         a byte that moves at purge-start but NOT at engine-start is a candidate.

CAPTURE LAYOUT (this session)
    Channel 1 = GM vehicle bus (GMLAN; ECM messages 0x0C9, 0x1A1, 0x4C1 ...)
    Channel 2 = Via PT / VCU bus (0x600, 0x639-0x64B, 0x598 ...)
    No OBD bus was captured -- phase 3 verifies there is no 0x7E0/0x7E8 traffic.
    Buses are identified by message content, never by channel number.

TIME BASE
    Chunk-relative timestamps are HH:MM:SS:tttt where tttt is 10 kHz ticks
    (0.1 ms), per AGENTS.md. Absolute wall clock comes from each chunk's
    "START DATE AND TIME" header, whose sub-second field IS milliseconds.

Phases (toggle in PHASES / --phases):
    1  single pass over the session: 1 Hz joint timeseries + exact transition
       times for the evap flag, the evap counter and the generator
    2  report off the cached CSV: engine-start -> purge-start lag, coolant
       temperature at each, comparison table against prior sessions
    3  GM-bus differential scan: every byte of every channel-1 message,
       transitions inside the purge-start window vs inside the engine-start
       control window (answers Q2)

Usage:  python3.13 projects/vtrux/notes/artifacts/evap_manual_start_20260815.py
        python3.13 ... .py --phases 1
"""

import sys
import os
import re
import csv
import glob
import json
import subprocess
import multiprocessing as mp
from collections import defaultdict

sys.path.insert(0, ".")

PHASES = {1, 2}

LOGDIR = "../../CANLogs/VtruxLogs"
OUTDIR = "projects/vtrux/notes/artifacts"
DBC = "projects/vtrux/vtrux-powertrain-experimental.dbc"
GMLAN_DBC = "projects/vtrux/GMW8762_PPEI_GMLAN.dbc"

SESSION = "vtrux_20260815_195222"

TS_CSV = os.path.join(OUTDIR, "evap_manual_start_20260815_timeseries.csv")
EV_JSON = os.path.join(OUTDIR, "evap_manual_start_20260815_events.json")
REPORT = os.path.join(OUTDIR, "evap_manual_start_20260815_report.txt")
SCAN_TXT = os.path.join(OUTDIR, "evap_manual_start_20260815_gmscan.txt")

ID_600 = 0x600     # VCM generator command / engine-state counter
ID_63C = 0x63C     # B6 = generator RPM proxy
ID_649 = 0x649     # evap flag + counter
ID_598 = 0x598     # ess/gen/trac power
ID_596 = 0x596     # bms_soc
ID_639 = 0x639     # shift lever position
ID_4C1 = 0x4C1     # GMLAN Engine_General_Status_4 -> coolant temperature

TARGETS = (ID_600, ID_63C, ID_649, ID_598, ID_596, ID_639, ID_4C1)
GREP_RE = r" 0x(600|63C|649|598|596|639|4C1) "

HDR = re.compile(r"START DATE AND TIME (\d+):(\d+):(\d+) (\d+):(\d+):(\d+):(\d+)")

DEC_649 = 10       # 0x649 is ~20 Hz here; every 10th frame is still 2 Hz
NWORKERS = 8


# ---------------------------------------------------------------- helpers

def chunk_paths(session):
    out = []
    for p in glob.glob(os.path.join(LOGDIR, "%s_T*.log" % session)):
        m = re.match(r"^.*_T(\d+)\.log$", os.path.basename(p))
        if m:
            out.append((int(m.group(1)), p))
    return [p for _, p in sorted(out)]


def header_start(path):
    """Seconds since midnight of the chunk's start, plus the raw tuple."""
    with open(path, "r", errors="replace") as f:
        for _ in range(80):
            line = f.readline()
            if not line:
                break
            m = HDR.search(line)
            if m:
                dd, mo, yy, hh, mm, ss, ms = (int(x) for x in m.groups())
                return (hh * 3600 + mm * 60 + ss + ms / 1000.0,
                        (yy, mo, dd, hh, mm, ss))
    return None, None


def clock(t):
    """Seconds-since-midnight -> HH:MM:SS.s"""
    return "%02d:%02d:%06.3f" % (t // 3600, (t % 3600) // 60, t % 60)


# ---------------------------------------------------------------- worker

_DB = None
_GM = None


def _db():
    global _DB
    if _DB is None:
        import cantools
        _DB = cantools.db.load_file(DBC)
    return _DB


def _gm():
    global _GM
    if _GM is None:
        import cantools
        _GM = cantools.db.load_file(GMLAN_DBC)
    return _GM


def scan_chunk(path):
    """One pass over a chunk: 1 Hz timeseries plus exact transition events."""
    base, raw = header_start(path)
    if base is None:
        return {"chunk": os.path.basename(path), "error": "no header timestamp"}

    db = _db()
    gm = _gm()

    series = {}
    events = []
    chan = defaultdict(set)

    evap = cnt = None
    gen600 = eng600 = None
    genrpm = None
    ess = gpow = tpow = None
    soc = None
    shift = None
    ect = None
    n649 = 0

    def ev(t, what, old, new):
        events.append((round(t, 4), what, old, new))

    p = subprocess.Popen(["grep", "-E", GREP_RE, path],
                         stdout=subprocess.PIPE, text=True, errors="replace")
    for line in p.stdout:
        f = line.split()
        if len(f) < 7:
            continue
        try:
            ts = f[0].split(":")
            t = (base + int(ts[0]) * 3600 + int(ts[1]) * 60
                 + int(ts[2]) + int(ts[3]) / 10000.0)
            ch = int(f[2])
            cid = int(f[3], 16)
        except (ValueError, IndexError):
            continue
        if cid not in TARGETS:
            continue
        chan[cid].add(ch)
        try:
            data = bytes(int(x, 16) for x in f[6:])
        except ValueError:
            continue

        if cid == ID_649:
            n649 += 1
            if n649 % DEC_649 or len(data) < 8:
                continue
            try:
                d = db.decode_message(ID_649, data, decode_choices=False)
            except Exception:
                continue
            a, c = int(d["vcm_evap_active"]), int(d["vcm_evap_counter"])
            if evap is not None and a != evap:
                ev(t, "evap_active", evap, a)
            if cnt is not None and c != cnt:
                ev(t, "evap_counter", cnt, c)
            evap, cnt = a, c

        elif cid == ID_600 and len(data) >= 4:
            if gen600 is not None and data[0] != gen600:
                ev(t, "0x600_B0", gen600, data[0])
            if eng600 is not None and data[3] != eng600:
                ev(t, "0x600_B3", eng600, data[3])
            gen600, eng600 = data[0], data[3]

        elif cid == ID_63C and len(data) >= 7:
            genrpm = data[6]

        elif cid == ID_598 and len(data) >= 8:
            try:
                d = db.decode_message(ID_598, data, decode_choices=False)
                ess, gpow, tpow = d["ess_power"], d["gen_power"], d["trac_power"]
            except Exception:
                pass

        elif cid == ID_596 and len(data) >= 8:
            try:
                soc = db.decode_message(ID_596, data,
                                        decode_choices=False)["bms_soc"]
            except Exception:
                pass

        elif cid == ID_639 and len(data) >= 8:
            try:
                s = int(db.decode_message(
                    ID_639, data, decode_choices=False)["shift_lever_pos"])
            except Exception:
                s = None
            if s is not None:
                if shift is not None and s != shift:
                    ev(t, "shift_lever_pos", shift, s)
                shift = s

        elif cid == ID_4C1 and len(data) >= 8:
            try:
                d = gm.decode_message(ID_4C1, data, decode_choices=False)
                ect = d["Engine_Coolant_Temperature"]
            except Exception:
                pass

        series[int(t)] = (round(t, 1), evap, cnt, gen600, eng600, genrpm,
                          None if gpow is None else round(gpow, 2),
                          None if ess is None else round(ess, 2),
                          None if tpow is None else round(tpow, 2),
                          soc, shift, ect)

    p.stdout.close()
    p.wait()

    return {
        "chunk": os.path.basename(path),
        "start": raw,
        "base": base,
        "chan": {"0x%03X" % k: sorted(v) for k, v in chan.items()},
        "events": events,
        "series": sorted(series.values()),
        "n649": n649,
    }


# ---------------------------------------------------------------- phase 1

def phase1():
    paths = chunk_paths(SESSION)
    print("phase 1: %s -- %d chunks, %.2f GB"
          % (SESSION, len(paths),
             sum(os.path.getsize(p) for p in paths) / 2**30))

    with mp.Pool(min(NWORKERS, max(1, len(paths)))) as pool:
        results = []
        for i, r in enumerate(pool.imap_unordered(scan_chunk, paths), 1):
            results.append(r)
            print("  [%2d/%2d] %-36s %s"
                  % (i, len(paths), r["chunk"],
                     r.get("error", "649=%d ev=%d" % (r["n649"],
                                                      len(r["events"])))),
                  flush=True)

    good = [r for r in results if "error" not in r]
    rows, events, chanmap = [], [], {}
    for r in good:
        rows.extend(r["series"])
        events.extend(r["events"])
        chanmap[r["chunk"]] = r["chan"]
    # sort on time alone -- tuple compare would trip over the None placeholders
    # that appear before each signal has been seen for the first time
    rows.sort(key=lambda r: r[0])
    events.sort(key=lambda e: e[0])

    with open(TS_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "evap_active", "evap_counter", "b0_600", "b3_600",
                    "genrpm_b6", "gen_kw", "ess_kw", "trac_kw", "soc",
                    "shift", "ect_c"])
        w.writerows(rows)

    with open(EV_JSON, "w") as f:
        json.dump({"session": SESSION, "chanmap": chanmap,
                   "events": events, "rows": len(rows)}, f, indent=1)

    print("\nwrote %s (%d rows)" % (os.path.basename(TS_CSV), len(rows)))
    print("wrote %s (%d events)" % (os.path.basename(EV_JSON), len(events)))


# ---------------------------------------------------------------- phase 2

def phase2():
    with open(EV_JSON) as f:
        meta = json.load(f)
    events = meta["events"]
    rows = []
    with open(TS_CSV) as f:
        for d in csv.DictReader(f):
            def num(k, cast=float):
                v = d[k]
                return None if v == "" else cast(v)
            rows.append({
                "t": float(d["t"]),
                "evap": num("evap_active", int),
                "cnt": num("evap_counter", int),
                "b0": num("b0_600", int),
                "b3": num("b3_600", int),
                "rpm": num("genrpm_b6", int),
                "gen": num("gen_kw"),
                "soc": num("soc"),
                "ect": num("ect_c"),
            })
    rows.sort(key=lambda r: r["t"])

    out = []

    def emit(s=""):
        out.append(s)
        print(s)

    emit("=" * 78)
    emit("Evap purge start after a manual engine start -- %s" % SESSION)
    emit("=" * 78)

    emit("\nBus channels (identified by content, not by number):")
    first = next(iter(meta["chanmap"].values()))
    emit("   %s" % json.dumps(first))

    t0 = rows[0]["t"] if rows else 0
    t1 = rows[-1]["t"] if rows else 0
    emit("\nSession span: %s -> %s  (%.0f s, %d one-second samples)"
         % (clock(t0), clock(t1), t1 - t0, len(rows)))

    # ---- headline evap / generator events
    emit("\n--- Evap flag and counter events ---")
    for t, what, old, new in events:
        if what == "evap_active":
            emit("   %s  vcm_evap_active  %s -> %s" % (clock(t), old, new))
    cnt_events = [e for e in events if e[1] == "evap_counter"]
    if cnt_events:
        firstnz = next((e for e in cnt_events if e[3] > 0), None)
        emit("   %s  vcm_evap_counter first change  %s -> %s"
             % (clock(cnt_events[0][0]), cnt_events[0][2], cnt_events[0][3]))
        if firstnz:
            emit("   %s  vcm_evap_counter LEAVES ZERO  %s -> %s"
                 % (clock(firstnz[0]), firstnz[2], firstnz[3]))
        emit("   %s  vcm_evap_counter last change   %s -> %s"
             % (clock(cnt_events[-1][0]), cnt_events[-1][2], cnt_events[-1][3]))
        emit("   counter range: %d .. %d"
             % (min(e[3] for e in cnt_events), max(e[3] for e in cnt_events)))

    emit("\n--- 0x600 B0 (VCM generator command) transitions ---")
    for t, what, old, new in events:
        if what == "0x600_B0":
            emit("   %s  0x%02X -> 0x%02X%s"
                 % (clock(t), old, new,
                    "   [GEN_ON]" if (new & 0x10) and not (old & 0x10)
                    else ("   [GEN_OFF]" if (old & 0x10) and not (new & 0x10)
                          else "")))

    emit("\n--- shift lever position transitions ---")
    for t, what, old, new in events:
        if what == "shift_lever_pos":
            emit("   %s  %s -> %s" % (clock(t), old, new))

    # ---- engine start.
    # 0x63C B6 does NOT rest at zero in this session: it sits at 6 with the
    # engine stopped, so a ">0" test reads as "running" for the whole log.
    # Use a threshold above that floor, and prefer the VCM's own GEN_ON edge
    # (0x600 B0 bit 4) when one is present -- it is the command that starts
    # the engine and is exact to the frame.
    def first_running(rows):
        run = 0
        for r in rows:
            if r["rpm"] is not None and r["rpm"] > 20:
                run += 1
                if run >= 3:
                    return r["t"] - 2
            else:
                run = 0
        return None

    t_eng = first_running(rows)
    gen_on = [e for e in events
              if e[1] == "0x600_B0" and (e[3] & 0x10) and not (e[2] & 0x10)]
    if gen_on:
        emit("\n   (engine-start anchor taken from the 0x600 GEN_ON edge; "
             "RPM-threshold estimate was %s)"
             % ("n/a" if t_eng is None else clock(t_eng)))
        t_eng = gen_on[0][0]
    t_purge = None
    for r in rows:
        if r["cnt"]:
            t_purge = r["t"]
            break

    emit("\n--- THE MEASUREMENT ---")
    if t_eng is None:
        emit("   engine never ran in this session")
    else:
        emit("   engine start (0x63C B6 sustained > 0) : %s" % clock(t_eng))
    if t_purge is None:
        emit("   vcm_evap_counter never left zero")
    else:
        emit("   purge start (counter leaves 0)        : %s" % clock(t_purge))
    if t_eng is not None and t_purge is not None:
        emit("   LAG                                    : %.1f s (%.1f min)"
             % (t_purge - t_eng, (t_purge - t_eng) / 60.0))

    def at(t, key):
        best, bd = None, 1e9
        for r in rows:
            d = abs(r["t"] - t)
            if d < bd and r[key] is not None:
                best, bd = r[key], d
        return best

    if t_eng is not None and t_purge is not None:
        emit("\n   coolant temp at engine start : %s C" % at(t_eng, "ect"))
        emit("   coolant temp at purge start  : %s C" % at(t_purge, "ect"))
        emit("   SoC at engine start          : %s %%" % at(t_eng, "soc"))
        emit("   SoC at purge start           : %s %%" % at(t_purge, "soc"))
        emit("   gen power at purge start     : %s kW" % at(t_purge, "gen"))

    # ---- second-by-second through the engine-start -> purge-start gap, which
    # is the whole point of the session: what was moving while the counter sat
    # at zero with the engine already running.
    if t_eng is not None and t_purge is not None:
        emit("\n--- The gap: engine running, counter still zero (every 15 s) ---")
        emit("%-12s %7s %8s %8s %8s %7s %7s"
             % ("time", "t_eng+", "counter", "genrpm", "gen_kW", "ect_C", "soc"))
        for r in rows:
            if not (t_eng - 30 <= r["t"] <= t_purge + 30):
                continue
            if int(r["t"]) % 15:
                continue
            emit("%-12s %7.0f %8s %8s %8s %7s %7s"
                 % (clock(r["t"])[:8], r["t"] - t_eng, r["cnt"], r["rpm"],
                    r["gen"], r["ect"], r["soc"]))

    # ---- what the three-state display would have shown, minute by minute
    emit("\n--- Display state minute by minute (Phase 5 three-state rule) ---")
    emit("%-12s %6s %8s %8s %8s %7s %7s"
         % ("time", "state", "flag", "counter", "genrpm", "gen_kW", "ect_C"))
    lastmin = None
    for r in rows:
        m = int(r["t"] // 60)
        if m == lastmin:
            continue
        lastmin = m
        if r["evap"] is None:
            st = "?"
        elif r["evap"] == 0:
            st = "COMPLETE"
        elif not r["cnt"]:
            st = "PENDING"
        else:
            st = "PURGE"
        emit("%-12s %8s %8s %8s %8s %7s %7s"
             % (clock(r["t"])[:8], st, r["evap"], r["cnt"], r["rpm"],
                r["gen"], r["ect"]))

    with open(REPORT, "w") as f:
        f.write("\n".join(out) + "\n")
    print("\nwrote %s" % os.path.basename(REPORT))


# ---------------------------------------------------------------- phase 3

# Filled in from phase 2 output before phase 3 is run.
T_ENGINE = None
T_PURGE = None
WIN = 20.0          # +/- seconds around each anchor


def scan_chunk_gm(args):
    """All byte transitions on every message, inside two anchored windows."""
    path, t_eng, t_purge, win = args
    base, _ = header_start(path)
    if base is None:
        return None

    windows = {"engine": (t_eng - win, t_eng + win),
               "purge": (t_purge - win, t_purge + win)}
    lo = min(w[0] for w in windows.values())
    hi = max(w[1] for w in windows.values())

    last = {}
    hits = defaultdict(list)
    counts = defaultdict(int)
    has_obd = set()

    with open(path, "r", errors="replace") as fh:
        for line in fh:
            f = line.split()
            if len(f) < 7 or f[1] != "Rx":
                continue
            try:
                ts = f[0].split(":")
                t = (base + int(ts[0]) * 3600 + int(ts[1]) * 60
                     + int(ts[2]) + int(ts[3]) / 10000.0)
                ch = int(f[2])
                cid = int(f[3], 16)
            except (ValueError, IndexError):
                continue
            if 0x7DF <= cid <= 0x7EF:
                has_obd.add(cid)
            if t < lo - 5 or t > hi + 5:
                continue
            try:
                data = bytes(int(x, 16) for x in f[6:])
            except ValueError:
                continue
            key = (ch, cid)
            prev = last.get(key)
            last[key] = data
            if prev is None or len(prev) != len(data):
                continue
            for i, (a, b) in enumerate(zip(prev, data)):
                if a == b:
                    continue
                counts[(ch, cid, i)] += 1
                for name, (w0, w1) in windows.items():
                    if w0 <= t <= w1:
                        hits[(ch, cid, i, name)].append((round(t, 3), a, b))
    return {"hits": {"%d|%d|%d|%s" % k: v for k, v in hits.items()},
            "counts": {"%d|%d|%d" % k: v for k, v in counts.items()},
            "obd": sorted(has_obd)}


def phase3():
    if T_ENGINE is None or T_PURGE is None:
        print("phase 3 needs T_ENGINE and T_PURGE set from the phase 2 report")
        return
    paths = chunk_paths(SESSION)
    args = [(p, T_ENGINE, T_PURGE, WIN) for p in paths]
    print("phase 3: differential byte scan over %d chunks" % len(paths))
    with mp.Pool(min(NWORKERS, max(1, len(paths)))) as pool:
        res = [r for r in pool.map(scan_chunk_gm, args) if r]

    hits = defaultdict(list)
    counts = defaultdict(int)
    obd = set()
    for r in res:
        for k, v in r["hits"].items():
            ch, cid, i, name = k.split("|")
            hits[(int(ch), int(cid), int(i), name)].extend(v)
        for k, v in r["counts"].items():
            ch, cid, i = k.split("|")
            counts[(int(ch), int(cid), int(i))] += v
        obd |= set(r["obd"])

    out = []

    def emit(s=""):
        out.append(s)
        print(s)

    emit("=" * 78)
    emit("GM-bus differential scan: purge-start window vs engine-start window")
    emit("=" * 78)
    emit("anchors: engine=%s  purge=%s  window=+/-%.0f s"
         % (clock(T_ENGINE), clock(T_PURGE), WIN))
    emit("\nOBD-II diagnostic IDs (0x7DF-0x7EF) seen anywhere in the session: %s"
         % (["0x%03X" % c for c in sorted(obd)] or "NONE -- no OBD bus captured"))

    keys = {(ch, cid, i) for (ch, cid, i, _) in hits}
    cand = []
    for k in sorted(keys):
        n_e = len(hits.get(k + ("engine",), []))
        n_p = len(hits.get(k + ("purge",), []))
        if n_p and not n_e:
            cand.append((k, n_p, counts[k]))

    emit("\n--- Bytes that move in the PURGE window but NOT in the ENGINE window ---")
    emit("%-5s %-8s %-5s %8s %12s   %s"
         % ("ch", "id", "byte", "n_purge", "n_session", "transitions"))
    for (ch, cid, i), n_p, n_all in sorted(cand, key=lambda x: (x[2], x[0])):
        tr = hits[(ch, cid, i, "purge")][:6]
        emit("%-5d 0x%03X    B%-4d %8d %12d   %s"
             % (ch, cid, i, n_p, n_all,
                " ".join("%.1f:%02X->%02X" % v for v in tr)))
    emit("\n%d candidate bytes" % len(cand))
    emit("A purge-solenoid signal should be quiet across the session apart from")
    emit("purge windows, so low n_session with n_purge > 0 is what to look for.")

    with open(SCAN_TXT, "w") as f:
        f.write("\n".join(out) + "\n")
    print("\nwrote %s" % os.path.basename(SCAN_TXT))


# ---------------------------------------------------------------- phase 4

# OBD-II mode 01 PIDs polled on 0x7E0 in this session, and answered on 0x7E8.
# 0x2E is the one that matters here: Commanded Evaporative Purge, the ECM's own
# duty-cycle command to the canister purge solenoid.
OBD_REQ, OBD_RSP = 0x7E0, 0x7E8
PID_NAMES = {
    0x01: "monitor_status_since_clear",
    0x0E: "timing_advance",
    0x2E: "commanded_evap_purge",
    0x3C: "cat_temp_b1s1",
    0x41: "monitor_status_this_cycle",
}
OBD_CSV = os.path.join(OUTDIR, "evap_manual_start_20260815_obd.csv")
OBD_TXT = os.path.join(OUTDIR, "evap_manual_start_20260815_obd.txt")


def scan_chunk_obd(path):
    """Pull every mode-01 response off 0x7E8, decoded per PID."""
    base, _ = header_start(path)
    if base is None:
        return []
    rows = []
    p = subprocess.Popen(["grep", "-E", r" 0x7E8 ", path],
                         stdout=subprocess.PIPE, text=True, errors="replace")
    for line in p.stdout:
        f = line.split()
        if len(f) < 7:
            continue
        try:
            ts = f[0].split(":")
            t = (base + int(ts[0]) * 3600 + int(ts[1]) * 60
                 + int(ts[2]) + int(ts[3]) / 10000.0)
            data = bytes(int(x, 16) for x in f[6:])
        except (ValueError, IndexError):
            continue
        # single-frame ISO-TP: [len][0x41][pid][payload...]
        if len(data) < 4 or data[1] != 0x41:
            continue
        n = data[0]
        pid = data[2]
        payload = data[3:1 + n]
        rows.append((round(t, 3), pid, payload.hex()))
    p.stdout.close()
    p.wait()
    return rows


def phase4():
    paths = chunk_paths(SESSION)
    print("phase 4: OBD mode-01 extraction over %d chunks" % len(paths))
    with mp.Pool(min(NWORKERS, max(1, len(paths)))) as pool:
        rows = [r for part in pool.map(scan_chunk_obd, paths) for r in part]
    rows.sort()

    with open(OBD_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "pid", "pid_name", "payload_hex", "value"])
        for t, pid, hx in rows:
            val = ""
            b = bytes.fromhex(hx)
            if pid == 0x2E and b:
                val = round(b[0] * 100.0 / 255.0, 2)
            elif pid == 0x0E and b:
                val = round(b[0] / 2.0 - 64.0, 1)
            elif pid == 0x3C and len(b) >= 2:
                val = round(((b[0] << 8) | b[1]) / 10.0 - 40.0, 1)
            w.writerow([t, "0x%02X" % pid, PID_NAMES.get(pid, "?"), hx, val])

    out = []

    def emit(s=""):
        out.append(s)
        print(s)

    emit("=" * 78)
    emit("ECM OBD-II telemetry -- %s" % SESSION)
    emit("=" * 78)
    seen = defaultdict(int)
    for _, pid, _ in rows:
        seen[pid] += 1
    emit("\nMode 01 PIDs answered by the ECM on 0x7E8:")
    for pid in sorted(seen):
        emit("   0x%02X  %-28s %6d responses"
             % (pid, PID_NAMES.get(pid, "?"), seen[pid]))

    # ---- PID 0x2E: commanded evaporative purge, the direct cross-reference
    purge = [(t, bytes.fromhex(h)[0] * 100.0 / 255.0)
             for t, pid, h in rows if pid == 0x2E and h]
    emit("\n--- PID 0x2E commanded_evap_purge (%% duty) ---")
    if not purge:
        emit("   no responses")
    else:
        nz = [p for p in purge if p[1] > 0]
        emit("   responses: %d   nonzero: %d   max: %.1f%%"
             % (len(purge), len(nz), max(p[1] for p in purge)))
        if nz:
            emit("   first nonzero: %s (%.1f%%)" % (clock(nz[0][0]), nz[0][1]))
            emit("   last  nonzero: %s (%.1f%%)" % (clock(nz[-1][0]), nz[-1][1]))
        emit("\n   %-12s %10s" % ("time", "purge_%"))
        lastmin = None
        for t, v in purge:
            m = int(t // 30)
            if m == lastmin:
                continue
            lastmin = m
            emit("   %-12s %10.1f" % (clock(t)[:8], v))

    # ---- monitor readiness: is the ECM's own EVAP monitor complete?
    # Mode 01 PID 41 / 01, byte C bit 2 = evap monitor supported,
    # byte D bit 2 = evap monitor INCOMPLETE.
    for pid in (0x41, 0x01):
        mon = [(t, bytes.fromhex(h)) for t, p, h in rows if p == pid and h]
        emit("\n--- PID 0x%02X %s: EVAP monitor readiness ---"
             % (pid, PID_NAMES.get(pid, "?")))
        if not mon:
            emit("   no responses")
            continue
        states = []
        for t, b in mon:
            if len(b) < 4:
                continue
            sup = bool(b[2] & 0x04)
            inc = bool(b[3] & 0x04)
            st = (sup, inc)
            if not states or states[-1][1] != st:
                states.append((t, st))
        for t, (sup, inc) in states:
            emit("   %s  evap supported=%s  incomplete=%s -> %s"
                 % (clock(t), sup, inc,
                    "NOT READY" if (sup and inc) else
                    ("COMPLETE" if sup else "not supported")))

    with open(OBD_TXT, "w") as f:
        f.write("\n".join(out) + "\n")
    print("\nwrote %s and %s"
          % (os.path.basename(OBD_CSV), os.path.basename(OBD_TXT)))


# ---------------------------------------------------------------- phase 5

JOIN_TXT = os.path.join(OUTDIR, "evap_manual_start_20260815_join.txt")


def phase5():
    """Join the ECM purge duty (PID 0x2E) to the VCM evap counter.

    The two are independent observers of the same event: the ECM reports what it
    is commanding the canister purge solenoid to do, the VCM reports its own
    notion of purge progress. Their relative timing is the finding.
    """
    obd = []
    with open(OBD_CSV) as f:
        for d in csv.DictReader(f):
            if d["pid"] == "0x2E" and d["value"] != "":
                obd.append((float(d["t"]), float(d["value"])))
    obd.sort()

    ts = []
    with open(TS_CSV) as f:
        for d in csv.DictReader(f):
            ts.append((float(d["t"]),
                       None if d["evap_counter"] == "" else int(d["evap_counter"]),
                       None if d["ect_c"] == "" else float(d["ect_c"]),
                       None if d["genrpm_b6"] == "" else int(d["genrpm_b6"]),
                       None if d["gen_kw"] == "" else float(d["gen_kw"])))
    ts.sort(key=lambda r: r[0])

    out = []

    def emit(s=""):
        out.append(s)
        print(s)

    def ts_at(t):
        best, bd = None, 1e9
        for row in ts:
            d = abs(row[0] - t)
            if d < bd:
                best, bd = row, d
        return best

    emit("=" * 78)
    emit("ECM commanded purge (OBD PID 0x2E) vs VCM evap counter -- %s" % SESSION)
    emit("=" * 78)

    # requester activity window -- does the polling track the engine?
    emit("\nOBD poll window: %s -> %s" % (clock(obd[0][0]), clock(obd[-1][0])))

    nz = [p for p in obd if p[1] > 0]
    t_ecm = nz[0][0] if nz else None
    t_vcm = next((r[0] for r in ts if r[1]), None)
    emit("ECM opens purge valve (PID 0x2E first > 0) : %s"
         % (clock(t_ecm) if t_ecm else "never"))
    emit("VCM counter leaves zero                    : %s"
         % (clock(t_vcm) if t_vcm else "never"))
    if t_ecm and t_vcm:
        emit("VCM counter lags the ECM valve by          : %.1f s"
             % (t_vcm - t_ecm))
        r = ts_at(t_ecm)
        emit("coolant temp when the ECM opened the valve : %s C" % r[2])

    emit("\n--- Second-by-second across the ECM purge onset ---")
    emit("%-12s %9s %9s %8s %8s" % ("time", "purge_%", "vcm_cnt", "ect_C", "rpm"))
    for t, v in obd:
        if not (t_ecm - 60 <= t <= t_ecm + 90):
            continue
        r = ts_at(t)
        emit("%-12s %9.1f %9s %8s %8s"
             % (clock(t)[:8], v, r[1], r[2], r[3]))

    with open(JOIN_TXT, "w") as f:
        f.write("\n".join(out) + "\n")
    print("\nwrote %s" % os.path.basename(JOIN_TXT))


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--phases" in argv:
        i = argv.index("--phases")
        PHASES = {int(x) for x in argv[i + 1].split(",")}
    # --session re-points every phase at another capture, so the same joins can
    # be run against an earlier session as a cross-check without editing paths
    if "--session" in argv:
        i = argv.index("--session")
        SESSION = argv[i + 1]
        TS_CSV = os.path.join(OUTDIR, "evap_%s_timeseries.csv" % SESSION)
        EV_JSON = os.path.join(OUTDIR, "evap_%s_events.json" % SESSION)
        REPORT = os.path.join(OUTDIR, "evap_%s_report.txt" % SESSION)
        OBD_CSV = os.path.join(OUTDIR, "evap_%s_obd.csv" % SESSION)
        OBD_TXT = os.path.join(OUTDIR, "evap_%s_obd.txt" % SESSION)
        JOIN_TXT = os.path.join(OUTDIR, "evap_%s_join.txt" % SESSION)
    if "--anchors" in argv:
        i = argv.index("--anchors")
        T_ENGINE = float(argv[i + 1])
        T_PURGE = float(argv[i + 2])
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
