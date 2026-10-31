# Model screens for the 0.13 g regen + brake-blend candidate, and ring on braked stops

Owner: `Coda drivetrain lash model` session, 2026-10-14. Plan `../plans/regen13_model_screens.md`; parent plan
`../plans/next_flash_regen13_brake_blend.md` (owned by `Coda DLCM work`), its step 5. Simulation and log analysis only;
nothing flashed. Inputs: `regen13-modelling-inputs.md`. Each section is written at its plan step's checkpoint.

Script `artifacts/regen13_screens.py` (phases; outputs `artifacts/regen13_screens.p*.out.txt` / `.json`).

## 1. Braked-stop episodes (step 1; reviewed with the user 2026-10-14)

Why: the K1+B25+FLAT31 review found that ring on braked stops was never scored (worklog 3BK.2), and the new candidate
edits the D brake map. At a braked stop the motor torque passes from regen to the standstill preload, a lash crossing
without the lever.

### Definition (`codasim/episodes.py`, `find_stops`; reversal and launch extraction unchanged)

Two sets, both adopted (user, 2026-10-14):

| | `kind="stop"` | `kind="stop_low"` |
|---|---|---|
| anchor t | first 0x1C0 \|rpm\| < 470 (~5 mph) | first \|rpm\| < 281 (~3 mph) |
| armed by | \|rpm\| > 940 (~10 mph) within 8 s before t | \|rpm\| > 470 (~5 mph) within 15 s before t |

Common to both:
- stationary (\|rpm\| < 20 on every frame for >= 0.5 s) starting within (t, t + 4 s];
- the brake on (0x212 BrakeSW 1, or a valid 0x208 pressure > 0) at the moment it becomes stationary; the brake may
  come on before or after t (on C4c the driver mostly brakes late, after one-pedal regen);
- 0x210 accelerator < 1 % from t - 0.5 s to the stop;
- 0x418 PRND D on every frame in [t - 2 s, t + 4 s]. Stops followed by a shift out of D within 4 s stay out of both
  sets: the shift's ring would mix into the stop's;
- one event per descent;
- impact and ring as for shifts: the largest 0x330 step in (t, t + 2.5 s]; ring = 2.4-10 Hz mean square over
  [t_imp + 0.1, t_imp + 2.0] s.

Stores (regenerable): `artifacts/codasim_stop_episodes.npz`, `artifacts/codasim_stop_low_episodes.npz`. Corpus 1101
captures; 189 dropped for an unresolved D bus, 16 with no 0x418 on D, 4 with no 0x1C0, 12 / 16 stops past a capture
edge. f7_clunk kept in the store, out of the headline.

### Counts

| | stops | runnable (quiet point) | C4c (envelope + post-revert) | pre-campaign | stock+FLOOR5 |
|---|---|---|---|---|---|
| `stop` | 635 | 423 | 26 | 329 | 267 |
| `stop_low` | 857 | 598 | 55 | 429 | 347 |

`stop_low` contains 634 of `stop`'s 635 (same capture, stationary within 0.5 s) and adds 223 (176 runnable, 29 C4c).

The 112 braked C4c stops (presses from > 0.5 mph that end stationary, `regen13_inputs.p1.json`;
`artifacts/regen13_stop_diag.py`):

| | `stop` | `stop_low` |
|---|---|---|
| qualify | 25 | **56** |
| never fast enough beforehand | 53 | 17 (peaked at 1-5 mph) |
| accelerator >= 1 % near the stop | 16 | 2 |
| not stationary within 4 s of the anchor | 13 | 11 |
| left D within [t - 2, t + 4] s | 2 | 16 |
| other (stationary < 0.5 s, brake off at the stop, second stop in one descent) / no anchor | 3 | 10 |

### Recorded measures (headline, f7_clunk excluded), p10 / p50 / p90

| | `stop` | `stop_low` |
|---|---|---|
| anchor -> stationary, s | 1.54 / 2.21 / 3.02 | 0.95 / 1.40 / 2.40 |
| impact after the anchor, s | 0.05 / 1.48 / 2.30 | 0.26 / 1.21 / 1.89 |
| speed at the impact, mph | 0.07 / 0.54 / 4.90 | 0.00 / 0.26 / 2.50 |
| 0x1C0 torque at the impact, Nm | -25.9 / -0.1 / 5.5 | -1.4 / 1.9 / 8.2 |
| ring, (m/s2)^2 | 0.0004 / 0.0017 / 0.0094 (n 364) | 0.0006 / 0.0027 / 0.0093 (n 358) |
| brake onset before the anchor, s | 6.75 / 2.98 / 0.60 | 7.10 / 3.30 / 0.97 |
| speed at the brake onset, mph | 6.2 / 14.8 / 28.9 | 4.7 / 12.1 / 26.9 |

- `stop`'s lower median ring (a reading): its impact window, starting at ~5 mph, more often takes a step before the
  final one (speed at the impact p90 4.9 mph against 2.5; impact step p10 -2 counts against +1).
- In `stop_low`, 107 stops brake from 2-5 mph (37 of them C4c), 742 from above 5 mph.
- Brake onset is measured on the stored series (>= 5 s before the episode window); 24 / 39 stops were braking from the
  start of the stored series, so their onset is earlier still.

### The accelerometer goes invalid just after the car stops

In 577 of the 857 `stop_low` stops, 0x330 Long_Accel sends its invalid value (raw 255, a few 254) for ~0.12 s (p10-p90
0.12-0.14 s), starting a median 0.6 s (p10-p90 0.38-0.88 s) after the car becomes stationary. With the mask around
invalid samples (2 before, 8 after) more than 5 % of the ring window is invalid, so **the recorded ring is undefined
for ~58 % of stops in both sets** (n 358 of 857, 364 of 635).

- The candidate comparison is not affected: the simulated ring is computed on the plant's own acceleration (all
  valid), so every runnable stop is scored.
- It limits the car-vs-sim check of the model to the ~360 stops per set with a recorded ring.

## 2. Brake friction and the grade in the plant (step 2; reviewed with the user 2026-10-14)

Closed loop (cosim, preset current, each stop's own on-car CAL, speed delay 12 ms, receive timing as of 2026-10-14
before the poll-schedule change; `regen13_screens.py` phases 2 / 2g). Simulated vs recorded motor speed on every
runnable stop.

**Options added to `codasim/plant/road.py`** (defaults unchanged; stored C4c reversal rings reproduce bit for bit):
- `friction="measured"`: the brake friction follows the car-measured curve (`regen13-modelling-inputs.md` section 3;
  the bin medians embedded as `FRICTION_MEAS`, P = 0 set to 0, the last slope extrapolated), converted at the plant's own
  gain GEOM / J_TOT, so the plant decelerates as the car does. Default `"p7"` (R0 + kb x P) unchanged.
- `grade_fallback=True` (opt-in, for stops): the grade fit needs >= 20 brake-off moving samples, and a braked stop is
  usually brake-on over the whole episode. Without it 312 of 423 runnable `stop` episodes and 452 of 597 `stop_low`
  episodes were refused. The fallback takes the grade over all moving samples with the friction model subtracted.
  Episodes that ran before are unchanged (512 of 512 runs identical). Default off so no earlier sweep's runnable set
  moves.
- `cosim.run(..., friction=, grade_fallback=)` passes them through.

**Results with the fallback** (p50; f7_clunk excluded):

| | `p7` | `measured` |
|---|---|---|
| runnable `stop` / `stop_low` | 423 / 569 | 423 / 569 |
| stop time, sim - recorded (`stop`) | -0.04 s | -0.02 s |
| RMS speed error, handover to the recorded stop (`stop`) | 0.17 mph | 0.16 mph |
| simulated car not stationary within 4 s (both sets) | 72 | 94 |

- Stops run only through the fallback track as well as the others (median RMS 0.16 mph, stop time -0.04 s).
- The speed trace does not separate the two friction models: before the anchor the measured road absorbs the
  friction model's error.
- The simulated stops that do not complete are mostly pre-campaign and stock stops at light pressure (median 65-80
  raw, some on the switch alone), where the simulated brake does not hold against creep; the measured curve, weaker
  below ~200 raw, lets more through. A reading, not checked: the car holds better at standstill than the curve
  measured at speed.

Decided (user, 2026-10-14): the fallback as an opt-in road option for stops; step 3 scores both stop sets under both
friction models.

## 2b. Receive timing: cosim on the COM poll schedule (step 2b; reviewed with the user 2026-10-15)

User, 2026-10-14: *"use the same sim as the other session put together, but check its work yourself against the code
and data"*. The schedule is `codasim/io/comsched.py` (DLCM session, worklog 6H.74). Checked here independently, then
adopted in `codasim/cosim.py`.

**Firmware** (`coda_dlcm_prog.bin`, TriCore, disassembled read-only). Everything comsched states matches:
- the COM task 0x80068D3C calls TX main 0x80068B5C, then RX main 0x80068B0A;
- the RX countdown (0x80068072, mode 1) reloads from each record's period (+6), set at RX start 0x80067D66;
- the RX dividers in ComConfig 0x80041DA4: 0x208 / 0x200 / 0x300 / 0x330 every 4 calls (20 ms), 0x209 / 0x20B / 0x20C
  every 2 (10 ms), 0x275 / 0x276 every 20 (100 ms);
- the TX offsets: 0x212 / 0x210 / 0x418 / 0x315 / 0x278 period 4 offset 3; 0x308 / 0x312 / 0x204 period 2 offset 3;
  0x08C period 200 offset 3;
- ComRxCopy 0x8008008C is called at the top of the torque task (0x8007C29A), gated on a mode byte equal to 0x18.

**Logs, tested without comsched's code** (`artifacts/rx_poll_timing_check.py`):
- Brake pressure (161k frame pairs): a 0x208 frame moves the next 0x212 request at full weight when it arrives up to
  4 ms after a 0x212 burst, half at 4-6 ms, almost not at all later. That is a poll at +5 ms, not the +15 ms that
  delivery at arrival implies.
- Motor speed (4.6 M pairs): the DLCM's 0x308 speed echo carries the 0x1C0 frame caught by the poll 5 ms after a
  burst; the edge fit puts 0x20C's arrival 0.65 ms after the logged 0x1C0.
- Brake switch: 0x212's BrakeSW changes before 0x200's on 4,145 of 4,145 edges, so the DLCM's switch is not the
  polled 0x200 copy.

**Defect found in comsched, fixed by the DLCM session.** It rounded the poll instants onto codasim's 10 ms tick grid
before comparing arrivals. The logger and DLCM clocks drift about -4 ms per 300 s capture while 0x208 arrives at a
near-fixed phase, so over long stretches each poll caught a frame 10 ms early or late: 21.9 % of polls. After the fix
(true polls, only the delivery rounded) the residual is 3.8 %, and the DLCM session's brake-pressure replay error went
from 0.927 to 0.160 Nm.

**cosim** now uses the poll timing by default (`rx_timing="poll"`); the old rule is `rx_timing="arrival"`.
- Poll phases are anchored on the episode's own logged DLCM TX frames (0x308 for divider 2, 0x210 / 0x212 for 4, 0x08C
  for 20). The episode stores were rebuilt with the 0x08C frame times; otherwise byte-identical, plus one new reversal
  from a later capture.
- Parity: open loop, cosim matches `io/inputs` replay exactly (308 episodes, 854,248 ticks, 0 differences).
- A closed-loop call that passes the old speed delay without `rx_timing="arrival"` is refused.

**The 0x20C arrival offset** (`cosim.SPEED_ARRIVAL_US`). The DLCM reads its speed from M-CAN 0x20C
(AccurateFeedbacks_Mech), which is never logged; the logged stand-in is 0x1C0, the D-CAN relay of M-CAN 0x209. Scanned
against the reversed 0x308 echo over 308 episodes (`codasim_cosim_check.py` phase 2o):

| 0x20C after 0x1C0 | -3 ms | -1.5 ms | 0 | 0.65 ms | **1.5 ms** | 2.5 ms | 3.5 ms | 5 ms |
|---|---|---|---|---|---|---|---|---|
| SpeedRaw identical | 44.1 % | 57.8 % | 71.9 % | 77.2 % | **77.8 %** | 75.8 % | 72.5 % | 68.8 % |
| mean command error, Nm | 1.000 | 0.802 | 0.588 | 0.475 | **0.441** | 0.457 | 0.494 | 0.538 |

Decided (user, 2026-10-15): **1.5 ms**, the best direct match; sensitivity runs at 0.65 and 2.5 ms (the ends of the
flat stretch) replace the old 12 / 22 ms speed-delay bracket. No offset matches better than ~78 %, because 0x1C0 and
0x20C do not always carry the same value. The scan places 0x20C relative to the DLCM's poll only. HYPOTHESIS, not
observed (M CAN is not logged): the MCM sends 0x209 before 0x20C, and the relay puts 0x1C0 on D CAN within a frame
time, so 0x20C reaches the DLCM ~3-6 frame slots after the logged 0x1C0. Negative offsets fit clearly worse, which
agrees with that order.

**Re-runs on the poll timing at 1.5 ms**:
- Closed-loop reversal ring check (`codasim_cosim_check.py` phase 3p; rank correlation / sim:car / spread, all
  reversals, f7_clunk excluded): current-computed 0.61 / 1.23 / 7.7x (12 ms arrival: 0.59 / 1.20 / 8.4x); current-replay
  0.61 / 1.18 / 7.7x; msm 0.63 / 1.59 / 8.5x. At 0.65 ms the figures differ by <= 0.04 (spread up to 1.1x).
  Predicted resets in these runs: the 5 f7_clunk ones, plus 2 C4c_post_revert with replay bounds, as under the old timing.
- Step-2 stop checks (`regen13_screens.py` phase 2p): the section 2 figures to within 0.01.
- Reset sweeps (`ecm2_population_check.py`, open loop; the speed comes from the reversed 0x308, so the 0x20C offset does
  not enter): each car's own CAL, the same 3 f7_clunk resets at the same instants; C4c and K1+B25+FLAT31 on every drive,
  0; the f7_clunk CAL on every drive, 283 (281 before; the 2 extra on capture 20261010_161318, recorded after the old run).

## 3. Braked stops scored: C4c vs K1+B25+FLAT31 (step 3; reviewed with the user 2026-10-16)

Closed loop (cosim, preset current, computed bounds, COM poll timing with 0x20C at 1.5 ms after 0x1C0, sensitivity at
0.65 and 2.5 ms, `grade_fallback` on), both stop sets, both friction models, each CAL on every runnable stop
(`regen13_screens.py` phases 3 / 3b / 3c / 3d; worklog 3BP). f7_clunk excluded from the statistics.

**Resets and debounce: none.** 0 predicted resets in every configuration, and ECM2 reason-10 / reason-12 debounce max 0,
for C4c and K1+B25+FLAT31, both sets, both frictions, all three 0x20C offsets.

**What the stop ring measures** (`stop_ring_source.py`, recorded data, 635 `stop` stops). The plan's premise was that a
braked stop rings like a shift because the torque crosses the lash. The recorded ring does not track the crossing: ring
vs swing at the crossing rho +0.03, vs torque rate +0.06; stops with no return to positive torque ring at least as much
(p50 0.0051 vs 0.0016). It tracks how hard the car stops: vs decel over the last 0.3 s rho +0.29, vs pressure at
standstill +0.29. So the headline measures for stops are deceleration over the last 0.3 / 0.1 s before standstill and
stop time; ring is reported beside them.

**C4c vs K1+B25+FLAT31** (`stop` set; p10 / p50 / p90; p7 friction, measured friction within 0.02 unless stated):

| | C4c | K1+B25+FLAT31 | paired K1 - C4c |
|---|---|---|---|
| decel last 0.3 s, m/s2 | 0.69 / 1.11 / 1.46 | 0.66 / 1.05 / 1.28 | -0.30 / -0.12 / +0.10 |
| decel last 0.1 s, m/s2 | 0.64 / 1.09 / 1.46 | 0.55 / 0.82 / 1.05 | -0.54 / -0.30 / +0.15 |
| time to standstill, s | 1.00 / 1.51 / 2.17 | 0.96 / 1.34 / 1.93 | -0.30 / -0.13 / -0.03 |
| ring, (m/s2)^2 | 0.0069 / 0.0217 / 0.0397 | 0.0097 / 0.0253 / 0.0430 | ratio 0.85 / 1.08 / 2.06 |
| largest McmCommand change per tick, 0.1 Nm | 23 / 35 / 69 | 25 / 34 / 62 | |

- K1+B25+FLAT31 stops sooner, with a lower decel over the final 0.1 s. Its ring is higher by a median 8 % (higher in
  311 of 423).
- `stop_low` set: the same direction (decel last 0.3 s -0.06, last 0.1 s -0.12, stop time -0.18 s; ring ratio 1.17).
- C4c drives alone (20 `stop`, 42 `stop_low`) agree with the pre-campaign + stock stops in direction.
- The 0x20C offset moves no figure by more than 0.01.

**Model check against the recorded stops** (own CAL, `stop`, p7): stop time rho +0.82, sim p50 2.17 s vs car 2.22 s;
decel last 0.3 s rho +0.41 (sim p50 0.80 vs car 0.64); decel last 0.1 s rho +0.27 (sim 0.75 vs car 1.11: the model's
final 0.1 s is too soft). A torque crossing occurs in 365 car stops and 360 simulated ones; the simulated crossing
rate is faster (p50 43 vs 18 Nm/s).

**Per-episode divergence, now standard** (`codasim.scoring.divergence`, `divergence_flags`; user 2026-10-16). Population
medians and rank correlations passed a stop the user flagged by eye as ~0.7 s late (coda_20260524_120838_T0 t = 44.72).
Every closed-loop screen now reports, per episode: |car - model| speed RMS and max (mph, both 2 Hz low-passed), 0x330
RMS, and the standstill time error; and it lists the episodes flagged as **the model never stops**, **|dt_still| > 0.5
s**, or **speed gap > 1 mph**. On the step-3 run (own CAL, 992 stops): never stops 72, |dt_still| > 0.5 s 104 (> 0.3 s
281), spd_max p99 2.33 mph; the flagged stop ranks 19 of 992 by 0x330 RMS.

**Options added to the plant, both OPT-IN, defaults unchanged:**
- `plant/road.py stop_grade="parked"` (ramp 0.5 s; `cosim.run(stop_grade=, stop_grade_ramp_s=)`), **kept opt-in (user
  2026-10-16)**. The model's slope is the moving fit held constant after the anchor; over 180 D stops the model's
  lateness tracks model G minus the car's parked 0x330 slope (rho -0.51, `stop_grade_check.py`). The option ramps G to
  the parked slope. It runs on 224 / 423 `stop` and 396 / 597 `stop_low` (refused mostly because the car is not still
  for the 1.5 s parked window). There: |dt_still| > 0.3 s 56 -> 44 and 102 -> 58, p99 1.29 -> 0.68 s and 1.24 -> 0.93 s,
  no stop worse by > 0.2 s. The paired K1 - C4c measures do not move with it.
- `plant/vehicle.py BodyPlant(z_hold=)` (`cosim` `body_hold_z`): the body spring's damping while the wheel is held, so
  braked stops settle as the car's do. The car's 0x330 settles without overshoot after standstill; the "current" body
  (fitted to shift ring) overshoots +0.7 with ~10x the car's 4-6 Hz power (`body_rock_check.py`, `stop_ring_proto.py`,
  `stop_ring_plots.py`). Off: bit for bit. Default off; making it default is an open question.
- The flagged stop: no chock impact visible in the wheel speeds; any contact was below the wheel-speed floor
  (`chock_impact_check.py`).

**The 72 stops the model never completes** (`regen13_screens.py` phase 3d, against 832 stops of the same cohorts that
it does complete).
- Not the controller: open loop on the car's speed and closed loop both give the car's 0x212 request at its standstill
  to 0.1 Nm.
- 27 have 0x208 pressure 0 at the car's standstill (22 of them with the 0x212 brake switch on); controls 22 / 832. The
  plant's only friction there is R0 17.8 Nm against ~22 Nm of creep request; 17 of 27 are pushed through.
- 45 have pressure (median ~70): the plant would hold at standstill, but is still at ~94 rpm when the car has stopped,
  with model G ~20 Nm further downhill than the parked slope (controls 11).
- C4c and K1+B25+FLAT31 complete 65 / 72 and 72 / 72 of them; the candidate comparison above is unaffected.
- Park and the parking brake are not modelled and not reached: stops are in D on every frame of [t - 2, t + 4] s by
  construction, 0 of 387 stored reversals have P in their grid, and 0x052 ParkingBrake reads 0 on every frame of the
  72 windows.

**Braking below the 0x208 floor** (`brake_floor_check.py`, 1101 captures; `brake_signal_scan.py`):
- 0x208 BrakePressure reads 0 or >= 48 raw, never 1-47 (16.9 M samples at 0, none at 1-47, 3.7 M at >= 48). While
  braking and moving, 24 % of the time reads 0.
- With the brake switch on and pressure 0, friction decel (regen subtracted, rear-wheel speed) is real but small: press
  +0.040 m/s2 (CI +0.030..+0.060), release +0.069, brake off -0.009; +0.128 at 3-5 mph, ~0.04-0.06 above 5 mph. For
  scale, 48-63 raw gives +0.217.
- No other logged value reads brake pressure without that dead zone (D, B, C buses; bytes, 16-bit, 12-bit and
  nibble-split fields). Only 0x208 itself and the DLCM's 0x312 track pressure, both with <= 3 values in the hidden zone.
  M CAN is not logged.
- Stock creep at standstill depends on pressure, not on how long the brake is held (flat out to > 8 s): 0x212 request
  p50 22.8 Nm at pressure 0, ~10 at 48-99, 2.8 at 100-199, 0 at >= 200. C4c requests <= ~2 Nm at every pressure.
- **Not modelled (user, 2026-10-16).** No logged signal gives the size of the hidden-zone friction; it could only be
  inferred from the wheel-speed deceleration that the screens are scored against. The plant keeps BrakeSW out of its
  inputs.
- The measured friction curve's points at 5 / 14.8 / 24.8 / 35.0 / 45.3 raw (`regen13_inputs.p3.json`, `FRICTION_MEAS`)
  are 2 Hz low-pass values across the 0 -> 48 jump, not readings. They do not affect the plant, which is fed held raw
  0x208 counts (never 1-47): removing them moves the friction at 48-55 raw by <= 0.0006 m/s2. The peer's brake-blend
  design now uses a quadratic fit on 48-400 raw instead.

Decided (user, 2026-10-16): per-episode divergence and its three flags standard for every closed-loop screen;
`stop_grade` stays opt-in with the 0.5 s ramp; the hidden-zone friction is not modelled; step 3 closed.

## 4. The peer's candidate K1+B25+FLAT31+R13P10+BBSW20P256 (step 4; reviewed with the user 2026-10-17)

Candidate md5 13679c3c4bc82caf2317749cb3e698f3 (the peer's step 4, supersedes BBFE144), against C4c (the reference)
and K1+B25+FLAT31 (its base). Closed loop (cosim, COM poll timing, 0x20C at 1.5 ms after 0x1C0, sensitivity 0.65 / 2.5
ms where stated), `regen13_screens.py` phases 4a-4v; worklog 3BQ. f7_clunk excluded from the statistics, included in
the reset counts. **Verdict: PASS** under the grading below (`regen13_screens.p4v.out.txt`). Nothing flashed.

### Independent rebuild and reset sweeps

- `bbsw20p256_rebuild.py` (the peer's builder not imported) re-implements R13P10 and BBSW20P256 from the stated rule
  on K1+B25+FLAT31: **md5 identical**, 482 bytes changed vs the base, all in PedalD x / z, BrakeD z and their ECM2
  twins. It needed the speed-axis constant the peer then stated (motor rpm = axis count / 2.203); the documented 2.000
  x 282/256 = 2.203125 moves one 49.6 mph cell by 0.1 Nm (worklog 3BQ).
- `ecm2_population_check`: quick check (phase 6) 16 captures, 0 predicted; full sweep (phase 4) 868 captures run, 0
  predicted resets (233 skipped: 189 BusError, 44 too few 0x212 frames; 2 replay errors, ValueError).
- 0 predicted resets and ECM2 reason-10 / 12 debounce max 0 in every closed-loop phase below (about 8,800 candidate
  runs).

### The grading system (user, 2026-10-17)

Replaying the recorded foot through a CAL other than the one it drove is not a fair test: the driver presses
differently when the pedal curve changes (user: *"I'll change my pedal usage when the curve change"*), and on a shift
the pedal is not in the loop (*"pedal is not in the loop during shift"*). The user's framing: *"off the line is graded
by unfiltered requested torque. shift clunk is graded by pedal at 0% travel with brake pressed ... off the line and
after shift pedal application should have similar behavior"*.

| What | Graded by | Phase | Gate |
|---|---|---|---|
| Pull-away: standing launch and drive-off after a shift | A4 at an equal unfiltered request (adapted driver), clock from the recorded foot's 5 % press | 4e | gated (median <= +0.020 s, p90 <= +0.050 s vs C4c) |
| Filter lag | A4 from each CAL's own request rise | 4e | reported |
| Shift clunk | A7 ring, pedal 0 from the shift on, brake held at its value at the shift | 4c `hold` | reported, not gated |
| Ring after drive-off and on launches | A7-style ring | 4e | reported |
| Braked stops | decel last 0.3 / 0.1 s, stop time, ring | 4s | reported |
| Static and synthetic | A2 / A3 / A5 / A6, standing launch, cap | 4a | as declared |
| The recorded foot | A7 / A4 on the recorded inputs | 4r / 4l | context only; gate on resets |

Any predicted reset rejects the candidate in every phase.

**The adapted driver** (`cosim` `pedal_remap=<reference image>`, opt-in, user *"do option 2"*). At each 0x210 sample
with the foot on and the gear in D or R, the sink finds the smallest pedal byte (>= 1, never foot-off) at which the
running CAL's map gives at least the torque the reference map gives for the recorded pedal at the same speed index
(exact search over the map's pedal cells; any map shape). Foot-off, other gears and identical maps pass through; the
run reports how many samples were remapped, saturated or clamped to the minimum press, and the largest overshoot
(<= 1.9 Nm here). The paired requested steps agree to a median +1.1 Nm (shifts) and +0.9 Nm (launches) against C4c.

### Pull-away (4e; gated): pass

CAND - C4c, paired, median / p90 (s):

| | n | cmd50 | cmd90 | wheel 50 | wheel 90 | ring CAND / C4c |
|---|---|---|---|---|---|---|
| drive-off after a shift | 269 | +0.000 / +0.020 | +0.000 / +0.020 | +0.000 / +0.016 | +0.001 / +0.022 | -25 % median, lower in 71 % |
| standing launch | 756 | +0.000 / +0.000 | +0.000 / +0.000 | +0.000 / +0.001 | +0.000 / +0.003 | +1 %, lower in 44 % |

- Against K1+B25+FLAT31: p90 <= +0.010 s; ring unchanged.
- Filter lag (reported) passes the same limits.
- Rollback on launches: 5 launches roll back more than 0.3 mph (max 0.47); C4c 0 (max 0.25); K1+B25+FLAT31 the same 5.

### Shift clunk (4c `hold`; reported)

| CAND vs | all (n 300) | R->D (n 186) | D->R (n 114) |
|---|---|---|---|
| C4c | -72 % [-97, 0], lower in 87 % | -73 %, lower in 84 % | -71 %, lower in 92 % |
| K1+B25+FLAT31 | 0 % | 0 % | 0 % [-11, +34] |

CAND is worse than C4c on 20 of 300 shifts. With the brake as recorded (`rec`) instead of held: -67 %, lower in 81 %.

**What the car does at a shift** (phase 4b, recordings, 380 headline reversals; p50 unless stated):
- Pedal 0 at every shift. Brake switch on at 365; at the other 15 the switch dropped within 10 ms of the shift with
  pressure still 80-336 counts. Pedal and brake are never on together.
- Pressure at the shift 182 counts (p10 77, p90 292); 24 shifts read 0 at that instant.
- The car is still rolling the old way, 0.41 mph median magnitude (|v| < 0.3 mph at only 35).
- Brake on 1.1 s before the shift, released 0.29 s after; first pedal 0.60 s after (0.25 s after the release).
- 348 shifts have pedal inside 2.0 s of the shift, i.e. inside the old A7 ring window; 71 of 380 car impacts come
  after the first pedal (drive-off clunks, not the shift's).

**The mechanism -- a HYPOTHESIS approved by the user 2026-10-17, to be verified in car data once creep-off data
exists** (user: *"needs to be verified in data - once we have the creep off data"*):
- C4c's creep (CalCreepEnable 1, CalCreepBrakeOk 1, so it runs with the brake on; K1+B25+FLAT31 and the candidate have
  CalCreepEnable 0) drives 30-150 Nm against the wrong-way roll right after the shift. Every recorded cohort has creep
  enabled.
- The model reproduces the car's 0x212 at the shift (phase 4m, own CAL, recorded inputs, n 297): peak 45 Nm car vs
  45 model (p90 96 vs 111), both at 0.40 s; model - car +2.5 Nm median, Spearman 0.89.
- The car's impact falls near the torque onset (first 0x212 >= 10 Nm, 0.15 s) in 172 and near the end of the wrong-way
  roll in 137 of 309 pre-pedal impacts (phase 4n).
- Without creep the driveline carries about -5 Nm and the clunk left is the brake stopping the roll: the impact is
  0.04-0.06 s after the wheel sticks (phases 4n, 4h).
- **Time in neutral** (user: *"this may be dependent on how much time is spent in neutral"*): 0.16-0.30 s (p10-p90)
  on every recorded shift, and no relation to impact timing (Spearman -0.02). Longer neutrals are not in the data, so
  the dependence is untested.

**The body's held-wheel damping, now the default** (`cosim` `body_hold_z=1.0`, `BODY_HOLD_Z`; user 2026-10-17
*"agree"*; was opt-in since step 3). Off, the body over-rings after the wheel sticks. Phase 4h, own CAL against the car:
model / car shift ring median 1.23 -> 0.99, Spearman 0.61 -> 0.62. CAND vs C4c (4c `hold`) moves from -37.5 % (worse on
84) to -72 % (worse on 20); vs K1+B25+FLAT31 0 % either way. Still to be checked against creep-off car data.
`body_hold_z=None` gives the old body; with `plant=` it must be passed as None. Phases 4c, 4e and 4s ran with it;
4m, 4n and 4r / 4l predate it (4h runs both).

### Braked stops (4s; reported)

p7 friction, 0x20C 1.5 ms (on `stop` the measured friction moves these by <= 0.01; the 0.65 / 2.5 ms offsets move
stop time by <= 0.03 s). Paired medians:

| | set | n | decel last 0.3 s | decel last 0.1 s | stop time | ring ratio |
|---|---|---|---|---|---|---|
| CAND - K1+B25+FLAT31 | `stop` | 423 | -0.000 | -0.000 | +0.07 s | 0.99 |
| | `stop_low` | 569 | +0.000 | +0.000 | +0.03 s | 0.99 |
| CAND - C4c | `stop` | 423 | -0.12 | -0.29 | -0.05 s | 1.06 |
| | `stop_low` | 562-569 | -0.07 | -0.11 | -0.14 s | 1.11 |

The CAND vs K1+B25+FLAT31 differences are the same as before `body_hold_z` became the default.

### Static and synthetic (4a)

- A2 (regen not reduced) fails at 6-31 mph by design: the candidate is graded by C1 / C2 there.
- A3 zero crossing 0.04 / 0.05 / 0.05 s at 500 / 1000 / 2000 rpm: pass.
- 100 % standing launch cmd90 0.29 s vs C4c 0.26 s, shared with K1+B25+FLAT31 (its 326.8 Nm request step against C4c's
  300); torque capped at 300 Nm.

### Context: the recorded foot (4r / 4l)

Kept for reference, gated on resets only (0). On recorded inputs, A7 ring CAND / C4c -38 % (lower in 70 %), with the
recorded pedal inside the ring window on most shifts. A4 from the start of the drive request (option 1) and from the
CAL's own request rise are reported there; both are superseded by 4e.

Decided (user, 2026-10-17): the grading system above; the creep mechanism recorded as a hypothesis pending creep-off
data; `body_hold_z` 1.0 the default; step 4 closed (*"close it!"*).

## 5. Summary for the parent plan's step 6 (step 5; reviewed with the user 2026-10-17)

The model screens of K1+B25+FLAT31+R13P10+BBSW20P256 (md5 13679c3c4bc82caf2317749cb3e698f3) against the parent plan's
acceptance criteria (`../plans/next_flash_regen13_brake_blend.md`; C4 refers to the base's A-criteria in
`../plans/next_flash_from_c4c.md`). Detail in section 4; worklog 3BQ, 3BR. Nothing flashed.

| criterion | result | status |
|---|---|---|
| C5 / A1 resets | 0 predicted: quick check (16 captures), full sweep (868 drives), ~8,800 closed-loop candidate runs incl. stops; reason-10 / 12 debounce 0 | pass |
| C6 independent rebuild | rebuilt from the stated rule, md5-identical; 482 bytes changed vs the base, all in PedalD / BrakeD and their ECM2 twins | pass (twin and rule-1 checks: the peer's step 4) |
| A3 zero crossing | 0.04 / 0.05 / 0.05 s at 500 / 1000 / 2000 rpm vs C4c 0.05 | pass |
| A4 pull-away at equal unfiltered request (gated) | drive-off after a shift p90 +0.022 s, standing launch p90 +0.003 s, medians 0 | pass |
| A4 synthetic standing launch | 35 % and 50 % pass; 100 %: cmd90 0.29 vs C4c 0.26 s, time to 100 Nm equal (0.09 s) | not gated (below) |
| A7 shift clunk, pedal 0 and brake held (reported) | -72 % vs C4c; 0 % vs K1+B25+FLAT31 | holds |
| braked stops (the 2026-10-13 review gap; reported) | vs K1+B25+FLAT31: stop time +0.07 s (`stop`) / +0.03 s (`stop_low`); decel and ring unchanged | reported |

**The 100 % synthetic launch** (user 2026-10-17, confirmed): it misses the base's synthetic sub-criterion (cmd90 no
more than +20 ms) by 10 ms because the request is bigger (a 326.8 Nm step against C4c's 300, so 90 % of it is reached
later), not because of extra lag; time to 100 Nm is identical. Inherited from K1+B25+FLAT31, whose write-up did not
report this line. Not gated under the equal-request grading.

**Caveats to carry:**
1. Phases 4e and 4c ran at the 1.5 ms 0x20C arrival only. On the recorded-foot runs (4r / 4l, all three offsets) the
   0.65 / 2.5 ms offsets moved A4 by <= 0.01 s and the shift-ring change by <= 1.5 points; on stops (4s), stop time by
   <= 0.03 s.
2. The -72 % shift-clunk figure depends on `body_hold_z` 1.0 (-37.5 % without). That default and the creep mechanism
   (section 4, a hypothesis) are unverified until creep-off car data exists.
3. Launch rollback: 5 launches past 0.3 mph (max 0.47), the same as K1+B25+FLAT31; C4c 0. Rollback is not a criterion.
4. Stop-model limits from step 3: the model never completes 72 stops, its final-0.1 s decel is too soft, and friction
   below the 0x208 floor is not modelled.
