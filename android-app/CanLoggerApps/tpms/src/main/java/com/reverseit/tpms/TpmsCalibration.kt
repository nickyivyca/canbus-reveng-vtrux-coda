package com.reverseit.tpms

import kotlinx.coroutines.flow.StateFlow

/**
 * The seam between the indirect-TPMS **UI** and the indirect-TPMS **algorithm**.
 *
 * The app's settings page depends only on [TpmsCalibrationStore]. The implementation is
 * [FileTpmsCalibrationStore] over [TpmsEpochStore]; the file format and the detector are specified
 * by the algorithm session in `projects/coda/notes/tpms-algorithm-spec.md`.
 *
 * Background: `projects/coda/notes/indirect-tpms-feasibility.md` and its plan file
 * `projects/coda/notes/plans/tpms_app_algorithm.md`. Two facts from there shape this interface:
 *
 *  - **The learn event has to be explicit and user-initiated.** The per-wheel mechanical baseline
 *    is the same size as the signal, so absolute `DEL` means nothing without one -- but the leak is
 *    slow and continuous (0.051 psi/day), so anything that quietly re-learns the baseline from
 *    recent drives tracks the leak and reports nothing wrong, forever. Hence a SET button: the app
 *    is told "I have just set the pressures", it never infers it.
 *  - **Ambient temperature is entered by hand.** `0x391` B3 `OPAirTemp` is on the bus but the DBC
 *    records it as unreliable -- reads ~+12 degF high with a varying +5..+20 degF error, so it is
 *    not offset-calibratable. A typed reading from a real thermometer is the only trustworthy one.
 */

/**
 * The four wheels, each carrying its own display label.
 *
 * **Everything per-corner is keyed by this rather than held in four positional fields.** Four
 * adjacent same-typed parameters are transposable at a construction site: it compiles, the numbers
 * stay entirely plausible, and the consequence is the driver inflating the wrong tyre on the
 * strength of a confident display. The car-shaped grid on screen guards against misreading a
 * corner; keying guards against the data arriving pre-swapped, which no amount of layout can catch.
 *
 * Carrying [label] here rather than passing it alongside the data means a cell names its corner
 * exactly once, so the heading and the value it sits above cannot disagree either.
 */
enum class Corner(val label: String) {
    LF("FRONT LEFT"),
    RF("FRONT RIGHT"),
    LR("REAR LEFT"),
    RR("REAR RIGHT"),
}

/**
 * One user-entered calibration: the four gauge readings and the ambient temperature at the moment
 * the tyres were known-good.
 *
 * Wheel order matches the CAN signal names throughout the project (`WheelSpeed_LF` etc.) rather
 * than any driver's-eye convention.
 */
data class TpmsCalibrationEntry(
    val lfPsi: Float,
    val rfPsi: Float,
    val lrPsi: Float,
    val rrPsi: Float,
    val ambientC: Float,
    /** Wall-clock ms when SET was pressed. */
    val setAtMs: Long,
) {
    fun psi(corner: Corner): Float = when (corner) {
        Corner.LF -> lfPsi
        Corner.RF -> rfPsi
        Corner.LR -> lrPsi
        Corner.RR -> rrPsi
    }

    companion object {
        /**
         * Build from a keyed map, so no caller has to get four same-typed arguments in the right
         * order. **All four corners are required**: a missing one is a caller bug, and silently
         * filling it with a placard figure would record a pressure nobody measured.
         */
        fun of(psi: Map<Corner, Float>, ambientC: Float, setAtMs: Long): TpmsCalibrationEntry {
            require(Corner.entries.all { it in psi }) { "calibration needs all four corners, got ${psi.keys}" }
            return TpmsCalibrationEntry(
                lfPsi = psi.getValue(Corner.LF),
                rfPsi = psi.getValue(Corner.RF),
                lrPsi = psi.getValue(Corner.LR),
                rrPsi = psi.getValue(Corner.RR),
                ambientC = ambientC,
                setAtMs = setAtMs,
            )
        }
    }
}

/**
 * The five states the detector can be in. Names and meanings come from the algorithm session's
 * specification -- do not redefine them here.
 *
 * **[STALE] is not a mild state.** It means a fill was detected that the user never announced, so
 * the frozen baseline no longer describes the tyres and every corner number computed against it is
 * meaningless. It demands recalibration. An earlier version of this file used "stale" to mean
 * merely "no qualifying drive recently", which would have rendered a recalibrate-now condition as
 * soft grey text; the benign case is covered by [LEARNING] and by the detail line instead.
 */
enum class TpmsState {
    /** Baseline still being learned from the first qualifying drives. Waiting, not actionable. */
    LEARNING,

    /** All four corners within tolerance. */
    OK,

    /** A corner has moved enough to mention but not enough to warn. */
    ADVISE,

    /** A corner is low enough to act on. */
    WARN,

    /**
     * An unannounced fill was detected: the baseline is dead and the numbers mean nothing until
     * the user recalibrates. Actionable, and deliberately rendered unlike [LEARNING].
     */
    STALE,
}

/**
 * One corner's output.
 *
 * Both fields coexist rather than a global relative/absolute mode flag, because that is what makes
 * the eventual cutover free: `absolutePsi = calibrationPsi + deltaPsi + commonModePsi`, and
 * `commonModePsi` is null today because the ratio discriminants cancel common mode by construction.
 * When the GPS common-mode channel lands, [absolutePsi] simply starts being non-null and the same
 * four cells begin showing absolute pressure with no UI change.
 */
data class TpmsCornerEstimate(
    /** Change since the calibration, in psi. Signed. Null if not yet computable. */
    val deltaPsi: Float? = null,

    /** True pressure in psi, or null while common mode is unavailable. */
    val absolutePsi: Float? = null,
)

/**
 * The algorithm side's output, as the UI needs it.
 *
 * [detail] is free text so the algorithm can explain itself -- "312 / 800 samples", "no qualifying
 * drive since Tuesday" -- without this file modelling a state machine it does not own.
 *
 * A null corner value renders as absent, never as zero. That matches the rule the specs page
 * already follows: a signal that is not there must not look like a reading of zero. Precision is
 * about 0.7 psi 1 sigma per corner from a single drive, so the UI renders one decimal place and
 * no more.
 */
data class TpmsEstimate(
    /** Keyed rather than four positional fields -- see [Corner]. Absent keys render as absent. */
    val corners: Map<Corner, TpmsCornerEstimate> = emptyMap(),
    val state: TpmsState = TpmsState.LEARNING,
    /** One short line under the grid explaining the current state. Null renders nothing. */
    val detail: String? = null,
    val updatedAtMs: Long? = null,
) {
    /**
     * A corner's estimate, or an empty one when the map has no entry for it.
     *
     * Degrading to absent rather than throwing is deliberate: a partially-populated map renders as
     * dashes for the corners it lacks, which is honest, instead of taking down the settings page.
     */
    operator fun get(corner: Corner): TpmsCornerEstimate =
        corners[corner] ?: TpmsCornerEstimate()
}

/**
 * Holds the current calibration and accepts new ones -- what the settings page needs from the
 * calibration files, and nothing about how they are laid out on disk.
 */
interface TpmsCalibrationStore {

    /** The most recent calibration, or null if the user has never pressed SET. */
    val lastEntry: StateFlow<TpmsCalibrationEntry?>

    /**
     * Current per-wheel estimate, shown on the right of the settings page. Starts at
     * [TpmsState.LEARNING] and is driven entirely by the algorithm side.
     */
    val estimate: StateFlow<TpmsEstimate>

    /**
     * The calibration [undoLast] would restore, or null when undo is unavailable.
     *
     * Exposed as a value rather than a boolean so the UI can name what it is about to restore. An
     * undo control that does not say where it lands is not usable on a car dashboard.
     *
     * **Availability is the store's decision, and the rule is "no qualifying drive has been
     * recorded in the current epoch yet".** Until that first drive, nothing has been measured
     * against the new baseline and the previous epoch can be resumed exactly. After it, undo goes
     * null and the control disappears. The store also returns null when there is no previous
     * calibration to land on, since undoing the first one would leave no baseline at all — the
     * state undo exists to rescue the user from.
     */
    val undoTarget: StateFlow<TpmsCalibrationEntry?>

    /**
     * Record a new calibration. Called on the main thread from the SET button, so an implementation
     * that writes to disk must move that off-thread itself.
     *
     * Semantically this is "the tyres are correct as of now": it should reset the learned baseline,
     * not average into it.
     */
    fun set(entry: TpmsCalibrationEntry)

    /**
     * Discard the most recent calibration and resume the one before it.
     *
     * **This must restore the previous epoch, not re-apply its numbers.** The distinction is the
     * whole point of the operation. Calling `set(previousEntry)` would look identical in the UI and
     * be useless: it opens a *third* epoch with an empty baseline, so the user still loses the
     * accumulated learning and still ends up in [TpmsState.LEARNING] — which is exactly the cost
     * they invoked undo to avoid. Undo has to make the accidental calibration not have happened:
     * discard its epoch, reinstate the previous epoch's frozen baseline and its accumulated drives.
     *
     * Motivating case, from the owner: SET was pressed by accident, and re-calibrating properly
     * would mean going out and gauging four tyres. Undo exists so a stray press costs nothing.
     *
     * Any drives recorded against the discarded epoch are discarded with it. That is correct —
     * they were measured against a baseline the user is declaring invalid — and cheap, because
     * everything except GPS sums and ambient temperature is regenerable from the CAN logs.
     *
     * No-op when [undoTarget] is null.
     */
    fun undoLast()

    /**
     * Correct the *recorded pressure values* of the current calibration without touching the epoch,
     * the baseline or the accumulated history.
     *
     * This is possible because a calibration record does two independent jobs, and only one of them
     * is load-bearing for detection:
     *
     *  1. **Event marker** — "the pressures were just set to known-good". This anchors the `DEL`
     *     baseline, and is the thing that must never be re-learned automatically.
     *  2. **Pressure values** — the four psi and the temperature. These are used *only* to turn
     *     relative deltas into absolute pressures. They never feed the baseline.
     *
     * So a mistyped number is not a bad calibration, it is a bad annotation on a good one, and
     * fixing it needs no new epoch and costs no learning. Amend stays available indefinitely —
     * including a month and many drives later — precisely because the entered numbers were never
     * part of what was learned.
     *
     * Distinct from [set], which asserts (1) and therefore correctly costs the learning period, and
     * from [undoLast], which withdraws (1) entirely.
     *
     * Implementations should **append** an amendment record rather than rewriting the original, so
     * the file stays strictly append-only -- which is what makes a truncated final line from a
     * mid-append upload safe -- and so the originally-entered values remain auditable. The
     * amendment record may carry its own timestamp for audit; the calibration's own timestamp, and
     * therefore the epoch's identity, must not move.
     *
     * **Takes values rather than a [TpmsCalibrationEntry] on purpose.** An entry carries `setAtMs`,
     * so an amend that accepted one could change the epoch's timestamp and silently become a [set]
     * -- the same class of trap as reimplementing [undoLast] via [set], and equally invisible in
     * the UI. Not being able to express the timestamp here makes that impossible rather than merely
     * discouraged. (Verified against
     * `projects/coda/notes/artifacts/tpms_app_prototype.py`, whose `amend()` takes no timestamp for
     * the same reason.)
     *
     * Keyed by [Corner] rather than four floats, so the correction cannot land on the wrong wheel.
     */
    fun amend(psi: Map<Corner, Float>, ambientC: Float)

    /**
     * Why the last operation did not reach the disk, or null when it did. Shown on the page: a SET
     * that failed to save while the page looked as though it had is worse than no SET button.
     */
    val storageError: StateFlow<String?>
}
