r"""codasim interfaces -- the contracts between the DLCM half and the plant half.

JOINT FILE (plan codasim_full_model.md): either session may propose a change; it lands only after the
other acknowledges by message.  Drafted 2026-10-09 by `Coda drivetrain lash model`; interface points
1-3 agreed by `Coda DLCM work` 2026-10-09 (Load, `estimated` provenance, actuator owns the gear flip);
draft acknowledged 2026-10-09 with three changes, applied: GEAR418_* names, plant rpm = TRUE speed, no dt
argument on Actuator.step / Sensor.step (objects declare dt_us; the clock calls them at that rate).
Controller protocol proposed by `Coda DLCM work` 2026-10-09, amended by `Coda drivetrain lash model` (4 points:
command in counts; sensor samples stamped at the END of the plant step; reset(warmup); off-grid rule by
provenance), all four accepted and landed by `Coda DLCM work` 2026-10-09.  reset(warmup) removed at plan step 7
(2026-10-09, proposed by `Coda DLCM work`, acknowledged by `Coda drivetrain lash model`): it reproduced
DlcmLoop.reset for the deleted parity tests; a run starts with an open-loop lead-in from a quiet point instead.

FRAMES AND UNITS
  motor frame   + = the motor turning the way that drives the car FORWARD.  rpm, shaft torque, the
                torque applied by the MCM, and Load are in the motor frame.
  gear frame    the DLCM's frame: + = toward the selected gear's direction of travel.  The DLCM's MCM
                command is gear frame; the actuator converts it (Actuator.step takes the gear).
  acc_ms2       longitudinal acceleration of the BODY (what 0x330 senses before its sensor element),
                + = forward, m/s2.
  time          integer microseconds on the clock.  Plants, sensors and actuators declare `dt_us`
                (int); `dt` (s, float) = dt_us / 1e6 is derived, never accumulated.
  gear          at THIS boundary, the gear as the DLCM publishes it on 0x418 (ASCII: GEAR418_*).  NOT the
                DLCM's internal enum (GEAR_D = 40 / GEAR_R = 10 in creep_damper_blocks, torque_path_sim and
                codasim.dlcm); codasim's io layer owns the single 0x418-ASCII <-> internal mapping.

PROVENANCE (R4).  Every input to a run carries one; every result header lists the inputs by class.
"""
from enum import Enum
from typing import Callable, NamedTuple, Optional, Protocol, runtime_checkable

GEAR418_D, GEAR418_R, GEAR418_N, GEAR418_P = 68, 82, 78, 80


class Provenance(str, Enum):
    RECEIVED = "received"                # an external frame the DLCM receives, at its log time
    REVERSED = "reversed"                # DLCM-internal, recovered by inverting its own published form
    PLANT = "plant"                      # produced by the physical model in closed loop
    REPLAYED_OUTPUT = "replayed-output"  # a DLCM output the model does not compute yet (a known hole)
    ESTIMATED = "estimated"              # derived from the recording by a plant-side model (e.g. road load)
    SUBSTITUTE = "substitute"            # a DIFFERENT logged frame standing in for an unlogged input (declared)


class Load(NamedTuple):
    """External load on the vehicle side, motor frame, Nm at the motor shaft."""
    grade_Nm: float        # signed; + resists FORWARD motion (uphill when facing forward)
    friction_Nm: float     # >= 0; Coulomb (rolling + brake): opposes motion, HOLDS the car at
                           # standstill while |net driving torque| <= friction_Nm


PLANT_KEYS = ("rpm", "acc_ms2", "shaft_Nm", "in_lash")


@runtime_checkable
class Plant(Protocol):
    """Driveline + vehicle.  One step = dt_us of simulated time.
    reset/step return a dict with at least PLANT_KEYS:
      rpm       TRUE motor speed, motor frame (no sensor element: Sensor produces the observed view)
      acc_ms2   body acceleration (see FRAMES)
      shaft_Nm  shaft (contact) torque, motor frame
      in_lash   bool, the shaft is inside the lash gap
    Extra keys are allowed (w_v, w_b, theta, ...).  `w_m_sensed` (rad/s), when present, is the physical
    quantity the speed transducer measures if it differs from the rotor's absolute speed (rotor relative
    to a moving housing, MountPlant); speed sensors read it in preference to rpm.  It is kinematics, not
    a sensor model."""
    dt_us: int

    def reset(self, w_m0: float, T0: float = 0.0, w_v0: Optional[float] = None) -> dict: ...
    def step(self, T_motor_Nm: float, load: Load) -> dict: ...


@runtime_checkable
class Actuator(Protocol):
    """The MCM: DLCM command (gear frame, internal 0.1 Nm counts, Controller.command_counts()) -> torque
    applied to the motor (motor frame, Nm). Owns the counts -> delivered Nm conversion (a fitted factor)
    and the gear-frame -> motor-frame flip, from the gear it is TOLD (cosim wires the DLCM model's
    published gear, not the recorded 0x418), as GEAR418_*.  Called once per dt_us."""
    dt_us: int

    def reset(self, T0_motor_Nm: float = 0.0) -> None: ...
    def step(self, cmd_counts: int, gear: int) -> float: ...


@runtime_checkable
class Sensor(Protocol):
    """Plant output -> what a bus signal would carry.  step() runs at the plant step and returns a
    value only when a new sample is published (its frame instant), else None.
    `signal` names what it stands for, e.g. "0x1C0.Motor_Speed", "0x330.Long_Accel".  Called once per dt_us."""
    signal: str
    dt_us: int

    def reset(self, value0: float) -> None: ...
    def step(self, plant_out: dict) -> Optional[float]: ...


@runtime_checkable
class InputSource(Protocol):
    """Minimal common shape for anything that feeds a run from outside the closed loop.  The DLCM
    side's io/inputs registry may extend it; `name` and `provenance` are the part both halves rely on."""
    name: str
    provenance: Provenance


@runtime_checkable
class LoadSource(InputSource, Protocol):
    """Road load for the plant (plant-side; provenance ESTIMATED).  bind() gives it the episode, i.e.
    access to the recording, before the run; at() is then queried at plant steps.
    `causal` = False when the estimate at t uses recorded data after t (e.g. zero-phase filters); it is
    listed in the result header with the provenance."""
    causal: bool

    def bind(self, episode: dict) -> None: ...
    def at(self, t_us: int) -> Load: ...


@runtime_checkable
class Controller(Protocol):
    """The DLCM model.  It owns its tasks: install() registers them on the clock.  cosim never calls a
    controller tick; it registers the plant side on the same clock and connects signals to sinks.

    command_counts()  the latest MCM command, GEAR frame, internal 0.1 Nm counts (0xD0006A54), int.
                      Converting to delivered Nm is the actuator's (a fitted torque-follow factor is not
                      firmware arithmetic -- McmDelay.delivered_Nm_per_count).
    gear418()         the gear the DLCM publishes on 0x418 (GEAR418_*); the actuator is wired to THIS.
    sink(signal, provenance, delay_us=0) -> fn(t_us, value)
                      signal is a bus signal name ("0x1C0.Motor_Speed", "0x210.ThottlePedalPos",
                      "0x418.PRND", "0x208.BrakePressure", "0x200.BrakeSW", "0x312.M_MIN", ...); value is
                      the physical value as the DBC decodes it, and the sink performs the reverse path.
                      TIME STAMP: t_us is the instant the value DESCRIBES.  A sample from a plant step
                      registered at t describes t + dt_us, so cosim calls fn(t + dt_us, v).
                      DELIVERY: the write happens at t_us + delay_us, on the clock at ORDER_RX, so a
                      sample due exactly at a task instant is seen by that task.  A due time already in
                      the past raises.
                      OFF-GRID: for PLANT provenance a value off its signal's DBC quantum raises (a sensor
                      that forgot the quantisation is caught); RECEIVED/REVERSED values come from decoded
                      frames and are on-grid by construction.
    reset()           power-on state.  Pre-history comes from feeding the controller before the scored span
                      (R5): an open-loop lead-in on recorded inputs from a quiet point.
    header()          image + edits, every sink's signal / provenance / delay_us and timing parameters.
    """
    def install(self, clock) -> None: ...
    def reset(self) -> None: ...
    def sink(self, signal: str, provenance: Provenance,
             delay_us: int = 0) -> Callable[[int, float], None]: ...
    def command_counts(self) -> int: ...
    def gear418(self) -> int: ...
    def header(self) -> str: ...


def check_plant_out(d: dict) -> dict:
    """Raise if a plant result lacks a required key; returns d unchanged."""
    miss = [k for k in PLANT_KEYS if k not in d]
    if miss:
        raise KeyError(f"plant output missing {miss}")
    return d
