"""
Compare PT bus ID inventories between two logs to identify
which IDs require specific hardware (BMS, pump, etc.)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file
from collections import defaultdict

PT_ANCHOR = 0x051
LOGS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')


def get_pt_ids(path, label):
    """Get standard-frame ID set and stats on PT bus."""
    pt_bus = None
    id_stats = {}  # id -> (count, first, last)

    for f in parse_file(path):
        if pt_bus is None and f.arbitration_id == PT_ANCHOR:
            pt_bus = f.bus
        if pt_bus is None or f.bus != pt_bus:
            continue
        if f.arbitration_id >= 0x800:
            continue
        aid = f.arbitration_id
        if aid not in id_stats:
            id_stats[aid] = [1, f.timestamp, f.timestamp]
        else:
            id_stats[aid][0] += 1
            id_stats[aid][2] = f.timestamp

    t_min = min(s[1] for s in id_stats.values()) if id_stats else 0
    t_max = max(s[2] for s in id_stats.values()) if id_stats else 0
    dur = t_max - t_min if t_max > t_min else 1

    result = {}
    for aid, (count, first, last) in id_stats.items():
        result[aid] = count / dur
    return result, pt_bus, dur


def main():
    parts = os.path.join(LOGS_DIR, "vtruxpartstruck.log")
    main_truck = os.path.join(LOGS_DIR, "vtruxunplugpumpthenhvbatterylvconnector.log")

    print("PT BUS ID COMPARISON")
    print("Parts truck: no HV battery, no PE pump on CAN")
    print("Main truck: full system (with disconnect events during capture)\n")

    parts_ids, parts_bus, parts_dur = get_pt_ids(parts, "Parts")
    main_ids, main_bus, main_dur = get_pt_ids(main_truck, "Main")

    print(f"Parts truck: bus={parts_bus}, {len(parts_ids)} IDs, {parts_dur:.1f}s")
    print(f"Main truck:  bus={main_bus}, {len(main_ids)} IDs, {main_dur:.1f}s\n")

    common = sorted(set(parts_ids) & set(main_ids))
    parts_only = sorted(set(parts_ids) - set(main_ids))
    main_only = sorted(set(main_ids) - set(parts_ids))

    print(f"{'='*60}")
    print(f"IDs ONLY ON MAIN TRUCK ({len(main_only)}) — require HV battery or pump")
    print(f"{'='*60}")
    print(f"  {'ID':>8}  {'Freq':>8}")
    for aid in main_only:
        print(f"  0x{aid:03X}  {main_ids[aid]:8.1f} Hz")

    print(f"\n{'='*60}")
    print(f"IDs ONLY ON PARTS TRUCK ({len(parts_only)}) — may be VCU-only or diagnostic")
    print(f"{'='*60}")
    print(f"  {'ID':>8}  {'Freq':>8}")
    for aid in parts_only:
        print(f"  0x{aid:03X}  {parts_ids[aid]:8.1f} Hz")

    print(f"\n{'='*60}")
    print(f"COMMON IDs ({len(common)}) — present on both (VCU / body / always-on)")
    print(f"{'='*60}")
    print(f"  {'ID':>8}  {'Parts':>8}  {'Main':>8}  {'Ratio':>8}")
    for aid in common:
        pf = parts_ids[aid]
        mf = main_ids[aid]
        ratio = mf / pf if pf > 0 else float('inf')
        note = ""
        if ratio > 1.5:
            note = "  << higher on main"
        elif ratio < 0.67:
            note = "  << lower on main"
        print(f"  0x{aid:03X}  {pf:8.1f}  {mf:8.1f}  {ratio:8.2f}{note}")


if __name__ == "__main__":
    main()
