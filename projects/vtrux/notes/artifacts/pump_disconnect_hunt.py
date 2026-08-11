"""
Hunt for the pump disconnect event. Look at ALL PT bus IDs in 1-second
bins from t=50 to t=90, looking for any ID that drops or changes
before the big battery dropout at t=75.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file
from collections import defaultdict

PT_ANCHOR = 0x051


def analyze(path):
    print(f"Analyzing: {os.path.basename(path)}\n")

    pt_bus = None
    # Collect all frames on PT bus with timestamps
    frames = []

    for f in parse_file(path):
        if pt_bus is None and f.arbitration_id == PT_ANCHOR:
            pt_bus = f.bus
        if pt_bus is None or f.bus != pt_bus:
            continue
        frames.append((f.timestamp, f.arbitration_id, f.data))

    if not frames:
        print("No PT bus frames found")
        return

    t_min = frames[0][0]
    t_max = frames[-1][0]
    print(f"PT bus: {pt_bus}, Duration: {t_max - t_min:.1f}s")

    # 1-second bins from t=50 to t=90
    BIN = 1.0
    T_START = 50.0
    T_END = 90.0

    n_bins = int((T_END - T_START) / BIN)
    id_bins = defaultdict(lambda: [0] * n_bins)

    for t, aid, data in frames:
        if t < T_START or t >= T_END:
            continue
        b = int((t - T_START) / BIN)
        if 0 <= b < n_bins:
            id_bins[aid][b] += 1

    # Find IDs where the count changes significantly (drops or appears)
    # Compare bins 0-20 (t=50-70, "before") vs bins 20-30 (t=70-80, "transition")
    print(f"\nLooking for IDs that change between t=50-70 (before) and t=70-80 (transition)...\n")

    results = []
    for aid in sorted(id_bins.keys()):
        bins = id_bins[aid]
        # Average count in "before" period (t=50-70)
        before_bins = bins[0:20]
        before_avg = sum(before_bins) / len(before_bins) if before_bins else 0
        # Check each bin in t=70-80 for significant change
        for i in range(20, min(30, n_bins)):
            t_bin = T_START + i * BIN
            count = bins[i]
            if before_avg > 0.5 and count < before_avg * 0.5:
                results.append((aid, t_bin, before_avg, count, "DROP"))
                break
            elif before_avg < 0.5 and count > 1:
                results.append((aid, t_bin, before_avg, count, "APPEAR"))
                break

    # Sort by time of change
    results.sort(key=lambda r: (r[1], r[0]))

    print(f"{'ID':>8}  {'Change at':>10}  {'Avg before':>10}  {'Count at':>10}  {'Type':>8}")
    print(f"{'-'*8}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*8}")
    for aid, t, avg, count, typ in results:
        ext = "X" if aid >= 0x800 else ""
        if aid >= 0x800:
            print(f"  0x{aid:08X}  {t:10.0f}  {avg:10.1f}  {count:10d}  {typ:>8}")
        else:
            print(f"  0x{aid:03X}       {t:10.0f}  {avg:10.1f}  {count:10d}  {typ:>8}")

    # Now show ALL IDs in 1-second bins from t=60 to t=90 for the ones that changed
    changed_ids = {r[0] for r in results}
    # Also add some always-on baselines for reference
    changed_ids.update({0x051, 0x639, 0x644})

    print(f"\n\n=== Detailed 1-second bins: t=60-90s ===")
    print(f"{'ID':>12}  ", end="")
    for i in range(30):
        t = 60 + i
        print(f"{t:4d}", end="")
    print()
    print(f"{'-'*12}  " + "-" * (4 * 30))

    for aid in sorted(changed_ids):
        bins_full = id_bins[aid]
        if aid >= 0x800:
            row = f"  0x{aid:08X}  "
        else:
            row = f"       0x{aid:03X}  "
        for i in range(30):  # t=60 to t=89
            idx = int((60 - T_START) / BIN) + i
            if 0 <= idx < n_bins:
                c = bins_full[idx]
                if c == 0:
                    row += "   ."
                else:
                    row += f"{c:4d}"
            else:
                row += "   ?"
        print(row)


if __name__ == "__main__":
    analyze(os.path.join(os.path.dirname(__file__), '..', '..', 'logs',
            'vtruxunplugpumpthenhvbatterylvconnector.log'))
