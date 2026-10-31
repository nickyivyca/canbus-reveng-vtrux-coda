"""Per-chunk state summary for the 2026-06-17 evening -> 2026-06-18 00:20 drive.

Context: the owner recalls the truck faulting, then unplugging the extra Via 12V
fusebox (leaving the GM one intact) to reset it, around the smog-test work. This
script lays out every chunk from the end of the 06-17 19:39 drive to the end of the
06-18 00:20 drive so the initial fault, the fusebox unplug/replug, and the 00:21:26
AC 10 01 trip can be told apart and their fault codes kept separate.

Per chunk: header start, duration, which modules are on the PT bus (frame counts for
VCM / BMS / GENE / DCDC / TCM / pack boards), change points of VCM OperationState,
key state, BMS hvil/epo/alarm, contactor state, distinct 0x460 records, VCM 0x617 B7
values, dash lamp field (0x646 B7[6:4]), GM run/crank, max GM speed, and the ECM's
mode-01 PID-01 reply (MIL + DTC count) on the OBD bus.

Run from project root:
  python3.13 projects/vtrux/notes/artifacts/via_fusebox_sessions.py > projects/vtrux/notes/artifacts/via_fusebox_sessions.txt
"""
import sys
sys.path.insert(0, ".")

import glob
import re
from collections import Counter, defaultdict

OPSTATE = {0: "INIT", 1: "STBY", 2: "ACTIVATION", 3: "DEACTIVATION", 4: "OPERATIONAL", 5: "FAILURE", 6: "SHTDWN", 7: "WAIT4COOLING", 8: "PWR_OFF_RDY"}
MAINC = {0: "ALL_OPEN", 2: "CLOSE_MAINR", 5: "CLOSE_MAINN", 7: "WAIT_PRECHARGE", 8: "CLOSE_MAINP", 9: "OPEN_MAINR", 11: "PN_CLOSED_DRIVE", 12: "P_CLOSED_CHARGE", 13: "SHUTDOWN_REQUEST", 14: "ALL_OPEN_SHUTDOWN"}
HDR = re.compile(r"START DATE AND TIME\s+(\d+):(\d+):(\d+)\s+(\d+):(\d+):(\d+):(\d+)")
GROUPS = {
    "VCM": {0x400, 0x53, 0x592, 0x617, 0x639, 0x646, 0x51},
    "BMS": {0x410, 0x440, 0x460, 0x430},
    "GENE": {0x470, 0x482, 0x54},
    "DCDC": {0x18FFD6B3, 0x18FECAB3},
    "TCM": {0x308, 0x55C, 0x580},
    "packboards": {0x370, 0x371, 0x372, 0x373, 0x374, 0x375},
    "TRAC_obd": {0x044, 0x462},
}
WATCH = set().union(*GROUPS.values()) | {0x3E9, 0x1F1, 0x7E8}

FILES = (sorted(glob.glob("../../CANLogs/VtruxLogs/vtrux_20260617_193900_T3[45].log"))
         + sorted(glob.glob("../../CANLogs/VtruxLogs/vtrux_20260617_2*_T*.log"))
         + sorted(glob.glob("../../CANLogs/VtruxLogs/vtrux_20260618_002023_T*.log")))


def tsec(s):
    a = s.split(":")
    return int(a[0]) * 3600 + int(a[1]) * 60 + int(a[2]) + int(a[3]) / 10000.0


def hms(sec):
    sec = sec % 86400
    return "%02d:%02d:%06.3f" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def summarize(path):
    hdr = None
    cnt = Counter()
    chan = Counter()
    ev = []
    last = {}
    recs = {}
    b7 = Counter()
    lamp = Counter()
    pid01 = Counter()
    maxspeed = 0.0
    t_first = None
    t_last = 0.0

    def emit(t, k, v):
        if last.get(k) != v:
            ev.append((t, k, last.get(k), v))
            last[k] = v

    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if line[0] == "*":
                m = HDR.search(line)
                if m and hdr is None:
                    d, mo, y, hh, mm, ss, ms = (int(x) for x in m.groups())
                    hdr = hh * 3600 + mm * 60 + ss + ms / 1000.0
                continue
            p = line.split()
            if len(p) < 6 or not p[3].startswith("0x"):
                continue
            aid = int(p[3], 16)
            t = tsec(p[0])
            if t_first is None:
                t_first = t
            t_last = t
            if aid not in WATCH:
                continue
            ch = p[2]
            try:
                b = bytes(int(x, 16) for x in p[6:6 + int(p[5])])
            except ValueError:
                continue
            cnt[aid] += 1
            if aid == 0x410 and len(b) == 8:
                chan[ch] += 1
                emit(t, "bms hvil", (b[0] >> 3) & 1)
                emit(t, "bms epo", (b[0] >> 1) & 1)
                emit(t, "bms alarm", (b[1] >> 6) & 3)
                emit(t, "bms ready", b[0] & 1)
            elif aid == 0x440 and len(b) == 8:
                emit(t, "bms mainc", MAINC.get((b[0] >> 2) & 0xF, (b[0] >> 2) & 0xF))
            elif aid == 0x460 and len(b) == 8 and b[0] in (1, 2):
                for k in (2, 5):
                    r = b[k:k + 3].hex(" ")
                    if r != "00 00 00" and r not in recs:
                        recs[r] = t
            elif aid == 0x53 and b:
                emit(t, "vcm opstate", OPSTATE.get(b[0] & 0xF, b[0] & 0xF))
            elif aid == 0x592 and b:
                emit(t, "vcm key592", (b[0] >> 4) & 1)
            elif aid == 0x617 and len(b) == 8:
                b7["%02X" % b[7]] += 1
            elif aid == 0x646 and len(b) == 8:
                lamp[(b[7] >> 4) & 7] += 1
                emit(t, "lamp field", (b[7] >> 4) & 7)
            elif aid == 0x400 and b:
                emit(t, "vcm 0x400 B0", "0x%02X" % b[0])
            elif aid == 0x1F1 and b:
                emit(t, "GM run/crank", (b[0] >> 3) & 1)
            elif aid == 0x3E9 and len(b) >= 2:
                maxspeed = max(maxspeed, ((b[0] & 0x7F) << 8 | b[1]) * 0.0156)
            elif aid == 0x7E8 and len(b) >= 7 and b[1] == 0x41 and b[2] == 0x01:
                pid01["MIL=%d DTCs=%d" % (b[3] >> 7, b[3] & 0x7F)] += 1

    name = path.split("/")[-1].replace(".log", "")
    print("=" * 100)
    print("%s  start=%s  span=%.0f s  first-frame-line-time=%.2f" % (name, hms(hdr) if hdr else "?", (t_last - (t_first or 0)), t_first or 0))
    print("  modules on bus: " + "  ".join("%s=%s" % (g, "/".join(str(cnt[i]) for i in sorted(ids))) for g, ids in GROUPS.items()))
    print("  0x617.B7=%s  lamp=%s  maxspeed=%.0f km/h  ECM PID01=%s" % (dict(b7), dict(lamp), maxspeed, dict(pid01)))
    print("  0x460 records (first seen): " + (", ".join("%s@%.1f" % (r, t) for r, t in sorted(recs.items(), key=lambda x: x[1])) or "(none)"))
    shown = 0
    for t, k, a, v in ev:
        if k == "lamp field" and shown > 200:
            continue
        print("    %8.2f (%s)  %-14s %s -> %s" % (t, hms(hdr + t) if hdr else "?", k, a, v))
        shown += 1
        if shown > 60:
            print("    ... (%d more change points)" % (len(ev) - shown))
            break


for f in FILES:
    summarize(f)
