# Coda Indirect (Wheel-Speed) TPMS — Feasibility

**Question:** the factory TPMS sensors are dead and are Coda-proprietary, so
unreplaceable. Can a wheel-speed-based (indirect) TPMS be built from the ESC
wheel channels instead, avoiding an aftermarket retrofit?

**Answer: yes.** A single qualifying drive resolves a **2.4 psi** front-axle
differential at 3 sigma — roughly 4x finer than the 25 % under-inflation
(10.5 psi here) at which a legislated direct TPMS warns.

**Status:** feasibility established from six months of existing logs and one
gauge reading. Not yet implemented. The psi scale rests on a single
calibration point; the A/B test in the last section would pin it.

**The warning path is reachable, and now understood.** The factory telltale is
`0x600` B7 bit 5, reachable from OBD pins 2/3. But the RCU asserts it **almost
always** (all four sensors dead), so the lamp is permanently lit and carries no
information. Using it means removing the RCU and transmitting `0x600`
continuously to hold the lamp *off* — mandatory infrastructure. One parts car
reached Ready and drove with no RCU, but **that contradicts the factory manual
and the conflict is unresolved** (§6). The existing Android app is the cheaper
first output and needs none of this. See §6.

Started 2026-09-20. Corpus: **154 usable capture sessions, 448,864 filtered
samples, 2026-02-17 .. 2026-09-24** — the Android backup library plus the
primary set. The parts car is excluded by quarantine, not by filter: it is a
different vehicle in ABS fault and lives in `partscar_capture_20260304/`.

---

## 1. No pressure data on the bus — but the lamp state IS there

Checked first, because live pressures would have made everything else easy —
they would have given continuous ground truth across the whole corpus instead
of one gauge reading.

Two separate questions, with two different answers, and an earlier version of
this section ran them together under the title "There is no direct TPMS data
on the bus":

| | on the bus? |
|---|---|
| per-wheel **pressures** | **No** — nothing, anywhere (§1.1) |
| TPMS **telltale/fault state** | **Yes** — `0x600` B7 bit 5 (§1.2) |

### 1.1 No pressures

**`0x600` does not carry tyre pressures**, contrary to the DBC comment
(`VICD: misc_Recvd 0x600. Candidate: TPMS pressure (1.37 kPa/count)`):

- `(B6<<8)|B5` is an **RCU awake-time counter** — within a power cycle it is
  strictly monotonic (3,761 consecutive frames, **zero decreases**, steps of
  only 0 and 1) at ~1 count per 1.05 s. It is *not* a wall clock and *not*
  globally monotonic: it counts only time the RCU is awake, and it **zeroes on
  an RCU restart**. Measured across the 2026-09-20 17:32 → 2026-09-21 10:58
  park (17.4 h) it advanced **20 counts**, where a wall clock would have
  advanced ~59,771. Its zeroing is therefore an exact, frame-local **reset
  detector** — better than inferring power events from runs of clear frames,
  because it also reports how much awake time preceded the first logged frame.
  (Established by the concurrent service-manual session; verified here.)
- `B1=01 B2=01 B3=07 B4=00` are frozen across a whole drive.
- `B0` cycles a 4-phase tag (`00,03,10,13`) with **identical payload in every
  phase** — so it is not a per-wheel multiplexer.
- Declared DLC is 2 in the DBC; actual frames are 8 bytes.

> **CORRECTION 2026-09-21.** This list previously included "`B7` was `0x6A` in
> February and `0x4A` in September: a slow high-order counter byte, not a
> tyre." **That was wrong**, and it is the one claim in this document that was
> over-inferred: a counter was read off **two** observations, when `0x6A` →
> `0x4A` is a single-bit *decrease* that no counter produces — which should
> have caught it at the time. B7 in fact takes **exactly two values across the
> whole corpus**, and the bit that differs is the TPMS telltale. See §1.2.
> (Verified here independently: 797,401 `0x600` frames across all 1,002
> `CodaLogs` files, 713,816 at `0x6A` and 83,585 at `0x4A`, nothing else.)
> The B5/B6 counter finding above survives, though it has since been
> **refined rather than overturned**: it was checked properly within one log
> (3,761 consecutive frames, zero decreases), and that is exactly why the
> "monotonic" reading held — a single log rarely spans an RCU restart. It is
> an *awake-time* counter that zeroes on restart, not a free-running one. The
> lesson is the same one B7 taught: a property verified inside one window is
> only established for that window.

**A whole-bus sweep found no pressure-shaped channel anywhere.**
`artifacts/tpms_direct_sweep.py` gated every byte of every ID on
non-constant, not-a-counter, slow (<30 transitions/min), small-step, and
ranked by drift. The discriminating test is that **a real tyre-pressure
channel must drift upward as the tyre warms over a drive**; a frozen byte
cannot fake it. No candidate survived across drives with a consistent range,
positive drift and three siblings. Top hits are known signals (`0x080` B3
steering, `0x241` MCM thermal).

The owner confirms the sensors have never worked in his ownership, which is
consistent. **Caveat:** this shows nothing is *broadcast*; the RCU could in
principle receive on 315 MHz and keep the value internally.

### 1.2 The telltale IS on the bus — `0x600` B7 bit 5

Established by the concurrent service-manual session (`tpms_lamp_bus_path.py`,
`tpms_partscar_check.py`), and spot-checked here. It does not change any
conclusion below, but it changes what an implementation can *do* — see §6.

- **B7 takes exactly two values corpus-wide**, `0x4A` and `0x6A`, differing
  only in **bit 5**. 877 files at `0x6A`, 107 at `0x4A`, 9 catching a live
  transition. Now `SG_ TPMS_TelltaleFault` in the DBC (0 = OFF, 1 = FAULT).
- **Validated against the owner, not the data.** In
  `coda_20260921_105818_T2` the bit flips `0x4A` → `0x6A` at **11:09:55.8**
  absolute, and the owner independently reported the dash lamp lighting at
  11:10. (Reading the *chunk header* matters here: it says 11:08:19 where the
  filename says 105818.)
- **Path:** the RCU is D CAN only and the IPK B CAN only, so the frame crosses
  the gateway. `0x600` appears on both buses as a pure pass-through —
  1753 vs 1757 frames in `driverinputpart4.log`, payload sets differing by
  4 capture-edge frames out of 1753.
- **Reset and re-arm:** the fault memory is **volatile** and clears on an RCU
  restart; it then re-latches after **421.3 s of driving above 30 km/h**
  accumulated since (sd 1.07 s over six power-event clusters). Both the speed
  gate and the 7-minute figure are verbatim in the factory manual.

  **The reset is far easier to trigger than the manual claims.** The manual
  says RCU fault codes reset only on a DTC clear or a battery disconnect, and
  both this document and the DBC previously said "12 V disconnect". The one
  mid-log clear in the corpus (`coda_20260425_222956_T1`, 59.7 s in) was
  **neither**: there is no diagnostic traffic anywhere in the chunk (no 11-bit
  ID in `0x700`–`0x7FF` at all), and the `0x600` cadence is metronomic straight
  through the event — gaps 0.523 / 0.524 / 0.525 / 0.524 s with no
  interruption — yet the awake-time counter drops **4130 → 0 on exactly the
  frame the bit clears**. So the RCU restarted and resumed transmitting within
  a single frame period: a **sub-500 ms brownout is enough**. (A 3.1 s bus
  disturbance follows at t=61.3–64.4, ~1.6 s *after* the bit had already
  cleared, so it is a consequence of the restart, not its cause.)

  It also shows **bit 5 never self-clears on a live RCU** — every clear in the
  corpus coincides with the counter zeroing.

  *Carry the caveat:* two further clusters measured 303 s and 306 s with
  unlogged driving immediately before them. **~55 s of one (8/17) remains
  unexplained**, and this now holds from two independent directions: the
  odometer caps its unlogged distance at 0.5 km (≈60 s above 30 km/h), and
  the awake-time counter says 231 s of unlogged *awake* time — which is not
  driving time and so does not dissolve the gap. The 8/10 cluster by contrast
  is fully explained by its 2.4 km. The exclusion is not fully clean.
- **The blink is the cluster's, not the bus's.** B7 does not toggle (530
  consecutive `0x6A` frames after a flip), so the flash-then-steady pattern is
  generated inside the IPK.
- **Not synthesised by the gateway.** With the RCU physically removed,
  `codapartscarlog.log` has `0x600` absent on all three buses (~290 frames
  expected, zero seen) with no substitute ID. No log can show the lamp,
  since its state lives inside the missing frame. The owner's account
  supplies it (§6, §7a): on the parts car the lamp lights immediately at
  key-on, **including the first key-on after a 12 V reconnect**. So the IPK
  infers the fault from the absence.

---

## 2. Method

### Signals

| ID | Signals | Notes |
|----|---------|-------|
| `0x200` | `WheelSpeed_LF`, `WheelSpeed_RF` | valid **only** in `SubFrameID`(B0)`==0` |
| `0x208` | `WheelSpeed_LR`, `WheelSpeed_RR`, `BrakePressure` | |
| `0x080` | `SteeringAngle` | straightness test |
| `0x1C0` | `Torque` | drive-slip test, real Nm |

Wheel channels: zero = `0xC000`, **0.0567 km/h per count** (17.61 counts per
km/h) — see `../README.md` and `artifacts/vehicle_speed_chain.py`.

### Filters

Slip and cornering are far larger than the signal, so samples are kept only
while: **> 25 km/h**, **straight** (|steering| < 2 deg from the session's own
median, and steering rate < 5 deg/s), **steady** (speed within 1 % over 1 s),
**off the brakes**, and **|torque| < 20 Nm** (the Coda is FWD, so drive slip
contaminates any front/rear comparison).

**One correction worth recording.** The first version of this analysis judged
straightness by `|LF-RF|/mean < 0.004`. That **filters on the very quantity
being measured** — it truncates the LF/RF distribution and, had the true
separation ever exceeded the tolerance, would have rejected exactly the
samples carrying the signal. Steering angle is independent of the wheel
channels and is the correct gate.

### Discriminants

- `DEL = (LF+RR)/(RF+LR)` — diagonal; cancels front/rear and left/right to
  first order
- `F/R = (LF+RF)/(LR+RR)` — catches both fronts or both rears
- `L/R = (LF+LR)/(RF+RR)` — catches both lefts or both rights
- `LF/RF`, `LR/RR` — per-axle pairs

---

## 3. DEL is the right discriminant, and it is not the obvious one

The intuitive choice is `LF/RF`: the front left is the tyre that leaks, so
watch the front pair. **That is wrong**, and the data rather than theory
showed it. Changepoint detection (`artifacts/tpms_fill_events.py`, weighted
binary segmentation on a piecewise-constant fit):

| discriminant | segments | residual sd | steps found |
|---|---|---|---|
| **DEL** | 3 | **0.00010** | +0.00009 (noise), **−0.00101** |
| `LF/RF` | 5 | 0.00017 | +0.00034, +0.00056, **−0.00211**, +0.00040 |
| `LR/RR` (control) | 1 | 0.00019 | **none** |

`LF/RF` shows four steps but **only one moves the front axle without moving
the rear**. The other three move `LF/RF` and `LR/RR` *up together* by similar
amounts — a left/right common-mode effect (road camber, or a change of
route), not pressure. `DEL` is built to cancel exactly that: the three
artifacts vanish, the real event survives, and residual scatter nearly
halves.

`LR/RR` is the control channel — both rears have been equal throughout — and
it shows **no changepoints in six months**.

---

## 4. Validation: a real inflation event, found before it was reported

`DEL` finds exactly one tyre event in the logged period, pinned to **43
minutes** on 2026-07-01:

| session | DEL | LF/RF | LR/RR |
|---|---|---|---|
| `coda_20260701_193414` | 1.00050 | 1.00182 | 1.00082 |
| `coda_20260701_201737` | 0.99950 | 0.99971 | 1.00072 |

Front moved −0.00211, rear −0.00010: a **21:1** front-vs-rear ratio.

Four independent checks, none of which was fitted to produce this:

1. **The owner independently recalled "July 1 could be about right for the
   last time I filled them up"** — after being shown the date, not before
   being asked. He also expected there might be no later fill in the log set;
   there is none.
2. **Single-wheel arithmetic.** A change of `d` in LF alone must move `LF/RF`
   by `d` and `DEL` by `d/2`. Measured ratio **0.48 against 0.50 predicted** —
   confirming the front left was the only wheel that moved.
3. **Not a wheel swap.** A left/right front swap would have inverted the ratio
   to 0.99818, not 0.99971.
4. **Constant leak rate.** Fitted independently in each of the three `DEL`
   segments: **+0.0000062, +0.0000050, +0.0000056 per day** = 0.051 psi/day.
   A steady leak producing a steady slope across six months and a fill event
   is evidence the response is linear in pressure — and the consistency was
   not fitted.

Direction also corroborates independently: the owner reports the front left
has **always** been the lowest tyre on the car. A softer tyre rolls on a
smaller radius and turns *faster*, so `DEL` and `LF/RF` should sit above
baseline and climb as it leaks. They do.

**Only one fill appears between 2026-03-22 and 2026-09-18.** `DEL` rises
monotonically from the start of the corpus to 1 July with no downward step,
so any earlier top-ups predate the log set.

---

## 5. Sensitivity and detection limit

**Calibration anchor** (there is no pressure log, so psi comes from two
bracketing events):

1. the 2026-07-01 fill — taken as the moment the front pair was last levelled
2. gauge, 2026-09-20: **FL 31, FR 35, LR 33, RR 33 psi** — a 4 psi front
   differential accumulated since.

**A note on those gauge readings.** The factory placard is **42 psi**,
corroborated by the RCU's own DTC limits of 33.6 and 50.4 psi — exactly
0.80x and 1.20x of 42 — in the factory
manual's RCU DTC table (internal-only). Three
of the four gauged corners (31, 33, 33) sit *below* the low-pressure limit,
so the car was running 17–26 % under-inflated and a live RCU would have been
setting a low-pressure DTC on three corners. The dead sensors have therefore
been masking a real condition, not merely failing to report one. None of this
affects the calibration below, which uses only the front *differential*.

| quantity | value |
|---|---|
| `DEL` per psi of front differential | **0.000114** |
| residual sd between drives | **0.00010** |
| **3-sigma detection, one drive** | **2.71 psi** |
| 2-sigma detection | 1.80 psi |
| leak rate | 0.051 psi/day |
| size of the 1 July fill | ~9.2 psi |
| per-corner 3σ | LF 2.11, RF 1.89, LR 1.63, RR 1.99 psi |
| fast path, single drive | **6 psi: 0.00 % observed**; 5 psi 1.40 %; 4 psi 2.10 % |

**Rule set: `proc` 3 — 20 Nm on every contrast, 2 % steadiness, fast steering
centre, D CAN pinned by anchors.** 167 usable sessions; the sensitivity and
3σ figures come from the 137 with n ≥ 800 between 2026-02-17 and 09-18.

> **These supersede the figures published under the legacy rule set**
> (0.000110, 2.75 psi, per-corner LF 2.00 / RF 2.12 / LR 1.78 / RR 1.79).
> *Republished 2026-09-27.* Two changes moved them and both were corrections
> rather than choices: the torque cap went back to 20 Nm on every contrast
> (the 40 Nm relaxation cost 21 % of the sensitivity), and the ratios are now
> pinned to **D CAN by anchor ids** instead of chosen by frame count, which had
> been mixing the ESC's own frames with the gateway's rebroadcast at roughly
> 7:5 per capture. See `tpms-algorithm-spec.md` §1.
>
> **Pinning cost 19 % of the drives and improved every number.** The 44 drives
> dropped are the early single-dongle era with no D CAN logged at all; removing
> the native/rebroadcast mixture tightened the scatter more than the smaller
> corpus loosened it. Per corner it improved on all four: LR 1.83 → 1.63 psi is
> the largest.
>
> **The leak rate has not moved from 0.051 psi/day under any of it** — five rule
> sets, a log recovery that added six files, and a complete change of bus
> policy. It is the one number in this document that nothing has been able to
> shift.

The 9.2 psi figure extrapolates 2.3x beyond the 4 psi calibration range and
should be treated as indicative.

**Rolling-radius sensitivity is ~3–6x below the textbook rule of thumb.** A
single wheel's fractional rolling-radius change is **0.023 % per psi** — twice
the 0.000114 above, because a change in one wheel moves `DEL` by only half of
it (§4 check 2). Over a 25 % loss from the 42 psi placard, 10.5 psi, that is
**0.23 % of radius**, against the literature figure of 0.5–1.0 % per 25–30 %
loss. This is expected and not a problem: the rule is quoted for tall
sidewalls, and this car runs **205/45R17**, whose short stiff sidewall barely
changes rolling radius with pressure. The signal is smaller than advertised;
the noise floor is smaller still.

> **CORRECTION, 2026-09-21.** This paragraph previously read "~10x below the
> textbook rule" and gave the measured value as "~0.077 % radius per 25 %
> loss", and `artifacts/tpms_common_mode_accel.py` carried
> `RADIUS_PCT_PER_PSI = 0.0093` sourced from that sentence. Both dropped the
> factor of two that converts a `DEL` excursion to a single-wheel change, so
> both understated the sensitivity by 2.37x.
>
> **Nothing measured changes.** The 0.000110, the 0.00009 residual sd and the
> 2.44 psi detection limit are computed in `DEL` space and never touch radius.
> What changes is every figure expressed in radius or in the psi-equivalent of
> an absolute measurement — the accelerometer error bars in §6 below, and the
> GPS requirement, which is 2.37x **easier** than the table in §6 states. The
> accelerometer verdict is unaffected: it remains far too coarse, and it still
> returns opposite signs on two drives.
>
> Found while sizing the common-mode signal for the app's GPS channel
> (`artifacts/tpms_gps_resolution.py`). The error had propagated into a script
> constant, so it is recorded here rather than silently edited.

**Assumption that remains**, and it is the conservative direction: that the
1 July fill brought FL level with FR. Since the owner says FL has *always*
been lowest, it may never have been truly equalised — in which case the real
excursion per psi is larger and the detection limit **better** than stated.

---

## 6. What a working implementation needs

- **A learn phase.** The per-wheel mechanical baseline (tyre wear, sensor
  calibration, tone-ring tolerance) is the same size as the signal — LR and
  RR differ by a consistent 0.2 % at equal pressures. Absolute `DEL` means
  nothing; record it when the tyres are known-good and watch for **change**.
- **The filters of section 2**, unchanged.
- **~800+ qualifying samples per verdict.** At the 100 Hz valid wheel rate
  (`SubFrameID == 0`) that is **8 seconds** of qualifying driving, and the
  median drive in the corpus yields 22 s. Below 800 the estimate starts to be
  limited by averaging noise rather than by the per-drive bias floor: cutting
  the same drive down, the sd of its own mean is 0.00005 at 800 samples
  against a 0.00010 between-drive floor, rising to 0.00008 at 400 and 0.00010
  at 200 (`artifacts/tpms_filter_sensitivity.py`). Above 800 more seconds buy
  little — 1600 samples improves the total by ~5 %. Short urban drives still
  yield nothing: all four drives captured on 2026-09-20 were rejected because
  they contained no 8-second stretch meeting the filters.

- **The steering mask width is not critical between 0.5 and 3 degrees.**
  Drive-to-drive sd is flat across that range and degrades beyond it, while
  looser masks keep more drives — at 0.5 deg only 11 of 38 drives clear 800
  samples, at 2 deg 26 do. 2 deg is well placed; tightening buys nothing and
  costs more than half the usable drives.
- **Carry `F/R` and `L/R` as well.** `DEL` alone is blind to two diagonally
  opposite tyres going soft together. They are noisier (sd 0.00020 and
  0.00018) but cover the blind spot.

### What it cannot see: average (common-mode) pressure

**The ratios are blind to all four tyres changing together, by construction.**
`DEL`, `F/R` and `L/R` are ratios between wheels, so a change affecting all
four equally cancels exactly. That immunity is what makes them robust to
speed, load and surface — and it is also a blind spot. Tyres warming up over a
drive (2–4 psi, so 0.044–0.088 % of rolling radius) is therefore **not a
confound for the detector**; it is invisible to it. The same blindness means
the detector cannot see all four tyres going down together, e.g. a seasonal
ambient drop.

**The longitudinal accelerometer cannot fill that gap.** Tested, because the
idea is sound: `0x330` B7 measures acceleration in m/s² independently of
rolling radius, while the wheel channel measures it in counts/s which depends
on radius, so the regression slope between them *is* the rolling
circumference (`artifacts/tpms_common_mode_accel.py`). It fails on precision by
a wide margin, and then fails worse:

| drive | slope SE as % of radius | equivalent |
|---|---|---|
| `frombonnydoon` | ±0.356 % | ±16 psi (1σ) |
| `driveafterfullycharged` | ±0.378 % | ±17 psi (1σ) |

Against a 0.044–0.088 % signal, that is **~24× too coarse on random error
alone**, and closing it by averaging would need ~300 hours of qualifying
driving at constant pressure.

**But the decisive failure is systematic, not random.** Splitting each drive
into a cold first half and a warm second half — the actual experiment — gives:

| drive | warm − cold | significance |
|---|---|---|
| `frombonnydoon` | **+18.3 %** (≈ +832 psi) | 19.7 σ |
| `driveafterfullycharged` | **−6.1 %** (≈ −277 psi) | 7.2 σ |

Absurd magnitudes, **opposite signs**, both "highly significant". The residual
road grade left inside the 30 s high-pass differs between halves of a drive
(`frombonnydoon` descends a mountain, front-loading its grade), and the
regression's error bar cannot see that. The implied rolling circumference
across those four half-drives ranges 1.53–1.88 m against a known 1.8906 m.

*A small standard error certifies repeatability, not accuracy. A multi-sigma
result whose sign flips between two drives is measuring an artifact.*

**GPS is the right instrument for common mode.** An absolute speed reference
that does not pass through the wheel sensors is what the job needs, and the
Android logger app already runs on hardware that has one. Arithmetic, at
25 m/s cruise:

| GPS speed noise | 3σ on 3 psi | 3σ on 1 psi |
|---|---|---|
| 0.10 m/s @ 1 Hz | 6 min | 50 min |
| 0.05 m/s @ 1 Hz | 1 min | 12 min |
| 0.05 m/s @ 10 Hz | <1 min | 1 min |

*Corrected 2026-09-21 for the factor of two in §5 — these were 31 min, 4.6 h,
8 min, 70 min, <1 min, 7 min.* They assume uncorrelated fixes, which a
smoothed receiver does not give; `artifacts/tpms_gps_resolution.py` redoes
this with an autocorrelation term and adds the systematic budget, which is
what actually decides the channel.

So the random error is comfortably beatable. **Grade is the thing that must be
handled**: GPS reports *horizontal* ground speed, which understates road speed
by ~½·grade², i.e. **0.020 % on a 2 % grade and 0.125 % on 5 %** — already 2×
to 13× the 1 psi signal. It is also a one-signed bias, so it does **not**
cancel on an out-and-back pairing the way elevation energy does in
`efficiency-calculation.md`. It has to be corrected from GPS altitude rate, or
the analysis restricted to segments measured flat (|grade| < 1 %, giving
<0.005 %). **Untested** — recorded as the recommended approach, not a result.

### GPS without logging position — the collection design

**Requirement set by the owner**, refined 2026-09-24 and quoted because the
wording matters: *"I just don't want absolute GPS position stored. OK to store
enough data to theoretically integrate someone's travel from it, but ideally
we limit to only what is needed for GPS TPMS support."*

So the rule is **no absolute position; otherwise only what GPS-TPMS needs.**
That is looser than the 2026-09-21 version this document previously carried,
which forbade anything grade-derived outright, and it was relaxed
deliberately — see the note under rule 2.

**The key fact: a least-squares slope needs only five running sums.** For
`y = k·x`, the estimator is a function of `N, Σx, Σy, Σxy, Σx²` alone. Those
sums are *sufficient statistics* — the slope and its standard error computed
from them are identical to the ones computed from the raw samples. So the app
never needs to retain a single sample, let alone a coordinate.

**What is persisted per drive: sums, binned by speed.** No position, no speed
series, no altitude, nothing from which a *route* can be reconstructed.

Rules for the implementation:

1. **Never write a `Location` object anywhere.** Read `speed` from it inside
   the callback, fold it into the accumulators, and let it go out of scope.
   It must never reach a file, a log line, or a crash report.
2. **Never store altitude or altitude rate, and no per-sample grade.**
   Altitude is consumed inside the sample handler. **Σ(grade²) per speed band
   may be stored** — one scalar per band per drive. (The phone's own pitch,
   from its gravity vector, is an alternative grade source if the mount is
   rigid; also untested.)

   > **Revised 2026-09-23, approved by the owner 2026-09-24.** This rule
   > originally required the grade correction to be done purely as
   > *rejection* — gate on |grade| < 1 % and store nothing grade-derived at
   > all. Simulation (`artifacts/tpms_gps_resolution.py`) showed that does
   > not work: a gate applied to a *noisy* grade estimate leaks the
   > large-grade tail, and because the grade bias is one-signed the leak does
   > not average away. Gated bias −0.74 psi against −0.80 raw; carrying
   > Σ(grade²) and correcting afterwards gives **−0.18 psi**.
   >
   > Σ(grade²) is a scalar aggregate over a whole drive. It does not
   > localise, and it adds no positional exposure beyond the full wheel-speed
   > time series the CAN logs already contain.
3. **Persist only the accumulators**, flushed per drive alongside the
   per-drive `DEL` statistics. Band sums go in every row; no derived ratio is
   stored (see `tpms-algorithm-spec.md` §7 for why a whole-drive ratio would
   be misleading).
4. **Never accumulate a per-sample speed series**, even in memory beyond what
   the lag products need. A speed *time series* partially fingerprints a
   route; the sums do not.
5. **Collect only what the feature needs, and stop when it stops needing it.**
   The "loose" accumulators exist solely to measure whether the steady-speed
   gate can be dropped — the strict set cannot answer that, because the gate
   removes exactly the speed variation a receiver lag would displace. They
   come out once the lag is known. Recorded as a scheduled removal so it does
   not become collection by inertia.

**What this permits that the earlier wording did not.** Speed-binned sums plus
qualifying seconds let a reader bound *how far* the car travelled in a drive.
They do not say where. The owner accepted that explicitly in the wording above.

**An honest note on what this does and does not buy.** The app's existing CAN
logs already contain a full wheel-speed time series, which is itself somewhat
route-identifying. This design does not make that worse, and it adds no new
positional exposure — but it should not be described as making the app's
logging privacy-preserving overall. It makes *the GPS addition* carry no
positional data.

**The permission cost is real and worth weighing.** `ACCESS_FINE_LOCATION` is
currently declared **only** in the `companion` module, and only to read the
WiFi SSID for file sync — no code in any module calls a location API. Adding
GPS speed to the Coda app means adding that permission to a module that does
not have it, and coarse location will not do: GPS speed needs fine. That is a
user-visible location prompt on an app that has never asked for one, in
exchange for a secondary capability.

**So the feature must be optional and must degrade cleanly.** The primary
differential detector needs no GPS at all — `DEL` and the 2.4 psi result are
untouched by any of this. With GPS off or permission denied, the app should
lose only common-mode detection and behave identically otherwise.

### The factory dash lamp: reachable, but not usable as-is

Because of §1.2 an indirect TPMS could in principle light the original tyre
icon with no cluster modification — the IPK reads the telltale off B CAN,
which is OBD pins 2 and 3. That is necessary but **not sufficient**, and an
earlier version of this section claimed the warning path was "already solved".
It is not.

**The lamp is already permanently on.** All four sensors have been dead
throughout, so the RCU has loss-of-comms latched and asserts bit 5 essentially
always:

| | |
|---|---|
| frames with lamp asserted, corpus-wide | **89.52 %** (713,814 of 797,399) |
| files whose *first* `0x600` frame is already asserted | **873 of 983** |

The 10.48 % of frames with it clear are confined to the ~421 s windows after an
RCU restart, which happen only because the owner has been working on the car
(and a sub-500 ms brownout is enough to cause one — §1.2). In ordinary use the lamp is simply on. **A permanently-lit lamp carries no
information**, so it is not an available output channel in the current
configuration, regardless of what any injector does.

**Whether injection can clear it is only half-answered.** A fault telltale
that flashes then steadies may **latch inside the IPK** instead of tracking the
bit live. Two observations bear on this, and they answer different parts:

- **Upward, live: yes.** In `coda_20260921_105818_T2` bit 5 asserts at
  11:09:55.7, and the owner saw the lamp light at 11:10. The awake-time
  counter, `(B6<<8)|B5`, rises strictly 1684 → 2477 across T0–T2, straight
  through the transition. So the RCU never restarted, and the IPK followed the
  bit up mid-trip with no power event.
- **Dark while the bit is clear from power-up: yes.** Seeing the lamp *light*
  means it was dark before. Bit 5 was clear on all 1,322 frames from the
  session's first frame (10:58:19) to 11:09:55.7, identically on both buses.
  That's 696 s of dark lamp on a car whose lamp is otherwise lit 89.5 % of the
  time.
- **Downward, live: still unknown.** The one mid-log clear
  (`coda_20260425_222956_T1`, 59.7 s in, a sub-500 ms RCU brownout, §1.2)
  happened with nobody watching the dash. The 696 s window doesn't settle it
  either. That session started at key-on, so the IPK saw a clear bit from
  power-up, and "tracks the bit live" can't be told apart from "evaluates at
  power-up".

The third case is the one lamp-hold depends on. The IPK lights the lamp
immediately when the frame is absent (§7a), and an injector on the head unit is
probably not transmitting by the time the IPK powers up. So with the RCU
removed, every key-on is expected to start with no frame, a lit lamp, and then
a clear bit arriving later. Whether the lamp then goes dark is the open
question. Measured with `artifacts/tpms_lamp_dark_window.py`.

**Contention, stated correctly.** An earlier version of this section said a
crafted frame would contend such that "the arbitration winner varies per
frame". That is wrong about CAN. Two nodes transmitting the **same ID** both
*win* arbitration — the arbitration field is identical, so there is no bit on
which either loses. They proceed together into the control and data fields, and
at the first differing payload bit the node sending recessive reads back
dominant. Outside the arbitration field that is a **bit error**: an error flag
is raised, the frame is destroyed on the wire, both nodes retransmit, and both
increment their transmit error counters — toward error-passive (128) and
eventually bus-off (256). Nobody wins and the IPK sees neither value.

That applies only to frames that start in the **same bit time**. Transmissions
offset in time do not collide at all: the later node waits for bus idle and
sends cleanly. So the real picture is mostly clean interleaving, punctuated by
destroyed frames and error-counter accumulation whenever the two schedules
align — and they align more often than a duty-cycle estimate suggests, because
CAN transmitters synchronise to the bus-idle transition, so two nodes both
holding a queued frame for this ID at the end of a busy period will start
together.

One refinement neither session stated initially: on B CAN the contending
transmitter is **the gateway's rebroadcast**, not the RCU directly. Silencing
the RCU removes both, since the gateway has nothing left to forward.

**The fork is resolved, and the answer is the expensive one.** The owner
recalls that on the parts car — which has no RCU — **the TPMS lamp comes on
immediately**. First recorded on 2026-09-21 as his recollection and adopted
as the working assumption. Restated on 2026-10-04 with the detail that rules
out the obvious alternative: the lamp lights immediately **even at the first
key-on after the 12 V battery is reconnected**. So it can't be a stale latch
carried over from before; it is generated fresh from the frame's absence. So
the IPK infers the
fault from the *absence* of `0x600`, and it follows that:

- Removing the RCU does **not** give a dark lamp. It gives a permanently lit
  one, for a different reason.
- An implementation must transmit a well-formed `0x600` **continuously at
  ~1.9 Hz just to keep the lamp off**, and assert bit 5 only when it wants to
  warn. The transmitter is mandatory infrastructure, not an override.

The compensation is that this is a *clean* channel. With the RCU gone there is
no second transmitter, so none of the bit-error and error-counter trouble above
applies, and the lamp is a reliable binary output under sole control.

**Silencing the RCU is affordable: the immobiliser fails open on RCU
removal.** The RCU also houses the
keyfob receiver and the immobiliser, so the obvious worry is that removing it
immobilises the car.

What is measured, on `codapartscarlog.log` (2026-03-04, no RCU fitted, **zero
`0x600` frames on any of the three buses**):

- `0x240` B0 reaches **`0x01` = Ready, HV on**, and it is *entered during the
  capture* — `0x11` (key-on) at t=14.57 s, then `0x01` at t=19.18 s — not
  merely already-on at log start.
- Wheel speed reaches **≈21.9 km/h**, corroborated by **two independent
  healthy channels on different messages and different axles** — `0x200` RF
  387 counts and `0x208` LR 386 counts, agreeing to within one count. Motion
  spans t≈45.7–110.9 s. (Two channels agreeing across axles is a stronger
  statement than either alone, and immune to the objection that a lone peak
  might be a glitch.)

What the factory manual says, in its DLCM functionality topic
(internal-only):

> "The DLCM will not enter READY mode until the RCU has communicated that the
> correct key has been used. ... **If the RCU is not communicating then the
> DLCM will not allow READY mode to be entered.** ... If the car has been off
> for less than 15 seconds then this check will be bypassed automatically."

**These cannot both be right as stated, and which gives way is not known.**
The manual names a bypass — off for under 15 s — and this capture **cannot
rule it out**, because the car's off-duration *before* the log began is
unknown. A tempting counter-argument does not survive: `0x240` B0 sits at
`0x00` for 53.9 s mid-capture before returning to `0x01`, which looks like a
>15 s off period, but the bus runs at **1324 fps throughout it — identical to
READY — and `0x240` itself transmits 2166 frames during it**. The modules
never slept, so that is not the car being off and it tests nothing.

Other untested explanations: the manual may describe intended rather than
shipped behaviour; the DLCM's own reset clause ("will attempt to come back to
READY mode if that is where it was prior"); a defeated or unconfigured
immobiliser on that particular car; or the check applying to an RCU that is
present but failing authentication rather than absent.

**Resolved by the owner, 2026-09-25.** He unplugged the RCU on the parts car
*in order* to reach READY and drive it — with it connected, the immobiliser
asserted and READY was blocked. So this is a two-armed, deliberate
observation rather than one anomalous capture.

The natural reading is that the veto requires an **active assertion**, so an
absent RCU produces none and nothing blocks READY. That reading is an
inference rather than the owner's words, and it is what carries the result
from a car with a non-authenticating RCU to one whose RCU works normally.
**Demonstrated on the parts car; untested on the working car.**

The manual's clause is still literally wrong, but wrong by describing a
fail-closed design this vehicle does not implement — not contradicted for
reasons unknown.

*Considered and set aside*, kept because the next person to meet a READY
anomaly will reach for them as we did: the manual describing intended rather
than shipped behaviour; the DLCM's own reset clause; a defeated immobiliser
on that particular car; and the **<15 s bypass**, which was never tested and
is simply no longer *needed* to explain the observation.

**A caveat for anyone re-deriving this.** The parts car **never emits
`SubFrameID == 0x00` on `0x200`** — it is `0x14` (the ABS-fault sub-frame)
throughout, plus `0x0D`, `0x1C` and `0x1E`, three values absent from the DBC's
documented list. Every script here gates wheel speeds on `SubFrameID == 0`, so
on this car that returns nothing. Its rear-right channel is also stuck at
`0xFFFF` (DTC C102B) in 12,534 of 12,539 frames, so any max taken across both
rear channels without dropping the sentinel is meaningless.

The four channels on that capture, for anyone reusing this car:

| channel | max | |
|---|---|---|
| `0x200` B4-5 RF | 387 counts (22.0 km/h) | healthy |
| `0x208` B6-7 LR | 386 counts (21.9 km/h) | healthy |
| `0x200` B2-3 LF_secondary | 374 counts (21.2 km/h) | reads low |
| `0x200` B6-7 LF | 372 counts (21.1 km/h) | reads low |
| `0x208` B4-5 RR | — | **faulted**, `0xFFFF` throughout (C102B) |

None of the `0x200` channels carries any `0xFFFF`. **LF peaks ~14 counts below
RF and LR**, which over a 65 s crawl could be a genuine cornering/slip artifact
or an LF sensor reading low — not chased, but **LF is the channel to distrust
after RR** if this car is used for wheel-speed work. Averaging the front pair
is also the wrong statistic on a FWD car and is depressed here because the LF
and RF peaks are not simultaneous.

**A cheaper output exists and should be weighed first.** This project already
ships an Android app for the Coda (`android-app/`), which can read the bus over
the same OBD connection. Surfacing a tyre warning there needs no RCU removal,
no continuous transmitter, and no loss of remote locking. The dash lamp is the
better *product*; the app is the better *first implementation*, and the
detection stage — which is the hard part and is already solved — is identical
for both.

**What the other bits mean is still unknown.** B1-B4 are frozen at
`01 01 07 00` throughout the corpus precisely *because* all four sensors have
been dead the whole time, so nothing here reveals whether they carry per-wheel
detail. That needs a car with a working sensor, or a bench RCU.

---

## 7. Open items

Two, and they are independent: **7a decides whether there is a usable *output*
at all**, and 7b decides the *detection* accuracy. 7a is the one that can
invalidate the product, so it goes first.

### 7a. The output stage — absence-inference confirmed by the owner

**Resolved 2026-09-21 by the owner's recollection, and restated with the
deciding detail on 2026-10-04:** on the parts car, with no RCU fitted, the TPMS
lamp comes on immediately, **even at the first key-on after the battery is
reconnected**. The IPK therefore infers the fault from the absence of `0x600`.
That fixes the design: a transmitter must send continuously at ~1.9 Hz to hold
the lamp off (§6).

The battery-reconnect detail is what settles it. A 12 V reconnect clears any
state the cluster could have carried over, so a lamp lit immediately afterwards
comes from the absence itself, at power-up, with no noticeable timeout. That
was the confirmation this paragraph used to ask for. It is still the owner's
report and not a logged measurement, as any lamp observation has to be.

**The RCU-removal step is gated on a power cycle** — reinstated 2026-10-03,
having been wrongly removed. The manual-versus-measurement conflict was
resolved by the owner on 2026-09-25 (§6): he removes the RCU on the parts car
*in order* to reach READY, because with it fitted the immobiliser asserts and
blocks READY. The cold-start test this section originally demanded existed
only to close out the manual's <15 s bypass clause, and that rationale is
indeed dead — so this section dropped the gate entirely. That was wrong: the
**action** the gate prescribed is required for a different reason.

The owner's fuller account, 2026-10-03, **as recollection rather than
measurement and hedged in his own words** ("I think you need to"): the DLCM
*latches* the assertion. Once it has been told there is an immobiliser
problem it keeps blocking, and the car must be power-cycled before RCU
absence stops mattering. Three states, not two:

| state | READY |
|---|---|
| RCU fitted, failing authentication | blocked — DLCM is being told |
| RCU unplugged, **no** power cycle since | **still blocked** — DLCM remembers |
| RCU unplugged, power-cycled since | allowed — absence vetoes nothing |

Not verified from logs. The parts-car capture cannot test it either way, since
whether a power cycle intervened before `codapartscarlog.log` is unknown.
**Anyone pulling an RCU and expecting to drive away should plan on a power
cycle.** Also recorded in the distilled factory manual
(internal-only), which is where a reader meets the clause this contradicts.

Still unexamined, and answerable only on the car:

- **whether the IPK tracks bit 5 down live.** Two cases are measured in §6:
  the lamp follows the bit up, and it stays dark while the bit is clear from
  power-up. A clear bit arriving *after* a period of absence is not measured,
  and that is exactly the lamp-hold case. It can be answered on the first
  key-on with the RCU removed and the transmitter enabled:
  - lamp lit at key-on, then dark once the app is transmitting: it tracks the
    bit down, and lamp-hold works as designed;
  - lit the whole time: the lamp latches per power cycle, and the transmitter
    has to be running before the IPK wakes.
- **the timeout.** At power-up there's effectively none: the lamp lights
  immediately. What period a running synthetic frame has to beat mid-drive is
  still unmeasured. The RCU's 523–525 ms is the safe target.
- what `B1`–`B4` encode. They are frozen at `01 01 07 00` throughout the corpus
  *because* all four sensors have been dead the whole time, so establishing
  whether they carry per-wheel detail needs a working sensor or a bench RCU.

### 7b. The A/B test that would settle the psi scale

The trend *shape* is solid: two leak cycles, a front-only step, a flat rear
control, a constant leak rate. The **psi scale is one measurement**.

Procedure: gauge all four, drive a highway route long enough to clear ~800
filtered samples, deflate one corner by a known amount, drive the same route,
compare. With a 0.00010 noise floor even a 3 psi change lands at ~3 sigma, so
the test is cheap and decisive. It would also measure the response of a
*rear* corner, which the corpus cannot — every event in it is front-left.

---

## Artifacts

| File | Purpose |
|------|---------|
| `artifacts/tpms_direct_sweep.py` | whole-bus hunt for pressure-shaped channels (section 1) |
| `artifacts/tpms_wheel_ratio_trend.py` | corpus sweep: 331 sessions, 12 workers, ~3 min → CSV |
| `artifacts/tpms_wheel_ratio_trend.csv` | per-session filtered wheel ratios |
| `artifacts/tpms_wheel_ratio_trend.out` | sweep log |
| `artifacts/tpms_fill_events.py` | changepoint detection across discriminants (section 3) |
| `artifacts/tpms_sensitivity.py` | calibration and detection limit (section 5) |
| `artifacts/vehicle_speed_chain.py` | wheel-speed scale, anchored to `0x491` odometer |
| `artifacts/tpms_lamp_bus_path.py` | **(not mine)** telltale bus path, B7 corpus sweep, re-arm timing — §1.2 |
| `artifacts/tpms_partscar_check.py` | **(not mine)** RCU-absent parts-car scan — §1.2 |
