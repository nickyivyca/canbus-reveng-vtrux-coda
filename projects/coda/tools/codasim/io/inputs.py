"""Play a capture into a Controller's sinks on the clock (plan R4/R5).

Each FEED is one bus signal routed to the sink of the same name, with its
provenance and a declared time shift. Frames are decoded with cantools against the
D CAN DBC (AGENTS.md: never hand-roll bits for a DBC signal), on the bus identified
by content (logreplay), and delivered at t_frame + shift_us.

Timing parameters are DECLARED, never silent:
  phase     each tick runs ALIGN_US (5 ms) before the TX burst it publishes (aligned on
            0x308, which is in every burst; 0x212 follows 0x308 by ~0.6 ms).
  PUBLISHED frames (REVERSED / REPLAYED_OUTPUT: 0x210, 0x418, 0x308, 0x312) carry the
            value the tick that SENT them used. So they are delivered PUBLISHED_SHIFT_US
            (-7.5 ms) early, i.e. 2.5 ms before that tick, +/-2.5 ms margin for jitter.
            Delivering them at frame time instead makes the model consume every reversed
            input one tick late; measured 2026-10-09 on coda_20261004_165539_T0 as a best
            fit at "+1 tick" (0x212 mean |err| 1.71 -> 0.70 Nm), now removed by construction.
  20 ms PUBLISHED frames (0x210, 0x418) skip every other tick, so one tick in two
            used a value no frame shows. DECLARED ESTIMATE: that tick takes the NEXT frame's
            value (TWENTY_MS_EXTRA_US = -10 ms more). Chosen over hold-previous by 0x212
            agreement on coda_20261004_165539_T0 (C4c): mean |err| 0.69 -> 0.43 Nm, p99
            10.2 -> 4.7 Nm. It cannot distinguish "the unseen tick is nearer the next value"
            from "0x210 is packed one tick stale"; both assign the same values.
  0x308     carries MotorSpeedSignedX2 of the sending tick, which TrqSpeedTask took from SpeedRaw
            AFTER tick member 0x8006F870 refreshed it from the 0x20C RX buffer in the same tick, so
            the plain published shift applies (worklog 6H.68, correcting 6H.67.1's -10 ms extra).
            The COM task polls 0x20C 5 ms before the tick that copies it (worklog 6H.74). 0x308 is a published
            value, so that timing is already inside the reversed frame.
  RECEIVED frames (0x208, 0x300, 0x200, 0x275, 0x276) and the SUBSTITUTE 0x1C0 words for 0x20B
            reach the tick on the firmware's COM RX poll schedule (io/comsched.py, worklog 6H.74; default
            rx_timing="poll"). The COM task polls each record every n x 5 ms (n from its RX record: 2 for
            the M-CAN frames, 4 for the ESC frames, 20 for 0x275 / 0x276), with the phase anchored on the
            logged TX bursts. A polled frame reaches the tick 10 ms after its poll; only the latest frame
            per poll counts. Arrivals are compared with the true (unrounded) polls and only the delivery
            is rounded onto the tick grid, because the logger and DLCM clocks drift (fixed 2026-10-14). Before 6H.74 these were delivered at arrival, so the first tick after arrival
            saw them: 10-15 ms early, and 0x208 at 100 Hz where the DLCM samples it at 50 Hz. That rule
            remains as rx_timing="arrival".
  BrakeSW   is REVERSED from 0x212 (Publish10ms copies BrakeSwitch 0xD0006831), exact, replacing
            the 0x200 BrakeSW feed (another module's view) used before 2026-10-09.
  shifts    per feed, default 0. The lash session's fitted GEAR_LEAD (2 ticks early on
            0x418 PRND) is NOT applied by default: GearStatus carries both gear codes
            and is expected to make it unnecessary -- that is a test, not an assumption.

    from codasim.io import inputs
    run = inputs.replay(capture, controller, t0_us, t1_us)
"""

import os

import cantools

from ..clock import Clock
from ..interfaces import Provenance

DBC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "CODA-D-CAN.dbc"))
ALIGN_US = 5000
PUBLISHED_SHIFT_US = -7500
TWENTY_MS_EXTRA_US = -10000

# (signal, frame id, DBC signal, provenance, shift_us, frame filter)
FEEDS = [
    ("0x210.ThottlePedalPos", 0x210, "ThottlePedalPos", Provenance.REVERSED,
     PUBLISHED_SHIFT_US + TWENTY_MS_EXTRA_US, None),
    ("0x418.GearStatus", 0x418, "GearStatus", Provenance.REVERSED,
     PUBLISHED_SHIFT_US + TWENTY_MS_EXTRA_US, None),
    ("0x308.InputShaftSpeed", 0x308, "InputShaftSpeed", Provenance.REVERSED,
     PUBLISHED_SHIFT_US, None),
    ("0x208.BrakePressure", 0x208, "BrakePressure", Provenance.RECEIVED, 0, None),
    ("0x208.BrakePressure_Valid", 0x208, "BrakePressure_Valid", Provenance.RECEIVED, 0, None),
    ("0x212.BrakeSW", 0x212, "BrakeSW", Provenance.REVERSED, PUBLISHED_SHIFT_US, None),
    ("0x300.ESP_BrakingTqLimit", 0x300, "ESP_BrakingTqLimit", Provenance.RECEIVED, 0, None),
    ("0x300.ESP_TractiveTqLimit", 0x300, "ESP_TractiveTqLimit", Provenance.RECEIVED, 0, None),
    ("0x300.ESP_TractiveTqLimit_Armed", 0x300, "ESP_TractiveTqLimit_Armed", Provenance.RECEIVED, 0, None),
    ("0x312.M_MIN", 0x312, "M_MIN", Provenance.REPLAYED_OUTPUT, PUBLISHED_SHIFT_US, None),
    ("0x312.M_MAX", 0x312, "M_MAX", Provenance.REPLAYED_OUTPUT, PUBLISHED_SHIFT_US, None),
]
RAW_SIGNALS = {"GearStatus", "BrakePressure", "ESP_BrakingTqLimit", "ESP_TractiveTqLimit"}   # sinks take the raw field

B_DBC = os.path.join(os.path.dirname(DBC), "CODA-B-CAN.dbc")
# Inputs of the COMPUTED bound chain (DlcmController(bounds="computed")); kept out of FEEDS, which the
# lash session's episode store is keyed on. (signal, frame id, DBC signal, provenance, shift_us, filter,
# dbc). Every one is delivered RAW (the firmware reads the bytes). Frames come from the D CAN channel:
# 0x275 / 0x276 are B CAN messages the gateway rebroadcasts frame for frame, and the DLCM sits on D.
BOUND_FEEDS = [
    ("0x275.BattSentDischargeLimit", 0x275, "BattSentDischargeLimit", Provenance.RECEIVED, 0, None, "B"),
    ("0x275.BattSentChargeLimit", 0x275, "BattSentChargeLimit", Provenance.RECEIVED, 0, None, "B"),
    ("0x276.PTC_PowerConsumption", 0x276, "PTC_PowerConsumption", Provenance.RECEIVED, 0, None, "B"),
    ("0x276.ACCM_PowerConsumption", 0x276, "ACCM_PowerConsumption", Provenance.RECEIVED, 0, None, "B"),
    ("0x200.SubFrameID", 0x200, "SubFrameID", Provenance.RECEIVED, 0, None, "D"),
]
# DECLARED SUBSTITUTE (user decision 2026-10-09, worklog 6H.69.5): the bound chain reads the M-CAN 0x20B
# words (B0..B1, B2..B3; 0x20B = AccurateFeedbacks_Elec, by elimination), which no log carries. 0x1C0
# HV_Current / HV_Voltage (same 0x7D80-offset encoding) stand in for them, raw, unshifted. That they
# carry the same values is NOT established.
SUBSTITUTE_20B_FEEDS = [
    ("0x1C0.HV_Voltage", 0x1C0, "HV_Voltage", Provenance.SUBSTITUTE, 0, None, "D"),
    ("0x1C0.HV_Current", 0x1C0, "HV_Current", Provenance.SUBSTITUTE, 0, None, "D"),
]
COMPUTED_BOUND_FEEDS = BOUND_FEEDS + SUBSTITUTE_20B_FEEDS


POLLED = (Provenance.RECEIVED, Provenance.SUBSTITUTE)      # feeds delivered on the COM RX poll schedule


class Replay:
    def __init__(self, capture, controller, t0_us, t1_us, feeds=FEEDS, bus="D", trace=(), extra=None,
                 rx_timing="poll"):
        """extra: 7-tuple feeds (..., dbc "D" | "B"), delivered raw. Default: COMPUTED_BOUND_FEEDS
        (BOUND_FEEDS + the 0x1C0 SUBSTITUTE for 0x20B) when the controller computes its bounds, else none.
        rx_timing: "poll" (default since 2026-10-14, worklog 6H.74): RECEIVED and SUBSTITUTE feeds reach the
        tick on the firmware's COM RX poll schedule (io/comsched.py); "arrival": the first tick after arrival
        (the rule before 6H.74, kept for comparison)."""
        if rx_timing not in ("poll", "arrival"):
            raise ValueError(rx_timing)
        self.rx_timing = rx_timing
        self.cap, self.ctl, self.t0, self.t1 = capture, controller, int(t0_us), int(t1_us)
        self.db = cantools.database.load_file(DBC, strict=False)
        self.dbs = {"D": self.db, "B": cantools.database.load_file(B_DBC, strict=False)}
        if extra is None:
            extra = COMPUTED_BOUND_FEEDS if getattr(controller, "bounds_mode", None) == "computed" else []
        self.clock = Clock(t0_us)
        self.trace_names = list(trace)
        self.trace = []                   # (t_us, *values) after each controller tick
        self.counts = {}
        spd = capture.frames(bus, 0x308)
        if not spd:
            raise ValueError("%s: no 0x308 on %s CAN; cannot align the task phase" % (capture.stem, bus))
        phase = (spd[0][0] - ALIGN_US) % 10000
        controller.install(self.clock, phase_us=phase)
        self.phase = phase
        if self.trace_names:
            vs = [controller.ram.var(n) for n in self.trace_names]
            from ..clock import ORDER_TX
            self.clock.every(10000, lambda t: self.trace.append((t,) + tuple(v.get() for v in vs)),
                             phase_us=phase, order=ORDER_TX, name="trace")
        allf = [f + (None,) for f in feeds] + list(extra)
        self.com = None
        if rx_timing == "poll":
            from .comsched import ComSchedule, ARRIVAL_OFFSET_US
            self.com, polls = ComSchedule(controller.ctx.img, controller.ctx.sym), {}
        self.poll_anchor = {}
        for sig, fid, dbcsig, prov, shift, filt, dbc in allf:
            rows = capture.frames(bus, fid)
            if filt == "subframe0":
                rows = [r for r in rows if r[1][0] == 0x00]
            if dbc is None:
                rows = [(t, self._dec(fid, d, dbcsig)) for t, d in rows]
            else:
                rows = [(t, self._dec_raw(self.dbs[dbc], fid, d, dbcsig)) for t, d in rows]
            rows = [r for r in rows if r[1] is not None]
            if not rows:
                raise ValueError("%s: feed %s has no frames -- an empty feed is not a negative (Mode 1)"
                                 % (capture.stem, sig))
            if self.com is not None and prov in POLLED:
                if fid not in polls:
                    polls[fid] = self._polls(capture, bus, fid, phase)
                due = self.com.deliver([t for t, _ in rows], polls[fid], ARRIVAL_OFFSET_US.get(fid, 0), phase)
                rows = [(int(d), v) for d, (_, v) in zip(due, rows) if d >= 0]
                rows = [r for i, r in enumerate(rows) if i + 1 == len(rows) or rows[i + 1][0] != r[0]]
            self.counts[sig] = len(rows)
            sink = controller.sink(sig, prov)
            self.shifts = getattr(self, "shifts", {})
            self.shifts[sig] = shift
            first_t = rows[0][0]
            prior = [r for r in rows if r[0] + shift <= self.t0]
            if prior:                              # warm start: latest value before t0
                sink(self.t0, prior[-1][1])
            self.clock.feed([r for r in rows if r[0] + shift > self.t0], sink, shift_us=shift)

    def _polls(self, capture, bus, fid, phase):
        """Poll instants of fid's COM RX record, anchored on the first logged TX record whose period fits."""
        n = self.com.rx_divider(fid)
        lo, hi = capture.span_us()
        for _, aid in self.com.anchors(n):
            at = [t for t, _ in capture.frames(bus, aid)]
            if at:
                self.poll_anchor[fid] = (n, aid)
                return self.com.poll_instants(n, aid, at, phase, lo, hi)
        raise ValueError("%s: no logged TX burst fixes the phase of 0x%03X's divider-%d poll (Mode 1)"
                         % (capture.stem, fid, n))

    def _dec(self, fid, data, sig):
        try:
            d = self.db.decode_message(fid, data, scaling=sig not in RAW_SIGNALS,
                                       decode_choices=False)
        except Exception:
            return None
        return d.get(sig)

    @staticmethod
    def _dec_raw(db, fid, data, sig):
        try:
            return db.decode_message(fid, data, scaling=False, decode_choices=False).get(sig)
        except Exception:
            return None

    def run(self):
        self.clock.run_until(self.t1)
        return self


def replay(capture, controller, t0_us, t1_us, **kw):
    return Replay(capture, controller, t0_us, t1_us, **kw).run()
