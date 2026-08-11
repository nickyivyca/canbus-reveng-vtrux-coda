"""Intersect test for the amber telltale bit.

The lamp is reported to come on some time after key-on (a VCM timeout) and then
stay on. So on the parts truck the driving bit must:

  1. start LOW and end HIGH within a log that begins at key-on
     (vtrux_partstruck_startup_test.log), and
  2. be constantly HIGH across a log captured later with the lamp already lit
     (vtrux_partstruck_exclamationindicatorforunpluggedpump.log), and
  3. be constantly LOW on the healthy main truck.

Only bits satisfying all three survive. Vehicle bus is resolved by content.

Usage:  py -3.12 projects/vtrux/notes/artifacts/telltale_intersect.py
"""

import sys
from collections import defaultdict

sys.path.insert(0, ".")

STARTUP = "projects/vtrux/logs/vtrux_partstruck_startup_test.log"
LIT = "projects/vtrux/logs/vtrux_partstruck_exclamationindicatorforunpluggedpump.log"
GOOD = ["projects/vtrux/logs/vtrux_ccmscan.log",
        "projects/vtrux/logs/vtrux_trailergainsetting.log"]

VEH_ANCHORS = {0x1E5, 0x500}
OBD_ANCHORS = {0x043, 0x044, 0x441, 0x442, 0x44A}
PT_ANCHORS = {0x051, 0x410, 0x420, 0x430}


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
                yield t, int(p[2]), int(p[3], 16), p[6:]
            except (ValueError, IndexError):
                continue


def vehicle_channel(path):
    seen = defaultdict(set)
    for n, (_, ch, cid, _) in enumerate(frames(path)):
        seen[ch].add(cid)
        if n > 600000:
            break
    for ch, ids in seen.items():
        if (ids & VEH_ANCHORS) == VEH_ANCHORS and not (ids & OBD_ANCHORS) \
           and not (ids & PT_ANCHORS):
            return ch
    return None


def bit_profile(path):
    """(cid,byte,bit) -> [first_value, last_value, ever0, ever1, t_first_high]"""
    ch_v = vehicle_channel(path)
    if ch_v is None:
        raise SystemExit("no Vehicle bus in %s" % path)
    prof = {}
    prevb = {}
    for t, ch, cid, data in frames(path):
        if ch != ch_v:
            continue
        for i, bs in enumerate(data):
            bkey = (ch, cid, i)
            try:
                b = int(bs, 16)
            except ValueError:
                continue
            if prevb.get(bkey) == b:
                continue
            prevb[bkey] = b
            for bit in range(8):
                v = (b >> bit) & 1
                key = (cid, i, bit)
                r = prof.get(key)
                if r is None:
                    prof[key] = [v, v, v == 0, v == 1, t if v else None]
                else:
                    r[1] = v
                    if v == 0:
                        r[2] = True
                    else:
                        r[3] = True
                        if r[4] is None:
                            r[4] = t
    return ch_v, prof


def main():
    ch_s, start = bit_profile(STARTUP)
    ch_l, lit = bit_profile(LIT)
    print("startup log  Vehicle bus = ch%d" % ch_s)
    print("lit log      Vehicle bus = ch%d" % ch_l)
    goods = []
    for g in GOOD:
        ch_g, p = bit_profile(g)
        goods.append(p)
        print("good log     Vehicle bus = ch%d  (%s)" % (ch_g, g))
    print()

    print("=== bits LOW->HIGH in startup, constant HIGH when lit, constant LOW on healthy truck ===")
    hits = 0
    for key, r in sorted(start.items()):
        first, last, ever0, ever1, t_hi = r
        if not (first == 0 and last == 1):
            continue
        l = lit.get(key)
        if l is None or l[2] or not l[3]:      # must never be low while lit
            continue
        ok = True
        for p in goods:
            g = p.get(key)
            if g is None or g[3]:              # must never be high when healthy
                ok = False
                break
        if not ok:
            continue
        hits += 1
        print("  0x%-6X B%-2d bit%-2d   goes high at t=%.1fs in startup log"
              % (key[0], key[1], key[2], t_hi or -1))
    if not hits:
        print("  (none)")

    print()
    print("=== relaxed: LOW->HIGH in startup AND constant HIGH when lit (healthy truck ignored) ===")
    hits = 0
    for key, r in sorted(start.items()):
        first, last, ever0, ever1, t_hi = r
        if not (first == 0 and last == 1):
            continue
        l = lit.get(key)
        if l is None or l[2] or not l[3]:
            continue
        hits += 1
        print("  0x%-6X B%-2d bit%-2d   goes high at t=%.1fs"
              % (key[0], key[1], key[2], t_hi or -1))
    if not hits:
        print("  (none)")


if __name__ == "__main__":
    main()
