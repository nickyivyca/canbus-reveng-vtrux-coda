#!/usr/bin/env python3
"""Bus survey tool - analyze CAN bus traffic from log files."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.parsers import parse_file
from canre.analysis.survey import run_survey, format_survey, save_survey_json
from canre.utils.merge import detect_capture_groups, merge_files


def main():
    parser = argparse.ArgumentParser(description="Survey CAN bus traffic from log files")
    parser.add_argument("path", help="Log file or directory of log files")
    parser.add_argument("--bus", type=int, default=None, help="Filter to specific bus number")
    parser.add_argument("--output", "-o", help="Save results to JSON file")
    args = parser.parse_args()

    p = Path(args.path)
    if p.is_dir():
        groups = detect_capture_groups(p)
        if groups:
            # Merge grouped files
            for group_name, files in groups.items():
                print(f"\n=== Capture Group: {group_name} ===")
                frames = merge_files(files)
                results = run_survey(frames, bus_filter=args.bus)
                print(format_survey(results))
                if args.output:
                    out = Path(args.output).with_stem(f"{Path(args.output).stem}_{group_name}")
                    save_survey_json(results, out)
                    print(f"\nResults saved to {out}")
        else:
            # Process each file individually
            for f in sorted(p.glob("*.log")):
                print(f"\n=== {f.name} ===")
                results = run_survey(parse_file(f), bus_filter=args.bus)
                print(format_survey(results))
    else:
        results = run_survey(parse_file(p), bus_filter=args.bus)
        print(format_survey(results))
        if args.output:
            save_survey_json(results, args.output)
            print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
