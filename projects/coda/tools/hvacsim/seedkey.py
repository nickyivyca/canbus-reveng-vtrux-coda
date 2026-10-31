"""SecurityAccess key computation: SeedToKey (0x7E5853), called by the 0x27 handler (0x7F8D93).

The handler pushes the 32-bit seed (RAM 0x2A20 for levels 03/04, 0x2A24 for 01/02) and
passes a per-level constant in X:D. SeedToKey XORs the two, then runs 48 rounds of a
left-shifting 32-bit LFSR whose feedback bit is bit29 ^ bit20 ^ bit11 ^ bit4 of the
state before the shift (the runtime helper 0x7FC8DD does the right shifts). The result
returns in X:D and is compared byte by byte with the tester's key.

    key(0x6E760729, LEVEL_03) -> 0xBE7B5888

Constants are the immediates loaded at 0x7F9022/0x7F9025 (level 03/04) and
0x7F8E8E/0x7F8E91 (level 01/02).
"""

from .fixedpoint import u32

LEVEL_01 = 0xF0EF3607
LEVEL_03 = 0x4F7B7C79
ROUNDS = 0x30


def key(seed, const):
    s = u32(seed ^ const)
    for _ in range(ROUNDS):
        fb = ((s >> 29) ^ (s >> 20) ^ (s >> 11) ^ (s >> 4)) & 1
        s = u32((s << 1) | fb)
    return s
