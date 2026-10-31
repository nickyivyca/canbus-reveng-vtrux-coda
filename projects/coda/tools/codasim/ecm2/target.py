"""The slew limiter's TARGET operands b70 and b64 (b56 = sat16(b64 + b70) is formed in the limiter).

  Ecm2Reason10Detector      0x8004EEA2..0x8004F2A8  b74, b6e, aa7, aac (reason 10), b70
    Ecm2DirectionAgreementFlags 0x8004F2AA..0x8004F910  aa6/aa5 latches, aad, b72 (map value)
      Ecm2DemandMapD        0x8004F912..0x8004FC6A  (c11 == 40)
      Ecm2DemandMapR        0x8004FC6C..0x8004FFC8  (c11 == 10)
    Ecm2SlewLimiter_b6e     0x8004FFCA..0x80050244  (calibrated pass-through; ported anyway, R1)
  Ecm2Reason11Detector      0x80050246..0x80050AFC  aa1/aa0 latches, aa2, aa3, aab (reason 11), b64
    Ecm2CreepCeiling_b62    0x80050AFE..0x80050F14
    Ecm2CreepNotPermitted_aa4 0x80050F16..0x8005129A

Source: full_listing.txt; step-5 spec A (2026-10-09), which corrects worklog 6H.15-6H.17:
aa4 is not an N/P flag, b70 is not a symmetric min-magnitude select, b62 = b5e in normal running.
The pedal-fault (cb5 == 1) branches are transliterated but unreachable while cb5 is held 0. b5c's
divisor is 7 * (|EC| * PROG 0x80040A54 = 0): the firmware divides by zero EVERY tick EC != 0, and
uses the result only on the cb5 path -- so the model stores 0 there and raises if that path runs.
"""

from ..dlcm.base import Block
from ..fixedpoint import s16, sat_s16, div_trunc, ld_h, ld_hu, u16
from ..lut import lut1d_signed, lut1d_unsigned, lut2d
from .common import abs16, debounce, iir_q14, latch


class Ecm2DemandMap(Block):
    """0x8004F912 (D, c11 == 40) / 0x8004FC6C (R, c11 == 10): ECM2's own demand value b6c."""

    def __init__(self, ctx, side):
        super().__init__(ctx)
        self.side = side
        self.aad, self.e6 = self.v("Ecm2DirectionAgree_aad"), self.v("Ecm2SpeedFiltScaled")
        self.ca8, self.c68, self.ce4, self.cb5 = (self.v("Ecm2BrakePressure_ca8"), self.v("Ecm2BrakeSwitch_c68"),
                                                  self.v("Ecm2Pedal_ce4"), self.v("Ecm2PedalFault_cb5"))
        self.spd = self.v("Ecm2MapSpeed%s" % side)                     # b6a (D) / b68 (R)
        self.b6c = self.v("Ecm2MapValue_b6c")
        self.kbrk, self.kped = self.k("CalEcm2Map%sBrakeThreshold" % side), self.k("CalEcm2Map%sPedalThreshold" % side)
        self.brake_map, self.drive_map = self.t2("DescEcm2BrakeMap%s" % side), self.t2("DescEcm2DriveMap%s" % side)
        self.brake_map_f = self.t2("DescEcm2BrakeMap%sFault" % side)
        self.fault_1d = self.t1("DescEcm2Map%sFault1d" % side)

    def run(self):
        y = abs16(self.e6.get()) if self.aad.get() == 1 else 0           # 8004F9FC / 8004FD56
        self.spd.set(y)
        ca8, ce4, cb5 = ld_hu(self.ca8.get()), ld_hu(self.ce4.get()), self.cb5.get()
        brk = (self.kbrk < ca8) or self.c68.get()                         # lt.u on ld.hu values
        sel = brk and ce4 < self.kped                                     # pedal below 1.00 %
        if sel:
            v = lut2d(*(self.brake_map_f if cb5 else self.brake_map), ca8, ld_h(y))
        elif cb5:
            v = (lut1d_signed(*self.fault_1d, ld_h(y)) if self.side == "D"
                 else lut1d_unsigned(*self.fault_1d, u16(y)))             # R: extr.u then 0x80052370
        else:
            v = lut2d(*self.drive_map, ce4, ld_h(y))
        self.b6c.set(v)


class Ecm2DirectionAgreementFlags(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.spd, self.c10, self.c11 = self.v("Ecm2Speed"), self.v("Ecm2GearCode_c10"), self.v("Ecm2GearState_c11")
        self.aa6, self.aa5, self.aad = self.v("Ecm2DirFlag_aa6"), self.v("Ecm2DirFlag_aa5"), self.v("Ecm2DirectionAgree_aad")
        self.cnt = {n: self.v("Ecm2DirCnt_%s" % n) for n in ("ae4", "ae0", "ab4", "ab8")}
        self.th = [self.k(n) for n in ("CalEcm2Aa6Set", "CalEcm2Aa6Clr", "CalEcm2Aa5Set", "CalEcm2Aa5Clr")]
        self.dset, self.dclr = self.k("CalEcm2Aa56SetDebounce"), self.k("CalEcm2Aa56ClrDebounce")
        self.gD, self.gR = self.k("Ecm2GearCodeD"), self.k("Ecm2GearCodeR")
        self.sD, self.sR = self.k("Ecm2GearStateD"), self.k("Ecm2GearStateR")
        self.mapD, self.mapR = Ecm2DemandMap(ctx, "D"), Ecm2DemandMap(ctx, "R")
        self.b6c, self.b72 = self.v("Ecm2MapValue_b6c"), self.v("Ecm2MapValue_b72")

    def run(self):
        v = self.spd.get()
        s6, c6, s5, c5 = self.th
        latch(self.aa6, s6 < v, self.cnt["ae4"], self.dset, v < c6, self.cnt["ae0"], self.dclr)   # 8004F3F8..
        latch(self.aa5, v < s5, self.cnt["ab4"], self.dset, c5 < v, self.cnt["ab8"], self.dclr)   # 8004F5AC..
        c10 = self.c10.get()
        self.aad.set(1 if ((c10 == self.gD and self.aa6.get()) or (self.aa5.get() and c10 == self.gR)) else 0)
        c11 = self.c11.get()
        if c11 == self.sD:                                                # 8004F810
            self.mapD.run()
        if c11 == self.sR:                                                # 8004F840
            self.mapR.run()
        if c11 != self.sD and c11 != self.sR:                             # 8004F856
            self.b6c.set(0)
        self.b72.set(self.b6c.get())                                      # 8004F8C0


class Ecm2SlewLimiterB6e(Block):
    """0x8004FFCA: target b74 -> b6e, state b66. Steps 0/0 and snap bounds -32768/+32767 in every
    image make it an exact pass-through; transliterated anyway so a CAL edit would take effect."""

    def __init__(self, ctx):
        super().__init__(ctx)
        self.b74, self.b66, self.b6e = self.v("Ecm2ClampedMap_b74"), self.v("Ecm2SlewState_b66"), self.v("Ecm2SlewMap_b6e")
        self.up, self.dn = self.k("CalEcm2B66UpStep"), self.k("CalEcm2B66DownStep")
        self.lo, self.hi = self.k("CalEcm2B66SnapLo"), self.k("CalEcm2B66SnapHi")

    def run(self):
        tgt, st = self.b74.get(), self.b66.get()
        if sat_s16(tgt - st) >= 1:                                        # 800500BC
            out = tgt if self.lo < st else min(tgt, max(sat_s16(st + self.up), self.hi))
        else:
            out = tgt if st < self.hi else max(tgt, min(sat_s16(st + self.dn), self.lo))
        self.b6e.set(out)
        self.b66.set(out)                                                 # 800501F4


class Ecm2Reason10Detector(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.dirflags, self.slew = Ecm2DirectionAgreementFlags(ctx), Ecm2SlewLimiterB6e(ctx)
        self.b72, self.b76, self.b78 = self.v("Ecm2MapValue_b72"), self.v("Ecm2MapClampLo_b76"), self.v("Ecm2MapClampHi_b78")
        self.b74, self.b6e = self.v("Ecm2ClampedMap_b74"), self.v("Ecm2SlewMap_b6e")
        self.a14, self.aa7 = self.v("Ecm2DemandMirror_a14"), self.v("Ecm2MapOverridesProg_aa7")
        self.aac, self.cae8, self.b70 = self.v("Ecm2Reason10Flag"), self.v("Ecm2Reason10Cnt"), self.v("Ecm2Target_b70")
        self.margin, self.deb = self.k("CalEcm2B70Margin"), self.k("CalEcm2Reason10Debounce")

    def run(self):
        self.dirflags.run()                                               # 8004EFD4
        self.b74.set(s16(min(max(self.b72.get(), self.b76.get()), self.b78.get())))   # 8004EFD8..8004F044
        self.slew.run()                                                   # 8004F070
        m = sat_s16(abs16(self.b6e.get()) + self.margin)                  # 8004F074
        a14 = self.a14.get()
        aa7 = 1 if m < abs16(a14) else 0                                  # 8004F0BC (signed lt)
        self.aa7.set(aa7)
        self.aac.set(1 if self.deb < debounce(aa7 == 1, self.cae8) else 0)   # 8004F116 (non-latching)
        self.b70.set(self.b6e.get() if aa7 == 1 else a14)                 # 8004F1E2


class Ecm2CreepCeiling(Block):
    """0x80050AFE: b62. In normal running (cb5 == 0) b62 = b5e = aa2 ? 800 : Lut(0x80040938)[|E6|];
    the IIR (gain = coeff = 16384, load 0) is an exact pass-through."""

    def __init__(self, ctx):
        super().__init__(ctx)
        self.ec, self.e6, self.aa2, self.cb5 = (self.v("Ecm2SpeedFilt"), self.v("Ecm2SpeedFiltScaled"),
                                                self.v("Ecm2DirectionAgree_aa2"), self.v("Ecm2PedalFault_cb5"))
        self.b5c, self.b5e, self.b60 = self.v("Ecm2CreepPowerLimit_b5c"), self.v("Ecm2CreepCeilRaw_b5e"), self.v("Ecm2CreepCeilSel_b60")
        self.b62, self.st = self.v("Ecm2CreepEnvelope_b62"), self.v("Ecm2CreepEnvIirAcc_b94")
        self.pscale, self.num = self.k("Ecm2CreepPowerScale"), self.k("CalEcm2CreepPowerNum")
        self.kaa2, self.cap = self.k("CalEcm2CreepCeilDirOk"), self.k("CalEcm2CreepCeilCap")
        self.tab = self.t1("DescEcm2CreepCeiling")
        self.g, self.c = self.k("CalEcm2CreepEnvIirGain"), self.k("CalEcm2CreepEnvIirCoeff")

    def run(self):
        ec = self.ec.get()                                                # 80050C28
        if ec == 0:
            b5c = 0x7FFF
        else:
            p = s16(abs16(ec) * self.pscale)                              # mul, extr
            if p == 0:
                b5c = None        # dvinit by zero, EVERY tick EC != 0 (PROG 0x80040A54 = 0): result is
            else:                 # architecture-defined; consumed only on the cb5 path, which raises below
                b5c = sat_s16(div_trunc(0x3439 * self.num, 7 * p))
        self.b5c.set(0 if b5c is None else b5c)
        b5e = self.kaa2 if self.aa2.get() == 1 else lut1d_signed(*self.tab, abs16(self.e6.get()))   # 80050D0A
        self.b5e.set(b5e)
        if self.cb5.get() == 1:                                           # 80050DD6
            if b5c is None:
                raise NotImplementedError("b60 on the cb5 path needs b5c, a divide by zero (PROG 0x80040A54 = 0)")
            b60 = max(min(b5c, self.cap), b5e)
        else:
            b60 = b5e
        self.b60.set(b60)
        self.b62.set(iir_q14(self.st, b60, self.g, 0, self.c))            # 80050EBE


class Ecm2CreepNotPermitted(Block):
    """0x80050F16: aa4 = gear state not D/R, or b62 + 250 < b70, or |E6| >= b5a."""

    def __init__(self, ctx):
        super().__init__(ctx)
        self.c11, self.ce4, self.cb5 = self.v("Ecm2GearState_c11"), self.v("Ecm2Pedal_ce4"), self.v("Ecm2PedalFault_cb5")
        self.b62, self.b70, self.e6 = self.v("Ecm2CreepEnvelope_b62"), self.v("Ecm2Target_b70"), self.v("Ecm2SpeedFiltScaled")
        self.b58, self.b5a, self.aa4 = self.v("Ecm2CreepSpeedLimit_b58"), self.v("Ecm2CreepSpeedLimit_b5a"), self.v("Ecm2CreepNotPermittedFlag_aa4")
        self.tR, self.tD = self.t1("DescEcm2CreepSpeedLimitR"), self.t1("DescEcm2CreepSpeedLimitD")
        self.cap, self.margin = self.k("CalEcm2CreepSpeedLimitFaultCap"), self.k("CalEcm2CreepMargin")
        self.sD, self.sR = self.k("Ecm2GearStateD"), self.k("Ecm2GearStateR")

    def run(self):
        c11 = self.c11.get()
        b58 = lut1d_unsigned(*(self.tR if c11 == self.sR else self.tD), ld_hu(self.ce4.get()))   # 800510C4
        self.b58.set(b58)
        b5a = min(b58, self.cap) if self.cb5.get() == 1 else b58          # 800510EA
        self.b5a.set(b5a)
        self.aa4.set(1 if ((c11 != self.sR and c11 != self.sD)
                           or sat_s16(self.b62.get() + self.margin) < self.b70.get()
                           or abs16(self.e6.get()) >= b5a) else 0)        # 8005115C


class Ecm2Reason11Detector(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.spd, self.c10 = self.v("Ecm2Speed"), self.v("Ecm2GearCode_c10")
        self.aa1, self.aa0, self.aa2 = self.v("Ecm2DirFlag_aa1"), self.v("Ecm2DirFlag_aa0"), self.v("Ecm2DirectionAgree_aa2")
        self.cnt = {n: self.v("Ecm2DirCnt_%s" % n) for n in ("adc", "ad8", "abc", "ac0")}
        self.th = [self.k(n) for n in ("CalEcm2Aa1Set", "CalEcm2Aa1Clr", "CalEcm2Aa0Set", "CalEcm2Aa0Clr")]
        self.dset, self.dclr = self.k("CalEcm2Aa01SetDebounce"), self.k("CalEcm2Aa01ClrDebounce")
        self.gD, self.gR = self.k("Ecm2GearCodeD"), self.k("Ecm2GearCodeR")
        self.ceil, self.notperm = Ecm2CreepCeiling(ctx), Ecm2CreepNotPermitted(ctx)
        self.b62, self.a18, self.b70 = self.v("Ecm2CreepEnvelope_b62"), self.v("Ecm2CreepMirror_a18"), self.v("Ecm2Target_b70")
        self.aa4, self.aa3 = self.v("Ecm2CreepNotPermittedFlag_aa4"), self.v("Ecm2EnvelopeSelect_aa3")
        self.aab, self.cad4, self.b64 = self.v("Ecm2Reason11Flag"), self.v("Ecm2Reason11Cnt"), self.v("Ecm2Target_b64")
        self.margin, self.deb = self.k("CalEcm2CreepMargin"), self.k("CalEcm2Reason11Debounce")

    def run(self):
        v = self.spd.get()
        s1, c1, s0, c0 = self.th
        latch(self.aa1, s1 < v, self.cnt["adc"], self.dset, v < c1, self.cnt["ad8"], self.dclr)   # 800503F8..
        latch(self.aa0, v < s0, self.cnt["abc"], self.dset, c0 < v, self.cnt["ac0"], self.dclr)   # 800505D8..
        c10 = self.c10.get()
        self.aa2.set(1 if ((c10 == self.gD and self.aa1.get()) or (self.aa0.get() and c10 == self.gR)) else 0)
        self.ceil.run()                                                   # 8005083E
        self.notperm.run()                                                # 80050842
        b62, a18, b70, aa4 = self.b62.get(), self.a18.get(), self.b70.get(), self.aa4.get()
        L = sat_s16(b62 + self.margin)                                    # 80050846
        R = sat_s16(a18 + b70)                                            # 80050894
        aa3 = 1 if ((L < R and aa4 == 0) or (aa4 != 0 and a18 != 0)) else 0
        self.aa3.set(aa3)                                                 # 800508BC
        self.aab.set(1 if self.deb < debounce(aa3 == 1, self.cad4) else 0)   # 80050920 (non-latching)
        if aa3 == 0:                                                      # 800509EC
            self.b64.set(a18)
        elif aa4 == 0:                                                    # 80050A28
            self.b64.set(sat_s16(b62 - b70))
        else:                                                             # 80050AAE
            self.b64.set(0)
