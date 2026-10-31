# BorgWarner eGearDrive Transmission — CAN Notes

Cross-vehicle topic. Both vehicles use the same BorgWarner eGearDrive TCM hardware/firmware family:

| Vehicle | Model | Orientation |
|---------|-------|-------------|
| Vtrux | 32-01 | Longitudinal |
| Coda | 31-03 | Transverse |

Confirmed by exact CAN ID, DLC, byte encoding, and rate match across both vehicles. Hardware reference: `notes/borgwarner-transmissions.pdf`.

---

## CAN Signals

Present on PT bus (Vtrux) and D CAN (Coda) at all times the vehicle is on. **0x55C is a TCM broadcast. 0x308 is NOT** -- corrected 2026-09-24, see below.

### 0x308 — Park Request (controller → TCM)

DLC=5, 100 Hz. **Transmitted by the controller — the DLCM on Coda, the HCU on Vtrux — not by
the TCM.** Corrected 2026-09-24; it had been recorded here as a TCM broadcast reporting the
park pin's state.

| Byte | Signal | Encoding | Confidence |
|------|--------|----------|------------|
| B0 bits 6-5 | **ParkRequest** | 2-bit command: `0` = OFF, `1` = Park (byte `0x20`), `2` = UnPark (byte `0x40`) | CONFIRMED |
| B0 other bits | unused | never set: 0 frames of 3,855 on Coda, 0 of 6,423 on Vtrux | CONFIRMED |
| B1–B2 | Input shaft speed | uint16 LE (B1 = LSB, B2 = MSB); `RPM = (value - 32128) × 0.5`; zero at 32128 (0x7D80). Same encoding as 0x1C0 B6-B7 on Coda. Pearson r = 0.9999 vs traction motor RPM on both vehicles. | CONFIRMED |
| B3–B4 | Unknown | Constant `0x00` | — |

Three independent lines agree:

1. **The Vtrux EPRI DBC already had it.** `epri-pt-bus.dbc` declares
   `SG_ ParkRequest : 5|2@1+` — byte 0 bits 6-5 — with `0 "OFF" 1 "Park" 2 "UnPark"`, and
   describes the message as the HCU park request command. That file is decoded from the
   vendor's own logging app.
2. **The Coda DLCM firmware writes exactly those two bits.** 0x308 is TX record 9 in the
   DLCM's CAN transmit table at `0x80041B74` with a 10 ms period, matching the measured
   99.7 Hz, and `FUN_80080C14` assembles all five bytes, ORing `DAT_d0006AF1 * 0x20 & 0x60`
   into B0 and taking B1-B2 from `0xD00069CA`. The DLCM Functional Requirements describe
   parkRequest as "command desired state every 10msec".
3. **The request leads the TCM's own state machine, in both directions, on both vehicles.**

| Vehicle | 0x308 edge | 0x55C parkLockState response | Lead |
|---|---|---|---|
| Coda | Park → UnPark @ 4.209 s | Parked → Unparking @ 4.285 s | +76 ms |
| Coda | UnPark → Park @ 12.888 s | Unparked → Park @ 12.977 s | +89 ms |
| Coda | Park → UnPark @ 23.358 s | Parked → Unparking @ 23.446 s | +88 ms |
| Coda | UnPark → Park @ 30.448 s | Unparked → Park @ 30.533 s | +85 ms |
| Vtrux | Park → UnPark @ 25.045 s | Parked → Unparking @ 25.100 s | +55 ms |
| Vtrux | UnPark → Park @ 56.065 s | Unparked → Park @ 56.130 s | +65 ms |

A pin-state report cannot lead the TCM's own state machine on park **engage**; a command
must. The 55–65 ms figures previously recorded here as "solenoid actuation delay" are that
command-to-acknowledge latency. Coda logs: `prndnrp-twice-...log`; Vtrux:
`generator-on-then-off.log`. Script: `notes/artifacts/park_request_0x308_cross_vehicle.py`.

**The GMLAN timing is consistent with this, not against it.** On Vtrux the chain is: the
driver selects a gear, GMLAN `0x1F5` declares it, the HCU issues the 0x308 request, the TCM
answers on 0x55C. So B0 = `0x20` "lagging" the 0x1F5 Park declaration by ~65 ms is the HCU
reacting to the gear selection, and B0 = `0x40` leading the 0x1F5 gear-change by ~13 ms at
park exit is the request going out before the declaration is published.

**Consequence for B1-B2.** If the controller transmits the frame, the shaft-speed field is
the controller *sending* motor speed to the TCM rather than the TCM reporting it. Everything
measured about that signal still holds — it is input-side, not output-side, by the
cross-vehicle gear-ratio argument below — but the direction is the reverse of what was
assumed. A value that equals motor rpm exactly on two transmissions with different gear
ratios is what a controller relaying motor speed looks like.

**The third state, `0` = OFF, exists and was missing from the Coda DBC.** It appears in 288
of 3,855 frames in the Coda PRND log, at the end of the sequence after the final Park
request. It was never observed in the Vtrux log checked.

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

### CODACAN display mapping (Coda, 2026-07-26)

Cross-check from the Coda CODACAN bench-replay run (manufacturer LabVIEW decoder;
see `projects/coda/notes/codacan-replay-verification-queue.md`):

- CODACAN's Driveline-tab park fields — **ParkLock / ParkSensor / DriveSensor** — are
  the **0x55C** signals (parkLockState / parkSensor / driveSensor above). At key-on
  stationary they read `ParkLock = StatusOff`, ParkSensor/DriveSensor = off.
- **0x308 has no distinct CODACAN display field.** A byte-sweep of
  0x308 B0 across `0x00`–`0xF0` moved no Driveline field (the park state shown is
  driven by 0x55C, not 0x308). So CODACAN neither confirms nor adds to the 0x308 B0
  encoding — that rests on the EPRI definition, the Coda transmit code and the
  cross-vehicle timing documented above. In hindsight the null result is expected: CODACAN
  displays module state, and 0x308 B0 is a command the DLCM issues, not a state it reports.

This is a CODACAN-method limitation (no displayed field), not evidence against the
0x308 decode.

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

B1-B2 tracked motor RPM continuously throughout the rev. Since the output shaft was mechanically decoupled (TC neutral), this confirms the speed signal originates on the **motor/input side** of the gearbox — consistent with the 0x308 speed field being measured on the motor/input side of the gearbox. (The *transmitter* attribution in this paragraph is superseded — see the 0x308 section above; the input-vs-output-shaft conclusion is unaffected.)

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
