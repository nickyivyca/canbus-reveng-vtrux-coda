#!/usr/bin/env python3
"""Upload CAN log data to InfluxDB 1.x for Grafana visualization.

Two measurements are written:
  signals  -- DBC-decoded signal values, one point per signal per frame
  raw      -- raw bytes for frames not in the DBC (only with --raw)

Each point carries a 'bus' tag (e.g. powertrain/vehicle/obd for Vtrux,
b_can/c_can/d_can for Coda) derived by matching anchor IDs to channel numbers.

Requires:  pip install influxdb cantools
"""
import argparse
import contextlib
import io
import queue
import re
import sys
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canre.parsers import parse_file

try:
    import cantools
except ImportError:
    cantools = None

try:
    from influxdb import InfluxDBClient
except ImportError:
    InfluxDBClient = None


# ---------------------------------------------------------------------------
# Vehicle profiles — hardcoded DBCs and bus anchor IDs
#
# bus_anchors: ordered list of (bus_name, {anchor_id, ...}).
#   A channel is assigned the name of the first anchor set that overlaps
#   with the IDs seen on that channel. Order matters — put the most
#   distinctive anchor first.
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

VEHICLE_PROFILES = {
    "vtrux": {
        "dbcs": [
            PROJECT_ROOT / "projects/vtrux/vtrux-powertrain.dbc",
            PROJECT_ROOT / "projects/vtrux/BelInverter.dbc",
            PROJECT_ROOT / "projects/vtrux/GMW8762_PPEI_GMLAN.dbc",
        ],
        # Powertrain: 0x051 is exclusive and fires at 100 Hz — most reliable anchor
        # Vehicle (Vehicle): 0x1E5/0x500 never appear on the other buses
        # OBD: 0x040-0x044 exclusive to OBD bus
        "bus_anchors": [
            ("powertrain", {0x051}),
            ("vehicle",    {0x1E5, 0x500}),
            ("obd",        {0x040, 0x041, 0x042, 0x043, 0x044}),
        ],
        # Exclusions: each entry is one of:
        #   {"signal": "Name", "bus": "..."}   -- exclude signal by name on a specific bus
        #   {"signal": "Name"}                 -- exclude signal on all buses
        #   {"can_id": 0xXXX, "bus": "..."}    -- exclude entire message on a specific bus
        #   {"can_id": 0xXXX}                  -- exclude entire message on all buses
        #
        # VCM gateway modifications (see notes/gmlan-signals-investigation.md):
        # OBD bus carries wrong/synthetic data for these IDs — real data is on Vehicle bus.
        # Vehicle bus carries wrong/synthetic data for these IDs — real data is on OBD bus.
        # Faithfully bridged IDs are excluded from the non-source bus to avoid duplicates.
        "exclude": [
            # --- OBD bus: VCM-modified or spoofed content (real data on Vehicle bus) ---
            {"can_id": 0x0C1, "bus": "obd"},  # Driven wheel speeds masked to all zeros
            {"can_id": 0x0C5, "bus": "obd"},  # Non-driven wheel speeds masked to all zeros
            {"can_id": 0x0F9, "bus": "obd"},  # TCM stub: torque ratio canned, shaft speed zero, B5-B7=0xFF
            {"can_id": 0x1C7, "bus": "obd"},  # EBCM torque requests frozen to constant (B0=0x07, B1=0x02)
            {"can_id": 0x1E9, "bus": "obd"},  # Chassis status fully frozen (all 8 bytes constant)
            {"can_id": 0x1F5, "bus": "obd"},  # Transmission position frozen at Park
            {"can_id": 0x3E9, "bus": "obd"},  # Vehicle speed frozen at zero (cascade: VCM masks wheel inputs to ECM)
            # EBCM messages faithfully bridged to OBD bus (source = Vehicle bus)
            {"can_id": 0x2F9, "bus": "obd"},  # EBCM reference -- identical on both buses; Vehicle is native
            {"can_id": 0x1CF, "bus": "obd"},  # TCCM/RDCM torque request -- identical on both; Vehicle is native
            # --- Vehicle bus: VCM-synthetic ECM content (real data on OBD bus) ---
            {"can_id": 0x0C9, "bus": "vehicle"},  # All ECM signals synthetic (~800 RPM motor idle, not real engine)
            {"can_id": 0x1C3, "bus": "vehicle"},  # Motor torque substituted for engine torque
            {"can_id": 0x1C5, "bus": "vehicle"},  # Axle torque reporting adjusted by VCM
            # ECM messages faithfully bridged to Vehicle bus (source = OBD bus)
            {"can_id": 0x3C1, "bus": "vehicle"},  # Engine_General_Status_6 -- identical on both; OBD is native
            {"can_id": 0x3F9, "bus": "vehicle"},  # Engine_General_Status_3 -- identical on both; OBD is native
            {"can_id": 0x3FB, "bus": "vehicle"},  # Engine_Torque_Status_1 -- identical on both; OBD is native
            {"can_id": 0x4D1, "bus": "vehicle"},  # Engine_Torque_Status_5 -- identical on both; OBD is native
            # --- Vehicle bus: high-rate messages not useful for EV analysis ---
            {"can_id": 0x0C1, "bus": "vehicle"},  # Wheel distance accumulators (10-bit rollover counters, not graphable speed; use 0x3E9 for vehicle speed)
            {"can_id": 0x0C5, "bus": "vehicle"},  # Non-driven wheel distance accumulators -- same
            {"can_id": 0x1E5, "bus": "vehicle"},  # Steering wheel angle -- not used in Vtrux analysis
            {"can_id": 0x1C4, "bus": "vehicle"},  # Accelerator pedal override -- irrelevant for EV drivetrain
            {"can_id": 0x1C4, "bus": "obd"},      # Same message bridged to OBD
            {"can_id": 0x1F1, "bus": "vehicle"},  # A/C + fuel flags -- faithfully bridged; keep OBD copy
            {"can_id": 0x2C3, "bus": "vehicle"},  # Engine MAP/max torque -- B3 frozen on Vehicle; keep OBD copy
            {"can_id": 0x3D1, "bus": "vehicle"},  # TPS/DFCO/A/C cmd -- B3 frozen on Vehicle; keep OBD copy
            # --- OBD 0x0C9: trim to the 6 signals we use; exclude the other 18 ---
            # Kept: Engine_Speed, Engine_Run_Active, Engine_Idle_Active, Cruise_Control_Active,
            #       Accelerator_Actual_Position, Accelerator_Actual_Position_Validity
            {"signal": "Cruise_Control_Enabled",                                "bus": "obd"},
            {"signal": "Driver_Throttle_Override_Detected",                     "bus": "obd"},
            {"signal": "Driver_Throttle_Override_Detected_Protection_Value",    "bus": "obd"},
            {"signal": "Driver_Throttle_Override_Detection_Alive_Rolling_Count","bus": "obd"},
            {"signal": "Engine_Cylinder_Deactivation_Event_Pending",            "bus": "obd"},
            {"signal": "Engine_Cylinder_Deactivation_Mode",                     "bus": "obd"},
            {"signal": "Engine_Intake_Air_Boost_Pressure",                      "bus": "obd"},
            {"signal": "Engine_Intake_Air_Boost_Pressure_Validity",             "bus": "obd"},
            {"signal": "Engine_Speed_Status",                                   "bus": "obd"},
            {"signal": "Platform_Engine_Speed_Command_Inhibit_Request",         "bus": "obd"},
            {"signal": "Platform_Engine_Speed_Command_Superceded",              "bus": "obd"},
            {"signal": "Power_Take_Off_Powertrain_Run_Aborted",                 "bus": "obd"},
            {"signal": "Powertrain_Brake_Pedal_Discrete_Input_Status",          "bus": "obd"},
            {"signal": "Powertrain_Brake_Pedal_Discrete_Input_Status_Validity", "bus": "obd"},
            {"signal": "Powertrain_Crank_Aborted",                              "bus": "obd"},
            {"signal": "Powertrain_Crank_Active",                               "bus": "obd"},
            {"signal": "Powertrain_Run_Aborted",                                "bus": "obd"},
            {"signal": "Remote_Vehicle_Start_Engine_Running",                   "bus": "obd"},
        ],
    },
    "coda": {
        "dbcs": [
            PROJECT_ROOT / "projects/coda/CODA-B-CAN.dbc",
            PROJECT_ROOT / "projects/coda/CODA-D-CAN.dbc",
            PROJECT_ROOT / "projects/coda/CODA-C-CAN-cells.dbc",
        ],
        # C CAN: cell voltage IDs 0x000-0x019 are definitive
        # D CAN: 0x308/0x312/0x325/0x330/0x580 never rebroadcast to B CAN
        # B CAN: everything else (SoC, BMS, DCDC)
        "bus_anchors": [
            ("c_can", set(range(0x000, 0x01A))),
            ("d_can", {0x308, 0x312, 0x325, 0x330, 0x580}),
            ("b_can", {0x1D5, 0x48A, 0x275, 0x381, 0x383}),
        ],
        # GWM gateway rebroadcast exclusions (see notes/driver-inputs.md Gateway Rebroadcast):
        # D CAN native IDs that are passed through to B CAN -- upload from D CAN only.
        # B CAN native IDs that are passed through to D CAN -- upload from B CAN only.
        "exclude": [
            # --- B CAN: gateway copies of D CAN native messages (source = D CAN) ---
            {"can_id": 0x080,  "bus": "b_can"},  # EPS steering angle (EPS/PSM is D CAN module)
            {"can_id": 0x1C0,  "bus": "b_can"},  # MCM core telemetry (D CAN native)
            {"can_id": 0x200,  "bus": "b_can"},  # Heartbeat/counter (D CAN native)
            {"can_id": 0x208,  "bus": "b_can"},  # ESC brake pressure + wheel speeds (D CAN native)
            {"can_id": 0x210,  "bus": "b_can"},  # Throttle pedal position (D CAN native)
            {"can_id": 0x212,  "bus": "b_can"},  # EPS sub-frames + brake switch (D CAN native)
            {"can_id": 0x215,  "bus": "b_can"},  # TCM signal (D CAN native)
            {"can_id": 0x240,  "bus": "b_can"},  # System state (D CAN native)
            {"can_id": 0x241,  "bus": "b_can"},  # Motor thermal data (D CAN native)
            {"can_id": 0x248,  "bus": "b_can"},  # Mode flags / exterior lights (D CAN native)
            {"can_id": 0x276,  "bus": "b_can"},  # HVAC status (D CAN native; confirmed Part 2)
            {"can_id": 0x278,  "bus": "b_can"},  # Drive keepalive / HV ready (D CAN native)
            {"can_id": 0x315,  "bus": "b_can"},  # DLCM status: brake switch, Batt_Volt (D CAN native)
            {"can_id": 0x370,  "bus": "b_can"},  # Death counter batch (D CAN native)
            {"can_id": 0x418,  "bus": "b_can"},  # PRND gear selector (D CAN native)
            {"can_id": 0x600,  "bus": "b_can"},  # TPMS pressure (D CAN native)
            # --- D CAN: gateway copies of B CAN native messages (source = B CAN) ---
            {"can_id": 0x275,  "bus": "d_can"},  # BMS discharge/charge limits (B CAN native)
            {"can_id": 0x383,  "bus": "d_can"},  # State of Charge (B CAN native)
            {"can_id": 0x1D5,  "bus": "d_can"},  # DCDC Status1 (B CAN native)
            {"can_id": 0x491,  "bus": "d_can"},  # IPK status (IPK is B CAN module)
            {"can_id": 0x6FA,  "bus": "d_can"},  # GWM VIN broadcast (GWM is the gateway; primary on B CAN, rebroadcast to D CAN)
        ],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def derive_session(path: Path) -> str:
    """
    Build a session tag from the filename.
    canlog_20260315_123456_M0_T1.log -> 2026-03-15_M0
    Falls back to the stem with _T<n> stripped.
    """
    name = path.stem
    date_m = re.search(r'(\d{4})(\d{2})(\d{2})_\d{6}', name)
    mn_m = re.search(r'_M(\d+)', name)
    if date_m:
        date = f"{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}"
        return f"{date}_M{mn_m.group(1)}" if mn_m else date
    return re.sub(r'_T\d+$', '', name)


def _parse_tz(tz_str: str):
    """
    Parse a timezone string into a tzinfo object.
    Accepts IANA names ('America/Los_Angeles', 'UTC') or numeric offsets ('-7', '+5.5').
    """
    try:
        hours = float(tz_str)
        return timezone(timedelta(hours=hours))
    except ValueError:
        pass
    try:
        return ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"Unknown timezone: {tz_str!r}. "
                         "Use an IANA name (e.g. 'America/Los_Angeles') "
                         "or a numeric offset (e.g. '-7').")


def read_log_start_time(path: Path, tz=timezone.utc) -> float | None:
    """
    Read the start timestamp from a BUSMASTER log header line:
      ***START DATE AND TIME DD:MM:YYYY HH:MM:SS:TTTT***
    Returns Unix epoch (seconds, UTC) or None if not found / not parseable.
    TTTT are 10 kHz ticks (0.1 ms), same unit as frame timestamps.

    tz: tzinfo for the recording PC's clock. datetime.timestamp() converts to UTC.
    Defaults to UTC (header treated as UTC). Pass ZoneInfo('America/Los_Angeles')
    for DST-aware Pacific time, or timezone(timedelta(hours=-7)) for a fixed offset.
    """
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for _ in range(20):
                line = f.readline()
                if not line:
                    break
                m = re.search(
                    r'START DATE AND TIME\s+(\d{2}):(\d{2}):(\d{4})\s+(\d{2}):(\d{2}):(\d{2}):(\d+)',
                    line
                )
                if m:
                    day, mon, yr, h, mn, s, ticks = (int(x) for x in m.groups())
                    frac = ticks * 0.0001
                    dt = datetime(yr, mon, day, h, mn, s, tzinfo=tz)
                    return dt.timestamp() + frac
    except Exception:
        pass
    return None


def derive_start_epoch(path: Path, log_duration: float = 0.0, tz=timezone.utc) -> float:
    """
    Return the Unix epoch (seconds, UTC) for the start of this capture.
    Priority:
      1. BUSMASTER header: ***START DATE AND TIME DD:MM:YYYY HH:MM:SS:TTTT***
      2. YYYYMMDD_HHMMSS in filename
      3. file mtime minus log_duration (mtime is when the file was written = end of capture)

    tz: tzinfo for the recording PC's clock (applied to header and filename timestamps).
    """
    t = read_log_start_time(path, tz)
    if t is not None:
        return t

    m = re.search(r'(\d{8})_(\d{6})', path.stem)
    if m:
        try:
            dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            return dt.replace(tzinfo=tz).timestamp()
        except ValueError:
            pass

    return path.stat().st_mtime - log_duration


def scan_log(path: Path) -> tuple[dict, float, int]:
    """
    Single streaming pass over the log to collect:
      - channel_ids: {bus_int: set of arbitration_ids}
      - last_timestamp: float (seconds) — used to compute log duration
      - frame_count: total frames seen
    Very low memory: only tracks one set of IDs per channel.
    """
    channel_ids: dict[int, set] = defaultdict(set)
    last_ts = 0.0
    count = 0
    for frame in parse_file(path):
        channel_ids[frame.bus].add(frame.arbitration_id)
        last_ts = frame.timestamp
        count += 1
    return dict(channel_ids), last_ts, count


def identify_buses(channel_ids: dict, bus_anchors: list) -> dict:
    """
    Map channel integers to named bus strings using anchor ID sets.
    Channels that match nothing get the name 'ch<N>'.
    Returns {channel_int: bus_name_str}.
    """
    mapping = {}
    for channel, ids in channel_ids.items():
        for bus_name, anchors in bus_anchors:
            if ids & anchors:
                mapping[channel] = bus_name
                break
        else:
            mapping[channel] = f"ch{channel}"
    return mapping


_EXTENDED_BIT = 0x80000000
_BO_RE = re.compile(r'^(BO_ )(\d+)( )', re.MULTILINE)


def _fix_extended_ids(text: str) -> str:
    """
    Some DBCs store 29-bit extended IDs without the 0x80000000 marker that
    cantools requires. Detect BO_ IDs > 0x7FF and OR in the marker.
    """
    def _fix(m):
        raw_id = int(m.group(2))
        if raw_id > 0x7FF and not (raw_id & _EXTENDED_BIT):
            raw_id |= _EXTENDED_BIT
        return m.group(1) + str(raw_id) + m.group(3)
    return _BO_RE.sub(_fix, text)


def load_databases(dbc_paths: list[Path]) -> list:
    """
    Load each DBC into a separate cantools Database object.
    Applies extended-ID fix and suppresses cantools chatter.
    Skips files that don't exist or fail to parse (with a warning).
    Returns list of (name_str, db) tuples.
    """
    result = []
    for path in dbc_paths:
        if not path.exists():
            print(f"  Warning: DBC not found, skipping: {path}", file=sys.stderr)
            continue
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                text = f.read()
            text = _fix_extended_ids(text)
            sink = io.StringIO()
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                db = cantools.database.load_string(text, database_format='dbc', strict=False)
            result.append((path.name, db))
        except Exception as e:
            print(f"  Warning: could not load {path.name}: {e}", file=sys.stderr)
    return result


def decode_frame(frame, databases: list) -> dict:
    """
    Try each database in order. Collect signals from all that match.
    If two DBCs define the same signal name for the same ID, later wins.
    Returns {} if no database decodes the frame.
    """
    signals = {}
    for _name, db in databases:
        try:
            result = db.decode_message(
                frame.arbitration_id,
                frame.data,
                decode_choices=False,
            )
            signals.update(result)
        except Exception:
            pass
    return signals


def all_dbc_ids(databases: list) -> set:
    """Return the union of all message frame_ids across all loaded databases."""
    ids = set()
    for _name, db in databases:
        for msg in db.messages:
            ids.add(msg.frame_id)
    return ids


# ---------------------------------------------------------------------------
# Streaming decode + write
# ---------------------------------------------------------------------------

def build_exclude_sets(profile_exclude: list, cli_exclude: list) -> tuple[set, set, set, set]:
    """
    Parse exclusion lists into four sets for fast lookup:
      exclude_global:     {signal_name}            -- excluded on all buses
      exclude_bus_signal: {(bus_name, signal_name)} -- excluded on a specific bus
      exclude_id:         {can_id}                 -- entire message excluded on all buses
      exclude_bus_id:     {(bus_name, can_id)}     -- entire message excluded on a specific bus

    Profile entries use dicts:
      {"signal": "Name", "bus": "obd"}   or  {"signal": "Name"}
      {"can_id": 0x0C1,  "bus": "obd"}   or  {"can_id": 0x0C1}

    CLI --exclude entries use strings: "SignalName" or "bus:SignalName"
    (can_id exclusions are profile-only; CLI does not support them)
    """
    exclude_global: set = set()
    exclude_bus_signal: set = set()
    exclude_id: set = set()
    exclude_bus_id: set = set()

    for entry in profile_exclude + cli_exclude:
        if isinstance(entry, dict):
            bus = entry.get("bus")
            if "can_id" in entry:
                can_id = entry["can_id"]
                if bus:
                    exclude_bus_id.add((bus, can_id))
                else:
                    exclude_id.add(can_id)
            else:
                sig = entry["signal"]
                if bus:
                    exclude_bus_signal.add((bus, sig))
                else:
                    exclude_global.add(sig)
        else:
            # CLI format: "bus:signal" or just "signal"
            if ":" in entry:
                bus, sig = entry.split(":", 1)
            else:
                bus, sig = None, entry
            if bus:
                exclude_bus_signal.add((bus, sig))
            else:
                exclude_global.add(sig)

    return exclude_global, exclude_bus_signal, exclude_id, exclude_bus_id


def stream_and_write(
    path: Path,
    databases: list,
    vehicle: str,
    session: str,
    start_epoch: float,
    upload_raw: bool,
    bus_map: dict,
    batch_size: int,
    client,
    dry_run: bool,
    total_frames: int = 0,
    exclude_global: set = frozenset(),
    exclude_bus_signal: set = frozenset(),
    exclude_id: set = frozenset(),
    exclude_bus_id: set = frozenset(),
    gzip: bool = False,
) -> int:
    """
    Single streaming pass: decode each frame and write to InfluxDB in
    fixed-size batches. A background writer thread sends batches while the
    main thread continues decoding, hiding network round-trip latency.
    Returns total points queued (or counted in dry-run mode).
    """
    known_ids = all_dbc_ids(databases)
    batch: list = []
    queued = 0
    frames_seen = 0

    # Producer/consumer pipeline: main thread decodes; worker thread writes.
    # Queue depth 3 lets the worker stay one batch ahead without unbounded memory.
    write_queue: queue.Queue = queue.Queue(maxsize=3)
    write_error: list = [None]

    def writer_worker():
        while True:
            item = write_queue.get()
            if item is None:          # sentinel — time to exit
                write_queue.task_done()
                break
            pts = item
            try:
                if not dry_run:
                    client.write_points(pts, time_precision="n")
            except Exception as exc:
                write_error[0] = exc
            finally:
                write_queue.task_done()

    worker = threading.Thread(target=writer_worker, daemon=True)
    worker.start()

    def flush():
        nonlocal queued
        if not batch:
            return
        if write_error[0]:
            raise write_error[0]
        pts = list(batch)
        batch.clear()
        queued += len(pts)
        write_queue.put(pts)   # blocks if worker is behind (natural back-pressure)
        pct = f" ({frames_seen * 100 // total_frames}%)" if total_frames else ""
        print(f"  {queued} points queued{pct}", end="\r", flush=True)

    for frame in parse_file(path):
        frames_seen += 1
        if frame.is_tx:
            continue

        ts_ns = int((start_epoch + frame.timestamp) * 1_000_000_000)
        can_id_hex = f"0x{frame.arbitration_id:03X}"
        bus_name = bus_map.get(frame.bus, f"ch{frame.bus}")

        # Skip entire message if its CAN ID is excluded for this bus (or all buses)
        if frame.arbitration_id in exclude_id:
            continue
        if (bus_name, frame.arbitration_id) in exclude_bus_id:
            continue

        decoded = False
        if frame.arbitration_id in known_ids:
            signals = decode_frame(frame, databases)
            for sig_name, sig_value in signals.items():
                if sig_value is None:
                    continue
                if sig_name in exclude_global:
                    continue
                if (bus_name, sig_name) in exclude_bus_signal:
                    continue
                batch.append({
                    "measurement": "signals",
                    "tags": {
                        "vehicle": vehicle,
                        "bus":     bus_name,
                        "signal":  sig_name,
                        "can_id":  can_id_hex,
                        "session": session,
                    },
                    "fields": {"value": float(sig_value)},
                    "time": ts_ns,
                })
            decoded = bool(signals)

        if upload_raw and not decoded:
            fields = {"dlc": frame.dlc}
            for i, b in enumerate(frame.data):
                fields[f"b{i}"] = b
            batch.append({
                "measurement": "raw",
                "tags": {
                    "vehicle": vehicle,
                    "bus":     bus_name,
                    "can_id":  can_id_hex,
                    "session": session,
                },
                "fields": fields,
                "time": ts_ns,
            })

        if len(batch) >= batch_size:
            flush()

    flush()  # queue any remainder
    write_queue.put(None)   # send sentinel to stop worker
    write_queue.join()      # wait for all batches to finish writing
    if write_error[0]:
        raise write_error[0]
    label = "counted" if dry_run else "written"
    print(f"  {queued} points {label}          ")
    return queued


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Upload CAN log data to InfluxDB 1.x",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Upload using vehicle default DBCs
  py -3.11 tools/influx_upload.py canlog_20260315_143000_M0_T0.log --vehicle vtrux

  # Add an extra DBC on top of the vehicle defaults
  py -3.11 tools/influx_upload.py <log> --vehicle coda --dbc projects/coda/extra.dbc

  # Include raw bytes for frames not in any DBC
  py -3.11 tools/influx_upload.py <log> --vehicle vtrux --raw

  # Re-upload after DBC changes (delete old data first)
  py -3.11 tools/influx_upload.py <log> --vehicle vtrux --delete

  # Dry run to verify parsing, bus detection, and point counts
  py -3.11 tools/influx_upload.py <log> --vehicle vtrux --dry-run
    """,
    )
    p.add_argument("logs", nargs="+", help="Log file(s) to upload (auto-detects format)")
    p.add_argument("--vehicle", "-v", required=True,
                   help=f"Vehicle name ({', '.join(VEHICLE_PROFILES)}). "
                        "Sets default DBC list and bus anchor IDs.")
    p.add_argument("--dbc", "-d", nargs="+", metavar="DBC",
                   help="Extra DBC file(s) to load in addition to the vehicle defaults")
    p.add_argument("--host",     default="10.0.0.4",    help="InfluxDB host (default: 10.0.0.4)")
    p.add_argument("--port",     type=int, default=8086, help="InfluxDB port (default: 8086)")
    p.add_argument("--database", default="canbus-data",  help="InfluxDB database (default: canbus-data)")
    p.add_argument("--user",     default="claude",       help="InfluxDB username (default: claude)")
    p.add_argument("--password", default="claude",       help="InfluxDB password (default: claude)")
    p.add_argument("--session",  help="Override session name tag (default: derived from filename)")
    p.add_argument("--tz", default="America/Los_Angeles", metavar="TZ",
                   help="Timezone of the recording PC's clock. The BUSMASTER header timestamp "
                        "is local time; this converts it to UTC. Accepts IANA names "
                        "('America/Los_Angeles', 'America/Denver', 'UTC') or numeric offsets "
                        "('-7', '-8'). Default: America/Los_Angeles (Pacific, DST-aware).")
    p.add_argument("--exclude", nargs="+", metavar="SIGNAL",
                   help="Exclude signal(s) from upload. Format: 'SignalName' (all buses) "
                        "or 'bus:SignalName' (specific bus). Stacks with profile defaults.")
    p.add_argument("--compress", action="store_true",
                   help="Reserved for future gzip support (no-op; influxdb-python 5.x "
                        "does not expose gzip_body)")
    p.add_argument("--raw", action="store_true",
                   help="Upload raw byte values for frames not decoded by any DBC")
    p.add_argument("--delete", action="store_true",
                   help="DROP existing series for vehicle+session before uploading")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse and count points but do not write to InfluxDB")
    p.add_argument("--batch-size", type=int, default=5000,
                   help="Points per write batch (default: 5000)")
    args = p.parse_args()

    # Dependency checks
    if InfluxDBClient is None:
        print("Error: influxdb package not installed.  pip install influxdb", file=sys.stderr)
        sys.exit(1)
    if cantools is None:
        print("Error: cantools not installed.  pip install cantools", file=sys.stderr)
        sys.exit(1)

    # Resolve vehicle profile
    profile = VEHICLE_PROFILES.get(args.vehicle)
    if profile is None:
        known = ', '.join(VEHICLE_PROFILES)
        print(f"Error: unknown vehicle '{args.vehicle}'. Known: {known}", file=sys.stderr)
        sys.exit(1)

    bus_anchors = profile["bus_anchors"]
    exclude_global, exclude_bus_signal, exclude_id, exclude_bus_id = build_exclude_sets(
        profile.get("exclude", []),
        args.exclude or [],
    )
    if exclude_global or exclude_bus_signal or exclude_id or exclude_bus_id:
        for sig in sorted(exclude_global):
            print(f"  excluding signal: {sig} (all buses)")
        for bus, sig in sorted(exclude_bus_signal):
            print(f"  excluding signal: {sig} (bus={bus})")
        for can_id in sorted(exclude_id):
            print(f"  excluding message: 0x{can_id:03X} (all buses)")
        for bus, can_id in sorted(exclude_bus_id, key=lambda x: (x[0], x[1])):
            print(f"  excluding message: 0x{can_id:03X} (bus={bus})")

    # Build DBC path list: vehicle defaults + any --dbc extras
    dbc_paths = list(profile["dbcs"])
    if args.dbc:
        dbc_paths += [Path(d) for d in args.dbc]

    # Load all DBCs
    print(f"Loading DBCs for {args.vehicle}:")
    databases = load_databases(dbc_paths)
    if not databases:
        print("Warning: no DBCs loaded -- only raw bytes will be written (use --raw)", file=sys.stderr)

    for name, db in databases:
        n_sigs = sum(len(m.signals) for m in db.messages)
        print(f"  {name}: {len(db.messages)} messages, {n_sigs} signals")

    # Connect
    client = None
    if not args.dry_run:
        client = InfluxDBClient(
            host=args.host, port=args.port,
            username=args.user, password=args.password,
            database=args.database,
        )

    try:
        recording_tz = _parse_tz(args.tz)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Recording timezone: {args.tz}")

    for log_str in args.logs:
        log_path = Path(log_str)
        if not log_path.exists():
            print(f"\nSkipping {log_str}: file not found", file=sys.stderr)
            continue

        session = args.session or derive_session(log_path)

        print(f"\n--- {log_path.name}")
        print(f"  session : {session}")

        if args.delete and not args.dry_run:
            print(f"  Dropping existing series for vehicle={args.vehicle} session={session} ...")
            client.query(
                f"DROP SERIES FROM signals "
                f"WHERE \"vehicle\"='{args.vehicle}' AND \"session\"='{session}'"
            )
            if args.raw:
                client.query(
                    f"DROP SERIES FROM raw "
                    f"WHERE \"vehicle\"='{args.vehicle}' AND \"session\"='{session}'"
                )

        # Pass 1: scan for bus IDs and log duration (streaming, low memory)
        print(f"  Scanning ...")
        channel_ids, log_duration, frame_count = scan_log(log_path)
        print(f"  {frame_count} frames")

        start_epoch = derive_start_epoch(log_path, log_duration, recording_tz)
        start_dt = datetime.fromtimestamp(start_epoch, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        print(f"  anchor  : {start_dt}")

        bus_map = identify_buses(channel_ids, bus_anchors)
        for ch, name in sorted(bus_map.items()):
            n = sum(1 for ids in [channel_ids.get(ch, set())] for _ in ids)
            print(f"  ch{ch} -> {name}  ({len(channel_ids.get(ch, set()))} unique IDs)")

        # Pass 2: stream decode + write
        print(f"  Writing ...")
        stream_and_write(
            log_path, databases, args.vehicle, session,
            start_epoch, args.raw, bus_map,
            args.batch_size, client, args.dry_run,
            total_frames=frame_count,
            exclude_global=exclude_global,
            exclude_bus_signal=exclude_bus_signal,
            exclude_id=exclude_id,
            exclude_bus_id=exclude_bus_id,
            gzip=args.compress,
        )

    print("\nDone.")


if __name__ == "__main__":
    main()
