"""Full detail of every recovered (non-terminal) BMS fault, with its trigger.

Follows up recovered_fault_scan.py. For each EPO-recovery / alarm-recovery /
contactor-recovery it looks in a +/-15 s window for an operator action that
would explain the clear:

  IGNITION 0->1        key-on clear
  EVSE_SW  0->1        EVSE switch cycle
  on_plug  0->1        J1772 plug re-insert
  (none)               UNEXPLAINED -- candidate spontaneous / self-clearing

Reads the file list from recovered_fault_scan.txt so only logs already known to
contain events are re-scanned.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/recovered_fault_detail.py
"""
import sys
import os
import re
from pathlib import Path

sys.path.insert(0, ".")

MAINC = ["ALL_OPEN", "F_MAINP_R_WELD", "CLOSE_MAINR", "F_MAINR_OPEN", "F_MAINN_WELD",
         "CLOSE_MAINN", "F_MAINN_OPEN", "WAIT_PRECHARGE", "CLOSE_MAINP", "OPEN_MAINR",
         "F_MAINP_OPEN", "PN_CLOSED_DRIVE", "P_CLOSED_CHARGE", "SHUTDOWN_REQ",
         "ALL_OPEN_SHUTDOWN", "(15)"]
ALARM = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3"}
CLOSED = {11, 12}
IDS = {0x410, 0x440, 0x592}

BM = re.compile(r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
CD = re.compile(r"^\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)$")

SCAN_OUT = "projects/vtrux/notes/artifacts/recovered_fault_scan.txt"
DIRS = [Path("projects/vtrux/logs"), Path("../../CANLogs/VtruxLogs")]


def find(name):
    for d in DIRS:
        if not d.exists():
            continue
        for p in d.rglob(name):
            return str(p)
    return None


def frames(p):
    t0 = None
    with open(p, "r", encoding="utf-8", errors="ignore") as fh:
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
            if t0 is None:
                t0 = t
            yield t - t0, aid, d


def analyse(path):
    """Return (events, actions). events = list of (t, kind, detail, fault_t)."""
    events, actions = [], []
    pe = pm = po = pev = pig = pal = None
    epo_up = None
    left = None
    for t, aid, d in frames(path):
        if aid == 0x410 and len(d) >= 8:
            epo = (d[0] >> 1) & 1
            onp = (d[0] >> 2) & 1
            al = (d[1] >> 6) & 3
            if pe is not None and epo != pe:
                if epo == 1:
                    epo_up = t
                elif epo_up is not None:
                    events.append((t, "EPO_RECOVERED",
                                   "EPO held %.2fs then cleared" % (t - epo_up), epo_up))
                    epo_up = None
            if pal is not None and al != pal and pal == 3 and al < 3:
                events.append((t, "ALARM_RECOVERED", "TYPE3 -> %s" % ALARM[al], None))
            if po is not None and onp != po:
                actions.append((t, "on_plug %d->%d" % (po, onp)))
            pe, po, pal = epo, onp, al
        elif aid == 0x440 and len(d) >= 1:
            m2 = (d[0] >> 2) & 0xF
            if pm is not None and m2 != pm:
                if pm in CLOSED and m2 not in CLOSED:
                    left = (t, pm, m2)
                elif left and m2 in CLOSED:
                    events.append((t, "CONTACTOR_RECOVERY",
                                   "%s -> %s -> %s (down %.2fs)"
                                   % (MAINC[left[1]], MAINC[left[2]], MAINC[m2], t - left[0]),
                                   left[0]))
                    left = None
            pm = m2
        elif aid == 0x592 and len(d) >= 1:
            evs = (d[0] >> 1) & 1
            ig = (d[0] >> 4) & 1
            if pev is not None and evs != pev:
                actions.append((t, "EVSE_SW %d->%d" % (pev, evs)))
            if pig is not None and ig != pig:
                actions.append((t, "IGNITION %d->%d" % (pig, ig)))
            pev, pig = evs, ig
    return events, actions


def trigger_for(t, actions, win=15.0):
    near = [(abs(a[0] - t), a) for a in actions if abs(a[0] - t) <= win and a[1].endswith("0->1")]
    if not near:
        return "UNEXPLAINED"
    near.sort()
    _, a = near[0]
    return "%s @ %+.2fs" % (a[1], a[0] - t)


names = set()
if os.path.exists(SCAN_OUT):
    for line in open(SCAN_OUT, encoding="utf-8", errors="ignore"):
        m = re.match(r"\s+(\S+\.(?:log|txt))\s+t=", line)
        if m:
            names.add(m.group(1))
print("re-scanning %d logs that contained events...\n" % len(names), flush=True)

buckets = {"EPO_RECOVERED": [], "ALARM_RECOVERED": [], "CONTACTOR_RECOVERY": []}
for n in sorted(names):
    p = find(n)
    if not p:
        continue
    try:
        evs, acts = analyse(p)
    except Exception:
        continue
    for t, kind, detail, ft in evs:
        if kind in buckets:
            buckets[kind].append((n, t, detail, trigger_for(t, acts)))

for kind in ("EPO_RECOVERED", "ALARM_RECOVERED", "CONTACTOR_RECOVERY"):
    rows = buckets[kind]
    print("=" * 118)
    print("  %s -- %d events" % (kind, len(rows)))
    print("=" * 118)
    print("  %-44s %-10s %-40s %s" % ("log", "t", "detail", "trigger"))
    print("  " + "-" * 114)
    for n, t, detail, trig in sorted(rows, key=lambda r: (r[0], r[1])):
        print("  %-44s %-10.2f %-40s %s" % (n[:44], t, detail[:40], trig))
    unexp = [r for r in rows if r[3] == "UNEXPLAINED"]
    print("\n  --> %d/%d UNEXPLAINED (no operator action within 15s)\n"
          % (len(unexp), len(rows)))
