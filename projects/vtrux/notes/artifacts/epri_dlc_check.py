"""
epri_dlc_check.py -- Compare EPRI DBC declared DLCs against actual frame DLCs in a log.

Usage (from project root):
    py -3.12 projects/vtrux/notes/artifacts/epri_dlc_check.py <log_file>

Reads both epri-pt-bus.dbc and epri-obd-bus.dbc, extracts all message IDs and their
declared DLCs, then scans the log for those IDs and reports the actual DLC seen.
Flags any mismatch.
"""

import sys
import os
import cantools
sys.path.insert(0, os.path.abspath("."))
from canre.parsers import parse_file

def main():
    if len(sys.argv) < 2:
        print("Usage: py -3.12 projects/vtrux/notes/artifacts/epri_dlc_check.py <log_file>")
        sys.exit(1)

    log_path = sys.argv[1]
    dbc_paths = [
        "projects/vtrux/epri-pt-bus.dbc",
        "projects/vtrux/epri-obd-bus.dbc",
    ]

    # Collect declared DLCs from both DBCs
    declared = {}  # arbitration_id -> (dbc_dlc, msg_name, dbc_file)
    for dbc_path in dbc_paths:
        db = cantools.db.load_file(dbc_path, strict=False)
        for msg in db.messages:
            declared[msg.frame_id] = (msg.length, msg.name, os.path.basename(dbc_path))

    print(f"Loaded {len(declared)} EPRI messages from DBCs")
    print(f"Scanning log: {log_path}\n")

    # Collect actual DLCs seen in log -- track all DLCs seen per ID (modal)
    from collections import defaultdict, Counter
    actual_dlcs = defaultdict(Counter)

    frames = parse_file(log_path)
    for frame in frames:
        if frame.arbitration_id in declared:
            actual_dlcs[frame.arbitration_id][frame.dlc] += 1

    # Report
    ok = []
    mismatch = []
    not_seen = []

    for arbitration_id, (dbc_dlc, msg_name, dbc_file) in sorted(declared.items()):
        if arbitration_id not in actual_dlcs:
            not_seen.append((arbitration_id, dbc_dlc, msg_name, dbc_file))
            continue
        modal_dlc = actual_dlcs[arbitration_id].most_common(1)[0][0]
        all_dlcs = dict(actual_dlcs[arbitration_id])
        if modal_dlc == dbc_dlc:
            ok.append((arbitration_id, dbc_dlc, msg_name, dbc_file))
        else:
            mismatch.append((arbitration_id, dbc_dlc, modal_dlc, all_dlcs, msg_name, dbc_file))

    print("=== MISMATCHES ===")
    if mismatch:
        for arbitration_id, dbc_dlc, modal_dlc, all_dlcs, msg_name, dbc_file in mismatch:
            print(f"  0x{arbitration_id:03X}  {msg_name}")
            print(f"    DBC claims DLC={dbc_dlc}, log shows DLC={modal_dlc}  (all seen: {all_dlcs})  [{dbc_file}]")
    else:
        print("  None")

    print("\n=== OK (DLC matches) ===")
    for arbitration_id, dbc_dlc, msg_name, dbc_file in ok:
        print(f"  0x{arbitration_id:03X}  DLC={dbc_dlc}  {msg_name}")

    print("\n=== NOT SEEN IN LOG ===")
    for arbitration_id, dbc_dlc, msg_name, dbc_file in not_seen:
        print(f"  0x{arbitration_id:03X}  DLC={dbc_dlc}  {msg_name}  [{dbc_file}]")

if __name__ == "__main__":
    main()
