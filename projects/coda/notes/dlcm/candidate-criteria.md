# Calibration candidate criteria: two scorecards

Agreed with the user 2026-10-17. Owner: codasim / DLCM session (flash definition); the closed-loop measures are the
lash session's. For new work this replaces the A1-A7 table of `../plans/next_flash_from_c4c.md` and the C1-C6 table of
`../plans/next_flash_regen13_brake_blend.md`; those tables stay as the record of how past candidates were judged.

**FLASHING IS NOT AUTHORISED by any scorecard.** A card says how a candidate scores in simulation; whether anything goes
on the car is the user's decision alone.

## 1. The images, all maintained

| headline name | what it is | builder code (traceability) | md5 |
|---|---|---|---|
| `0.13g-brakeblend-156nm` | off-throttle regen capped at 0.13 g; the full 156.2 Nm blended in on the brake; reverse pedal mapped as forward; highway chatter fix | K1+B25+FLAT31+R13P75+BBSW20P256+RDZ+G58 (since 2026-10-28) | `aa6377a1...` |
| `0.13g-brakeblend-156nm-nochatterfix` | the same without the highway chatter fix (the headline 2026-10-27..28) | K1+B25+FLAT31+R13P10+BBSW20P256+RDZ | `d917d465...` |
| `illegal-onepedal-156nm` | full one-pedal regen at C4c's level, no brake blend | K1+B25+FLAT31 | `f9885ced...` |

Both are defined by the same few inputs. The pedal zero point is NOT an input: it follows from linear torque per pedal
travel at the image's coast level, zero = T / (T + 326.8 Nm), which gives 24.49 % at T = 106 Nm and 32.34 % at
T = 156.2 Nm, held from 0 to 31 mph, where constant power takes over.

| input | `0.13g-brakeblend-156nm` | `illegal-onepedal-156nm` |
|---|---|---|
| off-throttle regen | 0.13 g (106 Nm requested, driver-only load); 46.6 kW constant power above 31 mph (`-nochatterfix`: 50.5 kW) | C4c's 156.2 Nm; C4c's constant power above 31 mph |
| brake blend | 0.2 of the brake regen from the switch alone, full from 256 raw | none: brake regen equals coast, as today |
| charging-current feedback (CalBoundDerateBGain) | 58 (`-nochatterfix`: stock 230) | stock 230 |
| reverse accelerator map | D's zero point 24.49 % and 326.8 Nm full pedal (RDZ) | C4c's |
| creep | off | off |
| low-speed regen floor | 25 % blend, regen down to about 1.1 mph | the same |
| zero point (derived) | 24.49 % | 32.34 % |

**Reference:** every comparison is against the calibration on the car (`../../tools/flash_sim/omitec_sim.py` `CAL_ON_CAR`; C4c
today), not against C4c by name. S2's adapted driver remaps every image to the reference's pedal map, so S2 is "at
C4c's request" only while C4c is the reference.

## 2. Gates (any failure rejects)

| | gate | card |
|---|---|---|
| G1 | No predicted ECM2 reset: quick check, full sweep, every closed-loop run, and the firmware brake-press and release screens (reason 10 / 12 debounce) | both |
| G2 | The C4c low-speed slope never comes back: every column below the cruising row is two segments meeting at the zero point, the cruising row's gain above it (the builder refuses an image that breaks this) | both |
| G3 | Flash protocol: independent rebuild from the written rule matches the md5; every map edit has its ECM2 copy; nothing else moved; the flash-7 rule-1 bytes untouched (`dlcm-cal-flash-campaign.md` section 1) | both |
| G4 | **Optional, for 'legal' flashes only:** off-throttle regen-only deceleration <= 0.13 g (UN R13-H stop-lamp threshold), on the driver-only calibration | `0.13g-brakeblend-156nm` only |

The illegal image does not go through G4 (user 2026-10-17: "we don't want to have to go through major hoops for
'illegal' flashes").

## 3. Scored goals

| | goal | measure | card |
|---|---|---|---|
| S1 | **Shift clunk lower** | paired ring vs the reference after a shift, pedal at 0 and the brake held at its shift value (closed loop); median % and the share of shifts lower | both |
| S2 | **Response no slower**, from the request through the filtering to the wheels | at an equal unfiltered request (the adapted driver), drive-off after a shift and standing launches, cmd50 / cmd90 / whl50 / whl90 paired vs the reference: median <= +20 ms and p90 <= +50 ms; zero crossing 0 -> +40 Nm at 500 / 1000 / 2000 rpm no more than one tick (10 ms) slower. Pass / fail with the values | both |
| S3 | **Accelerator pedal smooth** | torque linear in pedal travel from the zero point to full pedal; one zero point from 0 to 31 mph; dead travel at the bottom of the pedal and unused regen above 31 mph, per speed | both |
| S4 | **Regen carried as low as it can go** without negatively affecting the other criteria | lowest speed with regen (static) | both |
| S5 | **Brake pedal smooth** | total deceleration vs brake pressure (regen + the friction model) on the reachable knots 48..352: worst gain step <= 0.25 m/s2 per 100 raw on a smooth friction fit; the regen step at the switch and at the first pressure reading (Nm); brake regen reaches the full value by its ramp end | `0.13g-brakeblend-156nm` only |

**Optional scores** (reported when asked, never decisive): regen energy recovered (Wh/mile; the differences between
designs were in the noise of the method, about 1.3 Wh/mile across the whole range); stop time.

**Model-validity lines** (printed under the card, about the model rather than the candidate): car-vs-model divergence
flags; sensitivity to the 0x20C arrival offset; dependence on cosim's held-wheel body damping (`body_hold_z`).

## 4. Not criteria

- Rollback after a shift or launch (user: not a criterion).
- Regen at high brake pressure stays fully on, as today (user 2026-10-14, "1. keep it").
- The feel changes already accepted for the illegal image (`next-flash-candidate-k1-b25-flat31.md` section 4).
- Braked-stop ringing (dropped 2026-10-17: the user has never noticed it. The car settles without rocking; the model's
  excess stop ring was its undamped body, and the car's own stop ring tracks stop hardness, not the lash; lash step 3).
- A2 "regen not reduced" (superseded by the 0.13 g goal) and any specific zero-point value (the zero point is derived).
- Launch ringing, and the full-pedal synthetic launch time (user: not gated under the equal-request grading).
- The recorded-foot replays and the filter-lag form of A4: model context only.

## 5. Current cards

Measured by `artifacts/candidate_scorecard.py <name> --closed-loop` (2026-10-17; the cards are
`artifacts/candidate_scorecard.<name>.out.txt`). The closed-loop lines reproduce the lash session's step-4 results. The
images are in `cal_images/`.

`0.13g-brakeblend-156nm` as it was on 2026-10-17, K1+B25+FLAT31+R13P10+BBSW20P256 (`13679c3c...`, flashed 2026-10-25, now deprecated; write-up `next-flash-candidate-regen13-brakeblend.md`): G1-G4 pass (0 resets in 2736
closed-loop runs, and in the full sweep and brake-press screens of lash step 4; G4 0.1300 g at 7.5 mph). S1 -72.2 % vs
C4c, lower on 87 % of 300 shifts (R->D -72.6 %, D->R -70.8 %). S2 pass (p90 +0.022 s drive-off after a shift, +0.003 s
standing launch; zero crossing 0.04 / 0.05 / 0.05 s). S3 zero point 24.49 % from 0 to 31 mph, within 0.04 Nm of a
straight line above it; above 31 mph, unused regen mean 0.4 Nm (worst 1.5 Nm at 42-47 mph) and dead travel mean 1.5 %
(worst 3.5 % at 67-72 mph). S4 1.08 mph. S5 worst step 0.21 per 100 raw on the smooth fit (at 86.8 mph); the switch adds
10 Nm at 12.4-31 mph, up to 19.4 Nm at 86.8 mph; no step at the first reading; full at 256 raw. Model-validity: S1 is
-37.5 % without the held-wheel body damping; 0x20C arrival 1.5 ms only for S1 / S2 (where every offset ran, A4 moved
<= 0.01 s).

`illegal-onepedal-156nm` (write-up `next-flash-candidate-k1-b25-flat31.md`): G1-G3 pass (0 resets in 2736 closed-loop
runs). S1 -71.9 % vs C4c, lower on 88 % of 300 shifts (R->D -72.6 %, D->R -68.7 %); its old -43 % was the recorded-foot
method. S2 pass (p90 +0.030 s drive-off after a shift, +0.003 s standing launch; zero crossing 0.05 / 0.05 / 0.05 s).
S3 zero point 32.34 % from 0 to 31 mph, within 0.05 Nm of a straight line above it; above 31 mph, unused regen mean
0.2 Nm (worst 0.7 Nm at 31-37 mph) and dead travel mean 7.3 % (worst 11.7 % at 67-72 mph). S4 1.08 mph. Model-validity:
S1 is -37.3 % without the held-wheel body damping (`p4h`).

S4 read 1.5 mph before 2026-10-17 on both images because the old check sampled only 1.0 and 1.5 mph; coast torque
crosses zero between 1.0 mph (+0.4 Nm) and 1.12 mph (-0.2 Nm).
