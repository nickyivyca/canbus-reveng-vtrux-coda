# DLCM Decompile — Second-Pass Hypotheses & Investigation Angles

> **⚠ 2026-09-19.** Written under the assumption that the DLCM is a Renesas SH-4. It is an
> **Infineon TriCore, little-endian**. Any hypothesis here that reasons about instruction
> encodings, opcode statistics or "obfuscation" is void; hypotheses about data layout, LUT
> shape and CAN behaviour are unaffected. See `coda-dlcm-decompile-notes.md` → Architecture.

**Status: UNCONFIRMED. Nothing here is acted on or verified.** These are fresh angles from a
re-read of `coda-dlcm-decompile-notes.md`, written before discussion. The prior pass was thorough
but hit a wall (V-curve LUT has strong shape evidence, zero discoverable code reference). Several
of the walls it hit look like they were built on an unverified assumption or a conflation of two
different tables. Each item below states the hypothesis, why the prior pass missed/mishandled it,
a concrete test, and what would confirm or refute it.

Goal unchanged: locate `gradientLimiterPositive_TrqLast` / `gradientLimiterNegative_TrqLast` in
CAL and widen them through the lash zone.

---

## UPDATE 2026-07-02 — the crux (off-by-8) is resolved; see main notes

The "single most important observation" below was investigated first. Result: the `0x80021400`
"pointer" **does not exist** — it is a big-endian misread of a little-endian data field `(640, 20)`
at record offset **+0x30** of a 24-record, 52-byte descriptor array at 0x80041800. Full write-up in
`coda-dlcm-decompile-notes.md` -> "Off-by-8 resolved" (2026-07-02); scratchpad
`artifacts/descriptor_offby8_trace.py`. Consequences for the hypotheses below:

- **Crux / off-by-8:** RESOLVED. There was never a real +0x3C (or +0x30) CAL pointer. `[R12+0x34]`
  in DBC0 is real code (BE `0x50cd`), but R12 is a runtime RAM struct, not this init table.
- **H1 / H7:** premise removed — 0x80021400 is not E5CC's target (not a pointer at all). The
  "two different tables" tension is moot on the 0x80021400 side; the V-curve question stands alone.
- **H2:** resolved as far as static analysis can take it (see main notes "R12 backtrace" +
  "R13 up-trace", 2026-07-02). R12/R13 are inherited base pointers; `[R13+0x34]` is the module
  data-block pointer (13 confirmed load sites); E5CC's input is a double RAM indirection
  `[[R13+0x34]+0x34]`. The up-trace showed R13 is **OS/context-managed** (set by the VBR-dispatch /
  task-control-block layer, restored via `mov.l @(0x20,r1),r13` in the VBR+0x400 handler), and the
  gradient task functions are entered by that dispatch layer with **no static caller or flash
  pointer table**. So the table addresses are per-task RAM, not in the flash dump. **Static analysis
  of PROG+CAL cannot yield the numeric table address.** Next options: live-ECU RAM walk, or empirical
  patch-and-observe on the CAL V-curve candidate (0x80021500 / 0x80021b50). The code-trace line of
  attack is now exhausted; remaining approaches need an ECU.
- **H3:** RESOLVED — the BE-pointer dismissal was *correct*; the field is LE data, not a BE pointer.
- **H6:** RESOLVED — uniform **BE instructions / LE data**; the "inconsistent endianness" was the
  symptom of reading one LE data field as a BE pointer.
- **H4 / H5:** untouched — independent of the off-by-8; still open as cross-checks.

---

## The single most important observation: the "E5CC reads 0x80021400" chain is UNVERIFIED

The prior pass's whole code-side story is: `DBC0: mov.l @(0x34,r12),r0 ; bsr E5CC`, therefore
`R0 = [R12+0x34] =` the gradient table pointer; and separately, "the only CAL pointer in the
FFFF module descriptor blocks is `0x80021400`, sitting at descriptor offset **+0x3C**"
(PROG 0x80041A0C). It then wrote "R0 starts at 0x80021400" into the R0-advancement map and built
the entire 0x80021400 layout analysis on top of that.

**But +0x34 != +0x3C.** They differ by 8 bytes. The code reads `[R12+0x34]`; the only CAL pointer
found sits at `[descriptor_base + 0x3C]`. So "E5CC reads 0x80021400" is an *assumption*, never
demonstrated. Three possibilities, none checked:

1. `R12 = descriptor_base - 8`, so `[R12+0x34] = [descriptor_base+0x3C] = 0x80021400`. (Plausible;
   note the pre-pointer monotone sequence starts at 0x800213F8 = 0x80021400 - 8, hinting the real
   table base may be 0x800213F8 and the descriptor stores base+8.)
2. There is a *second* CAL pointer at the `[descriptor_base+0x34]` slot that the prior scan didn't
   surface, and *that* is what E5CC reads — a different table than 0x80021400.
3. `0x80021400` isn't read by this path at all.

Resolving this one off-by-8 is the crux. Everything downstream depends on it.

---

## H1 — 0x80021400 (E5CC target) and the V-curve at 0x80021500/0x80021b50 are DIFFERENT tables

The prior pass simultaneously treated (a) 0x80021400 as "the gradient limiter table" (because the
code pointer leads there) and (b) the V-curve at 0x80021500 as "the gradient limiter table"
(because its shape matches). These point to different CAL addresses, so they cannot both be the
same table. The pass never reconciled this.

- `0x80021400` data is a **monotone ascending** sequence `[3000,4000,5000,6000,7500,9000,10000]`.
  That is the wrong shape for a gradient rate limiter (which is a V-curve, tight near zero). It is
  the *right* shape for a torque/demand map, a speed-limit map, or a pedal curve.
- `0x80021500` / `0x80021b50` data is the **V-curve** `[62,35,15,10,10,1,20,40,70,70]` — textbook
  gradient-limiter shape.

**Hypothesis:** the DBC0->E5CC path computes something else (torque demand, or a speed/torque
limit) from the monotone table at 0x80021400, and the actual §10.7 rate-limiter V-curves live at
0x80021500/0x80021b50, reached by a *different* code path we haven't traced. This would explain the
central paradox — why the code-trace (-> 0x80021400) and the shape-search (-> 0x80021500) never met.

**Test:** verify (via H2) exactly which CAL address E5CC reads; independently find the code path
that reads 0x80021500/0x80021b50. If they are distinct paths, H1 holds.

---

## H2 — Complete the R12 backtrace (never done) using PROG init code, not the boot ROM

The pass said "next step: trace R12 backward to read [R12+0x34]" at least three times and never did
it. Its stated excuse — "R12 is set by the bytecode VM at runtime" — was later **retracted** when
the pass disproved the VM hypothesis ("plain SH-4 throughout"). So the blocker is gone; the trace
was just never redone.

Critically, the pass kept deferring to "GBR / the descriptor base is set in boot ROM we don't
have." But the FFFF module descriptor blocks and the CAL pointer are in **PROG's own init region
(0x80041800-0x80041C00, pointer at 0x80041A0C)** — which we have. The descriptor R12 points to is
almost certainly a RAM copy of one of these PROG-resident templates, set up by PROG init code at
0x8004xxxx. We do not need the boot ROM for this.

**Test:**
- In Ghidra (or Python), find every writer of R12 on the path into DBC0 (the D8xx-D9xx computation
  block, and its callers). Determine R12's value or the descriptor it points to.
- Fully enumerate the four FFFF descriptor blocks at PROG 0x80041800-0x80041C00: dump every 4-byte
  field, flag every value in 0x8002xxxx (CAL range) under **both** endiannesses. Map which
  descriptor field offset holds which CAL pointer.
- Read `[descriptor+0x34]` directly from the binary once the descriptor base is known.

**Confirms:** a concrete CAL address that the gradient path provably loads. That single fact ends
the entire "no code reference" impasse.

---

## H3 — The dismissed 0x80041A0C -> 0x80021400 "spurious BE" pointer may be real; descriptors may store pointers differently than code literal pools

The pass found the bytes at PROG 0x80041A0C read as `0x80021400` when interpreted **BE u32**, and
dismissed it: "region is LE u32 init-table data, BE interpretation almost certainly spurious; LE
value 0x00140280 fits the init-table record pattern."

That dismissal is shaky. It is entirely normal for a **data descriptor structure** to store
pointers in a different byte order than **code literal pools**, or to store **16-bit CAL-relative
offsets** instead of absolute pointers. `0x00140280` as "init-table record" was asserted, not
shown. And `0x80021400` BE is a perfectly valid CAL pointer landing exactly in the V-curve region.

**Test:** parse the whole descriptor region structurally (record stride, field roles) rather than
scanning for a fixed pointer format. Check whether CAL addresses in these records are stored BE
u32, LE u32, or as 16-bit offsets from 0x80020000. If descriptors store CAL pointers BE (while code
pools store LE), then the pass's exhaustive "0 LE pointers to the V-curve" scans were looking in the
wrong byte order for this structure class the entire time.

---

## H4 — 0x80020820 is likely the calibration TOC / descriptor array; parse its 44-byte records for CAL-relative OFFSETS

`0x80020820` is the *only* non-string CAL data with a confirmed code reference (loaded by the 8 KB
PROG@0x800730f6, which is in the gradient call tree at depth 6). The pass found ~16 entries sharing
a `00 3c 00 46` marker at a **44-byte stride** (it even guessed `RECORD_SIZE = 44`), then abandoned
it after deciding the marker was "just (60,70) as adjacent X breakpoints."

A 44-byte record array with a code-referenced base is a prime **calibration descriptor table**
(EMS9180 is a Continental platform; these carry internal record arrays mapping calibration items to
addresses/dimensions). The pass's "no calibration TOC in CAL" conclusion assumed a TOC would store
**absolute** 0x8002xxxx pointers. If records store **16-bit offsets relative to CAL base**
(0x80020000), then the V-curve at file offset 0x1500 is stored as `00 15` — invisible to every
absolute-pointer scan run so far.

**Test:** dump the 44-byte records at 0x80020820 (and the 15 sister entries) as structured fields.
Search each record for 16-bit LE values equal to 0x1400, 0x1500, 0x1514, 0x1528, 0x1b50, 0x1b64,
0x1b88, etc. (the candidate table offsets). A hit maps a descriptor record to a table and, via the
record's other fields, tells us dimensions and axis pointers.

---

## H5 — 0x80021b50 is a contiguous BANK of all four §10.7 tables, not a "second copy" of the V-curve

The pass called 0x80021b64 a duplicate of the 0x80021528 V-curve, but its own dumps show the two
regions have **different structure**: 0x80021500 is a single table with header+clips; 0x80021b50 is
"multiple 1-D LUTs grouped back-to-back." The bank contents it dumped:

```
0x80021b58  [-256,-128,128,256]                                small X axis
0x80021b64  [62,35,15,10,10,1,20,40]                           V-curve Y  (pos_TrqLast?)
0x80021b78  [-700,-600,-80,-70,0,80,200,400,800,3000]          X axis
0x80021b88  [-4,-4,-15,-15,-20,-25,-30,-40,-40,-40]            descending Y (neg_TrqLast?)
0x80021ba0  [0,80,160,320,480,640,800,960]                     another X axis (VehSpd/BrakePress?)
```

That is exactly the shape of the four §10.7 calibration items sitting together: a positive-gradient
V-curve, a shared/paired X axis, a negative-gradient descending curve, and additional axes for the
VehSpd/BrakePress limbs. The "two copies" framing obscured this.

**Hypothesis:** 0x80021b50 is the runtime bank holding `gradientLimiterPositive_TrqLast`,
`gradientLimiterNegative_TrqLast`, and their axes contiguously; 0x80021500 is a single table's
fuller/standalone descriptor. The edit target for the lash-zone widening is this bank.

**Test:** parse 0x80021b50..0x80021c80 as a sequence of {X-axis, Y-axis} i16 tables under confirmed
LE i16, label each against the four §10.7 items by shape and axis-domain, and cross-check the count
of axes/curves against §10.7's four LUTs + two scalar constants.

---

## H6 — Resolve the endianness split; the "different endianness per axis" is a misparse symptom, not a real split

The pass left a genuinely alarming loose end (its own section title: "The Inconsistent Endianness
Problem - Why It Doesn't Make Sense"): in the 0x80021400 region, the "BrakePress axis" only reads
sensibly as LE, the "VehSpd axis" and "TrqLast axis" only as BE, and the "Y outputs" only as LE.
A single table cannot use different byte orders per row. When a parse needs that, the parse is
wrong about the structure — not the endianness.

Separately: instructions disassemble correctly as BE 16-bit words, yet CAL numeric arrays read
sensibly only as LE i16. On a single-endian SH-4 both should agree. The likely real explanations
(in order): Continental's calibration tooling writes CAL data in x86/LE order and the firmware
byte-swaps on read; or the region at 0x80021400 is not a clean X/Y array at all (supports H1).

**Test:** pin the SH-4 data endianness definitively — (a) check the reset/strap configuration if
recoverable, (b) cross-check against a CAN RX handler storing a *known* signal (e.g., a DBC-defined
Motorola BE wheel-speed) into SRAM and see whether it byte-swaps, (c) statistical: which single
interpretation makes the *most* CAL arrays monotone/plausible. Then re-parse 0x80021400 under the
one correct interpretation. If it stops looking like a clean axis table, H1 is reinforced and
0x80021400 is a different (or non-LUT) structure.

---

## H7 — Re-derive E5CC's role and the D1CE operand assignment; the MAC.W kernel is a dot-product, not a bracket-and-lerp

Two things the pass may have gotten backwards:

1. **D1CE `cmp/ge r0,r12`.** The pass labels R0 = "gradient limit threshold (from E5CC)" and
   R12 = TrqLast, then uses the compare to pick positive/negative path. But the Simulink Relational
   Operator picks the path from `TorqueDemand > TrqLast_prev` — i.e., it compares **demand vs
   TrqLast**, not "limit vs TrqLast." If R0 is actually **TorqueDemand** (freshly computed by
   E5CC), then E5CC computes the *demand*, and 0x80021400 (its input table) is a **demand/torque
   map** — directly supporting H1 that 0x80021400 is not the rate limiter.

2. **E5CC kernel is `mac.w @r0+,@r2+` x3.** That is a sum-of-products (dot product / FIR /
   polynomial eval), not the compare-fraction-interpolate pattern of a 1-D breakpoint lookup. So
   0x80021400 may be a **coefficient/weight array**, not an X-axis. A gradient-rate-limiter table
   lookup would more likely be a simple indexed fetch + clamp (few or no MAC.W). This is evidence
   that the V-curve tables (0x80021500/0x80021b50) are read by *different, simpler* code than
   E5CC — consistent with H1/H5.

**Test:** hand-trace E5CC + its three BSR targets (EFD2/EFE4/EFF6 -> E3F8 etc.) as raw SH-4,
ignoring Ghidra's SLEIGH gaps, to establish: does it interpolate one output from an X/Y pair, or
accumulate a weighted sum across an array? And re-derive R0's identity at D1CE by tracing R0 back
from the compare. Result tells us what 0x80021400 physically is.

---

## Recommended order (cheapest-definitive first)

1. **H2 + the +0x34/+0x3C off-by-8** — trace R12, enumerate descriptor CAL pointers, read
   `[descriptor+0x34]` from the binary. Pure static, Ghidra + Python, no hardware. Most likely to
   end the impasse outright.
2. **H1 / H7** — with H2's answer, determine whether 0x80021400 (E5CC) and 0x80021500/0x80021b50
   (V-curve) are separate tables, and what each computation actually is.
3. **H4** — parse 0x80020820 records for CAL-relative offsets (independent path to the same answer;
   good cross-check on H2).
4. **H5** — parse the 0x80021b50 bank into the four §10.7 items once we trust the region.
5. **H3 / H6** — endianness and descriptor-pointer byte order; mostly feed the above.

The empirical patch-and-power-cycle test (prior pass's fallback) stays as the last-resort confirmer
once static analysis names a specific address — but H2 may make it unnecessary for *identification*
(still wise as the final safety check before trusting a flash edit).
