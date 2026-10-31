"""Sweep captures for interlock chatter -- rapid repeated hvil transitions.

Motivation: the fault classifier prototyped in
`android-app/CanLoggerApps/display/.../FaultClassifier.kt` gates on
`bcm_epo == 1`. `notes/fault-signature-comparison.md` records a mid-drive
interlock flutter (2026-06-10) that asserted **no EPO at all**, which such a
gate would show nothing for. This sweep finds every chatter episode in a set
of captures so the gate can be tested against real ones.

Raw line scan rather than `parse_file`: these are 50 MB Android-logger chunks
and only 0x410 byte 0 is needed, so building a CANFrame per line costs far
more than it returns.

Reports, per file:
  * every hvil transition, and
  * "CHATTER" whenever >= 3 transitions land within `--window` seconds.

Usage:
    py -3.11 projects/vtrux/notes/artifacts/hvil_chatter_sweep.py \
        ../../CANLogs/VtruxLogs/vtrux_20260610_*.log
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import argparse
import re
from pathlib import Path

# BUSMASTER data line, narrowed to 0x410 so the regex rejects everything else
# before any field splitting happens.
LINE_RE = re.compile(
    r"^(\d{1,2}):(\d{2}):(\d{2}):(\d{4})\s+\S+\s+(\d+)\s+0x0*410\s+s\s+\d+\s+"
    r"([0-9A-Fa-f]{2})\s+([0-9A-Fa-f]{2})",
    re.IGNORECASE,
)


def sweep(path: Path, window: float, quiet: bool) -> int:
    transitions: list[tuple[float, int, int, int]] = []
    prev_hvil: int | None = None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "0x410" not in line:
                continue
            m = LINE_RE.match(line)
            if not m:
                continue
            h, mi, s, ticks = (int(m.group(i)) for i in range(1, 5))
            t = h * 3600.0 + mi * 60.0 + s + ticks * 0.0001
            b0 = int(m.group(6), 16)
            b1 = int(m.group(7), 16)
            hvil = (b0 >> 3) & 1
            if prev_hvil is not None and hvil != prev_hvil:
                transitions.append((t, prev_hvil, hvil, (b0 >> 1) & 1))
            prev_hvil = hvil

    if not transitions:
        if not quiet:
            print(f"{path.name}: hvil steady, no transitions")
        return 0

    print(f"\n{path.name}: {len(transitions)} hvil transition(s)")
    # Cluster: any run of >=3 transitions whose span is under `window`.
    chatter_marks = set()
    for i in range(len(transitions)):
        j = i
        while (j + 1 < len(transitions)
               and transitions[j + 1][0] - transitions[i][0] <= window):
            j += 1
        if j - i + 1 >= 3:
            chatter_marks.update(range(i, j + 1))

    episodes = 0
    for idx, (t, old, new, epo) in enumerate(transitions):
        tag = "CHATTER" if idx in chatter_marks else "       "
        print(f"  {tag}  t={t:9.3f}  hvil {old} -> {new}   epo={epo}")
    if chatter_marks:
        span = (transitions[max(chatter_marks)][0]
                - transitions[min(chatter_marks)][0])
        epo_any = any(transitions[i][3] for i in chatter_marks)
        episodes = 1
        print(f"  => {len(chatter_marks)} transitions in {span:.3f}s, "
              f"EPO asserted during chatter: {'yes' if epo_any else 'NO'}")
    return episodes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--window", type=float, default=2.0,
                    help="seconds; >=3 transitions inside it counts as chatter")
    ap.add_argument("--quiet", action="store_true",
                    help="only print files that have transitions")
    args = ap.parse_args()

    total = 0
    for path in args.logs:
        total += sweep(path, args.window, args.quiet)
    print(f"\n# chatter episodes found: {total}")


if __name__ == "__main__":
    main()
