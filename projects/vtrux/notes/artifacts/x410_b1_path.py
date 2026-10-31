"""Trace the 0x410 B1 byte through a fault trip.

`notes/fault-signature-comparison.md` claims B1's *lower nibble* clearing
during shutdown (0xB0 / 0xF0 / 0xC0) is the isolation fault's unique tell,
while every other mode keeps the lower nibble at F and goes straight to 0xCF.
If that holds it is a *persistent, post-hoc* discriminator -- i.e. isolation
can be identified from the latched state without catching the 146 ms edge.

B1 layout per the app DBC: bits 7-6 = bcm_alarm, bits 3-0 = bcm_gfd's high
nibble (bcm_gfd is 11|12@0+, so B1[3:0]:B2).
"""
import sys
sys.path.insert(0, ".")

from pathlib import Path

from canre.parsers import parse_file

ALARM = {0: "NONE", 1: "TYPE1", 2: "TYPE2", 3: "TYPE3"}

for path in sys.argv[1:]:
    print(f"\n# {Path(path).name}")
    print(f"{'t(s)':>9}  {'B0':>4} {'B1':>4}  epo hvil  alarm  gfd")
    prev = None
    for frame in parse_file(Path(path)):
        if frame.arbitration_id != 0x410 or len(frame.data) < 3:
            continue
        b0, b1, b2 = frame.data[0], frame.data[1], frame.data[2]
        key = (b0, b1)
        if key == prev:
            continue
        prev = key
        gfd = (((b1 & 0x0F) << 8) | b2) * 0.25
        print(f"{frame.timestamp:9.3f}  0x{b0:02X} 0x{b1:02X}  "
              f"{(b0 >> 1) & 1:^3} {(b0 >> 3) & 1:^4}  "
              f"{ALARM[(b1 >> 6) & 3]:<6} {gfd:7.1f}")
