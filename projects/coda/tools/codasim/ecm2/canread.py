"""Ecm2Can300ProtectedRead 0x80047EFC..0x800485EE: the parts on the reason-12 chain.
Source: full_listing.txt; step-5 specs A s7, B s1.1/s4.

0x208 (PDU 0xD0007FA0): brake12 = ((B2&0x0F)<<8)|B3, valid = B2 bit 4 (FUN_8008062E / 8008061C), read
  from the PDU buffer itself -- the same buffer PROG's FUN_8006ED3C copies to BrakeAnalog earlier in the
  same tick. The COM copy FUN_8008008C refreshes it once per tick at 0x8007C29A, before both reads
  (worklog 6H.73), so PROG and ECM2 always see the same 0x208 frame.
  c67 = brake12 != 0x0FFF and valid and 0x208 fresh     (0x8004812E, worklog 6H.56)
  ca8 = brake12 if c67 else 0                            (0x80048176)
c68 = port pin P1.14 (FUN_8007C55A) -- the hard-wired brake switch. SUBSTITUTED by PROG's copy of
  the same pin, BrakeSwitch 0xD0006831 (FUN_8006F110 reads it through the same FUN_8007C55A).
0x300 (PDU 0xD0007FA8): ca6 / ca4 = s16(u16(raw13*5 >> 1) - 5000) of B2-B3 / B4-B5; c64 = B4 bit 6;
  c63 = fresh && parity && alive (checks NOT transliterated; their result is an input here).
c65 (0x300 fault latch, FUN_800488C2) NOT PORTED: its set condition is partly traced.
"""

from ..dlcm.base import Block
from ..fixedpoint import s16, u16


class Ecm2Can300ProtectedRead(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.pdu208 = (self.v("Can208PduB2"), self.v("Can208PduB3"))
        self.fresh208 = self.v("Can208Timeout")
        self.sentinel = self.k("Can208BrakePressureInvalidSentinel")
        self.c67, self.ca8, self.ca0, self.ca2 = (self.v("Ecm2DownStepSelector_c67"), self.v("Ecm2BrakePressure_ca8"),
                                                  self.v("Ecm2BrakePressureRaw_ca0"), self.v("Ecm2BrakePressureRaw_ca2"))
        self.pin, self.c68 = self.v("BrakeSwitch"), self.v("Ecm2BrakeSwitch_c68")
        self.pdu = [self.v("Can300PduB%d" % i) for i in (2, 3, 4, 5)]
        self.ca6, self.ca4, self.c64 = self.v("Ecm2EspBrakingTqLimit_ca6"), self.v("Ecm2EspTractiveTqLimit_ca4"), self.v("Ecm2EspTractiveArmed_c64")

    def run(self):
        b2, b3 = (b.get() for b in self.pdu208)
        b12 = ((b2 << 8) & 0xF00) | b3                                     # 800480C6 (FUN_8008062E)
        vbit = (b2 & 0x10) >> 4                                            # FUN_8008061C
        self.ca2.set(b12)                                                  # 800480CE
        c67 = 1 if (b12 != self.sentinel and vbit and self.fresh208.get() == 0) else 0
        self.c67.set(c67)                                                  # 8004812E
        self.ca0.set(b12)                                                  # 8004814E
        self.ca8.set(b12 if c67 == 1 else 0)                               # 80048172..8004819C
        b2, b3, b4, b5 = (b.get() for b in self.pdu)
        raw_b = ((b2 & 0x1F) << 8) | b3                                    # Can300BrakingTqLimitRead 0x80080588
        self.ca6.set(s16(u16((raw_b * 5) >> 1) - 5000))                    # 8004820E..8004822E
        self.c64.set((b4 & 0x40) >> 6)                                     # Can300TractiveArmedRead 0x8008054E
        raw_t = ((b4 & 0x1F) << 8) | b5                                    # Can300TractiveTqLimitRead 0x80080572
        self.ca4.set(s16(u16((raw_t * 5) >> 1) - 5000))                    # 80048292..800482D8
        self.c68.set(self.pin.get())                                       # 800481B8..800481C8
