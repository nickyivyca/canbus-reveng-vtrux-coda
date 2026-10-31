# codasim — one executable model of the Coda DLCM, driven by real logs, coupled to the plant

Decision (user, 2026-10-09): *"cut over to the full python model, the csv just becomes a
programmatic access lookup table. no shims."* Plan: `../../notes/plans/codasim_full_model.md`.
Findings: worklog `../../notes/dlcm/artifacts/flash7_diagnosis_worklog.md` §6H.62–6H.65.
**FLASHING IS NOT AUTHORISED.** This package produces a model, never a flash.

Two sessions write it, split by file; neither edits the other's files.

- **[DLCM]** is `Coda DLCM work`.
- **[LASH]** is `Coda drivetrain lash model`.
- **[JOINT]** files change only after the other session acknowledges.

Scripts that use it live in `notes/<topic>/artifacts/` and add `projects/coda/tools` to `sys.path`.

## File layout

| Path | Owner | What it is |
|---|---|---|
| `fixedpoint.py` | DLCM | TriCore integer semantics: s16/u16/s32 wrap, saturate, `divu` (dvinit.u+dvstep.u), `div_trunc` (dvadj), `ld_h`/`ld_hu` register values |
| `lut.py` | DLCM | The firmware's table lookups, transliterated from the listing: `lut1d_signed` (0x80052284 / 0x8005F082), `lut1d_unsigned` (0x80052370 / 0x8005EFD0; it **interpolates**), `lut2d` (0x8005246A / 0x8005F3DA; X unsigned, Y signed), `lut1d_wavg_u` (0x8005EF50, weighted-average floor), `lut1d_signed_yu` (0x8005F138, u16 result) |
| `image.py` | DLCM | A PROG + CAL pair (`Image("stock" / "c4c" / "f7" / path)`), descriptors read at firmware widths, recorded what-if CAL edits |
| `symbols.py` | DLCM | `dlcm_symbols.csv` as the lookup table: name ↔ address, type, span. `var()` refuses an untyped row |
| `ram.py` | DLCM | DLCM RAM keyed by real address; stores narrow to the declared type; overlap raises; `assume()`; `unsourced()` lists variables read but never written |
| `clock.py` | DLCM | Integer-µs discrete-event scheduler. Same-instant order: RX < TASK < TX < ACT < PLANT < SENSOR |
| `interfaces.py` | JOINT | Contracts: `Plant`, `Actuator`, `Sensor`, `InputSource`, `LoadSource`, `Controller`; `Provenance` (incl. `SUBSTITUTE`: a different logged frame standing in for an unlogged input); `Load`; `GEAR418_*` |
| `io/logreplay.py` | DLCM | Capture → sorted per-(bus, id) streams; bus identified by audited anchors (≥ 2 of one bus AND zero of every other, else unresolved) |
| `io/inputs.py` | DLCM | Plays a capture into a Controller's sinks on the clock, with the timing rule below. `FEEDS` (lash-keyed) plus `COMPUTED_BOUND_FEEDS` = `BOUND_FEEDS` (0x275 / 0x276 via the B-CAN DBC, 0x200 B0; raw) + `SUBSTITUTE_20B_FEEDS` (0x1C0 HV_Current / HV_Voltage standing in for the never-logged M-CAN 0x20B words; user decision 2026-10-09, worklog 6H.69.5), passed as `extra` and used by default when the controller computes its bounds (the default) |
| `io/comsched.py` | DLCM | The COM stack's receive-poll schedule (worklog 6H.74), read from the firmware's COM RX/TX tables (`ComConfig`): poll divider per RX record, TX period/offset per TX record, poll instants anchored on logged TX bursts (0x308 / 0x210-0x212 / 0x08C), delivery = true poll + 10 ms, rounded onto the tick grid only after the comparison with arrivals. `ARRIVAL_OFFSET_US` holds the declared 2 ms estimate for the 0x1C0 stand-in. Used by `io/inputs.py` (`rx_timing="poll"`, the default) and available to `cosim.py` |
| `dlcm/` | DLCM | The 10 ms torque task, one module per firmware function; `controller.py` is the `Controller` (see its docstring for what is and is not ported) |
| `dlcm/accel.py` | DLCM | The accel limiter 0x800750E8 (+ 0x80075394 bounds, 0x8007566E, 0x80075896 speed cap) -> AccelTermNeg/Pos, added after 0x212 into the MCM command (plan step 5b). Its input, the measured acceleration 0xD0006A28, is the accel path now ported in `dlcm/speed.py` |
| `dlcm/speedrx.py` | DLCM | Tick member 0x8006F870's copies from the M-CAN RX buffers: SpeedRaw (0x20C) and the two 0x20B words Mcm20BW0 / Mcm20BW1. It runs BEFORE TrqSpeedTask, so PROG and ECM2 see the same tick's speed (worklog 6H.68) |
| `dlcm/boundsrc.py` | DLCM | The seven bound-source functions of BoundsTask (plan step 6): 0x80077598, 0x80076EC6, 0x80076DC2, 0x800774AA, 0x80076D72 (+ 0x80076BE6, 0x80076A92, slew 0x80076A18), 0x8007729A, 0x800771FA. Run with `DlcmController(bounds="computed")`, the default since 2026-10-09 (worklog 6H.70); `bounds="replay"` keeps AB4/ACA from 0x312 instead |
| `dlcm/rxdecode.py` | DLCM | PROG-side receive decodes: `Brake208Copy`, FUN_8006ED3C's 0x208 part. It turns the PDU buffer into BrakeAnalog (unscaled) and BrakeAnalogValid (valid bit && fresh && != 0xFFF), and runs always. The bound chain's reads: the 0x300 decode 0x8006F05A, the 0x200 B0 bit 2 flag, the 0x275 / 0x276 copies. The 0x208 sinks fill the PDU buffer, and ECM2 (`ecm2/canread.py`) reads that same buffer. The COM copy FUN_8008008C refreshes every RX buffer once per tick at 0x8007C29A, before both readers (worklog 6H.73) |
| `dlcm/gate.py` | DLCM | Tick member 0x800704AC: the RunState gate on the MCM command (0xD00068C0), which Publish turns into 0xD00069D0 |
| `ecm2/` | DLCM | ECM2, the internal torque monitor (plan step 5), called inside the torque task after Publish: `snapshot`, `speed`, `canread`, `gear` (c11 substituted), `limits`, `target` (b70/b64, reasons 10/11), `limiter` (b8c), `reason12`, `reason15` (Ecm2LimiterOutputConsumer band b46/b48 with exits aaf/ab0, plus Ecm2Reason15: over-speed 968, enables 96e/96f, channels A/B, 1.00 s detector; a0-0x967 held 0 as an ASSUMPTION; reason 16 not ported; lash session 2026-10-27, its worklog 3BT), `reaction` (a reset halts the controller), `task` (order), `common` (debounce, Q14 IIR) |
| `plant/`, `sensors/`, `actuator/` | LASH | Driveline/vehicle plants, road load, speed and accel sensors, the MCM. Each has its own `README.md` |
| `episodes.py` | LASH | Rolling R<->D reversals (default) or standing launches in D (`kind="launch"`, `find_launches`; t_us = brake release) from raw captures: series at log time, D bus via `io/logreplay`; `COHORT_CAL` (moved from `rd_shift_episodes.CAL`); `grid()` gives the 10 ms views. Stores (regenerable): reversals `notes/dlcm/artifacts/codasim_episodes.npz`, launches `notes/dlcm/artifacts/codasim_launch_episodes.npz`. Braked stops (2026-10-14, lash session): `kind="stop"` (anchor ~5 mph after > 10 mph) and `kind="stop_low"` (anchor ~3 mph after > 5 mph within 15 s), both via `find_stops(S, anchor_rpm, from_rpm, from_us)`. Stores `notes/dlcm/artifacts/codasim_stop_episodes.npz` (635 stops, 423 runnable) and `codasim_stop_low_episodes.npz` (857, 598 runnable); write-up `notes/dlcm/regen13-model-screens.md` section 1. Recorded 0x330 ring is undefined for ~58 % of stops (raw 255 for ~0.12 s about 0.6 s after standstill); simulated ring is unaffected |
| `cosim.py` | LASH | Closed-loop co-simulation on `codasim.clock` (plan step 4): `DlcmController` (bounds passed explicitly) at the capture's task phase; an open-loop lead-in on recorded inputs from the episode's quiet point (no warm-up); at the handover (first 0x1C0 frame at or after t_shift - 2 s) the `0x1C0.Motor_Speed` input switches from the recorded frames to the plant's `EdgeSpeedSensor`, delivered after a DECLARED 12-22 ms speed delay; `McmDelay` applies the gear from the model's own 0x418 (`ctl.gear418()`). Results carry shaft and applied torque per ms. All other inputs stay recorded (open loop w.r.t. the plant). A predicted ECM2 reset ends the run. Since 2026-10-17 the body's held-wheel damping is the default (`BODY_HOLD_Z = 1.0`; `body_hold_z=None` gives the old bare body bit for bit; `plant=` with a non-None `body_hold_z` raises). Opt-in `pedal_remap=<reference CAL>` (`PedalRemap`, an adapted driver): each recorded pedal becomes the reference CAL's request at the current speed, and the pedal the run's CAL needs for that request is delivered; off by default |
| `scoring.py` | LASH | Impact / ring / spectrum measures and the model-check statistics; per-episode car-vs-model divergence and its standard flags |
| `scorecard.py` | LASH | The closed-loop parts of the scorecards (`notes/dlcm/candidate-criteria.md`): S1 shift clunk with the brake held, S2 equal-request A4 plus the zero crossing, each as a call taking (cal, ref); the measures moved from `next_flash_score` / `next_flash_response` (worklog 3BS). The card script is `notes/dlcm/artifacts/candidate_scorecard.py` |
| `tests/test_lut.py` | DLCM | Lookups vs hand cases (the sweep against the old float model went with `torque_path_sim` at step 7) |
| `tests/replay_vs_car.py` | DLCM | A raw capture end to end through `io.inputs`; model 0x212 vs every recorded frame. Default: the computed bound chain with the 0x1C0 substitute for 0x20B; `--replay-bounds` replays AB4/ACA from 0x312 |
| `tests/brake_regen_vs_car.py` | DLCM | The regen limit at speed, model vs car (2026-10-14): a capture through `io.inputs` on the CAL it ran (optionally a candidate on the same inputs); per recorded 0x212 frame the model and car request, model and car 0x312 M_MIN, delivered 0x1C0 Torque, map target and coast value. Masks `brake on` and `map > limit` (map target for the recorded inputs deeper than the car's own M_MIN, so selected without using model output), by speed band 12.4-31 / 31-50 / 50+ mph. Corpus driver: `notes/dlcm/artifacts/regen13_step4.py` phases 6-7 |
| `tests/ecm2_gate.py` (+ `.out.txt`, `ecm2_gate_stock.out.txt`) | DLCM | Step-5 gate: predicted ECM2 resets vs recorded, on the f7 and C4c drives under both calibrations, and on the four true-stock reset captures |

## Rules (plan R1–R7; each is a failure mode already paid for)

1. **Mirror the code.** One module per firmware function. Addresses come by symbol name, never as literals.
2. **Integer-exact.** Every DLCM variable has a declared width and sign. Floats exist only on the plant side and in unit conversion.
3. **Each table read names its firmware entry point.** There are two 1-D behaviours (signed, unsigned) and one 2-D, all interpolating.
4. **Every input declares its provenance.** The classes are `received`, `reversed`, `plant`, `estimated` and `replayed-output`. `Controller.header()` lists them all, plus every assumption, every unported function, and every variable read but never written.
5. **Timing is explicit** (see below).
6. **Parity before replacement**, then the car decides.
7. **Bus by content.**

## The replay timing rule (`io/inputs.py`)

- **Published frames** (0x210, 0x418, 0x308, 0x312) carry the value **the tick that sent them** used, so they are delivered to that tick. Each tick runs 5 ms before its TX burst; frames are shifted −7.5 ms.
- **0x308** carries the 0x20C buffer of its sending tick (SpeedRaw is refreshed at the start of the tick), so it takes the plain −7.5 ms shift. Worklog 6H.68 withdraws the extra −10 ms that 6H.67.1 had.
- **The 20 ms frames** (0x210, 0x418): the unseen in-between tick takes the next frame's value (a further −10 ms). This is a declared estimate.
- **Received frames** (0x208, 0x300, 0x200, 0x275, 0x276, and the 0x1C0 stand-in for 0x20B) reach the tick on the firmware's COM RX poll schedule (`io/comsched.py`, worklog 6H.74). The COM task polls each record every n x 5 ms (2 for M-CAN, 4 for ESC, 20 for 0x275 / 0x276). A frame reaches the tick 10 ms after the first poll at or after its arrival. Checked against the logs: 0x208 -> 0x212 0.93 -> 0.16 Nm while pressure moves; 0x312 M_MIN 0.143 -> 0.043 Nm (after the 2026-10-14 rounding fix, worklog 6H.74.6). `rx_timing="arrival"` keeps the old at-arrival rule. `cosim.py` (LASH) uses the same poll schedule by default since 2026-10-14 (`rx_timing="poll"`).
- **BrakeSW** is reversed from 0x212 (the DLCM's own copy of its brake-switch pin), replacing the 0x200 feed.

**Interface used by the lash session:** `episodes.py` (LASH) imports `FEEDS`, `RAW_SIGNALS`, `ALIGN_US`, `DBC`, `COMPUTED_BOUND_FEEDS` and `B_DBC` from `io/inputs.py`, and `cosim.py` (LASH) imports `FEEDS` and `COMPUTED_BOUND_FEEDS` with their shifts and provenance. `episodes.py` stores rows at log time, so the shifts in these feed lists stay the single source of timing. Tell that session before renaming or restructuring any of these names, or changing a feed's shift or provenance.

**Reset screen used by the lash session** (adopted by its user 2026-10-10, worklog 3BE): `ecm2_population_check.py` phases 4-6 replay every drive (and a 16-capture quick set, `ecm2_quickset.json`) through `io.inputs` into `DlcmController` with computed bounds; any predicted ECM2 reset rejects a candidate. Tell that session before changing anything in `dlcm/`, `ecm2/` or `io/` that could move a reset prediction, so it can re-run the screen for both CALs.

## Resets (plan step 5)

**Captures the model cannot decode are dropped, not supported** (user, 2026-10-09: *"I'd rather drop the weird logs rather than support them - or trim them in special cases if they're useful to us."*). The replay and the sinks raise on an empty feed or an out-of-table value (e.g. 0x418 GearStatus 0xDF, PRND 0xFF, in the last 3.3 s of `coda_20260715_162457_T0`); a caller drops that capture, or trims it to its decodable span where it is useful. Decoders are not widened to accept such values.

A predicted ECM2 reset halts the controller and is reported in `controller.resets`. The user's rule (2026-10-09): a reset on a candidate profile rejects it, so recovery is not modelled.

Result on `coda_20261004_165539_T0` (C4c): 0x212 mean |err| 1.71 → 0.43 Nm. On the held-out f7 drive before its first reset: 0.16 Nm.
