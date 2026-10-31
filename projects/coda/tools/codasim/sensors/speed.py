r"""Motor-speed path as the DLCM receives it (Sensor "0x1C0.Motor_Speed").
Ported 2026-10-09 from notes/dlcm/artifacts/closed_loop_sim.EdgeSpeedSensor (worklog 3AP,
speed_sensor_lowspeed.p2) by `Coda drivetrain lash model`, plan codasim_full_model.md step 3.  Arithmetic
unchanged.

The MCM's estimate is updated once per q_deg of motor rotation with the mean speed over that interval
(~6.6-7.6 deg/update measured between 5 and 120 rpm; every 10 ms frame above 120 rpm), held in between,
0 after `timeout` with no update, quantised to 0.5 rpm.  `transport_us` adds a pure delay.  The estimate
runs at the plant step; step() returns it only at frame instants (every frame_us, at the END of each
frame period), else None.  It reads plant_out["w_m_sensed"] when present, else the true speed.

Default transport 10 ms = the value rd_shift_episodes._closed used (adopted plant).  The further 2-tick
DLCM speed delay (0x308 lags 0x1C0 by 22 ms) is NOT here: it is a DLCM-side timing parameter
(io/inputs + clock, `Coda DLCM work`).
"""
import math

from ..interfaces import Provenance


class EdgeSpeedSensor:
    signal = "0x1C0.Motor_Speed"
    provenance = Provenance.PLANT

    def __init__(self, q_deg=7.0, timeout=0.25, transport_us=10000, dt_us=1000, frame_us=10000):
        self.q = math.radians(q_deg)
        self.dt_us, self.frame_us = int(dt_us), int(frame_us)
        self.dt, self.frame = self.dt_us / 1e6, self.frame_us / 1e6
        self.timeout = timeout
        self.buf = [0.0] * max(1, int(round(transport_us / dt_us)))
        self.reset(0.0)

    def reset(self, value0):
        self.acc = 0.0
        self.tsince = 0.0
        self.tframe = 0.0
        self.val = round(value0 * 2) / 2
        self.buf = [self.val] * len(self.buf)
        self.n = 0

    def estimate(self, w):
        """Advance one plant step with true (or sensed) motor speed w, rad/s; returns the held, delayed rpm."""
        self.acc += w * self.dt
        self.tsince += self.dt
        self.tframe += self.dt
        if abs(self.acc) >= self.q or (self.tframe >= self.frame and abs(w) * 60 / (2 * math.pi) > 120):
            if self.tsince > 0:
                self.val = round(self.acc / self.tsince * 60 / (2 * math.pi) * 2) / 2
            self.acc, self.tsince = 0.0, 0.0
            if self.tframe >= self.frame:
                self.tframe = 0.0
        elif self.tsince >= self.timeout:
            self.val, self.acc, self.tsince = 0.0, 0.0, 0.0
        self.buf.append(self.val)
        return self.buf.pop(0)

    def step(self, plant_out):
        w = plant_out.get("w_m_sensed", plant_out.get("w_m"))
        if w is None:
            w = plant_out["rpm"] * 2 * math.pi / 60
        v = self.estimate(w)
        self.n += 1
        return v if (self.n * self.dt_us) % self.frame_us == 0 else None
