"""DemandTask 0x8007766C = AppLossLatch 0x800778DE; TrqRawDemandWriter 0x80077676; DemandClampGate 0x8007787E.

Source: instruction listings (dlcm_export/demand_fn.txt, full_listing.txt).
Differences from torque_path_sim/DlcmLoop, all from the listing:
  - the map speed is SpeedIndex only while ClampBoundFlag is set, else 0;
  - the APP-loss latch selects the speed-only / flag-brake maps (DlcmLoop assumed clear);
  - R maps need GearCode == GearCode2 == 10; demand is 0 in gear codes 5 and 20;
  - integer lookups, with the firmware's entry points (0x8005F3DA 2-D, 0x8005F082 1-D).
"""

from ..lut import lut1d_signed, lut2d
from ..fixedpoint import ld_h, ld_hu
from .base import Block


class AppLossLatch(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.c1d, self.c2d = self.v("AppCh1Digital"), self.v("AppCh2Digital")
        self.n1, self.n2 = self.v("AppLossSetCounter"), self.v("AppLossClearCounter")
        self.pedal, self.flag = self.v("PedalInternal"), self.v("AppLossLimpHome")
        self.k_set, self.k_clr = self.k("CalAppLossSetDebounce"), self.k("CalAppLossClearDebounce")
        self.k_ped = self.k("CalAppLossClearPedalMax")

    def run(self):
        either = self.c1d.get() != 0 or self.c2d.get() != 0
        cond1 = not either
        old = self.n1.get()
        self.n1.set((0xFFFF if old == 0xFFFF else old + 1) if cond1 else 0)
        deb1 = cond1 and old >= self.k_set
        cond2 = either and self.pedal.get() <= self.k_ped
        old = self.n2.get()
        self.n2.set((0xFFFF if old == 0xFFFF else old + 1) if cond2 else 0)
        deb2 = cond2 and old >= self.k_clr
        if deb1 and not deb2:
            self.flag.set(1)
        elif deb2:
            self.flag.set(0)


class TrqRawDemandWriter(Block):
    MAPS = {"D": ("DescDemandAppLossBrakeD", "DescDemandBrakeD", "DescDemandAppLossAccelD", "DescDemandPedalD"),
            "R": ("DescDemandAppLossBrakeR", "DescDemandBrakeR", "DescDemandAppLossAccelR", "DescDemandPedalR")}

    def __init__(self, ctx):
        super().__init__(ctx)
        self.f, self.a42, self.sidx = self.v("ClampBoundFlag"), self.v("SpeedIndex"), self.v("DemandSpeedIndex")
        self.g1, self.g2 = self.v("GearCode"), self.v("GearCode2")
        self.ba, self.bv, self.bsw = self.v("BrakeAnalog"), self.v("BrakeAnalogValid"), self.v("BrakeSwitch")
        self.pedal, self.app = self.v("PedalInternal"), self.v("AppLossLimpHome")
        self.out = self.v("TrqRawDemand")
        self.D, self.R = self.k("ProgGearCodeD"), self.k("ProgGearCodeR")
        self.c5, self.c20 = self.k("ProgGearCode5"), self.k("ProgGearCode20")
        self.bsw_is_brake = self.k("CalDemandBrakeSwitchIsBrake")
        self.override = self.k("CalDemandPedalOverride")
        self.tabs = {g: (self.t2(a), self.t2(b), self.t1(c), self.t2(d)) for g, (a, b, c, d) in self.MAPS.items()}

    def _one(self, g, spd):
        (bf, br, ac, pm) = self.tabs[g]
        b = self.ba.get() if self.bv.get() else 0                         # ld.hu, else 0
        y = ld_h(spd)
        s4 = lut2d(*bf, ld_hu(b), y)
        s5 = lut2d(*br, ld_hu(b), y)
        bsw = self.bsw.get() != 0 and self.bsw_is_brake != 0
        over = self.override <= self.pedal.get()                         # lt.u inverted
        s6 = lut1d_signed(*ac, y)
        s7 = lut2d(*pm, ld_hu(self.pedal.get()), y)
        app = self.app.get() != 0
        if (b == 0 and not bsw) or over:
            return s6 if app else s7
        return s4 if app else s5

    def run(self):
        spd = self.sidx.set(self.a42.get() if self.f.get() else 0)
        g1, g2 = self.g1.get(), self.g2.get()
        if g1 == self.D:
            self.out.set(self._one("D", spd))
        if g1 == self.R and g2 == self.R:
            self.out.set(self._one("R", spd))
        if g1 == self.c5 or g1 == self.c20 or g2 == self.c5:
            self.out.set(0)


class DemandClampGate(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.dem, self.lo, self.hi = self.v("TrqRawDemand"), self.v("ClampLo"), self.v("ClampHi")
        self.c, self.cg = self.v("DemandClamped"), self.v("DemandClampedGated")
        self.en, self.run_state = self.v("DemandEnable"), self.v("RunState")
        self.active = self.k("ProgRunStateActive")

    def run(self):
        d = max(min(self.dem.get(), self.hi.get()), self.lo.get())
        self.c.set(d)
        gate = self.en.get() != 0 and self.run_state.get() == self.active
        self.cg.set(d if gate else 0)


class DemandTask(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.parts = (AppLossLatch(ctx), TrqRawDemandWriter(ctx), DemandClampGate(ctx))

    def run(self):
        for p in self.parts:
            p.run()
