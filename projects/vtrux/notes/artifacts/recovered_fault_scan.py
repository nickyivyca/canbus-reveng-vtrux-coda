"""Non-terminal / recovered HV fault signatures, plus contactor-state census.

*** SUPERSEDED (2026-08-09) for recovery counts -- use type1_census_merged.py ***

This script scans each `_T{n}` chunk file INDEPENDENTLY, so any fault whose EPO-set and
EPO-clear straddle a chunk boundary is silently dropped. Confirmed miss: the M0_b
self-recovery (boundary at t=5667.11 sits between EPO-set 5662.2 in T9 and EPO-clear
5667.24 in T10). It also does not deduplicate basenames that exist in several folders.
Merged+deduplicated counts are higher: EPO 27->34, alarm 31->38.

Its Q1 CONTACTOR STATE CENSUS remains valid and is not reproduced elsewhere:
all five FAILED_* diagnostic states are 0 frames across 5.67M frames / 1153 logs.
Keep the script for that result; take recovery counts from type1_census_merged.py.

Two questions:

  Q1. Do the BMS's dedicated FAILED_* contactor diagnostic states EVER fire?
      The state machine has FAILED_MAINP_OR_R_WELD(1), FAILED_MAINR_OPEN(3),
      FAILED_MAINN_WELD(4), FAILED_MAINN_OPEN(6), FAILED_MAINP_OPEN(10).
      If a real welded MAINN never sets FAILED_MAINN_WELD, these states are
      decorative and every abort funnels to the generic ALL_OPEN_SHUTDOWN(14).

  Q2. Are there fault signatures during charging/driving that the truck RECOVERED
      from -- i.e. did not end in a latched brick? Looks for:
        - EPO asserted then cleared (0 -> 1 -> 0) without ending the session
        - alarm reaching TYPE3 then returning to a lower state
        - contactor leaving a closed state (11/12) and returning to it
        - iso_r dropping to 0 mid-run then recovering to a valid reading

Uses the fast raw-text ID filter (no full parse), and skips files above SIZE_CAP
so the multi-GB captures do not stall the sweep -- they are scanned separately.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/recovered_fault_scan.py [--cap MB]
"""
import sys
import os
import re
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, ".")

SIZE_CAP_MB = 400
if "--cap" in sys.argv:
    SIZE_CAP_MB = float(sys.argv[sys.argv.index("--cap") + 1])

DIRS = [Path("projects/vtrux/logs"), Path("../../CANLogs/VtruxLogs")]

MAINC = ["ALL_OPEN", "FAILED_MAINP_OR_R_WELD", "CLOSE_MAINR", "FAILED_MAINR_OPEN",
         "FAILED_MAINN_WELD", "CLOSE_MAINN", "FAILED_MAINN_OPEN", "WAIT_PRECHARGE",
         "CLOSE_MAINP", "OPEN_MAINR", "FAILED_MAINP_OPEN", "MAIN_PN_CLOSED_DRIVE",
         "MAIN_P_CLOSED_CHARGE", "SHUTDOWN_REQUEST", "ALL_OPEN_SHUTDOWN", "(idx15)"]
FAILED_STATES = {1, 3, 4, 6, 10}
CLOSED_STATES = {11, 12}
ALARM = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3"}

WATCH = {0x410, 0x420, 0x440}
BM = re.compile(r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
CD = re.compile(r"^\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)$")


def iter_watch(path):
    t0 = None
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if line[:1] == "*":
                continue
            m = BM.match(line)
            if m:
                hh, mm, ss, tk, idh, _d, rest = m.groups()
                aid = int(idh, 16)
                if aid not in WATCH:
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
                if aid not in WATCH:
                    continue
                t = float(ep)
                try:
                    d = bytes.fromhex(pl) if pl else b""
                except ValueError:
                    continue
            if t0 is None:
                t0 = t
            yield t - t0, aid, d


def scan(path):
    state_census = Counter()
    events = []
    prev_st = None
    prev_epo = None
    prev_alarm = None
    prev_iso = None
    epo_up_t = None
    left_closed = None
    for t, aid, d in iter_watch(path):
        if aid == 0x440 and len(d) >= 1:
            st = (d[0] >> 2) & 0xF
            state_census[st] += 1
            if st != prev_st:
                if st in FAILED_STATES:
                    events.append((t, "FAILED_STATE", "%s (from %s)"
                                   % (MAINC[st], MAINC[prev_st] if prev_st is not None else "?")))
                if prev_st in CLOSED_STATES and st not in CLOSED_STATES:
                    left_closed = (t, prev_st, st)
                elif left_closed and st in CLOSED_STATES:
                    events.append((t, "CONTACTOR_RECOVERY",
                                   "%s -> %s -> %s after %.2fs"
                                   % (MAINC[left_closed[1]], MAINC[left_closed[2]],
                                      MAINC[st], t - left_closed[0])))
                    left_closed = None
                prev_st = st
        elif aid == 0x410 and len(d) >= 8:
            epo = (d[0] >> 1) & 1
            alarm = (d[1] >> 6) & 3
            if prev_epo is not None and epo != prev_epo:
                if epo == 1:
                    epo_up_t = t
                elif epo == 0 and epo_up_t is not None:
                    events.append((t, "EPO_RECOVERED",
                                   "EPO cleared after %.2fs" % (t - epo_up_t)))
                    epo_up_t = None
            prev_epo = epo
            if prev_alarm is not None and alarm != prev_alarm:
                if prev_alarm == 3 and alarm < 3:
                    events.append((t, "ALARM_RECOVERED",
                                   "TYPE3 -> %s" % ALARM[alarm]))
            prev_alarm = alarm
        elif aid == 0x420 and len(d) >= 4:
            iso = d[3]
            if prev_iso is not None and prev_iso == 0 and 0 < iso < 250:
                events.append((t, "ISO_RECOVERED", "iso_r 0 -> %d" % iso))
            prev_iso = iso
    return state_census, events


files = []
for dp in DIRS:
    if dp.exists():
        for p in list(dp.rglob("*.log")) + list(dp.rglob("*.txt")):
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if 2000 < sz <= SIZE_CAP_MB * 1024 * 1024:
                files.append(p)

print("scanning %d files (<= %g MB)...\n" % (len(files), SIZE_CAP_MB), flush=True)

total_census = Counter()
all_events = defaultdict(list)
nlogs_with_bms = 0

for i, fp in enumerate(files):
    if i % 200 == 0:
        print("  %d/%d" % (i, len(files)), flush=True)
    try:
        census, evs = scan(str(fp))
    except Exception:
        continue
    if not census:
        continue
    nlogs_with_bms += 1
    total_census.update(census)
    for t, kind, msg in evs:
        all_events[kind].append((fp.name, t, msg))

print("\n%d logs contained BMS contactor data\n" % nlogs_with_bms)

print("=" * 100)
print("  Q1: CONTACTOR STATE CENSUS -- every state ever observed, corpus-wide")
print("=" * 100)
tot = sum(total_census.values())
for idx in range(16):
    n = total_census.get(idx, 0)
    flag = "  <<< DEDICATED FAULT STATE" if idx in FAILED_STATES else ""
    print("  %2d  %-24s %10d frames  %6.2f%%%s"
          % (idx, MAINC[idx], n, 100.0 * n / tot if tot else 0, flag))

print()
print("=" * 100)
print("  Q2: RECOVERED / NON-TERMINAL FAULT EVENTS")
print("=" * 100)
for kind in ("FAILED_STATE", "EPO_RECOVERED", "ALARM_RECOVERED",
             "CONTACTOR_RECOVERY", "ISO_RECOVERED"):
    rows = all_events.get(kind, [])
    print("\n  --- %s : %d occurrence(s) ---" % (kind, len(rows)))
    if not rows:
        print("      none found in corpus")
        continue
    seen = Counter()
    for fn, t, msg in rows:
        seen[fn] += 1
    for fn, t, msg in rows[:40]:
        print("      %-46s t=%9.2f  %s" % (fn[:46], t, msg))
    if len(rows) > 40:
        print("      ... %d more (across %d files)" % (len(rows) - 40, len(seen)))
