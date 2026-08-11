"""Friday 2026-07-24: key on/off cycle timeline with per-window context.

Key state is taken from two independent PT-bus sources so the boundaries can be
cross-checked rather than trusted from one byte:

  0x400 B0   HSC BCM control -- 0x0D = HV enabled (key on), 0x08 = HV down
  0x592 B0   bit4 = IgnitionKeyState (epri-pt-bus)

Each window is annotated with what the truck actually did (lever positions used,
generator runs, whether M was selected) so a given stop can be recognised.

Boundaries that coincide with the start or end of CAN capture are flagged, since
those are logging artefacts, not real key events.

Usage:  py -3.12 projects/vtrux/notes/artifacts/friday_keycycles.py
"""

import sys
import os
import re
import glob
import subprocess

sys.path.insert(0, ".")

LOGDIR = "../../CANLogs/VtruxLogs"
SESSIONS = ["20260724_160300", "20260724_160330", "20260724_162517",
            "20260724_172621", "20260724_211556"]
GREP_RE = " 0x(400|592|53|639) "
HDR = re.compile(r"START DATE AND TIME \d+:\d+:\d+ (\d+):(\d+):(\d+):(\d+)")
LEVER = {0: "P", 1: "R", 2: "N", 3: "D", 4: "M"}


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
    return "%02d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def main():
    events = []
    day, prev_t = 0.0, 0.0
    t_capture_first, t_capture_last = None, None

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
                    data = f[6:]
                except (ValueError, IndexError):
                    continue
                if t + day < prev_t - 3600:
                    day += 86400.0
                t += day
                prev_t = t
                if t_capture_first is None:
                    t_capture_first = t
                t_capture_last = t

                if cid == 0x400 and data:
                    events.append((t, "hv", data[0]))
                elif cid == 0x592 and data:
                    try:
                        events.append((t, "ign", 1 if int(data[0], 16) & 0x10 else 0))
                    except ValueError:
                        pass
                elif cid == 0x53 and len(data) >= 1:
                    try:
                        events.append((t, "gen", 1 if int(data[0], 16) & 0x30 else 0))
                    except ValueError:
                        pass
                elif cid == 0x639 and len(data) >= 7:
                    try:
                        events.append((t, "lev", (int(data[6], 16) >> 4) & 7))
                    except ValueError:
                        pass
            p.stdout.close()
            p.wait()

    events.sort(key=lambda e: e[0])

    # build windows from the HV-enable byte, collecting context inside each
    windows = []
    cur = None
    last = {}
    for t, kind, v in events:
        if kind == "hv":
            if v == "0D" and cur is None:
                cur = {"on": t, "off": None, "levers": [], "gen_runs": 0,
                       "ign_off": []}
            elif v == "08" and cur is not None:
                cur["off"] = t
                windows.append(cur)
                cur = None
        elif cur is not None:
            if kind == "lev":
                nm = LEVER.get(v, "?%d" % v)
                if not cur["levers"] or cur["levers"][-1] != nm:
                    cur["levers"].append(nm)
            elif kind == "gen":
                if last.get("gen") == 0 and v == 1:
                    cur["gen_runs"] += 1
            elif kind == "ign":
                if last.get("ign") == 1 and v == 0:
                    cur["ign_off"].append(t)
        last[kind] = v
    if cur is not None:
        cur["off"] = t_capture_last
        windows.append(cur)

    print("Friday 2026-07-24 -- key on/off cycles (PT bus 0x400 B0: 0x0D=on, 0x08=off)")
    print("CAN capture ran %s -> %s" % (hhmmss(t_capture_first), hhmmss(t_capture_last)))
    print()
    print("%-4s %-9s %-9s %-8s %-9s %-5s %-4s %s"
          % ("win", "KEY ON", "KEY OFF", "on_dur", "off_after", "gen", "M?", "gear sequence"))
    print("-" * 110)
    for n, w in enumerate(windows):
        on, off = w["on"], w["off"]
        nxt = windows[n + 1]["on"] if n + 1 < len(windows) else None
        off_after = "%.1f min" % ((nxt - off) / 60.0) if nxt else "-"
        note = ""
        if abs(on - t_capture_first) < 2:
            note += "  [on = capture start, truck was already on]"
        if abs(off - t_capture_last) < 5:
            note += "  [off = capture end]"
        seq = " ".join(w["levers"])
        if len(seq) > 46:
            seq = seq[:43] + "..."
        print("%-4s %-9s %-9s %-8s %-9s %-5d %-4s %s%s"
              % ("W%d" % n, hhmmss(on), hhmmss(off),
                 "%.1fm" % ((off - on) / 60.0), off_after,
                 w["gen_runs"], "YES" if "M" in w["levers"] else "-",
                 seq, note))


if __name__ == "__main__":
    main()
