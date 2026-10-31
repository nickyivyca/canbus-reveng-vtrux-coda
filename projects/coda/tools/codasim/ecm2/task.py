"""Ecm2Task FUN_800463B8: ECM2, called once per DlcmTorqueTask10ms tick at 0x8007C4DA -- after
Publish10ms has written 0xD00069D0 and before the COM pack 0x80080C14, so reason 12 compares THIS
tick's command (step-5 spec C s1). Order, as listed at 0x800463B8..0x8004647A:

  0x80046484  APP/pedal inputs, reason 1          NOT PORTED (pedal ce4 substituted, see controller)
  0x80054274  Ecm2InputSnapshot                   ported (chain copies)
  0x8005872C  Ecm2SpeedFilterAndScale             ported (reason 3 fault logic not)
  0x80047EFC  Ecm2Can300ProtectedRead             ported (chain outputs; c63/c65 inputs)
  0x800526EC, 0x8004D80C                          NOT PORTED (not on the reason-12 chain)
  0x80049264  gear-code block -> c11, c10         c10 ported, c11 SUBSTITUTED (gear.py)
  0x80053B28  reason 9                            NOT PORTED
  0x8004DE28 -> Ecm2TickDispatcher 0x8004DE30:
     0x8004DEDE limits, 0x8004EEA2 reason 10 / b70, 0x80050246 reason 11 / b64,
     0x80051B92 slew limiter -> b8c               ported
     0x800512AA limiter output consumer -> band b46/b48, aaf, ab0   ported (lash session, reason15.py)
  0x80056C20  reason 12, and reason 15 with its enables (13, 14, 16 not)   ported (15: reason15.py)
  0x800552BC  reaction                            ported to the reset decision
  0x800550D8  shut-off output stage               not modelled (no recovery, user 2026-10-09)
"""

from ..dlcm.base import Block
from .canread import Ecm2Can300ProtectedRead
from .gear import Ecm2GearState
from .limiter import Ecm2SlewRateLimiter
from .limits import Ecm2EnableAndOuterClampWriter
from .reaction import Ecm2Reaction
from .reason12 import Ecm2Reason12
from .snapshot import Ecm2InputSnapshot
from .speed import Ecm2SpeedFilterAndScale
from .target import Ecm2Reason10Detector, Ecm2Reason11Detector
from .reason15 import Ecm2LimiterOutputConsumer, Ecm2Reason15


class Ecm2Task(Block):
    def __init__(self, ctx, on_reset):
        super().__init__(ctx)
        self.blocks = [Ecm2InputSnapshot(ctx), Ecm2SpeedFilterAndScale(ctx), Ecm2Can300ProtectedRead(ctx),
                       Ecm2GearState(ctx), Ecm2EnableAndOuterClampWriter(ctx), Ecm2Reason10Detector(ctx),
                       Ecm2Reason11Detector(ctx), Ecm2SlewRateLimiter(ctx), Ecm2LimiterOutputConsumer(ctx),
                       Ecm2Reason12(ctx), Ecm2Reason15(ctx), Ecm2Reaction(ctx, on_reset)]

    def run(self):
        for b in self.blocks:
            b.run()
