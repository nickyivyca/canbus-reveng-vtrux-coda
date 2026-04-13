#!/usr/bin/env python3
"""Scan all OBD diagnostic traffic in a CAN log and identify EVAP-related PIDs.

Extracts:
  - Mode 0x41 (standard OBD Mode 01 responses): any PID
  - Mode 0x62 (GM enhanced Mode 0x22 responses): any PID

For each PID found, shows:
  - How often it was polled
  - Min/max/mean of decoded value over the full log
  - Decoded value at log start, at generator start, and at log end
  - Whether the value monotonically decreases after generator start

Also extracts request frames (0x7DF = broadcast, 0x7E0 = GM ECM targeted)
to confirm which PIDs are actively being requested.

Output CSV: timestamp_s, source_id, mode, pid_hex, raw_value
Also prints a summary table to stdout.

Usage:
    python scan_obd_traffic.py <log_file> [--bus N] [--t-gen-start T] [--output file.csv]
"""
import argparse
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from canre.parsers import parse_file


# Standard OBD PID names (Mode 01)
PID_NAMES_01 = {
    0x05: "EngineCoolantTemp_C",
    0x0C: "EngineRPM",
    0x0D: "VehicleSpeed_kmh",
    0x11: "ThrottlePos_%",
    0x2E: "CommandedEvapPurge_%",
    0x33: "BaroPressure_kPa",
    0x44: "FuelAirEquivRatio",
    0x45: "RelativeThrottle_%",
    0x46: "AmbientAirTemp_C",
    0x47: "ThrottleActuator_%",
    0x53: "AbsEvapSysVaporPressure_kPa",
    0x54: "EvapSysVaporPressure_Pa",
    0x5C: "EngineFuelTemp_C",
    0x5E: "EngineFuelRate_Lph",
}


def decode_mode01(pid, data):
    """Decode standard OBD Mode 01 response. Returns float value, or None if unknown."""
    if pid == 0x0C and len(data) >= 2:
        return (data[0] * 256 + data[1]) / 4.0     # Engine RPM
    if pid == 0x0D and len(data) >= 1:
        return float(data[0])                        # Vehicle speed km/h
    if pid == 0x05 and len(data) >= 1:
        return data[0] - 40.0                        # Coolant temp C
    if pid == 0x11 and len(data) >= 1:
        return data[0] * 100.0 / 255.0              # Throttle %
    if pid == 0x2E and len(data) >= 1:
        return data[0] * 100.0 / 255.0              # Commanded evap purge %
    if pid == 0x33 and len(data) >= 1:
        return float(data[0])                        # Baro pressure kPa
    if pid == 0x44 and len(data) >= 2:
        return (data[0] * 256 + data[1]) / 32768.0  # Fuel/air ratio
    if pid == 0x53 and len(data) >= 2:
        return (data[0] * 256 + data[1]) / 200.0    # Abs evap vapor pressure kPa
    if pid == 0x54 and len(data) >= 2:
        raw = (data[0] * 256 + data[1])
        if raw >= 32768:
            raw -= 65536
        return float(raw)                            # Evap vapor pressure Pa (signed)
    if pid == 0x5E and len(data) >= 2:
        return (data[0] * 256 + data[1]) / 20.0     # Fuel rate L/h
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log", help="BUSMASTER log file path")
    ap.add_argument("--bus", type=int, default=None,
                    help="Filter to specific bus number (default: auto-detect OBD bus)")
    ap.add_argument("--t-gen-start", type=float, default=None,
                    help="Generator start timestamp in seconds (default: auto-detect via 0x63C B6)")
    ap.add_argument("--output", "-o", default=None,
                    help="Write raw rows to this CSV file")
    args = ap.parse_args()

    # Identify OBD bus and PT bus, and find t_gen_start if not provided
    obd_bus = args.bus
    pt_bus = None
    t_gen_start = args.t_gen_start

    # First-pass: detect bus numbers and optionally find t_gen_start
    if obd_bus is None or t_gen_start is None:
        print("Auto-detecting bus channels...", file=sys.stderr)
        seen_obd = set()
        seen_pt = set()
        for frame in parse_file(args.log):
            cid = frame.arbitration_id
            if cid in {0x040, 0x041, 0x042, 0x043, 0x044}:
                seen_obd.add(frame.bus)
            if cid == 0x051:
                seen_pt.add(frame.bus)
            if t_gen_start is None and pt_bus and cid == 0x63C and frame.bus == pt_bus:
                if frame.dlc >= 7 and frame.data[6] > 6:
                    t_gen_start = frame.timestamp
            # Once all three assigned, we only need to find t_gen_start
            if obd_bus is None and seen_obd:
                obd_bus = min(seen_obd)
                print(f"  OBD bus: {obd_bus}", file=sys.stderr)
            if pt_bus is None and seen_pt:
                pt_bus = min(seen_pt)
                print(f"  PT bus: {pt_bus}", file=sys.stderr)
            if obd_bus and pt_bus and t_gen_start:
                break
        if t_gen_start:
            print(f"  Generator start: t={t_gen_start:.3f}s", file=sys.stderr)
        else:
            print("  Generator start: not detected (generator may not have run)", file=sys.stderr)

    if obd_bus is None:
        print("ERROR: Could not identify OBD bus. Use --bus N.", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning OBD traffic on bus {obd_bus}...", file=sys.stderr)

    # Collect all OBD responses and requests
    # pid_data: {(mode_hex, pid_hex): [(timestamp, decoded_value, raw_bytes)]}
    pid_data = defaultdict(list)
    request_pids = defaultdict(int)   # {(src_id_hex, pid_hex): count}

    csv_rows = []

    for frame in parse_file(args.log):
        if frame.bus != obd_bus:
            continue
        cid = frame.arbitration_id
        d = frame.data
        ts = frame.timestamp

        # OBD request frame (scanner or VCM)
        if cid in (0x7DF, 0x7E0) and len(d) >= 3:
            if d[1] == 0x01:  # Mode 01 request
                pid = d[2]
                request_pids[(hex(cid), hex(pid))] += 1

        # OBD standard response (Mode 0x41 = Mode 01 + 0x40)
        if cid == 0x7E8 and len(d) >= 4 and d[1] == 0x41:
            pid = d[2]
            val_bytes = bytes(d[3:])
            decoded = decode_mode01(pid, val_bytes)
            pid_key = ("0x41", hex(pid))
            pid_data[pid_key].append((ts, decoded, val_bytes))
            csv_rows.append((ts, hex(cid), "0x41", hex(pid),
                             decoded if decoded is not None else int(d[3]) if len(d) > 3 else 0))

        # GM enhanced Mode 0x22 response (Mode 0x62 = 0x22 + 0x40)
        # Response: [len, 0x62, PID_H, PID_L, data...]
        if cid == 0x7E8 and len(d) >= 5 and d[1] == 0x62:
            pid = (d[2] << 8) | d[3]
            val_bytes = bytes(d[4:])
            raw_val = int.from_bytes(val_bytes[:4], 'big') if val_bytes else 0
            pid_key = ("0x62", hex(pid))
            pid_data[pid_key].append((ts, float(raw_val), val_bytes))
            csv_rows.append((ts, hex(cid), "0x62", hex(pid), float(raw_val)))

    if not pid_data:
        print("No OBD response frames found on bus {obd_bus}.", file=sys.stderr)
        sys.exit(1)

    # Write CSV if requested
    if args.output:
        with open(args.output, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp_s", "source_id", "mode", "pid_hex", "raw_value"])
            w.writerows(csv_rows)
        print(f"Wrote {len(csv_rows)} rows to {args.output}", file=sys.stderr)

    # Print summary table
    print()
    print(f"=== OBD Traffic Summary (bus {obd_bus}) ===")
    print(f"Generator start: {t_gen_start:.3f}s" if t_gen_start else "Generator start: N/A")
    print()

    # Request summary
    if request_pids:
        print("Request PIDs observed:")
        for (src, pid_hex), cnt in sorted(request_pids.items()):
            pid_int = int(pid_hex, 16)
            name = PID_NAMES_01.get(pid_int, "")
            print(f"  {src:>8}  PID={pid_hex:>6}  count={cnt:>6}  {name}")
        print()

    # Response summary
    print(f"{'Mode':>6} {'PID':>8}  {'Count':>7}  {'Mean':>10}  {'Min':>10}  {'Max':>10}  "
          f"{'AtStart':>10}  {'AtGenEnd':>10}  {'Descending?':>12}  Name")
    print("-" * 120)

    for (mode, pid_hex), entries in sorted(pid_data.items()):
        pid_int = int(pid_hex, 16)
        name = PID_NAMES_01.get(pid_int, "") if mode == "0x41" else f"GM_Enhanced_{pid_hex}"

        timestamps = [e[0] for e in entries]
        vals = [e[1] for e in entries if e[1] is not None]

        if not vals:
            continue

        mean_val = sum(vals) / len(vals)
        min_val = min(vals)
        max_val = max(vals)

        # Value at start of log (~first 5s)
        early = [e[1] for e in entries if e[0] <= 5.0 and e[1] is not None]
        at_start = sum(early) / len(early) if early else float('nan')

        # Value near generator start (if available)
        if t_gen_start:
            gen_window = [e[1] for e in entries
                          if abs(e[0] - t_gen_start) <= 30.0 and e[1] is not None]
            at_gen_start = sum(gen_window) / len(gen_window) if gen_window else float('nan')
        else:
            at_gen_start = float('nan')

        # Check if value is descending after generator start
        if t_gen_start:
            post_vals = [e[1] for e in entries if e[0] > t_gen_start and e[1] is not None]
        else:
            post_vals = vals
        descending = "YES" if (len(post_vals) > 2
                               and post_vals[-1] < post_vals[0]
                               and (post_vals[0] - post_vals[-1]) > 1.0) else "no"

        print(f"{mode:>6} {pid_hex:>8}  {len(entries):>7}  {mean_val:>10.2f}  {min_val:>10.2f}"
              f"  {max_val:>10.2f}  {at_start:>10.2f}  {at_gen_start:>10.2f}"
              f"  {descending:>12}  {name}")


if __name__ == "__main__":
    main()
