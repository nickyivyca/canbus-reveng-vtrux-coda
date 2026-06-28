# Vtrux Powertrain Bus — Message Catalog

**Bus:** Powertrain bus (bus 3 in generator/driveway logs; bus 1 in code-reading logs)
**Protocol:** Via Motors proprietary + J1939 extended frames
**Identification fingerprint:** 0x051 present @ ~100 Hz; extended IDs (0x18xxxxxx); no 0x0C1/0x1F5

For bus identification across log sets, see `threebusinvestigation.md`.
For voltage/current signal investigation methodology and correlation scan results, see `context-voltage-current.md`.

---

## Confirmed Signals

### 0x051 — Composite Command Message (Generator Torque + Engine RPM Reference)

**0x051 is a 6-byte composite command message: generator torque command (B1-B2) and engine/generator RPM reference (B3-B4).**

| Bytes | Signal | Encoding | Confidence |
|-------|--------|----------|------------|
| B1-B2 (LE) | Generator torque command | `(b2<<8\|b1) - 32768`; <0=generating, >0=backdriving | **CONFIRMED** |
| B3-B4 (LE) | **Engine/generator RPM reference** | `(b4<<8\|b3) - 32768`; null = -1 when engine off; active range +512 to +2047 = ~512-2047 RPM | **CONFIRMED** — r=0.88-0.95 vs 0x63C B6 measured RPM; visual overlay confirms exact tracking |
| B5 | Rolling counter | 0x00-0x0F (4-bit, repeating) | Confirmed |

**Rate:** ~100 Hz. **DLC:** 6.

**Neutral:** B1-B2 = 0x8000 (32768 -> 0), B3-B4 = 0x807F (32767 -> -1 when engine off).

**Notes:** Gen torque (B1-B2) flattens to ~0 when vehicle goes full-electric. RPM reference (B3-B4) is null when engine off and active whenever engine is running. Likely purpose: generator inverter uses this VCU-commanded RPM reference as a safety check against measured RPM (0x63C B6) -- divergence indicates coupling failure or rotor estimation failure, triggering inverter shutdown.

**B3-B4 encoding detail (zone+fine structure):** B4 is a discrete zone selector (7 values: 127=null, 130-135=active; each zone = 256 RPM band). B3 is fine RPM within the zone. Null gap: centered 0-511 never appears -- engine never idles below ~512 RPM when active. "Digital" steps at low RPM = B4 zone dithering at idle (~512-767 RPM, B4=130-131). "Analog" above ~1500 RPM = B4 fixed at 134 or 135, B3 sweeping full range. Max = ~2047 RPM (B4=135, B3=255). Bit-for-bit identical to 0x052 B2-B3.

**Previous misidentification (corrected 2026-03-03):** B3-B4 was cataloged as "Traction motor DRIVE torque command" based on being null in EV-only mode and active during hybrid driving. Null-when-engine-off is equally consistent with an RPM reference. The misidentification was resolved via mixed-encoding correlation decomposition (B3-alone r~0 vs all generator state signals during cruise) and visual overlay with 0x63C B6. See `notes/cruise-control-analysis.md` Phase 6.

**Scripts:** `artifacts/find_drive_torque_feedback.py`, `artifacts/find_drive_cmd_vs_5a2.py`

---

### 0x052 — Engine RPM Reference Broadcast (Addressee Unknown)

| Field | Value |
|-------|-------|
| Bytes | B2-B3, little-endian |
| Encoding | Unsigned centered at 32768: `rpm_ref = ((b3 << 8) \| b2) - 32768` |
| Neutral | 32767 (-1 when engine off) |
| Active range | +512 to +2047 centered = ~512-2047 RPM |
| Rate | 100 Hz |
| DLC | 5 |
| Confidence | **HIGH** — bit-for-bit identical to 0x051 B3-B4 (confirmed engine RPM reference) |

**Byte map:**

| Byte | Role |
|------|------|
| B0 | Constant 0x00 |
| B1 | Constant 0x80 (= 0x8000 LE neutral, i.e., B0-B1 always at 32768) |
| B2-B3 | **Engine/generator RPM reference** (LE-32768; same zone+fine encoding as 0x051 B3-B4) |
| B4 | Nibble counter — high nibble increments each frame (0xB1->0xC1->0xD1->...) |

**Interpretation:** 0x052 broadcasts the engine/generator RPM reference (identical to 0x051 B3-B4) to an unknown PT bus recipient. B0-B1 constant at 32768 neutral with no active signal. The addressee is unresolved. The "traction inverter" label was speculative and is now doubly invalidated: (1) engine RPM reference is relevant to the generator inverter (mechanically coupled to the engine) but has no obvious use for the traction inverter (fixed-ratio drivetrain, no engine coupling); (2) EPRI data confirms the traction inverter (TRAC MCU) is on the OBD bus, not the PT bus, and cannot directly receive this message. Most plausible remaining hypothesis is a supplementary RPM reference for the generator inverter or another PT bus module. Addressee unconfirmed.

**Previous misidentification (corrected 2026-03-03):** B2-B3 was cataloged as "Traction motor DRIVE torque command (positive/motoring only)" because it is identical to 0x051 B3-B4, which was itself misidentified. Both were corrected simultaneously. See `notes/cruise-control-analysis.md` Phase 6.

**Scripts:** `artifacts/find_drive_torque_feedback.py`, `artifacts/find_drive_cmd_vs_5a2.py`

---

### 0x053 — Generator/System Mode Status

| Field | Value |
|-------|-------|
| Rate | Very low — typically 6–7 transitions per session |
| DLC | 2 |
| Confidence | **MEDIUM** — bit assignments from single highway drive log (debuglog_M0.log, Aug 2025); patterns consistent across all observed transitions |

**Observed state transitions (from `notes/deprecated/highway-drive-cycle.md`):**

| Value (LE) | B0 | B1 | State |
|------------|----|----|-------|
| 0x0001 | 0x01 | 0x00 | Boot/init (first frame only) |
| 0x2204 | 0x04 | 0x22 | EV mode / system ready |
| 0x2234 | 0x34 | 0x22 | Engine armed (B0 bits 4+5 set, ~1.1s before generator starts) |
| 0x0034 | 0x34 | 0x00 | Generator running (B1 EV flags cleared) |
| 0x0004 | 0x04 | 0x00 | Generator stopping (B0 arm bits clear) |
| 0x0006 | 0x06 | 0x00 | Session ending / shutdown |

**Bit assignments (hypothesis):**

| Bit | Mask | Meaning |
|-----|------|---------|
| B0[0] | 0x01 | Boot/init (only at log start) |
| B0[1] | 0x02 | Session ending |
| B0[2] | 0x04 | Normal operating mode |
| B0[4] | 0x10 | Engine arm / running |
| B0[5] | 0x20 | Engine arm / running |
| B1[1] | 0x02 | EV mode (set when generator NOT running) |
| B1[5] | 0x20 | EV mode (set when generator NOT running) |

**Key pattern:** B1=0x22 is the EV/idle state; B1=0x00 means the generator is running. The EV flags are *cleared* when the engine is engaged, not set. B0 arm bits (4+5) set ~1.1s before B1 EV flags clear at startup; symmetric at shutdown (B0 arm bits clear before B1 EV flags restore).

---

### 0x471 — Generator Torque Feedback

| Field | Value |
|-------|-------|
| Bytes | B0-B1, little-endian |
| Encoding | Unsigned centered at 32768: `torque = ((b1 << 8) \| b0) - 32768` |
| Neutral | 32768 (0x8000) |
| Sign | Same convention as 0x051: <32768=generating, >32768=backdriving |
| Rate | ~100 Hz |
| Confidence | **HIGH** — r=0.9984 vs 0x051 torque command (gen-loaded filter); not an identical copy |

**Evidence:** `find_torque_feedback.py` on `vtruxevapdrivelog4part2.log` with gen-loaded filter (|cmd|>200):
- r(0x471 B0-B1, 0x051 B1-B2) = 0.9993 across all frames
- r(0x471 B0-B1, torque cmd) = **0.9984** when filtered to gen-loaded frames
- Mean absolute difference vs command: **6.9 counts** (~0.2% of full scale)
- Max absolute difference: **1374 counts** (transient control loop error)
- Range wider than command: 0x471 −2333 to +1913 vs 0x051 −2293 to +1600

**Interpretation:** 0x471 is the generator **inverter's torque feedback** — the value the inverter reports
it is actually producing, as opposed to 0x051 which is the VCM's command. The small mean residual (6.9
counts) and occasional large deviations (up to 1374 counts) are exactly what a real-time torque
feedback signal with a control loop would show. A pure command echo would have mean diff ≈ 0 and max
diff near 0; an independent measurement has genuine transient errors.

**Other bytes of 0x471:**

| Byte | Observation | Notes |
|------|-------------|-------|
| B0 | 0–255, 256 unique | LSB of torque feedback |
| B1 | 118–135, 17 unique | MSB of torque feedback (centered at 128 = 32768 high byte) |
| B2 | 0–252, 73 unique | Unknown; symmetric with B4 — possibly a second feedback parameter |
| B3 | 2–11, 4 unique | Coarse version of B2's parameter |
| B4 | 5–251, 71 unique | Mirror of B2 (bit-toggle pattern identical) |
| B5 | 2–11, 4 unique | Mirror of B3 |
| B6 | 0–240, step 16; 16 unique | Nibble rolling counter |

The B2-B3 / B4-B5 symmetric pairs (nearly identical toggle patterns) suggest a second measurement
reported twice — possibly generator phase current or DC link current in two redundant encodings.

**Nm scale (from EPRI DBC, confirmed from DAT constant):** `raw * 0.125 - 4096 Nm` — i.e. the
raw-count offset above maps to Nm by multiplying by 0.125. Zero torque = raw 32768. The +-4096 Nm
theoretical range far exceeds the HVH250-115D motor limit; the wire range actually used is much
narrower.

**Peak observed values (vtruxanotherevaplogpart1-3, sustained uphill generation):**
- Peak generating torque (feedback): **-367 Nm** @ ~2000 RPM
- Torque at peak power: **-348 Nm** @ **~4000 RPM** -> 139.5 kW (0x598 B2-B3 confirmed)
- Shaft power cross-check: T * omega = 348 Nm * 418 rad/s = 145.6 kW; 0x598 reads 139.5 kW (ratio 0.96 -- consistent with ~4% inverter/motor losses and minor inter-frame timing offset)
- The -367 Nm peak is ~92-98% of the HVH250-115D torque envelope at that RPM/voltage per the product data sheet.

**Scripts:** `artifacts/find_torque_feedback.py`

---

### 0x411 — High-Resolution State of Charge (B0:B1)

| Field | Value |
|-------|-------|
| Bytes | B0, B1 |
| Encoding | `SoC (%) = (B0 * 64 + (B1 >> 2)) / 100` |
| Resolution | 0.01% per count |
| Full-charge value | ~10000 counts (100.00%) |
| Rate | 16 Hz |
| Confidence | **CONFIRMED** — r > 0.998 across 5 logs spanning discharge, charge, and regen |

**Encoding verified genuine (2026-03-29):** B1 lower 2 bits are always 0 (100% of frames in debuglog_M3_T11 and evap drive logs) — the encoding is a clean 14-bit integer with no sub-resolution noise. All 64 fine steps (B1>>2 = 0-63) occur sequentially within each B0 value. Both constant-B0 windows are perfectly monotone (zero reversals). The 0.01% resolution is real, not padding. Within a 1% real SoC change window, 0x411 produced ~100 unique values; bcm_soc (0x410 B3, 0.5% resolution) produced 3.

**Step pattern:** B1 increments/decrements by 4 per frame (~0.91s per step); B0 carries at
each B1 wrap (~58s per B0 step). Direction: counts UP during charging, DOWN during discharge,
tracks regen bidirectionally in real time.

**Relationship to 0x596 B6:** 0x596 B6 is the integer-rounded (whole-percent) version of the
same SoC value. 0x411 is the BMS's full-precision register. 0x411 is also valid before
0x596 begins broadcasting at session startup.

**Evidence:** Correlated against 0x596 B6 across vtruxexporttest (r=0.9998, scale=100.1),
vtruxcurrentlimitingtest with regen (r=0.9988), vtruxevapdrivelog4 p1 (r=0.9981),
vtruxchargeafterexportchargetest-80pctcv (r=0.9984), rainychargedebug (r=0.9990).
Linear fit across all sessions: combined = 99.7 * SoC% + ~65. See
`notes/after-battery-swap-charge-fail-analysis.md` (0x411 section) and
`notes/artifacts/correlate_0x411_soc.py`.

**Other bytes:** Remaining bytes in 0x411 include a contactor request signal (changes at
startup, not at shutdown). Not yet decoded.

---

### 0x596 — State of Charge (SoC %)

| Field | Value |
|-------|-------|
| Byte | B6, single byte |
| Scale | 0–100% direct |
| Confidence | **CONFIRMED** — consistent 75–80% across multiple drive logs |

**Notes:** Message also contains BMS state machine and charge/discharge enable bits. Digital-heavy (bits flip, not analog ramps). Integer-rounded version of 0x411 B0:B1 (see above).

---

### 0x600 — VCM Status: Generator Active Flag + Evap Cycle Stage

| Field | Value |
|-------|-------|
| Rate | 20 Hz |
| Confidence | **CONFIRMED** — B0 bit 4 from bitfields-investigation; B3 from evap-cycle-analysis |

**Byte map:**

| Byte | Role | Notes |
|------|------|-------|
| B0 | VCM mode flags | Bit 4 = generator active (0x34=active, 0x24=inactive). B0=0x10 seen at EV key-off state. |
| B1 | Constant 0x00 | |
| B2 | Evap sub-stage counter | Varies continuously within each B3 stage. Together B2-B3 (LE uint16) tracks finer evap progress. |
| B3 | **Evap cycle stage** | See state table below. |
| B4-B5 | Normally 0x00 | Transiently non-zero during B3 state transitions. |
| B6 | Constant 0x0F | |
| B7 | Constant 0x00 | |

**B3 state table:**

| B3 | State | Observed context |
|----|-------|-----------------|
| 12 (0x0C) | Normal operating state — no evap in progress | Constant in driveway, gen on/off, and climit logs (all non-evap); also at evap log start |
| 6 | Evap in progress — early | ~110s after generator start |
| 4–5 | Evap in progress — mid/late | Long plateau during purge |
| 3 | Evap in progress — near end | Terminal descent |
| 11 (0x0B) | Post-evap state — evap cycle complete | B3 rises 3–4→11 in ~1.4s; B0 bit 4 clears ~3s later; engine stops ~5s later. Persists until next key cycle. |
| 0–10 (transient) | VCM boot sequence | B3 rises from 0 to 12 at key-on |

**Note (2026-02-28):** Earlier versions of this table had 11 and 12 swapped — labelling 11 as "idle"
and 12 as "evap pending." This was incorrect. B3=12 is the universal normal state (confirmed across
8 logs); B3=11 is the post-evap completion state. The "Follow-up needed" item is resolved. See
`notes/evap-cycle-analysis.md` for full timeline and correction details.

**Evap cycle full timeline:** Documented in `notes/evap-cycle-analysis.md`.

---

### 0x598 — Power Bundle (HCU/VCU power averages)

All 16-bit words are little-endian, unsigned, centered at 32768.

| Bytes | Signal | Confidence | Notes |
|-------|--------|------------|-------|
| B0-B1 | Battery power | HIGH | Active during AC charging; near-zero when generator fully covers traction load |
| B2-B3 | Generator power | HIGH | Near-zero in pure EV (stddev=33 cts); mean +3083 cts when generator active; r=−0.98 vs gen torque (0x051) |
| B4-B5 | Drivetrain power | HIGH | Large in both EV and hybrid; balance: B4-B5 = B0-B1 + B2-B3 (drivetrain = battery + generator) |
| B6-B7 | Unknown | LOW | Static bias; not part of balance |

**Balance: `drivetrain = battery + generator`** (i.e., B4-B5 = B0-B1 + B2-B3). Verified across pure-EV and hybrid segments: residual stddev/mean = 5.9% (EV) and 6.9% (hybrid). Sign convention: positive = providing energy to HV bus (battery discharging, generator generating, drivetrain consuming).

**Power vs current — RESOLVED (POWER):** Corrected 2026-03-29. Earlier "RESOLVED (CURRENT)" conclusion (2026-02-xx, A2b charging-phase analysis, r vs I = −0.74 > r vs P = −0.53) was based on low-variance charging data where V and I are collinear; those weak correlations do not distinguish the hypotheses.

Evidence for power: cross-correlation of B2-B3 (generator channel) with GENE_HighPwr_Curr (A) vs GENE_HighPwr_Curr × GENE_HighPwr_Volt (W) across `vtruxevapdrivelog4part2.log` (68 gen-on frames, 342–393 V, −192.5 to +41.8 A generator current): both r values are 0.9994–0.9995 (indistinguishable), but the power scale is **locked at −0.010 kW/count across all segments** (gen-on, gen-off, all-frames: −0.01007, −0.01004, −0.00998 kW/count). If the signal were current, the effective kW/count ratio would drift with bus voltage; it does not. Scale matches EPRI decompile (B0-B1 and B4-B5 both explicitly 0.01 kW/count) exactly. See `artifacts/epri_verify_open_items.py` Phase 1.

**Channel roles confirmed via `signal_scaling.py`** (`vtruxcurrentlimitingtest.log` + `vtruxevapdrivelog4.log`). Note: A1 analysis (charging log only) had B2-B3 and B4-B5 roles **swapped** — both are flat during AC charging so A1 could not distinguish them; the driving-log segmentation resolved this.

**Scale — CONFIRMED 0.01 kW/count:**

| Source | Scale | Notes |
|--------|-------|-------|
| Phase 1 gen-on cross-corr (evap4part2) | **0.01007 kW/count** | B2-B3 vs GENE power; locked across segments |
| EPRI decompile (B0-B1, B4-B5) | 0.01 kW/count | Adjacent channels; DAT_00029590 = 0.01 |
| Generator flatline evap purge (4400 cts, ~47.5 kW ref) | 0.0108 kW/count | `check_evap_scale.py`, evap4 windows; ~11% high |
| Export panel reading (~1025 W, 84.4 cts) | 0.01214 kW/count | `exportpowerattempt.log`; ~22% high vs panel reading |
| Analog gauge anchor (0.04 A/count @ ~380 V) | ~0.015 kW/count | `signal_scaling.py`; gauge appears ~50% inflated vs confirmed sources |

Digital references (generator flatline, export panel) are consistent with 0.01 kW/count within plausible measurement uncertainty. Analog dashboard gauges read ~50% higher than confirmed sources and are not reliable calibration anchors.

**Physical formula:**
```
power_kW = (raw_u16 - 32768) * 0.01
```

Sign convention: positive = providing energy to HV bus. Generator-active readings are positive (~44 kW evap purge, ~74 kW uphill). Regen and battery charging are negative.

**Scripts:** `artifacts/signal_scaling.py` (original calibration), `artifacts/check_evap_scale.py` (per-file segment analysis), `artifacts/check_energy_integral.py` (energy balance), `artifacts/plot_power.py` (3-channel + RPM plots), `artifacts/epri_verify_open_items.py` Phase 1 (power vs current resolution).

---

### 0x597 — Multi-field message (current + drive torque tracking + regen power proxy)

**Rate:** ~20 Hz. Multiple distinct signals in different byte positions.

| Bytes | Signal | Confidence | Notes |
|-------|--------|------------|-------|
| B1-B2 (LE) | Current (role ambiguous) | MEDIUM | Confirmed current (A2b: r vs I_charger=−0.74 > r vs P_charger=−0.53). In EV mode r=0.79 vs drivetrain current (0x598 B4-B5); in hybrid r=0.77 vs battery current (0x598 B0-B1). Ambiguous between battery and drivetrain. |
| B3-B4 (LE-32768) | Tracks 0x052 motoring demand (role TBD) | MEDIUM | r=+0.9571 vs 0x052 B2-B3 (**engine/generator RPM reference** — the "drive cmd" label was superseded 2026-03-03) in evap log; rest value ≈ −1. Stays near −1 during regen (r=−0.05 vs actual bidirectional torque). Tracks the motoring-side demand but ignores regen; exact role pending re-analysis given the 0x052 correction. |
| B5-B6 (LE-32768) | Regen power/current proxy | LOW-MEDIUM | r=+0.83 vs actual motor torque (0x5A2 B4-B5) in bidirectional scan. Regen-only scan (10375 frames, actual torque < −100): |r|=0.60 vs regen magnitude — highest non-self PT bus correlator in that scan. Goes MORE POSITIVE during regen (reaches +455 when actual torque = −2358) while staying negative during drive. Lower r in regen-only mode expected: bidirectional correlation is driven by the large contrast between heavy motoring (signal ~−9526) and regen (~+455); within regen-only frames the variance is smaller. Not a torque command — a power/current consequence. Range: −9526 to +16064. |

**Notes on B1-B2:** Not a simple copy of any 0x598 slot (max r=+0.84). Does not correlate with generator torque (r≈0). During AC charging, mean=10.5 ≈ 0x598 B0-B1 (mean=10.6), suggesting battery-current tracking in that context. Prior note: "r=−0.888 vs DCDC HV voltage" — consistent with battery or drivetrain current. Scale calibration pending.

---

### 0x592 — Pedal / Driver Inputs

| Bytes | Signal | Confidence | Notes |
|-------|--------|------------|-------|
| B0 | Switch flags (EVSESwitchState, ExportPowerState, IgnitionKeyState) | HIGH | EPRI decompile confirmed. 3 bit fields. |
| B1 | Unknown | LOW | |
| B2-B3 (LE) | Throttle position | HIGH | User-confirmed; physical pedal position. Reads 0 when foot is off pedal. VCU cruise control does not act through this signal (confirmed: reads 0 throughout cruise window while traction cmd is positive). |
| B4-B5 (LE) | Brake pedal | HIGH | User-confirmed; correlates with regen events |
| B6-B7 (LE) | Unknown | LOW | |

---

### 0x18FFD6B3, 0x18EFB3FE, 0x18FFD4B3, 0x18FF0320 — Bel DCDC Converter (Extended IDs)

Source address 0xB3. Same LE signed ×0.05 encoding as Bel Charger (0xC0). All signals active during both charging and driving.

#### `0x18FFD6B3` — Analog Measurements (confirmed)

| Bytes | Signal | Scale | Observed Range | Confidence |
|-------|--------|-------|----------------|------------|
| B0-B1 (LE signed) | **LV bus voltage** | ×0.05 V | 12.15–14.35V | **CONFIRMED** |
| B2-B3 (LE signed) | 12V output current | ×0.05 A | 0–200A (drive); 5–7A (charge float) | PARTIAL |
| B4-B5 (LE signed) | **HV bus input voltage** | ×0.05 V | 2.4–417.6V | **CONFIRMED** |
| B6-B7 (LE signed) | **Internal temperature** | ×0.1 degC (signed) | 15.8–22.7°C | **CONFIRMED** |

**HV input voltage confirmation:** r=0.993 vs charger GT (`full charge then fail.log`, 380–422V arc). Reads ~7V lower than charger — calibration offset, not resistive drop. MAE=0.94V after linear correction. See `context-voltage-current.md` for full details. Also in `vtrux-powertrain.dbc` as `BELDCDC_hvInputVoltage`.

#### `0x18EFB3FE` — Limits / Configuration (constant)

| Bytes | Signal | Scale | Value |
|-------|--------|-------|-------|
| B0-B1 (LE signed) | HV max voltage limit | ×0.05 V | 384.00V |
| B4-B5 (LE signed) | 12V output minimum | ×0.05 V | 13.95V |

All values constant throughout logs — configuration, not live measurements.

#### `0x18FF0320` — 12V Bus Voltage (separate message)

| Bytes | Signal | Scale | Confidence |
|-------|--------|-------|------------|
| B2-B3 (LE) | 12V bus voltage | ~0.001 V/count | MEDIUM-HIGH |

Starts 12–13V, rises to ~14.2–14.8V after startup.

#### `0x18FFD4B3` — DCDC Status

Nearly all zeros in charge log; B6-B7 LE ×0.05 = 11.35V observed once. Needs generator/drive log analysis.

---

## High Confidence — Not Yet Fully Confirmed

### 0x5A2 — Remy-Motor RPM

| Field | Value |
|-------|-------|
| Bytes | B2-B3, little-endian |
| Encoding | Unsigned centered at 32768: `rpm = ((b3 << 8) \| b2) - 32768` |
| Scale | ~1 RPM/count |
| Sign | Positive = Drive direction, Negative = Reverse |
| Rate | ~20 Hz |
| Confidence | **HIGH — not yet fully confirmed** |

**Evidence — driveway (movingaroundindriveway.log):** Pearson r=0.9976 vs proxy motor RPM (built from 0x3E9 vehicle speed × 64.3 RPM/km/h drivetrain ratio). Zeroes cleanly in Park. Tracks Drive and Reverse excursions with ~1:1 magnitude match across 0–1000 RPM:

| Moment | Proxy RPM | Signal | Delta |
|--------|-----------|--------|-------|
| Park (idle) | 0.0 | -1 | ~0 |
| Drive #1 peak (~15.5 km/h) | 760 | 747 | -13 |
| Reverse #1 peak (~4.6 km/h) | -293 | -290 | +3 |
| Drive #2 mid (~13.3 km/h) | 853 | 826 | -27 |
| Reverse #3 peak (~1.7 km/h) | -109 | -118 | -9 |

**Evidence — highway (debuglog_M0_T2_short.log):** Signal reads 4,301–5,946 RPM across the 48-second log, implying 67–93 km/h (42–57 mph). The truck is visibly decelerating from ~57 mph — consistent with coasting on a highway off-ramp. Calibration at the top of the window: signal reads **5,837 RPM → implied 90.8 km/h**, giving an independent ratio of **5837 / 90.8 = 64.3 RPM/km/h**, identical to the driveway-derived value. Signal is internally consistent from ~0 RPM (parking lot) through ~6,000 RPM (highway).

**debuglog_M0_T0_half.log:** Motor reads ≤76 RPM throughout — confirms stationary startup sequence, signal correctly idles at zero.

**debuglog_M0_T7.log:** Low-speed end-of-drive, decelerates 13 km/h → stop, briefly negative (Reverse). Consistent with expected behavior.

**What's needed to fully confirm:** A tachometer reference or OBD RPM cross-check at a known steady speed. The scaling is self-consistent but has not been compared against an independent ground truth. Also note: at 64.3 RPM/km/h, the 8000 RPM motor limit implies a top speed of ~124 km/h (77 mph) rather than the 82 mph in the drivetrain spec — suggesting this truck may have a 3.73 rear axle rather than the 3.42 shown in the spreadsheet.

**B4-B5 (LE)-32768** in the same message is traction motor torque FEEDBACK. Confirmed in `debuglog_M0_T7.log` (behavioral) and `vtruxcurrentlimitingtest.log` (T=P/ω correlation, 2026-02-28):

| Moment | RPM (B2-3) | Torque (B4-5) | Notes |
|--------|-----------|----------------|-------|
| Decelerating from highway (no pedal) | +850 | -88 | Regen braking |
| Throttle burst near stop | +186 | +562 | Forward motoring |
| Reverse creep (no pedal) | -158 | -128 | Auto reverse torque |
| Reverse at speed (no pedal) | -140 | -158 to -1058 | Auto reverse + braking |

Sign convention: Positive = motoring (outputting torque in direction of travel), Negative = regenerating or reverse-motoring.

**P/ω confirmation (2026-02-28):** Using T_ref = I_drive × V_HV / ω (0x598 B4-B5 current, 0x5A2 B2-B3 RPM)
on `vtruxcurrentlimitingtest.log` with |RPM|>200 filter:
- r(B4-B5, T_ref) = +0.708 — positive, consistent with torque
- r(B4-B5, RPM)   = −0.087 — **near-zero**: definitively rules out RPM interpretation

The r vs RPM ≈ 0 is the decisive test. An RPM echo would have r→1.0 vs RPM; a torque signal at
constant power (T = P/RPM) would have r→−1.0 vs RPM. Near-zero means neither — it's tracking a
different physical quantity (torque feedback from the motor controller). The r=0.71 vs T (not 1.0)
reflects noise in T_ref from the low-RPM hyperbolic region; the qualitative result is solid.

**Runners-up from RPM correlation search:**
- `0x308 B1-2 (LE)`: r=0.9970 (**spurious — short window pre-wrap**). B1-B2 LE is a 16-bit encoder position counter (zero=32128=0x7D80); full-log r≈0. See `notes/borgwarner.md`.
- `0x6000001 B6-7 (BE)-32768`: r=0.9981 absolute magnitude, extended J1939 frame, pinned at minimum during driveway. May be relevant at highway speeds.
- `0x594 B0-1 (BE)-32768`: r=0.9958 absolute magnitude only (doesn't go negative in Reverse).

**Per-byte motor speed echoes (Phase 8, 2026-03-08):** The following single bytes track motor speed closely
over the full log and are near-constant during the zero-throttle cruise window. No DBC entry needed.

| Signal | Observation |
|--------|-------------|
| `0x594 B0` (uint8) | Strong visual match to motor speed trace across full log. Possibly encodes vehicle speed in km/h (range at highway speeds consistent with ~90 km/h). Does not go negative in Reverse (absolute magnitude only). |
| `0x308 B2` (uint8) | High byte of the B1-B2 LE16 encoder counter. Appeared to track motor speed because B1 wraps rapidly at speed; B2 carries the overflow. See `notes/borgwarner.md` Phase 1. |

**Scripts:** `artifacts/find_motor_rpm.py`, `artifacts/verify_motor_rpm_candidates.py`

---

### 0x6000001 — Unknown Extended Frame (Motor-Related)

| Field | Value |
|-------|-------|
| CAN ID type | Extended (29-bit) |
| Rate | ~20 Hz |
| Confidence | **LOW-MEDIUM — role ambiguous** |

**Observed signal map:**

| Byte | Observation | Notes |
|------|-------------|-------|
| B0 | Odd values only (bit 0 always 1). Range 1–109. Tracks throttle pedal (r=0.9998). | Command or status echo — see below |
| B1 | 6 unique values, range 116–136. Slowly varying. | Possibly temperature or mode |
| B2 | Always 0x39 | Constant — likely message type byte |
| B3 | 4 unique values: 1=Park, 5=Reverse, 9=Neutral, 13=Drive | Gear state values |
| B4 | 0=parked/off, 128=in motion | Motion flag |
| B5 | Always 0 | |
| B6 | 8 unique values (0–7) | Rolling counter or mode |
| B7 | Rolling counter (even values 0–254) | |

**Observed behavior:** B0 rises proportionally with throttle pedal during Drive phases, returns to 1 at idle/release. During Reverse with no pedal, B0 stays at 1 while motor still applies creep/braking torque (per 0x5A2 B4-5). B3 tracks gear position exactly.

**Why the command interpretation is doubtful:** The generator torque command 0x051 is confirmed (by direct experiment: editing it causes generator backdriving). No equivalent experiment has been done for 0x6000001. Additionally, 0x052 B2-B3 is now confirmed as a real traction drive torque command (positive/motoring only, identical to 0x051 B3-B4) — but it stays near −1 during confirmed regen events. An exhaustive correlation scan of all PT bus bytes/words against 0x5A2 B4-B5 (actual bidirectional motor torque) found no signal with |r| > 0.83, confirming there is no explicit negative-torque (regen) command on the PT bus.

**Current best theory — traction inverter handles regen autonomously:** **⚠ Premise superseded (2026-03-03):** 0x051 B3-B4 / 0x052 B2-B3 are the **engine/generator RPM reference**, NOT a traction motoring torque command (the TRAC MCU is on the OBD bus, not the PT bus; the actual traction command is 0x041 on the OBD bus). The reasoning below predates that correction and treats them as traction commands — it needs re-analysis and is retained only for history. Under the (superseded) model:
- 0x051 B1-B2: VCM → generator inverter torque command (confirmed, bidirectional)
- 0x051 B3-B4 / 0x052 B2-B3: ~~VCM → traction inverter MOTORING torque command~~ **superseded — engine/generator RPM reference (see correction above)**
- 0x052 B0-B1: constant 0x8000 neutral throughout all logs
- 0x6000001 B0: Motor controller publishing its current throttle reading or output torque reference (status/echo, not the command input)
- 0x6000001 B3: Gear state broadcast, consumed by motor controller to determine direction

**What would distinguish command from status:** Edit B0 of 0x6000001 while the motor is running and observe whether motor torque (0x5A2 B4-5) changes. If it does, 0x6000001 is the command. If it does not, the motor is acting autonomously on 0x592 and 0x6000001 is a status echo.

**Scripts:** `artifacts/find_motor_torque.py`, `artifacts/verify_torque_cmd.py`

---

## Partially Confirmed / Hypothesized

### 0x639 — Unknown

**Notes:** Originally cataloged as battery current at B5-B6 BE, but that was wrong — B5=0x49 constant across all frames; the r=0.99 vs 0x592 B0-B1 was a spurious artifact of two near-constant signals. Active bytes are B2-B3 (93 unique values in highway logs) but no confirmed interpretation. Role and encoding unverified.

---

### 0x63C — Generator RPM (SECONDARY — overflows above ~4000 RPM)

**Use `0x054 B0-B1` instead for all RPM analysis.** This signal wraps above ~4000 RPM with no carry bit; use 0x63C only when you are certain RPM stays below that threshold and the 50 Hz rate is acceptable.

| Field | Value |
|-------|-------|
| Bytes | B6 (single byte) |
| Encoding | uint8, unsigned |
| Scale | 16 RPM/count |
| Offset | -96 (RPM = 16 × B6 − 96) |
| Zero RPM | B6 = 6 |
| Range valid | B6 = 5–255 → ~0–3984 RPM (wraps above here) |
| Max observed (normal ops) | B6 = 141 → ~2160 RPM (evap purge limited) |
| Rate | 50 Hz |
| Confidence | **CONFIRMED** (valid range only) — r=0.9975 vs OBD PID 0x0C ground truth |
| **OVERFLOW WARNING** | B6 wraps 255→0 above ~4000 RPM; no carry bit. Values ≥4000 RPM are invalid. |

**Overflow confirmed (2026-03-19):** Generator overheat test drove engine to ~4686 RPM (confirmed by OBD 0x0C9 and 0x054 B0-B1). At that RPM, B6 wraps and the signal shows values descending from 0 rather than continuing to climb. Full-log Pearson r vs OBD RPM collapses to +0.89 (vs +0.9975 in normal range) and high-RPM-only r turns negative (−0.77), confirming wrap.

**Notes:** Confirmed via OBD Bluetooth scanner (PID 0x0C) correlation during `vtruxevapdrivelog4`. Brute-force per-byte correlation identified B6 as the signal (r=0.9975 across 0–2174 RPM). Empirical fit: RPM = 15.9998 × B6 − 92.89. Clean form: RPM = 16 × B6 − 96 (zero at B6=6).

**B0-B1:** Not RPM. Varies even when generator is off — possible motor electrical angle or cumulative shaft position.

**B7:** Nibble-aligned (0x00–0xF0 in steps of 0x10), 16 unique values, likely sub-counter.

**B6-B7 counter:** In prior genlog, B6-B7 (LE) slowly incremented (~1 unit per 2s) — possible cumulative revolution count. Do not confuse with B6 RPM byte.

---

### 0x63F B2 — Generator-Correlated Coarse Signal (role uncertain)

| Field | Value |
|-------|-------|
| Byte | B2 (single byte) |
| Encoding | Inverted: value decreases as generator output increases |
| At generator off | B2 = 14 (constant; clean zero — unlike B0-B1 of 0x63C which moves with motor) |
| At generator idle (~1250 RPM) | B2 = 7 |
| At max observed output | B2 = 2 |
| Distinct values | 13 (range 2–14) — ~181 RPM/step if interpreted as RPM |
| Rate | 50 Hz (same cluster as 0x63C) |
| Correlation | r = −0.9985 vs OBD PID 0x0C RPM |
| Confidence | MEDIUM — correlated with generator activity, role ambiguous |

**B0-B1:** Constant 0x7FFD (≈32768 neutral). **B3:** Variable (0–246), needs investigation. **B5-B7:** Always 0x00.

**Role ambiguity:** Generator operates in torque mode, so RPM is a consequence of the efficiency curve (higher power → higher RPM). With only 13 bands, a coarse "RPM tier" maps almost 1:1 to a power tier. Signal is **strongly correlated with generator activity** but it is unclear whether it is a coarse RPM feedback, a power-level feedback, or some other generator status tier. The inverted encoding (lower B2 = higher output) is consistent with a period or countdown representation (shorter period = faster engine).

---

### 0x054 B0-B1 — Generator/Engine RPM (PRIMARY, overflow-immune, CONFIRMED 2026-03-19)

| Field | Value |
|-------|-------|
| Bytes | B0 (LSB) + B1 (MSB) — LE uint16 |
| Encoding | `RPM = (B1<<8 \| B0) - 32768` (offset binary, centered at 32768) |
| At engine off | le16 = 0x7FFF → RPM = −1 (null=-1, same convention as 0x051 B3-B4) |
| At engine idle (~1250 RPM) | B1 ≈ 0x84–0x85 |
| Max observed (overheat test) | ~4686 RPM — no overflow |
| Rate | 100 Hz (same cluster as 0x051) |
| Correlation | r = +0.9999 full-log, r = +1.0000 at >3500 RPM vs OBD 0x0C9 |
| Fit | a = 0.9996 RPM/count, b = 2.25 RPM; RMSE = 8.9 RPM (n=222979) |
| Confidence | **CONFIRMED** — calibrated and verified in two logs (2026-03-19) |

**Use this signal** for all RPM analysis. It runs at 100 Hz and does not overflow at any engine speed observed in testing (up to 4686 RPM). The secondary signal (0x63C B6) wraps above ~4000 RPM.

**Previous analysis (corrected 2026-03-19):** B1 alone was characterized as a "coarse RPM reference" with only 10 discrete tiers (~242 RPM/step, r=0.9972). B0 was dismissed as "high-entropy noise." RPM correlation scan on the generator overheat test log revealed B0 is the LSB of a full 16-bit RPM word; the combined LE uint16 gives ~1 RPM/count resolution with r=0.9999.

**B2-B3:** High entropy, role unknown. **B4:** Nibble counter (steps of 0x10, 16 unique values).

**Artifacts:** `rpm_054_calibration.txt`, `rpm_054_verification.png`.

---

### 0x395 — Generator Phase Current RMS + Torque Tier

| Field | Value |
|-------|-------|
| Rate | 77 Hz |
| Confidence | **HIGH** — r=0.9720 vs torque command (gen-loaded filter) |

**Byte map (all bytes observed in `vtruxevapdrivelog4part2.log`):**

| Byte | Value | Notes |
|------|-------|-------|
| B0 | Constant 0x0D | Header |
| B1–B3 | Constant 0x00 | Header padding |
| B4 | Range 21–102; B4=B5 always | Coarse torque tier. r=+0.8076 vs torque command (positive sign: increases as generation decreases). 22 unique values. |
| B5 | Always equal to B4 | Redundant copy of coarse tier |
| B6 | Range 0–116; B6≈B7 (differ ≤1) | Fine signal; r=−0.9553 vs torque cmd (gen-loaded). 99 unique values. |
| B7 | Range 0–118; ≈B6 | Fine signal; r=−0.9720 vs torque cmd (gen-loaded). 102 unique values. **Best candidate.** |

**Sign convention:** B7=0 at generator neutral; increases as generation torque magnitude increases.
Negative r vs torque command (0x051) because 0x051 goes negative when generating, while B7 goes positive.

**Interpretation:** The unsigned magnitude, fine resolution (102 steps, 0–118 range), and zero-at-neutral
behaviour are consistent with **phase current RMS feedback** from the generator inverter. For a PMSM,
phase current RMS is proportional to torque magnitude regardless of direction. The coarse B4/B5 tier
(22 steps) is likely the same quantity rounded or quantised to fewer levels.

**Previous note:** Earlier analysis described B5-B6 (LE) as "Generator Speed alternate candidate, 0–23k
raw, goes to zero in EV mode." The 0–23k raw reading was B5-B6 LE = dat[5]|(dat[6]<<8) ≈ B5×256+B6,
which mixes the coarse tier byte (B5) with the fine byte (B6). The correlation with torque command
(not RPM) now suggests this is current/power magnitude, not speed.

**Scripts:** `artifacts/find_torque_feedback.py`

---

## A123 BMS Message Cluster

IDs in this area are split by source based on T2 (HV battery LV connector pull) and T3 (VCM B-connector) disconnect tests in `can-disconnect.md`.

### BMS-Direct IDs (drop immediately at T2)

These stop transmitting within ~0.2s of the HV battery LV connector being pulled. BMS board is the broadcaster. Also absent from the parts truck (no battery).

| CAN ID | Rate | Role | Notes |
|--------|------|------|-------|
| 0x370–0x375 | ~8 Hz | BMS section temperatures | Multi-byte temperature cluster; see Battery Temperature section below |
| 0x430 | 16 Hz | V_max, V_min cell voltage + T_max, T_min cell temp | B0-B1 = V_max (12-bit masked, 1 mV/cnt); B2-B3 = V_min; B4 = T_max; B5 = T_min; see below |
| 0x506 | 8 Hz | Battery temperature (3 sensors) | B1/B2/B3; raw-40=degC; persists ~3s longer than others at key-off |
| 0x507 | 8.8 Hz | Battery temperature (2 sensors) | B0/B1; raw-40=degC, sentinel 0x7F; see below |

### B-Connector-Dependent / BMS-Correlated IDs (survive T2, drop at T3)

These survive the HV battery LV connector pull (T2 = P) and only drop when the VCM B-connector is removed (T3 = A). The BMS is confirmed not the broadcaster. However, T3 cannot distinguish two possibilities: (1) the VCM itself broadcasts these and loses its enable from the B-connector, or (2) the B-connector carries the wake/power signal for whichever module actually broadcasts them. See T3 "PT Bus Collapse" notes in `can-disconnect.md`.

| CAN ID | Rate | Role | Notes |
|--------|------|------|-------|
| 0x596 | — | BMS state / SoC / permissions | Contains SoC (B6), charge/discharge enable bits |
| 0x639 | — | Unknown | B5-B6 was misidentified as battery current (constant field). B2-B3 active but uninterpreted. Populates with 0x63A during fault events. |
| 0x63A | — | Bytes 6-7: Generator initialization state (see `status-bits-cross-log-comparison.md`); other bytes uncharacterized | "Cell extremes" label from early analysis — removed; byte-level content unclear except bytes 6-7. |
| 0x63D | — | Fault flags / protection | OV/UV/OT bits, charge/discharge inhibit; changes before charger faults |
| 0x640 | — | Pack status / temperature | B1 is NOT SoC; likely pack average temp or status summary |

**Observed fault sequence (from failed charge log):**
1. `t≈54125s`: 0x63A and 0x639 both populate simultaneously — BMS protection assertion
2. 0x596 state changes — charge/discharge permission revoked
3. Charger (Bel inverter) faults secondarily

Root cause hypothesis: NOT cell overvoltage. Suspected isolation fault, contactor disagreement, or HVIL interruption.

### Battery Temperature Signals

All confirmed via: (1) BMS-dependent disappearance test, (2) I^2*t correlation in
`vtruxcurrentlimitingtest.log`, (3) b3-correlates scan across all slowly-varying bytes,
(4) seasonal survey across charge logs Jan 2025 -- Feb 2026
(`artifacts/seasonal_batt_temp.py`, output `artifacts/seasonal_batt_temp.txt`).

Per-cell temperature min/max is broadcast in 0x430 B4/B5 — see below.

#### 0x373 B3 -- Battery System Temperature

| Attribute | Value |
|-----------|-------|
| Encoding | unsigned byte, raw - 40 = degC |
| Drive-log range | 43-65 raw (3-25 degC); rises with cumulative I^2*t; r=+0.975 |
| Seasonal range | ~43 (3 degC, cold Feb) to ~65 (25 degC, warm session) |
| Confidence | Medium |
| Notes | Anomalous values (raw 36-39, -4 to -1 degC) seen in some long overnight charge sessions while 0x507 B0 in the same session reads +20 degC -- B3 may carry a different signal or change meaning in charge mode. Use 0x507 B0/B1 or 0x430 B5 as temperature reference in charge-context analysis. |

#### 0x506 B1, B2, B3 -- Battery Temperatures (3 sensors)

| Attribute | Value |
|-----------|-------|
| Encoding | unsigned byte, raw - 40 = degC |
| Drive-log range | B1/B2: 55-58 raw (15-18 degC); B3: 59-63 raw (19-23 degC) |
| Confidence | Medium |
| Notes | Tracks closely with 0x373 B3 and 0x507 B0/B1 cluster in drive logs. B0=0x0F constant header; B4=1 constant; B5 binary flag (0/1). Sensor identity (which physical location each byte represents) unknown. Persists ~3s longer than other BMS IDs at key-off. |

#### 0x507 B0, B1 -- Battery Temperature Sensors A and B

| Attribute | Value |
|-----------|-------|
| Encoding | unsigned byte, raw - 40 = degC; 0x7F (127) = invalid/startup sentinel |
| Drive-log range | B0: 60-65 raw (20-25 degC); B1: 62-68 raw (22-28 degC) |
| Seasonal range (charge logs) | B0/B1 stable 57-65 across sessions; not affected by overnight ambient cooling |
| Confidence | Medium |
| Notes | B0/B1 track cell thermal mass more closely than 0x373 B3 -- remain stable during long overnight charges while B3 drifts toward ambient. Preferred temperature reference for charge-context analysis. B1 shares an unexplained correlated spike with 0x430 B4 (not present in any other signal); may reflect a shared sensor or data path. B2-B5 constant (0x29, 0x29, 0x4C, 0x55). |

#### 0x430 -- V_max, V_min, T_max, T_min (CONFIRMED 2026-03-02)

Complete 8-byte layout of 0x430 (20 Hz, BMS-originated):

| Bytes | Signal | Encoding | Scale | Confidence |
|-------|--------|----------|-------|------------|
| `(B0 & 0x0F) * 256 + B1` | V_max cell voltage | 12-bit unsigned, 1 mV/cnt | mV, no offset | High |
| B0 >> 4 | V_max segment tag | Status/identity bits; changes as pack state changes; meaning unclear | — | — |
| `(B2 & 0x0F) * 256 + B3` | V_min cell voltage | 12-bit unsigned, 1 mV/cnt | mV, no offset | High |
| B2 >> 4 | V_min segment tag | Same type as B0 tag | — | — |
| B4 | T_max cell temperature | unsigned byte, raw - 100 = degC (provisional) | degC | Medium |
| B5 | T_min cell temperature | unsigned byte, raw - 100 = degC (provisional) | degC | Medium |
| B6 | Constant 0x00 | No data | — | — |
| B7 | Frame state/freshness counter | LSB toggles 0/1 each frame; **bits[6:5] = BMS operating-mode flag** used as DBC validity mux (see below); upper bit evolves with BMS state (0x8C/0x8D normal, 0x7E/0x7F shutdown sentinel, 0x74-0x7F startup init range) | — | — |

**B7 bits[6:5] -- DBC validity mux (confirmed 2026-03-20, 527,034 frames, 14 logs):**
`(B7 & 0x60) == 0x00` = BMS in normal operating mode. `(B7 & 0x60) == 0x60` = BMS
offline, initializing, or shutting down. Values 01/10 never observed. Used in `vtrux
powertrain.dbc` as `BMS_ValidityMux` (startbit=61, 2-bit LE, mux=0 selects valid signals)
to suppress sentinel garbage (V=4094) and startup noise from graphs. **Caveat:** this is
the best available filter, not a true data-validity guarantee. During the BMS init window
(~2-6s after key-on; up to ~124s after fault recovery), voltages are physically plausible
but bits[6:5]=0x60 -- the mux will suppress those frames too. If the BMS never reaches
normal operating mode (e.g. stuck in init state, as seen in vtruxinterlocktest2.log), the
muxed signals will show no data at all; use `BMS_Vmax_430_unmasked`/`BMS_Vmin_430_unmasked`
in that case. See notes/cell-voltage-investigation.md "B7 Validity Flag" section.

**V_max/V_min evidence:** Both 12-bit masked fields correlate r>0.99 with DCDC HV/117 in
30-120s windows (full-log r collapses to near zero due to occasional B0/B2 MSB steps --
see notes/cell-voltage-investigation.md). V_max > V_min in every frame. Spread is 1-4 mV
at rest; 13-17 mV during late-session charging; up to ~250 mV in the original (severely
imbalanced) battery. Confirmed across truk1log (main truck, pre-swap/original battery) and
original battery logs. Shutdown/BMS-offline sentinel: B0=B2=0x1F, B1=B3=0xFE (value=4094).

**Segment tags:** The B0 and B2 upper nibbles identify the cell segment containing the
extreme. They change over time as different segments become the pack maximum/minimum, and
differ between the two physical batteries -- confirming they encode segment identity, not
a fixed field type. Do not assume constant values. The 9-BMS-board architecture (pack is 116 cells = 4×26s + 1×12s; board-to-cell assignment uneven and unresolved) does not map cleanly to the observed nibble range (0x0-0xE); exact
meaning is unresolved.

**T_max/T_min evidence:** B4 >= B5 in effectively all frames (35,867/35,874 in climit log).
Spread widens during high-discharge events (median 3 -> 5 degC, max 15 degC during 90+kW
discharge vs max 3 degC during regen), consistent with hottest cell diverging from coolest
under load. Absolute temperatures plausible across seasons (10-43 degC range in cross-log
check). Provisional encoding (raw-100=degC) is self-consistent but not calibrated against
an independent thermometer. Sentinel 0xFE = invalid (same as voltage fields).

| Attribute | B4 (T_max) | B5 (T_min) |
|-----------|-----------|-----------|
| Drive-log range | 121-141 raw (21-41 degC) | 119-133 raw (19-33 degC) |
| Seasonal range | ~+3 degC cold-soak to +39 degC Aug 2025 peak | same |
| Spike anomaly | shares unexplained correlated spike with 0x507 B1 | none |
| Preferred use | max cell temperature | min cell temperature; best seasonal indicator |

---

### 0x308 — BorgWarner TCM Park Pin State

**Source: BorgWarner TCM (same unit as in the Coda EV). Confirmed 2026-03-05 by cross-vehicle
ID/byte-structure match and correlated timeline analysis against the VCM gear position message in generator-on-then-off log.**

| Bytes | Signal | Encoding | Confidence |
|-------|--------|----------|------------|
| B0 | Park pin state | `0x20` = pin locked (Park); `0x40` = pin released (not Park) | **CONFIRMED** |
| B1-B2 (LE) | Shaft encoder counter | 16-bit LE position counter, zero at 32128 (0x7D80). Increments forward, decrements reverse; carry propagates B1→B2. Resets to ~32128 on Park. Prior r=0.997 vs motor RPM was spurious (short window pre-wrap); full-log r≈0. See `notes/borgwarner.md` Phase 1. | Medium — shaft (input vs output) unconfirmed |
| B2 | Constant 0x7D | Unknown | — |
| B3-B4 | Constant 0x00 | Unknown | — |

**Rate:** 100 Hz. **DLC:** 5.

**Timing correlation with gear position message (generator-on-then-off log):**
- Park exit: B0 = 0x40 at t=25.045; gear position message transitions at t=25.058 (13 ms lag — ~1 frame)
- Park entry: gear position message declares Park at t=56.000; B0 = 0x20 at t=56.065 (65 ms after — pin physically
  engages after position is declared, as expected for a solenoid-actuated mechanism)

**Cross-vehicle match (Coda 0x308):** Identical ID, frequency, DLC, and B0 values (0x20/0x40). On the Coda,
this message was identified as the D CAN park position indicator with the same encoding. Coda B1 also varies
widely, confirming the non-B0 bytes carry additional TCM data on both vehicles. This confirms both vehicles
use the same BorgWarner TCM hardware and firmware stack.

---

### 0x55C — BorgWarner TCM Heartbeat / Status

**Source: BorgWarner TCM. Confirmed 2026-03-05 by exact cross-vehicle match with Coda 0x55C (ID,
DLC, B0 range, B1-B3 all-zero structure, 10 Hz rate all identical) and correlated state transitions
in generator-on-then-off log.**

| Bytes | Signal | Encoding | Confidence |
|-------|--------|----------|------------|
| B0 | TCM state | Enum — see table below | **CONFIRMED** |
| B1-B3 | Constant 0x00 | Unknown | — |

**Rate:** 10 Hz. **DLC:** 4. **First appears:** t=8.58 in generator log (before gear shifts — steady
Park-idle state from startup).

**B0 state enumeration (from generator-on-then-off log):**

| B0 | State |
|----|-------|
| 0x42 (66) | Steady Park — TCM idle in Park |
| 0x04 (4) | Park releasing — brief transition state exiting Park |
| 0x85 (133) | Drive/Manual active — park pin released, vehicle in gear |
| 0x01 (1) | Park engaging — brief transition state entering Park |

**Timing correlation (generator-on-then-off log):**
- Park exit: B0 = 0x04 at t=25.100 (55 ms after 0x308 pin release), B0 = 0x85 at t=25.380
- Park entry: B0 = 0x01 at t=56.130 (65 ms after park pin engages), B0 = 0x42 at t=56.400

**Cross-vehicle match (Coda 0x55C):** On the Coda, this ID is the confirmed TCM heartbeat carrying
ParkLock and DriveSensor flags. Coda survey shows identical structure: DLC=4, B0 range 0x01-0x85,
B1-B3 = 0x00, 10 Hz. The B0 values map directly: 0x01/0x04 are transition states, 0x42 is steady
Park, 0x85 is drive-active.

---

## Mirror / Rebroadcast Signals

These appear to be filtered or republished copies from other ECUs:

| Signal | Notes |
|--------|-------|
| 0x595 LE W0 | Mirrors generator power |
| 0x596 LE W0 | Mirrors generator power |
| 0x63D LE W0 | Mirrors generator power (r≈0.91) |
| 0x050–0x054 | Follow same offset pattern as OBD 0x040–0x044. 0x051 is confirmed as a real composite command (gen torque B1-B2, **engine/generator RPM reference B3-B4**). 0x052 B2-B3 is the **engine/generator RPM reference** (identical to 0x051 B3-B4). *(Corrected 2026-03-03 — the earlier "traction drive torque command" label was a misidentification; there is no traction drive command on the PT bus, the TRAC MCU is on the OBD bus and its command is 0x041. See the 0x051/0x052 sections.)* 0x053 = generator/system mode status (see section above). 0x054 B0-B1 CONFIRMED as primary generator RPM (LE uint16, ~1 RPM/count, overflow-immune — see 0x054 section above). |
| 0x470-0x484 | Share +0x30 ID offset with OBD 0x440-0x454, but mirror direction unconfirmed (timing inconclusive; 0x452 does not exist on any bus; 0x440 and 0x470 both only on powertrain bus). **0x482 and 0x470 confirmed as POST-contactor HV DC bus voltage** (interlock test + drive correlation r=0.9974). Encoding: B1-B2 LE = integer volts (1 V/count, uint16), B0 = fractional. **0x440 B3-B4 LE** also confirmed post-contactor voltage (r=0.9818), but encoding is **NOT integer volts** — in driving logs, B3-B4 reads 21k–26k (vs expected 337–408V), consistent with 1/64 V/count (≈ 0.015625 V/count). Previously documented as integer volts; that was incorrect. See `context-voltage-current.md` interlock test section. |
