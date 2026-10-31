"""Tick member 0x8006F870, the part that refreshes SpeedRaw from the M-CAN 0x20C RX buffer.

  DlcmTorqueTask10ms body starts at 0x8007C2C6 (0x8007C33A is a spurious ENTRY label mid-body).
  0x8007C2E6  call 0x8006F870   -> call 0x8006FD22 (NOT PORTED)
                                -> call 0x8006FAEA, at 0x8006FBCA..0x8006FBDE:
                 a0-0x27A2 0xD000685E = Can20CSpeedRead 0x8008075C()      (B0|B1 of the buffer)
                 a0-0x2796 0xD000686A = u16(0xD000685E) - 0x7D80           SpeedRaw (st.h, wraps)
              and at 0x8006FC36..0x8006FC6A (spec F 5.1, spec H 7.2):
                 0xD000685A = 0x20B B0|B1 ; 0xD0006868 Mcm20BW0 = s16(that - 0x7D80)
                 0xD0006866 = 0x20B B2|B3 ; 0xD000686E Mcm20BW1 = max(s16(that - 0x7D80), 0)
                                -> call 0x80070288, j 0x80070382 (NOT PORTED)
Everything else in 0x8006FAEA is NOT PORTED. Source: full_listing.txt.

ORDER: this member runs BEFORE TrqSpeedTask (called at 0x8007C346), so PROG and ECM2 (end of the
task) both see this tick's 0x20C buffer. Worklog 6H.68 corrects 6H.67.1, which had the refresh in
0x8006F17C after TrqSpeedTask.
"""

from ..fixedpoint import s16, u16
from .base import Block


class SpeedRxCopy(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.buf, self.raw, self.out = self.v("Can20CRxSpeedRaw"), self.v("SpeedRxRaw20C"), self.v("SpeedRaw")
        V = self.v
        self.b0, self.r0, self.w0 = V("Can20BRxW0"), V("Mcm20BRxW0Raw"), V("Mcm20BW0")
        self.b1, self.r1, self.w1 = V("Can20BRxW1"), V("Mcm20BRxW1Raw"), V("Mcm20BW1")

    def run(self):
        self.raw.set(self.buf.get())                                      # 0x8006FBCA..0x8006FBCE
        self.out.set(s16(u16(self.raw.get()) - 0x7D80))                   # 0x8006FBD0..0x8006FBDE
        self.r0.set(self.b0.get())                                        # 0x8006FC36..
        self.w0.set(s16(u16(self.r0.get()) - 0x7D80))                     # ..0x8006FC4A
        self.r1.set(self.b1.get())                                        # 0x8006FC4C..
        self.w1.set(max(s16(u16(self.r1.get()) - 0x7D80), 0))             # ..0x8006FC6A
