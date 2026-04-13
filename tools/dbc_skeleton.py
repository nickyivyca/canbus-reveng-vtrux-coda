#!/usr/bin/env python3
"""Generate a skeleton DBC file from CAN bus traffic."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.parsers import parse_file
from canre.dbc.skeleton import generate_skeleton


def main():
    parser = argparse.ArgumentParser(description="Generate skeleton DBC from CAN traffic")
    parser.add_argument("log", help="Log file path")
    parser.add_argument("--output", "-o", default="skeleton.dbc", help="Output DBC file (default: skeleton.dbc)")
    parser.add_argument("--bus", type=int, default=None, help="Filter to specific bus")
    args = parser.parse_args()

    generate_skeleton(parse_file(args.log), args.output, bus_filter=args.bus)
    print(f"Skeleton DBC written to {args.output}")


if __name__ == "__main__":
    main()
