"""Exhaustive byte-level hunt for what makes truklog_M2 escalate in 8.810 s.

Four of five main-orig steady-state escalations sit at 10.165-10.259 s. truklog_M2
sits at 8.810 s and no DECODED signal explains it. This goes past the decoded set:
every ID in 0x400-0x5FF (the BMS-relevant range), every byte, compared across all five.

Three passes:
  A. PRESENCE   -- IDs seen in some sessions but not others
  B. VALUE      -- every ID.byte at the TYPE1 instant, flagging bytes where M2 differs
                   from ALL four others (M2-unique) and where M2 is outside their range
  C. DYNAMICS   -- bytes that CHANGE during the TYPE1->TYPE3 countdown, per session.
                   A byte that moves only in M2 (or moves in the cluster but not M2)
                   is the strongest available lead.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/m2_outlier_bytewise.py
"""
import sys
import os
import re
import glob
from collections import defaultdict

sys.path.insert(0, ".")

BM = re.compile(r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")

LO, HI = 0x400, 0x5FF          # BMS-relevant standard-ID range
PRE_WINDOW = 60.0              # seconds before TYPE1 to sample "steady" value


def chunks(pattern, prefix):
    cand = {}
    for p in glob.glob(pattern, recursive=True):
        n = os.path.basename(p)
        if not n.startswith(prefix):
            continue
        try:
            sz = os.path.getsize(p)
        except OSError:
            continue
        if n not in cand or sz > cand[n][1]:
            cand[n] = (p, sz)

    def tnum(n):
        m = re.search(r"_T(\d+)", n)
        return int(m.group(1)) if m else 0
    return [v[0] for k, v in sorted(cand.items(), key=lambda kv: tnum(kv[0]))]


SESSIONS = {
    "M2*": chunks("projects/vtrux/logs/**/truklog_M2_T*.log", "truklog"),
    "M0": chunks("projects/vtrux/logs/**/truklog_M0_T*.log", "truklog"),
    "M1": chunks("projects/vtrux/logs/**/truklog_M1_T*.log", "truklog"),
    "M3": chunks("projects/vtrux/logs/**/debuglog_M3_T*.log", "debuglog"),
    "0822": ["projects/vtrux/logs/full-charge-then-fail.log"],
}
CLUSTER = ["M0", "M1", "M3", "0822"]


def stream(paths):
    base = last = 0.0
    for p in paths:
        first = None
        try:
            fh = open(p, "r", encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                if line[:1] == "*":
                    continue
                m = BM.match(line)
                if not m:
                    continue
                hh, mm, ss, tk, idh, _x, rest = m.groups()
                aid = int(idh, 16)
                if not (LO <= aid <= HI):
                    continue
                t = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(tk) / 10000.0
                try:
                    d = bytes(int(b, 16) for b in rest.split())
                except ValueError:
                    continue
                if first is None:
                    first = t
                    base = last
                tt = base + (t - first)
                if tt < last:
                    tt = last
                last = max(last, tt)
                yield tt, aid, d


def analyse(paths):
    """Return (at_t1, at_pre, dyn, ids_seen, t1, t3)."""
    latest = {}
    at_pre = None
    at_t1 = None
    prev_alarm = None
    t1 = t3 = None
    win = defaultdict(set)          # aid -> set of payloads seen in [t1, t3]
    pending_pre = None

    for t, aid, d in stream(paths):
        latest[aid] = d
        if aid == 0x410 and len(d) >= 2:
            a = (d[1] >> 6) & 3
            if prev_alarm is not None and a != prev_alarm:
                if a == 1 and prev_alarm == 0 and t1 is None:
                    t1 = t
                    at_t1 = dict(latest)
                elif a == 3 and prev_alarm == 1 and t1 is not None and t3 is None:
                    t3 = t
            prev_alarm = a
        if t1 is None:
            # keep a snapshot ~PRE_WINDOW old
            if pending_pre is None or t - pending_pre[0] > 5.0:
                pending_pre = (t, dict(latest))
            if pending_pre and False:
                pass
        if t1 is not None and t3 is None:
            win[aid].add(d)
        if t3 is not None and t > t3 + 0.5:
            break
    # crude pre-window snapshot: re-stream is expensive, approximate with pending
    at_pre = pending_pre[1] if pending_pre else {}
    return at_t1 or {}, at_pre, win, set(latest), t1, t3


data = {}
for name, paths in SESSIONS.items():
    if not paths:
        print("%-6s NO FILES" % name)
        continue
    print("scanning %-6s (%d chunks)..." % (name, len(paths)), flush=True)
    data[name] = analyse(paths)

names = ["M2*"] + CLUSTER
print()
print("=" * 118)
print("  A. PRESENCE -- IDs in 0x400-0x5FF seen per session")
print("=" * 118)
allids = set()
for n in names:
    allids |= data[n][3]
print("  %-8s " % "ID" + "".join("%-8s" % n for n in names) + "  note")
print("  " + "-" * 114)
for aid in sorted(allids):
    row = ["yes" if aid in data[n][3] else "--" for n in names]
    note = ""
    if row[0] == "yes" and all(r == "--" for r in row[1:]):
        note = "<== ONLY IN M2"
    elif row[0] == "--" and all(r == "yes" for r in row[1:]):
        note = "<== MISSING FROM M2"
    print("  0x%03X    " % aid + "".join("%-8s" % r for r in row) + "  " + note)

print()
print("=" * 118)
print("  B. VALUE AT TYPE1 -- every ID.byte; flags where M2 stands apart")
print("=" * 118)
print("  %-12s " % "ID.byte" + "".join("%-8s" % n for n in names) + "  verdict")
print("  " + "-" * 114)
uniq = []
outside = []
for aid in sorted(allids):
    payloads = {n: data[n][0].get(aid) for n in names}
    if payloads["M2*"] is None:
        continue
    if any(payloads[n] is None for n in CLUSTER):
        continue
    ln = min(len(payloads[n]) for n in names)
    for b in range(ln):
        vals = {n: payloads[n][b] for n in names}
        m2v = vals["M2*"]
        others = [vals[n] for n in CLUSTER]
        if len(set(others)) == 1 and m2v == others[0]:
            continue                      # all identical, boring
        verdict = ""
        if all(m2v != o for o in others):
            verdict = "<== M2 UNIQUE"
            uniq.append((aid, b, m2v, others))
        elif m2v < min(others) or m2v > max(others):
            verdict = "<- M2 outside cluster range"
            outside.append((aid, b, m2v, others))
        if verdict or len(set(others)) > 1:
            print("  0x%03X.B%-6d " % (aid, b)
                  + "".join("%-8s" % ("%02X" % vals[n]) for n in names)
                  + "  " + verdict)

print()
print("  --> %d M2-unique bytes, %d bytes where M2 is outside the cluster range"
      % (len(uniq), len(outside)))

print()
print("=" * 118)
print("  C. DYNAMICS -- bytes that CHANGE during the TYPE1->TYPE3 countdown")
print("=" * 118)
for n in names:
    win = data[n][2]
    t1, t3 = data[n][4], data[n][5]
    movers = []
    for aid, payloads in sorted(win.items()):
        if len(payloads) < 2:
            continue
        ln = min(len(p) for p in payloads)
        for b in range(ln):
            vs = set(p[b] for p in payloads)
            if len(vs) > 1:
                movers.append("0x%03X.B%d(%d vals)" % (aid, b, len(vs)))
    print("  %-6s  gap=%.3fs  %d moving bytes" % (n, (t3 - t1) if t1 and t3 else -1, len(movers)))
    print("          %s" % (", ".join(movers[:24]) if movers else "(none)"))
    if len(movers) > 24:
        print("          ... +%d more" % (len(movers) - 24))
