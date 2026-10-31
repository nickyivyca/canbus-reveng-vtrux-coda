# Flash 7 — why the DLCM reset seven times and shut the motor off

Flash 7 (`artifacts/cal_candidate_f7_clunk_on_c4c.bin`, on the car 2026-10-04
16:10:23 to 16:27:01) produced seven DLCM resets in 158 s of driving and then
the Permanent Shut-off Path: the MCM's 12 V was cut and did not return until
a 12 V cycle. This file records the cause, the evidence for it, and the rules
it imposes on every future CAL change. Established 2026-10-08 by the
`Coda DLCM fault path trace` session (worklog
`artifacts/flash7_reset_trigger_worklog.md`), on top of the reaction-chain and
firmware reads of the `Coda DLCM work` session
(`artifacts/flash7_diagnosis_worklog.md`, cited by section). Promoted with
the user's approval the same day.

**One sentence.** Flash 7 switched on a three-stage lag filter (7a) between
the DLCM's rate limiter and its published torque command; the safety
supervisor ECM2 has no copy of that filter, so on a sharp pedal release at
walking pace the published command froze while ECM2's own allowance kept
falling, the gap exceeded the supervisor's tolerance, and ECM2 reset the
module — seven times, which is the calibrated cap.

Units: one internal count = 0.1 Nm; the published `0x212` unit is 0.25 Nm.

---

## 1. The chain, end to end

Every link below is either a firmware read (DLCM session, section cited) or a
measurement on the captures (this session, section cited).

```
pedal released to 0 % at |rpm| < ~310            [measured, S3]
  -> raw demand 0xD0005166 lands at +20..+48 counts (the coast row),
     inside 7a's slow band [0, 130]              [demand model, S3]
  -> 7a (FUN_80075F56, enable 0xA0021545 = 1, gain LUT 0x80043F88)
     switches from pass-through to alpha = 0.1 x 3 stages
     with its states charged to the pre-release command   [6H.38.7, 6H.52]
  -> published 0x212 FREEZES at 550..2385 counts (S-shaped onset)  [S2]
  -> ECM2's allowance b8c, slewed by the SAME tables but with NO filter,
     keeps descending at the down V-curve rate     [6H.38.5, 6H.54.1]
  -> |cmd| > |b8c| + 300 (0x80040A60) for > 5 ticks (0xA0021CDC)
     = ECM2 reason 12, FUN_80056C20                [6H.9, 6H.28, 6H.33]
  -> Ecm2SafetyDisableOrChain FUN_80055A3E, gated on occurrence count
     0xD0008642 < CAL 0xA0021D8C = 7              [3AM.3]
  -> FUN_800561E0 -> FUN_800552BC -> FUN_800569CC -> FUN_8008CC60(0xA2)
     = module reset, ~0.435 s dark, MCM 12 V cycled (~0.875 s)   [3AM.1-2, 3AM.7]
  -> on reboot FUN_8005ABAC restores the mirror and reports P3115  [3AM.5]
  -> after the 7th, the Permanent Shut-off Path: MCM enable stays off  [3AB, 3AI.1]
```

The driveline oscillation that the driver felt is a **sibling effect** of the
same filter (7a's lag inside the creep loop, 6H.52-6H.53), not a cause of the
resets. Nothing in the chain above reads an oscillation.

## 2. The seven resets are seven releases, and the command froze at each

Resets located from the data as `0x212` gaps > 0.3 s; they agree with the
DLCM session's windows to the millisecond. At 20 ms resolution
(`artifacts/reset_trigger_transients.py` p1):

| reset | t (s) | pedal in the last 0.2 s | gear, rpm | cmd at pedal-0 (counts) | descent before -> after (counts/s) |
|---|---|---|---|---|---|
| 1 | 26.429 | 24.8 -> 0 | D, 58 | 638 | 5125 -> 225 |
| 2 | 34.901 | 21.6 -> 0 | D, 234 | 552 | 2875 -> 175 |
| 3 | 42.306 | 72 -> 0 in 80 ms | D, 124 | 2378 | 6100 -> ~375 |
| 4 | 63.772 | 89 -> 0 in 160 ms | D, 300 | 2085 | 9100 -> ~600 |
| 5 | 68.007 | 31 -> 0 in 60 ms | D, 177 | 898 | 3700 -> 1100 |
| 6 | 180.702 | 46 -> 0 in 100 ms | R, -116 | 2385 | 5475 -> 225 |
| 7 | 184.178 | 30 -> 0 | R, -271 | 850 | 6850 -> 1225 |

Brake pressure 0 and BrakeSW 0 throughout all seven. While the pedal was still
above ~10 % the command descended at the limiter's -100 counts/tick; the sample
the pedal reached 0.0 % it stopped. An earlier reading of resets 3, 4 and 6 as
tip-ins and 5 as steady pedal (worklog 3AC) came from 0.1 s sampling and is
withdrawn: they are tip-in or launch **followed by** a sharp release.

**The discriminator, over every release in both drives** (p4): f7 drive 33
releases to 0 %, C4c same-day drive (`coda_20261004_165539_T0`) 20. The seven
resets are exactly the f7 releases whose post-release descent fell below
~1300 counts/s with the command still above the 300-count tolerance. Every
other release in both cohorts kept descending at 1375-12000 counts/s.

## 3. Why those seven: the demand lands in 7a's slow band

7a's gain schedule under f7 is pass-through (k = 1.0) for demand <= -20 counts
and >= 140, and alpha = 0.1 per stage inside [0, 130] (worklog 6H.52.3).
**The band is two-sided, and the lower edge is what makes the mechanism
predictive rather than descriptive:** a release whose demand goes straight
to regen (below -20 counts) never engages the lag, and one whose demand
crosses the band and leaves it at the bottom un-freezes within a few ticks.
The pedal-map coast row (pedal 0, no brake; `dlcm_demand.Demand`, flag 0) is:

| rpm | D (counts) | R (counts) |
|---|---|---|
| 0 | +50 | +50 |
| 200 | +43 | +25 |
| 300 | +26 | +8 |
| 350 | -53 | -55 |
| 500 | -397 | -243 |

So **a release below ~310 rpm lands inside the band; above it the demand is
already regen and the filter is transparent.** Modelled demand at the pedal-0
sample (`artifacts/release_freeze_7a.py` p5): the seven resets +20..+48, all
in band; the six low-speed releases that did not freeze (45.85, 60.21, 74.86,
79.00, 81.86, 87.37 s) were at 345-504 rpm with demand -48..-414, out of band.
Two of them touched the band for ~60 ms and left it (R, at the edge), froze
for ~60 ms and then dropped — too short for the 5-tick debounce.

The C4c drive has five releases that meet the same conditions (56.53, 59.08,
61.41, 64.29, 147.81 s; cmd 552-2142, |rpm| 55-148, demand in band) and none
froze, because the filter is disabled in C4c.

## 4. The freeze is the firmware filter, shown from the bus alone

With the limiter's real down V-curve as the filter's input, a three-stage
cascade at alpha 0.1 on a 10 ms tick reproduces the recorded post-release
`0x212` to an RMS of 7.0 / 4.8 / 7.6 / 14.2 counts on resets 1, 2, 6, 7.
Alternatives: 5 ms tick 52-101, 20 ms tick 9-33, two stages 39-77, alpha
0.05 11-38, pass-through (what C4c does) 244-592. The configuration read from
the image is the best fit on every reset with a long enough record.

## 5. The replay: C4c's command through 7a, and the whole path forward

**C4c command through 7a** (`release_freeze_7a.py` p6): C4c's `0x212` is the
limiter output (filter off). Pushed through `ThreeStageIIR` with the f7 CAL
and scored as `|filtered| - (|original| + 300) > 0` for > 5 ticks: **12
predicted trips on the C4c drive, five of them 70-180 ms after exactly the
five in-band releases above; the identical scoring with the C4c CAL gives 0.**

**Forward replay** (`artifacts/flash7_forward_replay.py`): recorded pedal,
brake, gear, rpm and published limits through `creep_damper_blocks.DlcmLoop`
unchanged, plus an ECM2 block (target creep + demand, mirrored UP V-curve,
table-driven down step, TOL 300, 5 ticks, counter capped at 7, 0.435 s dark
then zero-state restart with the counter kept). The simulated `0x212` matches
each drive's own recorded `0x212` to a p90 of 8 (C4c) and 17 (f7) published
units.

| driver inputs from | CAL in sim | predicted resets | recorded |
|---|---|---|---|
| f7 drive | f7 | 8 (all 7 recorded hit at -0.000 .. +0.062 s, plus one extra) | 7 |
| f7 drive | C4c | **0** | — |
| C4c drive | C4c | **0** | 0 |
| C4c drive | f7 | 10 (first seven inside 53-70 s) | — |

The one extra prediction (40.72 s) is where the real module published zero
torque with the pedal at 52-80 % for ~1 s, an unmodelled post-reset inhibit,
and it is flagged by its own `0x212` mismatch (sim 1014, recorded 0).

## 6. What is and is not established

**Established on the captures:** the trigger is a release into 7a's slow band
with a high residual command; 7a is running and is the lag; the reaction cap
of 7 is `0xA0021D8C`; oscillation is not in the chain; 7c (the UP V-curve
cut) is not in the chain — releases use the DOWN step, which is byte-identical
in C4c and f7 (6H.54.1), and the freeze shape is a multi-stage lag, not a
rate limit.

**Consistent, not identified:** which ECM2 reason code fired. The code at
`0xD001086A` was erased by the 12 V cycle. Reason 12 is the only candidate
that reads the slew-limiter output and whose comparand sits downstream of 7a
(6H.9, 6H.33), and its tolerance and debounce reproduce the observed split
and timing; no other reason has been shown to.

**ECM2's down-step path is a firmware fact, not a fitted choice.** The
selector `a0-0xc67` is written at `0x8004812E` as
`(brake12 != 0x0FFF) && (0x208 B2 bit 4) && (0x208 fresh)` — a validity gate
on the `0x208` brake-pressure signal — and `1` selects the table path (DLCM
session, worklog 6H.56). Measured on all three 2026-10-04 captures the
validity bit is set on 100 % of samples and the sentinel never appears, so
the table path is live throughout both drives. The replay's **7-on-f7 and
0-on-C4c are therefore both predictions**; the constant -100/tick path, which
would have produced two spurious C4c resets, is simply not the firmware's
live path. (An earlier draft of this file said the path was chosen by the
C4c zero; the trace supersedes that.)

**Timing residual:** a -100/tick allowance, TOL 300 and 5 ticks predict the
dark onset ~0.09 s after the pedal-0 sample; observed 0.14 s for the three
low-command resets and 0.04-0.06 s for the four high-command ones. Within the
`0x210` sampling slop, with a consistent sign that the simple model does not
explain.

**Retracted on the way:** worklog 3AB's "absent DTCs weaken the reset
hypothesis" — `dtcs_after_f7_drive_fault_20261004.log` shows P3115 status
0x04 after the drive and `dtcs_postclear_f7_20261004.log` shows an explicit
clear afterwards; 3AC's tip-in reading of resets 3-6; the envelope-based
reason-12 model as a reset predictor (12 trips on the C4c drive with no
reset, identical under both rate tables; its earlier "match" was scored only
inside the reset windows).

## 7. Rules for every future CAL change

1. **`0xA0021545` stays 0, and the whole of 7a's gain table is off-limits:
   X axis `0xA002148C..0xA0021499`, Y axis `0xA002149C..0xA00214A9`**
   (descriptor `0x80043F88`, n = 7, int16; the 2 bytes at `0xA002149A..9B`
   belong to neither). These are the table extents, not the bytes flash 7
   happened to change (which were 9 of the 14 X bytes and 6 of the 14 Y
   bytes, leaving entry 6 of each untouched). For the published command to
   stay within 300 counts of an allowance that falls at up to 100 counts/tick,
   any filter between the limiter and the output must have a group delay
   under ~3 ticks (30 ms). **That budget is a conservative bound taken at the
   worst-case allowance rate**: the live down-step is -30 to -100 per tick
   depending on the limiter state (6H.54.1), and the monitor needs the gap to
   persist a further 5 ticks, so the real margin varies by more than 3x with
   operating point; do not recompute it at -30/tick to recover margin. A
   three-stage cascade at alpha 0.1 has ~300 ms. There is no useful setting
   of that filter that is also safe on a sharp low-speed release.
2. **No edit without an ECM2 twin.** Most tables the torque path reads are
   duplicated in the ECM2 bank (`README.md` → "Tables exist twice"); the two
   edits that caused the fault were the two with **no** twin. The distinction
   is readable straight off a byte diff of two images, no reader tracing
   needed: in flash 7's 22-byte diff the 7c V-curve change appears **twice**
   (`0xA0021532..36` and `0xA0021B6E..72`, three bytes each) while 7a's gain
   table and enable appear **once**. A proposed change list must state, per
   address, which ECM2 copy mirrors it, and an address with none is rejected
   unless the supervisor's view of it is traced and shown unchanged.
3. **Screen before md5.** `release_freeze_7a.phase6` pushes a recorded
   command through a candidate CAL's filter and scores the reason-12 gap;
   `flash7_forward_replay.py` runs the whole path on a recorded drive. A
   candidate that predicts > 0 resets on `coda_20261004_165539_T0` is
   rejected before the two-session rebuild step.
4. **Flash 8 (`cal_candidate_f8_regenfloor_on_f7.bin`) carries all 22 of
   flash 7's bytes and must be rebuilt on C4c before it is considered.**

## 8. Files

| file | what |
|---|---|
| `artifacts/flash7_reset_trigger_worklog.md` | The working log of this investigation: sections 0-5, every number above with its provenance. |
| `artifacts/reset_trigger_transients.py` (+ `.p123.out.txt`, `.p4.out.txt`) | p1 20 ms traces at each reset; p2 the envelope model whole-drive (the falsification); p4 the release freeze test. |
| `artifacts/release_freeze_7a.py` (+ `.p567.out.txt`) | p5 demand at each release and the coast rows; p6 C4c command through 7a (+ the C4c-CAL control); p7 trip timing. |
| `artifacts/flash7_forward_replay.py` (+ `.out.txt`, `.trace.out.txt`, `.limits.out.txt`) | Script deleted 2026-10-10 at codasim plan step 7; the outputs stand, and `../../tools/codasim/tests/ecm2_gate.py` is the current replay. The forward replay of §5, four drive/CAL combinations; `.trace` has per-tick traces at every predicted and recorded reset. |
| `artifacts/flash7_diagnosis_worklog.md` | The DLCM session's log: the reaction chain (3AM), the firmware reads of the filter (6H.38, 6H.52), the ECM2 limiter and monitor (6H.9-6H.40), the down-step read (6H.54). |
| `dcan_drive_capture_20261004_f7/` | The four flash-7 captures, quarantined outside every sync root. |
