r"""Longitudinal accelerometer as 0x330 carries it (Sensor "0x330.Long_Accel").
Ported 2026-10-09 from notes/dlcm/artifacts/lash_plant.AccelSensor and the 0x330 handling in
rd_shift_episodes._closed by `Coda drivetrain lash model`, plan codasim_full_model.md step 3.
Arithmetic unchanged.

Per plant step: optional first-order low-pass at fc_hz (rd_shaft_refit phase 7; default off), pure delay
(18 ms fitted, H_a phase vs 0x1C0, worklog 3AD; delay_us = 0 -> none), quantised to 0.08 m/s2.  Sampled
every period_us (50 Hz) at phase 0: the FIRST plant step after reset and every 20th after it, as _closed
sampled (k % 20 == 0).
"""
import math

from ..interfaces import Provenance


class AccelSensor:
    signal = "0x330.Long_Accel"
    provenance = Provenance.PLANT

    def __init__(self, delay_us=18000, dt_us=1000, quantum=0.08, period_us=20000, fc_hz=None):
        self.dt_us, self.period_us = int(dt_us), int(period_us)
        self.dt = self.dt_us / 1e6
        self.q = quantum
        self.nbuf = max(1, int(round(delay_us / dt_us))) if delay_us > 0 else 0
        self.k_lp = (self.dt / (1.0 / (2 * math.pi * fc_hz) + self.dt)) if fc_hz else None
        self.reset(0.0)

    def reset(self, value0=0.0):
        self.a_lp = float(value0)
        self.buf = [float(value0)] * self.nbuf
        self.n = 0

    def step(self, plant_out):
        a = plant_out["acc_ms2"]
        self.a_lp = self.a_lp + self.k_lp * (a - self.a_lp) if self.k_lp is not None else a
        if self.nbuf:
            self.buf.append(self.a_lp)
            v = self.buf.pop(0)
        else:
            v = self.a_lp
        av = round(v / self.q) * self.q
        due = (self.n * self.dt_us) % self.period_us == 0
        self.n += 1
        return av if due else None
