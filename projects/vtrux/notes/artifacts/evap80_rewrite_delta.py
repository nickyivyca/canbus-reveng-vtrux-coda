"""Why evap_80pct's modified-frame count fell from 18,753 to 18,735.

The spec 6 plug-out rule (2026-10-03) ends the override at the charger's
`vehicleConnected` 1 -> 0 report instead of at the VCU's flow drop ~1.1 s
later. Everything the core would have rewritten in that gap is no longer
rewritten, so the question is simply: how many frames did the VCU send to
the charger in it?

Counted here rather than taken on trust -- the figure is going into a
README as a cause, and the review session's count and mine are independent
only if I do not read theirs into the code.
"""
import sys
from collections import Counter

sys.path.insert(0, ".")
sys.path.insert(0, "projects/vtrux/tools/interposer")

from replay import iter_pt, detect_pt_bus          # noqa: E402
import machine as M                                 # noqa: E402

PATH = "projects/vtrux/notes/artifacts/filt_evap_80pct.log"

# The two ends of the gap, from the core's own event log for this capture:
#   9298.0    TERMINATED  charger reports the plug out
#   9299.0955             the VCU's flow drop (page 00 with the flow bit 0)
PLUG_OUT_S = 9298.0


def main():
    bus = detect_pt_bus(PATH)
    known = M.VEHICLE_IDS | M.CHARGER_IDS if hasattr(M, "VEHICLE_IDS") else None
    from replay import VEHICLE_IDS, CHARGER_IDS
    known = VEHICLE_IDS | CHARGER_IDS

    pages = Counter()
    flow_drop_s = None
    n = 0
    for t, arb, ext, data in iter_pt(PATH, bus, known):
        if t < PLUG_OUT_S:
            continue
        if arb != M.CMD_ID:
            continue
        page = data[0]
        # page 00 carries the flow bit in d[1]; its clearing ends the window
        if page == 0x00 and len(data) >= 2 and (data[1] & 0x01) == 0:
            flow_drop_s = t
            break
        if page == 0x03 and len(data) >= 2:
            pages["03.%02d" % data[1]] += 1
        else:
            pages["%02d" % page] += 1
        n += 1

    print("plug-out report      t = %.4f s" % PLUG_OUT_S)
    print("VCU flow drop        t = %s" % ("%.4f s" % flow_drop_s
                                           if flow_drop_s else "NOT FOUND"))
    if flow_drop_s:
        print("gap                  = %.4f s" % (flow_drop_s - PLUG_OUT_S))
    print()
    print("VCU -> charger frames in the gap, by page:")
    for k in sorted(pages):
        print("   page %-6s %3d" % (k, pages[k]))
    print("   %-11s %3d  TOTAL" % ("", n))
    print()
    print("observed drop in modified count: 18753 - 18735 = 18")


if __name__ == "__main__" and not set(sys.argv) & {"--phase2", "--phase3", "--phase4"}:
    main()


def phase2():
    """The decisive measurement: replay the capture twice, once with the
    plug-out rule live and once with it disabled, and diff the counts.

    Counting frames in the gap (phase 1) is not the same quantity -- only
    the pages the core actually REWRITES contribute to `modified`, and 21
    frames arrive in the gap. `chg_vehicle_connected` has exactly one call
    site, the rule itself, so forcing it to 1 disables that rule and
    nothing else.
    """
    import replay
    import machine as Mm

    def run(label):
        core = Mm.InterposerCore(Mm.Config(), now_ms=0)
        res = replay.replay_offline(PATH, core)
        print("   %-22s modified=%d" % (label, res["modified"]))
        return res["modified"]

    print("replaying twice (about 90 s each) ...")
    with_rule = run("plug-out rule ON")
    orig = Mm.chg_vehicle_connected
    Mm.chg_vehicle_connected = lambda d: 1
    try:
        without = run("plug-out rule OFF")
    finally:
        Mm.chg_vehicle_connected = orig
    print()
    print("   delta attributable to the rule = %d" % (without - with_rule))
    print("   README records 18753 -> 18735  = 18")


if __name__ == "__main__" and "--phase2" in sys.argv:
    phase2()


def phase3():
    """Which 18 frames, exactly.

    Phase 2 established the count by controlled replay. The review session
    then tallied the rewritten pages in the gap and got 17, and guessed the
    missing one was a frame at the boundary. A guess is cheap to replace
    here: replay with the rule disabled and record every frame the core
    actually rewrites in the window, with its timestamp and page.
    """
    import replay
    from replay import iter_pt, detect_pt_bus, VEHICLE_IDS, CHARGER_IDS
    import machine as Mm
    import regress

    case = [c for c in regress.CASES if c.name == "evap_80pct"][0]
    path, err = regress.prepare(case, keep=True, verbose=True)
    if err:
        raise SystemExit(err)

    orig = Mm.chg_vehicle_connected
    Mm.chg_vehicle_connected = lambda d: 1      # the rule off, nothing else
    try:
        core = Mm.InterposerCore(Mm.Config(), now_ms=0)
        bus = detect_pt_bus(str(path))
        known = VEHICLE_IDS | CHARGER_IDS
        rows = []
        for t, arb, ext, data in iter_pt(str(path), bus, known):
            t_ms = int(t * 1000)
            if arb in CHARGER_IDS:
                out = core.on_charger_frame(arb, ext, data, t_ms)
            else:
                out = core.on_vehicle_frame(arb, ext, data, t_ms)
            for side, oid, oext, odata in out:
                if oid == arb and odata != data and t >= PLUG_OUT_S - 0.5:
                    page = ("03.%02d" % data[1] if data[0] == 0x03
                            else "%02d" % data[0])
                    rows.append((t, page, data.hex(), odata.hex()))
            if t > 9299.5:
                break
    finally:
        Mm.chg_vehicle_connected = orig

    print("frames the core REWRITES from %.1f s onward, rule disabled:"
          % (PLUG_OUT_S - 0.5))
    for t, page, a, b in rows:
        mark = "   " if t >= PLUG_OUT_S else ">> "
        print("  %s%.4f s  page %-6s %s -> %s" % (mark, t, page, a, b))
    inside = [r for r in rows if r[0] >= PLUG_OUT_S]
    print()
    print("  rewrites at or after the plug-out instant: %d" % len(inside))
    print("  ('>>' rows are BEFORE it and are not part of the delta)")


if __name__ == "__main__" and "--phase3" in sys.argv:
    phase3()


def phase4():
    """17 or 18, settled: find the plug-out instant to full precision.

    Phase 3 counted 17 rewrites at or after t = 9298.0 s, which is what the
    review session's tally also gave -- while phase 2's controlled replay
    measured 18. The gap is my window boundary, not a missing frame:
    `9298.0s` is the core event log's ONE-DECIMAL rendering of the plug-out,
    and there is a rewrite at 9297.9931 s sitting just the wrong side of
    the rounded value. So read the real instant off the frame itself.
    """
    from replay import iter_pt, detect_pt_bus, VEHICLE_IDS, CHARGER_IDS
    import machine as Mm
    import regress

    case = [c for c in regress.CASES if c.name == "evap_80pct"][0]
    path, err = regress.prepare(case, keep=True, verbose=False)
    if err:
        raise SystemExit(err)

    bus = detect_pt_bus(str(path))
    known = VEHICLE_IDS | CHARGER_IDS
    prev = None
    edge = None
    for t, arb, ext, data in iter_pt(str(path), bus, known):
        if t < 9290.0:
            continue
        if t > 9300.0:
            break
        if arb != Mm.CHG_STATUS or len(data) < 8 or Mm.chg_mux(data) != 0:
            continue
        vc = Mm.chg_vehicle_connected(data)
        if prev == 1 and vc == 0:
            edge = t
            print("vehicleConnected 1 -> 0 at t = %.4f s  (%s)"
                  % (t, data.hex()))
            break
        prev = vc

    if edge is None:
        print("edge NOT FOUND in 9290-9300 s")
        return
    print("the core event log renders this as %.1f s" % edge)
    print()
    print("rewrites in phase 3's listing at or after %.4f s: the 03.02 at"
          % edge)
    print("9297.9931 s is INSIDE the gap, giving 18 -- which is the number")
    print("the controlled replay measured. 17 came from rounding 9298.0.")


if __name__ == "__main__" and "--phase4" in sys.argv:
    phase4()
