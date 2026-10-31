r"""Vehicle-side plants: LashPlant's driveline with grade + Coulomb friction (stiction), a fore-aft body
suspension, and the (rejected) housing-on-mounts variant.
Ported 2026-10-09 from notes/dlcm/artifacts/rd_shift_episodes.py (FrictionPlant phase 7, BodyPlant
phase 10, MountPlant rd_shaft_refit phase 6) by `Coda drivetrain lash model`, plan codasim_full_model.md
step 3.  Arithmetic and integrator order unchanged (semi-implicit, angles on post-update speeds); only
the interface changed: step(T_motor_Nm, Load) -> dict, reset(w_m0, T0, w_v0).

LOAD (motor frame).  grade_Nm G resists forward motion; friction_Nm F >= 0 opposes motion and HOLDS
the wheel at standstill while |net| <= F.  A wheel speed that would cross zero within a step stops at 0.
"""
import math

from ..interfaces import check_plant_out
from . import lash as LP


class FrictionPlant:
    """lash.LashPlant with the vehicle side carrying grade G and Coulomb friction F (stiction).
    acc_ms2 is the vehicle's actual acceleration (dw_v/dt * GEOM)."""

    def __init__(self, params=None, dt_us=1000):
        self.p = dict(LP.DEFAULT, **(params or {}))
        self.dt_us = int(dt_us)
        self.dt = self.dt_us / 1e6

    def reset(self, w_m0, T0=0.0, w_v0=None):
        self.w_m = float(w_m0)
        self.w_v = float(w_m0 if w_v0 is None else w_v0)
        self.th = LP.preload_twist(T0, self.p)
        self.Ts, self.a = 0.0, 0.0
        return self._out(self.w_m)

    def _wheel(self, net, F, J):
        """Wheel speed after one step under net torque and Coulomb friction F (stiction at 0)."""
        dt, w0 = self.dt, self.w_v
        if w0 == 0.0:
            return 0.0 if abs(net) <= F else dt * (net - F * math.copysign(1.0, net)) / J
        w1 = w0 + dt * (net - F * math.copysign(1.0, w0)) / J
        return 0.0 if w1 * w0 < 0 else w1

    def step(self, T_motor_Nm, load):
        p, dt = self.p, self.dt
        G, F = load
        Ts = float(LP.contact_torque(self.th, self.w_m - self.w_v, p))
        self.w_m += dt * (T_motor_Nm - Ts) / p["J_m"]
        w0 = self.w_v
        w1 = self._wheel(Ts - G, F, LP.J_V)
        self.a = (w1 - w0) / dt * LP.GEOM
        self.w_v = w1
        self.th += dt * (self.w_m - self.w_v)
        self.Ts = Ts
        return self._out(self.w_m)

    def _out(self, w_sensed):
        return check_plant_out(dict(
            rpm=self.w_m * 60 / (2 * math.pi), acc_ms2=self.a, shaft_Nm=self.Ts,
            in_lash=abs(self.th) <= self.p["L"], w_m=self.w_m, w_m_sensed=w_sensed, w_v=self.w_v, theta=self.th))


class BodyPlant(FrictionPlant):
    """Wheel/unsprung J_w and sprung body J_b = s*J_V (J_w + J_b = J_V) joined by a linear fore-aft
    suspension k2, c2 (motor-frame units) set from the body-on-held-wheel formula for f2 (Hz), z2.
    Brake and rolling friction act on the wheel (stiction there); grade is shared by inertia fraction.
    acc_ms2 is the BODY's acceleration (what 0x330 senses).

    z_hold (OPT-IN, default None = off; 2026-10-15, regen13_model_screens.md step 3): the body spring's damping ratio
    while the wheel is held at standstill (w_v == 0 at the start of the step).  At a braked stop the car's 0x330 settles
    overdamped, with no overshoot, while this body (fitted to SHIFT ring) springs back at f2 with z2 and puts ~10x the
    car's 4-6 Hz power into the stop (notes/dlcm/artifacts/body_rock_check.py).  A MODELLING PATCH, not identified
    physics: z_hold 1.0 matches the car's stop to a +0.12 overshoot (stop_ring_proto.py phase 1).  It also acts during
    shifts with the wheel held: on the reversal ring model check (preset current) it moved 247 of 297 episodes'
    simulated ring, median ratio 0.99, p10 0.43; rank corr 0.61 -> 0.62, sim/car 1.23 -> 0.99, spread 7.7x -> 7.3x
    (stop_ring_proto.py phase 2)."""

    def __init__(self, params=None, dt_us=1000, s=0.85, f2=3.5, z2=0.144, z_hold=None):
        super().__init__(params, dt_us)
        self.Jb, self.Jw = s * LP.J_V, (1 - s) * LP.J_V
        self.k2 = self.Jb * (2 * math.pi * f2) ** 2
        self.c2 = 2 * z2 * math.sqrt(self.k2 * self.Jb)
        self.c2_free = self.c2
        self.z_hold = z_hold
        self.c2_hold = 2 * z_hold * math.sqrt(self.k2 * self.Jb) if z_hold is not None else self.c2

    def reset(self, w_m0, T0=0.0, w_v0=None):
        super().reset(w_m0, T0, w_v0)
        self.w_b = self.w_v
        self.th2 = T0 * self.Jb / (LP.J_V + self.p["J_m"]) / self.k2     # body spring preload
        self.ab = 0.0
        return self._out(self.w_m)

    def _out(self, w_sensed):
        d = super()._out(w_sensed)
        if hasattr(self, "w_b"):
            d["w_b"] = self.w_b
        return d

    def step(self, T_motor_Nm, load):
        p, dt = self.p, self.dt
        G, F = load
        if self.z_hold is not None:
            self.c2 = self.c2_hold if self.w_v == 0.0 else self.c2_free
        Ts = float(LP.contact_torque(self.th, self.w_m - self.w_v, p))
        Tb = self.k2 * self.th2 + self.c2 * (self.w_v - self.w_b)
        self.w_m += dt * (T_motor_Nm - Ts) / p["J_m"]
        fb = self.Jb / LP.J_V
        w1 = self._wheel(Ts - Tb - G * (1 - fb), F, self.Jw)
        wb1 = self.w_b + dt * (Tb - G * fb) / self.Jb
        self.a = (wb1 - self.w_b) / dt * LP.GEOM
        self.w_v, self.w_b = w1, wb1
        self.th += dt * (self.w_m - self.w_v)
        self.th2 += dt * (self.w_v - self.w_b)
        self.Ts = Ts
        return self._out(self.w_m)


class MountPlant(BodyPlant):
    """HYPOTHESIS TESTED AND NOT ADOPTED (rd_shaft_refit phase 6, 2026-10-08): BodyPlant plus the drive-unit
    housing rolling on its mounts; the speed sensor reads rotor relative to housing.
    Housing roll phi (physical rad), roll inertia Jh, mount stiffness from the uncoupled frequency fh (Hz)
    and damping zh.  Motor frame:
        shaft twist rate  = w_m + lam * phi_dot - w_v
        housing torque    = -sig * T_motor - lam * Ts - kh * phi - ch * phi_dot
        sensed speed      = w_m - sig * phi_dot   (returned as w_m_sensed; rpm stays the rotor's true speed.
                            The old MountPlant returned the sensed speed itself; rd_shaft_refit's outputs used it.)
    lam, sig = (N - 1, +1), or (N + 1, -1) with rev=True."""

    def __init__(self, params=None, dt_us=1000, s=0.85, f2=3.5, z2=0.144, Jh=4.0, fh=8.0, zh=0.1, rev=False, z_hold=None):
        if z_hold is not None:
            raise NotImplementedError("z_hold is a BodyPlant option; MountPlant.step does not apply it")
        super().__init__(params, dt_us, s=s, f2=f2, z2=z2)
        N = LP.RATIO
        self.lam, self.sig = (N + 1.0, -1.0) if rev else (N - 1.0, 1.0)
        self.Jh = Jh
        self.kh = Jh * (2 * math.pi * fh) ** 2
        self.ch = 2 * zh * math.sqrt(self.kh * Jh)

    def reset(self, w_m0, T0=0.0, w_v0=None):
        super().reset(w_m0, T0, w_v0)
        Ts0 = T0 * LP.J_V / (LP.J_V + self.p["J_m"])
        self.ph = -(self.sig * T0 + self.lam * Ts0) / self.kh
        self.phd = 0.0
        return self._out(self.w_m)

    def step(self, T_motor_Nm, load):
        p, dt = self.p, self.dt
        G, F = load
        Ts = float(LP.contact_torque(self.th, self.w_m + self.lam * self.phd - self.w_v, p))
        Tb = self.k2 * self.th2 + self.c2 * (self.w_v - self.w_b)
        self.w_m += dt * (T_motor_Nm - Ts) / p["J_m"]
        self.phd += dt * (-self.sig * T_motor_Nm - self.lam * Ts - self.kh * self.ph - self.ch * self.phd) / self.Jh
        self.ph += dt * self.phd
        fb = self.Jb / LP.J_V
        w1 = self._wheel(Ts - Tb - G * (1 - fb), F, self.Jw)
        wb1 = self.w_b + dt * (Tb - G * fb) / self.Jb
        self.a = (wb1 - self.w_b) / dt * LP.GEOM
        self.w_v, self.w_b = w1, wb1
        self.th += dt * (self.w_m + self.lam * self.phd - self.w_v)
        self.th2 += dt * (self.w_v - self.w_b)
        self.Ts = Ts
        return self._out(self.w_m - self.sig * self.phd)
