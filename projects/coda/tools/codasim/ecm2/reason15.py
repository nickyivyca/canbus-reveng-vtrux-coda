"""ECM2 reason 15 and the band it is enabled by.  Written by the lash session, 2026-10-27 (user: "decompile/model it
... and add to the sim"); traced in worklog 6H.36-6H.47, transliterated here from full_listing.txt:

  Ecm2LimiterOutputConsumer 0x800512AA..0x80051B82 (tick dispatcher, after the slew limiter):
    b4a = aad == 1 ? b8c : -max(b8c, 0)                                       0x800514E0..0x8005153C
    spd = |E6| (guarded abs)
    b4c = sat16(b4a - LutB(0x80040980)[spd])                                  0x800515B6..0x800515D2
    b42 = CAL 0xA0021D82 (1508) ? sat16(div_trunc(CAL * b4c, 2560)) : 0      0x800515EC..0x80051658
    b48 = sat16(max(B, 0) + Lut2d(0x80040A40)[spd, spd])                      0x80051672..0x800516EE
          B = b42, or b4c when the CAL is 0 (the register is not reloaded on that path)
    b46 = sat16(min(b42, 0) + LutB(0x8004098C)[spd])                          0x8005170E..0x800517B2
    ab0 = debounce( (b44 < spd && spd < CAL 0xA0021D80) || b48 < E4 )  > CAL 0xA0021D86 (75)    0x8005195C
    aaf = debounce( !(CAL 0xA0021D84 < ca8 || c68) && E4 < b46 && spd >= CAL 0xA0021D80 ) > CAL 0xA0021D88 (75)
                                                                                                  0x80051B40
      NOTE: the brake gate on aaf (ca8 > 5 or the switch) is in the listing at 0x800519A2..0x800519D2 and is not
      in worklog 6H.37.7's summary of this condition.
    CAL 0xA0021D80 = 0 in stock, C4c, f7 and the candidates, so the b44 term (a0-0xce4, untraced) cannot be true and
    aaf's speed term always is; the port refuses an image where it is not 0.
  Inside Ecm2Reason12And14Detector 0x80056C20 (after reason 12):
    99c = c11 == Ecm2GearStateR ? CAL 0xA0021CE8 (6400) : CAL 0xA0021CEA (17536)    0x800570E8..0x80057122
    968 = 99c < spd                                                            0x800571B0 (an over-speed flag)
    967 = the six-term OR of 6H.44.1                                           0x800573A0   MODELLED 0, see below
    96f = 967 || 968 || aad == 0 || ab0                                        0x800573BE..0x8005743A
    96e = 967 || aaf || aae                                                    0x80057458..0x800574C4
  Ecm2Reason15And16Detector 0x80057CDE (called at 0x800574E2):
    channel A 0x8005821C runs only while 96e == 1, channel B 0x800584A6 only while 96f == 1; each refreshes its term
    (held otherwise):  n = aad == 1 ? a16 : u16(0x7D80 - (a16 - 0x7D80))
                       96d = n <u 0x7D80 (A)        96a = 0x7D80 <u n (B)
    cond15 = (96e && 96d) || (96f && 96a); counter a0-0x982; flag = CAL 0xA0021CE2 (100) < counter   0x80057FD0
  Reason 16 (the same detector's leaky counter, P3116) is NOT ported.

ASSUMPTION, not a reading: a0-0x967 is modelled as 0.  Four of its six terms bottom out at controller-side bytes
this image cannot name further (6H.44, 6H.47.6).  If it were 1 in normal running, channel A would be enabled
permanently and any regen held for more than 1 s with the direction flag set would raise reason 15; the corpus
replays show no such resets, so 0 is the only value consistent with them.  It is an assumption all the same.
"""

from ..dlcm.base import Block
from ..fixedpoint import s16, sat_s16, u16, div_trunc
from ..lut import lut1d_unsigned, lut2d
from .common import abs16, debounce

CH_A_OR_967 = 0          # the assumption above


class Ecm2LimiterOutputConsumer(Block):
    """0x800512AA..0x80051B82: the band [b46, b48] around ECM2's torque-predicted rate, and its two exits."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.aad, self.b8c, self.e6, self.e4 = (V("Ecm2DirectionAgree_aad"), V("Ecm2Allowance_b8c"),
                                                V("Ecm2SpeedFiltScaled"), V("Ecm2SpeedRateFilt"))
        self.ca8, self.c68 = V("Ecm2BrakePressure_ca8"), V("Ecm2BrakeSwitch_c68")
        self.b4a, self.b4c, self.b42 = V("Ecm2BandCentreIn_b4a"), V("Ecm2BandCentreLess_b4c"), V("Ecm2BandCentre_b42")
        self.b48, self.b46 = V("Ecm2BandHi_b48"), V("Ecm2BandLo_b46")
        self.cab, self.cbe = V("Ecm2BandAboveCnt_ad0"), V("Ecm2BandBelowCnt_acc")
        self.ab0, self.aaf = V("Ecm2BandAbove_ab0"), V("Ecm2BandBelow_aaf")
        self.t_ctr, self.t_lo, self.t_hi = (self.t1("DescEcm2BandCentreOffset"), self.t1("DescEcm2BandLoTol"),
                                            self.t2("DescEcm2BandHiTol"))
        self.gain, self.bgate = self.k("CalEcm2BandGain"), self.k("CalEcm2BandBrakeGate")
        self.dab, self.dbe = self.k("CalEcm2BandAboveDebounce"), self.k("CalEcm2BandBelowDebounce")
        self.sgate = self.k("CalEcm2BandSpeedGate")
        if self.sgate != 0:
            raise NotImplementedError("CalEcm2BandSpeedGate != 0: the b44 / a0-0xce4 term is not ported")

    def run(self):
        b8c = self.b8c.get()
        b4a = b8c if self.aad.get() == 1 else s16(-s16(max(b8c, 0)))          # 0x8005151A..0x80051538
        self.b4a.set(b4a)
        spd = abs16(self.e6.get())
        spd = spd if spd >= 1 else 0                                           # 0x800515A0
        b4c = sat_s16(b4a - lut1d_unsigned(*self.t_ctr, spd))                  # 0x800515B6..0x800515C6
        self.b4c.set(b4c)
        if self.gain:
            b42 = sat_s16(div_trunc(self.gain * b4c, 0xA00))                   # 0x80051610..0x8005164C
            d8 = b42
        else:
            b42, d8 = 0, b4c                                                   # 0x800515F6..: d8 not reloaded
        self.b42.set(b42)
        b48 = sat_s16(max(d8, 0) + lut2d(*self.t_hi, spd, spd))                # 0x80051678..0x800516E8
        self.b48.set(b48)
        b46 = sat_s16(min(b42, 0) + lut1d_unsigned(*self.t_lo, spd))           # 0x80051732..0x800517AC
        self.b46.set(b46)
        e4 = self.e4.get()
        above = b48 < e4                                                       # 0x800518A0 (b44 term: CAL 0 -> false)
        self.ab0.set(1 if self.dab < debounce(above, self.cab) else 0)         # 0x800518AE..0x8005195C
        gate = not (self.bgate < u16(self.ca8.get()) or self.c68.get())        # 0x800519A2..0x800519D2
        below = gate and e4 < b46 and spd >= self.sgate                       # 0x80051A20..0x80051A8E
        self.aaf.set(1 if self.dbe < debounce(below, self.cbe) else 0)         # 0x80051A92..0x80051B40


class Ecm2Reason15(Block):
    """The enables (inside 0x80056C20) and Ecm2Reason15And16Detector's reason-15 half."""

    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.aad, self.e6, self.c11, self.a16 = (V("Ecm2DirectionAgree_aad"), V("Ecm2SpeedFiltScaled"),
                                                 V("Ecm2GearState_c11"), V("Ecm2ComparandMirror"))
        self.ab0, self.aaf, self.aae = V("Ecm2BandAbove_ab0"), V("Ecm2BandBelow_aaf"), V("Ecm2EnableTerm_aae")
        self.l99c, self.f968, self.f967 = V("Ecm2OverSpeedLim_99c"), V("Ecm2OverSpeed_968"), V("Ecm2Ch15AOr_967")
        self.en_b, self.en_a = V("Ecm2Ch15BEnable_96f"), V("Ecm2Ch15AEnable_96e")
        self.n_a, self.n_b = V("Ecm2Ch15ANorm_9a0"), V("Ecm2Ch15BNorm_99e")
        self.t_a, self.t_b = V("Ecm2Ch15ATerm_96d"), V("Ecm2Ch15BTerm_96a")
        self.cnt, self.flag = V("Ecm2Reason15Cnt"), V("Ecm2Reason15Flag")
        self.gR = self.k("Ecm2GearStateR")
        self.lim_r, self.lim_d = self.k("CalEcm2OverSpeedR"), self.k("CalEcm2OverSpeedD")
        self.deb = self.k("CalEcm2Reason15Debounce")

    def _norm(self):
        a = u16(self.a16.get())
        return a if self.aad.get() == 1 else u16(0x7D80 - (a - 0x7D80))       # 0x80058356..0x80058364

    def run(self):
        lim = self.lim_r if self.c11.get() == self.gR else self.lim_d           # 0x800570D6..0x80057122
        self.l99c.set(lim)
        f968 = 1 if lim < abs16(self.e6.get()) else 0                          # 0x800571B0
        self.f968.set(f968)
        self.f967.set(CH_A_OR_967)                                             # 0x800573A0 (assumption)
        en_b = 1 if (CH_A_OR_967 or f968 or self.aad.get() == 0 or self.ab0.get()) else 0
        self.en_b.set(en_b)                                                    # 0x8005743A
        en_a = 1 if (CH_A_OR_967 or self.aaf.get() or self.aae.get()) else 0
        self.en_a.set(en_a)                                                    # 0x800574C4
        if en_a == 1:                                                          # 0x80057E62 -> 0x8005821C
            n = self._norm()
            self.n_a.set(n)
            self.t_a.set(1 if n < 0x7D80 else 0)                               # 0x80058390
        if en_b == 1:                                                          # 0x80057E88 -> 0x800584A6
            n = self._norm()
            self.n_b.set(n)
            self.t_b.set(1 if 0x7D80 < n else 0)                               # 0x8005861A
        cond = (en_a and self.t_a.get()) or (en_b and self.t_b.get())          # 0x80057E90..0x80057F1E
        c = debounce(bool(cond), self.cnt)                                     # 0x80057F22..0x80057FC4
        self.flag.set(1 if cond and self.deb < c else 0)                       # 0x80057F9A..0x80057FD0
