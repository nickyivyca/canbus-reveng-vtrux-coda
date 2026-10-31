"""vcu_page01_gaps.py -- how regular is the VCU's 0x18EFC000 page 01 on the
real truck (reviewer, 2026-10-13; user asked before ruling the HOLD cadence).

Question: the interposer's hold steps at most once per 0.3 s, timed on the
page-01 frames it rewrites. The VCU sends page 01 every ~0.3 s, so a strict
0.3 s gate skips alternate frames. Option A relaxes the gate to 0.28 s. The
user's condition: the logs must show the VCU's page-01 spacing consistently
at ~0.3 s, never near or under 0.28 s.

Raw logs, not InfluxDB (frame timing is the point). Same file selection and
powertrain-channel test as charger_wake_sequence.py: every file of every
session with a Bel frame on a powertrain channel; a channel is powertrain if
it carries >= 100 0x051 frames and none of the vehicle/obd anchors.
Channels carrying the interposer's diag frames 0x7F4-0x7F7 are excluded
(bench or board-in-loop captures: the "VCU" there may be a simulator, and the
board's rewrite changes the timing).

Page 01 = 0x18EFC000 with data[0] == 0x01. Each channel's series is sorted
before gaps are taken (file order is not time order). A gap over 1.0 s is
a logger gap or a bus stop, not a cadence, and is counted separately.

Phase 1: per file/channel gap lists -> vcu_page01_gaps.json
Phase 2: per format and corpus-wide distribution -> vcu_page01_gaps.txt

Usage (project root, madhouse): python3 <this> 1 2 [--workers N]
"""
import sys
sys.path.insert(0, ".")
import json
import multiprocessing as mp
from collections import Counter, defaultdict
from pathlib import Path

from canre.parsers import parse_file

ART = "projects/vtrux/notes/artifacts/"
sys.path.insert(0, ART)
from charger_wake_sequence import select_files  # noqa: E402

CACHE = ART + "vcu_page01_gaps.json"
OUT = ART + "vcu_page01_gaps.txt"
PT_ANCHOR = 0x051
OTHER_ANCHORS = {0x1E5, 0x500, 0x040, 0x041, 0x042, 0x043, 0x044}
DIAG_IDS = {0x7F4, 0x7F5, 0x7F6, 0x7F7}
ID_VCU = 0x18EFC000
BIG_GAP = 1.0


def scan_one(path):
    ch = {}
    try:
        for fr in parse_file(path, absolute=True):
            c = ch.get(fr.bus)
            if c is None:
                c = ch[fr.bus] = {"n051": 0, "other": False, "diag": False,
                                  "t": []}
            i, x = fr.arbitration_id, bool(fr.is_extended)
            if not x:
                if i in OTHER_ANCHORS:
                    c["other"] = True
                elif i == PT_ANCHOR:
                    c["n051"] += 1
                elif i in DIAG_IDS:
                    c["diag"] = True
                continue
            if i == ID_VCU and fr.data and fr.data[0] == 0x01:
                c["t"].append(fr.timestamp)
    except Exception as e:
        return str(path), None, "parse error: %s" % e
    out = []
    for bus, c in ch.items():
        if c["n051"] < 100 or c["other"] or len(c["t"]) < 2:
            continue
        ts = sorted(c["t"])
        gaps = [round(b - a, 5) for a, b in zip(ts, ts[1:])]
        out.append({"bus": str(bus), "diag": c["diag"], "gaps": gaps})
    return str(path), out, None


def phase1(workers):
    files = select_files()
    print("files:", len(files), flush=True)
    res = {}
    ctx = mp.get_context("fork")
    with ctx.Pool(workers) as pool:
        for k, (p, out, err) in enumerate(
                pool.imap_unordered(scan_one, files, chunksize=1), 1):
            res[p] = {"chans": out, "err": err}
            if k % 50 == 0:
                print("%d / %d" % (k, len(files)), flush=True)
    with open(CACHE, "w") as f:
        json.dump(res, f)


def pct(sv, q):
    return sv[min(len(sv) - 1, int(q * len(sv)))]


def phase2():
    with open(CACHE) as f:
        res = json.load(f)
    lines = []
    w = lines.append
    by_fmt = defaultdict(list)
    per_file = []
    errs = [p for p, r in res.items() if r["err"]]
    excluded = 0
    big = 0
    for p, r in sorted(res.items()):
        for c in r["chans"] or []:
            if c["diag"]:
                excluded += 1
                continue
            g = [x for x in c["gaps"] if x <= BIG_GAP]
            big += len(c["gaps"]) - len(g)
            if not g:
                continue
            fmt = Path(p).suffix.lower() or "?"
            by_fmt[fmt].extend(g)
            sv = sorted(g)
            per_file.append((sv[0], p, c["bus"], len(g), pct(sv, 0.5),
                             sv[-1]))
    w("VCU 0x18EFC000 page 01 spacing on the powertrain bus, real truck")
    w("=" * 70)
    w("files scanned: %d, parse errors: %d" % (len(res), len(errs)))
    w("channels excluded (interposer diag 0x7F4-0x7F7 present): %d" % excluded)
    w("gaps > %.1f s (logger gaps / bus stops, not cadence): %d" % (BIG_GAP, big))
    w("")
    allg = []
    for fmt, g in sorted(by_fmt.items()):
        allg.extend(g)
        sv = sorted(g)
        w("format %-6s gaps %8d  min %.4f  p0.01%% %.4f  p0.1%% %.4f  p1%% %.4f"
          "  median %.4f  p99%% %.4f  max %.4f" % (
              fmt, len(sv), sv[0], pct(sv, 0.0001), pct(sv, 0.001),
              pct(sv, 0.01), pct(sv, 0.5), pct(sv, 0.99), sv[-1]))
        for th in (0.28, 0.29, 0.295, 0.298):
            n = sum(1 for x in sv if x < th)
            w("    < %.3f s: %d (%.4f %%)" % (th, n, 100.0 * n / len(sv)))
    w("")
    sv = sorted(allg)
    w("ALL: %d gaps, min %.4f, median %.4f" % (len(sv), sv[0], pct(sv, 0.5)))
    w("")
    w("histogram, 5 ms bins, 0.20-0.40 s (all formats):")
    h = Counter()
    for x in sv:
        if 0.2 <= x < 0.4:
            h[int(x * 200)] += 1
    for b in sorted(h):
        w("  %.3f-%.3f  %d" % (b / 200.0, (b + 1) / 200.0, h[b]))
    w("  < 0.200: %d   0.400-%.1f: %d" % (
        sum(1 for x in sv if x < 0.2), BIG_GAP,
        sum(1 for x in sv if 0.4 <= x <= BIG_GAP)))
    w("")
    w("20 channels with the smallest gap:")
    for mn, p, bus, n, med, mx in sorted(per_file)[:20]:
        w("  min %.4f  median %.4f  max %.4f  n %6d  %s [%s]" % (
            mn, med, mx, n, p, bus))
    if errs:
        w("")
        w("parse errors:")
        for p in errs:
            w("  %s: %s" % (p, res[p]["err"]))
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:40]))


if __name__ == "__main__":
    args = sys.argv[1:]
    workers = 4
    if "--workers" in args:
        workers = int(args[args.index("--workers") + 1])
    if "1" in args:
        phase1(workers)
    if "2" in args:
        phase2()
