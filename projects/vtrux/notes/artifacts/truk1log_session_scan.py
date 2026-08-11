"""
Scan truk1log files to identify which sessions have PT bus / BMS data (0x430, 0x410).
Run from project root:
    py -3.12 projects/vtrux/notes/artifacts/truk1log_session_scan.py
"""
import sys, os, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
from canre.parsers import parse_file

logs = sorted(glob.glob('projects/vtrux/logs/truk1log*.log'))
print(f"{'file':35s}  {'frames':>7}  {'0x430':>6}  {'0x410':>6}  {'time range':>20}")
print("-" * 85)
for log in logs:
    frames = list(parse_file(log))
    if not frames:
        print(f"{os.path.basename(log):35s}  {'empty':>7}")
        continue
    ids = set(f.arbitration_id for f in frames)
    t_range = f"{frames[0].timestamp:.0f}s -- {frames[-1].timestamp:.0f}s"
    print(f"{os.path.basename(log):35s}  {len(frames):7d}  {str(0x430 in ids):>6}  {str(0x410 in ids):>6}  {t_range:>20}")
