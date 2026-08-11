"""Phase 4: per-ignition-window state profile for the Friday 2026-07-24 trip.

The reported symptom is a latched warning that survived until a key off/on and
never came back. So the discriminating question is not "what changed" but "which
state was held during one key-on window and never during the others".

This splits the trip into ignition windows using 0x400 B0 (the HSC BCM control
byte: 0x0D = HV enabled / key on, 0x08 = HV down / key off), then records for
each PT-bus status byte how long each value was held inside each window. A byte
whose value appears in exactly one window -- and holds there -- is the candidate
latched-fault flag.

Usage:  py -3.12 projects/vtrux/notes/artifacts/friday_phase4.py
"""

import sys
import os
import re
import glob
import subprocess
from collections import defaultdict

sys.path.insert(0, ".")

LOGDIR = "../../CANLogs/VtruxLogs"
SESSIONS = ["20260724_160300", "20260724_160330", "20260724_162517",
            "20260724_172621", "20260724_211556"]

GREP_RE = " 0x(6[0-9A-F][0-9A-F]|592|53|55C|308|400) "
HDR = re.compile(r"START DATE AND TIME \d+:\d+:\d+ (\d+):(\d+):(\d+):(\d+)")
SKIP_IDS = {0x661}          # only OBD-bus id in the grep set
NOISY_IDS = {0x6A0}         # rotating/hashed field, not a status word

MAX_DISTINCT = 16
MIN_HOLD = 5.0              # seconds a value must be held to count as "held"


def chunk_files(session):
    fs = glob.glob(os.path.join(LOGDIR, "vtrux_%s_T*.log" % session))
    return sorted(fs, key=lambda p: int(re.search(r"_T(\d+)\.log$", p).group(1)))


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
    return "%02d:%02d:%05.2f" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def main():
    # (key, value) -> {window_index: seconds held}
    hold = defaultdict(lambda: defaultdict(float))
    vals = defaultdict(set)
    dead = set()

    cur = {}            # key -> (value, t_started)
    windows = []        # list of [t_on, t_off]
    win = -1
    ign_on = False

    day, prev_t = 0.0, 0.0

    for sess in SESSIONS:
        for path in chunk_files(sess):
            base = header_start(path)
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
                    cid = int(f[3], 16)
                except (ValueError, IndexError):
                    continue
                if cid in SKIP_IDS or cid in NOISY_IDS:
                    continue
                if t + day < prev_t - 3600:
                    day += 86400.0
                t += day
                prev_t = t

                data = f[6:]

                # ignition window tracking from 0x400 B0
                if cid == 0x400 and data:
                    b0 = data[0]
                    on = (b0 == "0D")
                    off = (b0 == "08")
                    if on and not ign_on:
                        ign_on = True
                        win += 1
                        windows.append([t, None])
                    elif off and ign_on:
                        ign_on = False
                        if windows:
                            windows[-1][1] = t

                if win < 0:
                    continue

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
                    pv = cur.get(key)
                    if pv is None:
                        cur[key] = (b, t)
                    elif pv[0] != b:
                        hold[(key, pv[0])][win] += t - pv[1]
                        cur[key] = (b, t)
            p.stdout.close()
            p.wait()

    # flush trailing holds
    for key, (v, t0) in cur.items():
        if key not in dead:
            hold[(key, v)][win] += prev_t - t0

    print("=== ignition windows (from 0x400 B0: 0x0D=key on, 0x08=key off) ===")
    for n, (a, b) in enumerate(windows):
        print("  W%-2d  %s -> %s   (%.1f min)"
              % (n, hhmmss(a), hhmmss(b) if b else "end",
                 ((b or prev_t) - a) / 60.0))

    nwin = len(windows)
    print()
    print("=== values held >=%.0fs that occur in EXACTLY ONE ignition window ===" % MIN_HOLD)
    print("    (a latched fault flag should look like this)")
    hits = []
    for (key, v), per in hold.items():
        if key in dead:
            continue
        wins = [w for w, sec in per.items() if sec >= MIN_HOLD]
        if len(wins) == 1 and nwin > 2:
            hits.append((key, v, wins[0], per[wins[0]]))
    hits.sort(key=lambda h: (-h[3]))
    for (key, v, w, sec) in hits:
        print("  0x%-6X B%-2d value=%-4s  W%-2d only, held %8.1fs   (all values: %s)"
              % (key[0], key[1], v, w, sec, " ".join(sorted(vals[key]))))

    print()
    print("=== per-window value profile for every tracked byte ===")
    keys = sorted({k for (k, v) in hold if k not in dead})
    for key in keys:
        row = []
        for w in range(nwin):
            vv = [v for (k, v), per in hold.items()
                  if k == key and per.get(w, 0) >= MIN_HOLD]
            row.append("W%d:%s" % (w, "/".join(sorted(vv)) if vv else "-"))
        print("  0x%-6X B%-2d  %s" % (key[0], key[1], "  ".join(row)))


if __name__ == "__main__":
    main()
