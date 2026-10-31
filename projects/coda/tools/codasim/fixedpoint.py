"""TriCore integer semantics, so DLCM blocks compute what the firmware computes.

Python ints never overflow, which is exactly why a transliteration in Python can be
silently wrong: a value the firmware truncates to 16 bits keeps growing here. Every
DLCM block therefore routes arithmetic through these helpers at the points where
the firmware narrows (`extr`, `extr.u`, `st.h`, `sat`) -- never "where it seems
likely to matter". Plan R2 (`notes/plans/codasim_full_model.md`).

Naming follows the instruction, not the intent:
  s16 / u16 / s32 / u32   wrap, as `extr d,d,#0,#16` / `extr.u` / 32-bit register
  sat_s16                 saturate, as `sat.h`
  divu                    dvinit.u + 4x dvstep.u: unsigned 32/32 truncating divide
  div_trunc               signed divide truncating toward zero (dvinit + dvstep)
TriCore `min`/`max` are signed numeric; `min.u`/`max.u` unsigned (worklog 6H).
"""


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def u16(v):
    return v & 0xFFFF


def s32(v):
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def u32(v):
    return v & 0xFFFFFFFF


def s8(v):
    v &= 0xFF
    return v - 0x100 if v & 0x80 else v


def u8(v):
    return v & 0xFF


def sat(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def sat_s16(v):
    return sat(v, -0x8000, 0x7FFF)


def divu(a, b):
    """Unsigned 32-bit truncating divide. Division by zero is not modelled: the
    firmware's result there is architecture-defined, and every call site that can
    reach it must be shown unreachable instead (raises, so it cannot pass silently)."""
    a, b = u32(a), u32(b)
    if b == 0:
        raise ZeroDivisionError("divu by zero: firmware result undefined here")
    return a // b


def div_trunc(a, b):
    """Signed divide, truncating toward zero (C semantics), on s32 operands."""
    a, b = s32(a), s32(b)
    if b == 0:
        raise ZeroDivisionError("div_trunc by zero")
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def q14_mul(a, coeff):
    """(a * coeff) >> 14 with an arithmetic shift, as MathIirFirstOrderQ14 uses."""
    return (a * coeff) >> 14


def ld_h(raw16):
    """Register value after `ld.h` of a halfword: sign-extended."""
    return s16(raw16)


def ld_hu(raw16):
    """Register value after `ld.hu` of a halfword: zero-extended."""
    return u16(raw16)
