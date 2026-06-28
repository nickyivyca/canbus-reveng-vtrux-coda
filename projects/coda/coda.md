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

| Bus   | Anchor IDs | Condition | Confidence |
|-------|-----------|-----------|------------|
| C CAN | 0x000–0x019 (cell voltages, 104 cells) | Always present | Definitive |
| B CAN | 0x1D5, 0x48A (DCDC), 0x275 (BMS limits), 0x381 (cell min/max/avg), 0x383 (SoC) | Always present when key-on | High |
| B CAN | 0x274–0x27D, 0x615–0x617 (charger) | Only during charging | Definitive |
| D CAN | 0x308, 0x312, 0x325, 0x330, 0x580 (D CAN exclusive — not rebroadcast to B CAN) | Confirmed in 4 sessions | High |

D CAN exclusive IDs are never rebroadcast to B CAN by the GWM gateway. Most other D CAN IDs (0x1C0, 0x208, 0x210, 0x212, 0x418, etc.) are also present on B CAN via gateway pass-through. See `notes/driver-inputs.md` for full gateway rebroadcast inventory.

### Non-Cell IDs Visible on C CAN

Non-cell IDs (0x0FF, 0x200–0x203, 0x300–0x304, 0x621–0x627) appear in C CAN captures
alongside the cell voltage frames. These are **native BMS output** — the BMS broadcasts
additional status messages on its C CAN diagnostic port beyond just cell data.

**Confirmed:** `codacharging.log` (Bus 1=C CAN, Bus 3=B CAN) shows zero shared IDs between
the two buses, ruling out any electrical coupling or cross-bus leakage at the OBD connector.
See `notes/charging-analysis.md` Goal 2. D CAN gateway rebroadcast behavior characterized — see `notes/driver-inputs.md` for full inventory.

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
- **ACCM** and **AICM** — may be the same module. Unconfirmed; treat as hypothesis.

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

**Pack voltage cross-check:** `sum(104 raw cell values) / 1000` = pack voltage in V (~338V typical).
Use this to anchor/validate any pack voltage signal found on B CAN.

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
| 0x050 | BMSChargerCmd | BMS | HVCurrentCmd, MaxVoltage |
| 0x270 | BMS_FaultStatus | BMS | BMSFaultStatus |
| 0x275 | BMSDriveLimits | BMS | DischargeLimit (alias: MotorDriveLimit), ChargeLimit, PackCurrent, PackVoltage, HVACLimit |
| 0x2C1 | BMSDrivingRange | BMS | DrivingRange_Exp, DrivingRange_Max, DrivingRange_Min — scale unconfirmed |
| 0x378 | BattPowermode | BMS | HVPowermode, Chargemode, KeepWakeNetworkBMS, rolling counter, BMSmode |
| 0x381 | BMSVminVmax | BMS | Min cell mV, max cell mV, avg cell mV, VminId, VmaxId. VminId/VmaxId use BMS-internal cell numbering, not C CAN frame/byte position. |
| 0x382 | BMSThermal | BMS | Cell_T_avg, Cell_T_max, Cell_T_min, MaxTempId, MinTempId |
| 0x383 | BMSBattStatus | BMS | SoC, HVBattCharging, ChrgPortOpen, ChargeCableConnected |
| 0x390 | BMS_HVBattTemp1 | BMS | FrontInletAirTemp, RearInletAirTemp, ReturnAirTempPsg, ReturnAirTempDrv, AllowedCellTempMax, AllowedCellTempMin, AllowedCellTempDiff, AllowedHumidity |
| 0x271 | GWM_VehFaults | GWM | VehFaultSeverity, VehicleFaultLampReq (OFF/YELLOW/RED), key-on lamp-test flag, VehicleFault |
| 0x276 | HVACStatus | HVAC | PTC_PowerConsumption, ACCM_PowerConsumption, HVACHVDisableStatus (enum, bit layout provisional), CIntTempRadOutlet, CIntTempPTCOutlet, PTCHeaterPWM, RadiatorFanPWM, BattFanPWM |
| 0x391 | HVACAirState | HVAC | UnderHoodHumidity, UnderHoodTemp, OpAirHumidity, OPAirTemp, ReturnAirTemp, EvapAirOffTemp |
| 0x274 | ChrgrSysFaultsTemp | CMM | Fault status, Chrgr1Temp, Chrgr2Temp |
| 0x277 | CMMTempStatus | CMM | CaseTemp confirmed; PFCTemp, HV1/HV2 inconclusive |
| 0x279 | CMMOutputValues | CMM | HVOutVoltage, HVOutCurrent, LVOutVoltage, LVOutCurrent (all confirmed; HVOutVoltage cross-checks with C CAN pack voltage) |
| 0x27A | CMSTempStatus | CMS | PFCTemp, HV1Temp, HV2Temp, CaseTemp (all confirmed) |
| 0x27B | CMSInputValues | CMS | ACInVoltage, ACInCurrent, ACInPower (all confirmed) |
| 0x27C | CMSOutputValues | CMS | HVOutVoltage, HVOutCurrent, LVOutVoltage, LVOutCurrent (all confirmed) |
| 0x27D | CMMInputValues | CMM | ACInVoltage, ACInCurrent, ACInPower |
| 0x615 | ChrgrSysLimits | CMM | Limit and enable flag signals |
| 0x616 | ChrgrSysCtrlEcho | CMM | Echo of charger control commands |
| 0x617 | ChrgrSysSts | CMM | Charger system status |
| 0x61A | CMSHVCmd | CMS | HV Cmd Voltage, HV Cmd Current, AC Max Current Avail, HV Cmd Enabled |
| 0x491 | IPK_Status | IPK | IPK_FaultLamps (key-on latch; set once at key-on, does not update mid-drive) |

**Charger note:** CMM and CMS each report their own individual measurements (not totals).
Charger IDs are only present during active charging sessions. CODACAN CH M/S tab displays
CMS-side values (0x27A/27B/27C); CMM-side slots (0x277/27D/279) have lower display priority.
See `notes/charging-analysis.md` for encoding and full decode.

#### D CAN Signals

| ID (hex) | DBC Name | Module | Signals |
|----------|----------|--------|---------|
| 0x1C0 | MCM_Telemetry | DLCM | Torque, HV_Voltage, HV_Current, Motor_Speed |
| 0x212 | DLCM_TorqueRequest | DLCM | BrakeSW confirmed (B2.bit0); TorqueRequest: 12-bit nibble-split `(B4 & 0x0F) << 8 \| B5`, zero=2000 (0x7D0), scale ~0.244 Nm/count (scale unconfirmed; r=+0.999 vs 0x1C0 Torque across 4 drive logs); KeepWakeNetworkDLCM position unconfirmed |
| 0x241 | MCM_Thermal | DLCM | Rotor temp, Stator temp, IGBT temp (role confirmed; DLC=8; per-byte assignment unconfirmed — see codacan-signal-decode-notes.md Section 6 item 6) |
| 0x278 | DLCM_Keepalive | DLCM | KeepWakeNetworkDLCM, EngineStsRun |
| 0x315 | DLCM_Status | DLCM | Brake_SW, rolling counter, Batt_Volt |
| 0x418 | DLCM_Globals | DLCM | PRND, gear status |
| 0x052 | ParkingBrake_Crank | misc_Recvd | ParkingBrake, crank signal |
| 0x080 | EPS_Steering | EPS | RelativeSteeringAngle; CRC8 protected |
| 0x210 | ThrottlePedalPos | misc_Recvd | ThrottlePedalPos |
| 0x215 | Unknown | misc_Recvd | 16-bit word, scale 1/128 (VICD). TCM.ParkLock hypothesis invalidated — see `notes/codacan-signal-decode-notes.md` Section 5c. |
| 0x271 | GWM_VehFaults | GWM | Gateway rebroadcast of B CAN 0x271 (same structure) |
| 0x273 | IPK_ClusterData | IPK | Primary ODO, Interior Illum, Side Light Active, Low Beam Active |
| 0x308 | TCM_ParkPin | TCM | ParkPinState, shaft speed. BorgWarner cross-vehicle match with Vtrux — see `notes/borgwarner.md`. |
| 0x330 | Long_Accel | ESC? | Longitudinal acceleration |
| 0x370 | DeathCounters | misc_Recvd | Death counter batch |
| 0x55C | TCM_State | TCM | TCMState. BorgWarner cross-vehicle match with Vtrux — see `notes/borgwarner.md`. |
| 0x600 | TPMS_Pressure | RCU | Tire pressures; does not trigger TPMS indicator in CODACAN |

**Note:** misc_Recvd IDs (0x052, 0x080, 0x210, 0x215, 0x271, 0x273, 0x330, 0x370, 0x600)
are assigned to D CAN (RCU, TCM, ESC are D CAN modules), but most are also rebroadcast to
B CAN by the GWM gateway. See `notes/driver-inputs.md` for the full gateway rebroadcast
inventory.

**Open items:** BMSmode shows different values on other vehicles — meaning unknown. 0x2C1
range scale unconfirmed (single calibration point). 0x410 boolean bit positions unresolved.

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

#### 0x312 — ESC Internal Measurement Frame (D CAN, 100 Hz) -- 2026-03-20

Mux frame, NOT a simple 4-channel wheel speed message (previously mischaracterized).
Full decode in `notes/traction-control-analysis.md` (0x312 Structure Decoded section).

| Byte(s) | Name | Encoding | Notes |
|---------|------|----------|-------|
| B0 | Mux/counter | [7:4]=Gray-code 4-state counter, [3:0]=channel ID (6-12) | 30 raw values → 7 channel IDs |
| B1 | Torque echo | uint8, r=0.84 with 0x212 B5 (motor torque output) | B1=B3 (redundant); echoes 0x212 B5 -- confirmed 2026-03-20 |
| B2 | Channel ID echo | Always = B0[3:0] | NOT independent data |
| B3 | Torque echo | uint8 | Same as B1 |
| B4-B5 | Speed_inv (BE uint16) | 2000=startup, 2119=stationary Ready, 3199=clamped (low speed / TC active); below 3199 inversely proportional to speed at HIGH speeds only | Resolved only at LR>1400 in defroster2 log |
| B6-B7 | Speed_fwd (BE uint16) | 2000=startup only, 800=low speed floor or TC active, above 800 proportional to vehicle speed | Tracks LR (left rear) speed proxy |

Channel distribution: ch 6-7 at high speed, ch 8 dominant at normal speed, ch 9-12 at low speed or TC/ABS.
Both B4-5 and B6-7 clamped to limits (3199 and 800) during TC intervention.
Scale to km/h not yet determined; requires LR km/h calibration (pending motor-rpm → km/h conversion).

#### 0x391 — HVAC Air State B4 (B111D sentinel)

CIntTempRadOutlet (0x276 B3, radiator outlet temp) shows 0x58 = -40°C in parts car — open-sensor sentinel value for HVAC DTC B111D (coolant temp sensor fault). Never seen below -7°C in normal operation. DTC B112D (airmix motor) has no observable CAN status because the airmix flap is downstream of the radiator sensor.

**B3 OPAirTemp — unreliable as outside-air temp.** Decodes cleanly (T = raw − 128 °C) but is a damped/poorly-calibrated *estimate*, not a clean ambient thermistor: it reads ~+12 °F high vs ground-truth weather in all conditions (including parked at night) and stays stuck high even at highway speed, so it cannot be offset-calibrated. An "Outside: NN°F" display sourced from it was added then **dropped** (removed in `coda-debug (19).apk`, 2026-05-22). Full analysis — including why no other CAN sensor (FrontInletAirTemp 0x390 B0 reads pack temp after charge/hot-soak, EvapAirOffTemp 0x391 B5 is HVAC-coupled) is a reliable ambient source — in `notes/outside-air-temp-investigation.md`.

### 9. Diagnostic Tool Reverse Engineering (Confirmed, Diag CAN)

`coda-diagnostics/` contains Python scripts reverse-engineered from the Omitec dealer scan tool.
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

ECU 0x7E8, Continental EMS9180. Two plaintext images: PROG (1.83 MB) and CAL (114 KB); SH-4 core, analyzed in Ghidra. The work targets the §10.7 State-Dependent Torque Gradient Limiter calibration LUTs (to widen the rate limit through the lash zone for throttle feel). Firmware build `1CI527_D003`. See `notes/dlcm/coda-dlcm-decompile-notes.md`.

### BMS — extracted but encrypted (blocked)

The BMS application image (249,856 bytes) was downloaded via the same UDS method but is **encrypted**: ~7.9992-bit entropy (AES-class), no readable strings or instruction patterns, despite the UDS request declaring no encryption; size is an exact multiple of the AES block size. Decompilation is not meaningful until decrypted, and the firmware-encryption key is a separate secret from the SecurityAccess key (not recoverable from the captured session). Not pursued further.

### Green-screen / telemetry box — code-protected (parked)

The dashboard green-screen display box uses a Microchip **PIC32MX564F128L** (MIPS32). ICSP access was established (valid Device ID read), but the part is **code-protected** (DEVCFG0.CP fuse set) and there is no reflash protocol to capture, so flash readout is blocked. The only remaining path is voltage glitching, which is not being pursued for now. Extraction parked.

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
| `CODA-D-CAN.dbc` | D CAN messages (ESC, DLCM, EPS, misc, GWM) | 22 messages. Confirmed signals documented in signal table above. 0x312 excluded — mux frame partially understood, see `notes/traction-control-analysis.md`. Unconfirmed bytes use `Packet_N` placeholders. |
| `CODA-C-CAN-cells.dbc` | Cell voltage/temp frames on C CAN | Cell voltage portion confirmed and complete — 26 frames, 104 cells. Additional non-cell IDs visible on C CAN (0x0FF, 0x200–0x203, 0x300–0x304, 0x621–0x627) not yet characterized; not in DBC. |

All multi-byte signals use Motorola byte order (@0+, big-endian). Unconfirmed bytes use
`Packet_N` placeholders. Placeholder IDs (sentinels ≥ 8191) from LabVIEW clusters removed —
that information is preserved in `CODACAN/labview-signals.json`.

---

## Log Capture Status

See `logs/README.md` for log file inventory.

---

## Open Questions & Investigation Areas

### High Priority
- [ ] **CODACAN signal decode — Phase 5 in progress.** Most signals confirmed; partial/open items tracked in `notes/codacan-signal-decode-notes.md` (Sections 5b, 5c, 6, 7). Key remaining: IPK ODO/lighting byte positions (0x491/0x273), IPK gauge feeds (SoC%/speed source unknown), 0x410 B0 boolean bit positions, 0x270 B0 fault sub-field split, 0x2C1 scale, 0x050 B4-B7 characterization.

### Medium Priority
- [ ] RCU — TPMS keepalive frame unknown. 0x600 carries pressure data (1.37 kPa/count) but does not trigger TPMS indicator. **Capture task:** trip the immobilizer to force RCU to broadcast its keepalive ID.
- [ ] **BMSmode (0x378 B2) unknown value range**: Normal car shows 0xD2 (210) driving, 0xA9 (169) charging. the second reference car and parts car both show 0xF2–0xF8 (242–248) — unknown whether this indicates a fault/degraded state or firmware variant. Step=1 sweep of 0x378 B2 needed to catalog all values against CODACAN display changes.
- [ ] Decode 0x215, 0x330 (and confirm 0x600) — see `notes/codacan-signal-decode-notes.md` Section 5c.
- [ ] Identify weak cell #94 in C CAN individual cell data near EOC

### Lower Priority
- [ ] Re-run `labview_xml_extract.py --batch` on full CODACAN/ directory for any missed cluster IDs
- [ ] FCHM — does it ever appear on B CAN?
- [ ] OCS / SRS — only relevant if airbag work needed
- [ ] IPK_Recvd.vi — what does the instrument cluster subscribe to?

---

## File Layout

```
projects/coda/
  coda.md                         # This file — project overview & entry point
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
    dbc_skeleton_labview.py       # Generates DBC skeleton stubs from LabVIEW signal inventory
    labview_xml_extract.py        # Extracts signal clusters from LabVIEW Globals XML files
    update_skeleton_dbcs.py       # Updates DBC skeleton from labview signal inventory
    vicd_disasm.py                # VICD bytecode disassembler for ICD .vi files
  notes/                          # Analysis session write-ups (see README.md)
    README.md                     # Index of analysis notes
    android-coda-app-notes.md     # Android app CAN overlay development notes
    bonnydoon-limp-analysis.md    # Drive with BMS limp mode — weak cell #94 identified
    charging-analysis.md          # L2 home charging session (codacharging.log)
    chargepointcharge-analysis.md # Full charge to 100% at Chargepoint (OV confirmed)
    codacan-capture-notes.md      # codacan_capture.py development and tuning notes
    codacan-signal-decode-notes.md # CODACAN bench replay signal decode — all phases
    gateway/                      # Gateway (GWM) firmware decompile (NXP LPC2xxx ARM) — CAN routing/firewall table recovered
      coda-gateway-decompile-notes.md # Gateway decompile notes (folder also holds coda_gateway.bin firmware image)
    dlcm/                         # DLCM firmware decompile (Continental EMS9180, SH-4) — torque LUT analysis
      coda-dlcm-decompile-notes.md # DLCM decompile notes (folder also holds PROG/CAL .bin firmware images)
    driver-inputs.md              # Throttle, brake, PRND, body electronics, gateway rebroadcast
    driving-sequence-investigation.md  # Startup sequence, HVAC, AC compressor signals
    othercars-comparison.md       # Signal comparison with other Coda vehicles
    outside-air-temp-investigation.md  # Outside-temp display dropped — no reliable ambient sensor on CAN
    thermal-behavior-investigation.md  # Pack heater / cold-start thermal behavior
    traction-control-analysis.md  # ESC 0x312 mux frame decode
    plans/                        # Analysis plan files (empty — all executed)
    artifacts/                    # Generated data files: CSVs, JSONs, survey outputs (see artifacts/README.md)
      cowork-results/             # Cowork-driven CODACAN validation output (see README.md)
```
