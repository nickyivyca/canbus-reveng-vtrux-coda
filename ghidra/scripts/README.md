# ghidra/scripts

Ghidra headless analysis scripts for the Coda DLCM (`dlcm_analysis` project) and
gateway work. Pass this folder to `analyzeHeadless -scriptPath`; nothing needs to
be copied into the Ghidra install.

Per-script purposes, run flags, and the standard headless command are in
[`../README.md`](../README.md#3-headless-analysis-scripts).

> **⚠ 2026-09-19.** The DLCM is an **Infineon TriCore**, not an SH-4. Scripts written
> before this date targeted `SuperH4:BE:32` and the patched SLEIGH; their output is void.
> `DlcmSecurityAccess.java` and `DlcmA0RefScan.java` are the TriCore-era replacements.
> Per-script status is in [`../README.md`](../README.md#3-headless-analysis-scripts).

> **Second caveat on the A0 scanner (2026-09-23).** `DlcmA0RefScan.java` matches the literal offset text of an instruction, so an address built in more than one step is invisible to it. `FUN_8008047A` reaches `0xD0007FB2` as `lea a0,-0x1050` then `lea +0x2`, so a scan for `104e` returns nothing and looks like proof of absence. Scan for plausible base offsets too, not just the effective address.

| File | Kind |
|---|---|
| `DlcmSpanDecompile.java` | **TriCore.** Decompiles one function over a given ret-to-ret span. It clears no-return on the redundancy trap `0x80082EAA` (which otherwise splits functions at every trap call), removes every function whose entry lies inside the span, and creates one function over the whole span. Args `<outpath> <start> <end> [<trap,...>]`. **It modifies the database, so run it only on a throwaway COPY of the project, with `-readOnly`** (copy `dlcm_tricore.gpr`/`.rep` to a scratch dir first). Added 2026-10-08 |
| `DlcmSecurityAccess.java` | **TriCore.** General-purpose decompile runner: seeds the UDS handlers, deep-decompiles given addresses plus callees, re-reads the dispatch table. Args `<outpath> [hex,addrs]` |
| `DlcmA0RefScan.java` | **TriCore.** Finds `A0`/`A1` small-data-relative references by offset substring. Args `<outpath> <substrings>` |
| `DlcmAddrXref.java` | **TriCore.** Lists every reference to given addresses with the containing function. Args `<outpath> <hex,addrs>`. **Caveat:** on this image the reference manager returns *nothing* even for addresses the decompiler visibly uses (code-built `movh.a`/`lea` pairs are not resolved into references), so an empty result is not evidence of absence — cross-check with `projects/coda/notes/dlcm/artifacts/desc_block_selector.py` |
| `DlcmCallCensus.java` | **TriCore.** Ranks every function by distinct caller count, then for chosen targets dumps every call site with the constants loaded into `d4`/`d5` beforehand. Args `<outfile> [hex,addrs] [topN]`. Written 2026-09-23 to find the DEM event reporter (`FUN_8007F6C8`) on the reasoning that it must be heavily called and must take a small constant event id at nearly every site -- it found 114 distinct event ids across 118 call sites. Note `FUN_80082EAA` tops the census with 199 callers and is **not** a reporter but the safety trap. See `projects/coda/notes/dlcm/dlcm-dtcs-investigation.md` |
| `DlcmApplySymbols.java` | **TriCore.** Applies the repo-side symbol map `projects/coda/notes/dlcm/artifacts/dlcm_symbols.csv` to the database: function names plus a plate comment per row carrying the true ret-to-ret span, the confidence and the note section that established it. Args `<csvpath> [<outpath>]`. **The CSV is the source of truth and the database is derived** -- Ghidra projects must live on a local path, so anything recorded only in the database is stranded when the machine changes (that is exactly how `dlcm-dtcs-investigation.md` S2b came to exist). Never hand-edit a name in the GUI and expect it to survive; add the row to the CSV and re-run. **Re-run this after any rebuild of the project, and extend the CSV as new functions are identified** |
| `DlcmSymbolCensus.java` | **TriCore.** Counts how much knowledge the database actually holds: functions with a real name vs. still `FUN_<addr>`, user-defined symbols, and commented addresses. Args `[<outpath>]`. Written 2026-10-07 to answer that question with a measurement; the first run returned **0 named of 2960 functions, 0 labels, 0 comments** after two months of work, which is why `DlcmApplySymbols.java` exists. Use it as the regression check that the map is still applied |
| `DlcmFuncContext.java` | **TriCore.** For given addresses: the containing function, its callers two levels up, and its decompilation. Args `<outpath> <hex,addrs> [decompile 1\|0]`. Useful for addresses that are not function entry points, which `DlcmSecurityAccess.java` requires |
| `SleighStubProbe.java` | Superseded; kept as a record of the wrong-ISA investigation |
| `Dlcm*.java` (pre-2026-09-19), `dlcm_analysis_export.java` | SH-4-era headless analysis scripts, all run as `-noanalysis -postScript`. **Void** — see the note above |
| `run_can212.bat` | Archived original cmd wrapper; contains absolute machine paths, kept as a reference example only |

Ghidra scripts belonging to other investigations live next to those
investigations: `projects/vtrux/notes/artifacts/*.java` (EPRI logger),
`projects/leaf/DecompileLeafParsers.java`, `projects/volt/DecompileVoltParsers.java`.
