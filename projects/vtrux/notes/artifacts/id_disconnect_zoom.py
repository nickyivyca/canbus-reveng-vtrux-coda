"""
Zoom into ID transitions around disconnection events.
Shows 1-second bins for specific time windows to identify exact
disconnect/reconnect timing for pump vs battery.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file
from collections import defaultdict

PT_ANCHOR = 0x051

# IDs only on main truck (not on parts truck) — candidates for pump or BMS
TARGET_IDS = {0x370, 0x400, 0x410, 0x411, 0x412, 0x420, 0x430, 0x440, 0x460, 0x506, 0x507}

# Some baseline IDs we know are always present (from VCU/other)
BASELINE_IDS = {0x051, 0x308, 0x639, 0x644}


def analyze(path):
    print(f"Analyzing: {os.path.basename(path)}")

    pt_bus = None
    # Collect frames with timestamps for target + baseline IDs
    events = []  # (timestamp, id, is_target)

    for f in parse_file(path):
        if pt_bus is None and f.arbitration_id == PT_ANCHOR:
            pt_bus = f.bus
        if pt_bus is None or f.bus != pt_bus:
            continue
        if f.arbitration_id >= 0x800:
            continue

        aid = f.arbitration_id
        if aid in TARGET_IDS or aid in BASELINE_IDS:
            events.append((f.timestamp, aid))

    if not events:
        print("No PT bus frames found")
        return

    t_min = events[0][0]
    t_max = events[-1][0]
    print(f"PT bus: {pt_bus}, Duration: {t_max - t_min:.1f}s\n")

    # Find transition windows: look for when target IDs stop/start
    # Bin everything in 1-second bins
    BIN = 1.0
    n_bins = int((t_max - t_min) / BIN) + 1

    id_bins = defaultdict(lambda: [0] * n_bins)
    for t, aid in events:
        b = min(int((t - t_min) / BIN), n_bins - 1)
        id_bins[aid][b] += 1

    # Find bins where any target ID goes from present to absent or vice versa
    transition_bins = set()
    for aid in TARGET_IDS:
        bins = id_bins[aid]
        for i in range(1, n_bins):
            if (bins[i] > 0) != (bins[i-1] > 0):
                # Add surrounding bins for context
                for j in range(max(0, i-3), min(n_bins, i+4)):
                    transition_bins.add(j)

    if not transition_bins:
        print("No transitions detected for target IDs")
        return

    # Group consecutive transition bins into windows
    sorted_bins = sorted(transition_bins)
    windows = []
    start = sorted_bins[0]
    prev = sorted_bins[0]
    for b in sorted_bins[1:]:
        if b - prev > 2:
            windows.append((start, prev))
            start = b
        prev = b
    windows.append((start, prev))

    # Print each window
    all_ids = sorted(TARGET_IDS | BASELINE_IDS)
    for w_start, w_end in windows:
        t_start = t_min + w_start * BIN
        t_end = t_min + (w_end + 1) * BIN
        print(f"\n=== Window: t={t_start:.0f}s - {t_end:.0f}s ===\n")

        hdr = f"{'ID':>8}  "
        for i in range(w_start, w_end + 1):
            t_s = t_min + i * BIN
            hdr += f"{t_s:6.0f}"
        print(hdr)
        print(f"{'-'*8}  " + "-" * (6 * (w_end - w_start + 1)))

        for aid in all_ids:
            row = f"  0x{aid:03X}  "
            bins = id_bins[aid]
            for i in range(w_start, w_end + 1):
                c = bins[i]
                if c == 0:
                    row += "     ."
                else:
                    row += f"{c:6d}"
            # Mark if target or baseline
            label = "  [TARGET]" if aid in TARGET_IDS else "  [baseline]"
            print(row + label)


if __name__ == "__main__":
    log = sys.argv[1] if len(sys.argv) > 1 else None
    if not log:
        print("Usage: python id_disconnect_zoom.py <log_file>")
        sys.exit(1)
    analyze(log)
