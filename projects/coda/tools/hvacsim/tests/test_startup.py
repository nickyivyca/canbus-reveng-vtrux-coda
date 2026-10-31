"""The start-up copy-down list as the image holds it: 7 entries from local 0xCD01."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from hvacsim.image import Image  # noqa: E402
from hvacsim.startup import copy_down, copy_down_entries  # noqa: E402


def test_entries():
    img = Image()
    assert img.u16(img.g(0xC013)) == 0xCD01
    got = [(d, len(b)) for d, b in copy_down_entries(img)]
    assert got == [(0x0FE209, 708), (0x0FE4D6, 107), (0x0FE54C, 17), (0x0FE591, 2),
                   (0x0FEA2C, 57), (0x0FEA66, 52), (0x0FEFB7, 1)]


def test_did_range_table():
    m = copy_down()
    row = bytes(m[0x0FEA2C + i] for i in range(7))
    assert row == bytes.fromhex("e0000064000403")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
