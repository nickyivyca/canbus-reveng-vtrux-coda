# Vtrux Evap Cycle Analysis

**Log files:** `vtruxevapdrivelog4.log` (part 1, 1462s) + `vtruxevapdrivelog4part2.log` (part 2, 342s)

## Background

During the evap drive cycle, an unidentified signal was observed holding constant from log start until the generator kicks on at ~80% SoC, then slowly counting down as the engine runs and purges the canister, reaching its end state at evap cycle completion near the start of part 2.

Two mechanisms were investigated:

- **Hypothesis A (OBD diagnostic read):** Via VCM queries the GM ECU over OBD (Mode 0x01 or Mode 0x22 enhanced) for an EVAP canister status PID.
- **Hypothesis B (PT bus internal timer):** Via VCM broadcasts an evap progress counter on the powertrain bus — a stage index that decrements as purge progresses.

The signal could live on any of the three buses (PT, Vehicle, OBD).

---

## Summary

**STATUS UPDATE (Phase 2B, 2026-03-05): The 0x600 B3 identification as evap stage counter is invalidated.**
See Phase 2B below. B3 tracks engine/generator operational state and changes with M mode shifts and stall
events that have nothing to do with evap progress. The original correlation was a coincidence of the first
evap drive where the engine only ran for evap purposes. True evap status signal not yet identified —
event cluster scan in progress.

---

The original Phase 1 identification (now revised) was **0x600 B3** (and coupled byte B2) on the **PT bus**.

- B3 = VCM engine/generator operational state counter (descends when engine running, holds when engine off/stalled, resets to 12 at key cycle)
- B2 = sub-counter within each B3 state
- B0 bit 4 = generator active flag (0x34=active, 0x24=inactive) — still valid

---

## Hypotheses Evaluated

### Hypothesis A — OBD Diagnostic Read (RULED OUT)
Via VCM polls the GM ECU over OBD for an EVAP canister status PID, and the VCM or scanner displays the
descending value.

**Evidence against:** `scan_obd_traffic.py` scanned the full evap drive log for all OBD traffic on the OBD bus.
The only PIDs actively polled were:

| PID  | Name              | Count |
|------|-------------------|-------|
| 0x10 | (Monitor status)  | 3023  |
| 0x44 | FuelAirEquivRatio | 3023  |
| 0x0C | EngineRPM         | 3022  |
| 0x0D | VehicleSpeed_kmh  | 3022  |
| 0x05 | EngineCoolantTemp | 152   |

No EVAP PIDs (0x2E CommandedEvapPurge, 0x53 AbsEvapVaporPressure, 0x54 EvapVaporPressure) were polled.
No Mode 0x62 (GM enhanced) responses appeared. Hypothesis A ruled out.

### Hypothesis B — PT Bus Internal Timer/State (CONFIRMED)
Via VCM broadcasts an evap progress counter on the PT bus — a stage index that starts near a nominal
"loaded" value when evap is commanded, steps downward as the engine purges the canister, and resets to its
idle state (11) when purge is complete.

---

## Signal: 0x600 B3 (PT bus)

**Message:** 0x600, PT bus, 20 Hz
**Byte:** B3 (index 3)
**Type:** Unsigned byte, evap cycle stage counter
**Normal operating value:** 0x0C = 12 (confirmed across driveway, gen on/off, and climit logs — no evap activity in any of them). Earlier notes incorrectly stated 0x0B = 11 as the idle value; that was based on a single post-evap log (debuglog_M0_T7) where 11 persisted because the prior session had just completed an evap cycle.

### State Definitions

| B3 value | Meaning |
|----------|---------|
| 12 (0x0C) | Normal operating state — no evap in progress |
| 6 | Evap in progress — early stage |
| 4–5 | Evap in progress — mid/late stage |
| 3 | Evap in progress — near completion |
| 11 (0x0B) | Post-evap state — evap cycle complete; VCM releases generator within ~4s. Persists until next key cycle. |
| 0–10 (transient at boot) | VCM startup sequence — B3 rises from 0 to 12 at key-on |

### Coupled Byte: 0x600 B2

B2 varies continuously within each B3 stage and appears to be a sub-stage counter. Together, B2-B3 as a
little-endian uint16 tracks finer progress than B3 alone:

| Stage | B3 | Example B2 | LE uint16 |
|-------|----|------------|-----------|
| Idle  | 0x0B | 0x5C, 0x0A, 0x33 | 2908, 2826, 2867 |
| Evap start | 0x0C | 0xA3 | 3235 |
| Evap mid | 0x04 | 0x28, 0x00, 0xCC | 1064, 1024, 1228 |
| Near end | 0x03 | 0x33, 0xB8, 0x66 | 819, 696, 614 |
| Complete | 0x0B | resets to idle range | 2826–2908 |

---

## Part 1 Trajectory (vtruxevapdrivelog4.log)

Generator start: t=431.686s

| Time (s) | B3 | Notes |
|----------|----|-------|
| 0–450 | 12 | Constant. Evap cycle pending. Generator not yet running. |
| ~540 | 6 | First change, ~110s after generator start. Evap purge underway. |
| ~600 | 11 (transient) | Brief reset to idle — VCM may have detected partial completion condition, then re-entered evap. |
| 630–1080 | 4 | Long plateau. Active purge mid-stage. |
| ~1080 | 3 | Deeper stage reached. |
| ~1140 | 11 (transient) | Another brief idle — similar transient completion check. |
| 1141–1260 | 4–5 | Re-enters purge stage. |
| 1260–1441 | 4→3 | Final descent at end of part 1. |

**End of part 1:** B3=3–4, B2-B3 LE ≈ 860. Evap still in progress (logging gap follows).

**Note:** The ~110s lag between generator start (431.7s) and first B3 change (~540s) suggests the VCM
requires a warm-up period before the evap purge stage advances.

---

## Part 2 Trajectory (vtruxevapdrivelog4part2.log)

Logging resumes after a brief gap (generator was still running during the gap).

| Time (s) | B3 | B0 | Notes |
|----------|----|-----|-------|
| 0–10.6 | 4 | 0x34 | Evap still in progress (continuing from part 1). Generator active. |
| 10.65 | 4→5→...→11 | 0x34 | **B3 begins rising** — evap completion sequence starts. Generator still running. |
| 12.07 | 11 | 0x34 | B3 reaches idle value. Evap stage declared complete. |
| 10.86–11.6 | — | — | Generator revs up to ~2400 RPM (load change as purge stops), then decelerates. |
| 15.6 | 11 | **0x24** | **B0 bit 4 clears** — VCM flags generator as inactive. |
| 16.7 | — | — | Engine RPM reaches 0. |
| ~16.7–90 | 11 | 0x24 | Post-evap EV driving. B3 stable at 11. |
| ~90 | 3 | 0x34 | **User manually starts engine (M mode).** B3 picks up from ~3 (continuing to purge). |
| 90–145 | 3→2 | 0x34 | Manual engine run. B2-B3 LE continues descending: 819→696→655→614. |
| 145.5 | 11 | **0x24** | **User stops M mode.** B3 snaps back to 11, B0 clears. |
| 145.5–end | 11 | 0x24/0x10 | EV-only driving. B3 stable at 11. |

**Evap completion event:** B3 rises 4→11 over ~1.4s at t≈10.65s, followed by generator spin-down.

---

## Supporting Correlation Data (from find_evap_countdown.py)

| Bus | ID | Byte | pre_mean | pre_std | post_min | r (Pearson) |
|-----|----|------|----------|---------|----------|-------------|
| PT | 0x600 | 3 | 12.00 | 0.000 | 1.0 | +0.564 |

Note: r=0.564 (not high) reflects the non-monotonic nature of B3 — it's a step-wise state machine,
not a smooth countdown, so Pearson r underestimates the correlation strength.

---

## Additional Correlated Signal: OBD 0x1A1 B4

Also detected by the countdown scan (r=+0.752, pre_mean=156, post_min=68). However, this is likely
an **engine-state parameter** (value=156 when engine off, drops to ~68-93 when engine running) rather than
an evap-specific signal. Its correlation is explained by the generator running continuously during the
evap window, not by evap canister load specifically.

---

## Verification Checklist

- [x] Pre-gen: B3=12 constant (pre_std=0.000) from log start to t≈540s
- [x] Post-gen: B3 descends from 12 through 6→4→3 over the evap run
- [x] Part 2 continuation: B3=4 at part 2 start (consistent with end of part 1)
- [x] Completion event: B3 snaps to 11 at t≈12s in part 2
- [x] Generator shutdown follows B3 completion: B0 clears at t≈15.6s, engine stops t≈16.7s
- [x] M-mode cross-check: manual engine start resumes B3 from low value and continues counting down

---

## Outstanding Questions

1. ~~**Why does B3 start at 12, not 11?**~~ **RESOLVED (2026-02-28):** The premise was wrong.
   All non-evap drives show B3=12, not 11. B3=11 was observed in debuglog_M0_T7 because that
   session immediately followed an evap completion in T2. B3=12 is the normal operating state;
   B3=11 is the post-evap state that persists until the next key cycle. The evap log starting at
   12 is simply normal — it was not an indicator of evap pending.

2. **Meaning of the transient B3=11 spikes in part 1** (at t≈600s and t≈1140s): These brief
   returns to 11 during active purging remain unexplained. They may be intermediate stage resets,
   partial-completion milestones, or purge-stroke boundaries within the VCM's evap state machine.
   Need to examine adjacent bytes (B2, B4-B5) and other IDs during those windows.

3. **What is B2 exactly?** It changes continuously and does not obviously encode time or load.
   Possible: a 0.1s resolution sub-counter within each B3 stage, cycling 0→some max→0.

4. **Why does B3 counting up (4→11) correlate with generator REVVING UP?** The rev-up at t≈10.86s
   happens as B3 is counting 6→7→8→9... This may be the VCM removing purge load command from the
   engine simultaneously with declaring evap complete, causing a transient RPM increase.

---

## Phase 2 — Second Evap Log + Charge Context

### Phase 2A — Evap-Pending Bit in Charge Log (COMPLETE 2026-03-04)

**Log:** `vtruxchargeafterexportchargetest-80pctcv.log`
**Duration:** 9394s (~2h 36min). 36.6M frames. Bus3 = PT bus.
**Artifacts:** `status_events_evap_charge_80pct.txt`, `evap_charge_80pct_SoC_timeseries.csv`

**Background:** Battery had been drained to 13% SoC by an export power test. Charge ran CC from
13% to 80% (~7425s), then held at 80% CV for ~31 min before handle pull at t=9299s.

#### Findings

**1. 0x600 B3 = 12 throughout the entire charge**
The 25 COUNTER transitions in the status_events inventory are the boot sequence (B3 rising 0→12
at key-on, t~79s) only. After key-on, B3=12 constant for all 9394s. B3 carries no evap-stage
information during stationary charging — it only changes when the engine is actively purging.

**2. 0x600 message identical to normal charge**
Full frame: `25 00 A3 0C 00 00 0F 00` throughout. Compared against normal charge `charge_M0_T10`:
identical byte-for-byte. B0=0x25 is the standard charging state. B2=0xA3=163, B3=0x0C=12
(B2-B3 LE=3235, matching the evap drive log starting state).

**3. No "evap required" flag found on PT bus**
status_events found no discrete PT bus state changes at the 80% SoC threshold that could serve
as an "evap required" flag. 0x412 B2 (CCL source) held at 0xF0=240 from startup to shutdown;
0x050 B1/B3 (CCL enable) only toggled at startup/shutdown.

**4. SoC profile**
SoC=13% at key-on (t=79.4s). First reaches 80 at t=7425.7s. CC phase: 7345s (13%→80%).
CV hold t=7425s–9299s (~31 min), SoC clamped at 80%.

**5. PT bus event coincident with 80% threshold**
At t=7426.94s (1.2s after SoC first hits 80):
- `Bus3 0x648 B1: 0x00 → 0x75`
- `Bus3 0x647 B0: 0x08 → 0x04`
- `Bus3 0x648 B7: 0xA0 → 0x20 → 0xA0` (brief toggle)
These are VCU BMS cluster IDs (VCU-sourced). However, the same B1=0x75 state is present in
normal charges (`charge_M0_T40+` shows B1=0x75 constant at SoC=100%). These transitions mark
the CC→CV mode change, not an evap-specific event. The 80% cutover simply causes this transition
to happen at 80% instead of the normal LFP charge-curve knee.

**6. Isolated mid-charge event: 0x596 B0**
At t=469.34s: `Bus3 0x596 B0: 0x00 → 0x08`. Cleared at shutdown (t=9299.80s). Also present in
normal charges. Not evap-specific.

#### Conclusion

**No distinct "evap required" flag is broadcast on the PT bus.** The 80% SoC ceiling is most
likely enforced by the VCM issuing tighter charge current/voltage setpoints to the Bel charger
that terminate at the 80% SoC battery voltage — no separate "evap required" state is communicated
as a flag. The 0x600 B3 stage counter carries no evap-pending information during stationary
charging. The CC→CV transition events on 0x648/0x647 are structural markers of the mode change
that occur in all charges, not evap-specific indicators.

---

### Phase 2B — Second Evap Drive: Event Timeline and B3 Invalidation (COMPLETE 2026-03-05)

**Logs:** `vtruxanotherevaplogpart1.log` (364s), `vtruxanotherevaplogpart2.log` (2011s), `vtruxanotherevaplogpart3.log` (521s)
**Artifacts:** `anotherevap_p1_0x600.txt`, `anotherevap_p2_0x600.txt`, `anotherevap_p3_0x600.txt`,
`anotherevap_p1_0x600_b3.csv`, `anotherevap_p2_0x600_b3.csv`, `anotherevap_p3_0x600_b3.csv`,
`anotherevap_p2_rpm.csv`, `anotherevap_p2_corrected_events.png`

**Sidecar notes (part2):** Highway drive. Power was visibly limited before the generator kicked on.
Engine stalled and restarted during a drive through town. Cruise control used extensively. At end:
pulled into a quarry gate, shut off generator manually, drove down a quarry road.

**Sidecar notes (part3):** Drove out of quarry on EV-only. Turned generator on to climb a hill, then
off near the top. Discharge current limit was active when pressing throttle hard near the end.

#### Part 2 Confirmed Event Timeline

Events extracted from 0x63C B6 (generator RPM) zero-crossings; timestamps confirmed by user.

| Event | Time (Part 2) | Notes |
|-------|--------------|-------|
| Engine start | t=12.31s | Automatic — generator kicked on for hybrid operation |
| Engine stall start | t=808.42s | Involuntary stall during drive through town |
| Engine stall restart | t=815.81s | 7.4s stall duration |
| Engine auto-off | t=1392.79s | Evap cycle complete — VCM stops generator |
| M mode engage | t=1455.66s | User-commanded, hill climbing |
| M mode disengage | t=1669.86s | User-commanded |

#### 0x600 B3 Behavior During Part 2 Events

- **At engine start (t=12.31s):** B3=12 → begins descending immediately.
- **During stall (t=808–816s):** B3 was at 11 and **held unchanged** through the stall. No reset to
  12 or drop to 0. B3 holds its value when the engine stops unexpectedly.
- **At engine auto-off (t=1392.79s):** B3 had reached 11 at t=1388.56s (4.2s before engine off).
  After engine off, B3=12 (resets to default when engine not running).
- **At M mode engage (t=1455.66s):** B3 immediately begins descending again from 12, identically to
  how it behaved at the initial engine start — the engine state is the same regardless of reason.
- **At M mode disengage (t=1669.86s):** B3 frozen at whatever value it held at engine-off.

#### Invalidation of 0x600 B3 as Evap Status Signal

B3 was identified as an "evap stage counter" based solely on the first evap drive, where the engine
only ran for evap purposes. In the second evap drive, B3 was observed responding identically to:

1. **Automatic generator start** (for hybrid power assist, not evap)
2. **User M mode** (purely manual, nothing to do with evap state)
3. **Engine stall** (accidental — B3 holds at stall, not tracking any evap condition)

B3 is a **engine/generator operational state counter** — it descends when the engine is running
(regardless of why) and resets to 12 at key-on or when the engine stops. It has no exclusive
relationship with the evap canister purge cycle.

The first evap drive showed B3 descending and completing in lockstep with evap only because the
engine ran exclusively for evap in that drive. With M mode and normal hybrid operation mixed in,
the correlation breaks down completely.

#### Stall Event Characterization (Phase 2C finding, embedded here)

The engine stall at t=808.42–815.81s is the first captured stall event. Key properties:

- **Duration:** 7.4s
- **B3 behavior:** B3=11 throughout — no change, no reset. The VCM does not alter 0x600 B3 on
  an unintended engine stop. B3 only resets to 12 on a voluntary/controlled engine-off.
- **RPM:** 0x63C B6 drops to near-zero at t=808.42s and recovers to normal at t=815.81s.
- Detailed event cluster scan around the stall window is deferred to Phase 2C (see below).

#### Conclusion

0x600 B3 is not the evap status signal. The true evap status signal (if present on the PT bus)
remains unidentified. The confirmed event timestamps from Part 2 provide reference windows for an
event cluster scan: signals that change at t=1392.79s (evap completion / engine auto-off) but NOT
at t=808s (stall), t=1455.66s (M mode on), or t=1669.86s (M mode off) are candidate evap signals.

---

### Phase 2C — Event Cluster Scan (COMPLETE 2026-03-05)

**Script:** `evap_event_cluster_scan.py`
**Log:** `vtruxanotherevaplogpart2.log`
**Output:** `evap_cluster_scan_results.txt`

Single-pass scan recording all byte-level transitions (bus, msg_id, byte_pos, old_val, new_val)
within four reference windows. Candidates = changed in evap_done, NOT in any control window.

**Reference windows:**
- `evap_done`: t=1388–1395s (evap complete / engine auto-off)
- `stall`:     t=806–818s (control: involuntary stop)
- `m_on`:      t=1453–1458s (control: M mode engage)
- `m_off`:     t=1667–1672s (control: M mode disengage)

**Summary counts:**
- Signals changed in evap_done window: 578
- Signals changed in any control window: 713
- **Candidates (evap-only): 14**

#### Candidate Analysis

**Top candidates (clean, single-shot transitions):**

| Signal | Transition | Time | Notes |
|--------|-----------|------|-------|
| Bus1 0x1A1 B1 | 0x04 → 0x00 | t=1388.060s | Unidentified GM message (not in any DBC) |
| Bus2 0x1A1 B1 | 0x04 → 0x00 | t=1388.058s | Same message, VCM-forwarded to second bus |
| Bus1 0x4C1 B2 | 0x86 → 0x85 | t=1388.043s | EPRI engine temperature message |
| Bus2 0x4C1 B2 | 0x86 → 0x85 | t=1388.040s | Same, forwarded |
| Bus3 0x600 B2+B3 | large jump | t=1388.555s | Already understood: B2-B3 sub-counter pair |

Remaining 9 candidates (0x370 B7, 0x410 B3, 0x596 B6, 0x589 B7, 0x0BE B4, 0xC0CA040 B3,
0x18FFD6B3 B0, and two others) are lower-priority: they are either BMS-sourced IDs that change
infrequently, or signals where the coincidence window is wide enough that noise/drift explains it.

#### 0x1A1 B1 — Ruled Out (Coincidental Pulse)

**Message identity:** 0x1A1 is an unidentified GM bus message, observed at 80 Hz, DLC=7,
bridged by VCM to both GM buses.

**Cross-validation result (2026-03-05):** Extracted 0x1A1 B1 timeseries from the full Part 2 log
(`anotherevap_p2_0x1a1_b1.csv`). B1 does NOT hold at 0x04 throughout the evap period — it
**oscillates between 0x00 and 0x04 frequently throughout the entire engine-running window.**
Dozens of 0x04 pulses occur between t=241s and t=1388s, each lasting 0.5–2s. The transition at
t=1388.058s that the cluster scan captured was simply the **last pulse** of this regular
oscillation, coincidentally within the evap_done window.

The control windows (stall t=806-818s, M-on t=1453-1458s, M-off t=1667-1672s) did not catch any
transitions only because B1 happened to be in its 0x00 phase during those specific windows.

**B1 full behavior in Part 2:**

| Time | B1 | Event |
|------|----|-------|
| t=0.001s | 0x10 | Engine off (initial) |
| t=12.389s | 0x00 | Engine starts |
| t=241–1388s | 0x00/0x04 oscillating | Engine running; frequent pulses (dozens) |
| t=1388.058s | 0x00 | Last pulse returns to 0x00 (within evap_done window) |
| t=1388–1505s | 0x00 | Engine stopped after evap; no transitions |
| t=1505–1508s | 0x04/0x05/0x06/0x02/0x03/0x00 | M mode engine run resumes oscillation |

The 0x04 oscillation pattern is unrelated to evap — it occurs throughout all engine operation.
It likely represents a sub-state counter or rolling field within the B1 byte.

**Observed B1 states (empirical):**
- 0x10: engine off (initial cold start / before first run)
- 0x00: engine running (or post-run idle between pulses)
- 0x20: seen in first evap drive part 1 (different operating mode)
- 0x04/0x05/0x06/0x02/0x03: oscillating pulses during engine operation

**Conclusion:** 0x1A1 B1 is NOT an evap signal. The cluster scan result was coincidental.

#### 0x4C1 B2 — Ruled Out (Engine Coolant Temperature)

**Message identity:** 0x4C1 is an EPRI-attributed engine temperature message
(`EPRI_PPEI_Engine_General_Status_4_04C1` in `epri-obd-bus.dbc`). Faithfully bridged between
both GM buses (byte-identical). Per the EPRI decompile, B2 encodes `ECM_EngineCoolantTemp` — a
continuous raw byte (scale 1, offset -40 degC).

**Conclusion:** A single-count drop in coolant temperature (0x86→0x85) coinciding with the evap
completion window is coincidental. Engine temperature fluctuates ±1 count continuously. Ruled out.

#### Cluster Scan Conclusion

Both top candidates from the cluster scan have been ruled out after cross-validation:
- **0x1A1 B1:** oscillating sub-state counter during all engine operation; evap_done transition was a coincidental last pulse before the engine stopped
- **0x4C1 B2:** engine coolant temperature single-count drop; coincidental

**Cross-validation results (2026-03-05):** All remaining candidates checked against
`vtruxevapdrivelog4part2.log` via `evap_crossval_scan.py`. Every candidate was ruled out:

| Candidate | Verdict |
|-----------|---------|
| Bus1+Bus2 0x589 B7 | 0 evap-window hits in first drive; fires in M-ON only — not evap |
| Bus2 0x0BE B4 | 3094 transitions total (294 in evap window) — continuously oscillating |
| Bus3 0x370 B7 | 34 transitions in 342s log; 1 in evap window is coincidental |
| Bus3 0x410 B3 | 36 transitions in 342s; 1 in evap window is coincidental |
| Bus3 0x596 B6 | 0 evap hits in first drive — SoC decrement in second drive was coincidental |
| Bus3 0xC0CA040 B3 | Rapid rolling counter throughout entire log |
| Bus3 0x18FFD6B3 B0 | More transitions in M-ON than evap window — not evap-specific |

**Conclusion: The cluster scan found no confirmed evap signal.** All 14 candidates fail either the
cross-validation or the oscillation check.

#### Why the Scan Missed It

The cluster scan filter (changed in evap_done, NOT in any control window) has a blind spot: if the
true evap status signal ALSO responds to M mode engine start/stop (likely — the VCM would update
evap state at any controlled engine event), it would be classified as an "engine-state" signal and
excluded from candidates. The stall and M mode controls are too broad to distinguish
evap-specific transitions from engine-state transitions.

#### Two-Window Comparison — Finding 0x649 B0 (COMPLETE 2026-03-05)

**Script:** `evap_two_window_compare.py`
**Output:** `evap_two_window_results.txt`
**Windows:** A = t=12.31–1388s (engine + evap active); B = t=1455.66–1669.86s (M mode, no evap)
**Stability threshold:** 90% of samples at modal value; min 200 samples per window.

Results: 883 signals stable in both windows; 871 with same modal value (engine-state signals);
**12 with different values between windows (candidates).**

Key candidates from timing analysis:

| Signal | Window A value | Window B value | Transition time | Verdict |
|--------|---------------|---------------|-----------------|---------|
| Bus3 **0x649 B0** | 0x91 (99.9%) | 0x00 (100%) | t=1386.794s | **EVAP SIGNAL** |
| Bus3 **0x649 B4** | 0x83 (99.9%) | 0x02 (100%) | t=1386.784s | Related to 0x649 B0 |
| Bus3 0x649 B5 | 0x1B (94.0%) | 0xFB (100%) | multiple | Complex; linked to 0x649 |
| Bus1 0x1F5 B3 | 0x04 (98.5%) | 0x09 (99.5%) | n/a | GMLAN gear position (Drive vs Manual) |
| Bus1 0x1F5 B5 | 0x00 (100%) | 0x02 (99.5%) | n/a | 0x1F5 transmission state byte |
| Bus3 0x644 B0 | 0xD0 (98.5%) | 0x10 (99.5%) | t=1438.627s | VCU→BMS cmd; fires 46s after engine stop, not at evap |
| Bus3 0x639 B6 | 0x32 (98.5%) | 0x42 (99.5%) | t=1438.626s | Same ~46s post-engine-stop cluster; not evap |
| Bus3 0x592 B1/B6 | 0x03 (98.5%) | 0x04 (99.5%) | t=1438.66s | Same 46s cluster |
| Bus3 0x6000001 B3 | 0x0D (98.5%) | 0x11 (99.5%) | t=1438.66s | Same 46s cluster |
| Bus1 0x140 B1 | 0x02 (100%) | 0x04 (100%) | t=1450.4s | Transitions near M mode, not at evap |
| Bus3 0x5A0 B0 | 0x04 (99.4%) | 0x06 (99.5%) | t=1391.878s | Engine-stop coincident |

**Note on the t=1438s cluster:** 0x644 B0, 0x639 B6, 0x592 B1/B6, 0x6000001 B3 all transition
within milliseconds of each other at t≈1438.6s — 46 seconds after engine stop, 17 seconds before
M mode engage. This is likely the VCM switching to a different idle/ready mode after the evap
engine-off completes its cooldown. Not evap-specific.

---

### Phase 2D — 0x649 B0 Evap Status Signal (COMPLETE 2026-03-05)

**Signal:** `0x649 B0` (PT bus; VCU-sourced; part of the 0x639–0x64B VCU cluster)

#### Evidence

The two-window comparison flagged 0x649 B0 as a strong candidate. Timing analysis showed it
transitions ~6 seconds BEFORE engine stop in the second evap drive — 1.2 seconds before the
cluster scan window opened, which is why the scan missed it. Confirmed across **three independent
evap completion events** in three different logs:

| Log | Starting B0 | Transition | Engine off | Lead |
|-----|------------|-----------|-----------|------|
| `vtruxevapdrivelog4part2.log` | 0xBB (evap active from part 1) | t=10.529s | t≈16.7s | **~6.2s** |
| `vtruxanotherevaplogpart2.log` | 0x91 (evap active, engine running) | t=1386.794s | t=1392.79s | **~6.0s** |
| `oghighwaydrive.log` | 0xC6 (evap active, engine running) | t=1223.257s | t=1229.379s | **~6.1s** |

The ~6.1s lead is consistent to ±0.1s across all three events. The VCM writes B0=0x00 first,
then stops the engine — B0 is the declaration, engine stop is the consequence.

Additional evidence from two supporting logs:

| Log | B0 value | Notes |
|-----|----------|-------|
| `vtruxevapdrivelog4.log` (Part 1, full 1462s) | **0xBB** constant, zero transitions | Evap in progress; engine start at t=431.7s does NOT change B0 |
| `generator on then off.log` (M mode only, 64s) | **0x04** constant | No evap session; engine runs in M mode only |

**After evap completion, B0=0x00 throughout — including subsequent M mode engine-on periods.**
Engine running for M mode does NOT restore B0 to a non-zero value. This rules out engine-state
as the underlying signal.

#### State Encoding

| B0 value | State |
|----------|-------|
| **0xBB / 0x91 / 0xC6** (bit 7 set) | Evap cycle in progress |
| **0x00** | Evap cycle completed this key session |
| **0x04** | No evap session this key cycle (baseline; only M mode engine use seen) |

All three "evap in progress" values have bit 7 set; lower 7 bits differ by session. B0 is
constant throughout the entire evap run — it does not count down. It holds at the
session-start value and clears to 0x00 only at evap completion.

#### Why the Cluster Scan Missed It

The cluster scan evap_done window was t=1388–1395s in the second evap drive. The actual
transition was at t=1386.794s — 1.2s before the window opened. B0 fires ~6s before engine stop;
the B3→11 transition (which anchored the window) fires ~1.76s after B0.

#### Outstanding Questions

1. **Full 0x649 message structure.** B4 and B5 also change around evap completion in the second
   drive. B0 is the cleanest single-byte signal but the full message may encode more evap state
   detail. Also check whether B0 differs between the automatic engine-on at the start of the
   second evap drive (t=12.31s, SoC-driven) vs the M mode engine-on — both are in the same log
   so this is directly testable.

2. **Meaning of the non-zero values.** All three "evap in progress" values (0xBB, 0x91, 0xC6)
   have bit 7 set; lower 7 bits differ by session. Whether bit 7 alone is the "evap active"
   flag, or whether the full byte value encodes initial canister load or other session context,
   is unresolved.

3. ~~**Automatic engine start for power (no evap) — `vtruxcurrentlimitingtest.log`.**~~
   **RESOLVED (2026-03-05):** B0=0x00 constant throughout the entire 1810s log — from the
   very first frame, before the engine starts. B0 does NOT change when the automatic SoC-triggered
   engine start occurs. Therefore:
   - 0x04 is NOT the general "no evap needed" baseline; it is specific to `generator on then off.log`.
   - Bit 7 = evap active flag still holds: both 0x00 and 0x04 have bit 7 clear; all "evap in progress"
     values (0xBB, 0x91, 0xC6) have bit 7 set.
   - B0 is a session-level policy flag set at key-on (or persisted in VCM memory), NOT a dynamic
     engine-mode indicator. It does not update on engine start/stop or M mode transitions within a session.
   - The 0x04 vs 0x00 distinction in non-evap contexts likely reflects VCM evap history: 0x04 = no prior
     evap completion in VCM memory (fresh state); 0x00 = evap was completed at some prior point and VCM
     cleared the flag. `generator on then off.log` was probably a fresh-state capture; `vtruxcurrentlimitingtest.log`
     was captured after a prior evap completion.
   - The lower 7 bits do NOT encode engine start reason (M mode vs automatic SoC). The encoding is more
     complex than a single bit 7 flag, but the core "bit 7 set = evap in progress" interpretation is confirmed.

4. ~~**Pre-engine-start period in the first evap drive — `vtruxevapdrivelog4.log`.**~~
   **RESOLVED (2026-03-05):** Already answered by Phase 2D data. B0=0xBB constant across all
   1462s of Part 1, with zero transitions. The engine doesn't start until t=431.7s, yet B0=0xBB
   from the very first frame. B0 encodes "evap needed" at key-on, before the engine ever runs —
   the VCM sets the flag based on canister load state at startup, not at engine start. Engine start
   is a consequence of the evap-pending condition, not the trigger for B0 to become meaningful.

5. ~~**0x649 B0 during stationary charging — `vtruxchargeafterexportchargetest-80pctcv.log`.**~~
   **RESOLVED (2026-03-05):** B0 = 0x7D → 0x7F (3 unique values) across the entire 9394s charge.
   All have bit 7 CLEAR — no evap-active flag. Two additional findings:
   - The full 0x649 message content is completely different in charge mode vs drive mode (B4-B7 all differ:
     charge `7d 19 f0 00 83 23 30 00` vs drive `00 37 a0 00 03 33 40 40`). The message repurposes its
     byte fields between drive and charge states. B0 values cannot be compared across modes.
   - The 0x7D→0x7F drift (~2 counts over 2.6h) likely represents a slow counter or temperature-like value
     in charge mode; it has no relationship to the evap-active meaning in drive mode.
   **Conclusion:** 0x649 B0 does NOT track evap-pending state during stationary charging. The evap-active
   flag (bit 7) is only meaningful in drive mode with the engine capable of running.

6. ~~**Stall event deep-dive — second evap drive, t=808–816s.**~~
   **RESOLVED (2026-03-05):** B0=0x91 constant throughout the entire stall window (t=795–830s).
   No transition at t=808.42 (stall start) or t=815.81 (restart). B0 holds at its evap-active
   value without interruption.
   **Conclusion: B0 tracks VCM intent, not physical engine state.** The flag is cleared only when
   the VCM deliberately declares the evap cycle complete — not when the engine physically stops for
   any involuntary reason (stall). This is consistent with the evap completion event where B0 clears
   ~6s BEFORE the engine stops (VCM decides first, engine follows).

---

## Phase 3 — VCU Cluster Timer Scan: 0x649 B3 (COMPLETE 2026-05-02)

**Logs analyzed:** `vtruxevapdrivelog4.log` + part2, `vtruxanotherevaplogpart1-3.log`
**Method:** Streamed all 5 logs, extracted VCU cluster frames (0x639–0x64B) to CSV (4.28M rows
total), then scanned every byte and 16-bit LE/BE pair for monotonic behavior in evap windows vs
control windows (M-mode, pre-engine, stall, post-evap).
**Script:** `vcu_cluster_extract.py` (extraction), `vcu_cluster_timer_analysis.py` (analysis)
**Artifacts:** `vcu_evap4_p1.csv`, `vcu_evap4_p2.csv`, `vcu_another_p1-3.csv`

### Finding: 0x649 B3 is the evap activity counter

**0x649 B3** is the only byte in the entire VCU cluster that is perfectly discriminated between
evap and all control windows:

| Window | B3 behavior | Notes |
|--------|------------|-------|
| Pre-engine (evap4_p1, t=0-431.7s) | 0x00, flat (uq=1) | Engine off, evap pending but not running |
| Engine run + evap (evap4_p1, t=431.7-1462s) | counts 0x00->0x63 (mono=1.00) | All 256 unique values used |
| Engine run + evap (another_p2, t=12.31-1386.8s) | counts 0x0D->0x00 wrapping (mono=1.00) | Wraps 0xFF->0x00 |
| Stall mid-evap (another_p2, t=808-816s) | 0xB1, flat (uq=1) | Pauses while engine is off |
| M-mode engine run (another_p2, t=1455.7-1669.9s) | 0x00, flat (uq=1) | **Evap already done; not counting** |
| Post-evap (another_p3, t=0-521s) | 0x00, flat (uq=1) | Evap complete, stays at 0x00 |

**evap_mono=1.00, ctrl_mono=0.00, delta=+1.00** — perfect discriminator.

### Behavior summary

- B3 is 0x00 whenever no evap cycle is pending or active
- B3 counts upward (wrapping 0xFF->0x00) while engine is running during an active evap cycle
- Counting pauses when the engine stops (stall, controlled off) — it holds at the current value
- Counting resumes when the engine restarts (cross-session continuity confirmed: p1 ends at 13, p2 starts at 13)
- B3 returns to 0x00 when the evap cycle completes

### Rate estimates

| Evap cycle | Duration | Counts | Rate |
|------------|---------|--------|------|
| evap4 (partial, log ended early) | ~1030s engine run | 99 counts (0x00->0x63) | ~0.096 c/s |
| another evap (complete cycle) | ~1374s engine run | 243 counts (0x0D->0x00 wrapping) | ~0.177 c/s |

Rate varies between cycles. To complete one full wrap (256 counts):
- At 0.177 c/s: ~1447s (~24 min engine-on time)
- At 0.096 c/s: ~2667s (~44 min engine-on time)

### Implication for M-mode / low-SoC engine-run timer reset

During the M-mode control window in this log, B3=0x00 because the evap cycle had already
completed. The counter only runs when an evap cycle is active AND the engine is on. For M-mode
to reset the 5-day timer, the evap cycle would need to be pending — if it is, B3 would count
during M-mode just as it does during automatic evap runs. The engine-on time needed is the same
regardless of how the engine was started: approximately 24-44 minutes at the observed rates.

### Full 0x649 byte map (as of 2026-05-02)

Bit-level scan across evap vs control (M-mode, pre-engine, post-evap) windows.

| Byte | Role | Notes |
|------|------|-------|
| B0 | Evap-active flag byte | Bit 7 SET = evap active; clears to 0x00 at completion (~6s before engine stop). Session-level: set at key-on based on VCM NVM state, not dynamic. |
| B1 | Sub-state / sequence counter | Increments by +1 in small steps (~30 per evap session). Not discriminating (also increments in M-mode). |
| B2[7:4] | **Free-running clock** | Increments by +0x10 per step regardless of engine state — runs during stall, M-mode, everything. Not evap-specific. |
| B2[3:0] | **Evap counter MSB** | Increments by 1 each time B3 wraps 0xFF->0x00. Frozen during stall. Zero in M-mode and post-evap. |
| B3 | **Evap counter LSB** | +1/step while engine is on during evap. Frozen during stall. Zero in M-mode and post-evap. |
| B4 | Evap-active flag byte | Bit 7 SET = evap active (0x83), cleared at completion (0x03/0x02). Also bit 0 discriminates. |
| B5 | Mode/stage indicator | 0x1B during evap run; transitions to 0x13 once during run (one-shot -8 step, stage flag); 0xFB in M-mode. Bits 7,6 clear during evap, SET in M-mode (delta -0.63/-0.57). |
| B6 | Infrequent flag | -8 steps occasionally; not strongly discriminating. |
| B7 | Mostly static | Occasional jumps between a few values; role unknown. |

### Evap counter: 12-bit value B2[3:0]:B3

The evap activity is tracked by a **12-bit counter** formed from B2's lower nibble (MSB) and the
full B3 byte (LSB):

```
evap_counter = (B2 & 0x0F) << 8 | B3
```

Properties:
- Zero (`0x000`) when no evap cycle is active
- Increments only when engine is on during an active evap cycle
- Frozen (holds value) during stall — B3 stops, B2 lower nibble stops
- B2 upper nibble is a separate free-running clock (+16/step) that is NOT part of this counter
- Cross-session continuity: counter survives log gaps (p1 ends at 0x00D, p2 starts at 0x00D)

**Observed completion values:**
- `another_p2` evap: 3 full B3 wraps + B3=0x85 at completion = `(3<<8)|0x85 = 0x385 = 901 counts`
- Rate is variable: starts ~0.1 c/s, ramps to peak ~1.0 c/s, then decreases — not a linear timer

### B4 as evap-active flag

0x649 B4 tracks the evap-active state:
- **0x83** = evap cycle active (engine running with evap pending)
- **0x03 / 0x02** = evap not active (completed or not pending)

B4 transitions from 0x83 to 0x03 at evap completion, simultaneous with B3 returning to 0x00 and
B0 clearing to 0x00. B4 was already identified in Phase 2D (two-window comparison); this confirms
it encodes an evap-active state separate from the timer counter in B3.

**B0 vs B4 comparison:** Both flag evap-active state, but with different encodings and different
timing characteristics. Full comparison pending investigation (see Outstanding Questions below).

### B1 + B2[7:4] counter hypothesis: NOT confirmed

B1 never wraps (0xFF→0x00) in another_p2 (full 2010s session), so the hypothesis that
B2[7:4] increments per B1 wrap cannot hold. B2[7:4] runs ~15x faster than B1 (969 vs 61 changes
in the same session). They are independent signals.

### B0 vs B4 evap flag: timing and encoding differences

Both bytes signal evap-active state, but they differ in origin and timing:

| Property | B0 | B4 |
|----------|----|----|
| Source | VCM NVM (loaded at key-on from flash) | VCM real-time CAN initialization |
| At key-on | Already set to evap-active value in first CAN frame | Briefly 0x03, then transitions to 0x83 within ~0.14s |
| Active encoding | Various values, bit 7 SET (0x91, 0x95, 0xBB, 0xC6) | 0x83 (bit 7 SET + bit 1 + bit 0) |
| Inactive encoding | 0x00 (post-completion), 0x04 or 0x2F (no evap session) | 0x02 or 0x03 (bit 1 or bits 1+0) |
| At evap completion | Clears to 0x00 directly | 0x83 -> 0xC3 (one frame) -> 0x03 (leads B0 by ~8-10ms) |
| Post-completion change | None | 0x03->0x02 appears ~57s after evap completion |
| Mid-session changes | Can change at engine start (0x90->0x91 in p1 at t=193s) | Stable until evap completes |

Key conclusions:
- B0 is the session-level NVM policy byte: the VCM writes it to flash at key-off and it is
  broadcast from the first frame at key-on. It encodes more state information than just evap-active.
- B4 is a real-time status flag initialized ~0.14s into the session. It leads B0 at completion,
  suggesting B4 is updated by the VCM's control loop while B0 is updated by a higher-level
  state machine (or DMA update that lags the control loop).
- The intermediate B4=0xC3 state at completion (one frame) suggests a momentary intermediate
  state where bit 6 is also set during the transition.
- The B4 0x03->0x02 transition ~57s after completion may mark a post-evap engine cooldown event.

### Generator overheat log characterization

**Log:** `vtruxgeneratoroverheattest.log` (2828s)
**B0 at start:** 0x95 (bit 7 SET = evap active); B4=0x82 (bit 7 SET)
**Evap counter at start:** 0x18D = 397 — the engine had already been running mid-evap-cycle before
this log started.
**Evap completes at:** t=764.8s (B0: 0x95->0x00; B4: 0x82->0xC2->0x02)
**Evap counter at completion:** ~0x358=856 (starting from 397, ~459 counts added during this log)

This log was initially described as "no evap expected" but the data shows an active evap cycle
already in progress. The starting counter value confirms the engine had already been running for
some time before the log started.

After evap completion (t>780s): B3=0x00 constant, evap counter=0x000. B1 restarts from 0x00 and
counts up (key-cycle boundary at t~1920s visible as B1/B2 reset to 0x00).

### Partstruck testdrive characterization

**Logs:** `vtrux_partstruck_testdrive.log` (743s) + `vtrux_partstruck_testdrive_part2.log` (339s)
**Context:** Parts truck "reawakened" after long idle; 12V disconnect/reconnect occurred.
**B0:** 0x2F (constant in p1, changes to 0x30 at t=260s in p2) — bit 7 CLEAR throughout = NO evap active
**B4:** 0x02 (constant both parts) — NO evap active
**B3:** 0x00 constant (evap counter = 0x000 throughout)

The parts truck had been idle for several months, so the 5-day evap timer was definitely expired.
Despite this, evap never activated. The most likely explanation is the generator inverter fuse was
pulled at first boot — see the section below on fuse-pull evap inhibition.
The B0 values 0x2F and 0x30 are new values not seen in evap-active sessions; both have bit 7 clear.
The change 0x2F→0x30 at p2 t=260s is NOT an evap flag change (B4 unchanged, B3=0x00).
B1 and B2 continue counting freely regardless of evap state (confirmed independent).

### Generator inverter fuse pull and evap inhibition

**Log:** `vtrux_no_gene_inv_fuse.log` (168s, main truck)
**B0 at start:** 0x4d (constant — bit 7 CLEAR = evap NOT active)
**B4:** 0x01 at start, transitions to 0x81 at t=0.143s (normal CAN init, not an evap flag)
**Evap counter at start:** 0x18e = 398 (frozen from a prior partial cycle in NVM)
**Evap counter at end:** 0x18e = 398 — **zero change across the entire 168-second log**

Generator activity (0x600 B0):
- t=0-15s: normal init sequence (0x00->0x22->0x26->0x24, all GEN_OFF)
- t=124.886s: 0x24->0x34 (GEN_ON flag) — VCM commanded engine start (M-mode attempt)
- t=142.997s: 0x34->0x20->0x00 (GEN_OFF) — VCM gave up
- 0x600 B3 (engine-running state counter) = 0x0c = 12 throughout the ENTIRE log, including
  during the 0x34 window. In normal logs B3 descends from 12 when the engine actually runs.
  B3 staying at 12 confirms the engine never actually started — the fuse prevented the
  generator from responding to the VCM's command. 0x600 B0 = 0x34 reflects VCM intent, not
  confirmed generator operation.

Shift sequence (0x1F5 B3/B5 from Bus 3 only — Bus 1 carries a different version of 0x1F5
that only ever shows transitional values and is not useful for gear state):

**Fuse pulled (t=0–98.778s):**
- t=30.021s: Drive (first clean reading)
- t=31.613s: M-mode — no start (~15s, back to Drive t=46.886s)
- t=48.357s: M-mode — no start (~10s, back to Drive t=58.555s)
- t=59.638s: M-mode — no start (~2s, gave up, back to Drive t=61.461s)
- t=61–98s: stayed in Drive

**t=98.778s: fuse reinserted** (0x054/0x470/0x471/0x479/0x482 all reappear within 0.1s)

**Post-reinsertion (t=98.778s–168.7s):**
- t=106.980s: M-mode — no start (~14s, back to Drive t=120.775s)
- t=121.926s: M-mode — engine starts at t=124.764s (~2.8s into shift)
- t=134.162s: Drive — engine stays on (behavioral indicator of evap active)
- Engine still running at log end (t=168.7s, B6=75 = ~1104 RPM above zero)

Key observation — **evap flag (B0 bit7) never set, evap counter frozen throughout:**
Despite the engine running from t=124.764s onward in a session where SoC=79.5% (<80% gate
met), B0 bit7 stayed clear and ec stayed frozen at 0x18e. The engine staying on in Drive
suggests evap was being attempted, but the CAN signaling is in an unusual state, possibly
because the VCM session started without the GENE MCU present and the mid-session reinsertion
does not restore normal evap flag behavior for the remainder of the session.
The evap counter not advancing is a consequence of B0 bit7 never being set, not an
independent data point — it is also consistent with normal M-mode engine-on behavior where
evap is not active (counter does not advance in those windows either).

**SoC in this log:** 79.5% (stable from t=1.8s onward). This is below the ~80% threshold
required for evap to start (VCM requires SoC < 80% before initiating an evap cycle, so the
battery has headroom to accept charge during the engine run). The SoC gate was satisfied in
this session — evap was eligible on that criterion.

**Hypothesis — fuse pull blocks evap initiation (during fuse-pulled window):**
With the fuse pulled (t=0–98.778s): three M-mode attempts, no engine start, SoC=79.5%
(<80% gate met). The GENE MCU was offline and the VCM could not start the engine at all
during this window — evap could not have run regardless of whether the VCM wanted it to.

After fuse reinsertion: engine eventually started and stayed on in Drive, suggesting evap
was active, but the CAN evap signals (B0, B4, ec) were in an unusual state for the rest of
the session. The mid-session reinsertion appears to leave the VCM's evap signaling in a
non-standard state for the remainder of the key cycle.

**Implication for parts truck:** The parts truck had a definitely-expired 5-day timer and
the fuse was pulled at first boot (before the VCM could initiate evap). In that session,
the engine likely couldn't start at all during the fuse-pulled window, and there was no
opportunity for evap to run. When the fuse was eventually reinserted (or the truck was
rebooted), the evap timer state may have been reset or the session was not long enough
for evap to complete.

To confirm causation directly, a log capturing the full sequence (key-on with fuse pulled,
fuse reinserted, evap completes) with known timer state would be needed.

### Parts truck fuse experiment (vtrux_partstruck_evapfuseexperiment.log)

**Log:** `vtrux_partstruck_evapfuseexperiment.log` (1131s, parts truck)
**Purpose:** Deliberate experiment — see sidecar `.txt` for full procedure.

**B0=0xdb (evap active, bit7=1) from frame 1. Never changes. ec=0x000 throughout.**

The NVM-backed evap flag (B0) survived every 12V disconnect, fuse pull, and HCU reset in
the experiment. Pulling the generator fuse did not reset the evap requirement.

Phase timeline (matched to sidecar notes):
- **t=0–201.5s** (Phase 1): fuse in, GENE MCU online. Evap active (B0=0xdb). Engine starts
  at t=147.82s, runs ~6s, shuts off due to isolation fault (0x600: GEN_ON t=147.94s,
  gen_off t=151.01s; B6 returns to zero at t=153.62s). ec stays 0x000 — engine ran too
  briefly for the counter to advance, or isolation fault killed it before purge began.
- **t=201.5s**: GENE MCU goes offline (fuse pulled).
- **t=215–444s** (Phase 2): 228s CAN silence — 12V disconnect to reset isolation fault.
- **t=444–512s** (Phase 3): VCM online, fuse still out. Precharge fail. Short 5.3s gap
  at t=443–449s. 0x600 init sequence at t=480–488s.
- **t=512–533s** (Phase 4): 20.4s gap — Via fusebox 12V disconnect to reset HCU.
- **t=533–933s** (Phase 5): Running with fuse out. B0=0xdb unchanged throughout.
  0x600 goes to 0x00 at t=804s (key-off).
- **t=933–952s** (Phase 6a): 18.9s gap — key off, waiting for HCU sleep.
- **t=1037–1084s** (Phase 6b): 47.2s gap — additional wait.
- **t=1085.46s** (Phase 7): GENE MCU reappears — fuse reinserted.
- **t=1093.69–1096.43s** (Phase 8): Engine starts (~3s), isolation fault kills it again.
  B6 peaks at ~B6=86 (~1280 RPM), then returns to zero. B0 still 0xdb at log end.

**Conclusion (confirmed by data):** The evap NVM flag (B0) is not reset by pulling the
generator fuse or by 12V disconnects. The experiment was also confounded by the isolation
fault repeatedly killing the engine before evap could run. Sidecar conclusion: "unable to
latch evap reset by pulling generator fuse."

### Log summary table

| Log | B0_start | B4_start | Evap active? | Evap counter start | Completion |
|-----|----------|----------|-------------|-------------------|-----------|
| evap4_p1 | 0xBB | 0x83 | YES | 0x000 | Not in log |
| evap4_p2 | 0xBB | 0x83 | YES (ends here) | ~0x17A | t=10.5s |
| another_p1 | 0x90 | 0x03 | YES (B4 sets t=0.14s) | ~0x000 | Not in log |
| another_p2 | 0x91 | 0x83 | YES | 0x00D | t=1386.8s |
| another_p3 | 0x00 | 0x02 | NO (complete) | 0x000 | - |
| gen_overheat | 0x95 | 0x82 | YES | 0x18D (mid-cycle) | t=764.8s |
| partstruck p1 | 0x2F | 0x02 | NO | 0x000 | - |
| partstruck p2 | 0x2F | 0x02 | NO | 0x000 | - |
| gen_on_off | 0x04 | 0x03 | NO | 0x000 | - |
| og_highway | 0xC6 | 0x03 | YES (B4 sets t=0.14s) | unknown | t=1223.3s |
| no_gene_inv_fuse | 0x4d | 0x81 | UNKNOWN (unusual state) | 0x18e (frozen; fuse pulled t=0-98.8s, reinserted then engine started; evap signals non-standard post-reinsertion) | - |
| partstruck_fuseexp | 0xdb | 0x82 | YES (flag set, engine killed by isolation fault) | 0x000 (never advanced — engine runs too short) | - |

---

## Confirmed Evap Completion Logs

Four logs are confirmed to contain an evap completion event (0x649 B0 bit 7 clears, engine stops ~6s later):

| Log | Date | Completion time in log |
|-----|------|----------------------|
| `oghighwaydrive.log` | 2025-08-21 | t=1223.3s |
| `vtruxevapdrivelog4part2.log` | 2026-02-25 | t=10.5s (cycle began in part1) |
| `vtruxanotherevaplogpart2.log` | 2026-03-04 | t=1386.8s |
| `vtruxgeneratoroverheattest.log` | 2026-03-18 | t=764.8s (cycle was mid-progress at log start) |

---

## Logs Within 5 Days of Each Evap Completion

Catalogued 2026-05-10 as part of investigating whether any signal counts up during the 5-day
idle period between evap clear cycles (candidate source for a display countdown timer).
Date of each primary log is from file mtime; Android log dates are from filename timestamps.
.txt sidecar files excluded.

### oghighwaydrive.log (2025-08-21)

| Offset | Log | Notes |
|--------|-----|-------|
| 0d | `debuglog_M0.log` through `debuglog_M8_T24.log` | All from same capture session as oghighwaydrive; oghighwaydrive.log is likely a renamed/merged form of debuglog_M0.log |
| +1d | `full-charge-then-fail.log` | Charge session |

No Android logs — auto-logger was not running at this time.

### vtruxevapdrivelog4part2.log (2026-02-25)

| Offset | Log | Notes |
|--------|-----|-------|
| -1d | `vtruxinterlocktest.log`, `vtruxinterlocktest2.log` | Interlock tests |
| 0d | `vtruxevapdrivelog.log`, `vtruxevapdrivelog2.log`, `vtruxevapdrivelog3.log`, `vtruxevapdrivelog4.log` | Earlier evap attempts that same day (evap1-3 were aborted/failed before evap4 succeeded) |
| 0d | `vtruxpartstruck.log`, `vtruxunplugpumpthenhvbatterylvconnector.log` | Parts truck and pump connector unplug test |
| +1d | `vtruxchargeafterevaplog-failed.log`, `vtruxchargeafterevaplogattempt2.log` | Charge attempts after evap |
| +1d | `vtruxcurrentlimitingtest.log`, `vtruxstartingat20.log` | Drive tests |
| +1d | `vtruxoverflowrecoverytest.log` through `vtruxoverflowrecoverytest10.log` | Overflow recovery tests |
| +1d | `vtruxunpluggingchargehandleendofcharge.log` | Charge test |
| +3d | `vtruxchargeafterucsc.log` | Charge |
| +4d | `vtruxchargeafterucsc2-4.log`, `vtruxchargeafterafterucscexport.log`, `vtruxexportafterucsc.log` | UCSC charge/export logs |

No Android logs. **This window (2026-02-25 to 2026-03-04) is the best candidate for finding a
5-day timer signal:** the next evap completion was 7 days later, so these logs span the full
5-day idle period. Note: 0x649 repurposes its byte fields in charge mode (Phase 2D), so the
known evap signals (B0, B3) are not interpretable in the charge logs. The drive logs
`vtruxcurrentlimitingtest.log` (+1d) and `vtruxstartingat20.log` (+1d) are the cleanest
candidates. The charge logs are still worth scanning for an unknown signal that may be
unaffected by charge vs. drive mode — a 5-day timer signal could live on a different ID
entirely — but the known evap bytes cannot be used as a reference in those logs.

### vtruxanotherevaplogpart2.log (2026-03-04)

| Offset | Log | Notes |
|--------|-----|-------|
| -4d | `vtruxchargeafterucsc.log` | Charge (also in window above) |
| -3d | `vtruxchargeafterucsc2-4.log`, `vtruxchargeafterafterucscexport.log`, `vtruxexportafterucsc.log` | UCSC charges/export |
| -1d | `vtruxexporttest.log`, `vtruxunpluggedpumpoverheattest.log` | Export and pump overheat tests |
| 0d | `vtruxanotherevaplogpart1.log`, `vtruxanotherevaplogpart3.log` | Evap drive parts 1 and 3 |
| 0d | `vtruxchargeafterexportchargetest-80pctcv.log`, `vtruxtrailerpokinglog.log` | Charge and trailer tests |
| +1d | `vtruxanotherevaplogpart4-batteryonly.log` | Post-evap battery-only drive |
| +1d | `vtruxscottsvalleydrive.log`, `vtruxextensioncabletest.log` | Drive and charge cable test |
| +1d | `vtruxchargeblueevse.log`, `vtruxchargemegearevse.log`, `vtruxchargemegearevse2.log`, `vtruxchargeafterscottsvalley.log`, `vtruxchargeafterscottsvalley2-16asetpoint.log` | Charge logs |
| +2d | `vtruxisolationtest.log`, `vtruxisolationtestrecovery.log`, `vtruxwoodwardbconnectordisconnected.log` | Isolation fault tests |

No Android logs.

### vtruxgeneratoroverheattest.log (2026-03-18)

| Offset | Log | Notes |
|--------|-----|-------|
| 0d | `vtruxdrivetrainconnectorunplug.log`, `vtruxgeneratorpumpunplug.log` | Drivetrain and pump unplug tests |
| +4d | `vtrux_20260322_165622_T0.log`, `vtrux_20260322_165622_T1.log` (primary + Android) | Overlapping primary/Android capture |
| +4d | `vtrux_20260322_171601_T0.log`, `vtrux_20260322_172146_T0.log`, `vtrux_20260322_173535_T0.log`, `vtrux_20260322_173541_T0.log` | Android auto-captured sessions from 2026-03-22 |
| +5d | ~50 Android auto-captured sessions from 2026-03-23 (`vtrux_20260323_*`) | Android logs from 2026-03-23 |

The large batch of Android logs on 2026-03-22/23 (+4/+5d) falls right at the edge of the
5-day window. These may capture the transition from post-evap-clear back to evap-pending.

---

## Open items

### Evap flag persistence mechanism (OPEN)

**Observation:** In `vtruxunplugpumpthenhvbatterylvconnector.log`, the evap pending flag (0x649 B0 bit7) was set at session start (B0=0xbb) and cleared at the next key-on (B0=0x1c) after the following sequence: PE pump CAN connector unplugged, key off, HV battery LV logic connector unplugged then reconnected, full 12V battery terminal disconnect/reconnect, key on.

**What we can rule out:**
- VCM volatile SRAM: ruled out — in `partstruck_fuseexp`, a fusebox 12V cut power-cycled the VCM (proven by the precharge/contactor fault clearing) but the evap flag (B0=0xdb) persisted through multiple such resets.
- BMS as storage: ruled out — known BMS messages (0x410, 0x411, 0x420, 0x430) carry no evap-related signals.
- GENE MCU as source: ruled out — flag persisted in `partstruck_fuseexp` through VCM power cycles with GENE offline the entire time.
- SoC as the evap scheduling gate: SoC is only a gate for engine start (engine won't fire if SoC > 80%), not for whether evap is pending. VCM tracks evap pending independently and uses it to reserve charge headroom below 100%.

**Remaining candidates:**
- VCM NVM (EEPROM/flash): flag survives power cycles, consistent with NVM. Unknown what caused the NVM write to clear in the unplugpump scenario.
- Something carried on the HV battery LV connector beyond BMS CAN traffic (hardwired signal, pilot line) that VCM consults at startup to determine evap state.

**Experiment needed to isolate:** Full 12V terminal disconnect (without touching the HV LV connector) followed by key-on — does the flag clear? If yes, the full terminal disconnect does something the fusebox cut doesn't. If no, the HV LV connector manipulation is the differentiator. This log is not controlled enough to distinguish the two — both actions occurred.

---

## Phase 4 — 5-Day Timer Signal Search (COMPLETE 2026-05-10)

**Goal:** Find a CAN signal that could power an "Evap Status" display indicator showing Clear / Pending / countdown timer for hours until next evap.

**Method:** Broad monotonic scan across three drive logs spanning the 5-day post-evap window (post_a=+1d, post_b=+1d, pre_next=+7d from the Feb 25 evap). Tested all signal widths per methodology: 8-bit, 16-bit LE/BE, 12-bit byte-aligned Moto/Intel, 12-bit nibble-split A/B. Phase 1 scanned within-log monotonicity; Phase 2 compared stable modal values across logs.
**Script:** `evap_5day_timer_scan.py`, `characterize_0x135.py`
**Output:** `evap_5day_timer_results.txt`, `characterize_0x135_results.txt`

### Finding: 0x135 B2 is the best available candidate — but not a workable standalone solution

**0x135** is a native Vehicle-bus chassis module message (not VCM — confirmed present after VCM B-connector disconnect in T3 test). B2 appears to function as a day counter that increments by 1 per calendar day, and the VCM fires evap when this counter has increased by 5 from the value at the previous evap completion.

#### Evidence

| Log | Date | B2 value | Notes |
|-----|------|----------|-------|
| `vtruxevapdrivelog4.log` | 2026-02-25 | 0x01 | Pre-completion, evap in progress |
| `vtruxevapdrivelog4part2.log` | 2026-02-25 | 0x01 | Evap completes at t=10.5s — no B2 change |
| `vtruxcurrentlimitingtest.log` | 2026-02-26 | 0x01 | +1d drive |
| `vtruxstartingat20.log` | 2026-02-26 | 0x01 | +1d drive |
| `vtruxexporttest.log` | ~2026-03-03 | 0x06 | ~+6d |
| `vtruxunpluggedpumpoverheattest.log` | ~2026-03-03 | 0x06 | ~+6d |
| `vtruxanotherevaplogpart1.log` | 2026-03-04 | 0x07 | +7d, evap pending (brief 0x01 startup artifact then 0x07) |
| `vtruxanotherevaplogpart2.log` | 2026-03-04 | 0x07 | 2nd evap completes at t=1386.8s — no B2 change |
| `vtruxanotherevaplogpart4-batteryonly.log` | 2026-03-05 | 0x08 | Starts at 0x07 then transitions to 0x08 — day boundary crossed mid-session |
| `vtruxscottsvalleydrive.log` | 2026-03-05 | 0x08 | +1d from 2nd evap |
| `vtruxgeneratoroverheattest.log` | 2026-03-18 | 0x0c (12) | 3rd evap completes at t=764.8s — no B2 change |

Key observations:
- B2 increments by 1 per calendar day. Mar 3=6, Mar 4=7, Mar 5=8 shows three consecutive days with consecutive values. The part4-batteryonly log actually captures the midnight rollover (starts 0x07, transitions to 0x08 mid-session).
- B2 does **not** reset or change at the evap completion moment. Both confirmed evap events show B2 constant throughout (before and after 0x649 B0 → 0x00).
- **The delta between successive evap events matches the 5-day rule:** 2nd evap at B2=7, 3rd evap at B2=12, delta=5. The VCM fires evap when B2 has increased by 5 from the previous evap's B2 value.
- The 1st-to-2nd delta is 6 (B2=1→7), one more than 5. This is likely because B2=1 was the pre-existing default when the first evap fired, not a freshly-reset counter — the threshold was met at B2=6 but the evap session was logged the following day at B2=7.

#### Why this is not a workable standalone solution

1. **No reset at evap completion.** B2 does not start from a known value after each evap. To compute days remaining you need to know B2 at the last evap completion. This requires cross-session state storage in the display app: detect the 0x649 B0 → 0x00 transition, record B2 at that moment, persist it, then compute `days_remaining = max(0, (B2_last_evap + 5) - B2_current)`.

2. **Counter resets unpredictably.** The counter appears to reset during certain power or module events (confirmed: VCM B-connector disconnect on 2026-03-06 dropped B2 back to 0x01). If the counter resets due to a routine hardware event, the stored reference becomes invalid and the countdown would read incorrectly.

3. **Not a direct display value.** B2 cannot be read directly as "days remaining" — it only becomes meaningful relative to a stored reference. Compare to 0x649 B3 (evap activity counter) which is a direct cycle-completion metric, or 0x649 B0 bit 7 which is a direct "evap active/pending" flag.

#### Secondary candidates ruled out

- **0x640 B0** (VCM): 0x15 = post-evap normal, 0x66 = evap pending. Confirms evap-pending state but is binary — no timer resolution.
- **0x649 B0, B4** (evap flags): already characterized. Binary state change at evap-pending, not a countdown.
- **0x395 B4/B5** (generator phase current): eliminated — the cross-log value difference reflects drive loading conditions, not a timer.
- Within-session monotonic signals (Phase 1): all strong hits were either the known evap activity counter (0x649 B3) or session odometers unrelated to the 5-day period.

#### Summary

**0x135 B2 is the best signal found for tracking the 5-day evap window**, but it requires the display app to detect evap completion events and persist a reference value across sessions. Without that infrastructure it cannot drive a countdown directly. The existing 0x649 B0 bit 7 flag remains the only clean binary signal for "evap pending."
</content>
