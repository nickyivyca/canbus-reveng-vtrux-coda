"""
Extract a structured catalog of every byte-level and bit-level change at each
charge failure event from the Vtrux charge failure logs.

Three events:
  - M0_b failure:  buckBoostFault, 0x420 goes all-zeros (truklog_M0_T9.log)
  - M1_b failure:  buckBoostFault, 0x420 goes all-zeros (truklog_M1_T13.log)
  - Full charge then fail: shutdownSource=7, voltage collapse (full charge then fail.log)

Outputs:
  failedcharge-bit-catalog.json  -- machine-readable change catalog
  failedcharge-bit-catalog.txt   -- human-readable summary
"""

import sys
import json
import struct
import time
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[3]  # artifacts -> notes -> vtrux -> projects -> reverse-it (root)
sys.path.insert(0, str(PROJECT_ROOT))

from canre.parsers.autodetect import parse_file

# -- Configuration ----------------------------------------------------------

FAILED_CHARGES_DIR = PROJECT_ROOT / "projects" / "vtrux" / "Bel Inverter" / "actual-failed-charges"
LOGS_DIR = PROJECT_ROOT / "projects" / "vtrux" / "logs"
OUTPUT_DIR = SCRIPT_DIR

# Event definitions -- the signature is detected automatically, not by fixed timestamps
EVENTS = {
    "m0b_failure": {
        "label": "M0_b buckBoostFault",
        "log_files": [
            FAILED_CHARGES_DIR / "truklog_M0_T8.log",
            FAILED_CHARGES_DIR / "truklog_M0_T9.log",
            FAILED_CHARGES_DIR / "truklog_M0_T7.log",
        ],
        "detection": "0x420_allzeros",
        "window_before": 2.0,   # seconds before event to capture
        "window_after": 10.0,   # seconds after event to capture
    },
    "m1b_failure": {
        "label": "M1_b buckBoostFault",
        "log_files": [
            FAILED_CHARGES_DIR / "truklog_M1_T13.log",
            FAILED_CHARGES_DIR / "truklog_M1_T12.log",
            FAILED_CHARGES_DIR / "truklog_M1_T14.log",
        ],
        "detection": "0x420_allzeros",
        "window_before": 2.0,
        "window_after": 10.0,
    },
    "full_charge_failure": {
        "label": "Full Charge Then Fail (shutdownSource=7)",
        "log_file": LOGS_DIR / "full charge then fail.log",
        "detection": "voltage_collapse",
        "window_before": 5.0,
        "window_after": 15.0,
    },
}

# Bus identity anchor IDs (standard IDs)
ANCHOR_PT = {0x051}                                       # Powertrain bus
ANCHOR_UF = {0x1E5, 0x500}                                # Vehicle bus
ANCHOR_OBD = {0x040, 0x041, 0x042, 0x043, 0x044}          # OBD bus

# Rolling counter detection threshold
COUNTER_THRESHOLD = 0.80
COUNTER_MIN_CHANGES = 5

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


def detect_bus_map(log_path):
    """Read first 500 frames and map raw bus numbers to logical bus names.

    Returns dict like {1: "OBD", 2: "PT", 3: "UF"} or partial if not all found.
    """
    bus_id_counts = defaultdict(set)  # raw_bus -> set of arb_ids seen
    count = 0
    for frame in parse_file(log_path):
        bus_id_counts[frame.bus].add(frame.arbitration_id)
        count += 1
        if count >= 500:
            break

    bus_map = {}
    for raw_bus, ids in bus_id_counts.items():
        std_ids = {i for i in ids if i <= 0x7FF}
        if std_ids & ANCHOR_PT:
            bus_map[raw_bus] = "PT"
        elif std_ids & ANCHOR_UF:
            bus_map[raw_bus] = "UF"
        elif std_ids & ANCHOR_OBD:
            bus_map[raw_bus] = "OBD"
        else:
            bus_map[raw_bus] = f"BUS{raw_bus}"

    return bus_map


def detect_failure_0x420(log_path):
    """Detect 0x420 B0-B4 going to zeros. Returns t_event.

    In the Vtrux, 0x420 carries battery voltage in B0-B4. When the BMS
    disconnects, B0-B4 go to zero but B5 stays at 0xFF (constant).
    We detect B0-B4 transitioning from non-zero to all-zero.
    """
    last_420_b0b4 = {}  # bus -> last B0-B4 bytes
    frame_count = 0
    t_start = time.time()

    print("  Pass 1: Scanning for 0x420 B0-B4 zeros signature...")
    for frame in parse_file(log_path):
        frame_count += 1
        if frame_count % PROGRESS_INTERVAL == 0:
            elapsed = time.time() - t_start
            print(f"    {frame_count:,} frames ({elapsed:.1f}s elapsed, t={frame.timestamp:.1f}s)")

        if frame.arbitration_id == 0x420 and len(frame.data) >= 5:
            b0b4 = bytes(frame.data[:5])
            prev = last_420_b0b4.get(frame.bus)
            last_420_b0b4[frame.bus] = b0b4

            if prev is not None and prev != b'\x00' * 5 and b0b4 == b'\x00' * 5:
                print(f"    FOUND: 0x420 B0-B4 went to zeros at t={frame.timestamp:.4f}s "
                      f"(bus {frame.bus}, frame #{frame_count:,})")
                return frame.timestamp

    print(f"    WARNING: 0x420 B0-B4 zeros signature NOT found in {frame_count:,} frames")
    return None


def detect_voltage_collapse(log_path):
    """Detect voltage collapse on 0x18FFD7C0 B0-B1 LE signed * 0.05.

    Returns t_event when voltage drops from >400V to <350V.
    """
    last_voltage = None
    frame_count = 0
    t_start = time.time()

    print("  Pass 1: Scanning for voltage collapse on 0x18FFD7C0...")
    for frame in parse_file(log_path):
        frame_count += 1
        if frame_count % PROGRESS_INTERVAL == 0:
            elapsed = time.time() - t_start
            print(f"    {frame_count:,} frames ({elapsed:.1f}s elapsed, t={frame.timestamp:.1f}s)")

        if frame.arbitration_id == 0x18FFD7C0 and len(frame.data) >= 2:
            raw = struct.unpack_from('<h', frame.data, 0)[0]
            voltage = raw * 0.05

            if last_voltage is not None and last_voltage > 400.0 and voltage < 350.0:
                print(f"    FOUND: Voltage collapsed from {last_voltage:.1f}V to {voltage:.1f}V "
                      f"at t={frame.timestamp:.4f}s (frame #{frame_count:,})")
                return frame.timestamp

            last_voltage = voltage

    print(f"    WARNING: Voltage collapse NOT found in {frame_count:,} frames")
    return None


def extract_changes(log_path, t_event, window_before, window_after):
    """Pass 2: Extract all byte-level and bit-level changes in the event window.

    Returns (raw_changes, byte_deltas) where:
      raw_changes: list of change dicts
      byte_deltas: dict of (bus, arb_id, byte_idx) -> list of (old, new)
    """
    t_lo = t_event - window_before
    t_hi = t_event + window_after

    raw_changes = []
    byte_deltas = defaultdict(list)
    last_seen = {}  # (bus, arb_id) -> (t, data)
    frame_count = 0
    recording = False
    t_start = time.time()

    print(f"  Pass 2: Extracting changes in window [{t_lo:.1f}, {t_hi:.1f}]...")
    for frame in parse_file(log_path):
        frame_count += 1
        if frame_count % PROGRESS_INTERVAL == 0:
            elapsed = time.time() - t_start
            print(f"    {frame_count:,} frames ({elapsed:.1f}s elapsed, t={frame.timestamp:.1f}s)")

        t = frame.timestamp
        key = (frame.bus, frame.arbitration_id)
        data = bytes(frame.data)

        # Always update last_seen so we have the prior state when we enter the window
        prev = last_seen.get(key)
        last_seen[key] = (t, data)

        if prev is None:
            continue

        # Skip if no data change
        prev_t, prev_data = prev
        if data == prev_data:
            continue

        # Only record changes within the window
        if t < t_lo:
            continue
        if t > t_hi:
            # Stop once well past the window
            if t > t_hi + 1.0:
                break
            continue

        if not recording:
            recording = True
            print(f"    Entering window at t={t:.3f}s")

        # Compute byte-level changes
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
            raw_changes.append(change_record)
            byte_deltas[(frame.bus, frame.arbitration_id, byte_idx)].append((old_b, new_b))

        # Handle data length increase
        if len(data) > len(prev_data):
            for byte_idx in range(len(prev_data), len(data)):
                if data[byte_idx] == 0x00:
                    continue
                bits = byte_diff_bits(0x00, data[byte_idx])
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
                raw_changes.append(change_record)
                byte_deltas[(frame.bus, frame.arbitration_id, byte_idx)].append((0x00, data[byte_idx]))

    print(f"    Extracted {len(raw_changes):,} raw byte-changes")
    return raw_changes, byte_deltas


def detect_counters(byte_deltas):
    """Identify rolling counter bytes. Returns set of (bus, arb_id, byte_idx) keys."""
    counter_bytes = set()
    for (bus, arb_id, byte_idx), deltas in byte_deltas.items():
        if len(deltas) < COUNTER_MIN_CHANGES:
            continue
        counter_like = 0
        for old_b, new_b in deltas:
            diff = (new_b - old_b) % 256
            if diff == 1 or diff == 255:  # +1 or -1 mod 256
                counter_like += 1
        ratio = counter_like / len(deltas)
        if ratio >= COUNTER_THRESHOLD:
            counter_bytes.add((bus, arb_id, byte_idx))
            is_ext = arb_id > 0x7FF
            id_s = fmt_id(arb_id, is_ext)
            print(f"    Counter detected: Bus {bus} {id_s} B{byte_idx} "
                  f"({counter_like}/{len(deltas)} = {ratio:.0%} incremental)")
    return counter_bytes


def filter_counters(raw_changes, counter_bytes):
    """Remove counter byte changes from raw_changes. Returns filtered list."""
    filtered = []
    removed = 0
    for ch in raw_changes:
        bkey = (ch["bus"], ch["arb_id"], ch["byte"])
        if bkey in counter_bytes:
            removed += 1
            continue
        filtered.append(ch)
    print(f"    Removed {removed:,} counter-byte changes, {len(filtered):,} changes remain")
    return filtered


# -- Main --------------------------------------------------------------------

def main():
    print("FAILED CHARGE BIT-FLIP CATALOG EXTRACTION")
    print("=" * 60)
    print()

    results = {}  # event_key -> processed data for output

    for event_key, ev in EVENTS.items():
        # Support both single file and list of files to try
        if "log_files" in ev:
            candidate_files = ev["log_files"]
        else:
            candidate_files = [ev["log_file"]]
        label = ev["label"]

        print(f"--- {label} ---")

        # Try each candidate file until we find the failure
        log_path = None
        t_event = None
        bus_map = None
        detection_method = ev["detection"]

        for candidate_path in candidate_files:
            print(f"  Trying: {candidate_path.name}")
            try:
                if not candidate_path.exists():
                    print(f"    File not found, skipping")
                    continue
                with open(candidate_path, "r", encoding="utf-8", errors="replace") as fh:
                    fh.readline()
            except (OSError, PermissionError) as e:
                print(f"    Cannot read: {e}")
                continue

            # Detect failure in this file
            if detection_method == "0x420_allzeros":
                t_event = detect_failure_0x420(candidate_path)
            elif detection_method == "voltage_collapse":
                t_event = detect_voltage_collapse(candidate_path)

            if t_event is not None:
                log_path = candidate_path
                print(f"  FOUND failure at t={t_event:.4f}s in {log_path.name}")
                # Detect bus map
                print("  Detecting bus identities...")
                bus_map = detect_bus_map(log_path)
                bus_map_str = {str(k): v for k, v in sorted(bus_map.items())}
                print(f"  Bus map: {bus_map_str}")
                break
            else:
                print(f"    Signature not found in this file")

        if t_event is None or log_path is None:
            print(f"  SKIPPING: Could not detect failure event in any candidate file")
            print()
            continue

        print(f"  Event detected at t={t_event:.4f}s in {log_path.name}")

        # Phase B: Extract changes in window
        raw_changes, byte_deltas = extract_changes(
            log_path, t_event, ev["window_before"], ev["window_after"]
        )

        # Phase C: Counter detection and filtering
        print("  Detecting rolling counters...")
        counter_bytes = detect_counters(byte_deltas)
        filtered_changes = filter_counters(raw_changes, counter_bytes)

        # Sort by timestamp
        filtered_changes.sort(key=lambda c: (c["t"], c["bus"], c["arb_id"], c["byte"]))

        # Build output records
        json_changes = []
        for ch in filtered_changes:
            is_ext = ch["is_extended"]
            bus_name = bus_map.get(ch["bus"], f"BUS{ch['bus']}")
            json_changes.append({
                "t": ch["t"],
                "dt": round(ch["t"] - t_event, 6),
                "bus_raw": ch["bus"],
                "bus_name": bus_name,
                "id": fmt_id(ch["arb_id"], is_ext),
                "is_extended": is_ext,
                "byte": ch["byte"],
                "old_byte": f"0x{ch['old_byte']:02X}",
                "new_byte": f"0x{ch['new_byte']:02X}",
                "bits": ch["bits"],
            })

        # Summary stats
        total_bit_changes = sum(len(ch["bits"]) for ch in json_changes)
        before_event = sum(1 for ch in json_changes if ch["dt"] < 0)
        after_event = sum(1 for ch in json_changes if ch["dt"] >= 0)
        unique_ids = sorted(set(ch["id"] for ch in json_changes))

        earliest_dt = 0.0
        earliest_change = None
        if json_changes:
            earliest_dt = min(ch["dt"] for ch in json_changes)
            for ch in json_changes:
                if ch["dt"] == earliest_dt:
                    earliest_change = f"{ch['id']} B{ch['byte']}"
                    break

        summary = {
            "total_byte_changes": len(json_changes),
            "total_bit_changes": total_bit_changes,
            "changes_before_event": before_event,
            "changes_after_event": after_event,
            "unique_ids": unique_ids,
            "earliest_change_dt": round(earliest_dt, 6),
            "earliest_change_id": earliest_change,
            "counter_bytes_excluded": len(counter_bytes),
        }

        results[event_key] = {
            "label": label,
            "log_file": log_path.name,
            "t_event": round(t_event, 4),
            "detection_method": detection_method,
            "bus_map": bus_map_str,
            "changes": json_changes,
            "filtered_changes": filtered_changes,  # keep for text output (has raw bytes)
            "counter_bytes": counter_bytes,
            "summary": summary,
        }

        print(f"  Summary: {len(json_changes)} byte-changes, "
              f"{total_bit_changes} bit-changes, {len(unique_ids)} unique IDs")
        print()

    if not results:
        print("No events were successfully processed. Exiting.")
        return

    # -- Write JSON output ---------------------------------------------------

    json_output = {"log_events": {}}

    for ek, res in results.items():
        json_output["log_events"][ek] = {
            "log_file": res["log_file"],
            "t_event": res["t_event"],
            "detection_method": res["detection_method"],
            "bus_map": res["bus_map"],
            "changes": res["changes"],
            "summary": res["summary"],
        }

    json_path = OUTPUT_DIR / "failedcharge-bit-catalog.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_output, f, indent=2)
    print(f"Wrote {json_path.name}")

    # -- Write text output ---------------------------------------------------

    lines = []
    lines.append("FAILED CHARGE BIT-FLIP CATALOG")
    lines.append("=" * 70)
    lines.append("")

    for ek, res in results.items():
        label = res["label"]
        t_event = res["t_event"]
        log_file = res["log_file"]
        bus_map = res["bus_map"]
        counter_bytes = res["counter_bytes"]
        filtered_changes = res["filtered_changes"]
        summ = res["summary"]

        lines.append(f"=== {label} ===")
        lines.append(f"  File: {log_file}")
        lines.append(f"  Event detected at t={t_event}s")
        lines.append(f"  Detection: {res['detection_method']}")
        lines.append(f"  Bus map: {bus_map}")
        lines.append("")

        # Counter bytes excluded
        if counter_bytes:
            lines.append("  Excluded rolling counter bytes:")
            for (bus, arb_id, byte_idx) in sorted(counter_bytes):
                is_ext = arb_id > 0x7FF
                bus_name = bus_map.get(str(bus), f"BUS{bus}")
                lines.append(
                    f"    Bus {bus} ({bus_name})  {fmt_id(arb_id, is_ext)}  B{byte_idx}"
                )
            lines.append("")

        # Table header
        hdr = (f"  {'dt(s)':>9s}  {'Bus':>3s}  {'Name':>4s}  {'ID':<12s}  "
               f"{'Byte':>4s}  {'Old':>5s}  {'New':>5s}  Bit Changes")
        sep = (f"  {'-' * 9}  {'-' * 3}  {'-' * 4}  {'-' * 12}  "
               f"{'-' * 4}  {'-' * 5}  {'-' * 5}  {'-' * 30}")
        lines.append(hdr)
        lines.append(sep)

        for ch in filtered_changes:
            dt = ch["t"] - t_event
            is_ext = ch["is_extended"]
            id_s = fmt_id(ch["arb_id"], is_ext)
            bus_name = bus_map.get(str(ch["bus"]), f"BUS{ch['bus']}")
            ext_tag = " [EXT]" if is_ext else ""

            bits_parts = []
            for b in ch["bits"]:
                bits_parts.append(f"bit{b['bit']}: {b['old']}->{b['new']}")
            bits_str = ", ".join(bits_parts)

            lines.append(
                f"  {dt:+9.3f}  {ch['bus']:3d}  {bus_name:>4s}  {id_s:<12s}  "
                f"B{ch['byte']:<3d}  0x{ch['old_byte']:02X}  "
                f"0x{ch['new_byte']:02X}  {bits_str}{ext_tag}"
            )

        lines.append("")
        lines.append("  Summary:")
        lines.append(f"    Total byte changes: {summ['total_byte_changes']}")
        lines.append(f"    Total bit changes:  {summ['total_bit_changes']}")
        lines.append(f"    Changes BEFORE event: {summ['changes_before_event']}")
        lines.append(f"    Changes AFTER event:  {summ['changes_after_event']}")
        eid = summ["earliest_change_id"]
        edt = summ["earliest_change_dt"]
        lines.append(f"    First change: dt={edt:+.3f}s ({eid})")
        lines.append(f"    Unique IDs involved: {len(summ['unique_ids'])}")
        lines.append(f"    Counter bytes excluded: {summ['counter_bytes_excluded']}")
        lines.append("")
        lines.append("")

    txt_content = "\n".join(lines)
    txt_path = OUTPUT_DIR / "failedcharge-bit-catalog.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt_content)
    print(f"Wrote {txt_path.name}")
    print()

    # -- Print summary to stdout ---------------------------------------------

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for ek, res in results.items():
        summ = res["summary"]
        label = res["label"]
        print(f"\n  {label}:")
        print(f"    File:          {res['log_file']}")
        print(f"    t_event:       {res['t_event']}s")
        print(f"    Byte changes:  {summ['total_byte_changes']}")
        print(f"    Bit changes:   {summ['total_bit_changes']}")
        print(f"    Before event:  {summ['changes_before_event']}")
        print(f"    After event:   {summ['changes_after_event']}")
        eid = summ["earliest_change_id"]
        edt = summ["earliest_change_dt"]
        print(f"    First change:  dt={edt:+.3f}s ({eid})")
        print(f"    Unique IDs:    {len(summ['unique_ids'])}")
        print(f"    Counters excl: {summ['counter_bytes_excluded']}")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
