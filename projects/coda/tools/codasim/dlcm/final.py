"""TrqComparandClampAndError 0x80075D52: the final sum -> McmCommand 0xD0006A54.

Source: dlcm_export/clunk_funcs2.txt. AccelTermNeg / AccelTermPos come from the accel limiter
0x800750E8 (dlcm/accel.py, plan step 5b), which runs just before it.
"""

from ..fixedpoint import s16
from .base import Block


class FinalSum(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.y, self.tn, self.tp = V("TrqIir7aOut"), V("AccelTermNeg"), V("AccelTermPos")
        self.sin, self.base, self.dcl, self.mcm = V("FinalSumIn"), V("FinalBase"), V("FinalDamperClamped"), V("McmCommand")
        self.lo, self.hi, self.damp = V("FinalClampLo"), V("FinalClampHi"), V("DamperOut")

    def run(self):
        x = self.sin.set(self.y.get() + self.tn.get() + self.tp.get())
        b = self.base.set(max(min(x, self.hi.get()), self.lo.get()))
        m = s16(-b) if b < 0 else b
        dc = self.dcl.set(max(min(self.damp.get(), m), s16(-m)))
        s = s16(b + dc)
        self.mcm.set(max(min(s, 3000), -3000))
