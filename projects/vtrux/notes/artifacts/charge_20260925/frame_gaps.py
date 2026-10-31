"""List inter-frame gaps > MIN_GAP s in a log (all channels), and per-second
frame counts per channel over a window.
Usage: python3.13 <this> LOG MIN_GAP [T_START T_END]
"""
import sys
sys.path.insert(0, ".")
from collections import Counter
from canre.parsers import parse_file

path, gmin = sys.argv[1], float(sys.argv[2])
ws = float(sys.argv[3]) if len(sys.argv) > 3 else None
we = float(sys.argv[4]) if len(sys.argv) > 4 else None
prev = None
per = Counter()
for fr in parse_file(path):
    t = fr.timestamp
    if prev is not None and t - prev > gmin:
        print(f"gap {prev:9.3f} -> {t:9.3f}  ({t - prev:.3f} s)")
    prev = t
    if ws is not None and ws <= t <= we:
        per[(int(t), fr.bus)] += 1
for (s, b), n in sorted(per.items()):
    print(f"sec {s} bus {b}: {n}")
