"""Friday 2026-07-24: timeline of the 6xx-band shift-position telemetry.

Fields identified from `logs/vtrux_shifter_disconnect.log`, where the shifter
position box was deliberately unplugged at t=20.3s and reconnected at t=29.5s:

  0x639 B6  bits[5:4] = lever index   (3=Drive, 2=Neutral, 1=.., 0=Park side)
  0x644 B0  bits[7:6] = same lever index, bit4 set
  0x601 B0  bit5      = tracks the same transition (0x20 <-> 0x00)

In that log all three step to the Neutral code the instant the box is unplugged
and step back on reconnect, which matches the documented VCM behaviour of
defaulting to Neutral when it loses a coherent shifter input.

This script prints every transition of those fields across the Friday trip, so a
momentary invalid/neutral excursion during a shift would be visible.
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

GREP_RE = " 0x(639|644|601|592|53) "
HDR = re.compile(r"START DATE AND TIME \d+:\d+:\d+ (\d+):(\d+):(\d+):(\d+)")

# (id, byte) -> (label, mask). Masked so rolling-counter / unrelated bits in the
# same byte do not generate spurious transitions.
WATCH = {
    (0x639, 6): ("LEVER/0x639.B6", 0x70),
    (0x644, 0): ("LEVER2/0x644.B0", 0xC0),
    (0x601, 0): ("SHIFT/0x601.B0", 0x20),
    (0x592, 0): ("IGN/0x592.B0", 0x10),
    (0x053, 1): ("GENMODE/0x053.B1", 0xFF),
}

# 0x639 B6 bits[6:4] -- confirmed against logs/generator-on-then-off.log, where
# M mode engages at t=39.1s (field 3->4) and drops back to Drive at t=53.2s
# (4->3), and against logs/vtrux_shifter_disconnect.log, where unplugging the
# shifter box drives it to 2 (the VCM's documented Neutral safe default).
# 0x644 B0 bits[7:6] carries the same index but only 2 bits, so it cannot
# distinguish M from Park -- 0x639 B6 is the authoritative field.
LEVER = {0: "P", 1: "R", 2: "N", 3: "D", 4: "M", 5: "?5", 6: "?6", 7: "?7"}


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


def annotate(cid, i, v):
    if (cid, i) == (0x639, 6):
        return "  LEVER=%s" % LEVER.get((v >> 4) & 7, "?")
    if (cid, i) == (0x644, 0):
        return "  idx2=%d" % ((v >> 6) & 3)
    if (cid, i) == (0x592, 0):
        return "  ignition=%s" % ("ON" if v & 0x10 else "OFF")
    return ""


def main():
    prev = {}
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
                    cid = int(f[3], 16)
                except (ValueError, IndexError):
                    continue
                if t + day < prev_t - 3600:
                    day += 86400.0
                t += day
                prev_t = t
                data = f[6:]
                for i, bs in enumerate(data):
                    key = (cid, i)
                    if key not in WATCH:
                        continue
                    label, mask = WATCH[key]
                    try:
                        v = int(bs, 16) & mask
                    except ValueError:
                        continue
                    pv = prev.get(key)
                    if pv is not None and pv != v:
                        print("%s  %-18s 0x%02X -> 0x%02X%s   [%s]"
                              % (hhmmss(t), label, pv, v,
                                 annotate(cid, i, v), tag))
                    prev[key] = v
            p.stdout.close()
            p.wait()


if __name__ == "__main__":
    main()
