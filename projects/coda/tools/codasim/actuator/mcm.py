r"""The MCM: DLCM command (gear frame, internal 0.1 Nm counts) -> torque applied to the motor (motor frame, Nm).
Ported 2026-10-09 from the MCM handling in notes/dlcm/artifacts/rd_shift_episodes._closed and
closed_loop_sim.run_episode by `Coda drivetrain lash model`, plan codasim_full_model.md step 3.

Delivered torque = counts x delivered_Nm_per_count (0.096: a FITTED torque-follow factor, closed_loop_sim
NM_DELIVERED_PER_INTERNAL, not firmware arithmetic; the same float expression DlcmLoop used).
Gear-frame -> motor-frame flip: negated when the gear it is TOLD is R (GEAR418_R), else passed through
(closed_loop_sim A8).  Then a pure delay of delay_us (MCM_DELAY_STEP3 = 25 ms, closed_loop_step3; no
response dynamics).  The queue starts filled with T0 (motor frame), as _closed did with the recorded
0x1C0 torque x gear sign.
"""
from ..interfaces import GEAR418_R

MCM_DELAY_STEP3_US = 25000
NM_DELIVERED_PER_COUNT = 0.096


class McmDelay:
    def __init__(self, delay_us=MCM_DELAY_STEP3_US, dt_us=1000, delivered_Nm_per_count=NM_DELIVERED_PER_COUNT):
        self.dt_us = int(dt_us)
        self.delivered_Nm_per_count = delivered_Nm_per_count
        self.n = int(round(delay_us / dt_us))
        self.reset(0.0)

    def reset(self, T0_motor_Nm=0.0):
        self.q = [float(T0_motor_Nm)] * self.n

    def step(self, cmd_counts, gear):
        cmd = cmd_counts * self.delivered_Nm_per_count
        self.q.append(-cmd if int(gear) == GEAR418_R else cmd)
        return self.q.pop(0)
