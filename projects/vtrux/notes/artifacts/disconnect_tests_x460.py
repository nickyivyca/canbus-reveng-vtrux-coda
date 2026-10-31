"""What did the 0x460 fault list and the BMS do in the physical disconnect tests?

Asked 2026-09-06 while writing up the AC 10 xx parameter hypothesis (00 = EPO bit on
0x400, 01 = 0x400 heartbeat timeout): did the HV-battery LV-connector pull [T2] or the
VCM B-connector pull [T3] produce an AC 10 01, or other codes?

For each log: PT bus by content, 0x400 gaps > 0.3 s, bcm_epo 0->1 events with the
last-0x400 gap and hsc_bcm_epo, distinct 0x460 records (first/last seen), 0x410 presence
gaps (BMS off the bus).

Run from project root:
  python3.13 projects/vtrux/notes/artifacts/disconnect_tests_x460.py > projects/vtrux/notes/artifacts/disconnect_tests_x460.txt
"""
import sys
sys.path.insert(0, ".")

from collections import Counter

from canre.parsers import parse_file

LOGS = [
    ("T1/T2 pump then HV-battery LV connector", "projects/vtrux/logs/vtruxunplugpumpthenhvbatterylvconnector.log"),
    ("T3 VCM B-connector", "projects/vtrux/logs/unidentified-bus/vtruxwoodwardbconnectordisconnected.log"),
    ("T4 gene inverter fuse", "projects/vtrux/logs/vtrux_no_gene_inv_fuse.log"),
]


def gaps(ts, thr=0.3):
    return [(a, b - a) for a, b in zip(ts, ts[1:]) if b - a > thr]


for name, path in LOGS:
    print("=" * 90)
    print(name, path)
    try:
        fr = list(parse_file(path))
    except Exception as e:
        print("  LOAD FAILED", e)
        continue
    t0 = fr[0].timestamp
    fr = [(f.timestamp - t0, f.bus, f.arbitration_id, f.data) for f in fr]
    c = Counter(b for _, b, a, d in fr if a == 0x410 and len(d) == 8)
    if not c:
        print("  no 0x410")
        continue
    pt = c.most_common(1)[0][0]
    print("  %d frames, %.0f s, PT bus %d" % (len(fr), fr[-1][0], pt))
    t410 = [t for t, b, a, d in fr if b == pt and a == 0x410 and len(d) == 8]
    t400 = [t for t, b, a, d in fr if b == pt and a == 0x400]
    print("  0x410 span %.1f..%.1f  gaps>0.3s: %s" % (t410[0], t410[-1], ["%.1f+%.1f" % g for g in gaps(t410)]))
    print("  0x400 span %.1f..%.1f  gaps>0.3s: %s" % ((t400[0], t400[-1], ["%.1f+%.1f" % g for g in gaps(t400)]) if t400 else (0, 0, "none")))
    prev = None
    for t, b, a, d in fr:
        if b == pt and a == 0x410 and len(d) == 8:
            e = (d[0] >> 1) & 1
            if prev == 0 and e == 1:
                before = [tt for tt in t400 if tt <= t]
                f400 = [(tt, dd) for tt, bb, aa, dd in fr if bb == pt and aa == 0x400 and t - 1 <= tt <= t + 1]
                epo1 = [tt for tt, dd in f400 if (dd[0] >> 1) & 1]
                print("  bcm_epo 0->1 at %.3f: last 0x400 %.3f s before; hsc_bcm_epo=1 first at %s"
                      % (t, (t - before[-1]) if before else float("nan"), ("%+.3f" % (epo1[0] - t)) if epo1 else "never in +/-1 s"))
            prev = e
    recs = {}
    for t, b, a, d in fr:
        if b == pt and a == 0x460 and len(d) == 8 and d[0] in (1, 2):
            for k in (2, 5):
                r = d[k:k + 3].hex(" ")
                if r != "00 00 00":
                    recs.setdefault(r, [t, t])[1] = t
    print("  0x460 records: " + (", ".join("%s [%.1f..%.1f]" % (r, v[0], v[1]) for r, v in sorted(recs.items(), key=lambda x: x[1][0])) or "(none)"))
