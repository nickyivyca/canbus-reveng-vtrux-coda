"""GearLatchAndSpeedFlags 0x800722FE (tail of the gear task 0x80071608).

Source: ghidra_flash7/creep_flag_fns.txt. The gear state machine that runs
before it in 0x80071608 (0x8007162E, 0x8007214C, 0x800719B8 -> GearCode,
GearCode2) is NOT PORTED: the gear codes enter as a reversed input from 0x418
GearStatus (io/inputs), which carries both codes exactly.
"""

from .base import Block


class GearLatchAndSpeedFlags(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.g2, self.latch, self.spd = self.v("GearCode2"), self.v("GearLatch"), self.v("MotorSpeedSignedX2")
        self.cf, self.cr = self.v("DirFwdCount"), self.v("DirRevCount")
        self.ff, self.fr, self.out = self.v("DirFwdFlag"), self.v("DirRevFlag"), self.v("MovingInGearDir")
        self.D, self.R = self.k("ProgGearCodeD"), self.k("ProgGearCodeR")
        self.fclr, self.fset = self.k("CalDirFwdClear"), self.k("CalDirFwdSet")
        self.rclr, self.rset = self.k("CalDirRevClear"), self.k("CalDirRevSet")
        self.deb = self.k("CalDirDebounce")

    @staticmethod
    def _inc(c):
        return 0xFFFF if c == 0xFFFF else c + 1

    def run(self):
        g = self.g2.get()                                  # a0-0x3f52 = GearCode2
        if g == self.D:
            self.latch.set(1)
        elif g == self.R:
            self.latch.set(0)
        v = self.spd.get()
        b3, b2 = v <= self.fset, v < self.fclr
        old = self.cf.get()
        self.cf.set(self._inc(old) if b2 else 0)
        b7 = self.deb <= old and b2
        if not b3 and not b7:
            self.ff.set(1)
        elif b7:
            self.ff.set(0)
        b3, b2 = v < self.rset, self.rclr < v
        old = self.cr.get()
        self.cr.set(self._inc(old) if b2 else 0)
        x = self.deb <= old and b2
        if b3 and not x:
            self.fr.set(1)
        elif x:
            self.fr.set(0)
        lat = self.latch.get() != 0
        self.out.set((lat and self.ff.get() != 0) or (not lat and self.fr.get() != 0))
