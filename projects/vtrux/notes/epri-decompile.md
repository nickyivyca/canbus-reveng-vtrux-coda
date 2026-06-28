# EPRI Logger App -- Decompile Findings

> Background and hardware context: `original-datalogging-investigation.md`
> CAN interrogation tools and DTC analysis: `dtc-can-interrogation.md`

---

## Part 3 -- EPRI Logger iPhone Analysis (COMPLETE 2026-03-26)

### Summary

Successfully extracted and analyzed the EPRI Logger app bundle from the iPhone. No binary
decryption was needed -- all signal configuration is in plaintext/plist files in the bundle.
App binary is NOT encrypted (enterprise distribution, as anticipated).

### Jailbreak path actually used

Device is iPhone 4S (not 5s -- see correction above). Jailbroken with **Carbon** WebKit
exploit (http://carbon.sep.lol, served via GitHub Pages). Phone's DNS was hijacked by ISP;
fixed by setting manual DNS 1.1.1.1 on the Wi-Fi connection. Carbon installed Cydia.
OpenSSH installed via Cydia; accessed over Wi-Fi (10.0.0.134) using legacy key algorithms
(`-o HostKeyAlgorithms=ssh-rsa -o PubkeyAcceptedKeyTypes=ssh-rsa`), password `alpine`.

### App identity

- **Bundle ID:** `com.epri.canbuslogger2`
- **App name:** CANbusLogger2 (binary: `CANbusLogger2.app/CANbusLogger2`)
- **Version:** 2.2.1, build 912 (git: 4a394d8)
- **Distribution:** Enterprise (not App Store) -- binary is NOT FairPlay encrypted
- **VIN this phone was configured for:** `3GCUKPEH2EG488714` (the Vtrux)
- **Device name:** "iPhone for VIN 3GCUKPEH2EG488714"
- **EPRI server:** `https://data.electrans.epri.com/upload/log/vehicle/{VIN}/{timestamp}`
- **Last successful data upload from this device:** 2015-11-24 14:50:45 UTC-7

### Why it crashes

App requires an "App Configuration Dictionary" fetched from the EPRI server at launch
(RunLog_2026-03-27.log line: "WARNING: No app config dictionary found!"). Without it, the
app initializes the Via vehicle type and both CAN buses, then crashes when it finds 0 GoPoint
modules connected and cannot proceed. The crash is post-`main()` (bus classes fully init'd).
The app binary is fully mapped and dumpable if needed, but not required -- all signal config
is in the bundle as plists.

### EPRI signal map -- PT bus (Via_CANid_List.plist)

Format: `CANID.byteindex` -> Via signal name. Intervals in seconds (0 = not sampled in that mode).

| Key | Description | Parked | Operating | Driving | Charging |
|-----|-------------|--------|-----------|---------|----------|
| 0x0054.2 | MCU_Cmd2_Response: GENE_RotSpd | 1 | 1 | 1 | 0 |
| 0x0410.11 | BCM_Status: bcm_gfd (ground fault detection; 1000.0=normal, 0.0=isolation fault) | 1 | 5 | 1 | 5 |
| 0x0410.12 | BCM_Status: bcm_ibat (battery current, signed: neg=discharge, pos=charge) | 1 | 5 | 1 | 5 |
| 0x0410.13 | BCM_Status: SOC | 1 | 5 | 1 | 5 |
| 0x0410.14 | BCM_Status: bcm_vbat (battery voltage) | 1 | 5 | 1 | 5 |
| 0x0420.3 | BCM_Limits: bcm_chg_max (max charge current) | 1 | 5 | 1 | 5 |
| 0x0420.4 | BCM_Limits: bcm_dis_max (max discharge current) | 1 | 5 | 1 | 5 |
| 0x0430.5 | BCM_Data1: bcm_cell_tmax | 1 | 5 | 1 | 5 |
| 0x0430.6 | BCM_Data1: bcm_cell_tmin | 1 | 5 | 1 | 5 |
| 0x0430.7 | BCM_Data1: bcm_cell_vmax | 1 | 5 | 1 | 5 |
| 0x0430.8 | BCM_Data1: bcm_cell_vmin | 1 | 1 | 1 | 5 |
| 0x0430.9 | BCM_Data1: bcm_lvbat (12V battery voltage) | 1 | 5 | 1 | 5 |
| 0x0440.4 | BCM_Data2: bcm_balancing_cnt | 1 | 5 | 1 | 5 |
| 0x0440.5 | BCM_Data2: bcm_fgd | 1 | 5 | 1 | 5 |
| 0x0440.6 | BCM_Data2: bcm_vbus_neg | 1 | 5 | 1 | 5 |
| 0x0440.7 | BCM_Data2: bcm_vbus_pos | 1 | 5 | 1 | 5 |
| 0x0471 | MCU_Info2: GENE_Mot_Trq (generator motor torque) | 1 | 1 | 1 | 0 |
| 0x0479.1 | MCU_Thermal1: GENE_DrvCoolFlowReq_pct | 5 | 5 | 5 | 0 |
| 0x0479.2 | MCU_Thermal1: GENE_MotCoolFlowReq_pct | 5 | 5 | 5 | 0 |
| 0x0479.3 | MCU_Thermal1: GENE_ThermInd_pct | 5 | 5 | 5 | 0 |
| 0x0482.1 | MCU_Info1: GENE_HighPwr_Curr | 1 | 1 | 1 | 0 |
| 0x0482.2 | MCU_Info1: GENE_HighPwr_Volt | 1 | 1 | 1 | 0 |
| 0x0592.4 | HCU_Sensor: Brake pedal position | 1 | 0 | 1 | 0 |
| 0x0598.1 | HCU_VIRTSENS_7_PwrStatAvg: DBL_ESSPwrAvg | 1 | 5 | 1 | 5 |
| 0x0598.2 | HCU_VIRTSENS_7_PwrStatAvg: DBL_TracPwrAvg | 1 | 1 | 1 | 0 |
| 0x0599.1 | HCU_VIRTSENS_5_Pressures: TracOilPress | 1 | 0 | 1 | 0 |
| 0x0599.2 | HCU_VIRTSENS_5_Pressures: GeneOilPress | 1 | 1 | 1 | 0 |
| 0x0625.2 | Veh_Odo - Odometer | 10 | 10 | 1 | 10 |
| 0x18FFD5C0.1 | INVCH_Bdc_Temperature_Int | 0 | 5 | 0 | 5 |
| 0x18FFD5C0.2 | INVCH_Bdc_TempPercent | 0 | 5 | 0 | 5 |
| 0x18FFD6B3.1 | DCDC_Feedback: DCDC_HV_Volt | 1 | 1 | 1 | 1 |
| 0x18FFD6B3.2 | DCDC_Feedback: DCDC_HW_Temp | 1 | 1 | 1 | 1 |
| 0x18FFD6B3.3 | DCDC_Feedback: DCDC_LV_Curr | 1 | 1 | 1 | 1 |
| 0x18FFD6B3.4 | DCDC_Feedback: DCDC_LV_Curr (duplicate?) | 1 | 1 | 1 | 1 |
| 0x18FFD6C0.1 | INVCH_Inv_Output: INVCH_Inv_Iout1_RMS | 1 | 1 | 0 | 0 |
| 0x18FFD6C0.2 | INVCH_Inv_Output: INVCH_Inv_Iout2_RMS | 1 | 1 | 0 | 0 |
| 0x18FFD6C0.3 | INVCH_Inv_Output: INVCH_Inv_Vout1_RMS | 1 | 1 | 0 | 0 |
| 0x18FFD6C0.4 | INVCH_Inv_Output: INVCH_Inv_Vout2_RMS | 1 | 1 | 0 | 0 |
| 0x18FFD7C0.1 | INVCH_Bdc_battery_Chg_input: INVCH_Bdc_Ibat | 0 | 0 | 0 | 5 |
| 0x18FFD7C0.2 | INVCH_Bdc_battery_Chg_input: INVCH_Bdc_Vbat | 0 | 0 | 0 | 5 |
| 0x18FFD7C0.3 | INVCH_Bdc_battery_Chg_input: INVCH_Chg_Iin_RMS | 0 | 0 | 0 | 5 |
| 0x18FFD7C0.4 | INVCH_Bdc_battery_Chg_input: INVCH_Chg_Vin_RMS | 0 | 0 | 0 | 5 |
| 0x18FFD8C0 | INVCH_Bdc_J1772 | 0 | 0 | 0 | 5 |
| 0x0868A047.2 | EAC_STATUS1: EAC_Elec_Curr (A/C compressor current) | 1 | 1 | 1 | 1 |
| 0x0868A047.3 | EAC_STATUS1: EAC_Elec_Pwr (A/C compressor power) | 1 | 1 | 1 | 1 |
| 0x0870A047 | EAC_STATUS2: EAC_CompHVInput (A/C HV input) | 1 | 1 | 1 | 1 |
| 0x06000001.2 | EPT_Stat_HMI_1: Accel_Ped_Pos | 1 | 1 | 1 | 0 |
| 0x06000001.3 | EPT_Stat_HMI_1: Veh_Speed | 1 | 0 | 1 | 0 |

Note: IDs >= 0x800 that don't match J1939 pattern (0x18xxxxxx) may be GoPoint internal
message IDs, not raw CAN IDs. 0x06000001, 0x0868A047, 0x0870A047 are likely GoPoint
message IDs that encapsulate EPT (Extended Powertrain) and EAC (Electric A/C) signals.

### EPRI signal map -- OBD bus (Via_OBD_List.plist)

| Key | Description | Parked | Operating | Driving | Charging |
|-----|-------------|--------|-----------|---------|----------|
| 0x0044.2 | MCU_Cmd2_Response: TRAC_RotSpd (traction motor RPM) | 1 | 1 | 1 | 0 |
| 0x00C9 | PPEI_Engine_General_Status_1: Engine speed | 1 | 1 | 1 | 0 |
| 0x0120 | BCM_Vehicle_Odometer_HS | 10 | 1 | 1 | 1 |
| 0x01C3.1 | PPEI_Engine_Torque_Status_2 | 1 | 1 | 1 | 0 |
| 0x01C3.2 | PPEI_Engine_Torque_Status_2 | 1 | 1 | 1 | 0 |
| 0x02C3 | PPEI_Engine_Torque_Status_3 | 1 | 1 | 1 | 0 |
| 0x03D1 | PPEI_Engine_General_Status_2 (TPS etc.) | 1 | 1 | 1 | 0 |
| 0x03E9.1 | PPEI_Vehicle_Speed_and_Distance: DistRollCntAvgDrvn_dist | 1 | 0 | 1 | 0 |
| 0x03E9.3 | PPEI_Vehicle_Speed_and_Distance: VehSpdAvgDrvn_linspd | 0 | 0 | 1 | 0 |
| 0x0451 | MCU_Info2 TRAC | 1 | 0 | 1 | 0 |
| 0x0459.1 | MCU_Thermal1 TRAC | 5 | 0 | 5 | 0 |
| 0x0459.2 | MCU_Thermal1 TRAC | 5 | 0 | 5 | 0 |
| 0x0459.3 | MCU_Thermal1 TRAC | 5 | 0 | 5 | 0 |
| 0x0462.1 | MCU_Info1 TRAC | 1 | 0 | 1 | 0 |
| 0x0462.2 | MCU_Info1 TRAC | 1 | 0 | 1 | 0 |
| 0x04C1.1 | PPEI_Engine_General_Status_4: Engine coolant temp | 1 | 1 | 1 | 1 |
| 0x04C1.2 | PPEI_Engine_General_Status_4: Engine air intake temp | 1 | 0 | 1 | 1 |
| 0x04C1.3 | PPEI_Engine_General_Status_4: Outside air temp | 1 | 1 | 1 | 30 |

### GENE vs TRAC MCU message pairing

Via uses parallel message structures for the two motor controllers with a systematic ID offset:

| TRAC (OBD bus) | GENE (PT bus) | Offset | Message type |
|-----------------|---------------|--------|-------------|
| 0x0044 | 0x0054 | +0x10 | MCU_Cmd2_Response (rotation speed) |
| 0x0451 | 0x0471 | +0x20 | MCU_Info2 (motor torque) |
| 0x0459 | 0x0479 | +0x20 | MCU_Thermal1 (coolant flow %) |
| 0x0462 | 0x0482 | +0x20 | MCU_Info1 (HV current, HV voltage) |

TRAC messages appear on the OBD bus; GENE messages appear on the PT bus. This implies
the traction motor controller (Motor 2) and generator controller (Motor 1) each have their
own native bus -- Motor 2 (traction) on the OBD bus, Motor 1 (generator) on the PT bus.

### Key new signals for follow-up investigation

- **0x0054 B0:B1: GENE_RotSpd** -- generator rotation speed (actual speed feedback, not the
  command/reference in 0x051 B3-B4). Need to decode scale (likely RPM direct or with offset).
- **0x0044 B0:B1: TRAC_RotSpd** -- traction motor rotation speed. **This ID is on the OBD bus
  and has NOT appeared in prior PT bus logs.** Confirms traction MCU is on OBD bus.
- **0x0410/0x0420/0x0430/0x0440** -- BCM messages with cell-level detail (min/max cell V and T,
  charge/discharge limits, balancing). These are on the PT bus and should be in our existing
  logs. Byte positions from the plist key suffix need to be verified against actual log frames
  (the `.N` suffix appears to be a signal index within the message, not a byte offset).
- **0x0598: DBL_ESSPwrAvg and DBL_TracPwrAvg** -- computed power averages. The "DBL" prefix
  suggests these may be double-precision floats or 16-bit scaled values.
- **0x0599: TracOilPress, GeneOilPress** -- oil pressures for both motor drives.
- **0x18FFD6C0** -- Bel inverter output voltages and currents (two phases: Vout1/Vout2,
  Iout1/Iout2). Present during driving (not just charging). Need to cross-reference with
  BelInverter.dbc -- these may already be decoded or may be new signals.

### Files extracted to artifacts/epri-app/

- `CANbusLogger2.app/` -- full app bundle (binary + all resource files)
- `app-data/RunLog_2015-11-24.log` -- last real operation log (Nov 2015), shows upload URLs
- `app-data/RunLog_2026-03-27.log` -- today's crash log, confirms crash reason
- `app-data/savedAppData.plist` -- VIN and last upload timestamp
- `app-data/crashes.plist` -- BugSense crash reporter state

Other vehicle data files in bundle (not yet analyzed):
- `J1939Data.txt`, `J1939_SPN_List.plist` -- J1939 SPN definitions
- `OBDData.txt`, `OBD_ID_List.plist` -- generic OBD-II IDs
- `LeafCARData.txt`, `LeafEVData.txt`, `Leaf_CARCAN_List.plist`, `Leaf_EVCAN_List.plist`
- `OdyneHCUData.txt`, `Odyne_CANid_List.plist`
- `VoltHVMData.txt`, `VoltOBDData.txt`, `Volt_HVM_CANid_List.plist`, `Volt_OBD_CANid_List.plist`
- `ZCG-Notes` -- developer notes from contractor who wrote the iOS app (ZCG = Zachary C. G.?)
- `TestLogFile.txt` -- March 2014 debug session logs from "GMSW Test iPhone 4"

---

## Part 5 -- Binary Analysis of CANbusLogger2 (2026-03-26)

### What was done

The CANbusLogger2 binary was analyzed without jailbreak, directly from the app bundle
(enterprise distribution, cryptid=0 confirmed -- no FairPlay decryption needed).

**Fat binary structure:**
- ARMv7 (32-bit) slice: 1,194,080 bytes at offset 0x4000
- ARM64 (64-bit) slice: 1,408,496 bytes at offset 0x128000

**Key correction:** The iPhone 4S (A5 chip, Cortex-A9) is **ARMv7 only** -- it does NOT
support ARM64. ARM64 (AArch64) was introduced in the Apple A7 chip (iPhone 5s, 2013). The
ARM64 slice in this binary is compiled for newer iPhones in the same fleet deployment. Both
slices contain identical decoding logic compiled for different architectures.

**For Ghidra analysis: use the ARMv7 slice** (`CANbusLogger2_ARM` in artifacts/) -- that
is what actually executed on this device. Both will yield the same signal decoding logic.

### Developer identity

Source file paths embedded in the binary reveal the development environment:

```
/Users/andersmelen/Documents/Repositories/epri-logger-app-2.0/CANbusLoggerXCode/CANbusLogger/
```

Developer: **Anders Melen**. GitHub search found no public repo (`andersmelen` does not
have a public profile). Source code is private. The app binary footer credits
**Green Mountain Software Corp., Burlington VT** as the developer and EPRI as owner.

### What static analysis found

**Plist files (Via_CANid_List.plist, Via_OBD_List.plist):** Signal names and sampling
intervals only. No byte positions, scales, or offsets -- those are compiled into the parsers.

**Binary format strings (extracted via strings search):** Reveal signal units, types, and
output format for every Via signal. Full table:

| Signal | Unit | Format | Source |
|--------|------|--------|--------|
| GENE_RotSpd | rpm | `%d` (integer) | `"GENE_RotSpd = %d rpm"` |
| TRAC_RotSpd | rpm | `%d` (integer) | `"TRAC_RotSpd = %d rpm"` |
| GENE_Mot_Trq | Nm | `%.3f` | `"GENE_Mot_Trq = %.3f Nm"` |
| TRAC_Mot_Trq | Nm | `%.3f` | `"TRAC_Mot_Trq = %.3f Nm"` |
| GENE_HighPwr_Curr | A | `%.2f` | `"GENE_HighPwr_Curr = %.2f A"` |
| GENE_HighPwr_Volt | V | `%.1f` | `"GENE_HighPwr_Volt = %.1f V"` |
| TRAC_HighPwr_Curr | A | `%.2f` | mirror of GENE |
| TRAC_HighPwr_Volt | V | `%.1f` | mirror of GENE |
| GENE_DrvCoolFlowReq_pct | % | `%.1f` | thermal message |
| GENE_MotCoolFlowReq_pct | % | `%.1f` | thermal message |
| GENE_ThermInd_pct | % | `%.1f` | thermal message |
| bcm_gfd | - | `%.2f` | ground fault detection (isolation monitor output); 1000.0=normal, 0.0=isolation fault (fires 150ms before EPO). Confirmed 2026-03-29. |
| bcm_ibat | A | `%.2f` | battery current; signed: neg=discharge, pos=charge; `raw * 0.025 - 1000` |
| bcm_soc | % | `%.2f` | state of charge |
| bcm_vbat | V | `%.2f` | battery voltage |
| bcm_chg_max | A | `%.2f` | max charge current limit |
| bcm_dis_max | A | `%.2f` | max discharge current limit |
| bcm_cell_tmax | degC | `%.2f` | hottest cell |
| bcm_cell_tmin | degC | `%.2f` | coolest cell |
| bcm_cell_vmax | V | `%.3f` | highest cell voltage (V, 3dp) |
| bcm_cell_vmin | V | `%.3f` | lowest cell voltage |
| bcm_lvbat | V | `%.2f` | 12V battery |
| bcm_balancing_cnt | - | `%d` (integer) | cell balancing count |
| bcm_fgd | % | `%.2f` | role unconfirmed (plist label only) |
| Veh_BrakePdl_Pos | % | `%.2f` | brake pedal position (from 0x0592) |
| DCDC_HV_Volt | V | `%.2f` | DCDC HV input |
| DCDC_HW_Temp | degC | `%.2f` | DCDC temperature |
| DCDC_LV_Curr | A | `%.2f` | DCDC LV output current |
| DCDC_LV_Volt | V | `%.2f` | DCDC LV output voltage |
| INVCH_Bdc_Temperature_Int | degC | `%.2f` | Bel charger internal temp |
| INVCH_Bdc_TempPercent | % | `%d` (integer) | Bel charger temp % |
| INVCH_Inv_Iout1/2_RMS | A | `%.2f` | inverter output current phases |
| INVCH_Inv_Vout1/2_RMS | V | `%.2f` | inverter output voltage phases |
| INVCH_Bdc_Ibat | A | `%.2f` | battery charge current |
| INVCH_Bdc_Vbat | V | `%.2f` | battery charge voltage |
| INVCH_Chg_Iin_RMS | A | `%.2f` | AC input current |
| INVCH_Chg_Vin_RMS | V | `%.2f` | AC input voltage |
| INVCH_Bdc_12Vbat | V | `%.1f` | 12V from Bel unit |
| EAC_Elec_Curr | A | `%.2f` | A/C compressor current |
| EAC_Elec_Pwr | W | `%d` (integer) | A/C compressor power |
| EAC_CompHVInput | VDC | `%d` (integer) | A/C HV input voltage |
| Engine_Speed (0x00C9) | rpm | `%.1f` | via GMLAN |
| Engine_Torque_Actual (0x01C3) | Nm | `%.1f` | via GMLAN |
| Throttle_Position (0x03D1) | % | `%.0f` | via GMLAN |
| VehSpdAvgDrvn (0x03E9) | km/h | `%.3f` | via GMLAN |

**BCM format strings also reveal additional boolean flags not individually listed in the
plist** (app logs them as `%@` = YES/NO): `bcm_alarm`, `bcm_chg_done`, `bcm_chgc_stat`,
`bcm_cool_req`, `bcm_cpwr_cmd`, `bcm_epo`, `bcm_hvil_mon`, `bcm_mainc_stat`, `bcm_on_plug`,
`bcm_ready` (all in 0x0410); `bcm_chga_ena`, `bcm_chga_mon`, `bcm_mod_ena`, `bcm_veh_mon`
(all in 0x0430); `bcm_balancing`, `bcm_fault_mon` (in 0x0440).

**TestLogFile.txt:** Useless -- repeated app startup sessions with no vehicle selected,
no signal data.

**ViaCANData.txt / ViaOBDData.txt:** Sample CAN frames in format `[2-byte CAN ID BE]
[data bytes]`. Extended IDs use bit 31 set (DBC convention). Contains some IDs not in the
plists (0x0053, 0x00C0, 0x00C1, 0x00C4, 0x016A, 0x0710, 0x0720 on PT bus;
0x18FFD4C0 on extended). These may be additional passively monitored messages.

### DBC files generated

Two new DBC files in `projects/vtrux/`:

| File | Bus | Messages | Contents |
|------|-----|----------|----------|
| `epri-pt-bus.dbc` | PT bus | 26 messages, 103 signals | GENE MCU, BCM, Bel charger/DCDC, ESS, odometer, A/C + 9 non-plist Ghidra IDs (see below) |
| `epri-obd-bus.dbc` | OBD bus | 11 messages, 19 signals | TRAC MCU, GMLAN engine/chassis |

Both validated with cantools (strict=False). SG_ entries are fully populated with byte-level
bit positions, scales, and offsets confirmed from Ghidra decompile. CM_ comments carry the
full EPRI signal inventory (plist signal names, indices, sampling intervals) plus decompile
evidence (DAT constant offsets, ARM instruction annotations).

Generator script: `notes/artifacts/generate_epri_dbcs.py`

**Non-plist IDs added manually (2026-03-29):** The generator script builds stubs only from
plist entries. Nine IDs present in `parseEPRIMessage` but absent from both plists were added
manually to `epri-pt-bus.dbc` via `notes/artifacts/add_missing_epri_ids.py`:

| ID | Name | Signals | Why missed |
|----|------|---------|-----------|
| 0x0053 | EPRI_OperatingMode_0053 | OperationMode (3-bit), OperationState (9-state) | Not in plist |
| 0x0308 | EPRI_ParkRequest_0308 | ParkRequest (3-entry enum) | Not in plist |
| 0x0400 | EPRI_HV_BCM_Control_0400 | 4 hsc_ boolean flags | Not in plist |
| 0x055C | EPRI_ParkLock_055C | parkLockState (7-state), parkSensor, driveSensor | Not in plist |
| 0x0580 | EPRI_TCM_CANError_0580 | tcm_CAN_ERR | Not in plist |
| 0x062F | EPRI_HCU_SwVersion_062F | MajorVersion, MinorVersion + 2 project enums | Not in plist |
| 0x063A | EPRI_VehicleConfig_063A | iVehCfg_chgr_md, iVehCfg_ess_md | Not in plist |
| 0x065B | EPRI_HCU_DTC_065B | DTC_Code (16-bit, 29-entry VAL_ table) | Not in plist |
| 0x18FFD4C0 | EPRI_INVCH_Bdc_Status_18FFD4C0 | 4-page mux: Signal_State (29), bBoost_St (21), Inverter_St (35), 10 AC fault flags | Not in plist |

Note on 0x062F: three cross-byte packed fields (HCU_SwIDMaturity_Enum, HCU_SwIDVehVariant_Enum,
HCU_SwIDCalVer_Cnt) cannot be expressed as standard DBC SG_ entries and are documented in
CM_ only. MajorVersion and MinorVersion are byte-aligned and have clean SG_ entries.

### Ghidra analysis -- COMPLETE 2026-03-26

**Goal:** Decompile `ViaCANbusParser` and `ViaOBDParser` methods to extract byte-level
signal decoding (bit positions, scale factors).

**Status:**
- Ghidra 12.0.4 installed at `C:\Users\nicholas.ivy\Programs\ghidra_12.0.4_PUBLIC`
- Java 25 (Eclipse Temurin) at `C:\Program Files\Eclipse Adoptium\jdk-25.0.2.10-hotspot`
- ARMv7 and ARM64 slices extracted to `notes/artifacts/CANbusLogger2_ARM` and `_ARM64`
- Ghidra project: `notes/artifacts/ghidra-project/EPRILogger`
  (ARMv7 slice imported 2026-03-26; loaded as ARM:LE:32:v8, same instruction set)
- Scripts: `notes/artifacts/DecompileViaParsers.java` (v2), `notes/artifacts/DiagnoseGhidra.java`
- Runner: `notes/artifacts/run-ghidra-armv7.ps1` (sets JAVA_HOME, invokes analyzeHeadless)
- Output: `notes/artifacts/ghidra-via-decompiled.txt` (263 KB, 12 functions)

**Why ARM64 failed / ARMv7 succeeded:**
- ARM64 run found only 2 property setters because the format string xref search looked for
  code references to `__cstring` addresses. ObjC code never references `__cstring` directly --
  it loads `__cfstring` struct objects, which are in the `__cfstring` section and POINT to
  the raw strings in `__cstring`. Fix: two-level lookup (find string in `__cstring` ->
  scan `__cfstring` for cfstring struct with matching chars pointer -> find code xrefs to
  the cfstring struct base address). Also added ObjC class metadata walk (Pass 3) to extract
  all methods of target classes directly from their `class_ro_t` method lists.
- ARMv7 result: 12 functions (Pass 1: 2, Pass 2: 3, Pass 3: 7).

**Architecture note:** iPhone 4S = Apple A5 = ARMv7 only. ARM64 slice is for newer
devices but contains identical logic. Either slice will yield the same decoding algorithms;
use ARMv7 for exact match to what ran on this device.

**VMA-to-file-offset mapping for CANbusLogger2_ARM:**
TEXT segment: vmaddr=0x4000, fileoff=0x0 -- so `file_offset = VMA - 0x4000`.

### Complete parseEPRIMessage ID inventory (2026-03-27)

Systematic enumeration of all `if (uVarN == 0x...)` / `if (uVarN != 0x...)` guards in
`ghidra-gopoint-decompiled.txt`. **All 35 guards accounted for. No undocumented handlers remain.**

Script: `artifacts/enumerate_all_ids.py`

#### VIA CAN bus IDs (uVar2 -- 20 unique)

| ID | Name / function | Notes |
|----|----------------|-------|
| 0x0053 | OperatingMode / OperationState | enum arrays |
| 0x0054 | GENE_RotSpd, GENE_EmergcyStp_flg | RPM + E-stop flag |
| 0x0308 | ParkRequest | enum (Park/Unpark) |
| 0x0400 | HV BCM Control (hsc_ signals) | boolean flags |
| 0x0410 | BCM_Status | enums + booleans |
| 0x0420 | BCM_Limits | booleans |
| 0x0430 | BCM_Data1 | OFF/LOW/HIGH + booleans |
| 0x0440 | BCM_Data2 | OFF/LOW/HIGH + booleans |
| 0x0471 | GENE_Mot_Trq | generator torque (%.3f Nm) |
| 0x0479 | MCU_Thermal1 | thermal signals (%.2f) |
| 0x0482 | GENE_HighPwr_Curr / GENE_HighPwr_Volt | current (%.2f A), voltage (%.1f V) |
| 0x055C | park lock / drive sensor | parkLockState enum + driveSensor/parkSensor ON/OFF |
| 0x0580 | TCM CAN error flag | YES/NO |
| 0x0592 | HCU_Sensor | ON/OFF flags |
| 0x0598 | HCU_VIRTSENS_7_PwrStatAvg | 3x power channels (floats) |
| 0x0599 | HCU_VIRTSENS_5_Pressures | generator + traction cooling oil pressure (%.2f kPa) |
| 0x0625 | Veh_Odo (odometer) | K2XX/600 variant + distance (%.1f km) |
| 0x062F | HCU software version | 7-field version struct |
| 0x063A | VehicleConfig (charger/ESS type) | POWERONE/DRS + A123/VALENCE |
| 0x065B | HCU DTC code dispatcher | 29-entry DTC lookup table |

#### GoPoint / extended CAN IDs (uVar59 -- 10 unique)

| ID | Name / function | Notes |
|----|----------------|-------|
| 0x06000001 | EPT_Stat_HMI_1 (gear position) | 6-entry enum: Park/UnPark/Neutral/Drive/Low/Invalid |
| 0x0868A047 | EAC_STATUS1 (A/C compressor) | compressor status (4) + fault (8) enums |
| 0x0870A047 | EAC_STATUS2 (A/C HV voltage) | voltage reading (%d VDC) |
| 0x18EFC000 | (no decoder) | ID tested as range guard; routes to UnknownCANID |
| 0x18FFD4C0 | INVCH_Bdc status/command | paged (B0=page): multi-page fault flags, enums, counters |
| 0x18FFD5C0 | INVCH_Bdc temperature | BDC temp (%.2f degC) + percent |
| 0x18FFD6B3 | DCDC converter readings | multiple voltage/current signals |
| 0x18FFD6C0 | INVCH_Inv AC output | Iout1/2 RMS (%.2f A), Vout1/2 RMS (%.2f V) |
| 0x18FFD7C0 | INVCH_Bdc battery / INVCH_Chg charger | Ibat, Vbat, Chg Iin/Vin RMS |
| 0x18FFD8C0 | INVCH_Bdc 12V battery voltage | 12Vbat (%.1f V) |

#### GoPoint protocol messages (uVar3 -- 5 unique, in handleGoPointMessage_)

These are GoPoint dongle protocol messages, not vehicle CAN IDs. Not logged to plist.

| ID | Function |
|----|---------|
| 0x0708 | Bus type report (sets GoPoint physical bus type) |
| 0x1200 | User filter response (1 of 2) |
| 0x1208 | User filter response (2 of 2) |
| 0x1210 | User flow control response (1 of 2) |
| 0x1218 | User flow control response (2 of 2) |

---

### Signal decodings extracted from ViaCANbusParser::parseEPRIMessage:

All byte-level accesses are via `*(ushort *)` or `*(short *)` on little-endian ARM, which
reads the CAN frame bytes in little-endian order (byte N = low byte, byte N+1 = high byte).
Via Motors stores these signals in LE byte order in their CAN frames.

The main parsing function (`parseEPRIMessage:` at 0x25d00) reads the 2-byte message ID as
`CONCAT11(pbVar15[0], pbVar15[1])` (big-endian), then dispatches by ID.

**Buffer layout / index offset note:** `pbVar15` points to the EPRI data buffer where bytes
0–1 are the CAN message ID and bytes 2–9 are the 8 CAN data bytes. Therefore:
`pbVar15[2]` = CAN B0, `pbVar15[3]` = CAN B1, ..., `pbVar15[9]` = CAN B7.
All signal descriptions below use CAN Bx notation (CAN frame byte index). The raw
`pbVar15[N]` expressions are preserved in parentheses for traceability to the decompiled code.

#### 0x0053 -- OperatingMode

Format string: `"Operation Mode: %@ Operation State: %@"` (CFString at 0xF5788)

**OperationMode** -- CAN B0 bits[6:4] (3-bit index, `(B0 >> 4) & 0x7`), 4-entry array:

| Index | String | VMA |
|-------|--------|-----|
| 0 | "NTRL" | 0xF56B8 |
| 1 | "Invalid (1)" | 0xF56C8 |
| 2 | "Invalid (2)" | 0xF56D8 |
| 3 | "Invalid (%d)" | 0xF56E8 |

Only index 0 is a real operating mode; indices 1-3 are error strings.

**OperationState** -- CAN B0 bits[3:0] (4-bit index, `B0 & 0xF`), valid 0-8, 9-entry array:

| Index | String | VMA |
|-------|--------|-----|
| 0 | "INIT" | 0xF56F8 |
| 1 | "STBY" | 0xF5708 |
| 2 | "ACTIVATION" | 0xF5718 |
| 3 | "DEACTIVATION" | 0xF5728 |
| 4 | "OPERATIONAL" | 0xF5738 |
| 5 | "FAILURE" | 0xF5748 |
| 6 | "SHTDWN" | 0xF5758 |
| 7 | "WAIT4COOLING" | 0xF5768 |
| 8 | "PWR_OFF_RDY" | 0xF5778 |

String values confirmed from Mach-O __cfstring section scan (read_cfstrings.py).

#### 0x0054 -- GENE_RotSpd, GENE_EmergcyStp_flg

- **GENE_RotSpd** = `(int16_t_LE)(CAN B0:B1) - 32767` rpm
  (zero at raw=32767; `sVar3 = *(short*)(pbVar15+2); value = sVar3 - 0x7FFF`)
- **GENE_EmergcyStp_flg** = CAN B4 bit 3 (`(pbVar15[6] & 8) != 0`), boolean

#### 0x0308 -- ParkRequest

- CAN B0 bits [6:5] (2 bits, `(B0 << 25) >> 30` = `(B0 >> 5) & 3`): ParkRequest index into 4-entry string array:

| Index | String |
|-------|--------|
| 0 | "OFF" |
| 1 | "Park" |
| 2 | "UnPark" |
| 3 | "Park Request: %@" (fallback/error, uses B0 value) |

(String values confirmed from binary cfstrings at VMAs 0xF57A8-0xF57D8, 2026-03-27)
Only B0 is read; no other bytes accessed.

#### 0x0400 -- HV BCM Control (hsc_ prefix signals, not the same as 0x0410 BCM_Status)

CAN B0 bit-field:
- bit 0: `hsc_bcm_enable`
- bit 1: `hsc_bcm_epo`
- bit 2: `hsc_bcm_mainc_close`
- bit 3: `hsc_bcm_leakage_ena`

#### 0x0410 -- BCM_Status (CONFIRMED byte layout)

Format string: `BCM_Status: bcm_alarm:%@ bcm_chg_done:%@ bcm_chgc_stat:%@ bcm_cool_req:%@
bcm_cpwr_cmd:%@ bcm_epo:%@ bcm_hvil_mon:%@ bcm_mainc_stat:%@ bcm_on_plug:%@ bcm_ready:%@
bcm_gfd:%.2f bcm_ibat:%.2f bcm_soc:%.2f%% bcm_vbat:%.2f`

Booleans (YES/NO) from bit fields (all in CAN B0 unless noted):
- `bcm_alarm`      -- from 5-entry array via CAN B1 bits [7:6] (2-bit index 0-3; index 4 = fallback "Invalid")

  | Index | String | VMA |
  |-------|--------|-----|
  | 0 | "NONE" | 0xF4FD8 |
  | 1 | "TYPE1" | 0xF57F8 |
  | 2 | "TYPE2" | 0xF5808 |
  | 3 | "TYPE3" | 0xF5818 |

  (String values confirmed from Mach-O cfstring scan)

- `bcm_chg_done`   -- CAN B6 bit 4 (`pbVar15[8] & 0x10`)
- `bcm_chgc_stat`  -- 4-entry array via CAN B0 bits [7:6] (2-bit index 0-3)
- `bcm_cool_req`   -- CAN B6 bit 5 (`pbVar15[8] & 0x20`)
- `bcm_cpwr_cmd`   -- CAN B1 bit 4 (`pbVar15[3] & 0x10`)
- `bcm_epo`        -- CAN B0 bit 1 (`pbVar15[2] & 2`)
- `bcm_hvil_mon`   -- CAN B0 bit 3 (`pbVar15[2] & 8`), reported as LOW/HIGH
  **Cross-validated**: matches experimental interlock test result (B0 bit3 = interlock loop status, 5 deliberate press/release cycles confirmed in vtruxinterlocktest2.log)
- `bcm_mainc_stat` -- 4-entry array via CAN B0 bits [5:4] (`(B0 << 0x1a) >> 0x1e`)
- `bcm_on_plug`    -- CAN B0 bit 2 (`pbVar15[2] & 4`)
- `bcm_ready`      -- CAN B0 bit 0 (`pbVar15[2] & 1`)

**bcm_chgc_stat and bcm_mainc_stat shared 4-entry array** (same array used for both signals,
different 2-bit index fields from B0):

| Index | String | VMA | Note |
|-------|--------|-----|------|
| 0 | "OPEN"   | 0xF5828 | confirmed from cfstring scan |
| 1 | "CLOSED" | 0xF5838 | confirmed from cfstring scan 2026-03-27 |
| 2 | "HIGH"   | 0xF5848 | confirmed from cfstring scan 2026-03-27 |
| 3 | "LOW"    | 0xF5858 | confirmed from cfstring scan 2026-03-27 |

Note: previous notes incorrectly listed entry [2] as "FAILURE" at 0xF5748; that VMA is in the
0x0044 OperationState array (index 5 = "FAILURE"), not this array.

Numeric signals (floats):
- **bcm_gfd** (ground fault detection): 12-bit = `CAN B2 | (CAN B1 & 0xF) << 8`
  → `value = uint12 * 0.25`; invalid if raw==0xFFE
  (SIMDImm(0xF,0x50) = 0.25, confirmed by ARM VFP immediate decoding 2026-03-27)
  Normal value: 1000.0 (raw=4000), stable across all drive and charge fault logs.
  **CONFIRMED ground fault detection (isolation monitor output). Fault value: 0.0
  (raw=0) — fires 150ms before EPO in isolation test (vtruxisolationtest.log); does
  not fire in charge fault EPO or any normal drive log. Confirmed 2026-03-29.**
  Note: signal names are EPRI plist labels. Byte positions (B1-B2 → bcm_gfd, B4-B5 →
  bcm_ibat) confirmed 2026-03-28 by tracing Ghidra format-string argument order and
  cross-validating against generator-on/off log (B4-B5 signal crosses 0 A at raw=40000
  when generator runs; B1-B2 stays constant).
- **bcm_soc** (state of charge): CAN B3, single byte
  → `value = CAN_B3 * 0.5` %; calls `setSOC:` on app delegate
  → invalid if CAN_B3 >= 0xFE
  (SIMDImm(0xF,0x60) = 0.5, confirmed 2026-03-27; raw 0-200 maps to 0-100%)
- **bcm_ibat** (battery current): 16-bit BE `CONCAT11(CAN B4, CAN B5)`
  → `value = uint16 * 0.025 - 1000` A (confirmed from literal pool constants)
  → invalid if `(uint16 & 0xFFFE) == 0xFFFE`
  Zero at raw=40000. Negative=discharge, positive=charge. Range approx -1000 to +638 A.
  Validated 2026-03-28: signal crosses 0 A (raw=40000) when generator runs in
  generator-on/off log; shows -3 to -7 A (accessory discharge) at idle, +6 to +7 A
  (battery charging) during generator operation.
- **bcm_vbat** (battery voltage): 12-bit = `CAN B7 | (CAN B6 & 0xF) << 8`
  → `value = uint12 * 0.25` V; invalid if raw==0xFFE
  (same SIMDImm(0xF,0x50) = 0.25 as bcm_gfd)

#### 0x0471 -- GENE_Mot_Trq

- **GENE_Mot_Trq** = `uint16_LE(CAN B0:B1) * 0.125 - 4096` Nm
  (zero at raw=32768; `FixedToFP(*(ushort*)(pbVar15+2)) * 0.125 + DAT_00029ea8`)
  - `DAT_00029ea8` at file offset 0x25ea8 = -4096.0 (double, confirmed from binary)

#### 0x0479 -- MCU_Thermal1 (GENE_DrvCoolFlowReq_pct etc.)

Format: `"GENE_DrvCoolFlowReq_pct: %.1f%  GENE_MotCoolFlowReq_pct: %.1f%  GENE_ThermInd_pct: %.1f%"`

All three signals use the same scale: `SIMDImm(0xF,0x69) = 0.78125`; raw 0-128 = 0-100%.

- **GENE_DrvCoolFlowReq_pct** (drive coolant flow request %): CAN B0 * 0.78125
- **GENE_MotCoolFlowReq_pct** (motor coolant flow request %): CAN B1 * 0.78125
- **GENE_ThermInd_pct** (thermal indicator %): CAN B2 * 0.78125

B3-B7 not read by EPRI app.

#### 0x0482 -- GENE_HighPwr_Curr / GENE_HighPwr_Volt

Format: `"GENE_HighPwr_Curr: %.2f A  GENE_HighPwr_Volt: %.1f V"`

- **GENE_HighPwr_Curr**: `B3 | (B4 & 0x3F) << 8` → 14-bit unsigned
  → `value = uint14 * 0.25 - 2048` A (DAT_0002ab28 = -2048.0 double, confirmed from binary)
- **GENE_HighPwr_Volt**: `B1 | (B2 & 0x7) << 8` → 11-bit unsigned
  → value = raw (integer cast to float), units V (1 V/count; 0-2047 V range)

B0, B5-B7 not read by EPRI app.

#### 0x0420 -- BCM_Limits

Format string: `"BCM_Limits: bcm_cell_overvolt: %@ bcm_cell_undervolt: %@ bcm_chg_max: %.2f bcm_dis_max: %.2f"` (CFString at 0xF5878)

Boolean bits (CAN B6 = pbVar15[8]):
- `bcm_cell_overvolt` -- B6 bit 7 (`(char)pbVar15[8] < 0`) -- NO/YES
- `bcm_cell_undervolt` -- B6 bit 6 (`pbVar15[8] & 0x40`) -- NO/YES

Numeric signals:
- **bcm_chg_max** (max charge current): 12-bit = `B2 | (B1 & 0xF) << 8`
  (`pbVar15[4] | (pbVar15[3] & 0xF) << 8`)
  sentinel: if `(B2 & 0xFFE | (B1&0xF)<<8) == 0xFFE` -> invalid
  value = `raw * 0.25` A (SIMDImm(0xF,0x50) = 0.25, confirmed 2026-03-27)

- **bcm_dis_max** (max discharge current): 12-bit = `(B1 >> 4) | (B0 << 4)`
  (`(pbVar15[3] >> 4) | (pbVar15[2] << 4)`)
  B0 provides the upper 8 bits [11:4], B1's high nibble provides bits [3:0]
  sentinel: if `(B1>>4 & 0xFFE | B0<<4) == 0xFFE` -> invalid
  value = `raw * 0.25` A (same 0.25 scale as bcm_chg_max)

#### 0x0430 -- BCM_Data1

Format string: `"BCM_Data1: bcm_chga_ena: %@ bcm_chga_mon: %@ bcm_mod_ena: %@ bcm_veh_mon: %@ bcm_cell_tmax: %.2f bcm_cell_tmin: %.2f bcm_cell_vmax: %.3f bcm_cell_vmin: %.3f bcm_lvbat: %.2f"` (CFString at 0xF5898)

Boolean bits:
- `bcm_chga_ena` -- CAN B0 bit 7 (`(char)pbVar15[2] < 0`) -- OFF/ON (charge adapter enable)
- `bcm_chga_mon` -- CAN B2 bit 6 (`pbVar15[4] & 0x40`) -- LOW/HIGH (charge adapter monitor)
- `bcm_mod_ena`  -- CAN B2 bit 7 (`(char)pbVar15[4] < 0`) -- OFF/ON (module enable)
- `bcm_veh_mon`  -- CAN B2 bit 5 (`pbVar15[4] & 0x20`) -- LOW/HIGH (vehicle monitor)

Numeric signals:
- **bcm_cell_tmax** (max cell temperature): CAN B4 single byte (`pbVar15[6]`)
  valid if `B4 < 0xFE`; value = `B4 * 0.5 − 40` degC
  (DAT_0002b600 = −40.0, confirmed by reading file offset 0x27600 from binary)

- **bcm_cell_tmin** (min cell temperature): CAN B5 single byte (`pbVar15[7]`)
  valid if `B5 < 0xFE`; value = `B5 * 0.5 − 40` degC (same formula as tmax)

**Temperature scaling -- experimental vs EPRI (reconciled 2026-03-27):**
The experimental notes (`cell-voltage-investigation.md`) used a provisional formula of
`raw - 100` degC, derived by correlating B4 values against ambient temperature on days
when the truck had been sitting (cells would equilibrate to ambient). Sample points:
B4=110 -> 10 degC, B4=121 -> 21 degC, B4=141 -> 41 degC, B4=143 -> 43 degC.
Under `raw - 100` these give exact integer ambient temperatures -- which looked convincing.

The EPRI formula `raw * 0.5 - 40` gives different results for the same raws:
B4=110 -> 15 degC, B4=121 -> 20.5 degC, B4=141 -> 30.5 degC, B4=143 -> 31.5 degC.

**Conclusion:** The experimental `raw - 100` was a provisional estimate, not an independent
calibration. The ambient-correlation method cannot distinguish between `raw - 100` and
`raw * 0.5 - 40` if the ambient temperatures tested happened to cluster around values where
both formulas are close (e.g., at raw=121: raw-100=21, raw*0.5-40=20.5 -- 0.5 degC apart).
The EPRI app was written specifically for this vehicle by EPRI engineers using the BMS
manufacturer's signal definitions; its DAT constant (DAT_0002b600 = -40.0, confirmed from
binary) is authoritative. Trust `raw * 0.5 - 40` and treat `raw - 100` as superseded.

- CAN B6 (`pbVar15[8]`): not referenced anywhere in the 0x430 handler; consistent with
  experimental observation that B6 is constant 0x00.

- **bcm_cell_vmax** (max cell voltage): 13-bit = `B1 | (B0 & 0x1F) << 8`
  (`pbVar15[3] | (pbVar15[2] & 0x1F) << 8`)
  value = raw * 0.001 V (DAT_0002bab0 = 0.001, confirmed from binary at file offset 0x27AB0)
  = 1 mV/count, consistent with experimental confirmation.
  Bit 4 of B0 is 0 in all observed data (all segment tag nibbles are 0x0/0x8/0xA/0xE), so
  this is functionally equivalent to the experimental 12-bit formula `(B0&0xF)*256+B1` in mV.
  Sentinel: B0=0x1F, B1=0xFE → raw=0x1FFE.

- **bcm_cell_vmin** (min cell voltage): 13-bit = `B3 | (B2 & 0x1F) << 8`
  (`pbVar15[5] | (pbVar15[4] & 0x1F) << 8`)
  value = raw * 0.001 V (same DAT_0002bab0 = 0.001). Sentinel same 0x1FFE pattern.

- **bcm_lvbat** (12V battery voltage): CAN B7 single byte (`pbVar15[9]`)
  valid if `B7 < 0xFE`; value = raw * 0.1 V (DAT_0002c568 = 0.1, confirmed from binary)
  Typical: 0x8C/0x8D (140/141) → 14.0/14.1V under charge/active; 0x7E/0x7F (126/127) → 12.6/12.7V at shutdown.
  Drops below 12.8V when DCDC converter has not started or has shut down. Note: 0x430 frames
  transmitted during this window are real BMS readings -- DCDC state does not affect BMS validity.

**Validity / sentinel approach for 0x430:**
EPRI uses per-signal sentinel values. The epri-pt-bus.dbc uses range filtering where possible:
- Cell voltages: sentinel raw=0x1FFE → 8.190 V. DBC range [0|3.8 V] excludes this -- healthy
  LFP cells stay below ~3.8 V. Range is our choice; EPRI code uses explicit raw==0x1FFE checks.
- Cell temperatures: sentinel raw>=0xFE → >=87.0 degC. DBC range [-40|80 degC] excludes this
  cleanly -- normal operating temps stay well below 80 degC.
- bcm_lvbat: valid if raw<0xFE; raw>=0xFE excluded by DBC range [0|25.3 V] (max raw=253).

#### 0x0440 -- BCM_Data2

Format string: `"BCM_Data2: bcm_balancing: %@ bcm_fault_mon: %@ bcm_balancing_cnt: %d bcm_fgd: %.2f%%"` (CFString at 0xF5998)
(bcm_mainc_stat and bcm_vbus signals are added as separate plist entries, not in this format string)

Boolean bits (CAN B0 = pbVar15[2]):
- `bcm_balancing` -- B0 bit 7 (`(char)pbVar15[2] < 0`) -- NO/YES (cell balancing active)
- `bcm_fault_mon` -- B0 bit 6 (`pbVar15[2] & 0x40`) -- LOW/HIGH (fault monitor)

**bcm_mainc_stat** -- 4-bit index from CAN B0 bits[5:2] (`(B0 << 26) >> 28`), 16-entry array:

| Idx | String | VMA | Idx | String | VMA |
|-----|--------|-----|-----|--------|-----|
| 0 | "ALL_OPEN" | 0xF58A8 | 8 | "CLOSE_MAINP" | 0xF5928 |
| 1 | "FAILED_MAINP_OR_R_WELD" | 0xF58B8 | 9 | "OPEN_MAINR" | 0xF5938 |
| 2 | "CLOSE_MAINR" | 0xF58C8 | 10 | "FAILED_MAINP_OPEN" | 0xF5948 |
| 3 | "FAILED_MAINR_OPEN" | 0xF58D8 | 11 | "MAIN_PN_CLOSED_DRIVE" | 0xF5958 |
| 4 | "FAILED_MAINN_WELD" | 0xF58E8 | 12 | "MAIN_P_CLOSED_CHARGE" | 0xF5968 |
| 5 | "CLOSE_MAINN" | 0xF58F8 | 13 | "SHUTDOWN_REQUEST" | 0xF5978 |
| 6 | "FAILED_MAINN_OPEN" | 0xF5908 | 14 | "ALL_OPEN_SHUTDOWN" | 0xF5988 |
| 7 | "WAIT_PRECHARGE" | 0xF5918 | 15 | (BCM_Data2 format string -- likely never reached) | 0xF5998 |

MAINP = main positive contactor, MAINN = main negative contactor, MAINR = main precharge resistor contactor. **These expansions are inferred from the precharge circuit state sequence (WAIT_PRECHARGE -> MAIN_P_CLOSED states), not confirmed from the Ghidra binary string dump.**
String values at VMAs 0xF58A8-0xF5988 confirmed from Mach-O cfstring scan.

Numeric signals:
- **bcm_balancing_cnt** (balancing count): CAN B7 single byte (`pbVar15[9]`)
  valid if `B7 < 0xFE`; value = raw (direct count, %d format)

- **bcm_fgd** (role unconfirmed; plist label only): CAN B1 single byte (`pbVar15[3]`)
  valid if `B1 < 0xFE`; value = `raw * 0.5` % (SIMDImm(0xF,0x60) = 0.5, confirmed 2026-03-27)
  **Always at sentinel 0xFE in all captured logs** (73 logs: all drive, charge, fault, and
  CANLog sessions). Signal is defined and decoded by EPRI binary but never populated by this
  BMS configuration.

- **bcm_vbus_neg** (negative DC bus voltage): 12-bit = `B6 | (B5 & 0xF) << 8`
  (`pbVar15[8] | (pbVar15[7] & 0xF) << 8`)
  sentinel: if `(B6 & 0xFFE | (B5&0xF)<<8) == 0xFFE` -> invalid
  value = `raw * 0.25 - 500` V (DAT_0002bab8 = -500.0 float32, confirmed 2026-03-27)
  Zero at raw=2000; range -500 to ~+524 V

- **bcm_vbus_pos** (positive DC bus voltage): 12-bit = `(B5 >> 4) | (B4 << 4)`
  (`(pbVar15[7] >> 4) | (pbVar15[6] << 4)`)
  B4 provides bits[11:4], B5 high nibble provides bits[3:0]
  sentinel: if `(B5>>4 & 0xFFE | B4<<4) == 0xFFE` -> invalid
  value = raw * 0.25 [V; literal constant 0x3fd0000000000000 = 0.25 double, confirmed]

#### 0x0598 -- HCU_VIRTSENS_7_PwrStatAvg

Format string: `"Average power discharged by the battery pack: %.2f kW\nAverage power produced by Traction motor: %.2f kW"`

Both signals decoded via `FUN_00045af0(uint16, 0x10)` followed by `FixedToFP` and multiplication by DAT_0002d1a8 = 0.01 kW/count = 10 W/count (confirmed from binary at file offset 0x291A8).

- **DBL_ESSPwrAvg** (average battery pack power): decoded from CAN B0:B1 as uint16
  (`*(uint16*)(pbVar15 + 2)` = big-endian B0:B1)

- **DBL_TracPwrAvg** (average traction motor power): decoded from CAN B5:B4 as uint16
  (`CONCAT11(pbVar15[7], pbVar15[6])` = (B5 << 8) | B4, i.e. B5 is high byte)

**FUN_00045af0(value, 0x10)** = `(int32_t)(int16_t)value` (generic N-bit sign extension;
reversed 2026-03-27).

**⚠ CORRECTED 2026-06-27 (log data):** the wire values are **offset-binary (excess-32768), zero at raw 0x8000** — NOT plain signed-int16-zero-at-0. A raw-value check of 0x598 B0-B1/B4-B5 (`artifacts/check_0598_signedness.py`) shows both channels sit at ~0x8000 at idle (zero power) and swing around 0x8000 under load, never near 0x0000/0xFFFF. Effective decode is `(raw_u16 − 32768) × 0.01 kW` (matches `powertrain-messages.md` and `Vtrux.md`). The plain `(int16_t)` reading here likely missed a preceding MSB-flip / −0x8000 offset. Range still ±327.68 kW; positive = power discharged by battery / produced by motor.

#### 0x0592 -- HCU_Sensor

Format string: `"EVSESwitchState: %@ ExportPowerState: %@ IgnitionKeyState: %@ Veh_BrakePdl_Pos: %.2f"`

All signals from CAN B0 (boolean flags) and B4:B5 (analog).

Boolean flags (OFF/ON), all from `pbVar15[2]` = CAN B0:
- **EVSESwitchState** (plist .1): B0 bit 1 (`B0 & 0x02`)
- **ExportPowerState** (plist .2): B0 bit 2 (`B0 & 0x04`)
- **IgnitionKeyState** (plist .3): B0 bit 4 (`B0 & 0x10`)

Numeric signal:
- **Veh_BrakePdl_Pos** (plist .4): uint16_LE(CAN B4:B5) (`*(ushort*)(pbVar15+6)`)
  value = `raw * 0.01` (DAT_00029ea0 = 0.01, confirmed from binary at file offset 0x25EA0)
  Units: likely % (%.2f format); raw 0-10000 = 0-100.00%

B1-B3 and B6-B7 are not read. Only .4 (BrakePdl_Pos) was sampled in the plist; .1/.2/.3 are
parsed and logged but not included in the standard sampling intervals.

#### 0x0599 -- HCU_VIRTSENS_5_Pressures

Format string: `"Generator cooling oil pressure: %.2f kPa  Traction cooling oil pressure: %.2f kPa"`
(Note: format string in binary has typo "Genertorcoolingoilpressure")

Both signals are uint16 LE scaled by DAT_0002ab30 = 0.1 kPa/count (confirmed from binary at
file offset 0x26B30).

- **GeneOilPress** (plist .2): uint16_LE(CAN B0:B1) (`*(ushort*)(pbVar15+2)`)
  value = `raw * 0.1` kPa; format arg 1 in the format string (Generator listed first)
- **TracOilPress** (plist .1): uint16_LE(CAN B4:B5) (`*(ushort*)(pbVar15+6)`)
  value = `raw * 0.1` kPa; format arg 2 in the format string

Note: plist indices (.1 = TracOilPress, .2 = GeneOilPress) are assigned in the opposite order
from the format string (Generator first, Traction second). B2:B3 are not read.

#### 0x0625 -- Veh_Odo (odometer)

Format string: `"hcuDiagPt_vehCfgGmt_md: %@ VehicleOdometer: %.1f km"`

Two logged plist entries (only .2 was included in the standard plist table):

- **Vehicle config label** (plist .1): CAN B3 (`pbVar15[5]`), 2-entry array + invalid:
  - B3 < 0x20 (`B3 >> 5 == 0`): `"K2XX"` -- GM K2XX platform (Silverado/Tahoe/Suburban/Yukon);
    covers both the Vtrux pickup (Silverado-based) and the Suburban variant
  - 0x20 <= B3 < 0x40 (`B3 >> 5 == 1`): `"600"` -- GM GMT-600 platform (Chevy Express /
    GMC Savana full-size van); covers the Vtrux Express van variant
  - B3 >= 0x40: `"Invalid(%d)"` (sentinel; not expected in normal operation)
  The HCU software was shared across Via Motors variants; this byte is a runtime platform tag.

- **VehicleOdometer** (plist .2): 24-bit value assembled from B0:B1:B2 as big-endian
  (`(CAN_B0 << 16) | (CAN_B1 << 8) | CAN_B2`; `pbVar15[2]`=B0=MSB, `pbVar15[3]`=B1,
  `pbVar15[4]`=B2=LSB)
  value = raw converted directly to float (no DAT multiplier), displayed as `%.1f km`
  Scale: 1 km/count (%.1f shows X.0 precision) or 0.1 km/count if FixedToFP applies implicit
  fractional scaling -- unconfirmed; verify against log data.
  Not logged to plist if raw == 0.

B4-B7 are not read.

#### 0x055C -- VIA CAN park lock / drive sensor

Not in any plist; found during extra-IDs investigation (2026-03-27).

Format string: `"driveSensor = %@, parkLockState = %@, parkSensor = %@"` (cfstring VMA 0xF5A38).

Three logged fields, all from B2:

| Field | Source | Extraction | Values |
|-------|--------|------------|--------|
| driveSensor | B2 bit 7 | `(char)B2 < 0` (sign bit) | "OFF" / "ON" |
| parkLockState | B2 bits [2:0] | `(int)(char)B2 & 7` | 8-entry enum below |
| parkSensor | B2 bit 6 | `(B2 & 0x40) != 0` | "OFF" / "ON" |

Each field is logged individually via `addSingleRecordWithID:withData:` (index loop using `countByEnumeratingWithState:objects:count:`).

parkLockState 8-entry enum (B2[2:0]):

| Index | String | cfstring VMA | Confidence |
|-------|--------|-------------|------------|
| 0 | "OFF" | 0xF57A8 | confirmed (explicit MOVW in decompile) |
| 1 | "Park" | 0xF57B8 | inferred (NEON paired-load adjacent to "OFF") |
| 2 | "Parked" | 0xF59E8 | confirmed (explicit MOVW in decompile) |
| 3 | "ParkStalled" | 0xF59F8 | inferred (NEON paired-load adjacent to "Parked") |
| 4 | "Unparking" | 0xF5A08 | confirmed (explicit MOVW in decompile) |
| 5 | "Unparked" | 0xF5A18 | inferred (NEON paired-load adjacent to "Unparking") |
| 6 | "UnparkStalled" | 0xF5A28 | confirmed (explicit MOVW in decompile) |
| 7 | (format string bleed -- never expected in practice) | 0xF5A38 | -- |

Index is clamped to `count - 1` if out of range. Index 7 bleeds into the format string cfstring; it should never occur in valid data.

B0-B1, B3-B7 are not read.

#### 0x0580 -- TCM CAN error flag

Not in any plist; found during extra-IDs investigation. No EPRI signal name (no format string).

Single logged field: `tcm_CAN_ERR: %@` — B2 bit 1, YES/NO.

- `(pbVar15[4] & 2) != 0` → `"YES"`, else `"NO"`
  (`pbVar15[4]` = CAN B2; bit 1 is the second-lowest bit)

Logged as a single plist record via `addSingleRecordWithID:withData:` using the YES/NO string.
B0, B1, B3-B7 are not read.

#### 0x062F -- HCU software version

Not in any plist; found during extra-IDs investigation. No EPRI signal name.

Format string: `"MajorVersion: %d MinorVersion: %d HCU_SwIDCalVer_Cnt: %d HCU_SwIDMaturity_Enum: %d HCU_SwIDPrj_Enum: %d HCU_SwIDType_Enum: %d HCU_SwIDVehVariant_Enum: %d"`

The 7 fields are tightly bit-packed across B0:B5:

| Field | Source bytes | Extraction |
|-------|-------------|------------|
| HCU_SwIDPrj_Enum | B0 bits 7:2 | `B0 >> 2` (6-bit) |
| HCU_SwIDType_Enum | B0 bit 1 | `(B0 >> 1) & 1` (1-bit) |
| HCU_SwIDMaturity_Enum | B0 bit 0, B1 bit 7 | `(B0 & 1) << 1 \| (B1 >> 7)` (2-bit) |
| MajorVersion | B1 bits 6:0 | `B1 & 0x7F` (7-bit) |
| MinorVersion | B2 | full byte (8-bit) |
| HCU_SwIDVehVariant_Enum | B3, B4 bits 7:6 | `(B3 << 2) \| (B4 >> 6)` (10-bit uint) |
| HCU_SwIDCalVer_Cnt | B4 bits 5:0, B5 bits 7:6 | `(B4 << 2) \| (B5 >> 6)` (8-bit) |

B6-B7 are not read.

Each field is also logged individually as a separate plist entry `"<CAN_ID>.<n>"` (n = 1..7),
stored as a formatted decimal string `"%d"`. The combined format-string log is a separate record.
(The per-field loop iterates over a 7-element NSArray using `countByEnumeratingWithState:objects:count:`.)

#### 0x065B -- HCU DTC code dispatcher

Not in any plist; found during extra-IDs investigation. No EPRI signal name.

Reads B6:B7 as a big-endian uint16 DTC code: `sVar3 = (B6 << 8) | B7` (`pbVar15[8]`, `pbVar15[9]`).

If the 16-bit value is 0x0000, logs `<null>`. Otherwise looks up the value in a 29-entry
`NSDictionary` (integer key -> string name) and logs the matching DTC string. All 29 entries
confirmed in binary at cfstring VMAs 0x0F5B18-0x0F5CD8 (Task 23, 2026-03-27).

29-entry DTC lookup table:

| Code | String key |
|------|-----------|
| 0x0D67 | `aChgr_p0d67ChgrPfrm_dtc` — charger platform DTC |
| 0x1A20 | `sEss_p1a20BecmAFlt` — BECM fault A |
| 0x0A7B | `sEss_p0a7bBecmMilOnReq` — BECM MIL-on request |
| 0x1A21 | `sEss_p1a21BecmACritFlt` — BECM critical fault A |
| 0x1A81 | `sEss_p1a81HvilPrfmGene` — HVIL performance, generator |
| 0x1A82 | `sEss_p1a82HvilPrfmTrac` — HVIL performance, traction |
| 0x1A80 | `sEss_p1a80HvilPrfmDcdc` — HVIL performance, DCDC |
| 0x0AA6 | `sEss_p0aa6HvIso` — HV isolation |
| 0x1AA0 | `sChgr_p1aa0ChgrShtdwn` — charger shutdown |
| 0x0A0B | `cEss_p0a0bHvilPrfm` — ESS HVIL performance |
| 0x0A1F | `cEss_p0a1fEss` — ESS fault |
| 0xD300 | `diagHcu_u1300AppIntrptTsk` — HCU: app interrupt task |
| 0xD301 | `diagHcu_u1301LowMemTsk2` — HCU: low mem task 2 |
| 0xD302 | `diagHcu_u1302LowMemTsk1` — HCU: low mem task 1 |
| 0xD303 | `diagHcu_u1303LowMemIdleTsk` — HCU: low mem idle task |
| 0xD304 | `diagHcu_u1304LowMemIntrpt` — HCU: low mem interrupt |
| 0xD305 | `diagHcu_u1305LowMemKernel` — HCU: low mem kernel |
| 0xD306 | `diagHcu_u1306ShtdwnTsk` — HCU: shutdown task |
| 0xD307 | `diagHcu_u1307LowMemHeap` — HCU: low mem heap |
| 0xD311 | `diagHcu_u1311HighCpuTsk2` — HCU: high CPU task 2 |
| 0xD310 | `diagHcu_u1310HighCpuAppIntrptTsk` — HCU: high CPU app interrupt task |
| 0xD312 | `diagHcu_u1312HighCpuTsk1` — HCU: high CPU task 1 |
| 0xD313 | `diagHcu_u1313HighCpuShtdwnTsk` — HCU: high CPU shutdown task |
| 0xD314 | `diagHcu_u1314CpuIdleApp` — HCU: CPU idle app |
| 0xC129 | `inAbstrCanEbcm_u0129LostRx` — CAN lost Rx: EBCM |
| 0xC100 | `inAbstrCanEcm_u0100LostRx` — CAN lost Rx: ECM |
| 0xC16B | `inAbstrCanAccm_u016BLostRx` — CAN lost Rx: ACCM |
| 0xC111 | `inAbstrCanBecm_u0111LostRx` — CAN lost Rx: BECM |
| 0xC296 | `inAbstrCanBdc_u0296LostRx` — CAN lost Rx: BDC |

The DTC codes embed the GMLAN SPN/DTC conventions: `sEss_` = ESS (Energy Storage System/BECM);
`sChgr_` / `aChgr_` = charger; `cEss_` = ESS controller; `diagHcu_` = HCU self-diagnostics;
`inAbstrCan*_` = CAN abstraction layer lost-receive faults for specific modules (EBCM, ECM,
ACCM, BECM, BDC).

B0-B5 are not read.

#### 0x063A -- VehicleConfig (charger type / ESS type)

Not in any plist; found during systematic decompile enumeration (2026-03-27).

No EPRI signal name (no format string cfstring referencing this ID).

Format string: `"iVehCfg_chgr_md = %@, iVehCfg_ess_md = %@"` — charger mode and ESS (battery pack) type.

Two fields, both from B7 (`pbVar15[9]`):

| Field | Source | Values |
|-------|--------|--------|
| iVehCfg_chgr_md (charger type) | B7 bit 0 | 0 = "POWERONE", 1 = "DRS" |
| iVehCfg_ess_md (ESS/battery type) | B7 bit 1 | 0 = "A123", 1 = "VALENCE" |

Both fields are logged individually via `addSingleRecordWithID:withData:` (NSArray enumeration loop).

B0-B6 are not read.

#### 0x18EFC000 -- no decoder (recognized but unhandled)

This ID appears explicitly in the binary as `if (uVar59 != 0x18efc000)` — used as a guard to route around the 0x18FFD4C0 paged handler — but has no decoder of its own. Control flow for 0x18EFC000 reaches `LAB_0002982c` which logs `"UnknownCANID %08x"`. The ID may be a removed handler or a range boundary marker. No fields are decoded.

### Signal decodings from ViaOBDParser::parseEPRIMessage:

Same structure as ViaCANbusParser. Key decoded signals:

#### 0x00C9 -- PPEI_Engine_General_Status_1 (engine speed)

Format string: `"Engine speed: %7.3f rpm"`

- **Engine speed**: uint16 BE at `CONCAT11(B1, B2)` → FixedToFP → × SIMDImm(0xF,0x50) = 0.25
  value = `uint16_BE(B1:B2) * 0.25` rpm
  This is standard GM PPEI encoding; cross-check against GMLAN DBC expected to match exactly.

#### 0x0120 -- BCM_Vehicle_Odometer_HS

Format string: `"VehicleOdometer: %.3f miles"`

- **VehicleOdometer**: uint32 BE from B1:B2:B3:B4 (`(B1<<24)|(B2<<16)|(B3<<8)|B4`)
  value = `raw * DAT_00044f88 * DAT_00044f90` = `raw * 0.015625 * 0.62137` miles
  = raw × 0.015625 km/count (standard PPEI scale), then converted to miles for display.
  DAT_00044f88 = 0.015625 (double), DAT_00044f90 = 0.62137 (double) = km→miles factor.
  B0 is not read (likely message counter or flags byte).

#### 0x01C3 -- PPEI_Engine_Torque_Status_2

Format string: `"EngineTorqueActual: %.1f Nm  EngineTorqueRequested: %.1f Nm"`

Both signals are 12-bit unsigned fields scaled by 0.5 with offset DAT_00044f98 = −848.0 Nm.
Zero torque at raw = 1696 (1696 × 0.5 − 848 = 0). Range: −848 to +1199.5 Nm.

- **EngineTorqueActual** (plist .1): 12-bit = `(B0 & 0xF) << 8 | B1`
  value = `raw * 0.5 − 848` Nm
- **EngineTorqueRequested** (plist .2): 12-bit = `(B2 & 0xF) << 8 | B3`
  value = `raw * 0.5 − 848` Nm

Note on byte order: B0 provides the upper 4 bits ([11:8]) and B1 provides the lower 8 bits ([7:0])
for Signal 1; same pattern shifted by 2 bytes for Signal 2. This is consistent with standard
PPEI encoding but the nibble assignment should be cross-checked against a GMLAN DBC.

#### 0x02C3 -- MAP (Manifold Absolute Pressure)

Format string: `"Manifold absolute pressure: %.1f kPa"`

**Note on plist label:** The EPRI plist used 'PPEI_Engine_Torque_Status_3' as the message name — correct per GM spec (confirmed against GMLAN DBC). The decompile reveals the EPRI app reads MAP from B6, one of several signals in the message.

- **MAP**: CAN B6 single byte, signed int8 (`puVar20[8]`), × SIMDImm(0xF,0x60) = 0.5
  value = `int8(B6) * 0.5` kPa
  Range: −64 to +63.5 kPa. Likely gauge pressure (atmospheric ≈ 0 kPa, vacuum = negative).
  B0–B5, B7 are not read by this handler.

#### 0x03D1 -- Instantaneous Fuel Consumption Rate

Format string: `"ECM_InstFuelConsmpRate_volPt: %.3f ltrs/hr"`

**Note on plist label:** The EPRI plist used 'PPEI_Engine_General_Status_2' as the message name — correct per GM spec (confirmed against GMLAN DBC). The decompile reveals the EPRI app reads fuel rate, one of several signals in the message.

- **ECM_InstFuelConsmpRate_volPt**: 12-bit = `(B4 & 0xF) << 8 | B5`
  value = `raw * DAT_000447a0` = `raw * 0.025` L/hr
  DAT_000447a0 = 0.025 (double, confirmed from binary at file offset 0x437A0).
  Range: 0 to 4095 × 0.025 = 102.375 L/hr.

#### 0x03E9 -- PPEI_Vehicle_Speed_and_Distance

Format string: `"ECM_DistRollCntAvgDrvn_dist: %.2f km  ECM_VehSpdAvgDrvn_linspd: %.3f km/h"`

- **ECM_DistRollCntAvgDrvn_dist** (plist .1): 13-bit = `(B2 & 0x1F) << 8 | B3`
  value = `raw * 0.125` km (signed via int cast, but range 0–8191 is always positive)
  Delta distance since last message transmission.
- **ECM_VehSpdAvgDrvn_linspd** (plist .3): 15-bit = `(B0 & 0x7F) << 8 | B1`
  value = `raw * DAT_000447a8` = `raw * 0.015625` km/h = `raw / 64` km/h
  DAT_000447a8 = 0.015625 (double, confirmed from binary at file offset 0x437A8).
  Range: 0 to 32767 × 0.015625 = 511.98 km/h.

Plist entry .2 is a placeholder (sentinel value −1); only .1 and .3 are stored.
B4–B7 are not read.

#### 0x04C1 -- PPEI_Engine_General_Status_4 (engine temperatures)

Format string: `"Engine coolant temp: %d degC  Engine air intake temp: %d degC  Outside air temp (Est.): %f degC"`

Decompile (case 0x4c1, lines ~5294-5302 in ghidra-via-decompiled.txt):
- `cVar31 = puVar20[4]` -- B4: engine coolant temp
- `cVar3 = puVar20[5]` -- B5: air intake temp
- `(uint)(byte)puVar20[6]` -- B6: outside air temp (zero-extended to uint)
- Coolant/intake formula: `(int)(char)(raw - 0x28)` -- signed byte then subtract 40
- Outside air formula: `FixedToFP(uint8) * 0.5 + DAT_000441b8`
  - DAT_000441b8 = -40.0 (double, confirmed at file offset 0x401b8)
  - value = `uint8(B6) * 0.5 - 40.0` degC, resolution 0.5 degC

Signal summary:
- **ECM_EngineCoolantTemp**: B4, `uint8 - 40` degC (1 degC resolution, range -40 to +215 degC)
- **ECM_EngineAirIntakeTemp**: B5, `uint8 - 40` degC (same formula)
- **ECM_OutsideAirTemp**: B6, `uint8 * 0.5 - 40.0` degC (0.5 degC resolution, range -40 to +87.5 degC)
- B0-B3 and B7 not read by EPRI app.

Note: DAT_000441b8 is the same -40.0 offset used by the thermal investigation (standard GM temperature encoding). The int8 cast for coolant/intake is only relevant above raw 127 (>87 degC for a 1:1 scale); for normal engine operating range signed and unsigned give the same result.

#### GMLAN DBC cross-check (2026-03-27)

All EPRI-decoded signals confirmed consistent with GMLAN DBC encodings. Two exceptions:

- **0x0120 odometer:** GMLAN DBC carries a placeholder signal (B0:B3, scale=1); EPRI reads B1:B4 × 0.015625 km, which is the actual Vtrux encoding. EPRI is authoritative here.
- **0x02C3 MAP:** GMLAN DBC marks the signal unsigned (correct); EPRI uses signed, giving wrong values above 63.5 kPa (raw > 127, i.e. above sea-level atmospheric). Use unsigned.

---

#### TRAC_RotSpd (0x0044 B0:B1, on OBD bus)

- Same formula as GENE_RotSpd: `int16_LE(CAN B0:B1) - 32767` rpm

#### TRAC_Mot_Trq (0x0451 B2:B3, on OBD bus)

- **TRAC_Mot_Trq** = `uint16_LE(CAN B0:B1) * 0.125 - 4096` Nm
  - `DAT_000441b0` at file offset 0x401b0 = -4096.0 (double, confirmed from binary)
  - Identical formula to GENE_Mot_Trq -- confirmed symmetric MCU encoding across both
    motor controllers (GENE on PT bus, TRAC on OBD bus)

#### 0x0462 -- TRAC_HighPwr_Curr / TRAC_HighPwr_Volt (on OBD bus)

- Same 14-bit layout as GENE (0x0482): `CAN B3 | (CAN B4 & 0x3F) << 8`
- `value = uint14 * 0.25 - 2048` (same DAT constant as GENE_HighPwr)

### Remaining items -- not yet decoded from Ghidra decompile

All items below are expected to be in `notes/artifacts/ghidra-via-decompiled.txt` (263 KB,
12 functions). Source plist column: P = Via_CANid_List (PT bus), O = Via_OBD_List (OBD bus),
C = ViaCANData.txt (passive monitor, may or may not have a decode path in the app).

#### PT bus signals (parseEPRIMessage, ViaCANbusParser)

| ID | EPRI signal name | Plist | Notes |
|----|-----------------|-------|-------|
| ~~0x0592~~ | HCU_Sensor: EVSESwitchState, ExportPowerState, IgnitionKeyState, Veh_BrakePdl_Pos | P .4 | DONE 2026-03-27 |
| ~~0x0599~~ | HCU_VIRTSENS_5_Pressures: GeneOilPress, TracOilPress | P .1/.2 | DONE 2026-03-27 |
| ~~0x0625~~ | Veh_Odo: vehicle config + odometer | P .2 | DONE 2026-03-27 (odometer scale unconfirmed) |

#### OBD bus signals (parseEPRIMessage, ViaOBDParser)

These are standard GM PPEI/GMLAN messages; the app likely decodes them with known GM
encoding. Worth extracting the exact byte layout and scale from the decompile to cross-check
against existing GMLAN DBC files -- any discrepancy could indicate Via-specific extensions
or corrections to the standard encoding.

| ID | EPRI signal name | Plist | Notes |
|----|-----------------|-------|-------|
| ~~0x00C9~~ | Engine speed (B1:B2 BE × 0.25 rpm) | O | DONE 2026-03-27 |
| ~~0x0120~~ | BCM_Vehicle_Odometer_HS (B1:B4 BE × 0.015625 km, displayed miles) | O | DONE 2026-03-27 |
| ~~0x01C3~~ | EngineTorqueActual + Requested (12-bit × 0.5 − 848 Nm) | O | DONE 2026-03-27 |
| ~~0x02C3~~ | Manifold abs pressure (B6 int8 × 0.5 kPa) -- plist label was wrong | O | DONE 2026-03-27 |
| ~~0x03D1~~ | Inst. fuel consumption rate (12-bit × 0.025 L/hr) -- plist label was wrong | O | DONE 2026-03-27 |
| ~~0x03E9~~ | Distance (13-bit × 0.125 km) + speed (15-bit × 0.015625 km/h) | O | DONE 2026-03-27 |
| ~~0x04C1~~ | Engine coolant temp (B4), air intake temp (B5), outside air temp (B6) | O | DONE 2026-03-28 -- was missing from this table; decoded from decompile case 0x4c1 |

#### Passive monitor IDs (in ViaCANData.txt, not in plists)

These IDs appear in the sample data file but have **no handler anywhere in the decompiled
code** — they do not appear in parseEPRIMessage or any other decompiled function. The app
captures them on the bus but does not decode them. Their content is unknown from the EPRI
app alone.

Searched entire Vtrux log corpus (all sessions including charge logs, individual debuglog
chunks, and truk1log M1 chunks) for all six IDs. Result: **0x00C1 appears in 62 log files
across the entire corpus — ubiquitous.** The other five are complete zeros.

| ID | Bus | Status |
|----|-----|--------|
| 0x00C0 | PT | absent from all Vtrux logs; not our truck |
| 0x00C1 | PT | **present in 62 log files; ubiquitous on Vtrux PT bus; no decode in app** |
| 0x00C4 | PT | absent from all Vtrux logs; not our truck |
| 0x016A | PT | absent from all Vtrux logs; not our truck |
| 0x0710 | PT | absent from all Vtrux logs; not our truck |
| 0x0720 | PT | absent from all Vtrux logs; not our truck |

The five absent IDs originated from whatever vehicle produced ViaCANData.txt (likely a
different Via truck variant or test bench) and are not relevant to Truck 1. 0x00C1 is
a real Vtrux message; its content is unknown and not decoded by the app.

Note: while searching for these, three additional PT bus IDs were found in parseEPRIMessage
that were never in any plist and had not been previously documented — 0x0580, 0x062F, 0x065B.
These are now decoded in the signal decodings section above.

#### GoPoint-internal encapsulation IDs

These IDs are GoPoint BT1 internal message type IDs — not raw CAN IDs. The GoPoint
translates CAN bus data into its own proprietary Bluetooth SPP packet format before
sending to the iPhone. EPT (Extended Powertrain) and EAC (Electric A/C) are GoPoint
message categories defined in the GoPoint Programming Manual v4.6.

**Initial assumption** (wrong): these IDs were thought to live in GoPoint SDK code outside
the 12 decompiled functions.

**Task 24 recon (2026-03-27) found:** all three GoPoint IDs ARE in
`ViaCANbusParser::parseEPRIMessage` (VMA 0x25D00). The MOVT constant search located the
comparison instructions in two clusters inside the function body — regions that Ghidra
apparently failed to render cleanly in the original decompile export:

| GoPoint ID | MOVT instruction VMA(s) | Offset into function |
|-----------|------------------------|---------------------|
| 0x0870A047 (EAC_STATUS2) | 0x2636E, 0x2637C | ~1650 bytes in |
| 0x06000001 (EPT_Stat_HMI_1) | 0x275FE | ~6400 bytes in |
| 0x0868A047 (EAC_STATUS1) | 0x2760C | ~6410 bytes in |

**Ghidra session 2 (2026-03-27):** `DecompileGoPoint.java` targeted `EPRIGoPointModule`
(33 methods), `EPRIViaBus`, GoPoint name-matched functions, and `parseEPRIMessage` via the
four MOVT VMAs. 27 functions decompiled; output in `artifacts/ghidra-gopoint-decompiled.txt`.

##### GoPoint message wire format

The GoPoint device wraps CAN frames into its own protocol over iOS EAP (External Accessory
Protocol). `EPRIGoPointModule::processInputData` unpacks the stream:

- If `messageIsGoPointMessage` (class byte in GoPoint header): routed to `handleGoPointMessage:` for protocol control (module state machine, filter setup, bus type detection, sleep/wake).
- If `messageIsGoPointUserData` and module state == 1 (CONNECTED): extract CAN payload via `subdataWithRange:3:B2` (skip 3 GoPoint header bytes, take B2 payload bytes) → wrap in `EPRIMessage` → `delegate.busDataReceived:` → `ViaCANbusParser::parseEPRIMessage:`.

Inside `parseEPRIMessage`, each CAN-like frame starts with a 4-byte GoPoint message type ID
(big-endian 32-bit), followed by signal data bytes. The parser first examines B0 to decide
standard (B0 < 0x80, uses B0:B1 as 16-bit ID) vs. extended (B0 >= 0x80). The three GoPoint
IDs 0x06000001, 0x0868A047, 0x0870A047 all have B0 < 0x80 and are dispatched via a nested
binary search on the full 32-bit ID.

The 29-bit GoPoint IDs use the upper 16 bits for the category dispatch tree. The three IDs
are in the `uVar2 >= 0x0600` branch, well beyond the standard 11-bit CAN ID range of 0x000–0x7FF.

##### 0x06000001 -- EPT_Stat_HMI_1 (powertrain HMI state)

Plist signals: Accel_Ped_Pos (index .2, logged at 1 Hz), Veh_Speed (index .3, logged at 1 Hz).
The .1 index is absent from the plist and not decoded here — possibly a transmission state field.

Format string logged: "Gear lever position: %@ Accelerator pedal position: %d Vehicle Speed: %f/kmph"

| Byte offset | Field | Extraction | Notes |
|-------------|-------|-----------|-------|
| B4 | Accel_Ped_Pos | `B4 >> 1` (bits [7:1]) | 7-bit raw, 0-127; stored as NSNumber/unsignedChar, fed to dataSampler as plist index .2 |
| B7 | Gear lever | `(B7 << 27) >> 29` = bits [4:2] | 3-bit, 0-5 → 6-entry enum; see table below |
| B10, B11 | Veh_Speed | `(B10:B11 BE uint16) / 128` | Equivalent to `(B10<<7)\|(B11>>1)` as a 15-bit integer × 0.015625; scale constant DAT_00029588 = 0.015625 (1/64) confirmed from binary; range 0–511 km/h, realistic range 0–120 km/h = raw 0–15360; float pushed to `[appDelegate setSpeed:]` |

**Gear position enum** (6-entry NSArray, cfstring VMAs confirmed from binary 2026-03-27):

| Index | String | VMA | Note |
|-------|--------|-----|------|
| 0 | "Park" | 0xF57B8 | confirmed |
| 1 | "UnPark" | 0xF57C8 | inferred (NEON paired-load adjacent to Park; same strings used in ParkRequest 0x0308 enum) |
| 2 | "Neutral" | 0xF5D28 | confirmed |
| 3 | "Drive" | 0xF5D38 | inferred (NEON paired-load adjacent to Neutral) |
| 4 | "Low" | 0xF5D48 | confirmed (direct `&cf_Low` ref in decompile) |
| 5 | "Invalid" | 0xF52F8 | confirmed (direct `&cf_Invalid` ref in decompile) |

Entries [1] and [3] are inferred from the NEON register paired-load pattern (same pattern
confirmed against OperationMode where the implicit register always holds the adjacent-higher
cfstring). The 'Reverse' cfstring at 0xF5D18 is not in this array; it appears elsewhere in
the parser (possibly a diagnostic format string or a separate VIA CAN message condition check).

Gear index also sent to `[ViaOperatingMode setDrivePosition:]` when index < array count - 1
(i.e., when a valid gear, not "Invalid").

##### 0x0868A047 -- EAC_STATUS1 (A/C compressor status)

Plist signals: EAC_Elec_Curr (index .2, logged at 1 Hz), EAC_Elec_Pwr (index .3, logged at 1 Hz).
The .1 index is absent from the plist.

Format string logged: "AC-Compressor status: %@ AC Current: %f/Amps AC Electric power: %d Watt EAC_CompFltStat: %@"

| Byte offset | Field | Extraction | Notes |
|-------------|-------|-----------|-------|
| B4[6:3] | AC compressor status | `(B4 << 25) >> 28` = 4 bits | Index into 4-entry enum (see table below) |
| B4[3:0] | EAC_CompFltStat | `B4 & 0x0F` | Index into 8-entry fault enum (see table below); indices 0-6 valid |
| B5 | EAC_Elec_Pwr | `B5 * 40` | Watts (0x28 = 40); unsigned char; dataSampler plist index .3 |
| B8 | EAC_Elec_Curr | `B8 * 0.2` | Amps; scale constant DAT_00027b10 = 0.2 (double) confirmed from binary; range 0–51.0 A; dataSampler plist index .2 |

**AC compressor status enum** (4-entry array @ 0xF5D68, confirmed 2026-03-27):

| Index | String | VMA |
|-------|--------|-----|
| 0 | "Normal Operation" | 0xF5D68 |
| 1 | "Degraded Operation" | 0xF5D78 |
| 2 | "Inoperative" | 0xF5D88 |
| 3 | "No Fault" | 0xF5D98 |

**EAC_CompFltStat fault enum** (8-entry array @ 0xF5D98, confirmed 2026-03-27; indices 0-6 valid):

| Index | String | VMA |
|-------|--------|-----|
| 0 | "No Fault" | 0xF5D98 |
| 1 | "Under Voltage" | 0xF5DA8 |
| 2 | "Over Voltage" | 0xF5DB8 |
| 3 | "Over Temperature" | 0xF5DC8 |
| 4 | "Input Control" | 0xF5DD8 |
| 5 | "Current Fault" | 0xF5DE8 |
| 6 | "Internal Fault" | 0xF5DF8 |
| 7 | (format string bleed -- unreachable) | 0xF5E08 |

One explicit `addSingleRecordWithID:withData:` call logs the compressor status string at
GoPoint ID sub-record .1 before the dataSampler loop for indices .2/.3.

##### 0x0870A047 -- EAC_STATUS2 (A/C compressor HV voltage)

Plist signal: EAC_CompHVInput (single index, logged at 1 Hz).

Format string logged: "EAC High Voltage volt reading: %d VDC"

| Byte offset | Field | Extraction | Notes |
|-------------|-------|-----------|-------|
| B6 | EAC_CompHVInput | `B6 << 2` = `B6 * 4` | VDC; 8-bit raw → multiply by 4; range 0-1020 VDC; stored via `updateDataSamplerWithID:withValue:` |

This is the simplest of the three: single field, no enum lookup, no multi-byte combiner.

##### .1 index — what the plist did not log

Both 0x06000001 and 0x0868A047 have a .1 sub-record:
- **0x06000001 .1**: the gear lever position string is added to the `uVar16` array (via `addObject:`)
  at slot 0 before the data sampler loop that writes .2 and .3. The sampler loop for
  0x06000001 starts with `local_b6c = 1`, meaning sub-record index starts at 1, so the
  string array entry (gear) would be at .1 if explicitly logged — but it is NOT in the plist.
  The gear position IS sent to `[ViaOperatingMode setDrivePosition:]` in real time, just
  not written to the SQLite log.
- **0x0868A047 .1**: the compressor status string is explicitly logged via
  `addSingleRecordWithID:withData:` at sub-record .1, separate from the dataSampler loop.
  But the plist has no entry for .1, so it never surfaces in the exported log data.

**Summary of decode status:**

| ID | Plist index | Signal | Status |
|----|------------|--------|--------|
| 0x06000001 | .1 | Gear lever position (string) | Decoded — not in plist, not logged to SQLite |
| 0x06000001 | .2 | Accel_Ped_Pos | Decoded: B4 >> 1 (0-127 raw) |
| 0x06000001 | .3 | Veh_Speed | Decoded: B10:B11 BE uint16 / 128 km/h (scale 0.015625) |
| 0x0868A047 | .1 | AC compressor status string | Decoded — logged to SQLite but not in plist |
| 0x0868A047 | .2 | EAC_Elec_Curr | Decoded: B8 * 0.2 Amps (scale confirmed) |
| 0x0868A047 | .3 | EAC_Elec_Pwr | Decoded: B5 × 40 Watts |
| 0x0870A047 | (only) | EAC_CompHVInput | Decoded: B6 × 4 VDC |

Both scale constants confirmed by reading the binary data section directly (`read_gopoint_scales.py`):
- `DAT_00027b10` = 0.2 (IEEE 754 double `9a9999999999c93f`) → EAC_Elec_Curr = B8 * 0.2 A
- `DAT_00029588` = 0.015625 = 1/64 (IEEE 754 float32 `0000803c`) → Veh_Speed = B10:B11 BE uint16 / 128 km/h

#### 0x18FFD4C0 page 3 -- 3 missing fault flags

The EPRI app does not decode three flags present in the Bel DBC (B2 & 0x08 =
wakeOutputError, B2 & 0x20 = underFrequency, B2 & 0x40 = overFrequency). These are
documented in the 0x18FFD4C0 page 3 section above. Bel DBC is authoritative for the bit
positions; no Ghidra work needed unless the EPRI app uses a different bit mask.

---

### Open items from Ghidra analysis

- ~~**bcm_chgc_stat / bcm_mainc_stat string array entries [1] and [3]** (0x0410)~~
  RESOLVED 2026-03-27: Full array confirmed OPEN/CLOSED/HIGH/LOW.
  Previous [2]="FAILURE" was a cross-contamination from the 0x0044 OperationState array.

- **bcm_mainc_stat index 15** (0x0440): the 16-entry array is built by placing 16 consecutive
  cfstring pointers from 0xF58A8 to 0xF5998 on the stack. Entry 15 at 0xF5998 happens to be
  the BCM_Data2 format string itself (an artifact of adjacent cfstrings). This index is likely
  never reached in practice (4-bit state machine only has 15 real states, 0-14).

- ~~**0x18FFD4C0 full bit-field decode**~~
  RESOLVED 2026-03-27: All 4 pages fully decoded. See section above.
  Bonus: discovered 0x18EFC000 (EPRI command/mode message) also parsed by the app
  (SetpointMode, LED1/LED2 mode, cmd_Enable, cmd_Mode). Not in Bel DBC.

**Resolved since last update (2026-03-27):**
- 0x0053 OperationMode (4 entries) and OperationState (9 entries) string arrays: DONE
- 0x0410 bcm_alarm string array ["NONE","TYPE1","TYPE2","TYPE3"]: DONE
- 0x0410 bcm_chgc_stat/mainc_stat array partial resolution: DONE
- 0x0420 BCM_Limits full signal decode: DONE
- 0x0430 BCM_Data1 full signal decode: DONE
- 0x0440 BCM_Data2 full signal decode including 16-entry mainc_stat array: DONE
- 0x0598 HCU_VIRTSENS_7_PwrStatAvg decode: DONE

**Resolved 2026-03-27 (this session):**
- SIMDImm(0xF,0x50) = 0.25, SIMDImm(0xF,0x60) = 0.5, SIMDImm(0xF,0x69) = 0.78125: DONE
- DAT_0002bab8 = -500.0 (bcm_vbus_neg offset): DONE
- FUN_00045af0 fully reversed: DONE
- Extended ID messages 0x18FFD5C0/6B3/6C0/7C0/8C0 fully decoded: DONE
- Cross-validated against Bel Fuse DBC (`BelInverter.dbc`): DONE (see note below)
- GoPoint IDs 0x06000001/0x0868A047/0x0870A047 fully decoded (byte layouts, scales, enum lookups): DONE via Ghidra session 2
- EPRIGoPointModule protocol flow documented (processInputData, handleGoPointMessage, state machine): DONE
- .1 sub-record mystery resolved: gear lever position (0x06000001) and AC compressor status string (0x0868A047) are computed and either sent to ViaOperatingMode/app delegate or logged to SQLite respectively, but absent from plist so not exported

**Bel DBC cross-validation (2026-03-27):** `projects/vtrux/BelInverter.dbc` covers
0x18FFD4C0/5C0/6C0/7C0/8C0 and additionally 0x18FFD9C0/FFDAC0/FFDBC0.
All scales, byte positions, and signedness confirmed against EPRI decompile:
- 0x18FFD4C0 mux flags spot-checked: evseConnected, chargingInProgress, exporting, gridTied,
  bBoostState (m1), inverterState (m2), AC faults (m3) all match exactly.
- 0x18FFD6C0: perfect byte/scale match (leg1/2Voltage = Vout1/2, leg1/2Current = Iout1/2).
- 0x18FFD7C0: scale 0.05, byte positions match; Bel marks all signed, EPRI unsigned for
  voltage/AC signals (benign, those can't go negative in practice).
- 0x18FFD8C0: B0:B1 12V voltage at 0.02V/count confirmed.
- 0x18FFD9C0/FFDAC0/FFDBC0: fully covered by Bel DBC; EPRI app doesn't parse them.
  No Ghidra work needed -- Bel DBC is authoritative for these.
- 0x18FFD6B3 (DCDC converter): NOT in Bel DBC -- different device. EPRI decompile is
  the sole decode source for this message.

---

### DAT constants confirmed from binary (complete list)

| VMA | File offset | Value | Used in | Signal |
|-----|-------------|-------|---------|--------|
| 0x0002b600 | 0x27600 | -40.0 (double) | 0x0430 | bcm_cell_tmax/tmin: `raw * 0.5 - 40` degC |
| 0x0002bab0 | 0x27AB0 | 0.001 (double) | 0x0430 | bcm_cell_vmax/vmin: `raw * 0.001` V |
| 0x0002bab8 | 0x27AB8 | -500.0 (float32) | 0x0440 | bcm_vbus_neg offset: `raw * 0.25 - 500` V |
| 0x0002c568 | 0x28568 | 0.1 (double) | 0x0430 | bcm_lvbat: `raw * 0.1` V |
| 0x0002d1a8 | 0x291A8 | 0.01 (double) | 0x0598 | ESS/Trac power: `decoded * 0.01` kW |
| 0x00027b18 | 0x23B18 | 0.05 (double) | 0x18FFD6B3 | DCDC volt/current scale |
| 0x00027b20 | 0x23B20 | 0.1 (double) | 0x18FFD6B3 | DCDC temperature scale |
| 0x00028950 | 0x24950 | 0.05 (double) | 0x18FFD6C0 | INVCH_Inv AC output scale |
| 0x00028d50 | 0x24D50 | 0.05 (double) | 0x18FFD7C0 | INVCH_Bdc/Chg scale |
| 0x00026cf0 | 0x22CF0 | 0.02 (double) | 0x18FFD8C0 | INVCH_Bdc_12Vbat scale |
| 0x00029590 | 0x25590 | 0.1 (double) | 0x18FFD5C0 | INVCH_Bdc temperature scale |

### SIMDImm VFP immediates (ARM VMOV.F32 8-bit encoding, decoded 2026-03-27)

ARM VFP immediate encoding: for imm8 = `abcdefgh`, the float is:
sign=a, exp=NOT(b):b:b:b:b:b:c:d (biased-127), mantissa=e:f:g:h:0...0

| Ghidra notation | imm8 | Decoded float | Affected signals |
|-----------------|------|---------------|-----------------|
| SIMDImm(0xF, 0x50) | 0x50 | **0.25** | bcm_gfd, bcm_vbat (0x0410); bcm_chg_max, bcm_dis_max (0x0420) |
| SIMDImm(0xF, 0x60) | 0x60 | **0.5** | bcm_soc (0x0410); bcm_fgd (0x0440) |
| SIMDImm(0xF, 0x69) | 0x69 | **0.78125** | 0x0479 coolant flow percentages |

Updated signal scales for 0x0410/0x0420/0x0440 (replacing "TBD"):
- **bcm_ibat**: `uint16_BE * 0.025 - 1000` A; zero at raw=40000; neg=discharge, pos=charge; range -1000 to +638 A
- **bcm_gfd**: `uint12 * 0.25`; CONFIRMED ground fault detection; 1000.0=normal, 0.0=isolation fault (fires 150ms before EPO). Confirmed 2026-03-29.
- **bcm_vbat**: `uint12 * 0.25` V; range 0-1023.75 V
- **bcm_soc**: `uint8 * 0.5` %; range 0-127.5% (normal 0-100%, raw 0-200)
- **bcm_chg_max**: `uint12 * 0.25` A
- **bcm_dis_max**: `uint12 * 0.25` A
- **bcm_fgd**: `uint8 * 0.5` % (role unconfirmed; plist label only)
- **bcm_vbus_neg**: `uint12 * 0.25 - 500` V (range -500 to +523.75 V; 0 V at raw=2000)
- **0x0479 flow %**: `uint8 * 0.78125`; raw 0-128 maps to 0-100% (128 * 0.78125 = 100)

### FUN_00045af0 -- N-bit sign extension

VMA 0x45af0 (file offset 0x41AF0), Thumb-2. Disassembled 2026-03-27.

Signature: `int32_t FUN_00045af0(uint16_t val, uint32_t n_bits)`

Algorithm: `return (int32_t) sign_extend(val, n_bits)`
- Masks `val` to `n_bits` wide
- XORs bit `n_bits-1` to perform sign extension
- Equivalent to: flip bit 15, subtract 0x8000, sign-extend (= two's complement sign extension)

For `n = 0x10` (16, the only call site value): identical to `(int32_t)(int16_t)val`.

Used at all 5 call sites with `n=16`; result fed to `FixedToFP` then multiplied by a DAT constant.

Updated 0x0598 signal description: both ESS and Trac power signals are **offset-binary (excess-32768), zero at raw 0x8000** — corrected 2026-06-27 from an earlier "signed int16, zero at 0x0000" reading that the 0x598 raw-value check refuted (see above). Effective decode `(raw_u16 − 32768) × 0.01 kW`. Range: -327.68 to +327.67 kW. Positive = power discharged/produced.

### Extended ID signal decodings from ViaCANbusParser::parseEPRIMessage

All extended ID (29-bit) messages are handled in ViaCANbusParser::parseEPRIMessage
(VMA 0x25d00), NOT in ViaOBDParser. The buffer layout for extended IDs uses a 4-byte
CAN ID prefix: pbVar15[0:3] = 4-byte extended ID, pbVar15[4:11] = CAN B0..B7.

"INVCH" = Inverter/Charger -- the combined Bel Power Solutions unit.
"INVCH_Bdc" = Bidirectional DC (converter) -- the HV battery-side DC power stage within the
    Bel unit. Bidirectional: current flows inward (charging) or outward (discharging/export).
    Essentially the EPRI app's name for the Bel bidirectional charger/inverter core.
    Confirmed by: bCharging, bExporting, bGridTied flags and Ibat/Vbat signals all on Bdc.
"INVCH_Inv" = Inverter output sub-stage (DC->AC for grid export or onboard loads).
"INVCH_Chg" = Charger input sub-stage (AC->DC rectification when charging from grid).
"DCDC" = DC-DC step-down converter (0x18FFD6B3 only; separate device, not the Bel unit).

All multi-byte values in these messages are LE uint16 unless noted as signed.
Signed values use FUN_00045af0 (= two's complement int16 sign extension).

#### 0x18FFD4C0 -- INVCH_Bdc status/command (multi-page)

Fully decoded 2026-03-27. Dispatches on `switch(B0)` with cases 0-3. Format string per page:
`"INVCH_Bdc_F_W_S_MessageMode: %d <signals...>"`.

**Bel DBC cross-validation**: all byte/bit positions confirmed matching. Bel DBC is missing the
enum value labels for B5 on pages 0/1/2; the EPRI app is missing 3 fault flags on page 3
that the Bel DBC has (see below).

---
**Page 0 (B0=0)** -- main operating state + 4 boolean flags

Boolean flags (YES/NO):
| Signal | Byte | Bit mask |
|--------|------|---------|
| INV_Bdc_bCharging     | B2 | & 0x01 |
| INV_Bdc_bEVSEConnected | B1 | & 0x08 |
| INV_Bdc_bExporting    | B2 | & 0x08 |
| INV_Bdc_bGridTied     | B2 | & 0x10 |

**INVCH_Bdc_Signal_State** = B5 (raw byte), looked up in 29-entry dictionary:
(Bel DBC = BELINV_state, byte B5, raw range [0|255] -- enum labels not in DBC)

| Value | Label | Value | Label |
|-------|-------|-------|-------|
| 0  | INIT              | 13 | ENERGY_DISC_E      |
| 1  | WAKE_UP           | 14 | ERR                |
| 2  | VEH_CHARGE        | 15 | SHUTDOWN_CHARGER   |
| 3  | OTP               | 20 | CHRGR_SHTDOWN_1    |
| 4  | SLEEP             | 21 | CHRGR_SHTDOWN_2    |
| 5  | DELAYED_SLEEP     | 22 | CHRGR_SHTDOWN_3    |
| 6  | TEST              | 23 | CHRGR_SHTDOWN_4    |
| 7  | EXPORT            | 30 | EXP_INIT           |
| 8  | STANDBY           | 31 | EXP_DISABLED       |
| 9  | DEBUG             | 32 | EXP_ENERGY         |
| 10 | NOT_CONN_A        | 33 | EXP_SHTDOWN        |
| 11 | CONN_B            | 34 | EXP_ALCI           |
| 12 | ACCEPT_ENERGY_CD  | 40 | EXP_SHTDWN_1       |
|    |                   | 41 | EXP_SHTDWN_2       |
|    |                   | 42 | EXP_SHTDWN_3       |
|    |                   | 43 | EXP_SHTDWN_4       |

Sentinel: invalid state emits `"MessageID_0x18FFD4C0_InvalidINVCH_Bdc_Signal_State: %d"`.

---
**Page 1 (B0=1)** -- buck-boost state

**INVCH_Bdc_bBoost_St** = B5 (raw byte), 21-entry dictionary:
(Bel DBC = BELINV_buckBoostState, byte B5 -- enum labels not in DBC)

| Value | Label | Value | Label |
|-------|-------|-------|-------|
| 0  | FIRST_START   | 11 | DRIVER_FAULT    |
| 1  | IDDLE         | 12 | SHORTCIRCUIT    |
| 2  | UV_OV         | 13 | DCDC_SOFTSTART  |
| 3  | STARTUP       | 14 | BB_SOFTSTART    |
| 4  | RUNNING       | 15 | SOFTSTART       |
| 5  | LATCHED_FAULT1 | 16 | JUMP_BOOTLOADER |
| 6  | BUS_ERROR     | 17 | GOTO_SLEEP      |
| 7  | OTP           | 18 | BB_DEBUG        |
| 8  | DEBUG         | 19 | DC_DEBUG        |
| 9  | INIT          | 20 | WATCHDOG        |
| 10 | OVERLOAD      |    |                 |

Sentinel: invalid state emits `"MessageID_0x18FFD4C0_InvalidINVCH_Bdc_bBoost_St: %d"`.

---
**Page 2 (B0=2)** -- inverter state

**INVCH_Bdc_Inverter_St** = B5 (raw byte), 35-entry dictionary:
(Bel DBC = BELINV_inverterState, byte B5 -- enum labels not in DBC)

| Value | Label | Value | Label |
|-------|-------|-------|-------|
| 0  | FIRST_START          | 18 | PFC_DC_UV_OV          |
| 1  | IDDLE                | 19 | INV_DRIVER_SOFTSTART  |
| 2  | INV_UV_OV            | 20 | ALCI_ACTIVE           |
| 3  | INV_STARTUP          | 21 | INV_RELAY_START       |
| 4  | INV_RUNNING          | 22 | PFC_DEBUG             |
| 5  | LATCHED_FAULT        | 23 | PFC_DRIVER_SOFTSTART  |
| 6  | BUS_ERROR            | 24 | PFC_SOFTSTART         |
| 7  | OTP                  | 25 | PFC_RELAY_START       |
| 8  | INV_DEBUG            | 26 | PFC_RUNNING           |
| 9  | INIT                 | 27 | DC_DEBUG              |
| 10 | DRIVER_FAULT         | 28 | INV_DC_DEBUG          |
| 11 | OVERLOAD             | 29 | PFC_AC_UV_OV          |
| 12 | SHORTCIRCUIT         | 30 | WATCHDOG              |
| 13 | INV_SOFTSTART        | 31 | INV_DC_DEBUG_NO_PROT  |
| 14 | BB_SOFTSTART         | 32 | INV_ENABLE_N          |
| 15 | SOFTSTART            | 33 | PFC_ENABLE_N          |
| 16 | JUMP_BOOTLOADER      | 34 | INV_HICCUP            |
| 17 | GOTO_SLEEP           |    |                       |

Sentinel: invalid state emits `"MessageID_0x18FFD4C0_InvalidINVCH_Bdc_Inverter_St: %d"`.

---
**Page 3 (B0=3)** -- AC fault flags

All boolean (YES/NO). Source byte B1 and B2:

| Signal | Byte | Bit mask | In Bel DBC? |
|--------|------|---------|-------------|
| INV_Bdc_bACOk          | B1 | & 0x01 | yes (BELINV_acOk) |
| INV_Bdc_bACOV          | B1 | & 0x02 | yes (BELINV_acOverVoltage) |
| INV_Bdc_bACUV          | B1 | & 0x04 | yes (BELINV_acUnderVoltage) |
| INV_Bdc_bBatteryUV     | B1 | & 0x08 | yes (BELINV_systemBatteryUnderVoltage) |
| INV_Bdc_bHVBatteryOV   | B1 | & 0x10 | yes (BELINV_hvBatteryOverVoltage) |
| INV_Bdc_bHVBatteryUV   | B1 | & 0x20 | yes (BELINV_hvBatteryUnderVoltage) |
| INV_Bdc_bOTP           | B1 | & 0x40 | yes (BELINV_overTemperature) |
| INV_Bdc_bExportOverload | B1 | & 0x80 | yes (BELINV_exportOverLoad) |
| INV_Bdc_bInverterFault | B2 | & 0x01 | yes (BELINV_inverterFault) |
| INV_Bdc_bBBFault       | B2 | & 0x02 | yes (BELINV_buckBoostFault) |
| *(not decoded by app)* | B2 | & 0x08 | yes (BELINV_wakeOutputError) |
| *(not decoded by app)* | B2 | & 0x20 | yes (BELINV_underFrequency) |
| *(not decoded by app)* | B2 | & 0x40 | yes (BELINV_overFrequency) |

Note: 3 flags present in the Bel DBC (wakeOutputError, underFrequency, overFrequency) are
**not** decoded by the EPRI app. Bel DBC is the authoritative source for these.

---
**Additional: 0x18EFC000** -- INVCH_Bdc command/mode message (separate CAN ID, not in Bel DBC)

The EPRI app parses 0x18EFC000 in `ViaCANbusParser::parseEPRIMessage`. Dispatches on B0 (page):

- **Page 0** -- cmd_Enable + cmd_Mode:
  - `invch_Bdc_cmd_Enable` = B1 (0 = "Turn OFF output", nonzero = "Turn ON output")
  - `INVCH_Bdc_cmd_Mode` = B2, clamped to [0..4], index into 5-entry array:
    - [0] "Export Power Mode"
    - [1] "STBY"
    - [2] "Stand-By"
    - [3] "DEACTIVATION"
    - [4] "Invalid"
  - Log: `"INVCH_Bdc_SetpointMode: %d, invch_Bdc_cmd_Enable: %@, INVCH_Bdc_cmd_Mode: %@"`

- **Page 6** -- LED1_mode:
  - Also logs `SetpointMode` (B1 raw integer)
  - `INVCH_Bdc_LED1_mode` = B2, clamped to [0..3], index into 4-entry array:
    - [0] "OFF"
    - [1] "STBY"
    - [2] "FLASH"
    - [3] "DEACTIVATION"
  - Log: `"INVCH_Bdc_Setpoint Mode: %d, INVCH_Bdc_LED1_mode = %@"`

- **Page 7** -- LED2_mode (same array as Page 6):
  - Log: `"INVCH_Bdc_Setpoint Mode: %d, INVCH_Bdc_LED2_mode = %@"`

**How the arrays were decoded:** The string values for array elements [1] and [3] (shared
across both arrays) are loaded via VFP register halves (`in_register_00000384` = upper 32
bits of d16, `in_register_0000038c` = upper 32 bits of d17). These are live-in register
values set by the caller. Identification confirmed via the 9-entry OperationState array for
CAN 0x0053, which uses the same registers at positions [1]="STBY" and [3]="DEACTIVATION" in
a perfect alternating pattern: INIT/STBY/ACTIVATION/DEACTIVATION/OPERATIONAL/FAILURE/
SHTDWN/WAIT4COOLING/PWR_OFF_RDY. Binary is PIE (MH_PIE set); cfstring VMAs are patched by
dyld rebase at runtime and do not appear as raw 4-byte values in the on-disk binary.

#### 0x18FFD5C0 -- INVCH_Bdc temperature

Format: `"INVCH_Bdc_Temperature_Int: %.2f degC INVCH_Bdc_TempPercent: %d"`

- **INVCH_Bdc_Temperature_Int**: signed int16 LE(B4:B5) * 0.1 degC
  (via FUN_00045af0 + DAT_00029590 = 0.1)
- **INVCH_Bdc_TempPercent**: CAN B6 single byte, unsigned (%d)

#### 0x18FFD6B3 -- DCDC converter readings

Format: `"DCDChighvoltagevoltreading: %.2f V  DCDCunitinternaltemperature: %.2f degC
DCDClowvoltagecurrentreading: %.2f A  DCDClowvoltagevoltreading: %.2f V"`

Scale DAT_00027b18 = 0.05 for volt/current signals, DAT_00027b20 = 0.1 for temperature.

- **DCDClowvoltagevoltreading**: LE_uint16(B0:B1) * 0.05 V (12V side voltage)
- **DCDClowvoltagecurrentreading**: LE_uint16(B2:B3) * 0.05 A (12V side current)
- **DCDChighvoltagevoltreading**: LE_uint16(B4:B5) * 0.05 V (HV side voltage)
- **DCDCunitinternaltemperature**: signed int16 LE(B6:B7) * 0.1 degC
  (via FUN_00045af0; can be negative for cold starts)

#### 0x18FFD6C0 -- INVCH_Inv AC output signals

Format: `"INVCH_Inv_Iout1_RMS: %.2f A  INVCH_Inv_Iout2_RMS: %.2f A
INVCH_Inv_Vout1_RMS: %.2f V  INVCH_Inv_Vout2_RMS: %.2f V"`

All signals use DAT_00028950 = 0.05 scale.

- **INVCH_Inv_Iout1_RMS**: LE_uint16(B4:B5) * 0.05 A
- **INVCH_Inv_Iout2_RMS**: LE_uint16(B6:B7) * 0.05 A
- **INVCH_Inv_Vout1_RMS**: LE_uint16(B0:B1) * 0.05 V
- **INVCH_Inv_Vout2_RMS**: LE_uint16(B2:B3) * 0.05 V

#### 0x18FFD7C0 -- INVCH_Bdc battery and INVCH_Chg charger input signals

Format: `"INVCH_Bdc_Ibat: %.2f A  INVCH_Bdc_Vbat: %.2f V
INVCH_Chg_Iin_RMS: %.2f A  INVCH_Chg_Vin_RMS: %.2f V"`

All signals use DAT_00028d50 = 0.05 scale.

- **INVCH_Bdc_Vbat**: LE_uint16(B0:B1) * 0.05 V (HV bus voltage on BDC side)
- **INVCH_Bdc_Ibat**: signed int16 LE(B2:B3) * 0.05 A (bidirectional; + = charge, - = discharge)
- **INVCH_Chg_Vin_RMS**: LE_uint16(B4:B5) * 0.05 V (AC grid input voltage)
- **INVCH_Chg_Iin_RMS**: LE_uint16(B6:B7) * 0.05 A (AC grid input current)

#### 0x18FFD8C0 -- INVCH_Bdc 12V battery voltage

Format: `"INVCH_Bdc_12Vbat: %.1f volts"`

- **INVCH_Bdc_12Vbat**: LE_uint16(B0:B1) * 0.02 V (DAT_00026cf0 = 0.02)

### Remaining decompiled functions (bus infrastructure layer)

The 12 decompiled functions include 10 outside the two `parseEPRIMessage` methods. These were
not examined during the initial signal-extraction phase because the plist-based scan did not
require them. Examined 2026-03-27.

#### FileSourceBus::initWithBusType_ (VMA 0x37C28)

Initializes a `FileSourceBus` instance for a given vehicle type and bus number. Key findings:

**Multi-vehicle support** -- the app was built to support 7 vehicle configurations (see footnote
below). For the Via Vtrux (vehicle type 5): bus type 5 gets `ViaCANbusParser` + `ViaCANData.txt`;
bus type 6 gets `ViaOBDParser` + `ViaOBDData.txt` plus a `OBDIIParser` fallback.

**Read interval** -- `_readInterval` is initialized to `0x3FB9999999999A` (double 0.1 s). The
file-source playback timer fires at 10 Hz.

**Data loading** -- loads the vehicle's `.txt` data file from the app bundle using
`NSBundle pathForResource:ofType:`, reads it as a UTF-8 string, splits on newlines, converts each
line from hex via `dataFromHexString:`, and stores frames in `_testData`. Then schedules a
repeating `NSTimer` at the read interval calling `_readTestData:`.

#### EPRIViaOBDIIBus::configureModuleForNormalOperation_ (VMA 0x4EF2A)

Called when the GoPoint module finishes initialization (and on wake from sleep). Calls the class
method `[EPRIViaOBDIIBus ViaOBDFilters]` and pushes the result as the GoPoint's
`userFilterConfiguration`. This class method -- **not decompiled** -- is the actual source of
truth for the CAN ID pass-filter list sent to the hardware. It is not a plist.

#### EPRIViaOBDIIBus::busDataReceived_ (VMA 0x4F238)

Dual-parser dispatch: tries `viaOBDParser` first; if it returns false (message not recognized),
falls through to `obdParser` (the generic `OBDIIParser`). The app silently handles standard
OBD-II PIDs alongside Via-specific messages on the same bus, with no plist entry required for
the generic path.

#### EPRIViaOBDIIBus::moduleDidCompleteInitialization_ (VMA 0x4F290)

Calls `configureModuleForNormalOperation_`. Source path baked into the binary:
`/Users/andersmelen/Documents/Repositories/epri-logger-app-2.0/CANbusLoggerXCode/CANbusLogger/BusClasses/EPRIViaOBDIIBus.m`
Developer: **Anders Melen**. Repository name: `epri-logger-app-2.0`.

#### EPRIViaOBDIIBus::moduleDidWakeFromSleep_ (VMA 0x4F364)

Calls `configureModuleForNormalOperation_` on wake, resetting the GoPoint filters.

#### EPRIViaOBDIIBus::flowControlFiltersWereSetOnModule_ (VMA 0x4F374)

After flow-control filters are pushed, calls `setPhysicalBusTypeTo: 1` on the module.

#### EPRIViaOBDIIBus::physicalBusTypeWasSetOnModule_ (VMA 0x4F388)

When physical bus type == 1, resets `VINRequestAttemptCount` to 0 on the current vehicle object
and calls `sendVINRequest`. The app actively polls the vehicle VIN from the OBD bus during
module initialization.

#### FileSourceBus::setViaCANbusParser_ / setViaOBDParser_ (VMA 0x0C / 0x25)

Trivial ObjC property setters for the two parser ivar slots. No logic.

#### EPRIViaOBDIIBus::_cxx_destruct (VMA 0x4F4B8)

ObjC ARC destructor; releases the `viaOBDParser` ivar. No logic.

---

**Footnote -- other vehicle platforms (out of scope)**

`FileSourceBus::initWithBusType_` reveals the app was deployed across a multi-vehicle EPRI
fleet study, not just Via Vtrux. All vehicle parsers are compiled into the binary; none except
the Via parsers were decompiled.

| Type | Vehicle | Parsers |
|------|---------|---------|
| 1 | Chevy Volt | VoltHVMParser (bus 7), VoltOBDParser (bus 3) |
| 2 | Nissan Leaf | LeafCARbusParser, LeafEVbusParser (bus 2) |
| 3 | Toyota Prius | data file only; no dedicated parser allocated |
| 4 | Odyne Systems PHEV truck | J1939Parser (bus 1), OdyneHCUParser (bus 4) |
| 5 | Via Motors Vtrux | ViaCANbusParser (bus 5), ViaOBDParser (bus 6) |
| 6 | Generic OBD-II | OBDIIParser |
| 7 | Generic J1939 | J1939Parser |

Odyne Systems produced plug-in hybrid medium-duty utility trucks (bucket trucks, etc.) and was
an EPRI/DOE partner in the same vehicle electrification programs as Via Motors. Their decoder
uses J1939 + a proprietary HCU parser, suggesting a different CAN architecture from the Via GM
platform.

---
