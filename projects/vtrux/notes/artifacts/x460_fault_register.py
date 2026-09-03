"""Characterize 0x460 (PT bus, BMS-sourced) as a candidate fault-annunciation register.

Discovery (2026-08-26, type1_micro_forensics.py): in all five main-orig steady-state
escalations, 0x460 is static before TYPE1, begins alternating two content pages within
~20-120 ms of TYPE1 (B2 01<->FC, B3 01<->22, B4 00<->02, B6 01<->00), and switches to a
three-page cycle with new values (F0/B0/FC) right after TYPE3. The m2_outlier bytewise
sweep saw these bytes move but dismissed them because they moved in ALL sessions -- it
was hunting M2-unique bytes. The page content may encode WHICH fault the BMS saw.

This script does a distinct-frame census of 0x460 in windows around each EPO event
across every known fault mode, to test whether the page content discriminates:

  - five main-orig steady-state escalations (expect the same code in all five)
  - deliberate isolation fault, deliberate interlock fault
  - operator unplug (truklog_M2 t~4297, and a clean unplug log)
  - main-orig precharge failures (M4_T20, chargeagain2, 20260802 x2)
  - Truck 3's contactor faults (welded MAINN / bad precharge)

If distinct fault modes show distinct 0x460 page sets, this is a fault-reason register
and the steady-state code is the first direct readout of the mystery trigger.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/x460_fault_register.py
"""
import sys
sys.path.insert(0, ".")

import os
import re
import glob
from collections import Counter, defaultdict

BM_RE = re.compile(
    r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+\d+\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
CD_RE = re.compile(r"^\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)$")
WATCH = {0x410, 0x460}
ALARM = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3"}


def load(paths):
    frames = []
    t0 = None
    for p in paths:
        if not os.path.exists(p):
            print("  MISSING: %s" % p)
            continue
        with open(p, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line[:1] == "*":
                    continue
                m = BM_RE.match(line)
                if m:
                    hh, mm, ss, tk, idh, _dlc, rest = m.groups()
                    aid = int(idh, 16)
                    if aid not in WATCH:
                        continue
                    t = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(tk) / 10000.0
                    try:
                        data = bytes(int(b, 16) for b in rest.split())
                    except ValueError:
                        continue
                else:
                    m = CD_RE.match(line.strip())
                    if not m:
                        continue
                    ep, idh, payload = m.groups()
                    aid = int(idh, 16)
                    if aid not in WATCH:
                        continue
                    if t0 is None:
                        t0 = float(ep)
                    t = float(ep) - t0
                    data = bytes.fromhex(payload) if payload else b""
                frames.append((t, aid, data))
    frames.sort(key=lambda f: f[0])
    return frames


def epo_events(frames):
    """(t_epo, had_type1_lead, alarm_at_minus_11s) for each 0->1 epo edge."""
    events = []
    prev = None
    alarm_hist = []          # (t, alarm)
    for t, aid, d in frames:
        if aid != 0x410 or len(d) < 2:
            continue
        epo = (d[0] >> 1) & 1
        alarm_hist.append((t, (d[1] >> 6) & 3))
        if prev == 0 and epo == 1:
            a11 = None
            lead = False
            for tt, aa in reversed(alarm_hist):
                if tt < t - 11.5:
                    a11 = aa
                    break
            for tt, aa in reversed(alarm_hist):
                if tt >= t - 11.0 and aa == 1:
                    lead = True
                if tt < t - 11.0:
                    break
            events.append((t, lead, ALARM.get(a11, "?")))
        prev = epo
    return events


def census(frames, a, b):
    c = Counter()
    for t, aid, d in frames:
        if aid == 0x460 and a <= t < b:
            c[d.hex(" ").upper()] += 1
    return c


def show(label, c, maxrows=8):
    total = sum(c.values())
    print("    %-28s (%d frames)" % (label, total))
    for v, n in c.most_common(maxrows):
        print("      %6d  %s" % (n, v))
    if len(c) > maxrows:
        print("      ... %d more distinct values" % (len(c) - maxrows))


TARGETS = [
    ("STEADY M0", ["projects/vtrux/logs/actual-failed-charges/truklog_M0_T%d.log" % i for i in range(11)]),
    ("STEADY M1", ["projects/vtrux/logs/actual-failed-charges/truklog_M1_T%d.log" % i for i in range(10, 15)]),
    ("STEADY M2", sorted(glob.glob("projects/vtrux/logs/other-logs/truklog_M2_T1[4-9].log"))
                  + sorted(glob.glob("projects/vtrux/logs/other-logs/truklog_M2_T2[0-1].log"))),
    ("STEADY M3", sorted(glob.glob("projects/vtrux/logs/debuglog_M3_T*.log"))),
    ("STEADY 0822", ["projects/vtrux/logs/full-charge-then-fail.log"]),
    ("ISOLATION (deliberate)", ["projects/vtrux/logs/vtruxisolationtest.log"]),
    ("INTERLOCK (deliberate)", ["projects/vtrux/logs/vtruxinterlocktest.log"]),
    ("PRECHARGE M4_T20", ["projects/vtrux/logs/debuglog_M4_T20.log"]),
    ("PRECHARGE chargeagain2", ["projects/vtrux/logs/vtrux_partstruck_chargeagain2.log"]),
    ("PRECHARGE evapfuse", ["projects/vtrux/logs/vtrux_partstruck_evapfuseexperiment.log"]),
    ("PRECHARGE 20260802", sorted(glob.glob("../../CANLogs/VtruxLogs/vtrux_20260802_123318_T[0-3].log"))),
    ("UNPLUG 20260714", ["../../CANLogs/VtruxLogs/vtrux_20260714_161319_T74.log"]),
    ("GEN-ISO part2", ["projects/vtrux/logs/vtrux_partstruck_testdrive_part2.log"]),
    ("GEN-ISO part3", ["projects/vtrux/logs/vtrux_partstruck_testdrive_part3_engine.log"]),
    ("truck3-welded MAINN", ["projects/vtrux/logs/truck3-logs/truck3-canlog.log"]),
    ("truck3-bad precharge", ["projects/vtrux/logs/truck3-logs/truck3log2.log"]),
    ("truck3-round3 log", ["projects/vtrux/logs/truck3-logs/truck3-truck-3.log"]),
    ("truck3-bms powerloss", ["projects/vtrux/logs/truck3-logs/truck3-truck4-keyoff-on-off-on.log"]),
    ("truck3-export OK (control)", ["projects/vtrux/logs/truck3-logs/truck3-6_key_and_export.txt"]),
    ("truck3-candump 0805a", ["projects/vtrux/logs/truck3-logs/candump-2026-08-05_134035.log"]),
    ("truck3-candump 0805b", ["projects/vtrux/logs/truck3-logs/candump-2026-08-05_135122.log"]),
    ("AFTER-SWAP chargefail 0216", ["projects/vtrux/logs/canlog_20260216_212016.log"]),
    ("OCT25 truk1log", sorted(glob.glob("projects/vtrux/logs/truk1log_M0_T*.log"))),
    ("SEP15 stuck-TYPE2", ["projects/vtrux/logs/other-logs/truklog_M0_T1.log"]),
    ("SEP19 stuck-TYPE2", ["projects/vtrux/logs/other-logs/truklog_M0_T0.log"]),
    ("SEP20 stuck-TYPE2", ["projects/vtrux/logs/other-logs/TRUKLOG_M1_T0.log"]),
    ("GEN-ISO part2", ["projects/vtrux/logs/vtrux_partstruck_testdrive_part2.log"]),
    ("GEN-ISO part3", ["projects/vtrux/logs/vtrux_partstruck_testdrive_part3_engine.log"]),
]

for name, paths in TARGETS:
    print("=" * 96)
    print("%s" % name)
    frames = load(paths)
    if not frames:
        print("  no frames")
        continue
    evs = epo_events(frames)
    if not evs:
        print("  no EPO events; baseline 0x460 census over whole log:")
        show("all", census(frames, -1, 1e12))
        continue
    for t_epo, lead, a11 in evs:
        print("  EPO at t=%.3f   TYPE1 lead: %s   alarm at T-11.5s: %s" % (t_epo, lead, a11))
        show("baseline [EPO-70 .. EPO-12)", census(frames, t_epo - 70, t_epo - 12))
        show("countdown [EPO-10.5 .. EPO)", census(frames, t_epo - 10.5, t_epo))
        show("trip      [EPO .. EPO+5)", census(frames, t_epo, t_epo + 5))
        show("latched   [EPO+5 .. EPO+30)", census(frames, t_epo + 5, t_epo + 30))
        print()
