# Regen torque, friction braking and brake-press pressure, measured from the car (inputs for the 0.13 g candidate)

Owner: `Coda drivetrain lash model` session, 2026-10-14. Plan `../plans/regen13_modelling_inputs.md`; parent plan
`../plans/next_flash_regen13_brake_blend.md` (owned by `Coda DLCM work`), its step 2. Log analysis only; nothing
flashed. Reviewed with the user 2026-10-14 (*"ok yeah this is all good"*). Worklog 3BL.

Script `artifacts/regen13_inputs.py` (phases 0-6; outputs `artifacts/regen13_inputs.p*.out.txt` / `.json`). Corpus:
1101 captures, D bus only; 189 dropped for bus errors, 57 for too few frames, the 3 f7 captures excluded.

**Units.** Brake pressure is the raw 12-bit 0x208 `BrakePressure` count, which is the DLCM's BrakeAnalog unscaled
(`Coda DLCM work`, its step 1(a)). Motor torque is 0x1C0 `Torque` (delivered, as the MCM reports it); 0x212
`TorqueRequest` beside it.

## 1. The measurement chain (and why the accelerometer is not in it)

- **Speed and acceleration** come from the REAR (non-driven) wheel speeds, 0x208 `WheelSpeed_LR/RR`, 2.000 counts per
  wheel rpm. That scale and the rolling radius **0.3008 m** are anchored to the 0x491 odometer (0.1 km/count, checked
  against known mileage on three Codas; `../artifacts/vehicle_speed_chain.py`, `low-speed-clunk-and-creep-columns.md`).
  Motor rpm / 6.576 matches the rear wheels to 1.0001.
- **Geometry**: 6.576 / 0.3008 = **21.86 N of wheel force per motor Nm** at 100 % gearbox efficiency. The plant's
  GEOM 0.04714 m/rad (`plant/lash.py`) is 3 % above the measured 0.3008 / 6.576 = 0.04574.
- **The 0x330 accelerometer's scale (0.08 m/s2/count) comes from CodaCAN's VICD parsers** and the DBC calls it
  approximate (+/-12 %). It does not enter (a), (b) or (c). Measured here against the wheels: **0.0817** (Long_Accel
  change / wheel-derived change over 3099 torque steps, slope 0.979) -- VICD's scale is right to about 2 %.
- **Not validated**: the odometer's own accuracy against true distance, and the MCM's reported torque scale. A torque
  scale error goes one-for-one into the mass below but not into the torque for 0.13 g, which is in the same reported
  units the map is written in.

## 2. (b) Regen torque -> deceleration

Paired steady-torque windows (0.6 s each) either side of a torque step >= 30 Nm, brakes off, D, above 8 mph; grade and
drag cancel in the difference. k = change in acceleration per change in delivered torque.

| step type | n | k (m/s2 per Nm) [5-95 %, capture bootstrap] | effective mass N/k | Nm for 0.13 g |
|---|---|---|---|---|
| regen (both windows < -10 Nm) | 412 | 0.01172 [0.01159, 0.01186] | 1865 kg | 108.7 [107.5, 110.0] |
| drive | 928 | 0.01112 | 1967 kg | 114.7 |
| mixed | 697 | 0.01139 | 1919 kg | 111.9 |
| plant constant (0.04714 / 4.385) | -- | 0.01075 | ~1970 kg | 118.6 |

- Regen k is flat from 8 to 35 mph (Nm for 0.13 g 108.0-108.3); the bands above have few steps.
- The regen / drive difference fits a gearbox efficiency **eta 0.974** (wheel force eta x 21.86 T driving, 21.86 T / eta
  regenerating) and a mass, rotating parts included, of 1915 kg (corpus average load).
- **Delivered / requested** in steady regen: p50 0.977 (p10 0.968, p90 0.988; n 995).

### Mass per drive and occupancy (phase 6)

Per drive (85 sessions with >= 15 steps, all step types, eta held): wheel-speed slopes give +/-90 kg per drive, too
coarse; the accelerometer's change across each step (scale set from the wheels) gives +/-45 kg. Masses 1717-2039 kg,
median 1863, with a dense mode at 1800-1820 kg (accelerometer method; it reads ~2 % below the wheel method). Clean
occupancy buckets are not resolvable (+/-45 kg per drive against ~80 kg per person), but the spread follows the
calendar: weekday 06-17 h median 1846 kg (n 38), weekday evenings 1877 (n 20), Friday evenings and weekends 1917 (n 27).

### Sizing T13 for the driver alone (user, 2026-10-14)

The user: 170 lb, often with a heavy backpack and/or ~45 lb of dogs. The driver-only car is the lightest realistic
load, so the most deceleration per Nm: sizing for it keeps regen at or below 0.13 g with any heavier load.

| item | basis | equivalent mass |
|---|---|---|
| curb weight | Wikipedia (user) | 1660 kg |
| driver | 170 lb | 77 kg |
| motor rotor | **estimate**, 0.07-0.11 kg m2 (below) x 478 | 33-53 kg |
| 4 aluminium 16" wheels, tyres, brake rotors | **assumed** typical 0.85-1.0 kg m2 each, / r2 | 35-45 kg |
| gearbox, half-shafts | small | ~3 kg |
| **total** | | **~1825 kg** |

Rotating parts count as J x (6.576 / 0.3008)^2 = 478 x J of vehicle mass: the rotor spins 6.576x the wheels, so an
~12-18 kg rotor acts like 33-53 kg (its mass at ~75 mm radius of gyration moves ~1.64x the car's speed; 1.64^2 ~ 2.7).
The rotor inertia is an estimate: a steel and magnet ring if "SPM195-114" means a 195 mm rotor and a 114 mm stack
(hypothesis), consistent with the clunk model's fitted motor-side inertia 0.09-0.105 kg m2 -- which covers everything
on the motor side of the backlash, gearbox input gears included, so it overstates the rotor alone somewhat.

**Driver-only T13: about 104 Nm delivered, about 106 Nm requested (+/-1.5 Nm)**; with eta 1.0 instead of 0.974, about
109 Nm requested. 10 kg moves it 0.6 Nm. Cross-check: the lowest dense cluster of per-drive masses sits within ~2 % of
1825 kg. The motor: UQM PowerPhase 100, SPM195-114-3, 50 kg, 286 mm x 276 mm, 300 Nm peak, 8000 rpm (public UQM
datasheet, thunderstruck-ev.com `UQMPP100DataSheet.pdf`); no rotor inertia is published there. The DLCM spec's "UQM
100kW Traction System Specification" is not in the project.

Approved (user, 2026-10-14): **the 0.13 g target is about 106 Nm requested (driver only), not the plant's 118.6.**

## 3. (a) Friction deceleration vs pressure, regen subtracted

1102 brake applications that start from a 0.7 s steady brake-off window (pedal 0, D, > 5 mph); the window's road load
(grade, drag, rolling) is held for up to 4 s; the motor's delivered torque is subtracted with (b)'s k. Speed, torque
and pressure all through the same 2 Hz zero-phase filter. Friction decel in m/s2 is a kinematic difference and does not
depend on the mass.

| pressure (raw) | 0-50 | 50-60 | 60-80 | 80-100 | 100-125 | 125-150 | 150-175 | 175-200 | 200-250 | 250-300 | 300-400 | 400-500 | 500-700 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| friction decel, median m/s2 | 0.03-0.15 | 0.19 | 0.25 | 0.34 | 0.45 | 0.62 | 0.76 | 0.92 | 1.13 | 1.43 | 1.83 | 2.46 | 3.21 |

- **Shape (approved as the friction brake's real curve shape)**: a soft knee from 0 to ~100 raw at roughly half the gain
  above it; above ~100 raw close to linear at **~0.006 m/s2 per count** (0.06 g per 100 counts; ~0.5 regen-equivalent
  motor Nm per count). Friction equal to the 156 Nm regen plateau at ~340 raw.
- Straight line with threshold: d = kb x max(0, P - P0), P0 30, kb 0.00584 [0.00578, 0.00591] m/s2 per count.
- Speed: kb 0.0059 below 20 mph, 0.0057 at 20-35, 0.0053 at 35-50 mph (about -10 %).
- Apply / hold / release 0.0055 / 0.0059 / 0.0064 (hysteresis or lag; best-fit lag 40-60 ms). First 0.5 s 0.0051.
- Accelerometer instead of wheel speed (grade change removed, body pitch not): +8 %. Overall about +/-10 %.
- `plant/road.py` (17.8 + 0.482 P motor-frame Nm, plant constants) is 0.00518 per count with no knee: ~12 % low above
  100 raw, too strong near 0.

### Total deceleration vs pressure (phase 5)

Delivered brake-on regen does not drop with pressure: it rises in magnitude (all cohorts, 5-20 mph: -65 Nm at 0-25 raw,
-81 at 175-200, -95 at 275-300, -104 at 400-500). C4c at 5-20 mph still delivers ~-150 Nm at 200-225 raw; a C4c stop at
470-512 raw (`coda_20261008_184602_T1`, 18 -> 11 mph) delivered ~-148 Nm with 0x312 M_MIN at -300. Total (regen +
friction) rises smoothly across 150-300 raw in every speed band (5-20 mph: 1.65 / 1.88 / 2.07 / 2.25 / 2.46 m/s2 at
150-175 ... 250-275). This corrected the peer's reading of `BoundBrakeAndMins` (a drive-side bound; worklog 6H.72.7).

## 4. (c) Pressure of early brake presses

2881 presses started while moving above 3 mph in D (583 captures).

- The switch leads: pressure > 0 a median **100 ms** after it (p25 60, p75 358, p90 700 ms); 181 presses never showed
  pressure; 24 % of braking time is switch-on at zero pressure.
- Pressure (raw), p25 / p50 / p75:

  | | p25 | p50 | p75 |
  |---|---|---|---|
  | at 0.5 s | 53 | 102 | 146 |
  | peak in the first 1 s | 88 | 128 | 193 |
  | press peak | 124 | 203 | 256 |

- Peaks: 17 % of presses at or below 100 raw, 50 % at or below 200, 86 % at or below 300, 98 % at or below 500.
  Presses that end at a stop peak higher (median 239). Speed band hardly matters.
- Time-weighted while braking: p50 100, p75 163, p90 223, p99 352.
