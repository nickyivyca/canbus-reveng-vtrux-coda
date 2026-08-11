"""Discriminate per-module TEMPERATURE vs per-module VOLTAGE among the candidate
bytes from module_temp_hunt.py.

Confound: in a charge + idle tail, both temp and voltage move together (voltage
relaxes down in the tail, like cooling). Clean separator = a DISCHARGE (drive):
  voltage channel  -> crashes with SoC   (high |r_soc|)
  temperature      -> ~flat while pack temp barely moves (low |r_soc|)

Window: 20260714 final drive (SoC ~100 -> ~36, big voltage swing; tmax ~flat 40-41).
"""
import sys
sys.path.insert(0, ".")

import glob
import math
import subprocess
from datetime import datetime
from collections import defaultdict

import cantools

from battery_fan_signature import parse_header_time, decode_line

pt = cantools.database.load_file("projects/vtrux/epri-pt-bus.dbc")
M410 = pt.get_message_by_frame_id(0x410)
M430 = pt.get_message_by_frame_id(0x430)

CAND_IDS = {0x370, 0x371, 0x372, 0x373, 0x374, 0x375, 0x506, 0x507}
W0 = datetime(2026, 7, 14, 21, 59)   # final drive start
W1 = datetime(2026, 7, 14, 22, 47)


def pearson(xs, ys):
    n = len(xs)
    if n < 10:
        return None
    mx = sum(xs) / n; my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def run():
    files = sorted(glob.glob("<home>/Seafile/CANLogs/VtruxLogs/vtrux_20260714_161319_T*.log"),
                   key=lambda f: int(f.rsplit("_T", 1)[1].split(".")[0]))
    chunks = []
    hdrs = [(f, parse_header_time(f)) for f in files]
    hdrs = [(f, h) for f, h in hdrs if h is not None]
    for i, (f, h) in enumerate(hdrs):
        nxt = hdrs[i + 1][1] if i + 1 < len(hdrs) else W1
        if h <= W1 and nxt >= W0:
            chunks.append(f)

    cur = {}
    series = defaultdict(list)   # key -> list aligned to samples
    soc = []; tmax = []
    last_snap = None
    for path in chunks:
        base = parse_header_time(path)
        if base is None:
            continue
        out = subprocess.run(["grep", "-hE", " 0x(37[0-5]|506|507|410|430) ", path],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            dec = decode_line(line, base)
            if dec is None:
                continue
            t, arb, data = dec
            if t < W0 or t > W1:
                continue
            if arb in CAND_IDS:
                for bi, bv in enumerate(data):
                    cur[(arb, bi)] = bv
            elif arb == 0x410:
                try:
                    cur["soc"] = M410.decode(data, allow_truncated=True).get("bcm_soc")
                except Exception:
                    pass
            elif arb == 0x430:
                try:
                    s = M430.decode(data, allow_truncated=True)
                    tm = s.get("bcm_cell_tmax")
                except Exception:
                    continue
                if tm is None or tm < -30 or tm > 80 or cur.get("soc") is None:
                    continue
                ep = t.timestamp()
                if last_snap is not None and ep - last_snap < 5:
                    continue
                last_snap = ep
                soc.append(cur["soc"]); tmax.append(tm)
                for k, v in cur.items():
                    if k == "soc":
                        continue
                    series[k].append((len(soc) - 1, v))
    print(f"samples over final drive: {len(soc)}  SoC {soc[0]:.0f}->{soc[-1]:.0f}, "
          f"tmax {min(tmax):.1f}-{max(tmax):.1f}")
    print("\ncandidate byte vs SoC and vs tmax over the DISCHARGE:")
    print("(VOLTAGE -> high +r_soc, crashes with SoC | TEMPERATURE -> low |r_soc|, tracks tmax)")
    print(f"{'ID':>6} {'byte':>4} {'r_soc':>7} {'r_tmax':>7} {'rawmin':>7} {'rawmax':>7} {'verdict':>10}")
    rows = []
    for k in sorted(series):
        idx = [i for i, _ in series[k]]
        vals = [v for _, v in series[k]]
        if len(set(vals)) <= 1:
            continue
        rs = pearson(vals, [soc[i] for i in idx])
        rt = pearson(vals, [tmax[i] for i in idx])
        rows.append((k, rs, rt, min(vals), max(vals)))
    for (arb, bi), rs, rt, vmn, vmx in rows:
        if rs is None:
            continue
        verdict = "VOLTAGE" if abs(rs) > 0.85 else ("temp?" if abs(rs) < 0.5 else "mixed")
        rts = f"{rt:7.3f}" if rt is not None else "   -   "
        print(f"{hex(arb):>6} {bi:>4} {rs:7.3f} {rts} {vmn:7d} {vmx:7d} {verdict:>10}")


if __name__ == "__main__":
    run()
