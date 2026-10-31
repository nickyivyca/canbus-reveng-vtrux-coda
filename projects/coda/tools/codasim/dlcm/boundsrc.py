"""The seven bound-source functions BoundsTask 0x8007689C calls before TrqClampBoundsRoleSwap.

Ported from three instruction-level specs (codasim step 6, worklog 6H.69), each read from
full_listing.txt. Call order, all in one tick:

    0x80077598  BoundTrackerMcm20B        Mcm20BW1 -> TrackLo 0xD0006ADC / TrackHi 0xD0006ADA
    0x80076EC6  BoundChgDisPerSpeed       0x275 / 0x276 copies, TrackLo/Hi -> AA8, AC2, A8A, A86
    0x80076DC2  BoundBrakeAndMins         AA4 = AA8; brake tables -> ABE
    0x800774AA  TrqBoundDerateAndMin      Lut(SpeedFilteredAbs) x (0x20D byte)/125 -> AB2, AC8
    0x80076D72  TrqLimitBases             0x80076BE6, 0x80076A92, slew 0x80076A18 -> AAE, AC6
    0x8007729A  TrqLimitMagnitudes        -> BoundSrcAB4, BoundSrcACA (published on 0x312)
    0x800771FA  EscTorqueLimitApply       -> BoundSrcAA6, BoundSrcAC0 (the final clamp)

Notation as in the specs: div_trunc is the signed dvinit/dvstep/dvadj divide (truncates toward
zero); sat_hi clamps the upper side only (a quotient below -0x8000 wraps, as st.h does); TriCore
min/max are signed. Every CAL these functions read is identical in stock, C4c and f7.
"""

from ..fixedpoint import s8, s16, u16, u8, s32, div_trunc
from ..lut import lut1d_signed, lut1d_unsigned
from .base import Block


def sat_hi(q):
    return 0x7FFF if q > 0x7FFF else s16(q)


def sat8(p):
    """TrqLimitMagnitudes' saturating >> 8: 0x7FFF above 0x007FFF00, -0x8000 below -0x00800000."""
    if p > 0x007FFF00:
        return 0x7FFF
    if p < -0x00800000:
        return -0x8000
    return s16(p >> 8)


def sat_inc(c):
    return 0xFFFF if c > 0xFFFE else c + 1


class _Deb:
    """u16 debounce counter: fires when cond and the OLD count >= cal (spec G 1a)."""

    def __init__(self, var):
        self.var = var

    def __call__(self, cond, cal):
        old = u16(self.var.get())
        self.var.set(sat_inc(old) if cond else 0)
        return bool(cond) and old >= cal


def _latch(var, set_, rst):
    """Reset-dominant set/reset latch (spec G 1b): no store when neither."""
    if set_ and not rst:
        var.set(1)
    elif rst:
        var.set(0)


class BoundTrackerMcm20B(Block):
    """0x80077598..0x80077668."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.v1 = V("Mcm20BW1")
        self.lo_st, self.lo = V("Mcm20BW1TrackLoState"), V("Mcm20BW1TrackLo")
        self.hi_st, self.hi = V("Mcm20BW1TrackHiState"), V("Mcm20BW1TrackHi")
        self.step, self.off = self.k("CalMcm20BTrackStep"), u16(self.k("CalMcm20BTrackOffset"))

    def run(self):
        v = self.v1.get()
        d4 = v * 100                                                   # 800775BA
        d5 = u16(v)
        lo = s16(d5 - self.off) * 100                                  # 800775CA..D6
        st = self.lo_st.set(max(lo, min(d4, s32(self.lo_st.get() + self.step))))
        self.lo.set(div_trunc(st, 100))                                # 800775E0..80077610
        hi = s16(self.off + d5) * 100                                  # 8007761C..30
        st = self.hi_st.set(min(hi, max(d4, s32(self.hi_st.get() - self.step))))
        self.hi.set(div_trunc(st, 100))                                # 8007763A..66


class BoundChgDisPerSpeed(Block):
    """0x80076EC6..0x800771F8."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.accm, self.ptc = V("Hvac276AccmX100"), V("Hvac276PtcX100")
        self.chg, self.dis = V("Bms275ChgLimX20"), V("Bms275DisLimX20")
        self.tlo, self.thi, self.spd = V("Mcm20BW1TrackLo"), V("Mcm20BW1TrackHi"), V("SpeedFilteredAbs")
        self.a82, self.a8c, self.a7c, self.a8e = (V("BoundChgLimNet"), V("BoundChgSum"),
                                                  V("BoundChgSpeedGain"), V("BoundChgSumScaled"))
        self.aa8 = V("BoundChgPerSpeed")
        self.a80, self.a92, self.a7e, self.a94 = (V("BoundDisLimNet"), V("BoundDisSum"),
                                                  V("BoundDisSpeedGain"), V("BoundDisSumScaled"))
        self.ac2, self.a8a, self.a86 = V("BoundDisPerSpeed"), V("BoundChgPerTrackHi"), V("BoundDisPerTrackHi")
        self.c_chg = u16(self.k("CalBoundChgLimOffset"))
        self.c_dis = u16(self.k("CalBoundDisLimOffset"))
        self.c_hvac = u16(self.k("CalBoundDisHvacOffset"))
        self.lut_chg, self.lut_dis = self.t1("DescBoundChgSpeedGain"), self.t1("DescBoundDisSpeedGain")

    def run(self):
        d8 = s16(u16(self.accm.get()) + u16(self.ptc.get()))                          # 80076EC6..E4
        a82 = self.a82.set(max(s16(u16(self.chg.get()) - self.c_chg), 0))             # 80076EEC..F14
        q1 = u16(div_trunc(d8, 10))                                                    # 80076F16..44
        q2 = u16(div_trunc(self.tlo.get() * a82, 1000))                                # 80076F48..76
        a8c = self.a8c.set(max(s16(q1 + q2), 0))                                       # 80076F7E..9A
        spd = self.spd.get()
        a7c = self.a7c.set(lut1d_signed(*self.lut_chg, spd))                           # 80076FA0..A6
        if a7c != 0:
            a8e = sat_hi(div_trunc(a8c << 15, a7c))                                   # 80076FA8..E6
        else:
            a8e = -0x8000 if a8c < 0 else 0x7FFF                                       # 80076FEC
        d11 = max(spd, 1) * 7                                                          # 80077000..10
        self.a8e.set(a8e)
        self.aa8.set(sat_hi(div_trunc(a8e * 0x3439, d11)))                             # 80077014..50
        a80 = self.a80.set(max(s16(u16(self.dis.get()) - self.c_dis), 0))             # 80077052..7E
        d5 = u16(div_trunc(self.tlo.get() * a80, 1000))                                # 80077080..AC
        d15 = u16(div_trunc(s16(self.c_hvac + u16(d8)), 10))                           # 800770B0..F4
        a92 = self.a92.set(max(s16(d5 - d15), 0))                                      # 800770FC..114
        a7e = self.a7e.set(lut1d_signed(*self.lut_dis, spd))                           # 80077116..1A
        a94 = self.a94.set((a7e * a92) >> 15)                                          # 8007711C..2A
        self.ac2.set(sat_hi(div_trunc(a94 * 0x3439, d11)))                             # 8007712C..6C
        dv = max(self.thi.get(), 1)                                                    # 8007716E..74
        self.a8a.set(sat_hi(div_trunc(a8c * 1000, dv)))                                # 80077178..B6
        self.a86.set(sat_hi(div_trunc(1000 * a92, dv)))                                # 800771B8..F6


class BoundBrakeAndMins(Block):
    """0x80076DC2..0x80076EC4."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.aa8, self.aa4 = V("BoundChgPerSpeed"), V("BoundChgPerSpeedCopy")
        self.ba, self.bvalid, self.bsw = V("BrakeAnalog"), V("BrakeAnalogValid"), V("BrakeSwitch")
        self.ad0, self.a90, self.acc = V("BoundBrakeTblA"), V("BoundBrakeTblB"), V("BoundBrakeTblBPerSpeed")
        self.abc, self.abe = V("BoundBrakeMin"), V("BoundBrakeDisMin")
        self.ac2, self.spd = V("BoundDisPerSpeed"), V("SpeedFilteredAbs")
        self.fa, self.fb = self.k("CalBoundBrakeTblAFallback"), self.k("CalBoundBrakeTblBFallback")
        self.ta, self.tb = self.t1("DescBoundBrakeTblA"), self.t1("DescBoundBrakeTblB")

    def _sel(self, table, fallback):
        r = lut1d_unsigned(*table, u16(self.ba.get()))
        if self.bvalid.get() != 0:
            return r
        return fallback if self.bsw.get() != 0 else 0x7FFF

    def run(self):
        self.aa4.set(self.aa8.get())                                                   # 80076DC2..CC
        ad0 = self.ad0.set(self._sel(self.ta, self.fa))                                # 80076DCE..E14
        d2 = self.a90.set(self._sel(self.tb, self.fb))                                 # 80076E16..4C
        den = max(self.spd.get(), 1) * 7                                               # 80076E4E..
        acc = self.acc.set(sat_hi(div_trunc(0x3439 * d2, den)))                        # ..80076EA6
        abc = self.abc.set(min(ad0, acc))                                              # 80076EA8..B2
        self.abe.set(min(abc, self.ac2.get()))                                         # 80076EB4..C2


class TrqBoundDerateAndMin(Block):
    """0x800774AA..0x80077596. Half A reads 0x20D B2, half B 0x20D B1; one LUT lookup for both."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.spd, self.lutv = V("SpeedFilteredAbs"), V("BoundSpeedLut")
        self.bit0, self.b1, self.b2 = V("Can20APduB0"), V("Can20DPduB1"), V("Can20DPduB2")
        self.fa, self.fb = V("BoundFactorRawA"), V("BoundFactorRawB")
        self.qa, self.qb = V("BoundDeratedA"), V("BoundDeratedB")
        self.aa4, self.abe = V("BoundChgPerSpeedCopy"), V("BoundBrakeDisMin")
        self.ab2, self.ac8 = V("BoundMinA"), V("BoundMinB")
        self.lut = self.t1("DescBoundSpeedLut")

    def _half(self, byte, fvar, qvar, other, out):
        f = fvar.set(125 if (self.bit0.get() & 1) else u8(byte.get() - 125))         # stored u8, read ld.b
        q = qvar.set(div_trunc(self.lutv.get() * s8(f), 125))
        out.set(min(other.get(), q))

    def run(self):
        self.lutv.set(lut1d_signed(*self.lut, self.spd.get()))                        # 800774BE..C4
        self._half(self.b2, self.fa, self.qa, self.aa4, self.ab2)                     # 800774C6..8007752C
        self._half(self.b1, self.fb, self.qb, self.abe, self.ac8)                     # 8007752E..80077594


class TrqBaseSelFrom300(Block):
    """0x80076BE6..0x80076D70."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.e, self.ped = V("Can300ChecksOk"), V("PedalInternal")
        self.c_inv = _Deb(V("TrqBase300InvalidCnt"))
        self.c_up, self.c_dn = _Deb(V("TrqBase300PedalAboveCnt")), _Deb(V("TrqBase300PedalBelowCnt"))
        self.la, self.lc = V("TrqBase300LatchA"), V("TrqBase300LatchC")
        self.sa, self.sc = V("TrqBase300SelA"), V("TrqBase300SelC")
        self.deb, self.thr, self.pdeb = (self.k("CalTrqBase300Deb"), self.k("CalTrqBasePedalThr"),
                                         self.k("CalTrqBase300PedalDeb"))
        self.a_off, self.a_on = self.k("CalTrqBase300SelAOff"), self.k("CalTrqBase300SelAOn")
        self.c_off, self.c_on = self.k("CalTrqBase300SelCOff"), self.k("CalTrqBase300SelCOn")

    def run(self):
        e = u8(self.e.get())
        s = self.c_inv(e == 0, self.deb)                                               # 80076BF0..C32
        ped = u16(self.ped.get())
        fu = self.c_up(self.thr < ped, self.pdeb)                                      # 80076C34..92
        _latch(self.la, s, fu and e != 0)                                              # 80076C9A..CB8
        fd = self.c_dn(ped < self.thr, self.pdeb)                                      # 80076CBA..CFC
        _latch(self.lc, s, e != 0 and fd)                                              # 80076D04..D1E
        self.sa.set(self.a_on if self.la.get() else self.a_off)                        # 80076D20..
        self.sc.set(self.c_on if self.lc.get() else self.c_off)                        # ..80076D70


class TrqBaseSelFrom200(Block):
    """0x80076A92..0x80076BE4."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.cl, self.b2, self.ped = V("Can200CounterLive"), V("Can200B0Bit2Fresh"), V("PedalInternal")
        self.c_cl, self.c_b2 = _Deb(V("TrqBase200CntrFrozenCnt")), _Deb(V("TrqBase200B0Bit2Cnt"))
        self.c_up = _Deb(V("TrqBase200PedalAboveCnt"))
        self.l, self.sel = V("TrqBase200Latch"), V("TrqBase200Sel")
        self.d_cl, self.d_b2 = self.k("CalTrqBase200CntrDeb"), self.k("CalTrqBase200B0Bit2Deb")
        self.d_up, self.thr = self.k("CalTrqBase200PedalDeb"), self.k("CalTrqBasePedalThr")
        self.off, self.on = self.k("CalTrqBase200SelOff"), self.k("CalTrqBase200SelOn")

    def run(self):
        a = self.c_cl(u8(self.cl.get()) == 0, self.d_cl)                              # 80076A92..ADE
        b = u8(self.b2.get()) != 0
        bb = self.c_b2(b, self.d_b2)                                                   # 80076AE0..B2A
        fu = self.c_up(self.thr < u16(self.ped.get()), self.d_up)                      # 80076B34..B92
        _latch(self.l, a or bb, (not b) and fu)                                        # 80076B9A..BB8
        self.sel.set(self.on if self.l.get() else self.off)                            # 80076BBA..BE4


class TrqUpperBoundSlewLimiter(Block):
    """0x80076A18..0x80076A90. The branch is chosen by a 16-bit WRAPPED difference (spec G 5)."""

    def __init__(self, ctx):
        super().__init__(ctx)
        self.tgt, self.out = self.v("TrqUpperBoundTarget"), self.v("TrqUpperBoundSlewed")
        self.en, self.step = self.k("CalUpperBoundSlewEnable"), self.k("CalUpperBoundSlewStep")

    def run(self):
        tgt = self.tgt.get()
        if self.en == 0:
            self.out.set(tgt)                                                          # 80076A84..90
            return
        prev = self.out.get()
        if s16(u16(tgt) - u16(prev)) >= 1:
            up = s16(prev + self.step)
            if prev >= 0 and up < 0:
                up = 0x7FFF
            out = min(tgt, up)
        else:
            dn = s16(prev - self.step)
            if prev < 0 and dn >= 0:
                dn = -0x8000
            out = max(tgt, dn)
        self.out.set(out)                                                              # 80076A80


class TrqLimitBases(Block):
    """0x80076D72..0x80076DC0."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.f300, self.f200 = TrqBaseSelFrom300(ctx), TrqBaseSelFrom200(ctx)
        self.slew = TrqUpperBoundSlewLimiter(ctx)
        self.sa, self.s200, self.tgt = V("TrqBase300SelA"), V("TrqBase200Sel"), V("TrqUpperBoundTarget")
        self.ab2, self.slewed, self.aae = V("BoundMinA"), V("TrqUpperBoundSlewed"), V("TrqBoundBaseForAB4")
        self.ac8, self.sc, self.ac6 = V("BoundMinB"), V("TrqBase300SelC"), V("TrqBoundBaseForACA")

    def run(self):
        self.f300.run()
        self.f200.run()
        self.tgt.set(min(self.sa.get(), self.s200.get()))                              # 80076D7A..8E
        self.slew.run()
        self.aae.set(min(self.ab2.get(), self.slewed.get()))                           # 80076D94..A8
        self.ac6.set(min(self.ac8.get(), self.sc.get()))                               # 80076DAA..BE


class TrqLimitMagnitudes(Block):
    """0x8007729A..0x800774A8."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.thi, self.tlo, self.w0 = V("Mcm20BW1TrackHi"), V("Mcm20BW1TrackLo"), V("Mcm20BW0")
        self.a8a, self.a86, self.a78 = V("BoundChgPerTrackHi"), V("BoundDisPerTrackHi"), V("DamperAbsPeakHold")
        self.aae, self.ac6 = V("TrqBoundBaseForAB4"), V("TrqBoundBaseForACA")
        self.ade, self.ad6, self.a88, self.ad4, self.ab6 = (V("BoundDerateADiff"), V("BoundDerateA"),
                                                             V("BoundDerateBDiff"), V("BoundDerateB"),
                                                             V("BoundDerateMinLo"))
        self.ae0, self.ad8, self.a84, self.ad2, self.ace = (V("BoundDerateCDiff"), V("BoundDerateC"),
                                                             V("BoundDerateDDiff"), V("BoundDerateD"),
                                                             V("BoundDerateMinHi"))
        self.ab4, self.aca = V("BoundSrcAB4"), V("BoundSrcACA")
        self.zcnt, self.zlat = V("BoundAcaZeroCount"), V("BoundAcaZeroLatched")
        self.ref_a, self.ref_c = u16(self.k("CalBoundDerateARef")), u16(self.k("CalBoundDerateCRef"))
        self.ga, self.gb = self.k("CalBoundDerateAGain"), self.k("CalBoundDerateBGain")
        self.gc, self.gd = self.k("CalBoundDerateCGain"), self.k("CalBoundDerateDGain")
        self.zdeb = u16(self.k("CalBoundAcaZeroDeb"))

    def run(self):
        ade = self.ade.set(s16(self.ref_a - u16(self.thi.get())))                     # 800772A2..B8
        ad6 = self.ad6.set(sat8(ade * self.ga))                                        # 800772BA..F4
        x = self.w0.get()
        a88 = self.a88.set(s16(u16(self.a8a.get()) - max(s16(-x), 0)))               # 800772FC..31A
        ad4 = self.ad4.set(sat8(a88 * self.gb))                                        # 8007731C..34A
        ab6 = self.ab6.set(min(min(ad6, ad4), 0))                                      # 8007734C..35C
        a78 = u16(self.a78.get())
        self.ab4.set(max(s16(u16(ab6) + u16(self.aae.get()) - a78), 0))               # 80077366..392
        ae0 = self.ae0.set(s16(u16(self.tlo.get()) - self.ref_c))                     # 80077394..3AE
        ad8 = self.ad8.set(sat8(ae0 * self.gc))                                        # 800773B0..3DE
        a84 = self.a84.set(s16(u16(self.a86.get()) - max(x, 0)))                      # 800773E0..3F6
        ad2 = self.ad2.set(sat8(a84 * self.gd))                                        # 800773F8..426
        ace = self.ace.set(min(min(ad8, ad2), 0))                                      # 80077428..438
        aca = self.aca.set(max(s16(u16(ace) + u16(self.ac6.get()) - a78), 0))         # 8007743A..45C
        z = aca == 0
        old = u16(self.zcnt.get())
        self.zlat.set(1 if (z and old >= self.zdeb) else 0)                           # 8007749A
        self.zcnt.set(sat_inc(old) if z else 0)                                        # 800774A6


class EscTorqueLimitApply(Block):
    """0x800771FA..0x80077298 (two rets)."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.copy = V("EscLimitEnableCopy")
        self.la, self.l200, self.lc = V("TrqBase300LatchA"), V("TrqBase200Latch"), V("TrqBase300LatchC")
        self.eb, self.et, self.arm = V("EspBrakingTqLimitProg"), V("EspTractiveTqLimitProg"), V("EspTractiveArmedProg")
        self.aae, self.ac6 = V("TrqBoundBaseForAB4"), V("TrqBoundBaseForACA")
        self.aa6, self.ac0 = V("BoundSrcAA6"), V("BoundSrcAC0")
        self.en_b, self.en_t = self.k("CalEscBrakingLimitEnable"), self.k("CalEscTractiveLimitEnable")

    def run(self):
        self.copy.set(self.en_t)                                                       # 80077202..08
        aae = self.aae.get()
        if self.la.get() == 0 and self.l200.get() == 0 and self.en_b != 0:            # 8007720A..24
            self.aa6.set(min(max(self.eb.get(), 0), aae))                              # 80077230..50
        else:
            self.aa6.set(aae)
        ac6 = self.ac6.get()
        if self.arm.get() != 0 and self.lc.get() == 0 and self.en_t != 0:             # 8007725A..68
            e = max(self.et.get(), 0)
            if e < ac6:
                self.ac0.set(e)                                                        # 80077288
                return
        self.ac0.set(ac6)                                                              # 8007728C..96


class BoundSources(Block):
    """The seven calls of BoundsTask before the role swap, in firmware order."""

    def __init__(self, ctx):
        super().__init__(ctx)
        self.blocks = [BoundTrackerMcm20B(ctx), BoundChgDisPerSpeed(ctx), BoundBrakeAndMins(ctx),
                       TrqBoundDerateAndMin(ctx), TrqLimitBases(ctx), TrqLimitMagnitudes(ctx),
                       EscTorqueLimitApply(ctx)]

    def run(self):
        for b in self.blocks:
            b.run()
