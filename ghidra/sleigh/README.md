# ghidra/sleigh

The modified Renesas SH-4 processor definition used for the Coda DLCM
(Continental EMS9180) firmware: stock Ghidra's `SuperH4.sinc` plus 529 NOP
constructors for Continental variant opcodes, so disassembly walks past
instructions that are not valid SH-4.

Rationale, stub-group breakdown, hashes, and the Ghidra-upgrade procedure are in
[`../README.md`](../README.md#1-modified-superh4-sleigh).

| File | What it is |
|---|---|
| `SuperH4.sinc` | Complete patched file (against Ghidra 12.0.4). `../restore-ghidra.ps1` copies this into the Ghidra install. |
| `continental-stubs.sinc` | Only the inserted block (552 lines, 529 `:nop_*` constructors) — the actual delta vs stock. |
| `apply_continental_stubs.py` | Re-applies that block onto a different/newer stock `SuperH4.sinc`. Use this instead of copying `SuperH4.sinc` after a Ghidra upgrade. |

Consequence to keep in mind when reading decompiler output: stubbed opcodes are
modelled as no-ops, so whatever they actually do is invisible to the decompiler.
See `projects/coda/notes/dlcm/coda-dlcm-decompile-notes.md`.
