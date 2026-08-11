# Cell Index Mapping — 0x381 VminId/VmaxId to C CAN Cell Array

**Status:** Confirmed (2026-07-21); C CAN DBC renumbered to match (2026-07-22)
**Buses:** B CAN (0x381) + C CAN (0x000-0x019)
**Script:** `notes/artifacts/cell_index_mapping.py`

> **⚠ Cell numbering updated 2026-07-22.** The C CAN DBC (`CODA-C-CAN-cells.dbc`) is now
> **1-based** (`Cell1…Cell104`), matching the BMS's own `VmaxId`/`VminId` directly
> (VmaxId 82 = Cell82) — this file's whole finding. It was previously **0-based**
> (`Cell0…Cell103`). **The Result below is stated in current 1-based terms; the Evidence and
> counterfactual sections still use the 0-based names in effect when the mapping was
> discovered, and are explicitly marked.** Any older artifact, CSV, plot, or export is 0-based
> — add 1 to reconcile (old `Cell94` = current `Cell95`). `MinTempId`/`MaxTempId` are a
> separate index, unaffected.

## Result

`0x381` **VmaxId** (B6) and **VminId** (B7) are the **C CAN cell number, directly** —
both use the BMS's 1-based numbering (1..104):

```
VmaxId N  ==  CellN        (CODA-C-CAN-cells.dbc, 1-based since 2026-07-22)
VmaxId 82 ==  Cell82
```

Where `CellN` is the signal naming in `CODA-C-CAN-cells.dbc` (26 frames
0x000-0x019, 4x 16-bit Motorola cells per frame, 1 mV/bit).

**History:** the mapping was *discovered* while the C CAN DBC was 0-based
(`Cell0..Cell103`), where the relation was `reported_id = old_Cell_index + 1`. On
2026-07-22 the DBC was renumbered to 1-based so the +1 disappears and the two
numberings coincide. This also supersedes the earlier statement that the ids used
an opaque "BMS-internal cell numbering" unrelated to C CAN position — the
BMS numbering *is* the C CAN transmit order (1-based).

## Source Data

Three independent sessions, all carrying C CAN alongside B and D. C CAN is only
occasionally instrumented (it needs a third dongle) — most Coda captures have B
and D only — so these are the logs that can answer the question at all.

| Session | Log(s) | Paired samples | Strict at +1 |
|---------|--------|----------------|--------------|
| 2026-07-21 Android (3-dongle) | `CANLogs/CodaLogs/coda_20260721_192435_T0..T2`, `_201109_T0/T1`, `_202031_T0` | 660 | 82-87% |
| 2026-02 Bonnydoon drive (33 min) | `projects/coda/logs/frombonnydoon.log` | 1,972 | 80-84% |
| 2026-07-22 charge to 100% | `CANLogs/CodaLogs/coda_20260722_173203_T0..T21` | 979 | **100%** |

The 2026-07-22 charge session is the cleanest: low, steady load means cells barely
reorder between the B and C sweeps, so the strict test hits **100.0% at +1** on both
VmaxId (591 samples) and VminId (706). It also charged from 75.7% to 100% SoC, past
the OV cutoff, which pinned the failed-balance/over-voltage cell at **Cell82**
(VmaxId 82, peak 3778 mV, ~400 mV above any other cell) — see `charging-analysis.md`.

Bus identification is by content (0x000-0x019 cell frames = C CAN; 0x381/0x382/
0x383/0x390/0x439 = B CAN; 0x308/0x312/0x325/0x330/0x55C = D CAN), not by bus
number — the two sessions assign different bus numbers to the same physical buses
(C CAN is bus 1 in both, but 0x381 is on bus 2 in the Android session and bus 3
in Bonnydoon).

Totals: 430k+ C CAN cell frames, 8,300+ 0x381 frames, 3,600+ time-paired samples
(C CAN array complete and no frame staler than 2 s at the 0x381 sample instant).

## Evidence

> **Numbering note:** the tables in this section use the **old 0-based** C CAN names
> (`Cell0..Cell103`) — the numbering in effect when the mapping was found. That is *why* the
> offset shows as **+1**. Under the current 1-based DBC each `CellK` below is `Cell(K+1)`, and
> the "+1 offset" is an exact identity. The tables are left in 0-based form as the discovery
> record; do not renumber them, or the +1 evidence stops making sense.

**1. Value range.** VminId and VmaxId together span 1-104 across the sessions.
Never 0, never 105-254, for a pack of exactly 104 cells — consistent with a
1-based index and inconsistent with a 0-based one. (`255` does occur; see the
sentinel note below.)

**2. Same-session extreme-cell distributions.** The strongest evidence, because it
is an aggregate comparison and therefore immune to B/C sampling skew. Tally which
cell the C CAN array itself makes the extreme, and independently tally what 0x381
reports, over the same session. Bonnydoon, 1,972 samples:

| 0x381 VmaxId | share | C CAN argmax | share |
|---|---|---|---|
| 84 | 31.8% | Cell83 | 30.4% |
| 82 | 13.7% | Cell81 | 14.2% |
| 25 | 2.8% | Cell24 | 3.6% |
| 24 | 2.8% | Cell23 | 3.2% |
| 85 | 2.6% | Cell84 | 2.6% |

| 0x381 VminId | share | C CAN argmin | share |
|---|---|---|---|
| 95 | 66.8% | Cell94 | 66.7% |
| 96 | 5.6% | Cell95 | 4.5% |
| 100 | 1.9% | Cell99 | 2.1% |
| 77 | 1.3% | Cell76 | 1.5% |

Rank-for-rank alignment at exactly +1, with shares matching to within ~1.5 points.

**3. Per-sample offset histogram.** For every C CAN index whose voltage equals the
reported extreme, tally `reported_id - ccan_index`. Offset +1 dominates in both
sessions (Android: 188 vs next-best 6 for each of VmaxId and VminId).

**4. Strict per-sample test.** Restricted to samples where the C CAN array's own
extreme exactly equals the reported mV, is held by a *single* cell, and leads the
runner-up cell by >= 3 mV:

| Session | | strict n | at offset +1 | distinct ids | id range |
|---|---|---|---|---|---|
| Android | VmaxId | 135 | 82.2% | 11 | 6-104 |
| Android | VminId | 146 | 87.0% | 26 | 1-101 |
| Bonnydoon | VmaxId | 225 | 79.6% | 44 | 6-104 |
| Bonnydoon | VminId | 376 | 84.3% | 33 | 1-104 |
| Charge (07-22) | VmaxId | 591 | **100.0%** | 2 | 82-95 |
| Charge (07-22) | VminId | 706 | **100.0%** | 1 | 96 |

No competing offset exceeds 4% in the drive sessions; the charge session has none.
(The charge session's narrow id range — VmaxId only 82/95, VminId only 96 — reflects
one failed-balance cell dominating a low-imbalance steady charge, not a weakness of
the test.)

### Sentinel value 255

Both `VmaxId` and `VminId` take the value **255** in `frombonnydoon.log`. With a
104-cell pack this cannot be a cell index; it is an invalid/no-data sentinel.
The analysis filters drop these samples implicitly (no cell matches). Do not read
255 as "cell 254".

### Why the residual ~15% is not a counterexample

The two buses are not sampled simultaneously. C CAN needs ~800 ms to sweep all
26 frames; 0x381 arrives at ~1.1 Hz. These were driving logs, so load swings
reorder near-tied cells between the 0x381 sample instant and the C CAN sweep.

The signature confirms skew rather than a permutation: the non-+1 pairs collapse
onto a handful of C CAN indices (81, 83, 94, 102 for max; 76, 80, 95 for min),
which are the habitually-extreme cells. A genuine permutation would scatter the
misses across the whole array instead of concentrating them on the cells that
are *already* near the extremes.

## Why this was not found earlier (counterfactual)

`bonnydoon-limp-analysis.md` previously parked this question, concluding the indices "may be
due to different indexing conventions." That failure traces to the pre-2026-07-15 DBC byte
order, recovered from the published mirror (commit `460b455`, 2026-04-13):

```
OLD: B0-1=MinCellVoltage  B2-3=MaxCellVoltage  B4-5=AvgCellVoltage  B6=VminId  B7=VmaxId
NEW: B0-1=AvgCellVoltage  B2-3=MaxCellVoltage  B4-5=MinCellVoltage  B6=VmaxId  B7=VminId
```

Re-running the strict test under the old attribution (phase 4 of the script):

| Attribution | Android n / at +1 | Bonnydoon n / at +1 |
|---|---|---|
| Corrected max — value B2-3, id B6 | 135 / 111 (82.2%) | 225 / 179 (79.6%) |
| Corrected min — value B4-5, id B7 | 146 / 127 (87.0%) | 376 / 317 (84.3%) |
| Old max — value B2-3, id B7 | 135 / 0 (0.0%) | 225 / 1 (0.4%) |
| Old min — value B0-1, id B6 | 0 / 0 | 0 / 0 |

Two distinct faults, asymmetric between the ends:

- **Min side: no signal existed.** Old `MinCellVoltage` read B0-B1, which is actually the
  pack average. The average essentially never equals a single cell uniquely and with margin,
  so zero samples survived the filter in *either* session — there was nothing to correlate
  against.
- **Min side, second fault:** the id was also read from the wrong byte (B6 = true VmaxId).
- **Max side: right value, wrong id.** B2-B3 was genuinely the max under both readings, but
  the index came from B7 = the true VminId. A correct max voltage paired with the *minimum*
  cell's index yields noise (best offset 21%), which reads convincingly as "a different
  indexing convention."

**Scope limit.** This applies only to values decoded from raw bytes via the DBC. Figures read
off **CODACAN GUI screenshots** — e.g. the `VminId=96 / VmaxId=76` in `charging-analysis.md`
— come from the LabVIEW cluster, which was correct all along, and are *not* affected by the
DBC error.

**A second, independent error: cross-session comparison.** The byte order alone does not
explain the parked question. `frombonnydoon.log` carries C CAN *and* 0x381, and its own
0x381 reports **VminId 95 / VmaxId 84** — which are exactly the two cells that note
identified (in old 0-based names, `Cell94` and `Cell83`; in current 1-based, `Cell95` and
`Cell84`). The mapping was verifiable inside that single log. The note instead compared those
cells against a *different* (charging) session's values of 96/76 and read the gap as an
encoding difference. Whenever both buses are present, compare within one session.

## Independent confirmation of the 2026-07-15 byte-order correction

The mapping only resolves under the corrected attribution **B6 = VmaxId,
B7 = VminId**. In this data B6 tracks the C CAN array's argmax and B7 tracks its
argmin. Under the previous swapped reading, B6 would be compared against the
minimum cell and the +1 offset would disappear into noise. The C CAN cell data
therefore independently ratifies the LabVIEW-derived byte order for 0x381.

## Method

`notes/artifacts/cell_index_mapping.py` — phase architecture:

1. Stream both buses, hold a rolling 26-frame C CAN snapshot, emit a paired
   sample on each 0x381 frame when the snapshot is complete and fresh.
2. Sanity-check that the array's own min/max equals the reported min/max, then
   tally the candidate index offsets.
3. Strict pass with the uniqueness and margin filters described above.

```
py -3.12 projects/coda/notes/artifacts/cell_index_mapping.py <log> [<log> ...]
```
