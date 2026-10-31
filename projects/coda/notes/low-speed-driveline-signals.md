# What the Coda's CAN bus can and cannot resolve at very low speed

Measured 2026-09-24 to answer one question — *can a log distinguish "driveline lash held
closed" from "lash taken up on tip-in"?* — but the limits below apply to anything asked
about the first metre of motion: creep, launch, rollback, clunk, standstill preload.

**Headline: three of the four plausible channels are blind in this regime, and two of
them are blind in ways that look like data rather than like absence.**

Script: `dlcm/artifacts/lash_takeup_probe.py`. Corpus: recent Coda D-CAN drives on
`the Linux box`.

---

## The channels, measured

| signal | ID | bus rate | resolution | usable below ~2 km/h? |
|---|---|---|---|---|
| `Motor_Speed` | `0x1C0` | 100 Hz | 1 rpm | **partly** — see below |
| `InputShaftSpeed` | `0x308` | 50 Hz | 1 rpm | no — redundant |
| `WheelSpeed_LF/RF` | `0x200` | 100 Hz | 0.5 wheel rpm | **no** — hard cutoff |
| `WheelSpeed_LR/RR` | `0x208` | 100 Hz | 0.5 wheel rpm | **no** — hard cutoff |
| `Long_Accel` | `0x330` B7 | 50 Hz | 0.08 m/s² | **yes** |

### Wheel speed has a hard low-speed cutoff

The ABS channels do not report small non-zero speeds at all. The **smallest non-zero value
ever observed** is 15.5 wheel rpm on the front (driven) pair and 8.0 on the rear, and
departures from rest jump straight to those values rather than passing through smaller
ones. At the DBC's 0.0567 km/h per count / 2 counts per wheel rpm, that is:

- front: **≈1.76 km/h**
- rear: **≈0.91 km/h**

Below that they read exactly `0` — not noisy, not missing, *zero*. This is the trap: a
stationary car and a car moving at 1 km/h produce identical wheel-speed data, so any
method that integrates or differences wheel speed in this regime silently measures
nothing. In particular, **motor-vs-wheel differential angle cannot measure lash**, because
the wheel signal does not exist yet at the moment the lash closes.

### `InputShaftSpeed` is `Motor_Speed` again

`0x308` carries an **identical value set** to `0x1C0` at half the sample count. It is the
same quantity rebroadcast, not an independent shaft measurement, and it adds nothing. (The
DBC's "ratio to motor RPM = 2.000, on both Vtrux and Coda regardless of gear ratio" is an
encoding artifact and reads as a physical claim — it is not one.)

### `Motor_Speed` resolves the value but not the timing

It is on the bus at 100 Hz and reads exactly `0.0` at standstill (10,057 consecutive
samples in one drive), with a 1 rpm step near zero — so as a *value* it is good down to
walking pace and below.

But its **content updates on sensor edges, not on the bus schedule**. At 20–30 rpm the
same value is held for **100–140 ms** across 10–14 consecutive frames before stepping.
The bus rate is 100 Hz; the information rate at low speed is closer to 8 Hz and falls
further as speed falls.

Consequence: any event shorter than one update interval is invisible. Lash take-up at
those speeds lasts tens of milliseconds, so it falls inside a single sample. Fitting a
two-slope "knee" to the rise — the natural way to look for the free-spin-then-impact
signature — was tried on 13 corpus departures and returns noise: negative "fast" slopes,
gain ratios from 0.1× to infinity. **Do not try to read lash, or any other fast transient,
out of a low-speed rpm trace.**

Motor-to-wheel ratio, if needed: **6.576** median motor rpm per rear-wheel rpm, regressed
from steady cruise (p25 6.54, p75 6.60 in the cleanest log).

### `Long_Accel` is the one channel that works

`0x330` B7, 50 Hz, 0.08 m/s² per count, zero at raw 123, raw ≥ 200 invalid (see the DBC
comment for the scale's ±12 % uncertainty — the *zero* and the role are confirmed, the
scale is approximate).

Noise floor, measured as **sample-to-sample step** rather than as standard deviation
(standing variance is dominated by road grade, which is not noise):

| condition | median step | p95 | max |
|---|---|---|---|
| at standstill | 0 counts | 1 | 29 |
| moving, >300 rpm | 1 count | 3 | 21 |

So **a single-sample step of ≥4 counts (0.32 m/s², ≈0.033 g) is real signal.** A driveline
clunk is on the order of 0.05–0.15 g = 6–18 counts, comfortably above that.

**Caveat, and it is asymmetric.** At 20 ms sampling an impact shorter than one sample is
aliased, so the recorded peak understates the true one by an unknown factor and can
occasionally fall between samples. A spike is therefore **strong evidence of a clunk**;
its absence is **weak evidence of no clunk**. Judge across several events, never one.

---

## Reference: what "lash held" looks like

Every drive in the corpus before 2026-09-23 23:58 ran a standstill creep preload of 345
internal, which holds the lash closed. Those departures are the control, and they show
**no jerk transient at all** — 1–2 count `Long_Accel` steps through the departure.

The first drive at the reduced preload (50 internal) shows the same 1-count steps on its
two genuine zero-pedal departures. Suggestive that the reduced preload still holds; **not
settled**, because n=2 for the case that matters. See
`dlcm/dlcm-cal-flash-campaign.md` §3.

---

## Practical consequences

- **To test whether a calibration took effect at standstill, read the commanded torque,
  not the motion.** `0x212` published torque at rest with **the brake released** is a
  single unambiguous number. With the brake applied the brake map zeroes creep, so it
  reads 0 regardless and proves nothing.
- Standstill populations are **small and transient-heavy**. Check n, and look at the
  values, before trusting a median — a gear the car was only briefly in can produce ten
  samples of which six are mid-decay ramp-downs.
- If a future question needs true low-speed kinematics, nothing currently on the bus
  provides it. The gap would have to be closed with added instrumentation, not with a
  better decode.
