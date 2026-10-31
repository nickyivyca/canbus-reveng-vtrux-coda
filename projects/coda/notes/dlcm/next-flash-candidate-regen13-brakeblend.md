# Calibration candidate: 0.13 g off-throttle regen, the full 156.2 Nm blended in on the brake (K1+B25+FLAT31+R13P10+BBSW20P256)

Owner: codasim / DLCM session (flash definition), 2026-10-17. Plan `../plans/next_flash_regen13_brake_blend.md`, step 6.
Modelling and screens: `Coda drivetrain lash model` session, `regen13-model-screens.md` sections 4-5.
Evidence: `artifacts/flash7_diagnosis_worklog.md` 6H.72-6H.76 (this session) and 3BO-3BR (lash). Every number below
is from those sections, each reviewed with the user when it was recorded; this file collects them.

**FLASHING IS NOT AUTHORISED.** This is a simulation result (`projects/coda/tools/codasim`). The image is a simulation
image; whether anything goes on the car, and when, is the user's decision alone, and a flash belongs to the in-car
session after its own review (`dlcm-cal-flash-campaign.md` section 1, `flash7-reset-mechanism.md` section 7).

## 0. The request and why

User, 2026-10-14: *"another flash that is similar in goals to the current flash candidate, but with 0.13g off throttle
regen and then the existing 150nm/0.17 ramped in on early brake presses ... it feels continuous (matching the curve
shape of the existing friction brake)."* The Coda does not light the stop lamps for regen. UN R13-H 5.2.22.4 requires
the stop-lamp signal above 1.3 m/s2 (0.13 g) of regen on accelerator release; with the brake pressed the switch lights
them. So off-throttle regen is capped at 0.13 g, and the rest of today's regen moves onto the brake pedal.

## 1. The image

| | |
|---|---|
| image | `cal_images/0.13g-brakeblend-156nm.bin` (until 2026-10-17 `artifacts/codasim_cand_K1_B25_FLAT31_R13P10_BBSW20P256.bin`) |
| md5 | `13679c3c4bc82caf2317749cb3e698f3` |
| builder | `artifacts/codasim_cal_candidates.py`, `build("K1+B25+FLAT31+R13P10+BBSW20P256")` |
| built on | C4c, `cal_as_flashed_20260925_envelope_c4c.bin` (`2c7a6c6e...`, on the car), through K1+B25+FLAT31 (`f9885ced...`) |
| vs C4c | 615 bytes, 347 words |
| vs K1+B25+FLAT31 | 482 bytes, only in the D accelerator and brake maps and their ECM2 twins |
| independent rebuild | lash session, without the builder, from the stated rule (now section 2): md5-identical (2026-10-16); section 2 reproduces that rebuild with no gaps (lash check 2026-10-17) |
| flash tool name | `0.13g-brakeblend-156nm` in `projects/coda/tools/flash_cal.py` (a draft name; status `candidate`) |

## 2. The rule (enough to rebuild the bytes)

Units: map cells are 0.1 Nm counts; the D accelerator map's pedal axis is in 0.01 % (10000 = 100 %); its speed axis is
in internal counts, 2.203 per CAN motor rpm (the rounded form of the firmware's 2 x 282/256 = 2.203125; the user chose
2.203, 2026-10-16), mph = rpm x 86.8 / 8134. Columns are selected by speed-axis count, not by computed mph:

| axis count | 0 | 640 | 1024 | 1536 | 2560 | 6400 | 10240 | 12800 | 15360 | 17920 |
|---|---|---|---|---|---|---|---|---|---|---|
| mph | 0 | 3.1 | 4.96 | 7.44 | 12.4 | 31.0 | 49.6 | 62.0 | 74.4 | 86.8 |
| R13 class | near 0 | near 0 | near 0 | near 0 | REF | REF | envelope | envelope | envelope | envelope |

**K1, B25, FLAT31** (the base) are unchanged from `next-flash-candidate-k1-b25-flat31.md` section 1: creep assist off
(`0xA00215C0` 1 -> 0), flash 8's coast columns blended in at 25 % over the first-bank D brake and accelerator maps, and
FLAT31's one zero point to 31 mph.

**R13P10, the coast cap** (D accelerator map, `DescDemandPedalD`), T13 = 106 Nm requested, full pedal 326.8 Nm:

- Zero point Z = round(106 / (106 + 326.8) x 10000) = **2449** (24.49 %). It replaces FLAT31's moved pedal knot 2
  (3234). Knots: 0 / 1500 / 2449 / 4000 / 5000 / 6000 / 7000 / 8000 / 9000 / 9500 / 10000.
- REF columns (2560, 6400): one straight line, cell = -106 + 432.8 x x / 10000 Nm (-0.07 counts at Z, so 0 after
  rounding).
- Envelope columns (10240 up): pedal-0 value c = max(-106, -50500 W / omega), omega = (count / 2.203) x 2 pi / 60 rad/s
  (P10: a 50.5 kW constant-power fit to the 10th percentile of the DLCM's own published 0x312 M_MIN at 47-67 mph);
  cell = c + (full - c) x x / 10000, full = the column's 100 % cell in the base (equal to C4c's above 31 mph). Pedal-0 values -103.7 / -83.0 / -69.2 /
  -59.3 Nm.
- Near-0 columns (0 to 1536), the user's exception (*"this was applied too widely when c4c was made ... so this doesn't
  accidentally come back"*): two segments, c = max(own pedal-0, -106) straight to 0 at Z, then the REF values above Z.
  The 7.44 mph column's pedal-0 value -132.8 (C4c's, unchanged by B25) becomes -106. `check_r13` refuses an image that breaks this (C4b).
- Each cell is rounded once to the nearest count (no ties occur).

**BBSW20P256, the brake blend** (D brake map, `DescDemandBrakeD`; pressure axis = raw 0x208 BrakePressure, knots 0 / 48 /
64 / 80 / 96 / 144 / 192 / 256 / 352 / 480 / 1600):

- Applied in every column whose new coast value c (the accelerator map's pedal-0 cell after R13, read back as count x
  0.1) is regen (< 0) and more than 1 Nm shallower than the brake map at pressure 0: the columns R13 lifted, 7.44 mph
  up. The 0-4.96 mph columns keep the base's brake regen.
- Each knot becomes round((c + h x (b - c)) / 0.1), b = the knot's current value (count x 0.1), with
  **h = 0.2 / 0.2 / 0.311963 / 0.416497 / 0.513336 / 0.755022 / 0.917881 / 1 / 1 / 1 / 1** at the knots above.
- Why this h: 0x208 reads 0 or >= 48 raw, never 1-47 (lash 3BP; 582,769 frames, 20 captures), so the map is read only
  at the switch alone (P = 0) or from 48 up. h(0) = h(48) = 0.2 gives 10 Nm from the switch at the plateau and no step at
  the first reading (user: "move forward with 0.2"). From 48 to 256: 0.2 + 0.8 x a friction-shaped ramp
  (friction-increment weights x (1 - u), u = (P - 48) / 208) on a count-weighted quadratic fit of the friction curve,
  F = -0.144647 + 0.00519368 P + 2.54002e-06 P^2 m/s2 (user: "yes to both", p_r 256 linear and C3 on a smooth fit).
- From 256 raw up (h = 1) the brake map keeps the base's value: -156.2 Nm from 12.4 mph, -132.8 at 7.44 mph (option a,
  user 2026-10-14): above 31 mph the live regen limit (0x312 M_MIN) decides.

**ECM2:** every changed map array is copied onto its ECM2 twin (`DescEcm2DriveMapD`, `DescEcm2BrakeMapD`), which must be
byte-identical to the DLCM map (an unmirrored map edit trips ECM2 reason 10; worklog 3BG).

## 3. The change list, per address, with its ECM2 copy

Generated from the descriptors, not from the builder: `artifacts/regen13_change_list.py` ->
`artifacts/regen13_change_list.csv` (one row per word: address, table, cell, C4c / base / candidate value, layer, ECM2
twin address, twin identical) and `.out.txt`.
Counted independently by lash (`artifacts/regen13_change_list_check.py`, `codasim.image` only): the same 615 bytes,
347 words, per-table counts and 0 twin mismatches.

| table (DLCM side -> ECM2 twin) | array (DLCM / ECM2 address) | words: base / regen13 / both |
|---|---|---|
| CalCreepEnable (K1), byte | `0xA00215C0`; no twin (ECM2's creep monitor cannot fire under K1, `creep-off-ecm2-reason11.md`) | 1 / 0 / 0 |
| `DescDemandPedalD` -> `DescEcm2DriveMapD` | x, pedal knot 2: `0xA002179C` -> `0xA0021A1C` (3000 -> 3234 -> 2449) | 0 / 0 / 1 |
| | z: `0xA0023C44` (110 words) -> `0xA0021F6C` | 10 / 55 / 36 |
| `DescDemandBrakeD` -> `DescEcm2BrakeMapD` | z: `0xA0023B68` (110 words) -> `0xA0021DB4` | 22 / 49 / 0 |
| the four ECM2 twin arrays | as above | same counts |

"base" = already changed in K1+B25+FLAT31; "regen13" = changed only by R13P10 / BBSW20P256; "both" = changed by the base
and again by regen13. Checks (all from the script):

- every one of the 615 changed bytes is in a mapped array or the named scalar: 0 unexplained;
- 173 DLCM-side map words changed, 173 with an ECM2 twin holding the same new value, 0 without; the 173 changed ECM2
  words are exactly those twins;
- unchanged: the AppLoss / Fault maps (`DescDemandAppLossBrakeD`, `DescEcm2BrakeMapDFault`), all R maps and their
  twins, `DescBoundBrakeTblA/B`; the flash-7 rule-1 bytes are untouched (step 4).

## 4. Results against the acceptance criteria

Static and firmware screens: this session (`artifacts/regen13_step4.py`, worklog 6H.75.4). Closed loop and sweeps: lash
(`regen13-model-screens.md` sections 4-5, `artifacts/regen13_screens.p4v.out.txt`), under the user's grading system
(2026-10-17): pull-away graded at an equal unfiltered request (an adapted driver, reference C4c), shift clunk with the
pedal at 0 and the brake held, stops and static reported, resets gate everything.

| | criterion | result | verdict |
|---|---|---|---|
| C1 | off-throttle regen-only decel <= 0.13 g | 0.130 g (106 Nm, driver only, step 2's calibration) | pass |
| C1b / C1c | regen shortfall / pedal dead zone above 31 mph | P10: <= 0.2 Nm shortfall, about 2 % dead zone above 42 mph (`regen_envelope_c4c.p5`) | user-chosen trade |
| C2 | brake-on regen reaches 156.2 Nm by p_r | full at 256 raw in every ramped column | pass |
| C3 | total decel vs pressure: gain step <= 0.25 m/s2 per 100 raw on knots 48..352 | 0.21 worst (86.8 mph column) on the smooth fit [0.23 binned]; the derived h is <= 0.17 on every friction curve tried | pass |
| C4b | near-0 columns: two segments, one zero point | `check_r13` passes; zero point 24.49 % at every speed 0-31 mph (19 of 19 static points) | pass |
| A1 / C5 | no predicted ECM2 reset | 0: full sweep (868 drives run; 233 skipped, 2 replay errors, as the base), quick check, ~8,800 closed-loop runs, 90 brake-press screens (reason 10 / 12 debounce max 0), release sweep, backward roll, N->D | pass |
| A3 | zero crossing, 0 -> +40 Nm at 500 / 1000 / 2000 rpm | 0.04 / 0.05 / 0.05 s | pass |
| A4 | pull-away at equal unfiltered request vs C4c, median / p90 (fail > +0.020 / +0.050 s) | drive-off after a shift (n 269): cmd90 +0.000 / +0.020 s, wheel90 +0.001 / +0.022; standing launch (n 756): +0.000 / <= +0.003 | pass |
| A7 | shift clunk, pedal 0 and brake held (reported) | -72 % vs C4c (lower in 87 %, worse on 20 of 300); 0 % vs the base | holds |
| -- | braked stops vs the base (reported) | stop time +0.07 s (from ~5 mph) / +0.03 s (~3 mph); decel and ring unchanged | -- |
| -- | ring after pull-away (reported) | drive-off after a shift -25 % vs C4c; standing launch +1 % (no change) | -- |
| C6 | flash protocol | independent rebuild md5-identical; nothing else moved; every edit has an ECM2 twin; rule-1 untouched (section 3) | pass |
| -- | reality test: candidate request vs the car's while braking on C4c drives (75 captures; p6) | p50 0 in every band; p99 47.5 / 7.8 / 0.2 Nm at 12.4-31 / 31-50 / 50+ mph | -- |

A2 ("regen not reduced") is replaced off-throttle by C1 / C2, the user's new goal, and fails at 6-31 mph by design. A5 is
replaced by linear torque per pedal travel with one zero point from 0 to 31 mph.

## 5. Decisions and accepted changes (user)

- 0.13 g is regen only; T13 106 Nm requested, no extra margin; envelope P10; C3 bound 0.25 m/s2 per 100 raw (step 3).
- Regen stays fully on at every brake pressure, as today ("1. keep it").
- Above 31 mph the brake map keeps C4c's -156.2 Nm target and the live limit decides ("option a").
- Switch share 0.2, chosen on feel: energy share cannot rank it (method bias about 2 points; 0.5 point per 0.1 of h_s).
- p_r 256 with a linear taper, C3 on a smooth friction fit ("yes to both"). Cost against p_r 144: about 0.5 Wh/mile at
  the wheels, 0.4-0.45 at the battery (assumed 80-90 % regen path), out of 30.9 Wh/mile braking energy on 455 stock-map
  drives. A rough figure.
- The speed-to-rpm constant 2.203 ("Keep 2.203").
- The 100 % synthetic standing launch reaches 90 % command in 0.29 s vs C4c's 0.26 s (the base: 0.29, the same), from
  the bigger request step (326.8 vs 300 Nm; time to 100 Nm is equal). User decision (lash session, 2026-10-17): not
  gated under the equal-request grading.
- The base's accepted feel changes carry over (`next-flash-candidate-k1-b25-flat31.md` section 4), with the zero point
  now at 24.49 % instead of 32.34 %.

## 6. Caveats and the model's limits

1. The pull-away and clunk runs used the 1.5 ms 0x20C arrival only. Where every offset was run, A4 moved <= 0.01 s, ring
   <= 1.5 points, stop time <= 0.03 s.
2. **Hypothesis (user-approved, lash 3BQ):** the clunk reduction comes from removing C4c's creep, which drives 30-150 Nm
   against the wrong-way roll with the brake on; the model reproduces the car's 0x212 at the shift (peak 45 vs 45 Nm,
   rho 0.89). The -72 % also depends on cosim's held-wheel body damping (`body_hold_z` 1.0, the default since
   2026-10-17); -37.5 % without it. Both are to be verified on creep-off car data. Time in neutral (0.16-0.30 s in the
   data) is untested.
3. 5 standing launches roll back past 0.3 mph (max 0.47), the same as the base; C4c 0. Rollback is not a criterion.
4. The braked-stop model's limits from lash's step 3 apply (`regen13-model-screens.md` section 3); friction in the
   hidden brake zone (switch on, 0x208 = 0) is not modelled.
5. Brake-on exposure at speed in the logs is thin (about 6 s at 31-50 mph, under 1 s above 50 mph), so the option-a
   evidence above 31 mph rests mostly on the map-above-limit rows (102 s).

## 7. Next

The user decides whether this goes to the in-car session. If it does, that session reviews and flashes it with its own
protocol; `flash_cal.py 0.13g-brakeblend-156nm --allow-candidate` names the image. After any flash, the on-car reference
(`omitec_sim.CAL_ON_CAR`) and the lineage in `dlcm-cal-flash-campaign.md` are updated.
