#!/usr/bin/env python3
"""List and group CAN log files by session.

Groups files matching _M#_T# pattern and lists standalone files.

Usage:
    python tools/list_sessions.py "logs"
    python tools/list_sessions.py "Bel-Inverter/actual-failed-charges"
    python tools/list_sessions.py "logs" --json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.utils.sessions import group_files_by_session


def main():
    parser = argparse.ArgumentParser(
        description="List and group CAN log files by session"
    )
    parser.add_argument("path", help="Directory containing log files")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of human-readable format",
    )
    args = parser.parse_args()

    folder = Path(args.path)
    if not folder.is_dir():
        print(f"Error: {folder} is not a directory", file=sys.stderr)
        sys.exit(1)

    sessions = group_files_by_session(folder)

    if not sessions:
        print(f"No log files found in {folder}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        # JSON output
        output = {}
        for name, files in sorted(sessions.items()):
            output[name] = {
                "file_count": len(files),
                "files": [str(f) for f in files],
            }
        print(json.dumps(output, indent=2))
    else:
        # Human-readable output
        print(f"Found {len(sessions)} session(s) in {folder}:\n")

        for name, files in sorted(sessions.items()):
            if len(files) == 1:
                print(f"  {name}: 1 file")
                print(f"    {files[0].name}")
            else:
                print(f"  {name}: {len(files)} files")
                print(f"    {files[0].name} .. {files[-1].name}")

        # Summary
        total_files = sum(len(files) for files in sessions.values())
        multi_file = sum(1 for files in sessions.values() if len(files) > 1)
        single_file = len(sessions) - multi_file

        print(f"\nSummary:")
        print(f"  Total sessions: {len(sessions)}")
        print(f"  Multi-file sessions: {multi_file}")
        print(f"  Single-file sessions: {single_file}")
        print(f"  Total files: {total_files}")


if __name__ == "__main__":
    main()
