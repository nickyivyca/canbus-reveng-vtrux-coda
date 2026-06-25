#!/usr/bin/env python3
"""Deep analysis of a specific CAN ID."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.parsers import parse_file
from canre.utils.merge import merge_files
from canre.analysis.bitstats import analyze_id, format_bitstats
from canre.analysis.counters import detect_counters, detect_checksums
from pathlib import Path


def _load_frames(log_paths: list[str]) -> list:
    paths = [Path(p) for p in log_paths]
    if len(paths) == 1:
        return list(parse_file(paths[0]))
    return list(merge_files(paths))


def main():
    parser = argparse.ArgumentParser(description="Deep-dive analysis of a specific CAN ID")
    parser.add_argument("log", nargs="+",
                        help="Log file(s). Pass multiple T-chunk files to merge "
                             "them into a single session at runtime.")
    parser.add_argument("--id", required=True, help="CAN ID to analyze (hex, e.g. 0x123)")
    parser.add_argument("--bus", type=int, default=None, help="Filter to specific bus")
    parser.add_argument("--dbc", help="Optional DBC file for signal decoding context")
    parser.add_argument("--start", type=float, default=None,
                        help="Start of time window in seconds (relative to capture start)")
    parser.add_argument("--end", type=float, default=None,
                        help="End of time window in seconds (relative to capture start)")
    args = parser.parse_args()

    target_id = int(args.id, 16) if args.id.startswith("0x") or args.id.startswith("0X") else int(args.id, 16)

    # Load all frames once; reuse for all passes.
    all_frames = _load_frames(args.log)

    if args.start is not None or args.end is not None:
        t0 = args.start if args.start is not None else float("-inf")
        t1 = args.end if args.end is not None else float("inf")
        all_frames = [f for f in all_frames if t0 <= f.timestamp <= t1]
        window_desc = f" [t={t0:.1f}s..{t1:.1f}s]" if args.start is not None and args.end is not None \
            else (f" [t>={t0:.1f}s]" if args.start is not None else f" [t<={t1:.1f}s]")
        print(f"Time window filter applied: {len(all_frames)} frames retained{window_desc}")

    # First pass: bit statistics
    print(f"=== Analysis of ID {args.id} ===\n")
    stats = analyze_id(iter(all_frames), target_id, bus_filter=args.bus)
    print(format_bitstats(stats))

    # Second pass: counter/checksum detection
    print("\n=== Counter Detection ===\n")
    counter_results = detect_counters(iter(all_frames), target_id, bus_filter=args.bus)
    if counter_results.get("counters"):
        for pos, info in counter_results["counters"].items():
            print(f"  Byte {pos}: Rolling counter detected (confidence: {info['confidence']:.1%})")
    else:
        print("  No rolling counters detected.")

    # Third pass: checksum detection (needs list of frames)
    print("\n=== Checksum Detection ===\n")
    frames_list = [f for f in all_frames
                   if f.arbitration_id == target_id and (args.bus is None or f.bus == args.bus)]
    if frames_list:
        checksum_results = detect_checksums(frames_list, target_id)
        if checksum_results.get("checksums"):
            found_any = False
            for pos, info in checksum_results["checksums"].items():
                if info.get("best") is not None:
                    print(f"  Byte {pos}: {info['best']} (confidence: {info['best_confidence']:.1%})")
                    found_any = True
            if not found_any:
                print("  No checksums detected.")
        else:
            print("  No checksums detected.")

    # DBC decode if provided
    if args.dbc:
        try:
            import cantools
            db = cantools.database.load_file(args.dbc)
            msg = db.get_message_by_frame_id(target_id)
            print(f"\n=== DBC Definition: {msg.name} ===")
            print(f"  Signals: {', '.join(s.name for s in msg.signals)}")
            if frames_list:
                sample = frames_list[0]
                decoded = msg.decode(sample.data)
                print(f"  Sample decode: {decoded}")
        except Exception as e:
            print(f"\n  DBC decode error: {e}")


if __name__ == "__main__":
    main()
