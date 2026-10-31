"""Census of 0x460 BMS fault records across a set of captures.

Lists every distinct 3-byte record seen per file, when it first appeared, and
flags any record not in the catalog in `notes/battery-fault-codes.md` -- i.e.
codes this project has never characterised.

Raw line scan (see `hvil_chatter_sweep.py` for why) filtered to DLC=8, which
excludes the unrelated OBD-bus 0x460 (TRAC MCU, DLC=5).

Usage:
    py -3.11 projects/vtrux/notes/artifacts/fault_record_census.py \
        ../../CANLogs/VtruxLogs/vtrux_20260618_*.log
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import argparse
import re
from pathlib import Path

LINE_RE = re.compile(
    r"^(\d{1,2}):(\d{2}):(\d{2}):(\d{4})\s+\S+\s+\d+\s+0x0*460\s+s\s+8\s+"
    + r"\s+".join([r"([0-9A-Fa-f]{2})"] * 8),
    re.IGNORECASE,
)

# Everything named or at least observed in notes/battery-fault-codes.md.
KNOWN = {
    "FC 22 02": "steady-state charge fault",
    "F0 E0 00": "precharge abort",
    "F6 C0 01": "contactor-fault family",
    "F6 C3 02": "welded MAINN",
    "F6 C5 03": "bad precharge contactor",
    "F6 CF 00": "interlock opened while HV up",
    "FC 16 F2": "generator inverter not communicating",
    "FB B6 E4": "observed, identity unknown",
    "AC 10 00": "fault-EPO record",
    "AC 10 01": "fault-EPO record, param 01 (2026-06-18 only)",
    "F0 00 00": "universal fault-trip record",
    "FB C0 00": "charger went away during charge",
    "FC B0 00": "observed, meaning unknown",
    "FB E0 00": "observed, meaning unknown",
    "FB E0 02": "observed, meaning unknown",
    "FB E0 03": "observed, meaning unknown",
    "F7 00 00": "hypothesis: 12V-loss/reset",
    "F8 00 00": "hypothesis: 12V-loss/reset",
    "DE E0 03": "Truck 3 only",
}


def census(path: Path) -> dict[str, float]:
    first_seen: dict[str, float] = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "0x460" not in line:
                continue
            m = LINE_RE.match(line)
            if not m:
                continue
            h, mi, s, ticks = (int(m.group(i)) for i in range(1, 5))
            t = h * 3600.0 + mi * 60.0 + s + ticks * 0.0001
            b = [int(m.group(i), 16) for i in range(5, 13)]
            if b[0] == 0:
                continue  # header page, no records
            for rec in (b[2:5], b[5:8]):
                if not any(rec):
                    continue
                key = " ".join(f"{x:02X}" for x in rec)
                first_seen.setdefault(key, t)
    return first_seen


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="+", type=Path)
    args = ap.parse_args()

    all_unknown: dict[str, list[str]] = {}
    for path in args.logs:
        seen = census(path)
        if not seen:
            continue
        unknown = {k: v for k, v in seen.items() if k not in KNOWN}
        marker = "  ** UNKNOWN CODES **" if unknown else ""
        print(f"\n{path.name}{marker}")
        for key, t in sorted(seen.items(), key=lambda kv: kv[1]):
            tag = KNOWN.get(key, "*** NOT IN CATALOG ***")
            print(f"   t={t:9.3f}  {key}   {tag}")
        for key in unknown:
            all_unknown.setdefault(key, []).append(path.name)

    print("\n" + "=" * 60)
    if all_unknown:
        print("Records not in the catalog:")
        for key, files in sorted(all_unknown.items()):
            print(f"  {key}  in {len(files)} file(s): {files[0]}"
                  + (" ..." if len(files) > 1 else ""))
    else:
        print("No uncatalogued records found.")


if __name__ == "__main__":
    main()
