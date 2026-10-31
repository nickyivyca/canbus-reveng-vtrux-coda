# ESP torque intervention — the `0x300` / `0x312` torque-limit interface

How the ESC's torque limits reach the Coda's motor, what the DLCM publishes
about them, and the measured event populations for both directions.

**Scope.** This file owns the *external* torque-limit interface: `0x300`
inbound from the ESC, `0x312` outbound from the DLCM, the firmware that joins
them, and the interventions measured in the log corpus. The DLCM's *internal*
torque path -- the gradient limiter, the creep/assist subsystem, the demand
path, the `0x212` transmit chain -- is
[`dlcm-torque-limiter-code-trace.md`](dlcm-torque-limiter-code-trace.md), and
the factory requirement's own torque-flow diagram is
[`dlcm-torque-flow.md`](dlcm-torque-flow.md). Regen's power limit and the
pedal-map shaping work are [`regen-limit-chain.md`](regen-limit-chain.md) and
[`pedal-map-envelope-design.md`](pedal-map-envelope-design.md).

**Provenance.** Assembled 2026-10-03 from the working log of the 2026-10-02/03
investigation plus sections 2, 6 and 7 of `regen-limit-chain.md`, which was
64 percent this topic by line count. Part I is the current state.
**Part II preserves the migrated sections verbatim, including the parts that
turned out to be wrong**, each under a banner saying what supersedes it -- the
reasoning errors are why several of these findings took three passes to settle,
and deleting them would remove the record of how.

**Source-of-truth order within this file: Part I over Part II, always.**

---

# Part I -- current state

## 1. Confirmed — the braking-side clamp

`0x300` B2–3 (`ESP_BrakingTqLimit`, 13-bit, scale 2.5, offset −5000, internal
torque counts where 1 count = 0.1 Nm) is a genuine intervention signal. It
parks at the no-limit sentinel **7000** and only moves during an event:
904 of 996 stored points in `coda_20261002_175334`.

Five episodes corpus-wide, found independently by two methods that agree
exactly — raw BUSMASTER parsing with hand bit-extraction, and the corpus
decoded through `cantools` at Influx upload time. Same five sessions, nothing
extra from either:

| session | t (s) | ABS offset | clamp dur | mph | regen request |
|---|---|---|---|---|---|
| `coda_20260429_222231` | 120.99 | 0.70 s | 5.65 s | 14.6 | −84.2 Nm |
| `coda_20260510_153916` | 120.39 | 0.64 s | 21.17 s | 18.0 | −69.0 Nm |
| `coda_20260617_191308` | 122.76 | 1.01 s | 2.53 s | 15.6 | −71.2 Nm |
| `coda_20260702_001157` | 213.73 | 1.07 s | 18.97 s | 19.9 | −71.5 Nm |
| `coda_20261002_175334` | 424.02 | 0.97 s | 9.31 s | 12.2 | **−156.2 Nm** |

`ABS_BrakeEvent` (`0x208` B0 bit 6) starts within one sample in all five, the
limit reaches exactly 0 in all five, all five are regen under braking at
12–20 mph. Four predate the flash campaign. The 2026-10-02 event is the one
the user felt; it is the same mechanism as the other four with roughly twice
the regen magnitude to remove.

## 2. Confirmed — the DLCM's application of the limit IS on D CAN

It is in `0x312 TorqueFeedback`, not in the request. Measured at all five
events (`tc_clamp_mechanism_verify.py`, claim B):

```
ESC  ESP_BrakingTqLimit   7000 -> 1310 -> 310 -> 0     in 0.10-0.18 s
DLCM 0x312 TorqueFeedback -152 ->  -92 -> -3.25        90% gone in 0.16-0.21 s
DLCM 0x212 TorqueRequest  -156 -> -156 -> -156 ...     90% gone in 1.58-2.13 s
```

Delivered torque collapses **one sample behind** the limit, in 0.16–0.21 s at
every one of the five events. The published request keeps showing unclamped
demand for a further 1.5–2 s, and in three of the five it initially moves
*further negative* while delivery is already cut. Release is a linear ramp at
**6.0–9.7 Nm/s**.

This answers the user's question of 2026-10-03 — *"is it maybe still the DLCM
asserting, but it would be only seen on M CAN which we do not have access
to?"* — **no M CAN access is required.** The post-intervention applied torque
is published on D CAN as `0x312 TorqueFeedback`.

Earlier description to correct when `regen-limit-chain.md` is updated: the
release was written up as passing through "100 internal = +10 Nm". That was one
sample of the linear ramp above, not a discrete step.

## 3. CORRECTED TWICE — `0x300` B4–5 *is* a tractive torque limit

Read this whole section before using any earlier statement about B4–5. It was
wrong, then the correction was also wrong, and the final answer is close to
where it started.

### 3.1 What is measured

B4–5 tracks `0x212 TorqueRequest` almost perfectly over a whole drive:
r = +0.9988 … +0.9996 on four sessions via InfluxDB, and on raw frames across
six sessions **MAE 0.28–0.39 Nm, median residual 0.000, p99 residual 0.750 Nm**
(`tc_clamp_mechanism_verify.py`, claim A). Both fields quantise to 0.25 Nm.

It is also never parked at a sentinel, unlike the braking-side field:

| field | n | p50 | range | parks at a sentinel? |
|---|---|---|---|---|
| `ESP_BrakingTqLimit` (B2–3) | 996 | **7000** | 0…7000 | yes, 904/996 |
| `ESP_TractiveTqLimit` (B4–5) | 8951 | 150 | −1570 … +2990 | **never** |

### 3.2 The wrong inference drawn from it

From the correlation and the absent sentinel I concluded B4–5 was "a second
copy of the torque request, not a limit", and withdrew the name. **That was an
over-correction.** A correlation of 0.999 is consistent with two different
things — a copy of the request, or *a limit whose idle value is the request* —
and the correlation alone cannot separate them.

### 3.3 What the firmware does with it, and the bit that settles it

`FUN_80080572` reads `B5 | ((B4 & 0x1F) << 8)` from the `0x300` RX mirror at
`a0-0x1058`, `FUN_8006F05A` scales it `*5>>1 - 5000` (= ×2.5 − 5000) into
`0xD0006826`, and `FUN_800771FA` applies it as a limit:

```c
a0-0x2540 = min( a0-0x253a, max(0xD0006826, 0) )
```

gated on `DAT_d0006844 != 0 && a0-0x3e9c == '\0' && CAL 0xA0021716 != 0`.

`0xD0006844` is `a0-0x27bc`, written by `FUN_8006F05A` from `FUN_8008054E`,
which returns **`0x300` B4 bit 6**. So B4 bit 6 is the runtime arming flag for
the tractive application. Both calibrations are enabled: `0xA0021715 = 1`
(braking) and `0xA0021716 = 1` (tractive), read from `coda_dlcm_cal.bin`.

**The bit explains both the correlation and the absence of events.** Measured
over 315,555 `0x300` frames on d_can across six sessions:

| B4 bit | set in | share |
|---|---|---|
| bit 5 (`FUN_80080560` → `a0-0x27bd`) | 0 | 0 % |
| **bit 6 (arming flag)** | **46** | **0.0146 %** |
| bit 7 | 157,777 | **49.9998 %** — an alternating toggle |

B2 bits 5, 6 and 7 are **0 in all 315,555 frames**: the braking side has no
arming bit, matching `FUN_800771FA`'s first gate, which has no runtime flag.

And in the frames where the bit *is* set, B4–5 stops matching the request —
it drops **below** it by 6.75 … 88.75 Nm. The longest armed run, 36 frames /
0.70 s in `codadriveslowturnonwithdefroster2` at t = 586.43:

```
 arm   B4-5(limit)   0x212 req   0x312 fb    M_MAX
  1       218.00       267.25     261.50     299.75
  1       193.75       264.25     188.75     299.75
  1       167.75       256.50     207.00     299.75
  1       167.75       253.00     166.50     299.75     <- fb follows the LIMIT
  1       299.75       254.25     240.50     299.75     <- releasing
  0       250.00       243.75     240.50     299.75     <- re-converges on req
  0       241.00       241.25     234.25     299.75
```

`TorqueFeedback` tracks the limit, not the request, while armed; the moment the
bit clears, B4–5 snaps back onto the request to within one LSB.

### 3.4 Conclusion

**`ESP_TractiveTqLimit` is the correct role and the correct name.** It is the
ESC's tractive torque limit, which *idles at a transparent value equal to the
request* and drops below the request only when the ESC arms it via B4 bit 6.
The DBC name stands; the rename proposed in §5.1 is withdrawn.

**What was genuinely wrong was the detector and the episode list, not the
role:**

- "A positive/tractive torque clamp exists" (`regen-limit-chain.md` §7.7) is
  **correct after all**, and the user predicted it. It needs re-supporting with
  the arming bit rather than the evidence originally given.
- The "10 sustained tractive-side clamp episodes, limit pulled back to
  148–223 Nm for 0.27–0.41 s" (§7.8) came from a detector that compared the
  request against a copy of itself, so the list cannot be relied on as it
  stands. Its numbers are suspiciously close to the armed events measured here
  (limits 167–221 Nm), so some of those episodes were probably real — but the
  method cannot distinguish a real intervention from transport skew between two
  50 Hz copies, and I am not claiming them on that basis. **Re-derived
  corpus-wide — see §3.5, and the original episodes were substantially right.**
- Mistake 8's "+167.8 Nm vs +253.0 request" is, in hindsight, plausibly a real
  armed event rather than an artefact. Unresolved pending the sweep.

### 3.5 The armed-episode population, corpus-wide

`artifacts/tractive_arm_sweep.py`, detector = `0x300` B4 bit 6 set, runs of
>= 2 frames separated by more than 0.25 s. Coverage: **396 sessions**, of which
253 analysable with no events, **40 with events**, 95 carrying no d_can
(diagnostic and charging captures) and 8 with no resolvable timebase anchor.

**34 armed episodes across 29 sessions.** Durations p50 **0.12 s**, p90 0.66 s,
max **0.86 s**. Request-minus-limit gap p50 **84.25 Nm**, p90 120.75, max
153.75.

The population splits by duration. Thirteen episodes at >= 0.44 s, every one of
which releases by ramping the limit to exactly the +299.75 Nm ceiling before
the bit clears:

| session | t | dur | n | lim_min | req_max | gap |
|---|---|---|---|---|---|---|
| `coda_20260827_191940` | 92.05 | 0.86 s | 39 | 179.00 | 299.75 | 120.75 |
| `coda_20260921_105818` | 135.94 | 0.80 s | 41 | 171.75 | 297.00 | 125.25 |
| `codadriveslowturnonwithdefroster2` | 586.44 | 0.70 s | 36 | 167.75 | 270.00 | 102.25 |
| `coda_20260501_091019` | 33.84 | 0.66 s | 34 | 148.50 | 299.75 | 151.25 |
| `coda_20260627_103353` | 169.53 | 0.64 s | 33 | 199.00 | 299.75 | 100.75 |
| `coda_20260905_103825` | 62.02 | 0.52 s | 27 | 215.00 | 299.25 | 84.25 |
| `coda_20260509_204629` | 336.59 | 0.52 s | 27 | 181.50 | 291.25 | 109.75 |
| `coda_20260901_235157` | 43.66 | 0.52 s | 27 | 207.75 | 299.75 | 92.00 |
| `coda_20260608_200650` | 35.05 | 0.48 s | 25 | 197.50 | 294.75 | 97.25 |
| `coda_20260613_193703` | 45.59 | 0.48 s | 25 | 194.75 | 299.75 | 105.00 |
| `frombonnydoon` | 1873.34 | 0.46 s | 24 | 211.25 | 299.75 | 88.50 |
| `coda_20260727_123835` | 256.90 | 0.46 s | 24 | 223.25 | 299.75 | 76.50 |
| `coda_20260807_182202` | 75.42 | 0.44 s | 23 | 200.50 | 282.75 | 82.25 |

The remaining 21 are 0.02–0.20 s, 2–9 frames.

**The withdrawn episode list was substantially right.** It reported limits
pulled back to **148–223 Nm**; the arming-gated long episodes give
**148.5–223.25 Nm**, a match to within rounding. Its durations (0.27–0.41 s)
were short, because without the arming bit the detector could only see the part
of each episode where the gap was wide. So those events were real; the method
could not establish that they were, and the bit now does. Both the original
claim and its withdrawal were over-confident in opposite directions.

**One episode arms without binding:** `coda_20260721_215506` at t = 176.79,
0.08 s, where `lim_min` 217.00 **exceeds** `req_max` 194.75 — gap −22.25 Nm. So
the bit being set does not by itself mean torque was removed; 1 of 34.

**Character contrast with the braking side**, now quantified: tractive
interventions are brief (p50 0.12 s, max 0.86 s) and partial (limit to
148–223 Nm of a ~300 Nm ceiling). Braking-side clamps run **2.5–21 s** and go
to **exactly 0**. Same `min()`, same scaling, very different behaviour.

**Why every threshold detector fails on this field, worth recording as a
general trap:** its idle value is not a sentinel, it is *another live signal*.
An absolute threshold therefore returns the whole drive (285 "episodes"
corpus-wide), and a request-minus-limit gap detector compares the request
against a copy of itself. The field needed its validity bit found in the
firmware before it could be measured at all.

## 4. Confirmed — the `0x312` trace, and why `M_MIN` does not move

`0x312` is TX mailbox 10, packed by `FUN_80080C14` from the mirror block at
`0xD00069D2`, which `FUN_80074780` fills with `clamp(v, -5000, 15475) * 0.4 +
2000`. The byte map, read off the packer:

| `0x312` field | mirror | filled from |
|---|---|---|
| `TorqueFeedback` (B0[4:0],B1) **and** the B2–3 duplicate | `0xD00069D8` | `0xD000686C` |
| `M_MAX` (B4[4:0],B5) | `0xD00069D4` | `0xD0006A96` |
| `M_MIN` (B6[4:0],B7) | `0xD00069D6` | `0xD0006A98` |

The B2–3 "duplicate" is literally the same variable packed into two field
positions by the same two statements — which is why it was measured identical
in 100 % of frames.

`FUN_8007689C` is the arbitration orchestrator. It calls the whole ladder and
then publishes:

```c
*(short *)(a0 + -0x2568) = -*(short *)(a0 + -0x254c);     // M_MIN, NEGATED
*(undefined2 *)(a0 + -0x256a) = *(undefined2 *)(a0 + -0x2536);  // M_MAX, direct
```

**The negation is independent confirmation of the magnitude convention** — the
stored value is a positive magnitude, negated at publication to form the
negative limit. That is the same reading arrived at from `FUN_800768D6`, now
corroborated from a second, unrelated site.

`a0-0x254c` and `a0-0x2536` are written by **`FUN_8007729A`**, and
`FUN_800771FA` — the function that applies both ESC limits — **does not write
either of them.** So:

> **The ESC intervention never reaches the published `M_MAX`/`M_MIN`.** `0x312`
> publishes the pack/motor envelope only.

The writes in `FUN_8007729A` make this airtight rather than merely circumstantial,
because they name their inputs:

```c
iVar7 = (uVar1 + *(ushort *)(a0 + -0x2552)) - _DAT_d0006a78;
*(ushort *)(a0 + -0x254c) = (short)iVar7 * (ushort)(0 < iVar7 ...);  // M_MIN src, clamped >= 0

iVar6 = (sVar5 + *(short *)(a0 + -0x253a)) - uVar2;
*(short *)(a0 + -0x2536) = (short)iVar6;                             // M_MAX src
```

`a0-0x2552` and `a0-0x253a` are the **pre-ESC** magnitudes — they are the first
operand of each of `FUN_800771FA`'s two `min()` calls. The post-ESC results live
at `a0-0x255a` and `a0-0x2540`, and neither appears here. So the published
envelope is read from upstream of the intervention by construction, not merely
as an observed coincidence. The `>= 0` clamp on the `M_MIN` source is a further
corroboration of the magnitude convention.

This is exactly what was measured: `M_MIN` sat flat at −300.00 Nm through the
entire 2026-10-02 braking clamp while `TorqueFeedback` collapsed from −152 to
−3.25 Nm. Code and data agree.

**The structural hypothesis of §4 as originally written is refuted.**
`FUN_800768D6`'s outputs are `a0-0x2560`/`a0-0x255e` and
`a0-0x2548`/`a0-0x2546`; the published pair comes from `a0-0x254c`/`a0-0x2536`.
`FUN_800768D6` *reads* those two and combines them with the ESC-applied pair to
produce the demand-clamp bounds that `FUN_8007787E` turns into input A at
`0xD0006AEE`.

**Red herring cleared:** `M_MAX` = +29.75 Nm during the clamp window is the
documented brake-on collapse (+299.75 in 100 % of brake-off frames, +29.75 in
97.2 % of brake-on frames, `coda-dlcm-decompile-notes.md`), not an
intervention.

### 4.1 The two ESC applications, side by side

`FUN_800771FA`, in full:

```c
a0-0x255a = min( a0-0x2552, max(0xD0006824, 0) )   // braking / regen side
  gate:  a0-0x3e9d == 0 && a0-0x3e9e == 0 && CAL 0xA0021715 != 0

a0-0x2540 = min( a0-0x253a, max(0xD0006826, 0) )   // tractive / drive side
  gate:  DAT_d0006844 != 0 && a0-0x3e9c == 0 && CAL 0xA0021716 != 0
```

`0xD0006824` ← `FUN_80080588` = `0x300` B2–3; `0xD0006826` ← `FUN_80080572` =
`0x300` B4–5. Both scaled ×2.5 − 5000 by `FUN_8006F05A`.

**The asymmetry is the whole story.** The braking side is gated on calibration
and fault flags only, so it fires whenever the ESC lowers B2–3 — five times in
the corpus. The tractive side additionally requires a runtime arming bit from
the ESC, which is set in 0.015 % of frames. Same `min()`, same scaling, same
calibration state; one fires and the other almost never does, and the
difference is one bit.

### 4.2 RESOLVED — where the ESC limit is applied, and why `0x212` never shows it

Found 2026-10-03 while checking `dlcm-torque-flow.md` against the firmware, in
a function that had already been written up for a different reason.

`FUN_80075CF8` — the gradient limiter's caller — takes the rate-limited torque
`v` and writes it to **two different places on adjacent lines**:

```c
FUN_80075CF8:
    *(s16*)(a0-0x25b0) = *(s16*)0xD0006AEE + *(s16*)0xD000513A;   // request in
    FUN_80075DFA();                                               // rate limiter
    FUN_80075F56();                                               // 3-stage IIR (CAL-disabled)
    v = *(s16*)(a0-0x25ae);
    *(s16*)(a0-0x25a6) = v;                                       // 0xD0006A5A  -- UNCLAMPED
    *(s16*)(a0-0x25b2) = clamp(v, *(s16*)0xD0006AA0, *(s16*)0xD0006AA2);
```

`0xD0006AA0` and `0xD0006AA2` are `a0-0x2560` and `a0-0x255e` — **the pair
`FUN_800768D6` builds from the ESC-applied values** `a0-0x255a` and
`a0-0x2540`, direction-resolved. And `0xD0006A5A` is confirmed (`DlcmVarXref`)
read by `FUN_80074780` into mirror `0xD00069D2`, which `FUN_80080C14` packs
into TX mailbox 8 — `0x212`.

> **So `0x212` publishes the unclamped sink and the ESC limit lands on the
> other one. The two writes are consecutive statements. This is by
> construction, not an oversight.**

**It also reconciles the two measurements that looked contradictory.**
`0x212` *is* clipped — by the pack envelope, upstream, because input A at
`0xD0006AEE` comes from `FUN_8007787E` applying `FUN_800768D6`'s **other**
pair, `a0-0x2548`/`a0-0x2546`, which derives from the **pre-ESC** magnitudes
`a0-0x254c`/`a0-0x2536`. So:

| pair | built from | applied | reaches |
|---|---|---|---|
| `a0-0x2548` / `a0-0x2546` | pre-ESC envelope (`a0-0x254c`, `a0-0x2536`) | upstream, via `FUN_8007787E` → input A | `0x212`, and `0x312` `M_MAX`/`M_MIN` |
| `a0-0x2560` / `a0-0x255e` | **ESC-applied** (`a0-0x255a`, `a0-0x2540`) | downstream of the rate limiter | `0xD0006A4E`, not `0x212` |

That is exactly the measured behaviour: the request sits on `M_MAX`/`M_MIN`
(`\|req − M_MAX\| = 0` at p10/p50/p90, established 2026-09-24) while ignoring
the ESC braking clamp completely, and `M_MIN` stays flat at −300 Nm through an
intervention. One pair carries the envelope and is published; the other carries
the ESC limit and is not.

**Two limits on this result, both real:**

- **`0xD0006A4E`'s consumer is not found, so "it goes to the motor command on
  M CAN" remains a hypothesis.** `DlcmA0RefScan` finds only the write;
  `DlcmVarXref` reports `reads: 0  writes: 0`. Each scanner has exactly the
  blind spot that would hide the reader — and the check that proves it is that
  neither scanner found `FUN_80075CF8`'s *own* reads of `0xD0006AA0`/`0xD0006AA2`
  either, which are visible in the decompilation. Treat the absence as
  unmeasured, not as absent.
- **`FUN_80075D52` reads the same limit pair** (`0xD0006AA0` at `80075D9E`,
  `0xD0006AA2` at `80075D94`), so there is a second consumer of the ESC-applied
  limits that has not been followed. This is the function already noted as
  reading `FUN_800764F6`'s output at `0xD0006A76`.

### 4.3 Still open

- Whether the 1.5–2 s ramp-out of the published request at a braking clamp is
  the documented falling rate limiter. §4.2 explains why the request is not
  clamped directly; it does not explain the ramp's rate. Untested.
- Who writes `0xD000686C` (`TorqueFeedback`'s source). `FUN_8006FBE0` and
  `FUN_80070382` both reference `a0-0x2794`; neither is decompiled here.
- `0x300` B4 bit 5 (`FUN_80080560` → `a0-0x27bd`, feeding DTC `0x6e` logic via
  `a0-0x27bb`) is never set in 315,555 frames. Role unknown.
- `FUN_80075D52`, the second consumer of the ESC-applied pair.

## 5. Proposed, awaiting the trace and then approval

Not yet written anywhere:

1. **DBC** — the rename is **withdrawn** (see §3.4); `ESP_TractiveTqLimit`,
   `ESP_BrakingTqLimit` and `ABS_BrakeEvent` all stand as confirmed `SG_`
   entries and no re-upload is needed. What the DBC *should* gain is the
   arming bit, now confirmed from both firmware and data:
   **`0x300` B4 bit 6 = the tractive-limit arming / validity flag**, the gate
   on `FUN_800771FA`'s tractive `min()`. Plus `CM_` text for B4 bit 7 (a 50/50
   toggle) and the fact that B2 bits 5–7 are always 0, i.e. the braking side
   has no arming bit. A new `SG_` does re-trigger the `0x300` message hash and
   another ~300-session Influx re-upload, so settle the full set of `0x300`
   additions in one edit.
2. **`regen-limit-chain.md`** — §7.7 ("positive clamp exists") is **retained,
   re-evidenced** on the arming bit rather than withdrawn; §7.8's tractive
   episode list is re-derived from `tractive_arm_sweep.py`; add §2 and §4;
   correct the release-ramp description.
3. **`projects/coda/README.md`**, **`notes/README.md`**,
   **`notes/traction-control-analysis.md`** — the `0x300` row and dependent
   claims.

## 6. Process errors made during this work

- **Timebase stacking, a repeat.** The first raw-frame check of §3 merged four
  chunks by `frame.timestamp` and returned MAE 33.6 Nm, appearing to refute the
  Influx result. `parse_file()` re-bases every file to t=0; merging a
  multi-chunk session requires `TimebaseIndex.anchor_ns()`. With the anchor the
  same check gives 0.28 Nm. **InfluxDB was right and the local check was
  broken** — the opposite of the expected failure direction, because Influx
  stores anchored absolute time and a hand-rolled merge does not.
- **An absolute threshold is not a clamp detector.** `limit < 3000 counts`
  applied to B4–5 returned 285 "episodes", many spanning a whole drive. This is
  Mode 2 of *Filters that fail silently*: a parameter chosen by the analyst,
  believed as a finding. What exposed it was orthogonal and cheap — the point
  count and the absence of a sentinel value, not scrutiny of the episode list.
- **Interpretation written to a file before the gate.** The phase-4 comment
  block in `tc_clamp_influx_scan.py` asserted conclusions before they were put
  to the user. `artifacts/` is still a file; the write is the gate regardless
  of which file.


---

# Part II -- migrated sections, verbatim

Preserved from `regen-limit-chain.md` as of 2026-10-03. Section numbering is
that file's, kept so its internal cross-references still resolve. Read the
banner on each before citing it.

---

> ### FALSIFIED -- do not cite
>
> Section 2 below concludes that `0x300` B4-5 "is not limiting" and is "a
> mirror, not a wall". **It is a wall.** It is the ESC's tractive torque limit,
> armed by `0x300` B4 bit 6, and it binds for up to 0.86 s at a time in 34
> episodes across 29 sessions. The authoritative treatment is **Part I**
> **section 3**, and the corpus population is **3.5**.
>
> The section is kept because its *measurement* was sound -- B4-5 really does
> track the torque request to within one LSB for 99.985 percent of frames --
> and the error was entirely in the inference drawn from that correlation.
> Part I 3.2 explains why a 0.999 correlation could not separate "a copy of the
> request" from "a limit whose idle value is the request".

## 2. MMAX_ESP_REGEN_TQ_REQ — decoded, and it is not limiting

This signal had been uncharacterised since the traction-control work, and it was the one gap
preventing an answer to the user's question.

**`0x300` bytes 4–5, mask `0x1FFF`, internal = (raw − 2000) / 0.4** — the same 13-bit torque
encoding as `0x212` and `0x312`. (Confirmed 2026-09-24 from the transmit code: `FUN_80080572` reads `0x300` B4 masked `0x1F` with B5, exactly the `36|13@0` the DBC declares. `0x312` is transmitted by the DLCM, not the MCM.) Masked range −1570 … +2990 internal, which brackets
M_MIN/M_MAX as a torque limit should.

Two things had to be got right:

- **Identify the bus by content.** The DBC warns that a different message shares `0x300` on
  C CAN. In this capture `0x300` appears *only* on the D-CAN bus (n=15,001, exactly 50.0 Hz,
  DLC 8, B0 = `0x00` in every frame), so there was nothing to disentangle — but a filter on
  `B0 == 0` does **not** separate them in general, because the C-CAN multiplex includes
  B0 = 0.
- **Mask the toggle.** Reading B4–B5 as a plain 16-bit value returns hundreds of unrelated
  values in two interleaved families 32,768 apart. **B4 bit 7 toggles on exactly alternate
  frames (50.0 %)** and must be masked off.

Note the DBC's existing observation that **B1 toggles `0x00`/`0x80` at 50:50 is also correct**
— measured 49.5 % here. There are two toggling bits, not one, and the earlier note is not
superseded by this finding. B2–B3 are constant (`0x12C0`).

### Why it is a mirror, not a wall

The decisive test was to compare its floor across three drives with different map requests:

| drive | map coast plateau | ESC floor | delivered floor |
|---|---|---|---|
| C1 | −690 | −690 | −690 |
| launch rate | −690 | −980 | −980 |
| C2 | −1562 | −1570 | −1562 |

**The ESC floor tracks the request.** It was −690 when the map asked −690 and is −1570 now
the map asks −1562. Where the two differ it sits slightly *deeper*, i.e. permitting more
regen than the car produces. The −1570 that looks alarmingly close to our −1562 request is
our own number coming back, not a hard floor we are about to hit.

> **WITHDRAWN 2026-10-03 — the section's conclusion is wrong, not just its
> wording. B4–5 binds.** Measured in `codadriveslowturnonwithdefroster2.log` at
> t ≈ 586 s: during a 369-count wheel-slip event it falls to **+167.8 Nm against
> a +253.0 Nm request** and delivered torque follows it down to 166.5 Nm. It
> idles *at* the value it is limiting — 2870 against a request of 2872 one
> sample earlier — which is why three drives' worth of samples read as a mirror.
> The evidence for "mirror" and for "limit" is the same data until the moment it
> departs. Details and the direction-dependent pairing in §7.6–§7.7.
>
> **Also corrected — this paragraph said two things, and only one of them
> is true.** It claimed the field "tracks the request" **and** that it "reports
> delivered torque rather than constraining it". Those are indistinguishable in
> the population it was measured on, because there request ≈ delivered in every
> sample. The 2026-10-02 event separates them: `0x212` requested −156.2 Nm, the
> motor delivered −2 Nm, and B4–5 read **−1570 counts (−157.0 Nm) throughout**.
> It tracks the **request**. The "reports delivered torque" half is wrong and is
> withdrawn.
>
> What survives: B4–5 is not the limiter. What does **not** survive is the wider
> reading that the ESC therefore cannot limit regen — it can, on **B2–3** of the
> same message, two bytes away and undecoded when this section was written. See
> §7. The error was scoping a conclusion about a *message* to one *field* of it.
>
> **Units trap in the same breath.** `MMAX_ESP_REGEN_TQ_REQ` decodes through the
> DBC to **internal counts** (scale 2.5, offset −5000) while `TorqueRequest` and
> `M_MIN` decode to **Nm** (scale 0.25, offset −500) — a factor of 10 for the same
> physical quantity. So −1570 and −156.2 are **the same number**, not a 10x
> discrepancy. Same shape as the 1703/1562 episode: two numbers that look
> different being one value.

---


---

> ### STILL VALID, extended
>
> Section 6 below decodes `0x312`'s two limit fields as a motor envelope
> (`M_MAX`) and the pack charge limit (`M_MIN`). That stands. **Part I**
> **section 4** adds where they are produced in firmware, the byte map of the
> whole message, and the finding that both are read from *pre-ESC* magnitudes
> -- so neither ever carries an ESC intervention.

## 6. What 0x312's two limit fields actually are (2026-09-24)

Corpus sweeps over 1042 captures, `artifacts/mmax_variation.py` and
`artifacts/mmin_variation.py`. This resolves a conflation that ran through the
earlier sections: **one field is a motor limit and the other is a pack limit**,
and treating both as "the pack" produces wrong design conclusions.

### B4-5 (M_MAX) is a MOTOR envelope

| rpm | p10 | p50 | p90 | spread |
|---|---|---|---|---|
| 750–2250 | 2998 | 2998 | 2998 | **0.0 Nm** |
| 3750 | 2602 | 2745 | 2812 | 20.2 Nm |
| 4250 | 2272 | 2378 | 2522 | 24.0 Nm |
| 6250 | 1555 | 1612 | 1652 | 9.4 Nm |

Flat at 2998 internal (287.8 Nm) below ~2750 rpm with **zero spread across
1.2 M samples**, then a constant-power fall: the 4250 bin p50 works out to
101.5 kW, the 3500 bin to 101.9 kW. So the envelope is
`min(287.8 Nm, 100 kW / w)` with only ~+/-5 % wobble. The user independently
confirmed 100 kW is a motor rating.

**This matters because it is nearly static.** There is very little upside to
chase by over-commanding drive torque — an earlier claim in this session that
pinning the top rung to a measured p50 would give up "19 % of peak torque" was
wrong, built from mistaking this field for a pack ceiling.

### B6-7 (M_MIN) is the PACK charge limit, and it moves

| rpm | p10 | p50 | p90 | p50 kW |
|---|---|---|---|---|
| 3750 | −1482 | −1385 | −1255 | 52.2 |
| 4250 | −1270 | −1180 | −1082 | 50.4 |
| 5250 | −975 | −920 | −848 | 48.6 |
| 6250 | −800 | −772 | −698 | 48.5 |
| 6750 | −740 | −688 | −625 | 46.7 |

**44–54 kW depending on the drive**, on a constant-power line. The deepest
genuine values are 53.7 kW (6250 bin) and 54.4 kW (6750 bin) — those two bins
are the clean ones. This spread is the reason a regen command should over-ask:
see `pedal-map-envelope-design.md` §4.

### Saturation artifacts in both fields — HYPOTHESIS

`−3000` appears as the deepest value in nearly every M_MIN bin and as the p50
below 1250 rpm; `298` is common on M_MAX in some captures. **Interpreted as the
field's "no constraint" / pre-init value rather than a real limit**, on two
grounds: at 750 rpm a 48.6 kW limit would be 619 Nm, far past the 288 Nm motor
ceiling, so there is genuinely nothing to report there; and taken literally the
M_MIN tail would imply 128–173 kW of charge acceptance. Not proven — no init
sequence has been traced — so treat as a hypothesis and **exclude these values
before quoting any maximum.**

### The speed axis of the accelerator map is calibratable

`0xA00217B0`, in CAL space, 10 entries: 0, 640, 1024, 1536, 2560, 6400, 10240,
12800, 15360, 17920 counts = 0, 291, 465, 697, 1162, 2905, 4648, 5810, 6972,
8134 rpm. **Used by the D accelerator map alone** — a scan of every descriptor in
`0x80040000–0x80045000` found exactly one referent, so moving a breakpoint does
not disturb another table. Ascending order must be preserved
(`FUN_8005F082` assumes it). Considered and not used; see
`pedal-map-envelope-design.md` §4 for why a single knot cannot serve both the
drive and regen envelope corners.
---


---

> ### MIXED -- see Part I for each claim
>
> Section 7 below is the original write-up of the 2026-10-02 event. Its
> braking-side material is superseded in full by **Part I sections 1 and 2**,
> which are the same findings with the mechanism traced. Within it:
>
> - 7.7 ("the positive-side clamp DOES exist") is **correct**, and was the
>   user's prediction. It is re-evidenced on the arming bit in Part I 3.
> - 7.8's braking-side result (n=5) stands. Its **tractive half (n=10) came
>   from a detector that compared the torque request against a copy of
>   itself**; the corrected population is Part I 3.5, and the original episodes
>   turned out to be substantially right anyway.
> - 7.9 and 7.10 are trap records and are worth keeping as written.

## 7. The ESC can clamp torque to zero, and on 2026-10-02 it did

Found 2026-10-03, from the user's report: *"driving home from work I hit a poor
stretch of road and the traction control kicked in — on the regen side … now it
was more noticeable since the regen torque was higher and it dropped all the way
to 0."* They added that they have felt it on the same stretch **before** the
reflash campaign.

Everything in §7.1 is measured. §7.2 is the reading of it, kept separate and
labelled, and §7.3 is what is still open.

### 7.1 Measured

**The event.** `coda_20261002_175334` (the 17:53 commute), **t = 424.0–425.4 s**,
12 → 14 mph. The drive profile matches the user's account step for step: 4.7 min
stationary, surface streets 280–450 s, the event at 424 s, then 52–65 mph from
450 s — the highway merge. Identification rests on that profile, not on the
clock: the logger puts the session start at 17:53 and the user recalls ~17:30.

**Sequence, all of it on D CAN.**

| t (s) | what |
|---|---|
| 424.016–424.028 | **one wheel channel drops to 256/260** while the other three hold 350–365 — spread **109 counts**. DBC labels it `WheelSpeed_RF`; see the caveat below |
| 424.019 | **`0x300` B2–3 starts falling**, 4800 → 2604 |
| 424.057 | **`0x208` B0 bit 6 asserts** |
| 424.099 → 424.236 | delivered torque collapses **−153 → −2 Nm in 0.14 s** (~1100 Nm/s) |
| 424.178 | **B2–3 reaches 2000** |
| 424.99 | `0x208` bit 6 releases after 0.97 s |
| 425.1 → 433.3 | B2–3 ramps back in 4-count steps: 2004, 2008, 2012, 2016, 2020, 2024 … |

> **Which corner it was: a DRIVEN front wheel. Established 2026-10-03.** The
> `0x208`-vs-halfshaft conflict raised earlier the same day is settled in the
> DBC's favour: in the 2026-03 defroster drive, a 369-count slip event moves the
> **front** pair (`0x200`) by 83 → 327 counts while the `0x208` pair stays flat at
> **1–7 counts**, which is what the DBC's "non-driven axle" comment already
> claimed. So `0x200`'s `WheelSpeed_LF`/`_RF` are the driven front pair and the
> channel that dropped here, `WheelSpeed_RF`, is a **driven** wheel losing grip
> under braking — which is the reading this event needs. The caveat below is
> retained only to record that it was once open.
>
> **Superseded caveat:** `traction-control-analysis.md`
> and `CODA-D-CAN.dbc` disagree about whether `0x208` B4–7 are the driven front
> halfshafts or the undriven rear wheels, and they are left/right-swapped and
> different widths between the two sources. That conflict is flagged in that
> file and is the user's to settle. **Nothing in this section depends on it:**
> the measurement is that *one of four* wheel-speed channels diverged by 109
> counts against a p99.9 of 79, which holds under either labelling. Do not read
> "RF" here as established fact.

**`0x212` never moves.** The published request holds −156.2 Nm throughout and for
a second afterwards. `0x312` TorqueFeedback and `0x1C0` Torque both show the
collapse, so the loss is in *delivery*, not in the request.

**`0x300` B2–3** (13 bits, firmware masks `B2:0x1F`, `B3:0xFF`), on the
`(raw − 2000) / 0.4` internal encoding at 0.1 Nm per count:

| raw | internal | Nm |
|---|---|---|
| 4800 | 7000 | **+700.0** |
| 2604 | 1510 | +151.0 |
| 2284 | 710 | +71.0 |
| **2000** | **0** | **0.00** |

Its behaviour across whole sessions is the striking part:

| session | n | distinct values | min | frames < 4000 |
|---|---|---|---|---|
| `coda_20261002_195747` | 49,527 | **1** | 4800 | 0 |
| `coda_20260904_181915` | 37,783 | **1** | 4800 | 0 |
| `coda_20261002_175334` | 46,081 | 89 | **2000** | 466, over one 9.30 s window |

46 of those frames are at exactly 2000. So the field is a constant in drives
where nothing happens, and in this drive it leaves that constant **once**.

**The DLCM reads exactly these bits.** `FUN_80080588` returns B2 mask `0x1F` and
B3 mask `0xFF`. That is not inferred from the DBC — it is from the accessor band
`0x800803FA`-`0x80080B4A`, which `coda-dlcm-decompile-notes.md` establishes is
the module's exhaustive declaration of every received field, verified by an
A0-relative scan returning zero buffer references from outside it.

**`0x208` B0 bit 6 is named by the firmware itself.** Accessor `FUN_8008060E`
(`a0-0x1060 & 0x40 >> 6`), consumed in `FUN_8006ED3C`, which stores a raw copy at
`a0-0x27d8` and a validity-qualified copy at `a0-0x27d2` (`0xD000682E`), and runs
a rationality counter against CAL `0xA00212BE` = 6000 feeding
**DEM event 124 = `U2111` "Invalid Anti Lock Braking System Brake Event"**. The
neighbouring bit via `FUN_800805EE` feeds event 123 = `U2110` "Invalid Anti-Lock
Braking System Lamp Request". So this is the ABS brake-event line, on the
module's own naming.

Its incidence is a clean one-off:

| session | `0x208` frames | bit-6 runs | frames set |
|---|---|---|---|
| `coda_20261002_175334` | 92,184 | **1** (t 424.02–424.99, 0.97 s) | 98 |
| 6 other sessions | 650,000+ | **0** | 0 |

**What the DLCM does with the ABS bit.** `0xD000682E` has exactly **one** reader
in the image: `FUN_800764F6` at `0x800766B6` (via `DlcmVarXref`). That function
computes `_DAT_d0006a38 - _DAT_d0005114` — a speed error against the signed speed
the APP-loss dig identified — runs a derivative through an IIR (CAL
`0xA00215E4`) and a 1-D table `0x80043FF4`, adds a proportional term (CAL
`0xA00215E2`), flips sign in reverse gear, clamps to ±`0xA00215F0`, and then:

```
bVar8 = DAT_d000682e == 0;       // ABS brake event clear
bVar9 = DAT_d0006831 == 0;       // commanded brake-lamp state clear
...                              // debounce against CAL 0xA00215EE
if (enabled) *(a0-0x258a) = *(a0-0x258c);   // pass the computed value
else         *(a0-0x258a) = 0;              // force output to ZERO
```

so the ABS event, ANDed with the brake-lamp state, **forces that function's
output to zero**.

**That function's calibration is untouched by this campaign.** Its table
`0x80043FF4` (x `0xA00215C4`, y `0xA00215D4`) and its gains `0xA00215E2`–`F4` are
not written by flash 7 or flash 8 — established by the byte attribution in
`artifacts/app_loss_map_exclusion_check.py`, which accounts for **every** changed
byte in both images and leaves none in that range.

**Motor CAN exists, and `0x212` is not the motor command.** From the DLCM's own
message tables, where the mailbox is the `u16` at record `+0x04`:

| table | record | CAN id | mailbox | bus |
|---|---|---|---|---|
| TX `0x80041B74` | 8 | `0x212` | `0x00E0` | main (D CAN) |
| TX `0x80041B74` | 10 | `0x312` | `0x0120` | main (D CAN) |
| TX `0x80041B74` | **11** | **`0x207`** | **`0x2080`** | **Motor CAN** |
| TX `0x80041B74` | **12** | **`0x204`** | **`0x2140`** | **Motor CAN** |
| RX `0x8004162C` | — | `0x209`–`0x20F` | `0x20xx`/`0x21xx` | **Motor CAN** |

The decode cross-checks: applied to the RX table it reproduces exactly the
`0x209`–`0x20F` group that `dlcm-dtcs-investigation.md` reached independently.
The three staging buffers are distinct RAM — `0x212` ← `a0-0x39e7`,
`0x207` ← `a0-0x39bd`, `0x204` ← `a0-0x3b28` + `a0-0x3be4` — so the published
request and whatever goes to the MCM are different variables by construction.

**Magnitude scales with the command; the floor does not.** Across 51 September–
October sessions, six other sessions carry a feedback-minus-request gap ≥ 60 Nm.
All six are at wheel spread 5–15 counts with `0x208` bit 6 **never set** — they
are ordinary regen-to-friction handoff approaching a stop, a different
phenomenon. Comparing magnitudes:

| | map asked | lost | ended at |
|---|---|---|---|
| pre-reflash brake fades | −95 … −107 Nm | 61–99 Nm | ~−20 Nm |
| 2026-10-02 clamp | −156.2 Nm | **154.5 Nm** | **~−2 Nm** |

The car ends near zero either way, so the **drop** is larger when the
calibration commands more. That is exactly the user's "more noticeable now",
and it is quantified rather than inferred.

### 7.2 The reading — HYPOTHESIS, not confirmed

**`0x300` B2–3 is an ESC-commanded torque limit that the DLCM obeys.** The
evidence is the correlation (it leaves its constant once, at the event, 3 ms
after the wheel slip), the encoding (it lands on exactly 0.00 Nm in the same
units as every other torque field on this bus), the firmware reading those exact
bits, and the delivered torque following it down. **This is not proven**: no
consuming code path has been traced from `FUN_80080588` to a torque output, and
the role name is an interpretation of a correlation.

Under that reading the answer to "what is the path" is that it is an **ESC
command on D CAN**, visible to our tap, rather than a DLCM decision hidden on
Motor CAN. The ABS brake-event bit is corroborating evidence of ESC intervention,
and its one traced effect — zeroing `FUN_800764F6` — is **not** the regen cut,
because that function is a speed-error controller and the sign and shape are
wrong for it.

Per the project notes rule this stays a hypothesis in prose and gets no `SG_`
entry in the DBC. A `CM_` comment is the most that is justified, and it has not
been written.

> **WEAKENED 2026-10-03 by the code trace in §7.4, same day.** The DLCM applies
> B2–3 as an **upper bound floored at zero** —
> `min(value, max(esc_limit, 0))`. Under the signed torque convention used
> everywhere else on this path (`0x212` signed, `M_MIN` negative, the envelope
> rule signed), an upper bound **cannot reduce regen**: `min(-1562, 0) = -1562`.
> So the decompiled mechanism does not obviously produce the effect that was
> measured, and the correlation in §7.1 now has a mechanism problem rather than
> a mechanism. Either the clamped quantity is a **magnitude** in that sub-path,
> or B2–3 going to zero is a *correlate* of the intervention rather than its
> cause. Do not resolve this by preferring whichever half is more convenient.
>
> **§7.5 sharpens this.** Across two drives there are **125** samples of large
> wheel slip under *drive* torque — up to 369 counts of spread at +262.8 Nm —
> and B2–3 stays at its idle value in every one. An upper bound on positive
> torque would have acted there. So the `min()` form and the observed behaviour
> disagree about which sign this field governs, and that disagreement is the
> open problem, not a detail.

### 7.3 Open

- ~~**The sign convention of B2–3**~~ — **RESOLVED, §7.6/§7.7.** The clamped
  quantities are magnitudes, negated per direction by `FUN_800768D6`, so
  `min(magnitude, max(esc, 0))` at esc = 0 is a zero regen floor. There are two
  clamps, one per sign, and they swap with travel direction: forward, B2–3 is
  the regen limit and B4–5 the drive limit. The
  normal value is **+700 Nm**, far above the 300 Nm motor ceiling, so it is
  inert by magnitude rather than by sign. Whether 0 means "no torque either way"
  or "no regen" is not established. **The user has identified the test:** the
  early `codadriveslowturnonwithdefroster*.log` drives should contain
  positive-torque clamp events. If B2–3 drops while drive torque collapses, it
    clamp and the question is settled. **Tested 2026-10-03: NEGATIVE** — §7.5.
  Neither field nor the ABS bit leaves idle anywhere in those drives, so the
  question is still open and needs a different population.
- ~~**How the DLCM applies the limit internally**~~ — traced, §7.4. It is a
  `min()` clamp in `FUN_800771FA` inside the torque task, not a pass-through.
  **But the trace raised a sharper question than it answered**: the clamp is an
  upper bound floored at zero and cannot reduce a signed negative torque. See
  §7.5's closing paragraph.
- **Why `0x212` keeps publishing the pre-limit request.** `FUN_800771FA` writes
  `a0-0x255a` / `a0-0x2540`, and `0x212` is assembled from `a0-0x39e7`
  (TX record 8), so they are different RAM — consistent with the request being
  published upstream of the clamp, but **not traced**, and not proven.
- **The identity of `FUN_800764F6`.** It is a clamped speed-error PD controller
  gated off by ABS and in P/N, reached from `FUN_8007C33A`. The shape fits a
  creep or speed-hold contribution, which would make it positive torque — but
  it is **not identified**, and the §1A creep-assist work is the obvious
  neighbour to check against. Next step: who writes `_DAT_d0006a38` (the
  target), and who reads `a0-0x258a` (the output).
- Whether the reduction is executed by the DLCM on Motor CAN or by the MCM
  autonomously. The Motor CAN link (`0x204`/`0x207`) is untapped, so this is
  not answerable from D CAN alone — but it is not needed for the limit
  question above.

### 7.4 The path, traced 2026-10-03 — how the DLCM applies it

Confirmed, each step from the image:

| step | evidence |
|---|---|
| ESC transmits `0x300`, two 13-bit fields: B2–3 and B4–5 | DBC + logs |
| DLCM reads them via `FUN_80080588` (B2–3) and `FUN_80080572` (B4–5) | accessor band, exhaustive |
| `FUN_8006F05A` scales **both identically** and stores them | ← `FUN_8006ED2C` ← `FUN_8007C2C6` |
| scaled values at `0xD0006824` (B2–3) and `0xD0006826` (B4–5) | adjacent `u16`s |
| each read in **exactly one** place, adjacent instructions in `FUN_800771FA` | `DlcmVarXref`: 1 read, 0 writes each |
| `FUN_800771FA` ← `FUN_8007689C` ← `FUN_8007C33A` — the torque task | caller chain |

**The scaling is the firmware's own, and it settles the units.**
`FUN_8006F05A` computes `raw * 5 >> 1 - 5000`, i.e. **raw x 2.5 − 5000**, giving
internal counts at 0.1 Nm. That is exactly the DBC's `scale 2.5, offset −5000`
for `MMAX_ESP_REGEN_TQ_REQ`, now confirmed from code rather than assumed, and it
reproduces §7.1's table without going through the `(raw − 2000) / 0.4` form:
raw 4800 → **7000 internal = +700.0 Nm**, raw 2000 → **0**.

**How it is applied.** `FUN_800771FA` is 160 bytes and does nothing but apply
these two clamps:

```
esc1 = _DAT_d0006824 * (0 < _DAT_d0006824)        // floor the limit at 0
if (fault_3e9d || fault_3e9e || CAL_a0021715 == 0 || value1 <= esc1)
        out1 = value1                              // pass through
else    out1 = esc1                                // clamp
                                                   // => min(value1, max(esc1,0))

esc2 = _DAT_d0006826 * (0 < _DAT_d0006826)
if (DAT_d0006844 && !fault_3e9c && CAL_a0021716 && esc2 < value2)
        out2 = esc2
else    out2 = value2                              // => min(value2, max(esc2,0))
```

So **both ESC fields are `min()` clamps**, each with its own CAL enable byte and
its own fault gates. Outputs go to `a0-0x255a` and `a0-0x2540`.

**Both clamps are enabled, and this campaign does not touch them.**

| byte | role | stock | as-flashed C4c | f7 | f8 |
|---|---|---|---|---|---|
| `0xA0021715` | B2–3 clamp enable | 1 | 1 | 1 | 1 |
| `0xA0021716` | B4–5 clamp enable | 1 | 1 | 1 | 1 |

Consistent with the byte attribution in
`artifacts/app_loss_map_exclusion_check.py`, which accounts for every changed
byte in both images and leaves none in that range.

**What this does NOT explain, and it is the open centre of the problem.** A
`min()` floored at zero is an **upper** bound. Under the signed convention used
everywhere else on this path it cannot make regen less negative. And the two
published limits did not move in the direction needed either: during the event
**`M_MIN` held −300.0 Nm for the entire window**, and `M_MAX` tracked the power
curve and the brake switch (97 → 229 → 280 → 299.8, then 29.75 once the brake
switch latched), neither of them following B2–3 down. So:

- `FUN_800771FA`'s outputs are **not** `M_MAX`/`M_MIN` as published on `0x312`;
- the quantity actually reduced — delivered torque, seen on `0x312`
  TorqueFeedback and `0x1C0` — has no traced connection to this clamp yet.

The honest state is: **a confirmed ESC→DLCM clamp mechanism exists and is live,
and a confirmed regen collapse coincides with its input going to zero, and the
two have not been joined.** Next step is to identify `a0-0x2552` / `a0-0x255a`
and `a0-0x253a` / `a0-0x2540` — if either pair is a magnitude rather than a
signed torque, the tension dissolves.

### 7.5 The defroster drives — slip in abundance, and B2–3 never fires

> **Superseded in part by §7.7.** This section checked the wrong field for a
> positive-torque population. B2–3 governs the regen side in forward motion;
> the drive-side clamp is B4–5, and it **does** fire in these drives. The slip
> measurements below stand; the conclusion "the clamp mechanism is absent from
> these drives" does not.

The user's test for the sign convention (2026-10-03) was that the early
`codadriveslowturnonwithdefroster*` drives should contain positive-torque clamp
events. They do not, on three independent checks of `...defroster2.log`
(697 s, 69,689 aligned samples, D CAN identified by all five audited anchors):

| check | result |
|---|---|
| `0x300` B2–3 | **constant 4800** — 1 distinct value in 34,615 frames, 100.00 % at idle |
| `0x208` B0 bit 6 (ABS brake event) | **0 in all 69,689 samples** |
| `M_MAX` below 290 Nm with brake off | 19,281 samples, but it tracks the **power curve** (289.8 Nm at 33 mph → 235.8 at 42 mph) with request ≈ delivered throughout — not a clamp |

**But those three checks do not establish a negative on their own, and the first
version of this section wrongly implied they did.** They show the *response* is
absent; they say nothing about whether the *trigger* occurred. Concluding
"no clamp events" without first establishing that slip happened is mode 1 of
`AGENTS.md` → Filters that fail silently — and the population here is very far
from empty. Corrected the same day, after the user asked whether the slip events
were present at all.

**The slip is there, and it is larger than the 2026-10-02 event.** Over 46,343
samples above 4 mph in `...defroster2.log`:

| wheel-speed spread | p50 | p90 | p99 | p99.9 | max |
|---|---|---|---|---|---|
| all four channels | 9 | 22 | 58 | 159 | **369** |
| the `0x208` pair alone — what the 2026-03 method used | 3 | 15 | 45 | 60 | 92 |

**82 samples reach ≥ 80 counts**, against the 109-count excursion that
accompanied the regen cut. The largest are unambiguous wheelspin:

| t (s) | spread | mph | request | `0x300` B2–3 | ABS bit |
|---|---|---|---|---|---|
| 586.17 | **369** | 14.4 | **+262.8 Nm** | 4800 (idle) | 0 |
| 514.33 | 219 | 14.8 | +274.5 Nm | 4800 (idle) | 0 |
| 586.65 | 97 | 12.5 | +256.0 Nm | 4800 (idle) | 0 |
| 97.76 | 92 | 12.5 | +145.0 Nm | 4800 (idle) | 0 |

Every one is at **positive** torque, and in every one **neither traced signal
moves**.

**That makes the negative result evidence rather than an absence of evidence,
and it points the opposite way from the code form.** Combining both drives:

| population | samples | `0x300` B2–3 clamp |
|---|---|---|
| large spread under **drive** torque (82 here + 43 in the 2026-10-02 drive) | **125** | never fires |
| large spread under **regen**, with brake applied (2026-10-02) | **2** | fires, to 0 Nm |

So **slip is not what separates the two populations** — it is abundant in both.
The torque sign and the brake application are. And this cuts directly against
reading B2–3 as a drive-torque upper bound, which is what the `min()` form in
§7.4 looks like: an upper bound on positive torque is precisely what should have
acted on a 369-count wheelspin at +262.8 Nm, and it did not. **§7.4's sign
tension is therefore sharper after this test, not softer.**

The sign question is resolved in §7.6, and §7.7–§7.8 show the positive-side clamp does exist — on B4–5, with 10 sustained instances corpus-wide. `codadriveslowturnonwithdefroster.log` (the first one)
**cannot** answer it at all: no bus in that capture carries the D-CAN anchors —
bus 3 has only the rebroadcast set (`0x1C0`, `0x200`, `0x208`, `0x210`, `0x212`,
`0x215`), bus 2 is the C-CAN cell bus, bus 1 carries only the immobiliser
handshake — so `0x300` and `0x312` are not in the file. The discriminator
**refused rather than selecting bus 3**, which is the `AGENTS.md`
"discriminator that cannot fail" rule behaving correctly: bus 3 has D-CAN
*content* but no exclusive anchor, and picking it would have produced a
confident label on a capture that cannot answer the question.

**Two further corrections to `../traction-control-analysis.md`, both measured
here.** First, `0x200` **is** present on this drive's D CAN bus (69,230 frames
alongside `0x208`'s 69,230), so the front pair was available in 2026-03 and that
file's "No front/rear distinction is available" was a limitation of the decode in
use, not of the capture. Second, the pair that file did use tops out at **92**
counts where all four channels reach **369**, so its method could not see the
largest events in its own drive — its 17 events were found with a ≥ 30-count
threshold against a p90 of 15 on that pair.

**And a third, on its "second mechanism".** This file's companion
`../traction-control-analysis.md` records a "second TC mechanism: symmetric
slip", detected by a torque-cut rule of "torque drops > 20 Nm in 0.5 s while
throttle stays within 5 % and is > 3 %". Applied to that same drive's own
cluster windows (t = 55–152 s) the rule fires **578 times in 97 seconds**, with
`M_MAX` at 299.8 Nm (not limiting) and the ESC field at idle in every one. A
rule that fires 578 times in 97 s of ordinary driving is not detecting a rare
event, so that section's second mechanism should be treated as unestablished
until re-derived. Flagged there as well.

### 7.6 RESOLVED 2026-10-03 — the clamped quantities are MAGNITUDES, and there are two clamps, one per sign

The sign tension in §7.4 and §7.5 is gone, and it was resolved by identifying the
four variables rather than by preferring either side of the contradiction.

**The producer.** `FUN_80076D72` (← `FUN_8007689C` ← `FUN_8007C33A`) writes both
clamp inputs, each as the smaller of two candidates:

```
a0-0x2552 = min(a0-0x254e, a0-0x3eb2)      // input to the B2-B3 clamp
a0-0x253a = min(a0-0x2538, a0-0x253c)      // input to the B4-B5 clamp
```

so each is already "the most restrictive of several" before the ESC clamp is
applied at all.

**The consumer, and this is the decisive part.** `FUN_800768D6` (same caller)
takes the two clamp *outputs* and **negates one, passing the other through** —
with which one is which selected by a direction flag:

```
cVar4 = (DAT_d00050ab == 0 && flag_2519) || (DAT_d00050ab != 0 && flag_251b)

a0-0x2560 = -( cVar4 ? a0-0x255a : a0-0x2540 )    // the NEGATIVE limit
a0-0x255e =  ( cVar4 ? a0-0x2540 : a0-0x255a )    // the POSITIVE limit
```

A value that is negated to form a limit is a **magnitude**, not a signed torque.
That dissolves the contradiction: `min(magnitude, max(esc, 0))` with the ESC
field at 0 gives magnitude 0, and negating 0 gives a regen floor of **0 Nm**.
The `min()` form was never an upper bound on signed torque; it is an upper bound
on *how much torque is available in that direction*.

`DAT_d00050ab` is the gear/forward latch already identified by the `DAT_d0006937`
dig (§ the plan's §2.2): 1 in D, 0 in R. The two debounced flags compare the
signed speed `_DAT_d0005114` against CAL `0xA00216EC` = **+140** and
`0xA00216EE` = **−140** with debounce `0xA00216FA` = **20** — the same
±threshold-with-debounce shape as the creep-direction flag. **Moving forward**
(D, speed > +140) gives `cVar4 = 1`, so:

| direction | negative limit (regen) | positive limit (drive) |
|---|---|---|
| **forward** | −(B2–3 clamped) | B4–5 clamped |
| reverse | −(B4–5 clamped) | B2–3 clamped |

They **swap with direction**, which is what a magnitude pair must do: in reverse,
"drive" torque is negative and "regen" positive.

### 7.7 So the positive-side clamp DOES exist in the defroster drives — on the other field

§7.5 reported the defroster test as negative. That was wrong, and wrong for a
second reason beyond the one §7.6 records: it checked **B2–3**, which §7.6 now
shows governs the *regen* side in forward motion, against a population of
**positive-torque** wheelspin. The clamp that should act there is **B4–5**, and
it was never looked at.

Measured at the 369-count wheelspin in `...defroster2.log`, t ≈ 586 s:

| t (s) | request | B2–3 internal | **B4–5 internal** | delivered |
|---|---|---|---|---|
| 585.61 | +287.2 | 7000 | 2870 | 282.8 |
| 585.98 | +272.2 | 7000 | 2750 | 245.8 |
| 586.10 | +267.2 | 7000 | 2180 | 261.5 |
| 586.23 | +259.2 | 7000 | **1938** | 171.5 |
| 586.36 | +253.0 | 7000 | **1678** | **166.5** |
| 586.60 | +254.2 | 7000 | 2998 | 240.5 |

**B4–5 falls to 1678 internal = +167.8 Nm against a request of +253.0 Nm, and
delivered torque follows it to 166.5 Nm.** B2–3 sits at its 7000 sentinel
throughout. That is a drive-torque clamp binding during wheelspin — exactly the
positive-side event the user predicted would be in these drives.

**This also corrects §2's "never binds" at its root.** B4–5 mirrors the request
closely in ordinary driving — at t = 585.61 it reads 2870 against a request of
2872 — and **departs downward when the ESC intervenes**. "It reports rather than
constrains" was measured on three drives in which it never departed. It is a
limit that happens to idle at the value it is limiting, which is the hardest kind
of limit to catch: the evidence for "mirror" and the evidence for "limit" are the
same samples until the one moment they differ.

**A naming problem follows, and it is NOT resolved here.** The DBC calls B4–5
`MMAX_ESP_REGEN_TQ_REQ`, but B4–5 is the field observed clamping **drive** torque,
while B2–3 — unnamed in the DBC — is the one that clamped **regen**. Either the
name is on the wrong field, or it means something more general than "regen".
Per the project notes rule this is a signal-role question and stays a flagged
conflict rather than a DBC edit; no `SG_` is added and no rename is made.

### 7.8 Corpus scan, 2026-10-03 — both clamps confirmed, n=5 and n=10

Run once the two fields were declared in the DBC, so the signatures could be
searched for directly instead of inferred. `artifacts/tc_regen_intervention.py
--corpus`, 363 sessions of `CANLogs/CodaLogs`, **281 readable** (82 refused —
no bus in them carries two distinct audited D-CAN anchors, mostly the early
2026-03 captures and the diagnostic/charging logs).

**The braking-side clamp: 5 episodes, and `ABS_BrakeEvent` is coincident in
every one.**

| session | t (s) | ABS event | clamp | mph | request | brake |
|---|---|---|---|---|---|---|
| `coda_20260429_222231` | 120.99 | 0.70 s | 5.65 s | 14.6 | −84.2 Nm | 164 |
| `coda_20260510_153916` | 120.39 | 0.64 s | 21.17 s | 18.0 | −69.0 Nm | 90 |
| `coda_20260617_191308` | 122.76 | 1.01 s | 2.53 s | 15.6 | −71.2 Nm | 158 |
| `coda_20260702_001157` | 213.73 | 1.07 s | 18.97 s | 19.9 | −71.5 Nm | 109 |
| `coda_20261002_175334` | 424.02 | 0.97 s | 9.31 s | 12.2 | **−156.2 Nm** | 181 |

The two signatures start within **one sample** of each other in all five, the
limit reaches **exactly 0** in all five, and all five are regen under braking at
**12–20 mph**. Four of the five predate the reflash campaign entirely. Traced
frame by frame in all four new logs, the shape is identical every time:

```
brk_lim 7000 (idle), regen flowing, req ~= fb
  -> ABS_BrakeEvent 0->1 and brk_lim -> 0 in the same or the next sample
  -> delivered torque collapses to ~0 within ~0.1 s
  -> request keeps asking its full value throughout
  -> ABS clears, brk_lim returns to 100, delivered regen resumes
  -> brk_lim ramps back to 7000
```

**The recovery value is the best independent confirmation of §7.6.**
`brk_lim` does not jump from 0 back to its 7000 sentinel; it passes through
**100 internal = +10 Nm**, and delivered regen comes back at about that
magnitude (−9.5, −4.0, −12.5 Nm in `coda_20260617_191308`). A limit that
permits "10 Nm of regen" is a magnitude being negated, exactly as
`FUN_800768D6` says. Nothing in the clamp arithmetic was needed to predict
that — it fell out of the data.

**And the magnitude scaling now has n=5 rather than n=1.** Same mechanism, same
speeds, same end state of ~0 Nm; what changed is how much there was to lose:

| | request at the clamp | lost |
|---|---|---|
| four 2026-04 … 2026-07 events | −69 … −84 Nm | 69–84 Nm |
| 2026-10-02, post-C4c | **−156.2 Nm** | **156 Nm** |

That is the user's "more noticeable now since the regen torque was higher",
measured. The intervention is not more frequent and not faster; it removes
roughly twice as much.

**The tractive-side clamp: 10 sustained episodes, and they are the positive-side
events the user predicted.** 516 raw hits, but the duration distribution splits
them cleanly — p50 **0.01 s**, p90 0.03 s, and only **10 at or above 0.25 s**.
The 506 brief ones are the limit tracking the request through fast pedal
movement, not clamping. The 10 sustained ones are strikingly uniform:

| | |
|---|---|
| speed | 13.2 – 21.9 mph |
| request | 281 – 300 Nm — i.e. at the motor ceiling |
| limit falls to | 148 – 223 Nm |
| duration | 0.27 – 0.41 s |

Hard acceleration at low speed, the ESC pulls tractive torque back by 80–150 Nm
for about a third of a second. Ten instances across 281 sessions, spanning
2026-05-01 to 2026-09-21. `codadriveslowturnonwithdefroster2.log`'s t=586 event
(§7.7) is **not** in this list: it lives in `projects/coda/logs/`, which the
corpus scan does not glob — that folder was scanned separately and is almost
entirely diagnostic and charging captures with no D-CAN anchors.

**So both signs are now confirmed corpus-wide, and the two clamps behave
differently.** The braking-side one goes to **zero** and holds for seconds; the
tractive-side one is a **partial** pull-back for a fraction of a second. That
asymmetry is a finding in its own right and was not predicted by the code,
which applies both through the identical `min()`.

### 7.9 A units error in this investigation's own detector

**The first run of the §7.8 tractive detector was wrong, and it was wrong in the
way this file had already documented.** It tested
`request - ESP_TractiveTqLimit >= 25`, comparing a value in **Nm** (scale 0.25)
against one in **internal counts** (scale 2.5) — the exact 10x boundary recorded
in §2's units note earlier the same day.

It did not fail loudly. It returned **450 episodes**, every one shorter than
0.2 s, which are regen-to-drive transitions where the request had gone positive
while the limit still read a regen value. And it **missed the one sustained
tractive clamp already known** (defroster2 t=586, limit +167.8 Nm against a
+253.0 Nm request), because across the unit boundary that comparison evaluates
false. A detector that produces 450 plausible-looking hits and silently drops
the one confirmed instance is worse than one that returns nothing.

Fixed by an explicit `INT_TO_NM = 0.1` conversion, with the trap written into
the script so the next reader meets it before the code. Re-run gives 516 hits of
which 10 are sustained, and the known defroster event's shape is reproduced.

**The lesson is narrow and worth stating exactly:** the DBC decodes the two
`0x300` limits to internal counts and the `0x212`/`0x312` torque fields to Nm.
Any comparison between them needs a conversion, and nothing in either name says
so. This is the third time in this file that the 0.1 Nm count has caused an
error — after the 0.096 docstring and the −1570/−1562 near-coincidence.

### 7.10 Four traps this investigation walked into

- **Gating a detector on the request.** The first detector looked for `0x212`
  rising toward zero while coasting. The request *never moves* during this
  event, so that detector was blind to it by construction, and what it did
  return was the ordinary low-speed taper — 23 "events" at ~7 mph, all going
  −135 → −95 Nm. The uniformity was the tell. Mode 1 of *Filters that fail
  silently*: the premise excluded the case.
- **A threshold that conflated two mechanisms.** Switching to
  `feedback - request >= 60 Nm` found 7 events and would have supported
  "this happens routinely, pre- and post-reflash". Six of them are brake fades.
  Only wheel spread separates them, and the separation is sharp: 109 counts
  against 5–15. A gap threshold alone measures "regen is not being delivered",
  which is true of both.

- **Calling a negative result before checking that the trigger occurred.** The
  defroster test was first reported as "no clamp events in these drives" on the
  strength of three checks that all measured the *response* — `0x300` B2–3, the
  ABS bit, and `M_MAX`. None of them asked whether any wheel slip had happened.
  The user's question — *"did you see the slip events in either log?"* — is what
  surfaced it, and the answer turned out to be 82 samples up to 369 counts of
  spread, larger than the event that started this investigation. The first
  reading was not merely incomplete: it was the difference between an
  uninformative absence and the most useful measurement in §7.5, because a
  trigger that fires without the response is evidence about what the response
  responds to. `AGENTS.md` states the rule — "when a filter returns nothing,
  establish that the population is non-empty before concluding the answer is
  negative" — and this section had been written in the same sitting as two
  other instances of it.
- **Checking the wrong field against the right population.** §7.5 tested the
  defroster drives for a *positive*-torque clamp and reported a negative — while
  only ever examining **B2–3**, which §7.6 then showed is the *regen*-side limit
  in forward motion. The drive-side field, B4–5, was two bytes away, already in
  the DBC, already read by the firmware, and binding hard at the exact timestamps
  the search had surfaced. The search was correct, the population was correct,
  and the field was wrong, so the result read as a clean negative. It took the
  user asking whether the slip events were present at all, and then identifying
  the four clamp variables, to find it.

  The general form is the one worth keeping: **this file has now twice scoped a
  conclusion about a *message* to one *field* of it** — §2 concluded "the ESC
  never binds" from B4–5 alone, and §7.5 concluded "the clamp is absent" from
  B2–3 alone. Both times the other field held the answer. When the firmware's
  accessor band says the DLCM reads several fields of a message, test all of
  them before writing a verdict about the message.

- **Comparing two fields of the same message across a 10x unit boundary.**
  §7.9 has the instance. The general form: `AGENTS.md` makes the DBC the source
  of truth for scaling, and a DBC may legitimately carry the same physical
  quantity at two different scales — here `0x300`'s limits in internal counts
  and `0x212`/`0x312`'s torques in Nm. **A signal name does not carry its
  unit**, so any cross-field comparison has to convert explicitly, and a
  detector that compares them raw will return a plausible population rather
  than an error.
