"""
Stream a log file and extract only VCU cluster (0x639-0x64B) frames.
Writes a CSV with columns: timestamp, arb_id, b0..b7
Run on each log separately to avoid loading everything into memory.

Usage:
  py -3.12 projects/vtrux/notes/artifacts/vcu_cluster_extract.py <logfile> <outcsv>
"""

import sys
import csv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from canre.parsers import parse_file

VCU_IDS = set(range(0x639, 0x64C))

log_path = sys.argv[1]
out_path = sys.argv[2]

n_total = 0
n_kept = 0

with open(out_path, "w", newline="") as fout:
    writer = csv.writer(fout)
    writer.writerow(["t", "id", "bus", "b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7"])
    for frame in parse_file(log_path):
        n_total += 1
        if frame.arbitration_id in VCU_IDS:
            row = [
                f"{frame.timestamp:.4f}",
                f"0x{frame.arbitration_id:03X}",
                frame.bus,
            ] + [frame.data[i] if i < len(frame.data) else "" for i in range(8)]
            writer.writerow(row)
            n_kept += 1
        if n_total % 1_000_000 == 0:
            print(f"  {n_total//1_000_000}M frames scanned, {n_kept} VCU kept...", flush=True)

print(f"Done. {n_total:,} total frames, {n_kept:,} VCU cluster frames -> {out_path}", flush=True)
