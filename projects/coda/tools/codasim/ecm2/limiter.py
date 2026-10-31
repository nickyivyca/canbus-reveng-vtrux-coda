"""Ecm2SlewRateLimiter 0x80051B92..0x80052188. Source: full_listing.txt; step-5 spec B s1
(matches worklog 6H.38.5 line for line; corrects 6H.54.1 and 6H.10, see below).

  b56 = sat16(b64 + b70)                                       target
  b52 = min(Lut A(0x80040998)[E6], Lut A(0x800409A4)[b4e])     up step   (speed arm CAN bind)
  b50 = min(c67 ? Lut B(0x800409B0)[ca8] : (c68 ? -100 : -100),
            Lut A(0x800409BC)[b4e])                            down step (brake operand IS live)
  b54 = slew(b4e -> b56), snapping to the target outside +/-3000; b4e = b54 (state)
  b8c = min(max(b54, b7a), b7c)                                the allowance reason 12 checks
"""

from ..dlcm.base import Block
from ..fixedpoint import s16, sat_s16, ld_h, ld_hu
from ..lut import lut1d_signed, lut1d_unsigned


class Ecm2SlewRateLimiter(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.b64, self.b70, self.b56 = self.v("Ecm2Target_b64"), self.v("Ecm2Target_b70"), self.v("Ecm2SlewTarget_b56")
        self.e6, self.b4e = self.v("Ecm2SpeedFiltScaled"), self.v("Ecm2SlewState_b4e")
        self.c67, self.c68, self.ca8 = self.v("Ecm2DownStepSelector_c67"), self.v("Ecm2BrakeSwitch_c68"), self.v("Ecm2BrakePressure_ca8")
        self.b52, self.b50, self.b54 = self.v("Ecm2UpStep_b52"), self.v("Ecm2DownStep_b50"), self.v("Ecm2SlewOut_b54")
        self.b7a, self.b7c, self.b8c = self.v("Ecm2OuterClampLo_b7a"), self.v("Ecm2OuterClampHi_b7c"), self.v("Ecm2Allowance_b8c")
        self.t_up_spd, self.t_up_v = self.t1("DescEcm2UpSpeedCap"), self.t1("DescEcm2UpVcurve")
        self.t_dn_brk, self.t_dn_v = self.t1("DescEcm2DownBrake"), self.t1("DescEcm2DownVcurve")
        self.dn_sw, self.dn = self.k("CalEcm2DownStepBrakeSw"), self.k("CalEcm2DownStepNoBrake")
        self.lo, self.hi = self.k("CalEcm2SlewFloor"), self.k("CalEcm2SlewCeiling")

    def run(self):
        b56 = sat_s16(self.b64.get() + self.b70.get())                    # 80051D32..80051D78
        self.b56.set(b56)
        st = self.b4e.get()
        b52 = s16(min(lut1d_signed(*self.t_up_spd, ld_h(self.e6.get())),  # 80051DD2
                      lut1d_signed(*self.t_up_v, ld_h(st))))              # 80051E04, min 80051E10
        self.b52.set(b52)
        if self.c67.get() == 1:                                           # 80051E5A
            d8 = lut1d_unsigned(*self.t_dn_brk, ld_hu(self.ca8.get()))    # 80051E90
        else:
            d8 = self.dn_sw if self.c68.get() == 1 else self.dn           # 80051EB8..80051EC6
        b50 = s16(min(d8, lut1d_signed(*self.t_dn_v, ld_h(st))))          # 80051EF2, min 80051EFE
        self.b50.set(b50)
        if sat_s16(b56 - st) >= 1:                                        # rising
            out = b56 if self.hi < st else min(s16(max(sat_s16(b52 + st), self.lo)), b56)
        else:                                                             # falling
            out = b56 if st < self.lo else max(s16(min(sat_s16(b50 + st), self.hi)), b56)
        self.b54.set(out)                                                 # 80052092
        self.b4e.set(out)                                                 # 800520B0
        self.b8c.set(s16(min(s16(max(out, self.b7a.get())), self.b7c.get())))   # 800520CE..80052146
