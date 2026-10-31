"""PROG-side receive decodes the bounds chain reads (codasim step 6).

Can300DecodeProg   0x8006F05A, first callee of tick member 0x8006ED2C (called at 0x8007C316, before
                   TrqSpeedTask). Its own decode of the 0x300 PDU, bit-identical to ECM2's ca6/ca4
                   (ecm2/canread.py) but separate RAM, with no validity gate on the limits.
                   0xD0006845 = 0x300 fresh && parity-ok && toggle-live. The DEM report that follows
                   (tail call 0x8007F6C8, event 0x6E) is NOT PORTED.
Can200B0Bit2       0x8006ED3C, also under 0x8006ED2C: 0xD0006839 = 0x200 fresh && 0x200 B0 bit 2.
Brake208Copy       0x8006ED3C, its 0x208 brake-pressure part (0x8006ED88..0x8006EDCC): BrakeAnalog = the
                   12-bit field from the 0x208 PDU buffer, unscaled; BrakeAnalogValid = validity bit &&
                   0x208 fresh && field != 0x0FFF.  Runs in every bounds mode (the demand, creep, limiter
                   and bound chain all read BrakeAnalog).
BmsHvacCopy        the 0x275 / 0x276 copies inside tick member 0x80072674 (0x80072B86, 0x80072C70,
                   0x80072CCE; called at 0x8007C35E, after TrqSpeedTask). Their range flags and DTC tail
                   jumps are NOT PORTED.

Received PDU buffers are filled by the COM copy FUN_8008008C (ComRxCopy), called once per tick at
0x8007C29A at the top of DlcmTorqueTask10ms (worklog 6H.73), before every block here and before ECM2.
codasim's sinks write those buffers at frame arrival (clock ORDER_RX, ahead of the tick), which is the
same thing: a frame is seen by the first tick at or after it, by PROG and ECM2 alike.  The freshness
flags and the parity / toggle / counter checks are still declared assumptions in controller.ASSUMPTIONS.
Source: specs F (5.2, 5.3), G (8a, 8b), H (3.2); full_listing.txt.
"""

from ..fixedpoint import s16, u16
from .base import Block


class Can200B0Bit2(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.b0, self.bit, self.stale, self.out = V("Can200RxB0"), V("Can200B0Bit2"), V("Can200Stale"), V("Can200B0Bit2Fresh")

    def run(self):
        b = self.bit.set((self.b0.get() & 0x04) >> 2)                       # 8006ED3E..46
        self.out.set(1 if (self.stale.get() == 0 and b != 0) else 0)        # 8006ED48..5E


class Brake208Copy(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.b2, self.b3, self.stale = V("Can208PduB2"), V("Can208PduB3"), V("Can208Timeout")
        self.raw, self.vbit = V("Can208BrakeRaw12"), V("Can208BrakeValidBit")
        self.ba, self.bv = V("BrakeAnalog"), V("BrakeAnalogValid")

    def run(self):
        b2 = self.b2.get()
        raw = self.raw.set(((b2 << 8) & 0xF00) | self.b3.get())            # 8006ED8C..90 (FUN_8008062E)
        self.ba.set(raw)                                                    # 8006ED92..9A, ld.hu / st.h
        vb = self.vbit.set((b2 & 0x10) >> 4)                                # 8006EDA0..A4 (FUN_8008061C)
        fresh = self.stale.get() == 0                                       # 8006EDA6..A8
        self.bv.set(1 if (vb and fresh and raw != 0xFFF) else 0)            # 8006EDAC..CC


class Can300DecodeProg(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.pdu = [V("Can300PduB%d" % i) for i in (2, 3, 4, 5)]
        self.rb, self.eb = V("EspBrakingTqLimitRawProg"), V("EspBrakingTqLimitProg")
        self.rt, self.et = V("EspTractiveTqLimitRawProg"), V("EspTractiveTqLimitProg")
        self.ra, self.arm = V("EspTractiveArmedRawProg"), V("EspTractiveArmedProg")
        self.par, self.tog, self.stale = V("Can300ParityOk"), V("Can300ToggleLive"), V("Can300Stale")
        self.parc, self.togc, self.ok = V("Can300ParityOkCopy"), V("Can300ToggleLiveCopy"), V("Can300ChecksOk")

    def run(self):
        b2, b3, b4, b5 = (b.get() for b in self.pdu)
        rb = self.rb.set(((b2 & 0x1F) << 8) | b3)                           # 8006F072 (FUN_80080588)
        self.eb.set(s16(u16((rb * 5) >> 1) - 5000))                         # 8006F07C..92
        rt = self.rt.set(((b4 & 0x1F) << 8) | b5)                           # 8006F094 (FUN_80080572)
        self.et.set(s16(u16((rt * 5) >> 1) - 5000))                         # 8006F09A..B0
        p = self.parc.set(self.par.get())                                   # 8006F0C2..C8
        t = self.togc.set(self.tog.get())                                   # 8006F0CA..CC
        self.ok.set(1 if (self.stale.get() == 0 and p != 0 and t != 0) else 0)   # 8006F0D2..E8
        self.arm.set(self.ra.set((b4 & 0x40) >> 6))                         # 8006F0EE..FA


class BmsHvacCopy(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.r275 = (V("Can275RxB0"), V("Can275RxB1"))
        self.dpre, self.dis, self.cpre, self.chg = (V("Bms275DisLimX20Pre"), V("Bms275DisLimX20"),
                                                    V("Bms275ChgLimX20Pre"), V("Bms275ChgLimX20"))
        self.r276 = (V("Can276RxB0"), V("Can276RxB1"))
        self.araw, self.accm, self.praw, self.ptc = (V("Hvac276AccmRaw"), V("Hvac276AccmX100"),
                                                     V("Hvac276PtcRaw"), V("Hvac276PtcX100"))

    def run(self):
        self.dis.set(self.dpre.set(self.r275[0].get() * 20))               # 0x80072B86..
        self.chg.set(self.cpre.set(self.r275[1].get() * 20))
        self.accm.set(self.araw.set(self.r276[1].get()) * 100)            # 0x80072C70..86
        self.ptc.set(self.praw.set(self.r276[0].get()) * 100)             # 0x80072CCE..E4
