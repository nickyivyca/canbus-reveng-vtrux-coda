#!/usr/bin/env python3
"""Cowork-driven CAN replay tool for CODACAN signal discovery.

Designed for use with Claude Cowork — Anthropic's computer-use agent — to
autonomously map CODACAN display fields to CAN IDs, byte positions, and scalings.

Modes:
    baseline    Replay entire log at original timing. All CODACAN fields populate.
    drop-id     Replay log minus one specific ID. See what disappears.
    solo-id     Replay ONLY specified ID(s). See what appears.
    sweep-byte  Replay background traffic normally; sweep one byte of target ID.
    inject      Send a single crafted frame on repeat.

All modes write a cowork_state.json file that Cowork polls to coordinate
screenshots with the current experiment state.

Usage:
    python tools/cowork_replay.py baseline capture.log --brands ixxat
    python tools/cowork_replay.py drop-id capture.log --target 0x275
    python tools/cowork_replay.py solo-id capture.log --target 0x1D5,0x48A
    python tools/cowork_replay.py sweep-byte capture.log --target 0x275 --byte 2
    python tools/cowork_replay.py inject --id 0x275 --data "00 00 80 00 FF 00 00 00"
"""
import argparse
import json
import logging
import signal
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.parsers.autodetect import parse_file, detect_format

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# State file path — Cowork polls this to know current experiment state
STATE_FILE = Path("cowork_state.json")


# ---------------------------------------------------------------------------
# Hardware detection — imported from can_replayer pattern
# ---------------------------------------------------------------------------

def detect_all_can_interfaces(bitrate, brands=None):
    """Detect all available CAN interfaces.

    Returns list of (interface, channel_spec, description) tuples.
    """
    import can

    interfaces = []

    if brands is None or 'ixxat' in brands:
        try:
            from can.interfaces.ixxat import get_ixxat_hwids
            hwids = get_ixxat_hwids()
            for hwid in hwids:
                try:
                    channel_spec = {'channel': 0, 'unique_hardware_id': hwid}
                    bus = can.interface.Bus(interface='ixxat', bitrate=bitrate, **channel_spec)
                    bus.shutdown()
                    interfaces.append(('ixxat', channel_spec, f'ixxat {hwid}'))
                    logger.info(f"Detected ixxat {hwid}")
                except Exception as e:
                    logger.debug(f"ixxat {hwid}: {e}")
        except ImportError:
            logger.warning("ixxat interface not available")
        except Exception as e:
            logger.debug(f"ixxat enumeration failed: {e}")

    if brands is None or 'kvaser' in brands:
        for ch in range(8):
            try:
                bus = can.interface.Bus(interface='kvaser', channel=ch, bitrate=bitrate)
                channel_info = str(bus.channel_info) if hasattr(bus, 'channel_info') else ''
                bus.shutdown()
                if 'Virtual' in channel_info or 'virtual' in channel_info:
                    continue
                interfaces.append(('kvaser', ch, f'kvaser channel {ch}'))
                logger.info(f"Detected kvaser channel {ch}")
            except Exception:
                pass

    if brands is None or 'pcan' in brands:
        for ch in ['PCAN_USBBUS1', 'PCAN_USBBUS2', 'PCAN_USBBUS3', 'PCAN_USBBUS4']:
            try:
                bus = can.interface.Bus(interface='pcan', channel=ch, bitrate=bitrate)
                bus.shutdown()
                interfaces.append(('pcan', ch, f'pcan {ch}'))
                logger.info(f"Detected pcan {ch}")
            except Exception:
                pass

    if brands is None or 'socketcan' in brands:
        for ch in ['can0', 'can1', 'can2', 'can3']:
            try:
                bus = can.interface.Bus(interface='socketcan', channel=ch, bitrate=bitrate)
                bus.shutdown()
                interfaces.append(('socketcan', ch, f'socketcan {ch}'))
                logger.info(f"Detected socketcan {ch}")
            except Exception:
                pass

    return interfaces


def open_bus(interface_tuple, bitrate):
    """Open a single CAN interface. Returns a python-can Bus object."""
    import can

    iface, ch, desc = interface_tuple
    if isinstance(ch, dict):
        bus = can.interface.Bus(interface=iface, bitrate=bitrate, **ch)
    else:
        bus = can.interface.Bus(interface=iface, channel=ch, bitrate=bitrate)
    logger.info(f"Opened {desc}")
    return bus


# ---------------------------------------------------------------------------
# State file management
# ---------------------------------------------------------------------------

def write_state(state_dict):
    """Write current experiment state to cowork_state.json."""
    state_dict['timestamp'] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state_dict, indent=2))


def clear_state():
    """Remove state file."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()


# ---------------------------------------------------------------------------
# Frame helpers
# ---------------------------------------------------------------------------

def parse_target_ids(target_str):
    """Parse comma-separated hex IDs like '0x1D5,0x48A' into a set of ints."""
    ids = set()
    for part in target_str.split(','):
        part = part.strip()
        ids.add(int(part, 16) if part.startswith('0x') or part.startswith('0X') else int(part))
    return ids


def parse_data_hex(data_str):
    """Parse hex data string like '00 FF 80 12 00 00 00 00' into bytes."""
    parts = data_str.replace(',', ' ').split()
    return bytes(int(b, 16) for b in parts)


def parse_byte_range(byte_str):
    """Parse byte spec like '2' or '2-3' into (start_index, count).

    Returns (start, count) where start is 0-based byte index.
    """
    if '-' in byte_str:
        lo, hi = byte_str.split('-', 1)
        lo, hi = int(lo), int(hi)
        return lo, hi - lo + 1
    else:
        return int(byte_str), 1


def compute_median_frame(frames, target_id):
    """Compute the median data for a target ID from captured frames.

    Returns (median_data_bytes, frame_count, avg_interval_sec).
    """
    matching = [f for f in frames if f.arbitration_id == target_id]
    if not matching:
        return None, 0, 0.0

    dlc = matching[0].dlc
    median_data = bytearray(dlc)
    for byte_idx in range(dlc):
        values = [f.data[byte_idx] for f in matching if len(f.data) > byte_idx]
        if values:
            median_data[byte_idx] = int(statistics.median(values))

    if len(matching) > 1:
        intervals = [matching[i+1].timestamp - matching[i].timestamp
                     for i in range(len(matching) - 1)]
        avg_interval = statistics.mean(intervals)
    else:
        avg_interval = 0.1  # default 100ms if only one frame

    return bytes(median_data), len(matching), avg_interval


# ---------------------------------------------------------------------------
# Transmit helpers
# ---------------------------------------------------------------------------

def send_frame(bus, arb_id, data, is_extended=False):
    """Send a single CAN frame."""
    import can
    msg = can.Message(
        arbitration_id=arb_id,
        data=data,
        is_extended_id=is_extended,
        dlc=len(data),
        is_remote_frame=False,
    )
    bus.send(msg)


# ---------------------------------------------------------------------------
# Mode: baseline
# ---------------------------------------------------------------------------

def run_baseline(frames, bus, speed, loop, abort):
    """Replay entire log faithfully."""
    write_state({"mode": "baseline", "status": "running", "total_frames": len(frames)})

    pass_num = 0
    total_tx = 0
    while not abort.is_set():
        pass_num += 1
        logger.info(f"Baseline pass {pass_num} ({len(frames):,} frames)...")

        start_wall = time.perf_counter()
        log_start = frames[0].timestamp
        tx = 0

        for frame in frames:
            if abort.is_set():
                break
            if speed > 0:
                target = (frame.timestamp - log_start) / speed
                actual = time.perf_counter() - start_wall
                delay = target - actual
                if delay > 0:
                    time.sleep(delay)

            send_frame(bus, frame.arbitration_id, frame.data, frame.is_extended)
            tx += 1

        total_tx += tx
        write_state({"mode": "baseline", "status": "running",
                      "pass": pass_num, "frames_sent": total_tx})

        if not loop:
            break

    write_state({"mode": "baseline", "status": "done",
                  "passes": pass_num, "frames_sent": total_tx})
    return total_tx


# ---------------------------------------------------------------------------
# Mode: drop-id
# ---------------------------------------------------------------------------

def run_drop_id(frames, bus, speed, loop, abort, drop_ids):
    """Replay log minus specified IDs."""
    filtered = [f for f in frames if f.arbitration_id not in drop_ids]
    dropped_count = len(frames) - len(filtered)

    ids_hex = ', '.join(f'0x{i:03X}' for i in sorted(drop_ids))
    logger.info(f"Drop-ID mode: dropping {ids_hex} ({dropped_count:,} frames removed, "
                f"{len(filtered):,} remain)")

    write_state({"mode": "drop-id", "status": "running",
                  "dropped_ids": [f'0x{i:03X}' for i in sorted(drop_ids)],
                  "frames_dropped": dropped_count,
                  "frames_remaining": len(filtered)})

    if not filtered:
        logger.warning("No frames remain after filtering!")
        write_state({"mode": "drop-id", "status": "done", "frames_sent": 0})
        return 0

    pass_num = 0
    total_tx = 0
    while not abort.is_set():
        pass_num += 1
        logger.info(f"Drop-ID pass {pass_num}...")

        start_wall = time.perf_counter()
        log_start = filtered[0].timestamp
        tx = 0

        for frame in filtered:
            if abort.is_set():
                break
            if speed > 0:
                target = (frame.timestamp - log_start) / speed
                actual = time.perf_counter() - start_wall
                delay = target - actual
                if delay > 0:
                    time.sleep(delay)

            send_frame(bus, frame.arbitration_id, frame.data, frame.is_extended)
            tx += 1

        total_tx += tx
        if not loop:
            break

    write_state({"mode": "drop-id", "status": "done",
                  "dropped_ids": [f'0x{i:03X}' for i in sorted(drop_ids)],
                  "passes": pass_num, "frames_sent": total_tx})
    return total_tx


# ---------------------------------------------------------------------------
# Mode: solo-id
# ---------------------------------------------------------------------------

def run_solo_id(frames, bus, speed, loop, abort, solo_ids):
    """Replay ONLY frames matching specified IDs."""
    filtered = [f for f in frames if f.arbitration_id in solo_ids]

    ids_hex = ', '.join(f'0x{i:03X}' for i in sorted(solo_ids))
    logger.info(f"Solo-ID mode: playing only {ids_hex} ({len(filtered):,} frames)")

    write_state({"mode": "solo-id", "status": "running",
                  "solo_ids": [f'0x{i:03X}' for i in sorted(solo_ids)],
                  "frames_matching": len(filtered)})

    if not filtered:
        logger.warning(f"No frames match IDs {ids_hex} in this log!")
        write_state({"mode": "solo-id", "status": "done", "frames_sent": 0})
        return 0

    pass_num = 0
    total_tx = 0
    while not abort.is_set():
        pass_num += 1
        logger.info(f"Solo-ID pass {pass_num}...")

        start_wall = time.perf_counter()
        log_start = filtered[0].timestamp
        tx = 0

        for frame in filtered:
            if abort.is_set():
                break
            if speed > 0:
                target = (frame.timestamp - log_start) / speed
                actual = time.perf_counter() - start_wall
                delay = target - actual
                if delay > 0:
                    time.sleep(delay)

            send_frame(bus, frame.arbitration_id, frame.data, frame.is_extended)
            tx += 1

        total_tx += tx
        if not loop:
            break

    write_state({"mode": "solo-id", "status": "done",
                  "solo_ids": [f'0x{i:03X}' for i in sorted(solo_ids)],
                  "passes": pass_num, "frames_sent": total_tx})
    return total_tx


# ---------------------------------------------------------------------------
# Mode: sweep-byte
# ---------------------------------------------------------------------------

def run_sweep_byte(frames, bus, speed, abort, target_id, byte_start, byte_count,
                   dwell, step_size):
    """Replay background traffic while sweeping byte(s) of target ID.

    Background frames replay at original timing in a loop. The target ID is
    replaced with a synthetic frame where the sweep byte(s) step through their
    range. Each step is held for `dwell` seconds.
    """
    median_data, frame_count, avg_interval = compute_median_frame(frames, target_id)
    if median_data is None:
        logger.error(f"Target ID 0x{target_id:03X} not found in log!")
        return 0

    dlc = len(median_data)
    logger.info(f"Sweep-byte: target 0x{target_id:03X}, DLC={dlc}, "
                f"byte{'s' if byte_count > 1 else ''} {byte_start}"
                f"{f'-{byte_start + byte_count - 1}' if byte_count > 1 else ''}, "
                f"median data={median_data.hex(' ')}, "
                f"avg interval={avg_interval*1000:.0f}ms, "
                f"dwell={dwell}s, step={step_size}")

    # Compute sweep range
    if byte_count == 1:
        max_val = 256
    else:
        max_val = 1 << (8 * byte_count)

    sweep_values = list(range(0, max_val, step_size))
    total_steps = len(sweep_values)
    logger.info(f"Sweep range: 0x{0:0{byte_count*2}X} to "
                f"0x{sweep_values[-1]:0{byte_count*2}X} "
                f"in {total_steps} steps ({total_steps * dwell:.0f}s total)")

    # Separate background frames from target frames
    bg_frames = [f for f in frames if f.arbitration_id != target_id]

    write_state({"mode": "sweep-byte", "status": "running",
                  "target_id": f"0x{target_id:03X}",
                  "sweep_byte_start": byte_start,
                  "sweep_byte_count": byte_count,
                  "total_steps": total_steps,
                  "dwell_sec": dwell,
                  "median_data_hex": median_data.hex(' ')})

    total_tx = 0

    for step_idx, val in enumerate(sweep_values):
        if abort.is_set():
            break

        # Build the sweep frame
        sweep_data = bytearray(median_data)
        if byte_count == 1:
            sweep_data[byte_start] = val & 0xFF
        else:
            # Big-endian packing for multi-byte
            for i in range(byte_count):
                byte_pos = byte_start + i
                shift = 8 * (byte_count - 1 - i)
                sweep_data[byte_pos] = (val >> shift) & 0xFF

        data_hex = bytes(sweep_data).hex(' ')
        logger.info(f"  Step {step_idx+1}/{total_steps}: "
                     f"byte{'s' if byte_count > 1 else ''} "
                     f"= 0x{val:0{byte_count*2}X}  "
                     f"frame=[{data_hex}]")

        write_state({"mode": "sweep-byte", "status": "running",
                      "target_id": f"0x{target_id:03X}",
                      "sweep_byte_start": byte_start,
                      "sweep_byte_count": byte_count,
                      "current_value": val,
                      "current_value_hex": f"0x{val:0{byte_count*2}X}",
                      "step": step_idx + 1,
                      "total_steps": total_steps,
                      "frame_data_hex": data_hex,
                      "dwell_sec": dwell})

        # Transmit for the dwell period: interleave background + target
        dwell_start = time.perf_counter()
        bg_idx = 0

        while time.perf_counter() - dwell_start < dwell and not abort.is_set():
            # Send the sweep frame at the target's original rate
            send_frame(bus, target_id, bytes(sweep_data))
            total_tx += 1

            # Interleave some background frames to keep other CODACAN fields alive
            if bg_frames:
                bg_burst_end = time.perf_counter() + avg_interval
                while time.perf_counter() < bg_burst_end and bg_idx < len(bg_frames):
                    if abort.is_set():
                        break
                    f = bg_frames[bg_idx % len(bg_frames)]
                    send_frame(bus, f.arbitration_id, f.data, f.is_extended)
                    total_tx += 1
                    bg_idx += 1
                    # Small inter-frame gap
                    time.sleep(0.001)
            else:
                time.sleep(avg_interval)

    write_state({"mode": "sweep-byte", "status": "done",
                  "target_id": f"0x{target_id:03X}",
                  "sweep_byte_start": byte_start,
                  "sweep_byte_count": byte_count,
                  "steps_completed": min(step_idx + 1, total_steps) if 'step_idx' in dir() else 0,
                  "total_steps": total_steps,
                  "frames_sent": total_tx})
    return total_tx


# ---------------------------------------------------------------------------
# Mode: inject
# ---------------------------------------------------------------------------

def run_inject(bus, abort, arb_id, data, interval, duration):
    """Send a single crafted frame on repeat."""
    data_hex = data.hex(' ')
    logger.info(f"Inject: 0x{arb_id:03X} [{data_hex}] every {interval*1000:.0f}ms"
                f"{f' for {duration}s' if duration else ' (indefinite, Ctrl+C to stop)'}")

    write_state({"mode": "inject", "status": "running",
                  "id": f"0x{arb_id:03X}",
                  "data_hex": data_hex,
                  "interval_ms": interval * 1000})

    tx = 0
    start = time.perf_counter()
    while not abort.is_set():
        if duration and (time.perf_counter() - start) >= duration:
            break
        send_frame(bus, arb_id, data)
        tx += 1
        time.sleep(interval)

    write_state({"mode": "inject", "status": "done",
                  "id": f"0x{arb_id:03X}",
                  "frames_sent": tx})
    return tx


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------

def dry_run_summary(frames, mode, args):
    """Print what would happen without requiring hardware."""
    unique_ids = sorted(set(f.arbitration_id for f in frames))
    duration = frames[-1].timestamp - frames[0].timestamp if len(frames) > 1 else 0

    print()
    print("=" * 60)
    print(f"DRY RUN — {mode}")
    print("=" * 60)
    print(f"Frames:     {len(frames):,}")
    print(f"Unique IDs: {len(unique_ids)}")
    print(f"Duration:   {duration:.1f}s")
    print()
    print("IDs in log:")
    for aid in unique_ids:
        count = sum(1 for f in frames if f.arbitration_id == aid)
        freq = count / duration if duration > 0 else 0
        print(f"  0x{aid:03X}  {count:>6,} frames  ({freq:>6.1f} Hz)")
    print()

    if mode == 'drop-id' and hasattr(args, 'target') and args.target:
        drop_ids = parse_target_ids(args.target)
        remaining = sum(1 for f in frames if f.arbitration_id not in drop_ids)
        print(f"Would drop: {', '.join(f'0x{i:03X}' for i in sorted(drop_ids))}")
        print(f"Frames remaining: {remaining:,}")

    elif mode == 'solo-id' and hasattr(args, 'target') and args.target:
        solo_ids = parse_target_ids(args.target)
        matching = sum(1 for f in frames if f.arbitration_id in solo_ids)
        print(f"Would play only: {', '.join(f'0x{i:03X}' for i in sorted(solo_ids))}")
        print(f"Matching frames: {matching:,}")

    elif mode == 'sweep-byte' and hasattr(args, 'target') and args.target:
        target_id = parse_target_ids(args.target).pop()
        byte_start, byte_count = parse_byte_range(args.byte)
        median_data, fcount, avg_int = compute_median_frame(frames, target_id)
        if median_data:
            max_val = 1 << (8 * byte_count)
            steps = len(range(0, max_val, args.step))
            print(f"Target: 0x{target_id:03X} ({fcount:,} frames, {1/avg_int:.1f} Hz)")
            print(f"Median data: {median_data.hex(' ')}")
            print(f"Sweep byte{'s' if byte_count > 1 else ''}: "
                  f"{byte_start}{f'-{byte_start+byte_count-1}' if byte_count > 1 else ''}")
            print(f"Steps: {steps} (dwell {args.dwell}s each = {steps * args.dwell:.0f}s total)")
        else:
            print(f"Target 0x{target_id:03X} NOT FOUND in log!")

    print()
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description='Cowork-driven CAN replay for CODACAN signal discovery'
    )
    sub = parser.add_subparsers(dest='mode', required=True)

    # Common args added to each subparser
    def add_common(p, needs_log=True):
        if needs_log:
            p.add_argument('logfile', help='Path to CAN log file')
        p.add_argument('--bitrate', '-b', type=int, default=500000,
                       help='CAN bitrate (default: 500000)')
        p.add_argument('--brands', default=None,
                       help='Comma-separated dongle brands (e.g. ixxat,kvaser)')
        p.add_argument('--speed', '-s', type=float, default=1.0,
                       help='Replay speed multiplier (default: 1.0, 0=no delay)')
        p.add_argument('--dry-run', action='store_true',
                       help='Print summary without sending frames')
        p.add_argument('--no-wait', action='store_true',
                       help='Skip the "Press Enter to start" prompt')
        p.add_argument('--state-file', default='cowork_state.json',
                       help='Path to state file (default: cowork_state.json)')
        p.add_argument('--debug', action='store_true',
                       help='Enable debug logging')
        if needs_log:
            p.add_argument('--start-time', type=float, default=None, metavar='SEC',
                           help='Start offset in seconds from log beginning (skip earlier frames)')
            p.add_argument('--end-time', type=float, default=None, metavar='SEC',
                           help='End offset in seconds from log beginning (drop later frames)')

    # baseline
    p = sub.add_parser('baseline', help='Replay entire log faithfully')
    add_common(p)
    p.add_argument('--loop', '-l', action='store_true',
                   help='Loop replay indefinitely')

    # drop-id
    p = sub.add_parser('drop-id', help='Replay log minus specified ID(s)')
    add_common(p)
    p.add_argument('--target', '-t', required=True,
                   help='CAN ID(s) to drop (hex, comma-separated: 0x275 or 0x1D5,0x48A)')
    p.add_argument('--loop', '-l', action='store_true',
                   help='Loop replay indefinitely')

    # solo-id
    p = sub.add_parser('solo-id', help='Replay ONLY specified ID(s)')
    add_common(p)
    p.add_argument('--target', '-t', required=True,
                   help='CAN ID(s) to play (hex, comma-separated: 0x275 or 0x1D5,0x48A)')
    p.add_argument('--loop', '-l', action='store_true',
                   help='Loop replay indefinitely')

    # sweep-byte
    p = sub.add_parser('sweep-byte', help='Sweep a byte of target ID while replaying background')
    add_common(p)
    p.add_argument('--target', '-t', required=True,
                   help='CAN ID to sweep (hex: 0x275)')
    p.add_argument('--byte', required=True,
                   help='Byte index or range to sweep (e.g. 2 or 2-3)')
    p.add_argument('--dwell', type=float, default=3.0,
                   help='Seconds to hold each sweep value (default: 3.0)')
    p.add_argument('--step', type=int, default=1,
                   help='Sweep step size (default: 1)')

    # inject
    p = sub.add_parser('inject', help='Send a crafted frame on repeat')
    add_common(p, needs_log=False)
    p.add_argument('--id', required=True,
                   help='CAN ID to inject (hex: 0x275)')
    p.add_argument('--data', '-d', required=True,
                   help='Frame data as hex bytes (e.g. "00 FF 80 12 00 00 00 00")')
    p.add_argument('--interval', type=float, default=0.1,
                   help='Interval between frames in seconds (default: 0.1)')
    p.add_argument('--duration', type=float, default=None,
                   help='Total duration in seconds (default: indefinite)')

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    global STATE_FILE
    STATE_FILE = Path(args.state_file)

    if args.debug:
        logger.setLevel(logging.DEBUG)

    # Parse brands filter
    brands_filter = None
    if args.brands:
        brands_filter = {b.strip().lower() for b in args.brands.split(',')}

    # Load frames (not needed for inject)
    frames = None
    if args.mode != 'inject':
        logfile = Path(args.logfile)
        if not logfile.exists():
            logger.error(f"Log file not found: {logfile}")
            sys.exit(1)

        logger.info(f"Loading {logfile}...")
        try:
            detect_format(logfile)
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)

        frames = list(parse_file(logfile))
        if not frames:
            logger.error("No frames found in log file.")
            sys.exit(1)

        logger.info(f"Loaded {len(frames):,} frames, "
                     f"{len(set(f.arbitration_id for f in frames))} unique IDs")

        # Apply time slice if requested
        start_time = getattr(args, 'start_time', None)
        end_time   = getattr(args, 'end_time', None)
        if start_time is not None or end_time is not None:
            t0 = frames[0].timestamp
            if start_time is not None:
                frames = [f for f in frames if f.timestamp - t0 >= start_time]
            if end_time is not None:
                frames = [f for f in frames if f.timestamp - t0 <= end_time]
            if not frames:
                logger.error(f"No frames in time slice [{start_time}s – {end_time}s].")
                sys.exit(1)
            logger.info(f"Time slice [{start_time or 0:.1f}s – {end_time or 'end'}s]: "
                        f"{len(frames):,} frames, "
                        f"{len(set(f.arbitration_id for f in frames))} unique IDs")

    # Dry run?
    if args.dry_run:
        if frames:
            dry_run_summary(frames, args.mode, args)
        else:
            print("Dry run: inject mode — nothing to summarize from log.")
        return

    # Detect and open hardware
    logger.info("Detecting CAN interfaces...")
    interfaces = detect_all_can_interfaces(args.bitrate, brands=brands_filter)
    if not interfaces:
        logger.error("No CAN interfaces detected!")
        sys.exit(1)

    # Use first dongle (we transmit on one bus wire)
    bus = open_bus(interfaces[0], args.bitrate)

    # Signal handling
    abort = threading.Event()

    def on_signal(sig, frame):
        logger.info("\nShutdown signal received...")
        abort.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    # Print summary and wait for Enter
    print()
    print("=" * 60)
    print(f"Cowork Replay — mode: {args.mode}")
    print("=" * 60)
    print(f"Dongle:  {interfaces[0][2]}")
    print(f"Bitrate: {args.bitrate:,} bps")
    if frames:
        unique_ids = set(f.arbitration_id for f in frames)
        duration = frames[-1].timestamp - frames[0].timestamp if len(frames) > 1 else 0
        print(f"Log:     {len(frames):,} frames, {len(unique_ids)} IDs, {duration:.1f}s")
    if args.mode in ('drop-id', 'solo-id', 'sweep-byte'):
        print(f"Target:  {args.target}")
    if args.mode == 'sweep-byte':
        print(f"Byte:    {args.byte}  (dwell={args.dwell}s, step={args.step})")
    if args.mode == 'inject':
        print(f"ID:      {args.id}")
        print(f"Data:    {args.data}")
        print(f"Rate:    {1/args.interval:.0f} Hz")
    print()
    if args.no_wait:
        print("Starting immediately (--no-wait)...")
    else:
        print("Press Enter to start, Ctrl+C to abort...")
    print("=" * 60)

    if not args.no_wait:
        try:
            input()
        except KeyboardInterrupt:
            bus.shutdown()
            clear_state()
            print("\nAborted.")
            return

    # Run the selected mode
    try:
        if args.mode == 'baseline':
            tx = run_baseline(frames, bus, args.speed, args.loop, abort)

        elif args.mode == 'drop-id':
            drop_ids = parse_target_ids(args.target)
            tx = run_drop_id(frames, bus, args.speed, args.loop, abort, drop_ids)

        elif args.mode == 'solo-id':
            solo_ids = parse_target_ids(args.target)
            tx = run_solo_id(frames, bus, args.speed, args.loop, abort, solo_ids)

        elif args.mode == 'sweep-byte':
            target_id = parse_target_ids(args.target).pop()
            byte_start, byte_count = parse_byte_range(args.byte)
            tx = run_sweep_byte(frames, bus, args.speed, abort, target_id,
                                byte_start, byte_count, args.dwell, args.step)

        elif args.mode == 'inject':
            arb_id = int(args.id, 16) if args.id.startswith('0x') else int(args.id)
            data = parse_data_hex(args.data)
            tx = run_inject(bus, abort, arb_id, data, args.interval, args.duration)

        else:
            logger.error(f"Unknown mode: {args.mode}")
            tx = 0

    finally:
        bus.shutdown()

    print()
    print("=" * 60)
    print(f"Done: {tx:,} frames transmitted")
    print("=" * 60)


if __name__ == '__main__':
    main()
