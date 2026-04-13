"""
balancing_cnt_completed_charges.py

Report bcm_balancing_cnt across all Vtrux charge sessions that reached 100% SOC.

Signals:
  bcm_soc           0x410 B3, scale=0.5 %, 100% = raw 200, invalid if raw>=0xFE
  bcm_balancing_cnt 0x440 B7, raw integer count, invalid if raw>=0xFE

Usage:
  py -3.12 projects/vtrux/notes/artifacts/balancing_cnt_completed_charges.py
"""

import os
import sys
import collections

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from pathlib import Path
from canre.utils.merge import merge_files
from canre.utils.sessions import group_files_by_session

LOGS_ROOT = os.path.join(PROJECT_ROOT, "projects", "vtrux", "logs")
SWAP_ROOT = os.path.join(LOGS_ROOT, "after-battery-swap-charges")

PT_BUS_ANCHOR_IDS = {0x410, 0x420, 0x430, 0x440, 0x471}


# --------------------------------------------------------------------------- #
# PT bus identification (first pass, single file)
# --------------------------------------------------------------------------- #

def identify_pt_bus_from_frames(frames_iter, sample_limit=200000):
    """
    Consume up to sample_limit frames to find the bus channel carrying PT IDs.
    Returns (pt_bus_int, list_of_remaining_frames) -- but since we need to
    re-scan, callers should pass file paths and call merge_files twice.
    Returns the bus int or None.
    """
    counts = {}
    for i, frame in enumerate(frames_iter):
        if frame.arbitration_id in PT_BUS_ANCHOR_IDS:
            counts[frame.bus] = counts.get(frame.bus, 0) + 1
        if i >= sample_limit:
            break
    return max(counts, key=counts.get) if counts else None


# --------------------------------------------------------------------------- #
# Session processor
# --------------------------------------------------------------------------- #

def process_session(name, files):
    """
    Process an ordered list of log files using merge_files.
    Returns a stats dict or None if PT bus not found / no SOC data.
    """
    if not files:
        return None

    file_paths = [str(f) for f in files]

    # First pass: identify PT bus channel
    pt_bus = identify_pt_bus_from_frames(merge_files(file_paths))
    if pt_bus is None:
        print(f"  [{name}] Could not identify PT bus, skipping.")
        return None

    # Second pass: extract signals
    soc_samples = []   # (abs_time, soc_pct)
    cnt_samples = []   # (abs_time, cnt)

    for frame in merge_files(file_paths):
        if frame.bus != pt_bus:
            continue

        t = frame.timestamp

        if frame.arbitration_id == 0x410 and len(frame.data) >= 4:
            raw_soc = frame.data[3]
            if raw_soc < 0xFE:
                soc_samples.append((t, raw_soc * 0.5))

        elif frame.arbitration_id == 0x440 and len(frame.data) >= 8:
            raw_cnt = frame.data[7]
            if raw_cnt < 0xFE:
                cnt_samples.append((t, raw_cnt))

    if not soc_samples:
        print(f"  [{name}] No valid bcm_soc frames found, skipping.")
        return None

    soc_vals = [s for _, s in soc_samples]
    max_soc  = max(soc_vals)

    return {
        "name":        name,
        "files":       len(files),
        "duration_s":  soc_samples[-1][0] - soc_samples[0][0] if len(soc_samples) > 1 else 0,
        "soc_min":     min(soc_vals),
        "soc_max":     max_soc,
        "reached_100": max_soc >= 100.0,
        "soc_samples": soc_samples,
        "cnt_samples": cnt_samples,
        "cnt_vals":    [c for _, c in cnt_samples],
        "pt_bus":      pt_bus,
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def report_session(s):
    name  = s["name"]
    dur_m = s["duration_s"] / 60.0
    print(f"\n{'='*60}")
    print(f"Session: {name}")
    print(f"  Files: {s['files']}  |  Duration: {dur_m:.1f} min  |  PT bus: {s['pt_bus']}")
    print(f"  SOC range: {s['soc_min']:.1f}% -> {s['soc_max']:.1f}%")
    if not s["reached_100"]:
        print("  *** Did NOT reach 100% SOC ***")
        return

    cnt_vals = s["cnt_vals"]
    if not cnt_vals:
        print("  No valid bcm_balancing_cnt frames found.")
        return

    cnt_min  = min(cnt_vals)
    cnt_max  = max(cnt_vals)
    cnt_mean = sum(cnt_vals) / len(cnt_vals)
    dist     = collections.Counter(cnt_vals)

    print(f"  bcm_balancing_cnt: min={cnt_min}  max={cnt_max}  mean={cnt_mean:.1f}  n={len(cnt_vals)}")
    print(f"  Value distribution (value -> frame count / pct):")
    for val in sorted(dist):
        pct = dist[val] / len(cnt_vals) * 100
        print(f"    {val:3d}: {dist[val]:6d}  ({pct:.1f}%)")

    t0 = s["soc_samples"][0][0]

    nonzero = [(t, c) for t, c in s["cnt_samples"] if c > 0]
    if nonzero:
        first_t, first_c = nonzero[0]
        last_t,  last_c  = nonzero[-1]
        print(f"  First non-zero: t+{first_t - t0:.1f}s  val={first_c}")
        print(f"  Last  non-zero: t+{last_t  - t0:.1f}s  val={last_c}")

        # SOC at first non-zero
        nearest_soc = min(s["soc_samples"], key=lambda x: abs(x[0] - first_t))
        print(f"  SOC at first non-zero balancing_cnt: ~{nearest_soc[1]:.1f}%")
    else:
        print("  No non-zero bcm_balancing_cnt values observed.")

    # Coarse timeline: 10-min buckets
    if s["duration_s"] > 600:
        print(f"  Timeline (10-min buckets):")
        soc_dict = {}
        for t, v in s["soc_samples"]:
            bucket = int((t - t0) / 600)
            soc_dict.setdefault(bucket, []).append(v)
        cnt_dict = {}
        for t, v in s["cnt_samples"]:
            bucket = int((t - t0) / 600)
            cnt_dict.setdefault(bucket, []).append(v)
        all_buckets = sorted(set(list(soc_dict) + list(cnt_dict)))
        for b in all_buckets:
            sv = soc_dict.get(b, [])
            cv = cnt_dict.get(b, [])
            avg_soc = sum(sv)/len(sv) if sv else float("nan")
            avg_cnt = sum(cv)/len(cv) if cv else float("nan")
            max_cnt = max(cv) if cv else float("nan")
            print(f"    t+{b*10:3d}min: SOC~{avg_soc:5.1f}%  cnt_mean={avg_cnt:5.1f}  cnt_max={max_cnt}")


# --------------------------------------------------------------------------- #
# Session discovery
# --------------------------------------------------------------------------- #

def main():
    sessions = []

    # 1. full charge then fail (single file, standalone)
    full_charge = os.path.join(LOGS_ROOT, "full charge then fail.log")
    if os.path.exists(full_charge):
        sessions.append(("full_charge_then_fail", [full_charge]))

    # 2+3. After battery swap folder — use session grouping
    swap_groups = group_files_by_session(Path(SWAP_ROOT))
    for gname, files in sorted(swap_groups.items()):
        sessions.append((f"after_swap_{gname}", files))

    print(f"Sessions found: {[s[0] for s in sessions]}")
    print("Processing (two passes per session for PT bus detection)...\n")

    completed = []
    skipped   = []

    for name, files in sessions:
        print(f"  {name} ({len(files)} file(s))...")
        s = process_session(name, files)
        if s is None:
            skipped.append(name)
        elif s["reached_100"]:
            completed.append(s)
        else:
            skipped.append(f"{name} (max SOC={s['soc_max']:.1f}%)")

    print(f"\n{'#'*60}")
    print(f"SUMMARY: {len(completed)} session(s) reached 100% SOC")
    print(f"{'#'*60}")

    for s in completed:
        report_session(s)

    if skipped:
        print(f"\nSkipped (did not reach 100% or no data):")
        for sk in skipped:
            print(f"  {sk}")


if __name__ == "__main__":
    main()
