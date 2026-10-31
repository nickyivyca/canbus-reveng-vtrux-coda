# Via Vtrux EREV Conversion — CAN Bus Reverse Engineering

## Vehicle Overview

Vtrux is an EREV (extended range electric vehicle AKA series hybrid) conversion of a 2014 Silverado 1500. Express vans were also converted, but this project has only been tested on the pickup truck - likely most learnings crosses over to the vans. The conversion features:
- **Battery**: A123 Systems LFP pack, 116 cells in series, built out of 4 A123 AMP20 26s3p modules and one 12S3P module in series. Nominal ~383V (3.30 V/cell). Range: ~360V (10% SoC) to ~422V (full).
- **Power electronics coolant pump**: EMP WP29 C20 CAN controlled water pump for power electronics cooling loop.
- **Bel Fuse bidirectional charger/inverter**: Provides AC→DC charging from J1772 inlet; also provides 240V split-phase AC output when the export power key switch is on. Water cooled by PE loop.
- **Bel Fuse DCDC converter**: HV→12V conversion for vehicle 12V loads. Water cooled by PE loop.
- **AC compressor**: Sanden MI-EV36-BNKx HV electric compressor (EAC — Electric AC-Compressor). J1939 SA=0x47; broadcasts on PT bus as 0x0868A047 (EAC_STATUS1) and 0x0870A047 (EAC_STATUS2). See `notes/hvac-investigation.md`.
- **Cabin Heat**: Uses Eberspacher HV PTC heater for cabin heat when in EV mode, uses engine heat when the generator is running. 
- **Powertrain:** The original GM transmission has been replaced by 2 Remy HVH250-115D motors controlled by Dana TM4 CO150 inverters, one mounted directly to the engine to turn it into a generator and the other mounted to a BorgWarner single speed longitudinal transmission with electrically controlled parking pin (same family as Coda) to the original GM transfer case and 4wd system for traction. Both motors are dry sump ATF (Dexron VI) cooled with independent relay-controlled pumps but sharing an oil reservoir. Inverters are water cooled by PE loop.
- **Vehicle controller**: Woodward Motohawk ECM-5554-112-0904-C/F running NewEagle software (the Via Motors VCM). Acts as EV controller and GM CAN gateway/filter.
- **Electric vacuum boost pump:**: Since engine is not always running, electric vacuum boost pump is added for the brakes.
- **Shifter position box:** Converts physical shift cable lever position (that would have gone to original transmission) to electrical signal.
- **Instrument panel cluster**: Engine tachometer replaced with power dial, top dials now indicate generator power, battery SoC, fuel gauge, system temperature (does not indicate oil cooled system overheat, likely indicates something on the PE loop). Original center display with GM diagnostics retained.
- **Original GM system:** Left mostly intact with the following changes:
  - Exhaust rerouted around battery
  - Fuel tank shrunk
  - Original belt driven AC compressor and alternator removed

---

## Vtrux-Specific Tools

Vehicle-specific analysis scripts live in `projects/vtrux/tools/`. **Check here before writing custom scripts for Vtrux analysis tasks.** See `projects/vtrux/tools/README.md` for full usage.

| Tool | Purpose |
|------|---------|
| `diagnose_vtrux.py` | General-purpose Vtrux diagnostic tool — decodes all known fault and status signals from a PT-bus log; produces initial/final state snapshots, chronological event timeline with fault-tagged transitions, and fault summary |
| `vtrux_charge_failure_analysis.py` | Main charge failure analyzer — decodes Bel charger state machine, BMS signals, J1772 health, failure classification |
| `analyze_session.py` | Single-session charger fault event analyzer with windowed V/I context |
| `analyze_failed_charges.py` | Batch wrapper: discovers all sessions in a directory and runs `analyze_session` on each |
| `extract_obd.py` | Extracts and decodes OBD-II and J1939 DM diagnostic reads from a recorded CAN log |
| `vtrux_dtc_interrogation.py` | Active DTC interrogation — identifies buses, sends OBD-II DTC requests live, decodes responses in real time |

---

## CAN Bus Architecture

The Vtrux has three CAN buses. **Bus channel numbers in log files are arbitrary** (dongle insertion order varies per session). Always identify buses by message content using the anchor IDs below.

### Bus Identification — Anchor IDs

| Bus | Exclusive IDs (definitively identifies this bus) |
|-----|--------------------------------------------------|
| **Powertrain** | **0x051** @ ~100 Hz **plus 21 ids:** 0x592, 0x594, 0x596, 0x597, 0x599, 0x5A0, 0x5A2, 0x639, 0x63A, 0x63C, 0x63D, 0x63F, 0x640, 0x644–0x64B. All exclusive on every training channel (`notes/artifacts/anchor_discovery_audit.py`, `notes/artifacts/pt_anchor_crosscheck.py`, 2026-10-30). The old ranges 0x592–0x5A2 / 0x639–0x64B list ids that never occur (0x593, 0x59B–0x59F, 0x5A1, 0x63B, 0x63E, 0x641–0x643). Extended 0x18FF??B3 is exclusive but in only 94 % of sessions, and 0x18FF??C0 appears only while charging; neither is used |
| **Vehicle** | 0x1E5, 0x500, 0x514, 0x52A–0x530, 0x778, 0x780, 0x785, 0x788 |
| **OBD** | 0x040–0x044 (TRAC MCU — exclusive to OBD, never bridged to Vehicle bus) |

**Quick check:** If a bus has 0x051, it's Powertrain (canbench's resolver needs 2 of the powertrain ids, so 0x051 alone names nothing). If it has 0x1E5 and 0x500, it's Vehicle. If it has 0x040–0x044, it's OBD. **Secondary check (ID count):** Vehicle has more unique IDs (~90–93) than OBD (~74–79).

**Note:** Do not use 0x441–0x464 as OBD anchors — this range includes GMLAN IDs (e.g. 0x451 = `Gateway_LS_General_Information`) that the VCM bridges to the Vehicle bus, causing false OBD identification on some logs.

### DBC Files

All canonical DBC files are at this directory level.

| File | Contents | Status |
|------|----------|--------|
| `epri-obd-bus.dbc` | OBD bus signals logged by the EPRI iPhone app — decoded from Ghidra decompile of the app binary | Byte layouts confirmed from decompile; **most signals log-validated**. Two EPRI errors documented: 0x0451 misattributed to TRAC MCU (is GMLAN), 0x0459 wrong ID for TRAC thermal (actual: 0x044A). See `notes/epri-verification.md`. |
| `epri-pt-bus.dbc` | Powertrain bus signals logged by the EPRI iPhone app — decoded from Ghidra decompile of the app binary | Byte layouts confirmed from decompile; **major signals log-validated** (pack current/voltage/SoC, CCL/DCL, cell voltage/temp, GENE RPM/torque/thermal, GENE HV bus, DCDC all channels, Bel charger, BorgWarner park state, brake pedal). Remaining decompile-only entries are mostly 1-bit status flags never deliberately toggled. One EPRI defect documented: 0x0598 power bundle decoded as signed int16 when the wire format is offset-binary — `BO_ 1432` stubbed, corrected signals in `vtrux-powertrain-experimental.dbc`. See `notes/epri-verification.md`. |
| `vtrux-powertrain-experimental.dbc` | Powertrain bus — signals confirmed through our own log analysis, correlation tests, and interlock/disconnect experiments. **Only add signals here that are NOT already decoded in an EPRI DBC.** See rule below. | In progress |
| `vtrux-obd-experimental.dbc` | OBD bus — signals confirmed through our own log analysis that are NOT in `epri-obd-bus.dbc`. Same rules as the PT counterpart (see above). | In progress |
| `BelInverter-v2.dbc` | Bel charger/inverter — merged from previous DBC + EPRI Ghidra decompile. Fixes: extended ID bit-31, `overallTemperaturePercent` 8-bit, voltage signedness in `hvBatteryAndCharger`. See `notes/belinverter-dbc-merge.md`. | Current |
| `GMW8762_PPEI_GMLAN.dbc` | GM PPEI GMLAN standard — 51 messages, 586 signals extracted from spec PDF | Complete; use for decoding both GM buses |
| `vtrux-interposer-diag.dbc` | **The charge interposer board's own self-telemetry**, not a truck ECU. `0x7F4-0x7F7` carry state, trip reason, what the core believes about pack/charger/EVSE, counters and build; `0x18EFC0E1` / `0x18FFD7E1` are byte-exact mirrors (source address 0xE1) of every frame the interposer modified or synthesised, so an Android/laptop log shows what the charger actually received. Forward-engineered, authoritative by design. Schema: `charge-interposer/diag/interposer_diag_schema.md` in the public `canbus-esp-fw-vtrux` repo, branch `charge-interposer/main`; the behaviour specification is internal-only. | Current |
| `vtrux-wican-diag.dbc` | **The WiCAN gen-inhibit dongle's own self-telemetry**, not a truck ECU. 0x7F1-0x7F3 carry build/rev, mode, disable reason, and inhibit counters, so an Android/laptop log of a run is self-documenting. Forward-engineered, authoritative by design (like the 914). Schema: `gen-inhibit/diag/wican_diag_schema.md` in the public `canbus-esp-fw-vtrux` repo, branch `gen-inhibit/main`. | Current |


**When to add a signal to `vtrux-*-experimental.dbc`:** A signal belongs here only if it was confirmed through our own reverse engineering (log correlation, interlock/disconnect tests, physical measurement) AND is not already present in the corresponding `epri-*-bus.dbc` or `epri-obd-bus.dbc`. Do NOT copy EPRI-confirmed signals into the experimental DBC — they already live in the authoritative EPRI files and duplicating them creates a maintenance conflict. If you confirm the scale or encoding of an EPRI signal experimentally, update the `CM_` comment in the relevant EPRI DBC file rather than adding an entry to the experimental one. Note that `epri-obd-bus.dbc` contains some misidentified entries (e.g. 0x451 is GMLAN, not TRAC MCU); signals that were absent from or wrongly attributed in the EPRI DBC belong in the experimental dbcs once confirmed.

**Bugged EPRI decodes:** the same applies when the EPRI app decodes a real signal *incorrectly* (wrong signedness, wrong offset, wrong bit layout) rather than merely misattributing the ID. Reduce the EPRI entry to a `BO_` stub with its `SG_` entries removed, record the defect in a `CM_ BO_` comment, and put the corrected signal in the matching experimental DBC. Examples: 0x0451 and 0x0459 (wrong ID) in `epri-obd-bus.dbc`; 0x0598 `ess_power` / `trac_power` (signed int16 vs offset-binary, confirmed 2026-08-02 as a genuine app defect via Ghidra) in `epri-pt-bus.dbc`.

**After editing any DBC on this list, regenerate the Android parity fixtures.** Four of
these files — `epri-pt-bus.dbc`, `epri-obd-bus.dbc`, `BelInverter-v2.dbc` and
`GMW8762_PPEI_GMLAN.dbc` — are *copied* into
`android-app/CanLoggerApps/cancore/src/test/resources/dbcs/` by
`tools/dbc_parity_generate.py`, which also generates the expectations
`DbcParityTest` checks the Kotlin decoder against. Nothing links the copies back to
these originals and nothing fails when they drift: the test keeps passing against the
stale definition. It was found stale twice on 2026-09-25, by months. Run
`<py> tools/dbc_parity_generate.py` then `:cancore:testDebugUnitTest`, and see
`tools/tools.md` → `dbc_parity_generate.py` for the one-line `cmp` loop that detects
the drift without a build.

Working/source copies of some DBC files also exist in the `gmlan-info/` subdirectory (see File Layout below).

### Bus Definition

| Bus | DLC Pin access | Relevant DBCs | What is confirmed |
|-----|---------|-|---------|
| **Powertrain** | CAN-H: 1 <br> CAN-L: 9 <br> P2 on Via harness  | `epri-pt-bus.dbc` <br> `vtrux-powertrain-experimental.dbc` <br> `BelInverter-v2.dbc`| Via EV control bus: generator inverter (GENE MCU) commands and feedback, BMS, Bel charger/DCDC, driver inputs. Note: traction inverter was originally assumed to be here but is on the OBD bus. |
| **Vehicle** | standard OBD-II <br> CAN-H: 6 <br> CAN_L: 14 | `GMW8762_PPEI_GMLAN.dbc` | Native bus for EBCM and other chassis modules. Wheel speeds and gear state are real here. ECM engine messages (0x0C9, 0x1C3, etc.) are VCM-generated synthetic values on this bus, not real ECM data.  A normal scan tool on the stock DLC sees only this bus; the VCM acts as diagnostic gateway and controls what is visible. OBD PID 0x0D returns real vehicle speed because the VCM answers at 0x7E8 from its own Vehicle bus wheel speed data — it does not bridge the request to the ECM. |
| **OBD** | CAN-H: 10 <br> CAN-L: 2 <br> Via harness P1 connector | `epri-obd-bus.dbc` <br> `vtrux-obd-experimental.dbc` <br> `GMW8762_PPEI_GMLAN.dbc`| Native bus for the ECM and the traction inverter (TRAC MCU). Real engine RPM lives here. Wheel speed (0x0C1/0x0C5) masked to all zeros → ECM computes zero vehicle speed → 0x3E9 broadcast also zero (cascade effect, not direct substitution).  |

### Module Topology

| Module | Native Bus | Relevant DBCs | Evidence and Notes |
|--------|---------| --|----------|
| VCM (Via Motors Vehicle Control Module) | **All**; gateway for all buses | All| Bridges GM messages selectively; modifies ECM engine data when forwarding to Vehicle bus |
| ECM (Engine Control Module) | **OBD** | `GMW8762_PPEI_GMLAN.dbc`| Real engine RPM on OBD bus (0 off, real when running); ~800 RPM synthetic on Vehicle bus = VCM substitute |
| EBCM (Electronic Brake Control Module) | **Vehicle** | `GMW8762_PPEI_GMLAN.dbc` | 0x17D present only on Vehicle bus (0 frames on OBD); other EBCM messages bridged to OBD |
| GENE MCU (Generator Inverter) | **PT bus** | `epri-pt-bus.dbc` | Dana TM4 CO150 (J1939-native hardware). |
| TRAC MCU (Traction Inverter) | **OBD** | `epri-obd-bus.dbc` <br> `vtrux-obd-experimental.dbc` | Dana TM4 CO150 (J1939-native hardware). Not visible on PT bus. EPRI decompile incorrectly attributed 0x0451 to TRAC MCU (GMLAN Gateway_LS_General_Information) and incorrectly placed TRAC thermal at 0x0459 (zero frames; actual is 0x044A). Both errors documented in `epri-obd-bus.dbc`. |
| BorgWarner 32-01 eGearDrive + park-pin controller | **PT bus** | `epri-pt-bus.dbc` <br> `vtrux-obd-experimental.dbc` | BorgWarner 32-01 eGearDrive single-speed longitudinal transmission. Rated input torque: 350 Nm peak (`notes/borgwarner-transmissions.pdf`). Same eGearDrive family as the Coda EV (which uses the transverse 31-03 variant). VCM bridges park state to GMLAN. See Known Signals. |
| Via shift position sense box | **None** (hypothesis: direct non-CAN link to VCM) | — | Translates the non-standard Via shifter position into a signal for the VCM. Hypothesis: connects to the VCM via direct analog or digital wire rather than CAN — no CAN messages are directly attributed to this box. VCM generates GMLAN gear/lever position output from this input; when box is disconnected, VCM defaults to reporting Neutral. "Manual" (0x09) = generator mode. See `notes/shifting-transfer-case-investigation.md`, `notes/can-disconnect.md`. |
| TCCM (Transfer Case Control Module) / TCCM_RDCM | **OBD + Vehicle buses** (bridged) | `GMW8762_PPEI_GMLAN.dbc` | Manual TC. 0x1CF (`Secondary_Axle_General_Information`, GMLAN decimal 463) confirmed active on both GM buses — mode=2 when front axle engaged (4H or 4L), mode=0 in 2WD or Neutral. Cannot distinguish 4H from 4L on any logged signal. Source (residual TCCM_RDCM vs VCM-synthesized) not yet confirmed. See `notes/shifting-transfer-case-investigation.md`. |
| A123 BMS (Battery Management System) | **PT bus** | `epri-pt-bus.dbc` + `vtrux-powertrain-experimental.dbc` (0x0411 only) | A123 lithium iron phosphate battery pack. Broadcasts directly on PT bus in the 0x370–0x507 ID range (requires HV battery LV connector). 0x596 (integer SoC) is a VCM rebroadcast, not BMS-direct. See `notes/powertrain-messages.md` BMS section and `notes/isolation-fault-analysis.md`. |
| Bel Fuse Bidirectional Charger/Inverter | **PT bus** | `BelInverter-v2.dbc` + `epri-pt-bus.dbc` | On-board AC charger and V2G inverter. J1939 extended-frame IDs (SA=0xB3). EPRI PT bus table includes charger status signals (current, voltage, fault state). See `notes/charge-investigation.md` and `BelInverter-v2.dbc` for decoded signals. |
| Bel Fuse DCDC Converter | **PT bus** | `epri-pt-bus.dbc` | HV-to-12V DC-DC converter. J1939 extended-frame IDs (SA=0xB3 family). Broadcasts HV bus voltage reference (0x18FFD6B3 B4-B5) used as cross-validation for 0x470 and 0x482 voltage signals. See `notes/context-voltage-current.md`. |
| EMP WP29 C20 PE coolant pump | **PT bus** (independent pump CAN tier) | `vtrux-powertrain-experimental.dbc` | Electric glycol coolant pump for power electronics cooling loop. J1939 proprietary PGN 0xFF03, SA=0x20, ID=0x18FF0320. ~1 Hz. No signals decoded. Confirmed by CAN disconnect test (sole ID that drops when PE pump CAN connector is unplugged). See `notes/can-disconnect.md`. |
| Sanden MI-EV36-BNKx HV AC compressor | **PT bus** | `vtrux-powertrain-experimental.dbc` | Electric HV AC compressor. J1939 extended-frame IDs (SA=0x47). Broadcasts EAC_STATUS1 (0x0868A047) and EAC_STATUS2 (0x0870A047) at 10 Hz regardless of compressor state. EAC_STATUS2: eac_hv_input (B2 x4 V) confirmed; B1/B3 = temperature sensors. EAC_STATUS1: bytes partially characterized (B3=checksum confirmed, B2=current candidate, B1/B4 unknown) but no signals confirmed — stub only, no DBC signals. See `notes/hvac-investigation.md`. |
| Eberspacher HV PTC heater | **None** (PWM controlled) | — | High-voltage positive temperature coefficient cabin heater. Controlled via PWM signal from VCM, not via CAN. No CAN messages attributed to this device. |
| FSCM, BPIM, ACC, PTO, SGCM | **Absent** | — | Not installed or removed with EV conversion. Zero frames on either GM bus. |

### VCM Gateway

**Normal operation:** The VCM modifies content on both GM buses and bridges a subset of messages between them. Many GMLAN messages appear on both buses without VCM involvement -- T3 shows 33 IDs surviving on both buses with 0ms inter-bus delta, ruling out bridging. The source module(s) for this dual-bus presence are unconfirmed: candidates include stock C5500 chassis modules (EBCM, BCM, IPC) that are natively wired to both GM buses, and/or the GM ECM secondary CAN pins (confirmed to physically exist, no confirmed functionality in Vtrux install). The ECM is **not** uniformly dual-bus -- `0x0C9` on the Vehicle bus is VCM-synthesized (drops in T3), confirming the ECM's primary CAN is the OBD bus and it does not natively transmit all messages on Vehicle bus. See `notes/can-disconnect.md` T3 section for the evidence.

| Bus | VCM action | Key IDs |
|-----|-----------|---------|
| **Vehicle** | Substitutes ECM engine messages with EV-compatible values | 0x0C9 (~800 RPM motor idle), 0x1C3/0x1C5 (motor torque) |
| **OBD** | Masks wheel speeds to all zeros | 0x0C1, 0x0C5 |
| **OBD** | Freezes transmission position at Park | 0x1F5 |
| **OBD** | Replaces with canned/frozen frames | 0x1E9 (chassis status), 0x1C7 (EBCM torque requests), 0x3E9 (vehicle speed) |
| **OBD** | Stubs with invalid-fill bytes | 0x0F9 (TCM) |
| **OBD->Vehicle** | Bridged faithfully (absent from Vehicle in T3) | 0x772 |
| **OBD->Vehicle** | Bridged faithfully (absent from Vehicle in T3; engine-off confound -- may also be engine-running-only) | 0x0AA, 0x0BE, 0x0D3, 0x3D1, 0x3E9, 0x4F1, 0x4F3 |
| **Both buses, dual-native** | Survive T3 on BOTH buses with 0ms delta -- NOT VCM-bridged; source has native dual-bus connections | 0x3C1, 0x3F9, 0x3FB, 0x4D1, 0x4C9 and ~28 other chassis IDs |

**T3 correction (2026-04-14):** The prior "Bridged faithfully -- Both buses" row listed 0x3C1, 0x3F9, 0x3FB, 0x4D1, 0x772, 0x4C9. T3 (VCM B-connector disconnect) showed all of these except 0x772 survive on both buses without VCM, and with 0ms inter-bus timestamp delta. They are NOT VCM-bridged. 0x772 is the only confirmed VCM bridge from that list (drops from Vehicle bus in T3).

The 0x3E9 entry is a **cascade effect** -- VCM masks wheel speed inputs to ECM, so ECM naturally computes and broadcasts zero vehicle speed; VCM does not need to modify 0x3E9 directly.

**Counting hazard: the same ID on the two GM buses is often not the same message.** This is
the Vtrux form of the invariant in `AGENTS.md` under Data Sources, and it is worse here than
on the Coda. The Coda gateway mostly *rebroadcasts*, so merging buses double-counts and the
tell is an exact factor of two. The VCM **substitutes content**, so merging buses blends real
and synthetic data — and the synthetic side is plausible by construction, because it exists to
keep stock modules happy. `0x0C9` on the Vehicle bus reports a ~800 RPM engine idle that no
engine is producing. `0x0C1`/`0x0C5` on OBD report zero wheel speed while the truck is moving.
`0x1E9` on OBD is frozen across all eight bytes.

So for these IDs there is no such thing as "the value" without naming the bus, and an average
or histogram taken across both is not a noisier version of the right answer — it is a blend of
a measurement and a fabrication. **The authoritative per-ID inventory is the `exclude` list in
`VEHICLE_PROFILES["vtrux"]` in `tools/influx_upload.py`**, which names the real source bus for
each affected ID; the table above is the prose version. InfluxDB is uploaded with those
exclusions applied, so a query there already sees one copy — the right one. Raw-log analysis
does not, and must split by bus, identified by the anchor IDs above rather than by channel
number.

**Graphing / analysis note -- GMLAN messages appear on both GM buses:** Many GMLAN IDs produce frames on both the OBD bus and the Vehicle bus in a multi-bus capture. This is partly due to VCM bridging, but also because the GM ECM and other modules have native connections to both buses (33 IDs confirmed dual-native without VCM in T3, with 0ms inter-bus delta). The two copies often contain different content (real ECM value on OBD bus vs. VCM-substituted value on Vehicle bus -- see table above). When extracting a GMLAN signal for analysis or plotting, always filter to the bus where that signal is documented as valid. Never rely on channel numbers -- use the anchor IDs from the Bus Identification table above to identify the correct channel at runtime.

**Diagnostics:** The VCM acts as a diagnostic gateway on the standard DLC (Vehicle bus). For OBD-II services (Mode 01 PIDs, Mode 03/07/0A DTC reads), the VCM forwards requests to the ECM on the OBD bus and relays the response. Exception: PID 0x0D (vehicle speed) is intercepted and answered from the VCM's own wheel speed data, because the ECM would return zero due to its masked wheel speed inputs. UDS ReadDTCInformation (0x19) and KWP2000 (0x18) are rejected with NRC `serviceNotSupported`. A standard scan tool on the stock DLC cannot directly reach the ECM or TRAC MCU; the OBD bus is only accessible via the Via harness P1 connector.

**Scanner forwarding direction:** `0x7DF` (OBD broadcast request) originates on the Vehicle bus and is forwarded to the OBD bus ~2–4ms later by the VCM. `0x7E8` (ECM response) originates on the OBD bus and is echoed back to the Vehicle bus. When a scanner is connected directly to the OBD bus (P1 harness), `0x7DF` is NOT forwarded to the Vehicle bus — only the `0x7E8` response is echoed across. `0x7E0` tester-present follows the same asymmetry. See `notes/threebusinvestigation.md` for full forwarding detail.

**Known ECM DTC — P0621:** P0621 (Generator Lamp "L" Control Circuit) is permanently stored in the ECM because the alternator L-terminal was removed during the EV conversion. Classified as a non-emission enhanced diagnostic — not OBD-reportable, no MIL. Standard Mode 03/07/0A returns 0 DTCs even via direct ECM access on the OBD bus. ECM continuously broadcasts P0621 on `0x772` at ~1 Hz (bridged to Vehicle bus ~50ms later). Full DTC record accessible via GM proprietary service 0xA9 (`0x7E0` request, `0x5E8` response). See `notes/threebusinvestigation.md`.

**APP (accelerator pedal position) magnitude IS on GMLAN — correction 2026-08-14.** Earlier
revisions of this file stated there was no APP magnitude on CAN and that only validity flags
existed. That was an artifact of a broken DBC extraction, not of the vehicle. The deprecated
`gmlan-info/archive/GMW8762_PPEI_GMLAN.dbc.deprecated` omitted both APP magnitude signals and
merged 0x0F1 brake-pedal signals into 0x0C9; regenerating the DBC via `gmlan-info/run_extraction.py`
fixed it. The current `GMW8762_PPEI_GMLAN.dbc` defines both magnitudes, and both are populated
on the **OBD bus**:

| Signal | Message | Bit layout | Observed in corpus |
|--------|---------|-----------|--------------------|
| `Accelerator_Actual_Position` | `0x0C9` `Engine_General_Status_1` | (spec-derived, not reproduced) | 0–99.6%, 494k points across 64 sessions |
| `Accelerator_Effective_Position` | `0x1C3` | (spec-derived, not reproduced) | 0–99.6%, 430k points |

On the `ch1`/`ch2`/`ch3` fallback channels both read a constant 0 (a few hundred points total) —
consistent with the dual-native/bridged-copy behaviour described above. Filter to the OBD bus.

**Prefer `Accelerator_Actual_Position` over TPS** as the VCM engine throttle command. Measured on
session `vtrux_20260724_211556` (994 paired 10 s samples): APP correlates with `Engine_Speed` at
r=0.968, `Throttle_Position` at r=0.708. With the engine off, APP reads 0 while TPS rests at ~29%.
`Throttle_Position` (`0x3D1` `Engine_General_Status_2`, OBD bus) is the
throttle *body* position, which the ECM modulates independently for idle control and torque
management — it is a derivative of the command, not the command.

Neither APP signal is driver-controlled — the driver's foot is `0x592 B2-B3` on the PT bus. The VCM
generates the ECM's APP input as an analog voltage via the APP GEN MOD, and the ECM echoes what it
receives onto CAN. Confirmed by disconnect testing — see `notes/app-gen-mod-investigation.md`.

**Confirmed operating range: 0–66%, not 0–100%.** Verified across the entire InfluxDB corpus —
494,053 points on the OBD bus spanning 2026-02-17 to 2026-08-02, 161 sessions. The signal is defined
0–100% and the raw byte does reach 254, but **99.99% of points fall below 65%** and sessions top out
at 65.5–66.3% (raw counts 167–169). The VCM does not command more than about two-thirds pedal. The
soft ceiling — three adjacent counts rather than one repeated value — indicates a calibration limit
rather than a saturating register.

Only 48 points of 494,053 (0.010%) exceed 66%, spread across 6 sessions in handfuls of 1–22; only 17
exceed 70%. **Readings above ~70% are a fault signature, not driver input.** The only two sessions
reaching full scale (`vtrux_newcharger_part2`, `rainychargedebug4`, both 99.6%) are stationary
charging-debug captures where the pedal is at rest, and `vtrux_app_disconnect_test`'s single 71.0%
point is one of three stray frames in a log where the APP source was unplugged. Treat these as bit
errors.

Practical consequence: any gauge or plot axis for this signal should be scaled **0–70%**. At 0–100
the needle never passes two-thirds of scale. See `notes/artifacts/app_range_corpus.py` for the query.

> Caveat on the distribution: Influx point counts are not frame counts (on-change plus 1 s
> heartbeat), so band *shares* skew toward values that persist. The range and ceiling findings above
> are unaffected; do not read the shares as fraction-of-driving-time.

For full bus identification methodology and per-log-set bus number mappings, see `notes/threebusinvestigation.md`.

---

## Sources of Data

### EPRI Logger app investigation

The Vtrux had an EPRI-installed iPhone running an app called "EPRI Logger" that logged CAN data from the OBD bus and PT bus via GoPoint BT1 dongles. The app binary was extracted and fully reverse-engineered in Ghidra to recover exact byte layouts, scales, and offsets for all logged signals. Signals include engine temps (0x4C1), engine speed/torque/MAP/fuel rate (standard GM PPEI IDs), motor RPM and torque (Via MCU messages), HV bus voltage/current, SoC, and others.

All signal decodings are in `notes/original-datalogging-investigation.md` Part 3; encoded signals are in `epri-obd-bus.dbc` (OBD bus) and `epri-pt-bus.dbc` (Powertrain bus). The byte-level decodes are confirmed from the decompile but not all have been systematically validated against real Vtrux log data.

### EPRI Signal Coverage

Byte layouts confirmed from Ghidra decompile; scales confirmed from ARM binary DAT constants unless noted. For full encoding detail (bit positions, offsets, enum values) see the DBC files. For investigation methodology and findings, see `notes/original-datalogging-investigation.md` Part 3.

**PT bus (`epri-pt-bus.dbc`):**

| CAN ID | Message | Key signals | Notes |
|--------|---------|-------------|-------|
| 0x0054 | GENE MCU rotation speed | GENE_RotSpd (generator RPM), GENE_EmergcyStp_flg | B0:B1 LE, -32767 offset; GENE_EmergcyStp_flg: B4 bit 3 |
| 0x0308 | BorgWarner TCM park request | ParkRequest (B0[6:5], 2-bit: 0=OFF, 1=Park, 2=UnPark) | DLC=1. Ghidra-confirmed; not in original EPRI plist. See BorgWarner section below. |
| 0x0400 | BCM HV system control | hsc_bcm_enable (B0 bit0), hsc_bcm_epo (B0 bit1), hsc_bcm_mainc_close (B0 bit2), hsc_bcm_leakage_ena (B0 bit3) | DLC=1. Ghidra-confirmed; not in original EPRI plist. **BMS-sourced** (drops with BMS LV connector; previously incorrectly assumed VCU-sourced). See Battery/Contactor Operational Flow below. |
| 0x0410 | A123 BMS status | bcm_ibat (pack current), bcm_soc (SOC), bcm_vbat (pack voltage), bcm_gfd (ground fault detection), bcm_mainc_stat, bcm_chgc_stat, bcm_alarm, bcm_epo, bcm_ready, bcm_on_plug, bcm_hvil_mon, bcm_cpwr_cmd, bcm_chg_done, bcm_cool_req | bcm_ibat: 16-bit BE, `raw*0.025-1000` A, neg=discharge; bcm_vbat: 12-bit Motorola *0.25 V; bcm_gfd: 1000.0=normal, 0.0=isolation fault (fires 150ms before EPO); bcm_ready/bcm_on_plug/bcm_hvil_mon/bcm_cpwr_cmd/bcm_chg_done/bcm_cool_req: 1-bit flags in B0-B6. **Operational state values:** B0 bit3 (bcm_hvil_mon) = interlock loop state (1=closed, 0=open). B1 = BMS state machine: 0xBF=normal, 0xCF=fault latched. B2: 0xA0=normal, 0x00=isolation-fault ordered shutdown only (clears simultaneously with first B1 step), 0xFE=settled fault state. See `notes/interlock-bitfields-analysis.md`, `notes/isolation-fault-analysis.md`. |
| 0x0420 | A123 BMS limits | bcm_chg_max (CCL), bcm_dis_max (DCL), bcm_cell_overvolt flag, bcm_cell_undervolt flag | 12-bit Motorola fields |
| 0x0430 | A123 BMS cell data | bcm_cell_vmax, bcm_cell_vmin (13-bit Motorola, 1 mV/count), bcm_cell_tmax, bcm_cell_tmin (0.5°C/count - 40°C), bcm_lvbat (12V battery), bcm_chga_ena, bcm_veh_mon, bcm_chga_mon, bcm_mod_ena | **Cell temp: `0.5*raw - 40 degC` confirmed from DAT constant; supersedes provisional `raw-100` from experimental work**; bcm_chga_ena/bcm_veh_mon/bcm_chga_mon/bcm_mod_ena: 1-bit flags in B0-B2 |
| 0x0440 | A123 BMS data2 / isolation monitor | bcm_vbus_pos (positive rail to chassis), bcm_vbus_neg (negative rail to chassis), bcm_fault_mon (pulses HIGH 100ms every second), bcm_mainc_stat (contactor sequence, 4-bit), bcm_fgd, bcm_balancing_cnt, bcm_balancing | vbus_pos: 12-bit Motorola *0.25 V; vbus_neg: 12-bit Motorola *0.25-500 V (neg rail ~0 V in normal op); bcm_balancing: 1-bit flag B0 bit 7 |
| 0x0471 | GENE MCU motor torque | GENE_Mot_Trq | LE, -4096 offset. Actual DLC=7; B2–B6 uncharacterized (EPRI app only read B0:B1). |
| 0x0479 | GENE MCU thermal | GENE_DrvCoolFlowReq_pct, GENE_MotCoolFlowReq_pct, GENE_ThermInd_pct | 0.78125%/count; raw 128 = 100%. Actual DLC=4; B3 uncharacterized. **ThermInd_pct derate onset: ~85-86%** (confirmed 2026-03-29: sustained high torque from 80% crossing to cutback ~120s; 80% is not the threshold). **MotCoolFlowReq_pct interpretation unclear**: generator oil pump is relay-controlled (binary on/off); the percentage output is not yet understood in that context. |
| 0x0482 | GENE MCU HV bus | GENE_HighPwr_Curr (14-bit LE, -2048 A offset), GENE_HighPwr_Volt (11-bit LE, 1 V/count) | Actual DLC=6; B5 uncharacterized. |
| 0x055C | BorgWarner TCM park lock state | parkLockState (B0[2:0]), parkSensor (B0[6]), driveSensor (B0[7]) | DLC=4. Ghidra-confirmed; not in original EPRI plist. Original decompile notes had a transcription error (raw `pbVar15[2]` recorded as "B2" instead of CAN B0 per buffer layout in `notes/epri-decompile.md`). Corrected 2026-04-07. See BorgWarner section below and `notes/borgwarner.md`. |
| 0x0592 | HCU sensor inputs | Veh_BrakePdl_Pos (0.01/count), EVSESwitchState, ExportPowerState, IgnitionKeyState | Actual DLC=8; B6–B7 uncharacterized. |
| 0x0598 | HCU power averages | ess_power (B0-B1), gen_power (B2-B3), trac_power (B4-B5) — 0.01 kW/count, unsigned centered at 32768 (zero at 0x8000). Confirmed centered (not signed) by 0x598 raw-value check 2026-06-27. **All three now live in `vtrux-powertrain-experimental.dbc`**; `BO_ 1432` in `epri-pt-bus.dbc` is a stub, because the EPRI app genuinely decodes B0-B1/B4-B5 as signed int16 (app defect confirmed by Ghidra 2026-08-02, ARMv7 + ARM64). See `notes/epri-decompile.md`. Scale confirmed 2026-03-29. | Actual DLC=8; B6–B7 = static bias, not power data. |
| 0x0599 | Motor cooling oil pressures (VIRTSENS) | GeneOilPress (B0:B1 LE, 0.1 kPa/count, offset 0 per decompile), TracOilPress (B4:B5 LE, 0.1 kPa/count, offset 0) | PARTIAL. VIRTSENS: HCU reads ADC inputs directly. Scale 0.1 kPa/count decompile-confirmed; offset 0 for both per decompile. GeneOilPress idle raw ~0x8000 (~3276 kPa decoded) — likely mid-scale sensor, offset correction unconfirmed (no pump disconnect test). TracOilPress rises from near 0 to ~70 kPa under load. B2:B3 constant 103.0 kPa (barometric reference); B6:B7 uncharacterized. |
| 0x0625 | Odometer + config | VehicleOdometer (24-bit BE, 1 km/count confirmed), VehicleConfig (K2XX vs GMT-600 platform) | Actual DLC=8; B4–B7 uncharacterized. |
| 0x06000001 | EPT_Stat_HMI_1 | Accel_Ped_Pos (7-bit), GearPos (3-bit enum), Veh_Speed (15-bit Motorola, 1/64 km/h) | **Real PT bus CAN ID (VCU-sourced), but EPRI DBC byte layout (DLC=12) is a GoPoint-synthesized Bluetooth packet — byte positions B4/B7/B10:B11 do NOT match the raw CAN frame** |
| 0x0868A047 | EAC_STATUS1 | EAC_Elec_Curr (0.2 A/count), EAC_Elec_Pwr (40 W/count), EAC_CompStatus, EAC_CompFltStat | Sanden MI-EV36-BNKx EAC (SA=0x47). EPRI DBC DLC=9 is GoPoint-synthesized — byte positions not directly usable. See `vtrux-powertrain-experimental.dbc` and `notes/hvac-investigation.md`. |
| 0x0870A047 | EAC_STATUS2 | EAC_CompHVInput (4 V/count) | Sanden MI-EV36-BNKx EAC (SA=0x47). EPRI DBC byte positions GoPoint-synthesized. Byte-level confirmation in `vtrux-powertrain-experimental.dbc`. See `notes/hvac-investigation.md`. |
| 0x18FFD5C0 | Bel BDC temperature | INVCH_Bdc_Temperature_Int (0.1°C/count), INVCH_Bdc_TempPercent | Charging/operating only |
| 0x18FFD6B3 | DCDC feedback | DCDC_HV_Volt (B4-B5, ×0.05V), DCDC_LV_Volt (B0-B1, ×0.05V), DCDC_LV_Curr (B2-B3, ×0.05A), DCDC_HW_Temp (B6-B7, ×0.1°C signed) | All signals in one message — no separate temperature ID. B0=31 steady state. HV: r=0.993 vs charger; LV: ~14.35V regulated; temp: 18→42°C cold-start to peak, drops to ~35°C in CV phase. |
| 0x18FFD6C0 | Bel inverter AC output | INVCH_Inv_Vout1/2_RMS, INVCH_Inv_Iout1/2_RMS (0.05 V or A/count) | Active during driving and export |
| 0x18FFD7C0 | Bel charger DC+AC input | INVCH_Bdc_Ibat, INVCH_Bdc_Vbat, INVCH_Chg_Iin_RMS, INVCH_Chg_Vin_RMS (0.05 V or A/count) | Charging only |
| 0x18FFD8C0 | Bel J1772 monitor | INVCH_Bdc_J1772 (0.02 V/count) | Charging only |

**OBD bus (`epri-obd-bus.dbc`):**

| CAN ID | Message | Key signals | Notes |
|--------|---------|-------------|-------|
| 0x0044 | TRAC MCU rotation speed | TRAC_RotSpd (traction motor RPM), TRAC_EmergcyStp_flg | B0:B1 LE, -32767 offset; **OBD bus only** — not visible on PT bus; TRAC_EmergcyStp_flg: B4 bit 3 |
| 0x00C9 | PPEI engine speed | Engine_Speed (uint16 BE B1:B2, x0.25 RPM) | |
| 0x0120 | Vehicle odometer | VehicleOdometer (uint32 BE, x0.015625 km) | Actual DLC=5; EPRI DBC had 8 (over-declared). B0 unused; signal in B1–B4. |
| 0x01C3 | PPEI engine torque | 2 torque signals (12-bit Motorola, x0.5 Nm, -848 Nm offset) | |
| 0x02C3 | PPEI MAP | ECM_MAP (B6 x0.5 kPa) | Plist label "Engine_Torque_Status_3" was incorrect |
| 0x03D1 | PPEI Engine_General_Status_2 (multi-signal) | ECM_InstFuelConsmpRate_volPt; Throttle_Position; Engine_Coast_Fuel_Cut_Off | Multi-signal message — do NOT summarize the whole ID as "fuel rate". Message name "Engine_General_Status_2" is correct (the EPRI plist label was right). Fuel rate and throttle are carried in different bytes of the same frame. Throttle is the VCM engine-throttle command proxy. |
| 0x03E9 | PPEI vehicle speed + distance | ECM_VehSpdAvgDrvn_linspd (15-bit Motorola, x1/64 km/h), ECM_DistRollCntAvgDrvn_dist (13-bit Motorola, x0.125 km) | |
| 0x0451 | ~~TRAC MCU motor torque~~ **MISIDENTIFIED** | ~~TRAC_Mot_Trq~~ | EPRI decompile incorrectly attributed this to TRAC MCU. Log data shows it is the GMLAN message `Gateway_LS_General_Information`; decode withheld (see the GMLAN publish rule). SG_ entries removed from `epri-obd-bus.dbc`. See `traction-inverter-control.md` Phase 1. |
| ~~0x0459~~ | ~~TRAC MCU thermal~~ **WRONG ID** | — | EPRI plist listed this ID for TRAC MCU thermal; zero frames at 0x459 in all logs. Message exists but at 0x044A (EPRI offset was -0x020; actual is -0x02F). |
| 0x0462 | TRAC MCU HV bus | TRAC_HighPwr_Curr (14-bit LE, -2048 A), TRAC_HighPwr_Volt (11-bit LE, 1 V/count) | Symmetric to GENE 0x0482. Actual DLC=6; B5 uncharacterized. |
| 0x04C1 | PPEI engine temperatures | ECM_EngineCoolantTemp, ECM_EngineAirIntakeTemp (uint8, x1 degC, -40 offset); ECM_OutsideAirTemp (uint8, x0.5 degC, -40 offset) | Outside air temp has different scale (0.5°C/count) from the other two (1°C/count) |

---

### Bel-Inverter/Charger DBC

Source history: initial signal data from a previous DBC, with EPRI Ghidra decompile data merged in via `notes/belinverter-dbc-merge.md`. EPRI-confirmed signals are noted below; remaining signals are from the previous DBC and have unconfirmed byte layouts. Messages are present only when the charger/inverter is active (J1772 plugged in or export mode on).

**`BelInverter-v2.dbc` (SA=0xC0 — Bel inverter/charger):**

| CAN ID | Message | Key signals | Notes |
|--------|---------|-------------|-------|
| 0x18FFD4C0 | BINV_status | mux=0: BELINV_state (B5), BELINV_shutdownSource (B6), BELINV_stateBeforeLastShutdown (B7), 1-bit status flags (keySwitch, chargingInProgress, exportEnergy, inverterAlive, inverterReady, buckBoostAlive, gridTied, etc.); mux=1: BELINV_buckBoostState, BELINV_buckBoostStateBeforeLastShutdown; mux=2: BELINV_inverterState, BELINV_inverterStateBeforeLastShutdown; mux=3: fault bits (inverterFault, buckBoostFault, acOk, acOverVoltage, acUnderVoltage, hvBatteryOverVoltage, hvBatteryUnderVoltage, overTemperature, etc.) | Multiplexed on B0 (mux key). Source: previous DBC; byte layout unconfirmed by EPRI. **EPO/alarm/chgc_stat bits (mux=0) fire during every normal charge shutdown** — not fault-only. Causal order: inverterFault or external shutdown command → charger responds → EPO/alarm3/chgc fire ~1.1–1.5s later as orderly HV de-energization. Confirmed across 20 sessions including clean handle-pull (shutdownSrc=11). See `notes/after-battery-swap-charge-fail-analysis.md`. |
| 0x18FFD5C0 | BELINV_overallTemperature | BELINV_overAllInverterTemperature (B0-B1), BELINV_buckBoostTemperature (B2-B3), BELINV_ambientTemperature (B4-B5), BELINV_overallTemperaturePercent (B6) — signed 16-bit 0.1°C/count; percent uint8 | EPRI-confirmed: B4-B5 (`INVCH_Bdc_Temperature_Int`) and B6 (`INVCH_Bdc_TempPercent`) confirmed by Ghidra decompile; B6 corrected to 8-bit (previous DBC had 16-bit). B0-B3 from previous DBC only. Charging/operating only. |
| 0x18FFD6C0 | BELINV_inverterOutput | BELINV_leg1Voltage (B0-B1), BELINV_leg2Voltage (B2-B3), BELINV_leg1Current (B4-B5), BELINV_leg2Current (B6-B7) — unsigned 16-bit, 0.05 V or A/count | EPRI-confirmed (`INVCH_Inv_Output`); byte layout exact match with previous DBC. Active during driving and export. |
| 0x18FFD7C0 | BELINV_hvBatteryAndCharger | BELINV_hvBatteryVoltage (B0-B1, unsigned), BELINV_hvBatteryCurrent (B2-B3, signed), BELINV_chargerInputVoltage (B4-B5, unsigned), BELINV_chargerInputCurrent (B6-B7, unsigned) — 0.05 V or A/count | EPRI-confirmed (`INVCH_Bdc_Ibat`). Signedness corrected: hvBatteryCurrent signed (positive=charging); others unsigned. Charging only. **Accuracy (2026-10-10):** `hvBatteryCurrent` reads high below ~6 A (+0.4 A at 4-5 A, +1.5 A at a 2.0-2.5 A reading; ~0 above 10 A). `chargerInputCurrent` reads ~8 % low at full power, and V x I is apparent power. The logged hvBatteryCurrent is negative while charging, despite the comment. See `notes/charger-efficiency-and-grid-consumption.md`. |
| 0x18FFD8C0 | BELINV_j1772Info | BELINV_system12vBatteryVoltage (B0-B1, 0.02 V/count), BELINV_pilotDuty (B2, uint8), BELINV_pilotFrequency (B3-B4, uint16 Hz), BELINV_chargePilotOnlineTime (B5-B7, 24-bit count) | B0-B1 EPRI-confirmed (`INVCH_Bdc_12Vbat`); B2-B7 from previous DBC only. Charging only. |
| 0x18FFD9C0 | BELINV_chargeInfo | BELINV_maxAvailableChargingCurrent (B0-B1, signed 16-bit, 0.05 A/count), BELINV_vehicleState (B2, uint8) | Not in EPRI plist. Source: previous DBC only. **Charger-sourced (SA=0xC0), not a vehicle command** — `notes/specific-trucks/after-battery-swap-charge-fail-analysis.md` calls it the "vehicle charge command", which is wrong. `maxAvailableChargingCurrent` is the charger's own pilot-derived DC ceiling and is what actually limits CC current: measured 8 A at a 26 % pilot and 16 A at 52 %. |
| 0x18FFDAC0 | BELINV_inverterTemperature | BELINV_dc1Temperature (B0-B1), BELINV_dc2Temperature (B2-B3), BELINV_module1Temperature (B4-B5), BELINV_module2Temperature (B6-B7) — signed 16-bit, 0.1°C/count | Not in EPRI plist. Source: previous DBC only. |
| 0x18FFDBC0 | BELINV_buckBoostTemperature | BELINV_buckBoostModuleTemperature (B0-B1), BELINV_buckBoostDc1Temperature (B2-B3), BELINV_buckBoostDc2Temperature (B4-B5), BELINV_buckBoostDspTemperature (B6-B7) — signed 16-bit, 0.1°C/count | Not in EPRI plist. Source: previous DBC only. |

### Experimentally Determined

**Note:** Where a signal also appears in the EPRI-confirmed section above, the EPRI Ghidra-decompiled encoding takes precedence. EPRI data is not necessarily perfect and validation of both sources is required.

For full encoding details, confidence rationale, and source evidence, see **`notes/powertrain-messages.md`** (the authoritative signal catalog).

**PT bus (`vtrux-powertrain-experimental.dbc`):**

| CAN ID | Message | Key signals | Notes |
|--------|---------|-------------|-------|
| 0x051 | VCM_GenControl_0051 | gen_torque_cmd (B1-B2, LE uint16, centered at 32768, negative=generating), gen_rpm_ref (B3-B4, LE uint16, centered at 32768, rpm) | 100 Hz, DLC=6. B0 purpose unknown; B5 = rolling counter 0x00-0x0F. gen_torque_cmd: r=0.9984 vs feedback (0x471 B0-B1). gen_rpm_ref: null=−1 (raw=32767) when engine off; zone+fine encoding (B4=zone selector, B3=fine RPM within zone); bit-for-bit identical to 0x052 B2-B3. Corrected 2026-03-03 (previously misidentified B3-B4 as traction torque command). |
| 0x411 | BMS_SoC_HiRes_0411 | bms_soc_hires (14-bit Motorola, 0.01%/count; raw = B0×64 + (B1>>2)) | ~20 Hz (measured 16.9-20.0 Hz on four clean captures, 2026-09-24; previously recorded as 16 Hz), DLC=8. BMS-sourced (drops when HV battery LV connector unplugged). Not in EPRI plist. r>0.998 vs 0x596 bms_soc across 5 log types. Other bytes encode contactor request (changes at startup, not shutdown). |
| 0x617 | VCM_SysState_0617 | (BO_ stub — no SG_) | VCM-sourced. B0-B5=0, B6=0x50 constant. B7 = 0xC8+state: C8 normal, C9 unresolved secondary state, **CA = fault-active** — sets within ~0.3 s of BMS EPO in every fault mode tested, clears when the condition ends. Cheap VCM-side fault flag (no cause code). See `notes/battery-fault-codes.md`. |
| 0x460 | BMS_FaultRecords_0460 | (BO_ stub — no SG_; page-multiplexed) | ~20 Hz, DLC=8. BMS-sourced **fault-record annunciator** (2026-08-26): B0=page index; page 0 = record count; pages 1-N = two 3-byte fault records each, newest first. Records push when a fault latches, survive BMS reboot, clear with FAULT_LATCHED. Main-orig steady-state charge fault = `FC 22 02`; precharge abort = `F0 E0 00`; truck3-contactor faults = `F6` family. **Caution:** OBD bus has a different 0x460 (TRAC MCU, DLC=5) — filter to PT bus/DLC=8. Full catalog: `notes/battery-fault-codes.md`. |
| 0x470 | Unknown_0470 | hv_bus_volt_470 (11-bit LE, startbit B1, 1 V/count) | Not in EPRI DBC. Post-contactor HV bus voltage confirmed (drops 387 V to ~3 V when contactors open). r=0.9974 vs DCDC 0x18FFD6B3. Same encoding as GENE_HighPwr_Volt (0x482). Source ECU unknown — most likely GENE MCU (drops at same time, adjacent ID range). See `notes/context-voltage-current.md`. |
| 0x592 | VCM_Pedals_0592 | throttle_pos (B2-B3, LE uint16, unsigned, 0=no throttle, max ~10000 at full depression) | **10 Hz** (9.98-9.99 Hz on four clean captures, 2026-09-24; previously recorded here as 100 Hz), DLC=8. VCM-sourced. Brake pedal (B4-B5, scale 0.01%) and switch flags (B0) are in `epri-pt-bus.dbc`. B1 role unconfirmed. Scale to physical % unconfirmed. |
| 0x596 | BMS_SoC_0596 | bms_soc (B6, uint8, 1%/count) | ~1 Hz. VCM rebroadcast of BMS SoC data (drops when VCM B-connector unplugged, per `notes/can-disconnect.md`). Not in EPRI plist. Integer SoC percent. Use 0x411 for sub-percent resolution. |
| 0x598 | HCU_Power_0598 | ess_power (B0-B1), gen_power (B2-B3), trac_power (B4-B5) — all LE uint16, centered at 32768, 0.01 kW/count, positive = providing energy to HV bus | ~1 Hz, DLC=8. VCM/HCU-sourced. gen_power scale CONFIRMED 2026-03-29. ess_power/trac_power moved here from `epri-pt-bus.dbc` on 2026-08-02: that file's signed-int16 encoding is an EPRI app defect confirmed by Ghidra, so `BO_ 1432` there is now a stub. Channel balance `trac_power = ess_power + gen_power` holds. B6-B7 = static bias, not power data. |
| 0x5A2 | VCM_TractMotor_05A2 | trac_rpm (B2-B3, LE uint16, centered at 32768, 1 rpm/count assumed), trac_torque_fbk (B4-B5, LE uint16, centered at 32768, Nm/count unconfirmed) | ~100 Hz, DLC=8. VCU-sourced re-broadcast. trac_rpm: r=0.9976 vs proxy; 64.3 RPM/km/h ratio confirmed; scale assumed 1 rpm/count by symmetry with GENE/TRAC RotSpd. trac_torque_fbk: r=0.9998 vs TRAC_TrqFbk (0x442, OBD bus); positive=motoring, regen=negative; scale to Nm UNCONFIRMED. B0-B1 and B6-B7 uncharacterized. |
| 0x639 | VCM_ShiftPos_0639 | shift_lever_pos (B6 bits[6:4], 3-bit: 0=P, 1=R, 2=N, 3=D, 4=M) | ~100 Hz, DLC=8. VCM-sourced. The VCM's resolved view of the Via shifter position box. **The only shift-position source on captures without the Vehicle bus** — the OBD-bus copy of 0x1F5 is VCM-frozen at Park. 0x644 B0 bits[7:6] mirrors the index but is 2-bit and cannot distinguish M from Park. Confirmed 2026-07-26 against `generator-on-then-off.log` (M engagement) and `vtrux_shifter_disconnect.log` (drops to Neutral on unplug). B2-B3 uninterpreted. See `notes/shifting-transfer-case-investigation.md`. |
| 0x63A | VCM_GenInitState_063A | *(none — `BO_` stub)* | ~100 Hz, DLC=8. VCM-sourced. B6-B7 carry the generator initialization state — see `notes/status-bits-cross-log-comparison.md` (and its correction box). B7 observed values 0x04/0xC4/0xD4/0xE4/0xF4; bits[3:0] constant 0x4. **bits[5:4] are a 2-bit field: generator related, not further characterized** (all four values occur; bit4 set = a bounded ~16-57 kW gen_power band, and the *highest* generator output occurs with bit4 clear). A 2026-07-26 `vcm_evap_purging` signal on B7 bit4 was **RETRACTED 2026-08-09** and then **FALSIFIED** by counterexample: on 2026-07-26 bit4 sets for 329 s while `vcm_evap_counter` holds 0 all day. Use 0x649 for evap. **bits[7:6] is not an HV-up flag** — it was clear for 100% of Saturday 2026-07-25 while `ess_power` hit 22.4 kW; meaning unresolved. See `notes/evap-cycle-analysis.md` Phase 7. |
| 0x644 | VCM_CruiseDiag_0644 | cruise_mode (B2[7:4], 4-bit: 0x8=idle_standby, 0x9=throttle_override, 0xA=active), cruise_speed_setpoint (B2[3:0]:B3, 12-bit Motorola, 0.125 km/h/count) | 100 Hz. VCM-sourced. Diagnostic — reflects VCM internal cruise state, not a command to TRAC MCU. Confirmed across two cruise logs. See `notes/cruise-control-analysis.md`. |
| 0x646 | VCM_WarnLamp_0646 | via_warn_lamp_state (B7 bits[6:4], 3-bit: 0=HV not up, 6=lamp off, 5=lamp ON) | ~100 Hz, DLC=8. VCM-sourced. State of the **Via amber warning telltale** — a Via system, unrelated to the GM/GMLAN telltale set (GMLAN malfunction and indicator bits stay clear while it is lit). **B7 bit7 is a separate 1 Hz heartbeat and must be masked off.** Value 0 is ambiguous (pre-start vs fault shutdown) — pair with 0x400 B0 or 0x410 B1. Does not encode a blinking lamp. Validated across 18 logs on both trucks. See `notes/warning-lamp-investigation.md`. |
| 0x649 | VCM_EvapControl_0649 | vcm_evap_active (B4 bit 7, 1=evap cycle pending or purging, 0=not pending); vcm_evap_counter (B2[3:0]:B3, 12-bit Motorola, counts up while engine on during an active evap cycle) | ~20 Hz. VCM-sourced. vcm_evap_active: set at key-on when a cycle is due, before the engine ever runs; clears at VCM-declared completion (~6.1s before the generator is commanded to stop); holds through involuntary stalls (tracks VCM intent, not engine state). Verified set in 17/17 logged sessions with real purge activity and never set spuriously (Phase 5). vcm_evap_counter: B2 lower nibble = MSB (increments per B3 wrap at 0xFF->0x00), B3 = LSB; 0 when no cycle active; frozen when engine off; rate variable 0.1-1.0 c/s and terminal value differs per cycle (901, 901, 856) so it is NOT a percentage — use only as a zero/non-zero PENDING-vs-PURGE discriminator. B2 upper nibble = free-running clock (independent of evap state). **B0 role UNRESOLVED** — previously mapped as the evap-active flag (bit 7); invalidated 2026-07-19, wrong in 6/17 purge sessions. B1 role unresolved. Message content differs between drive and charge modes — do not interpret from charge logs. See `notes/evap-cycle-analysis.md` Phase 5. |
| 0x06000002 | VCU_TracThermal_06000002 | trac_therm_ind_pct (B5/B6, 10-bit LE startbit=46, 1%/count) | VCU-sourced extended frame (29-bit). Re-broadcasts traction motor thermal load indicator from OBD bus (0x44A B2). r=+1.000 vs 0x44A B2 TRAC_ThermInd_pct. Scale 1%/count (raw integer percent). Traction derate onset ~78-79%. B5[1:0] are ADC jitter; B0 multiples of 4 (r≈0.9998 vs throttle), B1[7:6] rolling sub-counter, B3 slow 5-value field, B4 role unknown. See `notes/thermal-investigation.md`. |
| 0x18FF0320 | EMP_PumpStatus_18FF0320 | (no decoded signals — stub) | J1939 extended ID (SA=0x20). EMP WP29 C20 PE glycol coolant pump. ~1 Hz. No signals decoded. Confirmed source: only ID that drops when PE pump CAN connector is physically unplugged. See `notes/can-disconnect.md`. |
| 0x0870A047 | EAC_STATUS2 | eac_hv_input (B2, uint8, 4 V/count) | J1939 extended ID, SA=0x47 (Sanden MI-EV36-BNKx HV AC compressor). DLC=4, 10 Hz. HV bus voltage at compressor. B2=0 before HV contactors close. CONFIRMED across 3 logs/conditions (on, off, charging); mean error 1.3 V vs 0x0482. Both EAC IDs broadcast at 10 Hz regardless of compressor state. Steady-state only — filtered + 10 Hz, lags `bcm_vbus_pos` by ~50–100 ms during fast transients (see Documented Behavior: HV Bus Voltage Measurement Sources). Paired with 0x0868A047 (EPRI PT bus table). See `notes/hvac-investigation.md`. |

**OBD bus (`vtrux-obd-experimental.dbc`):**

| CAN ID | Message | Key signals | Notes |
|--------|---------|-------------|-------|
| 0x041 | VCM_TRAC_TrqCmd_0041 | TRAC_TrqCmd (B1-B2, LE uint16, centered at 32768, 0.125 Nm/count unconfirmed, positive=motoring) | 100 Hz, DLC=6. VCM-to-TRAC MCU torque command; symmetric to 0x051 (GENE cmd, PT bus). B0=status nibble (8-11), B3=0xFF, B4=0x7F constants, B5=rolling counter. r=0.9994 vs feedback; max +380 Nm motoring, −287 Nm regen. Scale UNCONFIRMED — inferred from GENE symmetry. Not in `epri-obd-bus.dbc`. Confirmed 2026-03-29. |
| 0x044A | TRAC_MCU_Thermal1_044A | TRAC_DrvCoolFlowReq_pct (B0), TRAC_MotCoolFlowReq_pct (B1), TRAC_ThermInd_pct (B2) — uint8, 0.78125%/count | ~5 Hz, DLC=4. TRAC MCU thermal status; symmetric to GENE 0x479 (PT bus). EPRI plist listed 0x459 for this role (zero frames in all logs); actual ID confirmed at 0x044A (EPRI offset error of −0x02F). B3 = rolling counter. TRAC_ThermInd_pct: r=+1.000 vs PT bus 0x06000002 10-bit VCU rebroadcast; derate onset ~78–79%. Confirmed 2026-03-29. |
| 0x442 | TRAC_TrqFbk_0442 | TRAC_TrqFbk (B0-B1, LE uint16, centered at 32768, 0.125 Nm/count unconfirmed) | ~98 Hz, DLC=7. TRAC MCU torque feedback; symmetric to 0x471 (GENE feedback, PT bus). r=0.9998 vs 0x5A2 B4-B5 (VCM rebroadcast). B3, B5=low-entropy status bytes; B6=rolling counter nibble. Note: `epri-obd-bus.dbc` lists 0x451 as TRAC feedback — 0x451 is GMLAN; 0x442 is the actual TRAC feedback. Scale UNCONFIRMED — inferred from GENE symmetry. Confirmed 2026-03-29. |

### BorgWarner 32-01 eGearDrive Transmission (Confirmed 2026-03-05)

**Hardware:** BorgWarner 32-01 eGearDrive — single-speed longitudinal electric drive transmission. Rated input torque: 350 Nm peak. Same eGearDrive family as the Coda EV (Coda uses the transverse 31-03 variant). See `notes/borgwarner-transmissions.pdf`.

**Internal reduction ratio:** **2.68:1** per VIA's own technician training document (VIA VTruck Component Course: "Gearbox: 2.68:1 single-speed reduction"). This is also a listed ratio in the BorgWarner 32-01 eGearDrive catalog (2.12, 2.68, 3.05, 4.05). CAN log data (2026-03-29) gives a motor RPM/speed ratio of ~63–68 rpm/(km/h) across three logs; the spread reflects speed-reference calibration uncertainty. With 2.68:1 gearbox and 3.73:1 rear axle the expected value is 66.1 rpm/(km/h), which falls within the measured range.

**Rear axle ratio note:** The RPO sticker on both trucks shows GU6 (3.42:1) — the GM factory axle. The most consistent interpretation of all evidence is that VIA swapped the ring-and-pinion to GT4 (3.73:1) during the conversion, yielding a clean ~10.0:1 total ratio (2.68 x 3.73 = 9.996). The RPO sticker documents GM factory build, not VIA's post-conversion drivetrain. **Open item:** physical inspection of axle tag or ring-and-pinion to confirm 3.42 vs 3.73. See `notes/rpo/rpo.md` for full derivation.

Both 0x308 and 0x55C are BorgWarner TCM messages in `epri-pt-bus.dbc` (Ghidra-confirmed, not in original EPRI plist). 0x308 carries the park pin state (B0) and a 16-bit LE input shaft speed signal (B1-B2, `RPM = (value - 32128) * 0.5`, r=0.9999 vs traction motor RPM) — added to `vtrux-powertrain-experimental.dbc` as `InputShaftSpeed`. 0x55C carries park lock state and park/drive sensors. The original 0x55C decompile entry had a transcription error (signals recorded at B2 instead of CAN B0); corrected 2026-04-07 — see `notes/epri-decompile.md` for buffer layout. See `notes/borgwarner.md` for full cross-vehicle signal detail and investigation history.

---

### Unconfirmed / Partially Characterized Signals

Signals with some experimental characterization but not yet promoted to a DBC. Includes confirmed signals excluded from the DBC for specific reasons (redundant source, known overflow, limited decoding progress).

| CAN ID | Bytes | Signal / Role | Notes |
|--------|-------|--------------|-------|
| 0x050 | B0 + B1[1:0] | DC bus charge current limit / CCL (VCU) — role confirmed, scale unconfirmed | 10-bit unsigned: `(B1 & 0x03) << 8 \| B0`. Dynamic CCL setpoint — moves with DC bus activity, not a static limit. Nominal ~292–305 raw at rest; varies with bus conditions; drops to floor (~43 raw) when regen blocked. Discharge limiting is entirely VCM-internal (bcm_dis_max constant throughout drive events). Scale (A/count) unconfirmed. 9.1 Hz. See `notes/current-limits-investigation.md`. |
| 0x052 | B2-B3 | Engine/generator RPM reference — duplicate of 0x051 B3-B4 | Bit-for-bit identical to 0x051 B3-B4. B0-B1 constant at 0x8000 neutral; B4 = nibble counter. Addressee unknown (TRAC MCU is on OBD bus, cannot receive PT bus messages). Not added to DBC — redundant with existing RPM sources. 100 Hz, DLC=5. |
| 0x053 | B0-B1 | Generator/system mode status — MEDIUM confidence, state machine characterized | 16-bit status word. B1=0x22 = EV/idle mode (generator not running); B1=0x00 = generator running. B0 bits 4+5 (0x30) = engine arm — set ~1.1s before generator mode starts, cleared at shutdown. B0=0x01 boot/init, B0=0x02 session-ending, B0=0x04 normal operating. Very low transition rate (~6 transitions per drive session). Symmetric arm/restore pattern at start and stop. See `notes/powertrain-messages.md`. |
| 0x308 | B1-B2 (LE) | InputShaftSpeed — CONFIRMED, moved to `vtrux-powertrain-experimental.dbc` | uint16 LE, `RPM = (value - 32128) * 0.5`. Zero = 0x7D80 (32128) at rest; Vtrux parks at ~32146 (~9 RPM coasting). r=0.9999 vs traction motor RPM (full log). Input shaft confirmed: ratio (value-32128)/RPM = 2.000 on both Vtrux 32-01 and Coda 31-03 — output shaft would differ by each vehicle's gear ratio. See `notes/borgwarner.md`. |
| 0x395 | B7 (fine), B4=B5 (coarse) | Generator phase current RMS — scale unconfirmed | r=−0.9720 (B7) vs gen torque cmd (gen-loaded). B4 always equals B5 (redundant pair). **Note:** B4 and B7 are non-adjacent, making "coarse/fine" interpretation suspect — these may be independent signals rather than a composite. 77 Hz. |
| 0x600 | B0 bit4 | Generator active flag | 0x34=active, 0x24=inactive. Transitions with any engine-running condition (hybrid, manual mode, evap). Not added to DBC pending further characterization of full B0 byte. |
| 0x600 | B3 | Engine-running state counter | uint8; descends from 12 while engine running (any mode); 12=engine not running. NOT evap-specific — responds identically to hybrid assist, manual mode, and evap. See `notes/evap-cycle-analysis.md` Phase 2B. |
| 0x412 | B2 | BMS SoC-based charge current ceiling — role HIGH CONFIDENCE, full message uncharacterized | 8-bit. r=0.999 vs 0x050 CCL during charge ramp; VCU tracks it closely during charging. Static during driving (BMS holds full permission at drive SoC). Open question: whether B2 == 0x420 B2 (bcm_chg_max lower byte) when B1[3:0]=0. Full 0x412 message structure (B0, B1, B3+) not decoded. See `notes/current-limits-investigation.md` Phase 4. |
| 0x410 | B2 | Isolation fault indicator — CONFIRMED isolation-specific, role confirmed | 0xA0 during normal operation; clears to 0x00 simultaneously with B1's first fault step (0xBF→0xB0); settles to 0xFE when fault latch stabilizes (~9s later). B2=0x00 at fault onset does NOT appear in interlock or charge fault logs (those show only 0xA0/0xFE). Strongest isolation-specific positive indicator in CAN data. Not in EPRI plist. See `notes/isolation-fault-analysis.md`. |
| 0x420 | B3 | Isolation resistance periodic test result — CONFIRMED role, scale unknown | uint8; 0xC8=200 (init/"no measurement yet"), ~192 (healthy nominal during bulk charge), 0 (fault — measured resistance near zero; also occurs at key-off power-down). Updated each isolation test cycle (~27s period). Slow descent from 200 to 192 after startup reflects first few test cycles. B3=0 is causal only when it was at a valid non-zero reading immediately before the trip. Scale (kOhm/MOhm per count) not determined. Not in EPRI plist. See `notes/isolation-fault-analysis.md` Phase 2. |
| 0x63C | B6 | Generator RPM secondary (scale 16 rpm/count, offset −96) | r=0.9975 vs OBD PID 0x0C (valid range only). Overflows above ~4000 RPM (B6 wraps 255→0, no carry). Overflow detected during purposeful generator overheat test - suspect nominal limit Via programs is 4000rpm (also aligns with generator peak power investigation). Use 0x054 B0-B1 for all RPM analysis. Not added to DBC due to overflow. 50 Hz. |



### Battery / Contactor Operational Flow (0x0400 hsc_bcm_* bits)

0x0400 is **BMS-sourced** (drops with BMS LV connector; previously incorrectly assumed VCU-sourced). B0 carries four bits: `hsc_bcm_enable` (bit 0), `hsc_bcm_epo` (bit 1), `hsc_bcm_mainc_close` (bit 2), `hsc_bcm_leakage_ena` (bit 3). Observed across 20 charge sessions plus fault logs:

- **hsc_bcm_leakage_ena** is always 1 — never changes during any logged session.
- **hsc_bcm_epo**: 0 in all normal charges and all post-swap inverterFault sessions (charger-internal fault, BMS not involved). Asserts (B0=0x0A) in pre-swap BMS-EPO charge faults — 82–182ms AFTER 0x410 B1 completes its fault latch. Asserts in interlock faults ~175ms after HVIL opens (0x410 B0 bit3 clears), before B1 steps. Asserts in isolation faults simultaneously with B1=0xF0. **hsc_bcm_epo is always reactive — it never precedes a fault.**
- **hsc_bcm_enable** and **hsc_bcm_mainc_close** pulse together (0→1→0) during the precharge/contactor-close sequence at session start, then return to 0 for the remainder of the charge session.
- At the point of `inverterFault` failure: enable=0, epo=0, mainc_close=0, leakage_ena=1 in every session — the BCM is issuing no control commands when the charger faults. The failure is charger-internal; no BCM command precedes or accompanies it.

### Parts-Truck-Only Messages (Unexplained)

Two IDs appear on the parts truck PT bus but are completely absent from the main truck in every tested condition (drive, charge, export, battery-disconnected):

- **0x391** (88 Hz) — present in both the no-battery parts truck log and the battery reconnect log (alongside active BMS), so not a BMS-absent fallback. Most likely a VCU software version difference. Cause unconfirmed.
- **0x61E** (10 Hz, DLC 1, data=0x01) — same pattern. Not present in the reconnect log despite 0x391 being active; may only appear early in session or be suppressed once BMS is stable.

Evidence summary across four log conditions (2026-04-11 analysis):

| Log | 0x391 | 0x61E | BMS (0x411) |
|-----|-------|-------|-------------|
| Main truck drive (Aug 2025) | 0 | 0 | present |
| Main truck charge — truk1log (Oct 2025) | 0 | 0 | present |
| Parts truck no battery (Feb 2026) | 4,003 | 438 | 0 |
| Parts truck battery reconnect (Apr 2026) | 2,137 | 242 | present |

### How to Tell the Two Trucks Apart

The Vtrux project has two trucks: the main truck (actively used) and the parts truck (donor vehicle). Two methods exist depending on which buses are captured.

**Parts truck vs main truck differences:** The parts truck is WT1 trim; the main truck is WT2 (see `notes/rpo/rpo.md`). The parts truck does not have the APP GEN MOD (see `notes/app-gen-mod-investigation.md`). The PE water pump is present on the parts truck but not hooked up to CAN. The parts truck's HV battery was removed but is being reinstalled.

**Parts truck hardware status (as of Apr 2026):** Both trucks have the same drivetrain architecture including the generator. The only hardware difference is the PE water pump — present on the parts truck but not hooked up to CAN. The parts truck's HV battery was removed but is being reinstalled. HCU software version: Both trucks: **v3.23** across every log. No version differences.


**Method 1 — VIN from GMLAN (OBD or Vehicle bus captures only)**

GMLAN broadcasts VIN on two standard IDs at ~1 Hz:

| ID | Content | Encoding |
|----|---------|----------|
| 0x4E1 | VIN digits 10–17 | ASCII, 8 bytes |
| 0x514 | VIN digits 2–9 | ASCII, 8 bytes |

| Truck | 0x514 (digits 2–9) | 0x4E1 (digits 10–17) | Full VIN |
|-------|-------------------|----------------------|----------|
| Main truck | `GCUKPEH2` | `EG488714` | `3GCUKPEH2EG488714` |
| Parts truck | `GCUKPEHX` | `EG537190` | `3GCUKPEHXEG537190` |

Both are 2014 model year (`E` in position 10). Source logs: main truck from `vtruxcodereading.log` / `vtruxscottsvalleydrive.log`; parts truck from `vtrux__partstruck_reconnect.log`. **These IDs do not appear on PT-bus-only captures.**

**Method 2 — Odometer from PT bus (works on PT-bus-only captures)**

0x625 B0-B2 (24-bit BE, **1 km/count confirmed**) encodes vehicle odometer on the PT bus and differs clearly between trucks. Scale confirmed against known physical mileage of both trucks (main ~60k miles, parts ~27k miles):

| Truck | 0x625 B0-B2 | Odometer |
|-------|------------|----------|
| Main truck | `01 75 xx` range | ~95,500–97,500 km (~60k miles), Aug 2025–Mar 2026 |
| Parts truck | `00 AC CA` | ~44,234 km (~27k miles), Apr 2026 |

The parts truck has roughly half the odometer of the main truck. This is the only truck-identification method available for PT-bus-only logs. Used to confirm that `truk1log_M1` (Oct 2025, `01 75 56` = 95,574 km) is the main truck, not the parts truck as previously mislabeled.

### PT Bus Disconnect Test Evidence

**Logs:** T1/T2 from `logs/vtruxunplugpumpthenhvbatterylvconnector.log` (PE pump CAN
unplugged ~t=34s; HV battery LV connector unplugged ~t=75s, reconnected ~t=87s; 12V
battery cycled ~t=118s; key-on ~t=130s). T3 from `logs/vtruxwoodwardbconnectordisconnected.log`.
Full test notes: `notes/can-disconnect.md`.

**Direct attribution from disconnect tests:**

| Test | What disconnected | IDs attributed |
|------|------------------|----------------|
| T1: Pump CAN | PE pump CAN connector physically unplugged | **0x18FF0320** — only ID that drops; immediate. Source: PE coolant pump (EMP WP29 C20, SA=0x20). |
| T2: BMS LV | HV battery LV connector (powers BMS board) | **0x370–0x375, 0x400, 0x410–0x412, 0x420, 0x430, 0x440, 0x460 (PT bus), 0x506, 0x507** — all drop by t=75.2s on PT bus. Source: BMS board. Note: 0x460 also appears on a GM bus from an unrelated source; only the PT bus instance is BMS-attributed. |

**What these tests do not directly attribute:**

- **~30–33s cascade after BMS LV pull (t=107–108s):** A group of IDs stop 32–33s after
  the BMS disconnects — 0x474, 0x478, 0x480, 0x481, 0x55C, 0x580, 0x619, and the
  generator inverter / DCDC / EAC J1939 cluster. The delay is consistent with either a
  module-internal comms-loss watchdog or the VCU commanding shutdown after detecting a
  BMS fault — the test does not distinguish between these. The timing tells us nothing
  about module identity or power source. Attribution for individual IDs in this group
  comes from other evidence (EPRI DBC / Ghidra decompile / J1939 SA). 0x480, 0x481,
  0x580, 0x619, 0x681 remain unresolved.
- **12V battery cycle (t=118s):** A separate deliberate step in the same log. Cuts the
  entire 12V bus — all remaining modules go dark simultaneously. Provides no individual
  module attribution.
- **0x483:** Absent from this log entirely — likely only broadcasts during active motor
  operation. Cannot be evaluated from this test.

**Observation — Bel charger/inverter (SA=0xC0) during BMS disconnect:**
0x18FFD4C0, 0x18FFD7C0, and 0x18FECAC0 appear at t=74.9s (coinciding with the BMS
disconnect) and stop at t=89.5s (~1.8s after BMS reconnect at t=87.7s). These IDs are
absent in all normal operating logs and absent in parts truck logs despite the Bel unit
being present. Trigger mechanism unknown. See `notes/can-disconnect.md`.

### Common Encoding Pattern

Many powertrain signals use **unsigned 16-bit centered at 32768** (offset binary):
`value = raw - 32768` where 32768 (0x8000) = zero/neutral.

---

## Known Signals — GM Buses (Experimentally Determined)

**Note:** EPRI-confirmed encodings in the section above take precedence where signals overlap (0x00C9, 0x01C3, 0x03D1, 0x03E9, 0x04C1).

Use `GMW8762_PPEI_GMLAN.dbc` to decode. Key messages:

### Traction Inverter Commands (OBD bus — `vtrux-obd-experimental.dbc`)

Confirmed 2026-03-29. See `notes/traction-inverter-control.md` for full investigation.

| CAN ID | Bytes | Signal | Encoding | Notes |
|--------|-------|--------|----------|-------|
| 0x041 | B1-B2 | TRAC_TrqCmd — VCM-to-TRAC torque command | LE uint16, centered at 32768 (neutral=0 Nm); >32768=motoring, <32768=regen. 100 Hz, DLC=6. Scale 0.125 Nm/count (UNCONFIRMED — inferred from GENE symmetry). | B0=status nibble (8-11 observed). B3=0xFF, B4=0x7F constants. B5=rolling counter nibble 0x0-0xF. r=0.9994 vs feedback (full log). Bidirectional: max +380 Nm motoring, −287 Nm regen (climit log); max −42.6 Nm during cruise downhill. |
| 0x442 | B0-B1 | TRAC_TrqFbk — TRAC MCU torque feedback | LE uint16, centered at 32768. ~98 Hz, DLC=7. Scale 0.125 Nm/count (UNCONFIRMED — inferred from GENE symmetry). | r=0.9998 vs 0x5A2 B4-B5 (VCM rebroadcast). B3, B5=low-entropy status bytes. B6=rolling counter nibble (0x00/0x10/0x20/... steps). Structurally symmetric to 0x471 (GENE feedback, PT bus). Scale plausibility: at 0.125 Nm/count, peak observed motoring torque is +3040 counts = +380 Nm (climit log, hard acceleration). BorgWarner 32-01 eGearDrive longitudinal transmission (Vtrux) is rated 350 Nm peak input torque (`notes/borgwarner-transmissions.pdf`); the ~9% overshoot is consistent with a transient peak above continuous rating. |

### Brake-Related Signals (OEM-Specific — Not in GMLAN Standard DBC)

Investigation 2026-03-08 using `movingaroundindriveway.log` and `vtruxanotherevaplogpart1.log`.
Event-based scan (press consistency + recovery score) + Pearson vs pedal and EBCM reference (0x2F9 B5).
**Vacuum reservoir refill signal not yet conclusively identified.** See Next Steps.

| CAN ID | Bus | Bytes | Signal | Encoding | Notes |
|--------|-----|-------|--------|----------|-------|
| 0x1FC | Vehicle | B4-B5 (BE) | Brake applied pressure (not vacuum) | BE uint16: `(B4<<8)\|B5`, range 0-3618 | Increases when brake pressed, shape matches EBCM 0x2F9. B4=MSB (0-14, low toggle), B5=LSB. Responds instantly to pedal — tracks applied pressure, not reservoir vacuum. Confirmed 2026-03-08. Scale unconfirmed. |
| 0x0BE | OBD | MUX (B0=key: 0/4/8/12) | Applied pressure (B1) + inverse (B5) | DLC=6, 133 Hz | B1 mirrors brake pedal (Pr_ped≈1.00). B5 drops from ~255 on press (Pr_ebcm=−0.85, inverse). Neither shows delayed post-release recovery. B4=binary validity flag. Not the vacuum reservoir signal. |
| 0x0F1 | Vehicle + OBD | B0 | Candidate: vacuum state (coarse) | uint8, only 12 unique values (0-126), 200 Hz | RecSc=0.700 (highest of all candidates), suggesting slow recovery after release. B1 mirrors applied pressure (Pr_ped=0.9987). B0's coarse quantization may indicate a state machine rather than raw ADC. Inconclusive — needs a log with single brake events separated by 10+ seconds to see the pump refill curve cleanly. |

| CAN ID | Message | OBD Bus | Vehicle Bus |
|--------|---------|-----------|----------------|
| 0x0C1 | Driven_Wheel_Rotational_Status | **Masked to zeros** | **Real** wheel distance pulse counter |
| 0x0C9 | Engine_General_Status_1 | **Real** engine RPM (`(B1<<8|B2)*0.25`) | **VCM synthetic ~800 RPM** (motor idle; ignore) |
| 0x1C3 | Engine_Torque_Status_2 | **Real** engine torque (wide range when engine on) | **VCM modified** (motor torque substituted) |
| 0x1F5 | Transmission_General_Status_2 | **Frozen at Park** — all 8 bytes constant (B0=B1=0x0F, B3=0x01); never shows Drive, Reverse, or Manual even when truck is moving. Neutral briefly leaks through (~15 frames) during shift transients. VCM-generated (no real TCM). | **Real** — B3 bits 3–0 = lever position (Park/Rev/Neu/Drive/Manual); Manual (9) confirmed in generator log at 22% of frames during generator operation. VCM-generated from Via custom shift position sensor. |
| 0x3E9 | Vehicle_Speed_and_Distance | **Broadcast frozen at zero** (cascade: ECM receives masked-zero wheel speeds → computes zero → broadcasts zero). | Real on Vehicle bus (VCM-generated from real wheel data). OBD PID 0x0D via standard DLC returns real speed — VCM answers at 0x7E8 on the Vehicle bus from its own wheel speed data. |
| 0x1E1 | Cruise_Control_Switch_Status | Present on both GM buses at 33 Hz, DLC=7 (standard says 8 — byte 7 absent). B0 button bits always 0x00 (VCU suppresses button events). B5 is a non-standard VCU extension encoding cruise state as brief pulses (tiers 16–28 baseline, 48–60 setpoint-decrement, 80–92 engagement/cancel). See Cruise Control section below. | Same content on both buses |

---

## Documented Behavior

### Peak Operating Points

Generator peak generating: **-144.7 kW** (DC, V*I from 0x482). Traction peak motoring: **+183.9 kW** (DC, V*I from 0x462). Traction peak regen: **-94.2 kW**. All from evap drive logs.

See `notes/peak-operating-points.md`.

### Cruise Control

VCU-implemented; operates in both EV-only and hybrid modes. The VCM closes the speed loop via a continuously-varying traction torque command on 0x041 B1-B2 (OBD bus) — not throttle simulation. Speed setpoint is in 0x644 B2[3:0]:B3 (0.125 km/h/count). 0x1E1 B5 is a non-standard VCU extension encoding cruise state transitions as brief tier pulses (not in GMLAN DBC).

See `notes/cruise-control-analysis.md` and `notes/traction-inverter-control.md`.



---

### Evap Purge Mode Charging — 80% SoC Ceiling

When plugged in during evap purge mode, the VCM enforces a hard 80% SoC ceiling. CC runs normally to 80%, then the charger executes a brief retry and transitions to a distinctive two-step CV hold (~-6A then ~-2.2A) with SoC clamped at exactly 80% indefinitely. **Correction 2026-09-19:** `vcm_evap_active` (0x649 B4 bit 7) IS broadcast and set during stationary charging when a purge is pending -- 1 from the first frame of every 80 % ceiling session (3/3) and 0 in every other charge session (16/16 Low Power commands); see the interposer bench evidence (internal-only). The earlier statement that the 0x649 flags are inactive during charging was wrong for this flag.

See `notes/after-battery-swap-charge-fail-analysis.md` and `notes/evap-cycle-analysis.md`.

### Charge Termination — Two Different Mechanisms (2026-09-02)

The VCU ends a charge by sending `0x18EFC000` page 00 with `cmd_Mode` = 3 (**Charger Low
Power Mode** — not a completion state; see `notes/powertrain-messages.md`). It does so for
two quite different reasons, and **the BMS charge-current permission is what tells them
apart**:

| | genuine top of charge | evap 80 % ceiling |
|---|---|---|
| Trigger | `bcm_chg_max` walked to ~0 as `bcm_cell_vmax` approached 3.600 V | VCU's own SoC comparison, 1.2 s after SoC reached 80 |
| `bcm_chg_max` at the stop | 0–2.75 A | **300 A — never moved** |
| `bcm_cell_vmax` at the stop | 3590–3594 mV | 3340 mV |
| Sessions | `vtrux_charge_M1`, `vtrux_partstruck_charge` | `vtruxchargeafterexportchargetest-80pctcv` |

Two consequences worth knowing:

- **The current collapse follows page 00, not the page-01 setpoint.** In the evap session the
  setpoint still commanded 19.5 A for 155 s *after* the charger had already dropped to
  −0.7 A. The mode is the stop; the setpoint follows later.
- **Top-of-charge voltage is controlled by max cell voltage, not pack voltage.** The
  commanded pack limit (429.2 V) is never reached — `vtrux_partstruck_charge` topped out at
  417 V. `bcm_cell_vmax` pins at 3.598–3.600 V while `bcm_cell_vmin` climbs and the pack sum
  rises; `bcm_chg_max` reaches 0 at vmax ≈ 3.59 V regardless of how far apart the cells are.

See `notes/powertrain-messages.md` -> 0x18EFC000. (The interposer bench
built on this is internal-only.)

### Cell Balancing Behavior

`bcm_balancing_cnt` (0x440 B7) counts cells currently being bled by the BMS bleed resistors; max is 116 (the full pack balancing simultaneously). Balancing first appears when the leading cells reach ~3400 mV, typically at 93-96% SOC. Initial spread at onset is 8-15 mV; it grows to 23-63 mV as cells traverse the steep LFP CC->CV knee at different times (cells with higher SOC hit the knee first, producing large voltage differences for small SOC differences), then collapses to a 2-3 mV settled equilibrium once cells have been balanced. The failed charge session never reached spread-collapse.

Count distribution spikes map to pack module architecture: 12 (12s small module), 52 (2x26s modules), 104 (4x26s modules), 116 (full pack). Values of 1, 103, 115 reflect single outlier cells finishing earlier or later than their module group.

Two distinct cnt=116 episodes occur per charge: a brief ramp transient at ~3400-3420 mV (~2 min) as all cells cluster at the LFP CC->CV knee, then a sustained phase at ~3595-3600 mV after the charger reaches CV.

January 2026 post-swap audit (4 sessions): another_M0 (Jan 23, 548 min, 9-hour balancing tail) had the widest bulk spread (9-17 mV), confirming the pack was most imbalanced then. The following Jan 25 session showed tightest spread (5-10 mV) and fastest convergence, confirming the Jan 23 marathon improved balance.

See `notes/balancing-investigation.md`.

### BMS Log Startup Artifacts

Two artifacts appear at the start of every log session (both laptop USB dongle and Android logger) that must not be mistaken for real data:

**1. Stale SoC at startup (all loggers):** The A123 BMS broadcasts exactly one 0x430 frame with max-value sentinel cell voltages as the very first message after power-on (caught by the DBC `max=3.8V` range on `bcm_cell_vmax`/`bcm_cell_vmin`). The 0x411 SoC broadcast paired with that sentinel frame reflects the BMS's last stored Coulomb count from non-volatile memory — the SoC at previous power-down — not the current state. The stale value falls within the normal SoC range and will not be caught by any range check. The BMS transitions to its freshly computed SoC within seconds to ~60s after the sentinel. **Measured 2026-09-24** (an internal-only wake-transient scan, 114 wakes where the logger was demonstrably up before the BMS): the wrong reading lasted 0.32-1.15 s, ~1.0 s in 105 of them, and read low in 112 of 113 (median 13.8 %, up to 20.9 %); it was not the value from before the BMS slept in any of 40 mid-capture wakes. The longer figure above was not reproduced where the start of the wake was actually captured. Treat the first 0x411 SoC reading in a session as suspect until cell voltages have stabilized. The stale and real values can differ by 10-20% or more depending on how much charge/discharge occurred since the last session. Confirmed across all logger types: S1 laptop stale=40.28%, S2 laptop stale=59.08%, S3 Android stale=76.5%.

**2. Bus number churn in Android T0 (Android logger only):** If the Android CAN adapter reconnects during session startup, each reconnect is assigned a new bus number by the logger. T0 of an Android session may contain frames on 10-20+ different bus numbers, with the PT bus accumulating gradually to become dominant. Use the anchor ID (0x051) to identify the bus with sustained high frame counts; discard buses with only a handful of frames. T1 onward is typically stable on a single bus number. Confirmed in 171127_T0 which had 22 distinct bus numbers; T1 and T2 were clean on bus 21.

### Engine Stall Behavior

Involuntary stalls observed during normal driving during evap purge (no fault codes). The VCM's generator wind-down logic holds the engine at minimum throttle longer than the ECM's DFCO threshold tolerates — ECM cuts fuel, VCM responds ~100ms too late, RPM free-falls to 0. Engine auto-restarts after ~7s. Hypothesis: control loop timing gap, not a hardware failure.

Separately, the truck sometimes cranks and fails to catch on a restart shortly after a VCM-commanded stop, never in evap mode so far. The VCM retries ~9.5 s later and raises no fault; see `notes/failed-generator-starts.md`.

### HV Operation and Fault Response

HV contactors are managed by the A123 BMS. The `hsc_bcm_*` bits (0x0400 B0) reflect HV system control state; 0x0400 is BMS-sourced (see Battery/Contactor Operational Flow). Contactor state is monitored via `bcm_mainc_stat` (4-bit field in 0x0440). `0x644 B0` (VCU-sourced) is the reliable leading indicator: in orderly shutdowns it precedes 0x410 by 14–21ms; during physical interlock faults it lags 7–12ms instead.

**Startup sequence** (0x410 B0: 0x09 → 0x19; relative times):
1. `0x644 B2/B6` change (VCU preparing, t−1.3s)
2. `0x400 B0`: 0x09 → 0x0D; `0x600 B0`: 0x22 → 0x26 (HV arming, t−0.9s)
3. `0x644 B0`: 0x08 → 0x10 (VCU commands contactor close, t−0.25s)
4. `0x411 B0/B1` change (contactor close request, t−0.1s)
5. `0x410 B0`: 0x09 → 0x19 (interlock confirmed, key-on mode active, t=0)

`bcm_mainc_stat` contactor sequence: 0 → 2 → 5 → 7 → 8 → 9 → **11** (normal running state). Total precharge duration ~6.8 seconds from HVIL closure to charge-ready.

**Correction 2026-09-02 — 11 is the DRIVING steady state; charging sits at 12.** Measured over whole sessions on the 4-bit `bcm_mainc_stat` in 0x0440: `vtrux_charge_M1` is 12 for 8,681 points and `vtruxchargeafterexportchargetest-80pctcv` for 9,180, both reached through the same precharge ladder and both leaving via 14 at shutdown. Any check for "contactors closed" must accept **both 11 and 12**.

**Normal shutdown** — `0x644 B0` steps 0x10 → 0x07 (14–21ms before 0x410 B0 changes). `0x410 B1` settles at 0x8F (fault flag clear). `bcm_mainc_stat`: 11 → 13 → 14 (two-step ordered sequence).

**Isolation fault** (injected test: 1 kΩ resistor to chassis) — BMS detects on periodic IMD test cycle (~27s interval); no CAN warning before trip:
- `bcm_gfd` (0x0410): 1000 → **0.0 V**, 150ms before EPO fires (leading indicator, not consequence)
- `bcm_alarm`: background TYPE2 → TYPE3 + epo=1, ~150ms after bcm_gfd
- `0x410 B1` 4-step ordered path: 0xBF → 0xB0 → 0xF0 → 0xC0, latches to 0xCF after ~9s
- `0x410 B2`: 0xA0 → **0x00** at first B1 step — isolation-specific indicator; absent from all other fault types (interlock, charge); settles to 0xFE
- `bcm_mainc_stat`: 11 → **14** directly (skips state 13 used in normal shutdown — abrupt trip vs ordered power-down)
- `0x410 B0 bit3`: stays 1 (interlock loop remains physically closed — isolation fault does not open the interlock)
- Fault latches; removing the resistor does not self-clear. Clear: 12V battery disconnect/reconnect.

**Interlock fault** (injected test: HVAC or HVD interlock connector pulled) — abrupt physical event:
- `0x410 B0 bit3` clears immediately (0 = loop open) — first signal on bus
- `0x644 B0` increases to 0x17 — 7–12ms AFTER 0x410 (reversed vs orderly shutdown where it leads)
- `0x400 hsc_bcm_epo` asserts ~175ms after HVIL opens — after 0x644 reacts but before B1 steps
- `0x410 B1` abrupt path: 0xBF → 0xFF → 0xCF (no intermediate ordered steps), ~200ms after HVIL opens
- `0x410 B2` stays 0xA0 throughout (not isolation-specific; settles to 0xFE)
- Fault latches; clear: 12V battery cycle.

**Charge fault** — BMS-commanded contactor opening:
- `0x644 B0` steps toward 0x07, ~11ms BEFORE 0x410 (same orderly leading pattern as normal key-off, but fault flag then sets ~300ms later)
- `0x410 B1` fault flag sets, settling to 0xCF
- Bel charger EPO / alarm3 / chgc_stat fire 1.1–1.5s after the triggering event as orderly HV de-energization — these are consequences, not causes
- No `bcm_gfd` transition (charge faults do not trigger the isolation alarm)
- Before-battery-swap failures: BMS-initiated EPO with consistent TYPE1 alarm (~10s grace) → TYPE3+EPO sequence across all sessions. Root cause unknown — cell overvoltage was ruled out (vmax hit the 3.600V ceiling but never exceeded it)
- Post-swap failures: Bel charger hardware defect (inverterFault, shutdownSource=3); BMS was not initiating disconnect

**Fault latch behavior:** All fault types latch `0x410 B1 bit6` (0xCF final state). Self-clear does not occur — 12V battery cycle (disconnect/reconnect) is required to clear the latch. Fault state persists through key-off.

See `notes/isolation-fault-analysis.md`, `notes/interlock-bitfields-analysis.md`, `notes/before-battery-swap-failed-charge-analysis.md`, `notes/after-battery-swap-charge-fail-analysis.md`.

---

### HV Bus Voltage Measurement Sources

Three independent HV bus voltage measurements are visible on the PT bus, each from a different module:

| Source | ID / field | Scale | Rate | Character |
|--------|-----------|-------|------|-----------|
| BMS internal sense | `0x0440 bcm_vbus_pos` | 12-bit Motorola, 0.25 V/count | BMS frame rate | Lowest lag; tracks the bus in near-real-time |
| Sanden EAC compressor | `0x0870A047 B2` (`eac_hv_input`) | 4 V/count | 10 Hz | Filtered + low rate; lags during fast transients |
| GENE inverter | `0x0482 GENE_HighPwr_Volt` | 11-bit LE, 1 V/count | — | Only present when GENE MCU is awake (boots ~1s into precharge) |

**Steady state:** all three agree within ~±4 V (one EAC count). Confirmed across driving, idle, and charging in `notes/hvac-investigation.md`.

**Fast transients (precharge, contactor open/shutdown):** the EAC reading lags the BMS `bcm_vbus_pos` by ~50–100 ms. The EAC source broadcasts at only 10 Hz and is internally filtered (~one cycle behind), so during a rapidly changing bus its samples report the bus state from up to ~100 ms earlier. This can make EAC appear to *rise after* a contactor-open/shutdown event — an artifact of the lag reporting the still-rising pre-shutdown bus, not a real post-shutdown rise. Example (failed precharge, `debuglog_M4_T20.log`): at the ALL_OPEN_SHUTDOWN instant the BMS read 367 V while EAC still read 336 V; the matching 368 V did not appear on EAC until ~100 ms later, after which EAC began its true decay.

**Guidance:** for timing-sensitive analysis during fast transients, use BMS `bcm_vbus_pos` (0x0440). The EAC reading is suitable for steady-state HV monitoring only — its 4 V quantization and 10 Hz filtered lag make it unreliable for sub-100 ms timing. See `notes/hvac-investigation.md`.

---

### Current Limiting Behavior

**BMS current limit broadcasts — 0x420 B0-B2 (EPRI-confirmed, 12-bit Motorola nibble-split):**
- `bcm_chg_max`: maximum charge (regen) current, 0.25 A/count
- `bcm_dis_max`: maximum discharge current, 0.25 A/count
- Packed layout: B0 = dis_max upper 8 bits; B1 split (upper nibble = dis_max lower 4 bits, lower nibble = chg_max upper 4 bits); B2 = chg_max lower 8 bits

**BMS charge current ceiling — 0x412 B2:** 8-bit byte tracking bcm_chg_max during charging sessions (r=0.999 vs 0x050 CCL signal; VCU tracks it closely during charging, scaling ~1.184). During driving B2 is static at a high value (BMS holds full permission at drive SoC); 0x050's dynamic driving behavior comes from VCU-internal logic, not from B2. Relationship to 0x420 B2 (bcm_chg_max lower byte) is an open question — see `notes/current-limits-investigation.md` Phase 4.

**VCU effective limit message — 0x050** (10-bit unsigned: `(B1 & 0x03)<<8 | B0`, 9.1 Hz, VCU-sourced):
- Dynamic CCL setpoint — moves with DC bus activity, not a static limit
- Nominal ~292 raw during unconstrained driving; varies with bus conditions
- Drops to floor (~43 raw) when CCL fully engaged (regen blocked)

**CCL ramp during charging (another_M0 session, SoC 25%→100%):**

| SoC | 0x050 CCL raw | bcm_chg_max approx |
|-----|---------------|--------------------|
| 25–74% | ~300 | ~300 A — full limit |
| 74–91% | 300→232 | gradual decline begins ~80% |
| 91–99% | 232→10 | steep drop |
| 99%+ (CV taper) | ~10 | floor; stays flat while current tapers |

**Regen limiting during driving:** VCU pre-limits 0x050 ~5.9s before bcm_chg_max broadcasts its ramp; once bcm_chg_max drops below the VCU pre-limit equivalent the BMS becomes the binding constraint and VCU follows it down. bcm_chg_max floor is ~60 A; VCU command reaches its functional minimum (~43 raw) one frame before bcm_chg_max reaches 60 A. The VCM-internal trigger for the pre-limit is not identified.

**Discharge limiting:** bcm_dis_max stays constant at 612 A throughout all observed drive events including confirmed DCL-active spans. Discharge limiting is entirely VCM-internal; no BMS setpoint change is visible on the bus during discharge limit events.

See `notes/current-limits-investigation.md`.

---

### Thermal Limiting Behavior

Both the generator (GENE) and traction (TRAC) inverter/motor pairs broadcast thermal load indicators as a percentage of thermal capacity, plus cooling flow requests for their respective loops.

**Generator inverter thermal — PT bus (EPRI-confirmed):**
- `GENE_ThermInd_pct` (0x479 B2, 0.78125%/count): rises monotonically under sustained load. Confirmed derate onset: **~85–86%** (sustained generator torque cutback follows; ~120s between 80% crossing and cutback onset in overheat test log)
- `GENE_DrvCoolFlowReq_pct` (0x479 B0): PE glycol loop request; ~50% at normal load, rises toward 100% under sustained thermal stress
- `GENE_MotCoolFlowReq_pct` (0x479 B1): generator motor oil loop request; 0% when generator idle, saturates at 100% under sustained stress. Note: generator oil pump is relay-controlled (binary on/off) — the percentage output's mapping to actual pump state is not yet confirmed

**Traction inverter thermal — OBD bus (confirmed); PT bus mirror:**
- `TRAC_ThermInd_pct` (0x44A B2, 0.78125%/count): symmetric to GENE. Confirmed derate onset: **~78–79%**
- PT bus mirror: `trac_therm_ind_pct` (0x06000002 B5/B6, 10-bit LE, ~1%/count integer percent); r=+1.000 vs OBD 0x44A B2 — VCU reads from OBD bus and re-broadcasts on PT bus
- `TRAC_DrvCoolFlowReq_pct` (0x44A B0): PE glycol loop request, symmetric to GENE 0x479 B0
- `TRAC_MotCoolFlowReq_pct` (0x44A B1): traction motor oil loop request; same behavior as GENE B1

See `notes/thermal-investigation.md`.

---

### Generator Peak Power and RPM

*Investigation in progress. See `notes/artifacts/gen_torque_peak.py` for the analysis script.*

---

## Pinouts

### HV Battery Interlock Loop Order

The high-voltage interlock loop within the battery passes through each HV connector in this order:

1. LV Connector to Charger L
2. Charger R to DCDC Top
3. DCDC Bottom to HVAC Bottom
4. HVAC Top to Generator R
5. Generator L to Traction R
6. Traction L to Fuse Panel Switch
7. Fuse Panel Switch to HVD

### BMS LV Connector Pinout

Partial pinout for the HV battery LV connector (entries with `?` are unconfirmed, `-` are empty):

| Pin (Left col) | Pin (Right col) |
|----------------|-----------------|
| GND            | ?               |
| ?              | ?               |
| ?              | ?               |
| GND            | ?               |
| ?              | —               |
| —              | ?               |
| —              | ?               |
| —              | HVIL IN         |

### Woodward ECM-5554 Connector A (Black) — Signal Names

MotoTron P/N: CONFEML051 | Molex P/N: 98944-2001-32 | Woodward P/N: 1635-1768 | 32 pins

| Pin | Signal | Pin | Signal | Pin | Signal | Pin | Signal |
|-----|--------|-----|--------|-----|--------|-----|--------|
| A-A1 | EST 4 | A-A2 | EST 3 | A-A3 | EST 2 | A-A4 | EST 1 |
| A-B1 | EST 8 | A-B2 | EST 7 | A-B3 | EST 6 | A-B4 | EST 5 |
| A-C1 | TACH | A-C2 | RS485- | A-C3 | RS485+ | A-C4 | DRVG 3 |
| A-D1 | LSO13 | A-D2 | FUELPR | A-D3 | MPRD | A-D4 | XDRG 2 |
| A-E1 | LSO2 | A-E2 | LSO8 | A-E3 | LSO9 | A-E4 | LSO10 |
| A-F1 | LSO3 | A-F2 | LSO1 | A-F3 | FUEL/INJ 7 | A-F4 | FUEL/INJ 8 |
| A-G1 | FUEL/INJ 5 | A-G2 | FUEL/INJ 6 | A-G3 | FUEL/INJ 3 | A-G4 | FUEL/INJ 4 |
| A-H1 | FUEL/INJ 1 | A-H2 | FUEL/INJ 2 | A-H3 | LSO12 | A-H4 | LSO11 |

### Woodward ECM-5554 Connector B (Brown) — Signal Names

MotoTron P/N: CONFEML052 | Molex P/N: 98950-2003-48 | Woodward P/N: 1635-1769 | 48 pins

| Pin | Signal | Pin | Signal | Pin | Signal | Pin | Signal |
|-----|--------|-----|--------|-----|--------|-----|--------|
| B-A1 | Powertrain CAN1+ | B-A2 | Powertrain CAN1- | B-A3 | BATT 2 | B-A4 | AN16M |
| B-B1 | Vehicle CAN3- | B-B2 | Vehicle CAN3+ | B-B3 | CANSHIELD3 | B-B4 | AN21M |
| B-C1 | OBD CAN2+ | B-C2 | OBD CAN2- | B-C3 | CASEGND | B-C4 | AN18M |
| B-D1 | KNK1+ | B-D2 | KNK1- | B-D3 | XDRG 1 | B-D4 | AN19M |
| B-E1 | KNK2- | B-E2 | KNK2+ | B-E3 | AN1M | B-E4 | AN28M |
| B-F1 | AN2M | B-F2 | AN3M | B-F3 | AN14M | B-F4 | AN26M |
| B-G1 | CAM (DG) | B-G2 | SPEED 1 (DG) | B-G3 | AN27M | B-G4 | ECUP |
| B-H1 | SPEED 3 (DG) | B-H2 | SPEED 2 (DG) | B-H3 | STOP | B-H4 | CNK (DG) |
| B-J1 | CNK- (VR) | B-J2 | CNK+ (VR) | B-J3 | O2C- | B-J4 | O2D- |
| B-K1 | O2A+ | B-K2 | O2B+ | B-K3 | O2C+ | B-K4 | O2D+ |
| B-L1 | O2A- | B-L2 | O2B- | B-L3 | AN20M | B-L4 | EST RTN |
| B-M1 | LSO6 | B-M2 | LSO7 | B-M3 | LSO4 | B-M4 | LSO5 |

### Woodward ECM-5554 Connector C (Grey) — Pinout

MotoTron P/N: CONFEML054 | Molex P/N: 98944-3002-32 | Woodward P/N: 1635-1771 | 32 pins. Harness-side mating connector is P24 (VIA Motors part 64319-3218). **Bold** = confirmed from VIA Motors HVIL-debug.pdf (P24 pinout); unconfirmed entries show Woodward ECM signal name only.

| Pin | Signal | Pin | Signal | Pin | Signal | Pin | Signal |
|-----|--------|-----|--------|-----|--------|-----|--------|
| C-A1 | **PTC_OUTLET_TEMP** | C-A2 | AN6M | C-A3 | **VAC_PRES_SIG** | C-A4 | AN8M |
| C-B1 | **GBLP_A** | C-B2 | **GBLP_B** | C-B3 | **GBLP_C** | C-B4 | **GBLP_P** |
| C-C1 | **GBLP_PNP** | C-C2 | AN29M | C-C3 | AN4M | C-C4 | **APP1_PEDAL** |
| C-D1 | **APP2_PEDAL** | C-D2 | AN32M | C-D3 | **MIL_ECM** | C-D4 | **5V_REF_A** |
| C-E1 | AN31M | C-E2 | **HVAC_REQ** | C-E3 | **HVAC_TEMP_SEL** | C-E4 | **5V_REF_B** |
| C-F1 | AN25M | C-F2 | AN7M | C-F3 | AN30M | C-F4 | **HCU_VBAT1** |
| C-G1 | **CHASSIS_GND_HCU** | C-G2 | **CHASSIS_GND_HCU** | C-G3 | **HCU_DRVP1** | C-G4 | HBRIDGE1A [H1+] |
| C-H1 | **GEN_F_TERM_PWM** | C-H2 | HBRIDGE2A [H2+] | C-H3 | **HCU_DRVP2** | C-H4 | **ESS_HVIL_DRV** |

*C-H4 (ESS_HVIL_DRV) is the HV battery HVIL signal. Continuity from C-H4 to MDS HVIL pin should be <5 ohms.*

---

## File Layout

```
projects/vtrux/
  README.md                       # This file — project overview & entry point
  vtrux-powertrain-experimental.dbc  # Self-confirmed PT bus signals not in EPRI data
  vtrux-obd-experimental.dbc         # Self-confirmed OBD bus signals not in EPRI data
  deprecated/
    vtrux-powertrain.dbc          # Superseded — signals migrating to vtrux-powertrain-experimental.dbc
  BelInverter-v2.dbc              # Bel charger/inverter DBC — current (EPRI-merged)
  GMW8762_PPEI_GMLAN.dbc          # GM PPEI GMLAN standard DBC (51 messages, complete)
  gm bus messages.txt             # Early GM bus message notes
  notes/                          # Research notes & signal findings (see notes/README.md)
    README.md                     # Index of all notes files
    powertrain-messages.md        # PRIMARY signal catalog — powertrain bus
    threebusinvestigation.md      # Bus topology, OBD passthrough, scanner timing, per-log bus mappings
    context-voltage-current.md    # HV voltage/current investigation — methodology, scans, ECU hypotheses
    ENGINE-GENERATOR-CORRELATION.md  # Via engine data spoofing — critical finding
    status-bits-cross-log-comparison.md  # Generator status bits — identification + cross-log validation
    failed-charge-analysis.md     # Failed charging sessions — fault sequence
    full-charge-then-fail-summary.md  # Full-charge-then-fail event summary
    normal-vs-failed-shutdown.md  # Normal vs fault-state shutdown comparison
    after-battery-swap-charge-fail-analysis.md  # Post-battery-swap charge failure analysis (inverterFault/src=3 pattern)
    charging-vs-exporting.md      # Vehicle power modes: charging, export, driving
    deprecated/highway-drive-cycle.md  # ARCHIVED — 0x053 state machine extracted to powertrain-messages.md; 0x420 section stale
    after-fix-charge-sessions.md  # Post-repair charging session analysis
    bitfields-investigation.md    # Bit field analysis across BMS/status messages
    interlock-bitfields-analysis.md  # 0x410 bit-field analysis, shutdown precursors, message source attribution
    evap-cycle-analysis.md        # Evap canister purge cycle — 0x649 B4 bit7 flag + B2/B3 counter, OBD ruling-out, completion timing
    cruise-control-analysis.md   # Cruise control investigation — 0x1E1 B5, command mechanism, hybrid-mode torque cmd
    failed-generator-starts.md   # Starts that crank and do not catch (no inhibitor): 8 in 3 captures, VCM/ECM response
    battery-thermals.md          # Battery pack cooling — 0x508/0x506-bit5 cooling-active signature, 12V step, thermal trigger model
    artifacts/                    # Generated data files — see artifacts/README.md
      README.md                   # Provenance inventory
      *.py                        # Analysis scripts
      *.json                      # Survey outputs
      *.csv                       # Timeseries extracts
      *.txt                       # Status event outputs
      ratios.png                  # Drivetrain gear ratio reference
      Torque-command-identification.pdf  # Original ChatGPT session printout
    plans/                        # Investigation and implementation plans
      plan-status-codes.md        # Status code byte investigation plan
      documentation-cleanup.md    # Documentation reorganization plan
      gen-inhibit-wican-implementation.md  # Generator inhibitor: the narrative
      gen-inhibit-outstanding-work.md      # Generator inhibitor: the work queue,
                                  #   handed off 2026-10-07. Start here for what
                                  #   is open, including one spec/firmware
                                  #   divergence (`bus_on`) that is live.
      interposer-outstanding-work.md       # Charge interposer: its work queue
  logs/                           # All CAN capture log files (see logs/README.md)
    README.md                     # Log inventory and session descriptions
    after fix charge/             # Post-repair charging captures
  gmlan-info/                     # GM PPEI GMLAN spec and extracted DBC (see README.md)
    README.md                     # Directory overview
    GMW8762_PPEI_GMLAN.dbc        # Working copy (canonical copy at project root)
    EXTRACTION_COMPLETE.md        # Extraction summary and verification status
    README.md                     # Directory overview
    BelInverter.dbc               # Source reference — superseded by BelInverter-v2.dbc at project root
  CANsmog/                        # Generator control scripts and preliminary DBC (see README.md)
    README.md                     # Directory overview
    preliminary-dbc.dbc           # Initial DBC with 0x051 torque command definition
  tools/                          # Vtrux-specific CLI analysis tools (see tools/README.md)
    README.md                     # Tool inventory
```

---

## Next Steps

1. ~~Resolve power vs current ambiguity for 0x598~~ **DONE — confirmed POWER (0.01 kW/count)**. Corrected 2026-03-29: original "confirmed CURRENT" was based on weak charging-phase correlations. Cross-corr of B2-B3 generator channel vs GENE_HighPwr_Curr × GENE_HighPwr_Volt (evap4part2) shows power scale locked at 0.01007 kW/count across all segments, matching EPRI decompile exactly. Analog gauge anchor (0.04 A/count) was ~50% inflated; digital references (export panel, evap-purge flatline) are consistent with 0.01 kW/count. Channel roles confirmed (A=battery, B=generator, C=drivetrain). See `notes/powertrain-messages.md` 0x598 section.
2. Fully confirm 0x5A2 motor RPM with tachometer ground truth
3. ~~Extract and validate 0x63C generator RPM byte details~~ **DONE** — 0x63C B6 confirmed as generator RPM (r=0.9975 vs OBD PID 0x0C, scale=16 RPM/count, zero at B6=6). See `notes/artifacts/vtruxevaplog4_rpm_correlation.txt`.
4. ~~Map remaining DCDC signals in 0x18FFD6B3 and other DCDC IDs; build DCDC DBC~~ **DONE** — All four DCDC signals confirmed in `epri-pt-bus.dbc` (`EPRI_DCDC_18FFD6B3`): LV voltage (B0-B1), LV current (B2-B3), HV voltage (B4-B5), temperature (B6-B7). No separate DCDC DBC needed.
5. ~~Investigate GMLAN cluster (0x470-0x484) as potential HV voltage source in drive logs~~ **DONE** — 0x482 and 0x470 confirmed as post-contactor HV DC bus voltage (r=0.9974; 1 V/count integer encoding confirmed in `vtruxevapdrivelog4part2.log`). 0x440 B3-B4 was initially classified POST_CONTACTOR by interlock test but **rejected as real-time voltage** (2026-03-06) — flat during all drive-log load events, same latched behaviour as 0x420. Only two confirmed real-time HV voltage sources remain: 0x482 and 0x470 (plus DCDC 0x18FFD6B3 B4-B5). No pre-contactor pack voltage found on CAN. See `notes/context-voltage-current.md`.
6. ~~Design custom logger with active OBD2 requests to capture real engine RPM~~ **DONE** — Real engine RPM available passively on OBD bus via 0x0C9. See `notes/ENGINE-GENERATOR-CORRELATION.md`.
7. ~~Identify MI-EV36-BNKx compressor CAN IDs~~ **DONE** — 0x0868A047 (EAC_STATUS1) and 0x0870A047 (EAC_STATUS2), SA=0x47, confirmed as Sanden MI-EV36-BNKx HV AC compressor (EAC). EAC_CompHVInput (B2 x4 V/count) confirmed; remaining bytes under investigation. See `notes/hvac-investigation.md`.
8. ~~Add 0x482 voltage signal~~ **DONE** — 0x482 HV voltage/current confirmed from EPRI decompile (`GENE_HighPwr_Volt`/`GENE_HighPwr_Curr` in `epri-pt-bus.dbc`). 0x470 decode status unclear — was in deprecated `vtrux-powertrain.dbc` but not in EPRI DBC; needs review.
9. Investigate fault-only messages (0x473, 0x474, 0x478, 0x1CEBFFB3/0x1CECFFB3) discovered during interlock test — fault diagnostic data from Bel DCDC via J1939 TP
10. Investigate 0x18FECAB3 as DCDC enable/control message (only broadcasts when contactors are closed)
12. **[MEDIUM]** Compare `logs/vtruxchargeafterexportchargetest-80pctcv.log` against `logs/vtruxevapdrivelog4.log` for common evap-cycle signal activity: does 0x600 B3 (evap stage counter) step through purge stages during the stationary charge, and are generator flags / generator RPM / other evap markers active? Goal: determine whether the VCM runs the same evap logic path during a charge session or a simplified subset. A good starting point is running `status_events.py` on the charge log and comparing the 0x600 B3 timeline to `notes/evap-cycle-analysis.md`.
14. **[LOW] Resolve RPM mismatch between GMLAN engine RPM and PT-bus motor RPM in Grafana.** The two signals don't overlap as expected. Likely a scaling error on one. Cross-check both against OBD PID 0x0C (confirmed real engine RPM) and 0x5A2 ground truth.
13. **[MEDIUM] Resume brake booster vacuum signal investigation.** Applied pressure signals are confirmed (0x1FC B4-B5 BE16, 0x0BE B1/B5, 0x0F1 B1). The vacuum reservoir refill signal — which should show a slow exponential recovery 1-5s after pedal release as the pump refills — was not conclusively found. Best remaining candidate: **0x0F1 B0** (RecSc=0.700, 12 unique values 0-126 — may be a pressure state machine). Needs a log with brake events spaced 10+ seconds apart (no rapid re-pressing) to see the pump refill curve unambiguously. Could also try a log where the engine is off (pump working harder) for more dynamic range.
11. ~~Find bidirectional traction motor torque command~~ **FOUND — 0x041 B1-B2 (OBD bus).** The earlier PT bus scans found no regen command (correct — the command is on the OBD bus, not PT bus). 0x041 B1-B2 is confirmed bidirectional: in `vtruxcurrentlimitingtest.log` it reaches −287 Nm regen (31.9% regen frames); during cruise it reaches −42.6 Nm during downhill sections. The prior "traction inverter handles regen autonomously" hypothesis is refuted. See `notes/traction-inverter-control.md` Phase 1 (climit_regen) and Phase 2.
