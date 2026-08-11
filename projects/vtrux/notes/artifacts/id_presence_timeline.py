"""
Track when each ID on the PT bus first/last appears in a log.
Used to identify which IDs disappear when components are disconnected.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file

PT_ANCHOR = 0x051

def analyze(path):
    print(f"Analyzing: {os.path.basename(path)}\n")

    pt_bus = None
    # For each ID: (first_seen, last_seen, count)
    id_stats = {}

    for f in parse_file(path):
        if pt_bus is None and f.arbitration_id == PT_ANCHOR:
            pt_bus = f.bus
        if pt_bus is None or f.bus != pt_bus:
            continue
        if f.arbitration_id >= 0x800:
            continue

        aid = f.arbitration_id
        if aid not in id_stats:
            id_stats[aid] = [f.timestamp, f.timestamp, 1]
        else:
            id_stats[aid][1] = f.timestamp
            id_stats[aid][2] += 1

    if not id_stats:
        print("No PT bus frames found")
        return

    # Find log time range
    t_min = min(s[0] for s in id_stats.values())
    t_max = max(s[1] for s in id_stats.values())
    print(f"PT bus: {pt_bus}, Log duration: {t_max - t_min:.1f}s")
    print(f"Standard-frame IDs: {len(id_stats)}\n")

    # Sort by last_seen to find disconnection clusters
    by_last = sorted(id_stats.items(), key=lambda x: x[1][1])

    print(f"{'ID':>8}  {'First':>8}  {'Last':>8}  {'Count':>7}  {'Freq':>6}  Note")
    print(f"{'-'*8}  {'-'*8}  {'-'*8}  {'-'*7}  {'-'*6}  {'-'*20}")

    prev_last = None
    for aid, (first, last, count) in by_last:
        dur = last - first if last > first else 1
        freq = count / dur if dur > 0 else count
        gap_marker = ""
        if prev_last is not None and (last - prev_last) > 2.0:
            print(f"  --- gap: {last - prev_last:.1f}s ---")
        prev_last = last

        # Mark IDs that don't span the full log
        if (last - t_min) < (t_max - t_min) * 0.8:
            gap_marker = f"STOPS @ {last:.1f}s"
        elif (first - t_min) > (t_max - t_min) * 0.2:
            gap_marker = f"STARTS @ {first:.1f}s"

        print(f"  0x{aid:03X}  {first:8.1f}  {last:8.1f}  {count:7d}  {freq:6.1f}  {gap_marker}")


if __name__ == "__main__":
    log = sys.argv[1] if len(sys.argv) > 1 else None
    if not log:
        print("Usage: python id_presence_timeline.py <log_file>")
        sys.exit(1)
    analyze(log)
