"""Does the Via warning lamp assert ~15 min after key-on / charge start?

The parts truck has its PE coolant pump missing (0x18FF0320 absent in every
parts-truck log), and the reported behaviour is that the lamp comes on only once
a timeout of roughly 15 minutes has elapsed.

Lamp state is 0x646 B7 bits[6:4]:  0 = HV not up, 6 = HV up / no warning,
5 = HV up / warning latched.

For each log this reports duration, every key-on (0x400 B0 -> 0x0D) and
charge-start (0x18FFD7C0 appearing), and every lamp-field transition with the
elapsed time since the preceding key-on -- which is the number the timeout
hypothesis predicts.

Usage:
    py -3.12 projects/vtrux/notes/artifacts/lamp_timeout_partstruck.py LOG [LOG ...]
"""

import sys
import os
import subprocess

sys.path.insert(0, ".")


def scan(path):
    keyons, lamp, charge_first = [], [], None
    prev_hv, prev_field = None, None
    t_last = 0.0
    p = subprocess.Popen(
        ["grep", "-E", " 0x(646|400|18FFD7C0) ", path],
        stdout=subprocess.PIPE, text=True, errors="replace")
    for line in p.stdout:
        f = line.split()
        if len(f) < 7:
            continue
        try:
            ts = f[0].split(":")
            t = (int(ts[0]) * 3600 + int(ts[1]) * 60 + int(ts[2])
                 + int(ts[3]) / 10000.0)
        except (ValueError, IndexError):
            continue
        t_last = max(t_last, t)
        cid = f[3]
        if cid == "0x400" and len(f) >= 7:
            hv = f[6]
            if hv != prev_hv:
                if hv == "0D":
                    keyons.append(t)
                prev_hv = hv
        elif cid == "0x646" and len(f) >= 14:
            try:
                v = (int(f[13], 16) >> 4) & 7
            except ValueError:
                continue
            if v != prev_field:
                lamp.append((t, prev_field, v))
                prev_field = v
        elif cid == "0x18FFD7C0" and charge_first is None:
            charge_first = t
    p.stdout.close()
    p.wait()
    return t_last, keyons, lamp, charge_first


def main():
    print("%-52s %-9s %-7s %s" % ("log", "duration", "keyons", "lamp transitions"))
    print("-" * 118)
    for path in sys.argv[1:]:
        dur, keyons, lamp, charge = scan(path)
        name = os.path.basename(path)
        print("%-52s %-9s %-7d %s"
              % (name[:52], "%.1f min" % (dur / 60.0), len(keyons),
                 "charge@%.1fmin" % (charge / 60.0) if charge else ""))
        if keyons:
            print("      key-on at: %s"
                  % ", ".join("%.1f min" % (k / 60.0) for k in keyons[:6]))
        for (t, a, b) in lamp:
            if a is None:
                print("      t=%6.1f min  field starts at %d" % (t / 60.0, b))
                continue
            since = ""
            prior = [k for k in keyons if k <= t]
            if prior:
                since = "   (%.1f min after key-on)" % ((t - prior[-1]) / 60.0)
            flag = ""
            if b == 5:
                flag = "   <== LAMP ON"
            elif a == 5:
                flag = "   <== lamp off"
            print("      t=%6.1f min  field %d -> %d%s%s"
                  % (t / 60.0, a, b, since, flag))
        print()


if __name__ == "__main__":
    main()
