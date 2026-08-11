"""
Wide-net scan for charge failure precursors.
For each charge failure event, find EVERY byte-level transition on the
powertrain bus in a window before 0x410 B0 changes, sorted by time.
Goal: is 0x644 B0 the earliest indicator, or does something else move first?

Uses streaming to handle large logs. Only tracks standard-frame IDs.
"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from canre.parsers import parse_file
from collections import defaultdict

LOGS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')
SCRIPT_DIR = os.path.dirname(__file__)

PT_ANCHOR = 0x051

# Charge failure logs and approximate event times (from prior analysis)
CHARGE_EVENTS = [
    {
        "label": "rainychargedebug (full log)",
        "file": os.path.join(LOGS_DIR, "rainychargedebug.log"),
        "active_state": 0x4D,  # charging state
    },
    {
        "label": "rainychargedebug2 (short log, normal shutdown)",
        "file": os.path.join(LOGS_DIR, "rainychargedebug2.log"),
        "active_state": 0x19,  # key-on state (this is actually a normal shutdown for comparison)
    },
]

# Also check the bit catalogs from prior analysis for M0_b and M1_b
CATALOG_JSON = os.path.join(SCRIPT_DIR, "failedcharge-bit-catalog.json")


def scan_log_for_precursors(path, label, active_state, window_before=5.0, window_after=1.0):
    """Stream through a log, find when 0x410 B0 leaves active_state,
    then report ALL byte-level transitions in [-window_before, +window_after]."""

    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")

    # Pass 1: find PT bus and 0x410 B0 event times
    pt_bus = None
    prev_410_b0 = None
    event_times = []
    frame_count = 0

    for f in parse_file(path):
        frame_count += 1
        if pt_bus is None and f.arbitration_id == PT_ANCHOR:
            pt_bus = f.bus
        if pt_bus is not None and f.bus == pt_bus and f.arbitration_id == 0x410:
            b0 = f.data[0]
            if prev_410_b0 == active_state and b0 != active_state:
                event_times.append(f.timestamp)
            prev_410_b0 = b0

    if pt_bus is None:
        print("  (powertrain bus not found)")
        return
    if not event_times:
        print(f"  PT bus={pt_bus}, {frame_count} frames, no 0x410 B0 transition from 0x{active_state:02X}")
        return

    print(f"  PT bus={pt_bus}, {frame_count} frames")
    print(f"  0x410 B0 events (leaving 0x{active_state:02X}): {len(event_times)}")
    for i, t in enumerate(event_times):
        print(f"    Event {i+1}: t={t:.3f}s")

    # Pass 2: collect all byte-level transitions on PT bus in windows
    prev_bytes = {}  # (id, bi) -> value
    # For each event, transitions list
    event_transitions = {i: [] for i in range(len(event_times))}
    # Track which windows each frame falls in
    windows = [(t - window_before, t + window_after) for t in event_times]

    for f in parse_file(path):
        if f.bus != pt_bus or f.arbitration_id >= 0x800:
            continue

        aid = f.arbitration_id
        for bi in range(min(len(f.data), 8)):
            key = (aid, bi)
            bval = f.data[bi]
            prev = prev_bytes.get(key)
            if prev is not None and prev != bval:
                for ev_i, (w_start, w_end) in enumerate(windows):
                    if w_start <= f.timestamp <= w_end:
                        dt = f.timestamp - event_times[ev_i]
                        event_transitions[ev_i].append((dt, aid, bi, prev, bval))
            prev_bytes[key] = bval

    # Report
    for ev_i in range(len(event_times)):
        trans = event_transitions[ev_i]
        if not trans:
            print(f"\n  Event {ev_i+1}: no transitions in window")
            continue

        # Sort by dt, filter to BEFORE 0x410 (dt < 0) plus a small after window
        trans.sort(key=lambda r: r[0])

        # Count how many unique (id, byte) change before dt=0
        before = [(dt, aid, bi, old, new) for dt, aid, bi, old, new in trans if dt < 0]
        after_short = [(dt, aid, bi, old, new) for dt, aid, bi, old, new in trans if 0 <= dt <= 0.5]

        print(f"\n  --- Event {ev_i+1}: t={event_times[ev_i]:.3f}s ---")
        print(f"  Transitions before 0x410: {len(before)}")
        print(f"  Transitions 0-500ms after: {len(after_short)}")

        # Show all transitions before, then first few after
        print(f"\n  {'dt':>9}  {'ID':>6}  {'Byte':>4}  {'Old':>5}  {'New':>5}")
        print(f"  {'-'*9}  {'-'*6}  {'-'*4}  {'-'*5}  {'-'*5}")

        # Deduplicate: for each (id, byte), show only FIRST transition before event
        seen_before = set()
        for dt, aid, bi, old, new in before:
            key = (aid, bi)
            if key in seen_before:
                continue
            seen_before.add(key)
            print(f"  {dt:+9.3f}  0x{aid:03X}  B{bi}    0x{old:02X}  0x{new:02X}")

        print(f"  --- 0x410 B0 event (dt=0) ---")

        seen_after = set()
        count = 0
        for dt, aid, bi, old, new in after_short:
            key = (aid, bi)
            if key in seen_after:
                continue
            seen_after.add(key)
            marker = ""
            if aid == 0x410 and bi == 1:
                if (new & 0x40) and not (old & 0x40):
                    marker = "  <-- FAULT FLAG"
            print(f"  {dt:+9.3f}  0x{aid:03X}  B{bi}    0x{old:02X}  0x{new:02X}{marker}")
            count += 1
            if count >= 30:
                print(f"  ... ({len(after_short) - count} more)")
                break


def check_catalogs():
    """Check the pre-built charge failure catalogs for M0_b, M1_b, full-charge-fail."""
    if not os.path.exists(CATALOG_JSON):
        print(f"\n  SKIP: {CATALOG_JSON} not found")
        return

    print(f"\n{'='*70}")
    print(f"  CATALOG CHECK: M0_b, M1_b, full-charge-fail (from bit catalogs)")
    print(f"{'='*70}")

    with open(CATALOG_JSON) as f:
        data = json.load(f)

    for event_key in ("m0b_failure", "m1b_failure", "full_charge_failure"):
        edata = data["log_events"][event_key]
        t_event = edata["t_event"]
        changes = edata["changes"]

        # Filter to standard frames, sort by dt
        std_changes = [c for c in changes if not c.get("is_extended", False)
                       and int(c["id"], 16) < 0x800]
        std_changes.sort(key=lambda c: c["dt"])

        # Show everything before dt=0
        before = [c for c in std_changes if c["dt"] < 0]
        after_short = [c for c in std_changes if 0 <= c["dt"] <= 0.5]

        print(f"\n  --- {event_key}: t_event={t_event:.3f}s ---")
        print(f"  Changes before 0x410: {len(before)} (byte-level)")
        print(f"  Changes 0-500ms after: {len(after_short)}")

        # Deduplicate by (id, byte), show first occurrence
        print(f"\n  {'dt':>9}  {'ID':>6}  {'Byte':>4}  {'Old':>5}  {'New':>5}")
        print(f"  {'-'*9}  {'-'*6}  {'-'*4}  {'-'*5}  {'-'*5}")

        seen = set()
        for c in before:
            key = (c["id"], c["byte"])
            if key in seen:
                continue
            seen.add(key)
            old_val = c['old_byte'] if isinstance(c['old_byte'], int) else int(c['old_byte'])
            new_val = c['new_byte'] if isinstance(c['new_byte'], int) else int(c['new_byte'])
            print(f"  {c['dt']:+9.3f}  {c['id']:>6}  B{c['byte']}    0x{old_val:02X}  0x{new_val:02X}")

        print(f"  --- 0x410 B0 event (dt=0) ---")

        seen2 = set()
        count = 0
        for c in after_short:
            key = (c["id"], c["byte"])
            if key in seen2:
                continue
            seen2.add(key)
            marker = ""
            old_val2 = c['old_byte'] if isinstance(c['old_byte'], int) else int(c['old_byte'])
            new_val2 = c['new_byte'] if isinstance(c['new_byte'], int) else int(c['new_byte'])
            if c["id"] in ("0x410", "410") and c["byte"] == 1:
                if (new_val2 & 0x40) and not (old_val2 & 0x40):
                    marker = "  <-- FAULT FLAG"
            print(f"  {c['dt']:+9.3f}  {c['id']:>6}  B{c['byte']}    0x{old_val2:02X}  0x{new_val2:02X}{marker}")
            count += 1
            if count >= 30:
                print(f"  ... (more)")
                break


def main():
    print("CHARGE FAILURE PRECURSOR SCAN")
    print("Looking for ANY signal that changes before 0x410 B0 at charge failure events\n")

    for ev in CHARGE_EVENTS:
        if os.path.exists(ev["file"]):
            scan_log_for_precursors(ev["file"], ev["label"], ev["active_state"])
        else:
            print(f"\n  SKIP: {ev['label']} (not cached)")

    check_catalogs()


if __name__ == "__main__":
    main()
