# projects/vtrux/tools/

> **Staleness check:** Each section shows a `Source last modified` timestamp. If the `.py` file's mtime is newer than the timestamp shown here, re-read the source before relying on this documentation.

Vtrux-specific CLI analysis tools. These scripts use the `canre` framework but
are tightly coupled to Vtrux signal definitions and DBC content.

---

## diagnose_vtrux.py
*Source last modified: 2026-08-26*

General-purpose Vtrux diagnostic tool. Decodes all known fault and status signals
from a PT-bus log (any log type: battery reconnect, drive, idle, fault investigation)
and produces:

- **Initial state snapshot** — first observed values of every signal
- **System events timeline** — chronological list of every discrete state change,
  with fault-tagged transitions (EPO, alarm, HVIL open, contactor faults, emergency
  stops, HCU failure/shutdown)
- **Final state snapshot** — last observed values
- **Fault summary** — all detected fault conditions, initial-state faults, and
  repeated events deduplicated with counts; HVIL open note if interlock never closed

**Signals covered:**

| ID | Message | Fields |
|----|---------|--------|
| 0x053 | HCU OperatingMode/State | op_mode, op_state |
| 0x054 | GENE MCU | rpm, emerstop |
| 0x044 | TRAC MCU (OBD bus) | rpm, emerstop |
| 0x400 | HSC BCM control | hsc_enable, hsc_epo, hsc_mainc_close, hsc_leakage_ena |
| 0x410 | BMS status | hvil_mon, alarm, epo, ready, bms_b1/b2 state, ibat, soc, vbat, gfd |
| 0x420 | BMS limits | cell_overvolt, cell_undervolt, iso_r, chg_max, dis_max |
| 0x430 | BMS data1 | mod_ena, veh_mon, chga_ena/mon, cell V/T, lvbat |
| 0x440 | BMS data2 | mainc_stat (16-state), vbus_pos/neg, fgd |
| 0x411 | BMS SoC hi-res | soc_hires |
| 0x460 | BMS fault-record annunciator | record stack assembled from the page-multiplexed rotation: standing records in initial/final snapshots, pushes/clears in the timeline with catalog names (`FC 22 02` steady-state fault, `F0 E0 00` precharge abort, `F6` contactor/interlock family, ...); boot-time NVM restores labeled vs fresh pushes (EPO-coincident additions always count as pushes); DLC=8 filter guards OBD-bus 0x460 contamination. Catalog: `notes/battery-fault-codes.md` (added 2026-08-26) |
| 0x592 | HCU sensor | ignition, evse_switch, export_power |
| 0x617 | VCM system-state flag | vcm_sysstate (B7: NORMAL/STATE_C9/FAULT_ACTIVE; FAULT_ACTIVE fault-tagged, sets ~0.3 s after EPO in every mode) (added 2026-08-26) |
| 0x065B | HCU DTC | dtc_code, dtc_name |

**Usage:**

```
py -3.12 projects/vtrux/tools/diagnose_vtrux.py FILE [FILE ...]
py -3.12 projects/vtrux/tools/diagnose_vtrux.py "logs/session_M1_T*.log"
py -3.12 projects/vtrux/tools/diagnose_vtrux.py FILE --output report.txt
```

Glob patterns are expanded by the script (quote them on Windows to prevent shell interference).
Multi-file inputs are merged by timestamp and re-zeroed to t=0.

---

## vtrux_charge_failure_analysis.py
*Source last modified: 2026-03-29*

Analyzes one or more CAN log files from the Vtrux powertrain bus and produces
a structured plain-text report covering:

- Bel charger state machine and fault register (confirmed, from BelInverter.dbc)
- J1772 connection health
- Vehicle charge command / VCU-to-charger state (0x18FFD9C0)
- BMS cluster -- Tier 1 (confirmed signals decoded to physical values) and
  Tier 2 (unconfirmed bytes reported as raw change log)
- HSC BCM control bits (0x0400 B0 bits 0-3: hsc_bcm_enable, hsc_bcm_epo,
  hsc_bcm_mainc_close, hsc_bcm_leakage_ena) -- full timeline to cover
  before/after battery swap
- Voltage/current profile around each failure event
- Failure pattern classification

Replaces the piecemeal approach of running fault_bits_analysis.py,
j1772_analysis.py, and charge_intermittency_analysis.py separately.

**Usage:**

```
py -3.12 projects/vtrux/tools/vtrux_charge_failure_analysis.py FILE [FILE ...]
py -3.12 projects/vtrux/tools/vtrux_charge_failure_analysis.py --dir DIR [--session SFX]

  FILE [FILE ...]   One or more log files, merged by timestamp.
  --dir DIR         Scan directory for capture groups.
  --session SFX     With --dir: restrict to sessions whose prefix contains SFX.
  --output, -o      Write report to file (default: stdout).
  --window, -w      Analysis window in seconds around each failure event (default: 120).
```

**Examples:**

```
# Single standalone log
py -3.12 projects/vtrux/tools/vtrux_charge_failure_analysis.py "logs/full charge then fail.log"

# Multi-chunk session from a directory, session M1_b only
py -3.12 projects/vtrux/tools/vtrux_charge_failure_analysis.py --dir logs/ --session M1_b

# Write report to file
py -3.12 projects/vtrux/tools/vtrux_charge_failure_analysis.py "logs/full charge then fail.log" -o notes/artifacts/report.txt
```

**See also:** `notes/plans/vtrux-charge-failure-analysis-tool.md` for full
design rationale and per-section implementation notes.

---

## extract_obd.py
*Source last modified: 2026-04-05*

Extracts and decodes OBD-II and J1939 DM diagnostic reads from a recorded CAN log file. General-purpose (not Vtrux-specific) but lives here as the primary use case is Vtrux log analysis.

Covers:
- **OBD-II** (ISO 15765-4): requests on 0x7DF/0x7E0–0x7E7, responses on 0x7E8–0x7EF
- **J1939 DM1/DM2** (SAE J1939-73): active/previously-active DTC broadcasts via PGN FECA/FECB
- ISO-TP multi-frame reassembly for long responses
- Decodes Mode 01 PID 01 (MIL on/off, stored DTC count), Mode 03/07/0A (stored/pending/permanent DTCs), Mode 09 (vehicle info), negative responses (NRC)

**Usage:**
```
py -3.12 projects/vtrux/tools/extract_obd.py LOG [LOG ...]
py -3.12 projects/vtrux/tools/extract_obd.py LOG --bus 1
py -3.12 projects/vtrux/tools/extract_obd.py LOG --j1939-only
py -3.12 projects/vtrux/tools/extract_obd.py LOG --output report.txt
```

---

## vtrux_dtc_interrogation.py
*Source last modified: 2026-03-30*

Active DTC interrogation tool. Connects to all detected CAN hardware, identifies
each bus using anchor IDs, sends OBD-II DTC requests, logs all traffic, and decodes
responses in real time.

**Two-phase operation:**
1. **Ident phase** (default 3s): listen-only, identify PT/OBD/Vehicle buses by anchor IDs.
2. **Request + log phase** (default 10s): send Mode 03/07/0A at `0x7DF` (functional broadcast)
   and `0x7E0` (VCM physical) on each bus, then log all responses.

**Decoded in real time:**

| ID / Range | What | How |
|---|---|---|
| `0x065B` | HCU proprietary DTC (PT bus) | `(B6 << 8) | B7`, 29-entry lookup table from epri-decompile.md |
| `0x7E8-0x7EF` | OBD-II Mode 43 stored DTC responses | Standard ISO 15765-4 parsing |
| `0x7E8-0x7EF` | Negative response codes (0x7F) | NRC byte decoded to text |

Full session log saved to `notes/artifacts/dtc_interrogation_<timestamp>.log` (BUSMASTER format, readable by all project analysis tools).

**Usage:**
```
py -3.12 projects/vtrux/tools/vtrux_dtc_interrogation.py
py -3.12 projects/vtrux/tools/vtrux_dtc_interrogation.py --log-time 15
py -3.12 projects/vtrux/tools/vtrux_dtc_interrogation.py --output my_session.log
py -3.12 projects/vtrux/tools/vtrux_dtc_interrogation.py --brands ixxat

  --output, -o      Log file path. Bare filename goes in artifacts/. Default: timestamped.
  --ident-time      Seconds to listen before sending (default: 3).
  --log-time        Seconds to log after sending requests (default: 10).
  --brands          Comma-separated dongle brands (e.g. ixxat,kvaser). Default: all.
```

**Notes:**
- Ignition must be ON for modules to respond.
- If `0x065B` does not appear, the HCU DTC request address on the PT bus is still unknown
  (the EPRI app was passive — it never sent requests). Analyze the log to see what came back
  near the request timestamps, then refine the trigger address.
- Log is in BUSMASTER format and can be opened with `survey.py`, `analyze_id.py`, etc.

---

## analyze_session.py
*Source last modified: 2026-02-16 19:36:45*

Charger fault event analyzer for individual Bel Inverter / Vtrux charging sessions. Merges multi-chunk logs, decodes known charger CAN messages (extended IDs on `0x18FFDxC0`), and produces a fault timeline with windowed voltage/current context.

**Usage:**
```
py -3.12 projects/vtrux/tools/analyze_session.py <files...> [options]

  files            One or more log files (merged in order)
  --window SECS    Window around fault events (default: 5)
  --name NAME      Session name for display (default: from filename)
```

**Decoded messages (hardcoded):**

| ID | Name | Key Signals |
|---|---|---|
| `0x18FFD4C0` | BINV_status | Multiplexed: status bits (mux=0), fault bits (mux=3), state |
| `0x18FFD7C0` | hvBatteryAndCharger | hvBatteryVoltage, hvBatteryCurrent, chargerInputVoltage, chargerInputCurrent (LE signed x 0.05) |
| `0x18FFD9C0` | chargeInfo | maxAvailableChargingCurrent (LE signed x 0.05), vehicleState |
| `0x18FFD8C0` | J1772 info | Tracked, not decoded inline |
| `0x18FFD5C0` | chargerTemp | Tracked, not decoded inline |

**Output:** Session summary, charger states, fault bit transitions, status transitions, failure timeline with windowed V/I data, V/I profile.

**Note:** Forces UTF-8 stdout on Windows.

---

## analyze_failed_charges.py
*Source last modified: 2026-02-16 19:42:09*

Batch wrapper around `analyze_session.py`. Discovers capture sessions in a directory and runs `analyze_session` on each.

**Usage:**
```
py -3.12 projects/vtrux/tools/analyze_failed_charges.py <path> [options]

  path             Directory containing failed charge log files
  --session NAME   Only analyze a specific session (e.g. "M0")
  --window SECS    Window around fault events (default: 5.0)
```

**Output:** Session inventory, then per-session analysis output from `analyze_session()`.

