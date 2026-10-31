r"""The closed-loop parts of the candidate scorecards: S1 (shift clunk, brake held) and S2 (response at an equal
unfiltered request, plus the zero crossing), each as one call taking (cal, ref).
`Coda drivetrain lash model` session, 2026-10-17 (user: "agree with both" -- expose S1 / S2 for the scorecard script, and
move the measures here before next_flash_score.py / next_flash_response.py are deprecated).  The cards themselves, the
static goals (G2-G4, S3-S5) and the card script are the codasim / DLCM session's (`notes/dlcm/candidate-criteria.md`).
Simulation only; a card authorises nothing.

The measures are MOVED here unchanged from the scripts that declared them; regen13_screens phases 4c / 4e / 4a are the
reference runs, and s1 / s2 reproduce them (regen13-model-screens.md section 4):
  shift_ring     A7 ring (from next_flash_score._ring): scoring.sim_impact_time on the 50 Hz body acceleration (the
                 largest step within 2.5 s of the shift), then scoring.ring over impact +0.1 .. +2.0 s on the episode grid.
  a4_event       A4 (from next_flash_response.a4_event): onset at the first tick at or after the shift with
                 PedalInternal >= 5 %; window 1 s or until the foot backs off 5 points; d_lo = demand the tick before,
                 d_hi = the window's max; cmd / whl / dem 50 and 90 = time from onset to that level of the step.
  rec_view       (from regen13_screens._rec_view) PedalInternal replaced by the RECORDED pedal, so a4_event's onset and
                 back-off are the same instants for every CAL under the adapted driver.
  shift_only     (from regen13_screens._shift_only) pedal 0 from the shift on; hold=True also holds 0x200 BrakeSW and
                 0x208 BrakePressure / _Valid at their value at the shift.
  synthetic, zero_crossing   (from next_flash_response.synthetic / _p2_one) open-loop DlcmController, slow inputs held at a
                 C4c_post_revert quiet point; D, brake off, pedal 0 -> 60 % at 3 s; zero crossing = s from 0x212 >= 0 to
                 >= +160 raw (+40 Nm), at 500 / 1000 / 2000 rpm.

THE CARD CALLS (user 2026-10-17 grading; candidate-criteria.md section 3):
  s1_shift_clunk(cal, ref)   S1: every runnable headline reversal (f7_clunk out), closed loop, pedal 0 and the brake held,
                 cal and ref on the same episodes; paired log ring ratio -> median % change [p10, p90], share lower; all,
                 R->D, D->R.  Reported, not gated.
  s2_response(cal, ref)      S2: drive-off after each reversal and every standing launch, closed loop with the ADAPTED
                 DRIVER (cosim pedal_remap=ref: each CAL is driven to the request ref's pedal map gives for the recorded
                 foot); A4 on rec_view; paired cal - ref per level, PASS if median <= +0.020 s and p90 <= +0.050 s on
                 every level of both sets; and the zero crossing, PASS if cal <= ref + 0.010 s at every rpm.  With
                 ref = the CAL on the car the request is THAT CAL's: "equal request" means the reference's.
  Both return predicted resets and ECM2 reason-10 / 12 debounce maxima per CAL (G1 counts every closed-loop run) and the
  per-episode values.  Model-validity lines the card prints: s2's filter lag (A4 from each CAL's own demand reaching the
  level), the arrival offset (run again with arrival_us 650 / 2500), and body_hold_z (run again with body_hold_z=None).
"""
import multiprocessing as mp
import os

import numpy as np

from . import cosim as CS
from . import episodes as E
from . import scoring as SC
from .clock import ORDER_TX, Clock
from .dlcm.controller import DlcmController
from .interfaces import Provenance
from .io import inputs as INP

_ART = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "notes", "dlcm", "artifacts"))
REV_STORE = os.path.join(_ART, "codasim_episodes.npz")
LAUNCH_STORE = os.path.join(_ART, "codasim_launch_episodes.npz")
WORKERS = 8
EXCLUDE_COHORTS = ("f7_clunk",)     # out of every headline statistic (resets are still counted)

ONSET, BACKOFF, MIN_STEP, WIN_TICKS = 500, 500, 100, 100      # A4, PedalInternal / demand counts and 10 ms ticks
LEVELS = (0.5, 0.9)
A4_KEYS = ("cmd50", "cmd90", "whl50", "whl90")
A4_MED, A4_P90 = 0.020, 0.050       # S2 limits, s (user 2026-10-10 "Tight", worklog 3BH.4)
ZX_TOL = 0.010                      # S2 zero crossing: no more than one tick slower
ZX_RPM = (500, 1000, 2000)
TEMPLATE = "C4c_post_revert"
BRAKE_RAW = 102
TRACE_S1 = ("Ecm2Reason10Cnt", "Ecm2Reason12Cnt", "TrqRawDemand")
TRACE_S2 = ("TrqRawDemand", "PedalInternal", "CreepOut", "Ecm2Reason10Cnt", "GearCode", "Ecm2Reason12Cnt")
MPH_PER_RPM = 86.8 / 8134
_G = {}


# ------------------------------------------------------------------ measures
def shift_ring(e, r):
    """A7 ring of one cosim result; NaN if no impact was found."""
    g = E.grid(e)
    i_s = E.PRE_US // E.TICK_US
    acc = np.interp(g["t_us"], r["t50"], r["acc50"])
    ts = SC.sim_impact_time(r["t50"], r["acc50"], e["t_us"])
    return float(SC.ring(acc, np.ones(len(acc), bool), ts, i_s)) if np.isfinite(ts) else float("nan")


def a4_event(e, r, cap=None):
    """A4 for one cosim result (trace_extra must include TrqRawDemand and PedalInternal); None if the episode has no
    event, dict(halted=True) if a reset falls inside the window, dict(small=True, ...) if the step is under 10 Nm.
    cap: clip d_hi at this many counts."""
    x = r["extra"]
    tt, ped, dem, cmd = r["t_tick"], x["PedalInternal"], x["TrqRawDemand"], r["mcm"]
    on = np.flatnonzero((tt >= e["t_us"]) & (ped >= ONSET))
    if not len(on) or on[0] == 0:
        return None
    k0 = int(on[0])
    ke = min(k0 + WIN_TICKS, len(tt))
    runmax = np.maximum.accumulate(ped[k0:ke])
    back = np.flatnonzero(ped[k0:ke] < runmax - BACKOFF)
    if len(back):
        ke = k0 + int(back[0])
    if r["resets"] and r["resets"][0][0] <= tt[ke - 1]:
        return dict(halted=True)
    d_lo, d_hi = int(dem[k0 - 1]), int(dem[k0:ke].max())
    if cap is not None:
        d_hi = min(d_hi, cap)
    if d_hi - d_lo < MIN_STEP:
        return dict(small=True, d_lo=d_lo, d_hi=d_hi)
    sg = -1.0 if e["to"] == "R" else 1.0
    t_on = int(tt[k0])
    out = dict(stem=e["stem"], t_us=int(e["t_us"]), to=e["to"], cohort=e["cohort"], d_lo=d_lo, d_hi=d_hi,
               mph_on=float(r["speed_raw"][k0] / 2.0 * MPH_PER_RPM), t_on_from_shift=(t_on - int(e["t_us"])) / 1e6)

    def first(t, ok, start):
        k = np.flatnonzero(ok & (t >= start))
        return float((t[k[0]] - start) / 1e6) if len(k) else float("nan")

    t_end = int(tt[ke - 1])
    for f in LEVELS:
        L = d_lo + f * (d_hi - d_lo)
        w = tt <= t_end
        out[f"dem{int(f * 100)}"] = first(tt[w], dem[w] >= L, t_on)
        out[f"cmd{int(f * 100)}"] = first(tt[w], cmd[w] >= L, t_on)
        if "shaft_Nm" in r:
            wm = r["t_ms"] <= t_end
            out[f"whl{int(f * 100)}"] = first(r["t_ms"][wm], sg * r["shaft_Nm"][wm] >= L / 10.0, t_on)
    pub = r["pub212"]                                        # 0x212 is a magnitude in the gear's direction (R too)
    out["t400"] = first(tt[tt <= t_end], pub[tt <= t_end] >= 400, t_on) if d_hi >= 1000 else float("nan")
    return out


def rec_view(r):
    """r with PedalInternal replaced by the recorded pedal at each tick (cosim's pedal_rec)."""
    pr, tt = r["pedal_rec"], r["t_tick"]
    k = np.searchsorted(pr[:, 0], tt, "right") - 1
    r2 = dict(r)
    r2["extra"] = dict(r["extra"])
    r2["extra"]["PedalInternal"] = np.where(k >= 0, pr[np.clip(k, 0, None), 1], 0)
    return r2


def shift_only(e, hold):
    """The episode with the pedal at 0 from the shift on; hold: brake switch and pressure held at their shift value."""
    S, t0 = dict(e["series"]), int(e["t_us"])
    t, v = S["0x210.ThottlePedalPos"]
    v = np.array(v, float)
    v[t >= t0] = 0.0
    S["0x210.ThottlePedalPos"] = (t, v)
    if hold:
        for sig in ("0x200.BrakeSW", "0x208.BrakePressure", "0x208.BrakePressure_Valid"):
            t, v = S[sig]
            v = np.array(v, float)
            k = int(np.searchsorted(t, t0, "right")) - 1
            v[t > t0] = v[max(k, 0)]
            S[sig] = (t, v)
    e2 = dict(e)
    e2["series"] = S
    return e2


def template(store=REV_STORE):
    """The synthetic runs' held slow inputs: the first TEMPLATE-cohort reversal with a quiet point."""
    eps, _ = E.load(store)
    e = next(e for e in eps if e["cohort"] == TEMPLATE and e.get("quiet_us") is not None)
    S, t0 = e["series"], int(e["quiet_us"])
    held = {}
    feeds = [f + ("D",) for f in INP.FEEDS] + list(INP.COMPUTED_BOUND_FEEDS)
    for sig, fid, dbcsig, prov, shift, filt, dbc in feeds:
        if sig in ("0x210.ThottlePedalPos", "0x418.GearStatus", "0x212.BrakeSW", "0x308.InputShaftSpeed",
                   "0x208.BrakePressure"):
            continue
        t, v = S[sig]
        k = int(np.searchsorted(t + shift, t0, "right"))
        held[sig] = (prov, v[k - 1])
    return e["stem"], t0, held


def synthetic(cal, rpm, pedal_steps, brake_until_us=None, t_end_us=5000000, tmpl=None):
    """Open-loop controller run, speed held.  pedal_steps: [(t_us, pct)]; brake on until brake_until_us (None: off)."""
    stem, _, held = tmpl or _G.get("tmpl") or template()
    ctl = DlcmController(cal, bounds="computed")
    clk = Clock(0)
    ctl.install(clk, phase_us=0)
    for sig, (prov, v) in held.items():
        ctl.sink(sig, Provenance.SUBSTITUTE)(0, v)
    ctl.sink("0x418.GearStatus", Provenance.REVERSED)(0, 0x11)
    ctl.sink("0x1C0.Motor_Speed", Provenance.SUBSTITUTE)(0, float(rpm))
    bsw = ctl.sink("0x212.BrakeSW", Provenance.REVERSED)
    bsw(0, 1 if brake_until_us else 0)
    bp = ctl.sink("0x208.BrakePressure", Provenance.RECEIVED)        # SYNTHETIC: held 102 raw while braking
    bp(0, BRAKE_RAW if brake_until_us else 0)
    ped = ctl.sink("0x210.ThottlePedalPos", Provenance.REVERSED)
    ped(0, 0.0)
    if brake_until_us:
        clk.feed([(brake_until_us, 0)], bsw)
        clk.feed([(brake_until_us, 0)], bp)
    clk.feed([(t, p) for t, p in pedal_steps], ped)
    tr = []
    vs = [ctl.ram.var(n) for n in ("Pub212Raw", "McmCommand", "TrqRawDemand")]
    clk.every(10000, lambda t: tr.append((t,) + tuple(v.get() for v in vs)), phase_us=0, order=ORDER_TX, name="trace")
    clk.run_until(t_end_us)
    a = np.array(tr, np.int64)
    return dict(t=a[:, 0], pub=a[:, 1] - 2000, cmd=a[:, 2], dem=a[:, 3], resets=list(ctl.resets))


def zero_crossing(cal, tmpl=None):
    """{rpm: dict(zx=s or NaN, resets=[...])}: 0x212 from >= 0 to >= +40 Nm after a 0 -> 60 % pedal step."""
    out = {}
    for rpm in ZX_RPM:
        s = synthetic(cal, rpm, [(3000000, 60.0)], tmpl=tmpl)
        t, p = s["t"], s["pub"]
        k0 = np.flatnonzero((t >= 3000000) & (p >= 0))
        res = dict(resets=s["resets"], zx=float("nan"))
        if len(k0):
            k1 = np.flatnonzero((t >= t[k0[0]]) & (p >= 160))
            res["zx"] = float((t[k1[0]] - t[k0[0]]) / 1e6) if len(k1) else float("nan")
        out[rpm] = res
    return out


# ------------------------------------------------------------------ runs
def _headline(e):
    return e["cohort"] not in EXCLUDE_COHORTS


def _runnable(eps):
    return [i for i, e in enumerate(eps) if e.get("quiet_us") is not None]


def _pool(fn, jobs, workers):
    with mp.get_context("fork").Pool(workers) as pool:
        return list(pool.imap_unordered(fn, jobs, chunksize=4))


def _base(r, e):
    x = r["extra"]
    return dict(resets=[((t - e["t_us"]) / 1e6, c) for t, c in r["resets"]], r10=int(x["Ecm2Reason10Cnt"].max()),
                r12=int(x["Ecm2Reason12Cnt"].max()))


def _s1_one(arg):
    i, cal, kw = arg
    e = shift_only(_G["rev"][i], True)
    try:
        r, _ = CS.run(e, cal=cal, bounds="computed", preset="current", grade_fallback=True, trace_extra=TRACE_S1, **kw)
    except CS.NotRunnable as x:
        return i, cal, dict(skip=str(x).split(":")[0][:60])
    out = _base(r, e)
    if not r["resets"]:
        out["ring"] = shift_ring(e, r)
        out["t_imp"] = SC.sim_impact_time(r["t50"], r["acc50"], e["t_us"])
    return i, cal, out


def _s2_one(arg):
    kind, i, cal, ref, kw = arg
    e = _G[kind][i]
    try:
        r, _ = CS.run(e, cal=cal, bounds="computed", preset="current", trace_extra=TRACE_S2, pedal_remap=ref, **kw)
    except CS.NotRunnable as x:
        return kind, i, cal, dict(skip=str(x).split(":")[0][:60])
    out = _base(r, e)
    out["remap"] = r["pedal_remap"]
    if not r["resets"]:
        out["ring"] = shift_ring(e, r)
    ev = a4_event(e, rec_view(r))
    out["a4"] = ev if isinstance(ev, dict) else None
    if kind == "launch":
        x, tt = r["extra"], r["t_tick"]
        k = np.clip(np.searchsorted(tt, r["t_ms"], "right") - 1, 0, len(tt) - 1)
        m = (x["GearCode"][k] == 40) & (r["t_ms"] >= e["t_us"])
        mph = r["rpm"] * MPH_PER_RPM
        out["max_back"] = float(max(0.0, -mph[m].min())) if m.any() else 0.0
    return kind, i, cal, out


def _ring_summary(pairs):
    """pairs: [(ring cal, ring ref)] -> median / p10 / p90 % change, share lower, n (paired log10 ratio)."""
    dl = np.array([np.log10(a / b) for a, b in pairs if a and b and a > 0 and b > 0 and np.isfinite(a) and np.isfinite(b)])
    if not len(dl):
        return dict(n=0)
    pc = lambda x: float((10 ** x - 1) * 100)
    return dict(median_pct=pc(np.median(dl)), p10_pct=pc(np.percentile(dl, 10)), p90_pct=pc(np.percentile(dl, 90)),
                share_lower=float(np.mean(dl < 0)), n=int(len(dl)))


def _guard(cal, ref):
    for p in (cal, ref):
        if not os.path.isfile(p):
            raise FileNotFoundError(p)


def _resets(run):
    o_ = list(run.values())
    return dict(runs=len(o_), predicted_resets=sum(1 for o in o_ if o["resets"]),
                r10_max=max((o["r10"] for o in o_), default=0), r12_max=max((o["r12"] for o in o_), default=0))


def s1_shift_clunk(cal, ref, rev_store=REV_STORE, workers=WORKERS, **cosim_kw):
    """S1: shift clunk with the pedal at 0 and the brake held, cal vs ref (paths to CAL images).  cosim_kw go to
    cosim.run (e.g. speed_arrival_us=650, body_hold_z=None for the model-validity lines)."""
    _guard(cal, ref)
    _G["rev"], _ = E.load(rev_store)
    eps = _G["rev"]
    idx = _runnable(eps)
    cals = list(dict.fromkeys((cal, ref)))
    res = _pool(_s1_one, [(i, c, cosim_kw) for c in cals for i in idx], workers)
    run = {c: {} for c in cals}
    skipped = {c: 0 for c in cals}
    for i, c, o in res:
        if "skip" in o:
            skipped[c] += 1
        else:
            run[c][i] = o
    out = dict(cal=cal, ref=ref, cosim_kw=dict(cosim_kw), skipped={_side(c, cal): skipped[c] for c in cals},
               g1={_side(c, cal): _resets(run[c]) for c in cals}, rings={})
    both = [i for i in idx if i in run[cal] and i in run[ref] and _headline(eps[i])]
    for lab, sel in (("all", lambda e: True), ("R->D", lambda e: e["to"] == "D"), ("D->R", lambda e: e["to"] == "R")):
        out["rings"][lab] = _ring_summary([(run[cal][i].get("ring"), run[ref][i].get("ring")) for i in both if sel(eps[i])])
    out["episodes"] = [dict(stem=eps[i]["stem"], t_us=int(eps[i]["t_us"]), to=eps[i]["to"], cohort=eps[i]["cohort"],
                            ring_cal=run[cal][i].get("ring"), ring_ref=run[ref][i].get("ring")) for i in both]
    return out


def _a4_paired(run, cal, ref, keep, lag=False):
    """Per level: paired cal - ref median / p90 / n and pass; lag: from each CAL's own demand reaching the level."""
    out, ok = {}, True
    for k in A4_KEYS:
        dref = ("dem50" if k.endswith("50") else "dem90") if lag else None
        f = (lambda o: (o["a4"][k] - (o["a4"][dref] if dref else 0.0))
             if o.get("a4") and k in o["a4"] and (dref is None or dref in o["a4"]) else None)
        d = []
        for i in keep:
            x, y = f(run[cal][i]), f(run[ref][i])
            if x is not None and y is not None and np.isfinite(x) and np.isfinite(y):
                d.append(x - y)
        if not d:
            out[k] = dict(n=0)
            continue
        med, p90 = float(np.median(d)), float(np.percentile(d, 90))
        p = med <= A4_MED + 1e-9 and p90 <= A4_P90 + 1e-9
        ok &= p
        out[k] = dict(median=med, p90=p90, n=len(d), passed=p)
    out["passed"] = ok
    return out


def s2_response(cal, ref, rev_store=REV_STORE, launch_store=LAUNCH_STORE, workers=WORKERS, **cosim_kw):
    """S2: A4 at an equal unfiltered request (adapted driver, ref's pedal map) on drive-off after each reversal and on
    standing launches, plus the synthetic zero crossing; cal vs ref.  cosim_kw go to cosim.run."""
    _guard(cal, ref)
    _G["rev"], _ = E.load(rev_store)
    _G["launch"], _ = E.load(launch_store)
    _G["tmpl"] = template(rev_store)
    cals = list(dict.fromkeys((cal, ref)))
    jobs = [(kind, i, c, ref, cosim_kw) for kind in ("rev", "launch") for c in cals for i in _runnable(_G[kind])]
    res = _pool(_s2_one, jobs, workers)
    out = dict(cal=cal, ref=ref, cosim_kw=dict(cosim_kw), sets={}, g1={})
    passed = True
    for kind, lab in (("rev", "drive_off_after_shift"), ("launch", "standing_launch")):
        eps = _G[kind]
        run = {c: {} for c in cals}
        skipped = {c: 0 for c in cals}
        for k_, i, c, o in res:
            if k_ != kind:
                continue
            if "skip" in o:
                skipped[c] += 1
            elif _headline(eps[i]):
                run[c][i] = o
        keep = [i for i in run[cal] if i in run[ref]]
        a4 = _a4_paired(run, cal, ref, keep)
        passed &= a4["passed"]
        dd = [run[cal][i]["a4"]["d_hi"] / 10.0 - run[ref][i]["a4"]["d_hi"] / 10.0 for i in keep
              if (run[cal][i].get("a4") or {}).get("d_hi") is not None and (run[ref][i].get("a4") or {}).get("d_hi") is not None]
        s = dict(n=len(keep), skipped={_side(c, cal): skipped[c] for c in cals}, a4=a4, filter_lag=_a4_paired(run, cal, ref, keep, lag=True),
                 request_diff_nm=dict(p10=float(np.percentile(dd, 10)), p50=float(np.median(dd)),
                                      p90=float(np.percentile(dd, 90)), n=len(dd)) if dd else dict(n=0),
                 ring=_ring_summary([(run[cal][i].get("ring"), run[ref][i].get("ring")) for i in keep]),
                 remap={("cal" if c == cal else "ref"): _remap_stats(run[c]) for c in cals})
        if kind == "launch":
            for c in cals:
                mb = np.array([o["max_back"] for o in run[c].values()])
                s.setdefault("rollback", {})["cal" if c == cal else "ref"] = dict(
                    over_0p3_mph=int(np.sum(mb > 0.3)), over_1p1_mph=int(np.sum(mb > 1.1)), max_mph=float(mb.max()))
        out["sets"][lab] = s
        for c in cals:
            g = _resets({i: o for k_, i, c_, o in res if k_ == kind and c_ == c and "skip" not in o})
            out["g1"].setdefault("cal" if c == cal else "ref", {})[lab] = g
    zc, zr = zero_crossing(cal, _G["tmpl"]), zero_crossing(ref, _G["tmpl"])
    zx = {rpm: dict(cal=zc[rpm]["zx"], ref=zr[rpm]["zx"], resets=len(zc[rpm]["resets"]),
                    passed=bool(zc[rpm]["zx"] <= zr[rpm]["zx"] + ZX_TOL + 1e-9)) for rpm in ZX_RPM}
    zx["passed"] = all(zx[rpm]["passed"] for rpm in ZX_RPM)
    out["zero_crossing"] = zx
    out["passed"] = bool(passed and zx["passed"])
    return out


def _side(c, cal):
    return "cal" if c == cal else "ref"


def _remap_stats(run):
    st = {}
    for o in run.values():
        for k, v in o["remap"].items():
            st[k] = max(st.get(k, 0), v) if k == "over_max" else st.get(k, 0) + v
    return st
