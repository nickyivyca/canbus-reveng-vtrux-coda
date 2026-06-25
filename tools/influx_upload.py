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
import glob
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
from canre.parsers.autodetect import detect_format
from canre.parsers.busmaster import BusmasterParser

try:
    import cantools
except ImportError:
    cantools = None

try:
    from influxdb import InfluxDBClient
except ImportError:
    InfluxDBClient = None

try:
    import requests
except ImportError:
    requests = None


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
            PROJECT_ROOT / "projects/vtrux/epri-pt-bus.dbc",
            PROJECT_ROOT / "projects/vtrux/epri-obd-bus.dbc",
            PROJECT_ROOT / "projects/vtrux/BelInverter-v2.dbc",
            PROJECT_ROOT / "projects/vtrux/vtrux-powertrain-experimental.dbc",
            PROJECT_ROOT / "projects/vtrux/vtrux-obd-experimental.dbc",
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
        # VCM gateway modifications (real data bus differs per ID):
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


def scan_log(path: Path) -> tuple[dict, dict, float]:
    """
    Single streaming pass over the log to collect:
      - channel_ids:    {bus_int: set of arbitration_ids}     -- for anchor matching
      - channel_counts: {bus_int: total frame count}          -- for churn filtering
      - last_timestamp: float (seconds), only used as a mtime fallback for
                        derive_start_epoch when the BUSMASTER header and the
                        filename-date both fail to parse.

    Per-channel frame counts let identify_buses filter out the Android-logger
    startup churn described in projects/vtrux/vtrux.md ("Bus number churn in
    Android T0"): T0 captures can carry 20+ transient channel numbers, each
    with only a handful of frames, before settling on a stable bus number.

    For BUSMASTER logs (the primary format), this dispatches to
    `BusmasterParser.scan_ids` -- a stripped-down line scanner that skips
    timestamp conversion, data-byte hex decoding, and CANFrame allocation,
    roughly halving the scan-pass cost. (Benchmark: scan_log was ~23% of a
    535 MB upload's profiled runtime; the fast path nets ~50-70s real-world
    on that workload.)

    For other log formats (candump, PEAK TRC, SavvyCAN, Vector ASC) we fall
    back to a full parse via `parse_file`. Those formats are rare in this
    project; the extra cost is acceptable to keep the fast path
    BUSMASTER-only and avoid duplicating parsing logic in five places.
    """
    parser = detect_format(path)
    if isinstance(parser, BusmasterParser):
        return BusmasterParser.scan_ids(path)

    channel_ids: dict[int, set] = defaultdict(set)
    channel_counts: dict[int, int] = defaultdict(int)
    last_ts = 0.0
    for frame in parser.parse_file(path):
        channel_ids[frame.bus].add(frame.arbitration_id)
        channel_counts[frame.bus] += 1
        last_ts = frame.timestamp
    return dict(channel_ids), dict(channel_counts), last_ts


def identify_buses(
    channel_ids: dict,
    channel_counts: dict,
    bus_anchors: list,
    min_frames: int = 100,
    min_fraction: float = 0.05,
) -> dict:
    """
    Map channel integers to named bus strings using anchor ID sets, with
    Android-logger churn filtering (see projects/vtrux/vtrux.md "Bus number
    churn in Android T0").

    A channel is kept only if its frame count is BOTH >= min_frames absolute
    AND >= min_fraction of the highest-count channel. Channels failing
    either test are tagged None and their data is skipped at upload time.

    The fraction filter is the primary signal. Surveying 999 Android T0
    logs, the canonical churn case (vtrux_20260503_171127_T0) has a real
    PT bus at 155k frames alongside 9 noise channels of 2-7k frames each
    -- pure absolute thresholds fail to separate them, but a 5%-of-max
    cutoff cleanly does. Real captures dominate noise by 10x+ in frame
    count whether on Android or laptop USB capture.

    Channels passing the count test but lacking any anchor match get the
    fallback name 'ch<N>' (uploaded with channel number as the bus tag).

    Returns {channel_int: bus_name_str_or_None}.
    """
    if not channel_counts:
        return {}
    max_count = max(channel_counts.values())
    threshold = max(min_frames, int(max_count * min_fraction))

    mapping = {}
    for channel, ids in channel_ids.items():
        if channel_counts.get(channel, 0) < threshold:
            mapping[channel] = None
            continue
        for bus_name, anchors in bus_anchors:
            if ids & anchors:
                mapping[channel] = bus_name
                break
        else:
            mapping[channel] = f"ch{channel}"
    return mapping


def estimate_avg_bytes_per_line(path: Path, sample_bytes: int = 100_000) -> float:
    """
    Estimate average bytes per line by reading the first *sample_bytes* of
    the file and counting newlines. Used to drive a rough byte-based
    progress display without a frame-counting pre-pass: progress estimate
    is `frames_seen * avg_bytes_per_line / file_size`.

    The estimate ignores headers (which are negligible vs millions of data
    lines) and is parser-agnostic -- every CAN log format we support has
    one frame per line. Returns 0.0 if the file is empty or unreadable, in
    which case the caller should suppress the progress display.
    """
    try:
        with open(path, "rb") as fh:
            sample = fh.read(sample_bytes)
    except OSError:
        return 0.0
    newlines = sample.count(b"\n")
    if newlines == 0:
        return 0.0
    return len(sample) / newlines


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


def build_id_index(databases: list) -> dict:
    """
    Build {frame_id: [db, ...]} so each frame goes straight to the DBCs that
    actually define it. Avoids the per-frame "try every DBC and catch the
    KeyError" pattern, which is dominant on logs with many loaded DBCs.

    Most IDs land in exactly one DBC (single-element list); the few that
    appear in multiple DBCs are merged in decode_frame, preserving the
    previous "later DBC wins on signal-name collision" behaviour.
    """
    index: dict[int, list] = {}
    for _name, db in databases:
        for msg in db.messages:
            index.setdefault(msg.frame_id, []).append(db)
    return index


def decode_frame(frame, id_index: dict) -> dict:
    """
    Decode a frame using the frame_id -> [db,...] index built by build_id_index.
    Returns {} if no DBC defines this ID or all decode attempts fail.
    """
    dbs = id_index.get(frame.arbitration_id)
    if not dbs:
        return {}
    if len(dbs) == 1:
        try:
            return dbs[0].decode_message(
                frame.arbitration_id, frame.data, decode_choices=False,
            )
        except Exception:
            return {}
    signals: dict = {}
    for db in dbs:
        try:
            signals.update(db.decode_message(
                frame.arbitration_id, frame.data, decode_choices=False,
            ))
        except Exception:
            pass
    return signals


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
    http_session,
    write_url: str,
    dry_run: bool,
    exclude_global: set = frozenset(),
    exclude_bus_signal: set = frozenset(),
    exclude_id: set = frozenset(),
    exclude_bus_id: set = frozenset(),
) -> int:
    """
    Single streaming pass: decode each frame and write to InfluxDB in
    fixed-size batches. A background writer thread POSTs pre-built line
    protocol while the main thread continues decoding, hiding network
    round-trip latency. Returns total points queued (or counted in dry-run
    mode).

    Schema: one point per DECODED FRAME, with each signal stored as a field.
    Tag set is {vehicle, bus, can_id, session} -- signal name is NOT a tag,
    so series cardinality stays bounded and Grafana queries scan a single
    series per CAN ID. Querying a signal becomes SELECT "Signal_Name" instead
    of WHERE signal='Signal_Name'.

    Wire format: line protocol is generated here directly, not via
    influxdb-python's ``client.write_points`` / ``make_line``. The pure-Python
    client serializer was the second-largest hot spot in the 535MB benchmark
    (~65s tottime in `make_line` plus ~71s in `_escape_tag` -- 12 escape
    calls per point even though the tag set is fixed across the whole upload).
    Here, the static tag prefix `signals,bus=X,can_id=0x...,session=Y,vehicle=Z `
    is built once per (bus, can_id) pair and cached, so the per-point
    work is just a field-list f-string concat plus a ts_ns concat.

    Tag-value escaping is bypassed by relying on the project's invariants:
    bus names are alphanumeric+underscore (`powertrain`, `b_can`, `ch20`),
    can_ids are `0xNNN`, session names come from filename derivation or a
    user-supplied `--session` (assumed safe), vehicle names are CLI args.
    None of these can carry the line-protocol special characters
    `, =` so escaping is unnecessary in this script's context. Field names
    (signal names from the DBC, plus `dlc`/`bN`) are likewise safe.
    """
    id_index = build_id_index(databases)
    can_id_hex_cache: dict[int, str] = {}
    sig_prefix_cache: dict[tuple, str] = {}
    raw_prefix_cache: dict[tuple, str] = {}
    queued = 0
    frames_seen = 0

    file_size = path.stat().st_size
    avg_bytes_per_line = estimate_avg_bytes_per_line(path)
    can_show_pct = file_size > 0 and avg_bytes_per_line > 0

    # Tag prefix builders. Tags are emitted in alphabetical order so that the
    # InfluxDB engine can take the cached series hash without resorting -- a
    # convention the official client follows internally.
    def signals_prefix(bus_name: str, can_id_hex: str) -> str:
        key = (bus_name, can_id_hex)
        cached = sig_prefix_cache.get(key)
        if cached is None:
            cached = (f"signals,bus={bus_name},can_id={can_id_hex},"
                      f"session={session},vehicle={vehicle} ")
            sig_prefix_cache[key] = cached
        return cached

    def raw_prefix(bus_name: str, can_id_hex: str) -> str:
        key = (bus_name, can_id_hex)
        cached = raw_prefix_cache.get(key)
        if cached is None:
            cached = (f"raw,bus={bus_name},can_id={can_id_hex},"
                      f"session={session},vehicle={vehicle} ")
            raw_prefix_cache[key] = cached
        return cached

    # Lines accumulate as Python strings; encoded once per flush.
    batch: list[str] = []

    write_queue: queue.Queue = queue.Queue(maxsize=3)
    write_error: list = [None]

    def writer_worker():
        while True:
            item = write_queue.get()
            if item is None:
                write_queue.task_done()
                break
            try:
                if not dry_run:
                    resp = http_session.post(write_url, data=item, timeout=60)
                    if resp.status_code >= 300:
                        raise RuntimeError(
                            f"InfluxDB write failed {resp.status_code}: "
                            f"{resp.text[:300]}"
                        )
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
        body = "".join(batch).encode("utf-8")
        n_lines = len(batch)
        batch.clear()
        queued += n_lines
        write_queue.put(body)
        if can_show_pct:
            est_pct = int(frames_seen * avg_bytes_per_line * 100 / file_size)
            pct = f" (~{est_pct}%)"
        else:
            pct = ""
        print(f"  {queued} points queued{pct}", end="\r", flush=True)

    for frame in parse_file(path):
        frames_seen += 1
        if frame.is_tx:
            continue

        arb_id = frame.arbitration_id

        if arb_id in exclude_id:
            continue

        # bus_map[chan] is None for transient/churn channels (see Vtrux T0
        # Android startup behaviour, vtrux.md "Bus number churn in Android T0").
        bus_name = bus_map.get(frame.bus)
        if bus_name is None:
            continue

        if (bus_name, arb_id) in exclude_bus_id:
            continue

        ts_ns = int((start_epoch + frame.timestamp) * 1_000_000_000)
        can_id_hex = can_id_hex_cache.get(arb_id)
        if can_id_hex is None:
            can_id_hex = f"0x{arb_id:03X}"
            can_id_hex_cache[arb_id] = can_id_hex

        decoded = False
        if arb_id in id_index:
            signals = decode_frame(frame, id_index)
            field_parts = []
            for sig_name, sig_value in signals.items():
                if sig_value is None:
                    continue
                if sig_name in exclude_global:
                    continue
                if (bus_name, sig_name) in exclude_bus_signal:
                    continue
                field_parts.append(f"{sig_name}={float(sig_value)}")
            if field_parts:
                batch.append(
                    f"{signals_prefix(bus_name, can_id_hex)}"
                    f"{','.join(field_parts)} {ts_ns}\n"
                )
            decoded = bool(signals)

        if upload_raw and not decoded:
            # raw measurement: int fields written with the InfluxDB 'i' suffix
            # so they stay typed as integers in the database (line protocol's
            # default for `field=N` is float).
            field_parts = [f"dlc={frame.dlc}i"]
            for i, b in enumerate(frame.data):
                field_parts.append(f"b{i}={b}i")
            batch.append(
                f"{raw_prefix(bus_name, can_id_hex)}"
                f"{','.join(field_parts)} {ts_ns}\n"
            )

        if len(batch) >= batch_size:
            flush()

    flush()
    write_queue.put(None)
    write_queue.join()
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
  # Upload a single file
  py -3.11 tools/influx_upload.py canlog_20260315_143000_M0_T0.log --vehicle vtrux

  # Upload all logs in a folder (non-recursive, .log/.asc/.trc/.csv)
  py -3.11 tools/influx_upload.py projects/vtrux/logs/ --vehicle vtrux

  # Upload a folder with a success log so interrupted runs can resume
  py -3.11 tools/influx_upload.py projects/vtrux/logs/ --vehicle vtrux
      --success-log projects/vtrux/notes/artifacts/upload_done.txt

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
    p.add_argument("logs", nargs="+",
                   help="Log file(s) or folder(s) to upload (auto-detects format). "
                        "Folders are expanded non-recursively to .log/.asc/.trc/.csv files.")
    p.add_argument("--vehicle", "-v", required=True,
                   help=f"Vehicle name ({', '.join(VEHICLE_PROFILES)}). "
                        "Sets default DBC list and bus anchor IDs.")
    p.add_argument("--dbc", "-d", nargs="+", metavar="DBC",
                   help="Extra DBC file(s) to load in addition to the vehicle defaults")
    p.add_argument("--host",     default="localhost",    help="InfluxDB host (default: localhost)")
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
    p.add_argument("--success-log", metavar="FILE",
                   help="File to append successfully uploaded log paths to (append-only). "
                        "Skips files whose resolved path is already listed. "
                        "Use this when uploading a folder so interrupted batches can be resumed "
                        "without re-uploading files that already finished. "
                        "No-op in --dry-run mode.")
    args = p.parse_args()

    # Dependency checks
    if InfluxDBClient is None:
        print("Error: influxdb package not installed.  pip install influxdb", file=sys.stderr)
        sys.exit(1)
    if requests is None:
        print("Error: requests package not installed.  pip install requests", file=sys.stderr)
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

    # InfluxDBClient is kept for control-plane queries (DROP SERIES, etc.).
    # Writes go through a plain requests.Session pointed at /write -- the
    # per-point custom serializer in stream_and_write was profiled as ~3-5x
    # faster than the official client's `make_line` once tag-prefix caching
    # is in place. http_session uses HTTP keepalive, so we get the same
    # single-TCP-connection behaviour the InfluxDBClient had for writes.
    client = None
    http_session = None
    write_url = None
    if not args.dry_run:
        client = InfluxDBClient(
            host=args.host, port=args.port,
            username=args.user, password=args.password,
            database=args.database,
        )
        http_session = requests.Session()
        http_session.auth = (args.user, args.password)
        write_url = (f"http://{args.host}:{args.port}/write"
                     f"?db={args.database}&precision=n")

    try:
        recording_tz = _parse_tz(args.tz)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Recording timezone: {args.tz}")

    # Expand positional args:
    #   foo.log              -> use as-is
    #   path/to/folder/      -> expand to all .log/.asc/.trc/.csv inside
    #   path/with/*.log      -> shell-style glob (script-side, so PowerShell
    #                           and cmd users get the same convenience as Bash)
    _LOG_EXTS = {'.log', '.asc', '.trc', '.csv'}
    log_paths: list[Path] = []
    for entry in args.logs:
        if any(c in entry for c in '*?['):
            matches = sorted(Path(p) for p in glob.glob(entry))
            if not matches:
                print(f"Warning: no files matched glob {entry}", file=sys.stderr)
            log_paths.extend(matches)
            continue
        p_entry = Path(entry)
        if p_entry.is_dir():
            expanded = sorted(f for f in p_entry.iterdir()
                              if f.is_file() and f.suffix.lower() in _LOG_EXTS)
            if not expanded:
                print(f"Warning: no log files found in folder {entry}", file=sys.stderr)
            log_paths.extend(expanded)
        else:
            log_paths.append(p_entry)

    # Load already-uploaded paths from the success log (if provided).
    done_paths: set[str] = set()
    if args.success_log:
        sl_path = Path(args.success_log)
        if sl_path.exists():
            for line in sl_path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line:
                    done_paths.add(line)
        if done_paths:
            print(f"Success log: {len(done_paths)} file(s) already uploaded, will skip.")

    # Pre-compute (log_path, session) pairs for files we will actually upload,
    # so --delete can run ONCE per unique session before the upload loop
    # begins. Previous behaviour ran DROP per file, which on a multi-file
    # upload sharing one --session caused each file to wipe the previous
    # file's data, leaving only the last file's points in InfluxDB.
    pending: list[tuple[Path, str]] = []
    skipped_done: list[Path] = []
    failed: list[str] = []
    for log_path in log_paths:
        resolved_str = str(log_path.resolve())
        if resolved_str in done_paths:
            skipped_done.append(log_path)
            continue
        if not log_path.exists():
            print(f"Skipping {log_path}: file not found", file=sys.stderr)
            failed.append(str(log_path))
            continue
        pending.append((log_path, args.session or derive_session(log_path)))

    if args.delete and not args.dry_run and pending:
        unique_sessions = sorted(set(s for _, s in pending))
        print(f"\nDropping existing series for "
              f"{len(unique_sessions)} session(s) before upload ...")
        for sess in unique_sessions:
            print(f"  vehicle={args.vehicle} session={sess}")
            client.query(
                f"DROP SERIES FROM signals "
                f"WHERE \"vehicle\"='{args.vehicle}' AND \"session\"='{sess}'"
            )
            if args.raw:
                client.query(
                    f"DROP SERIES FROM raw "
                    f"WHERE \"vehicle\"='{args.vehicle}' AND \"session\"='{sess}'"
                )

    for log_path in skipped_done:
        print(f"\nSkipping {log_path.name}: already in success log")

    for log_path, session in pending:
        resolved_str = str(log_path.resolve())

        print(f"\n--- {log_path.name}")
        print(f"  session : {session}")

        try:
            # Pass 1: scan for per-channel IDs and frame counts (streaming, low memory).
            # The frame counts feed identify_buses' churn filter (Vtrux Android T0).
            print(f"  Scanning ...")
            channel_ids, channel_counts, log_duration = scan_log(log_path)
            total_frames = sum(channel_counts.values())
            print(f"  {total_frames} frames across {len(channel_counts)} channel(s)")

            start_epoch = derive_start_epoch(log_path, log_duration, recording_tz)
            start_dt = datetime.fromtimestamp(start_epoch, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
            print(f"  anchor  : {start_dt}")

            bus_map = identify_buses(channel_ids, channel_counts, bus_anchors)
            for ch, name in sorted(bus_map.items()):
                count = channel_counts.get(ch, 0)
                n_ids = len(channel_ids.get(ch, set()))
                if name is None:
                    print(f"  ch{ch} -> SKIP transient ({count} frames, {n_ids} unique IDs)")
                else:
                    print(f"  ch{ch} -> {name}  ({count} frames, {n_ids} unique IDs)")

            # Pass 2: stream decode + write. Progress is byte-based, estimated
            # from file_size and a sniffed avg-bytes-per-line ratio (no frame
            # count needed); the '~' prefix flags it as approximate.
            print(f"  Writing ...")
            stream_and_write(
                log_path, databases, args.vehicle, session,
                start_epoch, args.raw, bus_map,
                args.batch_size, http_session, write_url, args.dry_run,
                exclude_global=exclude_global,
                exclude_bus_signal=exclude_bus_signal,
                exclude_id=exclude_id,
                exclude_bus_id=exclude_bus_id,
            )

        except Exception as exc:
            print(f"\n  ERROR uploading {log_path.name}: {exc}", file=sys.stderr)
            failed.append(str(log_path))
            continue

        if args.success_log and not args.dry_run:
            with open(args.success_log, 'a', encoding='utf-8') as sf:
                sf.write(resolved_str + '\n')

    print("\nDone.")
    if failed:
        print(f"  {len(failed)} file(s) failed or not found:", file=sys.stderr)
        for f in failed:
            print(f"    {f}", file=sys.stderr)


if __name__ == "__main__":
    main()
