"""Start-up RAM initialisation: the CodeWarrior copy-down run by StartupCopyDown (0x7F8000).

`_startupData` sits at local 0xC00F (fixed page). Its word at 0xC013 points to the
copy-down list, a run of entries

    [size u16][GPAGE u8][dest u16][size bytes]

ended by size 0. Each entry's destination is a GPAGE:offset global address. On this
image the list starts at local 0xCD01 and holds 7 entries (notes section 5.6).

The zero-out list (nofZeroOuts at 0xC00F, pZeroOut at 0xC011) is not modelled yet:
RAM it covers reads 0 at start-up, which is also what a fresh `Ram` holds.

    from hvacsim.startup import copy_down
    init = copy_down(Image())        # {global address: byte}
"""

from .image import Image

STARTUP_DATA = 0xC00F
COPY_DOWN_PTR = 0xC013


def copy_down_entries(img):
    """List of (dest_global, bytes) in list order."""
    p = img.u16(img.g(COPY_DOWN_PTR))
    out = []
    while True:
        size = img.u16(img.g(p))
        if size == 0:
            return out
        gpage = img.u8(img.g(p + 2))
        dest = (gpage << 16) | img.u16(img.g(p + 3))
        out.append((dest, img.bytes(img.g(p + 5), size)))
        p += 5 + size


def copy_down(img=None):
    """{global address: initial byte} for every byte the copy-down writes."""
    img = img or Image()
    init = {}
    for dest, data in copy_down_entries(img):
        for i, b in enumerate(data):
            init[dest + i] = b
    return init
