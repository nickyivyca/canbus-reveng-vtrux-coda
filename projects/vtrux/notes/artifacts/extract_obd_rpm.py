#!/usr/bin/env python3
"""Extract OBD-II PID 0x0C (engine RPM) timeseries from a CAN log.

Filters 0x7E8 responses for Mode 01 / PID 0x0C and decodes RPM using the
standard formula: RPM = (byteA * 256 + byteB) / 4.

Output CSV columns: timestamp,value  (same convention as extract_timeseries.py)

Usage:
    python extract_obd_rpm.py <log_file> [--bus N] [--output file.csv]
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from canre.parsers import parse_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", help="BUSMASTER log file path")
    parser.add_argument("--bus", type=int, default=None,
                        help="Filter to specific bus number (default: all buses)")
    parser.add_argument("--output", "-o", default=None,
                        help="Output CSV file (default: stdout)")
    args = parser.parse_args()

    rows = []
    for frame in parse_file(args.log):
        if frame.arbitration_id != 0x7E8:
            continue
        if args.bus is not None and frame.bus != args.bus:
            continue
        d = frame.data
        if len(d) < 5:
            continue
        # OBD-II Mode 01 response structure: [len, 0x41, PID, byte_A, byte_B, ...]
        if d[1] == 0x41 and d[2] == 0x0C:
            rpm = (d[3] * 256 + d[4]) / 4.0
            rows.append((frame.timestamp, rpm))

    if not rows:
        print("No OBD RPM frames found.", file=sys.stderr)
        sys.exit(1)

    if args.output:
        with open(args.output, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "value"])
            w.writerows(rows)
        print(f"Wrote {len(rows)} RPM samples to {args.output}", file=sys.stderr)
    else:
        print("timestamp,value")
        for t, r in rows:
            print(f"{t:.6f},{r:.2f}")


if __name__ == "__main__":
    main()
