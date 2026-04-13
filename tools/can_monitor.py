#!/usr/bin/env python3
"""Live CAN monitor with vehicle-aware GUI.

Detects connected dongles, performs bus anchor detection, then opens a
PyQt5 window showing decoded signals in the appropriate vehicle mode layout.
Optionally writes a simultaneous BUSMASTER log file.

Usage:
    py -3.11 tools/can_monitor.py --vehicle coda [options]

Options:
    --vehicle, -v   Vehicle name: coda | vtrux  [required]
    --bitrate, -b   CAN bitrate in bps          (default: 500000)
    --brands        Comma-separated dongle brands to capture from
                    (default: auto-detect all)
    --output, -o    Optional BUSMASTER log file to write simultaneously
    --output-dir,-d Directory for auto-named log file
    --debug         Verbose logging
"""
import argparse
import datetime
import importlib.util
import logging
import sys
import time
from pathlib import Path
from queue import Empty, Queue

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import can

from canre.live.receiver import CANBusLogger, detect_all_can_interfaces
from canre.live.vehicle_configs import (
    DETECTION_WINDOW_S,
    VEHICLES,
    detect_bus_assignments,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("can").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_profile(vehicle: str, project_root: Path):
    """Import projects/<vehicle>/gui_profile.py and return its PROFILE instance."""
    profile_path = project_root / "projects" / vehicle / "gui_profile.py"
    if not profile_path.exists():
        logger.error(f"No GUI profile found: {profile_path}")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("gui_profile", profile_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "PROFILE"):
        logger.error(f"gui_profile.py for '{vehicle}' does not export a PROFILE instance.")
        sys.exit(1)
    return mod.PROFILE


def _resolve_output(args, project_root: Path, vehicle_cfg):
    """Return resolved output Path or None."""
    if args.output is None:
        if args.output_dir is None:
            return None
        output_dir = Path(args.output_dir)
    elif Path(args.output).parent == Path("."):
        output_dir = Path(args.output_dir) if args.output_dir else (
            project_root / vehicle_cfg.log_subdir if vehicle_cfg else project_root
        )
    else:
        return Path(args.output)

    if args.output is None:
        stem = f"canlog_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    else:
        stem = args.output

    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / stem


def _run_anchor_detection(message_queue: Queue, interfaces, sniff_s: float):
    """Collect observed IDs per channel for sniff_s seconds.

    Drains the queue during sniffing and returns:
        observed_ids  : {channel_id: set of seen arbitration IDs}
        buffered      : list of 4-tuples drained during sniff (to re-queue or replay)
    """
    observed_ids = {i: set() for i in range(len(interfaces))}
    buffered     = []
    deadline     = time.time() + sniff_s

    logger.info(f"Sniffing for {sniff_s:.0f}s to detect bus assignments...")
    while time.time() < deadline:
        try:
            item = message_queue.get(timeout=0.1)
            buffered.append(item)
            _ts, bus_id, msg, direction = item
            if direction == "Rx":
                observed_ids[bus_id].add(msg.arbitration_id)
        except Empty:
            continue

    return observed_ids, buffered


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Live CAN monitor with vehicle-aware GUI"
    )
    parser.add_argument("--vehicle", "-v", required=True,
                        help="Vehicle name: coda | vtrux")
    parser.add_argument("--bitrate", "-b", type=int, default=500000,
                        help="CAN bitrate in bps (default: 500000)")
    parser.add_argument("--brands", default=None,
                        help="Comma-separated dongle brands (e.g. ixxat,kvaser)")
    parser.add_argument("--output", "-o", default=None,
                        help="Optional BUSMASTER log file for simultaneous capture")
    parser.add_argument("--output-dir", "-d", default=None,
                        help="Directory for auto-named log file")
    parser.add_argument("--debug", action="store_true",
                        help="Verbose logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("can").setLevel(logging.DEBUG)

    project_root = Path(__file__).resolve().parent.parent

    # ---- Validate vehicle ----
    vehicle = args.vehicle.lower()
    vehicle_cfg = VEHICLES.get(vehicle)
    if vehicle_cfg is None:
        logger.error(f"Unknown vehicle '{vehicle}'. Known: {list(VEHICLES)}")
        sys.exit(1)

    # ---- Load GUI profile ----
    profile = _load_profile(vehicle, project_root)

    # ---- Brand filter ----
    brands_filter = None
    if args.brands:
        brands_filter = {b.strip().lower() for b in args.brands.split(",")}
        logger.info(f"Brand filter: {', '.join(sorted(brands_filter))}")

    # ---- Detect hardware ----
    logger.info("Detecting CAN interfaces...")
    interfaces = detect_all_can_interfaces(args.bitrate, brands=brands_filter)
    if not interfaces:
        logger.error("No CAN interfaces detected. Check connections and drivers.")
        sys.exit(1)

    logger.info(f"Found {len(interfaces)} interface(s):")
    for i, (_iface, _ch, desc) in enumerate(interfaces):
        logger.info(f"  Channel {i}: {desc}")

    # ---- Open buses and start receiver threads ----
    message_queue: Queue = Queue()
    bus_loggers = []

    try:
        for bus_id, (iface, ch, desc) in enumerate(interfaces):
            if isinstance(ch, dict):
                bus_obj = can.interface.Bus(interface=iface, bitrate=args.bitrate, **ch)
            else:
                bus_obj = can.interface.Bus(interface=iface, channel=ch, bitrate=args.bitrate)
            bl = CANBusLogger(bus_id, bus_obj, message_queue, iface, ch, args.bitrate)
            bus_loggers.append(bl)
            logger.info(f"Opened channel {bus_id}: {desc}")
    except Exception as exc:
        logger.error(f"Failed to open CAN interface: {exc}")
        for bl in bus_loggers:
            bl.stop()
        sys.exit(1)

    for bl in bus_loggers:
        bl.start()

    # ---- Anchor detection ----
    observed_ids, buffered = _run_anchor_detection(
        message_queue, interfaces, DETECTION_WINDOW_S
    )

    bus_assignments = detect_bus_assignments(vehicle_cfg, observed_ids)

    if bus_assignments:
        logger.info("Bus assignments:")
        for ch_id, bus_name in sorted(bus_assignments.items()):
            desc = vehicle_cfg.buses[bus_name].description
            logger.info(f"  Channel {ch_id} -> {bus_name}  ({desc})")
    else:
        logger.warning(
            "No bus assignments resolved (no anchor IDs seen during sniff window). "
            "GUI will show data but bus names will be unresolved."
        )

    # If no assignments, create a fallback: map channel 0 -> first bus name
    if not bus_assignments and interfaces:
        first_name = next(iter(vehicle_cfg.buses))
        bus_assignments = {0: first_name}
        logger.warning(f"Fallback: channel 0 -> '{first_name}'")

    # ---- Resolve output path (optional simultaneous log) ----
    output_path = _resolve_output(args, project_root, vehicle_cfg)
    writer = None

    # Import BUSMASTERWriter from can_logger if simultaneous logging is wanted
    if output_path is not None:
        try:
            from can_logger import BUSMASTERWriter
            writer = BUSMASTERWriter(output_path, len(interfaces), args.bitrate)
            writer.__enter__()
            logger.info(f"Simultaneous log: {output_path}")
        except Exception as exc:
            logger.warning(f"Could not open log file {output_path}: {exc}")
            writer = None

    # ---- Build BusDecoder ----
    from canre.gui.bus_decoder import BusDecoder
    decoder = BusDecoder(profile.dbc_paths, project_root)

    # Feed buffered frames (from sniff window) into decoder immediately
    for _ts, bus_id, msg, direction in buffered:
        bus_name = bus_assignments.get(bus_id)
        if bus_name and direction == "Rx":
            decoder.process(bus_name, msg.arbitration_id, bytes(msg.data))

    # Re-inject buffered frames into queue so the window also sees them
    for item in buffered:
        message_queue.put(item)

    # ---- Launch GUI ----
    from PyQt5.QtWidgets import QApplication
    from canre.gui.main_window import CANMonitorWindow

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = CANMonitorWindow(
        profile=profile,
        decoder=decoder,
        queue=message_queue,
        bus_assignments=bus_assignments,
        writer=writer,
    )
    window.show()

    exit_code = app.exec_()

    # ---- Cleanup ----
    logger.info("Stopping CAN receivers...")
    for bl in bus_loggers:
        bl.stop()

    if writer is not None:
        try:
            writer.__exit__(None, None, None)
        except Exception:
            pass

    logger.info("Done.")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
