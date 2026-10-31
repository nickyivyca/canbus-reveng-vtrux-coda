"""SeedToKey against the two SecurityAccess 27 03/04 exchanges in the 2026-10-25 flash capture
(notes/hvac/flash_capture_20261025/coda_hvac_flash.log, 0x758 seed / 0x750 key frames)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from hvacsim.seedkey import LEVEL_03, key  # noqa: E402


def test_capture_pairs():
    assert key(0x6E760729, LEVEL_03) == 0xBE7B5888
    assert key(0x12345678, LEVEL_03) == 0x58182FC9


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
