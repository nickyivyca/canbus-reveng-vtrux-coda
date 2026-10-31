"""Natural failed engine starts in the Vtrux corpus (no inhibitor involved).

Question (user, 2026-10-04): does the CAN history contain starts where the engine
cranked and did not catch on its own -- possibly around the evap-mode stalls? If so,
the VCM and the GM ECM have already met the situation a blocked start creates, which
bears on the generator inhibitor's truck-only questions (does the VCM fault, what does
the ECM store).

What a crank attempt looks like (gen-inhibit-truck-tests.md, truck_real3): the engine
has no starter, so the VCM cranks it with the generator. Each request is a burst of
POSITIVE gen_torque_cmd on 0x051 (motoring; peak 1736 there) lasting 1.09 s if nothing
catches, retried every 9.59 s; an allowed start had the engine turning in 0.24 s. When
the engine runs, the generator absorbs power and gen_torque_cmd goes negative.

Source: InfluxDB, first pass. Values are exact under forward fill, but points are
on-change + 1 s heartbeat, so durations here are bounded by point spacing and are
NOT frame-accurate. Anything that matters gets re-measured from the raw log.

Phase 1: per session, find motoring episodes (gen_torque_cmd > TORQUE_MIN), merging
         points closer than MERGE_S. Excludes the known rig sessions (data-sources.md).
Phase 2: for each episode, pull a window of supporting signals and classify whether the
         engine caught: GENE_RotSpd (0x054) sustained, gen_torque_cmd going negative,
         OBD Engine_Speed / Engine_Run_Active where the capture has the OBD bus.
"""
import sys
sys.path.insert(0, ".")
import json
import os
import urllib.parse
import urllib.request

OUT_DIR = "projects/vtrux/notes/artifacts/natural_failed_start"
HOST = "http://localhost:8086/query"
RIG_SESSIONS = {
    "vtrux_20260617_193900", "vtrux_20260617_215641", "vtrux_20260617_220758",
    "vtrux_20260617_221447", "vtrux_20260617_222323", "vtrux_20260618_002023",
}
TORQUE_MIN = 100        # gen_torque_cmd counts; truck_real3 cranks peaked at 1736
MERGE_S = 0.6           # points closer than this belong to one episode

RUN_PHASES = {1, 2}


def q(query):
    url = HOST + "?" + urllib.parse.urlencode(
        {"db": "canbus-data", "q": query, "epoch": "ms"})
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Basic Y2xhdWRlOmNsYXVkZQ==")   # claude:claude
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    res = data["results"][0]
    if "error" in res:
        raise RuntimeError(res["error"] + " :: " + query)
    return res.get("series", [])


def sessions():
    s = q("SHOW TAG VALUES FROM signals WITH KEY = session WHERE vehicle='vtrux'")
    return sorted(v[1] for v in s[0]["values"]) if s else []


def series(session, can_id, bus, fields, t0=None, t1=None, where=""):
    cond = ("vehicle='vtrux' AND session='%s' AND can_id='%s' AND bus='%s'"
            % (session, can_id, bus))
    if t0 is not None:
        cond += " AND time >= %dms AND time <= %dms" % (t0, t1)
    if where:
        cond += " AND " + where
    sel = ", ".join('"%s"' % f for f in fields)
    out = q("SELECT %s FROM signals WHERE %s" % (sel, cond))
    if not out:
        return []
    return out[0]["values"]          # [t_ms, f1, f2, ...]


def phase1():
    os.makedirs(OUT_DIR, exist_ok=True)
    all_sessions = sessions()
    print("vtrux sessions: %d (rig sessions excluded: %d)"
          % (len(all_sessions), len(RIG_SESSIONS & set(all_sessions))))
    episodes = []
    with_051 = 0
    for i, s in enumerate(all_sessions):
        if s in RIG_SESSIONS:
            continue
        rows = series(s, "0x051", "powertrain", ["gen_torque_cmd"],
                      where='"gen_torque_cmd" > %d' % TORQUE_MIN)
        # population check: does this session have 0x051 at all?
        if not rows:
            any051 = q("SELECT COUNT(\"gen_torque_cmd\") FROM signals WHERE "
                       "vehicle='vtrux' AND session='%s' AND can_id='0x051' "
                       "AND bus='powertrain'" % s)
            if any051:
                with_051 += 1
            continue
        with_051 += 1
        cur = None
        for t, v in rows:
            if v is None:
                continue
            if cur and t - cur["t_last"] <= MERGE_S * 1000:
                cur["t_last"] = t
                cur["peak"] = max(cur["peak"], v)
                cur["n"] += 1
            else:
                if cur:
                    episodes.append(cur)
                cur = {"session": s, "t_first": t, "t_last": t, "peak": v, "n": 1}
        if cur:
            episodes.append(cur)
        if (i + 1) % 50 == 0:
            print("  %d/%d sessions, %d episodes so far" % (i + 1, len(all_sessions),
                                                           len(episodes)))
    print("sessions with 0x051 on powertrain: %d; motoring episodes: %d"
          % (with_051, len(episodes)))
    with open(os.path.join(OUT_DIR, "phase1_episodes.json"), "w") as f:
        json.dump(episodes, f, indent=0)
    return episodes


def phase2(episodes):
    """Classify each motoring episode by what the engine did in the next few seconds."""
    rows_out = []
    for e in episodes:
        s = e["session"]
        t0 = e["t_first"] - 3000
        t1 = e["t_last"] + 15000
        tq = series(s, "0x051", "powertrain", ["gen_torque_cmd", "gen_rpm_ref"], t0, t1)
        rpm = series(s, "0x054", "powertrain", ["GENE_RotSpd"], t0, t1)
        obd = series(s, "0x0C9", "obd", ["Engine_Speed", "Engine_Run_Active"], t0, t1)
        evap = series(s, "0x649", "powertrain", ["vcm_evap_active"], t0, t1)
        after = e["t_last"]
        # engine caught = within 5 s after the episode ends, generator speed >= 600
        # AND torque negative (generating) at some point
        rpm_after = [v for t, v in rpm if v is not None and after <= t <= after + 5000]
        tq_after = [v for t, v, _ in tq if v is not None and after <= t <= after + 5000]
        rpm_during = [v for t, v in rpm if v is not None
                      and e["t_first"] <= t <= e["t_last"] + 300]
        eng_after = [v for t, v, _ in obd if v is not None and after <= t <= after + 5000]
        run_after = [r for t, _, r in obd if r is not None and after <= t <= after + 5000]
        ev = [v for t, v in evap if v is not None]
        rows_out.append({
            "session": s,
            "t_first_ms": e["t_first"],
            "dur_s": round((e["t_last"] - e["t_first"]) / 1000.0, 2),
            "peak_cmd": e["peak"],
            "n_pts": e["n"],
            "rpm_during_max": max(rpm_during) if rpm_during else None,
            "rpm_after_max": max(rpm_after) if rpm_after else None,
            "tq_after_min": min(tq_after) if tq_after else None,
            "obd_rpm_after_max": max(eng_after) if eng_after else None,
            "obd_run_after": max(run_after) if run_after else None,
            "evap": max(ev) if ev else None,
            "has_054": bool(rpm), "has_obd": bool(obd),
        })
    with open(os.path.join(OUT_DIR, "phase2_classified.json"), "w") as f:
        json.dump(rows_out, f, indent=0)
    return rows_out


RAW_LOGS = ["vtruxanotherevaplogpart2.log", "vtruxgeneratoroverheattest.log",
            "vtrux_to980.log"]
RAW_IDS = "51|54|617|644|C9|649|17D|1E5|1F3|120|514"
VEHICLE_MARKERS = {0x17D, 0x1E5, 0x1F3, 0x120, 0x514}   # gen-inhibit-truck-tests.md


def phase3():
    """Frame-accurate re-measurement of every crank attempt in the three logs that
    phase 2 flagged, from the raw capture. Buses by content: powertrain = carries
    0x051; of the GM channels carrying 0x0C9, OBD = the one with none of the
    Vehicle-bus-only markers (the Vehicle bus carries a VCM-substituted synthetic
    ~800 rpm in 0x0C9 and must not be read as engine speed)."""
    import re
    import subprocess
    import cantools
    from canre.parsers import parse_file
    pt_db = cantools.database.load_file("projects/vtrux/vtrux-powertrain-experimental.dbc")
    epri_db = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
    gm_db = cantools.database.load_file("projects/vtrux/GMW8762_PPEI_GMLAN.dbc")
    os.makedirs(OUT_DIR, exist_ok=True)
    report = {}
    for name in RAW_LOGS:
        src = os.path.join("projects/vtrux/logs", name)
        filt = os.path.join(OUT_DIR, name.replace(".log", "_filtered.log"))
        if not os.path.exists(filt):
            # pre-filter: header lines plus only the ids needed (the parser is the cost)
            with open(filt, "wb") as out:
                subprocess.run(["grep", "-a", "-E",
                                r"^\*\*\*| Rx [0-9]+ 0x(%s) " % RAW_IDS, src],
                               stdout=out, check=True)
        frames = list(parse_file(filt))
        ids_by_ch = {}
        for fr in frames:
            ids_by_ch.setdefault(fr.bus, set()).add(fr.arbitration_id)
        pt = [c for c, s in ids_by_ch.items() if 0x051 in s]
        gm = [c for c, s in ids_by_ch.items() if 0x0C9 in s and 0x051 not in s]
        obd = [c for c in gm if not (ids_by_ch[c] & VEHICLE_MARKERS)]
        veh = [c for c in gm if ids_by_ch[c] & VEHICLE_MARKERS]
        print("%s: channels %s; powertrain=%s obd=%s vehicle=%s"
              % (name, sorted(ids_by_ch), pt, obd, veh))
        if len(pt) != 1:
            print("  UNRESOLVED powertrain bus -- skipping")
            continue
        pt = pt[0]
        obd = obd[0] if len(obd) == 1 else None
        if obd is None:
            print("  OBD bus unresolved (%s) -- OBD rpm not reported" % gm)
        # series, sorted per series (file order is not time order)
        tq, rpm, b617, b644, eng, evap = [], [], [], [], [], []
        for fr in frames:
            t, d = fr.timestamp, bytes(fr.data)
            if fr.bus == pt:
                if fr.arbitration_id == 0x051 and len(d) >= 6:
                    m = pt_db.decode_message(0x051, d, decode_choices=False)
                    tq.append((t, m["gen_torque_cmd"], m["gen_rpm_ref"], d[0]))
                elif fr.arbitration_id == 0x054 and len(d) >= 5:
                    rpm.append((t, epri_db.decode_message(0x054, d, decode_choices=False)["GENE_RotSpd"]))
                elif fr.arbitration_id == 0x617 and len(d) >= 8:
                    b617.append((t, d[7]))          # no DBC signal: B7 state byte
                elif fr.arbitration_id == 0x644 and len(d) >= 7:
                    b644.append((t, d[6]))          # no DBC signal: B6 mode byte
                elif fr.arbitration_id == 0x649 and len(d) >= 8:
                    evap.append((t, pt_db.decode_message(0x649, d, decode_choices=False)["vcm_evap_active"]))
            elif obd is not None and fr.bus == obd and fr.arbitration_id == 0x0C9:
                m = gm_db.decode_message(0x0C9, d, decode_choices=False)
                eng.append((t, m.get("Engine_Speed"), m.get("Engine_Run_Active")))
        for s in (tq, rpm, b617, b644, eng, evap):
            s.sort(key=lambda x: x[0])
        # crank attempts: runs of 0x051 with torque > TORQUE_MIN and B0 = 0x0B
        attempts, cur = [], None
        for t, v, ref, b0 in tq:
            on = v > TORQUE_MIN
            if on and cur is None:
                cur = [t, t, v]
            elif on:
                cur[1], cur[2] = t, max(cur[2], v)
            elif cur is not None:
                attempts.append(cur)
                cur = None
        rows = []
        for a0, a1, peak in attempts:
            def win(series, lo, hi, k=1):
                return [x[k] for x in series if lo <= x[0] <= hi and x[k] is not None]
            r_dur = win(rpm, a0, a1 + 0.2)
            r_aft = win(rpm, a1 + 0.5, a1 + 5)
            e_dur = win(eng, a0, a1 + 0.5)
            e_aft = win(eng, a1 + 0.5, a1 + 5)
            run_aft = win(eng, a1 + 0.5, a1 + 5, 2)
            caught = (max(r_aft) if r_aft else 0) >= 600
            rows.append({
                "t": round(a0, 3), "dur_s": round(a1 - a0, 3), "peak": peak,
                "gen_rpm_during_max": max(r_dur) if r_dur else None,
                "gen_rpm_after_max": max(r_aft) if r_aft else None,
                "obd_rpm_during_max": max(e_dur) if e_dur else None,
                "obd_rpm_after_max": max(e_aft) if e_aft else None,
                "obd_run_after": max(run_aft) if run_aft else None,
                "b617_set": sorted(set(win(b617, a0 - 2, a1 + 12))),
                "b644_set": sorted(set(win(b644, a0 - 1, a1 + 1))),
                "evap": sorted(set(win(evap, a0 - 5, a1 + 5))),
                "caught": caught,
                # how long the engine had been stopped: last generator speed >= 600
                # before this attempt (None = not seen running earlier in the log)
                "off_s": (round(a0 - max(x[0] for x in rpm if x[0] < a0 and x[1] >= 600), 1)
                          if any(x[0] < a0 and x[1] >= 600 for x in rpm) else None),
            })
        report[name] = rows
        print("  attempts %d, not caught %d" % (len(rows), sum(not r["caught"] for r in rows)))
        for i, r in enumerate(rows):
            nxt = rows[i + 1]["t"] - r["t"] if i + 1 < len(rows) else None
            if not r["caught"] or (i > 0 and not rows[i - 1]["caught"]):
                print("   t=%9.3f dur=%.3f peak=%d genrpm_dur=%s genrpm_aft=%s obd_dur=%s "
                      "obd_aft=%s run=%s 617=%s 644=%s evap=%s caught=%s next=%s"
                      % (r["t"], r["dur_s"], r["peak"], r["gen_rpm_during_max"],
                         r["gen_rpm_after_max"], r["obd_rpm_during_max"],
                         r["obd_rpm_after_max"], r["obd_run_after"],
                         ["0x%02X" % b for b in r["b617_set"]],
                         ["0x%02X" % b for b in r["b644_set"]], r["evap"], r["caught"],
                         None if nxt is None else round(nxt, 3)))
        print("  every attempt: t, off_s, caught")
        for r in rows:
            print("    %9.3f off=%s %s" % (r["t"], r["off_s"], "caught" if r["caught"] else "NOT"))
        caught_d = [r["dur_s"] for r in rows if r["caught"]]
        if caught_d:
            caught_d.sort()
            print("  caught attempts: dur min %.3f median %.3f max %.3f"
                  % (caught_d[0], caught_d[len(caught_d) // 2], caught_d[-1]))
    with open(os.path.join(OUT_DIR, "phase3_raw_attempts.json"), "w") as f:
        json.dump(report, f, indent=0)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        RUN_PHASES = {int(a) for a in sys.argv[1:]}
    if 3 in RUN_PHASES:
        phase3()
    eps = None
    if 1 in RUN_PHASES:
        eps = phase1()
    if 2 in RUN_PHASES:
        if eps is None:
            with open(os.path.join(OUT_DIR, "phase1_episodes.json")) as f:
                eps = json.load(f)
        rows = phase2(eps)
        print("classified %d episodes -> %s" % (len(rows), OUT_DIR))


def phase4():
    """How did the engine stop before each start attempt? For every attempt, find the
    last instant generator speed was >= 600 rpm before it (the stop), and read what
    the VCM was asking for over the 3 s before that instant: gen_rpm_ref >= 0 means
    it still wanted the engine (an involuntary stop -- a stall), < 0 is its engine-off
    null (a commanded stop). Also reports the 0x649 evap flag at the stop."""
    import cantools
    from canre.parsers import parse_file
    pt_db = cantools.database.load_file("projects/vtrux/vtrux-powertrain-experimental.dbc")
    epri_db = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
    with open(os.path.join(OUT_DIR, "phase3_raw_attempts.json")) as f:
        report = json.load(f)
    out = {}
    for name in RAW_LOGS:
        filt = os.path.join(OUT_DIR, name.replace(".log", "_filtered.log"))
        frames = list(parse_file(filt))
        pt = [c for c in {fr.bus for fr in frames}
              if any(fr.bus == c and fr.arbitration_id == 0x051 for fr in frames[:20000])]
        pt = pt[0]
        ref, rpm, evap = [], [], []
        for fr in frames:
            if fr.bus != pt:
                continue
            d = bytes(fr.data)
            if fr.arbitration_id == 0x051 and len(d) >= 6:
                m = pt_db.decode_message(0x051, d, decode_choices=False)
                ref.append((fr.timestamp, m["gen_rpm_ref"], m["gen_torque_cmd"]))
            elif fr.arbitration_id == 0x054 and len(d) >= 5:
                rpm.append((fr.timestamp, epri_db.decode_message(0x054, d, decode_choices=False)["GENE_RotSpd"]))
            elif fr.arbitration_id == 0x649 and len(d) >= 8:
                evap.append((fr.timestamp, pt_db.decode_message(0x649, d, decode_choices=False)["vcm_evap_active"]))
        for s in (ref, rpm, evap):
            s.sort(key=lambda x: x[0])
        rows = []
        print(name)
        seen_stop = set()
        for r in report[name]:
            a0 = r["t"]
            prior = [x[0] for x in rpm if x[0] < a0 and x[1] >= 600]
            if not prior:
                continue
            t_stop = max(prior)
            if t_stop in seen_stop:
                continue              # second segment of the same start sequence
            seen_stop.add(t_stop)
            refs = [x[1] for x in ref if t_stop - 3 <= x[0] <= t_stop]
            # A first revision classified on `refs` alone and called EVERY stop a
            # stall, including 4- and 11-minute engine-off periods: the reference
            # is still >= 0 in the seconds before any stop, so it cannot separate
            # the two. What separates them is AFTER the stop: a commanded stop
            # drops to the engine-off null (< 0); after a stall the VCM keeps
            # asking. Fraction of the 5 s after the stop spent at >= 0:
            post = [x[1] for x in ref if t_stop < x[0] <= t_stop + 5]
            frac_wanted = (sum(1 for v in post if v >= 0) / len(post)) if post else None
            ev = sorted({x[1] for x in evap if t_stop - 5 <= x[0] <= t_stop + 1})
            kind = ("no data" if frac_wanted is None else
                    "STALL (VCM kept asking)" if frac_wanted >= 0.95 else
                    "commanded stop" if frac_wanted <= 0.05 else
                    "mixed (%.2f)" % frac_wanted)
            row = {"attempt_t": a0, "stop_t": round(t_stop, 3), "off_s": round(a0 - t_stop, 1),
                   "rpm_ref_min": min(refs) if refs else None,
                   "rpm_ref_max": max(refs) if refs else None,
                   "post_frac_wanted": frac_wanted,
                   "evap_at_stop": ev, "stop_kind": kind, "caught": r["caught"]}
            rows.append(row)
            print("  start@%9.3f %-6s off=%5.1fs  stop@%9.3f  rpm_ref[%s..%s]  evap=%s  %s"
                  % (a0, "caught" if r["caught"] else "FAILED", row["off_s"], t_stop,
                     row["rpm_ref_min"], row["rpm_ref_max"], ev, kind))
        out[name] = rows
    with open(os.path.join(OUT_DIR, "phase4_stop_kind.json"), "w") as f:
        json.dump(out, f, indent=0)


if __name__ == "__main__" and 4 in RUN_PHASES:
    phase4()
