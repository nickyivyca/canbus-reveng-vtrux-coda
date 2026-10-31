"""charger_wake_sequence.py -- how the Bel charger/inverter comes onto and
leaves the powertrain bus, around plug-in (charge) and around export
(reviewer, 2026-10-13; user asked, export included).

Question: does the Bel start transmitting before the VCU acts, or only after
the VCU wakes/commands it? How long after the plug (EVSESwitchState) or the
export switch (ExportPowerState) does its first frame come, and what do its
wake/sleep flags say? At the end, how long does it keep talking after the plug
or switch drops? Feeds the interposer's "vehicle port listen-only while the
charger is silent" idea: whether the board could switch over in time.

Raw logs, not InfluxDB: the order of events and frame timing are the point.
Decoded with cantools (no hand-rolled bits):
  0x592  EVSESwitchState / ExportPowerState / IgnitionKeyState  (epri-pt-bus)
  0x410  bcm_on_plug                                            (epri-pt-bus)
  0x18EFC000 page 00 chgcmd_enable / chgcmd_mode   (vtrux-powertrain-experimental)
  0x18FFD4C0 page 0 BELINV_state, _wakeOutput, _delayedSleepMode,
             _rewakedFromDelayedSleep, _exporting   (BelInverter-v2)
  any extended frame with source address 0xC0 = "a Bel frame"
Powertrain channel per file: 0x051 >= 100 frames and none of the vehicle/obd
anchors (projects/vtrux/README.md). 0x051 runs at 100 Hz, so a 0x051 gap
> 0.5 s on that channel is a logger gap and is reported.

File selection (madhouse): every file of every session that has a Bel frame on
a powertrain channel in interposer_jam_priority_sweep.json (so the chunk before
the Bel's first frame is included). Session = file name less _T<n>.

Phase 1: per file, transitions only, absolute timestamps -> charger_wake_sequence.json
Phase 2: per session, merged and time-sorted; per plug-in / export episode,
         the sequence relative to the switch edge -> charger_wake_sequence.txt

Usage (project root, madhouse): python3 <this> 1 2 [--workers N]
"""
import sys
sys.path.insert(0, ".")
import json
import multiprocessing as mp
import re
import statistics
from collections import defaultdict
from pathlib import Path

import cantools

from canre.parsers import parse_file

ART = "projects/vtrux/notes/artifacts/"
SWEEP = ART + "interposer_jam_priority_sweep.json"
CACHE = ART + "charger_wake_sequence.json"
OUT = ART + "charger_wake_sequence.txt"
PT_ANCHOR = 0x051
OTHER_ANCHORS = {0x1E5, 0x500, 0x040, 0x041, 0x042, 0x043, 0x044}
GAP_S = 0.5
BEL_SEG_S = 2.0

ID_SENSOR = 0x592
ID_BCM = 0x410
ID_VCU = 0x18EFC000
ID_BEL_STATUS = 0x18FFD4C0
SENSOR_SIGS = ("EVSESwitchState", "ExportPowerState", "IgnitionKeyState")
BEL_SIGS = ("BELINV_state", "BELINV_wakeOutput", "BELINV_delayedSleepMode",
            "BELINV_rewakedFromDelayedSleep", "BELINV_exporting")

_DB = {}


def dbs():
    if not _DB:
        epri = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc",
                                           strict=False)
        exp = cantools.database.load_file(
            "projects/vtrux/vtrux-powertrain-experimental.dbc", strict=False)
        bel = cantools.database.load_file("projects/vtrux/BelInverter-v2.dbc",
                                          strict=False)
        _DB["sensor"] = epri.get_message_by_frame_id(ID_SENSOR)
        _DB["bcm"] = epri.get_message_by_frame_id(ID_BCM)
        _DB["vcu"] = exp.get_message_by_frame_id(ID_VCU)
        _DB["bel"] = bel.get_message_by_frame_id(ID_BEL_STATUS)
    return _DB


def is_bel(ident, ext):
    return ext and (ident & 0xFF) == 0xC0


def session_key(path):
    return re.sub(r"_T\d+$", "", Path(path).stem)


def scan_one(path):
    d = dbs()
    ch = {}
    try:
        for fr in parse_file(path, absolute=True):
            c = ch.get(fr.bus)
            if c is None:
                c = ch[fr.bus] = {"n051": 0, "other": False, "t0": fr.timestamp,
                                  "t1": fr.timestamp, "last051": None,
                                  "gaps": [], "ev": [], "raw": {},
                                  "val": {}, "bel_first": None,
                                  "bel_last": None, "vcu_first": None,
                                  "bel_segs": []}
            t = fr.timestamp
            c["t0"] = min(c["t0"], t)
            c["t1"] = max(c["t1"], t)
            i, x = fr.arbitration_id, bool(fr.is_extended)
            if not x and i in OTHER_ANCHORS:
                c["other"] = True
                continue
            if not x and i == PT_ANCHOR:
                c["n051"] += 1
                if c["last051"] is not None and t - c["last051"] > GAP_S:
                    c["gaps"].append([c["last051"], t])
                c["last051"] = t
                continue
            if is_bel(i, x):
                if c["bel_first"] is None:
                    c["bel_first"] = [t, i]
                c["bel_last"] = [t, i]
                segs = c["bel_segs"]
                if segs and segs[-1][0] - BEL_SEG_S <= t <= segs[-1][1] + BEL_SEG_S:
                    segs[-1][0] = min(segs[-1][0], t)
                    segs[-1][1] = max(segs[-1][1], t)
                else:
                    segs.append([t, t])
            key = (i, x)
            if key not in ((ID_SENSOR, False), (ID_BCM, False),
                           (ID_VCU, True), (ID_BEL_STATUS, True)):
                continue
            data = bytes(fr.data)
            if i == ID_VCU and c["vcu_first"] is None:
                c["vcu_first"] = t
            if i in (ID_VCU, ID_BEL_STATUS):
                if not data or data[0] != 0:
                    continue
                rk = (i, 0)
            else:
                rk = (i, None)
            if c["raw"].get(rk) == data:
                continue
            c["raw"][rk] = data
            try:
                if i == ID_SENSOR:
                    msg, sigs = d["sensor"], SENSOR_SIGS
                elif i == ID_BCM:
                    msg, sigs = d["bcm"], ("bcm_on_plug",)
                elif i == ID_VCU:
                    msg, sigs = d["vcu"], ("chgcmd_enable", "chgcmd_mode")
                else:
                    msg, sigs = d["bel"], BEL_SIGS
                dec = msg.decode(data, decode_choices=False)
            except Exception:
                continue
            for s in sigs:
                if s not in dec:
                    continue
                v = dec[s]
                if c["val"].get(s) != v:
                    c["ev"].append([t, s, v])
                    c["val"][s] = v
    except Exception as e:
        return str(path), None, "parse error: %s" % e
    out = []
    for bus, c in ch.items():
        if c["n051"] < 100 or c["other"]:
            continue
        out.append({"bus": str(bus), "t0": c["t0"], "t1": c["t1"],
                    "gaps": c["gaps"], "ev": c["ev"],
                    "bel_first": c["bel_first"], "bel_last": c["bel_last"],
                    "vcu_first": c["vcu_first"], "bel_segs": c["bel_segs"]})
    return str(path), out, None


def select_files():
    with open(SWEEP) as f:
        sweep = json.load(f)
    bel_sessions = set()
    for p, r in sweep.items():
        for _ch, verdict, _span, ids in (r["chans"] or []):
            if verdict == "powertrain" and any(is_bel(i, x) for i, x, _n in ids):
                bel_sessions.add((str(Path(p).parent), session_key(p)))
    return sorted(p for p in sweep
                  if (str(Path(p).parent), session_key(p)) in bel_sessions)


def phase1(workers):
    files = select_files()
    print("files:", len(files), flush=True)
    res = {}
    ctx = mp.get_context("fork")
    with ctx.Pool(workers) as pool:
        for k, (p, out, err) in enumerate(
                pool.imap_unordered(scan_one, files, chunksize=1), 1):
            res[p] = {"chans": out, "err": err}
            if k % 50 == 0:
                print("%d / %d" % (k, len(files)), flush=True)
    with open(CACHE, "w") as f:
        json.dump(res, f)


def fmt(dt):
    return "-" if dt is None else "%+.2f" % dt


def phase2():
    with open(CACHE) as f:
        res = json.load(f)
    sessions = defaultdict(list)
    errs = []
    for p, r in res.items():
        if r["err"]:
            errs.append(p)
            continue
        for c in r["chans"]:
            sessions[(str(Path(p).parent), session_key(p))].append((p, c))
    lines = ["charger_wake_sequence -- Bel onto/off the powertrain bus around "
             "plug-in and export",
             "files: %d, parse errors: %d, sessions with a powertrain channel: %d"
             % (len(res), len(errs), len(sessions)),
             "times in s relative to the switch edge; '-' = not seen; "
             "'gap' = a 0x051 gap > %.1f s within 5 s of the edge or of the "
             "first Bel frame (order there is unknown)" % GAP_S, ""]
    starts, ends, keyoffs = [], [], []
    detail = []
    for (folder, sk), chans in sorted(sessions.items()):
        ev, gaps, belf, bell, span, segs = [], [], [], [], [], []
        vcuf = []
        for p, c in chans:
            ev += [tuple(e) for e in c["ev"]]
            gaps += c["gaps"]
            span.append((c["t0"], c["t1"]))
            if c["bel_first"]:
                belf.append(c["bel_first"][0])
                bell.append(c["bel_last"][0])
            segs += c.get("bel_segs", [])
            if c["vcu_first"]:
                vcuf.append(c["vcu_first"])
        ev.sort()
        segs.sort()
        merged = []
        for a, b in segs:
            if merged and a <= merged[-1][1] + BEL_SEG_S:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        segs = merged
        t_start = min(s[0] for s in span)
        t_end = max(s[1] for s in span)
        bel_on = min(belf) if belf else None
        bel_off = max(bell) if bell else None

        def first_after(sig, t, pred=lambda v: True, within=600):
            for te, s, v in ev:
                if s == sig and te >= t - 0.001 and te <= t + within and pred(v):
                    return te
            return None

        def near_gap(t):
            return t is not None and any(
                g0 - 5 <= t <= g1 + 5 for g0, g1 in gaps)

        # A transition is a change from the value last seen on this bus in
        # this session. A channel's first value is NOT an edge (Android
        # bus-number churn restarts channels mid-session).
        edges, prev = [], {}
        for te, s, v in ev:
            if s in prev and prev[s] != v:
                edges.append((te, s, v))
            prev[s] = v

        def state(sig, t):
            val = None
            for te2, s2, v2 in ev:
                if te2 > t:
                    break
                if s2 == sig:
                    val = v2
            return val

        for te, s, v in edges:
            if s != "IgnitionKeyState" or v != 0:
                continue
            seg = next((g for g in segs if g[0] <= te + 1 and g[1] >= te - 1),
                       None)
            row = {"session": sk, "evse": state("EVSESwitchState", te),
                   "export": state("ExportPowerState", te),
                   "bel_exporting": state("BELINV_exporting", te),
                   "wake": state("BELINV_wakeOutput", te),
                   "bel_state": state("BELINV_state", te),
                   "vcu_mode": state("chgcmd_mode", te)}
            if seg is None:
                row["bel"] = "silent at key-off"
            else:
                after = [v2 for te2, s2, v2 in ev
                         if s2 == "BELINV_state" and te < te2 <= seg[1] + 0.5]
                vcu_after = [v2 for te2, s2, v2 in ev
                             if s2 == "chgcmd_mode" and te < te2 <= seg[1] + 0.5]
                ds = first_after("BELINV_delayedSleepMode", te,
                                 lambda x: x == 1, seg[1] + 0.5 - te)
                row["bel"] = ("last frame %+.2f s; Bel states after key-off %s; "
                              "VCU modes after %s; delayedSleep=1 %s; powertrain "
                              "log continues %.1f s after the Bel's last frame%s"
                              % (seg[1] - te, after, vcu_after,
                                 fmt(None if ds is None else ds - te),
                                 t_end - seg[1],
                                 " GAP" if near_gap(seg[1]) else ""))
            keyoffs.append(row)

        for kind, sig in (("plug", "EVSESwitchState"),
                          ("export", "ExportPowerState")):
            for te, s, v in edges:
                if s != sig:
                    continue
                if v == 1:
                    lead = te - t_start
                    row = {"session": sk, "kind": kind, "edge": "on",
                           "lead_s": lead}
                    rel = lambda t: None if t is None else t - te
                    seg = next((g for g in segs if g[1] >= te - 60), None)
                    row["bel_first"] = (rel(seg[0]) if seg and seg[0] - te < 600
                                        else None)
                    row["on_plug"] = rel(first_after("bcm_on_plug", te - 30,
                                                     lambda x: x == 1))
                    row["wakeOutput1"] = rel(first_after(
                        "BELINV_wakeOutput", te - 30, lambda x: x == 1))
                    row["vcu_enable1"] = rel(first_after(
                        "chgcmd_enable", te - 30, lambda x: x == 1))
                    row["vcu_mode"] = None
                    for te2, s2, v2 in ev:
                        if s2 == "chgcmd_mode" and te2 >= te - 30:
                            row["vcu_mode"] = (round(te2 - te, 2), v2)
                            break
                    row["bel_state12"] = rel(first_after(
                        "BELINV_state", te - 30, lambda x: x == 12))
                    row["gap"] = near_gap(te) or (seg is not None and near_gap(seg[0]))
                    starts.append(row)
                else:
                    row = {"session": sk, "kind": kind, "edge": "off",
                           "tail_s": t_end - te}
                    rel = lambda t: None if t is None else t - te
                    seg = next((g for g in reversed(segs) if g[0] <= te + 5), None)
                    row["bel_last"] = (rel(seg[1]) if seg and seg[1] >= te - 60
                                       else None)
                    row["delayedSleep1"] = rel(first_after(
                        "BELINV_delayedSleepMode", te, lambda x: x == 1))
                    row["vcu_standby"] = rel(first_after(
                        "chgcmd_mode", te - 30, lambda x: x == 2, 60))
                    row["gap"] = near_gap(te) or (seg is not None and near_gap(seg[1]))
                    ends.append(row)
        detail.append((sk, folder, t_start, t_end, bel_on, bel_off, edges, gaps,
                       ev))

    lines.append("== ON edges (plug-in / export switch on). lead_s = log time "
                 "before the edge (< 1 s: the logger may have started with it)")
    lines.append("session | kind | lead_s | bel_first | on_plug | "
                 "wakeOutput=1 | vcu_enable=1 | vcu first mode (t, mode) | "
                 "bel state 12 | gap")
    for r in starts:
        lines.append("%s | %s | %.1f | %s | %s | %s | %s | %s | %s | %s" % (
            r["session"], r["kind"], r["lead_s"], fmt(r["bel_first"]),
            fmt(r["on_plug"]), fmt(r["wakeOutput1"]), fmt(r["vcu_enable1"]),
            r["vcu_mode"], fmt(r["bel_state12"]), "GAP" if r["gap"] else ""))
    lines.append("")
    lines.append("== OFF edges (plug / export switch off). tail_s = log time "
                 "after the edge")
    lines.append("session | kind | tail_s | bel_last | delayedSleep=1 | "
                 "vcu STAND_BY | gap")
    for r in ends:
        lines.append("%s | %s | %.1f | %s | %s | %s | %s" % (
            r["session"], r["kind"], r["tail_s"], fmt(r["bel_last"]),
            fmt(r["delayedSleep1"]), fmt(r["vcu_standby"]),
            "GAP" if r["gap"] else ""))
    lines.append("")
    for kind in ("plug", "export"):
        clean = [r for r in starts if r["kind"] == kind and r["lead_s"] >= 1
                 and not r["gap"] and r["bel_first"] is not None]
        if clean:
            bf = [r["bel_first"] for r in clean]
            lines.append("%s ON, clean (lead >= 1 s, no gap): n=%d; bel_first "
                         "median %+.2f s, min %+.2f, max %+.2f; Bel already "
                         "talking before the edge in %d" % (
                             kind, len(clean), statistics.median(bf), min(bf),
                             max(bf), sum(1 for x in bf if x < 0)))
        clean = [r for r in ends if r["kind"] == kind and not r["gap"]
                 and r["bel_last"] is not None and r["tail_s"] >= 5]
        if clean:
            bl = [r["bel_last"] for r in clean]
            lines.append("%s OFF, clean (tail >= 5 s, no gap): n=%d; bel_last "
                         "median %+.2f s, min %+.2f, max %+.2f" % (
                             kind, len(clean), statistics.median(bl), min(bl),
                             max(bl)))
    lines.append("")
    lines.append("== Sessions with Bel frames but no switch edge in the log "
                 "(logger started after the edge): first Bel frame relative "
                 "to the log's start, and switch states at the start")
    for sk, folder, t0, t1, bon, boff, edges, gaps, ev in detail:
        if bon is None:
            continue
        on_edges = [e for e in edges if e[1] in ("EVSESwitchState",
                                                  "ExportPowerState")
                    and e[2] == 1]
        if on_edges:
            continue
        init = {}
        for te, s, v in ev:
            if s in ("EVSESwitchState", "ExportPowerState",
                     "IgnitionKeyState") and s not in init:
                init[s] = v
        lines.append("%s | bel_first %+.2f s after log start | %s" % (
            sk, bon - t0, init))
    lines.append("")
    lines.append("== Key-off edges (IgnitionKeyState 1 -> 0): switch and Bel "
                 "state at the edge, and how the Bel left the bus")
    lines.append("session | EVSE | export switch | BELINV_exporting | "
                 "wakeOutput | Bel state | VCU mode | Bel after key-off")
    for r in keyoffs:
        lines.append("%s | %s | %s | %s | %s | %s | %s | %s" % (
            r["session"], r["evse"], r["export"], r["bel_exporting"],
            r["wake"], r["bel_state"], r["vcu_mode"], r["bel"]))
    lines.append("")
    lines.append("== wakeOutput while exporting vs while charging: per session, "
                 "the values BELINV_wakeOutput takes while BELINV_exporting = 1, "
                 "and while EVSESwitchState = 1 and BELINV_exporting = 0")
    for sk, folder, t0, t1, bon, boff, edges, gaps, ev in detail:
        cur = {}
        w_exp, w_chg = set(), set()
        for te, s, v in ev:
            cur[s] = v
            w = cur.get("BELINV_wakeOutput")
            if w is None:
                continue
            if cur.get("BELINV_exporting") == 1:
                w_exp.add(w)
            elif cur.get("EVSESwitchState") == 1:
                w_chg.add(w)
        if w_exp or w_chg:
            lines.append("%s | exporting: %s | charging/plugged: %s" % (
                sk, sorted(w_exp) or "-", sorted(w_chg) or "-"))
    if errs:
        lines += ["", "parse errors:"] + errs
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:4]))


if __name__ == "__main__":
    args = sys.argv[1:]
    workers = 4
    if "--workers" in args:
        workers = int(args[args.index("--workers") + 1])
    if "1" in args:
        phase1(workers)
    if "2" in args:
        phase2()
