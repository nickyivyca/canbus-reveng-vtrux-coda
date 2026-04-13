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
| `gmlan-signals-investigation.md` | Investigation of GMLAN standard signals on the GM buses. |
| ~~`gmlan-additional-investigation.md`~~ | Moved to `deprecated/` — pre-dates full GMLAN data awareness. VCM stub findings (0x189/0x199/0x19D/0x18E) and ECM/TCM TX/RX ID lists preserved there. |

## Generator & Status Bit Investigation

| File | Description |
|------|-------------|
| `status-bits-cross-log-comparison.md` | Generator status bit identification and cross-log validation across 6 driving logs. Covers 0x644 B6 (operating mode), 0x63A B6-B7 (persistent init state), 0x649 B7 (load indicator). Includes DBC recommendations. |

## Charge Failure & Shutdown Analysis

| File | Description |
|------|-------------|
| `isolation-fault-analysis.md` | Deliberate isolation fault test (2026-03-06): fault signature, 0x410 B1 state machine, 0x420 B3 countdown, resistor-removal recovery, comparison to charging faults (Phase 2 & 3 in progress). |
| `my-trucks/full-charge-then-fail-summary.md` | Summary of the full-charge-then-fail event (key reference log). |
| `my-trucks/before-battery-swap-failed-charge-analysis.md` | Pre-battery-swap failed charge analysis: Bel Inverter folder sessions (M0_b, M1_b) plus the 2025-08-22 full-charge-then-fail event. Failure signature confirmed (TYPE1→TYPE3+EPO, ~10s gap), precharge sequence decoded, cell overvoltage root cause established, post-failure stuck-TYPE2 state documented through Sep 2025. |
| `my-trucks/after-battery-swap-charge-fail-analysis.md` | Post-battery-swap charge failure analysis: five consecutive inverterFault/shutdownSource=3 failures (Feb 16 + Feb 28 2026). Includes J1772 pilot analysis, intermittency catalogue, fault register confirmation, and vtruxchargeafterucsc session. |
| `my-trucks/after-fix-charge-sessions.md` | Analysis of post-repair charging sessions. |

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

## Other Investigation Notes

| File | Description |
|------|-------------|
| `interlock-bitfields-analysis.md` | 0x410 bit-field analysis, interlock status, fault register, shutdown precursors, and message source attribution (BMS vs VCU). |

## Subdirectories

| Directory | Contents |
|-----------|----------|
| `artifacts/` | Generated data files (CSVs, JSONs, scripts, survey outputs, reference docs). See `artifacts/README.md` for provenance inventory. |
| `plots/` | Plots embedded in documentation files only. Exploratory or undocumented plots stay in `artifacts/`. See `plots/README.md`. |
| `plans/` | Investigation and implementation plan files (including `plan-status-codes.md`). |
| `my-trucks/` | Per-truck charge session analyses (full-charge-then-fail, pre/post battery swap failures, post-repair sessions). See `my-trucks/README.md`. |
| `deprecated/` | Investigation files superseded by later findings or EPRI decompile. Currently: cruise control PT bus investigation (Phases 1-8). See `deprecated/README.md`. |
| `rpo/` | RPO code sticker photos and analysis for both trucks. See `rpo/README.md`. |
