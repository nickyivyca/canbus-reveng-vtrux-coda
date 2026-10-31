"""What values does `bcm_gfd` (0x410 B1[3:0]:B2) actually take?

The shipped classifier carries an unreviewed hypothesis: that a raw all-ones
reading means "no measurement" rather than a healthy result. It was written
after seeing 1023.5 in two captures where the DBC only documents normal=1000.0
(raw 4000) and fault=0.0 (raw 0). This settles what the field really does.

Reports, per log and pooled:
  * the full distribution of raw values, and how long each is held;
  * which values coincide with EPO asserted vs clear;
  * whether the top nibble (B1[3:0], the signal's four MSBs) is ever anything
    but 0xF outside the fault value -- if it is not, the 12-bit framing is
    carrying only 8 bits of information and the DBC's [0|1023.75] range is
    misleading.

Usage:
    py -3.11 projects/vtrux/notes/artifacts/gfd_value_census.py LOG...
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import argparse
from collections import Counter
from pathlib import Path

sys.path.insert(0, "projects/vtrux/notes/artifacts")
from fault_push_counter import parse  # noqa: E402


def by_contactor(paths: list[Path]) -> None:
    """Cross-tabulate gfd value against the 0x440 contactor state.

    The question this settles: is the third value a reading at all, or is it
    what the monitor reports when the HV bus is not up? If it never appears
    while the contactors are closed (states 11 / 12), it is not a measurement.
    """
    table: dict[tuple[int, int], float] = {}
    mainc = None
    prev_t = prev_raw = None
    for path in paths:
        mainc = None
        prev_t = prev_raw = None
        for t, cid, dlc, b in parse(path):
            if cid == 0x440 and dlc == 8:
                mainc = (b[0] >> 2) & 0xF
                continue
            if cid != 0x410 or dlc != 8:
                continue
            raw = ((b[1] & 0x0F) << 8) | b[2]
            if prev_t is not None and prev_raw is not None and mainc is not None:
                dt = t - prev_t
                if 0 <= dt < 5.0:
                    key = (mainc, prev_raw)
                    table[key] = table.get(key, 0.0) + dt
            prev_t, prev_raw = t, raw

    raws = sorted({r for _, r in table})
    print("\nseconds held, contactor state x gfd value:")
    header = "  state  " + "".join(f"{r*0.25:>12.2f}" for r in raws)
    print(header)
    for st in sorted({s for s, _ in table}):
        row = "".join(f"{table.get((st, r), 0.0):12.1f}" for r in raws)
        print(f"  {st:5d}  {row}")
    print("\n  (11 = MAIN_PN_CLOSED_DRIVE, 12 = MAIN_P_CLOSED_CHARGE,")
    print("   13 = SHUTDOWN_REQUEST, 14 = ALL_OPEN_SHUTDOWN, 0 = ALL_OPEN)")


def census(paths: list[Path]) -> None:
    dwell: Counter = Counter()       # raw -> seconds held
    with_epo: Counter = Counter()    # raw -> seconds held while epo == 1
    nibbles: Counter = Counter()
    per_log: dict[str, Counter] = {}

    for path in paths:
        prev_t = None
        prev_raw = None
        prev_epo = None
        local: Counter = Counter()
        for t, cid, dlc, b in parse(path):
            if cid != 0x410 or dlc != 8:
                continue
            raw = ((b[1] & 0x0F) << 8) | b[2]
            epo = (b[0] >> 1) & 1
            if prev_t is not None and prev_raw is not None:
                dt = t - prev_t
                if 0 <= dt < 5.0:
                    dwell[prev_raw] += dt
                    local[prev_raw] += dt
                    if prev_epo == 1:
                        with_epo[prev_raw] += dt
            nibbles[(b[1] & 0x0F)] += 1
            prev_t, prev_raw, prev_epo = t, raw, epo
        if local:
            per_log[path.name] = local

    total = sum(dwell.values()) or 1.0
    print(f"\npooled over {len(per_log)} logs, {total/60:.1f} min of 0x410")
    print(f"{'raw':>6} {'hex':>5} {'value':>9} {'seconds':>10} {'share':>7} "
          f"{'of which epo=1':>15}")
    for raw, secs in dwell.most_common(20):
        print(f"{raw:6d} {raw:#05x} {raw*0.25:9.2f} {secs:10.1f} "
              f"{100*secs/total:6.1f}% {with_epo.get(raw, 0.0):14.1f}s")

    print("\nB1 low nibble (the signal's four MSBs) frequency:")
    tot_n = sum(nibbles.values()) or 1
    for nib, n in sorted(nibbles.items()):
        print(f"   0x{nib:X}  {n:9d}  {100*n/tot_n:6.2f}%")

    print("\nper-log dominant value:")
    for name, local in sorted(per_log.items())[:40]:
        raw, secs = local.most_common(1)[0]
        others = sorted(local, key=lambda r: -local[r])[1:4]
        print(f"   {name:44s} {raw*0.25:8.2f} ({secs:6.1f}s)  also "
              + ", ".join(f"{r*0.25:.2f}" for r in others))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--by-contactor", action="store_true",
                    help="cross-tabulate against the 0x440 contactor state")
    args = ap.parse_args()
    if args.by_contactor:
        by_contactor(args.logs)
        return
    census(args.logs)


if __name__ == "__main__":
    main()
