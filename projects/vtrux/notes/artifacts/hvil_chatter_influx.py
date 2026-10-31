"""Corpus-wide hunt for interlock chatter, via InfluxDB.

Complements `hvil_chatter_sweep.py`, which raw-scans individual captures. The
Influx write policy is on-change plus a 1 s heartbeat, so every *transition* of
a boolean like `bcm_hvil_mon` is stored exactly -- which is all this needs.
(Rate and inter-frame timing are not preserved, so any timing measured here
must be confirmed against the raw log before it is trusted.)

Reports every hvil transition, flags runs of >= 3 transitions inside
`--window` seconds as chatter, and records whether `bcm_epo` was asserted
during the episode -- the question that matters for the fault-display gate,
which currently triggers on EPO.

Usage:
    py -3.11 projects/vtrux/notes/artifacts/hvil_chatter_influx.py \
        --start 2026-01-01 --end 2027-01-01
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import argparse
import json
import subprocess
from datetime import datetime

INFLUX = "http://localhost:8086/query"
AUTH = "claude:claude"
DB = "canbus-data"


def query(q: str) -> list[dict]:
    out = subprocess.run(
        ["curl", "-s", "-G", INFLUX, "-u", AUTH,
         "--data-urlencode", f"db={DB}",
         "--data-urlencode", f"q={q}"],
        capture_output=True, text=True, check=True,
    ).stdout
    payload = json.loads(out)
    results = payload.get("results", [{}])[0]
    if "error" in results:
        raise RuntimeError(results["error"])
    return results.get("series", [])


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2027-01-01")
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--vehicle", default="vtrux")
    args = ap.parse_args()

    q = (
        'SELECT "bcm_hvil_mon", "bcm_epo", "bcm_mainc_stat" FROM signals '
        f"WHERE vehicle='{args.vehicle}' "
        f"AND time >= '{args.start}T00:00:00Z' AND time < '{args.end}T00:00:00Z' "
        "GROUP BY session"
    )
    series = query(q)
    print(f"# sessions returned: {len(series)}")

    episodes = 0
    for s in series:
        session = s["tags"]["session"]
        cols = s["columns"]
        i_hvil = cols.index("bcm_hvil_mon")
        i_epo = cols.index("bcm_epo")

        transitions = []
        prev = None
        last_epo = None
        for row in s["values"]:
            if row[i_epo] is not None:
                last_epo = int(row[i_epo])
            if row[i_hvil] is None:
                continue
            hvil = int(row[i_hvil])
            t = parse_time(row[0])
            if prev is not None and hvil != prev:
                transitions.append((t, prev, hvil, last_epo))
            prev = hvil

        if len(transitions) < 3:
            continue

        marks = set()
        for i in range(len(transitions)):
            j = i
            while (j + 1 < len(transitions)
                   and (transitions[j + 1][0] - transitions[i][0]).total_seconds()
                   <= args.window):
                j += 1
            if j - i + 1 >= 3:
                marks.update(range(i, j + 1))
        if not marks:
            continue

        episodes += 1
        lo, hi = min(marks), max(marks)
        span = (transitions[hi][0] - transitions[lo][0]).total_seconds()
        epo_any = any(transitions[i][3] == 1 for i in marks)
        print(f"\n{session}: CHATTER -- {len(marks)} transitions in {span:.3f}s")
        print(f"  EPO asserted during episode: {'yes' if epo_any else 'NO'}")
        for i in range(lo, hi + 1):
            t, old, new, epo = transitions[i]
            print(f"    {t.isoformat()}  hvil {old} -> {new}   epo={epo}")

    print(f"\n# chatter episodes: {episodes}")


if __name__ == "__main__":
    main()
