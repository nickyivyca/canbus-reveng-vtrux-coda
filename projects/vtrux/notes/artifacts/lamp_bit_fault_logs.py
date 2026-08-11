"""What does the amber-lamp field (0x646 B7 bits[6:4]) do during major HV faults?

Solid lamp = field held at 5 (see the Friday 2026-07-24 event and the parts-truck
logs). The open question is whether a BLINKING lamp shows up as the field
toggling, and at what rate.

For each log this prints every segment the field holds for more than a few
frames, plus toggle statistics (transition count and median dwell), so a periodic
blink is distinguishable from a one-way latch.

  field 0 = system down / booting
  field 5 = warning (lamp on)
  field 6 = normal (lamp off)

Usage:
    py -3.12 projects/vtrux/notes/artifacts/lamp_bit_fault_logs.py LOG [LOG ...]
"""

import sys
import os
import subprocess
from statistics import median

sys.path.insert(0, ".")

MIN_SEG = 0.05          # ignore sub-frame noise when listing segments


def field_series(path):
    out = []
    p = subprocess.Popen(["grep", "-E", " 0x646 ", path],
                         stdout=subprocess.PIPE, text=True, errors="replace")
    for line in p.stdout:
        f = line.split()
        if len(f) < 14:
            continue
        try:
            ts = f[0].split(":")
            t = (int(ts[0]) * 3600 + int(ts[1]) * 60 + int(ts[2])
                 + int(ts[3]) / 10000.0)
            v = (int(f[13], 16) >> 4) & 7
        except (ValueError, IndexError):
            continue
        out.append((t, v))
    p.stdout.close()
    p.wait()
    return out


def main():
    for path in sys.argv[1:]:
        pts = field_series(path)
        print("=" * 84)
        print("%s   (%d frames of 0x646)" % (os.path.basename(path), len(pts)))
        print("=" * 84)
        if not pts:
            print("  no 0x646 frames\n")
            continue

        segs = []
        prev, start = None, None
        for t, v in pts:
            if v != prev:
                if prev is not None:
                    segs.append((start, t, prev))
                prev, start = v, t
        segs.append((start, pts[-1][0], prev))

        dist = {}
        for a, b, v in segs:
            dist[v] = dist.get(v, 0.0) + (b - a)
        print("  time in each state: %s"
              % "  ".join("field%d=%.1fs" % (k, v) for k, v in sorted(dist.items())))

        # toggle statistics between the two lamp states
        lamp = [s for s in segs if s[2] in (5, 6)]
        flips = sum(1 for i in range(1, len(lamp))
                    if lamp[i][2] != lamp[i - 1][2])
        print("  segments=%d  lamp-state flips=%d" % (len(segs), flips))
        if flips >= 4:
            dwell5 = [b - a for a, b, v in lamp if v == 5]
            dwell6 = [b - a for a, b, v in lamp if v == 6]
            if dwell5 and dwell6:
                print("  >>> TOGGLING: median dwell field5=%.3fs field6=%.3fs"
                      " -> ~%.2f Hz"
                      % (median(dwell5), median(dwell6),
                         1.0 / max(1e-6, median(dwell5) + median(dwell6))))

        shown = 0
        for a, b, v in segs:
            if b - a < MIN_SEG:
                continue
            print("    t=%8.3f -> %8.3f  (%7.3fs)  field=%d" % (a, b, b - a, v))
            shown += 1
            if shown >= 30:
                print("    ... (%d more segments)" % (len(segs) - shown))
                break
        print()


if __name__ == "__main__":
    main()
