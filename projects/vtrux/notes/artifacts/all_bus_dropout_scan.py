"""
Scan ALL buses for any ID that drops out during the capture.
1-second bins across the full log, flag any ID whose count drops
to zero for 3+ consecutive seconds after being consistently present.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file
from collections import defaultdict

LOGS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')


def analyze(path):
    print(f"Analyzing: {os.path.basename(path)}\n")

    # Collect all frames grouped by bus
    bus_frames = defaultdict(list)  # bus -> [(t, id)]

    for f in parse_file(path):
        bus_frames[f.bus].append((f.timestamp, f.arbitration_id))

    for bus in sorted(bus_frames.keys()):
        frames = bus_frames[bus]
        t_min = frames[0][0]
        t_max = frames[-1][0]
        dur = t_max - t_min

        BIN = 1.0
        n_bins = int(dur / BIN) + 1

        # Count per (id, bin)
        id_bins = defaultdict(lambda: [0] * n_bins)
        all_ids = set()
        for t, aid in frames:
            b = min(int((t - t_min) / BIN), n_bins - 1)
            id_bins[aid][b] += 1
            all_ids.add(aid)

        print(f"{'='*70}")
        print(f"  Bus {bus}: {len(all_ids)} IDs, {len(frames)} frames, {dur:.1f}s")
        print(f"{'='*70}")

        # For each ID, find dropout events:
        # ID was present (>0) for 3+ consecutive seconds, then absent (0) for 3+ seconds
        dropouts = []
        for aid in sorted(all_ids):
            bins = id_bins[aid]
            # Find runs of present/absent
            i = 0
            while i < n_bins:
                # Find a run of "present" (at least 3 consecutive bins with count > 0)
                run_start = i
                while i < n_bins and bins[i] > 0:
                    i += 1
                present_end = i  # first absent bin
                present_len = present_end - run_start

                # Find run of "absent"
                absent_start = i
                while i < n_bins and bins[i] == 0:
                    i += 1
                absent_end = i
                absent_len = absent_end - absent_start

                if present_len >= 3 and absent_len >= 3:
                    t_dropout = t_min + present_end * BIN
                    # Check: does the ID come back later?
                    comes_back = any(bins[j] > 0 for j in range(absent_end, n_bins))
                    avg_rate = sum(bins[run_start:present_end]) / present_len
                    dropouts.append((t_dropout, aid, avg_rate, absent_len, comes_back))

        if not dropouts:
            print("  No dropout events detected.\n")
            continue

        dropouts.sort(key=lambda r: r[0])

        print(f"\n  {'Dropout t':>10}  {'ID':>12}  {'Avg rate':>8}  {'Gap(s)':>6}  Returns?")
        print(f"  {'-'*10}  {'-'*12}  {'-'*8}  {'-'*6}  {'-'*8}")

        for t_drop, aid, avg, gap, returns in dropouts:
            ret = "YES" if returns else "no"
            if aid >= 0x800:
                id_str = f"0x{aid:08X}"
            else:
                id_str = f"0x{aid:03X}"
            print(f"  {t_drop:10.1f}  {id_str:>12}  {avg:8.1f}  {gap:6d}  {ret}")

        print()


if __name__ == "__main__":
    analyze(os.path.join(LOGS_DIR, "vtruxunplugpumpthenhvbatterylvconnector.log"))
