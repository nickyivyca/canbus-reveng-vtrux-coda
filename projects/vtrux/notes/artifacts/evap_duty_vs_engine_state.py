"""Commanded purge duty vs engine state: warm-up gate, non-purge purging, stalls.

Three questions, all answerable now that PID 0x2E (Commanded Evaporative Purge)
is known to be polled on the OBD bus whenever the engine runs:

  Q1  When SoC reaches 80% and the VCM starts the engine ITSELF, does the purge
      still wait for warm-up? (The warm-up correlation in
      `evap_purge_history.py` phase 5b mixed manual M-mode starts and automatic
      SoC-driven starts without separating them.)

  Q2  What purge activity is there in ordinary non-purge driving? Does the ECM
      command any purge when the VCM has no evap cycle pending, and is the duty
      lower than during a cycle?

  Q3  Could the high duty explain the occasional stall during evap purge?
      `notes/engine-stall-analysis.md` traces the stall to a VCM wind-down /
      ECM DFCO timing gap, and its outstanding question 4 is "why only when in
      evap purge?" -- which was unanswerable without a purge-flow signal.

SIGNALS (bus matters -- see projects/vtrux/README.md: GMLAN IDs appear on both GM buses with
DIFFERENT content, the OBD-bus copy being the real ECM value)
    OBD bus   0x7E8 mode 01 PID 0x2E   commanded purge duty, A*100/255 %
              0x0C9 Engine_Speed       real RPM, (B1<<8|B2)*0.25
              0x0C9 Accelerator_Actual_Position   throttle command as ECM sees it
              0x0C9 Engine_Run_Active
              0x3D1 Throttle_Position  throttle body
              0x3D1 Engine_Coast_Fuel_Cut_Off_Active   DFCO
              0x4C1 Engine_Coolant_Temperature
    PT bus    0x649 vcm_evap_active / vcm_evap_counter
              0x600 B0 bit 4           VCM generator command (GEN_ON)
              0x639 shift_lever_pos    4 = M mode -> manual start

BUS IDENTIFICATION
    Never by channel number. The OBD bus is the one carrying 0x040-0x044 (TRAC
    MCU, exclusive to OBD per projects/vtrux/README.md); the PT bus is the one carrying 0x051.
    Android captures carry only those two buses, but the primary laptop logs
    carry three, and the Vehicle-bus copies of 0x0C9/0x3D1 would give wrong
    values if picked up by mistake.

Phases:
    1  one pass over every log with PID 0x2E -> joint event/sample series
    2  Q1: engine starts classified auto vs manual, with warm-up delay
    3  Q2: duty distribution, evap-active vs evap-idle, engine running
    4  Q3: stalls and near-stalls, with purge duty through each event

Usage:  python3.13 projects/vtrux/notes/artifacts/evap_duty_vs_engine_state.py
"""

import sys
import os
import re
import glob
import json
import subprocess
import multiprocessing as mp
from collections import defaultdict

sys.path.insert(0, ".")

PHASES = {1, 2, 3, 4}

OUTDIR = "projects/vtrux/notes/artifacts"
ANDROID = "../../CANLogs/VtruxLogs"
PRIMARY = "projects/vtrux/logs"
GMLAN_DBC = "projects/vtrux/GMW8762_PPEI_GMLAN.dbc"

SERIES_JSON = os.path.join(OUTDIR, "evap_duty_state_series.json")
REPORT = os.path.join(OUTDIR, "evap_duty_state_report.txt")

# Sessions confirmed to carry PID 0x2E (from evap_purge_history.py phase 3),
# plus the two primary logs that contain the only captured stall.
ANDROID_SESSIONS = [
    "vtrux_20260512_121839", "vtrux_20260512_202115", "vtrux_20260512_204407",
    "vtrux_20260609_175327", "vtrux_20260610_202222", "vtrux_20260714_075514",
    "vtrux_20260714_075545", "vtrux_20260719_164520", "vtrux_20260719_190019",
    "vtrux_20260724_162517", "vtrux_20260815_195222",
]
PRIMARY_LOGS = ["vtruxanotherevaplogpart2.log", "vtruxevapdrivelog4.log"]

HDR = re.compile(r"START DATE AND TIME (\d+):(\d+):(\d+) (\d+):(\d+):(\d+):(\d+)")

ID_0C9, ID_3D1, ID_4C1 = 0x0C9, 0x3D1, 0x4C1
ID_600, ID_639, ID_649 = 0x600, 0x639, 0x649
GREP = r" (0x7E8|0x0C9|0xC9|0x3D1|0x4C1|0x600|0x639|0x649|0x051|0x51|0x044|0x44) "

NWORKERS = 8

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
    return 0.0


def clock(t):
    r = t % 86400
    return "%02d:%02d:%06.3f" % (r // 3600, (r % 3600) // 60, r % 60)


# ---------------------------------------------------------------- phase 1

def scan_chunk(path):
    """Two passes: identify the OBD/PT channels, then extract on those only."""
    base = header_start(path)
    gm = _gm()

    # ---- pass 1: which channel is which bus? anchors only, cheap.
    obd_votes = defaultdict(int)
    pt_votes = defaultdict(int)
    # BUSMASTER prints IDs without leading zeros, so 0x044 appears as "0x44"
    # and 0x051 as "0x51"; match both spellings and normalise via int().
    p = subprocess.Popen(
        ["grep", "-E", r" (0x044|0x44|0x051|0x51) ", path],
        stdout=subprocess.PIPE, text=True, errors="replace")
    for line in p.stdout:
        f = line.split()
        if len(f) < 7:
            continue
        try:
            ch = int(f[2])
            cid = int(f[3], 16)
        except (ValueError, IndexError):
            continue
        if cid == 0x044:
            obd_votes[ch] += 1
        elif cid == 0x051:
            pt_votes[ch] += 1
    p.stdout.close()
    p.wait()
    obd_ch = max(obd_votes, key=obd_votes.get) if obd_votes else None
    pt_ch = max(pt_votes, key=pt_votes.get) if pt_votes else None

    # ---- pass 2: extract
    duty = []          # (t, %)
    rpm = []           # (t, rpm)
    app = []           # (t, %)
    tps = []           # (t, %)
    dfco = []          # (t, 0/1) changes only
    ect = []           # (t, degC) changes only
    evap = []          # (t, active, counter) changes only
    gen = []           # (t, old, new) 0x600 B0 GEN edges
    shift = []         # (t, pos) changes only

    prev = {}
    p = subprocess.Popen(["grep", "-E", GREP, path],
                         stdout=subprocess.PIPE, text=True, errors="replace")
    for line in p.stdout:
        f = line.split()
        if len(f) < 7:
            continue
        try:
            ts = f[0].split(":")
            t = round(base + int(ts[0]) * 3600 + int(ts[1]) * 60
                      + int(ts[2]) + int(ts[3]) / 10000.0, 3)
            ch = int(f[2])
            cid = int(f[3], 16)
            data = bytes(int(x, 16) for x in f[6:])
        except (ValueError, IndexError):
            continue

        if obd_ch is not None and ch == obd_ch:
            if cid == 0x7E8:
                if len(data) >= 4 and data[1] == 0x41 and data[2] == 0x2E:
                    duty.append((t, round(data[3] * 100.0 / 255.0, 2)))
            elif cid == ID_0C9 and len(data) >= 8:
                try:
                    d = gm.decode_message(ID_0C9, data, decode_choices=False)
                except Exception:
                    continue
                rpm.append((t, round(d["Engine_Speed"], 1)))
                app.append((t, round(d["Accelerator_Actual_Position"], 1)))
            elif cid == ID_3D1 and len(data) >= 8:
                try:
                    d = gm.decode_message(ID_3D1, data, decode_choices=False)
                except Exception:
                    continue
                tps.append((t, round(d["Throttle_Position"], 1)))
                v = int(d["Engine_Coast_Fuel_Cut_Off_Active"])
                if prev.get("dfco") != v:
                    dfco.append((t, v))
                    prev["dfco"] = v
            elif cid == ID_4C1 and len(data) >= 8:
                try:
                    v = gm.decode_message(
                        ID_4C1, data,
                        decode_choices=False)["Engine_Coolant_Temperature"]
                except Exception:
                    continue
                if prev.get("ect") != v:
                    ect.append((t, v))
                    prev["ect"] = v

        if pt_ch is not None and ch == pt_ch:
            if cid == ID_649 and len(data) >= 8:
                a = (data[4] >> 7) & 1
                c = ((data[2] & 0x0F) << 8) | data[3]
                if prev.get("evap") != (a, c):
                    evap.append((t, a, c))
                    prev["evap"] = (a, c)
            elif cid == ID_600 and len(data) >= 4:
                pb = prev.get("g600")
                if pb is not None and (data[0] & 0x10) != (pb & 0x10):
                    gen.append((t, pb, data[0]))
                prev["g600"] = data[0]
            elif cid == ID_639 and len(data) >= 8:
                s = (data[6] >> 4) & 0x07
                if prev.get("shift") != s:
                    shift.append((t, s))
                    prev["shift"] = s
    p.stdout.close()
    p.wait()

    # RPM/APP/TPS are high rate; decimate to ~10 Hz for storage, keeping every
    # sample near zero so stalls are not smoothed away
    def thin(seq, keep_below=None):
        out, last = [], None
        for t, v in seq:
            hot = keep_below is not None and v < keep_below
            if last is None or t - last >= 0.1 or hot:
                out.append((t, v))
                last = t
        return out

    return {"chunk": os.path.basename(path), "obd_ch": obd_ch, "pt_ch": pt_ch,
            "duty": duty, "rpm": thin(rpm, 600), "app": thin(app),
            "tps": thin(tps), "dfco": dfco, "ect": ect,
            "evap": evap, "gen": gen, "shift": shift}


def all_logs():
    jobs = []
    for s in ANDROID_SESSIONS:
        ps = sorted(glob.glob(os.path.join(ANDROID, "%s_T*.log" % s)),
                    key=lambda p: int(re.search(r"_T(\d+)\.log$", p).group(1)))
        if ps:
            jobs.append((s, ps))
    for name in PRIMARY_LOGS:
        p = os.path.join(PRIMARY, name)
        if os.path.exists(p):
            jobs.append((name.replace(".log", ""), [p]))
    return jobs


def phase1():
    jobs = all_logs()
    print("phase 1: %d sessions, %d files, %.2f GB"
          % (len(jobs), sum(len(p) for _, p in jobs),
             sum(os.path.getsize(f) for _, p in jobs for f in p) / 2**30))
    out = {}
    for i, (sess, paths) in enumerate(jobs, 1):
        with mp.Pool(min(NWORKERS, max(1, len(paths)))) as pool:
            parts = pool.map(scan_chunk, paths)
        agg = {}
        for k in ("duty", "rpm", "app", "tps", "dfco", "ect", "evap",
                  "gen", "shift"):
            agg[k] = sorted((v for part in parts for v in part[k]),
                            key=lambda x: x[0])
        agg["buses"] = [(p["chunk"], p["obd_ch"], p["pt_ch"]) for p in parts]
        out[sess] = agg
        print("  [%2d/%2d] %-28s duty=%-6d rpm=%-7d evap=%-5d gen=%d"
              % (i, len(jobs), sess, len(agg["duty"]), len(agg["rpm"]),
                 len(agg["evap"]), len(agg["gen"])), flush=True)
    with open(SERIES_JSON, "w") as f:
        json.dump(out, f)
    print("  wrote %s (%.1f MB)"
          % (os.path.basename(SERIES_JSON),
             os.path.getsize(SERIES_JSON) / 2**20))


# ---------------------------------------------------------------- helpers

def at(seq, t, default=None):
    """Last value in `seq` at or before t (seq is (t, v) sorted)."""
    v = default
    for tt, vv in seq:
        if tt > t:
            break
        v = vv
    return v


def at3(seq, t):
    a = c = None
    for tt, aa, cc in seq:
        if tt > t:
            break
        a, c = aa, cc
    return a, c


def load():
    with open(SERIES_JSON) as f:
        return json.load(f)


OUT = []


def emit(s=""):
    OUT.append(s)
    print(s)


# ---------------------------------------------------------------- phase 2

def phase2(data):
    emit("=" * 88)
    emit("Q1 -- Does an AUTOMATIC (SoC-driven) engine start also wait for warm-up?")
    emit("=" * 88)
    emit("%-26s %11s %7s %8s %8s %9s %9s"
         % ("session", "gen_on", "shift", "start", "ect@gen", "delay_s",
            "ect@valve"))
    rows = []
    for sess in sorted(data):
        d = data[sess]
        duty, gen, shift = d["duty"], d["gen"], d["shift"]
        if not duty or not gen:
            continue
        gen_on = [t for t, o, n in gen if (n & 0x10) and not (o & 0x10)]
        gen_off = [t for t, o, n in gen if (o & 0x10) and not (n & 0x10)]
        for t_gen in gen_on:
            nxt = next((t for t in gen_off if t > t_gen), float("inf"))
            # first valve opening inside this engine run
            first = None
            for i, (t, v) in enumerate(duty):
                if t <= t_gen or t >= nxt:
                    continue
                if v > 0 and (i == 0 or duty[i - 1][1] <= 0):
                    first = t
                    break
            if first is None:
                continue
            # M mode is shift_lever_pos 4; anything else at the moment of the
            # start means the VCM started the engine on its own
            sp = at(shift, t_gen)
            kind = "MANUAL" if sp == 4 else "AUTO"
            e_gen = at(d["ect"], t_gen)
            e_vlv = at(d["ect"], first)
            rows.append((kind, first - t_gen, e_gen, sess))
            emit("%-26s %11s %7s %8s %8s %9.1f %9s"
                 % (sess, clock(t_gen), sp, kind,
                    "n/a" if e_gen is None else "%.0f" % e_gen,
                    first - t_gen,
                    "n/a" if e_vlv is None else "%.0f" % e_vlv))

    for kind in ("AUTO", "MANUAL"):
        sub = [(dl, e) for k, dl, e, _ in rows if k == kind]
        if not sub:
            continue
        cold = [dl for dl, e in sub if e is not None and e < 40]
        warm = [dl for dl, e in sub if e is not None and e >= 40]
        emit("\n   %s starts: n=%d" % (kind, len(sub)))
        if cold:
            emit("      from cold (<40 C): %s  -> median %.0f s"
                 % (" ".join("%.0f" % x for x in sorted(cold)),
                    sorted(cold)[len(cold) // 2]))
        if warm:
            emit("      from warm (>=40 C): %s  -> median %.0f s"
                 % (" ".join("%.0f" % x for x in sorted(warm)),
                    sorted(warm)[len(warm) // 2]))
    emit("\n   -> if AUTO cold starts match MANUAL cold starts, the warm-up wait")
    emit("      is a property of the ECM, not of how the engine was started.")


# ---------------------------------------------------------------- phase 3

def phase3(data):
    emit("\n" + "=" * 88)
    emit("Q2 -- Purge activity when NO evap cycle is pending")
    emit("=" * 88)

    # engine-running seconds, split by whether the VCM has a cycle pending
    bins = {0: defaultdict(float), 1: defaultdict(float)}
    tot = {0: 0.0, 1: 0.0}
    peak = {0: 0.0, 1: 0.0}
    nz = {0: 0.0, 1: 0.0}
    persess = defaultdict(lambda: {0: [0.0, 0.0, 0.0], 1: [0.0, 0.0, 0.0]})

    for sess in sorted(data):
        d = data[sess]
        duty, rpm, evap = d["duty"], d["rpm"], d["evap"]
        if not duty or not evap:
            continue
        ri = 0
        rv = 0.0
        ei = 0
        ea, ec = 0, 0
        prev_t = None
        for t, v in duty:
            while ri < len(rpm) and rpm[ri][0] <= t:
                rv = rpm[ri][1]
                ri += 1
            while ei < len(evap) and evap[ei][0] <= t:
                ea, ec = evap[ei][1], evap[ei][2]
                ei += 1
            if prev_t is not None:
                dt = t - prev_t
                if 0 < dt < 5 and rv > 400:      # engine actually running
                    k = 1 if ea else 0
                    bins[k][min(int(v // 10) * 10, 90)] += dt
                    tot[k] += dt
                    peak[k] = max(peak[k], v)
                    if v > 0:
                        nz[k] += dt
                    ps = persess[sess][k]
                    ps[0] += dt
                    ps[1] += dt if v > 0 else 0.0
                    ps[2] = max(ps[2], v)
            prev_t = t

    emit("\n--- Engine-running time by commanded duty band ---")
    emit("%10s %16s %16s" % ("duty band", "evap idle (s)", "evap active (s)"))
    for b in sorted(set(bins[0]) | set(bins[1])):
        emit("%7d-%-3d %16.0f %16.0f" % (b, b + 9, bins[0][b], bins[1][b]))
    emit("%10s %16.0f %16.0f" % ("TOTAL", tot[0], tot[1]))
    for k, lbl in ((0, "evap idle  "), (1, "evap active")):
        if tot[k]:
            emit("   %s: %.0f s engine-running, %.1f%% of it with duty > 0, "
                 "peak %.1f%%" % (lbl, tot[k], 100.0 * nz[k] / tot[k], peak[k]))

    emit("\n--- Per session (engine running) ---")
    emit("%-26s %10s %8s %8s %10s %8s %8s"
         % ("session", "idle_s", "idle>0%", "idle_pk", "active_s",
            "act>0%", "act_pk"))
    for sess in sorted(persess):
        a, b = persess[sess][0], persess[sess][1]
        if a[0] < 10 and b[0] < 10:
            continue
        emit("%-26s %10.0f %8s %8.1f %10.0f %8s %8.1f"
             % (sess, a[0],
                "n/a" if not a[0] else "%.1f" % (100.0 * a[1] / a[0]), a[2],
                b[0],
                "n/a" if not b[0] else "%.1f" % (100.0 * b[1] / b[0]), b[2]))


# ---------------------------------------------------------------- phase 4

def phase4(data):
    emit("\n" + "=" * 88)
    emit("Q3 -- Purge duty through stalls and near-stalls")
    emit("=" * 88)

    # Classifying a collapse needs care. On the one captured stall the VCM
    # clears its GEN_ON bit 0.5 s BEFORE RPM reaches zero -- it is reacting to
    # the engine dying, not commanding it. So "GEN_OFF happened" cannot mean
    # "commanded shutdown". The separating evidence is (a) how far ahead of the
    # collapse the GEN_OFF edge sits and (b) whether the VCM re-asserts GEN_ON
    # shortly afterwards, which it only does when it still wanted the engine.
    RESTART_WINDOW = 60.0
    SUBIDLE = 700.0     # rpm below which the engine is under normal idle
    # Observed wallow times are bimodal: 0.4-1.2 s (eight events) then a gap to
    # 2.7 s and up. Split in the gap.
    WALLOW_S = 2.0

    events = []
    for sess in sorted(data):
        d = data[sess]
        rpm, gen = d["rpm"], d["gen"]
        if not rpm:
            continue
        gen_on = [t for t, o, n in gen if (n & 0x10) and not (o & 0x10)]
        gen_off = [t for t, o, n in gen if (o & 0x10) and not (n & 0x10)]

        i = 0
        while i < len(rpm):
            t, v = rpm[i]
            if v >= 100:
                i += 1
                continue
            # was the engine genuinely running in the preceding 30 s?
            hi = [x for x in rpm[:i] if t - 30 <= x[0] < t and x[1] >= 900]
            if not hi:
                i += 1
                continue
            j = i
            lo = v
            while j + 1 < len(rpm) and rpm[j + 1][1] < 900:
                j += 1
                lo = min(lo, rpm[j][1])
            # Classifying by CAN state alone does not work here. Every engine
            # stop in the corpus -- deliberate or not -- shows the same
            # signature at the moment of death: DFCO sets ~0.5 s before RPM
            # reaches zero, TPS dips to ~2% and then rests at ~29% (the
            # throttle body's unpowered position, not a restart attempt), and
            # the VCM clears GEN_ON ~0.6 s ahead. None of those separate the
            # cases.
            #
            # What does separate them is the APPROACH, which is also the
            # mechanism engine-stall-analysis.md describes: a deliberate stop
            # decays from a healthy RPM in about a second, whereas a stall
            # wallows for seconds at sub-idle RPM first, and only then gets
            # cut by DFCO. So the metric is the length of the contiguous
            # sub-idle run immediately preceding the collapse.
            k = i - 1
            lo_pre = None
            while k >= 0 and rpm[k][1] < SUBIDLE:
                lo_pre = rpm[k][1] if lo_pre is None else min(lo_pre, rpm[k][1])
                k -= 1
            wallow = t - rpm[k + 1][0] if k + 1 < i else 0.0

            off_lead = rpm_at_off = None
            prior_off = [x for x in gen_off if x <= t + 1.0]
            if prior_off:
                off_lead = t - prior_off[-1]
                rpm_at_off = at(rpm, prior_off[-1])
            restart = next((x - t for x in gen_on
                            if t < x <= t + RESTART_WINDOW), None)
            commanded = wallow < WALLOW_S
            events.append({"sess": sess, "t": t, "t_end": rpm[j][0], "low": lo,
                           "off_lead": off_lead, "restart": restart,
                           "rpm_at_off": rpm_at_off, "wallow": wallow,
                           "lo_pre": lo_pre,
                           "kind": "stop" if commanded else "STALL"})
            i = j + 1

        # near-stalls: dipped well below idle but recovered without dying
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
                events.append({"sess": sess, "t": t, "t_end": rpm[j][0],
                               "low": lo, "off_lead": None, "restart": None,
                               "rpm_at_off": None, "wallow": None,
                               "lo_pre": None,
                               "kind": "dip"})
            i = j + 1

    events.sort(key=lambda e: (e["sess"], e["t"]))
    stalls = [e for e in events if e["kind"] == "STALL"]
    dips = [e for e in events if e["kind"] == "dip"]
    stops = [e for e in events if e["kind"] == "stop"]
    emit("\n%d RPM collapse/dip events: %d stalls, %d commanded stops, "
         "%d recovered dips" % (len(events), len(stalls), len(stops), len(dips)))

    emit("\n--- Every event, with purge duty in the 30 s before it ---")
    emit("%-26s %11s %6s %6s %8s %8s %8s %9s %8s"
         % ("session", "time", "low", "type", "duty@-30", "duty@t0",
            "dutymax30", "evap a/cnt", "wallow_s"))
    for e in events:
        d = data[e["sess"]]
        t = e["t"]
        w = [v for tt, v in d["duty"] if t - 30 <= tt <= t]
        ea, ec = at3(d["evap"], t)
        emit("%-26s %11s %6.0f %6s %8s %8s %8s %9s %8s"
             % (e["sess"], clock(t), e["low"], e["kind"],
                "n/a" if not w else "%.1f" % w[0],
                "n/a" if not w else "%.1f" % w[-1],
                "n/a" if not w else "%.1f" % max(w),
                "%s/%s" % (ea, ec),
                "n/a" if e["wallow"] is None else "%.1f" % e["wallow"]))

    # the split that answers the question
    def summarise(lbl, evs):
        if not evs:
            return
        act = [e for e in evs if at3(data[e["sess"]]["evap"], e["t"])[0] == 1]
        idle = [e for e in evs if at3(data[e["sess"]]["evap"], e["t"])[0] == 0]
        emit("\n   %s: %d total -- %d with an evap cycle active, %d without"
             % (lbl, len(evs), len(act), len(idle)))
        for name, sub in (("evap active", act), ("evap idle", idle)):
            if not sub:
                continue
            mx = []
            for e in sub:
                w = [v for tt, v in data[e["sess"]]["duty"]
                     if e["t"] - 30 <= tt <= e["t"]]
                if w:
                    mx.append(max(w))
            if mx:
                mx.sort()
                emit("      %s: peak duty in the 30 s before, median %.1f%% "
                     "(min %.1f, max %.1f)"
                     % (name, mx[len(mx) // 2], mx[0], mx[-1]))

    summarise("Stalls", stalls)
    summarise("Recovered dips", dips)
    summarise("Commanded stops", stops)

    # detailed trace of each full stall
    for e in stalls:
        d = data[e["sess"]]
        t = e["t"]
        emit("\n--- Stall trace: %s at %s ---" % (e["sess"], clock(t)))
        emit("%11s %8s %7s %7s %7s %6s %8s"
             % ("time", "rpm", "duty%", "tps%", "app%", "dfco", "evap_cnt"))
        marks = sorted({tt for tt, _ in d["rpm"] if t - 25 <= tt <= t + 15})
        step = max(1, len(marks) // 40)
        for tt in marks[::step]:
            ea, ec = at3(d["evap"], tt)
            emit("%11s %8s %7s %7s %7s %6s %8s"
                 % (clock(tt), at(d["rpm"], tt), at(d["duty"], tt),
                    at(d["tps"], tt), at(d["app"], tt),
                    at(d["dfco"], tt), ec))


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--phases" in argv:
        PHASES = {int(x) for x in argv[argv.index("--phases") + 1].split(",")}
    if 1 in PHASES:
        phase1()
    if PHASES & {2, 3, 4}:
        data = load()
        if 2 in PHASES:
            phase2(data)
        if 3 in PHASES:
            phase3(data)
        if 4 in PHASES:
            phase4(data)
        with open(REPORT, "w") as f:
            f.write("\n".join(OUT) + "\n")
        print("\nwrote %s" % os.path.basename(REPORT))
