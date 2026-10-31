"""BoundsTask 0x8007689C: the bound chain, TrqClampBoundsRoleSwap 0x800768D6, the 0x312 sources.

Source: full_listing.txt 0x8007689C..0x800768D4, 0x800768D6..0x80076A16 (the
f == 0 store of 0xD0006ABA is out of line at 0x80076A0A).

The seven functions that compute the bound sources (0x80077598, 0x80076EC6,
0x80076DC2, 0x800774AA, 0x80076D72, 0x8007729A, 0x800771FA) are NOT PORTED yet
(plan step 6). Their outputs -- BoundSrcAB4/ACA (demand clamp) and
BoundSrcAA6/AC0 (final clamp) -- are written by whatever the controller is told
to use: a replayed 0x312 (REPLAYED_OUTPUT; rail-pinned on >= 50 % of frames,
worklog 6H.60) for AB4/ACA, and a declared assumption for AA6/AC0.
"""

from ..fixedpoint import s16
from .base import Block


class TrqClampBoundsRoleSwap(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.spd = self.v("MotorSpeedSignedX2")
        self.ca, self.cb = self.v("BoundCountFwd"), self.v("BoundCountRev")
        self.fa, self.fb = self.v("BoundFlagA"), self.v("BoundFlagB")
        self.latch, self.f = self.v("GearLatch"), self.v("ClampBoundFlag")
        self.aa0, self.aa2 = self.v("FinalClampLo"), self.v("FinalClampHi")
        self.aa6, self.ac0 = self.v("BoundSrcAA6"), self.v("BoundSrcAC0")
        self.ab8, self.aba = self.v("ClampLo"), self.v("ClampHi")
        self.ab4, self.aca = self.v("BoundSrcAB4"), self.v("BoundSrcACA")
        self.fwd, self.rev = self.k("CalBoundFwd"), self.k("CalBoundRev")
        self.deb = self.k("CalBoundDebounce")

    @staticmethod
    def _sat_inc(c):
        return 0xFFFF if c == 0xFFFF else c + 1

    def run(self):
        v = self.spd.get()
        below = v < self.fwd                                  # lt d0,d15,d0
        old = self.ca.get()
        self.fa.set((old < self.deb) or below)
        self.ca.set(0 if below else self._sat_inc(old))
        above = self.rev < v
        old = self.cb.get()
        self.fb.set((old < self.deb) or above)
        self.cb.set(0 if above else self._sat_inc(old))
        f = (self.fb.get() if self.latch.get() else self.fa.get()) != 0
        self.f.set(f)
        self.aa0.set(s16(-(self.aa6.get() if f else self.ac0.get())))
        self.aa2.set(self.ac0.get() if f else self.aa6.get())
        self.ab8.set(s16(-(self.ab4.get() if f else self.aca.get())))
        self.aba.set(self.aca.get() if f else self.ab4.get())


class BoundsTask(Block):
    """0x8007689C. `sources` is called where the seven unported functions run;
    it must write BoundSrcAB4/ACA/AA6/AC0 for this tick."""

    def __init__(self, ctx, sources):
        super().__init__(ctx)
        self.sources = sources
        self.swap = TrqClampBoundsRoleSwap(ctx)
        self.ab4, self.aca = self.v("BoundSrcAB4"), self.v("BoundSrcACA")
        self.p_min, self.p_max = self.v("Pub312MinSrc"), self.v("Pub312MaxSrc")

    def run(self):
        self.sources()
        self.swap.run()
        self.p_min.set(s16(-self.ab4.get()))
        self.p_max.set(self.aca.get())
