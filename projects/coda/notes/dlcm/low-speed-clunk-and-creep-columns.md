# Low-speed driveline clunk and the creep columns

Two open problems that live in the same place — the bottom three speed columns of
the DLCM accelerator map — and that the user has asked be worked **together**
rather than separately. Opened 2026-09-24. Nothing here has been acted on.

The connecting fact: every proposal in the pedal-map redesign
(`pedal-map-envelope-design.md`) deliberately leaves this region alone, so both
problems below survive into the calibration currently on the car.

---

## 1. Direction-change clunk (D <-> R while still rolling)

**Reported by the user 2026-09-24**, after the creep-preload reduction: shifting
D->R or R->D while still slightly moving is clunkier than before. Re-reported
after the C4c pedal map was flashed and driven — **still clunky**, so C4c neither
caused nor cured it.

### What the corpus says — REMEASURED 2026-09-26, and the earlier table is withdrawn

> **The table that stood here reported a median normalised step of +1.0 in every
> cohort and concluded there was no cohort effect outside the launch-rate flash.
> That was an artefact of the metric, in two independent ways, and it is
> withdrawn.** The creep conclusion in it survives; the "no effect" one does
> not. Superseded by `artifacts/gear_change_clunk.py`, which sweeps the same
> corpus with the two faults below fixed.

`artifacts/dr_shift_clunk.py` scored the largest single-sample `Long_Accel` step
in the **2.5 s** after the shift, minus the same event's pre-shift baseline step.
Both halves are wrong for this question.

**Fault 1 — an invalid-sensor burst fabricates the largest steps.** `Long_Accel`
raw >= 200 is the invalid sentinel. It arrives as a burst of **exactly six
samples (120 ms)**, about once per five-minute chunk, and it fires at standstill
with a 1-count torque request as readily as under load — so it is not a clunk.
Aligned across 14 bursts in 18 captures it has a fixed shape, baseline 123.5 raw:

```
sample     -2    -1   |burst|   +1    +2    +3    +4    +5    +6    +7
median   123.0 127.5  (>=200) 139.0 132.0 131.5 131.5 131.0 125.5 124.5
```

so the artefact runs from one sample before the burst to about seven after, and
the **decay back to baseline fabricates a -6 to -12 step five or six samples
later** — above the 4-count real-signal threshold and far enough from the burst
to look like an unrelated event. One such step was the largest value in the C4c
cohort until it was guarded (21 counts; the real maximum is 12). 21 of 745
events had a burst in their window. The guard is two samples before an invalid
run and eight after.

**Fault 2 — the window scores the launch, and the baseline is not independent.**
A reversal is normally followed within a second by the driver getting on the
pedal: in the C4c reversal at `coda_20260924_231904_T0` t=119.397 the pedal
reaches 36 % at t+1.2 s and torque 160 Nm, all inside a 2.5 s window. And
`step_base` is not a control — the approach to a reversal is a braked
deceleration governed by the falling limbs, and flash 2 tripled
`gradientLimiterNegative_TrqLast` idx0..3, so subtracting it removes part of the
effect under test.

The replacement window is **0 to 0.6 s**, which covers the slowest case (the
limiter needs 620 ms to reach 63 Nm on stock and 80 ms now). The replacement
control, `road50`, is the accelerometer step distribution over samples where the
**command is not moving** and the car is rolling at walking pace — road surface
plus sensor noise, and nothing the calibration can touch.

1058 captures, **745 reversals, 393 of them rolling** (|motor rpm| >= 100 in the
0.6 s before). Cohorts are assigned from absolute wall clock at flash **end**,
which matters for the two captures that span a flash — `coda_20260924_004341_T1`
(flash 5) and `coda_20260924_222022_T11` (flash 6, at t=57.4..190.7 s). The old
cohort list stopped at flash 5, so every C4c event was silently labelled C2.

| cohort | n | step p50 | p90 | jerk² p50 | road p50 | Δcmd p50, raw |
|---|---|---|---|---|---|---|
| pre-campaign | 192 | 4 | 7 | 3 | 0 | 16 |
| stock + FLOOR5 | 148 | 4 | 8 | 4 | 0 | 31 |
| FLOOR20 | 18 | 5 | 8 | 4 | 0 | 40 |
| FLOOR40 + speed limb 40 | 8 | 7 | 10 | 5 | 0 | 51 |
| negTrqLast x3 | 5 | 7 | 7 | 5 | 1 | 56 |
| C1 creep 50 | 5 | 6 | 8 | 6 | 1 | 54 |
| **C1 + launch rate** | 5 | **9** | 10 | 6 | 0 | **86** |
| C2 one-pedal | 6 | 9 | 10 | 7 | 0 | 80 |
| **C4c (on the car)** | 2 | 8 | 9 | 9 | 0 | 80 |

Pooled and matched on entry speed (rpm_pre 150–500): **step p50 4.0 (bootstrap
CI 4–5) before, 7.0 (CI 7–8) after**; second-difference jerk 3.0 (CI 3–4) to 6.0
(CI 5–7). **The road control does not move.** `Δcmd` is the largest commanded
torque step inside the window and rises 16 -> 80 raw, a factor of five.

So the clunk metric roughly **doubles** across the campaign, monotonically, and
the rise tracks the commanded rate rather than the road.

**The honest limit: the calibration actually on the car has two rolling
reversals in the entire corpus.** `coda_20260924_222022` is an hour of driving
after C2 with no direction reversal in it at all. Everything said about C4c here
rests on `coda_20260924_231904_T0/T1`.

### Mechanism — the spec says it outright, and the numbers are now exact

DLCM Functional Requirements V4.2 §10.7, verbatim:

> The DLCM will implement a function to limit the torque request rate of change.
> **The primary purpose for this limiter is to manage driveline lash near zero
> torque and during torque reversals.**

So the V-curve and the speed limb **are** the factory's anti-lash function, and
the campaign raised both, in the region they exist to protect. Per
`artifacts/lash_zone_rate.py`, reading each flashed image:

| image | V-curve idx2..7 | rising rate at TrqLast 0 / 4 / 8 / 12 / 20 Nm |
|---|---|---|
| stock | `[15, 10, 10, 1, 20, 40]` | 10 / 6 / **1** / 7 / 20 |
| FLOOR5 | `[15, 10, 10, 5, 20, 40]` | 10 / 8 / 5 / 10 / 20 |
| FLOOR20 | `[20, 20, 20, 20, 20, 40]` | 20 / 20 / 20 / 20 / 20 |
| FLOOR40 + limb 40 | `[40, 40, 40, 40, 40, 40]` | 40 / 40 / 40 / 40 / 40 |
| C1 + launch rate → C4c | `[40, 40, 40, 100, 100, 100]` | 40 / 70 / 100 / 100 / 100 |

Stock carries a **notch of 1 internal count per tick at exactly 8 Nm** — a
deliberate near-stall placed where the lash is being taken up. Time for the
limiter to climb from 0 on entering a gear at walking pace:

| image | to 4 Nm | to 8 Nm | to 20 Nm | to 63 Nm |
|---|---|---|---|---|
| stock | 0.060 s | 0.200 s | 0.400 s | 0.620 s |
| FLOOR20 | 0.020 | 0.040 | 0.100 | 0.320 |
| FLOOR40 + limb 40 | 0.010 | 0.020 | 0.050 | 0.160 |
| C4c (on the car) | 0.010 | 0.020 | 0.030 | **0.080** |

**Verified on the wire, not only modelled.** Raw `0x212` frames at the C4c
reversal, read straight out of `coda_20260924_231904_T0` (the resampling in the
older extractor had hidden this):

```
-0.12  GEAR N     0 raw
 0.00  GEAR D    19 raw   +19
 0.02            90       +71     TrqLast 47.5 -> V(47.5)=75.6 then 100  => 89 predicted
 0.04           170       +80     2 x 100 per tick                       => 170 predicted
 0.06           253       +83                                            => 251 predicted
```

0 to 63 Nm in **60 ms**, with the limiter model reproducing every step to 1–2 raw
counts. This is the mechanism, no longer a hypothesis: **the factory's anti-lash
rate limit through the 0–20 Nm band has been raised by a factor of 5 to 20, and
the stock 8 Nm notch has been removed entirely.**

The earlier reading — "a knee sitting inside the lash zone, slow to 8 Nm then a
5x step" — was right in shape but wrong in level for the current image. On C4c
the rate at 0 Nm is already 40 and reaches 100 by 8 Nm, so the first 8 Nm take
20 ms, not ~0.5 s. The knee is real but it is crossed almost immediately.

**Secondary hypothesis, unchanged and still unestablished:** C1's preload
reduction (345/449 -> 50 internal) may compound this by no longer holding the
lash closed. The creep-50 cohort shows no elevation of its own, so if it
contributes it does so only in combination.

### The model: what it predicts, and what it does not

Built 2026-09-26 as `artifacts/clunk_model.py`. It splits in two and only one
half works.

**The command half is exact.** Replaying the gradient limiter over a recorded
reversal reproduces the frames above to 1-2 raw counts. Anything this file says
about what a candidate CAL will command rests on that.

**The plant half does not reproduce the clunk, and three attempts are recorded
rather than the one that flattered best:**

| attempt | outcome |
|---|---|
| waveform fit, raw acceleration | collapses -- drives J_m to 13 kg m^2 and the lash to zero, RMS 0.65 m/s2. A reversal happens with the brake ON (interlock, spec s9.3) and friction braking is not in the model |
| waveform fit, 3-15 Hz band | **R^2 = 0.012.** Every parameter walks to a bound so the model predicts nothing |
| magnitude and cohort trend, parameters chosen on pre-campaign events only | tracks the trend, but see below |

The waveform failure is instrumentation, not physics: a ~7 Hz ring sampled at
50 Hz needs the impact instant to a few ms, and that depends on where in the
dead zone the driveline was sitting and on the motor speed at the shift, which
`../low-speed-driveline-signals.md` establishes is unobservable at these speeds.

The third attempt looks good -- predicted step 2.86 / 4.37 / 6.24 / 9.44
against measured 4.0 / 6.0 / 7.0 / 10.0 across the cohorts, with nothing
refitted -- **but it needs 10-16 degrees of lash at the wheel**, five to eight
times a real driveline. At physically plausible lash (1.7 deg at the wheel) it
under-predicts the measured increment by ~2.3x, **and a linear plant does just
as well**: the dead-zone element contributes almost nothing. So the agreement
is not evidence that the lash model is right.

Driving the plant with the MCM's ACTUAL torque (`0x1C0`) rather than the
command closes part of the gap, and why is itself the finding: **the delivered
torque carries 2-4x the per-sample step of the command** (13.5 -> 65 Nm across
the cohorts against 8 -> 23 Nm). `FUN_80075D52` forms the MCM command as
`TrqLast + acceleration-limiter terms (0xD00050F8, 0xD00050FA) + Active Speed
Damper (0xD0006A76, clamped to +/-|TrqLast|)` at `0xD0006A54`, and
`FUN_80070AD4` packs that for M CAN. `0x212` is read from `0xD0006A5A`, which
`FUN_80075CF8` stores **before** any of it. So the bus shows the pre-damper
command, and the damper may be adding to the excitation rather than removing
it. Not testable from this bus.

**What the model is therefore good for: ranking candidates, not predicting a
magnitude.** The one quantity that tracks the measured clunk across nine
cohorts is the commanded torque step through the lash zone, and that is exactly
what the exact half predicts. Empirically, from the nine cohort medians in the
table above:

```
step = 2.93 + 0.0722 * dcmd        r = 0.96, n = 9 cohort medians
```

A nine-point cohort-level regression, not a physical law. Use it to ORDER
candidates; do not quote a predicted count to one decimal place.

### Candidate changes and what each costs

31 post-campaign reversals replayed through each edit (`clunk_model.py` phase
6). "Excess" is predicted clunk above the pre-campaign level; "launch" is the
campaign's own metric, 0 -> 400 raw (100 Nm) at standstill, which flash 4 took
from 0.220 s to 0.080 s and which is therefore the thing being traded.

| candidate | dcmd | excess vs now | launch 0->100 Nm | 0->20 Nm |
|---|---|---|---|---|
| **as flashed (C4c)** | 56 | — | 0.110 s | 0.030 s |
| A  V-curve idx5,6,7 -> 40 | 46 | **-25 %** | 0.190 s | 0.050 s |
| B  speed limb idx0,1 -> 40 | 53 | -8 % | **0.250 s** | 0.050 s |
| C  both -> 40 (revert flash 4) | 44 | -30 % | 0.250 s | 0.050 s |
| G  both -> 60 | 48 | -20 % | 0.180 s | 0.040 s |
| E  both -> 20 (FLOOR20 level) | 22.5 | **-84 %** | **0.500 s** | 0.100 s |
| D / H  V-curve idx5 alone | 56 | **0 %** | 0.130 s | 0.050 s |

Three results here are counter-intuitive and each cost a wrong assumption:

- **The speed limb is the worst trade, not the safest.** It reads like the
  standstill-only table, so it looks like the safe one to touch. It is not: it
  stops binding above ~116 CAN motor rpm and most of a rolling reversal's
  torque rise happens above that, so it costs the launch metric heavily
  (0.110 -> 0.250 s) and buys 8 %.
- **The V-curve idx5 knee -- the lever this file previously proposed -- does
  nothing on its own.** That proposal was written against the pre-flash-4
  numbers. On the current image the rate is already 40 at 0 Nm and 100 by
  8 Nm, so the knee is crossed in 20 ms.
- **The V-curve is the only rate lever that works, and it is inherently
  coupled**, because it is indexed by torque rather than speed. Slowing the
  8-40 Nm band at a reversal necessarily slows at-speed tip-in and the
  one-pedal zero crossing by the same amount. Within the rate tables that
  coupling is unavoidable.

### What would settle it

A drive with the V-curve and speed limb moved back toward their FLOOR20/FLOOR40
values in the 0–20 Nm band only, with C1, C2 and C4c left alone, and ~20
deliberate D<->R reversals at 1–3 mph. Two reasons that is now a sharper test
than it was: the corpus contains **two** usable reversals on the current
calibration, so almost any deliberate set doubles the evidence; and the metric
above is sensitive enough to separate the cohorts, which the old one was not.

---

## 1A. A SECOND clunk source: the creep assist against wrong-way rollback

Found 2026-09-26. **This is not a gear change and it would never have appeared
in a D<->R reversal sweep.** The driver touches nothing.

### The drive

The user reported experiencing it on 2026-09-25 evening and deliberately held
it: on a slope at a stop sign leaving a parking lot, in D, rolling backwards,
pedal released, brake cycled on and off, several seconds at a time. Captures
`coda_20260925_193945_T0/T1`, `_183600_T0..T2`, `_200811_T0`, all on the C4c
calibration. `artifacts/creep_assist_wrongway.py` finds **three sustained
wrong-way episodes**, all in `_193945_T0` at t = 38-41, 51-52 and 56-58 s.

Four predictions were written into that script's docstring **before the log was
read**, from the decompilation and the CAL constants. Two were falsified and
the falsifications produced the better answer, which is the reason for writing
them down first.

### P1 FALSIFIED -- the creep setpoint is a SPEED target, and it is not 64

The prediction used `0xA00215BA` = 64 as the setpoint. That constant applies
only when the latch `a0-0x3EC0` is **set**. With it clear -- which is the
wrong-way case -- `FUN_800763D2` takes the target from LUT `0x80043FD0` in D
(**640**) or `0x80043FC4` in R (**256**), in internal SPEED units, i.e. a creep
speed target of **290 / 116 CAN motor rpm** (about 3.0 / 1.2 mph). The error
term is then an order of magnitude larger than assumed and the P term saturates
its headroom at every speed.

### P2 CONFIRMED, and more strongly than predicted -- the command IS the ceiling

The ceiling does not merely limit below a knee; it binds everywhere. Reading
the table at the magnitude of motor speed, passed through a first-order lag:

| lag tau | cmd / ceiling p50 | p10 | p90 |
|---|---|---|---|
| 0.00 s | 1.03 | 0.71 | 1.96 |
| **0.20 s** | **1.02** | **0.96** | **1.06** |
| 0.50 s | 1.06 | 0.90 | 1.25 |

**Within +/-6 % across all 40 settled samples.** During a wrong-way rollback
with the pedal released, the commanded torque **is** `0x80043FDC` read at the
(0.2 s lagged) rollback speed. That closes the blocker in section 2 and closes
it better than "characterised" -- it is a measured identity, not a table dump.

### P2 CONFIRMED AGAIN, in R, with 19x the samples (2026-09-26)

The 2026-09-26 driveway captures put the car in the wrong-way state in
**R** -- reversing up the slope, stopping, and rolling forward -- which no
capture had before. `artifacts/driveway_reverse.py` phase 3, 757 settled
samples with the pedal below the 2.5 % gate:

| | p10 | p50 | p90 |
|---|---|---|---|
| R, 757 samples | 0.88 | **1.00** | 1.06 |
| D, 40 samples (above) | 0.96 | 1.02 | 1.06 |

So the identity holds in a second gear, on a second slope, with nineteen times
the sample count. Two consequences beyond confirming P2: **the ceiling table
`0x80043FDC` is shared between gears** -- `FUN_80076302` has no gear branch,
and now the data says so too -- and the measurement that bounds the
forward-ceiling fix's failure mode (see the reflash plan §5A) rests on a much
broader base than the original 40 samples.

### P3 FALSIFIED -- the brake switch does not gate the assist

| | n | commanded, assist engaged |
|---|---|---|
| brake OFF | 18 | 58.2 Nm |
| brake ON | 22 | **63.0 Nm** |

Higher with the brake applied, not zero. So `DAT_d0006937` in `FUN_80076302`,
which swaps the ceiling source to the all-zero table `0x80043FE8`, is **not**
the brake switch.

**RESOLVED 2026-09-26 -- it is "moving in the commanded direction", and the
writer has been decompiled.** See item 6 below. The reason the brake looked
irrelevant here is now explicit: both of the branches this byte selects between
are calibrated to zero on this car, so the brake could not have shown up
either way.

### P4 CONFIRMED exactly -- and this is the clunk

Two engagements, both this shape (`coda_20260925_193945_T0`, t = 56.8):

```
 56.809  D   4.75 Nm          rolling back at -83 rpm, pedal 0, brake off
 56.829  D  22.25   +70 raw
 56.849  D  42.25   +80 raw   <-- 100 internal/tick, the flash-4 rate
 56.869  D  60.25   +72 raw
 56.889  D  62.25    +8
```

**4.75 -> 60 Nm in 40 ms with no pedal input and the lash hanging open from
rolling backwards.** `Long_Accel` steps +5 counts through it, above the 4-count
real-signal threshold and comparable to the 7-9 counts a D<->R reversal
produces. The other engagement is identical (+70/+80/+37). Engage delay after
the rollback starts: 0.36, 0.09, 0.40 s.

### The assist's own ramp is a hair above the limiter, and that is the lever

```
setpoint ramp   0xA00215B8 = 13 speed-counts per update
P gain          0xA00215B4 = 1000, applied as err * Kp >> 7  =  x 7.8125
                13 x 7.8125 = 101.6 torque-internal per update
gradient limiter, post-flash-4                = 100 internal per tick
```

**Within 1.6 % of each other.** The assist demands torque at 101.6 and the
limiter passes 100, which is why the engagement rides the limiter at exactly
80 raw/sample -- and why flash 4 made assist engagements 2.5x faster as a side
effect nobody intended.

**HYPOTHESIS, not established.** Lowering `0xA00215B8` from 13 to about 5 makes
the setpoint ramp the binding constraint at ~39 internal/tick. Then the
engagement is 2.5x gentler through the lash; the setpoint still reaches 640 so
B still reaches the same ceiling, i.e. **same final torque and same rollback
resistance, a few hundred ms later**; the accelerator path does not pass
through the creep setpoint ramp, so **launch is untouched**; and the gradient
limiter is untouched, so **at-speed tip-in and the zero crossing are
untouched**. It is the only lever found so far that is decoupled from
everything else -- it trades *time to full creep torque* rather than torque,
rollback or launch.

Falsifiable cheaply: at `0xA00215B8` = 5 the engagement should rise at about
31 raw/sample instead of 80 and reach the same final torque about 0.3 s later.

### Why the delay costs almost nothing

The obvious objection -- that delaying creep torque costs launch, because the
driver's foot is moving from brake to throttle meanwhile -- does not apply, for
a reason stronger than foot timing:

**At a standstill the assist contributes nothing at all.** The ceiling is 0 at
0 rpm, so headroom is 0 and B is 0. The pre-load felt at standstill is `A`, the
accelerator map's creep cell, which is a table lookup with **no ramp** -- it is
there the instant the brake releases and `0xA00215B8` cannot touch it. The
assist only exists once the car is moving.

For the rollback case the delay is real (+90 ms at low rollback speed to
+330 ms at higher) but what is felt is rollback, not torque, and that
integrates out small: missing ~30 Nm for ~250 ms is ~0.39 m/s2 of unopposed
acceleration, giving **about a centimetre** of extra rollback.

### The grade, measured from the driveline

`artifacts/grade_estimate.py`. Deliberately does not use the accelerometer,
whose scale the DBC itself calls +/-12 % uncertain.

Geometry derived rather than assumed: the wheel-speed encoding (2.000 counts
per wheel rpm, 0.0567 km/h per count, anchored to `0x491 Primary_ODO` at
0.1 km/count and verified across three Codas) gives a rolling radius of
**0.3008 m**, and with the 6.576 gear ratio, **21.86 N of wheel force per motor
Nm**.

| method | grade |
|---|---|
| free-roll segments >= 0.3 s (**mass-free**) | 7.6 / 8.2 / 6.9 -> **7.6 %** |
| regression `a = b*T + c`, 360 brake-off samples | **8.2 %** |
| accelerometer, stationary on the brake | 10.1 % |

The free-roll estimate needs no mass: during free roll gravity and rolling
resistance are the whole story and mass divides out, leaving `Crr` (assumed
0.010) as the only real assumption; every 0.005 of it moves the answer
0.5 points.

**The regression validates the geometry chain through something it was not
asked to produce:** its slope gives an effective mass of **1786 kg**, with
nothing anywhere fitted to mass. That is a Coda plus a driver, and it would
have come out wrong had either the radius or the ratio been wrong.

**And it closes the loop on the driver's report.** At 8.2 % and 1786 kg,
holding the car needs **62-65 Nm at the motor**; the assist delivered **63-70 Nm
actual**. Right on the boundary -- which is exactly *"applying forward torque,
but not enough to prevent the car from rolling backward, but enough to be
noticeable."* Three independent things agree: the grade from vehicle dynamics,
the torque from the creep ceiling table, and the driver's description.

One consequence: sitting on the hold boundary makes the assist unusually
sensitive near this grade, so **the rollback cost of lowering `0x80043FDC` is
larger here than the centimetre estimated for the ramp-rate change.** That
reinforces the conclusion above -- the ceiling is the wrong lever for the
clunk, and the setpoint ramp is the right one.

### Why lowering the ceiling does NOT reduce this clunk

Recorded because it is the intuitive move and it does not work. The ceiling
sets where the ramp **stops**; the clunk is set by how fast it **travels**
through the lash, which is the gradient limiter. Dropping the ceiling from
72 Nm to 30 Nm turns the trace above into `4.75 -> 22.25 -> 30` -- **the first
step is unchanged**, so the impact is unchanged and only the sustained torque
afterwards is truncated. The step only shrinks once the ceiling falls below
about **20 Nm** (80 raw) in the 58-232 rpm band, which is not "accept more
rollback", it is "delete the wrong-way assist".

## 2. The creep columns

### What they are

The accelerator map's speed axis has 10 columns. **Only the lowest two command
positive torque at a released pedal** — they are the creep columns:

| col | speed | row 0, stock | row 0, now | role |
|---|---|---|---|---|
| 0 | 0.0 mph | +33.1 Nm | +4.8 Nm | creep |
| 1 | 3.1 mph | +26.5 Nm | +3.8 Nm | creep |
| 2 | 5.0 mph | −11.0 Nm | −22.6 Nm | regen |

Interpolating the coast row on the speed axis, **coast crosses zero at 316 rpm =
3.4 mph**. Below that, lifting off pushes you forward; above it, regen.

Every candidate in the pedal-map redesign skips columns 0 and 1 by rule, because
the design is built around a zero crossing and these columns have none.

### C1's unintended side effect

C1 changed **only row 0** in these columns — 345 -> 50 and 276 -> 40, both a
factor of ~0.145 — and left rows 1–10 at their factory values. Dragging one
endpoint down while leaving the next rung alone steepened the first pedal
segment:

| speed | stock 0->15 % gain | now | |
|---|---|---|---|
| 0.0 mph | 3.68 Nm/% | 5.57 Nm/% | 1.51x steeper |
| 3.1 mph | 2.65 Nm/% | 4.16 Nm/% | 1.57x steeper |

Nobody chose this. It is the same error class as C2's, recorded in
`dlcm-cal-flash-campaign.md`.

### The coast cliff, and the user's follow-on request

Between 3.4 and 12 mph the coast row ramps from 0 to −150 Nm, most of it between
5 and 7.4 mph: **~−44 Nm per mph, against stock's ~−14**. Roughly 3x steeper in
the speed domain, so at walking pace small speed changes swing regen hard with no
pedal input at all.

**Measured on the C4c drive** (in-car session): coast regen is ~0 Nm below
3 mph, -22 Nm at 4.3, -72 at 5.3, -113 at 6.4, and reaches the full -156 only
past 11 mph.

**User request, 2026-09-24, after driving C4c:** extend the strong regen down to
a lower speed. As it stands regen "just falls off to coasting" below ~5 mph,
where the user expects creep to blend in instead. This is the same cliff seen
from the other side — the gap between where regen ends (3.4 mph) and where creep
becomes meaningful is currently filled by neither.

### The blocker — CLEARED 2026-09-26

`0x80043FDC` (`D_CREEP_CEIL`) is the **creep/assist ceiling**, and it is now
characterised both as a table and against the road (§1A):

| CAN motor rpm | 0 | 58 | 116 | 232 | 290 | 349 |
|---|---|---|---|---|---|---|
| ceiling | 0 Nm | 57 | 107 | 208 | 300 | 320 |

Three properties settle what it does and does not do to this region:

1. **It bounds the assist term B only, never the pedal demand A.**
   `FUN_80076302` computes `headroom = ceiling - A` and clamps it at zero, and
   `FUN_80076208` clamps B to that headroom. If A already exceeds the ceiling,
   B is simply zero and A passes through untouched. So it cannot steal
   pedal-commanded torque.
2. **It is zero at zero speed**, so it contributes nothing at standstill. The
   creep felt at rest is the accelerator map's row-0 cell, which is what C1
   changed.
3. **Where it does act, the command equals it to +/-6 %** (§1A, P2), so it is a
   one-to-one lever on torque in the 58-349 rpm band.

So it was never an invisible limiter on the pedal map, which is what this
section feared. It IS the thing that acts between roughly 0.5 and 3.5 mph with
the pedal released -- exactly the band item 2 below wants to rebuild -- and it
is a clean lever there. **Item 1 below is therefore closed and no longer blocks
anything.**

---

## 3. Units note

Nm figures in this file that come from the pedal-map work were computed at
0.096 Nm per internal count, which is **wrong by 4 %** -- the true scale is 0.1.
See `pedal-map-envelope-design.md` section 10. The figures quoted from the
in-car session's C4c drive analysis (the -156 coast floor, the 20 Nm/sample
engagement rate, the 8 Nm knee) are already in correct units. Nothing in the
argument here depends on the 4 %.

## 4. Status

Both parked, to be worked together once the C4c pedal map has been evaluated.
The user has stated these "will all be changed together".

Open, in dependency order:

0. **Design items 2 and 4 as ONE change.** Both levers live in the same low-speed
   corner, and raising low-speed regen necessarily changes what the pedal does
   through the lash zone, so tuning them separately would have each undo the
   other's evidence. The user has said the same. **Item 5 now belongs in the
   same bundle** — the creep ceiling is the torque authority between 0.5 and
   3.5 mph, which is the same band item 2 wants to rebuild, and the two pull in
   opposite directions.
1. ~~Characterise `0x80043FDC`~~ — **DONE 2026-09-26**, see §2 "The blocker" and
   §1A. No longer blocks anything.
2. Extend regen to a lower speed / close the regen-to-creep gap below 5 mph.
3. Rebuild the creep columns' pedal shape, removing C1's 1.5x steepening.
4. ~~Test the launch-rate limb hypothesis for the reversal clunk.~~
   **ESTABLISHED 2026-09-26, see §1.** The gradient limiter is the factory
   anti-lash function by the spec's own words, the campaign raised it 5x to 20x
   through the 0-20 Nm band, and the remeasured clunk metric doubles
   monotonically across the campaign while a calibration-independent
   road-surface control stays flat. What remains open is not whether but how
   much to give back, and against what cost at launch.
5. **NEW: the creep-assist engagement against wrong-way rollback (§1A)** is a
   second clunk source with the same signature and no driver input. Its
   candidate lever, `0xA00215B8` 13 -> ~5, is the only one found that is
   decoupled from launch, at-speed tip-in and the zero crossing. HYPOTHESIS,
   not established; the falsification test is one drive.
6. **CLOSED 2026-09-26 -- `DAT_d0006937` is "moving in the commanded
   direction".** Written by `FUN_800722FE`, reached by tail-jump from
   `FUN_80071608` (itself called from `FUN_8007C33A`); the store is
   `0x80072448  lea a15,[a0]-0x26c9` / `st.b [a15],d15`, invisible to an
   address cross-reference because it is `a0`-relative with
   `a0 = 0xD0009000`. The function maintains three latches and selects between
   two of them:

   | latch | address | rule |
   |---|---|---|
   | gear | `0xD00050AB` | 1 when the gear byte `0xD00050AE` is 40 (**D**); 0 when it is 10 (**R**); held otherwise, so N and P keep the last driving gear |
   | forward | `0xD00050B1` | set when speed > `+100`; cleared once speed < `-100` has accumulated 12 counts; else held |
   | reverse | `0xD00050B2` | set when speed < `-100`; cleared once speed > `+100` has accumulated 12 counts; else held |

   `DAT_d0006937 = gear ? forward : reverse`. Speed is `0xD0005114`, signed,
   positive forward. The four thresholds are CAL `0xA0021344`/`46`/`48`/`4A` =
   `-100` / `+100` / `+100` / `-100` and both debounce counters share
   `0xA0021358` = 12 -- symmetric by construction, so the function is a
   direction-match test and nothing else.

   **It is a latch with a deadband, not a comparator, and that matters at the
   speeds this file is about.** +/-100 internal counts is +/-45.4 CAN motor rpm
   = **+/-0.48 mph**. Coasting to a stop in D the byte stays 1 straight through
   zero speed and only clears once the car is genuinely rolling back past
   0.48 mph for the debounce; conversely, after stopping on a grade the ceiling
   does not switch to `0x80043FDC` until rollback exceeds 0.48 mph. That
   accounts for roughly half of the ~1.16 mph of rollback measured before the
   assist catches.

   Confirmed against all four measured states: non-zero rolling forward in D
   (§1A), zero on rollback in D (§1A, 40 samples), zero rolling forward in R
   down the driveway (§1A re-test, 757 samples), and set while actually
   reversing. The gear-code assignment 40 = D is itself measured, not inferred
   -- see `dlcm-torque-limiter-code-trace.md`, "Map selection, per gear".

## Artifacts

- `artifacts/gear_change_clunk.py` — the current corpus sweep. Wall-clock
  cohorts at flash end, the invalid-burst guard, the 0.6 s window, the
  road-noise control, and per-event traces. Phases: 1 sweep, 2 cohort report,
  3 one event's row, 4 frame-by-frame trace, 5 matched before/after.
- `artifacts/gear_change_events.csv` — 745 reversals, the table in §1
- `artifacts/gear_change_traces.json` — 393 rolling events resampled to the
  50 Hz accelerometer grid over [-0.6, +2.0] s, for the model
- `artifacts/lash_zone_rate.py` — the limiter's rate through the lash zone for
  every flashed image, and the climb times in §1
- `artifacts/active_damper_constants.py` — the Active Speed Damping (§10.5)
  calibration out of each image
- `artifacts/clunk_model.py` — the lash plant and the counterfactual. Phases:
  1 trace inventory, 2 windowed cohort metrics, 3 the post-impulse oscillation,
  4 the waveform fit (a NEGATIVE result, kept), 5 cohort-trend validation,
  6 candidate CAL replay.
- `artifacts/creep_assist_wrongway.py` — the wrong-way assist detector and the
  four pre-registered predictions of §1A
- `artifacts/grade_estimate.py` — grade from the driveline, without the
  accelerometer
- **Superseded:** `artifacts/dr_shift_clunk.py`, `dr_shift_detail.py` and
  `dr_shift_events.csv` produced the withdrawn table in §1. Kept because the
  cohort definitions and the channel argument in their docstrings are still
  correct; **do not re-run them for a clunk number.**
- `../low-speed-driveline-signals.md` — which channels can and cannot resolve this regime
