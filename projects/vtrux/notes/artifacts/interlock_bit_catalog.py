"""
Extract a structured catalog of every byte-level and bit-level change at each
interlock disconnect event from the Vtrux interlock test log.

Two events:
  - HVAC pull: first fault bit at t=63.23s (Bus 2, 0x410 B0)
  - HVD pull:  first fault bit at t=240.75s (Bus 2, 0x410 B0)

Outputs:
  interlock-bit-catalog.json  -- machine-readable change catalog
  interlock-bit-catalog.txt   -- human-readable summary
"""

import sys
import json
import time
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]  # artifacts -> notes -> vtrux -> projects -> reverse-it (root)
sys.path.insert(0, str(PROJECT_ROOT))

from canre.parsers.autodetect import parse_file

# -- Configuration ----------------------------------------------------------

LOG_FILE = PROJECT_ROOT / "projects" / "vtrux" / "logs" / "vtruxinterlocktest.log"
OUTPUT_DIR = SCRIPT_DIR

# Event definitions
EVENTS = {
    "hvac_pull": {
        "label": "HVAC PULL",
        "t_first_fault_bit": 63.23,
        "window": (61.0, 73.0),
    },
    "hvd_pull": {
        "label": "HVD PULL",
        "t_first_fault_bit": 240.75,
        "window": (238.0, 251.0),
    },
}

# Rolling counter detection: if a byte changes by exactly +/-1 (mod 256)
# more than this fraction of its total changes within a window, it is a counter.
COUNTER_THRESHOLD = 0.80

PROGRESS_INTERVAL = 500_000


# -- Helpers -----------------------------------------------------------------

def fmt_id(arb_id, is_extended):
    """Format arbitration ID as hex string."""
    if is_extended:
        return f"0x{arb_id:08X}"
    return f"0x{arb_id:03X}"


def byte_diff_bits(old_byte, new_byte):
    """Return list of bit-level changes between two byte values.

    Bit 0 is the LSB.  Returns [{"bit": N, "old": 0/1, "new": 0/1}, ...]
    """
    xor = old_byte ^ new_byte
    changes = []
    for bit in range(8):
        if xor & (1 << bit):
            changes.append({
                "bit": bit,
                "old": (old_byte >> bit) & 1,
                "new": (new_byte >> bit) & 1,
            })
    return changes


# -- Main --------------------------------------------------------------------

def main():
    print("INTERLOCK BIT-FLIP CATALOG EXTRACTION")
    print(f"Log: {LOG_FILE.name}")
    ev_labels = ", ".join(ev["label"] for ev in EVENTS.values())
    print(f"Events: {ev_labels}")
    print()

    # Storage: event_key -> list of raw change dicts
    raw_changes = {k: [] for k in EVENTS}

    # Track byte-level change increments for rolling counter detection
    # Key: event_key -> (bus, arb_id, byte_idx) -> list of (old, new)
    byte_deltas = {k: defaultdict(list) for k in EVENTS}

    # Last seen data per (bus, arb_id)
    last_seen = {}

    frame_count = 0
    change_count = 0
    t_start = time.time()

    print("Scanning log...")
    for frame in parse_file(LOG_FILE):
        frame_count += 1
        if frame_count % PROGRESS_INTERVAL == 0:
            elapsed = time.time() - t_start
            print(f"  {frame_count:,} frames processed "
                  f"({elapsed:.1f}s elapsed, t={frame.timestamp:.1f}s in log)")

        key = (frame.bus, frame.arbitration_id)
        t = frame.timestamp
        data = bytes(frame.data)

        prev = last_seen.get(key)
        last_seen[key] = (t, data)

        if prev is None:
            continue

        prev_t, prev_data = prev

        # Quick check: any change at all?
        if data == prev_data:
            continue

        # Check if this timestamp falls in any event window
        matched_events = []
        for ek, ev in EVENTS.items():
            lo, hi = ev["window"]
            if lo <= t <= hi:
                matched_events.append(ek)

        if not matched_events:
            continue

        # Compute byte-level and bit-level changes
        min_len = min(len(data), len(prev_data))
        for byte_idx in range(min_len):
            old_b = prev_data[byte_idx]
            new_b = data[byte_idx]
            if old_b == new_b:
                continue

            bits = byte_diff_bits(old_b, new_b)
            change_record = {
                "t": round(t, 6),
                "bus": frame.bus,
                "arb_id": frame.arbitration_id,
                "is_extended": frame.is_extended,
                "byte": byte_idx,
                "old_byte": old_b,
                "new_byte": new_b,
                "bits": bits,
            }

            for ek in matched_events:
                raw_changes[ek].append(change_record)
                byte_deltas[ek][
                    (frame.bus, frame.arbitration_id, byte_idx)
                ].append((old_b, new_b))
                change_count += 1

        # Handle case where new data is longer than previous
        if len(data) > len(prev_data):
            for byte_idx in range(len(prev_data), len(data)):
                bits = byte_diff_bits(0x00, data[byte_idx])
                if not bits:
                    continue
                change_record = {
                    "t": round(t, 6),
                    "bus": frame.bus,
                    "arb_id": frame.arbitration_id,
                    "is_extended": frame.is_extended,
                    "byte": byte_idx,
                    "old_byte": 0x00,
                    "new_byte": data[byte_idx],
                    "bits": bits,
                }
                for ek in matched_events:
                    raw_changes[ek].append(change_record)
                    byte_deltas[ek][
                        (frame.bus, frame.arbitration_id, byte_idx)
                    ].append((0x00, data[byte_idx]))
                    change_count += 1

    elapsed = time.time() - t_start
    print(f"  Done: {frame_count:,} frames in {elapsed:.1f}s, "
          f"{change_count:,} raw byte-changes in event windows")
    print()

    # -- Rolling counter filtering -------------------------------------------

    print("Detecting rolling counters...")
    counter_bytes = {k: set() for k in EVENTS}

    for ek in EVENTS:
        for (bus, arb_id, byte_idx), deltas in byte_deltas[ek].items():
            if len(deltas) < 5:
                # Too few changes to reliably classify
                continue
            counter_like = 0
            for old_b, new_b in deltas:
                diff = (new_b - old_b) % 256
                if diff == 1 or diff == 255:  # +1 or -1 mod 256
                    counter_like += 1
            ratio = counter_like / len(deltas)
            if ratio >= COUNTER_THRESHOLD:
                counter_bytes[ek].add((bus, arb_id, byte_idx))
                id_s = fmt_id(arb_id, arb_id > 0x7FF)
                print(f"  [{ek}] Counter detected: Bus {bus} {id_s} B{byte_idx} "
                      f"({counter_like}/{len(deltas)} = {ratio:.0%} incremental)")

    # Filter out counter bytes
    filtered_changes = {k: [] for k in EVENTS}
    removed_counts = {k: 0 for k in EVENTS}

    for ek in EVENTS:
        for ch in raw_changes[ek]:
            bkey = (ch["bus"], ch["arb_id"], ch["byte"])
            if bkey in counter_bytes[ek]:
                removed_counts[ek] += 1
                continue
            filtered_changes[ek].append(ch)

    for ek in EVENTS:
        print(f"  [{ek}] Removed {removed_counts[ek]:,} counter-byte changes, "
              f"{len(filtered_changes[ek]):,} changes remain")
    print()

    # -- Sort by timestamp ---------------------------------------------------

    for ek in EVENTS:
        filtered_changes[ek].sort(
            key=lambda c: (c["t"], c["bus"], c["arb_id"], c["byte"])
        )

    # -- Build JSON output ---------------------------------------------------

    json_output = {
        "log": LOG_FILE.name,
        "events": {},
        "summary": {},
    }

    for ek, ev in EVENTS.items():
        t_fault = ev["t_first_fault_bit"]
        changes = filtered_changes[ek]

        # Build JSON change records
        json_changes = []
        for ch in changes:
            is_ext = ch["is_extended"]
            json_changes.append({
                "t": ch["t"],
                "dt": round(ch["t"] - t_fault, 6),
                "bus": ch["bus"],
                "id": fmt_id(ch["arb_id"], is_ext),
                "byte": ch["byte"],
                "old_byte": f"0x{ch['old_byte']:02X}",
                "new_byte": f"0x{ch['new_byte']:02X}",
                "bits": ch["bits"],
            })

        json_output["events"][ek] = {
            "t_first_fault_bit": t_fault,
            "window": list(ev["window"]),
            "changes": json_changes,
        }

        # Summary
        unique_ids = sorted(set(ch["id"] for ch in json_changes))
        total_bit_changes = sum(len(ch["bits"]) for ch in json_changes)
        before_fault = sum(1 for ch in json_changes if ch["dt"] < 0)
        after_fault = sum(1 for ch in json_changes if ch["dt"] >= 0)

        earliest_dt = 0.0
        earliest_change = None
        if json_changes:
            earliest_dt = min(ch["dt"] for ch in json_changes)
            for ch in json_changes:
                if ch["dt"] == earliest_dt:
                    earliest_change = f"{ch['id']} B{ch['byte']}"
                    break

        json_output["summary"][ek] = {
            "total_byte_changes": len(json_changes),
            "total_bit_changes": total_bit_changes,
            "unique_ids": unique_ids,
            "earliest_change_dt": round(earliest_dt, 6),
            "earliest_change_id": earliest_change,
            "changes_before_fault": before_fault,
            "changes_after_fault": after_fault,
            "counter_bytes_excluded": len(counter_bytes[ek]),
        }

    # Write JSON
    json_path = OUTPUT_DIR / "interlock-bit-catalog.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_output, f, indent=2)
    print(f"Wrote {json_path.name}")

    # -- Build text output ---------------------------------------------------

    lines = []
    lines.append("INTERLOCK BIT-FLIP CATALOG")
    lines.append(f"Log: {LOG_FILE.name}")
    lines.append("")

    for ek, ev in EVENTS.items():
        t_fault = ev["t_first_fault_bit"]
        label = ev["label"]
        changes = filtered_changes[ek]
        summ = json_output["summary"][ek]

        lines.append(f"=== {label} (first fault bit at t={t_fault}s) ===")
        lines.append("")

        # Counter bytes excluded
        if counter_bytes[ek]:
            lines.append("  Excluded rolling counter bytes:")
            for (bus, arb_id, byte_idx) in sorted(counter_bytes[ek]):
                is_ext = arb_id > 0x7FF
                lines.append(
                    f"    Bus {bus}  {fmt_id(arb_id, is_ext)}  B{byte_idx}"
                )
            lines.append("")

        # Table header
        hdr = (f"  {'dt(s)':>9s}  {'Bus':>3s}  {'ID':<10s}  "
               f"{'Byte':>4s}  {'Old':>5s}  {'New':>5s}  Bit Changes")
        sep = (f"  {'-' * 9}  {'-' * 3}  {'-' * 10}  "
               f"{'-' * 4}  {'-' * 5}  {'-' * 5}  {'-' * 30}")
        lines.append(hdr)
        lines.append(sep)

        for ch in changes:
            dt = ch["t"] - t_fault
            is_ext = ch["is_extended"]
            id_s = fmt_id(ch["arb_id"], is_ext)
            bits_parts = []
            for b in ch["bits"]:
                bits_parts.append(f"bit{b['bit']}: {b['old']}->{b['new']}")
            bits_str = ", ".join(bits_parts)
            lines.append(
                f"  {dt:+9.3f}  {ch['bus']:3d}  {id_s:<10s}  "
                f"B{ch['byte']:<3d}  0x{ch['old_byte']:02X}  "
                f"0x{ch['new_byte']:02X}  {bits_str}"
            )

        lines.append("")
        lines.append("  Summary:")
        lines.append(
            f"    Total byte changes: {summ['total_byte_changes']}"
        )
        lines.append(
            f"    Total bit changes:  {summ['total_bit_changes']}"
        )
        lines.append(
            f"    Changes BEFORE fault: {summ['changes_before_fault']}"
        )
        lines.append(
            f"    Changes AFTER fault:  {summ['changes_after_fault']}"
        )
        eid = summ["earliest_change_id"]
        edt = summ["earliest_change_dt"]
        lines.append(
            f"    First change: dt={edt:+.3f}s ({eid})"
        )
        lines.append(
            f"    Unique IDs involved: {len(summ['unique_ids'])}"
        )
        lines.append(
            f"    Counter bytes excluded: {summ['counter_bytes_excluded']}"
        )
        lines.append("")
        lines.append("")

    txt_content = "\n".join(lines)

    txt_path = OUTPUT_DIR / "interlock-bit-catalog.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt_content)
    print(f"Wrote {txt_path.name}")
    print()

    # -- Print summary to stdout ---------------------------------------------

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for ek, ev in EVENTS.items():
        summ = json_output["summary"][ek]
        label = ev["label"]
        print(f"\n{label}:")
        print(f"  Byte changes:  {summ['total_byte_changes']}")
        print(f"  Bit changes:   {summ['total_bit_changes']}")
        print(f"  Before fault:  {summ['changes_before_fault']}")
        print(f"  After fault:   {summ['changes_after_fault']}")
        eid = summ["earliest_change_id"]
        edt = summ["earliest_change_dt"]
        print(f"  First change:  dt={edt:+.3f}s ({eid})")
        print(f"  Unique IDs:    {len(summ['unique_ids'])}")
        print(f"  Counters excl: {summ['counter_bytes_excluded']}")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
