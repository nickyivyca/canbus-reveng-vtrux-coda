"""The ECM2 reaction, as far as a candidate screen needs it: FUN_800552BC ->
Ecm2SafetyDisableOrChain 0x80055A3E -> Ecm2ReasonCodeAssigner 0x800561E0 -> FUN_800569CC ->
SoftwareReset 0x8008CC60(0xA2). Source: full_listing.txt; step-5 spec C s3.

One debounced reason flag resets the module IN THE SAME TICK while the occurrence count is
below CAL 0xA0021D8C (= 7). The user's rule (2026-10-09): a reset on a candidate profile rejects
it, so recovery is not modelled -- the reset is reported (tick, reason code) and the caller stops.

Reason flags: 10, 11, 12 and 15 (reason15.py, lash session 2026-10-27) are computed by ported blocks; every other reason is NOT PORTED and
held 0 (listed by the controller header). The count restore (first tick after boot), the
mirror to reset-surviving RAM and the permanent shut-off stage are not modelled.
"""

from ..dlcm.base import Block

# priority order of Ecm2ReasonCodeAssigner (sites 0x800563A2..0x800567B8): code -> flag name
REASONS = [(1, None), (2, None), (3, None), (4, None), (5, None), (6, None), (7, None), (8, None),
           (9, None), (10, "Ecm2Reason10Flag"), (11, "Ecm2Reason11Flag"), (12, "Ecm2Reason12Flag"),
           (13, None), (14, None), (15, "Ecm2Reason15Flag"), (16, None)]
P3116_GROUP = {4, 13, 16}


class Ecm2Reaction(Block):
    def __init__(self, ctx, on_reset):
        super().__init__(ctx)
        self.on_reset = on_reset
        self.flags = [(c, self.v(n) if n else None) for c, n in REASONS]
        self.count, self.code, self.gate, self.prev = (self.v("Ecm2ReactionCount"), self.v("Ecm2ReasonCode"),
                                                       self.v("Ecm2ResetGate_9bb"), self.v("Ecm2ResetGatePrev_9b1"))
        self.cap, self.cap_p3116 = self.k("CalEcm2ReactionCap"), self.k("CalEcm2ReactionCapP3116")

    def run(self):
        cnt = self.count.get()
        self.code.set(0)                                                  # 80055CD6
        active = {c for c, f in self.flags if f is not None and f.get()}
        a = bool(active & P3116_GROUP)
        b5 = a and cnt >= self.cap_p3116                                  # (+ a0-0xd20, not ported)
        b = bool(active - P3116_GROUP)
        b6 = b or (a and cnt < self.cap_p3116)
        if not (b6 and not b5 and cnt < self.cap):                        # 80056172..80056188
            return
        code = min(active)                                                # priority encoder
        self.code.set(code)
        self.gate.set(1 if code > 0 else 0)                               # 80056806
        if self.gate.get() == 1 and self.prev.get() == 0:
            self.count.set(min(cnt + 1, 255))                             # 8005685C add ; sat.bu
        self.prev.set(self.gate.get())                                    # 80056884
        if self.gate.get() == 1:                                          # 80055418 -> 0x800569CC
            self.on_reset(code)
