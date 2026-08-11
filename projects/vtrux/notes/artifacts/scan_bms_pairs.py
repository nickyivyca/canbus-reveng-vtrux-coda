"""
scan_bms_pairs.py

16-bit byte-pair scan of all BMS cluster IDs (0x400-0x507).
Tests every adjacent pair (B[i], B[i+1]) as both LE and BE.
Reports pairs whose decoded value has 2-40 unique counts
(discrete limit or moderate-resolution analog) and shows
any difference across the three reference event windows.

Skip IDs already fully characterized.
"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parents[4]))
from canre.parsers.autodetect import parse_file

LOG = Path(__file__).parents[4] / "projects/vtrux/logs/vtruxcurrentlimitingtest.log"

SKIP_IDS = {0x410, 0x420, 0x430, 0x440, 0x460, 0x482, 0x506, 0x507}

WINDOWS = [
    ('unreg',  30,   72),
    ('regen', 401,  503),
    ('dch',   598,  700),
]

# Collect raw bytes per frame
raw = defaultdict(list)          # aid -> list of (t, bytes)
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
    raw[aid].append((t, bytes(d)))

print(f"IDs: {sorted(f'0x{x:03X}' for x in id_frames)}\n")

def win_name(t):
    for wn, t0, t1 in WINDOWS:
        if t0 <= t <= t1:
            return wn
    return None

def fmt_vals(vals):
    if not vals:
        return '--'
    u = sorted(set(vals))
    if len(u) <= 8:
        return str(u)
    return f'({len(u)}u {min(u)}-{max(u)})'

print("=== 16-bit pair scan (adjacent bytes, LE and BE) ===\n")
for aid in sorted(id_frames):
    frames = raw[aid]
    if not frames:
        continue
    n_bytes = max(len(d) for _, d in frames)

    found = []
    for i in range(n_bytes - 1):
        for endian, label in [('LE', 'LE'), ('BE', 'BE')]:
            all_v  = []
            win_v  = {wn: [] for wn, *_ in WINDOWS}

            for t, d in frames:
                if i + 1 >= len(d):
                    continue
                if endian == 'LE':
                    v = d[i] | (d[i+1] << 8)
                else:
                    v = (d[i] << 8) | d[i+1]
                all_v.append(v)
                wn = win_name(t)
                if wn:
                    win_v[wn].append(v)

            if not all_v:
                continue
            n_u = len(set(all_v))
            if n_u < 2 or n_u > 40:
                continue

            # Check if it differs across windows
            win_sets = [set(win_v[wn]) for wn, *_ in WINDOWS if win_v[wn]]
            if len(win_sets) < 2:
                continue
            # At least one window must differ from another
            if all(win_sets[0] == s for s in win_sets[1:]):
                # Constant across windows — only include if very few unique (2-6)
                if n_u > 6:
                    continue

            rng = f"{min(all_v)}-{max(all_v)}"
            w_strs = [fmt_vals(win_v[wn]) for wn, *_ in WINDOWS]
            found.append((i, label, n_u, rng, w_strs))

    if found:
        print(f"0x{aid:03X}  ({id_frames[aid]} frames):")
        for i, label, n_u, rng, w_strs in found:
            print(f"  B{i}-B{i+1} {label}  {n_u:3d}u  {rng:<12}"
                  f"  unreg={w_strs[0]}  regen={w_strs[1]}  dch={w_strs[2]}")
        print()
