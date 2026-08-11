"""Do 0x4C9 / 0x4F1 / 0x4F3 ever appear on the PT bus outside truklog_M2_T19?

*** ANSWERED 2026-08-09 WITHOUT RUNNING THIS -- DO NOT RE-RUN, THE PREMISE IS FALSE ***

The premise was that GM IDs had appeared on the powertrain bus. They had not. In
truklog_M2_T19 the dongle was briefly moved OFF the PT bus and onto a GM bus while
logging:

    t=513.2..515.8   0 frames                    (disconnected)
    t=516.3..520.4   ~800 frames/s, ALL GM IDs,
                     ZERO PT anchors             (on a GM bus, 4.12 s)
    t=520.8..523.3   0 frames                    (disconnected again)

3310 frames / 20 GM IDs, and not one PT anchor throughout. The three IDs this script
looks for are just the rarest members of that set -- searching for only those made a
whole-bus change look like a 16-frame anomaly.

Kept for the per-window bus-identification pattern, which is still useful. See
`../../logs/README.md` corpus-hygiene item 5.


A 16-frame, 3.5 s burst of these GM chassis IDs was found on bus 1 of
truklog_M2_T19.log, ~10 min before that session's TYPE1. Per vtrux.md they belong to
the GM buses and should never be on the powertrain bus.

Scans the corpus, identifies the PT bus per file by the 0x051 anchor (never by channel
number), and reports every occurrence of the three IDs on that bus.

Run from project root:
  py -3.12 projects/vtrux/notes/artifacts/gmlan_on_pt_scan.py [--cap MB]
"""
import sys
import os
import re
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, ".")

CAP_MB = 1200
if "--cap" in sys.argv:
    CAP_MB = float(sys.argv[sys.argv.index("--cap") + 1])

TARGETS = {0x4C9, 0x4F1, 0x4F3}
PT_ANCHOR = 0x051

DIRS = [Path("projects/vtrux/logs"), Path("../../CANLogs/VtruxLogs")]

BM = re.compile(r"^(\d+):(\d+):(\d+):(\d+)\s+\S+\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+\S+\s+(\d+)\s+(.*)$")
CD = re.compile(r"^\((\d+\.\d+)\)\s+(\S+)\s+([0-9A-Fa-f]+)#")


def scan(path):
    """Return (pt_buses, hits) where hits = [(t, aid, bus)] on a PT bus."""
    pt = set()
    seen = []
    t0 = None
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if line[:1] == "*":
                continue
            m = BM.match(line)
            if m:
                hh, mm, ss, tk, ch, idh, _d, _r = m.groups()
                aid = int(idh, 16)
                bus = int(ch)
                t = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(tk) / 10000.0
            else:
                m = CD.match(line.strip())
                if not m:
                    continue
                ep, chan, idh = m.groups()
                aid = int(idh, 16)
                bus = chan
                t = float(ep)
            if t0 is None:
                t0 = t
            if aid == PT_ANCHOR:
                pt.add(bus)
            elif aid in TARGETS:
                seen.append((t - t0, aid, bus))
    hits = [(t, a, b) for (t, a, b) in seen if b in pt]
    return pt, hits, [(t, a, b) for (t, a, b) in seen if b not in pt]


files = []
for dp in DIRS:
    if dp.exists():
        for p in list(dp.rglob("*.log")) + list(dp.rglob("*.txt")):
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if 2000 < sz <= CAP_MB * 1024 * 1024:
                files.append(p)
# dedup by basename, largest copy
byname = {}
for p in files:
    sz = os.path.getsize(p)
    if p.name not in byname or sz > byname[p.name][1]:
        byname[p.name] = (p, sz)
files = [v[0] for v in byname.values()]

print("scanning %d unique files for 0x4C9/0x4F1/0x4F3 on the PT bus...\n" % len(files), flush=True)

on_pt = defaultdict(list)
off_pt = defaultdict(int)
no_anchor = 0
for i, p in enumerate(files):
    if i % 200 == 0:
        print("  %d/%d" % (i, len(files)), flush=True)
    try:
        pt, hits, others = scan(str(p))
    except Exception:
        continue
    if not pt:
        no_anchor += 1
    for t, a, b in hits:
        on_pt[p.name].append((t, a, b))
    for t, a, b in others:
        off_pt[p.name] += 1

print()
print("=" * 104)
print("  0x4C9 / 0x4F1 / 0x4F3 SEEN ON A PT BUS (bus carrying 0x051)")
print("=" * 104)
if not on_pt:
    print("  NONE anywhere in the corpus")
for fn, hits in sorted(on_pt.items()):
    ids = defaultdict(int)
    for _t, a, _b in hits:
        ids["0x%03X" % a] += 1
    span = max(h[0] for h in hits) - min(h[0] for h in hits)
    print("  %-46s %3d frames  span %6.1fs  %s"
          % (fn[:46], len(hits), span, dict(sorted(ids.items()))))

print()
print("  files where these IDs appear on a NON-PT bus (expected, GM buses): %d" % len(off_pt))
for fn, n in sorted(off_pt.items())[:10]:
    print("     %-46s %d frames" % (fn[:46], n))
if len(off_pt) > 10:
    print("     ... +%d more files" % (len(off_pt) - 10))
print()
print("  files with no 0x051 anchor (bus identity unknown, skipped): %d" % no_anchor)
