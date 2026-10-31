"""Test what the AC 10 xx parameter means, across the corpus of AC-record EPO events.

Hypothesis (from ac1001_trip_forensics.py on the 2026-06-18 trip): the BMS pushes
`AC 10 01` when it EPOs because the VCM's 0x400 control message timed out
(VCM died mid-drive), while `AC 10 00` is the EPO commanded by the VCM through
0x400 hsc_bcm_epo=1 (or at least with 0x400 still alive).

For each event log: find every bcm_epo 0->1 on 0x410 (PT bus identified by content:
the bus carrying DLC-8 0x410 frames) and report, relative to that instant:
  - the last 0x400 frame before it (gap), and hsc_bcm_epo in the frames before/after
  - the first hsc_bcm_epo=1 frame (lead time, negative = VCM commanded first)
  - 0x053 OperationState in the 2 s around it
  - the 0x460 AC record pushed within 3 s after

Run from project root:
  python3.13 projects/vtrux/notes/artifacts/ac_param_discriminator.py > projects/vtrux/notes/artifacts/ac_param_discriminator.txt
"""
import sys
sys.path.insert(0, ".")

import glob
from collections import defaultdict

from canre.parsers import parse_file

OPSTATE = {0: "INIT", 1: "STBY", 2: "ACTIVATION", 3: "DEACTIVATION", 4: "OPERATIONAL", 5: "FAILURE", 6: "SHTDWN", 7: "WAIT4COOLING", 8: "PWR_OFF_RDY"}

EVENTS = [
    ("TRIP 20260618 (AC 10 01)", ["../../CANLogs/VtruxLogs/vtrux_20260618_002023_T0.log"]),
    ("ISOLATION (deliberate)", ["projects/vtrux/logs/vtruxisolationtest.log"]),
    ("INTERLOCK (deliberate)", ["projects/vtrux/logs/vtruxinterlocktest.log"]),
    ("PRECHARGE chargeagain2", ["projects/vtrux/logs/vtrux_partstruck_chargeagain2.log"]),
    ("PRECHARGE evapfuse", ["projects/vtrux/logs/vtrux_partstruck_evapfuseexperiment.log"]),
    ("PRECHARGE 20260802", sorted(glob.glob("projects/vtrux/logs/partsdrive_20260802_T[0-3].log"))),
    ("GEN-ISO part2", ["projects/vtrux/logs/vtrux_partstruck_testdrive_part2.log"]),
    ("GEN-ISO part3", ["projects/vtrux/logs/vtrux_partstruck_testdrive_part3_engine.log"]),
    ("STEADY 0822", ["projects/vtrux/logs/full-charge-then-fail.log"]),
    ("STEADY M3", sorted(glob.glob("projects/vtrux/logs/debuglog_M3_T*.log"))),
    ("PRECHARGE M4_T20", ["projects/vtrux/logs/debuglog_M4_T20.log"]),
    ("REINSTALL boot-fault 0408", sorted(glob.glob("projects/vtrux/logs/*partstruck_reconnect*.log"))),
    ("truck3-welded MAINN", ["projects/vtrux/logs/truck3-logs/truck3-canlog.log"]),
    ("truck3-bad precharge", ["projects/vtrux/logs/truck3-logs/truck3log2.log"]),
    ("truck3-candump 0805a (no AC)", ["projects/vtrux/logs/truck3-logs/candump-2026-08-05_134035.log"]),
    ("UNPLUG 20260714 (no AC)", ["../../CANLogs/VtruxLogs/vtrux_20260714_161319_T74.log"]),
]


def load(paths):
    frames = []
    off = 0.0
    for p in paths:
        chunk = list(parse_file(p))
        if not chunk:
            continue
        base = chunk[0].timestamp
        for f in chunk:
            frames.append((off + f.timestamp - base, f.bus, f.arbitration_id, f.data))
        off += chunk[-1].timestamp - base + 0.001
    return frames


def pt_bus(frames):
    c = defaultdict(int)
    for _, bus, aid, data in frames:
        if aid == 0x410 and len(data) == 8:
            c[bus] += 1
    return max(c, key=c.get) if c else None


def analyze(name, paths):
    print("=" * 96)
    print(name)
    try:
        frames = load(paths)
    except Exception as e:
        print("  LOAD FAILED:", e)
        return
    if not frames:
        print("  no frames")
        return
    bus = pt_bus(frames)
    print("  %d frames, %.0f s, PT bus=%s" % (len(frames), frames[-1][0], bus))
    if bus is None:
        return
    f410 = [(t, d) for t, b, a, d in frames if b == bus and a == 0x410 and len(d) == 8]
    f400 = [(t, d) for t, b, a, d in frames if b == bus and a == 0x400]
    f053 = [(t, d) for t, b, a, d in frames if b == bus and a == 0x053]
    f460 = [(t, d) for t, b, a, d in frames if b == bus and a == 0x460 and len(d) == 8]
    print("  0x400 frames: %d   0x053 frames: %d" % (len(f400), len(f053)))
    epos = []
    prev = None
    for t, d in f410:
        e = (d[0] >> 1) & 1
        if prev == 0 and e == 1:
            epos.append(t)
        prev = e
    if not epos:
        print("  no bcm_epo 0->1 events")
        return
    for te in epos:
        print("  --- bcm_epo 0->1 at t=%.3f" % te)
        before = [(t, d) for t, d in f400 if t <= te]
        after = [(t, d) for t, d in f400 if t > te]
        if before:
            tl, dl = before[-1]
            print("      last 0x400 before EPO: t=%.3f (%.3f s earlier), B0=0x%02X hsc_epo=%d enable=%d close=%d"
                  % (tl, te - tl, dl[0], (dl[0] >> 1) & 1, dl[0] & 1, (dl[0] >> 2) & 1))
            if len(before) > 20:
                gaps = [b[0] - a[0] for a, b in zip(before[-21:], before[-20:])]
                print("      0x400 period in last 20 frames: %.3f..%.3f s" % (min(gaps), max(gaps)))
            first1 = None
            for t, d in f400:
                if te - 30 <= t <= te + 3 and (d[0] >> 1) & 1:
                    first1 = t
                    break
            if first1 is None:
                print("      hsc_bcm_epo=1 never seen in [-30 s, +3 s]")
            else:
                print("      first hsc_bcm_epo=1 at t=%.3f (%+.3f s vs bcm_epo)" % (first1, first1 - te))
        else:
            print("      no 0x400 before EPO")
        if after:
            print("      next 0x400 after EPO: %+.3f s" % (after[0][0] - te))
        else:
            print("      no 0x400 after EPO in log")
        st = [(t, OPSTATE.get(d[0] & 0xF, d[0] & 0xF)) for t, d in f053 if te - 3 <= t <= te + 3]
        chg = []
        last = None
        for t, s in st:
            if s != last:
                chg.append("%+.3f:%s" % (t - te, s))
                last = s
        print("      0x053 OperationState [-3,+3]: %s" % (" ".join(chg) if chg else "(none)"))
        recs = []
        seen = set()
        for t, d in f460:
            if te - 0.5 <= t <= te + 4 and d[0] in (1, 2):
                for k in (2, 5):
                    r = d[k:k + 3].hex(" ")
                    if r != "00 00 00" and r not in seen:
                        seen.add(r)
                        recs.append("%+.2f:%s" % (t - te, r))
        print("      0x460 records seen [-0.5,+4]: %s" % (" | ".join(recs) if recs else "(none)"))


for name, paths in EVENTS:
    analyze(name, paths)
