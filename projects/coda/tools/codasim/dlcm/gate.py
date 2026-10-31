"""Tick member 0x800704AC: the RunState gate on the MCM command, which ECM2 monitors.

  0x800704AC  call TrqGateFlagWriter 0x80070B7A   ported: first write only (a0-0x2735)
              call 0x80070AAA                     NOT PORTED (role unknown)
              call TrqGateComparand 0x80070AD4    ported in full
              (0x800704B8.. continues)            NOT PORTED

Source: full_listing.txt 0x800704AC..0x800704B8, 0x80070AD4..0x80070B78, 0x80070B7A..0x80070B96;
worklog 6H.9. 0xD00068C0 = McmCommand while RunState == 5, else 0; Publish adds 0x7D80 to form
0xD00069D0, the word ECM2's reason 12 compares (step-5 spec C).
"""

from .base import Block


class TrqGateFlagWriter(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.rs, self.flag = self.v("RunState"), self.v("TrqGateFlag")
        self.active = self.k("ProgRunStateActive")

    def run(self):
        self.flag.set(1 if self.rs.get() == self.active else 0)           # 80070B92..80070B96


class TrqGateComparand(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        V = self.v
        self.cmd, self.cnt, self.flag = V("McmCommand"), V("McmCommandZeroCnt"), V("TrqGateFlag")
        self.ok, self.latch_in, self.gl = V("TrqGateCmdOk"), V("TrqGateGearLatch"), V("GearLatch")
        self.out, self.code_gl, self.code_ok = V("McmCommandGated"), V("TrqGateGearLatchCode"), V("TrqGateCmdOkCode")
        self.kcnt = self.k("CalMcmCommandZeroDebounce")

    def run(self):
        d0 = self.cmd.get()                                               # 80070ADC ld.h
        zero = d0 == 0
        old = self.cnt.get()
        self.cnt.set((old + 1 if old < 0xFFFF else 0xFFFF) if zero else 0)   # 80070AE6..80070B20
        long_zero = zero and not (old < self.kcnt)                        # 80070B1A jlt.u ; cmov
        gate = self.flag.get() != 0                                       # 80070B2A
        self.ok.set(1 if gate and not long_zero else 0)                   # 80070B2E..80070B38
        self.latch_in.set(self.gl.get())                                  # 80070B3A..80070B48
        self.out.set(d0 if gate else 0)                                   # 80070B4A..80070B5A
        self.code_gl.set((1 if self.latch_in.get() != 0 else 0) + 1)      # 80070B5C..80070B68
        self.code_ok.set((1 if self.ok.get() != 0 else 0) + 1)            # 80070B6A..80070B76


class TickMember800704AC(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.parts = [TrqGateFlagWriter(ctx), TrqGateComparand(ctx)]

    def run(self):
        for p in self.parts:
            p.run()
