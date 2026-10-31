# Coda DLCM ECU — Firmware Decompile Notes

> ## ⚠ 2026-09-19 — ISA CORRECTION: this ECU is TriCore, not SH-4
>
> **The DLCM is an Infineon TriCore (little-endian). This file previously asserted
> Renesas SuperH (SH-4) big-endian, and every disassembly-derived finding below was
> produced under that wrong premise.** See the [Architecture](#architecture) section for
> the evidence and for why the old evidence looked convincing.
>
> **Before relying on anything in this file, check which side of this line it falls on:**
>
> | Status | What |
> |---|---|
> | **Still valid** | Anything derived from *data*: the UDS dispatch table, DID descriptor tables, the REDYWAIT state descriptor struct, the 12-byte event record table, CAL contents, binary provenance, load addresses, the flash session summary, and all CAN-log analysis. Data structures were read correctly because reading a table does not depend on the instruction decoder. |
> | **Invalid until re-derived** | Anything derived from *disassembly*: the 353 functions in the `dlcm_analysis` Ghidra project, the “529 Continental variant opcodes”, the delay-slot “obfuscation”, the `reset_entry` / VBR / startup-chain analysis, the CAN 0x212 transmit code trace, the torque-limiter code trace, and every `halt_unimplemented()` / `halt_baddata()` explanation. |
>
> Re-derivation is cheap, not a re-investigation: under `tricore:LE:32:default` the image
> disassembles cleanly on the first pass. The UDS SecurityAccess handler went from
> `halt_baddata()` to readable C in one run, which is how the seed/key algorithm
> — blocked for months — was solved the same day. See `dlcm-security-access.md` §1c.

## Goal

**Speed up the torque zero-crossing anti-lash filtering / rate limiting** so the throttle response feels less sluggish through the lash zone. Mechanism per the spec is the §10.7 State Dependent Torque Gradient Limiter — a pure rate limiter whose tightness near zero comes from `gradientLimiterPositive_TrqLast[TrqLast]` and `gradientLimiterNegative_TrqLast[TrqLast]` having small step sizes around TrqLast = 0. The end goal is to identify those two LUTs in the CAL binary and edit them so the rate limit through the lash zone is larger.

## §10.7 Block Diagram (authoritative)

The Simulink topology, calibration item list, and rate-limit equations live in **`dlcm-torque-flow.md`** (re-transcription of `dlcm-torque-flow-chart.png`). Refer to that file for the canonical architecture; this notes file does not reproduce it.

## The symbol map — KEEP THIS UP TO DATE

**`artifacts/dlcm_symbols.csv` is the function-to-meaning index for this firmware,
and it is the source of truth. The Ghidra database is derived from it.**

Apply it with `ghidra/scripts/DlcmApplySymbols.java`; check it is still applied
with `DlcmSymbolCensus.java`.

**Why it exists.** On 2026-10-07 the census measured the database after two
months of reverse engineering: **2960 functions, 0 with a real name, 0 labels, 0
comments.** Findings flowed out of Ghidra into prose and never back in, so every
session opened the project, saw `FUN_80056c20`, and had no signal that the answer
was already written down. That produced **four re-derivations of existing material
in a single session** (worklog 6H.1 the UDS DID table, 6H.26 the creep
identification, 6H.29 the reaction chain, 6H.32 reason code 12) and one of them
published a wrong attribution that an existing note had explicitly warned against.
A named function makes that failure visible the moment a decompile is read.

**Why the CSV and not the database.** Ghidra projects must live on a local path
(`tools-reference.md`), so the database does not sync between machines. Anything
recorded only there is stranded — which is literally how
`dlcm-dtcs-investigation.md` §2b came to exist, its opening line noting that the
finding "existed only in `~/ghidra-projects/dlcm_export/safety_flags.txt`, which
is machine-local and does not sync." The CSV is in the repo and syncs. The
database is disposable and rebuildable.

**The maintenance rule, for every future session doing decompilation work:**

1. **Before tracing a function, look it up.** `grep` the address in
   `dlcm_symbols.csv`. A hit means the work is done — read the `source` column
   and go to that note section instead of re-deriving it.
2. **After identifying a function, add the row** — in the same step as writing
   the finding to notes, not later. Columns: `address, name, kind, end, role,
   source, confidence`. Set `confidence` to `hypothesis` unless the role is
   confirmed, and always fill `source` with the note section that establishes it,
   so a later reader can check the claim rather than trust the name.
3. **Record fragments explicitly** with `kind=fragment` and a `role` naming the
   real parent function. The ECM2 band is pervasively fragmented because
   `FUN_80082EAA` is wrongly marked "does not return" (worklog 6H.15), and a
   fragment label is **not a stable identifier** — the same region was
   `FUN_80050980` in one Ghidra run and `FUN_800509A6` in the next (worklog
   6H.32b). Rows that pin a fragment to its parent are among the most valuable in
   the file.
4. **Prefer the true ret-to-ret span** in the `end` column over any Ghidra
   function boundary in this band.
5. **Re-run `DlcmApplySymbols.java` after any project rebuild**, and never
   hand-edit a name in the GUI expecting it to survive.

Seeded 2026-10-07 with 54 rows covering the torque and ECM2 safety path (the
limiter, all 16 reason-code detectors, the speed chain, creep, the IIR and LUT
helpers, the reaction and reset path). **It is deliberately partial** — 2894
functions are still unnamed, so an absent row means "not yet recorded", never
"not identified".

## Tooling guidance: prefer Ghidra over manual Python disassembly

**Running Ghidra (headless, via `analyzeHeadless.bat`) is effectively free** — local computer execution costs nothing, and the only token cost is generating the script and interpreting the output log. Where Ghidra and a hand-rolled Python disassembler can both do the job, **default to Ghidra**. Where Ghidra is helpful at all, **just run it autonomously without asking** — the cost profile is the same as running a Python scratchpad.

Practical implications for this investigation:
- For TriCore disassembly, function discovery, decompilation, control-flow graphs, jump-table analysis: use Ghidra with `tricore:LE:32:default`.
- For raw byte-pattern scans, statistics, shape-search across data: Python scratchpads are still fine (they're already written).
- **Do not use the `dlcm_analysis` Ghidra project.** It was built as `SuperH4:BE:32` with the modified Continental SLEIGH and its disassembly is meaningless (see the ISA correction above). Use `dlcm_tricore` instead — created 2026-09-19 by importing `coda_dlcm_prog.bin` at `0x80040000` under `tricore:LE:32:default`.
- Headless commands and conventions: see `tools-reference.md`.

### Ghidra's caller lists are wrong by default on this image — run `DlcmFixOrphanCode.java` first

*Recorded 2026-09-25.*

"Who calls this function?" returns an empty set for functions that run every task
cycle. `FUN_8006eb8c` — the brake-lamp-feedback module that raises DTC B2100 —
reported **zero callers** and was briefly written off as dead code. It is called
from `0x8007C2E2`, in the main periodic task, every cycle.

**The cause is not what it looks like.** The first diagnosis was that TriCore tail
calls (`j <function>` instead of `call`) were being recorded as jumps and so missed
by `Function.getCallingFunctions`, which filters on `RefType.isCall()`. That
diagnosis was **wrong**, and a script written to fix it added exactly one reference
to the entire image. Ghidra's TriCore language already classifies them correctly —
probing `0x8007C5FC`:

```
insn: j 0x8007cd6e
flowType: CALL_TERMINATOR   isCall=true  isJump=false
reference: -> 8007cd6e  type=UNCONDITIONAL_CALL  isCall=true
```

**The real cause is that the caller is code with no function around it.** Every way
of listing callers turns a reference into a *function*, through
`getFunctionContaining(callsite)`. Where the call site lies in a region the rebuild
never turned into a function, that mapping yields null and the caller silently
disappears. The reference is right there in the database; only its container is
missing.

`DlcmFixOrphanCode.java` repairs both directions, in the project database, once:

- any call/jump **destination** holding instructions but in no function gets one;
- any call **site** in no function: walk back to the previous terminator and create
  a function at the instruction after it.

It iterates to a fixed point and is idempotent. Applied to `dlcm_tricore` on
2026-09-25: **1692 → 2959 functions**, after which `FUN_8006eb8c` reports its
caller correctly.

**A region that was never disassembled is a separate, earlier step.**
`DlcmFixOrphanCode` cannot recover a call site that is not an instruction. For
`0x8007C2C6`–`0x8007C339` the bytes had to be disassembled explicitly first, with
`DlcmDisasmRange.java`. That script also **verifies alignment**, which matters
because TriCore instructions are 2 or 4 bytes and a stream started at the wrong
offset decodes plausible garbage: give it the address the stream must end at, and a
clean landing on a known function boundary is the proof the start was right.

**Corollary for `artifacts/call_target_scan.py`.** That Python linear sweep finds
call sites by decoding raw bytes, and it found the `call 0x8006EB8C` above — in a
region Ghidra had never disassembled, so the hit was unverified until the region
was decoded properly. Treat a hit as a lead to confirm, never as proof. Its **zero
counts mean nothing at all**: it decodes `CALL` (0x6D) and 16-bit `CALL` (0x5C)
only — not `J` (0x1D), `CALLA` or `CALLI` — so every tail-called function in the
I/O accessor band `0x8007C54C`–`0x8007C662` reports zero call sites while being
called normally.

**What the gap does and does not affect** (checked on the repaired project by
`reverse-it-e1`, 2026-09-25, not reasoned about). Orphaned code breaks *"who calls
this?"* and nothing else: `DlcmA0RefScan` iterates `listing.getInstructions()` and
`getReferencesTo` returns references regardless of whether the site sits in a
function, so instruction-level scans and reference enumeration were correct all
along. Re-run across the repair: buffer-region readers outside the accessor band
**0 both times**; signal accessor call sites **14 TX + 26 RX, identical**;
instruction count 101,070 → 101,099, the 29 added being exactly the periodic-task
region. So results derived before the fix are suspect only where they depend on a
caller list.

**The repair itself can create mid-function fragments — check before trusting a new
function.** `getFunctionContaining` is not a reliable "is this inside a function"
test here, because Ghidra's recorded *body* can be a fraction of the code a function
executes: `FUN_800803fa` has a 4-byte body while its decompilation runs through
`0x80080414`. Every address past `0x800803FE` therefore reported no container, and
the first version of `DlcmFixOrphanCode` created `FUN_80080400` in the middle of it —
a fragment that decompiles to nonsense (`*a0 = unaff_a13; FUN_800686d8();`) while
looking like a real function. The script now requires a candidate entry to be
preceded by a terminator or an unconditional jump, which rejects that case.

Two fragments were created in the accessor band and have been removed; the band is
back to the documented **120** getters, which is what made the damage there
measurable. **Elsewhere there is no such ground truth and an unknown number may
remain.** A report-only pass lists entries not preceded by a terminator, but it
over-flags badly — 831 under the loose test and 553 under a stricter
"falls through from another function" test, both including legitimate pre-existing
functions such as `FUN_80048d94` — so do **not** bulk-delete on it. Treat a
suspiciously tiny function, or one whose decompilation references `unaff_` registers,
as a probable fragment and check its predecessor.

## Open data-collection items

- ~~**Firmware version number from the scanner screen.**~~ Captured 2026-05-05: scanner shows **`1CI527_D003`** for the DLCM flash. This matches the part numbers visible in the binaries (`1CI527` / `1CI52710` PROG, `1CI315270D003` CAL header) but does **not** disambiguate which spec revision the firmware was built against. **Decision:** proceed under the assumption that the v4.2 spec applies; if the §10.7 architecture refuses to match the binary, fall back and re-attempt against the pre-Rev-25 spec (separate Zero Crossing Filter + Zero Torque Rate Limiter).

## Binary Provenance

| Item | Value |
|------|-------|
| Source log | `projects/coda/logs/flash/coda_dlcm_flash6.log` |
| Capture date | 2026-04-26 |
| Tool | Omitec scanner, BUSMASTER 500 kbps (Ixxat interface) |
| Manufacturer label | Continental **EMS9180** |
| PROG binary | `projects/coda/notes/dlcm/coda_dlcm_prog.bin` |
| CAL binary | `projects/coda/notes/dlcm/coda_dlcm_cal.bin` |
| Extractor script | `projects/coda/notes/artifacts/extract_dlcm_firmware.py` |

## UDS Flash Session Summary

- **Tester**: 0x7E0 (Omitec scanner, standard OBD-II address)
- **ECU**: 0x7E8 (DLCM, standard OBD-II response address)
- **Session**: DiagnosticSessionControl → Programming (0x02)
- **SecurityAccess**: Level 0x01/0x02 (differs from BMS 0x03/0x04 and gateway 0x03/0x04)
- **Observed pair**: seed `89 34 97 39` → key `3B ED 53 8A`
- **Pre-PROG erase**: RoutineControl `31 01 FF 00 02` — ~37 seconds
- **RequestDownload #1 (PROG)**: address `0x80040000`, size `0x1BFE00` (1,834,496 bytes)
- **TransferExit** (PROG complete)
- **Post-write verify**: RoutineControl `31 01 FF 01`
- **Pre-CAL erase**: RoutineControl `31 01 FF 00 03`
- **RequestDownload #2 (CAL)**: address `0xA0020000`, size `0x1C000` (114,688 bytes)
- **Max block length**: 255 bytes total, 252 bytes data payload

## Encryption Status

The DLCM firmware is **NOT encrypted** — plaintext, directly analyzable.

| Binary | Entropy | Assessment |
|--------|---------|------------|
| `coda_bms.bin` | 7.9992 bits | AES-encrypted, Ghidra blocked |
| `coda_dlcm_prog.bin` (active region) | ~6.0 bits | Plaintext SH-4 code |
| `coda_gateway.bin` | 4.95 bits | Plaintext ARM firmware |

Readable strings in the PROG region:

| Offset | String | Notes |
|--------|--------|-------|
| 0x000604 | `1CI527101CI527` | Part number fragment |
| 0x000624 | `1111CI3152701111CI315270UU` | Part number strings, padding |
| 0x000AF8 | `0123456789abcdef86` | Hex alphabet table |
| 0x001F98 | `REDYWAIT` | State machine strings |

CAL region starts with ASCII `CA1CI5271CI52700` — the `CA` prefix is likely short for CALibration, followed by the same part number string family seen in PROG.

## Architecture

**Infineon TriCore, little-endian.** Corrected 2026-09-19; this section previously
asserted Renesas SuperH (SH-4) big-endian.

| Setting | Value |
|---------|-------|
| Ghidra language | `tricore:LE:32:default` |
| PROG load address | `0x80040000` |
| Active code | `0x80040000`-`0x80095CB2` (~344 KB). The remaining 1.48 MB of the container is a single zero run — 83 % of the file. |
| Small-data base `A0` | **`0xD0009000`**, set at `0x800400B0` (`movh.a a0,#0xD001` + `lea a0,[a0]-0x7000`). DSPR data RAM. |
| Const small-data base `A1` | `0xA0028000`, set at `0x800400B8`. Uncached flash mirror, and *below* the PROG image — i.e. it points into the bootloader region, which we do not have. |
| Ghidra project (local) | `~/ghidra-projects/dlcm_tricore` |

Startup builds these at `0x80040000`-`0x80040200`: `A0` = `0xD0009000`, `A1` = `0xA0028000`,
plus `0xD0004000`, `0xD00009C0`, `0x80048000`, `0x80045144`, `0x80045219`. Enumerated by
scanning for `movh.a` + `lea` pairs — see "Address constants" below.

Resolved `A0`-relative addresses in use (SecurityAccess):

| Symbol | Offset | Absolute |
|---|---|---|
| per-level key constants, element `[1]` | `a0-0x4074` | `0xD0004F8C` (level 1, `0xCAF77776`) |
| element `[2]` | `a0-0x4070` | `0xD0004F90` (level 3, `0x9D89EA36`) |
| slot *before* the array (unrelated counter; level `7D` underflows onto it) | `a0-0x4078` | `0xD0004F88` |
| current seed | `a0-0x3708` | `0xD00058F8` |
| expected key | `a0-0x370C` | `0xD00058F4` |

These check out against independent references elsewhere in the image: other code builds
`0xD0004F80` and `0xD0004FFC` (bracketing the constants array) and `0x800440E0`-`0x800440F4`
holds a pointer table of `0xD00058F0`-`0xD00058F3` (bracketing the seed).

### Address constants

TriCore builds 32-bit addresses as `movh.a aX,#hi` + `lea aX,[aX]lo`, so absolute addresses
do not appear as literals and cannot be found by searching for them. Scanning for that
instruction pair recovers 3050 constructions at 1117 distinct addresses across the image
— that scan is the practical substitute for a symbol table, and it is what resolved `A0`.
Tooling: `artifacts/dlcm_image_encoding_probe.py`.

TriCore addresses globals as offsets from `A0`/`A1` rather than absolutely, so a
global's address is only meaningful once `A0` is known. This is why the
SecurityAccess key constants appear in the decompiler as `a0 - 0x4078 + index*4`
rather than as a literal address, and why locating them meant tracing `A0`'s
initialisation.

### Evidence

Counted over the active region only (the trailing zeros swamp whole-file statistics):

| Test | Result |
|---|---|
| TriCore `call` (op `0x6D`, disp24) | 4965 sites, **98.8 %** of targets land inside the active region. Control opcodes under the same decode score 0.6-5.1 %. |
| TriCore `ret` (`00 90`) | 2192 occurrences — a sensible return count for 344 KB of code. |
| SH-4 `rts`+`nop` (`000B 0009`), the standard SH-4 epilogue | **0** occurrences, in *any* byte order (identity, 16-bit swap, 32-bit reverse, 32-bit halfword swap). Bare `rts` occurs twice in 917k 16-bit slots. |
| Ghidra `tricore:LE:32:default` | Disassembles and decompiles the image cleanly on the first pass, with no patched processor spec. |

Tooling: `artifacts/dlcm_image_encoding_probe.py` (byte-order and idiom census),
`ghidra/scripts/DlcmSecurityAccess.java` (import and decompile).

### Why the SH-4 conclusion looked well-supported

All three original arguments are recorded below with what is wrong with each,
because two of them are the kind of reasoning that will recur.

**1. "Load addresses rule out every other MCU family."** The original argument was
that `0x80040000` (cached) and `0xA0020000` (uncached) are the SH-4 P1/P2
direct-mapped regions. TriCore has the *same* segment structure in the *same*
two nibbles — segment `8` is cached program flash, segment `A` is the uncached
mirror of the same physical flash, and `D` is data scratchpad RAM. The load
addresses are equally consistent with TriCore and rule out nothing. They were
right about what the addresses *mean*; the inference to a vendor was unsound.

**2. "cpu_rec confirmation."** This one matters most.
**`cpu_rec` cannot identify this image, because TriCore is not in its corpus.**
The corpus shipped in `artifacts/cpu_rec_tool/cpu_rec_corpus/` holds 76
architectures including SuperH, V850 and TMS320C6x, and **no TriCore** (verified
2026-09-19). A classifier that does not contain the right answer will always
return the nearest wrong one. The margin it returned was also noise: SuperH 3.80
against TMS320C6x 3.86 is a 1.6 % separation, and on two of the four chunks
SuperH did not win at all. Re-run 2026-09-19 on the active region, it reports
`None` for the whole region and `TMS320C6x` for the largest chunk.

> **Do not use `cpu_rec` as an architecture check on this firmware, and do not
> read a narrow win in it as confirmation on any firmware.** Absence from the
> corpus is invisible in the output.

**3. "Eliminated architectures."** ARM, ColdFire/68k and PowerPC were each
eliminated correctly, by searching for their call/return idioms. The method was
sound. TriCore was simply never a candidate, so it was never tested — and the
same idiom test applied to TriCore is what settled it today.

### Why the error was self-concealing

The wrong ISA did not fail loudly; it was made to fail quietly. Roughly half the
16-bit words in a TriCore stream are not valid SH-4, so disassembly stopped
constantly. Each stop was read as a Continental "variant opcode" and patched with
a NOP stub in a modified SLEIGH, which let the disassembler continue and produce
more output that looked superficially like code. **529 stubs is not a measure of
obfuscation; it is a measure of how wrong the decoder was.** The
"nested-delay-slot traps" attributed to Continental obfuscation were Ghidra
correctly applying SH-4 delay-slot semantics to a CPU that has no delay slots.
The `halt_unimplemented()` output blamed on gaps in Ghidra's SH-4 spec was the
decompiler reporting, accurately, that the bytes were not SH-4.

Two specific differences did the damage: SH-4 is fixed 16-bit while TriCore is
variable 16/32-bit with the length in bit 0 of the first byte, so a 32-bit TriCore
instruction reads as two unrelated SH-4 words (this is the recurring `6D FF` +
`xx F6` pattern — one `call`, seen twice); and SH-4 was configured big-endian
while TriCore is little-endian, which is the whole of the "mixed-endian image,
big-endian instructions with little-endian pointers" puzzle. Nothing was mixed.

### Generalisable lesson

An architecture guess that is wrong but *almost* works is more expensive than one
that obviously fails, because the workarounds that make it almost work also
suppress the signal that it is wrong. Before patching a processor spec to get
past undecodable bytes, run the cheap census that does not depend on the
decoder: count the call and return idioms, and check what fraction of relative
branch targets land inside the image. That test took minutes and separated the
two candidates by a factor of roughly fifty.

## Region Details

### PROG region

| Property | Value |
|----------|-------|
| Virtual address | `0x80040000` |
| Physical address | `0x00040000` |
| Declared size | 1,834,496 bytes (0x1BFE00) |
| Real data captured | 1,834,496 bytes (100%) |
| Active code/data | 0x000000–0x055CB2 (343 KB); rest is zero padding |
| Gaps | None |
| Blocks transferred | 7,280 |

### CAL region

| Property | Value |
|----------|-------|
| Virtual address | `0xA0020000` (write) / `0x80020000` (runtime) |
| Physical address | `0x00020000` |
| Declared size | 114,688 bytes (0x1C000) |
| Captured | 114,688 bytes (100%) |
| Active calibration data | 0x000000–0x00481C (18 KB); rest is zero padding |
| Gaps | None |
| Blocks transferred | 456 |
| Header | ASCII `CA1CI5271CI52700` at offset 0x000000 |

The CAL region is small (18 KB active) relative to the PROG region (343 KB active). It almost certainly contains calibration tables — fixed-point constants for things like pedal response curves, ramp rates, and regen levels — that are separate from the executable code in PROG. This separation is the target for tuning (Goal 2 below).

## Analysis Goals

### Goal 1: Ghidra initial analysis
Architecture confirmed — proceed to Ghidra (SuperH4:BE:32, load PROG at 0x80040000, CAL at 0x80020000). Priorities: locate the SH-4 exception vector table at 0x80040000, identify the reset entry point, and anchor auto-analysis to the code section.

### Goal 2: Throttle ramp and regen constant editing
**Investigate feasibility of flashing modified constants.** The CAL region (18 KB active) is the natural home for tunable parameters: throttle pedal smoothing ramp rates and off-throttle regen level. Hypothesis: these are stored as fixed-point constants in the CAL data section, separate from executable code.

Full workflow:
1. Load CAL in Ghidra at 0x80020000 and identify the data layout
2. Find ramp rate and regen constants (cross-reference from PROG code that reads them)
3. Edit desired values in the CAL binary
4. Recalculate the firmware integrity check (locate in PROG bootloader validation path)
5. Build a reflash tool: `python-can` + UDS session replicating the Omitec flow (SecurityAccess algorithm needed — collect more seed/key pairs, or decompile the Omitec tool)
6. Flash modified CAL binary, leaving PROG untouched

Key unknowns: (a) SecurityAccess level 0x01/0x02 key algorithm, (b) CRC algorithm and location, (c) whether the bootloader checks PROG-over-CAL cross-signatures.

#### SecurityAccess algorithm — seed/key pairs

> **See `dlcm-security-access.md`** for the dedicated analysis. Key findings
> (2026-07-21): the handshake is on **D CAN**, terminated by the **DLCM** (the
> GWM only bridges `0x7E0`/`0x7E8`); and a `CMP/EQ #SID` scan of PROG shows **no
> UDS/SecurityAccess handler in PROG** — the seed/key algorithm is in the
> **bootloader** (`<0x80040000`), which we do not have. So "decompile the Omitec"
> below is one option, but "dump + decompile the bootloader" is the other.

Extracted from all flash logs using `security_access_extract.py` (artifacts/). Three distinct sessions confirmed — seeds are truly random (ECU-generated). No simple single-transform algorithm found (not constant XOR, constant add, or any rotation).

| Log | Seed | Key | XOR |
|-----|------|-----|-----|
| flash2.log | `86 BD 07 60` | `C6 CC DA 14` | `40 71 DD 74` |
| flash5.log | `89 34 97 39` | `3B ED 53 8A` | `B2 D9 C4 B3` |
| flash6.log | `7C 87 6E 19` | `27 26 96 6F` | `5B A1 F8 76` |

Algorithm is likely a multiply + add + XOR or polynomial chain — needs decompilation of the Omitec keygen to crack, or more pairs + brute force. **Not required for the interposer path** (the interposer passes the Omitec's key through untouched).

#### Interposer reflash path (preferred approach)

Script: `projects/coda/notes/artifacts/dlcm_interposer.py`

A MITM script sitting between the Omitec and the DLCM on the CAN bus does **not** require knowing the SecurityAccess algorithm:

- SecurityAccess (0x27/0x67): pass through untouched — the Omitec computes the key, the ECU sees it unmodified
- TransferData (0x36) for the CAL region: intercept and swap in modified bytes from `coda_dlcm_cal_modified.bin`
- Everything else (RequestDownload 0x34, RoutineControl 0x31): pass through

**Hardware required:** Two CAN adapters (e.g. two Ixxat USB-to-CAN devices) physically bridging the Omitec CAN connection and the car's OBD-II port. The script uses `python-can` with `bustype="ixxat"`, channels 0 and 1.

**Post-write integrity check: NOT a blocker (2026-04-27)**

Investigated via `routine_control_dump.py` and `cal_crc_scan.py` (artifacts/).

The `0xFF01` verify routine is a **flash readability check, not a content CRC check**:
- Omitec sends `31 01 FF 01` with **no extra data** (no CRC supplied)
- ECU responds `71 01 FF 01 statusRecord=00 00 00 0C` — same constant `0x0C` status for both PROG verify and CAL verify despite completely different sizes; this is a hardware write-success code, not a content check
- CAL binary header (`0x0010–0x001F`, the natural checksum field location) contains all zeros
- CRC-32, sum32, sum16, XOR32 of the CAL active region are not found anywhere in the CAL binary

The interposer works without any CRC patching.

**Transfer-level validation: CAN hardware CRC only (2026-04-27)**

Investigated via `transfer_validation_check.py` (artifacts/).

There is no application-layer checksum at any point in the transfer protocol:
- **CAN frame level**: every frame carries a 15-bit hardware CRC enforced by the CAN controller silicon — completely transparent, handled in hardware, cannot be disabled. The application never sees frames that fail this check.
- **UDS TransferData (0x36)**: ECU ACKs each 252-byte block with exactly `76 BSN` — 2 bytes, no checksum, no data echo. The only thing validated at this layer is the block sequence number.
- **UDS TransferExit (0x37/0x77)**: both tester request and ECU response carry no extra bytes.

The interposer swaps content bytes inside valid CAN frames, so the hardware CRC is correct by construction. No additional integrity bypass is needed at any layer.

**Content-checksum re-verification on the complete capture (2026-07-02)**

Re-ran the "no content checksum" question with a stronger method on the gap-free `flash6.log`. Artifact: `artifacts/flash_session_analyze.py`.

- **Reconstructed PROG (0x80040000, 1,834,496 B) and CAL (0xA0020000, 114,688 B) from the TransferData stream — both byte-exact** vs `coda_dlcm_prog.bin` / `coda_dlcm_cal.bin`. Confirms flash6 is gap-free and the bins are authentic to the flashed image.
- Full reprogramming sequence captured: DiagSession 0x02 -> SecurityAccess (seed `7C876E19` / key `2726966F`, accepted) -> erase `31 01 FF00` (data `02`=PROG, `03`=CAL) -> RequestDownload (`dataFormatIdentifier=0x00` = no compression/encryption) -> TransferData (252-byte blocks) -> TransferExit -> verify `31 01 FF01` (no data; constant status `00 00 00 0C` for both regions). Only negative response in the whole session is NRC `0x78` (responsePending) during the ~37 s erase; no rejections.
- **Checksum hunt:** computed CRC32, adler32, sum16/32, XOR32, wordsum16, CRC16-CCITT, CRC16-XMODEM over CAL (whole / active `0x0-0x24900` / minus-header) and PROG, then searched (a) all 399 distinct 2- and 4-byte values across every non-TransferData UDS message (both endiannesses) and (b) the PROG and CAL binaries for the CAL's own 32-bit checksums. **Zero matches in either.**
- **Conclusion:** no application-layer content checksum/signature over the CAL is transmitted during flashing *or* stored for a boot-time comparison. Confirms and strengthens the 2026-04-27 findings. Residual (not brute-forceable): a custom-polynomial CRC or a cryptographic signature — but no signature-length data is transmitted anywhere in the session, and cryptographic CAL signing is uncommon for a 2012 Continental EMS. Low likelihood.

**Flash-proxy byte-targeting validated offline — no dongles (2026-07-02)**

Drove the real `FlashSession` (imported from `dlcm_flash_proxy.py`) over all 301,994 `flash6.log` frames in dry-run, cross-checked against an independent ground-truth walk of the CAL TransferData blocks. Artifact: `artifacts/flash_proxy_dryrun_validate.py`.

- Default patches `0xA0021532` / `0xA0021B6E` (runtime `0x80021532` / `0x80021B6E`) both currently hold `0x01` — the lash-minimum (index 5) of the two V-curve copies at `0x80021528` and `0x80021b64`.
- **Both methods agree exactly:** `0xA0021532` -> CAL TransferData block_seq `0x16` (block index 21), in-block offset 134 = CF#19 d[5]; `0xA0021B6E` -> block_seq `0x1C` (index 27), offset 218 = CF#31 d[5]. The proxy's fixed 252-byte-block base-address assumption holds (all blocks are 252 B except a final 28 B block, well past the targets).
- The proxy writes LE i16 `05 00` (value 1->5) at both cells and arms **only** for the CAL download (leaves PROG untouched). It reports 4 byte-writes = 2 real changes + 2 no-op high-byte (`00`->`00`) writes — expected for a 2-byte LE i16 patch, not a bug.
- **Conclusion:** the proxy flips exactly the two intended lash-minimum bytes, with correct block/offset math and endianness, verified against real captured traffic.

**Flash-readiness summary (2026-07-02):** the two flash-failure risks — a content checksum the patch would invalidate, and wrong-byte targeting — are both cleared offline. What remains is *efficacy only* (whether the `0x80021500`/`0x80021b50` V-curve is the active gradient LUT — medium confidence by elimination; the patch is the experiment that decides it) plus one operational item: a **proven CAL rollback** (re-flash stock CAL via the same Omitec flow, proxy off) before a first live attempt.

### Goal 3: State machine and fault enumeration
Locate the state table behind `REDYWAIT` strings and extract fault/error code definitions for DLCM-reported faults.

### Goal 4: CAN message dispatch
Identify DLCM CAN message construction — confirms byte layout for DLCM-originated signals not yet in the DBC.

---

## Findings

### Flash extraction history: flash5 vs flash6

The first extraction (flash5.log) produced a binary with a 9,576-byte zero-fill at binary offset 0x02A738 (address range 0x8006A738–0x8006CCA0) — a UDS transfer timeout that left those blocks missing and zero-padded. The affected region contains the CAN driver / motor state machine subroutine cluster. The flash6 extraction is 100% complete; `coda_dlcm_prog.bin` is the flash6 binary and has no gaps.

---

### Goal 1: Startup chain analysis (2026-04-26)

Analysis performed with Python SH-4 binary decoder (`dlcm_goals13_final.py`, output in `dlcm_goals13_final_out.txt`).

#### Header region — 0x80040000–0x8004002F (48 bytes, NOT code)

The first 48 bytes are ECU metadata, not a standard SH-4 exception vector table. The SH-4 normally has exception vectors at VBR+offset (set at runtime); the on-chip ROM handles the very first power-on sequence. The header contains what appear to be part number bytes (some ASCII-printable sequences visible in the raw dump), consistent with the strings found later in the binary.

#### Entry point

| Address | Word | Instruction | Notes |
|---------|------|-------------|-------|
| 0x80040030 | A00F | `BRA 0x80040052` | First executable instruction; immediately after 48-byte header |
| 0x80040032 | 9140 | `MOV.W @(0x800400B6),R1` | Delay slot — loads a 16-bit value into R1 before the BRA takes effect |

The BRA at 0x80040030 is the reset vector replacement. There is no standard exception vector table.

#### reset_entry — 0x80040052

```
0x80040052  1100  MOV.L R0,@(0x0,R1)     ; store R0 at [R1]
0x80040054  ...   [1-2 more short instr]
0x8004005A  A210  BRA 0x8004047E          ; jump to RAM init region
0x8004005C  0921  [delay slot]
0x80040066  BF10  BSR 0x8003FE8A         ; HAL call into bootloader
```

reset_entry is a tiny stub (≈10 bytes of code). Its only control-flow action is the unconditional BRA to 0x8004047E.

#### BSS / RAM region — 0x8004047E

The BRA target 0x8004047E is **zero-filled in the flash binary** (all 0x00 from 0x8004047E through at least 0x800404FD). Non-zero content resumes at 0x800404FE. This means PROG does not self-start from a cold flash — the bootloader must:

1. Initialize RAM at 0x8004047E with the actual startup code before jumping to PROG's entry
2. OR: the zero region is a .bss section that gets filled by a BSS-clear routine that runs before PROG, with the real startup at some higher address

Additional BRA targets at 0x800400E0→0x80040504 and 0x800400E6→0x8004050A (both just above the zero region) suggest that different startup paths converge on code starting at ~0x80040500.

#### Bootloader / HAL dependency

PROG is NOT self-contained. Twelve unique call targets in 0x8003Fxxx (below PROG base 0x80040000) indicate a pre-existing bootloader/HAL layer:

| Caller in PROG | HAL target | Type |
|----------------|-----------|------|
| 0x80040066 | 0x8003FE8A | BSR |
| 0x80040D48 | 0x8003FE8C | BSR |
| 0x80040AB0 | 0x8003FB26 | BSR |
| 0x8004064A | 0x8003FBA2 | BRA |
| 0x8004064C | 0x8003FBA4 | BRA |
| 0x8004056E | 0x8003FC84 | BRA |
| 0x8004057A | 0x8003FC90 | BRA |
| 0x80040582 | 0x8003FC98 | BRA |
| 0x80040B56 | 0x8003FE68 | BRA |
| 0x80040AA2 | 0x8003FEFC | BRA |
| 0x80040A72 | 0x8003FFCA | BRA |
| 0x80040A74 | 0x8003FFCC | BRA |

The HAL calls at 0x8003FC84/0x8003FC90/0x8003FC98 are made from thin one-instruction wrappers (BRA-only functions at 0x8004056E, 0x8004057A, 0x80040582). These look like the SH-4 BIOS / bootloader abstraction layer that handles low-level hardware (interrupt controller, clock, watchdog, CAN PHY init, etc.).

#### VBR setup

Two `LDC Rn,VBR` instructions configure the Vector Base Register:

| Address | Word | Instruction | Context |
|---------|------|-------------|---------|
| 0x8005D22A | 412E | `LDC R1,VBR` | Sets VBR = R1 (first configuration) |
| 0x8005E2AC | 492E | `LDC R9,VBR` | Sets VBR = R9 (second configuration — possibly re-arm after init) |

Both are in the 0x8005D000–0x8005F000 VBR region.

#### VBR value analysis (2026-04-26)

**VBR candidate: 0x8005DED8** (best from binary scan, `dlcm_vbr_scan.py`).

The value 0x8005DED8 appears exactly once in the binary as an LE32 word at 0x80042AB4. That table entry is consistent with a structured linked list (0x80042AC0→0x80042AB4 etc.). No `MOV.L @(d,PC),R1` instruction in the 0x8005C000–0x8005D22A range loads this value directly — R1 is set through an indirect path not traceable by linear binary analysis alone.

**Second VBR setup (LDC R9,VBR at 0x8005E2AC):**
The pool at 0x8005E2E0 contains LE32 = 0x003B0000, so R9 = 0x003B0000 and this instruction sets VBR = 0x003B0000. Handlers would be at 0x003B0100/0x003B0400/0x003B0600 — below the PROG base (0x80040000 in P1), pointing to the bootloader's exception handler area. This is called before BSR to 0x8005DC9C, which bridges to bootloader services at 0x8003Fxxx. Interpretation: this LDC temporarily restores the bootloader's VBR to allow safe bootloader calls, then the app VBR (0x8005DED8) is presumably restored afterward.

**Handler evidence supporting VBR = 0x8005DED8:**
- VBR+0x100 = 0x8005DFD8: begins with valid SH-4 MOV.L/store instructions before hitting an FP-range byte that Ghidra's Sleigh spec doesn't cover
- VBR+0x400 = 0x8005E2D8: `EXTU.B R12,R8` then `BSR 0x8005DCC6` (delay slot = 0x0000, possibly NOP-equivalent on this SH-4 variant)
- VBR+0x600 = 0x8005E4D8: `MOV.L @pool,R4` where pool LE32 = **0xA009EF54** (P2 uncached peripheral register — exactly what an interrupt handler reads to determine interrupt source); then `MAC.L @R5+,@R2+`, `TST #0x32,R0`, `ADDV R5,R2`, `BSR 0x8005DCC4`

All three handlers jump to common dispatch functions in 0x8005DC9C–0x8005DCC6.

**Ghidra clean rebuild (2026-04-26):**

`DlcmCleanSetup.java` replaced the aggressive sweep (5848 garbled 1–2 byte functions) with a proper recursive disassembly from 90 confirmed seed addresses. Result: 5848 functions removed → 90 functions created with correct flow-traced bodies.

`DlcmDisasmDump.java` then produced `dlcm_export/disasm_dump.txt` (clean disassembly for Goal 1, Goal 3, and the three VBR handler regions). Decompile output was limited by Ghidra SuperH Sleigh spec gaps: MAC.L (@Rm+,@Rn+), FMOV/FSRRA floating-point instructions, and ADDV/MULS.W are absent from Ghidra's SH-4 decoder, causing `halt_unimplemented()` in all three VBR handler decompiles.

**dlcm_goals13_final.py bug (fixed 2026-04-26):** The Python decoder was using `be32()` for MOV.L literal pool values; the correct byte order is `le32()` (consistent with the LE function pointer tables throughout the binary). Also fixed: incorrect GBR-immediate instruction encodings (TST/AND/XOR/OR vs the wrong mnemonics), and wrong MULS.W/MULU.W opcode masks (0x700E/F → 0x200E/F). Added: MAC.L, MAC.W, SHAD, SHLD decodings.

The VBR region (0x8005D000–0x8005F000) contains some of the largest functions in the binary (FUN_8005D95E ≥3172 bytes, FUN_8005E32E ≥3328 bytes, FUN_8005E45C ≥3120 bytes) — the interrupt dispatch chain. Goal 4 (CAN dispatch) traces from these handlers.

---

### Goal 3: REDYWAIT state machine (2026-04-26)

Analysis performed with `dlcm_goals13_final.py`. Supporting earlier work: `dlcm_goals13_prepass.py`, `dlcm_goals13_prepass2.py`, `dlcm_goals13_prepass3.py`, `dlcm_goals13_datatables.py`.

#### REDYWAIT is the only embedded state name

Scanning the entire 0x80041E00–0x80042300 state machine data region returns exactly one ASCII string: `"REDYWAIT"` at 0x80041F98. Other state names are not stored here — they may be numeric IDs, in a different memory region, or not embedded as strings at all.

#### REDYWAIT state descriptor struct — 0x80041F70–0x80041FA0 (48 bytes)

The struct is not referenced by pointer anywhere in the binary (no literal pool entry points to 0x80041F70). The state machine runner accesses it via the object graph at 0x80042030, not by string lookup.

Layout (little-endian 4-byte fields):

| Offset | LE value | Interpretation |
|--------|----------|----------------|
| +0x00 | 0x0000BFBF | type/flags word |
| +0x04 | 0xAFF1E404 | peripheral reg A (control) — P2 uncached on-chip |
| +0x08 | 0xAFF1EA1C | peripheral reg A (status) |
| +0x0C | 0x01000080 | bitmask / flags |
| +0x10 | 0xAFF1E60C | peripheral reg B (control) |
| +0x14 | 0xAFF1EB1C | peripheral reg B (status) |
| +0x18 | 0x01000080 | bitmask / flags (same as above) |
| +0x1C | 0xAFF1E814 | peripheral reg C (control) |
| +0x20 | 0xAFF1EC1C | peripheral reg C (status) |
| +0x24 | 0x01000080 | bitmask / flags (same) |
| +0x28 | "REDY" | state name byte 0-3 |
| +0x2C | "WAIT" | state name byte 4-7 |
| +0x30 | 0x00000000 | null terminator / padding |

The three peripheral register pairs (0xAFF1E404/0xAFF1EA1C, 0xAFF1E60C/0xAFF1EB1C, 0xAFF1E814/0xAFF1EC1C) are in the SH-4 P2 uncached area (0xAxxxxxxx → physical 0x2xxxxxxx). The address pattern (Exxx control, Ex+6xx status, spacing 0x208 between control regs and 0x100 between status regs) suggests 3 instances of the same peripheral type — likely SCIF serial channels or SCI+SCIF combination channels. The 0x01000080 mask has bits 24 and 7 set; bit 7 = 0x80 is a common "ready/idle" bit in many SH-4 peripherals.

**Hypothesis (unconfirmed):** REDYWAIT = "READY WAIT" = idle state waiting for activation. The three peripheral pairs control whether those channels are enabled or in a low-power mode. The 0xAFF1Exxx address range maps to SH-7751R SCU/serial interfaces in P2. Not yet cross-validated against SH-7751R datasheet.

#### LE function pointer dispatch table — 0x80041E00–0x80041EF3

Unusual: function pointers stored as **little-endian 32-bit words** on a big-endian SH-4. This is a deliberate compiler/linker choice for the dispatch table format.

| Section | Entry count | Pool address range | Target code range |
|---------|------------|-------------------|------------------|
| S1 | 46 entries | 0x80041E00–0x80041EB4 | 0x8007FFDE–0x80080C08 |
| NULL | separator | 0x80041EB8 | — |
| S2 | 14 entries | 0x80041EBC–0x80041EF0 | 0x80068BB2–0x80068C5C |

Section 1 targets cluster tightly in 0x8007F000–0x80080C00 — likely the main DLCM CAN message handler functions. Section 2 targets cluster in 0x80068BB0–0x80068C60 — a separate handler group (possibly a second physical CAN bus or a secondary state machine component).

#### State machine object graph — 0x80042030–0x800421FF

The table starts with a multi-level object graph. Key structural observations:

| Address | Field value | Interpretation |
|---------|------------|----------------|
| 0x80042030 | 0x00000100 | root object; type ID or vtable offset |
| 0x80042034 | 0x00000006 | event queue size or child count |
| 0x80042038 | 0x00000006 | (same) |
| 0x8004203C | 0x0000007D | timeout or count (125) |
| 0x80042054 | -> 0x800420D8 | handler function pointer |
| 0x8004205C | -> 0x80042030 | self-reference (parent/root pointer) |
| 0x80042074 | -> 0x80042132 | child object pointer |
| 0x8004207C | -> 0x80042030 | self-reference (second link-back) |
| 0x80042080 | -> 0x80042040 | sub-object A pointer |
| 0x80042084 | -> 0x80042060 | sub-object B pointer |
| 0x80042094 | -> 0x8008A82A | handler (init/tick?) |
| 0x800420A4 | -> 0x80042080 | sub-object C pointer |
| 0x800420A8 | -> 0x8008AC54 | handler |
| 0x800420AC | -> 0x800617B0 | handler |
| 0x800420B0 | -> 0x80061828 | handler |
| 0x800420B4 | -> 0x80061AFC | handler |
| 0x800420B8 | -> 0x80061BAC | handler |
| 0x800420BC | -> 0x80061A00 | handler |
| 0x800420C8 | -> 0x800619D4 | handler |
| 0x800420CC | -> 0x8008AD20 | handler |

The linked-list self-references (0x8004205C, 0x8004207C → 0x80042030) indicate a doubly-linked or tree-structured state container. Handler pointers in the 0x80061xxx range are callbacks for specific events (motor control, charge state, etc.); handlers in 0x8008Axxx are likely RTOS infrastructure (timer callbacks, task dispatchers).

Starting at +0x0A8 (0x800420D8), the table transitions to a packed repeated structure:
```
0x800420D8: 0x0000000F  (15)
0x800420DC: 0x000E0500
0x800420E0: 0x05000000
0x800420E4: 0x0000000D  (13)
0x800420E8: 0x000C0400
...
```
This looks like a priority queue or timer list — descending count fields (0xF=15, 0xD=13, 0xB=11, 0x9=9, 0x7=7, 0x5=5, 0x2=2) interleaved with packed register/command fields (0x0E0500 = channel 14 priority 5, etc.).

#### 12-byte event record table — 0x800421A0–0x80042218

9 records × 12 bytes = 108 bytes. Format: `(object_ptr_or_flags, handler_ptr, event_code_field)`.

| Rec | Address | field[0] | field[1] (handler) | field[2] |
|-----|---------|---------|-------------------|---------|
| 0 | 0x800421A0 | 0x00000001 | -> 0x8004218C | 0x00000000 |
| 1 | 0x800421AC | 0x00000000 | 0x00000000 | 0x00000001 |
| 2 | 0x800421B8 | -> 0x80042198 | -> 0x800422AE | 0x00520000 |
| 3 | 0x800421C4 | 0x00000101 | -> 0x800422AE | 0x00530001 |
| 4 | 0x800421D0 | 0x00000101 | -> 0x800422AE | 0x00250002 |
| 5 | 0x800421DC | 0x00000101 | -> 0x800422AE | 0x000D0003 |
| 6 | 0x800421E8 | 0x00000101 | -> 0x800422AE | 0x000E0004 |
| 7 | 0x800421F4 | 0x00000101 | -> 0x800422AE | 0x00560005 |
| 8 | 0x80042200 | 0x00000101 | -> 0x800422AE | 0x00380006 |

Records 2–8 all dispatch to 0x800422AE — a default/no-op handler stub. The high 16 bits of field[2] are candidate event/fault codes:

| High word | Decimal | Low word (index) |
|-----------|---------|-----------------|
| 0x0052 | 82 | 0 |
| 0x0053 | 83 | 1 |
| 0x0025 | 37 | 2 |
| 0x000D | 13 | 3 |
| 0x000E | 14 | 4 |
| 0x0056 | 86 | 5 |
| 0x0038 | 56 | 6 |

These are **hypothesized to be internal event IDs or DTC codes** — not yet cross-validated against known DLCM fault codes.

#### State machine callers (external to 0x80041E00–0x80042300)

Key callers identified by branch scan:

| Caller | Type | Target | Notes |
|--------|------|--------|-------|
| 0x8004136C | BRA | 0x80042036 | Primary state machine entry |
| 0x800416E8 | BSR | 0x80041FE0 | Calls into state machine area |
| 0x80042688 | BSR | 0x80041ED4 | Calls into dispatch table S2 |
| 0x8004270C | BSR | 0x8004209C | Calls into object table |
| 0x800427D0 | BSR | 0x800421C2 | Accesses 12-byte record table |
| 0x800427D4 | BSR | 0x800421CC | (same) |
| 0x800427E4 | BSR | 0x80042036 | State machine entry (second caller) |
| 0x800428AC | BSR | 0x80042106 | Accesses object table mid-point |
| 0x80042D1C | BSR | 0x800421D6 | |
| 0x80042E18 | BSR | 0x80041E9C | Dispatch table entry |
| 0x80042E40 | BSR | 0x80041EC4 | Dispatch table entry |
| 0x80043028 | BSR | 0x80042064 | |

The main state machine entry point is effectively **0x80042036** (called from 0x8004136C and 0x800427E4). The internal BRA chain from 0x800421B8 through 0x80042270 dispatches to individual entries in the dispatch table section 1 — these are the "handle event" paths that call the 0x8007Fxxx/0x80080xxx handlers.

---

### Goal 2: Torque request signal and anti-lash ramp characterization (2026-04-29)

Analysis performed with `dlcm_212_torque_corr.py` (torque encoding) and `dlcm_antilash_characterize.py` (ramp characterization), both in `notes/artifacts/`. Logs used: `frombonnydoon.log`, `driveafterfullycharged.log`, `codadriveslowturnonwithdefroster.log`, `codadriveslowturnonwithdefroster2.log` (418 zero-crossing events total, 59 fast-throttle events).

#### 0x212 TorqueRequest encoding

| Field | Value |
|-------|-------|
| Byte layout | **13-bit**: `(B4 & 0x1F) << 8 \| B5` — corrected 2026-09-19 from the publisher and the DID 8539 handler, both of which mask with `0x1F`. Previously recorded as 12-bit `(B4 & 0x0F)`; torque never reaches 12 bits in practice so the difference was invisible. |
| Zero torque | raw = 2000 (0x7D0) |
| Scale | ~0.244 Nm/count (OLS fit; unconfirmed — scale not in DBC) |
| Correlation | r = +0.999 vs 0x1C0 Torque across 4 drive logs |
| B4 upper nibble | Sub-frame counter / mux field — alternates between two values per sub-frame pair |
| B2 | Also sub-frame dependent; alternates with B4[7:4] |
| B0, B1, B3 | Constant zero in all logs |

Zero-torque throttle setpoint: approximately **21% pedal position** (throttle@crossing median 20–25% across all logs).

#### Anti-lash ramp structure

Analysis scripts: `dlcm_zero_crossing_ramp.py` (V-curve through lash zone), `dlcm_lash_exit_ramp.py` (post-lash table), `dlcm_drive_ramp.py` (Region 3), `dlcm_lash_crossing_graph.py` (timing visualization). All scripts in `notes/artifacts/`.

> **Clarification (2026-07-08) — the "8 cts/frame" figure and the §10.7 framing of this section.** The per-update step near zero is **not** a flat rate and "±8 cts/frame" is not a single rate limit. A raw re-run of `dlcm_zero_crossing_ramp.py` shows a **state-dependent V-curve in TrqLast**: ~16 cts/update deep in regen, narrowing to **exactly 8 at the zero crossing**, tightening to **~0–1** at the top of the lash zone (TrqLast ~= +33), then re-widening (1, 2, 3, 5, 7, 9 ...). The value **8 is the crossing-specific step only.** It reproduces at exactly 8 across independent events with different throttle rates (39 %/s and 70 %/s), and the shaping is **throttle-independent**: in a slow event the torque keeps stepping after the pedal stops moving; in a fast event the step *decreases* (16 -> 13 -> 8) while the pedal is still rising. So proximity to zero (TrqLast), not demand magnitude, sets the step. Torque updates every **~20 ms (~50 Hz)**; each value is repeated in two adjacent sub-frames (the B4-nibble mux), so "per frame" here means per 20 ms update. 8 cts/20 ms ~= 400 cts/s ~= 98 Nm/s at the unconfirmed 0.244 Nm/ct scale.
>
> **Attribution is a hypothesis, not a finding.** The observed profile is the *combined* output of the rate limiter and the §10.6 smoothing IIR, whose pipeline order is unconfirmed — an IIR can round a fixed-rate clamp into a curve. The Phase 0–2 descriptions below attribute the profile to reads of `gradientLimiterPositive_TrqLast[TrqLast]`; that attribution presupposes the modern §10.7 mechanism and is **under active re-examination**: is the near-zero limit a TrqLast-indexed table (modern §10.7 State Dependent Torque Gradient Limiter) or a fixed near-zero clamp plus a separate zero-crossing detector (the pre-Rev-2 Zero Torque Rate Limiter + Zero Crossing Filter)? The behavioral state-dependence is *consistent with* §10.7 but does not by itself prove the modern code topology. Code-level resolution is tracked in `dlcm-torque-limiter-code-trace.md`.

The total elapsed time from pedal press to maximum torque command is approximately **1 second**. The torque curve is smooth. The smooth appearance likely comes from the Torque Smoothing Filter (§10.6, a separate 3rd-order IIR on all torque requests) rather than from filtering inside the gradient limiter itself. The gradient limiter (§10.7) is a pure rate limiter — its smoothness is a product of the TrqLast-indexed table having small step sizes near zero, not a separate filter pole.

The empirical data below describes per-frame step sizes at the gradient limiter output (which is TorqueDemand to the motor before §10.6 smoothing, or after — the pipeline order relative to §10.6 is unconfirmed).

The Phases 0–2 below are all reading the **same `gradientLimiterPositive_TrqLast[TrqLast]` lookup table** at progressively different TrqLast values. There is no separate "gate" or "phase" boundary in the firmware — the table is continuous.

**Phase 0 — Positive path, TrqLast deep in regen (torque_signed << 0):**
- Positive gradient limit (from TrqLast table at deeply negative values): approximately **16 cts/frame**
- This is the positive path because TorqueDemand (throttle pressed) > TrqLast (still regen); the Relational Operator routes to `limit_positive_gradient`
- Decreases to **8 cts/frame** as TrqLast approaches −20 cts — the table tightening, not a gate

**Phase 1 — Positive path, TrqLast through the lash zone (−20 cts to +40 cts):**
- At TrqLast ≈ −20: **8 cts/frame**
- Decelerates as TrqLast climbs: approximately 7→5→5→3→3→2→2→1→1→0 cts/frame near TrqLast ≈ +33
- Re-accelerates: 1→2→2→3 cts/frame as TrqLast reaches +40
- ~14 update frames (one per 20 ms), total ~280 ms through this range
- Throttle-independent — determined entirely by TrqLast table, not by TorqueDemand magnitude

**Phase 2 — Positive path, TrqLast above lash zone (TrqLast > +40 cts):**
- Reads `gradientLimiterPositive_TrqLast[TrqLast]` at higher values. The accelerating ramp sequence is self-reinforcing: each frame TrqLast increases by approximately the current table value, so TrqLast climbs faster each step with no frame counter needed.
- Observed delta sequence: **3, 5, 7, 9, 12, 16** for normal throttle steps; **19, 24, 28, 33, 56** for large torque gaps (TrqLast still far below TorqueDemand at lash exit)
- Throttle-independent — identical sequence because TrqLast, not TorqueDemand, indexes the table

**Phase 3 — Gradient limit bypassed (steady state, far above lash zone):**
- Rate is variable and throttle-dependent; no fixed ramp observed
- Consistent with spec §10.7: "this gradient limit will be bypassed when the torque demand gets outside of the calibrated bounds"
- The bypass threshold is unconfirmed

**Regen side (negative gradient path):**
- Drive→regen crossing: torque decrements at **−8 cts/frame** = −97 Nm/s. Source not yet attributable — per the negative-path topology, this is `min(brake-switch constant or BrakePress LUT, gradientLimiterNegative_TrqLast[TrqLast])`, and which input is the binding limit at this operating point is unconfirmed.
- Passive regen fade (coasting to stop): +2 cts/frame ≈ +24 Nm/s — a different control path (uncharacterized).

#### CAN 0x212 transmit code site (2026-04-29)

Identified via binary search (`dlcm_find_212_tx.py`, artifacts/). Searched all occurrences of 0x0212 as a 16-bit BE pool word across the PROG binary. **Only one confirmed code reference** out of nine total hits:

| Address | Instruction | Notes |
|---------|-------------|-------|
| `0x8006d9e2` | `MOV.W @(0x8006da66,PC),R1 ; 0x0212` | Loads CAN ID 0x212 into R1 |
| `0x8006d9e4` | `?? 00F8` | Unrecognized opcode (valid per pattern, not in our decoder) |
| `0x8006d9e6` | `MOV.L @(0x8006dde4,PC),R9` | Loads a constant into R9 |
| `0x8006d9e8` | `BSR 0x8006ce4c` | Calls CAN send function |
| `0x8006d9ea` | `MOV.L R4,@(0x0,R15)` | Delay slot: stores R4 to stack |

The same pattern appears at `0x8006da04` for CAN ID **0x211**, confirming the call convention: R1 = CAN arbitration ID, BSR to a CAN send helper, delay slot pushes an argument. The `0x00F8` opcode appears in both sites — likely a valid but unrecognized SH-4 variant instruction (NOP-equivalent or flag operation).

**CAN send helper:** `0x8006ce4c` (`FUN_8006ce4c`). Also called from `0x8006cfcc` with the same target, confirming it is a reusable CAN transmit routine.

**Region status:** The address range `0x8006a738–0x8006cca0` was a zero-fill gap in the `flash5` capture (UDS timeout). The `flash6` binary (`coda_dlcm_prog.bin`) has these bytes correctly. The `DlcmCan212.java` Ghidra script seeds this region and was run 2026-05-02; see Ghidra findings below.

**Strategy:** The filter and per-phase rate schedule constants are both inside the function that calls `0x8006ce4c`. Trace backwards from `0x8006d9e2` via Ghidra decompile to find the torque computation logic, identify the rate constants, and locate the IIR filter coefficient(s).

#### Firmware search targets (Goal 2) — updated

| What to find | Status | Where / value |
|---|---|---|
| CAN 0x212 transmit site | **Confirmed** | `0x8006d9e2` — inline (fallthrough from D9E0, not a function entry) |
| Relational Operator branch | **Confirmed** | `0x8006d1ce`: `cmp/ge r0,r12` — T = (R12 >= R0) signed |
| §10.7 vs §10.6 ordering | **Confirmed** | §10.7 gradient limiter (D1B8-D224) runs FIRST; §10.6 IIR filter (D40A-D9DC) runs after |
| §10.7 positive gradient path | **Confirmed** | D1E8 falls through to D1EE-D206; calls `0x8006dbee` on positive gradient |
| §10.7 negative gradient path | **Confirmed** | D1E8 `bf D20A` taken — skips DBEEx call |
| `gradientLimiterPositive_TrqLast` table | Pending | Values at lash zone: 8, 7, 5, 5, 3, 3, 2, 2, 1, 1, 0 ... 3, 5, 7, 9, 12, 16 ... 56 (empirical); binary location TBD |
| `gradientLimiterPositive_VehSpd` table | Pending | Binary location TBD |
| `gradientLimiterNegative_TrqLast` table | Pending | Binary location TBD |
| `gradientLimiterNegative_BrakePress` table | Pending | Binary location TBD |
| `gradientLimiterNegative_BrkSwOn` constant | Pending | Unknown; binary location TBD |
| `gradientLimiterNegative_BrkSwOff` constant | Pending | Binary location TBD |
| Unit Delay (TrqLast) SRAM address | Pending | Written after gradient limit arithmetic in DBEEx region; exact address TBD |
| §10.6 IIR filter coefficient locations | Pending | D40A-D9DC contains ~30+ BSR calls to Cxxx/Dxxx/Exxx tap helpers; coefficients likely in CAL binary |

#### Ghidra DlcmCan212.java findings (2026-05-02)

Script: `%LOCALAPPDATA%\ghidra-projects\DlcmCan212.java`  
Output: `%LOCALAPPDATA%\ghidra-projects\dlcm_export\can212_analysis.txt`  
Analysis script (raw binary decoder): `projects/coda/notes/dlcm/artifacts/gradient_limiter_db.py`

**0x212 TX site is inline code, not a function entry.** Ghidra creates `FUN_8006d9e2` as a 30-byte function with no callers, but `0x8006d9e2` is reached by fallthrough from `0x8006d9e0` (`mac.l @r15+,@r2+`) — it is the last block of the large D29C-D9E2 computation chain, not a separate subroutine.

**Computation chain structure (D1B8 – D9E2, ~2 KB):**

```
D1B8  bsr 0x8006dbc0           ; load compare values (pre-Relational Operator)
D1C2  mov.l @(0x34,r14),r0     ; R0 = first compare value (post-BSR load)
...
D1CE  cmp/ge r0,r12            ; §10.7 Relational Operator: T = (R12 >= R0) signed
...
D1E8  bf 0x8006d20a            ; T=0 (R12 < R0, negative gradient) → branch to D20A
D1EE  extu.w r10,r0            ; positive gradient path: R0 = R10 & 0xFFFF
D206  bsr 0x8006dbee           ; positive gradient rate-limit computation
D20A: [join point]
D224  bra 0x8006d40a           ; both paths merge and jump to §10.6 IIR filter
...
D40A – D9DC  [§10.6 Torque Smoothing Filter — 30+ BSR calls to Cxxx/Dxxx/Exxx tap helpers]
D9DE – D9E2  [final filter step, then 0x212 CAN TX]
DA00 – DA0A  [0x211 TX site, falls through from D9E2]
```

**§10.7 precedes §10.6 in the firmware** — the gradient limiter comparison + path selection at D1CE-D224 runs before the long IIR filter tap computation at D40A-D9DC. This matches the Simulink diagram: TorqueDemand → §10.7 (rate limit) → §10.6 (IIR smooth) → TX.

**DBC0** (called before compare, `bsr DBC0` at D1BE): loads `@(0x34,r12)` into R0, then calls `0x8006e5cc`. After returning, D1C2 loads the compare value from `@(0x34,r14)` into R0. At D1CE `cmp/ge r0,r12`: **R0 is the gradient limit threshold** (result of E5CC table lookup) and **R12 is TrqLast** (the current state variable). T=1 if TrqLast >= threshold → positive gradient path; T=0 if TrqLast < threshold → negative path. *(Earlier note had R0/R12 reversed — corrected 2026-05-03.)*

**DBEEx** (positive gradient helper, called at D206): at `0x8006dbee` — seeded and decompiled 2026-05-03; see DB-region findings below.

**Branch summary:**
- `D1E8 bf D20A`: §10.7 gradient direction — negative gradient skips DBEEx  
- `D224 bra D40A`: §10.7 output feeds §10.6 IIR filter (D40A entry point)
- `D7B2 bra DBD4`: shortcut within IIR filter to DBD4 (IIR continuation)
- `D7F8 bra D9DE`: shortcut to final IIR filter step (skips ~484 bytes)
- `D852 bra DA38`: another IIR shortcut past D9E2

**IIR filter helpers pattern:** Each tap group = `mov.l pool,r15` (buffer ptr) + `bsr Cxxx` + `add #-0x10,r15` + `mov.l r0,@(0x40,GBR)` + `bsr Exxx`. The Cxxx functions (CB2A, CB3E, CB82, CB96, CBDA, CBEE, CC32, CC46, CCAA) and Dxxx functions (D076, D08A, D0CE, D0E2, D17E, D192) are the 1-2 tap coefficient helpers. The Exxx/DDxx functions (DD36, DD60, ..., E202, E262, E282, ..., E3B4, E3CC) are the paired accumulate helpers. Together these implement the §10.6 3rd-order IIR.

**Note on disassembly noise:** This firmware interleaves literal pool constants densely between instructions. The `D90F`, `D91F` `mov.l @(0x3c,PC),r9` patterns load pool constants; the 4-byte values at those pool locations appear as garbage instructions when decoded linearly. The actual valid instructions are those that read from known register contexts.

#### Ghidra DlcmCan212.java findings — DB-region (2026-05-03)

Seeds added: `DBC0=0x8006DBC0`, `DBEE=0x8006DBEE`, `DBD4=0x8006DBD4`, `DD36=0x8006DD36`. Dump extended to `0x8006DD80`. New decompile targets: DBC0, DBEE, DBD4.

**D1B8-D224 clean instruction sequence (confirmed from Ghidra listing):**

```
D1BC  62BD  extu.w r11,r2          ; R2 = R11 (zero-extended)
D1BE  B4FF  bsr 0x8006dbc0         ; → DBC0 (gradient compare loader)
D1C0  D90F  (delay) mov.l @pool,r9
D1C2  50ED  mov.l @(0x34,r14),r0   ; R0 = gradient limit threshold (from SRAM)
D1C4  14FF  mov.l r15,@(0x3c,r4)   ; [R4+0x3C] = R15
D1C8  5E14  mov.l @(0x10,r1),r14   ; R14 = [R1+0x10] (update frame ptr)
D1CE  3C03  cmp/ge r0,r12          ; T = (R12 >= R0); R12=TrqLast, R0=threshold
D1E8  8B0F  bf 0x8006d20a          ; T=0 → negative path (D20A)
D1EE  60AD  extu.w r10,r0          ; R0 = R10 zero-extended (positive path)
D204  64BD  extu.w r11,r4          ; R4 = R11 zero-extended
D206  B4F2  bsr 0x8006dbee         ; → DBEE (positive gradient computation)
D208  0090  (delay) nop
D224  A0F1  bra 0x8006d40a         ; → §10.6 IIR filter entry
```

**DBC0** (`FUN_8006dbc0`, 20 bytes, caller: D1BE):
- `DBC0: mov #-9, r0` — sets R0=-9 (immediately overwritten; likely pool data decoded as instruction)
- `DBC8: mov.l @(0x34,r12),r0` — loads [R12+0x34] into R0; R12 is a CAL/SRAM struct pointer at this point
- `DBCA: bsr 0x8006e5cc` — calls E5CC, the actual gradient limit table interpolation function
- `DBCE: mov.l @(0x34,r15),r0` — after E5CC: R0 = [R15+0x34]
- `DBD0: mov.l r15,@(0x3c,r4)` — stores R15 at [R4+0x3C]
- Body ends at DBD3 with no visible RTS — likely E5CC stores result into SRAM[R14+0x34] itself, which D1C2 then reads

**DBEE** (`FUN_8006dbee`, 18 bytes, caller: D206):
- Positive gradient path — called when TrqLast >= threshold
- `DBEE: cmp/eq r0,r11` — compare
- `DBF0: clrt` — clear T flag (the 0x0008 dual-use opcode)
- `DBF2: add #4,r14` — R14 += 4
- Contains `shld r12,r14` equivalent (shift left by R12) — likely scales TrqLast for table index
- Calls `0x8006e606` — another table interpolation function (E606, same `mac.w` kernel as E5CC)
- Body ends at DBF7; pool contamination prevents Ghidra from decoding past DBF6

**DBD4** (`FUN_8006dbd4`, 8 bytes, caller: D7B2 `bra DBD4`):
- `DBD4: mov.l @(0x20,r1),r14` — R14 = [R1+0x20]
- `DBD8: shld r12,r14` — shift R14 left by R12 count
- Only 2 clean instructions before pool gap; too short for Ghidra decompile

**E-region table interpolation functions:**
The functions at `E5CC`, `E606`, `E672`, `E686`, `E6CE` all share an identical repeating structure:
```
1420  mov.l r2,@(0x0,r4)   ; store R2 (table Y-ptr) at [R4]
420F  mac.w @r0+,@r2+       ; MACL += [R0]*[R2]; R0+=2, R2+=2
B4FF  bsr <next_stage>       ; call next stage
D90F  (delay) mov.l @pool,r9
36BF  addv r11,r6
09FF  mac.l @r15+,@r9+
C008  mov.b r0,@(0x8,GBR)  ; watchdog feed
```
This is a Continental fixed-point piecewise-linear interpolation kernel — `mac.w` advances through X- and Y-axis arrays simultaneously. The actual CAL table addresses are passed via registers (R0=X-ptr, R2=Y-ptr) — they are NOT hard-coded in E5CC/E606 but passed as arguments.

#### Ghidra DlcmCan212.java findings — E-region decompile (2026-05-03)

E5CC and E606 were seeded and decompiled in a third Ghidra run. Results:

**E5CC** (`FUN_8006e5cc`, 54 bytes, `0x8006e5cc-0x8006e601`):
- Caller: `0x8006dbca` inside FUN_8006dbc0 (confirmed from Ghidra cross-ref)
- 3 MAC.W iterations, each followed by BSR to EFD2/EFE4/EFF6 respectively
- Between iterations: `addv r11,r6` + `mac.l @r15+,@r9+` + watchdog
- Literal pool references (loaded via `mov.l @(disp,PC),r9` in delay slots): E610, E5E4(→E624), E5F8(→E634)
- At E610: bytes [C2 08 A2 0F] = instruction bytes, NOT a CAL pointer — Ghidra decodes this as `mov.l r0,@(0x20,GBR)` followed by gaps
- Decompile is invalid due to MAC register protocol; Ghidra cannot reconstruct the argument passing

**E606** (`FUN_8006e606`, 12 bytes, `0x8006e606-0x8006e611`):
- Caller: `0x8006dc1e` inside FUN_8006dc00 (not DBEE as earlier hypothesized)
- `C208: mov.l r0, @(0x20,GBR)` — confirmed: writes R0 to SRAM at GBR+0x20
- Decompile confirms: `*(undefined4 *)(in_GBR + 0x20) = in_r0`

**E672**: body = 1 byte — Ghidra failed to decode; `halt_baddata()` only.

**EFD2/EFE4/EFF6** (E5CC's BSR targets): Ghidra decoded only 2 bytes at EFD2 (`nop_8201`), then a separate function FUN_8006efd4 starts at EFD4. These likely involve a Continental-specific opcode (`0x8201`) that Ghidra's SH-4 processor module doesn't recognize. EFF6 decompile shows a `bsr 0x8006f842` into a higher-address helper.

#### PROG binary base address correction (2026-05-03)

Earlier analysis assumed PROG base = 0x80060000. Confirmed correct base is **0x80040000** by checking instruction bytes: file offset 0x2E5CC contains `0x1420` = `mov.l r2,@(0x0,r4)` matching the known Ghidra address 0x8006E5CC.

PROG binary spans: 0x80040000–0x801FFDFF (1,834,496 bytes = 0x1BFE00).

#### CAL access method — no literal addresses in application code (2026-05-03)

> ### ⚠ CORRECTED 2026-09-19 — the premise of this section is an artefact of the wrong ISA
>
> ### ⚠ EXTENDED 2026-09-25 — scalars ARE directly referenced, through A1
>
> The corrected statement below is right about *descriptors* and wrong as a general claim
> about calibration access. TriCore's second global address register is set once at startup:
>
> ```
> 0x800400B0   movh.a a0,#0xd001
> 0x800400B4   lea    a0,[a0]-0x7000      ->  A0 = 0xD0009000   (RAM small-data base)
> 0x800400B8   movh.a a1,#0xa003
> 0x800400BC   lea    a1,[a1]-0x8000      ->  A1 = 0xA0028000
> ```
>
> `A1` sits exactly at the top of the CAL region (`0xA0020000`–`0xA0028000`), so **every
> `[a1]`-relative load with a negative displacement names a calibration constant directly**,
> resolvable as `cal_addr = 0xA0028000 + disp`. There are **359 distinct CAL addresses**
> referenced that way. `ghidra/scripts/DlcmA1CalRefs.java` enumerates them with the stored
> value decoded as u8/u16/i16 beside every referencing instruction.
>
> So: LUT *tables* are reached through the descriptor blocks, as this section says, and are
> invisible to a code-address scan. Calibration *scalars* are reached through A1 and were
> invisible only because nothing had resolved A1. The two mechanisms coexist.
>
> Found 2026-09-25 while looking for a hysteresis threshold; `DlcmA0Base.java` prints every
> write to A0/A1, which is how the bases were recovered.

> "Zero CAL literals in the application code region" was guaranteed by the architecture, not
> a finding. **TriCore cannot encode a 32-bit immediate.** Every CAL address is built at
> runtime from two instruction fields:
>
> ```
> movh.a a4, #0xA002        ; high half
> lea    a4, [a4] 0x13FB    ; low half, sign-extended
> ```
>
> A byte search for `0x8002xxxx` / `0xA002xxxx` finds nothing and always would have, on any
> firmware for this core. The four "CAL literals" the table below reports are coincidental
> byte patterns, which is also why the 2026-07-02 note had to explain one of them away.
>
> Reconstructing the `movh.a`+`lea` pairs instead gives **273 CAL addresses referenced from
> 321 code sites** — tooling: `artifacts/cal_code_xref.py` (+ `.out.txt`). Two structural
> results fall straight out:
>
> - CAL is referenced exclusively through the **uncached** mirror `0xA0020000`, not the
>   cached `0x80020000` alias this file assumes elsewhere.
> - The dense block `0xA00212A0`-`0xA0021894` is ~200 two-byte scalars, each read from
>   exactly one code site — the main calibration parameter area.
>
> **Startup copy table** (found 2026-09-19 while testing a since-refuted hypothesis):
> `0x800933CC`, 76 records of `{dst, src, len}` on a 16-byte stride, copying 15,046 bytes
> from **PROG flash** to RAM. It sources **nothing from CAL** and contains no CAL pointers,
> so CAL is not shadowed into RAM at init. It independently confirms the SecurityAccess RAM
> layout to the byte.
>
> What remains true from the original section: the gradient-limiter tables are **not**
> reached by a statically resolvable direct reference, while neighbours in the same bank
> are. The mechanism by which they *are* reached is still not traced — see
> `dlcm-torque-limiter-code-trace.md`, "The indirection wall", for why address-scanning
> cannot answer it here.


Searched the entire PROG binary for embedded 0x8002xxxx constants (CAL address range). Result: **zero CAL literals in the application code region (0x8006xxxx)**. Only 4 exist in the entire binary, all in init/OS code:

| PROG address | CAL address | CAL content (LE u16) |
|---|---|---|
| 0x80041A0C | 0x80021400 | [3000,4000,5000,6000,7500,9000,10000,...] — unidentified monotone sequence |
| 0x800452C8 | 0x800241C2 | [0,25700,4096,1,...] — config block |
| 0x8005FFD4 | 0x80023BF0 | [26876,26876,0,...] — structured data |
| 0x800932EC | 0x800200C0 | [0,0,0,...] — zero region |

**Conclusion:** all gradient limiter CAL access is through SRAM pointers initialized by the init code at 0x8004xxxx. The DBC0 instruction `mov.l @(0x34,r12),r0` reads a CAL table pointer from SRAM — R12 points to a module parameter block that was populated by the init code at startup. To find the CAL table addresses, the init code at 0x8004xxxx (specifically the code near 0x80041A0C that reads CAL 0x80021400) must be analyzed.

> **SUPERSEDED (2026-07-02) — see "Off-by-8 resolved" section below.** The table row `0x80041A0C -> 0x80021400` above and the tail of this conclusion are wrong. `0x80041A0C` does **not** hold a pointer to `0x80021400`. Those bytes `80 02 14 00` are little-endian data `0x00140280` = the u16 pair `(640, 20)` — the `+0x30` field of a 52-byte descriptor record, structurally identical to the same field in 23 sibling records. It only reads as a CAL pointer when misinterpreted big-endian. Nothing in PROG references `0x80021400`. The `mov.l @(0x34,r12),r0` instruction IS real (BE `0x50cd`), but R12 points to a runtime RAM struct, not this init table.

#### CAL table inventory — 0x0001/0x8003 format (2026-05-03)

Scanning CAL 0x80020400–0x80021000 for `[0x0001, 0x8003, count-1]` headers found 8 tables, all n=6:

| # | Header addr | X-axis (BE u16) | Y-axis (LE u16, 11 values) | Notes |
|---|---|---|---|---|
| 1 | 0x800205AA | [10,25,**20480**,40,60,65] | [0,48,96,144,192,256,352,480,640,960,1600] | Anomalous X[2]=0x5000 |
| 2 | 0x800205D6 | [10,25,40,50,60,65] | same | Standard kph axis |
| 3 | 0x80020602 | [10,25,40,50,60,65] | same + [0,800,600,400,200] appended | Extra data after Y |
| 4 | 0x80020642 | [10,25,40,50,60,65] | [0] (1 word — immediately followed by table 5) | No Y-axis |
| 5 | 0x80020656 | [10,25,40,50,60,65] | same as #2 | Standard |
| 6 | 0x80020682 | [10,25,40,50,60,65] | [0,48,...,480,**960**,1600] (Y[8]=960 not 640) | Slightly different Y |
| 7 | 0x800206AE | [10,25,40,50,60,65] | same as #3 | Extra data |
| 8 | 0x800206EE | [10,25,40,50,60,65] | [800,1497,2000,3000,3000,3000,...] | Very different Y-axis |

The Y-axis [0,48,96,144,192,256,352,480,640,960,1600] appears in most tables (11 LE u16 values for a 6-point X-axis). The 11 vs 6 count mismatch suggests either: two stacked tables sharing this header format, or a Y-axis with 11 breakpoints for a different (possibly torque-based) X-axis whose header is stored separately.

Table 8's Y-axis [800,1497,2000,3000,...] is distinctly different and may represent a different parameter type (RPM limits, filter coefficients, etc.).

#### Spec cross-reference — State Dependent Torque Gradient Limiter (2026-05-02)

DLCM Functional Requirements §10.7 names this function **State Dependent Torque Gradient Limiter** and describes its purpose as "to manage driveline lash near zero torque and during torque reversals." This is the anti-lash function we characterized empirically above.

**Revision history note (from spec changelog):** The spec we have is **DLCM Functional Requirements V4.2, Revision 4.2, dated 11 June 2012**. Revision 25 of its changelog deleted the Zero Crossing Filter and Zero Torque Rate Limiter sections and replaced them with the Torque Smoothing Filter (§10.6) and the State Dependent Torque Gradient Limiter (§10.7).

**Firmware-to-spec correspondence is unconfirmed.** Scanner reports `1CI527_D003` (captured 2026-05-05), matching the binary part numbers `1CI527` / `1CI52710` (PROG), `1CI315270D003` (CAL header). None of these strings map directly to a spec revision. The empirical Phase 1 V-curve through zero is *consistent* with a single TrqLast-indexed LUT (post-Rev-25 / v4.2-style §10.7 behavior) rather than a separate ZCF + rate limiter, but does not prove the firmware was built against spec v4.2 specifically. **Working assumption:** §10.7 architecture applies; if the hunt cannot make sense against §10.7, fall back and re-attempt against the pre-Rev-25 spec (separate Zero Crossing Filter + Zero Torque Rate Limiter).

> **RESOLVED (2026-07-08) — working assumption confirmed: the firmware implements the modern §10.7, not the old scheme.** Behavioral discrimination on three drive logs shows the torque rate limit is **vehicle-speed-dependent** with a clean `min(VehSpd-limb, TrqLast-limb)` structure: the accelerating per-update rate collapses from ~50 cts/update near standstill to ~1–3 cts/update at high speed, flat across all TrqLast bands at high speed, and survives a demand-controlled confound check. The old torque-only Zero Torque Rate Limiter structurally cannot produce a speed-dependent cap, so it is ruled out. The empirical near-zero V-curve documented above is the **TrqLast limb** of that `min()`; a co-equal **VehSpd limb** dominates at speed and was never isolated by the low-speed lash-zone characterization (hence the "single TrqLast-indexed LUT" read above is incomplete — it is at least two limbs). This resolution is **behavioral**; the instruction-level §10.7 topology claims in these notes (the "Firmware search targets" table's *Confirmed* rows for the D1CE Relational Operator and the positive/negative limbs) should be read as **structure-consistent but operand-unverified** — the region is literal-pool-contaminated and neither disassembly nor Ghidra decompile cleanly extracts the limb/`min` bindings. The CAL-table hunt's "strong shape evidence, zero discoverable code reference" wall reflects the §10.7 LUTs living in **runtime RAM** (per the 2026-07-02 off-by-8 / R13 up-trace), **not** the firmware being the old scheme. Full write-up, evidence tables, and confidence levels: **`dlcm-torque-limiter-code-trace.md`**. Repro: `artifacts/torque_limiter_scheme_test.py`.

**Simulink flow chart:** see `dlcm-torque-flow.md`.

The `TrqLast` state-dependency in `gradientLimiterPositive_TrqLast` is the mechanism producing the empirically observed tight per-frame limits near zero torque (Phase 1 plateau behavior, ~8 cts/frame then decelerating to ~1 cts/frame through the lash zone).

#### Candidate CAL LUT addresses — shape-search (HYPOTHESIS, 2026-05-05)

Scratchpads: `artifacts/trqlast_v_curve_shape_search.py` (full-binary V-shape sweep) and `artifacts/trqlast_lut_xref.py` (region structure + PROG xref). Outputs alongside.

**Scope reminder.** The two binaries we have (`coda_dlcm_cal.bin`, `coda_dlcm_prog.bin`) are both flash-resident. We do **not** have RAM (runtime state — never captured) or EEPROM (a separate chip storing VIN, key codes, etc — not part of the DLCM flash). Anything with two copies in this data is two flash-resident copies, not "RAM vs EEPROM" or "active vs shadow."

**The empirical Phase 1 V-curve has a strong shape match in two flash locations:**

| Address | Y values (i16 LE, 8 elements) |
|---|---|
| `0x80021528` | `[62, 35, 15, 10, 10, 1, 20, 40]` |
| `0x80021b64` | `[62, 35, 15, 10, 10, 1, 20, 40]` (identical bytes) |

**Why this is plausible (the Y-data identification):**
1. **Shape match.** Monotone-decreasing → plateau (`10,10`) → minimum (`1`) → asymmetric rise — the same V-shape as the empirical Phase 1 curve through zero. Absolute values are ~4× empirical, consistent with a Q-format / per-second rate scaled by dt downstream.
2. **Surrounding structure looks like a 1-D LUT** (header + clip values + monotone X-axis + Y-axis); see structure dumps below.

**Region-structure findings (HYPOTHESIS):**

Region @ 0x80021500 — clean canonical 1-D LUT layout (header → clips → X → Y):

```
0x80021500  00 01 00 28 80 39 00 00     header / magic (contains 0x8039 type marker)
0x80021508  14 00 14 00 e8 03 e8 03     [20, 20, 1000, 1000]              ? clip
0x80021510  e8 03 00 00 44 fd a8 fd     [1000, 0, -700, -600]             ? clip cont.
0x80021518  b0 ff ba ff 00 00 50 00     [-80, -70, 0, 80,                 X axis
0x80021520  c8 00 90 01 20 03 b8 0b      200, 400, 800, 3000]              (asymmetric, dense near 0)
0x80021528  3e 00 23 00 0f 00 0a 00     [62, 35, 15, 10,                  Y axis V-curve
0x80021530  0a 00 01 00 14 00 28 00      10, 1, 20, 40]
```

Region @ 0x80021b50 — different layout, with **multiple 1-D LUTs grouped back-to-back**:

```
0x80021b58  [-256, -128, 128, 256]                           ? small X axis
0x80021b62  0x8039 type marker
0x80021b64  [62, 35, 15, 10, 10, 1, 20, 40]                  Y axis (same V-curve as 0x80021528)
0x80021b78  [-700, -600, -80, -70, 0, 80, 200, 400, 800, 3000]   X axis (after Y here)
0x80021b88  [-4, -4, -15, -15, -20, -25, -30, -40, -40, -40]    Y axis: monotone-descending into negatives
0x80021ba0  [0, 80, 160, 320, 480, 640, 800, 960]            third X axis (smaller breakpoints)
```

**Why the two V-curve copies exist (UNRESOLVED).** Plausible explanations, none confirmed:
- The 0x80021500 region and the 0x80021b50 region configure two separate gradient limiters (e.g. one called from one operating mode / code path, one from another) that happen to share the same Y calibration in this build.
- Build/toolchain inlined the same calibration table at two sites for two different consumers.

**Symmetric driving feel (HYPOTHESIS).** Driver impression is that the torque gradient feels symmetrical between positive and negative TrqLast directions. This would be consistent with positive and negative `TrqLast` LUTs being calibrated to the same Y values — but **the two V-curve copies above are NOT the pos/neg pair** (see next item).

**Negative-side LUT candidate at 0x80021b88 (HYPOTHESIS).** The sequence `[-4, -4, -15, -15, -20, -25, -30, -40, -40, -40]` (i16 LE, 10 elements) is monotone-descending into negatives, exactly the expected shape of `gradientLimiterNegative_TrqLast` (a negative rate limit, more negative as TrqLast grows). It shares the X-axis at 0x80021b78 with the positive Y at 0x80021b64. So a more probable mapping is:
- `gradientLimiterPositive_TrqLast` Y data = the V-curve (at 0x80021528 and/or 0x80021b64)
- `gradientLimiterNegative_TrqLast` Y data = the descending-negative sequence at 0x80021b88

The "symmetric driving feel" then has to be explained by the matched magnitude/shape between these two LUTs (max-magnitude ~40 cts/frame on both sides, flat plateaus) rather than by literal byte identity.

**Other notable shape-search hits (for later reference):**

| Address | Width / endianness | Values | Note |
|---|---|---|---|
| `0x800215d6` | i16 LE, 7 elements | `[40, 40, 40, 18, 8, 1, 45]` | Second V-shape inside the 0x80021500 region. Possibly a third LUT (candidate: `gradientLimiterPositive_VehSpd` or `gradientLimiterNegative_BrakePress`). |
| `0x80021ba0` | i16 LE, 8 elements | `[0, 80, 160, 320, 480, 640, 800, 960]` | Third X-axis in the 0x80021b50 bank. All-positive monotone increasing — fits a VehSpd or BrakePress axis. |
| `0x800218e1` | u8/i8, 9 elements | `[20, 2, 3, 4, 5, 6, 7, 20, 20]` | Asymmetric, looks more linear-ramp-with-clamp than V-curve; lower confidence. |
| `0x80024500` region | u8/i8 hits | various `[X, 0, 0, 0, ..., Y]` | Inside region with lots of `00 00 00` filler — likely code/string data, deprioritized. |

**`0x8039` type marker (HYPOTHESIS).** The 16-bit word `0x8039` appears immediately before both V-curve copies (at 0x80021502 and 0x80021b62). The `artifacts/trqlast_lut_marker_and_xref.py` enumeration confirms only **2 BE occurrences in the entire 112KB CAL** (and 0 LE), both at `0x8039 0x0000` followed by recognizable LUT data. Extreme rarity is consistent with a structure-type marker — but §10.7 names four LUTs and we only see two markers, so either only some §10.7 LUTs use this marker type, or the marker isn't the §10.7 family at all.

**PROG cross-reference: failed.** Two scratchpads (`trqlast_lut_xref.py`, `trqlast_lut_marker_and_xref.py`) hunted for the candidate LUT addresses in PROG and found:
- Zero full 32-bit literal-pool entries (BE or LE, aligned or unaligned).
- Zero adjacent (`0x8002`, candidate-offset) 16-bit literal pairs — rules out the "build pointer from two adjacent halves" pattern.
- Zero BE 16-bit literal references for the most distinctive offsets (`0x1528`, `0x1538`, `0x1b50`, `0x1b60`, `0x1b88`, `0x1ba0`).
- High-count BE hits exist for non-distinctive offsets (`0x1500` = 118, `0x1508` = 20) but those are most plausibly random byte pairs, not real references.

**Confidence is now LOW** based on direct address xref. Three remaining possibilities:
1. **Access via the token-threaded bytecode VM** Sonnet's earlier work flagged in the C800-D200 region. The VM token format is unknown to us, so a SH-4-literal search wouldn't find anything.
2. **Access via base+small-displacement.** A base register pre-loaded with the LUT structure address would let SH-4 `MOV.L @(disp,Rn),Rm` access the whole structure with a 4-bit displacement embedded in each instruction word — invisible to a 16-bit literal search.
3. **The shape match is coincidence.** These two flash regions happen to contain V-shape and descending sequences but aren't the §10.7 LUTs.

**Do NOT edit any bytes** until a code-side trace confirms one of the candidate addresses is actually loaded by the gradient limiter path.

#### Pointer-endianness correction and broader CAL-pointer inventory (2026-05-05)

Scratchpads: `artifacts/cal_pointer_inventory.py` (BE, original), `artifacts/cal_pointer_inventory_le.py` (LE, corrected), `artifacts/config_table_reader_hunt.py`, `artifacts/cal_0x21400_inspect.py`.

**Endianness fact:** CAL data is provably **little-endian** — the X-axis `[-80, -70, 0, 80, 200, 400, 800, 3000]` at `0x80021518` is monotone in LE only. SH-4 instructions are universally BE (16-bit IFU fetch). Therefore the SH-4 must be running in **LE data mode**, and 32-bit pointer literals in PROG literal pools are stored LE.

**Scan comparison:**
- Aligned **LE** 32-bit pointers from PROG into PROG range: **1953** (sanity check — most function pointers/literals)
- Aligned **BE** 32-bit pointers from PROG into PROG range: **59**

The 33× ratio confirms LE is correct. The earlier BE scan that reported "7 CAL pointers including 0x80021400" was a misinterpretation — those bytes `80 02 14 00` are actually LE `0x00140280` (not a valid pointer).

**Corrected LE result:** 83 LE pointers from PROG into the CAL range, but they cluster in the **second half of CAL (0x80030000-0x8003c000)**. The most-referenced bucket is `0x80033000-0x800330ff` with 21 hits. **Zero LE pointers to any candidate LUT address** (0x80021400, 0x80021500, 0x80021b50, etc.).

**This invalidates the V-curve LUT hypothesis at 0x80021500 and 0x80021b50.** Those regions sit in the unreferenced first half of CAL — consistent with **stale or legacy calibration data, not the active gradient limiter LUTs**. The real LUTs are most likely in the 0x80030000+ region we haven't searched yet.

**Other PROG-side observations (unchanged by the endianness correction):**
- **Zero `LDC Rn,GBR` instructions** in PROG — GBR is set up outside this binary (boot ROM or secondary loader) and never reloaded inside PROG.
- **48 `STC GBR,Rn`** instructions — GBR IS read.
- **~5000 GBR-relative load/store ops** — bulk of small-scalar CAL access goes through GBR + 8-bit disp.

#### Correction-to-the-correction: 0x80030000+ is RAM, not active CAL (2026-05-05)

Scratchpads: `artifacts/lut_hunt_active_region.py`, `artifacts/cal_data_extent.py`, `artifacts/region_0x23300_hunt.py`.

The previous claim that "the active LUTs are in 0x80030000+" was wrong. Direct inspection of CAL `0x80030000-0x8003c000` shows **the entire region is all zeros** in the flash dump. That's the **RAM region** in the binary (zeroed because RAM isn't pre-initialized in flash); the 83 LE pointers from PROG that land there are pointers to runtime working storage (variables, buffers, state) — **not** pointers to LUTs.

**Real CAL data extent** (only ~10.5% of the 112 KB binary):

| Region | Size | Contents |
|---|---|---|
| 0x80020000-0x80020100 | 256 B | Header / config block |
| 0x80020300-0x80020900 | 1.5 KB | Configuration data |
| **0x80021100-0x80022400** | **4.9 KB** | Contains LUT-A (0x80021500), LUT-B (0x80021b50), the 0x80021400 multi-LUT region, and the V-curves catalogued above |
| **0x80023300-0x80024400** | **4.3 KB** | Different feature — see below |
| 0x80024500-0x80024900 | 1 KB | Smaller data block |
| 0x80024900-0x8003c000 | 0 | Zero-initialized RAM region in the flash image |

**The 0x80023300-0x80024400 region is NOT the §10.7 LUTs.** Investigation shows:
- Zero V-shape candidates in i16 LE
- Zero `0x8039` markers
- Zero LE pointer references from PROG
- Highly structured but in a different style — repeating 4-tuples like `[25700, X, 256, 0]` (~150 records at 0x80023fb0-0x800242ff), and earlier `[800, 700, 150, -150, ...]` clusters that look like per-phase setpoints. Reads as a different firmware feature (possibly a fixed-format command/setpoint table or VM token stream) — out of scope for this gradient-limiter hunt.

**The 0x80021500 / 0x80021b50 V-curve hypothesis is now strengthened by elimination:**
1. It's the only region in CAL that exhibits both V-shape data AND a candidate type marker (`0x8039`).
2. The 0x80030000+ "active region" lead was a RAM-image artifact.
3. The 0x80023300+ region is structured but architecturally different and lacks LUT-shape evidence.
4. The remaining unsearched non-zero regions (256 B header, 1.5 KB at 0x80020300, 1 KB at 0x80024500) are too small to hold the four §10.7 LUTs.

**The reason no PROG pointer literal references the LUTs directly is most likely one of:**
- Access via the **token-threaded bytecode VM** Sonnet's earlier work flagged (the VM's token format is unknown, so a SH-4-literal search wouldn't find token operands).
- Access via a base register **set up by boot/loader code outside this PROG binary** (consistent with the zero `LDC Rn,GBR` count and the 5000+ GBR-relative ops).

**Confidence:** 0x80021500 / 0x80021b50 / 0x80021400 as the §10.7 gradient-limiter LUT location is **medium-high by elimination**, but with **no direct code-side proof yet**.

**Edit-target candidates (HYPOTHESIS) for tightening lash response:** the cluster `[15, 10, 10, 1, 20]` at offsets 0x152c-0x1535 (and the matching cluster at 0x80021b68-0x80021b71) are the bytes the positive limiter would read when `TrqLast` is in the lash zone, IF this hypothesis holds. **Do NOT edit until either (a) the bytecode VM is decoded and confirms which CAL addresses the gradient limiter loads from, or (b) a writable test ECU is available for empirical patch-and-observe testing.**

#### Bytecode VM hypothesis disproved (2026-05-05)

Ghidra script: `%LOCALAPPDATA%/ghidra-projects/DlcmBytecodeProbe.java`. Output: `%LOCALAPPDATA%/ghidra-projects/dlcm_export/bytecode_probe.txt`.

The earlier Sonnet finding — that "0x8006C000-0x8006D200 is a token-threaded bytecode VM" and "BSRF dispatch sites at 0x8006E7B0 / 0x8006E8A6" are the dispatcher core — was **incorrect**. Ghidra disassembly + decompile shows:

- **0x8006C000-0x8006D200 is mostly zero padding** (72% zero bytes, matching the 74% baseline of known SH-4 code — i.e. normal). Real content starts only at 0x8006CCAA and reads as plain SH-4 with FMUL, MAC.L, BSR, fmov — looks like a single floating-point / DSP filter function, NOT a token interpreter.
- **0x8006E7B0** decompiles as code that packs the SH-4 SR bits (T/S/IMASK/Q/M/FD/BL/RB/MD positions match exactly) into a 32-bit word and saves FR15/XD14 floating-point state — i.e. **an interrupt handler / context-save routine**, not a dispatcher.
- No tight load-token / increment / computed-jump dispatcher pattern was found anywhere in the suspected regions.

**Implication:** the DLCM firmware is **plain SH-4 code throughout**, with Continental variant opcodes interspersed (the user-modified SLEIGH treats variants as no-ops). There is no custom VM to decode.

**Why no PROG pointer references the candidate LUTs (revised):** code accesses the LUTs via **base register + small displacement**, where the base is loaded into a register at a call site we haven't traced yet (the previous straight-line forward-trace died at BSR instructions because we didn't follow the BSR targets into the actual function bodies).

#### Gradient-limiter call-chain trace — exhaustive negative result (2026-05-05)

Tools used:
- `%LOCALAPPDATA%/ghidra-projects/DlcmGradientCallChain.java` — recursive Ghidra decompile from 5 gradient-limiter entry points, depth 6, 72 functions visited. Decompile output partially corrupted by the no-op'd Continental opcodes — Ghidra mislabels executable code in the literal-pool gaps as "global variables." Output: `dlcm_export/gradient_call_chain.txt`.
- `artifacts/gradient_movl_pc_loads.py` — pure-Python disassembly that doesn't depend on SLEIGH semantics. Walks every byte in the gradient-limiter call tree (depth 4, 910 functions visited), finds every `MOV.L @(disp,PC),Rn` instruction (0xDnnn opcode), computes each literal's address, and reports its 32-bit LE/BE value. Output: `artifacts/gradient_movl_pc_loads.out.txt`.

**Findings:**
- 1596 distinct LE literal values are loaded via MOV.L PC-relative across the 910-function call tree.
- **ZERO of those literals point into the candidate CAL data range (0x80020000-0x80024900).** Same result for BE.
- The Ghidra decompile pseudocode references like `iRam8006d90c`, `sRam8006da80` etc. are **mislabeled** — those addresses are actually instruction bytes interpreted by the decompiler as "global variables" because the no-op'd Continental opcodes confuse data-flow analysis. The actual values at those PROG addresses are SH-4 instruction bytes, not data pointers.

**Conclusion:** the gradient-limiter code path **does not load any 32-bit literal pointing into the candidate CAL LUT region** via any code path reachable in 4 call levels from the entry points.

**This means one of:**
1. **GBR-relative access** — GBR is set externally (boot ROM / secondary loader, not in this PROG), points to one of the candidate LUT regions, and individual LUT fields are accessed via 8-bit displacements in 0xC0xx-0xC6xx instructions (~5000 such ops in PROG, all using GBR's fixed value).
2. **The V-curves at 0x80021500/0x80021b50/0x80021400 are NOT the gradient limiter LUTs** — they're calibration data for some other vehicle subsystem.

Static analysis of these two binaries alone cannot distinguish (1) from (2). To break the impasse we need one of:
- **Boot ROM / secondary loader binaries** (where GBR is set) — would tell us what GBR is.
- **Live ECU access** to read GBR at runtime.
- **Empirical patch-and-observe** on a writable test ECU (preferably with a secondary already-flashed unit as a recovery option in case of brick).

#### Evidence summary as of 2026-05-05 — current best guess

**Best guess:** the V-curves at `0x80021528` and `0x80021b64` are the `gradientLimiterPositive_TrqLast` LUT data, and the descending sequence at `0x80021b88` is the `gradientLimiterNegative_TrqLast` LUT data, accessed by code via GBR-relative loads where GBR is configured outside this PROG binary.

**Confidence: medium.** Strong shape evidence + strong elimination evidence + arithmetic/opcode concentration in the right call tree, but **zero direct code-side proof** that any code reads from these specific addresses.

#### Off-by-8 resolved: the "0x80021400 pointer at 0x80041A0C" is a big-endian misread of a little-endian data field (2026-07-02)

Scratchpad: `artifacts/descriptor_offby8_trace.py`.

Re-examined the single most load-bearing claim of the code-side analysis — that DBC0's `mov.l @(0x34,r12),r0` leads to CAL `0x80021400` (the table row and conclusion in "CAL access method — no literal addresses in application code", 2026-05-03). **It does not.** Three findings, all from the raw binary:

**1. The 0x80041800 region is a 24-record descriptor array — 0x34 (52) bytes per record, little-endian.** Records begin with a `<type> ff 01 01` marker (`type` in {0x04,0x05,0x06,0x07,0x08}) at a clean 0x34 stride from 0x80041808 to 0x80041d16. Every record has the same column layout (offsets relative to the marker):

| off | field | example |
|---|---|---|
| +0x00 | type/flags `<t> ff 01 01` | 0x08 |
| +0x04 | count/enable (0 or 1) | 1 |
| +0x08 | **LE PROG pointer**, steps ~+0x2A/record | 0x800676ee |
| +0x0C | **LE PROG pointer** into a 0x80041F00 table, +2/record | 0x80041f18 |
| +0x10 | small int | 2 |
| +0x18 | **LE PROG pointer** into a 0x80067AD8 table, +6/record | 0x80067afc |
| +0x24 | u16 pair (symmetric limits?) | (200,200) |
| +0x2C | u16 scalar | 1372 |
| +0x30 | u16 pair | (640,20) |

Endianness is decisive: read little-endian, **48 fields are valid PROG pointers and 0 are CAL pointers**; read big-endian, only 2 PROG and 1 CAL (the phantom). This confirms the 2026-05-05 endianness fact (BE instructions / LE data) and extends it to the PROG descriptor tables. The three pointer columns (+0x08, +0x0C, +0x18) each step by a fixed amount per record, i.e. they index parallel companion tables — the hallmark of a signal/task descriptor array, not a LUT-pointer table.

**2. `0x80021400` is not a pointer — it is the +0x30 data field `(640, 20)`.** In the record at 0x800419dc, the +0x30 field holds LE `0x00140280` = u16 pair `(640, 20)`, bytes `80 02 14 00`. Read big-endian those bytes are `0x80021400`, which coincidentally lands on the V-curve region — the entire basis of the "pointer." But +0x30 is a **data column**: across all 24 records it holds `(608,20)`, `(704,20)`, `(672,200)`, `(768,4)`, `(832,4)`, `(1152,5)`, `(960,0)`, `(832,4)`… Our record's low half is `0x0280`, the single value whose raw bytes happen to form a plausible CAL address under BE. It is the only such coincidence in the table, and there are **zero** little-endian pointers into `0x80021xxx` anywhere in it.

**3. The "off-by-8" dissolves.** The field is at record offset **+0x30**, not +0x3C. The "+0x3C" (which set up the code-reads-+0x34 vs pointer-at-+0x3C paradox) came from drawing the record boundary 8 bytes before the marker (base 0x800419d0 instead of 0x800419dc) — the framing ambiguity was itself the artifact of forcing a pointer to appear. Either way the offset is moot: the field is data, so there is nothing for the code's +0x34 to be "off from."

**What IS confirmed on the code side:** DBC8 `mov.l @(0x34,r12),r0` is real — the bytes are `50 cd` = BE `0x50cd`, a genuine instruction (verified alongside the documented D1B8 sequence `62bd b4ff d90f 50ed 14ff`, all of which decode only as BE; the known anchor `0x1420` at E5CC is likewise BE). So R12 is a live struct pointer and `[R12+0x34]` genuinely is E5CC's input. It just isn't this init table: at a 0x34 stride, `[record_base+0x34]` lands on the next record's marker, and no field in the table is a CAL pointer. **R12 points at a runtime RAM structure** (native BE order, populated by init code) — tracing R12's provenance is the valid, still-untried next step, now free of the 0x80021400 red herring.

**Net effect on prior conclusions:**
- **Confirms** (2026-05-05): no PROG literal/pointer references the candidate LUTs; endianness is BE-code / LE-data.
- **Corrects** (2026-05-03 "CAL access method"): `0x80041A0C` does not point to `0x80021400`; the DBC0/R12 path does not read this init table. The row should be struck from the "4 CAL literals" table (it leaves 3 genuine ones: 0x800452C8, 0x8005FFD4, 0x800932EC).
- **Resolves** the second-pass "off-by-8 crux" and the H6 "Inconsistent Endianness Problem" loose end — both were symptoms of this one BE-misread data field.
- **Leaves** the V-curve-LUT-by-elimination hypothesis (medium confidence) standing, but **removes the phantom code-side support** that specifically propped up 0x80021400. The unresolved access mechanism is now R12-struct-relative (DBC0 path) and/or GBR-relative (E606 path).

#### R12 backtrace: gradient tables are reached via a RAM context pointer (R13), double-indirected (2026-07-02)

Scratchpad: `artifacts/r12_backtrace.py`. Ground truth: Ghidra recursive-descent listing `dlcm_export/can212_analysis.txt` (linear-sweep disassembly is NOT reliable in this region — the dense literal pools alias to plausible opcodes; every claim below is from Ghidra's listing, which separates code from pool data).

Backtraced R12, the pointer DBC8 dereferences (`mov.l @(0x34,r12),r0`). Findings:

**R12 and R13 are both inherited base pointers — neither is written on the path into DBC0.** The DBC0 caller is `FUN_8006d192` (0x8006d192-0x8006d228). On its execution path `d192 -> d1be (bsr DBC0) -> d1ce (cmp/ge r0,r12) -> d224 (bra d40a)`, R12 is *read* (compared at D1CE, dereferenced inside DBC0) but never *written*. Same for R13. Both are callee-saved (SH-4 preserves R8-R14) and threaded in from an ancestor — Ghidra models R13 as `unaff_r13` and passes it as an implicit argument through the whole gradient/filter family (FUN_8006d0ce, d0e2, d076, d08a, ...).

**The module-wide idiom identifies what these base pointers are.** `[R13+0x34]` is loaded into a scratch register right before each interpolation/filter stage, at 13 Ghidra-confirmed sites:

| sites | instruction |
|---|---|
| 0x8006cda4 / cdc2 / cddc | `mov.l @(0x34,r13),r6` |
| 0x8006ce40 / ce5e | `mov.l @(0x34,r13),r8` |
| 0x8006ceb6 / ced0 | `mov.l @(0x34,r13),r10` |
| 0x8006d2b2 / d2d0 / d2ea | `mov.l @(0x34,r13),r12` |
| 0x8006d33a / d358 / d372 | `mov.l @(0x34,r13),r14` |

So `[R13+0x34]` is the **module data-block pointer**, and R13 is the **module context**. R12 is set to `[R13+0x34]` by an ancestor before the gradient compare (the `mov.l @(0x34,r13),r12` idiom at d2b2/d2d0/d2ea is the same load on other paths). The E5CC input is therefore a **double RAM indirection**:

```
R13 (module context, inherited)  --[+0x34]-->  MDB (module data block)  --[+0x34]-->  E5CC X-input / table ptr
```

**Reached from the 0x212 CAN-TX handler.** FUN_8006d192 is called at 0x8006d9ae, inside the 0x212 periodic-TX dispatcher (0x8006d8fa+). R12/R13 are inherited into the dispatcher too (read via `cmp/hi r0,r12`, never written there), so they are established still higher, at the task entry.

**Why this matters:**
- It gives a **concrete mechanism** for the 2026-05-05 "no PROG literal references the LUTs" result: the table addresses are stored in **RAM struct fields** (`[[R13+0x34]+0x34]` and neighbors) populated at init, not as code literals — so a literal search could never have found them, regardless of endianness.
- The gradient tables the code actually reads therefore live at **RAM addresses not present in our flash dump** (PROG+CAL only); their values are set at runtime.
- It **redirects the hunt to a tractable static target**: trace R13 up to the task-init/scheduler that sets it, then find the init code that populates `[R13+0x34]` and `[[R13+0x34]+0x34]`. This is more concrete than the prior "GBR set in boot ROM, impasse" framing — R13 is set inside PROG's own task setup. (It remains possible R13 itself derives from GBR at the task entry; the up-trace will show which.)

**Hypothesis (unconfirmed):** R13 points at a per-module RAM context (OSEK/AUTOSAR-style runnable context); `+0x34` is its parameter/data-block pointer; the gradient X/Y tables are either RAM copies of CAL data or base-relative views established at init. Confirming requires the R13 up-trace (next step) or a live-ECU RAM read.

#### R13 up-trace (Ghidra): R13 is OS/context-managed; the tables are runtime RAM, not statically resolvable (2026-07-02)

Ghidra script `DlcmR13Trace.java` -> `dlcm_export/r13_trace.txt`; scratchpad cross-check `artifacts/dispatch_table_search.py`. Ran a headless pass: a program-wide scan of Ghidra's *defined* instructions (code only) for real R13/R12 writes, a caller-chain walk up from the gradient code, and decompiles of every function that writes R13.

1. **R13/R12 are never cleanly set in the gradient module.** Across 0x8006cd00-0x8006da40, R13 is touched only by pool-alias byte-loads (`mov.b @r0,r13`), never a pointer write. Both are inherited — confirms the backtrace above.

2. **The call chain tops out at OS-dispatched functions.** `FUN_8006d192` (gradient) <- `FUN_8006d96e` (0x212 TX) <- `FUN_8006cf68`; and `FUN_8006d29c` <- `FUN_8006da00`. The top functions `FUN_8006cf68` / `FUN_8006da00` have **no analyzed callers and appear zero times as function pointers anywhere in PROG** (verified by raw pointer search). They are entered by the firmware's OS/dispatch layer, not by a static call or a flash pointer table.

3. **The only clean R13 *pointer* writes in the entire binary are in VBR / interrupt-context handlers.** e.g. the VBR+0x400 handler `FUN_8005e2d8` does `mov.l @(0x20,r1),r13` — restoring R13 from a context frame at `[R1+0x20]`. (The other 730-odd "r13 writers" the scan reported are `mov.w @r0,r13` byte-loads in mis-disassembled data regions at 0x80054000-0x80056000 — noise.) A context-frame restore is the signature of R13 as an **OS-managed, per-task context base**, not a value produced by any code literal. (Note: this shows R13 is context-managed in general; it does not prove this specific handler dispatches the gradient task.)

4. **The 0x80041800 descriptor table is a registration table for a 0x80067xxx handler band.** Its +0x08 and +0x18 pointer columns reference functions at 0x80067568.., 0x80067ad8.., and those addresses appear **only** inside the descriptor table. That handler band is saturated with the no-op'd Continental variant opcodes, so its dataflow can't be followed cleanly with the current SLEIGH.

**Conclusion — the gradient tables are not statically resolvable from the flash images.** R13 is established by the OS/context-switch layer (VBR dispatch + task/context control blocks), so E5CC's input `[[R13+0x34]+0x34]` is a doubly-indirected RAM pointer whose value only exists at runtime. That RAM is not in our PROG+CAL dump, and the OS code that would populate it is obscured by unresolved variant opcodes. This upgrades the earlier "GBR set in boot ROM, impasse" to a precise diagnosis: **R13 = OS task-context base; the gradient tables live in per-task RAM.**

**Realistic paths to the actual table address (in order):**
1. **Live-ECU RAM walk** — read R13 (or GBR) at runtime and follow R13 -> +0x34 -> +0x34 to the table addresses. Definitive; needs ECU access.
2. **Empirical patch-and-observe** on the by-elimination CAL V-curve candidate (0x80021500 / 0x80021b50): flash a widened lash-zone curve and observe behaviour. Needs a writable + recoverable ECU.
3. **Deeper static OS trace** — low payoff until the Continental variant opcodes are modelled in SLEIGH (they currently no-op, hiding the dispatch/init dataflow).

##### Positive evidence (supporting)

| Evidence | Strength |
|---|---|
| **Shape match** — `[62, 35, 15, 10, 10, 1, 20, 40]` is a textbook V-curve: monotone decrease → plateau → minimum → asymmetric rise, matching the empirical Phase 1 lash-zone behavior (16, 8, 5, 3, 3, 0, 2, 3 cts/frame). Absolute values are ~4× empirical, consistent with a Q-format / per-second rate scaled by dt. | High |
| **Replication** — the exact same 16-byte payload exists at two non-adjacent CAL addresses (`0x80021528` and `0x80021b64`). Identical bytes at two addresses suggest two distinct LUT registrations sharing one calibration. | Medium-high |
| **`0x8039` type marker** — only **2 occurrences** in the entire 112 KB CAL, both immediately preceding the two V-curve copies. Extreme rarity is consistent with a structure-type marker for "1-D LUT, this variant." | Medium |
| **Matched negative-Y candidate** — `[-4, -4, -15, -15, -20, -25, -30, -40, -40, -40]` appears at TWO addresses (`0x800214c0` and `0x80021b88`) and reads as a `gradientLimiterNegative_TrqLast` candidate (negative rate limit, more negative as TrqLast grows). The pos/neg max-magnitudes (~40 vs ~40) match the user's "feels symmetrical" driving observation. | Medium |
| **Surrounding structure** — full LUT-shaped layout around the V-curves: `0x8039` marker → clip values → asymmetric monotone X-axis (`[-80, -70, 0, 80, 200, 400, 800, 3000]`) → Y-axis V-curve. Reads as a complete 1-D T(u) calibration block. | Medium |
| **Structure-self-describing** — at `0x80021502` BE u16 = `0x0028` = 40, and the V-curve Y axis starts exactly 40 bytes later at `0x80021528`. Reads as a "Y-axis offset" header field. | Low-medium |
| **MAC.L instruction concentration in call tree: 7.67× the PROG baseline** (45.89 / 1000 insns vs 5.99 / 1000). MAC.L is the canonical instruction for linear interpolation (`Y[i] + (input - X[i]) * slope`) and IIR filtering. The gradient-limiter call tree is doing heavy multiply-accumulate work — exactly what you'd expect if real interpolation happens here. | Medium-high |
| **Continental variant opcodes concentrated 6-14×** in call tree vs PROG: `0x03f0` (14.1×), `0x0340` (12.5×), `0x0640` (12.0×), `0x0440` (10.8×), `0x0211` (6.4×), `0x09a0` (5.5×). Domain-specific ops the SLEIGH treats as no-ops. **Decode of the top four (2026-05-06)**: `0x03f0` is a BSR delay-slot instruction (function-call ABI). `0x0340`, `0x0440`, `0x0640` are sibling state-machine dispatch variants — all three share the same `add #-89,r4; cmp/eq rN,r11; <variant>` precondition pattern (frame-offset setup + state-vs-marker test), with `r11` as the dispatch selector. They appear to be the BT/BF/store-and-branch trio of a Continental-extended conditional. **None of the top four are LUT lookups.** This RULES OUT the "LUT-lookup is a single variant opcode" sub-hypothesis for the most-concentrated variants, but indirectly *strengthens* the broader hypothesis: if all the dense Continental ops are dispatch/control-flow scaffolding, then the 7.67× MAC.L concentration is literally `MAC.L` doing the multiply-accumulate, which means table data must be reachable by ordinary SH-4 loads (compatible with CAL-resident data). | Low (was Medium-low) |

##### Negative evidence (against)

| Evidence | Strength |
|---|---|
| **Zero PROG literal-pool references** to the candidate addresses — not as 32-bit pointers (BE or LE), not as adjacent 16-bit halves, not as 16-bit GBR displacements. Exhaustive call-tree walk visited 910 functions and found 1596 distinct literals, none in 0x80020000-0x80024900. | High |
| **Ghidra decompile didn't surface any clear LUT-load pattern** in the gradient-limiter call tree (e.g. interpolation code with a base register pointing into our range). Decompile was partially corrupted by no-op'd Continental opcodes, lowering the value of this signal. | Low-medium |

##### Absence of expected evidence

| Expected if hypothesis is right | What we observe |
|---|---|
| At least one PROG literal storing the LUT base address | Zero |
| GBR setup in PROG (`LDC Rm,GBR` instruction) | Zero |
| Some way to derive how the LUTs are addressed | Neither |

**Big asterisk:** GBR setup happening in boot ROM (outside this binary) would explain ALL of these absences. We have no way to confirm or refute that without the boot ROM.

##### Eliminated alternatives

| Alternative | Why eliminated |
|---|---|
| LUTs at 0x80021500 are referenced via 32-bit literal pool | Exhaustive scan: 0 hits (BE and LE) |
| LUTs are in the "active region" 0x80030000+ (where 83 LE pointers go) | That region is **all zeros** in the flash dump — it's the RAM area, populated at runtime |
| LUTs are in the second non-zero data block 0x80023300-0x80024400 | Investigated: zero V-shape candidates, zero `0x8039` markers, zero pointer references; structurally different (looks like a fixed-format table for a different feature) |
| Bytecode VM hides the access pattern (Sonnet's earlier hypothesis) | Disproved 2026-05-05: 0x8006C000-0x8006D200 is plain SH-4 code, not bytecode. The supposed BSRF "dispatcher" is an interrupt handler / context-save routine |

#### Open items (2026-05-05)

- Static analysis via direct address xref is exhausted. The loop-bound search (`artifacts/loop_bound_lut_signature.py`) found NO loops with bound 8 or 10 in the call tree — but the MAC.L concentration (`artifacts/mac_concentration_and_variant_opcodes.py`) showed 7.67× over PROG baseline, and several Continental variant opcodes are concentrated 6-14×. The top-four variants (`0x03f0`, `0x0340`, `0x0440`, `0x0640`) were decoded by usage-pattern (`artifacts/decode_variant_opcodes.py`, output in `decode_variant_opcodes.out.txt`): `0x03f0` is a BSR delay-slot ABI instruction; `0x0340`/`0x0440`/`0x0640` are sibling members of a Continental conditional-dispatch family (shared `add #-89,r4; cmp/eq rN,r11; <variant>` precondition, `r11` as state selector). **None are LUT lookups**, ruling out the "lookup-as-variant-opcode" sub-hypothesis for the dense variants. Remaining angles: the lookup is inlined as standard SH-4 (compare-branch chain or `MAC.L`-driven interpolation rather than a loop), OR access really is GBR-relative.
- **2026-05-06 plan re-run** (`artifacts/lut_hunt_active_region.py`, output `.out.txt`): Re-ran V-shape hunt restricted to `0x80030000-0x8003c000` per a stale plan that hypothesized this was the active LUT region. Confirmed empty: Phase 1 dump of `0x80033000-0x800330ff` (most-pointed bucket, 21 hits) is **all zeros**; Phase 2 V-shape sweep across `0x80030000-0x8003c000` returned **0 candidates** across all 6 width/endianness interpretations; Phase 3 dumped 36 unique LE-pointer targets in this region — every single one is a zero-filled run. This re-confirms the existing eliminated-alternative row: 77 PROG pointers landing in `0x80030000+` are pointers to **runtime-initialized RAM struct fields** (the addresses are real but flash-dump bytes are zero because RAM gets initialized at boot from elsewhere). The plan is fully closed out as a dead end.
- Live-test the V-curve hypothesis on a writable test ECU. Smallest definitive experiment: bump the `0x01` byte at `0x80021530+2` (LE; the lash-zone minimum) up to e.g. `0x05` and observe whether the empirical lash-zone Phase 1 minimum changes from ~0 cts/frame to ~5 cts/frame. If no change, the LUT hypothesis is wrong.
- If a boot ROM / secondary-loader image becomes available, re-run the GBR-load search in that image to determine GBR's value.

#### 2026-05-06 overnight session — major re-direction (the V-curve hypothesis is in serious trouble; a stronger candidate has emerged)

This session ran four exhaustive scans and produced one hard pivot. Sequence:

1. **MAC.L call-site forensics** (`artifacts/mac_callsite_forensics.py/.out.txt`) — for each of 11,825 MAC.L sites in the gradient-limiter call tree, traced backward up to 80 instructions to find the source of Rm/Rn pointer registers. Across 23,650 register traces: 9,881 (42%) inherited from caller; 4,988 (21%) loaded via PC-pool literal — and **0 of those 4,988 PC-pool literals point into CAL**. 3,757 (16%) are `add #N,Rm` (offset modifiers); 2,907 (12%) are struct-field loads `mov.l @(disp,Rm),Rn`. Conclusion: MAC.L pointers are dominantly inherited or struct-walked, not loaded via PC-pool — and none point into CAL via direct literal.

2. **GBR-relative load census** (`artifacts/gbr_relative_census.py/.out.txt`) — counted every `mov.b/.w/.l @(disp,gbr),r0` and store-to-GBR in PROG. Out of 186/227/915 PROG-wide GBR loads (b/w/l), only 4/1/7 are in the gradient-limiter call tree. Stores dominate (440 in call tree, top disp=0x08). **The gradient call tree DOES use GBR — but for storing per-task state, NOT for loading calibration data.** Cross-check: hypothetical GBR bases of `0x80021400/0x80021500/0x80021800` paired with V-curve target addresses produce displacements that are NEVER USED in the call tree. Only 4 LDC-GBR instructions exist in PROG (all `ldc.l @Rm+,gbr` — context-switch / per-task GBR setup). **The "GBR-relative addressing hides the LUT lookup" theory is now strongly disproved.**

3. **Boot CAL→RAM copy loop hunt** (`artifacts/boot_copy_loop_hunt.py/.out.txt`) — searched all PROG for memcpy-shaped loops (`mov.l @rm+,r0; mov.l r0,@rn`; cmp/dt; bf-back) within a 12-insn window. **Zero candidates found.** Also reduced the question to "any 32-bit literal anywhere in PROG that points into the V-curve region 0x80021400-0x80021c00": **0 LE matches at any alignment, 1 BE match (PROG@0x80041a0c -> 0x80021400) but in a region that's clearly LE u32 init-table data — the BE interpretation is almost certainly spurious**. The LE-interpreted value `0x00140280` at that slot fits the surrounding init-table record pattern. Boot-RAM-mirror theory also weakened.

4. **CAL-referenced data dump** (`artifacts/cal_referenced_dump.py/.out.txt`) — listed every CAL address actually loaded by `mov.l @(disp,pc),Rn` in PROG. **Only 12 unique CAL targets across the entire 1.7 MB PROG**, of which only 3 are in actual CAL data (the other 9 are RAM addresses): `0x80020005`, `0x80020820`, `0x8002fd2c`. Dumped the structure at each:
   - `0x80020005`: ASCII calibration-ID strings (`5271CI52700`, `1111CI315270D003`, `1111CI3152700000`) — metadata only.
   - `0x8002fd2c`: all zeros for 256+ bytes — probably an empty calibration slot or RAM-init source that's defaulted to zero.
   - **`0x80020820`: a structured data block with the recurring 16-byte pattern `00 3c 00 46 00 00 00 00 ... 00 05 00 14 00 1e ... 00 28`** — a clip-limit pair (60, 70 BE) followed by zeros and an ascending-sequence Y-axis. Plus the surrounding 0x80020800-0x80020846 contains: clip pair `0x2710` (10000), an LE-u16 X-axis `[116, 117, 137, 165, 204, 254, 315, 388]` (clean monotone ascending), and the clip-pair structure repeats.

   Also: zero CAL-internal LE pointers exist (no calibration TOC in CAL). Only 1 SHLL16 in PROG (rules out hidden 32-bit address construction via MOV+SHLL16+OR). 0x14c0 (low half of negative-curve addr) appears 27× as BE u16 in PROG — but that's just the SH-4 instruction `mov.l r12,@(0x0,r4)` which is a legitimately common opcode, not a pointer reference.

5. **🎯 Investigation of 0x80020820 and the recurring `00 3c 00 46` marker** (`artifacts/investigate_0x20820.py/.out.txt`) — the breakthrough:
   - The function loading `0x80020820` is **PROG@0x800733f6**, ending at **0x800736f6**. Its body is dense with `MULS.W r1,r6 → MAC.L → MULS.W r2,r6 → MAC.L → MULS.W r3,r6 → MAC.L → MULS.W r4,r6 → MULS.W r5,r6 → MAC.L` — a clear sum-of-products / polynomial-evaluation pattern (5-tap FIR or similar).
   - **PROG@0x800733f6 is in the gradient-limiter call tree at depth 6** from seed `0x8006e31c` (just past the depth-4 BFS limit used by previous scans, which is why it was missed).
   - 0 direct BSR callers — invoked via JSR @Rn or function pointer (indirect dispatch).
   - The byte pattern `00 3c 00 46` (= 60, 70 as BE u16) appears **16 times in CAL**: at `0x80020820, 0x80020840, 0x80021444, 0x80021740, 0x8002176c, 0x800217c0, 0x800217ec, 0x80021818, 0x8002186c, 0x800219bc, 0x800219e8, 0x80021a14, 0x80021a68, 0x80021a94, 0x80021ac0, 0x80021c38`.
   - **The 16-byte sequence `74 00 75 00 89 00 a5 00 cc 00 fe 00 3b 01 84 01` appears at BOTH `0x80020804` AND `0x80021448`** — the same data exists at two CAL locations, exactly like the V-curve replication.
   - As LE u16: `[116, 117, 137, 165, 204, 254, 315, 388]` — a clean monotone ascending X-axis with exponential-ish spacing (1, 20, 28, 39, 50, 61, 73). Plausible breakpoint axis for temperature, RPM, voltage, or current.
   - This is a **DIFFERENT structure schema** than the V-curve we've been hunting. It uses `00 3c 00 46` as marker (60, 70 BE = clip-pair) and likely LE u16 storage for X-axis — not BE u16 with `0x8039` marker like the V-curve.
   - There are 16 candidate `00 3c 00 46`-marked entries (10 in the V-curve region 0x80021400-0x80021c00 alone). At least one of them — by analogy with `0x80020820` which IS code-referenced — is highly likely to be a real, in-use LUT.

**Implication for the V-curve hypothesis:** the original V-curve at 0x80021528 might be UNUSED legacy/template data, and the actual gradient-limiter (or other DLCM) LUT data uses the `00 3c 00 46` schema. **Confidence in V-curve = §10.7 LUT was briefly downgraded to low**, but partially recovered after deeper analysis below.

#### 2026-05-06 follow-up — sister-entry survey, function-end bug, and the LE i16 reinterpretation

After the breakthrough above, ran several follow-up scripts that produced both negative results AND a critical reinterpretation:

6. **Sister-entry population survey** (`artifacts/sister_lut_survey.py/.out.txt`):
   - Of the 16 `00 3c 00 46`-marked entries, **only 0x80020820 (the code-referenced one) is sparsely populated** — 9 of 64 nonzero bytes. The other 15 are FULLY populated (24-42 of 64 nonzero, 247-256 bytes of populated content).
   - **The marker `00 3c 00 46` is just `(60, 70)` as BE u16** — and similar adjacent-X-axis-pairs are very common: `(40, 50)` 32×, `(50, 60)` 29×, `(10, 25)` 26×, `(25, 40)` 26×. So `(60, 70)` is NOT a uniquely-discriminating marker; it's just "two adjacent X-axis breakpoints that happen to be `60` and `70`." The sister-entry list might over-include or under-include true LUTs.
   - **None of the 15 fully-populated sister entries have any PROG reference** — neither LE nor BE 32-bit literal, neither aligned nor unaligned. The asymmetry between 0x80020820 (referenced, sparse) and 0x80021444+ (unreferenced, populated) is total.

7. **Function-end finder bug discovered** (`artifacts/trace_0x800733f6.py/.out.txt`):
   - The function loading 0x80020820 is **PROG@0x800730f6**, NOT 0x800733f6 — my prior `find_function_end` used `max_scan=0x300` and split this 8 KB+ function's CALLEES at the 0x300 boundary, leading to the wrong "function start" extraction. **Every prior call-tree analysis truncated long functions silently.**
   - Re-ran with corrected `max_scan` and depth-8 BFS (`artifacts/corrected_call_tree.py/.out.txt`): now 1744 functions in tree, 103,393 MAC.L sites (vs prior 11,825 — 9× more). Re-ran MAC.L pointer trace with 200-insn lookback: **STILL 0 of 358 distinct PC-pool literals feeding MAC.L are in CAL.** This negative result is now extremely robust.
   - PROG@0x800730f6 itself is **8192+ bytes long** (giant function), with 46 MAC.L and 55 MULS.W instructions. **0 direct BSR callers, 0 LE u32 literals pointing to it** anywhere in PROG. So the function is invoked by an indirect mechanism we cannot easily trace from static analysis (likely JSR @Rn after a register is loaded from RAM or a function-table offset).
   - Only 11 unique CAL targets via PC-relative pointer load even at corrected depth 8 — same 11 as before. The deeper BFS adds zero new CAL accesses.

8. **🚨 LE i16 reinterpretation** (`artifacts/decode_vcurve_region.py/.out.txt`) — the night's biggest insight:

   **Previous interpretation: the CAL is BE u16. CORRECTED: the CAL is LE i16 throughout.**

   The V-curve at `0x80021528` has bytes `3e 00 23 00 0f 00 0a 00 0a 00 01 00 14 00 28 00`. The "clean" interpretation `[62, 35, 15, 10, 10, 1, 20, 40]` only emerges when read as LE u16 (or equivalently BE u16 with implicit /256 Q8 scaling — but the LE interpretation is much simpler). The X-axis bytes `b0 ff ba ff 00 00 50 00 c8 00 90 01 20 03 b8 0b` ONLY make sense as LE i16 = `[-80, -70, 0, 80, 200, 400, 800, 3000]` — as BE u16 they read as garbage `[45311, 47871, 0, ...]`.

   Verified across multiple structures:
   - 0x80020800 X-axis: bytes `74 00 75 00 89 00 a5 00 cc 00 fe 00 3b 01 84 01` → LE u16 `[116, 117, 137, 165, 204, 254, 315, 388]` (clean ascending) vs BE u16 `[29696, 29952, ...]` (garbage).
   - The "0x8039" marker at 0x80021504 is BE = 0x8039 OR LE = 0x3980 = 14720. Under LE interpretation, it's just an LE i16 value with the sign bit set — possibly a "default value" / "valid" flag from Continental's CAL tooling, not a special structure marker.

   **Revised V-curve LUT structure (LE i16):**
   ```
   0x80021500: header [256, 10240, 14720, 0, 20, 20, 1000, 1000, 1000, 0]
   0x80021514: X-axis [-700, -600, -80, -70, 0, 80, 200, 400, 800, 3000]   (10 values, not 8!)
   0x80021528: Y-axis [62, 35, 15, 10, 10, 1, 20, 40, 70, 70]              (10 values, not 8!)
   0x8002153c: trailer [3000, -100, -100, -3000, 1, 0, 0, 2000, 5000, 7500, 10000, 0, 256, 384, 384, 384, 384, 0]
   ```

   So the V-curve is a 10-entry LUT: monotone decrease 62→35→15→10→10 (plateau), minimum 1 at lash zero-crossing, then increase 20→40→70→70 (plateau). The X-axis covers -700..3000 (TrqLast in scaled units), with breakpoints concentrated near zero. The lash-zone minimum of `1` (vs ~5 cts/frame empirically observed) at exactly the X=0 breakpoint is a *very* clean fit.

   **This INVALIDATES many prior numeric interpretations** of CAL structure values throughout this notes file. The V-curve hypothesis itself is unchanged in shape and meaning, but had been described with a truncated 8-value X/Y axis. The full 10-value version matches the lash-zone phenomenology even more cleanly (more X-axis resolution near zero = finer control of lash-zone behavior).

#### 2026-05-06 final confidence assessment & what changed

| Aspect | Before night | After night |
|---|---|---|
| V-curve at 0x80021528 = §10.7 LUT shape | Medium | **Medium** (confirmed; now known to be 10-entry not 8-entry) |
| V-curve at 0x80021528 has any code reference | Unknown / suspected | **Disproved**: 0 PC-pool, 0 GBR-relative, 0 init-table, 0 boot-copy, 0 MAC.L pointer literal, 0 32-bit literal anywhere in PROG (BE, LE, aligned, or unaligned) |
| Active LUT data is at 0x80030000+ (active-region plan) | Hypothesized | **Disproved**: empty |
| GBR-relative addressing might explain LUT access | Hypothesized | **Disproved**: gradient call tree uses GBR for STORES not loads; only 4 LDC-GBR sites in PROG |
| Boot-time CAL→RAM copy could initialize LUT mirrors | Hypothesized | **Weakened**: no memcpy-shaped loop found anywhere; theory not formally killed because boot code might use indirect/non-standard copy patterns |
| 0x80020820 is in use by code | New finding | **Confirmed**: PROG@0x800730f6 (8 KB function with 46 MAC.L, 55 MULS.W) loads it via PC-pool. Function is in gradient call tree (depth 6 from seed 0x8006e31c), but invoked via indirect mechanism with no traceable caller. |
| Sister `00 3c 00 46` entries at 0x80021444+ are accessed by code | Hypothesized | **Disproved for direct reference**: zero PROG literals point to any of them. Possibly accessed via indirect base-register load that we cannot trace. |
| CAL is BE u16 throughout | Assumed | **Disproved**: CAL is **LE i16** throughout. |

**Net result: the V-curve identification is INTACT but the access mechanism is genuinely unknown.** The most likely remaining explanations are:
- (A) Boot ROM (or a non-PROG firmware partition) initializes RAM mirrors of CAL data, and runtime gradient code reads from the RAM mirrors. Static analysis of PROG alone cannot find the LUT base in a register.
- (B) The CAL data is accessed via a calibration-tool-generated indirection layer (e.g., a global "calibration descriptor" pointer that lives in RAM, set up by external tooling before PROG executes). No direct PROG→CAL pointer exists by design.
- (C) The data is unused legacy from prior calibration revisions, kept in flash for diagnostic / version-history reasons, and the actual runtime gradient logic uses a separately-stored copy.

**Practical implications for empirical patching:** If theory (A) or (B) is correct, patching the V-curve bytes in CAL alone will NOT change runtime behavior — the boot ROM / CAL tooling will re-initialize RAM with the new CAL values, but only after the next power cycle (or possibly never, if CAL is read only once at programming time and the RAM image is stored elsewhere). If theory (C) is correct, patching does nothing at all. **The minimum viable empirical experiment is therefore a power-cycled patch test**: bump `0x01` byte at 0x80021530+2 (LE u16; the lash-zone minimum) to `0x05`, fully power-cycle the ECU, then drive and observe whether Phase 1 minimum changes. Same answer either way: if behavior changes, we know CAL still drives runtime; if not, our hypothesis is wrong AND/OR runtime data lives elsewhere.

**Files generated this session:**
- `artifacts/lut_hunt_active_region.py/.out.txt` — V-shape sweep of 0x80030000+ (zero hits — region is RAM)
- `artifacts/mac_callsite_forensics.py/.out.txt` — 11825 MAC.L sites traced (0 CAL pointer literals)
- `artifacts/gbr_relative_census.py/.out.txt` — exhaustive GBR-relative load/store distribution + plausibility check
- `artifacts/boot_copy_loop_hunt.py/.out.txt` — memcpy pattern search across PROG (zero candidates)
- `artifacts/cal_referenced_dump.py/.out.txt` — every CAL address loaded by PC-pool, with structure dumps
- `artifacts/investigate_prog_init_table.py/.out.txt` — investigated 0x80041a0c init-table region; confirmed BE-pointer interpretation was spurious
- `artifacts/investigate_0x20820.py/.out.txt` — discovered the `00 3c 00 46` schema and the 8 KB function loading 0x80020820
- `artifacts/sister_lut_survey.py/.out.txt` — population status of all 16 sister entries; only 0x80020820 referenced
- `artifacts/trace_0x800733f6.py/.out.txt` — confirmed function-end bug; corrected function bounds to 0x800730f6-0x800736f6+
- `artifacts/corrected_call_tree.py/.out.txt` — re-ran MAC.L analysis with depth=8 and max_scan=4096 — same negative result, robust
- `artifacts/decode_vcurve_region.py/.out.txt` — full LE i16 decode of 0x80021400-0x80021c80 region; revealed CAL is LE i16 not BE u16
- `artifacts/calibration_catalog_le.py/.out.txt` — exhaustive structural catalog of LUTs in the V-curve region under correct LE i16 interpretation; classifier-confirmed the V-curve at X@0x80021514 / Y@0x80021528 with 10-entry shape, plus ~30 other monotone/V/inverted-V/clip LUTs in the 0x80021400-0x80021c80 region

#### 2026-05-06 morning TLDR (read this first when reviewing)

**What we proved this night:**

1. **The V-curve at 0x80021528 is a genuine LUT structure**, with a classifier-validated V-shape under the LE i16 interpretation. Full 10-entry table:
   ```
   X = [-700, -600, -80, -70,   0,  80, 200, 400, 800, 3000]   @ 0x80021514
   Y = [  62,   35,  15,  10,  10,   1,  20,  40,  70,   70]   @ 0x80021528
   ```
   Min Y=1 at X=80 (just past the lash zero-crossing) is a textbook gradient-limiter rate curve. The full 10-entry shape (was thought 8-entry) is even cleaner than the prior interpretation.

2. **The CAL is stored LE i16 throughout**, not BE u16 as previously assumed. This invalidates many prior numeric interpretations of CAL data values. Any future scripts that read CAL must use `<h` (LE i16) format strings.

3. **The V-curve has ~30 sister LUTs in the 0x80021400-0x80021c80 region**, catalogued in `artifacts/calibration_catalog_le.out.txt`. These include monotone ramps, inverted-V shapes, clip pairs, and the matching `gradientLimiterNegative_*` candidate `[-4, -4, -15, -15, -20, -25, -30, -40, -40, -40]` at Y@0x80021b8c with the same X-axis as the V-curve.

4. **The V-curve has NO discoverable code reference of any kind** — no PC-pool literal (LE or BE, aligned or unaligned), no GBR-relative load, no init-table entry, no boot-copy loop, no MAC.L pointer source. This is robust across depth-8 BFS with corrected function-end detection.

5. **The only confirmed code-referenced CAL data is at 0x80020005 (calibration ID strings) and 0x80020820 (a sparse 9/64-byte structure loaded by PROG@0x800730f6).** The 8 KB function PROG@0x800730f6 is reachable from gradient-limiter seed 0x8006e31c at depth 6 and contains 46 MAC.L + 55 MULS.W instructions, but has 0 direct callers and 0 LE-pointer literals anywhere in PROG — invoked by an indirect mechanism we cannot trace from static analysis.

**What this means for empirical patching:**

The fact that no PROG location holds a 32-bit literal pointing to the V-curve in any form strongly suggests one of:
- (A) Boot ROM (or non-PROG firmware) initializes RAM mirrors of CAL data; runtime code reads RAM mirrors with bases that never appear as PROG literals.
- (B) The CAL data is accessed via an indirection layer set up by Continental's calibration tool prior to PROG execution (e.g., a global pointer table in RAM populated at first boot from CAL).
- (C) The data is unused legacy from prior calibration revisions.

**Recommended empirical experiment:** With the corrected understanding that CAL is LE i16 — to test the lash-zone minimum:
- The byte at 0x80021530 is `0a 00` (LE i16 = 10) — the second-to-last decreasing value.
- The byte at 0x80021532 is `01 00` (LE i16 = 1) — the V-curve **minimum**, the lash zero-crossing rate.
- To bump the lash-zone minimum from 1 to 5: change the bytes at `0x80021532-0x80021533` from `01 00` to `05 00` (LE i16 5).
- Power-cycle the ECU after the patch (in case boot copies CAL→RAM only at boot).
- Drive and observe: does the empirical Phase 1 minimum change from ~0 cts/frame to ~5 cts/frame? If yes, V-curve identification is fully confirmed and CAL writes propagate to runtime. If no, either the V-curve is not the active LUT OR runtime data lives elsewhere (RAM-only / EEPROM-mirrored).
- If you want to test the second V-curve copy at 0x80021b64 simultaneously: also change bytes at `0x80021b6e-0x80021b6f` from `01 00` to `05 00`.
  - **Correction (2026-05-20):** this was originally written as `0x80021b6c`, which is **wrong**. Both copies are byte-identical (`[62, 35, 15, 10, 10, 1, 20, 40, 70, 70]`), so the minimum `01 00` sits at +0x0A from each Y-axis start: `0x80021532` for copy A (`0x80021528`+0xA) and `0x80021b6e` for copy B (`0x80021b64`+0xA). `0x80021b6c` (+0x08, index 4) is the *second* `10` of the `10, 10` plateau (`0a 00`), not the minimum. The slip: copy A's minimum was pinned by reading the actual bytes (see two lines up — `0x80021530`=`0a 00`, `0x80021532`=`01 00`), but copy B's was hand-counted off the doubled `10, 10` plateau and landed one entry early; it was never byte-verified, and the `01 00` byte value asserted here was itself wrong (the bytes at `0x80021b6c` are `0a 00`). `dlcm_flash_proxy.py` `DEFAULT_PATCHES` inherited the same off-by-one (flash-side `0xA0021B6C`) and was corrected to `0xA0021B6E` the same day.

**Status of investigation:** Static analysis of PROG/CAL alone is now exhausted. The V-curve identification has strong shape evidence and weak code-reference evidence; the asymmetry is best resolved empirically. If you can read RAM at runtime (live ECU debugger, or memory-dumping tool over CAN) you could resolve all this in minutes by reading addresses 0x80030000+ at boot and looking for the V-curve byte pattern in RAM.

#### 2026-05-06 final overnight findings (`final_search_and_0x730f6_analysis.py/.out.txt`)

Two further confirmations and one critical observation:

1. **V-curve byte pattern uniqueness.** Searched the ENTIRE CAL and ENTIRE PROG byte-by-byte for the V-curve signature bytes:
   - Positive Y `[62,35,15,10,10,1,20,40]` (16 bytes): **2 hits in CAL** (0x80021528, 0x80021b64), **0 hits in PROG**
   - Positive Y with `[70, 70]` plateau (20 bytes): same 2 CAL hits, 0 PROG
   - X-axis bytes `[-700,-600,-80,-70,0,80,200,400,800,3000]` (20 bytes): **2 hits in CAL** (0x80021514, 0x80021b78), 0 PROG
   - Negative Y `[-4,-4,-15,-15,-20,-25,-30,-40,-40,-40]` (20 bytes): **2 hits in CAL** (0x800214c0, 0x80021b8c), 0 PROG

   The exact 2-fold duplication of all four byte patterns at consistent address pairs strongly supports interpretation as a **pos/neg gradient-limiter pair** stored at two CAL locations (likely active and shadow / backup, or two different state branches). The complete absence in PROG rules out the V-curve being inlined as immediate constants in code.

2. **PROG@0x800730f6 reload pattern (most significant single-instruction finding):**
   ```
   0x800736f6  d806  mov.l @(0x18,pc),r8  [pool@0x80073710]    ; R8 = 0x80020820
   0x800736f8  01fa  <Continental variant>                       ; (no-op'd by SLEIGH)
   0x800736fa  00f6  mov.l r15,@(r0,r0)                          ; (or variant)
   0x800736fc  89f0  bt -32                                      ; backward branch
   0x800736fe  3ff4  div1 r15,r15                                ; (probably variant)
   0x80073700  580b  mov.l @(0x2c,r0),r8                         ; R8 OVERWRITTEN
   ```

   **R8 is overwritten only 4 instructions after the load.** This means one of:
   - (a) The 4 intermediate instructions ARE Continental variants that consume R8 as input (the SLEIGH file no-ops them, hiding their semantics).
   - (b) The literal load is effectively DEAD CODE in this path — possibly leftover from compilation, or the load happens for an alternative branch that wasn't taken.
   - (c) The literal serves some side-effect purpose (CRC check on the LUT, hardware MMU prefetch hint) that doesn't show up as a "use" in classic dataflow.

   Of these, **(a) is most plausible** since the variants in this exact instruction sequence (`01fa, 00f6, 89f0, 3ff4`) appear with high frequency in the gradient-limiter call tree and are likely Continental's specialized arithmetic/control opcodes. Without RE'ing the Continental SLEIGH definitions, we can't know exactly what they do with R8.

3. **0x80020820 has only ONE loader in all of PROG** (confirmed). Sister entries have a stride of 0x2c (44 bytes) between most consecutive entries — strongly suggesting `RECORD_SIZE = 44 bytes` for the underlying LUT-record format. Larger gaps (0x54 = 84, 0x150 = 336, 0x178 = 376) likely mark group boundaries where different LUT families begin.

**Final assessment:** The V-curve identification at `0x80021528` (and matching neg-curve at `0x800214c0`) is **structurally confirmed** as a 10-entry gradient-limiter-shaped LUT in LE i16 storage. The runtime access mechanism remains unknown and is likely either (a) Continental-variant-opcode-mediated (since the only confirmed code reference involves R8 being immediately consumed by 4 variant instructions before being overwritten) or (b) RAM-based with bases set by boot ROM. Empirical patching is the cheapest next step to resolve which is the case.

---

### Goal 4: DLCM firmware decompile — 0x212 TX path (2026-04-29/30)

Analysis performed with Python SH-4 disassembler scripts: `dlcm_phase_dump.py`, `dlcm_filter_trace.py`, `dlcm_bsrf_context.py`, `dlcm_dispatch_trace.py` (all in `notes/artifacts/`).

#### Continental SH-4 variant opcodes

> **⚠ DEPRECATED — wrong ISA era. Do not use any of the following.** This table and
> the Phase 27 correction beneath it were derived under the SuperH4 misidentification,
> before the processor was established as TriCore (see the ISA correction above and
> `Architecture`). The opcode numbers, their "roles", and the `dlcm_analysis`
> workspace they came from are all meaningless against the real instruction set.
> Kept only so a future session recognises the material and does not re-derive it.
> The TriCore-era equivalents live in `ghidra/README.md` under "TriCore-era scripts".


**⚠ Correction (Phase 27):** The opcode roles below were revised after Phase 27 analysis. `00F8` is Motor CAN TX (not a generic "CAN TX stub"), and `00F6` is D-CAN TX (via pre-configured mailbox, not listed here originally). See Phase 27 for the confirmed opcode map.

| Opcode | Label | Behavior (revised) |
|--------|-------|----------|
| `0x00F8` | Motor CAN TX | ~~NOP.X / CAN TX stub~~ **REVISED: Motor CAN TX opcode.** The `MOV.W @pool,R1 ; R1=CAN_ID` pattern followed by 00F8 transmits on the private Motor CAN sub-bus (DLCM↔MCM). The 0x02FF "Universal Command" frame uses this pattern. CAN IDs 0x0200, 0x0211, 0x0212, 0x0233 in 0x8006xxxx are likely Motor CAN (or sub-bus) IDs, not D-CAN. |
| `0x00F6` | D-CAN TX | **NEW (Phase 27).** 564 occurrences. Takes a `01Fx` mailbox-index argument in the preceding word. The mailbox's CAN ID was pre-configured at startup from the init table at 0x8008FCxx — no CAN ID appears at the TX call site. |
| `0xFFFF` | NOP.Y | Function boundary marker. Appears at the start/end of functions. Zero-cost delimiter analogous to a linker-injected NOP boundary. |
| `0x09A0` | (unknown) | Appears in the E340-E6F6 per-channel gain loop, always between a MAC.L and a GBR-relative store. Hypothesis: reads MAC accumulator result into R0 (i.e., `STS MACL,R0` equivalent). Unconfirmed — not in any SH-4 reference. |

#### CAN TX call convention

The pattern for Motor CAN (sub-bus, DLCM→MCM) transmit stubs:

```
MOV.W @(pool,PC), R1   ; R1 = Motor CAN arbitration ID (16-bit)
0x00F8                  ; Motor CAN TX opcode
MOV.L @(pool,PC), R9   ; R9 = pointer to frame data
BSR   <CAN helper>      ; call CAN transmit helper
MOV.L R4, @(0x0,R15)   ; delay slot: push R4 to stack frame
```

Confirmed instances of this pattern (Motor CAN sub-bus IDs):
- `0x8006D9E2`: CAN ID **0x0212** → BSR `0x8006CE4C`
- `0x8006DA04`: CAN ID **0x0211** → BSR `0x8006D06E`
- `0x8006DCB4`: CAN ID **0x0200** (in phase handler region)
- `0x8006F34E`: CAN ID **0x00FD** → BSR `0x8006E7FE`

#### 0x212 transmit function structure (0x8006D900–~0x8006DA60)

This function is the top-level torque output routine. It:

1. Opens with NOP.Y (0xFFFF) at D900 — function boundary marker
2. Makes 8 BSR calls into the E340-E6F6 per-channel gain region (entry points E304, E31C, E332, E35C, E374, E38A, E3B4, E3CC)
3. Makes one BSR at D91A into the 15-phase state machine dispatcher (0x8006E31C)
4. Transmits CAN 0x212 at D9E2 (the anti-lash torque request)
5. Transmits CAN 0x211 at DA04 (a second torque-related message)

#### 15-phase state machine dispatch (0x8006E31E–0x8006E33A)

A jump table of 15 consecutive BRA instructions beginning at 0x8006E31E:

| Index | Address | Opcode | Target |
|-------|---------|--------|--------|
| 0 | 0x8006E31E | `ACA1` | `BRA 0x8006DC64` |
| 1 | 0x8006E320 | `ACA2` | `BRA 0x8006DC68` |
| 2 | 0x8006E322 | `ACA3` | `BRA 0x8006DC6C` |
| ... | ... | ... | ... |
| 14 | 0x8006E33A | `ACAF` | `BRA 0x8006DC9C` |

Each phase target is 4 bytes apart: phase N handler is at `0x8006DC64 + N*4`. The entry is selected by offsetting into this table — the selector code at 0x8006E31C computes the offset from the current phase state and falls into the appropriate BRA.

This is called from 0x8006D91A (`BSR 0x8006E31C`) inside the 0x212 TX function. The current phase state is stored GBR-relative (GBR+8 and GBR+32 based on filter loop accesses).

#### Phase handlers (0x8006DC64–0x8006DC9C)

15 handlers, one per phase, each 4 bytes apart. Each handler loads phase-specific parameters (pool constants into R9, etc.) and calls phase-specific helper functions. Phase handlers are not long — 4 bytes each means each one is a single instruction (the BRA from the dispatch table) plus delay slot, transferring control to a longer handler body elsewhere. The bodies set up the filter parameters (ramp coefficient, state machine variables) for that phase's computation.

Confirmed feature at 0x8006DCB4–DCB8: CAN ID 0x0200 TX stub (NOP.X pattern), confirming some phase handlers also trigger additional CAN transmissions beyond 0x212/0x211.

#### BSRF R0 dispatch structure (0x8006E7B0, 0x8006E8A6)

Two identical dispatch sites, 0xF6 bytes apart:

```
; Site 1 at 0x8006E7B0 (site 2 at 0x8006E8A6 is structurally identical)
0x8006E79C  5000  MOV.L @(0x0,R0),R0    ; R0 = *R0 (dereference phase pointer)
...
0x8006E7B0  4003  BSRF R0               ; branch to PC+4+R0 (position-independent BSR)
0x8006E7B2  0000  (delay slot)
0x8006E7B4        [jump table entry 0]  ; BRA 0x8006E7FE
0x8006E7B8        [jump table entry 1]  ; BRA 0x8006E83C
```

`BSRF R0` (opcode `0x0003`) branches to `PC+4+R0`. The jump table begins immediately at `PC+4` (the instruction after the delay slot). R0 is loaded by dereferencing the phase state pointer — `MOV.L @(0,R0),R0` converts a phase-state address into a byte offset into the jump table. This is the per-phase function dispatch for the filter dispatch layer above the 0x212 TX function.

Jump table targets for site 1:
- Entry 0: `BRA 0x8006E7FE` — CAN TX helper (identified as handler for CAN ID **0x00FD** via context at 0x8006F34E)
- Entry 1: `BRA 0x8006E83C` — second handler

Jump table targets for site 2 (0x8006E8A6):
- Entry 0: `BRA 0x8006E8F4`
- Entry 1: `BRA 0x8006E932`

#### Call chain: main loop → 0x212 TX function

Scanning for direct BSR/BRA or JSR @Rn callers of the 0x8006E700–0x8006E800 dispatch region from the 0x8007xxxx main loop found **zero** direct callers. The call chain passes through an intermediate layer in 0x8006Fxxx:

- Main loop (0x80070076) calls into 0x8006Fxxx (e.g., `BSR 0x8006F2B4`)
- The 0x8006Fxxx functions contain NOP.X stubs for CAN IDs 0x00FD and others (confirmed at F6A2, F6AE, F6BC, F6C8, F7AE, F7BE)
- These in turn call the 0x8006Exxx filter/dispatch functions

The 0x8006A738–0x8006CCA0 gap-region functions (recovered in flash6) are entirely self-contained — no external callers were found. They are likely called indirectly through the BSRF dispatch mechanism or through function pointers stored in SRAM.

#### CAN IDs identified in 0x8006xxxx region

| CAN ID | TX stub address | CAN helper BSR target | Notes |
|--------|----------------|----------------------|-------|
| 0x00FD | 0x8006F34E | 0x8006E7FE | Dispatch target; also called from BSRF site 1 |
| 0x0200 | 0x8006DCB4 | (unclear, linear disasm) | In phase handler region |
| 0x0211 | 0x8006DA04 | 0x8006D06E | Second message in 0x212 TX function |
| 0x0212 | 0x8006D9E2 | 0x8006CE4C | Anti-lash torque request (primary target) |

#### E340-E6F6 region: byte pattern observations

Direct binary scan of the E340-E6F6 region:

- The byte pattern `D9 0F 36 BF` repeats at every 0x10-byte interval from 0x8006E33C to 0x8006E6F6 (57 occurrences).
- Each occurrence has a different BSR target (EDxx/EExx).
- The role of this region is not yet understood. The bytes `D9 0F` would decode as `MOV.L @(0x0F,PC),R9` if executed as an instruction, but the same bytes also appear at the pool slot 64 bytes ahead — making any "load constant" reading produce the misaligned value `0xD90F36BF`, which cannot be a valid 32-bit-aligned pointer. This is consistent with the wider observation (see C630 binary analysis below) that D90Fxxxx pool "constants" in this area are instruction bytes incidentally falling in the P3 address range, not real SRAM addresses.

The actual temporal filter is **C630** (called from CE4C and CFCC). See the C630 binary analysis section below for the real filter coefficient sources (P3 DRAM, accessed via `*[GBR+0x14] + 0x04`).

#### Open questions for Goal 2

| Question | Status |
|----------|--------|
| Filter coefficient locations (R9 pointer target) | **RESOLVED** — 0xD90F36BF is SRAM (P3 cache), not static flash. Cannot determine value without runtime dump. |
| Coefficient value at 0xD90F36BF | Unresolved — SRAM-only, requires runtime observation or startup trace |
| C630 coefficient at piRam8006ccf0 (0x8006CCF0) | **CORRECTED (2026-05-01)** — `piRam8006ccf0` was a Ghidra artifact from an old binary. In the current binary, 0x8006CCF0 is CODE. C630 loads its coefficient pointer from a state struct at `*[GBR+0x14] + 0x04`. The actual SRAM coefficient buffer pointers are: 0xD9FFB830, 0xD9FFB930, 0xD922B930, 0xD922BA30, 0xD922BB30 (all 4-byte-aligned P3 DRAM). Values are in DRAM at runtime — not static. |
| Opcode 0x09A0 exact behavior | Unresolved — hypothesis is MAC result read to R0 |
| Per-phase parameter differences (what changes between DC64–DC9C) | Partially observed — pool loads differ; full phase-by-phase comparison needed |
| GBR base address at runtime | Unresolved — GBR value not visible in static analysis; points to per-task state block |
| What writes the phase pointer that R0 dereferences before BSRF | Unresolved — upstream caller sets it |
| Ghidra flow-traced disassembly of EC70–EE50 | Not yet done — linear scan too garbled; requires seeding from known entry points |

#### Tracing the input source to the D9xx region

**Scan for callers of 0x8006D900:** Binary scan (BSR/BRA) for anything targeting 0x8006D900 returned **zero direct BSR/BRA callers**, and 0x8006D900 does not appear as a 32-bit literal value (BE or LE) anywhere in the binary — ruling out JSR @Rn via static literal load as well.

D900 is **not a standalone function entry**. The NOP.Y at 0x8006D900 is the delay slot of `BBF0 BSR 0x8006D0E2` at 0x8006D8FE. After that BSR returns, execution resumes at 0x8006D902. The entire sequence from D902 through DA60 (BSR calls into E3xx, the 15-phase dispatch, 0x212 TX, 0x211 TX) is the **continuation** of a large outer function after `BSR D0E2` returns.

The outer function contains multiple BSR/NOP.Y pairs in the same pattern:
- `D892: BSR 0x8006D076 / D894: NOP.Y` (delay slot)
- `D8A6: BSR 0x8006D08A / D8A8: NOP.Y` (delay slot)
- `D8EA: BSR 0x8006D0CE / D8EC: NOP.Y` (delay slot)
- `D8FE: BSR 0x8006D0E2 / D900: NOP.Y` (delay slot)

NOP.Y (0xFFFF) is used as a standard delay-slot NOP after BSR calls throughout this code — it is NOT exclusively a function boundary marker.

The outer function spans at minimum from before 0x8006D500 through 0x8006DA60. It contains many additional CAN TX stubs (NOP.X at D506, D51C, etc.) and BSR calls to D0xx helpers, making this the main DLCM torque computation + output loop.

**R15 dual-role:** In the D500–D7C0 range, `MOV.L @(pool),R15` instructions load R15 with a fixed SRAM array address, then `MAC.L @R15+,...` uses R15 as an auto-incrementing data pointer. Before each BSR call, R15 is advanced past the array end (or reloaded), restoring it to stack-pointer behavior. So when MAC.L instructions reference R15 in this region, R15 is pointing into a fixed SRAM array — base addresses stored in literal pools in the D5xx–D8xx range — not into the call stack.

The D0xx helpers (`0x8006D076`, `D08A`, `D0CE`, `D0E2`) called from the outer function are adjacent to the CAN TX helpers at `CE4C`/`D06E`.

Linear disassembly is too noisy in this region (heavy code/pool mixing) to trace cleanly. Ghidra flow-traced disassembly is required.

**4b: Ghidra flow-trace from 0x8006D9E2** *(completed 2026-04-30)*

**Blocker resolved: Sleigh patch.** All Continental custom opcodes in the C000-DA80 region blocked Ghidra's SH-4 disassembler. Fix: added 140 Continental-specific NOP constructors to `SuperH4.sinc` (the SH-4 Sleigh spec at `Ghidra\Processors\SuperH4\data\languages\SuperH4.sinc`). These opcodes decode as no-ops in Ghidra, allowing disassembly to flow through. Patch is a bulk add around the existing `nop` definition at line 2407. All opcodes that conflicted with valid SH-4 definitions were identified and excluded (SHLL Rn variants, CLRS, MOVT Rn, DT Rn, etc.). Also added a `listing.clearCodeUnits(C000-DA80)` step at the start of `DlcmCan212.java` to flush stale gap records before each reseed.

**Outer function structure (D8xx region):** The D0xx BSR calls are interleaved with BSR calls to E2xx helpers and MAC.L filter taps:
```
D88E: mov.l <literal>,r15    ; load R15 = stack frame address for D076
D890: mov.l r8,@(r7+0)       ; store R8
D892: BSR D076               ; call filter phase helper
D894: nop_y                  ; delay slot
D896: add #-0x10,r15         ; restore stack (R15 -= 16)
D898: nop_0680
D89A: mov.l r0,@(0x40,GBR)   ; store R0 result
D89C: nop_0200
D89E: BSR E282               ; call E2xx filter step helper
D8A0: cmp/hi r0,r12          ; delay slot
...
D8A6: BSR D08A               ; second D0xx helper
...
D8EA: BSR D0CE               ; third D0xx helper (floating-point phase)
...
D8FE: BSR D0E2               ; fourth D0xx helper
D900: nop_y                  ; delay slot
D902: BSR E304               ; first BSR into E3xx
```

**D0xx helper decompile results:**

- **D076** (called from D892) — subtracts 0x43 from R6, calls DA60 and DA86 (sub-functions), then MAC.L using `*D0C8` as register-loaded pointer.
- **D08A** (called from D8A6) — confirmed single MAC.L + GBR store:
  ```c
  if (in_S != '\0') { mac_lOp(MACH_MACL, (int64)param_2 * (int64)*unaff_r9); }
  *(char *)(in_GBR + 8) = (char)in_r0;
  // then calls DA9C
  ```
  Accumulates param_2 times `*R9` (R9 = pool-loaded pointer) into MAC.
- **D0CE** (called from D8EA) — floating-point operations: calls `func_0x8006dad8()`, then writes FP registers fr15/xd14 to a struct offset determined by another FP result.
- **D0E2** (called from D8FE) — similar FP operations: reads fr0/fr1, writes to `in_r0+register[0x3c]` and adjacent offsets, stores `(char)in_r0` to GBR+1.

**D9xx region (D902-D9E0):** Eight or more BSR calls to E3xx functions (E304, E31C, E332, E35C, E374, E38A, E3B4, E3CC, …), each preceded by a MAC.L instruction. Pattern per iteration:
```
D9B2: BSR E3B4              ; BSR into E3xx
D9B4: mov.l <pool>,r9       ; delay slot: load R9 from pool
D9B6: nop_00a9              ; Continental NOP
D9B8: mac.l @r15+,@r9+      ; MAC.L
D9BA: mov.b r0,@(8,GBR)     ; store low byte of R0 to GBR+8
D9BC: add #0xf,r15          ; advance R15
D9BE: nop_0880
...
```
R15 and R9 are both auto-incremented by MAC.L; R15 is periodically reloaded from literal pools (e.g., 0x7F0F0880 — an on-chip SRAM address specific to this Continental SH-4 variant). The role of these MAC.L instructions is uncertain: R9 is loaded with values like `0xD90F36BF` from pool slots, but those values are not 32-bit-aligned and so are unlikely to be valid coefficient pointers (see C630 binary analysis below).

**0x212 CAN ID load site — confirmed:**
```
8006D9E2  91 40  mov.w 0x8006da66,r1    ; load 0x0212 into R1 — CONFIRMED (DA66 = 0x0212)
8006D9E4  00 F8  nop_x                   ; Continental NOP
8006D9E6  D9 FF  mov.l 0x8006dde4,r9    ; load far pointer into R9
8006D9E8  BA 30  BSR 0x8006CE4C          ; call CAN TX function
8006D9EA  14 F0  mov.l r15,@(r4+0)      ; delay slot
```

**CE4C (CAN TX 0x212) decompile:**
```c
void FUN_8006ce4c(void) {
    uVar1 = FUN_8006c630();           // prepare CAN payload (calls C630 helper)
    *(uint32*)(in_GBR + 0x40) = uVar1; // store to GBR+0x40
    func_0x8006d83c();                // unknown intermediate step
    FUN_8006c644();                   // second data-prep helper
    func_0x8006d866();                // actual CAN frame send
}
```
C630 is a multi-tap FIR/IIR filter (confirmed by decompile — see C630 section below). It is called from both CE4C (0x212 TX) and CFCC (0x211 TX), and returns the filtered output value that is stored at GBR+0x40.

**Partial blocker:** Some D0xx function bodies still show 1-6 byte bodies in Ghidra's listing (Ghidra stops flow-following at certain Continental opcodes). However decompile output was produced for all targeted functions (with warnings). See sub-section below for full decompile results.

---

#### C630 filter structure and CE4C signal chain (2026-04-30, session 2)

**Sleigh patches applied (session 2):**

Added NOP constructors to `SuperH4.sinc` for additional Continental obfuscation opcodes:

| Opcode | Location | Mechanism |
|--------|----------|-----------|
| `0x3489` | D0C8 (delay slot) | OP_3 NOP |
| `0x0D00` | D11E | OP_3 NOP |
| `0x8FFF` | CD02 | BF/S disp=-1 self-referential trap; OP_3 NOP overrides BF/S (16 vs 8 fixed bits) |
| `0x8FF1` | CD04 (delay slot of 8FFF) | OP_3 NOP |

`nop_8fff` and `nop_8ff1` resolved the CD02 nested-delay-slot trap. After this fix, all Cxxx function decompiles (CB2A, CB3E, CB82, CB96, C630, C900, C95A) completed without nested-delay-slot errors.

**Unresolved Sleigh blockers:**

D128 (0xA021) and D12A (0xA03F) remain unpatched. Both encode as BRA instructions with displacements that create a nested delay slot (BRA targets its own delay slot). Two NOP override approaches attempted:
- `OP_3=0xA021` (full opcode match): does not override BRA in Ghidra's Sleigh compiler despite having more fixed bits (16 vs 4). Root cause unknown — possibly a Ghidra specificity resolution bug with subconstructor-based constructors.
- `OP_0=0xa & I_1=0x021` (same field decomposition as BRA): also does not win.

Decompiles for D076, D08A, D0CE, D0E2, D06E, CFCC produce "Nested delay slotted instruction not permitted at 8006d128" warnings from the decompiler, but C code output is still generated (the decompiler truncates the bad-instruction block and continues). Diagnostic confirmed D128 is shown as `[gap] A0` in the Listing — it's also referenced as a literal pool data word by `mov.l @D128,R9` at D0EA (value = 0xA021A03F), so D128 serves dual roles (literal pool data AND obfuscation code bytes).

CDB2 (0xFF0F) similarly unpatched — `nop_ff0f` constructor added but BSR at CDB0 still gets "Program does not contain referenced instruction at CDB2."

CE68 (0x0E99) and DA00 (0x8202): both constructors exist but still show "Unable to resolve constructor" — likely related to being in delay slot positions.

**C630 decompile (FIR/IIR filter function at 0x8006C630):**

```c
void FUN_8006c630(double param_1, int param_2, int param_3) {
  do {
    piVar3 = piRam8006ccf0;          // load filter coefficient pointer from flash 0x8006CCF0
    param_1 = param_1 * (double)CONCAT44(in_fr0, in_fr1);  // FP double multiply
    param_3 = param_3 + -0xe;
    *in_r2 = unaff_r8;              // store R8 via R2 (state struct update)
    *(uint *)(param_2 + 0x3c) = (uint)piVar3 & 0xffff;
    FUN_8006bf1a(param_1, param_3); // sub-filter stage A
    ...
    uVar1 = CONCAT44(MACH,MACL) + (longlong)*piVar3 * (longlong)*extraout_r2;  // MAC.L tap
    ...
    uVar1 = mac_lOp(..., (longlong)*piVar4 * (longlong)*unaff_r11);
    unaff_r11 = unaff_r11 + 1;      // advance sample pointer
    piVar4[2] = (int)(piVar3 + 1);
    ...
    FUN_8006bf2a();                 // sub-filter stage B
    ...
  } while( true );                  // infinite loop (decompiler artifact from bad-instr truncation)
}
```

C630 is a multi-tap FIR/IIR filter. Key observations:
- The decompile shows `piRam8006ccf0` as the loaded pointer, but this is a Ghidra artifact: in the current binary 0x8006CCF0 is CODE, not a flash data pointer. C630's actual coefficient pointer comes from a state struct at `*[GBR+0x14] + 0x04` and points into P3 DRAM (see C630 binary analysis section below).
- `FUN_8006bf1a` and `FUN_8006bf2a` at 0x8006BF1A / 0x8006BF2A are sub-stages of the same filter chain
- `unaff_r11` auto-increments as a sample pointer — reads consecutive samples from the circular buffer
- Double-precision FP multiply on `param_1`: suggests the filter output is floating-point before being truncated to integer for the CAN frame
- Both CE4C (0x212 TX) and CFCC (0x211 TX) call C630 — the same filter function produces values for both messages

**CE4C decompile (CAN TX 0x212 at 0x8006CE4C):**

```c
void FUN_8006ce4c(void) {
  uVar1 = FUN_8006c630();              // run filter, get packed return value in R0
  *(undefined4 *)(in_GBR + 0x40) = uVar1;  // store to GBR+0x40 (module state block)
  func_0x8006d83c();                   // intermediate step (unknown)
  FUN_8006c644();                      // second data-prep helper
  func_0x8006d866();                   // actual CAN frame transmit
}
```

C630's return value goes to GBR+0x40 in the module state block. GBR points to the DLCM's per-task state structure; offset 0x40 is the torque request output slot.

**CFCC decompile (0x211 TX enclosing at 0x8006CFCC):**

Same structure as CE4C:
```c
void FUN_8006cfcc(double param_1, ...) {
  FUN_8006c630();                    // same filter
  // FP multiply with filter output
  // MAC.L accumulations (multiple passes)
  func_0x8006da10(param_1, ...);     // DA10 step
  func_0x8006d9fa();                 // D9FA step
  func_0x8006da18(); func_0x8006da3e(); func_0x8006da58();
  func_0x8006da42();
  func_0x8006da60(param_4); iVar5 = func_0x8006da86(param_4 + -0x43);
  func_0x8006da9c();
  uVar10 = func_0x8006dad8(...);
  uVar4 = _DAT_8006d128;             // read 0xA021A03F from literal pool
  ...
  *(uint *)(puVar7 - 4) =
      (uint)(unaff_r11 == uVar4) | ...;  // compare R11 vs literal pool constant
}
```

The `(unaff_r11 == uVar4)` comparison checks R11 against the literal pool constant 0xA021A03F — this appears to be a state/status comparison, not a filter value.

**Filter input write in the outer function:**

At D344 (first filter group in D342 region):
```
D342: mov.l @pool,r15    ; R15 = 0x7F0F0880 (SRAM filter input buffer base)
D344: mov.l r8,@(0x0,r7) ; write R8 (current sample) to @R7 (buffer write pointer)
D346: BSR CB2A           ; call filter tap function
```

At D890 (before BSR to D076 helper):
```
D88E: mov.l @D90C,r15    ; load R15
D890: mov.l r8,@(0x0,r7) ; write R8 (current sample) to @R7 (buffer write pointer)
D892: BSR D076           ; call helper
```

Both sites: **R8 is the sample value**, **R7 is the buffer write pointer**. The filter input circular buffer at **0x7F0F0880** (SRAM) is populated by the outer function on each invocation.

**D0xx helper decompile results (all with bad-instruction warnings):**

| Function | Calls | Behavior |
|----------|-------|----------|
| D076 | DA60, DA86, DA9C, DAD8 | Multi-step MAC.L filter; reads literal pool @D128 as data; calls sub-functions with param_2 decremented by 0x43 |
| D08A | DA60, DA86, DA9C, DAD8 | Same pattern as D076; one MAC.L tap per helper call |
| D0CE | DA60, DA86, DA9C, DAD8 | FP-heavy variant; writes FP registers to struct offsets |
| D0E2 | DA60, DA86, DA9C, DAD8 | Same FP pattern; writes (char) result to GBR+1 |

DA60, DA86, DA9C, DAD8 are the leaf-level filter sub-functions called by all D0xx helpers.

---

#### Outer function structure and R8 source trace (2026-05-01)

Binary scan of the full PROG binary (`coda_dlcm_prog.bin`) to find the outer function entry and trace R8.

**Outer function is a RTOS task loop — no traditional entry point:**

- **Zero `sts.l pr,@-r15` (0x4F22) instructions** in 0x80060000-0x8006C000. No standard SH-4 function prologue.
- **Zero RTS (0x000B) instructions** in 0x80060000-0x8006A100 (and confirmed no RTS in 0x8006A000-0x8006D000 either).
- The BRA at 0x8006A000 (`ADC8 bra 0x80069B94`) is a backward branch to a loop target, not a function call target.
- 0x80069B94 itself (the BRA target) is mid-loop code — `mov.l @(0x3c,r0),r15` with no prologue above it.
- Only two things branch to 0x80069B94: a `bf/s` at 0x80069BB0 (inner loop conditional) and the `bra` at 0x8006A000 (outer loop back-edge). Both are within the same large task body.
- **Conclusion:** The outer "function" is an RTOS task entered via function pointer from a task scheduler. It has no BSR call site and never returns. R8, R13, and other callee-saved registers are initialized once at task startup (before the loop), then maintained across all loop iterations.

**R8 source confirmed: struct field [R13 + 0x30]:**

Binary scan for all instructions with destination R8 in 0x8006A000-0x8006D900:

- **0x8006A072: `58DC mov.l @(0x30,r13),r8`** — first confirmed R8 load from the input struct
- **0x8006A09C: `58DC mov.l @(0x30,r13),r8`** — second load, same field, different branch path

R13 is a callee-saved register holding a pointer to an input data struct. Field offset 0x30 (12th 32-bit field from the struct base) is the raw torque/speed sample value. R13 is set at task initialization (before the loop begins) and is never reloaded inside the loop.

After being loaded, R8 is written to the SRAM circular filter buffer at 0x7F0F0880 via `mov.l r8,@(0x0,r7)` at D344 and D890 (R7 = running write pointer into the circular buffer).

**What writes R13+0x30:** Unknown — requires tracing the ISR or DMA callback that fills this struct. This code path is separate from the outer task and was not analyzed in this session.

**Other R8 load sites in the binary (sub-functions, not the main sample load):**

| Address | Instruction | Context |
|---------|-------------|---------|
| 0x8006CE40, CE5E, CE78 | `mov.l @(0x34,r13),r8` | Inside CE4C (0x212 TX); reads processed output back from struct — not the input sample |
| 0x8006B3AA, B4A4, B590 | `mov.l @(0x34,r11),r8` | Sub-functions in Bxxx range; R11 is a different struct pointer |
| 0x8006B430, B4EE | `mov.l @(0x34,r14),r8` | Sub-functions in Bxxx range |
| 0x8006B2E8 | `mov.l @(0x4,r0),r8` | Sub-function at B2E8 |
| 0x8006BF24 | `mov.w @r8,r8` | Inside BF24 (sub-stage of filter); re-reads R8 from the address R8 previously held |

**SRAM filter buffer references confirmed:**

0x7F0F0880 appears as a literal pool value loaded into R15 at: D342, D39A, D3F2, D834, D88E, D8E6, D93E. These are all filter-tap write setup points in the outer loop. A nearby address 0x7F0F0480 is loaded at B488 (a different SRAM region, role unknown).

**Remaining unknowns for Goal 2:**

| Unknown | Status |
|---------|--------|
| What ISR/DMA writes to R13+0x30 | Not yet traced — requires separate analysis of interrupt handlers |
| What R13+0x30 physically represents | Unknown — likely throttle pedal ADC or resolver angle; confirmed it is a 32-bit value in a struct |
| Filter coefficient layout at 0x8006CCF0 | **N/A** — `piRam8006ccf0` was Ghidra artifact; see C630 analysis section below |
| C630 coefficient VALUES in SRAM | Unresolved — values are in DRAM at runtime; requires runtime dump or empirical measurement |
| GBR base address at runtime | Partially resolved — GBR+0x14 = pointer to C630 filter state struct; GBR+0x40/0x7C = filter outputs; GBR+0x3C = second filter state pointer (8004Bxxx area); absolute GBR value still unknown |
| Why nop_a021/nop_a03f don't override BRA in Ghidra Sleigh | Unresolved Ghidra limitation |

#### C630 filter architecture (binary analysis, 2026-05-01)

Further direct analysis of the PROG binary (no Ghidra) clarified the C630 filter structure.

**C630 is a multi-stage IIR/FIR filter. Its coefficient data lives entirely in DRAM — not in the PROG or CAL flash binaries.**

**State structure layout (accessed via GBR):**

```
GBR (base of per-task DLCM state block, absolute value unknown)
  +0x08  : status flag byte (written by MOV.B R0,@(0x8,GBR) in many places)
  +0x14  : pointer to C630 filter state struct A
  +0x3C  : pointer to filter state struct B (used in 0x8004Bxxx area — separate filter)
  +0x40  : C630 filter output (torque request slot)
  +0x7C  : C630 secondary output
  +0x3C0 : third output slot
```

**C630 filter state struct A (at *[GBR+0x14]):**
```
struct[+0x00] : state variable (written with R13)
struct[+0x04] : coefficient buffer pointer -> R2 (loaded at 0x8006BF4C: MOV.L @(0x4,R0),R2)
struct[+0x3C] : delay buffer pointer -> R15 (loaded at 0x8006BF58: MOV.L @(0x3C,R0),R15)
```

MAC.L @R15+,@R2+ operates over both: R15 = delay buffer (samples), R2 = coefficient buffer (filter taps).
BSR targets in C630 call 20+ sub-stages: BA5E, BA76, BAEC, BAAA, BC04, BC90, BD0A, BE9C, BF1A, BF2A, etc.

**Real coefficient SRAM addresses (4-byte-aligned P3 DRAM):**

| SRAM address | Physical | Region |
|---|---|---|
| 0xD9FFB830 | 0x19FFB830 | C630 / 0x8004Bxxx area |
| 0xD9FFB930 | 0x19FFB930 | C630 area (+0x100 from B830) |
| 0xD922B930 | 0x1922B930 | C630 area |
| 0xD922BA30 | 0x1922BA30 | C630 area (+0x100 from B930) |
| 0xD922BB30 | 0x1922BB30 | C630 area (+0x100 from BA30) |

All are 4-byte-aligned, all are in P3 write-through DRAM (physical ~423-425MB range).

**The D90Fxxxx addresses are NOT real coefficient SRAM addresses.** All D90Fxxxx pool "constants" in C630 have bit-alignment that makes them invalid as 32-bit buffer starts (e.g., 0xD90F36BF ends in bits 1:0 = 11). They are instruction bytes that happen to fall in the P3 range when misread as data — an artifact of Continental's obfuscation technique where pool slots contain instruction bytes.

**Static analysis limit reached:**

All coefficient VALUES (at 0xD9FFB830 etc.) are initialized by startup code at or before 0x8003FE8A, which is before the PROG binary base (0x80040000) and is not in our available binaries. The values cannot be extracted without either:
1. A runtime memory dump of DRAM at 0xD9FFB830-0xD9FFBB30
2. Obtaining the startup code binary (likely a bootloader/OS region at 0x80000000-0x8003FFFF)
3. Empirical filter characterization from CAN log data (step response or frequency sweep)

**The empirical approach (option 3) is the practical next step** for characterizing the filter to enable potential modification.

---

### Goal 2 supplement: Binary search for empirical anti-lash values (2026-05-01)

Analysis performed with `antilash_search_p3.py`, `antilash_search_p4.py`, `antilash_search_p5.py` (all in `notes/artifacts/`).

#### Search methodology — CLRMAC / CLRT false positives

Raw 16-bit value searches for 0x0008 and 0x0028 in PROG return hundreds of false positives because these values are common SH-4 opcode encodings:

| Value | SH-4 opcode | Meaning |
|-------|-------------|---------|
| 0x0008 | CLRT | Clear T flag |
| 0x0028 | CLRMAC | Clear MAC registers |

The technique used to filter these out: scan specifically for **MOV.W instructions whose pool VALUE equals the target** — i.e., instructions of the form `0x9xNN` whose literal pool word holds the constant.

#### Search outcomes — gradient limiter empirical values

Scanning PROG and CAL for empirical values from the gradient limiter characterization:

| Value | Result |
|-------|--------|
| 0x0010 (=16) | NOT FOUND as MOV.W pool target |
| 0xFFEC (=-20 s16) | NOT FOUND as 16-bit-aligned pool word; only at odd byte boundaries |
| Sequence [8,7,5,5,3,3,2,2,1,1] | NOT FOUND in any encoding (u16 BE, u16 LE, u8) at any scale multiplier (×2, ×4, ×8, ×10, ×16, ×32, ×64, Q8.8) |
| Sequence [3,5,7,9,12,16] | NOT FOUND (same encodings/scales) |
| Sequence [16,21,28,37,56] | NOT FOUND (same encodings/scales) |

#### Why empirical-value searches failed

The empirical values are raw 12-bit nibble-split CAN count deltas from the 0x212 signal (`((B4 & 0x0F) << 8) | B5`, zero at 2000). These are CAN-bus-side counts, not firmware-internal torque units. The firmware computes gradient limits in an internal fixed-point representation and applies an unknown scale + offset before packing the result into the 12-bit CAN field. The 0.244 Nm/count scale estimate is OLS-derived and **explicitly unconfirmed**; the true scale is not known from static analysis alone.

Without knowing the CAN-to-internal-unit scale factor, neither the LUT Y-values nor the X-axis breakpoints can be predicted from CAN observations. In addition, the TrqLast X-axis likely contains signed (negative) torque values stored as large unsigned 16-bit words, which the monotone-sequence brute-force scan missed by restricting to the range 10–2000.

**Conclusion:** the gradient table binary locations cannot be found by pattern-matching empirical CAN values. The correct approach is to trace which CAL addresses the firmware gradient limiter code actually loads, using Ghidra disassembly of the DBC0 / DBEEx region (see §10.7 sections below).

---

## Goal 3: MCM 0x1C0 Motor CAN receive path and filter input (2026-05-01)

**Scripts:** `antilash_search_p6.py`, `antilash_search_p6b.py`, `antilash_search_p7.py`, `antilash_search_p8.py`, `antilash_search_p8b.py`

### Background

The MCM (UQM PowerPhase 100) communicates with the DLCM on a private Motor CAN sub-bus not accessible from the OBD-II port. The MCM transmits telemetry including motor speed, HV voltage, HV current, and torque feedback. This investigation traces whether motor speed feeds into the DLCM's torque control path — either as input to the C630 IIR filter or as a control input to some other downstream computation.

The 0x1C0 message encoding (confirmed from correlation analysis elsewhere):

| Field | Bytes | Encoding |
|-------|-------|---------|
| Motor_Torque | B0-B1 | LE uint16, x0.1 Nm, offset -3212.8 |
| HV_Voltage | B2-B3 | (details TBD) |
| HV_Current | B4-B5 | (details TBD) |
| Motor_Speed | B6-B7 | LE uint16, x0.5 rpm, offset -16064 |

### Key SRAM address

The main task loop init (at `0x800676B8`) loads R13 from pool:

```
800676B8  DD43  MOV.L @pool,R13 ; pool[800677C8]=0xD9047B5C
```

R13 = `0xD9047B5C` is the base of the torque/filter input struct. The main loop reads the filter input at:

```
8006A072: MOV.L @(0x30,R13),R8   ; R8 = [0xD9047B8C]
8006A09C: MOV.L @(0x30,R13),R8   ; same, second use per frame
```

**R13+0x30 = 0xD9047B8C is the filter input SRAM cell.** This is the value written to the circular buffer at `0x7F0F0880` and processed by the C630 filter.

### 0x1C0 transmit mechanism: NOT NOP.X

The standard CAN TX pattern in this firmware is `MOV.W @pool,R1 ; R1=CAN_ID` followed immediately by `NOP.X (0x00F8)`. This pattern is used for 0x212, 0x211, 0x00FD, and ~130 other TX stubs throughout `0x8007xxxx-0x8009xxxx`.

The 0x01C0 CAN ID does NOT use this pattern anywhere in PROG. Instead, the only occurrence of 0x01C0 as a pool word is at `0x8008D2F0`:

```
8008D2F0  9BF0  MOV.W @pool,R11 ; pool[8008D4D4]=0x01C0   <- load CAN ID
8008D2F8  A66F  BRA  0x8008DFDA                            <- jump to TX function
```

This uses a different TX mechanism: the CAN ID is loaded into R11 (not R1), and the code branches to a dedicated TX handler at `0x8008DFDA` rather than triggering via NOP.X. The D-CAN rebroadcast of MCM telemetry uses a separate code path from all other TX stubs.

### 0x1C0 receive and D-CAN rebroadcast path (confirmed)

The DLCM receives MCM Motor CAN frames in a large monolithic function spanning at least `0x8008B000-0x8008D800`. No function prologues (`STS.L PR,@-R15` / `0x4F22`) exist anywhere in `0x8008D000-0x8008E000`, confirming this is one flat function block with multiple BRA entry points.

Two caller paths feed into the rebroadcast sequence at `0x8008D2EC`:

| Caller | Entry target | Description |
|--------|-------------|-------------|
| `0x8008C4EC` | `BRA 0x8008D2EC` | Skips BSR CACE decode — MCM data already processed |
| `0x8008C5DA` | `BRA 0x8008D2DC` | Calls BSR CACE decode at `0x8008D2EA` first |

After both paths converge, the rebroadcast sequence runs:

```
8008D2EE  542F  MOV.L @(0x3C,R2),R4   ; R2 = CAN rx buffer; R4 = decoded MCM field
8008D2F0  9BF0  MOV.W @pool,R11        ; R11 = 0x01C0 (D-CAN rebroadcast ID)
  ...
8008D2F8  A66F  BRA  0x8008DFDA        ; jump to D-CAN TX function
8008D2FA  742F  ADD #47,R4              ; (delay slot: bias applied to field before TX)
```

The `BSR 0x8008CACE` decode sub (when called via path B) repeatedly does `CMP/EQ #47,R0` checks and writes decoded values to `R2+0x3C` — consistent with extracting a specific byte-value from the MCM payload and storing it back into the CAN buffer struct.

The DLCM also handles at least two other MCM Motor CAN IDs in the same block:
- `0x01C8` (456) — found at `0x8008C5E8`
- `0x01D0` (464) — found at `0x8008C374`
- `0x00F0` (240) — found at `0x8008CF6E`

The MCM likely transmits on multiple IDs for different data categories.

### MCM data stored to SRAM struct (tentative — R10 unconfirmed)

Inside the same monolithic function, at addresses `0x8008D16A`–`0x8008D1FA`, there are six writes of MCM decoded fields to struct offset +0x30:

```
8008D16A  14AC  MOV.L R4,@(0x30,R10)
8008D170  14AC  MOV.L R4,@(0x30,R10)
8008D17E  14AC  MOV.L R4,@(0x30,R10)
8008D1B0  14AC  MOV.L R4,@(0x30,R10)
8008D1B8  18AC  MOV.L R8,@(0x30,R10)
8008D1FA  10AC  MOV.L R0,@(0x30,R10)
```

These writes store different MCM payload fields (R0, R4, R8 hold different decoded values) into offset +0x30 of whatever struct R10 points to.

Also, in the outer caller context around `0x8008D730` (the BSR that enters `0x8008D11A`), the same offset is written using R12 as the base:

```
8008D6F6  18CC  MOV.L R8,@(0x30,R12)
8008D708  18CC  MOV.L R8,@(0x30,R12)
8008D760  18CC  MOV.L R8,@(0x30,R12)
```

**Hypothesis (not confirmed):** R10 and R12 both hold `0xD9047B5C` = R13 in the main loop. If true, these writes update the filter input cell at `0xD9047B8C` with motor speed (or another MCM field) each time the MCM CAN handler fires. The main loop then reads this value as R8 = [R13+0x30] on the next 20 ms tick.

**Why unconfirmed:** The struct base address `0xD9047B5C` is only loaded from pool in three places — all in the outer task init region (`0x800670F8`, `0x80067642`, `0x800676B8`) — and none of them are in the MCM receive handler. No `MOV.L @pool,R10 = 0xD9047B5C`, no `MOV Rn,R10`, and no `MOV.L @(GBR+n),R0; MOV R0,R10` sequence was found anywhere in `0x8008A000-0x8008D200`. R10 must be set in the function prologue far before the 0x8008D000 boundary, but the entire region `0x80080000-0x8008E000` contains zero `STS.L PR,@-R15` prologues — this is a flat, prologue-free monolithic block. Confirming R10's value requires full register propagation analysis (Ghidra or manual trace from the function's outer entry point).

### Outer task init struct writes (tentative)

In the outer task init region starting at `0x800670F8`:

```
800670F8  D9FF  MOV.L @pool,R9 ; pool=0xD9047B5C   <- R9 = struct base
800670FE  BF2F  BSR  0x80066F60                      <- calls refresh sub (R9 as param?)
```

After the BSR returns, multiple writes occur to `@(0x30,R14)`:

```
8006719A  18EC  MOV.L R8,@(0x30,R14)
80067242  18EC  MOV.L R8,@(0x30,R14)
8006726E  18EC  MOV.L R8,@(0x30,R14)   (+ 2 more)
```

If R14 = R9 = `0xD9047B5C` at those points, these writes place the current MCM-sourced value into the filter input cell before the main loop iteration. This would be the "double-buffer copy" path: MCM handler writes to one buffer, outer init copies to main struct. **This is not confirmed** — R14's value at those addresses was not traced.

### Summary of what is and is not confirmed

| Claim | Status |
|-------|--------|
| 0x1C0 TX uses BRA 0x8008DFDA, not NOP.X | **Confirmed** |
| 0x1C0 rebroadcast entry points at 0x8008C4EC / 0x8008C5DA | **Confirmed** |
| MCM data decoded by BSR 0x8008CACE (CMP/EQ #47 dispatch) | **Confirmed** |
| DLCM handles 0x01C0, 0x01C8, 0x01D0, 0x00F0 from MCM | **Confirmed** |
| @(0x30,R10) writes at 0x8008D16A-D1FA store MCM decoded fields | **Confirmed** |
| R10 = R13 = 0xD9047B5C (struct_base) in that context | **Hypothesis — unconfirmed** |
| R13+0x30 = 0xD9047B8C is the filter input cell | **Confirmed** |
| Motor speed from 0x1C0 is the filter input | **Hypothesis — unconfirmed** |

### Next step to confirm

Run Ghidra on `coda_dlcm_prog.bin` with load address `0x80040000`. Find the function that contains `0x8008D11A` and trace the entry point where R10 is initialized. Also check: **does any code path write to absolute SRAM address `0xD9047B8C`?** Ghidra's "References to" on that address would answer both the R10 question and the write-source question directly.

---

## Goal 3 supplement: Ghidra MCM handler analysis — filter selector architecture (2026-05-01)

**Script:** `DlcmMcmHandler.java` (in `%LOCALAPPDATA%\ghidra-projects\`)

**Output:** `%LOCALAPPDATA%\ghidra-projects\dlcm_export\mcm_handler_analysis.txt`

### SLEIGH stubs added (session 2026-05-01)

Ran `antilash_search_p9c_gap_scan.py` against the `B000-E000` MCM handler region plus the `A000-B000` state machine region. Found and added 184 new NOP stubs to `SuperH4.sinc`:

| Batch | Count | Source |
|-------|-------|--------|
| Gap-scan unknowns (D100-D240, D680-D800, B300-BA00, A000-B000) | 135 | `p9c_gap_scan.py` combined output |
| FP op3=F (SH-4A FMOV XD variants, `1111nnnnmmmm1111`) | 30 | Missed by scanner: `is_standard_sh4_strict` returned True for all op0=F unconditionally |
| op0=8 invalid sub-opcodes (sub=A, C, E, F not in standard SH-4 `0x8x__` group) | 19 | False positive: scanner accepted sub=A which is undefined in SH-4; `0x8A0E` at D164 was blocking disassembly |

Total stub count after this session: **539**. Zero duplicates (verified by scan).

Critical blocker was `0x8A0E` at `0x8008D164` — it fell in the delay slot of a BSR at D162, and the strict scanner incorrectly classified it as valid SH-4 (op0=8, sub=A). Once the 19 op0=8 stubs were added, D164 disassembled and D11A decompiled successfully.

### @(0x30,Rx) write site analysis — corrected pattern

The six write sites in `0x8008D16A-0x8008D1FA` were previously described with uncertain Rx. Ghidra confirmed:

```
8008D16A  14AC  MOV.L R4,@(0x30,R4)   ; R4 = struct pointer; written with R4 (self-base write — R4 is ALSO the value)
8008D170  14AC  MOV.L R4,@(0x30,R4)
8008D17E  14AC  MOV.L R4,@(0x30,R4)
8008D1B0  14AC  MOV.L R4,@(0x30,R4)
8008D1B8  18AC  MOV.L R8,@(0x30,R8)   ; R8 = struct pointer; written with R8
8008D1FA  10AC  MOV.L R0,@(0x30,R0)   ; R0 = struct pointer; written with R0
```

**Correction from earlier notes:** The source and base register are the SAME register in each case (opcode `0x14AC` = MOV.L Rn,@(disp,Rm) with Rn=R4, Rm=R4 both encoded as `4`). R4 is simultaneously the value written AND the struct base. This changes the interpretation: D11A is not writing a computed torque value to a struct — it is writing a struct pointer address value into a field of that same struct (a self-referential pointer initialization, or the compiled output of `struct->field = (int)struct` which is how Ghidra renders a struct self-registration pattern).

This means the `R10 = struct base = 0xD9047B5C` hypothesis for D16A-D1FA is wrong as stated: the value written at +0x30 is the struct pointer itself, not the motor speed sample.

### D11A decompile summary

Ghidra produced a partial decompile for `FUN_8008d11a` (body D11A-D145):

```c
void FUN_8008d11a(undefined4 param_1, double param_2, double param_3, int param_4, ...) {
  // FP arithmetic on param_2, param_3
  *(int *)(iVar10 + 0x30) = iVar13;    // write computed value to struct[+0x30]
  *(int *)(iVar10 + 0x30) = iVar13;    // (four writes, different struct instances)
  *(int *)(iVar10 + 0x30) = iVar13;
  *(int *)(iVar10 + 0x30) = iVar13;
}
```

`iVar10` is an intermediate value derived from the input params, and `iVar13` is the computed filter output. Ghidra's intermediate variable naming obscures the actual registers. The four writes to `iVar10+0x30` correspond to the four write sites at D16A/D170/D17E/D1B0 — each targeting a different struct instance.

### D730 decompile summary — filter selector

`FUN_8008d730` (body D730-E3B3, a very large function spanning ~4KB):

```c
void FUN_8008d730(int param_1, undefined1 *param_2, int param_3) {
  FUN_8008d11a();        // first instruction: call inner MCM decode
  // ... CMP/EQ R8,R12
  // ... CMP/EQ R11,R12
  *(int *)(... + 0x3C) = ...; // write to output slot +0x3C
  *(int *)(... + 0x3C) = ...;
}
```

The `CMP/EQ R8,R12` and `CMP/EQ R11,R12` comparisons after the D11A call are the filter-instance selector: they determine which of the parallel filter instances' output (+0x3C slot) to forward as the active output. Offset +0x30 = filter input slot (written by D11A); offset +0x3C = output/result slot (written by D730 after D11A returns).

### D530 decompile summary — multi-instance initialization

`FUN_8008d530` initializes multiple filter instances simultaneously:

```c
*(unaff_r8 + 0x30) = 0x18AC590F;    // init instance A input slot
*(unaff_r12 + 0x30) = 0x18AC590F;   // init instance B input slot (same constant)
*unaff_r13 = iVar2;                  // write to *R13 (struct base slot)
```

`0x18AC590F` is the initialization constant for the filter input slot. Both R8 and R12 instances are written identically at startup. `unaff_r13` in Ghidra notation means R13 is not modified by D530 itself — it is passed in from the outer caller. R13 = `0xD9047B5C` (confirmed from outer task init analysis).

At D708 (in the D700 caller function, before BSR D530):
```
8008D708  18CC  MOV.L R8,@(0x30,R12)   ; write R8 to instance C input slot
```
This is a third instance being updated before D530 is called to handle the other two.

### Filter selector architecture: multiple parallel states

**Motor speed (or other MCM data) is a filter-selector input, not a direct filter input.**

The evidence:

1. **D11A feeds multiple struct instances simultaneously** — it writes the same computed value to four different `iVar10+0x30` slots. Each instance is a separate filter state (separate delay buffer, coefficients, or both).

2. **D530 initializes R8+0x30 and R12+0x30 with the same constant** — two instances start from the same reset state.

3. **D730's CMP/EQ R8,R12 / CMP/EQ R11,R12 logic selects one instance's output** — depending on which comparison passes, a different struct's +0x3C slot is written as the active output. This is a run-time switch between parallel filter states.

4. **D700 writes R8 to @(0x30,R12) before calling D530** — the selector context (which instance is "current") is established by the outer dispatcher before D11A/D530 run.

**Architecture interpretation (hypothesis):** The DLCM maintains 2-4 parallel filter instances, each representing a different operating state (e.g., motoring, regenerating, stopped, post-brake-release). Motor speed (or a state code derived from it) is used to select which filter instance's output to route to the torque command. All instances are updated each MCM tick (D11A writes all of them), but only the "active" instance's +0x3C output is forwarded. This is consistent with the observed anti-lash behavior: after a direction reversal, the firmware switches to a different filter state (with its own internal state history) rather than recalculating from the same filter state.

**This is a hypothesis** — the specific condition checked by CMP/EQ (whether it is motor speed, a gear/direction flag, or a braking state bit) and the number of parallel instances were not confirmed in this session.

### Remaining unknowns

| Unknown | Status |
|---------|--------|
| What value R8 and R12 hold at D16A write sites (struct base addresses) | Requires full register trace from 0x8008B000 entry — static analysis blocked by no-prologue monolithic block |
| Whether R8 or R12 == 0xD9047B5C (linking MCM handler to main loop filter input) | Hypothesis — not confirmed |
| What condition D730 CMP/EQ R8,R12 actually checks | Not determined; R8 and R12 sources unknown |
| Number of parallel filter instances | 2-4 based on write count; not confirmed |
| Whether filter selector state is motor speed, direction flag, or brake flag | Not determined |

---

## Goal 4: Brake switch and sensor input path — GBR inter-task architecture (2026-05-02)

**Script:** `projects/coda/notes/artifacts/brake_sw_trace.py` (phases 1-13)

### Background

The DBC has BrakeSW in three DLCM-transmitted messages (0x200 B1.0, 0x212 B2.0, 0x315 B0.0). The accelerator pedal (ThottlePedalPos) is also DLCM-transmitted (appears on D-CAN as 0x210 via GWM rebroadcast). Both signals originate as hardware inputs read by the DLCM itself. This investigation traces how those inputs reach the CAN TX packing code and the MCM handler filter.

### GBR is a fixed hardware-initialized global (confirmed)

Zero `LDC Rn,GBR` (opcode `4n1E`) instructions exist anywhere in the 1.8 MB binary. GBR is set once at hardware reset and never changed by software. All code regions — sensor processing (0x8005xxxx), CAN TX (0x8006-8007xxxx), and MCM handler (0x8008xxxx) — share the same GBR base. GBR-relative cells are the only shared memory accessible to all three regions simultaneously.

`GBR+0x1FE` appears 81 times as a read (opcode `C5FF`) and zero times as a write — it is a read-only boot-time calibration constant, not a runtime sensor value.

### Three-region SRAM partition (confirmed)

Each major code region uses a distinct SRAM page:

| Region | SRAM range used | Unique addresses |
|--------|----------------|-----------------|
| 0x8005xxxx (sensor processing) | 0xD90Fxxxx | 478 |
| 0x8006-8007xxxx (CAN TX) | 0xD902xxxx, 0xD904xxxx | 449 |
| 0x8008xxxx (MCM handler) | 0xD90Fxxxx, 0xD90Cxxxx | 20 |

CAN TX and MCM handler share **zero** SRAM addresses. 0x8005xxxx and MCM handler also share zero SRAM addresses despite using the same 0xD90Fxxxx prefix. **All inter-region communication flows exclusively through GBR cells**, not SRAM.

### Sensor → GBR → consumer path

The 0x8005xxxx sensor processing region reads hardware sensor data from SRAM (populated by ISR) and stages results into GBR cells via a recurring pattern:

```
C008  MOV.B R0,@(0x08,GBR)   ; write sensor byte to GBR+0x08
BBF0  BSR   0x80056F0A        ; call staging function
  80056F0A:  C0F1  MOV.B R0,@(0xF1,GBR)   ; ALSO writes R0 to GBR+0xF1
```

The same R0 value is written to both GBR+0x08 and GBR+0xF1 on each call. Two consumers then read from these cells:

| GBR cell | Consumer | Location | Use |
|----------|----------|----------|-----|
| GBR+0xF1 | CAN TX packing | `0x80079FEE` | Single read — stages byte into CAN TX buffer for 0x200 |
| GBR+0x08 | MCM handler filter | `0x8008A886` (×8) | 8 reads in MCM handler — filter state machine input |

GBR+0x08 is heavily written throughout 0x8005xxxx (sensor processing) and the CAN TX region (0x8006-8007xxxx), and read 8 times by the MCM handler. It is the primary inter-task communication channel between the sensor layer and the filter.

### Brake switch and pedal: same source path

Both the brake switch and the accelerator pedal:
- Originate from the 0x8005xxxx sensor processing region
- Flow through GBR+0x08 and GBR+0xF1
- Are consumed by the MCM handler (via GBR+0x08) on every MCM CAN tick

The two signals diverge only downstream:
- **Brake switch** → GBR+0xF1 → `0x80079FEE` → packed into 0x200/0x212/0x315
- **Accelerator pedal** → transmitted by DLCM on MCM sub-bus (no `pool=0x0210` TX site with NOP.X found on D-CAN bus path; GWM rebroadcasts as 0x210 on D-CAN)

Because both pass through GBR+0x08, the MCM handler filter reads both on every MCM handler invocation. Whether the filter selector (the CMP/EQ R8,R12 logic in D730) uses the brake state, the pedal state, or something else derived from GBR+0x08 is not yet determined.

### No TST/AND #1 in CAN TX region (confirmed)

No `TST #1,R0` (opcode `C801`) or `AND #1,R0` (opcode `C901`) appears anywhere in 0x8006xxxx. The brake switch bit is pre-extracted to a full byte (0 or 1) in the 0x8005xxxx sensor processing layer before it reaches the CAN TX packing code — the packing loop does not need to mask it.

### 0x0210 TX mechanism

No `MOV.W pool=0x0210, R1; 00F8` pattern exists anywhere in the binary. The word constant 0x0210 appears only once (at 0x80089146, in the MCM handler, loaded into R10 — not R1 — in a context without a following 00F8). The pedal is transmitted by DLCM on the MCM sub-bus under a different CAN ID; the 0x210 visible on D-CAN is a GWM gateway rebroadcast.

### Relevance to filter

The MCM handler filter state machine (D11A → D730) receives brake and pedal state via GBR+0x08 on every MCM CAN tick. The filter selector (CMP/EQ comparisons in D730) likely uses this value to determine which parallel filter instance's output to forward as the active torque command. The brake switch as a filter selector input is consistent with the observed anti-lash timing: engaging the brake would cause D730 to switch to a different filter instance (one initialized to zero or a hold state), then releasing the brake returns to the motoring filter instance.

## Goal 5: ESC wheel speed as filter selector input — GBR cross-reference (2026-05-02)

The working hypothesis from Goal 3 was that motor speed from the MCM's 0x1C0 message drives the filter selector. The user proposed an alternative: **ESC wheel speed**, received from the ESC on D-CAN, may be the actual filter input — more reliable than motor speed (which is indirect), and directly available to the DLCM as a D-CAN participant.

### DBC context

From `CODA-D-CAN.dbc`:
- **BO_ 512 (0x200): ESC_FrontWheelSpeeds** — transmitted by ESC, 200 Hz. Signals: `WheelSpeed_LF`, `WheelSpeed_RF`, zero-value encoding `0xC000`, SubFrameID mux.
- **BO_ 520 (0x208): ESC_BrakePressure** — transmitted by ESC. Signals: `ESPSysSts`, `BrakePressure`, `WheelSpeed_RR`, `WheelSpeed_LR`. DLCM is an **explicit receiver** in the DBC attribute list.

### GBR shared-cell cross-reference (Phase 15)

Full scan of all GBR writes in 0x8005xxxx (sensor/receive handler region) and GBR reads in 0x8008xxxx (MCM handler region) yielded **12 shared GBR cells** — cells written by the ESC receive handler and read by the MCM filter handler:

| GBR offset | Writes (8005) | Reads (8008) | Notes |
|------------|--------------|--------------|-------|
| GBR+0x000 | 4 | 12 | |
| GBR+0x008 | **624** | **53** | Primary inter-task channel |
| GBR+0x010 | 3 | 2 | |
| GBR+0x020 | 14 | 12 | Used as struct pointer in MCM |
| GBR+0x040 | 5 | 13 | Used as struct pointer in MCM |
| GBR+0x074 | 1 | 1 | |
| GBR+0x07C | 18 | 6 | Struct pointer; MCM writes then reads |
| GBR+0x0E8 | 2 | 1 | |
| GBR+0x0FE | 1 | 1 | |
| GBR+0x3C0 | 8 | 3 | |
| GBR+0x3C4 | 6 | 1 | |
| GBR+0x3FC | 16 | 1 | |

**GBR+0x116** (written at 0x8005172A near the first 0x0208 dispatch hit) is **not** in this set — the MCM handler never reads it. It is not the ESC→MCM channel.

### GBR+0x008 confirmed written by ESC 0x0208 handler body (Phase 18)

The 0x0208 dispatch at 0x80051DEC contains `94F1 MOV.W pool=0x0208,R4` followed by `A460 BRA 0x800526C2` — an unconditional jump to the actual handler body. The chain continues: 0x800526C2 → `A040 BRA 0x80052746` → `A3B0 BRA 0x80052EC4`.

Phase 18-B found **9 GBR+0x008 writes** in the 0x80052600–0x80052A00 block that contains this handler body — the most of any region examined. The pattern at each write site is:

```
C008  MOV.B R0,@(0x08,GBR)    ; commit processed value to primary inter-task byte
Axxx  BRA   <next_handler>    ; or BSR to sub-handler
```

GBR+0x008 writes within this block are followed by BRAs to 0x80052A4E, 0x80052A8A, 0x80052AD4 — three different continuation targets, suggesting the handler branches on a sub-field of the 0x0208 CAN frame before committing to GBR+0x008.

Several writes use GBR+0x03C as an intermediate: `C60F MOV.L @(0x03C,GBR),R0 ... C008 MOV.B R0,@(0x08,GBR)`. GBR+0x03C is not in the MCM shared-cell set; it is an internal staging register within the ESC handler, not directly read by the MCM.

### GBR+0x040 — shared pointer cell

GBR+0x040 is a 32-bit cell written 5 times in 0x8005xxxx (first write at 0x80052258, 1132 bytes past the 0x0208 dispatch at 0x80051DEC) and read 13 times by the MCM handler. In the MCM handler it is loaded as a long and used as a struct base pointer:

```
C610  MOV.L @(0x040,GBR),R0   ; load pointer
...
MOV.L R15,@(0x04,R0)          ; write to struct field at [R0+4]
```

At MCM read site 0x800881DE, the sequence `C610 ... C24F MOV.L R0,@(0x13C,GBR) ... C008 MOV.B R0,@(0x08,GBR)` shows GBR+0x040 being read, saved to GBR+0x13C, then R0's low byte committed to GBR+0x008 — suggesting GBR+0x040 feeds GBR+0x008 in this path.

### Refocus: 0x0200 front wheel speeds

The DBC identifies 0x0200 as ESC_FrontWheelSpeeds (WheelSpeed_LF, WheelSpeed_RF, 200 Hz). Front wheel speed is a cleaner proxy for vehicle velocity than rear wheel speed or motor speed; it is the more likely candidate for the anti-lash filter selector.

Key 0x0200 non-TX hits in 0x8005xxxx (from Phase 14-A):

| Address | Load | Notes |
|---------|------|-------|
| 0x80050C3C | `MOV.W pool=0x0200,R4` next=82F1 | ESC handler region |
| 0x80050F7E | `MOV.W pool=0x0200,R8` next=49FF | ESC handler region |
| 0x800520D2 | `MOV.W pool=0x0200,R4` next=02F8 | Near 00FD sites |
| 0x800520EE | `MOV.W pool=0x0200,R4` next=02FF | Near 00FD sites |
| 0x800527BC | `MOV.W pool=0x0200,R8` next=14FF | **Inside the 0x0208 handler body** (same 0x80052600 block) |
| 0x8005A3A8 | `MOV.W pool=0x0200,R4` next=3E04 | Deeper in 0x8005xxxx |

The hit at 0x800527BC is significant: it is inside the same 0x80052600–0x80052A00 block as the 0x0208 handler body, suggesting a combined ESC receive handler that processes both 0x0200 and 0x0208 in the same code region. The 0x80050C3C and 0x80050F7E hits are the earliest 0x0200 references in 0x8005xxxx — these are the candidate dispatch entry points for ESC_FrontWheelSpeeds.

### 0x0200 front wheel speed receive handler (Phase 19)

**Key negative result — Phase 19-C:** Zero instances of `MOV.W pool=0x0200,R? ; 00FD` anywhere in the binary. The `00FD` filter setup opcode is **never** used for CAN ID 0x0200. The front wheel speed message is received via a different mechanism than the 0x0208 rear wheel/brake-pressure message.

**Handler body at ~0x80050F7E:** The `MOV.W pool=0x0200,R8` at 0x80050F7E loads the CAN ID into R8, surrounded by a loop structure with backward conditional branches (`8FF0/8FF1`) — the same iteration pattern as the 0x0208 handler body. Phase 19-B finds **5 GBR+0x008 writes within 250 bytes** of this pool load:

| Address | Dist | Pattern |
|---------|------|---------|
| 0x80050FDE | +96 | `C008; BBF0 BSR 0x800507C4` |
| 0x80050FEC | +110 | `C008; 3E04` (after `C60F MOV.L @(0x03C,GBR),R0`) |
| 0x80051064 | +230 | `C008; 02F8` |
| 0x8005106A | +236 | `C008; BBF0 BSR` |
| 0x80051078 | +250 | `C008; 3E04` |

This is the same alternating `C008; BSR; C60F @GBR+0x03C; C008` double-write pattern confirmed in the 0x0208 handler body. **Front wheel speed data writes GBR+0x008 (primary MCM inter-task channel)** — the same cell the MCM filter reads 53x.

**GBR+0x0F1 write at 0x80050C88 (+76 bytes from 0x80050C3C hit):** The 0x80050C3C region also triggers a GBR+0x0F1 write at 0x80050C88 — the same cell that feeds the 0x200 CAN TX staging (from Goal 4 analysis). This suggests the DLCM's 0x0200 receive handler forwards a derived byte into GBR+0x0F1 for relay via the motor-bus 0x200 TX.

**Pool constant `0x10010200` at 0x8005117A:** The 4-byte pool at 0x80051178 = `0x10010200`. The high word `0x1001` is a SubFrameID mux selector for ESC_FrontWheelSpeeds; the low word `0x0200` is the CAN ID. The DBC for BO_ 512 (0x0200) uses SubFrameID as a mux signal — SubFrameID 0x1001 selects one of the `WheelSpeed_LF` / `WheelSpeed_RF` values.

### Summary: ESC wheel speed → GBR+0x008 → MCM filter path confirmed

Both ESC receive handlers (0x0200 front wheels, 0x0208 rear wheels + brake pressure) write GBR+0x008. The front wheel handler at 0x80050F7E does so with 5 writes in a ~250-byte region using the same code pattern as the rear/brake handler. GBR+0x008 is the aggregated sensor state byte written by all 0x8005xxxx handlers and read 53x by the MCM filter handler (0x8008xxxx). **ESC wheel speed (both front and rear) is confirmed in the data path to the MCM filter selector.**

### Pre-commit BSR bodies (Phase 20)

Both the 0x0200 and 0x0208 handlers call a BSR immediately before/after each GBR+0x008 commit:
- **BSR 0x800507C4** — called by 0x0200 handler (at 0x80050FDE)
- **BSR 0x80051FCC** — called by 0x0208 handler (at ~0x800527E8)

Phase 20 results:
- **Zero GBR writes** inside either BSR body — they are read-only relative to GBR
- Both bodies read **GBR+0x040** (`C610 MOV.L @(0x040,GBR),R0`) as a receive buffer pointer and navigate the CAN frame struct with fixed offsets
- BSR 0x800507C4 computes `ADD #95,R0; MOV.W @R0,R13` — reads a 16-bit word at buffer+0x5F (field 47 of the receive struct, likely a processed speed value or sequence counter)
- BSR 0x80051FCC additionally reads **GBR+0x03C** (`C60F MOV.L @(0x03C,GBR),R0`) and does `MOV.L @(0x3C,R0),R15; CMP/EQ R0,R14` — a struct dereference with equality check

The caller's double-write pattern around each BSR:
```
C008  MOV.B R0,@(0x08,GBR)   ; pre-commit
BBF0  BSR <handler_sub>       ; call with receive buffer pointer in registers
FF0F  (delay slot / pool)
C60F  MOV.L @(0x03C,GBR),R0  ; reload GBR+0x03C
C008  MOV.B R0,@(0x08,GBR)   ; post-commit (potentially updated value)
```

### GBR+0x03C — byte cell, not a pointer (Phases 21-22)

Phase 21 binary-wide search: **exactly one write** to GBR+0x03C in the entire 1.8 MB binary:

| Address | Opcode | Instruction | Region |
|---------|--------|-------------|--------|
| 0x80074C4C | C03C | `MOV.B R0,@(0x3C,GBR)` | 0x8007xxxx |

This is a **byte write** (sub=0, off=0x3C), not a longword write. The same code block writes GBR+0x008 with the same R0 value at 0x80074C42:
```
80074C3A  B93C  BSR 0x80073EB6        ; call returns value in R0
80074C42  C008  MOV.B R0,@(0x08,GBR) ; -> GBR+0x008 (inter-task byte)
80074C4C  C03C  MOV.B R0,@(0x3C,GBR) ; -> GBR+0x03C (same R0)
80074C56  BBE0  BSR 0x8007441A        ; follow-up call
```

Phase 22-D: The adjacent bytes completing the 32-bit GBR cell at 0x3C–0x3F:
- GBR+0x3C: runtime byte write from 0x80074C4C (dynamic)
- GBR+0x3D: **never written anywhere** in binary — defaults to 0x00 at startup
- GBR+0x3E..0x3F: word write at 0x80045F16 (init region, startup only) + byte at 0x80045366

GBR+0x3C is therefore a **byte-sized status/selector value** that happens to live at the start of a 4-byte GBR cell whose other three bytes are static. The `C60F MOV.L @(0x03C,GBR),R0` reads in the ESC BSR bodies load all 4 bytes together as a packed value; R0 is then used for comparison (`CMP/EQ R0,R14`) or offset arithmetic (`ADD #127,R0`), not as a raw SRAM dereference pointer.

### 0x8007xxxx — full CAN receive processing region (Phase 22)

Initial labeling of 0x8007xxxx as "CAN TX region" was incorrect. Phase 22-F shows it is a full CAN receive processing hub:

| GBR cell | Writes in 0x8007xxxx | Shared with MCM |
|----------|---------------------|-----------------|
| GBR+0x008 | **431** | yes |
| GBR+0x07C | **120** | yes |
| GBR+0x040 | 31 | yes |
| GBR+0x03C | 1 | no |
| (51 cells total) | | |

GBR+0x008 is written **431 times in 0x8007xxxx** vs 624 times in 0x8005xxxx. Both regions are independent CAN receive processing hubs writing the same MCM inter-task byte.

**GBR+0x040 — global receive buffer pointer:** Written **111 times across the entire binary** (0x8004, 0x8005, 0x8006, 0x8007, 0x8008 regions all write it). Every CAN message handler updates GBR+0x040 with the current frame's buffer address before processing. The ESC pre-commit BSRs read GBR+0x040 to locate the CAN frame data they need.

**Phase 22-B note:** The 00FD filter setup search in 0x8007xxxx produced only false positives — all matches had `pool=0x00FD` or `pool=0xD9FF`, caused by the degenerate `9100` (disp=0) encoding where the pool address equals the next instruction address. No real CAN IDs (0x0100–0x07FF) were found as pool values in these matches. A corrected search filtering for legitimate CAN ID pool values is needed to identify which messages 0x8007xxxx handles.

### CAN IDs handled by each region (Phase 23)

> **SUPERSEDED 2026-09-24.** The Motor CAN ids named here (`0x0048`, `0x0100`,
> `0x0222`, `0x0500`, `0x02FF`) are artefacts of the SH-4 decode and appear nowhere
> in the firmware's CAN configuration tables. See
> [The firmware's own CAN configuration tables](#the-firmwares-own-can-configuration-tables--full-message-inventory-2026-09-24)
> for the real inventory.

Phase 23 searched for corrected 00FD filter setups (pool value in 0x0001–0x07FF, non-degenerate displacement) in both regions.

**0x8007xxxx — only ONE legitimate receive filter:**

| CAN ID | Address | Notes |
|--------|---------|-------|
| 0x0100 | 0x8007C1D6 | Only inbound message in entire 0x8007xxxx region |

Phase 23-D found only 10 non-degenerate 00FD opcodes in all of 0x8007xxxx; every pool value except 0x0100 exceeds 0x7FF and is not a valid 11-bit CAN ID. **0x8007xxxx is primarily a CAN TX signal-construction region.** *(revised in Phase 27: reclassified as B-CAN receive region; 00F8 = Motor CAN TX, not D-CAN TX)* The 431 GBR+0x008 writes are part of building outgoing CAN frames — staging signal values into GBR cells before 00F8 TX triggers — not receive processing. It receives exactly one inbound message: 0x0100.

CAN ID 0x0100 context at 0x8007C1D6: after the 00FD filter there is `BF/S 0x8007C0E0; MOV.B R1,@R0`, then reads of GBR+0x1E8 and GBR+0x000. This is in a loop body (`BF/S 0x8007C1C6` at 0x8007C1E2 loops back). The 0x0100 ID may be a motor-bus feedback message from the MCM reporting its own state to the DLCM.

**0x8005xxxx — confirmed receive filters:**

| CAN ID | Address | Notes |
|--------|---------|-------|
| 0x0208 | 0x80055E88 | ESC_BrakePressure (confirmed from DBC) |
| 0x0500 | 0x800590CA, 0x80059606, 0x800596D6 | 3 setups — mux or multi-instance |
| 0x0222 | 0x800535BC | Single filter setup |
| 0x0048 | 0x80051DA4 | Single filter setup |

(Several 0x00FD and 0x02FF pool values also appear; 0x00FD may be a diagnostic bus address and 0x02FF may be an internal protocol marker — neither confirmed as vehicle CAN IDs.)

**Conclusion:** The 431 GBR+0x008 writes in 0x8007xxxx are TX-side signal staging, not received wheel speed or brake data. The MCM torque filter path runs through the ESC receive side (0x8005xxxx) exclusively for ESC messages. The unidentified 0x0500, 0x0222, and 0x0048 receive handlers in 0x8005xxxx are new leads.

### Motor CAN message identification — UQM PID file

`projects/coda/notes/UQM-PID-20240123.csv` is a Thunderstruck Motors OBD diagnostic PID file (not raw CAN broadcasts). It uses UDS service 0x22 (ReadDataByIdentifier) with DIDs 0xDD10–0xDD15, broadcast to address 0x7DF. The DLCM proxies these diagnostic requests from D CAN to the MCM over Motor CAN and forwards the response back — this is why the MCM is accessible via OBD-II despite being on a private sub-bus.

| DID | Signal | Encoding | Units |
|-----|--------|----------|-------|
| 0xDD10 | IGBT temp (B), Inverter temp (A) | byte − 40 | °C |
| 0xDD11 | Rotor temp (A), Stator temp (B) | byte − 40 | °C |
| 0xDD12 | Battery voltage | LE uint16, (val − 32128) / 10 | V |
| 0xDD13 | Motor torque | LE uint16, (val − 32128) / 10 | Nm |
| 0xDD14 | Current | LE uint16, (val − 32128) / 10 | A |
| 0xDD15 | Speed | LE uint16, (val − 32128) / 2 | RPM |

The offset 32128 = 0x7D80 is the UQM zero-crossing convention for signed values stored as unsigned 16-bit little-endian. This encoding likely applies to the Motor CAN periodic broadcasts (0x0048, 0x0222, 0x0500, 0x0100) as well.

These signals correspond to what is already broadcast on D CAN: torque/speed/voltage/current → 0x1C0 (MCM_Telemetry), temperatures → 0x241 (MCM_Thermal). The UDS diagnostic interface and the D CAN periodic broadcasts are parallel views of the same MCM state.

### Motor CAN receive handlers — GBR+0x008 writes confirmed (Phase 24)

All three unidentified receive IDs in 0x8005xxxx were traced for GBR writes (Phase 24). Each one writes GBR+0x008 at positive offsets from its 00FD filter using the identical `C008; BBF0 BSR; 5F10` double-write+BSR pattern confirmed for the ESC wheel speed handlers.

| CAN ID | Filter addr | First positive GBR+0x008 write | BSR pattern | Notes |
|--------|-------------|-------------------------------|-------------|-------|
| 0x0048 | 0x80051DA4 | 0x80051E64 (+192), 0x80051E6A (+198) | yes (BBF0) | Dispatch BRA → 0x800526C2 = same body as 0x0208 ESC_BrakePressure handler |
| 0x0222 | 0x800535BC | 0x8005362A (+110), 0x80053630 (+116) | yes (BBF0) | Multiple writes (+110..+734); also writes GBR+0x074 [SHARED] at +626 |
| 0x0500 | 0x800590CA | 0x80059240 (+374), 0x80059246 (+380) | yes (BBF0) | 3 filter setups (mux'd); writes across +374..+1000 range |

**None can be dismissed from the signal path.** All three use the same inter-task signaling mechanism as the ESC handlers. The 0x0048 dispatch to the 0x0208 handler body suggests it is a vehicle/D CAN message (not Motor CAN) — perhaps a low-frequency D CAN message not captured in surveys.

**Open question:** whether these messages feed the anti-lash filter specifically or only non-filter MCM logic (thermal derating, torque limits, etc.) requires tracing inside 0x8008xxxx to see how GBR+0x008 reads branch.

**The UQM-PID file does not contain raw Motor CAN periodic broadcast frame definitions.** The IDs 0x0048, 0x0222, 0x0500 and 0x0100 remain unidentified pending a Motor CAN protocol spec from UQM or Thunderstruck.

### UQM Motor CAN architecture — Thunderstruck research findings

Search of thunderstruck-ev.com (2026-05-02) found UQM hardware documentation but not the key CAN spec:

**Found — UQM PP100 User Guide (P/N 87510-011), hosted at thunderstruck-ev.com:**
- Motor CAN baud: 500 kbps, 11-bit identifiers, little-endian byte order (default)
- Three message categories:
  - **Universal Command** (DLCM → MCM): torque/speed/voltage setpoint + rolling counter
  - **Universal Feedback** (MCM → DLCM): RPM, temperature, voltage
  - **Heartbeat Command** (DLCM → MCM): periodic security/watchdog message
- CAN arbitration IDs for all three are **user-configurable** via UQM Motor Controller software — no hardcoded IDs in the published spec

**Found — Dilithium VCU Manual v3.1.4, hosted at thunderstruck-ev.com:**
- Explicitly distinguishes `inverter coda` from generic `inverter uqm` — Coda is a distinct variant
- Coda-specific: 300 Nm torque limit, Universal Command every **10 ms** (vs 125 ms for standard UQM), Watchdog Status message **not expected** from Coda inverter
- Fixed 500 kbps, 11-bit IDs, little-endian, torque drive mode

**Not found — UQM CANbus Interface Manual P/N 87510-009:** Referenced by name in multiple documents as the source for all CAN message definitions. Not hosted on Thunderstruck's site. This is the primary missing document.

### Motor CAN ID interpretation

Because IDs are configurable, the DLCM firmware's own 00FD filter setups are the ground truth for what Continental programmed into this specific Coda DLCM:

| ID | Firmware region | Candidate message |
|----|----------------|-------------------|
| 0x0100 | 0x8007xxxx (TX construction) | Universal Feedback (MCM → DLCM) — received here because feedback directly informs the next Universal Command |
| 0x0048 | 0x8005xxxx (ESC/sensor receive) | Unknown MCM periodic feedback |
| 0x0222 | 0x8005xxxx | Unknown MCM periodic feedback |
| 0x0500 | 0x8005xxxx (3 filter setups) | Unknown MCM periodic feedback, mux'd (like ESC 0x0200) |

The placement of 0x0048/0x0222/0x0500 in the same receive region as ESC wheel speed messages, writing to the same GBR+0x008 inter-task byte, indicates the MCM torque filter has inputs from **both** the vehicle-side sensors (ESC wheel speeds via D CAN) **and** motor-side feedback (MCM state via Motor CAN). The filter is a closed-loop controller, not a simple wheel-speed threshold switch.

### Motor CAN handler role differentiation — GBR write scope (Phase 25)

Phase 25 widened the GBR write scan to include ALL GBR offsets (not just shared cells) across ±0x600 of each Motor CAN filter, to test whether any handler writes cells that are NOT shared with the MCM handler — which would indicate side-channel data (thermal staging, telemetry) rather than direct MCM control input.

**Findings — cells written INSIDE each handler body (positive-offset region):**

| CAN ID | GBR+0x008 [SHARED] | Non-shared GBR writes (inside body) | Interpretation |
|--------|---------------------|--------------------------------------|----------------|
| 0x0048 | Yes (double-write+BSR at +192/+198) | GBR+0x21C at +388 | Carries at least 2 distinct signal values; side-channel to non-MCM consumers |
| 0x0222 | Yes (double-write+BSR at +110/+116) | GBR+0x0F1 at +406 | Carries at least 2 distinct signals; side-channel to non-MCM consumers |
| 0x0500 | Yes (double-write+BSR at +374/+380) | None in +-0x600 | Writes only the inter-task byte; "purest" MCM state feed |

The non-shared cells (GBR+0x21C, GBR+0x0F1) are NOT in the 12-cell shared set and therefore NOT read by the MCM handler (0x8008xxxx). They are consumed elsewhere — most likely by the CAN TX region (0x8007xxxx) for D-CAN telemetry staging.

**None of the three handlers can be eliminated from the MCM communication path** — all write GBR+0x008. Calling any of them "only used for derating/limits" is not yet supported by the data. Determining which GBR+0x008 values gate anti-lash vs. thermal derating requires tracing MCM handler branching logic (Phase 25-B / future work).

### MCM handler GBR+0x008 usage — multi-pattern byte (Phase 25-B)

53 total reads of GBR+0x008 in 0x8008xxxx MCM handler, organized in at least 5 usage patterns:

| Pattern | Example address | Description |
|---------|----------------|-------------|
| Pointer dereference | 0x80085272 | `C408; 6D00 MOV.B @R0,R13` — byte value used as SRAM address/index in a tight loop |
| State compare | 0x80085288 | `CMP/EQ R0,R11` — equality test against state variable |
| Threshold compare | 0x80085E08 | `CMP/GE R0,R12` — signed greater-or-equal, consistent with limit checking |
| Bit-flag test | 0x80088514 | `C408; BT; BT; C21F MOV.L R0,@(0x07C,GBR)` — bit tests gate write to GBR+0x07C |
| Write-back transition | 0x80085290 | Read → compare → `C008` write same cell — state machine step |

GBR+0x008 is a **multi-bit state/flags byte**, not a simple enable flag. Different bits of its value gate different MCM handler behaviors. This means separate bits could independently encode anti-lash state vs. thermal derating state.

One read at 0x8008005C uses `C602 MOV.L @(0x008,GBR),R0` — a 32-bit LONG read covering GBR+0x008..0x00B. This implies the firmware sometimes treats that 4-byte window as a 32-bit structure; the byte writes at GBR+0x008 only update the first byte of this structure.

### D-CAN linkage — 00F8 TX scan (Phase 26)

> **SUPERSEDED 2026-09-24.** The Motor CAN ids named here (`0x0048`, `0x0100`,
> `0x0222`, `0x0500`, `0x02FF`) are artefacts of the SH-4 decode and appear nowhere
> in the firmware's CAN configuration tables. See
> [The firmware's own CAN configuration tables](#the-firmwares-own-can-configuration-tables--full-message-inventory-2026-09-24)
> for the real inventory.

Phase 26 searched for 00F8 (CAN TX trigger) patterns to find which Motor CAN handlers relay data to D-CAN messages, specifically MCM_Thermal (0x0241 / 577 decimal).

**0x0241 TX not found anywhere in binary.** The 9110+00F8 pattern (which successfully finds other TX sites) locates no 0x0241 TX. Either:
- D-CAN TX for 0x0241 uses a different mechanism (direct CAN hardware mailbox write, different opcode) not captured by the 00F8 scan
- The DBC attribution of 0x0241 to DLCM may be incorrect — the source ECU warrants verification

**0x02FF (767 decimal) — actively transmitted by Motor CAN receive handlers:**

The 0x0500 handler body (at 0x80059B98) and the 0x0222 handler area (at 0x80053F22) both directly trigger TX of 0x02FF via the 00F8 opcode. A third 00F8 TX of 0x02FF appears at 0x8005AB8E, near the 0x0048 handler region. CAN ID 0x02FF is not present in any Coda DBC (D-CAN or B-CAN).

Two interpretations:
1. **00F8 = Motor CAN TX** (not D-CAN TX). In this reading, the Motor CAN receive handlers process MCM feedback and immediately issue a new 0x02FF Motor CAN command frame (likely the Universal Command, 10 ms cycle). D-CAN TX would then use a different SH-4 opcode not yet identified. This would explain why D-CAN messages like 0x1C0, 0x0241 are absent from the 00F8 scan.
2. **0x02FF = undocumented D-CAN message** re-transmitted by DLCM when it receives a Motor CAN frame.

Evidence favouring interpretation 1: 0x8007xxxx (the CAN TX construction region *(revised in Phase 27: B-CAN receive region)* with 431 GBR+0x008 writes and 120 GBR+0x07C writes) only has 5 distinct 00F8 TX IDs (0x000A, 0x0090, 0x00F6, 0x00FD, 0x0580) — none of which match known D-CAN IDs like 0x1C0, 0x0208, 0x0241. If 00F8 were D-CAN TX, the 0x8007xxxx TX construction region should show the expected D-CAN IDs.

**Candidate mapping (hypothesis, unconfirmed):**
- 0x0500 (Motor CAN MCM→DLCM feedback, 3 mux slots) → triggers 0x02FF TX = Universal Command DLCM→MCM torque update; also feeds MCM handler via GBR+0x008
- 0x0222 (Motor CAN, 1 filter, writes non-shared GBR+0x0F1) → may carry thermal/status data; triggers 0x02FF TX; GBR+0x0F1 may stage thermal values for D-CAN TX via separate mechanism
- 0x0048 (Motor CAN, 1 filter, dispatches to 0x0208 body, writes non-shared GBR+0x21C) → function unclear; close structural similarity to brake pressure handler body is unexplained

**Open questions (resolved in Phase 27 — see below):**
- What CAN bus does 00F8 operate on? Motor CAN or D-CAN?
- What SH-4 opcode (if not 00F8) is used for D-CAN TX of 0x1C0 / 0x0241?
- What does GBR+0x0F1 (written by 0x0222 handler, not MCM-readable) feed downstream?

---

## Phase 27 — D-CAN TX mechanism and MCM_Thermal source identification

> **SUPERSEDED 2026-09-24.** The Motor CAN ids named here (`0x0048`, `0x0100`,
> `0x0222`, `0x0500`, `0x02FF`) are artefacts of the SH-4 decode and appear nowhere
> in the firmware's CAN configuration tables. See
> [The firmware's own CAN configuration tables](#the-firmwares-own-can-configuration-tables--full-message-inventory-2026-09-24)
> for the real inventory.

**Goal:** Determine which Motor CAN receive handler (0x0048, 0x0222, or 0x0500) feeds D-CAN MCM_Thermal (0x0241 / 577 decimal) and how that transmission is triggered.

**Summary of findings:** Motor CAN message **0x0222** is the source for MCM_Thermal. The 0x0048 and 0x0500 handlers are definitively ruled out. The D-CAN TX mechanism uses opcode **00F6** (not 00F8), with a mailbox-index argument `01Fx`.

### Architecture revision: four-region firmware layout

| Region | Role | Key opcode |
|--------|------|-----------|
| 0x8005xxxx | Motor CAN + D-CAN receive filters and handlers | 00FD (RX filter) |
| 0x8006xxxx | D-CAN TX construction (builds and transmits D-CAN frames) | 00F6 (D-CAN TX) |
| 0x8007xxxx | **role unconfirmed** (hypothesis: D-CAN receive handlers — see note below) | 00FA (role unconfirmed) |
| 0x8008xxxx | MCM compute handler (processes Motor CAN data, drives state machine) | 00F6 (D-CAN TX from MCM handler) |

**00F6 = D-CAN TX opcode.** All 564 00F6 calls share a consistent `01Fx` argument (top byte always 0x01, lower byte = mailbox index). The mailbox was pre-configured at startup from the table at 0x8008FCxx (0x0240 and 0x0241 appear as adjacent pool entries). At runtime, 00F6 triggers TX of a pre-configured mailbox without specifying the CAN ID in code — explaining why the standard CAN-ID pool scan found 0x0241 nowhere.

**00F8 = Motor CAN TX opcode** (confirmed). All three Motor CAN handlers (0x0048, 0x0222, 0x0500) trigger 0x02FF Motor CAN TX via 00F8 — the Universal Command frame DLCM→MCM. This is NOT D-CAN TX.

**00FA — role unconfirmed.** 174 occurrences; dominant in 0x8007xxxx (120+ sites). Originally labeled "B-CAN RX" — ruled out: the DLCM Functional Requirements confirm the DLCM has exactly two CAN interfaces (D_CAN and M_CAN only; no B-CAN connection). Working hypothesis: 00FA = D-CAN receive frame handler, making 0x8007xxxx the D-CAN receive processing region. Basis: DLCM only has D_CAN and M_CAN; M_CAN receive is accounted for via 00FD filter setups in 0x8005xxxx; 00FA's argument convention differs from both 00F8 and 00F6. **Not confirmed by instruction tracing or spec cross-reference — treat as assumption until verified.**

### Non-shared GBR cell disposal (Phase 27-I)

| Motor CAN handler | Non-shared cell written | Where consumed |
|-------------------|------------------------|---------------|
| 0x0222 | GBR+0x0F1 | Read at 0x80079FEE in 0x8007xxxx (region role unconfirmed) — feeds 0x8007xxxx processing only, not MCM_Thermal |
| 0x0048 | GBR+0x21C | **Never read anywhere in binary** — dead or hardware-DMA-only path |

This eliminates non-shared cell paths to MCM_Thermal. The thermal data must flow through shared GBR cells.

### Shared GBR cell writes per handler

From scanning GBR writes within handler bodies in 0x8005xxxx (Phase 27-N):

| Handler | Shared cells written (beyond GBR+0x008) |
|---------|-----------------------------------------|
| 0x0222 | GBR+0x074, GBR+0x07C |
| 0x0048 | GBR+0x008 only |
| 0x0500 | GBR+0x008 only |

GBR+0x074 and GBR+0x07C are written exclusively by the 0x0222 handler body (the false-positive cluster at 0x80053716-0x8005379E is internal to the 0x0222 handler's 960-byte body at 0x80053540-0x80053900).

### D-CAN TX calls consuming 0x0222 data (Phase 27-P2, Phase 27-Q-2)

GBR+0x07C is read within the 0x100-byte window before **6 of the 182 00F6 TX calls** in 0x8006xxxx:

| TX site (0x8006xxxx) | Argument | Notes |
|----------------------|----------|-------|
| 0x80062ECE | 0x0122 | - |
| 0x80062F00 | 0x01F1 | - |
| 0x80063B0A | 0x01F8 | Cluster: three consecutive TX calls near 0x80063Bxx |
| 0x80063B26 | 0x01F8 | Cluster |
| 0x80063B58 | 0x01F0 | Cluster; GBR+0x07C read earlier in function body |
| 0x80063FD6 | 0x0169 | Reads GBR+0x07C twice |

The cluster at 0x80063B0A/3B26/3B58 (three TX calls in 24 bytes) is the primary candidate for the MCM_Thermal TX (0x0241), along with adjacent messages (MCM_CoreTelemetry 0x01C0 is also sent nearby). The exact mapping of `01Fx` argument → CAN ID 0x0241 requires decoding the mailbox init table at 0x8008FCxx.

### MCM compute handler TX calls (Phase 27-O)

Only **4** 00F6 TX calls were found in the MCM handler core range (0x80085000-0x80086400):

| TX site | Argument | Shared GBR reads nearby |
|---------|----------|------------------------|
| 0x8008518E | 0x0141 | GBR+0x000 (rel -52) |
| 0x8008592E | 0x01F1 | none in window |
| 0x80085DFE | 0x01F0 | GBR+0x000 x2, GBR+0x008 x2 |
| 0x80085E8E | 0x01F0 | GBR+0x008 x3 |

These 4 calls likely correspond to MCM state/telemetry broadcasts from the compute handler, not the thermal message.

### Conclusion

**Motor CAN 0x0222 → GBR+0x074 + GBR+0x07C (shared) → 0x8006xxxx D-CAN TX construction region → MCM_Thermal (0x0241)**

- 0x0500: ruled out (writes only GBR+0x008)
- 0x0048: ruled out (non-shared GBR+0x21C never read; other writes only GBR+0x008)
- 0x0222: confirmed as thermal source (exclusive writer of GBR+0x074 and GBR+0x07C, both consumed near D-CAN TX calls)

**Residual open questions:**
- What is the precise `01Fx` mailbox argument for 0x0241 TX? Requires decoding the mailbox init table at 0x8008FCxx or comparing the TX cluster context against the known 0x0241 CAN frame payload.
- GBR+0x0FE (one writer at 0x80052F2A, one reader in 0x8008xxxx near 01F4 00F6) — appears to be a control/counter value, not thermal data (read used in arithmetic subtraction, not CAN frame assembly).
- Full 00F6 argument → CAN ID mapping: requires iterating the 0x8008FCxx init table structure to map all pre-configured mailbox slots.

---

## Spec Cross-Reference — DLCM & MCM Functional Requirements (2026-05-02)

Source documents: `DLCM Functional requirements_V4_2.pdf` and `MCM_Functional_requirements_V1_2.pdf` (both in `notes/dlcm/`). Extracted via pdfminer (`dlcm_functional_requirements.txt`, `mcm_functional_requirements.txt`) and targeted docling table extraction (`dlcm_tables_*.md`, `mcm_tables_full.md`), all in `notes/dlcm/artifacts/`.

### M_CAN message inventory (from MCM spec §7.1–7.2)

Complete message list on the private Motor CAN bus:

**DLCM → MCM:**
| Message | Security | Notes |
|---------|----------|-------|
| TorqueCommandMessage | CRC + message counter | Contains TrqCmdCtrl_Enable, TrqCmdCtrl_Direction, TrqCmdRequestValue. MCM timeout-checks only this message. |
| ResetCANWatchdogTimer | none | Clears MCM legacy watchdog fault function. |

**MCM → DLCM:**
| Message | Security | DLCM forwards to D_CAN? |
|---------|----------|------------------------|
| AccurateFeedbacks_Mech | CRC + message counter | No — protected version for DLCM internal use |
| AccurateFeedbacks_Elec | CRC + message counter | No — protected version for DLCM internal use |
| AccurateFeedbacks | none (security bits stripped) | Yes — forwarded to D_CAN per §7.1.1 |
| SystemStatusMessage | none | Yes — forwarded to D_CAN per §7.1.1 |
| Temperature | none | Yes — forwarded to D_CAN per §7.1.1 (the Phase 27 claim that this is Motor CAN 0x0222 is SUPERSEDED — see 2026-09-24 CAN configuration tables) |
| limited_torque_percentage | none | No (contains high_bound and low_bound as % of 300 Nm) |
| CANWatchdogStatus | none | No (legacy watchdog status) |

AccurateFeedbacks_Mech carries AccurateSpeed + AccurateTorque (CRC + counter). AccurateFeedbacks_Elec carries AccurateCurrent + AccurateVoltage (CRC + counter). AccurateFeedbacks is the same data without security — this is the version forwarded on D_CAN.

### TorqueCommandMessage signal breakdown (§8.8.6)

| Signal | Direction | Description |
|--------|-----------|-------------|
| TrqCmdCtrl_Enable | DLCM → MCM | If != 'Enable', MCM forces torque target to 0 Nm |
| TrqCmdCtrl_Direction | DLCM → MCM | Forward or reverse direction command |
| TrqCmdRequestValue | DLCM → MCM | Torque magnitude; sign referenced to Direction |

Plus CRC and message counter security fields. This confirms our Phase 27 finding that 0x02FF = TorqueCommandMessage (the 00F8 Motor CAN TX target).

### MCM fault feedback signal list (§8.8.9, SystemStatusMessage)

These are the bit-flags inside SystemStatusMessage that the DLCM reads and reacts to:

| Signal | MCM behaviour | DLCM reaction | Lamp |
|--------|--------------|---------------|------|
| ADC_Calibration_Problem | Runs on default cal, severely limited; AccurateFeedback untrustworthy | 3 power cycles, then off until key cycle | Red Vehicle |
| BadDriver | Limits torque above base speed; may not restart once stopped | — | Red Vehicle |
| BadPositionSignal | Shut down torque production | 3 power cycles | Red Vehicle |
| CTFault | Shut down torque production; torque delivery unknown | 3 power cycles | Red Vehicle |
| Forced_Voltage_Control | Internal caps at 875 V; motors slightly to bleed to 825 V | — | — |
| ForcedOpenLoop | Open loop, output power limited | — | — |
| Invalid12V | Internal 12 V < 11.75; open loop, 50% torque limit | 3 power cycles | Red Vehicle |
| Inverter_Fault | Attempts self-clear, then shuts down | 3 power cycles after 1 sec | Red Vehicle |
| Coolant_Loss_Detected | — | — | MotorOverTemp + Red Vehicle |
| IGBT_Over_Temperature | Limiting active | — | MotorOverTemp |
| Stator_Over_Temperature | Limiting active | — | MotorOverTemp |
| MotorStalled | Pulses torque to escape stall; stall limit 150 Nm continuous | — | MotorOverTemp |
| Over_Phase_Advance | Will be limited | — | Yellow Vehicle |
| Over_Speed_Alarm | >8300 rpm; applies up to 150 A regen | — | Yellow Vehicle |
| Over_Speed_Warning | >7700 rpm; torque limiting active; 0 Nm at 8000 rpm | — | Yellow Vehicle |
| Over_Voltage_Alarm | >850 V; inverter damage risk | — | Yellow Vehicle |
| Over_Voltage_Warning | >450 V; regen limited | — | Yellow Vehicle |
| PhaseCurrentSensorError | Open loop ~50%, torque delivery unknown | 3 power cycles | Red Vehicle |
| TrqCmdCRCFault | CRC error on torque command; 0 Nm until power cycle | 2 DLCM power cycles | Red Vehicle |
| TrqCmdCounterFault | Counter error on torque command; 0 Nm until fault clears | 2 DLCM power cycles | Red Vehicle |
| Rotor_Over_Temperature | Limiting active | — | MotorOverTemp |
| Under_Voltage_Warning | Limiting active | — | — |
| RegenAllowed | FALSE = 7th switch open, no regen possible | DTC if FALSE and AccurateCurrent > 20 A for 3 sec | Yellow Vehicle |

### CAN signal validity table highlights (§8.13.4)

Key validity check details not obvious from signal names alone:

| Signal(s) | Invalid when | Default at boot |
|-----------|-------------|----------------|
| VehSpd (ESC) | CAN timeout OR signal = 0xFFFF | invalid |
| BrakePressureFilt (ESC) | CAN timeout OR BrakePressureFilt = 0xFF OR BrakePressureFiltVld = Invalid | valid, pressure = 0 |
| MMIN_ESP / M_ESP / MMAX_ESP_REGEN_TQ_REQ (ESC, 0x0300) | CAN timeout OR **MPAR_ESP** invalid OR **MTOG_ESP** invalid | valid; M_ESP = 300 Nm, MMAX_ESP_REGEN_TQ_REQ = 300 Nm |
| DVL / DVR (ESC) | CAN timeout OR signal = 0x3FF OR **ESP_BRK_COUNT** not changing | invalid |
| ABS_LMP_RQ (ESC) | CAN timeout OR ESP_BRK_COUNT not changing | off |
| ABS_BrkEvt (ESC) | CAN timeout OR signal ON for 1 minute | off |
| AccurateSpeed (MCM) | CAN timeout OR signal CRC OR CAN message counter OR disagrees with DVL/DVR | invalid |
| AccurateCurrent (MCM) | CAN timeout OR signal CRC OR CAN message counter | invalid |
| AccurateTorque (MCM) | CAN timeout OR CAN message counter | invalid |
| AccurateVoltage (MCM) | CAN timeout OR CAN message counter | invalid |
| high_bound / low_bound (MCM) | CAN timeout OR value > 100 | 100% (no limiting assumed) |
| BattSentDischargeLimit / BattSentChargeLimit (GWM/BMS) | CAN timeout OR BattSentLimit_Tog invalid | derating mode value |
| Chargemode (GWM/BMS) | CAN timeout OR undefined state OR cable connected above creep speed | invalid |
| HVPowermode (GWM/BMS) | CAN timeout OR undefined/'invalid' state | invalid |

Notes: **MPAR_ESP** is a parity bit (XOR of all bits in M_ESP, MMIN_ESP, MMAX_ESP, MTGL_ESP). **MTOG_ESP** (also written MTGL_ESP) is a toggle bit that changes every other message (0-0-1-1-0-0-1-1). **ESP_BRK_COUNT** is an incrementing counter in the ABS/wheel-speed messages on 0x0200 — used as an anti-stale check for DVL/DVR and ABS_LMP_RQ.

### ESC CAN message breakdown

From §8.3.1 (0x0300) and the CAN validity table:

**0x0300 — ESC torque limits:**
- MMIN_ESP (flag: when 1, positive torque is limited to M_ESP)
- M_ESP (positive torque limit, Nm)
- MMAX_ESP_REGEN_TQ_REQ (regen torque limit, always active)
- MPAR_ESP (parity security bit)
- MTGL_ESP / MTOG_ESP (toggle security bit)

**0x0208 (ESC_BrakePressure, confirmed in DBC):**
- BrakePressureFilt
- BrakePressureFiltVld

**0x0200 (implied by ABS signal grouping):**
- DVL (front left wheel speed)
- DVR (front right wheel speed)
- VehSpd
- ABS_LMP_RQ
- ABS_BrkEvt
- ESP_BRK_COUNT (message counter / anti-stale token)

### MCM operational limits (§8.8.2) — calibration variable names

These `Cal_Ecm1_*` names should be locatable in the CAL binary (0x80020000) as string literals or as indexed constant entries:

| Parameter | Limit | Cal variable |
|-----------|-------|-------------|
| Max motoring torque | 300 Nm | — |
| Max regen torque | 300 Nm | — |
| Max regen current | 150 A (hardware switch opens at 225 A) | — |
| Max speed for full torque | calibrated | `Cal_Ecm1_MtrMaxPerfSpd_rpm` |
| Max speed for operation | calibrated | `Cal_Ecm1_MtrMaxOpSpd_rpm` |
| Speed hysteresis (hi) | calibrated | `Cal_Ecm1_MtrSpdHystHi_rpm` |
| Speed hysteresis (lo) | calibrated | `Cal_Ecm1_MtrSpdHystLo_rpm` |
| Vehicle speed limit target | 82 mph fwd / 25 mph rev | `Cal_Ecm1_VehSpdMaxTargt_kph` |
| Max voltage (regen limit onset) | 450 V | — |
| Min voltage (full performance) | 270 V | — |
| Min voltage (operation floor) | 230 V | — |

### Stale text flag — §8.3.1.1 ESC Limit Application

§8.3.1.1 states: "the ESC will limit the application of the zero torque filter, zero crossing filter, creep function, pedal request, etc." This text still references the Zero Crossing Filter by name. However, revision 25 of the spec changelog explicitly deleted the Zero Crossing Filter and Zero Torque Rate Limiter sections. This sentence was not updated to match. Our binary should not implement a ZCF — the functions that the ESC limits in this context are: the Torque Smoothing Filter (§10.6) and the State Dependent Torque Gradient Limiter (§10.7), not a ZCF.

---

## §10.7 State Dependent Torque Gradient Limiter — CAL address mapping (2026-05-03)

### FFFF module descriptor anchor

The FFFF-delimited module descriptor blocks at PROG 0x80041800–0x80041C00 include four blocks. Block3 (at PROG 0x80041A00) is the only block containing a CAL pointer. At offset +0x3C within Block3, the pointer value is **0x80021400**.

```
PROG 0x80041A0C: 0x80021400  <-- CAL pointer (module not yet confirmed)
```

### Pre-pointer data context

A monotone numeric sequence sits 8 bytes before the CAL pointer location:

```
0x800213F8:  0      (LE u16)
0x800213FA:  500
0x800213FC:  1000
0x800213FE:  2000
0x80021400:  3000   <-- CAL pointer lands here
0x80021402:  4000
0x80021404:  5000
0x80021406:  6000
0x80021408:  7500
0x8002140A:  9000
0x8002140C:  10000
0x8002140E:  0      (terminator)
```

Role unknown. Does not correspond to any input of the §10.7 gradient limiter (VehicleSpeed, BrakePressure, TrqLast). May belong to a different module that shares this CAL block, or the CAL pointer at PROG 0x80041A0C may not be the gradient limiter's base.

### Data layout at 0x80021400 — identified blocks

The memory at and immediately after the CAL pointer location contains data that — based on value patterns alone — looks consistent with §10.7 gradient limiter input axes and output tables. Based on value pattern analysis:

| Address | Size | LE values | BE values | Pattern-match hypothesis |
|---------|------|-----------|-----------|--------------------------|
| 0x800213F8 | 16 bytes | 0,500,1000,2000,3000,4000,5000,6000,7500,9000,10000,0 | 0,128,256,512,47115,... | Unidentified monotone sequence; CAL pointer lands at offset +8 (=3000 LE) |
| 0x80021410 | 4 bytes | 0x0100, 0x0180 | 0x0001, 0x8001 | BE values look like dispatch tokens |
| 0x80021414 | 2 bytes | 0x0400 | 0x0004 | Unknown |
| 0x80021416 | 8 bytes | 1280, 6400, 10240, 16640 | 5, 25, 40, 65 | BE values look like Nm (TrqLast axis hypothesis) |
| 0x8002141E | 4 bytes | 0x0100, 0x0280 | 0x0001, 0x8002 | BE values look like dispatch tokens |
| 0x80021420 | 10 bytes | 0, 100, 200, 300, 3000 | 0, 25600, 51200, 11265, 47115 | LE values look like pressure units (BrakePress axis hypothesis) |
| 0x8002142A | 4 bytes | 0, 0 | 0, 0 | Unknown |
| 0x8002142E | 8 bytes | (mixed) | 3, 0x8005, 0x8007, 65 | BE values include dispatch-looking tokens |
| 0x8002143A | 14 bytes | 1280, 5120, 7680, 10240, 12800, 15360, 17920 | 5, 20, 30, 40, 50, 60, 70 | BE values look like km/h (VehSpd axis hypothesis) |
| 0x80021448 | 14 bytes | 116, 117, 137, 165, 204, 254, 315 | (large values) | LE values are monotone-increasing; associated with the 7-element axis above |

**Note on "Confirmed" labels in this table**: All axis identifications above are **pattern-match hypotheses only**. The byte order used internally by the SH-4 for each SRAM signal is unknown without tracing the CAN RX handlers. See the endianness discussion in the 2026-05-04 section below.

### Interpolation function E5CC

PROG 0x8006E5CC (54 bytes) is the gradient limiter table interpolation function. It contains three sequential `mac.w @r0+,@r2+` + BSR sequences:

1. `mac.w @r0+,@r2+` then BSR to **EFD2** — calls E3F8 inner interpolation loop
2. `mac.w @r0+,@r2+` then BSR to **EFE4** — adds to R6, branches to E40C (no E3F8 call)
3. `mac.w @r0+,@r2+` then BSR to **EFF6** — calls FUN_8006F842 (separate interpolation mechanism)

Each `mac.w @r0+,@r2+` reads one u16 coefficient from R0 (CAL base pointer) and one u16 input from R2 (SRAM). R0 advances past the coefficient into the table's axis/output data, which the BSR target then consumes.

**E3F8 unrolled loop** (0x8006E360–0x8006E460): 15-block unrolled MAC.W loop. Entry at 0x8006E3F8 = block 9's MAC.W position. Per-block handler is called via BSR after each MAC.W; the block 9 handler is EDFC.

**CORRECTION (2026-05-03): EDFC exits immediately.** EDFC's first substantive instruction (at 0x8006EE08) is `BRA 0x8006E236`, which exits the entire unrolled loop after only ONE MAC.W iteration. When E3F8 is called from EFD4, only one mac.w runs. Handler 1 R0 advance is +4 bytes total (not +30 as previously assumed).

### R0 advancement map (2026-05-03, corrected)

R0 starts at 0x80021400 (from PROG pointer at 0x80041A0C). The three E5CC handlers advance it as follows:

| Handler | mac.w coeff at | coeff value | R0 advance | Notes |
|---------|----------------|-------------|------------|-------|
| EFD2 -> E3F8 | 0x80021400 | 3000 (LE) | +4 bytes | E5CE +2, E3F8 block-9 +2; EDFC exits immediately |
| EFE4 | 0x80021402 | 4000 (BE) | +2 + ? | EFE4 BRAs to E40C (mid-block-10); may cause additional mac.w iterations -- UNCERTAIN |
| EFF6 -> F842 -> EEF6 | ? | ? | +2 + ? | downstream position depends on EFE4 output -- UNCERTAIN |

**Downstream R0 positions for Handlers 2 and 3 need re-verification** now that EDFC's single-iteration exit is confirmed. The positions in the original map (0x8002141E, 0x80021420) assumed 14 iterations and are wrong.

FUN_8006F842 is a trampoline: it immediately BRAs to 0x8006EEF6 (with R15 saved to [R4+0x3C] in the delay slot). EEF6 itself performs zero R0 advancement and exits by BRAing to 0x8006E534. F842/EEF6 uses the current R0 value as an input, not as a sequential CAL data pointer.

The one word E3F8 reads via block-9 MAC.W (at 0x80021402):
```
[0x80021402]: BE=4000
```

Remaining unidentified monotone sequence and downstream data starting at 0x80021402 (BE u16):
```
[0x80021402]: 4000
[0x80021404]: 5000
[0x80021406]: 6000
[0x80021408]: 7500
[0x8002140A]: 9000
[0x8002140C]: 10000
[0x8002140E]: 0
[0x80021410]: 0
[0x80021412]: 1
[0x80021414]: -32767  (= 0x8001 as s16 BE)
[0x80021416]: 5
[0x80021418]: 25
[0x8002141A]: 40
[0x8002141C]: 65
[0x8002141E]: 0
[0x80021420]: 0
```

### CAL layout beyond R0=0x80021422

After the three handlers, the remaining CAL data is processed by additional E40C-dispatched handlers. The structure from 0x80021422 onward:

```
0x80021422–0x80021429: BrakePress axis elements [1..4]: LE = [100, 200, 300, 3000]
0x8002142A–0x8002142D: zeros
0x8002142E:            BE = 3
0x80021430:            BE = 0x8005  (dispatch token?)
0x80021432:            BE = 0x8007  (dispatch token?)
0x80021434:            BE = 65
0x80021436–0x80021439: zeros
0x8002143A–0x80021447: VehSpd axis [5, 20, 30, 40, 50, 60, 70] (BE u16)
0x80021448–0x80021455: candidate Y-axis values [116, 117, 137, 165, 204, 254, 315] (LE u16) [HYPOTHESIS]
```

The values [116..315] are monotone-increasing with the VehSpd axis, which is consistent with them being Y-axis outputs, but this is a pattern-match hypothesis only. **Not confirmed.** See §10.7 CAL Layout — Endianness and Axis Identification Status below for full uncertainty discussion.

### Open questions

- What E40C dispatch tokens 0x8005 and 0x8007 dispatch to — these are likely the handlers for BrakePress and VehSpd, but which is which is unresolved.
- What EEF6 computes using R0 as an input value (not a data stream pointer).
- What the 14-word E3F8 coefficient table represents physically — it contains the pre-pointer monotone sequence continuation + [0, 1, -32767] + TrqLast [5,25,40,65]. The mix of values suggests E3F8 is a multi-tap FIR/IIR computation rather than a simple piecewise-linear interpolation.

---

## VM Dispatch Table Architecture and GBR SRAM Map (2026-05-04)

### VM Dispatch Table Hierarchy

The DLCM executes a threaded-code virtual machine. Two table tiers were confirmed by static analysis:

**Outer dispatch table** (2-word entries):
- Format: `[native_instruction, 0x00D0]`
- Located at: 0x80040Bxx, 0x80044xxx
- The context word 0x00D0 is passed as an argument to the inner handler
- Example: `BSR 0x80045264` with delay-slot `0x00D0`

**Inner batch signal-copy table** (4-word entries):
- Format: `[secondary_store, metadata, context_index, gbr_primary_store]`
- Located at: 0x80045xxx (confirmed; extends at least to 0x80045450)
- `secondary_store` (word0): SH-4 opcode in the `80/81` family — `MOV.B/W R0,@(d4,Rn)` — a valid register-relative store
- `gbr_primary_store` (word3): SH-4 opcode in the `C0/C1/C2` family — `MOV.B/W/L R0,@(GBR+offset)` — the primary GBR-relative store
- Example entries (from Phase 3):
  ```
  [8031 41F1 0033] -> C1F3   secondary=MOV.W R0,@(2,R3), primary=MOV.W R0,@(GBR+0x1e6)
  [81F2 4032 0036] -> C1F6   secondary=MOV.W R0,@(4,R15), primary=MOV.W R0,@(GBR+0x1ec)
  ```

**All 4 `LDC.L @Rn+,GBR` instructions** in PROG are inside VM dispatch table entries, not startup code:
- 0x80044054, 0x80045DF2, 0x800463D2, 0x8006026E

GBR's value is set at runtime by the VM engine. It cannot be determined by static analysis alone.

### GBR SRAM Map — Region near 0x01EE

Full scan of all 3,674 GBR-write instructions in PROG; confirmed addresses near the E5CC Y-axis hypothesis range:

| GBR offset | Size | Writer opcode | Writer address | Notes |
|------------|------|---------------|----------------|-------|
| 0x01DA | W | C1ED | 0x80045396 | batch table entry |
| 0x01D0 | W | C1E8 | 0x8004537E | batch table entry |
| 0x01E6 | W | C1F3 | 0x80045346 | batch table entry |
| 0x01E8 | W | C1F4 | 0x80064C38 | in 0x80064xxx VM region |
| 0x01EA | W | C1F5 | 0x8009200A | in 0x8009xxx VM region |
| 0x01EC | W | C1F6 | 0x8004534E | batch table entry |
| **0x01EE** | **—** | **absent** | **—** | **C1F7 = 0 occurrences in entire PROG** |
| 0x01F2 | W | C1F9 | 0x80045376 | batch table entry |
| 0x01F8 | W | C1FC | 0x8004535E | batch table entry |

**GBR+0x01EE has no GBR-relative writer anywhere in the 3,674-instruction scan.** The batch table at 0x80045xxx jumps from C1F6 (GBR+0x01EC) to the next entry which stores to GBR+0x35 — C1F7 is absent.

### GBR+0x01EE Reads (C5F7) — 4 sites

`C5F7 = MOV.W @(GBR+0x01EE),R0` appears 4 times:

| Site | Address | Context |
|------|---------|---------|
| 1 | 0x800664CA | R0 immediately overwritten by `C400` (MOV.B @(GBR+0x00),R0) — value discarded |
| 2 | 0x80066756 | R0 used as a POINTER: `1080 MOV.L R8,@(0,R0)` — GBR+0x01EE holds an address |
| 3 | 0x80066EEC | R0 immediately overwritten by `C400` — value discarded |
| 4 | 0x8008DB0A | R0 used arithmetically |

Site 2 is the most significant: GBR+0x01EE stores a pointer value, not a signal. It may be written by a non-GBR-relative mechanism (register-indirect store, DMA, or always-zero init) rather than by a `C1xx` instruction.

### E5CC Y-Axis Hypothesis — Status

Prior hypothesis: E5CC Y-axis inputs (R2 pointer) are GBR+0x01EA, 0x01EC, 0x01EE.

This hypothesis is **unconfirmed and weakened**:
- R2 at E5CC entry = `EXTU.W(R11)` where R11 = `[R14+52]` (a module descriptor SRAM pointer — a runtime value)
- GBR+0x01EA and GBR+0x01EC have confirmed writers, consistent with the hypothesis
- GBR+0x01EE has no GBR-relative writer; if it is one of the Y-axis inputs, it must be written differently
- Cannot confirm without descriptor table contents (runtime data)

### Blocker for CAL Gradient Limit Table (R12 trace)

`DBC0` at 0x8006DBC0 loads the gradient limit table pointer via:
```
DBCA: MOV.L @(0x34,R12),R0   ; R0 = CAL table address
DBCA: BSR 0x8006E5CC          ; -> E5CC
```

R12 is described as a "CAL/SRAM struct pointer" (a module parameter block populated by init code). Its value is not determinable by examining PROG alone — it depends on the descriptor block that the init code at 0x8004xxxx loads at startup.

The next analysis step is: **trace R12 backward through the D8xx-D9xx computation block** (around 0x8006D8xx) to find where R12 is loaded, then read `[R12+0x34]` from the binary to obtain the actual CAL table address.

---

## §10.7 CAL Layout — Endianness and Axis Identification Status (2026-05-04)

### Endianness — Unresolved

The dump script prints two interpretations of every 16-bit word: `u16le` (LE column) and `u16be` (BE column). The physically plausible values are inconsistently distributed across these two columns:

| Table hypothesis | Physically plausible column | Example |
|-----------------|----------------------------|---------|
| "BrakePress axis" | LE | LE=100, BE=25600 → 100 looks like pressure |
| "VehSpd axis" | BE | LE=1280, BE=5 → 5 looks like km/h |
| "TrqLast axis" | BE | LE=1280, BE=5 → 5 looks like Nm |

This is not explainable by any single uniform byte order. The correct interpretation depends on how each input signal is stored in SRAM, which in turn depends on the CAN RX handlers — not determinable from static analysis.

**DBC constraints** (objective, from CODA-D-CAN.dbc):
- WheelSpeed signals (VehSpd source, 0x200/0x208): Motorola `@0+` (BE), scale TBD, zero=0xC000
- BrakePressure (0x208 B2-B3): Motorola `@0+` (BE), scale=1, offset=-4096
- Motor_Speed (0x1C0 B6-B7): Intel `@1+` (LE), scale=0.5, offset=-16064
- TrqLast: DLCM-internal value, not a raw CAN signal

The BrakePressure signal is Motorola BE with a +4096 offset. Even if the DLCM subtracts the offset before storing, a physical value of 100 stored as BE u16 would give bytes [0x00, 0x64] → LE=25600, BE=100. But the CAL shows LE=100 (bytes [0x64, 0x00]) for the "BrakePress" axis. These don't match, suggesting either the axis is not brake pressure, or the DLCM applies an unknown scale/format conversion before SRAM storage.

**Bottom line**: all axis identifications in this region are pattern-match hypotheses. The byte order question, and therefore which column represents the values the SH-4 compares against, cannot be resolved from static analysis alone. Tracing the CAN RX handler for each input signal is the only path to resolution without runtime data.

### Extended CAL Dump — Raw Data (+0x5A to +0xAE)

The 64 bytes following the 7-element output table at +0x48 are unidentified:

| Offset | LE value | BE value | Notes |
|--------|----------|----------|-------|
| +0x5A | 2000 | 53255 | — |
| +0x5C | 200 | 51200 | — |
| +0x5E | 13 | 3328 | — |
| +0x60 | 0 | 0 | — |
| +0x62 | 2000 | 53255 | — |
| +0x64 | 0 | 0 | — |
| +0x66 | -13 (s16) | -3073 (s16) | — |
| +0x68–+0x6E | 1280, 128, 16384, -32768 | 5, 32768, 64, 128 | — |
| +0x70–+0x76 | 1508, 5150, 5150, 16476 | 58373, 7700, 7700, 23616 | — |
| +0x78–+0x82 | 0, 257, 983, 2458, 282, 1907 | (various) | — |
| +0x84–+0x86 | 1280, 1920 | 5, 32775 | — |
| +0x88–+0x90 | 3, 100, 20, 40, 50 | 768, 25600, 5120, 10240, 12800 | — |
| +0x92–+0x98 | 130, 140, 2500, 3000 | 33280, 35840, 50185, 47115 | — |
| +0x9A | 0 | 0 | — |

This region may be filter coefficients, IIR tap weights, or intermediate computation constants. Its role is unknown.

### Structured Data Beyond +0x9A

| Offset | LE value(s) | Notes |
|--------|-------------|-------|
| +0x9C–+0xA2 | 1638, 1638, 1638, 1638 | 4 identical values; count matches the 4-element axis hypothesis above |
| +0xA4–+0xA8 | 16384, 16384, 16384 | 3 identical values |
| +0xAA–+0xAC | 0, 0 | 2 zeros |
| +0xAE–+0xBE | 80, 160, 320, 480, 640, 800, 960, 1120, 1280 | Monotone 9-element sequence |
| +0xC0–+0xD2 | -4,-4,-15,-15,-20,-25,-30,-40,-40,-40 (s16) | 10 negative values |
| +0xD4 | -3000 (s16) | Anomalous |
| +0xD6–+0xD8 | -80, -70 (s16) | — |
| +0xDA | 0 | — |
| +0xDC–+0xE6 | 70, 80, 300, 600, 800, 3000 | Monotone 6-element sequence |
| +0xE8–+0xFA | -10,-10,-7,-4,-15,-15,-20,-40,-100,-100 (s16) | 10 negative values |
| +0xFC | 0 | — |

The 9-element and 6-element sequences paired with arrays of negative values resemble axis+output table structure. The negative output values are consistent with the spec description of a gradient limiter for deceleration. These are structural observations, not confirmed interpretations.

A further structured region begins near +0x11E with what looks like another set of axes and outputs (including LE=[80,200,400,800,3000] followed by values [62,35,15,10,10,1] and [20,40,70,70]). A fourth cluster near +0x14A begins with LE=[2000,5000,7500,10000].

### Open Questions

- **Byte order of SRAM inputs**: Cannot be determined without tracing the CAN RX handlers that populate VehSpd, BrakePress, and TrqLast into SRAM.
- **Which dump column to trust for each axis**: Follows directly from the byte order question above.
- **Mystery region +0x5A to +0x9A**: Role unknown.
- **Position of Y-axis data** for TrqLast, BrakePress: Not traced — the 4×1638 and 3×16384+2×0 groupings near +0x9C and +0xA4 are plausible candidates given their counts, but require handler chain advance tracing to confirm.
- **VehSpd Y units**: What does the value 116 (first element of the 7-element output table at +0x48) represent in physical terms?

---

## §10.7 CAL Gradient Limit Y-Axis Hypothesis — Session 2026-05-05

### Context

This session attempted to trace R11 (the SRAM data pointer that becomes R2 at E5CC entry) to identify the exact SRAM addresses of the gradient limiter's input signals. The trace was not completed due to the VM bytecode architecture (see below), but produced new structural observations about the CAL region.

### VM Bytecode Architecture — Confirmed

The code region 0x8006C000–0x8006D200 (and likely much of the DLCM text segment) is a **threaded-code bytecode VM**, not straight-line SH-4 machine code. This explains:

- No `STS.L PR` / `RTS` instructions in the C800-D200 range despite many BSR calls.
- Garbled disassembly: the bytes between BSR instructions are bytecode arguments and literal pool constants, not SH-4 opcodes.
- The `MOV.L @(PC+60),R9` pattern appearing after every BSR: loading the next bytecode argument into R9 for the handler.
- `MAC.L @R15+,@R2+` appearing ubiquitously: these are real SH-4 opcodes that the interpreter executes as part of the bytecode semantics, advancing R2 (the bytecode PC or data pointer) and R15 (stack/argument frame).

The interpreter is likely a variant of **token-threaded code** where each "instruction" is a BSR to a handler function. The handler reads its operands from [PR] (= the return address, which points to the next bytecode word), then jumps to the next handler rather than executing RTS.

R11 is used by the interpreter as a **signal context block offset** or **GBR word-offset**. Before each of the four BSR-to-DBC handlers at D152/D176/D198/D1BE, R11's lower 16 bits are zero-extended into the argument register (R6, R8, R8, R2 respectively). The value of R11 could not be traced to a static source — it is set by the interpreter engine at runtime from the bytecode stream or from a per-task context block.

### Raw CAL Data at 0x80021400 — Confirmed Structure

Dumped directly from cal.bin. All values shown as raw bytes `HH LL`, LE u16, and BE u16:

```
+0000  B8 0B  LE=  3000  BE= 47115  <- unidentified monotone sequence
+0002  A0 0F  LE=  4000  BE= 40975
+0004  88 13  LE=  5000  BE= 34835
+0006  70 17  LE=  6000  BE= 28695
+0008  4C 1D  LE=  7500  BE= 19485
+000a  28 23  LE=  9000  BE= 10275
+000c  10 27  LE= 10000  BE=  4135
+000e  00 00  LE=     0  BE=     0  <- separator/terminator
+0010  00 00  LE=     0  BE=     0
+0012  00 01  LE=   256  BE=     1  <- dispatch token (BE=1)?
+0014  80 01  LE=   384  BE= 32769  <- dispatch token (BE=0x8001)?
+0016  00 05  LE=  1280  BE=     5  <- TrqLast X[0]=5 (BE) HYPOTHESIS
+0018  00 19  LE=  6400  BE=    25  <- TrqLast X[1]=25 (BE)
+001a  00 28  LE= 10240  BE=    40  <- TrqLast X[2]=40 (BE)
+001c  00 41  LE= 16640  BE=    65  <- TrqLast X[3]=65 (BE)
+001e  00 00  LE=     0  BE=     0  <- separator
+0020  00 00  LE=     0  BE=     0
+0022  64 00  LE=   100  BE= 25600  <- BrakePress X[0]=100 (LE) HYPOTHESIS
+0024  C8 00  LE=   200  BE= 51200  <- BrakePress X[1]=200 (LE)
+0026  2C 01  LE=   300  BE= 11265  <- BrakePress X[2]=300 (LE)
+0028  B8 0B  LE=  3000  BE= 47115  <- BrakePress X[3]=3000 (LE)
+002a  00 00  LE=     0  BE=     0  <- separator
+002c  00 00  LE=     0  BE=     0
+002e  00 03  LE=   768  BE=     3  <- dispatch token (BE=3)?
+0030  80 05  LE=  1408  BE= 32773  <- dispatch token (BE=0x8005)?
+0032  80 07  LE=  1920  BE= 32775  <- dispatch token (BE=0x8007)?
+0034  00 41  LE= 16640  BE=    65  <- dispatch token (BE=65)?
+0036  00 00  LE=     0  BE=     0  <- separator
+0038  00 00  LE=     0  BE=     0
+003a  00 05  LE=  1280  BE=     5  <- VehSpd X[0]=5 km/h (BE) HYPOTHESIS
+003c  00 14  LE=  5120  BE=    20  <- VehSpd X[1]=20 km/h (BE)
+003e  00 1E  LE=  7680  BE=    30  <- VehSpd X[2]=30 km/h (BE)
+0040  00 28  LE= 10240  BE=    40  <- VehSpd X[3]=40 km/h (BE)
+0042  00 32  LE= 12800  BE=    50  <- VehSpd X[4]=50 km/h (BE)
+0044  00 3C  LE= 15360  BE=    60  <- VehSpd X[5]=60 km/h (BE)
+0046  00 46  LE= 17920  BE=    70  <- VehSpd X[6]=70 km/h (BE)
+0048  74 00  LE=   116  BE= 29696  <- ???  Y[0] at VehSpd=5? HYPOTHESIS
+004a  75 00  LE=   117  BE= 29952  <- ???  Y[1] at VehSpd=20?
+004c  89 00  LE=   137  BE= 35072  <- ???  Y[2] at VehSpd=30?
+004e  A5 00  LE=   165  BE= 42240  <- ???  Y[3] at VehSpd=40?
+0050  CC 00  LE=   204  BE= 52224  <- ???  Y[4] at VehSpd=50?
+0052  FE 00  LE=   254  BE= 65024  <- ???  Y[5] at VehSpd=60?
+0054  3B 01  LE=   315  BE= 15105  <- ???  Y[6] at VehSpd=70?
+0056  84 01  LE=   388  BE= 33793  <- ???  Y[7] or start of next table?
+0058  00 00  LE=     0  BE=     0  <- separator?
```

### The Inconsistent Endianness Problem — Why It Doesn't Make Sense

The LE/BE inconsistency across the axes is the core unsolved problem. The specific inconsistency:

- BrakePress axis: only LE readings make physical sense ([100, 200, 300, 3000])
- VehSpd axis: only BE readings make physical sense ([5, 20, 30, 40, 50, 60, 70] km/h)
- TrqLast axis: only BE readings make physical sense ([5, 25, 40, 65] Nm)

The raw bytes for VehSpd X[0]: `00 05`. As LE = 0x0500 = 1280. As BE = 0x0005 = 5.

So the SRAM representation (and therefore the SIGNED comparison in MAC.W) must use different byte ordering for different signals. This could be because different CAN RX handlers process the signals differently — Motorola vs. Intel CAN signals are processed natively in their frame encoding without conversion. This is consistent with the DBC: WheelSpeeds (VehSpd source) are Motorola BE.

**But this still doesn't explain why the Y values at +0x48 use LE** (bytes `74 00` = 116 LE, 29696 BE). The Y values are not CAN signals — they are gradient limit outputs computed by the ECU. Their byte order depends on how the code reads them and how MAC.W interprets them, not on CAN encoding. This remains unexplained.

### Gradient Limit Y-Axis Hypothesis

**Hypothesis**: The 7 values at cal.bin offset 0x1448–0x1454 (bytes `74 00 75 00 89 00 A5 00 CC 00 FE 00 3B 01`) are the gradient limit Y-axis outputs for the VehSpd dimension. Read as LE u16 = [116, 117, 137, 165, 204, 254, 315].

**Evidence for**:
- These 7 values immediately follow the 7-element VehSpd X axis in the CAL stream — the correct position for Y values in a paired X/Y table.
- The values are monotone-increasing, consistent with a gradient limit that allows faster torque changes at higher speed.
- The count (7) matches the VehSpd X axis count (7).

**Evidence against / reasons for doubt**:
- The byte order of the Y values (LE) is inconsistent with the VehSpd X axis (BE). No explanation for this asymmetry has been found.
- The MAC.W computation accumulates MACL across multiple signals (TrqLast, BrakePress, VehSpd). The final gradient limit may not come from a simple Y-axis lookup at +0x48 — it may be a product of multiple MAC.W contributions, and the bytes at +0x48 may be coefficients in that product rather than direct gradient limits.
- The value 388 at +0x56 (cal.bin 0x1456) may be an additional 8th Y value (extrapolation clamp), or the first element of a new unrelated table — ambiguous without confirming the table structure.
- Units are unknown. The numbers [116..315] could be in any internal ECU unit.

**Additional candidate region** (hypothesis): The 9-element sequence at +0xAE–0xBE:
`[80, 160, 320, 480, 640, 800, 960, 1120, 1280]` (LE u16)
This arithmetic sequence is suspiciously regular (step 160 from the third element onward). Its count (9) doesn't directly match any of the X axes identified (7, 4, 4). This may be a gradient limit table for a different input dimension, or for a different ECU function entirely.

### What Would Be Needed to Confirm

1. **Runtime capture**: Compare known physical conditions (e.g., VehSpd=30 km/h, low TrqLast) to the MACL output at E5CC's exit. If MACL correlates with the value 137 (Y[2] at VehSpd=30), the hypothesis is confirmed.
2. **Edited CAL test**: Double all values at 0x1448–0x1454 and observe whether anti-lash filtering speed changes proportionally. This is the fastest practical path.
3. **CAN handler trace**: Trace the VehSpd CAN RX handler to confirm that SRAM stores the value as BE (no byte swap), which would explain the BE X axis — and separately confirm how the Y output bytes are read (LE or BE), explaining the Y byte order.

### cal.bin Edit Locations (Hypothesis Only — Not Confirmed)

If the hypothesis is correct, bytes to edit to double the gradient limit (allow 2x faster torque ramp):

| cal.bin offset | Current bytes | Current LE value | 2x LE value | New bytes |
|----------------|---------------|-----------------|-------------|-----------|
| 0x1448 | `74 00` | 116 | 232 | `E8 00` |
| 0x144A | `75 00` | 117 | 234 | `EA 00` |
| 0x144C | `89 00` | 137 | 274 | `12 01` |
| 0x144E | `A5 00` | 165 | 330 | `4A 01` |
| 0x1450 | `CC 00` | 204 | 408 | `98 01` |
| 0x1452 | `FE 00` | 254 | 508 | `FC 01` |
| 0x1454 | `3B 01` | 315 | 630 | `76 02` |

These edits are **not confirmed safe or correct**. They should only be applied with full awareness that the hypothesis may be wrong and the actual effect (if any) is unknown.

---

## 2026-09-13 — the mapping crack: mixed-endian pointer network + module registration table

Session goal: find the indirect memory mapping from the torque-filtering
constants, i.e. resolve `[[R13+0x34]+0x34]` to CAL addresses. Result: the
mapping's **static structure is now decoded** (registration table + dispatch
stubs + CAL offsets); the final *numeric* link (runtime MDB/table pointer
values) is not statically obtainable and goes to live RAM read (Route A plan).
Scratchpad: `artifacts/module_mapping_recon.py` (+ `.out.txt` phase series).
Emulator: `artifacts/dlcm_init_emulator.py`. Ghidra: `DlcmInitTrace.java`.

### 1. Why every prior pointer scan was blind (the endianness resolution)

The torque task's R13 is a **static literal, stored big-endian**:
`pool[0x800677C8] = d9 04 7b 5c` = `0xD9047B5C`, loaded at `0x800676B8`
(`DD43 mov.l @(0x10c,pc),r13`). All prior "zero pointers" results came from
LE-only scans (after the 2026-05-06 "CAL is LE i16" finding); BE hits were
dismissed as spurious. Re-running the inventory big-endian surfaces the
network the LE scans missed: `0xD9047B5C` (3 pool slots), `0x7F0F0880` (the
filter ring buffer — all seven documented load sites), and the
`0xD9FFB830`/`0xD9FFB930`/`0xD922B930/BA30/BB30` coefficient-buffer family.

**Pool storage is mixed-endian (evidence: this session, HIGH confidence):**
assembler/emitted address literals are BE (same byte order as the instruction
stream they sit in; CPU data accesses are BE); calibration-tool-generated
tables (CAL, the 0x80041800 descriptor array, the 0x80041E00 dispatch table)
are LE and swapped in software where needed. Confirmed samples: pool
`0x800677C8` BE = `0xD9047B5C` (real RAM pointer) vs pool `0x80073710` LE =
`0x80020820` (real CAL pointer) vs dispatch-table entry `0x80041E00` LE =
`0x80080C08` (real code pointer). This **resolves the "Inconsistent
Endianness Problem" loose end** from the earlier passes: there is no
per-axis endianness split inside CAL — the split is *provenance* (assembler
BE vs cal-tool LE), nothing more mysterious.

### 2. The "indirect memory mapping" is a physical registration structure

The 24-record descriptor array at **0x80041800** is the module registration
table, and **0x800673FC–0x80067A60** is a dispatch-stub table: ~0x2A-byte
stubs, each embedding its context pointer as an **inline BE u32** (not a pool
— invisible to every pool scan, the second reason "zero code references" was
an artifact). Decoded layout (record stride 0x34 for records 0–16; records
17–23 are a 0x28-stride second family):

| field | meaning (evidence level) |
|---|---|
| +0x00 | type byte (0x04–0x08) + `ff 01 01` marker (confirmed) |
| +0x08 | module entry stub ptr into 0x80067568–0x800678xx (confirmed) |
| +0x0C | per-record u16 ID into 0x80041F00 table (confirmed) |
| +0x18 | per-record 6-byte companion record into 0x80067AD8 table (confirmed) |
| +0x24 | u16 config pair, e.g. (40,40), (200,200), (400,400) (confirmed data; role hypothesis) |
| +0x2C | **CAL offset** — for 10/17 records it lands on clean per-module calibration data (rec 7 → `0x80021714`; rec 9 → `0x8002165C` descending `[11000,5000,...]`; rec 10 → `0x80021680` monotone `[7000..16000]`) |
| +0x30 | **CAL offset + size-ish pair** — rec 16 (32,0) → `0x80020020` **CAL part-number header** (clean validation); rec 5 (960,0) → `0x800214C0` **the negative gradient curve**; rec 13 (768,4) → `0x80021400`; rec 15 (832,4) → `0x80021440` (`[116,117,137,...]`); recs 3/8/12 (8288/8352/8384) → `0x80022060–0x800220C0` |

Stub→context mapping (inline BE values at ~0x2A stride, confirmed):

- **Records 0–16 (stubs 0x80067568–0x80067834) all share ONE context struct:
  `0xD9047B5C`** — the driveline/torque context (not per-module structs).
- **Records 17–23 share a second context: `0xD9057B5C`.**
- **The torque module is record 7** (type 0x07, stub `0x80067698` — the R13
  load `0x800676B8` sits inside its stub range; its body is `bsr 0x8006704C`).
  Its CAL offsets: +0x2C=1556 → `0x80021714`; +0x30=(1120,0) → `0x80021560`.

The exact base/field semantics of +0x2C/+0x30 (which base address each is
relative to, and the second +0x30 word's role) are the one remaining static
ambiguity — they are runtime-computed (base+offset, which is why no absolute
CAL pointers exist in PROG), to be pinned by the Route A RAM read.

### 3. New candidate for the fixed ~8 cts/update near-zero clamp (open item 5)

Sibling records 8 (+0x2C=522) and 12 (+0x2C=526) — two calibration variants
of one torque-path module — point into the same small constants block at
**`0x80021308`: `[100, 8, 8, 50, 20, 135, 0, 25, 25, 80, 10, 200, 200]`**
(LE i16). Two adjacent `8`s, right magnitude (cts/update units, consistent
with the live-edit-confirmed V-curve units), inside the §10.7 bank,
registered to torque-path modules. **HYPOTHESIS (unconfirmed):** one of these
`8`s (or a near neighbor) is the fixed near-zero positive-rate clamp that
`map_rate_limit.py` measured (~7–9 cts/update, speed-flat, below both
`min()` limbs). Confirmation route: Route A RAM read (check whether the
runtime torque structure references this block), then a live edit.

### 4. The remaining wall, now precisely characterized

The code that *populates* `[0xD9047B5C+0x34]` (the MDB pointer) is saturated
with Continental variant opcodes whose semantics are unknown. Verified two
independent ways this session: (a) Ghidra with the 529-stub SLEIGH truncates
decompiles in the init band with "bad instruction data" (`DlcmInitTrace.java`
output `~/ghidra-projects/dlcm_export/init_trace.txt`); (b) a purpose-built
bare-metal SH-4 interpreter (`artifacts/dlcm_init_emulator.py` — written
because Unicorn 2.1.4 has no SH-4) derails within tens of instructions: the
variants carry real control-flow semantics (loop guards/register moves), so
NOP-ing them breaks execution. The MDB pointer is not a pool or inline
literal anywhere in PROG (endianness-complete scans); it is computed at
runtime. Priority decode targets recorded for Route B: `0x49A4/0x4944/0x49A5,
0x8204/0x8212/0x8216/0x8234, 0x438E/0x4C8E, 0x0220/0x0480, 0x0040/0x0090,
0x8CCF, 0xFFFA, 0x40F2, 0x0920, 0x010A, 0x0F50, 0x000A`.

### 5. Route forward (decided 2026-09-13)

- **Route A — NEXT STEP: live RAM read via UDS ReadMemoryByAddress (0x23).**
  Walk `[0xD9047B90]` → MDB → `[MDB+0x34]` → tables; content-match to CAL;
  produce the definitive mapping table. Read-only toward the ECU. Car + both
  dongles available on the car-side laptop (not this machine).
  Plan: `projects/coda/notes/plans/dlcm_ram_read_mapping.md`.
  **Step-0 service inventory DONE (same day):** normal mode = `10 01` + 0x22
  loop on 11 DIDs, unlocked, no 0x23 seen; the app's 0x22 stack IS in PROG —
  11-record DID descriptor table at `0x80040C38` (4) + `0x80041174` (7),
  20-byte records `(DID, len, flags, rsvd, RAM data ptr, handler ptr)`, DID
  data in RAM `0xD0006Cxx`/`0xD000534C`. Programming mode = `10 02` → `27`
  levels 01/02 → erase (~10 s NRC-0x78 gaps = injection windows). 0x23 support
  indeterminate statically, so the car-side plan probes it FIRST with a single
  dongle in default session (no Omitec/MITM needed for the first attempt);
  escalates to the MITM+Omitec path only if security-gated. Script:
  `artifacts/uds_service_inventory.py` (+ `.out.txt`).
- **Route B — backup: decode the variant opcodes, then emulate the init path**
  (`dlcm_init_emulator.py`) to extract the same mapping statically; backport
  semantics into `ghidra/sleigh/continental-stubs.sinc`.
  Plan: `projects/coda/notes/plans/dlcm_variant_opcode_decode.md`.
- **Route C (blind empirical edit campaign on the 0x80021308 candidate) —
  declined for now.**

### New artifacts (this session)

- `artifacts/module_mapping_recon.py` + `module_mapping_recon*.out.txt` —
  phased recon: descriptor-table decode, endianness-complete pool inventories,
  stub-band inline-pointer scan, CAL scalar/clamp scans, referrer analysis.
- `artifacts/dlcm_init_emulator.py` + `.out.txt` — bare-metal BE SH-4
  interpreter (sparse paged memory, watch windows, pointer-store log) with
  init-path scenarios; demonstrates the variant wall empirically.
- `ghidra/scripts/DlcmInitTrace.java` — init-band seed/decompile dump (output
  `~/ghidra-projects/dlcm_export/init_trace.txt`).

---

## The firmware's own CAN configuration tables — full message inventory (2026-09-24)

The DLCM does not scatter its CAN handling through code: it carries a COM
configuration in flash, and reading it gives a **closed inventory** of every
message the ECU sends or receives. This supersedes every ID list derived from
SH-4 pattern matching (see the supersession note at the end of this section).

Entry point is the master CAN config at **`0x80041DA4`**, already found during the
0x212 transmit-chain trace (`dlcm-torque-limiter-code-trace.md`, 2026-09-19):

```
master CAN config              0x80041DA4
  +0x00 -> RX message table    0x8004162C   26 x 52B
  +0x04 -> TX message table    0x80041B74   14 x 40B
  +0x10 =  26   (RX count)
  +0x14 -> RX signal table     0x80041490   27 x  8B
  +0x18 -> TX signal table     0x80041568        x 12B
  +0x1C =  27   (RX signal count);  +0x1E = TX signal count
```

The three tables are contiguous: RX signal table ends where the TX signal table
begins, which ends at the RX message table, which ends at the TX message table,
which ends at the config struct itself.

### Message record layout

Common prefix for RX and TX records:

| Offset | Type | Meaning |
|---|---|---|
| `+0x00` | u32 | CAN id |
| `+0x04` | u16 | frame buffer offset |
| `+0x06` | u16 | period (TX) or expected period / timeout (RX), in **5 ms ticks** |
| `+0x08` | u8 | DLC — **RX records only** |
| `+0x0A` | u8 | DLC — **TX records only** |
| `+0x10` | u32 | per-message handler stub (RX stubs run `0x800673EA` upward at a 42-byte stride) |

The period field is verified against measured bus rates: `0x580` = 200 ticks and
is 1.0 Hz on the wire; `0x055C` = 20 ticks and is 9.9 Hz; `0x1D5` = 5 ticks and
is 39.9 Hz; `0x212` = 4 ticks and is 49.9 Hz; `0x308` = 2 ticks and is 99.7 Hz.

### Hardware mailbox / acceptance-filter array

A separate array at **`0x800422E8`**, stride 12B, `+0x00` = id, `+0x04` = mask
(`0x7FF` throughout), `+0x08` = optional callback pointer. 51 entries, indexed by
an 8-byte `(handle, pointer)` table starting at `0x8004254C` with handles from
`0x0100`. It is the union of both COM tables plus the diagnostic addresses and
three ids that have no COM record at all. `0x7E1`/`0x7E9` appear twice.

This array — not the `0x8008FCxx` address guessed in Phase 27 — is the mailbox
configuration.

### TX table — the 14 messages the DLCM transmits

`0x80041B74`, stride 40. "Wire" is a survey of `projects/coda/logs/driverinputpart4.log`
(bus 2 = D CAN, bus 3 = B CAN in that capture).

| ID | Period | DLC | DBC | Wire |
|---|---|---|---|---|
| `0x052` | 50 ms | 8 | `ParkingBrake_0x052`, sender `Vector__XXX` | 20.0 Hz |
| `0x08C` | 1000 ms | 1 | **absent** | 1.0 Hz |
| `0x210` | 20 ms | 6 | `VehicleMode_0x210`, sender `Vector__XXX` | 49.9 Hz |
| `0x212` | 20 ms | 6 | `DLCM_TorqueRequest` | 49.9 Hz |
| `0x278` | 20 ms | 8 | `DLCM_DriveKeepalive`, **DBC DLC 2** | 49.9 Hz, DLC 8 |
| `0x308` | 10 ms | 5 | `TCM_ParkPin`, sender `Vector__XXX` | 99.7 Hz |
| `0x312` | 10 ms | 8 | **absent** | 99.7 Hz |
| `0x315` | 20 ms | 6 | `DLCMStatus` | 49.9 Hz |
| `0x418` | 20 ms | 6 | `DLCM_Globals_0x418` | 49.9 Hz |
| `0x591` | event | 7 | **absent** | not seen |
| `0x592` | event | 8 | **absent** | not seen |
| `0x595` | event | 8 | **absent** | not seen |
| `0x204` | 10 ms | 5 | **absent** | not seen — second buffer region |
| `0x207` | 480 ms | 8 | **absent** | not seen — second buffer region |

### RX table — the 26 messages the DLCM receives

`0x8004162C`, stride 52.

| ID | Expected period | DLC | DBC | Wire |
|---|---|---|---|---|
| `0x051` | 100 ms | 8 | **absent** | 10.0 Hz |
| `0x168` | 100 ms | 8 | **absent** | not seen |
| `0x1D5` | 25 ms | 7 | B CAN `DCDCStatus1` (DLC 8) | 39.9 Hz, DLC 8 |
| `0x200` | 20 ms | 8 | `ESC_FrontWheelSpeeds` | 99.8 Hz |
| `0x208` | 20 ms | 8 | `ESC_BrakePressure` | 99.8 Hz |
| `0x215` | 20 ms | 7 | `misc_0x215`, **DBC DLC 2** | 49.9 Hz, DLC 7 |
| `0x271` | 20 ms | 8 | `misc_0x271` | 10.0 Hz (bus 3 only in this capture) |
| `0x275` | 100 ms | 8 | B CAN `BMSDriveLimits` | 10.0 Hz |
| `0x276` | 100 ms | 8 | B CAN `HVACStatus` | 9.6 Hz |
| `0x300` | 20 ms | 8 | `ESC_0x300` | 49.9 Hz |
| `0x330` | 20 ms | 8 | `misc_0x330` | 49.9 Hz |
| `0x370` | 20 ms | 8 | `misc_0x370` | 49.9 Hz |
| `0x383` | 100 ms | 8 | B CAN `BMSBattStatus` | 10.0 Hz |
| `0x491` | 100 ms | 8 | B CAN `IPK_Cluster` | 10.0 Hz |
| `0x55C` | 100 ms | 4 | `TCM_State` | 9.9 Hz |
| `0x580` | 1000 ms | 4 | `DCANAnchor_0x580` | 1.0 Hz |
| `0x593` | event | 8 | **absent** | not seen |
| `0x603` | event | 7 | **absent** | not seen |
| `0x614` | event | 8 | **absent** | not seen |
| `0x209` | 10 ms | 8 | **absent** | not seen — second buffer region |
| `0x20A` | 25 ms | 8 | **absent** | not seen — second buffer region |
| `0x20B` | 10 ms | 6 | **absent** | not seen — second buffer region |
| `0x20C` | 10 ms | 6 | **absent** | not seen — second buffer region |
| `0x20D` | 25 ms | 8 | **absent** | not seen — second buffer region |
| `0x20E` | 100 ms | 8 | **absent** | not seen — second buffer region |
| `0x20F` | 480 ms | 8 | **absent** | not seen — second buffer region |

The B CAN ids in this table are the ones the DBC already documents as gateway
rebroadcasts; the DLCM has no B CAN interface, so it reads them off D CAN.

### Mailbox-only ids — no COM record

| ID | Callback | Note |
|---|---|---|
| `0x7DF` | `0x800422B8` | OBD functional request |
| `0x7E0` | `0x800422C0` | tester -> ECU |
| `0x7E8` | `0x800422C8` | ECU -> tester |
| `0x7E1`, `0x7E9` | none | second diagnostic pair, listed twice |
| `0x7FF` | none | terminator / catch-all |
| `0x240` | none | `SystemState_0x240`, 40.0 Hz on the wire |
| `0x241` | none | `MCM_Thermal`, DBC sender DLCM, 1.0 Hz |
| `0x1C0` | none | `MCM_CoreTelemetry`, DBC sender DLCM, 99.7 Hz |

`0x1C0`, `0x241` and `0x240` are filtered by hardware but handled outside the
generic COM stack. This is consistent with the DBC's description of `0x1C0` and
`0x241` as relays of Motor CAN data, and it explains why the Phase 26 scan for a
`0x0241` transmit site found nothing: there is no COM TX record to find.

### Hypothesis: the second buffer region is M_CAN

Nine records — TX `0x204`, `0x207` and RX `0x209`, `0x20A`, `0x20B`, `0x20C`,
`0x20D`, `0x20E`, `0x20F` — use frame buffer offsets at `0x2020`-`0x2160`, while
every other record in both tables uses an offset below `0x1000`. Exactly those
nine are absent from every D CAN capture surveyed.

Supporting evidence, all circumstantial:

- The counts match the MCM spec §7.1 inventory exactly: **2 DLCM -> MCM**
  (TorqueCommandMessage, ResetCANWatchdogTimer) and **7 MCM -> DLCM**
  (AccurateFeedbacks_Mech, AccurateFeedbacks_Elec, AccurateFeedbacks,
  SystemStatusMessage, Temperature, limited_torque_percentage,
  CANWatchdogStatus).
- `0x204` transmits every **10 ms**, matching the Coda-specific Universal Command
  rate documented in the Dilithium VCU manual (10 ms for Coda against 125 ms for
  standard UQM).

**Not confirmed.** The buffer-region split is the only structural evidence that
these are a different physical channel; the absence from captures is equally
explained by a message that simply never appears in the logged conditions. Per
message assignment within the nine is unassigned.

### What this says about the DBC

Presented and pending review; the DBC has not been edited.

- **Sender attribution.** `0x052`, `0x210` and `0x308` are in the DLCM TX table
  with periods matching the wire exactly, but are `Vector__XXX` in the DBC, and
  `0x308` is named and commented as a BorgWarner TCM message.
- **DLC.** `0x278 DLCM_DriveKeepalive` is DLC 8 in the firmware and on the wire,
  2 in the DBC. `0x215 misc_0x215` is DLC 7 in the firmware and on the wire, 2 in
  the DBC.
- **Missing from the DBC entirely**, on the D CAN wire: `0x312` (10 ms, DLC 8),
  `0x08C` (1 s, DLC 1), `0x051` (100 ms, DLC 8). Configured but not seen in the
  surveyed capture: `0x168`. Event-driven and not seen: TX `0x591`/`0x592`/`0x595`,
  RX `0x593`/`0x603`/`0x614`.
- **In the DBC, in no firmware table:** `0x080 EPS_SteeringAngle`,
  `0x248 ExteriorLights_0x248`, `0x325 DCANAnchor_0x325`, `0x600 misc_0x600`,
  `0x6FA GWM_VIN`. The DLCM neither filters nor consumes them.

### Supersedes the Phase 26 / Phase 27 Motor CAN ids

Phases 23-27 identified the Motor CAN ids as `0x0048`, `0x0100`, `0x0222`,
`0x0500` and `0x02FF`, and concluded that `0x0222` is the source of MCM_Thermal.
**All of that is void.** It came from matching a supposed `00FD` receive-filter
opcode in an SH-4 decode of a TriCore image; none of those five ids appears in
either COM table or in the mailbox array. The real configured id set is the one
tabulated above. Those sections are left in place as a record of the method
failure, not as findings.

### Reproduction

`artifacts/dlcm_can_table_inventory.py` dumps all three tables from
`coda_dlcm_prog.bin` and joins them to the three Coda DBCs and to a survey of a
capture. The survey it reads is `artifacts/survey_driverinputpart4.txt`
(`python3.13 tools/survey.py projects/coda/logs/driverinputpart4.log`).

---

## What each configured message actually carries (2026-09-24)

The message tables above say which messages exist. This section says what is in
them. Everything here is read out of the TriCore image and then checked against
logs; where the two disagree the check is recorded rather than the conclusion.

### The accessor band — and why the field map is complete

The DLCM never touches a CAN payload in application code. `FUN_8008008C` fetches
each received message into a per-message RAM buffer with
`FUN_800686D8(buf, sig)`, and **every** read of those buffers goes through one of
**120 tiny getters in the contiguous band `0x800803FA`-`0x80080B4A`**. That
completeness is checked, not assumed: an A0-relative scan over the whole buffer
region returns zero references from outside the band. Each getter names one byte
or byte pair and a mask, so the band is the module's own declaration of every
received field's bit layout.

Transmitted messages are assembled inline in `FUN_80080C14` into staging buffers
and published with `FUN_800685C4(buf, sig)`.

`sig` resolves to a CAN id through the signal tables at `0x80041490` (RX, 27 x 8B)
and `0x80041568` (TX, 15 x 12B), whose first byte is the message-table index. Two
messages carry two signal records each and are split across them: RX `0x20A` and
TX `0x204`.

Tooling: `ghidra/scripts/DlcmBandDecompile.java`, `ghidra/scripts/DlcmCanHandlers.java`,
`ghidra/scripts/DlcmCanSignalUsers.java`; `artifacts/dlcm_signal_map.py` joins the
result to the DBCs, `artifacts/verify_signal_map.py` checks the conflicts against
logs.

### 0x312 — the DLCM's torque and torque-limit broadcast

**It is not an ESC message.** It is TX record 10 in the DLCM's own transmit table
at 10 ms, and `FUN_80080C14` writes all eight bytes from the `0xD00069Dx` mirror
block that `FUN_80074780` fills with `internal * 0.4 + 2000`.

| Bits | Field | Check |
|---|---|---|
| B0[4:0],B1 | torque feedback | r = 0.9994 against `0x1C0` Torque; least-squares slope **0.24993 Nm/count, zero at 1999.5** |
| B0 bit5 | parity over `(B0 & 0x5F) ^ B1` | **197,193 / 197,193** |
| B0 bit6 | alternating toggle | 50/50, independent of the data |
| B2[4:0],B3 | duplicate of B0[4:0],B1 | identical in **100 %** of frames |
| B4[4:0],B5 | **M_MAX** | 0 … +299.75 Nm |
| B6[4:0],B7 | **M_MIN** | −300 … 0 Nm |

The `0x212` request lies inside [M_MIN, M_MAX] in 99.997 % of samples and sits
exactly on M_MAX in 1.07 %. Actual torque never leaves the band. **M_MAX collapses
to +29.75 Nm while the brake switch is on** — +299.75 Nm in 100.0 % of 90,230
brake-off frames, +29.75 Nm in 97.2 % of 1,650 brake-on frames, the residue being
the transition. That is what `driver-inputs.md` recorded as an undecoded
brake-correlated signal.

The three-field layout and the M_MAX/M_MIN assignment were already in
`plans/dlcm_zero_crossing_cal_proposal.md` and `dlcm-cal-flash-campaign.md`; this
adds the source ECU, the duplicated field, the parity and toggle bits, the brake
behaviour, and confirmation of that file's `[hypothesis]` that bytes 2-3 are
achieved rather than requested torque — median error 0.90 Nm against `0x1C0`
versus 1.25 Nm against the `0x212` request. The two references are themselves
r = 0.99 to each other, so this supports the hypothesis without settling it.

**Scale note.** `plans/dlcm_zero_crossing_cal_proposal.md` records
`Nm = 0.23913 * tq_raw` for `0x212` against `0x1C0`. That is a regression of the
*request* against *achieved* torque, which the limiter's dynamics bias low. The
encoding is 0.25 Nm/count exactly, from `(v * 0x3333) >> 15` with
`0x3333/0x8000 = 0.40000` and internal units of 0.1 Nm. Do not re-derive the scale
by regression across the limiter.

### 0x591 / 0x592 / 0x603 / 0x614 — the RCU/DLCM immobiliser handshake

The factory manual's RCU immobiliser-functionality topic (internal-only)
describes the RCU authenticating to the DLCM by ciphered exchange, with "maximum 4 attempts,
approximately one each 100 ms" and a password paired into both modules. The four
event-driven ids are that exchange:

```
0x603  02 FF 00 01 18 00 00     RCU  -> DLCM   idle / status   (237 of 313 frames)
0x603  11 FF 00 00 18 00 00     RCU  -> DLCM   start
0x603  20 01 00 01 18 00 00     RCU  -> DLCM   request challenge
0x592  <8 bytes, all distinct>  DLCM -> RCU    challenge       (+10 ms)
0x614  <8 bytes, all distinct>  RCU  -> DLCM   response        (+5 ms)
0x591  A0 00 00 00 00 00 00     DLCM -> RCU    verdict         (+15 ms)
```

Corpus-wide `0x591` B0 takes **exactly two values**, `0xA0` (31 frames) and `0xB0`
(12) — precisely what `FUN_8007385E` can emit, `(flag != 1) * 0x10 + 0xA0`.
`FUN_80073A8C` builds the challenge from a random source plus a flash constant at
`0x80043F2D`. The retry counter in `FUN_80073F24` latches a lockout at 4 attempts,
matching the manual. All four are D CAN only and never gateway-rebroadcast, which
fits the RCU being D CAN only.

Which of `0xA0`/`0xB0` means pass is inferred from the ordering (`0xA0` follows a
completed exchange, `0xB0` appears alone), not proved.

`0x168` belongs to the same subsystem and has never been seen on a bus:
`FUN_80073824` reads a 32-bit field from it and compares against a key derived
with **`0x9D89EA36`, the SecurityAccess level-3 constant**, latching the same
lockout flag. *Hypothesis:* the DLCM side of the scan-tool "Immobilizer Password
Learn" procedure. `0x593` is read by the firmware but never observed; `0x595` has
no publish call anywhere in the image. Both are dead on this build.

### 0x051 and 0x08C

`0x051` is received at 100 ms and consumed: `FUN_800806B4` returns B0, and
`FUN_80074390` treats `0x00` or `0x55` as valid and otherwise raises DTC events
`0x2D`, `0x76` and `0x64`. The payload is all-zero in **4,374,280 frames across
1,022 corpus captures**. The transmitter is not identified anywhere in the DLCM
image.

`0x08C` is transmitted at 1 Hz with DLC 1 and carries one bit, bit 2, written by
`FUN_800779D8` as a debounce-limited pulse: true while a condition holds *and* a
counter stays below the CAL threshold at `0xA002187A`, with a CAL override at
`0xA0021882`. Corpus-wide: 197,305 frames of `0x00` and **exactly two** of `0x04`,
both in `coda_20260715_162457_T0.log` about two seconds after that session's
`0x591 = 0xB0`. The bit's meaning rests on that single observation and is not
established.

### The nine M_CAN messages, assigned individually

Zero frames across 1,030 captures and 26 GB. Content identifies each against MCM
spec §7.1:

| ID | Period | Firmware evidence | Spec message |
|---|---|---|---|
| `0x204` TX | 10 ms | enable/direction bitfields, 16-bit torque from `0xD00069D0`, CRC via `FUN_80080052` | TorqueCommandMessage |
| `0x207` TX | 480 ms | constant `A5 A5 5A` | ResetCANWatchdogTimer |
| `0x209` | 10 ms | four LE uint16 accessors | AccurateFeedbacks (→ `0x1C0`) |
| `0x20B` | 10 ms | 2 x uint16 + CRC byte + 3-bit counter | AccurateFeedbacks_Elec (by elimination, 2026-10-09) |
| `0x20C` | 10 ms | identical layout | AccurateFeedbacks_Mech (2026-10-09) |
| `0x20A` | 25 ms | **24** distinct bit/byte accessors | SystemStatusMessage |
| `0x20D` | 25 ms | exactly two byte accessors | limited_torque_percentage |
| `0x20E` | 100 ms | exactly three byte accessors | Temperature (→ `0x241`) |
| `0x20F` | 480 ms | never read anywhere in the image | CANWatchdogStatus |

Two CRC-protected plus seven unprotected matches the spec's split exactly, and
`0x207`/`0x20F` share the 480 ms watchdog period. **`0x20C` is AccurateFeedbacks_Mech and
`0x20B` is AccurateFeedbacks_Elec** (resolved 2026-10-09, worklog §6H.69.5). The DLCM republishes
0x20C's two words, B0..B1 on 0x308 (speed) and B2..B3 on 0x312 TorqueFeedback, and both match
0x1C0 (the D-CAN relay of 0x209 AccurateFeedbacks) Motor_Speed / Torque on 99.2 / 99.1 % of frames
on the C4c drive, 0x1C0 leading by 17.5 ms. So 0x20C carries speed and torque, and 0x20B, the other
CRC-protected frame, is the current/voltage one by elimination. 0x20B is never logged, so its own
words have not been compared with anything. `0x312`'s limits are finer-grained than a byte (893
distinct values), so they are not a direct rescale of `0x20D`.

### The DBC diff — a repeated defect shape

Running the field map against the DBCs found one shape over and over: **a field
declared a byte or a word too wide, swallowing a counter's neighbours, a parity
bit or a validity bit.** Coda's house style is a 4-bit counter plus parity, and
12/13/14-bit values with flags in the top of the MSB.

| Message | Was | Is | Check |
|---|---|---|---|
| `0x208` BrakePressure | `23\|16@0` | 12-bit at `19\|12@0` + valid bit at `20\|1@0` | `FUN_8008062E` masks `0xF00`; `FUN_8008061C` reads B2 bit 4; both called from the same two consumers |
| `0x200` byte 1 | `WheelSpeed_RollingCounter 15\|8@0` | BrakeSW bit 0, 4-bit counter bits 5-2, parity bit 6 | counter +1 in 68,687/68,687; parity 68,688/68,688; BrakeSW 99.94 % vs `0x315` |
| `0x200` wheel speeds | `16@0` | `14@0` | B2/B4/B6 bits 7-6 = `0b11` in 196,707/196,707 — the source of "zero encoding 0xC000" |
| `0x208` rear speeds | `16@0` | `14@0` | same, 197,248/197,248 — **wire evidence only**, the DLCM does not read them |
| `0x315` RollingCounter | `7\|6@0` | `5\|4@0` + parity at `6\|1@0` | counter +1 in 98,596/98,596 (the 6-bit reading: 31.27 %); parity 98,597/98,597 |
| `0x212` | "two sub-frames at 25 Hz" | one 50 Hz message; B2 bit3 / B4 bit7 toggles, B2 bit2 / B4 bit6 parity | toggles 50.00 %, both parities 100.00 % over 98,597 frames |
| `0x308` ParkPinState | `7\|8@0` | 2-bit field at bits 6-5 | `FUN_80080C14` writes `DAT_d0006AF1 * 0x20 & 0x60` |

The 0x200 and 0x208 wheel-speed narrowing **moves every decoded value down by
49152**. The scale is unchanged, but anything that carried the `0xC000` offset in
its own code must be rechecked, and InfluxDB content for those signals is stale
until re-uploaded.

`0x308` was resolved separately against the Vtrux EPRI definition and data from both
vehicles, and the answer is bigger than a field width: **the DLCM transmits it and B0 is a
park *request*, not a park pin state report.** The Vtrux `epri-pt-bus.dbc` already declared
`SG_ ParkRequest : 5|2@1+` with `0 = OFF, 1 = Park, 2 = UnPark` and called the message the
HCU park request command; the Coda firmware writes precisely those bits. Direction confirmed
from data: the B0 change leads the TCM's own `0x55C` parkLockState in both directions on
both vehicles -- Coda +76, +89, +88, +85 ms across two P-R-N-D-N-R-P cycles, Vtrux +55 and
+65 ms -- which a pin-state report cannot do on park engage. The consequence is that B1-B2
is the DLCM *sending* motor speed to the TCM rather than the TCM reporting input shaft
speed. Full write-up and the corrected cross-vehicle table are in `notes/borgwarner.md`;
script `notes/artifacts/park_request_0x308_cross_vehicle.py`.

### A parser bug that made half the field map wrong (2026-09-26)

**62 of the 120 getters were recorded with a mask of `0xFF` when their real mask
was a single bit or a small field.** `artifacts/dlcm_signal_map.py` extracted the
mask with a regex matching only Ghidra's hex form, `& 0x..`, and Ghidra prints
small masks in decimal — `& 4`, `& 7`, `& 0x3f00`. Every decimal case fell through
to a default of "whole byte". No error was raised and the output looked ordinary.

Six messages were wrong in what was published here: `0x168` B0, `0x200` B0,
`0x20A` B0-B3, `0x370` B1, `0x55C` B0, `0x580` B1-B2. Two consequences beyond the
table itself:

- `0x200` B0 was recorded as a whole-byte read, which was quoted as evidence that
  the DLCM reads `SubFrameID`. It does not — it reads bit 2 only. See the RX-path
  section below.
- `0x55C` B0 was recorded as a whole-byte read, which hid a DBC defect. The
  firmware reads bits 2-0 (`FUN_80080940`), matching both `notes/borgwarner.md`
  and the Vtrux EPRI DBC against the Coda DBC's 8-bit `TCMState`. Corrected in
  `CODA-D-CAN.dbc` 2026-09-26.

Fixed by matching `& (0x[0-9a-f]+|\d+)` and parsing with `int(x, 0)`. Worth
keeping as an instance of the class in AGENTS.md → "Filters that fail silently":
a pattern matcher that quietly defaulted rather than failing when it met a format
it did not expect, across half a band, in a direction that looked plausible.

### Fields the DLCM consumes that no DBC signal covers

Not defects — gaps, and useful leads because they say the module cares.

- **`0x580`** ("signal content unknown"): eight single-bit fields, no bytes —
  B0 bits 4, 5, 6 and 7, B1 bits 2 and 6, B2 bits 1 and 3. Not a bare heartbeat.
  *(Corrected 2026-09-26; B1 and B2 were previously given here as whole bytes.)*
- **`0x370`**: seven fields feeding the DTC block in `FUN_80074478` — B0[3:0],
  B0[6:4], B1 bit 0, B1 bit 1, B1[3:2], B3[3:0], B3[7:4].
  *(Corrected 2026-09-26; B1 was previously given here as a whole byte, twice.)*
- **`0x300`**: B4 bit 7 (50 % toggle), B1 bit 7 (the MTOG_ESP candidate), B4 bits
  5 and 6 (both always 0 in 98,624 frames), and B2 masked `0x1F` with B3 as a
  second 13-bit torque field, constant `0x12C0` = +700 Nm, so non-binding.
  `MMAX_ESP_REGEN_TQ_REQ` at `36|13@0` is confirmed exactly by `FUN_80080572`.
- **`0x208` B0 bit 6** — read by `FUN_8008060E`, never set in any frame observed.
- **`0x491` B3 bits 3-0**, **`0x276` B2 bit 7**.

Conversely the DLCM does **not** read `0x300` YawRate, `0x200` B6-B7
(WheelSpeed_LF), or `0x208` ESPSysSts — the last of which is set in 197,078 of
197,248 frames.

---

## Does the DLCM gate on 0x200 SubFrameID? No — and its silence is not confirmation (2026-09-26)

Commissioned from `notes/artifacts/handoff_0x200_subframeid.md`, which asked two
things: does the receive path gate on `SubFrameID`, and does it decode `0x14`
through the same field layout as `0x00`. The handle is the accessor band.

### The finding

**Nothing in the image compares B0 against `0x00`, `0x14`, `0x1C`, `0x1E` or
`0x20`.** Neither layer gates:

- **COM layer.** The RX record for `0x200` carries a single signal record
  (`sig 0x8005`, 8 bytes, no mux field), and `FUN_800686D8` copies *every*
  `0x200` frame into `a0-0x1068` regardless of B0. The buffer holds whichever
  sub-frame arrived last.
- **Application.** `FUN_8006EF12` calls both wheel-speed getters
  unconditionally and rejects only the value `0x3FFF`.

The only part of B0 read anywhere is **bit 2**, by `FUN_800805EE`
(`(a0-0x1068) & 0x04`). It has two consumers: `FUN_8006ED3C`, which turns it
into a boolean at `a0-0x27C7`, and `FUN_800488C2`, the safety monitor, which
stores it with its complement under a verify-or-trap at `a0-0xC60`/`a0-0xC48`,
the same integrity treatment as brake pressure. It is a safety-relevant ESC
status bit, not a frame selector.

### What that does and does not establish

It **does** establish that the DLCM applies one field layout to every sub-frame,
because it has only one and no way to select between them.

It does **not** corroborate the DBC's claim that `0x14` carries the same wheel
speed layout as `0x00`. That is a claim about what the *ESC emits*, and the
firmware never inspects the byte that would distinguish them — so the absence of
a gate is silence, not agreement. If the ESC repurposed those bytes under `0x14`,
the DLCM would read them as wheel speeds anyway and never notice. **Do not cite
this section as firmware confirmation of the same-layout claim**; that claim
still rests on log data alone.

There is a weak argument in the other direction, worth only what it is: a
safety-relevant consumer reading the field unconditionally suggests the ESC is
not expected to repurpose it, since doing so would silently corrupt a
safety-monitored input. That is an argument from design intent, not evidence.

### Consequence: the DLCM ingests the startup frames as real wheel speeds

With no gate, during the ~3.9 s ESC startup (`0x1E` then `0x1C`, payload
`1E 44 C0 00 C0 00 C0 00` — all channels at the zero code) the DLCM reads both
front wheel speeds as exactly zero. Zero is not the invalid sentinel, so nothing
rejects it.

### The invalid sentinel is 0x3FFF, which independently confirms the 14-bit width

`FUN_8006EF12` rejects either front channel reading **`0x3FFF`** and raises DTC
event `0x7A`. `0x3FFF` is the 14-bit all-ones and is only meaningful if the field
is 14 bits — a 16-bit field would sentinel at `0xFFFF`. This is a second,
independent confirmation of the narrowing applied to the DBC on 2026-09-24, which
until now rested only on bits 7-6 being constant `0b11`.

It also reframes a parts-car observation: `WheelSpeed_RR` stuck at wire `0xFFFF`
is the ESC's own invalid code (`0x3FFF` in 14-bit terms), not an arbitrary
stuck-at value.

### Bit 2 partitions the sub-frames, measured

| SubFrameID | B0 bit 2 | wheel-speed fields |
|---|---|---|
| `0x1E`, `0x1C` | 1 | all zero |
| `0x00`, `0x20` | 0 | real data |

Verified on `frombonnydoon` and `codadriveslowturnonwithdefroster2`.
*Hypothesis, not established:* B0 is a status **bitfield** rather than an enum —
`0x1E` = bits 4,3,2,1, then `0x1C` = bits 4,3,2, then either `0x00` or `0x14`.
`0x0A`/`0x0B` fit the pattern trivially since they turn out not to be ESC frames
at all.

### Reproduction

`artifacts/x200_subframeid_rxpath.py` for the log side. Firmware side:
`ghidra/scripts/DlcmFuncContext.java` on `800805EE,800805FC,800805C2,800805D8`
for the getters, then on their callers.
