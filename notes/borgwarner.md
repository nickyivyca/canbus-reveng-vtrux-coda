# BorgWarner eGearDrive Transmission — CAN Notes

Cross-vehicle topic. Both vehicles use the same BorgWarner eGearDrive TCM hardware/firmware family:

| Vehicle | Model | Orientation |
|---------|-------|-------------|
| Vtrux | 32-01 | Longitudinal |
| Coda | 31-03 | Transverse |

Confirmed by exact CAN ID, DLC, byte encoding, and rate match across both vehicles. Hardware reference: `notes/borgwarner-transmissions.pdf`.

---

## CAN Signals

Both IDs broadcast from the TCM at all times the vehicle is on. Present on PT bus (Vtrux) and D CAN (Coda).

### 0x308 — Park Pin State

DLC=5, 100 Hz.

| Byte | Signal | Encoding | Confidence |
|------|--------|----------|------------|
| B0 | Park pin state | `0x20` = locked (Park), `0x40` = released (not Park) | CONFIRMED |
| B1–B2 | Input shaft speed | uint16 LE (B1 = LSB, B2 = MSB); `RPM = (value - 32128) × 0.5`; zero at 32128 (0x7D80). Same encoding as 0x1C0 B6-B7 on Coda. Pearson r = 0.9999 vs traction motor RPM on both vehicles. | CONFIRMED |
| B3–B4 | Unknown | Constant `0x00` | — |

**Timing (from Vtrux `generator on then off.log`):**
- Park exit: B0 = `0x40` leads GMLAN 0x1F5 gear-change declaration by ~13 ms
- Park entry: B0 = `0x20` lags GMLAN 0x1F5 Park declaration by ~65 ms (solenoid actuation delay)

### 0x55C — Park Lock State

DLC=4, 10 Hz.

| Byte | Signal | Encoding | Confidence |
|------|--------|----------|------------|
| B0[2:0] | parkLockState | 3-bit enum (see table) | CONFIRMED |
| B0[6] | parkSensor | `0`=off, `1`=on | CONFIRMED |
| B0[7] | driveSensor | `0`=off, `1`=on | CONFIRMED |
| B1–B3 | — | Constant `0x00` | — |

**State enum (VAL_ from DBC):**

| B0 (hex) | parkLockState | parkSensor | driveSensor | Meaning |
|----------|--------------|-----------|-------------|---------|
| `0x42` | 2 = Parked | 1 | 0 | Steady Park — pin engaged, sensor confirmed |
| `0x01` | 1 = Park | 0 | 0 | Park engaging — mid-transition |
| `0x04` | 4 = Unparking | 0 | 0 | Park releasing — mid-transition |
| `0x85` | 5 = Unparked | 0 | 1 | Drive active — pin released, drive sensor confirmed |

Full enum: 0=OFF, 1=Park, 2=Parked, 3=ParkStalled, 4=Unparking, 5=Unparked, 6=UnparkStalled.

**Timing (from Vtrux `generator on then off.log`):**
- Park exit: `0x04` appears ~55 ms after 0x308 pin releases; `0x85` follows ~280 ms later
- Park entry: `0x01` appears ~65 ms after 0x308 pin engages; `0x42` follows ~270 ms later

---

## Investigation: 0x308 B1-B2 Motor Speed Signal

### Phase 1 findings — Signal characterization (2026-04-07, corrected 2026-04-09)

**B1-B2 is a input shaft speed signal, not an encoder position counter.**

The original Phase 1 analysis incorrectly dismissed the speed hypothesis. The initial characterization (B1 = shaft speed, r=0.997 vs motor RPM in a short window) was actually correct. The full-log byte-level r≈0 that led to dismissal was a methodological error: B1 alone wraps mod 256 every 128 RPM, so correlating a cycling byte against a wide-range RPM signal always produces near-zero full-log r regardless of what the signal is. The correct test is the 16-bit combined value, which gives r=0.9999 on both vehicles.

**B1–B2 is a 16-bit LE input shaft speed signal** with encoding `RPM = (value − 32128) × 0.5`, identical in scale to 0x1C0 B6-B7 on Coda (Motor_Speed). Confirmed by full-log linear regression on both vehicles:

| Vehicle | Log | Regression | Pearson r |
|---------|-----|------------|-----------|
| Vtrux | `vtruxevapdrivelog4.log` | counter = 1.999 × RPM + 32136 | 0.99989 |
| Coda | `frombonnydoon.log` | counter = 2.000 × RPM + 32128 | 0.99997 |

Ratio `(counter − 32128) / RPM` = 2.000 across all RPM bins (500–6500 RPM) with stdev < 0.05 at all speeds on both vehicles.

**At-Park values** (re-interpreted as RPM ≈ 0):

| Vehicle | Typical park value | RPM implied |
|---------|-------------------|-------------|
| Coda | 32128 (0x7D80, exact) | 0 RPM |
| Vtrux | 32146 | ~9 RPM (motor still coasting when pin engages) |

The Vtrux 108/146 oscillation in Park is small RPM oscillation (±19 RPM around ~9 RPM) from driveline compliance with the park pawl engaged.

**B1 parity:**
- Vtrux B1 is always even: `2 × (integer RPM)` is always even.
- Coda B1 takes both even and odd values: Coda input shaft speed has 0.5 RPM resolution, so `2 × (half-integer RPM)` can be odd.

**Vtrux 10 Hz effective update rate:** same raw value broadcast 10× at 100 Hz. Coda updates at the full 100 Hz broadcast rate.

**Scratchpad:** `projects/vtrux/notes/artifacts/borgwarner_shaft_phase1.py`, `projects/coda/notes/artifacts/borgwarner_shaft_coda.py`

---

### Phase 2 findings — Motor-side confirmation (2026-04-08, revised 2026-04-09)

Phase 2 was conducted under the (incorrect) assumption that B1-B2 was a rotation counter. The cpr tables from Phase 2B are void. The TC neutral test observation from 2A still provides useful cross-validation.

#### 2A — TC neutral test (`vtrux_transfer_case_test.log`)

Log sequence: 4H → 2H → neutral → 4Lo → neutral → motor revved → 2H. TC was in a neutral position during the motor rev. At t=24.92s the park pin releases and the motor ramps from 0 to ~10,800 RPM.

B1-B2 tracked motor RPM continuously throughout the rev. Since the output shaft was mechanically decoupled (TC neutral), this confirms the speed signal originates on the **motor/input side** of the gearbox — consistent with 0x308 being a TCM message reporting input shaft speed.

Supporting: at t=50–54s (TC neutral, motor at rest, pin electrically NotPark), B1-B2 oscillates 108↔146 — equivalent to ±19 RPM oscillation at ~9 RPM, consistent with driveline compliance with the park pawl engaged.

#### 2B — Cross-vehicle encoding and input shaft confirmation (2026-04-09/10)

Full-log linear regression of 0x308 B1-B2 against each vehicle's motor speed reference:

| Vehicle | Gearbox | Reference signal | Regression | Pearson r |
|---------|---------|-----------------|------------|-----------|
| Vtrux | 32-01 (longitudinal) | 0x5A2 trac_rpm | counter = 1.999 × RPM + 32136 | 0.99989 |
| Coda | 31-03 (transverse) | 0x1C0 Motor_Speed | counter = 2.000 × RPM + 32128 | 0.99997 |

The ratio (counter − 32128) / motor_RPM = **2.000** on both vehicles to three decimal places.

**Input shaft confirmed by cross-vehicle gear ratio argument:** if 0x308 measured the output shaft, the ratio would be `2 / gear_ratio` for each vehicle. The 32-01 and 31-03 are physically different transmissions with different gear ratios — an identical ratio of 2.000 on both is only possible if the signal measures the shaft common to both at the same speed as the motor: the input shaft. Output shaft would produce different ratios on each vehicle.

Note: the TC neutral test (2A) does not independently prove input shaft — both BorgWarner input and output shafts spin together at the gear ratio in TC neutral (the TC decouples downstream of the gearbox output). The cross-vehicle gear ratio argument above is the actual proof.

**Scratchpad:** `projects/vtrux/notes/artifacts/borgwarner_shaft_phase2.py`, `projects/vtrux/notes/artifacts/borgwarner_shaft_phase3.py`
