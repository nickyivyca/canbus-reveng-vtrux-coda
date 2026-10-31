# Coda Indirect TPMS — Algorithm and Storage Spec

What the Coda Android app computes, and what it writes to disk. This is the
source of truth for the detector and the data format.

**Not here:** why any of it works. Method, validation and the psi calibration
are in `indirect-tpms-feasibility.md`; this file states decisions and does not
re-argue them. App-side implementation — Kotlin structure, UI, modules,
lifecycle, the CAN transmit path — is in
`../../../android-app/android-coda-tpms-implementation.md`. The TPMS and GPS
code lives in its own `:tpms` Gradle module, depended on only by `:coda`; that
move does not change the file format described here.

**Ownership, agreed 2026-09-21.** Split by file, not by section: SeaDrive
syncs whole files, so two machines editing different sections of one file
still collide. This file is written only from the analysis side; the app file
only from the app side. Changes to either go by message to its owner. The
executable version of everything below is
`artifacts/tpms_app_prototype.py`, which replays it against the real corpus —
prefer diffing behaviour against that over reading prose.

---

## 1. What it measures

Wheel speeds give three orthogonal contrasts over the four per-wheel
fractional speed deviations:

```
2*ln(DEL) = +LF -RF -LR +RR      DEL = (LF+RR)/(RF+LR)
2*ln(F/R) = +LF +RF -LR -RR      F/R = (LF+RF)/(LR+RR)
2*ln(L/R) = +LF -RF +LR -RR      L/R = (LF+LR)/(RF+RR)
```

The fourth contrast is the common mode and **ratios cannot see it at all**.
Setting it to zero inverts to one deviation per corner.

**The scale factor, which decides what the displayed number means.** Three
contrasts cannot reconstruct four wheels, so one wheel moving by *d* appears
as *+3d/4* on that corner and *−d/4* spread over the other three — "LF down
1.0" and "LF down 0.75, the rest up 0.25" are the same measurement to any
ratio method. Two honest readings follow, differing by 4/3:

| reading | meaning |
|---|---|
| projected | the raw contrast estimate; never overstates, reads 25 % low when one tyre really is the only one moving |
| **outlier** | the same data assuming the other three are at baseline. This is what "that tyre is N psi low" means, so **thresholds use it** |

**A free self-check: the four corner deviations always sum to zero.** Every
column of the inversion matrix sums to zero, so this holds exactly, for any
input, while `commonModePsi` is null — it is the arithmetic statement of the
fact that ratios cannot see the common mode. Any implementation can assert it
on every verdict for the cost of one addition, and a failure means the
inversion or its sign convention has been broken. (The app's first end-to-end
run on real rows read LF +4.0, RF −3.2, LR +0.5, RR −1.3, which sums to zero
and is therefore at least self-consistent.)

It also says something the UI should not hide: if one corner reads low,
*something else must read high*, whether or not it has gained any pressure.
A positive number on this panel is not good news, it is the complement of the
negative one.

Sensitivity is **2.28e-4 fractional per psi** per corner (twice the 0.000114
of §5 of the feasibility doc, because a single wheel moves `DEL` by half of
its own change). Measured per-corner drive-to-drive noise, using the real
covariance between contrasts rather than assuming independence
(`artifacts/tpms_corner_inversion.py`):

| corner | 1σ | 3σ |
|---|---|---|
| LF | 0.67 psi | 2.00 psi |
| RF | 0.71 psi | 2.12 psi |
| LR | 0.59 psi | 1.78 psi |
| RR | 0.60 psi | 1.79 psi |

So naming the corner costs nothing against the 2.71 psi `DEL` figure.

### Inputs and filters

| ID | Signals |
|----|---------|
| `0x200` | `WheelSpeed_LF`, `WheelSpeed_RF` — **`SubFrameID`(B0) `== 0` only, a VALIDITY gate** |
| `0x208` | `WheelSpeed_LR`, `WheelSpeed_RR`, `BrakePressure` |
| `0x080` | `SteeringAngle` |
| `0x1C0` | `Torque` |

**Encoding, as of the 2026-09-25 DBC change.** The four ESC wheel-speed
signals are **14-bit**, narrowed from 16 on firmware evidence: the DLCM masks
each MSB with `0x3F`, bits 7-6 are `0b11` in every frame observed, and the
firmware's own invalid-value comparison is `0x3FFF` — the 14-bit all-ones,
which only makes sense for a 14-bit field. `BrakePressure` became 12-bit at
start 19, with a new `BrakePressure_Valid` at 20.

There are now two conventions, and a statement must say which it means:

| | |
|---|---|
| **decoded** via the DBC | already the count above `0xC000`. **Do not subtract.** |
| **raw** 16-bit word | subtract `0xC000`, or mask `& 0x3FFF`. Unchanged. |

**The wire is unchanged.** The top two bits are still `0b11`, so `0xC000` is
still physically present in the frame. Notes describing the *wire* remain
correct; only statements about the decoded signal moved. 0.0567 km/h per
count either way.

Code implementing the old wording literally — decode, then subtract `0xC000`
— lands 49,152 low, about −2,800 km/h, and fails loudly. The dangerous
version is the reverse: reading raw and *not* subtracting gives a large
positive number that still looks like a speed.

Keep a sample only while: **> 25
km/h**, **|steering| < 2° from the session's steering centre (below)**,
**steering rate < 5°/s**, **speed steady within 2 % over 1 s**, **brakes
off**, and **|torque| below the contrast's own cap (below)**.

### The torque cap is per contrast, because the bias is

The single 20 Nm cap was discarding the car's normal operating points. On
`coda_20260926_155726`, straight and off the brakes:

| operating point | available | at 20 Nm / 1 % | at 40 Nm / 2 % |
|---|---|---|---|
| ~40 mph | 30.3 s | **1.9 s** (6 %) | 17.1 s |
| ~60-65 mph | 21.7 s | 7.6 s (35 %) | **21.7 s** (100 %) |
| total > 25 km/h | | 11.1 s | 56.1 s |

**The cap sat below the torque needed to hold speed.** Median |torque| while
straight, steady and above 60 km/h is **27.5 Nm**; only 31 % of good cruising
samples passed a 20 Nm gate. The filter was not rejecting slip-contaminated
data, it was rejecting the act of maintaining speed — and this car has no
cruise control, so the driver cannot avoid it.

**Why the cap can differ per contrast.** Drive torque is shared by the two
*front* wheels. It therefore cancels in any contrast that puts one front wheel
against the other, and does not cancel in the one that puts both fronts on the
same side. Measured across 0→40 Nm at fixed steadiness:

| | shift over 0→40 Nm | fronts arranged |
|---|---|---|
| `DEL` = (LF+RR)/(RF+LR) | +0.00016 | opposed — cancels |
| `L/R` = (LF+LR)/(RF+RR) | +0.00020 | opposed — cancels |
| **`F/R`** = (LF+RF)/(LR+RR) | **+0.00155** | **together — does not cancel** |

Ten to one, in the direction theory predicts.

**The 40 Nm relaxation was wrong and is withdrawn.** *Owner-approved
2026-09-26: "yes do it, don't want false positives".* Re-swept on one corpus
changing one thing at a time:

| rule set | drives | sens/psi | DEL 3σ | 6 psi false alarms |
|---|---|---|---|---|
| 20 Nm, 1 %, all-sample centre (build 23) | 122 | 0.000111 | 2.74 psi | **0.00 %** |
| **20 Nm, 2 %, fast centre — `proc` 3** | **172** | **0.000113** | **2.85** | **0.00 %** |
| 40 Nm, 1 %, fast centre | 154 | 0.000088 | 3.06 | 0.00 % |
| 40 Nm, 2 %, fast centre — `proc` 2, shipped in v24 | 188 | 0.000092 | 3.13 | **1.03 %** |

Relaxing steadiness from 1 % to 2 % is free and gains 50 drives. The torque
relaxation is the damage: **−21 % sensitivity**, and the fast path goes from no
observed false alarm to one per ~97 drives — which invalidates the measurement
the 6 psi threshold was chosen from. So:

| contrast | cap |
|---|---|
| every contrast | **20 Nm** |

**But the mechanism is not what the table above implies, and the difference
matters for anyone tuning this later.** *Measured 2026-09-26,
`artifacts/tpms_torque_slip_character.py`, on a 300 s mixed drive and a 1971 s
mountain descent, binning samples by their own instantaneous torque:*

- **`F/R` behaves exactly as the theory says** — smooth, monotonic, and
  consistent between the two drives: +0.0003, +0.0005, +0.0009, +0.0010 across
  the bands up to 100 Nm, then +0.0040 above it.
- **`DEL` is nearly immune**: +0.0001 falling to −0.00005 across 0→100 Nm,
  essentially flat. Which is what "shared by both front wheels, so it cancels
  in the diagonal" predicts.
- **`L/R` is not consistent between drives at all**: +0.0024 at 30–40 Nm on one
  and +0.00004 on the other; −0.0075 against −0.0008 above 100 Nm. So its
  apparent torque sensitivity is **drive-specific — cornering correlated with
  throttle, not a torque law.** The +0.00020 in the table above was a
  single-drive artifact and should not be read as a coefficient.

**So the 20 Nm cap does not help `DEL` by removing drive-torque creep from
`DEL`; there is almost none to remove.** It works as a proxy for *the car being
driven hard* — acceleration, load transfer, cornering. The corpus result is
solid and the causal story for `DEL` specifically is not, and those are
different claims. A future attempt to replace the cap with something more
targeted should target that, not wheel slip.

`LR/RR` is a rear pair on an undriven axle and could take any cap; it shares
the same one so that it stays sample-for-sample comparable with `DEL`.

**The masks are nested**, the 20 Nm set being a subset of the 40 Nm set, so
this is one pass with two counters rather than two passes.

**`n` at the top of the row gates the FLOORS; each contrast is weighted by
its OWN `n`.** The wide count decides whether a drive is usable at all — the
sample floor and the fast-path floor — because `DEL` is the channel that
decides a verdict. But pooling, both segment-to-session and across drives,
weights each contrast by the count that actually produced it. Weighting `F/R`
by the wide count would over-weight a segment that happened to yield little
`F/R` data, and a segment with no `F/R` at all has no mean to weight.

A ratio carrying no `n` of its own falls back to the row's `n`, so rows
written before v24 pool exactly as they did.

**A drive that clears the floor can still be unusable, and the test is a
minimum rather than a presence check.** All three contrasts are needed to form
four corners, and `F/R` runs the stricter cap, so it can be short when `DEL`
is not. A bare `n > 0` test is not enough, and the arithmetic says why: one
`F/R` sample has sd 0.0029, so an `F/R` mean from five samples has a standard
error of 0.0013 — which through the inversion is **2.9 psi on a corner, past
the 2.5 psi advisory on noise alone**. At 300 samples it is 0.38 psi.

So every contrast carries a floor of its own, `min_n_contrast`, default
**300**. `DEL` and `L/R` clear it whenever the drive clears 800; `F/R` is the
one it bites. Below it the drive is skipped for scoring rather than attributed
from noise — and skipping is safe because "no recent qualifying drive" is
already handled by ageing the estimate and greying the numbers, not by a
state of its own. Every
ratio additionally carries **its own `n`**, including the ones that equal the
top-level value. That redundancy is deliberate: `steer_n` was misread as
per-segment when it is cumulative, in this very investigation, and a count
that must be inferred from which cap applies is the same trap.

**The residual +0.00016 on `DEL` is not zero**, about 1.5 psi across the full
torque range, and it is tolerated only because the baseline is learned under
the same cap and absorbs it. What it cannot absorb is *drive-to-drive*
variation in the torque distribution, which is why the row records the
distribution — see `torque_abs_mean` in section 4.

**Steadiness goes 1 % → 2 %**, same definition (spread of the mean-of-four over
the trailing 1 s), tolerance only. This part is free: `DEL` reads 0.99922
under either.

> **These thresholds invalidate the published constants until re-derived.**
> The sensitivity, the DEL residual sd, the 3σ and the leak rate were all
> measured under 20 Nm / 1 % when this was written. **Republished 2026-09-27
> under `proc` 3 with D CAN pinned: 0.000114/psi, residual sd 0.00010, 3σ
> 2.71 psi, leak 0.051 psi/day** — see the table below and §1.
> They are not wrong, they are *measured under a different filter*, and the
> corpus must be re-swept before they are quoted against post-v24 rows.

### The steering centre is estimated from fast samples only

The sensor's zero moves between power cycles — 19592 during one session on
2026-09-26 and about 20000 an hour earlier the same afternoon — so the centre
must be estimated per session and cannot come from the DBC offset.

**That is now a characterised property of the signal, not an inference from two
sessions.** `0x080` is a *relative* angle, re-zeroed to raw 20000 whenever the
EPS powers up, and **only about 12 % of drives have their straight-ahead within
2° of 20000** — so a consumer that needs straight-ahead has to estimate it per
power cycle. Owner-approved 2026-09-27 and recorded in
`driver-inputs.md`, *Relative angle, zeroed at EPS power-up*, and in the DBC's
`CM_ SG_ 128 SteeringAngle`; swept over 869 captures and 20.46 M frames by the
`Coda steering angle` session (`artifacts/steering_0x080/`). Two results there
were load-bearing for this spec, and both came back the way the design needed:

| question | answer |
|---|---|
| does the zero ever move **while driving**? | **No.** All 12 EPS restarts in the corpus resume with the counter at 1 and raw exactly 20000, and the car was **stationary in all 12**. Between counter-contiguous frames the largest step is 146 counts and only below ~11 km/h; above 30 km/h (7.9 M frames) at most 77, above 60 km/h (3.7 M frames) at most 22. **Limit:** a *software* re-zero smaller than about 5° without an EPS restart cannot be excluded by those tests. |
| is there an **absolute** source that could replace the estimator? | **No.** Every id on every captured bus, in every layout the scan-completeness rule requires, by level and by 1 s deltas: nothing but `0x080` moves with the wheel (positive control, its own B CAN copy, r = 1.000). The factory ICD names the signal *Relative Steering angle*; ABS DTC C123F shows the ESC learns its own offset **internally**, so it exists but is not broadcast. Whether UDS exposes it is untested. |

**What this settles for the detector.** The straightness gate cannot be
silently invalidated mid-session: there is no mechanism that moves the zero
while the car is moving, and the one that does move it — an EPS power-up — is
observable in `0x080` itself. So a per-session centre is sound for the span it
covers, and the only exposure left is a session that **spans** a power cycle,
which is the key-cycle case below.

**The sub-5° edge case is NOT handled, and that is a decision rather than an
omission.** *Owner's, 2026-09-27.* A software re-zero smaller than about 5°
with no EPS restart is the one thing the corpus tests cannot exclude — but
**no such event has ever been observed**, which is the reason it is accepted:
the limit describes what the data cannot rule out, not something seen. Not an
open question, and not to be reopened as one without an observation behind it.
The remaining `0x080` unknowns — scale unmeasured, B5 bit 4's meaning, whether
UDS exposes the ESC's learned offset — are characterisation and do not gate
TPMS. The
estimator was the median over **all** of a session's samples, and that is
wrong for any session that is not mostly highway.

**How it failed.** Recovering `coda_20260924_004341_T0` from the head unit on
2026-09-26 turned a 450-byte stub into 31.4 MB of real data, and the session
went from 617 qualifying samples to **zero**. The recovered chunk is low-speed
manoeuvring with the wheel turned, its own median 22040, while the highway
chunk sits at 19985 near true centre. Pooling them moved the session median
**+357 counts = +35.7°**, so the ±2° mask landed 35.7° away from straight
ahead. More data produced fewer samples, which a stable estimator cannot do.

The all-samples median assumes most of a session is spent going straight.
That holds on a highway session and fails on a mixed one, where "straight
ahead" ends up defined by whatever angle the wheel spent most of its time at.

**Two failure modes, and only one is visible.** A *large* shift rejects
everything: `n` collapses, the drive is lost, and it is obvious. A *small*
shift of a few degrees is the dangerous one — the mask still admits plenty of
samples, but every one is taken at a constant mild steering angle, and a
constant turn produces a real left/right wheel-speed difference, which is
precisely the L/R contrast the detector reads. `n` looks healthy and the
measurement is biased.

**The estimator.** The median of the steering angle over the samples of the
session so far whose speed is **> 60 km/h**. At highway speed the car is
almost always going straight, so that subset estimates the zero well.

Pinned down, because the app and the corpus pipeline must agree exactly:

| | |
|---|---|
| grid | the centre is **estimated** on the wheel-sample grid (`0x200` timestamps), with steering interpolated onto it, because the speed gate needs a speed per sample and speed lives on that grid |
| mask | the ±2° mask runs on the steering **frames**, centred and scaled and *then* interpolated — **not** interpolated and then centred. Equal in exact arithmetic, not in floating point: the wrong order cost one sample in 32,520 against the app. |
| fallback | when the fast population is too small, the centre is the median over the steering **frames' own values**, not over the interpolated copy. Resampling changes the population, which is the same trap as estimating it on the wrong grid. |
| speed | the **same `kmh` the extractor already computes**: the four-wheel mean count divided by `COUNTS_PER_KMH`. Not a second definition. |
| test | `kmh > 60.0`, strictly greater, matching the `kmh > MIN_KMH` convention |
| minimum | **200** qualifying samples, about 2 s at 100 Hz, before the fast centre is trusted |

**Validated as a strict improvement, not a trade.** On three sessions it
fixes the broken case and leaves the good ones alone: `20260924_004341` goes
0 → 615 samples, `20260926_155726` moves 944 → 974 with DEL changing by
1e–05 against a drive-to-drive noise of 3e–05, and `20260723_130702` is
bit-identical. Independently, on a clean highway session the *modal* steering
angle above 80 km/h equals the all-samples median to the count — so where the
old estimator was already right, the new one agrees.

**The fallback, which is the app's real exposure.** The app centres on the
session *so far*, so a town-first segment is scored before any highway
samples exist. When fewer than 200 fast samples are available, fall back to
the all-samples median and **record which was used**. Two reasons that beats
withholding the row: a row that had to be re-scored later would need a
replacement mechanism; and the fallback rows are exactly reproducible offline
from the logs, which are kept.

*Updated 2026-09-26: the fragment store of §4 does now give one — dedupe by
`log` resolves duplicates by `proc`, then `seq` — so the first reason is
weaker than when it was written. The second still stands on its own, and
tagging remains the thing that makes the fallback acceptable.*

This deliberately reproduces the old behaviour for those rows. That is
acceptable **only because they are tagged** — an untagged fallback would put
known-suspect rows and sound ones in the same pool with nothing to separate
them.

| field | meaning |
|---|---|
| `steer_centre` | the centre used, in raw counts |
| `steer_centre_src` | `"fast"`, `"all"`, or `null` when the segment carried no steering at all |
| `steer_n` | **unchanged**: cumulative steering frames in the session so far |
| `steer_n_fast` | new: how many of those were above 60 km/h. **Cumulative in the session, like `steer_n`** — the two are only comparable if they count over the same span. |
| `torque_abs_mean`, `torque_abs_sd` | mean and sd of \|torque\| over the **wide** qualifying samples — the same samples `DEL` is computed from, so it is a covariate of `DEL` and not merely a description of the drive. Signal taken as decoded, absolute value, no other treatment. |
| `band_kmh` | band width for `ratio_bands`, 10 km/h. Carried at top level rather than read from `gps.band_kmh`, which is null on any catch-up row. |
| `ratio_bands` | per-speed-band sufficient statistics — see below |

### `ratio_bands` — collect banded now, bin later

The tyre grows with speed roughly as v², so a drive's pooled ratio depends on
its speed mix. Measured on one drive under the old filters: `DEL` read
**0.99939** at 40 mph and **0.99917** on the freeway — 0.00022 apart, about 7σ,
**2 psi of apparent front differential arising purely from route mix**. The
new thresholds shrink it to 0.00004 by admitting far more of each band, but
they do not remove the mechanism.

The durable fix is to compare a band against the same band. That is not a v24
detector change — the detector stays **pooled** — it is a collection change, so
that binning becomes possible later without re-reading logs:

```
band_kmh 10
ratio_bands { "90": { "DEL":  {n, sum, sumsq},
                      "FR":   {n, sum, sumsq},   <- its own n: stricter cap
                      "LR_":  {n, sum, sumsq},
                      "LFRF": {n, sum, sumsq},
                      "LRRR": {n, sum, sumsq} } }
```

Keyed on the band's lower edge in km/h, as a string, the same convention and
the same width as `gps.bands`, so the two join. `n`, `sum` and `sumsq` are
sufficient for a mean and an sd per band, and they add over drives — which is
what lets a baseline be rebuilt per band from stored rows alone.

Speed is the same `kmh` every other filter uses. Bands with `n = 0` are
omitted rather than stored as zeros.

This is the same "collect more than is needed now, narrow later" posture as
the GPS block, and it costs about 1-2 kB per row against the ~500 B the row
was.

`steer_n` keeps its existing meaning. Redefining a shipped field in place
would make old and new rows silently incomparable, which is the same class of
error as the `0xC000` convention change above — and there, at least, the wrong
reading failed loudly.

### Bus identity comes from anchors, and the ratios are pinned to D CAN

**Every id the detector reads — `0x200`, `0x208`, `0x080`, `0x1C0` — is
gateway-rebroadcast onto B CAN**, so a two-dongle capture holds two copies of
each. The channels really are two buses: they share 21 ids and each carries ids
the other never does.

**The bus is identified by ids that are never rebroadcast**, and the ratios are
taken from **D CAN only**:

```
D_CAN_ANCHORS = (0x308, 0x312, 0x325, 0x330, 0x580)
MIN_ANCHORS   = 2      # two distinct ids, so one stray frame cannot decide
```

**Three tests, and each exists for a case that has been seen:**

1. the winner needs `MIN_ANCHORS` **distinct** anchor ids, so one frame cannot
   decide a bus;
2. a rival needs `MIN_ANCHORS` distinct ids **too** before it counts as
   ambiguity — presence alone is the wrong test, see below;
3. the winner must carry **all four signal ids**, so a channel that looks like
   D CAN but is missing what we came for is refused rather than yielding an
   empty row.

A capture that fails any of them is **rejected, with the reason printed**. "No
rows" and "rows I could not trust" look identical from outside, so a rejection
that does not say why is the silent failure this rule exists to remove.

> **Presence is the wrong ambiguity test, because stray frames are real.**
> `coda_20260425_225558_T0` contains exactly one `0x4` and one `0xC`, at the same
> 0.1 ms stamp, and nothing else below `0x19` in the whole capture — bus noise or
> a bit error, not a message. Had one of those strays carried an anchor id, a
> presence test would have rejected an entire good capture. That is a loss in the
> safe direction and still a loss, and at corpus scale it would be invisible.
> Requiring two distinct ids on the rival keeps the guard while ignoring noise.

**C CAN is the case this guards against in future.** *Owner, 2026-09-27: no
in-car capture has C CAN linked today, but it should be guarded against.* C CAN
carries a **different message** under `0x200` and another under `0x300`, so frame
counting could select it and decode garbage shaped like wheel speeds. None of the
five anchors is known to appear on C CAN, so C is simply never selected; and if
one ever did appear there in quantity, test 2 refuses the capture and names the
ambiguity rather than choosing.

> **`0x300` is deliberately not an anchor**, although it is D-only in every
> capture examined, because the DBC records a different C CAN message sharing
> that id. **An anchor must be unique across every bus that could ever be
> logged, not merely across the two that are logged today.** That is the
> difference between a set that happens to work and one that will keep working.

Rejecting is right *for this car specifically*. The Coda's logger does not
suffer the mid-session channel dropouts the Vtrux bench does, so there is no
need to stay robust to a channel vanishing while the app runs.

#### `dominant_bus` is withdrawn, on both sides

It kept, per id, the channel with the most frames. That reads as content-based
selection and is not: since every id it was applied to is rebroadcast, both
channels carry it in near-equal numbers and the winner is decided by margins of
**one frame or an outright tie** — broken by whichever channel appeared first.
Measured over 12 captures it kept B CAN 7 times and D CAN 5, on margins like:

```
2973 vs 2973     30002 vs 30001     2275 vs 2276
 106 vs  105     29656 vs 29655     29796 vs 29894
```

So the corpus was a **mixture of native and rebroadcast measurements, chosen per
capture by a coin flip, with no record of which.** It did no numerical harm —
forcing each bus in turn moves the contrasts by 0.03–0.05 psi against a 0.9 psi
noise floor — but "no harm measured" is not "correct", and one hazard is
specific and live: **a different message shares id `0x200` on C CAN.** Frame
counting would happily select it. Anchors cannot.

> **The app's live path had the same idea in a worse form, and it must go too.**
> `GpsRateAccumulator.onDominantBus()` incremented a per-bus counter and then
> asked whether the arriving frame's bus was *currently* ahead. With two
> near-equal copies the lead changes hands constantly. Simulated on one real
> 5-minute segment:
>
> ```
> 0x200  60006 frames  accepted 35737 (59.6%)  selection flipped 11468 times
> 0x208  60008 frames  accepted 37068 (61.8%)  selection flipped 14128 times
> final counts per bus: {1: 30003, 2: 30003}   -- an exact tie
> ```
>
> It never selected a bus at all; it read an interleaved mixture and did about
> 20 % redundant work. **It must be replaced by the same anchor rule**, applied
> live — the anchor ids stream continuously, so identification costs a few
> hundred milliseconds at session start and nothing after.
>
> **It did NOT corrupt the GPS block, and an earlier claim here that it inflated
> `N` by ~20 % was wrong.** `Band.n` increments **once per paired GPS fix**, not
> per wheel frame (`GpsRateAccumulator.kt`, the `b.n++` beside `b.sx += x`), so
> duplicated wheel samples cannot inflate it. They enter only the ±0.5 s window
> mean that produces `x`, and since both copies carry the same value the mean is
> unchanged. The correction matters because the retracted version would have
> put an unwarranted asterisk on the one channel that cannot be re-derived.

### `SubFrameID == 0` is a validity gate, not a sample-count filter

This was nearly mis-specified. `reverse-it-e1` established from DLCM firmware
that the DLCM does **not** gate `0x200` on `SubFrameID` — it reads the
wheel-speed fields from every frame — which reads as an argument for dropping
the filter and gaining samples. It is not, for a reason the firmware does not
show and the data does:

**A non-zero `SubFrameID` on the ESC bus means the ESC is in a fault state,
and in a fault state not all four wheel speeds are available.** The parts car
emits `0x14` (`ABSFault_0x14`) for all 24,294 of its `0x200` frames — and on
that same car `WheelSpeed_RR` is stuck at all-ones in 12,534 of 12,539
`0x208` frames (DTC C102B), while LR reads normally. So the fault flag is
not bureaucratic: one wheel is genuinely dead behind it.

`DEL` needs all four wheels. Computing it across a stuck channel produces a
confident number from a dead sensor, which is the worst available outcome.
So the gate stays, and it stays *because* of what it excludes rather than in
spite of what it costs.

What it costs, measured content-separated across the whole corpus
(`artifacts/tpms_subframe_check.py`):

| population | frames | `SubFrameID != 0` |
|---|---|---|
| ESC bus, this car | 44,516,953 | **0.052 %** (`0x1C`, `0x1E`, `0x20`) |
| ESC bus, parts car | 25,078 | 96.9 % (`0x14`) |
| the *other* `0x200`, on C CAN | 160,452 | — not ESC frames at all |

### Void the drive, not the sample, when the ESC sensors are faulty

**Owner's rule, 2026-09-26: all TPMS data from a drive whose ESC sensors are
problematic is void.** Not "drop the affected samples" — void the drive. A
wheel sensor that is failing intermittently produces frames that pass every
per-sample check and are still wrong, so rejecting only the frames that
announce themselves keeps exactly the data the announcement was warning about.

**"Problematic" has to be defined narrowly, or the rule voids everything.**

| value | verdict | why |
|---|---|---|
| `SubFrameID 0x14` (`ABSFault`) | **fault → void the drive** | the parts car: all 24,294 frames, with `WheelSpeed_RR` dead behind it |
| any wheel word `== 0x3FFF` | **fault → void the drive** | the ESC's own invalid sentinel; the firmware compares against it |
| `SubFrameID 0x1C`, `0x1E`, `0x20` | **normal — do not void** | see below |

`0x1C`, `0x1E` and `0x20` are an **ESC initialisation sequence**, and it is
worth being precise about why, because two wrong descriptions of it have been
in circulation.

`0x1E` and `0x1C` form a fixed, contiguous pair: **192 frames of `0x1E`
(1.91 s) immediately followed by 200 frames of `0x1C` (1.99 s)**, zero breaks,
once per capture. `0x20` is a separate 150-frame (1.49 s) block that can
appear more than once.

They are **not at the start of the capture** — median 73 s in, p90 215 s, only
0.7 % inside the first 5 seconds. That is what made them look periodic. They
are not periodic either: checked within a file, all 200 `0x1C` frames are one
unbroken 2-second run, not 200 frames scattered at 15-second intervals.

What they line up with is a **vehicle power-state transition** — specifically a
**key cycle partway through the capture**. In both captures checked, the block
begins ~0.7 s *before* `0x240` B0 cycles `0x01 → 0x15 → 0x11 → 0x01`.

> *Corrected 2026-09-27, by `reverse-it-e1`, and verified here.* This said the
> block was the ESC powering up with the car, "typically well after logging
> begins, since the logger starts at screen-on". **Both halves were wrong.** The
> logger is woken by the IGN signal, not independently of it, so it does not
> start before the car; and in both cited captures `0x240` B0 already reads
> `0x01` (Ready) at t = 0.02, so the car was fully powered at the first frame.
> There was no pre-power-up window to explain. The ESC is **restarting**, not
> starting.
>
> **`0x370` B0[3:0] is how to tell**, and it is the tool this section lacked. It
> is a GWM-transmitted vehicle power state, and because the GWM stays powered
> through a key-off it can report the off period from outside it, which `0x240`
> cannot:
>
> `0 = Off · 1 = Shutdown · 2 = Accessory · 3 = KeyOffTransition · 4 = IgnitionOn · 9 = Crank · 6 = PostCrank · 5 = Ready`
>
> *Corrected 2026-09-29 to match `VAL_ 880 VehiclePowerState`, which the owner
> approved that day. This line previously read `1 = Off` with no entry for 0 at
> all — so it named the wrong state as rest and had no name for the real one.*
> **The full descent is `5 → 3 → 1 → 0`, and `0` is the resting off state**;
> `1` is shutting down, with a median dwell of about 5.2 s on B CAN, and a quick
> restart interrupts it. Anything keying on `== 1` to mean "off" is wrong, and
> wrong in the direction that matters: it would call a car mid-shutdown parked.
>
> Mask with `0x0F`; the high nibble is a constant `0x1`. Verified here on
> `coda_20260322_153141_T0` — `5 → 3 → 1 → 2 → 4 → 9 → 6 → 5`, a 9.8 s key-off
> at t = 62 s, with the `0x1C` block at t = 72 s — and on
> `coda_20260322_160846_T0`, which cycles and then keys off again at the end.
>
> That ladder stops at `1` and never reaches `0`, which under the corrected
> labels means the descent was interrupted by the restart rather than completing
> — consistent with a 9.8 s key-off. **A restart resumes from wherever the
> descent reached**, so both `1 → 2` and `0 → 2` are real ascents and neither
> identifies the resting state. The relabel rests on the descent timing, not on
> where an ascent begins.
>
> **A ladder that stops at `1` is only evidence of that if the descent was
> INTERRUPTED rather than TRUNCATED, and the two look identical.** `VAL_ 880`'s
> comment records both causes: on D CAN the GWM stops rebroadcasting `0x370`
> about 6.2 s into an off period, so the descent is cut off and state `1` merely
> stops being *visible* — the state continued, the record ended. **The
> discriminator is that a truncation ENDS THE MESSAGE while an interruption is
> FOLLOWED BY `2`.** Here state `1` begins at 67.1 s and `2` follows at 70.0 s,
> with `0x370` still transmitting 1.9 s after the ascent completes, so this is a
> genuine interruption; the `1` dwell of 2.9 s is well short of the ~5.2 s median,
> as a restart cutting it off predicts. Checked independently by the
> `CAN messages inventory` session, 2026-09-29
> (`artifacts/powerstate_ladder_check.py`).
>
> *Worth noting how this nearly went wrong on our side, twice.* The 6.2 s D CAN
> hold-off is recorded in this very section, and the ladder was first offered as
> evidence without citing why truncation did not apply to it. **The reason then
> given — that `dominant()` takes `0x370` from the copy that keeps transmitting
> — was itself wrong for this capture, and is withdrawn.**
> `coda_20260322_153141_T0` is SINGLE-CHANNEL: 318,640 frames and all 15,000
> `0x370` frames on one channel, so "take the bus with the most frames" selected
> the only bus present and protected nothing. *Caught by `CAN messages
> inventory`, 2026-09-29, after I had claimed the guard as the reason.*
>
> **The ladder's admissibility rests only on the truncation-versus-interruption
> test, which is bus-independent** — a `2` follows, and `0x370` is still
> transmitting afterwards. That holds whichever copy the channel is, which is why
> the conclusion survives a bus check that comes back UNRESOLVED (`b=3, d=7`). It
> is the weaker claim: not *protected from truncation by construction*, but
> *shown not to have been truncated, after the fact, by what followed*. Only the
> second is supported, and unlike the first it does not depend on trusting any
> selection logic.
>
> **A selection among one candidate cannot fail, and that is the same hazard in a
> third form.** Frame-count selection across two rebroadcast copies turns on
> margins of one frame; a two-set score where both sets contain rebroadcast ids
> matches on both sides; and a single-channel capture returns its only channel
> while establishing nothing about which copy it is. All three emit a confident
> bus label carrying no evidence.
>
> **"Modules appear late" has at least two causes and they must be separated.**
> `reverse-it-e1`'s sweep of 1,085 captures found 93 multi-module dropout events
> in 76 captures, of which only **23 are real key cycles**, 1 is a DLCM reflash,
> and **66 are the logger or dongle losing the bus**. A real key-off always shows
> the `0x370` descent *before* the GWM itself goes quiet; the same state either
> side of a silence means the capture lost the bus and the key never moved. Full
> method in `key-cycle-detection.md`.

**A capture can span a power cycle, and IT DOES BITE.** `steer_centre` is a
per-session estimate precisely because the sensor's zero moves between power
cycles — so a session *containing* a cycle gets one centre estimate for two
different zeros.

> *Corrected within hours of being written, 2026-09-27.* This first said "it
> does not bite", on two captures showing +1.5° and 0°. `reverse-it-e1` pointed
> out their sweep had already located every key cycle in the corpus, which made
> the real measurement cheap. Over the **6 captures where the car keys off and
> back on mid-file** (`artifacts/tpms_keycycle_steering_centre.py`):
>
> | capture | off | shift |
> |---|---|---|
> | `coda_20260322_153141_T0` | 9.8 s | +1.50° |
> | `coda_20260322_160846_T0` | 8.7 s | +0.00° |
> | `coda_20260425_222956_T1` | 6.5 s | +0.00° |
> | `coda_20260425_225558_T0` | 61.1 s | **−2.10°** |
> | `coda_20260426_151050_T11` | 144.9 s | −0.40° |
> | `coda_20260701_121829_T3` | 7.2 s | **+6.90°** |
>
> Median \|shift\| 0.95°, max **6.90°** — and **2 of 6 reach or exceed the ±2°
> mask**, the worst at 3.5× it after only 7.2 s off. The duration of the off
> period does not predict the shift: the largest came from the second-shortest
> cycle.
>
> **Two files were not a small sample, they were an unrepresentative one**, and
> the conclusion drawn from them was the opposite of the truth. The check that
> found nothing was recorded honestly as "not a guarantee" and that hedge did
> not help: the number was still used as though the effect were absent.

**What it costs, and why nothing is being changed for it yet.** The exposure is
narrow: only 6 captures in the corpus key off and back on mid-file, against ~350
sessions, so of order **1 % of sessions** can be affected at all, and only those
whose zero actually moved. The failure in those is the silent kind — the mask
still admits samples and they sit at a constant mild steering angle, which is a
real left/right wheel-speed difference and exactly the `L/R` contrast the
detector reads.

Three ways to close it, none yet chosen, **owner's call**:

1. **Split the centre per power cycle.** Correct, and needs the app to see a
   power transition. `0x370` B0[3:0] is now a DBC signal, so this is available
   rather than hypothetical — and there is now a **cheaper marker inside `0x080`
   itself**: a silence > 0.3 s followed by the counter in {1, 2} **and** raw ==
   20000 (`driver-inputs.md`, *Relative angle, zeroed at EPS power-up*). It
   needs no second id. **The counter alone is not enough** — logger frame drops
   across the counter wrap mimic it, which is why the raw == 20000 conjunct is
   load-bearing rather than belt-and-braces.
2. **Void a session whose zero moved** by more than some fraction of the mask.
   Cheap, and throws away a whole drive to fix a half of it.
3. **Accept it and record it.** What is in force today.

**A wider exposure is not yet measured.** Rows are pooled per session and a
session is several segments, so a key cycle falling *between* segments spans the
session just as one inside a segment does. The 6 above are only the within-file
cases, which are the ones a single file can settle. The corpus has 19 captures
containing a key cycle; 13 of them end during the off period, and whether their
session resumes in a later segment has not been checked.
`../dlcm/artifacts/keycycle_corpus_sweep.py` groups by
`detect_capture_sessions()` and is the way in if it is wanted.

> **The script that produced the table above did not split by bus, and the fix
> changed nothing — which is a fact about `0x080`, not a reason it was
> acceptable.** *Found by `reverse-it-e1`, 2026-09-27.* It merged every channel
> for both `0x080` and `0x370`, which is the error `AGENTS.md` states outright:
> *"Not splitting at all is the same error"* as trusting a channel number. The
> steering figures survive because the two `0x080` copies' medians agree to
> **0.0 counts** in every two-bus capture here; the only visible effect was
> `n_pre` halving.
>
> The `0x370` merge did do damage. **The GWM stops rebroadcasting `0x370` onto
> D CAN about 6.2 s into an off period while still transmitting it on B CAN** —
> a fixed hold-off, 6.1–6.2 s across four captures — so the two copies of a
> descent differ and a merged view is their union. That union manufactured
> zero-duration `4 → 0 → 4 → 0` flickers which were reported as real
> transitions and are absent on the dominant bus.
>
> Off durations in the table came from the merged view, and the two
> single-channel captures were a worry: if that channel were D CAN their true
> off periods would be longer than shown. **Resolved 2026-09-27 — they are
> B CAN**, so 9.8 s and 8.7 s are the true off periods and there is no
> truncation bias in the table. That came out of `reverse-it-e1` re-deriving bus
> identity against a set of **D-CAN-exclusive** ids (`0x308`, `0x312`, `0x325`,
> `0x330`, `0x580`) after finding their previous anchor set was entirely
> rebroadcast and so could not tell the buses apart at all.

*Nothing in the detector depends on why `0x1C`/`0x1E` occur: they are not
sub-frame 0 and the validity gate excludes them either way. The correction
matters for the explanation, not the behaviour.*

> *Corrected 2026-09-26.* This section previously read "ordinary periodic
> sub-frames … roughly one every 15 s". That was wrong: the ~200-per-file
> count was right, the distribution was not. It came from pooling timestamps
> across 240 files and reading the spread as periodicity, without once
> checking contiguity *within* a file — where the answer is obvious in a
> single line of output. A per-file structure question cannot be answered by
> a cross-file histogram.

**The operational conclusion is unchanged**: they never void a drive, and the
per-sample `SubFrameID == 0` gate excludes them anyway. A stationary power
transition would also fail the >25 km/h filter.

So a rule that voided a drive on *any* non-zero `SubFrameID` would void
essentially every drive in the corpus. The distinction that matters is
**fault** versus **not `0` **, and those are not the same set.

The per-sample `SubFrameID == 0` gate stays as well: it is what keeps
`DEL` from being computed across a frame layout we have not verified. Voiding
the drive is the additional consequence when the non-zero value is a *fault*
value.

**Add a second, independent guard: reject any wheel word reading `0x3FFF`.**
The fault flag and the stuck channel are separate signals and either can in
principle appear without the other. The test costs one comparison. On this
car it has never fired — 0 all-ones wheel words in 5.4 million frames — which
is the point: it is insurance, not a filter.

> **An implementation must never read "no `SubFrameID == 0` frames" as "no
> wheel-speed data".** It means the ESC is in a fault state. The two are
> indistinguishable to a decoder that simply finds nothing, and on the parts
> car that is exactly what happens.

Two filter facts, measured (`artifacts/tpms_filter_sensitivity.py`):

- **The steering mask width is not critical between 0.5° and 3°.**
  Drive-to-drive sd is flat across that range and degrades beyond it, while
  tighter masks discard drives — at 0.5° only 11 of 38 drives clear the
  sample floor, at 2° 26 do. Do not tighten it.
- **800 samples is 8 seconds** at the 100 Hz valid rate, and it is enough.
  Cutting the same drive down, the sd of its own mean is 0.00005 at 800
  against a 0.00010 between-drive floor — so averaging noise is already below
  the irreducible per-drive bias and adds ~14 % in quadrature. 1600 samples
  recovers ~5 % of that. Below 800 it degrades fast (+31 % at 400).

---

## 2. Baseline

**Learned from the first K qualifying drives after a calibration, then frozen
for the life of that file.** Not a rolling window, and it must never become
one: the leak is continuous at 0.051 psi/day, so a baseline that re-learns
from recent drives tracks the leak and reports nothing wrong for ever. The
2026-07-01 fill is visible across six months precisely because nothing
re-baselined over it.

K is a *setting*, not a stored value — see §4.

**Do not freeze while any pooled contrast is short.** The learning pool must
clear `min_n_contrast` on *all three* contrasts, not just the drive count and
the pooled sample total. Since the per-contrast torque cap arrived, a set of
learning drives can be rich in `DEL` and thin in `F/R`.

Freezing anyway is worse than waiting, and specifically worse than an ordinary
bad reading: the baseline is **written once and never re-learned**, so a
partial one is not degraded, it is permanently wrong, and every later verdict
is measured against it. In the prototype it also surfaces at the wrong place
entirely — the NaN propagates to the first *scored* drive and trips the
zero-sum assertion there, drives away from the cause.

So learning simply continues until the pool is complete. That has a
consequence worth designing for rather than discovering: **a car driven only
in town could stay in LEARNING indefinitely**, because `F/R` needs the 20 Nm
cap and town driving rarely offers it. LEARNING that never ends and does not
say why is indistinguishable from a broken app. The panel should therefore be
able to report learning *progress per contrast* — drives so far, and each
contrast's pooled `n` against its floor — not merely the state name.

**Enforce this structurally, not in a comment.** The prototype holds the
baseline in a write-once object that raises on a second assignment. A rule
carried in prose did not prevent either session from writing code that could
break it (see the `amend()` note in §5), and a silently re-learned baseline
produces plausible output for ever rather than failing.

---

## 3. Verdict

Worst corner decides, on the **outlier** reading, with hysteresis and
confirmation over consecutive qualifying drives.

| state | meaning |
|---|---|
| LEARNING | baseline not yet frozen |
| OK | no corner beyond the advisory threshold |
| ADVISE | a corner at or beyond −2.5 psi |
| WARN | a corner at or beyond −4.0 psi |
| **STALE** | **a fill was detected that the owner did not announce. The baseline is dead and every corner number is meaningless until recalibration.** |

STALE is not a worse pressure reading, it is an invalid-data statement.
Render it off the OK/ADVISE/WARN ladder and suppress the four numbers rather
than showing precise meaningless ones — a hotter colour would file it under
"tyre problem" and point the owner at the wrong action.

"No qualifying drive recently" is **not** a state. Derive it from the
estimate's age and grey the numbers; keeping it as a sixth state would put a
benign condition on the same axis as an actionable one.

### Two paths: a fast one for punctures, a slow one for leaks

Owner's requirement, 2026-09-26: *"if I hit a nail and my tire is starting to
go flat, I want to know on the first drive after that, not the second drive."*

| | fast path | slow path |
|---|---|---|
| evidence | **this drive alone** | rolling window of M drives |
| confirmation | none | `confirm_drives` consecutive |
| threshold | **−6.0 psi** | −4.0 WARN, −2.5 ADVISE |
| sample floor | 800 within the session | 800 per drive |
| evaluated | at every segment close, on samples pooled so far | at drive close |
| catches | a puncture, on the drive it happens | a gradual leak |

**The fast-path threshold is 6 psi, and it was measured rather than chosen.**
Single-drive worst-corner deviations, taken against each changepoint
segment's own mean so that real drift cannot masquerade as noise
(`artifacts/tpms_fastpath_falsealarm.py`, 127 qualifying drives):

| threshold | false alarms | one per |
|---|---|---|
| 4.0 psi | 1.57 % | 64 drives |
| 5.0 psi | 0.79 % | 127 drives |
| **6.0 psi** | **none observed** | — |

At 4 psi that is a nuisance warning every couple of months of daily driving,
which would teach the owner to ignore it — and an ignored warning is worse
than none, because the slow path's 4 psi WARN is the one that matters for a
real leak.

**The Gaussian estimate would have got this badly wrong.** The measured sd is
0.75 psi, which puts 4 psi at 5.3σ and predicts a false-alarm rate near zero.
The observed rate is 1.57 %. The tail is far heavier than normal, so a
threshold argued from σ rather than from the empirical distribution would
have shipped a nuisance alarm.

Raising the *sample* floor does not substitute for raising the threshold: the
4 psi rate is 2.56 % at a 300-sample floor, 1.57 % at 800 and 2.17 % at 1600.
It is between-drive bias, not averaging noise, so more samples per drive do
not remove it.

> **6 psi sits one drive past the observed extreme** (worst single drive:
> −5.63 psi) in a 127-drive sample, so "none observed" bounds the rate at
> roughly 2 % rather than proving it is zero. It should be revisited once
> there is more data — which is the owner's stated order of work: collect
> first, tune at ingest afterwards, since no threshold is stored in the file.

A puncture is in any case far larger than 6 psi, so the fast path is not
being asked to be sensitive. It is being asked not to cry wolf.

### The verdict window excludes the learning drives

The rolling window is the last M **post-baseline** qualifying drives, in file
order. Two things about that, both of which were arrived at by accident and
are kept on purpose:

- **File order, not timestamp order.** Spec §4 states that nothing in the
  detector is time-based, and selecting the window with `ts <= current.ts`
  quietly made it so: with a clock behind — the case §4 exists to handle — a
  row whose timestamp precedes an earlier row's would drop out of *its own*
  window.
- **Post-baseline only.** The learning drives must not appear in the window
  they are being compared against. Including them compares the baseline with
  a window that partly *is* the baseline, pulling the first M−1 estimates
  toward zero — that is, toward "nothing is wrong", which is the wrong
  direction to be wrong in.

Measured on the corpus at default settings, the first post-freeze estimate
reads **−0.14 psi** with the learning drives included and **−0.28 psi**
without. The two converge by the fifth estimate, once the window no longer
overlaps the learn phase, and no event or date changes either way. It is a
small effect that only ever appears immediately after a calibration —
which is exactly when an owner who has just set his pressures is most likely
to be watching.

**The fast path requires `min_n_contrast` on each contrast of the solo drive**,
not merely that the contrasts exist. It needs this more than the slow path
does, because it is a single-drive verdict with no confirmation and no window
to average over.

The 6 psi threshold was chosen from a measured false-alarm rate across 127
drives — but that measurement was taken when every drive's `F/R` rested on the
full sample set, before the cap became per contrast. It therefore says nothing
about a drive whose `F/R` is starved. An `F/R` mean from five samples carries
2.9 psi of corner noise, half the trigger, from nothing at all.

### Un-announced fill detection

**Run it on `DEL`, never on the worst corner.** The worst corner can change
identity across the very event being detected — it was LF before the
2026-07-01 fill and RF after — so a two-window comparison of "the worst
corner" silently subtracts two different quantities and misses the step. A
scalar cannot do that.

On detection the app goes STALE and stops naming corners. Without this it
keeps reporting against a dead reference and invents a fault on a different
corner three weeks later.

### Corpus replay

Against the real six months, with a synthetic calibration at the start:

```
20260327  baseline  frozen on 3 drives, 4198 samples
20260501  advise    LF at -3.1 psi
20260613  warn      LF at -4.4 psi
20260702  stale     pressures rose +3.7 psi with no calibration entered
```

The warning precedes the owner's actual inflation of that tyre by 18 days.
A 10-drive rolling window smooths the fill below the step threshold and
misses it; 3–5 catches it.

---

### Published constants — `proc` 3, D CAN pinned, 2026-09-27

| quantity | value |
|---|---|
| `DEL` per psi of front differential | **0.000114** |
| per-corner fractional sensitivity | **2.28e-4** (twice the above) |
| residual sd between drives | **0.00010** |
| **3σ detection, one drive** | **2.71 psi** |
| 2σ detection | 1.80 psi |
| per-corner 3σ | LF **2.12**, RF **1.89**, LR **1.64**, RR **1.99** psi |
| leak rate | **0.051 psi/day** |
| fast path, single drive, observed | **6 psi 0.00 %**, 5 psi 1.40 %, 4 psi 2.10 % |
| `DEL` changepoints | 3 (against `LF/RF` 5, `LR/RR` 2) |
| corpus | **169** usable sessions; **147** at n ≥ 800, 2026-02-17 .. 09-26 |

These **supersede** the legacy figures (0.000110, 2.75 psi, per-corner LF 2.00 /
RF 2.12 / LR 1.78 / RR 1.79). Both changes that moved them were corrections, not
preferences: the torque cap returned to 20 Nm everywhere, and the bus is pinned
by anchors instead of chosen by frame count.

**D pinning cost 19 % of the drives and improved every number** — the dropped
drives are the early single-dongle era with no D CAN at all, and removing the
native/rebroadcast mixture tightened the scatter more than the smaller corpus
loosened it. Largest single gain: `LR` 3σ from 1.83 to 1.63 psi.

> **The 6 psi fast path survives the republication at 0.00 % observed**, so the
> threshold chosen under the legacy rule set does not need revisiting. Note the
> scale trap that nearly put 3.50 % here instead: the false-alarm script's
> constant is the **per-corner** sensitivity, twice the `DEL`-per-psi figure.
> Feeding it 1.14e-4 instead of 2.28e-4 halves the scale, doubles every psi and
> inflates the rate. Its own comment warns that the wrong constant "rescales
> every psi figure by 20 %"; being out by 2× rescales it far more.

---

## 4. The file

**The store is a folder of immutable fragments**, `CodaLogs/tpms/` — a
subfolder of the served log directory. Every file in it is written once,
complete, and never modified again. Each calibration starts a new epoch; the
active epoch is the newest `calibration` record, not the newest file.

### Why immutable — the transport uploads once and never looks again

*Rewritten 2026-09-26. This section previously specified one append-only JSON
Lines file per epoch. That design is sound on a filesystem and is destroyed by
the transport, which is the part it did not model.*

SeaDrive on the head unit is a **one-way, upload-only** sync: it uploads a
file when it first sees it and ignores every later modification. An
append-only file is therefore frozen server-side at whatever it held the
instant the sync first noticed it — for ever, with no error anywhere.

Measured three independent ways on 2026-09-26:

- the first real calibration file reached the library at 127 bytes, frozen
  mid-append, while the head unit's copy went on growing;
- 347 of 353 corpus sessions are missing their BUSMASTER close footer;
- **32 chunks are cut mid-line while later chunks of the same session
  exist** — which a crashed writer cannot produce. Only a copy taken
  mid-append and never refreshed can.

The third is the decisive one, and it is the shape the rest of this project
keeps meeting: the first two are equally consistent with a writer that dies,
so they cannot distinguish the two causes. Only the existence of *successor*
chunks does.

**Immutability inverts the problem.** If a file is complete the moment it
appears and is never touched again, then "upload once and ignore
modifications" is not a bug to work around — it is exactly correct
behaviour. Nothing needs to be re-uploaded because nothing ever changes.

> **The stopgap does not work, and it is worth recording why.** Stopping the
> sync except while backing up assumes there is a quiet window. There is
> none: the store is written continuously for as long as the logger runs.

### A fragment

Names are `tpms_<epoch>_<seq>.jsonl`, `seq` zero-padded and monotonic within
the epoch:

```
tpms_20260926T154945_000000_full.jsonl
tpms_20260926T154945_000001.jsonl
tpms_20260926T154945_000002.jsonl
```

**The name is an ordering and grouping hint only. Every identity decision
comes from content.** That is what makes a manual re-upload arriving as
`tpms_20260926T154945 (1).jsonl` a non-event rather than a second epoch.

Each fragment contains, in order:

1. the epoch's `calibration` record — **repeated in every fragment**;
2. every `calibration_amend` and `epoch_void` for that epoch (few, ~100 B);
3. what is new since the last fragment — a completed drive row, or the open
   segment's `partial` row.

So **every fragment is a self-contained mini-epoch**: it leads with its
calibration, so any one of them dropped into an empty folder is a working
store. That is the property that makes role-by-first-record work and makes the
folder hand-placeable.

**There is no completed-row tail. R = 0.** *Set 2026-09-26; it was 8.* The tail
existed to repair a fragment the transport never picked up, and the reasoning
that justified it was wrong in a way worth recording:

> **The per-minute partials already overlap each other.** The GPS block is
> cumulative over a segment, so the partial at minute 4 contains everything the
> partial at minute 3 held. Repair inside a segment is therefore free and
> automatic. A tail of completed rows could only protect *earlier* segments —
> whose content is regenerable from the logs except for GPS, and whose GPS was
> already carried by that segment's last partial, short by at most one minute.

So `R = 8` bought at most 60 s of one earlier segment's GPS. Measured against
the live records rather than estimated, it cost **40–50 kB per fragment**,
because a real drive row is 5–6.4 kB and not the 500 B this spec claimed for
months. The per-field measurement:

| row | `gps` | `ratios` | `temps` | rest |
|---|---|---|---|---|
| 1028 B | 660 | — | 305 | 63 |
| 2442 B | 1838 | 329 | 305 | −30 |
| 5229 B | 2819 | 379 | 305 | 1726 |
| 6411 B | 4017 | 383 | 305 | 1706 |

**GPS is 63–79 % of a drive row.** The 500 B figure was a pre-GPS estimate
carried forward without remeasuring after the GPS block landed.

**A `partial` row carries GPS only:** `log`, `ts`, `gps`, `n: 0`,
`ratios: null`, `partial: true`. It is **not** a re-scored drive. Computing
ratios for it would mean re-parsing the still-open log every minute — up to
37 MB, seconds of head-unit CPU — to recover something invariant 3 says is
regenerable anyway. What is *not* regenerable is the GPS block, so that is what
a partial carries. *Agreed with the app side 2026-09-26.*

**Consolidation.** A fragment holds the *entire* epoch, named
`…_<seq>_full.jsonl`, when any of these is true:

- an epoch operation happens (`set`, `amend`, `undo`);
- the epoch has no `_full` at all — which is what gives a freshly installed
  build a consolidated file, and bounds the startup read after any install;
- **256 completed rows** have accumulated since the last one.

*Changed 2026-09-26 from "every 32 fragments", which was O(n²): a fragment
count is not a measure of how much there is to consolidate, and against a
linearly growing epoch it repeated the whole history ~800 times a year — order
of 1–2 GB. Counting completed rows scales with the thing being copied. At the
corpus's 4.8 segments/day it gives ~7 consolidations a year ramping to ~2.8 MB,
about 11 MB/year.*

There is therefore always one file that **is** the epoch — the file a migration
produces and the file to hand-place when rebuilding the folder. The reader
treats it identically to any other fragment; the suffix is for humans.

**Size, with R = 0.** Estimated from the live records as 0.7 → 4 kB for a
partial fragment and up to 6.5 kB for a close, giving about 14 kB per
five-minute driving segment against 6.4 kB today — 2.2×, for a per-minute
off-car copy of the one unregenerable channel. Roughly 61 MB/year of fragments
plus 11 MB/year of consolidations at an hour of driving a day.

*Measured on the emulator 2026-09-26, replaying `coda_20260618_195906`:
**0.75–1.3 kB per partial fragment and 3 kB per close** — below the estimate,
because a GPS block's size is dominated by how many speed bands it has touched
and that drive is short on bands. So the figures above are an upper bound for
short drives and the year-scale numbers should be read as conservative. The
band count, not the duration, is what sets a partial's size.*

### The write protocol

Build in memory, write `<name>.jsonl.tmp`, `fsync`, `rename`. The sync never
observes a partial file, so the mid-append truncation class is designed out
rather than tolerated. A power cut or force-stop leaves a `.tmp`, which the
reader's `*.jsonl` glob does not match.

`seq` is taken from the directory listing at startup (max + 1) and probed for
non-existence before each write. **The directory is the state** — there is no
counter file that a power cut can desynchronise from what is actually there.

**Cadence: one fragment per minute while a segment is open, plus one at every
event** — segment close, `set`, `amend`, `undo`. The timer is unconditional,
matching the CAN logger's own continuous-write discipline.

*A conditional was considered and rejected: checkpointing only when the GPS
block had gained fixes would skip parked segments, where the checkpoint is
worthless anyway. It is a filter whose failure mode is suppressing a write,
silently, in the losing direction — the failure this project collects
instances of.*

**No fragment is written on app stop, and that is a decision, not an
omission.** The owner established how the sync behaves: *"seafile seems to scan
all files when it opens and uploads any it hasn't already uploaded"*
(2026-09-26). A complete fragment on disk is therefore picked up whenever the
sync next runs, so the last per-minute fragment already covers the shutdown.
This is also the direct confirmation that the store's central premise holds:
new files upload, modified ones do not.

**Reading need not be O(folder), and correctness is defined as if it were.** The
authority is a full scan of every `*.jsonl`. An implementation may instead read
the newest `_full` plus the fragments after it, which is bounded by the 256-row
consolidation rule. It must then have some way to notice a fragment it would
otherwise skip, or a hand-placed file older than the newest consolidation is
ignored silently — which is exactly the case hand-placing exists for.

*My first suggestion for that check does not work and the app side said so:*
comparing the listing against "names I have not seen" needs state persisted
across restarts, which is the counter file this section rules out for the write
path, reintroduced on the read path. **The app's rule instead: force a full
scan when a fragment it would skip — `seq` below the newest `_full` of its
prefix — has an **mtime later than that `_full`**. A hand-placed file, or one
the migration tool overwrote, gives itself away that way, and no state is
persisted. Its stated limit: a copy that preserves an old mtime is not caught,
so a rebuild should not be restored with mtimes preserved.

### What a force-stop costs, and why the fragments are not enough on their own

The head unit is force-stopped often and deliberately, and it loses power with
the ignition. Neither runs a shutdown path: `SIGKILL` has no `onDestroy`, no
flush, no hook.

For the **store**, that is already survivable — `rename` means a fragment is
either absent or complete, so nothing committed is ever at risk.

For the **open segment**, the picture is narrower than this section first
claimed.

*Corrected 2026-09-26, the same day, by the Android session reading the code.*
This said `GpsRateAccumulator` keeps its block in memory until segment close, so
a kill costs up to five minutes of GPS. **That was build 23's behaviour and is
no longer true.** Build 27 added `GpsSnapshotStore`
(`tpms/GpsSnapshotStore.kt`, wired at `CodaApplication.kt:106` and `:218`): it
writes the open segment's block to app-internal storage every 60 s, and
catch-up reads it back — `gpsFor = { gps.take(name) ?: gpsSnapshots.take(name) }`.
So the ON-CAR loss is already bounded at 60 s. The three `gps: null` rows in
the corpus are build 23 rows, from before that existed, and were read here as
current behaviour.

This is the post-compaction failure `AGENTS.md` describes, in its exact shape:
the corpus evidence was real, the inference from it to today's code was never
checked, and nothing about the conclusion looked wrong.

**So what the `partial` row adds is not recovery on the car — it is getting that
GPS OFF the car.** `GpsSnapshotStore` is internal, deliberately outside
`CodaLogs/`, and reaches neither SeaDrive nor the companion; and `take()`
deletes the snapshot as it reads it, so it is one-shot. If the row it fed never
reaches the server, the block is gone from both places. The `partial` row is the
off-car copy, which makes it a **replacement** for `GpsSnapshotStore` rather
than a second mechanism beside it.

**`GpsSnapshotStore` is therefore scheduled for removal**, once partial rows are
writing — one mechanism rather than two, with catch-up taking the block from the
newest partial row for that log instead of from internal storage. Agreed with
the app side 2026-09-26.

*One-time bridge, theirs:* the segment open when the new build installs has its
last snapshot only in the old internal folder, so catch-up reads that folder
once as a final fallback after the store. A migration step with a natural end,
not a permanent second path.

The CAN-derived half of a row is regenerable from the log, *provided the
bytes reached disk*. How deep `BusmasterWriter`'s buffer is at the instant of
a kill is **not yet measured**, and it bounds how much is truly regenerable.
The check is cheap and orthogonal: force-stop mid-segment, note the wall
clock, compare against the log's last frame time. The answer changes the
justification for carrying the ratio accumulators in a `partial` row, not the
design — they are carried either way.

### Dedupe is mandatory, not a nicety

Fragments overlap by construction, so a reader that does not dedupe
double-weights drives and reads one calibration as several. Today's folder
already demonstrates it: two files, 18 drive rows, **13 distinct logs**, five
duplicated, two byte-identical calibration records.

- **Epoch identity** is the `calibration` record's **`name_ts` when present,
  else its `ts`** — the ordering key. N copies of one calibration are one
  epoch.

  *Changed 2026-09-26: it was `ts` alone, and two SETs in the same second
  merged into one epoch silently.* `ts` is a one-second stamp, so the second
  press carried the same identity; the reader folded it into the first, kept
  the first calibration, and the SET did nothing at all. Found by the app side.

  The ordering key is the right identity and costs nothing: `set` already
  pushes it strictly past every existing one, so it is unique by construction.
  Both fields are **record content**, so this is still an identity taken from
  the record and not from a filename. It also leaves `ts` meaning exactly what
  this section promises — the true wall-clock time of the press — which making
  `ts` itself unique by shifting it would have quietly broken. And it collapses
  two notions into one, so identity and ordering can no longer disagree.

  > **Nothing may derive a TIME from the identity key.** The key is a
  > timestamp-shaped string and, for a bumped epoch, it is *not* the press
  > time. Anything that parses a clock out of it silently starts reporting the
  > bumped value — which the app side hit immediately (its `setAtMs` was read
  > from the key) and warned about. The press time is `ts` on the head record,
  > always. `epoch_void.epoch` is likewise an **identity reference, not a
  > timestamp**. Both sides now assert this.
- **Drive identity** is `log`. A completed row beats every `partial`; then
  higher `proc`; then, among completed rows, higher `n`; among partials, higher
  **`gps.fixes`**; and `seq` breaks any remaining tie.

**Order by content, not by name.** `n` for completed rows and `gps.fixes` for
partials are both monotonic within a segment and both *measure how much the row
holds*, so they order correctly for a row that arrives out of sequence, is
rebuilt by catch-up, or is hand-placed — where `seq` means nothing. A partial
carries `n: 0` by construction, so `n` cannot order partials and `gps.fixes`
takes exactly the role `n` plays for completed rows.

> **Invariant: dedupe never loses a GPS block.** *Added 2026-09-26, after the
> app side found the hole.* The block on the surviving row comes from **the
> highest-ranked row for that log that has one** — the winner itself when it
> has its own, since a completed row outranks every partial, and otherwise the
> best partial. An inherited block is tagged `gps.source: "partial"`.
>
> **The donor's rank is what decides, not merely whether a block is present.**
> *Corrected the same day, again by the app side.* Stated as "inherit when the
> winner has none", the result depended on the order fragments happened to be
> read in: once a winner had taken a block from a weak partial, a better
> partial read later was ignored. Normal write order hides it, because partials
> precede their completed row; a consolidation mixed with ordinary fragments, a
> ` (1)` copy, or a hand-placed file produces the order that exposes it.
> Measured on three records before the fix — read completed/10/90 the winner
> kept **10 fixes**, read 10/90/completed it kept **90**. Both orders are
> reachable. The prototype now asserts all six permutations agree.
>
> This is a **merge, not a pick**, and it is allowed for exactly one field —
> the only one invariant 3 says cannot be regenerated. The hole it closes: a
> catch-up row is computed by re-reading a footerless log and can have no GPS
> of its own, yet it outranks every partial, so the GPS the partials existed to
> carry would be discarded at dedupe. Silently, with the row still present and
> still plausible.
>
> Stated as an invariant rather than a catch-up special case deliberately. Any
> future path that yields a `gps: null` winner is covered, and the rule is
> checkable without knowing which path produced the row.

*Recorded because the test did not catch this and should have:* the prototype's
phase 7 asserted "a completed row beats the partials", which is the rule as
written, and never asserted what the winner *loses*. A test that checks the
rule you wrote cannot find a rule that was wrong.

### Three invariants

1. **No derived quantity is ever stored.** No baseline, no psi, no verdict,
   no threshold. All of those are settings applied at ingest, so every one
   can be changed later against an unchanged file. K, the window length and
   the thresholds are all adjustable without restarting an epoch.
2. **Ratios are stored dimensionless.** The psi scale rests on a single gauge
   reading and the A/B test has not been done; keeping the conversion out of
   the file means the archive stays valid when that constant is revised.
3. **Everything except the GPS block is regenerable** from the CAN logs,
   which is why each row names its source log. Only the GPS sums are
   irrecoverable; they are the part that must not be lost.

   *Corrected 2026-09-24: this previously said "except GPS and temperature".
   Temperatures come from `0x382`/`0x390`/`0x391` on B CAN, which the app
   captures in the same logs, so they are as regenerable as the ratios. The
   practical consequence is that the temperature channel list below is a
   convenience and a wrong choice is recoverable — unlike the GPS block,
   where a wrong choice is permanent.*

### Records

```
{"type":"calibration","schema":2,"ts":...,"psi":{LF,RF,LR,RR},"temp_c":...}
{"type":"calibration_amend","schema":2,"ts":...,"psi":{...},"temp_c":...}
{"type":"epoch_void","schema":2,"ts":...,"epoch":"<calibration ts>"}
{"type":"drive","schema":2,"proc":2,"ts":...,"log":"coda_..._T0.log","n":...,
 "partial":false,"dur_s":...,"kmh_med":...,"ratios":{...},"temps":{...},
 "gps":{...},"steer_centre":...,"steer_centre_src":"fast"|"all",
 "steer_n":...,"steer_n_fast":...,"void":null}

{"type":"drive","schema":2,"ts":...,"log":"coda_..._T0.log",
 "partial":true,"n":0,"ratios":null,"gps":{...}}
```

The second form is the per-minute checkpoint of a segment still open. It
carries **GPS and nothing else that matters**, because GPS is the only field
invariant 3 says cannot be regenerated. `partial` is written explicitly rather
than left absent: a reader using get-with-default cannot tell absent from
false, and this is the field dedupe turns on.

`gps.source` records where a block came from — a live segment close, or
`"partial"` when a completed row inherited one under the dedupe invariant
above.

`schema` 2 is the fragment store. The only record-level changes from schema 1
are `partial` on a drive row and the new `epoch_void` type; the rest of a row
is byte-for-byte what schema 1 held, so a schema-1 row can be promoted by
adding `"partial": false`.

One drive row per CAN log segment, so the store stays 1:1 with the logs
beside it. About 500 bytes per drive.

**A reader drops unparseable lines and counts them; it never raises.** A
fragment should never be truncated now that files are renamed into place, but
the rule costs nothing and a reader that throws discards the whole history
over one bad byte in one fragment.

### `proc` — which rules produced the numbers

`schema` says how a record is *laid out*. `proc` says which filters and decode
*produced its numbers*. They move independently: a change that adds a field
bumps `schema`; a change that moves `DEL` bumps `proc`. Conflating them would
make a row whose layout is unchanged but whose numbers are on a new scale
indistinguishable from one that is genuinely comparable.

| `proc` | rules |
|---|---|
| 1 | build 23: 20 Nm on every contrast, 1 % steadiness, all-samples steering centre |
| 2 | v24 (builds 24–28): fast steering centre, 40/20 Nm per contrast, 2 % steadiness |
| 3 | **20 Nm on every contrast**, 2 % steadiness, fast steering centre, **D CAN pinned by anchors**. First implemented by the build AFTER 29 — see the note below |

`proc` 3 is `proc` 2 with the torque relaxation withdrawn, and it is the best of
the four rule sets measured on every column — see §1.

> **Corrected 2026-09-27: `proc` 3 is not build 29.** This row read "build 29"
> until the app session reported that build 29 *was* dropped to the owner on
> 2026-09-26, tagging its rows `proc` 3 while still using `dominantBus` — so a
> build carrying the `proc` 3 label without D CAN pinning existed. **The owner
> has confirmed build 29 was never installed**, which is why `proc` 3 keeps the
> number and no `proc` 4 is needed; build 29 is recorded app-side as "do not
> install". Had it run on the car, identical `proc` values would have described
> different processing. `proc` is a claim about *rules*, and tying it to a build
> number in this table is what made the mismatch invisible — hence the wording
> above.

**D CAN pinning was folded into `proc` 3 rather than given a `proc` 4, and that
was only possible because no `proc` 3 row had reached the car.** *2026-09-27.* Pinning
moves the numbers by about 3e−6 (0.03 psi), which by this section's own rule
demands a bump — but no row had yet been written under `proc` 3, so there was
nothing to keep comparable and the definition could still absorb it. Build 29
came within one installation of costing a `proc` 4 and leaving
the epoch mixing three rule sets instead of two. **The general point: a rule
change is free only in the window before the first row is written under the
rule set it changes.**

Bump it whenever a change moves the numbers, not when one moves the layout.

**The absent case needs a rule, because "absent means 1" is wrong for one
build.** The tag ships after build 26, but build 26's rows are already v24.
Taking absence to mean `proc 1` would therefore label a whole build's rows
with the wrong rule set — silently, and in the direction that makes them look
poolable with older rows when they are not.

So absence is resolved by **structure, not by default**:

- `ratios.DEL.n` present → **`proc` 2**. Per-ratio counts arrived with the
  per-contrast cap, so their presence *is* the v24 signature.
- otherwise → `proc` 1.

A row with `ratios: null` carries no marker and needs none: it has no numbers,
contributes nothing to any pool, and its rule set is therefore unobservable
and irrelevant. Prefer `ratios.DEL.n` over `steer_centre_src` for this test —
the latter is legitimately `null` on a segment with no steering, and a reader
using a get-with-default cannot tell that from absent.

**Nothing reads `proc` yet, deliberately.** It is recorded now so that the
information exists when it is needed, on the same principle as the GPS block.
Acting on it would mean either discarding rows or rescaling them, and with a
single pre-v24 drive in the corpus the mixing is far below the noise — see
below. The tag's value is that it makes a *later* decision possible; using it
now would be a change with no measurable benefit.

**Mixing three rule sets in one epoch, measured rather than estimated.**
*Rewritten 2026-09-26 when build 29 took the cap back to 20 Nm; this section
previously reasoned about `proc` 1 against v24 as though v24 were the future,
and concluded 0.073 psi. That framing is superseded — future readings are
`proc` 3.*

Reprocessing `coda_20260926_155726` under all three rule sets:

| | `proc` 1 | `proc` 2 (v24) | `proc` 3 | 3 − 1 | 3 − 2 |
|---|---|---|---|---|---|
| `DEL` | 0.999216 | 0.999288 | 0.999223 | **+0.0000070** | −0.0000656 |
| `F/R` | 1.004577 | 1.004547 | 1.004547 | −0.000030 | **0.0000000** |
| `L/R` | 0.999958 | 1.000230 | 1.000079 | +0.000121 | −0.000151 |

Two independent checks fall out of this table, and both hold:

- **`F/R` is bit-identical between `proc` 2 and `proc` 3**, because `F/R` was
  already capped at 20 Nm in v24. If a re-implementation's `proc`-3 `F/R`
  differs from its v24 `F/R` by anything at all, that is a bug in the new
  filter set and not a rule change.
- **`proc` 3 lands within 7 × 10⁻⁶ of `proc` 1 on `DEL`** — 0.06 psi. Which it
  must, because those two rule sets *share the 20 Nm cap* and differ only in
  steadiness and the steering-centre estimator. The `proc` 1 → 2 offset was
  measured weeks earlier by reprocessing one drive; the `proc` 2 → 3 offset
  came from the corpus CSVs and the extractor. **Two offsets, measured at
  different times by different routes, cancelling to 9 % of their own
  magnitude.** That is the only independent validation these offset numbers
  have, and it says the torque cap is what moves the numbers while the other
  two changes are nearly free.

**The offset is not a constant of the rule change; it is drive-dependent, and
the corpus mean has the wrong SIGN for this car's epoch.** Over the 208
sessions both rule sets accept, `proc` 3 − `proc` 2 averages **+0.0000431** on
`DEL` (sd 0.0000435). On the two drives actually in the live epoch it is
**−0.0000656 and −0.0000657**, agreeing to 10⁻⁷ with each other and opposite in
sign to the corpus. So use the epoch's own drives, never the corpus mean.

**The live epoch was still learning when this was measured** — two qualifying
sessions against K = 3 — so build 29's first qualifying drive joins the learning
pool rather than being read against a frozen baseline. The pool then holds all
three rule sets at n-weighted shares 7.7 / 63.9 / 28.4 %, and the residual bias
on a frozen baseline works out at

```
0.077 x (+7.0e-6) + 0.639 x (-6.56e-5) = -4.14e-5 DEL
```

= **−0.38 psi of front differential, about 0.16–0.31 psi on a corner** — roughly
63 % of what an all-`proc`-2 pool would have given, because the `proc`-3 learning
drive pulls the baseline toward where the readings will land. Against a
per-drive 3σ of ~2.0 psi and an advisory at 2.5 psi.

**No re-SET is forced.** A re-SET at the owner's next real inflation is
preferred to one now: he will be gauging the tyres then anyway, and the
alternative is discarding a learned baseline to remove a quarter of a psi.

**The sample floors do NOT need relaxing to compensate, and must not be.**
`learn_min_samples` is a floor on the POOLED count across the learning drives,
not a per-drive one, so halving the per-drive yield does not halve the learning
rate:

| | `proc` 2 | `proc` 3 |
|---|---|---|
| drives clearing `min_samples` 800 | 197 | 181 |
| median `n` per qualifying drive | 7545 | 3508 |
| per-drive retention | — | median 0.494 (p10 0.355, p90 0.687) |
| drives needed for K=3 **and** pooled ≥ 2400 | median 3, worst 3 | median 3, worst 3 |
| distinct qualifying days in 221 | 84 | 81 |

K = 3 binds; the sample floor never does, because the median `proc`-3 drive
still yields 3508 samples and even the 25th percentile is 2462. The practical
cost is **one qualifying day every 2.63 days becoming one every 2.73** — a
tenth of a day. Lowering the floors to restore the old drive count would hand
back exactly the 21 % sensitivity the cap was adopted to gain.

*A per-drive count of "drives with n ≥ 2400" gives 166 → 139 and reads like a
16 % learning penalty. It is the wrong test: it treats a pooled requirement as
a per-drive one. Recorded because the number looks like an answer.*

*On-device reprocessing was considered and declined. The logs are the source
for any offline re-derivation, which keeps one authority rather than two.*

### Transport, and the guards that must survive opening it up

**Backup is SeaDrive on the head unit**, one-way, upload-only. It **scans every
file when it opens and uploads any it has not already uploaded** (owner,
2026-09-26) — which is both why the fragment store works and why the
append-only file could not: a new file is picked up, a modified one is
"already uploaded". Nothing placed in the library reaches the car.

- **This transition needs no manual migration.** *Corrected 2026-09-26 by the
  app side, and verified here.* The pre-fragment files already lead with a
  `calibration` record, so the fragment reader reads them as fragments as they
  stand — an absent `partial` is false. The first fragment a new build writes
  has no `_full` in the epoch yet, so it consolidates, carrying the whole
  history forward. Installing the build migrates the store. Checked against the
  live file: read as one epoch with all 13 rows before any write, and the first
  new row produced a 15-record `…_000000_full.jsonl`.
- **The hand-placed rebuild remains, for a future schema break.** That is what
  the owner asked it for: *"if we break the schema, we clear out the folder on
  the car and drop in something regenerated from the old data."* It is a
  capability, not a step in this change. `artifacts/tpms_migrate_fragments.py`
  produces the folder; placing it is car-side, because the sync is one-way.
- **The library's copy of a pre-fragment file is frozen for ever.** It will
  never be refreshed, whatever happens on the car.

**Requirement on the app side: the head unit gets a recursive read route.**
Today `LogFileServer` is `.log`-only and non-recursive, so `CodaLogs/tpms/` has
no network route at all — the folder cannot be read back, verified, or
recovered remotely, which is why the 2026-09-26 recovery could reach the CAN
logs and not the store. This also closes the open question already recorded at
`android-app/notes/plans/companion-file-sync.md:195`.

**`/files` does not change. A new `GET /tree` does the recursive listing.**

| route | scope |
|---|---|
| `GET /files` | **unchanged** — log root, `.log`, flat |
| `GET /tree` | recursive, over a served-extension whitelist (`.log`, `.jsonl`, `.json`) |
| `GET /files/<path>` | accepts sub-paths, with canonical-path containment |
| **`PUT /files/tpms/<name>.jsonl`** | **new** — places a fragment on the car. Nothing else is writable. See below. |
| `DELETE /files/<name>` | **unchanged** — log root, `.log`, flat |

**Measured on the car, build 30, 2026-10-04.** The implementation is *narrower*
than the `PUT /files/<path>` this table first specified, and the narrowing is
right: the only writable target is `tpms/<name>.jsonl`, so **`PUT` cannot reach
a CAN capture at all.**

| attempt | result |
|---|---|
| `tpms/<name>.jsonl` | **201 Created** |
| `<name>.log` (log root) | 403 `PUT accepts only tpms/<name>.jsonl` |
| `tpms/probe.json` | 403 — extension enforced, not just the served whitelist |
| `tpms/sub/deep.jsonl` | 403 — no nesting |
| `tpms/../escape.jsonl` | 403 |
| `../escape.jsonl`, `tpms/../../escape.jsonl` | 404 |

Containment holds and the rejected attempts wrote nothing, confirmed against
`GET /tree` afterwards.

**Immutability is enforced server-side, not left to convention.** A second
`PUT` of a name that already exists returns **409 `exists; PUT never
replaces`**. This section's requirement that a correction be an addition and
never an edit is therefore impossible to violate over the network, rather than
merely discouraged.

**`DELETE` cannot reach a fragment, and that is load-bearing.** Verified the
same day: `DELETE /files/tpms/<name>.jsonl` and `DELETE /files/<name>.jsonl`
both return 404, because `DELETE` stays log-root `.log`-flat. So the companion's
pull-then-DELETE can never touch the store — the guard
`artifacts/recover_truncated_logs.py` records as by-design. **The consequence
for operations: a fragment placed by `PUT` can only be removed on the head unit
by hand.** Place nothing whose permanence is not acceptable.

**A hand-placed fragment is picked up live, with no restart.** Measured the same
day: a `PUT` at `seq` 500 landed at 15:59:52 and the app's next per-minute write
took `seq` **501** at 16:00:02. So `seq = max(directory) + 1` holds against an
external writer, and "the directory is the state" is true of writers other than
the app. Note the cost: an out-of-band `seq` advances the counter permanently.
A correction should take the next free `seq`, not a high one.

#### `PUT` exists so a correction can go back to the car and still be used

**Owner's requirement, 2026-09-27**, and it is the reason the read-only route is
not enough: *"this is why we need to be able to regenerate/correct the locally
stored data so we can put corrected data back on the car but still use it."*

Rows are derived from CAN logs, and the logs are kept — so when a rule changes,
or a defect like the `dominant_bus` selection is found, the affected rows can be
**re-derived offline and returned**, instead of the epoch carrying known-bad
numbers until the next calibration. Without a write route the only options were
to live with them or to clear the folder by hand.

**The fragment store already makes the correction work; `PUT` only moves the
bytes.** Nothing needs deleting and nothing is overwritten:

- a re-derived row is written under the **new `proc`**, and dedupe prefers the
  **higher `proc`** for a given `log` — so the corrected row supersedes the old
  one the moment it lands, and the old fragment can stay where it is;
- the epoch, the baseline history and every other row are untouched, which is
  what *"but still use it"* requires;
- fragments are immutable, so a correction is an **addition**, never an edit.

> **A corrected row must carry the original's GPS block forward verbatim,
> `gps.source` included.** Everything else in a row is regenerable from the log;
> the GPS block is not (invariant 3). An offline re-derivation that recomputed a
> row from CAN alone would produce `gps: null` and **silently drop the one
> unregenerable channel**. The dedupe inheritance invariant of §4 would catch it
> — a GPS-less winner inherits from the row it superseded — but that is a
> backstop, not the mechanism. The tool copies the block deliberately.

**Guards on `PUT`, because it is the first route that can write to the car:**

- **bearer token**, the same `sync.token` as every other route;
- **`.jsonl` under the TPMS subtree only.** It exists to place fragments, not to
  write anywhere on the device. A `PUT` outside that subtree is refused;
- **path safety as for `GET`** — reject empty, `.` and `..` segments,
  canonicalise, assert containment under the served root;
- **create-only, never replace.** A `PUT` to an existing path is refused. Under
  an immutable-fragment store there is no legitimate reason to overwrite, and
  refusing means a mistaken push cannot destroy a fragment the sync has not yet
  uploaded;
- **atomic on the device** — write `.jsonl.tmp`, `fsync`, rename — so the sync
  and the app never observe a partial fragment, exactly as for the app's own
  writes;
- **the active epoch is not special.** A fragment may be placed for any epoch,
  including the live one, because dedupe resolves it rather than the file
  position doing so.

*Clearing the folder by hand remains possible and is now the exception rather
than the route: it is for a schema break, where the whole store is rebuilt.
`PUT` is for a correction inside an existing schema.*

*This is the app side's design and it is better than the one this section
carried until 2026-09-26, which widened `/files` itself.* The failure that
version could not see:

> **The companion already installed pulls whatever `/files` lists and then
> `DELETE`s it** (`SyncEngine.kt:162`). With `DELETE` refused for `tpms/` it
> records "DELETE failed; will retry next sync" and never adds the name to its
> index — so it would **re-download every fragment on every sync, for ever.**

The earlier reasoning was "reading was never the danger", and that was the
error. Reading was not the danger; **being listed** was. Keeping `/files`
byte-identical means no installed client changes behaviour at all, which is a
stronger guarantee than making the destructive verb refuse.

Path safety on `/files/<path>` replaces the no-`/` rule with the standard one:
reject empty, `.` and `..` segments, canonicalise, and assert the resolution
lies under the served root.

This also retires a trap this section used to carry: *"if the primary sync
route is ever switched from SeaDrive to the companion, TPMS backup silently
stops"* — true while the store was invisible to the server, and no longer true
once `/tree` exists. The trap was recorded because the failure was silent; the
fix is to remove the silence, not to remember harder.

*Under the fragment store, pull-then-DELETE stops being a hazard on its own
terms — fragments are immutable, which is the contract `SyncEngine` was built
for. The app notes retired an immutable-fragment design on the reasoning that
"nothing deletes these files, so a single append-only file works". That
reasoning is now falsified: the deleter was never the only threat, and the
transport is.*

---

**The file name is an ordering key; the record carries the true clock time.**
Usually the same string, and they must not be assumed to be. If the head
unit's clock is behind the newest epoch — no RTC guarantee before a time sync
after boot — or two presses land in the same second, a name taken straight
from the clock would not sort last and `set` would *silently do nothing*. The
name is therefore pushed past the newest epoch while the record keeps the
real time, under `name_ts` when the two differ.

Clock error degrades reporting, not detection: nothing in the detector is
time-based. K, M, confirmation and step detection are all counted in drives,
so a wrong clock misdates a row without changing a verdict.

Drives below the sample floor are still stored, with their `n`. The floor is
a setting and may change.

---

## 5. Epoch operations

A calibration record does two independent jobs, and conflating them costs the
owner his history:

- **Event marker** — "the pressures were just set to known-good". This
  anchors the baseline and is what must never be re-learned automatically.
- **Pressure values** — four psi and a temperature, used *only* to convert
  relative deltas into absolute pressures. **They never feed the baseline.**

Hence three operations:

| op | availability | effect |
|---|---|---|
| `set` | always | opens a new epoch; costs the learning period, correctly |
| `undo` | while the current epoch has recorded no qualifying drive **and** a previous epoch exists | voids the new epoch with an `epoch_void` record, resumes the previous one with baseline and history intact |
| `amend` | always, including months later | corrects the values only; touches neither epoch nor baseline |

`undo` answers "I bumped SET and don't want to go and gauge the tyres again".
Without it an accidental keypress costs the whole learning period and orphans
the history.

Two traps, both invisible at the call site:

- **`undo` must restore the previous epoch, not re-apply its numbers through
  `set`.** The naive version looks identical in the UI and opens a *third*
  epoch, destroying exactly what undo exists to preserve.
- **`amend` must not be able to move the epoch's timestamp.** If it can, a
  caller building a record with the current time — which is what the `set`
  path does — silently converts the amend into a `set`. Make it
  unrepresentable: take loose values, not a record carrying a timestamp. The
  amendment gets its own audit timestamp; the calibration's stays put.

There is no archive step. Old fragments simply stay in the folder; nothing is
ever moved.

**`undo` is a tombstone, not a delete.** *Changed 2026-09-26 with the fragment
store.* It writes an `epoch_void` record naming the voided calibration's `ts`,
in a fragment of the epoch it voids — so the fragment's first record is still
that epoch's `calibration` and the role-by-first-record rule holds unchanged.
A reader treats an epoch with a matching `epoch_void` as not an epoch, and the
previous one resumes as active.

Deleting instead cannot work, for two independent reasons:

- an epoch is now spread over many fragments, so `undo` would have to find and
  delete all of them, and missing one leaves the voided epoch active;
- **fragments already uploaded cannot be recalled.** The sync is one-way, so a
  local delete never reaches the server copy. A record can say "this epoch was
  withdrawn"; an absent file cannot.

A local delete of the voided epoch's fragments is still permitted as tidying,
and must never be load-bearing: the tombstone is what carries the meaning.

**A file's role comes from its first record, never from its name.** A
precalibration file is named like an epoch and is not one; keying on the name
makes it an undo target and lets it be picked as active, silently. Only a
file whose first record is a `calibration` is an epoch.

**"A qualifying drive has been recorded" means a qualifying SESSION.** Rows
are per log segment, so three 300-sample segments of one session are a
qualifying drive that no single row shows. Pool `n` by session before
comparing against the floor, or `undo` stays available after a drive that has
already moved the baseline.

---

## 6. Display

**Corners are keyed, never positional.** Four positional corner fields, or
four positional psi arguments, are transposable at any construction site: it
compiles, the numbers stay entirely plausible, and the driver inflates the
wrong tyre on the strength of a confident display. No screen layout can catch
data that arrives pre-swapped. So the app keys by a `Corner` enum on both the
display side and the calibration-entry side — a transposition on entry is
worse still, since it poisons the baseline for two corners at once rather
than merely misreporting them. An absent key renders as absent rather than
throwing, so a partially populated map degrades to dashes.

The same hazard exists on the analysis side and is handled the same way: the
contrast signs are declared per corner (`CONTRAST_SIGNS`) and the inversion
matrix is *derived* from them in `CORNERS` order, so reordering one cannot
silently desynchronise the other.

Per corner: `deltaPsi` against the calibration baseline, plus a **nullable**
`absolutePsi`, with

```
absolutePsi = calibrationPsi + deltaPsi + commonModePsi
```

`commonModePsi` is null today because ratios cancel common mode by
construction. When the channel of §7 lands it fills in and the same four
fields switch from relative to absolute with no UI change.

The four deltas already share an unknown common offset, and that offset *is*
the common mode — which is why `absolutePsi` is a separate nullable rather
than defaulting to zero. Showing an absolute pressure without it would be
asserting something not measured.

One decimal place. Per-corner precision is ~0.7 psi (1σ) from one drive and
~0.3 psi from a five-drive window; more digits claim precision that is not
there.

**Placard is 42 psi**, corroborated by the RCU's own DTC limits of 33.6 and
50.4 psi — exactly 0.80× and 1.20× of 42 — in the factory
manual's RCU DTC table (internal-only). This is
the only placard figure; an earlier 33 in the feasibility doc was wrong and
has been corrected.

---

## 7. Common mode — collect now, use later

Ratios are blind to all four tyres moving together. GPS is the only viable
absolute reference (the CAN accelerometer was tested and fails by ~24×).
**Collected but not in the detection loop**, so a rate-aware algorithm can be
built once there is data.

### What the blind spot costs, on this car, today

Not hypothetical. Take the gauged 2026-09-20 pressures against the 42 psi
placard and split them into what the detector can and cannot see:

| corner | actual | deficit | common mode | residual | **displayed** |
|---|---|---|---|---|---|
| LF | 31 | −11 | −9 | −2 | **−2.7** |
| RF | 35 | −7 | −9 | +2 | **+2.7** |
| LR | 33 | −9 | −9 | 0 | **0.0** |
| RR | 33 | −9 | −9 | 0 | **0.0** |

Assuming a correct calibration at 42 all round and then this state developing,
the panel would show: two tyres at zero, one advisory at −2.7, and **RF — which
is 7 psi down — reading +2.7, as though it were above reference.** The worst
tyre, 26 % under-inflated, scrapes past the advisory threshold and never
reaches WARN.

The visible share of the real problem on the worst corner is **18 %**, or 24 %
after the 4/3 projection. Roughly a fifth, not a third. This is the difference
between "misses some of it" and "misses nearly all of it", and it is why the
GPS collection is worth enabling early rather than treated as optional.

### Two distinct ways the common mode bites

They need separating because they have different fixes:

1. **Calibrating at already-low pressures.** The app cannot check what it is
   told, so calibrating at whatever the tyres currently read records the
   under-inflation as the reference and the detector will never mention it —
   it only ever reports divergence *from soft*. Fixed by the UI making the
   order of operations explicit: inflate to spec, then set.
2. **A uniform leak after a correct calibration.** The case in the table
   above. No UI wording helps; only an absolute reference does.

Until `absolutePsi` is non-null the panel must not say anything that reads as
a pressure — and **"pressure change" is not good enough either.** RF's
pressure changed by −7 psi and the cell reads +2.7; the rear pair changed by
−9 and read 0.0. Under a heading that says *change*, those are not merely
uninformative, they are false in direction.

The numbers are correct as **imbalance**, so the heading is what has to
carry the qualification: *pressure imbalance*, subtitled to the effect that
it is measured between corners and that a uniform loss on all four reads
zero. That puts the blind spot in front of the reader at the moment of
reading rather than only in this document. Headings flip to an absolute
form the moment any corner carries a non-null `absolutePsi`.

*This paragraph previously recommended "pressure change". The worked table
above is what overturned it — the recommendation was made before the
per-corner figures were computed.*

**No absolute position stored; otherwise only what GPS-TPMS needs.** Owner
requirement, refined 2026-09-24: *"I just don't want absolute GPS position
stored. OK to store enough data to theoretically integrate someone's travel
from it, but ideally we limit to only what is needed for GPS TPMS support."*

Satisfiable exactly: a least-squares slope depends only on
`N, Σx, Σy, Σxy, Σx²`, which are sufficient statistics, so the app never
retains a sample. Never write a `Location` object anywhere — read `speed`
inside the callback, fold it into the accumulators, let it go out of scope.
Altitude is consumed in-handler and never stored; only Σ(grade²) leaves it.

Speed-binned sums do let a reader bound how far the car travelled in a drive.
They do not say where, and the owner accepted that trade explicitly.

> **Collect broadly now, narrow deliberately later.** Owner's position,
> 2026-09-26: he is driving the car himself and is content to be tracked at
> this level, *and* the goal is to end up collecting as little as possible —
> because a friend who borrows the car should not be tracked by it. Those are
> not in tension: knowing which data the algorithm actually needs requires
> collecting more than it needs first.
>
> So the present breadth is a **measurement phase with an exit**, not a
> settled design. Every accumulator here should be revisited once the
> algorithm is calibrated, and the ones that did not earn their place
> removed. The `loose` set already has such an exit condition; the rest need
> one. Whatever survives should be small enough that a borrowed-car mode is a
> matter of switching collection off rather than redesigning it.

### The block, as built

`gps` is `null` when GPS was not running, including every catch-up row. When
it ran but got no fix, the block exists with `fixes: 0`.

```
schema 1
x  "rear_counts"   rear-pair average as counts above 0xC000 -- i.e. a DBC
                   decode of the 14-bit signal, equivalently raw16 & 0x3FFF.
                   No wheel scale applied. See the encoding note in section 1:
                   decoding via the DBC and THEN subtracting 0xC000 is the
                   error this wording exists to prevent.
y  "gps_mps"       GPS speed, m/s
band_kmh 10
source   "close" | "snapshot"
fixes, no_speed, unpaired, implausible
sum_speed_acc, n_speed_acc, sum_speed_acc_sq
strict { ... }     share no state
loose  { ... }
```

**`schema` is 2 from v24.** The `strict` channel's mask tracks the `DEL`
filter set by definition — it is *the tight set*, and if the tight set is
redefined and strict does not follow, its name lies. So the v24 threshold
change (torque 40 Nm, steadiness 2 %) moves it too. `x` is the rear pair on an
undriven axle, so the torque relaxation is safer here than for the
discriminants.

The cost is that schema-1 and schema-2 `strict` sums are **not poolable**: the
same accumulator now covers a different population. Hence the bump, so the
discontinuity is a data value rather than a date someone has to remember.
`loose` moves with it for the same reason.

*Evidence that this was needed: on 2026-09-26 `strict` yielded `gps_s` of
**1.0 s** against `loose`'s **17.96 s** over a 300 s segment — one paired
sample in one band. The plan had been to retire `loose` once real data
existed; the data said it was `strict` that could not survive.*

**`source` distinguishes a complete block from a short one.** `"close"` is a
block finished at a live segment close. `"snapshot"` is the last periodic copy
of an open segment's block, taken every 60 s and used by catch-up after a
power cut, so it is **up to about 60 s short of the segment's true end**.

That is a coverage difference, not provenance, which is why it is not merely
flagged as "recovered": a snapshot's `gps_s`, band sums and lag chains all
stop early, and pooling them with close blocks silently under-weights the ends
of segments. Since a power cut is what produces a snapshot, and a power cut
most often happens at the end of a drive, the missing minute is
systematically the arrival — not a random minute.

Snapshots live in app-internal storage, never in `CodaLogs`, so they cannot
reach the log store as stray files.

*Before this existed, a segment that died took its whole GPS block with it,
the block being in memory only. On 2026-09-26 that was 3 of 5 rows — and the
three were exactly the three logs with no BUSMASTER close footer.*

Each of `strict` and `loose`:

```
gps_s                seconds covered by kept fixes
bands { "80": { N, sum_x, sum_y, sum_xy, sum_xx, sum_yy,
                n_g, sum_g2, n_g_noise, sum_g2_noise,
                n_speed_acc, sum_speed_acc } }
lags  { N[4], yy[4], xx[4], yx[4], xy[4] }   l = 0..3 kept fixes back
```

Why each part is the way it is:

- **`x` is the rear pair, in raw counts.** The Coda is FWD, so the driven
  wheels carry slip the undriven pair does not. Raw counts bake in no wheel
  scale, so every stored sum stays valid if the 17.61 is ever revised.
- **Bands are keyed on `x`, not `y`.** Binning on the GPS speed would select
  on its own error, pulling each band's mean toward the band centre and
  dragging the slope with it. `x` is effectively noise-free — one count is
  0.0157 m/s, averaged over ~100 samples per pairing window.
- **Banding at all**, because the tyre grows with speed roughly as v²: a drive
  averaging 80 km/h reads ~2.5 psi different from one averaging 60. Banding
  makes that term fittable instead of lurking.
- **Pairing** holds each fix until wheel samples exist ±0.5 s around it, then
  pairs it with the mean `x` over that window. The mean of a locally linear
  speed over a symmetric window equals its midpoint value, so this is
  unbiased at the fix epoch *and* reduces wheel noise. Fix time comes from
  `elapsedRealtimeNanos` mapped into the CAN frames' clock with the offset
  re-taken at every fix — sub-millisecond jitter instead of accumulating
  drift.
- **Lag 0–3 products, k-agnostic**: any `k`'s residual autocovariance is
  recoverable as `Syy(l) − k(Syx(l) + Sxy(l)) + k²Sxx(l)`. *Both* cross terms
  are needed; cross-covariance is not symmetric in lag. Chains reset on any
  non-kept fix, so **the strict lag arrays will be sparse** — that is expected,
  and it is the same reason the loose set must exist.

  *This spec originally asked for the autocovariance of (y − k·x) directly.
  That is not computable at collection time, because `k` is the very thing
  being measured. Corrected 2026-09-23.*

- **The live filter mask differs slightly from the offline one** and cannot be
  reconciled later, so it is recorded here: rear speed, steering and torque
  are sample-and-hold rather than interpolated, and steer rate is a backward
  difference over 0.1 s rather than a centred `np.gradient`. Neither biases —
  sample-and-hold is a sub-sample difference at 100 Hz, and a backward
  difference is noisier but unbiased.

### The plausibility gate

A fix whose GPS speed disagrees with its paired wheel speed by more than 20 %
is rejected before anything is summed, counted in `implausible`, and breaks
both lag chains.

**This matters more here than anywhere else in the app.** With raw samples a
bad one can be discarded later; with sums it cannot — a single absurd fix
folded into a band is permanent, silent, and afterwards unidentifiable. That
asymmetry is why the irrecoverable block gets *more* input sanitisation than
the regenerable ones, not less.

It cannot clip the signal: 50 psi of common mode is a 1.10 % speed difference
and 10 psi is 0.22 %, so the gate has some twenty thousand times the headroom
of anything being measured. It catches receiver glitches and tunnel
re-acquisition only.

**Do not gate on `speedAccuracy`** — that one *would* bias, because accuracy
correlates with conditions. It is recorded instead, per band and in total
with its sum of squares, so a degraded band is identifiable at ingest.

### Grade, and why the noise term is not optional

Grade is measured over a ~10 s baseline (8–12 s, ≥50 m): `g = Δaltitude / d`,
with `d` the integrated GPS speed. Only `g²` is summed; no altitude, altitude
rate or per-sample grade is stored.

`E[ĝ²]` is inflated by `(σ₁² + σ₂²)/d²` from the two altitude errors, so
`sum_g2_noise` accumulates that term from each fix's `verticalAccuracy` and
the correction is `sum_g2 − sum_g2_noise` at ingest. This is not a refinement:

| baseline | inflation | vs a real 2 % grade (g² = 4.0e-4) |
|---|---|---|
| 10 s at 25 m/s (250 m) | 2.9e-4 | comparable |
| 10 s at 7 m/s (70 m) | 3.7e-3 | **9× larger** |
| 1 s at 25 m/s (25 m) | 2.9e-2 | 70× larger |

at 3 m vertical accuracy. Without the noise term the "correction" would be
mostly subtracting noise, and over one fix interval it would be meaningless —
which is why the baseline is ~10 s and not per-fix.

> **The correction can go negative, and that is information, not an error.**
> At low speed the baseline is short and the noise term dominates. A band
> whose `sum_g2_noise` is comparable to or larger than its `sum_g2` carries no
> grade information; drop it from the grade correction. Do **not** clamp it to
> zero and use it — that silently asserts flat road on exactly the bands where
> nothing is known.

### `gps.elev` — elevation change. Not a TPMS input.

Added 2026-09-25 at the owner's request, for a different job: correcting
efficiency estimates for gravitational energy. `efficiency-calculation.md` §2c
currently cancels elevation only by averaging out-and-back pairs, and its own
open items record that **only 3 highway pairs survive that filter**, so the
+4.4 % highway drivetrain penalty rests on 88.7 miles. A direct elevation term
replaces a filter that discards most of the corpus.

It rides in the drive row because that is the one per-segment, synced,
GPS-bearing record joinable to the logs by name. **Nothing in the TPMS
detector reads it.**

```
gps.elev { dh_m, climb_m, descent_m, deadband_m, n, low_acc,
           sum_vacc, n_vacc, parked }
```

- **Changes only, never an altitude.** Consistent with "no absolute position".
- **`dh_m` is the net change and telescopes**, each increment taken from the
  previous fix, across segment boundaries. Per-segment values therefore sum
  exactly to the trip's net change. No deadband. Noise enters only at the two
  endpoints — `σ_net = √2·σ_v` ≈ 4.2 m at σ_v = 3 m, so 4 % of a 100 m climb.
- **`climb_m` and `descent_m`** run a 5 m hysteresis on altitude **averaged
  over 10 s**. Separate from each other because regen recovers only part of a
  descent. Session-scoped, carried across segments, used only once the window
  spans ≥ 8 s.
- **Fixes taken while the wheels show under 5 km/h are skipped**, counted in
  `parked`, as are fixes with no wheel sample within 2 s. They change
  *nothing* — not `n`, `dh_m`, `climb_m` or `descent_m` — and the smoothing
  window restarts when motion resumes.

  This is not a refinement. A stationary receiver's altitude solution wanders
  as the satellite geometry changes, and the wander is **one-signed over
  minutes**, which a deadband cannot catch. Measured on 2026-09-26 in
  `154817_T0`, a segment in which the car provably did not move above 6.9
  km/h: **climb 10.06 m, descent 0.00 m** over 300 fixes with the 5 m
  deadband in force. Ten metres of climb from a parked car, and none of the
  matching descent — the same order as the 10.16 m of real climb recorded on
  the drive itself. Grade enters the model as g²/2, which is one-signed and
  does not average out, so this biases in a fixed direction.

  `dh_m` is unaffected either way and still telescopes across the stop:
  a sum of per-fix increments through a parked stretch collapses to
  (first moving fix after) − (last moving fix before), which is what skipping
  them gives directly. What it does mean is that a long stop puts the drift
  between those two fixes into `dh_m` — so on a drive with long stops the
  `σ_net = √2·σ_v ≈ 4.2 m` figure above is optimistic, and `parked` is the
  field that says when to distrust it.

  **`deadband_m` stays 5** in v24. Scaling it off the reported vertical
  accuracy was considered and deferred: motion gating removes the measured
  failure, and the two changes at once would have made it impossible to tell
  which one worked.

- **Fixes with `verticalAccuracy` > 20 m are skipped**, counted in `low_acc`.
- `deadband_m` is stored rather than assumed, so the threshold is a data value
  and not a hidden constant.

> **The smoothing is load-bearing, not a refinement.** Run on raw 1 Hz fixes
> the hysteresis is not a deadband, it is a random walk with a step filter.
> Simulated on *perfectly flat* ground over a 30-minute drive: **2216 m** of
> phantom climb at σ_v = 3 m, 4558 m at σ_v = 5 m, and still 669 m if the
> deadband is raised to 10 m without smoothing. With a 10 s mean it falls to
> 0.1 m. The app's test asserts phantom climb + descent < 20 m on 30 minutes
> of 3 m noise; the same seed gives 3093 m unsmoothed, so the test
> discriminates rather than merely passing.
>
> The 10 s window is the same baseline the grade term uses, and at 25 m/s it
> is 250 m of road — far shorter than any real hill, so terrain survives it.

Two known biases, recorded so they are not later mistaken for defects:

- **The `low_acc` skip biases `climb_m`/`descent_m` downward.** It cannot bias
  `dh_m`, which telescopes, but a skipped stretch's undulation collapses into
  one jump between good fixes. Tunnels and urban canyons lose real climb.
- **Altitude is WGS84 ellipsoid height**, not sea level. Differences are what
  matter, but the geoid-to-ellipsoid separation has a gradient of order
  0.1 m/km, so a 50 km leg can carry a few metres of systematic — the same
  order as the endpoint noise, and not worth correcting.

> **Open, 2026-09-25 — a privacy escalation to be ruled on, not assumed.** The
> speed-binned sums already let a reader bound how far the car travelled. A
> per-segment elevation-change *sequence* adds a relative terrain profile at
> 5-minute resolution, and distance plus elevation profile is a considerably
> stronger route fingerprint than distance alone. The owner's rule — no
> absolute position, otherwise only what the feature needs — permits it, and
> there are still no coordinates anywhere. It is recorded here because each
> addition has been individually reasonable while the cumulative picture has
> moved, and that is precisely the kind of drift nobody notices from inside.

**The "loose" accumulators are temporary, and that is a condition of keeping
them.** They exist solely to measure whether the steady-speed gate can be
dropped. The strict set *cannot* answer that: holding speed within 1 % over a
second removes exactly the variation a receiver lag would displace, so the
strict lag products are structurally blind to it. Without the loose sums the
1.8× time gain stays permanently unavailable and phase D's conclusion stays
resting on a modelled lag rather than this receiver's.

They come out once the lag is measured — a few weeks of data. Recorded as a
scheduled removal, because "only what is needed" is a rule about *now*, and
data collected past its purpose is collection by inertia.

**Keep the steady-speed filter** for this channel too. Dropping it buys 1.8×
the qualifying time and costs far more: an unknown receiver output lag turns
speed variation into one-signed bias — −2.5 psi at 0.5 s, −11 psi at 2 s.
Not tradeable until the lag is measured.

Random error is not the constraint; even a mediocre 1 Hz receiver reaches
3 psi in ~3 minutes of qualifying driving. Per-drive spread is ~3.5 psi, so
the channel is built by **pooling drives** — roughly a week for 3 psi, a
couple of months for 1 psi.

The feature must be optional and degrade cleanly: with GPS off or denied the
app loses only common-mode detection. `ACCESS_FINE_LOCATION` exists today
only in `:companion`, for reading a WiFi SSID, so this means a new
user-visible location prompt on an app that has never asked for one.

### Temperature

Drives carry candidate temperature channels from CAN. Store several per
drive and decide later which is best, once there is enough GPS data to check
against — `outside-air-temp-investigation.md` found no clean ambient sensor,
but `FrontInletAirTemp` reads true outside air when `FrontInlet < AvgCell`,
which is exactly the sustained-highway condition a qualifying drive already
requires.

Store, as `SG_` names decoded against `CODA-B-CAN.dbc` (all `(1,-128)` degC):

| signal | message | role |
|---|---|---|
| `FrontInletAirTemp` | `0x390` | best ambient proxy, when the gate below holds |
| `Cell_T_avg` | `0x382` | the gate's other half — pack-dominated when `FrontInlet ≈ Cell_T_avg` |
| `RearInletAirTemp` | `0x390` | second pack inlet; cross-check on FrontInlet |
| `OPAirTemp` | `0x391` | the factory's own outside-air estimate; poor, but it is the named one |
| `EvapAirOffTemp` | `0x391` | cabin air; rises with the heater, so it flags when HVAC is active |

`UnderHoodTemp` (`0x391`) is excluded — all-sentinel in every log, not wired
on this vehicle. The minimum viable set is the first three.

**Aggregate: median over the whole segment, plus the valid fraction.** Not
the mean (sentinel runs skew it), and not restricted to the kept samples —
temperature does not depend on the DEL filters, restricting it discards data
for no gain and leaves the field undefined when a segment contributes no
qualifying samples. Raw `0x80` is a sentinel and is excluded from the median;
the valid fraction records how much was dropped. Note this also discards
genuine 0 °C readings, which is acceptable here and should not be if the car
ever lives somewhere colder.

`Cell_T_avg` carries two more documented sentinels — `0x00` (standby) and
`0x33` (charge stopped), per its `CM_` in `CODA-B-CAN.dbc` and corroborated
independently at `chargepointcharge-analysis.md:143-144`. They decode to
−128 °C and −77 °C, so they are not temperatures at all. Exclude them, and
add a physical-plausibility backstop (roughly −40…+90 °C) on every channel so
an *undocumented* sentinel elsewhere cannot silently poison a median.
`UnderHoodTemp` is the precedent for why: it is 100 % sentinel on this car.

**The line between this and the validity gate.** Excluding a sentinel removes
a value that is not a measurement — that is decoding, and `valid_frac`
preserves the fact that it happened. The `FrontInlet < Cell_T_avg` gate
discards *real* measurements judged unrepresentative, which is analysis and a
tunable one. The first belongs at write time, the second does not. Keep the
distinction sharp or the gate will drift into the writer by analogy.

(The median is in any case robust below 50 % contamination, so sentinel
exclusion mostly protects `valid_frac`'s meaning and the pathological
all-sentinel case rather than the central estimate.)

**Do not apply the `FrontInlet < Cell_T_avg` gate at write time.** The gate is
a *setting*, so applying it on write would violate invariant 1 and freeze a
threshold into the archive. Store both medians and evaluate the gate at
ingest.

`DEL` cancels common-mode temperature by construction, so this is not for the
differential detector. It is for the common-mode work and for honest absolute
reporting.

---

### The `void` field

Each drive row carries `"void": null | ["esc_fault", "wheel_stuck"]`.
It fires on `SubFrameID 0x14` or on any wheel word reading `0x3FFF`.

**Void is per SESSION, not per row.** A fault in any one 5-minute segment
condemns the whole session: not learned from, not in any window, not
fast-pathed. It also does not close the `undo` window. That follows from the
owner's rule — a sensor failing intermittently produces frames that pass
every per-sample check and are still wrong, so dropping only the segments
that announced themselves keeps exactly the data the announcement warned
about.

**Traction control is already excluded, and NOT by anything written for it.**
*Measured corpus-wide 2026-09-26, `artifacts/tpms_tc_event_exposure.py`.* The
ESC announces a TC event by switching this byte to `0x20`, which the
`SubFrameID == 0` gate rejects for validity reasons. Across both log roots —
1,102 files, 27 GB — a burst appears in **15 files, 15 distinct sessions, 16
bursts, 24.3 s of traction control in 221 days**. Running the real `proc`-3
filter chain on every one of those files:

| qualifying samples in the 15 files | inside burst + 2.5 s | inside burst + 5.0 s |
|---|---|---|
| 20,683 | **0** | **0** |

Zero at twice the lead-in window, so a few seconds of time-origin error cannot
change it. **And the sub-frame gate is not what achieves this.** The filters
exclude the whole neighbourhood of a TC event for reasons that have nothing to
do with TC: a car that is spinning a wheel is not simultaneously straight, off
the brakes, under 20 Nm and holding speed to 2 %. So the gate's TC side effect
is real and it is redundant — it can be reasoned about as validity alone, which
is what it was written as.

*This corrects a figure recorded earlier the same day. A single-drive estimate
put the residual exposure at "about 0.13 % of that drive", from the ~2.5 s during
which `0x300` B4-B5 ramps before `0x212` responds
(`notes/traction-control-analysis.md` Phase 2b). Both halves were wrong: one
drive is not a characterisation, and fraction-of-drive-time is the wrong
denominator, because a sample the filters already reject cannot contaminate
anything. The right denominator is qualifying samples, and the answer is none.*

*Incidental, and it settles an open question in `CODA-D-CAN.dbc`:
`coda_20260422_102839_T0.log` carries TWO bursts, 99 s and 266 s in. "One block
per capture" is therefore not a rule.*

*Limit of the result: `0x20` is the ESC announcing a TC event. Intervention that
never announced itself would not appear in this scan. What is established is
that whenever the ESC does announce one, no qualifying sample is near it.*

**Count fault values only on buses that also carry `0x208`.** C CAN's own
`0x200` — a different message sharing the ID — has B0 spanning `0x07`–`0x1B`,
which *contains* `0x14`: 15,113 frames of it corpus-wide. An unscoped count
would void healthy drives on a fault code belonging to an unrelated message.
This is the same conflation that produced a 0.39 % answer where the truth was
0.052 %, and it is why bus identity comes from content and never from a
channel number.

**Ratios are still stored on a void row.** Void is a verdict about trust, not
a reason to discard a measurement that is regenerable from the log anyway.

### Rows recorded before any calibration

Drives captured before the first `set` are **kept**, in a file whose first
record is `{"type":"precalibration",...}`. The role is carried by that
record, not by the file's name — identifying a file's purpose by a magic
timestamp fails the same way positional corner fields do.

Such a file is never an epoch: no baseline, no verdict, no undo target. The
detector ignores it. It is retained permanently and used only for
common-mode work.

This exists for one specific and non-repeatable opportunity. If GPS bringup
and the first calibration happen on the same visit, the drive to the air pump
and the drive back bracket a ~9 psi **common-mode** step with GPS on both
sides — a direct calibration point for the channel of §7, which is otherwise
uncalibrated and cannot be manufactured later without deliberately deflating
all four tyres.

---

## 8a. Handoff — what build 29 must change, 2026-09-27

Written for the app session, which is not reachable by message. **`AGENTS.md`
says a returning session reads the spec before touching the implementation; this
is that.** Ordered by how fast each one decays.

1. **Drop the dominant-bus idea entirely — both places.** Owner's direction.
   - `WheelRatioExtractor.extractSegment()` and `.extractSession()` call
     `dominantBus(...)` per id (`:405–407`, `:427–428`). Replace with the anchor
     rule of §1: identify D CAN from `{0x308, 0x312, 0x325, 0x330, 0x580}`,
     require two distinct ids on the winner, treat another channel as ambiguous
     **only if it also has two distinct ids** (one stray frame must not reject a
     capture), require all four signal ids on the winner, and reject with a
     stated reason otherwise.
   - **`GpsRateAccumulator.onDominantBus()` (`:241–245`) is the more important
     one** and needs the same rule applied *live*, from anchors as frames
     arrive. Measured, it flips 11,468 / 14,128 times in one 5-minute segment
     and accepts ~60 % of frames. It has not corrupted the GPS block — see §1
     for why `N` is unaffected — but it does not do what its name says.
2. **`proc` 3 now includes D CAN pinning** (§4 table). This was free only because
   build 29 had not shipped. **It stops being free the moment it does.**
3. **The parity references are stale**, because pinning moved them:

   | | n | `DEL` | `F/R` | `L/R` |
   |---|---|---|---|---|
   | `coda_20260926_155726_T0` | 1275 | 0.999223 | 1.004553 | 1.000014 |
   | `coda_20260926_155726_T1` | 417 | 0.999191 | 1.004508 | 1.000232 |
   | `coda_20260926_155726` pooled | 1701 | 0.999221 | 1.004541 | 1.000082 |
   | `coda_20260926_181156_T0` | 541 | 0.999208 | 1.004252 | 1.000613 |
   | `coda_20260926_181156_T1` | 3610 | 0.999277 | 1.004712 | 1.000063 |
   | `coda_20260926_181156_T2` | 0 | — | — | — |
   | `coda_20260926_181156` pooled | 4298 | 0.999266 | 1.004661 | 1.000138 |

   **A parity reference must name its bus.** A 5e−7 tolerance is ten times finer
   than the bus disagreement, so a test that does not pin the copy verifies "we
   picked the same one", not "we decode identically". These are D CAN.
4. **`PUT /files/<path>` and `GET /tree`** per §4 — the round-trip that lets a
   corrected row reach the car. `/files` and `DELETE` do not change.

   > **LANDED and exercised on the car, build 30, 2026-10-04.** `GET /tree`
   > returns the recursive listing, `GET /files/tpms/<name>` fetches a fragment,
   > and a `PUT` round-tripped byte-identical. `PUT` is scoped tighter than this
   > item asked — `tpms/<name>.jsonl` only — and it rejects a repeat name with
   > 409. See the measured table in §4.
5. **A rejected capture needs a reason, in a `reject` field — NOT in `void`.**
   With D CAN required, a capture without it yields no row, and if a dongle
   fails the app goes silent. Record why, so a missing row is explicable rather
   than mysterious:

   ```
   "reject": null | {"code": "no_d_can"|"d_can_ambiguous"|"d_can_incomplete",
                     "why": "..."}
   ```

   > *Corrected 2026-09-27. This item first said to record it as a `void`
   > reason, which was wrong, and the app session caught it before building.*
   > `void` means **the ESC's own sensors misbehaved** (`esc_fault`,
   > `wheel_stuck`) and it condemns the whole session on purpose — because an
   > intermittently failing sensor emits frames that pass every per-sample check
   > and are still wrong, so dropping only the segments that announced
   > themselves keeps exactly the data the announcement warned about. **A
   > missing D CAN makes no claim about the sensors at all**: the dongle or
   > logger lost the bus (66 such events in `reverse-it-e1`'s sweep) or the car
   > was keyed off. There is no plausible-but-contaminated data to protect
   > against — there is simply no data. Voiding would discard the good segments
   > of the same drive to punish a segment that reported nothing.

   Two invariants worth asserting rather than assuming:

   - ~~**`reject` and `void` are mutually exclusive.**~~ **WITHDRAWN the same
     day, and it was wrong.** *The app session caught it before asserting it.*
     The two detectors are scoped to **different buses on purpose**: `reject`
     fires when D CAN cannot be identified, while faults are counted on **any**
     bus that also carries `0x208`, the gateway's B CAN copy included. So a
     missing D CAN dongle with `0x14` on the rebroadcast copy yields
     `void: ["esc_fault"]` **and** `reject: no_d_can` together, and **that pair
     is correct**. The gateway does not invent the fault flag: it is the ESC
     reporting, and it should still condemn the session. My claim assumed fault
     detection was scoped to D CAN. It is not, and scoping it there to buy the
     symmetry would discard real fault evidence.

     **The asymmetry is the design, not an inconsistency.** The two paths have
     opposite error preferences: a missed **fault** means bad data is accepted
     and trusted, so fault detection is deliberately **inclusive**; a missed
     **measurement** merely wastes a drive that the log can reproduce, so
     measurement is deliberately **strict**. Opposite costs, opposite scoping.
   - **A reject row still inherits its GPS block.** It is `partial: false` with
     `n: 0`, so it outranks every partial for that log — but §4's donor-rank
     rule takes the block from the best-ranked row that *has* one, so the
     per-minute partials still supply it. Position known, ratios null, which is
     the right outcome and needs no special case.

   The shapes differ from `void` deliberately: `void` is a **set** of conditions
   that can co-occur, `reject` is a **single** mutually-exclusive reason with a
   human-readable note. Schema stays 2 — an added nullable field.
6. **`WheelRatioExtractor.kt:189`** still says the `0x1C`/`0x1E` block is "often
   a minute or more into a capture, since logging starts at screen-on". It is a
   mid-capture **key cycle**; see §1.

### Added later on 2026-09-27, after the steering and log-repair work

7. **`proc` 3 is now stamped as 3 by the corpus pipeline.** It had been emitting
   `proc: 2` for the proc-3 rule set, so every reference CSV generated before
   this carried the wrong rule-set id. The app must tag its rows **3**. This is
   the one item here that can corrupt data rather than merely mislead: the
   fragment store's dedupe ranks by `proc`, so a row tagged 2 and a row tagged 3
   describing *identical* processing resolve against each other on a false
   distinction.
8. **The parity references in item 3 are UNCHANGED by the log repair** — checked,
   not assumed. 55 captures had a backward wall-clock step repaired on disk that
   day and `canre`'s BUSMASTER parser was fixed to stop silently dropping
   negative timestamp components, but none of the five chunks behind those
   references contains a single negative-stamped line, and both pooled rows come
   out bit-identical before and after. **Do not re-derive them.**
9. **The steering centre estimator stays exactly as specified**, and §1 now says
   why on measured grounds rather than on two sessions: `0x080` is relative,
   re-zeroed only at EPS power-up, never while the car is moving, and no
   absolute source is broadcast on any bus. **Build nothing for the sub-5°
   silent re-zero** — owner's decision, it is an accepted limitation because no
   such event has ever been observed.
10. **If the centre is ever split per power cycle**, there is now a marker inside
    `0x080` itself that needs no second id: a silence > 0.3 s followed by the
    message counter in {1, 2} **and** raw == 20000. The counter alone is not
    enough — logger frame drops across the counter wrap mimic it.
11. **The Android logger WAS the source of the timestamp defect — fixed in
    build 23, and confirmed 2026-10-03. Nothing to do.** It used to write tokens
    with negative components at chunk starts (e.g. `00:00:-13:-6809`), costing
    the corpus 4.8 M silently dropped lines across 734 of 1,096 Coda captures
    and leaving 52 captures with a clock stepping backwards by up to 236.7 s.
    The parser fix and the on-disk repair of 55 captures were the
    `CAN messages inventory` session's.

    > *This item first said stopping the logger was still the app's to do. It
    > was already done:* `BusmasterWriter` had measured offsets from file-open
    > time, so a frame received before a chunk roll but written after it went
    > negative; build 23 took the origin from the first frame written, with
    > monotonic tick offsets and a pipeline lock emitting in stamp order.
    >
    > **Confirmed on the 14 captures from 2026-10-02/03**, the first driving
    > since the corpus cutoff: zero negative-stamped lines, zero backward steps,
    > and a tick profile of 8.2–12.4 % multiples of 10 against 52–57 % on the
    > retired millisecond path — so genuine 0.1 ms ticks, not merely clean by
    > luck. **Every chunk opens at `00:00:00:0000`, including every `_T1`/`_T2`/
    > `_T3` roll**, which is the test that matters: every residual negative stamp
    > found earlier sat in a `_T1` or higher and never in a `_T0`, so the
    > boundary that was still producing them is now exercised and clean.
    >
    > **The forward test for any future capture is the tick profile, not the
    > first line.** Under 20 % multiples of 10 means real 0.1 ms ticks, hence
    > build 23 or later. A first line of `00:00:00:0000` is necessary but NOT
    > sufficient — 22 captures in the corpus open that way and six predate the
    > fix by months, because a millisecond-resolution writer lands on the origin
    > instant about one chunk in ten.

*Open and NOT to be implemented yet, owner's call:* the published 3σ of 2.71 psi
is confirmed for a baseline one day old (2.72 psi measured by an independent
pair-separation estimator), but it degrades with baseline **age** — about 5 psi
at 30–60 days and 7.5 psi beyond 60. If the baseline is frozen from the first
K drives and never refreshed, its effective threshold grows. Refreshing rather
than freezing is the obvious answer and is not yet decided.

---

## 8. Open

- **A/B deflation test** to pin the psi scale, which rests on one gauge
  reading. Also the only way to measure a *rear* corner's response — every
  event in the corpus is front-left.
- ~~The SeaDrive path check in §4~~ — **answered 2026-09-26, and the answer
  was worse than either outcome anticipated.** SeaDrive does reach
  `CodaLogs/tpms/`: the first calibration file arrived in the library. It
  arrived at 127 bytes, frozen mid-append, and was never refreshed. So the
  path works and uploads exactly once, which is the finding the fragment store
  of §4 exists to answer. The check as written could only have returned
  "arrives" or "does not arrive"; the truth was "arrives, once" — a state the
  question did not have a slot for.
- **`BusmasterWriter` buffer depth at force-stop**, per §4. Bounds how much of
  a killed segment is regenerable from the log.
- **Tyre rotation and new tyres** permute the per-wheel biases wholesale and
  require a fresh calibration. Not tracked in the car's database, so this is
  a matter for the owner to remember.
- **Standing assumption: the gateway reproduces rebroadcast values faithfully.**
  §1's bus-choice result rests on it, and it is not a contingency — **roughly
  half the corpus already comes from the GWM's copy rather than the
  transmitting module's**, selected per capture by a frame-count margin that is
  frequently zero or one. **It is an assumption about hardware, not a property
  of the algorithm**, and it would fail *silently*: the pipeline would keep
  producing plausible ratios from the altered copy. Re-measure it after anything that could change a
  gateway's behaviour — a GWM swap, a firmware difference, or running the
  pipeline on a different car. The Vtrux is the standing example that this is
  not paranoia: its VCM **substitutes** content rather than rebroadcasting it,
  masking `0x0C1`/`0x0C5` wheel speeds to zeros. *Recorded as a standing
  assumption at `reverse-it-e1`'s suggestion, 2026-09-27, rather than left as a
  closed measurement.*
- **Proposed for `AGENTS.md`, owner's call** (raised independently by
  `reverse-it-e1` and this session): *a bus discriminator must be shown to
  SEPARATE* — score it on both buses and require one side to be empty, or name
  the ids that are exclusive and assert they are. The existing rule says
  identify a bus by content rather than channel number, and both sessions
  followed it and still got the bus wrong, because the content chosen was
  present on both buses. Unlike everything in "Filters that fail silently",
  which produces a wrong *quantity*, a null discriminator produces a wrong
  *label on a right quantity* — so there is no residue to notice. For the Coda
  the exclusive set is already written down (`0x308`, `0x312`, `0x325`, `0x330`,
  `0x580`), so the rule costs nothing here.

## Artifacts

All in `artifacts/`: `tpms_app_prototype.py` (executable spec),
`tpms_corner_inversion.py`, `tpms_gps_resolution.py`,
`tpms_filter_sensitivity.py`, `tpms_wheel_ratio_trend.py`,
`tpms_fill_events.py`, `tpms_sensitivity.py`, `tpms_direct_sweep.py`,
`tpms_common_mode_accel.py`. See `artifacts/README.md`.
