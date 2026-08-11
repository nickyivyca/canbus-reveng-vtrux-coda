# ghidra/scripts

Ghidra headless analysis scripts for the Coda DLCM (`dlcm_analysis` project) and
gateway work. Pass this folder to `analyzeHeadless -scriptPath`; nothing needs to
be copied into the Ghidra install.

Per-script purposes, run flags, and the standard headless command are in
[`../README.md`](../README.md#3-headless-analysis-scripts).

| File | Kind |
|---|---|
| `Dlcm*.java`, `dlcm_analysis_export.java` | Headless analysis scripts, all run as `-noanalysis -postScript` |
| `run_can212.bat` | Archived original cmd wrapper; contains absolute machine paths, kept as a reference example only |

Ghidra scripts belonging to other investigations live next to those
investigations: `projects/vtrux/notes/artifacts/*.java` (EPRI logger),
`projects/leaf/DecompileLeafParsers.java`, `projects/volt/DecompileVoltParsers.java`.
