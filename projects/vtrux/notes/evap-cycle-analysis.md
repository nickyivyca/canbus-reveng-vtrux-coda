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
| Bus1 0x1A1 B1 | 0x04 → 0x00 | t=1388.060s | Unknown GM message (identity unconfirmed) |
| Bus2 0x1A1 B1 | 0x04 → 0x00 | t=1388.058s | Same message, VCM-forwarded to second bus |
| Bus1 0x4C1 B2 | 0x86 → 0x85 | t=1388.043s | 0x4C1 ECM engine status (EPRI confirmed) |
| Bus2 0x4C1 B2 | 0x86 → 0x85 | t=1388.040s | Same, forwarded |
| Bus3 0x600 B2+B3 | large jump | t=1388.555s | Already understood: B2-B3 sub-counter pair |

Remaining 9 candidates (0x370 B7, 0x410 B3, 0x596 B6, 0x589 B7, 0x0BE B4, 0xC0CA040 B3,
0x18FFD6B3 B0, and two others) are lower-priority: they are either BMS-sourced IDs that change
infrequently, or signals where the coincidence window is wide enough that noise/drift explains it.

#### 0x1A1 B1 — Ruled Out (Coincidental Pulse)

**Message identity:** 0x1A1 is an unidentified GM bus message, observed at 80 Hz, DLC=7, bridged by VCM to both GM buses.

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

**Known B1 states (from direct observation):**
- 0x10: engine off (initial cold start / before first run)
- 0x00: engine running (or post-run idle between pulses)
- 0x20: seen in first evap drive part 1 (different operating mode)
- 0x04/0x05/0x06/0x02/0x03: oscillating pulses during engine operation

**Conclusion:** 0x1A1 B1 is NOT an evap signal. The cluster scan result was coincidental.

#### 0x4C1 B2 — Ruled Out (Engine Coolant Temperature)

**Message identity:** 0x4C1 is the ECM engine status message (EPRI confirmed), faithfully bridged between both GM buses (byte-identical). B2 encodes engine coolant temperature — a continuous raw byte (scale 1.0, offset -40).

**Conclusion:** A single-count drop in coolant temperature (0x86→0x85) coinciding with the evap
completion window is coincidental. Engine temperature fluctuates ±1 count continuously. Ruled out.

#### Cluster Scan Conclusion

Both top candidates from the cluster scan have been ruled out after cross-validation:
- **0x1A1 B1:** oscillating sub-state counter during all engine operation; evap_done transition was a coincidental last pulse before the engine stopped
- **0x4C1 B2:** Engine coolant temperature single-count drop; coincidental

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
| Bus1 0x1F5 B3 | 0x04 (98.5%) | 0x09 (99.5%) | n/a | **Shift mode (Drive vs Manual)** |
| Bus1 0x1F5 B5 | 0x00 (100%) | 0x02 (99.5%) | n/a | Shift state byte |
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
