# Plan: Vehicle-Aware can_logger.py with Anchor Detection and Diagnostic Reads

## Context

`can_logger.py` currently writes logs to CWD with generic filenames, assigns bus channel numbers
arbitrarily (dongle insertion order), and has no diagnostic capability. Three improvements are needed:

1. **Vehicle-aware output** — `--vehicle coda|vtrux` directs logs to `projects/<vehicle>/logs/` automatically.
2. **Bus anchor detection** — after a brief sniff window, identify which physical dongle is on which
   logical bus by matching observed CAN IDs against per-vehicle anchor sets. This enables diagnostic
   reads to go to the *right* bus regardless of dongle insertion order.
3. **Active diagnostic framework** — after anchor detection, spawn a periodic send thread on the
   identified diagnostic bus. Vtrux: OBD-II Mode 01 PIDs on OBD bus. Coda: UDS DIDs on Diag CAN
   (DIDs TBD — framework built now, populated after inspecting `coda-diagnostics/` scripts).

**Coda Diag CAN anchor finding** (`codadriveslowturnonwithdefroster.log`):
The log is a 3-bus capture (OBD/Diag CAN = channel 1, B CAN = channel 3, C CAN = channel 2).
Grep for `Rx 1` returns **0 matches** across the entire drive — the Diag CAN produces zero broadcast
frames. Its anchor spec is an empty frozenset; detection is by exclusion (unmatched channel after
identifying the other buses).

---

## Files

| File | Action |
|------|--------|
| `tools/plans/can_logger_vehicle_support.md` | Create (Step 0 — plan saved to repo first) |
| `tools/vehicle_configs.py` | Create — vehicle config registry |
| `tools/can_logger.py` | Modify (add `--vehicle`, anchor detection, `DiagnosticReader`) |
| `tools/tools.md` | Update — document new `--vehicle` arg and behavior |

---

## Step 0 — Write plan to repo ✓

Create `tools/plans/` and write this plan as `tools/plans/can_logger_vehicle_support.md` so it is
tracked in the repo and syncs via SeaDrive. Done before any code changes.

---

## Step 1 — Create `tools/vehicle_configs.py`

New module containing vehicle anchor sets and diagnostic request specs.

```python
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional

@dataclass
class DiagRequest:
    name: str
    arb_id: int
    data: bytes
    interval_s: float = 1.0
    is_extended: bool = False

@dataclass
class BusConfig:
    anchors: FrozenSet[int]   # IDs that definitively identify this bus; empty = silent bus
    description: str = ""

@dataclass
class VehicleConfig:
    log_subdir: str                        # relative to project root, e.g. "projects/vtrux/logs"
    buses: Dict[str, BusConfig]            # bus_name → BusConfig
    diag_bus: Optional[str] = None         # bus name to send diagnostic requests on
    diag_requests: List[DiagRequest] = field(default_factory=list)
```

### Vtrux config

```python
"vtrux": VehicleConfig(
    log_subdir="projects/vtrux/logs",
    buses={
        "powertrain": BusConfig(
            anchors=frozenset({0x051}),
            description="Powertrain CAN (0x051 @ ~100 Hz)"
        ),
        "gm_unfiltered": BusConfig(
            anchors=frozenset({0x1E5, 0x500, 0x514, 0x52A}),
            description="Vehicle CAN"
        ),
        "gm_obd": BusConfig(
            anchors=frozenset({0x040, 0x041, 0x042, 0x043, 0x044}),
            description="OBD CAN (OBD-II DLC)"
        ),
    },
    diag_bus="gm_obd",
    diag_requests=[
        DiagRequest("RPM",          0x7DF, bytes([0x02, 0x01, 0x0C, 0,0,0,0,0]), interval_s=0.5),
        DiagRequest("VehicleSpeed", 0x7DF, bytes([0x02, 0x01, 0x0D, 0,0,0,0,0]), interval_s=0.5),
        DiagRequest("ThrottlePos",  0x7DF, bytes([0x02, 0x01, 0x11, 0,0,0,0,0]), interval_s=1.0),
        DiagRequest("CoolantTemp",  0x7DF, bytes([0x02, 0x01, 0x05, 0,0,0,0,0]), interval_s=2.0),
    ]
)
```

### Coda config

All four buses are accessible at the J1962 OBD-II connector, so up to 4 dongles can be connected
simultaneously. The anchor detection must handle all 4 in one pass. Diag CAN is detected last by
exclusion — it is the channel (if any) with no anchor hits after the other three are matched.

```python
"coda": VehicleConfig(
    log_subdir="projects/coda/logs",
    buses={
        "c_can": BusConfig(
            anchors=frozenset(range(0x000, 0x01A)),   # cell voltage frames 0x000–0x019
            description="C CAN (BMS cell voltages, always present)"
        ),
        "b_can": BusConfig(
            anchors=frozenset({0x1D5, 0x48A, 0x275, 0x381, 0x383, 0x492}),
            description="B CAN (battery/body, key-on)"
        ),
        "d_can": BusConfig(
            anchors=frozenset({0x308, 0x312, 0x325, 0x330, 0x580}),
            description="D CAN (driveline, accessible at OBD connector)"
        ),
        "diag_can": BusConfig(
            anchors=frozenset(),   # Silent: confirmed zero broadcast frames in entire drive capture
            description="Diag CAN (scan tool routing via GWM; silent at rest)"
        ),
    },
    diag_bus="diag_can",
    diag_requests=[
        # TODO: populate after inspecting projects/coda/coda-diagnostics/ for UDS DID addresses.
        # Framework is in place; add DiagRequest entries once DIDs are confirmed.
    ]
)
```

---

## Step 2 — Anchor detection function (add to `can_logger.py`)

```python
DETECTION_WINDOW_S = 5.0   # seconds to sniff before assigning bus names

def detect_bus_assignments(vehicle_config, observed_ids_per_channel):
    """
    Match observed ID sets to named buses via anchor intersection.
    Silent buses (empty anchor set) are assigned by exclusion to unmatched channels.

    Returns: {channel_id: bus_name}
    """
    assignments = {}          # channel_id → bus_name
    silent_bus_name = None

    # Sort buses so empty-anchor (silent) bus is handled last
    named_buses = [(n, c) for n, c in vehicle_config.buses.items() if c.anchors]
    silent_buses = [(n, c) for n, c in vehicle_config.buses.items() if not c.anchors]
    if silent_buses:
        silent_bus_name = silent_buses[0][0]   # expect at most one silent bus

    # Greedy best-match: assign each named bus to the channel with most anchor hits
    assigned_channels = set()
    for bus_name, bus_cfg in named_buses:
        best_ch = None
        best_hits = 0
        for ch, ids in observed_ids_per_channel.items():
            if ch in assigned_channels:
                continue
            hits = len(bus_cfg.anchors & ids)
            if hits > best_hits:
                best_hits = hits
                best_ch = ch
        if best_ch is not None and best_hits > 0:
            assignments[best_ch] = bus_name
            assigned_channels.add(best_ch)

    # Assign silent bus to any remaining unmatched channel
    if silent_bus_name:
        for ch in observed_ids_per_channel:
            if ch not in assigned_channels:
                assignments[ch] = silent_bus_name
                break

    return assignments
```

---

## Step 3 — `DiagnosticReader` class (add to `can_logger.py`)

```python
class DiagnosticReader:
    """Sends periodic diagnostic requests on a CAN bus; queues Tx frames for logging."""

    def __init__(self, bus_id, bus, requests, message_queue, start_time):
        self.bus_id = bus_id
        self.bus = bus
        self.requests = requests
        self.message_queue = message_queue
        self.start_time = start_time
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._request_loop, daemon=True)
        self.thread.start()

    def _request_loop(self):
        next_send = {req.name: time.time() + 1.0 for req in self.requests}  # 1s initial delay
        while self.running:
            now = time.time()
            for req in self.requests:
                if now >= next_send[req.name]:
                    try:
                        msg = can.Message(
                            arbitration_id=req.arb_id,
                            data=req.data,
                            is_extended_id=req.is_extended,
                            is_rx=False,
                        )
                        self.bus.send(msg)
                        timestamp = now - self.start_time
                        self.message_queue.put((timestamp, self.bus_id, msg, "Tx"))
                    except Exception as e:
                        logger.warning(f"DiagnosticReader send error ({req.name}): {e}")
                    next_send[req.name] = now + req.interval_s
            time.sleep(0.005)

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
```

Tx frames are queued to the same `message_queue` as Rx frames. The queue tuple changes from
`(timestamp, bus_id, msg)` → `(timestamp, bus_id, msg, direction)` throughout.
`CANBusLogger._receive_loop` puts `"Rx"`; `DiagnosticReader` puts `"Tx"`.

---

## Step 4 — Modify `main()` in `can_logger.py`

### New argument
```python
parser.add_argument(
    '--vehicle', '-v',
    default=None,
    help='Vehicle name (e.g. coda, vtrux). Enables auto log placement, '
         'bus anchor detection, and diagnostic reads.'
)
```

### Output path logic (after arg parse)
```python
vehicle_cfg = None
if args.vehicle:
    from vehicle_configs import VEHICLES
    vehicle_cfg = VEHICLES.get(args.vehicle.lower())
    if vehicle_cfg is None:
        logger.error(f"Unknown vehicle '{args.vehicle}'. Known: {list(VEHICLES)}")
        sys.exit(1)

if args.output is None:
    now = datetime.datetime.now()
    stem = f"canlog_{now.strftime('%Y%m%d_%H%M%S')}.log"
    if vehicle_cfg:
        # Project root is two levels up from tools/
        project_root = Path(__file__).parent.parent
        output_dir = project_root / vehicle_cfg.log_subdir
        output_dir.mkdir(parents=True, exist_ok=True)
        args.output = str(output_dir / stem)
    else:
        args.output = stem
```

### Anchor detection phase (in `main()`, after buses are started, inside `with BUSMASTERWriter`)

```python
if vehicle_cfg:
    logger.info(f"Detecting bus assignments (sniffing {DETECTION_WINDOW_S}s)...")
    observed_ids = {i: set() for i in range(len(buses))}
    deadline = time.time() + DETECTION_WINDOW_S
    sniffed = []
    while time.time() < deadline:
        try:
            item = message_queue.get(timeout=0.1)
            sniffed.append(item)
            timestamp, bus_id, msg, direction = item
            if direction == "Rx":
                observed_ids[bus_id].add(msg.arbitration_id)
        except Empty:
            continue

    # Write sniffed messages to file before continuing
    for timestamp, bus_id, msg, direction in sniffed:
        writer.write_message(timestamp, bus_id, msg, direction)

    bus_assignments = detect_bus_assignments(vehicle_cfg, observed_ids)
    logger.info("Bus assignments:")
    for ch, name in sorted(bus_assignments.items()):
        desc = vehicle_cfg.buses[name].description
        logger.info(f"  Channel {ch} → {name}  ({desc})")

    # Start diagnostic reader on identified diag bus
    diag_channel = None
    if vehicle_cfg.diag_bus:
        for ch, name in bus_assignments.items():
            if name == vehicle_cfg.diag_bus:
                diag_channel = ch
                break

    if diag_channel is not None and vehicle_cfg.diag_requests:
        diag_reader = DiagnosticReader(
            bus_id=diag_channel,
            bus=buses[diag_channel].bus,
            requests=vehicle_cfg.diag_requests,
            message_queue=message_queue,
            start_time=buses[diag_channel].start_time,
        )
        diag_reader.start()
        logger.info(f"Diagnostic reads started on channel {diag_channel} "
                    f"({len(vehicle_cfg.diag_requests)} request types)")
    elif vehicle_cfg.diag_bus:
        logger.warning(f"Diag bus '{vehicle_cfg.diag_bus}' not identified — no diagnostic reads")
```

---

## Step 5 — Update `BUSMASTERWriter.write_message`

Change signature to accept `direction` parameter (default `"Rx"`):

```python
def write_message(self, timestamp, bus_id, msg, direction="Rx"):
    ...
    line = f"{time_str} {direction} {channel} {can_id} {msg_type} {dlc} {data_str}\n"
```

Also update `CANBusLogger._receive_loop` to put 4-tuples: `(timestamp, self.bus_id, msg, "Rx")`.
Update the main drain loop to unpack 4-tuples accordingly.

---

## Step 6 — Update `tools/tools.md`

Document the new `--vehicle` flag, the anchor detection warm-up behavior, the log auto-placement,
and Coda Diag CAN anchor finding (silent bus detected by exclusion). Note Coda `diag_requests` are
empty pending DID discovery from `coda-diagnostics/`.

---

## Verification

1. **No vehicle:** `python tools/can_logger.py` — behavior unchanged; log in CWD.
2. **Vehicle arg, no hardware:** `python tools/can_logger.py --vehicle coda` — log path resolves
   to `projects/coda/logs/canlog_*.log`; anchor detection completes (no assignments if no dongles); no crash.
3. **With Vtrux connected:** Bus assignments output shows correct channel→bus_name after 5s sniff.
   Log has `Tx` entries for OBD PID requests (0x7DF).
4. **With Coda connected (all 4 buses):** C CAN, B CAN, D CAN assigned by anchor hits; Diag CAN
   assigned by exclusion as the 4th unmatched channel. Also verify 3-bus case (e.g. B+C+Diag,
   no D CAN dongle) assigns correctly with 3 channels.
5. **Unknown vehicle:** `python tools/can_logger.py --vehicle bogus` → clean error exit.

---

## Addon: Data Overrun Recovery (2026-02-25)

### Context

When a CAN dongle experiences a data overrun the driver latches and stops delivering messages:
```
[ERROR] Bus 0 receive error: Data overrun occurred
```
The fix detects the overrun string, shuts down the affected `Bus` object, and re-opens it using
the stored interface spec so logging resumes without a full restart.

### Changes

- `CANBusLogger.__init__`: add `iface`, `ch`, `bitrate` parameters (stored for reconnect)
- `CANBusLogger._reconnect()`: new method — shutdown + re-open with exponential backoff (1/2/4/8/16 s);
  sets `self.running = False` after 5 failed attempts
- `CANBusLogger._receive_loop`: detect `'overrun' in str(e).lower()`, call `_reconnect()` instead
  of just logging; non-overrun exceptions keep existing log-and-continue behaviour
- `main()` bus construction: pass `iface`, `ch`, `args.bitrate` to `CANBusLogger`

No changes to `BUSMASTERWriter`, `stop()`, or the main write loop.

### Key findings from live testing (2026-02-26)

- Soft reconnect (`shutdown()` + `Bus()`) does not clear the hardware latch — CAN LED stays off and overrun recurs immediately after reconnect
- `rx_fifo_size` increase and drain-on-reconnect did not help; overflow is at the ixxat hardware FIFO level, not the python-can ring buffer
- A second ixxat dongle on the same high-traffic bus had no overflow, confirming the issue is dongle-specific hardware state, not bus traffic rate
- **VID is `08D8`** (HMS Industrial Networks), not `0A71` (original ixxat VID)
- `unique_hardware_id` (e.g. `HW379841`) appears verbatim as the final component of the Windows PnP instance ID: `USB\VID_08D8&PID_0008\HW379841` — enables targeted single-dongle reset
- USB hardware reset (`Disable-PnpDevice` / `Enable-PnpDevice`) successfully clears the latch; requires administrator privileges
- `can_logger_admin.bat` added as a self-elevating UAC wrapper so admin cmd is not needed manually

---

## Addon: Vehicle-Specific CAN GUI — can_monitor.py (2026-03-05, implemented 2026-03-09)

### Summary

Add a PyQt-based live CAN monitor (`can_monitor.py`) alongside the existing headless `can_logger.py`. The GUI is vehicle-specific and mode-aware (charging vs. driving). The logger's core CAN plumbing is extracted into a shared library module so both tools share it without duplication.

### Decisions Locked

| Decision | Choice | Rationale |
|----------|--------|-----------|
| GUI vs. logger relationship | Separate tool (`can_monitor.py`); shared CAN plumbing extracted to `canre/live/` | Logger stays headless and unchanged in behavior; GUI is purely additive |
| Vehicle profile architecture | Python class (`VehicleProfile` subclass per vehicle) | Mode detection needs multi-signal logic that a dict config can't express; layouts differ substantially between vehicles |
| DBC -> GUI relationship | **Explicit only** — widgets are declared in the profile, not inferred from DBC | Adding a signal to the DBC must NOT auto-add it to the GUI; profiles own the display contract |
| Widget sharing | Shared widget library (`canre/gui/widgets.py`) for reusable components; vehicle profiles compose them selectively | Vtrux has generator widgets Coda does not; both share e.g. HV voltage gauge |

### Design Decisions (resolved 2026-03-09)

- **Mode granularity**: Arbitrary number of modes per vehicle; profile declares the ordered list.
  Mode is active if ANY of its ModeRules evaluates True (ID presence OR signal value predicate).
  First matching mode wins. Last mode is the fallback default.
- **Mode switching**: Fully automatic — evaluated on every 50 ms timer tick.
- **Log passthrough**: `--output` flag enables simultaneous BUSMASTER log write from the same queue.
- **Multi-bus display**: Anchor detection runs at startup (5 s sniff window); assigns channel IDs to
  logical bus names. Same logic as vehicle_configs.detect_bus_assignments.
- **Offline/replay mode**: Not yet implemented. Can feed a log file through can_replayer.py to the
  same hardware interface, and the monitor picks it up normally.
- **Window layout**: Single window; QStackedWidget swaps mode layouts. Each layout wrapped in QScrollArea.
- **Coda profile scope**: Coda charging GUI implemented as first profile (2026-03-09).

### Proposed File Layout

```
canre/
  live/
    __init__.py
    receiver.py        # CANBusLogger, detect_all_can_interfaces, Queue — extracted from can_logger.py
  gui/
    __init__.py
    base_profile.py    # VehicleProfile ABC
    main_window.py     # QMainWindow, mode banner, QStackedWidget, QTimer drain loop
    widgets.py         # Reusable widget classes: LiveGauge, LivePlot, LiveIndicator, LiveValue

tools/
  can_logger.py        # Unchanged behavior; imports CANBusLogger from canre.live.receiver
  can_monitor.py       # GUI entrypoint

projects/
  vtrux/
    gui_profile.py     # VtruxProfile(VehicleProfile)
  coda/
    gui_profile.py     # CodaProfile(VehicleProfile) — may be deferred
```

### Phase 1 — Extract shared CAN plumbing  DONE 2026-03-09

`canre/live/receiver.py` created with `CANBusLogger`, `detect_all_can_interfaces`, USB reset helpers.
`can_logger.py` updated to import from it. 4-tuple queue format `(ts, bus_id, msg, direction)` added.
`canre/live/vehicle_configs.py` created with VEHICLES registry and `detect_bus_assignments`.

### Phase 2 — VehicleProfile ABC  DONE 2026-03-09

`VehicleProfile` ABC (tentative interface):

```python
class VehicleProfile(ABC):
    dbc_path: str                         # path to vehicle DBC (relative to project root)
    bus_anchor_ids: dict[str, list[int]]  # bus name -> anchor IDs (reuse vehicle_configs data)

    @abstractmethod
    def detect_mode(self, live_signals: dict) -> str:
        """Return mode string given current decoded signal state."""
        ...

    @abstractmethod
    def get_modes(self) -> list[str]:
        """Return list of valid mode strings for this vehicle."""
        ...

    @abstractmethod
    def build_layout(self, mode: str, parent: QWidget) -> QWidget:
        """Construct and return the Qt layout widget for the given mode."""
        ...
```

`live_signals` dict shape (tentative):

```python
{
    ("PT", 0x592): {"signal_name": decoded_value, ...},  # cantools-decoded signals
    ("PT", 0x592, 2): 0x05,                              # raw byte fallback for un-DBC'd bytes
}
```

VtruxProfile mode detection sketch:
- Bus identification: reuse anchor-ID assignments from `vehicle_configs.py` / `canre/live/receiver.py`
- Charging mode: PT bus charger state byte != 0 (exact byte/values TBD — confirm against logs)
- Driving mode: vehicle speed > 0 OR motor torque != 0
- Parked: fallthrough default

### Phase 3 — Core GUI scaffolding  DONE 2026-03-09

`canre/gui/` package created with:
- `base_profile.py` — `ModeRule` dataclass + `VehicleProfile` ABC
- `bus_decoder.py` — `BusDecoder` (cantools, `strict=False`, `decode_choices=False`)
- `widgets.py` — `LiveValue`, `LiveBar`, `LiveIndicator`, `make_group`
- `main_window.py` — `CANMonitorWindow` (QStackedWidget, QTimer 50 ms, status bar)
`tools/can_monitor.py` CLI created.

### Phase 4 — Coda charging GUI profile  DONE 2026-03-09

`projects/coda/gui_profile.py` (`CodaProfile`) created with:
- **Modes**: charging, idle
- **Mode detection**: 4 rules for charging (HVPowermode=5, Chargemode=3, HVBattCharging=1,
  CMS messages present); 1 rule for idle (B CAN alive)
- **Charging layout** (two-column QSplitter):
  - Left: Battery Pack (SoC bar, voltage, current, charge limit) | Cell Voltages (0x381) |
    Pack Temperature (0x382)
  - Right: Charger Input CMS (0x27B) | Charger Output CMS (0x27C) | Charger Temps CMS (0x27A) |
    BMS Charger Command (0x050) | System Status (0x378/383/270/271) | HVAC/Thermal (0x276/1D5)
- Fault alerts: cell spread > 50 mV highlighted red; fault severity > 0 highlighted red;
  VehicleFaultLampReq >= 2 (RED) highlighted red

### Phase 5 (Not Yet Started) — Vtrux charging layout

Full charging layout for Vtrux. Signals TBD from Vtrux DBC. Create `projects/vtrux/gui_profile.py`.

### Phase 6 (Not Yet Started) — Vtrux driving layout

Full driving layout. Likely: vehicle speed, motor torque (traction + generator), SoC/Ah,
HV voltage, pack current, engine RPM (OBD bus), fault indicators.

### Phase 7 (Not Yet Started) — Coda driving layout

Add "driving" mode to CodaProfile. Key signals: MCM_CoreTelemetry (0x1C0 D CAN), vehicle speed,
throttle (0x210), brake pressure (0x208), SoC, pack current, fault status.

### Dependencies

- `PyQt5` (prefer over PyQt6 for Windows compatibility with the py-3.11 environment)
- `pyqtgraph` (for LivePlot)
- `cantools` and `python-can` (already project dependencies)
