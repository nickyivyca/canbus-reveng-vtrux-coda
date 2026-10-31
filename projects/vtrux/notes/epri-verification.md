# EPRI DBC Verification Tracking

> Created 2026-03-29. Separate from `epri-decompile.md` for pre-release signal review.
> Feed confirmed items and corrections back into `epri-decompile.md` when done.
>
> **Sources cross-referenced:**
> - Ghidra ARMv7 decompile (`ghidra-via-decompiled.txt`, `ghidra-gopoint-decompiled.txt`)
> - Pre-EPRI experimental work in `deprecated/vtrux-powertrain.dbc` and `vtrux-powertrain-experimental.dbc`
> - Log-based behavioral tests and correlation results documented in notes files
> - Cross-validation against `GMW8762_PPEI_GMLAN.dbc` and `BelInverter-v2.dbc`

## Confirmation Tiers

| Tier | Meaning |
|------|---------|
| **CONFIRMED** | Encoding AND role both independently validated (physical test, behavioral log evidence, correlation against known reference, or cross-DBC match) |
| **CONFIRMED-SYMM** | Confirmed by structural symmetry with a CONFIRMED signal; no independent test |
| **CONFIRMED-DECOMPILE** | Encoding confirmed from Ghidra; role is EPRI's label only; no independent physical/behavioral check |
| **PARTIAL** | Encoding confirmed; role or scale has a specific outstanding question flagged below |
| **REMOVED** | SG_ entries removed per DBC signal policy; documented in CM_ |

---

## PT Bus (`epri-pt-bus.dbc`)

### 0x0053 -- EPRI_OperatingMode_0053

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| OperationState (B0[3:0], 9-entry) | CONFIRMED-DECOMPILE | Ghidra + cfstring scan confirmed string values. Never cross-checked against observed bus state during startup/shutdown. |
| OperationMode (B0[6:4], 4-entry) | CONFIRMED-DECOMPILE | Same. Only index 0 ("NTRL") is a real mode; 1-3 are app error strings. |

---

### 0x0054 -- EPRI_MCU_Cmd2_Response_0054 (GENE MCU)

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| GENE_RotSpd (B0:B1 LE int16 - 32767 rpm) | **CONFIRMED** | Decompile confirmed encoding. Pre-EPRI: scale ~1.0 RPM/count, r=0.9999 full-log vs OBD PID 0x0C RPM (deprecated DBC). No overflow to at least 4686 RPM in overheat test. Note: deprecated DBC used offset -32768 (null=-1 RPM); EPRI decompile gives offset -32767 (null=0 RPM); 1-count difference has no practical significance. |
| GENE_EmergcyStp_flg (B4 bit 3) | CONFIRMED-DECOMPILE | Decompile: `(pbVar15[6] & 8) != 0`. Never observed firing in any log; no behavioral test. |

---

### 0x0308 -- EPRI_ParkRequest_0308

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| ParkRequest (B0[6:5], 3-entry) | **CONFIRMED** | Decompile confirmed bit decode. Pre-EPRI cross-validation: deprecated DBC independently observed B0=0x20 (bit 5) = Park and B0=0x40 (bit 6) = UnPark, which maps exactly onto EPRI's bits[6:5] index 1=Park / 2=UnPark. |

---

### 0x0400 -- EPRI_HV_BCM_Control_0400

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| hsc_bcm_enable (B0 bit 0) | CONFIRMED-DECOMPILE | Decompile only. 0x400 is BMS-sourced (drops with BMS LV connector; previously misattributed as HCU-to-BMS command). No dedicated behavioral test for this bit. |
| hsc_bcm_epo (B0 bit 1) | **CONFIRMED** | 0x400 is BMS-sourced. EPO is always reactive, never a leading indicator: fires ~175ms after HVIL opens in interlock faults; simultaneous with B1=0xF0 in isolation faults; fires after B1 fault latch in charge faults; never fires in post-swap inverterFault (charger-internal, BMS not involved). Confirmed across 9 fault log sets. |
| hsc_bcm_mainc_close (B0 bit 2) | CONFIRMED-DECOMPILE | Decompile only. 0x400 is BMS-sourced; no dedicated behavioral test for this bit. |
| hsc_bcm_leakage_ena (B0 bit 3) | CONFIRMED-DECOMPILE | Decompile only. 0x400 is BMS-sourced; no dedicated behavioral test for this bit. |

---

### 0x0410 -- EPRI_BCM_Status_0410

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| bcm_ready (B0 bit 0) | CONFIRMED-DECOMPILE | Decompile: `pbVar15[2] & 1`. No dedicated test. |
| bcm_epo (B0 bit 1) | CONFIRMED-DECOMPILE | Decompile: `pbVar15[2] & 2`. |
| bcm_on_plug (B0 bit 2) | CONFIRMED-DECOMPILE | Decompile: `pbVar15[2] & 4`. |
| bcm_hvil_mon (B0 bit 3) | **CONFIRMED** | 5 deliberate press/release cycles in vtruxinterlocktest2.log. 1=loop closed, 0=open. |
| bcm_mainc_stat (B0[5:4], OPEN/CLOSED/HIGH/LOW) | **CONFIRMED** | Charge logs show OPEN→CLOSED transitions at contactor close/open events. |
| bcm_chgc_stat (B0[7:6], shared array) | **CONFIRMED** | Same charge log evidence. |
| bcm_cpwr_cmd (B1 bit 4) | CONFIRMED-DECOMPILE | Decompile: `pbVar15[3] & 0x10`. |
| bcm_alarm (B1[7:6], NONE/TYPE1/TYPE2/TYPE3) | **CONFIRMED** | TYPE1→TYPE3 alarm progression observed in charge failure logs. |
| bcm_gfd (B1[3:0]:B2, 12-bit, 0.25 scale) | **CONFIRMED** | Decompile (SIMDImm). Physical: fault value 0.0 fires 150ms before EPO in vtruxisolationtest.log; normal value 1000.0 stable across all other-logs. |
| bcm_soc (B3 × 0.5 %) | **CONFIRMED** | Decompile (SIMDImm). r=0.9999 vs 0x411 high-res SoC in deprecated DBC. |
| bcm_ibat (B4:B5 BE uint16 × 0.025 - 1000 A) | **CONFIRMED** | Decompile (literal pool). Log-validated: crosses 0 A (raw=40000) at generator-on/off transitions. |
| bcm_vbat (B6[3:0]:B7, 12-bit, 0.25 V) | **CONFIRMED** | Decompile confirmed encoding. Phase 5 (2026-03-29, oghighwaydrive.log): after contactors close, tracks GENE_HighPwr_Volt within ±1.25V over ~380V (rounding resolution of both signals). Sample: t=786.7s bcm_vbat=393.00V vs GENE=393.0V (diff=0.00V). Startup sentinel = 1023.5V (raw ~4094, near-max 12-bit) before contactors close. Full-log r=+0.39 is depressed by startup sentinel period; active-window data unambiguous. |
| bcm_chg_done (B6 bit 4) | CONFIRMED-DECOMPILE | Decompile: `pbVar15[8] & 0x10`. |
| bcm_cool_req (B6 bit 5) | CONFIRMED-DECOMPILE | Decompile: `pbVar15[8] & 0x20`. |

---

### 0x0420 -- EPRI_BCM_Limits_0420

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| bcm_dis_max (B0:B1[7:4], 12-bit, 0.25 A) | **CONFIRMED** | Decompile (SIMDImm). Confirmed in current-limits-investigation.md as DCL. Nibble-split encoding confirmed by EPRI decompile after prior scans missed it. |
| bcm_chg_max (B1[3:0]:B2, 12-bit, 0.25 A) | **CONFIRMED** | Same; confirmed as CCL. |
| bcm_cell_undervolt (B6 bit 6) | CONFIRMED-DECOMPILE | Decompile: `pbVar15[8] & 0x40`. Never independently observed firing. |
| bcm_cell_overvolt (B6 bit 7) | CONFIRMED-DECOMPILE | Encoding from the decompile. **Never observed set** (corrected 2026-09-16): zero in all 227 InfluxDB sessions / 412,300 points; the corpus maximum of `bcm_cell_vmax` is 3.603 V. The earlier "fires at charge failure cutoff events" claim was wrong -- the pre-swap failures pushed `FC 22 02` with this flag clear (`specific-trucks/before-battery-swap-failed-charge-analysis.md`, `fault-signature-comparison.md`). |

---

### 0x0430 -- EPRI_BCM_Data1_0430

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| bcm_chga_ena (B0 bit 7) | CONFIRMED-DECOMPILE | Decompile: `(char)pbVar15[2] < 0`. |
| bcm_cell_vmax (B0[4:0]:B1, 13-bit, 0.001 V) | **CONFIRMED** | Decompile: DAT=0.001 at 0x27AB0. Pre-EPRI: r>0.99 in stable windows (cell-voltage-investigation.md). Experimental formula (B0[3:0]*256+B1) was correct within 1 bit. |
| bcm_cell_vmin (B2[4:0]:B3, 13-bit, 0.001 V) | **CONFIRMED** | Same evidence. |
| bcm_veh_mon (B2 bit 5) | CONFIRMED-DECOMPILE | Decompile: `pbVar15[4] & 0x20`. |
| bcm_chga_mon (B2 bit 6) | CONFIRMED-DECOMPILE | Decompile: `pbVar15[4] & 0x40`. |
| bcm_mod_ena (B2 bit 7) | CONFIRMED-DECOMPILE | Decompile: `(char)pbVar15[4] < 0`. |
| bcm_cell_tmax (B4 × 0.5 - 40 degC) | **CONFIRMED** | Decompile: DAT=-40.0 at 0x27600. Supersedes provisional experimental formula raw-100 (formula reconciliation documented in epri-decompile.md). |
| bcm_cell_tmin (B5 × 0.5 - 40 degC) | **CONFIRMED** | Same. |
| bcm_lvbat (B7 × 0.1 V) | **CONFIRMED** | Decompile: DAT=0.1 at 0x28568. Observed values physically meaningful: 140=14.0V (DCDC active), 127=12.7V (at rest). |

---

### 0x0440 -- EPRI_BCM_Data2_0440

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| bcm_fault_mon (B0 bit 6) | CONFIRMED-DECOMPILE | Decompile only. |
| bcm_balancing (B0 bit 7) | CONFIRMED-DECOMPILE | Decompile only. |
| bcm_mainc_stat (B0[5:2], 4-bit, 16-entry contactor state machine) | **CONFIRMED** | State transitions (ALL_OPEN → CLOSE_MAINR → WAIT_PRECHARGE → MAIN_PN_CLOSED_DRIVE, etc.) observed in charge logs (before-battery-swap-charge-analysis.md). String values confirmed from cfstring scan. Note: MAINP/MAINN/MAINR abbreviation expansions are inferred from state sequence names, not from binary text. |
| bcm_fgd (B1 × 0.5 %) | **PARTIAL** | Encoding CONFIRMED from decompile. Role unknown (plist label only). Always at sentinel 0xFE in all 73 captured logs — never populated by this BMS configuration. |
| bcm_vbus_pos (B4:B5[7:4], 12-bit, 0.25 V) | **CONFIRMED** | Decompile (literal 0.25 double). Confirmed as positive DC bus rail in current-limits-investigation.md. |
| bcm_vbus_neg (B5[3:0]:B6, 12-bit, 0.25 V - 500) | **CONFIRMED** | Decompile: DAT=-500.0 at 0x27AB8. Confirmed as negative DC bus rail in same investigation. |
| bcm_balancing_cnt (B7 raw byte) | **CONFIRMED** | Balancing count confirmed in balancing-investigation.md. |

---

### 0x0471 -- EPRI_MCU_Info2_0471 (GENE torque feedback)

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| GENE_Mot_Trq (B0:B1 LE uint16 × 0.125 - 4096 Nm) | **CONFIRMED** | Decompile: DAT=-4096.0 at 0x25ea8. Pre-EPRI: deprecated DBC explicitly used 0x471 B0-B1 as torque feedback reference with r=0.9984 vs 0x051 torque command across full drive log. |

---

### 0x0479 -- EPRI_MCU_Thermal1_0479 (GENE thermal)

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| GENE_DrvCoolFlowReq_pct (B0 × 0.78125 %) | **CONFIRMED** | Decompile (SIMDImm). Thermal investigation: steady ~50% at normal load, rises toward 100% under sustained overheat; PE glycol loop behavior confirmed. |
| GENE_MotCoolFlowReq_pct (B1 × 0.78125 %) | **CONFIRMED** | Saturates at 100% during generator oil pump unplug overheat test. Motor oil circuit behavior confirmed. |
| GENE_ThermInd_pct (B2 × 0.78125 %) | **CONFIRMED** | Rises monotonically through overheat event, peaks 80-90% at RPM overflow; confirmed as trigger for generator torque derating. |

---

### 0x0482 -- EPRI_MCU_Info1_0482 (GENE HV bus)

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| GENE_HighPwr_Volt (B1:B2[2:0], 11-bit LE, 1 V/count) | **CONFIRMED** | Decompile. Log-validated: 383-384V stable at highway cruise in oghighwaydrive.log. BE alternative gives nonsense values. |
| GENE_HighPwr_Curr (B3:B4[5:0], 14-bit LE, 0.25 A - 2048) | **CONFIRMED** | Decompile: DAT=-2048.0 at 0x2ab28. Log-validated: ~-40A at highway cruise, +2.75A at startup — physically consistent. |

---

### 0x055C -- EPRI_ParkLock_055C

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| parkLockState (B0[2:0], 3-bit, 7-entry) | CONFIRMED | Ghidra + cfstring (VMAs 0xF59E8-0xF5A28) + raw log cross-validation (Vtrux + Coda, 2026-04-07). Index 1 ("Park") inferred from NEON paired-load; indices 0/2/4/6 have explicit MOVW instructions. |
| parkSensor (B0 bit 6) | CONFIRMED | Same. |
| driveSensor (B0 bit 7) | CONFIRMED | Same. |

**Byte position correction (2026-04-07):** Original entry recorded signals at B2. This was a transcription error: the Ghidra code accesses `pbVar15[2]` which per the buffer layout documented in `epri-decompile.md` (lines 416-420) = CAN B0 (`pbVar15[N]` → CAN B`N-2`). Raw log extraction across both vehicles confirmed CAN B2 is always 0x00; B0 carries all active state transitions. DBC corrected: DLC 3→4, signals moved from bit 16/22/23 to bit 0/6/7. See `notes/borgwarner.md`.

---

### 0x0580 -- EPRI_TCM_CANError_0580

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| tcm_CAN_ERR (B2 bit 1) | CONFIRMED-DECOMPILE | Decompile: `(pbVar15[4] & 2) != 0`. Never observed firing in any log. |

---

### 0x0592 -- EPRI_HCU_Sensor_0592

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| EVSESwitchState (B0 bit 1) | CONFIRMED-DECOMPILE | Decompile. No behavioral check (e.g., does it toggle when EVSE connected/disconnected in charge logs?). |
| ExportPowerState (B0 bit 2) | CONFIRMED-DECOMPILE | Decompile. No behavioral check. |
| IgnitionKeyState (B0 bit 4) | CONFIRMED-DECOMPILE | Decompile. No behavioral check (e.g., does it clear at key-off?). |
| Veh_BrakePdl_Pos (B4:B5 LE uint16 × 0.01 %) | **CONFIRMED** | Decompile: DAT=0.01 at 0x25EA0. Pre-EPRI: brake pedal role confirmed in deprecated DBC. Scale cross-validates: max raw ~10000 × 0.01 = 100.0% (consistent with pre-EPRI experimental observation of max ~4700-10000 raw in hard braking). |

---

### 0x0598 -- EPRI_HCU_VIRTSENS_7_PwrStatAvg_0598

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| DBL_ESSPwrAvg (B0:B1 offset-binary excess-32768, zero at 0x8000, × 0.01 kW) | **CONFIRMED** | Encoding: `(raw_u16 − 32768) × 0.01 kW` — confirmed 2026-06-27 by 0x598 raw-value check (idle sits at 0x8000); corrected from the decompile's earlier "signed int16, zero at 0x0000" reading (see `epri-decompile.md`). Scale 0.01 kW/count from decompile (DAT=0.01). Role "battery pack power" confirmed experimentally (near-zero when generator fully covers traction load, tracks regen). Scale 0.01 kW/count confirmed 2026-03-29 by cross-correlation of B2-B3 (gen channel) against GENE_HighPwr_Curr × GENE_HighPwr_Volt: power slope locked at -0.01007 kW/count across gen-on, gen-off, and all-frames segments, matching EPRI. Adjacent channel scale confirmed. |
| DBL_TracPwrAvg (B4:B5 as B5<<8\|B4, offset-binary excess-32768, zero at 0x8000, × 0.01 kW) | **CONFIRMED** | Encoding `(raw_u16 − 32768) × 0.01 kW` (corrected 2026-06-27 — see ESS row / `epri-decompile.md`). Same scale confirmation applies (shared 0.01 kW/count constant across all three channels per decompile; gen channel independently validated). Role "traction motor power" confirmed experimentally. |

Note: B2-B3 is the generator power channel (not in EPRI DBC, added to `vtrux-powertrain-experimental.dbc`). Role and scale both confirmed 2026-03-29 (scale 0.01 kW/count, peak ~73.7 kW uphill, ~44 kW during evap purge). See powertrain-messages.md.

**⚠ 2026-08-02 — both signals moved out of the EPRI DBC (app defect, not an extraction error).** Ghidra analysis established that the EPRI app genuinely decodes B0-B1 and B4-B5 as plain signed int16: `FUN_00045af0(v, 0x10)` is exactly `(int16_t)v` (verified over all 65536 inputs), and `parseEPRIMessage` contains zero 0x8000-family constants on both the ARMv7 and ARM64 slices. The earlier guess that the decompile had missed an MSB-flip was wrong — there is no bias in the app. At idle the app therefore displayed −327.68 kW for both fields.

Per the bugged-decode convention (as with 0x0451 and 0x0459), `BO_ 1432` in `epri-pt-bus.dbc` is now a **stub with SG_ entries removed**, and the corrected signals live in `vtrux-powertrain-experimental.dbc` as `ess_power` (B0-B1), `gen_power` (B2-B3), and `trac_power` (B4-B5), all `(0.01, -327.68)` unsigned LE. The tiers above remain CONFIRMED — they describe the **wire format**, which is unchanged; only the DBC home changed.

---

### 0x0599 -- EPRI_HCU_VIRTSENS_5_Pressures_0599

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| GeneOilPress (B0:B1 LE uint16 × 0.1 kPa, offset 0 per decompile) | **PARTIAL** | Scale 0.1 kPa/count decompile-confirmed (DAT=0.1 at 0x26B30). Offset 0 per decompile — EPRI applies raw × 0.1 with no subtraction. Idle raw ~0x8000 decodes to ~3276 kPa, which is physically implausible; likely a mid-scale sensor (if so, true pressure = (raw − 32768) × 0.1 kPa, range 0–160 kPa in overheat logs). Offset correction unconfirmed — no pump disconnect test. Role from EPRI name only. |
| TracOilPress (B4:B5 LE uint16 × 0.1 kPa, offset 0) | **PARTIAL** | Scale 0.1 kPa/count decompile-confirmed. Offset 0 consistent with log data — values start near zero and rise to ~70 kPa under load. Note: plist order is swapped from format string (format string lists Gene first, but plist .1=Trac, .2=Gene) — byte assignment confirmed from decompile. Role not independently validated. |
| B2:B3 (uncharacterized) | **NOTE** | Constant value 1030 raw = 103.0 kPa across both overheat logs. Consistent with ~1 atm barometric reference. Not read by EPRI. |

**Architecture note:** 0x0599 is an **HCU (VCU) message**, not from either motor inverter. The "VIRTSENS" prefix (virtual sensor) means the HCU reads the analog pressure sensor inputs directly via ADC, digitizes them, and republishes on the PT bus. Scale 0.1 kPa/count is decompile-confirmed for both signals; offset 0 per decompile. TracOilPress decoded values are consistent with offset 0. GeneOilPress idle raw ~0x8000 (~3276 kPa decoded) suggests a mid-scale sensor convention, but offset correction is unconfirmed without a pump disconnect test.

---

### 0x0625 -- EPRI_Veh_Odo_0625

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| VehicleConfig (B3[7:5], 3-bit) | **CONFIRMED** | Decompile: `B3 >> 5` dispatch; 0=K2XX (Silverado-based), 1=GMT-600 (Express van). |
| VehicleOdometer (B0:B1:B2, 24-bit BE) | **CONFIRMED** | Scale 1 km/count confirmed 2026-03-29 by log cross-check: oghighwaydrive.log shows raw=95,517 km (59,353 miles) at start, +39 km over 35 min at highway speed (67 km/h avg), consistent with current ~60,000 mile reading. 0.1 km/count ruled out (would give 9,552 km = 5,935 miles). Note: B3-B5 are active but NOT read by EPRI; B6-B7 constant 0x00. |

Note: The GMLAN BCM odometer (0x0120 on OBD bus) is absent from all passive captures (0 frames across multiple drive sessions). The Via-modified vehicle does not broadcast the GM BCM odometer. 0x0625 (HCU) is the authoritative odometer.

---

### 0x062F -- EPRI_HCU_SwVersion_062F

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| HCU_SwIDPrj_Enum (B0[7:2]) | CONFIRMED-DECOMPILE | Decompile. Version fields not cross-checked against known HCU version. |
| HCU_SwIDType_Enum (B0 bit 1) | CONFIRMED-DECOMPILE | Same. |
| MajorVersion (B1[6:0]) | CONFIRMED-DECOMPILE | Same. |
| MinorVersion (B2) | CONFIRMED-DECOMPILE | Same. |
| HCU_SwIDMaturity_Enum (2-bit cross-byte, CM_ only) | CONFIRMED-DECOMPILE | Same. |
| HCU_SwIDVehVariant_Enum (10-bit cross-byte, CM_ only) | CONFIRMED-DECOMPILE | Same. |
| HCU_SwIDCalVer_Cnt (8-bit cross-byte, CM_ only) | CONFIRMED-DECOMPILE | Same. |

---

### 0x063A -- EPRI_VehicleConfig_063A

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| iVehCfg_chgr_md (B7 bit 0) | **CONFIRMED** | Decompile: 0=POWERONE, 1=DRS. Confirmed 2026-03-29: 0x063A present in passive captures (211,591 frames in oghighwaydrive.log). B7=0x00 in all frames — chgr_md=0 (POWERONE), consistent with installed Bel/Solectria POWERONE charger. |
| iVehCfg_ess_md (B7 bit 1) | **CONFIRMED** | Same log evidence. B7=0x00 — ess_md=0 (A123), consistent with installed A123 battery pack. |

---

### 0x065B -- EPRI_HCU_DTC_065B

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| DTC_Code ((B6<<8)\|B7, 16-bit) | CONFIRMED-DECOMPILE | Decompile confirmed encoding; 29-entry lookup table strings confirmed from cfstring scan. Message **never observed in any of 62+ log files** (scan-tool-requested response only, not periodically broadcast). |

---

### Bel Inverter / DCDC Messages (J1939 extended IDs)

| ID | Signal | Tier | Evidence / Gap |
|----|--------|------|----------------|
| 0x18FFD4C0 | All page 0-3 signals | **CONFIRMED** | Cross-validated against BelInverter-v2.dbc (byte/bit positions match; EPRI app missing 3 page-3 fault flags that Bel DBC has). |
| 0x18FFD5C0 | INVCH_Bdc_Temperature_Int | **CONFIRMED** | Decompile (DAT at 0x25590). Thermal investigation confirms charger BDC temperature values are physically meaningful across charge sessions. |
| 0x18FFD5C0 | INVCH_Bdc_TempPercent | CONFIRMED-DECOMPILE | Decompile. Percentage value not independently cross-checked. |
| 0x18FFD6B3 | DCDC_HV_Volt | **CONFIRMED** | r=0.993 vs charger reference in deprecated DBC; interlock test confirms drop at contactor open. |
| 0x18FFD6B3 | DCDC_Temperature | **CONFIRMED** | Thermal trajectory (18.4→41.5 degC cold start to peak) across full charge session (deprecated DBC Phase 1C). |
| 0x18FFD6B3 | DCDC_LV_Volt | **CONFIRMED** | Encoding from decompile (DAT=0.05 at 0x23B18). Phase 6 (2026-03-29): range 12.15-14.35V exactly consistent with 12V bus (12.15V near resting, 14.35V DCDC active); r=+0.87 vs bcm_lvbat in rainychargedebug.log. bcm_lvbat has startup sentinel that pulls r down; DCDC_LV_Volt range itself is clean. |
| 0x18FFD6B3 | DCDC_LV_Curr | **PARTIAL** | Encoding from decompile. Values physically plausible: 5-7A during 12V battery float charge (tapering taper over charge session), 26-56A during driving (varying with active loads). Blower fan test: +1.26A for 32.9% blower speed (~18W, plausible). Generator oil pump (~430W) confounds controlled tests. No independent physical measurement. See `dcdc-current-investigation.md`. |
| 0x18FFD6B3 | DCDC_Temperature | **CONFIRMED** | EPRI decompile: DCDCunitinternaltemperature x0.1 degC (signed). Phase 2: 15.8-22.7°C in isolation test log. Prior powertrain-messages.md note "B6-B7: 12V measured output" was wrong — corrected 2026-03-29. |
| 0x18FFD6C0 | All four INVCH_Inv signals | **CONFIRMED** | Cross-validated against BelInverter-v2.dbc (exact match on scale 0.05 and byte positions). |
| 0x18FFD7C0 | INVCH_Bdc_Vbat, INVCH_Bdc_Ibat, INVCH_Chg_Vin/Iin_RMS | **CONFIRMED** | Cross-validated against BelInverter-v2.dbc (scale and positions match). |
| 0x18FFD8C0 | INVCH_Bdc_12Vbat | **CONFIRMED** | Cross-validated against BelInverter-v2.dbc (exact match). |

---

### GoPoint-internal IDs (not in EPRI DBCs)

These IDs in the EPRI plist are GoPoint BT1 internal message type IDs wrapping J1939 extended frames.

| GoPoint ID | EPRI signal name | Status |
|-----------|-----------------|--------|
| 0x0868A047 | EAC_STATUS1: EAC_Elec_Curr, EAC_Elec_Pwr | **In `vtrux-powertrain-experimental.dbc`.** Investigated in hvac-investigation.md. |
| 0x0870A047 | EAC_STATUS2: EAC_CompHVInput | **In `vtrux-powertrain-experimental.dbc`.** eac_hv_input confirmed: B2 × 4 = HV bus voltage, mean error 1.3V vs 0x0482 reference. |
| 0x06000001 | EPT_Stat_HMI_1: Accel_Ped_Pos, Veh_Speed, gear position | Not decoded at raw CAN level; GoPoint wrapper format not analyzed. |

---

## OBD Bus (`epri-obd-bus.dbc`)

### 0x0044 -- EPRI_MCU_Cmd2_Response_0044 (TRAC MCU)

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| TRAC_RotSpd (B0:B1 LE int16 - 32767 rpm) | CONFIRMED-SYMM | Encoding confirmed from decompile (symmetric to GENE 0x0054). GENE was validated r=0.9999 vs OBD RPM. TRAC motor RPM values not independently validated. |
| TRAC_EmergcyStp_flg (B4 bit 3) | CONFIRMED-SYMM | Structural symmetry with GENE_EmergcyStp_flg. Never observed firing. |

---

### 0x00C9 -- Engine_Speed

| Signal | Tier | Evidence |
|--------|------|----------|
| Engine_Speed (B1:B2 BE uint16 × 0.25 rpm) | **CONFIRMED** | Exact match with GMW8762_PPEI_GMLAN.dbc. |

---

### 0x0120 -- EPRI_BCM_Vehicle_Odometer_HS_0120

| Signal | Tier | Evidence / Gap |
|--------|------|----------------|
| VehicleOdometer (B1:B4 BE uint32 × 0.015625 km) | **CONFIRMED** | Encoding confirmed from decompile (DAT=0.015625; ×0.62137 for miles display). GMLAN DBC has placeholder only — EPRI is authoritative for Vtrux encoding. Note: **0 frames in all passive captures** (oghighwaydrive.log, truk1log_M0_T0.log). The Via-modified vehicle does not broadcast the GM BCM odometer; use PT bus 0x0625 instead. |

---

### 0x01C3 -- Engine Torque

| Signal | Tier | Evidence |
|--------|------|----------|
| EngineTorqueActual (12-bit × 0.5 - 848 Nm) | **CONFIRMED** | Exact match with GMW8762_PPEI_GMLAN.dbc. |
| EngineTorqueRequested (12-bit × 0.5 - 848 Nm) | **CONFIRMED** | Same. |

---

### 0x02C3 -- MAP

| Signal | Tier | Evidence / Caveat |
|--------|------|-------------------|
| MAP (B6 × 0.5 kPa) | **CONFIRMED** | GMLAN DBC match (unsigned). Caveat: EPRI app uses signed int8 — wrong above 63.5 kPa. DBC uses unsigned (correct). Plist label "PPEI_Engine_Torque_Status_3" was wrong; decompile reveals actual signal is MAP. |

---

### 0x03D1 -- Fuel Rate

| Signal | Tier | Evidence |
|--------|------|----------|
| ECM_InstFuelConsmpRate_volPt (12-bit × 0.025 L/hr) | **CONFIRMED** | Exact match with GMW8762_PPEI_GMLAN.dbc. Plist label wrong; decompile reveals fuel rate, not TPS. |

---

### 0x03E9 -- Vehicle Speed and Distance

| Signal | Tier | Evidence |
|--------|------|----------|
| ECM_VehSpdAvgDrvn_linspd (15-bit × 0.015625 km/h) | **CONFIRMED** | Exact match with GMLAN DBC. |
| ECM_DistRollCntAvgDrvn_dist (13-bit × 0.125 km) | **CONFIRMED** | Exact match with GMLAN DBC. |

---

### 0x044A -- EPRI_MCU_Thermal1_044A (TRAC thermal -- CORRECTED from EPRI's 0x459)

| Signal | Tier | Evidence |
|--------|------|----------|
| TRAC_DrvCoolFlowReq_pct (B0 × 0.78125 %) | **CONFIRMED** | Correct ID confirmed via OBD correlation (r=+1.000 vs 0x06000002 10-bit). Scale from GENE decompile (symmetric). |
| TRAC_MotCoolFlowReq_pct (B1 × 0.78125 %) | **CONFIRMED** | Saturates at 100% under sustained traction thermal stress. Symmetric to GENE. |
| TRAC_ThermInd_pct (B2 × 0.78125 %) | **CONFIRMED** | r=+1.000 vs PT bus 0x06000002 B5/B6 VCU rebroadcast. B3 is rolling counter, not a signal. |

EPRI plist listed 0x0459 (wrong ID, zero frames in all logs). Stub at BO_ 1113 has SG_ removed per policy.

---

### 0x0451 -- Stub only (SG_ removed)

EPRI attributed this to TRAC_Mot_Trq. Log data identifies it as `Gateway_LS_General_Information` (GMLAN). SG_ removed per policy. See traction-inverter-control.md.

---

### 0x0462 -- EPRI_MCU_Info1_0462 (TRAC HV bus)

| Signal | Tier | Evidence |
|--------|------|----------|
| TRAC_HighPwr_Volt (B1:B2[2:0], 11-bit LE, 1 V/count) | CONFIRMED-SYMM | Identical layout to GENE_HighPwr_Volt (log-validated on GENE). Symmetric +0x20 ID offset. |
| TRAC_HighPwr_Curr (B3:B4[5:0], 14-bit LE, 0.25 A - 2048) | CONFIRMED-SYMM | Same. |

---

### 0x04C1 -- Engine Temperatures

| Signal | Tier | Evidence |
|--------|------|----------|
| ECM_EngineCoolantTemp (B2, uint8 - 40 degC) | **CONFIRMED** | GMLAN DBC (start_bit=23 @0+) + independent raw-data validation in hvac-investigation.md (cold start->operating temperature arc). Decompile: `puVar20[4]` = CAN B2 (corrected 2026-05-12; earlier notes mislabeled as B4 by not subtracting puVar20's 2-byte ID header). |
| ECM_EngineAirIntakeTemp (B3, uint8 - 40 degC) | **CONFIRMED** | GMLAN DBC (start_bit=31 @0+). Decompile: `puVar20[5]` = CAN B3 (same index-offset correction). |
| ECM_OutsideAirTemp (B4, uint8 × 0.5 - 40 degC) | **CONFIRMED** | GMLAN DBC (start_bit=39 @0+). Decompile: `puVar20[6]` = CAN B4. hvac-investigation.md confirms B4 reads 9-12 degC (ambient), not ECT values. |

---

## Open Items (action needed before release)

| # | Signal | Issue | Action |
|---|--------|-------|--------|
| 1 | **GeneOilPress, TracOilPress** (0x0599) | Role not independently validated; ongoing investigation. | Complete thermal-investigation.md oil pressure phase before including in any release DBC. |
| 2 | **DBL_ESSPwrAvg, DBL_TracPwrAvg** (0x0598) | ~~Scale 0.01 kW/count from decompile only; experimental DBC notes scale unconfirmed.~~ **RESOLVED 2026-03-29.** Scale 0.01 kW/count confirmed: gen channel (B2-B3) cross-correlated against GENE_HighPwr_Curr × GENE_HighPwr_Volt in evap4part2 (68 gen-on frames); slope -0.01007 kW/count locked across all segments. All three 0x0598 channels share the same scale constant per decompile. Tier upgraded to CONFIRMED for ESS and Trac channels. |
| 3 | **DCDC_LV_Volt** (0x18FFD6B3 B0-B1) | ~~Medium confidence; not independently verified.~~ **RESOLVED 2026-03-29.** CONFIRMED: range 12.15-14.35V, r=+0.87 vs bcm_lvbat in normal charge log. B6-B7 also resolved as temperature (not 12V output). **DCDC_LV_Curr** (B2-B3) remains PARTIAL — branched to `dcdc-current-investigation.md`. |
| 4 | **bcm_vbat** (0x0410 B6-B7) | ~~Role "pack voltage" not cross-checked.~~ **RESOLVED 2026-03-29.** CONFIRMED as HV pack voltage: tracks GENE_HighPwr_Volt within ±1.25V after contactors close (Phase 5, oghighwaydrive.log). Startup sentinel 1023.5V confirmed as pre-contactor-close invalid state. |
| 5 | **0x063A VehicleConfig** | ~~Never confirmed in log data.~~ **RESOLVED 2026-03-29.** Confirmed present (211,591 frames in oghighwaydrive.log). B7=0x00 in all frames: chgr_md=0 (POWERONE), ess_md=0 (A123). Both signals upgraded to CONFIRMED. |
| 6 | **GoPoint EPT_Stat_HMI_1** (0x06000001) | Not decoded at raw CAN level. | Low priority; Accel_Ped_Pos and Veh_Speed are available from other confirmed sources. |

---

## Signals with inferred (not text-confirmed) expansions

| Signal | Inferred element | Basis |
|--------|-----------------|-------|
| bcm_mainc_stat (0x0440) 16-entry table | MAINP/MAINN/MAINR abbreviation expansions | State sequence analysis (WAIT_PRECHARGE → MAIN_P_CLOSED_CHARGE etc.). String values confirmed from cfstring; expansions are inference. |
| parkLockState (0x055C) index 1 = "Park" | Adjacent to explicitly confirmed index 0 in NEON paired-load | Indices 0/2/4/6 have explicit MOVW instructions. |
