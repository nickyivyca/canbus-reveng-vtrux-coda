# Coda Traction Control Analysis

**Log:** `projects/coda/logs/codadriveslowturnonwithdefroster2.log` (B+C+D CAN)
**Started:** 2026-03-19

---

## Phase 1 -- TC Event Detection (COMPLETE)

### Wheel speed signal location

The plan assumed TC events would appear in `0x312`. This was wrong. `0x312` B0-B3 are a
multiplexed structure (B0 is a mux/counter byte cycling through ~30 unique values, B1/B3
carry interleaved analog channels). B4-B5 = ESC ABS/decel status (constant 3199 during
normal driving), B6-B7 anomalous in this log (stuck at 800, well below the expected zero
of 2000).

**Actual wheel speed location: `0x208`**
- B4-B5 = DHL (left halfshaft), BE uint16, zero = 0xC000 = 49152
- B6-B7 = DHR (right halfshaft), BE uint16, zero = 0xC000 = 49152
- Rate: 200 Hz
- DBC labels these WheelSpeed_FL / WheelSpeed_FR as HYPOTHESIS -- now confirmed by driving data.

No front/rear distinction is available. The 0x312 channels that were expected to carry
front wheel speeds have a different structure and do not decode as wheel speeds in this log.
DHL/DHR are the only confirmed wheel speed channels.

### TC events found

17 events detected via DHL/DHR divergence >= 30 counts for >= 0.2s.
Grouped into 5 clusters:

| Cluster | Events | Time range (s) | Notes |
|---------|--------|----------------|-------|
| A | A1-A3 | 59.6 -- 90.6 | First acceleration out of slow section |
| B | B4-B7 | 106.5 -- 148.1 | Second acceleration cluster |
| C | C8-C10 | 244.8 -- 246.6 | Short cluster, cornering |
| D | D11-D13 | 445.7 -- 451.5 | Fourth cluster |
| E | E14-E17 | 620.2 -- 622.9 | Final cluster near end of drive |

Full timestamp table in `artifacts/tc_events.txt`. Plots in `artifacts/tc_cluster_*.png`.

### Cornering vs real slip discrimination

Added steering angle (0x080 B2-B3, center=2000, scale=0.1 deg) to plots. Events where
DHL/DHR diverge during cornering (inner vs outer wheel speed difference) are distinguishable:
- A1, A2, C8-10, D11-13 have strong steering angle correlation -- likely cornering-induced
- A3, B4-7 have confirmed motor torque cuts while throttle is held -- real TC events

### Second TC mechanism: symmetric slip (no DHL/DHR divergence)

The t=500-630s window contains repeated motor torque reductions that are NOT detected by
the wheel divergence method -- both driven wheels slip equally, so DHL-DHR stays near zero.
These are identified via the torque-cut detector (torque drops >20 Nm in 0.5s while throttle
stays within 5% and is >3%). Plots in `artifacts/tc_cluster_f-torquecuts.png`.

---

## Anti-Lash Smoothing -- CONFIRMED (2026-03-19)

### Finding

The Coda DLCM applies **torque smoothing specifically at the driveline lash point (torque
zero-crossing)**, not at the initial ramp-up of the throttle pedal.

Confirmed by examining 8 zero-crossing events (torque negative->positive while throttle held):
in every case, the throttle pedal (0x210 B2) is already at a stable non-zero value (15-60%)
when motor torque crosses zero. The zero-crossing happens because car inertia/regen is
decelerating the vehicle to the point where the steady throttle produces net zero torque --
not because the driver is pressing the pedal for the first time.

Evidence:
- **Throttle is flat** at the crossing in events #1 (20%), #2 (20%), #4 (23%), #6 (25%)
- **MCM torque ramps slowly through zero** while throttle does not change -- rate-limited
  at the zero-crossing, not upstream in the throttle signal
- **DLCM B5 (0x212)** drops to near-zero right at the crossing then recovers, confirming
  the DLCM is the source of the smoothing (it momentarily requests minimal torque to let
  the driveline slack take up quietly before ramping to the throttle-proportional value)
- Crossing #6 shows **driveline ringing (~10 Hz oscillation in MCM torque)** around zero,
  the characteristic signature of lash excitation. The smoothing limits amplitude but
  does not fully suppress it at low vehicle speeds.

### Analysis implication

Divergence between throttle input and motor torque output is **not always TC**. At every
torque sign change (regen to drive), there will be a deliberate torque suppression window
lasting ~0.3-0.8s. When identifying TC events in future analysis:

**Ignore torque-vs-throttle divergence that occurs at or immediately following a torque
zero-crossing.** Only flag divergence that occurs while torque is already clearly positive
and throttle is held steady -- that is the TC signature.

### Artifacts

| File | Description |
|------|-------------|
| `artifacts/lash_analysis.py` | Script to find zero-crossing events and plot throttle/DLCM/torque |
| `artifacts/lash_crossing_01-08.png` | Per-crossing overlay plots |
| `artifacts/lash_overview.png` | Full-drive overview with crossings marked |

---

## Phase 2 -- TC Signal Mechanism (Partial Findings)

### Deep dive: torque cut at t=597s (COMPLETE)

Examined raw frames in window t=596.5-600.5s (`artifacts/tc_deep_dive.py`).

**Primary finding: no ESC discrete bits toggle.**
- `0x208` ESPSts=1 constant, BP=0 constant -- no wheel braking applied
- `0x312` B4-B5=3199 constant -- no ABS/ESC status bits change throughout

**The mechanism is entirely quantitative via 0x212 B5.**

`0x212` is the DLCM torque request (50 Hz, two interleaved sub-frames keyed by B2=0x0C/0x00
at 25 Hz each). **B5 is the torque limit/request value** (uint8). During the TC event:

| Time (s) | B5 (hex) | B5 (dec) | MCM torque (Nm) |
|----------|----------|----------|-----------------|
| 596.51 | 0xC8 | 200 | ~200 |
| 596.69 | 0xBB | 187 | -- |
| 596.71 | 0x9F | 159 | ~252 (lag) |
| 597.13 | 0x67 | 103 | ~229 |
| 597.49 | 0x19 | 25 | -- |
| 597.69 | 0x07 | 7 | -- |
| 597.79 | 0x00 | 0 | ~205 |

Ramp from B5=200 to B5=0 takes ~1.1s. MCM torque follows with ~20-50ms lag.

**0x212 message structure:**
- B0-B1: always 0x00 0x00
- B2: alternates 0x0C / 0x00 (sub-frame mux at 25 Hz each)
- B3: always 0x00
- B4[7:6]: 2-bit Gray-code rolling counter (0,1,3,2 sequence)
- B4[5:0]: 0x2B (constant 43) during TC cut; changes to 0x2A at recovery onset
- B5: torque limit/request value

**Secondary finding: 0x312 B6-B7 activates at TC end.**
Value stuck at 800 throughout drive, then starts increasing from 800 to ~1200 exactly when
the TC event ends (t=597.99s, coinciding with motor speed increasing past ~1580 rpm). May
be a wheel speed channel with a minimum speed threshold, or an ESC counter. Not yet decoded.

~~**What initiates the cut is unknown.**~~ **ANSWERED -- see Phase 2b (0x300) below.**
0x300 is the ESC torque limits message; its B4:B5 pair begins ramping ~2.5s before 0x212
responds, confirming ESC-initiated TC via D CAN, not DLCM self-detection.

---

## Phase 2b -- 0x300 ESC Torque Limits (2026-05-02)

Analysis via `artifacts/dlcm_0x300_tc_analysis.py`. Context: DLCM spec §8.3.1 names
0x0300 as the ESC torque limits message carrying MMIN_ESP, M_ESP, MMAX_ESP_REGEN_TQ_REQ,
MPAR_ESP, and MTOG_ESP. This was confirmed against TC events in the defroster2 log.

### Message structure

0x300 runs at ~59 Hz and contains two interleaved frame types distinguished by B0:

**Type 1 — B0=0x00, high-rate (~50 Hz):** The live signal frames. B4:B5 carry a
continuously varying 16-bit value. B1 bit 7 alternates in a 0-0-1-1 pattern (MTOG_ESP
candidate). B2-B3 are static throughout the log.

**Type 2 — B0=non-zero (0x05, 0x0A, 0x0F, 0x14, 0x19, 0x1E, 0x23), ~6 Hz each:**
Fixed-content sub-frames. B1-B5 are completely static — same byte values every time,
regardless of vehicle state or TC. These likely carry calibration or configuration data.

B7 has 256 unique values and high toggle rates — MPAR_ESP parity checksum candidate.

### What changes during TC

**B6 (all sub-frame types):** During normal driving B6 cycles slowly through
`0x58, 0x5C, 0x60, 0x64, 0x68, 0x6C, 0x70, 0x74`. During TC it jumps to `0x8C` or
`0x9C` — values that never appear outside TC windows. This is the clearest discrete TC
flag in the message; MMIN_ESP flag candidate (bit 7 set = limit active).

**B4:B5 in Type 1 (B0=0x00) frames:**
- Baseline (non-TC): alternates between `0x080C` (2060) and `0x880C` (34828) — the same
  underlying value with B1 bit 7 toggling as the MTOG parity field
- TC lead-up (t=593.87s, ~2.5s before 0x212 begins cutting): B5 ramps up 0x0C → 0x7C,
  B4 upper nibble increments (0x08 → 0x0C / 0x88 → 0x8C); pair reaches ~3196/35964
- TC peak (~594.9s): stabilizes briefly at 3196/35964
- Torque cut active (t=596.51s onward, when 0x212 B5 starts ramping): B4:B5 ramps back
  down, oscillating in the ~2960 range as DLCM responds
- Recovery: descends back toward 2344 as TC releases

**Phase 4 correlation (full log): 0x300 B5 vs 0x212 B5 = r = +0.821.** Strong positive
correlation confirms B4:B5 tracks motor torque demand in real time; M_ESP limit candidate.

### Key finding: ESC acts 2.5s before DLCM responds

0x300 B4:B5 begins its ramp at t=593.87s. 0x212 B5 does not begin cutting until
t=596.51s (~2.5s later). The ESC is watching for slip and pre-loading its torque limit
well before the DLCM acts on it. The DLCM is responding to the ESC command, not
self-detecting slip.

### Signal role hypotheses (unconfirmed)

| Byte(s) | Candidate role | Basis |
|---------|---------------|-------|
| B6 | MMIN_ESP flag | Discrete jump to high values during TC only; present in all sub-frames |
| B4:B5 (Type 1) | M_ESP torque limit | r=+0.82 vs motor torque; ramps before and during TC |
| B1 bit 7 (Type 1) | MTOG_ESP toggle | 0-0-1-1 pattern in B0=0x00 frames |
| B7 | MPAR_ESP parity | 256 unique values, high entropy |
| B1-B5 (Type 2, non-zero B0) | Configuration / calibration constants | Completely static across all driving conditions |

Scale and offset for M_ESP not yet determined. DBC entry pending scale confirmation.

---

## Wheel Speed Signal Identification (COMPLETE, 2026-03-19)

### Method

Cross-validated across three logs: `codadriveslowturnonwithdefroster2.log`,
`frombonnydoon.log` (1972s, best left/right balance), and `codapartscarlog.log`.

**Ackermann geometry test:** computed OLS regression slope of (channel - vehicle_speed) vs
steering angle (0x080 B2-B3, center raw=20000) for all moving non-TC frames. An
Ackermann-responsive channel (individual wheel sensor) produces a non-zero slope; a
steering-neutral channel (axle average, rear torsion beam, or duplicate) produces slope ~0.

**Parts car cross-check:** with C102B (Right Rear Wheel Speed Sensor Circuit) active,
the faulted channel should output a fault sentinel in place of valid speed data.

**TC event sequence:** during the 597s symmetric-slip TC event, 0x200 B4-B5 spikes first,
then 0x200 B2-B3/B6-B7 spike more -- consistent with right front losing traction first,
then left front following.

### Results

| Channel | Slope (counts/steer_count) | r | Identity | Basis |
|---------|---------------------------|---|----------|-------|
| 0x200 B2-B3 | ~0 (circular ref) | ~0 | Left Front (secondary) | TC spike; outer in right turns vs B4-B5 |
| 0x200 B4-B5 | -0.0248 | -0.822 | Right Front | Ackermann inner-right; TC spike |
| 0x200 B6-B7 | ~0 (circular ref) | ~0 | Left Front (primary) | Same sensor as B2-B3; TC spike |
| 0x208 B4-B5 | -0.0253 | -0.813 | Right Rear | Ackermann inner-right; C102B DTC; fault sentinel in parts car |
| 0x208 B6-B7 | -0.0005 | -0.031 | Left Rear | Ackermann neutral; does not spike in TC |

Note on circular reference: vehicle speed reference was computed as (0x200 B2-B3 + 0x200
B6-B7) / 2, which forced those two channels to show r=0 against themselves. Their
left-front identity is established instead by (a) the pairwise correlation steer vs
(B2-B3 - B4-B5) = r=+0.746 (B2-B3 is outer when B4-B5 is inner), and (b) both channels
spiking during FWD TC events.

### 0x200 message structure

- B0: sub-frame mux byte. B0=0x00 = primary wheel speed sub-frame (200 Hz). Other values
  observed: 0x0A/0x0B (startup transition frames), 0x20 (appears only during TC events,
  ~400ms before torque cut -- significance unknown), 0x14 (parts car, same structure as
  0x00, B0 value reflects ESC fault state).
- B1: rolling counter within sub-frame (0-125).
- B2-B3: WheelSpeed_LF_secondary -- left front, BE uint16, zero=0xC000. Identical to
  B6-B7 (same physical sensor broadcast twice).
- B4-B5: WheelSpeed_RF -- right front, BE uint16, zero=0xC000.
- B6-B7: WheelSpeed_LF -- left front, BE uint16, zero=0xC000. Primary channel.

Scale (counts to physical speed) not yet confirmed. Zero encoding (0xC000=49152) matches
0x208 B4-B5/B6-B7.

### 0x208 B4-B5 and B6-B7 -- corrected from HYPOTHESIS

Prior DBC had these labeled WheelSpeed_FL/FR (front). Corrected to rear:

- **B4-B5 = Right Rear.** Confirmed by: (a) Ackermann inner-right slope r=-0.813 matching
  0x200 B4-B5 (right front); (b) C102B DTC "Right Rear Wheel Speed Sensor Circuit" on
  parts car; (c) parts car: B4-B5 stuck at 0xFFFF (fault sentinel, the standard ESC
  invalid-sensor value) with only brief 0xC000 at startup -- 2 unique values vs 1674 in
  healthy car. Channel does not spike during FWD TC events (non-driven axle).
- **B6-B7 = Left Rear.** Ackermann neutral (r=-0.031). Does not spike during TC. Vehicle
  reference speed throughout the drive.

### 0x312 -- Structure Decoded (2026-03-20)

Full analysis via `artifacts/analyze_0x312.py` and `artifacts/analyze_0x312_composite.py`
and `artifacts/analyze_0x312_scale.py` (defroster2 + frombonnydoon cross-validation).

#### B0 mux structure

B0 = (4-state Gray-code counter in high nibble) | channel_ID (in low nibble).
30 observed B0 values collapse to 7 real channel IDs (6,7,8,9,10,11,12) + startup (0,32).
B0 counter states: high nibble cycles 0x0,0x2,0x4,0x6 (Gray-code, 4-state, ~25 Hz each).

**B2 = B0 low nibble (channel ID echo)** -- B2 carries no independent data.
**B1 = B3 (redundant)** -- same signal broadcast in both byte positions, identical
statistics across both bytes for every channel.

#### Channel distribution vs vehicle state

Lower channel IDs appear at HIGHER vehicle speeds; higher channel IDs at LOWER speeds
or during TC/ABS intervention. Channel 8 dominates normal driving (~63%).

| Channel | % normal drive | B4-5 range | B6-7 range | Vehicle state |
|---------|---------------|------------|------------|---------------|
| 6 | 8% | 2000-3199 | 800-2000 | High speed sections |
| 7 | 26% | 2000-3199 | 800-2000 | Medium-high speed |
| 8 | 63% | 2685-3199 | 800-1705 | Normal driving (dominant) |
| 9 | 7% | 2859-3199 | 800-1641 | Lower speed / higher load |
| 10-12 | <4% | 2869-3199 → 3199 | 800 | Low speed / TC / ABS |

Ch 0/32: startup frames only (20-18 frames), all zeros except B4-5=2000, B6-7=2000.

#### B6-B7 = vehicle/rear-axle speed proxy

- **2000 (0x07D0)**: initialization only (first frames after key-on, before Ready mode)
- **800**: ESC floor -- clamped here when (a) speed is below ~LR=550 threshold, or
  (b) TC intervention is active (even if vehicle is at moderate speed)
- **Above 800**: proportional to vehicle speed. Rises from ~900 at LR=600 to ~1704 at
  LR=1703 (max observed). During cruising at LR=1456-1703 (defroster2): B6-7=1645-1704.
  During bonnydoon at LR=825-945: B6-7=1095-1348.
- The "800 throughout" observation from prior TC analysis was misleading -- it was clamped
  during the TC event window. Normal cruising data shows clear speed tracking.

**Scale estimate (provisional):** at zero speed B6-7≈800 (floor, not absolute zero),
at LR=1703 B6-7≈1704. Cannot derive a clean physical unit without knowing LR's km/h scale.

#### B4-B5 = driven-wheel speed or slip reference (PROVISIONAL)

- **2000**: initialization only (key-on startup frame)
- **2119**: stationary in Ready mode (brakes applied / motor idle)
- **3199**: UPPER FLOOR -- clamped at maximum when (a) TC intervention active, or (b)
  vehicle speed is below the measurement threshold (holds throughout most of bonnydoon log
  where max LR=945)
- **Below 3199**: proportional to vehicle speed at HIGH SPEEDS ONLY. In defroster2 cruising
  (LR=1456-1703): B4-5=2685-2804 (inversely proportional -- higher speed = lower B4-5).
  In bonnydoon at max speed (LR=945): B4-5 barely dips to 3153.
- Interpretation: B4-5 encodes speed with an inverted relationship (higher speed → lower
  value) and saturates at 3199 for low-moderate speeds. Only resolves at high speeds.

**Prior misidentification corrected:** B4-5 was called "ESC ABS/decel status (constant
3199 during normal driving)" based on defroster2 only. Confirmed now: 3199 is a saturation
floor for low speeds, not a binary decel flag.

#### B1/B3 = motor torque echo (CONFIRMED 2026-03-20)

Analysis via `artifacts/analyze_0x312_b1.py` and `artifacts/analyze_0x312_b1_torque.py`.

**B1 strongly correlates with 0x212 B5 (r=0.84 for Ch8, r=0.73-0.85 across all channels).**
The correlation holds entirely outside the TC event window (r_notc = 0.74-0.84), ruling out
TC-driven confound.

Key findings:
- Checksum hypothesis rejected: B1 == XOR(B0,B2-B7) for only 217/64501 frames (~0.3%,
  near-random). No sum/XOR formula matches consistently.
- r(B1, wheel speeds) < 0.35 for all channels -- B1 does not encode vehicle speed.
- Delta correlation r(dB1, d-wheel-speed) < 0.01 -- no dynamic tracking of wheel speed.
- Direct value comparison (Ch8): B1 = 0x212 B5 exactly in 4.2% of aligned frames,
  within +-2 in 20.9% (vs 1.2% and 3.1% expected by chance).
- 0x212 B5 is NOT a simple limiter stuck at 200. It varies continuously 0-255 throughout
  the drive (all 256 values observed), with 208 as the idle/stopped value.

**Interpretation:** 0x312 B1/B3 echoes the motor torque output signal from 0x212 B5 into
the ESC's wheel-speed multiplexed frame. This provides torque context alongside the speed
data. The ~10-15 count residual difference may reflect different ADC, slight time offset,
or commanded vs measured torque. The composite (channel<<8|B1) is therefore NOT a separate
ESC computation -- it conflates channel ID with a torque-like quantity.

Note: 0x212 B5's physical units remain unconfirmed. Prior TC analysis called it "torque
limit" because it ramps to 0 during TC; however, the continuously varying behavior over
0-255 during normal driving suggests it is actual motor torque output or demand, not a limit.
The "ramp to 0" during TC is consistent with a torque cut applied to stop wheel spin.

#### TC-related behavior summary

During TC intervention: B4-5=3199 AND B6-7=800 (both clamped to their limit values),
regardless of vehicle speed. This is the ESC's way of signaling "intervention active --
these speed measurements are unreliable." The channel number shifts to 9-12 during TC.
Both signals return to normal values after TC releases (B6-7 first, then B4-5 requires
higher speed to unlock).

---

## Remaining Work

### Survey remaining D CAN IDs during TC windows

0x300 confirmed as ESC torque limits message (see Phase 2b above). Remaining candidate
IDs not yet examined: `0x080, 0x215, 0x241, 0x278, 0x418, 0x55C, 0x580`.

### Confirm brake-based vs torque-only TC

For asymmetric-slip events (A3, B4-7): check if 0x208 brake pressure rises on one wheel
without the brake switch (0x315 B0 bit0) being set. If yes, brake-based TC is active
alongside or instead of torque reduction.

### Decode 0x212 B5 units

B5=200 corresponds to MCM torque of ~200-250 Nm. B5=0 does not produce zero motor torque
(MCM torque levels off at ~200 Nm when B5=0x00 during the ramp). Determine scale/offset.
Also determine whether B4[0] is part of a 9-bit value spanning B4[0]:B5.

### DBC updates needed

- `0x200`: add new message with WheelSpeed_LF (B6-B7), WheelSpeed_RF (B4-B5),
  WheelSpeed_LF_secondary (B2-B3). Document sub-frame mux structure in CM_. DONE 2026-03-19.
- `0x208`: rename WheelSpeed_FL/FR to WheelSpeed_RR/LR (corrected from front to rear).
  Add fault sentinel note for B4-B5 (parts car C102B). DONE 2026-03-19.
- `0x312`: B0 mux structure decoded (2026-03-20). B2=channel_ID echo (not data). B1=B3
  (redundant). B6-7=vehicle speed proxy (proportional, floor at 800). B4-5=inverted speed
  reference (saturated at 3199 for low speeds, resolved at high speeds). B1 physical meaning
  unresolved. Update CM_ in DBC stub with mux description; do not add SG_ for B1 until
  confirmed.
- `0x212`: add SG_ for B5 torque limit (role confirmed, scale unconfirmed), document
  B2 sub-frame mux and B4 Gray-code counter in CM_
- `0x300`: add BO_ stub as ESC_TorqueLimits (per spec §8.3.1). No SG_ entries until signal
  scale confirmed. CM_ should note two-frame-type structure (B0=0x00 live signals vs
  non-zero B0 fixed config), B6 TC flag (0x58-0x74 normal / 0x8C-0x9C TC active), and
  B4:B5 as M_ESP candidate (r=+0.82 vs motor torque, scale unconfirmed).
