#!/usr/bin/env python3
"""Merge chunked CAN bus log captures."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.utils.merge import detect_capture_groups, merge_files


def main():
    parser = argparse.ArgumentParser(description="Merge chunked CAN bus captures")
    parser.add_argument("directory", help="Directory containing log file chunks")
    parser.add_argument("--output", "-o", help="Output file (default: print summary)")
    parser.add_argument("--group", help="Process only this capture group")
    args = parser.parse_args()

    groups = detect_capture_groups(Path(args.directory))

    if not groups:
        print("No capture groups found (looking for _M{bus}_T{chunk} pattern)")
        return

    for group_name, files in groups.items():
        if args.group and group_name != args.group:
            continue

        bus_count = len(set(f.get("bus", 0) for f in files)) if isinstance(files[0], dict) else "?"
        print(f"Group: {group_name}")
        print(f"  Files: {len(files)}")

        if args.output:
            out_path = args.output if len(groups) == 1 else f"{Path(args.output).stem}_{group_name}{Path(args.output).suffix}"
            count = 0
            with open(out_path, "w") as fout:
                fout.write("timestamp,bus,id,extended,dlc,data\n")
                for frame in merge_files(files):
                    data_hex = frame.data.hex()
                    fout.write(f"{frame.timestamp:.6f},{frame.bus},0x{frame.arbitration_id:X},{frame.is_extended},{frame.dlc},{data_hex}\n")
                    count += 1
            print(f"  Wrote {count} frames to {out_path}")
        else:
            count = sum(1 for _ in merge_files(files))
            print(f"  Total frames: {count}")


if __name__ == "__main__":
    main()
