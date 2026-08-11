"""Truck 3 logs 1-4 analysis (BMS master silent investigation).

Phase 1: ID-set diff across all of Truck 3's logs -- which modules are on the bus?
Phase 2: Bus identity check (PT vs Vehicle vs OBD anchors).
Phase 3: HV bus voltage + key state timeline (per log).
Phase 4: Is the BMS powered? BMS-direct (section boards) vs BMS-master block.
Phase 5: 0x596 SoC/permission rebroadcast + BMS-correlated VCM messages.

Run from project root:  py -3.12 projects/vtrux/notes/artifacts/truck3_3_bus_and_state.py
"""
import sys
sys.path.insert(0, ".")

from collections import defaultdict, Counter
from canre.parsers import parse_file

LOGS = {
    "log1_2026-05-15": "projects/vtrux/logs/truck3-logs/truck3-canlog.log",
    "log2_2026-07-02": "projects/vtrux/logs/truck3-logs/truck3log2.log",
    "log3_2026-07-24": "projects/vtrux/logs/truck3-logs/truck3-truck-3.log",
    "log4_2026-07-24": "projects/vtrux/logs/truck3-logs/truck3-truck4-keyoff-on-off-on.log",
}

# Log 4 is the focus of this run; set others True to re-do earlier phases.
PHASE1 = True
PHASE2 = False
PHASE3 = True
PHASE4 = True
PHASE5 = True

FOCUS = "log4_2026-07-24"

BMS_DIRECT = [0x370, 0x371, 0x372, 0x373, 0x374, 0x375, 0x430, 0x505, 0x506, 0x507, 0x50F]
BMS_MASTER = [0x400, 0x410, 0x411, 0x412, 0x420, 0x440, 0x460]


def fmt_id(i):
    return "0x%08X" % i if i > 0x7FF else "0x%03X" % i


def load_ids(path):
    stats = {}
    t0 = None
    tlast = None
    n = 0
    for f in parse_file(path):
        n += 1
        if t0 is None:
            t0 = f.timestamp
        tlast = f.timestamp
        k = f.arbitration_id
        if k in stats:
            c, ft, lt = stats[k]
            stats[k] = (c + 1, ft, f.timestamp)
        else:
            stats[k] = (1, f.timestamp, f.timestamp)
    return stats, (tlast - t0 if t0 is not None else 0.0), n


if PHASE1 or PHASE2:
    loaded = {}
    for name, path in LOGS.items():
        print("loading %s ..." % name, flush=True)
        loaded[name] = load_ids(path)

    names = list(LOGS.keys())
    print()
    print("=" * 78)
    print("PHASE 1 -- ID SET DIFF")
    print("=" * 78)
    for name in names:
        stats, dur, n = loaded[name]
        print("  %-16s  %7d frames  %6.1fs  %3d unique IDs" % (name, n, dur, len(stats)))
    print()

    s2 = set(loaded["log2_2026-07-02"][0])
    s3 = set(loaded["log3_2026-07-24"][0])
    s4 = set(loaded[FOCUS][0])
    print("  IDs in log2 (last known-good BMS) but ABSENT in log4:")
    for i in sorted(s2 - s4):
        print("     %s" % fmt_id(i))
    print()
    print("  IDs in log4 but ABSENT in log2:")
    for i in sorted(s4 - s2) or ["(none)"]:
        print("     %s" % (fmt_id(i) if not isinstance(i, str) else i))
    print()
    print("  log3 vs log4 -- identical ID sets? %s" % (s3 == s4))
    if s3 != s4:
        print("     only in log3: %s" % [fmt_id(i) for i in sorted(s3 - s4)])
        print("     only in log4: %s" % [fmt_id(i) for i in sorted(s4 - s3)])
    print()

if PHASE2:
    print("=" * 78)
    print("PHASE 2 -- BUS IDENTITY CHECK")
    print("=" * 78)
    ANCHORS = {
        "Powertrain": [0x051, 0x592, 0x594, 0x639, 0x644, 0x64B, 0x5A2],
        "Vehicle": [0x1E5, 0x500, 0x514, 0x52A, 0x778, 0x780, 0x785, 0x788],
        "OBD (TRAC MCU)": [0x040, 0x041, 0x042, 0x043, 0x044],
        "GMLAN (either GM bus)": [0x0C9, 0x1C3, 0x17D, 0x1E1, 0x4C9, 0x1CF, 0x3E9],
    }
    for name in LOGS:
        stats = loaded[name][0]
        print("  %s:" % name)
        for bus, ids in ANCHORS.items():
            hits = [fmt_id(i) for i in ids if i in stats]
            print("     %-24s %d/%d  %s" % (bus, len(hits), len(ids), " ".join(hits)))
        print()

if PHASE3:
    print("=" * 78)
    print("PHASE 3 -- %s STATE TIMELINE" % FOCUS)
    print("=" * 78)
    t0 = None
    samples = defaultdict(list)
    for f in parse_file(LOGS[FOCUS]):
        if t0 is None:
            t0 = f.timestamp
        t = f.timestamp - t0
        d = f.data
        i = f.arbitration_id
        if i == 0x482 and len(d) >= 3:
            samples["hv_bus_0x482"].append((t, d[1] | (d[2] << 8)))
        elif i == 0x470 and len(d) >= 3:
            samples["hv_bus_0x470"].append((t, d[1] | (d[2] << 8)))
        elif i == 0x0870A047 and len(d) >= 3:
            samples["eac_hv_volts"].append((t, d[2] * 4))
        elif i == 0x054 and len(d) >= 2:
            samples["gene_rpm"].append((t, (d[0] | (d[1] << 8)) - 32767))

    for key in ["hv_bus_0x482", "hv_bus_0x470", "eac_hv_volts", "gene_rpm"]:
        v = [x[1] for x in samples[key]]
        if not v:
            print("  %-16s : no frames" % key)
        else:
            print("  %-16s : n=%-5d min=%-6d max=%-6d" % (key, len(v), min(v), max(v)))
    print()

    print("  --- ignition / VCM state transitions ---")
    t0 = None
    prev = {}
    events = []
    for f in parse_file(LOGS[FOCUS]):
        if t0 is None:
            t0 = f.timestamp
        t = f.timestamp - t0
        d = f.data
        i = f.arbitration_id
        if i == 0x592 and len(d) >= 1:
            cur = ("ignition", (d[0] >> 4) & 1, "evse", (d[0] >> 1) & 1, "export", (d[0] >> 2) & 1)
            if prev.get(0x592) != cur:
                events.append((t, "0x592 HCU_SENSOR", "ign=%d evse=%d export=%d  (B0=0x%02X)"
                               % (cur[1], cur[3], cur[5], d[0])))
                prev[0x592] = cur
        elif i == 0x600 and len(d) >= 1:
            if prev.get(0x600) != d[0]:
                events.append((t, "0x600 VCM", "B0=0x%02X" % d[0]))
                prev[0x600] = d[0]
        elif i == 0x644 and len(d) >= 1:
            if prev.get(0x644) != d[0]:
                events.append((t, "0x644 VCM", "B0=0x%02X" % d[0]))
                prev[0x644] = d[0]
    for t, src, msg in events:
        print("      t=%7.3fs  %-18s %s" % (t, src, msg))
    print()

if PHASE4:
    print("=" * 78)
    print("PHASE 4 -- BMS POWERED? (section boards vs master)")
    print("=" * 78)
    for label in ["log2_2026-07-02", "log3_2026-07-24", FOCUS]:
        print("-" * 78)
        print("  %s" % label)
        print("-" * 78)
        t0 = None
        recs = defaultdict(list)
        for f in parse_file(LOGS[label]):
            if t0 is None:
                t0 = f.timestamp
            if f.arbitration_id in BMS_DIRECT or f.arbitration_id in BMS_MASTER:
                recs[f.arbitration_id].append((f.timestamp - t0, bytes(f.data)))
        print("    BMS-DIRECT (pack section/monitor boards):")
        for i in BMS_DIRECT:
            r = recs.get(i)
            if not r:
                print("      %s  ABSENT" % fmt_id(i))
                continue
            print("      %s  n=%-5d first=%6.2fs last=%6.2fs  uniq=%-4d last_payload=%s"
                  % (fmt_id(i), len(r), r[0][0], r[-1][0],
                     len(set(x[1] for x in r)), r[-1][1].hex(" ")))
        print("    BMS MASTER block:")
        for i in BMS_MASTER:
            r = recs.get(i)
            if not r:
                print("      %s  ABSENT" % fmt_id(i))
            else:
                print("      %s  n=%-5d first=%6.2fs last=%6.2fs" % (fmt_id(i), len(r), r[0][0], r[-1][0]))
        print()

if PHASE5:
    print("=" * 78)
    print("PHASE 5 -- 0x596 SoC/permission + BMS-correlated VCM messages")
    print("=" * 78)
    WATCH = [0x596, 0x63D, 0x639, 0x63A, 0x640]
    for name in LOGS:
        print("  %s" % name)
        c = {i: Counter() for i in WATCH}
        for f in parse_file(LOGS[name]):
            if f.arbitration_id in c:
                c[f.arbitration_id][bytes(f.data)] += 1
        for i in WATCH:
            if not c[i]:
                print("     %s  ABSENT" % fmt_id(i))
                continue
            top = c[i].most_common(2)
            extra = ""
            if i == 0x596:
                b6 = sorted(set(p[6] for p in c[i] if len(p) > 6))
                b0 = sorted(set(p[0] for p in c[i]))
                extra = "   B0(permissions)=%s  B6(SoC%%)=%s" % ([hex(v) for v in b0], b6)
            print("     %s n=%-5d distinct=%-3d top=%s%s"
                  % (fmt_id(i), sum(c[i].values()), len(c[i]),
                     " | ".join("%s x%d" % (p.hex(" "), n) for p, n in top), extra))
        print()
