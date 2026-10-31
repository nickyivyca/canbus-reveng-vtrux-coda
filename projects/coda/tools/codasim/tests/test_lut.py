"""lut.py against hand cases.

Run from the project root:  python3.13 projects/coda/tools/codasim/tests/test_lut.py
The sweep against torque_path_sim's float interp1/interp2 on real CAL tables was removed with that
module at plan step 7 (2026-10-09, worklog 6H.71).
"""
import sys
sys.path.insert(0, ".")
sys.path.insert(0, "projects/coda/tools")

from codasim import lut
from codasim.fixedpoint import ld_h, ld_hu

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("%-4s %-52s got %s want %s" % ("ok" if ok else "FAIL", name, got, want))


# hand cases: rising, falling, clamps, exact breakpoint, truncation direction
xs, ys = [0, 100, 200], [0, 10, 5]
check("signed rising mid", lut.lut1d_signed(xs, ys, 50), 5)
check("signed rising trunc 0.99 -> 0", lut.lut1d_signed(xs, ys, 9), 0)
check("signed falling trunc keeps toward ylo", lut.lut1d_signed(xs, ys, 101), 10)
check("signed falling mid", lut.lut1d_signed(xs, ys, 150), 8)
check("signed clamp low", lut.lut1d_signed(xs, ys, -5), 0)
check("signed clamp high", lut.lut1d_signed(xs, ys, 999), 5)
check("signed at breakpoint", lut.lut1d_signed(xs, ys, 100), 10)
check("unsigned interpolates (B)", lut.lut1d_unsigned(xs, ys, 50), 5)
check("unsigned: sign-extended -5 -> Y[n-1]", lut.lut1d_unsigned(xs, ys, ld_h(0xFFFB)), 5)
check("unsigned: zero-extended -5 -> Y[n-1]", lut.lut1d_unsigned(xs, ys, ld_hu(0xFFFB)), 5)
nx = [0, 100]; ny = [-10, 10]; z = [0, 20, 100, 120]
check("2d centre", lut.lut2d(nx, ny, z, 50, 0), 60)
check("2d negative x clamps to TOP of X", lut.lut2d(nx, ny, z, ld_h(0xFFFF), -10), 100)
check("2d negative y clamps to bottom of Y", lut.lut2d(nx, ny, z, 0, -50), 0)

print("\nhand-case failures:", fails)
sys.exit(1 if fails else 0)
