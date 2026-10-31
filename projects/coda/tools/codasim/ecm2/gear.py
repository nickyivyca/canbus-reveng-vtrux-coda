"""ECM2's gear state c11 and direction code c10 (gear-code block 0x8004B8D2, via 0x80049264).

c11 (Ecm2StateByteC11Writer 0x8004CBAC) is ECM2's own P/R/N/D machine, stepped by lever pulses that
ECM2 decodes from selector bytes on no logged bus (step-5 spec D). It is NOT PORTED: the model
SUBSTITUTES c11 = the snapshot of PROG GearCode2 (a0-0x9EE), a declared assumption printed in every
header. Spec D: equal in steady D (40) and R (10); at a reversal the firmware's c11 passes through
N (20) and may enter N earlier, and leave it later, than GearCode2.

c10 is transliterated (0x8004C060..0x8004C116): 2 if c11 == 40, 1 if c11 == 10, else a0-0x9EF
(the snapshot of 0xD00068C5 = (PROG GearLatch != 0) + 1).
"""

from ..dlcm.base import Block


class Ecm2GearState(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.gc2, self.c11 = self.v("Ecm2GearCode2Mirror_9ee"), self.v("Ecm2GearState_c11")
        self.fb, self.c10 = self.v("Ecm2GearFallback_9ef"), self.v("Ecm2GearCode_c10")
        self.sD, self.sR = self.k("Ecm2GearStateD"), self.k("Ecm2GearStateR")
        self.gD, self.gR = self.k("Ecm2GearCodeD"), self.k("Ecm2GearCodeR")

    def run(self):
        self.c11.set(self.gc2.get())                                      # SUBSTITUTE for 0x8004CBAC
        c11 = self.c11.get()
        self.c10.set(self.gD if c11 == self.sD else (self.gR if c11 == self.sR else self.fb.get()))
