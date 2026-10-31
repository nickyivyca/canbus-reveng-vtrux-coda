"""The CPU emulator runs the firmware's own SeedToKey (0x7E5853) and must reproduce the
two SecurityAccess 27 03/04 seed/key pairs of the 2026-10-25 flash capture, and agree
with seedkey.key() on random seeds at both levels."""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from hvacsim.cpu import Cpu  # noqa: E402
from hvacsim.seedkey import LEVEL_01, LEVEL_03, key  # noqa: E402


def run_seedkey(seed, const):
    cpu = Cpu()
    cpu.sp = 0x2100
    cpu.push16(seed & 0xFFFF)
    cpu.push16(seed >> 16)
    cpu.d = const & 0xFFFF
    cpu.x = const >> 16
    cpu.call(0x7E5853)
    return (cpu.x << 16) | cpu.d


def test_capture_pairs():
    assert run_seedkey(0x6E760729, LEVEL_03) == 0xBE7B5888
    assert run_seedkey(0x12345678, LEVEL_03) == 0x58182FC9


def test_random_seeds():
    rnd = random.Random(1)
    for _ in range(10):
        s = rnd.getrandbits(32)
        for c in (LEVEL_01, LEVEL_03):
            assert run_seedkey(s, c) == key(s, c)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
