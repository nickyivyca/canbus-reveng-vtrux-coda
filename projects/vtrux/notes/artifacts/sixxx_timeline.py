"""Print a timestamped transition timeline for the PT-bus 6xx HCU diagnostic band.

Two passes: the first learns which (bus, id, byte) look like discrete status
fields (few distinct values, not counters); the second prints every transition of
those fields with a timestamp, so a fault window can be read off directly.

Usage:
    py -3.12 projects/vtrux/notes/artifacts/sixxx_timeline.py LOG [--from S] [--to S]
                                                                  [--max-distinct N]
"""

import sys
import subprocess
from collections import defaultdict

sys.path.insert(0, ".")

GREP_RE = " 0x6[0-9A-F][0-9A-F] "


def parse_args():
    log = sys.argv[1]
    t0, t1, md = 0.0, 1e18, 12
    a = sys.argv[2:]
    for i, x in enumerate(a):
        if x == "--from":
            t0 = float(a[i + 1])
        elif x == "--to":
            t1 = float(a[i + 1])
        elif x == "--max-distinct":
            md = int(a[i + 1])
    return log, t0, t1, md


def frames(path):
    p = subprocess.Popen(["grep", "-E", GREP_RE, path], stdout=subprocess.PIPE,
                         text=True, errors="replace")
    for line in p.stdout:
        f = line.split()
        if len(f) < 7:
            continue
        try:
            ts = f[0].split(":")
            t = (int(ts[0]) * 3600 + int(ts[1]) * 60 + int(ts[2])
                 + int(ts[3]) / 10000.0)
            ch = int(f[2])
            cid = int(f[3], 16)
        except (ValueError, IndexError):
            continue
        yield t, ch, cid, f[6:]
    p.stdout.close()
    p.wait()


def main():
    path, t0, t1, maxd = parse_args()

    # pass 1 -- profile each byte
    vals = defaultdict(set)
    changes = defaultdict(int)
    seq = defaultdict(int)
    prev = {}
    for t, ch, cid, data in frames(path):
        for i, b in enumerate(data):
            key = (ch, cid, i)
            if len(vals[key]) <= 64:
                vals[key].add(b)
            pv = prev.get(key)
            if pv is not None and pv != b:
                changes[key] += 1
                if abs(int(b, 16) - int(pv, 16)) in (1, 255):
                    seq[key] += 1
            prev[key] = b

    keep = set()
    for key, s in vals.items():
        n, c = len(s), changes.get(key, 0)
        if n < 2 or n > maxd:
            continue
        if c > 4 and seq.get(key, 0) > 0.8 * c:
            continue                      # rolling counter
        keep.add(key)

    print("tracking %d discrete 6xx bytes (<=%d distinct, non-counter)"
          % (len(keep), maxd))
    print("-" * 78)

    # pass 2 -- timeline
    prev = {}
    for t, ch, cid, data in frames(path):
        for i, b in enumerate(data):
            key = (ch, cid, i)
            if key not in keep:
                continue
            pv = prev.get(key)
            if pv is not None and pv != b and t0 <= t <= t1:
                print("t=%8.3f  ch%-2d 0x%-6X B%-2d  %s -> %s"
                      % (t, ch, cid, i, pv, b))
            prev[key] = b


if __name__ == "__main__":
    main()
