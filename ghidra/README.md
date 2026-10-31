# Ghidra Setup — Portable Bundle

> ## ⚠ 2026-09-19 — the SLEIGH half of this bundle is for the wrong architecture
>
> **The Coda DLCM is an Infineon TriCore (little-endian), not a Renesas SH-4 big-endian.**
> The modified `SuperH4.sinc` and its 529 "Continental variant opcode" NOP stubs were
> built to force an SH-4 decoder past bytes that are not SH-4 instructions at all. They
> decode nothing correctly and they silently destroy real code.
>
> - **Do not install the modified SLEIGH** (`sleigh/`, and the SLEIGH half of
>   `restore-ghidra.sh` / `.ps1`) for DLCM work. Use Ghidra's stock
>   `tricore:LE:32:default` and no processor patch.
> - **Do not use the archived `dlcm_analysis` workspace.** Its disassembly and its ~353
>   functions were produced under the wrong ISA.
> - `coda_gateway` (ARM:LE:32) is a separate binary and is **unaffected**.
>
> Evidence and the full post-mortem, including why the SH-4 conclusion looked
> well-supported for months, are in
> `projects/coda/notes/dlcm/coda-dlcm-decompile-notes.md` → Architecture.
>
> The bundle is kept rather than deleted because the restore mechanism, the machine-path
> tables and the headless script inventory are all still correct and still used. It is
> only the processor definition and the SH-4 workspace that are void.

> ### Rebuilding the DLCM project? Re-apply the symbol map.
>
> The TriCore database carries **54 named functions and their plate comments**, and
> they are **not** stored in the database as far as this repo is concerned — they are
> generated from `projects/coda/notes/dlcm/artifacts/dlcm_symbols.csv` by
> `scripts/DlcmApplySymbols.java`. A rebuilt or restored project comes back with
> every function called `FUN_<addr>` again. Re-run the script, then confirm with
> `scripts/DlcmSymbolCensus.java` (it reports how many functions carry a real
> name; 0 means the map is not applied).
>
> **Keep the CSV growing as decompilation work proceeds** — the rule, and the
> measured reason it exists, are in
> `projects/coda/notes/dlcm/coda-dlcm-decompile-notes.md` → *The symbol map*.

Everything needed to reproduce this project's Ghidra environment on another
computer. Nothing outside this repo is required except a stock Ghidra download
and a JDK.

The problem this folder solves: the working Ghidra setup was spread across three
machine-local locations that do not sync —

| Machine-local location | What lived there |
|---|---|
| `<GHIDRA_HOME>\Ghidra\Processors\SuperH4\data\languages\SuperH4.sinc` | Modified SLEIGH with 529 Continental variant-opcode NOP stubs |
| `%LOCALAPPDATA%\ghidra-projects\*.gpr` / `*.rep` | The `dlcm_analysis` and `coda_gateway` Ghidra projects |
| `%LOCALAPPDATA%\ghidra-projects\*.java` | All the headless analysis scripts |

All three are now archived here.

---

## Quick start on a new machine

1. Install **Ghidra 12.0.4 PUBLIC** and a **JDK 21+** (this project used Temurin
   JDK 25.0.2.10). Ghidra does not need to be on PATH.
2. Add the new machine to the `$GhidraMachines` table in
   [`machine-paths.ps1`](machine-paths.ps1) (hostname → Ghidra home, JDK home,
   workspace dir). Alternatively set `GHIDRA_HOME` and `JAVA_HOME` and skip this
   step — the script falls back to those with a warning.
3. Run the restore:

   ```powershell
   powershell -ExecutionPolicy Bypass -File ghidra\restore-ghidra.ps1
   ```

   This installs the modified SLEIGH (backing up the stock file), removes the
   stale compiled `SuperH4_be.sla` so Ghidra rebuilds it, and unpacks the
   archived workspaces into the machine's local workspace directory.
4. Also record the new machine in `tools-reference.md` (Ghidra table) — that
   file is the general external-tool reference; this folder is the Ghidra detail.

`restore-ghidra.ps1` is idempotent: re-running it skips an already-patched
SLEIGH and already-restored workspaces. Pass `-Force` to overwrite,
`-SkipSleigh` / `-SkipWorkspaces` to do only one half.

### Linux / macOS

Same three steps, same idempotency, via the POSIX twins:

```bash
bash ghidra/restore-ghidra.sh            # --force / --skip-sleigh / --skip-workspaces
```

Machine paths come from `ghidra/machine-paths.sh` (a `case "$(hostname)"` block).
If a machine has no entry, it uses `$GHIDRA_HOME`, and failing that autodetects
`~/ghidra_*_PUBLIC`, `/opt/ghidra*`, `/usr/local/ghidra*`. Workspaces default to
`~/ghidra-projects` — the "keep projects off SeaDrive" constraint is a Windows
concern; on Linux put them wherever is convenient and set `GHIDRA_WORKSPACE_DIR`
if it should differ.

Nothing in the bundle is Windows-specific: the SLEIGH files are LF-only ASCII,
the `.java` scripts and project archives are platform-neutral, and Ghidra ships
the POSIX `support/analyzeHeadless` alongside the `.bat` in the same download.
Unpacking needs `unzip` or `python3` (the script uses whichever is present) and
`md5sum` from coreutils.

Verified 2026-08-02 by running the full chain — `restore-ghidra.sh`, then the
POSIX `analyzeHeadless` against the restored `dlcm_analysis` workspace with
`-scriptPath ghidra/scripts` — which reported 353 functions, resolved
`reset_entry`, and decompiled successfully. That exercised the non-Windows code
path but on this Windows box under Git Bash; the one thing it does **not** prove
is that a Ghidra project database opens on an actual Linux JVM. The format is
platform-neutral Java, so this is expected to work, but it is untested on
`the Linux box` itself. `run_can212.bat` is the only Windows-only file in the
bundle, and it is reference-only.

**Now confirmed end-to-end on `the Linux box` (2026-08-02).** Ghidra 12.0.4 and
Temurin JDK 25.0.4+7 were unpacked into `$HOME` (no root, no `apt` — the distro
ships only Java 8, which Ghidra 12 rejects). `restore-ghidra.sh` ran clean, and
`DlcmTest.java` against the restored `dlcm_analysis` reported the same numbers as
the Windows run: **353 functions, `reset_entry` resolved, decompile success,
exit 0**, with SLEIGH recompiling the patched spec (532 NOP constructors). The
project-database format is confirmed portable across platforms. Per-machine paths
are in `machine-paths.sh` and `tools-reference.md`.

### Project ownership across machines

Ghidra stamps the creating account into `<project>.rep/project.prp` and refuses
to open a project owned by anyone else:

```
ERROR Abort due to Headless analyzer error:
      ghidra.util.NotOwnerException: Project is owned by <user>
```

Every archived workspace here carries `<user>`, so this fires on any other
machine or username. `restore-ghidra.sh` now rewrites the `OWNER` field to
`getpass.getuser()` after unpacking (and fixes up any project already sitting in
the workspace dir), so a fresh restore just works. The `.ps1` twin does **not**
do this yet — it has not needed to, since the archives were made under that same
Windows account.

The in-repo `EPRILogger` project has the same stamp. It is not touched by the
restore script, so on a non-`<user>` machine copy it to the local workspace
dir and rewrite the owner there rather than editing the synced copy — editing it
in place would flip the owner for the Windows box and churn 184 MB through
SeaDrive:

```bash
cp -r projects/vtrux/notes/artifacts/ghidra-project/EPRILogger.gpr \
      projects/vtrux/notes/artifacts/ghidra-project/EPRILogger.rep ~/ghidra-projects/
sed -i 's/VALUE="<user>"/VALUE="'"$USER"'"/' ~/ghidra-projects/EPRILogger.rep/project.prp
```

The four `.ps1` runners under `projects/` (leaf, volt, vtrux) have no `.sh`
equivalents yet — they drive the in-repo `EPRILogger` project. Port them the same
way if that work moves to Linux.

---

## 1. Modified SuperH4 SLEIGH

**This section describes a mistake. Read it as history, not instruction.** It was written
believing the Coda DLCM (Continental EMS9180) firmware to be Renesas SH-4 big-endian and
to be "interspersed with opcodes that are not valid SH-4". It is in fact **Infineon
TriCore, little-endian** throughout, so the great majority of the image is not valid SH-4
and the stubs below are suppressing ordinary TriCore instructions. The original text
follows unchanged.

The Coda DLCM (Continental EMS9180) firmware was believed to be Renesas SH-4 big-endian, but
interspersed with opcodes that are not valid SH-4. Stock Ghidra stops
disassembly at each one. The workaround already in use on this project is to add
NOP constructors so the decoder walks past them; the notes record this as
"variant opcodes treated as no-ops", with the known consequence that the
semantics of those instructions are invisible to the decompiler (see
`projects/coda/notes/dlcm/coda-dlcm-decompile-notes.md`).

| Item | Value |
|---|---|
| Stock file patched | `Ghidra/Processors/SuperH4/data/languages/SuperH4.sinc` |
| Ghidra version patched against | 12.0.4 PUBLIC (build 20260303) |
| Stock line count | 3133 |
| Patched line count | 3685 |
| Insertion | 552 lines, containing **529** `:nop_*` constructors |
| Insertion point | immediately after the stock `:nop … is OP_3=0x9` constructor |
| Patched file MD5 | `212c67b7acb5d60df14002e453248971` |
| Stub block MD5 | `8d07fa34a9a2435be1c2e00ce997aad8` |

### Files

| File | Purpose |
|---|---|
| `sleigh/SuperH4.sinc` | Complete patched file. This is what `restore-ghidra.ps1` copies into the Ghidra install. |
| `sleigh/continental-stubs.sinc` | Just the inserted block — the actual delta against stock. |
| `sleigh/apply_continental_stubs.py` | Re-applies the block onto a *different* stock `SuperH4.sinc`. |

### Stub groups inside the block

The block carries its own inline comments recording which scan added each group:

- Hand-identified markers (`0x00F8` CAN TX stub marker, `0xFFFF` function
  boundary marker) and early filter-loop opcodes.
- Bulk scan of the `C000`–`DA80` region.
- Delay-slot overrides for `0x8FFF` / `0x8FF1` / `0xA021` / `0xA03F`
  (self-referencing branches that otherwise trigger nested-delay-slot errors).
- MCM handler region `0x8008C000`–`0x8008D800` stubs (2026-05-01).
- `A000-B000` / `B300-BA00` gap-scan stubs (2026-05-01).
- FP `op3=F` (`FMOV XD` variants) missing from Ghidra's SH-4 spec (2026-05-01).
- `op0=8` invalid sub-opcode stubs (2026-05-02).

Lines beginning `# 0x…= … (valid SH-4) -- skip` document opcodes deliberately
*not* stubbed because stock SLEIGH already decodes them.

### On a Ghidra upgrade

Do not copy `sleigh/SuperH4.sinc` over a newer stock file — it would revert
upstream SH-4 fixes. Instead re-apply just the block:

```bash
py -3.12 ghidra/sleigh/apply_continental_stubs.py \
    "<GHIDRA_HOME>/Ghidra/Processors/SuperH4/data/languages/SuperH4.sinc"
```

It writes a `.stock` backup, refuses to double-apply (checks for `:nop_x`), and
errors out if the stock anchor line has moved. Then delete `SuperH4_be.sla` in
that directory and refresh `sleigh/SuperH4.sinc` here from the new result.

Round-trip verified 2026-08-02: stripping the block from the live patched file
and re-applying it with this script reproduces the patched file byte-identically.

---

## 2. Archived Ghidra workspaces

`tools-reference.md` records the standing constraint that Ghidra project
directories are kept on a **local path**, not in the SeaDrive folder. The
archives below therefore restore to `%LOCALAPPDATA%\ghidra-projects\`, not into
the repo. Zipping also keeps SeaDrive from syncing a live Ghidra database.

| Archive | Restores to | Programs inside | Language | Load address |
|---|---|---|---|---|
| `workspaces/dlcm_analysis.zip` (4.6 MB) | `%LOCALAPPDATA%\ghidra-projects\dlcm_analysis.gpr` + `.rep` | `coda_dlcm_prog.bin` | `SuperH4:BE:32:default` | `0x80040000` |
| `workspaces/coda_gateway.zip` (0.3 MB) | `%LOCALAPPDATA%\ghidra-projects\coda_gateway\` | `coda_gateway.bin` | `ARM:LE:32:v8` | `0x00000000` |

Note the layout asymmetry, which the archives preserve: `dlcm_analysis` sits
directly in `ghidra-projects\`, while `coda_gateway` sits in its own subfolder.

The `dlcm_analysis` project contains **one** program, `coda_dlcm_prog.bin`. The
CAL image (`coda_dlcm_cal.bin`) is not imported into it — CAL analysis was done
with Python scratchpads against the raw binary.

### Source binaries (in-repo, for rebuilding from scratch)

If an archive is ever lost or a project needs rebuilding, the firmware images
are in the repo:

| Binary | Path | Size | MD5 |
|---|---|---|---|
| DLCM PROG | `projects/coda/notes/dlcm/coda_dlcm_prog.bin` | 1,834,496 | `4196f8b91eec49c533f3b12ff8d63843` |
| DLCM CAL | `projects/coda/notes/dlcm/coda_dlcm_cal.bin` | 114,688 | `7db9d7c24918c79814843e7eb812f570` |
| Gateway | `projects/coda/notes/gateway/coda_gateway.bin` | 90,112 | `970651bf6cf6255c01197408bfc6e25c` |

Rebuild import (run from the project root, Bash tool, full paths — see the
command-syntax note below):

```bash
"<GHIDRA_HOME>/support/analyzeHeadless.bat" "%LOCALAPPDATA%/ghidra-projects" dlcm_analysis \
  -import "projects/coda/notes/dlcm/coda_dlcm_prog.bin" \
  -processor SuperH4:BE:32:default -loader BinaryLoader \
  -loader-baseAddr 0x80040000 -noanalysis
```

A rebuilt project starts empty of markup — the archived one carries the
accumulated disassembly and function definitions, so prefer restoring the
archive.

---

## 3. Headless analysis scripts

`scripts/` holds every script that lived in `%LOCALAPPDATA%\ghidra-projects\`.
Pass this folder to `-scriptPath`; nothing needs to be copied into the Ghidra
install.

### TriCore-era scripts (2026-09-19 onward) — use these

| Script | Purpose |
|---|---|
| `DlcmSecurityAccess.java` | Import/seed the UDS service handlers and deep-decompile them plus their callees. Args: `<outpath> [comma-separated hex addresses]` — the second arg overrides the built-in target list, so new leads are chased without editing the file. Also re-reads the dispatch table at `0x80041248` from the image and hex-dumps the handlers. This is the general-purpose "decompile these addresses" runner. |
| `DlcmA0RefScan.java` | Scan every disassembled instruction for `A0`/`A1` small-data-relative offsets matching a substring, printing kind (load/STORE/lea/call) and containing function. Args: `<outpath> <comma-separated substrings>`. Written to find who writes the SecurityAccess key constants at `a0-0x4078+index*4`; useful for any TriCore global whose address is only known as an `A0` offset. **This is the only one of the two reference scanners that can see `[a0]`-relative accesses — see the pairing note below the table.** It matches literal offset text, so a multi-step address (`lea a0,-0x1050` then `lea +0x2`) defeats a search for the effective offset; scan for the base too. Note also that a firmware may reach the same byte through more than one base register, so a hit list filtered to `[a0]` is not the complete set of accesses. |
| `DlcmFixOrphanCode.java` | **Run this once on any freshly rebuilt TriCore project, before anything that asks "who calls this?".** Gives a function to every call/jump destination holding code, and to every call *site* sitting in no function (walking back to the previous terminator). Without it, caller lists are silently incomplete — `FUN_8006eb8c` reported zero callers while running every task cycle. Iterates to a fixed point, idempotent. Applied to `dlcm_tricore` 2026-09-25: 1692 -> 2957 functions. **Caveat:** a candidate entry must be preceded by a terminator, because Ghidra's recorded function *body* can be far shorter than the code it executes and an unguarded version created fragments mid-function (two in the accessor band, since removed — it is back to the documented 120 getters). A report-only pass 0 lists suspect entries but over-flags legitimate functions; do not bulk-delete on it. Args: `<outpath> [entries to delete first] ["prune"]`. |
| `DlcmListRange.java` | **Read-only** dump of the instructions Ghidra has ALREADY decoded over a range, marking function entries, flow terminators and gaps. Answers "does the code at X fall through into the next recorded function, or does it return?" without clearing anything -- which `DlcmDisasmRange` does, and which is the wrong risk to take in a band whose boundaries are already suspect. Added 2026-10-05: it showed `FUN_80055AA0`, `FUN_80055C92`, `FUN_80055EC4` and `FUN_80055FD0` are **mid-stream fragments of `FUN_80055A3E`**, not functions, which had made the ECM2 aggregator look like it had no callers. Args: `<outpath> <lo> <hi>`. |
| `DlcmDisasmRange.java` | Clear a range, disassemble from a chosen start, print the stream and report whether it ends exactly on a given boundary. The alignment check is the point: TriCore instructions are 2 or 4 bytes, so a stream started wrong decodes plausible garbage, and landing cleanly on a known function entry is the proof the start was right. Needed before `DlcmFixOrphanCode` where a region was never disassembled at all. Args: `<outpath> <clearLo> <clearHi> <start> [expectEnd]`. |
| `DlcmProbeRefs.java` | For each address: containing function (and whether it is a thunk), flow type with all its predicates, `getFlows()`, and every outgoing reference with its type. The diagnostic that settles "how does Ghidra actually see this instruction" — it is what disproved the tail-call theory. Args: `<outpath> <comma-separated hex addresses>`. |
| `DlcmVarXref.java` | All references to given absolute addresses, split into reads and writes, with containing function and optional decompilation of the writers. Args: `<outpath> <comma-separated hex addresses> [decompile 1\|0]`. **Blind to `[a0]`/`[a1]`-relative accesses, and it reports `reads: 0  writes: 0` rather than failing — see the pairing note below the table.** |
| `DlcmMakeFunc.java` | Disassemble at an address, create a function there, decompile it; falls back to a raw listing if the function cannot be created. For code the rebuild left outside any function. Args: `<outpath> <comma-separated hex addresses>`. **Prefer `DlcmFixOrphanCode.java`** — an ad-hoc `createFunction` here gave Ghidra bad bounds that had to be deleted and redone. |
| `DlcmA1CalRefs.java` | Every calibration scalar the application references directly, via TriCore `A1`. Resolves each `[a1]`-relative load to a CAL address and prints the stored value as u8/u16/i16 alongside every referencing instruction. Args: `<outpath> [cal bin path]`. |
| `DlcmB974Map.java` | Map the **second** table-driven digital-output layer, the one behind `FUN_8007b974`, end to end. That layer is not the `FUN_8007cd6e` channel table: its entries are 0x14 bytes and carry **two** pin ids each (at +4 and +5), so its `id` packs the entry index in the high bits with which-pin in bit 0. The script recovers the cfg pointer handed to the installer `FUN_80089ed4`, decodes the entry table straight out of the image, and censuses every literal-argument caller of the setter and of the `FUN_8007c662` selector wrapper, so "nothing commands this pin" becomes a closed enumeration rather than an empty search. Applied 2026-09-26: two entries, four pins, P2.0 = Reverse Lamp (B2101), P2.2 driven with an unreported diagnostic, P1.4 and P1.5 written once at init and never again. Args: `<outpath> [comma-separated extra installer function names to probe for a cfg literal]`. |
| `DlcmGpioMap.java` | Every digital I/O pin the firmware drives or reads, by finding the callers of the three GPIO helpers and recovering the literal pin id at each call site. Args: `<outpath>`. |
| `DlcmPoolIdScan.java` | Every call site of the four indexed-signal-pool accessors (`FUN_80064574` read, `FUN_80064520` write, `FUN_800645C8` commit, `FUN_8008EA3E` per-element) with the literal signal id loaded into `d4`, chasing `mov d4,dN` aliases back to the literal. **Prints `?` rather than skipping when no literal is found**, so a computed id cannot pass unnoticed as an absent one. Pairs with `projects/coda/notes/dlcm/artifacts/sigB_pool_record.py`, which decodes the pool's static config to turn an id into bank/record/element. Args: `<outpath>`. |
| `DlcmDtcReporters.java` | Every DTC event id this build can raise, by collecting the literal first argument at each call site of the DTC reporter. Args: `<outpath> [reporter function names]`. |
| `DlcmBrakeLamp.java` | Peripheral-space census (which functions touch TriCore port registers), plus references to the brake-switch RAM mirror and the accessor-band getters that reach them. Args: `<outpath>`. |
| `DlcmLatchHunt.java` | Find a hysteresis comparator by its constants: indexes immediate operands by containing function and reports functions holding both thresholds of a pair, across every torque scaling this ECU uses. Args: `<outpath>`. |
| `DlcmA0Base.java` | Print every instruction that writes `A0`/`A1`, with context. Recovers the small-data base registers, without which large parts of the decompilation cannot be turned into addresses. Args: `<outpath>`. |
| `SleighStubProbe.java` | **Superseded.** Probes every Continental NOP-stub opcode against the installed processor spec. Written to test the hypothesis that the stubs were shadowing valid SH-4 instructions — which turned out to be the wrong question, since the firmware is not SH-4 at all. Kept only as a record; nothing needs it. |

> ### The two reference scanners are complementary, and one of them fails silently
>
> `DlcmVarXref.java` and `DlcmA0RefScan.java` answer the same question — "who touches this
> address?" — over **disjoint** sets of instructions, so neither alone is a complete answer:
>
> | Access form | `DlcmVarXref` | `DlcmA0RefScan` |
> |---|---|---|
> | `[a0]`/`[a1]`-relative (TriCore small-data) | blind | sees it |
> | absolute (`movh.a`/`lea` to a full address) | sees it | blind |
>
> Ghidra creates a reference to an absolute address only when the instruction names it. A
> TriCore small-data access names a *register*, so there is no reference to find and
> `DlcmVarXref` reports `reads: 0  writes: 0` — **indistinguishable from a genuine absence
> of writers.** Recorded 2026-10-03 after it returned exactly that for `0xD000834F` and
> `0xD000834D`, two DLCM safety flags whose writers had just been read in the decompiler.
>
> Two habits that make this safe:
>
> - **Score a known-written address alongside the unknown ones.** If the control comes back
>   `writes: 0` too, the scanner is the problem, not the firmware. This is the only check
>   here whose failure looks different from its success.
> - **Before concluding "no writer", re-derive the offsets from the addresses and diff that
>   set against what was actually passed.** The same investigation attributed a missing
>   writer to a scanner blind spot when the offset had simply never been in the argument
>   list.
>
> Also: the same byte can be reachable through more than one base. In the DLCM the safety
> flags are addressed both as `a0-0x8B1` (`a0 = 0xD0009000`) and as `a15-0x78B1`
> (`a15 = 0xD0010000`), and the second form is absolute enough for Ghidra to resolve — so
> the two scanners returned *different, each-incomplete* writer sets for one address.

### HVAC scripts (S12X, `coda_hvac`, 2026-10-26 onward)

The HVAC project is **not archived**: it is rebuilt from the repo in one command, and
everything learned is kept in `projects/coda/notes/hvac/artifacts/hvac_symbols.csv`, which
the rebuild applies. Rebuild:

```bash
bash ghidra/hvac-build.sh --force     # ~4 min on the Linux box
```

It runs `pack_hvac_image.py`, imports `coda_hvac_prog.bin` as `HCS-12X:BE:24:default` at
`0x780000` (BinaryLoader, `-noanalysis`), runs `HvacFlowSeed.java`, then
`DlcmApplySymbols.java` with the HVAC CSV and `DlcmSymbolCensus.java` (both are
program-agnostic). Reports go to `~/ghidra-projects/hvac_export/`. Stock Ghidra, no
processor patch.

| Script | Purpose |
|---|---|
| `HvacFlowSeed.java` | **The build's analysis pass; run on any fresh import.** Iterates to a fixed point: computes JMP/JSR/CALL extended targets itself (stock SLEIGH encodes them as `goto [opr16a]`, so Ghidra never follows them), seeds the vector table at `0x7FEE10`, parses the three compiler switch helpers' inline tables (flow override BRANCH + jumptable override), and scrubs wrong-page references (below), keeping fall-through targets. Reports coverage, errors, switch sites. Does not parse the fourth switch helper `0x7FCAEA` (one site, `0x7F984D`). Args: `<outpath> <flashed ranges lo-hi,...>` (the build script derives them from `coda_hvac_map.json`). |
| `HvacDecompile.java` | General "decompile these addresses" runner: function at or containing each address, its page, its callers, the C. Args: `<outpath> <hex addresses,...> [timeoutSeconds]`. |
| `HvacListFrom.java` | Disassemble with follow-flow from given addresses and print the stream with flows. Use with `-readOnly`. Args: `<outpath> <hex addresses,...> [maxInstructions]`. |
| `HvacMapCheck.java` | The step-1a test of the S12X map (vector targets, CALL page operands). Superseded by `HvacFlowSeed`'s report; kept as the record of that check. |
| `HvacPpageProbe.java` | Diagnostic: the PPAGE value stored in the program context at given addresses. |
| `HvacListingDump.java` | Every decoded instruction as one TSV row (address, containing function, bytes, text, references) for sweeps in Python: register and RAM accesses, immediates, callers. Read-only; run with `-readOnly`. Args: `<outpath>` (the step-2 dump is `~/ghidra-projects/hvac_export/listing.tsv`, regenerable). |

`DlcmListRange.java`, `DlcmVarXref.java` and `DlcmProbeRefs.java` are program-agnostic and
work on `coda_hvac` unchanged.

> **Three HCS-12X pitfalls in stock Ghidra, all silent.**
>
> - **`BRSET` is decoded backwards in the stock SLEIGH** (`HCS_HC12.sinc`, all three
>   forms): `result = ~M & mask; if (result != 0) goto rel`, i.e. "branch if any masked
>   bit is clear". The CPU12 reference says BRSET branches when all masked bits are set
>   (`~M & mask == 0`). `BRCLR` is correct. **Every `BRSET` in a decompile is inverted**,
>   the listing text is right; the HVAC has 246 sites in 56 functions. Found 2026-10-26 at
>   `0x7FAA78` (the decompile set a bit the machine code clears) and at every Stateflow
>   "first pass" init; it had reversed a step-3 conclusion (E0xx/E2xx were written up as
>   read-only over `2E`; they are writable). Read `BRSET` sites from the listing, or run
>   the code in `projects/coda/tools/hvacsim/cpu.py`, which decodes the bytes itself. The
>   SLEIGH is not patched (a patched SLEIGH is how the DLCM work went wrong).
> - **The constant propagator resolves `0x8000`-`0xBFFF` operands with PPAGE = `0xFE`
>   everywhere**, the pspec's `tracked_set` default. It ignores the per-page values stored
>   in the program context (verified with `HvacPpageProbe`: the context holds the right
>   page), because PPAGE is a RAM-space byte, not a register. Every Ghidra-made reference
>   from banked code in another page therefore lands in page FE. On the HVAC it seeded
>   bogus code in 14 places and two decode conflicts. `HvacFlowSeed` moves such references
>   onto the instruction's own page (36 moved) and clears code reached only through them.
>   A target the previous instruction falls through to is kept (fall-through is not a
>   reference; before 2026-10-26 the clear removed `0x7FA371`-`0x7FA6DD`, the tail of the
>   thermal model, and `0x7FB478`; 398 instructions came back).
>   References from fixed-page code (`0x4000`/`0xC000` windows) cannot be fixed this way,
>   because the runtime PPAGE is unknown; the report counts them (2).
> - **Switch sites carry a 2-byte stack error in the decompiler.** The JSR to a switch
>   helper pushes a return address the helper pops; with the BRANCH override the push
>   stays in the p-code, so stack-relative variables after the switch read as
>   `*(puVar + -n)` noise. Readable, but read those functions with that in mind.

### SH-4-era scripts — all void

Every script below was written against `SuperH4:BE:32` and the patched SLEIGH. They run,
but their output describes an SH-4 decode of a TriCore binary and means nothing. Several
encode SH-4 specifics in their logic (`@(0x30,Rx)` write sites, R10/R13 register traces),
so they cannot simply be repointed at the TriCore project — the *questions* are still
good, the implementations are not.

| Script | Purpose |
|---|---|
| `DlcmCleanSetup.java` | Wipe aggressive-sweep artifacts; recursively disassemble from ~80 known entry points |
| `DlcmDisasmDump.java` | Dump disassembly + decompile for Goal 1, Goal 3, and VBR handlers |
| `DlcmMcmHandler.java` | MCM handler region (B000-E000): disassemble from seeds, decompile key fns, probe `@(0x30,Rx)` write sites, dump R10 data path |
| `DlcmCan212.java` | CAN 0x212 message path analysis |
| `DlcmCanTxDump.java` | CAN TX path dump. Takes `<outpath>` as `args[0]`. **Fixed 2026-10-06:** the output path was hardcoded to a Windows absolute path and `args` were ignored, so on `the Linux box` the run logged success and wrote a file literally named `C:\Users\...` into the CWD while the requested path stayed absent. Check any pre-2026-10-06 output of this script actually came from where you think |
| `DlcmGapDecompile.java` | Decompile the unmapped gap regions |
| `DlcmGradientCallChain.java` | Gradient-limiter call-tree walk |
| `DlcmBytecodeProbe.java` | Bytecode/variant-opcode probe |
| `DlcmR13Trace.java` | R13 register dataflow trace |
| `DlcmInitTrace.java` | Module-init band (0x80066xxx-0x80068xxx) seed + decompile dump: traces what populates the 0xD9047B5C torque context struct / [R13+0x34] MDB pointer (output `init_trace.txt`) |
| `dlcm_analysis_export.java` | Export full function list and gap context |
| `DlcmTest.java` | Minimal sanity check (function count + one decompile) |
| `run_can212.bat` | cmd wrapper for the `DlcmCan212` run (contains machine paths — see note) |

All are run as `-noanalysis -postScript`.

> `scripts/run_can212.bat` is an archived copy of the original and still carries
> this machine's absolute paths. Treat it as a reference example; prefer the
> command form below.

### Standard headless command

Use **full paths directly** in the Bash tool — do NOT use `set VAR=…` / `%VAR%`
syntax (that is cmd.exe syntax; in bash `%VAR%` is a job spec and causes
"fg: no job control"). Exit code 1 from Ghidra is normal (Sleigh pcode errors);
exit code 0 is a clean run.

```bash
"<GHIDRA_HOME>/support/analyzeHeadless.bat" "<WORKSPACE_DIR>" dlcm_analysis \
  -process coda_dlcm_prog.bin -noanalysis -postScript DlcmCan212.java \
  -scriptPath "<REPO>/ghidra/scripts" \
  > "<WORKSPACE_DIR>/dlcm_export/DlcmCan212_log.txt" 2>&1
```

Always redirect stdout+stderr to a `_log.txt` in `dlcm_export\` — SLEIGH errors
and script failures appear only there, not in Ghidra's `application.log`.

### Output and log locations

| What | Path |
|---|---|
| Headless script output | `%LOCALAPPDATA%\ghidra-projects\dlcm_export\` (created by `restore-ghidra.ps1`) |
| Ghidra application log | `%APPDATA%\ghidra\ghidra_<version>_PUBLIC\application.log` |

Output files worth keeping get copied into the relevant `notes/artifacts/`
folder per the project's data-artifact rules. The bulk `dlcm_export\` dumps
(~2 MB of raw disassembly and decompile text) are intentionally **not** archived
here — they are regenerable by re-running the scripts against the restored
workspace.

---

## 4. Ghidra work that already lives in the repo

Not everything was external. The Vtrux EPRI logger decompile keeps its project
inside the synced folder and needs no restore step:

| Item | Path |
|---|---|
| `EPRILogger` Ghidra project (184 MB) | `projects/vtrux/notes/artifacts/ghidra-project/` |
| Programs inside | `CANbusLogger2_ARM`, `CANbusLogger2_ARM64` |
| Source binaries | `projects/vtrux/notes/artifacts/CANbusLogger2_ARM`, `…_ARM64` |
| Scripts | `projects/vtrux/notes/artifacts/DecompileViaParsers.java`, `DecompileGoPoint.java`, `DiagnoseGhidra.java`, `Epri0598Decode.java`, `Epri0598Caller.java`, `Epri0598Arch.java`, `EpriDumpFn.java` |
| Runner scripts | `projects/vtrux/notes/artifacts/run-ghidra-armv7.ps1`, `run-ghidra-gopoint.ps1` |
| Leaf decompile | `projects/leaf/run-ghidra-leaf.ps1` + `DecompileLeafParsers.java` |
| Volt decompile | `projects/volt/run-ghidra-volt.ps1` + `DecompileVoltParsers.java` |

The leaf and volt runners reuse the same `EPRILogger` project via `-process`.

All four `.ps1` runners previously hardcoded this machine's Ghidra path, JDK
path, and an outdated SeaDrive library path (`My Libraries\Projects\reverse-it`,
which no longer exists — the library is now `My Libraries\NotGit\reverse-it`), so
they were broken as written. They now dot-source `ghidra/machine-paths.ps1` and
derive the repo root from `$PSScriptRoot`, so they work from a fresh clone on any
machine listed in the table.

`projects/vtrux/notes/artifacts/run-ghidra-armv7.bat` is the original one-time
`-import` of `CANbusLogger2_ARM` and still carries the same stale absolute paths.
It was left as-is — the import it performs is already baked into the committed
`ghidra-project/`, so it is history rather than a working runner.

---

## File layout

```
ghidra/
├── README.md                       this file
├── machine-paths.ps1               hostname -> Ghidra/JDK/workspace paths; dot-sourced by runners
├── machine-paths.sh                same, for Linux/macOS
├── restore-ghidra.ps1              one-shot restore on a new machine (Windows)
├── restore-ghidra.sh               one-shot restore on a new machine (Linux/macOS)
├── hvac-build.sh                   rebuild the coda_hvac project from the repo (HVAC, S12X)
├── scripts/                        headless analysis scripts (-scriptPath target)
│   ├── Dlcm*.java, dlcm_analysis_export.java
│   ├── Hvac*.java                  HVAC (S12X) scripts, see the HVAC section
│   └── run_can212.bat              archived original wrapper (machine paths inside)
├── sleigh/
│   ├── SuperH4.sinc                full patched SLEIGH (Ghidra 12.0.4)
│   ├── continental-stubs.sinc      the 552-line insertion block alone
│   └── apply_continental_stubs.py  re-apply the block to a newer stock .sinc
└── workspaces/
    ├── dlcm_analysis.zip           Ghidra project: coda_dlcm_prog.bin
    └── coda_gateway.zip            Ghidra project: coda_gateway.bin
```

## Related documentation

| Topic | Where |
|---|---|
| Per-machine external tool paths (Ghidra install, JDK, Wireshark, dongles) | `tools-reference.md` |
| Per-machine Python executable | `python-executables-reference.md` |
| DLCM decompile findings | `projects/coda/notes/dlcm/coda-dlcm-decompile-notes.md` |
| Gateway decompile findings | `projects/coda/notes/gateway/coda-gateway-decompile-notes.md` |
| HVAC decompile findings | `projects/coda/notes/hvac/coda-hvac-decompile-notes.md` |
| Vtrux EPRI decompile findings | `projects/vtrux/notes/epri-decompile.md` |
