"""
scan_bms_cluster.py

Scan all BMS-cluster IDs (0x400-0x507) for current-limit and analog candidates.
Reports per-byte stats plus behavior in three reference event windows.

Flags:
  DISCRETE  : 2-8 unique values  -- stepped limit candidate
  ANALOG    : 9-60 unique values  -- slowly-varying measurement candidate
  (bytes with >60 unique values or constant are not flagged)

Reference windows (confirmed from climit log):
  unrestricted_regen  : t=30-72s
  regen_limit_active  : t=401-503s
  highway_discharge   : t=598-700s
"""

import sys
from pathlib import Path
from collections import defaultdict
import statistics

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"

# IDs already fully characterized -- skip to keep output focused
SKIP_IDS = {0x440, 0x460, 0x410, 0x420, 0x482}

WINDOWS = [
    ('unreg',  30,   72),
    ('regen', 401,  503),
    ('dch',   598,  700),
]

# Collect: all_vals[aid][byte] and win_vals[aid][wname][byte]
all_vals  = defaultdict(lambda: defaultdict(list))
win_vals  = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
id_frames = defaultdict(int)

print("Parsing log...")
for frame in parse_file(str(LOG)):
    t   = frame.timestamp
    d   = frame.data
    aid = frame.arbitration_id

    if not (0x400 <= aid <= 0x507):
        continue
    if aid in SKIP_IDS:
        continue

    id_frames[aid] += 1
    for i, b in enumerate(d):
        all_vals[aid][i].append(b)

    for wname, t0, t1 in WINDOWS:
        if t0 <= t <= t1:
            for i, b in enumerate(d):
                win_vals[aid][wname][i].append(b)

print(f"IDs found in 0x400-0x507 (excl. already-analyzed): "
      f"{sorted(f'0x{x:03X}' for x in id_frames)}\n")

def fmt_win(vals):
    if not vals:
        return '--'
    u = sorted(set(vals))
    if len(u) <= 6:
        return str(u)
    return f'({len(u)}u {min(u)}-{max(u)})'

# Print results per ID
for aid in sorted(id_frames):
    n_bytes = max(all_vals[aid].keys()) + 1
    print(f"=== 0x{aid:03X}  ({id_frames[aid]} frames, {n_bytes} bytes) ===")
    found_anything = False
    for i in range(n_bytes):
        vals = all_vals[aid][i]
        if not vals:
            continue
        u = sorted(set(vals))
        n_u = len(u)
        rng = f"{min(u)}-{max(u)}"
        mean = statistics.mean(vals)

        if n_u == 1:
            flag = 'CONST'
        elif n_u <= 8:
            flag = 'DISCRETE'
        elif n_u <= 60:
            flag = 'ANALOG'
        else:
            flag = ''

        if not flag:
            continue  # skip high-noise bytes

        found_anything = True
        w_strs = [fmt_win(win_vals[aid][wn][i]) for wn, *_ in WINDOWS]
        print(f"  B{i}  {flag:<10}  {n_u:3d}u  range={rng:<8}  mean={mean:5.1f}"
              f"  | unreg={w_strs[0]}  regen={w_strs[1]}  dch={w_strs[2]}")

    if not found_anything:
        print("  (no DISCRETE or ANALOG bytes)")
    print()
