"""Reason 12, inside Ecm2Reason12And14Detector 0x80056C20 at 0x80056ECC..0x800570B2.
Source: full_listing.txt; step-5 spec C s2. No gate of its own (no gear state, no enable byte).

  tol  = Lut B(0x80040A60)[|E6|]                  (flat 300 in stock, C4c and f7)
  trip when sat16(|b8c| + tol) < |s16(a16 - 0x7D80)|  (difference WRAPS; signed strict lt)
  flag = counter > CAL 0xA0021CDC (= 5): the 6th consecutive violating tick; a passing tick
         clears counter and flag.
Reasons 13, 14, 15/16 in the same function are NOT ported (they do not gate reason 12).
"""

from ..dlcm.base import Block
from ..fixedpoint import s16, sat_s16, u16
from ..lut import lut1d_unsigned
from .common import abs16, debounce


class Ecm2Reason12(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.e6, self.b8c, self.a16 = self.v("Ecm2SpeedFiltScaled"), self.v("Ecm2Allowance_b8c"), self.v("Ecm2ComparandMirror")
        self.tol, self.cnt, self.flag = self.v("Ecm2Reason12Tolerance"), self.v("Ecm2Reason12Cnt"), self.v("Ecm2Reason12Flag")
        self.t_tol, self.deb = self.t1("DescEcm2Reason12Tolerance"), self.k("CalEcm2Reason12Debounce")

    def run(self):
        x = abs16(self.e6.get())                                          # 80056ECC..80056F16
        tol = lut1d_unsigned(*self.t_tol, x)                              # 80056F2C
        self.tol.set(tol)
        lim = sat_s16(abs16(self.b8c.get()) + tol)                        # 80056F52..80056F94
        c = abs16(s16(u16(self.a16.get()) - 0x7D80))                      # 80056F96..80056FE0
        cond = lim < c                                                    # 80056FE4
        n = debounce(cond, self.cnt)                                      # 80056FE8..
        self.flag.set(1 if cond and self.deb < n else 0)                  # 80057060 / 80057096
