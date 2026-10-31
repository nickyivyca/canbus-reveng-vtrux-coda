# Coda — Thermal Indicator Signals (0x276 B2)

Investigation into which CAN signal reliably indicates cabin heating/cooling and pack heating/cooling, motivated by the Android app's cabin and battery thermal icons disagreeing with the original Coda green screen.

**Status (2026-10-28):** B2 is now decoded from the HVAC firmware (`hvac/coda-hvac-decompile-notes.md` section 9). B2 carries a 4-bit mode nibble that encodes cabin mode × pack mode directly. The earlier per-value enum below, built from observation, is superseded; its meanings are corrected in the table. The app fix is in code (2026-10-30, decompile notes 9.4) and ships in the next Coda release build.

## 0x276 B2 layout (from firmware)

```
B2 = (0x3DF3 & 3) << 6  |  mode_nibble << 2  |  HV disable bits (1:0)
mode_nibble = (B2 >> 2) & 0x0F        -- RAM 0x37C4
```

The nibble is set by the HVAC mode chart (0x7F17ED / 0x7F18F4). It is the cabin superstate crossed with two pack-demand flags:

| Pack \ Cabin | none (off) | heat | cool |
|---|---|---|---|
| none | 0 | 2 | 4 |
| pack heat (`0x3756` b0) | 1 | 5 | 7 |
| pack cool (`0x3753` b0) | 3 | 8 | 6 |

- **Cabin "on"** (`0x374E` bit 3) needs the cabin blower to be running (`0x3821` ≥ cal 20).
- **Cabin heat** (bit 2) is set when the temperature knob `0x37DE` is ≥ 140 (with hysteresis) and the AC switch is off.
- **Cabin cool** (bit 1) is set when AC is requested and the knob is ≤ 180.
- The knob value is transmitted as `0x392 B0`.
- **Pack cool demand** (`0x3753` b0) comes from `0x3807`, a ramp centred on the BMS's AllowedCellTempMax.
  - It is also raised by ATD0 ch9/ch10.
  - **Hypothesis:** ch9/ch10 are the battery humidity and battery humidity-temperature sensors, which would make nibble 3 at least partly a pack-dehumidify state. This is not confirmed, and the humidity value is not on CAN.

Bits 7:6 (`0x3DF3`) have no known writer. In the corpus they are non-zero only briefly (B2 0x81, 0x91: 51 s in total).

## 0x276 B2 — observed values, corrected meanings

Dwell and actuator figures come from 1,052 CANLogs captures on B CAN (`hvac/artifacts/hvac_mode_corpus.py` c1). Actuator columns are the % of that dwell with each actuator on.

| B2 | Nibble | Meaning | Dwell (s) | PTC PWM | Compressor | Battery fan | Old label (wrong) |
|----|----|---------|-----:|----:|----:|----:|----|
| 0x01 | 0 | idle: cabin off, no pack demand | 175,930 | 6 % | 0 % | 1 % | "low-level state" |
| 0x02 | 0 | idle, HV disabled | 3,770 | 0 % | 0 % | 0 % | — |
| 0x05 | 1 | pack heat, cabin off | 0 in corpus¹ | | | | "pack conditioning only" (correct) |
| 0x09 | 2 | cabin heat, no pack demand | 8,926 | 90 % | 25 % | 8 % | "cabin heat — transitional" |
| 0x0D | 3 | pack cool, cabin off | 2,505 | 14 % | 21 % | 88 % | "fresh air / default off" |
| 0x0E | 3 | pack cool, HV disabled | 74 | 0 % | 0 % | 0 % | "HVAC fully off" |
| 0x11 | 4 | cabin cool (AC), no pack demand | 59,325 | 0 % | 98 % | 1 % | "AC active" (correct) |
| 0x19 | 6 | cabin cool + pack cool | 97 | 0 % | 98 % | 12 % | — |
| 0x21 | 8 | cabin heat + pack cool | 793 | 82 % | 17 % | 88 % | "cabin heat — sustained" |
| 0x91 | 4 | cabin cool, bits 7:6 = 2 | 51 | 0 % | 99 % | 0 % | — |

¹ B2 0x05 is absent from the CANLogs corpus. It was seen in the primary-log conditioning capture (`thermal-behavior-investigation.md`). Nibbles 5 (cabin heat + pack heat) and 7 (cabin cool + pack heat) have not been observed anywhere.

### What this resolves

- **0x09 vs 0x21.** Both mean cabin heat. 0x21 adds a pack-cool demand. This fits the battery fan running 88 % of 0x21 time against 8 % of 0x09 time, and it explains why 0x21 was the "sustained" value on a warm commute.
- **0x0D is not "fresh air".** It is pack cool demand with the cabin off. The battery fan is on 88 % of that time and the compressor 21 %.
  - The earlier note's "PTC running for the pack" at 0x0D accounts for 14 % of the dwell.
  - The firmware does not explain why the PTC runs in a pack-cool state. Under the humidity hypothesis above, it would be reheat during dehumidify.
- **Cabin heat with the compressor running** (25 % of nibble 2 time; presumably defrost/demist) cannot be told apart from plain cabin heat in B2. The compressor is visible separately as `0x410 B6 > 0`.

## Mapping for the Android app (approved 2026-10-28)

```
nib = (B2 >> 2) & 0x0F
cabin:   HEATING if nib in {2, 5, 8};  COOLING if nib in {4, 6, 7};  else NONE
battery: HEATING if nib in {1, 5, 7};  COOLING if nib in {3, 6, 8};  else NONE
```

- Cabin heat with the compressor running stays **HEATING** (red). This matches the behaviour the user has seen on the original green screen.
- A separate compressor-running flag, `0x410 B6 > 0`, is exposed for later use and does not change the icon.
- Under the humidity hypothesis, a pack-dehumidify state shows as battery COOLING. That is consistent with the green screen staying on cooling during dehumidify.

## Android App Bugs (fixed in code 2026-10-30, step 6d)

The app now uses the mapping above (`HvacMode.kt`); a replay of the 17 flip captures shows no icon change while B2 holds still (plan step 6d). What `CodaSignalDecoder.kt` did before:

- **Cabin icon:** `hvacFlags & 0x10 -> COOLING; & 0x08 -> HEATING; else NONE`. These are bits of the nibble, not mode values. As a result:
  - 0x0D (pack cool, cabin off) shows cabin HEATING.
  - 0x21 (cabin heat) shows NONE.
  - 0x15 (nibble 5, cabin heat + pack heat) would show COOLING.
- **Battery icon:** NONE if the battery fan PWM (0x390) is 0. Otherwise HEATING if the mean of the front and rear inlet coolant temperatures is above the return temperature, else COOLING. This keys on coolant temperatures, not the controller's mode.
  - A corpus replay found 218 direct HEATING↔COOLING icon changes in 17 captures.
  - **217 of them are the battery icon flipping while B2 stayed constant:** 0x0D 130, 0x01 68, 0x21 17, 0x09 2.
  - This is the flip-flopping seen during what looked like dehumidify.
  - The one cabin flip (0x11 → 0x09) was a real mode change.

The earlier pending fix in this file (`hvacFlags == 0x09 || hvacFlags == 0x21`) is superseded by the nibble mapping above.

## Supporting Logs and Scripts

| Log / script | Role |
|-----|------|
| `CANLogs/CodaLogs/coda_20260422_192202_T0.log` | Evening commute, heat starts at T0 t=282s (highway merge) |
| `CANLogs/CodaLogs/coda_20260422_192202_T1.log` | Evening commute cont., 0x09/0x21 changes (cabin heat with and without pack-cool demand); heat off at T1 t=80s |
| `CANLogs/CodaLogs/coda_20260422_193155_T0.log` | Targeted test: 0x0D period (pack cool demand, cabin off), then cabin heat, heat off sequence |
| `projects/coda/notes/artifacts/hvac_targeted_test.py` | B2/B5/B1/B0 transition dumps for the three logs above |
| `projects/coda/notes/artifacts/commute_speed_power.py` | Speed + torque + PTC power binned trace for commute logs |
| `projects/coda/notes/hvac/artifacts/hvac_mode_run.py` | Emulator runs of the HVAC mode chart: knob/AC/blower inputs, `0x3807` pack-cool ramp, cabin × pack matrix |
| `projects/coda/notes/hvac/artifacts/hvac_mode_corpus.py` | Corpus sweep: dwell and actuator activity per B2 and per nibble, and replay of the app's icon logic (`hvac_mode_corpus.c1.out.txt`, `.flips.csv`) |
