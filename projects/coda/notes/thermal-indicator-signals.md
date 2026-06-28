# Coda — Thermal Indicator Signals (0x276 B2)

Investigation into which CAN signal reliably indicates cabin heating vs pack conditioning vs fresh air, motivated by the Android app `cabinThermal` display being wrong during normal heating.

## Background

The green screen display shows a heat/cool indicator for the cabin. The Android app reads 0x276 B2 (HVACHVDisableStatus) and was checking bit 3 (`hvacFlags & 0x08`). This was derived from the driver-inputs.md Part 2 HVAC on/off test, which captured the transition state (B2=0x09, where bit 3 is set) but missed the sustained steady-state heating value (B2=0x21, where bit 3 is NOT set).

## 0x276 B2 — Known Enum Values

| B2 value | Meaning | Confidence | Notes |
|----------|---------|------------|-------|
| 0x01 | Unknown — low-level state | Medium | Appears during pack heater oscillation (thermal-behavior-investigation.md); also appears in commute logs during conditioning cycles |
| 0x05 | Pack conditioning only | High | Confirmed in conditioning-specific log; B5=0, cabin fan off or low |
| 0x09 | Cabin heat — transitional | High | Appears briefly at heat start or during mid-drive windows; always co-occurs with B5=186; treat as cabin heating active |
| 0x0d | Fresh air / default off state | High | Appears when cabin HVAC is in fresh-air mode or conditioning-only; PTC may or may not be running (if B5>0 here, PTC is for pack not cabin) |
| 0x0e | HVAC fully off | High | Seen when fan shuts off in targeted test; brief transition state |
| 0x11 | AC active | High | Confirmed in driving-sequence-investigation.md |
| 0x21 | Cabin heat — sustained | High | Primary steady-state heating value; co-occurs with B5=186; confirmed across multiple logs |

## Correct Cabin Heating Check

Cabin heat is active when `B2 ∈ {0x09, 0x21}`.

`B2 == 0x0d` with `B5 > 0` means the PTC is running for the pack, not the cabin — this is the key distinction that makes PTCHeaterPWM (B5) insufficient as a standalone cabin heating indicator.

## Why PTCHeaterPWM (B5) Alone Is Insufficient

B5 = PTCHeaterPWM (0x276 byte 5). It indicates the PTC element is physically energized, but does not tell you whether that heat is going to the cabin or the battery pack.

- `B2=0x21` + `B5=186` = cabin heating at full power
- `B2=0x0d` + `B5>0`  = PTC running for pack conditioning; cabin on fresh air

This was confirmed in the targeted test (2026-04-22 commute + 193155_T0): pack conditioning ran with B2=0x0d and B5 ramping while the cabin was set to fresh air.

## 0x09 vs 0x21 — Unresolved Distinction

Both values indicate cabin heating is active. The difference is not yet understood.

**Ruled out:**
- Battery conditioning state — B7(batt) fan is high during both 0x09 and 0x21, and 0x21 also appears with B7(batt)=0 (no conditioning). Not the differentiator.

**Observations:**
- 0x09 is always transient: appears for ~4s at the start of a heat cycle in the commute T0 log, and for ~20s in T1 while PTC power (B0) was in the 43–47 count range
- In the targeted test (193155_T0), heat went directly to 0x21 — no 0x09 appeared at all
- In commute T1, a mode knob spin occurred at t=8.73s and 0x09 appeared at t=24.39s (~16s later), though the causal link is unclear
- Both 0x09 and 0x21 always co-occur with B5=186 in the commute logs

**Working hypothesis (unconfirmed):** 0x09 may be an HVAC controller transitional state — either mid-ramp or a brief state entered when the mode knob is adjusted while heat is active. Needs a deliberate test to confirm.

## Android App Bug

`CodaSignalDecoder.kt` (around line 141) uses:

```kotlin
val cabinThermal = if (hvacFlags and 0x08 != 0) ThermalState.HEATING else ...
```

This catches 0x09 (bit 3 set) but misses 0x21 (bit 5 set, bit 3 clear), so sustained heating is never displayed.

Pending fix (not yet applied):

```kotlin
val cabinThermal = when {
    hvacFlags and 0x10 != 0                -> ThermalState.COOLING  // 0x11 = AC
    hvacFlags == 0x09 || hvacFlags == 0x21 -> ThermalState.HEATING
    else                                   -> ThermalState.NONE
}
```

## Supporting Logs

| Log | Role |
|-----|------|
| `CANLogs/CodaLogs/coda_20260422_192202_T0.log` | Evening commute, heat starts at T0 t=282s (highway merge) |
| `CANLogs/CodaLogs/coda_20260422_192202_T1.log` | Evening commute cont., shows 0x09/0x21 oscillation; heat off at T1 t=80s (highway exit) |
| `CANLogs/CodaLogs/coda_20260422_193155_T0.log` | Targeted test: pack conditioning + fresh air, then cabin heat, heat off sequence |
| `projects/coda/notes/artifacts/hvac_targeted_test.py` | Script that produced B2/B5/B1/B0 transition dumps for all three logs |
| `projects/coda/notes/artifacts/commute_speed_power.py` | Speed + torque + PTC power binned trace for commute logs |
