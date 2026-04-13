"""
balancing_count_spikes.py

For each session, find count values that are elevated relative to their
local neighbors (i.e., true spikes, not just regions of higher density).
Reports values where count > N * local_median for a sliding window.

Usage:
  py -3.12 projects/vtrux/notes/artifacts/balancing_count_spikes.py
"""

import os
import sys
import cantools
from pathlib import Path
import statistics

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from canre.utils.merge import merge_files
from canre.utils.sessions import group_files_by_session

DBC_PATH  = os.path.join(PROJECT_ROOT, "projects", "vtrux", "epri-pt-bus.dbc")
LOGS_ROOT = os.path.join(PROJECT_ROOT, "projects", "vtrux", "logs")
SWAP_ROOT = os.path.join(LOGS_ROOT, "after-battery-swap-charges")
PT_BUS_ANCHOR_IDS = {0x410, 0x420, 0x430, 0x440, 0x471}
SAMPLE_LIMIT = 200000
WINDOW = 8
SPIKE_RATIO = 3.0


def identify_pt_bus(file_paths):
    counts = {}
    for i, frame in enumerate(merge_files(file_paths)):
        if frame.arbitration_id in PT_BUS_ANCHOR_IDS:
            counts[frame.bus] = counts.get(frame.bus, 0) + 1
        if i >= SAMPLE_LIMIT:
            break
    return max(counts, key=counts.get) if counts else None


def get_cnt_distribution(file_paths):
    pt_bus = identify_pt_bus(file_paths)
    if pt_bus is None:
        return None
    dist = {}
    for frame in merge_files(file_paths):
        if frame.bus != pt_bus:
            continue
        if frame.arbitration_id == 0x440 and len(frame.data) >= 8:
            raw = frame.data[7]
            if 0 < raw < 0xFE:
                dist[raw] = dist.get(raw, 0) + 1
    return dist


def find_spikes(dist, window=WINDOW, ratio=SPIKE_RATIO):
    if not dist:
        return []
    all_vals = sorted(dist)
    spikes = []
    for v in all_vals:
        neighbors = [dist.get(n, 0) for n in range(v - window, v + window + 1) if n != v and n > 0]
        if not neighbors:
            continue
        local_med = statistics.median(neighbors)
        if local_med > 0 and dist[v] / local_med >= ratio:
            spikes.append((v, dist[v], dist[v] / local_med))
        elif local_med == 0 and dist[v] > 50:
            spikes.append((v, dist[v], float("inf")))
    return sorted(spikes, key=lambda x: -x[2])


def t_key(path):
    import re
    m = re.search(r"_T(\d+)", str(path))
    return int(m.group(1)) if m else 0


def main():
    print("Loading DBC...")
    db = cantools.database.load_file(DBC_PATH)

    sessions = []
    full_charge = os.path.join(LOGS_ROOT, "full-charge-then-fail.log")
    if os.path.exists(full_charge):
        sessions.append(("full_charge_then_fail", [full_charge]))

    swap_groups = group_files_by_session(Path(SWAP_ROOT))
    for gname, files in sorted(swap_groups.items()):
        sessions.append((f"after_swap_{gname}", files))

    charge_files = sorted(Path(LOGS_ROOT).glob("vtrux_charge_M1_T*.log"), key=t_key)
    if charge_files:
        sessions.append(("vtrux_charge_M1_jan25", charge_files))

    all_dists = {}
    for name, files in sessions:
        print(f"  Processing {name} ({len(files)} file(s))...")
        dist = get_cnt_distribution([str(f) for f in files])
        if dist:
            all_dists[name] = dist

    print()
    for name, dist in all_dists.items():
        total = sum(dist.values())
        spikes = find_spikes(dist)
        print(f"{'='*60}")
        print(f"Session: {name}  (total non-zero cnt frames: {total})")
        print(f"  Spikes (>{SPIKE_RATIO}x local median in +-{WINDOW} window):")
        if spikes:
            for val, cnt, ratio in spikes:
                pct = cnt / total * 100
                print(f"    cnt={val:3d}: {cnt:6d} frames ({pct:.1f}%)  ratio={ratio:.1f}x")
        else:
            print("    none found")

    print()
    print(f"{'='*60}")
    print("Cross-session spike values (appearing in 2+ sessions):")
    from collections import Counter
    spike_vals = Counter()
    session_spike_map = {}
    for name, dist in all_dists.items():
        spikes = find_spikes(dist)
        for val, cnt, ratio in spikes:
            spike_vals[val] += 1
            session_spike_map.setdefault(val, []).append((name, cnt, ratio))

    for val in sorted(v for v, c in spike_vals.items() if c >= 2):
        print(f"  cnt={val}:")
        for sname, cnt, ratio in session_spike_map[val]:
            print(f"    {sname}: {cnt} frames  ratio={ratio:.1f}x")


if __name__ == "__main__":
    main()
