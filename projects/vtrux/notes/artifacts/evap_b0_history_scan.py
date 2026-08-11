"""Phase 2 of the 2026-07-19 evap display investigation.

Question: the EVAP indicator (0x649 B0 bit 7) read correctly on past drives but
showed COMPLETE during an active evap cycle on 2026-07-19. What changed?

Scans every Android-logger session (and optionally the primary logs) for the
0x649 evap bytes and reports, per session:
  - first and last B0, plus the min/max B0 seen
  - whether B0 bit 7 was ever set (what the app decodes as vcm_evap_active)
  - first/last B4 and whether B4 bit 7 was ever set (candidate true flag)
  - max evap counter (B2[3:0]:B3) -- non-zero means a purge actually ran

Uses grep to pull only 0x649 lines, so a multi-GB session costs ~a second.
"""

import re
import subprocess
import sys
from collections import defaultdict

LOGDIR = "../../CANLogs/VtruxLogs"
SESSION_RE = re.compile(r"^(vtrux_\d{8}_\d{6})_T(\d+)\.log$")


def sessions(logdir):
    """Group chunk files into sessions, chunks in numeric order."""
    import os
    groups = defaultdict(list)
    for name in os.listdir(logdir):
        m = SESSION_RE.match(name)
        if m:
            groups[m.group(1)].append((int(m.group(2)), f"{logdir}/{name}"))
    for sess in sorted(groups):
        yield sess, [p for _, p in sorted(groups[sess])]


def scan_session(paths):
    """Return the evap summary for one session, or None if 0x649 never appears."""
    first_b0 = last_b0 = None
    first_b4 = last_b4 = None
    b0_min = b0_max = None
    b0_bit7_ever = False
    b4_bit7_ever = False
    ec_max = 0
    n = 0

    for path in paths:
        # grep is far cheaper than parsing the whole log for one ID
        p = subprocess.run(["grep", " 0x649 ", path],
                           capture_output=True, text=True)
        for line in p.stdout.splitlines():
            f = line.split()
            if len(f) < 14:
                continue
            try:
                b0 = int(f[6], 16)
                b2 = int(f[8], 16)
                b3 = int(f[9], 16)
                b4 = int(f[10], 16)
            except ValueError:
                continue
            n += 1
            if first_b0 is None:
                first_b0, first_b4 = b0, b4
            last_b0, last_b4 = b0, b4
            b0_min = b0 if b0_min is None else min(b0_min, b0)
            b0_max = b0 if b0_max is None else max(b0_max, b0)
            b0_bit7_ever |= bool(b0 & 0x80)
            b4_bit7_ever |= bool(b4 & 0x80)
            ec = ((b2 & 0x0F) << 8) | b3
            ec_max = max(ec_max, ec)

    if n == 0:
        return None
    return dict(frames=n, first_b0=first_b0, last_b0=last_b0,
                b0_min=b0_min, b0_max=b0_max, b0_bit7=b0_bit7_ever,
                first_b4=first_b4, last_b4=last_b4, b4_bit7=b4_bit7_ever,
                ec_max=ec_max)


def main():
    print(f"{'session':<22} {'frames':>9} {'B0 first/last':>14} {'B0 rng':>10} "
          f"{'b7':>3} {'B4 f/l':>9} {'b7':>3} {'ec_max':>7}  verdict")
    for sess, paths in sessions(LOGDIR):
        r = scan_session(paths)
        if r is None:
            continue
        purged = r["ec_max"] > 0
        # What the app showed vs what actually happened.
        shown = "PURGE" if r["b0_bit7"] else "COMPLETE"
        verdict = "OK" if (purged == r["b0_bit7"]) else "*** MISMATCH ***"
        if not purged and not r["b0_bit7"]:
            verdict = "ok (no evap)"
        print(f"{sess:<22} {r['frames']:>9} "
              f"0x{r['first_b0']:02X}/0x{r['last_b0']:02X}".rjust(0).ljust(0)
              + f"   0x{r['b0_min']:02X}-0x{r['b0_max']:02X} "
              f"{int(r['b0_bit7']):>3} "
              f"0x{r['first_b4']:02X}/0x{r['last_b4']:02X} "
              f"{int(r['b4_bit7']):>3} "
              f"{r['ec_max']:>7}  app={shown} {verdict}", flush=True)


if __name__ == "__main__":
    main()
