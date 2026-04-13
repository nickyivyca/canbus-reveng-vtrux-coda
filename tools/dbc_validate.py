#!/usr/bin/env python3
"""Validate DBC file coverage against CAN bus traffic."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.parsers import parse_file
from canre.dbc.validator import validate_dbc, format_validation


def main():
    parser = argparse.ArgumentParser(description="Validate DBC coverage against traffic")
    parser.add_argument("dbc", help="DBC file path")
    parser.add_argument("log", help="Log file path")
    parser.add_argument("--bus", type=int, default=None, help="Filter to specific bus")
    args = parser.parse_args()

    results = validate_dbc(args.dbc, parse_file(args.log), bus_filter=args.bus)
    print(format_validation(results))


if __name__ == "__main__":
    main()
