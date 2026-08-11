# Vtrux — Analysis Notes

Research notes and signal findings for the Vtrux CAN bus reverse engineering project.
Vehicle overview, signal inventory, DBC status, and bus architecture all live in `../Vtrux.md`.

---

## Signal Catalogs

| File | Description |
|------|-------------|
| `powertrain-messages.md` | **Primary signal catalog** — powertrain bus. Confirmed and high-confidence signals with full encoding details, confidence levels, and source evidence. |
| `context-voltage-current.md` | HV DC link voltage and current investigation: methodology, ECU inventory, correlation scan results, candidates under evaluation, rejected candidates. |
| `dcdc-current-investigation.md` | Ongoing: DCDC_LV_Curr (0x18FFD6B3 B2-B3 x0.05A). EPRI encoding confirmed, values physically plausible (5-7A charge float, 26-56A driving), but no precision calibration test yet. Evidence and next steps documented. |

## Bus Architecture & GM Signals

| File | Description |
|------|-------------|
| `threebusinvestigation.md` | Three-bus architecture: per-log bus number mappings, OBD passthrough behavior, scanner timing, GM proprietary diagnostics. Bus identification anchor IDs are in `../Vtrux.md`. |
| ~~`ENGINE-GENERATOR-CORRELATION.md`~~ | Moved to `deprecated/` — analysis body based on wrong byte-order extraction. Key finding (VCM substitutes ~800 RPM synthetic on Vehicle bus; real RPM on OBD bus) is in `../Vtrux.md`. |
| ~~`gmlan-additional-investigation.md`~~ | Moved to `deprecated/` — pre-dates full GMLAN data awareness. VCM stub findings (0x189/0x199/0x19D/0x18E) and ECM/TCM TX/RX ID lists preserved there. |

## Generator & Status Bit Investigation

| File | Description |
|------|-------------|
| `status-bits-cross-log-comparison.md` | Generator status bit identification and cross-log validation across 6 driving logs. Covers 0x644 B6 (operating mode), 0x63A B6-B7 (persistent init state), 0x649 B7 (load indicator). Includes DBC recommendations. **Carries a 2026-07-26 correction box:** 0x63A B7 bit5 is not persistent (toggles within a session) and B7 bit4 (evap purge) was missed entirely. |
| `warning-lamp-investigation.md` | Identification of the **Via amber warning telltale** on CAN: `0x646` B7 bits[6:4] (0=HV not up, 6=lamp off, 5=lamp on), PT bus, VCM-sourced. Validated across 18 logs on both trucks with a captured off→on transition and an on→off clear. Documents behaviour during major HV faults (field goes to 0, never toggles — so it does not encode a blink), the ~20 min timer-based pump-missing timeout on the parts truck (measured 20.1 min after charge start, bounded >16.6 min; not thermal), and what was ruled out (all GMLAN malfunction/indicator bits, 0x65B, and "shifter input lost"). |

## Charge Failure & Shutdown Analysis

| File | Description |
|------|-------------|
| **`fault-signature-comparison.md`** | **START HERE for any HV/BMS fault.** Cross-cutting discriminator table for all known fault modes (contactor weld, bad precharge, BMS master power loss, main-orig precharge fail, main-orig steady-state charge fault, isolation, interlock) plus the operator-unplug confound, contactor-sequence comparison, and a list of variables that do NOT discriminate. Documents the easy-to-misread signals: `vbus_pos`/`vbus_neg` are node voltages (the bus is their difference); TYPE1 is a startup state at wake but a **fault classifier in steady state** (present = internal fault, absent = external disconnect); and the Android-logger blackout confound. |
| `isolation-fault-analysis.md` | Deliberate isolation fault test (2026-03-06): fault signature, 0x410 B1 state machine, 0x420 B3 countdown, resistor-removal recovery, comparison to charging faults (Phase 2 & 3 in progress). |
| `specific-trucks/full-charge-then-fail-summary.md` | Summary of the full-charge-then-fail event (key reference log). |
| `specific-trucks/before-battery-swap-failed-charge-analysis.md` | Pre-battery-swap failed charge analysis: Bel Inverter folder sessions (M0_b, M1_b) plus the 2025-08-22 full-charge-then-fail event. Failure signature confirmed (TYPE1→TYPE3+EPO, ~10s gap), precharge sequence decoded, post-failure stuck-TYPE2 state documented through Sep 2025. **Cell overvoltage is RULED OUT, not established** — the `cell_overvolt` flag never sets anywhere in the log (confirmed 2026-07-26); root cause remains unknown. |
| `specific-trucks/after-battery-swap-charge-fail-analysis.md` | Post-battery-swap charge failure analysis: five consecutive inverterFault/shutdownSource=3 failures (Feb 16 + Feb 28 2026). Includes J1772 pilot analysis, intermittency catalogue, fault register confirmation, and vtruxchargeafterucsc session. |
| `specific-trucks/after-fix-charge-sessions.md` | Analysis of post-repair charging sessions. |

## Bel Charger / Power Mode Analysis

| File | Description |
|------|-------------|
| `charging-vs-exporting.md` | Vehicle power modes: charging, export, and driving. Startup/shutdown sequences, state codes, mode detection, 0x420 HV lifecycle states, and diagnostic implications. |
| `belinverter-dbc-merge.md` | Changes made when creating `BelInverter-v2.dbc` from the previous DBC plus EPRI Ghidra decompile findings: ID bit-31 fix, overallTemperaturePercent 8-bit correction, hvBatteryAndCharger signedness fixes, DCDC exclusion rationale. |

## Drive Cycle & Control Analysis

| File | Description |
|------|-------------|
| `peak-operating-points.md` | Peak power and torque operating points from evap drive logs. Generator: -144.7 kW generating, +15.8 kW motoring (engine start). Traction: +183.9 kW motoring, -94.2 kW regen, +403.4 Nm peak torque. Includes context and notes on artifacts (feedback spike, reverse vs regen). |
| ~~`highway-drive-cycle.md`~~ | Moved to `deprecated/` — early Aug 2025 log. 0x053 state machine extracted to `powertrain-messages.md`. |
| `cruise-control-analysis.md` | Cruise control signal reference — 0x644 B2-B3 speed setpoint (CruiseMode + CruiseSpeedSetpoint, 0.125 km/h/count, confirmed), 0x1E1 B5 button state (see Vtrux.md for tier table), torque command via 0x041 B1-B2 OBD bus. Full PT bus investigation history in `deprecated/`. |
| `traction-inverter-control.md` | Traction inverter command identification (2026-03-29): 0x041 B1-B2 confirmed as VCM-to-TRAC-MCU torque command (r=0.9994 vs feedback, r=0.9782 vs throttle). Conflicts with epri-obd-bus.dbc: log data shows TRAC torque feedback at 0x442 B0-B1, not 0x451 as the DBC states. Phase 2 (cruise re-investigation) not yet started. |
| `vtrux-smog-pass.md` | `generator_runner.py` smog-pass session (2026-06-17, `vtrux_20260617_193900`). Characterizes the backdrive↔HCU limit cycle on post-bridge 0x051 (threshold 32420, cap 33110); the ~4945 RPM runaway "oops" traced to experimental script limits (cap 33090 + threshold lowered to 32320, both confirmed on the bus) arrested by VCM throttle-lift→DFCO; TPS/DFCO wind-down; and OBD readiness progression (Catalyst→Fuel→O2 complete, Evap left incomplete = CA pass). Artifacts in `artifacts/smog-test/`. |

## Module & Bus Attribution

| File | Description |
|------|-------------|
| `can-disconnect.md` | Physical connector disconnect tests: PE pump CAN (T1), HV battery LV (T2), VCM B-connector (T3). Per-bus ID presence matrix across all tests; VCM bridging behavior and module attribution findings. |
| `app-gen-mod-investigation.md` | APP GEN MOD — 6-pin module under the dash, present on main truck only. Disconnect test set P2122+P2127 (APP sensor D/E circuit low) on first engine crank. Hypothesis: CAN-to-analog conditioner that generates the two analog APP voltages the ECM expects from the VCM's throttle command. Open: parts truck wiring path, module CAN address, connector pinout. |

## OBD / External Datalogging

| File | Description |
|------|-------------|
| `original-datalogging-investigation.md` | Factory datalogging hardware on both Vtruxes: GoPoint BT1 protocol findings, INL/EPRI fleet study context, Samsara VG34 and Pathway MPR 3 identification. Includes Part 3 extraction approach/jailbreak notes (planning). |
| `epri-decompile.md` | EPRI Logger (CANbusLogger2) app decompile findings: app identity, plist signal maps, all signal decodings extracted from Ghidra ARMv7 decompile (PT bus + OBD bus), GoPoint encapsulation IDs, extended IDs (Bel charger/DCDC), bus infrastructure layer, DAT constants, SIMDImm VFP immediates. |
| `epri-verification.md` | Pre-release verification tracking for all EPRI-derived signals (epri-pt-bus.dbc + epri-obd-bus.dbc). Lists confirmation status and evidence for every SG_ entry; documents open items and EPRI errors. Feed corrections back into epri-decompile.md when done. |
| `dtc-can-interrogation.md` | CAN interrogation tool proposals (4a-4d: OBD sweep, UDS DID sweep, J1939 PGN sweep, MPR 3 identification) and DTC interrogation findings (0x065B live-log search results, SAE J2012 code analysis). DTC lookup table is in `epri-decompile.md`. |
| `wican-pro-swcan.md` | WiCAN Pro SWCAN/GMLAN single-wire logging status: hardware supports it (secondary OBD chip, OBD pin 1), but current firmware does not expose it via WiFi/web UI. Root cause in firmware, next steps to enable. |

## Current Limits Investigation

| File | Description |
|------|-------------|
| `current-limits-investigation.md` | BMS CCL/DCL investigation. bcm_chg_max and bcm_dis_max confirmed by EPRI (0x420, 12-bit Motorola nibble-split, 0.25 A/count). VCU-sourced 0x050 (10-bit, 9.1 Hz) confirmed as DC bus current limit command. 0x412 B2 confirmed correlated with CCL ramp (r=0.998) but role vs bcm_chg_max unresolved. Explains why nibble-split 12-bit values were missed in byte/pair scans. |

## Android Logger App

| File | Description |
|------|-------------|
| `android-otg-power-cycling.md` | OTG power cycling bug — ongoing. Dongle repeatedly loses/regains USB power when external truck power is absent. Documents all attempted fixes (4 so far, all failed), what's still unknown, and the next step: capture logcat during a cycling episode then rewrite VtruxApplication power state as an explicit state machine. |

## Drivetrain & Transfer Case

| File | Description |
|------|-------------|
| `shifting-transfer-case-investigation.md` | Transfer case and shifter position on CAN bus. TC: 0x1CF `Secondary_Axle_Operational_Mode` (4WD vs 2WD/N, cannot distinguish 4H/4L); 0x17D bit 5 EBCM response. Gear estimate on 0x1F5: RPM-threshold algorithm in normal driving; timer-based fallback when motor decoupled. Shifter disconnect: VCM reports Neutral Range, torque ramps to 0 in ~270ms, no validity flags set. OBD bus 0x1F5 frozen at Park for diagnostics only. |

## Energy & Efficiency

| File | Description |
|------|-------------|
| `fuel-to-electricity.md` | Generator fuel efficiency. **~10,100 Wh per baseline-E8 gallon; 30.9% tank-to-HV-bus efficiency** (28.4–33.5% per trip) over 16 engine-run trips / 583 mi. Ethanol normalised to E8 using the math from `Vtrux Gas.xlsx` (verified correct); blend read from CAN via `0x3FB` `Fuel_Alcohol_Composition` (measured E7–E68) and fuel-flow weighted per trip. Validated against the owner's own fill-up records: 21.13 mpg from CAN vs 22.13 mpg lifetime in the sheet (4.5%). **`0x4D1` tank gauge disagrees by 1.81x and is the unreliable channel** — `Fuel_Total_Capacity` still reports the stock 98.4 L despite the conversion's shrunken tank. |
| `weekend-trip-2026-07-24.md` | Deep dive on a 372-mile, three-day round trip reconstructed from CAN alone as ordered **phases and events** — no GPS. Friday sea-level departure, 62%-of-tank refuel, a sustained **+1,334 m night climb** on the generator, Saturday parked at altitude, Sunday's **-1,103 m descent** exactly mirroring Friday's climb. Separates the three regimes cleanly: flat highway 405-531 Wh/mi, engine-on climbs 610-1300, engine-off descents -36 to +225 with 22-76% regen. Also documents the MAP-altimeter contamination gate (manifold vacuum passing the engine-off gate) that this trip exposed. |
| `charger-efficiency-and-grid-consumption.md` | Bel on-board charger efficiency vs power, and **from-grid Wh/mile (~750 typical, ~650 if always 32 A, ~890 if always 16 A)**. Losses are essentially FIXED — ~470-650 W charger conversion plus ~460-620 W HV aux — so efficiency is just `1 - loss/P_ac`: **92-93% at 6.5 kW but 77-82% at 2.9 kW**. Charging at 16 A costs ~29% more grid energy for the same charge. 16 sessions / 118 kWh AC, including 10 Android sessions found by scanning for `0x18FFD7C0`. **All 16 sessions verified MAIN truck** (odometer 96.4-98.6k km; `0x18FF0320` present so the pump is CAN-commanded) so the parts-truck free-running-pump confound is absent; the check is built into the script. **Export mode proves the ~440 W charging aux is a real load, not sensor disagreement** — the two current sensors agree to 0.02 A with current reversed, ruling out both a zero-offset and a gain error. **Bel unit was replaced 2026-05-03**, and era is perfectly aliased with logger source (all Ixxat logs = original, all Android = replacement); voltage- and power-matched comparison shows **no degradation of the original unit** and the low-power penalty on BOTH units. **Voltage dependence — two separate terms with opposite signs**, acting on different stages and near-orthogonal in the data (r=0.10, n=343k): `V_ac` **+2.5 W/V** (input/PFC switching loss, scales with blocking voltage) and `V_dc` **-11 W/V** (output stage — higher pack voltage means lower output current, so less conduction loss). Efficiency gains ~3 points from 380 to 405 V pack, confirmed independently within-session. AC supply voltage costs efficiency directly but pays back via throughput on a current-limited charger. Identifiability is handled by three structurally independent contrasts rather than one pooled fit: `I_dc` moves <2% across the `V_dc` sweep (so that term is not disguised conduction), a same-day 16 A/32 A pair at matched `V_dc` varies current 2.5x, and the EVSE current limit gives `V_ac` variation at matched `I_ac`. Documents three corrections: the `hvBatteryCurrent` sign is backwards in the DBC, CV-hold must be excluded from low-power bins, and pack energy must be integrated over charging intervals only. |
| `energy-consumption.md` | Road energy consumption (Wh per mile). **~530 Wh/mi** across 22 trips / 647 miles (5 Ixxat logs + the 20 largest Android sessions); individual trips 193–840 Wh/mi, driven by net elevation and regen recovery; accessory load 1.1–3.6 kW. Method: pack/generator/traction DC power channels validated by a closing power balance; four independent distance sources; `trac_rpm / 62.48` motor-speed-to-road-speed expansion for captures without a Vehicle bus. **Sessions must be split into trips first** — parked wall charging otherwise scores as negative consumption (-3069 Wh/mi seen). **Elevation:** `0x2C3` MAP doubles as a barometric altimeter whenever the engine is off (`0x599` B2:B3 is a dead constant, not a barometer), usable at whole-trip scale only — road-load regression and cruise-window binning both failed. Three independent elevation treatments converge on 531/532/557 Wh/mi. Also records three DBC encoding errors found in cross-checks (`0x598` signedness, `0x120` 256x scale, `0x3E9` distance unit). |

## Other Investigation Notes

| File | Description |
|------|-------------|
| `interlock-bitfields-analysis.md` | 0x410 bit-field analysis, interlock status, fault register, shutdown precursors, and message source attribution (BMS vs VCU). |
| `battery-thermals.md` | Battery pack cooling system. Cooling-active CAN signature (0x508 broadcast, 0x506 B0 bit5) confirmed by a ~+95 A 12V load step; thermal trigger model (~38 °C on / ~36.5 °C off); Peltier-liveness and pack thermal-model tasks. |

## Cross-Vehicle Topics

Analyses that span more than one vehicle live in the project-root `notes/` folder, not here.

| File | Contents |
|------|----------|
| `../../../notes/ac-resistance.md` | AC supply voltage and source resistance seen during charging. Methodology (four estimators, drift/pooling pitfalls), Vtrux results across both log roots (121 sessions, 20 outlets), extension-cord A/B, the 2026-07-14 180 V weak-supply event, and the EVSE current derate (`drawn ~= advertised - 3 A`). Vtrux artifacts in `artifacts/ac-voltage/`. |

## Subdirectories

| Directory | Contents |
|-----------|----------|
| `artifacts/` | Generated data files (CSVs, JSONs, scripts, survey outputs, reference docs). See `artifacts/README.md` for provenance inventory. |
| `plots/` | Plots embedded in documentation files only. Exploratory or undocumented plots stay in `artifacts/`. See `plots/README.md`. |
| `plans/` | Investigation and implementation plan files (including `plan-status-codes.md`). |
| `specific-trucks/` | Per-truck analyses: charge sessions, precharge failures, fault investigations for owner trucks (main truck, parts truck, Truck 3's truck). See `specific-trucks/README.md`. |
| `deprecated/` | Investigation files superseded by later findings or EPRI decompile. Currently: cruise control PT bus investigation (Phases 1-8). See `deprecated/README.md`. |
| `rpo/` | RPO code sticker photos and analysis for both trucks. See `rpo/README.md`. |
