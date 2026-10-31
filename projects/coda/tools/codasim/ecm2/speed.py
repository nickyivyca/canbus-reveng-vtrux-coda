"""ECM2 speed chain: Ecm2Reason03Detector_AndSpeedChain 0x80058AE2 (speed path only) and
Ecm2SpeedFilterAndScale 0x8005872C..0x80058AD6. Source: full_listing.txt; step-5 spec B s3.

0xD00086EA (V)  = last valid (0x20C B0|B1 - 0x7D80), forced 0 while PROG SpeedInvalid.
0xD00086EC (EC) = 3-stage Q14 IIR of V (coeff 2458).
0xD00086E6 (E6) = sat16(trunc0(EC * 282 / 256)).
0xD00086E4      = 3-stage IIR (coeff 983) of 100 x the first difference of |V*282/256|.
Reason 3's fault logic (0x80058D56.., 0x800592B2..) is NOT ported; it does not write V.
"""

from ..dlcm.base import Block
from ..fixedpoint import s16, sat_s16
from .common import iir_q14


def _div256_trunc0(t):
    """caddn idiom: if t < 0 add 0xFF, then arithmetic >> 8 (truncation toward zero)."""
    return (t + 0xFF if t < 0 else t) >> 8


class Ecm2SpeedChain(Block):
    """0x80058AE2, the part that maintains a0-0x90e / a0-0x90c / a0-0x916 / a0-0x8a9."""

    def __init__(self, ctx):
        super().__init__(ctx)
        self.raw = self.v("Can20CRxSpeedRaw")
        self.s90e, self.s90c, self.out = self.v("Ecm2SpeedRx_90e"), self.v("Ecm2SpeedHeld_90c"), self.v("Ecm2Speed")
        self.inv, self.edge, self.prev = self.v("Ecm2SpeedInvalidMirror"), self.v("Ecm2SpeedInvEdge_8a9"), self.v("Ecm2SpeedInvPrev_8a1")
        self.e2e_a, self.e2e_b = self.v("Ecm2Speed20CCheckA_8ab"), self.v("Ecm2Speed20CCheckB_8ad")
        self.timeout = self.v("Can20CTimeout")
        self.lim = self.k("CalEcm2SpeedRange")

    def run(self):
        s = s16(self.raw.get() - 0x7D80)                                   # 80058CEE..80058CFE
        self.s90e.set(s)
        in_range = s < self.lim and -self.lim < s                          # 80058D1A..80058D3C
        valid = in_range and self.e2e_b.get() and self.e2e_a.get() and self.timeout.get() == 0
        if valid:                                                          # 80058FD0..800590AE
            self.s90c.set(s)
        inv = self.inv.get()
        self.out.set(self.s90c.get() if inv == 0 else 0)                   # 800590CA..80059136
        self.edge.set(1 if inv != self.prev.get() else 0)                  # 8005914E..800591C4
        self.prev.set(inv)                                                 # 800591D2


class Ecm2SpeedFilterAndScale(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.chain = Ecm2SpeedChain(ctx)
        self.v_, self.edge = self.v("Ecm2Speed"), self.v("Ecm2SpeedInvEdge_8a9")
        self.c1 = [self.v("Ecm2SpeedIir1Acc%d" % i) for i in (1, 2, 3)]
        self.c2 = [self.v("Ecm2SpeedRateIirAcc%d" % i) for i in (1, 2, 3)]
        self.ec, self.e6 = self.v("Ecm2SpeedFilt"), self.v("Ecm2SpeedFiltScaled")
        self.fc, self.e2, self.e4 = self.v("Ecm2SpeedAbsScaled"), self.v("Ecm2SpeedAbsPrev"), self.v("Ecm2SpeedRateFilt")
        self.g1, self.k1 = self.k("CalEcm2SpeedIirGain"), self.k("CalEcm2SpeedIirCoeff")
        self.scale = self.k("CalEcm2SpeedScale")
        self.g2, self.k2 = self.k("CalEcm2SpeedRateIirGain"), self.k("CalEcm2SpeedRateIirCoeff")

    def run(self):
        self.chain.run()                                                   # 800587EE
        x, ld = self.v_.get(), self.edge.get()
        y = x
        for st in self.c1:
            y = iir_q14(st, y, self.g1, ld, self.k1)
        self.ec.set(y)                                                     # 800588AE
        self.e6.set(sat_s16(_div256_trunc0(y * self.scale)))               # 800588D6..800588F0
        u = sat_s16(_div256_trunc0(x * self.scale))                        # 8005891C..80058934
        self.fc.set(0x7FFF if u == -0x8000 else abs(u))                    # 80058954
        if ld == 1:                                                        # 80058990: 8a9 == 1 -> 0
            d10 = 0
        else:
            d10 = sat_s16(100 * sat_s16(self.fc.get() - self.e2.get()))   # 800589D8..800589EA
            self.e2.set(self.fc.get())                                     # 800589F0
        z = d10
        for st in self.c2:
            z = iir_q14(st, z, self.g2, ld, self.k2)
        self.e4.set(z)                                                     # 80058A92
