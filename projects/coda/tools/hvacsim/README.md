# hvacsim — executable model of the Coda HVAC module firmware

Started 2026-10-26 (HVAC work step 1; decompile notes 4.6). Notes:
`../../notes/hvac/coda-hvac-decompile-notes.md`. **FLASHING IS NOT AUTHORISED.** This
package produces a model, never a flash.

The HVAC counterpart of `../codasim/`, built on the same rules. Patterns are copied from
codasim, its files are never edited (other sessions own them). Modules are added one per
firmware function as functions are decompiled, each with a test against the listing or
a log. Scripts that use it live in `notes/hvac/artifacts/` and add `projects/coda/tools`
to `sys.path`.

## File layout

| Path | What it is |
|---|---|
| `fixedpoint.py` | HCS12/S12X integer semantics: u8/s8/u16/s16/u32/s32 wrap, and the compiler's arithmetic opcodes `emul`, `emuls`, `ediv`, `edivs`, `idiv`, `idivs`, `fdiv` (signed divides truncate toward zero; divide by zero raises) |
| `image.py` | The packed program image (`notes/hvac/coda_hvac_prog.bin` + `coda_hvac_map.json`) read by CPU-local address and page, as the listing reads it; `to_global()` is the S12X local -> global map. Reading unflashed fill raises |
| `symbols.py` | `notes/hvac/artifacts/hvac_symbols.csv` as the lookup table: name <-> global address, type, span. `var()` refuses an untyped row |
| `ram.py` | RAM and registers keyed by global address; stores narrow to the declared type; overlap raises; `assume()`; `unsourced()` lists variables read but never written |
| `startup.py` | The CodeWarrior copy-down run by `StartupCopyDown` (`0x7F8000`): `copy_down_entries()` walks the list at the pointer in `_startupData` (local `0xC013`), `copy_down()` returns `{global address: initial byte}`. The zero-out list is not modelled |
| `seedkey.py` | SecurityAccess `SeedToKey` (`0x7E5853`): seed XOR per-level constant, 48 rounds of a 32-bit LFSR; `LEVEL_01`, `LEVEL_03` constants |
| `cpu.py` | **S12X (CPU12X) instruction emulator** (2026-10-26, plan step 4): runs firmware functions as they are, decoding the bytes itself (never Ghidra's listing or p-code, whose `BRSET` is inverted). `Mem` = flash from the image (read-only), RAM `0x0FE000`-`0x0FFFFF` initialised by the copy-down, registers as a dict (reads logged). `Cpu.call(global)` far-calls to the matching RTC; `jsr_call` for near functions; `hooks` stand in for hardware (e.g. ADC completion). Opcodes outside the HVAC's set raise `Unimplemented`; G-prefixed instructions, RPAGE/EPAGE windows and interrupts are not modelled. About 120k instructions/s. Driven by `notes/hvac/artifacts/hvac_model_run.py` |
| `tests/test_cpu.py` | The emulator runs the firmware's `SeedToKey` (`0x7E5853`) and reproduces both captured seed/key pairs and random seeds at both levels |
| `tests/test_image.py` | Each packed segment's CRC-16/CCITT-FALSE equals the flash tool's TransferExit value; address translation cases; the three reset slots read `0xCBA5`; unflashed reads raise |
| `tests/test_fixedpoint.py` | Hand cases for the multiply/divide semantics |
| `tests/test_startup.py` | The copy-down list: 7 entries from local `0xCD01`, and the first row of the E-DID table at `0x2A2C` |
| `tests/test_seedkey.py` | `SeedToKey` reproduces both `27 03/04` seed/key pairs of the 2026-10-25 flash capture |

Run the tests from the project root: `python3.13 projects/coda/tools/hvacsim/tests/test_image.py`
(and `test_fixedpoint.py`, `test_startup.py`, `test_seedkey.py`, `test_cpu.py`); all also run under pytest.

## Rules (codasim's R1-R7, applied here)

1. **Mirror the code.** One module per firmware function. Addresses come by symbol name, never as literals.
2. **Integer-exact.** Every variable has a declared width and sign.
3. **Each table read names its firmware entry point.**
4. **Every input declares its provenance.**
5. **Timing is explicit.**
6. **Parity before replacement**, then the car decides.
7. **Bus by content.**

## Addresses

Everything is an **S12X global address** (the same space as the Ghidra project
`coda_hvac`): flash pages `0xE0`-`0xFF` at `0x780000`-`0x7FFFFF`, RAM at `0x0FE000`
(CPU-local `0x2000`-`0x3FFF`), registers at their local address. The map rests on
hypothesis H1 (notes section 3) and is what the Ghidra project and the tests use.
