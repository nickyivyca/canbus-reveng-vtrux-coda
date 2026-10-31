"""Publish10ms 0x80074780: the mirror words the COM layer packs into frames.

Source: full_listing.txt 0x8007478E..0x800749B0. Of the three calls at its head, 0x80074AC8 and
0x800749B2 are not ported, nor is the 0x260c word. TrqPublishComparand 0x80074A06 is ported for its
0xD00069D0 write only (0x80074AB2..0x80074AC2), the MCM command word ECM2 monitors (spec C).
"""

from ..fixedpoint import u16, u32
from .base import Block

NIB = {5: 0xD, 10: 0xB, 20: 0x0, 40: 0x1}
ASC = {5: 0x50, 10: 0x52, 20: 0x4E, 40: 0x44}


def pack_torque(v):
    """u16(((v clamped to [-5000, 0x3C73]) * 0x3333) bits 15..30) + 0x7D0."""
    v = 0x3C73 if v > 0x3C73 else max(v, -0x1388)
    return u16(((u32(v * 0x3333) >> 15) & 0xFFFF) + 0x7D0)


class Publish10ms(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.bsw, self.pbsw = V("BrakeSwitch"), V("Pub212BrakeSw")
        self.pedal, self.pped = V("PedalInternal"), V("Pub210Pedal")
        self.g, self.g2 = V("GearCode"), V("GearCode2")
        self.nlo, self.nhi, self.prnd = V("Pub418GearNibLo"), V("Pub418GearNibHi"), V("Pub418Prnd")
        self.words = [(V("Pub312FbSrc"), V("Pub312FbRaw")), (V("Pub312MinSrc"), V("Pub312MinRaw")),
                      (V("Pub312MaxSrc"), V("Pub312MaxRaw"))]
        self.spd, self.p308 = V("MotorSpeedSignedX2"), V("Pub308SpeedRaw")
        self.src212, self.p212 = V("Pub212Src"), V("Pub212Raw")
        self.gated, self.comparand = V("McmCommandGated"), V("McmCommandWord")

    def run(self):
        self.comparand.set(u16(self.gated.get()) + 0x7D80)                 # 80074AB2..80074AC2 (st.h wraps)
        self.pbsw.set(self.bsw.get())
        self.pped.set((self.pedal.get() * 0x33333) >> 0x17)
        self.nhi.set(NIB.get(self.g2.get(), 0xF))
        self.prnd.set(ASC.get(self.g.get(), 0xFF))
        self.nlo.set(NIB.get(self.g.get(), 0xF))
        for src, dst in self.words:
            dst.set(pack_torque(src.get()))
        self.p308.set(self.spd.get() + 0x7D80)
        self.p212.set(pack_torque(self.src212.get()))
