"""HCS12/S12X CPU integer semantics, exact (rule 2).

Width helpers wrap like the registers do. The arithmetic instructions the compiler
emits for multiply and divide are given as functions named after the opcode, so a
module transliterated from a listing reads instruction for instruction:

    EMUL  (Y:D = Y * D)            u16 x u16 -> u32
    EMULS                          s16 x s16 -> s32
    EDIV  (Y = Y:D / X, D = rem)   u32 / u16 -> (u16 q, u16 r), V on overflow
    EDIVS                          s32 / s16 -> (s16 q, s16 r), V on overflow
    IDIV  (X = D / X, D = rem)     u16 / u16
    IDIVS                          s16 / s16
    FDIV                           (D << 16) / X, fractional

Signed divides truncate toward zero and the remainder takes the dividend's sign
(CPU12 reference manual, IDIVS/EDIVS). Division by zero sets C and leaves the
result undefined on the chip; here it raises, so a model never silently consumes
an undefined value.
"""


def u8(v):
    return v & 0xFF


def s8(v):
    v &= 0xFF
    return v - 0x100 if v & 0x80 else v


def u16(v):
    return v & 0xFFFF


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def u32(v):
    return v & 0xFFFFFFFF


def s32(v):
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def _tdiv(n, d):
    q = abs(n) // abs(d)
    q = -q if (n < 0) != (d < 0) else q
    return q, n - q * d


def emul(y, d):
    return u16(y) * u16(d)


def emuls(y, d):
    return s32(s16(y) * s16(d))


def ediv(yd, x):
    """Returns (quotient, remainder, overflow). On overflow the chip leaves Y undefined."""
    if u16(x) == 0:
        raise ZeroDivisionError("EDIV by zero (C set, result undefined)")
    q, r = divmod(u32(yd), u16(x))
    return u16(q), u16(r), q > 0xFFFF


def edivs(yd, x):
    if s16(x) == 0:
        raise ZeroDivisionError("EDIVS by zero (C set, result undefined)")
    q, r = _tdiv(s32(yd), s16(x))
    return s16(q), s16(r), not -0x8000 <= q <= 0x7FFF


def idiv(d, x):
    if u16(x) == 0:
        raise ZeroDivisionError("IDIV by zero (C set, X = 0xFFFF on the chip)")
    q, r = divmod(u16(d), u16(x))
    return q, r


def idivs(d, x):
    if s16(x) == 0:
        raise ZeroDivisionError("IDIVS by zero")
    q, r = _tdiv(s16(d), s16(x))
    return s16(q), s16(r)


def fdiv(d, x):
    """Fractional divide: (D * 65536) / X. Overflow (V) when D >= X."""
    if u16(x) == 0:
        raise ZeroDivisionError("FDIV by zero")
    q, r = divmod(u16(d) << 16, u16(x))
    return u16(q), u16(r), u16(d) >= u16(x)
