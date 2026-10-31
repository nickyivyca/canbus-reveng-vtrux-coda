# DLCM Torque Limiter — Modern (§10.7) vs Old-Scheme Trace

**Created 2026-07-08 (overnight autonomous run). Status: behavioral verdict HIGH confidence; code-level internal trace VOID — see the 2026-09-19 note below.**

## Terminology: gradient limiter tables (renamed 2026-09-23)

The limiter's tables are named as in DLCM Functional Requirements V4.2 section 10.7
(the Simulink diagram on p83). Earlier revisions of this file used nicknames; in
particular **"second jaw" was used for two different tables** (`0x80043FAC` on the
rising side and, in a few places, `0x80043FA0` on the falling side). The rename was
applied mechanically by `artifacts/rename_limiter_terms.py`.

| spec name (s10.7) | prose short form | old nickname(s) | indexed by | descriptor | y values (L1 / monitor copy) |
|---|---|---|---|---|---|
| `gradientLimiterPositive_VehSpd` | speed limb | jaw, second jaw, `D_JAW_UP` | speed | `0x80043FAC` | `0xA0021508` / `0xA0021B4C` |
| `gradientLimiterPositive_TrqLast` | V-curve | V-curve, `D_VCURVE` | TrqLast | `0x80043FB8` | `0xA0021528` / `0xA0021B64` |
| `gradientLimiterNegative_TrqLast` | negative TrqLast limb | `D_JAW_DOWN`, jaw_down | TrqLast | `0x80043FA0` | `0xA00214E8` / `0xA0021BB4` |
| `gradientLimiterNegative_BrakePress` | brake-pressure limb | `D_STEP_DOWN` | brake analog | `0x80043F94` | `0xA00214C0` / `0xA0021B8C` |
| `gradientLimiterNegative_BrkSwOff` | BrkSwOff constant | `C_STEP_NOBRAKE` | (scalar, -100) | -- | `0xA002153E` |
| `gradientLimiterNegative_BrkSwOn` | BrkSwOn constant | `C_STEP_BRAKE` | (scalar, -100) | -- | `0xA0021540` |

Code constants in `artifacts/torque_path_sim.py` *(Deleted 2026-10-10 at codasim plan step 7; the model is now `../../tools/codasim/`. Recorded outputs stand.)*: `D_GL_POS_VEHSPD`, `D_GL_POS_TRQLAST`,
`D_GL_NEG_TRQLAST`, `D_GL_NEG_BRAKEPRESS`, `C_GL_NEG_BRKSWOFF`, `C_GL_NEG_BRKSWON`.
Rising step = `min(speed limb(speed), V-curve(TrqLast))`. Falling step:
`max(brake limb, negative TrqLast limb)`, where the brake limb is the
brake-pressure table when brake pressure is valid, else the BrkSwOn/BrkSwOff
constant selected by the brake switch (`FUN_80075DFA`).

**The falling combine is `max()`, not the `min()` the decompile appears to show**
(established 2026-09-23; this paragraph previously said only "combined with",
which left the operator unstated). Both limbs are negative, so `max()` is the
*shallower* of the two -- the same "least aggressive limit wins" semantics as the
rising side's `min()`, not the opposite.

Measured directly, on the pre-scale-3 calibration: **-8 raw per published
sample** at negative TrqLast. Mind the units -- that is the *published* rate.
The limb entry is -10 internal per 100 Hz tick, and the limiter ticks twice
between 50 Hz publishes, so -10 internal/tick x 2 ticks x 0.4 raw/internal =
-8 raw/sample. The brake limb at the same instant is `gradientLimiterNegative_BrkSwOff`
= -100 internal/tick. `max(-100, -10) = -10` reproduces the measurement;
`min(-100, -10) = -100` would give -80 raw/sample, ten times what the car does.

(The four entries that measurement rests on were scaled x3 on 2026-09-23 --
`gradientLimiterNegative_TrqLast` idx0..3 are now `[-30, -30, -21, -12]` -- so
re-measuring today gives -24 raw/sample, not -8. The `max()` conclusion is
unaffected; only the number changed.)

> **⚠ 2026-09-19.** The "obfuscation" that limited the code-level trace was not
> obfuscation. The DLCM is an **Infineon TriCore, little-endian** and the trace was made
> against an SH-4 big-endian decode of the image, so the instruction-level reasoning in
> this file is void. **The behavioural verdict, drawn from CAN logs and vehicle response,
> is unaffected** — it never depended on the disassembly.
>
> This is good news for the goal: the wall this file hit was an artefact, and the trace
> can now be redone properly under `tricore:LE:32:default`. See
> `coda-dlcm-decompile-notes.md` → Architecture.

## Question

The v4.2 DLCM spec restructured its near-zero torque-shaping functions at **Rev 2 (2011-07-14, changelog item 25)**: it *deleted* the **Zero Crossing Filter** + **Zero Torque Rate Limiter** and *added* the **Torque Smoothing Filter (§10.6)** + **State Dependent Torque Gradient Limiter (§10.7)**. The v4.2 body is internally inconsistent — §8.3.1.1 and §8.3.8 still name the old "zero crossing filter" / "zero torque filter" — and the firmware label `1CI527_D003` does not disambiguate the spec revision it was built against.

Mapping of the two eras (see also `dlcm-torque-flow.md` for the modern §10.7 block diagram):

| Function | Old (pre-Rev-2) | Modern (v4.2) |
|---|---|---|
| Smoothing filter | Zero Crossing Filter | §10.6 Torque Smoothing Filter (3rd-order IIR, time-constant LUT) |
| Rate limiter | Zero Torque Rate Limiter | §10.7 **State Dependent** Torque Gradient Limiter |
| Damper | Active Speed Damper | §10.5 Active Speed Damper (unchanged) |

**The distinguishing feature is state-dependence.** The modern §10.7 rate limiter is parameterized by vehicle speed, TrqLast, and brake pressure via calibration LUTs combined with `min()`. The old "Zero Torque Rate Limiter", by its name and the "**State Dependent**" rename that replaced it, was a near-zero rate clamp keyed on torque only. So: **does the firmware's torque rate limiter depend on vehicle speed and brake state (modern §10.7), or only on torque (old scheme)?**

---

## TL;DR verdict

**The firmware implements the modern §10.7 State Dependent Torque Gradient Limiter.** The torque rate limit is strongly, cleanly, and reproducibly **vehicle-speed-dependent**, with the exact `min(VehSpd-limb, TrqLast-limb)` structure §10.7 specifies. An old torque-only Zero Torque Rate Limiter is ruled out — it structurally cannot produce a speed-dependent rate cap.

- **Behavioral evidence (HIGH confidence):** across three drive logs, the accelerating per-update torque rate collapses from ~50 cts/update near standstill to ~1–3 cts/update at high speed, holding flat across all TrqLast bands at high speed — a textbook two-input `min()` surface. Survives a demand-controlled confound check.
- **Code corroboration (MEDIUM confidence):** the torque-compute path calls **six** distinct fixed-point interpolation kernels via a chain of wrappers, plus a path-select compare, feeding the §10.6 IIR then TX. Multi-LUT structure is consistent with §10.7's four gradient LUTs and inconsistent with a single fixed clamp.
- **Code caveat (important):** the *internal register dataflow* of the limiter (which kernel is indexed by VehSpd vs TrqLast vs BrakePress) **cannot be reliably read statically** — the region is corrupted by Continental's literal-pool-interleaving obfuscation and per-task GBR aliasing. The prior notes' "§10.7 topology confirmed at D1CE-D224" is **over-stated** (it was hand-curated from pool-contaminated disassembly). The modern-vs-old determination therefore rests decisively on the behavioral evidence, with the code providing consistent structural support but not an independent instruction-level proof of the VehSpd binding.

---

## Method: why the answer leads with behavior, not disassembly

The obvious approach — disassemble the limiter and read which signals index which LUT — fails here, and it is worth being explicit about why, because the prior investigation spent ~10 sessions against this wall.

The torque-limiter region (`0x8006D176`–`0x8006D224` and its DBxx/DCxx/DDxx/E-region helpers) is **densely interleaved with literal-pool words** that decode as plausible-but-fake SH-4 instructions. Raw dumps of the helpers show this directly: e.g. `FUN_8006dbee` decodes as an incoherent jumble (`cmp/eq`, `clrt`, `fmov fr15,@(r0,r15)`, `dmulu.l`, `mov.b r0,@(0xf1,gbr)`), which is the signature of pool data being read as code. Only the branch instructions Ghidra's recursive disassembler actually followed to real function bodies (`bsr DBC0`, `cmp/ge r0,r12`, `bf D20A`, `bsr DBEE`, `bra D40A`) are trustworthy; everything between them is suspect. Additional NOP/SLEIGH patches do not fix this — the problem is data-in-code, not an unmodeled opcode.

Given that, the reliable discriminator is **behavioral**: the modern and old schemes make different, testable predictions about the transmitted torque signal, and the drive logs are ground truth.

- Modern §10.7 positive limb: `rate = min(gradLimPos_VehSpd[VehSpd], gradLimPos_TrqLast[TrqLast])` → above the lash zone (TrqLast limb open), the accelerating rate should **decrease with vehicle speed**.
- Modern §10.7 negative limb: `rate = min(brake_selector(BrakePress/BrakeSwitch), gradLimNeg_TrqLast[TrqLast])` → the regen (descending) rate should **depend on brake state**.
- Old Zero Torque Rate Limiter: near-zero rate is a function of torque only → **invariant** to vehicle speed and brake.

Ground-truth signals (D_CAN, single bus, deduped; script `artifacts/torque_limiter_scheme_test.py`, output `artifacts/torque_limiter_scheme_test.out.txt`):
- torque = `0x212` raw `(B4&0x0F)<<8|B5`, zero=2000, signed=raw−2000 (50 Hz on one bus; the earlier "sub-frame pairs" were dual-bus duplication, not a mux).
- vehicle speed = `0x208` WheelSpeed_LR `(B6<<8|B7)−0xC000` (reference-speed proxy, non-driven axle, per DBC).
- brake pressure = `0x208` BrakePressure `(B2<<8|B3)−4096`; brake switch = `0x200` B1 bit0.

---

## Behavioral evidence (decisive)

### 1. Vehicle-speed dependence of the accelerating ramp — the `min()` surface

Median rising-step rate (cts/update) over TrqLast (rows) × VehSpd (cols), `frombonnydoon.log` (representative of all three logs):

```
  TrqLast\VehSpd |  0-100  100-300  300-600  600-1000  1000-1500  1500+
      40-100     |   6.0     7.0      7.0       2.0        2.0       1.0
     100-200     |   9.0    26.0      4.0       2.0        2.0       1.0
     200-350     |  16.0     2.5      7.5       2.0        2.0       1.0
     350-550     |  10.0    56.0      7.0       3.0        1.0        -
     550-800     |  33.0     8.0      2.0       3.0         -         -
     800+        |  56.0    13.0      1.5        -          -         -
```

- **Down a high-speed column** (600–1000): `2, 2, 2, 3, 3` — flat regardless of TrqLast → the **VehSpd limb binds**.
- **Down the low-speed column** (0–100): `6, 9, 16, 10, 33, 56` — grows with TrqLast → the **TrqLast limb binds**.
- **Across the high-TrqLast row** (800+): `56, 13, 1.5` — collapses as speed rises → transition from TrqLast-bound to VehSpd-bound.

This is exactly `min(f(VehSpd), g(TrqLast))` with `f` decreasing in speed and `g` increasing away from zero. The same structure appears in all three logs.

### 2. Demand-controlled confound check

A skeptic could argue the low high-speed rate merely reflects the driver not demanding fast torque at speed. Restricting to **sustained** demand ramps (torque rising ≥4 updates in a row):

| Log | low-speed (v≤800) | high-speed (v>800) |
|---|---|---|
| frombonnydoon | n=2314 med=8 p90=30 max=56 | n=1188 med=4 **p90=12** max=55 |
| driveafterfullycharged | n=1240 med=10 p90=33 max=56 | n=379 med=4 **p90=9** max=22 |
| codadrive…defroster2 | n=1170 med=12 p90=27 max=56 | n=441 med=4 **p90=14** max=33 |

Even under sustained demand, high-speed steps are capped ~3× lower (p90 9–14 vs 27–33). Driver demand cannot produce that — it is a hard speed-dependent rate cap. **Confound rejected.**

### 3. Regen (negative) limb vs brake — weak positive

Descending (drive→regen) ramp rate below the lash zone, braking vs coasting:

| Log | braking median (min) | coasting median (min) |
|---|---|---|
| frombonnydoon | 0.0 (−9) | 0.0 (−8) |
| driveafterfullycharged | −1.0 (−9) | 0.0 (−8) |
| codadrive…defroster2 | −1.75 (−12) | 0.0 (−8) |

Braking allows a steeper regen descent (min −12 vs −8; the down-crossing in defroster2 was −7 braking vs −3 not). Direction matches the §10.7 negative limb (BrakePress table + brake-switch constants modulating regen), but the effect is **weak** at the median — LOW–MEDIUM confidence. Most descending segments are gentle regardless of brake, so this limb is less cleanly exercised than the VehSpd limb. Not needed for the verdict; the VehSpd result alone settles modern-vs-old.

### 4. Near-zero crossing step

The crossing-specific step pins near ~6–8 cts/update and is largely throttle-independent (see `coda-dlcm-decompile-notes.md` "Anti-lash ramp structure", 2026-07-08 clarification). This is the TrqLast limb dominating near zero (where the `min()` is smallest), consistent with the surface in §1.

### 5. Drive/regen asymmetry — a second, independent §10.7 fingerprint

§10.7's two limbs take *different* inputs: the positive (drive) limb includes VehSpd; the negative (regen) limb does not (it has BrakePress/BrkSw instead). So drive rate should be speed-dependent while regen rate should be speed-**independent**. That asymmetry holds cleanly (`Phase 8`, steepest descent per event):

- **Drive side** collapses ~50 → ~2 cts/update as speed rises (§1).
- **Regen side** stays flat at ~2–5 cts/update across every speed band in all three logs (frombonnydoon: −2, −3, −3, −2 across 100→1500+; the other logs likewise flat).

A symmetric old-style rate limiter would treat both directions alike. The observed drive-vs-regen **input asymmetry** matches §10.7's specific limb design and is hard to explain otherwise. (The regen limb's brake-pressure sub-dependence, `Phase 7`, is weak/noisy — the TrqLast limb appears to dominate regen in these logs and there are few hard-braking regen events — so the BrakePress sub-limb is consistent-with but not independently confirmed. Output: `artifacts/torque_limiter_regen_asymmetry.out.txt`.)

---

## Code corroboration (structure reliable; internal bindings not)

Anchors that ARE reliable (branch targets Ghidra followed; kernel signatures from clean bytes):

1. **Torque output datapath (Ghidra-flow-traced, prior work):** RTOS task loop samples `[R13+0x30]` → SRAM ring buffer `0x7F0F0880` → filter → `GBR+0x40` → `CE4C` packs `0x212` (and `CFCC` packs `0x211`). Confirmed twice.
2. **§10.6 smoothing filter = C630 (`0x8006C630`):** a genuine multi-stage IIR/FIR (MAC.L taps over delay+coefficient buffers, FP arithmetic), feeding both TX paths. Coefficients live in DRAM (`0xD9FFB830…`), initialized by boot code below `0x80040000` (not in our flash). Consistent with §10.6 "third-order filter".
3. **Six interpolation kernels in the pre-TX torque computation:** `bsr` to each of `E5CC, E606, E672, E686, E6CE, E71A` appears exactly once, reached via wrappers `DBC0, DBEE, DC00, DCAE, DCD8, DCF0, DD14, DD24, DD36, DD60, DD78, DD8E, DDB8, DDD0`. Each kernel is a fixed-point `mac.w @r0+,@r2+` evaluation (X-array in R0/coeff, input in R2) writing its result to `GBR+0x20` (with a `mov.b r0,@(0x8,GBR)` watchdog/status write). **Six table lookups** in the torque path is consistent with §10.7's four gradient LUTs plus neighbors (creep/pedal/speed-limit maps also use this kernel), and inconsistent with a single fixed-constant clamp.
4. **Path-select + ordering:** a `cmp/ge r0,r12` at `D1CE` selects a positive branch (`bsr DBEE` at D206) vs a negative branch (`bf D20A`), which merge and `bra D40A` into the C630 IIR. Structurally this is a two-limb selector ahead of the smoothing filter — the shape of the §10.7 → §10.6 pipeline. The Ghidra **decompiler** corroborates the selector at the C level: it renders D1CE/D206 as `if ((int)piVar10 <= unaff_r12) { ... FUN_8006dbee(...); }` with `piVar10 = *(int**)(iVar7+0x34)` (the `mov.l @(0x34,r14),r0` load). So the two-way branch is real; only the *operand identities* are unproven.

   Caveat from the same decompile: the enclosing function is **dominated by MAC.L sum-of-products** (`mac_lOp(acc, piVar27[k] * r2[k])` chains over coefficient/input arrays) — a filter/polynomial computation. This is why neither the disassembler nor the decompiler can cleanly separate the gradient-limiter `min()`/limb structure from the IIR taps: the prior notes' tidy "D1B8-D224 = limiter, D40A+ = IIR" split is an idealization; MAC accumulation appears on both sides of D224. The six 16-bit `mac.w` interpolation kernels (E5CC family) are distinguishable from the 32-bit `mac.l` filter taps, but mapping them 1:1 onto §10.7's four gradient LUTs is *not* established.

What is NOT reliably established (and why):

- **Which kernel is indexed by VehSpd vs TrqLast vs BrakePress.** The register setup lives in the pool-contaminated wrapper glue; the X-index pointer (R2) for each kernel cannot be traced to a signal with confidence.
- **The `D1CE` compare operands.** The prior notes read it as "R0 = gradient threshold (from E5CC), R12 = TrqLast" and even flipped R0/R12 once mid-investigation. Given the surrounding contamination, treat the *operand identities* as unproven; only the *existence* of a two-way selector is solid.
- **A code-level VehSpd→limiter link.** Prior Goal-5 work traced ESC wheel speed → `GBR+0x008` → the **MCM handler** (`0x8008xxxx`) filter — a *different task's* GBR than the `0x8006xxxx` torque-compute task (GBR is per-task). So that trace does not, by itself, place vehicle speed inside this gradient limiter. The behavioral result proves speed must reach it; the exact code path is unresolved.
- **The §10.7 CAL table addresses.** Per the 2026-07-02 "off-by-8 resolved" and R13 up-trace work, the gradient tables are reached through OS-managed runtime-RAM context pointers and are not statically resolvable in the PROG+CAL dump. This is a *table-location* problem, independent of the modern-vs-old question — and it is now clear the tables genuinely exist (§10.7 is real), they are just not addressable from the flash images alone.

---

## Reconciliation with prior investigation

- The prior pass's **working assumption** ("§10.7 applies; fall back to the old scheme if it won't match") can be **resolved in favor of §10.7** — but on behavioral, not static-code, grounds. The wall it hit ("strong V-curve shape evidence, zero discoverable code reference") was **not** a sign the firmware is the old scheme; it is genuinely modern §10.7 whose LUTs live in runtime RAM.
- The 2026-05-03 "§10.7 topology confirmed" claims (Relational Operator at D1CE, positive/negative limbs) should be **downgraded to "structure consistent, operands unverified"** — they were extracted by hand from disassembly that is materially pool-contaminated.
- The empirical V-curve documented earlier is now explained as the **TrqLast limb of a two-input min()**, with a co-equal **VehSpd limb** that dominates at speed — which the earlier per-frame characterization (done at low speed / launch) never isolated.

---

## Verdict and confidence

| Claim | Confidence | Basis |
|---|---|---|
| Torque rate limit is vehicle-speed-dependent with a `min(VehSpd, TrqLast)` structure | **HIGH** | 3 logs, clean 2D surface, demand-controlled |
| Drive/regen limb asymmetry (drive speed-dependent, regen speed-independent) matches §10.7's two-limb design | **HIGH** | Phase 8 across 3 logs |
| Firmware implements the modern §10.7 State Dependent Torque Gradient Limiter (not the old torque-only Zero Torque Rate Limiter) | **HIGH** | speed-dependence + limb asymmetry are the §10.7 signature; old scheme cannot produce either |
| C630 is the §10.6 3rd-order Torque Smoothing Filter | **MEDIUM-HIGH** | confirmed IIR structure; "3rd order" and torque-indexed time-constant not independently verified |
| Torque path has multi-LUT (≥6 interpolation) structure | **HIGH** | reliable branch-target count |
| Negative/regen limb is brake-modulated (§10.7 negative limb) | **LOW-MEDIUM** | weak but correctly-signed behavioral effect |
| Specific VehSpd/TrqLast/BrakePress → kernel bindings in code | **UNRESOLVED** | obfuscation + per-task GBR aliasing |

**Bottom line for the original question:** the code is written to the **modern** requirements for the torque gradient limiter, not the old scheme.

---

## Live-edit confirmation (2026-07-21): V-curve lash-floor 1->5 on the real car

This is a **live-edit behavioral confirmation** of Open item 2, for the TrqLast-limb
near-zero floor (not the VehSpd table). The positive V-curve floor cell (stock
`1`) at CAL flash `0xA0021532` (copy A, `0xA0021528` base, index 5) and its mirror
at `0xA0021B6E` (copy B, `0xA0021B64` base, index 5) were changed `1 -> 5` and
flashed to the **real vehicle's DLCM** via the MITM proxy (procedure/verification:
`projects/coda/README.md` DLCM section; `../../tools/flash_sim/README.md` roadmap step 6;
`artifacts/proxy_real_flash_20260721.log`). The full V-curve (both copies,
idx 0-9) is `[62, 35, 15, 10, 10, 1, 20, 40, 70, 70]` -- a rate-limit-vs-torque
shape with the minimum (idx5) at zero torque; raising idx5 raises the near-zero
rate cap (less lash softening).

A ~5-min post-flash drive (`CANLogs/CodaLogs/coda_20260721_215506_*`) was compared
against the pre-flash baseline drive cohort using the same 0x212 zero-crossing
characterization as `dlcm_antilash_characterize.py` (script:
`artifacts/lash_mod_pre_post_compare.py`, output `.out.txt`).

**Result -- the near-zero lash ramp changed in the predicted direction,
concentrated on off-the-line tip-in (regen->drive):**

Fast tip-in (|throttle rate| > 40 %/s), regen->drive:

| metric | PRE (n=21) | POST (n=31) |
|---|---|---|
| dwell in +/-40-count lash band | 400 ms (p10-p90 380-401) | 241 ms (239-260) |
| ramp_out (torque building out of the zone) | 722 cts/s (129-1580) | 1509 cts/s (775-1766) |

- Post-mod torque ramps out of the lash zone **~2x faster** and **dwells ~40 %
  less** time near zero. All-crossings agree (dwell 840->249 ms, ramp_out
  102->1443 cts/s).
- The distributions barely overlap (POST ramp_out p10 > PRE median), and the
  dwell values are **tightly quantized and shifted cleanly** (~390 -> ~245 ms) --
  the fingerprint of a discrete calibration/timer quantum moving, not driving
  noise. Overlays: `artifacts/lash_overlay_{offline_tipin_fast,offline_tipin_all,liftoff_fast}.png`.
- Lift-off (drive->regen) shows a weaker, noisier shift (fast-subset POST n=8;
  not leaned on).
- Matches the driver's subjective "a bit different off the line."

**Establishes (confidence MEDIUM-HIGH):** the CAL positive V-curve floor at
`0xA0021528` idx5 and its mirror at `0xA0021B64` idx5 behaviorally control the
near-zero lash ramp-out rate and dwell -- i.e. this is the TrqLast-limb near-zero
floor of the §10.7 limiter, confirmed by the definitive live-edit method.
**Caveats:** single short post drive; uncontrolled day/route/SOC/temperature
confounds (mitigated but not removed by the fast-throttle subset); 0x212 Nm scale
(0.244) unconfirmed, so magnitudes are raw counts, not Nm.

## Live-edit series 2 (2026-07-22): floor 20, filter ruled out, hidden constant clamp

Follow-on to the 1->5 edit: raised the floor further to **20** and did a second
test drive, then compared three cohorts (baseline floor 1 = `frombonnydoon`;
floor 5 = `coda_20260721_215506`; floor 20 = `coda_20260722_112358`), focused on
the two driver-reported maneuvers (launch from a stop; full 100<->0 throttle
swings). Driver report: floor 20 "doesn't feel much different." The data agrees,
and pins the mechanism.

### 1. The floor edit saturated by ~5 (floor 20 == floor 5 everywhere)

> **Alternative reading (2026-09-17, unconfirmed):** the per-update envelope
> shows FLOOR20 == FLOOR5 bin for bin *and* both matching the floor-5 table
> values exactly, which is also what you would see if the 07-22 flash never
> took effect in the copy the firmware reads. See "Zero-crossing clamp
> characterization (2026-09-17)" H4 below; to be settled by the UDS RAM read.

Fast tip-in (regen->drive), near-zero crossing:

| metric | baseline (floor 1) | floor 5 | floor 20 |
|---|---|---|---|
| dwell in +/-40-ct band | 400 ms | 241 ms | **241 ms** |
| ramp_out | 722 cts/s | 1509 cts/s | **1640 cts/s** |

1->5 is a big change; **5->20 is nothing** (dwell identical, ramp within noise).
The effective rate-limit envelope (`artifacts/map_rate_limit.py`, p90 cts/update
vs torque) is **bin-for-bin identical between floor 5 and floor 20** at every
torque level. Launch-from-stop is **unchanged across all three cohorts**
(~790-800 cts/s) — a launch builds from ~0 upward and never crosses *through* the
lash zone from regen, so the V-curve floor never engages there. Lift-off
(drive->regen) is also unchanged by the mod (it uses the *negative* descending
curve, which we did not touch). Scripts: `artifacts/lash_3cohort_maneuvers.py`,
`artifacts/lash_mod_pre_post_compare.py`; overlays `artifacts/lash_overlay_*.png`.

### 2. The through-zero response is rate-limited, NOT the §10.6 IIR

We tested whether the residual slowness is the §10.6 smoothing filter (a
speed-independent lag would explain both the saturation and "slow at all
speeds"). Two independent tests say no:

- **Shape fit** (`artifacts/lash_shape_fit.py`): over the post-crossing rise a
  straight line beats a 1st-order exponential in every cohort (R2_lin 0.84-0.90
  >= R2_exp; the exp fit's tau railed to the grid max, i.e. degenerated to
  linear).
- **Pole extraction** (`artifacts/filter_pole_match.py`): the per-update torque
  increments through the settling do **not** decay geometrically — the ratio
  `d[k+1]/d[k]` sits at **1.00** (constant slew = a hard rate clip; for floor 5/20
  the tail is dead-constant, baseline slightly grows). A low-pass IIR would show
  a pole ~0.9 with shrinking increments. There is no filter pole to match, so the
  candidate LUT `[116,117,137,165,204,254,315,388]` (0x80021448/0x80021C1C) cannot
  be validated as an IIR time constant under any clean fixed-point scale. **The
  curvature through zero is the V-curve rate *schedule* (slow at zero, faster
  away = a reverse-S), not filter rounding.** (§10.6 may still smooth the larger
  1-s pedal-to-max response; it is not what governs the near-zero crossing.)

### 3. The binding cap is a FIXED near-zero rate constant (~8 cts/update), not the VehSpd table

Rate-limit mapping (`artifacts/map_rate_limit.py`, Phases A-C):

- **vs torque (Phase A):** rate is lowest near zero and climbs away from it — the
  V-curve shape, working. Floor 5 == floor 20 in every bin.
- **vs speed at near-zero torque (Phase B, decisive):** the cap is **~7-9
  cts/update and flat across the whole speed range** (0-1300). A speed-scheduled
  `gradientLimiterPositive_VehSpd` (`0xA00215D4 [10,40,40,40,18,8,1,45]`,
  decreasing) would drop the cap toward ~1 at high speed; it does not. **So the
  cap is not the VehSpd table.**
- **where the crossings live (Phase C):** near-zero tip-ins happen mostly at low
  speed (floor 5/20 median ~120). There the VehSpd table reads ~40 and the
  floor-20 V-curve reads 20 — yet the observed cap is **~8, below both limbs of the
  documented `min(VehSpd, TrqLast)`**.

**Conclusion (HIGH confidence, behavioral):** a **fixed ~8 cts/update
(~400 cts/s) near-zero positive-rate clamp** binds the tip-in. It is *below* both
documented `min()` inputs at the operating point, **speed-independent** (matches
"slow at 0 and at 50 mph"), and **floor-independent** (why 5->20 did nothing).
This is a **third constraint** not present in the §10.7 positive-path
`min(VehSpd, TrqLast)` diagram — a scalar rate clamp (hypothesis: analogous to the
negative path's `BrkSwOn/BrkSwOff` constants, or a residual fixed near-zero rate
limiter). Finding and raising **that constant** is the real driveability lever;
the V-curve floor (saturated), the §10.6 filter (no pole), and the VehSpd table
(speed-flat) are all ruled out.

### 4. Pointer status (correction)

Neither the V-curve nor any candidate table is reached by a statically-resolvable
pointer. The §10.6 filter body loads pool pointers, but resolved against
`coda_dlcm_prog.bin` (`artifacts/filter_pool_pointer_scan.py`) they yield **zero**
CAL/CAL-map references — the region is instruction/data-interleaved (the
documented obfuscation), and the filter's coefficient buffers point into
boot-init DRAM (~`0xDD..`/`0xD9FF..`, below `0x80040000`, not in our image). Both
the V-curve and any rate-clamp constant must be found by CAL scan + confirmed by
live-edit, exactly as the V-curve was.

## Two CAL access patterns, and what that means for flash-edit semantics (2026-09-19)

> **THIS SECTION'S PREMISE IS RETIRED.** It rests on the V-curve having no code
> reference. That turned out to be a **tooling limit, not a firmware property**: the
> limiter reaches its tables through LUT descriptors stored in PROG
> (`{count, x_ptr, y_ptr}` at `0x80043F88`..`0x80043FB8`), and a pointer sitting in a data
> descriptor is invisible to a scan that reconstructs *code-built* addresses. The V-curve
> at `0xA0021528` is reached from `0x80043FB8`. See "THE RATE LIMITER, FOUND" below.
>
> The flash-edit-semantics distinction drawn here (direct scalar vs init-time RAM copy) is
> therefore **not established** and should not be relied on. What survives is only that
> `0x80021308` and `0x800213B8` *are* directly code-referenced. Retained for the refutation
> it records, which is still worth reading.

From the Ghidra session's `artifacts/cal_code_xref.py`, which reconstructs TriCore
`movh.a`+`lea` address pairs: **273 CAL addresses are referenced from 321 code sites.**
Against that map:

| CAL | directly referenced? |
|---|---|
| `0x80021526` V-curve positive base | no |
| `0x80021532` / `0x80021B6E` the edited cell | no |
| `0x800214C0` / `0x80021B90` negative curve | no |
| `0x80021BA0` / `0x800214AE` axes | no |
| **`0x80021308`** the `[100, 8, 8, 50, 20, 135...]` block | **yes** -- one site, `0x800706A2`, in `FUN_80070578` |
| **`0x800213B8`** VehSpd candidate | **yes** -- one site, `0x80074A44`, in `FUN_80074A06` |

Neighbours in the same bank are referenced (`0xA002148A` from `0x80075CD2`, `0xA00215C2`
from `0x80076196`), so this is not a scan gap.

### What this does NOT mean -- a wrong reading, refuted, recorded so it is not repeated

It was briefly proposed that "nothing reads the edited table" explains FLOOR5 == FLOOR20.
**That is refuted by data already in this file.** It is the *same cell* in all three
cohorts -- `0x80021532` was 1 (stock), then 5, then 20 -- and the envelope-minimum row
above reads:

```
BASELINE 1   |   FLOOR5 5   |   FLOOR20 5
```

Baseline reads the stock 1; FLOOR5 reads 5. So the firmware **is** reading that cell, and
the FLOOR5 edit demonstrably worked (dwell 400->241 ms, ramp_out 722->1509 cts/s). An
explanation that the cell is never read would predict BASELINE == FLOOR5, which is false.
It proves too much. FLOOR20 reading **5, not 20**, is H4 exactly -- the hypothesis already
on record -- and the xref result at best supplies a *mechanism* for H4, not a replacement
for it.

### What DOES survive, and it is more useful

The V-curve has no statically resolvable **direct** reference, yet behaviour proves it is
read. Therefore the access is **indirect** -- which confirms the 2026-07-02 runtime-RAM
finding from the code side rather than only behaviourally.

**A proposed "init-time RAM copy" mechanism for this was also refuted, same day.** It was
suggested that the V-curve is copied from CAL into RAM at startup, so a flash edit would
only take effect when that copy re-runs (i.e. would need a power cycle). The startup copy
table was then found and read: it sits at **`0x800933CC`**, 76 records of
`{dst, src, len}` on a 16-byte stride. 23 records are `.data` copies from PROG flash
(**600 bytes**); the other 53 have `src = 0` and are `.bss` zero-fills (14446 bytes).

- **No record sources from CAL**, and
- **none of the 76 copied blocks contains a single CAL pointer.**

So there is no init-time RAM copy of the V-curve, and no power-cycle prediction. That is
two mechanisms proposed and refuted for the same gap; the correct statement is simply that
**the V-curve access path is not yet traced.**

(The same table is independently useful: it confirms the SecurityAccess RAM layout to the
byte -- `RAM 0xD0004F80 <- flash 0x800948AC len 22` puts `secret[1]` at RAM `0xD0004F8C`
from flash `0x800948B8`, which is exactly where the verified constant `0xCAF77776` sits.
See `../../../ghidra/README.md` and `dlcm-security-access.md` s.1c.)

Two consequences:

1. **RAM-read target 2 is now the high-value one**, not target 1. "Does the runtime pointer
   resolve to CAL flash or a RAM copy" is the question that resolves H4 and explains what
   the 07-22 flash actually needed. (Note `0x23` cannot answer it -- see
   `dlcm-uds-live-access.md` section 2 -- so this needs another route.)
2. **If the ~8 clamp is at `0x80021308`, it is in the directly-referenced class**, so
   editing it should take effect without depending on the init copy. That makes it a
   cleaner live-edit experiment than the V-curve floor ever was, independently of whether
   it turns out to be the right constant.

---

## Live confirmation of the 8 cts/update clamp, and the 0x212 torque encoding (2026-09-19)

First confirmation from **live-polled data on a running car** rather than archived logs,
and the first on the reflashed FLOOR20 CAL in situ. Capture: Android logger chunk
`dcan_uds_capture_20260919/coda_20260919_190953_T2.log` (moved out of
`CANLogs/CodaLogs/` 2026-09-20 -- see that folder's README), 0x212 at its native 20 ms
cadence, time-aligned to a
simultaneous UDS DID poll (`artifacts/did_vs_broadcast_clamp_drive.csv`) by anchoring on
the poller's own `22 85 0C` requests visible in the same log.

### The clamp

Same methodology as `zero_crossing_clamp_characterize.py` -- near-zero band
`TrqLast -25..+16` **counts**, brake off, fast tip-ins `|throttle rate| >= 30 %/s`,
envelope = max delta per 5-count bin:

```
delta histogram, one 20 ms update:  1x61  2x14  3x2  4x1  5x4  6x31  7x27  8x62
                                    -- nothing above 8, anywhere in the band
envelope:  -25..-21: 8   -20..-16: 8   -15..-11: 8   -10..-6: 8
            -5..-1:  8    +0..+4:  8    +5..+9:  7   +10..+14: 6
```

A hard ceiling at exactly **8 counts/update** with zero excursions. This is the fourth
independent confirmation (BASELINE / FLOOR5 / FLOOR20 archived, now live) and answers the
question of whether running the reflashed calibration changes it: **it does not.**

### 0x212 DLCM_TorqueRequest torque field -- previously undocumented

`CODA-D-CAN.dbc` defines only `BrakeSW` for this message. The torque value is:

```
torque_raw = (B4 & 0x1F) << 8 | B5          13-bit
Nm         = (raw - 2000) / 4               exactly 0.25 Nm/count, zero at exactly 2000
```

> **Both lines above are CORRECTED from what this section originally said.** It gave a
> 12-bit `0x0F` mask and an empirical `Nm = 0.2405 * (raw - 2004.9)`. The static analysis
> below (`FUN_80074780`, and the publisher `FUN_80080C14`) gives the exact form: the mask
> is `0x1F` in both the publisher and the DID 8539 handler, and
> `raw = internal * 0.4 + 2000` with internal at 0.1 Nm/count.
>
> Why the empirical fit was off: it regressed `0x212` (the **request**) against DID `8515`
> (**delivered** torque). `0.2405 / 0.25 = 0.962`, i.e. it was measuring drivetrain loss,
> not the presentation scale. Checked against the drive: the exact scale puts peak request
> at **+299.75 Nm** against a measured delivered peak of **+300.70** (0.32% apart); the
> fitted scale gave +287.18 (4.50% apart). The 12-bit mask never truncated any observed
> sample -- peak raw was `0xC7F`, so bit 12 was never set -- but the formula was still wrong.

Empirically **r = +0.9925** against DID `8515`. 6 bytes, 20 ms, mirrored on both logged
channels.

**There are NOT two torque encodings on this bus.** An earlier reading here claimed there
were. It is **one quantity with a x0.4 presentation scale**: `0x1C0` carries it at
0.1 Nm/count, `0x212` at 0.25 Nm/count, both derived from the same internal 0.1 Nm/count
value (clamped to [-5000, +15475]).

> **Correction to a figure that was never in these notes.** A 2026-09-19 analysis briefly
> claimed the clamp "did not bind", reporting ~127 Nm/s median against an asserted ~40 Nm/s
> clamp. That was wrong five times over: it measured `0x1C0` (delivered) instead of `0x212`
> (request); converted counts to Nm using `0x1C0`'s 0.1 Nm/ct instead of `0x212`'s 0.2405;
> used a band in Nm where the published band is in counts (20x too wide); applied no
> throttle-rate or brake conditioning; and used percentiles of all deltas instead of the
> envelope. **These notes never stated a Nm figure** -- they correctly kept the clamp in
> counts (`~8 cts/update`, `~400 cts/s`). In proper units the clamp is
> `8 * 0.2405 / 0.020` = **~96 Nm/s**.

### SUPERSEDED -- the request DID is 8539, not 8525

This section originally proposed **`8525`** as the limiter output, from a slope match
(4.1865 vs 4.158 counts/Nm) and a 2000 at-rest value. **That was wrong**, and it is now
settled statically rather than by correlation -- see "DID 8539 IS the 0x212 torque request"
below.

`8539`'s handler reads the **same RAM address** as the `0x212` publisher and applies the
**same `(v>>8) & 0x1F` / `v & 0xFF` split**. Same variable, same encoding, no drive needed.
`8525` reads a *different* variable through a getter, which is why it correlated well
(r = 0.998 vs torque) without being the request -- a good reminder that a strong
correlation identifies a *related* quantity, not necessarily *the* quantity.

Caution for whoever follows: the specific mirror RAM addresses for `850C`/`850D`/`850E`/
`8537`/`8539` shifted between successive analyses as the descriptor layout was corrected.
Re-derive them from the handlers rather than trusting any address quoted in passing.

### Ruled out: 850C / 850D are not the live limiter bounds

Over a full drive with real crossings in both directions, `850C` held `+1600.0 Nm` in
**1316 of 1317** samples and `850D` held `-1600.0 Nm` in **1314 of 1314**. Static
configuration, despite matching the Omitec panel's `high_bound`/`low_bound` rows by
position. The two single-sample excursions were poller artifacts -- each carried the
*other* DID's constant. `850E` is likewise not `TorqueDesired`: its divergence from `8515`
alternates sign between consecutive samples, which is sampling skew during a slew, not a
command-versus-delivery gap.

---

## Zero-crossing clamp characterization (2026-09-17) -- unconfirmed hypotheses in support of the UDS RAM read

**Status: every interpretation in this section is an UNCONFIRMED HYPOTHESIS.**
This analysis exists to sharpen what the Route A UDS ReadMemoryByAddress
session (`projects/coda/notes/plans/dlcm_ram_read_mapping.md`) should look for.
Behavioral data alone cannot confirm any of it; the RAM read can. Script:
`artifacts/zero_crossing_clamp_characterize.py`; output (all three cohorts, run
headless on `the Linux box`): `artifacts/zero_crossing_clamp_characterize.3cohort.out.txt`.

### What was measured

Per 0x212 update (one frame = one update, see below), the pair (TrqLast, delta)
through every torque zero crossing, in three cohorts: BASELINE (stock CAL, four
`projects/coda/logs/` drives), FLOOR5 (`coda_20260721_215506_*`), FLOOR20
(`coda_20260722_112358_*`). Conditioning signals: 0x210 throttle rate, 0x208
speed, 0x212 B2.bit0 brake switch. Envelope = max positive delta per 5-ct
TrqLast bin (a hard rate clip shows up as the max, not the mean).

**Cadence correction.** 0x212 arrives every 20 ms and the torque value changes
on any frame regardless of the B4[7:4] mux nibble (value changes are split
evenly across all four nibble values in every log). The earlier statement that
each value is repeated in two adjacent sub-frames is not what the data shows;
one frame is one 20 ms update.

### Measured facts (these are data, not interpretation)

Fast regen->drive tip-ins (|throttle rate| >= 30 %/s), brake off:

| | BASELINE | FLOOR5 | FLOOR20 |
|---|---|---|---|
| crossings, all directions | 441 | 93 | 122 |
| fast tip-ins, step at crossing == 8 (else 7) | 24 of 29 | 26 of 30 | 26 of 32 |
| run of consecutive 8s spans TrqLast | -25 to +8 | -25 to +16 | -26 to +16 |
| run length | 4-5 updates | 5-6 | 5-6 |
| time in the 8-run vs cohort V-curve alone over the same span | 0 ms (p90 20) | 20 ms | 60 ms |
| envelope minimum after the run | 1 at +30..+35 | 5 at +25..+35 | 5 at +25..+35 |

- The crossing step of 8 is flat across speed (FLOOR20 900-1300 bin: n=22, all
  7 or 8), across throttle rate 30-250 %/s, and across the three CALs.
- The FLOOR5 and FLOOR20 positive envelopes are **identical bin for bin** from
  -40 to +60 (8 flat from -25 to +10, then 7, 6, 6, 5, 5, 6, 8, 9, 10, 11).
- Lift-off (drive->regen): step through zero is -3/-4, then a dead-flat **-8**
  from TrqLast -34 (p10 -37, p90 -32) downward for 16+ updates in all 49
  baseline fast lift-offs, brake off. With brake ON the deep-regen max is 12,
  but that is 5-8 samples per bin (probably one event).
- Baseline positive envelope, TrqLast +5 to +100: 7, 6, 5, 4, 3, 2, 1 down to
  +33, then 4, 5, 7, 9, 10, 11, 13, 15, 16, 17, 18, 20 up to +92.

### Hypotheses (unconfirmed) and their backing

**H1 -- the V-curve axis is in 0.1 Nm, not torque counts.** Fitting the
baseline max envelope over TrqLast [-35, +100] to `min(C, Vcurve(TrqLast * s))`
gives rms 1.4 cts at s = 2.2-2.44 versus rms 8.2 at s = 1. The observed
minimum sits at TrqLast +33; the CAL knot is at axis 80; 0.244 Nm/ct x 10 =
2.44, and 80 / 2.44 = 32.8. The rise from the minimum matches the 1 -> 20 knot
pair (axis 80 -> 200, i.e. +33 -> +82 cts) at 0.24 cts/update per ct. *Cannot be
confirmed behaviorally*; the RAM read can show whether TrqLast is scaled before
indexing.

**H2 -- the 8 is a scalar cap that only shows where the table exceeds 8 near
zero, and it costs little.** In all three cohorts the max delta is exactly 8
from about -25 to +8..+16, where the (scaled-axis) table reads 10. Outside that
band the envelope follows the table. Near-zero-window fit (TrqLast [-35, +35])
picks C = 8 with rms 0.94 (baseline) / 0.96 (floor 5). Measured time cost of
the cap versus the cohort's own table over the 8-run is 0-60 ms per tip-in;
the 400 ms baseline dwell in the +/-40 band is dominated by the table's own
taper to 1 at +33, not by the cap. *Candidate location*: the two adjacent 8s at
`0x80021308` `[100, 8, 8, 50, 20, 135, ...]` (see decompile notes 2026-09-13 s.3).

**H3 -- the same 8 appears in the negative direction.** The lift-off envelope is
-8 flat from -34 downward where the negative table (on the H1 axis, knot -80 ->
-33 cts) reads -10. Both tables say 10 at the zero-adjacent knots; both
directions show 8. A single scalar applied to |rate| is the simplest reading;
two constants (the two 8s at `0x80021308`, or the negative path's BrkSwOff
constant) is the alternative. The brake-on value of 12 in deep regen, if it
survives more events, would be the BrkSwOn constant.

**H4 -- the on-car CAL is behaving as the floor-5 CAL, not floor-20.** This is
the hypothesis the RAM read should test first. FLOOR20 == FLOOR5 bin for bin,
and both match the floor-5 table exactly under H1: a 10 -> 5 taper from 0 to
+33 (predicted 8.5 at +10, 7 at +20, 5.5 at +30; observed 7, 6, 5), a minimum
of 5 (the 07-21 flashed value), then 5 -> 20 toward +82 (predicted 12 at +57;
observed 11). A live idx5 = 20 with idx2..4 = 20 would give a flat 20 from -33
to +82; nothing in the 07-22 data looks like that, and the deep-negative bins
(-40..-30: max 11-13 in both cohorts) also match 10-15, not 20. The earlier
"floor edit saturated" reading (s.1 above) explained FLOOR5 == FLOOR20 by the
8 cap, but the cap only binds below +16; above that the car is following a
table whose minimum is 5. Either the 07-22 flash did not change the copy the
firmware reads, or something restored it. **Check with the RAM read: the live
value at V-curve idx5 (CAL `0x80021532` / `0x80021B6E`) should be 20 if the
07-22 flash took effect; 5 says it did not.** The 07-22 flash session
(`coda_20260722_102259_*`, Android-only) can also be re-examined on
`the Linux box`.

### What the RAM read should therefore target (inputs to the plan)

1. Live contents of the positive V-curve Y at both CAL copies, idx2..5
   (expected 20/20/20/20 per the 07-22 flash; H4 predicts 10/10/10/5 in the
   copy actually read).
2. Whether the runtime pointer for the V-curve resolves to CAL flash or a RAM
   copy (decides whether a flash edit needs a power cycle, and whether the
   07-22 edit could have been overwritten).
3. The `0x80021308` block, to see whether the torque-path module references it
   (H2/H3 candidate for the 8 constants).
4. Any scaling applied to TrqLast before table indexing (H1).

## The FLOOR20 cohort is a direct measurement of a second limiter (2026-09-19)

> **RETRACTED 2026-09-19 (same day), by measurement.** There is no second limiter. The
> "X" envelope is the V-curve's own y-values under the correct scale factor, which was
> unknown when this section was written and is now measured: 1 internal count = 0.8 raw
> counts per observed 0x212 sample. See "The scale, the update rate, and the retraction
> of X" below. The section is kept because its *reasoning* was sound given the scale
> ambiguity it explicitly flagged, and because the three-cohort measurements in it are
> still good data.

**This is the most useful result to come out of the three-cohort data, and it had been
filed as a null result.**

Assume the 07-22 flash landed correctly (see the verification section below: there is no
positive evidence it failed, and the tooling is proven). Then read the three cohorts as
`min(V-curve, X)` for some second limiter X:

| region | baseline V=1 | FLOOR5 V=5 | FLOOR20 V=20 | observed |
|---|---|---|---|---|
| near zero (V reads 10) | `min(10, X)` | `min(10, X)` | `min(20, X)` | **8, 8, 8** |
| +25..+35 | `min(1, X)` | `min(5, X)` | `min(20, X)` | **1, 5, 5** |

Every cell is consistent with **X = 8 near zero and X = 5 at +25..+35**:

- baseline reads **1** because V=1 sits *below* X and binds;
- FLOOR5 reads **5** because V=5 is approximately equal to X;
- FLOOR20 reads **5** because V=20 is out of the way and the car is reading **X directly**.

### What this forces

1. **X is a schedule, not a scalar.** Section 3 above ruled out the "floor edit saturated"
   reading on the grounds that a scalar 8 cap "only binds below +16; above that the car is
   following a table whose minimum is 5". That argument dissolves if X is itself a table --
   the "table whose minimum is 5" **is** X.
2. **The V-curve stopped binding the moment idx5 rose above ~5**, so it is spent as a lever.
   Further V-curve edits cannot change anything, which is exactly what 5 -> 20 showed.
3. **The FLOOR20 envelope is X's own shape**, measured unobstructed:

   ```
   X ~= 8 flat from -25 to +10, then 7, 6, 6, 5, 5, 6, 8, 9, 10, 11
   ```

4. It reconciles with the live measurement of the same day: a hard ceiling of exactly 8
   near zero on the FLOOR20 CAL is **X's near-zero plateau**, not a scalar clamp.

Status: this is an **inference from three cohorts plus the assumption that the 07-22 flash
landed**, not a measurement of X in code or CAL. It is falsified if the flash did not land.

### Searching CAL for X by shape -- NEGATIVE

`artifacts/x_limiter_shape_scan.py` scans the active CAL region (`0x0000-0x4800`) for a
table matching the shape above, as u8 / u16 LE / u16 BE / i16 LE, widths 7-16, requiring a
descend-then-ascend profile with an interior minimum of 4-6 and a leading value near 8.

**No match.** The only hits were three overlapping windows of a single structure at
`0x800218E0`, which is an 8x8 `max(i, j)` arbitration matrix (rows 0/1 special-cased to
20), not a rate limiter; the nearby referenced byte `0xA0021894` is an enable flag read by
`FUN_8007809C`, a debounce counter.

So X is not a CAL table carrying those literal values. Either it is scaled differently, is
not monotone, or is not tabulated at all. Loosening the scan (scale factors, non-monotone,
wider widths) is cheap and has not been done.

---

## What was actually flashed on 2026-07-21, byte-exact (2026-09-19)

The FLOOR5 flash is recoverable **from the Android CAN capture**, independently of the
proxy's own log, because the proxy patches the stream and the logger records the wire.
`artifacts/reconstruct_flashed_image.py` reassembles the ISO-TP stream, takes the address
and size from RequestDownload (`0x34`) and concatenates TransferData (`0x36`).

From `../../../../CANLogs/CodaLogs/coda_20260721_202537_T*.log` (286,207 `0x7E0` frames):

```
download 0x80040000  declared 0x1BFE00  reassembled 1,834,496 bytes
download 0xA0020000  declared 0x1C000   reassembled   114,688 bytes

PROG: 0 bytes differ from coda_dlcm_prog.bin
CAL:  2 bytes differ
   CAL 0x1532 (flash 0xA0021532): 01 -> 05
   CAL 0x1B6E (flash 0xA0021B6E): 01 -> 05
```

Exactly the `vcurve-lash-5` preset, confirmed on the wire. Three things follow:

- **A "flash" rewrites both images.** Stock PROG was re-flashed unchanged (1.83 MB, zero
  differences); only CAL carried the edit.
- **FLOOR5 was two bytes; `vcurve-floor-20` is eight** (idx2..idx5 on both copies). They are
  not the same edit with a different value.
- The resulting image is saved as `artifacts/cal_as_flashed_20260721_floor5.bin`
  (md5 `97e4046042f7f97bc265847c426dfeaf`; stock CAL is `7db9d7c24918c79814843e7eb812f570`).
  **This, not `coda_dlcm_cal.bin`, is the CAL the car was running from 07-21 onward.**

### There is no FLOOR20 flash capture -- do not re-hunt it

Searched the whole `CodaLogs` corpus **by content** (diagnostic-frame count per session),
not by filename or date. Only three sessions carry flash-scale traffic:

| session | `0x7E0` frames | what |
|---|---|---|
| `coda_20260426_151050` | 286,281 | original extraction (flash6) |
| `coda_20260721_202537` | 286,207 | **FLOOR5** -- complete, both images |
| `coda_20260722_102259` | 2,286 | 07-22 -- ~1% of a flash |

The 07-22 session yields 60 TransferData blocks / ~15 KB, in five disjoint runs of block
counters, of which **58 blocks are pure zero padding** and the two with content match PROG.
It cannot say what was written. No proxy run-log was saved for the FLOOR20 run either --
only a sim validation from 00:03 that morning (`artifacts/floor20_proxy.log`, header
`Virtual transport (sim-to-sim, no hardware)`), in which all eight patches apply cleanly.

So **both records that would settle H4 are missing**, and no floor20-specific failure mode
is visible in `dlcm_flash_proxy.py`. For the next attempt, two cheap changes make this
unrepeatable: redirect the proxy's stdout to a file in `artifacts/` (it logs via
`basicConfig` to stdout only), and keep the Android logger running for the whole session.
Either alone would have answered this.

---

## The indirection wall: why static write-tracing keeps failing (2026-09-19)

Three independent attempts to trace a producer statically all stopped the same way:

| trace attempted | what stopped it |
|---|---|
| who writes the CAN `0x212` torque signal | signals go through a typed pool (bit/u8/u16/u32 arrays at `a0-0x3992` / `-0x3a86` / `-0x3b28` / `-0x3bf0`) written by a generic setter; only 5 call sites to it resolve statically |
| how the V-curve CAL table is read | no direct CAL reference, and the startup copy table sources nothing from CAL |
| who writes the torque mirror DID 8525 reads (`0xD0007FA8`) | 26 references across 100k instructions, **every one a `lea`** -- a generated accessor layer in `0x800800xx-0x80080Axx`; `FUN_8008008C` takes the addresses of five sub-blocks and registers them elsewhere |

**This firmware routes inter-module data through registered pointer tables.** "Who writes
X" is therefore not answerable by scanning for stores to X's address -- which is why three
unrelated traces failed identically rather than for three different reasons. This is the
code-side view of the same thing the 2026-07-02 runtime-RAM finding saw behaviourally.

**RESOLVED the same day — see the next section.** The indirection is not opaque: it is a
config struct reached by following a single store, and once you have the struct the message
tables, signal tables, publisher and source variable fall out in order. The pessimism above
about needing the live RAM read for this is withdrawn.

---

## The CAN 0x212 transmit chain, fully resolved (2026-09-19)

Traced end to end under the TriCore decode. Every link is a table or a single store, so
this is reproducible rather than inferred.

```
master CAN config              0x80041DA4
  +0x00 -> RX message table    0x8004162C   26 x 52B   CAN ids at +0x00
  +0x04 -> TX message table    0x80041B74   14 x 40B   id at +0x00
  +0x10 =  26   (RX count)
  +0x14 -> RX signal table     0x80041490   27 x  8B
  +0x18 -> TX signal table     0x80041568        x 12B
  +0x1C =  27   (RX signal count);  +0x1E = TX signal count
```

Unpacked into RAM by **`FUN_80067B2C`** (`config+0x14 -> a0-0x3d10`, `config+0x18 ->
a0-0x3d0c`, etc). Accessors: **`FUN_800686D8`** for RX (`id & 0x8000` set, 8-byte records)
and **`FUN_800685C4`** for TX (`id & 0x8000` clear, 12-byte records).

**The 14 transmitted messages** (TX table, `0x80041B74`, stride 40): `0x591 0x592 0x595
0x052 0x278 0x315 0x418 0x210 0x212 0x308 0x312 0x207 0x204 0x08C`. Record fields: id at
`+0x00`, period at `+0x06` in 5 ms ticks (`0x212` = 4 = 20 ms, `0x08C` = 200 = 1 s),
serialiser at `+0x10`, a second handler at `+0x1C`.

**`0x212` is TX record 8**, and TX signal record 8 (`0x800415C8`) reads
`08 01 30 05 9E 00 01 10 ...` — 6 bytes (`0x30` bits), type 5 (byte array), **pool index
`0x9E`**, plus a status bit at bit-pool index `0x10`.

**Publisher: `FUN_80080C14`.** It assembles all TX payloads in staging buffers and
publishes each with `FUN_800685C4(&buf, signal_id)`. `0x212`'s buffer is `a0-0xF9E` =
`0xD0008062`; the publish call is at `0x80080DC6` with `d4 = 8`.

### The torque field, and what it actually is

`FUN_80074780` writes the value the publisher reads:

```c
v = *(s16 *)0xD0006A5A;                       // internal torque
v = (v < 0x3C74) ? max(v, -5000) : 0x3C73;    // clamp [-5000, +15475]
*(s16 *)0xD00069D2 = ((v * 0x3333) >> 15) + 2000;
```

`0x3333 / 0x8000 = 0.40000`, so **0x212 raw = internal * 0.4 + 2000**.

Three corrections follow, all read directly off the instruction stream:

1. **The 0x212 torque field is 13-bit, not 12-bit.** Both the publisher
   (`0x80080D32: and d1,d1,#0x1f`) and the DID handler mask with `0x1F`. The recorded
   layout `(B4 & 0x0F) << 8 | B5` should be **`(B4 & 0x1F) << 8 | B5`**. Torque never
   reaches 12 bits in practice, which is why it was never visible.
2. **There are not two torque encodings on the bus.** The internal value is in
   0.1 Nm/count — the same scale as `0x1C0` MCM_CoreTelemetry Torque — and `0x212`
   is that value times 0.4. Hence 0.2405 Nm/count on `0x212` against 0.1 on `0x1C0`:
   one quantity, two presentation scales.
3. **`FUN_80074780` is telemetry, not the limiter.** It applies the same
   `* 0.4 + 2000` transform to several internal values, writing `0xD00069D2`,
   `0xD00069D4` and `0xD00069D6` — the block the `85xx` DIDs read. That block is a
   **mirror**, which is why `850C`/`850D`/`850E` looked like static configuration.

### DID 8539 IS the 0x212 torque request (statically proven)

`8539`'s handler `0x8007A346` is twelve bytes:

```
movh.a a15,#0xd000 ; lea a15,[a15]0x69d2      ; 0xD00069D2 -- the same variable
ld.hu  d15,[a15]0x0 ; sha d15,#-0x8 ; and d15,#0x1f ; st.b [a2],d15     ; byte 0
ld.hu  d15,[a15]0x0 ;                           st.b [a2]#0x1,d15       ; byte 1
```

Same source variable and same 13-bit split as the `0x212` publisher. **No drive is needed
to confirm this.** It supersedes the earlier hypothesis that `8525` is the torque request
(`8525` reads `0xD0007FAC` through a getter, a different variable), and it explains why
`850E` was correctly dismissed — `850E` reads `0xD00069D0`, a neighbour in the same mirror
block.

Corrected `85xx` map (record layout: DID at `+0x0C`, handler A at `+0x04`):

| DID | handler | reads |
|---|---|---|
| `850C` | `0x8007A0B8` | `0xD00069CC` |
| `850D` | `0x8007A0D6` | `0xD00069CE` |
| `850E` | `0x8007A0F4` | `0xD00069D0` |
| `8515` | `0x8007A16E` | via getter `0x800806FE` -> `0xD0007FE0`, LE, 16-bit |
| `8525` | `0x8007A232` | via getter `0x80080572` -> `0xD0007FAC`, BE, 13-bit |
| `8537` | `0x8007A306` | `0xD00069D8` |
| **`8539`** | **`0x8007A346`** | **`0xD00069D2` = the 0x212 torque request** |

### Next target

The limiter is upstream of all of this and writes **`0xD0006A5A`** (`a0-0x25A6`), in
0.1 Nm/count. That is now a single concrete address, and the method that resolved this
chain — find the one store, read the function — applies directly.

---

## THE RATE LIMITER, FOUND: `FUN_80075DFA` (2026-09-19)

The §10.7 gradient limiter is **`FUN_80075DFA`**, called from `FUN_80075CF8`:

```c
FUN_80075CF8:
    *(s16*)(a0-0x25b0) = *(s16*)0xD0006AEE + *(s16*)0xD000513A;   // request
    FUN_80075DFA();                     // <-- RATE LIMITER
    FUN_80075F56();                     // <-- 3-stage IIR (disabled, see below)
    v = *(s16*)(a0-0x25ae);             // result
    *(s16*)(a0-0x25a6) = v;             // = 0xD0006A5A, feeds CAN 0x212 and DID 8539
    *(s16*)(a0-0x25b2) = clamp(v, *(s16*)0xD0006AA0, *(s16*)0xD0006AA2);
```

`FUN_80075DFA` contains the documented two-limb structure verbatim --
`iVar5 = min(step_limit, iVar7)` -- then steps `TrqLast` by that amount and clamps.

### How CAL tables are actually reached -- and why the xref missed them

**The limiter's tables are reached through LUT descriptors in PROG whose fields are CAL
data pointers.** Format `{count, x_ptr, y_ptr}`, 12-byte stride:

| descriptor | n | x axis | y values | role |
|---|---|---|---|---|
| `0x80043F88` | 7 | `0xA002148C` | `0xA002149C` | IIR gain `k` |
| `0x80043F94` | 10 | `0xA00214AC` | `0xA00214C0` | step-limit source |
| `0x80043FA0` | 10 | `0xA00214D4` | `0xA00214E8` | negative TrqLast limb (`iVar7`) |
| `0x80043FAC` | 5 | `0xA00214FC` | `0xA0021508` | indexed by `0xD0006A42` |
| **`0x80043FB8`** | 10 | **`0xA0021514`** | **`0xA0021528`** | **TrqLast limb = the V-curve** |

```
V-curve  x: [-700, -600, -80, -70,  0,  80, 200, 400, 800, 3000]   (0.1 Nm units)
         y: [  62,   35,  15,  10, 10,   1,  20,  40,  70,   70]
neg TrqLast y: [ -10,  -10,  -7,  -4,-15, -15, -20, -40,-100, -100]
step src   y: [  -4,   -4, -15, -15,-20, -25, -30, -40, -40,  -40]
```

> **This retires the "the V-curve has no code reference" result entirely, and the
> limitation is in my tooling, not the firmware.** `artifacts/cal_code_xref.py`
> reconstructs `movh.a`+`lea` pairs, i.e. **addresses built by code**. A CAL address stored
> as a *pointer inside a PROG descriptor* is invisible to it. That is an entire class of
> CAL reference the scan cannot see, and the gradient tables are all in that class.
> Anyone using that xref must treat "not referenced" as "not referenced *by code-built
> address*", never as "not read".

**Address correction:** this file recorded the V-curve at `0x80021526`. It is at
**`0x80021528`**, with its x-axis at `0x80021514`. The edited cell was still correct:
`0xA0021528 + 5*2 = 0xA0021532`, exactly what FLOOR5/FLOOR20 patched.

### The limiter's CAL scalars, `0xA002153C`-`0xA0021545`

All directly referenced from `FUN_80075DFA` / `FUN_80075F56`, so all in the
immediately-effective class:

| address | value | role (from the code) |
|---|---|---|
| `0xA002153C` | 3000 | upper clamp on the stepped output |
| `0xA002153E` / `0xA0021540` | -100 each | step-limit fallbacks, selected by `0xD0006831` |
| `0xA0021542` | -3000 | lower clamp |
| `0xA0021544` | **1** | rate limiting **ENABLED** |
| `0xA0021545` | **0** | three-stage IIR filter **DISABLED** |

### The old §10.6 filter is present in code but switched off by calibration

`FUN_80075F56` is a genuine **three-stage cascaded first-order IIR**:

```c
s1 += (in - (s1 >> 14)) * k;
s2 += (((s1<<2)>>16) - (s2 >> 14)) * k;
s3 += (((s2<<2)>>16) - (s3 >> 14)) * k;
out = (s3<<2)>>16;
```

gated entirely on `DAT_a0021545`, which is **0** in this calibration -- when it is 0 the
function passes the input straight through unfiltered.

This **independently confirms, from the code, the behavioural finding in section 2 above**
("the through-zero response is rate-limited, NOT the §10.6 IIR" / "no pole"). The filter
was not absent from the firmware; it is compiled in and disabled by a one-byte calibration
flag. Two opposite methods, same answer.

It also means `0xA0021545` is a **live one-byte experiment**: setting it to 1 would switch
the three-stage filter on. That is a behaviour change nobody has tried, and it is in the
directly-referenced (immediately-effective) class.

### The two limbs, located

`FUN_80075DFA` branches on direction. The **increasing-torque** path (which is what the
fast regen->drive tip-in measurements exercise) is:

```c
else if (sVar4 <= _DAT_a002153c) {          // TrqLast below the upper clamp
    iVar5 = min(iVar5, iVar6);              // <<< the documented two-limb min()
    sVar3 = sVar4 + iVar5;                  // step TrqLast by that amount
    if (sVar3 < _DAT_a0021542) sVar3 = _DAT_a0021542;
```

| limb | descriptor | table | values |
|---|---|---|---|
| `iVar6` | `0x80043FB8` indexed by TrqLast | `0xA0021528` | `[62,35,15,10,10,1,20,40,70,70]` = **the V-curve** |
| `iVar5` | `0x80043FAC` indexed by `0xD0006A42` | `0xA0021508` | **`[20, 20, 1000, 1000, 1000]`** |

The decreasing-torque path uses the other pair (`*(a0-0x25b6)` from `0x80043F94`, and
`iVar7` from `0x80043FA0`).

**The speed limb caps the low end at 20.** This is a hard constraint on any future edit and
it holds regardless of how H4 resolves: **raising the V-curve above 20 does nothing unless
`0xA0021508[0..1]` is raised with it.** The previous "min(VehSpd, TrqLast)" description was
right; both tables are now bound to addresses.

### H4, argued from the code -- both branches

Near zero the stock/FLOOR5 V-curve reads **10** (idx3/idx4) and the speed limb reads **20**,
so `min = 10`. FLOOR20 set idx2..idx5 to **20**, which makes `min = 20` -- a doubling of the
near-zero rate limit. The measured near-zero plateau is **8 in all three cohorts**
(baseline 8, FLOOR5 8, FLOOR20 8), unchanged. That comparison is a ratio, so it holds
whatever the units and whatever the limiter's update rate.

**Branch A -- the flash did not take (H4).** Every measurement follows with no new
entities: near zero all three cohorts read V=10 -> identical plateaus; at +25..+35 baseline
reads V=1 -> 1, FLOOR5 reads V=5 -> 5, and FLOOR20 (still the FLOOR5 CAL) reads 5. The
FLOOR5 edit landing and the FLOOR20 edit not landing is the whole explanation.

**Branch B -- the flash did take.** Then the 8 cannot come from this limiter, since both
limbs are >= 20 under FLOOR20, and a third limiter "X" must bind below both, with
X = 8 near zero, 5 at +25..+35, ~11 at +60, and X above the V-curve minimum in baseline
and FLOOR5 so those edits still show through. Internally consistent, **not ruled out**.

The argument against Branch B is parsimony plus one coincidence: X would have to equal
**exactly 5** at +25..+35, the very value FLOOR5 wrote into idx5 two days earlier. Under
Branch A that 5 is simply the FLOOR5 cell being read. **This is a judgement about
plausibility, not a measurement**, and it is the same style of reasoning that produced two
refuted mechanisms earlier in this session -- so it is recorded as a lean, not a finding.

**Unresolved in both branches:** the absolute scale. The table says 10 near zero and the
measurement says 8. A x0.8 factor fits that (and 1 -> 0.8 ~= 1) but then FLOOR5's idx5 = 5
should read 4 and it reads 5. Knot interpolation and the max-per-5-count binning can absorb
a count either way, so the scale is still not closed.

### The full LUT descriptor block, and a negative on X

The descriptor block runs **`0x80043F88` - `0x8004403C`, 15 descriptors**, all resolved
against the CAL image by `artifacts/lut_descriptor_map.py` (+ `.out.txt`). Consumers, from
code-built references:

| descriptor | n | y-table | consumer | role |
|---|---|---|---|---|
| `0x80043F88` | 7 | `0xA002149C` | `FUN_80075F56` | IIR gain `k` (filter disabled) |
| `0x80043F94` | 10 | `0xA00214C0` | `FUN_80075DFA` | step-limit source, decreasing |
| `0x80043FA0` | 10 | `0xA00214E8` | `FUN_80075DFA` | negative TrqLast limb (`gradientLimiterNegative_TrqLast`) |
| `0x80043FAC` | 5 | `0xA0021508` | `FUN_80075DFA` | **speed limb, increasing** (`gradientLimiterPositive_VehSpd`) `[20,20,1000,1000,1000]` |
| `0x80043FB8` | 10 | `0xA0021528` | `FUN_80075DFA` | **the V-curve** |
| `0x80043FC4` | 5 | `0xA0021554` | `FUN_800763D2` | creep/assist |
| `0x80043FD0` | 5 | `0xA002156C` | `FUN_800763D2` | creep/assist |
| `0x80043FDC` | 6 | `0xA0021584` | `FUN_80076302` | creep/assist |
| `0x80043FE8` | 8 | `0xA00215A0` | `FUN_80076302` | creep/assist (all zeros) |
| `0x80043FF4` | 7 | `0xA00215D4` | not yet found | `[10,40,40,40,18,8,1]` |
| `0x80044000` | 11 | `0xA0021610` | not yet found | |
| `0x8004400C` | 11 | `0xA0021640` | `FUN_80076EC6` | |
| `0x80044018` | 8 | `0xA0021668` | `FUN_80076DC2` | |
| `0x80044024` | 15 | `0xA0021698` | `FUN_800774AA` | |
| `0x80044030` | 8 | `0xA00216C8` | `FUN_80076DC2` | |

**Correction to an earlier candidate:** this file recorded a VehSpd candidate as
`0x800215D6 [40,40,40,18,8,1]`. It is descriptor `0x80043FF4`, y-table at `0xA00215D4`
with **7** entries `[10,40,40,40,18,8,1]` on axis `[0,100,400,1500,4000,6000,16000]`. The
earlier reading started one entry late. Its consumer is not yet identified.

**Negative on X:** none of the 15 y-tables has the shape Branch B requires (a plateau
near 8 with an interior minimum near 5, rising after). Combined with the upstream trace --
input A (`0xD0006AEE`) is a pure clamp between RAM bounds `0xD0006AB8`/`0xD0006ABA`, with
no rate limiting -- **Branch B has no candidate anywhere in the torque path's calibration
or in the limiter's immediate input.** That is evidence, not proof: the shape test is
narrow, X could be a scalar or expressed in other units, and the creep/assist subsystem
feeding input B (`0xD000513A`) has only been read at its entry points.

### Tooling gap found while doing this: 16-bit calls were being missed

TriCore has a **16-bit `call` (op `0x5C`)** as well as the 32-bit `call` (op `0x6D`). Every
call-target scan in this project so far -- including the seeding for the TriCore project
rebuild -- collected only `0x6D`:

```
op 0x6D (32-bit call): 4965 sites
op 0x5C (16-bit call):  454 sites   <- missed
```

`FUN_80075DFA`, the gradient limiter itself, is reached by a 16-bit call from
`FUN_80075CF8` and was therefore **not** in the seed set. Consequences: the "1091 distinct
call targets" and "1395 functions / 82.9 % coverage" figures are undercounts, and any
"nearest preceding call target" heuristic mis-attributes code to the previous function.
Re-seeding with both opcodes is cheap and should be done before trusting any further
call-graph result.

### How to settle it

1. **Reflash FLOOR20 with the proxy log saved and the Android logger running end to end.**
   A flash is two downloads (PROG `0x80040000`, then CAL `0xA0020000`) and we now know
   exactly what the wire should show. Patches on the wire plus a plateau moving 8 -> ~16
   closes it. Patches on the wire and **no** movement proves Branch B and locates X
   upstream.
2. Statically, the place to look for X is the limiter's **input**:
   `*(a0-0x25b0) = *(s16*)0xD0006AEE + *(s16*)0xD000513A`. If that sum is rate-limited
   before it reaches the gradient limiter, that upstream limit is X.

### RESOLVED (2026-09-19): the scaling, the update rate, and therefore H4

Superseded by "The scale, the update rate, and the retraction of X" below. The factor
was **measured off the wire**, not chosen: the limiter runs at 100 Hz, the 0x212 torque
value refreshes at 50 Hz, so one published sample spans two limiter updates and one
internal table count equals **0.8 raw counts per observed sample**. H4 stands and is
sharper: FLOOR20 should read 16 and reads 5.

The caution below still applies to anything that follows and was not, in the end,
violated -- recorded because it was the live risk at the time:

> The factor must be read out of the code or the data rather than chosen to fit --
> picking it to match the desired answer is exactly the error made twice earlier in
> this session.

---

## The creep/assist subsystem, and what actually governs off-the-line feel (2026-09-19)

Ends the "input B" thread from `plans/dlcm_creep_assist_dig.md`. Input B
(`0xD000513A`) is written by `FUN_80075FF8`, which orchestrates four helpers:

| function | role |
|---|---|
| `FUN_8007605E` | enable / direction state machine (gear, brake, pedal, 50-count debounce) |
| `FUN_80076302` | ceiling = `min(LUT(0x80043FDC, speed), 0xD0006ABA)`; **headroom = ceiling - input A** |
| `FUN_80076208` | P term `min(Kp*err >> 7, headroom)`, integrator with anti-windup |
| `FUN_800763D2` | ramps the controller's own setpoint: `a0-0x3ecc += CAL 0xA00215B8`, then `min(target)` |

`FUN_80075FF8` sums the P and I halves and stores the result only when positive,
so **B >= 0 always**, and the anti-windup clamps `P + I <= headroom`, so
**A + B <= ceiling**. It is an assist that fills torque up to a speed-scheduled
envelope, not a limit.

### There is no rate limiter in it

The dig was looking for `step = min(limit, ...)` then `value += step` on the torque
path. It is not there. Three findings, each sufficient on its own:

- **Ki = 0** (`0xA00215B2`), so the integrator never grows and B is pure proportional.
- B is **additive and non-negative**, bounded above by headroom. It can only lift the
  limiter's input, never cap it.
- The only rate-shaped structure, `a0-0x3ecc += 13`, ramps the controller's internal
  setpoint, not torque.

Descriptor `0x80043FF4` -- flagged as an X candidate in the plan -- is consumed by
`FUN_800764F6`, a **PD controller on a speed error** (`0xD0006A38 - 0xD0005114`). The
table `[10,40,40,40,18,8,1]` is its derivative-gain schedule. Not a torque rate limit.

### Calibration constants read out of the code

Identical in the stock CAL and in `cal_as_flashed_20260721_floor5.bin`
(`artifacts/creep_assist_constants.py`):

| addr | value | role |
|---|---|---|
| `0xA00215B0` | 250 | creep gate: enable requires pedal `0xD0004FFC` < this, on a 0..10000 scale = **2.5 %** |
| `0xA00215B2` | 0 | integral gain Ki -- **zero, integrator dead** |
| `0xA00215B4` | 1000 | proportional gain Kp (`err * Kp >> 7`) |
| `0xA00215B6` | 16384 | IIR gain on the ceiling; 2^14 in Q14 = **unity, a pass-through** |
| `0xA00215B8` | 13 | **setpoint ramp step per update** |
| `0xA00215BA` | 64 | setpoint target when the direction flag is set |
| `0xA00215BC` | 50 | debounce count for the direction latch |
| `0xA00215BE` | 0 | creep target when the brake flag is clear |
| `0xA00215C0` / `C1` / `C2` | 1 / 1 / 1 | master enable, direction-latch enable, brake override |

### The creep loop, corrected and measured on the road (2026-09-26)

Three statements above are wrong or incomplete, all settled by the 2026-09-25
wrong-way rollback log. Full write-up in
`low-speed-clunk-and-creep-columns.md` §1A; the corrections themselves:

- **`0xA00215BA` = 64 is not the creep setpoint in general.** It is used only when
  the latch `a0-0x3EC0` is SET. With it clear, `FUN_800763D2` takes the target from
  LUT `0x80043FD0` in D (**640**) or `0x80043FC4` in R (**256**), in internal SPEED
  units -- a creep speed target of **290 / 116 CAN motor rpm**, which is spec §10.1.1
  "Creep Speed Target".
- **`0x80043FDC` is the creep/assist ceiling and it is now characterised:**
  `[0, 570, 1070, 2080, 3000, 3200]` internal on `[0, 128, 256, 512, 640, 768]`
  = 0 / 57 / 107 / 208 / 300 / 320 Nm at 0 / 58 / 116 / 232 / 290 / 349 CAN motor
  rpm. During a wrong-way rollback with the pedal released the commanded torque
  **equals** this table read at |motor speed| through a 0.2 s first-order lag, to
  **+/-6 % over 40 settled samples**. It bounds B only, never the pedal demand A,
  and it is zero at zero speed.
- **`DAT_d0006937` in `FUN_80076302` is "moving in the commanded direction"**
  (IDENTIFIED 2026-09-26; it is not the brake switch -- the measured command with
  the brake APPLIED is 63.0 Nm p50 against 58.2 Nm with it released, because both
  branches it selects between are calibrated to zero on this car). It swaps the
  ceiling source away from the wrong-way speed table `0x80043FDC` to the all-zero
  `0x80043FE8` / scalar `0xA00215BE`, i.e. it switches the assist off while the car
  is moving the way the gear commands. Written by `FUN_800722FE` as
  `gear_latch ? forward_latch : reverse_latch`, on a +/-100-count (+/-0.48 mph)
  deadband with a 12-count debounce on each clear. Full derivation and the latch
  addresses are in `low-speed-clunk-and-creep-columns.md` section 4 item 6.

Also worth recording because it is the one lever found so far that is decoupled from
everything else: the setpoint ramp `0xA00215B8` = 13 speed-counts per update times
`Kp >> 7` = 7.8125 is **101.6 torque-internal per update**, against the limiter's 100
internal/tick -- **within 1.6 %**. So the assist engagement rides the limiter, and
flash 4 made creep engagements 2.5x faster as an unintended side effect.

### 0x212 is the PRE-DAMPER command (2026-09-26)

`FUN_80075CF8` stores TrqLast at `0xD0006A5A`, and `FUN_80074780` -- the 0x212
publisher -- reads it from there. **`FUN_80075D52` then forms a different value**:

```c
a0-0x25AA = TrqLast + DAT_d00050f8 + DAT_d00050fa      // acceleration limiter terms
base      = clamp(a0-0x25AA, 0xD0006AA0, 0xD0006AA2)
damp      = clamp(0xD0006A76, -|base|, +|base|)        // Active Speed Damper output
0xD0006A54 = clamp(base + damp, -3000, +3000)
```

and `FUN_80070AD4` packs `0xD0006A54` for M CAN. So **the MCM is commanded something
0x212 never shows**, and the difference is the damper plus the acceleration limiter.
Measured consequence: through a direction reversal the actual torque (`0x1C0`) carries
**2-4x the per-sample step of the command** -- 13.5 -> 65 Nm across the cohorts against
8 -> 23 Nm. `0x1C0 Torque` is the only view of the post-damper command available from
the bus.

### Named signals picked up on the way

Traced from their producers (`artifacts/launch_pedal_technique.py` phase 1 verifies
the CAN-side decodes against cantools, 0 mismatches in 600 frames):

| RAM | meaning | producer |
|---|---|---|
| `0xD0004FFC` | accelerator pedal, slew-limited copy, 0..10000 | `FUN_8006E9AC` |
| `0xD000681C` | brake analog level (0xFFF = fault sentinel) | `FUN_8006ED3C`, sets DTC 0x6D |
| `0xD000683B` | brake analog valid | `FUN_8006ED3C` |
| `0xD0006831` | brake switch, digital | `FUN_8006F110`, plausibility DTC 8 |
| `0xD0006A42` | \|three-stage-IIR-filtered speed\| x 282/256 | `FUN_8007596E` |

Two consequences for the limiter:

1. **The speed limb is a standstill-only cap.** `0x80043FAC` is indexed by
   `0xD0006A42` on breakpoints `[0, 128, 256, 10240, 14720]` with
   `y = [20, 20, 1000, 1000, 1000]`. Sibling tables on the same axis run to 16000, so
   the speed limb caps the step in roughly **the bottom 1.6 % of the speed range** and is wide
   open above it. The creep ceiling table tops out at 768 on the same axis -- the bottom
   ~4.8 %. Both are low-speed-only functions, which is scale-free and does not depend on
   knowing the axis unit.
2. **The decreasing-path step is scheduled on brake pressure.**
   `a0-0x25b6 = LUT(0x80043F94, 0xD000681C)` runs -4 with no brake to -40 at full brake,
   and falls back to the constant -100 (`0xA002153E` / `0xA0021540`) when the brake
   analog channel is invalid. Lift-off with no brake is therefore the *slowest* possible
   torque decay.

---

## The scale, the update rate, and the retraction of X (2026-09-19)

### The 0x212 torque field, validated against actual motor torque

Cross-correlating the 13-bit field `(B4 & 0x1F) << 8 | B5` against the DBC's
`0x1C0 Torque` over one drive (59,162 paired samples):

- **r = 0.9939**
- slope **0.240 Nm per raw count**

Since the publisher `FUN_80074780` computes `raw = v * 0.4 + 2000`, one internal count
is `0.240 / 2.5 = 0.096 Nm`. That is the assumed 0.1 Nm/count internal scale, arrived at
independently from the wire rather than assumed.

### The limiter runs at 100 Hz -- measured, not inferred

> **CORRECTION, 2026-09-20: `0x212` is broadcast at 50 Hz, not 100 Hz.** The conclusion
> of this section (value refreshes at 50 Hz, each change spans two limiter updates, 1
> internal count -> 0.8 raw) is **CONFIRMED and unchanged** -- re-measured directly on the
> car, see "0.8 confirmed live" below. But the 100 Hz frame rate below is an artifact of a
> 2-channel capture recording `0x212` on both channels and merging them, and the
> "zero-run lengths are odd" evidence is the duplication, not the limiter.
>
> The tell was already in the numbers: gap median 0.0089 s sits *below* the mean 0.0100 s,
> which means clustered arrivals, not a steady publisher. A real 100 Hz stream has median
> = mean. The live capture gives median = mean = 0.0200 s with a 0.3 ms spread over 500
> frames.
>
> **The two errors cancelled in the ratio** -- the merge doubled the apparent frame rate
> *and* the apparent zero-run length -- so "refreshes at 50 Hz" came out right from wrong
> intermediates. **Do not build a new inference on the 100 Hz figure.** `CM_ BO_ 530` in
> `../../CODA-D-CAN.dbc` has said "two alternating sub-frames at 25 Hz each (50 Hz total)"
> all along.
>
> **Source identified.** The 29,581 frames are `coda_20260721_215506_T0.log` with bus 2
> (14,796) and bus 3 (14,785) merged -- 14,796 + 14,785 = 29,581 exactly. Per bus, both
> give median = mean = 0.0200 s (50.0 Hz); merged they give median 0.0190 / mean 0.0143.
> Same on `frombonnydoon.log`: 98,597 frames per bus at 50.0 Hz each, merged median 0.0194
> / mean 0.0138.
>
> **The odd-zero-run evidence is dead, not merely weakened.** Single-bus zero-run lengths
> decay smoothly with no odd/even structure at all -- 1:3115, 2:1631, 3:1067, 4:725,
> 5:535, 6:379, 7:259, 8:197. The published "1 (7846), 3 (503), 5 (147), 7 (92)" is the
> duplication and nothing else. Zero-delta share is 67.2 % single-bus, not 70.0 %.
>
> **The step histogram survives, so 0.8 has archive support too.** Single-bus
> `frombonnydoon`, 14,103 rising steps: 8 stands above its neighbours (435 vs 434 at 7 and
> 211 at 9), and 16 stands well above 15 and 17. Those are y=10 and y=20 at x0.8 -- the
> same logic as the live standstill capture, noisier. **The conversion therefore rests on
> two paths (archive step size, live step size), not the three once claimed.**
>
> **Analysis pipelines are unaffected.** Every loader keeps, per ID, only the single bus
> with the most frames -- done originally against gateway-rebroadcast double counting, and
> it immunises them against this. No re-extraction needed.

0x212 was read as broadcast at **100.0 Hz** (median dt 0.0089 s, 29,581 frames over
295.9 s) -- see the correction above -- but
the torque *value* does not change every frame:

- 70.0 % of consecutive-frame deltas are zero
- zero-run lengths are overwhelmingly **odd** -- 1 (7846), 3 (503), 5 (147), 7 (92) --
  i.e. changes land on every second frame
- median interval between actual changes during motion: **0.0200 s exactly**

So the value refreshes at 50 Hz and each observed change spans **two limiter updates**.
This closes the open thread on the limiter's task period without needing the timer
configuration behind the interrupt vector at `0x800408E0`.

**The conversion, therefore: 1 internal table count -> 0.8 raw counts per observed
0x212 sample.**

Corroboration from the step histogram during one drive: the most common non-trivial
deltas are 8, 56, 4, 80, 16, 12 -- which are the V-curve and speed-limb y-values times 0.8
(`y=10 -> 8`, `y=70 -> 56`, `y=20 -> 16`, `y=15 -> 12`) and the decreasing limb's
saturated `-100 -> 80` and `-4 -> 4`.

### FLOOR20 FLASHED AND VERIFIED (2026-09-20)

**The edit took, and it hit its prediction exactly.** This is the same edit as the
2026-07-22 attempt, which did not take.

Flash: `../../tools/flash_sim/omitec_sim.py --segments cal --preset vcurve-floor-20`, D CAN, Innomaker
gs_usb, 17:21. 456 blocks / 114,688 bytes in 10.7 s (42.5 blk/s), 16.0 s including erase
and verify, zero retries. `0xFF01` returned status `00 00 00 0C`, matching the captured
Omitec flash -- but that is a **readability check, not a content CRC**, so it is not
evidence the edit took. Log: `artifacts/flash_floor20_20260920.log`.

Verification drive, 89 s, no test gear transmitting
(`artifacts/floor20_verify.py`, `coda_20260920_172556_T0.log`):

| t(torque 0 -> +80 raw) | stock | FLOOR5 | FLOOR20 predicted | **FLOOR20 measured** |
|---|---|---|---|---|
| at speed | 0.380-0.440 | 0.220-0.240 | 0.100 | **0.100** (n=11 at >=500 rpm, p25=p75=0.100) |

**The arithmetic closes.** Target +80 raw = +200 internal; floor 20 gives 20 internal/tick
x 2 ticks per 20 ms sample = 200/(20x2) x 20 ms = **100 ms**. The same model on the old
curve (idx4=10, idx5=5, mean ~9 over the span) gives ~220 ms, which is what FLOOR5
measured. The model that predicted this drive also retrodicts the previous one.

**General form, at speed where the speed limb is open: `t(ms) = 2000 / floor`.** Floor 20 -> 100
ms, floor 35 -> 57 ms, floor 40 -> 50 ms. Below the speed-limb knee the speed limb caps the step at 20
regardless, so `0xA0021508[0..1]` is the only lever there.

**Open, n too small to call:** `p75` is 0.200 across all crossings but 0.100 once filtered
to >=500 rpm -- the slow ones are all low-speed (7 events). With floor and speed limb both at 20,
min() is 20 either way and low speed should also give 100 ms. Unexplained; may be an
artifact of the detector's 2 s window rather than a real effect. Needs more low-speed
crossings before it means anything.

> **Two analysis traps, both hit while producing the table above**, now guarded in
> `artifacts/floor20_verify.py`:
> 1. **`0x212` is on two buses at 50 Hz each.** Merging them yields the phantom 100 Hz --
>    the same artifact as the correction block above. Keep one bus per ID, by frame count.
> 2. **Timestamps are per-file relative** -- every file starts at 0.000. Concatenating
>    frames across files interleaves unrelated timelines and *silently changed the median
>    from 0.100 to 0.168* without changing the event count. Extract events per file; pool
>    the events, never the frames.

### 0.8 confirmed live, and the speed limb caught binding (2026-09-20)

Measured on the car in READY, in D, parking brake on, against gentle throttle blips
(`../artifacts/torque_update_interval.py`, log alongside it). 1250 frames, 25 s.

| Quantity | Measured | Means |
|---|---|---|
| `0x212` frame rate | **50.0 Hz** | not 100; see the correction above |
| gaps between torque **value changes** | median **0.0200 s**; 81 % in 0.016-0.024 s, 1 % near 0.040 s | value refreshes at **50 Hz** |
| median step size | **16 raw counts** | **20 internal x 0.8** |
| max step | 80 raw | 5 update periods at 16, across the ~99 ms holds between blips |

The value-change interval is measured directly here rather than inferred from a frame
rate, so **the 0.8 conversion no longer depends on the 100 Hz figure at all.**

**The median step of 16 is the speed limb, caught in the act.** The car was at standstill,
which is below the speed-limb knee, where `0xA0021508` caps the step at 20 internal. 20 x 0.8 =
16, and 16 is exactly what the limiter produced. One capture independently confirms the
speed limb's value, that it binds at standstill, the 0.8 conversion, and the
`(B4 & 0x1F) << 8 | B5` torque decode -- none of which it was designed to test.

**The decode is immune to the sub-frame alternation.** `0x212` alternates `AA BB AA BB`
between two payloads differing only in B2 and B4's top two bits (`0xE8 ^ 0x28 = 0xC0`).
The `B4 & 0x1F` mask excludes exactly those bits, so both sub-frames carry an identical
torque value. Verified by `../artifacts/frame_0x212_structure.py`.

### The internal speed axis: 2.203 counts per CAN motor rpm, derived

The speed limb's index `0xD0006A42` is `|three-stage-IIR-filtered speed| x 282/256`
(`FUN_8007596E`), and the speed limb breakpoints `[0, 128, 256, 10240, 14720]` are in
those units. Converting a breakpoint to CAN motor rpm needs the scale of the
speed the filter is fed, and this file previously supplied only a weak
constraint on it: the envelope test below reports overshoot of 1.68 / 1.42 /
1.38 % at 1.1 / 2.2 / 4.4 counts per rpm and says "2.2 is used; the conclusions
do not turn on it". That is not a measurement, and scripts downstream came to
describe 2.2 as "fitted", which it never was.

It is derivable, with two measured halves and no free parameter:

1. **The drivetrain's native speed unit is 2.000 counts per motor rpm.** Not an
   assumption from the DBC: regression of `0x308` BorgWarner input-shaft speed
   against `0x1C0` `Motor_Speed` gives `counter = 2.000 x RPM + 32128`,
   r = 0.99997, with the ratio 2.000 to three decimals across 500-6500 rpm and
   stdev < 0.05 in every speed bin, on both Coda and Vtrux. See
   [`../../../notes/borgwarner.md`](../../../notes/borgwarner.md).
2. **`x 282/256 = x1.10156`**, from the decompile above.

`2.000 x 1.10156 = 2.2031` counts per CAN motor rpm, so the speed limb's 256-count
breakpoint is **116.2 CAN rpm** and the speed limb is wide open above it.

**No gear ratio enters this conversion**, and `borgwarner.md` is what settles
that too: `0x308` reads the *input* shaft, which turns at motor speed. Were it
the output shaft the ratio would be `2 / gear_ratio` and would differ between
the Vtrux 32-01 and the Coda 31-03, which are physically different
transmissions; an identical 2.000 on both is only possible for the shaft common
to both at motor speed.

The competing reading -- that `282/256` alone gives 1.102 counts/rpm and a
232 rpm knee -- drops step 1: the input to that gain is already in half-rpm
counts, not rpm.

**This was not settleable from the logs.** `artifacts/speed_scale_check.py`
tries to locate the knee by finding the road speed at which the largest
observed step stops being capped at the speed limb's `20 x 0.8 = 16` raw counts, and
fails for two reasons worth recording: apparent "steps" above `70 x 0.8 = 56`
raw are the zero-order-hold grid bridging gaps in `0x212`, not limiter steps;
and the speed limb's index is IIR-filtered, so during a launch the real lookup can be
above the knee while instantaneous rpm is below it. With both filtered out,
no steady-speed high-torque samples remain below 232 rpm at all.

### X was never a second limiter

Applying the measured conversion to the V-curve:

| TrqLast | table y | predicted raw/sample | previously measured |
|---|---|---|---|
| 0 | 10 | **8** | **8** -- the "X plateau" |
| +80, baseline | 1 | 0.8 | 1 |
| +80, FLOOR5 | 5 | 4 | 5 |
| +80, FLOOR20 | 20 | **16** | **5** |

The unexplained plateau of 8 near zero is the V-curve's own `y = 10` at zero torque. Two
further checks agree: the measured plateau is **flat across speed**, which is what a
TrqLast-indexed table does and a speed-indexed limb does not; and the speed limb would
predict 16, above the observed 8, so the speed limb is not the binding term at those points.

`artifacts/x_limiter_shape_scan.py` found no table of X's shape because there is none.
Its negative result was correct and is now explained.

### H4 is strengthened, not weakened

Under the measured scale FLOOR20 should read **16** and reads **5**, while FLOOR5
predicts **4**. The 2026-07-22 flash did not take. This is now an arithmetic statement
with no free parameter, where before it rested on a scale-free ratio argument.

---

## H5 CONFIRMED: pedal timing, creep pre-load, and the notch (2026-09-19)

**H5 as stated:** the creep/assist term B is added to input A *before* the limiter, so
when creep has been allowed to build, the limiter's state TrqLast already sits past the
V-curve's notch at TrqLast = +80 internal (= +32 raw) and the notch is never traversed.

Tested over **1098 launches from standstill** across the whole Coda corpus (333 sessions,
26 GB, ID-filtered to 0x208/0x210/0x212/0x315), split at the FLOOR5 flash session
`coda_20260721_202537`. Script `artifacts/launch_pedal_technique.py`, output
`artifacts/launch_pedal_technique.csv`.

A launch is: stationary for >= 1 s, throttle crosses 2.5 % (the DLCM's own creep gate)
and stays on for >= 0.4 s, and the car subsequently moves.

### The brake never overlaps the throttle -- the variable is the gap

In all 1098 launches the brake is released *before* the throttle crosses 2.5 %. So the
driver-reported "careful touch and timing between brakes and throttle" is not pedal
overlap; it is **how long the car is allowed to creep in between**.

| brake-off -> throttle gap | n | torque at throttle-on (raw) | torque @300 ms | time to 400 raw (96 Nm) |
|---|---|---|---|---|
| 0 - 0.1 s | 132 | **33** | 161 | **0.581 s** |
| 0.1 - 0.3 s | 355 | 101 | 341 | 0.380 s |
| 0.3 - 1 s | 203 | 158 | 392 | 0.301 s |
| 1 - 3 s | 44 | 159 | 437 | 0.280 s |

(hard launches only, peak throttle >= 40 %.)

**A 2x spread, saturating at about 0.3 s.** Go straight from brake to throttle and the
launch starts at 33 raw counts -- sitting in the V-curve notch at +32. Wait three tenths
of a second and creep has carried TrqLast to ~160, well past it.

> **CORRECTION 2026-09-26 -- the attribution of that 0.3 s was WRONG, though the
> measurement is not.** This paragraph read: *"The saturation time is the mechanism's own
> signature: `0xA00215B8 = 13` internal counts per update, so 0 -> ~400 internal is ~31
> updates, which at 10 ms is ~0.31 s."*
>
> `0xA00215B8` ramps a **speed** setpoint, not torque. `FUN_800763D2` adds it to
> `a0-0x3ECC`, and `FUN_80076208` then multiplies the resulting error by `Kp >> 7` =
> 7.8125, so 13 is **101.6 torque-counts per update**, not 13. The 2026-09-25 wrong-way
> hill log rules the old reading out directly: the observed creep engagement rises at
> **80 raw per 20 ms sample**, which requires a demand ramp above the limiter's 100
> internal/tick. At 13 torque-counts/update it would rise at 10.4 raw/sample and the
> limiter would never bind.
>
> **The real mechanism for the 0.3 s is the gradient limiter climbing to the map's creep
> value through the stock V-curve notch.** Integrating the stock V-curve from 0 to the
> pre-C1 creep cell of 345 internal:
>
> ```
> 0 -> 80      rate 10 -> 6            ~10 ticks
> 80 -> 200    rate 1 -> 20  (notch)   ~19 ticks
> 200 -> 345   rate 20 -> 34           ~ 5 ticks
>                                      ~34 ticks = 0.345 s
> ```
>
> against a measured 0.31 s. Same number, different mechanism -- and the new one is
> consistent with the rest of this section, including why FLOOR5 bought 21 % in the notch
> band and ~5 % outside it.
>
> **Consequence: this table no longer describes the car.** C1 cut the standstill creep
> cell 345 -> 50 internal (7x less to pre-load) and flash 4 raised the limiter 10 -> 100
> internal/tick (TrqLast reaches 50 in half a tick). Pre-load is now small and
> essentially instantaneous, so the "wait three tenths of a second and it launches twice
> as well" behaviour is gone. Do not use these numbers to predict the current
> calibration.

### Sorted by the mediating variable, the notch is visible

| torque at throttle-on | n | @300 ms | time to 400 raw |
|---|---|---|---|
| <= 32 (at/below the notch) | 48 | 125 | 0.640 s |
| 33 - 79 (in the notch) | 232 | 221 | 0.520 s |
| 80 - 139 (past it) | 102 | 365 | 0.341 s |
| 140+ (fully crept up) | 371 | 392 | 0.301 s |

### What the FLOOR5 reflash actually bought, matched on pre-load band

| pre-load band | pre-flash | post-flash |
|---|---|---|
| 33 - 79 (in the notch) | 0.540 s (n=200) | **0.428 s** (n=32) |
| 80 - 139 (past it) | 0.360 s (n=46) | 0.340 s (n=56) |
| 140+ (fully crept) | 0.320 s (n=181) | 0.301 s (n=190) |

**-21 % where the notch is traversed, ~-5 % where it is not.** This is the quantitative
form of the driver's report that the reflash changed off-the-line feel and little else:
off the line is where the notch actually gets crossed.

Caveat: the `<= 32` band has only 2 post-flash launches, so no pre/post claim is made
there. The 33-79 band (n=200 pre, n=32 post) is the load-bearing comparison.

Incidental: the driver's median brake-to-throttle gap moved from 0.24 s pre-flash to
0.34 s post-flash -- adaptation to the changed response.

### Consistency with the earlier "launch-from-stop is unchanged" result

"Live-edit series 2" recorded launch-from-stop as unchanged across all three cohorts.
That is not contradicted: it pooled launches without conditioning on pre-load, and 71 %
of launches in the corpus begin already past the notch, where the edit is worth ~5 %.
Conditioning on pre-load separates the population the edit acts on from the one it
does not.

---

## The demand path (input A), fully resolved (2026-09-19)

The last unmapped block. `FUN_80077676` writes the raw demand at `0xD0005166`,
`FUN_800768D6` writes its clamp bounds `0xD0006AB8` / `0xD0006ABA`, and
`FUN_8007787E` applies the clamp to produce input A at `0xD0006AEE`. With this the
whole chain from pedal to CAN is table-driven and simulable.

### A second descriptor shape

The descriptor block starting at `0x80043F88` mixes two record layouts, so it cannot
be walked on a fixed stride:

```
1-D  { u32 n;  u32 x_ptr; u32 y_ptr; }                      12 bytes  -> FUN_8005F082 / FUN_8005EFD0
2-D  { u32 nx; u32 x_ptr; u32 ny; u32 y_ptr; u32 z_ptr; }   20 bytes  -> FUN_8005F3DA(desc, x, y)
```

The 2-D z plane is `nx` rows of `ny` int16, i.e. `z[i*ny + j]` with `i` indexing x.
**Slicing it the other way produces planes in which every row is the previous one
shifted by one column** -- that is the tell, and it is worth checking every time,
because the wrong slicing still yields a plausible-looking table. Under the correct
layout the accelerator map is monotone in both axes; under the wrong one it is
monotone in neither. `artifacts/demand_map_dump.py` walks the block, validates each
record shape at the current address, and dumps stock and as-flashed side by side.

### Map selection, per gear

> **GEAR ROLES CORRECTED 2026-09-26.** Until this date the table below read
> `0x80043378` = 10 = *forward* and `0x80043374` = 40 = *reverse*, and the
> prose called `0x800440B8` the forward accelerator map. That is backwards.
> The correction was established by measurement on **2026-09-22** and recorded
> in `artifacts/torque_path_sim.py` and in both reflash plans, but it never
> reached this file -- every flash from that date onward has used the
> corrected assignment while this section still contradicted it. Found while
> decompiling the `DAT_d0006937` writer, which reads the same constants.

Gear comes from `0xD00050AF` compared against PROG constants. The values are read
from the image; the roles were originally inferred from how the code uses them, and
the **forward/reverse assignment is now confirmed by measurement** (three
independent lines, below):

| constant | value | used as |
|---|---|---|
| `0x80043374` | 40 | **forward gear (D)** |
| `0x80043378` | 10 | **reverse gear (R)** |
| `0x80043376` | 20 | a non-driving position (demand forced to 0) |
| `0x80043377` | 5 | a non-driving position (demand forced to 0) |
| `0x80043355` | 5 | the mode value `0xD000501D` is gated against |

What confirms 40 = D:

1. **The map fit.** In D the car's coast and creep torque follow `0x80044070`'s
   zero-pedal row at RMS 2.4 raw against 26.8 for `0x800440B8`, and in R they
   follow `0x800440B8`'s point for point (`artifacts/one_pedal_model.py` phase 2,
   2026-09-22).
2. **The creep targets.** `FUN_800763D2` hands gear 10 the `0x80043FC4` target
   (256 internal = 116 CAN motor rpm = 1.2 mph) and everything else the
   `0x80043FD0` target (640 = 290 rpm = 3.1 mph). Forward creep is the faster of
   the two.
3. **The encoding.** 5 / 10 / 20 / 40 is one bit each in shifter order --
   P, R, N, D -- with 255 (`0x80043375`) as the invalid marker. The two values
   the code treats as non-driving are 5 and 20, i.e. P and N.

For the **reverse** gear the selection in `FUN_80077676` is:

```
if (brake_analog == 0 && (brake_switch == 0 || CAL 0xA0021878 == 0))
        || pedal >= CAL 0xA0021872:
    demand = flag ? LUT1D(0x800440AC, speed) : LUT2D(0x800440B8, pedal, speed)
elif flag:
    demand = LUT2D(0x80044084, brake_analog, speed)
else:
    demand = LUT2D(0x80044098, brake_analog, speed)
```

where `flag` is `a0-0x3e94` (`0xD000516C`). The **forward** gear uses the same
structure with `0x80044070 / 0x80044064 / 0x8004403C / 0x80044050` -- and those are
the descriptors every flash in this campaign edits.

| descriptor | **reverse**-gear role | forward-gear twin |
|---|---|---|
| `0x800440B8` | **the accelerator map**, `f(pedal, speed)`, 11 x 10 | `0x80044070` |
| `0x800440AC` | speed-only map, pedal **ignored**, `[800, 600, 400, 200, 0, 0, 0, 0, 0, 0]` on `[0, 256, 640, 1280, 2560, ...]` — see the warning below | `0x80044064` |
| `0x80044098` | brake map, `f(brake_analog, speed)`, default branch | `0x80044050` |
| `0x80044084` | brake map, `f(brake_analog, speed)`, flag branch | `0x8004403C` |

The pairing is confirmed by the **speed axis**, read from the image, and that is a
second tell independent of the map fit. All four reverse descriptors sit on
`[0, 256, 640, 1280, 2560, ...]`. The forward ones do not, and they are not all on
one axis either:

| descriptor | speed axis |
|---|---|
| `0x80044070` accel, `0x80044050` brake default | `[0, 640, 1024, 1536, 2560, ...]` |
| `0x80044064` flag-branch speed-only, `0x8004403C` flag-branch brake | `[0, 512, 896, 1280, 2560, ...]` |

So "the two gears do not share a speed axis" is true, but the stronger reading —
that each gear has one axis — is not: the forward side uses two. Anything that
edits these maps by **column index** has to check the axis of the specific
descriptor it is writing.

> **`0x80044064` / `0x800440AC` are NOT a coast map. Label corrected
> 2026-10-03.** The 2026-09-26 revision of this section called `0x80044064`
> "coast", which was wrong and was my error: I carried the name across from
> `artifacts/torque_path_sim.py`'s variable `D_COAST_D` and wrote a scratchpad
> variable name into a notes file as a role label. Flagged by the in-car
> session the same day.
>
> These two are the **flag-branch, pedal-ignored** maps — the 1-D speed-only
> tables `FUN_80077676` substitutes for the 2-D pedal map when `a0-0x3e94`
> (`0xD000516C`) is set, paired with `0x80044084` / `0x8004403C` on the brake
> side. Verified from the image 2026-10-03, both sides:
>
> ```
> 0x80044064  x [0, 512, 896, 1280, 2560, 6400, 10240, 12800, 15360, 16640]
> 0x800440AC  x [0, 256, 640, 1280, 2560, 6400, 10240, 12800, 15360, 16640]
> both        y [800, 600, 400, 200, 0, 0, 0, 0, 0, 0]
>            = +80 / +60 / +40 / +20 / 0 Nm, zero from 2560 counts (12.4 mph)
> ```
>
> **Why the label mattered.** Called "coast", this reads as a positive-torque
> path of +80 Nm at standstill and +40 at 4.4 mph, at exactly the speeds flash
> 8 drives negative — which would swamp −50/−88 and would be the §5A defect
> shape from a third direction. Called the flag branch, it is inert unless
> `a0-0x3e94` is set. The distinction is the whole of the risk assessment, so
> the label is not cosmetic.
>
> **The identification is CLOSED as of 2026-10-03: this is the APP-loss
> limp-home map family.** `../plans/dlcm_creep_and_one_pedal.md` line 218 had
> recorded it as a hypothesis — the **APP-loss base torque map**, requirements
> §4.2.1.1, limp home on loss of the accelerator pedal signal — with an
> explicit *"it must be identified, because a creep reduction that misses it
> leaves a path that creeps at 800"* that stayed open for weeks. It is now
> confirmed from the code: `a0-0x3e94`'s two inputs are the per-channel
> validity flags of a **dual-channel** accelerator pedal, and the flag arms
> only when **both** channels go invalid. Full chain, with the arbiter and the
> pedal DTCs, in
> `../plans/dlcm_reflash_7_8_clunk_and_regen_floor.md` §8.
>
> The practical consequence is unchanged from what the risk argument already
> assumed, and now rests on the code rather than on measurement alone: the
> branch cannot arm in ordinary driving, because arming it requires a hard
> dual-channel pedal-sensor fault that also sets P0120 / P0121. **But "cannot
> arm in ordinary driving" is not "cannot arm"** — if the pedal sensor does
> fail, this family is what drives the car, so do not treat these tables as
> dead bytes.

Selection scalars (identical stock and as-flashed):

| addr | value | role |
|---|---|---|
| `0xA0021870` | 200 | pedal must be <= this to *clear* the flag |
| `0xA0021872` | 100 | **pedal >= this overrides the brake map** -- 1.0 % on the 0..10000 scale |
| `0xA0021874` | 300 | debounce, flag clear |
| `0xA0021876` | 20 | debounce, flag set |
| `0xA0021878` | 1 | enables the brake-switch term in the selection |

`a0-0x3e94` is a two-way debounced latch in `FUN_800778DE`, driven by the two
digital inputs `0xD0006800` / `0xD0006801` and a pedal-low condition.
**CONFIRMED 2026-10-03 — the two inputs are the per-channel validity flags of a
dual-channel accelerator pedal**, written by the twin channel processors
`FUN_8006E734` (ch1 → `0xD0006800`) and `FUN_8006E828` (ch2 → `0xD0006801`),
both reached via `FUN_8006E704` ← `FUN_8007C2C6`. Each is
`valid = !(fault_a || fault_b)` over that channel's own pair of fault bits.

The latch therefore **sets when both pedal channels are invalid** (debounce
`0xA0021876` = 20) and **clears when either returns and the slew-limited pedal
`0xD0004FFC` ≤ `0xA0021870` = 200**, i.e. 2.0 %, for `0xA0021874` = 300 counts.
Counters at `a0-0x3e96` (set) / `a0-0x3e98` (clear).

Two neighbouring functions complete the pedal path and are worth knowing when
reading anything that consumes `0xD0004FFC`: `FUN_8006E93C` is the correlation
check (both valid **and** `|ch1 − ch2| ≤ 0xA00212A4` = 500 = 5.00 %, result to
`a0-0x27fe`, reported as DEM event 5), and `FUN_8006EA36` is the arbiter — ch1
when both agree, the surviving channel when one is invalid, the **lower** of the
two when both are valid but disagree, and CAL `0xA00212A2` (= **0**) when both
are invalid. The earlier "creep-only / pedal-ignored mode" guess in this
paragraph was wrong in its *reason*, though it landed near the right place: the
map ignores the pedal because the pedal is gone, not to produce creep.

### The REVERSE accelerator map (stock == as-flashed)

`0x800440B8`, internal counts. This is the **R** map -- see the correction note
under "Map selection, per gear" above. The live D accelerator map is
`0x80044070`, z at CAL `0xA0023C44`, tabulated in
`../plans/dlcm_creep_and_one_pedal.md`.

*(The "0.096 Nm/count" this section was written with is itself superseded: one
internal torque count is 0.1 Nm. The counts below are as read from the image and
are unaffected; only a conversion to Nm would be.)*

```
pedal \ speed     0    256    640   1280   2560   6400  10240  12800  15360  17920
    0           449    276    173   -345   -575   -690   -460   -368   -150   -150
 1000           920    690    322   -253   -368   -288   -219   -150   -115   -115
 1500          1265    920    460    345    230    115     92     58     58     58
 2000          1553   1265    690    633    575    288    230    230    230    230
 3000          2300   2128   1438   1035    920    805    690    633    518    460
 4000          2875   2818   2013   1725   1438   1265   1035    978    805    748
 5000          3000   3000   2300   2070   1898   1668   1380   1265   1035    863
 6000          3000   3000   2818   2588   2473   2300   1840   1610   1323   1150
 7500          3000   3000   3000   2990   2875   2703   2128   1840   1438   1323
 9000          3000   3000   3000   3000   3000   3000   2300   1955   1610   1438
10000          3000   3000   3000   3000   3000   3000   2415   2013   1668   1495
```

3000 counts is ~288 Nm, the right order for this motor, and the taper along the speed
axis is the constant-power region. The lift-off regen limb is the negative row at
pedal 0.

The forward brake map `0x80044098` at standstill gives 230 at zero brake, falling
through 173 / 100 / 80 to **0 for brake_analog >= 144**.

### What this does to H5 -- it becomes exact

At standstill the two maps differ sharply:

- **brake held firmly** (analog >= 144): demand = **0**
- **brake released**, pedal 0: demand = **+449**

So a firm brake hold pins the demand at zero and the limiter pulls TrqLast down to
zero with it. Releasing the brake steps the demand to +449, and the limiter must climb
from 0 to 449 -- **through the V-curve notch at +80**. The pre-load ramp the launch
data measures is therefore not creep building up; it is **the limiter climbing to the
creep demand through the notch**. That is why the FLOOR5 edit shows up off the line
and essentially nowhere else.

It also predicts a second, independent lever: hold the brake lightly (analog < 144)
and the demand never reaches zero -- it sits at 230/173/100/80, already at or above
the notch. Tested on the launch corpus, **matched on a short brake-to-throttle gap
(< 0.15 s)** so the timing effect cannot account for it:

| brake pressure held (0x208, 2 s before) | n | median pre-load (raw) | median time to 400 raw |
|---|---|---|---|
| <= 150 | 110 | **85** | 0.400 s |
| > 150 | 162 | **33** | 0.581 s |

Both halves of the driver-reported "careful touch" are real and separable: **how hard
the brake is held**, and **how long after releasing it before the throttle**. Either
one puts TrqLast above the notch.

### The overlap question, closed at the threshold that actually matters

The first launch extraction used a 2.5 % pedal threshold (the DLCM's creep gate,
`0xA00215B0` = 250), but `0xA0021872` = 100 means **1.0 %** pedal already overrides the
brake map -- so overlap in the 1.0-2.5 % band would have been invisible. Re-extracted
with the 1 % crossing recorded and ordered against brake release:

**In all 1059 launches where both events are visible, the throttle never reaches 1 %
before the brake is released.** There is no brake/throttle overlap at either threshold.
The two levers really are just brake pressure and the wait after release.

---

## A validated model of the torque path, and what it says the levers are (2026-09-19)

`artifacts/torque_path_sim.py` implements the chain as decompiled -- demand maps,
creep/assist, both limiter limbs, the publish scale -- reading its tables live out of a
CAL image, so pointing it at a modified CAL predicts what that CAL would do.

### Validation

The model is decomposed so each part is checked against data that does not depend on
the parts that are least certain. Two input scalings are **not** recoverable from the
code (the DLCM's internal speed unit against CAN rpm, and its brake analog channel
against `0x208 BrakePressure`). Nothing downstream of the sum depends on the brake
scaling, so the limiter test is independent of it.

**Test 1 -- the limiter envelope**, over 8 drive sessions spanning both cohorts,
89,748 rising published torque deltas. For each, the model is given the recorded
TrqLast and speed and asked for `min(speedLimb(speed), Vcurve(TrqLast)) * 0.4 * 2`:

| | |
|---|---|
| deltas exceeding the modeled envelope by > 1 count | **1,273 (1.42 %)** |
| deltas sitting *at* the envelope (limiter binding) | 18,066 (20.1 %) |
| \|observed - modeled\| on binding samples | median **0.15**, p90 0.75 counts |

98.6 % of observed deltas lie inside the envelope and a fifth sit exactly on it to
within a quarter of a count. If the tables, the 0.4 publish scale or the
two-ticks-per-sample factor were wrong, the envelope would either be violated
constantly or never touched.

The speed scaling is only weakly constrained by this test -- overshoot is 1.68 % /
1.42 % / 1.38 % at 1.1 / 2.2 / 4.4 internal counts per CAN rpm -- because the speed limb only
acts below ~256 internal, which is a small share of samples. 2.2 is used; the
conclusions do not turn on it.

### H6 is REFUTED: the limiter binds at speed too

H6 proposed that at speed the driver's own demand rate stays below the limiter's step,
so the limiter is transparent and no table edit could help. The binding data says
otherwise -- binding fraction of rising samples by CAN motor rpm:

| rpm | rising n | binding |
|---|---|---|
| 0 - 200 | 14,602 | **40.6 %** |
| 200 - 600 | 20,987 | 7.7 % |
| 600 - 1500 | 20,927 | 17.4 % |
| 1500 - 3000 | 14,096 | 21.6 % |
| 3000 - 6000 | 17,832 | 20.9 % |
| 6000+ | 1,304 | 7.1 % |

The limiter is an active constraint at every speed. The at-speed response **is**
tunable through these tables.

### Where it binds, and therefore which table cells matter

Binding fraction by TrqLast, split at 600 rpm:

| TrqLast (internal) | below 600 rpm | 600+ rpm | V-curve y (as-flashed) |
|---|---|---|---|
| -3000 .. -400 | 0.3 % | 4.8 % | 62 |
| -400 .. -160 | 1.9 % | 21.4 % | 22.7 |
| -160 .. -32 | 3.0 % | 30.5 % | 15.6 |
| -32 .. 0 | 5.0 % | 44.6 % | 10 |
| 0 .. +32 | 16.3 % | 45.2 % | 9 |
| +32 .. +80 | 28.0 % | **62.2 %** | 6.5 |
| +80 .. +200 | 25.6 % | 38.9 % | 12.5 |
| +200 .. +400 | 22.8 % | 6.7 % | 30 |
| +400 .. +1000 | **36.8 %** | 2.8 % | 62.5 |
| +1000 .. +3000 | **38.2 %** | 26.3 % | 70 |

Two distinct regimes, and they want different edits:

- **At speed the binding is concentrated in TrqLast -160 .. +200**, peaking at 62 % in
  the +32..+80 band. That is the zero crossing -- the driver-reported
  coasting-to-motoring case -- and it spans **five V-curve breakpoints (idx2..idx6 =
  x -80, -70, 0, +80, +200, y 15, 10, 10, 5, 20)**. The FLOOR5 edit moved only idx5.
  That is a plausible explanation for why the edit read as off-the-line-only: off the
  line the pre-load climb dwells specifically at the notch, while at speed the
  crossing sweeps the whole span and one point of five is a modest share.
  **Hypothesis, not yet tested on the car.**
- **Below 600 rpm the binding moves up to TrqLast +400..+3000** (37-38 %), where the
  V-curve is 62-70 but the **speed limb caps at 20**. So the speed limb, not the V-curve,
  governs the upper part of a launch, and `0xA0021508[0..1]` is the lever there.

### Predicted effect of candidate edits

`torque_path_sim.py 4`. Case 1 is the off-the-line pre-load climb (TrqLast 0 -> 400 at
standstill against the accelerator map's +449, so the speed limb applies); case 2 is the
at-speed crossing (TrqLast -400 -> +400 at 3000 rpm, speed limb open).

| variant | case 1 | case 2 | V-curve idx2..6 |
|---|---|---|---|
| stock (notch 1) | 0.50 s | 0.70 s | `[15, 10, 10, 1, 20]` |
| **as-flashed FLOOR5** | **0.33 s** | **0.53 s** | `[15, 10, 10, 5, 20]` |
| FLOOR20 (notch only) | 0.22 s | 0.43 s | `[15, 10, 10, 20, 20]` |
| notch 20 + speed-limb low end 60 | 0.20 s | 0.43 s | `[15, 10, 10, 20, 20]` |
| V idx2..6 all 20 | 0.20 s | 0.35 s | `[20, 20, 20, 20, 20]` |
| V idx2..6 all 20 + speed limb 60 | 0.18 s | 0.35 s | `[20, 20, 20, 20, 20]` |
| V idx2..6 all 40 + speed limb 80 | 0.10 s | 0.21 s | `[40, 40, 40, 40, 40]` |

Sanity check against the car: the model says stock -> FLOOR5 is -34 % on case 1; the
launch corpus measured -21 % on the comparable in-the-notch band. Same direction, same
order of magnitude, different metric.

**An unresolved tension, recorded rather than smoothed over:** the model predicts
stock -> FLOOR5 was worth -24 % on case 2 (at speed), and the driver reports feeling no
at-speed change. Either the at-speed improvement is real but masked in a rolling
tip-in, or the at-speed complaint is about a part of the response this model does not
cover. This should be resolved before an at-speed-targeted edit is flashed.

### Caution on the aggressive variants

The last row is a 4x increase in the step across the whole zero-crossing region. The
notch exists in the stock calibration for a reason -- almost certainly driveline lash
take-up -- so flattening it invites a clunk on every tip-in. The middle rows are the
defensible ones.

---

## Model-data convergence, and the at-speed tension resolved (2026-09-19)

### How tight the model actually is

The whole ramp is deterministic software on inputs that are all broadcast, so
convergence should be limited only by what the CAN observable can resolve. It is.

First, a modelling error found and fixed. The per-sample envelope was being computed
as `2 * step(TrqLast)`, but the limiter ticks **twice** between publishes and the
second tick indexes the V-curve at the *updated* TrqLast. Where the curve rises with
torque the second step is the larger one, so the doubling under-predicts. Stepping
sequentially instead:

| | doubling | two sequential ticks |
|---|---|---|
| rising deltas above the envelope by > 1 count | 1.42 % | **0.34 %** |
| mean signed error on binding samples | +0.071 | **+0.017** counts |

**Per-sample agreement** (89,748 rising deltas, 8 sessions, both cohorts):

| | |
|---|---|
| deltas inside the modeled envelope | **99.66 %** |
| deltas sitting *at* the envelope (limiter binding) | 21.0 % |
| of those, exact integer match | **76.7 %** |
| \|observed - modeled\| median / p90 / **max** | 0.17 / 0.72 / **1.00** counts |

The maximum error is exactly 1.00 count, which is the hard floor of the measurement:
the observed delta is `round(T1 * 0.4) - round(T0 * 0.4)`, and double-rounding the two
endpoints can differ from `(T1 - T0) * 0.4` by up to one count. **The model is
converged to the quantisation limit of the signal.** One count is 0.240 Nm.

**Free-run reproduction** (`torque_path_sim.py 6`) is the stronger test. While the
limiter binds, TrqLast evolves independently of the demand, so a whole run of binding
samples can be reproduced open-loop with no demand model: seed TrqLast from the first
published value and free-run. The only free parameter is the seed, searched over the
+/-1.25 internal counts the published value leaves open. 1272 runs, median 11 samples
(220 ms), longest 49:

| worst divergence across an entire free-run | runs |
|---|---|
| exact (0 counts) | 26.1 % |
| within 1 count | **67.1 %** |
| within 2 counts | 86.0 % |
| within 3 counts | 90.9 % |
| median 1, p90 3, max 74 | |

The tail is a classification artefact, not a model error: the binding flag is
per-sample, so if the demand catches up mid-run the model keeps climbing while the
real torque flattens.

**Sampling is not a limitation.** Measured broadcast rates: 0x210 pedal **100 Hz**
(the same rate the limiter ticks at), 0x1C0 and 0x208 above 300 Hz, 0x212 100 Hz with
the value refreshed every 20 ms. The DLCM's internal pedal filter (`FUN_8006E9AC`,
step `0xA00212A0` = 10) is a **deadband, not a rate limit** -- when the error exceeds
`3 * step` it jumps straight to the target, so fast pedal movements pass through
untouched and only dither is smoothed.

### The at-speed tension: the improvement was real, and larger than predicted

`artifacts/at_speed_crossing_compare.py` measures coast-to-drive crossings while
moving: published torque goes from below -40 raw to above +80 raw (+200 internal,
where the V-curve reopens), with the car above a standstill gate.

**A methodology trap, recorded because it nearly produced a wrong answer twice.**
0x212's inter-frame gap is bimodal -- median 9 ms, p90 20 ms -- so a naive continuity
threshold of 15 ms rejects almost every window. Checked across ten sessions spanning
2026-03 to 2026-09, 47-50 % of gaps exceed 15 ms in **both** cohorts, so this is not a
cohort artefact and the earlier launch comparisons are unaffected. With no continuity
check at all, capture gaps fabricate crossings with apparent steps of 250-490 raw
counts -- impossible, since the limiter's largest y is 70 internal = 56 raw per
sample -- and those dominated the pre-flash median. The script now uses a 50 ms
threshold and reports the physically-impossible population separately instead of
mixing it in.

**Rate-limited population, max step <= 60 raw:**

| cohort | n | t 0 -> +80 | notch dwell |
|---|---|---|---|
| pre-flash | 1755 | 0.401 s | 0.141 s |
| post-flash | 974 | **0.221 s** | **0.061 s** |

**-45 % on the traverse, -57 % on the dwell.** Matched on how hard the crossing was
driven, so entry rate cannot explain it:

| entry rate (raw counts/s) | pre | post |
|---|---|---|
| 0 - 200 | 0.639 s (n=415) | 0.400 s (n=202) |
| 200 - 500 | 0.401 s (n=765) | 0.320 s (n=383) |
| 500 - 1000 | 0.400 s (n=574) | 0.220 s (n=389) |

So the FLOOR5 edit **did** change the at-speed crossing substantially -- by more than
the model's -24 % prediction, not less. The model is conservative at speed, not wrong,
and the at-speed lever works.

**What remains open is perception, not physics.** The driver reports feeling no
at-speed change while the data shows the crossing got 45 % faster. Two candidates,
neither tested:

1. The notch traverse is a small share of the total at-speed tip-in. Reaching +200
   internal is only the start; climbing on to full demand (up to 3000) takes roughly
   half a second more at the V-curve's upper y-values, so a 0.18 s saving may be a
   modest fraction of the felt response.
2. The at-speed complaint may be about a later phase of the response that these
   tables do not govern.

Deciding between them needs the time-to-high-torque measured on the same crossings,
which is a small extension of the same script. **Until then, an at-speed-targeted
edit is justified by the code and the data, but its perceptual payoff is unproven.**

An unexplained observation, recorded rather than dropped: the physically-impossible
population (single-sample jumps of 190-490 raw counts, which are mode transitions
releasing a forced-zero output, or residual capture gaps) is 3868 pre-flash against
425 post-flash. That ratio is 9:1 where the clean populations run 1.8:1, and the
pre-flash corpus is only about 2.4x larger. Not understood; it does not affect the
clean comparison above, which excludes them.

---

## The perception question, answered with the accelerometer (2026-09-19)

### Finding the accelerometer first

The DBC carries `CM_ BO_ 816 "VICD: misc_Recvd 0x330. Long_Accel: signed byte,
0.08 m/s2/count."` -- a comment, not a confirmed `SG_`, and **wrong as written**:
0x330 is declared 1 byte in the DBC, but every frame is **8 bytes**, B0-B6 are
constant (`FC FC FC FD FF FF FF`), and B0 read as the signal gives a dead constant
of -4. So the signal was hunted rather than assumed
(`artifacts/accel_signal_hunt.py`), correlating every layout the project's
scan-completeness rule requires -- 8-bit signed/unsigned, 16-bit LE/BE
signed/unsigned, 12-bit byte-aligned both ways, 12-bit nibble-split -- against
kinematic acceleration derived from the wheel-speed derivative.

**0x330 B7 is the longitudinal accelerometer**, at 50 Hz:

| evidence | |
|---|---|
| r against kinematic acceleration | **+0.827** (excluding 13 out-of-range samples per drive) |
| zero point from the regression | B7 = **122.6** |
| modal value across a whole drive | B7 = **123** |
| implied scale consistency | slope 4.27 wheel-speed counts/s per accel count; with the VICD 0.08 m/s2/count this makes 1 wheel-speed count = 0.0187 m/s, so the drive's peak of 1073 counts is 20.1 m/s = 45 mph -- physically right |

The regression zero and the modal value agreeing to within half a count is the
strong check: a longitudinal accelerometer spends most of its time at zero.
The residual against the wheel-speed derivative is expected -- an accelerometer
also senses road grade, which the kinematic estimate cannot.

**PROMOTED TO THE DBC 2026-09-20** after the grade test below: `BO_ 816` DLC 1 -> 8,
`SG_ Long_Accel : 63|8@0+ (0.08,-9.84) [-9.84|10.56] "m/s2"` (offset = -123 * 0.08),
with the old, wrong `CM_` replaced. `dbc_validate.py` reports 100 % coverage and the
signal decodes symmetrically: raw 99 / 123 / 147 -> -1.92 / 0.00 / +1.92 m/s2.

### Does grade compensation take r toward 1? Partly -- and the elevation check is decisive

An accelerometer senses proper acceleration, so on a slope it also reads the
along-axis component of gravity: `a_measured = a_kinematic + g * sin(theta)`. Grade
varies on the timescale of terrain, kinematic acceleration on the timescale of pedal
inputs, so the test is a high-pass on both series.

| drive | raw r | r, 30 s high-pass | recovered grade p5..p95 | integrated elevation |
|---|---|---|---|---|
| `frombonnydoon` (mountain descent) | 0.742 | **0.877** | -0.91 .. +0.78 m/s2 (+/-9 %) | **-177 m** |
| `coda_20260818_135227` (urban) | 0.827 | 0.828 | -0.42 .. +0.44 (+/-4 %) | +6 m |
| `coda_20260904_190942` | 0.853 | 0.888 | -0.32 .. +0.79 | +55 m |
| `coda_20260610_121025` (flattest) | 0.894 | **0.932** | -0.22 .. +0.44 | +9 m |

Grade compensation helps **most exactly where the terrain is hilliest** (+0.135 on the
mountain descent, +0.001 on the flat urban drive), which is the signature the
hypothesis predicts. The flattest drive reaches r = 0.932 raw-ish.

**The integrated elevation is the load-bearing evidence**, because it is an external
physical check that a spurious correlation cannot pass: the Bonny Doon descent
integrates to **-177 m** with gradients up to +/-9 %, while flat urban round trips
integrate to **+6 m** and **+9 m** with gradients of +/-4 %. Right sign, right order,
right terrain.

**It does not reach 1, and the residual is the reference's fault, not the signal's.**
Two diagnostics say so: r is **flat to within 0.01 across +/-200 ms of lag** (so there
is no timing misalignment), and r **rises monotonically as the derivative window
widens** (0.05 s -> 0.30 s takes it 0.52 -> 0.88), which means the high-frequency
disagreement is noise in the differentiated wheel speed rather than in the
accelerometer. Differentiating a quantised speed signal is simply a poor acceleration
reference; the accelerometer is probably better than r = 0.93 suggests.

**One caveat carried into the DBC comment:** the fitted scale varies about +/-12 %
across drives (0.160-0.192 accel counts per wheel-speed count/s). Part of that is
errors-in-variables attenuation, which biases the slope low by an amount that depends
on how noisy each drive is. So the **zero point and the role are confirmed; the 0.08
m/s2/count scale is VICD's and is corroborated only to about +/-12 %.**

### What the driver actually felt

At-speed coast-to-drive crossings, rate-limited population, split by how much
acceleration the crossing actually produced:

| peak accel band | cohort | n | a peak | a at +0.6 s | t to +0.5 m/s2 | peak jerk |
|---|---|---|---|---|---|---|
| gentle < 0.4 | pre | 246 | 0.320 | 0.160 | -- | 4.02 |
| | post | 121 | **0.320** | **0.160** | -- | **4.04** |
| moderate 0.4-0.9 | pre | 757 | 0.480 | 0.320 | 0.822 s | 5.00 |
| | post | 587 | **0.480** | **0.320** | **0.587 s** | 5.89 |
| hard 0.9-1.6 | pre | 223 | 1.200 | 0.720 | 0.563 s | 8.01 |
| | post | 120 | **1.200** | **0.720** | **0.393 s** | **8.12** |
| very hard > 1.6 | pre | 135 | 1.920 | 0.960 | 0.549 s | 9.99 |
| | post | 146 | 2.640 | 2.080 | 0.378 s | 11.01 |

(m/s2 and m/s3; the same split by entry rate gives the same picture.)

**The reflash bought latency, not shove.** Across the gentle, moderate and hard
bands -- 94 % of crossings -- peak acceleration and peak jerk are **identical to
the count**, and only the onset moved, by **190-235 ms**. That is precisely the
change a driver is least equipped to notice: humans discriminate jerk and peak g
well, and a latency shift in a self-initiated action poorly.

So the torque ramp being 45 % faster through the notch and the drive feeling
unchanged are **both true and consistent**. The notch traverse happens at torques
too low to produce much acceleration; by the time torque is high enough to be felt,
the V-curve is well past the notch and unedited.

**Caveat on the last row.** The "very hard" band is selected on the outcome
(`a_peak`), so comparing `a_peak` inside it is partly circular. The post-flash
corpus also has proportionally more crossings in that band (15.0 % against 9.9 %),
which may be the driver using the car differently rather than a calibration effect.
Treat the bottom row as suggestive only; the load-bearing result is the identity of
peak and jerk in the three bands above it.

### What this implies for the next edit

The notch is the wrong lever for at-speed *feel*. It governs latency, and its
latency payoff has largely been taken already. To change what the car feels like at
speed the V-curve has to move where the torque is large enough to make acceleration
-- and the binding table says that at 600+ rpm the limiter only binds up there in
the **+1000..+3000** band (26.3 % of rising samples), i.e. **idx8/idx9, y = 70**.
Between +200 and +1000 at speed the limiter binds 3-7 % of the time: the demand
governs, and no table edit will change it.

**Hypothesis to test, not yet confirmed:** raising V-curve idx8/idx9 above 70 is
the at-speed "shove" lever, and the notch indices are the off-the-line "latency"
lever. They are different edits for different complaints.

---

## Open items / suggested follow-ups

**[2026-09-19] Current state and the shortest path forward.** The whole chain from
pedal to CAN is now traced and modelled, and `artifacts/torque_path_sim.py` reproduces
the limiter envelope on recorded data to within a quarter of a count. Remaining work,
in order:

- **A. [PARTLY RESOLVED 2026-09-19] The case-2 tension.** Measured: the at-speed
  crossing got **45 % faster** post-flash (0.401 s -> 0.221 s, n=1755/974, matched on
  entry rate). The model was conservative, not wrong, so at-speed predictions stand.
  **[RESOLVED 2026-09-19]** why it was not perceived: measured with the
  accelerometer at 0x330 B7, peak acceleration and peak jerk are identical pre and
  post across 94 % of crossings; only the onset moved, by 190-235 ms. The reflash
  bought latency, not shove. See "The perception question" above.
- **B. Decide the edit set with the simulator, then flash once, with capture.** A
  FLOOR20-only reflash is knowably capped: below ~116 on the speed axis the speed limb
  holds the step at 20, so setting the V-curve notch to exactly 20 saturates against
  it. Any edit aimed at the low end must move `0xA0021508[0..1]` too. Flash hygiene:
  redirect the proxy's stdout to a file in `artifacts/` (it logs via `basicConfig` to
  stdout only) and keep the Android logger running for the whole session -- both
  records were missing for FLOOR20, which is the only reason H4 needed arguing.
- **C. Identify the producers of `0xD0006800` / `0xD0006801`**, the two digital inputs
  behind the `a0-0x3e94` latch that swaps the accelerator map for a speed-only map.
- **D. `0x80044000` still has no identified consumer** (byte-identical to
  `0x8004400C`, whose consumer is `FUN_80076EC6`); likely selected by a computed index
  off the same base.
- **E. The brake analog channel `0xD000681C` has no established mapping to
  `0x208 BrakePressure`.** Needed only for modelling the decreasing path and the brake
  demand map; the increasing path and all launch predictions are independent of it.


0. **[2026-09-17] Zero-crossing hypotheses H1-H4 above are inputs to the Route A
   RAM read.** H4 (on-car CAL behaves as floor-5) is the one to test first,
   because if true it changes the interpretation of every 07-22 result in
   "Live-edit series 2" and reopens the question of whether the V-curve floor
   is a driveability lever after all.
1. **CAL §10.7 bank is physically present; VehSpd-table not yet pinned.** A targeted scan (`artifacts/cal_vehspd_table_scan.py`, output inline) confirms a family of gradient-limiter-shaped tables clustered at CAL **`0x80021400`–`0x80021c80`**: increasing axes `[0,80,160,320,480,640,800,960,1120,1280]` (0x80021BA0 / 0x800214AE), a positive V-curve `[62,35,15,10,10,1,20,40,70,70]` (0x80021526), and a negative descending curve `[-4,-4,-15,-15,-20,-25,-30,-40,-40,-40]` (0x800214C0 / 0x80021B90). Given the behavioral proof that §10.7 is active, these are very likely the §10.7 LUTs (positive/negative TrqLast limbs + axes). Candidate `gradientLimiterPositive_VehSpd` arrays — monotone-decreasing to small values, matching the observed speed→rate-cap collapse — include `0x800215D6 [40,40,40,18,8,1]` and `0x800213B8 [200,50,25,20,20,12]`, both **unconfirmed**. Per the 2026-07-02 runtime-RAM finding the active copy cannot be tied to the VehSpd role statically; confirm by the live-test edit (item 2). NB: this bounded scan advances the standing Goal-2 (CAL edit target) but does not resolve it.
2. **Live confirmation (definitive).** Reflash a candidate VehSpd gradient LUT (Goal 2 reflash path is established) and observe whether the high-speed rate cap shifts. This is the only way to name the table with certainty given the runtime-RAM indirection. **PARTIAL (2026-07-21):** the reflash path is now proven end-to-end on the real car via the MITM proxy, and a live edit of the **TrqLast-limb near-zero V-curve floor** (`0xA0021528`/`0xA0021B64` idx5) produced the predicted near-zero lash-ramp change (see "Live-edit confirmation" section above). The **VehSpd gradient table** itself is still not live-confirmed -- that remains the outstanding edit.
3. **Sharper regen/brake test.** Re-run the negative-limb test conditioned on brake-pressure magnitude bands (not just on/off) and deeper into regen, to see whether the descending rate cap scales with pressure (would firm up the §10.7 negative limb from LOW-MEDIUM).
4. **Do not** keep grinding static disassembly of `D176-D224`; it is obfuscation-bound. Effort is better spent on (1)/(2).
5. **[RESOLVED 2026-09-19 -- there is no such clamp.] Find the fixed ~8 cts/update
   near-zero rate clamp.** The ~8 cts/update figure is the V-curve's own `y = 10` at
   TrqLast = 0 under the measured scale (1 internal count = 0.8 raw counts per observed
   0x212 sample, limiter at 100 Hz, value published at 50 Hz). See "The scale, the update
   rate, and the retraction of X". No scalar to hunt; no live-edit needed. Original text
   follows for the record.
   ~~[NEW, top priority 2026-07-22] Find the fixed ~8 cts/update near-zero rate clamp.~~ The "Live-edit series 2" mapping proved the tip-in is bound by a scalar rate constant *below* both `min()` limbs, not by the V-curve (saturated) or the VehSpd table (speed-flat). Hunt this constant in CAL (a scalar ~8 in cts/update, or its fixed-point scaling; likely near the §10.7 bank `0x80021400-0x80021C80`) and confirm by live-edit. This — not the VehSpd table (item 2, now deprioritized for the *tip-in* question) — is the real driveability lever for off-the-line/tip-in feel.

## Artifacts / reproduction

**Creep/assist and launch characterization (2026-09-19) artifacts:**
- `artifacts/creep_assist_constants.py` -- dumps every calibration scalar the creep/assist
  subsystem reads, stock CAL against `cal_as_flashed_20260721_floor5.bin` side by side.
- `artifacts/launch_pedal_technique.py` -- phase 1 verifies the CAN decodes against
  cantools and inventories the corpus; phase 2 extracts every launch-from-standstill to
  CSV; phase 3 reports response against pedal technique. Reads ID-filtered copies of the
  corpus (the docstring gives the one-line `grep` that builds them, ~45 s for 26 GB).
- `artifacts/launch_pedal_technique.csv` -- 1098 launches, 706 pre-flash / 392 post-flash.
- `artifacts/lut_descriptor_map.py` -- the 1-D LUT descriptors and their CAL tables.
- `artifacts/demand_map_dump.py` (+ `.out.txt`) -- walks the mixed 1-D/2-D descriptor
  block and dumps the per-gear demand maps, stock against as-flashed.
- `artifacts/accel_signal_hunt.py` -- locates the longitudinal accelerometer by
  correlating every candidate layout against wheel-speed-derived acceleration.
- `artifacts/at_speed_crossing_compare.py` (+ `.csv`) -- at-speed coast-to-drive
  crossings, pre against post flash, with the continuity handling that population
  needs.
- `artifacts/torque_path_sim.py` *(Deleted 2026-10-10 at codasim plan step 7; the model is now `../../tools/codasim/`. Recorded outputs stand.)* -- the validated model. Phase 1 self-test, phase 2
  limiter envelope against recorded CAN, phase 3 demand map against settled torque,
  phase 4 what-if sweep of candidate CAL edits. Reads its tables out of whichever CAL
  image it is pointed at.
- Ghidra: `DlcmTricoreRebuild.java` now seeds both call widths; re-seeded project is
  1595 functions / 83.3 % instruction coverage (was 1395 / 82.9 %).


- `artifacts/torque_limiter_scheme_test.py` — behavioral discriminator (Phases 1–8). `RUN` set at top toggles phases; re-run: `py -3.12 projects/coda/notes/dlcm/artifacts/torque_limiter_scheme_test.py`.
- `artifacts/torque_limiter_scheme_test.out.txt` — comprehensive output, all Phases 1–8, all three logs (2026-07-08). Contains every number cited above.
- `artifacts/torque_limiter_regen_asymmetry.out.txt` — standalone Phases 7–8 capture (regen-limb brake/speed asymmetry) (2026-07-08).
- `artifacts/cal_vehspd_table_scan.py` — CAL §10.7-bank dump + decreasing-table scan (follow-up item 1).
- Logs: `projects/coda/logs/{frombonnydoon,driveafterfullycharged,codadriveslowturnonwithdefroster2}.log`.
- Code disassembly source: `%LOCALAPPDATA%/ghidra-projects/dlcm_export/can212_analysis.txt` (D-region + DBxx/E-region helpers).

**Live-edit series 2 (2026-07-22) artifacts:**
- `artifacts/lash_3cohort_maneuvers.py` (+ `.out.txt`) — baseline/floor5/floor20 comparison for launch-from-stop and full 100<->0 swings.
- `artifacts/lash_mod_pre_post_compare.py`, `artifacts/lash_overlay_plots.py` (+ `lash_overlay_*.png`) — pre/post crossing distributions and overlays.
- `artifacts/lash_shape_fit.py`, `artifacts/filter_pole_match.py` — rise linear-vs-exp + IIR pole extraction (ruling out §10.6 for the near-zero crossing).
- `artifacts/map_rate_limit.py` (+ `.out.txt`) — effective rate-limit envelope vs torque & speed; the decisive "fixed ~8 cts/update clamp, speed-flat" result.
- `artifacts/filter_pool_pointer_scan.py` — resolves §10.6 pool pointers (all boot-DRAM, no CAL ref).
- Cohort logs: floor5 `CANLogs/CodaLogs/coda_20260721_215506_*`, floor20 `coda_20260722_112358_*`; the floor-20 flash session was `coda_20260722_102259_*`.

**Zero-crossing clamp characterization (2026-09-17) artifacts:**
- `artifacts/zero_crossing_clamp_characterize.py` -- per-update (TrqLast, delta) through every zero crossing; Phase 0 cadence, Phase 1 traces, Phase 2 envelope fit / clamp-run / independence, Phase 3 negative side. Cohort-aware (baseline / floor5 / floor20 with per-cohort V-curve Y). Refuses the Android cohorts on `the bench PC` / `the bench laptop` (placeholder tree); run on `the Linux box` for all three.
- `artifacts/zero_crossing_clamp_characterize.3cohort.out.txt` -- full output, all three cohorts (the Linux box, 2026-09-17). Every number in the 2026-09-17 section comes from this file.

---

## Two behaviours of the torque path, measured on the car (2026-09-24)

Both were previously assumed from the decompile. Both are now measured, and one
of them is the opposite of what a first (unit-buggy) pass reported. They govern
any future map edit, so they belong here rather than in a per-change note.

### The accelerator map interpolates LINEARLY between rungs

The sim models the descriptor interpolators (`FUN_8005F082` / `FUN_8005F3DA`) as
clamped piecewise-linear. That was a code-reading claim; hypothesis H7 in
`dlcm-second-pass-hypotheses.md` separately disputes whether the *E5CC* MAC.W
kernel is a bracket-and-lerp at all. E5CC is the gradient-limiter path, not the
accelerator map, so it is not the contested case — but the claim was still
untested against hardware.

`artifacts/map_interp_check.py` tests it directly: 4322 samples where the rate
limiter is provably slack (pedal held +/-0.45 % for 220 ms, torque settled, brake
off, gear D), predicting `0x212` from the map and binning the residual **by where
the pedal sits between two rungs**. That last part is the whole test — a constant
offset or noise proves nothing about shape.

| position between rungs | n | median residual |
|---|---|---|
| on a rung (0.0–0.1) | 642 | 0.43 Nm |
| 0.4–0.5 | 352 | 0.30 Nm |
| midway (0.5–0.6) | 247 | 0.47 Nm |
| on a rung (0.9–1.0) | 929 | 0.05 Nm |

Flat. A firmware that stepped, held, or curved between rungs would bow at the
midpoint and vanish at the rungs. Overall median offset 0.44 Nm ~= 1.8 raw
counts, which is quantisation.

**Consequence:** the map is straight segments with real corners at the rungs. A
slope change designed at a rung is something the driver can feel if they move the
pedal slowly through it. Downstream filtering (the rate limiter, the §10.6 IIR)
rounds off fast transitions **in time**, not in pedal position, so it will not
soften a corner driven through slowly.

### The DLCM clips its own request to M_MAX / M_MIN before publishing 0x212

Not downstream in the MCM — inside the DLCM, upstream of the bus.

Drive side, `artifacts/where_is_the_clamp.py`, samples where the map asks more
than the concurrent `0x312` M_MAX allows:

| | p10 | p50 | p90 |
|---|---|---|---|
| `\|req − map\|` | 114 | 323 | 857 |
| `\|req − M_MAX\|` | **0** | **0** | 550 |

Regen side, `artifacts/regen_clamp_check.py`, steady-state only:
`\|req − M_MIN\|` = **0** at p10, p50 and p90, with actual torque tracking at
0.98 of the limit. Map asks −1562, pack allows −905, DLCM publishes −905.
(n = 11 — only captures postdating the C2 flash can test this, and there are
three. The agreement is exact rather than statistical; re-check when more data
exists.)

**Consequence, and it is what makes the current calibration strategy safe:**
commanding more than the limit is benign and behaves as `delivered =
min(commanded, limit)`. The excess is removed before it reaches the motor, so a
map may deliberately over-ask in order to capture whatever the pack allows that
day. The cost is dead travel at that end of the pedal, not a fault.

**The negative clamp LAGS -- corrected 2026-09-24 by the in-car session.** On the
C4c drive, 324 samples in 21 episodes had the request sitting BELOW M_MIN, 94 %
of them on a sample where M_MIN had just moved; longest episode ~1.10 s, worst
excursion 9.75 Nm past the limit. The request tracks M_MIN downward through the
FALLING RATE LIMITER rather than being hard-limited instantaneously. So read the
clamp as **"clamped within ~1 s"**, not "clamped by construction".

The steady-state measurement above could not see this **because of how it was
filtered**: requiring the request settled for 300 ms selects exactly the samples
where the lag has already resolved. A filter chosen to remove one confound
removed the evidence for another. Worth remembering when a clean result comes
out of a tightly filtered population.

**A trap that reversed this answer once.** The first pass stored `0x312` as
`raw − 2000` while comparing against the map in internal counts, which differ by
0.4. That made the normal 2998-internal ceiling read as "1199", manufactured an
apparent population of spurious low limits, inflated every gap 2.5x, and produced
the **opposite** conclusion — that the DLCM published its full request. If a
limit field ever appears to be violated by actual torque, check units before
believing it.
