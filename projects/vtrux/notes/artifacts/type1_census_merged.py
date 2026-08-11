"""TYPE1 census + recovery scan, with chunked sessions correctly MERGED.

Fixes the bug in recovered_fault_scan.py: that scan processed each `_T{n}` chunk
independently, so any fault whose EPO-set and EPO-clear straddled a chunk boundary
was silently dropped. Confirmed miss: the M0_b self-recovery, where the boundary
falls at t=5667.11 between EPO-set (5662.2, T9) and EPO-clear (5667.24, T10).

Session grouping uses canre.utils.merge.detect_capture_groups (the project's
existing utility). Frame reading uses a raw-text ID filter for speed, chaining the
time base across chunks in order.

Reports:
  A. TYPE1 CENSUS -- every NONE->TYPE1, and its outcome:
       ESCALATED   -> TYPE3 (with the gap)
       CLEARED     -> back to NONE/TYPE2 without escalating  <-- the interesting case
       TRUNCATED   -> log ended while still TYPE1
  B. RECOVERY EVENTS -- EPO / alarm / contactor, with unplug-confound check.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/type1_census_merged.py [--cap MB]
"""
import sys
import os
import re
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, ".")

from canre.utils.merge import detect_capture_groups  # noqa: E402

CAP_MB = 1200
if "--cap" in sys.argv:
    CAP_MB = float(sys.argv[sys.argv.index("--cap") + 1])

DIRS = [Path("projects/vtrux/logs"), Path("../../CANLogs/VtruxLogs")]

MAINC = ["ALL_OPEN", "F_MAINP_R_WELD", "CLOSE_MAINR", "F_MAINR_OPEN", "F_MAINN_WELD",
         "CLOSE_MAINN", "F_MAINN_OPEN", "WAIT_PRECHARGE", "CLOSE_MAINP", "OPEN_MAINR",
         "F_MAINP_OPEN", "PN_CLOSED_DRIVE", "P_CLOSED_CHARGE", "SHUTDOWN_REQ",
         "ALL_OPEN_SHUTDOWN", "(15)"]
ALARM = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3"}
CLOSED = {11, 12}
IDS = {0x410, 0x440, 0x592}

BM = re.compile(r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
CD = re.compile(r"^\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)$")


def read_chunked(paths):
    """Yield (t, aid, data, filename) across chunks with a continuous time base."""
    base = 0.0
    last = 0.0
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
                if m:
                    hh, mm, ss, tk, idh, _x, rest = m.groups()
                    aid = int(idh, 16)
                    if aid not in IDS:
                        continue
                    t = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(tk) / 10000.0
                    try:
                        d = bytes(int(b, 16) for b in rest.split())
                    except ValueError:
                        continue
                else:
                    m = CD.match(line.strip())
                    if not m:
                        continue
                    ep, idh, pl = m.groups()
                    aid = int(idh, 16)
                    if aid not in IDS:
                        continue
                    t = float(ep)
                    try:
                        d = bytes.fromhex(pl) if pl else b""
                    except ValueError:
                        continue
                if not d:
                    continue
                if first is None:
                    first = t
                    base = last
                tt = base + (t - first)
                if tt < last:
                    tt = last
                last = max(last, tt)
                yield tt, aid, d, os.path.basename(p)


def scan_session(paths):
    t1_events = []          # (t_start, outcome, gap_or_dur, file)
    recoveries = []         # (t, kind, detail, trigger_note)
    prev = {}
    t1_open = None
    epo_up = None
    left = None
    unplug_t = None

    for t, aid, d, fn in read_chunked(paths):
        if aid == 0x592 and len(d) >= 1:
            ev = (d[0] >> 1) & 1
            if prev.get("evse") is not None and prev["evse"] == 1 and ev == 0:
                unplug_t = t
            prev["evse"] = ev
            ig = (d[0] >> 4) & 1
            if prev.get("ign") is not None and prev["ign"] != ig:
                recoveries.append((t, "_ACTION", "IGNITION %d->%d" % (prev["ign"], ig), ""))
            prev["ign"] = ig
        elif aid == 0x410 and len(d) >= 8:
            al = (d[1] >> 6) & 3
            epo = (d[0] >> 1) & 1
            onp = (d[0] >> 2) & 1
            if prev.get("onp") is not None and prev["onp"] == 1 and onp == 0:
                unplug_t = t
            if prev.get("onp") is not None and prev["onp"] != onp:
                recoveries.append((t, "_ACTION", "on_plug %d->%d" % (prev["onp"], onp), ""))
            prev["onp"] = onp

            pa = prev.get("alarm")
            if pa is not None and al != pa:
                if al == 1 and pa == 0:
                    t1_open = (t, fn)
                elif t1_open is not None:
                    if al == 3:
                        t1_events.append((t1_open[0], "ESCALATED", t - t1_open[0], t1_open[1]))
                    else:
                        t1_events.append((t1_open[0], "CLEARED->%s" % ALARM[al],
                                          t - t1_open[0], t1_open[1]))
                    t1_open = None
                if pa == 3 and al < 3:
                    recoveries.append((t, "ALARM_RECOVERED", "TYPE3 -> %s" % ALARM[al], ""))
            prev["alarm"] = al

            pe = prev.get("epo")
            if pe is not None and epo != pe:
                if epo == 1:
                    epo_up = t
                    was_unplug = (unplug_t is not None and 0 <= t - unplug_t <= 1.0)
                    prev["epo_unplug"] = was_unplug
                elif epo_up is not None:
                    tag = "PRECEDED-BY-UNPLUG" if prev.get("epo_unplug") else "no unplug before EPO"
                    recoveries.append((t, "EPO_RECOVERED",
                                       "held %.2fs" % (t - epo_up), tag))
                    epo_up = None
            prev["epo"] = epo
        elif aid == 0x440 and len(d) >= 1:
            m2 = (d[0] >> 2) & 0xF
            pm = prev.get("mainc")
            if pm is not None and m2 != pm:
                if pm in CLOSED and m2 not in CLOSED:
                    left = (t, pm, m2)
                elif left and m2 in CLOSED:
                    recoveries.append((t, "CONTACTOR_RECOVERY",
                                       "%s -> %s -> %s (down %.2fs)"
                                       % (MAINC[left[1]], MAINC[left[2]], MAINC[m2], t - left[0]),
                                       "via SHUTDOWN_REQ" if left[2] == 13 else "via fault path"))
                    left = None
            prev["mainc"] = m2
    if t1_open is not None:
        t1_events.append((t1_open[0], "TRUNCATED", -1, t1_open[1]))
    return t1_events, recoveries


# ---- build session list --------------------------------------------------
all_files = []
for dp in DIRS:
    if dp.exists():
        for p in list(dp.rglob("*.log")) + list(dp.rglob("*.txt")):
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if 2000 < sz <= CAP_MB * 1024 * 1024:
                all_files.append(p)

# NOTE: canre.utils.merge.detect_capture_groups treats _M{n} as a BUS number and
# merges M0/M1/M2... into one session. AGENTS.md states the opposite for this project:
# "M numbers are separate capture sessions, NOT different CAN buses from the same
# session." So we group by (prefix, M) here instead of prefix alone.
#
# Also: the same chunk basename exists in several folders (e.g. truklog_M0_T0.log is
# in actual-failed-charges/, actual-failed-charges/bel-only/ and other-logs/).
# Deduplicate by basename, preferring the largest copy (the full PT-bus capture over
# a bel-only extract).
by_name = {}
for p in all_files:
    try:
        sz = os.path.getsize(p)
    except OSError:
        continue
    cur = by_name.get(p.name)
    if cur is None or sz > cur[1]:
        by_name[p.name] = (p, sz)
uniq_files = [v[0] for v in by_name.values()]
print("deduplicated %d -> %d files by basename" % (len(all_files), len(uniq_files)), flush=True)

_MT = re.compile(r"^(?P<pre>.+)_M(?P<m>\d+)_T(?P<t>\d+)\.(log|txt)$", re.I)
_T = re.compile(r"^(?P<pre>.+)_T(?P<t>\d+)\.(log|txt)$", re.I)

sessions = defaultdict(list)
for p in uniq_files:
    m = _MT.match(p.name)
    if m:
        sessions["%s_M%s" % (m.group("pre"), m.group("m"))].append((int(m.group("t")), p))
        continue
    m = _T.match(p.name)
    if m:
        sessions[m.group("pre")].append((int(m.group("t")), p))
        continue
    sessions[p.name].append((0, p))
sessions = {k: [p for _n, p in sorted(v)] for k, v in sessions.items()}

print("%d unique files -> %d sessions\n" % (len(uniq_files), len(sessions)), flush=True)

T1_ALL = []
REC_ALL = defaultdict(list)
for i, (name, paths) in enumerate(sorted(sessions.items())):
    if i % 100 == 0:
        print("  %d/%d sessions..." % (i, len(sessions)), flush=True)
    try:
        t1s, recs = scan_session(paths)
    except Exception:
        continue
    for e in t1s:
        T1_ALL.append((name, len(paths)) + e)
    for t, kind, detail, note in recs:
        if kind != "_ACTION":
            REC_ALL[kind].append((name, t, detail, note))

print()
print("=" * 116)
print("  A. TYPE1 CENSUS -- every NONE->TYPE1 transition and its outcome")
print("=" * 116)
print("  %-40s %-4s %-11s %-16s %-10s %s" % ("session", "chk", "t", "outcome", "gap(s)", "file"))
print("  " + "-" * 112)
for name, nch, t, outcome, gap, fn in sorted(T1_ALL, key=lambda r: (r[3], r[0])):
    print("  %-40s %-4d %-11.2f %-16s %-10s %s"
          % (name[:40], nch, t, outcome, ("%.3f" % gap) if gap >= 0 else "-", fn[:28]))
esc = [r for r in T1_ALL if r[3] == "ESCALATED"]
clr = [r for r in T1_ALL if r[3].startswith("CLEARED")]
print("\n  TOTAL: %d TYPE1 events | %d escalated to TYPE3 | %d cleared without escalating | %d truncated"
      % (len(T1_ALL), len(esc), len(clr), len(T1_ALL) - len(esc) - len(clr)))
if esc:
    gaps = [r[4] for r in esc]
    print("  escalation gaps: min=%.3f  max=%.3f  mean=%.3f  n=%d"
          % (min(gaps), max(gaps), sum(gaps) / len(gaps), len(gaps)))

for kind in ("EPO_RECOVERED", "ALARM_RECOVERED", "CONTACTOR_RECOVERY"):
    rows = REC_ALL.get(kind, [])
    print()
    print("=" * 116)
    print("  B. %s -- %d events (chunk-merged)" % (kind, len(rows)))
    print("=" * 116)
    for name, t, detail, note in sorted(rows)[:60]:
        print("  %-42s %-10.2f %-34s %s" % (name[:42], t, detail[:34], note))
    if len(rows) > 60:
        print("  ... %d more" % (len(rows) - 60))
