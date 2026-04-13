# BelInverter DBC Merge Notes

`BelInverter-v2.dbc` was created at the project toplevel by merging the previous DBC (`Bel-Inverter/BelInverter.dbc`) with findings from the EPRI Ghidra decompile investigation. The previous DBC is left untouched.

## Changes from previous DBC

### Extended ID bit (all messages)
All IDs had bit 31 added (e.g. 419419584 → 2566903232). The previous DBC stored raw 29-bit CAN IDs without bit 31, causing cantools to misidentify them as 11-bit standard frames.

### `BELINV_overallTemperature` (0x18FFD5C0)
- `overallTemperaturePercent` corrected from 16-bit (`48|16@1+`) to 8-bit (`48|8@1+`).
  The Ghidra decompile reads a single byte at offset B6 (`bVar69 = pbVar15[10]`) and formats it with `%d`. The previous DBC's 16-bit definition would have consumed B7, which is unrelated data.
  Validated against `full charge then fail.log`: B7 is zero for the entire charge session except a 21-frame startup transient (15:45:31–15:45:51). The 8-bit reading gives a clean 0–37% thermal load curve tracking BDC temperature from ~25°C to ~56°C peak.
- B4:B5 (`ambientTemperature`) confirmed by Ghidra as BDC internal temperature, not ambient. Signal name kept from previous DBC pending a rename decision.
- B0:B3 unconfirmed by EPRI; left as-is from previous DBC.

### `BELINV_inverterOutput` (0x18FFD6C0)
Byte layout confirmed by Ghidra decompile as an exact match with the previous DBC. No signal changes; IDs updated only.

### `BELINV_hvBatteryAndCharger` (0x18FFD7C0)
Three signals corrected from signed to unsigned per EPRI decompile:
- `hvBatteryVoltage` (B0:B1): unsigned — physical bus voltage cannot be negative
- `chargerInputVoltage` (B4:B5): unsigned — AC RMS voltage
- `chargerInputCurrent` (B6:B7): unsigned — AC RMS current

`hvBatteryCurrent` (B2:B3) remains signed (bidirectional; positive = charging, negative = discharging/export).

### `BELINV_j1772Info` (0x18FFD8C0)
`system12vBatteryVoltage` (B0:B1, scale 0.02) confirmed by Ghidra decompile. B2–B7 from previous DBC only.

### Unchanged messages
`BINV_status`, `BELINV_chargeInfo`, `BELINV_inverterTemperature`, `BELINV_buckBoostTemperature` — not present in EPRI plist; carried forward from previous DBC unchanged (IDs updated only).

## What was NOT merged
The DCDC step-down converter (0x18FFD6B3, SA=0xB3) discovered during the EPRI investigation is a separate device and was intentionally excluded. Its confirmed signals are documented in `epri-pt-bus.dbc`.
