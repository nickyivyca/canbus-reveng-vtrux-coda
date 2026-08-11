"""Hunt for per-module battery temperature channels (possibly multiplexed).

Reference thermal signal = bcm_cell_tmax (0x430 B4). Correlate every byte of every
BMS-range ID (0x300-0x5FF) against it, over:
  - r_full: whole another_M0 winter session (pack 12->23.5->20 C)
  - r_tail: the post-charge idle tail only (pack FALLS 23.5->20 C, SoC/voltage FLAT)
r_tail is the discriminator: a real temperature channel tracks the tail decline
(high r_tail); a voltage/SoC channel goes flat (low r_tail).

Also: mux scan -- for each ID, if a byte looks like a cycling counter, group another
byte by it and check the per-group values are temp-plausible and bracket tmax/tmin.

Session: another_M0 (Jan 23, post-swap) -- big clean thermal swing + long idle tail.
"""
import sys
sys.path.insert(0, ".")

import glob
import math
import subprocess
from collections import defaultdict

import cantools

from battery_fan_signature import parse_header_time, decode_line

pt = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
M430 = pt.get_message_by_frame_id(0x430)

FILES = sorted(
    glob.glob("projects/vtrux/logs/after-battery-swap-charges/another_M0_T*.log"),
    key=lambda f: int(f.rsplit("_T", 1)[1].split(".")[0]))
SNAP_DT = 30.0
TAIL_AFTER_H = 6.5   # charge ended ~h5.7; tail = pure cooldown, flat SoC


class Corr:
    __slots__ = ("n", "sx", "sy", "sxx", "syy", "sxy")

    def __init__(self):
        self.n = self.sx = self.sy = self.sxx = self.syy = self.sxy = 0.0

    def add(self, x, y):
        self.n += 1; self.sx += x; self.sy += y
        self.sxx += x * x; self.syy += y * y; self.sxy += x * y

    def r(self):
        if self.n < 10:
            return None
        dx = self.n * self.sxx - self.sx * self.sx
        dy = self.n * self.syy - self.sy * self.sy
        if dx <= 0 or dy <= 0:
            return None
        return (self.n * self.sxy - self.sx * self.sy) / math.sqrt(dx * dy)


def scan():
    cur = {}                       # (id,byte) -> val
    full = defaultdict(Corr); tail = defaultdict(Corr)
    vrange = {}                    # (id,byte) -> [min,max]
    muxraw = defaultdict(lambda: defaultdict(list))  # id -> byte -> list of vals (subsample)
    t0 = None; last_snap = None
    for path in FILES:
        base = parse_header_time(path)
        if base is None:
            continue
        out = subprocess.run(["grep", "-hE", " 0x[345][0-9A-F][0-9A-F] ", path],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            dec = decode_line(line, base)
            if dec is None:
                continue
            t, arb, data = dec
            if not (0x300 <= arb <= 0x5FF):
                continue
            for bi, bv in enumerate(data):
                cur[(arb, bi)] = bv
            if arb == 0x430:
                try:
                    s = M430.decode(data, allow_truncated=True)
                    tmax = s.get("bcm_cell_tmax"); tmin = s.get("bcm_cell_tmin")
                except Exception:
                    continue
                if tmax is None or tmax < -30 or tmax > 80:
                    continue
                ep = t.timestamp()
                if t0 is None:
                    t0 = ep
                if last_snap is not None and ep - last_snap < SNAP_DT:
                    continue
                last_snap = ep
                is_tail = (ep - t0) > TAIL_AFTER_H * 3600
                for k, v in cur.items():
                    full[k].add(v, tmax)
                    if is_tail:
                        tail[k].add(v, tmax)
                    r = vrange.get(k)
                    if r is None:
                        vrange[k] = [v, v]
                    else:
                        if v < r[0]: r[0] = v
                        if v > r[1]: r[1] = v
                for bi, bv in enumerate(data if arb == arb else []):
                    pass
    return full, tail, vrange


def report(full, tail, vrange):
    cand = []
    for k, cf in full.items():
        rf = cf.r(); rt = tail[k].r() if k in tail else None
        if rf is None:
            continue
        cand.append((k, rf, rt, vrange[k]))
    print("=== bytes most correlated with bcm_cell_tmax, sorted by TAIL r ===")
    print("(temp channel: high r_full AND high r_tail; voltage: high r_full, low r_tail)")
    print(f"{'ID':>6} {'byte':>4} {'r_full':>7} {'r_tail':>7} {'rawmin':>7} {'rawmax':>7} "
          f"{'as0.5-40':>12}")
    cand.sort(key=lambda x: (x[2] if x[2] is not None else -9, x[1]), reverse=True)
    for (arb, bi), rf, rt, vr in cand[:40]:
        if (arb, bi) == (0x430, 4):
            tag = "  <- tmax itself"
        elif (arb, bi) == (0x430, 5):
            tag = "  <- tmin itself"
        else:
            tag = ""
        rts = f"{rt:7.3f}" if rt is not None else "   -   "
        tlo = vr[0] * 0.5 - 40; thi = vr[1] * 0.5 - 40
        print(f"{hex(arb):>6} {bi:>4} {rf:7.3f} {rts} {vr[0]:7d} {vr[1]:7d} "
              f"{tlo:5.1f}..{thi:4.1f}{tag}")


if __name__ == "__main__":
    full, tail, vrange = scan()
    report(full, tail, vrange)
