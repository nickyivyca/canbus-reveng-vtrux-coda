"""A PROG + CAL pair, read the way the firmware reads it.

Address map (TriCore; segment 8 = cached, A = uncached view of the same flash,
both accepted):
  CAL   0xA0020000 .. 0xA003BFFF   (0x1C000 bytes, the calibration image)
  PROG  0x80040000 .. 0x801FFDFF   (0x1BFE00 bytes)
All multi-byte values little-endian.

Descriptors are read at the widths the lookup code uses (worklog 6H.62.2):
  1-D  {u8 n @+0 (ld.bu), u32 xptr @+4, u32 yptr @+8}
  2-D  {u16 nx @+0 (ld.hu), u32 xptr @+4, u16 ny @+8 (ld.hu), u32 yptr @+0xc, u32 zptr @+0x10}
`torque_path_sim.Cal` read every one of these as u32. That gives the same answer
only while the upper bytes are zero, which nothing checks.

What-if edits go through `set_cal()`, which records each one; `describe()` puts
them in every result header (plan R4: a run states what it was run on).
"""

import hashlib
import os

from .fixedpoint import s8, s16, s32

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", "..", ".."))
DLCM = os.path.join(ROOT, "projects", "coda", "notes", "dlcm")
PROG_PATH = os.path.join(DLCM, "coda_dlcm_prog.bin")

# Named calibration images. Only images that were on the car, or the stock dump.
CALS = {
    "stock": os.path.join(DLCM, "coda_dlcm_cal.bin"),
    "c4c": os.path.join(DLCM, "artifacts", "cal_as_flashed_20260925_envelope_c4c.bin"),
    "f7": os.path.join(DLCM, "artifacts", "cal_as_flashed_20261004_f7_clunk.bin"),
}

CAL_OFF, PROG_OFF = 0x20000, 0x40000


class Image:
    def __init__(self, cal="stock", prog_path=PROG_PATH):
        cal_path = CALS.get(cal, cal)
        self.name = cal if cal in CALS else os.path.basename(cal_path)
        self.cal_path, self.prog_path = cal_path, prog_path
        self.cal = bytearray(open(cal_path, "rb").read())
        self.prog = open(prog_path, "rb").read()
        self.cal_md5 = hashlib.md5(self.cal).hexdigest()
        self.edits = []

    # ---------------------------------------------------------------- bytes
    def _loc(self, addr, n):
        seg, off = addr >> 28, addr & 0x0FFFFFFF
        if seg not in (0x8, 0xA):
            raise ValueError("0x%08X is not a flash address" % addr)
        if CAL_OFF <= off and off + n <= CAL_OFF + len(self.cal):
            return self.cal, off - CAL_OFF
        if PROG_OFF <= off and off + n <= PROG_OFF + len(self.prog):
            return self.prog, off - PROG_OFF
        raise ValueError("0x%08X (+%d) is outside CAL and PROG" % (addr, n))

    def raw(self, addr, n):
        buf, o = self._loc(addr, n)
        return bytes(buf[o:o + n])

    def u8(self, a):
        return self.raw(a, 1)[0]

    def u16(self, a):
        return int.from_bytes(self.raw(a, 2), "little")

    def u32(self, a):
        return int.from_bytes(self.raw(a, 4), "little")

    def read(self, addr, typ):
        """A scalar at `addr` under a symbol-map type (u8 s8 u16 s16 u32 s32)."""
        if typ == "u8":
            return self.u8(addr)
        if typ == "s8":
            return s8(self.u8(addr))
        if typ == "u16":
            return self.u16(addr)
        if typ == "s16":
            return s16(self.u16(addr))
        if typ == "u32":
            return self.u32(addr)
        if typ == "s32":
            return s32(self.u32(addr))
        raise ValueError("no scalar read for type %r at 0x%08X" % (typ, addr))

    def halfwords(self, addr, n):
        return [self.u16(addr + 2 * i) for i in range(n)]

    # ---------------------------------------------------------------- tables
    def table1d(self, desc):
        """Raw (xs, ys) halfwords; the lookup re-reads them signed or unsigned."""
        n = self.u8(desc)
        return self.halfwords(self.u32(desc + 4), n), self.halfwords(self.u32(desc + 8), n)

    def table1d_ptrs(self, desc):
        return self.u8(desc), self.u32(desc + 4), self.u32(desc + 8)

    def table2d(self, desc):
        """Raw (xs, ys, zs); zs is nx rows of ny."""
        nx, ny = self.u16(desc), self.u16(desc + 8)
        return (self.halfwords(self.u32(desc + 4), nx),
                self.halfwords(self.u32(desc + 0xC), ny),
                self.halfwords(self.u32(desc + 0x10), nx * ny))

    # ---------------------------------------------------------------- edits
    def set_cal(self, addr, typ, value, why=""):
        """Edit one CAL scalar for a what-if run. PROG is never edited."""
        buf, o = self._loc(addr, 4 if typ.endswith("32") else (2 if typ.endswith("16") else 1))
        if buf is not self.cal:
            raise ValueError("0x%08X is PROG; only CAL can be edited" % addr)
        n = {"u8": 1, "s8": 1, "u16": 2, "s16": 2, "u32": 4, "s32": 4}[typ]
        old = self.read(addr, typ)
        self.cal[o:o + n] = (value & ((1 << (8 * n)) - 1)).to_bytes(n, "little")
        self.edits.append((addr, typ, old, value, why))

    def describe(self):
        s = "image %s  cal md5 %s" % (self.name, self.cal_md5)
        for a, t, old, new, why in self.edits:
            s += "\n  EDIT 0x%08X %s %d -> %d  %s" % (a, t, old, new, why)
        return s
