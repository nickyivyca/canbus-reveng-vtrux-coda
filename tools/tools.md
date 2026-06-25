# Tools Reference

> **Staleness check:** Each section shows a `Source last modified` timestamp in `YYYY-MM-DD HH:MM:SS` format (file mtime). If the `.py` file's mtime is newer than the timestamp shown here, re-read the source before relying on this documentation. When updating a timestamp, always include the full date and time — not just the date.

## CANFrame field names (common mistake)

When writing scripts or scratchpads that touch `CANFrame` objects:

- **`frame.arbitration_id`** — correct. `arb_id` is only a local variable name used inside parsers before being passed as the constructor kwarg `arbitration_id=`; it is not a `CANFrame` attribute.
- **`frame.bus`** — correct. `channel` is a `python-can` concept (hardware channel spec for `can.interface.Bus(channel=...)`); the `CANFrame` dataclass field is `bus`. Never use `frame.channel`.

---

**Vehicle-specific tools** are kept alongside their vehicle's project files, not here:
- Coda: `projects/coda/tools/` — see `projects/coda/tools/README.md`
- Vtrux: `projects/vtrux/tools/` — see `projects/vtrux/tools/README.md`

**Cross-tool investigations and benchmarks** live in `tools/notes/` — see `tools/notes/README.md`.

---

## dbc_parity_generate.py
*Source last modified: 2026-05-10*
*Consumed by: `android-app/CanLoggerApps/cancore/src/test/java/com/reverseit/cancore/DbcParityTest.kt`*

Generates parity test cases for the Kotlin DBC decoder by running each
Vtrux DBC through cantools and dumping the (payload -> decoded signals)
mapping to a TSV the Kotlin test loads from its classpath. For each
non-multiplexed message, generates N random payloads. For multiplexed
messages, generates N payloads per mux value (with the multiplexer bits
forced to each value in turn). Copies the source DBC files into
`cancore/src/test/resources/dbcs/` so the test has self-contained fixtures.

**Requires:** `pip install cantools` (already a project dep).

**Usage (default: all four Vtrux DBCs, 30 cases each):**
```
py -3.12 tools/dbc_parity_generate.py
```

**Optional flags:**
```
  --dbc PATH        DBC file (repeatable; default: Vtrux set)
  --output-dir DIR  cancore test resources root (default: the cancore module)
  --cases N         Random payloads per message / per mux value (default: 30)
  --seed N          PRNG seed for reproducibility (default: 42)
```

**Output format** (TSV at `cancore/src/test/resources/dbc_parity_cases.tsv`):
```
dbc_basename<TAB>message_id_decimal<TAB>payload_hex<TAB>sig=val;sig=val;...
```
String-valued signals (from DBC value tables) are emitted as quoted strings
and skipped by the Kotlin test (the protocol emits raw scalars per §11/§13;
enum mapping is client-side).

Regenerate any time a Vtrux DBC changes, then run `:cancore:testDebugUnitTest`
to validate parity.

---

## can_display_server.py
*Source last modified: 2026-05-10 16:09:24*
*Companion files: `can_display_client.py`, `can_display_bus_identity_vtrux.json`, `can_display_server_requirements.txt`*
*Protocol spec: `android-app/notes/protocols/can-display-protocol.md` (v1)*

Reference implementation of the CAN Display Protocol v1. WebSocket server that
replays a recorded CAN log and streams server-decoded signal values to a
display client. Built so the `:display` Android module and other clients can be
developed and validated without phone hardware.

Supports the full Tier 1 aggregation set (`decimate`, `latest`, `min`, `max`,
`mean`) on tumbling windows, anchor-ID-based bus identification, bearer-token
auth, and protocol takeover semantics (a new authenticated client supersedes
any existing session per protocol §10).

**Requires:** `pip install -r tools/can_display_server_requirements.txt`
(`websockets >= 12.0`, `cantools`).

**Usage:**
```
py -3.12 tools/can_display_server.py [options]

  --log PATH              CAN log to replay (BUSMASTER, candump, SavvyCAN, TRC,
                          Vector ASC; auto-detected) [required]
  --bus-identity PATH     JSON file mapping named buses to anchor-ID lists
                          (see can_display_bus_identity_vtrux.json) [required]
  --dbc PATH              Optional. Overrides the DBC sent by the client in its
                          `config` message; useful for testing without a real
                          client. By default the client's DBC is used.
  --port N                WebSocket listen port (default: 9878 -- distinct from
                          LogFileServer's 9877)
  --token T               Bearer token. Random 16-hex generated and printed at
                          startup if omitted.
  --speed F               Replay speed multiplier (default 1.0; 0 = no delay)
  --loop                  Loop the log when it ends
  --verbose               Log every wire message
  --dump-subscription-summary
                          On client config, log a human-readable subscription
                          summary
```

**Bus identity JSON format:**
```json
[
  {"name": "powertrain", "anchor_ids": ["0x051", "0x592-0x5A2"]},
  {"name": "vehicle",    "anchor_ids": ["0x1E5", "0x500"]},
  {"name": "obd",        "anchor_ids": ["0x040-0x044"]}
]
```
- `anchor_ids` accepts decimal ints, hex-prefixed strings, and `lo-hi` ranges.
- The shipped `can_display_bus_identity_vtrux.json` covers Vtrux PT/Vehicle/OBD
  buses as documented in `projects/vtrux/vtrux.md`.

**Bus identification:** the server pre-scans the first 2 s of the log,
counting anchor-ID matches per channel, and assigns each named bus to the
channel with the highest count above a threshold (3 anchors, or all anchors if
fewer than 3 are configured). Identified buses receive a `bus_identified`
status; unidentified buses with subscriptions receive `bus_silent`.

**Decode:** uses `cantools.database.decode_message()` against the DBC supplied
by the client (or `--dbc` override). Multiplexed messages (protocol §8.5) are
supported: cantools transparently decodes the multiplexer signal first, then
returns only the signals from the matching mux group. Signals from inactive
mux groups are absent on a per-frame basis; the aggregator updates only on
frames where the signal is present (sparse-update semantics). Value-table
(enum) signals decode to their underlying scalar; clients map to strings if
needed.

**Aggregation:** tumbling windows of `1/rate_hz` seconds, per protocol §7.
`decimate` emits every Nth frame where N = round(observed_bus_rate / rate_hz).

**Companion smoke-test client (`can_display_client.py`):** loads a DBC and a
JSON manifest, connects, sends `config`, prints incoming frames. Useful for
end-to-end verification without the Android client.

```
py -3.12 tools/can_display_client.py \
    --url ws://localhost:9878/stream \
    --token <token printed by server> \
    --dbc projects/vtrux/epri-pt-bus.dbc \
    --manifest tools/artifacts/smoke_manifest.json
```

The manifest file contains a single `subscriptions` array matching the
protocol's `config.subscriptions` schema.

**Aggregation primitives unit-test:**
`tools/artifacts/test_can_display_aggregation.py` validates the running
sum/min/max/mean primitives against known sequences. Run with `py -3.12`.

---

## influx_upload.py
*Source last modified: 2026-05-05 22:50:25*

Uploads CAN log data to InfluxDB 1.x for Grafana visualization. Decodes frames against
per-vehicle DBC sets (cantools) and writes signal values to the `signals` measurement.
Optionally writes raw byte values for undecodable frames to the `raw` measurement.

Each point carries a `bus` tag (e.g. `powertrain`/`vehicle`/`obd` for Vtrux,
`b_can`/`c_can`/`d_can` for Coda) identified from anchor IDs — never from the arbitrary
channel number in the log file.

**Requires:** `pip install influxdb cantools`

**Default connection:** `localhost:8086`, database `canbus-data`, user `claude`.

**Usage:**
```
py -3.11 tools/influx_upload.py <log|folder> [<log2|folder2> ...] --vehicle <name> [options]

  log / folder           One or more log files or folders. Folders are expanded
                         non-recursively to .log/.asc/.trc/.csv files, sorted by name.
  --vehicle, -v          Vehicle name: vtrux | coda  [required]
                         Loads the vehicle's default DBC set and bus anchor IDs.
  --dbc, -d DBC [...]    Extra DBC file(s) appended after the vehicle defaults
  --host                 InfluxDB host (default: localhost)
  --port                 InfluxDB port (default: 8086)
  --database             InfluxDB database name (default: canbus-data)
  --user                 InfluxDB username (default: claude)
  --password             InfluxDB password (default: claude)
  --session              Override session name tag (default: derived from filename)
  --raw                  Also upload raw bytes for frames not decoded by any DBC
  --delete               DROP existing series for vehicle+session before uploading
  --dry-run              Parse and count points but do not write to InfluxDB
  --batch-size N         Points per write batch (default: 5000)
  --success-log FILE     Append-only file recording successfully uploaded log paths.
                         On re-run, files already listed are skipped automatically.
                         Use with folder uploads so interrupted batches can be resumed.
                         No-op in --dry-run mode.
```

**Vehicle default DBCs:**

| Vehicle | DBCs loaded by default |
|---------|----------------------|
| vtrux | `vtrux-powertrain.dbc`, `BelInverter.dbc` |
| coda | `CODA-B-CAN.dbc`, `CODA-D-CAN.dbc`, `CODA-C-CAN-cells.dbc` |

**Data model:**

| Measurement | Tags | Fields | When |
|---|---|---|---|
| `signals` | vehicle, bus, signal, can_id, session | value (float) | DBC-decoded frame |
| `raw` | vehicle, bus, can_id, session | b0..b7 (int), dlc (int) | Frame not in any DBC, with --raw |

**Bus tag values:**

| Vehicle | Bus tag | Anchor IDs used |
|---------|---------|----------------|
| vtrux | `powertrain` | 0x051 |
| vtrux | `vehicle` | 0x1E5, 0x500 |
| vtrux | `obd` | 0x040–0x044 |
| coda | `c_can` | 0x000–0x019 (cell voltages) |
| coda | `d_can` | 0x308, 0x312, 0x325, 0x330, 0x580 |
| coda | `b_can` | 0x1D5, 0x48A, 0x275, 0x381, 0x383 |

Channels that don't match any anchor are tagged `ch<N>`.

**Timestamps:** Anchored by parsing `YYYYMMDD_HHMMSS` from the filename (standard
`can_logger.py` naming). Falls back to file mtime. Frame-relative timestamps are added
to produce nanosecond-precision InfluxDB timestamps.

**Session tag:** Derived from filename: `canlog_20260315_143000_M0_T0.log` → `2026-03-15_M0`.
Override with `--session` if needed.

**Known limitation — validity signal masking:** Many signals have a paired validity bit
(e.g. Coda cell voltages, GMLAN `*_Validity` signals). When validity is low the signal
value is meaningless but is still written to InfluxDB and plotted in Grafana. Two
sub-problems to solve:

1. **DBC encoding:** DBC has no native validity-gating concept. Leading candidate is a
   naming convention (`FooSignal` + `FooSignal_Validity`) so the uploader can
   automatically suppress `FooSignal` points where its paired validity bit is 0.
   Also worth checking whether cantools `invalid` value support causes `decode_message`
   to return `None` for out-of-range values (which the uploader already skips).
2. **Grafana side:** If invalid points do reach the DB, options are an InfluxQL `WHERE`
   clause filtering on a known sentinel value, or a Grafana "Filter by value" transform.
   The cleaner fix is upload-time suppression (sub-problem 1) so invalid points are
   never written.

**Updating after DBC changes:** Use `--delete` to drop the session's data before re-uploading.
Or run directly in InfluxQL:
```sql
DROP SERIES FROM signals WHERE "vehicle"='vtrux' AND "session"='2026-03-15_M0'
```

**Examples:**
```bash
# Basic upload using vehicle defaults
py -3.11 tools/influx_upload.py canlog_20260315_143000_M0_T0.log --vehicle vtrux

# Upload all logs in a folder (non-recursive)
py -3.11 tools/influx_upload.py projects/vtrux/logs/ --vehicle vtrux

# Upload a folder with a success log so interrupted runs can resume
py -3.11 tools/influx_upload.py projects/vtrux/logs/ --vehicle vtrux \
    --success-log projects/vtrux/notes/artifacts/upload_done.txt

# Add an extra DBC on top of the defaults
py -3.11 tools/influx_upload.py <log> --vehicle coda --dbc projects/coda/extra.dbc

# Include raw bytes for frames not in any DBC
py -3.11 tools/influx_upload.py <log> --vehicle vtrux --raw

# Re-upload after DBC changes
py -3.11 tools/influx_upload.py <log> --vehicle vtrux --delete

# Dry run (shows bus detection and point counts, no writes)
py -3.11 tools/influx_upload.py <log> --vehicle vtrux --dry-run
```

---

## uds_interrogator.py
*Source last modified: 2026-03-15*
*API reference: `canre/uds/uds.md`*

Scans a CAN bus for UDS-responding ECUs and fully interrogates each one.
Outputs a JSON report plus a human-readable console summary.

Requires: `pip install can-isotp` (installs as `isotp` module; package name is `can-isotp` not `isotp`)

**Usage:**
```
py -3.12 tools/uds_interrogator.py [options]

  --bitrate N           CAN bitrate in bps (default: 500000)
  --brands BRANDS       Comma-separated dongle brands (default: all detected)
  --scan-range S:E      Hex address range e.g. 0x600:0x7EF (default: 0x600:0x7EF)
  --scan-timeout MS     Per-address timeout ms during scan (default: 50)
  --request-timeout MS  Per-request timeout ms during interrogation (default: 200)
  --module ADDR         Skip scan; interrogate only this address e.g. 0x7E0
  --output FILE         JSON output path (default: auto-named in project root)
  --output-dir DIR      Directory for auto-named output
  --no-kwp              Skip KWP2000 0x18 DTC queries
  --no-dtc              Skip all DTC queries (0x19 and 0x18)
  --verbose / -v        Print per-address and per-module progress
  --debug               Enable debug logging
```

**Scan coverage:** 0x600-0x7EF by default (496 addresses, ~25 s worst case).
Each address is probed with DiagnosticSessionControl default (0x10 0x01).

**Interrogation per module:**
1. Extended session (0x10 0x03)
2. All F1xx ECU identity DIDs via ReadDataByIdentifier (0x22)
3. Service support probes (0x10, 0x19, 0x22, 0x27, etc.)
4. All 10 UDS ReadDTCInformation (0x19) subfunctions
5. KWP2000 ReadDTCByStatus (0x18) for 5 DTC groups
6. Return to default session

**Non-standard response ID detection:** the tool taps all received CAN frames
during each probe and flags ECUs that respond on an ID other than request_id+8.

**JSON report structure (abbreviated):**
```json
{
  "generated_at": "ISO8601",
  "hardware": "ixxat HW379841",
  "bitrate": 500000,
  "scan_range": {"start": "0x600", "end": "0x7EF"},
  "modules_found": 2,
  "modules": [{
    "request_id": "0x7E0", "response_id": "0x7E8",
    "session_extended": true,
    "dids": {"0xF190": {"responded": true, "value": "VIN...", ...}},
    "service_probes": {"0x19": {"supported": true, "nrc": null}},
    "dtc_results": {"0x02_reportDTCByStatusMask": {"responded": true, "dtc_count": 2, ...}},
    "kwp_dtc_results": {"0xFF00_all": {"responded": false, "nrc": "0x11"}}
  }]
}
```

---

## make_graph.py
*Source last modified: 2026-03-12*
*Notes and .gdf format findings: `tools/savvycan-graphing.md`*

Generates SavvyCAN Graph Definition (`.gdf`) files from DBC signals. Replaces the slow
matplotlib path for exploratory graphing — load the output via SavvyCAN right-click →
"Load graph definitions from file".

**Usage:**
```
py -3.12 tools/make_graph.py --dbc PATH [PATH ...] --signal MSG.signal [MSG.signal ...]
                              [--output PATH] [--append] [--stride N] [--line-width N]

  --dbc PATH [...]    DBC file(s) to search for signals. Searched in order; first match wins.
                      Handles extended-ID DBCs that lack the 0x80000000 marker.
  --signal MSG.signal Signal(s) as MessageName.signal_name. Repeatable.
  --output PATH       Output .gdf file (default: graph_output.gdf in CWD)
  --append            Append to existing .gdf; color cycling continues from last existing signal.
  --stride N          Plot every Nth point (default: 1)
  --line-width N      Line width in pixels (default: 1)
```

**Multi-DBC workflow** — use when signals span multiple sources (main DBC, GMLAN, provisional):
```bash
# Step 1: create .gdf with main DBC signals
py -3.12 tools/make_graph.py \
    --dbc projects/vtrux/BelInverter.dbc \
    --signal BELINV_hvBatteryAndCharger.BELINV_hvBatteryVoltage \
             BELINV_hvBatteryAndCharger.BELINV_hvBatteryCurrent \
    --output projects/vtrux/notes/artifacts/my_graph.gdf

# Step 2: append a signal from a second DBC
py -3.12 tools/make_graph.py \
    --dbc projects/vtrux/epri-obd-bus.dbc \
    --signal SomeMsg.SomeSignal \
    --output projects/vtrux/notes/artifacts/my_graph.gdf --append
```

**SavvyCAN workflow:**
1. Open log in SavvyCAN (drag-drop or File → Open)
2. Open Graph window
3. Right-click graph area → "Load graph definitions from file" → select `.gdf`

**Color cycling:** 8-color palette (blue, orange, green, red, purple, brown, pink, gray).
`--append` reads the existing file to count signals and continues the cycle correctly.

**BE signal caveat:** Big-endian signals emit a warning with the raw cantools start bit.
SavvyCAN may use a different bit-addressing convention — hand-edit the `.gdf` if needed.

**Notes:**
- DBC files with overlapping signals (e.g. large GMLAN DBCs) load with `strict=False` — noisy
  "Overwriting message" warnings are suppressed automatically.
- Extended CAN IDs stored without the 0x80000000 marker are fixed automatically on load.
- Save `.gdf` files to `projects/<vehicle>/notes/artifacts/` for reuse across sessions.

---

## can_monitor.py
*Source last modified: 2026-03-09*

Live CAN monitor with vehicle-aware GUI. Auto-detects dongles, sniffs for 5 s to identify which
physical channel is which logical bus (anchor detection), then opens a PyQt5 window showing decoded
signals for the active vehicle mode. Simultaneously writes a BUSMASTER log if `--output` is given.

**Usage:**
```
py -3.12 tools/can_monitor.py --vehicle coda [options]

  --vehicle, -v   Vehicle name: coda | vtrux  [required]
  --bitrate, -b   CAN bitrate in bps (default: 500000)
  --brands        Comma-separated brands to capture from (e.g. ixxat,kvaser)
  --output, -o    Optional BUSMASTER log file for simultaneous capture
  --output-dir,-d Directory for auto-named log file
  --debug         Verbose logging
```

**Vehicle profiles:** `projects/<vehicle>/gui_profile.py` — each exports a `PROFILE` instance
(subclass of `canre.gui.base_profile.VehicleProfile`).

**Mode detection:** `ModeRule` objects declare conditions (ID presence or signal value predicate).
A mode is active if ANY of its rules evaluates True. Modes are evaluated in priority order; the
last mode is the fallback default. Mode switches automatically on every 50 ms tick.

**Coda modes (charging GUI implemented 2026-03-09):**

| Mode | Trigger signals |
|------|----------------|
| charging | HVPowermode=5 OR Chargemode=3 OR HVBattCharging=1 OR CMS messages present (0x27B) |
| idle | B CAN alive (0x383 present) |

**Charging layout signals (all B CAN):**
- Battery Pack: SoC (0x383), PackVoltage/PackCurrent/BattSentChargeLimit (0x275)
- Cell Voltages: min/avg/max mV, spread, cell IDs (0x381 BMSVminVmax) — spread alert > 50 mV
- Pack Temperature: avg/max/min degC (0x382 BMSThermal)
- Charger Input CMS: AC voltage/current/power (0x27B CMSInputValues)
- Charger Output CMS: HV out V/I/P (calc), LV out V/I (0x27C CMSOutputValues)
- Charger Temps CMS: case/PFC/HV1/HV2 degC (0x27A CMSTempStatus)
- BMS Charger Command: current cmd, max voltage (0x050 BMSChargerCmd)
- System Status: HVPowermode, Chargemode, BMSmode, fault severity/code, fault lamp, cable/full flags
- HVAC/Thermal: PTC power, battery fan PWM, radiator fan PWM (0x276), DCDC 14V (0x1D5)

**Dependencies:** `PyQt5`, `cantools`, `python-can` (all already project deps)

**Architecture:** `canre/live/receiver.py` (hardware), `canre/live/vehicle_configs.py` (anchor data),
`canre/gui/` (framework: `base_profile`, `bus_decoder`, `widgets`, `main_window`).

---

## can_logger.py
*Source last modified: 2026-03-09*

Multi-device CAN logger. Auto-detects all connected dongles and logs traffic from all of them simultaneously to a single BUSMASTER-format `.log` file.

**Refactored 2026-03-09:** CAN hardware plumbing (`CANBusLogger`, `detect_all_can_interfaces`, USB reset) moved to `canre/live/receiver.py`. Queue 4-tuple format changed from 3-tuple to `(timestamp, bus_id, msg, direction)` where direction is `"Rx"`. Behavior and CLI interface unchanged.

**Usage:**
```
tools\can_logger_admin.bat [options]        <- preferred (auto-elevates for ixxat recovery)
py -3.11 tools/can_logger.py [options]     <- direct (must be in admin prompt for ixxat recovery)

  --output, -o    Output log file. Bare filename (no directory) is placed in --output-dir.
                  Default: auto-generated canlog_YYYYMMDD_HHMMSS.log in --output-dir.
  --output-dir,-d Directory for output log files. Default: project root (parent of tools/).
  --bitrate, -b   CAN bitrate in bps (default: 500000)
  --brands        Comma-separated brands to capture from, e.g. kvaser or ixxat,kvaser
                  Default: auto-detect all brands
  --debug         Verbose logging
```

**Supported hardware:** ixxat, kvaser, pcan, socketcan

**Output format:** BUSMASTER (`.log`), compatible with all `canre` parsers.

**Notes:**
- Use `--brands` to restrict capture to specific dongles. Required for loopback testing so the logger doesn't also capture from the dongle that's transmitting.
- Each detected dongle becomes a separate channel (1-indexed) in the log file.
- **Administrator privileges required** when ixxat dongles are connected. Use `can_logger_admin.bat` (self-elevating via UAC) rather than opening an admin cmd manually. Without admin, ixxat overflow recovery silently fails.
- **ixxat overflow recovery:** if a dongle latches in hardware overflow, the logger auto-resets it via PowerShell `Disable-PnpDevice` / `Enable-PnpDevice` targeting the specific dongle by `unique_hardware_id` (`USB\VID_08D8&PID_0008\HWxxxxxx`). Other connected ixxat dongles are unaffected. Full details in `tools/README-can_logger.md`.

---

## can_replayer.py
*Source last modified: 2026-02-18 21:48:56*

Plays back a captured log file through connected CAN hardware at the original timing. Complementary to `can_logger.py`.

**Usage:**
```
py -3.11 tools/can_replayer.py <logfile> [options]

  logfile        Path to log file (auto-detects format)
  --bitrate, -b  CAN bitrate in bps (default: 500000)
  --brands       Comma-separated brands to transmit on, e.g. ixxat
                 Default: auto-detect all brands
  --bus BUS_ID   Only replay frames from this log bus/channel ID.
                 Default: replay all buses.
  --speed, -s    Replay speed multiplier (default: 1.0). Use 0 for no delay.
  --loop, -l           Loop replay indefinitely (Ctrl+C to stop)
  --skip-confirmation  Skip the "Press Enter to start" prompt (use for non-interactive/scripted runs)
  --debug              Verbose logging
```

**Supported input formats:** BUSMASTER, candump, SavvyCAN, PEAK TRC (auto-detected)

**Channel mapping:**
- If the log has the same number of channels as connected dongles, log channel N is sent through dongle N (1:1).
- Otherwise all frames go through the first dongle.

**Notes:**
- Prints a startup summary with the channel mapping and waits for Enter before transmitting (skip with `--skip-confirmation`).
- Timing uses `time.perf_counter()` for sub-millisecond accuracy.
- On Ctrl+C, finishes the current frame then shuts down cleanly.

**Loopback test (Ixxat TX → Kvaser RX):**
```
# Terminal A — capture on Kvaser only
py -3.11 tools/can_logger.py --brands kvaser --output verify.log

# Terminal B — replay through Ixxat only
py -3.11 tools/can_replayer.py <capture.log> --brands ixxat
```
Start the logger first, then the replayer. Frame counts should match to within a handful of frames.

---

## status_events.py
*Source last modified: 2026-03-28 12:57:46*

Status event finder with two modes: **auto-discovery** (default) surveys all IDs and auto-selects discrete status signals, or **watch-profile** uses a manually curated signal set. Tracks byte-level and optionally bit-level transitions, filters to quiet signals, detects and excludes rolling counters, and clusters co-occurring transitions into events.

**Usage:**
```
python tools/status_events.py <log> [log ...] [options]

  log                       Log file(s). Pass multiple T-chunk files to merge at runtime.
  --bus N                   Filter to single bus number
  --watch-profile NAME      Use a named vehicle-specific signal set (e.g. "coda-charging")
  --auto                    Auto-discover candidates (default when no --watch-profile)
  --max-transitions N       Quiet-signal threshold (default: 50)
  --gap SECONDS             Cluster gap in seconds (default: 2.0, 0=disable clustering)
  --bits                    Include bit-level transitions
  --output FILE             Write report to file instead of stdout
```

**Modes:**

- **Auto-discovery** (default): Runs `run_survey()` on the log, selects bytes with `unique_count` 2–16 as byte-level candidates. With `--bits`, bytes with `unique_count` 17–256 are also scanned at bit level. Skips extended (29-bit) IDs and constant bytes.
- **Watch-profile**: Selects from `WATCH_PROFILES` dict in the source. Currently available: `coda-charging`. Signal annotations (human-readable labels) are shown in profile mode.

**Analysis pipeline:**

1. **Load** — parses entire log into memory via `parse_file()`
2. **Candidate selection** — from survey or watch-profile
3. **Transition scan** — single pass: tracks byte-level state changes; optionally XOR-decomposes into bit-level transitions; inline counter detection (>80% sequential +1/-1, only for bytes with >4 unique values)
4. **Classification** — each signal tagged QUIET (count <= threshold), NOISY (above), or COUNTER
5. **Clustering** — quiet transitions sorted by time, split into clusters at gaps > `--gap` seconds
6. **Output** — three sections: signal inventory, event clusters, full timeline

**Output sections:**

1. **Signal Inventory** — all candidate signals with transition counts, sorted ascending, tagged QUIET/NOISY/COUNTER
2. **Event Clusters** — groups of co-occurring transitions with time range, transition count, and signal count per cluster. Single-transition clusters marked "(isolated)"
3. **Full Timeline** — flat chronological list of all quiet-signal transitions

**Vehicle-specific config** (top of source file, clearly marked):

- `WATCH_PROFILES` — named signal sets per vehicle/session. Currently: `coda-charging` (B CAN bus 3 + C CAN bus 1 charger/BMS signals)
- `SIGNAL_NOTES` — human-readable labels keyed by `(bus, id, byte)` or `(bus, id)`. Only shown in watch-profile mode.

**Imports:** `canre.parsers.autodetect.parse_file`, `canre.analysis.survey.run_survey`

---

## survey.py
*Source last modified: 2026-02-15 12:39:49*

CLI wrapper around `canre.analysis.survey`. Surveys CAN bus traffic from a log file or directory, reporting an ID inventory with frame counts, frequencies, and byte-level statistics.

**Usage:**
```
python tools/survey.py <path> [options]

  path             Log file or directory of log files
  --bus N          Filter to specific bus number
  --output, -o     Save results to JSON file
```

**Input handling:**
- Single file: parses and surveys directly.
- Directory: detects capture groups (`_M*_T*` or `_T*` pattern), merges grouped files, surveys each group separately. If no groups found, surveys each `.log` individually.

**Output:** Formatted survey table to stdout. With `--output`, saves JSON (directory mode appends group name to filename).

**Imports:** `canre.parsers.parse_file`, `canre.analysis.survey`, `canre.utils.merge`

---

## analyze_id.py
*Source last modified: 2026-05-02 23:28:11*

Deep-dive analysis of a single CAN arbitration ID. Three separate passes: bit-level statistics, rolling counter detection, and checksum detection. Optionally decodes against a DBC file.

**Usage:**
```
python tools/analyze_id.py <log> [log ...] [options]

  log              Log file(s). Pass multiple T-chunk files to merge at runtime.
  --id ID          CAN ID in hex (e.g. 0x123) [required]
  --bus N          Filter to specific bus number
  --dbc FILE       Optional DBC file for signal decoding context
  --start SECS     Start of time window in seconds (relative to capture start)
  --end SECS       End of time window in seconds (relative to capture start)
```

**Output sections:**
1. Per-byte and per-bit statistics (ranges, entropy, toggle rates)
2. Counter detection (sequential +1/-1 patterns with confidence)
3. Checksum detection (XOR, sum, CRC-8 J1850, nibble sum per byte position)
4. DBC signal decode (only with `--dbc`)

**Notes:** `--id` is always parsed as hex regardless of `0x` prefix. All three analysis passes reuse a single in-memory frame list (log loaded once).

---


## compare.py
*Source last modified: 2026-02-15 12:40:04*

Compares two CAN bus captures: IDs unique to each, and byte-level diffs for shared IDs.

**Usage:**
```
python tools/compare.py <log_a> <log_b> [options]

  log_a            First log file
  log_b            Second log file
  --ids-only       Only compare ID presence; skip byte-level diff
  --bus N          Filter to specific bus number
```

---


## extract_timeseries.py
*Source last modified: 2026-03-28 12:58:23*

Extracts a raw signal time series from a CAN log for a specific ID and byte range. Outputs CSV.

**Usage:**
```
python tools/extract_timeseries.py <log> [log ...] [options]

  log              Log file(s). Pass multiple T-chunk files to merge at runtime.
  --id ID          CAN ID in hex (e.g. 0x123) [required]
  --bytes RANGE    Byte index or range, e.g. '2' or '2-3' [required]
  --endian MODE    'big' or 'little' (default: big)
  --signed         Interpret as signed
  --output, -o     Output CSV file (default: stdout)
  --bus N          Filter to specific bus number
```

**Notes:** `--bytes` range is inclusive on both ends. `--id` always parsed as hex.

**Limitation — no DBC mux / validity gating:** This tool extracts raw bytes directly from frames without consulting the DBC. It has no concept of multiplexed messages or validity flags. For multiplexed signals (e.g. `0x200 ESC_FrontWheelSpeeds`, where B0 is a sub-frame selector and wheel speeds are only valid when B0=0x00), the tool will include all frames regardless of mux state, producing spurious values from non-speed sub-frames. Workaround: post-filter the CSV on a known validity byte/value before plotting. **Outstanding feature:** add a `--gate-byte`/`--gate-value` option that reads the DBC mux definition for the target signal and drops frames where the mux signal does not match the expected value.

---

## dbc_skeleton.py
*Source last modified: 2026-02-15 12:40:14*

Generates a skeleton DBC file from observed CAN traffic. One message per observed ID, with DLC from traffic.

**Usage:**
```
python tools/dbc_skeleton.py <log> [options]

  log              Log file path
  --output, -o     Output DBC file (default: skeleton.dbc)
  --bus N          Filter to specific bus number
```

---

## dbc_validate.py
*Source last modified: 2026-02-15 12:40:16*

Validates a DBC file against actual CAN traffic. Reports coverage, undefined IDs, and decode errors.

**Usage:**
```
python tools/dbc_validate.py <dbc> <log> [options]

  dbc              DBC file path
  log              Log file path
  --bus N          Filter to specific bus number
```

---

## merge_logs.py
*Source last modified: 2026-02-15 12:40:21*

Merges chunked CAN log captures. Supports both `_M{bus}_T{chunk}` (BUSMASTER multi-bus) and `_T{chunk}` (timestamp-keyed sessions) naming patterns. Detects capture groups in a directory and either prints a frame count summary or writes merged CSV.

**Usage:**
```
python tools/merge_logs.py <directory> [options]

  directory        Directory containing log file chunks
  --output, -o     Output CSV file (default: print summary only)
  --group          Process only this named capture group
```

**Output format:** CSV with columns: `timestamp, bus, id, extended, dlc, data`. Multiple groups get separate files with group name appended to stem.

---

## list_sessions.py
*Source last modified: 2026-02-16 19:34:14*

Lists and groups CAN log files in a directory by capture session.

**Usage:**
```
python tools/list_sessions.py <path> [options]

  path             Directory containing log files
  --json           Output as JSON instead of human-readable
```

**Output:** Session names with file counts and filename ranges. JSON mode outputs keyed by session name with `file_count` and `files`.

---






