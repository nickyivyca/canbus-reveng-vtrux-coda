# Vtrux Thermal Investigation


## Signal Summary

*Updated 2026-03-29: GENE MCU thermal percentage signals confirmed (0x479 B0/B1/B2, EPRI DBC). TRAC MCU thermal found at 0x44A B0/B1/B2 via OBD correlation (EPRI ID 0x459 absent). 0x06000002 B5/B6 re-identified as thermal percentage re-broadcast, not a winding temperature.*

| ID | Bytes | Signal | Encoding | Observed Range (raw) | °C Range | Confidence |
|----|-------|--------|----------|----------------------|----------|------------|
| 0x18FFD5C0 | B0-B1 | Charger overall inverter temp | LE signed int16 × 0.1°C | 438–460 | 43.8–46.0°C | High (DBC confirmed) |
| 0x18FFD5C0 | B2-B3 | Charger buckboost temp | LE signed int16 × 0.1°C | 438–452 | 43.8–45.2°C | High (DBC confirmed) |
| 0x18FFD5C0 | B4-B5 | Charger ambient temp | LE signed int16 × 0.1°C | 284–317 | 28.4–31.7°C | High (DBC confirmed) |
| 0x18FFDAC0 | B0-B1 | Charger dc1 temp | LE signed int16 × 0.1°C | 440–459 | 44.0–45.9°C | High (DBC confirmed) |
| 0x18FFDAC0 | B2-B3 | Charger dc2 temp | LE signed int16 × 0.1°C | 438–452 | 43.8–45.2°C | High (DBC, not yet extracted) |
| 0x18FFDAC0 | B4-B5 | Charger module1 temp | LE signed int16 × 0.1°C | 431–448 | 43.1–44.8°C | High (DBC, not yet extracted) |
| 0x18FFDAC0 | B6-B7 | Charger module2 temp | LE signed int16 × 0.1°C | 393–417 | 39.3–41.7°C | High (DBC, not yet extracted) |
| 0x18FFDBC0 | B0-B1 | BuckBoost module temp | LE signed int16 × 0.1°C | 403–415 | 40.3–41.5°C | High (DBC, not yet extracted) |
| 0x18FFDBC0 | B2-B3 | BuckBoost dc1 temp | LE signed int16 × 0.1°C | 438–452 | 43.8–45.2°C | High (DBC, not yet extracted) |
| 0x18FFDBC0 | B4-B5 | BuckBoost dc2 temp | LE signed int16 × 0.1°C | 431–448 | 43.1–44.8°C | High (DBC, not yet extracted) |
| 0x18FFDBC0 | B6-B7 | BuckBoost DSP temp | LE signed int16 × 0.1°C | 350–390 | 35.0–39.0°C | High (DBC, not yet extracted) |
| 0x18FFD6B3 | B2-B3 | DCDC 12V output current (unconfirmed) | LE unsigned × 0.05 A | 0–192 raw | 0–9.6A | Low — observed 0-9.6A range in charge sessions; decay pattern consistent with 12V battery top-off but not confirmed; Phase 2C inconclusive |
| 0x18FFD6B3 | B6-B7 | DCDC temperature | LE signed int16 × 0.1°C | 184–415 | 18.4–41.5°C | High — Phase 1C, thermal trajectory across full charge session |
| 0x18FF0320 | B3 | PE pump coolant temp | unsigned byte × 0.1°C | 73–254 | 7.3–25.4°C | High — Phase 1B calibrated |
| 0x18FF0320 | B5 | PE pump speed feedback | raw count (0=stopped, 241=full speed) | 0–241 | — | High |
| 0x18FF0320 | B4 | PE pump VFD status tier | VFD-reported tier (36 or 38) | 36–38 | — | Medium |
| 0x18EF2000 | B0 | PE pump enable (VCU cmd) | 0=disabled, 1=enabled | 0–1 | — | High |
| 0x18EF2000 | B3 | PE pump speed setpoint (VCU cmd) | 0=stop, 1–11=tiers (6 never used), 11=max | 0–11 | — | High |
| 0x373 | B3 | Battery system temperature (internal — enclosure/board, not confirmed cell) | unsigned byte, raw−40 = °C | 43–65 | 3–25°C | Medium — r=+0.975 vs I²·t; consistent across 5 sessions Feb 2026; encoding provisional |
| 0x506 | B1, B2, B3 | Battery temperatures (3 sensors, identity unknown) | unsigned byte, raw−40 = °C | 55–63 | 15–23°C | Medium — tracks with 0x373/0x507 cluster in drive logs; B5 is a binary flag |
| 0x507 | B0 | Battery temperature sensor A | unsigned byte, raw−40 = °C; sentinel 0x7F=invalid | 60–65 | 20–25°C | Medium — correlates with 0x373 B3 in drive logs |
| 0x507 | B1 | Battery temperature sensor B (correlated with 0x430 B4) | unsigned byte, raw−40 = °C; sentinel 0x7F=invalid | 62–68 | 22–28°C | Medium — shares unexplained spike with 0x430 B4 |
| 0x430 | B4 | T_max cell temperature (correlated with 0x507 B1) | unsigned byte, `raw * 0.5 − 40 °C` (EPRI decompile confirmed) | 121–141 | 20.5–30.5°C | Medium — identified as T_max; B4>=B5 in all frames; spread peaks 15°C during heavy discharge vs 3°C max during regen; see notes/cell-voltage-investigation.md |
| 0x430 | B5 | T_min cell temperature | unsigned byte, `raw * 0.5 − 40 °C` (EPRI decompile confirmed) | 119–133 | 19.5–26.5°C | Medium — identified as T_min; no spike anomaly; best seasonal indicator |
| 0x483 | B0 | Unknown temperature A (not PE coolant loop) | unsigned byte, raw−100 = °C | 116–181 | 16–81°C | Medium — overheat test Mar 2026; starts at cold-soak ambient, rises monotonically through full test including pump-at-full-speed; does not plateau or drop with pump |
| 0x483 | B2[0]+B1 | Unknown temperature A, fine (9-bit) | (B2 bit0)<<8 \| B1; scale unknown | 181–493 | — | Medium — nearly monotonic (1 dip); r_win=0.979 vs DCDC temp; same thermal source as B0 at finer resolution |
| 0x483 | B2[7:4] | Thermal derating zone | upper nibble of B2; values 3–6 | 3–6 | — | Medium — 4 discrete levels; 5=normal, 6=high-temp, 3–4=during pump-at-full-speed oscillation; independent of 9-bit carry |
| 0x595 | B2 | PE water/glycol cooling loop temperature (candidate, possibly generator-side) | unsigned byte, scale unknown | 17–93 normal drive; 19–93 overheat test | — | Low-Medium — VCU-sourced; 1 Hz; B3=0x80 valid flag; rises from ambient (~19) to ~93 under motor load with no response to oil pump events; consistent with PE glycol loop; 59x cluster may be generator-oriented; 2026-03-12 overheat test |
| 0x619 | B2 | Thermal fault accumulator / derating mode indicator | discrete states {0, 46, 59, 84, 99, 109} | 0–109 | — | Medium — saturates at 109 during no-cooling cycle; clears to 0 within 0.4s of pump command restore (too fast for thermal cooling = not a temperature); inverter fault flag |
| 0x619 | B5 | Thermal current headroom / IGBT limit (inferred) | raw unsigned, declining as load accumulates | 127–225 | — | Low-Medium — r=-0.84 vs smoothed drive torque; does NOT recover when pump at full speed; inverter likely reducing current limit as internal IGBT temps rise without broadcasting those temps |
| 0x06000002 | B5/B6 | **Traction motor thermal load indicator (PT bus re-broadcast of OBD 0x44A B2)** | 10-bit Intel LE at startbit 46: `(B6<<2)\|(B5>>6)`. B5[1:0] are ADC jitter. B5[5:2] constant padding (bit5=1, bits4:2=0). **Scale ~1.0%/count** (confirmed 2026-03-29 by comparing against OBD 0x44A B2). | 0–82 raw | ~0–82% | **High** — 2026-03-12 (encoding), 2026-03-29 (role and scale revised). Bit packing confirmed. Original scale 2.0 deg C/count and "164°C peak" were WRONG. VCU reads OBD 0x44A B2 (TRAC_ThermInd_pct, 0.78125%/count) and re-broadcasts the resulting percentage as a 10-bit integer on PT bus: raw10 ≈ percentage value. At derate onset (t=1953s drivetrain overheat): raw10=78, OBD pct=78.9%. Artifacts: `b5b6_bit_analysis.png`, `motor_temp_9bit.png`, `verify_b5_encoding.py`. |
| 0x479 | B0 | GENE inverter cooling flow request | `raw × 0.78125 %`; raw 128 = 100% | 0–128 | — | **High** (EPRI DBC confirmed) — 2026-03-29. Steady ~50% at normal load; rises toward 100% under sustained overheat. PE glycol loop. |
| 0x479 | B1 | GENE motor oil cooling flow request | `raw × 0.78125 %`; raw 128 = 100% | 0–128 | — | **High** (EPRI DBC confirmed) — 2026-03-29. Saturates at 100% during generator oil pump unplug overheat test; drops to 0 when generator not under load. Oil circuit. |
| 0x479 | B2 | GENE thermal load indicator | `raw × 0.78125 %`; raw 128 = 100% | 0–128 | — | **High** (EPRI DBC confirmed) — 2026-03-29. Rises monotonically through overheat event, peaks at ~86.7% near RPM overflow event. Generator torque derate onset observed at **~85-86%** (confirmed from gen overheat log: sustained high torque from 80% crossing to cutback, ~120s). Not a raw temperature. |
| 0x44A | B0 | TRAC inverter cooling flow request | `raw × 0.78125 %`; raw 128 = 100% | 0–128 | — | **High** — 2026-03-29. Symmetric to GENE 0x479 B0. EPRI claimed 0x459 but that ID has 0 frames in all logs; 0x44A confirmed via OBD correlation scan (r=+1.000 vs 0x06000002 10-bit). |
| 0x44A | B1 | TRAC motor oil cooling flow request | `raw × 0.78125 %`; raw 128 = 100% | 0–128 | — | **High** — 2026-03-29. Symmetric to GENE 0x479 B1. Same structure: 0 when traction motor idle, saturates at 100% under sustained thermal stress. |
| 0x44A | B2 | TRAC thermal load indicator | `raw × 0.78125 %`; raw 128 = 100% | 0–128 | — | **High** — 2026-03-29. Symmetric to GENE 0x479 B2. r=+1.000 vs 0x06000002 10-bit (PT bus re-broadcast). VCU reads this from OBD bus and mirrors it onto PT bus via 0x06000002 B5/B6 at ~1.0%/count. Traction derate onset at **~78-79%** (confirmed from drivetrain overheat log at t=1953s). B3 is a rolling counter. |

---

## Phase 1A — PE Glycol Water Pump

### 0x18FF0320 — Pump Feedback Message

| Attribute | Value |
|-----------|-------|
| PGN | 0xFF03 (65283) — manufacturer-proprietary |
| Source address | 0x20 (PE pump controller) |
| Bus | PT bus (channel number varies per session) |
| Rate | ~0.2–1 Hz |

#### B5 — Pump Speed Feedback

```
speed_feedback = B5   [unsigned byte, 0=stopped, 241=full speed]
```

The clearest signal in the dataset. In the pump disconnect log (Feb 25, 2026):

| Phase | B5 |
|-------|----|
| Normal operation before disconnect (t=3.5–33.5s, no charging active) | **0 throughout** |
| CAN reconnect burst (t=162.46s) | 238–241 (pump still at mechanical failsafe speed) |
| One frame after reconnect (t=163.7s) | **Drops to 0 immediately** |
| Remainder of log (VFD back in control) | **0 throughout** |

The 241→0 drop in a single frame (~1 second) matches the audible observation that the pump drops from full speed to nearly stopped immediately when the CAN connector is reconnected. The VFD takes back control, reads the commanded speed (0, no charging active), and instantly kills the motor.

During chargedown (Aug 21, 2025, active charging):
- B5 starts at 8 (t=10s into log) and slowly rises: 8→9→10→11
- Plateaus at 11 by t=71s and holds there for the remaining ~225s

The pump operates at very low speed during normal charging (B5≈8–11 out of 241 = 3–5% of max). Consistent with the pump "barely getting started" in normal operation; full speed is much faster.

#### B3 — Coolant Temperature (primary)

Slowly and continuously varying. Does NOT change when pump speed changes, confirming it is thermal not mechanical.

| Log | B3 range | Rise rate | Context |
|-----|---------|-----------|---------|
| Pump disconnect (Feb 25, cold start) | 73→107 over 29s | +1.2 units/s | Charger cold, coolant warming up |
| chargedown (Aug 21, mid-charge) | 128→164 over 287s | +0.13 units/s | Charger already warm, steady heat buildup |
| Post-reconnect (after 128s at full pump speed) | 254→240 over 19s | −0.8 units/s | Coolant very hot, slowly cooling |

**Working encoding** (needs Phase 1B calibration against confirmed charger temperature):

```
temp_degC ≈ B3 × 0.5 − 28
```

Gives plausible values given seasonal context:
- B3=73 (Feb cold start) → ~8.5°C
- B3=128 (Aug, mid-charge start) → ~36°C
- B3=164 (Aug, after 5 min charging) → ~54°C
- B3=254 (after 128s at full failsafe pump speed) → ~99°C

#### B4 — Speed Tier / Operating Mode

Constant within each session, different between sessions:
- Pump disconnect test (no charging, pump idle): B4 = **36** (0x24)
- chargedown (active charging): B4 = **38** (0x26)
- Reconnect transient: briefly 37 as pump transitions

Hypothesis: VCU selects a higher operating tier (38) when charging is active. Could also be embedded speed command.

#### B1-B2 — Cumulative Counter

16-bit LE counter (B1 low, B2 high), incrementing at variable rate. Likely a flow pulse or rotation counter. Not temperature-related.

#### B7 — Secondary Slowly-Varying Signal

Rises slowly in sync with B3 during charging (chargedown: 52→61 over 287s). Possibly pump board or motor temperature. Not decoded.

---

### 0x475 — System CAN Heartbeat (NOT pump-specific)

All-zero payload, 7.2 Hz, broadcasts continuously for the **entire** 182s disconnect log including the 128s pump CAN gap. Does not stop during pump disconnect.

Previous assumption that "0x475 stops 31s after pump CAN disconnect" is **not supported** by this log. It is a system-level keepalive unrelated to pump state.

Counterpart: 0x446 on Bus 1 at 7.1 Hz — same behavior on a second bus.

---

### 0x18EF2000 — VCU→Pump Command Message

**Identified.** J1939 PDU1 format: PF=0xEF (239), destination=0x20 (pump VFD), SA=0x00 (VCU). Confirmed on Bus 3 (PT bus) in both chargelog_M1 and the pump disconnect log.

| Byte | Role | Values |
|------|------|--------|
| B0 | Enable flag | 0=disabled (pump off), 1=enabled |
| B3 | Speed setpoint | 0=stop, 1–11=speed tiers, 11=max requested |
| B1-B2, B4-B7 | Constant zero | — |

#### Speed Ramp Protocol

The VCU never jumps B3 directly to target — it soft-starts and soft-stops:

**Soft-start ramp** (each step held ~1s / 2 frames at 2 Hz):
```
0 → 1 → 2 → 3 → 4 → 5 → 7 → 8 → 9 → 10 → 11
```
Value 6 is **always skipped**. Total ramp time: ~12–14 seconds from stop to full target.

**Soft-stop:** B3 steps to 7, holds ~2.5s, then drops to 0. B0 drops to 0 at the same time.

#### Command ↔ Feedback Timing (chargelog_M1)

| Event | B3 cmd → 0 (stop) | B5 fbk → 0 lag | B3 starts ramp | B5 fbk → 3 lag |
|-------|--------------------|-----------------|----------------|-----------------|
| Cycle 1 | t=20.3s | ~1.6s | t=61.3s | ~6.6s |
| Cycle 2 | t=131.3s | ~0.6s | t=169.3s | ~6.6s |
| Cycle 3 | t=274.4s | ~1.5s | t=308.4s | ~7.5s |

Stop lag (~1s): one CAN frame delay. Start lag (~7s): pump remains unresponsive until B3 ramps past ~4.

#### Disconnect Log Cross-Check

In the pump disconnect log (no charging active), 0x18EF2000 broadcasts `00 00 00 00 00 00 00 00` for the full 182s — B0=0, B3=0 throughout. The pump was commanded off the entire time. When the CAN connector was physically pulled, the pump VFD lost the command, triggered its failsafe (B5→241), then immediately dropped back to B5=0 the instant CAN reconnected and it heard B3=0 again. This confirms the command/failsafe relationship.

#### B4 Revisited

B4 of 0x18FF0320 (pump feedback, not command) is constant at 36 in the disconnect log and in chargelog_M1. It was 38 in other sessions. Now that the command is identified as 0x18EF2000, B4 is likely a pump status tier reported by the VFD itself (not a VCU command byte).

---

### Key Timestamps — Pump Disconnect Log

| Event | Time |
|-------|------|
| First pump frame | t=3.5s |
| Last pump frame (CAN disconnect) | t=33.5s |
| Pump CAN absent | t=33.5–162.5s (128.9s; pump at mechanical full speed) |
| CAN reconnect burst | t=162.46s |
| B5 drops to 0 | t=163.7s |
| Log end | t=181.7s |

---

### Parser Fix — Truncated BUSMASTER Headers

`chargedown.log` is missing the standard `***BUSMASTER Ver X.X***` first line and starts directly with `***START DATE AND TIME`. `BusmasterParser.detect()` in `canre/parsers/busmaster.py` was updated to also match this pattern, `***END CHANNEL BAUD RATE***`, and data lines directly.

---

### Open Questions

1. **B3 encoding calibration**: ~~Phase 1B will overlay B3 against confirmed charger temperature.~~ **Resolved in Phase 1B.** Encoding is ×0.1°C. The old ×0.5−28 hypothesis was disproved: at t=580s of chargelog_M1, B3=241 (24.1°C) while charger body = 44.9°C — physically consistent. The former formula would give 92.5°C, which is impossible.
2. **B5 upper limit**: Does B5 ever exceed 11 in longer/hotter charging sessions? Check "full charge then fail.log."
3. **B4 dynamics**: Does B4 ever change within a single charging session, or is it always static?
4. **Pump command**: ~~Not yet found.~~ **Resolved — 0x18EF2000 B3/B0.** See "VCU→Pump Command Message" section.

---

## Phase 1B — Charger Temperature Baseline (chargelog_M1.log)

**Log:** `chargelog_M1.log` — Jan 28, 2025, ~580s duration. Winter session; charger already warm at log start (session was underway before capture began).

**Artifacts:** `chargelog_M1_overall_temp.csv`, `chargelog_M1_buckboost_temp.csv`, `chargelog_M1_ambient_temp.csv`, `chargelog_M1_dc1_temp.csv`, `chargelog_M1_pump_B3.csv`, `chargelog_M1_pump_B5.csv`

### Confirmed Charger Temperature Signals

All signals from `BelInverter.dbc`, LE signed int16, factor 0.1°C, offset 0:

| Signal (DBC name) | ID | Bytes | Start (raw/°C) | End (raw/°C) | Behavior |
|-------------------|----|-------|----------------|--------------|----------|
| overAllInverterTemperature | 0x18FFD5C0 | B0-B1 | 449 / 44.9°C | 449 / 44.9°C | Oscillates ±1°C with pump cycling |
| buckBoostTemperature | 0x18FFD5C0 | B2-B3 | 447 / 44.7°C | 445 / 44.5°C | Same oscillation, slightly lower |
| ambientTemperature | 0x18FFD5C0 | B4-B5 | 284 / 28.4°C | 317 / 31.7°C | Monotonic rise +3.3°C over 580s |
| dc1Temperature | 0x18FFDAC0 | B0-B1 | 449 / 44.9°C | 449 / 44.9°C | Matches overall inverter; slightly sharper peaks |

The bytes B6-B7 of 0x18FFD5C0 (`overallTemperaturePercent`, unsigned 0–100) are all zero throughout this log — either unused in this firmware or 0 = "no thermal stress."

Survey byte-range data confirms the remaining unextracted signals exist in this log:
- dc2Temp (0x18FFDAC0 B2-B3): 438–452 raw
- module1Temp (0x18FFDAC0 B4-B5): 431–448 raw
- module2Temp (0x18FFDAC0 B6-B7): 393–417 raw — notably cooler
- buckBoostModuleTemp (0x18FFDBC0 B0-B1): 403–415 raw — cooler than inverter side
- buckBoostDspTemp (0x18FFDBC0 B6-B7): 350–390 raw — lowest of all (DSP chip, low dissipation)

### Pump ↔ Charger Temperature Correlation

Pump B5 cycles between 0 and 3 in this log (intermittent low-speed operation). B4=36 constant throughout.

| Pump phase | B5 | Duration | Charger overall temp behavior |
|------------|----|----------|-------------------------------|
| ON | 3 | 0–21s | 449 → 441 (cooling) |
| OFF | 0 | 21–67s | 441 → ~457 (rising) |
| ON | 3 | 67–132s | peaks at 459 at ~t=82s (+15s lag), then falls to 442 |
| OFF | 0 | 132–175s | brief continued fall, then starts rising |
| ON | 3 | 175–275s | peaks at 460 at ~t=188s, falls to 442 |
| OFF | 0 | 275–315s | 442 → 455 (rising) |
| ON | 3 | 315–580s | peaks at 460 at ~t=330s, then slow descent to 449 |

**~15-second lag** between pump turning on and temperature starting to fall — time for coolant to circulate and begin drawing heat from the sensors.

### Pump B3 Encoding Confirmed

Pump B3 rises monotonically 101 → 241 over 580s, independent of pump on/off cycling.

| t | B3 raw | °C (×0.1) |
|---|--------|-----------|
| 0s | 101 | 10.1°C |
| 132s | 132 | 13.2°C |
| 275s | 170 | 17.0°C |
| 315s | 180 | 18.0°C |
| 580s | 241 | 24.1°C |

Rate: ~0.024°C/s = 1.44°C/min. Physically consistent: coolant (10→24°C) warms as it absorbs heat from the charger body (45°C). Coolant always remains below charger temperature as required.

**The Phase 1A working hypothesis (×0.5−28) is wrong** — it gives 92.5°C at B3=241, impossibly hotter than the 44.9°C charger body. Correct encoding: **×0.1°C (unsigned byte)**.

### Thermal Architecture Summary

Temperature gradient observed in this session:
- Charger inverter (dc1 / overall): 44–46°C — hottest (power semiconductors)
- Charger buckboost: 43–45°C
- Charger module2: 39–42°C — cooler (output-side or smaller devices)
- BuckBoost module: 40–42°C
- BuckBoost DSP: 35–39°C — coolest internal (logic chip, low dissipation)
- Charger ambient (inside housing): 28–32°C
- PE coolant (pump B3): 10–24°C (cold January loop warming up)

### Open Questions After Phase 1B

1. **B4=36 constant**: In this log B4=36 throughout even with active charging (B5 cycling). What determines which tier is commanded? Does B4 ever change mid-session?
2. **overallTemperaturePercent = 0**: Is this always zero, or does it appear in hotter sessions?
3. **Pump command signal**: ~~Still unidentified.~~ **Resolved — 0x18EF2000 B3/B0.** Identified later in Phase 1A write-up (see above).

---

## Phase 1C — DCDC Temperature Hunt

**Logs:** `logs/after-battery-swap-charges/charge_M0_T0.log`, `T20.log`, `T40.log` + `logs/other-logs/chargelog_M1.log` (cross-check)

**Artifacts:** `dcdc_0x18FFD6B3_swapT0.txt`, `dcdc_0x18FFD6B3_swapT20.txt`, `dcdc_0x18FFD6B3_swapT40.txt`, `pump_0x18FF0320_swapT20.txt`, `dcdc_0x18FFD6B3_B6_swapT0.csv`, `dcdc_0x18FFD6B3_B0_swapT0.csv`, `pump_B3_swapT0.csv`, `chargelog_M1_survey.json`

### What the DCDC Actually Broadcasts

The DCDC (SA=0xB3) broadcasts only 4 IDs. Unlike the charger, it does **not** have dedicated temperature message IDs (D5/DA/DB PGN analogs do not exist for 0xB3). Survey of chargelog_M1 confirmed:

| ID | Freq | Role |
|----|------|------|
| 0x18E8FFB3 | 10 Hz | J1939 acknowledgment (constant payload) |
| 0x18FECAB3 | 1 Hz | J1939 network management (constant) |
| 0x18FFD4B3 | 10 Hz | Status message — mostly zeros; B6=227 constant in steady state, varies (5 discrete values) at startup |
| 0x18FFD6B3 | 10 Hz | Electrical/thermal measurements — **all variable signals including confirmed HV voltage and newly confirmed temperature** |

Temperature is encoded within **0x18FFD6B3**, not in a separate message.

### 0x18FFD6B3 — Full Decode (Steady Operating State, B0=31)

| Bytes | Signal | Encoding | Confidence |
|-------|--------|----------|------------|
| B0-B1 | LV output voltage | LE signed int16 × 0.05V; ~14.35V regulated; ~12.1V during startup | Medium — consistently observed, no direct meter validation |
| B2-B3 | Unknown | LE format, range 59–153 across sessions, × 0.05 gives ~3–8 units | Unconfirmed role |
| B4-B5 | HV input voltage | LE signed int16 × 0.05V; B5 steps at each 12.8V boundary (B5=0x1E at ~385V, B5=0x20 at ~419V) | **Confirmed** (see `context-voltage-current.md`) |
| B6-B7 | **DCDC temperature** | LE signed int16 × 0.1°C | **Confirmed** — see below |

**B0 is a DCDC operating state byte**, not a mux key:
- B0=242–241: startup initializing (~6s, LV not yet regulated)
- B0=30: early operating transient (~100s)
- B0=31: steady operating state (dominant; same value seen in all steady-state sessions)

### Temperature Confirmation — Thermal Trajectory

B6-B7 as LE unsigned uint16 × 0.1°C (signed int16 gives identical result for positive temps):

| Chunk | Session time | B6 | B7 | uint16 | °C | Condition |
|-------|-------------|-----|-----|--------|-----|-----------|
| T0 start (t=35s) | ~35s | ~186 | 0 | 186 | 18.6°C | Cold start (winter, battery just swapped) |
| T0 end (t=287s) | ~287s | 220 | 0 | 220 | 22.0°C | ~4 min charging, beginning to warm |
| chargelog_M1 | mid-session | 22–31 | 1 | 278–287 | 27.8–28.7°C | ~Jan 2025, moderate session |
| T20 start | ~6000s | 156–159 | 1 | 412–415 | 41.2–41.5°C | Peak charging current |
| T40 | ~12000s | 89–94 | 1 | 345–350 | 34.5–35.0°C | CV phase, reduced current, DCDC cooling |

**B7 transitions from 0 → 1 when temperature exceeds 25.5°C** (raw uint16 value > 255), which is normal LE uint16 behavior — not a mode change.

**Physical consistency checks:**
- Cold start (18.6°C) ≈ garage ambient in winter ✓
- Peak temperature (41.5°C) reached at mid-session full CC-phase current ✓
- Temperature drops (41°C → 35°C) as charge enters CV phase and current decreases ✓
- Coolant temperature at T20 (pump B3 = 22.6–23.4°C) is cooler than DCDC (41°C) — heat flows DCDC → coolant → removed by pump ✓
- DCDC peak (~41°C) is cooler than charger inverter (~44–46°C) — DCDC is a smaller unit with less waste heat ✓

### DBC Update

Signals added to `vtrux-powertrain.dbc` under existing `BELDCDC_analogMeasurements` message (0x18FFD6B3):
- `BELDCDC_lvOutputVoltage` — B0-B1 (medium confidence)
- `BELDCDC_temperature` — B6-B7 (**confirmed**)

B2-B3 left undeclared until role is confirmed.

### Open Questions After Phase 1C

1. **B2-B3 role**: LE uint16 × 0.05 = 3–8 units. Candidates: LV output current (4–8A at 12V = 48–96W, plausible 12V load), LV input power, or a second voltage channel. Needs direct 12V current measurement to confirm.
2. **B0 meaning**: Values 30–31 in steady state, 242→241 during startup. Whether B0 encodes a specific DCDC internal state (e.g., soft-start phase, regulation locked) is unknown.
3. **0x18FFD4B3 B6**: Shows 5 discrete values (150, 182, 227, ...) during startup sequence. Likely a DCDC internal status code, not temperature. Not investigated further.

---

## Phase 2A -- BMS Cluster Temperature Candidates (Complete)

### Source Confirmation

**0x370-0x375 are BMS-dependent.** Confirmed by the disconnect test in
`notes/interlock-bitfields-analysis.md` (Message Source Attribution section):
all six IDs disappear simultaneously when the HV battery LV connector is unplugged
(~t=75s in `vtruxunplugpumpthenhvbatterylvconnector.log`) and reappear when
reconnected (~t=87s). Absent from the parts truck (no HV battery).

The cell section BMS boards power from 12V (not HV-side) with a ~6-7 second boot
delay. Confirmed by `vtruxinterlocktest2.log`: HVIL open (HV never came up), yet
0x375 counter still started at 1 at t=7.5s.

**0x640** is VCU-sourced (present on parts truck). In every log examined it settles
to a static payload (`15 80 00 00 00 00 00 00`) within ~0.3s. Not a temperature signal.

### Message Structure

All six IDs broadcast at 0.7-0.9 Hz. Pack architecture: 9 BMS boards (pack is 116 cells = 4×26s + 1×12s; board-to-cell assignment unresolved).

| ID | Variable bytes | Constant/structural bytes |
|----|---------------|--------------------------|
| 0x370 | B0, B1, B4, B6 | B2=0, B5=0; B3/B7 = small int (0-4) |
| 0x371 | B0, B1, B4, B6 | B2=0, B5=0; B3/B7 = small int (0-4) |
| 0x372 | B0, B2, B4, B5 | B1=0x14 constant; B3=B6=B7=0 |
| 0x373 | B4; B1/B3 unclear | B0=0, B2=0, B5=B6=0; B7 = monotonic counter |
| 0x374 | B0, B1, B4, B6 | B2=0, B5=0; B3/B7 = small int (0-4) |
| 0x375 | B4 only | All others 0; B4 = session message counter (1, 2, 3, ...) |

Variable bytes in 0x370-0x374 have 3-8 unique values and change slowly over minutes.
Already confirmed as non-voltage in `cell-voltage-investigation.md` (eliminated
because they "slow-drift over minutes, don't respond to discharge events").

### I^2*t Analysis -- Primary Result

**Script:** `artifacts/i2t_bms_correlation.py` on `logs/vtruxcurrentlimitingtest.log`

**Battery current (0x598 B0-B1):**
- Duration: 1809s; 73% discharge / 24% regen / 3% near-zero
- Max discharge: +13192 counts (~527 A); Max regen: -5770 counts (~231 A)
- Cumulative I^2*t: 1.48e10 count^2*s

**Full correlation table (sorted by |r|):**

| ID | Byte | r vs I^2*t | unique | range | first | last | mono% |
|----|------|-----------|--------|-------|-------|------|-------|
| 0x373 | B3 | **+0.975** | 7 | 6 | 59 | 65 | 57% |
| 0x372 | B4 | -0.910 | 4 | 3 | 58 | 56 | 25% |
| 0x373 | B1 | -0.887 | 3 | 2 | 58 | 56 | 0% |
| 0x372 | B5 | -0.875 | 4 | 3 | 58 | 56 | 43% |
| 0x372 | B2 | -0.717 | 5 | 5 | 56 | 53 | 29% |
| 0x370 | B0 | -0.644 | 5 | 4 | 61 | 59 | 44% |
| 0x371/0x374 | B4 | ~-0.61 | 5 | 4 | ~61 | ~59 | ~44% |
| ... | ... | ~-0.55 | ... | ... | ... | ... | ... |

0x370/0x371/0x374 variable bytes all cluster at r=-0.55 to -0.65.
Artifacts: `i2t_bms_correlation.py`, `i2t_bms_candidates.csv`

### 0x373 B3 -- Battery Temperature (Best Candidate)

**r = +0.975** vs cumulative I^2*t. Confirmed battery-temperature-related signal.

**Timeseries shape in current limiting test:** B3 makes 6 step-increases (59->65)
over 1809s, each step held for ~200-450 seconds before the next. This is
characteristic of a slowly-warming thermal mass, not an instantaneous or counter-
type signal.

| Session | Date | B3 | degC (raw-40) | Notes |
|---------|------|----|---------------|-------|
| charge_M0_T0.log | Jan 16, 2026 | 56 constant | 16 degC | Cold start; DCDC at 18.6 degC -- consistent |
| movingaroundindriveway.log | Feb 16, 2026 | 43 | 3 degC | February, cold-soaked overnight outdoors |
| vtruxevapdrivelog4.log | Feb 25, 2026, 20:42 | 55->57 | 15->17 degC | Winter evening drive |
| vtruxevapdrivelog4part2.log | Feb 25, 2026, 21:07 | 57->56 | 17->16 degC | Brief post-drive segment, cooling |
| vtruxcurrentlimitingtest.log | Feb 25, 2026, 23:37 | 59->65 | 19->25 degC | 2.5h after evap drive |

**Cross-session check:** Evap drive part 2 ends at B3=56 (16 degC). Current limiting
test starts 2.5h later at B3=59 (19 degC) -- the battery WARMED by 3 degC while the
truck sat outside. This is consistent with "battery internal ambient" behavior: the
pack interior (insulated by cell mass and housing) retains heat longer than surface
temperature, and may even absorb some residual heat from BMS electronics running in
standby. It is NOT consistent with simple outdoor ambient tracking (February night air
would cool the pack, not warm it).

**Encoding: raw - 40 = degC (provisional).** Consistent across all sessions above.
All values are physically plausible for the respective dates and conditions.

### Signal Character Interpretation

**0x373 B3 is some form of battery system temperature -- exact sensor location
unknown.** It is NOT confirmed as cell temperature. Possible interpretations:

1. **Battery internal ambient / enclosure air temperature** -- Temperature sensor
   inside the battery housing measuring air trapped among cells. Would respond slowly
   to cell heating (thermal lag through cell surface + air) and track cell thermal mass
   rather than surface conditions. Consistent with the observed slow response and with
   the pack interior staying warmer than outside air during a 2.5h rest.

2. **BMS board or shunt box temperature** -- A sensor on one of the 9 BMS cell-
   monitoring boards or on the main contactor/shunt PCB. Would track the electronics
   temperature, which heats from I^2*R in the shunt and cell interconnects, and cools
   slowly when the pack is idle.

3. **Bulk cell surface temperature** -- A single sensor touching cells in one area of
   the pack. Less likely to show the "warming during outdoor rest" behavior.

**A true per-cell or per-group temperature report would be expected as a min/max
pair** (Tmax and Tmin) across cell groups, similar to how 0x63A reports min/max cell
voltages. No such pair was found in the I^2*t scan -- none of the other variable bytes
show a matching positive correlation. The negatively-correlated bytes (0x372 B4/B5,
0x373 B1) decline as I^2*t accumulates and do not track temperature in the same way;
they may encode current limits or thermal headroom that the BMS reduces as the pack
warms.

### Hypothesis: Cell Temperatures Not Broadcast

Given that:
- No clear min/max cell voltage pair has been found in passively-broadcast frames
  (see `notes/plans/cell-voltage-decode.md`)
- No clear min/max cell temperature pair was found in the I^2*t scan
- 0x373 B3 shows thermal character but is likely an enclosure/board sensor, not a
  per-cell reading

It is likely that **detailed cell temperatures and cell-level voltages are only
available via active diagnostic reads (UDS / ISO 14229 or a proprietary A123 protocol
over CAN)**, not passively broadcast. The BMS presumably supports diagnostic sessions
that return cell-level data on request, but has not been queried in any existing log.

Investigating this would require:
- Identifying the BMS CAN address (likely 0x7B? or another ID in the 0x7xx range)
- Issuing UDS ReadDataByIdentifier (0x22) or a proprietary request
- Using `can_logger.py` in tandem with a CAN-transmitting tool or the OBD scanner

This is a separate investigation requiring active log capture with query injection.

### B3-Correlates Scan

**Script:** `artifacts/b3_correlates_scan.py` — scans all slowly-varying (ID, byte)
pairs in the current limiting test and correlates against 0x373 B3 as a thermal
reference. Filter: unique >= 3, change rate < 5 transitions/sec. 530 candidates.

**Monotonic counter false-positives discarded:** 0x625 B2, 0x649 B1, 0x4C7 B1,
0x4E9 B4, 0x375 B3 all show r=+0.95-0.97 with mono=100%. They are simply
counters/integrators that increase over time, same as B3. Not thermal.

#### 0x507 B0/B1 -- Additional Battery Temperature Candidates

BMS-dependent (disappears with LV connector). PT bus. 8.8 Hz. Full 8-byte message.

Sample at t=0.04s: `3C 3E 29 29 4C 55 01 00`

| Byte | Start (raw) | End (raw) | r vs B3 | x-40 encoding | Notes |
|------|------------|-----------|---------|---------------|-------|
| B0 | 0x3C = 60 | 65 | +0.943 | 20->25 degC | 8 unique values; 0x7F=127 sentinel (startup) |
| B1 | 0x3E = 62 | 68 | +0.912 | 22->28 degC | 10 unique values; 0x7F=127 sentinel (startup) |
| B2-B5 | constant | — | — | — | 0x29, 0x29, 0x4C, 0x55; fixed calibration or protocol |
| B6 | 1 (mostly) | — | — | — | Rarely 0 (5/15838 frames); possible fault flag |

At x-40 encoding all three sensors read within 3 degC at the start: B3=19, B0=20,
B1=22 degC. By end: B3=25, B0=25, B1=28 degC. The B1 reading is consistently 2-6
degC warmer than B0 and B3, suggesting B1 is positioned closer to a heat source.

0x7F = 127 appears only in the first few frames (BMS boot artifact) and during
occasional error conditions. It is a standard invalid/no-sensor sentinel and should
be filtered in all analysis.

**Confidence: medium.** All three sensors agree at x-40 encoding. No independent
calibration yet. Physical source (which sensors in the pack) unknown.

#### 0x430 B4/B5 -- Cell T_max / T_min

> **Superseded.** The `raw - 100` formula used in this section is wrong. Correct encoding is `raw * 0.5 - 40 degC` per EPRI decompile (confirmed 2026-03-28). Decoded temperature values below are invalid. See `powertrain-messages.md` 0x430 section and `vtrux.md` for current signal definitions. Correlation evidence and seasonal trend finding (Task V3) remain valid; only the decoded °C numbers are wrong.

BMS-dependent. PT bus. 20 Hz. 8-byte message.

| Byte | Start (raw) | End (raw) | r vs B3 | raw-100 encoding | Notes |
|------|------------|-----------|---------|-----------------|-------|
| B4 | 124 | 137-141 | +0.925 | 24->37-41 degC (WRONG — see above) | 18-19 unique values; wide range |
| B5 | 121 | 131-133 | +0.948 | 21->31-33 degC (WRONG — see above) | 13-14 unique values |

B1 and B3 in the same message have 256 unique values each — fast-changing data,
not temperature. B6=0 constant. B7: 10 unique values (126-142), slowly varying.

**Note on 0x480 B0:** r=-0.978 vs B3, declining 89->69 over 1809s. 5-byte, 10 Hz
PT bus message with a 4-bit nibble counter in B4 and all other bytes constant. Noted
as a possible current/power limit register. **No temperature confidence assigned.**
The current limiting test is specifically designed to hit power limits, and a limit
register would show large step-changes at limit events rather than smooth thermal
drift. Characterizing it requires examining the limit-hit events directly.

### Other Variable Bytes -- Role Unclear

The negatively-correlated bytes (0x372 B4/B5: r~-0.90; 0x373 B1: r=-0.887; 0x372
B2: r=-0.717) all decline as I^2*t accumulates. NOT temperature with the same
encoding. Candidates: current/power limit registers or SoC-correlated state bytes.

The variable bytes of 0x370/0x371/0x374 (r~-0.55 to -0.65) are weakly anti-correlated
and may carry per-section charge balance data or similar BMS state. Not temperature.

### Verification Task Results

#### Task V1 -- Temperature Candidate Graphs (complete)

Scripts: `artifacts/plot_batt_temps.py`
Outputs: `artifacts/batt_temps_evap_and_currentlimit.png`, `artifacts/batt_temps_exhaust_delta.png`

All 8 signals (0x373 B3, 0x506 B1/B2/B3, 0x507 B0/B1, 0x430 B4/B5) show plausible
battery temperature behaviour. 0x506 B1/B2/B3 cluster closely with 0x373 B3 and 0x507
B0/B1. All are some form of battery temperature -- exact sensor placement unknown.

**0x430 B4 and 0x507 B1 share a correlated spike** not present in any other signal.
No physical explanation identified; may be a shared sensor, common data path, or
transient noise. All other signals are spike-free and follow smooth thermal curves.

Encoding cross-check passes: 0x373/0x506/0x507 at raw-40 and 0x430 at raw-100 all
give temperatures in a physically consistent range across both logs.

#### Task V2 -- Exhaust-Side Temperature Delta (complete)

No clear thermal differential detected between B0 and B1 of 0x507 (or B4/B5 of
0x430) attributable to exhaust routing during generator operation. This does not rule
the effect out -- the logs are drive logs with vehicle airflow between the exhaust and
battery enclosure. Moving air would equalise the pack surface temperatures regardless
of which side the exhaust passes. The effect, if real, may only be detectable in a
stationary generator test with stagnant air around the pack.

#### Task V3 -- Seasonal Check Across Charge Logs (complete)

Script: `artifacts/seasonal_batt_temp.py` -- Output: `artifacts/seasonal_batt_temp.txt`

Seasonal trend confirmed across all available charge sessions. 0x430 B4/B5 is the
most consistent indicator, present even in early 2025 sessions where 0x373/0x507 were
filtered out by the capture hardware:

- Jan 2025 (Bel Inverter sessions): B4 ~+12degC, B5 ~+7degC
- Aug 2025 (full charge then fail): B4 +25->+39degC (summer heat soak; pack heats 14degC during charge)
- Jan 2026: B4 +3 to +22degC depending on prior soak time
- Feb 2026: B4 +13 to +28degC

**Note on 0x373 B3 in charge-mode logs:** Some charge sessions show B3 values (raw
36-39, i.e. -4 to -1degC at x-40) that are implausible for this climate, while 0x507
B0 in the same session reads +20degC. B3 may carry a different signal during charge
mode, or its content shifts when the BMS enters a charging state. Do not use B3 from
charge-mode logs for cross-session temperature comparison. 0x507 B0/B1 and 0x430
B4/B5 are more reliable across both drive and charge contexts.

### Charge Log PT Bus Reference

Discovered during seasonal scan (`seasonal_batt_temp.py`). Useful for any future
analysis that requires standard-frame BMS data from a charge session.

**Full PT bus (0x373, 0x507, 0x430 all present):**

| Session | Chunks | Date | Directory |
|---------|--------|------|-----------|
| `charge_M0` | 60 | 2026-01-16 19:41 | `logs/after-battery-swap-charges/` |
| `charge_9pm` | 1 | 2026-01-16 20:46 | `logs/after-battery-swap-charges/` |
| `another_M0` | 55 | 2026-01-23 12:53 | `logs/after-battery-swap-charges/` |
| `rainychargedebug` | 1 | 2026-02-16 21:22 | `logs/` |
| `rainychargedebug2` | 1 | 2026-02-16 22:44 | `logs/` |
| `rainychargedebug3` | 1 | 2026-02-16 22:45 | `logs/` |
| `rainychargedebug4` | 1 | 2026-02-16 23:32 | `logs/` |
| `chargingafterturningaroundandnotusingextension` | 1 | 2026-02-16 23:37 | `logs/` |
| `vtruxchargeafterevaplog (failed)` | 1 | 2026-02-26 09:21 | `logs/` |
| `vtruxchargeafterevaplogattempt2` | 1 | 2026-02-26 12:28 | `logs/` |

**Partial (0x430 present, 0x373/0x507 absent -- partial filter):**

| Session | Chunks | Date | Directory |
|---------|--------|------|-----------|
| `charge2_M1` | 1 | 2025-01-28 20:58 | `logs/other-logs/` |
| `full charge then fail` | 1 | 2025-08-22 15:45 | `logs/` |

**Extended-ID only (no standard BMS IDs -- captured with hardware filter on):**

All sessions from `logs/other-logs/` dated Jan-Feb 2025:
`chargelog_M0/M1/M2/M3/M5/M6/M7`, `charge2_M0/M2`, `charge3_M0`, `charge4_M0`,
`212charge_M1`. Also `chargelog_M4` (date unknown).

`212charge_M0` (2025-02-12): no BMS IDs at all (not even 0x430).

### Previous Notes Corrections

The note "raw 0x61=97 -> 57 degC after only 1-2 minutes of very low-power driveway
repositioning" referred to a byte that is NOT 0x373 B3 (which was 43 in that session,
not 97). That "impossible 97" byte has not been identified in the current scan and may
be from a different message or byte position than tested here.

The note "B3=43 is lower in a warm driving session than in a cold session -- opposite
of what temperature would show" is **resolved**: movingaroundindriveway.log was
captured Feb 16, 2026 (confirmed from BUSMASTER header). February outdoor cold-soak
gives 3 degC (raw 43) which is entirely consistent with temperature. The session was
not "warm" -- it was a cold February day.

### Artifacts

From `logs/after-battery-swap-charges/charge_M0_T0.log` (cold winter, DCDC cold-
start ~18.6 degC):
- `batt_0x370_B0_swapT0.csv` -- rises 56->59 over 262s (startup artifact: first frame = 89)
- `batt_0x370_B1/B4/B6_swapT0.csv` -- same range/trend as B0
- `batt_0x372_B0/B2/B4/B5_swapT0.csv` -- B0 rises 57->60 (multi-frame decay from 135 startup)
- `batt_0x373_B4_swapT0.csv` -- stabilizes at 46 after startup artifact; meaning unclear
- `batt_0x374_B0/B6_swapT0.csv` -- similar to 0x370

From `logs/vtruxcurrentlimitingtest.log` (Feb 25, 2026, winter drive, 1809s):
- `i2t_bms_correlation.py` -- I^2*t vs BMS bytes correlation script
- `i2t_bms_candidates.csv` -- full timeseries: I_centered, cum_i2t, all variable bytes

All messages show a first-frame startup artifact (elevated value on first broadcast
after boot), stabilizing within 2-5 frames.

---

## Phase 2B -- Battery Temperature Documentation (Complete)

Update reference docs and DBC with confirmed battery temperature signals from Phase 2A
and the V1/V3 verification tasks. Must be complete before Phase 2C.

**Step 2.5** -- Update `notes/powertrain-messages.md` BMS Message Cluster section.
Add encoding, observed ranges (seasonal and drive), confidence notes, and the
0x430 B4 / 0x507 B1 spike anomaly for each signal:
- 0x373 B3: raw-40=degC; BMS-dependent; anomalous values in charge-mode logs
- 0x506 B1/B2/B3: raw-40=degC; 3 sensors, identity unknown
- 0x507 B0/B1: raw-40=degC, sentinel 0x7F; B1 shares spike anomaly with 0x430 B4
- 0x430 B4/B5: raw-100=degC provisional, sentinel 0xFE; B4 shares spike with 0x507 B1;
  B5 is best seasonal indicator (present in filtered logs where others are absent)

**Step 2.6** -- Add confirmed battery temperature signals to `vtrux-powertrain.dbc`.

---

## Phase 2C -- Peltier Heater Investigation (Complete -- Inconclusive)

**Goal:** Check whether there is any CAN-observable evidence of Peltier heater/cooler
operation during cold charging. Existence and operability on either battery remain
unknown.

**Logs analyzed:** `artifacts/peltier_check.png` (generated by `peltier_check.py`)
- Cold warm-start: `charge_M0` T0-T59 (Jan 16 2026, 5.0h, pack pre-warmed by driving)
- Cold-soaked: `another_M0` T1-T55 (Jan 23 2026, 9.2h, cold-soaked from overnight)
- Warm reference: `full charge then fail` (Aug 22 2025, 2.0h)

**Temperature finding:** `another_M0` (cold-soaked) shows a gradual temperature rise
over ~9 hours that could be consistent with active heating, but could equally be
ambient warming of a cold-soaked pack. The warm-start `charge_M0` session shows
less rise, consistent with the pack already being near ambient. No strong
differentiating signature.

**DCDC 12V current (`0x18FFD6B3 B2-B3`, x0.05 A, LE unsigned):** Present in all
three sessions. Cold-soaked session starts ~9.6A and decays to ~4.5A over the first
few hours; warm session stays in the 4.6-7A range throughout. However, this decay
pattern is consistent with the DCDC topping off the 12V battery at session start
then backing off -- it does not align temporally with the pack temperature rise in
a way that implicates a Peltier load specifically. **Signal identification for B2-B3
as "12V output current" also remains medium-confidence and unconfirmed.**

**Conclusion:** Inconclusive on both fronts:
- No CAN-observable evidence for or against Peltier presence/operation.
- DCDC 12V current signal (`0x18FFD6B3 B2-B3`) identification is not confirmed;
  the decay pattern seen is consistent with 12V battery charging but the signal
  could represent something else. Do not treat as confirmed until cross-referenced
  against a known 12V load event.

**Not attempted:** Bit-level comparison of 0x596/0x644 between cold and warm
sessions (potential Peltier enable/status flag). Could be revisited if a
confirming 12V signal is found or if hardware information clarifies Peltier presence.

---

## Phase 3 -- Inverter + Motor Temperatures

### 0x619 Initial Observations (Mar 2026, inconclusive)

**Log:** `vtruxevapdrivelog4.log`, PT bus (bus 2). 10 Hz, 8 bytes, 14627 frames.

**Message structure:**

| Byte | Range | Unique | Notes |
|------|-------|--------|-------|
| B0 | 244-254 | 8 | Slow staircase; likely 1-count/unit temp signal |
| B1 | 0 | 1 | Always zero |
| B2 | 93-111 | 17 | Slowly varying |
| B3 | 0 | 1 | Always zero |
| B4 | 40-92 | 53 | Fast-varying, tracks load; initially thought thermal |
| B5 | 138-171 | 34 | Slowly varying |
| B6 | 0/64/128/192 | 4 | 2-bit cycling counter in bits 6-7 |
| B7 | 128 | 1 | Always 0x80 |

**Source attribution:** Source ECU unattributed. **Not confirmed -- do not
attribute 0x619 to any specific device without targeted data.**

**PE pump speed** (0x18FF0320 B5) runs at B5=12 throughout the drive; B4 variation
does not correlate with pump speed changes. The dips in B4 are load-driven, not
cooling-driven.

**Next step:** Capture a targeted log designed to produce useful thermal excursions --
e.g. stationary high-load run from cold, then cooldown -- so that B4 and the other
variable bytes can be decoded against known thermal conditions. Until then, 0x619 byte
roles remain unattributed.

**Artifacts:** `619_vs_torques.py/png`, `619_all_bytes.png`

---

### Targeted Overheat Test Log — vtruxunpluggedpumpoverheattest.log

This is the purpose-built thermal excursion log called for above. The PE coolant
pump CAN connector was physically unplugged before key-on, so the DCDC (and both
inverters, which share the PE glycol coolant loop) operated with no active cooling for
the duration of key-on cycle 1. The pump was reconnected at the start of key-on
cycle 2, restoring cooling. No dash fault light appeared during the test.

**Cooling architecture note:** The PE glycol loop cools the charger, DCDC, and both
inverters (generator and traction). The two motors (generator motor and drivetrain/traction
motor) are oil-cooled — each has its own dedicated oil pump, with both pumps sharing
a common oil reservoir. Unplugging the PE pump stresses the inverters and charger/DCDC
but does NOT affect the motor winding temperatures (those are on the oil circuit).

This log is the primary candidate for Phase 3A thermal candidate discovery —
the thermal excursion is far larger than in any normal drive log, making
temperature-like signals easy to distinguish from counters and status bytes.

#### Expected Event Sequence

| Event | Observable |
|-------|-----------|
| Key-on cycle 1 — pump CAN disconnected | 0x18FF0320 absent from log start (or disappears within first few seconds) |
| Cycle 1 running — no cooling | 0x18FFD6B3 B6-B7 (DCDC temp) rises monotonically. Any inverter temperature bytes should also rise monotonically. |
| Key-off — end of cycle 1 | PT bus traffic stops. Temperatures may tick slightly higher or plateau before CAN drops (thermal inertia). |
| Key-on cycle 2 — pump reconnected at beginning | 0x18FF0320 reappears immediately. VCU issues soft-start ramp via 0x18EF2000 B3 (0->1->2->...->11, step held ~1s each, ~12-14s total). 0x18FF0320 B5 feedback begins rising after ~7s lag. |
| Pump cooling active | DCDC temperature levels off then begins falling. ~15s lag expected between pump-on and temperature response (Phase 1B finding). Inverter temperatures follow with similar or longer lag. |
| Pump at full speed | 0x18EF2000 B3 = 11; B5 feedback at maximum. Temperature decline rate accelerates. |

#### Key Signals to Extract First

- 0x18FF0320 B5 (pump speed feedback) — gives exact pump-reconnect and ramp timestamps
- 0x18EF2000 B3 (VCU pump command) — confirms the ramp sequence
- 0x18FFD6B3 B6-B7 (DCDC temperature, LE signed x0.1 degC) — the anchor thermal signal;
  should show the full heating arc and the cooling recovery

Any byte across all PT bus IDs that shows a monotonic rise during cycle 1 and
a plateau/decline after pump reconnect in cycle 2 is a thermal signal. The DCDC
temperature arc is the reference to compare against.

---

### Overheat Test Thermal Scan — Findings (Mar 2026)

**Log:** `vtruxunpluggedpumpoverheattest.log` — 705s, 3-bus capture. PT bus = Bus 3 (has 0x051).

**Reference signal:** 0x18FFD6B3 B6-B7 (DCDC temp, ×0.1°C) — 17.2→24.0°C arc. Key events:
- Key-off gap: t=411.7–471.2s (59.5s)
- Pump reconnect (0x18FF0320 first frame): t=471.3s
- Pump at full speed (B5 feedback saturated): t≈660s

**Method:** Windowed Pearson r correlation against DCDC temp (window t=100–411s, stable monotonic ramp before key-off). Per-byte and LE/BE uint16 pair tests. 274 candidates above |r|≥0.35.

**Artifacts:** `overheat_thermal_scan.py`, `overheat_thermal_candidates.txt`, `overheat_analyze_0x483.txt`, `overheat_0x483_B0/B1/B2.csv`, `overheat_0x483_0x484_raw.png`, `overheat_0x483_combined.png`, `overheat_0x483_bitpack.png`

#### 0x483 — Temperature Signal with Derating Zone

0.9 Hz, 8 bytes, identical timestamps to 0x484 (same module). Absent from stationary dropout test — only present during motor operation.

**B0 — temperature (1°C resolution):**
- Encoding: raw − 100 = °C (confirmed by cold-soak start: raw=116 → 16°C)
- Range in overheat test: 116–181 (16–81°C)
- Shape: smooth monotonic rise throughout the entire 705s log
- **Does not plateau or drop when pump reconnects or at full pump speed**
- Source/location: unknown

**B1 + B2 bit0 — temperature (fine resolution, 9-bit):**
- B2 bit0 is the carry bit for B1: flips 0→1 when B1 overflows near 255 (observed at t=90.88s when B1=253). After the flip it stays 1 for the rest of the log.
- 9-bit value = (B2 bit0) << 8 | B1; nearly monotonic (only 1 downward transition in 631 samples)
- r_win = 0.979 vs DCDC temp. Same thermal source as B0, higher resolution.
- Scale not yet determined. Raw range 181–493 over the same 16→81°C arc as B0.
- **Same pump-non-response as B0:** no plateau or drop at pump reconnect or full speed.

**B2 — packed status byte:**

| Bits | Role | Values |
|------|------|--------|
| 7–4 (upper nibble) | Thermal derating zone | 3–6 (3=low, 5=normal, 6=high) |
| 3 | Always 0 | — |
| 2 | Always 1 | — |
| 1 | Always 0 | — |
| 0 | Carry from B1 (9th bit of temperature) | 0 before first B1 overflow, 1 after |

Zone behavior: stays at 5 through cycle 1; briefly 6 near end of no-cooling phase (t≈394s); oscillates between 3–5 during pump-at-full-speed period (t≈519–677s), indicating the system is crossing a thermal threshold repeatedly as it cools.

**Other bytes:** B4/B5 near-constant (operational state); B6 is a 16-step cycling counter; B7 is the upper byte of that counter (B6–B7 together = LE uint16 counter, decrementing by 16).

#### 0x484 — Candidate Signal, Role Unconfirmed

0.9 Hz, 8 bytes, identical timestamps to 0x483 (same module). r_win = 0.809 vs DCDC temp.

- B0: range 108–180, 17 unique values, steps of ~4 counts. Rises through cycle 1. V-shaped drop during key-off gap (drops ~56 counts, recovers immediately on key-on cycle 2). Continues rising in cycle 2.
- B1–B7: mostly constant (B1=18, B2=20, B3=128, B4=36 fixed; B5 and B6 near-constant with rare transitions).
- The V-notch during key-off distinguishes this from the 0x483 temperatures (which plateau at key-off but don't drop sharply). Role not yet confirmed — possible 12V bus voltage (needs comparison against 0x18FFD6B3 B0-B1 DCDC LV output).

---

### Torque-Correlated Thermal Scan — Findings (Mar 2026)

**Goal:** Find IGBT-type temperature signals that correlate with motor torque (with thermal delay)
and drop when the PE pump runs at full speed. Hypothesis: IGBT temps are "wavy" (fast thermal
response to torque) vs the smooth DCDC arc. Expected: r_win(smoothed |torque|) >= 0.5 AND
pump_delta < 0.

**Script:** `torque_thermal_scan.py` — Output: `torque_thermal_candidates.txt`
**Reference:** smoothed |0x5A2 B4-B5| (drive torque, tau=15/30/60s)

**Key result: No IGBT temperature signals found.** All strong candidates were false positives:
- 0x646 B6 (r=+0.980 drive_torque, pump_delta=-112.5): ELIMINATED — cyclic counter wrapping
  at 255 (increments 1 count per ~2s; the apparent "drop" in cycle 2 is a wrap artifact)
- 0x619 B2 (r=+0.782 drive_torque, pump_delta=-109): ELIMINATED — discrete fault flag,
  not a temperature. Drops to 0 within 0.4 seconds of pump reconnect; physically impossible for
  thermal cooling. Values: {0, 46, 59, 84, 99, 109}. Saturates at 109 during cycle 1, clears
  immediately when pump command is detected. Likely a thermal fault accumulator or derating mode
  indicator that resets when pump is restored.
- All other pump_delta negatives were: battery current decreasing (expected), BMS limit bytes, and
  small-delta miscellaneous signals with no thermal character.

**Additional observations:**
- 0x619 B5 (r=-0.842 drive_torque, pump_delta=+9): slowly declines ~225->127 as load accumulates.
  Negative torque correlation + no pump recovery = likely a thermal headroom / current limit
  register that the inverter reduces as IGBT temps rise internally. Does NOT broadcast the IGBT
  temps directly and does NOT recover in the cycle 2 window.
- 0x410 B3 and 0x411 B0 (strong DCDC-scan candidates): both exhibit startup artifacts only
  (drop on key-on, recover within seconds to a stable operating value). Not thermal.
- 0x0870A047 B1: rises 58->62 (4 counts) over cycle 1, resets on key-on. Not thermal.
- DCDC temp (0x18FFD6B3 B6-7): rose only 19.1->21.7 degC during cycle 1 (7 degC over 320s).
  Small rise suggests the PE coolant loop was only mildly stressed during this test.

**Conclusion: IGBT temperature signals are NOT passively broadcast on the PT bus CAN.**
The inverter controllers track IGBT temperatures internally and surface only fault flags
(0x619 B2) and current limits (0x619 B5), not raw temperature values. This is consistent
with Phase 3C hypothesis. 0x483 B0 is a temperature on a separate (non-PE-loop) thermal path
whose source is not yet confirmed.

---

### Drivetrain Motor Overheat Test -- vtruxdrivetrainoverheattest.log (Mar 2026)

**Purpose:** Deliberately overheat the Remy HVH250-115D drivetrain motor by
disconnecting its cooling circuit (drivetrain oil pump) while driving. This is a
distinct test from `vtruxunpluggedpumpoverheattest.log`, which stressed the PE glycol
loop (charger/DCDC/generator inverter cooling). This test targets the **traction motor**
thermal path specifically.

**Motor:** Remy HVH250-115D. **Inverters:** Dana TM4 CO150 (spec sheet in `notes/`
folder; general spec only, no pinouts or CAN protocol documentation).

Motor PDFs in `notes/Remy-Motor/`:
- `HVH250_MotorManual20110408.pdf` -- motor manual
- `Remy_Hybrid_Application_Manual_Rev_2-TRB-9-25-2013.pdf` -- application manual
- `remy-pds---hvh250-115-sheet-euro-pr-3-16_3.pdf` -- product data sheet

#### Observed Events (from sidecar .txt)

| Time | Event |
|------|-------|
| 8:19 PM | Drivetrain oil pump unplugged |
| ~8:45 PM | Truck enters drivetrain torque limit (thermal cutback/limp mode -- NOT a complete shutdown). Radiator fan had been running for several minutes already by this point. |
| ~8:50 PM | Pump reconnected. Torque limit releases (motor current/torque comes back). Radiator fan fades out after a few minutes. |

#### Key Observations and Implications

1. **Thermal cutback, not shutdown:** The controller reduced maximum torque rather than
   cutting power entirely. This is characteristic of a measured temperature-based derate,
   not a binary fault trip. There is likely a continuous temperature signal on the bus --
   the controller must be reading something to decide how much to derate.

2. **Radiator fan activation:** The radiator fan ran *before* the torque limit was reached
   and *in response to* the rising motor temperature -- the controller commanded the fan
   when the motor got hot. This means:
   - There is a control loop using motor temperature (or a proxy) to drive fan speed.
   - Fan speed or fan enable on the GMLAN bus could be a second indicator of when the
     controller recognized the motor as thermally stressed.
   - The fan running "for a few minutes" before the torque limit gives us a temperature
     threshold to bracket: fan-on < cutback threshold.

3. **Recovery:** Fan and torque limit both respond to pump reconnect within minutes.
   Consistent with the motor winding cooling down once oil circulation resumes.

#### Expected Thermal Profile of Drivetrain Motor Temperature Signal

If a motor temperature signal exists on the bus, it should show:

- **Slow monotonic rise** from pump-disconnect to torque-limit onset, shaped by the
  I^2*t of the drive torque feedback (0x5A2 B4-B5). Rise rate steepens with high torque,
  flattens with low torque.
- **Plateau or inflection** at torque-limit onset (~8:45). Derate reduces motor current,
  which reduces heating rate, causing temperature to level off near peak.
- **Sharp decrease** after pump reconnect (~8:50). Oil circulation resumes and winding
  cools. Decrease should be faster than the rise.
- **Temperature range:** Remy HVH250-115D thermal protection thresholds TBD from PDFs.
  Typical winding temp for cutback onset is in the 150-180 degC range for this motor
  family -- confirm from motor manual.

#### Motor Temperature Sensor Architecture -- Find the Signal First

The Remy HVH250-115D likely has a single thermistor embedded in the stator winding
(confirm count from the HVH250 motor manual). Beyond that we do not know the signal
path: the thermistor could be read by the Dana TM4 CO150 inverter and broadcast as a
CAN message, or it could be wired directly to the VCM which then may or may not
broadcast it. The Dana TM4 spec sheet does not document the CAN protocol, so we cannot
determine the architecture from documentation alone.

**Approach: find the signal first without assuming its source, then attribute it.**
Once a temperature candidate is confirmed, the VCM disconnect logs (which show which
IDs drop when the VCM loses power) can help determine whether the signal originates
from the VCM or from one of the inverters.

#### Investigation Steps

**STOP after each numbered step and confirm the finding before proceeding to the next.**

**Step 1 -- Check motor datasheet for thermistor count. (COMPLETE)**

Findings from Remy HVH250-115D motor manual and application manual:
- **1 NTC thermistor per motor**, embedded in the stator winding (end-turn region).
  Wiring diagram (motor manual p.23) shows a single thermistor pair on LV connector
  pins G+H, routed via the LV cable to the inverter.
- **Signal path per datasheet:** the thermistor wires are designed to connect to the
  inverter (Dana TM4 CO150), not directly to the VCM. This is what we expect -- but
  we have not confirmed the actual wiring in this vehicle. If a CAN temperature signal
  is found, attribute its source via VCM disconnect logs (Step 3), not from this
  datasheet alone.
- **Thermal derate thresholds** (application manual p.20): derate begins at 160 degC,
  ramps linearly to 0A at 180 degC. Stator end-turn continuous limit is 160 degC.
- **Thermistor resistance at key temperatures** (motor manual p.8):
  25 degC = 30,000 ohms; 160 degC ~= 500 ohms; 175 degC ~= 310 ohms.
- **Implication:** expect exactly one temperature value per motor in the CAN data.
  At cutback onset (~8:45 PM) the winding was likely in the 160-180 degC range.

**Step 2 -- Establish time base and confirm torque cutback is visible. (COMPLETE)**

Log header: start time 20:12:27 on 2026-03-11 (8:12:27 PM). Duration: 2637.95s (~44 min).

| Event | Wall clock | Log offset |
|-------|-----------|-----------|
| Log start | 8:12:27 PM | 0 s |
| Pump unplugged | 8:19 PM | ~393 s |
| Torque cutback onset | ~8:45 PM | ~1953 s |
| Pump reconnected | ~8:50 PM | ~2253 s |

Torque cutback confirmed visible: 0x5A2 B2-B3 (motor RPM) and B4-B5 (torque
feedback) both clearly collapse at t=1953s despite full throttle input from
0x592 B2-B3. Context: t=1600-1950s was hill driving under heavy load which
drove the motor to thermal cutback.

Plots saved to artifacts/: step2_torque_throttle.png (full log),
step2_cutback_zoom.png (t=1700-2400s zoomed).

**Step 3 -- Scan for drivetrain motor temperature candidate. (COMPLETE 2026-03-12)**

**Signal confirmed: 0x06000002 B5/B6, 10-bit Intel LE at startbit 46, 2.0 deg C/count.**

Method: windowed Pearson r (t=1500-2550s, post-generator-shutdown) against all PT bus
per-byte and adjacent LE/BE uint16 pairs. 640 candidates tested. 0x06000002 B6 was
identified as the coarse motor temperature (monotonic arc 0-20, peaks at cutback),
then bit-level analysis revealed the packed encoding in B5/B6.

**Encoding details (corrected -- original 9-bit/0.5 deg C formulation was revised to
produce a valid DBC definition):**
- `signal = (B6<<2) | (B5>>6)` -- 10-bit Intel LE, startbit 46, 2.0 deg C/count
- B5[7:6] = 2 LSBs of the signal (bits 1:0 in the 10-bit word)
- B5[5:2] = constant padding (bit5=1, bits4:2=0)
- B5[1:0] = ADC jitter (noise, not data -- verified 50/50 +1/-1 transitions; discard)
- B6 = bits [9:2] of the 10-bit word
- B6 range: 0-20 across this log; 10-bit raw range: 0-82.

**Scale confirmation:** 10-bit signal peaks raw=82 at torque cutback event (t=1953s).
Remy HVH250-115D derate starts at 160 deg C (motor manual p.20). 82 x 2.0 = 164 deg C.
Raw=0 at inverter init (not a calibrated zero). Cold-soak start ~7 raw (~14 deg C).

Artifacts: `thermal_corr_16bit.py/txt`, `analyze_b5b6_bits.py`, `b5b6_bit_analysis.png`,
`plot_motor_temp_9bit.py`, `motor_temp_9bit.png`, `verify_b5_encoding.py`.
(Note: artifact filenames retain "9bit" from the original analysis; the confirmed encoding
is 10-bit at 2.0 deg C/count as described above.)

**Full-bus scan for other drivetrain-temperature-correlated signals (COMPLETE 2026-03-12 -- no additional candidates):**

`drivetrain_thermal_scan.py` ran a 3-method correlation sweep (full-window r, 200s
sliding window, bucket-to-bucket delta) against the decoded motor temperature reference
over t=1500s to end of log, sorted by full-window r. Top scorers ruled out:

| Signal | r_full | Reason ruled out |
|--------|--------|-----------------|
| 0x63F B3 | 0.950 | Erratic and jumpy before t=1500s (generator active); not thermally shaped outside the post-gen-shutdown window. Generator-influenced, not a temperature sensor. |
| 0x18FFD6B3 B3 | 0.889 | Smooth rise from t=0, PE water-loop shape (slow rise, plateaus as pump compensates). DCDC is PE-cooled -- not motor winding. |
| 0x484 B0 | 0.565 | Same PE-loop plateau profile. |
| 0x0870A047 B1 | 0.604 | Smooth monotonic rise, 7-count range. PE-cooled component (SA=0x47 unattributed). |
| 0x483 B6:7 LE | 0.594 | PE-loop plateau shape. |

The pattern across all high-scoring candidates is a slow rise that levels off as the
PE pump compensates -- characteristic of water-cooled power electronics, not motor
windings. No signal with the winding-temperature shape (fast rise under load, fast
drop on cooling) was found other than 0x06000002 B5/B6.

**0x06000002 B5/B6 is the only motor winding temperature signal on the PT bus.**

Artifacts: `drivetrain_thermal_scan.py/txt`, `plot_drivetrain_thermal_candidates.py`,
`drivetrain_thermal_candidates.png`.

**Step 4 -- Scan GMLAN bus for radiator fan signal. (COMPLETE)**

No fan control signal found on GMLAN. The radiator fan observed running before the torque cutback is NOT visible on the GM buses. It is likely controlled via a direct VCM PWM/relay output (not a CAN message) or by the inverter directly. The fan on-ramp timestamp cannot be determined from the CAN log.

**Step 5 -- Find generator motor temperature signal. (IN PROGRESS -- overheat test scan 2026-03-12)**

The generator motor is also a Remy HVH250-115D on the same model inverter. Once the
drivetrain motor temperature format is confirmed in Step 3, look for an analogous
message on the generator inverter. This log started in evap purge mode so the
generator was running during the early portion -- generator motor temperature should
be visible in this same log without needing a separate capture. Candidates: 0x483 /
0x484 (flagged from the PE overheat test; 0x483 B0 rose monotonically without
responding to the PE glycol pump, consistent with a thermal source on a different
cooling circuit -- possibly the motor oil circuit).

**Overheat test correlation scan (2026-03-12):**

Ran `gen_motor_temp_corr.py`: Pearson r sweep on PT bus, t>=800s (after 0x483 B0
overflow), reference = 0x483 B0.

- 0x0870A047 B3: r=+0.964 -- appears nearly flat in time-series plot; high r is likely
  a correlation artifact from both signals being monotone over the window. Not a useful
  temperature signal.
- 0x595 B2: r=+0.790 -- NOT a motor temperature candidate. Time-series shows it rises
  from ambient (~19) to ~93 during the early load ramp (before pump unplug), peaks,
  then slowly declines with no clear response to oil pump events. Shape is consistent
  with PE water/glycol cooling loop temperature (possibly generator-side); correlation
  with 0x483 B0 was coincidental (both are thermal signals with a broadly similar arc).
  Moved to signal summary table as a separate candidate. See `595_vs_483_comparison.png`.

Artifacts: `gen_motor_temp_corr.txt`, `gen_motor_temp_candidates2.png`.

**0x483 and 0x484 carry-bit analysis (2026-03-12):**

Both messages show one early B0 overflow: 0x483 at t=699s, 0x484 at t=734s. Ran full
carry-bit search (`find_483_484_msb.py`) to find the MSB that extends B0 past 255.

*0x484 -- B1 bit0 is a clean carry:*
All B1 values before the overflow are even (bit0=0); all after are odd (bit0=1). Clean,
intentional carry. B1[7:1] contains a rapidly oscillating counter/status field unrelated
to temperature. 9-bit encoding: `(B1[bit0]<<8)|B0`, range 128-364 over this test.

*0x483 -- no clean carry; B1 bit1 gives the most plausible shape:*
At the B0 overflow, B1 stepped from 37 (0b00100101) to 42 (0b00101010) -- a jump of +5,
not +1. B1 is a separate slowly-changing structured field, not a dedicated carry byte.
However, B1 bit1 happens to flip 0->1 at exactly the overflow moment (37: bit1=0;
42: bit1=1), giving `(B1[bit1]<<8)|B0` a plausible monotonic shape with range 126-320
and 0 overflows in the full log. This alignment may be coincidence. The bit position
difference (bit1 for 0x483 vs bit0 for 0x484) is inconsistent with parallel messages
from identical hardware, suggesting the two messages have different internal layouts.

*Role hypothesis -- possible inverter temperatures (unconfirmed, scale unconfirmed):*
Both signals rise gradually over the overheat test, including during periods when both
the drivetrain oil pump and the PE glycol pump were active. Since inverters are
water-cooled (PE loop), both generator and drivetrain inverter temperatures would rise
together regardless of which oil pump is cut. The similar thermal profiles of 0x483 and
0x484 are consistent with inverter temperatures. Not consistent with motor winding
temperatures, which should diverge when only one oil pump is cut.

Cross-validation against logs with only one motor active is still needed to confirm role:
- Generator-only: `logs/generator on then off.log`
- Drive-only: any drive log without generator operation

*Gate: Confirm role and encoding before closing this investigation.*

**Generator motor overheat test — new logs (2026-03-18):**

Two new logs cover a deliberate generator motor overheat event by disconnecting the
generator oil pump.

**Secondary log (captured first): `logs/vtruxgeneratorpumpunplug.log`**
- Generator and generator oil pump both running normally at log start
- A few minutes before the end of the log, the generator oil pump was unplugged
- This log establishes the normal operating temperature range and captures the transition
  from pumped to unpumped — use it to verify signal continuity once candidates are found

**Primary log (the overheat test): `logs/vtruxgeneratoroverheattest.log`**
- Recorded after the pumpunplug log; oil pump was already unplugged when this log started
- Generator had been idling in the driveway for a while before logging; temperature does
  NOT start at ambient — it was already elevated when the log began
- Overheat manifested around **10:57 PM** (wall clock; log-relative timestamp TBD from survey)
- Symptom: generator engine RPM spiked very high — the VCU was thermally limiting generator
  torque, so the engine saw less load and its RPM rose
- Use 0x63C B6 (confirmed generator RPM) to precisely locate the overheat peak in the log

**Target signal shape:** starts elevated (pre-warmed), rises further to a peak at or near the
RPM spike (~10:57 PM), then declines after the generator oil pump was plugged back in and the
generator was left running to circulate oil. Both flanks should be visible.

**Search approach:**
- Look for signals that peak at the RPM spike and are lower on both sides (not monotone)
- 0x483 B0/B1 remain highest-priority candidates: in `vtruxunpluggedpumpoverheattest.log`
  (PE glycol loop stressed, motors unaffected), 0x483 B0 rose without responding to PE pump
  restoration — consistent with it being on the generator motor oil circuit rather than the
  PE glycol loop
- Disqualify: counters, binary flags, anything that drops instantly on pump reconnect

**Graphing plan (for candidate review plots):** Each candidate temperature plot should
include the following reference signals on a multi-axis figure:
- Generator RPM (0x63C B6; RPM = 16×B6 − 96)
- Generator torque command (0x051 B1-B2 LE uint16, centered at 32768)
- Generator power — direct (0x598 B2-B3 LE uint16, centered at 32768; generator current channel)
- Generator power — computed (RPM × torque command, scaled so it normally tracks the direct
  power signal)
- Drivetrain motor temperature (0x06000002 B5/B6, 10-bit LE at startbit 46, ×2.0°C/count)

**0x63C B6 RPM overflow and GMLAN reference (2026-03-19):**

During the overheat test, 0x63C B6 overflows three times (B6 wraps 255->0 with no recovery
carry bit). True peak engine RPM during the long overflow window was ~4686 RPM confirmed via
`Engine_Speed` on the OBD bus. No carry bit was found in any adjacent byte of 0x63C or in
nearby PT messages (0x63D, 0x63F, B5/B7 LSBs all unchanged across overflow windows). Via
likely intended engine RPM to stay below ~4000 RPM during normal torque-limited generator
operation; the overflow is only reachable under abnormal thermal conditions where the VCU
reduces generator torque and the engine runs away.

**For this investigation, use `Engine_Speed` (OBD bus) rather than 0x63C B6 as the RPM
reference.** The PT bus signal is accurate under normal conditions but saturates exactly where
the thermal event of interest occurs.

**Correlation scans on `vtruxgeneratoroverheattest.log` (2026-03-19):**

Two windowed Pearson r sweeps were run to search for the generator motor temperature signal.
Neither found the target signal; both produced noteworthy incidental findings.

**Scan 1 -- 0x484 B0 as reference (full log, t>=800s):**

0x484 B0 (1 Hz, range 20-255 raw, rises from cold-soak ambient) used as the correlation
reference. 57 candidates passed filters (unique>=4, range>=3, mean-abs-change<=15, n>=20).
Top results:

| Rank | ID | Byte | r | Notes |
|------|----|------|---|-------|
| 1 | 0x483 | B0 | +0.911 | Monotonically rising; does not respond to PE pump — consistent with generator oil circuit |
| 2 | 0x625 | B2 | +0.777 | 1 Hz; range 41-68 (28 unique); slowly varying thermal readout |
| 3 | 0x06000001 | B1 | +0.756 | 20 Hz; range 220-252 |

Script: `artifacts/gen_overheat_corr_484.py`. Full ranking: `artifacts/gen_overheat_corr_484.txt`.
Plot of all candidates + reference signals: `artifacts/gen_overheat_corr_484_plot.png`.

**Scan 2 -- 0x595 B2 as reference (windowed, t=1700-2300s -- pump-off overheat phase):**

0x595 B2 (PE glycol loop temp candidate) used as reference in the overheat window only.
Negative correlators are valid -- signal could encode resistance or voltage inversely with
temperature. Top results:

| Rank | ID | Byte | r | Notes |
|------|----|------|---|-------|
| 1 | 0x594 | B5 | -0.768 | 20 Hz; range 0-255 |
| 2 | 0x0870A047 | B1 | -0.669 | 10 Hz; range 84-90 (7 unique); see below |
| 3 | 0x625 | B2 | +0.620 | Same byte as Scan 1 rank 2 |

Script: `artifacts/gen_overheat_corr_595b2.py`. Full ranking: `artifacts/gen_overheat_corr_595b2.txt`.
Plot of top candidates: `artifacts/595b2_candidates.png`.

**Incidental findings -- signals of interest that are NOT the generator motor temperature:**

*0x625 B2 -- slow thermal readout, identity unknown:*
- 1 Hz, 8-byte message; B0=1 and B1=121 always constant (J1939-style fixed header)
- B2=41-68 (28 unique, 8.0 std dev), slowly varying over the full test; positive correlation
  with both reference signals
- B4-B5 are rapidly switching bitfields (unrelated to temperature)
- Appears in both scans. Source address and role unknown. Not the generator motor temperature:
  1 Hz is too slow for motor winding thermal feedback, and the raw range (41-68) does not
  match the expected encoding for a winding temperature near 100+ degC.

*0x0870A047 -- multi-channel temperature report, source 0x47:*
- Extended 29-bit J1939 ID; 10 Hz; 4 bytes; no rolling counter, no checksum
- B0 = 0 always
- B1 = 78-91 (mean 86.4), B2 = 91-100 (mean 96.5), B3 = 74-89 (mean 82.4)
- All three bytes slowly varying in the 74-100 range -- consistent with multiple coolant
  temperature sensors in the same thermal circuit
- B1 negatively correlated with glycol temp rise (r=-0.669), B2 barely correlated (+0.208),
  B3 not scanned but similar range -- likely measuring different points in the same loop
  (e.g., inlet vs outlet temperatures with different transient response)
- Cold-start values (log open): B1=78, B2=96, B3=77 -- vehicle already at operating temp
- Source address 0x47 not yet attributed to any known module
- NOT the generator motor temperature: signals in this message do not peak at the RPM spike
  and are inconsistent with winding-side thermal dynamics (winding temps would be in a
  different range and have faster time constant under hard load)

**Conclusion -- generator motor temperature signal not found:**

Neither correlation scan identified the generator motor temperature. The signal should peak
at the 0x63C B6 RPM overflow event, start elevated (pre-warmed at log start), and decline
after the oil pump is restored. No candidate matching this shape was found in either scan.
The target signal may be:
- Encoded as a 16-bit word (both scans operated on individual bytes; a LE/BE uint16 carrying
  a fine-resolution winding temp could be missed if neither constituent byte passes the
  individual-byte correlation threshold)
- On an extended-ID message that was filtered out by the KNOWN_EXT_SRCS exclusion list
- Not present in these logs at all if the generator inverter does not broadcast winding
  temperature on the PT bus

**Scan 3 -- 0x484 9-bit as reference, with LE/BE uint16 pair scan added (2026-03-19):**

Re-ran with reference upgraded to 0x484 9-bit `(B1[0]<<8)|B0` and added LE uint16 and BE
uint16 pair accumulators alongside per-byte. 176 total candidates (57 byte, 58 LE16, 61 BE16).

Top new finding: **0x483 B6-B7 LE, r=+0.989, range 3411-4115, 1 Hz** -- completely invisible
to per-byte scans due to B7 stepping between 13-16 (causing 256-count jumps that collapse
per-byte r). Initial hypothesis: Kelvin*10 encoding (3411=68.0C, 4115=138.4C), consistent
with a motor winding starting pre-warmed and climbing toward the Remy derate threshold.

**Hypothesis disproved on visual inspection (2026-03-19):** Plotted 0x483 B6-B7 LE and
0x484 B6-B7 LE alongside all other signals in both the generator overheat log and the
drivetrain overheat log. Findings:

- **0x483 B6-B7 LE**: behaves similarly in both logs despite their pump situations being
  completely different (generator oil pump disconnected vs. not). Does not respond to the
  specific overheat event in either log. Not a motor winding temperature.

- **0x484 B6-B7 LE**: noisy/erratic across both logs. Not a temperature signal.

- **0x483 and 0x484 overall**: both likely carry water-cooled (glycol loop) temperatures
  of unknown source. The slowly-rising B0/9-bit signals in both messages track similarly
  across different thermal stress scenarios, consistent with a shared glycol loop rather
  than individual motor oil circuits. Source module and exact signal role remain unknown.

**Conclusion -- generator motor temperature signal not found (2026-03-19):**

After per-byte correlation scans, windowed correlation scans, LE/BE uint16 pair scans,
and visual inspection of both the generator and drivetrain overheat logs, no signal
matching the expected generator motor winding temperature shape has been identified.

**Key finding from this investigation:** The Vtrux does NOT shut down abruptly when
the drivetrain or generator motors overheat. Both motors derate gently -- the inverter
itself limits delivered torque without the VCU reducing its torque command. This is
visible as a divergence between |torque_cmd|*RPM (which stays high, as the VCU command
does not drop) and actual generator current (which falls). The derating is inverter-side,
not VCU-side. The same mechanism likely applies to the drivetrain motor inverter.

**Proposed follow-up test:** Run a longer PE water pump unplug test where the pump is
disabled and the truck is actually driven (not just idling in the driveway) for long
enough to trigger PE glycol overheat logic. The previous `vtruxunpluggedpumpoverheattest.log`
was insufficient -- no overheat logic fired because the PE loop did not get hot enough
from driveway idling alone. A sustained driving load with no coolant flow should produce
a cleaner thermal event with more signal candidates responding.

Next approach: run the candidate discovery plan (Phases 3A-3B) against `vtruxevapdrivelog4.log`
where generator was running under controlled conditions, and apply the thermal time-constant
classification to distinguish inverter-side from winding-side signals.

**EPRI 0x479 thermal signals — revisit (2026-03-29):**

The EPRI decompile identifies `0x479` (`EPRI_MCU_Thermal1_0479`) as the GENE MCU thermal
status message with three signals (confirmed byte layout from Ghidra decompile, DLC=4):

| Byte | Signal | Scale | Meaning |
|------|--------|-------|---------|
| B0 | `GENE_DrvCoolFlowReq_pct` | raw × 0.78125 % | Inverter (drive) cooling flow request — PE glycol loop |
| B1 | `GENE_MotCoolFlowReq_pct` | raw × 0.78125 % | Motor oil cooling flow request |
| B2 | `GENE_ThermInd_pct` | raw × 0.78125 % | Generator thermal load indicator |

Raw 128 = 100%. All three broadcast at ~5 Hz in all operating modes (Parked, Operating, Driving).

**Why the correlation scans missed this signal:** All prior scans looked for temperature-shaped
bytes (raw range ~100-800, slowly varying, absolute units). These three signals are
*percentage* values capped at raw=128 (100%). Their raw range (0-128) and plateau behavior
at 100% do not resemble temperature encodings, so they passed through all filters undetected.

**Observations from `vtruxgeneratoroverheattest.log` and `vtruxgeneratorpumpunplug.log`**
(decoded via `gene_thermal_0479_epri.py`, plot `gene_0479_epri_overheat.png`):

*Normal operation (pumpunplug log, generator running with oil pump active):*
- `DrvCoolFlowReq_pct` and `MotCoolFlowReq_pct` both hold flat at ~50% throughout.
- `ThermInd_pct` is flat and low (~20-25%).
- No significant variation across the log; the generator is thermally stable.

*Overheat event (overheat log, oil pump already disconnected at log start):*
- `MotCoolFlowReq_pct` (B1) rises to ~100% and holds there during the sustained
  high-load generating phases. It drops briefly during pauses where generator torque
  goes to zero (the inverter stops requesting oil cooling when not under load).
- `ThermInd_pct` (B2) rises monotonically from ~25% at log start, peaks in the
  80-90% range near the RPM overflow event (t~1858s), then begins declining as the
  engine load is reduced and oil is allowed to circulate.
- `DrvCoolFlowReq_pct` (B0) also rises but less dramatically -- the inverter heatsink
  (PE glycol cooled) is secondary to the motor winding (oil cooled) as the stressed
  thermal path when the oil pump is disconnected.
- The `ThermInd_pct` peak aligns with the RPM spike: the VCU limits generator torque,
  the engine sees less load and RPM rises -- confirming `ThermInd_pct` as the trigger
  for generator torque derating.

**Role conclusion:** `GENE_ThermInd_pct` (B2) is the generator thermal load indicator
that drives inverter-side torque derating. It is not a raw temperature -- it is a
normalized percentage of the motor's thermal headroom consumed. `MotCoolFlowReq_pct`
(B1) is the motor oil cooling demand and saturates at 100% under sustained overheat
load. These signals explain the derating mechanism but do not give an absolute winding
temperature in degC.

**Raw winding temperature:** Still not found on the PT bus. The EPRI app does not
sample any raw temperature byte from the GENE MCU. The inverter likely tracks winding
temperature internally and only exports the derived percentage signals via 0x479.
This is consistent with the earlier conclusion that raw motor temperatures are not
broadcast -- only fault-derived indicators are exported to the VCU.

---

**TRAC MCU thermal signals -- revisit (2026-03-29):**

EPRI claimed `0x459` as `EPRI_MCU_Thermal1_0459` (symmetric to GENE 0x479 by a -0x020
offset). After finding the GENE signals via DBC decode, the same approach was attempted
for the traction motor.

**0x459 is the wrong ID:** Zero frames at 0x459 in all logs. The EPRI plist listed 0x459
for TRAC MCU thermal (derived by applying -0x020 to GENE 0x479), but the message exists at
0x44A instead. Unlike 0x451 (which exists but carries a different GMLAN message), 0x459
simply has no frames -- the TRAC MCU never broadcasts at that ID.

**OBD bus correlation scan:** A Pearson r sweep was run on the OBD bus (isolated using
the 0x044 anchor ID to identify the correct channel), excluding known GMLAN IDs. Per-byte and LE/BE uint16 pair tests were run
against the PT bus 0x06000002 10-bit signal as the reference. 642 candidates tested.

**Top hit: 0x44A B2 at r=+1.000.** Exact structure:

| Byte | Signal | Scale | Meaning |
|------|--------|-------|---------|
| B0 | `TRAC_DrvCoolFlowReq_pct` | raw x 0.78125 % | Inverter (drive) cooling flow request |
| B1 | `TRAC_MotCoolFlowReq_pct` | raw x 0.78125 % | Motor oil cooling flow request |
| B2 | `TRAC_ThermInd_pct` | raw x 0.78125 % | Traction motor thermal load indicator |
| B3 | Rolling counter | nibble (0x00/0x10/0x20/...) | Not a signal -- rolling counter same structure as TRAC torque feedback 0x442 B6 |

Structure is identical to GENE 0x479. Scale 0.78125 = SIMDImm(0xF,0x69) from EPRI ARM decompile
of the 0x479 decoder; assumed identical by symmetry (not yet confirmed from decompile of
the 0x44A decoder path).

**0x06000002 B5/B6 re-interpretation:** This 10-bit PT bus signal was previously labeled
"traction motor winding temperature, 2.0 deg C/count." That interpretation was inferential:
the "scale" was chosen to make raw=82 equal 164 deg C, matching the Remy HVH250-115D
derate threshold. No independent scale confirmation existed.

The r=+1.000 correlation with 0x44A B2 (TRAC_ThermInd_pct) shows the PT bus signal is
the OBD bus thermal percentage re-broadcast by the VCU. It is not a temperature in deg C.
The 10-bit encoding on the PT bus and the 8-bit encoding on the OBD bus are related by a
linear mapping, but the exact scale of the PT bus field has not been decoded. The "164 deg C
peak" figure was wrong -- the peak value at torque cutback was ~64% thermal load (raw=82,
0.78125/count mapping from OBD reference), not 164 deg C.

**EPRI ID offset pattern analysis:**

EPRI mapped TRAC MCU OBD IDs as GENE MCU PT IDs minus a fixed offset. Confirmed vs corrected:

| GENE (PT) | TRAC (OBD) EPRI claim | TRAC (OBD) actual | EPRI offset | Actual offset | Status |
|-----------|----------------------|------------------|------------|--------------|--------|
| 0x054 (rotation speed) | 0x044 | 0x044 | -0x010 | -0x010 | Correct |
| 0x051 (torque cmd) | 0x041 | 0x041 | -0x010 | -0x010 | Correct |
| 0x471 (torque feedback) | 0x451 | 0x442 | -0x020 | -0x02F | Wrong -- 0x451 is GMLAN Gateway_LS_General_Information |
| 0x479 (thermal) | 0x459 | 0x44A | -0x020 | -0x02F | Wrong -- 0x459 has 0 frames |
| 0x482 (HV bus) | 0x462 | 0x462 | -0x020 | -0x020 | Correct |

Pattern: EPRI applied -0x020 uniformly to the 0x47x group. The actual offset for both
0x47x messages is -0x02F. The actual TRAC counterparts of both wrong IDs land in the 0x44x
range (0x442 and 0x44A). The 0x04x/0x05x group (speed, commands) correctly uses -0x010;
the 0x48x/0x46x group (HV bus) correctly uses -0x020.

**Derate threshold analysis (2026-03-29):**

ThermInd_pct values at torque derate onset were checked against known event times in both
overheat logs. Generator torque (0x051) and traction torque feedback (0x5A2 B4-B5) were
used to confirm the cutback moment; ThermInd_pct was read from the confirmed OBD source
(0x44A B2 for TRAC, 0x479 B2 for GENE).

| Motor | Event time | ThermInd_pct at cutback | Peak in window | Notes |
|-------|-----------|------------------------|----------------|-------|
| GENE (generator) | t=1930.9s (gen overheat log) | **85.9%** | 86.7% | Under sustained high torque (~2000 counts) from 80% crossing all the way to cutback (~120s). 80% is not the threshold -- it is a point on the way up. |
| TRAC (drivetrain) | t=1953s (drivetrain overheat log) | **78.9%** | 80.5% (after cutback) | Peak reached after torque already dropped. Actual threshold ~78-79%. |

Both motors are Remy HVH250-115D with the same 160 degC derate threshold per datasheet.
The different ThermInd_pct thresholds (79% vs 86%) suggest the inverter thermal models are
tuned differently for each motor's application (generator vs traction duty cycle).

**0x06000002 PT bus scale confirmed (2026-03-29):**

Comparing 0x44A B2 OBD values (confirmed scale 0.78125%/count) against 0x06000002 10-bit
PT bus values at the same timestamps reveals that the PT bus raw10 values closely match the
OBD *percentage* values (not the OBD raw counts):

| Time | OBD 0x44A B2 pct | PT bus raw10 |
|------|-----------------|--------------|
| t=1943s | 77.3% | 77 |
| t=1953s | 78.9% | 78 |
| t=1963s | 79.7% | 79 |
| t=1973s | 79.7% | 79 |
| t=1983s | 78.1% | 78 |

The VCU converts the OBD percentage to a 10-bit integer: PT bus raw10 ≈ OBD_pct (i.e.,
**scale ~1.0%/count**, not 0.78125 and definitely not 2.0 degC/count). The "164 degC at
raw=82" figure was doubly wrong: wrong units (it is a percentage) and wrong scale. Correct
reading at raw=82 would be approximately 82%.

---

### 3A: Candidate Discovery

**Goal:** Find all slowly-varying temperature-like signals on the PT bus in the evap
drive log. Primary targets: drivetrain inverter, generator inverter, traction motor
winding, generator motor winding.

**Step 3.1** -- Survey `vtruxevapdrivelog4.log`. List all PT bus extended IDs not
attributed to charger (0xC0) or DCDC (0xB3). Note standard-frame IDs in 0x300-0x5FF
with moderate unique counts. Reuse `evaplog4_p1_survey.json` if complete.

**Step 3.2** -- Extract load reference signals (reuse existing artifacts if present):
```
py tools/extract_timeseries.py "logs/vtruxevapdrivelog4.log" --id 0x051 --bytes 1-2 --endian little > artifacts/evap4_gen_torque.csv
py tools/extract_timeseries.py "logs/vtruxevapdrivelog4.log" --id 0x598 --bytes 4-5 --endian little --signed > artifacts/evap4_drivetrain_current.csv
py tools/extract_timeseries.py "logs/vtruxevapdrivelog4.log" --id 0x598 --bytes 2-3 --endian little --signed > artifacts/evap4_gen_current.csv
```

**Step 3.3** -- Write and run `find_thermal_candidates.py` in artifacts/. Script:
1. Loads evap4, filters to PT bus
2. For each (ID, byte) not yet identified: computes median absolute change/sec + unique count
3. Correlates against four reference signals (interpolated to each candidate's timestamps):
   a. Synthetic gen-on ramp (t=90-1100s, rise then exponential decay) -- broad proxy
   b. Gen torque magnitude: |0x051 B1-B2 LE_uint16 - 32768| -- targets gen inverter
   c. Drivetrain torque magnitude: |0x5A2 B4-B5 LE_uint16 - 32768| -- targets traction inverter
   d. Negated pump speed: -(0x18FF0320 B5) -- validator; real thermals cool with pump
4. Ranks by max(|r|) across all four references -- catches both inverter types

Output: `artifacts/evap4_thermal_candidates.txt` -- top 40 ranked with all four r values.

**Step 3.4** -- Run `analyze_id.py` on top candidates. Temperature signature: raw range
200-800 for 20-80 degC at x0.1 encoding, LE signed, not previously attributed.
Priority IDs: 0x619, 0x0870A047, 0x0868A047, 0x390, 0x481, 0x599.

**Step 3.5** -- Check `0x6000001 B1` ("6 unique values, 116-136, slowly varying"):
```
py tools/extract_timeseries.py "logs/vtruxevapdrivelog4.log" --id 0x6000001 --bytes 1 > artifacts/evap4_0x6000001_B1.csv
```

**Step 3.6** -- Separate traction-only IDs using compare.py:
```
py tools/compare.py "logs/generator on then off.log" "logs/vtruxevapdrivelog4.log" --ids-only
```
IDs only in evap4 (absent from generator log) -> likely traction-only. IDs in both ->
generator-or-shared. NOTE: generator inverter stays powered and on-bus even when not
generating (see 0x471 torque feedback going to zero rather than disappearing). Cannot
use absence-from-gen-log as a positive identifier for generator inverter IDs.

---

### 3B: Thermal Time-Constant Analysis

**Goal:** Classify each confirmed signal as inverter-side (tau ~30-120s) vs
motor-winding-side (tau ~3-15 min) using rise/decay time constants.

**Step 3.7** -- Extract confirmed thermal candidates from both log parts:
```
py tools/extract_timeseries.py "logs/vtruxevapdrivelog4.log" --id <ID> --bytes <B> --endian little --signed > artifacts/evap4_thermal_<ID>.csv
py tools/extract_timeseries.py "logs/vtruxevapdrivelog4part2.log" --id <ID> --bytes <B> --endian little --signed > artifacts/evap4p2_thermal_<ID>.csv
```

**Step 3.8** -- Check Part 1 / Part 2 temporal continuity (compare last 60s of evap4
vs first 60s of evap4p2). If values are continuous, treat as a single 1804s record.

**Step 3.9** -- Write `thermal_time_constants.py` in artifacts/. Fits exponential
rise/decay to each timeseries using generator start/stop timestamps from evap cycle
analysis. Reports tau per signal.

**Step 3.10** -- Generator motor heat-soak test: In evap4part2, generator shuts down
~t=290s. Signals that briefly *continue rising* after shutdown (engine heat conducting
into generator motor winding) are unique to the generator motor -- not seen on inverter
or traction motor.

**Step 3.11** -- Traction motor isolator: run top candidates against the driveway log
(no generator) -- traction signals change with driving, generator signals do not.

---

### 3C: Motor Temperature Decision

**Hypothesis**: Motor temperatures may not be broadcast at all -- only binary fault
states from inverters. This would explain sudden thermal limits with no gradual warning.

**Step 3.12** -- If no signals with tau > 3 min found in 3A/3B, this is strong
evidence motor temperatures are internal to the inverter and only a fault bit is exported.

**Step 3.13** -- If 4 temperature-like signals are found:
- 2 fast (tau < 2 min) -> drivetrain inverter + generator inverter heat sinks
- 2 slow (tau > 5 min) -> traction motor + generator motor windings
- Distinguish inverter vs motor using Step 3.9 time constants
- Distinguish generator motor from traction motor using heat-soak test (Step 3.10)

---

## Phase 4 -- Oil Pumps: CAN Presence Check (Not Yet Started)

**Goal:** Determine whether the two oil pumps (shared reservoir; one cools drivetrain
motor, one cools generator motor) have CAN presence. Distinct from PE glycol water pump.

**Prior knowledge:** No evidence of oil pump CAN messages documented. May be simple
relay/PWM-controlled with no bus presence.

**Step 4.1** -- In evap drive log, list all PT bus extended-frame source addresses
not yet attributed. An oil pump controller would only broadcast when its motor runs
(drive logs only, not charge logs). Reuse Phase 3 survey output if complete.

Known attributed source addresses: 0xC0/0x40/0x80 (Bel charger, absent in drive),
0xB3 (Bel DCDC), 0x20 (PE coolant pump). Any new address = oil pump candidate.

**Step 4.2** -- For each candidate: run `analyze_id.py`. Look for speed/flow setpoints
(discrete values), temperature feedback (slowly varying), or on/off status (2-4 unique
values).

**Step 4.3** -- If no new source addresses found: conclude oil pumps are not CAN-visible
on the PT bus (likely VCU direct PWM/digital control or internal to inverters). Record
conclusion and close question.

---

## Final Documentation Updates (After All Phases Confirmed)

1. **Update** `notes/powertrain-messages.md` -- add Thermal Signals section; update
   BMS cluster section with confirmed temperature bytes and Peltier findings
2. **Update** `vtrux-powertrain.dbc` -- add confirmed battery temp and inverter/motor
   temperature signals (DCDC temperature already added in Phase 1C)
3. **Update** `Vtrux.md` -- PE Coolant Pump section (pump command confirmed as
   0x18EF2000), Next Steps
4. **Update** `notes/artifacts/README.md` -- inventory all new artifacts with provenance

*Note: A separate BelDCDC.dbc was originally planned but DCDC signals were added
directly to `vtrux-powertrain.dbc` under BELDCDC_analogMeasurements. No separate
DCDC DBC is needed.*

Validate DBC changes:
```
py tools/dbc_validate.py "vtrux-powertrain.dbc" "logs/vtruxcurrentlimitingtest.log"
py tools/dbc_validate.py "vtrux-powertrain.dbc" "logs/vtruxevapdrivelog4.log"
```
