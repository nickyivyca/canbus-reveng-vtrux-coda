# CODACAN Signal Decode -- Notes

*Consolidated from: codacan-validation-phase2.md, cowork-codacan-validation-plan.md,
cowork-codacan-protocol.md (Phases 2-7), phase5-sweep-schedule.md,
CODACAN/labview-decode-plan.md, driver-inputs-plan.md. Last updated: 2026-03-03.*

See `codacan-capture-notes.md` for the OCR capture tool (`codacan_capture.py`) and Phase 1
(UI Discovery / layout JSON setup).

---

## 1. Bench Setup & Tool Overview

CODACAN (`CODACAN/CODACAN.exe`) is the original Coda engineering ground-truth decoder.
By replaying captured log files onto a bench CAN bus and observing CODACAN's labeled GUI,
every CAN ID and byte is mapped to a named field with its scale and offset.

**Bench setup (confirmed working):**
- PCAN USB on `PCAN_USBBUS1` -- TX only -- bench harness with 120 ohm termination
- NI CAN dongle <-- RX <-- same harness (NI dongle is never touched during experiments)
- Both at 500 kbps. CODACAN is bus-agnostic -- B CAN + D CAN traffic replayed simultaneously
  through the single NI dongle.

**Tools:**
- `tools/cowork_replay.py` -- replay with modes: `baseline`, `drop-id`, `solo-id`, `sweep-byte`, `inject`
- `tools/codacan_capture.py` -- OCR capture: `snapshot`, `watch` (see `codacan-capture-notes.md`)

**Important:** Always close and reopen CODACAN.exe before any capture session. Stale display
values from prior sessions persist and contaminate baselines.

**Python executable:** `py -3.11-32` (default `py` = 3.9 on this machine; fails on `dataclass(slots=True)`)
**CAN brand flag:** `--brands pcan`
**Add `--no-wait`** to skip the interactive "Press Enter" prompt for unattended runs.

---

## 2. Quick Reference -- Replay Commands

**Key paths:**

| What | Path |
|------|------|
| CODACAN app | `projects/coda/CODACAN/CODACAN.exe` |
| Log files | `projects/coda/logs/` |
| Results output | `projects/coda/notes/artifacts/cowork-results/` |
| B CAN DBC | `projects/coda/CODA-B-CAN.dbc` |
| D CAN DBC | `projects/coda/CODA-D-CAN.dbc` |

**Recommended logs:**

| Log | Contents | Best for |
|-----|----------|---------|
| `codacharging.log` | B+C CAN, charging | BMS, charger, DCDC tabs |
| `codadriveslowturnonwithdefroster2.log` | B+C+D CAN, driving | Driveline, HVAC, IPK tabs |

**Driving log time slice:** Always use `--start-time 55 --end-time 695`. The first 55 seconds
are stationary key-on -- motor signals are zero before Ready state, skewing median frames.

### Experiment Modes

```
# Full baseline replay
py -3.11-32 tools/cowork_replay.py baseline <log> --loop --no-wait --brands pcan

# Drop one ID -- observe which fields disappear
py -3.11-32 tools/cowork_replay.py drop-id <log> --target 0x275 --loop --no-wait --brands pcan

# Solo one ID -- observe which fields appear
py -3.11-32 tools/cowork_replay.py solo-id <log> --target 0x275 --loop --no-wait --brands pcan

# Inject a specific crafted frame on repeat
py -3.11-32 tools/cowork_replay.py inject --id 0x275 --data "64 32 80 00 01 5E 00 DD" --brands pcan
```

### Two-Terminal Sweep Workflow

Terminal B (start first, leave running):
```
py -3.11-32 tools/codacan_capture.py watch --tabs <TABS> --results-dir "projects/coda/notes/artifacts/cowork-results/sweep"
```

Terminal A -- coarse scan (17 steps x 2s = 34s per byte):
```
py -3.11-32 tools/cowork_replay.py sweep-byte <log> --target <ID> --byte <N> --dwell 2 --step 16 --no-wait --brands pcan
```

Terminal A -- fine sweep (256 steps x 1s = 4.3 min per byte):
```
py -3.11-32 tools/cowork_replay.py sweep-byte <log> --target <ID> --byte <N> --dwell 1 --step 1 --no-wait --brands pcan
```

Terminal A -- multi-byte 16-bit BE sweep:
```
py -3.11-32 tools/cowork_replay.py sweep-byte <log> --target <ID> --byte <N>-<N+1> --dwell 1 --step 256 --no-wait --brands pcan
```

Watch auto-captures at `dwell/2` into each step, writes per-step JSONs to
`cowork-results/sweep/`, and merges into `sweep_results.json` on completion.
Restart Terminal A for the next target; Terminal B stays running unless `--tabs` changes.

### Deriving Scale/Offset from Sweep Data

```python
import json, numpy as np
data = json.loads(open('projects/coda/notes/artifacts/cowork-results/sweep/sweep_results.json').read())
obs = data['0x275']['byte_0']['observations']
pairs = [(o['input_value'], o['fields']['BMS']['BattSentDischargeLimit (A)']['value'])
         for o in obs if o['fields']['BMS']['BattSentDischargeLimit (A)']['ok']]
x = [p[0] for p in pairs]
y = [p[1] for p in pairs]
scale, offset = np.polyfit(x, y, 1)
print(f"scale={scale:.6f}, offset={offset:.4f}")
```

For enum/text fields: group observations by text string and record which raw values produce
each string.

### Inject Mode (Verification)

```
py -3.11-32 tools/cowork_replay.py inject --id 0x275 --data "64 32 80 00 01 5E 00 DD" --brands pcan
py -3.11-32 tools/codacan_capture.py snapshot --tabs BMS --output verify_inject.json
```

Expected for data above: DischargeLimit = 200 A (B0=0x64=100, x2), ChargeLimit = 100 A
(B1=0x32=50, x2).

---

## 3. Phase Completion Summary

| Phase | Status | Key output |
|-------|--------|-----------|
| 1 -- UI Discovery | **Complete** | `ui_layout.json`, annotated PNGs in `screenshots/ui_discovery/` |
| 2 -- Module Presence | **Complete** | `module_presence_map.json` -- see Section 4 |
| 3 -- Baseline Capture | **Complete** | `baseline_driving.json` (177/179 fields), `baseline_charging.json` (173/179) |
| 4 -- ID->Field Mapping | **Complete** | `id_field_map_codacharging.json` (91 tests), `id_field_map_codadriveslowturnonwithdefroster2.json` (97 tests) |
| 5 -- Byte Sweep | **In progress** | `sweep_results.json` -- most Tier 1/2 signals confirmed; see Section 5 |
| 6 -- Validation | Not started | `validation_report.md` |
| 7 -- DBC Update | Not started | Updated DBC files |

---

## 4. Phase 2 -- Module Presence Mapping (Complete)

**Date:** 2026-02-22
**Method:** `solo-id` replay + `snapshot --tabs Overview` for each ID
**Logs:** `codacharging.log` (B+C CAN), `pressingthrottlethenbrake.log` (D CAN, car in Ready)
**Results file:** `artifacts/cowork-results/module_presence_map.json`

### B CAN Modules

| Module | Indicator | Trigger ID(s) | Notes |
|--------|-----------|--------------|-------|
| BMS | BMS | 0x050, 0x270, 0x275, 0x378, 0x383, 0x1D7, 0x2C1, 0x381, 0x382, 0x390, 0x620 | Any one sufficient |
| DCDC | DCDC | 0x1D5, 0x48A | Any one sufficient |
| CHM | CHM | 0x054, 0x277 | 0x054 (52 Hz) = CMM keepalive; 0x277 = CMMTempStatus |
| CHS | CHS | 0x27A, 0x61A | 0x61A (50 Hz) = CMS keepalive |
| AICM | AlCM | 0x276, 0x391, 0x392, 0x410 | Thermal controller, **B CAN native**. 0x276 = AICM status. 0x410 = compressor command AICM sends to ACCM. All four IDs share one transmit clock (102.90 ms, 4.60 ms jitter) distinct from every other B CAN message (100.00 ms, <1.3 ms) across 113 sessions -- see `artifacts/x276_bus_presence.py` Phase 10. **Hypothesis (strengthened 2026-08-23):** AICM and ACCM are separate modules -- 0x439 (ACCM) sits on the tight 100.00 ms clock, not the AICM one. Not proof: one ECU can run two timer tasks. |
| ACCM | ACCM | 0x439 | Compressor status frame only |
| IPK | IPK | 0x491 | **0x491 is the IPK heartbeat.** 0x6FA does NOT trigger indicator. |
| GWM | GWM | 0x271 | **0x271 is the GWM heartbeat.** 0x248 and 0x2C2 do NOT trigger GWM. |

### D CAN Modules

| Module | Indicator | Trigger ID(s) | Notes |
|--------|-----------|--------------|-------|
| DLCM | DLCM | 0x1C0, 0x210, 0x212, 0x241, 0x278, 0x315, 0x418 | Any one sufficient. 0x210 and 0x212 confirm DLCM as originator. |
| EPS | EPS | 0x080 | Steering angle frame. Triggers EPS only, not ESC. |
| TCM | TCM | 0x55C | **0x55C is the TCM heartbeat.** |

### Modules with No Trigger Found

| Module | Conclusion |
|--------|------------|
| ESC | No ID triggers the ESC indicator. All D CAN-exclusive IDs tested (0x080, 0x208, 0x308, 0x312, 0x325, 0x580, etc.). CODACAN may have no ESC presence indicator implemented, or the keepalive frame is absent from our captures. |
| TPMS | 0x600 (pressure data) does NOT trigger indicator. RCU keepalive ID unknown. **Capture task:** trip the immobilizer -- RCU must broadcast, which may finally light the TPMS indicator and reveal its heartbeat ID. |
| TEM | Consistently dark -- likely not populated on US-market cars. |
| SRS | Consistently dark. No crash-state NM frames in normal captures. |

### Reclassifications from Phase 2

| ID | Old label | Corrected label |
|----|-----------|-----------------|
| 0x271 | "Death Counter partial" | GWM heartbeat + VehFaults |
| 0x55C | "VehFaults or status flags" | TCM heartbeat |
| 0x054 | Uncharacterized (52 Hz) | CMM keepalive |
| 0x61A | Uncharacterized (50 Hz) | CMS keepalive |

### Methodology Note

All modules use an "any one" threshold -- a single frame from any confirmed ID lights the
indicator. Use `solo-id` for discovery (it loops all frames of an ID, so a late-waking module
is still found). Use `pressingthrottlethenbrake.log` (14.5s, car in Ready) for baselines --
loads fast and all modules active from frame 1. Avoid slow key-on logs for baselines.

---

## 5. Phase 5 -- Byte Sweep Signal Status

### 5a. Confirmed & Complete

Signal encoding fully confirmed (byte position, scale, offset). Full detail in `projects/coda/README.md`.

| ID | Name | Encoding summary |
|----|------|-----------------|
| 0x080 | EPS steering | B2-B3: BE uint16 x 0.1, center=2000 (deg). CRC8 in B7. |
| 0x1C0 | MCM Telemetry | 4x LE uint16, zero=0x7D80. B0-B1: Torque (x0.1 Nm, offset -3212.8). B2-B3: HV_Voltage (x0.1 V). B4-B5: HV_Current (x0.1 A). B6-B7: Motor_Speed (x0.5 rpm, offset -16064). |
| 0x1D5 | DCDCStatus1 | B0[4]: HVInputCurrentSensorValidity. B0[7]: 14VMasterFault. B1: HVInputCurrent (x0.1 A). B2[2:0]: DCDCDtcStatus. B2[7:3]: DtcIndex. B3: 14VMonitor (x20/255 V). B4[7]: 14VConditionBit. B6[6:0]: 14VCurrentMonitor (x2 A). |
| 0x1D7 | BMS_DCDCEnableSet | Enable_14V, BuckBoostVoltageSetPoint, Boost_Enable -- all confirmed. |
| 0x208 | ESC BrakePressure | B2-B3: BE uint16, zero=0x1000=4096 (apply offset -4096). |
| 0x210 | ThrottlePedalPos | B2: uint8 x 0.4 (%). |
| 0x212 | DLCM TorqueRequest | B2.bit0 = brake switch. Drives TorqueRequest (Nm) and KeepWakeNetwork. |
| 0x241 | Motor Thermal | Role confirmed (drop-ID: Rotor/Stator/IGBT fields go to 0). DLC=8 confirmed from log. DLCM_glb.xml cluster order: IGBT, Rotor, Stator. Per-byte assignment unconfirmed -- see Section 5b. |
| 0x271 | GWM VehFaults | B0[7:4]: VehFaultSeverity. B0[1:0]: VehicleFaultLampReq (00=OFF, 01=YELLOW, 10=RED). B0[2]: VehicleFaultB0Bit2 (PROVISIONAL -- set during key-on lamp test). B1-B4: VehicleFault (BE uint32). |
| 0x275 | BMSDriveLimits | B0: BattSentDischargeLimit (uint8 x2=A). B1: BattSentChargeLimit (uint8 x2=A). B2-B3: PackCurrent (BE uint16 x0.1 A, zero=0x8000). B4-B5: PackVoltage (BE uint16, 1 V/bit). B6: BattSentHVACLimits (uint8 x2=A). B7: unknown (baseline 0xDD). |
| 0x276 | HVACStatus | B0: PTC_PowerConsumption (x0.1 kW). B1: ACCM_PowerConsumption (x0.1 kW). B2: HVACHVDisableStatus (enum, sub-byte layout PROVISIONAL). B3: CIntTempRadOutlet (raw-40 degC). B4: CIntTempPTCOutlet (raw-40 degC). B5: PTCHeaterPWM (x100/255 %). B6: RadiatorFanPWM. B7: BattFanPWM. |
| 0x278 | Drive Keepalive | KeepWakeNetwork, EngineStsRun -- drop to false when suppressed. |
| 0x315 | DLCM Status | B0.bit0: Brake_SW. B0.bits2-7: rolling counter. B5: Batt_Volt (uint8 x0.1 V). |
| 0x378 | BattPowermode | B0[7:4]: HVPowermode enum. B0[3:0]: Chargemode enum. B1[1:0]: KeepWakeNetworkBMS. B1[2]: rolling counter (~6Hz). B2: BMSmode (uint8; 0xD2=driving, 0xA9=charging). B3-B7: unknown (not yet swept). |
| 0x381 | BMSVminVmax | B0-B1: avg cell mV. B2-B3: max cell mV. B4-B5: min cell mV (all BE uint16, 1 mV/bit). B6: VmaxId. B7: VminId. **Corrected 2026-07-15**: this row previously had Min<->Avg and VminId<->VmaxId swapped (went by the cluster *name* "VminVmax" instead of the LabVIEW field order Vavg,Vmax,Vmin,VmaxId,VminId). Empirically avg lies between min/max in 99% of 20k samples; VmaxId(B6) pins to one cell index at charge termination. **VmaxId/VminId = C CAN cell number directly** (`VmaxId 82 = Cell82`), both 1-based since the 2026-07-22 C CAN DBC renumber (was 0-based; older exports need +1). See `cell-index-mapping.md`. |
| 0x382 | BMSThermal | B0: Cell_T_avg. B1: Cell_T_max. B2: Cell_T_min (all uint8, T=raw-128 degC). B3: MaxTempId. B4: MinTempId. |
| 0x383 | BMSBattStatus | B0-B1: SoC (BE uint16 / 10 = %). Also drives HVBattCharging, ChrgPortOpen, ChargeCableConnected (bit positions not yet documented). |
| 0x390 | BMS_HVBattTemp1 | B0: FrontInletAirTemp. B1: RearInletAirTemp. B2: ReturnAirTempPsg. B3: ReturnAirTempDrv. B4: AllowedCellTempMax. B5: AllowedCellTempMin. B6: AllowedCellTempDiff. B7: AllowedHumidity. All uint8, T=raw-128 degC except B6-B7. |
| 0x391 | HVACAirState | B0: UnderHoodHumidity (x2 %). B1: UnderHoodTemp (raw-128 degC). B2: OpAirHumidity (x2 %). B3: OPAirTemp (raw-128 degC). B4: ReturnAirTemp (raw-128 degC). B5: EvapAirOffTemp (raw-128 degC). B6-B7: inactive. |
| 0x418 | DLCM_Globals | B0: PRND (ASCII; P/R/N/D). B4: gear status. |
| 0x439 | AC_Compressor_Status | B0: COMPRESSOR_STATUS (0=Standby, 1=Running, 2=CASS Complete, 3=Off). B1: speed (x60 rpm). B2: power (x0.1 kW). |
| 0x48A | DCDCStatus2 | B0[7]: HighVLowFault. B2: 14VTempThermister (int8, -40 degC). B4: CalcdPwrLossThroughU2C (x2). B5: HeatplateTempThermister (int8, -40 degC). |
| 0x55C | TCM Heartbeat | ParkLock -> "StatusOff", DriveSensor -> false when suppressed. |
| 0x277/279/27D | CMM temps/out/in | BE uint16 / 32. CaseTemp/PFCTemp/HV1Temp/HV2Temp (0x277). HVOut/LVOut V+A (0x279). ACIn V/A/W (0x27D). Note: Phase 4 confirms only CaseTemp drops for 0x277; PFCTemp/HV1/HV2 may be CMM exclusive display slots. |
| 0x27A/27B/27C | CMS temps/in/out | BE uint16 / 32. All four temps, AC in V/A/W, HV+LV out V/A confirmed (Phase 4). |
| 0x61A | CMSHVCmd | CMS HV Cmd Voltage, Current, AC Max Current Avail, HV Cmd Enabled -- all drop (Phase 4). |

### 5b. Partially Decoded -- Further Sweep Needed

| ID | Name | What is known | What remains |
|----|------|---------------|--------------|
| 0x050 | BMSChargerCmd | B0-B1: HVCurrentCmd (BE uint16 x0.1 A, R2=0.992; baseline 0x00DC=22A). B2-B3: MaxVoltage (BE uint16 x0.1 V, R2=0.605; baseline 0x0FF7=408.7V). Median frame: `00 dc 0f f7 00 01 3e 01`. | B4-B5: non-baseline values collapse Main Current to ~6A -- likely frame-validation or rolling counter. B6-B7: unknown. Injection testing needed (see Section 6). |
| 0x270 | BMS_FaultStatus | B0: fault byte (0x00=no fault, 0x12=fault code 18; bit 1=0x02 and bit 4=0x10 set for fault 18). Fires 1 frame before 0x271. Drop-0x270 causes CODACAN 'BMS Fault Severity' to drop. B6, B7 active during faults. | Sub-field decode of B0 (fault code vs severity split) not yet swept. B6-B7 unknown. |
| 0x2C1 | BMSDrivingRange | B0: StatusByte (flips readings at raw=0x70). B1=DrivingRange_Exp, B3=DrivingRange_Max, B5=DrivingRange_Min (R2 ~0.96-0.97). Scale provisional (~1.1 x raw - 19). Values: 33/66/122 at ~68% SoC; 84/168/21 at ~93% SoC. Units: likely mi. | Scale/offset not precisely confirmed. B2, B4, B6-B7 not swept. |
| 0x330 | Long_Accel | Drops when suppressed (borderline vs noise). VICD scale: signed byte x0.08 m/s2. | Not confirmed as analog. Needs timeseries extraction from a drive event with hard braking. |
| 0x383 | BMSBattStatus | SoC (B0-B1, BE uint16 /10) confirmed. Also drives HVBattCharging, ChrgPortOpen, ChargeCableConnected. | Exact bit positions of the boolean flags not documented. |
| 0x410 | AC_Compressor_Command | B2: compressor_on_off, CASS_on_off, warmup_cycle_cntr_incr. B6: target_compressor_speed (x60 rpm/bit). B7: max_pwr_consumption (x0.1 kW/bit). B0: 3 booleans observed during sweep (HVAC FaultRed, FaultYellow, KeepWakeNetworkHVAC). | B0 bit positions unresolved. Booleans may be ECU-response artefacts from the sweep setup rather than direct B0 bit assignments. |
| 0x241 | MCM_Thermal | Role confirmed (drop-ID). DLC=8 confirmed. Carries Rotor, Stator, IGBT temps -- signed bytes, probable offset -40 degC (raw 0x3C-0x48 -> 20-32 degC plausible). B4=0x00 likely not a temp (sentinel or non-temp field). DLCM_glb.xml cluster order IGBT/Rotor/Stator is a hint for byte order but not definitive. | Per-byte assignment to Rotor/Stator/IGBT unconfirmed. Sweep bytes 0-7 in driving log (DLCM tab), or disassemble DLCM_Recvd.vi VICD for byte extractor offsets. See Section 6. |
| 0x491 / 0x273 | IPK frames | Both drive: Primary ODO (km), Interior Illum, Side Light Active, Low Beam Active. 0x491 also triggers Overview IPK indicator; 0x273 does not. 0x491 B3 carries headlight mode. | ODO byte position and encoding (likely BE uint24 or uint32). Lighting bit positions. |

### 5c. Open -- No Decode Yet

| ID | Known | Notes |
|----|-------|-------|
| 0x215 | 16-bit word, scale 1/128 (VICD). Phase 4: no unique drops -- inconclusive. | ~~Candidate: TCM.ParkLock~~ — **invalidated**: TCM park signals are fully accounted for by 0x308 (ParkPinState + InputShaftSpeed) and 0x55C (ParkLockState), both confirmed BorgWarner TCM messages. The TCM.ParkLock hypothesis likely arose from a VICD decompile offset error misidentifying 0x308 as 0x215. True identity unknown. |
| 0x370 | 6 bytes (indices 0,1,2,3,4,7) + 0x80 mask on one signal. Scale 0.1. | Death Counter batch -- 6 ECU heartbeat watchdogs. Signal identities unknown. |
| 0x378 B3-B7 | B0-B2 decoded; B3-B7 not swept. | Run coarse sweep bytes 3-7 in driving log. |
| 0x275 B7 | Baseline 0xDD=221. Constant across all known conditions. | Sweep or inject to see if any CODACAN field responds. |
| 0x276 B2 | HVACHVDisableStatus -- 3 enum values observed. | Sub-byte bit layout provisional -- which bits encode which state. |
| 0x620 | Sparse decode; cluster unknown. Triggers BMS indicator. | Full 8-byte coarse scan needed. |
| 0x72A | Simple byte copy; cluster unknown. Triggers BMS indicator. | Full 8-byte coarse scan needed. |

---

## 6. Open Items -- Prioritized

### Priority 1: Close Out Partial Signals (Phase 5)

**1. 0x410 B0 -- HVAC booleans**
Step=1 sweep of B0 using `codacharging.log`; watch HVAC tab for FaultRed/FaultYellow/
KeepWakeNetworkHVAC transitions. Note: if these are ECU-response artefacts from the sweep
they will not track B0 linearly -- use inject mode with specific values to confirm.

**2. 0x270 B0 -- fault code vs severity split**
Step=1 sweep in defroster2 log, time slice `--start-time 130 --end-time 300`; watch BMS 2 tab
(Fault Severity). Also inject individual bit patterns to isolate bit 1 vs bit 4 contributions:
`00 02 ...` (bit 1 only), `00 10 ...` (bit 4 only), `00 12 ...` (both = fault code 18).

**3. 0x2C1 -- driving range scale**
Fine sweep B1, B3, B5 (step=1) in charging log. Consider extracting timeseries from
`chargepointcharge.log` (full 0-100% charge) and fitting directly against SoC for better
leverage on the linear fit. Confirm units (mi vs km).

**4. 0x050 B4-B7 -- validation/counter characterization**
Hold B0-B3 at baseline (`00 dc 0f f7`), inject different B4-B5 values while watching
Charging tab Main Current. If Main Current stays at ~131A for all B4-B5 values, they are
not the validation bytes. Try the baseline B4-B5 value (`00 01`) vs arbitrary values to
confirm whether the charger rejects non-matching frames.

**5. 0x491/0x273 -- IPK ODO and lighting byte positions**
Coarse scan all 8 bytes in driving log. ODO will appear as a multi-byte group with a large
display step per raw increment. Lighting flags will be in a single byte with discrete 0/1
transitions. Fine-sweep the ODO bytes once located.

**6. 0x241 -- MCM_Thermal per-byte assignment**
Coarse sweep all 8 bytes in driving log; watch DLCM tab for Rotor/Stator/IGBT temp fields.
Signal is constant at rest (20-32 degC), so sweep will distinguish which bytes each field
tracks. DLCM_glb.xml cluster order (IGBT/Rotor/Stator) is a hypothesis for byte order --
confirm or refute with sweep. Confirm offset (-40 degC assumed). Identify role of B4 (0x00
in all captures -- likely sentinel or non-temp field). Command:
```
py -3.11-32 tools/cowork_replay.py sweep-byte "projects/coda/logs/codadriveslowturnonwithdefroster2.log" \
    --start-time 55 --end-time 695 --target 0x241 --byte 0 --dwell 2 --step 16 --no-wait --brands pcan
```
Repeat for bytes 1-7.

**7. 0x330 -- confirm analog vs discrete**
Extract timeseries from `frombonnydoon.log` bytes B0-B7 across a hard braking event.
Analog: signed byte x0.08 m/s2 shows a smooth ramp. Discrete: only 2-4 values.

### Priority 2: Open ID Sweeps

**8. 0x378 B3-B7** -- coarse sweep bytes 3-7 in driving log; watch BMS tab.

**9. 0x275 B7** -- inject different values while watching BMS tab for any field response.

**10. 0x620 and 0x72A** -- full 8-byte coarse scan in charging log; watch BMS tab.

**11. 0x215** -- TCM.ParkLock hypothesis invalidated (see Section 5c). True identity unknown; no actionable next step.

### Priority 3: Signal Sources Still Unknown

**12. IPK gauge feeds** -- SoC%, speed display on the physical instrument cluster. Likely
0x383/0x275 rebroadcast or a dedicated IPK frame. Test: inject 0x383 with a specific SoC
value; observe whether the IPK gauge moves in CODACAN's IPK tab.

**13. 0x383 boolean flag bits** -- HVBattCharging, ChrgPortOpen, ChargeCableConnected.
Step=1 sweep of B0-B1 in charging log to find which bits flip at charge-start/stop events.

**14. RCU / TPMS keepalive** -- 0x600 carries pressure data but does not trigger the TPMS
indicator. Capture task: trip the immobilizer to force RCU to broadcast its keepalive.

---

## 7. Next Steps Plan

### Phase 5 Remaining Sweeps

**Batch 1 -- short runs, each <=10 min:**

```
# 0x410 B0 -- HVAC booleans (watch HVAC tab)
py -3.11-32 tools/cowork_replay.py sweep-byte "projects/coda/logs/codacharging.log" \
    --target 0x410 --byte 0 --dwell 1 --step 1 --no-wait --brands pcan

# 0x270 B0 -- fault sub-fields (watch BMS 2 tab)
py -3.11-32 tools/cowork_replay.py sweep-byte "projects/coda/logs/codadriveslowturnonwithdefroster2.log" \
    --start-time 130 --end-time 300 --target 0x270 --byte 0 --dwell 1 --step 1 --no-wait --brands pcan

# 0x491 coarse scan -- IPK ODO/lighting (watch IPK tab; repeat bytes 1-7)
py -3.11-32 tools/cowork_replay.py sweep-byte "projects/coda/logs/codadriveslowturnonwithdefroster2.log" \
    --start-time 55 --end-time 695 --target 0x491 --byte 0 --dwell 2 --step 16 --no-wait --brands pcan
```

**Batch 2 -- medium runs, each <=20 min:**

```
# 0x2C1 fine sweep -- DrivingRange scale (watch BMS tab; repeat bytes 3, 5)
py -3.11-32 tools/cowork_replay.py sweep-byte "projects/coda/logs/codacharging.log" \
    --target 0x2C1 --byte 1 --dwell 1 --step 1 --no-wait --brands pcan

# 0x620 coarse (watch BMS tab; repeat bytes 1-7; then same for 0x72A)
py -3.11-32 tools/cowork_replay.py sweep-byte "projects/coda/logs/codacharging.log" \
    --target 0x620 --byte 0 --dwell 2 --step 16 --no-wait --brands pcan
```

**Batch 3 -- injection testing:**

```
# 0x050 B4-B5 -- does Main Current collapse? (watch Charging tab)
py -3.11-32 tools/cowork_replay.py inject --id 0x050 --data "00 dc 0f f7 00 00 3e 01" --brands pcan
# compare: baseline "00 dc 0f f7 00 01 3e 01", try "00 dc 0f f7 ff ff 3e 01"
py -3.11-32 tools/codacan_capture.py snapshot --tabs Charging --output verify_050.json
```

### Phase 6 -- Validation

Once Phase 5 sweeps are complete:
1. Run scale/offset derivation on `sweep_results.json`
2. Compare against existing DBC entries; flag discrepancies
3. Verify each discrepancy with inject mode
4. Write `notes/artifacts/cowork-results/validation_report.md`

### Phase 7 -- DBC Update

Apply confirmed encodings to `CODA-B-CAN.dbc` and `CODA-D-CAN.dbc`. Verify each signal
with inject before committing. Validate coverage after update:

```
py -3.11-32 tools/dbc_validate.py "projects/coda/CODA-B-CAN.dbc" projects/coda/logs/codacharging.log
py -3.11-32 tools/dbc_validate.py "projects/coda/CODA-D-CAN.dbc" projects/coda/logs/codadriveslowturnonwithdefroster2.log
```

---

## 8. LabVIEW Decompile Reference

### What the Decompile Gave Us

The `CODACAN/` folder is a decompiled LabVIEW 10.0 application. Two phases were completed:

**Phase 1 (XML extraction) -- Done:** `tools/labview_xml_extract.py` parsed signal names and
data types from the `.xml` files into `CODACAN/labview-signals.json` (49 clusters, 464 signals).

**Phase 2 (VICD disassembly) -- Partially done:** `tools/vicd_disasm.py` (capstone-based)
disassembled the compiled x86 `_VICD_code.bin` files to extract CAN IDs, byte indices, and
scale factors. DCDC_Recvd fully completed and validated. DLCM_Recvd, misc_Recvd, and
BMS_Recvd partially completed -- CAN ID dispatch trees mapped; byte-level signal extraction
incomplete (superseded by sweep-based validation for most signals).

### Cluster -> CAN ID Mapping

| Cluster / DBC Name | CAN ID | Bus | Status |
|--------------------|--------|-----|--------|
| DCDCStatus1 | 0x1D5 | B | Confirmed, hardware manual |
| BMS_DCDCEnableSet | 0x1D7 | B | Confirmed, hardware manual |
| ChrgrSysFaultsTemp | 0x274 | B | Charger fault/temp |
| CMMTempStatus | 0x277 | B | Confirmed, ÷32 |
| CMMOutputValues | 0x279 | B | Confirmed, ÷32 |
| CMSTempStatus | 0x27A | B | Confirmed, ÷32 |
| CMSInputValues | 0x27B | B | Confirmed, ÷32 |
| CMSOutputValues | 0x27C | B | Confirmed, ÷32 |
| CMMInputValues | 0x27D | B | Confirmed, ÷32 |
| DCDCStatus2 | 0x48A | B | Confirmed, hardware manual |
| ChrgrSysLimits | 0x615 | B | Charger limits |
| ChrgrSysCtrlEcho | 0x616 | B | Charger ctrl echo |
| ChrgrSysSts | 0x617 | B | Charger system status |
| CMSHVCmd | 0x61A | B | Confirmed Phase 4 |
| BMSChargerCmd | 0x050 | B | Partially confirmed |
| BMS_FaultStatus | 0x270 | B | Confirmed |
| GWM_VehFaults | 0x271 | B | Confirmed |
| BMSDriveLimits | 0x275 | B | Confirmed Phase 5 |
| HVACStatus | 0x276 | B | Confirmed Phase 5. **B CAN native** (2026-08-23) -- transmits with D CAN asleep; the D CAN copy is a GWM rebroadcast. |
| BMSDrivingRange | 0x2C1 | B | Partially confirmed |
| BattPowermode | 0x378 | B | Confirmed Phase 5 |
| BMSVminVmax | 0x381 | B | Confirmed |
| BMSThermal | 0x382 | B | Confirmed Phase 5 |
| BMSBattStatus | 0x383 | B | Confirmed |
| BMS_HVBattTemp1 | 0x390 | B | Confirmed Phase 5 |
| HVACAirState | 0x391 | B | Confirmed Phase 5 |
| ESC_BS_208 | 0x208 | D | Confirmed, log |
| MCM_Telemetry | 0x1C0 | D | Confirmed Phase 5 |
| EPS_SAM1 (steering) | 0x080 | D | Confirmed |
| ThrottlePedalPos | 0x210 | D | Confirmed |
| DLCM_TorqueRequest | 0x212 | D | Confirmed |
| MotorThermal | 0x241 | D | Confirmed |
| DriveKeepalive | 0x278 | D | Confirmed |
| DLCM_Status | 0x315 | D | Confirmed |
| DLCM_Globals (PRND) | 0x418 | D | Confirmed |
| TCM_Heartbeat | 0x55C | D | Confirmed |
| Long_Accel | 0x330 | D | Partial (VICD: signed byte x0.08 m/s2) |
| Death Counter batch | 0x370 | D | Open (6 bytes, 0x1 scale) |
| TPMS pressure | 0x600 | D | VICD: 1.37 kPa/count; keepalive ID unknown |

### VICD Dispatch Summary

**DCDC_Recvd:** Scale factors 0.1 (HVInputCurrent), 0.078431 (14VMonitor), x2
(14VCurrentMonitor).

> **Correction 2026-08-24.** This entry previously read "Fully disassembled ... confirmed
> against hardware manual". Neither half is reproducible as written:
> `DCDC_Recvd_VICD_code.bin` contains **no** float constants, bit masks or shifts across
> all 10,864 bytes -- it is an init stub, not the decoder -- and the hardware manual was
> not in the repo at the time. The 0.1 and 0.078431 constants are real but come from
> `DCDC_Recvd.xml` (the VI resource), which is silent on an integer x2.
>
> The scales are nonetheless **correct**. The primary source is now in the repo --
> Delphi `U2C Manual Rev03_2-15-2011.pdf` (`notes/dcdc/`) -- and it specifies all three
> verbatim, plus 0x48A and 0x1D7. Verified by text extraction and by reading the
> rendered pages, and confirmed independently by an energy balance using the U2C's own
> reported power loss. See `notes/dcdc/README.md`.

**DLCM_Recvd:** 6 IDs dispatched: 0x1C0, 0x212, 0x241, 0x278, 0x315, 0x418.
0x208 (ESC) is NOT in DLCM_Recvd -- decoded by a separate unidentified VI.

**misc_Recvd:** 7 IDs dispatched: 0x210, 0x215, 0x271, 0x330, 0x370, 0x55C, 0x600.

**BMS_Recvd:** 12 IDs dispatched: 0x050, 0x1D7, 0x270, 0x275, 0x2C1, 0x378, 0x381, 0x382,
0x383, 0x390, 0x620, 0x72A. IDs 0x271-0x274 are explicitly INVALID in BMS_Recvd's dispatch.

**Charger IDs (0x274, 0x277, 0x279, 0x27A-0x27D, 0x615-0x617)** are NOT in any VICD binary.
Decoded by interpreted LabVIEW G VIs -- no x86 code to disassemble. Encodings confirmed from
log analysis (÷32 BE uint16 for all CMM/CMS signals).

### Charger VI Organization

| VI file | Type | Decodes |
|---------|------|---------|
| CMM_Recvd.vi | Interpreted | 0x274, 0x277, 0x279, 0x615-0x617 |
| CMS_Recvd.vi | Interpreted | 0x27A, 0x27B, 0x27C (CMS slave) |
| ACCM_Recvd.vi | Interpreted | 0x410 (command), 0x439 (status) |
| EPS_Recvd.vi | Interpreted | 0x080 |
| IPK_Recvd.vi | Interpreted | 0x491, 0x273 |

CMM_glb.xml is the readable signal definition source for CMM/CMS signals.
CMS_glb.vi was never exploded to XML -- CMS signals inferred as CMM mirror (same Lear OBC hardware).

### VICD Hypotheses That Were Disproved

These appeared in early VICD analysis and were later corrected by log/sweep validation.

| Early hypothesis | Correction |
|------------------|------------|
| 0x212 = EPS_SAM_1 (steering angle, 0.25 deg/count) | 0x212 = DLCM Torque Request. Steering = 0x080. |
| 0x210 = Vehicle_Mode containing VBatt (x0.4 V/count) | 0x210 B2 = ThrottlePedalPos (x0.4 %/count). |
| 0x271 = Death Counter partial (integer byte counters) | 0x271 = GWM heartbeat + VehFaults source. |
| 0x55C = VehFaults (3 bytes: lamp/severity/fault word) | 0x55C = TCM heartbeat. |
| 0x381 = BMSDriveLimits candidate (sentinel 1000.0 A) | 0x381 = BMSVminVmax (cell voltage min/max/avg). BMSDriveLimits = 0x275. |
| 0x382 B0 = charge stage counter (steps 0x8B->0x8E) | B0 = Cell_T_avg. Values 11-14 degC as pack warmed during charging. |
| 0x275 B4 = HV Active flag (bool) | B4-B5 = PackVoltage (BE uint16, 1 V/bit). LFP 104S pack always keeps the uint16 MSB set. |
| BattSentDischargeLimit / ChargeLimit scale = 1 | Scale = 2 (uint8 x2 = A). |
