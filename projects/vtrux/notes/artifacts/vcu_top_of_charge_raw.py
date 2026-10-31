"""vcu_top_of_charge_raw.py -- the VCU's charger command (0x18EFC000) from the
raw logs of a full charge, on the same absolute time base InfluxDB uses, for
the interposer's top-of-charge characterization (reviewer fork, 2026-10-10).

Time base: exactly what tools/influx_upload.py writes -- per file,
TimebaseIndex().anchor_ns(path, America/Los_Angeles) + frame.timestamp from
parse_file (re-based to the file's first frame). So the output joins to
Influx's `signals` without an offset; the caller still verifies it on the
Low Power command (chgcmd_mode 1 -> 3), which both sources carry.

Page 00: flow = B1, mode = B2. Page 01: Vlim = (B2<<8|B1)*0.05 V,
Ilim = (B4<<8|B3)*0.05 A (machine.py setpoint_ilim_counts).

Prints one line per change of a page's content and channel:
  <epoch_s> p00 flow=<n> mode=<n> ch<k>
  <epoch_s> p01 ilim=<A> vlim=<V> ch<k>
plus a per-channel frame count of 0x18EFC000 at the end (the bus check:
the id must sit on one channel per file).

Run on the Linux box from the project root:
  python3 <this> <out.txt> <log> [<log> ...]
"""
import sys
sys.path.insert(0, ".")
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

from canre.parsers import parse_file
from canre.utils.timebase import TimebaseIndex

ID = 0x18EFC000
TZ = ZoneInfo("America/Los_Angeles")


def main():
    out_path = sys.argv[1]
    paths = [Path(p) for p in sys.argv[2:]]
    tb = TimebaseIndex()
    rows = []
    chans = Counter()
    for p in paths:
        a = tb.anchor_ns(p, TZ)
        if a is None:
            raise RuntimeError("no anchor for %s" % p)
        for fr in parse_file(p):
            if fr.arbitration_id != ID or fr.is_tx:
                continue
            d = bytes(fr.data)
            if len(d) < 5:
                continue
            chans[(p.name, fr.bus)] += 1
            t = a / 1e9 + fr.timestamp
            ch = fr.bus
            if d[0] == 0x00:
                rows.append((t, "p00", "flow=%d mode=%d" % (d[1], d[2]), ch))
            elif d[0] == 0x01:
                rows.append((t, "p01", "ilim=%.2f vlim=%.2f" % (
                    (d[4] << 8 | d[3]) * 0.05, (d[2] << 8 | d[1]) * 0.05), ch))
    rows.sort(key=lambda r: r[0])
    last = {}
    with open(out_path, "w") as f:
        for t, pg, txt, ch in rows:
            key = (txt, ch)
            if last.get(pg) == key:
                continue
            last[pg] = key
            f.write("%.4f %s %s ch%s\n" % (t, pg, txt, ch))
        per_file = {}
        for (name, ch), n in chans.items():
            per_file.setdefault(name, []).append("ch%s:%d" % (ch, n))
        for name in sorted(per_file):
            f.write("# %s %s\n" % (name, " ".join(sorted(per_file[name]))))


if __name__ == "__main__":
    main()
