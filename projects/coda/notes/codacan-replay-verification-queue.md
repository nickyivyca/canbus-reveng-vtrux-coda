# CODACAN Replay Verification Queue

*Created 2026-07-24. A consolidated, deduplicated list of outstanding Coda signal
items that a CODACAN bench replay session could ground-truth. Compiled by sweeping
all `projects/coda/notes/` investigations (not just the decode-notes), so the queue
covers open hypotheses from charging, battery, thermal, driver-input, traction, fault,
and cross-car investigations as well as the CODACAN decode phases.*

This is a **verification worklist**, not a findings file. Nothing here is a new
conclusion — every row restates an already-documented open item and names the replay
that would resolve it. Results get written back into the source notes only after
review, per the notes gate.

**Method reference:** `codacan-signal-decode-notes.md` (bench setup, replay commands,
sweep/inject/solo/drop workflow). Machine-readable queue for the autonomous runner:
`notes/artifacts/cowork-results/sweep_queue.json`. Runner: `tools/codacan_autosweep.py`.

Legend: `sweep` = byte sweep · `inject` = crafted frame · `solo`/`drop` = ID presence ·
**[P1]** = already priority-flagged in decode-notes · **[NEW]** = surfaced from another
investigation. "Tab" = CODACAN tab where the ground-truth field is read.

---

## BMS tab

| ID | Byte(s) | Open question | Method | Src |
|----|---------|---------------|--------|-----|
| 0x378 | B2 | **BMSmode enum (flagship).** Catalog every value: 0xD2 drive / 0xA9 charge (normal) vs 0xF2-0xF8 (Car 2's + parts car) vs 0xEA (thermal log). One sweep closes an item flagged in 4 notes. | `sweep` B2 0x00-0xFF | projects/coda/README.md, othercars, thermal-behavior, decode-notes [P1] |
| 0x378 | B3-B7 | Never swept. Incl. B6 = DC-link voltage (~19.5 V/LSB?), B0 = HV system mode. | `sweep` bytes 3-7, driving log | decode-notes 5c, driving-sequence [NEW] |
| 0x275 | B0 | Drives BattSentDischargeLimit and/or MotorDriveLimit? (both read 336 A together). | `inject` distinct B0 | chargepoint [NEW] |
| 0x275 | B2 | Drops ~4 at limp - pack V / temp / scaled SoC? | `sweep` B2 | bonnydoon, artifacts [NEW] |
| 0x275 | B3 | Identity/scale unknown. | `sweep`/`inject` B3 | chargepoint, artifacts [NEW] |
| 0x275 | B4 | Binary flag set at startup - HV active / drive ready? | `sweep` B4 0/1 | bonnydoon, artifacts [NEW] |
| 0x275 | B5 | Likely BattSentHVACLimits or 2nd current limit (drops ~30% at limp). | `inject`/`sweep` B5 | bonnydoon, artifacts [NEW] |
| 0x275 | B6 | Steps 0->4->0xC - status/limits-active byte? | `sweep` B6 | driving-sequence [NEW] |
| 0x275 | B7 | Constant 0xDD - does any BMS field respond? | `inject` values | decode-notes [P1] |
| 0x270 | B0 | **Fault code-vs-severity split unreconciled**: nibble (Severity/Code) vs per-bit (bit1=red lamp, bit4=state, bit0=key-on). Also bit-4 role. | `inject` 00/01/02/10/11/12, read BMS 2 | decode-notes, fault-encoding, fault-light [P1] |
| 0x270 | B6 | State/mode nibble (ramps 0x10->0x41; fixed 0x40 parts car). | `sweep` B6 | othercars [NEW] |
| 0x2C1 | B1/B3/B5 | DrivingRange scale/offset (single cal point). Plus parts-car 0xAA-0xAC (sentinel?), Car 2's 0x68-0x69 (beyond 0-99 max). | `sweep`/`inject` | decode-notes, projects/coda/README.md, othercars [P1] |
| 0x383 | B4 | 0x66-0x8A, inverse to SoC - BattSentChargeLimit or thermal limit? | `inject`/`sweep` B4 | charging-analysis [NEW] |
| 0x383 | B0-B1 | Boolean flag bit positions: HVBattCharging, ChrgPortOpen, ChargeCableConnected. | `sweep` B0-B1 | decode-notes [P1] |
| 0x390 | B0 | Status enum 0x8D->0x8E->0x8F (thermal/degradation stage?); B1/B3/B4 roles. | `sweep` | bonnydoon, charging-analysis, artifacts [NEW] |
| 0x392 | all | Undecoded; wide ranges suggest fault/status - "may hold the code that triggers limit reduction." | `solo`/`sweep` | bonnydoon [NEW] |
| 0x620 | all | Cluster unknown; triggers BMS indicator. | `sweep` 8-byte coarse | decode-notes [P1] |
| 0x72A | all | Cluster unknown; triggers BMS indicator. | `sweep` 8-byte coarse | decode-notes [P1] |
| 0x2C2 | all | B CAN 10 Hz - possible pack temperature. | `solo`/`sweep` | bonnydoon [NEW] |
| (field->ID) | - | Map each displayed BMS-tab field to its source ID without firmware. | `solo`/`drop` per candidate | charging-analysis [NEW] |

## Charging / CH M/S tab

| ID | Byte(s) | Open question | Method | Src |
|----|---------|---------------|--------|-----|
| 0x050 | B4-B5 | Does non-baseline collapse Main Current (frame-validation/counter)? | `inject` variants vs baseline `00 dc 0f f7 00 01 3e 01` | decode-notes [P1] |
| 0x050 | B5-B6 | EVSEMaxCurrent field width/scale (only 256-511 raw seen; predict B5=0 -> 4.4 A). | `inject` crafted raw | charging-analysis [NEW] |
| 0x274 | B6-B7 | 0x35-0x39 - temperature or phase angle? | `sweep` B6-B7 | charging-analysis [NEW] |
| 0x617 | B1/B3/B4/B6 | Partial; ChrgrSys* field mapping + scale (/32?) unconfirmed. | `sweep` each byte | charging-analysis [NEW] |
| 0x615 | B2-B6 | Uncharacterised beyond B0/B5. | `sweep` | charging-analysis [NEW] |

## DCDC tab

| ID | Byte(s) | Open question | Method | Src |
|----|---------|---------------|--------|-----|
| 0x1D5 | B6 | Likely 12V output voltage. | `sweep` B6 | charging-analysis [NEW] |
| 0x48A | B4/B5 | B4 /4 = rail voltage; B5 likely 12V terminal voltage. | `sweep` | charging-analysis [NEW] |
| 0x1D7 | B0/B1 | B0 on/off, B1 output voltage? | `sweep` | driving-sequence [NEW] |
| 0x315 | B5 | Confirm Batt_Volt 0.1 V scale vs DCDC 14V-monitor. | `sweep` B5 | driver-inputs [NEW] |

## HVAC tab

| ID | Byte(s) | Open question | Method | Src |
|----|---------|---------------|--------|-----|
| 0x410 | B0 | HVAC boolean bit positions (FaultRed/FaultYellow/KeepWakeNetworkHVAC); maybe sweep artefacts. | `sweep` then `inject` to confirm | decode-notes, projects/coda/README.md [P1] |
| 0x276 | B2 | **HVACHVDisableStatus enum** full catalog: 0x01/0x05/0x09/0x0D/0x11/0x21. Specifically 0x09 vs 0x21 (both "cabin heat"?) and 0x0D ("pack heater running"?). | `inject` each value | decode-notes, thermal-behavior, thermal-indicator [P1] |
| 0x276 | B0/B3/B4 | Temp/energy metrics (uncharacterized). | `sweep` | driver-inputs [NEW] |
| 0x276 | B1 | Mode knob: face/feet/defog. | `sweep` low nibble | driver-inputs [NEW] |
| 0x391 | B0 | 0xFC<->0xC1 - humidity (implausible %) vs status bitfield. | `inject` B0 | thermal-behavior [NEW] |

## Driveline tab

| ID | Byte(s) | Open question | Method | Src |
|----|---------|---------------|--------|-----|
| 0x241 | B0-B7 | **Per-byte Rotor/Stator/IGBT assignment** (~6 live channels, not 3); confirm -40C offset; B4=0x00 role. | `sweep` all 8 bytes, driving log | decode-notes, artifacts, traction [P1] |
| 0x212 | B5 | Torque request scale/units (role confirmed); 9-bit via B4[0]? | `inject` known values | traction-control [NEW] |
| 0x418 | B4 | Gear-status/park-lock enum (P=0xDD,R=0xBB,N=0x00,D=0x11,intermediates). | `sweep` B4 | driver-inputs [NEW] |
| 0x308 | B0 | Park position (0x20 in / 0x40 out). D-CAN exclusive - confirm CODACAN decodes it. | `solo`/`sweep` B0 | driver-inputs [NEW] |

## IPK tab

| ID | Byte(s) | Open question | Method | Src |
|----|---------|---------------|--------|-----|
| 0x491/0x273 | all | ODO byte position/encoding + lighting bit positions. | `sweep` 8-byte coarse | decode-notes [P1] |
| 0x491 | B0/B1 | Warning-lamp bit->lamp assignment (parts-car bits 0/1/2 = ABS/Airbag/HVAC; B1 "OK" bits). | single-bit `sweep` | othercars [NEW] |
| 0x491 | B3 | Reconcile headlight-mode bitfield (firm) vs "drive-readiness" (old). | `sweep` B3 | driving-sequence vs driver-inputs [NEW] |
| 0x492 | - | Distinct IPK channel or pure echo of 0x491? | `solo` | othercars [NEW] |
| 0x271 | B0 bit2 | Role open (set during brake-switch yellow; DLCM-fault marker?). | `inject` 0x04/0x05 vs clear | fault-light [NEW] |
| (gauges) | - | Source of IPK SoC%/speed (0x383/0x275 rebroadcast or dedicated frame?). | `inject` 0x383 SoC, watch gauge | decode-notes [P1] |

## Overview / power-state tab

| ID | Byte(s) | Open question | Method | Src |
|----|---------|---------------|--------|-----|
| 0x240 | B0 | System/power state (0x11 key-on HV-off, 0x01 Ready HV-on). | `inject` | driver-inputs, driving-sequence [NEW] |
| 0x278 | B1 bit6 | HV/drive-ready flag - "confirm." | `inject` with/without 0x40 | driver-inputs [NEW] |
| 0x248/0x370 | B4/B1, B0/B3 | Ignition/power sub-state hypotheses. | `sweep`, watch Overview | driving-sequence [NEW] |

---

## Flag - CODACAN likely can't decode (no ESC presence indicator)

Run a quick `solo` first to confirm decodability before investing sweep time:
0x312 (DLCM torque/limits -- the "ESC speed_inv/fwd" label is withdrawn 2026-09-24; the negative CODACAN results here are unaffected), 0x300 (M_ESP torque limits + parity), 0x200 / 0x208
(wheel-speed & brake-pressure scale). 0x330 Long_Accel needs a hard-braking
timeseries, not a replay. 0x248 B6 (dimming), 0x536 / 0x600 (unidentified) have no
obvious tab. 0x215 - hypothesis invalidated, no actionable replay.

## Not replay items (need real stimulus - listed for completeness)

- RCU/TPMS keepalive: trip the immobilizer to force RCU broadcast (a capture task).
- battery-degradation / cell-index open items: need a real drive to UV cutoff and
  C CAN per-cell logging; CODACAN does not display raw cell frames.

---

# Autonomous Run 1 - Results (2026-07-24)

Executed by `tools/codacan_autosweep.py` against `sweep_queue_full.json` (86 experiments,
`--restart first`, Kvaser TX -> CODACAN v1.2.1). Raw output under
`notes/artifacts/cowork-results/autosweep/<name>/`; responder analysis via
`notes/artifacts/cowork-results/analyze_autosweep.py`.

**These are empirical replay observations, NOT yet promoted to `projects/coda/README.md` or the DBCs.**
Correlation `r` is CODACAN-field-value vs swept-byte-input across the sweep. Scale/offset
values still need a linear fit from the per-step JSON before any DBC entry.

## Resolved (clean responder)

| ID / byte | Observation | Confidence |
|-----------|-------------|-----------|
| 0x241 B1/B2/B3 | **B1 = IGBT, B2 = Rotor, B3 = Stator** temp (r ~ +0.96 each); B0, B4-B7 drive no temp field | High - resolves per-byte assignment |
| 0x491 B0 / B3 | **B3 = lighting** (Side/Low/High Beam Active all toggle) - High. **B0 = "ODO" is CONTESTED** (projects/coda/README.md says 0x491 B0/B1 = IPK fault-lamp latch; othercars says B2 = ODO) - see Run 2 cross-check, re-sweep queued | B3 High; B0 contested |
| 0x270 B0 | **BMS Fault Severity = linear 0-15, r = +1.00**; BMS Fault Status shows 6 named enum strings (Information Only -> All HV Components Should Be Disabled) | High - severity is a direct value, not a nibble/bit split as the DBC assumed |
| 0x410 B0 | HVAC FaultRed, FaultYellow, KeepWakeNetworkHVAC **all toggle** with B0 -> genuine B0 booleans, not sweep artefacts | High |
| 0x276 B0/B1/B3/B4 | B0 = PTC Power, B1 = ACCM Power, B3 = CIntTempRadOutlet, B4 = CIntTempPTCOutlet (each drives its named field) | High (roles); scale TBD |
| 0x276 B2 | Drives HVAC HV Component Disable Status enum ("All HV Components disabled" / "not disable" / ...) | Medium - full enum catalog still pending (see Run 2) |
| 0x391 B0 | Drives **UnderHoodHumidity** (0-480, r = +0.99) -> humidity (x2 %), **not** a status bitfield | High - resolves the humidity-vs-bitfield question |
| 0x2C1 B1/B3/B5 | Drive Expected / Max / Min driving-range, linear 0-240, r = +0.96 -> scale now fittable | High (roles); exact scale needs fit |
| 0x275 B2/B3, B4/B5, B6, B7 | B2/B3 -> PackCurrent, B4/B5 -> PackVoltage, B6 -> BattSentHVACLimits (r = +0.98), **B7 inert** (0xDD dead byte) | High - resolves bonnydoon "unknown byte" items as already-known signals |
| 0x212 B5 | DLCM Torque Request, r = +1.00 (signed; -116..-56 over the swept range) | High |
| 0x383 B0/B1 | Both drive SocMaster (SoC MSB/LSB, r ~ +1.00); B4 inert | High |
| 0x271 B0 | Drives Vehicle Faults Lamp Req (OFF/RED/YELLOW) + VehFaultSeverity | High (bit-2 role still needs the fine reads) |
| 0x492 | Drives IPK ODO + Side/Low Beam -> a functional IPK channel (not a dead echo) | Medium |

## Negatives (byte drives no field on the target tab)

0x050 B4/B5 (Charging) · 0x274 B6/B7 · 0x615 B2-B6 · 0x617 B1/B3/B4/B6 · 0x390 B0/B1/B3/B4 ·
0x378 B3-B7 · **0x620 all 8 bytes** (triggers BMS presence but decodes to no BMS field) ·
0x240 B0 (Overview). These bytes do not map to a displayed CODACAN field.

## Inconclusive - re-run in Run 2

| Item | Why | Run 2 fix |
|------|-----|-----------|
| 0x378 B2 BMSmode (flagship) | enum is a *text* box; step-1 OCR returned 251 garbled strings | inject the known values (0xD2/0xA9/0xEA/0xF2/0xF8 + refs) with screenshots |
| DCDC 0x1D5 B6 / 0x48A B4-B5 / 0x1D7 B0-B1 / 0x315 B5 | responders were low-r DtcIndex/thermistor noise (sweeping arbitrary bytes tripped DTC-index fields) | targeted re-run / inspect per-step |
| 0x418 B4 gear / 0x308 B0 park | buried in driving-log motion noise (Torque/Speed/Steering all live) | sweep on the stationary key-on slice (0-50 s) |
| 0x312 / 0x300 / 0x330 ESC probes | identical fully-populated Driveline tabs = stale display from `--restart first` | re-run solo with `--restart each` |

---

# Autonomous Run 2 (cleanup) + Cross-check vs notes (2026-07-26)

Run 2 (`sweep_queue_cleanup.json`, `--restart each`, output under
`autosweep_cleanup/`) re-ran the 4 inconclusive items. Findings were then
cross-checked against the vehicle notes by category (6 review passes). Still
empirical / **not promoted** to `projects/coda/README.md` or the DBCs. The BorgWarner **0x308**
park result is recorded in the shared `notes/borgwarner.md` (cross-vehicle with
Vtrux), not here.

## Run 2 outcomes

- **0x378 B2 BMSmode**: CODACAN displays the **raw decimal value** of B2 (0xD2->`210`, 0xA9->`169`, 0xEA->`234`, 0xF2->`242`; `Invalid` at 0), confirmed on screenshot. It is a numeric echo, NOT a decoded enum -> **CODACAN cannot resolve the meaning** of the cross-car 0xEA/0xF2/0xF8 values. Flagship closed as "not CODACAN-answerable."
- **0x330 -> Long_Accel**: decodes (solo lit Long_Accel). **0x312 / 0x300**: not decoded (clean-baseline solo left the Driveline tab blank; the Run-1 "populated" reading was stale display). Confirms no-ESC-indicator for 0x312/0x300.
- **Gear 0x418 B4**: no CODACAN Driveline field responds; the tab has no PRND field -> gear not CODACAN-surfaced. Log-derived gear enum (driver-inputs) stands.

## Cross-check verdicts (proposals, DBC/coda.md unchanged)

**Promotable (role-level, empirically re-confirmed):**
- 0x241 **B1=IGBT, B2=Rotor, B3=Stator** (confirms DLCM_glb order). Offset -40 C still needs a fit; firmware implies a 4th "Inverter" temp unaccounted; close the old "~6 channels" idea.
- 0x491 **B3 = headlight/lighting bitfield** (confirms driver-inputs; refutes driving-sequence "drive-readiness").
- 0x492 = **distinct functional IPK channel** (note-grade / BO_ stub).
- 0x391 **B0 = UnderHoodHumidity** -> resolves the thermal-behavior "humidity vs bitfield" doubt (humidity; high in-state values are sentinel).
- 0x276 **B0/B1/B3/B4** roles re-confirmed (kills the stale "B1 = mode knob" idea).
- 0x410 **B0 = 3 real booleans** (FaultRed/Yellow/KeepWake) - real, not artefacts; **bit positions still unknown -> CM_ only, no SG_**.
- 0x275 **B7 = dead byte** (0xDD) - drop DBC "possibly 4th current limit" note. B2/B3=PackCurrent, B4/B5=PackVoltage, B6=HVACLimits re-confirmed.
- 0x383 **B0/B1 = SoC** re-confirmed.
- 0x271 lamp req incl. **INVALID(3)** + six BMS fault-status strings (record as CM_).
- 0x620 8-byte scan complete -> no field (stays BO_ stub).

**Corrections / reconciliations flagged (do not edit those files yet):**
- **0x491 B0 = ODO is contested** (see Run-1 row above) - re-sweep B0/B1/B2.
- **0x212 B5 is NOT a signed uint8** - it is the low 8 bits of the confirmed 12-bit nibble-split (B4:B5); role re-confirmed, scale unconfirmed.
- **bonnydoon 0x275 labels superseded**: B2=PackCurrent MSB (not "pack V/temp"), B4=PackVoltage MSB (not "HV-active flag"), B5=PackVoltage LSB (not "HVACLimits" - that is B6).
- **0x383 B4** charge-limit/inverse-to-SoC hypothesis refuted (not a decoded field); reopen as "unexplained in-log varying byte."
- **charging-analysis vs DBC** (resolve DBC-favor): 0x1D5 B6 = Current_14V (not "12V voltage"); 0x48A B4/B5 = thermistors (not "12V rail /4").
- **0x2C1 units**: DBC says "mi", CODACAN ground-truth reads **km** - reconcile.
- **Stale prose**: fault-encoding/fault-light still describe the 0x270 nibble-split as present, but the DBC is already per-bit; projects/coda/README.md/decode-notes still list VehFaultSeverity/VehicleFault for 0x271 which the DBC dropped.

**"Negative != meaningless":** the charger negatives (0x050 EVSEMaxCurrent, 0x615 B5 total-AC-current, 0x274 fault flags) are **log-analysis results CODACAN never displayed** - NOT invalidated by a CODACAN negative.

## Reopened -> Run 3 (targeted)

| Item | Why Run-1/2 was insufficient | Run-3 method |
|------|------------------------------|--------------|
| 0x270 B0 severity | sweep can't tell whole-byte vs low-nibble + bit-4 role | inject 00/01/02/10/11/12, read BMS 2 (severity+status) + screenshots |
| 0x491 B0/B1/B2 ODO | B0=ODO contested vs B2=ODO | re-sweep B0,B1,B2 individually, read ODO + lighting |
| 0x390 B0/B1/B3/B4 | Run-1 watched BMS tab; the temps render on the **HVAC** tab | re-sweep watching HVAC tab (Front/Rear Inlet, Return Air, Allowed Cell Temp) |
| 0x315 B5 | Run-1 watched DCDC; 0x315 is D-CAN, Batt_Volt is on **Driveline** | re-sweep watching Driveline (Batt_Volt) |
| 0x276 B2 enum | text-OCR too noisy for a catalog | inject 0x01/05/09/0D/11/21, read Disable Status + screenshots |
| 0x2C1 scale | coarse; km/mi unresolved | finer B1 sweep + offline fit; unit = km (CODACAN ground-truth) |
| 0x617 fields | may render on another tab | solo probe, capture Charging + CH M/S + DCDC |

---

# Autonomous Run 3 - Results (2026-07-26)

Run 3 (`sweep_queue_run3.json`, `--restart each`, output under `autosweep_run3/`)
targeted the 7 reopened items with injects + correct-tab re-runs. Empirical; not
promoted. See the final Review section for promotion readiness.

## 0x270 B0 - fault severity RESOLVED (inject 00/01/02/10/11/12)

| B0 inject | BMS Fault Severity | BMS Fault Status string |
|-----------|--------------------|-------------------------|
| 0x00 / 0x01 / 0x02 | **0** | No Fault |
| 0x10 / 0x11 / 0x12 | **1** | Information Only, No Limiting |

**Severity = the high nibble B0[7:4]** (0-15; the Run-1 sweep's "linear 0-15" was the
high nibble tracking). The **low nibble does NOT drive CODACAN's BMS-2 severity/status**.
Reconciliation: the *severity nibble* (old DBC) and the *per-bit lamp* (current DBC)
are BOTH real but DIFFERENT fields - bit 1 (0x02) drives the RED dash lamp via **0x271**,
not via 0x270's CODACAN severity. Normal cars rest at 0x10 = severity 1 (benign
"Information Only"); a fault frame 0x12 adds bit1 -> RED via 0x271. Higher-severity
status strings (Limited Performance ... All HV Components Should Be Disabled) map to
high-nibble values 2-5 (from the Run-1 full sweep).

## 0x276 B2 - disable-status = low 2 bits (Run-1 fine-sweep catalog)

`HVAC HV Component Disable Status = B2[1:0]`, periodic every 4:

| B2 & 0x03 | String |
|-----------|--------|
| 0 | Invalid |
| 1 | All HV Components not disabled |
| 2 | All HV Components disabled |
| 3 | (enum "3", unnamed) |

The DBC's provisional decimal map (5=disabled, 8=not-disabled) is **wrong**. The Run-3
injects (01/05/09/0D/11/21 - all B2&3==1) correctly all read "not disabled". The
**0x09-vs-0x21 "mode" distinction is NOT this field** (both -> not-disabled) -> not
CODACAN-answerable; it is a separate axis CODACAN does not surface.

## 0x390 B0/B1/B3/B4 - CONFIRMED on the HVAC tab

Re-run watching HVAC (Run-1 watched BMS -> false negative). All four respond:
B0 -> Front Inlet Air Temp, B1 -> Rear Inlet AirTemp, B3 -> Return Air Temp Drv,
B4 -> Allowed Cell Temp Max (range consistent with raw-128 degC). Matches decode-notes
Phase-5 assignment; the Run-1 negative is void (wrong tab).

## 0x315 B5 - Batt_Volt, ~x0.1 V, on the Driveline tab

Re-run watching Driveline (0x315 is D-CAN). Batt_Volt tracks B5 at ~0.1 V/count
(48->4.8, 64->6.4, 80->8.0; occasional OCR outliers). Confirms decode-notes/DBC.

## 0x2C1 B1 - range scale fit

Expected = **1.051 x raw - 15.60** (n=31), **unit km** (CODACAN ground-truth) -> the
DBC "mi" unit is wrong. Max/Min share the same form (per Run-1). Refines the provisional
~1.1 x raw - 19.

## 0x491 ODO - B0/B1 yes, B2 NO

Per-byte re-sweep watching Primary ODO:
- **B0**: large monotonic steps (~0.168 km per count) -> ODO **high byte**.
- **B1**: small monotonic steps (~0.000655 km per count) -> ODO **next byte** (B0 = 256 x B1 weight -> 16-bit BE B0:B1 at least).
- **B2**: ODO **dead-constant** (1.401821 for all values) -> **B2 is NOT part of ODO**.

Corrects Run-1 ("B0=ODO" - it's the MSB, not the whole field) and **refutes othercars'
"B2=ODO"**. Still conflicts with projects/coda/README.md `IPK_FaultLamps` (B0/B1 latch). The ODO scale
implies too small a range for a real odometer over just B0:B1, so the field likely
extends into higher bytes - **targeted B4-B7 span sweep launched** (`sweep_queue_491span.json`).
Note: CODACAN has no fault-lamp *field* for 0x491, so the ODO-vs-fault-lamp conflict must
be settled by a **log check** (do B0/B1 change across captures = ODO, or stay fixed =
lamp latch?) - a separate offline task, not a CODACAN sweep.

**Span sweep result (`autosweep_491span/`):** B4/B5/B6/B7 all leave the CODACAN ODO
display dead-constant - CODACAN's "Primary ODO" field is a mis-scaled 16-bit slot fed only
by B0:B1, which is why it shows a nonsense ~1.4 km. **This does NOT mean 0x491 lacks the odo
- see the verified log analysis below, which OVERTURNS the fault-lamp reading.**

## ODO VERIFIED by log analysis (2026-07-26) - 0x491 B0:B1:B2 IS the odometer

`odo_verify.py` searched all broadcast IDs for a near-constant field scaling with the known
mileage (main ~34k mi, parts ~62k mi). Unambiguous hit: **0x491 B0:B1:B2 as a 24-bit
big-endian value x 0.1 km/count** matches BOTH anchors to <0.2%:

| Car | 0x491 B0 B1 B2 | raw 24-bit | km | mi |
|-----|----------------|-----------|-----|-----|
| main | `08 5B 57` | 547,673 | 54,767 | ~34,030 |
| parts | `0F 41 E9` | 999,913 | 99,991 | ~62,130 |
| Car 2 | `0F 0D ~0F` | 986,383 | 98,638 | **~61,290** |

**This overturns the fault-lamp interpretation.** Clincher: Car 2 B0=`0x0F` == parts B0=`0x0F`
despite entirely different fault sets, and both are ~61-62k mi - so B0 is the odometer high
byte, not a fault-lamp latch. B2 is the fine (0.1 km) byte that ticks during a drive (which
is why othercars saw B0/B1 "fixed" - the odo barely moves in one capture - and why B2
"varies"). Corrections required (pending approval, NOT yet applied):
- **projects/coda/README.md** 0x491 `IPK_FaultLamps` is WRONG -> 0x491 B0:B1:B2 = Primary ODO (24-bit BE, 0.1 km/count).
- **othercars-comparison.md** 0x491 B0/B1 "warning-lamp latch" + "3 fault bits in parts car" is WRONG (it is higher mileage). Also its "B2 = ODO" and 0x273-ODO ideas are wrong.
- Car 2's single logged bus = **B CAN** (native B-CAN IDs + gateway-passthrough D-CAN IDs, no D-CAN-exclusives 0x308/0x312/0x325/0x330/0x580, no C-CAN cells).
- CODACAN's own "Primary ODO" field is a mis-scaled partial decode (B0:B1 only) - a CODACAN display bug; the true odo needs B0:B1:B2 x 0.1 km.

## 0x617 - Bus V/I not displayed

Solo 0x617 lit no real field on Charging / CH M/S / DCDC (only OCR-noise "8.0"). The DBC
`ChrgrSysBusVoltage` / `ChrgrSysBusCurrent` `SG_` entries are not CODACAN-confirmed ->
downgrade to a `BO_` stub per the confirmed-signals-only policy.

---

# Review - Promotion Readiness (all runs, 2026-07-26)

Consolidated state of play across Runs 1-3 + the six cross-check reviews. **Nothing here
is in `projects/coda/README.md` or the DBCs yet** - this section is the staging list for your approval.

## Ready to promote to projects/coda/README.md / DBC (confirmed role; scale caveats noted)

| Signal | Confirmed finding | DBC action |
|--------|-------------------|-----------|
| 0x241 B1/B2/B3 | IGBT / Rotor / Stator temps (DLCM_glb order) | SG_ with offset -40 C flagged unconfirmed (needs fit); note 4th "Inverter" temp unaccounted |
| 0x270 B0[7:4] | BMS Fault Severity 0-15 -> named status strings; low-nibble bit1 = RED lamp via 0x271 | reconcile 0x270: severity=high nibble + keep bit1 red-lamp; add CM_ with the status-string map |
| 0x276 B2[1:0] | HV Disable Status enum {0 Invalid,1 not-disabled,2 disabled,3 -} | fix DBC decimal map -> low-2-bit enum |
| 0x276 B0/B1/B3/B4 | PTC Power / ACCM Power / RadOutlet / PTCOutlet | already in DBC - raise to confirmed |
| 0x390 B0/B1/B3/B4 | Front/Rear Inlet, Return Air Drv, Allowed Cell Temp Max | already in DBC - confirmed (void the Run-1 negative) |
| 0x391 B0 | UnderHoodHumidity (x2 %) | confirmed; close thermal-behavior bitfield doubt |
| 0x410 B0 | 3 real booleans (FaultRed/Yellow/KeepWake) | CM_ only (bit positions still unknown - no SG_) |
| 0x491 B3 | headlight/lighting bitfield | add SG_/CM_; refute driving-sequence drive-readiness |
| 0x492 | distinct functional IPK channel | BO_ stub + note |
| 0x275 B7 | dead byte (0xDD) | drop "4th current limit" speculation |
| 0x315 B5 | Batt_Volt ~0.1 V | confirmed |
| 0x2C1 B1/B3/B5 | DrivingRange Exp/Max/Min, ~1.05 x raw - 15.6, **km** | fit scale; change unit mi -> km |
| 0x330 | Long_Accel (CODACAN-decoded) | confirmed decodable |
| 0x212 B5 | Torque Request (low 8 bits of 12-bit nibble-split B4:B5) | keep nibble-split; do NOT write "signed uint8"; scale still unconfirmed |
| 0x620 | 8-byte scan complete - no decoded field | stays BO_ stub |

## Corrections to make in existing notes (superseded / wrong)

- bonnydoon 0x275: B2=PackCurrent MSB, B4=PackVoltage MSB, B5=PackVoltage LSB, B6=HVACLimits (old "HV-active flag"/"HVACLimits at B5" labels wrong).
- charging-analysis: 0x1D5 B6 = Current_14V (not "12V voltage"); 0x48A B4/B5 = thermistors (not "12V rail /4").
- 0x383 B4: charge-limit hypothesis refuted (not a decoded field) -> "unexplained in-log varying byte".
- fault-encoding / fault-light prose: 0x270 nibble-split described as present, but DBC is per-bit + severity nibble; update.
- projects/coda/README.md / decode-notes still list VehFaultSeverity/VehicleFault for 0x271 which the DBC dropped -> reconcile.
- othercars 0x491 "B2 = ODO" is refuted (B2 not ODO).
- 0x617 ChrgrSysBusVoltage/Current SG_ -> downgrade to BO_ stub.

## Open / needs more work

- **0x491 ODO** - RESOLVED by log analysis (see "ODO VERIFIED" section): **0x491 B0:B1:B2 = Primary ODO** (24-bit BE, 0.1 km/count), matched across 3 cars (main ~34.0k, parts ~62.1k, Car 2 ~61.3k mi). **This overturns the fault-lamp reading** - projects/coda/README.md `IPK_FaultLamps` and othercars 0x491 B0/B1 "warning lamps" are WRONG and need correcting.
- 0x241 -40 C offset fit; the firmware 4th "Inverter" temp.
- 0x270 higher-severity string map (levels 2-5) from Run-1 per-step JSON.

## Not CODACAN-answerable (close-outs)

- **BMSmode (0x378 B2)**: CODACAN echoes the raw byte value - meaning of cross-car 0xEA/0xF2/0xF8 must come from firmware, not CODACAN.
- **0x276 B2 mode 0x09-vs-0x21**: CODACAN's B2 field only decodes the low-2-bit disable status; the mode axis is not surfaced.
- **0x312 / 0x300**: not decoded by CODACAN (no ESC field).
- **0x418 gear / 0x308 park**: no PRND field; gear/park not CODACAN-surfaced (0x308 recorded in `notes/borgwarner.md`). Log-derived entries stand.
- charger log-analysis results (0x050 EVSEMaxCurrent, 0x615 B5 AC-current, 0x274 flags): CODACAN has no field - negatives do not invalidate them.
</content>
</invoke>
