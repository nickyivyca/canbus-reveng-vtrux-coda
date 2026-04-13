#!/usr/bin/env python3
"""Compare two CAN bus captures."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.parsers import parse_file
from canre.analysis.diff import diff_captures, format_diff


def main():
    parser = argparse.ArgumentParser(description="Compare two CAN bus captures")
    parser.add_argument("log_a", help="First log file")
    parser.add_argument("log_b", help="Second log file")
    parser.add_argument("--ids-only", action="store_true", help="Only compare IDs, skip byte-level diff")
    parser.add_argument("--bus", type=int, default=None, help="Filter to specific bus")
    args = parser.parse_args()

    frames_a = parse_file(args.log_a)
    frames_b = parse_file(args.log_b)
    results = diff_captures(frames_a, frames_b, bus_filter=args.bus)
    print(format_diff(results, ids_only=args.ids_only))


if __name__ == "__main__":
    main()
