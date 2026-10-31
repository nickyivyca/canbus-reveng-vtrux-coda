# Coda EV — CAN Reverse Engineering Project

## Vehicle Background

The Coda EV (2012) is a battery-electric vehicle based on the Chinese Hafei Saibao platform,
with an entirely new powertrain developed by Coda Automotive (US). The company went bankrupt
shortly after launch (~2013), leaving limited documentation. The vehicle has an unusual
architecture with multiple CAN buses and a mix of US-developed EV components and Chinese body
electronics.

Battery chemistry: **LFP (Lithium Iron Phosphate)**, 104 cells in series.
Nominal pack voltage ~338V (104 × ~3.25V). Cell voltage range: 2.5–3.65V.
LFP has a flat discharge curve — pack voltage does **not** track SoC through the middle range;
only useful as an absolute-value anchor at endpoints.


---

## CAN Bus Architecture

All four buses are accessible at the OBD-II (J1962) connector.

```
                         [J1962 OBD-II]
                               |
                           Diag CAN
                               |
         B CAN --------[ GWM ]-------- D CAN
         (Battery)    (Gateway,         (Driveline)
                       NM Master)

         C CAN --------[ BMS ] (separate diagnostic output, direct cell data)

         Motor CAN ----[ MCM ] (private sub-bus via DLCM, not OBD-accessible)
```

### Bus Summary

| Bus           | OBD-II Pin Access                              | Relevant DBCs           | Purpose |
|---------------|------------------------------------------------|-------------------------|---------|
| **B CAN**     | CAN-H: 2 <br> CAN-L: 3                        | `CODA-B-CAN.dbc`        | Battery-side body & powertrain support modules |
| **D CAN**     | CAN-H: 10 <br> CAN-L: 11                      | `CODA-D-CAN.dbc`        | Driveline control modules |
| **C CAN**     | CAN-H: 7 <br> CAN-L: 15                       | `CODA-C-CAN-cells.dbc`  | BMS secondary diagnostic — direct cell voltages & temps |
| **Diag CAN**  | CAN-H: 6 <br> CAN-L: 14 <br> (standard OBD-II pins) | —                 | Scan tool / diagnostic routing through GWM. See `coda-diagnostics/` |
| **Motor CAN** | Not accessible                                 | —                       | Private DLCM↔MCM sub-bus |

### Bus Identification — Anchor IDs

**Channel numbers in log files are arbitrary** (dongle insertion order varies per session). Always identify buses by their message content, not by channel number.

**Audited 2026-09-29** against 45 multi-channel captures
(`notes/artifacts/anchor_exclusivity_audit.py`). Four ids this table previously published as
anchors are gateway rebroadcasts and cannot identify a bus; they are listed as withdrawn below
rather than deleted, because they appear in older analysis whose bus labels are therefore
unevidenced.

| Bus   | Anchor IDs | Condition | Status |
|-------|-----------|-----------|--------|
| C CAN | 0x000–0x019 **except 0x004 and 0x00C** (cell voltages, 104 cells) | Always present | **Audited exclusive**, 45 captures; 0x004 and 0x00C withdrawn 2026-10-09 (below) |
| B CAN | 0x48A (DCDC), 0x381 (cell min/max/avg) | Always present when key-on | **Audited exclusive**, 45 captures |
| B CAN | 0x615–0x617 (charger) | Only during charging | **Audited exclusive**, 45 captures |
| D CAN | 0x308, 0x312, 0x325, 0x330, 0x580 | Always present when key-on | **Audited exclusive**, 45 captures |

**Withdrawn as anchors — these are rebroadcast and identify nothing:**

| Was listed as | IDs | Measured split |
|---|---|---|
| B CAN anchors, "High" | 0x1D5 (DCDC), 0x275 (BMS limits), 0x383 (SoC) | 50.00 % — e.g. 0x1D5 `{ch2: 5648, ch1: 5648}` |
| B CAN charger range, "Definitive" | 0x274–0x27D **as a range**: 0x275 and 0x276 are rebroadcast | 50.00 % |
| "an anchor such as 0x212" (C CAN section) | 0x212 | 50.00 % — `{ch2: 7299, ch1: 7299}` |

**How the audit decides, and why presence is not the test.** The GWM rebroadcasts frame for
frame, so a pass-through shows a near-exact even split between two channels — every confirmed
case measured 49.93–50.00 % minority share, which is the same mechanism as the doubled-count
hazard below. Stray traffic looks nothing like that: C CAN `0x004` and `0x00C` each appear once
on a second channel against 901 real frames, with payloads that are plainly not cell voltages,
and the cell range is exclusive as a *frame split*. A first version of the audit tested only "does this id appear
on two channels" and reported the cell range as rebroadcast on the strength of those single
frames — one frame deciding a verdict, the failure that AGENTS.md's discriminator rule exists to
prevent. Verdicts here are taken from the frame split, and the counts are printed so they can be
checked.

**`0x004` and `0x00C` are withdrawn as presence anchors (2026-10-09).** The "stray" frames
above are not noise. A sweep of all 1082 captures in `CANLogs/CodaLogs/` found `0x00C` on the
D CAN channel in 3 captures and on the B CAN channel in 14, at 1–17 frames per capture, with
payloads such as `00 00 02 00 00 00 00 1A` followed 2 s later by `00 00 04 00 00 00 00 23`.
`0x004` (all-zero payload, 1–10 frames per capture) appears the same way on the B CAN channel
of 28 captures (its withdrawal: user decision, 2026-10-09).

**Corrected 2026-10-28: these are the gs_usb adapter's CAN error reports, not a rare message
sharing the id.** The Android logger writes the adapter's error frames as ordinary standard
frames whose id is the SocketCAN error-class mask (`0x004` controller, `0x00C` controller +
protocol) -- see `android-app/notes/outstanding-changes.md` Bug 11. The `0x00C` payloads fit
that layout: `data[2]` is the protocol error type (`0x02` form, `0x04` stuff), `data[7]` the
receive error counter. The 2026-10-09 reasoning -- a corrupt frame cannot pass CAN's CRC, so
the id must be shared with another message -- was written before this was understood: these
are not frames another node sent; the adapter generates them when it detects an error on the
bus.

The withdrawal stands, for a different reason: an error report can appear on any channel, so
it identifies no bus. A presence-based discriminator that lets any frame of another bus's
anchor veto a channel (`tools/codasim/io/logreplay.py`) rejected the D CAN channel of
`coda_20260801_122531_T0` on a single such frame. The remaining 24 cell ids are ample.

Desktop BUSMASTER Kvaser captures also carry short `0x000` status frames (DLC 4) on any bus.
canbench marks them as inferred errors (`tools/error-report-sweep/README.md`, "Kvaser
id-0x000 status frames"), so `0x000` stays an anchor: the real cell frame is DLC 8.

**NOT YET AUDITED, and the audit could not have found these.** The 2026-09-29 sweep tested
exactly the ids this table already published, so by construction it could only *remove*
anchors, never discover better ones. Two leads it therefore missed:

- **A larger B CAN exclusive set already exists on the Android side.**
  `CodaConstants.B_CAN_EXCLUSIVE_IDS` is `{0x378, 0x381, 0x382, 0x390, 0x391, 0x270, 0x271,
  0x2C1}` — eight ids, against the two this table can now vouch for — and
  `android-app/android-coda-tpms-implementation.md` records the same rebroadcast problem with
  `0x275`/`0x383`/`0x1D5`, reached independently. If those eight audit clean, B CAN regains a
  minimum-distinct-hits guard, which the 2-id set cannot support (2 of 55 channels carry only
  `0x381`).
- **`0x492`** was dropped from canbench's B CAN anchors on 2026-10-30 and is still unaudited;
  the internal `can_logger_vehicle_support` plan still lists it.

**canbench's table matches this one (2026-10-30, can-tools `f407e0f`).** The rebroadcast ids,
`0x004` / `0x00C` and the never-audited `0x492` are gone from `canbench/live/vehicle_configs.py`.
Its resolver names a channel only with at least 2 anchors of one bus and none of another, and
raises on ambiguity rather than picking a winner. Nothing is named by elimination, so Diag CAN is
never named, and a lone D CAN capture is no longer called B CAN. Phase 3 of
`notes/artifacts/anchor_exclusivity_audit.py` checks the two tables against each other.
`projects/coda/gui_profile.py` still carries the old set and is read by nothing (held GUI work).

Do not copy the old set into a `can_display_server.py` bus-identity JSON either: its threshold is
`min(3, len(anchor_ids))`, which three rebroadcast ids clear on D CAN traffic alone. Only
`can_display_bus_identity_vtrux.json` exists today, so there is no Coda exposure there yet.

Several
per-investigation scratchpads under `notes/artifacts/` carry the old set too, and any bus label
in older notes that cites `0x1D5`, `0x275` or `0x383` as its evidence — for example
`notes/rcu_keyfob/rcu_keyfob_analysis.md` — is unevidenced rather than necessarily wrong.

**Anchor sets are easy to invert.** `influx_upload.py`'s `exclude` list entry
`{"can_id": 0x1D5, "bus": "d_can"}` means *exclude the D CAN copy* — so 0x1D5 is B CAN native.
Read as "0x1D5 is a D CAN id" it produces an anchor set of exactly the wrong bus, composed
entirely of rebroadcast ids, which then cannot separate in either direction. That happened on
2026-09-29 in `notes/artifacts/powerstate_ladder_check.py`.


D CAN exclusive IDs are never rebroadcast to B CAN by the GWM gateway. Most other D CAN IDs (0x1C0, 0x208, 0x210, 0x212, 0x418, etc.) are also present on B CAN via gateway pass-through. See `notes/driver-inputs.md` for full gateway rebroadcast inventory.

**Counting hazard: pass-through means one frame can be counted twice.** A corpus count of a
rebroadcast ID that does not deduplicate by bus comes out **exactly doubled**, and the doubled
figure looks entirely reasonable on its own. Two instances so far: a `0x208` census reported at
138,460 against a true 69,230, and a `0x200` TC-event burst at 300 frames against 150. An exact
factor of two between two people's frame counts is the tell — suspect the gateway before
suspecting the parser.

### Non-Cell IDs Visible on C CAN

Non-cell IDs (0x0FF, 0x200–0x203, 0x300–0x304, 0x621–0x627) appear in C CAN captures
alongside the cell voltage frames. These are **native BMS output** — the BMS broadcasts
additional status messages on its C CAN diagnostic port beyond just cell data.

**Confirmed:** `codacharging.log` (Bus 1=C CAN, Bus 3=B CAN) shows zero shared IDs between
the two buses, ruling out any electrical coupling or cross-bus leakage at the OBD connector.
See `notes/charging-analysis.md` Goal 2. D CAN gateway rebroadcast behavior characterized — see `notes/driver-inputs.md` for full inventory.

**Counting hazard: `0x200` and `0x300` are each two different messages.** The ESC message on
D CAN and an unrelated C CAN message share both IDs. Any count, histogram or rate for these
IDs that does not split by bus merges two unrelated populations, and the result reads as one
message with more states than it has. This has produced a wrong answer three times: sub-frame
values from the C CAN message written into the ESC message's `CM_` as ESC startup frames
(2026-03, corrected 2026-09-26); an "undocumented sub-frame" reported and retracted
(2026-09-25); and a filter-cost figure inflated several-fold (2026-09-26). Identify the bus by which channel carries an
**audited-exclusive** anchor, per session — `0x308`/`0x312`/`0x325`/`0x330`/`0x580` for D CAN,
`0x48A`/`0x381` for B CAN, the cell range for C CAN. The channel index differs between
captures, so a fixed channel filter gives opposite answers on different files.
**This paragraph recommended `0x212` until 2026-09-29, which was wrong**: `0x212` is a gateway
rebroadcast present on both buses, named as such eleven lines above in this same file, so it
returns a channel for every capture and can never fail to. Any bus label derived from it is
unevidenced regardless of whether it happened to be right.

---

## Module Inventory

### B CAN (Battery CAN)

| Node  | Full Name                   | NM Role          | Notes |
|-------|-----------------------------|-----------------|-------|
| GWM   | Gateway Module              | NM Master (red) | Central bridge; also routes Diag CAN to J1962 |
| TEM   | Telematics Module           | NM Slave Full   | Unconfirmed - module that generates green screen video signal? |
| HVAC  | HVAC Control Module         | NM Slave Full   | Climate control |
| ACCM  | AC-Compressor Control Module| No SW NM        | Ford AM64-19D623-AB HV AC compressor; receives command (0x410), sends status (0x439) |
| IPK   | Instrument Panel Cluster    | NM Slave Light  | Gauges, warning lights, state display |
| SRS   | Airbag / Restraints         | No SW NM        | Crash detection & airbag firing |
| OCS   | Occupant Classification System | No SW NM    | Seat sensor for airbag classification |
| DCDC  | DC-DC Converter             | No SW NM        | HV→12V converter; messages from hardware manual |
| CHM   | Charger Module(s)           | No SW NM        | Lear AC charger(s) — master (CMM) + slave (CMS) physically, shown as one node here |
| BMS   | Battery Management System   | NM Slave Full   | Main BMS; also outputs C CAN for cell-level diagnostics |
| FCHM  | (Unknown)                   | No SW NM        | Possibly a DC fast charge module concept never shipped; has proprietary HV Wakeup link from BMS |

**Module naming reconciliation:**
- **CMM** = CHM master — Labview calls it CMM; topology calls it CHM. Same hardware.
- **CMS** = CHM slave — second Lear charger unit; Labview has CMS_Recvd.vi (no XML sidecar found). CMS signals inferred to mirror CMM (same Lear OBC hardware, slave vs master role).
- **ACCM** and **AICM** — likely **separate** modules. Hypothesis, strengthened
  2026-08-23: the AICM's four messages (0x276, 0x391, 0x392, 0x410) run on a
  102.90 ms / 4.60 ms-jitter transmit clock across 113 sessions, while 0x439
  (ACCM status) sits on the tight 100.00 ms / <1.3 ms clock shared with the BMS.
  A single timebase cannot produce both. Still short of proof — one ECU can run
  two timer tasks. See `notes/artifacts/x276_bus_presence.py` Phase 10.

### D CAN (Driveline CAN)

| Node     | Full Name                        | NM Role       | Notes |
|----------|----------------------------------|--------------|-------|
| DLCM     | Driveline Control Module         | NM Slave Full | Main driveline coordinator; hosts Motor CAN sub-bus |
| TCM      | Transmission Control Module      | No SW NM      | Controls the single-speed transmission / park pin |
| ESC      | Electronic Stability Control     | No SW NM      | ABS + stability; connected to yaw sensor |
| RCU      | Radio Control Unit               | No SW NM      | TPMS, keyfob receiver, immobilizer |
| PSM/EPS  | Power Steering Module            | No SW NM      | Electric power steering |

### Motor CAN (private sub-bus, not OBD-accessible)

| Node | Full Name             | Notes |
|------|-----------------------|-------|
| MCM  | Motor Control Module  | **UQM PowerPhase 100** — permanent magnet AC motor and inverter; controlled via DLCM |

**Module part numbers & suppliers:** read over the diagnostic bus 2026-06-27 — see `notes/module-diagnostic-ids.md`. Key points: `AK` is Coda's internal VM part-number prefix (the supplier's own number is the separate `F192` field); DLCM = Continental (confirmed by `A2C` prefix + physical label); SRS/airbag is a pure KWP2000 module that exposes only Coda's `AK36030100` (supplier identity must be read from the physical ECU label).

---

## Known Signal Sources

### 1. DCDC Converter — Hardware Manual (Confirmed, B CAN)

Delphi **U2C Universal 2.2 kW Converter** (`U2C-10018134-001`). Primary source:
`notes/dcdc/U2C Manual Rev03_2-15-2011.pdf`; every 0x1D5 / 0x48A / 0x1D7 field
re-verified against it 2026-08-24 — see `notes/dcdc/README.md`.

| ID (dec) | ID (hex) | Name              | Direction    | Key Signals |
|----------|----------|-------------------|-------------|-------------|
| 469      | 0x1D5    | DCDCStatus1       | DCDC → bus  | Master_Fault, HV_Input_Current, DTC_Index, Voltage_14V, Current_14V |
| 1162     | 0x48A    | DCDCStatus2       | DCDC → bus  | HV_Low_Fault, U2C_Power_Loss, Thermister_14V, Heat_Plate_Thermister |
| 471      | 0x1D7    | BMS_DCDCEnableSet | BMS → DCDC  | Enable_14V, VoltageSetPoint, Boost_Enable (**Phase 4 driving confirmed**: BuckBoostVoltageSetPoint + 14V Enable both drop to 0 when suppressed) |

### 2. AC-Compressor — Hardware Documentation (Confirmed, B CAN)

ACCM is the compressor unit itself — it is not a separate controller talking to a compressor.

| ID (dec) | ID (hex) | Direction       | Key Signals |
|----------|----------|-----------------|-------------|
| 1040     | 0x410    | → ACCM (command)| target_compressor_speed (rpm), max_pwr_consumption (kW), compressor_on_off, CASS_on_off |
| 1081     | 0x439    | ACCM → bus      | COMPRESSOR_STATUS (enum), ACTUAL_COMPRESSOR_SPEED (rpm), ACTUAL_POWER_CONSUMPTION (kW) |

### 3. C CAN — BMS Cell Diagnostics (Confirmed, C CAN)

Documented in `CODA-C-CAN-cells.dbc`. 26 frames, IDs 0x000–0x019 (0–25 dec).
Each frame: 4× 16-bit Motorola byte-order cell values.
Scale: **1 mV/bit** (confirmed). Raw value = millivolts directly.
LFP range: 2500–3650 raw (2.5–3.65V). Typical mid-charge: ~3250 mV.
104 cells total (26 frames × 4 cells).

**Cell numbering (1-based since 2026-07-22):** the DBC signals are `Cell1..Cell104`,
matching the BMS's own 0x381 `VmaxId`/`VminId` **directly** (VmaxId 82 = Cell82). The DBC
was previously 0-based (`Cell0..Cell103`); older artifacts/exports are 0-based, so **add 1**
to reconcile them. Confirmed across three sessions (100% at the charge session) — see
`notes/cell-index-mapping.md`. `MinTempId`/`MaxTempId` (0x382) index temperature sensors, a
separate axis, unaffected.

**Pack voltage cross-check:** `sum(104 raw cell values) / 1000` = pack voltage in V (~338V typical).
Use this to anchor/validate any pack voltage signal found on B CAN.

**Broadcast rate — depends on vehicle state.** The 26 frames go out as one
back-to-back burst; what changes is how often the burst repeats. Measured by
`notes/artifacts/cell_frame_sweep_rate.py`:

| State | Burst period | Source |
|-------|--------------|--------|
| Driving | **0.15 s** (p10 0.14, p90 0.17, n=12,860) | `frombonnydoon.log`, 33 min |
| Charging, bulk phase | **14.24 s** (p10 14.23, p90 14.25, n=351 — not one interval under 10 s) | `coda_20260722_173203_*`, first 90 min |
| Charging, near end-of-charge | mixed: 69 bursts <0.3 s, 87 at 0.3–2 s, 51 still ≥10 s (n=208) | same session, after t=5608 s |

The fast episodes during charging are intermittent, not a permanent switch — the rate
flips to the 0.15 s driving cadence for a run of bursts, then back to 14.24 s. The first
one begins at t=5608 s, 27 s after Cell82's peak. **Hypothesis, untested:** the OV
excursion is what triggers them; it could equally be balancing activity or a charger
state change.

Practical consequence: a live cell display looks frozen for 14 s at a time on a
plugged-in car. That is the BMS, not the tool.

**Which captures carry C CAN.** C CAN needs a third dongle, so most Coda captures have
only B and D. The sessions with cell frames:

| Session | Path | Notes |
|---------|------|-------|
| 2026-07-22 charge to 100% | `../../CANLogs/CodaLogs/coda_20260722_173203_T0..T21` | Cleanest cell data; 75.7% -> 100% SoC past the OV cutoff. 602 complete sweeps over 106.8 min. |
| 2026-02 Bonnydoon drive | `logs/frombonnydoon.log` | 33 min of driving; the 0.15 s cadence reference |
| 2026-07-21 Android 3-dongle | `../../CANLogs/CodaLogs/coda_20260721_192435_T0..T2`, `_201109_T0/T1`, `_202031_T0` | Shorter |

Rendering either mapping of these frames onto the physical pack:
`coda-diagnostics/cell_viewer/`, in the `coda-diagnostics` submodule
(see `notes/pack-physical-layout.md` for the mapping itself).

### 4. CODACAN LabVIEW Decompile and Replay (B+D CAN)

`CODACAN/CODACAN.exe` is the original Coda engineering diagnostic application. Its LabVIEW
source — Globals XML files (signal cluster metadata) and compiled ICD `.vi` files (CAN parse
logic) — provides signal names, cluster assignments, and display logic. A bench replay
methodology replays captured log files into CODACAN via a CAN dongle, mapping every labeled
GUI field to its CAN ID, byte position, scale, and offset. See
`notes/codacan-signal-decode-notes.md` for bench setup, replay commands, and full
phase-by-phase decode analysis.

**Module extraction status:**

| Module      | XML Parsed?    | ICD Disassembled? | Notes |
|-------------|---------------|-------------------|-------|
| BMS_Recvd   | Yes (partial) | Yes (11 IDs)      | All key signals confirmed via bench replay |
| CMM_glb     | Yes (full)    | N/A (interpreted) | 7 clusters, all signals documented |
| CMS_Recvd   | N/A (no XML)  | N/A (interpreted) | Signals inferred from CMM mirror (same Lear OBC hardware) |
| DLCM_Recvd  | Yes (partial) | Yes (6 IDs)       | Includes misc_Recvd (D CAN) |
| DCDC_Recvd  | Yes           | Cross-checked     | Matches hardware manual |

**Note:** LabVIEW uses U+221E (∞) as a degree symbol in signal unit strings — causes CP1252
errors on Windows. Use `--quiet --output FILE` when running `labview_xml_extract.py`.

#### B CAN Signals

| ID (hex) | DBC Name | Module | Signals |
|----------|----------|--------|---------|
| 0x050 | BMSChargerCmd | BMS | HVCurrentCmd, MaxVoltage, **EVSEMaxCurrent** (B5-B6 BE, 0.1 A/bit — J1772 advertised station current, full/unsplit, same in idle and charging). **This is the canonical EVSE-advertised-current signal for the Coda** — prefer it over the per-module copies in 0x054/0x61A. Not CODACAN-derived: confirmed 2026-07-23 by log analysis across three known station ratings. Sender is the BMS (transmitter-clock fingerprint: 0x050 = -31.7 ppm vs BMS cluster -31.8, GWM +22.1) — the path is BMS -> chargers directly, no gateway hop. See `notes/charging-analysis.md` |
| 0x270 | BMS_FaultStatus | BMS | **B0[7:4] = BMSFaultSeverity (0-6 enum)** (located by CODACAN inject 2026-07-26; natural data only reaches 0-1); **B0 bit1 = BMSRedLampReq** (relayed to 0x271); B0 bit0 = key-on lamp test. B6/B7 active, unknown. |
| 0x275 | BMSDriveLimits | BMS | B0 DischargeLimit (alias MotorDriveLimit), B1 ChargeLimit, B2-B3 PackCurrent, B4-B5 PackVoltage, B6 HVACLimit, **B7 dead byte (0xDD, inert)** |
| 0x2C1 | BMSDrivingRange | BMS | DrivingRange_Exp (B1), Max (B3), Min (B5) — **raw × 0.62 mi, offset 0** (miles; green-screen/Android confirmed; DBC's old 1.17 mi was 2× too high, and CODACAN's km readout is a mis-scale) |
| 0x378 | BattPowermode | BMS | HVPowermode, Chargemode, KeepWakeNetworkBMS, rolling counter, BMSmode |
| 0x381 | BMSVminVmax | BMS | B0-B1=avg cell mV, B2-B3=max cell mV, B4-B5=min cell mV, B6=VmaxId, B7=VminId (all BE, 1 mV/bit). **Byte order corrected 2026-07-15** — DBC/decode-notes previously swapped Min<->Avg and VminId<->VmaxId (matches LabVIEW BMS_Recvd cluster order Vavg,Vmax,Vmin,VmaxId,VminId; avg lies between min/max in 99% of samples). **Index mapping resolved 2026-07-21** — VmaxId/VminId are the **C CAN cell number directly** (`VmaxId 82 = Cell82`), both 1-based since the 2026-07-22 DBC renumber (historically DBC was 0-based and reported id = old Cell + 1). Range 1-104. See `notes/cell-index-mapping.md`. |
| 0x382 | BMSThermal | BMS | Cell_T_avg, Cell_T_max, Cell_T_min, MaxTempId, MinTempId |
| 0x383 | BMSBattStatus | BMS | SoC, HVBattCharging, ChrgPortOpen, ChargeCableConnected |
| 0x390 | BMS_HVBattTemp1 | BMS | FrontInletAirTemp, RearInletAirTemp, ReturnAirTempPsg, ReturnAirTempDrv, AllowedCellTempMax, AllowedCellTempMin, AllowedCellTempDiff, AllowedHumidity |
| 0x271 | GWM_VehFaults | GWM | VehicleFaultLampReq (B0[1:0]: OFF/YELLOW/RED/INVALID), B0 bit2 flag. **VehFaultSeverity/VehicleFault removed** — B1-B4 = 0x00 in every captured car, so no fault code is on the bus |
| 0x276 | HVACStatus | HVAC | PTC_PowerConsumption, ACCM_PowerConsumption, HVACHVDisableStatus (**B2[1:0]** enum: 0 Invalid/1 not-disabled/2 disabled/3 -), CIntTempRadOutlet, CIntTempPTCOutlet, PTCHeaterPWM, RadiatorFanPWM, BattFanPWM. **B CAN native** (AICM) — the D CAN copy is a GWM rebroadcast, confirmed 2026-08-23; see `notes/efficiency-calculation.md` Sec.5 |
| 0x391 | HVACAirState | HVAC | UnderHoodHumidity, UnderHoodTemp, OpAirHumidity, OPAirTemp, ReturnAirTemp, EvapAirOffTemp |
| 0x274 | ChrgrSysFaultsTemp | CMM | Fault status, Chrgr1Temp, Chrgr2Temp |
| 0x277 | CMMTempStatus | CMM | CaseTemp confirmed; PFCTemp, HV1/HV2 inconclusive |
| 0x279 | CMMOutputValues | CMM | HVOutVoltage, HVOutCurrent, LVOutVoltage, LVOutCurrent (all confirmed; HVOutVoltage cross-checks with C CAN pack voltage) |
| 0x27A | CMSTempStatus | CMS | PFCTemp, HV1Temp, HV2Temp, CaseTemp (all confirmed) |
| 0x27B | CMSInputValues | CMS | ACInVoltage, ACInCurrent (16-bit ÷32), ACInPower (**32-bit ÷64 over bytes 4–7**, = charger-computed V×I) — all confirmed |
| 0x27C | CMSOutputValues | CMS | HVOutVoltage, HVOutCurrent, LVOutVoltage, LVOutCurrent (all confirmed) |
| 0x27D | CMMInputValues | CMM | ACInVoltage, ACInCurrent (16-bit ÷32), ACInPower (**32-bit ÷64 over bytes 4–7**, = charger-computed V×I) — all confirmed |
| 0x615 | ChrgrSysLimits | CMM | **Despite the message name, B5 is a measurement, not a limit** — it tracks total AC current, matching the 0x27B+0x27D sum within +/-0.44 A across all 12 charge sessions (2026-07-23). B0 = status/capability byte. Remaining bytes uncharacterised. Do **not** use this message for an EVSE limit — see 0x050 EVSEMaxCurrent |
| 0x616 | ChrgrSysCtrlEcho | CMM | CMM echo of the BMS command 0x050, byte-for-byte identical at 8.3 Hz. Same signals and scaling: HVCurrentCmd, MaxVoltage, EVSEMaxCurrent |
| 0x617 | ChrgrSysSts | CMM | Charger system status. **No confirmed SG_** — ChrgrSysBusVoltage/Current removed (CODACAN shows no field; log values don't match div32). BO_ stub. |
| 0x61A | CMSHVCmd | CMS | HVCmdVoltage, HVCmdCurrent, ACMaxCurrentAvail, HVCmdEnabled (all BE uint16 /32). **Per-module values**: ACMaxCurrentAvail is half the station current while charging (HVCmdEnabled=0x02) and the full station value when idle. 0x054 is the CMM counterpart with identical content. Both are charger-sourced, not GWM echoes (clock fingerprint places both in the charger cluster, +7 ppm) |
| 0x491 | IPK_Cluster | IPK | **Primary_ODO (B0:B1:B2, 24-bit BE, 0.1 km/count)** + headlight bits (B3: bit4 side/parking, bit5 low beam, bit6 high beam). Odometer verified across 3 Codas vs known mileage (this car ~34.0k mi, parts car ~62.1k mi, another Coda ~61.3k mi). **The former "IPK_FaultLamps" reading was wrong** — those bytes are mileage, not fault lamps (an othercars inference; see `notes/artifacts/cowork-results/promotion-staged-diff.md`). CODACAN's own "Primary ODO" GUI field is a mis-scaled partial decode — don't use it. |
| 0x492 | IPK_Cluster_Mirror | IPK | Redundant broadcast mirroring 0x491 B0:B1:B2 (same odometer); B3+ zero. All-zeros on a car = that IPK-mirror module silent (not fault-related) |

**Charger note:** CMM and CMS each report their own individual measurements (not totals).
Charger IDs are only present during active charging sessions. CODACAN CH M/S tab displays
CMS-side values (0x27A/27B/27C); CMM-side slots (0x277/27D/279) have lower display priority.
See `notes/charging-analysis.md` for encoding and full decode.

#### D CAN Signals

| ID (hex) | DBC Name | Module | Signals |
|----------|----------|--------|---------|
| 0x1C0 | MCM_Telemetry | DLCM | Torque, HV_Voltage, HV_Current, Motor_Speed |
| 0x212 | DLCM_TorqueRequest | DLCM | BrakeSW confirmed (B2.bit0); TorqueRequest: 12-bit nibble-split `(B4 & 0x0F) << 8 \| B5`, zero=2000 (0x7D0), scale **0.244 Nm/count, offset 0 — CONFIRMED** (log fit vs 0x1C0 Torque, r=0.999, peak 293 Nm vs ~300 anchor); KeepWakeNetworkDLCM position unconfirmed |
| 0x241 | MCM_Thermal | DLCM | **B1=IGBT, B2=Rotor, B3=Stator** temp — per-byte assignment confirmed by CODACAN sweep (matches DLCM_glb cluster order); offset -40°C unconfirmed; B0/B4-B7 = no temp; firmware implies a 4th "Inverter" temp not accounted for |
| 0x278 | DLCM_Keepalive | DLCM | KeepWakeNetworkDLCM, EngineStsRun |
| 0x315 | DLCM_Status | DLCM | Brake_SW, rolling counter, Batt_Volt |
| 0x418 | DLCM_Globals | DLCM | PRND, gear status |
| 0x052 | ParkingBrake_Crank | misc_Recvd | ParkingBrake, crank signal |
| 0x080 | EPS_Steering | EPS | RelativeSteeringAngle; CRC8 protected |
| 0x210 | ThrottlePedalPos | misc_Recvd | ThrottlePedalPos |
| 0x215 | Unknown (ESC suspected) | misc_Recvd | **B0:B1 = VehicleSpeed**, km/h x 128 BE, confirmed 2026-10-26 (odometer integration and r = 1.000 against the ESC wheel speeds); B2-B6 undecoded. The HVAC reads it with a precedence bug. See `notes/hvac/coda-hvac-decompile-notes.md` section 5.4. TCM.ParkLock hypothesis invalidated — `notes/codacan-signal-decode-notes.md` Section 5c. |
| 0x271 | GWM_VehFaults | GWM | Gateway rebroadcast of B CAN 0x271 (same structure) |
| 0x273 | IPK_ClusterData | IPK | Primary ODO, Interior Illum, Side Light Active, Low Beam Active |
| 0x300 | ESC_0x300 | ESC | **Yaw rate** in B6-B7 BE (zero 32792, ~0.0094 deg/s/count, positive = left), plus **TWO 13-bit ESC torque limits** -- `ESP_BrakingTqLimit` in B2-B3 and `ESP_TractiveTqLimit` in B4-B5 -- **and an arming flag for the second of them in B4 bit 6**. Both limits 13-bit BE, `internal = (raw - 2000)/0.4` = `raw*2.5 - 5000` (confirmed from `FUN_8006F05A`), in internal torque counts where 1 count = 0.1 Nm. Read by `FUN_80080588` (B2-3) and `FUN_80080572` (B4-5) and applied as `min(magnitude, max(limit, 0))` in `FUN_800771FA`. Named for what they bound relative to **travel direction**, not sign, because `FUN_800768D6` negates one and passes the other per direction, so **forward, B2-3 is the regen limit and B4-5 the drive limit; they swap in reverse** -- a sign-based name is wrong in one gear. ~~It mirrors delivered torque rather than limiting it~~ / ~~NAMING CONFLICT, unresolved~~ -- **BOTH WITHDRAWN 2026-10-03: both fields are torque limits, both bind, and the naming is settled** (`MMAX_ESP_REGEN_TQ_REQ` was renamed `ESP_TractiveTqLimit`, which the firmware confirms is the drive-side limit). **The two behave very differently and the difference is one bit.** B2-3 is gated on CAL `0xA0021715` and fault flags only: it fires **5 times in 363 sessions**, goes to **exactly 0** for 2.5-21 s, with `ABS_BrakeEvent` coincident within one sample in all five, and on 2026-10-02 took all 156 Nm of regen. B4-5 additionally requires **B4 bit 6**, a runtime arming flag (`FUN_8008054E` -> `0xD0006844` -> the gate on `FUN_800771FA`'s tractive `min()`), set in only **0.0146 %** of 315,555 frames: it fires **34 times across 29 sessions**, for 0.02-0.86 s, and only partially (to 148-223 Nm of a ~300 Nm ceiling). **When B4 bit 6 is clear, B4-5 idles at a value equal to the `0x212` torque request** (MAE 0.28-0.39 Nm over six sessions, median residual 0), which is why the field read as a mirror for so long -- mirror and limit are the same data until the flag arms it. **Masking: mask the 13-bit VALUE with `0x1FFF`, but do not treat the remaining B4 bits as noise** -- bit 6 is the arming flag above, bit 7 is an alternate-frame toggle at exactly 50.0000 %, and bit 5 is never set in 315,555 frames (role unknown). B2 bits 5-7 are always 0: the braking side has no arming bit. 50 Hz, `B0 == 0x00`. **A different message shares this ID on C CAN** (BMS diagnostic port, muxed 8 ways) -- identify by content, and note a `B0 == 0` filter does NOT separate them since the C CAN mux includes 0. See `notes/yaw-rate-signal.md`, `notes/dlcm/esp-torque-intervention.md` |
| 0x308 | DLCM_ParkRequest | **DLCM** | ParkRequest (B0 bits 6-5: 0=OFF, 1=Park, 2=UnPark) + shaft speed sent to the TCM. Corrected 2026-09-24 from "TCM_ParkPin / TCM": the DLCM transmits it and the request leads the TCM's 0x55C by 55-89 ms on both vehicles. BorgWarner cross-vehicle match with Vtrux — see `notes/borgwarner.md`. |
| 0x330 | Long_Accel | misc_Recvd | **Longitudinal acceleration, confirmed 2026-09-20.** DLC is 8 (not 1): B0-B6 constant, **B7** is the signal, offset binary with zero at raw 123, 0.08 m/s2/count, 50 Hz, raw >= 200 invalid. Now an `SG_` in the DBC. See `notes/dlcm/dlcm-torque-limiter-code-trace.md` and `notes/dlcm/artifacts/accel_signal_hunt.py`. |
| 0x370 | DeathCounters | misc_Recvd | Death counter batch |
| 0x55C | TCM_State | TCM | TCMState. BorgWarner cross-vehicle match with Vtrux — see `notes/borgwarner.md`. |
| 0x600 | misc_0x600 | RCU | **B7 bit5 = TPMS telltale — CONFIRMED 2026-09-21** (`SG_ TPMS_TelltaleFault`): flipped at 11:09:56 against the owner's observation of the lamp at 11:10. Cleared by a 12 V disconnect, re-latches after **421 s (7 min) of driving above 30 km/h** (sd 1.07 s, 6 clusters). **Still not tyre pressure** (disproved 2026-09-20): B5/B6 is a monotonic ~1 Hz counter, B1-B4 frozen across all 985 corpus files, B0 a 4-phase tag with identical payload. DLC is 8, not 2. See `notes/indirect-tpms-feasibility.md` |

**Note:** misc_Recvd IDs (0x052, 0x080, 0x210, 0x215, 0x271, 0x273, 0x330, 0x370, 0x600)
are assigned to D CAN (RCU, TCM, ESC are D CAN modules), but most are also rebroadcast to
B CAN by the GWM gateway. See `notes/driver-inputs.md` for the full gateway rebroadcast
inventory.

**Open items:** BMSmode (0x378 B2) shows different values on other vehicles — meaning unknown
(CODACAN echoes the raw byte, so not resolvable there). 0x410 boolean bit positions unresolved.

### 10. Parts Car Investigation Signals (2026-03-05)

Findings from comparing a parts car (3 active DTCs: ABS C102B, SRS B1382/B2505, HVAC B111D, DLCM C2100) against the normal vehicle. Full write-up in `notes/partscar-analysis.md`.

#### 0x6FA — GWM VIN Broadcast (B CAN + D CAN rebroadcast)

| Field | Value |
|-------|-------|
| Rate | 10 Hz |
| Structure | 3-frame mux: B0 = VIN_Frame (0/1/2), B1-B7 = 7 ASCII chars |
| Frame 0 | VIN chars 1-7 |
| Frame 1 | VIN chars 8-14 |
| Frame 2 | VIN chars 15-17 + padding |
| Normal VIN | 53G1U4A46CB000090 |
| Parts car VIN | ABCDEFGHI12345678 (sequential placeholder — triggers C2202) |

DBC: `BO_ 1786 GWM_VIN` with mux signals `VIN_C01`–`VIN_C17`. Identical message rebroadcast on D CAN.

#### 0x3A0 — SRS Airbag Status (B CAN)

| Signal | Position | Encoding |
|--------|----------|----------|
| SRS_FaultFlag | B0 bit 7 | 1 = fault active, 0 = normal |
| SRS_ModuleActive | B0 bit 5 | 1 = SRS ECU running |

Normal steady-state B0 = 0x20 (bit 5 only). Parts car steady-state B0 = 0xA0 (bits 7+5). Transient 0xAA during startup lamp test. Corresponds to DTCs B1382/B2505.

#### 0x312 — DLCM Torque and Torque Limits (D CAN, 100 Hz) -- corrected 2026-09-24

**This is a DLCM message, not an ESC message.** It is TX record 10 in the DLCM's own
CAN transmit table at `0x80041B74`, 10 ms period, and `FUN_80080C14` writes all eight
bytes from the `0xD00069Dx` torque mirror block. The "ESC Internal Measurement Frame"
reading below it is withdrawn; so are the wheel-speed and ESC-deceleration readings in
`notes/traction-control-analysis.md`, `notes/othercars-comparison.md` and
`notes/driver-inputs.md`. Full derivation in
`notes/dlcm/coda-dlcm-decompile-notes.md` ("What each configured message actually
carries").

All three fields use the `0x212` encoding: **0.25 Nm/count, zero at raw 2000**, taken
from the 13 low bits of each pair. Measured slope against `0x1C0` Torque is
0.24993 Nm/count with zero at 1999.5.

| Byte(s) | Name | Notes |
|---------|------|-------|
| B0[4:0],B1 | TorqueFeedback | tracks `0x1C0` Torque, r = 0.9994, median error 0.90 Nm |
| B0 bit 5 | Parity | over `(B0 & 0x5F) ^ B1` — holds in 197,193 of 197,193 frames |
| B0 bit 6 | Toggle | alternates, 50/50, independent of the data |
| B2[4:0],B3 | TorqueFeedback copy | bit-identical to B0-B1 in 100 % of frames |
| B4[4:0],B5 | **M_MAX** | positive torque limit, 0 … +299.75 Nm |
| B6[4:0],B7 | **M_MIN** | regen torque limit, −300 … 0 Nm |

The `0x212` request lies inside [M_MIN, M_MAX] in 99.997 % of samples and sits exactly
on M_MAX in 1.07 %. **M_MAX drops to +29.75 Nm whenever the brake switch is on** —
+299.75 Nm in 100.0 % of 90,230 brake-off frames, +29.75 Nm in 97.2 % of 1,650 brake-on
frames. That is the "brake-correlated signal" recorded as undecoded in
`notes/driver-inputs.md`.

Every observation behind the old ESC reading is explained by this one: "2000 stationary
default" is 0 Nm, "3199 clamp" is +299.75 Nm, "800 floor" is −300 Nm, "B1 = B3
redundant" is the duplicated field, and "B2 echoes B0[3:0]" is B2 being B0 without its
two flag bits.

Both B4-5 and B6-7 clamped to limits (3199 and 800) during TC intervention.
Scale to km/h not yet determined; requires LR km/h calibration (pending motor-rpm → km/h conversion).

#### 0x391 — HVAC Air State B4 (B111D sentinel)

CIntTempRadOutlet (0x276 B3, radiator outlet temp) shows 0x58 = -40°C in parts car — open-sensor sentinel value for HVAC DTC B111D (coolant temp sensor fault). Never seen below -7°C in normal operation. DTC B112D (airmix motor) has no observable CAN status because the airmix flap is downstream of the radiator sensor.

**B3 OPAirTemp — unreliable as outside-air temp.** Decodes cleanly (T = raw − 128 °C) but is a damped/poorly-calibrated *estimate*, not a clean ambient thermistor: it reads ~+12 °F high vs ground-truth weather in all conditions (including parked at night) and stays stuck high even at highway speed, so it cannot be offset-calibrated. An "Outside: NN°F" display sourced from it was added then **dropped** (removed in `coda-debug (19).apk`, 2026-05-22). Full analysis — including why no other CAN sensor (FrontInletAirTemp 0x390 B0 reads pack temp after charge/hot-soak, EvapAirOffTemp 0x391 B5 is HVAC-coupled) is a reliable ambient source — in `notes/outside-air-temp-investigation.md`.

### 9. Diagnostic Tool Reverse Engineering (Confirmed, Diag CAN)

`coda-diagnostics/` contains Python scripts reverse-engineered from the Omitec dealer scan tool.
It is the live, published tool. `Diagnostic/` is a separate, **private** folder holding
diagnostic findings that are deliberately not published — principally the Coda
SecurityAccess work — plus the scan-tool captures and the archived pre-repo scripts the
tool grew out of. See `Diagnostic/README.md`.
Supports reading and clearing DTCs from:
- ABS (ESC module)
- AC-Compressor (ACCM)
- Airbag (SRS)
- BMS
- DLCM (also exposes MCM and TCM codes)
- Gateway / DCDC
- HVAC
- Power Steering (EPS/PSM)

Does **not** support:
- Chargers (CHM) — security handshake involved
- RCU — no clean DTC pattern found yet

Also includes `coda_fake_car.py` — a playback tool that emulates vehicle CAN presence for
testing the scan tool without a real car.

---

## ECU Firmware Extraction & Decompile

Firmware extraction has been attempted on several Coda ECUs, mostly by capturing the Omitec scanner's UDS reflash session from a BUSMASTER log and reassembling the download blocks into a binary. Outcomes vary by module.

### Gateway (GWM) — extracted, plaintext, documented

ECU 0x718. 90,112-byte image, plaintext ARM (entropy 4.95). MCU is an NXP LPC2xxx (ARM7TDMI-S), confirmed by the ROM-API call at `0x7FFFFFF1`. Decompiled in Ghidra (123 functions). Recovered the UDS service dispatcher, the local DID dispatch table, and the 77-entry CAN routing/"firewall" table — including per-message bus-origin and SRAM signal-slot fields, which independently confirm the B CAN/D CAN module assignments and gateway rebroadcast behavior documented above. Limitation: VIN/serial strings and part of the per-byte signal-extraction logic live in the bootloader flash region (above the captured application image), which the UDS download did not include. See `notes/gateway/coda-gateway-decompile-notes.md`.

### DLCM — extracted, plaintext, documented

ECU 0x7E8, Continental EMS9180. Two plaintext images: PROG (1.83 MB) and CAL (114 KB); Infineon TriCore LE core (corrected 2026-09-19, previously recorded as SH-4), analyzed in Ghidra as `tricore:LE:32:default`. The work targets the §10.7 State-Dependent Torque Gradient Limiter calibration LUTs (to widen the rate limit through the lash zone for throttle feel). Firmware build `1CI527_D003`. See `notes/dlcm/coda-dlcm-decompile-notes.md`.

> **Vehicle-state change — real DLCM reflashed with a modified CAL (two flashes).** The near-zero gradient-limiter V-curve floor was raised via the MITM proxy (`notes/dlcm/dlcm_flash_proxy.py`), PROG left byte-exact, no DTCs both times:
> - **2026-07-21 (`vcurve-lash-5`):** idx5 `0xA0021532`/`0xA0021B6E` `1 -> 5`.
> - **2026-07-22 (`vcurve-floor-20`):** idx2-5 on both copies (`0xA002152C..32`, `0xA0021B68..6E`) all raised to `20`, making the true curve minimum 20.
> - **2026-09-20..24: six further CAL flashes** (FLOOR20, FLOOR40 + speed limb, negTrqLast x3, C1 creep 50, launch rate, C2 one-pedal, C4c pedal map). **C4c is the CURRENT on-car state.** Lineage and md5s: `notes/dlcm/dlcm-cal-flash-campaign.md`.
> - **2026-10-04 16:10–16:27: flash 7 (7a IIR enable + 7c V-curve cut), FAULTED and REVERTED.** Seven DLCM resets then the Permanent Shut-off Path; cause established 2026-10-08 as 7a, a filter with no ECM2 twin — `notes/dlcm/flash7-reset-mechanism.md`. Its captures are quarantined in `notes/dlcm/dcan_drive_capture_20261004_f7/`, outside every sync root.
>
> **All Coda driveline logs after 2026-07-21 reflect a modified calibration** (floor 5 for logs on 07-21, floor 20 for logs on/after 07-22) and are not directly comparable to earlier logs for torque-gradient/lash behavior. **Finding: the floor change saturated** — floor 5 and floor 20 produce identical near-zero rate behavior (a fixed ~8 cts/update clamp binds below the floor), so the floor is not the effective driveability lever beyond ~5. Full analysis: `notes/dlcm/dlcm-torque-limiter-code-trace.md`. Procedure/verification: `tools/flash_sim/README.md` roadmap step 6; logs `notes/dlcm/artifacts/proxy_real_flash_20260721.log`.

### BMS — extracted but encrypted (blocked)

The BMS application image (249,856 bytes) was downloaded via the same UDS method but is
**encrypted**, despite the UDS request declaring no encryption. Re-measured 2026-09-24 with
ISA-agnostic metrics: entropy 7.9992, chi-square 282 against uniform, longest single-byte
run 3, zero repeated 4-grams, zlib ratio 1.000 — statistically indistinguishable from
`os.urandom`, against 0.361 for the known-plaintext gateway image. Zero duplicate 16-byte
blocks, so it is not ECB over anything structured. The cipher is **unidentified**; the
earlier "AES-class" reading was an inference from entropy alone and is only a hypothesis,
as is the ARM7TDMI-S core attribution, which was inferred from the gateway rather than
observed on the BMS.

**Four-digit passcode hypothesis tested and closed 2026-09-26.** A former Coda engineer
reported that firmware images were sometimes encrypted with a four-digit passcode — the
last four of the VIN, later `2012`, and in some cases an engineer's own code. All three
cases are four-digit numbers, so the whole `0000`-`9999` space was swept: ~765,800
decryption attempts across AES, Camellia, SM4, CAST5, IDEA, DES, 3DES, Blowfish, RC4,
ChaCha20, TEA, XTEA and six PRNG keystreams, **0 hits**, with a detector calibrated to
recover a positive control at 0 false positives in 1,020 trials. The cipher class is now
narrowed by measurement to a **stream cipher or chained block mode** — ECB and short
repeating XOR are excluded outright. See `notes/coda-bms-decompile-notes.md`.

The firmware-encryption key is a separate secret from the SecurityAccess key. That was
originally an assumption and has since been **tested**: the SecurityAccess LFSR does not
decrypt the image under its own constants, nor under *any* key — a detector that finds an
injected keystream immediately finds nothing in the image. `0x23` and `0x35` are also not
implemented on the BMS application, so the bootloader that holds the real key is not
reachable from the extended session. Decompilation remains blocked; the open routes are
JTAG, the programming session, or the Omitec tool binary.

Full account: `notes/coda-bms-decompile-notes.md`.

### RCU (keyfob / immobilizer) — not yet extracted

The RCU (Radio Control Unit, D CAN — TPMS, keyfob, immobilizer) firmware has **not been extracted**. The MCU is an HCS08-class part (MC9S08DZ60). A separate CAN-level investigation into keyfob-pairing door-unlock behavior exists, but the on-chip firmware itself has not been pulled.

---

## Documented Behavior

Confirmed vehicle behaviors observed from CAN log analysis. Sources: `frombonnydoon.log` (33 min, B+C+D CAN) and `codadriveslowturnonwithdefroster2.log` (~12 min, B+C+D CAN). Signals: 0x1C0 (Torque, HV_Current, Motor_Speed), 0x210 (ThottlePedalPos), 0x275 (PackCurrent, PackVoltage, BattSentChargeLimit).

### Torque Ramp on Full-Throttle Launch

Torque does **not** reach peak instantly from standstill. On a full-throttle pull from rest, torque ramps from ~20–80 Nm up to ~290 Nm over approximately **0.5–0.8 seconds** (0–250 rpm), then holds flat. This is consistent across 8 events in both logs and is almost certainly a deliberate soft-start in DLCM or MCM firmware (not driver-induced — throttle is already at full during the ramp).

After the ramp, torque is flat at ~290 Nm up to ~1300–1500 rpm, then tapers as expected in the constant-power region.

Peak observed torque: ~300 Nm (UQM PowerPhase 100 rated peak: 310 Nm).

### Peak Regenerative Braking vs Battery Charge Limit

Peak regen is roughly **half the available charge current limit** — the BMS is not the bottleneck.

| Log | Peak PackCurrent | Pack Voltage | Regen Power | ChargeLimit at that moment | % of Limit |
|-----|-----------------|--------------|-------------|---------------------------|------------|
| bonnydoon | 80.8 A | 348 V | 28.1 kW | 150 A (52 kW) | 54% |
| defroster2 | 69.1 A | 343 V | 23.7 kW | 146 A (50 kW) | 47% |

When the battery is warm and SoC is mid-range the BMS broadcasts ChargeLimit = 150 A (~52 kW at nominal pack voltage), which is the "open" condition. Peak observed regen current reaches ~81 A — well under the limit. The bottleneck is motor braking torque (~108 Nm peak at ~2900 rpm), not the battery.

ChargeLimit in `defroster2` started at 128 A and climbed to 146 A over the drive, consistent with pack temperature rising as the pack heater ran during the early portion of the drive.

---

## DBC File Status

| File | Contents | Status |
|------|----------|--------|
| `CODA-B-CAN.dbc` | B CAN messages (BMS, DCDC, charger, ACCM, HVAC, SRS, IPK, GWM) | 35 messages. Confirmed signals documented in signal table above. Unconfirmed bytes use `Packet_N` placeholders; 0x410 B0 bit positions still unresolved. |
| `CODA-D-CAN.dbc` | D CAN messages (ESC, DLCM, EPS, misc, GWM, RCU) | 34 messages. Confirmed signals documented in signal table above. Ten messages added 2026-09-24 from the DLCM firmware's own CAN configuration tables (0x051, 0x08C, 0x168, 0x312, 0x591, 0x592, 0x593, 0x595, 0x603, 0x614); several field widths corrected in the same pass — see `notes/dlcm/coda-dlcm-decompile-notes.md`. Unconfirmed bytes use `Packet_N` placeholders. |
| `CODA-C-CAN-cells.dbc` | Cell voltage/temp frames on C CAN | Cell voltage portion confirmed and complete — 26 frames, 104 cells. Additional non-cell IDs visible on C CAN (0x0FF, 0x200–0x203, 0x300–0x304, 0x621–0x627) not yet characterized; not in DBC. `CellN` = B CAN 0x381 VminId/VmaxId value N directly (1-based since 2026-07-22 renumber; was 0-based) — see `notes/cell-index-mapping.md`. |

All multi-byte signals use Motorola byte order (@0+, big-endian). Unconfirmed bytes use
`Packet_N` placeholders. Placeholder IDs (sentinels ≥ 8191) from LabVIEW clusters removed —
that information is preserved in `CODACAN/labview-signals.json`.

---

## Log Capture Status

See `logs/README.md` for log file inventory.

---

## Open Questions & Investigation Areas

### High Priority
- [ ] **CODACAN signal decode — Phase 5 in progress.** Most signals confirmed; partial/open items tracked in `notes/codacan-signal-decode-notes.md` (Sections 5b, 5c, 6, 7). Key remaining: IPK gauge feeds (SoC%/speed source unknown), 0x410 B0 boolean bit positions, 0x050 B4-B7 characterization. (Resolved via Runs 1-3 + log verification — 0x491 ODO, 0x270 severity, 0x276 disable, 0x2C1 scale, 0x241 temps, 0x212 torque: see `notes/codacan-replay-verification-queue.md` and `notes/artifacts/cowork-results/promotion-staged-diff.md`.)

### Medium Priority
- [ ] RCU — **0x600 still does NOT carry pressure data** (disproved 2026-09-20; a whole-bus sweep found no pressure-shaped channel on any ID). But it *is* the RCU's status frame and its **B7 bit5 is the TPMS telltale, confirmed 2026-09-21** — so the lamp state is on the bus even though the pressures are not. Remaining unknown: which bits, if any, encode per-wheel fault detail — B1-B4 are frozen at `01 01 07 00` in every corpus file, because all four sensors have been dead throughout. **Capture task:** a car with a working sensor, or a bench RCU, would move those bytes. See `notes/indirect-tpms-feasibility.md`.
- [ ] **BMSmode (0x378 B2) unknown value range**: Normal car shows 0xD2 (210) driving, 0xA9 (169) charging. Another Coda and the parts car both show 0xF2–0xF8 (242–248) — unknown whether this indicates a fault/degraded state or firmware variant. **CODACAN echoes the raw B2 value (no semantic decode), so it cannot resolve the meaning** — needs firmware or cross-car log correlation.
- [ ] Decode 0x215 B2-B6 (B0:B1 = VehicleSpeed done 2026-10-26, see `notes/hvac/coda-hvac-decompile-notes.md` 5.4) (**0x600 partly done 2026-09-21** — B7 bit5 confirmed as the TPMS telltale; B1-B4 remain frozen and undecoded) — see `notes/codacan-signal-decode-notes.md` Section 5c. **0x330 DONE 2026-09-20**: B7 is the longitudinal accelerometer (see the signal table above); B0-B6 are constant and remain undecoded, but carry no variation in any drive examined.
- [x] **Identify the bad cells (DONE 2026-07-22).** Weak/low cell = **Cell95** (UV/limp trigger, `frombonnydoon.log`). Failed-balance/OV cell = **Cell82** (VmaxId 82, hits 3778 mV at EOC in `coda_20260722_173203_*`). Highest-under-load cell = **Cell84** — distinct from both. See `notes/cell-index-mapping.md`, `notes/charging-analysis.md`, `notes/battery-degradation.md`.

### Lower Priority
- [ ] Re-run `labview_xml_extract.py --batch` on full CODACAN/ directory for any missed cluster IDs
- [ ] FCHM — does it ever appear on B CAN?
- [ ] OCS / SRS — only relevant if airbag work needed
- [ ] IPK_Recvd.vi — what does the instrument cluster subscribe to?

---

## File Layout

```
projects/coda/
  README.md                       # This file — project overview & entry point
  CODA-B-CAN.dbc                  # B CAN DBC (35 messages, Motorola byte order)
  CODA-D-CAN.dbc                  # D CAN DBC (22 messages, Motorola byte order)
  CODA-C-CAN-cells.dbc            # C CAN cell voltage/temp DBC (cell frames confirmed; non-cell IDs not yet characterized)
  can_topology.JPG                # CAN network architecture diagram
  Coda-Green-Screen-JPGs/         # Photos of CODACAN green-screen display
  gui_profile.py                  # CODACAN GUI screen layout profiling script
  CODACAN/                        # Original CODACAN application + decompiled LabVIEW assets
    CODACAN.exe                   # Standalone CODACAN application (requires NI CAN dongle)
    labview-signals.json          # Full signal inventory (49 clusters, 464 signals)
    cmm_glb_signals.json          # Parsed CMM_glb.xml cluster data
    all_globals_signals.json      # Combined globals signal dump
    ui_layout.json                # Captured GUI field layout (pixel positions, signal mappings)
    ICD/                          # Per-module CAN frame parsers (.vi + .bin VICD code)
    Globals/                      # Per-module global variable clusters (.xml + .vi)
  Diagnostic/                     # PRIVATE diagnostic learnings — never published (see README.md)
    README.md                     # Folder purpose, layout, and the publish rule
    coda_security.py              # SecurityAccess key computation + unlock (private capability)
    notes/                        # Private learnings, one .md per topic
    logs/                         # Omitec scan-tool captures (cited by analysis notes — do not move)
    precursor/                    # Archived pre-repo scripts, superseded by coda-diagnostics/
  coda-diagnostics/               # Reverse-engineered scan tool scripts — own git repo (see README.md)
    README.md                     # Overview, supported modules & CAN dongles
    read_dtcs_coda.py
    clear_dtcs_coda.py
    read_cell_voltages_and_temps.py
    coda_dtc_list.csv             # Known DTC codes and descriptions
    requirements.txt
    test_regression.py
    docs/                         # Protocol documentation
    playback/                     # Fake-car CAN emulation scripts (see README.md)
  components/                     # Hardware documentation for individual modules
    lear/                         # Lear charger — pinout, wiring, Chevy Volt crossover docs
    AC-Compressor/                # Ford scroll compressor — CAN protocol docs & label photos
  logs/                           # CAN bus captures
    README.md                     # Log file inventory
  tools/                          # Coda-specific analysis tools (see tools/README.md)
    README.md
    codacan_capture.py            # Automated CODACAN screen capture and signal mapping
    cowork_replay.py              # CAN log replay for CODACAN cowork validation sessions
    flash_cal.py                  # Flash a named DLCM calibration (human front end)
    flash_sim/                    # DLCM reflash stack + Omitec / gateway simulators (see flash_sim/README.md)
    codasim/                      # Executable DLCM / ECM2 / driveline model (see codasim/README.md)
    dbc_skeleton_labview.py       # Generates DBC skeleton stubs from LabVIEW signal inventory
    labview_xml_extract.py        # Extracts signal clusters from LabVIEW Globals XML files
    update_skeleton_dbcs.py       # Updates DBC skeleton from labview signal inventory
    vicd_disasm.py                # VICD bytecode disassembler for ICD .vi files
  notes/                          # Analysis session write-ups (see README.md)
    README.md                     # Index of analysis notes
    android-coda-app-notes.md     # Android app CAN overlay development notes
    bonnydoon-limp-analysis.md    # Drive with BMS limp mode — weak cell (Cell95) identified
    battery-degradation.md        # Longitudinal pack fade & imbalance (2026-02→07); usable ~16 kWh, weak cell dominates loss; 0x381 Min/Avg byte-order corrected
    charging-analysis.md          # L2 home charging session (codacharging.log)
    chargepointcharge-analysis.md # Full charge to 100% at Chargepoint (OV confirmed)
    codacan-capture-notes.md      # codacan_capture.py development and tuning notes
    codacan-signal-decode-notes.md # CODACAN bench replay signal decode — all phases
    gateway/                      # Gateway (GWM) firmware decompile (NXP LPC2xxx ARM) — CAN routing/firewall table recovered
      coda-gateway-decompile-notes.md # Gateway decompile notes (folder also holds coda_gateway.bin firmware image)
    dlcm/                         # DLCM firmware decompile (Continental EMS9180, TriCore LE) — torque LUT analysis
      README.md                   # START HERE for the DLCM — folder map, document index, folder-wide units and table-duplication traps
      coda-dlcm-decompile-notes.md # DLCM decompile notes (folder also holds PROG/CAL .bin firmware images)
      dlcm-torque-flow.md         # §10.7 gradient-limiter Simulink block diagram (re-transcription of the flow-chart PNG)
      dlcm-torque-limiter-code-trace.md # Modern §10.7 vs old-scheme trace: behavioral verdict (speed-dependent limiter = §10.7) + code caveats (2026-07-08)
      dlcm-second-pass-hypotheses.md # Second-pass investigation angles for the CAL gradient-LUT hunt
      dlcm-dtcs-investigation.md  # DLCM fault subsystem: event->DTC table (0xA002451E), per-event CAL config, P3115 roll-up chain, C0044 brake rationality (validated on the bus), which DTC inputs are on the un-tapped Motor CAN
    driver-inputs.md              # Throttle, brake, PRND, body electronics, gateway rebroadcast
    efficiency-calculation.md    # Wh/mile: drivetrain / HVAC / 12 V split (293.6 pack, 365.9 grid); method, validation, capture-coverage caveats
    driving-sequence-investigation.md  # Startup sequence, HVAC, AC compressor signals
    othercars-comparison.md       # Signal comparison with other Coda vehicles
    outside-air-temp-investigation.md  # Outside-temp display dropped — no reliable ambient sensor on CAN
    thermal-behavior-investigation.md  # Pack heater / cold-start thermal behavior
    traction-control-analysis.md  # TC events via 0x208 REAR-axle divergence (0x208 is the non-driven
                                  #   rear pair, not halfshafts -- its 'DHL/DHR halfshaft' labels and its
                                  #   0x312 decode are both superseded; see dlcm/esp-torque-intervention.md)
    plans/                        # Analysis plan files (rcu_firmware_extraction; dlcm_ram_read_mapping + dlcm_variant_opcode_decode, 2026-09-13)
    artifacts/                    # Generated data files: CSVs, JSONs, survey outputs (see artifacts/README.md)
      cowork-results/             # Cowork-driven CODACAN validation output (see README.md)
```
