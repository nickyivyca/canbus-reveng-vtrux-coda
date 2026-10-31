"""partstruck_top_setpoint.py -- the VCU's page-01 current setpoint (Ilim) at
the parts truck's genuine top of charge (vtrux_partstruck_charge), for the
interposer tester's P3 stall question (reviewer, 2026-10-10).

Question: spec 4 sets the override's command to bcm_chg_max. Near the top of
a real charge, did the VCU's own setpoint follow chg_max, or run above it?

Reads the raw BUSMASTER log (one file, 6.2 GB: run on the Linux box).
0x18EFC000 exists only on the powertrain bus. Page 01: Vlim = B1|B2<<8,
Ilim = B3|B4<<8, both 0.05 per count (machine.py setpoint_ilim_counts).
Prints every change of (Ilim, Vlim) with log-relative seconds (BUSMASTER
data-line ticks are 0.1 ms).

Usage (from the project root): python3 <this> <log>
"""
import sys

path = sys.argv[1]
prev = None
with open(path, "rb") as f:
    for raw in f:
        if b" 0x18EFC000 " not in raw:
            continue
        p = raw.split()
        if len(p) < 14 or p[6] != b"01":
            continue
        h, m, s, tick = (int(x) for x in p[0].split(b":"))
        t = h * 3600 + m * 60 + s + tick / 10000.0
        d = [int(x, 16) for x in p[6:14]]
        ilim = (d[4] << 8 | d[3]) * 0.05
        vlim = (d[2] << 8 | d[1]) * 0.05
        key = (round(ilim, 2), round(vlim, 2), p[2])
        if key != prev:
            print("%.1f ilim=%.2f vlim=%.2f ch%s" % (t, ilim, vlim,
                                                     p[2].decode()))
            prev = key
