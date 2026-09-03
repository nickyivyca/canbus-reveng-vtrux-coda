# Coda DC-DC Converter (U2C) — Source Documents

The Coda's HV-to-12V converter is a **Delphi U2C — Universal 2.2 kW Converter**
(part `U2C-10018134-001`). `DCDCStatus2` (0x48A) carrying `U2C_Power_Loss` is the
giveaway; LabVIEW names the same field `CalcdPwrLossThroughU2C (W)`.

| File | What it is |
|------|-----------|
| `U2C Manual Rev03_2-15-2011.pdf` (internal-only, not in the public repo) | Delphi Operation / Application Manual, Rev 03, 11 Feb 2011, 65 pp. **Primary source** for every DC-DC CAN signal. Sections 2.5.1.1 (0x1D5, pp.16-18), 2.5.1.2 (0x48A, pp.18-19), 2.5.1.3 (0x1D7, pp.20-21), 2.5.2 (0x396/0x39F, pp.21-23), and Appendix B (UDS diagnostic modes, pp.32-65). |

## What the manual settles

Verified 2026-08-24 against `CODA-B-CAN.dbc`, by both text extraction and reading
the rendered pages (the p.17 bit-layout diagram is an image, so text extraction
alone would not have shown that bit 55 is left empty).

| Message | Manual | DBC | |
|---|---|---|---|
| 0x1D5 `HV_Input_Current` | 8 bits, B1, res .1 A | `15\|8@0+ (0.1,0)` | match |
| 0x1D5 `Voltage_14V` | 8 bits, B3, res .078431 V | `31\|8@0+ (0.078431,0)` | match |
| 0x1D5 `Current_14V` | **7 bits, B6 bits 0-6, res 2 A** | `54\|7@0+ (2,0)` | match |
| 0x48A `U2C_Power_Loss` | 8 bits, B2, res 2 W | `23\|8@0+ (2,0)` | match |
| 0x48A thermistors | 8 bits, B4/B5, res 1, offset -40 degC | `39\|8@0+`, `47\|8@0+` | match |
| 0x1D7 `VoltageSetPoint` | byte = V * 45.3329 - 473.161 | scale 0.0220590, offset 10.4375 | **corrected 2026-08-24** (was 0.022 / 10.437) |
| 0x1D7 `Boost_Enable` | 3 bits, B6 bits 5-7, 6-value enum | `55\|3@0+` + `VAL_` | enum **added 2026-08-24** |

The DBC now decodes the manual's own worked examples exactly: `10 47 52 B1 80 00 23 00`
-> 7.1 A / 13.88 V / 70 A / DTC 10 "Unused" / "No Status to Report", and
`80 A1 00 00 00 00 60 00` -> 13.989 V / Boost_Enable "Active".

Added to the DBC from this manual: `VAL_` tables for `DTC_Index` (19 named codes),
`DTC_Status` (5), and `Boost_Enable` (6).

## What the manual does not settle

- **0x1D5 B7 is active** (0xAD-0xB3 across every capture) although the manual shows
  byte 7 as unused. Role unknown; deliberately left without a signal definition.
  B5 *is* unused, as documented (0x00 in all 2.4M corpus frames).
- **0x396 (odometer) and 0x39F (timestamp)** are optional receive messages the U2C
  uses only to date-stamp its DTC stacks. Both are absent from the Coda bus —
  0 frames corpus-wide — so neither is in the DBC.
- **Boost mode** re-uses the 0x1D7 set-point byte with a different formula
  (byte = V * 1.0408 - 176.42, range 194-358 V). Not modelled; the Coda has not
  been observed commanding boost.
- `HV_Validity` and `Master_Fault` are **0 in all 2.4M corpus frames**, so the
  validity bit carries no information here.

## Light-load energy-balance artifact

Because the U2C reports its own loss, the balance can be closed with no external
reference: `(P_LV + P_loss) / I_HV` should equal pack voltage.

| HV input current | balance | implied efficiency |
|---|---|---|
| < 1.5 A | 1.13-2.09x | impossible |
| >= 1.5 A | **0.97-0.99x** | **89-92%** |

Above 1.5 A the converter's own three numbers add up and give a textbook efficiency
curve. Below it they do not, and `U2C_Power_Loss` reads exactly 0 — the U2C is not
computing loss in that regime. The divergence is **not** caused by charging (1.42x
charging vs 1.38x not), and **not** by a scale error, which the high-load agreement
rules out. Treat sub-1.5 A DC-DC readings as unreliable rather than re-deriving
scales from them. See `../efficiency-calculation.md` Sec.4 and
`../artifacts/dcdc_12v_scale_check.py`.
