# EVAP Indicator Bug — Wrong Signal, and Missing PENDING State

**Status:** Diagnosed 2026-07-19. **Implemented 2026-07-21** on the bench PC — both asset DBC copies,
both manifest copies, and `LiveDisplayScreen.kt` updated; `:vtrux:assembleDebug` and
`:companion:assembleVtruxDebug` both build clean. Not yet verified against a log replay or on the
truck.

**Evidence:** `projects/vtrux/notes/evap-cycle-analysis.md` Phase 5.

> **Unaffected by the 2026-08-09 `0x63A` retraction and falsification (Phase 6 / Phase 7).** That
> work concerned `0x63A` B7 bit4, an interim "evap purge in progress" reading that was retracted and
> then falsified by counterexample. The app never used it: `0x63A`, `1594`, `GenInitState` and
> `vcm_evap_purging` appear nowhere in `vtrux/src`, `companion/src` or `display/src`. This fix rests
> solely on `0x649` (Phase 5) and stands unchanged.

---

## Symptom

On the 2026-07-19 drive the display showed `EVAP: COMPLETE` for the entire trip. Once SoC fell to
80% the truck started an evap purge cycle anyway. The indicator never changed.

## Root cause

Two independent defects stacked.

### 1. Wrong signal (the actual bug)

`vcm_evap_active` was defined as `0x649` **B0 bit 7**. That is not the evap-active flag.

A scan of all 1052 Android logger sessions (104 contain `0x649`, 17 recorded real purge activity)
gives:

| Indicator | Correct in purge sessions |
|-----------|--------------------------|
| `0x649` B0 bit 7 | **6 of 17 wrong** (five 2026-04-14 sessions, plus 2026-07-19) |
| `0x649` B4 bit 7 | **17 of 17 correct**, never set spuriously |

B0 is constant within a session but varies widely between sessions (`0x00`–`0xE2` observed). The
original identification generalized from five logs that all happened to have B0 above `0x80`, so the
bit-7 test was really asking "is this session's B0 value above 128?" — which correlated with evap by
luck. On 2026-07-19 B0 was `0x64` (100) and the luck ran out.

Why it had not been seen before: every purge since the display shipped (2026-05-12) followed a gap
of 17–28 days and had B0 well above 128. 2026-07-19 was the first cycle run only 5 days after the
previous completion.

**B0's actual meaning is unresolved.** Do not substitute another B0 bit; a counter interpretation
was tested and rejected (Phase 5).

### 2. PENDING was specified but never implemented

`notes/plans/vtrux-live-display-ui-spec.md:21-24` specifies three states — green COMPLETE, red
PENDING, cyan PURGE. `LiveDisplayScreen.kt:221-229` implements only two, and says so:

```kotlin
// EVAP: vcm_evap_active is binary. v1 distinguishes only PURGE (active)
// vs COMPLETE (inactive). Distinguishing PENDING from COMPLETE requires
// session-level state tracking and is deferred.
```

That deferral rested on the wrong signal model. With the correct signals it needs no session-level
state tracking at all — see below. Even after fixing defect 1, a two-state indicator would have
shown `PURGE` only after the engine started, and `COMPLETE` during the pending period before it.

---

## Fix

### Project DBC — already done

`projects/vtrux/vtrux-powertrain-experimental.dbc` (the source of truth) has been updated:

```
BO_ 1609 VCM_EvapControl_0649: 8 VCM
 SG_ vcm_evap_active : 39|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ vcm_evap_counter : 19|12@0+ (1,0) [0|4095] "" Vector__XXX

VAL_ 1609 vcm_evap_active 0 "not_pending" 1 "pending_or_purging";
```

`vcm_evap_active` moved from `7|1@1+` (B0 bit 7) to `39|1@1+` (B4 bit 7). `vcm_evap_counter` is new:
12-bit Motorola, B2 lower nibble = MSB, B3 = LSB.

Verified with cantools against real frames:

| Frame (from log) | Decodes to | Expected |
|---|---|---|
| `64 9A A0 00 83 0B 28 40` (0719 t=0) | active=1, counter=0 | PENDING |
| `64 F8 F1 DA 83 0B 10 00` (0719 mid-drive) | active=1, counter=474 | PURGE |
| `00 37 A0 00 03 33 40 40` (0610 completion) | active=0, counter=0 | COMPLETE |
| `13 5C B0 00 03 08 00 00` (0715 non-evap) | active=0, counter=0 | COMPLETE |

### App asset DBC — DONE (code verified 2026-08-09)

`vtrux/src/main/assets/live-display/dbcs/powertrain.dbc` is a separate copy, not a symlink (as is
`companion/src/vtrux/assets/...`, plus stale ones under `build/intermediates/`). Both source copies
now carry `SG_ vcm_evap_active : 39|1@1+` at line 98 and the `VAL_` table at line 144.

### `LiveDisplayScreen.kt` — DONE (code verified 2026-08-09)

The two-state block was replaced; the three-state logic below is live at lines 221-232. The three
spec'd states fall out of the two signals with no persistence:

| `vcm_evap_active` | `vcm_evap_counter` | State | Color |
|---|---|---|---|
| 1 | 0 | PENDING | blue `0xFF1565C0` (spec said red; changed to blue 2026-07-21) |
| 1 | > 0 | PURGE | cyan `0xFF00ACC1` |
| 0 | any | COMPLETE | green `0xFF2E7D32` |
| null | — | `—` | grey `0xFF424242` |

```kotlin
val evapActive = signals["vcm_evap_active"]?.toInt()
val evapCounter = signals["vcm_evap_counter"]?.toInt()
val (evapText, evapBg) = when {
    evapActive == null -> "—" to Color(0xFF424242)
    evapActive == 0 -> "COMPLETE" to Color(0xFF2E7D32)
    (evapCounter ?: 0) > 0 -> "PURGE" to Color(0xFF00ACC1)
    else -> "PENDING" to Color(0xFF1565C0)
}
```

Both signals live on `0x649`, so they arrive in the same frame and cannot be transiently
inconsistent. `evapCounter` is treated as 0 when absent so a missing counter degrades to PENDING
rather than to the grey unknown state.

### Manifest / subscription — DONE (code verified 2026-08-09)

Adding a signal to the DBC does not by itself put it on the wire; the manifest enumerates signals
explicitly, so the counter had to be added there too or `signals["vcm_evap_counter"]` would always
be null and the indicator would sit on PENDING for the whole purge. Both manifest copies
(`vtrux/src/main/assets/live-display/manifest.json` and `companion/src/vtrux/assets/...`) now
request `["vcm_evap_active", "vcm_evap_counter"]` at line 54.

---

## Verification

The 2026-07-19 session is the regression test — the old code shows COMPLETE for all of it.

> **Corrected 2026-08-09.** The table below previously claimed COMPLETE after t=2244.25s in
> `vtrux_20260719_164520`. That is wrong: `vcm_evap_active` is 1 in **all 226,607** `0x649` frames of
> that session — it never clears. The purge is still running when the log ends. The cycle completes
> in the *next* session, `vtrux_20260719_190019`. Both sessions are needed to exercise all three
> states.

Replay `../../CANLogs/VtruxLogs/vtrux_20260719_164520_T*.log` through `tools/can_display_server.py`
and expect:

| Window | Expected |
|--------|----------|
| t=0 → t=1469.5s | **PENDING** (blue) — `active=1, counter=0` |
| t=1469.5s → end of log (t=2270.8s) | **PURGE** (cyan) — counter climbs 1 → 536 |

COMPLETE is **not reachable** in that log. To exercise it, replay
`vtrux_20260719_190019_T*.log`, which resumes the same cycle:

| Window | Expected |
|--------|----------|
| t=0 → t=969.7s | **PURGE** (cyan) — counter resumes at 536, climbs to 901 |
| t=969.7s (19:16:29) onward | **COMPLETE** (green) — `active` 1 → 0, counter resets to 0 |

Note the counter **carries across the key cycle** (536 at the end of the first session, 536 at the
start of the second) and 901 is the terminal value for this cycle, matching the 901/901/856 terminal
values recorded below.

For a clean COMPLETE-only case, replay `vtrux_20260715_202222_T*` — should read COMPLETE throughout.

## Known limitation

`vcm_evap_counter` freezes during an engine stall and resumes on restart, so a paused purge keeps
reading PURGE rather than dropping back to PENDING. This is intended.

The counter cannot drive a progress bar: its terminal value varies per cycle (901, 901, 856
observed) and its rate ramps up then down. The deferred "evap-completion progress meter" in
`plans/vtrux-live-display-ui.md` remains infeasible for the same reason it always was.
