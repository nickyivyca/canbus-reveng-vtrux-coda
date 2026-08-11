# Ghidra Setup — Portable Bundle

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

The Coda DLCM (Continental EMS9180) firmware is Renesas SH-4 big-endian, but is
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

| Script | Purpose |
|---|---|
| `DlcmCleanSetup.java` | Wipe aggressive-sweep artifacts; recursively disassemble from ~80 known entry points |
| `DlcmDisasmDump.java` | Dump disassembly + decompile for Goal 1, Goal 3, and VBR handlers |
| `DlcmMcmHandler.java` | MCM handler region (B000-E000): disassemble from seeds, decompile key fns, probe `@(0x30,Rx)` write sites, dump R10 data path |
| `DlcmCan212.java` | CAN 0x212 message path analysis |
| `DlcmCanTxDump.java` | CAN TX path dump |
| `DlcmGapDecompile.java` | Decompile the unmapped gap regions |
| `DlcmGradientCallChain.java` | Gradient-limiter call-tree walk |
| `DlcmBytecodeProbe.java` | Bytecode/variant-opcode probe |
| `DlcmR13Trace.java` | R13 register dataflow trace |
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
├── scripts/                        headless analysis scripts (-scriptPath target)
│   ├── Dlcm*.java, dlcm_analysis_export.java
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
| Vtrux EPRI decompile findings | `projects/vtrux/notes/epri-decompile.md` |
