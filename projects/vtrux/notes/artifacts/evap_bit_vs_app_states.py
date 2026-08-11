"""Does 0x63A B7 bit4 agree with the Android app's derived evap states?

The app (android-app/notes/evap-bug.md, implemented 2026-07-21) derives:

    active==0            -> COMPLETE
    active==1, counter>0 -> PURGE
    active==1, counter==0-> PENDING

from 0x649 B4 bit7 (vcm_evap_active) and 0x649 B2[3:0]:B3 (vcm_evap_counter).

0x63A B7 bit4 was identified 2026-07-26 as "purge actually in progress". This
checks it against the app's logic on the app's own regression session
(vtrux_20260719_164520, the 2026-07-19 drive that exposed the original bug).

Usage:
    py -3.12 projects/vtrux/notes/artifacts/evap_bit_vs_app_states.py SESSION_PREFIX
"""

import sys
import os
import re
import glob
import subprocess

sys.path.insert(0, ".")

LOGDIR = "../../CANLogs/VtruxLogs"
HDR = re.compile(r"START DATE AND TIME \d+:\d+:\d+ (\d+):(\d+):(\d+):(\d+)")


def chunk_files(prefix):
    fs = glob.glob(os.path.join(LOGDIR, "%s_T*.log" % prefix))
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
    sec %= 86400
    return "%02d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def app_state(active, counter):
    if active is None:
        return "UNKNOWN"
    if active == 0:
        return "COMPLETE"
    return "PURGE" if (counter or 0) > 0 else "PENDING"


def main():
    prefix = sys.argv[1]
    active = counter = bit4 = None
    prev = None
    disagree = 0
    total = 0
    first_mismatch_run = None

    for path in chunk_files(prefix):
        base = header_start(path)
        p = subprocess.Popen(["grep", "-E", " 0x(649|63A) ", path],
                             stdout=subprocess.PIPE, text=True, errors="replace")
        for line in p.stdout:
            f = line.split()
            if len(f) < 7:
                continue
            try:
                ts = f[0].split(":")
                t = (base + int(ts[0]) * 3600 + int(ts[1]) * 60
                     + int(ts[2]) + int(ts[3]) / 10000.0)
                data = [int(x, 16) for x in f[6:]]
            except (ValueError, IndexError):
                continue
            if f[3] == "0x649" and len(data) >= 5:
                active = 1 if data[4] & 0x80 else 0
                counter = ((data[2] & 0x0F) << 8) | data[3]
            elif f[3] == "0x63A" and len(data) >= 8:
                bit4 = 1 if data[7] & 0x10 else 0
            else:
                continue

            if active is None or bit4 is None:
                continue
            st = app_state(active, counter)
            total += 1
            expect_bit4 = 1 if st == "PURGE" else 0
            if bit4 != expect_bit4:
                disagree += 1
                if first_mismatch_run is None:
                    first_mismatch_run = (t, st, counter, bit4)
            key = (st, bit4)
            if key != prev:
                print("%s  app=%-9s counter=%-5s 0x63A_bit4=%d%s"
                      % (hhmmss(t), st, counter, bit4,
                         "   <== DISAGREE" if bit4 != expect_bit4 else ""))
                prev = key
        p.stdout.close()
        p.wait()

    print()
    print("samples=%d  disagreements=%d (%.2f%%)"
          % (total, disagree, 100.0 * disagree / max(1, total)))
    if first_mismatch_run:
        print("first disagreement at %s (app=%s counter=%s bit4=%d)"
              % (hhmmss(first_mismatch_run[0]), first_mismatch_run[1],
                 first_mismatch_run[2], first_mismatch_run[3]))


if __name__ == "__main__":
    main()
