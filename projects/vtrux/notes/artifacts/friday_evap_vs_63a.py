"""Is 0x63A B7 bit4 an evap signal?

Compares, across Friday session 20260724_162517 (ignition window W1, the one
window where 0x63A B7 bit4 was ever set):

  0x63A B7 bit4          the unexplained flag
  0x649 B4 bit7          vcm_evap_active (cycle pending OR purging)
  0x649 B2[3:0]:B3       vcm_evap_counter (advances only while purging)
  0x53  B0 bit4/5        generator armed/running

Per notes/evap-cycle-analysis.md the counter is 0 when no cycle is active and
frozen while the engine is off, so "counter advancing" is the purge-in-progress
discriminator that vcm_evap_active alone cannot give.

Usage:  py -3.12 projects/vtrux/notes/artifacts/friday_evap_vs_63a.py
"""

import sys
import os
import re
import glob
import subprocess

sys.path.insert(0, ".")

LOGDIR = "../../CANLogs/VtruxLogs"
SESSION = "20260724_162517"
HDR = re.compile(r"START DATE AND TIME \d+:\d+:\d+ (\d+):(\d+):(\d+):(\d+)")
GREP_RE = " 0x(63A|649|53) "


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
    state = {"bit4": None, "evap": None, "cnt": None, "gen": None}
    last_print = -1e9
    print("%-12s %-6s %-6s %-8s %-6s" % ("time", "63A.b4", "evap", "counter", "gen"))
    print("-" * 48)

    for path in chunk_files(SESSION):
        base = header_start(path)
        p = subprocess.Popen(["grep", "-E", GREP_RE, path],
                             stdout=subprocess.PIPE, text=True, errors="replace")
        for line in p.stdout:
            f = line.split()
            if len(f) < 7:
                continue
            try:
                ts = f[0].split(":")
                t = (base + int(ts[0]) * 3600 + int(ts[1]) * 60
                     + int(ts[2]) + int(ts[3]) / 10000.0)
                cid = int(f[3], 16)
                data = [int(x, 16) for x in f[6:]]
            except (ValueError, IndexError):
                continue

            changed = False
            if cid == 0x63A and len(data) >= 8:
                v = 1 if (data[7] & 0x10) else 0
                if v != state["bit4"]:
                    state["bit4"] = v
                    changed = True
            elif cid == 0x649 and len(data) >= 5:
                e = 1 if (data[4] & 0x80) else 0
                c = ((data[2] & 0x0F) << 8) | data[3]
                if e != state["evap"]:
                    state["evap"] = e
                    changed = True
                state["cnt"] = c
            elif cid == 0x53 and len(data) >= 1:
                g = 1 if (data[0] & 0x30) else 0
                if g != state["gen"]:
                    state["gen"] = g
                    changed = True

            # print on any discrete change, plus a periodic sample so the
            # counter's progress is visible between events
            if changed or (t - last_print) > 120:
                last_print = t
                print("%-12s %-6s %-6s %-8s %-6s   %s"
                      % (hhmmss(t), state["bit4"], state["evap"],
                         state["cnt"], state["gen"],
                         "<== CHANGE" if changed else ""))
        p.stdout.close()
        p.wait()


if __name__ == "__main__":
    main()
