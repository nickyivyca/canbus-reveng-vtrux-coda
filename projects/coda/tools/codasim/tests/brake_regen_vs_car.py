"""Brake-on regen at speed: the model against the car, frame by frame, where the regen limit decides.

    python3.13 projects/coda/tools/codasim/tests/brake_regen_vs_car.py <capture.log> <cal> [<cand_cal>]

Why (user 2026-10-14, on the brake-map target above 31 mph: "lets make it so the sim could handle a test of A against
reality").  Option A keeps the brake map's existing target (-156.2 Nm at 12.4 mph and up, as C4c); the live regen limit
(0x312 M_MIN = -BoundSrcAB4, computed by dlcm/boundsrc.py from the BMS limits and the 0x1C0 substitute for 0x20B)
then decides what is requested.  So the test is whether the model reproduces the car's request and limit while the
brake is pressed in D, by speed band, and in particular whether it classifies "limit binding" the same way.

`cal` is the calibration the car RAN for this capture (the model is scored against it).  `cand_cal`, if given, is run
on the same recorded inputs, open loop: its request is shown beside the car's, which on a C4c capture is the direct
reality for a candidate that keeps C4c's brake target.

Rows are the recorded 0x212 frames (each paired with the latest model tick at or before it, the replay_vs_car rule);
0x312 and 0x1C0 are taken from their latest frame at or before the same instant, and the model's M_MIN from the tick
that sent that 0x312 frame (fixed 2026-10-14: it was taken at the 0x212 frame's tick, a one-tick mismatch that inflated
the M_MIN error; see notes/dlcm/artifacts/regen_limit_scatter.py).  Excluded: 1 s after a 0x212 gap
> 100 ms (recovery is not modelled) and everything after a predicted ECM2 reset.

Per row (Nm unless noted): car / model 0x212 request, car / model M_MIN, car delivered 0x1C0 Torque, BrakeAnalog (raw
0x208 count), BrakeAnalogValid, gear code, speed (mph from MotorSpeedSignedX2), the demand map output TrqRawDemand,
the demand clamp ClampLo, and the coast value: the D pedal map at the same pedal and speed index, i.e. what the map
would give with no pressure.  "Binding" = the request is within 1 Nm of M_MIN.  "Extra over coast" = request minus
max(coast, M_MIN): what the brake added beyond what the limit lets coast deliver.
"""
import bisect
import sys
sys.path.insert(0, "."); sys.path.insert(0, "projects/coda/tools")
import numpy as np
import cantools
from codasim.io import logreplay as L, inputs
from codasim.dlcm.controller import DlcmController
from codasim.fixedpoint import ld_h, ld_hu
from codasim.lut import lut2d

MPH_PER_MOTOR_RPM = 2 * np.pi * 0.3008 * 60 / 1609.344 / 6.576    # 0.010715; rear wheels / odometer chain
BANDS = (("12.4-31 mph", 12.4, 31.0), ("31-50 mph", 31.0, 50.0), ("50+ mph", 50.0, 999.0))
TRACE = ("Pub212Raw", "Pub312MinRaw", "TrqRawDemand", "ClampLo", "DemandSpeedIndex", "PedalInternal",
         "BrakeAnalog", "BrakeAnalogValid", "GearCode", "MotorSpeedSignedX2")
RAW_NM = 0.25           # 0x212 / 0x312 raw count; zero at 2000
DLCM_NM = 0.1           # internal torque words


def _model(cap, cal, t0, t1, extra=None, rx_timing="poll"):
    ctl = DlcmController(cal, bounds="computed")
    rp = inputs.replay(cap, ctl, t0, t1, trace=list(TRACE), extra=extra, rx_timing=rx_timing)
    a = np.array(rp.trace, np.int64)
    img, sym = ctl.ctx.img, ctl.ctx.sym
    pm = img.table2d(sym.addr("DescDemandPedalD"))
    gd = img.read(*sym.var("ProgGearCodeD"))
    coast = np.array([lut2d(*pm, ld_hu(int(p)), ld_h(int(s))) for p, s in zip(a[:, 6], a[:, 5])], np.int64)
    halt = ctl.resets[0][0] + inputs.ALIGN_US if ctl.resets else None
    return dict(t=a[:, 0], v={n: a[:, i + 1] for i, n in enumerate(TRACE)}, coast=coast, gear_d=gd,
                resets=list(ctl.resets), halt=halt, bounds=ctl._bounds_prov)


def _latest(ts, vs, t):
    j = bisect.bisect_right(ts, t) - 1
    return vs[j] if j >= 0 else np.nan


def rows(path, cal, cand=None, a=None, b=None, extra=None, rx_timing="poll"):
    """Per recorded 0x212 frame, the dict of arrays described in the module docstring (+ cand_* if cand).
    extra: io.inputs extra feeds (default: inputs' own default for computed bounds)."""
    cap = L.load(path)
    db = cantools.database.load_file("projects/coda/CODA-D-CAN.dbc", strict=False)
    t0, t1 = cap.span_us()
    t0 = int(a * 1e6) if a is not None else t0 + 2_000_000
    t1 = int(b * 1e6) if b is not None else t1 - 1_000_000
    runs = {"m": _model(cap, cal, t0, t1, extra, rx_timing)}
    if cand is not None:
        runs["c"] = _model(cap, cand, t0, t1, extra, rx_timing)

    def dec(fid, sig, scaling):
        out = []
        for t, d in cap.frames("D", fid):
            try:
                out.append((t, db.decode_message(fid, d, scaling=scaling)[sig]))
            except Exception:
                pass
        return np.array([x[0] for x in out], np.int64), np.array([x[1] for x in out], float)
    f212 = dec(0x212, "TorqueRequest", False)
    f312 = dec(0x312, "M_MIN", False)
    f1c0 = dec(0x1C0, "Torque", True)
    ts = f212[0]
    gaps = [(ts[i], ts[i + 1]) for i in range(len(ts) - 1) if ts[i + 1] - ts[i] > 100_000]
    halts = [r["halt"] for r in runs.values() if r["halt"] is not None]
    halt = min(halts) if halts else None
    m = runs["m"]
    keep, idx = [], []
    for k, t in enumerate(ts):
        j = bisect.bisect_right(m["t"], t) - 1
        if j < 0 or not (m["t"][0] < t < m["t"][-1]) or (halt is not None and t >= halt):
            continue
        if any(g1 <= t < g1 + 1_000_000 for g0, g1 in gaps):
            continue
        keep.append(k); idx.append(j)
    keep, idx = np.array(keep, int), np.array(idx, int)
    tt = ts[keep]
    out = dict(t=tt,
               car_req=(f212[1][keep] - 2000) * RAW_NM,
               car_mmin=np.array([_latest(f312[0], f312[1], t) for t in tt]) * RAW_NM - 500.0,
               car_tq=np.array([_latest(f1c0[0], f1c0[1], t) for t in tt]))
    # M_MIN is its own 10 ms frame: the model's value is taken at the tick that sent the car's latest 0x312 frame (the
    # model tick at or before that frame), not at the 0x212 frame's tick -- 0x312 can trail 0x212 in the TX burst.
    t312 = np.array([f312[0][max(bisect.bisect_right(f312[0], t) - 1, 0)] for t in tt])
    idx312 = np.array([max(bisect.bisect_right(m["t"], t) - 1, 0) for t in t312], int)
    for key, r in runs.items():
        v = {n: x[idx] for n, x in r["v"].items()}
        out[key + "_req"] = (v["Pub212Raw"] - 2000) * RAW_NM
        out[key + "_mmin"] = (r["v"]["Pub312MinRaw"][idx312] - 2000) * RAW_NM
        out[key + "_dem"] = v["TrqRawDemand"] * DLCM_NM
        out[key + "_clamplo"] = v["ClampLo"] * DLCM_NM
        out[key + "_coast"] = r["coast"][idx] * DLCM_NM
        if key == "m":
            out["brake"], out["bvalid"] = v["BrakeAnalog"], v["BrakeAnalogValid"]
            out["in_d"] = v["GearCode"] == r["gear_d"]
            out["mph"] = v["MotorSpeedSignedX2"] / 2.0 * MPH_PER_MOTOR_RPM
    meta = dict(describe=cap.describe(), bounds=m["bounds"], gaps=len(gaps),
                resets={k: r["resets"] for k, r in runs.items()})
    return out, meta


def masks(r):
    """{(family, band): row mask}.  Selected on inputs and the car's own limit, never on the model's output:
    "brake on"   BrakeAnalog > 0 and valid, D;
    "map > limit" D, and the demand map's target for the recorded inputs (TrqRawDemand: brake map if pressed, else
                 the pedal map) is more than 1 Nm deeper than the car's recorded M_MIN -- the regime where the limit,
                 not the map, sets the request, whichever map asked."""
    d = r["in_d"]
    fam = {"brake on": (r["brake"] > 0) & (r["bvalid"] != 0) & d,
           "map > limit": d & (r["m_dem"] < r["car_mmin"] - 1.0)}
    return {(f, lab): fm & (r["mph"] >= lo) & (r["mph"] < hi) for f, fm in fam.items() for lab, lo, hi in BANDS}


def band_stats(r, m, key="m"):
    """Scores for one mask.  key "m": the model on the car's own CAL; "c": the candidate (no car truth for it)."""
    if not m.any():
        return None
    req, mmin = r[key + "_req"][m], r[key + "_mmin"][m]
    s = dict(n=int(m.sum()))
    bind = req <= mmin + 1.0
    s["bind"] = float(bind.mean())
    s["extra"] = r[key + "_req"][m] - np.maximum(r[key + "_coast"][m], mmin)
    if key == "m":
        car_bind = r["car_req"][m] <= r["car_mmin"][m] + 1.0
        s["car_bind"] = float(car_bind.mean())
        s["bind_agree"] = float((bind == car_bind).mean())
        s["err_req"] = np.abs(req - r["car_req"][m])
        s["err_mmin"] = np.abs(mmin - r["car_mmin"][m])
        s["deliv"] = r["car_tq"][m] - r["car_req"][m]
        s["car_extra"] = r["car_req"][m] - np.maximum(r["m_coast"][m], r["car_mmin"][m])
    else:
        s["vs_car"] = req - r["car_req"][m]
    return s


def report(r, meta, out=print):
    """0x212 is a 20 ms frame, so n rows = n x 20 ms."""
    out(meta["describe"])
    out("bounds: %s; 0x212 gaps > 100 ms: %s; predicted resets %s" % (meta["bounds"], meta["gaps"], meta["resets"]))
    for (fam, lab), m in masks(r).items():
        s = band_stats(r, m)
        if s is None:
            out("%-11s %-12s no rows" % (fam, lab))
            continue
        out("%-11s %-12s n %6d (%5.0f s)  req |err| mean %.2f p99 %.2f max %.1f | M_MIN |err| mean %.2f p99 %.2f max %.1f"
            " | binding car %3.0f%% model %3.0f%% agree %3.0f%% | delivered-request p50 %.1f"
            % (fam, lab, s["n"], s["n"] * .02, s["err_req"].mean(), np.percentile(s["err_req"], 99), s["err_req"].max(),
               s["err_mmin"].mean(), np.percentile(s["err_mmin"], 99), s["err_mmin"].max(), 100 * s["car_bind"],
               100 * s["bind"], 100 * s["bind_agree"], np.median(s["deliv"])))
        if "c_req" in r:
            c = band_stats(r, m, "c")
            out("%-24s cand: req - car req p01 %.1f p50 %.1f p99 %.1f | binding %3.0f%%"
                % ("", np.percentile(c["vs_car"], 1), np.median(c["vs_car"]), np.percentile(c["vs_car"], 99), 100 * c["bind"]))


if __name__ == "__main__":
    r, meta = rows(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    report(r, meta)
