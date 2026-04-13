#!/usr/bin/env python3
"""Extract signal time series from CAN log to CSV."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.parsers import parse_file
from canre.utils.merge import merge_files
from canre.analysis.timeseries import extract_timeseries, save_timeseries_csv
from pathlib import Path


def _load_frames(log_paths: list[str]):
    paths = [Path(p) for p in log_paths]
    if len(paths) == 1:
        return parse_file(paths[0])
    return merge_files(paths)


def main():
    parser = argparse.ArgumentParser(description="Extract signal time series to CSV")
    parser.add_argument("log", nargs="+",
                        help="Log file(s). Pass multiple T-chunk files to merge "
                             "them into a single session at runtime.")
    parser.add_argument("--id", required=True, help="CAN ID (hex, e.g. 0x123)")
    parser.add_argument("--bytes", required=True, help="Byte range (e.g. '2' or '2-3')")
    parser.add_argument("--endian", choices=["big", "little"], default="big", help="Byte order")
    parser.add_argument("--signed", action="store_true", help="Interpret as signed")
    parser.add_argument("--output", "-o", help="Output CSV file (default: stdout)")
    parser.add_argument("--bus", type=int, default=None, help="Filter to specific bus")
    args = parser.parse_args()

    target_id = int(args.id, 16) if args.id.startswith(("0x", "0X")) else int(args.id, 16)

    # Parse byte range
    if "-" in args.bytes:
        start, end = args.bytes.split("-")
        byte_start = int(start)
        byte_count = int(end) - byte_start + 1
    else:
        byte_start = int(args.bytes)
        byte_count = 1

    data = extract_timeseries(
        _load_frames(args.log), target_id,
        byte_start=byte_start, byte_count=byte_count,
        endian=args.endian, signed=args.signed,
        bus_filter=args.bus
    )

    if args.output:
        save_timeseries_csv(data, args.output)
        print(f"Saved {len(data)} samples to {args.output}")
    else:
        print("timestamp,value")
        for ts, val in data:
            print(f"{ts:.6f},{val}")


if __name__ == "__main__":
    main()
