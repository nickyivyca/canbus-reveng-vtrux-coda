# The accelerator map rebuilt on capability envelopes (C4c)

How the D accelerator map was redesigned 2026-09-24, what the rule is, the four
measurements it rests on, and why four earlier candidates were rejected. The
result was flashed and driven the same day; the user reports it drives well, with
two follow-ons recorded in `low-speed-clunk-and-creep-columns.md`.

> **UNITS: read section 10 before using any Nm figure below.** Everything in
> sections 1–9 was computed with `NM = 0.096` Nm per internal count, which is
> wrong — the true scale is **0.1**. The flashed image is safe and was verified
> against the true envelope, but every Nm number below is ~4 % low and the
> headroom actually flown is H_D 1.135 / H_R 1.354, not 1.09 / 1.30.

Base image `cal_as_flashed_20260924_onepedal1562.bin` (md5 `235df55d…`).
Candidate `cal_candidate_envelope_hr13_nocap_on_onepedal1562.bin`, md5
`2c7a6c6e81fcb16de1719269bf73fede`, 168 byte-pairs / 290 bytes, 13 guards.
Generator `artifacts/pedal_envelope_change_list.py`.

---

## 1. The objective, as the user finally stated it

Two statements, both load-bearing and in tension until the last one resolved them:

- *"the zero point shift slope should roughly allow us to be modulating % of
  available torque in both directions"*
- *"structure the line to make all power usable when it is available, accepting
  possible dead zones at the end of travel, vs always clamping directly to
  expected pack limits"*
- and on the resulting trade: *"I'd rather have dead travel than a region with
  lost performance."*

The third sentence is the tie-breaker and it decided two separate questions.

## 2. The rule

Applies only to speed columns whose row 0 is negative — columns 2..9,
465..8134 rpm. Columns 0 and 1 command positive creep, have no zero crossing, and
are untouched.

```
w(rpm)      = rpm * 2*pi/60
drive_env   = min(287.8 Nm, 100 kW / w)            MOTOR envelope
regen_cap   = min(287.8 Nm, 48.6 kW / w)           PACK charge limit
H_D = 1.09      H_R = 1.30
R = min(|row0| Nm, H_R * regen_cap)    D = H_D * drive_env
row_i = (-R + (R + D) * pedal_x[i] / 10000) / 0.096     for EVERY rung i = 0..10
```

Per-speed result:

| rpm | mph | R cmd | D cmd | crossing |
|---|---|---|---|---|
| 465 | 5.0 | −22.6 | 313.7 | 6.7 % |
| 697 | 7.4 | −127.5 | 313.7 | 28.9 % |
| 1162 | 12.4 | −150.0 | 313.7 | 32.3 % |
| 2905 | 31.0 | −150.0 | 313.7 | 32.3 % |
| 4648 | 49.6 | −129.8 | 223.9 | 36.7 % |
| 5810 | 62.0 | −103.8 | 179.1 | 36.7 % |
| 6972 | 74.4 | −86.5 | 149.3 | 36.7 % |
| 8134 | 86.8 | −74.2 | 128.0 | 36.7 % |

**Below 31 mph the coast row is byte-identical to the previous image.** That is
deliberate: flattening it would have moved the 5 mph crossing from 7.6 % to
34.3 % and landed on the reversal region under separate investigation.

## 3. The four measurements it rests on

1. **`0x312` B4-5 is a MOTOR envelope, not a pack limit.**
   `artifacts/mmax_variation.py`, 1042 captures: flat at 2998 internal
   (287.8 Nm) below 2750 rpm with **zero spread across 1.2 M samples**, then a
   constant-power fall measuring 101.9 kW at 3500 rpm. The user independently
   confirmed 100 kW is a motor limit. B6-7 is the pack charge limit, 44–54 kW
   (`artifacts/mmin_variation.py`).

2. **The map interpolates LINEARLY between rungs**, verified on the car rather
   than from the decompile. `artifacts/map_interp_check.py`: 4322 steady samples,
   residual binned by position *between* rungs is flat — median 0.30–0.47 Nm at
   the midpoint against 0.05–0.43 on a rung. A non-linear interpolation would bow
   at the midpoint and vanish at the rungs. So corners in the map are real and
   drivable.

3. **The DLCM clips its own request to the limits BEFORE publishing `0x212`**, in
   both directions. Drive (`artifacts/where_is_the_clamp.py`):
   `|req − M_MAX|` p50 = 0 against `|req − map|` p50 = 323. Regen
   (`artifacts/regen_clamp_check.py`): `|req − M_MIN|` = 0 at p10/p50/p90, actual
   torque tracking at 0.98 of the limit. **This is what makes over-asking safe by
   construction** rather than by luck.

4. **The envelope has a corner the speed axis straddles.** Torque-limit to
   power-limit transition at 3318 rpm (drive) and 3094 rpm (regen); breakpoints
   sit at 2905 and 4648, so linear interpolation cuts across both and
   under-commands by 19.4 Nm (6.7 %) on drive and 5.4 Nm (3.6 %) on regen.

## 4. Why H is split, and why an asymmetric H is legal

H does two jobs with different right answers, which is why one scalar failed:

- **H_D = 1.09** covers the interpolation corner in §3.4. Moving the 5th speed
  breakpoint was considered and rejected — the y-axis **is** calibratable
  (`0xA00217B0`, CAL space, used by this map alone, not shared) but one knot
  cannot sit at two corners: 3318 fixes drive and worsens regen to 9.1 Nm,
  3094 does the reverse.
- **H_R = 1.30** covers the *pack-limit spread*. At H_R = 1.09 the commanded
  ceiling is 53.0 kW against a limit measured at 44–54 kW, i.e. 1.9 % margin, so
  the calibration would have become the binding constraint and silently stolen
  regen on a generous day. 1.30 gives 63.2 kW, ~16 % above the deepest value
  observed.

**An asymmetric H does not break proportionality.** With
`X = H_R*R / (H_R*R + H_D*D)`, the *live* (unclipped) travel satisfies

```
live_regen / live_drive = (X/H_R) / ((100-X)/H_D) = R / D      exactly
```

verified at H_R = 1.09, 1.30 and 1.60 across all eight columns, 24/24 exact. The
crossing moves; what the driver can actually modulate stays proportional to
available torque. This is the result that made splitting H legal, and it resolved
a tension the in-car session had judged unresolvable.

## 5. No capping, and the cells above 3000

Eight cells exceed 3000 internal — row 9 and row 10 at the four low-speed columns,
290–314 Nm. **The map has never held a value above 3000 before.** They are safe
because of §3.3: the DLCM clips to `M_MAX` (2998) before publishing.

Capping them back to 3000 was built and measured, and it is **not** free:

- capping *everything* reopens a 153.5-internal shortfall at the 3318 rpm corner,
  worth 15.0 Nm (5.2 %) of peak torque at 35.4 mph;
- capping only the seven non-corner cells still costs **4.3 Nm at ~93 % pedal
  around 5–6 mph**, because row 9 then climbs to the ceiling over a longer stretch
  of travel.

The user chose dead travel over lost torque, so nothing is capped. Cost is dead
travel at the top: 1–3 % of pedal in a 33–38 mph band. Context: the car already
carried 10–13 % dead travel at the top above 50 mph, which this design cuts to
5.2 %.

## 6. Low-end clipping is deliberate

| rpm | mph | cmd | pack | over-ask | dead, before → after |
|---|---|---|---|---|---|
| 1162 | 12 | 150.0 | 287.8 | 0.52x | 0.0 % → 0.0 % |
| 2905 | 31 | 150.0 | 159.8 | 0.94x | 0.0 % → 0.0 % |
| 4648 | 50 | 129.8 | 99.8 | **1.30x** | 6.0 % → 8.5 % |
| 8134 | 87 | 74.2 | 57.1 | **1.30x** | 10.0 % → 8.5 % |

Above 31 mph the command sits a consistent 1.30x over the expected limit so the
clamp keeps whatever the pack offers that day. Below it there is nothing to clip.
The dead band is **not a defect — it is the map correctly over-asking, and its
width is a live readout of the pack's current limit.**

## 7. Rejected candidates, and what each got wrong

| | what it did | why rejected |
|---|---|---|
| **C3** | rebuilt only rungs *below* the crossing, kept the factory drive side | equalises the *average* gradient across the crossing while staying pointwise non-proportional; introduced a ~2x slope kink at 697/1162 rpm that the base image does not have, where one-pedal driving lives most |
| **C3d** | same, deliverable on both sides | identical at/below 2905 rpm; does not fix the kink |
| **C4** | symmetric H = 1.09, every rung | H on a *torque-limited* branch pushed commanded regen through the user's deliberate 150 Nm ceiling to 163.5 Nm at 12 mph — a delivered change nobody asked for, since the pack absorbs everything commanded there |
| **C4b** | split H, capping | capping measured to cost torque (§5) |

The C3 failure is the important one and it is structural, not a tuning slip: a
rule that stops at the crossing says nothing about the *local* gradient where the
rebuilt segment meets the untouched factory segment, so the two have no reason to
match slopes.

## 8. Errors made building this

Recorded because each produced plausible wrong numbers rather than obvious
nonsense.

- **Unit mismatch on `0x312`.** Stored as `raw − 2000` while compared against the
  map in internal counts, which differ by 0.4. The normal 2998-internal motor
  ceiling appeared as "1199", which was then explained as a spurious low-limit
  population, and every map-versus-limit gap was inflated 2.5x. It also produced
  the **opposite** answer on where clipping happens. If a limit field ever looks
  violated by actual torque, check units first.
- **Missing torque ceiling in the regen capability term.** Pure constant-power
  extrapolation run below the corner, so the code believed the pack would accept
  666 Nm at 697 rpm and 998 Nm at 465 rpm. Changed no output, because `min()`
  with the coast profile clipped it away, but the design function and the guard
  function disagreed about physics. Caught by the user.
- **A conclusion hardcoded into a print statement.** "capping those 7 cells is
  FREE" was printed unconditionally next to a measurement that contradicted it.
  A printed claim that is not derived from the value just computed is not a check.
- **Mixing pre- and post-flash captures.** The first regen-clamp pass globbed all
  of `coda_2026092*` and found the request pinned at −690 — the *stock* coast
  value — because those cars ran the pre-C2 map. **Any map-versus-bus comparison
  must be restricted to captures running that map.**
- **No steady-state filter.** Without one the sample is dominated by the falling
  rate limiter still ramping after a lift, which reads as "request above the
  limit" for reasons unrelated to clamping.

## 9. Artifacts

`artifacts/pedal_envelope_change_list.py` (generator + 13 guards),
`pedal_envelope_final.txt` (change list and guard output),
`map_interp_check.py`, `where_is_the_clamp.py`, `regen_clamp_check.py`,
`mmax_variation.py`, `mmin_variation.py`, `c3_metric_b.py`,
`pedal_curve_plots.py`, `pedal_headroom_design.py`, `pedal_endpoint_options.py`.
Plots: `pedal_c4c_final.png`, `pedal_c4b_vs_speed.png`, `coast_vs_speed.png`.

---

## 10. UNIT CORRECTION: one internal count is 0.1 Nm, not 0.096

Found by the in-car session on the C4c drive, 2026-09-24, and verified here
independently. **Every Nm figure in sections 1–9 above was computed with
`NM = 0.096` and is therefore ~4 % low.** The image on the car is unaffected and
safe; the generator is not, and must be fixed before the next candidate.

### The arithmetic is decisive

```
internal 2998  ->  published raw = 2998 * 0.4 + 2000 = 3199.2
                ->  decoded      = (3199.2 - 2000) / 4 = 299.80 Nm
                ->  0.10000 Nm per internal count
```

The published-raw formula and the 0.096 constant **contradict each other**, and
the bus sides with the raw formula. Three independent confirmations:

| anchor | value | Nm/count |
|---|---|---|
| M_MAX saturation | 299.75 Nm / 2998 internal | 0.09998 |
| coast floor, 11–14 mph | −156.25 Nm / 1562 internal | 0.10003 |
| rate limiter | 20 Nm per publish / 200 internal per publish | 0.10000 |

`dlcm-torque-limiter-code-trace.md` line 1184 already recorded 0.1 as *"the
assumed internal scale"*; 0.096 came from a `0.240 / 2.5` derivation and has been
wrong since it was written. It propagated into every script of this session.

### Why the car is nonetheless fine — two errors cancelling

The error is **not symmetric between the two branches**:

- **Torque-limited branch round-trips.** `MOTOR_TQ = 287.8` was itself derived as
  `2998 * 0.096`, so dividing back by 0.096 returns exactly 2998. Correct units
  give `299.8 / 0.1 = 2998`. Identical. The coast row likewise round-trips,
  which is why it is byte-identical below 31 mph as designed.
- **Power-limited branch does not.** `kW / w` produces *real* Nm; dividing real
  Nm by 0.096 instead of 0.1 inflates the internal command by 0.1/0.096 = 4.17 %.

Measured on the shipped image:

| | intended | effective |
|---|---|---|
| H_D | 1.09 | **1.135** |
| H_R | 1.30 | **1.354** |
| commanded drive | 109 kW | **113.5 kW** |
| commanded regen | 63.2 kW | **65.8 kW** |

And the envelope corner is really at **3185 rpm / 34.0 mph**, not 3318 — because
the true motor torque ceiling is 299.8 Nm, not 287.8. The 4.17 % inflation
happens to more than cover that shift: checked against the TRUE envelope
`min(299.8 Nm, 100 kW/w)` at full pedal across 800 speed points, **worst
shortfall 0.00 Nm**. The in-car session measured the same thing from the drive
data, worst 0.1 Nm at pedal >= 80 %.

**This is two mistakes cancelling, not a correct design.** They will not cancel
again if H, the envelope, or the coast profile changes. Fix the constant before
the next candidate, and expect the regenerated image to differ from the flashed
one on the power-limited columns.

### What this does and does not invalidate

- **Does not** invalidate the rule, the guards, the shape, or the flashed image.
- **Does not** invalidate anything on the torque-limited branch, including the
  whole coast row below 31 mph and every conclusion about the creep columns.
- **Does** mean every Nm figure above is ~4 % low, and the headroom actually
  flown is 1.135 / 1.354 rather than 1.09 / 1.30.
- **Does** mean the `mmax_variation.py` / `mmin_variation.py` kW figures in
  `esp-torque-intervention.md` Part II section 6 are ~4 % low, so the pack charge limit is
  nearer 46–56 kW than the 44–54 kW quoted, and the motor line nearer 106 kW
  than 101.9. The *shapes* and the motor-vs-pack distinction are unaffected.

### The general lesson

Two independent expressions of the same quantity existed in the codebase —
`raw = internal * 0.4 + 2000` and `Nm = internal * 0.096` — and they disagreed by
4 %. Nothing checked them against each other. A derived constant that can be
cross-checked against an encoding formula **should be**, as a guard, not left as
two separate beliefs.

---

## 11. Prior history: the C2 pedal-shape problem and the C3 fix

Migrated here 2026-10-03 from `regen-limit-chain.md` sections 4 and 4b, which
is where this work was originally written up. It is the history this file's C4c
design was built to answer: C2 created a pedal-shape problem, C3 was the first
attempt at a fix, and **C3 was then rejected** -- see section 7 above for why,
where its failure is recorded as structural rather than a tuning slip.

Section numbering below is the original file's, kept so existing references to
`regen-limit-chain.md` section 4 / 4b still find their text.

## 4. The pedal-shape problem C2 created

User, after the C2 drive: *"it feels like I have not very great resolution on the regen
portion, as if the zero point stays the same but the regen magnitude is much greater so the
torque per pedal travel is much greater on the regen side of the pedal."*

They are right, and the map shows it without touching a log. C2 deepened **pedal row 0 only**;
rows 1500/3000/4000 were untouched. So the whole added regen was loaded onto the first 15 %
of travel.

**It is strongly speed-dependent, and worst where they were driving.** Gradient ratio =
(gradient over pedal 0→1500) ÷ (gradient from 1500 to the zero crossing):

| rpm | 697 | 1162 | 2905 | 4648 | 5810 | 6972 | 8134 |
|---|---|---|---|---|---|---|---|
| before C2 | 0.30 | 0.42 | 0.93 | 0.67 | 0.85 | 1.00 | 1.66 |
| after C2 | 1.41 | 1.55 | 2.95 | 3.41 | 4.53 | 5.79 | **8.36** |

Because row 1 gets shallower with speed (−288 → −115) while coast is now flat at −1562. At
8134 rpm the first 15 % of travel covers ~93 % of the regen range. **C2 turned a near-linear
regen ramp into an up-to-8:1 progressive one.**

### Two structural facts that constrain any fix

**The zero-torque pedal position is set by row 1.** The crossing lives on the row1→row2
segment, so deepening row 1 always pushes it later. It sits at 25 % at cruise *because* row 1
is −288. With row 2 fixed you cannot deepen row 1 and hold the crossing.

**A fixed pedal-% target across all speeds is not achievable at any percentage.** row 1 must
stay *shallower* than coast or the map is non-monotonic in pedal — pressing the accelerator
would make regen deeper. Solving for a fixed crossing violates this at low speed, because
coast is not flat across speed:

| rpm | coast | for 26 % | 27 % | 28 % |
|---|---|---|---|---|
| 464 | −235 | −2214 ✗ | −3220 ✗ | −5233 ✗ |
| 697 | −1328 | −1501 ✗ | −2184 ✗ | −3549 ✗ |
| 1162 | −1562 | −1108 | −1612 ✗ | −2620 ✗ |
| 2905 | −1562 | −396 | −576 | −936 |

(✗ = deeper than coast = pedal works backwards.) **`C_LO` is the wrong constraint to cite
here** — it clamps TrqLast inside the rate limiter, downstream of the map, and M_MIN clamps
shallower than it through most of the range. Monotonicity bites first and by a wide margin.

**The low-speed earlier crossing is factory shaping — do not flatten it.** The zero-torque
pedal position in the *stock* map and the current one are identical at every speed (19.45 %
at 697 rpm, 22.16 % at 1162, 25.00 % at 2905, 24.97 % at 8134); the sole exception is 464 rpm,
which C2 moved itself. It has survived every flash. Holding a constant target across speeds
would delete it, and nobody has asked for that.

### The objective, and how it was arrived at

**Two candidate pedal shapes are live. Neither is chosen.** They are preserved side by side
below at the user's instruction, because the choice is a matter of feel and is theirs.

The framing took three passes to settle, and the dead ends are recorded so they are not
re-derived:

1. *"Shift the crossing later"* — a relayed paraphrase, not the user's intent. Dropped.
2. *"Gain resolution at the low-pedal end"* — closer, but it treats a symptom.
3. *"Roughly linear torque control"* — the user's own words, **but chosen on a false
   premise**: *"I asked for linear because I thought stock was linear."* It was not (§ below).

So linearity is a legitimate target but **a new design, not a restoration** — which is
exactly what makes the second candidate worth keeping.

### The distortion, measured

Splitting the regen span into a low-pedal gradient `g1` (pedal 0→1500) and a near-crossing
gradient `g2` (1500→crossing), at 2905 rpm:

| | row 0 | row 1 | g1 | g2 | ratio |
|---|---|---|---|---|---|
| pre-C2 | −690 | −288 | 0.268 | 0.288 | 0.93 |
| post-C2 | −1562 | −288 | 0.849 | 0.288 | **2.95** |

`g2` is untouched; the whole distortion is `g1`. C2 loaded all the added regen onto the first
15 % of travel, and it worsens with speed as row 1 gets shallower (−288 → −115) against a now
flat coast row — reaching **8.36:1 at 8134 rpm**, where the first 15 % of travel covers ~93 %
of the regen range.

As a single number, distance of row 1 from the linear midpoint averaged over seven speeds:

| | stock / pre-C2 | post-C2 |
|---|---|---|
| mean \|row 1 − midpoint\| | **94 counts** | **428 counts** |

### Was the factory linear? No

| rpm | 697 | 1162 | 2905 | 4648 | 5810 | 6972 | 8134 |
|---|---|---|---|---|---|---|---|
| stock ratio | 0.30 | 0.42 | 0.93 | 0.67 | 0.85 | **1.00** | 1.66 |

Linear at exactly one speed and close at two more. Elsewhere deliberately shaped: **strongly
regressive at low speed** — at 697 rpm `g1` is 0.153 against `g2` 0.517, so the first 15 % of
travel barely changes torque and the gradient steepens toward the crossing — and mildly
**progressive** at the top (1.66 at 8134 rpm).

A coherent design, just not a linear one: delicate control over deep regen when crawling,
coarsening as speed rises and the absolute regen shrinks anyway. **The factory's
speed-varying crossing was therefore not serving linearity**, and that hypothesis is dropped.

---

### Candidate A — linear

`row1 = (coast + row2) / 2`, per speed. Setting `g1 = g2` and solving gives the midpoint
exactly; there is no free parameter, nothing to tune.

| rpm | 464 | 697 | 1162 | 2905 | 4648 | 5810 | 6972 | 8134 |
|---|---|---|---|---|---|---|---|---|
| **row 1** | +285 | −391 | −580 | −709 | −724 | −735 | −740 | −752 |
| gradient | 0.347 | 0.625 | 0.655 | 0.569 | 0.559 | 0.551 | 0.548 | 0.540 |
| crossing | 6.78 % | 21.26 % | 23.85 % | 27.47 % | 27.94 % | 28.33 % | 28.52 % | 28.93 % |

Verified by recomputing `g1`/`g2` from the result: **ratio 1.000 at every speed.** The
crossing moves as a *consequence* — its spread widens from 17.4 points to 22.2 — rather than
being designed. 464 rpm stays positive (+230 → +285), so no cell needs a separate decision.

- **for:** uniform feel, trivially specified, self-documenting.
- **against:** it is not what the car ever did, and the user's reason for asking was
  a mistaken belief about stock.

### Candidate B — shape-preserving

Keep the factory's per-speed ratio `R` at the new depth: `v1 = (C + R·R2) / (1 + R)`.

| rpm | 697 | 1162 | 2905 | 4648 | 5810 | 6972 | 8134 |
|---|---|---|---|---|---|---|---|
| **row 1** | −900 | −983 | −740 | −892 | −804 | −550 | −752 |
| resulting g1 | 0.286 | 0.386 | 0.548 | 0.447 | 0.505 | 0.548 | 0.675 |
| stock g1 | 0.153 | 0.215 | 0.268 | 0.169 | 0.169 | 0.161 | 0.192 |

- **for:** preserves the character the car was sold with and that the user was content with
  before C2; keeps fine deep-regen control at crawl speed, where it matters most.
- **against:** carries forward factory choices nobody has verified were deliberate, and the
  ratio still varies 0.30–1.66 across speed.

The two **agree closely at 2905 and 6972 rpm**, where the factory was already near-linear,
and diverge most at low speed and at the top — exactly where it departed on purpose.

Both are 16 byte-pairs (8 cells × 2 copies), row 1 only, monotonic, and leave row 2 and the
drive side untouched. Neither is built.

---

### What neither candidate fixes

**Absolute sensitivity.** The regen range grew from 403…690 counts to 1562 over the same
pedal travel. Stock `g1` spanned 0.153…0.268; **any** post-C2 design lands near 0.35…0.66, so
the regen side stays roughly **2–3× more sensitive than stock** whatever is chosen. Inherent
in asking for 2.3× the regen across an unchanged pedal, not a defect in either candidate.
Only giving regen more travel — row 2 negative, crossing far later — changes that, at a large
cost to the pedal's character. Restoring stock's 0.276/unit outright would need the crossing
at ~57 % pedal.

**Gradient consistency across speed.** Candidate A is exact *within* each speed but its
gradient still ranges 0.540–0.655 (about ±10 %) *between* speeds, because that is set by
`(R2 − C)/3000` and row 2 still carries the factory's own profile. Flattening it needs row 2
to move. ±10 % is unlikely to be perceptible next to the 3×–8× distortion being removed.

### The pedal map does not set how fast regen arrives — the limiter does

Established 2026-10-03 while pricing zero-point options
(`artifacts/zero_point_shift.py` phase 11), and it is worth having on its own
because it changes how every "the regen side is N× more sensitive" claim above
should be read.

`gradientLimiterNegative_TrqLast` is the live branch on a no-brake lift-off.
Integrating it at 100 Hz from its own table — `y = [-30, -30, -21, -12, -15,
-15, -20, -40, -100, -100]` on `x = [-3000, -80, -70, 0, 70, 80, 300, 600,
800, 3000]` — a **commanded 0 → −156.2 Nm takes 0.55 s**. Against that:

| | time |
|---|---|
| pedal lift across 32.3 % of travel at 123.5 %/s (measured p50, float launches) | 0.26 s |
| pedal lift across 15 % | 0.12 s |
| **limiter descent, 0 → −156.2 Nm** | **0.55 s** |

So the limiter is 2–4× slower than the foot, and it binds in every case. The
map's regen-side gradient sets **where on the pedal** a given regen level
lives, and so how precisely it can be held at steady state; it does **not**
set how quickly regen arrives on a lift-off. A design that doubles the
commanded regen sensitivity therefore doubles the steady-state twitchiness
and changes the transient not at all.

This is why the §10.6 filter's gain axis had to be reshaped in flash 7 rather
than left alone: the filter sits *after* the limiter, so it is the one thing
in the chain that can slow the arrival further.

### Magnitude reference

Internal counts are **0.1 Nm/count** (CORRECTED 2026-09-24 -- this file previously said 0.096, which was wrong and propagated into every script of the pedal-map work; see `pedal-map-envelope-design.md` section 10).

| | off throttle (coast row) | on brake (full-press row) |
|---|---|---|
| **stock** | **−66.2 Nm** (−690), peak at 1162–2905 rpm, fading to −38.7 Nm by 6972 | **−110.4 Nm** (−1150), flat from 1162 rpm up |
| **now (post-C2)** | **−150.0 Nm** (−1562), flat from 1162 rpm up | **−150.0 Nm** — identical, Option A |

Stock gave the brake map **1.67×** the off-throttle regen; that gap is what C2 closed. C2 is
**+2.27×** on off throttle and **+1.36×** on brake. The stock brake figure was real rather
than notional — measured peak braking regen on the car was about −108.6 Nm (−1131 internal),
the map value delivered essentially in full.

The pedal complaint follows directly: the range the accelerator must cover went from 66 Nm to
150 Nm across unchanged travel.

## 4b. C3 — the pedal fix, built 2026-09-24

**Candidate:** `artifacts/cal_candidate_pedallinear_on_onepedal1562.bin`, md5
`b8bfa6edd13943607a8fb8ce9f4a1b50`, **28 byte-pairs**, on
`cal_as_flashed_20260924_onepedal1562.bin`. Generator + log:
`artifacts/pedal_linear_change_list.py` / `.log`. **Not flashed, not authorised.**

**Authored, built and verified by the analysis session alone**, so the two-session
independent-rebuild check does *not* apply to it. The in-car session must re-derive it from
the rule, not from the numbers.

### The rule

Per speed column `j` with `coast[j] < 0`:

```
deliv_regen[j] = min(|coast[j]|, |M_MIN(rpm)|)
deliv_drive[j] = min(row10[j],   M_MAX(rpm))
X[j] = deliv_regen[j] / (deliv_regen[j] + deliv_drive[j]) * 10000    # pedal counts
g[j] = |coast[j]| / X[j]
row_i[j] = coast[j] + g[j] * pedal_x[i]    for every row i with pedal_x[i] < X[j]
```

Coast row untouched; rows at or above the crossing untouched; creep columns untouched;
D accelerator map only, both copies; R maps and brake map untouched.

### The objective, third and final version

**Proportional torque control: the same fraction of *deliverable* torque per unit of pedal
in both directions.** This supersedes both "linear" (§4, chosen on the false premise that
stock was linear) and "shift the crossing later". It is the user's own criterion — *"we
should still have 2x forward torque as regen torque at high speed"* — and it is grounded in
the pack, not in taste.

### The physics, measured

| rpm | M_MIN | M_MAX | fwd:regen |
|---|---|---|---|
| 4000 | −119.0 Nm (49.9 kW) | +240.1 Nm (100.6 kW) | **2.02:1** |
| 6000 | −76.8 Nm (48.3 kW) | +155.7 Nm (97.8 kW) | **2.03:1** |
| 8000 | −58.1 Nm (48.6 kW) | +118.4 Nm (99.1 kW) | **2.04:1** |

The pack's ~100 kW discharge / ~50 kW charge split, holding within 1 % across the range.
**The user predicted this ratio from the pack spec before it was measured.**

### Result

| rpm | crossing was → now | g1/g2 was → now |
|---|---|---|
| 464 | 7.58 % → 7.58 % (**no cells change**) | — |
| 697 | 19.45 % → 30.32 % | 1.41 → 0.98 |
| 1162 | 22.16 % → 32.01 % | 1.55 → 0.88 |
| 2905 | 25.00 % → 33.74 % | 2.95 → 0.94 |
| 4648 | 25.46 % → 33.64 % | 3.41 → 0.98 |
| 5810 | 25.38 % → 33.39 % | 4.53 → 1.01 |
| 6972 | 24.98 % → 33.48 % | 5.79 → 1.03 |
| 8134 | 24.97 % → 33.75 % | 8.36 → 1.05 |

Peak forward torque unchanged at every speed. Pedal cost is uniform: the torque 30 % gives
today needs ~35.5–36.2 % above 697 rpm and exactly 30.0 % at 464 rpm. Nine guards pass
(L1==L2 monitor, coast untouched, only cells below their own crossing changed, every changed
cell below its crossing, creep columns untouched, monotonic in pedal at every speed, R maps
untouched, brake map untouched, peak forward torque unchanged).

### How proportional was the factory? Closer than expected

Stock crossing minus the deliverable-ratio prediction, in points of pedal travel:

| rpm | 464 | 1162 | 2905 | 5810 | 8134 |
|---|---|---|---|---|---|
| stock | +1.3 | +3.5 | +5.8 | +3.6 | **+0.02** |
| post-C2 | +0.3 | −12.1 | −10.0 | −7.8 | −7.9 |

The factory sat a few points *later* than proportional mid-range and converged to
**essentially exact at the top**, i.e. it was roughly tracking the pack's limit ratio, most
precisely where it matters. **C2 broke that by 8–12 points** — it added regen without moving
the crossing, so the pedal crosses zero far too early for the torque it spreads. That is a
better justification for C3 than "linearity" ever was.

### Two errors made getting here, both worth keeping

1. **A flat ratio where it should have been per-speed.** The first build took one 34.24 %
   crossing from the coast plateau. Available drive torque falls with speed, so the ratio is
   per-speed. Caught by the model sweep, which showed linearity getting **7× worse** at
   464 rpm — a cell-level inspection would not have found it.
2. **Commanded torque where it should have been deliverable.** The second build used
   `|coast| = 1562` as the regen side. Above ~3000 rpm the map asks for far more regen than
   the pack accepts — at 8134 rpm coast commands −1562 but M_MIN allows only **−595** — so
   pedal travel was being allocated to regen that can never be delivered. It produced a
   bogus 51 % crossing against a true 32.9 %, and a false alarm that row 4 would go negative
   at 8134 rpm (it does not; it stays +391). **The user caught this, not the model.**

The general lesson: *commanded* and *deliverable* are different quantities above ~3000 rpm,
and any pedal-shape reasoning that treats the map's own numbers as available torque will be
wrong at speed in exactly this way.
