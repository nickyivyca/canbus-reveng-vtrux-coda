"""Trace the 0x460 page-0 header counters over a capture.

Written to work out what the page-0 header actually does, because the shipped
classifier needed some way to tell a record the pack just pushed from a stale
one. What it established, and what the DBC now says:

  B2 `fr_pages`  populated record pages, always ceil(fr_total / 2)
  B3 `fr_grp3`   \\
  B4 `fr_grp2`    > three groups, summing exactly to fr_total
  B5 `fr_grp1`   /   -- and the slots are laid out in this order
  B6 `fr_total`  records stored, 0-8
  B7             free-runs 01<->02 at ~2 Hz; a liveness toggle, not state

It also disproved the assumption it started from. Records do *not* survive a
BMS reboot in any way the display can be fooled by: every counter drops to zero
within ~10 ms of EPO deasserting, so the store is already scoped to the current
EPO episode. What does bite is that pages above `fr_pages` stop transmitting,
leaving stale values in a last-known-value signal map.

Raw line scan filtered to DLC=8 (the OBD-bus 0x460 is TRAC MCU, DLC=5). Pages
1..4 each carry two 24-bit records (B2-B4, B5-B7).

Usage:
    py -3.11 projects/vtrux/notes/artifacts/fault_push_counter.py \
        projects/vtrux/notes/artifacts/fault-slices/05-interlock-fault-drive.log
    py -3.11 projects/vtrux/notes/artifacts/fault_push_counter.py --records LOG...
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import argparse
import re
from pathlib import Path

LINE_RE = re.compile(
    r"^(\d{1,2}):(\d{2}):(\d{2}):(\d{4})\s+\S+\s+\d+\s+0x0*(\w+)\s+s\s+(\d)\s+"
    + r"\s+".join([r"([0-9A-Fa-f]{2})"] * 8),
    re.IGNORECASE,
)


def parse(path: Path):
    """Yield (t_seconds, id_int, dlc, bytes) for every 8-byte data line."""
    prev = None
    wrap = 0.0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = LINE_RE.match(line)
            if not m:
                continue
            h, mi, s, ticks = (int(m.group(i)) for i in range(1, 5))
            t = h * 3600.0 + mi * 60.0 + s + ticks * 0.0001
            if prev is not None and t < prev - 3600.0:
                wrap += 86400.0  # midnight rollover
            prev = t
            yield (t + wrap, int(m.group(5), 16), int(m.group(6)),
                   [int(m.group(i), 16) for i in range(7, 15)])


def fmt_rec(b):
    return " ".join(f"{x:02X}" for x in b)


def trace(path: Path, show_records: bool) -> None:
    print(f"\n=== {path.name}")
    t0 = None
    last_hdr = None
    last_seen = {}          # page -> (r1, r2) as strings
    epo_prev = None
    hvil_prev = None
    events = []

    for t, cid, dlc, b in parse(path):
        if t0 is None:
            t0 = t
        rel = t - t0

        # 0x410 BMS status, for the fault context the counters must line up with.
        if cid == 0x410 and dlc == 8:
            epo = (b[0] >> 1) & 1
            hvil = (b[0] >> 3) & 1
            if epo != epo_prev:
                events.append((rel, "410", f"epo {epo_prev} -> {epo}"))
                epo_prev = epo
            if hvil != hvil_prev:
                events.append((rel, "410", f"hvil {hvil_prev} -> {hvil}"))
                hvil_prev = hvil
            continue

        if cid != 0x460 or dlc != 8:
            continue

        page = b[0]
        if page == 0:
            # Trace the whole header, not just the three bytes the DBC names --
            # the counter semantics are what this script is trying to establish.
            # B7 free-runs 01<->02 at ~2 Hz on every capture -- a liveness
            # toggle, not state. Excluded so it does not bury the real changes.
            hdr = tuple(b[1:7])
            if hdr != last_hdr:
                cur = " ".join(f"{x:02X}" for x in hdr)
                if last_hdr is None:
                    events.append((rel, "hdr", f"first  B1-B7 = {cur}"))
                else:
                    diff = " ".join(
                        f"{x:02X}" if x == y else f"[{y:02X}>{x:02X}]"
                        for x, y in zip(hdr, last_hdr))
                    events.append((rel, "hdr", f"       B1-B7 = {diff}"))
                last_hdr = hdr
        elif show_records and 1 <= page <= 4:
            cur = (fmt_rec(b[2:5]), fmt_rec(b[5:8]))
            if last_seen.get(page) != cur:
                events.append((rel, f"p{page}",
                               f"{last_seen.get(page, ('--','--'))} -> {cur}"))
                last_seen[page] = cur

    if not events:
        print("   (no 0x460 DLC=8 header traffic)")
        return
    for rel, kind, msg in events:
        print(f"   t+{rel:9.3f}  {kind:4s} {msg}")


def first_header(path: Path):
    """(t_rel, B1..B6) of the earliest page-0 header, or None."""
    t0 = None
    for t, cid, dlc, b in parse(path):
        if t0 is None:
            t0 = t
        if cid == 0x460 and dlc == 8 and b[0] == 0:
            return (t - t0, tuple(b[1:7]))
    return None


def survey(paths: list[Path]) -> None:
    """Does a session ever START with the leading record group non-empty?

    If `fr_grp1` is always 0 at the first header of a session, then `fr_grp1 > 0`
    is by itself a freshness gate -- no connect-time snapshot needed, and it
    survives an app restart. Any session starting above 0 falsifies that and
    forces a snapshot approach instead. Measured: 0 of 1079 session-start logs.
    """
    hits, misses, empty = [], 0, 0
    for path in paths:
        try:
            got = first_header(path)
        except OSError:
            continue
        if got is None:
            empty += 1
            continue
        rel, hdr = got
        if hdr[4] != 0:  # fr_grp1
            hits.append((path.name, rel, hdr))
        else:
            misses += 1

    print(f"sessions with a page-0 header : {misses + len(hits)}")
    print(f"  starting with fr_grp1 == 0  : {misses}")
    print(f"  starting with fr_grp1 >  0  : {len(hits)}")
    print(f"no 0x460 DLC=8 header at all  : {empty}")
    for name, rel, hdr in hits[:40]:
        cur = " ".join(f"{x:02X}" for x in hdr)
        print(f"   {name}  t+{rel:7.3f}  B1-B6 = {cur}")
    if len(hits) > 40:
        print(f"   ... and {len(hits) - 40} more")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--records", action="store_true",
                    help="also trace record pages 1-4 changing")
    ap.add_argument("--survey", action="store_true",
                    help="report only the first header of each log")
    args = ap.parse_args()
    if args.survey:
        survey(args.logs)
        return
    for path in args.logs:
        trace(path, args.records)


if __name__ == "__main__":
    main()
