"""Hunt for OTHER fault-annunciator-like messages beside 0x460.

0x460 turned out to be the BMS fault-record list: static at rest, content changes at
fault events. This sweep asks whether any other PT-bus ID behaves the same way --
a secondary fault-code register, echo, or extended record store.

Method: for one representative log of each fault mode, find every (ID, byte) that is
QUIET in baseline (<=2 distinct values in EPO-120..EPO-10) but takes NEW values in
the trip window (EPO-10..EPO+10). Measurement bytes churn in baseline and are
self-excluded. Known status IDs (0x400/410/411/412/420/430/440/460) are reported in
a separate bucket so novel responders stand out.

Also prints the full set of IDs present in 0x440-0x4FF per log (are there siblings
of 0x460 at all?).

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/fault_annunciator_sweep.py
"""
import sys
sys.path.insert(0, ".")

import re
from collections import defaultdict

BM_RE = re.compile(
    r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
CD_RE = re.compile(r"^\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)$")
KNOWN = {0x400, 0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460}


def load(path):
    frames = []
    t0 = None
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if line[:1] == "*":
                continue
            m = BM_RE.match(line)
            if m:
                hh, mm, ss, tk, idh, _dlc, rest = m.groups()
                aid = int(idh, 16)
                if aid > 0x7FF:
                    continue
                t = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(tk) / 10000.0
                try:
                    d = bytes(int(b, 16) for b in rest.split())
                except ValueError:
                    continue
            else:
                m = CD_RE.match(line.strip())
                if not m:
                    continue
                ep, idh, pl = m.groups()
                aid = int(idh, 16)
                if aid > 0x7FF:
                    continue
                t = float(ep)
                d = bytes.fromhex(pl) if pl else b""
            if t0 is None:
                t0 = t
            frames.append((t - t0, aid, d))
    return frames


def find_epo(frames, nth=1):
    prev = None
    count = 0
    for t, aid, d in frames:
        if aid != 0x410 or len(d) < 1:
            continue
        e = (d[0] >> 1) & 1
        if prev == 0 and e == 1:
            count += 1
            if count == nth:
                return t
        prev = e
    return None


def sweep(name, path, nth=1):
    frames = load(path)
    if not frames:
        print("== %s: no frames" % name)
        return
    epo = find_epo(frames, nth)
    if epo is None:
        print("== %s: no EPO found" % name)
        return
    base = defaultdict(set)
    trip = defaultdict(set)
    ids_46x = set()
    for t, aid, d in frames:
        if 0x440 <= aid <= 0x4FF:
            ids_46x.add(aid)
        for i, b in enumerate(d):
            if epo - 120 <= t < epo - 10:
                base[(aid, i)].add(b)
            elif epo - 10 <= t <= epo + 10:
                trip[(aid, i)].add(b)
    print("== %s  (EPO #%d at t=%.1f)" % (name, nth, epo))
    print("   IDs present 0x440-0x4FF: %s" % " ".join("%03X" % i for i in sorted(ids_46x)))
    novel = defaultdict(list)
    known = defaultdict(list)
    for key, tv in sorted(trip.items()):
        bv = base.get(key, set())
        if len(bv) <= 2 and bv and (tv - bv):
            aid, i = key
            entry = "B%d %s->%s" % (i, "/".join("%02X" % v for v in sorted(bv)),
                                    "/".join("%02X" % v for v in sorted(tv - bv)[:6]))
            (known if aid in KNOWN else novel)[aid].append(entry)
    print("   NOVEL fault-responsive quiet bytes:")
    if not novel:
        print("     none")
    for aid in sorted(novel):
        print("     0x%03X: %s" % (aid, "; ".join(novel[aid][:8])))
    print("   (known status IDs responding: %s)" % " ".join("0x%03X" % a for a in sorted(known)))
    print()


sweep("STEADY 0822 (full-charge-then-fail)", "projects/vtrux/logs/full-charge-then-fail.log")
sweep("PRECHARGE M4_T20", "projects/vtrux/logs/debuglog_M4_T20.log")
sweep("ISOLATION forced", "projects/vtrux/logs/vtruxisolationtest.log")
sweep("INTERLOCK deliberate", "projects/vtrux/logs/vtruxinterlocktest.log")
sweep("GEN-ISO part3", "projects/vtrux/logs/vtrux_partstruck_testdrive_part3_engine.log")
sweep("truck3-0805a", "projects/vtrux/logs/truck3-logs/candump-2026-08-05_134035.log")
