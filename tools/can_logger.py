#!/usr/bin/env python3
"""Multi-device CAN logger with BUSMASTER format output.

Automatically detects and logs from all connected CAN interfaces simultaneously.
Supports: ixxat, kvaser, pcan, socketcan

Usage:
    python tools/can_logger.py
    python tools/can_logger.py --output my_capture.log
    python tools/can_logger.py --bitrate 250000
"""
import argparse
import datetime
import logging
import signal
import sys
import threading
import time
from pathlib import Path
from queue import Queue, Empty

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import can
from canre.live.receiver import CANBusLogger, detect_all_can_interfaces

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress python-can debug noise unless we want it
can_logger = logging.getLogger('can')
can_logger.setLevel(logging.WARNING)


class BUSMASTERWriter:
    """Writes CAN messages to BUSMASTER log format."""

    HEADER = """***BUSMASTER Ver 3.2.2***
***PROTOCOL CAN***
***NOTE: PLEASE DO NOT EDIT THIS DOCUMENT***
***[START LOGGING SESSION]***
***START DATE AND TIME {datetime}***
***HEX***
***SYSTEM MODE***
***START CHANNEL BAUD RATE***
{channel_info}
***END CHANNEL BAUD RATE***
***START DATABASE FILES***
***END DATABASE FILES***
***<Time><Tx/Rx><Channel><CAN ID><Type><DLC><DataBytes>***
"""

    def __init__(self, filepath, num_buses, bitrate):
        self.filepath = Path(filepath)
        self.num_buses = num_buses
        self.bitrate = bitrate
        self.file = None
        self.message_count = 0

    def __enter__(self):
        self.file = open(self.filepath, 'w', encoding='utf-8')
        self._write_header()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.file:
            self._write_footer()
            self.file.close()
            logger.info(f"Wrote {self.message_count} messages to {self.filepath}")

    def _write_header(self):
        """Write BUSMASTER log file header."""
        now = datetime.datetime.now()
        datetime_str = now.strftime("%d:%m:%Y %H:%M:%S:%f")[:-3]  # milliseconds

        channel_lines = []
        for i in range(1, self.num_buses + 1):
            channel_lines.append(f"***CHANNEL {i} - Kvaser - {self.bitrate} bps***")
        channel_info = "\n".join(channel_lines)

        header = self.HEADER.format(
            datetime=datetime_str,
            channel_info=channel_info
        )
        self.file.write(header)
        self.file.flush()

    def _write_footer(self):
        """Write BUSMASTER log file footer."""
        now = datetime.datetime.now()
        datetime_str = now.strftime("%d:%m:%Y %H:%M:%S:%f")[:-3]
        footer = f"***END DATE AND TIME {datetime_str}***\n"
        footer += "***[STOP LOGGING SESSION]***\n"
        self.file.write(footer)

    def write_message(self, timestamp, bus_id, msg, direction="Rx"):
        """Write a single CAN message in BUSMASTER format.

        Format: <Time><Tx/Rx><Channel><CAN ID><Type><DLC><DataBytes>
        Example: 09:42:13:4523 Rx 1 0x123 s 8 01 02 03 04 05 06 07 08
        """
        # Convert timestamp (seconds) to HH:MM:SS:TTTT format
        # TTTT = 10kHz ticks (0.1ms resolution)
        hours = int(timestamp // 3600)
        minutes = int((timestamp % 3600) // 60)
        seconds = int(timestamp % 60)
        ticks = int((timestamp % 1.0) * 10000)  # 10kHz ticks

        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}:{ticks:04d}"

        channel = bus_id + 1
        can_id = f"0x{msg.arbitration_id:X}"
        msg_type = "x" if msg.is_extended_id else "s"
        dlc = msg.dlc
        data_str = " ".join(f"{b:02X}" for b in msg.data)

        line = f"{time_str} {direction} {channel} {can_id} {msg_type} {dlc} {data_str}\n"
        self.file.write(line)
        self.message_count += 1

        if self.message_count % 1000 == 0:
            self.file.flush()


def main():
    parser = argparse.ArgumentParser(
        description='Multi-device CAN logger with BUSMASTER format'
    )
    parser.add_argument(
        '--output', '-o',
        default=None,
        help='Output log file path. If a bare filename (no directory), '
             'it is placed in --output-dir. Default: auto-generated timestamp name.'
    )
    parser.add_argument(
        '--output-dir', '-d',
        default=None,
        help='Directory for output log files. Used when --output is a bare filename '
             'or when no --output is given. Default: project root (parent of tools/).'
    )
    parser.add_argument(
        '--bitrate', '-b',
        type=int,
        default=500000,
        help='CAN bitrate in bps (default: 500000)'
    )
    parser.add_argument(
        '--brands',
        default=None,
        help='Comma-separated list of dongle brands to capture from '
             '(e.g. kvaser or ixxat,kvaser). Default: auto-detect all brands.'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)
        can_logger.setLevel(logging.DEBUG)

    # Resolve output directory: explicit arg > vehicle detection > project root
    project_root = Path(__file__).parent.parent
    _vehicle_dirs = {
        'vtrux': project_root / 'projects' / 'vtrux' / 'logs',
        'coda':  project_root / 'projects' / 'coda'  / 'logs',
    }

    if args.output_dir is not None:
        output_dir = Path(args.output_dir)
    else:
        output_dir = None  # resolved below after filename is known

    # Generate default output filename if not specified
    if args.output is None:
        now = datetime.datetime.now()
        stem = f"canlog_{now.strftime('%Y%m%d_%H%M%S')}.log"
    else:
        stem = args.output

    # If output is a bare filename (no directory), detect vehicle from prefix
    output_path = Path(stem)
    if output_path.parent == Path('.'):
        if output_dir is None:
            lower = output_path.name.lower()
            for prefix, vdir in _vehicle_dirs.items():
                if lower.startswith(prefix):
                    output_dir = vdir
                    break
            else:
                output_dir = project_root
        args.output = output_dir / output_path
    else:
        # Caller supplied a path with a directory — use it as-is
        args.output = output_path

    logger.info("=" * 60)
    logger.info("Multi-device CAN Logger")
    logger.info("=" * 60)
    logger.info(f"Bitrate: {args.bitrate} bps")
    logger.info(f"Output: {args.output}")
    logger.info("")

    # Parse brands filter
    brands_filter = None
    if args.brands:
        brands_filter = {b.strip().lower() for b in args.brands.split(',')}
        logger.info(f"Brand filter: {', '.join(sorted(brands_filter))}")

    # Detect all CAN interfaces
    logger.info("Detecting CAN interfaces...")
    interfaces = detect_all_can_interfaces(args.bitrate, brands=brands_filter)

    if not interfaces:
        logger.error("No CAN interfaces detected!")
        logger.error("Please check:")
        logger.error("  - CAN devices are connected")
        logger.error("  - Drivers are installed")
        logger.error("  - python-can is properly configured")
        sys.exit(1)

    logger.info(f"Found {len(interfaces)} interface(s):")
    for i, (iface, ch, desc) in enumerate(interfaces):
        logger.info(f"  Bus {i}: {desc}")
    logger.info("")

    # Create buses
    buses = []
    message_queue = Queue()

    try:
        for bus_id, (iface, ch, desc) in enumerate(interfaces):
            try:
                if isinstance(ch, dict):
                    bus = can.interface.Bus(interface=iface, bitrate=args.bitrate, **ch)
                else:
                    bus = can.interface.Bus(interface=iface, channel=ch, bitrate=args.bitrate)
                bus_logger = CANBusLogger(bus_id, bus, message_queue, iface, ch, args.bitrate)
                buses.append(bus_logger)
                logger.info(f"Created bus {bus_id}: {desc}")
            except Exception as e:
                logger.error(f"Failed to create bus {bus_id} ({desc}): {e}")

        if not buses:
            logger.error("Failed to create any CAN buses!")
            sys.exit(1)

        # Set up signal handler for graceful shutdown
        shutdown_event = threading.Event()

        def signal_handler(sig, frame):
            logger.info("\nShutdown signal received...")
            shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start logging from all buses
        logger.info("")
        logger.info("Starting logging...")
        logger.info("Press Ctrl+C to stop")
        logger.info("")

        for bus_logger in buses:
            bus_logger.start()

        # Write messages to file
        with BUSMASTERWriter(args.output, len(buses), args.bitrate) as writer:
            last_status = time.time()

            while not shutdown_event.is_set():
                try:
                    timestamp, bus_id, msg, direction = message_queue.get(timeout=0.5)
                    writer.write_message(timestamp, bus_id, msg, direction)

                    now = time.time()
                    if now - last_status >= 5.0:
                        logger.info(f"Logged {writer.message_count} messages...")
                        last_status = now

                except Empty:
                    continue
                except Exception as e:
                    logger.error(f"Error writing message: {e}")

    finally:
        logger.info("")
        logger.info("Stopping buses...")
        for bus_logger in buses:
            bus_logger.stop()

    logger.info("")
    logger.info("=" * 60)
    logger.info("Logging complete")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
