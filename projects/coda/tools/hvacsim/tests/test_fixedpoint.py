"""Hand cases for the HCS12 divide/multiply semantics (CPU12 reference manual)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from hvacsim.fixedpoint import ediv, edivs, emul, emuls, fdiv, idiv, idivs, s16, u16  # noqa: E402


def test_wrap():
    assert u16(0x12345) == 0x2345 and s16(0x8000) == -0x8000 and s16(-1) == -1


def test_mul():
    assert emul(0xFFFF, 0xFFFF) == 0xFFFE0001
    assert emuls(-2, 3) == -6
    assert emuls(0x8000, 0x8000) == 0x40000000


def test_div_truncates_toward_zero():
    assert idivs(-7, 2) == (-3, -1)
    assert idivs(7, -2) == (-3, 1)
    assert edivs(-100000, 7) == (-14285, -5, False)


def test_div_overflow_flag():
    assert ediv(0x00020000, 1)[2] is True
    assert ediv(1000, 7) == (142, 6, False)
    assert idiv(1000, 7) == (142, 6)
    assert fdiv(1, 2) == (0x8000, 0, False)


def test_div_zero_raises():
    for f, args in ((ediv, (1, 0)), (idivs, (1, 0))):
        try:
            f(*args)
        except ZeroDivisionError:
            continue
        raise AssertionError(f.__name__)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
