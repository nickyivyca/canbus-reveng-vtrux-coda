r"""Shift-jerk measures and the model-check statistics, for recorded and simulated episodes alike.
Ported 2026-10-09 by `Coda drivetrain lash model`, plan codasim_full_model.md step 3, from
notes/dlcm/artifacts/gear_change_clunk.acc_steps, rd_shift_episodes (_measures, _spec) and rd_candidates
phase 11 (stats).  Arithmetic unchanged except: acc_steps takes integer-us times; the sim impact tie-break is explicit.

MEASURES (declared 2026-10-06, rd_shift_episodes plan step 1), from 0x330 Long_Accel:
  impact   largest single-sample step of consecutive guard-valid samples <= MAX_GAP_US apart, in
           (t_shift, t_shift + IMPACT_WIN_US], counts (0.08 m/s2); t_imp = its time
  ring     mean square of the 100 Hz episode-grid acceleration band-passed 2.4-10 Hz (zero phase, over the whole
           episode grid) over [t_imp + 0.1, t_imp + 2.0] s; NaN if < 1 s of window or < 95 % valid
  sim impact time   the simulated 50 Hz series' largest step between consecutive samples in [shift, shift + 2.5 s],
           in whole 0.08 m/s2 counts; ties go to the FIRST (user 2026-10-09: an explicit tie-break replaces the old
           float-rounding pick, which chose differently on 8 of 355 reversals and moved sim/car by 0.02).  Takes
           explicit sample times since 2026-10-10 (cosim samples at the plant's instants).
  spectrum  2 s from i0, linear detrend, Hann, |FFT|^2 normalised over 1-12 Hz
MODEL CHECK (rd_candidates phase 11): over events with sim > 0 and car > 0, Spearman rank corr of car vs sim ring,
  median sim/car ("bias"), and the p10-p90 spread of log10(sim/car) shown as a factor.
DIVERGENCE (regen13_model_screens.md step 3, 2026-10-15): PER EPISODE, car vs model trajectory, so a single episode
  the model gets wrong is ranked and named instead of averaging away inside population statistics (the user flagged a
  stop 0.7 s late by eye that model_check-style medians and rank correlations had passed).  See divergence().
  STANDARD since 2026-10-16 (user, at the step-3 close): every closed-loop screen reports divergence() per episode
  and lists the episodes divergence_flags() names: the model never stops (the car does); |dt_still| > 0.5 s;
  spd_max > 1 mph.  Thresholds in DIVERGENCE_FLAGS.
"""
import numpy as np
from scipy.signal import butter, sosfiltfilt

ACC_INVALID = 200
GUARD_BEFORE, GUARD_AFTER = 2, 8
MAX_GAP_US = 30000
IMPACT_WIN_US = 2500000
TICK_S = 0.01
BAND_RING = butter(2, (2.4, 10.0), btype="band", fs=100, output="sos")
_F = np.fft.rfftfreq(200, 0.01)


def acc_steps(t_us, raw):
    """[(t_us, step counts)] for consecutive samples that are both valid and not within the guard of an invalid
    run, and no more than MAX_GAP_US apart (gear_change_clunk.acc_steps; its docstring has the burst shape)."""
    raw = np.asarray(raw)
    n = len(raw)
    ok = raw < ACC_INVALID
    okg = ok.copy()
    for i in np.flatnonzero(~ok):
        okg[max(0, i - GUARD_BEFORE):min(n, i + GUARD_AFTER + 1)] = False
    j = np.flatnonzero(okg[:-1] & okg[1:] & (np.diff(t_us) <= MAX_GAP_US))
    return [(int(t_us[k + 1]), float(raw[k + 1] - raw[k])) for k in j]


def impact(ep):
    """(t_imp seconds after the shift, signed step counts) for a stored episode; (nan, 0) when no valid step."""
    t, raw = ep["series"]["0x330.Long_Accel_raw"]
    st = [(tt, v) for tt, v in acc_steps(t, raw) if ep["t_us"] < tt <= ep["t_us"] + IMPACT_WIN_US]
    if not st:
        return float("nan"), 0.0
    tt, v = max(st, key=lambda x: abs(x[1]))
    return (tt - ep["t_us"]) / 1e6, v


def sim_impact_time(t50_us, acc50, t_shift_us):
    """Seconds after the shift of the simulated 50 Hz series' largest step between consecutive samples, over the samples
    from the last one at or before the shift to the last one at or before shift + 2.5 s; the time is the later
    sample's.  Times are explicit (cosim samples at the plant's own instants, not on the episode grid); on a series
    sampled every 20 ms from the episode grid origin this is the step-3 pick exactly."""
    t50_us = np.asarray(t50_us)
    k0 = int(np.searchsorted(t50_us, t_shift_us, "right")) - 1
    k1 = int(np.searchsorted(t50_us, t_shift_us + IMPACT_WIN_US, "right")) - 1
    if k0 < 0 or k1 <= k0:
        return float("nan")
    steps = np.abs(np.rint(np.diff(acc50[k0:k1 + 1]) / 0.08))   # integer counts: quantised steps tie exactly,
    js = int(np.argmax(steps))                                    # and argmax takes the FIRST of the largest
    return (int(t50_us[k0 + js + 1]) - t_shift_us) / 1e6


def ring(acc100, ok, t_imp_rel, i_s):
    """Ring on the 100 Hz episode grid; i_s = the shift's grid index (rd_shift_episodes._measures)."""
    b = sosfiltfilt(BAND_RING, acc100 - acc100.mean())
    a = i_s + int(round((t_imp_rel + 0.1) / TICK_S))
    e = min(i_s + int(round((t_imp_rel + 2.0) / TICK_S)), len(b) - 30)
    if e - a < 100 or ok[a:e].mean() < 0.95:
        return float("nan")
    return float(np.mean(b[a:e] ** 2))


def spectrum(x, i0):
    seg = x[i0:i0 + 200]
    seg = seg - np.polyval(np.polyfit(np.arange(200), seg, 1), np.arange(200))
    S = np.abs(np.fft.rfft(seg * np.hanning(200))) ** 2
    return S / S[(_F >= 1.0) & (_F <= 12)].sum()


def model_check(pairs):
    """pairs: [(car ring, sim ring)].  dict(n, rho, bias, spread) over the pairs with both > 0 and finite;
    spread is the p10-p90 factor (10 ** (p90 - p10) of log10(sim/car))."""
    from scipy.stats import spearmanr
    x = [(c, s) for c, s in pairs if np.isfinite(c) and np.isfinite(s) and c > 0 and s > 0]
    if len(x) < 5:
        return dict(n=len(x), rho=float("nan"), bias=float("nan"), spread=float("nan"))
    c, s = np.array(x).T
    lr = np.log10(s / c)
    return dict(n=len(x), rho=float(spearmanr(c, s)[0]), bias=float(10 ** np.median(lr)),
                spread=float(10 ** (np.percentile(lr, 90) - np.percentile(lr, 10))))


MPH_PER_RPM = 86.8 / 8134          # motor rpm -> mph, as the step-3 scripts (regen13_screens MPH_PER_RPM)
STILL_RPM = 20.0                   # episodes.STOP_STILL_RPM
_LP2 = butter(2, 2.0, btype="low", fs=100, output="sos")
DIVERGENCE_FLAGS = dict(dt_still_s=0.5, spd_max_mph=1.0)   # user 2026-10-16 (regen13_model_screens step 3)


def divergence(g, r, i_s, lo_s=-1.0):
    """Car vs model for one closed-loop episode.  g = episodes.grid(ep); r = cosim result; i_s = the anchor's grid
    index.  Window: grid samples from max(anchor + lo_s, the model's first sample) to the grid's end.
      spd_rms, spd_max, t_spd_max   |car - model| motor speed, mph, both 2 Hz zero-phase low-passed first (0x1C0 steps
                                    0 <-> ~-44 rpm at a frame below ~80 rpm, a single-frame artifact); t in s from the anchor
      acc_rms                       car 0x330 (valid samples) - model 0x330 (AccelSensor, no gravity term), m/s2
      t_still_car, t_still_sim, dt_still   first |rpm| < STILL_RPM after the anchor, s; dt = sim - car (None if either
                                    never stops: then still_missing names which)"""
    t = g["t_us"]
    sim = np.interp(t, r["t_ms"], r["rpm"], left=np.nan, right=np.nan)
    a = max(i_s + int(round(lo_s / TICK_S)), int(np.argmax(np.isfinite(sim))))
    b = len(t) - int(np.argmax(np.isfinite(sim[::-1])))
    o = dict(spd_rms=None, spd_max=None, t_spd_max=None, acc_rms=None, t_still_car=None, t_still_sim=None,
             dt_still=None, still_missing=None)
    if b - a < 50:
        return o
    car, sm = g["rpm"][a:b], sim[a:b]
    d = np.abs(sosfiltfilt(_LP2, car) - sosfiltfilt(_LP2, sm)) * MPH_PER_RPM
    o.update(spd_rms=float(np.sqrt(np.mean(d ** 2))), spd_max=float(d.max()), t_spd_max=float((a + int(np.argmax(d)) - i_s) * TICK_S))
    acs = np.interp(t[a:b], r["t50"], r["acc50"])
    ok = np.asarray(g["acc_ok"][a:b], bool)
    if ok.sum() >= 50:
        o["acc_rms"] = float(np.sqrt(np.mean((g["acc"][a:b][ok] - acs[ok]) ** 2)))
    for key, x in (("t_still_car", np.abs(g["rpm"])), ("t_still_sim", np.abs(sim))):
        k = np.flatnonzero((np.arange(len(x)) > i_s) & (x < STILL_RPM))
        o[key] = float((k[0] - i_s) * TICK_S) if len(k) else None
    if o["t_still_car"] is not None and o["t_still_sim"] is not None:
        o["dt_still"] = o["t_still_sim"] - o["t_still_car"]
    elif o["t_still_car"] is not None or o["t_still_sim"] is not None:
        o["still_missing"] = "sim" if o["t_still_sim"] is None else "car"
    return o


def divergence_flags(o):
    """The standard flags for one divergence() result, in a fixed order: "never_stops" (the model never stops, the car
    does), "car_never_stops" (the reverse), "dt_still" (|dt_still| > DIVERGENCE_FLAGS dt_still_s), "spd_max" (spd_max >
    spd_max_mph).  An empty list means the episode passes."""
    f = []
    if o.get("still_missing") == "sim":
        f.append("never_stops")
    elif o.get("still_missing") == "car":
        f.append("car_never_stops")
    if o.get("dt_still") is not None and abs(o["dt_still"]) > DIVERGENCE_FLAGS["dt_still_s"]:
        f.append("dt_still")
    if o.get("spd_max") is not None and o["spd_max"] > DIVERGENCE_FLAGS["spd_max_mph"]:
        f.append("spd_max")
    return f
