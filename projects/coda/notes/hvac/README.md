# Coda HVAC module notes

Notes on the HVAC control module (B CAN). Created 2026-10-25 to hold the first HVAC
flash captures; firmware work started 2026-10-26.

| Path | Contents |
|---|---|
| `coda-hvac-decompile-notes.md` | Main notes file: goal, the extraction result, the flash session sequence, and decompile findings, open items (section 10) and the per-step work record (section 11). |
| `coda_hvac_prog.bin` | Program segments 1-8 packed at S12X global addresses, `0x780000`-`0x7FFFFF`, unflashed bytes `0xFF`. The image the Ghidra project `coda_hvac` and `hvacsim` load. |
| `coda_hvac_map.json` | Per-segment address as sent, global range, and the unflashed ranges. |
| `artifacts/hvac_symbols.csv` | The symbol map: name, global address, type and span, read by `hvacsim/symbols.py`. The extraction and packing scripts that built the image, and their outputs, are internal-only. |

This folder's `artifacts/` holds internal analysis scripts and their outputs
and is not published, apart from `hvac_symbols.csv`. Where the notes below
cite `artifacts/<script>.py`, they are naming the script a result came from,
for provenance; the script itself is internal. The same applies to the raw
flash captures and the per-segment downloads.

Ghidra project: `coda_hvac`, rebuilt from this folder by `ghidra/hvac-build.sh` (see
`ghidra/README.md`, HVAC section). Executable model: `projects/coda/tools/hvacsim/`.
