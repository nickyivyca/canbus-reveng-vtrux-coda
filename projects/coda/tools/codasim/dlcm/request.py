"""TrqRequestSum 0x80075CF8 -> TrqGradientLimiter 0x80075DFA -> TrqSpeedIir3Stage 0x80075F56.

Sources: full_listing.txt 0x80075CF8..0x80075D50, 0x80075F56..0x80075FF4;
ghidra_flash7/speedidx_limiter.txt (FUN_80075DFA). Integer throughout; the old
torque_path_sim.TorquePath ran this in float with a float TrqLast.
"""

from ..fixedpoint import s16, s32
from ..lut import lut1d_signed, lut1d_unsigned
from ..fixedpoint import ld_hu
from .base import Block


class TrqGradientLimiter(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.a42, self.last, self.req = self.v("SpeedIndex"), self.v("TrqLast"), self.v("TrqRequest")
        self.ba, self.bv, self.bsw = self.v("BrakeAnalog"), self.v("BrakeAnalogValid"), self.v("BrakeSwitch")
        self.bstep = self.v("LimiterBrakeStep")
        self.en, self.run_state = self.v("DemandEnable"), self.v("RunState")
        self.active = self.k("ProgRunStateActive")
        self.hi, self.lo = self.k("CalLimiterHi"), self.k("CalLimiterLo")
        self.rate_en = self.k("CalLimiterEnable")
        self.neg_off, self.neg_on = self.k("CalLimiterNegBrkSwOff"), self.k("CalLimiterNegBrkSwOn")
        self.t_up_spd, self.t_up_v = self.t1("DescLimiterUpSpeed"), self.t1("DescLimiterUpVcurve")
        self.t_dn_brk, self.t_dn_v = self.t1("DescLimiterDownBrake"), self.t1("DescLimiterDownVcurve")

    def run(self):
        last = self.last.get()
        up_spd = lut1d_signed(*self.t_up_spd, ld_hu(self.a42.get()))
        up_v = lut1d_signed(*self.t_up_v, last)
        b = lut1d_unsigned(*self.t_dn_brk, ld_hu(self.ba.get()))          # FUN_8005EFD0
        if not self.bv.get():
            b = self.neg_on if self.bsw.get() else self.neg_off
        self.bstep.set(b)
        dn_v = lut1d_signed(*self.t_dn_v, last)
        req = self.req.get()
        if not self.en.get() or self.run_state.get() != self.active:
            out = 0
        elif not self.rate_en:
            out = req
        elif s16(req - last) < 1:                                          # decreasing
            out = req
            if self.lo <= last:
                step = min(self.bstep.get(), dn_v)
                n = s16(last + step)
                if last < 0 and step < 0 and n >= 0:
                    n = -0x8000
                if self.hi < n:
                    n = self.hi
                if req <= n:
                    out = n
        else:                                                              # increasing
            out = req
            if last <= self.hi:
                step = min(up_spd, up_v)
                n = s16(last + step)
                if last >= 0 and step >= 0 and n < 0:
                    n = 0x7FFF
                if n < self.lo:
                    n = self.lo
                if n <= req:
                    out = n
        self.last.set(out)


class TrqSpeedIir3Stage(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.last, self.dem, self.out = self.v("TrqLast"), self.v("TrqRawDemand"), self.v("TrqIir7aOut")
        self.acc = [self.v("Iir7aAcc1"), self.v("Iir7aAcc2"), self.v("Iir7aAcc3")]
        self.gain = self.t1("Desc7aGain")
        self.en = self.k("Cal7aEnable")

    def run(self):
        x8 = self.last.get()
        k = lut1d_signed(*self.gain, self.dem.get())
        x = x8
        for acc in self.acc:
            if not self.en:
                a = s32(x8 << 14)
            else:
                a = acc.get()
                a = s32(a + s32((x - (a >> 14)) * k))
            acc.set(a)
            x = s16(a >> 14)                                               # extr d,d,#14,#16
        self.out.set(x if self.en else x8)                                 # 0x80075FE4 / 0x80075FEC


class TrqRequestSum(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.a, self.b, self.req = self.v("DemandClampedGated"), self.v("CreepOut"), self.v("TrqRequest")
        self.lim, self.iir = TrqGradientLimiter(ctx), TrqSpeedIir3Stage(ctx)
        self.y, self.pub = self.v("TrqIir7aOut"), self.v("Pub212Src")
        self.lo, self.hi, self.oc = self.v("FinalClampLo"), self.v("FinalClampHi"), self.v("TrqRequestOutClamped")

    def run(self):
        self.req.set(self.a.get() + self.b.get())                          # extr.u + add, st.h
        self.lim.run()
        self.iir.run()
        y = self.y.get()
        self.pub.set(y)
        self.oc.set(max(min(y, self.hi.get()), self.lo.get()))
