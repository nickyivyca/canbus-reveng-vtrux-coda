#!/usr/bin/env python3
"""UDS/KWP2000 diagnostic interrogator.

Plugs into a vehicle CAN bus, scans all UDS addresses in a configurable range,
and fully interrogates every responding ECU: ECU identity (F1xx DIDs), service
support, all UDS 0x19 DTC subfunctions, and KWP2000 0x18 DTC groups.

Writes a structured JSON report and prints a human-readable summary.

Usage
-----
  py -3.12 tools/uds_interrogator.py
  py -3.12 tools/uds_interrogator.py --bitrate 500000 --output report.json
  py -3.12 tools/uds_interrogator.py --module 0x7E0
  py -3.12 tools/uds_interrogator.py --scan-range 0x700:0x7EF --no-kwp
"""

import argparse
import dataclasses
import datetime
import json
import logging
import sys
import time
from pathlib import Path

# Make sure the project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import can
from canre.live.receiver import detect_all_can_interfaces
from canre.uds.scanner import UDSScanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Suppress python-can noise unless debug mode
can_logger = logging.getLogger("can")
can_logger.setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# JSON serialisation helper
# ---------------------------------------------------------------------------

def _to_json_obj(obj):
    """Recursively convert dataclasses/sets to JSON-serialisable objects."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        d = {}
        for f in dataclasses.fields(obj):
            val = getattr(obj, f.name)
            # Format integer IDs as hex strings for readability
            if f.name in ("request_id", "response_id", "did", "service_id",
                          "group", "subfunction") and isinstance(val, int):
                d[f.name] = "0x%X" % val
            else:
                d[f.name] = _to_json_obj(val)
        return d
    if isinstance(obj, dict):
        return {k: _to_json_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_obj(i) for i in obj]
    if isinstance(obj, set):
        return [_to_json_obj(i) for i in sorted(obj)]
    return obj


# ---------------------------------------------------------------------------
# Console summary printer (ASCII only -- Windows cp1252 rule)
# ---------------------------------------------------------------------------

def _print_summary(result, output_path):
    print()
    print("=" * 60)
    print("UDS Interrogation Summary")
    print("=" * 60)
    print("Hardware  : %s" % result.hardware_description)
    print("Bitrate   : %d bps" % result.bitrate)
    print(
        "Scan range: 0x%03X - 0x%03X" % (
            result.scan_range_start, result.scan_range_end,
        )
    )
    elapsed = result.scan_end - result.scan_start
    print("Elapsed   : %.1f s" % elapsed)
    print("Modules   : %d found" % len(result.modules))
    print()

    if not result.modules:
        print("No UDS modules found in scan range.")
    else:
        for mod in result.modules:
            _print_module_summary(mod)

    if result.nonstandard_rx_ids:
        print("Non-standard response IDs observed:")
        for rx_id, req_id in sorted(result.nonstandard_rx_ids.items()):
            print("  0x%03X responded to request at 0x%03X" % (rx_id, req_id))
        print()

    print("Report written to: %s" % output_path)


def _print_module_summary(mod):
    print("-" * 50)
    print(
        "Module 0x%03X -> 0x%03X%s" % (
            mod.request_id,
            mod.response_id,
            " [non-standard rx]" if mod.is_nonstandard_response else "",
        )
    )
    ext = "yes" if mod.session_extended else "no"
    print("  Extended session  : %s" % ext)

    # ECU info highlights
    vin_r = mod.dids.get("0xF190")
    if vin_r and vin_r.responded:
        print("  VIN               : %s" % (vin_r.value or vin_r.raw))
    sw_r = mod.dids.get("0xF188")
    if sw_r and sw_r.responded:
        print("  SW number         : %s" % (sw_r.value or sw_r.raw))
    hw_r = mod.dids.get("0xF191")
    if hw_r and hw_r.responded:
        print("  HW number         : %s" % (hw_r.value or hw_r.raw))

    # Service support summary
    supported = [
        k for k, v in mod.service_probes.items() if v.supported
    ]
    if supported:
        print("  Services supported: %s" % ", ".join(supported))

    # DTC summary
    dtc_hits = [
        (k, v) for k, v in mod.dtc_results.items()
        if v.responded and v.dtc_count > 0
    ]
    if dtc_hits:
        print("  UDS DTCs found:")
        for key, r in dtc_hits:
            print("    %s: %d DTC(s) -- %s" % (key, r.dtc_count, r.dtcs))
    else:
        responded_dtc = sum(1 for v in mod.dtc_results.values() if v.responded)
        if responded_dtc:
            print("  UDS DTC queries responded, no faults stored")
        elif mod.dtc_results:
            print("  UDS DTC queries: no response (service not supported)")

    kwp_hits = [
        (k, v) for k, v in mod.kwp_dtc_results.items()
        if v.responded and v.dtc_count > 0
    ]
    if kwp_hits:
        print("  KWP DTCs found:")
        for key, r in kwp_hits:
            print("    %s: %d DTC(s) -- %s" % (key, r.dtc_count, r.dtcs))
    elif mod.kwp_dtc_results:
        responded_kwp = sum(1 for v in mod.kwp_dtc_results.values() if v.responded)
        if responded_kwp:
            print("  KWP DTC queries responded, no faults stored")
        else:
            print("  KWP DTC queries: no response (service not supported)")

    t_elapsed = mod.interrogation_end - mod.interrogation_start
    print("  Interrogation time: %.1f s" % t_elapsed)
    print()


# ---------------------------------------------------------------------------
# Interface selection
# ---------------------------------------------------------------------------

def _select_interface(interfaces):
    """If multiple interfaces found, prompt user to select one.

    Returns (iface, ch, desc) tuple.
    """
    if len(interfaces) == 1:
        return interfaces[0]

    print("Multiple CAN interfaces found:")
    for i, (iface, ch, desc) in enumerate(interfaces):
        print("  [%d] %s" % (i, desc))
    while True:
        try:
            choice = input("Select interface [0-%d]: " % (len(interfaces) - 1))
            idx = int(choice.strip())
            if 0 <= idx < len(interfaces):
                return interfaces[idx]
        except (ValueError, KeyboardInterrupt):
            pass
        print("Invalid selection, try again.")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args():
    parser = argparse.ArgumentParser(
        description="UDS/KWP2000 diagnostic scanner and interrogator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--bitrate", "-b",
        type=int,
        default=500000,
        help="CAN bitrate in bps (default: 500000)",
    )
    parser.add_argument(
        "--brands",
        default=None,
        help="Comma-separated dongle brands to use "
             "(e.g. ixxat or ixxat,kvaser). Default: all detected.",
    )
    parser.add_argument(
        "--scan-range",
        default="0x600:0x7EF",
        metavar="START:END",
        help="Hex address range to scan, e.g. 0x600:0x7EF (default: 0x600:0x7EF)",
    )
    parser.add_argument(
        "--scan-timeout",
        type=int,
        default=50,
        metavar="MS",
        help="Per-address timeout in ms during scan (default: 50)",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=200,
        metavar="MS",
        help="Per-request timeout in ms during interrogation (default: 200)",
    )
    parser.add_argument(
        "--module",
        default=None,
        metavar="ADDR",
        help="Skip scan; interrogate only this hex address (e.g. 0x7E0)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="JSON output file path. Default: auto-named in --output-dir.",
    )
    parser.add_argument(
        "--output-dir", "-d",
        default=None,
        help="Directory for auto-named output file. Default: project root.",
    )
    parser.add_argument(
        "--no-kwp",
        action="store_true",
        help="Skip KWP2000 0x18 DTC queries.",
    )
    parser.add_argument(
        "--no-dtc",
        action="store_true",
        help="Skip all DTC queries (0x19 and 0x18).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-module progress to stdout.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Output path resolution
# ---------------------------------------------------------------------------

def _resolve_output_path(args):
    project_root = Path(__file__).resolve().parent.parent
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        out_dir = project_root

    if args.output:
        p = Path(args.output)
        if p.parent == Path("."):
            return out_dir / p
        return p

    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return out_dir / ("uds_report_%s.json" % now)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = _parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        can_logger.setLevel(logging.DEBUG)
    elif args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    # Parse brands filter
    brands_filter = None
    if args.brands:
        brands_filter = {b.strip().lower() for b in args.brands.split(",")}
        logger.info("Brand filter: %s", ", ".join(sorted(brands_filter)))

    # Parse scan range
    scan_start_id = 0x600
    scan_end_id = 0x7EF
    if args.scan_range:
        parts = args.scan_range.split(":")
        if len(parts) != 2:
            print("ERROR: --scan-range must be START:END e.g. 0x600:0x7EF")
            sys.exit(1)
        try:
            scan_start_id = int(parts[0], 0)
            scan_end_id = int(parts[1], 0)
        except ValueError:
            print("ERROR: invalid --scan-range values: %s" % args.scan_range)
            sys.exit(1)

    # Parse single-module override
    module_addr = None
    if args.module:
        try:
            module_addr = int(args.module, 0)
        except ValueError:
            print("ERROR: invalid --module address: %s" % args.module)
            sys.exit(1)

    # Resolve output path
    output_path = _resolve_output_path(args)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Detect interfaces
    logger.info("Detecting CAN interfaces (bitrate=%d)...", args.bitrate)
    interfaces = detect_all_can_interfaces(args.bitrate, brands=brands_filter)
    if not interfaces:
        print("ERROR: No CAN interfaces detected.")
        print("  - Check that your CAN dongle is connected and drivers installed.")
        sys.exit(1)

    logger.info("Found %d interface(s):", len(interfaces))
    for i, (iface, ch, desc) in enumerate(interfaces):
        logger.info("  [%d] %s", i, desc)

    iface, ch, desc = _select_interface(interfaces)
    logger.info("Using: %s", desc)

    # Open bus (reuse can_logger.py pattern)
    try:
        if isinstance(ch, dict):
            bus = can.interface.Bus(interface=iface, bitrate=args.bitrate, **ch)
        else:
            bus = can.interface.Bus(interface=iface, channel=ch, bitrate=args.bitrate)
    except Exception as e:
        print("ERROR: Failed to open CAN bus: %s" % e)
        sys.exit(1)

    try:
        scanner = UDSScanner(
            bus,
            scan_timeout=args.scan_timeout / 1000.0,
            request_timeout=args.request_timeout / 1000.0,
            verbose=args.verbose,
            skip_kwp=args.no_kwp,
            skip_dtc=args.no_dtc,
            hardware_description=desc,
            bitrate=args.bitrate,
        )

        if module_addr is not None:
            # Single-module interrogation: build a minimal ScanResult manually
            logger.info("Single-module mode: interrogating 0x%03X", module_addr)
            mod = scanner._interrogate(module_addr, module_addr + 8, False)
            from canre.uds.scanner import ScanResult
            t_now = time.time()
            result = ScanResult(
                scan_start=t_now,
                scan_end=t_now,
                bitrate=args.bitrate,
                hardware_description=desc,
                scan_range_start=module_addr,
                scan_range_end=module_addr,
                modules=[mod],
                nonstandard_rx_ids={},
            )
        else:
            result = scanner.scan_and_interrogate(
                start=scan_start_id,
                end=scan_end_id,
            )
    finally:
        bus.shutdown()

    # Write JSON report
    report = {
        "generated_at": datetime.datetime.now().isoformat(),
        "hardware": result.hardware_description,
        "bitrate": result.bitrate,
        "scan_range": {
            "start": "0x%03X" % result.scan_range_start,
            "end": "0x%03X" % result.scan_range_end,
        },
        "scan_duration_s": round(result.scan_end - result.scan_start, 2),
        "modules_found": len(result.modules),
        "modules": [_to_json_obj(m) for m in result.modules],
        "nonstandard_rx_ids": {
            "0x%03X" % k: "0x%03X" % v
            for k, v in result.nonstandard_rx_ids.items()
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info("Report written: %s", output_path)

    _print_summary(result, output_path)


if __name__ == "__main__":
    main()
