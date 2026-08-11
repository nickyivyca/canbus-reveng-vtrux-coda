# Coda Battery Degradation — Longitudinal Analysis

**Scope:** Pack capacity fade and cell imbalance over time, and attribution between
the two known bad cells. Built from 218 sessions with BMS cell data spanning
**2026-02-17 → 2026-07-15** (Android auto-backup logs + the original primary log set).

**Method:** Streaming extract of 0x381 (cell min/avg/max mV), 0x383 (SoC, charge flags),
0x275 (pack current + discharge/charge limits) from every session, downsampled to 1 Hz,
bucketed charging/driving. Scripts + per-session CSVs in
`artifacts/battery-degradation/` (see its README). Capacity via mid-range coulomb
counting; imbalance and derating via per-session extremes.

> **⚠ Cell numbering updated 2026-07-22.** The C CAN DBC (`CODA-C-CAN-cells.dbc`) is now
> **1-based** (`Cell1…Cell104`), matching the BMS's own `VmaxId`/`VminId` directly
> (VmaxId 82 = Cell82). It was previously **0-based** (`Cell0…Cell103`). Cell numbers in this
> file have been updated to 1-based; **any older artifact, CSV, plot, or export is still
> 0-based — add 1 to reconcile** (old `#94` = current `Cell95`). `VmaxId`/`VminId`/"BMS index"
> values were always 1-based and are unchanged. `MinTempId`/`MaxTempId` are a separate index,
> unaffected. See `cell-index-mapping.md`.

**Working model (per owner):** the **max cell = the cell with the failed balance channel**
(tops out early, ends charge); the **min cell = the weak cell** (sags first, limits
discharge); the other ~102 cells ≈ the average.

---

## 0. Prerequisite: 0x381 byte-order was mislabeled (corrected 2026-07-15)

The DBC/decode-notes had **Min↔Avg swapped** on 0x381. Corrected mapping (now in
`CODA-B-CAN.dbc`, `coda.md`, `codacan-signal-decode-notes.md`):

| Bytes | Signal |
|---|---|
| B0-B1 | **AvgCellVoltage** |
| B2-B3 | MaxCellVoltage |
| B4-B5 | **MinCellVoltage** |
| B6 | **VmaxId** |
| B7 | **VminId** |

**Evidence:** an average must lie between min and max — `B4B5 ≤ B0B1 ≤ B2B3` holds in
**99.0%** of 20,536 samples (DBC's ordering: 0.8%). **Root cause:** the LabVIEW
`BMS_Recvd.xml` cluster order is correct (`Vavg, Vmax, Vmin, VmaxId, VminId`); the error
entered at the bench-replay decode step, which went by the cluster *name* "Vmin**Vmax**"
(min-first) instead of the actual field order. All analysis below uses the corrected mapping.

The failed-balance (high) cell is **VmaxId 82 = Cell82** — pinned to that one index in
348/348 charge-termination frames, and independently confirmed as the over-voltage cell by
the full-charge log `coda_20260722_173203_*` (peaks 3778 mV at EOC, ~400 mV above any other
cell). The weak (low) cell is a *different* cell: **VminId 95 = Cell95**, the C-CAN cell
identified as the UV/limp trigger in `bonnydoon-limp-analysis.md`. **Cross-mapped 2026-07-22:**
both `VmaxId`/`VminId` and the C CAN DBC now use the same 1-based numbering, so these are
directly comparable (the old bonnydoon "#94" was the 0-based name for Cell95). Note also that
the cell that reads *highest under discharge load* (Cell84) is neither of these — see
`cell-index-mapping.md`.

---

## 1. Key realization: shallow cycling is FORCED, not chosen

Across all logs the pack is cycled almost entirely in the top half (median session floor
~89% SoC; lowest ever logged 40.4%; only 2 sessions below 50%). This is **not** a usage
preference — the **weak cell triggers undervoltage/limp cutoff and stops discharge**, so
the pack physically can't be driven lower. Consequence: the telemetry cannot directly see
the weak cell hit its floor, so the numbers below lean on two owner field observations:

- **Originally** (before degradation) the pack could be driven to **~11% SoC**.
- **A few months ago** UV cutoff was reached at **~40% SoC**.

The BMS SoC scale is **not** recalibrated to the degraded window (UV cutoff shows at 40%,
not 0%), so SoC still maps to the original 0–100% pack scale.

---

## 2. Capacity: bulk vs usable

| Measure | Value | Notes |
|---|---|---|
| Nominal | 31 kWh (~93 Ah @ 333 V) | owner-stated original |
| **Bulk** cell capacity now | ~82 Ah ≈ **27 kWh** (~12% fade) | mid-range coulomb slope 0.82 Ah/%SoC; cells mostly healthy in bulk |
| **Usable** originally (11%→100%) | ~27.6 kWh | field floor 11% |
| **Usable** now (40%→100%) | **~16 kWh** | field floor 40% |
| **Usable-capacity loss** | **~41%** | the number actually felt |

The often-quoted "~27 kWh" is the **bulk** figure (full 0–100% window). Real **usable** is
**~16 kWh** because the bottom ~40% is stranded behind the weak cell's cutoff.

### Rough attribution of the usable loss (ESTIMATES — see caveats)

| Cause | ~kWh | Character |
|---|---|---|
| **Weak cell (bottom)** — floor 11%→40% strands ~29% of pack | **~9** | **dominant**; series weakest-link caps whole-pack discharge |
| Bulk aging — all 104 cells 93→82 Ah | ~3.8 | general age |
| **Failed-balance cell (top)** — caps charge, still reaches 100% indicated | ~1–2 (growing) | "won't finish charging" symptom |

---

## 3. Failed-balance cell (top) — VmaxId 82 (= Cell82)

Every full charge terminates the same way: one cell hits the **3750 mV OV cutoff** while the
other 103 sit ~390 mV lower and bunched together (min ≈ avg → one runaway, 103 uniform):

| Date | maxC | avgC | minC | top gap (max−avg) |
|---|---|---|---|---|
| 2026-02-18 | 3776 | 3410 | 3398 | 366 |
| 2026-02-19 | 3779 | 3418 | 3405 | 361 |
| 2026-04-15 | 3779 | 3393 | 3382 | 386 |
| 2026-05-24 | 3780 | 3386 | 3386 | 394 |

Charge-termination top gap grows **+~28 mV Feb→May** (~+9 mV/month) — the cell is drifting
progressively further ahead. At "100%," the good cells only reach ~3.34 V rest (not fully
saturated), because this one cell forces cutoff. Resting high-SoC imbalance (~30–40 mV) is
roughly flat; the imbalance manifests most at the top of charge.

---

## 4. Weak cell (bottom) — the dominant limiter

At **rest** it's only ~30–40 mV below average. Under **hard load** it sags to **2.6–2.75 V**
(−250 to −382 A) even at 65–100% SoC — a high-**resistance** cell. As SoC drops it diverges
fast (e.g. `frombonnydoon` at 44%: min cell 3038 mV rest, 2817 mV under load, 53–70 mV below
avg). When it sags far enough the BMS folds back discharge current (§5) and ultimately
triggers UV cutoff — the mechanism setting the ~40% usable floor.

### 5. Discharge-limit foldback (0x275 B0) — onset SoC rising over time

`BattSentDischargeLimit` sits at full **396 A** in normal driving (the sub-396 values during
the first ~2 s are the key-on ramp, not derating). Genuine **under-load** foldback to
**174 A** (44% of nominal) occurs when the weak cell sags to ~3000–3050 mV, and its **onset
SoC is climbing** — i.e. the derate kicks in earlier (higher SoC) as the cell degrades:

| Date | Onset SoC | min cell @ onset | clamps to |
|---|---|---|---|
| 2026-02-19 (`frombonnydoon`) | ~50% | 2998 mV | 174 A |
| 2026-05-07 | ~56% | 3057 mV | 174 A |
| 2026-07-02 | ~62% | 3055 mV | 174 A |
| 2026-07-02 | ~56% | 2966 mV | 174 A |

**Trend: derate onset ~50% (Feb) → ~56% (May) → ~56–62% (Jul)** at a roughly constant
~3000–3050 mV trigger — consistent with the weak cell losing capacity/margin. (Small N:
~4 solid low-SoC events; deeper drives would sharpen it.)

A separate `124 A @ 100% SoC` derate (May 7/24, min cell high ~3303 mV) is a different
top-of-charge mechanism, not the weak-cell foldback.

---

## 6. Caveats & how to confirm

- kWh figures are **estimates**: the ~16 kWh usable leans on the owner's 11%/40% floor
  observations; telemetry never captured a fresh UV-cutoff event (deepest logs ~40–44% in
  Feb, ~53% recently). Bulk 82 Ah extrapolates a mid-range slope (±~2 kWh).
- **To nail it:** one drive taken to the actual UV cutoff **with C-CAN per-cell logging**
  (0x000–0x019, all 104 cells) would pin the weak cell's exact capacity and confirm the
  usable floor; a full charge logged on C-CAN would pin the top stranding.
- Discharge-limit trend is directional (small N); more sub-60% hard drives would strengthen it.

---

## 7. Cell-level degradation history — resistance vs capacity, and the swap decision

Two data sources: the **C CAN per-cell array** (0x000–0x019) on the three rare C-CAN drives
(Findings A/B, resistance vs capacity across eras), and **0x381 VminId** on all 237 B+D
sessions (Finding C, the dense min-cell history — no C CAN needed). Two **distinct** cell
failure modes separate cleanly. Scripts: `artifacts/cell_resistance_compare.py`,
`artifacts/fullcharge_weak_cell_scan.py`, `artifacts/fade_screen.py`, `artifacts/vminid_history.py`.

**Two metrics, both relative (so temperature divides out — the 2024 log is colder):**

- **Relative resistance** `R_i / R_avg` — slope of `d(cell_i)` vs `d(pack_mean)` across
  consecutive sweeps. Series cells share current, so current cancels; differencing removes
  slow SoC drift. `>1` = higher resistance than the pack average.
- **Capacity signature** — slope of a cell's deviation-from-mean vs pack-mean *level* among
  near-rest sweeps. `>0` = the cell sinks further below the pack as SoC falls (low capacity).

**Data:** `logs/data/17_drive_M0*` (Nov 2024, C-CAN-only, healthy baseline),
`frombonnydoon.log` (Feb 2026, ran to ~44% SoC — cleanest capacity read),
`CANLogs/CodaLogs/coda_20260722_191919_*` (Jul 2026, drive at ~100% SoC).

### Finding A — the high-resistance cells are intrinsic and lifelong, not acquired

| Cell | Nov'24 (healthy) | Jul'26 (now) |
|---|---|---|
| Cell76 | 1.11 | 1.12 |
| Cell71 | 1.10 | 1.14 |
| Cell95 | 1.10 | 1.11 |
| Cell89 | 1.09 | 1.12 |
| Cell16 | 1.09 | 1.10 |
| Cell82 | 1.05 | 1.03 |

Cell76 and Cell71 were **already the top relative-resistance cells when the pack was healthy**
and have barely moved in ~20 months. The high-R group (76, 71, 95, 89, 16, 17, 11) is largely
the same set then and now. This is intrinsic manufacturing spread, stable over years — not
progressive resistance growth. (The current-based scan of the Jul'26 full-charge drive
independently ranks Cell76/Cell71 highest by IR drop, corroborating the current-free metric.)

### Finding B — Cell95's low-capacity fault is acquired, and appeared after Nov 2024

Capacity signature (>0 = sinks as SoC falls):

| Cell | Nov'24 (healthy) | Feb'26 | Jul'26 |
|---|---|---|---|
| **Cell95** | 0.036 (middling) | **0.138 (dominant)** | 0.074 |
| Cell76 | 0.077 | 0.069 | 0.092 |
| Cell17 | 0.062 | 0.066 | 0.068 |

In the healthy Nov 2024 log — taken with a *full* SoC excursion (pack ran to ~2740 mV avg, so
the metric had every chance to see it) — Cell95's capacity signature was **unremarkable**
(0.036, mid-pack, not a top-6 fader). By Feb 2026 it was the single dominant capacity-fade
cell (0.138). So the capacity collapse began in the **Nov'24 → Feb'26** window — and, per the
dense 0x381 history below (Finding C), it has **continued to worsen through 2026**, not
plateaued.

What *was* present in 2024 was the softer precursor: Cell95 already sat in the elevated-**R**
group (1.10). So the cell was marginally weak by resistance before its capacity failed — but
the specific low-capacity fault that makes it today's limp/UV trigger was not yet visible.

### Finding C — dense min-cell history from 0x381 (all 237 sessions, no C CAN needed)

`0x381` reports **VminId** (B7) = the BMS's own 1-based min-cell number, so every B+D Android
log tracks *which* cell is weakest and its min-to-avg gap — no C CAN required. Aggregated over
all sessions at **low SoC (≤70%)**, where a low-capacity cell shows most
(`artifacts/vminid_history.py`):

| Month (2026) | Cell95 = min cell | median min→avg gap |
|---|---|---|
| Feb | 77% | 45 mV |
| Apr | 62% | 35 mV |
| May | 75% | 44 mV |
| Jun | 85% | 47 mV |
| **Jul** | **98%** | **68 mV** (to 92 mV @ 54–58% SoC) |

**Cell95 is progressively, actively degrading** — dominance 77%→98%, gap 45→68+ mV across
2026. (This corrects an earlier read from the 3 sparse C-CAN drives that suggested it was
"stable since Feb"; the dense 0x381 record shows continued worsening.)

**Screen for any other emerging weak cell — negative.** All-time min-cell share excluding
95/96: Cell104 5.9%, Cell100 5.6%, Cell99 5.5%, Cell76 4.5%, Cell71 3.3% — the *same*
intrinsic low cells seen in the healthy Nov 2024 baseline, with **flat monthly share all
year**. None is rising or newly emergent. Cell96 stays 3–11% (SoC-dependent, stable).

> **Note — the §0 byte-order swap, now resolved in the data.** The VminId/VmaxId id
> attribution was corrected 2026-07-15 (B6=VmaxId, B7=VminId; see §0 and
> `cell-index-mapping.md`), but the `sessions/*.csv` extractor initially applied it only to the
> min/avg/max *voltages*, leaving the *id columns* swapped. `extract_degradation.py` was fixed
> 2026-07-22 and the CSVs were **regenerated 2026-08-09** — the columns are now correct
> (`vminid` = true min cell). Verified: `vminid` now holds the min cells (95/72/96) and `vmaxid`
> holds 82 (the VmaxId OV cell) at charge termination. The regen also extended coverage to
> 2026-07-23 (253 sessions); the trajectory above is unchanged.

### Consequence and swap decision (Jul 2026)

The bad cells have distinct profiles:
- **Cell95** — acquired low capacity, **still actively worsening**. Bottom-of-charge limiter /
  limp+UV trigger. **Swap.**
- **Cell82** — failed balance channel + slightly elevated R. Top-of-charge OV cell (§3).
  **Swap.**
- **Cell96** — Cell95's immediate neighbour (adjacent BMS index, same C CAN frame 0x017). An
  *intrinsic* low cell (already the #1 low cell in healthy Nov 2024, −13 mV; drifted only to
  ~−19 mV in 20 months). Not a swap driver on its own; likely replaced with Cell95's module if
  they share one (confirm physical module boundary).

**No third module is justified.** Every other recurrent low cell (Cell104, 100, 99, 76, 71) and
the intrinsically higher-R cells (Cell71, 89, 17) have years of *stable* history — replacing
any of them trades a known-good, years-proven cell for an unknown fresh one. **Cell76/Cell71**
are intrinsically higher-R but stable — the pack's high-current-sag cells by design, not by
fault.

---

## Artifacts

`artifacts/battery-degradation/`:
- `extract_degradation.py` — per-session streaming extractor (→ `sessions/*.csv`, `manifest.json`, `session_summary.jsonl`)
- `analyze_degradation.py` — coverage, top/bottom trends, imbalance-vs-SoC, monthly trends
- `dislimit_trend.py` — discharge-limit foldback event detector (→ `dislimit_events.json`)
