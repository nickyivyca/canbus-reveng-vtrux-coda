"""hold_burst_check.py -- does the Bel charger duty-cycle (burst) during the
Low Power hold, and does it only transmit 0x18FFD7C0 while on? (2026-10-10)

If it did, the reported DC current would be an on-state value and would over-
read the average -- an alternative to a sensor error for the phase 8 finding
in hold_load_fit.py. vehicle-cost-per-mile.md 6.2 notes the charger message
rate falls to 55 % during the hold.

Input: hold_burst_80pct_filtered.log, the 80 % hold capture pre-filtered to
0x18FFD7C0 / 0x410 / 0x18EFC000 (all on one channel, which carries both the
Bel and the BMS ids, so it is the powertrain bus). Low Power entry at
2026-03-04 07:42:33 UTC (vcu_hold_character.txt); the capture starts
2026-03-03 21:38:46 PST = 05:38:46 UTC, so entry is t ~= 7427 s.

The filtered input was deleted after the run. Regenerate it with
  (head -15 projects/vtrux/logs/vtruxchargeafterexportchargetest-80pctcv.log;
   grep -aE " 0x18FFD7C0 | 0x410 | 0x18EFC000 " \
     projects/vtrux/logs/vtruxchargeafterexportchargetest-80pctcv.log) \
   > projects/vtrux/notes/artifacts/hold_burst_80pct_filtered.log
"""
import sys
sys.path.insert(0, ".")
import statistics as st
import cantools
from canre.parsers import parse_file

LOG = "projects/vtrux/notes/artifacts/hold_burst_80pct_filtered.log"
bel = cantools.database.load_file("projects/vtrux/BelInverter-v2.dbc")
pt = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
T_ENTRY = 7427

chg, bms = [], []
for f in parse_file(LOG):
    if f.arbitration_id == 0x18FFD7C0:
        d = bel.decode_message(f.arbitration_id, f.data)
        chg.append((f.timestamp, d["BELINV_hvBatteryCurrent"],
                    d["BELINV_chargerInputCurrent"]))
    elif f.arbitration_id == 0x410:
        d = pt.decode_message(f.arbitration_id, f.data)
        bms.append((f.timestamp, d["bcm_ibat"]))
chg.sort()
bms.sort()
print("frames: charger %d, bms %d, span %.0f..%.0f s"
      % (len(chg), len(bms), chg[0][0], chg[-1][0]))


def describe(label, a, b):
    c = [x for x in chg if a <= x[0] < b]
    m = [x for x in bms if a <= x[0] < b]
    if len(c) < 3:
        print("%s: no charger frames" % label)
        return
    gc = [y[0] - x[0] for x, y in zip(c, c[1:])]
    gm = [y[0] - x[0] for x, y in zip(m, m[1:])]
    idc = [-x[1] for x in c if abs(x[1]) < 100]
    iac = [x[2] for x in c if x[2] < 60]
    ib = [x[1] for x in m if abs(x[1]) < 600]
    print("\n%s  (%d..%d s)" % (label, a, b))
    print("  charger: %d frames = %.2f /s; gap med %.3f s, p99 %.3f, max %.2f; "
          "gaps > 0.5 s: %d (%.0f s total)"
          % (len(c), len(c) / (b - a), st.median(gc), sorted(gc)[int(.99 * len(gc))],
             max(gc), sum(1 for g in gc if g > .5), sum(g for g in gc if g > .5)))
    print("  Idc (reported, sign flipped): min %.2f q1 %.2f med %.2f q3 %.2f max %.2f;"
          " frames with |Idc| < 0.5 A: %d"
          % (min(idc), sorted(idc)[len(idc) // 4], st.median(idc),
             sorted(idc)[3 * len(idc) // 4], max(idc), sum(1 for x in idc if x < .5)))
    print("  Iac: min %.2f med %.2f max %.2f" % (min(iac), st.median(iac), max(iac)))
    if gm:
        print("  bms: %d frames = %.2f /s; gap med %.3f s, max %.2f; ibat min %.2f med %.2f "
              "max %.2f; sd %.3f"
              % (len(m), len(m) / (b - a), st.median(gm), max(gm), min(ib),
                 st.median(ib), max(ib), st.pstdev(ib)))
    secs = {}
    for t, i, _ in c:
        secs.setdefault(int(t), []).append(-i)
    s0 = int(a)
    trace = " ".join("%.1f" % st.mean(secs[s]) if s in secs else "  - "
                     for s in range(s0 + 60, s0 + 100))
    print("  1 s mean Idc, 40 s sample: %s" % trace)


describe("bulk, before entry", T_ENTRY - 600, T_ENTRY - 60)
describe("hold, settled", T_ENTRY + 300, T_ENTRY + 1800)
