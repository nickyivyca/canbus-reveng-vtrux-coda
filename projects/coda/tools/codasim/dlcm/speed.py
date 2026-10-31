"""TrqSpeedTask 0x80075930 -> TrqSpeedFilter 0x8007596E (..0x80075CF2, tail 0x80075944..0x8007596C).

Source: ghidra_flash7/speedidx_limiter.txt; the listing for the task wrapper.
PORTED: speed hold/valid debounce, the 3-stage Q14 IIR, |.|, the speed index, and the
acceleration path 0x80075AD2..0x80075BEA (plan step 5b, spec E s5) -> SpeedAccelFilt 0xD0006A28,
read by the accel limiter. NOT PORTED (declared): the motor-vs-wheel speed plausibility latch
a0-0x3ee6 -> fault 0x26 via FUN_8007F6C8.
"""

from ..fixedpoint import s16, s32, u16
from .base import Block


class TrqSpeedTask(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.valid, self.raw, self.held = self.v("SpeedValid"), self.v("SpeedRaw"), self.v("MotorSpeedSignedX2")
        self.cnt, self.inval, self.prev = self.v("SpeedInvalidCount"), self.v("SpeedInvalid"), self.v("SpeedInvalidPrev")
        self.acc = [self.v("SpeedIirAcc1"), self.v("SpeedIirAcc2"), self.v("SpeedIirAcc3")]
        self.out = [self.v("SpeedIir1"), self.v("SpeedIir2"), self.v("SpeedFiltered")]
        self.absv, self.idx = self.v("SpeedFilteredAbs"), self.v("SpeedIndex")
        self.copy_src, self.copy = self.v("SpeedTaskCopySrc"), self.v("SpeedTaskCopy")
        self.g = self.k("CalSpeedIirGain")
        self.scale = self.k("CalSpeedIndexScale")
        self.deb = self.k("CalSpeedInvalidDebounce")
        self.ia, self.ida, self.idprev = self.v("SpeedIndexRaw"), self.v("SpeedIndexDelta"), self.v("SpeedIndexRawPrev")
        self.invprev = self.v("SpeedAccelInvalidPrev")
        self.aacc = [self.v("SpeedAccelIirAcc%d" % i) for i in (1, 2, 3)]
        self.aout = [self.v("SpeedAccelIir%d" % i) for i in (1, 2, 3)]
        self.accel = self.v("SpeedAccelFilt")
        self.ga = self.k("CalSpeedAccelIirGain")

    def run(self):
        self._filter()
        self.copy.set(self.copy_src.get())                     # 0x80075932..0x80075940

    def _filter(self):
        valid = self.valid.get() != 0
        old = self.cnt.get()
        new = 0 if valid else (0xFFFF if old == 0xFFFF else old + 1)
        inval = (self.deb <= old) and not valid               # count BEFORE this tick
        self.inval.set(inval)
        self.cnt.set(new)
        if valid:
            self.held.set(self.raw.get())
        spd = self.held.get()
        x0 = 0 if inval else spd                              # iVar12
        recovered = (not inval) and self.prev.get() != 0
        self.prev.set(inval)
        preload = inval or recovered
        x = spd                                               # iVar13 feeds stage 1
        for acc, out in zip(self.acc, self.out):
            if preload:
                a = s32(x0 * 0x4000)
            else:
                a = acc.get()
                a = s32(a + s32((x - (a >> 14)) * self.g))
            acc.set(a)
            x = out.set(s16(a >> 14))
        y = self.out[2].get()
        a32 = self.absv.set(s16(-y) if y < 0 else y)
        p = s32(a32 * self.scale)
        self.idx.set(u16(p >> 8) if p < 0xFFFF01 else 0xFFFF)
        self._accel(spd, inval)

    def _accel(self, d5, inval):
        """0x80075AD2..0x80075BEA: 3-stage IIR (coeff CAL 0xA002147C) of 100 x the per-tick change of
        the UNFILTERED speed index |0xD0005114| * 282 >> 8; zeroed while SpeedInvalid or the tick after."""
        v = s16(-d5) if d5 < 0 else d5                                    # 80075AD2 rsub ; extr
        t = self.scale * v
        ia = self.ia.set(0xFFFF if t > 0x00FFFF00 else u16(t >> 8))       # st.h 0xD0006A3E
        t = ia - s16(self.idprev.get())                                   # prev read ld.h
        d = self.ida.set(0x7FFF if t > 0x7FFF else s16(t))                # upper clamp only
        x = 0x7FFF if d > 0x147 else (-0x8000 if d < -0x147 else d * 100)  # 80075B0E..80075B30
        rst = inval or self.invprev.get() != 0                            # 80075B34..80075B50
        self.invprev.set(self.inval.get())                                # 80075B40..80075B46
        for acc, out in zip(self.aacc, self.aout):
            st = 0 if rst else s32(acc.get() + s32((x - (acc.get() >> 14)) * self.ga))
            acc.set(st)
            x = out.set(s16(st >> 14))
        self.accel.set(self.aout[2].get())                                # 80075BDC
        self.idprev.set(ia)                                               # 80075BE6..80075BEA
