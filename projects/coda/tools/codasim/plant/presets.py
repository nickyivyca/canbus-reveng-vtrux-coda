r"""Named plant configurations.  Each entry records where its numbers came from.

  current  the ADOPTED plant (rd_shift_episodes step 3, STEP3_BODY; worklog 3AY): BodyPlant, contact
           damping c = 4.0 (closed_loop_step3.c_star.json), lash half-gap L = 0.20, body s 0.65 /
           f2 5.0 Hz / z2 0.10.  Phase-11 check under the 2026-10-09 DLCM model: ring rank corr 0.62,
           sim/car 1.38 (rd_model_recheck.out.txt).
  msm      TRIAL, NOT ADOPTED (rd_shaft_refit, 2026-10-08): light shaft c 1.25, k_lo/k_hi x 1.3,
           body s 0.70 / f2 5.0 / z2 0.30.  Matches the car's ~7 Hz motor-speed content; body spectral
           distance 0.19 under the 2026-10-09 DLCM model (rd_shaft_refit phase 14).

make(name) -> a fresh plant; overrides update the lash params (c, L, k_lo, ...) or, under "body", the
suspension.
"""
from . import lash as LP
from .vehicle import BodyPlant, FrictionPlant, MountPlant

PRESETS = {
    "current": dict(params=dict(c=4.0, L=0.20), body=dict(s=0.65, f2=5.0, z2=0.10)),
    "msm": dict(params=dict(c=1.25, L=0.20, k_lo=LP.DEFAULT["k_lo"] * 1.3, k_hi=LP.DEFAULT["k_hi"] * 1.3),
                body=dict(s=0.70, f2=5.0, z2=0.30)),
}


def make(name="current", dt_us=1000, params=None, body=None):
    pr = PRESETS[name]
    p = dict(pr["params"], **(params or {}))
    b = dict(pr["body"] or {}, **(body or {})) if (pr["body"] or body) else None
    if b is None:
        return FrictionPlant(p, dt_us)
    return (MountPlant if "Jh" in b else BodyPlant)(p, dt_us, **b)
