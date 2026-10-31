"""Ecm2InputSnapshot 0x80054274..0x800548E0: PROG -> ECM2 copies, once per ECM2 tick.
Source: full_listing.txt; step-5 spec B s4. Only the copies on the reason-12 chain are ported;
the rest of the table (12 bytes 0xD0005054.., 0xD000690F, 0xD0006910, 0xD0005034, 0xD000511A,
0xD000689F, 0xD0006898..9B) and the sub-checks 0x800548EC / 0x80054B38 / 0x80054DE8 are NOT PORTED.
"""

from ..dlcm.base import Block

# (destination, source, how) in listing order; how = "copy" or "eq1"
COPIES = [
    ("Ecm2CreepMirror_a18", "CreepOut", "copy"),                       # 0x800545D0
    ("Ecm2GearFallback_9ef", "TrqGateGearLatchCode", "copy"),          # u8 0xD00068C5
    ("Ecm2ComparandMirror", "McmCommandWord", "copy"),                 # 0x80054628 (unconditional)
    ("Ecm2GearCode2Mirror_9ee", "GearCode2", "copy"),
    ("Ecm2DemandMirror_a14", "DemandClampedGated", "copy"),            # 0x8005474C
    ("Ecm2SpeedInvalidMirror", "SpeedInvalid", "eq1"),                 # (u8 0xD0006A47 == 1)
]


class Ecm2InputSnapshot(Block):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.copies = [(self.v(d), self.v(s), how) for d, s, how in COPIES]

    def run(self):
        for d, s, how in self.copies:
            d.set(s.get() if how == "copy" else (1 if s.get() == 1 else 0))
