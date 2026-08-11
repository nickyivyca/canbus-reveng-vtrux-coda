# Fault Lamp Investigation — Coda

How the dashboard fault lamp (yellow / red) is driven on the Coda: which module
detects a fault, how it is signalled on the bus, and how it reaches the cluster.

Scripts and raw output: `artifacts/fault-encoding/`.

## Message chain

```
  BMS  0x270  ──┐
  DLCM (via absence, or a fault it reports) ──┐
                ▼                              ▼
              GWM  0x271  (arbiter)  ──►  IPK 0x491 / cluster lamp
```

- **`0x270` BMS_FaultStatus** (BMS, B CAN) — BMS fault state.
- **`0x271` GWM_VehFaults** (GWM, B CAN) — the arbitrated lamp request the GWM
  sends toward the cluster. This is the signal that actually corresponds to the
  lit lamp.
- **`0x491` IPK_Status** — cluster-side status; a key-on latch, not the driver.

## `0x271` B0 — the lamp request (confirmed)

`0x271` B0 bits [1:0] carry the lamp state: **0 = OFF, 1 = YELLOW, 2 = RED**. Bit 2
is a separate flag (see below). Established against `0x270` and against known
fault/no-fault logs.

**`0x271` carries lamp colour only — no source, no code.** Across all 428,827
`0x271` frames in the corpus (34 logs), **bytes B1–B7 are zero in every frame**.
So the DBC signals `VehicleFault` (B1–B4, 32-bit code) and `VehFaultSeverity`
(B0 high nibble) never carry data. There is no fault code or fault source on the
bus — only the lamp colour. Identifying *why* the lamp is on requires a UDS DTC
read per module (as in `logs/partscarcodes.txt`), not `0x271`.

Bit 2 (`VehicleFaultB0Bit2`) was documented as a "key-on lamp test" flag. It is
not: it pulses intermittently across entire drives (e.g. `defroster2` t=9.6 s to
701.7 s), so the "lamp test" label is wrong. Role still open.

## `0x270` B0 — BMS fault status (severity nibble + red-lamp bit)

The DBC splits B0 into `BMSFaultSeverity` (high nibble, 7|4) with a 0–6 severity
VAL_ table and a low nibble. **A CODACAN inject test (2026-07-26) confirms the high
nibble IS the severity:** injecting `B0 = 0x10` reads back severity **1 "Information
Only"**, and `B0 = 0x00` reads severity **0 "No Fault"** — the high nibble `[7:4]`
drives CODACAN's `BMSFaultSeverity` field directly. An earlier read of this byte as
"per-bit only, no real severity nibble" was incomplete and is superseded.

The confusion came from the lamp. Controlled test (BMS as fault source, B0 stable
≥250 ms before sampling the lamp, startup excluded), ~194 k frames:

| B0 | severity `[7:4]` | bit1 | bit0 | lamp | frames |
|----|------|------|------|------|--------|
| `0x10` | 1 | 0 | 0 | OFF | 169,446 |
| `0x12` | 1 | 1 | 0 | RED | 24,360 |

`0x10` and `0x12` share severity **1** but sit on opposite sides of the lamp — not
because the high nibble fails to be severity, but because **the red lamp is a
separate low-nibble bit (bit1), orthogonal to severity.** Both frames are severity
"Information Only"; only `0x12` also asserts the red-lamp request. Read the byte as:

- **`[7:4]` = `BMSFaultSeverity`** (0–6 enum), confirmed as the severity field by the
  inject test. In natural driving it only reaches 0–1, so **bit 4 is the severity
  nibble's LSB**, not an orthogonal state flag. (bit 4 set tracks high SoC — median
  100 % SoC when set vs 85 % when clear — but that is incidental to it being the
  severity LSB, not a separate meaning.)
- **bit 1 = red-lamp request.** 100 % clean vs `0x271` outside startup; relayed to
  `0x271` ~85 ms later.
- **bit 0 = key-on lamp test only**, never a real fault.

Across the whole corpus B0 only ever takes `00 01 02 10 11 12` — bits 2,3,5,6,7 are
never set, so on the bus the severity nibble only ever reads 0 or 1. Severities 2–6
(heavier limiting, contactor-open) are defined in the enum but were not exercised in
the logged conditions.

> **DBC action (proposed, not yet applied):** keep `BMSFaultSeverity` on the high
> nibble `[7:4]` of `BO_ 624` with its 0–6 VAL_ table (bus location confirmed by the
> 2026-07-26 inject test), and add `BMSRedLampReq` = bit 1. bit 4 is subsumed by the
> severity nibble, so no separate state-flag signal is needed there.

## Confirmed pathways

### BMS → RED
`0x270` B0 bit 1 set → GWM relays RED on `0x271` ~85 ms later. The BMS drives
**red only** — it never requests yellow in any log (every non-startup yellow has
`0x270` B0 = `0x00`). Seen in `defroster2` (t=136 s) and `frombonnydoon` (limp).

### DLCM absence → RED
During the ~30-minute DLCM-absent bootloader window of a reflash, `0x271` reads
**RED** continuously while the BMS is **not** requesting it (`0x270` B0 = `0x10`,
bit 1 clear). Confirmed on two independent flash captures:

| Capture | DLCM-absent window | Lamp during | BMS B0 |
|---|---|---|---|
| 2026-04-26 (`dlcm/dcan_flash_capture/`) | 29.5 min | RED (17,671 fr) | `0x10` |
| 2026-07-21 (`dlcm/dcan_flash_capture_20260721/`) | 30.0 min | RED (17,994 fr) | `0x10` |

OFF immediately before and after. So the GWM commands RED on DLCM
lost-communication, independent of the BMS. This is a **non-BMS red pathway** —
the DLCM being *gone* is the trigger, not any signal it sends.

### DLCM brake-switch fault → YELLOW (confirmed)
An intermittent brake-switch fault lights the yellow lamp: when the brake pedal
is pressed (hydraulic pressure rises on `0x208`) but the brake-switch bit fails
to assert, the DLCM flags yellow; the lamp clears when the switch catches up.

**Signature.** `BrakeSW` is triple-redundant — `0x212` B2.bit0, `0x315` B0.bit0,
`0x200` B1.bit0 — and normally engages ~40 ms *before* hydraulic pressure. In a
fault event all three stay **low** while `0x208` pressure builds, `0x271` goes
YELLOW (`0x00 → 0x05`, yellow + bit 2), and the moment the switch finally asserts
the lamp returns to OFF. BMS `0x270` bit 1 is clear throughout (not BMS-driven).

Reference event — `coda_20260723_130702` (2026-07-23 ~1pm), t≈502.5 s:

| window | brake pressure | switch high (3 copies) | lamp |
|---|---|---|---|
| pre-onset | rises 0 → 358 | 0–1 % | OFF |
| yellow pulse (2.7 s) | 350–419 | 75 % (switch asserts) | YELLOW |
| switch asserts fully | — | 100 % | clears to OFF |

**Causation (2×2 control, four multi-event logs, brake presses with t > 45 s):**

|                     | yellow | no yellow |
|---------------------|-------|----------|
| switch asserted     | 2\*   | 82       |
| switch NOT asserted | 6     | 11       |

82 normal presses assert the switch with no lamp (the control); yellow occurs
essentially only when the switch fails to assert during a real press. The two
"switch-asserted + yellow" cases are late-assertion recoveries (the switch comes
up *after* yellow has already fired and then clears it), not counter-examples.
The 11 switch-fail-without-lamp cases show the failure is necessary but not
always sufficient — the DLCM appears to need the pressure/switch mismatch to be
large or sustained enough, consistent with an intermittent fault.

**Recurrence.** The signature appears in ~12 android sessions from 2026-03 to
2026-07-23 (~15+ events) — a persistent intermittent fault, not a one-off. A
prefilter for `0x271` B0 = `0x05` (yellow + bit 2) plus the pressure-up /
switch-low test finds them; see `artifacts/fault-encoding/brake_yellow_scan.py`,
`brake_switch_causation.py`.

**Open:** which of the three redundant `BrakeSW` copies the DLCM actually
arbitrates on, and the exact mismatch magnitude/duration threshold that lights
the lamp (distinguishing the yellow cases from the switch-fail-no-lamp cases).

### Startup lamp test (excluded throughout)
Key-on runs a lamp-test sequence: `0x270` B0 `0x01`/`0x02` and `0x271` yellow/red
pulses in the first few seconds. These are test patterns, not faults, and are
excluded from all pathway analysis above.

## Notes on modules that do NOT drive the lamp

- **IPK `0x491`** — `IPK_FaultLamps` is constant per car (2 main car, 3 parts
  car) and never moves mid-drive even when the lamp goes red. A key-on latch /
  status report, not the display driver. (`0x491` B1–B2 is the odometer — a
  monotonic count, ruled out as a lamp signal.)
- **Parts car** — holds yellow continuously in its log; DTC pull shows faults in
  four modules at once (ABS C102B/C2202, Airbag B1382/B2505, DLCM U0110/C2100,
  HVAC B111D/B112D), so its yellow is not attributable to a single source. Per
  the owner it is functional and several codes stem from leaving the 12 V
  disconnected between uses. Not a clean test case.

## Open items

1. Which of the three redundant `BrakeSW` copies the DLCM arbitrates on, and the
   mismatch magnitude/duration threshold that lights the yellow lamp (separating
   the switch-fail-with-yellow cases from switch-fail-without-lamp).
2. ~~`0x270` B0 bit 4 role~~ — **RESOLVED 2026-07-26.** bit 4 is the LSB of the
   `BMSFaultSeverity` high nibble `[7:4]` (CODACAN inject test), not a standalone
   state flag. The high-SoC association is incidental.
3. `0x271` B0 bit 2 role (recurring pulse across drives; not a lamp test; set
   during the brake-switch yellow, so possibly a DLCM-fault marker).
4. Whether other modules (ABS, airbag, HVAC) reach the lamp via `0x271` the way
   the DLCM does — untested; the parts car cannot isolate them.
