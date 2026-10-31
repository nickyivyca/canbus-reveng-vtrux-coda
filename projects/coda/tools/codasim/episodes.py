r"""Shift episodes from raw captures: the R<->D reversal store the plant side, cosim and scoring read.
Written 2026-10-09 by `Coda drivetrain lash model`, plan codasim_full_model.md step 3.  Replaces the
extraction in notes/dlcm/artifacts/rd_shift_episodes.py phase 1 / 22 + gear_change_clunk's event list
(user 2026-10-09: "we should re-baseline from the raw logs" -- distilled stores are allowed only when a
re-runnable script generates them from the logs).

WHAT AN EPISODE IS.  One rolling reversal on one capture:
  event     a 0x418 PRND frame entering the opposite driving direction from the last COMMITTED one (D/R;
            the lever passes through N, so N/P frames are skipped, as gear_change_clunk.find_reversals)
  rolling   max |0x1C0 Motor_Speed| over frames in [t - ROLL_WIN, t] >= ROLL_RPM
  quiet     quiet_us = the latest quiet_points() instant at or before t - PRE (the cosim handover), the start of its
            open-loop lead-in (plan step 4, user 2026-10-10); None, with the reason in no_quiet, when there is none or
            the module went dark (0x212 gap) between it and t - PRE.  Such episodes stay in the store for the
            recorded-side measures; cosim refuses them.
  span      every SIGNALS series over [min(quiet, t - PRE - HIST), t + POST + TAIL] plus MARGIN_US and one frame before and one frame after, at LOG
            TIME (integer us from the parser's t = 0), sorted per series, decoded with cantools against the D-CAN DBC
            (B-CAN DBC for 0x275 / 0x276).  Values are exactly what io.inputs delivers for its FEEDS and
            COMPUTED_BOUND_FEEDS (same DBC, same raw/scaled rule), so cosim feeds them through clock.feed with the
            io.inputs shifts; nothing here is resampled.  The capture-edge rule still judges [t - PRE - HIST, t + POST].
  bus       D CAN, by content (io.logreplay: >= 2 audited anchors, zero of any other bus; raises otherwise).
            Every signal is read from that one bus.

The 10 ms grid views the old consumers expect (DlcmLoop, plant.road, the step-3 gate) are DERIVED by grid();
they are not stored.  Grid k is at t_shift_us - PRE_US + k * TICK_US.

DROPS (counted by the build script, never silent): D bus unresolved; no 0x418 / 0x1C0 / 0x330 on D; span past
the capture edge (judged on 0x1C0 and 0x330); any REQUIRED series empty in the span.
"""
import json

import cantools
import numpy as np

from .interfaces import GEAR418_D, GEAR418_R
from .io import inputs as INP

TICK_US = 10000
PRE_US, POST_US, HIST_US, TAIL_US = 2000000, 4000000, 5000000, 0          # TAIL: extra stored after POST (none needed: scoring reads the episode grid)
ROLL_WIN_US, ROLL_RPM = 600000, 100.0
ACC_INVALID = 200                 # 0x330 Long_Accel raw >= 200 is the invalid sentinel (DBC CM_)
ACC_GUARD = (2, 8)                # samples masked before / after an invalid run (gear_change_clunk.acc_steps)
ACC_GAP_US = 65000                # a grid point between samples further apart than this is not valid
QUIET_US, SETTLE_US, GAP_US = 500000, 1000000, 100000     # quiet_points(): tests/ecm2_gate.py's cold-start rule
MARGIN_US = 100000                # stored before the span start, so cosim's delayed speed path has a warm-start value

# (name, frame id, DBC signal, raw?, dbc "D" | "B")  The io.inputs FEEDS first, with io.inputs' raw/scaled rule; then
# its COMPUTED_BOUND_FEEDS (BOUND_FEEDS + the 0x1C0 SUBSTITUTE for 0x20B), always raw, each decoded against its own DBC
# (0x275 / 0x276 are B-CAN messages taken from the D-CAN channel, as io.inputs does).
_FEEDS = [(sig, fid, dbcsig, dbcsig in INP.RAW_SIGNALS, "D") for sig, fid, dbcsig, _p, _s, _f in INP.FEEDS]
_BOUND = [(sig, fid, dbcsig, True, dbc) for sig, fid, dbcsig, _p, _s, _f, dbc in INP.COMPUTED_BOUND_FEEDS]
SIGNALS = _FEEDS + _BOUND + [
    ("0x418.PRND", 0x418, "PRND", True, "D"),
    ("0x1C0.Motor_Speed", 0x1C0, "Motor_Speed", False, "D"),
    ("0x1C0.Torque", 0x1C0, "Torque", False, "D"),
    ("0x212.TorqueRequest", 0x212, "TorqueRequest", False, "D"),
    ("0x330.Long_Accel_raw", 0x330, "Long_Accel", True, "D"),
    ("0x200.BrakeSW", 0x200, "BrakeSW", True, "D"),     # SubFrameID 0 only (SUBFRAME0); the old controller feed
    ("0x08C.Flag_B0bit2", 0x08C, "Flag_B0bit2", True, "D"),   # its FRAME TIMES anchor the divider-20 COM RX poll
                                                              # (io/comsched.py: 0x275 / 0x276), plan
                                                              # regen13_model_screens.md step 2b
]
SUBFRAME0 = {"0x200.BrakeSW"}     # 0x200 signals read from SubFrameID 0 frames only; every other 0x200 signal (SubFrameID
                                  # itself, a BOUND_FEED) is read from every frame, as io.inputs feeds it
if len({s[0] for s in SIGNALS}) != len(SIGNALS):
    raise RuntimeError("duplicate signal name in episodes.SIGNALS")
REQUIRED = ("0x418.PRND", "0x1C0.Motor_Speed", "0x1C0.Torque", "0x330.Long_Accel_raw", "0x212.TorqueRequest",
            "0x210.ThottlePedalPos", "0x208.BrakePressure", "0x208.BrakePressure_Valid", "0x308.InputShaftSpeed")
NAMES = [s[0] for s in SIGNALS]
_DIR = {GEAR418_D: "D", GEAR418_R: "R"}

# Cohort -> the CAL image that cohort ran (ported from rd_shift_episodes.CAL, which retires at step 7).
# Paths relative to the project root.
_A = "projects/coda/notes/dlcm/artifacts/"
COHORT_CAL = {
    "pre-campaign": "projects/coda/notes/dlcm/coda_dlcm_cal.bin",
    "stock+FLOOR5": _A + "cal_as_flashed_20260721_floor5.bin",
    "FLOOR20": _A + "cal_as_flashed_20260920_floor20.bin",
    "F40+limb40": _A + "cal_as_flashed_20260923_floor40_speedlimb40.bin",
    "negtrq_x3": _A + "cal_as_flashed_20260923_negtrq_scale3.bin",
    "C1_creep50": _A + "cal_as_flashed_20260923_c1_creep50.bin",
    "C1+launchrate": _A + "cal_as_flashed_20260924_launchrate.bin",
    "C2_onepedal": _A + "cal_as_flashed_20260924_onepedal1562.bin",
    "C4c_envelope": _A + "cal_as_flashed_20260925_envelope_c4c.bin",
    "C4c_post_revert": _A + "cal_as_flashed_20260925_envelope_c4c.bin",
    "f7_clunk": _A + "cal_as_flashed_20261004_f7_clunk.bin",
}


def _dbs():
    return {"D": cantools.database.load_file(INP.DBC, strict=False),
            "B": cantools.database.load_file(INP.B_DBC, strict=False)}


def decode_series(cap, dbs=None, bus="D"):
    """{name: (t_us int64[], value float64[])} for every SIGNALS entry, from the frames on `bus`, sorted by time.
    Frames that fail to decode are skipped (counted in the returned `bad` dict)."""
    dbs = dbs or _dbs()
    out, bad = {}, {}
    by_key = {}
    for name, fid, sig, raw, dbc in SIGNALS:
        by_key.setdefault((fid, dbc), []).append((name, sig, raw))
    for (fid, dbc), sigs in by_key.items():
        db = dbs[dbc]
        rows = cap.frames(bus, fid)
        acc = {n: ([], []) for n, _, _ in sigs}
        for t, data in rows:
            for scaled in (False, True):
                want = [(n, s) for n, s, r in sigs if r != scaled]
                if not want:
                    continue
                try:
                    d = db.decode_message(fid, data, scaling=scaled, decode_choices=False)
                except Exception:
                    for n, _ in want:
                        bad[n] = bad.get(n, 0) + 1
                    continue
                for n, s in want:
                    if n in SUBFRAME0 and int(d.get("SubFrameID", -1)) != 0:
                        continue
                    if s in d:
                        acc[n][0].append(t)
                        acc[n][1].append(float(d[s]))
        for n, (ts, vs) in acc.items():
            t = np.asarray(ts, np.int64)
            v = np.asarray(vs, np.float64)
            o = np.argsort(t, kind="stable")
            out[n] = (t[o], v[o])
    return out, bad


def quiet_points(series):
    """Sorted instants Q (us) at which the recorded 0x212 TorqueRequest has been exactly 0 (raw 2000) for the preceding
    QUIET_US, >= SETTLE_US after the module's first frame and after its return from every 0x212 gap > GAP_US.  The cold-start
    rule of tests/ecm2_gate.py (creep's latch and PI state are not published, so only there is a fresh controller
    faithful); the same rule as ecm2_population_check._quiet_starts, on the decoded series."""
    t, v = series["0x212.TorqueRequest"]
    out, since, back = [], None, int(t[0]) if len(t) else 0
    for k in range(len(t)):
        tk = int(t[k])
        if k and tk - int(t[k - 1]) > GAP_US:
            back, since = tk, None
        since = (since if since is not None else tk) if v[k] == 0.0 else None
        if since is not None and tk - since >= QUIET_US and tk >= back + SETTLE_US:
            out.append(tk)
    return np.asarray(out, np.int64)


def find_reversals(prnd_t, prnd_v):
    """[(t_us, frm, to)] on entry to the opposite driving direction (last committed D/R)."""
    out, last = [], None
    for t, c in zip(prnd_t, prnd_v):
        d = _DIR.get(int(c))
        if d is None:
            continue
        if last is not None and d != last:
            out.append((int(t), last, d))
        last = d
    return out


LAUNCH_STILL_US, LAUNCH_STILL_RPM, LAUNCH_PEDAL_US, LAUNCH_PEDAL_PCT = 1000000, 20.0, 2000000, 5.0


def find_launches(S):
    """[(t_us, "D", "D")] STANDING LAUNCHES (plan next_flash_from_c4c.md step 4, user 2026-10-12): t = a 0x212 BrakeSW
    1 -> 0 edge with |0x1C0 Motor_Speed| < LAUNCH_STILL_RPM over the preceding LAUNCH_STILL_US (stationary), 0x210
    ThottlePedalPos < LAUNCH_PEDAL_PCT at the release (not both pedals) and >= it within LAUNCH_PEDAL_US after, and
    0x418 PRND D on every frame in [t - PRE_US, t + POST_US] (no shift: reversals are the other extractor)."""
    bt, bv = S["0x212.BrakeSW"]
    rt, rv = S["0x1C0.Motor_Speed"]
    pt, pv = S["0x210.ThottlePedalPos"]
    gt, gv = S["0x418.PRND"]
    out = []
    for k in np.flatnonzero((bv[:-1] > 0) & (bv[1:] == 0)) + 1:
        t = int(bt[k])
        m = (rt >= t - LAUNCH_STILL_US) & (rt <= t)
        if not m.any() or np.max(np.abs(rv[m])) >= LAUNCH_STILL_RPM:
            continue
        j = np.searchsorted(pt, t, "right") - 1
        if j < 0 or pv[j] >= LAUNCH_PEDAL_PCT:
            continue
        mp_ = (pt > t) & (pt <= t + LAUNCH_PEDAL_US) & (pv >= LAUNCH_PEDAL_PCT)
        if not mp_.any():
            continue
        mg = (gt >= t - PRE_US) & (gt <= t + POST_US)
        if not mg.any() or np.any(gv[mg] != GEAR418_D):
            continue
        out.append((t, "D", "D"))
    return out


STOP_ANCHOR_RPM, STOP_FROM_RPM, STOP_FROM_US = 470.0, 940.0, 8000000     # ~5 mph, ~10 mph (86.8 mph = 8134 rpm)
STOP_STILL_RPM, STOP_STILL_US, STOP_PEDAL_PCT, STOP_LEAD_US = 20.0, 500000, 1.0, 500000
STOP_LOW_ANCHOR_RPM, STOP_LOW_FROM_RPM, STOP_LOW_FROM_US = 281.0, 470.0, 15000000   # kind "stop_low": ~3 mph after ~5 mph


def find_stops(S, anchor_rpm=STOP_ANCHOR_RPM, from_rpm=STOP_FROM_RPM, from_us=STOP_FROM_US):
    """[(t_us, "D", "D")] BRAKED STOPS (plan regen13_model_screens.md step 1, 2026-10-14): t = the first 0x1C0
    Motor_Speed sample with |rpm| < STOP_ANCHOR_RPM (~5 mph) after |rpm| > STOP_FROM_RPM (~10 mph) somewhere in
    [t - STOP_FROM_US, t]; then stationary (|rpm| < STOP_STILL_RPM on every frame for >= STOP_STILL_US) starting within
    (t, t + POST_US]; the brake on (0x212 BrakeSW 1 or a valid 0x208 pressure > 0) when it becomes stationary and on
    every frame from its last onset before then (the onset may be before or after t: on C4c the driver mostly brakes
    below 5 mph, after one-pedal regen); 0x210 ThottlePedalPos < STOP_PEDAL_PCT on every frame from t - STOP_LEAD_US
    to the stop; 0x418 PRND D on every frame in [t - PRE_US, t + POST_US].  One event per descent: after an event the
    next must first exceed STOP_FROM_RPM.  The thresholds are arguments: kind "stop_low" (low-speed stops, user
    2026-10-14) calls it with STOP_LOW_* (anchor ~3 mph after ~5 mph within 15 s), for the low-speed stops that
    "stop" misses; the two sets overlap."""
    rt, rv = S["0x1C0.Motor_Speed"]
    bt, bv = S["0x212.BrakeSW"]
    pt, pv = S["0x208.BrakePressure"]
    vt, vv = S["0x208.BrakePressure_Valid"]
    at, av = S["0x210.ThottlePedalPos"]
    gt, gv = S["0x418.PRND"]
    if min(len(rt), len(bt), len(pt), len(vt), len(at), len(gt)) == 0:
        return []
    hold = lambda ts, vs, t: vs[np.clip(np.searchsorted(ts, t, "right") - 1, 0, len(vs) - 1)]

    def brake_on(t):
        return (hold(bt, bv, t) > 0) | ((hold(vt, vv, t) > 0) & (hold(pt, pv, t) > 0))
    ar = np.abs(rv)
    out, armed, last_fast = [], False, None
    for k in range(len(rt)):
        if ar[k] > from_rpm:
            armed, last_fast = True, rt[k]
            continue
        if not armed or ar[k] >= anchor_rpm or rt[k] - last_fast > from_us:
            continue
        t = int(rt[k])
        armed = False
        j = k
        still_from = None
        while j < len(rt) and rt[j] <= t + POST_US:
            if ar[j] < STOP_STILL_RPM:
                still_from = rt[j] if still_from is None else still_from
                if rt[j] - still_from >= STOP_STILL_US:
                    break
            else:
                still_from = None
            j += 1
        if still_from is None or j >= len(rt) or rt[j] - still_from < STOP_STILL_US or still_from > t + POST_US:
            continue
        if not brake_on(still_from):
            continue
        ma = (at >= t - STOP_LEAD_US) & (at <= still_from)
        if np.any(av[ma] >= STOP_PEDAL_PCT) or hold(at, av, t - STOP_LEAD_US) >= STOP_PEDAL_PCT:
            continue
        mg = (gt >= t - PRE_US) & (gt <= t + POST_US)
        if not mg.any() or np.any(gv[mg] != GEAR418_D):
            continue
        out.append((t, "D", "D"))
    return out


def task_phase_us(series):
    """The DLCM torque-task phase on the 10 ms grid, as io.inputs aligns it (first 0x308 - ALIGN_US)."""
    t = series["0x308.InputShaftSpeed"][0]
    return int((t[0] - INP.ALIGN_US) % 10000) if len(t) else None


def extract(cap, cohort_of=None, dbs=None, kind="reversal"):
    """(episodes, drops) for one logreplay.Capture.  cohort_of(t_us) -> cohort name (the build script supplies it
    from the capture's wall clock); None leaves the cohort unset.  kind: "reversal" (rolling R<->D, the default and
    the store's), "launch" (find_launches; t_us is then the brake release, frm = to = "D", no rolling filter) or
    "stop" (find_stops; t_us is the ~5 mph braked anchor, frm = to = "D", no rolling filter) or "stop_low"
    (find_stops with STOP_LOW_*: the ~3 mph anchor)."""
    if kind not in ("reversal", "launch", "stop", "stop_low"):
        raise ValueError(kind)
    drops = {}
    try:
        cap.require("D")
    except LookupError as e:
        return [], {"D bus unresolved": 1, "_why": str(e)[:200]}
    S, bad = decode_series(cap, dbs)
    for n in ("0x418.PRND", "0x1C0.Motor_Speed", "0x330.Long_Accel_raw"):
        if not len(S[n][0]):
            return [], {f"no {n} on D": 1}
    rt, rv = S["0x1C0.Motor_Speed"]
    at_ = S["0x330.Long_Accel_raw"][0]
    lo_edge, hi_edge = max(rt[0], at_[0]), min(rt[-1], at_[-1])
    phase = task_phase_us(S)
    Q = quiet_points(S)
    t212 = S["0x212.TorqueRequest"][0]
    eps = []
    events = (find_reversals(*S["0x418.PRND"]) if kind == "reversal" else find_launches(S) if kind == "launch"
              else find_stops(S) if kind == "stop"
              else find_stops(S, STOP_LOW_ANCHOR_RPM, STOP_LOW_FROM_RPM, STOP_LOW_FROM_US))
    for t, frm, to in events:
        m = (rt >= t - ROLL_WIN_US) & (rt <= t)
        rpm_pre = float(np.max(np.abs(rv[m]))) if m.any() else 0.0
        if kind == "reversal" and rpm_pre < ROLL_RPM:
            continue
        a, b = t - PRE_US - HIST_US, t + POST_US + TAIL_US
        if a < lo_edge or b > hi_edge:
            drops["span past capture edge"] = drops.get("span past capture edge", 0) + 1
            continue
        j = np.searchsorted(Q, t - PRE_US, "right") - 1          # the latest quiet point at or before the handover
        quiet, no_quiet = (int(Q[j]), None) if j >= 0 else (None, "no quiet point before t - PRE")
        if quiet is not None:
            k0, k1 = np.searchsorted(t212, quiet, "left"), np.searchsorted(t212, t - PRE_US, "right")
            if k1 - k0 > 1 and np.any(np.diff(t212[k0:k1]) > GAP_US):      # the module went dark after q and no quiet
                                                                            # point followed its return before t - PRE
                quiet, no_quiet = None, "0x212 gap between the quiet point and t - PRE"
        if quiet is not None:
            a = min(a, quiet)
        ser = {}
        for n in NAMES:
            ts, vs = S[n]
            i0, i1 = np.searchsorted(ts, a - MARGIN_US, "left"), np.searchsorted(ts, b, "right")
            j0 = max(0, i0 - 1)                       # MARGIN_US and one frame more before the span (warm starts: a feed
            j1 = min(len(ts), i1 + 1)                 # delayed by up to MARGIN_US has its value due at the start), one
                                                      # frame after it (interpolation / accel validity at its end)
            ser[n] = (ts[j0:j1], vs[j0:j1])
        miss = [n for n in REQUIRED if len(ser[n][0]) < 2]
        if miss:
            drops["required series empty: " + ",".join(miss)] = drops.get("required series empty: " + ",".join(miss), 0) + 1
            continue
        e = dict(stem=cap.stem, path=cap.path, t_us=int(t), frm=frm, to=to, rpm_pre=rpm_pre, kind=kind,
                 cohort=cohort_of(t) if cohort_of else None, phase_us=phase, quiet_us=quiet, no_quiet=no_quiet,
                 span_us=[int(a), int(b)], decode_errors=bad,
                 missing=[n for n in NAMES if not len(ser[n][0])], series=ser)
        try:
            grid(e)                                   # the grid view must be defined over the whole episode
        except (KeyError, ValueError) as x:
            k_ = f"grid view undefined: {x}"
            drops[k_] = drops.get(k_, 0) + 1
            continue
        eps.append(e)
    return eps, drops


# ---------------------------------------------------------------------------------------------- store

def save(path, eps, header):
    """One compressed npz: meta JSON (episodes without series), header JSON, and per signal the concatenated
    t (int64 us) / v (float64) with per-episode offsets."""
    meta = [{k: v for k, v in e.items() if k != "series"} for e in eps]
    arrs = {}
    for n in NAMES:
        ts = [e["series"][n][0] for e in eps]
        vs = [e["series"][n][1] for e in eps]
        key = n.replace(".", "_")
        arrs[key + "__t"] = np.concatenate(ts) if ts else np.zeros(0, np.int64)
        arrs[key + "__v"] = np.concatenate(vs) if vs else np.zeros(0)
        arrs[key + "__n"] = np.asarray([len(x) for x in ts], np.int64)
    np.savez_compressed(path, meta=np.asarray(json.dumps(meta)), header=np.asarray(json.dumps(header)), **arrs)


def load(path):
    """(episodes, header).  Each episode dict carries `series` {name: (t_us, v)} again."""
    z = np.load(path)
    meta = json.loads(str(z["meta"]))
    header = json.loads(str(z["header"]))
    if header.get("signals") != NAMES:
        raise ValueError("store %s was built with a different signal set (io.inputs FEEDS changed?): rebuild it.  "
                         "stored-only %s, current-only %s" % (path, sorted(set(header.get("signals", [])) - set(NAMES)),
                                                              sorted(set(NAMES) - set(header.get("signals", [])))))
    for n in NAMES:
        key = n.replace(".", "_")
        t, v, cnt = z[key + "__t"], z[key + "__v"], z[key + "__n"]
        o = np.concatenate([[0], np.cumsum(cnt)])
        for i, e in enumerate(meta):
            e.setdefault("series", {})[n] = (t[o[i]:o[i + 1]], v[o[i]:o[i + 1]])
    return meta, header


# ----------------------------------------------------------------------------------------- grid views

def _hold(ser, g):
    t, v = ser
    if not len(t):
        raise KeyError("empty series")
    i = np.searchsorted(t, g, side="right") - 1
    if np.any(i < 0):
        raise ValueError("grid starts before the series' first frame")
    return v[i]


def _lin(ser, g):
    t, v = ser
    return np.interp(g, t, v)


def acc_grid(ser, g):
    """0x330 on grid g: (m/s2, valid).  Valid = both bracketing samples are guard-valid (ACC_GUARD around every
    invalid run) and no more than ACC_GAP_US apart; values interpolate over guard-valid samples only."""
    t, raw = ser
    ok = raw < ACC_INVALID
    okg = ok.copy()
    for k in np.flatnonzero(~ok):
        okg[max(0, k - ACC_GUARD[0]):k + ACC_GUARD[1] + 1] = False
    acc = raw * 0.08 - 9.84
    val = np.interp(g, t[okg], acc[okg]) if okg.sum() > 2 else np.full(len(g), np.nan)
    j = np.clip(np.searchsorted(t, g, side="right"), 1, len(t) - 1)
    valid = okg[j - 1] & okg[j] & ((t[j] - t[j - 1]) <= ACC_GAP_US) & (g >= t[0]) & (g <= t[-1])
    return val, valid


def grid(ep, pre_us=PRE_US, post_us=POST_US, hist_us=HIST_US):
    """The 10 ms episode view the old consumers read, built from the stored series.
    Keys: gear rpm trq pedal brk_p (-1 where 0x208 says invalid) brk_sw (0x200) brk_sw212 pub (0x212 in its 0.25 Nm
    units) m_min m_max acc acc_ok gear_status; pre_rpm pre_gear pre_gear_status over [t0 - hist, t0); plus t_us
    (grid times) and the episode's meta fields."""
    s = ep["series"]
    t0 = ep["t_us"] - pre_us
    g = t0 + np.arange(0, pre_us + post_us, TICK_US, dtype=np.int64)
    gp = t0 - hist_us + np.arange(0, hist_us, TICK_US, dtype=np.int64)
    acc, acc_ok = acc_grid(s["0x330.Long_Accel_raw"], g)
    bv = _hold(s["0x208.BrakePressure_Valid"], g)
    out = {k: v for k, v in ep.items() if k != "series"}
    out.update(
        t_us=g, gear=_hold(s["0x418.PRND"], g), rpm=_lin(s["0x1C0.Motor_Speed"], g), trq=_lin(s["0x1C0.Torque"], g),
        pedal=_hold(s["0x210.ThottlePedalPos"], g),
        brk_p=np.where(bv > 0, _hold(s["0x208.BrakePressure"], g), -1.0),
        brk_sw212=_hold(s["0x212.BrakeSW"], g),
        pub=np.round(_hold(s["0x212.TorqueRequest"], g) * 4.0),
        acc=acc, acc_ok=acc_ok, gear_status=_hold(s["0x418.GearStatus"], g),
        pre_rpm=_lin(s["0x1C0.Motor_Speed"], gp), pre_gear=_hold(s["0x418.PRND"], gp),
        pre_gear_status=_hold(s["0x418.GearStatus"], gp))
    for k, n in (("brk_sw", "0x200.BrakeSW"), ("m_min", "0x312.M_MIN"), ("m_max", "0x312.M_MAX")):
        out[k] = _hold(s[n], g) if len(s[n][0]) else None       # None, never a default (no shims): caller decides
    return out
