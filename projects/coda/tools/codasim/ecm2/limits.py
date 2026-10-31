"""Ecm2EnableAndOuterClampWriter 0x8004DEDE..0x8004E95A with its callee Ecm2BaseTorqueLimits
0x8004E96A..0x8004EEA0. Source: full_listing.txt; step-5 specs A s1-2, B s2.

b82/b84 = brake-pressure lookups (or c68-selected CALs when 0x208 is invalid)
b86 = 0x3439*b82 / (7*|EC|) (signed divide, truncating), 0x7FFF at EC == 0;  b8a = min(b86, b84)
b88 = IIR toward 3000 (c65 == 0: reseeded every tick, so exactly 3000) or 350
b80/b7e = the 0x300 ESP limits mixed in;  aaa = selected-gear direction flag (aa9/aa8 latches)
[b7a, b7c] = aaa ? [-b7e, b80] : [-b80, b7e]   -> the outer clamp of b8c
[b76, b78] = aaa ? [-b88, b8a] : [-b8a, b88]   -> the clamp of ECM2's map value b74
"""

from ..dlcm.base import Block
from ..fixedpoint import s16, sat_s16, div_trunc, ld_hu
from ..lut import lut1d_unsigned
from .common import abs16, debounce, iir_q14, latch


class Ecm2BaseTorqueLimits(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.ca8, self.c67, self.c68, self.c65 = (self.v("Ecm2BrakePressure_ca8"), self.v("Ecm2DownStepSelector_c67"),
                                                  self.v("Ecm2BrakeSwitch_c68"), self.v("Ecm2Can300Lost_c65"))
        self.ec = self.v("Ecm2SpeedFilt")
        self.b82, self.b84, self.b86 = self.v("Ecm2BaseLimit_b82"), self.v("Ecm2BaseLimit_b84"), self.v("Ecm2BaseLimit_b86")
        self.b8a, self.b88, self.st88 = self.v("Ecm2BaseLimit_b8a"), self.v("Ecm2BaseLimit_b88"), self.v("Ecm2BaseLimitIirAcc_b9c")
        self.t82, self.t84 = self.t1("DescEcm2BrakeLimitB82"), self.t1("DescEcm2BrakeLimitB84")
        self.k82sw, self.k82 = self.k("CalEcm2B82BrakeSw"), self.k("CalEcm2B82NoBrake")
        self.k84sw, self.k84 = self.k("CalEcm2B84BrakeSw"), self.k("CalEcm2B84NoBrake")
        self.k88lost, self.k88 = self.k("CalEcm2B88Can300Lost"), self.k("CalEcm2B88Normal")
        self.g88, self.c88 = self.k("CalEcm2B88IirGain"), self.k("CalEcm2B88IirCoeff")

    def run(self):
        x = ld_hu(self.ca8.get())                                          # 8004EADA
        c67, c68 = self.c67.get(), self.c68.get()
        t = lut1d_unsigned(*self.t82, x)                                   # 8004EB0A
        b82 = t if c67 == 1 else (self.k82sw if c68 == 1 else self.k82)
        self.b82.set(b82)
        ec = self.ec.get()                                                 # 8004EBEE
        if ec == 0:
            b86 = 0x7FFF
        else:
            b86 = sat_s16(div_trunc(0x3439 * b82, 7 * abs16(ec)))          # 8004EC40..8004EC8E
        self.b86.set(b86)
        t = lut1d_unsigned(*self.t84, x)                                   # 8004ECE0
        b84 = t if c67 == 1 else (self.k84sw if c68 == 1 else self.k84)
        self.b84.set(b84)
        self.b8a.set(s16(min(b86, b84)))                                   # 8004EDC8
        lost = self.c65.get()
        inp = self.k88lost if lost == 1 else self.k88                      # 8004EDF4
        self.b88.set(iir_q14(self.st88, inp, self.g88, 1 if lost == 0 else 0, self.c88))


class Ecm2EnableAndOuterClampWriter(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.base = Ecm2BaseTorqueLimits(ctx)
        self.ca4, self.ca6, self.c63, self.c64 = (self.v("Ecm2EspTractiveTqLimit_ca4"), self.v("Ecm2EspBrakingTqLimit_ca6"),
                                                  self.v("Ecm2Can300Valid_c63"), self.v("Ecm2EspTractiveArmed_c64"))
        self.b8a, self.b88 = self.v("Ecm2BaseLimit_b8a"), self.v("Ecm2BaseLimit_b88")
        self.b80, self.b7e = self.v("Ecm2DeratedLimit_b80"), self.v("Ecm2DeratedLimit_b7e")
        self.aae, self.caf4 = self.v("Ecm2EnableTerm_aae"), self.v("Ecm2EnableTermCnt_af4")
        self.spd, self.c10 = self.v("Ecm2Speed"), self.v("Ecm2GearCode_c10")
        self.aa9, self.aa8, self.aaa = self.v("Ecm2DirFlag_aa9"), self.v("Ecm2DirFlag_aa8"), self.v("Ecm2ClampDirSel_aaa")
        self.cnt = {n: self.v("Ecm2DirCnt_%s" % n) for n in ("af0", "aec", "ac8", "ac4")}
        self.b7c, self.b7a = self.v("Ecm2OuterClampHi_b7c"), self.v("Ecm2OuterClampLo_b7a")
        self.b78, self.b76 = self.v("Ecm2MapClampHi_b78"), self.v("Ecm2MapClampLo_b76")
        self.kaae = self.k("CalEcm2AaeDebounce")
        self.th = [self.k(n) for n in ("CalEcm2Aa9Set", "CalEcm2Aa9Clr", "CalEcm2Aa8Set", "CalEcm2Aa8Clr")]
        self.dset, self.dclr = self.k("CalEcm2Aa89SetDebounce"), self.k("CalEcm2Aa89ClrDebounce")
        self.gD, self.gR = self.k("Ecm2GearCodeD"), self.k("Ecm2GearCodeR")

    def run(self):
        self.base.run()                                                    # 8004E0D8
        b8a, b88, c63 = self.b8a.get(), self.b88.get(), self.c63.get()
        t = s16(min(s16(max(self.ca4.get(), 0)), b8a))                     # 8004E0DC..8004E132
        b80 = t if (self.c64.get() and c63) else b8a                       # 8004E13A..8004E19E
        self.b80.set(b80)
        e = self.ca6.get() == 0 and c63                                    # 8004E1B8..8004E1E0
        self.aae.set(1 if self.kaae < debounce(e, self.caf4) else 0)       # 8004E1E2..8004E2B6
        t = s16(min(s16(max(self.ca6.get(), 0)), b88))                     # 8004E2C8..8004E2FE
        b7e = t if c63 == 1 else b88                                       # 8004E306..8004E32A
        self.b7e.set(b7e)
        v = self.spd.get()
        s9, c9, s8, c8 = self.th
        latch(self.aa9, s9 < v, self.cnt["af0"], self.dset, v < c9, self.cnt["aec"], self.dclr)   # 8004E370..
        latch(self.aa8, v < s8, self.cnt["ac8"], self.dset, c8 < v, self.cnt["ac4"], self.dclr)   # 8004E524..
        c10 = self.c10.get()
        aaa = 1 if ((c10 == self.gD and self.aa9.get()) or (self.aa8.get() and c10 == self.gR)) else 0
        self.aaa.set(aaa)                                                  # 8004E6D8..8004E76C
        if aaa:
            self.b7c.set(b80); self.b7a.set(s16(-b7e))                     # 8004E7DC.., rsub + extr (wraps)
            self.b78.set(b8a); self.b76.set(s16(-b88))                     # 8004E86E..8004E92E
        else:
            self.b7c.set(b7e); self.b7a.set(s16(-b80))
            self.b78.set(b88); self.b76.set(s16(-b8a))
