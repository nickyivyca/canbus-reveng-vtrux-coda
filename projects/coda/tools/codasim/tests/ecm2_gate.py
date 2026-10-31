"""Plan step 5 gate: ECM2 resets predicted from the model alone.

User's rule (2026-10-09): a reset on a candidate profile rejects it, so recovery is not modelled.
A predicted reset HALTS the controller. To score the f7 drive's later resets, each segment after a
RECORDED reset starts a fresh controller at the first QUIET point after the return: >= 1 s after the
module's first frame back, with the recorded 0x212 at exactly zero (raw 2000) for the preceding
QUIET_US (0.5 s). Only there is a cold start faithful: creep's latch and PI state are not published,
so a controller started mid-manoeuvre winds creep up from zero and trips where the car did not.
Measured: restart at the first 0x212 off zero gave false trips at 27.93 / 36.71 s, restart 2 s after
return at 29.36 / 37.86 s, each ~0.5 s in, each with the car rolling back under creep. A recorded
reset with no quiet point before it is reported NOT SCORABLE without recovery modelling.

A recorded reset is dated by its first MISSING 0x212 frame (last frame + 10 ms); a predicted one by
the TX burst its trip tick would have sent (tick + io.inputs.ALIGN_US). Delta is in ticks.

    python3.13 projects/coda/tools/codasim/tests/ecm2_gate.py
"""
import sys
sys.path.insert(0, "."); sys.path.insert(0, "projects/coda/tools")
import cantools
from codasim.io import logreplay as L, inputs
from codasim.dlcm.controller import DlcmController

F7 = "projects/coda/notes/dlcm/dcan_drive_capture_20261004_f7/coda_20261004_161521_T0.log"
C4C = "../../CANLogs/CodaLogs/coda_20261004_165539_T0.log"
DBC = cantools.database.load_file("projects/coda/CODA-D-CAN.dbc", strict=False)


SETTLE_US = 1_000_000
QUIET_US = 500_000


def recorded(cap):
    """[(first missing 0x212 burst, quiet restart time or None)] for each 0x212 gap > 100 ms."""
    fr = cap.frames("D", 0x212)
    raw = [(t, DBC.decode_message(0x212, d, scaling=False)["TorqueRequest"]) for t, d in fr]
    gaps = [i for i in range(len(fr) - 1) if fr[i + 1][0] - fr[i][0] > 100_000]
    out = []
    for k, i in enumerate(gaps):
        nxt = fr[gaps[k + 1]][0] if k + 1 < len(gaps) else fr[-1][0]
        quiet, since = None, None
        for t, v in raw[i + 1:]:
            if t >= nxt:
                break
            since = (since or t) if v == 2000 else None
            if since is not None and t >= fr[i + 1][0] + SETTLE_US and t - since >= QUIET_US:
                quiet = t
                break
        out.append((fr[i][0] + 10_000, quiet))
    return out


def segment(cap, cal, t0, t1):
    ctl = DlcmController(cal)
    inputs.replay(cap, ctl, t0, t1)
    return [(t + inputs.ALIGN_US, code) for t, code in ctl.resets]


def run(path, cal, restart="recorded"):
    cap = L.load(path)
    a, b = cap.span_us()
    rec = recorded(cap)
    t, end, pred = a + 2_000_000, b - 1_000_000, []
    starts = [t] + [back for _, back in rec]
    for i, s in enumerate(starts):
        stop = rec[i][0] + 30_000 if (restart == "recorded" and i < len(rec)) else end
        if s is None:
            continue
        while s < stop:
            r = segment(cap, cal, s, stop)
            if not r:
                break
            pred += r
            if restart == "recorded":
                break
            s = r[0][0] + 1_000_000                 # counterfactual: count the next independent trip
        if restart != "recorded":
            break
    print("\n%s under %s CAL: recorded resets %d, predicted %d" % (cap.stem, cal, len(rec), len(pred)))
    for tp, code in pred:
        near = min(rec, key=lambda r: abs(r[0] - tp)) if rec else None
        dt = (tp - near[0]) / 10_000 if near else float("nan")
        print("   predicted %9.4f s  reason %2d   nearest recorded %s  (%+.1f ticks)"
              % (tp / 1e6, code, ("%9.4f s" % (near[0] / 1e6)) if near else "-", dt))
    hit = [r for r in rec if any(abs(tp - r[0]) <= 20_000 for tp, _ in pred)]
    if rec and restart == "recorded":
        scorable = [rec[0]] + [rec[k] for k in range(1, len(rec)) if rec[k - 1][1] is not None]
        for k, r in enumerate(rec):
            ok = k == 0 or rec[k - 1][1] is not None
            print("   recorded %9.4f s  %s%s" % (r[0] / 1e6, "segment from %9.4f s" % (([t] + [b for _, b in rec])[k] / 1e6) if ok
                                                 else "NOT SCORABLE (no quiet point after the previous return)",
                                                 "  MATCHED" if r in hit else ""))
        print("   recorded resets matched within 2 ticks: %d / %d scorable (%d recorded)" % (len(hit), len(scorable), len(rec)))
    return pred, rec


if __name__ == "__main__":
    run(F7, "f7")                                   # gate: 7 at the recorded times
    run(C4C, "c4c", restart="counterfactual")       # gate: 0
    run(F7, "c4c")                                  # same inputs, filter off: segments between recorded resets
    run(C4C, "f7", restart="counterfactual")        # f7 on the C4c drive (peer predicted trips from 53.2 s)
