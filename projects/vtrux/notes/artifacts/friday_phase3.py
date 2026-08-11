"""Phase 3: bus-normalised latched-state scan over the Friday 2026-07-24 trip.

Streams every Friday chunk through grep (fast prefilter) and tracks, for every
PT-bus status ID byte, the distinct values and every transition. The goal is to
find a byte that steps once mid-trip and *stays* stepped until the key cycle --
the signature of a latched warning.

All the watched IDs are PT-bus-native, so channel number (which the Android
logger renumbers on every USB reconnect) is collapsed to a single "PT" stream;
reconnects are flagged so they are not mistaken for real transitions.

Usage:  py -3.12 projects/vtrux/notes/artifacts/friday_phase3.py
"""

import sys
import os
import re
import glob
import subprocess
from collections import Counter, defaultdict

sys.path.insert(0, ".")

LOGDIR = "../../CANLogs/VtruxLogs"
SESSIONS = ["20260724_160300", "20260724_160330", "20260724_162517",
            "20260724_172621", "20260724_211556"]

GREP_RE = " 0x(6[0-9A-F][0-9A-F]|592|53|55C|308|400) "
HDR = re.compile(r"START DATE AND TIME \d+:\d+:\d+ (\d+):(\d+):(\d+):(\d+)")

# 0x661 is the ONLY id in the grep set that lives on the OBD bus rather than the
# PT bus. Dropping it makes every remaining watched id PT-bus-exclusive, so the
# channel number (which the Android logger renumbers on each USB reconnect) can
# be ignored entirely instead of being mistaken for a signal transition.
SKIP_IDS = {0x661}

MAX_DISTINCT = 16          # stop tracking a byte once it looks analog/counter
MAX_CHANGES = 3000


def chunk_files(session):
    fs = glob.glob(os.path.join(LOGDIR, "vtrux_%s_T*.log" % session))
    return sorted(fs, key=lambda p: int(re.search(r"_T(\d+)\.log$", p).group(1)))


def header_start(path):
    with open(path, "r", errors="replace") as f:
        for _ in range(30):
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
    return "%02d:%02d:%05.2f" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def main():
    prev = {}
    vals = defaultdict(set)
    dead = set()
    changes = Counter()
    events = []
    reconnects = []
    last_ch = None
    day = 0.0
    prev_t = 0.0

    for sess in SESSIONS:
        for path in chunk_files(sess):
            base = header_start(path)
            tag = os.path.basename(path).replace("vtrux_", "").replace(".log", "")
            p = subprocess.Popen(["grep", "-E", GREP_RE, path],
                                 stdout=subprocess.PIPE, text=True,
                                 errors="replace")
            for line in p.stdout:
                f = line.split()
                if len(f) < 7:
                    continue
                try:
                    ts = f[0].split(":")
                    t = (base + int(ts[0]) * 3600 + int(ts[1]) * 60
                         + int(ts[2]) + int(ts[3]) / 10000.0)
                    ch = int(f[2])
                    cid = int(f[3], 16)
                except (ValueError, IndexError):
                    continue

                if cid in SKIP_IDS:
                    continue

                # wall clock rolls past midnight during the last session
                if t + day < prev_t - 3600:
                    day += 86400.0
                t += day
                prev_t = t

                if ch != last_ch:
                    # USB reconnect / new session: channel index changed. All
                    # watched ids are PT-exclusive, so state carries across.
                    reconnects.append((t, last_ch, ch, tag))
                    last_ch = ch

                data = f[6:]
                for i, b in enumerate(data):
                    key = (cid, i)
                    if key in dead:
                        continue
                    s = vals[key]
                    if b not in s:
                        s.add(b)
                        if len(s) > MAX_DISTINCT:
                            dead.add(key)
                            continue
                    pv = prev.get(key)
                    if pv is not None and pv != b:
                        changes[key] += 1
                        if changes[key] > MAX_CHANGES:
                            dead.add(key)
                            continue
                        events.append((t, cid, i, pv, b, tag))
                    prev[key] = b
            p.stdout.close()
            p.wait()

    print("=== reconnect / session boundaries ===")
    for (t, a, b, tag) in reconnects:
        print("  %s  ch %s -> %s   [%s]" % (hhmmss(t), a, b, tag))

    print()
    print("=== status-like bytes (<=%d distinct, <=%d changes) ===" % (MAX_DISTINCT, MAX_CHANGES))
    keep = set()
    for key in sorted(vals):
        if key in dead:
            continue
        n, c = len(vals[key]), changes.get(key, 0)
        if n <= MAX_DISTINCT and c <= MAX_CHANGES:
            keep.add(key)
            print("  0x%-8X B%-2d  distinct=%-3d changes=%-5d  vals=%s"
                  % (key[0], key[1], n, c, " ".join(sorted(vals[key]))))

    print()
    print("=== transitions for bytes that change RARELY (<=60 changes all trip) ===")
    rare = {k for k in keep if changes.get(k, 0) <= 60}
    for (t, cid, i, a, b, tag) in events:
        if (cid, i) in rare:
            print("  %s  0x%-8X B%-2d  %s -> %s   [%s]" % (hhmmss(t), cid, i, a, b, tag))


if __name__ == "__main__":
    main()
