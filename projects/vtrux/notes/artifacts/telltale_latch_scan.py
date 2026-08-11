"""Bit-level latch scan: find the CAN bit that drives the amber warning telltale.

Target logs are the parts-truck pair captured 2026-04-21 with all three buses:
  vtrux_partstruck_exclamationindicatorforunpluggedpump.log  (light ON case)
  vtrux_partstruck_pumpplugin.log                            (pump plugged back in)

A telltale driver should be a bit that flips a very small number of times and
then holds -- not a bit that oscillates. This reports every (channel, id, bit)
whose transition count is at or below a threshold, with the timestamp and
direction of each flip, so the flip that lines up with the lamp can be picked out.

Usage:
    py -3.12 projects/vtrux/notes/artifacts/telltale_latch_scan.py LOG [--max-flips N]
                                                                      [--id 0xNNN]
"""

import sys
from collections import defaultdict

sys.path.insert(0, ".")


def parse_args():
    log = sys.argv[1]
    maxflips = 6
    only = None
    a = sys.argv[2:]
    for i, x in enumerate(a):
        if x == "--max-flips":
            maxflips = int(a[i + 1])
        elif x == "--id":
            only = int(a[i + 1], 16)
    return log, maxflips, only


def frames(path):
    with open(path, "r", errors="replace") as f:
        for line in f:
            if not line or line[0] != "0":
                continue
            p = line.split()
            if len(p) < 7:
                continue
            try:
                ts = p[0].split(":")
                t = (int(ts[0]) * 3600 + int(ts[1]) * 60 + int(ts[2])
                     + int(ts[3]) / 10000.0)
                ch = int(p[2])
                cid = int(p[3], 16)
                data = [int(x, 16) for x in p[6:]]
            except (ValueError, IndexError):
                continue
            yield t, ch, cid, data


def main():
    path, maxflips, only = parse_args()

    prevb = {}                     # (ch,cid,byte) -> last byte value
    flips = defaultdict(list)      # (ch,cid,byte,bit) -> [(t, new_bit_value)]
    dead = set()

    for t, ch, cid, data in frames(path):
        if only is not None and cid != only:
            continue
        for i, b in enumerate(data):
            bkey = (ch, cid, i)
            pb = prevb.get(bkey)
            prevb[bkey] = b
            # Only decompose to bits when the byte actually moved. Most frames
            # are unchanged, so this skips the per-bit work almost every time.
            if pb is None or pb == b:
                continue
            diff = pb ^ b
            while diff:
                bit = (diff & -diff).bit_length() - 1
                diff &= diff - 1
                key = (ch, cid, i, bit)
                if key in dead:
                    continue
                flips[key].append((t, (b >> bit) & 1))
                if len(flips[key]) > maxflips:
                    dead.add(key)
                    del flips[key]

    print("LOG: %s" % path)
    print("bits flipping <=%d times (candidate latched telltale drivers)" % maxflips)
    print("-" * 88)
    rows = sorted(flips.items(), key=lambda kv: (len(kv[1]), kv[0]))
    for (ch, cid, i, bit), ev in rows:
        if not ev:
            continue
        seq = "  ".join("t=%.2f->%d" % (t, v) for t, v in ev)
        print("  ch%-2d 0x%-8X B%-2d bit%-2d  (%d flips)  %s"
              % (ch, cid, i, bit, len(ev), seq))


if __name__ == "__main__":
    main()
