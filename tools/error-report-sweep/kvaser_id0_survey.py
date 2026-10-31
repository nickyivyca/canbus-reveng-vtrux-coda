"""Short standard-id 0x000 frames (DLC < 8) in BUSMASTER captures, by adapter in the header.

Raised 2026-10-30 at step 4 of the internal `can-replay-readers` plan: two desktop-BUSMASTER
Kvaser captures carry `0x0 s 4 00 xx 00 00` on a B CAN channel, which makes the strict
anchor resolver call that channel ambiguous (C CAN anchor 0x000). The owner asked whether
this is another error status written as a real message. This survey only counts and
places them; it interprets nothing.

Per capture: adapter names from the header, short 0x000 frames per channel, their payload
patterns, DLC-8 0x000 frames per channel (the real C CAN cell frame), and where in the
capture the short ones fall (fraction of the file's time span, and seconds before the end).

Run from the reverse-it root on the Linux box:
  python3.13 tools/error-report-sweep/kvaser_id0_survey.py
"""
import re
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

ROOTS = ["projects/coda/logs", "projects/vtrux/logs", "../../CANLogs/CodaLogs",
         "../../CANLogs/VtruxLogs"]
OUT = Path("tools/error-report-sweep/artifacts/kvaser_id0_survey.txt")
CHAN = re.compile(r"^\*\*\*CHANNEL\s+(\d+)\s+-\s+(.*?)\s+-")
LINE = re.compile(r"^(\d+):(\d+):(\d+):(\d+) (Rx|Tx) (\d+) 0x([0-9A-Fa-f]+) (\w+) (\d+) ?(.*)$")


def ts(m):
    return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + int(m[4]) / 10000


def scan(path):
    adapters, short, eight, kinds, times = set(), Counter(), Counter(), Counter(), []
    t0 = t1 = None
    try:
        with open(path, errors="replace") as f:
            for line in f:
                if line.startswith("***"):
                    m = CHAN.match(line)
                    if m:
                        adapters.add(m[2])
                    continue
                m = LINE.match(line)
                if not m:
                    continue
                t = ts(m)
                t0 = t if t0 is None else min(t0, t)
                t1 = t if t1 is None else max(t1, t)
                if int(m[7], 16) != 0 or m[8] != "s":
                    continue
                if int(m[9]) == 8:
                    eight[m[6]] += 1
                else:
                    short[m[6]] += 1
                    kinds[f"dlc{m[9]} {m[10].strip()}"] += 1
                    times.append(t)
    except OSError as e:
        return str(path), sorted(adapters), None, str(e)
    if not short:
        return str(path), sorted(adapters), None, None
    span = (t1 - t0) or 1
    pos = [(round((t - t0) / span, 3), round(t1 - t, 1)) for t in times[:6]]
    return str(path), sorted(adapters), (dict(short), dict(eight), dict(kinds), pos, round(span)), None


def main():
    paths = [p for r in ROOTS for p in sorted(Path(r).glob("*.log"))]
    by_adapter_files, by_adapter_hits = Counter(), Counter()
    hits, errs = [], []
    with Pool(12) as pool:
        for path, adapters, res, err in pool.imap_unordered(scan, paths, chunksize=8):
            key = "+".join(adapters) or "(no channel header)"
            by_adapter_files[key] += 1
            if err:
                errs.append((path, err))
            if res:
                by_adapter_hits[key] += 1
                hits.append((path, key, res))
    lines = [f"files {len(paths)} (non-recursive: {', '.join(ROOTS)})",
             "files with short 0x000 frames / files, by header adapters:"]
    for k, n in by_adapter_files.most_common():
        lines.append(f"  {k:40s} {by_adapter_hits[k]:5d} / {n}")
    kinds_all = Counter()
    for _, _, (s, e, kinds, _, _) in hits:
        kinds_all.update(kinds)
    lines.append("payloads of short 0x000 frames, all files:")
    for k, n in kinds_all.most_common(30):
        lines.append(f"  {n:7d}  {k}")
    lines.append("per file: short per channel | DLC-8 0x000 per channel | span s | "
                 "first positions (fraction of span, s before end)")
    for path, key, (s, e, kinds, pos, span) in sorted(hits):
        lines.append(f"  {Path(path).name} [{key}] short={s} dlc8={e} span={span} pos={pos}")
    for path, err in errs:
        lines.append(f"  ERROR {path}: {err}")
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:60]))


if __name__ == "__main__":
    sys.exit(main())
