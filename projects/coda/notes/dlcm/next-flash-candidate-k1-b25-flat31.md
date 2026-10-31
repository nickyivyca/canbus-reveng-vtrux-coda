# The next calibration candidate after C4c: K1+B25+FLAT31 (simulation write-up)

Owner: `Coda drivetrain lash model` session, 2026-10-13. Plan `../plans/next_flash_from_c4c.md`, step 5.
Evidence: `artifacts/flash7_diagnosis_worklog.md` sections 3BG-3BJ. Every number below is from those sections,
each of which was reviewed with the user when it was recorded; this file collects them and adds nothing new.

**FLASHING IS NOT AUTHORISED.** This is the result of a simulation in `projects/coda/tools/codasim`. The image
`cal_images/illegal-onepedal-156nm.bin` (until 2026-10-17 `artifacts/codasim_cand_K1_B25_FLAT31.bin`) is a simulation image (its build header says "NOT a flash candidate").
Whether anything goes on the car, and when, is the user's decision alone, and a flash needs more review than a
simulation edit (the verification protocol in `dlcm-cal-flash-campaign.md` and `flash7-reset-mechanism.md` section 7).

**Next (user, 2026-10-13):** *"next step is to flash it and test it on the car, the in-car session will review before
it flashes."* The plan is closed; the flash and the car test belong to the in-car session, after its own review.

## 1. What changes vs C4c

Base `cal_as_flashed_20260925_envelope_c4c.bin` (C4c, on the car). Built by `artifacts/codasim_cal_candidates.py`
(`build("K1+B25+FLAT31")`); md5 `f9885cedd82c87fae50c7b1cc138d769`; 249 changed bytes, 124 of them the ECM2 twin
maps, mirrored from the DLCM maps (an unmirrored map edit trips ECM2; worklog 3BG).

| edit | what it does | goal it serves |
|---|---|---|
| **K1** | Creep assist off: CAL `0xA00215C0` 1 -> 0 (`creep-off-ecm2-reason11.md`: ECM2's creep monitor cannot fire under K1). The 5 Nm standstill preload is the map's pedal-0 cell and stays. | shift clunk |
| **B25** | Flash 8's 8a coast columns blended in at 25 % over the first-bank D brake and accelerator maps (`0xA0023B68`-`0xA0023D20`). With creep off, flash 8's 8b is not needed: the command follows the floor (worklog 3BG). | regen to lower speeds |
| **FLAT31** | One pedal zero point, 32.34 % (C4c's cruising crossing), from 0 to 31 mph: the 30 % pedal knot moved to 32.34 %, and each column up to 31 mph becomes two segments that keep its pedal-0 value and its full-pedal value (326.8 Nm below the reference speed). Above 31 mph, C4c's own curve resampled onto the moved axis (error <= 0.05 Nm), so its constant-power taper and its zero point (drifting to 36.7 % by 49.6 mph) stay. | the low-speed zero-point shift |

## 2. Results against the acceptance criteria

Closed loop (`codasim.cosim`), paired vs C4c, at both speed-delay ends (12 and 22 ms) unless marked static.
Thresholds "Tight" (user, 2026-10-10; worklog 3BH.4).

| | criterion | C4c | K1+B25+FLAT31 | verdict |
|---|---|---|---|---|
| A1 | Predicted ECM2 resets: quick check / full sweep | 0 / 0 | 0 / 0 (868 drives, ~41 simulated h); 0 in every closed-loop reversal and launch run; reason-10 debounce stayed at 0 | pass |
| A2 | Regen amount (static: coast torque at or above C4c's wherever C4c regenerates) | -- | identical to C4c from 9 mph up; more regen below it | pass |
| A3 | Zero crossing, synthetic 0 -> +40 Nm at 500 / 1000 / 2000 rpm | 0.05 s | 0.05 s | pass |
| A4 | Off-the-line FILTER LAG (demand -> McmCommand, demand -> shaft torque), reversals | -- | median 0, p90 <= +30 ms | pass |
| A4 | the same on 756 standing launches | -- | median 0 to -40 ms, p90 <= +30 ms | pass |
| A5 | Pedal zero point 0-31 mph (static) | none below 4 mph, 2.36-32.34 % from 4 to 12.4 mph | 32.34 % at every speed | met |
| A6 | Lowest speed with regen (static) | 4.0 mph | 1.5 mph | improved |
| A7 | **Shift clunk**: ring vs C4c over the reversals, all / R->D / D->R (median) | -- | **-43 % / -50 % / -24 %** | main target improved |
| -- | Launch ring vs C4c (756 standing launches; information) | -- | -35 % median, lower on 73 % | -- |
| -- | The 326.8 Nm full-pedal request at rest | -- | capped at 300 Nm (McmCommand and 0x212) | as C4c |

The reversal results are identical to K1+B25+FLAT (386 of 386 episodes; every reversal is below 31 mph).
The floor's D->R ring has a wider p90 tail than C4c: +105 to +210 % per event on about 1 in 10 (worklog 3BI.1).

Static profile (`artifacts/next_flash_score.p3.out.txt`), coast torque at pedal 0 (Nm):

| mph | 0 | 0.5 | 1.0 | 1.5 | 2.0 | 3.0 | 4.0 | 5.0 | 6.0 | 7.4 | 9.0+ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C4c | 5.0 | 4.9 | 4.7 | 4.6 | 4.4 | 4.1 | -9.3 | -25.2 | -69.3 | -131.0 | as C4c |
| K1+B25+FLAT31 | 5.0 | 2.7 | 0.4 | -2.0 | -4.3 | -9.0 | -24.0 | -41.0 | -78.7 | -131.3 | as C4c |

## 3. The candidates scored (worklog 3BI.1, 3BI.6)

| | resets quick / full sweep | zero crossing | regen from | one zero point | shift ring all / R->D / D->R | A4 filter lag | outcome |
|---|---|---|---|---|---|---|---|
| K1 | 0 / 0 | pass | 4.0 mph | no (2-32 %) | -20 / -15 / -26 % | pass | creep off alone |
| K1+FLAT | 0 / 0 | pass | 4.0 mph | 32.34 % | -41 / -51 / -21 % | pass | superseded by the floor |
| K1+B25+FLAT | 0 / 0 | pass | 1.5 mph | 32.34 % | -43 / -50 / -24 % | pass | superseded by FLAT31 |
| K1+B50+FLAT | 0 / 0 | pass | 0.75 mph | 32.34 % | -43 / -51 / -26 % | pass | not chosen (user chose B25) |
| K1+B100+FLAT | 0 / **3** (reason 10) | pass | 0.5 mph | 32.34 % | -37 / -42 / -27 % | pass | **rejected** |
| **K1+B25+FLAT31** | 0 / 0 | pass | 1.5 mph | 32.34 % to 31 mph | -43 / -50 / -24 % | pass | **going forward** |

## 4. Feel changes accepted by the user

- **More pedal for the same torque below the zero point.** Under FLAT31, pedal up to 32.34 % asks for (nearly) no torque
  at low speed, where C4c's steep launch rows gave real torque. When the pedal reaches 5 % at a standing launch,
  McmCommand is ~4 Nm vs C4c's ~31 Nm. On ~280 recorded post-shift presses, 92 stayed below ~32 %; on ~750 launches,
  238 stayed below ~33 %. Measured from the pedal onset this is +70 ms median, ~+360 ms p90, and all of it is pedal
  travel to the zero point (user: *"I want a feel change so feel changes are expected"*; worklog 3BI.2, 3BJ.2).
- **Hill starts need much more pedal.** On the steepest recorded R->D (`coda_20260801_122531_T0`), C4c's 252 Nm at the
  recorded 55 % pedal needs ~84 % under FLAT. Replaying the recorded pedal, the model rolls back to 6.6 mph; a driver
  would press further (worklog 3BI.4; user: accepted, noted).
- **Longer rollback after a rolling shift with creep off**: time below -0.3 mph p90 C4c 0.43 s, K1 0.73 s, FLAT images
  1.4-1.7 s; peak backward speed p90 ~2 mph for all. Rollback is not a criterion (user). At standing launches the
  rollback stays small (max 0.57 mph; 8 launches past 0.3 mph vs 0 for C4c).
- **The standstill dip.** At 0 mph the preload falls linearly from 5 Nm to 0 at 32.34 %:
  5.0 / 3.5 / 2.0 / 0.4 / 0.1 Nm at 0 / 10 / 20 / 30 / 32 % pedal. User: *"as long as it doesn't go to 0 or negative,
  then dip is fine"* -- it does not (worklog 3BJ.3).

## 5. Rejected and why

- **K1+B100+FLAT**: 3 predicted ECM2 reason-10 resets in the full sweep, all while rolling backward at ~1 mph in D with
  the brake held (the DLCM looks its map up by |speed| and asks for about -11 Nm; ECM2 looks its twin up at speed 0 and
  allows 0). The floor's magnitude passes the 5 Nm margin above about 0.6 mph (B100), 1.1 mph (B50), 2.2 mph (B25).
  Reason 10 is not flash 7's mechanism (that was reason 12, the MCM command check) (worklog 3BI.3).
- **FLAT's zero point above 31 mph**: FLAT moved the constant-power taper's zero (49.6-86.8 mph) from 36.7 % to
  32.34 %; the user chose to restore C4c's above 31 mph (worklog 3BI.6).
- **FLAT31H** (the preload held to 30 %): with the regen floor, the map blends the held 0 mph column with the 3.1 mph
  regen column and the zero moves to ~14-21 % between ~1.5 and 3 mph, breaking the single zero point. Built, not
  scored; not adopted (worklog 3BJ.4).

## 6. The model's limits

- **It ranks; it does not certify feel.** The closed loop misses by 5-28 Nm near standstill (plant speed after hard
  shifts), which is where creep acts. Ring is the model's clunk measure.
- **No driver model.** The recorded pedal is replayed as driven, so the model cannot say how much further the driver
  would press under FLAT31 (the light-press, hill-start and rollback figures above all carry this).
- **Reason 10 has no ground truth**: it has never fired on the car. Both sides of the check are transliterated firmware
  and C4c's full sweep predicts 0. The full sweep records resets, not the debounce, so near misses there are not
  measured; the closed-loop runs (reversals and launches) did measure it, and it stayed at 0 for B25.
- **Timing resolution.** The closed loop's 0x212 leads the recorded 0x212 by ~15 ms at the 50 / 90 % levels on 267 real
  presses (the car logs at 20 ms); the 12 vs 22 ms speed delay moves A4 times by <= 10 ms.
- **Two gaps found by the `Coda DLCM work` session's independent review** (2026-10-13, `artifacts/k1b25flat31_review.py`;
  worklog 3BK.2). (1) B25 also changes the D brake map: at 3.1 mph -10.0 to -12.5 Nm across the pressure knots vs C4c's
  +3.3 to 0, at 4.96 mph -39.6 vs -23.5 at every pressure; 0 mph and 7.44 mph up are unchanged. So with the brake on,
  below 7.44 mph, the candidate asks for more regen than C4c. (2) Ring on braked stops was not scored: A7 covers
  reversals, section 2's launch ring covers standing launches.
- **Coverage.** Full sweep: 1101 captures, 868 ran (233 skipped: 189 bus errors, 44 with too few 0x212 frames; 86 with
  no quiet point; 2 replay errors). 11 captures after 2026-10-05 have no established real-reset count. f7 captures are
  kept out of the headline statistics.
