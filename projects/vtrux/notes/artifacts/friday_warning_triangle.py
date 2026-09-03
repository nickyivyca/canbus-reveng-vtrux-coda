"""Friday 2026-07-24 trip: locate the signature of the yellow warning triangle.

Working theory (user): a momentary invalid shift position around a shift into M
tripped a latched warning that survived until a key off/on cycle.

Phased architecture -- enable phases via command line, e.g.:
    py -3.12 projects/vtrux/notes/artifacts/friday_warning_triangle.py 1
"""

import sys
import os
import re
import glob
from collections import defaultdict, Counter

sys.path.insert(0, ".")

LOGDIR = "../../CANLogs/VtruxLogs"
OUT = "projects/vtrux/notes/artifacts"

HDR_TIME = re.compile(r"START DATE AND TIME (\d+):(\d+):(\d+) (\d+):(\d+):(\d+):(\d+)")
FRAME = re.compile(
    r"^(\d\d):(\d\d):(\d\d):(\d{4})\s+(\w+)\s+(\d+)\s+0x([0-9A-Fa-f]+)\s+(\w)\s+(\d+)\s*(.*)$"
)

# Anchor IDs per AGENTS.md / projects/vtrux/README.md -- bus numbers are arbitrary, identify by content
PT_ANCHORS = {0x051, 0x410, 0x420, 0x430, 0x440, 0x592}
OBD_ANCHORS = {0x043, 0x044, 0x441, 0x442, 0x44A, 0x462}


def chunk_files(session):
    fs = glob.glob(os.path.join(LOGDIR, "vtrux_%s_T*.log" % session))
    return sorted(fs, key=lambda p: int(re.search(r"_T(\d+)\.log$", p).group(1)))


def header_start(path):
    """Absolute wall-clock start of this chunk, in seconds since midnight."""
    with open(path, "r", errors="replace") as f:
        for _ in range(20):
            line = f.readline()
            if not line:
                break
            m = HDR_TIME.search(line)
            if m:
                _, _, _, hh, mm, ss, ms = m.groups()
                return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000.0
    return None


def parse_ts(m):
    """BUSMASTER HH:MM:SS:TTTT where TTTT = 0.1 ms ticks."""
    h, mi, s, t = m.group(1), m.group(2), m.group(3), m.group(4)
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(t) / 10000.0


def hhmmss(sec):
    sec = sec % 86400
    return "%02d:%02d:%06.3f" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def iter_frames(path):
    """Yield (rel_t, channel, canid, dlc, databytes_list)."""
    with open(path, "r", errors="replace") as f:
        for line in f:
            if not line or line[0] != "0":
                continue
            m = FRAME.match(line)
            if not m:
                continue
            yield (
                parse_ts(m),
                int(m.group(6)),
                int(m.group(7), 16),
                int(m.group(9)),
                m.group(10).split(),
            )


# ---------------------------------------------------------------- phase 1
def phase1(sessions):
    """Index chunks: wall-clock span + channel->bus mapping."""
    for sess in sessions:
        files = chunk_files(sess)
        print("=" * 78)
        print("SESSION %s  (%d chunks)" % (sess, len(files)))
        print("=" * 78)
        first_start = header_start(files[0])
        last = files[-1]
        last_start = header_start(last)
        # last frame time of final chunk
        end_rel = 0.0
        with open(last, "r", errors="replace") as f:
            for line in f:
                if line and line[0] == "0":
                    m = FRAME.match(line)
                    if m:
                        end_rel = parse_ts(m)
        print("  start : %s" % hhmmss(first_start))
        print("  end   : %s" % hhmmss(last_start + end_rel))
        print("  span  : %.1f min" % ((last_start + end_rel - first_start) / 60.0))

        # channel -> bus, from first chunk
        seen = defaultdict(set)
        n = 0
        for _, ch, cid, _, _ in iter_frames(files[0]):
            seen[ch].add(cid)
            n += 1
            if n > 400000:
                break
        for ch in sorted(seen):
            ids = seen[ch]
            pt = len(ids & PT_ANCHORS)
            obd = len(ids & OBD_ANCHORS)
            if pt >= 3 and obd == 0:
                bus = "PT"
            elif obd >= 3:
                bus = "OBD"
            else:
                bus = "VEHICLE"
            print("  ch%-2d -> %-8s (%d unique ids)" % (ch, bus, len(ids)))
        print()


# ---------------------------------------------------------------- phase 2
def phase2(sessions, pt_ch, veh_ch):
    """Timeline of ignition, gear/lever position, and HCU DTC across a session."""
    for sess in sessions:
        files = chunk_files(sess)
        base0 = header_start(files[0])
        print("=" * 78)
        print("SESSION %s -- ignition / gear / DTC timeline" % sess)
        print("=" * 78)
        prev = {}
        dtc_seen = Counter()
        for path in files:
            base = header_start(path) - base0
            tag = os.path.basename(path)
            for rel, ch, cid, dlc, data in iter_frames(path):
                t = base + rel
                if cid == 0x65B:
                    dtc_seen[" ".join(data)] += 1
                    continue
                if ch == pt_ch and cid == 0x592 and len(data) >= 8:
                    # IgnitionKeyState / EVSE / export live in B0 per epri-pt-bus
                    key = ("0x592.B0", data[0])
                elif ch == veh_ch and cid == 0x1F5 and len(data) >= 6:
                    key = ("0x1F5", " ".join(data))
                elif ch == pt_ch and cid == 0x6000001 and len(data) >= 8:
                    key = ("EPT_HMI", " ".join(data))
                else:
                    continue
                name = key[0]
                if prev.get(name) != key[1]:
                    print("  t=%9.2f  %-10s %s   [%s]" % (t, name, key[1], tag))
                    prev[name] = key[1]
        if dtc_seen:
            print("  --- 0x65B HCU DTC payloads seen ---")
            for pl, c in dtc_seen.most_common(30):
                print("      %s  x%d" % (pl, c))
        else:
            print("  --- no 0x65B frames in session ---")
        print()


if __name__ == "__main__":
    phases = sys.argv[1:] or ["1"]
    SESSIONS = [
        "20260724_160300",
        "20260724_160330",
        "20260724_162517",
        "20260724_172621",
        "20260724_211556",
    ]
    if "1" in phases:
        phase1(SESSIONS)
