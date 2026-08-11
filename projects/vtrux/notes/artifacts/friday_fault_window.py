"""Friday 2026-07-24: three-way scan of the confirmed fault window.

The lamp was seen after the 21:17-21:24 refuel and cleared by a 3.2 s key cycle
at 21:39:42 -> 21:39:45 (ignition bit 0x592 B0 bit4; the only time all day that
0x53 B0 reaches 0x01 boot/init and 0x400 B0 drops to 0x09).

So the fault was present in:      BEFORE  21:35:45 .. 21:39:42
and absent in:                    PRE     21:29:57 .. 21:35:45   (key on, lamp not yet noticed)
                                  AFTER   21:39:46 .. 21:55:00   (post key cycle, lamp gone)

A byte holding a value during FAULT that it never holds in AFTER is the
candidate. PRE is reported too but not required to differ, since the lamp may
have lit before the driver noticed it.

Known-benign traffic is excluded: 0x63A B7 bit4 and 0x649 (evap purge, confirmed
earlier), 0x6A0 (rotating field), and the ids that simply track lever position.

Usage:  py -3.12 projects/vtrux/notes/artifacts/friday_fault_window.py
"""

import sys
import os
import re
import glob
from collections import defaultdict

sys.path.insert(0, ".")

LOGDIR = "../../CANLogs/VtruxLogs"
SESSION = "20260724_211556"
CHUNKS = range(2, 12)
HDR = re.compile(r"START DATE AND TIME \d+:\d+:\d+ (\d+):(\d+):(\d+):(\d+)")


def hm(s):
    h, m, sec = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


PRE = (hm("21:29:57"), hm("21:35:45"))
FAULT = (hm("21:35:45"), hm("21:39:42"))
AFTER = (hm("21:39:46"), hm("21:55:00"))

SKIP_IDS = {0x6A0, 0x649}
# lever-position carriers -- they differ between windows purely because the
# gear selected differs, which says nothing about a fault
LEVER_BYTES = {(0x639, 6), (0x644, 0), (0x601, 0), (0x639, 5)}


def chunk_files():
    fs = glob.glob(os.path.join(LOGDIR, "vtrux_%s_T*.log" % SESSION))
    out = []
    for p in fs:
        n = int(re.search(r"_T(\d+)\.log$", p).group(1))
        if n in CHUNKS:
            out.append((n, p))
    return [p for _, p in sorted(out)]


def header_start(path):
    with open(path, "r", errors="replace") as f:
        for _ in range(60):
            line = f.readline()
            if not line:
                break
            m = HDR.search(line)
            if m:
                hh, mm, ss, ms = m.groups()
                return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000.0
    return 0.0


def hhmmss(sec):
    sec = sec % 86400
    return "%02d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def main():
    # (cid, byte) -> {window: {value: seconds_held}}
    hold = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    cur = {}
    dead = set()
    vals = defaultdict(set)

    def win_of(t):
        if PRE[0] <= t < PRE[1]:
            return "PRE"
        if FAULT[0] <= t < FAULT[1]:
            return "FAULT"
        if AFTER[0] <= t < AFTER[1]:
            return "AFTER"
        return None

    for path in chunk_files():
        base = header_start(path)
        with open(path, "r", errors="replace") as f:
            for line in f:
                if not line or line[0] != "0":
                    continue
                p = line.split()
                if len(p) < 7:
                    continue
                try:
                    ts = p[0].split(":")
                    t = (base + int(ts[0]) * 3600 + int(ts[1]) * 60
                         + int(ts[2]) + int(ts[3]) / 10000.0)
                    cid = int(p[3], 16)
                except (ValueError, IndexError):
                    continue
                if cid in SKIP_IDS:
                    continue
                w = win_of(t)
                if w is None:
                    continue
                for i, b in enumerate(p[6:]):
                    key = (cid, i)
                    if key in dead or key in LEVER_BYTES:
                        continue
                    if key == (0x63A, 7):
                        # mask off the confirmed evap-purge bit
                        try:
                            b = "%02X" % (int(b, 16) & ~0x10)
                        except ValueError:
                            continue
                    s = vals[key]
                    if b not in s:
                        s.add(b)
                        if len(s) > 12:
                            dead.add(key)
                            continue
                    pv = cur.get(key)
                    if pv is None:
                        cur[key] = (b, t, w)
                    elif pv[0] != b or pv[2] != w:
                        hold[key][pv[2]][pv[0]] += t - pv[1]
                        cur[key] = (b, t, w)

    # flush the final held value of every byte, otherwise anything that stays
    # constant right through a window is never credited any hold time there
    for key, (v, t0, w) in cur.items():
        if key not in dead:
            end = {"PRE": PRE[1], "FAULT": FAULT[1], "AFTER": AFTER[1]}[w]
            hold[key][w][v] += max(0.0, end - t0)

    print("fault window scan -- Friday 2026-07-24")
    print("  PRE   %s .. %s" % (hhmmss(PRE[0]), hhmmss(PRE[1])))
    print("  FAULT %s .. %s   (lamp believed on)" % (hhmmss(FAULT[0]), hhmmss(FAULT[1])))
    print("  AFTER %s .. %s   (after 3.2 s key cycle, lamp gone)"
          % (hhmmss(AFTER[0]), hhmmss(AFTER[1])))
    print()
    print("=== values held >=2s in FAULT but never held in AFTER ===")
    hits = []
    for key, per in hold.items():
        if key in dead:
            continue
        fv = {v for v, s in per.get("FAULT", {}).items() if s >= 2.0}
        av = {v for v, s in per.get("AFTER", {}).items() if s >= 0.5}
        pv = {v for v, s in per.get("PRE", {}).items() if s >= 0.5}
        only = fv - av
        if only:
            hits.append((key, sorted(only), sorted(pv), sorted(av)))
    if not hits:
        print("  (none)")
    for key, only, pv, av in sorted(hits):
        print("  0x%-6X B%-2d  FAULT-only=%s   PRE=%s   AFTER=%s"
              % (key[0], key[1], ",".join(only),
                 ",".join(pv) or "-", ",".join(av) or "-"))


if __name__ == "__main__":
    main()
