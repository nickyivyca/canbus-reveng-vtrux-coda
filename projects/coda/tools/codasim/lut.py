"""The DLCM's table lookups, transliterated instruction by instruction.

Source: `full_listing.txt` (Ghidra 12.0.4, PROG 0x80040000), read 2026-10-09,
worklog 6H.62.2. Three entry points, two 1-D behaviours:

  lut1d_signed    0x80052284 MathLut1dLookupA, and 0x8005F082 (A recompiled)
  lut1d_unsigned  0x80052370 MathLut1dLookupB -- axis compared UNSIGNED, and it
                  DOES interpolate (an older symbol-map row said otherwise, from a
                  span cut at its clamp-exit ret 0x800523A2)
  lut2d           0x8005246A, X axis UNSIGNED, Y axis SIGNED

`x` is the 32-bit REGISTER value the caller passes, not "the quantity". The
compare is on the full register, so whether a negative quantity arrives as a
negative number (`ld.h`) or as 0xFFxx-and-up (`ld.hu`) is decided by the caller's
load, and it changes the answer: B returns Y[n-1] for a sign-extended negative x,
and the 2-D lookup clamps a negative x to the TOP of its X axis. Each call site in
`codasim.dlcm` states its load via `fixedpoint.ld_h` / `ld_hu`.

Tables are passed as (xs, ys) lists of the RAW halfwords as stored (ints 0..65535
or already-signed -- both accepted; each function re-reads them under the
signedness its instructions use).
"""

from .fixedpoint import s16, u16, s32, u32, divu


def _interp(ylo, yhi, dx, dX):
    """The split rising/falling interpolation shared by every lookup.

    rising  (ylo <  yhi): s16(ylo + u16((dx * u16(yhi - ylo)) /u dX))
    falling (ylo >= yhi): s16(ylo - u16((dx * u16(ylo - yhi)) /u dX))
    `jge ylo,yhi` takes the falling branch on equality, which then subtracts 0.
    """
    if ylo < yhi:
        return s16(u16(divu(u32(dx * u16(yhi - ylo)), dX)) + ylo)
    return s16(ylo - u16(divu(u32(dx * u16(ylo - yhi)), dX)))


def lut1d_signed(xs, ys, x):
    """0x80052284 / 0x8005F082. Axis signed (`ld.h`, jge/jlt on s32)."""
    X = [s16(v) for v in xs]
    Y = [s16(v) for v in ys]
    n = len(X)
    x = s32(x)
    if X[0] >= x:                       # jge d15(X0), d4(x) -> Y[0]
        return Y[0]
    if not x < X[n - 1]:                # jlt d4, X[n-1] else Y[n-1]
        return Y[n - 1]
    i = n - 1
    while True:                         # 0x800522B4: pre-decrement, loop while x < X[i]
        i -= 1
        if not x < X[i]:
            break
    dx = u16(x - X[i])                  # extr.u d1
    dX = u16(X[i + 1] - X[i])           # extr.u d15
    return _interp(Y[i], Y[i + 1], dx, dX)


def lut1d_unsigned(xs, ys, x):
    """0x80052370. Axis unsigned (`ld.hu`, jge.u/jlt.u on u32); Y still s16.

    dx = x - X[i] is NOT narrowed here (no extr.u, unlike A), but the search
    bounds it to 0 <= dx < 65536, so the result is the same."""
    X = [u16(v) for v in xs]
    Y = [s16(v) for v in ys]
    n = len(X)
    x = u32(x)
    if X[0] >= x:
        return Y[0]
    if not x < X[n - 1]:
        return Y[n - 1]
    i = n - 1
    while True:
        i -= 1
        if not x < X[i]:
            break
    dx = x - X[i]
    dX = X[i + 1] - X[i]
    return _interp(Y[i], Y[i + 1], dx, dX)


def lut2d(xs, ys, zs, x, y):
    """0x8005246A. Z stored as nx rows of ny, index yi + xi*ny.

    X (first axis, desc+4): clamp with max.u/min.u, search jlt.u -- UNSIGNED.
    Y (second axis, desc+0xc): clamp with max/min, search jlt -- SIGNED.
    Both searches start at n-2 regardless of where x sits, so x == X[n-1]
    lands in the last cell with full fraction.
    A zero-width Y cell (0x80052520) skips the Y interpolation and uses the
    lower value of each row; a zero-width X cell (0x8005264A) returns row xi's value.
    """
    X = [u16(v) for v in xs]
    Y = [s16(v) for v in ys]
    nx, ny = len(X), len(Y)
    assert len(zs) == nx * ny, "Z size %d != %d x %d" % (len(zs), nx, ny)
    Z = [s16(v) for v in zs]

    xc = min(max(u32(x), X[0]), X[nx - 1])          # max.u then min.u
    xi = nx - 1
    while True:
        xi -= 1
        if not xc < X[xi]:
            break

    yc = min(max(s32(y), Y[0]), Y[ny - 1])          # max then min, signed
    yi = ny - 1
    while True:
        yi -= 1
        if not yc < Y[yi]:
            break

    k = u16(yi + xi * ny)                           # madd + extr.u
    dy = u16(yc - Y[yi])
    dY = u16(Y[yi + 1] - Y[yi])
    if dY == 0:
        r0, r1 = Z[k], Z[k + ny]
    else:
        r0 = _interp(Z[k], Z[k + 1], dy, dY)
        r1 = _interp(Z[k + ny], Z[k + ny + 1], dy, dY)

    dX = u16(X[xi + 1] - X[xi])
    if dX == 0:
        return r0
    return _interp(r0, r1, xc - X[xi], dX)


def lut1d_wavg_u(xs, ys, x):
    """0x8005EF50..0x8005EFCE. Axis UNSIGNED, Y UNSIGNED, weighted average with a floor:
    (Y[i]*dhi + dlo*Y[i+1]) /u (dlo+dhi), u16 result. On a falling segment this can differ by 1
    from lut1d_unsigned (it floors the average instead of truncating the step). Spec E s1."""
    X = [u16(v) for v in xs]
    Y = [u16(v) for v in ys]
    n = len(X)
    x = u32(x)
    if X[0] >= x:                       # 0x8005EF5A jge.u
        return Y[0]
    if not x < X[n - 1]:                # 0x8005EF6E jlt.u
        return Y[n - 1]
    i = n - 1
    while True:                         # 0x8005EF78
        i -= 1
        if not x < X[i]:
            break
    dlo = u16(x - X[i])
    dhi = u16(X[i + 1] - x)
    num = u32(Y[i] * dhi + dlo * Y[i + 1])          # mul + madd
    return u16(divu(num, u16(dlo + dhi)))            # dvinit.u + dvstep.u, extr.u


def lut1d_signed_yu(xs, ys, x):
    """0x8005F138..0x8005F1EA. lut1d_signed's algorithm (axis SIGNED), but the Y branch test is
    unsigned (jge.u) and the result is u16. Spec E s1."""
    X = [s16(v) for v in xs]
    Y = [u16(v) for v in ys]
    n = len(X)
    x = s32(x)
    if X[0] >= x:
        return Y[0]
    if not x < X[n - 1]:
        return Y[n - 1]
    i = n - 1
    while True:
        i -= 1
        if not x < X[i]:
            break
    dx = u16(x - X[i])
    dX = u16(X[i + 1] - X[i])
    if Y[i] >= Y[i + 1]:                                                  # 0x8005F17E jge.u
        return u16(Y[i] - u16(divu(u32(dx * u16(Y[i] - Y[i + 1])), dX)))
    return u16(u16(divu(u32(dx * u16(Y[i + 1] - Y[i])), dX)) + Y[i])
