"""
Check shutdown cascade ordering across multiple logs.
Single-pass streaming: tracks 0x410 B0 transitions and records the first
change of 0x400, 0x644, 0x600, 0x411 relative to each 0x410 event.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file

LOGS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')

NORMAL_LOGS = [
    "generator on then off.log",
    "movingaroundindriveway.log",
    "rainychargedebug.log",
    "rainychargedebug2.log",
]

FAULT_LOGS = [
    "vtruxinterlocktest.log",
]

# IDs to track around shutdown events
TRACK_IDS = {0x410, 0x400, 0x644, 0x600, 0x411}
PT_ANCHOR = 0x051

# Active states for 0x410 B0 that indicate an operational truck
ACTIVE_STATES = {0x19, 0x4D, 0x0D, 0x09}


def analyze_log(path, label):
    print(f"\n{'='*70}")
    print(f"  {label}: {os.path.basename(path)}")
    print(f"{'='*70}")

    # Phase 1: find PT bus + identify all 0x410 B0 transitions + track
    # other IDs' byte values over time
    pt_bus = None
    n_frames = 0
    t_first = None
    t_last = None

    # Track last known byte values for each (id, byte_index) on PT bus
    prev_bytes = {}  # (id, bi) -> value
    # Track 0x410 B0 transitions
    shutdown_events = []  # (t, old_b0, new_b0)
    # For each ID, track all byte-level transitions with timestamps
    all_transitions = []  # (t, id, bi, old, new)

    for f in parse_file(path):
        n_frames += 1
        if t_first is None:
            t_first = f.timestamp
        t_last = f.timestamp

        # Find PT bus from anchor
        if pt_bus is None and f.arbitration_id == PT_ANCHOR:
            pt_bus = f.bus

        if pt_bus is None or f.bus != pt_bus:
            continue
        if f.arbitration_id not in TRACK_IDS:
            continue

        for bi in range(min(len(f.data), 8)):
            key = (f.arbitration_id, bi)
            bval = f.data[bi]
            prev = prev_bytes.get(key)
            if prev is not None and prev != bval:
                all_transitions.append((f.timestamp, f.arbitration_id, bi, prev, bval))
                # Detect 0x410 B0 shutdown-relevant transitions
                if f.arbitration_id == 0x410 and bi == 0 and prev in ACTIVE_STATES:
                    shutdown_events.append((f.timestamp, prev, bval))
            prev_bytes[key] = bval

    if pt_bus is None:
        print("  (powertrain bus not found)")
        return
    duration = (t_last - t_first) if t_first and t_last else 0
    print(f"  Powertrain bus: {pt_bus}, Frames: {n_frames}, Duration: {duration:.1f}s")

    if not shutdown_events:
        print("  (no shutdown events found)")
        return

    print(f"  Shutdown events: {len(shutdown_events)}")

    # Phase 2: for each shutdown event, find nearby transitions
    for ev_i, (t_ev, old_b0, new_b0) in enumerate(shutdown_events):
        print(f"\n  --- Event {ev_i+1}: t={t_ev:.3f}s, 0x410 B0: 0x{old_b0:02X}->0x{new_b0:02X} ---")

        # Collect transitions in [-2, +2] window, keep only first per (id, byte)
        first_by_key = {}
        for (t, aid, bi, old, new) in all_transitions:
            dt = t - t_ev
            if -2.0 <= dt <= 2.0:
                key = (aid, bi)
                if key not in first_by_key or abs(dt) < abs(first_by_key[key][0]):
                    first_by_key[key] = (dt, old, new)

        rows = []
        for (aid, bi), (dt, old, new) in first_by_key.items():
            rows.append((dt, aid, bi, old, new))
        rows.sort(key=lambda r: r[0])

        print(f"  {'dt':>8}  {'ID':>6}  {'Byte':>4}  {'Old':>5}  {'New':>5}  Note")
        print(f"  {'-'*8}  {'-'*6}  {'-'*4}  {'-'*5}  {'-'*5}  {'-'*30}")

        for dt, aid, bi, old, new in rows:
            marker = ""
            if aid == 0x410 and bi == 0:
                marker = "<<< 0x410 B0 (interlock/mode) >>>"
            elif aid == 0x410 and bi == 1:
                if (new & 0x40) and not (old & 0x40):
                    marker = "0x410 B1 — FAULT FLAG (bit6) SET"
                else:
                    marker = "0x410 B1 — clean (no fault flag)"
            elif aid == 0x410:
                marker = f"0x410 B{bi}"
            elif aid == 0x400:
                marker = f"0x400 B{bi} (HV system status)"
            elif aid == 0x644:
                marker = f"0x644 B{bi} (BMS cluster)"
            elif aid == 0x600:
                marker = f"0x600 B{bi} (BMS/charger)"
            elif aid == 0x411:
                marker = f"0x411 B{bi} (contactor-related)"

            print(f"  {dt:+8.3f}  0x{aid:03X}  B{bi}    0x{old:02X}  0x{new:02X}  {marker}")

        # Summary: order check
        t410 = first_by_key.get((0x410, 0), (0,))[0]
        t400 = first_by_key.get((0x400, 0))
        t644_0 = first_by_key.get((0x644, 0))
        t644_1 = first_by_key.get((0x644, 1))

        print(f"\n  ORDER SUMMARY (relative to 0x410 B0 @ dt=0):")
        if t400:
            order = "BEFORE" if t400[0] < t410 else "AFTER"
            print(f"    0x400 B0: dt={t400[0]:+.3f} ({order}) val 0x{t400[1]:02X}->0x{t400[2]:02X}")
        if t644_0:
            order = "BEFORE" if t644_0[0] < t410 else "AFTER"
            print(f"    0x644 B0: dt={t644_0[0]:+.3f} ({order}) val 0x{t644_0[1]:02X}->0x{t644_0[2]:02X}")
        if t644_1:
            order = "BEFORE" if t644_1[0] < t410 else "AFTER"
            print(f"    0x644 B1: dt={t644_1[0]:+.3f} ({order}) val 0x{t644_1[1]:02X}->0x{t644_1[2]:02X}")


def main():
    print("SHUTDOWN PRECURSOR VALIDATION")
    print("Checking cascade ordering: 0x400, 0x644, 0x600, 0x411 vs 0x410")

    for name in NORMAL_LOGS:
        path = os.path.join(LOGS_DIR, name)
        if os.path.exists(path):
            analyze_log(path, "NORMAL KEY-OFF")
        else:
            print(f"\n  SKIP: {name} (not found/cached)")

    for name in FAULT_LOGS:
        path = os.path.join(LOGS_DIR, name)
        if os.path.exists(path):
            analyze_log(path, "FAULT EVENT")
        else:
            print(f"\n  SKIP: {name} (not found/cached)")


if __name__ == "__main__":
    main()
