"""ActiveSpeedDamper 0x800764F6 (called from 0x800764F0).

Source: ghidra_flash7/iir_creep_damper.txt. Divides are dvinit/dvstep/dvadj:
signed, truncating toward zero (fixedpoint.div_trunc).
"""

from ..fixedpoint import s16, s32, div_trunc
from ..lut import lut1d_signed
from .base import Block


class ActiveSpeedDamper(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.a38, self.held, self.a32 = V("SpeedFiltered"), V("MotorSpeedSignedX2"), V("SpeedFilteredAbs")
        self.err, self.prev, self.diff = V("DamperErr"), V("DamperErrPrev"), V("DamperDiff")
        self.acc, self.filt = V("DamperDAcc"), V("DamperDFilt")
        self.dt, self.pt, self.sum = V("DamperDTerm"), V("DamperPTerm"), V("DamperSum")
        self.bcnt, self.bok, self.ncnt = V("DamperBrakeCount"), V("DamperBrakeOk"), V("DamperNpCount")
        self.en, self.out = V("DamperEnabled"), V("DamperOut")
        self.gate, self.bsw, self.g = V("DamperBrakeGate"), V("BrakeSwitch"), V("GearCode")
        self.D, self.R = self.k("ProgGearCodeD"), self.k("ProgGearCodeR")
        self.c5, self.c20 = self.k("ProgGearCode5"), self.k("ProgGearCode20")
        self.kp, self.kd = self.k("CalDamperPGain"), self.k("CalDamperDGain")
        self.min_np, self.min_spd = self.k("CalDamperMinSpeedNp"), self.k("CalDamperMinSpeed")
        self.np_deb, self.brk_deb = self.k("CalDamperNpDebounce"), self.k("CalDamperBrakeDebounce")
        self.clamp, self.enable = self.k("CalDamperClamp"), self.k("CalDamperEnable")
        self.gain = self.t1("DescDamperDGain")

    def run(self):
        e = self.err.set(self.a38.get() - self.held.get())
        d = s16(e - self.prev.get())
        d = 0x7FFF if d >= 0x148 else (-0x8000 if d < -0x147 else d * 100)
        self.diff.set(d)
        a = self.acc.get()
        a = self.acc.set(s32(s32((d - (a >> 14)) * self.kd) + a))
        f = self.filt.set(s16(a >> 14))
        u = s32(f * lut1d_signed(*self.gain, self.a32.get()))
        dt = 0x7FFF if u >= 0x3E7F831 else (-0x8000 if u < -0x3E80000 else div_trunc(u, 2000))
        self.dt.set(dt)
        u = s32(self.kp * e)
        pt = 0x7FFF if u >= 0x63FF39 else (-0x8000 if u < -0x640000 else div_trunc(u, 200))
        self.pt.set(pt)
        dt = self.dt.get()
        s = s16(dt + pt)
        if dt >= 0 and pt >= 0 and s < 0:
            s = 0x7FFF
        elif dt < 0 and pt < 0 and s >= 0:
            s = -0x8000
        g = self.g.get()
        rev = g == self.R
        if rev:
            s = s16(-s)
        s = min(s, self.clamp)
        self.prev.set(e)
        self.sum.set(s if -self.clamp < s else -self.clamp)
        b8, b9 = self.gate.get() == 0, self.bsw.get() == 0
        old = self.bcnt.get()
        self.bcnt.set(0 if (b8 or b9) else (0xFFFF if old == 0xFFFF else old + 1))
        self.bok.set(self.brk_deb <= old or b8 or b9)
        np_ = g == self.c5 or g == self.c20
        old = self.ncnt.get()
        self.ncnt.set((0xFFFF if old == 0xFFFF else old + 1) if np_ else 0)
        np_deb = self.np_deb <= old and np_
        a32 = self.a32.get()
        on = (self.min_spd <= a32 and self.enable != 0 and self.bok.get() != 0
              and (rev or g == self.D or (not np_deb and self.min_np <= a32)))
        self.en.set(on)
        self.out.set(self.sum.get() if on else 0)


class DamperAbsPeakHoldUpdate(Block):
    """0x800767DA..0x8007689A, the tail of 0x800764F0 (`call 0x800764F6 ; j 0x800767DA`).

    Peak-hold of 100 |DamperOut| for CAL 0xA00215EC ticks, then linear decay; 0xD0006A78 = acc / 100.
    Read by TrqLimitMagnitudes. The enable CAL 0xA00215F5 is 0 in stock, C4c and f7, so the
    accumulator is cleared every tick and A78 = 0 (spec H 4)."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.d, self.acc, self.cnt, self.out = V("DamperOut"), V("DamperAbsPeakAcc"), V("DamperAbsPeakHoldCount"), V("DamperAbsPeakHold")
        self.en, self.hold, self.decay = (self.k("CalDamperPeakHoldEnable"), self.k("CalDamperPeakHoldTicks"),
                                          self.k("CalDamperPeakDecay"))

    def run(self):
        d = self.d.get()
        if d < 0:
            d = s16(-d)                                                # rsub ; extr (-32768 stays)
        m = d * 100
        acc = self.acc.get()
        dec = m < acc
        old = self.cnt.get()
        self.cnt.set((0xFFFF if old > 0xFFFE else old + 1) if dec else 0)
        step = dec and not (old < self.hold)                          # 8007682E (OLD count)
        if self.en != 0:
            if step:
                acc = s32(acc - self.decay)
                if acc < 1:
                    acc = 0
            else:
                acc = max(m, acc)
        else:
            acc = 0
        acc = self.acc.set(acc)
        self.out.set(div_trunc(acc, 100))                             # 80076866..98
