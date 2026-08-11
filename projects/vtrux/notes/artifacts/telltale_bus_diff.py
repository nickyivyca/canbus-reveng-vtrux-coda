"""Vehicle-bus differential: parts truck (telltale lit) vs main truck (telltale off).

The IPC reads the Vehicle bus, so whatever drives the amber warning telltale
should differ there between a truck sitting with the light on and a healthy one.

For each (id, byte) this collects the value set on the Vehicle bus of each log and
reports bytes that are CONSTANT in both logs but hold DIFFERENT values -- the
shape a steady lamp-request bit would have. Bytes that vary in either log are
dropped, since those cannot be cleanly attributed.

Channel is resolved per log by content, never by number: the Vehicle bus is the
channel carrying 0x1E5 and 0x500 but none of the OBD-exclusive 0x043/0x044/0x441.

Usage:
    py -3.12 projects/vtrux/notes/artifacts/telltale_bus_diff.py FAULT_LOG GOOD_LOG [GOOD_LOG ...]
"""

import sys
from collections import defaultdict

sys.path.insert(0, ".")

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
                ch = int(p[2])
                cid = int(p[3], 16)
                data = p[6:]
            except (ValueError, IndexError):
                continue
            yield ch, cid, data


def vehicle_channel(path):
    seen = defaultdict(set)
    for n, (ch, cid, _) in enumerate(frames(path)):
        seen[ch].add(cid)
        if n > 600000:
            break
    best = None
    for ch, ids in seen.items():
        if (ids & VEH_ANCHORS) == VEH_ANCHORS and not (ids & OBD_ANCHORS) \
           and not (ids & PT_ANCHORS):
            best = ch
    return best


def profile(path):
    ch_veh = vehicle_channel(path)
    if ch_veh is None:
        raise SystemExit("no Vehicle-bus channel found in %s" % path)
    vals = defaultdict(set)
    for ch, cid, data in frames(path):
        if ch != ch_veh:
            continue
        for i, b in enumerate(data):
            if len(vals[(cid, i)]) <= 8:
                vals[(cid, i)].add(b)
    return ch_veh, vals


def main():
    fault_path = sys.argv[1]
    good_paths = sys.argv[2:]

    ch_f, fault = profile(fault_path)
    print("FAULT (telltale lit): %s   [Vehicle bus = ch%d]" % (fault_path, ch_f))

    goods = []
    for g in good_paths:
        ch_g, prof = profile(g)
        goods.append((g, prof))
        print("GOOD  (telltale off): %s   [Vehicle bus = ch%d]" % (g, ch_g))
    print()

    print("=== bytes constant in ALL logs but different in the fault log ===")
    print("    (candidate steady lamp-request bits)")
    hits = 0
    for key, fv in sorted(fault.items()):
        if len(fv) != 1:
            continue
        fval = next(iter(fv))
        gvals = []
        ok = True
        for _, prof in goods:
            gv = prof.get(key)
            if gv is None or len(gv) != 1:
                ok = False
                break
            gvals.append(next(iter(gv)))
        if not ok:
            continue
        if all(g == fval for g in gvals):
            continue
        if len(set(gvals)) != 1:
            continue              # good logs disagree -> not a stable reference
        gval = gvals[0]
        diff = int(fval, 16) ^ int(gval, 16)
        bits = [str(b) for b in range(8) if diff >> b & 1]
        hits += 1
        print("  0x%-6X B%-2d  fault=%-4s good=%-4s  differing bits: %s"
              % (key[0], key[1], fval, gval, ",".join(bits)))
    if not hits:
        print("  (none)")


if __name__ == "__main__":
    main()
