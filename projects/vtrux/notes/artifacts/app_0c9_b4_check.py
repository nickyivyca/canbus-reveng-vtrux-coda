"""Check whether 0x0C9 B4 (the ECM accelerator-position readback)
carries a real APP magnitude on the Vtrux, or is pinned/static.

RESULT (2026-08-14): it is REAL. On a normal main-truck drive log
(vtruxanotherevaplogpart2.log) B4 takes 230 distinct values spanning 0-254
(0-99.6%). The prior notes claim of "no APP magnitude on GMLAN" was an
artifact of the deprecated DBC, which omitted SG_ Accelerator_Actual_Position
entirely. Notes corrected; see projects/vtrux/README.md and engine-stall-analysis.md.

WATCH OUT when picking logs for this check -- two logs give a false negative
because APP is genuinely 0 in them, for physical reasons:
  - vtrux_app_disconnect_test.log  : APP GEN MOD was unplugged for that test
  - vtrux_partstruck_*             : parts truck has no APP GEN MOD at all
Both read B4 == 0 in every frame with the engine running. Use a main-truck
drive log.

Phase 1: distribution of 0x0C9 B4 vs Engine_Speed (0x0C9 B1-B2 BE * 0.25)
Phase 2: per-byte stats for 0x0C9, to rule out a wrong bit position
"""
import sys
sys.path.insert(0, ".")

from collections import Counter, defaultdict
from canre.parsers import parse_file

LOGS = sys.argv[1:] or ["projects/vtrux/logs/vtrux_partstruck_testdrive_part3_engine.log"]


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / (sxx * syy) ** 0.5


for path in LOGS:
    print("=" * 78)
    print(path)
    frames = parse_file(path)

    # per-(bus,id) collection
    c9 = defaultdict(list)   # bus -> [(t, b4, rpm, validity_bit)]
    d1 = defaultdict(list)   # bus -> [(t, tps)]
    p592 = defaultdict(list)  # bus -> [(t, pedal_raw)]

    total = 0
    for f in frames:
        total += 1
        d = f.data
        if f.arbitration_id == 0x0C9 and len(d) >= 8:
            rpm = ((d[1] << 8) | d[2]) * 0.25
            valid = (d[3] >> 7) & 1   # bit 31 = byte 3 MSB
            c9[f.bus].append((f.timestamp, d[4], rpm, valid))
        elif f.arbitration_id == 0x3D1 and len(d) >= 2:
            d1[f.bus].append((f.timestamp, d[1] * 0.392157))
        elif f.arbitration_id == 0x592 and len(d) >= 4:
            p592[f.bus].append((f.timestamp, (d[2] << 8) | d[3]))

    print("  total frames: %d" % total)

    for bus, rows in sorted(c9.items()):
        b4 = [r[1] for r in rows]
        rpm = [r[2] for r in rows]
        val = Counter(r[3] for r in rows)
        cnt = Counter(b4)
        print("  0x0C9 bus %s: %d frames" % (bus, len(rows)))
        print("    B4 unique=%d  min=%d max=%d  top: %s"
              % (len(cnt), min(b4), max(b4), cnt.most_common(6)))
        print("    B4 as %%: min=%.1f max=%.1f" % (min(b4) * 0.392157, max(b4) * 0.392157))
        print("    Validity bit counts: %s  (0=Valid)" % dict(val))
        print("    RPM min=%.0f max=%.0f" % (min(rpm), max(rpm)))
        print("    r(B4, RPM) = %.4f" % pearson(b4, rpm))

    for bus, rows in sorted(d1.items()):
        tps = [r[1] for r in rows]
        print("  0x3D1 bus %s: %d frames  TPS min=%.1f max=%.1f unique=%d"
              % (bus, len(rows), min(tps), max(tps), len(set(tps))))

    for bus, rows in sorted(p592.items()):
        pv = [r[1] for r in rows]
        print("  0x592 bus %s: %d frames  B2-B3 min=%d max=%d unique=%d"
              % (bus, len(rows), min(pv), max(pv), len(set(pv))))

    # cross-signal resample: nearest-previous alignment onto 0x0C9 timebase
    if c9 and d1:
        cb = max(c9, key=lambda b: len(c9[b]))
        db = max(d1, key=lambda b: len(d1[b]))
        drows = sorted(d1[db])
        crows = sorted(c9[cb])
        j = 0
        xs, ys = [], []
        for t, b4, _rpm, _v in crows:
            while j + 1 < len(drows) and drows[j + 1][0] <= t:
                j += 1
            if drows[j][0] <= t:
                xs.append(b4 * 0.392157)
                ys.append(drows[j][1])
        print("  aligned samples 0x0C9B4 vs 0x3D1 TPS: %d  r=%.4f"
              % (len(xs), pearson(xs, ys)))

# ---- Phase 2: per-byte variability of 0x0C9, to rule out a wrong bit position
print()
print("#" * 78)
print("PHASE 2: per-byte stats for 0x0C9")
for path in LOGS:
    print("=" * 78)
    print(path)
    per = defaultdict(lambda: defaultdict(Counter))
    for f in parse_file(path):
        if f.arbitration_id == 0x0C9 and len(f.data) >= 8:
            for i, b in enumerate(f.data):
                per[f.bus][i][b] += 1
    for bus in sorted(per):
        n = sum(per[bus][0].values())
        print("  bus %s (%d frames)" % (bus, n))
        for i in range(8):
            c = per[bus][i]
            print("    B%d unique=%-4d min=%-3d max=%-3d top=%s"
                  % (i, len(c), min(c), max(c), c.most_common(4)))
