"""End-to-end: a raw capture played through io.inputs into DlcmController; the model's
published 0x212 against every recorded 0x212 frame (paired with the latest model tick
at or before the frame).

    python3.13 projects/coda/tools/codasim/tests/replay_vs_car.py <capture.log> <cal> [t0_s t1_s] [--replay-bounds]

Default: the bound chain COMPUTED (the DlcmController default) with the unlogged M-CAN 0x20B words
taken from 0x1C0 HV_Voltage / HV_Current (io.inputs.SUBSTITUTE_20B_FEEDS, declared SUBSTITUTE).
--replay-bounds: AB4/ACA replayed from the recorded 0x312 instead (bounds="replay").

Reports overall and, if the capture has gaps in 0x212 longer than 5 periods (a DLCM
reset goes dark), excluding 1 s after each gap: recovery is not modelled (user, 2026-10-09),
so post-reset ticks are not a test of the controller. A PREDICTED ECM2 reset halts the
controller (plan step 5); frames after it are not scored and the reset is reported.
"""
import bisect
import sys
sys.path.insert(0, "."); sys.path.insert(0, "projects/coda/tools")
import numpy as np
import cantools
from codasim.io import logreplay as L, inputs
from codasim.dlcm.controller import DlcmController


def run(path, cal, a=None, b=None, bounds="computed"):
    cap = L.load(path)
    db = cantools.database.load_file("projects/coda/CODA-D-CAN.dbc", strict=False)
    t0, t1 = cap.span_us()
    t0 = int(a * 1e6) if a is not None else t0 + 2_000_000
    t1 = int(b * 1e6) if b is not None else t1 - 1_000_000
    ctl = DlcmController(cal, bounds=bounds)
    rp = inputs.replay(cap, ctl, t0, t1, trace=["Pub212Raw"])
    tt = np.array([x[0] for x in rp.trace]); pv = np.array([x[1] for x in rp.trace])
    fr = cap.frames("D", 0x212)
    ts = np.array([t for t, d in fr])
    gaps = [(ts[i], ts[i + 1]) for i in range(len(ts) - 1) if ts[i + 1] - ts[i] > 100_000]
    halt = ctl.resets[0][0] + inputs.ALIGN_US if ctl.resets else None
    out = []
    for t, d in fr:
        j = bisect.bisect_right(tt, t) - 1
        if j < 0 or not (tt[0] < t < tt[-1]) or (halt is not None and t >= halt):
            continue
        raw = db.decode_message(0x212, d, scaling=False)["TorqueRequest"]
        post = any(g1 <= t < g1 + 1_000_000 for g0, g1 in gaps)
        out.append((pv[j] - raw, post))
    e = np.array([abs(x) for x, _ in out]); post = np.array([p for _, p in out])
    print(cap.describe())
    print("bounds: %s" % ctl._bounds_prov)
    print("cal %s; 0x212 gaps > 100 ms: %d %s" % (cal, len(gaps), [round((g1 - g0) / 1e3) for g0, g1 in gaps][:10]))
    print("predicted ECM2 resets: %s%s" % ([(round(t / 1e6, 4), c) for t, c in ctl.resets],
                                          " -- scoring stops there" if ctl.resets else ""))
    for lab, m in (("all frames", np.ones(len(e), bool)), ("excluding 1 s after each gap", ~post)):
        x = e[m]
        print("%-30s n %6d  mean |err| %.3f Nm  exact %.1f%%  <=1cnt %.1f%%  p99 %.2f Nm  max %.2f Nm"
              % (lab, len(x), x.mean() * .25, 100 * (x == 0).mean(), 100 * (x <= 1).mean(),
                 np.percentile(x, 99) * .25, x.max() * .25))
    return ctl, rp


if __name__ == "__main__":
    mode = "replay" if "--replay-bounds" in sys.argv else "computed"
    args = [x for x in sys.argv[1:] if x != "--replay-bounds"]
    run(args[0], args[1], *(float(x) for x in args[2:4]), bounds=mode)
