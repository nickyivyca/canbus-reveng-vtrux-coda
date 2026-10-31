# Vtrux — Analysis Notes

Research notes and signal findings for the Vtrux CAN bus reverse engineering project.
Vehicle overview, signal inventory, DBC status, and bus architecture all live in `../README.md`.

**The ESP32 firmware work is not published from this repo.** The generator
inhibitor and the charge interposer -- their specifications, test evidence,
working logs, handoffs, bench artifacts and plans -- are internal-only; the
firmware itself is in the public `canbus-esp-fw-vtrux` repo, on branches
`gen-inhibit/main` and `charge-interposer/main`. The rows for those files are
omitted from the tables below.

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
| `threebusinvestigation.md` | Three-bus architecture: per-log bus number mappings, OBD passthrough behavior, scanner timing, GM proprietary diagnostics. Bus identification anchor IDs are in `../README.md`. |
| ~~`ENGINE-GENERATOR-CORRELATION.md`~~ | Moved to `deprecated/` — analysis body based on wrong byte-order extraction. Key finding (VCM substitutes ~800 RPM synthetic on Vehicle bus; real RPM on OBD bus) is in `../README.md`. |
| ~~`gmlan-additional-investigation.md`~~ | Moved to `deprecated/` — pre-dates full GMLAN data awareness. VCM stub findings (0x189/0x199/0x19D/0x18E) and ECM/TCM TX/RX ID lists preserved there. |

## Generator & Status Bit Investigation

| File | Description |
|------|-------------|
| `failed-generator-starts.md` | **Starts that crank and do not catch, with no inhibitor (2026-10-04).** 8 failed start sequences in 3 captures. Each recovered on the VCM's next attempt ~9.5 s later, with no VCM fault (`0x617` normal) and no new ECM DTC broadcast. None was in evap mode: all followed a VCM-commanded stop 12-53 s earlier, while the evap-mode stalls restarted first time. The note compares this with a start blocked by the generator inhibitor. |
| `status-bits-cross-log-comparison.md` | Generator status bit identification and cross-log validation across 6 driving logs. Covers 0x644 B6 (operating mode), 0x63A B6-B7 (persistent init state), 0x649 B7 (load indicator). Includes DBC recommendations. **Carries a 2026-07-26 correction box:** 0x63A B7 bit5 is not persistent (toggles within a session) and B7 bit4 (evap purge) was missed entirely. |
| `warning-lamp-investigation.md` | Identification of the **Via amber warning telltale** on CAN: `0x646` B7 bits[6:4] (0=HV not up, 6=lamp off, 5=lamp on), PT bus, VCM-sourced. Validated across 18 logs on both trucks with a captured off→on transition and an on→off clear. Documents behaviour during major HV faults (field goes to 0, never toggles — so it does not encode a blink), the ~20 min timer-based pump-missing timeout on the parts truck (measured 20.1 min after charge start, bounded >16.6 min; not thermal), and what was ruled out (all GMLAN malfunction/indicator bits, 0x65B, and "shifter input lost"). |

## Charge Failure & Shutdown Analysis

| File | Description |
|------|-------------|
| **`battery-fault-codes.md`** | **The BMS names its faults.** PT-bus `0x460` decoded (2026-08-26) as the A123 BMS fault-record annunciator: page-multiplexed list of 3-byte fault records pushed at fault events only (key-offs, unplugs, and charger-internal failures push nothing), surviving reboot (staged NVM restore at boot: first record ~1 s, second +15–35 s), cleared with FAULT_LATCHED. Code catalog with per-event evidence: steady-state fault = `FC 22 02` (all five 2025 instances, at TYPE1, never since); precharge abort = `F0 E0 00` (all four); contactor/interlock hardware faults = `F6` family (truck3-rounds 1/2/4 + one main-truck event); gen-inverter lost comms = `FC 16 F2` (**confirmed** against the T4 fuse experiment: pushes ~30 s after boot with the GENE MCU silent, latches until 12V clear — its Apr–Jul 2026 persistence tracks the deliberate gen-fuse pulls); isolation faults are **unnamed** (generics-only). Also: parts-truck record-era timeline, the 2026-06-10 mid-drive interlock flutter and 2026-06-18 `AC 10 01` trip, and the `0x617 B7=0xCA` VCM fault-active flag (no sibling record message exists). OBD-bus 0x460 (TRAC MCU, DLC=5) contamination caveat. |
| **`fault-signature-comparison.md`** | **START HERE for any HV/BMS fault.** Cross-cutting discriminator table for all known fault modes (contactor weld, bad precharge, BMS master power loss, main-orig precharge fail, main-orig steady-state charge fault, isolation, interlock) plus the operator-unplug confound, contactor-sequence comparison, and a list of variables that do NOT discriminate. Documents the easy-to-misread signals: `vbus_pos`/`vbus_neg` are node voltages (the bus is their difference); TYPE1 is a startup state at wake but a **fault classifier in steady state** (present = internal fault, absent = external disconnect); and the Android-logger blackout confound. |
| `isolation-fault-analysis.md` | Deliberate isolation fault test (2026-03-06): fault signature, 0x410 B1 state machine, 0x420 B3 countdown, resistor-removal recovery, comparison to charging faults (Phase 2 & 3 in progress). |
| `specific-trucks/full-charge-then-fail-summary.md` | Summary of the full-charge-then-fail event (key reference log). |
| `specific-trucks/before-battery-swap-failed-charge-analysis.md` | Pre-battery-swap failed charge analysis: Bel Inverter folder sessions (M0_b, M1_b) plus the 2025-08-22 full-charge-then-fail event. Failure signature confirmed (TYPE1→TYPE3+EPO, ~10s gap), precharge sequence decoded, post-failure stuck-TYPE2 state documented through Sep 2025. **Cell overvoltage is RULED OUT, not established** — the `cell_overvolt` flag never sets anywhere in the log (confirmed 2026-07-26); root cause remains unknown. **2026-08-26:** fault code identified (`0x460` record `FC 22 02`, see `battery-fault-codes.md`); the 2026-08-09 "M0_b self-recovery" claim RETRACTED (chunk-merge timebase artifact — no fault ever clears in place). |
| `specific-trucks/after-battery-swap-charge-fail-analysis.md` | Post-battery-swap charge failure analysis: five consecutive inverterFault/shutdownSource=3 failures (Feb 16 + Feb 28 2026). Includes J1772 pilot analysis, intermittency catalogue, fault register confirmation, and vtruxchargeafterucsc session. |
| `specific-trucks/after-fix-charge-sessions.md` | Analysis of post-repair charging sessions. |

## Bel Charger / Power Mode Analysis

| File | Description |
|------|-------------|
| **`charge-termination-behaviour.md`** | **How a Vtrux charge actually ends (2026-09-12, 49 charging sessions).** The terminator is the energy-flow bit `chgcmd_enable` going to 0, followed by `STAND_BY` -- the mode usually stays at `CHARGER`, and **only 16 of 49** terminations involve `CHARGER_LOW_POWER` at all. Mode 3 is a **hold, not a stop**: the charger stays in state 12 at a *reported* ~2.4 A DC while drawing ~1.9 kVA apparent (**corrected 2026-10-10:** ~570 W real, and the true DC is ~0.8-0.9 A because the reading is ~1.5 A high at this output). At a genuine top of charge that hold is when the pack balances, and its length tracks the cell spread -- 116.8 mV bought **7.7 h** on the parts truck, 94.5 mV bought 1.3 h, and a pack already at 2.3 mV was released with **no hold at all**, every completed hold ending at a converged 2.1-3.0 mV. Also records that the master page is **edge-triggered** (0.035/s in 3 bursts, against 3.325/s for each cyclic page), so a swallowed stop command is gone for good, and that `BELINV_hvBatteryCurrent` carries 10 corrupt samples in 1.83 M -- reject outside +/-100 A before quoting any extreme. |
| `charging-vs-exporting.md` | Vehicle power modes: charging, export, and driving. Startup/shutdown sequences, state codes, mode detection, 0x420 HV lifecycle states, and diagnostic implications. |
| `belinverter-dbc-merge.md` | Changes made when creating `BelInverter-v2.dbc` from the previous DBC plus EPRI Ghidra decompile findings: ID bit-31 fix, overallTemperaturePercent 8-bit correction, hvBatteryAndCharger signedness fixes, DCDC exclusion rationale. |

## Drive Cycle & Control Analysis

| File | Description |
|------|-------------|
| `peak-operating-points.md` | Peak power and torque operating points from evap drive logs. Generator: -144.7 kW generating, +15.8 kW motoring (engine start). Traction: +183.9 kW motoring, -94.2 kW regen, +403.4 Nm peak torque. Includes context and notes on artifacts (feedback spike, reverse vs regen). |
| ~~`highway-drive-cycle.md`~~ | Moved to `deprecated/` — early Aug 2025 log. 0x053 state machine extracted to `powertrain-messages.md`. |
| `cruise-control-analysis.md` | Cruise control signal reference — 0x644 B2-B3 speed setpoint (CruiseMode + CruiseSpeedSetpoint, 0.125 km/h/count, confirmed), 0x1E1 B5 button state (see projects/vtrux/README.md for tier table), torque command via 0x041 B1-B2 OBD bus. Full PT bus investigation history in `deprecated/`. |
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
| `charger-efficiency-and-grid-consumption.md` | **Corrected 2026-10-10 against real-power metering (garage CT, cross-checked by the Enphase CTs): real figures are ~786 Wh/mi, ~85 % charger efficiency and 79.5 % wall-to-pack at 32 A, with 16 A not re-measured; real charger loss scales with power (~1,050 W at full power, at most ~0.5 kW at the hold), so the "fixed losses" below are an apparent-power artefact; and `BELINV_hvBatteryCurrent` reads high below ~6 A (+1.5 A at a 2.0-2.5 A reading, fitting `reported = 0.891 x true + 1.51`), so the hold's "~940 W DC" and any "HV aux" over taper or hold time are invalid. No difference between the three Bel units has been measured. Original summary follows.** Bel on-board charger efficiency vs power, and **from-grid Wh/mile (~750 typical, ~650 if always 32 A, ~890 if always 16 A)**. Losses are essentially FIXED — ~470-650 W charger conversion plus ~460-620 W HV aux — so efficiency is just `1 - loss/P_ac`: **92-93% at 6.5 kW but 77-82% at 2.9 kW**. Charging at 16 A costs ~29% more grid energy for the same charge. 16 sessions / 118 kWh AC, including 10 Android sessions found by scanning for `0x18FFD7C0`. **All 16 sessions verified MAIN truck** (odometer 96.4-98.6k km; `0x18FF0320` present so the pump is CAN-commanded) so the parts-truck free-running-pump confound is absent; the check is built into the script. **Export mode proves the ~440 W charging aux is a real load, not sensor disagreement** — the two current sensors agree to 0.02 A with current reversed, ruling out both a zero-offset and a gain error. **Bel unit was replaced 2026-05-03**, and era is perfectly aliased with logger source (all Ixxat logs = original, all Android = replacement); voltage- and power-matched comparison shows **no degradation of the original unit** and the low-power penalty on BOTH units. **Voltage dependence — two separate terms with opposite signs**, acting on different stages and near-orthogonal in the data (r=0.10, n=343k): `V_ac` **+2.5 W/V** (input/PFC switching loss, scales with blocking voltage) and `V_dc` **-11 W/V** (output stage — higher pack voltage means lower output current, so less conduction loss). Efficiency gains ~3 points from 380 to 405 V pack, confirmed independently within-session. AC supply voltage costs efficiency directly but pays back via throughput on a current-limited charger. Identifiability is handled by three structurally independent contrasts rather than one pooled fit: `I_dc` moves <2% across the `V_dc` sweep (so that term is not disguised conduction), a same-day 16 A/32 A pair at matched `V_dc` varies current 2.5x, and the EVSE current limit gives `V_ac` variation at matched `I_ac`. Documents three corrections: the `hvBatteryCurrent` sign is backwards in the DBC, CV-hold must be excluded from low-power bins, and pack energy must be integrated over charging intervals only. |
| `energy-consumption.md` | Road energy consumption (Wh per mile). **~530 Wh/mi** across 22 trips / 647 miles (5 Ixxat logs + the 20 largest Android sessions); individual trips 193–840 Wh/mi, driven by net elevation and regen recovery; accessory load 1.1–3.6 kW. Method: pack/generator/traction DC power channels validated by a closing power balance; four independent distance sources; `trac_rpm / 62.48` motor-speed-to-road-speed expansion for captures without a Vehicle bus. **Sessions must be split into trips first** — parked wall charging otherwise scores as negative consumption (-3069 Wh/mi seen). **Elevation:** `0x2C3` MAP doubles as a barometric altimeter whenever the engine is off (`0x599` B2:B3 is a dead constant, not a barometer), usable at whole-trip scale only — road-load regression and cruise-window binning both failed. Three independent elevation treatments converge on 531/532/557 Wh/mi. Also records three DBC encoding errors found in cross-checks (`0x598` signedness, `0x120` 256x scale, `0x3E9` distance unit). |

## Other Investigation Notes

| File | Description |
|------|-------------|
| `interlock-bitfields-analysis.md` | 0x410 bit-field analysis, interlock status, fault register, shutdown precursors, and message source attribution (BMS vs VCU). |
| `battery-thermals.md` | Battery pack cooling system. Cooling-active CAN signature (0x508 broadcast, 0x506 B0 bit5) confirmed by a ~+95 A 12V load step; thermal trigger model (~38 °C on / ~36.5 °C off); conditioning telemetry is pack-specific (parts-orig has it, main-orig does not); 2026-07-24/26 weekend-trip validation on a long drive (peak 41.0 °C, ~80 min cooling, engagement ~1–1.5 °C higher than the 07-14 reference); Peltier-liveness and pack thermal-model tasks. |

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
| `a123-amp20m1hd-a-datasheet.pdf` | A123 AMP20M1HD-A cell datasheet (MD100105-02, 2011), supplied by the user 2026-10-10. The pack is 3p of these. Minimum capacity is 19.6 Ah per cell (58.8 Ah per 3p group); nominal 3.3 V, 65 Wh. It gives **no continuous charge or discharge voltage limits**, only the HPPC pulse-test window (Vmax 3.8 V, Vmin 1.6 V). |
| `plans/` | Investigation and implementation plan files (including `plan-status-codes.md`). The charge-interposer plan files there are internal-only. |
| `bms-soc-calibration.md` | **BMS SoC calibration and capacity learning, per pack** (2026-10-10, steps 1-3 of 5). Step 1: 242 sessions on the two packs (main-orig 42, thin; parts-orig 200), chained per truck with odometer-based detection of unlogged use. SoC rises across gaps are unusable because the garage CT cannot separate the truck's charging from unlogged Coda charging. Two unexplained SoC falls with no driving (2026-01-17, -13 %; 2026-03-05, -16 %) are candidates for a wake-time correction. The ~10 % event (2026-06-17) followed 71 km of unlogged driving, so only its wake value is observed. Step 2: the BMS holds a **per-pack capacity, not 60 Ah**. The first SoC frame after power-on is a fixed fraction *k* of the settled value (main-orig 0.826, parts-orig 0.789 drifting to 0.785), and *k* x 58.8 Ah (the datasheet minimum) reproduces each pack's measured Ah per % (48.6 / 46.4 Ah). parts-orig also has temporary ~0.400 Ah/% eras, two of them starting right after downward corrections. The 03-05 drop was captured as a correction 1 s after wake. Era cut for 12 V resets: 2026-06-17 (undervoltage relay removed). Step 3: SoC and *k* survive 12 V loss (48 power-ons, incl. deliberate cuts); a wake correction needs a rest at a low (off-plateau) voltage; on 03-04 the BMS opened the contactor with the weak cell at 2.73 V at an indicated 17.3 % (the weak group empty, display ~17 points high); holding at 100 % on a drive matches charge counted above 100 % and would carry such an over-statement through full charges (hypothesis); the 06-11 -> 06-14 rise is explained by a plug swap on 06-13. Also refined garage-CT attribution: Coda abrupt end + top-ups, Vtrux taper + hold, swaps as a half-power minute. |
| `plans/bms-soc-learning.md` | **BMS SoC calibration and capacity learning, per pack** (2026-10-10). Does the A123 BMS count against a fixed ~60 Ah (3p AMP20) or learn real capacity? Tests the user's hypothesis that the one ~10 % wake was a delayed, voltage-based recalibration on the weak-cell pack. Steps: session inventory with odometer-based detection of unlogged use, within-session Ah per % SoC, SoC change across clean rests, usable-capacity and buffer bounds; charger-DC cross-check deferred. Steps 1-3 done. |
| `specific-trucks/` | Per-truck analyses: charge sessions, precharge failures, fault investigations for owner trucks (main truck, parts truck, Truck 3). See `specific-trucks/README.md`. |
| `deprecated/` | Investigation files superseded by later findings or EPRI decompile. Currently: cruise control PT bus investigation (Phases 1-8). See `deprecated/README.md`. |
| `rpo/` | RPO code sticker photos and analysis for both trucks. See `rpo/README.md`. |
