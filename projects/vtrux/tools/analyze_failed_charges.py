#!/usr/bin/env python3
"""Analyze failed charge events from Bel Inverter logs.

Convenience wrapper that discovers sessions in a directory and analyzes each one.
This combines list_sessions.py + analyze_session.py for batch processing.

For more control, use the individual tools:
    python tools/list_sessions.py "logs"
    python tools/analyze_session.py "logs/specific_file.log"

Usage:
    python tools/analyze_failed_charges.py "Bel-Inverter/actual-failed-charges"
    python tools/analyze_failed_charges.py "Bel-Inverter/actual-failed-charges" --session M0
    python tools/analyze_failed_charges.py "logs"
"""
import argparse
import sys
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.utils.sessions import group_files_by_session
from analyze_session import analyze_session


def main():
    parser = argparse.ArgumentParser(description="Analyze failed charge events")
    parser.add_argument("path", help="Directory containing failed charge log files")
    parser.add_argument("--session", help="Only analyze specific session (e.g. M0)")
    parser.add_argument(
        "--window",
        type=float,
        default=5.0,
        help="Window size in seconds around fault events (default: 5)",
    )
    args = parser.parse_args()

    folder = Path(args.path)
    if not folder.is_dir():
        print(f"Error: {folder} is not a directory")
        sys.exit(1)

    # Discover sessions in directory
    sessions = group_files_by_session(folder)
    if not sessions:
        print(f"No log files found in {folder}")
        sys.exit(1)

    print(
        f"Found {len(sessions)} capture session(s): {', '.join(sorted(sessions.keys()))}"
    )
    for name, files in sorted(sessions.items()):
        print(f"  {name}: {len(files)} file(s) ({files[0].name} .. {files[-1].name})")

    # Analyze each session (or just the requested one)
    for session_name, files in sorted(sessions.items()):
        if args.session and session_name != args.session:
            continue
        analyze_session(files, session_name, window_sec=args.window)


if __name__ == "__main__":
    main()
