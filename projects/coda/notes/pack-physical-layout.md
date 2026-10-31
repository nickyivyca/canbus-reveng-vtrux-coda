# Coda Pack Physical Layout — Cell Number to Physical Position

**Status:** Confirmed (2026-09-06) for the module/orientation rule; two clearly-marked assumptions remain
**Vehicle:** Coda, 31 kWh pack (104S LFP)
**Scope:** Where each `CellN` physically sits in the pack. The *logical* mapping
(`0x381 VmaxId/VminId` ↔ `CellN` ↔ C CAN frame/byte) is a separate, already-settled
question — see [`cell-index-mapping.md`](cell-index-mapping.md). Nothing here changes the DBC.
**Scripts:** `notes/artifacts/cell_display_*.py`
**Machine-readable output:** `notes/artifacts/cell_display_corrected_mapping.csv`

## Result

The pack is **18 modules in a 9-wide x 2-deep top-down arrangement**: 4x 5-cell
(columns 1 and 2, both halves) and 14x 6-cell. The series string runs:

```
Cell1 (row6,col1)  --> across the top half, left to right -->  Cell52 (row1,col9)
                              |
                             HVD  (manual service disconnect, between Cell52 and Cell53)
                              |
Cell53 (row12,col9) --> across the bottom half, right to left --> Cell104 (row7,col1)
```

Modules **boustrophedon**: each is traversed end-to-end and the direction alternates,
so every module-to-module join is a short link between adjacent ends.

`Cell_Voltage_Display.exe` instead lays out every module in the same direction
(mid-line to outer edge), a "comb" in which each join would need a busbar running the
full length of a module and back. Relative to the physical pack:

> **Odd-numbered display columns (1, 3, 5, 7, 9) are correct.
> Even-numbered display columns (2, 4, 6, 8) are mirrored top-to-bottom
> within their own module.** Applies to both halves; 44 of 104 cells are misplaced.

Module membership, column, and colour are correct throughout — no cell ever changes
module or column, only its order within the module. To read the original tool
correctly, mirror each even column vertically inside its own colour block.

## Corrected grid (screen position to cell)

`(shows N)` = the cell number the original exe puts at that position.

```
row |    col1              col2      col3              col4      col5              col6      col7              col8      col9
  1 |       .                 .    Cell16  Cell17 (shows 22)    Cell28  Cell29 (shows 34)    Cell40  Cell41 (shows 46)   Cell52
  2 |   Cell5  Cell6 (shows 10)    Cell15  Cell18 (shows 21)    Cell27  Cell30 (shows 33)    Cell39  Cell42 (shows 45)   Cell51
  3 |   Cell4   Cell7 (shows  9)   Cell14  Cell19 (shows 20)    Cell26  Cell31 (shows 32)    Cell38  Cell43 (shows 44)   Cell50
  4 |   Cell3             Cell8    Cell13  Cell20 (shows 19)    Cell25  Cell32 (shows 31)    Cell37  Cell44 (shows 43)   Cell49
  5 |   Cell2   Cell9 (shows  7)   Cell12  Cell21 (shows 18)    Cell24  Cell33 (shows 30)    Cell36  Cell45 (shows 42)   Cell48
  6 |   Cell1  Cell10 (shows  6)   Cell11  Cell22 (shows 17)    Cell23  Cell34 (shows 29)    Cell35  Cell46 (shows 41)   Cell47
  7 | Cell104  Cell95 (shows 99)   Cell94  Cell83 (shows 88)    Cell82  Cell71 (shows 76)    Cell70  Cell59 (shows 64)   Cell58
  8 | Cell103  Cell96 (shows 98)   Cell93  Cell84 (shows 87)    Cell81  Cell72 (shows 75)    Cell69  Cell60 (shows 63)   Cell57
  9 | Cell102            Cell97    Cell92  Cell85 (shows 86)    Cell80  Cell73 (shows 74)    Cell68  Cell61 (shows 62)   Cell56
 10 | Cell101  Cell98 (shows 96)   Cell91  Cell86 (shows 85)    Cell79  Cell74 (shows 73)    Cell67  Cell62 (shows 61)   Cell55
 11 | Cell100  Cell99 (shows 95)   Cell90  Cell87 (shows 84)    Cell78  Cell75 (shows 72)    Cell66  Cell63 (shows 60)   Cell54
 12 |       .                 .    Cell89  Cell88 (shows 83)    Cell77  Cell76 (shows 71)    Cell65  Cell64 (shows 59)   Cell53
```

Rows 1 and 12 are blank in columns 1-2 because those modules are 5-cell.
Colour quadrants: black = Cells 1-28, blue = 29-52, green = 77-104, white = 53-76.

## Evidence

The layout was reconstructed from the owner-annotated busbar drawing (internal-only), an
annotated screenshot supplied by the owner marking the inter-module busbars, the HVD,
the true location of a high cell (red), and where the tool wrongly showed it (yellow).

The 16 busbar strokes were extracted by pixel-clustering
(`notes/artifacts/cell_display_bussing.py`); every one landed on a column boundary to
within 0.05 of a column width. Walking the resulting chain
(`notes/artifacts/cell_display_string_walk.py`) yields exactly 104 positions with two
free ends, and reproduces three independent observations it was not given:

| Check | Reconstruction predicts | Owner's observation |
|---|---|---|
| Repaired module, Cell84 (col4 bottom) | p5 to p2 of 6 | shown "1 in from the edge", found "1 in from the middle" — agrees |
| Yellow: 3.354 V shown at (row11,col8) = Cell60 | Cell60 is at (row8,col8) | red circle at (row8,col8) — agrees |
| Red: 3.32 V shown at (row7,col9) = Cell58 | Cell58 is at (row7,col9) | marked as correctly shown — agrees |

Supporting arguments:

- The exe is **internally perfectly regular** — all 18 module-columns are contiguous,
  strictly-descending runs in both its layouts, zero exceptions
  (`notes/artifacts/cell_display_regularity.py`). The error is one uniform wrong
  assumption, not a coding slip, and the binary holds no per-module information.
- The walk's two free ends are `(row6,col1)` and `(row7,col1)` — the two leftmost cells
  flanking the mid-line, one in the black block and one in the green. This matches the
  owner's independent expectation of where the pack terminals are.
- The HVD landing between Cell52 and Cell53 explains why that one join is a long cable:
  a service disconnect splitting a 104S string into two ~170 V halves is the standard
  arrangement.

## Assumptions (not established)

1. **`Cell1` is the pack-negative terminal.** The busbar drawing fixes the string
   topology but not its polarity. This assumes the usual BMS convention of numbering
   from the most-negative cell, which would put HV- at `(row6,col1)` and HV+ at
   `(row7,col1)`. The owner did not have photographs of the HV output side.
2. **The 36 kWh layout is unverified.** All of the above concerns the 31 kWh pack
   (`Df == 1`). The exe's 36 kWh layout (8 columns x 14 rows, modules of 5/6/7) has
   been extracted but never checked against a physical pack.

## Where the known outlier cells actually are

| Cell | Context | Exe shows | Actually |
|---|---|---|---|
| Cell95 | main car low cell, 3.214 V | row11 col2 (outer end) | **row7 col2** (mid-line end) |
| Cell84 | main car, the repaired module | row11 col4 | **row8 col4** |
| Cell82 | main car max 3.287 V; 3778 mV on the 2026-07-22 charge | row7 col5 | row7 col5 — correct |
| Cell91 | parts car low cell, 3.201 V | row10 col3 | row10 col3 — correct |
| Cell26 | parts car max, 3.247 V | row3 col5 | row3 col5 — correct |

## The source tool

`Cell_Voltage_Display.exe` (internal-only) is **not native x86** — it is a
PyInstaller bundle of a Python 3.7 + Tkinter script driving a Kvaser adapter through
`canlib32.dll`. Extracted and decompiled to
`notes/artifacts/cell_display_extract/Cell_Voltage_Display.py`.

Its CAN decode is correct and identical to our DBC — all 104 assignments verified
programmatically with no exceptions:

```python
if rx_id1.value == MM:                                    # MM = 0..25 decimal
    cellMM_C = (rx_msg1[2*C] * 256 + rx_msg1[2*C+1]) / 1000
```

so `MM_C` maps to `Cell(4*MM + C + 1)` — C CAN IDs `0x000`-`0x019`, 4x 16-bit Motorola
per frame, 1 mV/bit. Only the spatial placement was ever wrong.

On startup it prompts `Enter a 1 for 31Kw display or anything else for 36Kw display`;
answer `1` for a normal 31 kWh car.

## Artifacts

| File | Contents |
|---|---|
| `notes/artifacts/cell_display_corrected_mapping.csv` | 104 rows: cell to CAN frame/bytes to module, size, position from mid-line, true vs exe screen position |
| `notes/artifacts/cell_display_mapping.csv` | The exe's own layout, both 31 kWh and 36 kWh (208 rows) |
| `notes/artifacts/cell_display_re.py` | PyInstaller CArchive extractor |
| `notes/artifacts/cell_display_dis.py` | Py3.7 bytecode disassembly via `xdis` |
| `notes/artifacts/cell_display_layout.py` | Parses grid placements + CAN wiring out of the disassembly |
| `notes/artifacts/cell_display_regularity.py` | Internal-regularity check on the exe's layout |
| `notes/artifacts/cell_display_physical.py` | Per-module statistics from the annotated screenshots |
| `notes/artifacts/cell_display_bussing.py` | Pixel-extraction of the busbar/HVD/red/yellow annotations |
| `notes/artifacts/cell_display_string_walk.py` | Chain reconstruction and comparison against the exe |
| `notes/artifacts/cell_display_extract/` | Extracted `.pyc`, disassembly, decompiled source |
| `../coda-diagnostics/cell_viewer/layout.py` | The rule in code, verified against both CSVs |

## Related

- [`cell-index-mapping.md`](cell-index-mapping.md) — logical mapping, `0x381 VmaxId/VminId` to `CellN`
- [`../coda-diagnostics/cell_viewer/README.md`](../coda-diagnostics/cell_viewer/README.md) — the tool rebuilt on our CAN stack, which renders this mapping
- `../CODA-C-CAN-cells.dbc` — the 26 cell frames (unchanged by this work)
