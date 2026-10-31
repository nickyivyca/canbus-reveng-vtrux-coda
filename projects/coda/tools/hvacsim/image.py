"""The HVAC program image, addressed the way the firmware addresses it.

`coda_hvac_prog.bin` holds the eight program segments of the 2026-10-25 flash at S12X
global addresses (0x780000-0x7FFFFF, unflashed bytes 0xFF), built by
`notes/hvac/artifacts/pack_hvac_image.py`. A module reads constants by CPU-local
address and page, exactly as the listing does, and gets the global address back for
the symbol map:

    img = Image()
    img.u16(0x7FEEFE)                 -> 0xCBA5   (global)
    img.g(0x8000, page=0xF9)          -> 0x7E4000
    img.u8(0x8123, page=0xF9)         -> byte at page F9, local 0x8123
    img.flashed(0x7FD100)             -> False    (never written by the flash)

Reading an unflashed byte raises: the 0xFF there is fill, not firmware.
The local -> global map is the S12X one (hypothesis H1, notes section 3).
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
HVAC = os.path.join(REPO, "projects", "coda", "notes", "hvac")


def to_global(local, page=None):
    """S12X CPU-local address -> global. `page` is PPAGE, used only for 0x8000-0xBFFF."""
    if 0x8000 <= local < 0xC000:
        if page is None:
            raise ValueError("local 0x%04X is in the PPAGE window; give the page" % local)
        return 0x400000 | (page << 14) | (local & 0x3FFF)
    if local >= 0xC000:
        return 0x7FC000 | (local & 0x3FFF)
    if local >= 0x4000:
        return 0x7F4000 | (local & 0x3FFF)
    if local >= 0x2000:
        return 0x0FE000 | (local & 0x1FFF)
    if local >= 0x1000:
        raise ValueError("local 0x%04X is in the RPAGE window; not mapped yet" % local)
    if local >= 0x0800:
        raise ValueError("local 0x%04X is in the EPAGE window; not mapped yet" % local)
    return local


class Image:
    def __init__(self, path=os.path.join(HVAC, "coda_hvac_prog.bin"),
                 map_path=os.path.join(HVAC, "coda_hvac_map.json")):
        with open(path, "rb") as fh:
            self.data = fh.read()
        with open(map_path) as fh:
            m = json.load(fh)
        self.base = int(m["prog_base"], 16)
        self.segments = [s for s in m["segments"] if s["seg"] != 0]
        self.ranges = [(int(s["global"], 16), int(s["global_end"], 16)) for s in self.segments]

    def g(self, local, page=None):
        return to_global(local, page)

    def flashed(self, g):
        return any(lo <= g <= hi for lo, hi in self.ranges)

    def _at(self, addr, page, n):
        g = addr if addr > 0xFFFF else to_global(addr, page)
        for i in range(n):
            if not self.flashed(g + i):
                raise ValueError("0x%06X is not flashed (0xFF fill, not firmware)" % (g + i))
        return g - self.base

    def bytes(self, addr, n, page=None):
        o = self._at(addr, page, n)
        return self.data[o:o + n]

    def u8(self, addr, page=None):
        return self.data[self._at(addr, page, 1)]

    def s8(self, addr, page=None):
        v = self.u8(addr, page)
        return v - 0x100 if v & 0x80 else v

    def u16(self, addr, page=None):
        o = self._at(addr, page, 2)
        return int.from_bytes(self.data[o:o + 2], "big")

    def s16(self, addr, page=None):
        v = self.u16(addr, page)
        return v - 0x10000 if v & 0x8000 else v
