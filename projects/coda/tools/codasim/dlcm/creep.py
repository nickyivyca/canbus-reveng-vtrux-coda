"""CreepAssistOrchestrator 0x80075FF8 and its helpers:
CreepError 0x800763D2, CreepLatch 0x8007605E, CreepCeiling 0x80076302, CreepPi 0x80076208.

Sources: ghidra_flash7/creep_flag_fns.txt, creep_damper_fns.txt,
damper_sched_fns.txt; the PI's divide re-read in full_listing.txt
0x800762E2..0x800762FE (dvinit/dvstep/dvadj then st.h -- NO range check; the old
DlcmLoop zeroed the integral term unless 0 <= q <= 800).
"""

from ..fixedpoint import s16, s32, u16, div_trunc, ld_hu
from ..lut import lut1d_signed, lut1d_unsigned
from .base import Block


class Creep(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.pedal, self.g, self.g2 = V("PedalInternal"), V("GearCode"), V("GearCode2")
        self.a42, self.d6937 = V("SpeedIndex"), V("MovingInGearDir")
        self.bsw, self.ba, self.bv = V("BrakeSwitch"), V("BrakeAnalog"), V("BrakeAnalogValid")
        self.run_state, self.aba, self.aee = V("RunState"), V("ClampHi"), V("DemandClampedGated")
        self.latch, self.lprev, self.active = V("CreepLatch"), V("CreepLatchPrev"), V("CreepActive")
        self.seen, self.inhibit, self.lcnt = V("CreepActiveSeen"), V("CreepInhibit"), V("CreepLatchCount")
        self.ramp, self.spdt = V("CreepRamp"), V("CreepSpdTerm")
        self.err, self.err2, self.rising = V("CreepErr"), V("CreepErr2"), V("CreepRising")
        self.hold = V("CreepStandstillHold")
        self.craw, self.cacc, self.ceil, self.head = V("CreepCeilRaw"), V("CreepCeilAcc"), V("CreepCeil"), V("CreepHeadroom")
        self.integ, self.p, self.i, self.out = V("CreepInteg"), V("CreepP"), V("CreepI"), V("CreepOut")
        k = self.k
        self.D, self.R, self.active_rs = k("ProgGearCodeD"), k("ProgGearCodeR"), k("ProgRunStateActive")
        self.gate, self.ki, self.kp = k("CalCreepPedalGate"), k("CalCreepKi"), k("CalCreepKp")
        self.cg, self.kramp, self.tlat = k("CalCreepCeilGain"), k("CalCreepRamp"), k("CalCreepLatchedTarget")
        self.ldeb, self.cmov = k("CalCreepLatchDebounce"), k("CalCreepCeilMoving")
        self.en, self.len, self.bok = k("CalCreepEnable"), k("CalCreepLatchEnable"), k("CalCreepBrakeOk")
        self.tR, self.tD = self.t1("DescCreepTargetR"), self.t1("DescCreepTargetD")
        self.tC, self.tCB = self.t1("DescCreepCeiling"), self.t1("DescCreepCeilBrake")

    def _error(self):                                       # 0x800763D2
        ped = ld_hu(self.pedal.get())
        tr, td = lut1d_unsigned(*self.tR, ped), lut1d_unsigned(*self.tD, ped)
        latched = self.latch.get() != 0
        tgt = (tr if self.g.get() == self.R else td) if not latched else self.tlat
        spd = self.spdt.set(0 if ((not latched) == (self.d6937.get() == 0)) else self.a42.get())
        if not self.active.get():
            r = spd
        else:
            old = self.ramp.get()
            r = s16(self.kramp + old)
            if old >= 0 and r < 0:
                r = 0x7FFF
            r = min(r, tgt)
        r = self.ramp.set(r)
        e = s16(r - spd)
        self.err.set(e if not latched else s16(-e))
        self.rising.set(latched and self.lprev.get() == 0)
        e2 = s16(tgt - spd)
        self.err2.set(e2 if not latched else s16(-e2))
        self.lprev.set(self.latch.get())

    def _latch(self):                                       # 0x8007605E
        ped, bsw = self.pedal.get(), self.bsw.get() != 0
        b6 = bool(self.len and not bsw and ped < self.gate and self.active.get())
        still = self.a42.get() == 0
        self.hold.set(still and b6)
        old = self.lcnt.get()
        self.lcnt.set((0xFFFF if old == 0xFFFF else old + 1) if (still and b6) else 0)
        b4 = old < self.ldeb or not (still and b6)
        if not b4 and b6:
            self.latch.set(1)
        elif b4 and not b6:
            self.latch.set(0)
        held_zero = self.out.get() == 0 and self.latch.get() != 0
        stop = bsw or self.gate <= ped
        if stop:
            self.inhibit.set(0)
        elif held_zero:
            self.inhibit.set(1)
        g = self.g.get()
        self.active.set(bool(self.en and (not bsw or self.bok) and self.run_state.get() == self.active_rs
                             and g in (self.R, self.D) and g == self.g2.get()
                             and (self.err2.get() > 0 or self.out.get() > 0)
                             and self.inhibit.get() == 0))

    def _ceiling(self):                                     # 0x80076302
        cb = lut1d_unsigned(*self.tCB, ld_hu(self.ba.get()))
        calt = self.cmov if self.bsw.get() == 0 else 0
        c = lut1d_signed(*self.tC, ld_hu(self.a42.get()))
        if self.d6937.get():
            c = cb if self.bv.get() else calt
        self.craw.set(c)
        a = self.cacc.get()
        a = self.cacc.set(s32(a + s32((c - (a >> 14)) * self.cg)))
        v = min(s32(a * 4) >> 16, self.aba.get())
        self.ceil.set(v)
        h = s16(u16(v) - u16(self.aee.get()))
        self.head.set(h if h > 0 else 0)

    def _pi(self):                                          # 0x80076208
        err, head = self.err.get(), self.head.get()
        v = s32(self.kp * err)
        p = 0x7FFF if v >= 0x3FFF81 else (-0x8000 if v < -0x400000 else v >> 7)
        p = self.p.set(min(p, head))
        if not self.rising.get():
            w = s32(err * self.ki)
            w = 0x7FFF if w >= 0x7FFF1 else (-0x8000 if w < -0x80000 else w >> 4)
            w = s32(w + self.integ.get())
            lim = s32(s16(head - p) * 800)
            self.integ.set(max(min(lim, w), 0))
        else:
            self.integ.set(s32(s16(self.out.get() - p) * 800))
        self.i.set(div_trunc(self.integ.get(), 800))

    def run(self):                                          # 0x80075FF8
        self._error()
        self._latch()
        self._ceiling()
        if not self.active.get():
            self.seen.set(0)
        else:
            if not self.seen.get():
                self.integ.set(0)
                self.seen.set(1)
            self._pi()
        s = s16(u16(self.i.get()) + u16(self.p.get()))
        self.out.set(s if (self.active.get() and s > 0) else 0)
