r"""Road load for the plant, estimated from the recording (LoadSource, provenance ESTIMATED).
Ported 2026-10-09 from notes/dlcm/artifacts/rd_shift_episodes.py (_inv_dyn phase 7, _slow_grade phase 9,
_meas_grade phase 21, the grade set-up of _closed) by `Coda drivetrain lash model`, plan
codasim_full_model.md step 3.  Arithmetic unchanged.

MODEL.  Load = (G(t), F(t)), motor frame:
  F(t) = R0 + kb * max(0, brake pressure)       Coulomb friction, R0/kb fitted on capture-half A (phase 7)
  G    from inverse dynamics r = LP2(torque x gear sign) - J_TOT * d/dt LP2(w), on brake-off moving samples:
         "const"       one G per episode, median(r - sign(w) R0)
         "slow"        1 s bin medians, interpolated, low-passed at 0.25 Hz (phase 9)
         "meas_step" / "meas_blend" / "meas_hold"   phase 21: d(t) = r - sign(w)(R0 + kb P) up to the gear
                       change (the pre-shift road is exogenous), then the constant G / a 0.5 s linear blend from
                       the pre-shift value to G / the pre-shift value held.  "meas_blend" is ADOPTED (user,
                       2026-10-08).
BRAKE FRICTION OPTION (plan regen13_model_screens.md step 2, 2026-10-14).  friction="p7" (the default; every earlier
result) is R0 + kb * P above.  friction="measured" replaces kb * P with the car-measured friction deceleration curve
(FRICTION_MEAS, m/s2 vs raw 0x208 pressure) converted at the plant's own torque-to-decel gain GEOM / J_TOT, so the
plant decelerates as the car does whatever its effective mass; R0 stays (it is the brake-off rolling friction the grade
fit uses).  Both the friction and the measured road (meas_* modes subtract the friction model) follow the option.
GRADE FALLBACK OPTION (regen13_model_screens.md step 2, user 2026-10-14; opt-in, default off).  A braked stop is
usually brake-on over the whole episode, so the grade fit (brake-off moving samples) has < 20 samples and bind()
refuses.  grade_fallback=True then takes G = median over ALL moving samples of r - sign(w)(R0 + brake friction): the
friction model sets the grade too.  Episodes with >= 20 brake-off moving samples are unchanged (checked: 512 of 512
stop runs identical).  Default off so no earlier sweep's runnable set moves.
STOP GRADE OPTION (regen13_model_screens.md step 3, user 2026-10-15; opt-in, default off).  stop_grade="parked" ramps G,
over the STOP_GRADE_RAMP_S before the car's recorded standstill (first grid sample after the episode anchor with
|0x1C0 rpm| < 20), linearly from the mode's own value to the slope the car's 0x330 reads parked -- median of the valid
samples in [standstill + 0.2, + 1.5] s (>= 10 of them, car still throughout), converted at the plant's gain
J_TOT / GEOM, + = nose up = resists forward -- and holds it after.  Stop episodes in D only; anything else, or too
few valid parked samples, is refused (bind raises), never defaulted.  WHY (stop_grade_check.py): the constant G after
the anchor is the slope while moving; where the car stops on a different slope (coda_20260524_120838_T0: -25 Nm moving,
+49 Nm parked) the model rolls on past the car's standstill, and the model's lateness tracks G - parked slope
(rho -0.51 over 167 D stops).  CAVEATS: the parked 0x330 window can hold the tail of the rock-back after the stop
(body_rock_check.py: ~15-20 % of the braking reading, decaying over ~1 s), and 0x330's own zero offset is unchecked;
the median G - parked over those stops was -10.5 Nm.  Uses the recording after t (as every mode here).
AGAINST THE GEAR (user 2026-10-09): samples where the car rolls against the selected gear are left out of the grade
fit and held over in the measured road -- 0x1C0 Torque (and 0x312 TorqueFeedback) report the opposite sign on ~20 %
of them while the body acceleration follows the command (worklog 3BD).
NOT CAUSAL: every mode uses zero-phase filters over the whole episode, so the load at t depends on the
recording after t (`causal` = False; listed in result headers).

EPISODE.  A dict on a 10 ms grid starting at t_us = 0, with gear (0x418 ASCII), trq (0x1C0 torque, Nm,
gear frame), rpm (motor), brk_p (0x208 count, < 0 = invalid), brk_sw; the gear change at pre_s.
"""
import math

import numpy as np
from scipy.signal import butter, sosfiltfilt

from ..interfaces import GEAR418_D, GEAR418_R, Load, Provenance
from .lash import GEOM, J_TOT

TICK_US = 10000
# rd_shift_episodes.p7.friction.json (phase 7, half A; worklog 3AY)
FRICTION_P7 = dict(R0=17.834099755590337, kb=0.4817454085020181)
# Friction deceleration, regen subtracted, by raw 0x208 BrakePressure: bin median pressure -> median m/s2, all speeds,
# apply + hold + release (notes/dlcm/artifacts/regen13_inputs.p3.json "curve"; write-up regen13-modelling-inputs.md
# section 3; MEASURED, reviewed by the user 2026-10-14).  The P = 0 bin (0.032 m/s2; brake switch on, no pressure) is
# replaced by 0: the plant has no switch input and must match "p7" with the brake off.  Above the last bin, the last
# segment's slope continues.
FRICTION_MEAS = (
    (0.0, 0.0),
    (5.0, 0.0460),
    (14.8, 0.0667),
    (24.8, 0.0954),
    (35.0, 0.1220),
    (45.3, 0.1514),
    (55.5, 0.1865),
    (70.7, 0.2480),
    (90.4, 0.3356),
    (110.9, 0.4448),
    (136.9, 0.6201),
    (162.6, 0.7645),
    (186.5, 0.9241),
    (220.0, 1.1273),
    (266.6, 1.4307),
    (332.0, 1.8250),
    (425.4, 2.4645),
    (555.6, 3.2094))
FRICTIONS = ("p7", "measured")
STOP_GRADES = (None, "parked")
STOP_GRADE_RAMP_S = 0.5
STOP_KINDS = ("stop", "stop_low")
_LP2 = butter(2, 2.0, btype="low", fs=100, output="sos")


def inv_dyn(m):
    """(r, w_lp, P, moving mask, brake-on mask) on the episode grid (phase 7)."""
    g = m["gear"]
    sg = np.where(g == GEAR418_R, -1.0, np.where(g == GEAR418_D, 1.0, np.nan))
    trq_mf = m["trq"] * np.nan_to_num(sg, nan=1.0)
    w = m["rpm"] * 2 * math.pi / 60
    wl = sosfiltfilt(_LP2, w)
    r = sosfiltfilt(_LP2, trq_mf) - J_TOT * np.gradient(wl, 0.01)
    P = np.where(m["brk_p"] > 0, m["brk_p"], 0.0)
    rpm_l = wl * 60 / (2 * math.pi)
    zc = np.flatnonzero(np.diff(np.sign(trq_mf)) != 0)
    near = np.zeros(len(r), bool)
    for k in zc:
        near[max(0, k - 50):k + 50] = True
    against = np.sign(rpm_l) * np.nan_to_num(sg) < 0           # rolling against the selected gear: 0x1C0's sign is
    mov = (np.abs(rpm_l) >= 40) & np.isfinite(sg) & ~near & ~against   # unreliable there (worklog 3BD), so excluded
    mov[:30] = mov[-30:] = False
    bon = (m["brk_sw"] > 0) | (P > 0)
    return r, wl, P, mov, bon


def slow_grade(g_obs, mask, g_const):
    """Phase-9 grade profile: brake-off moving samples, 1 s bin medians, interpolated, 0.25 Hz zero-phase."""
    n = len(g_obs)
    cs, vs = [], []
    for a in range(0, n, 100):
        mm = mask[a:a + 100]
        if mm.sum() >= 10:
            cs.append(a + 50); vs.append(float(np.median(g_obs[a:a + 100][mm])))
    if len(cs) < 2:
        return np.full(n, g_const)
    gg = np.interp(np.arange(n), cs, vs)
    return sosfiltfilt(butter(2, 0.25, btype="low", fs=100, output="sos"), gg)


def brake_nm(P, friction="p7", kb=FRICTION_P7["kb"]):
    """Brake friction, motor-frame Nm, for pressure P >= 0 (array or scalar): kb * P ("p7"), or FRICTION_MEAS at the
    plant's gain ("measured")."""
    if friction == "p7":
        return kb * P
    if friction != "measured":
        raise ValueError(friction)
    x, y = np.array(FRICTION_MEAS).T
    d = np.interp(P, x, y) + np.maximum(0.0, np.asarray(P, float) - x[-1]) * (y[-1] - y[-2]) / (x[-1] - x[-2])
    return d * J_TOT / GEOM


def meas_grade(m, r, wl, P, R0, kb, G, mode, pre_s=2.0, Fb=None):
    """Phase 21: measured road up to the gear change, then step / blend / hold (see module docstring).
    Fb: brake friction per sample (motor-frame Nm); None = kb * P."""
    g = np.asarray(m["gear"], int)
    rpm_l = wl * 60 / (2 * math.pi)
    d = r - np.sign(wl) * (R0 + (kb * P if Fb is None else Fb))
    sg = np.where(g == GEAR418_R, -1.0, np.where(g == GEAR418_D, 1.0, 0.0))
    ok = (np.abs(rpm_l) >= 20) & np.isin(g, (GEAR418_D, GEAR418_R)) & (np.sign(rpm_l) * sg >= 0)   # not against the gear
    for i in range(len(d)):
        if not ok[i]:
            d[i] = d[i - 1] if i > 0 else G
    i_s = int(round(pre_s / 0.01))
    k = np.flatnonzero(g[i_s - 50:i_s + 1] != g[i_s + 5])
    j = i_s - 50 + int(k[-1]) if len(k) else i_s
    out = d.copy()
    hold = float(np.mean(d[max(0, j - 20):j + 1]))
    if mode == "meas_step":
        out[j + 1:] = G
    elif mode == "meas_blend":
        n = len(out) - j - 1
        ramp = np.clip(np.arange(1, n + 1) / 50.0, 0, 1)
        out[j + 1:] = hold + (G - hold) * ramp
    elif mode == "meas_hold":
        out[j + 1:] = hold
    else:
        raise ValueError(mode)
    return out


class RoadLoad:
    """LoadSource: Load(G[i], R0 + kb * max(0, brk_p[i])) for the 10 ms tick i containing t_us."""
    provenance = Provenance.ESTIMATED
    causal = False
    MODES = ("const", "slow", "meas_step", "meas_blend", "meas_hold")

    def __init__(self, mode="meas_blend", R0=FRICTION_P7["R0"], kb=FRICTION_P7["kb"], pre_s=2.0, friction="p7",
                 grade_fallback=False, stop_grade=None, stop_grade_ramp_s=STOP_GRADE_RAMP_S):
        if mode not in self.MODES:
            raise ValueError(mode)
        if friction not in FRICTIONS:
            raise ValueError(friction)
        self.mode, self.R0, self.kb, self.pre_s, self.friction = mode, R0, kb, pre_s, friction
        self.grade_fallback = bool(grade_fallback)
        if stop_grade not in STOP_GRADES:
            raise ValueError(stop_grade)
        self.stop_grade, self.stop_grade_ramp_s = stop_grade, float(stop_grade_ramp_s)
        self.name = (f"road_load.{mode}" + ("" if friction == "p7" else f"+friction.{friction}")
                     + ("+grade_fallback" if self.grade_fallback else "")
                     + ("" if stop_grade is None else f"+stop_grade.{stop_grade}(ramp {self.stop_grade_ramp_s:g} s)"))

    def bind(self, episode):
        """Raises ValueError when the episode has < 20 brake-off moving samples (no grade estimate), or with
        grade_fallback < 20 moving samples.  Sets self.fallback (the fallback grade was used)."""
        m, R0, kb = episode, self.R0, self.kb
        r, wl, P, mov, bon = inv_dyn(m)
        off = mov & ~bon
        s_ = np.sign(wl)
        G = float(np.median(r[off] - s_[off] * R0)) if off.sum() >= 20 else float("nan")
        self.fallback = False
        if not np.isfinite(G) and self.grade_fallback:
            if mov.sum() < 20:
                raise ValueError("no grade estimate: < 20 moving samples (grade_fallback)")
            Fb_ = kb * P if self.friction == "p7" else brake_nm(P, self.friction)
            G = float(np.median(r[mov] - s_[mov] * (R0 + Fb_[mov])))
            self.fallback = True
        if not np.isfinite(G):
            raise ValueError("no grade estimate: < 20 brake-off moving samples")
        if self.mode == "slow":
            Gs = slow_grade(r - s_ * R0, off, G)
        elif self.mode.startswith("meas"):
            Gs = meas_grade(m, r, wl, P, R0, kb, G, self.mode, self.pre_s,
                            Fb=None if self.friction == "p7" else brake_nm(P, self.friction))
        else:
            Gs = np.full(len(r), G)
        self.G_parked = None
        if self.stop_grade == "parked":
            Gs = Gs.copy()
            self.G_parked = self._parked_grade(m)
            k, n = self._k_still, int(round(self.stop_grade_ramp_s / 0.01))
            a = max(0, k - n)
            Gs[a:k] = Gs[a] + (self.G_parked - Gs[a]) * np.arange(1, k - a + 1) / (k - a)
            Gs[k:] = self.G_parked
        self.G, self.Gs = G, Gs
        if self.friction == "p7":
            self.F = [R0 + kb * max(0.0, float(x)) for x in m["brk_p"]]
        else:
            self.F = [R0 + float(x) for x in brake_nm(P, self.friction)]

    def _parked_grade(self, m):
        """Motor-frame Nm of the slope the car's 0x330 reads parked after the stop (see STOP GRADE OPTION); sets
        self._k_still.  Raises ValueError when it cannot be measured."""
        if m.get("kind") not in STOP_KINDS:
            raise ValueError("stop_grade: not a stop episode (kind %s)" % m.get("kind"))
        i_s = int(round(self.pre_s / 0.01))
        rpm = np.abs(m["rpm"])
        k = np.flatnonzero((np.arange(len(rpm)) > i_s) & (rpm < 20.0))
        if not len(k):
            raise ValueError("stop_grade: no recorded standstill")
        k = int(k[0])
        if m["gear"][k] != GEAR418_D:
            raise ValueError("stop_grade: not in D at the standstill")
        w = slice(k + 20, k + 150)
        if k + 150 > len(rpm) or (rpm[w] >= 20.0).any():
            raise ValueError("stop_grade: car not still over the parked window")
        ok = np.asarray(m["acc_ok"][w], bool)
        if ok.sum() < 10:
            raise ValueError("stop_grade: < 10 valid parked 0x330 samples")
        self._k_still = k
        return float(np.median(np.asarray(m["acc"][w])[ok])) * J_TOT / GEOM

    def at(self, t_us):
        i = min(int(t_us) // TICK_US, len(self.Gs) - 1)
        return Load(self.Gs[i], self.F[i])
