# 0x410 Bit-Field Analysis: Interlock Status, Fault Register, and Shutdown Precursors

**Date:** 2026-02-24 (updated 2026-02-25)
**Logs used:** vtruxinterlocktest.log, vtruxinterlocktest2.log, movingaroundindriveway.log, generator on then off.log, rainychargedebug.log, rainychargedebug2.log, rainychargedebug3.log, rainychargedebug4.log, chargingafterturningaroundandnotusingextension.log, truklog_M0_T9.log (M0_b), truklog_M1_T13.log (M1_b), vtruxpartstruck.log, vtruxunplugpumpthenhvbatterylvconnector.log

## Summary

0x410 B0-B1 is a combined interlock/mode status and fault register. By comparing normal key-off shutdowns, interlock fault events (including a controlled switch press test), and charge failure events, individual bit functions were identified.

**Key findings:**
- **B0 bit3** is the **interlock loop status** — directly reflects whether the interlock circuit is closed (1) or open (0). Confirmed by 5 deliberate switch press/release cycles in vtruxinterlocktest2.
- **B1 bit6** is the **fault flag** — sets during all fault events, never during normal shutdowns.
- **0x644 B0** is a **leading indicator** — changes 14–21ms BEFORE 0x410 B0 during orderly shutdowns, but 7–12ms AFTER during interlock faults. Value direction also differs (decreases to 0x07 on orderly shutdown, increases to 0x17 on fault). **Confirmed VCU-sourced** (present on parts truck with no HV battery; see "Message Source Attribution" section below).
- **0x410 is BMS-sourced** — disappears when HV battery LV connector is unplugged, absent from parts truck with no battery.

## B0 — Mode, Interlock Status, and Fault Bits

```
bit7: Always 0 (unused)
bit6: Charge mode — sets when charging begins, clears on fault/shutdown
bit5: Always 0 (unused)
bit4: Key-on mode — sets during key-on startup, never sets in charge mode
bit3: INTERLOCK LOOP STATUS — 1 = loop closed/intact, 0 = loop open
bit2: Sets during charge startup, clears on fault — charge-related
bit1: Fault-only — sets during faults, never during normal shutdown
bit0: Sets during startup; clears on normal shutdown, stays set on fault
```

### B0 bit3 Confirmation: vtruxinterlocktest2

Truck keyed on with fuse panel open (interlock already tripped). Switch pressed and released 5 times:

```
t= 27.700  bit3 SET   (press 1 — switch closed, interlock loop intact)
t= 30.089  bit3 CLR   (release 1 — switch open, loop broken)
t= 31.684  bit3 SET   (press 2)
t= 33.455  bit3 CLR   (release 2)
t= 35.327  bit3 SET   (press 3)
t= 36.844  bit3 CLR   (release 3)
t= 38.597  bit3 SET   (press 4)
t= 40.039  bit3 CLR   (release 4)
t= 41.507  bit3 SET   (press 5)
t= 42.759  bit3 CLR   (release 5)
```

B1 stayed constant at `11001111` throughout — fault flag remained set, only the interlock status toggled.

### B0 bit3 in the Original Interlock Test

The "oscillation" observed after the HVAC pull in vtruxinterlocktest.log was the interlock switch being physically manipulated, not contactor re-close attempts:

**After HVAC pull (fault at t=63.2s):**
- bit3 cleared at fault, stayed clear for ~32s
- Toggled several times t=95–133s (connector manipulation)
- Mostly irregular timing (0.1–23s durations), consistent with physical handling

**After HVD pull (fault at t=240.8s):**
- bit3 cleared at fault, stayed clear for ~60s
- Single toggle at t=300.7s (13.5s duration)

Both startups in this log (before HVAC pull and after 12V cycle before HVD pull) show identical sequences — the 12V cycle fully cleared all fault state.

### B0 Transition Sequences

**Normal key-off (4 logs, all identical):**
```
00000000 → 00001000 → 00001001 → 00011001 → 00010001 → 00000001 → 00000000
                 b3↑          b0↑       b4↑        b3↓         b4↓,b0↓
```

**Charge failures (rainy/turnaround):**
```
00000000 → 00000100 → 00001100 → 00001101 → 01001101 → 01000101 → 00000111 → 00000011
                 b2↑        b3↑        b0↑       b6↑        b3↓     b6↓,b2↓    b2↓
```
Some sessions include an intermediate `01000111` step before `00000111`.

**Charge failures (M0_b / M1_b — log starts mid-charge):**
```
01001101 → 01001111 → 00001111 → 00000111 → 00000011
              b1↑        b6↓        b3↓        b2↓
```
Different first transition vs rainy/turnaround (bit1 sets vs bit3 clears). Starting B1 also differs (0x7F vs 0xBF). May reflect different charging sub-state at time of fault.

**Interlock faults (from key-on state):**
```
HVAC: 00011001 → 00010001 → 00010011 → 00000011
                      b3↓        b1↑     b4↓
HVD:  00011001 → 00010001 → 00000011
                      b3↓     b4↓,b1↑
```

**Interlock test 2 (keyed on with panel open — immediate fault):**
```
00000000 → 00000010 (bit7 never sets in B1, bit4/bit3 never set — interlock already open)
```

## B1 — System Ready + Fault Flag

```
bit7: System ready — sets ~4s after startup, stays set through shutdown
bit6: FAULT FLAG — sets ONLY during fault events, never during normal shutdown
bit5: Active/running — clears on any shutdown (normal or fault)
bit4: Active/running — clears on any shutdown (normal or fault)
bit3-0: Always 1111 (static)
```

### B1 Distinguishes Normal vs Fault Shutdown

| | Normal shutdown | Fault shutdown |
|---|---|---|
| Final B1 | `10001111` | `11001111` |
| bit6 | stays **0** | sets to **1** |
| bit5, bit4 | clear | clear |

This is the single-bit difference between a clean shutdown and a fault.

### B1 Transition Sequences

**Normal key-off:**
```
00111111 → 10111111 → 10001111
              b7↑       b5↓,b4↓
```

**All fault events (charge + interlock):**
```
00111111 → 10111111 → 11111111 → 11001111
              b7↑        b6↑      b5↓,b4↓
```

**Interlock test 2 (immediate fault on startup):**
```
00111111 → 11111111 → 11001111
           b7↑,b6↑    b5↓,b4↓
```
bit7 and bit6 set simultaneously — system never reached "ready without fault."

## Cascade Timing Relative to Voltage

Using the DCDC HV input voltage (0x18FFD6B3 B4-B5 LE x0.05, 10Hz) as the reference for when the DC bus voltage actually changes:

| Signal | HVAC Pull | HVD Pull | M0_b | M1_b |
|--------|-----------|----------|------|------|
| 0x410 first change | **-235ms** | **-149ms** | **-79ms** | **-7ms** |
| 0x410 second change | -35ms | ~0ms | +21ms | +47ms |
| 0x400 B0 | -60ms | +19ms | +103ms | +169ms |
| 0x050 B0-B3 | +38ms | +78ms | -5ms | +108ms |
| DCDC voltage | 0ms (drop) | 0ms (drop) | 0ms (spike 401V) | 0ms (spike 418V) |

0x410 is the earliest CAN indicator in all events. The DCDC reference is 10Hz (~100ms resolution), so sub-100ms precision is limited.

Charge failures show a voltage **spike** (charger overshoot into open DC bus) before collapse. Interlock pulls show a clean monotonic drop. The charger is a victim of the contactor opening, not the cause — see `failed-charge-analysis.md`.

## Shutdown Precursors: What Changes BEFORE 0x410 B0 bit3 Clears?

B0 bit3 clears during both normal key-off and faults. B1 bit6 (fault flag) distinguishes the two, but sets 50–300ms AFTER — not a leading indicator. A systematic comparison of 0x410, 0x644, 0x400, 0x600, and 0x411 across all shutdown types reveals that **0x644 B0 is the earliest reliable precursor**.

### 0x644 B0 — Leading Indicator (15–20ms Early Warning)

**Normal key-off (3 logs, all consistent):**

| Log | 0x644 B0 dt | Value | 0x410 B1 bit6 |
|-----|-------------|-------|---------------|
| generator on then off | **−17ms** | 0x10→0x07 | clear (clean) |
| movingaroundindriveway | **−14ms** | 0x10→0x07 | clear (clean) |
| rainychargedebug2 | **−21ms** | 0x10→0x07 | clear (clean) |

**Interlock faults (vtruxinterlocktest.log):**

| Event | 0x644 B0 dt | 0x400 epo dt | 0x410 B1 bit6 |
|-------|-------------|--------------|---------------|
| HVAC pull | **+12ms** | **+~175ms** | SET (fault) |
| HVD pull | **+7ms** | **+~175ms** | SET (fault) |

`0x400 hsc_bcm_epo` asserts ~175ms after 0x410 B0 bit3 clears — consistent across both pulls. B1 fault steps (0xFF→0xCF) follow epo by ~25ms.

**Charge failure (rainychargedebug.log, BMS-initiated disconnect):**

| Event | 0x644 B0 dt | Value | 0x410 B1 bit6 |
|-------|-------------|-------|---------------|
| charge failure | **−11ms** | 0x19→0x07 | SET @ +300ms |

### Three-Way Shutdown Classification

| Pattern | 0x644 B0 timing | 0x644 B0 direction | 0x410 B1 bit6 | Meaning |
|---------|-----------------|-------------------|---------------|---------|
| Normal key-off | BEFORE (14–21ms) | Decreases to 0x07 | Clear | VCM commands orderly shutdown |
| BMS-initiated fault | BEFORE (~11ms) | Decreases to 0x07 | Sets @ +300ms | BMS commands disconnect, flags fault |
| Interlock fault | AFTER (7–12ms) | Increases to 0x17 | Sets @ +200ms | Physical disconnection detected |

**Interpretation:** 0x644 B0 timing distinguishes orderly (BMS-commanded) vs abrupt (physical) disconnects. 0x410 B1 bit6 then confirms whether the orderly shutdown was normal or fault-triggered.

### 0x644 B0 Value Hypothesis

| Value | Binary | State |
|-------|--------|-------|
| 0x08 | 00001000 | Pre-contactor-close / startup |
| 0x10 | 00010000 | Contactors closed, key-on operation |
| 0x19 | 00011001 | Contactors closed, charging |
| 0x07 | 00000111 | Contactors commanded open / shutdown |
| 0x17 | 00010111 | Fault response (bits from both states) |

### 0x411 — Startup Only, Not Shutdown

0x411 B0 and B1 change ~100ms before 0x410 B0 during every startup (contactor close request?) but do NOT change during any shutdown. Not useful as a shutdown precursor.

### Startup Cascade (For Reference)

Consistent across all logs (0x410 B0: 0x09→0x19):
1. **−1.3s**: 0x644 B2/B6 change (VCU preparing — 0x644 confirmed VCU-sourced)
2. **−0.9s**: 0x400 B0 0x09→0x0D, 0x600 B0 0x22→0x26 (HV system arming)
3. **−0.25s**: 0x644 B0 0x08→0x10 (VCU commands contactor close)
4. **−0.1s**: 0x411 B0/B1 change (contactor close request)
5. **0s**: 0x410 B0 0x09→0x19 (interlock confirmed, key-on mode active)

### Validation

Script: `artifacts/shutdown_precursor_check.py` — single-pass streaming analysis across multiple logs.

## Other Signals Investigated

### 0x400 B0 — Downstream, Not Precursor

In normal shutdowns, changes 1–10ms AFTER 0x410 (essentially simultaneous, not before). In faults, lags by 168–175ms. Different base values by mode (key-on: `00001101`, charging: `00001000`). Normal shutdown: 0x0C→0x08 (bit2 clears). Fault: 0x0D→0x0F (bit1 sets).

### 0x644 B2-B3 — NOT Voltage; Confirmed CruiseMode + CruiseSpeedSetpoint

Previously listed as a BMS voltage candidate (~384V). Actual behavior in startup/shutdown/fault contexts: B3 toggles between `00000100` and `00000001` at 2Hz while B2 holds `10000000` (0x80=128). Not a voltage measurement. After fault, B2 bit7 clears; B3 toggling continues with shifted values.

**Confirmed:** B2-B3 encodes CruiseMode (hi nibble of B2) and CruiseSpeedSetpoint (12-bit Motorola, 0.125 km/h/count). The 0x80 idle value is the zero-speed baseline when cruise is inactive. See `notes/cruise-control-analysis.md`.

### 0x050 B0-B3 — Generator/Motor Command (Reactor)

Responds 38-108ms after voltage drop. Downstream of the fault, not causal.

## No Analog Interlock Voltage on Bus

Confirmed negative: the A123 BMS does not broadcast the interlock loop voltage on CAN. A comprehensive search of every byte and byte pair on the powertrain bus around both interlock events found no signal that drops gradually before the fault bits trip. All candidates were known HV voltage signals or BMS status bytes changing after the fault cascade. See `artifacts/interlock-analog-candidates.txt`.

## Message Source Attribution — Disconnect Test

**Method:** Two logs compared to identify which messages come from the BMS vs VCU:
1. **vtruxpartstruck.log** — parts truck with no HV battery and PE pump not on CAN. Only VCU and body modules active.
2. **vtruxunplugpumpthenhvbatterylvconnector.log** — main truck with PE pump CAN connector unplugged (~t=34), then HV battery LV connector unplugged (~t=75), then battery LV reconnected (~t=87), then 12V battery cycled (~t=118), then key-on (~t=130).

Script: `artifacts/pt_bus_id_comparison.py`, `artifacts/all_bus_dropout_scan.py`

### BMS-Dependent Messages (Require HV Battery LV Connector)

These 16 standard-frame IDs are present on the main truck but absent from the parts truck, and all disappear simultaneously when the HV battery LV connector is unplugged:

| ID | Freq | Notes |
|----|------|-------|
| 0x370–0x375 | 0.7 Hz each | 6 IDs; only present when BMS active |
| 0x400 | 77 Hz | HV system status (downstream of 0x410 in shutdown cascade) |
| 0x410 | 16 Hz | Interlock/mode/fault register (this document) |
| 0x411 | 16 Hz | Contactor request (changes at startup, not shutdown) |
| 0x412 | 8 Hz | |
| 0x420 | 8 Hz | |
| 0x430 | 16 Hz | |
| 0x440 | 16 Hz | B3-B4 confirmed post-contactor HV voltage |
| 0x460 | 16 Hz | |
| 0x506 | 8 Hz | Persists ~3s longer than others at key-off |
| 0x507 | 7 Hz | |

**Note:** These IDs are "BMS-dependent" — they require the BMS LV connector to be present. Whether each is transmitted BY the BMS or by the VCU in response to BMS presence is not yet determined. 0x410 and 0x411 are strong BMS candidates since they report interlock status that only the BMS would know.

### VCU-Sourced Messages (Confirmed)

These IDs are present on the parts truck (no HV battery, no pump) at the same rates as on the main truck — they are from the VCU or other 12V-powered modules:

- **0x644** and the entire 0x639–0x64B cluster (100Hz / 50Hz)
- **0x600**, 0x5A2, 0x592, 0x596, 0x505, and other 0x5xx/0x6xx IDs
- 0x051 (generator torque command), 0x308, 0x390, 0x395, 0x3FE

This confirms 0x644 is **VCU-sourced**, not a BMS status report. It leads 0x410 by 14–21ms in orderly shutdowns; whether it is a direct command to the BMS or an internal VCU state broadcast that happens to precede the BMS response is unconfirmed.

### Parts-Truck-Only Messages (Unexplained)

See `../../vtrux.md` — "Parts-Truck-Only Messages" section.

## Charge Failure Root Cause

Superseded by later analysis. See `specific-trucks/before-battery-swap-failed-charge-analysis.md` and `specific-trucks/after-battery-swap-charge-fail-analysis.md` for full charge failure analysis.

## Bit-Flip Cross-Reference: Interlock vs Charge Failures

Scripts: `artifacts/interlock_bit_catalog.py` (interlock events), `artifacts/failedcharge_bit_catalog.py` (charge failures), `artifacts/crossref_bit_flips.py` (cross-reference).

Five events compared: HVAC pull (t=63.2s) and HVD pull (t=240.8s) from the interlock test log; M0_b buckBoostFault (t=268.1s), M1_b buckBoostFault (t=583.1s), and full-charge-then-fail (t=5677.5s). Window: [t-0.5s, t+5.0s], standard-frame PT bus only.

### Universal Changes (All 5 Events)

7 (id, byte) positions change in every fault event regardless of type. Five are uncharacterized 6xx-series VCU-tier bytes (0x625 B4/B5, 0x644 B4, 0x646 B7, 0x649 B2). The two with known roles:

| ID | Byte | Known Signal |
|----|------|-------------|
| 0x412 | B2 | BMS SoC-based charge current ceiling (HIGH CONFIDENCE — r=0.999 vs 0x050 CCL during charge ramp; VCU tracks it closely during charging, static during driving because BMS holds full permission at normal drive SoC) — see `current-limits-investigation.md` Phase 4 |
| 0x420 | B2 | bcm_chg_max partial (12-bit Motorola nibble-split, EPRI-confirmed) |

0x412 B2 and 0x420 B2 zero out completely on interlock events. In charge failures they change by smaller amounts (0x420 B2: 0xB0->0x88/0xA0; 0x412 B2 in "full charge then fail": only 0x0E->0x0D), consistent with partial rather than full bus collapse in those events.

### Charge-Only Changes

30 positions change only in charge failure events. Notable clusters:

- **0x611 B0/B1/B2/B4/B6/B7** and **0x610 B0** — change in all 3 charge events, absent from both interlock pulls. 0x611 B0/B6 appear in the earlier-precursor window (~1s before 0x410 B0 in rainychargedebug — see "Earlier Precursors" above).
- **0x647 B0, 0x648 B0/B1/B2/B7** — M0_b and M1_b only, not present in interlock events.
- **0x644 B2, B6** — these bytes respond to charge failures but not to interlock trips (contrast: 0x644 B0/B1 change in both fault types — see "Leading Indicator" section).

### Interlock-Only Changes

49 positions change only in interlock events. The large count is largely explained by:

1. **GENE MCU cluster (0x470, 0x471, 0x478, 0x482, 0x483, 0x484)** — active during driving but not during charging; their bus traffic changes on sudden DC collapse only in interlock events.
2. **0x681 (B0/B1/B2/B3/B5/B6)** — consistent across both interlock pulls, absent from all charge failure logs. Source and role unidentified.
3. **0x597 B3/B4/B5** — change in interlock, not in charge failures.
4. **0x592 B4** — interlock only.

### Cascade Ordering (Spearman Rank Correlation)

| Pair | r | n |
|------|---|---|
| M0_b vs M1_b | **+0.844** | 28 |
| HVAC vs HVD | +0.578 | 27 |
| HVAC vs M0_b | +0.289 | 28 |
| HVAC vs M1_b | +0.182 | 28 |
| HVD vs M0_b | +0.025 | 27 |
| HVD vs M1_b | -0.070 | 27 |

The two charge failure events (M0_b, M1_b) follow nearly the same cascade sequence (r=0.844). The two interlock events are moderately similar to each other (r=0.578). Interlock vs charge: low to no correlation in ordering — consistent with different fault response paths despite sharing some terminal states.

### Value Comparison

Only 2 positions have identical transitions across all events where they appear:
- **0x050 B3**: 0x01->0x00 in all 4 events (generator/motor command)
- **0x412 B0**: 0x2D->0x00 in all 4 events (current-related)

All other overlapping positions show different source values, different target values, or different dt offsets across fault types.
