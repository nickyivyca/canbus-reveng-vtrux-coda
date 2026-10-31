"""Image and address-map checks. Run from the project root:
    python3.13 -m pytest projects/coda/tools/hvacsim/tests -q
or without pytest:
    python3.13 projects/coda/tools/hvacsim/tests/test_image.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from hvacsim.image import Image, to_global  # noqa: E402

# The 2 bytes the flash tool sent in each TransferExit (37 xx xx), which equal the
# CRC-16/CCITT-FALSE of that segment (notes/hvac/artifacts/hvac_flash_extract.p3.out.txt).
EXIT_CRC = {"0x7FC000": 0xBE3A, "0x7FEE10": 0x59A4, "0x780800": 0x04A5, "0x7E4000": 0x563B,
            "0x7E8000": 0x5610, "0x7EC000": 0xF78A, "0x7F0000": 0x424B, "0x7F8000": 0xFE8D}


def crc16_ccitt_false(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def test_segments_match_tool_crc():
    img = Image()
    assert len(img.segments) == 8
    for s in img.segments:
        g, n = int(s["global"], 16), s["bytes"]
        assert crc16_ccitt_false(img.bytes(g, n)) == EXIT_CRC[s["global"]], s


def test_translation():
    assert to_global(0xC000) == 0x7FC000
    assert to_global(0xEE10) == 0x7FEE10
    assert to_global(0x8000, 0xF9) == 0x7E4000
    assert to_global(0x8800, 0xE0) == 0x780800
    assert to_global(0x2F73) == 0x0FEF73


def test_reset_slots_point_at_tool_start_address():
    img = Image()
    assert [img.u16(0x7FEEFA), img.u16(0xEEFC), img.u16(0xEEFE)] == [0xCBA5] * 3


def test_unflashed_read_raises():
    img = Image()
    try:
        img.u8(0x7FD100)
    except ValueError:
        return
    raise AssertionError("read of 0xFF fill did not raise")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
