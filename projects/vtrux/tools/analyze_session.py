#!/usr/bin/env python3
"""Analyze CAN log files for charger fault events.

Takes one or more log files and analyzes them as a session.
Files are merged in the order provided.

Usage:
    python tools/analyze_session.py "logs/full charge then fail.log"
    python tools/analyze_session.py debuglog_M0_T0.log debuglog_M0_T1.log debuglog_M0_T2.log
    python tools/analyze_session.py "Bel-Inverter/actual-failed-charges"/truklog_M0_T*.log
    python tools/analyze_session.py file1.log file2.log --window 10
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.parsers import parse_file
from canre.parsers.base import CANFrame
from canre.utils.merge import merge_files

# ── Charger CAN IDs (extended) ──────────────────────────────────────
ID_BINV_STATUS = 0x18FFD4C0  # Multiplexed status + faults
ID_HV_BATT = 0x18FFD7C0  # hvBatteryVoltage, hvBatteryCurrent, charger input V/I
ID_CHARGE_INFO = 0x18FFD9C0  # maxAvailableChargingCurrent, vehicleState
ID_J1772 = 0x18FFD8C0  # J1772 info
ID_CHARGER_TEMP = 0x18FFD5C0  # overall temperature
ID_EFC000 = 0x18EFC000  # Unknown charger multiplex message

# ── Charger mux=0 status bit names (byte1 bits 0-7, byte2 bits 0-7, ...) ──
MUX0_STATUS_BITS = {
    # Byte 1 (bits 8-15 in DBC bit numbering, but byte1 bits 0-7 in data)
    (1, 0): "keySwitch",
    (1, 1): "pilotControlSignal",
    (1, 2): "proxEnabled",
    (1, 3): "evseConnected",
    (1, 4): "vehicleConnected",
    (1, 5): "auxPowerSupply",
    (1, 6): "chargerEnergyFlowEnable",
    (1, 7): "s2Switch",
    # Byte 2 (bits 16-23)
    (2, 0): "chargingInProgress",
    (2, 1): "powerChargingInProgress",
    (2, 2): "exportEnergy",
    (2, 3): "exporting",
    (2, 4): "gridTied",
    (2, 5): "wakeOutput",
    # bit 6 (22) unused
    (2, 7): "delayedSleepMode",
    # Byte 3 (bits 24-31)
    (3, 0): "rewakedFromDelayedSleep",
    (3, 1): "inverterAlive",
    (3, 2): "inverterReady",
    (3, 3): "buckBoostAlive",
    (3, 4): "buckBoostReady",
    (3, 5): "alciResetOn",
    (3, 6): "alciActive",
    # Byte 4 (bits 32-39)
    (4, 1): "evseDisconnected",
    (4, 2): "autoLowPower",
    (4, 6): "standby",
    (4, 7): "unitReady",
}

# ── Charger mux=3 fault bit names ───────────────────────────────────
MUX3_FAULT_BITS = {
    (1, 0): "acOk",
    (1, 1): "acOverVoltage",
    (1, 2): "acUnderVoltage",
    (1, 3): "systemBatteryUnderVoltage",
    (1, 4): "hvBatteryOverVoltage",
    (1, 5): "hvBatteryUnderVoltage",
    (1, 6): "overTemperature",
    (1, 7): "exportOverLoad",
    (2, 0): "inverterFault",
    (2, 1): "buckBoostFault",
    (2, 3): "wakeOutputError",
    (2, 5): "underFrequency",
    (2, 6): "overFrequency",
}


def decode_mux0_bits(data: bytes) -> dict[str, int]:
    """Decode mux=0 status bits from BINV_status data."""
    result = {}
    for (byte_idx, bit_idx), name in MUX0_STATUS_BITS.items():
        if byte_idx < len(data):
            result[name] = (data[byte_idx] >> bit_idx) & 1
    # Also grab state, shutdownSource, stateBeforeLastShutdown
    if len(data) >= 6:
        result["state"] = data[5]
    if len(data) >= 7:
        result["shutdownSource"] = data[6]
    if len(data) >= 8:
        result["stateBeforeLastShutdown"] = data[7]
    return result


def decode_mux3_bits(data: bytes) -> dict[str, int]:
    """Decode mux=3 fault bits from BINV_status data."""
    result = {}
    for (byte_idx, bit_idx), name in MUX3_FAULT_BITS.items():
        if byte_idx < len(data):
            result[name] = (data[byte_idx] >> bit_idx) & 1
    return result


def decode_hv_battery(data: bytes) -> dict[str, float]:
    """Decode hvBatteryAndCharger message."""
    result = {}
    if len(data) >= 2:
        raw = int.from_bytes(data[0:2], "little", signed=True)
        result["hvBatteryVoltage"] = raw * 0.05
    if len(data) >= 4:
        raw = int.from_bytes(data[2:4], "little", signed=True)
        result["hvBatteryCurrent"] = raw * 0.05
    if len(data) >= 6:
        raw = int.from_bytes(data[4:6], "little", signed=True)
        result["chargerInputVoltage"] = raw * 0.05
    if len(data) >= 8:
        raw = int.from_bytes(data[6:8], "little", signed=True)
        result["chargerInputCurrent"] = raw * 0.05
    return result


def decode_charge_info(data: bytes) -> dict:
    """Decode chargeInfo message."""
    result = {}
    if len(data) >= 2:
        raw = int.from_bytes(data[0:2], "little", signed=True)
        result["maxAvailableChargingCurrent"] = raw * 0.05
    if len(data) >= 3:
        result["vehicleState"] = data[2]
    return result


def analyze_session(files: list[Path], session_name: str, window_sec: float = 5.0):
    """Analyze a capture session for fault events."""

    print(f"\n{'='*80}")
    print(f" SESSION: {session_name}  ({len(files)} file(s))")
    if len(files) == 1:
        print(f" File: {files[0].name}")
    else:
        print(f" Files: {files[0].name} ... {files[-1].name}")
    print(f"{'='*80}")

    # Use merge_files to chain T-chunks with correct timestamps (starts at t=0)
    charger_status_events = []  # (timestamp, decoded_dict)  mux=0
    charger_fault_events = []  # (timestamp, decoded_dict)  mux=3
    hv_battery_events = []  # (timestamp, decoded_dict)
    charge_info_events = []  # (timestamp, decoded_dict)

    last_data: dict[int, bytes] = {}
    all_changes: list[tuple] = []  # (timestamp, arb_id, old_data, new_data)

    last_mux3_faults = None
    last_mux0_status = None
    fault_transitions = []  # (timestamp, bit_name, old_val, new_val)
    status_transitions = []  # (timestamp, field_name, old_val, new_val)

    frame_count = 0
    first_ts = None
    last_ts = None
    id_set = set()

    for frame in merge_files(files):
        frame_count += 1
        if first_ts is None:
            first_ts = frame.timestamp
        last_ts = frame.timestamp
        arb_id = frame.arbitration_id
        id_set.add(arb_id)

        # Track per-ID data changes
        prev = last_data.get(arb_id)
        if prev is not None and prev != frame.data:
            all_changes.append((frame.timestamp, arb_id, prev, frame.data))
        last_data[arb_id] = frame.data

        # Decode charger status
        if arb_id == ID_BINV_STATUS and len(frame.data) >= 1:
            mux = frame.data[0]
            if mux == 0:
                decoded = decode_mux0_bits(frame.data)
                charger_status_events.append((frame.timestamp, decoded))
                if last_mux0_status is not None:
                    for field, val in decoded.items():
                        old_val = last_mux0_status.get(field)
                        if old_val is not None and val != old_val:
                            status_transitions.append(
                                (frame.timestamp, field, old_val, val)
                            )
                last_mux0_status = decoded
            elif mux == 3:
                decoded = decode_mux3_bits(frame.data)
                charger_fault_events.append((frame.timestamp, decoded))
                if last_mux3_faults is not None:
                    for bit_name, val in decoded.items():
                        old_val = last_mux3_faults.get(bit_name)
                        if old_val is not None and val != old_val:
                            fault_transitions.append(
                                (frame.timestamp, bit_name, old_val, val)
                            )
                last_mux3_faults = decoded

        elif arb_id == ID_HV_BATT:
            hv_battery_events.append((frame.timestamp, decode_hv_battery(frame.data)))

        elif arb_id == ID_CHARGE_INFO:
            charge_info_events.append(
                (frame.timestamp, decode_charge_info(frame.data))
            )

    if frame_count == 0:
        print("  No frames found.")
        return

    duration = last_ts - first_ts
    print(f"\n  Total frames: {frame_count:,}")
    print(f"  Duration: {duration:.1f}s ({duration/60:.1f} min)")
    print(f"  Data changes tracked: {len(all_changes):,}")

    std_ids = sorted(i for i in id_set if i < 0x800)
    ext_ids = sorted(i for i in id_set if i >= 0x800)
    print(
        f"  Standard IDs ({len(std_ids)}): {', '.join(f'0x{i:03X}' for i in std_ids)}"
    )
    print(
        f"  Extended IDs ({len(ext_ids)}): {', '.join(f'0x{i:08X}' for i in ext_ids)}"
    )

    # Charger state summary
    if charger_status_events:
        states_seen = set()
        for _, decoded in charger_status_events:
            if "state" in decoded:
                states_seen.add(decoded["state"])
        print(f"\n  Charger states seen: {sorted(states_seen)}")

    if charger_fault_events:
        first = charger_fault_events[0]
        last = charger_fault_events[-1]
        print(f"\n  First mux=3 fault frame: t={first[0]:.4f}s  {first[1]}")
        print(f"  Last mux=3 fault frame:  t={last[0]:.4f}s  {last[1]}")

    # FAULT TRANSITIONS
    print(f"\n{'-'*70}")
    print(f"  CHARGER FAULT BIT TRANSITIONS ({len(fault_transitions)})")
    print(f"{'-'*70}")
    if not fault_transitions:
        print("  (no fault bit changes detected)")
    else:
        for ts, bit_name, old_val, new_val in fault_transitions:
            direction = "SET" if new_val == 1 else "CLEARED"
            print(f"  t={ts:.4f}s  {bit_name}: {old_val}->{new_val}  [{direction}]")

    # STATUS TRANSITIONS
    print(f"\n{'-'*70}")
    print(f"  CHARGER STATUS TRANSITIONS ({len(status_transitions)})")
    print(f"{'-'*70}")
    if not status_transitions:
        print("  (no status changes detected)")
    else:
        for ts, field, old_val, new_val in status_transitions:
            if field in ("state", "shutdownSource", "stateBeforeLastShutdown"):
                print(f"  t={ts:.4f}s  {field}: {old_val} -> {new_val}")
            else:
                direction = "SET" if new_val == 1 else "CLEARED"
                print(
                    f"  t={ts:.4f}s  {field}: {old_val}->{new_val}  [{direction}]"
                )

    # WINDOWED ANALYSIS around fault/state triggers
    triggers = []
    for ts, bit_name, old_val, new_val in fault_transitions:
        if bit_name == "acOk" and new_val == 0:
            triggers.append((ts, "FAULT: acOk LOST"))
        elif bit_name != "acOk" and new_val == 1:
            triggers.append((ts, f"FAULT: {bit_name} SET"))
    for ts, field, old_val, new_val in status_transitions:
        if field == "state":
            triggers.append((ts, f"STATE: {old_val}->{new_val}"))
        elif field in (
            "chargingInProgress",
            "chargerEnergyFlowEnable",
            "powerChargingInProgress",
        ):
            if new_val == 0:
                triggers.append((ts, f"STATUS: {field} CLEARED"))
    triggers.sort()

    if not triggers:
        print("\n  No failure trigger events detected.")
        _print_vi_profile(hv_battery_events, duration)
        return

    # Group triggers within 3s of each other
    failure_groups = []
    current_group = [triggers[0]]
    for evt in triggers[1:]:
        if evt[0] - current_group[0][0] < 3.0:
            current_group.append(evt)
        else:
            failure_groups.append(current_group)
            current_group = [evt]
    failure_groups.append(current_group)

    print(f"\n{'='*80}")
    print(f"  FAILURE TIMELINE ANALYSIS  ({len(failure_groups)} event groups)")
    print(f"{'='*80}")

    for group_idx, group in enumerate(failure_groups):
        anchor_ts = group[0][0]
        print(f"\n{'-'*70}")
        print(f"  EVENT GROUP #{group_idx+1}  at t={anchor_ts:.4f}s")
        print(f"  Triggers:")
        for ts, desc in group:
            print(f"    t={ts:.4f}s  {desc}")
        print(f"{'-'*70}")

        # Charger V/I in window
        print(f"\n  Charger V/I (+-{window_sec}s):")
        vi_count = 0
        for ts, decoded in hv_battery_events:
            if anchor_ts - window_sec <= ts <= anchor_ts + window_sec:
                dt = ts - anchor_ts
                v = decoded.get("hvBatteryVoltage", 0)
                i = decoded.get("hvBatteryCurrent", 0)
                vi = decoded.get("chargerInputVoltage", 0)
                ii = decoded.get("chargerInputCurrent", 0)
                print(
                    f"    dt={dt:+8.4f}s  battV={v:7.2f}V  battI={i:7.2f}A  "
                    f"inputV={vi:7.2f}V  inputI={ii:7.2f}A"
                )
                vi_count += 1
        if vi_count == 0:
            print("    (no hv battery data in window)")

        # Charge info in window
        print(f"\n  Charge info (+-{window_sec}s):")
        ci_count = 0
        for ts, decoded in charge_info_events:
            if anchor_ts - window_sec <= ts <= anchor_ts + window_sec:
                dt = ts - anchor_ts
                print(f"    dt={dt:+8.4f}s  {decoded}")
                ci_count += 1
        if ci_count == 0:
            print("    (no charge info in window)")

        # ALL CAN ID changes in window
        print(f"\n  ALL CAN ID data changes (+-{window_sec}s):")
        win_changes = [
            (ts, aid, od, nd)
            for ts, aid, od, nd in all_changes
            if anchor_ts - window_sec <= ts <= anchor_ts + window_sec
        ]

        by_id = defaultdict(list)
        for ts, aid, od, nd in win_changes:
            by_id[aid].append((ts, od, nd))

        for cid in sorted(by_id):
            ch_list = by_id[cid]
            changed_bytes = set()
            for _, od, nd in ch_list:
                for bi in range(min(len(od), len(nd))):
                    if od[bi] != nd[bi]:
                        changed_bytes.add(bi)
            if not changed_bytes:
                continue

            # Detect counter bytes (change >80% of the time)
            total = len(ch_list)
            counter_bytes = set()
            for bi in changed_bytes:
                cnt = sum(
                    1
                    for _, od, nd in ch_list
                    if bi < min(len(od), len(nd)) and od[bi] != nd[bi]
                )
                if cnt > total * 0.8 and total > 10:
                    counter_bytes.add(bi)

            interesting = changed_bytes - counter_bytes
            if not interesting:
                continue

            id_str = f"0x{cid:03X}" if cid < 0x800 else f"0x{cid:08X}"
            ctr_note = (
                f"  [counters: B{','.join(str(b) for b in sorted(counter_bytes))}]"
                if counter_bytes
                else ""
            )
            print(f"\n    {id_str}  changed bytes: {sorted(interesting)}{ctr_note}")

            shown = 0
            for ts, od, nd in ch_list:
                dt = ts - anchor_ts
                diffs = []
                for bi in sorted(interesting):
                    if bi < min(len(od), len(nd)) and od[bi] != nd[bi]:
                        diffs.append(f"B{bi}:{od[bi]:02X}->{nd[bi]:02X}")
                if diffs:
                    old_hex = " ".join(f"{b:02X}" for b in od)
                    new_hex = " ".join(f"{b:02X}" for b in nd)
                    print(f"      dt={dt:+8.4f}s  {' | '.join(diffs)}")
                    print(f"                   old: {old_hex}")
                    print(f"                   new: {new_hex}")
                    shown += 1
                    if shown >= 25:
                        print(f"      ... (truncated)")
                        break

    _print_vi_profile(hv_battery_events, duration)


def _print_vi_profile(hv_events, duration):
    if not hv_events:
        return
    print(f"\n{'-'*70}")
    print(f"  VOLTAGE/CURRENT PROFILE (sampled)")
    print(f"{'-'*70}")
    interval = max(1.0, duration / 40)
    last_sample = -999
    for ts, decoded in hv_events:
        if ts - last_sample >= interval:
            v = decoded.get("hvBatteryVoltage", 0)
            i = decoded.get("hvBatteryCurrent", 0)
            print(f"  t={ts:8.1f}s  V={v:7.2f}V  I={i:7.2f}A")
            last_sample = ts


def main():
    parser = argparse.ArgumentParser(
        description="Analyze CAN log files for charger fault events"
    )
    parser.add_argument("files", nargs="+", help="Log file(s) to analyze")
    parser.add_argument(
        "--window",
        type=float,
        default=5.0,
        help="Window size in seconds around fault events (default: 5)",
    )
    parser.add_argument(
        "--name", help="Session name for display (default: derived from filename)"
    )
    args = parser.parse_args()

    # Convert to Path objects and verify existence
    file_paths = []
    for f in args.files:
        p = Path(f)
        if not p.is_file():
            print(f"Error: {p} is not a file", file=sys.stderr)
            sys.exit(1)
        file_paths.append(p)

    # Determine session name
    if args.name:
        session_name = args.name
    elif len(file_paths) == 1:
        session_name = file_paths[0].stem
    else:
        # For multiple files, try to extract common prefix
        session_name = f"{len(file_paths)} files"

    analyze_session(file_paths, session_name, window_sec=args.window)


if __name__ == "__main__":
    main()
