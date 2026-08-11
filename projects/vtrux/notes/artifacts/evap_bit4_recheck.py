"""Re-examine 0x63A B7 bit4 against evap state across every session that has both.

Phase 6 of evap-cycle-analysis.md claimed bit4 == "purge actually in progress",
based on the 2026-07-24 session plus the onset of vtrux_20260719_164520.

Counter-evidence found 2026-08-09: in vtrux_20260719_190019 the purge is plainly
running (gen_power > 0, vcm_evap_counter climbing 536 -> 817) yet bit4 is 0 for
all 66159 sampled frames. This script rebuilds the full picture so the real
meaning of bit4 can be pinned down instead of guessed.

For every session containing 0x63A it emits:
  - bit4 on/off intervals with durations
  - the evap state (active/counter) at each bit4 edge
  - whether the counter was advancing while bit4 was set vs clear

Usage:
    py -3.12 projects/vtrux/notes/artifacts/evap_bit4_recheck.py [SESSION_PREFIX ...]

With no arguments it scans every session that contains 0x649 activity.
"""

import sys
import os
import re
import glob
import subprocess

sys.path.insert(0, ".")

LOGDIR = "../../CANLogs/VtruxLogs"
HDR = re.compile(r"START DATE AND TIME \d+:\d+:\d+ (\d+):(\d+):(\d+):(\d+)")
CHUNK = re.compile(r"_T(\d+)\.log$")


def sessions():
    out = set()
    for p in glob.glob(os.path.join(LOGDIR, "vtrux_*_T*.log")):
        out.add(CHUNK.sub("", os.path.basename(p)))
    return sorted(out)


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


def scan(prefix):
    fs = chunk_files(prefix)
    if not fs:
        return None
    t0 = header_start(fs[0])

    active = counter = bit4 = None
    edges = []            # (t, new_bit4, active, counter)
    # counter advance accounted separately for bit4 set vs clear
    adv = {0: 0, 1: 0}
    dur = {0: 0.0, 1: 0.0}
    last_counter = None
    last_t = None
    n649 = 0
    n63a = 0

    for path in fs:
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
                d = [int(x, 16) for x in f[6:]]
            except (ValueError, IndexError):
                continue

            if f[3] == "0x649" and len(d) >= 5:
                n649 += 1
                active = 1 if d[4] & 0x80 else 0
                c = ((d[2] & 0x0F) << 8) | d[3]
                if last_counter is not None and bit4 is not None and c > last_counter:
                    adv[bit4] += c - last_counter
                last_counter = c
                counter = c
            elif f[3] == "0x63A" and len(d) >= 8:
                n63a += 1
                nb = 1 if d[7] & 0x10 else 0
                if bit4 is not None:
                    if last_t is not None:
                        dur[bit4] += t - last_t
                    if nb != bit4:
                        edges.append((t, nb, active, counter))
                bit4 = nb
                last_t = t
        p.stdout.close()
        p.wait()

    if not n63a or not n649:
        return None
    return dict(prefix=prefix, t0=t0, edges=edges, adv=adv, dur=dur,
                n649=n649, n63a=n63a, final=(active, counter, bit4))


def main():
    targets = sys.argv[1:] or sessions()
    for pref in targets:
        r = scan(pref)
        if not r:
            continue
        # only report sessions where evap was doing something or bit4 moved
        if not r["edges"] and r["adv"][0] == 0 and r["adv"][1] == 0:
            continue
        print("=== %s   0x649=%d 0x63A=%d" % (pref, r["n649"], r["n63a"]))
        for (t, nb, a, c) in r["edges"]:
            print("    bit4 -> %d at %s (t=%7.1f)  active=%s counter=%s"
                  % (nb, hhmmss(t), t - r["t0"], a, c))
        print("    counter advance while bit4=1: %d   while bit4=0: %d"
              % (r["adv"][1], r["adv"][0]))
        print("    time  with bit4=1: %.1f s      bit4=0: %.1f s"
              % (r["dur"][1], r["dur"][0]))
        print("    final active=%s counter=%s bit4=%s" % r["final"])
        print()


if __name__ == "__main__":
    main()
