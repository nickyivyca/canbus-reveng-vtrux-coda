r"""Driveline lash element and the two-inertia LashPlant (no friction).
Ported 2026-10-09 from notes/dlcm/artifacts/lash_plant.py (`Coda drivetrain lash model` session,
plan codasim_full_model.md step 3).  Arithmetic and integrator order are unchanged; see that file's
docstring and worklog 3AD for where each number comes from.

STRUCTURE.  Two inertias joined by a backlash element with a load-stiffening contact spring and
contact damping, all at the MOTOR shaft (motor frame, + = forward):

    T_motor -> [J_m] --(gap 2L, spring k(delta), damper c)--> [J_V] <- load
                 w_m                                            w_v

theta = theta_m - theta_v (motor rad).  Contact penetration on the positive flank is delta =
theta - L, on the negative flank delta = -(theta + L).
    spring  F(delta) = k_hi*delta - (k_hi - k_lo)*d_s*(1 - exp(-delta/d_s))
    damper  c * delta_dot, only in contact
    CLAMP   the contact torque never changes sign across the flank (worklog 3T)

INTEGRATOR.  Semi-implicit Euler at dt, theta advanced with the POST-update speeds (worklog 3Q-3T:
an explicit-Euler reimplementation silently produced a different plant; keep this order).
"""
import math

import numpy as np

from ..interfaces import Load, check_plant_out

J_V = 4.28              # vehicle inertia at the motor, kg m2 (clunk_model)
GEOM = 0.04714          # m of vehicle travel per motor rad (clunk_model)
RATIO = 6.576           # motor : wheel
J_TOT = 4.28 + 0.105    # J_V + J_m, used by the road-load inverse dynamics

# Fitted 2026-10-04 (worklog 3AD, lash_plant_fit.grid2.out.txt).  k_lo / k_hi / d_s are not separately
# identified (effective stiffness ~130-175); c is uncertain by ~5x (presets set it).
DEFAULT = dict(J_m=0.105, L=0.20, k_lo=130.0, k_hi=175.0, d_s=0.5, c=4.0, clamp=True)


def spring(delta, k_lo, k_hi, d_s):
    """Load-stiffening contact spring, delta >= 0 (penetration), torque >= 0."""
    return k_hi * delta - (k_hi - k_lo) * d_s * (1.0 - np.exp(-delta / d_s))


def spring_inverse(T, k_lo, k_hi, d_s, iters=30):
    """Penetration that carries contact torque T >= 0 (Newton; scalar or array)."""
    T = np.asarray(T, float)
    x = T / k_hi
    for _ in range(iters):
        f = spring(x, k_lo, k_hi, d_s) - T
        fp = k_hi - (k_hi - k_lo) * np.exp(-x / d_s)
        x = np.maximum(x - f / fp, 0.0)
    return x


def contact_torque(th, rel, p):
    """Shaft torque for twist th and relative speed rel (arrays or scalars)."""
    L, c = p["L"], p["c"]
    pos = th > L
    neg = th < -L
    dp = np.where(pos, th - L, 0.0)
    dn = np.where(neg, -(th + L), 0.0)
    Tp = spring(dp, p["k_lo"], p["k_hi"], p["d_s"]) + c * rel
    Tn = -spring(dn, p["k_lo"], p["k_hi"], p["d_s"]) + c * rel
    if p["clamp"]:
        Tp = np.maximum(Tp, 0.0)
        Tn = np.minimum(Tn, 0.0)
    return np.where(pos, Tp, np.where(neg, Tn, 0.0))


def preload_twist(T0, p):
    """Equilibrium twist carrying the share of motor torque T0 that accelerates J_V."""
    Ts0 = T0 * J_V / (J_V + p["J_m"])
    d = float(spring_inverse(abs(Ts0), p["k_lo"], p["k_hi"], p["d_s"]))
    return (p["L"] + d) * (1.0 if T0 >= 0 else -1.0)


class LashPlant:
    """Two inertias + lash, no friction element: load.grade_Nm acts as a plain road torque and
    load.friction_Nm must be 0 (use vehicle.FrictionPlant for Coulomb friction / stiction)."""

    def __init__(self, params=None, dt_us=1000):
        self.p = dict(DEFAULT, **(params or {}))
        self.dt_us = int(dt_us)
        self.dt = self.dt_us / 1e6
        self.reset(0.0)

    def reset(self, w_m0, T0=0.0, w_v0=None):
        self.w_m = float(w_m0)
        self.w_v = float(w_m0 if w_v0 is None else w_v0)
        self.th = preload_twist(T0, self.p)
        self.Ts = 0.0
        return self._out(0.0)

    def step(self, T_motor_Nm, load=Load(0.0, 0.0)):
        if load.friction_Nm != 0.0:
            raise ValueError("LashPlant has no friction element; use vehicle.FrictionPlant")
        p, dt, road = self.p, self.dt, load.grade_Nm
        Ts = float(contact_torque(self.th, self.w_m - self.w_v, p))
        self.w_m += dt * (T_motor_Nm - Ts) / p["J_m"]
        self.w_v += dt * (Ts - road) / J_V
        self.th += dt * (self.w_m - self.w_v)
        self.Ts = Ts
        return self._out(road)

    def _out(self, road):
        return check_plant_out(dict(
            rpm=self.w_m * 60.0 / (2 * math.pi), acc_ms2=GEOM * (self.Ts - road) / J_V, shaft_Nm=self.Ts,
            in_lash=abs(self.th) <= self.p["L"], w_m=self.w_m, w_m_sensed=self.w_m, w_v=self.w_v, theta=self.th))
