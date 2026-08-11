"""Phase 7: characterize the 0x508 / 0x506-bit5 activation at 20:37.

Test hypothesis: 0x508 broadcast + 0x506 B0 bit5 = battery cooling active, and it
engaged during the evening charge because the pack reached its warmest point.

- For each 0x508 on/off edge, report tmax/tmin/soc/ibat (interpolated from cache).
- Correlate 0x508 B6/B7 payload with cell tmax.
- Confirm 0x506 B0 bit5 presence == 0x508 presence.
"""
import sys
sys.path.insert(0, ".")

import subprocess
from datetime import timedelta

from battery_fan_signature import (chunk_files, parse_header_time, decode_line,
                                   load_410, load_430, fmt)


def nearest(series, t):
    lo, hi = 0, len(series) - 1
    best = series[0]
    bestd = abs((series[0][0] - t).total_seconds())
    while lo <= hi:
        mid = (lo + hi) // 2
        d = (series[mid][0] - t).total_seconds()
        if abs(d) < bestd:
            bestd = abs(d)
            best = series[mid]
        if d < 0:
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def scan_508():
    files = chunk_files()
    frames = []          # (t, data)
    for path in files:
        base = parse_header_time(path)
        if base is None:
            continue
        out = subprocess.run(["grep", "-hE", " 0x508 ", path],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            dec = decode_line(line, base)
            if dec is None:
                continue
            t, arb, data = dec
            if arb == 0x508:
                frames.append((t, data))
    frames.sort(key=lambda x: x[0])
    return frames


def edges(frames, gap=120):
    segs = [[frames[0][0], frames[0][0]]]
    for t, _ in frames[1:]:
        if (t - segs[-1][1]).total_seconds() > gap:
            segs.append([t, t])
        else:
            segs[-1][1] = t
    return segs


if __name__ == "__main__":
    rows430 = load_430()
    temps = [(t, tmax, tmin) for t, tmax, tmin, _ in rows430 if tmax is not None]
    rows410 = load_410()
    ibats = [(t, ibat, soc) for t, ibat, soc, *_ in rows410 if ibat is not None]
    t0 = rows410[0][0]

    frames = scan_508()
    print(f"0x508 frames: {len(frames)}")
    segs = edges(frames)
    print("\n=== 0x508 active windows with thermal/charge context at edges ===")
    for a, b in segs:
        ta = nearest(temps, a); tb = nearest(temps, b)
        ia = nearest(ibats, a); ib = nearest(ibats, b)
        print(f"  ON  {fmt(a,t0)}  tmax={ta[1]:.1f} tmin={ta[2]:.1f} soc={ia[2]} ibat={ia[1]:.0f}")
        print(f"  OFF {fmt(b,t0)}  tmax={tb[1]:.1f} tmin={tb[2]:.1f} soc={ib[2]} ibat={ib[1]:.0f}")

    print("\n=== max tmax reached BEFORE first 0x508-during-charge (18:39-20:37) ===")
    from datetime import datetime
    win0 = datetime(2026, 7, 14, 18, 39)
    win1 = datetime(2026, 7, 14, 20, 37, 4)
    seg_t = [x[1] for x in temps if win0 <= x[0] <= win1]
    if seg_t:
        print(f"  during 18:39-20:37 charge (0x508 OFF): tmax rose to {max(seg_t):.1f}")
    win2 = datetime(2026, 7, 14, 16, 18)
    win3 = datetime(2026, 7, 14, 17, 13)
    seg_t2 = [x[1] for x in temps if win2 <= x[0] <= win3]
    if seg_t2:
        print(f"  during 4pm charge (0x508 OFF whole time):  tmax rose to {max(seg_t2):.1f}")

    print("\n=== 0x508 B6/B7 vs cell tmax (sampled) ===")
    step = max(1, len(frames) // 30)
    for i in range(0, len(frames), step):
        t, d = frames[i]
        tm = nearest(temps, t)
        b6 = d[6] if len(d) > 6 else None
        b7 = d[7] if len(d) > 7 else None
        print(f"  {fmt(t,t0)}  B6={b6} B7={b7}  tmax={tm[1]:.1f}")
