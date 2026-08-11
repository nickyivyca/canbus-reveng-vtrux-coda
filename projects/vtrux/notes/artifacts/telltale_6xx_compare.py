"""Telltale-bit hunt: compare the PT-bus 6xx HCU diagnostic band across trucks.

Idea: the amber warning telltale is lit by the VCM/HCU. If the HCU exposes a
"fault active / lamp request" flag, it should be a bit that is SET on the parts
truck (which sits with the light on once its missing-coolant-pump timeout
expires) and CLEAR on the healthy main truck.

For each log this prints, per 6xx-band id and byte: the first value, the last
value, the distinct value set, and the transition count -- so a byte that latches
partway through a log is obvious.

Usage:
    py -3.12 projects/vtrux/notes/artifacts/telltale_6xx_compare.py LOG [LOG ...]
"""

import sys
import subprocess
from collections import defaultdict

sys.path.insert(0, ".")

GREP_RE = " 0x6[0-9A-F][0-9A-F] "
# 0x661 is OBD-bus-native; every other 6xx id is PT-bus. Track the bus per id so
# a cross-bus id cannot silently merge two different payload streams.
MAX_DISTINCT = 20


def scan(path):
    first, last, vals, changes, prev = {}, {}, defaultdict(set), defaultdict(int), {}
    t_first, t_last = {}, {}
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
        for i, b in enumerate(f[6:]):
            key = (ch, cid, i)
            if key not in first:
                first[key] = b
                t_first[key] = t
            last[key] = b
            t_last[key] = t
            if len(vals[key]) <= MAX_DISTINCT:
                vals[key].add(b)
            pv = prev.get(key)
            if pv is not None and pv != b:
                changes[key] += 1
            prev[key] = b
    p.stdout.close()
    p.wait()
    return first, last, vals, changes


def main():
    for path in sys.argv[1:]:
        first, last, vals, changes = scan(path)
        print("=" * 100)
        print("LOG: %s" % path)
        print("=" * 100)
        print("  %-4s %-10s %-3s %-6s %-6s %-6s %-9s %s"
              % ("ch", "id", "B", "first", "last", "n_val", "n_change", "values"))
        for key in sorted(first, key=lambda k: (k[0], k[1], k[2])):
            ch, cid, i = key
            n = len(vals[key])
            c = changes.get(key, 0)
            if n == 1:
                continue                      # constant: nothing to say
            if n > MAX_DISTINCT:
                continue                      # analog / counter
            flag = ""
            if first[key] != last[key] and c <= 12:
                flag = "  <== LATCHED"
            print("  %-4d 0x%-8X B%-2d %-6s %-6s %-6d %-9d %s%s"
                  % (ch, cid, i, first[key], last[key], n, c,
                     " ".join(sorted(vals[key])), flag))
        print()


if __name__ == "__main__":
    main()
