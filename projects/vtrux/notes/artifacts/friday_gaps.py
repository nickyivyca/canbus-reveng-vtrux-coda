"""Friday 2026-07-24: find gaps in CAN capture coverage.

The Android logger's USB connection is unreliable, so an apparent "key off"
period may instead be a logging dropout -- and a key off/on that happened during
a dropout would be invisible in the key-cycle timeline.

This measures actual coverage from frame timestamps (exact, independent of any
signal), then uses the PT-bus odometer to say what the truck was doing across
each gap:

  0x625 B0-B2   VehicleOdometer, 24-bit BE, 1 km/count (per projects/vtrux/README.md)

1 km/count is coarse -- at highway speed that is roughly 36 s per tick -- so the
odometer cannot resolve short gaps. It can still answer the question that
matters: did the truck cover ground while the logger was down? Any odometer
advance across a gap means driving continued unlogged.

Usage:  py -3.12 projects/vtrux/notes/artifacts/friday_gaps.py [min_gap_seconds]
"""

import sys
import os
import re
import glob

sys.path.insert(0, ".")

LOGDIR = "../../CANLogs/VtruxLogs"
SESSIONS = ["20260724_160300", "20260724_160330", "20260724_162517",
            "20260724_172621", "20260724_211556"]
HDR = re.compile(r"START DATE AND TIME \d+:\d+:\d+ (\d+):(\d+):(\d+):(\d+)")

MIN_GAP = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0


def chunk_files(session):
    fs = glob.glob(os.path.join(LOGDIR, "vtrux_%s_T*.log" % session))
    return sorted(fs, key=lambda p: int(re.search(r"_T(\d+)\.log$", p).group(1)))


def hhmmss(sec):
    sec = sec % 86400
    return "%02d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def main():
    day, prev_t = 0.0, 0.0
    last_t = None
    gaps = []
    odo_samples = []          # (t, odometer_km) for every 0x625 frame seen
    spd_samples = []          # (t, km/h) derived from 0x5A2 trac_rpm
    total_frames = 0
    covered = 0.0
    first_t = None

    for sess in SESSIONS:
        for path in chunk_files(sess):
            base = 0.0
            with open(path, "r", errors="replace") as f:
                for _ in range(60):
                    line = f.readline()
                    if not line:
                        break
                    m = HDR.search(line)
                    if m:
                        hh, mm, ss, ms = m.groups()
                        base = (int(hh) * 3600 + int(mm) * 60 + int(ss)
                                + int(ms) / 1000.0)
                        break
                tag = os.path.basename(path).replace("vtrux_", "").replace(".log", "")
                for line in f:
                    if not line or line[0] != "0":
                        continue
                    p = line.split()
                    if len(p) < 7:
                        continue
                    try:
                        ts = p[0].split(":")
                        t = (base + int(ts[0]) * 3600 + int(ts[1]) * 60
                             + int(ts[2]) + int(ts[3]) / 10000.0)
                    except (ValueError, IndexError):
                        continue
                    if t + day < prev_t - 3600:
                        day += 86400.0
                    t += day
                    prev_t = t
                    total_frames += 1
                    if first_t is None:
                        first_t = t

                    # 0x5A2 B2-B3 = trac_rpm, LE uint16 centred at 32768,
                    # ~64.3 rpm per km/h (vtrux-powertrain-experimental.dbc).
                    # Far finer than the 1 km odometer for deciding whether the
                    # truck was rolling either side of a gap -- and a key cycle
                    # cannot happen while it is rolling.
                    if p[3] == "0x5A2" and len(p) >= 10:
                        try:
                            raw = int(p[8], 16) | (int(p[9], 16) << 8)
                            spd_samples.append((t, abs(raw - 32768) / 64.3))
                        except ValueError:
                            pass

                    if p[3] == "0x625" and len(p) >= 9:
                        try:
                            odo_samples.append(
                                (t, (int(p[6], 16) << 16) | (int(p[7], 16) << 8)
                                 | int(p[8], 16)))
                        except ValueError:
                            pass

                    if last_t is not None:
                        d = t - last_t
                        if d >= MIN_GAP:
                            gaps.append((last_t, t, d, tag))
                        else:
                            covered += d
                    last_t = t

    span = last_t - first_t
    print("Friday 2026-07-24 CAN capture coverage")
    print("  span    : %s -> %s  (%.1f min)"
          % (hhmmss(first_t), hhmmss(last_t), span / 60.0))
    print("  frames  : %d" % total_frames)
    print("  covered : %.1f min   uncovered: %.1f min"
          % (covered / 60.0, (span - covered) / 60.0))
    print()
    if odo_samples:
        print("  odometer: %d -> %d km over the day (%d km total)"
              % (odo_samples[0][1], odo_samples[-1][1],
                 odo_samples[-1][1] - odo_samples[0][1]))
    print()

    def odo_before(t):
        v = None
        for st, sv in odo_samples:
            if st <= t:
                v = sv
            else:
                break
        return v

    def odo_after(t):
        for st, sv in odo_samples:
            if st >= t:
                return sv
        return None

    def spd_before(t):
        v = None
        for st, sv in spd_samples:
            if st <= t:
                v = sv
            else:
                break
        return v

    def spd_after(t):
        for st, sv in spd_samples:
            if st >= t:
                return sv
        return None

    print("=== gaps >= %.0fs ===" % MIN_GAP)
    print("%-9s %-9s %-9s %-12s %-16s %s"
          % ("gap start", "gap end", "duration", "odo across", "speed in/out",
             "could a key cycle hide here?"))
    print("-" * 108)
    for (a, b, d, tag) in gaps:
        oa, ob = odo_before(a), odo_after(b)
        odo = "%d->%d" % (oa, ob) if (oa is not None and ob is not None) else "n/a"
        sa, sb = spd_before(a), spd_after(b)
        spd = "%.0f -> %.0f km/h" % (sa, sb) if (sa is not None and sb is not None) else "n/a"
        if sa is not None and sb is not None and sa > 5 and sb > 5:
            verdict = "NO - rolling on both sides"
        elif oa is not None and ob is not None and ob > oa:
            verdict = "unlikely - covered ~%d km in gap" % (ob - oa)
        else:
            verdict = "YES - stopped, key cycle would be invisible"
        print("%-9s %-9s %-9s %-12s %-16s %s"
              % (hhmmss(a), hhmmss(b), "%.1fm" % (d / 60.0), odo, spd, verdict))


if __name__ == "__main__":
    main()
