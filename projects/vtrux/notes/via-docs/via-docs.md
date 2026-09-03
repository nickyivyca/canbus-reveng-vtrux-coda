# VIA Docs Notes

Notes extracted from official VIA Motors documentation in this folder.
Each file is processed independently; a synthesis section may be added later.

---

## VIA-Small-Brochure.pdf

Marketing brochure, early generation (Gen 1). "eREV40" branding.

**Powertrain architecture:**
- 4.3L V6 combustion engine + VR150 electric generator (gas/electric generator set)
- Engine connected directly to generator, runs only to charge batteries
- Engine runs at fixed "sweet spot" RPM for efficiency
- VIA Dual-Drive Motor Controller: 300 kW x2, **650V architecture**, liquid cooled
- Single drive motor: VR300 PMSM, 300 kW / 402 hp, >400 Nm / 300 ft-lbs torque, weighs 108 lbs, 11"x11"
- Generator: VR150, 150 kW
- Battery: 24 kWh liquid-cooled Li-ion, under-bed inside frame rails
- Battery voltage: **640V** (spec page says 640V; body text says 650V architecture)

**Draft specs from spec page (Gen 1):**
- All Electric Range: 40 miles (truck), 35 miles (SUV/van)
- Combined Range: 400 miles
- Traction Motor Power: 300 kW peak / 175 kW continuous
- Traction Motor Torque: 400 Nm peak / 210 Nm continuous
- Generator Power: 158 kW peak / 112 kW continuous
- Power Export: up to 15 kW, 110 & 220 VAC 60 Hz
- Battery: ~24 kWh, 640V

**Physical / vehicle:**
- Curb weight: 5,500 lbs, payload: 1,500 lbs
- Available 2WD and 4WD
- Power export: 15 kW @ 30 amps, 120V & 240V outlets on back of truck

**Notable:** Transmission, alternator removed. Regenerative braking. Conventional heat from engine coolant + electric defrost. "VDrive" brand name for the drivetrain.

---

## VIA VTRUX truck flyer.pdf

Marketing flyer, later generation (Gen 2 / production spec). Different hardware from Gen 1.

**Powertrain architecture -- significant changes vs Gen 1:**
- 4.3L V6 **GEN V** EcoTec3 engine (updated engine generation)
- Generator: VR115, **100 kW** electric generator (down from VR150/150kW)
- Generator spec: 150 kW peak, 115 kW continuous
- Drive motor: VR190, **415 Nm peak** / 210 Nm continuous (model name changed from VR300)
- Controller: **350V architecture** (down from 650V -- major change)
- Battery: 23 kWh, **350V** (down from 640V)
- Power export: 14.4 kW at **50 amps** (was 15 kW at 30 amps)

**Specs (Gen 2):**
- All Electric Range: up to 40 miles
- Extended Range: up to 400 miles
- Drive: 4WD (only -- no 2WD option listed)
- Traction Motor Torque: 415 Nm peak / 210 Nm continuous
- Generator Power: 150 kW peak / 115 kW continuous
- Power Export: up to 14.4 kW (50 amps)
- Solar Panel Option: 600W and 800W options
- Power Export Voltage: 120 & 240 VAC 60 Hz
- Charge Input: 120 or 240V
- Lithium Ion Batteries: 23 kWh
- Battery Voltage: 350V
- Chassis: 1/2 ton, GVW: 7,500 lbs
- Payload: 1,000 lbs
- Curb weight: 6,500 lbs (heavier than Gen 1's 5,500 lbs)

**Features:**
- iPad integration for hybrid controls, GPS, dispatch
- J1772 charge connector
- Full charge costs less than $2 (~5 cents/mile)
- Solar panel roof option

**Body styles:** Crew cab first, then double cab standard box.

---

## VIA-VTRUX-Truck-Specifications-05.pdf

Formal spec sheet, Gen 1 (2011 beta vehicle, Extended Cab 4x2). **Caution: this is a GMT900-era prototype spec, not our K2XX (2014 MY) truck. Specifications — especially powertrain details, steering system, and electrical architecture — may not match the actual vehicle. Do not treat as authoritative for our truck without independent confirmation.**

**Vehicle:**
- GVWR: 7,000 lbs
- Payload: 1,000 lbs
- Dimensions: 230.2" L x 79.9" W x 73.9" H, wheelbase 143.3"
- Front axle capacity: 3,200 lbs; Rear: 3,750 lbs
- Steering: 42V Electric Rack Power Steering *(GMT900 prototype spec — our K2XX 1500 has stock GM EPS on 12V; 42V figure may not apply)*
- Drive: 4x2 (2011); 4x4 planned for 2012
- Seating: 6
- Tires: 265/70 R17 Steel
- Max speed: 85 mph
- 0-60: 9.7 seconds

**Traction Motor (VR300 PMSM -- Oil Cooled):**
- Power: 170 kW continuous / 305 kW peak
- Torque: 230 Nm continuous / 350 Nm peak
- Base speed: 7,900 rpm / Max speed: 10,000 rpm
- Transmission: one-speed step-down gearbox
- Regen on coast and braking

**Generator (VR150 PMSM -- Oil Cooled):**
- Power: 110 kW continuous / 160 kW peak
- Engine: GM 4.3L V-6 MFI Gasoline

**Battery:**
- Capacity: 24.4 kWh liquid cooled
- Chemistry: **LiFePO4** (LiFePh)
- Voltage: **650V nominal**
- SOC usage: 100-20% (80% usable window)
- BMS: CAN 2.0 controlled, cell balancing, health, temp, voltage
- Pre-charge circuitry, manual disconnects, auto power de-rating, internal fuses, diodes, current sensors, relays

**Charger:**
- 6.6 kW Level I and II
- SAE J1772 compliant
- 4 hr charge @ 240V / 15 hr @ 120V

**Battery Range:** 30-45 miles AER

**HVAC:**
- Cabin cooling: 650V electric AC compressor
- Cabin heat: engine coolant loop
- Defrost: electric heat

**Export Power:**
- 15 kW: four 120V outlets + one 240V outlet, in bed of truck
- Runs from battery; engine starts automatically at low SOC

**Telemetry:** WiFi for up to 4 users onboard

**Key note:** Document dated 2011, labeled "Beta eREV Truck", specs subject to change.

---

## VIA VTruck Component Course.pdf

Confidential technician training document. Most detailed systems-level document seen so far. Gen 2 truck (crew cab, matches truck flyer).

**Battery voltage:**
- Described as "approximately 400 volts" throughout — this is the operative working voltage of the production truck, not 350V or 650V. Consistent with DC/DC converter input spec (240-400V, nom 350V) and bi-directional charger spec (240-400V DC).

**Key module names (VIA terminology):**
- **BCM** = Battery Control Module — manages HV contactors. A 12V signal from BCM closes contactors to allow HV to flow. This is VIA's BCM, not the GM BCM.
- **HCU** = Hybrid Control Unit — the main VIA ECU. Located under the hood on driver side, under the Bussmann low-voltage fuse box. Manages signals from both GM and VIA systems for total vehicle operation.
- **HVIL** = High Voltage Intercept Loop — the interlock circuit. MSD (Manual Service Disconnect) disconnects the HVIL, preventing the 12V signal from reaching the BCM, and physically disconnects HV.
- **VDSS** = scan tool name mentioned (used to activate coolant pump for checking level)
- **APU** = Auxiliary Power Unit = the engine+generator set

**Shift / drive logic:**
- No transmission. Park via park pawl (electromechanical, 12V E-Park module).
- R/N/D: signal sent to traction inverter to indicate motor rotation direction.
- **Low gear (1 or M1): forces APU on**, generates power to maintain current SOC; also used for hill climbs and cold battery operation.
- Gearbox: 2.68:1 single-speed reduction. 1.4L DEXRON VI ATF.

**Vapor canister purge (EVAP) -- very detailed:**
- Triggered after **4.7 days** without sufficient engine operation.
- Activates only when battery SOC < 80%.
- During purge, battery will NOT charge above 80%.
- Battery gauge may show 80% (not 100%) when purge is pending -- driver-visible behavior.
- Purge mode max generator power: **45 kW** (reduced from normal).
- Purge complete after engine runs at sufficient load (>50 mph) for **15 minutes total** (can span multiple drives within 2 days).
- If 15 min not achieved within 2-day window, timer resets.
- Refueling pushes more vapors in, can advance purge trigger by up to 15 hours (full tank refill from empty = worst case).

**Charging system components:**
- EVSE port (left front fender, J1772)
- Bi-directional charger
- HV battery
- Generator + Generator inverter
- DC/DC converter

**Bi-directional charger:**
- Location: under rear of vehicle, in front of muffler.
- Converts 120/240V AC (from EVSE) -> DC to charge HV battery.
- Converts HV DC -> 240V AC to supply export power panel.
- Voltage range: 240-400V DC, 120-240V AC.
- Power: 14.4 kW in either direction.
- Liquid cooled (DEX-COOL 50/50).
- Connectors: HV DC to battery, AC IN from EVSE, AC OUT to export panel, control connector, coolant in/out.

**Power electronics cooling loop** (DEX-COOL 50/50, ~2 US gallons):
- Cools: Generator inverter, Traction inverter, HV battery (optional), DC/DC converter, Bi-directional charger.
- Pump near center of vehicle above front splash guard; runs during charging (audible -- normal).
- Battery cooling via this loop is an optional feature, may not be present on all vehicles.

**Generator/Traction Motor cooling loop** (DEXRON VI ATF, ~10.5 US quarts):
- Separate loops for generator and traction motor but shared reservoir.
- Generator pump: passenger side. Traction motor pump: driver side.
- 2 inline filters, 2 radiators, pressure sensor per loop.
- Reservoir: front driver side corner, behind headlight.

**HV battery pack:**
- Location: between H-frame and rear differential.
- Weight: ~800 lbs.
- Voltage: up to 400V.
- Supplies: DC/DC converter, Traction inverter, Generator inverter, Bi-directional charger, AC compressor, Cabin heater.
- Fuse center on underside of pack: DC/DC 25A, Cabin heater 25A, A/C compressor 25A, Bi-directional charger/inverter 80A.
- No serviceable internal components; only fuses replaceable.

**Generator:**
- Mounted to rear of ICE.
- Controlled by generator inverter.
- Dry sump lubrication, DEXRON VI ATF.
- Also used to **start the ICE** (no separate starter motor).
- Also produces AC power for export.
- Engine starts automatically at 20% SOC.

**Generator inverter:**
- Location: right inner frame rail, above traction motor inverter.
- Converts generator AC -> DC to charge HV battery.
- Controls generator output based on demand.
- Liquid cooled.

**DC/DC converter:**
- Location: above cross member, above long tail of HV battery.
- Input: 240-400V DC, **nominal 350V**.
- Output: 12-15V, **nominal 14.4V**.
- Replaces factory alternator for 12V system.
- Liquid cooled.

**Export panel:**
- Location: passenger side bed, between cab and rear tire.
- Two 30A 240V AC outlets (one 3-prong, one 4-prong); adapter available for 120V.
- Total: 14.4 kW.
- Operation: ignition key OFF, charger unplugged, export key switch ON, breaker ON.
- Export continues from battery until 20% SOC -- alarm sounds, outlet shuts down.
- For continued export: turn key to RUN, engine starts, generator sustains power.

**Drive system:**
- Traction motor: on H-frame, bolted to gearbox, dry sump DEXRON VI, uses/produces AC current.
- Traction inverter: passenger side H-frame, below generator inverter. DC HV -> 3-phase AC. Also handles regen (motor -> generator when braking/coasting).
- Shift box (PRNDL): center of vehicle, driver side outer frame rail. Converts gear selector to electrical signal.
- Transfer case: mounted to back of gearbox.

**HVAC:**
- HV AC compressor (replaced GM belt-driven). Uses POE oil (not PAG).
- Electric vacuum pump for brake booster (located inside frame rail near front cross support).
- HV cabin heater: located on cross member under engine, heats coolant when ICE is not running.
- Heater controlled by varying amperage to vary temperature output.
- Variable speed coolant pump circulates heated coolant through thermostat into GM coolant loop -> heater core.

**Driver interface gauges:**
- Battery % gauge (HV SOC).
- Generator kW gauge (output of engine-mounted generator; also shows HV output in export mode).
- Power kW gauge: blue scale = power draw; green scale = regen recovery.
- Hybrid System Lamp (HSL): VIA system malfunction indicator.
- MIL: OBD-2 malfunction (stays on >15s = fault).

---

## VIA VTruck User Guide.pdf

Operator-facing version of the Component Course (same truck, same slides, fewer technical details). Most content is duplicated from Component Course. New or clarified items only:

**System Temp Gauge:** 3-position (not continuous/analog). Green = normal, Yellow = warm, Red = hot. Indicates VIA cooling system temperature. This explains why CAN data may show the system temp as a discrete 3-state value rather than a continuous reading.

**SOC thresholds confirmed:**
- Engine starts at **20% SOC** (explicitly stated).
- **Regen braking reduced above 90% SOC** to prevent overcharging.
- In low gear (M1): engine will not fire if SOC is above 90% -- waits until SOC drops below 90% first.

**CARB regulation note (significant for CAN analysis):**
"Due to other C.A.R.B. regulations the battery state of charge has to stay within **+/-1% of where the APU is started**, this causes the engine to rev up and down to maintain this tolerance whether or not the vehicle is driving."
- This is the direct explanation for the generator RPM cycling visible in CAN captures. The APU doesn't run at a fixed setpoint -- it hunts continuously to keep SOC within +/-1% of the SOC at which the engine was started.

**First responder sticker:** confirms 400V system and 12V positive disconnect location.

---

## Charge System Inspection (Truck).pdf

Service/inspection document. Detailed physical layout and wiring of the charge system components.

**BDC physical location:** Rear of vehicle, behind the rear bumper.

**BDC connectors (5 total):**
1. HV charge cable (twist-lock)
2. HV export cable (twist-lock)
3. LV export (latch)
4. LV charging (latch)
5. Bidirectional HV lead

**BDC communication connector P18** (23-pin AMP connector, TE Connectivity part 770680-1):
- Pin 1: LED1_EN
- Pin 2: LED2_EN
- Pin 3: CHARGER_VBAT
- Pin 4: CAN1H (circuit 6433, WHT) — duplicated on pin 8
- Pin 5: CAN1L (circuit 6432, GRN) — duplicated on pin 9
- Pin 6: BDC_HVIL_IN
- Pin 7: ESS_HVIL_IN
- Pin 8: CAN1H (circuit 6433, WHT) — duplicate of pin 4
- Pin 9: CAN1L (circuit 6432, GRN) — duplicate of pin 5
- Pin 10: GND
- Pin 11: EVSE_WAKE
- Pin 12: CHARGER_ENABLE
- Pin 13: WARN_ALARM
- Pin 14: EXP_DIODE

**CAN bus termination:** 120 ohms x2 (standard dual-termination).

**J1772 charge port:** 2.6 kohm resistor between two pins; 6-pin connector with 5 active circuits.

**LV fuse center charge components:**
- Fuses: F7, F16, F19, F33
- Relays: K12, K3
- Diode: D3

**HV battery fuse cover:** 4 fuses inside. Lid torque: 4 Nm with Loctite 222.

**Notable for CAN analysis:**
- BDC is on CAN1 (circuits 6433/6432). Two pins are wired together for each signal (pins 4+8 for H, pins 5+9 for L) — typical for daisy-chain or stub redundancy.
- HVIL loop passes through BDC (BDC_HVIL_IN pin 6) and ESS (ESS_HVIL_IN pin 7) as separate inputs — the BDC monitors both its own HVIL and the ESS HVIL independently.
- CHARGER_ENABLE and EVSE_WAKE are separate discrete signals, not CAN-based — charge enable is a hard-wired logic line, not purely software.

---

## Vtrux Running Pumps WIthout Scan Tool (Truck).pdf

Service procedure for priming cooling system fluids without the VIA scan tool.

**Fluid specs (confirmed part numbers):**
- Power electronics cooling: GM OE DEX-COOL antifreeze. ACDelco 10-101 / GM 12377912
- Generator & traction motor cooling/lubrication: GM OE DEXRON VI ATF. ACDelco 10-9029 / GM 88861

**Power electronics pump (EMP):**
- Location: middle behind the front bumper (under splash shield)
- To force full speed without scan tool: ignition key ON, disconnect the smaller of the two connectors on the pump bottom. Pump goes to full speed (audible).
- Reason: the smaller connector carries the speed-control signal; removing it removes PWM/analog control and the pump defaults to full speed.
- Fill WEG to ~3 inches from top of reservoir while pump running. Replace cap BEFORE reconnecting the speed connector (surge risk if cap is off when pump is controlled).

**Oil pumps (generator and traction motor ATF loops):**
- Location: mid right and left side behind front bumper (two separate pumps -- one per loop)
- To run without scan tool: disconnect oil pump connector, apply 12V directly. Blue wire = 12V positive, Black wire = 12V negative.
- Run ~1 minute each, check/fill, repeat until level stable.
- Check level with pumps OFF (not running) for accurate reading.

**Notable for diagnostics:**
- The EMP speed connector removal trick explains how pump speed is controlled: discrete signal, not CAN-commanded directly to pump. Pump has a speed control input distinct from its main power supply.
- The oil pump connectors confirm the pumps are simple 12V DC motors -- no internal speed control, just on/off.

---

## HVIL debug.pdf

Service procedure for diagnosing HVIL continuity issues at the HV battery. Key value: partial HCU connector P24 pinout.

**HCU location (confirmed):** Engine compartment, driver side, just below the low-voltage fuse panel. Multi-pin connectors with bayonet-style lock (push tab, rotate 90 degrees).

**HCU connector P24** (Molex 64319-3218, gray face, driver-most connector):

| Pin | Signal | Circuit | Color | Destination |
|-----|--------|---------|-------|-------------|
| A1 | PTC_OUTLET_TEMP | 984 | YEL/BLU | P32:1 |
| A3 | VAC_PRES_SIG | 6030 | YEL/PUR | SP.6030.01 |
| B1 | GBLP_A | 973 | YEL/RED | P34:3 |
| B2 | GBLP_B | 974 | YEL/WHT | P34:4 |
| B3 | GBLP_C | 975 | YEL/BLU | P34:2 |
| B4 | GBLP_P | 976 | YEL | P34:5 |
| C1 | GBLP_PNP | 977 | YEL/BLK | P34:1 |
| C4 | APP1_PEDAL | 979 | BLU | P2:8 |
| D1 | APP2_PEDAL | 980 | L.BLU | P2:9 |
| D3 | MIL_ECM | 990 | ORG/WHT | P2:18 |
| D4 | 5V_REF_A | 971 | RED/WHT | SP.0971.01 |
| E2 | HVAC_REQ | 343 | WHT | P126:14 |
| E3 | HVAC_TEMP_SEL | 344 | L.BLU | P126:13 |
| E4 | 5V_REF_B | 972 | BRN/YEL | SP.0972.01 |
| F4 | HCU_VBAT1 | 943 | RED | P115:A |
| G1 | CHASSIS_GND_HCU | 250 | BLK | TM6 |
| G2 | CHASSIS_GND_HCU | 250 | BLK | TM6 |
| G3 | HCU_DRVP1 | 919 | PNK | P117:H |
| H1 | GEN_F_TERM_PWM | 44 | GRN/WHT | P2:20 |
| H3 | HCU_DRVP2 | 919 | PNK | P118:E |
| **H4** | **ESS_HVIL_DRV** | **996** | **ORG** | **P126:15** |

**HVIL debug procedure:**
- Target pin: H4 (ESS_HVIL_DRV) in connector P24.
- Test continuity from H4 to the MSD HVIL pin -- should be <5 ohms.

**HV battery MSD HVIL connector:**
- Two HVIL pins at upper and lower positions on either the right or left side of the MSD connector (build-dependent; unused side has no pins installed).
- The MSD connector is orange (high-voltage interlock orange is universal color coding).

**Notable signal names from P24:**
- `GBLP_A/B/C/P/PNP` -- group of 5 signals on B-row and C1. Likely gear selector (PRNDL) signals from the shift box. GBLP = gear/brake/lamp/park? Five signals match P/R/N/D/L or a binary-encoded selector.
- `APP1_PEDAL` / `APP2_PEDAL` -- accelerator pedal position (dual-redundant), HCU reads these directly (not from GM ECM via CAN).
- `MIL_ECM` -- HCU reads the GM MIL signal.
- `HVAC_REQ` / `HVAC_TEMP_SEL` -- HCU controls HVAC (consistent with HV compressor and HV cabin heater being VIA-managed).
- `GEN_F_TERM_PWM` -- generator field terminal PWM (circuit 44). Despite the name, this is almost certainly the HCU simulating the alternator field control signal that the original GM ECU expects. The GM ECU monitors the alternator field duty cycle; without a plausible signal here, it logs a fault. In practice, a fault code IS present when read with a GM-specific scanner, but it does not trigger a check engine light and does not appear on a generic OBD-II scan -- suggesting VIA's simulation is close enough to suppress the MIL but not exact enough to fully clear the GM-internal fault.
- `HCU_DRVP1` / `HCU_DRVP2` -- HCU drive power (two pins, likely redundant power feeds to HCU).
- `ESS_HVIL_DRV` -- Energy Storage System HVIL drive. The HCU drives this line to activate the HVIL loop.

---

## High Voltage Battery Contactor Replacement.pdf

Service document for HV battery removal and internal contactor replacement.

**Battery weight: 900 lbs** (Component Course said ~800 lbs -- minor discrepancy, 900 lbs is the more specific service doc figure).

**MSD (Manual Service Disconnect):**
- Location: driver side front of the battery pack.
- Two-stage lever mechanism: opens HVIL circuit FIRST, then disconnects HV contacts. This sequencing is intentional -- HVIL opens before HV, so the BCM de-energizes contactors before physical separation.
- Not serviceable internally -- replace entire assembly on failure.

**HV battery external connectors (from removal procedure):**
- HV charge cable (twist-lock, orange)
- HV export cable (twist-lock, orange)
- Generator and traction inverter HV connectors (black handle, rotate-to-release)
- Bi-directional HV lead (white tab, press down to release)
- DCDC high voltage lead (3-stage connector: red tab unlock, orange tab slide, black tab final release)
- **BCCM 12V connector** (black, pull white tab to unlock + lift black tab) -- note: "BCCM" appears here; likely BCM + CCM or a combined Battery/Charge Control Module designation
- 16-pin low voltage connector (pull red tab rearward, push down)
- HVAC HV connector (white wedge lock + orange tab with press/lift sequence)
- Two coolant lines (clamp-off before removing)

**Battery mounting:**
- 11 bolts, 15mm, Loctite 242 (blue) on reinstall
- Torque: 35 ft-lb to frame abutments
- Optional spacers at mounting points (build variation -- retain if present)

**Internal battery modules (from exploded diagram):**
1. **EDM** = Electrical Distribution Module -- contains main contactors, covered by 4-bolt cover
2. **CSM** = Current Sense Module
3. **BCM** = Battery Control Module (confirmed internal to battery pack)

**Internal torque specs:**
- Battery case bolts: 11 Nm (10mm, tighten center-out)
- Connector plate bolts: 7 Nm (Allen socket)
- EDM mounting + main contactor nuts: 11 Nm
- EDM cover: 4 Nm
- Charge contactor mounting: 4 Nm

**Notable:**
- BCM is physically inside the battery pack. This confirms BCM = internal battery electronics, not a standalone external module. The "BCM closes HV contactors via 12V signal" from the Component Course means the HCU sends a 12V signal TO the BCM inside the pack, which then operates the contactors inside the EDM.
- Separate charge contactors exist distinct from main contactors -- consistent with our understanding that charging path has independent switching.
- "BCCM" connector naming on the 12V control connector may be a concatenation or a typo. No other document uses this term. Likely = BCM connector.

---

## 2014_2015_truck_operators_manual_06252015.pdf

Operator's manual supplement to the 2014/2015 Chevrolet Silverado Owner's Manual. Covers Gen 2 production crew cab 4x4. Most content overlaps with Component Course and User Guide, but fuse box list is new and highly useful.

**Full LV fuse panel inventory** (supplemental panel, under hood driver side):

| Fuse | Name | Rating |
|------|------|--------|
| F5 | CORE WAKE | 30A |
| F6 | IGN WAKE | 30A |
| F7 | CHG WAKE | 20A |
| F8 | ENG IGN | 25A |
| F11 | CABIN HEATER | 20A |
| F12 | FAN 1 | 30A |
| F13 | FAN 2 | 30A |
| F14 | EPT W.PUMP | 30A |
| F15 | PARK PAWL | 30A |
| F16 | CHARGER | 10A |
| F17 | TRAK INV | 10A |
| F18 | ESS | 15A |
| F19 | EVSE WAKE | 5A |
| F20 | HMI | 10A |
| F21 | A/C | 10A |
| F22 | SPARE | 20A |
| F23 | HCU | 10A |
| F24 | ESS2 | 15A |
| F25 | OBD | 10A |
| F26 | GENE INV | 10A |
| F27 | SPARE | 15A |
| F28 | HEATER | 5A |
| F29 | PTC PUMP | 10A |
| F30 | VACUUM PUMP | - |
| F31 | DRVP1 | 20A |
| F32 | DRVP2 | 20A |
| F33 | CHG/EXP ENABLE | 7.5A |
| F34 | SPARE | 30A |
| F35 | SPARE | 20A |
| F9 | GENE OIL (circuit breaker) | 25A |
| F10 | TRAC OIL (circuit breaker) | 25A |

**LV relays:**
- K1: CORE WAKE
- K2: IGN WAKE
- K3: CHG WAKE
- K4: ENG IGN
- K5: GENE OIL
- K6: TRAC OIL
- K7: CABIN HEATER
- K8: SPARE
- K9: FAN 2
- K10: FAN 1
- K11: SPARE
- K12: ESS COOLER

**LV diodes:**
- D1: EXP (6A)
- D2: IGN (6A)
- D3: EVSE (6A)
- D4: DIAG (6A)

**Notable fuse name signals for CAN analysis:**
- `ESS` (F18, F24 = ESS2) -- Energy Storage System = HV battery; two fuses suggest two separate LV circuits to the ESS/BCM
- `EVSE WAKE` (F19) -- separate wake line for the charge port, consistent with P18 pin 11 (EVSE_WAKE)
- `HMI` (F20) -- Human-Machine Interface power
- `GENE INV` (F26) -- generator inverter LV power (separate from traction inverter F17)
- `DRVP1/DRVP2` (F31/F32) -- matches HCU connector P24 pin names HCU_DRVP1 and HCU_DRVP2 exactly
- `CHG/EXP ENABLE` (F33) -- single fuse for both charger and export enable, matches Charge System Inspection fuse list
- `EPT W.PUMP` (F14) -- electric powertrain water pump (EMP)
- `PTC PUMP` (F29) -- PTC heater coolant pump

**Key operational details (new or clarified vs other docs):**
- Vapor canister purge trigger: "5 days" in this doc (Component Course said 4.7 days -- same thing, rounded).
- Battery charges to 90% max (not 80%) when purge is required -- **discrepancy with Component Course which said 80%**. This doc (operator-facing, 2015) says 90%.
- Export power SOC thresholds: warning buzzer at 22%, faster at 19.5%, very fast at 18.5%, shuts off at 18% -- more precise than the "20%" figure used elsewhere.
- Traction power reduced below 20%, could be lost at or below 10% (without engine).
- Ignition switch position D (Start) is NOT USED -- vehicle starts from key On (position C), no starter crank.
- Park pawl engagement requires 12V battery; must be engaged within 3 seconds of key-off or it won't engage.
- Must wait ~45 seconds after ignition off before engaging export power (discharge/charge mode switching delay).
- Export key switch can be removed in either ON or OFF position (intentional -- can leave power running unattended).
- Towing: flatbed preferred; if wheel-lift tow, tow from REAR only. Front wheels must be off ground. Rear wheels on ground = traction motor generates HV (regen). **Do not tow with rear wheels on the ground.**
- Cold battery performance: 40F (4.5C) threshold for overnight charging recommendation; ~20F (-7C) causes significant range loss.

**Maintenance intervals:**
- Generator/traction motor coolant (ATF): every 50,000 mi
- Generator/traction motor coolant filters: every 25,000 mi
- Power electronics coolant (DEX-COOL): every 150,000 mi
- Engine coolant: every 150,000 mi or 5 years
- Engine oil: at CHANGE OIL SOON message, or annually
- Engine accessory belt: inspect every 25,000 mi or 10 years

**Vehicle specs (capacities):**
- Engine oil: 4.8L / 5 qt
- Fuel tank: 64L / 17 gal
- Wheel nut torque: 190 Nm / 140 ft-lb

---

## Via VtruX Components.xlsx (Google Sheets export)

Community-maintained component spreadsheet. Mostly pointers and screenshots but contains some confirmed part identifications and links to manufacturer datasheets. External links were fetched where accessible; findings from datasheets are included below.

**Component inventory from spreadsheet:**

| Component | Make/Model | Notes |
|-----------|-----------|-------|
| Traction Motor | BorgWarner Remy HVH250-115D | 125 kW cont / 180 kW peak @ 400V (60s); 300 Nm cont / 405 Nm peak |
| Traction Inverter | **DANA TM4 CO150** | 150 kW @ 450 Vdc (30s); 320-750 Vdc operating range; 575 Arms max |
| Generator Motor | BorgWarner Remy HVH250-115D | Same motor family as traction |
| Generator Inverter | **DANA TM4 CO150** | Same inverter as traction -- explains CAN message symmetry |
| Gearbox | BorgWarner 32-01 eGearDrive | 2.68:1, 350 Nm, 1.4L DEXRON VI |
| HCU | NewEagle **ECM-5554-112-0904-F-M** | MotoHawk platform (Woodward) |
| Battery | A123 24 kWh 400V | 5 modules: 4 x 5.3 kWh + 1 x 2.6 kWh = 23.8 kWh total |
| Bi-Directional Charger | Bel Fuse 350INVCH150-120-240-**8G** | END OF LIFE per Bel datasheet |
| Engine | 4.3L Gen V V6 VVT **LV3** | Specific GM engine code |
| BMS | A123 | (no further detail in spreadsheet) |

---

**HVH250-115D specs (from Remy application manual):**

The "115D" variant uses dual/parallel windings (D suffix). Key specs at 320 Vdc, 100°C inlet ATF, 10 L/m flow:
- Peak: 400 Nm / 150 kW for 30 seconds (up to 3500 RPM)
- Continuous: 210 Nm / 100 kW (up to 4400 RPM)
- Max bus voltage: 700 Vdc; Max current: 600 Arms (D = parallel = higher current)
- Cooling: DEXRON VI ATF, 5-15 L/m; sump must face down
- Demagnetization risk above 180°C stator temp
- Resolver type: standard resolver (Amphenol D38999 LV connector), 4-wire excitation + 4-wire signal + 2 thermistor + 2 safety switch
- 24-tooth external spline output shaft (mates to BorgWarner 31-03/32-01 transmission directly)

**Notable for our truck:** Both traction and generator use the same HVH250-115D motor. This means the same thermal behavior characteristics, the same resolver interface, and the same ATF cooling requirements. The GENE and TRAC inverters (both CO150) being symmetric hardware also directly explains why GENE MCU CAN messages (0x471, 0x479, 0x482 on PT bus) are structurally identical to TRAC MCU messages (0x442, 0x44A, 0x0462 on OBD bus) — same inverter software base.

---

**DANA TM4 CO150 (traction and generator inverter):**
- Operating voltage: 320-750 Vdc
- Max output current: 575 Arms
- **CAN control: J1939** — the CO150 uses J1939 CAN protocol natively. The VCM communicates with both inverters via J1939-framed messages.

---

**Bel Fuse 350INVCH150-120-240-8G (from datasheet):**

DC operating range:
- Charge mode output: 250-435 Vdc (Component Course said "240-400V DC" -- the 435V max here is wider)
- Export mode input: 250-435 Vdc; shutdown below 240 Vdc
- Max charge output current: 40 Adc (adjustable via CAN)
- Export max output: 14.4 kVA @ >375 Vdc

Over-temperature: shutdown at T_coolant = 65°C. Full power at ≤50°C coolant; derated at 60°C.

Weight: 36 kg (79 lbs). Dimensions: 605 x 160 x 344 mm.

**CAN interface:**
- Protocol: **J1939** (consistent with CO150 inverters -- whole PT bus is J1939)
- Baud rate: hardware selectable via CAN_BAUD_RATE pin -- open = 500 kbit/s, grounded = 250 kbit/s (Signal 2 connector pin 17)

**EVSE_WAKE behavior (from datasheet, important for CAN analysis):**
"Wake output goes HIGH when control pilot is active and goes LOW when CAN command from VCU is received or in sleep mode."
This means the BDC itself drives the EVSE_WAKE signal to alert the VCU when a J1772 plug is connected. The VCU wakes up in response, then sends a CAN command back to the BDC to take over the session. This is a hardware wake-before-CAN bootstrap sequence.

**Signal 2 connector pin cross-validation:**
Bel's Signal 2 connector (TE 776087-1) maps exactly to VIA's P18 connector (TE 770680-1 mating side):

| P18 (VIA label) | Bel pin | Bel name |
|-----------------|---------|----------|
| LED1_EN | 1 | LED_1 |
| LED2_EN | 2 | LED_2 |
| CHARGER_VBAT | 3 | VBAT |
| CAN1H (pins 4+8) | 4 / 8 | CANH_1 / CANH_2 (internally connected) |
| CAN1L (pins 5+9) | 5 / 9 | CANL_1 / CANL_2 (internally connected) |
| BDC_HVIL_IN | 6 | HVIL_1 (= HVIL_IN from DC connector) |
| ESS_HVIL_IN | 7 | HVIL_2 (= HVIL_OUT from DC connector) |
| GND | 10 | 12V_RTN |
| EVSE_WAKE | 11 / 15 | EVSE_WAKE_OUT (both pins connected internally) |
| CHARGER_ENABLE | 12 | IGN (key switch -- CAN enable) |
| WARN_ALARM | 13 | ALARM_IN |
| EXP_DIODE | 14 | SWITCH_OUT |

"ESS_HVIL_IN" is VIA's label for what Bel calls HVIL_2/HVIL_OUT -- the outgoing side of the HVIL loop from the DC connector. The BDC monitors both sides of the HVIL loop via pins 6+7 to detect an open circuit.

---

**HCU (NewEagle ECM-5554-112-0904-F-M, from product page):**
- Platform: MotoHawk (Woodward acquisition of NewEagle)
- Processor: Motorola MPC5554, 80 MHz
- Memory: 2 MB Flash, 64 KB RAM, 32 KB EEPROM, 512 KB calibratable RAM
- I/O: 43 inputs, 35 outputs
- **CAN: 3 x CAN 2.0B channels** -- directly accounts for our three-bus architecture (PT + Vehicle + OBD)
- Operating voltage: 9-16 Vdc (24V jump start capable, 4.5V crank)
- Woodward P/Ns: 8923-1628, 1751-6454

Note on part suffix: spreadsheet and NewEagle store show **F-M** suffix. projects/vtrux/README.md records "C/F" -- F-M is the confirmed variant. The F likely = firmware flash variant (vs C = calibration-only variant).

---

## Cross-file observations (preliminary, not yet synthesized)

1. **Two hardware generations exist:** Gen 1 (640V/650V, VR300 motor, VR150 gen, 24.4 kWh LiFePO4) vs Gen 2 (350V, VR190 motor, VR115 gen, 23 kWh). Our truck's battery voltage from CAN analysis will determine which gen it is.

2. **Battery chemistry confirmed LiFePO4** in the spec sheet. Our A123 cells are LiFePO4 -- consistent.

3. **BMS uses CAN 2.0** -- directly confirmed in spec sheet. Consistent with our CAN captures.

4. **Engine runs at fixed "sweet spot" RPM** -- consistent with what we see in CAN data where generator RPM appears quantized/stepped.

5. **42V electric power steering** -- from GMT900 prototype spec only; our K2XX 1500 has stock GM EPS (12V, CAN-controlled). A separate 42V bus may not exist on our truck.

6. **SOC window: 100-20%** -- the BMS is expected to operate in this range, relevant to interpreting SOC signals.

7. **Export power behavior:** runs off battery; engine kicks on at low SOC automatically. Relevant to charge control logic investigation.
