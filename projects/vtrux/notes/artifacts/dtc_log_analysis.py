#!/usr/bin/env python3
"""Scratchpad for analyzing DTC interrogation session logs.

Usage:
    py -3.12 projects/vtrux/notes/artifacts/dtc_log_analysis.py <log_file>
"""

import sys
from pathlib import Path

PT_ANCHORS  = {0x051, 0x054, 0x471, 0x479, 0x482, 0x592, 0x639}
OBD_ANCHORS = {0x040, 0x041, 0x042, 0x043, 0x044, 0x441, 0x44A}
VEH_ANCHORS = {0x1E5, 0x500, 0x514, 0x52A, 0x778, 0x780}


def parse_log(path):
    """Return list of (ts_s, direction, arb_id, data_bytes) from a BUSMASTER log."""
    frames = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[1] not in ("Rx", "Tx"):
            continue
        try:
            t = parts[0].split(":")
            ts = int(t[0]) * 3600 + int(t[1]) * 60 + int(t[2]) + int(t[3]) / 10000
            arb = int(parts[3], 16)
            dlc = int(parts[5])
            data = [int(b, 16) for b in parts[6:6 + dlc]]
            frames.append((ts, parts[1], arb, data))
        except (ValueError, IndexError):
            pass
    return frames


def analyze(log_path):
    frames = parse_log(log_path)
    if not frames:
        print("No frames parsed.")
        return

    # Find first Tx timestamp (start of request phase)
    first_tx_ts = next((ts for ts, d, _, __ in frames if d == "Tx"), None)

    all_ids = {arb for _, _, arb, __ in frames}
    pre_ids = {arb for ts, d, arb, _ in frames if d == "Rx" and (first_tx_ts is None or ts <= first_tx_ts)}
    post_rx = [(ts, arb, data) for ts, d, arb, data in frames if d == "Rx" and first_tx_ts and ts > first_tx_ts]

    print(f"Total frames   : {len(frames)}")
    print(f"Unique IDs     : {len(all_ids)}")
    print(f"First Tx at    : {first_tx_ts:.2f}s" if first_tx_ts else "First Tx at    : (none)")
    print()
    print(f"PT  anchors hit: {sorted(hex(x) for x in all_ids & PT_ANCHORS)}")
    print(f"OBD anchors hit: {sorted(hex(x) for x in all_ids & OBD_ANCHORS)}")
    print(f"Veh anchors hit: {sorted(hex(x) for x in all_ids & VEH_ANCHORS)}")
    print()

    # Diagnostic address range after Tx
    diag = [(ts, arb, data) for ts, arb, data in post_rx if 0x7E0 <= arb <= 0x7FF]
    print(f"Frames in 0x7E0-0x7FF after Tx: {len(diag)}")
    for ts, arb, data in diag[:20]:
        print(f"  {ts:.3f}s  0x{arb:03X}  {' '.join(f'{b:02X}' for b in data)}")

    print()

    # 0x065B frames after Tx
    dtc_frames = [(ts, arb, data) for ts, arb, data in post_rx if arb == 0x065B]
    print(f"0x065B frames after Tx: {len(dtc_frames)}")
    for ts, arb, data in dtc_frames[:10]:
        print(f"  {ts:.3f}s  {' '.join(f'{b:02X}' for b in data)}")

    print()

    # IDs that appeared only after Tx
    new_ids = {arb for _, arb, __ in post_rx} - pre_ids
    print(f"IDs that appeared only after Tx: {sorted(hex(x) for x in new_ids)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py -3.12 dtc_log_analysis.py <log_file>")
        sys.exit(1)
    analyze(sys.argv[1])
