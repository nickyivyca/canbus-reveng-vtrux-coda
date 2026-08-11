"""
Show ID presence on PT bus in time bins.
Helps identify when components are disconnected/reconnected.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file

PT_ANCHOR = 0x051
BIN_SIZE = 5.0  # seconds per bin


def analyze(path):
    print(f"Analyzing: {os.path.basename(path)}")

    pt_bus = None
    # Collect (timestamp, id) for each PT bus standard frame
    frames = []

    for f in parse_file(path):
        if pt_bus is None and f.arbitration_id == PT_ANCHOR:
            pt_bus = f.bus
        if pt_bus is None or f.bus != pt_bus:
            continue
        if f.arbitration_id >= 0x800:
            continue
        frames.append((f.timestamp, f.arbitration_id))

    if not frames:
        print("No PT bus frames found")
        return

    t_min = frames[0][0]
    t_max = frames[-1][0]
    n_bins = int((t_max - t_min) / BIN_SIZE) + 1
    print(f"PT bus: {pt_bus}, Duration: {t_max - t_min:.1f}s, Bins: {n_bins} x {BIN_SIZE}s\n")

    # Count frames per (id, bin)
    all_ids = sorted(set(aid for _, aid in frames))
    id_bins = {aid: [0] * n_bins for aid in all_ids}
    for t, aid in frames:
        b = min(int((t - t_min) / BIN_SIZE), n_bins - 1)
        id_bins[aid][b] += 1

    # Find IDs that are NOT present in all bins (these are the interesting ones)
    always_on = []
    variable = []
    for aid in all_ids:
        bins = id_bins[aid]
        if all(c > 0 for c in bins):
            always_on.append(aid)
        else:
            variable.append(aid)

    # Print bin headers
    bin_labels = [f"{t_min + i * BIN_SIZE:.0f}" for i in range(n_bins)]

    print(f"=== IDs with gaps (present in some bins, absent in others): {len(variable)} ===\n")
    # Header: show time of each bin
    hdr = f"{'ID':>8}  "
    for i in range(n_bins):
        t_s = t_min + i * BIN_SIZE
        hdr += f"{t_s:5.0f}"
    print(hdr)
    print(f"{'-'*8}  " + "-" * (5 * n_bins))

    for aid in variable:
        row = f"  0x{aid:03X}  "
        for c in id_bins[aid]:
            if c == 0:
                row += "    ."
            else:
                row += f"{c:5d}"
        print(row)

    print(f"\n=== IDs always present (in every {BIN_SIZE}s bin): {len(always_on)} ===")
    for aid in always_on:
        total = sum(id_bins[aid])
        freq = total / (t_max - t_min)
        print(f"  0x{aid:03X}  total={total:6d}  freq={freq:.1f}Hz")


if __name__ == "__main__":
    log = sys.argv[1] if len(sys.argv) > 1 else None
    if not log:
        print("Usage: python id_presence_bins.py <log_file>")
        sys.exit(1)
    analyze(log)
