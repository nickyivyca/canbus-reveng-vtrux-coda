# Coda Charging Session Analysis

**Log:** `codacharging.log` (31.7 MB, 402,847 frames, 594.94s ≈ 9.9 min)
**Session:** Level 2 charging. Log started properly at charge startup. Log ended early — OBD adapter was removed while charging was still in progress (house meter confirms 6.5 kWh total over ~58 min; log captures only the first 9.9 min / ~1.11 kWh AC).
**Analyzed:** 2026-02-18

> **⚠ Cell numbering updated 2026-07-22.** The C CAN DBC (`CODA-C-CAN-cells.dbc`) is now
> **1-based** (`Cell1…Cell104`), matching the BMS's own `VmaxId`/`VminId` directly
> (VmaxId 82 = Cell82). It was previously **0-based** (`Cell0…Cell103`). Cell numbers in this
> file have been updated to 1-based; **any older artifact, CSV, plot, or export is still
> 0-based — add 1 to reconcile** (old `#94` = current `Cell95`). `VmaxId`/`VminId`/"BMS index"
> values were always 1-based and are unchanged. `MinTempId`/`MaxTempId` are a separate index,
> unaffected. See `cell-index-mapping.md`.

---

## Channel Identification

The log contains **2 buses only** (C CAN and B CAN). No D CAN was recorded in this capture — either the third OBD-II wire was not plugged in or the D CAN bus was silent.

| Bus | Confidence | Anchor IDs |
|---|---|---|
| **C CAN** | Definitive | 0x000–0x019 (cell voltages, confirmed in all prior captures) |
| **B CAN** | Definitive | 0x274, 0x277, 0x279, 0x27D, 0x615–0x617 (Lear CMM charger IDs) |

**B CAN:** 42 unique IDs
**C CAN:** 99 unique IDs

---

## Goal 2: Gateway Re-broadcast Analysis

**Result: ZERO shared IDs between B CAN and C CAN.**

No message ID appears on both buses. The GWM acts as a complete firewall between B and C CAN during a charging session (key on, no drive mode). This is a significant baseline finding:

- The "ghost" C CAN IDs seen in prior captures (0x0FF, 0x200–0x203, 0x300–0x304, 0x621–0x627) are **native C CAN / BMS diagnostic port traffic** — they are NOT being echoed by the GWM from B CAN.
- D CAN gateway behavior cannot be characterized from this log (D CAN absent). Future captures with all three buses connected will be needed.

---

## Goal 3: Charger Signal Validation

### 0x274 — ChrgrSysFaultsTemp (8.3 Hz)

```
Sample: 00 00 00 00 00 00 35 35
```

- **Bytes 0–5: ALL ZEROS** → no fault flags active ✓ (clean session, handle pull, no fault)
- Bytes 6–7: 0x35–0x39 (53–57) — slowly varying, suspected temperature or phase angle; not a fault flag field

**Finding:** Clean charge confirmed.

---

### 0x27D — CMMInputValues — AC Input (8.3 Hz)

```
Sample: 1D 60 01 C8 00 03 45 30
```

Encoding confirmed by power balance cross-check:

| Bytes | Formula | Observed Range | Physical Meaning |
|---|---|---|---|
| 0–1 (BE uint16) | ÷ 32 | 7392–7536 → **231–235.5 V** | AC line voltage (RMS) |
| 2–3 (BE uint16) | ÷ 32 | 458–459 → **14.31–14.34 A** | AC line current (RMS) — CMM individual |
| 4–7 (BE uint32) | ÷ 64 | 213435 → **3334.9 W** | AC input power — CMM individual |

**Voltage trend:** 235.0V (t=0) → 232.5V (steady-state). Small drop consistent with grid loading.
**Current (CMM only):** 14.34A. Combined with CMS (14.72A) = **29.06A total** — matches house meter ~6.8 kW ✓

> Note: Prior analyses used ÷20 (→ 23A) and ÷16 (→ 28.5A, treating CMM as combined total) which were incorrect. CODACAN replay confirms ÷32 and CMM-individual measurement.

> **CORRECTION (2026-07-21) — bytes 4–7 are ACInPower.** This table previously
> split bytes 4–5 ("fixed 0x0003, status/phase flag") and bytes 6–7 ("unknown,
> possibly phase angle or reactive power") into two mystery fields, and the note
> above previously claimed CODACAN's power display was calculated rather than
> decoded. Both were wrong, and for the same reason: bytes 4–7 are a **single
> 32-bit BE field at scale 1/64**, not two 16-bit fields at 1/32. Splitting it in
> half made the high bytes look like a constant `0x0003` enum and the low bytes
> look like noise. CODACAN was decoding this field all along — it matches V×I
> because the charger computes it that way, not because CODACAN did the multiply.
>
> `CODA-B-CAN.dbc` had the same pattern-fill error (`ACInPower : 39|16@0+
> (0.03125,0)`), which decoded to 3/32 = **0.09 W** against ~3.1 kW actual. Fixed
> to `39|32@0+ (0.015625,0)`.
>
> **Verification:** 367,728 charger frames across `drivewaycharge2`,
> `chargepointcharge`, `codachargepointcharge`, and `codacharging`, both 0x27B and
> 0x27D. Best-fit divisor exactly **64.0000** at p05/median/p95; error vs V×I
> **+0.000 %** from p01 through p99; 100 % of frames within ±1 %. Byte 4 is zero in
> all 183 k active frames, so a 24-bit field over bytes 5–7 fits the data
> identically — 32-bit is preferred as it makes the message a clean 16+16+32.
> Summed CMS+CMM = **6677 W median**, matching the ~6.8 kW house-meter figure.
> Script: `artifacts/ac-voltage/acinpower_phase3.py`.
>
> **Interpretation (hypothesis):** the fit is exact rather than approximate — the
> implied power factor is 1.0000 at every percentile and the raw value is the
> exact integer `(Vraw × Iraw) >> 4`. This reads as **apparent power (VA) computed
> internally by the Lear charger from its own V and I registers**, not an
> independently measured true-power value. Practically the field carries no
> information beyond V and I, so `notes/ac-resistance.md` lost nothing by not
> using it.

> **CRITICAL CORRECTION:** The previous "÷16 = 28.5A matches house meter" logic was wrong because it treated CMM current as the combined total. The correct interpretation: each module reports its own current at ÷32. CMM = 14.34A + CMS = 14.72A = 29.06A total ≈ house meter reading.

---

### 0x279 — CMMOutputValues — HV DC + LV Output (8.3 Hz)

```
Sample: 2B F4 01 14 01 A5 00 00
```

| Bytes | Formula | Observed Range | Physical Meaning |
|---|---|---|---|
| 0–1 (BE uint16) | ÷ 32 | 11252–11302 → **351.6–353.2 V** | HV DC output voltage |
| 2–3 (BE uint16) | ÷ 32 | 275–277 → **8.59–8.66 A** | HV DC output current (CMM individual) |
| 4–5 (BE uint16) | ÷ 32 | 420–423 → **13.13–13.22 V** | LV (12V) output voltage |
| 6–7 (BE uint16) | ÷ 32 | 0–44 → **0–1.375 A** | LV (12V) output current |

**Sample decode:** `2B F4 01 14 01 A5 00 00`
- B0-1 = 0x2BF4 = 11252 → 11252/32 = **351.625 V** HV voltage ✓
- B2-3 = 0x0114 = 276 → 276/32 = **8.625 A** HV current ✓
- B4-5 = 0x01A5 = 421 → 421/32 = **13.156 V** LV voltage ✓
- B6-7 = 0x0000 = 0 → LV current ≈ 0 at this moment (varies; CODACAN confirmed 1.375A = 44/32 at another frame)

**Correction of prior analysis:** Bytes 2–3 were previously marked as "unknown pair 275–277". They are confirmed HV current at ÷32. The prior "HV current = bytes 4–5 ÷ 25" was incorrect — bytes 4–5 are LV voltage.

**Power balance (CMM individual, from CODACAN replay):**
- CMM: 353.2V × 8.625A ≈ **3,048 W**
- CMS: 352.7V × 8.594A ≈ **3,030 W**
- Combined DC: **~6,078 W**
- Combined AC: (14.34A + 14.72A) × 233.5V ≈ **6,783 W**
- Efficiency: **89.6%** ✓ consistent with switching converter

Voltage slowly rising (351.6V → 353.2V) with stable current → **CC mode confirmed**.

---

### 0x277 — CMMTempStatus — Charger Temperatures (8.3 Hz)

```
Sample A (session start): 01 0D 03 50 02 79 02 80
Sample B (warmed up):     02 FD 03 D9 02 E7 02 E4
```

**Encoding: 4 × BE uint16 ÷ 32 = [CaseTemp, PFCTemp, HV1Temp, HV2Temp]. No multiplexer.**

| Bytes | Formula | Sample A | Sample B | CODACAN (mid-session) |
|---|---|---|---|---|
| 0–1 (BE uint16) | ÷ 32 | 0x010D = **8.41°C** | 0x02FD = **23.91°C** | **13.469°C** |
| 2–3 (BE uint16) | ÷ 32 | 0x0350 = **26.5°C** | 0x03D9 = **30.78°C** | **26.719°C** |
| 4–5 (BE uint16) | ÷ 32 | 0x0279 = **19.78°C** | 0x02E7 = **23.22°C** | **20.0°C** |
| 6–7 (BE uint16) | ÷ 32 | 0x0280 = **20.0°C** | 0x02E4 = **23.125°C** | **16.031°C** |

**Correction of prior analysis:** "B0 = 1 or 2 → multiplexor" was wrong. B0 is the **high byte of CaseTemp (BE uint16)**. As the charger warms from 8°C to ~24°C, the high byte naturally transitions from 0x01 (range 8–15.97°C) to 0x02 (range 16–31.97°C), which looked like a mux byte but is not.

**0x27A (CMS):** Identical structure — same 4 signals, same ÷32 encoding, same byte layout. CODACAN confirms: CaseTemp=12.969°C, PFCTemp=25.313°C, HV1Temp=18.813°C, HV2Temp=16.031°C.

**Status:** Charger thermally nominal. CaseTemp rose from 8.4°C (cold start) to ~24°C over the ~10 min session. PFCTemp consistently highest (~26–31°C), consistent with PFC stage being the main heat source.

---

### 0x615 — ChrgrSysLimits (8.3 Hz)

```
Sample: C1 00 C5 10 29 1D 76 00
```

Almost entirely static throughout the session:
- B0: 0xC1 = 193 = status/capability byte (bits 7–6 both set = online + capable)
- B2–B3: 0xC5/0xC4 0x10 = system current limit (minor variation)
- B4–B5: 0x29 0x1D = fixed configuration values
- B6: 116–118 (3 unique values) — system power or current limit in some unit

This ID contains configuration/limit parameters broadcast by the CMM system. Values are static during steady-state charging.

---

### 0x617 — ChrgrSysSts — System Status (8.3 Hz)

```
Sample: 0D BC 00 AB 83 00 00 00  (steady state)
        0D BC 00 AB 84 00 1F 00  (occasional)
```

- B0: Fixed 0x0D = 13 = charger system state code (active charging)
- B1: 188–204 (mostly 204=0xCC, occasionally lower) — likely AC voltage measurement or state sub-code
- B3: 171–173 (narrow range) — pack voltage measurement or power setpoint
- B4: 131–132 (0x83/0x84) — status flags, bit 0 toggles occasionally
- B6: bimodal — 0x00 (normal) or 0x1F (brief transient, likely frame-start of CC→CV or end-of-burst event)

---

### CMS Slave Charger IDs: 0x27A, 0x27B, 0x27C

**Architecture:** 1 CMM (master) + 1 CMS (slave). **CODACAN replay confirms Interpretation B: CMM and CMS each report their own individual measurements at the same ÷32 scale.**

Ground truth from CODACAN replay (codacharging.log):
- CMM AC: 14.3437A (14.34375 × 32 = 459 ✓); CMS AC: 14.7187A (14.71875 × 32 = 471 ✓)
- Total AC: 29.06A at 233.5V = **6,783 W** ✓ matches house meter ~6.8 kW
- CMM DC: 8.625A (276/32 ✓); CMS DC: 8.594A (275/32 ✓)
- Total DC: 17.22A at ~353V = **6,078 W** → efficiency 89.6%

**Interpretation A (CMM = combined total) is DISPROVEN.** CMM reports 14.34A, not ~29A. Both modules use identical ÷32 scale.

**0x27B — CMS AC Input (same byte structure as 0x27D):**
- B0-1 / 32 = AC voltage: ~233.5V (same AC line)
- B2-3 / 32 = AC current (CMS individual): **14.719 A** (14.71875 × 32 = 471)
- B4-7 / 64 = AC power (CMS individual), BE uint32: **3393.0 W** (0x00035043 = 217155)

**0x27C — CMS DC Output (same byte structure as 0x279):**
- B0-1 / 32 = HV voltage: **352.687 V** (11286/32)
- B2-3 / 32 = HV current (CMS individual): **8.594 A** (275/32)
- B4-5 / 32 = LV voltage: **13.156 V** (421/32)
- B6-7 / 32 = LV current: **1.375 A** (44/32)

**0x27A — CMS Temperature (same structure as 0x277):**
- 4 × BE uint16 ÷ 32 = [CaseTemp, PFCTemp, HV1Temp, HV2Temp]. No multiplexer.
- CODACAN confirms: CaseTemp=12.969°C (415/32), PFCTemp=25.313°C (810/32), HV1Temp=18.813°C (602/32), HV2Temp=16.031°C (513/32)

---

## Goal 3b: CODACAN BMS Tab — Ground Truth Values

From CODACAN replay screenshots (two moments during the charging session):

| Signal | Screenshot 3 (earlier, SoC=67.8%) | Screenshot 1 (later, SoC=68.2%) |
|---|---|---|
| SocMaster (%) | **67.8** | **68.2** |
| PackVoltage (V) | 349 | 350 |
| PackCurrent (A) | 16.4 | 16.4 |
| BattSentChargeLimit (A) | 84 | 62 |
| BattSentDischargeLimit (A) | 348 | 336 |
| MotorDriveLimit (A) | 348 | 336 |
| BattSentHVACLimits (A) | 2 | 2 |
| BMSmode | \<169\> | \<170\> |
| Chargemode | Charging | Charging |
| HVPowermode | HV On Charge | HV On Charge |
| KeepWakeNetworkBMS | Network Alive Request | Network Alive Request |
| HVBattCharging | ON | ON |
| ChrgPortOpen | OFF | ON |
| ChargeCableConnected | ON | ON |
| Cell V min / avg / max | 3.355 / 3.369 / 3.374 V | 3.360 / 3.374 / 3.378 V |
| Cell T min / avg / max | 7 / 7 / 8 °C | 7 / 7 / 9 °C |
| VminId / VmaxId | 96 / 76 | 96 / 76 |
| MinTempId / MaxTempId | 1 / 6 | 15 / 12 |
| BMSDrivingRange Expected/Max/Min | 66 / 122 / 33 km | 65 / 120 / 32 km |

**Key observations:**
- **SoC has 0.1% resolution** — confirmed by 67.8/68.2 display. Raw CAN value is SoC×10 (integer). At SoC=67.8 → raw=678=0x02A6.
- **SoC = 0x383 pair 0-1 ÷ 10**: From prior analysis, pair 0-1 ranges 676–709 over the session (67.6–70.9%), which brackets the observed range. Hypothesis is high confidence.
- **PackVoltage lower than charger output** (349–350V vs charger HV out 352–353V): small drop through cable/contactor — confirms CC mode.
- **PackCurrent 16.4A** stable across both screenshots, consistent with CMM 8.625A + CMS 8.594A = 17.22A (small cable/contactor loss).
- **BattSentChargeLimit decreases 84A→62A** as SoC rises — BMS throttling allowed charge current. Integer amps (1 A/LSB).
- **BMSmode 169→170** correlates with the pack conditioning activation event at t≈134.75s (Cluster 2). This is a meaningful state word, not a rolling counter — the increment marks conditioning turning on. Cross-corroborated by 0x390 B0 transitioning from 0x8D to 0x8C at the same event.
- **VminId/VmaxId** (96/76 in both snapshots): 8-bit unsigned cell indices. Coincidentally the same in these two snapshots but not necessarily stable — they will change as relative cell voltages shift during charging. **Resolved 2026-07-21/22:** these are the C CAN cell numbers directly — `VminId 96 = Cell96`, `VmaxId 76 = Cell76` (both 1-based since the 2026-07-22 DBC renumber; historically the DBC was 0-based and the relation was reported id = old Cell + 1). See `cell-index-mapping.md`. These GUI-read values are unaffected by the 0x381 DBC byte-order error corrected 2026-07-15 (CODACAN reads the LabVIEW cluster, which was always correct).
- **MinTempId/MaxTempId** (1/6 → 15/12): clearly dynamic — the module with the highest or lowest temperature can change as heat distributes through the pack.
- **BattSentDischargeLimit and MotorDriveLimit track together** (both 348A → 336A), suggesting they come from the same or adjacent fields in the same CAN message.

**BMS signal CAN IDs** (not yet confirmed — requires BMS_Recvd.vi analysis or targeted timeseries extraction):
- SocMaster, BMSDriveLimits: likely in 0x383 (10 Hz) or 0x381 (1 Hz)
- BMSBattStatus flags, BattPowermode: likely in 0x390–0x392 range (10 Hz)
- BMSVminVmax, BMSHVBattTemp: likely in 0x383 or dedicated IDs

---

## Goal 4: DCDC and BMS Status

### DCDC — IDs 0x1D5 and 0x48A (B CAN)

**Both DCDC IDs ARE present on B CAN during charging.** The Lear DCDC converter stays on the bus even when not actively switching.

**0x1D5 (40 Hz):**
- B4: Fixed **0x80 = 128** throughout the entire session → standby/inhibit flag
- B2: Perfect binary counter pattern (bits toggle at 2× intervals) → heartbeat counter confirms module is alive
- B6: 15–19 (5 unique values) — **Current_14V** (14V-rail output current). Not a voltage measurement: the DBC/hardware manual place the 12V/14V output *voltage* at B3.

**0x48A (4 Hz):**
```
00 00 00 00 36 33 00 00
00 00 00 00 37 33 00 00
```
- B0–B3: All zeros → no active conversion command
- **B4: 54–58 (0x36–0x3A)** — **14V thermistor** (temperature sensor on the DCDC/14V section), not a ÷4 voltage.
- **B5: 51–54 (0x33–0x36)** — **heatplate thermistor**, not a 12V terminal voltage.
- B6–B7: zeros

**Finding:** DCDC is in standby throughout the charging session (B0–B3 = 0). The Lear CMM module provides the 12V rail during charging (~13.1–13.2V, measured on 0x279 B4–5). 0x48A B4/B5 are DCDC-section thermistor readings (14V thermistor, heatplate thermistor), not the rail voltage. Standby is the expected behavior — the CMM has an integrated 12V auxiliary output for exactly this purpose.

---

### BMS on B CAN

**0x381 — BMS Cell Summary (1 Hz):**
```
Sample: 0D 2E 0D 39 0D 21 68 60
```

Uses the same encoding as C CAN cell voltages (0x000–0x019): `voltage_mV = (0x0D << 8) | Bx`

| Field | Bytes | Observed Range | Values |
|---|---|---|---|
| Min cell voltage | B0–B1 | 0x0D, 30–46 | **3,358–3,374 mV** |
| Max cell voltage | B2–B3 | 0x0D, 38–57 | **3,366–3,385 mV** |
| Avg cell voltage | B4–B5 | 0x0D, 21–33 | **3,349–3,361 mV** |
| B6 | — | 64–104 | Unknown: possibly SoC% × scale, or pack temp |
| B7 | — | Fixed 0x60 | Status / module identifier |

**Pack state assessment:** LFP cells at 3.35–3.39V → ~60–75% SoC at start of session. Max/min spread is tiny (~25 mV) → excellent cell balance. Session terminated early — cells never approached CV region.

**0x383 — BMS Pack Data (10 Hz):**

```
Sample (t=0):   02 A6 16 60 8A 09 09 00
Sample (t=592): 02 C5 16 60 66 09 09 00
```

| Bytes | Formula | Range | Confirmed value |
|---|---|---|---|
| 0–1 (BE uint16) | ÷ 10 | 676–709 | **SoC% — CONFIRMED** |
| 2 | fixed 0x16 | — | Module/status flag |
| 3 | fixed 0x60 | — | Module/status flag |
| 4 | 0x66–0x8A | varies | Unknown — second variable signal |
| 5–7 | fixed 0x09 0x09 0x00 | — | Static |

**SoC confirmed (timeseries extraction):**
- t=0s: 678 → **67.8%** (exact match with CODACAN screenshot)
- t=591.8s: 709 → **70.9%**
- Monotonically increasing throughout except one measurement glitch at t=84.4s (brief 0.7% drop, recovers in 0.5s — not a real SoC change)
- Update interval: ~23s between steps; resolution 0.1%
- Pack capacity cross-check: 3.1% ΔSoC / (6.08 kW DC × 0.1644 h) ≈ **32.2 kWh** — consistent with Coda ~33 kWh pack ✓

**Byte 4 (range 0x66–0x8A = 102–138):** Encoding TBD. Decreases over the session (0x8A=138 at start → 0x66=102 at end). Inversely correlated with rising SoC. Candidates: BattSentChargeLimit (which decreases from 84A to 62A as SoC rises — but range doesn't match 1 A/LSB), or a thermal/power limit signal.

**0x050 and 0x054 — Charging Command and Charger Status (50 Hz each):**

> **Correction 2026-07-23 — these are NOT GWM messages.** This section previously
> described 0x050 and 0x054 as "GWM Charging Commands" and 0x616/0x61A as echoes of
> them. That attribution was an inference with no supporting evidence and it was wrong.
> Transmitter-clock fingerprinting (below) places 0x050 in the BMS and 0x054/0x61A in the
> charger modules. The GWM is not involved: **the path is BMS → chargers directly.**
> The DBC (`BO_ 80 BMSChargerCmd: 8 BMS`), `coda.md`, and the CODACAN presence map all
> already said BMS; only this file said GWM.

| ID | Rate | Sender | Baseline data | Role |
|---|---|---|---|---|
| 0x050 | 50 Hz | **BMS** | `00 DC 0F F7 00 01 3E 01` | BMS → chargers: system-level charge command |
| 0x054 | 50 Hz | **CMM** | `33 16 01 60 01 FD 02 00` | CMM per-module status |
| 0x61A | 50 Hz | **CMS** | `33 16 01 60 01 FD 02 00` | CMS per-module status (identical content to 0x054) |
| 0x616 | 8.3 Hz | CMM | echo of 0x050 | CMM echo, byte-for-byte identical |

0x054 and 0x61A are therefore not "echoes of a GWM command" — they are the two charger
modules each reporting their own state. That is why their current fields read exactly
half of the BMS figure: each module reports its own share, rather than a command being
divided.

**Two unit systems for the same quantities.** 0x050 uses 0.1 units; 0x054/0x61A use the
Lear 1/32 convention. Pairing them frame-by-frame across a ramping 3-hour session:

| Quantity | 0x050 (×0.1) | 0x054 (÷32) | Median abs err | Split? |
|---|---|---|---|---|
| HV target voltage | B2–B3 = 408.7 V | B0–B1 = 408.69 V | 0.0125 V | no — shared rail |
| DC command current | B0–B1 = 22.0 A | B2–B3 = 11.00 A | 0.0000 A | yes, ratio exactly 2.0000 |
| AC station current | B5–B6 | B4–B5 | 0.0000–0.0125 A | yes |

The DC ratio held at exactly 2.0000 across 270k paired frames of a continuously ramping
signal, so the ×2 relationship is structural, not a static coincidence.

Note the earlier remark that "B3 in 0x054/0x61A alternates between 0x13 and 0x14" is
simply the low byte of the ramping HVCmdCurrent field, not a rounding artefact.

### Transmitter-clock fingerprinting — how the senders were established

Each ECU schedules its periodic messages off its own crystal, while the capture dongle
timestamps everything with one clock. So each ID's measured period, expressed as ppm
against nominal, fingerprints the *sending* module's oscillator. Clusters:

| Cluster | ppm | IDs |
|---|---|---|
| BMS | −31.7 … −31.9 | 0x270 0x275 0x378 0x381 0x382 0x383 0x390 **0x050** (also 0x2C2) |
| Chargers | +6.5 … +7.9 | 0x274 0x277 0x279 0x27A–0x27D 0x615–0x618 **0x61A** 0x61B |
| GWM | +22.1 | 0x271 |

The cleanest comparison avoids any nominal-rate assumption — same rate, same class:
**0x378 (known BMS, 20 ms) = −31.8 ppm and 0x050 (20 ms) = −31.7 ppm**, matching to
0.1 ppm, while the GWM sits 54 ppm away. The BMS anchors are justified by message
*content* (0x275 pack limits, 0x381 cell min/max, 0x383 SoC), so this is independent of
the CODACAN presence map that also says BMS.

Caveats: the method groups by oscillator, not by module name — two modules sharing a
clock source would be indistinguishable. 0x054 carries ~240 event-triggered extra frames
at 10 ms which inflate its frame count and drag a naive period estimate to −893 ppm;
corrected for those it lands near +6 ppm, i.e. charger cluster, but with roughly ±9 ppm
uncertainty it does **not** resolve CMM vs CMS on its own — that assignment comes from
the CODACAN presence map. 0x2C2 clustering with the BMS is consistent with the presence
map's note that 0x2C2 does not trigger the GWM indicator.

Script: `artifacts/j1772/pilot_phase9_clock_fingerprint.py`, `pilot_phase11_clock_corrected.py`.

---

## EVSE Advertised Current (J1772 Pilot) — 0x050 EVSEMaxCurrent

**Confirmed 2026-07-23.** `0x050` B5–B6 BE at **0.1 A/bit** is the EVSE's advertised
station current — the Coda's equivalent of the Vtrux `BELINV_pilotDuty` reference.

### Evidence: three known station ratings

| Station | Rating | Raw B5–B6 | Decoded | Car drew | AC V | Binding limit |
|---|---|---|---|---|---|---|
| ChargePoint | 30 A | 300 | **30.0 A** | 30.03–30.16 A | 199–206 | station |
| Driveway (home) | 32 A | 318 | **31.8 A** | 28.6–29.0 A | 232–236 | car |
| Marina Airport | 40 A (208 V) | 402 | **40.2 A** | 32.9–33.2 A | 204 | car |

All three ratings are independently known. Twelve charge sessions across eight
ChargePoint captures, two driveway, two Marina.

Cross-checked against nominal J1772 pilot duty (`I = duty × 0.6`): implied duty 50.00 %,
53.02 %, 66.98 % against nominal 50.00 / 53.33 / 66.67 — all within 0.31 percentage
points, far inside the ±2 % J1772 tolerance. The non-round decoded values (31.8, 40.2)
are what a measured PWM duty cycle converted to amps looks like; a stored configuration
value would be round.

### It reports the station's OFFER, not a commanded limit

At Marina the field reads **40.2 A while the car draws only 33.1 A**. If the BMS were
computing `min(station, car capability)` and commanding that, it would read ~33 A. The
driveway leg shows the same thing less dramatically (31.8 A advertised, 29.1 A car
ceiling at 232 V). Two independent legs therefore rule out the commanded-limit reading.

Nothing in 0x050 is clamped to the car's capability: the BMS DC current command sits at
22.0 A at every station regardless of rating, which at 408.7 V is ~9 kW — well above
anything ever delivered. The ~6.7 kW AC ceiling is enforced downstream by the charger
hardware and never appears as a negotiated value on the bus.

### Car-side power ceiling

Where the station is not the binding limit, implied car AC power is **6706–6751 W across
four sessions at two different supply voltages — a 0.7 % spread**. Where the station is
binding, draw pins to the advertised value within +0.16 A. `min(station, ~6.73 kW / V)`
explains all twelve sessions. This ceiling is empirical, not a spec figure, and has not
been checked for hot-pack or high-SoC derate.

### Split vs unsplit — which copy to use

| Message | Sender | Scale | Value | State-dependent? |
|---|---|---|---|---|
| **0x050 B5–B6** | BMS | 0.1 A | **full station** | **no — same idle and charging** |
| 0x616 B5–B6 | CMM | 0.1 A | full station (echo) | no |
| 0x054 B4–B5 | CMM | 1/32 A | per module (half) | yes — full when idle, half when charging |
| 0x61A B4–B5 | CMS | 1/32 A | per module (half) | yes |

`0x61A` halves the moment charging starts (960 → 480 at ChargePoint, 1018 → 509 at the
driveway; the doubled idle values are exactly 2× in both cases). `0x050` does not move
between states. **Use 0x050 EVSEMaxCurrent** — no state-dependent doubling to get wrong.

### Negative result — nothing else on the bus carries it

A sweep of every (bus, ID, byte) across all 12 sessions, testing 8-bit and 16-bit BE/LE
fields for the signature "static within a session, consistent within a station group,
different between station groups, scaling with the station rating", returned only the
0x050 / 0x616 / 0x054 / 0x61A family. Nothing from the BMS's other messages, nothing on
C CAN or D CAN. Near-misses all have mundane explanations: 0x615 B5 is measured current,
0x27B/0x27D B0 is the AC voltage high byte, 0x618/0x61B B5 is too coarse to discriminate
(32 A and 40 A both read 11).

**Caveat:** 0x050, 0x054, 0x616 and 0x61A are all one conversation. If the BMS misreads
the pilot, all four are wrong together — this is not an independent check of the pilot
itself. Also, B5 is `0x01` in every frame observed; linearity across three stations
proves the field spans B5–B6 (B6 alone gives 44/62/146, which does not track), but no
value below 256 or above 511 has been seen. A 12 A L1 EVSE would test the low end.

**Related:** the BMS appears to handle the J1772 handshake directly — 0x390 B2 toggles at
~5 Hz during pilot negotiation (see Cluster 1 above), and 0x390 is BMS-sourced
(−31.8 ppm).

Scripts: `artifacts/j1772/` — `pilot_phase6_buswide.py` (bus-wide sweep),
`pilot_phase7_confirm_0x050.py` (split vs scale), `pilot_phase8_scale_family.py`
(unit-system cross-check), `pilot_phase12_offer_vs_command.py` (offer vs command).

### Open items

1. **`CM_ BO_ 80` injection result needs reinterpreting (hypothesis, untested).** The DBC
   comment records a CODACAN bench observation: *"B4-B5=suspected rolling counter/
   validation (charger throttles to ~6A when non-baseline; frame likely rejected)."* Now
   that B5 is known to be the high byte of `EVSEMaxCurrent` (worth 25.6 A), a better
   explanation is available: zeroing B5 leaves `0x002C` = **4.4 A**, so the charger is not
   rejecting the frame — it is obeying a drastically reduced AC limit. Predicts a throttle
   to ~4.4 A against the ~6 A observed. **If confirmed this is a significant upgrade**: it
   would put the field on causal as well as correlational footing. Not yet tested — the
   original comment is left in place, marked superseded for B5 only. Re-run the bench
   injection sweeping B5–B6 to settle it.
2. **`0x054` has no DBC entry.** It is the CMM twin of `0x61A` (`BO_ 1562 CMSHVCmd`) with
   byte-identical content and the same ÷32 per-module scaling. Adding it would be a copy
   of that message under a different name and sender.
3. **Field width above 9 bits unverified.** B5 is `0x01` in every frame across all 12
   sessions, so only the 256–511 range has been exercised. A 12 A L1 EVSE (value 120,
   B5 = `0x00`) would test the low end; a 48 A+ station would test the high end.
4. **Car AC power ceiling (~6.7 kW) is empirical, not a spec figure.** Derived from four
   car-limited sessions at two supply voltages (6706–6751 W, 0.7 % spread). Not checked
   for hot-pack or high-SoC derate; the driveway sessions were long enough that taper may
   be mixed in.
5. **`0x054` CMM-vs-CMS clock placement unresolved.** After correcting for its ~240
   event-triggered extra frames it lands near +6 ppm — charger cluster, definitely not BMS
   — but the ±9 ppm uncertainty spans the gap between the CMM (+6.5…6.7) and CMS
   (+7.7…7.9) sub-clusters. The CMM assignment comes from the CODACAN presence map, not
   from this measurement. Re-measuring on a second long charge log would settle it.
6. **Station sample is three, not twelve.** Eight of the twelve sessions are the same 30 A
   ChargePoint. More distinct station ratings would strengthen the scale confirmation —
   particularly any station whose rating is not a multiple of the ones already seen.
7. **`0x615` remaining bytes uncharacterised** beyond B0 (status/capability) and B5
   (measured total AC current).

---

## Summary of Signal Confidence

**Encoding rule (CODACAN replay): Lear charger signals are BE uint16 ÷ 32 — with one confirmed exception.** `ACInPower` (0x27B / 0x27D bytes 4–7) is BE **uint32 ÷ 64**. The previous wording of this line ("ALL Lear charger signals use BE uint16 ÷ 32") is what drove the pattern-fill error in `CODA-B-CAN.dbc`; do not assume the 16-bit rule holds for a field that has not been individually checked.

The OutputValues messages **were** individually re-checked against this exception on 2026-07-21 and are genuinely four 16-bit ÷ 32 fields: testing bytes 4–7 of 0x279 / 0x27C as a uint32 ÷ 64 power field gives a median error of **+14,414 %** vs HVOutV × HVOutI, with **0.00 %** of frames within ±1 %. Their LV readings stand (13.31 V median LV voltage, LV current ~0 A). Per-charger DC-out ÷ AC-in efficiency lands at **90.7 % (CMM)** and **88.9 % (CMS)**, which is plausible for an OBC and independently corroborates the ÷64 power scale. Script: `artifacts/ac-voltage/acinpower_phase4_outputs.py`.

| ID | Signal | Confidence | Scale | CODACAN value |
|---|---|---|---|---|
| 0x27D B0–1 | AC voltage — CMM | **High** | ÷32, V | 233.5 V |
| 0x27D B2–3 | AC current — CMM (own) | **High** | ÷32, A | 14.344 A |
| 0x27D B4–7 | AC power — CMM (own) | **High** | ÷64, W (BE uint32) | 3334.9 W |
| 0x27B B0–1 | AC voltage — CMS (own) | **High** | ÷32, V | 233.5 V |
| 0x27B B2–3 | AC current — CMS (own) | **High** | ÷32, A | 14.719 A |
| 0x27B B4–7 | AC power — CMS (own) | **High** | ÷64, W (BE uint32) | 3393.0 W |
| 0x274 B0–5 | Fault flags | **High** | all-zero = no fault | 0 |
| 0x279 B0–1 | HV DC voltage — CMM | **High** | ÷32, V | 353.187 V |
| 0x279 B2–3 | HV DC current — CMM (own) | **High** | ÷32, A | 8.625 A |
| 0x279 B4–5 | LV output voltage — CMM | **High** | ÷32, V | 13.188 V |
| 0x279 B6–7 | LV output current — CMM | **High** | ÷32, A | 1.375 A (variable) |
| 0x27C B0–1 | HV DC voltage — CMS | **High** | ÷32, V | 352.687 V |
| 0x27C B2–3 | HV DC current — CMS (own) | **High** | ÷32, A | 8.594 A |
| 0x27C B4–5 | LV output voltage — CMS | **High** | ÷32, V | 13.156 V |
| 0x27C B6–7 | LV output current — CMS | **High** | ÷32, A | 1.375 A |
| 0x277 B0–1 | CaseTemp — CMM | **High** | ÷32, °C | 13.469°C |
| 0x277 B2–3 | PFCTemp — CMM | **High** | ÷32, °C | 26.719°C |
| 0x277 B4–5 | HV1Temp — CMM | **High** | ÷32, °C | 20.0°C |
| 0x277 B6–7 | HV2Temp — CMM | **High** | ÷32, °C | 16.031°C |
| 0x27A B0–1 | CaseTemp — CMS | **High** | ÷32, °C | 12.969°C |
| 0x27A B2–3 | PFCTemp — CMS | **High** | ÷32, °C | 25.313°C |
| 0x27A B4–5 | HV1Temp — CMS | **High** | ÷32, °C | 18.813°C |
| 0x27A B6–7 | HV2Temp — CMS | **High** | ÷32, °C | 16.031°C |
| 0x48A B4 | 14V thermistor | **Medium** (role confirmed, scale TBD) | temp, raw | 54–58 raw |
| 0x48A B5 | heatplate thermistor | **Medium** (role confirmed, scale TBD) | temp, raw | 51–54 raw |
| 0x381 B0–5 | Cell min/max/avg mV | **High** | same as C CAN cell IDs | 3355–3385 mV |
| 0x617 | ChrgrSysBusVoltage/Current/12V | **Medium** | partially decoded | TBD |
| 0x383 B0–1 | BMS SoC (%) | **High** | ÷10, % | 67.8% (start) → 70.9% (end) |
| 0x383 B4 | Unknown (inversely correlated with SoC) | **Low** | TBD | 0x8A→0x66 over session |

---

## Goal 5: Status Bit Event Analysis — Three Event Clusters

**Method:** Extracted all B CAN byte-level state transitions across the 594.9s session. Filtered to signals with ≤30 total transitions (discrete event markers only, excluding continuously-varying analogue bytes). Confirmed with full byte snapshots around each event window.

---

### Cluster 1 — Charge Startup / EVSE Handshake: t = 0–14s

Multiple B CAN signals undergo rapid state changes during the first 14 seconds, then lock into steady-state values for the remainder of the session.

#### Key signals:

**0x276 B0 — Charger State Machine:**
```
t= 0.9s   0x08 → 0x06   (phase 1: EVSE detected)
t= 7.3s   0x06 → 0x01   (phase 2: negotiation complete)
t= 9.4s   0x01 → 0x08   (brief revert — second handshake phase)
t=10.5s   0x08 → 0x01   (permanent: charging active)
```
0x276 B5 tracks identically (correlated). Final steady value = 0x01.

**0x439 B0 — EVSE Request Flag (binary):**
```
t= 8.0s   0x01 → 0x00   (charging request fulfilled — stays 0x00 forever)
```
B1 and B2 also go to 0x00 at t=8.0s (correlated multi-byte state).

**0x410 B6 — Inhibit Flag (binary):**
```
t= 7.9s   0x10 → 0x00   (clears at same time as 0x439 B0)
```

**0x410 B2 — Secondary Charger Flag:**
```
t= 9.1s   0x40 → 0x00   (drops at end of startup)
t=41.7s   0x00 → 0x40   (returns during steady-state — likely charger mode confirmation)
```

**0x390 B2 — Startup Negotiation Handshake:**
```
t= 1.6–4.5s   0x88 ↔ 0x89   (13 rapid toggles over 2.9s)
```
Toggles at ~5 Hz during EVSE pilot negotiation, then stops completely. B2 settles at 0x89 and never changes again. This appears to be J1772 CP signal detection or PWM handshake.

**0x390 B0 — Charging Confirmed Flag:**
```
t=13.9s   0x8C → 0x8D   (final startup step — charging fully established)
```
Stays at 0x8D until the conditioning event.

**Timeline summary:**
- t=0.9s: EVSE detected (0x276 B0 first move)
- t=1.6–4.5s: J1772 pilot negotiation burst (0x390 B2 toggles)
- t=7.9–8.0s: Charging request fulfilled (0x439 B0, 0x410 B6 both clear)
- t=9–10.5s: Final handshake (0x276 B0 settles at 0x01)
- t=13.9s: Charging confirmed (0x390 B0 → 0x8D)

---

### Cluster 2 — Pack Conditioning Activation: t ≈ 134.75–139.15s

The clearest single-signal event in the session. **Only 0x390 B0 changes** (on the B CAN bus-level event analysis). However, CODACAN replay screenshots also confirm a **BMSmode transition 169→170** that maps to this same event — giving two independent cross-corroborating signals from different system layers:

| Signal | Pre-conditioning | Post-conditioning |
|---|---|---|
| 0x390 B0 (GWM/charger side) | 0x8D | 0x8C |
| BMSmode (BMS side) | 169 | 170 |

BMSmode is therefore **not a rolling counter** — it is a meaningful state word where the increment 169→170 encodes the conditioning activation. The BMS and the GWM each independently register the same event on B CAN.

**0x390 B0 — Pack Conditioning Trigger:**
```
Pre-event: steady 0x8D (since t=13.9s)

t=134.75s   0x8D → 0x8C
t=134.85s   0x8C → 0x8D
t=135.85s   0x8D → 0x8C
t=136.05s   0x8C → 0x8D
t=136.25s   0x8D → 0x8C
t=136.45s   0x8C → 0x8D
t=137.35s   0x8D → 0x8C
t=137.45s   0x8C → 0x8D
t=137.55s   0x8D → 0x8C
t=138.55s   0x8C → 0x8D
t=138.75s   0x8D → 0x8C
t=139.05s   0x8C → 0x8D
t=139.15s   0x8D → 0x8C   ← settles permanently at 0x8C
```

13 rapid toggles (bit 0 of B0 flipping) over 4.4 seconds, then locks at 0x8C. This is the same pattern as the startup burst on B2 — a brief high-frequency handshake followed by a permanent state change.

**Full 0x390 snapshot (B0 only changes, all other bytes static):**
```
130.05  8D 8B 89 89 AD 88 85 00   ← pre-event steady state
134.75  8C ...                     ← burst begins
...
139.15  8C 8B 89 89 AD 88 85 00   ← post-event steady state (B0 = 0x8C)
```

**Interpretation:** 0x390 B0 bit 0 is a conditioning activation flag. The burst behavior (rather than a clean single edge) is consistent with a thermal system handshaking — possibly the pack blower/cooling pump enabling and the BMS acknowledging. Duration: ~4.4 seconds. Occurs at t=134.75s = 2 min 14 sec into the session.

No corresponding C CAN signal cleanly marks this event (C CAN changes in this window are all periodic-update messages cycling on their normal schedule).

---

### Cluster 3 — Log End Artifact (NOT end-of-charge): t ≈ 573–594s

> **⚠ INVALIDATED:** House meter confirms the full charging session used 6.5 kWh over ~58 minutes, while this log captures only the first 9.9 min (~1.11 kWh). The OBD adapter was removed from the car mid-session, ending the log while charging was still in progress. The events below are artifacts of that disconnection, not a real end-of-charge sequence.

**0x27B B1 — CMS AC Current (disturbance):**
```
t=570.1s   0x00 → 0x10
t=573.2s   0x00 → 0xF0   ← wild swings
t=575.9s   0xE0 → 0x00   ← readings collapse to zero
```
Previously interpreted as EVSE pilot disturbance before handle pull. More likely: the CAN bus disturbance caused by the OBD adapter being physically removed corrupted the last few frames of this message, producing invalid/overflow readings. The apparent "collapse to zero" is the adapter going offline, not AC power stopping.

**0x382 B0 — State byte transitions near log end:**
```
t=579.9s   0x87 → 0x88
t=586.9s   0x88 → 0x87
t=593.9s   0x87 → 0x88
```
Previously mapped to J1772 button press / charger stop / unplug. The rapid 4-way oscillation in the last 15 seconds is likely CAN noise from the OBD adapter being physically removed.

**Updated interpretation (confirmed in chargepointcharge.log):** The underlying value 0x87–0x88 at t≈580–594s is real — it reflects the charge stage counter at ~70% SoC. `0x382 B0` is a **monotonically-incrementing charge stage counter** that tracks progress through the charge session. In a full charge from 78.1% → 100% SoC, the counter steps 0x8B → 0x8C → 0x8D → 0x8E at ~6–8% SoC intervals. At 70% SoC the counter would be approximately 0x87–0x88, consistent with what this log shows. The oscillation was bus noise, not real state changes. See chargepointcharge.log section below.

---

## Summary Table — Status Event Signals

| Signal | Total transitions | Role |
|---|---|---|
| 0x276 B0 | 4 | Charger state machine (0x08=idle, 0x06=negotiating, 0x01=charging) |
| 0x439 B0 | 1 | EVSE request flag (1=pending, 0=fulfilled) |
| 0x410 B6 | 1 | Charger inhibit bit (0x10=inhibited, 0x00=active) |
| 0x390 B2 | 13 | J1772 pilot negotiation burst (startup only) |
| 0x390 B0 | 14 | System state flag: 0x8C=charging+conditioning, 0x8D=charging-only; burst = conditioning activation |
| 0x410 B2 | 2 | Secondary charger mode flag (drops at startup, returns at ~42s) |
| 0x382 B0 | 3 | ~~Charge stage counter~~ **CORRECTED: `Cell_T_avg` (avg pack cell temp, T = raw−128 °C)** — the rising values are pack warming during charge, not SoC stages. See `chargepointcharge-analysis.md`. |
| 0x27B B1 | many | ⚠ UNRELIABLE in this log — goes haywire at t=570-576s due to OBD adapter removal, not EVSE pilot loss |

---

## Key Findings Summary

1. **Buses present:** C CAN and B CAN only. D CAN absent from this capture - was plugged in, just no traffic.
2. **No gateway echo:** Zero IDs shared between B and C CAN during charging. Prior C CAN "ghost" IDs (0x0FF, 0x200–0x203, 0x300–0x304, 0x621–0x627) are native BMS diagnostic port output, not GWM re-broadcasts.
3. **Charger operating:** ~6.8 kW AC input at 233.5V / 29.1A combined (CMM 14.34A + CMS 14.72A, each at ÷32 scale). ~6.1 kW HV DC output at 353V / 17.2A combined (CMM 8.625A + CMS 8.594A). Efficiency ~89.6%. CC mode throughout. CMM and CMS each report their own individual measurements — Interpretation B confirmed, Interpretation A disproven.
4. **Zero faults:** 0x274 bytes 0–5 all zero for entire session. Handle pull was clean.
5. **DCDC standby:** Both 0x1D5 (B4=0x80 inhibit) and 0x48A (B0–B3=0) confirm DCDC offline. CMM maintains 12V bus at 13.5–14.5V.
6. **Charger handshake:** the **BMS** commands via 0x050 (50 Hz); CMM and CMS report their own per-module state via 0x054 and 0x61A (50 Hz each); CMM echoes the BMS command via 0x616 (8.3 Hz). The GWM is not in this path — corrected 2026-07-23, see the clock-fingerprinting section above.
7. **Cell balance in this session:** Min/max cell spread <25 mV throughout this 9.9-min session at mid-SoC (67.8–70.9%), consistent with good balance on the LFP plateau where all cells track together. Pack at 67.8% SoC at session start (confirmed by CODACAN replay). Note: a full charge session (`chargepointcharge.log`) later revealed ~79 mV resting OCV spread at end-of-charge — significant pack imbalance that only becomes apparent at high SoC.
8. **Three event clusters confirmed (status bit analysis):**
   - **Charge start (t=0–14s):** 0x276 B0 state machine (0x08→0x06→0x01), 0x439 B0 clears at t=8s, 0x390 B2 pilot negotiation burst (t=1.6–4.5s), 0x390 B0 → 0x8D at t=13.9s.
   - **Pack conditioning (t=134.75–139.15s):** 0x390 B0 bursts 13 toggles (0x8C↔0x8D) over 4.4s then permanently settles at 0x8C. Clear, isolated event with no other concurrent B CAN state changes.
   - **Log end artifact (t=570–594s):** ⚠ Previously interpreted as end-of-charge events. Invalidated — house meter confirms charging continued for ~48 min after the log ended. The OBD adapter was removed mid-session; the bus disturbances and 0x382 B0 transitions at the log end are disconnection artifacts, not real charge termination signals.

---

## Next Steps

- **Update DBC:** Add all confirmed charger signals to `CODA-B-CAN.dbc`: 0x27D, 0x27B (AC input), 0x279, 0x27C (HV+LV DC output), 0x277, 0x27A (temperatures) — all at ÷32, BE uint16. Add 0x381 (cell min/max/avg mV, BE uint16), 0x383 B0-1 (SoC ÷10), 0x382 B0 (Cell_T_avg, T=raw−128 °C — not a charge-stage counter).
- ~~**Identify the OV cell**~~ — **RESOLVED 2026-07-22.** The full-charge log `coda_20260722_173203_*` (75.7% -> 100% SoC, C+B+D CAN) settles it: the OV cell is **Cell82** (VmaxId 82), which peaks at **3778 mV** — above the 3750 mV cutoff and ~400 mV clear of every other cell at EOC. It dominates the charge-session argmax (86.7% of samples). This is the same failed-balance cell pinned in `battery-degradation.md` (VmaxId 82). The earlier candidates are *not* the OV cell: prior CODACAN `VmaxId=76` (`Cell76`, 0x012 B6-B7) peaks only 3348 mV, and the bonnydoon high-under-load cell `Cell84` (0x014 B6-B7, VmaxId 84) does not enter the charge argmax top-6. See `cell-index-mapping.md`.
- **Decode 0x383 B4:** Inversely correlated with SoC (0x8A→0x66 in short session). In `chargepointcharge.log` the charger current stepped down at t≈5400s — extract 0x383 B4 to confirm it maps to BattSentChargeLimit and find the step.
- **Identify BMS Drive Limits CAN IDs:** Determine which B CAN messages carry PackVoltage, PackCurrent, BattSentChargeLimit, etc. Candidates: 0x391, 0x392. Requires BMS_Recvd.vi analysis or targeted byte extraction.
- **Confirm BMSmode CAN ID:** Find which message carries BMSmode and extract timeseries to pinpoint the exact 169→170 transition timestamp and confirm it matches t≈134.75s (Cluster 2 conditioning event).
- **Decode 0x617 ChrgrSysSts:** From CODACAN/all_globals_signals.json, signals are ChrgrSysBusVoltage, ChrgrSysBusCurrent, ChrgrSys12VSysVoltage, ChrgrSys12VSysCurrent. Sample `0D BC 00 AB 83 00 00 00` — apply ÷32 and cross-check against 0x279 and CODACAN values.
- **Decode 0x390 fully:** B0 and B2 are confirmed event markers. B1 (34 transitions), B3 (75 transitions), B4 — cross-correlate against pack temperature (0x277/0x27A) to confirm thermal management link.
- **Decode 0x276 B0 difference:** In `codacharging.log` the active charging value is 0x01; in `chargepointcharge.log` it is 0x00 throughout. Capture a session that begins before plug-in to observe the full startup handshake and determine if the steady-state value differs by station or if the log started after handshake completion.
- ~~**Full charge session (priority)**~~ — **DONE** (`chargepointcharge.log`). OV limit confirmed at 3.750V. 0x382 B0 end-of-charge behavior confirmed. See cross-session section below.

---

## Cross-Session Findings — chargepointcharge.log (2026-02-19)

**Log:** `chargepointcharge.log` — Chargepoint station at work (208V AC), full charge from 78.1% → 100% SoC, then ~2 hours sitting plugged in. Full analysis in `chargepointcharge-analysis.md`.

### OV Termination — Confirmed at 3.750V (Fault, Not Normal Completion)

The max cell voltage (0x381 B2-3, BE uint16 → mV) climbed at ~1-2 mV/s in the final minutes and the BMS terminated charging **exactly at 3,750 mV**. The hypothesis that premature charge termination is caused by a cell hitting the 3.75V OV limit is confirmed.

**This is a cell overvoltage protection event, not a successful charge completion.** A healthy balanced pack ends charging via a CV taper — the charger holds a fixed voltage while current declines as all cells approach saturation together. What we observe here is a single cell racing ahead and tripping the hard OV protection limit while the rest of the pack is far below full (resting OCV spread ~79 mV, implying ~40–60% SoC difference between cells). Any charge termination at 3.750V should be treated as a **cell OV fault**, not a normal end-of-charge.

### Pack Imbalance — Quantified

| Metric | At EOC | 10 min rest | 80 min rest |
|---|---|---|---|
| Max cell | 3,752 mV | 3,453 mV | 3,409 mV |
| Min cell | 3,386 mV | 3,336 mV | 3,330 mV |
| Spread | 366 mV | 117 mV | **79 mV** |

The 366 mV spread at EOC is mostly surface charge on the high cell. True resting OCV spread is ~79 mV, representing a very large SoC difference between cells (~40–60% SoC spread on the LFP plateau). The highest cell hits OV while many cells are still well below full charge.

### Two-Phase CC Charge

Charging did not follow a simple CC→CV profile:

1. **Phase 1 (CC, ~7.8A CMM):** t=33s to t=5400s (~90 min). Max cell rose from 3.30V to ~3.77V terminal voltage.
2. **Brief stop + restart at reduced current:** At t=5400s the charger paused ~10s then restarted at ~4.2A CMM (~55% of Phase 1). Caused by BMS reducing BattSentChargeLimit as SoC approached 100%. NOT an OV event.
3. **Phase 2 (CC, ~4.2A CMM):** t=5411s to t=5442s (~31 min). Max cell rose from 3.72V to 3.75V → OV termination.

### SoC 100% Is Declared Before OV

BMS declared SoC = 100.0% at **t=4114s (68.6 min)**, when max cell was only ~3.41V. Charging continued for **21 more minutes** until the OV event. The 100% declaration is coulomb-counting-based and does not correspond to the cell voltage ceiling.

### 0x382 B0 — ~~Confirmed Charge Stage Counter~~ → Cell_T_avg (CORRECTED)

**SUPERSEDED:** 0x382 B0 is **average pack cell temperature** (`Cell_T_avg`, T = raw − 128 °C), not a charge-stage / SoC counter. The "monotonic sequence" below is the pack warming during the charge (0x8B=139 → 11 °C, 0x8E=142 → 14 °C); the 0x33/0x00 at the end are OBD-adapter-removal artifacts. Confirmed in `chargepointcharge-analysis.md`, `coda.md`, and `codacan-signal-decode-notes.md`. The original (incorrect) charge-stage reading is retained below for history.

Full monotonic sequence observed across 90-minute session:

| Value | Time | SoC approx. | Meaning |
|---|---|---|---|
| 0x8B (139) | t=33s | 78% | Charging begins |
| 0x8C (140) | t=841s | ~82% | Stage 2 |
| 0x8D (141) | t=2378s | ~91% | Stage 3 |
| 0x8E (142) | t=3994s | ~99% | Stage 4 / approaching full |
| 0x33 (51) | t=5448s | — | Brief charge-complete signal |
| 0x00 (0) | t=5449s | — | Charger standby |

The values 0x87/0x88 seen in `codacharging.log` at ~70% SoC are consistent with this counter at that SoC level. The rapid oscillation in that log was CAN bus noise from OBD adapter removal, not real state changes.

### 0x276 B0 Difference

In `codacharging.log`, the active-charging steady value was 0x01. In `chargepointcharge.log`, it was 0x00 throughout, with only a brief 0x33 at EOC. Cause unknown — station difference, log timing, or firmware. Needs a capture that starts before plug-in.

### Charger Power at 208V vs 233V (home L2)

| Parameter | Chargepoint 208V | Home L2 233V |
|---|---|---|
| AC voltage (CMM) | 203–209 V | 233.5 V |
| AC current (CMM) | 14.94 A | 14.34 A |
| DC current (CMM) | 7.81 A | 8.625 A |
| Combined DC power | ~5.5 kW | ~6.1 kW |

The charger draws similar AC current per module regardless of input voltage. Lower voltage → ~10% less power.
