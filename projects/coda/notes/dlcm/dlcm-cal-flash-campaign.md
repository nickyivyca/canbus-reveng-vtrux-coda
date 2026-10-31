# DLCM CAL flash campaign — what is on the car, and how each change was verified

Six CAL-only flashes were made to the Coda's DLCM between 2026-09-20 and 2026-09-24,
all through the OBD Diag-CAN gateway at Omitec block pacing. **PROG has never been
written by our tooling.** This file is the record of what went on the car, what each
change measurably did, and how each was independently checked before and after.

Plans: `../plans/dlcm_zero_crossing_cal_proposal.md` (the rate-limiter work),
`../plans/dlcm_creep_and_one_pedal.md` (creep and regen).
Mechanism and table semantics: `dlcm-torque-limiter-code-trace.md`.

---

## 1. The verification protocol

Two sessions work this in parallel and they are deliberately not the same session:

- **The in-car session** owns the car, the flashes and the DTC reads. It proposes a
  change list and builds a candidate image.
- **The analysis session** owns the logs and the models. It rebuilds the candidate
  **from the descriptors and the stated rule**, without calling the proposer's
  generator, and compares md5. It then measures the resulting drive.

**The user is the gate between the two.** A matching md5 is evidence the change list
says what it means; it is not permission to flash.

This has caught real errors in both directions — see §4 — so the cost is paid for.

### What an independent rebuild actually checks

Three things, and the third is the one that nearly went wrong:

1. **The rule reproduces the bytes.** Rebuild from `(descriptor, rule)` and compare md5.
2. **Both copies are written.** Every table the torque path reads has a mirror in the
   block-2 monitor (see `dlcm-torque-limiter-code-trace.md`). Every edit must land in
   both.
3. **Nothing else moved.** `omitec_sim.py` writes *stock base + patches*, so a flash
   necessarily carries every earlier accepted change forward or silently reverts it.
   Since 2026-09-23 the patch set is derived as the diff from stock to a target image
   (`--target-image` / `patches_from_target()`), which carries them by construction
   rather than by a hand-maintained literal.

That third property was proved rather than assumed, on the first flash that used it
[measured 2026-09-24, `artifacts/verify_c1_creep50.py` phase 2]:

| step | words changed |
|---|---|
| FLOOR40 + speed limb 40 | 14 |
| negTrqLast scale-3 | 8 |
| C1 creep-50 | 60 |
| **stock → car, total** | **82 words / 90 bytes** |
| **unexplained by any accepted change** | **0** |
| **accepted changes missing from the car (silent revert)** | **0** |

---

## 2. Image lineage — verified against the images, not transcribed

All under `artifacts/`. Each image is the one actually on the car after that flash.
**Every md5 and every byte count below was recomputed from the files on disk** against the
in-car session's flash-side record (2026-09-24); all seven agree.

| # | when | change | image | md5 | B vs stock | B vs prev |
|---|---|---|---|---|---|---|
| — | 2026-07-21 | FLOOR5 | `cal_as_flashed_20260721_floor5.bin` | `97e4046042f7f97b…` | 2 | 2 |
| — | 2026-09-20 17:21:18 | FLOOR20 | `cal_as_flashed_20260920_floor20.bin` | `dd2cfbdf3489479a…` | 8 | 8 |
| 1 | 2026-09-23 22:51–22:53 | FLOOR40 + speed limb 40 | `cal_as_flashed_20260923_floor40_speedlimb40.bin` | `baf6061d96c1c5a5…` | 14 | 14 |
| 2 | 2026-09-23 23:36–23:38 | negTrqLast idx0..3 ×3 | `cal_as_flashed_20260923_negtrq_scale3.bin` | `1224c0c1647b127c…` | 22 | **8** |
| 3 | 2026-09-23 23:55–23:58 | C1 creep 345/449 → 50 | `cal_as_flashed_20260923_c1_creep50.bin` | `8219af8dbc3c6364…` | 90 | 68 |
| 4 | 2026-09-24 00:23–00:25 | launch rate | `cal_as_flashed_20260924_launchrate.bin` | `5ba36b2db886dfdb…` | 96 | 14 |
| 5 | 2026-09-24 00:43–00:45 | C2 one-pedal −1562 | `cal_as_flashed_20260924_onepedal1562.bin` | `235df55d130d8f38…` | 456 | 360 |

**Flash 2 is 8 patch pairs but only 8 bytes.** Negative values change only ONE byte of a pair
when the high byte stays `0xFF`, so any "two bytes per pair" assertion is wrong. Check
containment, not counts.

The chain is self-consistent in a way that is hard to fake: each flash's own coverage check
(differing bytes found on the module before writing) equals the **previous** image's
stock-diff — flash 4 reported 90, which is C1's 90; flash 5 reported 96, which is launch
rate's 96. Cohort boundaries for log analysis are in `../../logs/README.md`.

**Flash 3 has no bus capture** — the logger was not running (user-confirmed); the only record
is `artifacts/flash_negtrq_scale3_20260923_obd.log`. All five flash logs are
`artifacts/flash_*_2026092[34]_obd.log`.

### The invocation, and why each flag is there

All five: CAL-only through the OBD/Diag-CAN DB9, Innomaker gs_usb, tester `0x7E0` / DLCM
`0x7E8` across the GWM. Every one: 456 blocks, 114,688 bytes, SecurityAccess level `0x01`,
erase 2.7 s, verify `7101ff010000000c`, no NRCs, no retries, ~132 s.

```
--segments cal --block-delay-ms 217 --tx-stmin-ms 1.1
--ignition-poll-interval 0 --startup-delay 0
```

**Four traps, each of which cost something.** The operational detail lives in
`../plans/dlcm_next_incar_session.md`; these are here because they bear on whether a flash
can be trusted:

- **`--ignition-poll-interval` defaults to 3.0 and opens a SECOND bus handle.** The Innomaker
  is single-channel, libusb refuses with Access denied, and the flash dies before sending
  anything. Effectively mandatory on gs_usb and undocumented as such. Cost one aborted
  attempt.
- **`--segments` defaults to `prog,cal`.** Forgetting `--segments cal` erases PROG. This is
  the single most destructive available mistake and nothing in the tool defends against it.
  Since 2026-10-16 `projects/coda/tools/flash_cal.py NAME` flashes a named complete image,
  CAL only, with the flags below as its defaults; `omitec_sim.py` itself still defaults to `prog,cal`.
- **A preset must carry EVERY deviation from stock**, because a flash writes stock base plus
  patches — otherwise it silently reverts earlier work. `check_base_covers_car()` catches
  it; `--target-image` removes the class of error entirely.
- **The "two bytes per pair" assertion** described above.

## 3. What each change did, measured

### Flash 1 — FLOOR40 + speed limb 40

V-curve idx2..6 → 40 and the speed limb's low end 20 → 40, both copies.

- At-speed rising `t(0 → +80 raw)`: **0.102 → 0.060 s** median, n=37 pooled over two
  drives, p25 0.040. Predicted 0.050; the 20 ms publish grid explains 40/60.
- Standstill tip-ins: **16 → 32 raw/sample**, 5 of 5.
- Creep and coast unchanged, as intended.

### Flash 2 — negTrqLast scale-3

idx0..3 ×3, both copies, giving `[-30, -30, -21, -12, -15, -15, -20, -40, -100, -100]`.

- Lift-off t90: **0.94 → 0.58 s**. The model matches all 5 events within 10 ms when run
  from each event's own start torque.
- Notch time **0.23 → 0.12 s**, as predicted.
- Rising side unchanged (control).
- n is small: 3 after, 2 before.

### Flash 3 — C1, creep preload

Creep 345 (D) / 449 (R) → **50 internal**, and the brake map's low-pressure creep cells
scaled by the same per-gear `k`, both gears, both copies. 60 byte-pairs.

**Intent, in the user's words** — this was mischaracterised as clunk mitigation when it
was first written up, and the correction matters for judging the result: *"it already
creeps to preload the drivetrain. I just want to disable creep while leaving the preload
part of it active, without completely disabling it."* So: stop the car rolling at
standstill, keep enough torque to hold driveline lash closed. Hill rollback increases;
the user explicitly accepted that.

Measured on `coda_20260923_235957_T0` [`artifacts/c1_drive_verify.py`]:

| test | before | predicted | measured |
|---|---|---|---|
| D, at rest, pedal 0, brake **released** | 137 raw | 20 | **19** (282 of 292 samples exactly 19) |
| R, same | 180 raw | 20 | **18** |
| D, at rest, pedal 0, brake **held** | 0 | 0 | 4 |

**The brake-held figure proves nothing** and must not be used: the brake map zeroes creep
in both regimes, so only a brake-released stationary stretch tests the change.

**Do not read R off a median.** The drive contains only 10 R/at-rest/brake-off samples —
0.20 s total — and 6 of them are mid-decay transients caught during ramp-downs (188, 167,
385, 305, 245, 212). The only settled run is four consecutive samples at 18. A median over
all ten reads 177 and looks like a failure; it is an artifact of n.

**Creep is gone.** Two departures had zero pedal and brake released, both at 19 raw. The
motor reaches ~6 CAN rpm (≈0.1 km/h at the wheel) and at t=25.45 it returns to 0 and
**stays** there. A creeping car does not arrest itself on the flat.

**Bearing on the preload question** [interpretation, flagged as such]: at 19 raw the
driveline rotates a few rpm and then stops. That is take-up without propulsion, which is
what the user asked for. No clunk signature either — both zero-pedal departures show
1-count `Long_Accel` steps, identical to the creep-345 control. One 5-count step exists at
t=52.18 but that is a 22.8 % pedal departure, not a gentle one. **Suggestive that 50 is
enough; not settled** — n is 2 for the case that matters.

Launch to 400 raw: **0.220 s median, n=6**, and unusually tight — 5 of 6 within 1 ms,
which is the fingerprint of a rate-limited (deterministic) path.

The four `coda_20260924_000223_T*` chunks are **PRND=P end to end with the motor at 0 for
every sample** — post-drive parked session, no road content. Don't look for driving data
in them.

---

### Flash 4 — launch rate

Speed limb 40 → 100 both copies; V-curve idx5,6,7 → 100 and idx8,9 → 120 both copies.
14 byte-pairs. The V-curve's idx2..idx4 (x = −80, −70, 0) were deliberately left at 40.

Measured on `coda_20260924_002356_T0/T1`:

| test | before | measured after |
|---|---|---|
| `t(0 → +80 raw)`, ≥500 rpm | 0.060 s (n=37) | **0.040 s** (n=16, p25 0.020) |
| launch to 400 raw (own extractor) | 0.220 s | **0.080 s** (n=3) |
| standstill published rise | 32 raw/sample | **80 raw/sample** |
| creep at rest, brake off, D / R | 19 / 19 raw | 19 / 19 raw (control, unchanged) |

**The zero-crossing metric is now saturated, and this closes the question permanently.**
At 100 internal/tick the published rise is 80 raw per 20 ms sample — 100 × 2 ticks × 0.4,
confirmed in the traces, which step +80 exactly, sample after sample. So `+80 raw` is now
**one publish sample**. Median 0.040 s is two samples and p25 0.020 s is one.
**`t(0 → +80)` cannot go below 0.020 s at a 50 Hz publish rate.** Raising the V-curve further
in this region cannot show up in this metric and is very unlikely to be felt. The user had
been planning a further increase and dropped it on this basis.

A framing error worth recording, because it nearly went into the notes as a fact: this flash
was described as leaving "the zero-crossing region untouched" because idx2..idx4 were not
edited. That is wrong. **`+80 raw` is 200 internal**, so the metric spans idx4 (x=0), idx5
(x=80) and idx6 (x=200) — two of which were raised. The check in
`artifacts/verify_launchrate.py` prints "zero-crossing region idx2..idx4 unchanged: True",
which is a region defined by x ≤ 0, **not** the region the metric measures. A passing check
answered a different question than the one being asked of it.

### Flash 5 — C2, one-pedal regen

Coast row idx2..9 → `[−235, −1328, −1562 ×6]`, scaled from the brake map's own full-press
row by 1562/1150 so the low-speed fade keeps the factory profile; then every D brake cell
set to `min(current, coast)` at the same speed. 192 byte-pairs (16 coast + 176 brake), both
copies of both maps.

Option A was chosen deliberately: **brake pressure no longer modulates regen.** From 465 rpm
up every brake row is byte-identical to the coast row; the only cells that still differ are
the 22 creep cells (11 rows × 2 columns) at 0 and 291 rpm. The brake pedal contributes
friction only above 465 rpm. This is an accepted consequence, not a side effect.

The mandatory coupling — any coast deepening must also take every brake cell to
`min(brake, coast)`, or light braking would *reduce* regen — was applied against the current
image rather than stock, and **C1's creep scaling survives untouched**: C1 changed 10 D-brake
cells per copy, C2 disturbs 0 of them. That is structural rather than lucky. Those cells sit
at y=0 and y=640 where the new coast row is still *positive* (50/40), so `min()` can never
reach them.

User verdict: regen magnitude is right, no more wanted. What they *did* object to is pedal
resolution — see `pedal-map-envelope-design.md` section 11.

## 4. Errors this process caught

Recorded because each was plausible, and three of the four were only caught by rebuilding
rather than reviewing.

**A stale base image inverted the sign of a prediction.** `one_pedal_model.phase6` computes
"today's crept launch" against the FLOOR20 image, which still has speed limb 20. It
therefore credited C1 with the FLOOR40 gain and reported launch *improving* 0.340 → 0.260 s.
Holding the image fixed, dropping creep is always **slower**
[`artifacts/verify_c1_creep50.py` phase 4]:

| image | creep 345 | creep 50 |
|---|---|---|
| floor20 | 0.340 s | 0.480 s |
| negtrq (pre-C1) | **0.180 s** | 0.240 s |
| C1 (on car) | 0.200 s | **0.260 s** |

The true prediction was **0.180 → 0.260 s: C1 costs ~80 ms to 400 raw.** The user
subsequently drove it and reported exactly that — *"still a slow ramp when I apply the
throttle... better than before, but still too slow"* — which the corrected sign predicts
and the original does not. **The FLOOR35-vs-FLOOR40 V-curve override that was suspected at
the time is a red herring: 0.260 s either way.** The stale base is the whole effect.
`phase6` has not been fixed; only the interpretation has.

**An apparent copy mismatch that was an axis artifact.** The C1 change-list output printed
`speedlimb L1 [40, 40, 1000, 1000, 1000]  L2 [1000, 40, 40, 1000, 1000]` and looked like
the live/monitor mismatch the whole protocol is built to prevent. It is not. The two
tables have **different x-axes** — L1 `[0, 128, 256, 10240, 14720]`, L2 signed
`[-256, -128, 128, 256, 14720]` — and agree at every breakpoint they share. Compare the
copies **as functions of speed**, never index by index: `max |L1(|s|) − L2(s)| = 0.000`
across the whole axis.

**"Raise the low-speed band" is the wrong implementation of itself.** Rebuilding a later
change list, the analysis session implemented the rule as *raise every speed-limb entry
with `|x| ≤ 256`* and produced 17 byte-pairs against the proposer's 14. The rebuild was
wrong, not the proposal: the extra three entries were the `1000`s at `x = ±256`, which are
"released" and would have been pulled **down** to 100 — a regression above the 116 rpm
breakpoint, not a launch gain. The correct rule is *only the entries currently at the
low-rate value*. The plain-English description of the edit and its correct implementation
differ, and the difference is a regression.

**A rejected approach, kept so nobody re-proposes it.** For the launch-rate change the
user first chose to narrow the speed limb's low-rate *band* by moving its x breakpoints down,
rather than raise its value. It was built, all guards passed, and then it was measured:
0.250 → 0.200 s only. The reason is the same one that makes the saturation argument work — a
launch reaches 400 raw in ~110 ms, by which time the car has only reached ~10 CAN rpm, so a
knee anywhere above that is never crossed while the launch is happening. Traces with and
without the narrowing are byte-identical through t=0.09. **Within a launch window a
speed-indexed breakpoint is nearly irrelevant; only the rate VALUE in the 0–10 rpm band
matters.** Kept as `artifacts/narrow_speedlimb_change_list.py`.

**A verdict computed over too few samples.** See the R-gear note in §3: `median` over 10
transient-contaminated samples reported a clean pass as a failure. Check n before trusting
a summary statistic on a standstill population — they are small and transient-heavy.

---

## 5. Facts established along the way

**DTCs are set by the reflash, not by driving.** Seven DLCM codes — C0044 `0x13`,
P0A05 `0x93`, P3115 `0x04`, P3103 `0x00`, U0110 `0x08` ×2, C2100 `0x93` — appear after every
flash. Proven by A/B: cleared 23:04 → stayed clean through the 23:15 drive → reappeared
**identically, same seven codes with the same status bytes**, after the 23:38 flash →
cleared → absent after that drive. Consistent with the DTC session's finding that P3115 is a
roll-up of internal safety-disable reasons, which a module sitting in its bootloader
legitimately is.

**A post-drive DTC read is only meaningful if the module was cleared after the flash and
before the drive.** That became standard procedure from flash 3 onward, and every post-drive
read since has been clean: DLCM No DTCs, Gateway No DTCs, and after the C2 highway drive ABS
No DTCs as well. Gateway codes B1102/U1074/U0037 seen once after flash 1 were stale and
never returned.

The evidence is in `artifacts/dtcs_*.log` — `dtcs_postflash_preDrive_negtrq_20260923.log`
and `dtcs_cleared_preDrive_negtrq_20260923.log` are the A/B pair; there is a
`dtcs_cleared_preDrive_*` for each of flashes 3, 4 and 5.

**Tooling changed during the campaign**, all in `artifacts/` unless noted:
`isotp.py` gained `tx_stmin_floor` + `_pace()`, which floors the sender's STmin instead of
honouring the DLCM's 0 — without it a TransferData block is ~37 back-to-back frames, about
4.3× the real Omitec's instantaneous rate through the GWM. (`time.sleep()` rounds up to
~15 ms on Windows, 14× the 1.1 ms target, so short waits spin on `perf_counter()`.)
`omitec_sim.py` gained `--tx-stmin-ms`, the named presets, and `patches_from_target()` /
`--target-image`. `one_pedal_model.py`'s `change_list()` now skips speed-limb entries already
at or above target, and phase 6's output path names itself after the actual base instead of a
hardcoded `_on_floor20`.

**The torque filter is disabled in calibration** [measured on the C1 image]:
`C_RATE_EN` (`0xA0021544`) = 1, `C_IIR_EN` (`0xA0021545`) = 0. Within the DLCM path the
rate limiter is therefore the **only** stage that is sensitive to dTrq/dt; nothing
downstream of it looks at the rate. `C_HI` = 3000, `C_LO` = −3000.

**The torque ceiling is a clean saturation, and it is not new.** M_MAX sits at 2997.5
internal for an entire drive and never moves — it is a constant, not a dynamic clamp. Published
torque ramps at the limiter's rate with no deviation right up to it and then holds: no
stepping, no clipping, no sign of the limiter and the MCM contending. The launch-rate flash
was flagged in advance as taking the car into "new territory" by reaching that ceiling; that
warning was **wrong** and is withdrawn. The C1 drive had already peaked at 1199 raw
(= 2997.5 internal) on three separate launches. What the launch-rate flash changed is how
fast the car gets there — roughly 0.25 s against 0.6 s — not whether it does.

**`0x212` BrakeSW is live**, DBC start bit 16 = byte 2 bit 0, agreeing with `0x315`
B0.bit0 in 69,615 of 69,690 frames. An earlier DTC session tested **bit 7** and concluded
the signal was dead; that conclusion is withdrawn. No notes file was found carrying the
dead claim, so the retraction is recorded here rather than as a correction elsewhere.

**`0x208` BrakePressure** uses `0x0FFF` as its invalid sentinel, which `cantools` renders
as −1.

**`0x312`**: bytes 4–5 = M_MAX, bytes 6–7 = M_MIN, internal = (raw13 − 2000)/0.4. M_MIN's
p50 is unconstrained (−3000) below ~1750 rpm and about 49 kW constant power above, so the
−690 coast plateau is a **map** value, not a clamp.

---

## 6. Open

- **The preload question is not settled.** n=2 for gentle zero-pedal departures. The
  discriminating channel and its limits are in `../low-speed-driveline-signals.md`.
- **The MCM side has not been audited.** Nothing here establishes what the motor
  controller does with a fast torque request, or how it behaves when the DLCM's rising
  path reaches the M_MAX region.
- **Hill start, ABS/ESC intervention at low speed, and the creep ceiling** have not been
  examined at all. Silence on them is not a pass.
- `one_pedal_model.phase6`'s stale base (§4) is still in the code.
- Arm 2 (one-pedal regen, C2) is not started. Its mandatory coupling — any coast-row
  deepening must also take every brake-map cell to `min(brake cell, new coast cell)` at
  the same speed, or light braking *reduces* regen — is recorded in
  `../plans/dlcm_creep_and_one_pedal.md`. Note that **C1 has already moved the brake map**
  in the low-pressure creep cells, so that rule must be applied against the current image,
  not stock, and must not undo C1's scaling.

---

## 7. Flash 6 — C4c, the accelerator map rebuilt on capability envelopes (2026-09-24)

| # | change | image | md5 | B vs stock | B vs prev |
|---|---|---|---|---|---|
| 6 | C4c pedal map | `cal_candidate_envelope_hr13_nocap_on_onepedal1562.bin` | `2c7a6c6e81fcb16de…` | — | **290** |

168 byte-pairs, 290 bytes against the C2 base (`235df55d…`). Rule, derivation and
rejected alternatives in `pedal-map-envelope-design.md`; **13 guards**, all
re-implemented independently by the in-car session before the flash.

**Driven the same day. User reports it drives well** ("I like it mostly"), with
two follow-ons — extend strong regen to a lower speed, and the D<->R clunk is
unchanged — both recorded in `low-speed-clunk-and-creep-columns.md`. The flash
record itself (timing, DTC reads, post-drive checks) is the in-car session's and
is not transcribed here.

Note the stock-diff column is left blank deliberately: this image was built on
the C2 base rather than regenerated from stock, so the accumulated-diff figure
has not been recomputed against `coda_dlcm_cal.bin` in this session.

---

## 8. An error class this campaign produced twice: the single-cell edit

**C1 and C2 each moved exactly one cell per speed column — row 0 — and left rows
1..10 at factory.** In both cases that dragged one endpoint of a piecewise-linear
curve without touching the next rung, and the unintended consequence was a much
steeper first pedal segment that nobody designed:

| flash | what moved | first-segment gain, stock -> after |
|---|---|---|
| C1 (creep) | row 0, creep columns, x0.145 | 3.68 -> 5.57 Nm/% at 0 mph (1.51x); 2.65 -> 4.16 at 3.1 mph (1.57x) |
| C2 (one-pedal) | row 0, all regen columns, to −1562 | 2.06 -> 7.64 Nm/% at 12 mph (3.7x); 1.84 -> 9.26 at 87 mph (5.0x) |

C2's 3–6x steepening of the gain just off coast is almost certainly what made
one-pedal driving feel touchy, and it was never a design decision. C1's is the
same shape at walking pace and still stands, because every pedal-map candidate so
far skips the creep columns by rule.

**The general lesson, and it applies to any LUT edit here:** moving an endpoint of
an interpolated table changes the *slope of the adjacent segment* as much as it
changes the endpoint value. A change list that moves N cells should state what it
does to the segments either side of each, not only to the cells themselves. The
C3 proposal failed the same way from the other direction — it rebuilt everything
*below* the crossing and left the factory curve above, so the rebuilt segment
butted onto an untouched one with no reason to match slopes, producing a ~2x
gain step at 697 and 1162 rpm.

---

## 9. Flash 7 — the two clunk levers. FAULTED, reverted the same drive (2026-10-04)

| # | when | change | image | md5 | B vs prev |
|---|---|---|---|---|---|
| 7 | 2026-10-04 16:10:23 | 7a: s10.6 IIR enabled (`0xA0021545` 0 -> 1) with its gain LUT rewritten (9 bytes of the x axis `0xA002148C..99`, 6 of the y axis `0xA002149C..A9`); 7c: V-curve idx5-7 100 -> 40, both copies | `cal_candidate_f7_clunk_on_c4c.bin` | `945317bf5b9bee4b…` | **22** |
| — | 2026-10-04 16:24:45–16:27:01 | **revert to C4c** | `cal_as_flashed_20260925_envelope_c4c.bin` | `2c7a6c6e81fcb16de…` | 22 |

Plan: `../plans/dlcm_reflash_7_8_clunk_and_regen_floor.md`. Both images
re-derived by the in-car session before the flash; the protocol held. The
drive produced a low-speed oscillation the driver felt, **seven DLCM resets
in 158 s, and then the Permanent Shut-off Path**: the MCM's 12 V was cut and
the car needed a 12 V cycle. Post-drive readout: `P3115` pending (the
shut-off path's witness), cleared, then reverted; the car is on C4c and
DTC-clean. The 7a enable had been recorded as a one-byte change; the byte
diff is 22 bytes, 15 of which rewrite the filter's gain schedule.

**Cause, established 2026-10-08:** `flash7-reset-mechanism.md`. In one line:
7a put a 300 ms lag between the rate limiter and the published command;
ECM2 has no copy of it; on a sharp release at walking pace the published
command froze while ECM2's allowance kept falling; 300 counts for 5 ticks is a
reset; `0xA0021D8C` = 7 caps the resets and then holds the motor off.

**What the protocol did not catch, and the rule that follows.** Both sessions
checked that every edited table was written to both of its copies. 7a's two
tables have **no** second copy — they are PROG-side only — so "both copies
written" was vacuously true, and nothing asked whether the supervisor's view
of the torque path still matched PROG's. From here, a change list states for
each address which ECM2 copy mirrors it, and an address with none is rejected
unless the supervisor is shown unaffected. Flash 8 was built on this image and
carries all 22 bytes; it is not to be flashed as built.
