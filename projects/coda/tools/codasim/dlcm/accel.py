"""The accel limiter: FUN_800750E8 (tick member between TrqRequestSum and FinalSum) with 0x80075394
(bounds and errors), 0x8007566E (AccelTermPos) and 0x80075896 (speed-limit cap). Writes
AccelTermNeg 0xD00050F8 (<= 0) and AccelTermPos 0xD00050FA (>= 0), which FinalSum adds to the 7a
output -- after 0x212, so no 0x212 validation can see them. Plan step 5b; source full_listing.txt,
spec E (2026-10-09). Every CAL and table is identical in stock, C4c and f7.

Structure (measured): a predicted acceleration d10 = (7a out - Lut(SpeedIndex)) * 1508 / 2560 (the
PROG twin of ECM2's reason-15 band), a band around the measured acceleration 0xD0006A28, and two PI
terms that count only while moving in the selected gear's direction (else the errors are pinned to
-13 / +13 and can only wind a term down).
"""

from ..fixedpoint import s16, s32, div_trunc, ld_hu
from ..lut import lut1d_signed, lut1d_signed_yu, lut1d_wavg_u, lut2d
from .base import Block

SATDIV = {1280: (0x027FFB00, -0x02800000), 1600: (0x031FF9C0, -0x03200000), 2560: (0x04FFF600, -0x05000000)}


def satdiv(t, n):
    """Interrupt-masked signed divide by n with the saturation bounds each site checks first."""
    hi, lo = SATDIV[n]
    if not hi >= t:
        return 0x7FFF
    if not t >= lo:
        return -0x8000
    return s16(div_trunc(t, n))


def sadd16(a, b):
    """Two-sided signed-overflow fix as the listing writes it."""
    r = s16(a + b)
    if a >= 0 and b >= 0 and r < 0:
        return 0x7FFF
    if a < 0 and b < 0 and r >= 0:
        return -0x8000
    return r


def ssub16(a, b):
    r = s16(a - b)
    if a >= 0 and b < 0 and r < 0:
        return 0x7FFF
    if a < 0 and b >= 0 and r >= 0:
        return -0x8000
    return r


class AccelSpeedCap(Block):
    """0x80075896: FE = Lut(0x80043F50)[k - SpeedIndex]; k selected by the 0x370 field and gear."""

    def __init__(self, ctx):
        super().__init__(ctx)
        self.f370, self.gc, self.idx = self.v("Can370B0Field64"), self.v("GearCode"), self.v("SpeedIndex")
        self.k_sel, self.k_dist, self.fe = self.v("AccelSpeedLimitK"), self.v("AccelSpeedLimitDist"), self.v("AccelSpeedCap")
        self.code1, self.gR = self.k("ProgCan370Field64Code1"), self.k("ProgGearCodeR")
        self.k_def, self.k_r, self.k_nr = self.k("CalAccelSpeedLimitK"), self.k("CalAccelSpeedLimitKR"), self.k("CalAccelSpeedLimitKNotR")
        self.tab = self.t1("DescAccelSpeedCap")

    def run(self):
        if self.f370.get() == self.code1:
            k = self.k_r if self.gc.get() == self.gR else self.k_nr
        else:
            k = self.k_def
        self.k_sel.set(k)
        t = k - ld_hu(self.idx.get())
        d = self.k_dist.set(0x7FFF if t > 0x7FFF else (-0x8000 if t < -0x8000 else s16(t)))
        self.fe.set(lut1d_signed(*self.tab, d))                            # 0x8005F082


class AccelBounds(Block):
    """0x80075394: predicted acceleration, the band, the low-side error A04 and high-side error FC."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.a22, self.idx, self.a24, self.a14 = V("AccelTorque"), V("SpeedIndex"), V("AccelTorqueOffset"), V("AccelTorqueNet")
        self.bsw, self.acc, self.a00, self.a02 = V("BrakeSwitch"), V("SpeedAccelFilt"), V("AccelBandLo"), V("AccelBandLoErr")
        self.gc, self.spd, self.a04, self.a06 = V("GearCode"), V("MotorSpeedSignedX2"), V("AccelErrLo"), V("AccelJerk")
        self.prev_acc, self.ped = V("SpeedAccelPrev"), V("PedalInternal")
        self.f6, self.f8, self.fe, self.fa, self.fc = (V("AccelBandHiRaw"), V("AccelBandHi"), V("AccelSpeedCap"),
                                                       V("AccelBandHiErr"), V("AccelErrHi"))
        self.a0e, self.a0c = V("AccelTorqueIndex"), V("AccelIndexMargin")
        self.cap = AccelSpeedCap(ctx)
        self.t_off, self.t_map, self.t_idx = self.t1("DescAccelTorqueOffset"), self.t2("DescAccelPedalMap"), self.t1("DescAccelTorqueIndex")
        self.k_scale, self.k_lo, self.k_lobrk = self.k("CalAccelPredictScale"), self.k("CalAccelBandLoOffset"), self.k("CalAccelBandLoBrakeSw")
        self.k_elo, self.k_ehi = self.k("CalAccelErrLoIdle"), self.k("CalAccelErrHiIdle")
        self.k_thr, self.k_q15 = self.k("CalAccelIndexFormThreshold"), self.k("CalAccelQ15Gain")
        self.gD, self.gR = self.k("ProgGearCodeD"), self.k("ProgGearCodeR")

    def run(self):
        a24 = self.a24.set(lut1d_wavg_u(*self.t_off, ld_hu(self.idx.get())))          # 0x8005EF50
        t = self.a22.get() - ld_hu(a24)
        a14 = self.a14.set(-0x8000 if t < -0x8000 else s16(t))                        # lower clamp only
        d10 = satdiv(a14 * ld_hu(self.k_scale), 2560)                                 # predicted accel
        d15 = s16(d10 - self.k_lo)
        if d10 < 0 and self.k_lo >= 0 and d15 >= 0:
            d15 = -0x8000                                                            # one-sided fix
        if self.bsw.get() != 0:
            d0 = s16(d15 - self.k_lobrk)
            if d15 < 0 and self.k_lobrk >= 0 and d0 >= 0:
                d0 = -0x8000
        else:
            d0 = d15
        a00 = self.a00.set(min(d0, 0))                                                # 80075488
        acc = self.acc.get()
        a02 = self.a02.set(ssub16(a00, acc))
        gc, spd = self.gc.get(), self.spd.get()
        moving = (gc == self.gR and spd < 0) or (gc == self.gD and spd >= 1)         # 800754BC..80075500
        self.a04.set(a02 if moving else self.k_elo)
        self.a06.set(ld_hu(s16(ld_hu(acc) - ld_hu(self.prev_acc.get())) * 100))      # extr.u, sub, extr, mul
        self.cap.run()                                                                # 0x80075896
        m = lut2d(*self.t_map, ld_hu(self.ped.get()), s16(ld_hu(self.idx.get())))     # 0x8005F3DA, y extr signed
        d15 = s16(m + d10)
        if m >= 0 and d10 >= 0 and d15 < 0:
            d15 = 0x7FFF                                                             # one-sided fix
        f6 = self.f6.set(max(d15, 0))
        f8 = self.f8.set(min(self.fe.get(), f6))                                      # 80075586
        direct = ld_hu(self.idx.get()) >= ld_hu(self.k_thr)                           # CAL 0 -> always
        a0e = self.a0e.set(lut1d_signed_yu(*self.t_idx, self.a22.get()))              # 0x8005F138
        t = ld_hu(self.idx.get()) - ld_hu(a0e)
        a0c = self.a0c.set(0x7FFF if t > 0x7FFF else (-0x8000 if t < -0x8000 else s16(t)))
        if direct:
            fa = ssub16(f8, acc)
        else:                                                                         # unreachable while CAL = 0
            t = ld_hu(self.k_q15) * a0c
            fa = 0x7FFF if t > 0x3FFF8000 else (-0x8000 if t < -0x40000000 else s16(t >> 15))
        self.fa.set(fa)
        self.fc.set(fa if moving else self.k_ehi)
        self.prev_acc.set(acc)                                                        # 8007566A


class _Term(Block):
    """The shared PI shape of AccelTermNeg (800750E8 tail) and AccelTermPos (0x8007566E)."""

    def __init__(self, ctx, side):
        super().__init__(ctx)
        V = self.v
        self.side = side
        self.a22, self.a06 = V("AccelTorque"), V("AccelJerk")
        self.en = V("AccelPosEnable" if side == "Pos" else "AccelNegEnable")
        self.err = V("AccelErrLo" if side == "Pos" else "AccelErrHi")
        self.st, self.iir = V("Accel%sJerkIirAcc" % side), V("Accel%sJerkIir" % side)
        self.p, self.e_t, self.integ, self.i_t = (V("Accel%sP" % side), V("Accel%sErrTerm" % side),
                                                  V("Accel%sInteg" % side), V("Accel%sI" % side))
        self.out = V("AccelTerm%s" % side)
        self.k_iir = self.k("CalAccelJerkIirCoeff")
        self.k_p, self.k_i, self.k_e = (self.k("CalAccel%sJerkGain" % side), self.k("CalAccel%sIntegGain" % side),
                                        self.k("CalAccel%sErrGain" % side))

    def run(self):
        d3 = s16(-self.a22.get())
        en = self.en.get()
        if not en:
            st = 0
        else:
            st = s32(self.st.get() + s32((self.a06.get() - (self.st.get() >> 14)) * self.k_iir))
        self.st.set(st)
        self.iir.set(s16(st >> 14))
        p = self.p.set(satdiv(self.iir.get() * self.k_p, 1280))
        e = self.err.get()
        et = self.e_t.set(satdiv(e * self.k_e, 1280))
        d5 = sadd16(p, et)
        if en:
            inc = satdiv(self.k_i * e, 1600)
            cand = s32(self.integ.get() + inc)
            aw = s32(ssub16(d3, d5) * 0x50)
            if self.side == "Neg":
                I = max(aw, cand)                                          # 80075312
                I = 0 if I >= 1 else I                                     # I in [aw, 0]
            else:
                I = min(aw, cand)                                          # 80075824
                I = 0 if I < 0 else I                                      # I in [0, aw]
        else:
            I = 0
        self.integ.set(I)
        it = self.i_t.set(s16(div_trunc(I, 80)))
        if not en:
            self.out.set(0)
        elif self.side == "Neg":
            y = max(sadd16(d5, it), d3)                                    # never beyond -torque
            self.out.set(y if y < 0 else 0)
        else:
            y = s16(it + d5)
            if d5 >= 0 and y < 0:
                y = 0x7FFF                                                 # one-sided: d5's sign only
            y = min(y, d3)
            self.out.set(y if y >= 1 else 0)


class AccelLimiter(Block):
    """FUN_800750E8: enables from the PREVIOUS tick's terms, then Pos (0x8007566E), then Neg."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.y7a, self.a22 = V("TrqIir7aOut"), V("AccelTorque")
        self.tn, self.tp = V("AccelTermNeg"), V("AccelTermPos")
        self.a04, self.fc = V("AccelErrLo"), V("AccelErrHi")
        self.pos_en, self.neg_en = V("AccelPosEnable"), V("AccelNegEnable")
        self.k_neg, self.k_pos = self.k("CalAccelNegEnable"), self.k("CalAccelPosEnable")
        self.bounds, self.pos, self.neg = AccelBounds(ctx), _Term(ctx, "Pos"), _Term(ctx, "Neg")

    def run(self):
        a22 = self.a22.set(self.y7a.get())                                 # 800750F6
        neg_torque = a22 < 0
        pos_was_on = self.tp.get() >= 1                                    # previous tick's AccelTermPos
        self.bounds.run()                                                  # 0x80075394
        self.pos_en.set(1 if (neg_torque and (pos_was_on or self.a04.get() >= 1) and self.k_pos != 0) else 0)
        self.neg_en.set(1 if (self.k_neg != 0 and a22 >= 1 and (self.tn.get() < 0 or self.fc.get() < 0)) else 0)
        self.pos.run()                                                     # 0x8007566E
        self.neg.run()                                                     # 0x8007515C..
