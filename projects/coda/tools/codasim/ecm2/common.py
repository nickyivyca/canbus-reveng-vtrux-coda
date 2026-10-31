"""Idioms the ECM2 band repeats in every function, transliterated once.

Sources: full_listing.txt; codasim step-5 specs A/B (2026-10-09). The ECM2 band also keeps
an inverse mirror of every variable and a program-flow token at a0-0x2428; a mismatch calls
RedundancyMismatchHandler 0x80082EAA. Neither changes a value, so neither is modelled.
"""

from ..fixedpoint import s16, s32, sat


def abs16(x):
    """The guarded abs every ECM2 site uses: -0x8000 -> 0x7FFF, then extr (s16)."""
    return 0x7FFF if x == -0x8000 else s16(abs(x))


def debounce(cond, cnt):
    """DB idiom: u16 counter, saturating at 0xFFFF while cond holds, 0 when it does not.
    Returns the new count; the caller compares `CAL < count` (jge.u CAL,cnt -> 0)."""
    v = cnt.get()
    v = (v + 1 if v < 0xFFFF else 0xFFFF) if cond else 0
    cnt.set(v)
    return v


def adds32(a, b):
    return sat(a + b, -0x80000000, 0x7FFFFFFF)


def subs32(a, b):
    return sat(a - b, -0x80000000, 0x7FFFFFFF)


def muls32(a, b):
    return sat(a * b, -0x80000000, 0x7FFFFFFF)


def iir_q14(state, inp, gain, load, coeff):
    """MathIirFirstOrderQ14 0x80052198..0x8005221E. `state` is an s32 Var (Q14).
    load == 1 seeds state = inp << 14 (32-bit, wraps). Output: s16(state >> 14) -- it WRAPS."""
    old = state.get()
    if load == 1:
        st = s32(inp << 14)
    else:
        t = s32(inp * gain) >> 14                   # MathMul 0x80045A94 (mul, wraps), sha -14
        u = subs32(t, old >> 14)                    # MathSubSat 0x80045A8C
        v = muls32(u, coeff)                        # MathMulSat 0x80045A9C
        st = adds32(v, old)                         # MathAddSat 0x80045A6C
    state.set(st)
    return s16(st >> 14)


def latch(flag, set_cond, set_cnt, set_cal, clr_cond, clr_cnt, clr_cal):
    """A latching flag with separate set and clear debounces; the set block runs first."""
    if set_cal < debounce(set_cond, set_cnt):
        flag.set(1)
    if clr_cal < debounce(clr_cond, clr_cnt):
        flag.set(0)
