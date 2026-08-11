"""Trace 0x63A B7 (whole byte) against evap state and generator power.

0x63A B7 takes five values across the 2026-07-19 / 2026-07-24 sessions:

    0x04  bits[7:6]=00                   (HV/VCM not up)
    0xC4  bits[7:6]=11  bit5=0 bit4=0
    0xD4  bits[7:6]=11  bit5=0 bit4=1
    0xE4  bits[7:6]=11  bit5=1 bit4=0
    0xF4  bits[7:6]=11  bit5=1 bit4=1

So bits[5:4] is a 2-bit field, and all four combinations occur. The Phase 6
claim that bit4 alone == "purge in progress" is contradicted by
vtrux_20260719_190019, where the counter advances 536 -> 901 with bit4 = 0 and
bit5 = 1 (0xE4 only).

This prints every B7 transition with the evap state and generator power at that
moment, so the two bits can be separated.

Usage:
    py -3.12 projects/vtrux/notes/artifacts/evap_bit4_trace.py SESSION_PREFIX ...
"""

import sys
import os
import re
import glob
import subprocess

sys.path.insert(0, ".")

import cantools

LOGDIR = "../../CANLogs/VtruxLogs"
HDR = re.compile(r"START DATE AND TIME \d+:\d+:\d+ (\d+):(\d+):(\d+):(\d+)")
CHUNK = re.compile(r"_T(\d+)\.log$")

DB = cantools.database.load_file("projects/vtrux/vtrux-powertrain-experimental.dbc")


def chunk_files(prefix):
    fs = glob.glob(os.path.join(LOGDIR, "%s_T*.log" % prefix))
    return sorted(fs, key=lambda p: int(CHUNK.search(p).group(1)))


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
    sec %= 86400
    return "%02d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def trace(prefix):
    fs = chunk_files(prefix)
    if not fs:
        print("no chunks for %s" % prefix)
        return
    t0 = header_start(fs[0])
    active = counter = genp = rpm = None
    prev_b7 = None
    print("=== %s" % prefix)
    print("    %-8s %-9s %-6s  %-7s %-8s %-9s %s"
          % ("time", "t", "B7", "bits54", "active", "counter", "gen_power"))
    for path in fs:
        base = header_start(path)
        p = subprocess.Popen(["grep", "-E", " 0x(598|051|63A|649) ", path],
                             stdout=subprocess.PIPE, text=True, errors="replace")
        for line in p.stdout:
            f = line.split()
            if len(f) < 7:
                continue
            try:
                ts = f[0].split(":")
                t = (base + int(ts[0]) * 3600 + int(ts[1]) * 60
                     + int(ts[2]) + int(ts[3]) / 10000.0)
                d = bytes(int(x, 16) for x in f[6:])
            except (ValueError, IndexError):
                continue

            if f[3] == "0x649" and len(d) >= 5:
                active = 1 if d[4] & 0x80 else 0
                counter = ((d[2] & 0x0F) << 8) | d[3]
            elif f[3] == "0x598" and len(d) >= 8:
                try:
                    genp = DB.decode_message(0x598, d)["gen_power"]
                except Exception:
                    pass
            elif f[3] == "0x051" and len(d) >= 8:
                try:
                    rpm = DB.decode_message(0x051, d)["gen_rpm_ref"]
                except Exception:
                    pass
            elif f[3] == "0x63A" and len(d) >= 8:
                b7 = d[7]
                if b7 != prev_b7:
                    bits54 = (b7 >> 4) & 0x03
                    print("    %-8s %8.1f 0x%02X   b54=%d    %-8s %-9s %s  rpm=%s"
                          % (hhmmss(t), t - t0, b7, bits54,
                             active, counter,
                             ("%8.2f" % genp) if genp is not None else "   -",
                             ("%.0f" % rpm) if rpm is not None else "-"))
                    prev_b7 = b7
        p.stdout.close()
        p.wait()
    print()


def main():
    for pref in sys.argv[1:]:
        trace(pref)


if __name__ == "__main__":
    main()
