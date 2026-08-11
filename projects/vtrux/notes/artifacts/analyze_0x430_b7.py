"""
Analyze 0x430 B7 (and all bytes) for validity/transition bits.
Focus on start/end of log vs steady-state middle.

Usage: py -3.12 projects/vtrux/notes/artifacts/analyze_0x430_b7.py <log_file> [--bus <bus_num>]
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))
from canre.parsers import parse_file

def run(log_path, bus_filter=None):
    frames = list(parse_file(log_path))

    # Collect 0x430 frames, optionally filter by bus
    target = [f for f in frames if f.arbitration_id == 0x430]
    if bus_filter is not None:
        target = [f for f in target if f.channel == bus_filter]

    if not target:
        # Show what buses have 0x430
        buses = set(f.channel for f in frames if f.arbitration_id == 0x430)
        if buses:
            print(f"0x430 found on buses: {buses}. Re-run with --bus <n>")
        else:
            print("0x430 not found in this log.")
        return

    print(f"0x430 frames: {len(target)} (bus filter={bus_filter})")
    print()

    # --- Full-log B7 bit-level transition analysis ---
    print("=== B7 bit transition rates (all 8 bits) ===")
    print(f"{'Bit':>4}  {'Toggles':>8}  {'Rate(Hz)':>9}  {'0->1':>6}  {'1->0':>6}  {'Sample values (first 5)'}")

    duration = target[-1].timestamp - target[0].timestamp
    for bit in range(8):
        vals = [(f.data[7] >> bit) & 1 for f in target]
        toggles = sum(1 for a, b in zip(vals, vals[1:]) if a != b)
        rate = toggles / duration if duration > 0 else 0
        up = sum(1 for a, b in zip(vals, vals[1:]) if a == 0 and b == 1)
        down = sum(1 for a, b in zip(vals, vals[1:]) if a == 1 and b == 0)
        sample = vals[:5]
        print(f"  {bit:>2}  {toggles:>8}  {rate:>9.3f}  {up:>6}  {down:>6}  {sample}")

    print()

    # --- Look at all 8 bytes for startup/shutdown transitions ---
    # Show the first N and last N frames in full hex
    N = 20
    print(f"=== First {N} frames ===")
    print(f"{'t(s)':>8}  B0   B1   B2   B3   B4   B5   B6   B7   | B7bin     | V_max(mV)  V_min(mV)")
    t0 = target[0].timestamp
    for f in target[:N]:
        d = f.data
        vmax = (d[0] & 0x0F) * 256 + d[1]
        vmin = (d[2] & 0x0F) * 256 + d[3]
        b7bin = f"{d[7]:08b}"
        print(f"{f.timestamp - t0:>8.3f}  {d[0]:02X}   {d[1]:02X}   {d[2]:02X}   {d[3]:02X}   "
              f"{d[4]:02X}   {d[5]:02X}   {d[6]:02X}   {d[7]:02X}   | {b7bin} | {vmax:>10}  {vmin:>10}")

    print()
    print(f"=== Last {N} frames ===")
    for f in target[-N:]:
        d = f.data
        vmax = (d[0] & 0x0F) * 256 + d[1]
        vmin = (d[2] & 0x0F) * 256 + d[3]
        b7bin = f"{d[7]:08b}"
        print(f"{f.timestamp - t0:>8.3f}  {d[0]:02X}   {d[1]:02X}   {d[2]:02X}   {d[3]:02X}   "
              f"{d[4]:02X}   {d[5]:02X}   {d[6]:02X}   {d[7]:02X}   | {b7bin} | {vmax:>10}  {vmin:>10}")

    print()

    # --- Find any bit in B7 that changes state only a few times (< 10) ---
    print("=== B7 bits with few transitions (possible state/validity bits) ===")
    b7_vals = [f.data[7] for f in target]
    for bit in range(8):
        vals = [(v >> bit) & 1 for v in b7_vals]
        toggles = sum(1 for a, b in zip(vals, vals[1:]) if a != b)
        if toggles < 20:
            # Find transition indices
            transitions = [(i+1, vals[i], vals[i+1], target[i+1].timestamp - t0)
                           for i, (a, b) in enumerate(zip(vals, vals[1:])) if a != b]
            print(f"  Bit {bit}: {toggles} toggles; initial={vals[0]}, final={vals[-1]}")
            for idx, old, new, ts in transitions:
                print(f"    t={ts:.3f}s: {old}->{new} (frame {idx})")

    print()

    # --- Scan ALL bytes for bits with very few transitions ---
    print("=== Any byte/bit with <= 5 transitions across whole log ===")
    found_any = False
    for byte_idx in range(min(8, len(target[0].data))):
        for bit in range(8):
            vals = [(f.data[byte_idx] >> bit) & 1 for f in target]
            toggles = sum(1 for a, b in zip(vals, vals[1:]) if a != b)
            if toggles <= 5:
                transitions = [(i+1, vals[i], vals[i+1], target[i+1].timestamp - t0)
                               for i, (a, b) in enumerate(zip(vals, vals[1:])) if a != b]
                print(f"  B{byte_idx} bit{bit}: {toggles} toggles; init={vals[0]}, final={vals[-1]}, "
                      f"byte values={set(f.data[byte_idx] for f in target)}")
                for idx, old, new, ts in transitions:
                    print(f"    t={ts:.3f}s: {old}->{new}")
                found_any = True
    if not found_any:
        print("  (none with <= 5 transitions)")

    print()

    # --- Show unique B7 values and their count ---
    from collections import Counter
    b7_counts = Counter(b7_vals)
    print("=== B7 unique values (sorted) ===")
    for val, cnt in sorted(b7_counts.items()):
        print(f"  0x{val:02X} ({val:3d}) = {val:08b}b : {cnt:6d} frames")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: py -3.12 analyze_0x430_b7.py <log_file> [--bus <n>]")
        sys.exit(1)

    log_path = sys.argv[1]
    bus_filter = None
    if '--bus' in sys.argv:
        bus_filter = int(sys.argv[sys.argv.index('--bus') + 1])

    run(log_path, bus_filter)
