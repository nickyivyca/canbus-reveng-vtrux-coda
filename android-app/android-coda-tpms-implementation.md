# Coda Android App — Indirect TPMS Implementation

App-side implementation of the wheel-speed (indirect) TPMS. **Detection method, feasibility and
psi calibration are not here** — they live in
`../projects/coda/notes/indirect-tpms-feasibility.md`, and the algorithm and storage design in
`../projects/coda/notes/tpms-algorithm-spec.md` (`../projects/coda/notes/plans/tpms_app_algorithm.md`
is the working agenda, not a spec). This file covers only what the app does:
the settings UI, the handoff seam the detector plugs into, and the CAN transmit path.

**Status (2026-09-26):** persistent store, drive rows, GPS capture and the detector are built in
the `:tpms` module and match the algorithm session's Python exactly on the corpus. **All of it is a
prototype until tested in the car** (owner, 2026-09-26: "nothing is fully expected to work yet
until tested. ok to have prototypes in place"). The goal is to collect data; the detector's
settings are provisional and are retuned against the collected files.
**`coda-debug (28).apk` dropped 2026-09-26, the latest**: build 27 plus a deeper hardware report
(sensor, permission, camera and SIM checks); TPMS behaviour is the same as 27. Build 27 added the
`proc` tag on drive rows. Build 26 had the v24 filters, the fixes from
build 23's first day in the car, and the per-contrast sample floor on the window, the learning pool
and the fast path — see [On the car — build 24](#on-the-car--build-24).
Nothing transmits on any bus.

---

## Division of labour

| Owned here (UI/scaffolding session) | Owned by the algorithm session |
|---|---|
| Settings page, entry widgets, layout | `DEL`/`F_R`/`L_R` computation and filters (as spec + prototype) |
| `TpmsCalibrationStore` and its file implementation (since 2026-09-24) | The file format and epoch rules, in the spec and prototype |
| `TpmsEstimate` shape the UI renders | What goes in it, and when |
| CAN transmit mechanism and its interlocks | Whether/when to register a `0x600` slot |

The seam is `tpms/.../TpmsCalibration.kt`. Everything the detector needs to provide, and
everything the UI needs to show, is declared there and nowhere else.

**Doc ownership, agreed 2026-09-21.** Split by *file*, not by section: SeaDrive syncs whole files,
so two machines editing different sections of one file still collide. This file is written only
from the app side; the algorithm session owns
`../projects/coda/notes/tpms-algorithm-spec.md`, and this one never restates its content. Changes to either go by message to its owner.

---

## File layout

| File | Role |
|---|---|
| `coda/.../SettingsScreen.kt` | Page 3. Calibration entry (left) + detector output (right) |
| **`tpms/`** | **The `:tpms` module: all TPMS and GPS code. File-by-file table in `CanLoggerApps/tpms/README.md`** |
| `tpms/.../TpmsCalibration.kt` | **The handoff seam.** Entry/estimate types, store interface |
| `tpms/.../TpmsEpochStore.kt`, `FileTpmsCalibrationStore.kt` | The calibration files in `CodaLogs/tpms/` |
| `tpms/.../WheelRatioExtractor.kt`, `DriveRowProducer.kt`, `SegmentWatcher.kt` | Drive rows from closed log segments |
| `tpms/.../GpsRateAccumulator.kt`, `GpsSpeedService.kt` | GPS common-mode channel (speed only) |
| `tpms/.../TpmsDetector.kt` | The detector (port of the prototype's `run()`) |
| `tpms/.../HardwareReport.kt` | Head-unit hardware inventory into `CodaLogs/diag/` |
| `notes/artifacts/tpms_ratio_parity.py` | Generates the Python reference values for the extractor parity test |
| `notes/artifacts/tpms_detector_parity.py` | Generates the detector parity fixture from the prototype |
| `cancore/.../BusmasterWriter.kt`, `CanPipelineManager.kt`, `CanFrame.kt` | Log timing fix: first-frame origin, monotonic stamps, ordered emit |
| `cancore/src/test/.../BusmasterWriterTest.kt` | 7 tests for the log timing fix |
| `coda/.../CodaConstants.kt` | `DEFAULT_TIRE_PSI`, TPMS signal IDs, `B_CAN_EXCLUSIVE_IDS`, `TX_ALLOWED_IDS` |
| `coda/.../CodaApplication.kt` | Constructs the transmitter + bus resolver, runs the TX loop |
| `cancore/.../CanTransmitter.kt` | The transmit capability interface |
| `cancore/.../PeriodicTransmitter.kt` | Scheduler **and every safety interlock** |
| `cancore/.../GsUsbDevice.kt` | Bulk OUT endpoint + `send()` |
| `cancore/.../GsUsbFrame.kt` | `forTransmit()`, `isEcho`, echo cookies |
| `cancore/.../CanFrame.kt` | `isTx` flag |
| `cancore/src/test/.../PeriodicTransmitterTest.kt` | 17 tests: one per interlock, plus the echo-classification fail-safe |

---

## Settings page (page 3)

Added as a third page in the existing `HorizontalPager` in `MainActivity`. Two panes split down
the middle of the 1024x600 panel.

```
+---------------------------+---------------------------+
|  TPMS CALIBRATION         |  PRESSURE IMBALANCE       |
|  Last set <date> ...      |  Change since last cal... |
+-------------+-------------+-------------+-------------+
| FRONT LEFT  | FRONT RIGHT | FRONT LEFT  | FRONT RIGHT |
|   [ 42.0 ]  |   [ 42.0 ]  |    -0.4     |    +0.1     |
|   [-] [+]   |   [-] [+]   |             |             |
+-------------+-------------+-------------+-------------+
| REAR LEFT   | REAR RIGHT  | REAR LEFT   | REAR RIGHT  |
|   [ 42.0 ]  |   [ 42.0 ]  |    +0.2     |    -0.1     |
|   [-] [+]   |   [-] [+]   |             |             |
+-------------+-------------+-------------+-------------+
| AMBIENT     |             |  status line              |
|   [  --  ]  |   [ SET ]   |                           |
|   [-] [+]   |             |                           |
+-------------+-------------+---------------------------+
```

### Layout decisions

- **Both grids are the car seen from above** — front pair on top, left pair in the left column.
  Reading a value off the wrong corner is the easiest mistake available here. The estimate grid
  carries a third row holding only the status line, purely so its row heights match the entry
  grid and each corner sits opposite its own corner across the divider.
- **+/- is the primary input; the keyboard is opt-in.** The soft keyboard covers most of a 600 px
  panel. Tapping a number opens a numeric field for direct entry; otherwise it is never seen.
  Steps are **0.1 psi** and **0.5 °C**. Press-and-hold repeats after 400 ms, accelerating after
  10 repeats (~33 steps/s).
- **The four tyre boxes preload to `CodaConstants.DEFAULT_TIRE_PSI`; ambient starts blank.**
  Calibration normally happens right after filling to the placard figure, so preloading saves
  ~100 presses. Ambient staying blank is what keeps that safe: **SET is disabled until all five
  boxes have values**, so an untouched form can never be submitted — at least one real reading
  has to be entered before the four defaults can go anywhere.
- **Ambient is typed, never read from the bus.** `0x391` B3 `OPAirTemp` exists but the DBC records
  it as unreliable: reads ~+12 °F high with a varying +5..+20 °F error, so it is not
  offset-calibratable. Pre-filling from it would seed the calibration with a known-wrong value.
- **A null estimate renders as `--`, never `0.0`.** A missing reading that looked like zero would
  read as "this tyre is exactly on target", the opposite of the truth. Same rule the specs page
  already follows for absent signals.
- **The right-hand pane says IMBALANCE, not CHANGE, while the numbers are relative** — see below.

### Why the heading is "PRESSURE IMBALANCE"

The ratio discriminants cancel common mode exactly, so a corner's number is its deviation from the
other three, **not** its change since calibration. Those coincide only when the change is not
uniform.

Worked on this car's real measured pressures — 31 / 35 / 33 / 33 against a 42 placard, assuming a
correct calibration at 42 and then that state developing:

| Corner | Actual | Actually down | Panel shows |
|---|---|---|---|
| LF | 31 | 11 psi | **−2.7** (barely advisory) |
| RF | 35 | 7 psi | **+2.7** |
| LR | 33 | 9 psi | **0.0** |
| RR | 33 | 9 psi | **0.0** |

Under a "CHANGE" heading the RF cell asserts that a tyre seven psi down has gone **up**, and the
rear pair assert that nine psi down is no change at all. The worst tyre in the car scrapes past
ADVISE and never reaches WARN.

The numbers are correct as imbalance and false as change, so **the heading is what gives** — the fix
is framing, not arithmetic. The subtitle then carries the blind spot explicitly ("a uniform loss on
all four reads zero"), because no per-corner number can express it. Both flip to absolute language
the moment any corner carries `absolutePsi`.

**Two distinct common-mode hazards**, and only the first is fixable by wording:

1. *Calibrating at already-low pressures.* The app cannot check what it is told, so it records
   under-inflation as the reference and only ever reports divergence **from** soft. Addressed by the
   SET caption, "Inflate to spec first — this becomes the reference".
2. *A uniform leak after a correct calibration.* The table above. No wording helps; only an absolute
   reference does, which is what the GPS common-mode channel is for.

### Preload pressure — `DEFAULT_TIRE_PSI = 42.0`

Single constant in `CodaConstants`, used both as the preload and as the re-seed value if a box is
cleared. Change that one line to change the whole page. Preloading from the last saved calibration
was offered and **declined** — the constant applies every time.

**Two sources disagree, and neither is a reading of this car's doorjamb.** Decided by the owner
2026-09-21 with all three figures in front of him:

| Source | Figure | What it actually is |
|---|---|---|
| Factory service manual, RCU DTC repair step | **42 psi** | "Repair or set to 42psi", five occurrences in the factory manual (internal-only) |
| Owner's gauge, 2026-09-20 | FL 31, FR 35, LR 33, RR 33 | Measured, but mid-leak-cycle |

A rival figure of 33 psi circulated briefly — it appeared in the feasibility doc's sensitivity
section, used in a "25 % loss from a 33 psi placard" calculation and never cited to a placard
reading. It has since been **corrected to 42 there**, so 42 is now the only figure in circulation
and no measured result moved (the sensitivity numbers are all differential and never touch the
placard).

What makes 42 the manual's nominal figure rather than one instruction's number is that three
independent thresholds elsewhere in it are exact multiples: **33.6** psi (RCU DTC low) = 0.80x,
**35.7** psi (IPK lamp-on) = 0.85x, **50.4** psi (RCU DTC high) = 1.20x.

**The tension is unresolved:** against a 42 placard, three of the four measured tyres sit below the
factory 33.6 psi DTC low limit — LF 31, LR 33 and RR 33 below it, RF 35 above — and all four are
between 16.7 % and 26.2 % under-inflated. A live RCU would therefore have been setting a
low-pressure DTC on three corners, so the dead-sensor lamp has been masking a real condition rather
than merely being uninformative. Confirm against the actual doorjamb — a preloaded value is the one
that gets submitted unchanged.

### Three operations, not one — SET / UNDO / AMEND

A calibration record does **two independent jobs**, and only one of them is load-bearing for
detection:

1. **Event marker** — "the pressures were just set, and this is the reference from here". Anchors the `DEL` baseline
   and is the thing that must never be re-learned automatically.
2. **Pressure values** — four psi and a temperature. Used *only* to turn relative deltas into
   absolute pressures. They never feed the baseline.

Separating them gives three operations instead of one, and makes both recovery paths cheap:

| | Asserts | Available | Costs |
|---|---|---|---|
| **SET** | (1) and (2) — opens a new epoch | always | the learning period, correctly |
| **UNDO** | withdraws (1) | while the current epoch has recorded **no qualifying drive** | nothing |
| **AMEND** | corrects (2) only | always, including a month and many drives later | nothing |

**UNDO answers "I bumped SET and I'm not going out to gauge four tyres."** A corrective SET does
not help there — it opens a *third* epoch and still drops back to `LEARNING`, so the stray press
still costs everything. Undo has to make the accidental calibration not have happened: discard its
epoch, reinstate the previous epoch's frozen baseline and accumulated drives. `undoLast()` must
restore the epoch, **not** re-apply the old numbers via `set()`, which would look identical in the
UI and be useless.

**AMEND answers "I typed 32 instead of 35."** A mistyped number is not a bad calibration, it is a
bad annotation on a good one, so it needs no new epoch and costs no learning — which is exactly why
it stays available indefinitely.

Implementation notes agreed with the algorithm session. *The three bullets below describe the
file-per-epoch store of builds 22-28. Since build 29 the store is immutable fragments: UNDO writes
an `epoch_void` tombstone instead of deleting, AMEND writes a new `_full` fragment, and the active
epoch is the newest calibration by its name key, read from content -- see
[Storage and sync](#storage-and-sync--immutable-fragments-and-what-the-server-may-do-with-them).
The no-archive rule and the calibration-as-first-record rule still hold.*

- **There is no archive step at all.** Settled by the owner: one file per calibration, each SET
  creates a new one, old files simply stay in `CodaLogs/tpms/`, and the active epoch is the newest.
  Simpler than the lazy-archive scheme this replaced, and it makes UNDO unambiguously a file
  delete — nothing is ever moved, so there is nothing to put back.
- **Naming carries the ordering.** Files are `tpms_<YYYYMMDDTHHMM>.jsonl`, so lexical order is
  chronological order and "the active epoch" is just the name that sorts last. Any future change to
  the naming scheme has to preserve that property — it is what makes "newest" computable without
  reading the files.
- **AMEND appends** a `calibration_amend` record rather than rewriting the calibration line, with
  the reader taking the last one as authoritative. Keeps the file strictly append-only — which is
  what makes a truncated final line from a mid-upload safe — and preserves what was originally
  entered.

#### UI

UNDO sits in the left-pane header beside the "Last set …" line it undoes, and exists only while the
store reports `undoTarget != null`. It is **arm-then-confirm**: the first tap arms it and names the
calibration it would restore, a second tap within 5 s commits, and it disarms itself otherwise. A
one-tap undo would have the same failure mode as the SET it is rescuing, and undoing a *good*
calibration is not itself recoverable without gauging four tyres.

The boxes keep their values after a SET, so re-entry is never needed to correct one.

**AMEND is defined in the store interface but has no UI control yet** — SET currently covers the
retype case at the cost of a new epoch.

#### `amend()` takes loose values, not a `TpmsCalibrationEntry`

Deliberate, and the reason is worth keeping: an entry carries `setAtMs`, so an amend that accepted
one could move the epoch's timestamp and silently become a `set()` — invisible in the UI, and the
same class of trap as reimplementing `undoLast()` via `set()`.

This is not hypothetical. The interface was first written as `amend(entry: TpmsCalibrationEntry)`
with the rule in the KDoc, and the in-memory store immediately broke that rule two lines from where
SET builds an entry with `System.currentTimeMillis()`. Documenting the rule did not prevent it;
making the timestamp unrepresentable did. The amendment *record* may carry its own audit timestamp
— only the calibration's must not move.

Matches `tpms_app_prototype.py`'s `amend(psi, temp_c, note)`, which takes no timestamp for the same
reason.

#### Checking an implementation against the reference

`../projects/coda/notes/artifacts/tpms_app_prototype.py` is the executable contract — its phase 5
walks the accidental-SET case against 40 real drives and asserts history-intact as a boolean rather
than printing numbers to eyeball. Three things there are easy to get subtly wrong:

- `undoTarget` must be null in **two** distinct cases: a qualifying drive has landed in the current
  epoch, *or* there is no previous epoch to land on.
- `undoLast()` is a **delete, not a restore** — nothing is ever archived or moved, so the previous
  epoch is simply still there. An implementation that finds itself restoring something has
  misunderstood the storage model.
- `amend()` must touch only the pressures and temperature.

---

## The handoff seam — `TpmsCalibration.kt`

```kotlin
enum class Corner(val label: String) { LF, RF, LR, RR }

data class TpmsCalibrationEntry(lfPsi, rfPsi, lrPsi, rrPsi, ambientC, setAtMs) {
    fun psi(corner: Corner): Float
    companion object { fun of(psi: Map<Corner, Float>, ambientC: Float, setAtMs: Long) }
}

enum class TpmsState { LEARNING, OK, ADVISE, WARN, STALE }

data class TpmsCornerEstimate(deltaPsi: Float?, absolutePsi: Float?)
data class TpmsEstimate(corners: Map<Corner, TpmsCornerEstimate>, state, detail, updatedAtMs) {
    operator fun get(corner: Corner): TpmsCornerEstimate   // absent key -> absent reading
}

interface TpmsCalibrationStore {
    val lastEntry: StateFlow<TpmsCalibrationEntry?>
    val undoTarget: StateFlow<TpmsCalibrationEntry?>
    val estimate: StateFlow<TpmsEstimate>
    fun set(entry: TpmsCalibrationEntry)
    fun undoLast()
    fun amend(psi: Map<Corner, Float>, ambientC: Float)
}
```

#### Everything per-corner is keyed, never positional

`TpmsEstimate` held four positional `TpmsCornerEstimate` fields, and `amend()` took four positional
floats. Both were transposable at a construction site: it compiles, the numbers stay entirely
plausible, and **the consequence is the driver inflating the wrong tyre** on the strength of a
confident display. The car-shaped grid guards against misreading a corner on screen; nothing
guarded against the data arriving pre-swapped, which no amount of layout can catch.

Now keyed by [`Corner`], which also carries the display label — so a cell names its corner exactly
once and the heading cannot disagree with the value beneath it. The same treatment is applied to the
entry side, where a transposition would be worse still: it poisons the baseline for two corners at
once rather than merely misreporting them.

An absent key renders as absent rather than throwing, so a partially-populated map degrades to
dashes instead of taking down the settings page.

**The five states and their meanings are the algorithm session's specification** — do not redefine
them here.

`STALE` is not a mild state: an unannounced fill was detected, the frozen baseline no longer
describes the tyres, and every corner number computed against it is meaningless until the user
recalibrates. An earlier version of this file used "stale" for the benign "no qualifying drive
recently", which would have rendered a recalibrate-now condition as soft grey text. That benign
case is now derived from the estimate's age rather than being a state of its own.

Two UI consequences, both deliberate:

- **`STALE` suppresses all four numbers** to `--`. They are not merely uncertain, they are
  meaningless, and a precise meaningless number is worse than none.
- **`STALE` takes a colour from off the OK/ADVISE/WARN ladder** (blue, chip reads `RECALIBRATE`).
  It is not a worse pressure reading, it is a statement that the readings are invalid. A hotter red
  would file it under "tyre problem" and point the user at the wrong action.

Notes for whoever implements the real store:

- **`set()` means "the tyres are correct as of now".** It should reset the learned baseline, not
  average into it. This is the explicit, user-initiated learn event the method requires: the leak
  is slow and continuous (0.051 psi/day), so any scheme that quietly re-learns from recent drives
  tracks the leak and reports nothing wrong, forever.
- **Each corner carries both `deltaPsi` and a nullable `absolutePsi`** rather than a global
  relative/absolute mode flag. `absolutePsi = calibrationPsi + deltaPsi + commonModePsi`, and
  `commonModePsi` is null today because the ratio discriminants cancel common mode by construction.
  When the GPS common-mode channel lands, `absolutePsi` starts being non-null and the same four
  cells begin showing absolute pressure **with no UI change and no cutover**. The cell prefers
  `absolutePsi` when present; the pane heading follows the data (`PRESSURE IMBALANCE` vs
  `ESTIMATED PRESSURE`) and relative values render with an explicit sign. That labelling is
  load-bearing: a relative number read as an absolute one is wrong by roughly the whole placard
  pressure.
- **One decimal place, never two.** Precision is about 0.7 psi 1 sigma per corner from a single
  qualifying drive, 0.3 from a five-drive window.
- **`detail` is free text** so the algorithm can explain itself ("312 / 800 samples") without this
  file modelling a state machine it does not own.
- **The store is `FileTpmsCalibrationStore`**, owned by `CodaApplication` (process lifetime, so
  drive rows can land without a UI) and attached with `CodaViewModel.useTpmsStore()` before the UI
  composes. The in-memory stub that preceded it was deleted on 2026-09-24 rather than kept as a
  fallback, so nothing can be left wired to a store that forgets. See
  [Persistent calibration store](#persistent-calibration-store).

---

## The `:tpms` module — independent of every other app

Owner, 2026-09-24: *"the gps should be part of the tpms module which should be an independent
module, and not just a disabled part of another module that still ends up on vtrux"*.

So all TPMS and GPS code is its own Android library module, `CanLoggerApps/tpms/`
(`com.reverseit.tpms`). **Only `:coda` depends on it.**
- **It depends on `:cancore`, never the reverse**, and not on any app. The host `Application`
  implements `TpmsHost` (so `GpsSpeedService` can find the accumulator) and points `TpmsLog.sink`
  at its own logger.
- **The location permissions and `GpsSpeedService` are declared in the module's manifest**, so
  they merge only into apps that include it.
- **No TPMS hook in `:cancore`.** An earlier `CanLoggingService.onSegmentClosed` callback (null by
  default) was removed. `SegmentWatcher` instead polls the already-public
  `CanLoggingService.currentSegmentName`. The service closes a file before changing that name, so a
  change means the previous segment is complete.
- **Verified by inspecting the APKs:** `vtrux-debug.apk` has no `com/reverseit/tpms` classes and
  no location permission. `coda-debug.apk` has both, plus the service.

What remains in `:cancore` from this work is general-purpose:
- the log timing fix, which applies to every app by intent;
- the CAN transmit path (`CanTransmitter`, `PeriodicTransmitter`, `GsUsbDevice.send`), built for
  the `0x600` lamp idea but not TPMS-specific, with no slots registered in any app. **Stays in
  `:cancore`, wired but unused** (owner, 2026-09-24: *"Vtrux may have a case for transmit path
  later, leave it wired but unused."*).

---

## Persistent calibration store

Built 2026-09-24 (plan `notes/plans/coda-tpms-gps.md` Step 2). The format and epoch rules are the
algorithm session's (spec sections 4-5, prototype `EpochStore`); this section records how the app
implements them and where it had to go further.

- **`TpmsEpochStore`** is synchronous and Android-free, so it runs under plain JVM tests (with
  `org.json:json` as a test-only dependency, because `android.jar`'s `org.json` is a stub there).
  **`FileTpmsCalibrationStore`** runs every operation on one background thread in call order, so
  SET, UNDO and a drive row from the logging side are ordered without locks, and republishes the
  flows **from disk** after each one. The page therefore always shows what is on disk.
- **A file's role comes from its first record, never its name.** `calibration`-first = an epoch;
  `precalibration`-first = drives recorded before any calibration existed. Anything else is ignored.
- **Drive rows before the first SET** go to a precalibration file (named
  `tpms_00000000T000000.jsonl` only so it sorts first). It is never an epoch, never active, never an
  undo target. After the first SET, rows go to the active epoch.
- **UNDO is withdrawn once a *session* qualifies**, with its 5-minute rows pooled by the log-name
  prefix before `_T<n>.log`. Three 300-sample segments of one drive qualify, even though no single row does.
- **Power-cut safe.** The head unit loses power with the ignition.
  - Every write is `fsync`ed.
  - A new epoch is written to `.tmp` and renamed, so a half-written file never becomes active.
  - The reader drops unparseable lines and counts them.
  - Before appending, the writer starts a fresh line if the file does not end in `\n`, so a
    cut-off line cannot swallow the next record.
- **The file name is an ordering key; the record's `ts` is data.** The name is pushed to one second
  past the newest epoch when the clock is behind it (unsynced head-unit clock) or two SETs land in one
  second. Without that, SET would write a file that is immediately not active. `ts` stays the
  wall-clock time of the press, and `name_ts` records the name when the two differ. Agreed with the
  algorithm session, which notes nothing in the detector is time-based.
- **Numbers are written as entered** (`41.9`, not `41.900001525878906`; whole values as `42`).
- **A failed operation is shown on page 3** in red, in place of the "Last set" line. That line is
  read back from disk, so after a failed SET it would otherwise still name the old calibration with
  nothing to say the SET had not saved. Not exercised on the AVD (the folder could not be made to
  fail there).

Five places where the prototype disagreed with this were reported to the algorithm session, and
it fixed all five with assertions in its phase 6:
- role by name
- undo qualifying per row
- reader raising on a truncated line
- a stale "archive lazily" comment
- the name/clock conflation

---

## Drive rows

Built 2026-09-24 (plan Step 3). One row per closed 5-minute log segment, appended to the active
epoch (or the precalibration file), per spec section 4.

- **Computed by re-reading the closed log** with `WheelRatioExtractor`, a numerically faithful port
  of `extract_one` in `../projects/coda/notes/artifacts/tpms_wheel_ratio_trend.py`. Re-reading
  the file gives the Kotlin byte-for-byte the input the Python reads, which is what makes the parity
  test meaningful. It takes ~0.4 s per 37 MB segment on a desktop JVM and 4-8 s on the AVD, on a
  low-priority background thread.
- **Exact parity** on `coda_20260618_195906` (4 segments) and `coda_20260618_185031` (6): n identical
  (11018, 10749), ratio means within 1e-13, sds within 1e-12.
- **Filters changed in v24** (spec section 1, owner approved 2026-09-26; details in
  [On the car — build 24](#on-the-car--build-24)): torque cap per contrast (40 Nm, F/R 20 Nm),
  steadiness 2%, steering centre from samples above 60 km/h. The exact-parity figures below are for
  the pre-v24 filters, which `WheelRatioExtractor.Filters.LEGACY` keeps for that test. The v24 rule
  set was checked by `ExtractorV24ReferenceTest` until 2026-09-27, when D CAN pinning moved its
  references (they came from the withdrawn frame-count bus pick); see
  [Spec 8a handoff](#spec-8a-handoff--d-can-pinning-put-and-reject-2026-09-27).
- **Rows are per segment, pooled per session at ingest** (agreed with the algorithm session).
  Pooled against the Python's per-session values, DEL differs by +/-5.6e-6 (about 0.05 psi, ~18x under
  the 0.00010 between-drive floor) and n by -62 / +317. The difference comes from the steering
  centre, which is the **running median of the session so far**, not the whole session's median.
  `SteeringCentre` keeps it exactly, from a histogram of raw counts. Each row stores `steer_centre`
  and `steer_n`. A segment arriving out of sequence (process restart, catch-up) re-reads the
  session's earlier segments to rebuild the centre.
- **Every segment gets a row**, including n = 0 (ratios null). The sample floor is a detector
  setting.
- **Temperatures:** five channels chosen by the algorithm session (FrontInletAirTemp,
  Cell_T_avg, RearInletAirTemp, OPAirTemp, EvapAirOffTemp). Each is stored as a whole-segment
  median on the channel with the most frames of that id, with `valid_frac` and `n`. Not pinned by
  anchors like the ratios: these are B CAN ids and no B CAN anchor set is settled yet. Byte positions and decode are checked
  against `CODA-B-CAN.dbc` with `DbcDecoder` in a test.
  - **Excluded as invalid:** `0x80` on all five, `0x00`/`0x33` on `Cell_T_avg` (per the DBC), and
    anything outside -40..+90 C. `0x80` is also a genuine 0 C, noted in code for colder climates.
  - **The rule:** drop values that are not measurements; never drop measurements judged
    unrepresentative. The FrontInlet < Cell_T_avg ambient gate is applied at ingest, never
    written.
- **Catch-up on start** covers segments that closed while the process was not running, e.g. a
  power-down before the last row was written. It only considers segments newer than the newest
  recorded one, so a first install does not backfill history. **From v24**, when nothing is
  recorded yet but an epoch exists, it takes segments last modified at or after the SET instead
  (before, it did nothing, and build 23's first epoch could not self-heal).
- **Parser parity quirk:** negative-tick lines (see the logger fix below) are rejected exactly as
  `canre`'s `\d{4}` regex rejects them, and each file's time origin is its first *valid* line.
- **Decode, as of 2026-09-26** (all mirrored in the Python `read_frames`, so parity still holds):
  - Wheel words are the 14-bit count, `word & 0x3FFF` (the DBC narrowed them to 14 bits on
    2026-09-25; on the wire the top two bits are always `0b11`, so this equals the old
    `word - 0xC000`).
  - **Stuck-wheel guard:** a `0x200`/`0x208` frame with either wheel word at `0x3FFF` (the ESC's
    own invalid value) is dropped. Never seen on this car.
  - **Brake:** `BrakePressure` is 12 bits with `BrakePressure_Valid` at bit 20. An invalid reading
    now counts as braking, encoded 1.0 so it fails the `<= 0` gate by the smallest margin. The old
    `raw16 - 4096` read the valid bit as part of the value and called an invalid frame brakes
    off (12 of 1.35 million frames on the corpus). Found by this session, fixed on both sides.
  - The live GPS pairing uses the same three decodes (`WheelRatioExtractor.wheel`, `stuckWheel`,
    `brake`).
- **Void marker (owner's rule, 2026-09-26: "All TPMS data when ESC sensors are problematic is
  void").** A segment is void if its ESC bus carries `SubFrameID 0x14` (ABSFault, what the parts
  car sends) or any wheel word at `0x3FFF`. The row records why, and the ratios are still stored.
  - **Counted only on buses that also carry `0x208`.** C CAN has an unrelated message on ID
    `0x200` whose B0 spans ~0x07-0x1B, which includes 0x14 (15,113 frames corpus-wide). An
    unscoped count would void healthy drives.
  - **`0x1E`/`0x1C` and `0x20` never void.** `0x1E` then `0x1C` is a fixed ~4 s pair when the ESC
    starts at car power-up; `0x20` is a ~1.5 s burst that can recur. A rule keyed on "SubFrameID
    != 0" would void every drive in the corpus.
  - The per-sample `SubFrameID == 0` gate stays as well.
- **Verified on the AVD** through catch-up with two real logs: identical rows to the JVM run. The
  live close detection (`SegmentWatcher`) needs a dongle, so the first car drive is its test: rows
  should appear in `CodaLogs/tpms/`.

Row shape:
- `type`, `schema`, `ts` (segment start, from the log header), `log`
- `n` (the wide count: sample floor and fast path), `dur_s`, `kmh_med`
- `steer_centre`, `steer_centre_src` (`"fast"`, `"all"`, or null without steering; v24),
  `steer_n`, `steer_n_fast` (v24; both cumulative over the session so far)
- `ratios`: `{DEL, FR, LR_, LFRF, LRRR: {mean, sd, n}}`. `n` per ratio from v24; F/R's is smaller
  (20 Nm cap), and its mean and sd are null when its n is 0.
- `torque_abs_mean`, `torque_abs_sd`: |torque| over the wide samples; null without `0x1C0` (v24)
- `band_kmh` (10) and `ratio_bands`: `{"<lower edge>": {<ratio>: {n, sum, sumsq}}}`, each ratio
  over its own samples, empty bands omitted (v24). The detector stays pooled for now.
- `temps`: `{<name>: {median, valid_frac, n}}`
- `gps`: see [GPS capture](#gps-capture-common-mode-channel); null when GPS was not running
- `void`: null, or `["esc_fault"]`, `["wheel_stuck"]` or both. Regenerable from the log.

### Proc 3 — 20 Nm on every contrast (build 29)

Owner, 2026-09-26: "yes do it, don't want false positives". `WheelRatioExtractor.Filters.PROC3`
(20 Nm on every contrast, 2 % steadiness, fast centre) is now the default, and rows carry
`proc: 3`. `Filters.V24` is kept for the parity tests.

- **Why** (algorithm session's corpus figures): the 6 psi fast-path false-alarm rate goes from
  1.03 % to none, and sensitivity from 0.000092 to 0.000113 per psi, at a cost of 16 drives of 188.
  Samples per drive fall a lot (5019 -> 1706 on `coda_20260926_155726`, 8034 -> 4307 on
  `coda_20260926_181156`; median retention 0.49), **but learning does not slow down**: the 2400
  learning floor is pooled over the learning drives, so K = 3 drives is what binds under both rule
  sets (median and worst 3), and qualifying days go from one every 2.63 to 2.73 days. The floors
  stay as they are (algorithm session's ruling: lowering them would give back the sensitivity).
- **Why torque, corrected the same day.** F/R does rise smoothly with drive torque (front-wheel
  creep; the Coda is front-wheel drive). DEL, binned by instantaneous torque, is essentially flat,
  and L/R is inconsistent between drives, so the older "+0.00020 over 0-40 Nm for L/R" was a single
  drive. On DEL the cap works as a proxy for the car being driven hard (acceleration, load
  transfer, cornering), not by removing slip.
- **Mixing in the live epoch: no re-SET** (algorithm session's ruling, measured on the epoch's own
  drives). The 40 -> 20 Nm change moves DEL by -0.000066 on both of them, about -0.25 to -0.49 psi
  on LF and the mirror on RF. The corpus mean has the opposite sign, so the offset depends on the
  drive and is not a constant. If the baseline is still learning, build 29's rows join the pool and
  the offset is diluted. The store copy in the library (2026-09-26) shows 2 of the 3 learning drives
  (pooled n 8806, already past the 2400 floor), so the third drive -- the first proc 3 one --
  completes learning. Pool shares 7.7 % proc 1, 63.9 % proc 2, 28.4 % proc 3, giving an expected
  fixed bias of about 0.16-0.31 psi on each front corner: no re-SET needed, one worth doing at the
  next real inflation.
- **Cross-check:** proc 1 and proc 3 share the 20 Nm cap, and on `coda_20260926_155726` they agree
  to 7e-6 DEL (0.06 psi), while proc 2 sits +0.000072 away. Two offsets measured by different
  routes cancel, which is what they must do if the cap is what moves DEL. Asserted in
  `ExtractorProc3ReferenceTest`.
- **The GPS block's strict channel stays at 40 Nm**, deliberately (algorithm session's ruling). It
  pairs GPS with the undriven rear pair, it is collect-only, and strict vs loose exists to measure
  the filter trade.
- **Traction control** arrives as `0x200` SubFrameID `0x20`, so the `SubFrameID == 0` gate already
  excludes it. That is a side effect of a gate written for another purpose, now recorded on the gate.
- **Checked:** `ExtractorProc3ReferenceTest` matches the algorithm session's reference n, DEL, F/R
  and L/R for both live-epoch sessions (7 cases), F/R is identical to v24's, and n equals v24's F/R n.

---

## GPS capture (common-mode channel)

Built 2026-09-24 (plan Step 4), approved by the owner the same day. It collects only; nothing on
screen uses it for pressure yet. The block format is in spec section 7, which the algorithm
session rewrote to match the block as built.

**Privacy (owner rule): no absolute position; otherwise only what GPS-TPMS needs.**
- `GpsSpeedService` reads exactly fix time, speed, speed accuracy, altitude and vertical accuracy
  from each `Location`. It never reads latitude or longitude, never logs the `Location` (its
  `toString()` contains coordinates), and never keeps one.
- Altitude is used transiently, for grade over a ~10 s baseline.
- A unit test walks every stored GPS block and fails on any key or string outside the allowed list.

**What each drive row's `gps` block holds** (null when GPS was not running, including every
catch-up row; present with `fixes: 0` when running without a fix):
- **Per 10 km/h band, strict and loose kept separately:** N, Σx, Σy, Σxy, Σx², Σy², the grade
  sums with their altitude-noise term, and the speed-accuracy sums. x is the rear-pair wheel speed
  in raw counts (no wheel scale baked in); y is GPS speed in m/s. Bands are keyed on x, because
  banding on the noisy y biases the slope.
- **Lag products l = 0..3** (yy, xx, yx, xy), so any receiver lag can be fitted later.
- **Receiver quality:** fix count, no-speed count, unpaired count, implausible count, and the sums
  of speed accuracy and its square.
- **Loose is for measuring the trade, not for use.** It is the only way to measure the receiver's
  lag, and is scheduled for removal once that is measured.

**How a fix is paired.**
- The fix time is mapped into the CAN frames' monotonic clock, with the offset taken fresh per fix.
- The fix is held until wheel samples exist 0.5 s either side, then paired with the mean rear-pair
  speed over that window.
- It is strict- or loose-kept only if every wheel sample in the window passes that set's live mask.
  That mask is sample-and-hold, with a backward 0.1 s steer rate. It cannot look ahead, so it
  differs slightly from `extract_one`. Recorded in the spec, because the GPS set can never be
  re-derived offline.
- **Plausibility gate:** above 25 km/h, a fix more than 20 % off its wheel speed is rejected before
  anything is summed, counted in `implausible`, and breaks the lag chains. Sums cannot be cleaned
  afterwards. The gate has ~20,000x the headroom of the signal. There is deliberately no gate on
  reported accuracy, which would bias.

**Android.**
- `GpsSpeedService` is a `location` foreground service (notification: "Speed only - position is
  never recorded"). It uses the plain `LocationManager` GPS provider, with no Play Services.
- It is started from `MainActivity` while in front. The location permission is requested at launch
  and from page 3's ALLOW button. After two refusals Android stops prompting, so ALLOW then opens
  the app's settings page.
- **The owner must choose Precise:** approximate location gives no speed.

**Elevation change, `gps.elev` (owner request 2026-09-24, not a TPMS input).** For correcting
efficiency estimates for gravitational energy (`../projects/coda/notes/efficiency-calculation.md`
currently cancels elevation only by out-and-back pairing). Fields: `dh_m`, `climb_m`, `descent_m`,
`deadband_m` (5.0), `n`, `low_acc`, `sum_vacc`, `n_vacc`. **Changes only, never an altitude.**
- `dh_m` is the net change and telescopes across a session's segments, so the segments sum
  exactly to the trip's net change.
- `climb_m`/`descent_m` run a 5 m hysteresis on altitude **averaged over 10 s**. On raw fixes the
  hysteresis is a random walk: 3 m per-fix noise gave ~3,000 m of phantom climb over 30 flat
  minutes in the test; smoothed, under 20 m (the test's bound).
- Fixes with vertical accuracy worse than 20 m are skipped (`low_acc`).
- Privacy: kept as built under the owner's position recorded in spec section 7 (2026-09-26):
  collect broadly now and narrow deliberately once the algorithms are calibrated, so that a
  borrowed-car mode can later be a matter of switching collection off.

**Page 3** shows one GPS line: not allowed / no receiver / location off / searching (satellites) /
fixes per minute, accuracy, satellites and the live GPS-to-wheel ratio for 70-80 km/h (strict,
whole session, reads ~1.00 when the 17.61 counts/km/h scale is right). The ratio is display only.

**Verification.**
- `GpsRateAccumulatorTest`, 16 tests: pairing, strict/loose separation, lags, grade, plausibility
  gate, one block per segment, elevation (chaining, jitter, flat-road noise), and the privacy key
  list.
- On the AVD: prompt, deny, ALLOW prompting again, the settings fallback after two denials, grant,
  the service in the foreground, and page 3 showing injected fixes.
- **Not yet verified:** GPS paired with real wheel data (the AVD has no CAN logging), and whether
  the A007 has a GPS receiver at all. Both need the car.

---

## Detector

Built 2026-09-26 (plan Step 5), approved by the owner as a prototype. `TpmsDetector` is a port of
`run()` in `../projects/coda/notes/artifacts/tpms_app_prototype.py`. `FileTpmsCalibrationStore`
replays it over the active epoch after every SET, UNDO, AMEND and drive row, and publishes the
result as the page-3 estimate.

**What it does.**
- **Stateless.** Every call replays the whole epoch from its first row. Baseline, verdict and
  pending confirmation are never kept or written (spec invariant 1), so every setting can be
  retuned against an unchanged file.
- **One drive = one capture session.** Rows are pooled by session (log name before `_T`) before
  any count applies; contrasts are n-weighted. The precalibration file is never read.
- **Void sessions are skipped entirely:** not learned from, not in any window, not fast-pathed. A
  void session also does not close the UNDO window. Page 3 says "Last drive void: ABS/ESC fault"
  (or "wheel sensor dead") so a faulted drive does not look like no qualifying driving.
- **Learning:** the first 3 qualifying drives (and at least 2,400 pooled samples) are frozen into
  the baseline. `FrozenBaseline` throws on a second freeze. Page 3 shows "Learning - not yet
  monitoring" with progress: neither path can see a puncture before the freeze.
- **Slow path (gradual leak):** the last 5 post-freeze drives pooled, in **file order**, never by
  timestamp. The per-corner **outlier** reading (projected x 4/3) goes through ADVISE 2.5 / WARN 4.0
  psi with hysteresis (clear at 1.8 / 3.0) and 2-drive confirmation.
- **Fast path (puncture; owner, 2026-09-26: "if I hit a nail ... I want to know on the first
  drive").** The current drive alone against the baseline, no window, no confirmation: WARN at 6 psi
  with at least 800 samples. It is re-evaluated at every segment close, so it can fire during the
  drive. 6 not 4 because single-drive false alarms were measured on the corpus by the algorithm
  session: 1.57 % of drives at 4 psi, 0.79 % at 5, none at 6. Provisional.
- **Unannounced fill:** a rise in DEL of 3 psi or more between two 3-drive windows goes to STALE,
  shown as RECALIBRATE with the corner numbers hidden.
- **What a single low tyre looks like:** the outlier reading is per corner, so LF alone 5 psi down
  reads LF -5.0 and +1.7 on each of the other three.
- **The four corners always sum to zero** while the common mode is unknown: every contrast's
  corner signs sum to zero. `outlierPsi` checks it on every call and throws if it fails (a broken
  inversion or flipped sign), which the store shows on page 3. Added 2026-09-26 after build 23, at
  the algorithm session's suggestion; the prototype's `corner_psi()` asserts the same. So a
  positive corner is the complement of a negative one, not news about that tyre.

**Two properties reached by review, now spec decisions.** Both were found by checking the
implementation against the spec's stated invariants rather than against the other implementation.
- The prototype picked its window by `ts <= rec.ts`, which made a detector specified as "never
  time-based" depend on the head unit's clock. Both now use file order.
- The fix to that also dropped the learning drives from the window (they are the baseline; mixing
  them in pulls the first estimates toward "nothing wrong"). The events on the corpus are
  unchanged, but the first post-freeze DEL moves from -0.14 to -0.28 psi, so "the events match" was
  not evidence of "identical".

**Verification.**
- `TpmsDetectorParityTest`: the prototype's corpus epoch file (154 real drives, 2026-02-17 to
  09-24) under 23 settings cases, three of which lower the fast-path threshold so it fires on real
  drives. Events and their drives, final state, baseline size, and every per-drive DEL and corner
  figure to 1e-9 psi. Default settings reproduce the spec's corpus replay: baseline 02-19, LF
  advise 04-27 at -3.3, warn 05-01 at -4.5, stale 07-02. Fixture:
  `CanLoggerApps/tpms/src/test/resources/detector_parity/`, written by
  `notes/artifacts/tpms_detector_parity.py`.
- `TpmsDetectorTest`, 11 tests: segment pooling, file-order window with a clock running
  backwards, write-once baseline, fast path on the puncture drive and mid-drive, void sessions,
  STALE suppression, the page's estimate.
- **Not verified:** anything on real driving. The corpus has no sudden loss, so the fast path has
  never seen a puncture; the owner's planned deflation test is its first real input.

---

## Hardware report — what the head unit has

Built 2026-09-26 (plan Step 5b), approved by the owner. Owner's request: "using the headunit's
Gyro/accel if it has one, let's add a diagnostic feature to the app that prints out what hardware
features it sees, into the seafile directory as a separate file. since we dont have ADB we can't
read this directly."

- `HardwareReport` (in `:tpms`) writes `CodaLogs/diag/hardware_<APK install time>.json` about 20 s
  after the app process starts, **once per installed APK**: a restart does not write another, a
  new build does.
- Contents: build and SoC identity, every declared system feature, GNSS hardware name, year and
  capabilities, and every sensor with its declared properties. Each continuous or on-change sensor
  is also sampled live for 5 s: event rate (by count and by timestamps), largest gap, per-axis
  mean / sd / min / max, and the offset of its timestamps from `elapsedRealtimeNanos`. A listed
  sensor with no events or zero noise is not a working sensor.
- **No position:** GNSS is described by hardware only; no location is read. Checked on the AVD
  report: no position-like keys.
- New permission: `HIGH_SAMPLING_RATE_SENSORS`, normal (granted at install, no prompt), needed
  above 200 Hz from Android 12.
- **It doubles as the SeaDrive subfolder check.** `CodaLogs/diag/` is reachable only by SeaDrive,
  exactly like `CodaLogs/tpms/`. The report appearing on the server shows subfolders sync; its
  absence means the TPMS files will not arrive either.
- Verified on the AVD: written once per install, not rewritten on relaunch, all 12 continuous
  emulator sensors sampled at their declared rates. The emulator's on-change sensors send nothing
  until a value changes, so zero events there is expected.

**What the head unit reported** (`hardware_20260926T154743.json` from build 23 and
`hardware_20260926T181152.json` from build 27, both on Seafile, so subfolders do sync):
- **No sensors are available to apps.** `sensors` is empty in both, although `features` declares
  an accelerometer, gyroscope, compass, light, proximity and step sensors. A gyro or accelerometer
  input to the TPMS method is therefore not available on this unit.
- **Display:** 1024 x 600 px at `density_dpi` 240, so 682 x 360 dp for the app (font scale 1).
  This is the space page 3 now scales to.
- **GNSS:** `gps` and `network` providers enabled. The GNSS HAL names itself "Google Mock GNSS
  Implementation v1.1" (2018), yet page 3 showed real fixes (47/min, 10 satellites, +/-0.25 m/s).
- `HIGH_SAMPLING_RATE_SENSORS` reads not granted; with no sensors it does not matter. (The
  permission is "normal": granted at install, never prompted, and it only caps rates above 200 Hz.
  It cannot hide a sensor, and listing sensors needs no permission.)
- `features` is the platform's own declaration (`getSystemAvailableFeatures`, written into the ROM's
  configuration files); `sensors` is what the sensor service actually reports
  (`getSensorList(TYPE_ALL)`). The two disagree on this unit. Owner, 2026-09-26: the unit has camera
  inputs (backup camera) and probably a SIM slot, definitely no fingerprint reader, and is unlikely
  to have an IMU; "but want to be sure".

**Report schema 2 (build 28)**, added to settle that:
- `sensor_system`: the sensor list count; dynamic-sensor discovery support, the dynamic list, and
  any dynamic sensor connecting during the 5 s window; sensor HAL libraries under
  `/vendor|/odm|/system lib*/hw` whose name contains "sensor"; `/sys/bus/iio/devices` names;
  `/proc/bus/input/devices` names. Each path is recorded as found, missing or not readable, since
  an unreadable path proves nothing.
- `platform`: `SDK_INT`, release, the app's target SDK, and `getprop` values for the build version,
  board, hardware and anything naming a sensor (the A007 reports `SDK_INT` 29 on Android 12).
- `permissions`: every permission the APK requests, with granted, whether the platform defines it,
  and its protection level. An undefined permission can never be granted.
- `cameras` (ids and facing; nothing opened) and `telephony` (phone type, slot count, SIM state; no
  identifiers).
- Checked on the AVD: it found the emulator's sensor HAL (`android.hardware.sensors@2.1-impl.ranchu.so`),
  16 sensors, dynamic discovery unsupported, `/sys/bus/iio` and `/proc/bus/input/devices` not
  readable by an app (SELinux), GSM with one slot, SIM ready, and no cameras. So on the car, the two
  sysfs/proc probes may well read "not readable" and settle nothing; the HAL library listing and
  `getprop` are the informative parts.

---

## Log timing fix — no negative offsets (shared logger, Coda and Vtrux)

Found 2026-09-24 while porting the drive rows, and fixed at the owner's direction: *"let's not
fix this by clipping the time, and instead just make sure the file write is timed properly so that
we never get negative time"*.

**The defect.** `BusmasterWriter` measured offsets from the moment a segment file opened. Frames
are stamped on receipt and written a little later, so at every roll the frames already received
but not yet written got negative offsets (`00:00:00:-160`, 16 of 720,965 lines in one capture).
Every parser rejects those lines: `canre`'s `\d{4}`, and the drive-row port for parity. A few frames
were silently lost at every 5-minute boundary, in every Coda and Vtrux log. A second defect sat
beside it: offsets came from millisecond wall-clock stamps through a truncating `Double`, so
3.404 s was written as `4039`.

**The fix, in `:cancore`:**
- `CanFrame.elapsedNanos` is a monotonic receipt stamp (`System.nanoTime()`), excluded from
  equality.
- `CanPipelineManager` stamps and emits each frame under one lock, so frames leave the flow in
  stamp order even with two dongles on two reader threads.
- `BusmasterWriter` takes its origin from **the first frame written to the file**, and the header's
  START DATE AND TIME is that frame's wall time, so header + offset stays each frame's absolute
  time. Offsets are integer nanoseconds -> 0.1 ms ticks. A wall-clock step mid-file (the head unit
  syncing its clock after boot) cannot move them.
- **Fallback:** a frame whose stamp is earlier than the previous one is written at the previous
  offset and counted in `outOfOrderFrames`, which `CanLoggingService` logs as an error. The
  stamp-and-emit lock makes this impossible for pipeline frames, so a non-zero count means a
  frame source is misbehaving. It exists only because the format cannot express a step back.

**What changes in logs from build 23 on:**
- The first data frame is at `00:00:00:0000`. T0 previously started a few seconds in, and absolute
  times are unchanged.
- No negative lines.
- Ticks now carry real 0.1 ms resolution.

Existing logs are unaffected, and every parser already handled both forms.

Verified by `BusmasterWriterTest` (7 tests: buffered-before-open frames, header time, wall-clock
step, exact ticks, out-of-order fallback, empty file, round trip through `BusmasterReader`).

---

## CAN transmission

**The app's first ever transmit path.** Everything before this was receive-only.

### Why it exists at all

An indirect TPMS that drives the factory dash lamp must transmit `0x600` continuously at ~1.9 Hz
**just to hold the lamp off** — the IPK appears to infer the fault from the frame's absence, so
there is no override, only replacement. That step also requires the RCU to be physically removed,
and the evidence for its safety is one parts-car observation that contradicts the factory manual
(feasibility §7a). Since 2026-09-26 the TPMS lamp slot is registered (see
[The lamp-hold prototype](#the-lamp-hold-prototype-0x600)). Through build 30 **the transmitter was
disabled on the car** by `CodaConstants.TPMS_LAMP_TX_ON_CAR = false` (owner, 2026-09-26: "leave it
disabled for now until I confirm the RCU is disconnected (it's not yet)"). **Build 31 turns it on**
(owner, 2026-10-04: "build v31 with the 0x600 TX enabled. I will go pull the RCU in the car and
then install it.").

### Which bus — B CAN

`0x600` originates on D CAN at the RCU and reaches B CAN as a GWM pass-through; the IPK reads the
telltale off **B CAN**. Injecting there puts the frame directly at its consumer. Both dongles are
fitted in the car, so D CAN is physically available too, but B CAN is better on two counts: D->B
forwarding is a dependency that B->consumer does not need, and — see the contention guard below —
injecting on D would have the gateway's copy land on the B dongle as apparent foreign traffic.

### Design

Five pieces, none of which disturb the receive path.

| Piece | What |
|---|---|
| `GsUsbDevice.send()` | Bulk OUT endpoint, discovered non-fatally in `open()`. A firmware without one degrades to read-only rather than refusing to log. |
| `CanFrame.isTx` | Defaulted `false`, so no existing construction site changed. Set from the gs_usb echo cookie. |
| `CanTransmitter` | The capability interface, mirroring `CanFrameSource`. `CanPipelineManager` implements it. |
| `PeriodicTransmitter` | Scheduler + all interlocks. No Android imports, so it is JVM-testable. |
| `BusmasterWriter` | Writes `Tx` in the direction column for our own frames. |

**Echo handling is mandatory, not cosmetic.** gs_usb echoes every transmitted frame back on the
bulk IN endpoint. Without `isTx`, our injected `0x600` would reappear indistinguishable from an RCU
broadcast, and the contention guard below would suppress its own slot one period after starting.
There is a test pinning this.

**`isEcho` matches our own cookie exactly (`echoId == ECHO_ID_TX`), not "anything that isn't
RX".** Found 2026-09-23 while checking the build for the car: `tools/influx_upload.py:989` **skips
every `Tx` frame**. Under the original `echoId != ECHO_ID_RX`, any received frame bearing an
unexpected echo_id would have been logged as `Tx` and silently vanished from the InfluxDB corpus,
while the log file still looked healthy at a glance. The exact match fails safe on both consumers:
an odd frame stays `Rx` in the logger (data kept), and the contention guard treats it as foreign
(suppress, not transmit). Standard gs_usb puts `0xFFFFFFFF` on RX — the Linux driver depends on it,
so the Innomaker almost certainly does — but this build had never been run against the real
dongle's echo_id, so the narrow match costs nothing and removes the silent path. Pinned by a test.

The direction column round-trips for free: `canre/parsers/busmaster.py` already reads `Tx` into
`CANFrame.is_tx`, so a log containing the app's own injected frames stays readable by every
existing offline tool with our frames distinguishable from the vehicle's.

### Interlocks

All in `PeriodicTransmitter`, not in feature code — one place to audit, and reachable from tests.

1. **Disabled by default.** `enabled` starts false; registering a slot does not transmit.
2. **ID allowlist**, fixed at construction from `CodaConstants.TX_ALLOWED_IDS` (currently just
   `0x600`). An ID outside it is rejected at `register()` — a wiring mistake fails at startup
   instead of quietly spraying a drivetrain bus at runtime.
3. **Bus resolved by identity, never by index.** A slot supplies a `() -> Int?`; until it returns,
   nothing transmits. Dongle insertion order decides physical indices.
4. **Contention guard, keyed on (busIndex, ID).** If another node has been heard sending the same
   ID on the same bus within 5 s, the slot is suppressed. Two nodes sending the same ID both win
   arbitration and then collide in the data field: the frame is destroyed, both retransmit, and
   both walk their transmit error counters toward bus-off. Suppressing is always right, and it
   makes the code safe to ship before the RCU is ever removed.
   **Per bus, not per ID** — contention is a property of one wire. Keyed on ID alone it would also
   break on any gatewayed frame: `0x600` injected on D CAN is rebroadcast onto B CAN, arrives there
   off the wire carrying `isTx = false`, and would suppress its own source slot permanently.
5. **Rate floor** — `MIN_PERIOD_MS = 50`.
6. **Failure backoff** — 10 consecutive rejected sends disable the slot and record why.

Scheduling (2026-09-26): a slot's next due time is one period after it was *due*, not after the
tick that served it, so loop lateness does not accumulate (it had stretched `0x600` to ~531 ms
against the RCU's 523-525); a slot more than a period behind restarts rather than bursting.

A slot's payload provider returning `null` skips that tick without unregistering — that is how a
feature stops asserting while keeping its schedule.

### Lifecycle

`CodaApplication` constructs the transmitter and the bus resolver, feeds every received frame to
both, registers the lamp slot, and runs the schedule. Idle cost is near zero: while the transmitter
is disabled (or has no slots) `sleepMs()` returns 1 s, and `observe()` drops every frame whose ID
is outside the allowlist. Before 2026-09-26 only "no slots" counted as idle; a registered but
disabled slot is permanently overdue and would have woken the loop every 10 ms on the car.

The resolver's decisions and every change of the lamp slot's state (GATED, BUS_UNRESOLVED,
CONTENDED, ACTIVE, ...) go to the debug log, which is the only way to see from the car why the lamp
is or is not being held.

### The lamp-hold prototype (`0x600`)

Built 2026-09-26 (plan `notes/plans/coda-slcan-harness-0x600.md`, Step 2), code in
`tpms/.../TpmsLamp.kt`. Owner's brief: "all TPMS warn states should light the light. if we can make
it flash when it's worse and steady when just in warn that works too. the exact state machine here
doesn't have to be perfect - getting the plumbing working is more important."

- **Policy** (`TpmsLampPolicy`): LEARNING, OK -> off; ADVISE, STALE -> steady; WARN -> flashing
  (bit 5 two frames on, two off, about a second each). Taken from the store's current estimate.
- **Payload** (`RcuStatusFrames`), shaped like the RCU's own, measured on B CAN in
  `coda_20260618_195906` (1,139 frames): B0 steps `00 03 10 13`; B1-B4 `01 01 07 00`; B5-B6 a
  little-endian counter stepping every second frame (on the `03` and `13` frames), starting at 0
  like a freshly woken RCU; B7 `0x4A`, or `0x6A` with bit 5 set. B1-B4 are copied, not understood.
- **Slot** (`TpmsLampSlot`): `0x600` on B CAN (resolved by content), every
  `RCU_STATUS_PERIOD_MS` = 525, through every interlock. If the app stops, the frame stops and (on
  the working assumption) the lamp comes on, so a failure warns rather than hides a warning.
- **The switch:** `CodaConstants.TPMS_LAMP_TX_ON_CAR`, true from build 31. False: registered, never sent. The emulator
  harness enables the transmitter regardless (ADB-only), and there `debug.coda.tpms_lamp`
  (off / steady / flash) can force a mode.
- **Verified in the harness:** with the RCU's `0x600` in the replay the slot sat CONTENDED and
  nothing was sent; with it dropped (`--drop-id 0x600`) frames reached the bridge on B CAN only,
  mean 525.0 ms (515-537), phases and counter exact, bit 5 following off -> flash -> off; the app's
  own log records them as `Tx` on channel 1. With the harness off (the car's configuration) the
  log reads "transmitter disabled" and the slot GATED, nothing sent.
- **Re-verified on build 31 before install (2026-10-04)**, the exact `coda-debug (31).apk` on the
  AVD, replaying `coda_20260618_195906_T0`:
  - harness off (the car's path, no dongle): "transmitter ENABLED (TPMS_LAMP_TX_ON_CAR)", slot
    BUS_UNRESOLVED, nothing sent;
  - RCU's `0x600` in the replay: B CAN identified in 3 s, slot CONTENDED, the bridge recorded 0
    frames;
  - `--drop-id 0x600`: slot ACTIVE; 243 frames from one process, all B CAN, period 525.0 ms mean
    (513-534), no B0 phase or counter errors, B1-B4 always `01 01 07 00`, B7 following the
    override off -> steady -> flash (two on, two off) -> off;
  - re-run with the AVD screen on, so the app also logged: 125 frames at the bridge, and the app's
    own segment held the same 125 as `Tx` on the B CAN channel and no received `0x600`.
  - Two harness traps seen in the run, not app faults: the app logs only while the screen is on
    (screen trigger), and the AVD had gone to sleep; and stopping the bridge does not stop the app,
    which reconnects to the next bridge, so force-stop the app between scenarios.
  Script and TX logs: `notes/artifacts/harness31_tx_check.py`, `harness31_*_tx.log`. Not covered
  by the harness: the real gs_usb transmit path and the IPK's response.
- **Tests:** `TpmsLampTest` (10) -- the first 12 real RCU frames reproduced byte for byte, counter,
  flash, policy, and the slot through `PeriodicTransmitter`; `PeriodicTransmitterTest` gained the
  schedule-anchoring and idle-when-disabled cases.
- **Unknown until the car:** whether the IPK follows bit 5 live or latches it (so whether flashing
  shows at all), whether it minds the counter restarting at 0, and whether it times out the frame's
  absence and after how long (feasibility §7a).

---

## Emulator harness

Built 2026-09-26 (plan `notes/plans/coda-slcan-harness-0x600.md`, Step 1). Real Coda logs are
replayed into the AVD through the app's real frame path, so the logger, segment rolls, drive rows,
GPS pairing, the display, the bus resolver and the transmitter all run on real traffic.

- **PC side:** `tools/slcan_bridge.py --busmaster <chunks> --vehicle coda` serves each bus (named by
  content) on its own port, 9000 up, paced by the log. It records whatever the app transmits
  (`--tx-log`), can leave an ID out (`--drop-id 0x600` = RCU removed), and can feed speed-only GPS
  to the emulator (`--nmea`, fixed dummy position). Usage in `tools/tools.md`.
- **App side:** `SlcanBusGroup` (`:cancore`) stands in for the dongles, including the gs_usb-style
  `isTx` echo. `CodaApplication` uses it only when `adb shell setprop debug.coda.slcan 9000,9001`
  is set at app start; otherwise it constructs nothing and uses `CanPipelineManager` as before. The
  head unit has no ADB, so the property cannot be set there. Not gated on `BuildConfig.DEBUG`,
  because the car runs debug builds.
- **Checking a run:** `android-app/notes/artifacts/harness_log_check.py` compares the app's pulled
  segments with the source, per bus. The first run matched every frame (numbers in the plan).
- **The emulator's GPS clock is wrong for injected fixes** (time since 1970, not since boot), so
  before the guard in `GpsRateAccumulator.fixTimeNanos` every fix was silently unpaired. The car's
  receiver is correct. The guard replaces any fix time more than 10 s from its arrival.

---

## A standing practice: prose does not enforce anything

Three separate bugs across the two sessions building this feature had the same shape — **correct
documentation sitting next to code that could violate it**:

| Where | The rule | How the code could break it |
|---|---|---|
| `amend()` (app) | must not move the epoch's timestamp | took a `TpmsCalibrationEntry`, which carries `setAtMs` — and SET builds one with `System.currentTimeMillis()` two lines away |
| `TpmsEstimate` (app) | each reading belongs to a named wheel | four adjacent same-typed positional fields, transposable in a way that compiles and stays plausible |
| Inversion matrix (analysis) | signs must stay aligned to the corner order | a bare 4x3 of signs maintained *beside* a positional corner tuple; reorder one and the attribution silently swaps |

Every one was documented correctly first and broken anyway. The `amend()` case is the clearest:
the rule was in the KDoc, and the signature that violated it was written in the same file, in the
same sitting, by the person who had just written the rule. **Proximity beat prose.**

What worked in all three was making the wrong call unrepresentable rather than discouraged —
removing the timestamp from the signature, keying by `Corner`, deriving the matrix from a per-corner
map instead of maintaining it alongside one. None of the three changed behaviour; each cost a few
lines and only speaks when someone reintroduces the bug.

**So: when a rule in this feature matters, encode it in a type or a shape, and use the comment to
explain *why* the shape is odd** — otherwise a later reader will "tidy" it back into the version
that permits the bug. That is what the unusual-looking signatures here are for.

And the part that actually generalises: **all three were found by the other session, not by the
author.** Each author had the rule in front of them, had just written it down, and shipped code that
violated it anyway. So the lesson is not "be more careful next time" — it is that a second reader
who did not write the code is what catches this class of defect, and that the cross-checking was
worth its coordination cost.

---

## Storage and sync — immutable fragments, and what the server may do with them

*Rewritten 2026-09-26 (plan `notes/plans/coda-tpms-fragment-store.md`). This section previously
concluded that "a single append-only file per calibration epoch works" because nothing deletes
these files. That was falsified: the deleter was never the only threat, the transport is. The
section also carried a contradiction — a heading saying `SAFE_NAME` was widened to `.jsonl`
("fixed") and a later paragraph saying the widening was reverted. The revert was the current
state; both are superseded below.*

### Why fragments

SeaDrive on the head unit is **one-way and upload-only**: it uploads a file when it first sees it
and ignores every later change (owner confirmed; the owner also reports that when Seafile opens it
scans everything and uploads what it has not uploaded yet). The append-only file per epoch was
therefore frozen on the server at whatever it held first — the live one reached the library at
127 bytes while the head unit's copy kept growing. The algorithm session's evidence and the design
are in spec §4 (`projects/coda/notes/tpms-algorithm-spec.md`).

So since build 29 the store is a folder of **immutable fragments**, `TpmsEpochStore` (`:tpms`):

- **Every write is a new file**: built in memory, written to `<name>.tmp`, fsynced, renamed. A
  kill or power cut leaves a `.tmp`, which nothing lists. Nothing is ever appended to or rewritten.
- **A fragment** is `tpms_<epoch>_<seq>.jsonl` and holds the epoch's `calibration` (repeated in
  every fragment, so any one of them is a working store), every `calibration_amend` and
  `epoch_void`, then **one** row: a segment's completed row, or the open segment's `partial` row.
  No tail of earlier rows (R = 0, agreed with the algorithm session after measuring rows at 1-6 kB).
- **A `_full` fragment** carries the whole epoch: on SET, AMEND and UNDO, when the epoch has none
  yet, and every 256 completed rows. The "none yet" rule is also the migration: the first write
  over a legacy file is a `_full` carrying all of it, so **installing build 29 migrates the store**
  with no car-side step. Legacy files are read as fragments as they are.
- **Precalibration** rows (before the first SET) use the same scheme under
  `tpms_00000000T000000_<seq>.jsonl`, first record `precalibration`.
- **Partial rows, once a minute** while a segment is open, unconditionally: `log`, `ts`, the GPS
  block so far, `n` 0, `ratios` null. The open log is not re-parsed (its CAN half is regenerable).
  This **replaces `GpsSnapshotStore`** (build 27), whose copy was internal and deleted when read;
  the partial row reaches the server. `CodaApplication.checkpointOpenSegment()`.
- **UNDO is a tombstone**: an `epoch_void` record in a `_full` of the voided epoch. Uploaded
  fragments cannot be recalled by a one-way sync, so a delete could not work.
- **Reading dedupes by content.** Epoch = the calibration record's ordering key, `name_ts` when
  present, else `ts` (so a `... (1).jsonl` re-upload is a non-event); drive = `log`. A completed row beats every partial, then higher `proc`, then
  higher `n` (completed) or `gps.fixes` (partials), then later seq. **Dedupe never loses a GPS
  block**: a winner without one takes the best one a row it beat had, tagged `source: "partial"`.
  That is what keeps a force-stop's GPS: catch-up's completed row for the killed segment has no
  live block, so it takes the last partial's (`storedGps`, and again at read time).

App-side choices the prototype does not have:

- **In-memory index, bounded startup read.** Per prefix, canonical fragments older than the newest
  `_full` are not read (the `_full` holds them). If such a fragment is *newer on disk* than that
  `_full` — placed or overwritten by hand — the read falls back to a full scan. The full scan is
  what defines correctness. The limit: a copy that preserves an old mtime would not be noticed.
- **Two SETs in the same second** share a `ts`. With identity = `ts` the second would silently
  merge into the first (the prototype did this too). Ruled by the algorithm session: identity is
  the ordering key (`name_ts`, else `ts`), which `set` already makes unique, and `ts` stays the
  true press time.
- **One-time bridge**: the segment open when build 29 is installed has its last GPS snapshot only
  in the old internal folder, so catch-up reads it once after the store. Removable later.

Measured: parity with the prototype's `FragmentStore` on a copy of the live folder (legacy file
plus its `(1)` copy) — 13 rows identical field by field, 5 GPS blocks each side, and the same first
`_full` after one added row (`notes/artifacts/tpms_fragment_parity.py`). `TpmsEpochStoreTest` (35)
covers the rest; mutation-checked (inheritance, partial ranking, consolidation, the full-scan
fallback each break at least one test).

### What the file server may do: read broadly, delete narrowly

`LogFileServer` (`:cancore`) is now general for reading (owner's request, 2026-09-26):

| Endpoint | Scope |
|---|---|
| `GET /files` | **unchanged**: log root, `.log`, non-recursive |
| `GET /tree` (new) | recursive, `.log` `.jsonl` `.json` — reaches `tpms/` and `diag/` |
| `GET /files/<path>` | sub-paths allowed: empty, `.` and `..` segments refused, canonicalised, must lie under the root |
| `DELETE /files/<name>` | **unchanged**: log root, `.log` only, no `/` |
| `PUT /files/tpms/<name>.jsonl` (2026-09-27) | adds a new fragment to the store only: create-only, JSON lines, `Content-Length` <= 8 MB, tmp + fsync + rename, then the store re-reads (full scan) |

**Why PUT** (owner, 2026-09-27: *"this is why we need to be able to regenerate/correct the locally
stored data so we can put corrected data back on the car but still use it"*): a row re-derived
offline goes back as a new fragment under the new `proc` and wins the store's dedupe, so nothing
is overwritten or deleted. `PUT` is enabled per app (`putDir`); only the Coda sets it, to `tpms`.
Everything else is 403, an existing name is 409, and a body with a line that is not a JSON object
is 400. *Limit:* a `_full` the store writes in the instant between a PUT's rename and the re-read
would not carry the placed row; if the placed name also sorts below that `_full`, a later bounded
startup read skips it (the mtime rule does not fire, the `_full` being newer). The re-read is
queued on the store thread at once, so the window is milliseconds.

**Why `/files` did not become recursive**: the companion already installed pulls whatever `/files`
lists and then DELETEs it (`SyncEngine.kt:162`). With the fragments listed and the DELETE refused,
it records "server DELETE failed; will retry next sync" and never indexes the name, so it would
re-download every fragment on every sync, forever. A separate `/tree` gives the read route without
changing any client's behaviour. **Why DELETE stays narrow**: the store is the one record the CAN
logs cannot regenerate, so the server refuses to delete it whatever a client does.

The deletion guards are still four, all non-recursive and `.log`-only:

| Path | Guard |
|---|---|
| `LogFileServer` `/files` listing | log root, `.log` |
| `LogFileServer` DELETE | `SAFE_LOG_NAME`, no `/` |
| `CanLoggingService.pruneOldLogs` | `.log` filter, non-recursive — the 10 GB cap cannot reach it |
| companion "Delete local copies" (`CompanionViewModel.kt`) | `isFile && .log`, non-recursive |

The old trap — "switch the primary route to the companion and TPMS backup silently stops" — is
retired: the store is no longer invisible to the server, and under fragments pull-then-DELETE would
not be destructive either (the files are immutable, the contract `SyncEngine` was built for). The
companion does not use `/tree` or `PUT` yet. `LogFileServerTest` (13, real HTTP on the JVM) covers
listing, sub-path GET, traversal, DELETE refusal on the store, auth, and PUT (placement, no
replace, path and type limits, body check, refused without a `putDir`); mutation-checked.

**Verified 2026-09-26:** the calibration file did reach the library from
`/sdcard/Android/data/com.reverseit.coda/files/CodaLogs/tpms/` (frozen, but there), so SeaDrive
does sync that subfolder.

---

## B CAN anchor IDs — the app uses a stricter set than the README

`CodaConstants.B_CAN_EXCLUSIVE_IDS` (0x378, 0x381, 0x382, 0x390, 0x391, 0x270, 0x271, 0x2C1) is
used to identify the bus for the transmit path, **not** the existing `B_CAN_ANCHOR_IDS`.

The reason: three of the six IDs in `B_CAN_ANCHOR_IDS` — `0x275`, `0x383` and `0x1D5` — are B CAN
native but **gateway-rebroadcast to D CAN** (`../projects/coda/notes/driver-inputs.md`, "B CAN ->
D CAN direct pass-through"). They therefore appear on both buses, and `BusIdentityResolver`'s
threshold is `min(3, anchorIds.size)` = 3 matches, which D CAN can clear on rebroadcast traffic
alone.

For picking a bus to *read* from — what `B_CAN_ANCHOR_IDS` was written for, in `ReplayCanSource` —
a wrong pick costs a bad replay. For picking a bus to *transmit* on it would put a synthetic frame
on the driveline bus. The sets are kept separate rather than the looser one reused.

Every ID in `B_CAN_EXCLUSIVE_IDS` is on the B CAN exclusive list in `driver-inputs.md`.

**This originates in `projects/coda/README.md`, which has the same weakness** — its B CAN anchor
row is `0x1D5, 0x48A, 0x275, 0x381, 0x383`, three of which are rebroadcast, and it is rated "High"
confidence. The README applies the right test to the other bus (its D CAN row is explicitly
"D CAN exclusive — not rebroadcast to B CAN") but never applies it to B CAN. **Not yet corrected —
see open items.**

---

## Verification

- `:cancore:testDebugUnitTest` — 28 tests, 0 failures. 17 are `PeriodicTransmitterTest`: one per
  interlock including the gs_usb self-echo and gateway-rebroadcast cases, plus the
  unexpected-echo_id fail-safe.
- Settings page exercised end to end on `7_WSVGA_Tablet_API_31` (1024x600, API 31): preload,
  single tap, press-and-hold repeat, keyboard entry and commit, SET, readback line, UNDO
  (arm → confirm → restore, and absent when nothing to undo), per-corner keying (1/2/3/4 taps →
  distinct values through cells *and* SET readback), and the estimate pane showing `LEARNING`.
- Pages 0 and 1 confirmed unaffected by the pager change.
- **Persistent store, 2026-09-24:**
  - `:coda:testDebugUnitTest`: `TpmsEpochStoreTest` 19 tests, 0 failures.
  - On the AVD, SET (RF 41.9, 20 C) wrote `CodaLogs/tpms/tpms_<ts>.jsonl` with the expected line.
    After force-stop and relaunch, page 3 read it back.
  - A second SET showed UNDO; arm and confirm deleted the new file and restored the first. That
    state survived another relaunch.
  - The `name_ts` change was made after the AVD run and is covered by the JVM tests only.

---

## Spec 8a handoff — D CAN pinning, PUT and `reject`, 2026-09-27

The algorithm session's handoff (`../projects/coda/notes/tpms-algorithm-spec.md` section 8a),
implemented at the owner's go-ahead (*"yes make the changes"*). In `coda-debug (30).apk`, dropped
2026-09-28 to `E:\Google Drive\To Seafile\` at the owner's request, sha256
`65f3286aa9000ee524f6c5221b876932f19b41b5a96eeea68655c7bb3317bdb0`. It carries everything build 29
did (see [On the car — build 29](#on-the-car--build-29)) plus this; build 29 was never installed,
so proc 3 keeps its number. Lamp transmit still off on the car (`TPMS_LAMP_TX_ON_CAR = false`).

- **Item 1, D CAN by anchors, both places.**
  - `WheelRatioExtractor.readFrames` keeps D CAN only, chosen by `selectDCan` (a port of the
    Python `select_d_can`): anchors `0x308 0x312 0x325 0x330 0x580`, two distinct ids to win, a
    rival counts only with two distinct ids of its own (so a stray frame does not reject a
    capture), and the winner must carry all four signal ids. Rows are sorted by time; the time
    origin is the first frame of an anchor or signal id, as the Python's grep file. `dominantBus` is
    gone.
  - `GpsRateAccumulator` applies the same rule live, per segment (evidence reset at each close):
    wheel frames are read only from the decided channel, and a rival reaching two anchors stops
    collection until the next segment. The all-signal-ids test cannot be decided live.
- **Item 2, proc 3 = D CAN pinned.** `DriveRowProducer.PROC` stays 3; the KDoc now says proc is a
  claim about rules, not a build.
- **Item 3, parity references.** `ExtractorProc3ReferenceTest` now uses the spec's D CAN values
  and matches all seven cases to the printed digits (e.g. `155726` pooled n 1701, DEL 0.9992211).
  Its F/R cross-check now compares against v24 run on the same frames instead of stored numbers.
  `ExtractorV24ReferenceTest` is deleted: its references came from the frame-count pick. The
  `WheelRatioParityTest` reference JSONs predate pinning and must be regenerated before use.
- **Item 4, `PUT`** — see [What the file server may do](#what-the-file-server-may-do-read-broadly-delete-narrowly).
  `/health` version 3.
- **Item 5, a stated reason.** A capture without D CAN yields a row with no ratios and
  `"reject": {"code", "why"}`, codes `no_d_can`, `d_can_ambiguous`, `d_can_incomplete`, and the
  row log line says `REJECTED`. **Deliberately not a `void`**, although the spec suggested one: a
  void condemns the whole session, and a segment without D CAN says nothing about the ESC's
  sensors (the dongle or logger lost the bus, or the car was keyed off). Raised with the owner and
  the algorithm session. Schema stays 2 (an added nullable field).
- **Item 6.** The `0x1C`/`0x1E` comment now says it marks a mid-capture key cycle.
- **Items 7-11.** Rows assert `proc` from a constant and nothing reads a CSV (7). References not
  re-derived (8). Steering estimator unchanged, nothing built for the silent re-zero (9, 10). The
  logger's negative timestamps were fixed in build 23; the 2026-09-25 captures the algorithm
  session found were written before it was installed (first data line already negative, ticks in
  whole milliseconds) (11). The frozen-baseline question is left open, and nothing here makes it
  harder to revisit.

**`reject` and `void` can both be set, by design** (agreed with the algorithm session 2026-09-28,
now in the spec's §8a item 5). `void` counts ESC faults on any channel that carries `0x208`, so a
missing D CAN dongle with `0x14` on the gateway's copy gives `void ["esc_fault"]` and `reject
no_d_can` together, and the fault still condemns the session. Fault detection is inclusive (a
missed fault means bad data trusted); measurement is strict (a missed measurement only costs a
drive the logs can reproduce). The `0x208` co-presence guard against C CAN's unrelated `0x200`
holds on all 255 C CAN bus-observations in the corpus (algorithm session,
`tpms_ccan_fault_guard.py`), and the owner has ruled C and D CAN are never on the same bus, so
no stronger guard is planned.

**Verified:** `:tpms` 130 (5 env-gated skips), `:cancore` 64 (1); `:coda`, `:vtrux`, `:p914`,
`:companion` build. New tests: D CAN selection and `reject` in `DriveRowProducerTest` (8),
D CAN-only pairing in `GpsRateAccumulatorTest` (4), PUT in `LogFileServerTest` (5), and
`GpsBusSelectionRealLogTest`: every frame of `coda_20260926_155726_T0` (713,507) through the live
path decides D CAN after 20 frames, on the extractor's channel, and never changes (the withdrawn
rule flipped 11,468 times on `0x200` in one such segment). Mutation-checked: PUT replacing, PUT
anywhere, no body check, no pinning, no ambiguity test, presence-as-rival, live any-bus, live
without the per-segment reset — each fails at least one test.

---

## On the car — build 29

`coda-debug (29).apk`, dropped 2026-09-26 to `E:\Google Drive\To Seafile\`, sha256
`d3307ab53299f7975f39b315547f58c00ac4acc7795c5504487cf9b537c18910`. Built after all tests passed
(`:tpms` 118, `:cancore` 59; skips are env-gated only, and both extractor reference tests pass on
the real logs). Contents:

- the immutable-fragment TPMS store, per-minute partial rows, and `/tree` on the file server
  ([Storage and sync](#storage-and-sync--immutable-fragments-and-what-the-server-may-do-with-them));
- proc 3, 20 Nm on every contrast ([Proc 3](#proc-3--20-nm-on-every-contrast-build-29));
- the GPS fix-time guard, the emulator harness (ADB-only) and the `0x600` lamp slot with transmit
  **off on the car** (`TPMS_LAMP_TX_ON_CAR = false`), and the transmitter scheduling fixes.

The car checklist is in `notes/plans/coda-tpms-fragment-store.md` § On the car with build 29.

**Not installed, and should not be (2026-09-27).** The spec's §8a handoff redefines proc 3 to
include pinning the ratios to D CAN, and build 29 still picks the dominant bus while tagging its
rows proc 3. The owner confirmed build 29 never went on the car, so the redefined proc 3 keeps its
number. Installing build 29 now would put proc-3 rows from two different rule sets into the store.
Its successor carries the §8a items.

## On the car — build 24 (25, 26, 27)

**Install `coda-debug (27).apk`**, sha256
`0dbb006c911658bba3b5f0a194cf60c152ddc4467efedcb72966418163dce8a8`: build 26 plus `proc: 2` on every
drive row (processing version, distinct from `schema`; spec section 4). The detector does not read
it yet. An untagged row is resolved by structure: `ratios.DEL.n` present means 2, else 1.

`coda-debug (26).apk`, sha256
`0807492012de4f87873b9f1def834798173f9f0879e68162accf7ce8991407dc`: build 25 plus the fast path
through the same per-contrast floor (the 6 psi threshold was measured when every drive's F/R had
the full sample set), and a LEARNING line that names a contrast still short of its floor
("F/R 120 of 300 - needs steady highway"). `:tpms` 89.

`coda-debug (25).apk`, sha256
`d98c66cd5f80304e2ef61bfff8e36ec661ff4f89ef1a264f322dca597b2d79b4`, was build 24 plus one detector change the algorithm session specced after 24 was dropped
(`min_n_contrast`, spec section 1): each contrast of a pooled set (learning pool or window) needs
300 samples of its own, not just more than zero. One F/R sample has sd 0.0029, so an F/R mean of
5 is 2.9 psi of noise on a corner, past the 2.5 psi advisory; at 300 it is 0.38 psi. A short window
logs a `skip` event and is not scored; the drive stays in the window. The fast path runs only on a
drive with all three contrasts, and the baseline does not freeze while a contrast is short. Mirrors
the prototype's `pooled(recs, min_n)`; detector parity regenerated and exact. `:tpms` 87.


`coda-debug (24).apk`, dropped 2026-09-26 to `E:\Google Drive\To Seafile\`, sha256
`1ce51e6e0353c571126a6818ff2f9cff6eabfa6a212e3a31a530e2d4e525cac7`. Owner: "roll everything into
v24 (including the incoming proposed updates - which I approve)", and on the thresholds, "do
everything in V24". Tests: `:tpms` 86, all passing, with both extractor checks run against real logs
(the legacy corpus parity and the v24 reference); `:cancore` 35.

**What build 23's first day showed** (2026-09-26, one qualifying drive, `coda_20260926_155726`):
- The app's rows and the algorithm session's independent Python agree: pooled n 944 on both,
  DEL within 1.9e-6.
- The rows were written; Seafile on the head unit uploaded the TPMS file once at 127 bytes and did
  not re-upload it (owner re-uploaded by hand). Storage stays as it is (owner decision, see the plan
  file).
- Build 23's timing fix holds on real data: 0 negative timestamp steps after it, 781 and 670 in
  the two logs before it, same afternoon.

**What build 24 changes:**
- **Page 3 scales to its space.** The head unit gave the page 683 x 400 dp, not the AVD's
  1024 x 600, and the +/- buttons were cut to slivers. Every size now scales by one factor, text in
  dp with a 9 dp floor. The hardware report now has a `display` block, so the density is on record.
- **Catch-up** covers an epoch with no rows yet (see Drive rows).
- **Steering centre from fast samples** (above 60 km/h on the four-wheel mean, strictly greater,
  on the wheel grid; used once there are 200, else the all-samples median, tagged `"all"`). The
  recovered `coda_20260924_004341` went from 617 samples to none under the all-samples centre,
  because slow manoeuvring with the wheel turned dragged it 35.7 deg off. The live GPS channel uses
  the same rule.
- **Torque cap per contrast, 40 Nm (F/R 20 Nm), steadiness 2%.** The old 20 Nm cap was below the
  owner's normal cruising torque (median 27.5 Nm straight and steady above 60 km/h) and kept 11 s
  of the drive; the new filters keep 56 s (n 944 -> 5019). Torque barely moves DEL and L/R
  (+0.00016, +0.00020 over 0-40 Nm) but moves F/R ten times as much (+0.00155), hence the split.
  Per-drive |torque| mean and sd are stored so any residual bias can be measured.
- **Per-band ratio sums** in every row, so a per-speed-band baseline can be built later from rows
  alone. Under the old filters one drive read DEL 0.99939 at 40 mph and 0.99917 on the freeway,
  about 2 psi from route mix alone.
- **Detector pools each contrast over its own samples** (F/R has fewer), and skips a drive with no
  F/R samples. Rows without per-ratio n pool exactly as before (the detector parity still passes).
  Sent to the algorithm session to ratify and mirror in the prototype.
- **GPS:** elevation only while the wheels show 5 km/h or more (`elev.parked` counts the rest).
  Parked, build 23 logged 10 m of climb and none of descent in five minutes. The open segment's
  block is saved every 60 s to app-internal storage, and catch-up uses it (`source: "snapshot"`,
  up to 60 s short), because a segment that ends in a power cut lost its block before, i.e. the
  last segment of most drives. `gps.schema` is 2: `strict` follows the new filters.

**End-to-end on the AVD at 240 dpi before the drop:** page 3 renders fully; SET wrote the epoch;
`coda_20260926_155726` T0 and T1 pushed and touched after the SET were picked up by catch-up on
restart. The T0 row matches the algorithm session's v24 reference (n 3293, F/R n 1279, fast centre
19599, all five ratios). T1 uses the session-so-far centre (19598 vs 19596 alone), n 1724. Page 3:
"1 of 3 drives, 5017 of 2400 samples". Hardware report: `density_dpi` 240, 682 x 384 dp.

**Car checklist, in order:**
1. Install build 27. **No new SET** (owner decision, 2026-09-26: the tyres were warm and not worth
   re-gauging). The 43.5 psi calibration stays; the epoch's one build-23 qualifying drive
   (n 944, old filters) becomes learning drive 1, 8.6% of a three-drive pool by sample count. The
   algorithm session measured the mixing by reprocessing that drive under both rule sets: baseline
   offset LF -0.061, RF +0.073, LR -0.045, RR +0.033 psi, worst 0.073 against a 2.5 psi advisory.
   L/R moves most between the rule sets (+0.000272; DEL +0.000072, F/R -0.000030). Keep Seafile off while driving (owner's workaround), start it to
   upload.
2. Page 3 fits: full-size +/- buttons, readable text.
3. Three ordinary, varied drives to learn the baseline.
4. After the first drive: rows in `CodaLogs/tpms/` with `steer_centre_src`, per-ratio `n`,
   `ratio_bands`, and a `gps` block with `schema: 2`. The last segment of the drive should have
   `gps.source: "snapshot"` if the head unit lost power at key-off.
5. The new `CodaLogs/diag/hardware_*.json` has the head unit's real `display` block.
6. Later, the deflation test, as before.

---

## On the car — build 23

`coda-debug (23).apk`, dropped 2026-09-26 to `E:\Google Drive\To Seafile\`, sha256
`32b971b7f75a955b9f6261766584c3ae02ff577a4f1325401be6ad5f7e483c3c`. Built after all tests passed:
`:tpms` 74 (both parity tests enabled), `:cancore` 35. The Vtrux APK built alongside contains no
`com/reverseit/tpms` classes and neither the location nor the sensor permission.

**What it adds over build 22:** persistent calibration files, a drive row per closed log segment,
GPS capture (speed only), the detector with fast path and void marker, the hardware report, and
the log timing fix. All of it is a prototype until tested in the car.

**End-to-end on the AVD before the drop (plan Step 6).**
- SET through page 3 wrote the calibration file (app-owned, as in the car).
- Four real sessions (2026-05-01, 06-18 x2, 08-18; 27 segments, ~1 GB) put in `CodaLogs/`;
  on restart, catch-up wrote 27 rows in ~2 minutes (4-5 s per segment), none void.
- Page 3 then showed OK, LF +4.0 / RF -3.2 / LR +0.5 / RR -1.3, "ADVISE pending, 1 of 2 drives" --
  identical to the Python prototype's `run()` on the same rows, pooled the same way.
- Pooled session n from the app's per-segment rows vs the corpus CSV's whole-session extraction:
  26971 vs 26901, 11066 vs 10749, 10956 vs 11018, 32109 vs 31963 (the running steering centre,
  as recorded under Drive rows).
- **Not testable on the AVD** (no CAN): the live segment roll feeding `SegmentWatcher`, GPS paired
  with real wheel speed, and whether `CodaLogs/` subfolders reach Seafile. The first two became
  testable on 2026-09-26 with the SLCAN harness (see [Emulator harness](#emulator-harness));
  the live roll and drive rows then passed on real traffic.

**Car checklist, in order:**
1. Grant location, choose **Precise**. Page 3's GPS line should show fixes per minute and
   satellites (it also tells whether the head unit has a receiver at all).
2. **Inflate all four to 42 psi cold, then SET.** The next three qualifying drives learn the
   baseline and should be ordinary, varied routes. Until then page 3 reads "Learning - not yet
   monitoring".
3. Within a day, on the Seafile server: `CodaLogs/diag/hardware_*.json` and
   `CodaLogs/tpms/tpms_*.jsonl`. **If either is missing, subfolders are not syncing** and the TPMS
   record is not being backed up.
4. The first build-23 log: no negative tick fields; timestamps monotonic on both channels.
5. Read the hardware report: does the head unit have a live gyro / accelerometer?
6. Later, the owner's deflation test (protocol in the plan file, Step 6). It ends in RECALIBRATE by
   design; gauge and SET afterwards.

---

## On the car — build 22

`coda-debug (22).apk`, dropped 2026-09-23 to `E:\Google Drive\To Seafile\`, sha256
`feed370845096bbfa1fecdb0671334bc2fd3e9a027449289b7a1d25704949464`, built from source last modified
2026-09-23 (the `isEcho` fail-safe) and 2026-09-21 (everything else).

**What it contains:** page 3 (TPMS calibration + imbalance display), the CAN transmit path
(disabled, zero slots — transmits nothing), the B CAN bus resolver, `CanFrame.isTx` and the `Tx`
direction column, and the `.log`-only `LogFileServer`.

**What it does not do yet:** no detection runs, so the right pane will only ever show `LEARNING`
with "Awaiting detection algorithm". **The calibration store is in-memory** — anything entered with
SET is lost when the app restarts, and nothing is written to `CodaLogs/tpms/`. Pressing SET on the
car is harmless but does not persist.

**First checks after install**, in order of how badly they would fail silently:

1. **Open the first new log and confirm column 2 reads `Rx`.** If it reads `Tx`, the Innomaker is
   returning `ECHO_ID_TX` on received frames and the whole session is being skipped by
   `influx_upload.py`. The `isEcho` narrowing makes this very unlikely, but it is the one failure
   here that loses data without any symptom.
2. Logging, green screen and specs pages behave as before.
3. Page 3 renders at the real panel's resolution, and a tap on a `+`/`−` steps once (the AVD-found
   fast-tap bug; the AVD's `input tap` is faster than a finger, so it should be fine, but the real
   touchscreen is the actual test).

---

## Resuming after a compaction

Read this file, then `../projects/coda/notes/tpms-algorithm-spec.md` sections 4-6 and
`android-tools-reference.md` before any build. State at close, 2026-09-29, updated 2026-10-04:

- **Build 31, 2026-10-04:** `coda-debug (31).apk` (sha256
  `2e2d1ee6fd3740faf2d6127fc56e35b99a633313dde210a8912f26878215b4dd`) is build 30 plus one
  change: `TPMS_LAMP_TX_ON_CAR = true`, so the car transmits `0x600` on B CAN. The owner is
  pulling the RCU and then installing it; build 30 was skipped. The next drop would be `(32)`.
  The SLCAN harness was re-run on the exact APK before install and passed (see
  [The lamp-hold prototype](#the-lamp-hold-prototype-0x600)).

- **Done:** everything in this file. Nothing half-applied; `coda-debug (29).apk` was dropped
  2026-09-26 from the current source (see [On the car — build 29](#on-the-car--build-29)).
  The plans that got it there are all complete: `notes/plans/coda-tpms-gps.md` (GPS, store, drive
  rows, detector), `notes/plans/coda-slcan-harness-0x600.md` (emulator harness, `0x600` lamp
  prototype) and `notes/plans/coda-tpms-fragment-store.md` (immutable fragments, `/tree`, and
  proc 3), which also holds the build 29 car checklist.
- **Superseded 2026-09-27:** build 29 was never installed and must not be (see
  [On the car — build 29](#on-the-car--build-29)). The spec's section 8a handoff is implemented and
  tested ([Spec 8a handoff](#spec-8a-handoff--d-can-pinning-put-and-reject-2026-09-27)), and
  `coda-debug (30).apk` was dropped 2026-09-28 with it. The checks below apply to build 30, plus:
  rows carry `reject: null` when D CAN was found. The next drop would be `(31)`. Build 30 is not
  installed yet (as of close); `(29)` is still in the dropoff folder and must be skipped.
- **Next (for the build after 29):** the owner installs it and drives. Then read what reaches the library under
  `../../CANLogs/CodaLogs/tpms/` (probe exact names or use `os.scandir`; never list `CANLogs`):
  expect `tpms_20260926T154945_000000_full.jsonl`, then small per-minute and per-segment fragments,
  and rows with `proc: 3`. Also still unread: the build 28+ hardware report in
  `../../CANLogs/CodaLogs/diag/`.
- **Tools for checking:** `notes/artifacts/tpms_fragment_parity.py` (app store vs prototype on the
  live folder); the emulator harness recipe is in [Emulator harness](#emulator-harness) and
  `../tools/tools.md`.
- **Decisions waiting on the owner:** AMEND control (interface ready, no button); tightening
  `B_CAN_ANCHOR_IDS` and the README's B CAN anchor row.
- **Needs the car:** the four "needs the car" rows in the open-items table below.
- **Coordination:** the algorithm session owns `projects/coda/notes/tpms-algorithm-spec.md` and the
  prototype; this file and everything under `android-app/` are app-side only. Changes across that
  line go as text by message, never as edits — SeaDrive syncs whole files, so even a one-line edit
  from the other machine collides.

---

## Open items

| Item | Owner |
|---|---|
| **Decision:** a capture without D CAN is recorded in a new `reject` field rather than as a `void` reason as the spec suggested, because a void condemns the whole session. The algorithm session agreed and corrected the spec (2026-09-28); the owner has not ruled | owner |
| After build 31 (build 30's checks apply unchanged): the migrated `_full` and the per-minute fragments reach the library; rows carry `proc: 3`; learning completes on the next qualifying drive | needs the car |
| SET again at the next real inflation (removes the ~0.16-0.31 psi front offset from the proc 2 / proc 3 mix in the learning pool) | needs the car |
| Confirm 42 against the doorjamb placard (service manual figure, corroborated by the DTC multiples; never read off the car) | needs the car |
| **Decision:** page 3 can read a positive corner as "this tyre is fine", but with the zero-sum split it is only the complement of another corner being low (on the AVD run, LF +4.0 is what RF -3.2 looks like from the other side). Whether to change how positives render | owner |
| Owner's deflation test (rear tyre, 8-10 psi) — first real input for the fast path and the rear psi scale | needs the car |
| Whether to tighten `B_CAN_ANCHOR_IDS` / correct the README's B CAN anchor row | **decision needed** |
| Whether to add an AMEND control — the store interface has it, the UI does not | **decision needed** |
| `0x600` lamp transmit on the car — on from build 31 (`TPMS_LAMP_TX_ON_CAR` true, RCU being removed). Check the debug log reads "transmitter ENABLED (TPMS_LAMP_TX_ON_CAR)" and the slot reaches ACTIVE (CONTENDED means an RCU is still heard), that `0x600` appears as `Tx` on B CAN in the log, then watch the dash for steady and flashing (feasibility §7a) | needs the car |
| A/B test to pin the psi scale (feasibility §7b) | needs the car |

---

## Related

- `../projects/coda/notes/indirect-tpms-feasibility.md` — the method, and why it works
- `../projects/coda/notes/plans/tpms_app_algorithm.md` — algorithm/storage plan
- `../projects/coda/notes/tpms-algorithm-spec.md` — algorithm session's spec: file format, five
  states, epoch operations, filter settings
- `android-coda-app-notes.md` — the rest of the Coda app
- `android-tools-reference.md` — build and deploy
- `notes/avd-emulator-bringup.md` — the head-unit AVD
