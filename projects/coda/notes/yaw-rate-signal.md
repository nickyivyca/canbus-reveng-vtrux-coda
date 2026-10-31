# Coda ESC Yaw Rate Signal — `0x300` B6-B7

**Found 2026-09-21.** `projects/coda/README.md` has always listed the ESC as
"ABS + stability; connected to yaw sensor", and the longitudinal accelerometer
was confirmed the day before at `0x330` B7, but nothing in the DBC named a yaw
channel.

**Result: `0x300` bytes 6-7, big-endian, on D CAN, is the ESC yaw-rate gyro.**

| property | value |
|---|---|
| layout | B6-B7, u16 **big-endian** |
| zero | **32792 raw** — identical in all four logs tested, 2026-02 to 2026-08 |
| sign | **positive = left turn** (raw rises as the right wheels outrun the left) |
| rate | 50.0 Hz, D CAN, `B0 == 0x00` frames |
| scale | **≈0.0094 deg/s per count** — approximate, see §4 |
| observed swing | −4297 / +3448 counts ≈ −40.6 / +32.5 deg/s (Bonny Doon descent) |
| invalid | `0xFFFF`, ~0.09 % of frames, mostly at standstill — discard |

Now an `SG_` in `CODA-D-CAN.dbc` as `ESC_0x300.YawRate`, following the
`Long_Accel` precedent: **role and zero confirmed, scale approximate.**

---

## 1. Method

No yaw signal can be guessed at, but it does not have to be — the car already
reports the wheels, and

    yaw_rate = (v_right - v_left) / track_width

so `(RR - LR)` from `0x208` is proportional to yaw rate. Three things make
that the right reference rather than steering angle:

- It comes from the **rear axle**, undriven on this FWD car, so drive slip
  does not contaminate it.
- Pearson r is invariant to scale and offset, so neither the track width nor
  the per-wheel radius bias measured in `indirect-tpms-feasibility.md` matters
  for *identification*.
- It is kinematically what yaw rate **is**. Steering angle is a driver
  *input*; yaw rate is the car's *response*, and the two part company exactly
  when a stability controller becomes interesting. Steering was scanned too,
  but only as a positive control.

Every layout required by the project's scan-completeness rule was tested:
8-bit signed/unsigned, 16-bit LE/BE signed/unsigned, 12-bit byte-aligned both
ways, and 12-bit nibble-split.

`artifacts/yaw_signal_hunt.py` (scan) and the same file's `confirm` phase.

## 2. Why this is a sensor and not a derived value

A high correlation alone proves nothing — anything shaped like the wheel-speed
difference scores well, **including a yaw value the ESC computed from the
wheel speeds itself**. Four checks separate the two, and each could have
failed:

**It is not zero at standstill.** This is the decisive one. `0x300` B6-7 sits
at 32792 with sd 12–23 counts of its own noise while the car is stopped. A
wheel-derived yaw would be **identically zero**, because both wheel speeds are
exactly zero. Sensor noise at rest is something only a sensor has.

**Correlation rises to ~1 under smoothing**, which locates the disagreement in
the reference rather than in the signal:

| smoothing | r vs wheel-derived yaw |
|---|---|
| raw (0.02 s) | 0.884 |
| 0.10 s | 0.980 |
| **0.30 s** | **0.9942** |
| 1.20 s | 0.9982 |

A genuinely different quantity would plateau; this is the reference's own
quantisation noise averaging away.

**It beats the steering control** (0.884 vs 0.859 raw), which a true gyro must,
steering being the input rather than the response.

**The low byte earns its place.** At 0.30 s smoothing, B6 alone gives 0.99013
and B6-7 gives 0.99415. Had B7 been a counter or a checksum, including it
would have *lowered* the correlation.

### The factory service manual agrees

The distilled factory manual (internal-only) corroborates this
independently, without having been used to find it:

- **`55.25.10 R&R Sensor - Yaw Rate`** is a discrete physical part, bolted to
  the body under the centre console with two 9 Nm bolts and its own harness
  connector. So the ESC reads a real gyro, which is what §2 concluded from the
  standstill noise alone.
- The ABS DTC tables call it the **"Sensor Cluster"** and check it for
  "plausibility of mis-mounted cluster or stuck **lateral or yaw rate** sensor
  signal", and for **"yaw rate scale factor out of range"**.
- One DTC condition reads: "one of the sensor signals remains constant while
  **the other two** signals show corresponding signal dynamic" — so the cluster
  carries **three** inertial channels.

Two of those three are broadcast and identified: **yaw rate** here, and
**longitudinal acceleration** at `0x330` B7 (2026-09-20). The third, lateral
acceleration, exists in the hardware but is **not** put on the bus — see §5.

No numeric scale factor appears anywhere in the manual, so §4 still stands as
the only source for it.

### Reproducibility

| log | zero | r @ 0.30 s | rate |
|---|---|---|---|
| `frombonnydoon.log` | 32792 | 0.99415 | 50.0 Hz |
| `driveafterfullycharged.log` | 32792 | 0.99448 | 50.0 Hz |
| `codadriveslowturnonwithdefroster2.log` | 32792 | 0.99593 | 50.0 Hz |
| `coda_20260818_135227_T0.log` (Android) | 32792 | 0.99565 | 50.0 Hz |

## 3. `0x300` is two unrelated messages sharing an ID

**This corrects `traction-control-analysis.md` Phase 2b (2026-05-02).**

| bus identified by content | `0x300` form |
|---|---|
| **D CAN** (7/7 anchors) | flat, `B0 ≡ 0x00`, 50 Hz — **ESC**: yaw rate + torque limits |
| **C CAN** (6/6 anchors) | 8-way muxed, `B0 ∈ {0,5,10,…,35}` — **BMS diagnostic-port traffic** |

`projects/coda/README.md` already records `0x300`–`0x304` as native C CAN
"ghost" IDs from the BMS diagnostic port; this confirms it and shows the
collision matters.

Phase 2b merged the two, which produced its "~59 Hz" figure (34,615 + 7,079
frames over ~700 s) and its "two interleaved frame types distinguished by B0".
The "Type 2 fixed-content sub-frames ... likely calibration or configuration
data" belong to a different module on a different bus.

**The bus numbering swaps between captures** — bus 1 is D CAN in
`codadriveslowturnonwithdefroster2` and C CAN in `frombonnydoon` — which is why
`yaw_signal_hunt.py` selects the ESC copy by the `B0 ≡ 0` signature and not by
channel number or frame count.

**Phase 2b's actual conclusion is unaffected**: B4:B5 ramping ~2.5 s before
`0x212` responds still shows TC is ESC-initiated. That rests on the D CAN copy.

### B7 is not MPAR_ESP parity

Phase 2b flagged B7 as a checksum candidate on the strength of "256 unique
values and high toggle rates". That is also exactly what the **low byte of a
smoothly sweeping 16-bit value** looks like, so unique-value count cannot
distinguish them. The step distribution can:

| measure | observed | a checksum byte |
|---|---|---|
| mean \|Δ(B6-7)\| between consecutive frames | **11.1** | ~85 |
| median | **8** | ~85, uniform |

Plus the low-byte check in §2. B7 is the low byte of the yaw value.

## 4. Scale, and why the obvious regression was wrong

With the owner-supplied **rear track of 59 in (1.4986 m)**, one `(RR−LR)` count
is 0.60217 deg/s, so the scale follows from the slope of `0x300` against the
reference.

**Ordinary least squares of the candidate on the reference is attenuated.** The
reference is the noisy variable, and noise in a regressor biases the slope
toward zero (regression dilution). Raw OLS gives **49.9** against a true value
near **63.5** — a 21 % error that would have gone straight into the scale.
Since `0x300` is the *clean* variable, the unbiased estimator is to regress the
reference on it and invert. At 0.6 s smoothing all three estimators converge
(OLS 63.16, TLS 63.55, inverted 63.55), confirming the noise is gone.

| log | deg/s per count |
|---|---|
| `frombonnydoon` | 0.00948 |
| `driveafterfullycharged` | 0.00954 |
| `codadriveslowturnonwithdefroster2` | 0.00940 |
| `coda_20260818_135227_T0` | 0.00935 |
| **mean** | **0.00944** (2.0 % spread) |

The DBC carries **0.0094**. Treat it as approximate: it inherits the
wheel-speed constant's own uncertainty, since the reference is built from wheel
counts. The round value **0.01 is 5.6 % away and is not supported**; 0.0095 and
3/320 = 0.009375 both fall inside the spread.

## 5. There is no lateral accelerometer on the bus

A stability controller usually reports lateral acceleration alongside yaw, and
the same reference gives it for free: `a_lat = v × yaw_rate`, so
`speed × (RR−LR)` is proportional to it. Nothing carries it.

- `0x300` B4/B5 — the torque-limit bytes — do not track it, |r| < 0.03.
- **No other ID on any bus exceeds |r| = 0.12**, and those hits are C CAN
  cell-voltage frames, i.e. noise.

So yaw rate and longitudinal acceleration (`0x330` B7) are broadcast; lateral
acceleration is not — **although the sensor for it exists**. The service manual
describes a three-channel "Sensor Cluster" and its DTCs name a lateral signal
explicitly, so the ESC reads lateral acceleration and simply consumes it
internally rather than publishing it. That is a definite negative result, not
an unfinished search.

## 6. Open

- **Scale to ±2 %** rather than ±0.5 %. Pinning it further needs a reference
  that does not come through the wheel-speed constant — a phone/IMU gyro
  logged alongside a drive would do it in one pass.
- **Whether 32792 is a designed zero or a fixed calibration bias.** It is
  24 counts above 0x8000 and identical across six months, which favours
  "designed", but nothing here separates the two.
- **B4:B5 torque-limit encoding** is still a `CM_` hypothesis, not an `SG_`.

## Artifacts

| File | Purpose |
|------|---------|
| `artifacts/yaw_signal_hunt.py` | scan (all IDs x all layouts vs yaw and lateral references) and `confirm` phase (the sensor-vs-derived tests, reproducibility, scale) |
