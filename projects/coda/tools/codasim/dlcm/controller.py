"""DlcmController: the DLCM torque task as a codasim Controller (interfaces.Controller).

One `step()` is one call of DlcmTorqueTask10ms (entry 0x8007C0EC; 0x8007C2C6 and 0x8007C33A are
spurious ENTRY labels mid-body, worklog 6H.73), in its order:

    ComRxCopy               0x8008008C   called at 0x8007C29A: every received PDU buffer is refreshed here from
                                         the COM shadow, once per tick, before any member and before ECM2. The
                                         COM task fills the shadow only when it polls a record (io/comsched.py,
                                         worklog 6H.74). Modelled by the sinks, which write the buffers when
                                         io/inputs delivers a frame on that poll schedule (ORDER_RX, ahead of
                                         the tick): a frame reaches PROG and ECM2 on the same tick.
    0x8006E704, 0x8006EB8C               NOT PORTED
    SpeedRxCopy             0x8006F870   only the 0x20C (SpeedRaw) and 0x20B word copies (dlcm/speedrx.py)
    0x8007426C                           NOT PORTED
    0x8006ED2C  Brake208Copy (0x208 -> BrakeAnalog / BrakeAnalogValid, always); Can300DecodeProg,
                Can200B0Bit2 (computed bounds only) (dlcm/rxdecode.py); rest NOT PORTED
    0x80077BCC                           NOT PORTED
    TrqSpeedTask            0x80075930   ported (plausibility latch not)
    0x80072674  BmsHvacCopy (0x275/0x276 copies; computed bounds only), rest NOT PORTED
    0x80070CA0, 0x8006F17C               NOT PORTED (0x8006F17C: RunState machine, A2)
    gear task 0x80071608 -> GearLatchAndSpeedFlags 0x800722FE   (state machine NOT PORTED;
                                         gear codes are a reversed input from 0x418 GearStatus)
    ActiveSpeedDamper       0x800764F0/F6  (+ tail 0x800767DA DamperAbsPeakHoldUpdate; computed bounds only)
    BoundsTask              0x8007689C   bounds="computed" (default): the 7 bound-source functions
                                         (dlcm/boundsrc.py), M-CAN 0x20B words from 0x1C0 (SUBSTITUTE);
                                         bounds="replay": AB4/ACA from 0x312, AA6/AC0 assumed (A3)
    DemandTask              0x8007766C
    Creep                   0x80075FF8
    TrqRequestSum           0x80075CF8   (+ limiter 0x80075DFA, 7a 0x80075F56)
    AccelLimiter            0x800750E8   (+ 0x80075394, 0x8007566E, 0x80075896; plan step 5b, dlcm/accel.py)
    FinalSum                0x80075D52
    0x800779D8                           NOT PORTED
    TickMember800704AC      0x800704AC   (RunState gate on the MCM command; partly ported)
    Publish10ms             0x80074780   (mirror words + 0xD00069D0; COM packing 0x80080C14 not ported)
    Ecm2Task                0x800463B8   (called at 0x8007C4DA; reason-12 chain and reason 15 ported, ecm2/task.py)

A predicted ECM2 reset (one debounced reason flag while the occurrence count < 7) is recorded in
`resets` and HALTS the controller: the user's rule (2026-10-09) is that a reset on a candidate
profile rejects it, so recovery is not modelled.

Everything the ported blocks read that no block computes is either fed by a sink
(see SINKS) or held by a declared assumption (ASSUMPTIONS). Anything else they
read stays zero and is listed by header() as UNSOURCED -- that list is the
model's own statement of what it does not know.
"""

from ..clock import ORDER_RX, ORDER_TASK
from ..image import Image
from ..interfaces import Provenance
from ..ram import Ram
from ..symbols import Symbols
from .base import Ctx
from .bounds import BoundsTask
from .boundsrc import BoundSources
from .rxdecode import BmsHvacCopy, Brake208Copy, Can200B0Bit2, Can300DecodeProg
from .creep import Creep
from .damper import ActiveSpeedDamper, DamperAbsPeakHoldUpdate
from .demand import DemandTask
from .direction import GearLatchAndSpeedFlags
from .accel import AccelLimiter
from .final import FinalSum
from .gate import TickMember800704AC
from ..ecm2.task import Ecm2Task
from ..fixedpoint import u16
from .publish import Publish10ms
from .request import TrqRequestSum
from .speed import TrqSpeedTask
from .speedrx import SpeedRxCopy

PERIOD_US = 10000

NOT_PORTED = [
    "0x8006E704, 0x8006EB8C, 0x8007426C, 0x8006ED2C, 0x80077BCC, 0x80072674, 0x80070CA0, 0x800779D8, 0x8007809C"
    " (tick members, roles unknown); 0x8006F870 beyond the 0x20C / 0x20B word copies; 0x8006F17C (RunState machine: A2);"
    " 0x800704AC beyond its gate",
    "gear state machine 0x8007162E / 0x8007214C / 0x800719B8 (gear codes are a reversed input)",
    "TrqSpeedFilter speed plausibility latch (fault 0x26)",
    "ECM2 reasons 1-9, 13, 14 and 16 (held 0; reason 15 ported 2026-10-27 with a0-0x967 held 0, ecm2/reason15.py), the 0x20C E2E checks, the 0x300 checks (c63) and fault latch (c65),"
    " ECM2's pedal ADC and arbitration (ce4 substituted), c11's selector machine (substituted), the shut-off stage",
]

# Model inputs that stand in for an unported firmware path. Each is copied every tick before ECM2
# runs and printed by header(); none is a firmware fact.
SUBSTITUTES = [
    ("Ecm2Pedal_ce4", "PedalInternal",
     "ECM2 pedal = PROG pedal. Firmware: ECM2's own ADC channels (0x80046484, 0x800476E2), same 0.01 % unit"),
]

# name -> (value, why). Each is an input the model does not source; header() prints them.
ASSUMPTIONS = {
    "RunState": (5, "A2: torque path in its active run state (PROG 0x80043355 = 5); writer not in decoded code"),
    "DemandEnable": (1, "A2: 0xD0006938 set; writer 0x80072104 not ported"),
    "AppCh1Digital": (1, "no APP loss: pedal channel 1 digital input healthy (writer FUN_8006E734 not ported)"),
    "AppCh2Digital": (1, "no APP loss: pedal channel 2 digital input healthy (writer FUN_8006E828 not ported)"),
    "DamperBrakeGate": (0, "A5: 0xD000682E clear; writer 0x8006ED86 = 0x208 B0 bit 6 (ABS brake event) && 0x208 fresh"
                           " (6H.73), not ported: the ABS event is not fed (0 in 650,000+ frames of six sessions)"),
    "BoundSrcAA6": (3000, "A3: final clamp source; bound chain not run (bounds=\"replay\")"),
    "BoundSrcAC0": (3000, "A3: final clamp source; bound chain not run (bounds=\"replay\")"),
    "Can370B0Field64": (1, "0x370 B0[6:4] (not in the DBC; writer task 0x8007C2C6 not ported): measured 1 on every frame of the 2026-10-04 drives"),
    "SpeedValid": (1, "A1: speed valid; 0x308 replay carries no validity"),
    "Ecm2PedalFault_cb5": (0, "ECM2 pedal-fault latch clear (0x80047B64 not ported)"),
    "Ecm2Can300Valid_c63": (1, "0x300 fresh/parity/alive (checks not ported); 0x300 is logged at 100 Hz"),
    "Ecm2Can300Lost_c65": (0, "0x300 fault latch clear (FUN_800488C2 partly traced)"),
    "Ecm2Speed20CCheckA_8ab": (1, "0x20C E2E/alive check 0x8005976A passes (not ported; 0x20C not logged)"),
    "Ecm2Speed20CCheckB_8ad": (1, "0x20C E2E/alive check 0x800598CA passes (not ported)"),
    "Can20CTimeout": (0, "0x20C not timed out (0xD000519E; role hypothesis)"),
    "Can208Timeout": (0, "0x208 not timed out; it is logged on rate (worklog 6H.56)"),
}

# Model state whose power-on zero is the firmware's own initial value, not a missing input:
# they are written by a ported block, just not on every tick. Excluded from UNSOURCED.
# Held only when the bound chain is COMPUTED (bounds="computed"): inputs of the seven bound-source
# functions that no log carries. Each is the healthy / no-limiting value; see dlcm/boundsrc.py.
ASSUMPTIONS_BOUNDS = {
    "Can200Stale": (0, "0x200 fresh (timeout monitor FUN_80080A8C not ported); 0x200 is logged at 100 Hz per bus"),
    "Can300Stale": (0, "0x300 fresh (timeout monitor not ported); 0x300 is logged at 100 Hz"),
    "Can300ParityOk": (1, "0x300 B1 bit 7 parity check passes (COM copy FUN_8008008C, once per tick at 0x8007C29A; its checks not ported)"),
    "Can300ToggleLive": (1, "0x300 B4 bit 7 toggles (same COM snapshot)"),
    "Can200CounterLive": (1, "0x200 B1[5:2] rolling counter live (same COM snapshot)"),
    "Can20APduB0": (1, "M-CAN 0x20A B0 bit 0 set: TrqBoundDerateAndMin factor = 125/125 = 1.0. 0x20A is not logged;"
                       " 0x20D B1 = B2 = 250 with bit 0 clear gives the same factor"),
}

POWER_ON_ZERO = {
    "AppLossLimpHome": "latch state; AppLossLatch writes it only when it sets or clears",
    "Ecm2ReactionCount": "ECM2 occurrence count; restored at boot from reset-surviving RAM, 0 after a flash/clear (P3115 absent before the f7 drive, 6H.54.2)",
    "Mcm20BW1TrackLoState": "x100 tracker state; startup RAM init not traced (spec F: affects the first 2 s only)",
    "Mcm20BW1TrackHiState": "x100 tracker state; startup RAM init not traced",
}

GEAR_NIB_TO_CODE = {0xD: 5, 0xB: 10, 0x0: 20, 0x1: 40}
GEAR_ASCII_TO_CODE = {0x50: 5, 0x52: 10, 0x4E: 20, 0x44: 40}


class DlcmController:
    def __init__(self, cal="c4c", assumptions=None, bounds="computed"):
        """bounds="computed" (default since 2026-10-09, worklog 6H.70): the seven bound-source functions
        run (dlcm/boundsrc.py); 0x312 is then recorded for validation only (self.rec312) and drives
        nothing. They read the unlogged M-CAN 0x20B words, which io.inputs feeds from 0x1C0
        HV_Current / HV_Voltage as a declared SUBSTITUTE (user decision 2026-10-09, worklog 6H.69.5).
        bounds="replay": BoundSrcAB4/ACA from a replayed 0x312, AA6/AC0 assumed (A3)."""
        if bounds not in ("replay", "computed"):
            raise ValueError(bounds)
        self.bounds_mode = bounds
        self.img = Image(cal)
        self.sym = Symbols()
        self.ram = Ram(self.sym)
        self.ctx = Ctx(self.img, self.sym, self.ram)
        base = dict(ASSUMPTIONS)
        if bounds == "computed":
            del base["BoundSrcAA6"], base["BoundSrcAC0"]
            base.update(ASSUMPTIONS_BOUNDS)
        self.assumptions = dict(base, **(assumptions or {}))
        self.sinks = []                       # (signal, provenance, delay_us, note)
        self.rec312 = []                      # (t_us, field, raw) when bounds="computed"
        computed = bounds == "computed"
        self.blocks = [
            SpeedRxCopy(self.ctx),
        ] + ([Can300DecodeProg(self.ctx), Can200B0Bit2(self.ctx)] if computed else []) + [
            Brake208Copy(self.ctx),
            TrqSpeedTask(self.ctx),
        ] + ([BmsHvacCopy(self.ctx)] if computed else []) + [
            GearLatchAndSpeedFlags(self.ctx),
            ActiveSpeedDamper(self.ctx),
        ] + ([DamperAbsPeakHoldUpdate(self.ctx)] if computed else []) + [
            BoundsTask(self.ctx, BoundSources(self.ctx).run if computed else self._bound_sources),
            DemandTask(self.ctx),
            Creep(self.ctx),
            TrqRequestSum(self.ctx),
            AccelLimiter(self.ctx),
            FinalSum(self.ctx),
            TickMember800704AC(self.ctx),
            Publish10ms(self.ctx),
        ]
        self.subs = [(self.ram.var(d), self.ram.var(s)) for d, s, _ in SUBSTITUTES]
        self.ecm2 = Ecm2Task(self.ctx, self._ecm2_reset)
        self.resets = []                      # (t_us, reason code)
        self.halted = False
        self.now = None
        self._bounds = {"BoundSrcAB4": 3000, "BoundSrcACA": 3000}
        self._bounds_prov = ("COMPUTED (dlcm/boundsrc.py); 0x312 recorded for validation only" if computed
                             else "assumed +/-3000 (A3)")
        self.reset()

    # ------------------------------------------------------------ protocol
    def install(self, clock, phase_us=0):
        clock.every(PERIOD_US, self._tick, phase_us=phase_us, order=ORDER_TASK,
                    name="DlcmTorqueTask10ms")
        self.clock = clock

    def _tick(self, t_us):
        self.now = t_us
        self.step()

    def step(self):
        if self.halted:
            return
        for b in self.blocks:
            b.run()
        for d, s in self.subs:
            d.set(s.get())
        self.ecm2.run()

    def _ecm2_reset(self, code):
        """Ecm2ResetRequest 0x800569CC -> SoftwareReset(0xA2): the candidate is rejected; stop."""
        self.resets.append((self.now, code))
        self.halted = True

    def reset(self):
        self.ram.reset()
        self.resets, self.halted = [], False
        for n, (v, why) in self.assumptions.items():
            self.ram.assume(n, v, why)

    def command_counts(self):
        return self.ram.var("McmCommand").get()

    def gear418(self):
        return self.ram.var("Pub418Prnd").get()

    def sink(self, signal, provenance, delay_us=0):
        fn = getattr(self, "_s_" + signal.replace(".", "_"), None)
        if fn is None:
            raise KeyError("no sink for %r; known: %s" % (signal, sorted(
                a[3:].replace("_", ".", 1) for a in dir(self) if a.startswith("_s_"))))
        self.sinks.append((signal, Provenance(provenance), delay_us))
        if not delay_us:
            return fn

        def delayed(t_us, v):
            self.clock.at(t_us + delay_us, lambda now: fn(now, v), ORDER_RX)
        return delayed

    def header(self):
        lines = [self.img.describe(), "controller: DlcmTorqueTask10ms every %d us" % PERIOD_US]
        lines += ["  sink %-26s %-16s delay %6d us" % (s, p.value, d) for s, p, d in self.sinks]
        lines += ["  bounds AB4/ACA: %s" % self._bounds_prov]
        lines += ["  ASSUME %-18s = %-5d %s" % (n, v, why) for n, (v, why) in self.assumptions.items()]
        lines += ["  SUBSTITUTE %s := %s  (%s)" % (d, s, why) for d, s, why in SUBSTITUTES]
        lines += ["  SUBSTITUTE Ecm2GearState_c11 := GearCode2 snapshot  (ecm2/gear.py; firmware c11 passes through N at reversals)",
                  "  SUBSTITUTE Ecm2BrakeSwitch_c68 := BrakeSwitch  (same pin P1.14, PROG's copy)"]
        lines += ["  NOT PORTED: " + x for x in NOT_PORTED]
        if any(s.startswith("0x1C0.HV_") for s, _, _ in self.sinks):
            lines += ["  SUBSTITUTE Can20BRxW0 / Can20BRxW1 (M-CAN 0x20B B0..B1 / B2..B3, never logged) := 0x1C0"
                      " HV_Current / HV_Voltage raw  (user decision 2026-10-09, worklog 6H.69.5; that they carry"
                      " the same values is not established)"]
        if self.bounds_mode == "replay":
            lines += ["  NOT RUN: bound sources 0x80077598 0x80076EC6 0x80076DC2 0x800774AA 0x80076D72 0x8007729A"
                      " 0x800771FA (ported in dlcm/boundsrc.py; bounds=\"computed\" runs them)"]
        else:
            lines += ["  NOT PORTED (bounds): the DEM report of 0x8006F05A; range flags / DTC tails of the 0x275/0x276"
                      " copies; the checks inside the COM copy FUN_8008008C (0x200/0x300 counter, parity, toggle: assumed healthy)"]
        uns = [n for n in self.ram.unsourced() if n not in self.assumptions and n not in POWER_ON_ZERO]
        lines += ["  UNSOURCED (read, never written, held at 0): " + (", ".join(uns) or "none")]
        return "\n".join(lines)

    # ------------------------------------------------------------ sinks (value = DBC physical)
    def _s_0x210_ThottlePedalPos(self, t_us, pct):
        """REVERSED. 0x210 = (PedalInternal * 0x33333) >> 0x17, a 0.4 % truncation, so byte b
        means PedalInternal in (40b, 40b+40]; the middle is taken (old A9, tested 2026-10-06)."""
        b = int(round(pct / 0.4))
        self.ram.var("PedalInternal").set(40 * b + 20 if b > 0 else 0)

    def _s_0x418_GearStatus(self, t_us, raw):
        """REVERSED, exact. 0x418 B4 = nib(GearCode2) << 4 | nib(GearCode) (Publish10ms)."""
        raw = int(raw)
        lo, hi = raw & 0xF, raw >> 4
        if lo not in GEAR_NIB_TO_CODE or hi not in GEAR_NIB_TO_CODE:
            raise ValueError("0x418 GearStatus 0x%02X has a nibble outside the code table" % raw)
        self.ram.var("GearCode").set(GEAR_NIB_TO_CODE[lo])
        self.ram.var("GearCode2").set(GEAR_NIB_TO_CODE[hi])

    def _s_0x418_PRND(self, t_us, ascii_code):
        """REVERSED, LOSSY: PRND carries GearCode only; GearCode2 is set equal (old A2).
        Use 0x418.GearStatus instead wherever the capture has it."""
        c = GEAR_ASCII_TO_CODE.get(int(ascii_code))
        if c is None:
            raise ValueError("0x418 PRND %r is not P/R/N/D" % ascii_code)
        self.ram.var("GearCode").set(c)
        self.ram.var("GearCode2").set(c)

    def _speed(self, counts):
        """Fills the M-CAN 0x20C RX buffer (Can20CRxSpeedRaw = speed x2 + 0x7D80). SpeedRxCopy copies
        it to SpeedRaw at the start of the tick; TrqSpeedTask and ECM2 both use it this tick (6H.68)."""
        self.ram.var("Can20CRxSpeedRaw").set(u16(counts + 0x7D80))

    def _s_0x308_InputShaftSpeed(self, t_us, rpm):
        """REVERSED, exact: 0x308 raw = MotorSpeedSignedX2 + 0x7D80 at 0.5/-16064 -> x2 rpm. The
        frame published by tick k carries the 0x20C buffer of tick k (6H.68)."""
        c = rpm * 2
        if c != int(c):
            raise ValueError("0x308 rpm %r is off the 0.5 rpm grid" % rpm)
        self._speed(int(c))

    def _s_0x1C0_Motor_Speed(self, t_us, rpm):
        """PLANT (or RECEIVED in replay): same 0.5/-16064 encoding as 0x308. Off-grid raises."""
        c = rpm * 2
        if c != int(c):
            raise ValueError("Motor_Speed %r is off the 0.5 rpm grid (sensor must quantise)" % rpm)
        self._speed(int(c))

    def _s_0x208_BrakePressure(self, t_us, raw12):
        """RECEIVED, exact: fills the 0x208 PDU buffer (B2 low nibble, B3) as ComRxCopy does. Brake208Copy
        turns it into BrakeAnalog (unscaled, 6H.72.1) and ECM2 reads the same buffer (6H.73)."""
        raw12 = int(raw12)
        if not 0 <= raw12 <= 0xFFF:
            raise ValueError("0x208 BrakePressure %r is not a 12-bit field" % raw12)
        b2 = self.ram.var("Can208PduB2")
        b2.set((b2.get() & 0xF0) | (raw12 >> 8))
        self.ram.var("Can208PduB3").set(raw12 & 0xFF)

    def _s_0x208_BrakePressure_Valid(self, t_us, bit):
        """RECEIVED, exact: the 0x208 PDU buffer's B2 bit 4."""
        b2 = self.ram.var("Can208PduB2")
        b2.set((b2.get() & ~0x10 & 0xFF) | ((int(bit) & 1) << 4))

    def _s_0x212_BrakeSW(self, t_us, bit):
        """REVERSED, exact: Publish10ms copies BrakeSwitch 0xD0006831 to 0x212 BrakeSW (Pub212BrakeSw)."""
        self.ram.var("BrakeSwitch").set(int(bit))

    def _pdu300(self, name, mask, value):
        v = self.ram.var(name)
        v.set((v.get() & ~mask & 0xFF) | (value & mask))

    def _s_0x300_ESP_BrakingTqLimit(self, t_us, raw):
        """RECEIVED: raw 13-bit field -> PDU B2[4:0], B3 (read back by Can300BrakingTqLimitRead)."""
        raw = int(raw)
        self._pdu300("Can300PduB2", 0x1F, raw >> 8)
        self._pdu300("Can300PduB3", 0xFF, raw)

    def _s_0x300_ESP_TractiveTqLimit(self, t_us, raw):
        raw = int(raw)
        self._pdu300("Can300PduB4", 0x1F, raw >> 8)
        self._pdu300("Can300PduB5", 0xFF, raw)

    def _s_0x300_ESP_TractiveTqLimit_Armed(self, t_us, bit):
        self._pdu300("Can300PduB4", 0x40, int(bit) << 6)

    def _s_0x200_BrakeSW(self, t_us, bit):
        """RECEIVED, path untraced: 0x200 BrakeSW from SubFrameID 0 frames."""
        self.ram.var("BrakeSwitch").set(int(bit))

    def _s_0x312_M_MIN(self, t_us, nm):
        """REPLAYED-OUTPUT: M_MIN = -BoundSrcAB4 to within one 0.25 Nm count (worklog 6H.68.2).
        With bounds="computed" it only records the raw field for validation."""
        if self.bounds_mode == "computed":
            self.rec312.append((t_us, "M_MIN", int(round(nm / 0.25)) + 2000))
            return
        self._bounds["BoundSrcAB4"] = -int(round(nm / 0.1))
        self._bounds_prov = "REPLAYED 0x312 (a copy of AB4/ACA within one 0.25 Nm count, worklog 6H.68.2)"

    def _s_0x312_M_MAX(self, t_us, nm):
        if self.bounds_mode == "computed":
            self.rec312.append((t_us, "M_MAX", int(round(nm / 0.25)) + 2000))
            return
        self._bounds["BoundSrcACA"] = int(round(nm / 0.1))
        self._bounds_prov = "REPLAYED 0x312 (a copy of AB4/ACA within one 0.25 Nm count, worklog 6H.68.2)"

    # ---- inputs of the computed bound chain (bounds="computed")
    def _s_0x275_BattSentDischargeLimit(self, t_us, raw):
        """RECEIVED (D-CAN copy of the B-CAN frame, B-CAN DBC): raw B0 -> RX buffer."""
        self.ram.var("Can275RxB0").set(int(raw))

    def _s_0x275_BattSentChargeLimit(self, t_us, raw):
        self.ram.var("Can275RxB1").set(int(raw))

    def _s_0x276_PTC_PowerConsumption(self, t_us, raw):
        self.ram.var("Can276RxB0").set(int(raw))

    def _s_0x276_ACCM_PowerConsumption(self, t_us, raw):
        self.ram.var("Can276RxB1").set(int(raw))

    def _s_0x200_SubFrameID(self, t_us, raw):
        """RECEIVED: 0x200 B0, every frame (the firmware does not demux; only bit 2 is read)."""
        self.ram.var("Can200RxB0").set(int(raw))

    def _s_0x1C0_HV_Voltage(self, t_us, raw):
        """SUBSTITUTE (io.inputs.SUBSTITUTE_20B_FEEDS, the computed-mode default; user decision
        2026-10-09, worklog 6H.69.5): 0x1C0 B2..B3 raw into the unlogged M-CAN 0x20B B2..B3 buffer
        word. Same 0x7D80-offset encoding; that the two carry the same values is NOT established."""
        self.ram.var("Can20BRxW1").set(int(raw))

    def _s_0x1C0_HV_Current(self, t_us, raw):
        """SUBSTITUTE (as above): 0x1C0 B4..B5 raw into the 0x20B B0..B1 word."""
        self.ram.var("Can20BRxW0").set(int(raw))

    def _bound_sources(self):
        for n, v in self._bounds.items():
            self.ram.var(n).set(v)
