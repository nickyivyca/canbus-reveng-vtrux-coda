r"""Closed-loop co-simulation: the DLCM model, the MCM, the driveline / vehicle plant and the sensors on one clock.
Written 2026-10-10 by `Coda drivetrain lash model`, plan codasim_full_model.md step 4 ("Step-4 design as agreed",
user 2026-10-10).  Simulation only; NOTHING HERE IS FLASHED.

ONE EPISODE (episodes.py store), times in integer us at log time:

    quiet_us ............ h ........ t_shift ........ t_shift + POST
    |-- open-loop lead-in --|-------------- closed loop ---------------|

  clock    starts at the episode's quiet point (episodes.quiet_points: 0x212 at exactly 0 for 0.5 s, >= 1 s after the
           module came up -- the only instants where a power-on controller is faithful; ecm2_gate).  No warm-up, no
           state copied from the recording: the controller's pre-history is the lead-in itself.
  DLCM     DlcmController(cal, bounds=...) at 10 ms on the capture's task phase (episodes.task_phase_us = io.inputs'
           ALIGN_US rule).  `bounds` is passed explicitly on every run.
  inputs   every io.inputs FEED except the speed, from the store, with io.inputs' provenance and shifts (warm start: the
           latest value at or before the clock start, as io.inputs.Replay); bounds="computed" adds io.inputs'
           COMPUTED_BOUND_FEEDS (0x275 / 0x276 / 0x200 B0 and the 0x1C0 HV SUBSTITUTE for 0x20B).  ALL of these stay
           recorded through the closed loop: they are OPEN LOOP WITH RESPECT TO THE PLANT, and header() says so.
  rx       RECEIVE TIMING (rx_timing="poll", the default since 2026-10-14, plan regen13_model_screens.md step 2b;
           user: "use the same sim as the other session put together, but check its work"): every RECEIVED /
           SUBSTITUTE feed, and the speed, reaches the controller on the firmware's COM RX poll schedule
           (io/comsched.py, worklog 6H.74; checked independently in notes/dlcm/artifacts/rx_poll_timing_check.py):
           the latest frame arriving at or before a poll, delivered at the tick 10 ms after it.  Poll phases are
           anchored on the episode's own logged DLCM TX frames (ANCHOR_SERIES).  rx_timing="arrival" is the rule
           before that: feeds at arrival, the speed speed_delay_us after its frame (the declared 12-22 ms bracket).
  speed    one path for the whole run: a "0x1C0.Motor_Speed" value (the M-CAN 0x20C buffer).  rx_timing="poll": on
           0x20C's poll (divider 2, 5 ms after each 0x308 burst) with 0x20C arriving SPEED_ARRIVAL_US after the logged
           0x1C0 (FITTED: codasim_cosim_check phase 2o, 1.5 ms; sensitivity 0.65 / 2.5 ms).  "arrival":
           speed_delay_us after its frame instant (DECLARED bracket, 12-22 ms, never fitted).  Before the handover h the values are the RECORDED 0x1C0 frames
           (SUBSTITUTE: the D-CAN broadcast standing in for the unlogged 0x20C); from h they come from the plant's
           EdgeSpeedSensor (PLANT).  speed="0x308" instead replays the reversed 0x308 for the whole run, exactly as
           io.inputs does (open loop; the parity check against io.inputs.replay).
  handover h = the first recorded 0x1C0 frame at or after t_shift - PRE_US, so the sensor's 10 ms frames continue the
           recorded 0x1C0 cadence (frames at h + k * 10 ms).
  plant    reset at h from the recorded 0x1C0 speed at h, preloaded with the torque the MCM model applies at h; then
           1 ms steps: actuator (ORDER_ACT) -> plant (ORDER_PLANT) -> sensors (ORDER_SENSOR).  Road load RoadLoad
           (ESTIMATED, not causal) on the episode grid.
  MCM      McmDelay, stepped from h - its delay so its queue holds the MODEL's own commands at h (no recorded
           torque enters the plant).  The gear it applies is the MODEL's published 0x418 (DlcmController.gear418(),
           Pub418Prnd), never the recorded one -- which in this model is itself the reversed 0x418 GearStatus, an
           input: the gear state machine is not ported.
  pedal    OPT-IN pedal_remap=<reference CAL> (default None = the recorded pedal): an ADAPTED DRIVER (PedalRemap; plan
           regen13_model_screens.md step 4, user 2026-10-16 "do option 2").  Each recorded 0x210 delivery becomes the
           request the reference CAL's pedal map gives for it at the current speed, and the pedal the run's CAL needs
           for that request is delivered instead.  header() says so.
  stop     t_shift + POST_US, or a predicted ECM2 reset: the controller halts (user rule 2026-10-09: a predicted
           reset rejects the candidate; recovery is not modelled).  The result carries `resets`.

    from codasim import cosim
    r = cosim.run(ep, preset="current", bounds="computed")                                   # COM poll timing
    r = cosim.run(ep, preset="current", bounds="computed", rx_timing="arrival", speed_delay_us=12000)   # the old rule
"""
import math

import numpy as np

from . import episodes as E
from .actuator.mcm import McmDelay
from .clock import ORDER_ACT, ORDER_PLANT, ORDER_RX, ORDER_SENSOR, ORDER_TX, Clock
from .dlcm.controller import DlcmController
from .fixedpoint import ld_h, ld_hu
from .image import Image
from .interfaces import GEAR418_R, Provenance
from .io import inputs as INP
from .io.comsched import ARRIVAL_OFFSET_US, ComSchedule
from .lut import lut2d
from .plant import presets
from .plant.road import RoadLoad
from .sensors.accel import AccelSensor
from .sensors.speed import EdgeSpeedSensor

SPEED_DELAY_BRACKET_US = (12000, 22000)       # declared, not fitted (plan step 4); rx_timing="arrival" only
SPEED_ARRIVAL_US = 1500     # 0x20C reaches the DLCM this long after the logged 0x1C0: FITTED 2026-10-15 (user-adopted)
                            # codasim_cosim_check.py phase 2o, cosim SpeedRaw vs the reversed 0x308 echo over 308
                            # episodes: 77.8 % identical at 1500 us, flat 650-2500 us (77.2 / 75.8 %), 71.9 % at 0,
                            # 57.8 % at -1500. M CAN is never logged, so this places 0x20C relative to the poll only.
                            # The edge fit (rx_poll_timing_check.py phase 5) gave 650 us. Sensitivity runs use
SPEED_ARRIVAL_SENSITIVITY_US = (650, 2500)   # the two ends of the flat stretch
BODY_HOLD_Z = 1.0           # BodyPlant z_hold, the DEFAULT since 2026-10-17 (user, plan regen13_model_screens.md step 4:
                            # "agree" to making it default for shift and stop grading).  Step 3: the car's 0x330 settles
                            # without overshoot after a braked stop, the bare body ~10x its 4-6 Hz power
                            # (body_rock_check.py, stop_ring_proto.py).  Step 4 (regen13_screens phase 4h): on the
                            # recorded shifts, own CAL, model / car ring 1.23 -> 0.99 (median), Spearman 0.61 -> 0.62.
                            # To be checked against creep-off car data (user: "needs to be verified in data").
SPEED_RECORD = 0x20C        # the COM RX record the speed comes from (inputs.py docstring, worklog 6H.68)
# logged DLCM TX frames stored in the episodes, by id: their times anchor the poll phases (io/comsched.anchors)
ANCHOR_SERIES = {0x210: "0x210.ThottlePedalPos", 0x212: "0x212.TorqueRequest", 0x308: "0x308.InputShaftSpeed",
                 0x418: "0x418.PRND", 0x08C: "0x08C.Flag_B0bit2"}
TRACE = ("McmCommand", "Pub212Raw", "Pub418Prnd", "SpeedRaw")


class NotRunnable(Exception):
    """The episode cannot be co-simulated (no quiet point, no road estimate, ...); the message says why."""


class PedalRemap:
    """OPT-IN adapted driver (plan regen13_model_screens.md step 4; user 2026-10-16: "do option 2").  The recorded pedal
    was pressed against whatever CAL was in the car; a driver adapts to a new pedal curve.  This replaces the 0x210 sink:
    after the controller's own sink sets PedalInternal from the recorded byte p_rec,
      target  = lut2d(REFERENCE CAL's DescDemandPedal{D,R}, p_rec, y)   y = DemandSpeedIndex (the last DLCM tick's)
      pedal   = the smallest 0x210 byte b >= 1 whose PedalInternal (40 b + 20, as the sink decodes it) gives
                lut2d(RUN CAL's map, pedal, y) >= target; the top byte if none does (saturated).
    The run CAL's column at y need not be monotone (R13P10 below 12.4 mph: the creep at pedal 0 falls to 0 at the zero
    point, then rises; blending two speed columns adds 0.1 Nm wiggles), so the search is exact for any shape: at fixed
    y lut2d is linear in pedal within each pedal-knot cell, so the cells are walked in order and the first byte reaching
    the target is taken (the cell's first byte if it already does, else a bisection inside the first cell whose last
    byte does).  A pressed foot is never turned into foot-off (byte >= 1; PedalInternal also feeds the creep and other
    blocks).
    The foot stays off (p_rec == 0 delivers 0); outside D / R (GearCode, GearCode2 as TrqRawDemandWriter selects the map)
    the recorded pedal passes through.  With the brake on the pedal map is not read, so only brake-off driving changes.
    Where the run CAL's map equals the reference's (the reference CAL itself; an unchanged R map) the recorded pedal
    passes through untouched.  stats: deliveries remapped / passed (foot off, not D/R) / same_map / saturated /
    min_press, and over_max = the largest (achieved - target) request on a remapped, unsaturated delivery (0.1 Nm): the
    byte grid's step, a check on the inverse.  rec: every delivery's (t_us, recorded PedalInternal), so a scorer can
    time from the RECORDED foot, the same instant for every CAL (result "pedal_rec")."""
    MAPS = {"D": "DescDemandPedalD", "R": "DescDemandPedalR"}
    TOP = 250

    def __init__(self, ctl, ref_cal):
        self.ref_cal = ref_cal
        ref = Image(ref_cal)
        self.ref = {g: ref.table2d(ctl.sym.addr(n)) for g, n in self.MAPS.items()}
        self.run_ = {g: ctl.img.table2d(ctl.sym.addr(n)) for g, n in self.MAPS.items()}
        self.same = {g: [list(a) for a in self.ref[g]] == [list(a) for a in self.run_[g]] for g in self.MAPS}
        V = ctl.ram.var
        self.ped, self.y, self.g1, self.g2 = V("PedalInternal"), V("DemandSpeedIndex"), V("GearCode"), V("GearCode2")
        k = lambda n: ctl.img.read(*ctl.sym.var(n))
        self.D, self.R = k("ProgGearCodeD"), k("ProgGearCodeR")
        self.orig = ctl._s_0x210_ThottlePedalPos
        self.stats = dict(remapped=0, passed=0, same_map=0, saturated=0, min_press=0, over_max=0)
        self.rec = []

    @staticmethod
    def pin(b):
        return 0 if b <= 0 else 40 * b + 20

    def sink(self, t_us, pct):
        self.orig(t_us, pct)
        p_rec = self.ped.get()
        self.rec.append((t_us, p_rec))
        g1, g2 = self.g1.get(), self.g2.get()
        g = "D" if g1 == self.D else ("R" if g1 == self.R and g2 == self.R else None)
        if p_rec == 0 or g is None:
            self.stats["passed"] += 1
            return
        if self.same[g]:
            self.stats["same_map"] += 1
            return
        y = ld_h(self.y.get())
        target = lut2d(*self.ref[g], ld_hu(p_rec), y)
        tab = self.run_[g]
        f = lambda b: lut2d(*tab, self.pin(b), y)
        X = [int(v) & 0xFFFF for v in tab[0]]
        b = None
        for i in range(len(X) - 1):                            # bytes whose PedalInternal lies in [X[i], X[i+1]]
            lo, hi = max(1, -(-(X[i] - 20) // 40)), min(self.TOP, (X[i + 1] - 20) // 40)
            if lo > hi:
                continue
            if f(lo) >= target:
                b = lo
                break
            if f(hi) >= target:                                # linear, rising in this cell: bisect
                while lo < hi:
                    mid = (lo + hi) // 2
                    if f(mid) >= target:
                        hi = mid
                    else:
                        lo = mid + 1
                b = lo
                self.stats["over_max"] = max(self.stats["over_max"], f(b) - target)
                break
        if b is None:
            b = self.TOP
            if f(b) < target:
                self.stats["saturated"] += 1
        if b == 1:
            self.stats["min_press"] += 1
        self.stats["remapped"] += 1
        self.ped.set(self.pin(b))


def _polled(t, v, polls, offset_us, phase_us):
    """(delivery instants, values) of a polled series: ComSchedule.deliver, frames no poll follows dropped, and only
    the latest frame per delivery instant kept (the mailbox holds the latest frame), as io.inputs.Replay does."""
    due = ComSchedule.deliver(t, polls, offset_us, phase_us)
    ok = due >= 0
    due, v = due[ok], np.asarray(v)[ok]
    last = np.ones(len(due), bool)
    last[:-1] = due[1:] != due[:-1]
    return due[last], v[last]


def _feed(clock, ctl, rows, sig, prov, shift, t0, poll=None):
    """io.inputs.Replay's delivery of one recorded series: warm start with the latest value at or before t0, then every
    later frame at t + shift.  poll = (polls, offset_us, phase_us): delivered on the COM RX poll instead."""
    t, v = rows
    if not len(t):
        raise NotRunnable("feed %s has no frames in the episode (an empty feed is not a negative)" % sig)
    sink = ctl.sink(sig, prov)
    if poll is not None:
        t, v = _polled(t, v, *poll)
        if not len(t):
            raise NotRunnable("feed %s: no frame is followed by a poll" % sig)
    due = t + shift
    k = int(np.searchsorted(due, t0, "right"))
    if not k:
        raise NotRunnable("feed %s has no value due at or before the clock start (no warm start)" % sig)
    sink(t0, v[k - 1])
    clock.feed(list(zip(t[k:].tolist(), v[k:].tolist())), sink, shift_us=shift)


class Cosim:
    def __init__(self, ep, cal=None, preset="current", bounds="computed", speed_delay_us=None,
                 speed="plant", road_mode="meas_blend", t_end_us=None, plant=None, assumptions=None, no_quiet="refuse", trace_extra=(),
                 friction="p7", grade_fallback=False, rx_timing="poll", speed_arrival_us=SPEED_ARRIVAL_US, body_hold_z=BODY_HOLD_Z,
                 stop_grade=None, stop_grade_ramp_s=None, pedal_remap=None):
        """ep: an episodes.load() episode.  cal: CAL path or name (default: the episode cohort's on-car image).
        speed: "plant" (closed loop from the handover), "0x1C0" (recorded 0x1C0 through the same delayed path for the
        whole run: open loop, no plant) or "0x308" (io.inputs' reversed 0x308: open loop, no plant).
        no_quiet: what to do with an episode that has no quiet point -- "refuse" (default; user 2026-10-10: left out for
        now) or "cold": a COLD START at the store span's start (t_shift - PRE - HIST), mid-manoeuvre, which ecm2_gate
        measured false-tripping ~0.5 s in; header() says so.
        friction: the RoadLoad brake friction, "p7" (default) or "measured" (plant/road.py, regen13_model_screens.md
        step 2).  grade_fallback: RoadLoad's opt-in grade fallback for episodes braked throughout (same step).
        body_hold_z: BodyPlant z_hold, the body spring's damping ratio while the wheel is held (plant/vehicle.py;
        regen13_model_screens.md step 3: braked stops settle as the car's).  DEFAULT BODY_HOLD_Z (1.0) since 2026-10-17;
        None = off (the bare body, bit for bit as before).  With plant= it must be None (ValueError otherwise: build the
        hold into the plant you pass).
        stop_grade: OPT-IN (default None = off) RoadLoad stop_grade, "parked": the slope ramps to the one the car's 0x330
        reads parked after the stop (plant/road.py; regen13_model_screens.md step 3).  A stop it cannot measure is
        NotRunnable.  stop_grade_ramp_s: its ramp length (None = road.STOP_GRADE_RAMP_S); only with stop_grade.
        pedal_remap: OPT-IN (default None = the recorded pedal) a reference CAL path: PedalRemap, an adapted driver.
        rx_timing: "poll" (default; see the module docstring) or "arrival".  speed_delay_us belongs to "arrival" only:
        with "poll" it must be None (the poll schedule times the speed; passing a delay is refused, not ignored)."""
        if stop_grade_ramp_s is not None and stop_grade is None:
            raise ValueError("stop_grade_ramp_s without stop_grade")
        if stop_grade is not None and speed != "plant":
            raise ValueError("stop_grade shapes the plant's road load; speed=%r runs no plant" % speed)
        if rx_timing not in ("poll", "arrival"):
            raise ValueError(rx_timing)
        if rx_timing == "poll" and speed_delay_us is not None:
            raise ValueError("speed_delay_us is the rx_timing='arrival' bracket; rx_timing='poll' times the speed "
                             "path by the COM poll (pass speed_delay_us=None)")
        if rx_timing == "arrival" and speed_delay_us is None:
            speed_delay_us = SPEED_DELAY_BRACKET_US[0]
        self.rx_timing = rx_timing
        self.speed_arrival_us = int(speed_arrival_us)          # rx_timing="poll": 0x20C after the logged 0x1C0
        if speed not in ("plant", "0x1C0", "0x308"):
            raise ValueError(speed)
        if no_quiet not in ("refuse", "cold"):
            raise ValueError(no_quiet)
        self.cold = ep.get("quiet_us") is None
        if self.cold and no_quiet == "refuse":
            raise NotRunnable("no quiet point: " + str(ep.get("no_quiet")))
        self.ep, self.speed_mode = ep, speed
        self.t_shift = int(ep["t_us"])
        self.t0 = int(ep["span_us"][0]) if self.cold else int(ep["quiet_us"])
        self.t_end = int(t_end_us if t_end_us is not None else self.t_shift + E.POST_US)
        self.g0 = self.t_shift - E.PRE_US                              # episode grid origin (RoadLoad, scoring)
        self.cal = cal if cal is not None else E.COHORT_CAL[ep["cohort"]]
        self.ctl = DlcmController(self.cal, assumptions=assumptions, bounds=bounds)
        self.remap = None
        if pedal_remap is not None:
            self.remap = PedalRemap(self.ctl, pedal_remap)
            self.ctl._s_0x210_ThottlePedalPos = self.remap.sink          # ctl.sink() looks the sink up by name
        self.clock = Clock(self.t0)
        self.ctl.install(self.clock, phase_us=int(ep["phase_us"]))
        S = ep["series"]
        self.phase_us = int(ep["phase_us"])
        self.com, self._polls, self.poll_anchor = None, {}, {}
        if rx_timing == "poll":
            self.com = ComSchedule(self.ctl.ctx.img, self.ctl.ctx.sym)
        feeds = [f + ("D",) for f in INP.FEEDS] + (list(INP.COMPUTED_BOUND_FEEDS) if bounds == "computed" else [])
        self.open_loop_inputs = []
        for sig, fid, dbcsig, prov, shift, filt, dbc in feeds:
            if sig == "0x308.InputShaftSpeed" and speed != "0x308":
                continue
            if filt is not None:
                raise NotImplementedError("feed filter %r" % filt)
            poll = None
            if self.com is not None and Provenance(prov) in INP.POLLED:
                poll = (self._polls_of(fid, S), ARRIVAL_OFFSET_US.get(fid, 0), self.phase_us)
            _feed(self.clock, self.ctl, S[sig], sig, prov, shift, self.t0, poll)
            self.open_loop_inputs.append((sig, Provenance(prov).value, shift if poll is None else "poll"))
        self.speed_delay_us = None if speed_delay_us is None else int(speed_delay_us)
        rt, rv = S["0x1C0.Motor_Speed"]
        if speed == "0x308":
            self.h = None
        else:
            if speed == "plant":
                j = int(np.searchsorted(rt, self.g0, "left"))
                if j >= len(rt) or rt[j] >= self.t_shift:
                    raise NotRunnable("no 0x1C0 frame in [t_shift - PRE, t_shift)")
                self.h = int(rt[j])
                last = self.h
            else:
                self.h, last = None, self.t_end
            m = (rt <= last)
            if self.com is not None:                                   # on 0x20C's poll (module docstring)
                due, val = _polled(rt[m], rv[m], self._polls_of(SPEED_RECORD, S), self.speed_arrival_us, self.phase_us)
                sink_rec = self.ctl.sink("0x1C0.Motor_Speed", Provenance.SUBSTITUTE)
                k = int(np.searchsorted(due, self.t0, "right"))
                if not k:
                    raise NotRunnable("0x1C0.Motor_Speed has no value delivered at or before the clock start")
                sink_rec(self.t0, val[k - 1])
                self.clock.feed(list(zip(due[k:].tolist(), val[k:].tolist())), sink_rec)
            else:
                sink_rec = self.ctl.sink("0x1C0.Motor_Speed", Provenance.SUBSTITUTE, delay_us=self.speed_delay_us)
                d = self.speed_delay_us
                k = int(np.searchsorted(rt[m] + d, self.t0, "right"))      # warm start as every other feed, the delay
                if not k:                                                  # playing the part of the shift: the latest
                    raise NotRunnable("0x1C0.Motor_Speed has no value due at or before the clock start (no warm start)")
                sink_rec(self.t0 - d, rv[m][k - 1])                        # value due at or before t0 is in the buffer AT t0
                self.clock.feed(list(zip(rt[m][k:].tolist(), rv[m][k:].tolist())), sink_rec)
        self.trace = []
        self.trace_extra = tuple(trace_extra)                         # extra RAM variables, traced per tick (r["extra"])
        vs = [self.ctl.ram.var(n) for n in TRACE + self.trace_extra]
        self.clock.every(10000, lambda t: self.trace.append((t,) + tuple(v.get() for v in vs)),
                         phase_us=int(ep["phase_us"]), order=ORDER_TX, name="trace")
        self.road = None
        if speed == "plant":
            self._plant_side(preset, plant, road_mode, rt, rv, friction, grade_fallback, body_hold_z, stop_grade,
                             stop_grade_ramp_s)

    def _polls_of(self, fid, S):
        """True poll instants of fid's COM RX record over the episode, anchored on the first ANCHOR_SERIES id whose
        TX period fits the divider and that has frames in the episode (io/inputs takes the first logged one)."""
        n = self.com.rx_divider(fid)
        if n not in self._polls:
            for _, aid in self.com.anchors(n):
                name = ANCHOR_SERIES.get(aid)
                if name is None or name not in S or not len(S[name][0]):
                    continue
                at = np.unique(S[name][0])
                self._polls[n] = self.com.poll_instants(n, aid, at, self.phase_us, int(self.ep["span_us"][0]) - E.MARGIN_US,
                                                        self.t_end)
                self.poll_anchor[n] = aid
                break
            else:
                raise NotRunnable("no stored DLCM TX frames anchor the divider-%d COM poll of 0x%03X" % (n, fid))
        return self._polls[n]

    # ------------------------------------------------------------------ plant side
    def _plant_side(self, preset, plant, road_mode, rt, rv, friction="p7", grade_fallback=False, body_hold_z=None,
                    stop_grade=None, stop_grade_ramp_s=None):
        g = E.grid(self.ep)
        if g["brk_sw"] is None:
            raise NotRunnable("no 0x200 SubFrameID-0 BrakeSW (RoadLoad's brake-on mask)")
        self.road = RoadLoad(road_mode, friction=friction, grade_fallback=grade_fallback, stop_grade=stop_grade,
                             **({} if stop_grade_ramp_s is None else dict(stop_grade_ramp_s=stop_grade_ramp_s)))
        try:
            self.road.bind(g)
        except ValueError as x:
            raise NotRunnable("road: %s" % x)
        if plant is not None and body_hold_z is not None:
            raise ValueError("body_hold_z applies to the preset plant (default %s); with plant= pass body_hold_z=None "
                             "and build the hold into the plant" % BODY_HOLD_Z)
        self.plant = plant if plant is not None else presets.make(
            preset, body=None if body_hold_z is None else dict(z_hold=body_hold_z))
        self.preset = preset if plant is None else type(plant).__name__
        dt = self.plant.dt_us
        self.act = McmDelay(dt_us=dt)
        self.spd = EdgeSpeedSensor(dt_us=dt)
        self.acs = AccelSensor(dt_us=dt)
        for o in (self.act, self.spd, self.acs):
            if o.dt_us != dt:
                raise ValueError("dt_us mismatch")
        self.rpm_h = float(rv[np.searchsorted(rt, self.h)])            # recorded 0x1C0 at h (a frame instant)
        if self.com is not None:
            fn = self.ctl.sink("0x1C0.Motor_Speed", Provenance.PLANT)
            polls = self._polls_of(SPEED_RECORD, self.ep["series"])

            def sink_plant(t_us, v):                                   # on 0x20C's poll; FIFO ties keep the latest
                d = int(ComSchedule.deliver([t_us], polls, self.speed_arrival_us, self.phase_us)[0])
                if d >= 0:
                    self.clock.at(d, lambda now, _v=v: fn(now, _v), ORDER_RX)
            self.sink_plant = sink_plant
        else:
            self.sink_plant = self.ctl.sink("0x1C0.Motor_Speed", Provenance.PLANT, delay_us=self.speed_delay_us)
        self.T, self.out, self.started = 0.0, None, False
        self.rpm_ms, self.acc50, self.spd_frames = [], [], []
        t_act = self.h - self.act.n * dt                              # the MCM queue fills with the model's commands
        self.clock.every(dt, self._act, phase_us=t_act % dt, order=ORDER_ACT, name="McmDelay", start_us=max(self.t0, t_act))
        self.clock.every(dt, self._plant, phase_us=self.h % dt, order=ORDER_PLANT, name="plant", start_us=self.h)
        self.clock.every(dt, self._sense, phase_us=self.h % dt, order=ORDER_SENSOR, name="sensors", start_us=self.h)

    def _act(self, t):
        self.T = self.act.step(self.ctl.command_counts(), self.ctl.gear418())

    def _plant(self, t):
        if not self.started:
            self.out = self.plant.reset(self.rpm_h * 2 * math.pi / 60, T0=self.T)
            self.spd.reset(self.rpm_h)
            self.acs.reset(0.0)
            self.started = True
        self.out = self.plant.step(self.T, self.road.at(t - self.g0))

    def _sense(self, t):
        dt = self.plant.dt_us
        v = self.spd.step(self.out)
        if v is not None:
            self.sink_plant(t + dt, v)                                 # a sample describes the END of the step
            self.spd_frames.append((t + dt, v))
        a = self.acs.step(self.out)
        if a is not None:
            self.acc50.append((t + dt, a))
        self.rpm_ms.append((t + dt, self.out["rpm"], self.out["shaft_Nm"], self.T))   # T: applied over [t, t + dt)

    # ------------------------------------------------------------------ run / results
    def run(self):
        self.clock.run_until(self.t_end)
        tr = np.array(self.trace, np.int64)
        r = dict(t_tick=tr[:, 0], mcm=tr[:, 1], pub212=tr[:, 2] - 2000, gear418=tr[:, 3], speed_raw=tr[:, 4],
                 resets=list(self.ctl.resets), halted=self.ctl.halted, h=self.h, t0=self.t0, g0=self.g0,
                 t_shift=self.t_shift, extra={n: tr[:, 5 + k] for k, n in enumerate(self.trace_extra)},
                 pedal_remap=None if self.remap is None else dict(self.remap.stats),
                 pedal_rec=None if self.remap is None else np.array(self.remap.rec, np.int64).reshape(-1, 2))
        if self.road is not None:
            a = np.array(self.acc50)
            r.update(t50=a[:, 0].astype(np.int64), acc50=a[:, 1])
            m = np.array(self.rpm_ms)
            r.update(t_ms=m[:, 0].astype(np.int64), rpm=m[:, 1], shaft_Nm=m[:, 2], applied_Nm=m[:, 3])   # motor frame, Nm
        return r

    def header(self):
        lines = ["cosim (codasim.cosim, plan codasim_full_model.md step 4)",
                 "  episode %s t_shift %.3f s %s->%s cohort %s; clock from %s %.3f s (lead-in %.2f s)"
                 % (self.ep["stem"], self.t_shift / 1e6, self.ep["frm"], self.ep["to"], self.ep["cohort"],
                    "a COLD START mid-manoeuvre (no quiet point: %s) at" % self.ep.get("no_quiet") if self.cold
                    else "the quiet point", self.t0 / 1e6, ((self.h or self.t_end) - self.t0) / 1e6),
                 "  speed: %s; %s"
                 % ({"plant": "recorded 0x1C0 (SUBSTITUTE for 0x20C) until the handover at %s, then the plant's "
                              "EdgeSpeedSensor (PLANT)" % (None if self.h is None else "%.4f s" % (self.h / 1e6)),
                     "0x1C0": "recorded 0x1C0 (SUBSTITUTE for 0x20C), whole run, open loop",
                     "0x308": "reversed 0x308 (io.inputs), whole run, open loop"}[self.speed_mode],
                    ("0x1C0.Motor_Speed path delay %d us (declared bracket %s us, not fitted)"
                     % (self.speed_delay_us, SPEED_DELAY_BRACKET_US)) if self.com is None else
                    ("0x1C0.Motor_Speed on the 0x%03X COM poll, arrival +%d us%s" % (SPEED_RECORD, self.speed_arrival_us,
                     " (fitted default)" if self.speed_arrival_us == SPEED_ARRIVAL_US else " (NOT the fitted default %d)" % SPEED_ARRIVAL_US))),
                 "  receive timing: %s" % ("arrival (feeds at their frame instants)" if self.com is None else
                                           "COM RX poll (io/comsched.py), anchors %s"
                                           % ", ".join("div %d <- 0x%03X" % kv for kv in sorted(self.poll_anchor.items()))),
                 "  OPEN LOOP WITH RESPECT TO THE PLANT (recorded through the closed loop): "
                 + ", ".join("%s [%s, %s]" % (sg, pv, "COM poll" if sh == "poll" else "shift %d us" % sh)
                             for sg, pv, sh in self.open_loop_inputs)]
        if self.road is not None:
            lines += ["  plant %s%s (dt %d us); %s %s, causal %s; McmDelay %d us x %.3f Nm/count, gear = model 0x418 "
                      "(Pub418Prnd); EdgeSpeedSensor, AccelSensor"
                      % (self.preset, "" if getattr(self.plant, "z_hold", None) is None else
                         " +body z_hold %.2f (%s)" % (self.plant.z_hold, "DEFAULT since 2026-10-17" if self.plant.z_hold == BODY_HOLD_Z
                                                       else "NOT the default %s" % BODY_HOLD_Z), self.plant.dt_us, self.road.name, self.road.provenance.value, self.road.causal,
                         self.act.n * self.act.dt_us, self.act.delivered_Nm_per_count)]
        if self.remap is not None:
            lines += ["  PEDAL REMAP (OPT-IN adapted driver, PedalRemap): the recorded 0x210 pedal -> the request %s's "
                      "pedal map gives at DemandSpeedIndex -> the smallest 0x210 byte giving that request on this CAL; "
                      "foot-off and non-D/R pass through" % self.remap.ref_cal]
        lines += [self.ctl.header(), self.clock.describe()]
        return "\n".join(lines)


def run(ep, **kw):
    """(result dict, header) for one episode; raises NotRunnable with the reason."""
    c = Cosim(ep, **kw)
    return c.run(), c.header()
