"""Replay captures through the old and new fault gates and diff the verdicts.

Mirrors `display/.../FaultClassifier.kt` closely enough to check one thing: does
bounding the 0x460 record list by the page-0 header (`fr_pages` /
`fr_grp1`) remove false faults without removing any real one?

  * OLD gate: every `fr_pN_rM` signal the display has ever seen, last-value
    held, is a live record. This is what shipped.
  * NEW gate: only the first `fr_grp1` slots of the first `fr_pages` pages
    count; if the header says the store is empty, the record list is empty
    however stale the page signals are.

Both are evaluated the way the app sees the world -- a flat map of last-known
signal values updated frame by frame -- so page multiplexing and the pages
going quiet after a clear are reproduced rather than assumed away.

Usage:
    py -3.11 projects/vtrux/notes/artifacts/fault_gate_replay.py \
        projects/vtrux/notes/artifacts/fault-slices/*.log
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import argparse
from pathlib import Path

sys.path.insert(0, "projects/vtrux/notes/artifacts")
from fault_push_counter import parse  # noqa: E402

TRIP = "F0 00 00"
SLOTS = [f"fr_p{p}_r{r}" for p in (1, 2, 3, 4) for r in (1, 2)]


def fmt(v: int) -> str:
    return f"{(v >> 16) & 0xFF:02X} {(v >> 8) & 0xFF:02X} {v & 0xFF:02X}"


def old_records(sig: dict) -> list[str]:
    out = []
    for name in SLOTS:
        v = sig.get(name)
        if v:
            s = fmt(v)
            if s not in out:
                out.append(s)
    return out


def new_records(sig: dict) -> list[str]:
    pages = sig.get("fr_pages")
    if pages is None or pages <= 0:
        return []
    # fr_grp1 bounds the group the trip's own records live in; records
    # pushed before the trip sit past it and must not be read as this event's.
    group = sig.get("fr_grp1")
    if group is None or group <= 0:
        return []
    out = []
    for name in SLOTS[:min(group, pages * 2, len(SLOTS))]:
        v = sig.get(name)
        if v:
            s = fmt(v)
            if s not in out:
                out.append(s)
    return out


def gate(sig: dict, records) -> bool:
    """True when the strip would claim a fault."""
    return sig.get("bcm_epo", 0) == 1 and TRIP in records(sig)


def header_start(path: Path) -> float:
    """Seconds-of-day from `***START DATE AND TIME dd:mm:yyyy HH:MM:SS:mmm***`.

    Data-line timestamps restart near zero in every rotation file, so they
    cannot order a session -- only this header can. Its sub-second field is
    milliseconds, unlike the 0.1 ms ticks on the data lines.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for _ in range(20):
            line = fh.readline()
            if not line:
                break
            if "START DATE AND TIME" in line:
                clock = line.split()[-1].rstrip("*")
                h, m, s, ms = (int(x) for x in clock.split(":"))
                return h * 3600 + m * 60 + s + ms / 1000.0
    return float("inf")


def stream(paths: list[Path]):
    """Frames from several rotation files as one continuous session.

    Timestamps are rebased onto each file's header start so the session reads
    as one monotonic timeline.
    """
    for p in sorted(paths, key=header_start):
        base = header_start(p)
        for t, cid, dlc, b in parse(p):
            yield (base + t, cid, dlc, b)


def replay(path: Path, extra: list[Path] | None = None) -> None:
    sig: dict = {}
    t0 = None
    prev = None
    spans = []          # (kind, t_start, t_end)
    src = stream([path] + list(extra)) if extra else parse(path)
    for t, cid, dlc, b in src:
        if t0 is None:
            t0 = t
        rel = t - t0
        if cid == 0x410 and dlc == 8:
            sig["bcm_epo"] = (b[0] >> 1) & 1
        elif cid == 0x460 and dlc == 8:
            page = b[0]
            if page == 0:
                sig["fr_pages"] = b[2]
                sig["fr_grp1"] = b[5]
                sig["fr_total"] = b[6]
            elif 1 <= page <= 4:
                sig[f"fr_p{page}_r1"] = (b[2] << 16) | (b[3] << 8) | b[4]
                sig[f"fr_p{page}_r2"] = (b[5] << 16) | (b[6] << 8) | b[7]
            else:
                continue
        else:
            continue

        cur = (gate(sig, old_records), gate(sig, new_records))
        if cur != prev:
            if spans:
                spans[-1] = (spans[-1][0], spans[-1][1], rel)
            spans.append((cur, rel, rel))
            prev = cur

    if spans:
        spans[-1] = (spans[-1][0], spans[-1][1], rel)

    print(f"\n=== {path.name}")
    for (old, new), a, b_ in spans:
        if not old and not new:
            continue
        mark = "  <-- DIFFERS" if old != new else ""
        print(f"   t+{a:8.3f} .. {b_:8.3f}  old={'FAULT' if old else '  -  '}"
              f"  new={'FAULT' if new else '  -  '}{mark}")
    if not any(o or n for (o, n), _, _ in spans):
        print("   no fault claimed by either gate")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--session", action="store_true",
                    help="treat every log given as one continuous session")
    args = ap.parse_args()
    if args.session:
        replay(args.logs[0], args.logs[1:])
        return
    for p in args.logs:
        replay(p)


if __name__ == "__main__":
    main()
