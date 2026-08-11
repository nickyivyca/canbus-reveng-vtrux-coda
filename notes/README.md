# Cross-Vehicle Notes

Topics that span more than one vehicle. Per-vehicle findings belong in
`projects/<vehicle>/notes/`; anything covering shared hardware or a vehicle-agnostic
method lives here so it is not duplicated per vehicle.

## Files

| File | Contents |
|------|----------|
| `ac-resistance.md` | AC supply voltage and source resistance during charging, from on-board charger CAN telemetry. Vehicle-agnostic method (four estimators of increasing drift-robustness, plus the pooling/classification pitfalls that produce wrong answers). Vtrux results: 121 charge sessions over 20 outlets, typical ~0.4 ohm at 240 V and ~0.24 ohm at 208 V, an extension-cord A/B worth ~+0.11 ohm, the 2026-07-14 ~190 V weak-supply event, and the EVSE derate (`drawn ~= advertised - 3 A`). Coda section pending. |
| `borgwarner.md` | BorgWarner eGearDrive transmission CAN signals. Same TCM hardware/firmware family in both Vtrux (32-01, longitudinal) and Coda (31-03, transverse). |
| `borgwarner-transmissions.pdf` | BorgWarner eGearDrive hardware reference, supporting `borgwarner.md`. |

## Subdirectories

| Directory | Contents |
|-----------|----------|
| `Heater/` | HV PTC coolant heater shared by Coda and Vtrux: vendor datasheets, PWM captures, plug polarity photos, vendor correspondence. |
| `artifacts/` | Generated cross-vehicle data files — verbose DBC exports for both vehicles and the `dbc_cleanup.py` script used to produce them, plus DBC tooling notes. |

## Conventions

- Analysis artifacts (scripts, CSVs, raw extracts) stay with the data they process. A
  cross-vehicle write-up here may therefore reference artifacts under
  `projects/<vehicle>/notes/artifacts/`; only genuinely cross-vehicle artifacts live in
  `artifacts/` here.
- Each topic file states which vehicles it covers and the status of each.
