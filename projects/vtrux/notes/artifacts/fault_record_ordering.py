"""Are the 0x460 record slots grouped, with the trip's own records first?

Motivation: `05-interlock-fault-drive` holds four records at the trip --
`AC 10 00`, `F0 00 00` (pushed by the trip) and `FC 16 F2`, `FB B6 E4` (pushed
18 s and 33 s *earlier*, while EPO was clear). A classifier that reads the whole
list would name the trip after `FC 16 F2` ("generator inverter not
responding"), which had nothing to do with it.

The page-0 header carries three counters -- `fr_grp3`, `fr_grp2` and `fr_grp1` --
that sum exactly to `fr_total`, the total record count. The hypothesis
under test is that the slot order mirrors that split -- `fr_grp1`'s group
first, then `fr_grp2`'s, then `fr_grp3`'s -- and that the trip's own records
always land in the `fr_grp1` group.

Two invariants checked per sample, over every log with 0x460 record pages:

  I1  fr_grp3 + fr_grp2 + fr_grp1 == fr_total, and fr_pages == ceil(fr_total / 2)
  I2  whenever `F0 00 00` is stored at all, its slot index is < fr_grp1

Usage:
    py -3.11 projects/vtrux/notes/artifacts/fault_record_ordering.py LOG...
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


def check(paths: list[Path]) -> None:
    logs = 0
    i1_samples = i1_bad = 0
    i2_samples = i2_bad = 0
    examples: list[str] = []

    for path in paths:
        pages_now = None
        counts = None          # (fr_pages, fr_grp3, fr_grp2, fr_grp1, fr_total)
        slots: dict[int, str] = {}
        saw = False
        for t, cid, dlc, b in parse(path):
            if cid != 0x460 or dlc != 8:
                continue
            if b[0] == 0:
                counts = (b[2], b[3], b[4], b[5], b[6])
                pages_now = b[2]
                if counts[4] == 0:
                    slots = {}
                # I1
                i1_samples += 1
                total = counts[1] + counts[2] + counts[3]
                want_pages = (counts[4] + 1) // 2
                if total != counts[4] or pages_now != want_pages:
                    i1_bad += 1
                    if len(examples) < 8:
                        examples.append(
                            f"I1 {path.name} hdr={counts} sum={total} "
                            f"want_pages={want_pages}")
            elif 1 <= b[0] <= 4:
                saw = True
                slots[(b[0] - 1) * 2] = rec(b[2:5])
                slots[(b[0] - 1) * 2 + 1] = rec(b[5:8])
                if counts is None:
                    continue
                grp1, total = counts[3], counts[4]
                live = [slots.get(i, "00 00 00") for i in range(min(total, 8))]
                if TRIP not in live:
                    continue
                i2_samples += 1
                if live.index(TRIP) >= grp1:
                    i2_bad += 1
                    if len(examples) < 8:
                        examples.append(
                            f"I2 {path.name} fr_grp1={grp1} live={live}")
        if saw:
            logs += 1

    print(f"logs with 0x460 record pages : {logs}")
    print(f"I1 (fr_grp3+fr_grp2+fr_grp1 == fr_total, fr_pages == ceil(fr_total/2))")
    print(f"    samples={i1_samples}  violations={i1_bad}")
    print(f"I2 ('{TRIP}' sits inside the first fr_grp1 slots)")
    print(f"    samples={i2_samples}  violations={i2_bad}")
    for e in examples:
        print("   ", e)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="+", type=Path)
    args = ap.parse_args()
    check(args.logs)


if __name__ == "__main__":
    main()
