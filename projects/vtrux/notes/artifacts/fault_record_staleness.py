"""Does `F0 00 00` ever stand in the 0x460 record pages while EPO is clear?

The shipped `classify()` gates a fault on `epo && "F0 00 00" in records`, and
`vtrux-fault-display.md` 5.1 assumes that record survives a BMS reboot, so a
later unplug would read as a fault. This checks that assumption against the
corpus instead of trusting it, and measures two things the fix depends on:

  A. how long a fault record keeps appearing in pages 1-4 after the page-0
     header has zeroed (the pages lag the header, so a decoded signal map goes
     on reporting a cleared record);
  B. whether pages 1-4 are transmitted at all once the header count is 0 -- if
     they simply stop, a display holding last-known values never sees the
     record go away.

Phase 1 (`--phase 1`): per-log timeline of header-zero vs page content.
Phase 2 (`--phase 2`): corpus scan for `F0 00 00` present while epo == 0.

Usage:
    py -3.11 projects/vtrux/notes/artifacts/fault_record_staleness.py --phase 1 LOG...
    py -3.11 projects/vtrux/notes/artifacts/fault_record_staleness.py --phase 2 LOG...
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import argparse
from pathlib import Path

sys.path.insert(0, "projects/vtrux/notes/artifacts")
from fault_push_counter import parse  # noqa: E402

TRIP = "F0 00 00"


def rec(b) -> str:
    return " ".join(f"{x:02X}" for x in b)


def phase1(path: Path) -> None:
    """Timeline around every header clear: when do the pages catch up?"""
    print(f"\n=== {path.name}")
    t0 = None
    pushlo = None
    clear_t = None
    page_last = {}          # page -> (t, r1, r2)
    page_tx = {}            # page -> count of frames since the clear
    for t, cid, dlc, b in parse(path):
        if t0 is None:
            t0 = t
        rel = t - t0
        if cid != 0x460 or dlc != 8:
            continue
        if b[0] == 0:
            lo = b[6]
            if pushlo is not None and lo == 0 and pushlo != 0:
                clear_t = rel
                page_tx = {}
                standing = {p: v for p, v in page_last.items()
                            if TRIP in (v[1], v[2])}
                print(f"   t+{rel:9.3f}  header cleared (push_lo {pushlo} -> 0); "
                      f"pages still showing {TRIP}: "
                      + (", ".join(f"p{p}" for p in standing) or "none"))
            pushlo = lo
        elif 1 <= b[0] <= 4:
            p = b[0]
            r1, r2 = rec(b[2:5]), rec(b[5:8])
            if clear_t is not None:
                page_tx[p] = page_tx.get(p, 0) + 1
            prev = page_last.get(p)
            if prev is None or (prev[1], prev[2]) != (r1, r2):
                if clear_t is not None and prev and TRIP in (prev[1], prev[2]):
                    print(f"   t+{rel:9.3f}  p{p} finally changed "
                          f"({rel - clear_t:.3f} s after the clear, "
                          f"{page_tx.get(p, 0)} frames): "
                          f"({prev[1]}, {prev[2]}) -> ({r1}, {r2})")
            page_last[p] = (rel, r1, r2)


def phase2(paths: list[Path]) -> None:
    """Corpus scan: is TRIP ever in the live page set while epo == 0?"""
    total = 0
    offenders = []
    for path in paths:
        try:
            it = parse(path)
        except OSError:
            continue
        t0 = None
        epo = None
        page_last = {}
        worst = 0.0
        since = None
        saw_pages = False
        for t, cid, dlc, b in it:
            if t0 is None:
                t0 = t
            rel = t - t0
            if cid == 0x410 and dlc == 8:
                epo = (b[0] >> 1) & 1
                if epo == 0 and saw_pages:
                    standing = any(TRIP in (v[0], v[1])
                                   for v in page_last.values())
                    if standing:
                        if since is None:
                            since = rel
                        worst = max(worst, rel - since)
                    else:
                        since = None
                else:
                    since = None
            elif cid == 0x460 and dlc == 8 and 1 <= b[0] <= 4:
                saw_pages = True
                page_last[b[0]] = (rec(b[2:5]), rec(b[5:8]))
        if saw_pages:
            total += 1
            if worst > 0.0:
                offenders.append((path.name, worst))

    print(f"\nlogs with 0x460 record pages : {total}")
    print(f"  showing {TRIP} while epo==0 : {len(offenders)}")
    for name, w in sorted(offenders, key=lambda x: -x[1])[:30]:
        print(f"   {name:44s} up to {w:8.3f} s")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--phase", type=int, default=1)
    args = ap.parse_args()
    if args.phase == 1:
        for p in args.logs:
            phase1(p)
    else:
        phase2(args.logs)


if __name__ == "__main__":
    main()
