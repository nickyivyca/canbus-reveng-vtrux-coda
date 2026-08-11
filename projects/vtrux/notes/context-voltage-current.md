# Voltage & Current Signal Investigation

## Objective
Find and confirm all HV DC link voltage and current signals on the powertrain bus, using the Bel charger as ground truth where possible.

**Signal catalog (confirmed signals):** See `powertrain-messages.md`. This file tracks the investigation methodology, candidates under evaluation, and scan results.

---

## ECU Inventory — Potential Voltage Sources

| ECU | Role | ID Type | Known IDs |
|-----|------|---------|-----------|
| Bel Charger | AC→DC HV charging | Extended (0x18FF??C0) | 0x18FFD7C0 (decoded), 0x18FFD4C0, 0x18EFC000 |
| Bel DCDC | HV→12V conversion | Extended (0x18FF??B3) | 0x18FFD6B3 (confirmed), 0x18FFD4B3, 0x18EFB3FE, 0x18FECAB3, 0x18FF0320 |
| TRAC MCU (Traction Inverter) | Traction motor | Standard | **OBD bus** (native). Confirmed IDs in `epri-obd-bus.dbc` (e.g. `TRAC_HighPwr_Volt` 0x0462). `0x5A2` is a VCM rebroadcast on PT bus, not a native Remy ID. |
| Generator Inverter | Engine-coupled gen | Standard | ~0x051 torque cmd; unknown for voltage |
| A123 BMS | Battery management | Standard | 0x596–0x640 cluster |
| AC-Compressor (MI-EV36-BNKx) | HVAC | Extended | 0x0870A047 (`EAC_CompHVInput` B2, uint8 x4 V — in `vtrux-powertrain-experimental.dbc`) |
| Via VCM | Vehicle controller/gateway | Standard | Various |

**Key encoding hint from Bel devices:** LE signed int16 × 0.05 V/A for all analog signals; LE signed int16 × 0.1 for temperature. Same encoding confirmed across source addresses 0xC0 (charger) and 0xB3 (DCDC).

**Warning — cross-byte decoding artifact:** Decoding non-aligned byte pairs (e.g. B3-B4 spanning two DBC signals) can produce plausible-looking voltage values from temperature data. Always verify against DBC signal boundaries before recording as new. `0x18FFD5C0` is the overallTemperature message (×0.1°C), NOT an AC voltage signal.

---

## Ground Truth

### Charger: `0x18FFD7C0`
- `hvBatteryVoltage`: B0-B1, LE signed ×0.05 → Volts (full decode in `BelInverter-v2.dbc`)
- `hvBatteryCurrent`: B2-B3, LE signed ×0.05 → Amps
- `chargerInputVoltage`: B4-B5, LE signed ×0.05 → Volts (~207V AC RMS in logs)
- Available only in charging logs. Standard-frame IDs (BMS cluster, drive inverter PT bus IDs) absent from early charge logs — those captures used extended-ID-only filter configurations.

### DCDC: `0x18FFD6B3` B4-B5
- LE signed ×0.05, tracks HV bus. **Confirmed r=0.993 against charger GT** (full charge then fail log, 380–422V arc).
- Reads ~5.5V lower than charger (calibration offset, not resistive drop). Near-constant within sessions (mae ~= |bias|). See DCDC offset investigation section below for multi-log analysis.
- Full byte layout: B0-B1 = 12V setpoint, B2-B3 = 12V output current, B4-B5 = HV input voltage, B6-B7 = 12V measured output.

---

## Confirmed HV Voltage Signals

All confirmed. No pre-contactor pack terminal voltage exists on CAN — the BMS does not broadcast it (see interlock test conclusions below).

| CAN ID | Bus | Signal | Encoding | Measurement point | Source |
|--------|-----|--------|----------|-------------------|--------|
| `0x18FFD7C0` B0-B1 | PT | Charger `hvBatteryVoltage` | LE signed x0.05 V | Post-contactor (charger DC terminals) | Bel charger. **Ground truth for charging logs.** Charging only. |
| `0x18FFD6B3` B4-B5 | PT | DCDC `DCDC_HV_Volt` | LE signed x0.05 V; reads ~5.5V low vs charger GT (calibration offset, near-constant within sessions; see DCDC offset investigation below) | Post-contactor (DCDC HV input) | Bel DCDC. Active during driving and charging. |
| `0x0482` B1-B2 | PT | `GENE_HighPwr_Volt` | 11-bit Intel LE, startbit=8, 1 V/count | Post-contactor (GENE MCU DC bus) | GENE MCU. EPRI-confirmed. In `epri-pt-bus.dbc`. |
| `0x0470` B1-B2 | PT | `hv_bus_volt_470` | 11-bit Intel LE, startbit=8, 1 V/count (encoding assumed symmetric with 0x482) | Post-contactor | Unknown ECU, most likely GENE MCU (drops at same time, adjacent ID range). Not in EPRI DBC. In `vtrux-powertrain-experimental.dbc`. |
| `0x0462` B1-B2 | OBD | `TRAC_HighPwr_Volt` | 11-bit Intel LE, startbit=8, 1 V/count | Post-contactor (TRAC MCU DC bus) | TRAC MCU. EPRI-confirmed. In `epri-obd-bus.dbc`. **OBD bus only.** |
| `0x0870A047` B2 | PT | `EAC_CompHVInput` | uint8 x4 V/count | Post-contactor (EAC HV input) | Sanden EAC compressor. In `vtrux-powertrain-experimental.dbc`. |
| `0x0410` B0-B1 | PT | `bcm_vbat` | 12-bit Motorola, startbit=3, x0.25 V | BMS-internal rail (pre/post-contactor behavior uncharacterized — byte position not in interlock sweep) | A123 BMS. EPRI-confirmed. In `epri-pt-bus.dbc`. |
| `0x0440` B4-B5 | PT | `bcm_vbus_pos` | 12-bit Motorola, startbit=39, x0.25 V | BMS-internal rail (pre/post-contactor behavior uncharacterized) | A123 BMS. EPRI-confirmed. In `epri-pt-bus.dbc`. |
| `0x0440` B5-B6 | PT | `bcm_vbus_neg` | 12-bit Motorola, startbit=43, x0.25 V, -500V offset | BMS-internal rail (pre/post-contactor behavior uncharacterized) | A123 BMS. EPRI-confirmed. In `epri-pt-bus.dbc`. |

---

## Correlation Scan Results

> **EPRI-confirmed signals** (GENE_HighPwr_Volt 0x482, bcm_vbat 0x410 B0-B1, bcm_vbus_pos/neg 0x440 B4-B6, bcm_ibat 0x410 B4-B5) were identified via these correlation scans and are now fully characterized in `epri-pt-bus.dbc`. Investigation records for those signals have been removed.

### Method
- **Charging logs:** Correlate against `0x18FFD7C0` B0-B1 (charger GT). Filter: V≥350V (excludes pre-contact and startup disconnects), t≤7242s (excludes the voltage-collapse failure event).
- **Drive logs:** Correlate against `0x18FFD6B3` B4-B5 (DCDC HV input). Filter: V≥300V.
- Scripts use nearest-match pairing (max_dt=0.15–0.20s), Pearson r, linear fit for scale/offset.
- **Monotonic artifact warning:** Sessions where voltage changes monotonically (long CC→CV arc, or steady drive discharge) will produce spurious high-r results for any signal that drifts in the same direction. Cross-validate between charge and drive modes.

---

### Charge Log Scan (`logs/full charge then fail.log`, 380–422V arc)

72,128 charger GT samples; 714 candidate byte-pair streams; threshold r>0.60.

**Candidates requiring further investigation:**

| CAN ID | Bytes | r | Decoded Range | Notes |
|--------|-------|---|---------------|-------|
| `0x412` | B4-B5 LE/BE | −0.946 | 391→425V inverted | Negative r across multiple byte pairs — likely current (tapers as V rises in CV phase) |
| `0x505` | B0-B1 LE/BE | +0.908 | 396→417V | Near-zero raw during CC, rises through CV — possibly energy counter or SoC proxy |
| `0x646` | B4-B5 LE | +0.885 | 385→418V | |
| `0x649` | B0-B1 BE | +0.888 | 386→417V | Same region as 0x646 |
| `0x411` | B0-B1 BE | +0.821 | 379→411V | Adjacent to 0x410; also appears in drive scan |

**Discarded from charge log:**

| CAN ID | Reason |
|--------|--------|
| `0x430` | Spurious session correlation — see below |

---

### Drive Log Scan (`debuglog_M0_T2_short`, `_T7`, `_T0_half`; DCDC as reference)

1,175 DCDC samples; 334–394V range (59V spread); threshold r>0.70.

**New candidates (not in charge scan or stronger here):**

| CAN ID | Bytes | r | Scale | Decoded Range | Notes |
|--------|-------|---|-------|---------------|-------|
| `0x470` | B0-B1 LE / B1-B2 BE | +0.9698 | ~0.00387 V/count | 258→493V | Same encoding as GENE_HighPwr_Volt (0x482, EPRI-confirmed). 0x470–0x484 is GMLAN mirror cluster (+0x30 from 0x440–0x454). Not in EPRI DBC. In `vtrux-powertrain-experimental.dbc`. |
| `0x597` | B1-B2/B2-B3 | −0.888 | ~−0.0029 V/count | 358→395V inverted | **Negative r — likely current.** Adjacent to 0x596 (SoC). See current candidates below. |
| `0x598` | B0-B1 BE | −0.830 | ~−0.00377 | 366→391V inverted | EPRI-confirmed as `DBL_ESSPwrAvg` (battery power average), 0.01 kW/count centered at 32768. Negative r vs voltage is consistent: more discharge power → lower voltage. |

---

### 0x430 — Discarded as Voltage Candidate

`analyze_id.py` on `full charge then fail.log` and correlation in drive logs both show high r, but:

- **Mode-dependent raw values:** B0-B1 BE ≈ 36,096–36,351 during charging (B0=0x8D, bit 7 set), but ≈ 3,100–3,600 during driving (B0=0x0C/0x0D). Same pack voltage (~392V), factor ~10 difference in raw value → no consistent voltage encoding.
- **Explanation:** 0x430 is the A123 BMS cell data message — `bcm_cell_vmax`, `bcm_cell_vmin` (13-bit Motorola, 1 mV/count), cell temps, and status flags. EPRI-confirmed in `epri-pt-bus.dbc`. The mode-dependent B0 values are the mux/status byte switching between operational states, not a voltage encoding.
- **Status:** Not a pack voltage signal.

---

## Current Signal Candidates

Signals with **negative r** vs voltage in the drive-log scan are consistent with current (more current = lower voltage in LFP flat region under load):

| CAN ID | Bytes | r vs DCDC V | Notes |
|--------|-------|-------------|-------|
| `0x597` | B1-B2/B2-B3 | −0.888 | Adjacent to 0x596 SoC — BMS cluster |
| `0x598` | B0-B1 BE | −0.830 | EPRI-confirmed **power** (`DBL_ESSPwrAvg`), not current. Appears here because discharge power anticorrelates with voltage. |
| `0x412` | B4-B5 | −0.946 (charge log) | Consistent negative r; tapers with voltage in CV phase |

`bcm_ibat` (0x410 B4-B5, 16-bit BE, raw × 0.025 − 1000 A) was found via correlation in this scan and is now EPRI-confirmed in `epri-pt-bus.dbc`.

---

---

## 0x598 Source Investigation — BMS Sweep Result and Current Hypothesis

### BMS sweep result (2026-03-05)

All confirmed BMS-tier IDs (`0x370–0x375, 0x400, 0x410, 0x411, 0x412, 0x420, 0x430,
0x440, 0x460, 0x506, 0x507` — complete set from LV connector dropout test) were swept
against all three 0x598 channels (battery B0-B1, generator B2-B3, drivetrain B4-B5)
using delta correlation and multi-window Pearson on `vtruxcurrentlimitingtest.log`.

**Result: zero confirmed candidates for any channel.** All Pass B survivors were
voltage-under-load signals (V=IR), high-res SoC (0x411 B0-B1), or sign-inconsistent
thermal/SoC drift. Script: `artifacts/bms_current_source_sweep.py`; output:
`artifacts/bms_current_source_sweep.txt`; plot: `artifacts/bms_current_candidates_plot.png`.

### Resolution

All three channels are EPRI-confirmed **power** (0.01 kW/count, unsigned centered at 32768) in `epri-pt-bus.dbc`:
- **B0-B1** `ess_power` (was `DBL_ESSPwrAvg`) — battery power average (VCU-computed, not a direct sensor)
- **B2-B3** `gen_power` — generator power; scale confirmed 2026-03-29 vs T*omega
- **B4-B5** `trac_power` (was `DBL_TracPwrAvg`) — traction power average

---

## Rejected Candidates (Pack Voltage)

These have been specifically investigated and rejected:

| CAN ID | Bytes | Why Rejected |
|--------|-------|--------------|
| `0x480` B1-B2 | BE /10 | ~383.8V but too flat/filtered; does not respond to load |
| `0x595` B0-B1 | BE /10 | ~400.7V, ~9V high; likely inverter DC-link rail, not pack terminal |
| `0x644` B2-B3 | LE ×1 | ~384V, ~8V below GT during CC; different measurement point |
| `0x63A` B0-B1 | LE /100 | ~388.9V, ~3V low; more likely cell min/max extremes |
| `0x600` B5-B6 | LE /10 | ~384V but constant in EV mode — not pack terminal |
| `0x420` B0-B1 | BE /100 | Was a candidate early on: 391.72V physically plausible (3.348 V/cell x 117 LFP), goes to all-zeros on contactor open, transitions from 0xFF.. to data on HV activation. Interlock test confirmed POST_CONTACTOR (drops on both HVAC pull and HVD pull). However: constant 39172 during highway driving with 35V DCDC variation — NOT a dynamic voltage measurement. Likely a latched/frozen value or setpoint. |
| `0x440` B3-B4 LE | POST_CONTACTOR (interlock), flat during drive | Interlock test gave r=0.9818 vs DCDC and POST_CONTACTOR classification, initially suggesting a third voltage source. Drive-log analysis (`vtruxevapdrivelog4part2.log`, 2026-03-06) shows flat ~372V constant throughout all load-induced sag events; r=0.30 full-log. Spikes opposite direction at key-off while DCDC crashes. Same latched/setpoint behaviour as 0x420. Script: `artifacts/plot_hv_voltage_comparison.py`; plot: `artifacts/hv_voltage_comparison.png`. |
| `0x430` | — | Multiplexed; mode-dependent raw values; not voltage (see above) |

---

## Log Inventory for Correlation Work

| Log | Type | Notes |
|-----|------|-------|
| `logs/full-charge-then-fail.log` | Dual (56 std + 27 ext) | 123 min; 380→422V; best charge-log candidate — both charger GT and vehicle IDs |
| `logs/other-logs/truklog_M0_T11..T24` | Charger-only ext | Full CC→CV (390→422V); no vehicle IDs; useful for extended-ID candidates only |
| `logs/other-logs/truklog_M0_T8` | Dual | Steady CC at ~391V; used for initial 0x420 comparison — 0x420 B0-B1 constant (39172) during AC charging, message present but value does not track voltage; used to confirm 0x420 is not a dynamic measurement. 0x420 since rejected as voltage candidate. |
| `logs/debuglog_M0_T2_short.log` | Drive | 48s highway deceleration; DCDC active |
| `logs/debuglog_M0_T7.log` | Drive | End-of-drive, low speed, EV mode; DCDC active |
| `logs/debuglog_M0_T0_half.log` | Drive | Startup sequence; DCDC active |
| `logs/vtruxinterlocktest.log` | Interlock test | 330s; HVAC pull, HVD pull, 12V disconnect cycle; 3-bus capture; used for voltage classification |

---

## Per-ECU Investigation Notes

### Remy Drive Inverter (TRAC MCU — OBD bus)

Native IDs are on the OBD bus; confirmed in `epri-obd-bus.dbc` (e.g. `TRAC_HighPwr_Volt` 0x0462). `0x5A2` is the VCM's PT-bus rebroadcast of traction motor data, not a native Remy ID.

PT-bus IDs that were investigated and rejected as voltage signals:
- `0x420` B0-B1 — see Rejected Candidates above
- `0x480` B1-B2 — too flat/filtered; see Rejected Candidates
- `0x595` B0-B1 — likely inverter internal DC-link rail; see Rejected Candidates

### Generator Inverter (GENE MCU — PT bus)

Confirmed IDs in `epri-pt-bus.dbc`. `GENE_HighPwr_Volt` (0x0482) is the confirmed HV voltage signal. `0x470` (same encoding, adjacent ID) is in `vtrux-powertrain-experimental.dbc`.

- `0x051` is confirmed generator torque command; `0x053` B0-B1 has generator active/off status bits.

### A123 BMS Cluster

- BMS standard-frame IDs absent from early charge logs — those captures used extended-ID-only filter configurations
- `0x63A` has cell min/max/delta (useful for cell health, not pack voltage directly)
- `0x640` B1 is NOT SoC — may be pack average temperature or pack status

**Hypotheses to test:**
- Does the BMS broadcast pack terminal voltage anywhere in the `0x596`–`0x640` cluster?
  - `0x640` B2-B7: unknown
  - `0x63D` B0-B7: fault flags + other unknowns
- Cell min/max decode in `0x63A`: what scaling for individual cell voltage? (~3.0–3.6V range expected)

### AC-Compressor (Sanden MI-EV36-BNKx)

- `0x0870A047` B2: `EAC_CompHVInput`, uint8 × 4 V/count — HV input voltage. In `vtrux-powertrain-experimental.dbc`.

---

## Investigation Methodology — Voltage Screening

### Scale Factor Reference

| Scale (V/count) | Raw range for 360–422V |
|-----------------|------------------------|
| ×0.05           | 7200–8440              |
| ×0.1            | 3600–4220              |
| ×1.0            | 360–422                |
| /100 (×0.01)    | 36000–42200            |

### Steps

1. **Review pre-computed surveys** (`artifacts/generator-survey.json`, `artifacts/driveway-survey.json`) — screen all byte pairs for raw ranges consistent with DC link voltage at candidate scale factors above.
2. **Correlate against charger GT** — run on charging logs, threshold r > 0.60; focus on extended IDs.
3. **Drive log analysis** — for IDs not captured in early charge logs (drive inverter, BMS standard frames), correlate against DCDC HV input reference.
4. **Deep dive shortlisted IDs** — `analyze_id.py` + `extract_timeseries.py` on candidates.

---

## Interlock Disconnection Test (2026-02-24)

### Method

Used `logs/vtruxinterlocktest.log` (103 MB, 330s, 3-bus capture) with known HV disconnection events to classify signals by measurement point. The test sequence creates natural step functions:

1. Key on (contactors close, all HV live)
2. **HVAC HV connector pull** (~63s) — opens interlock loop, contactors open, truck faults
3. Plug/unplug HVAC connector (contactors stay open due to fault)
4. Key off, key on (still faulted)
5. **12V battery disconnect/reconnect** (~175-211s) — clears fault; all ECUs lose power during disconnect (no CAN traffic in gap)
6. Key on (~211s) — contactors close, all HV restored
7. **HVD pull** (~241s) — all HV drops, including pre-contactor
8. HVD reconnect (truck faulted, contactors stay open)

**Classification windows:**
- HV live: 15-55s, 215-235s (~387V on DCDC)
- Post-HVAC-pull (contactors open, HVD still in): 100-170s
- Post-HVD-pull (all HV disconnected): 270-310s

**Scripts:** `artifacts/interlock_voltage_sweep.py` (single-pass extraction + classification), `artifacts/interlock_drive_crossval.py` (driving-log correlation cross-check)

### Results — Voltage Signal Classification

| Signal | Interlock Class | Drive r vs DCDC | Live Value | Post-HVAC | Post-HVD |
|--------|----------------|-----------------|------------|-----------|----------|
| **DCDC B4-B5** (x0.05) | POST_CONTACTOR | (reference) | 387.0V | 7.5V | 8.0V |
| **0x482 B1-B2 LE** | POST_CONTACTOR | **+0.9974** | 387 (int V) | ~3 | ~3 |
| **0x470 B1-B2 LE** | POST_CONTACTOR | **+0.9974** | 387 (int V) | ~3 | ~3 |
| ~~0x440 B3-B4 LE~~ | POST_CONTACTOR | **+0.3032** (flat) | 24788 | 1161 | 720 |
| 0x420 B0-B1 BE | POST_CONTACTOR | N/A (flat 39172) | 39169 | 108 | 0 |
| 0x505 B0-B1 | NON_VOLTAGE | N/A (flat 150) | 150 | 150 | 150 |
| 0x646 B4-B5 | NON_VOLTAGE | N/A (flat) | 41576 | 41576 | 41576 |
| 0x649 B0-B1 | NON_VOLTAGE | N/A (flat) | 42413 | 42420 | 42416 |
| 0x411 B0-B1 | NON_VOLTAGE | -- | 38337 | 38191 | 38320 |
| 0x410 B2-B3 | NON_VOLTAGE | -- | 49338 | 49224 | 49406 |
| 0x440 B1-B2 | NON_VOLTAGE | -- | 39934 | 39934 | 39934 |
| 0x480 B1-B2 | NON_VOLTAGE | -- | 3838 | 3838 | 3838 |
| 0x595 B0-B1 | NON_VOLTAGE | -- | 4007 | 4007 | 4007 |
| 0x412 B4-B5 | NO_SIGNAL | -- | 0 | 0 | 0 |
| BMS cluster (0x639-0x640, 0x596) | NO_SIGNAL / NON_VOLTAGE | -- | -- | -- | -- |

### Results — Broad Sweep Discoveries

108 byte pairs flagged with >50% step response (105 new beyond specific candidates).

**New POST_CONTACTOR IDs:** 0x050 (multiple bytes), 0x053 (multiple bytes), 0x412 B0-B1, 0x460 (multiple bytes), 0x471 (multiple bytes), 0x507 B5-B6.

**No clean PRE_CONTACTOR voltage found.** Some signals (0x64A, 0x619) showed partial pre-contactor patterns but with inconsistent values across the 12V reset — likely BMS state bytes, not voltage.

### Results — ECU Presence Analysis

Almost nothing goes offline when HV is disconnected:
- Bus 1 (OBD): 46/52 IDs always present (88%)
- Bus 2 (Powertrain): 70/93 IDs always present (75%)
- Bus 3 (Vehicle): 57/59 always present (97%)

**Only ID that requires HV/contactor state:** `0x18FECAB3` (Bel DCDC, extended) — present only when contactors are closed. Likely a DCDC enable/control message.

**Fault-only messages** (appear ONLY after truck enters fault state, absent during normal operation):
- 0x473, 0x474, 0x478 (Bus 2) — GMLAN mirror cluster fault-condition rebroadcasts
- 0x445, 0x449 (Bus 1) — DTC-related
- 0x1CEBFFB3, 0x1CECFFB3 (Bus 2) — J1939 TP from Bel DCDC (multi-frame diagnostic data during fault)

**12V disconnect gap (175-210s):** All ECUs lose power when 12V battery is disconnected, so all CAN traffic stops. Traffic resumes on 12V reconnection.

**BMS keeps broadcasting at full rate through all HV events** — the lack of pre-contactor voltage is not because the BMS goes offline; it genuinely does not report pack terminal voltage on this CAN bus.

### Key Conclusions

1. **0x482 and 0x470 are confirmed POST-contactor voltage** — they track the DC bus after the contactors, not the battery pack's internal measurement. Encoding: B1-B2 LE = integer volts (1 V/count, uint16). B0 is fractional. Confirmed against DCDC reference in `vtruxevapdrivelog4part2.log` (r=0.9974, traces overlap perfectly).
2. **0x440 B3-B4 LE** — **REJECTED as real-time voltage** (2026-03-06). Interlock test classified it POST_CONTACTOR, but drive-log analysis in `vtruxevapdrivelog4part2.log` shows it is essentially flat (~372V constant) throughout all load-induced sag events visible in 0x482/0x470/DCDC (r=0.30 drive log). Spikes upward at key-off while DCDC crashes to zero — opposite direction. Same behaviour as 0x420. Likely a latched value or setpoint. See Rejected Candidates.
3. **0x420** is confirmed HV-related (drops to 0 when contactors open) but is NOT a dynamic measurement — constant 39172 during highway driving with 35V DCDC variation. Likely a latched/frozen value or setpoint.
4. **No pre-contactor pack voltage signal exists** on the powertrain bus. The A123 BMS does not broadcast pack terminal voltage via CAN.
5. **Charge-log candidates 0x505, 0x646, 0x649, 0x411, 0x410 B2-B3** are definitively NOT voltage — zero response to HV disconnection. Their charge-log correlation was a monotonic artifact.
6. **0x18FECAB3** is a DCDC enable/control message — only present when contactors are closed.

---

## What Has Been Tried

1. **Pearson correlation on charge logs** — worked for DCDC B4-B5 (r=0.993); charge log had to span CC->CV (not just flat CC) for meaningful variance.
2. **Direct byte decode on `chargelog_M0.log`** — too little voltage variance (4.85V) for correlation; used direct LE signed x0.05 decode instead to find DCDC signals.
3. **DBC cross-reference** — caught the `0x18FFD5C0` temperature misidentification (decoded as "AC voltage 320-358V" — actually temperature x0.1 C). Always cross-check non-DBC extended IDs against `BelInverter.dbc` before recording.
4. **Drive log sweep against DCDC reference** — confirmed DCDC is a usable ground truth in drive mode; found 0x482/0x470 as top new candidates.
5. **0x430 multi-mode analysis** — charge log r=0.993 revealed as spurious; drive log confirmed multiplexed behavior.
6. **Interlock disconnection test** (2026-02-24) — definitive classification of all voltage candidates by measurement point. Confirmed 0x482/0x470/0x440 as post-contactor voltage. Eliminated 0x505, 0x646, 0x649, 0x411, 0x410 as false positives from charge-log correlation. Confirmed no pre-contactor voltage on the CAN bus. Identified fault-only messages and DCDC enable signal.

---

## 0x598 -- Balance Equation Hypothesis (2026-03-05)

### Background

The PT-bus-only inverter current sweep (bus 2 filter, gen-discriminant Pass B, script:
`artifacts/inverter_current_sweep.py`) found no high-confidence single-source candidate
for 0x598 B2-B3 (generator) or B4-B5 (drivetrain). Many IDs correlated well in gen-ON
windows but none was clearly a direct physical current sensor feed.

Two observations in `vtruxevapdrivelog4.log` motivate a different model:

1. **Pre-generator oscillations:** 0x598 B2-B3 ("generator current") shows significant
   oscillations during the EV-only section (t < 431.7s) when the generator is completely
   off. A physical generator current sensor would read near-zero. However, drivetrain
   current (B4-B5) varies substantially as the traction motor accelerates and regenerates.

2. **~1350s spike:** An anomalous spike in 0x598 B2-B3 is not matched by corresponding
   jumps in generator RPM or generator torque command, but may correspond to a drivetrain
   current transient.

3. **PTC heater invisibility:** The HV PTC heater is a significant battery load but leaves
   no trace in 0x598. If 0x598 encoded actual measured currents for each branch, the heater
   load should appear in the battery channel at minimum.

### Hypothesis: generator current is a computed residual, not a direct measurement

The VCU may be using a balance equation:

    P_battery = P_drivetrain + P_generator  (or current equivalent)

If it holds two of the three from direct measurements (e.g. drivetrain from Remy inverter
feedback, battery from a slow/filtered SoC-based estimate), the third is back-calculated:

    P_generator = P_battery - P_drivetrain

This would explain all three observations:

- **Pre-generator oscillations:** Fast drivetrain current transients (e.g. torque command
  snapping from 50% to 0%) are not matched instantaneously by the battery estimate if the
  battery channel uses a filtered or SoC-derived value. The unmatched residual shows up
  as fake generator current even when the generator is off.

- **~1350s spike:** A fast drivetrain transient creates a momentary mismatch. The filter
  lag in the battery estimate temporarily attributes the imbalance to the generator channel.

- **PTC heater invisibility:** The heater is a battery load that is not part of the
  drivetrain-generator balance. If the VCU only tracks the drivetrain and generator
  branches, the heater load either appears in the battery channel (if that is a direct
  measurement) or disappears entirely (if the battery channel is itself derived from the
  same balance). Either way, it need not appear in the generator or drivetrain channels.

### Key diagnostic tests

1. **Balance check:** Does B0-B1 + B2-B3 + B4-B5 sum to near-zero at all times? (With
   appropriate sign conventions.) If the three channels always sum to zero or a constant
   offset, the balance equation is confirmed and at least one channel is derived.

2. **Transient lag check:** At drivetrain torque step events, does the generator channel
   spike with a small time delay relative to the drivetrain channel? A lag consistent with
   a filter time constant would confirm the residual hypothesis.

3. **Drivetrain torque correlation at pre-generator oscillations:** Do the oscillations in
   B2-B3 before t=431.7s exactly mirror fast changes in the drivetrain channel (B4-B5)?
   If yes, they are the same event seen from the residual.

4. **SoC comparison:** Is the battery channel (B0-B1) more consistent with a slow SoC
   derivative than with a direct current sensor? A direct sensor would track fast
   transients; an SoC derivative would be smoother.

### Results (2026-03-05)

Script: `artifacts/power_torque_fit.py`; plot: `artifacts/power_torque_fit_plot.png`

**Generator channel (0x598 B2-B3): r = +0.998 vs (-gen_torque x gen_RPM)**
The fit is essentially perfect during gen-ON windows. 0x598 B2-B3 is consistent with
mechanical power computed by the VCU from 0x051 B1-B2 (generator torque command,
negated) x 0x63C B5-B6 (generator RPM). This is not a measured current.

Caveat: the pre-generator oscillations in 0x598 B2-B3 (t < 431.7s) are NOT explained
by this model. With RPM=0 before the generator starts, the T*RPM product is identically
zero regardless of the torque command. The fit correctly predicts zero in this window,
but the measured signal shows real oscillations. The source of these pre-generator
oscillations remains unexplained -- the balance-equation hypothesis (generator channel
as a residual of battery minus drivetrain) remains a candidate for this window.

**Drivetrain channel (0x598 B4-B5): r = +0.850 vs (drv_torque x drv_RPM)**
The fit is good but not tight. The 0x598 B4-B5 signal appears filtered or delayed
relative to the 0x5A2 B4-B5 x 0x5A2 B2-B3 estimate -- the fit line is faster and
sharper than the measured channel. The VCU likely applies a low-pass filter, or uses
a different (pre-filtered) torque/speed source. The large intercept (766 counts)
suggests a calibration offset or a constant auxiliary load folded into the channel.

**Implication for battery current source search:**
0x598 is a VCU-computed power bundle, not physical current measurements. The battery
channel (0x598 B0-B1) source is still unknown.

**Threshold note for future correlation sweeps:** The drivetrain channel shows r=0.850
with its own confirmed T*omega basis due to filtering. Any sweep targeting 0x598 B0-B1
must use a loose threshold (|r| >= 0.70 or lower) to avoid missing signals that are
related but smoothed.

**Pre-generator oscillations follow-up (2026-03-06):**

Script: `artifacts/plot_598_pregen_zoom.py`; plot: `artifacts/598_pregen_zoom_plot.png`

Zoomed into t=50-431s. Key stats:
  batt (B0-B1): min=-5228  max=+7275  mean=+1970
  gen  (B2-B3): min=-118   max=+139   mean=-0.2
  drv  (B4-B5): min=-5728  max=+6976  mean=+1697

The generator channel is tiny (+-120 counts) relative to battery and drivetrain
(+-6000 counts). Battery and drivetrain track each other closely during the pre-
generator window -- batt ~= drv, so batt - drv ~= 0, which is consistent with
gen ~= 0. The balance residual hypothesis does not explain the oscillations because
the residual itself (batt - drv) is nearly zero and would not produce the observed
gen oscillations.

The pre-generator gen oscillations are likely just quantization noise or a small
steady-state signal (e.g. idle torque command from the generator inverter at zero
speed). No conclusive mechanism was found.

### Status: resolved by EPRI

- All three channels confirmed as VCU-computed power in `epri-pt-bus.dbc` (see Resolution above).
- Generator channel (B2-B3): r=0.998 vs T*omega confirmed. Pre-generator oscillations (+-120 counts vs +-6000 for battery/drivetrain) are quantization noise or idle inverter commands — negligible.
- Drivetrain channel (B4-B5): consistent with filtered T*omega (r=0.850); VCU applies low-pass filtering, explaining lower r vs instantaneous T*omega.
- Balance equation hypothesis (gen = batt - drv): not supported by pre-generator data; moot given EPRI confirmation.

---

## 0x440 B2 / 0x410 B4 -- Low-Resolution Current Candidate (2026-03-06)

### Discovery

Three-pass BMS voltage correlation scan (`artifacts/scan_bms_voltage_correlation.py`) on
`vtruxevapdrivelog4part2.log` initially flagged 0x440 B2 and 0x410 B4 as voltage candidates
(r_full=+0.947, r_win=+0.993). Plotting against DCDC reference showed the signal is far too
dynamic to be voltage -- large swings on every drive event that dwarf the actual voltage
variation. The positive full-log r was driven by session-level discharge trend and load
covariance, not voltage encoding.

### Current hypothesis

Overlaying with 0x598 B0-B1 battery current (flipped: `255 - B2`) in
`vtruxcurrentlimitingtest.log` shows strong shape match across the full 1800s log.
Linear fit of `(255 - B2)` vs `(0x598 raw - 32768)`:

  slope = 0.00439 counts_440 / counts_598
  intercept = 99.58  (i.e. B2 ~= 155 at zero current)
  Pearson r = 0.838

The r=0.838 is consistent with the signal being an 8-bit compressed version of battery
current: 0x598 spans ~22,000 counts of dynamic range; B2 has only ~100 counts, so
quantization noise is the dominant source of scatter.

Scripts: `artifacts/scan_bms_voltage_correlation.py`,
         `artifacts/plot_440b2_410b4_vs_dcdc.py`,
         `artifacts/plot_440b2_vs_598_current.py`
Plots:   `artifacts/hv_voltage_comparison.png`,
         `artifacts/plot_440b2_410b4_vs_dcdc_climit.png`,
         `artifacts/plot_440b2_vs_598_current.png`

### Key properties (provisional)

- **0x440 B2 and 0x410 B4 are bit-for-bit identical** -- same value broadcast in both
  messages. Source ECU is BMS (BMS-tier by dropout test).
- **Sign convention: higher B4/B2 = less discharge (or more regen/charge).** Consistent
  with bcm_ibat: raw * 0.025 - 1000 A; higher raw = less negative (less discharge).
  Zero-current: B4 ~= 0x9C = 156 (raw=40000; confirmed 2026-03-28 vs generator log).
  Previous estimate B2~=155 was correct.
- **NOT 8-bit only.** B4 is the high byte of bcm_ibat (16-bit BE, confirmed in EPRI DBC
  as start=39, 16-bit Motorola). B5 of 0x410 is the paired low byte.
- **Scale confirmed (2026-03-28).** bcm_ibat = raw * 0.025 - 1000 A (from Ghidra literal
  pool constants). The positive correlation of B4 with HV voltage (r=+0.947) is consistent:
  higher raw = less discharge = less sag = higher voltage.
- **Signal identity confirmed.** 0x410 B4-B5 is bcm_ibat, the A123 BMS pack current signal.
  This resolves the long-standing "battery current source unknown" question (see below).

### Byte maps (from analyze_id on vtruxcurrentlimitingtest.log, 2026-03-06)

**0x440** (20 Hz, DLC=8):

| Byte | Unique | StdDev | Character | Status |
|------|--------|--------|-----------|--------|
| B0 | 6 | 19.2 | Status flags | Unknown |
| B1 | 1 | 0.0 | Constant 0xFE | Dead byte |
| B2 | 115 | 13.4 | Analog, 8-bit | **Bit-for-bit identical to 0x410 B4 = high byte of bcm_ibat (16-bit BE * 0.025 - 1000 A). Role in 0x440 not in EPRI DBC; likely same signal rebroadcast by BMS.** |
| B3 | 254 | 71.7 | Discrete +-17/18 step deltas; NOT equal to 0x410 B5 (0.4% match) | Possible current LSB or unrelated; leave as open question |
| B4 | 22 | 3.5 | MSB-zone, low StdDev | Cell voltage MSB (MSB-stepping pattern) |
| B5 | 20 | 71.6 | Fine/step byte | Cell voltage fine byte (paired with B4) |
| B6 | 6 | 2.0 | Nearly constant | Status flags |
| B7 | 1 | 0.0 | Constant 0x00 | Dead byte |

**0x410** (20 Hz, DLC=8):

| Byte | Unique | StdDev | Character | Status |
|------|--------|--------|-----------|--------|
| B0 | 4 | 0.4 | Few states | Known interlock/state byte (confirmed signals in DBC) |
| B1 | 2 | 0.8 | Binary | Known BMS state byte (confirmed in DBC) |
| B2 | 2 | 1.5 | Binary | Lower byte of bcm_gfd (role unconfirmed; 2 values = 0xA0 normal raw=4000, 0xFE sentinel) |
| B3 | 96 | 29.3 | Smooth monotonic drain | **Low-res SoC: B3 = 2 x SoC% (r=0.9999, in DBC)** |
| B4 | 110 | 13.1 | Analog, 8-bit | **High byte of bcm_ibat (16-bit BE * 0.025 - 1000 A; same value as 0x440 B2)** |
| B5 | 256 | 72.4 | Continuous, high entropy | **Low byte of bcm_ibat** (previously misread as free-running counter; flat delta histogram is normal for a low byte of a smoothly varying 16-bit signal) |
| B6 | 5 | 14.9 | Few states | Status flags |
| B7 | 255 | 75.3 | High entropy | Unknown analog or counter |

### LSB validity tests (2026-03-06)

Ran three tests on vtruxcurrentlimitingtest.log to determine whether B3 (0x440) and B5 (0x410)
are true fine bits of the current signal. Scripts: `artifacts/scan_lsb_carry_and_soc.py`,
`artifacts/scan_16bit_validity.py`.

**Test 1 -- Cross-message equality:**
- MSB (B2 vs B4): 63.8% equal; remainder are off-by-one (update timing jitter between messages). Same signal. ✓
- LSB (B3 vs B5): 0.4% equal. Scatter plot is a uniform cloud -- completely uncorrelated. They cannot both be the LSB of the same 16-bit value.

**Test 2 -- Step-size ratio:**
- 0x440 B2-B3: ratio = 1.086 (> 1.0, LSB adds noise)
- 0x410 B4-B5: ratio = 1.095 (> 1.0, LSB adds noise)
A true fine byte reduces this ratio below 1.0.

**Test 3 -- Autocorrelation of delta-LSB:**
- 0x440 B3: lag-1 autocorr = -0.17; discrete delta spikes at 0 and +-17/18 (structured, not a counter)
- 0x410 B5: lag-1 autocorr = -0.26; uniform flat delta histogram (free-running counter pattern)

**Conclusion:** B3 and B5 are independent bytes. B3 (0x440) has structured discrete steps suggesting it
is its own signal (role unknown). B5 (0x410) is most consistent with a free-running counter. Neither is
a reliable fine-bit extension of the 8-bit current MSB. The current signal is 8-bit only.

### Next steps

- Cross-check against a charging log where charger current is known (0x18FFD7C0 B2-B3).
  If B2/B4 tracks charger current during CC phase, role is confirmed as pack current.
- Investigate 0x440 B3: discrete +-17/18 step pattern suggests a structured signal. What is it?
- Investigate 0x410 B7 (255 unique, high entropy) -- analog or counter?
- Investigate 0x410 B6 (5 unique values, 0x05/0x06/0x1A/0x22/0x26 range) -- status flags.

---

## DCDC Calibration Offset Investigation (2026-03-29)

### Method

Script: `artifacts/dcdc_offset_investigation.py`. For each charging log, pair each DCDC frame
(0x18FFD6B3 B4-B5, LE signed x0.05 V) to the nearest charger GT frame (0x18FFD7C0 B0-B1,
LE signed x0.05 V) within 0.3s. Compute `bias = DCDC - Charger`. Report mean bias and MAE
for all pairs and for the V>=350V subset (excludes pre-contact startup noise).

### Results

| Log | n (V>=350) | bias_hi | mae_hi | Notes |
|-----|-----------|---------|--------|-------|
| full charge then fail.log | 71976 | -5.46 V | 5.457 V | |
| rainychargedebug.log | 36684 | -5.58 V | 5.575 V | |
| rainychargedebug3.log | 17902 | -5.68 V | 5.684 V | |
| chargingafterturning...extension.log | 1564 | -6.59 V | 6.593 V | |
| vtruxchargeafterevaplog-failed.log | 1415 | -5.31 V | 5.309 V | |
| vtruxchargeafterevaplogattempt2.log | 26162 | -5.52 V | 5.516 V | |
| vtruxunpluggingchargehandle.log | 148 | -4.78 V | 5.957 V | |
| rainychargedebug4.log | 168 | -18.43 V | 18.435 V | **EXCLUDED -- pairing artifact** (only 254 frames total; bias_all=+37.5V nonsensical; charger and DCDC likely on different buses in this session) |

**Mean bias (7 valid logs, V>=350): -5.56 V**
**Spread across valid logs: 1.81 V** (range -4.78 to -6.59 V)

### Key findings

1. **The DCDC reads ~5.5V lower than the charger GT**, not ~7V as originally noted. The original
   figure came from a single log (`full charge then fail.log`) where the all-data bias (-7.44V)
   was used instead of the V>=350 subset; the V>=350 value for that log is -5.46V.

2. **The offset is near-constant within sessions**: for each valid log, `mae_hi ~= |bias_hi|`
   (difference <0.15V in most cases). This means the error is a DC offset, not noise or
   load-dependent variation. After applying a fixed -5.5V correction, the residual error
   per session is less than ~1V.

3. **The 1.8V spread across sessions is real but small**: consistent with a fixed hardware
   calibration offset on the DCDC ADC input (resistor divider tolerance, reference voltage
   variation). No session-to-session pattern is obvious from the data available.

4. **Practical implication**: when using the DCDC as a voltage reference in drive-mode analysis,
   add 5.5V to get the best estimate of true pack voltage. Uncertainty is +/-0.9V (half-spread).
   This is adequate for all current-use cases (correlation reference, interlock classification).
