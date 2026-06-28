# Coda Module Diagnostic IDs & Supplier Part Numbers

Identification data read over the diagnostic bus on **2026-06-27** with the live
car, using `artifacts/module_id_survey.py` and `artifacts/srs_module_id_probe.py`
(both read-only; reuse the ISO-TP transport from the `coda-diagnostics` reader).

For each module the survey tried the KWP2000 `0x1A 0x80` ECU-identification block
and the UDS `0x22` part-number DIDs (`F187` VM spare-part, `F191` VM hardware,
`F192` supplier hardware, `F194` supplier software).

## Key finding: `AK` is Coda's internal part-number prefix

Confirmed: the `AK...` strings are **Coda's own vehicle-manufacturer (VM)
catalog numbers**, not the Tier-1 supplier's. They appear consistently across
modules in the VM part-number fields (`F191` / `F187`), while the separate
supplier-hardware field (`F192`) carries the Tier-1's own number. The BMS uses a
sibling `AX` prefix.

This is why the airbag's stored ID (`AK36030100`) reveals nothing about its
origin on its own -- it is only Coda's number for the unit.

## Part-number survey (2026-06-27)

| Module | Coda VM part # | Supplier hardware # (`F192`) | Supplier software # (`F194`) | Supplier |
|--------|----------------|------------------------------|------------------------------|----------|
| Airbag (SRS) | **AK36030100** (via `1A 80`) | not exposed (KWP2000 module) | - | unknown (see below) |
| DLCM | AK2108010000 (`F191`) | A2C3814910000 | 5270 | **Continental (confirmed)** |
| Gateway | AK21080200 (`F191`) | 318539Iss2 | 10010_3121 | unconfirmed (hypothesis: UK) |
| PowerSteering (EPS) | AK34040001 (`F187`) | 26145734002B | CODA_02.0.01 | unidentified |
| BMS | AX2108010000 (`F191`) | P820-100 | SVN-Version 4542 | unidentified |
| HVAC | (no clean VM #) | (malformed response) | - | unidentified |

Notes:
- **DLCM = Continental — confirmed.** The `A2C...` prefix is Continental/Temic's
  standard part-number format, and the physical module carries a Continental
  label. (Matches the firmware decompile: DLCM = Continental EMS9180, Renesas
  SH-4 -- see `dlcm/coda-dlcm-decompile-notes.md`.)
- Gateway VM # `AK21080200` matches the gateway firmware decompile string
  (see `coda-gateway-decompile-notes.md`).
- EPS supplier software `CODA_02.0.01` is Coda-specific firmware on a third-party
  EPS unit.
- **Hypothesis (unconfirmed):** Gateway supplier string `318539Iss2` -- the
  "Iss2" = "Issue 2" convention suggests a UK-based supplier. Not verified.
- HVAC returned malformed/inconsistent data for these DIDs (`F191` = `v1.4rev5`,
  a firmware-version string; `F187` = binary garbage). It does not cleanly
  support the part-number DIDs; treat HVAC IDs as unreliable.

## SRS / Airbag module

- Diagnostic addressing: request **0x7C4**, response **0x7CC**.
- **Pure KWP2000 (ISO 14230) module, pre-UDS.** No `0x22 ReadDataByIdentifier`
  support at all; only `0x1A` options `0x80` (ECU ID = `AK36030100`), `0x90`
  (VIN slot, blank `FF`), and `0x99` (blank `FF`) exist. Uses `0x18` for DTC
  read and `14 FF 00` (2-byte KWP group) for clear; sends `7F xx 78` pending.
- The module exposes **no supplier-ID field** -- only Coda's `AK36030100`. The
  actual Tier-1 supplier identity is therefore **not available on the bus**; it
  must be read from the physical label on the ECU case (look for a Bosch /
  Continental `A2C` / Autoliv / ZF-TRW / Mobis number).
- **Interpretation:** the parts-bin pattern across the car (distinct name-brand
  Tier-1s per module, each relabeled under an `AK` Coda number) indicates the
  SRS is a Tier-1 airbag ECU configured for Coda, not lifted from another
  automaker's complete electronics suite. Platform-sourcing background: the Coda
  Sedan is an adapted Hafei Saibao (Chinese-built).

### Sourcing the B1513 passenger buckle switch
The passenger seatbelt buckle switch (DTC B1513) is a **passive switch**, not a
smart sensor tied to the SRS generation. Most practical match path is by
electrical signature (connector pinout, NO/NC type, resistance) rather than by
SRS part catalog.

## SRS DTCs read 2026-06-27 (real scanner cross-checked)
Captured in `logs/coda_srs_dtc_read.log`:

| DTC | Description |
|-----|-------------|
| B1102 | Battery voltage low |
| U1110 | (lost comm / network) |
| U0110 | Lost communication with motor control module |
| B1513 | Buckle switch passenger open or short to battery |
| B1382 | Side airbag front-passenger resistance too high |

A later live read (same session, after the clear) showed the airbag reporting
**No DTCs** -- consistent with the clear having taken effect.

## Diagnostic tooling status (`coda-diagnostics` repo, isotp-refactor branch)
- Fixed DTC decoding: a single standard SAE J2012 decoder (`dec_sae16`) replaced
  the broken `dec_dlcm` / `dec_chassis16`. Previously DLCM C0044 mis-printed as
  P0044 and Gateway/Airbag U-codes printed as `?xxxx`. The third Gateway code is
  **U0037** ("CAN Bus Failure Detected"), not U1037 (the old decoder's hard-coded
  leading digit was an artifact).
- Fixed airbag clear: real scanner uses `14 FF 00` (2-byte KWP group), not the
  3-byte `14 FF FF FF`. Verified against `logs/coda_srs_dtc_clear.log`.
- See the repo's `docs/protocol.md` for full encoding details.
