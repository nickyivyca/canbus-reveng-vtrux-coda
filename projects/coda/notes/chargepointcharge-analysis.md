# Coda Chargepoint Full-Charge Session Analysis

**Log:** `chargepointcharge.log`
**Session:** Full charge at Chargepoint L2 station at work (208V AC, single-phase)
**Log duration:** 12,178.8s (203.0 min, 3h 23min) — captures the full charge AND ~2 hours of sitting while still plugged in
**Total frames:** 4,195,013
**Analyzed:** 2026-02-19

> **⚠ Cell numbering updated 2026-07-22.** The C CAN DBC (`CODA-C-CAN-cells.dbc`) is now
> **1-based** (`Cell1…Cell104`), matching the BMS's own `VmaxId`/`VminId` directly
> (VmaxId 82 = Cell82). It was previously **0-based** (`Cell0…Cell103`). Cell numbers in this
> file have been updated to 1-based; **any older artifact, CSV, plot, or export is still
> 0-based — add 1 to reconcile** (old `#94` = current `Cell95`). `VmaxId`/`VminId`/"BMS index"
> values were always 1-based and are unchanged. `MinTempId`/`MaxTempId` are a separate index,
> unaffected. See `cell-index-mapping.md`.

---

## Channel Identification

| Bus | Anchor IDs |
|---|---|
| **C CAN** | 0x000–0x019 (individual cell voltages), 0x200–0x203, 0x300–0x304 |
| **B CAN** | 0x27x (Lear charger), 0x38x (BMS), 0x390, 0x410 |

D CAN absent from this capture.

---

## Session Overview

| Parameter | Value |
|---|---|
| Active charging duration | ~90.7 min (t=33s to t=5442s) |
| Sitting while plugged in | ~112 min (t=5442s to end) |
| Starting SoC | 78.1% |
| SoC at end of active charge | 100.0% |
| SoC when BMS declared 100% | t=4114s (68.6 min) |
| End-of-charge cause | Max cell OV at 3.750V |
| AC input voltage | 203–209V (Chargepoint 208V circuit) |
| DC charging current per module | ~7.8A (CMM), rising to end at reduced ~4.2A phase |

---

## Goal 1: End-of-Charge Cell Voltage Analysis

### CONFIRMED: 3.750V OV Cutoff

The hypothesis that "charging terminates when a cell hits 3.75V" is **exactly confirmed**.

The max cell voltage (from `0x381 B2-3`, B CAN) approached 3.750V at a rate of ~1-2 mV/s and charging terminated at the exact moment the cell reached 3,750 mV:

```
t=5428.9s  max cell = 3735 mV
t=5429.9s  max cell = 3736 mV
t=5430.9s  max cell = 3737 mV
t=5431.9s  max cell = 3739 mV
t=5432.9s  max cell = 3740 mV
t=5433.9s  max cell = 3741 mV
t=5434.9s  max cell = 3742 mV
t=5435.9s  max cell = 3743 mV
t=5436.9s  max cell = 3745 mV
t=5437.9s  max cell = 3746 mV
t=5438.9s  max cell = 3747 mV
t=5439.9s  max cell = 3748 mV
t=5440.9s  max cell = 3750 mV  ← OV threshold hit
t=5441.9s  max cell = 3751 mV
t=5442.2s  HV current → 0.031 A  ← charger stops
t=5442.9s  max cell = 3752 mV  (surface charge peak, charger already stopping)
t=5444.9s  max cell = 3741 mV  (surface charge relaxing)
t=5445.9s  max cell = 3735 mV
```

**OV limit: 3.750V** (3,750 mV). This is the hard BMS protection threshold — a cell overvoltage fault, not a normal end-of-charge.

> **Important:** A healthy, balanced pack would end charging via a CV (constant-voltage) taper — the charger holds voltage fixed while current declines as all cells approach saturation together, eventually reaching a minimum current cutoff. What we observe here is categorically different: a single cell racing ahead and tripping the hard OV protection limit while the rest of the pack is nowhere near full. Every charge termination at 3.750V should be treated as a **cell OV fault event**, not a successful charge completion. The BMS is stopping to protect the high cell from damage, not because the pack is full.

---

### Pack Imbalance — Quantified

At the moment of OV termination:

| Cell Metric | At EOC | After 10 min rest | After 80 min rest |
|---|---|---|---|
| Max cell | 3,752 mV (3.752V) | 3,453 mV | 3,409 mV |
| Min cell | 3,386 mV (3.386V) | 3,336 mV | 3,330 mV |
| Spread | **366 mV** | **117 mV** | **79 mV** |

The 366 mV spread at EOC is largely surface charge on the high cell (it collapses rapidly after current stops). The **true resting OCV spread** settles to approximately **79–83 mV** after ~20 minutes of relaxation, and remains stable.

For LFP chemistry on the plateau, 80 mV OCV spread corresponds to a very large SoC difference between cells — likely **40–60% SoC spread** between the highest and lowest cells in the pack. The high cell hits OV while the lowest cells are still well below mid-charge.

**Conclusion:** The pack has a severe balance problem. The highest cell terminates charging before the rest of the pack can reach full SoC. The car reaches "100% SoC" (BMS declaration) while most cells are still in the 3.33–3.41V range (flat LFP plateau, well below full voltage).

---

### Two-Phase CC Charge — End-of-Charge Sequence

There was NOT a simple constant-current cutoff. Instead, charging ended in two stages:

**Phase 1 (CC, full current): t=33s to t=5400s (~90 min)**
- CMM HV current: ~7.75–7.81A steady
- Max cell rising slowly: 3.304V → 3.774V over 90 minutes

**First interruption at t≈5400s:**
```
t=5399.6s   7.344 A  (current starts dropping)
t=5399.7s   7.031 A
t=5399.8s   6.781 A
t=5400.0s   6.500 A
t=5400.1s   6.344 A
t=5400.2s   0.750 A
t=5400.3s   0.031 A
t=5400.4s   0.000 A  ← charger stops (10s pause)
t=5410.5s   0.438 A  ← charger restarts (ramp-up)
t=5411.6s   4.188 A  ← stable at reduced current
```

During Phase 1, the max cell reached ~3.774V as the current ramped down (terminal voltage overshoot). After the 10-second pause, the cell relaxed back to 3.721V and restarted at ~55% of original current.

**Interpretation of first interruption:** The BMS reduced `BattSentChargeLimit` as SoC approached/exceeded 100%, causing the charger to pause and restart at a lower setpoint. This is NOT the OV cutoff — it's the BMS-commanded current reduction into the top-balance phase. (The terminal voltage of 3.774V during current ramp-down is consistent with internal resistance drop at ~7.8A; the OCV at that point was below 3.750V.)

**Phase 2 (CC, reduced current): t=5411s to t=5442s (~31 min)**
- CMM HV current: stable 4.188A (~55% of Phase 1 current)
- Max cell rising slowly: 3.721V → 3.750V over 31 minutes

**Final cutoff at t=5442.2s:**
- Max cell hit 3,750 mV exactly → BMS OV termination

---

### 0x382 B0 — Cell_T_avg Temperature (CORRECTION: Previously Misidentified as Charge Stage Counter)

**CORRECTION (2026-03-25):** This section originally interpreted B0 as a charge stage counter. It is not. 0x382 B0 is `Cell_T_avg` — average pack cell temperature, encoded as `T°C = raw − 128`. The progression 0x8B→0x8E was the pack warming from 11→14°C during charging. See `coda.md` 0x382 entry for authoritative decode.

| Transition | Time | SoC at transition | Correct interpretation |
|---|---|---|---|
| → 0x8B (139) | t=32.9s | 78.1% | Pack avg temp = 11°C (charging begins cold) |
| → 0x8C (140) | t=840.8s (14.0 min) | ~82% | 12°C (pack warming) |
| → 0x8D (141) | t=2377.8s (39.6 min) | ~91% | 13°C |
| → 0x8E (142) | t=3993.7s (66.6 min) | ~99% | 14°C |
| → 0x33 (51)  | t=5447.9s (post-EOC) | — | Invalid sentinel (−77°C) — not a valid temperature |
| → 0x00 (0)   | t=5448.9s (post-EOC) | — | Invalid sentinel (−128°C) — charger standby |

**Corrected interpretation:** The 0x8B→0x8E steps simply reflect the pack warming by 3°C over the 66-minute charge session. There are no discrete "charge stages." The roughly equal spacing was a coincidence of the pack's thermal rise rate and the integer quantization. 0x33 and 0x00 are invalid sentinels, not charge-complete signals. In `codacharging.log`, the transitions near the log end were not OBD artifacts — they were genuine temperature readings from that shorter session.

---

### SoC vs Cell Voltage — BMS Declares 100% Early

The BMS declared 100% SoC (0x383 B0-1 = 0x03E8 = 1000, ÷10 = 100.0%) at **t=4114s (68.6 min)**, while the max cell was at approximately **3.41V** — 340 mV below the OV limit.

```
t=3500s (58 min)   SoC = 96.7%   max cell ~3405 mV
t=3720s (62 min)   SoC = 97.8%   max cell ~3409 mV
t=3942s (65.7 min) SoC = 99.0%   max cell ~3411 mV
t=4016s (66.9 min) SoC = 99.4%   max cell ~3413 mV
t=4114s (68.6 min) SoC = 100.0%  max cell ~3415 mV  ← 100% declared
t=5442s (90.7 min) SoC = 100.0%  max cell = 3751 mV  ← OV termination
```

**Charging continued for 21.4 more minutes after 100% SoC was declared.** The charger did not stop at 100% SoC. The BMS's 100% declaration is based on coulomb counting or a voltage threshold and does not align with cell-level OV protection. The OV event is the actual hard termination.

Full charging trajectory (every ~10 min):

| Time | Max Cell | SoC |
|---|---|---|
| t=33s (1 min) | 3,304 mV (3.304V) | 78.1% |
| t=634s (11 min) | 3,382 mV | 80.9% |
| t=1235s (21 min) | 3,385 mV | 84.1% |
| t=1836s (31 min) | 3,391 mV | 87.6% |
| t=2437s (41 min) | 3,397 mV | 90.7% |
| t=3038s (51 min) | 3,402 mV | 94.2% |
| t=3639s (61 min) | 3,406 mV | 97.4% |
| t=4240s (71 min) | 3,417 mV | **100.0%** |
| t=4841s (81 min) | 3,444 mV | 100.0% |
| t=5442s (91 min) | **3,751 mV** | 100.0% → **OV** |

Note the large voltage jump from 3,444 mV at t=4841s to 3,751 mV at t=5442s — this is the 31-minute Phase 2 (reduced current) segment where the imbalanced cell rapidly charged up while the BMS continued reporting 100% SoC.

---

## Goal 2: Charge Start Comparison vs `codacharging.log`

### AC Input Power

| Parameter | `chargepointcharge.log` | `codacharging.log` |
|---|---|---|
| AC voltage (CMM) | **203–209 V** (Chargepoint 208V) | 233.5 V (home L2) |
| AC current (CMM) | **14.94 A** | 14.34 A |
| CMM AC power | **~3,032 W** | ~3,349 W |
| Combined AC power | ~6,064 W | ~6,783 W |
| DC current (CMM) | **7.81 A** | 8.625 A |

The Chargepoint session operates at very similar **AC current per module** (~14.9A vs 14.3A), but lower voltage → ~10% less total power. The charger appears to run at maximum current regardless of input voltage (within its input range), consistent with a constant-current input regulation strategy.

### Starting Conditions

| Parameter | `chargepointcharge.log` | `codacharging.log` |
|---|---|---|
| Starting SoC | **78.1%** | 67.8% |
| Starting max cell | ~3,304 mV | ~3,360 mV |
| Starting min cell | (not extracted) | ~3,358 mV |

### 0x276 B0 — PTC Heater Power Difference

**CORRECTION:** 0x276 is `HVACStatus`; B0 is `PTC_PowerConsumption` (scale 0.1 kW), not a charger state machine signal.

In `codacharging.log` (home L2, cold session): B0 = 0x08 → 0x06 → 0x01 (0.8 → 0.6 → 0.1 kW), then steady 0x01 (0.1 kW). The PTC heater was active at session start and tapered down as the cabin/pack warmed.

In `chargepointcharge.log` (Chargepoint, warmer conditions): B0 = **0x00** (0 kW) throughout — PTC heater not active. Post-EOC transitions to 0x33 then 0x00 are invalid sentinels matching the same pattern seen in 0x382 Cell_T_avg at charge stop.

### Startup Handshake Timing (0x390 B0, 0x439 B0)

Not extracted for direct comparison in this session. Recommended for a follow-up capture that begins before plug-in.

---

## Key Confirmed Signals (Updated)

| Signal | ID | Bytes | Bus | Scale | Notes |
|---|---|---|---|---|---|
| Max cell voltage | 0x381 | 2–3 | B CAN (3) | BE uint16 → mV | OV limit = **3,750 mV**. Cross-checked vs 0x617 pack voltage: values diverge (~3300–3750 vs ~3500–3560 at same timestamps), confirming these are individual cell voltages, not pack voltage. |
| Min cell voltage | 0x381 | 0–1 | B CAN (3) | BE uint16 → mV | |
| Avg cell voltage | 0x381 | 4–5 | B CAN (3) | BE uint16 → mV | |
| SoC | 0x383 | 0–1 | B CAN (3) | BE uint16 ÷ 10 = % | **Confirmed 100.0% = 0x03E8** |
| Cell_T_avg (pack avg temp) | 0x382 | B0 | B CAN (3) | uint8, T=raw-128 °C | 11→14°C during this session (pack warming). 0x33 and 0x00 are invalid sentinels. **CORRECTION**: previously misidentified as charge stage counter. |
| HV DC current (CMM) | 0x279 | 2–3 | B CAN (3) | BE uint16 ÷ 32 = A | |
| HV DC current (CMS) | 0x27C | 2–3 | B CAN (3) | BE uint16 ÷ 32 = A | |
| AC voltage (CMM) | 0x27D | 0–1 | B CAN (3) | BE uint16 ÷ 32 = V | 203–209V at Chargepoint |
| AC current (CMM) | 0x27D | 2–3 | B CAN (3) | BE uint16 ÷ 32 = A | ~14.94A at Chargepoint |
| Pack voltage (charging) | 0x617 | 0–1 | B CAN (3) | BE uint16 ÷ 10 = V | ChrgrSysBusVoltage. ~350–356V during charge. |
| Total DC charge current | 0x617 | B3 | B CAN (3) | byte ÷ 10 = A | ChrgrSysBusCurrent. ~15.5A during Phase 1 (CMM + CMS combined). Cross-checked against 0x279 + 0x27C individual module currents. |
| BattSentChargeLimit | 0x275 | B1 | B CAN (3) | byte × 2 = A | **Confirmed via CODACAN ground truth** (84A at 67.8% SoC → raw 42). Drops to 20A (raw 10) at EOC; stays low while plugged in at 100% SoC. Also governs regen braking — recovers quickly after driving off a full charge. |
| BattSentDischargeLimit or MotorDriveLimit | 0x275 | B0 | B CAN (3) | byte × 2 = A | **Tentative** — raw 168 × 2 = 336A matches CODACAN reading when BattSentChargeLimit = 62A. CODACAN showed both BattSentDischargeLimit and MotorDriveLimit at 336A simultaneously; unclear if B0 drives one or both. Decreases as SoC rises (348A at 67.8% → 336A at 70.5%). Needs driving log to confirm. |
| Individual cell voltages | 0x000–0x019 | 0–7 | C CAN (2) | BE uint16 → mV | Not extracted this session |

### DBC Skeleton Correction

The skeleton DBC labels **0x381 as `BMSDriveLimits`** (with `BattSentChargeLimit` at B2, scale 1) — this is **wrong**. Empirical data confirms 0x381 contains individual cell voltage statistics (min/max/avg in mV). The "medium confidence" caveat in the skeleton was warranted.

`BattSentChargeLimit` is confirmed in **0x275 B1**. The skeleton DBC labels 0x275 as `BMS_Recvd_0x275` but the direction convention is uncertain.

---

## Next Steps

1. ~~**Identify which cell is the OV cell**~~ — **RESOLVED 2026-07-22.** Settled by the full-charge log `coda_20260722_173203_*` (75.7% -> 100% SoC, C+B+D CAN), not this session: the OV cell is **Cell82** (VmaxId 82, 0x014 B2-B3), peaking at 3778 mV — ~400 mV clear of every other cell at EOC and 86.7% of the charge-session argmax. Same failed-balance cell as `battery-degradation.md`. The earlier candidate `VmaxId 76` = `Cell76` (0x012 B6-B7) peaks only 3348 mV, and the bonnydoon high-under-load cell `Cell84` (0x014 B6-B7) never enters the charge argmax top-6 — the high-under-load and OV cells are different. See `cell-index-mapping.md`.

2. ~~**Confirm 0x382 B0 interpretations**~~ — **CORRECTED (2026-03-25)**: 0x382 B0 is `Cell_T_avg` temperature (T=raw-128 °C). The 0x8B→0x8E progression was pack temperature rising 11→14°C during charging, not charge stages. 0x33 and 0x00 are invalid sentinels. No action needed in `charging-analysis.md` — see correction note in this file's 0x382 section above.

3. **Capture a session from plug-in** to observe the full 0x276 B0 startup handshake and compare timing to `codacharging.log` Cluster 1 events.

4. **Decode remaining 0x275 bytes**: B0 (tentative BattSentDischargeLimit/MotorDriveLimit), B3, B5, B7 need a driving log with known operating conditions (ideally one that enters low-power/limp mode) to confirm signal identities and scaling.

5. **Pack balance monitoring**: With `0x381` cell min/max at 1 Hz, we can track the resting OCV spread over time across multiple charge sessions to see if the balance improves or worsens.
