package com.reverseit.coda

import com.reverseit.tpms.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Page 3 -- settings. Currently just indirect TPMS: calibration entry on the left, the detector's
 * per-wheel output on the right.
 *
 * Reached by swiping right from the specs page. Nothing here changes vehicle behaviour: SET records
 * what the tyres were inflated to, which is the explicit learn event the detection method requires
 * (see [TpmsCalibration]).
 *
 * ```
 *  +---------------------------+---------------------------+
 *  |  TPMS CALIBRATION         |  PRESSURE IMBALANCE       |
 *  +-------------+-------------+-------------+-------------+
 *  | FRONT LEFT  | FRONT RIGHT | FRONT LEFT  | FRONT RIGHT |
 *  |   [ 42.0 ]  |   [ 42.0 ]  |    -0.4     |    +0.1     |
 *  |   [-] [+]   |   [-] [+]   |             |             |
 *  +-------------+-------------+-------------+-------------+
 *  | REAR LEFT   | REAR RIGHT  | REAR LEFT   | REAR RIGHT  |
 *  |   [ 42.0 ]  |   [ 42.0 ]  |    +0.2     |    -0.1     |
 *  |   [-] [+]   |   [-] [+]   |             |             |
 *  +-------------+-------------+-------------+-------------+
 *  | AMBIENT     |             |  status line              |
 *  |   [  --  ]  |   [ SET ]   |                           |
 *  |   [-] [+]   |             |                           |
 *  +-------------+-------------+---------------------------+
 * ```
 *
 * Design constraints, which are why it looks the way it does:
 *  - **Both grids are laid out as the car is seen from above** -- front pair on the top row, left
 *    pair in the left column -- so a number's position is the wheel it belongs to. Reading a value
 *    off the wrong corner is the easiest mistake available here, and the layout is the cheapest
 *    defence against it. Both grids share the arrangement, so a corner lines up across the divider.
 *  - **The panel is 1024x600 landscape and the soft keyboard covers most of it.** So +/- buttons are
 *    the primary input and the keyboard is opt-in: tap a number to type it, otherwise never see one.
 *  - **The four tyre boxes preload to the door-placard pressure**
 *    ([CodaConstants.DEFAULT_TIRE_PSI]), because calibration normally happens immediately after
 *    filling to exactly that figure. Stepping there from blank would be ~420 presses per tyre.
 *  - **Ambient starts blank**, which is what stops the preload from becoming a hazard: SET is
 *    disabled until every box has a value, so an untouched form can never be submitted. The user
 *    has to enter at least one real reading before the four defaults can go anywhere.
 *  - **Ambient is typed, not read from the bus.** `0x391` B3 is unreliable by a varying amount; see
 *    [TpmsCalibration].
 */

// --- entry ranges and steps ------------------------------------------------

private const val PSI_STEP = 0.1f
private const val PSI_MIN = 0f
private const val PSI_MAX = 60f

private const val AMBIENT_STEP = 0.5f
private const val AMBIENT_MIN = -40f
private const val AMBIENT_MAX = 60f

/**
 * Where the ambient box lands on its first +/- press. A starting point for stepping, never a
 * submitted value -- the box is blank until the user acts on it.
 *
 * The tyre boxes have no equivalent: they are preloaded with [CodaConstants.DEFAULT_TIRE_PSI] and
 * re-seed to it if cleared.
 */
private const val SEED_AMBIENT_C = 20.0f

// --- press-and-hold repeat -------------------------------------------------

/** Delay before a held button starts repeating. Long enough that a tap is one step. */
private const val HOLD_DELAY_MS = 400L
/** Repeat interval for the first [ACCEL_AFTER_REPS] repeats, then [FAST_REPEAT_MS]. */
private const val SLOW_REPEAT_MS = 90L
private const val FAST_REPEAT_MS = 30L
private const val ACCEL_AFTER_REPS = 10

private val PANEL_BG = Color(0xFF101010)
private val BOX_BG = Color(0xFF1E1E1E)
private val BOX_BORDER = Color(0xFF4A4A4A)
private val LABEL = Color(0xFFBBBBBB)
private val MUTED = Color(0xFF8A8A8A)
private val ABSENT = Color(0xFF6A6A6A)
private val ACCENT = Color(0xFF3DDC84)

/** Amber for the armed undo -- deliberately not the green SET accent, and not a warning red. */
private val UNDO_ACCENT = Color(0xFFE0A030)

/** A calibration operation that did not reach the disk. */
private val STORAGE_ERROR = Color(0xFFFF5050)

/** How long an armed UNDO stays primed before disarming itself. */
private const val UNDO_ARMED_MS = 5_000L

@Composable
fun SettingsScreen(
    lastEntry: TpmsCalibrationEntry?,
    undoTarget: TpmsCalibrationEntry?,
    estimate: TpmsEstimate,
    onSet: (TpmsCalibrationEntry) -> Unit,
    onUndo: () -> Unit,
    modifier: Modifier = Modifier,
    storageError: String? = null,
    gpsStatus: GpsRateAccumulator.Status = GpsRateAccumulator.Status(),
    onRequestGps: () -> Unit = {},
) = BoxWithConstraints(modifier.fillMaxSize().background(PANEL_BG)) {
    val factor = minOf(1f, maxWidth / DESIGN_WIDTH, maxHeight / DESIGN_HEIGHT)
    val k = PageScale(factor, LocalDensity.current)
    CompositionLocalProvider(LocalPageScale provides k) {
        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = k.dp(14), vertical = k.dp(8)),
        ) {
            CalibrationPane(
                lastEntry = lastEntry,
                undoTarget = undoTarget,
                storageError = storageError,
                onSet = onSet,
                onUndo = onUndo,
                modifier = Modifier.weight(1f).fillMaxHeight(),
            )
            Box(
                Modifier
                    .width(1.dp)
                    .fillMaxHeight()
                    .padding(vertical = k.dp(6))
                    .background(BOX_BORDER)
            )
            EstimatePane(
                estimate = estimate,
                gpsStatus = gpsStatus,
                onRequestGps = onRequestGps,
                modifier = Modifier.weight(1f).fillMaxHeight(),
            )
        }
    }
}

/**
 * The layout space this page was designed and checked in: the AVD's 1024 x 600 mdpi. The head unit
 * gives it far less -- its first build 23 photo (2026-09-26) matched the AVD run at 240 dpi, i.e.
 * 683 x 400 dp -- and at fixed sizes the rows overflowed and the +/- buttons were cut to slivers.
 */
private val DESIGN_WIDTH = 1024.dp
private val DESIGN_HEIGHT = 600.dp

/**
 * Every size on this page, scaled by one factor so the page looks the same in whatever space it
 * gets. Text is sized in dp rather than sp so a system font scale cannot overflow the fixed-height
 * boxes either; the page is a fixed panel layout, not reflowing text. Text never shrinks below
 * [MIN_TEXT_DP], which only affects the captions and status lines, so they stay readable while
 * driving.
 */
private class PageScale(val factor: Float, private val density: Density) {
    fun dp(v: Int): Dp = (v * factor).dp
    fun sp(v: Int): TextUnit = with(density) { maxOf(v * factor, MIN_TEXT_DP).dp.toSp() }
}

private const val MIN_TEXT_DP = 9f

private val LocalPageScale = staticCompositionLocalOf { PageScale(1f, Density(1f)) }

// --- left pane: calibration entry -------------------------------------------

@Composable
private fun CalibrationPane(
    lastEntry: TpmsCalibrationEntry?,
    undoTarget: TpmsCalibrationEntry?,
    storageError: String?,
    onSet: (TpmsCalibrationEntry) -> Unit,
    onUndo: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val k = LocalPageScale.current
    // Keyed by Corner rather than four separate variables, so a cell cannot be wired to the wrong
    // wheel -- the entry side of the same hazard described on [Corner]. Getting it wrong here would
    // be worse than on the display side: it poisons the baseline for two corners at once.
    // Tyres preload to the placard figure; ambient deliberately does not. See the file KDoc.
    var psi by remember {
        mutableStateOf(Corner.entries.associateWith { CodaConstants.DEFAULT_TIRE_PSI as Float? })
    }
    var ambient by remember { mutableStateOf<Float?>(null) }

    val complete = ambient != null && Corner.entries.all { psi[it] != null }

    Column(modifier = modifier.padding(end = k.dp(12))) {
        CalibrationHeader(
            subtitle = lastEntry.summary(),
            storageError = storageError,
            undoTarget = undoTarget,
            onUndo = onUndo,
        )

        // Three equal rows: front pair, rear pair, then ambient alongside SET.
        val onPsiChange: (Corner, Float?) -> Unit = { corner, v -> psi = psi + (corner to v) }

        Column(Modifier.weight(1f)) {
            GridRow {
                CornerEntryCell(Corner.LF, psi, Modifier.weight(1f), onPsiChange)
                CornerEntryCell(Corner.RF, psi, Modifier.weight(1f), onPsiChange)
            }
            GridRow {
                CornerEntryCell(Corner.LR, psi, Modifier.weight(1f), onPsiChange)
                CornerEntryCell(Corner.RR, psi, Modifier.weight(1f), onPsiChange)
            }
            GridRow {
                EntryCell("AMBIENT", "C", ambient, AMBIENT_STEP, AMBIENT_MIN, AMBIENT_MAX,
                    SEED_AMBIENT_C, Modifier.weight(1f)) { ambient = it }
                SetCell(
                    enabled = complete,
                    replacing = lastEntry != null,
                    modifier = Modifier.weight(1f),
                    onClick = {
                        onSet(
                            TpmsCalibrationEntry.of(
                                psi = psi.mapValues { (_, v) -> v ?: CodaConstants.DEFAULT_TIRE_PSI },
                                ambientC = ambient ?: SEED_AMBIENT_C,
                                setAtMs = System.currentTimeMillis(),
                            )
                        )
                    },
                )
            }
        }
    }
}

/** One row of a 2-column grid. Equal height, equal width cells. */
@Composable
private fun ColumnScope.GridRow(content: @Composable RowScope.() -> Unit) {
    val k = LocalPageScale.current
    Row(
        modifier = Modifier.fillMaxWidth().weight(1f),
        horizontalArrangement = Arrangement.spacedBy(k.dp(12)),
        verticalAlignment = Alignment.CenterVertically,
        content = content,
    )
}

/**
 * Left-pane header: title, the last-set line, and the UNDO control beside it.
 *
 * UNDO sits next to the line it undoes, and only exists while the store says undo is available --
 * that is, while the current epoch has recorded no qualifying drive, so the previous baseline can
 * be resumed exactly. It disappears the moment the first drive lands.
 *
 * **Arm-then-confirm, because the thing it recovers from is a stray press.** A one-tap undo would
 * have the same failure mode as the SET it is rescuing, and undoing a good calibration by accident
 * is not itself undoable without going out and gauging four tyres. The armed state also names the
 * calibration being restored, so the second tap is made with the destination in view.
 */
@Composable
private fun CalibrationHeader(
    subtitle: String,
    storageError: String?,
    undoTarget: TpmsCalibrationEntry?,
    onUndo: () -> Unit,
) {
    val k = LocalPageScale.current
    var armed by remember { mutableStateOf(false) }
    // Disarm on a timer so a half-finished undo cannot sit primed indefinitely, and disarm
    // immediately if undo stops being available underneath us (a drive landed).
    LaunchedEffect(armed, undoTarget) {
        if (armed && undoTarget != null) {
            delay(UNDO_ARMED_MS)
            armed = false
        } else if (undoTarget == null) {
            armed = false
        }
    }

    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text("TPMS CALIBRATION", color = Color.White, fontSize = k.sp(18), fontWeight = FontWeight.Bold)
            // A storage failure replaces the last-set line rather than sitting beside it: that line
            // is read back from disk, so after a failed SET it still names the old calibration, and
            // showing it unqualified would look like the SET had worked.
            Text(
                text = when {
                    storageError != null -> storageError
                    armed -> "Restores: %s".format(undoTarget.summaryShort())
                    else -> subtitle
                },
                color = when {
                    storageError != null -> STORAGE_ERROR
                    armed -> UNDO_ACCENT
                    else -> MUTED
                },
                fontSize = k.sp(11),
            )
        }
        if (undoTarget != null) {
            Button(
                onClick = { if (armed) { armed = false; onUndo() } else armed = true },
                shape = RoundedCornerShape(5.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (armed) UNDO_ACCENT else Color(0xFF2E2E2E),
                    contentColor = if (armed) Color.Black else Color(0xFFDDDDDD),
                ),
                contentPadding = PaddingValues(horizontal = k.dp(12), vertical = k.dp(0)),
                modifier = Modifier.height(k.dp(40)),
            ) {
                Text(
                    text = if (armed) "CONFIRM UNDO" else "UNDO",
                    fontSize = k.sp(13),
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }
    Spacer(Modifier.height(k.dp(4)))
}

private fun TpmsCalibrationEntry?.summaryShort(): String {
    if (this == null) return "-"
    val at = SimpleDateFormat("MM-dd HH:mm", Locale.US).format(Date(setAtMs))
    return "%s  %.1f / %.1f / %.1f / %.1f psi".format(at, lfPsi, rfPsi, lrPsi, rrPsi)
}

@Composable
private fun PaneHeader(title: String, subtitle: String) {
    val k = LocalPageScale.current
    Text(title, color = Color.White, fontSize = k.sp(18), fontWeight = FontWeight.Bold)
    Text(subtitle, color = MUTED, fontSize = k.sp(11))
    Spacer(Modifier.height(k.dp(4)))
}

/** The SET button, occupying the cell beside AMBIENT. */
@Composable
private fun SetCell(
    enabled: Boolean,
    replacing: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val k = LocalPageScale.current
    Column(
        modifier = modifier.fillMaxHeight(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Button(
            onClick = onClick,
            enabled = enabled,
            shape = RoundedCornerShape(6.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = ACCENT,
                contentColor = Color.Black,
                disabledContainerColor = Color(0xFF2A2A2A),
                disabledContentColor = ABSENT,
            ),
            modifier = Modifier.fillMaxWidth().height(k.dp(72)),
        ) {
            Text("SET", fontSize = k.sp(26), fontWeight = FontWeight.Bold)
        }
        Spacer(Modifier.height(k.dp(6)))
        // Three captions, each answering the question the user actually has at that moment.
        //
        // "Inflate first" is not a nicety. The method is differential: it reports change since the
        // baseline and is blind by construction to all four tyres being equally low. So calibrating
        // at whatever the tyres happen to read records that state as the reference, and if they are
        // uniformly soft the app will never say so -- it will only ever report divergence from
        // soft. On this car today that is not hypothetical: measured 31/35/33/33 against a 42
        // placard decomposes into -9 psi common to all four plus a 4 psi front differential, and
        // only the differential part is visible. "Known-good", which this said before, implied the
        // app had checked. It cannot.
        //
        // Once a calibration exists the caption instead names the recovery path, which needs to be
        // visible at the moment of action: the boxes keep their values after a SET, so correcting
        // one is edit-the-box then SET again, with no file to find and delete.
        Text(
            text = when {
                !enabled -> "Enter ambient to enable"
                replacing -> "Replaces the current calibration"
                else -> "Inflate to spec first - this becomes the reference"
            },
            color = ABSENT,
            fontSize = k.sp(10),
            textAlign = TextAlign.Center,
        )
    }
}

private fun TpmsCalibrationEntry?.summary(): String {
    if (this == null) return "Never calibrated"
    val at = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US).format(Date(setAtMs))
    return "Last set %s -- LF %.1f  RF %.1f  LR %.1f  RR %.1f psi at %.1f C"
        .format(at, lfPsi, rfPsi, lrPsi, rrPsi, ambientC)
}

// --- right pane: detector output --------------------------------------------

@Composable
private fun EstimatePane(
    estimate: TpmsEstimate,
    gpsStatus: GpsRateAccumulator.Status,
    onRequestGps: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val k = LocalPageScale.current
    // Absolute pressure appears per corner as soon as the common-mode channel can supply it, so
    // the heading follows the data rather than a mode flag.
    val absolute = estimate.anyAbsolute()

    Column(modifier = modifier.padding(start = k.dp(14))) {
        // IMBALANCE, not CHANGE, while the numbers are relative -- a correctness matter, not a
        // wording preference.
        //
        // The ratio discriminants cancel common mode exactly, so a corner shows its deviation from
        // the other three, not its change since calibration. On this car's measured 31/35/33/33
        // against a 42 placard, a correct calibration followed by that state developing renders:
        //
        //     LF  11 psi down  ->  -2.7      RF   7 psi down  ->  +2.7
        //     LR   9 psi down  ->   0.0      RR   9 psi down  ->   0.0
        //
        // Under a "CHANGE" heading the RF cell asserts that a tyre seven psi down has gone UP, and
        // the rear pair assert that nine psi down is no change at all. The numbers are right as
        // imbalance and false as change, so the heading is what gives. The subtitle then states the
        // blind spot at the point of reading, because no per-corner number can express it.
        //
        // Both flip to absolute language the moment any corner carries absolutePsi.
        PaneHeader(
            title = if (absolute) "ESTIMATED PRESSURE" else "PRESSURE IMBALANCE",
            subtitle = if (absolute) "Absolute pressure, psi"
            else "Between corners - a uniform loss on all four reads zero",
        )

        // Three rows, not two, even though only two carry wheels: the third holds the state chip
        // and exists so this grid's row heights match the calibration grid's. Without it the two
        // halves each divide the same height differently and a corner no longer sits opposite its
        // own corner across the divider, which is the whole point of the car-shaped layout.
        Column(Modifier.weight(1f)) {
            GridRow {
                EstimateCell(Corner.LF, estimate, Modifier.weight(1f))
                EstimateCell(Corner.RF, estimate, Modifier.weight(1f))
            }
            GridRow {
                EstimateCell(Corner.LR, estimate, Modifier.weight(1f))
                EstimateCell(Corner.RR, estimate, Modifier.weight(1f))
            }
            GridRow {
                Box(
                    modifier = Modifier.weight(1f).fillMaxHeight(),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        StateBlock(estimate)
                        Spacer(Modifier.height(k.dp(10)))
                        GpsLine(gpsStatus, onRequestGps)
                    }
                }
            }
        }
    }
}

/**
 * One line of GPS status, for bringup: whether the head unit has a receiver at all, whether it has
 * a fix, how good the speed is, and the GPS/wheel ratio in the reference band. Speed-derived only
 * -- nothing positional exists to show.
 *
 * The ratio is GPS speed over wheel speed with wheel counts converted at the assumed 17.61
 * counts per km/h, so it reads about 1 when that scale is right. It is a live, whole-session
 * figure for eyeballing the channel, not a pressure; the stored per-band sums are the data.
 */
@Composable
private fun GpsLine(s: GpsRateAccumulator.Status, onRequestGps: () -> Unit) {
    val k = LocalPageScale.current
    val band = GpsRateAccumulator.REF_BAND_KMH
    val text = when (s.state) {
        GpsRateAccumulator.State.NO_PERMISSION -> "GPS: location not allowed"
        GpsRateAccumulator.State.NO_RECEIVER -> "GPS: no receiver on this unit"
        GpsRateAccumulator.State.PROVIDER_OFF -> "GPS: location is off in system settings"
        GpsRateAccumulator.State.OFF -> "GPS: not running"
        GpsRateAccumulator.State.SEARCHING ->
            "GPS: searching" + (s.satellitesUsed?.let { ", $it satellites in fix" } ?: "")
        GpsRateAccumulator.State.FIXING -> buildString {
            append("GPS: ${s.fixesLastMinute}/min")
            s.speedAccMps?.let { append("  +/-%.2f m/s".format(it)) }
            s.satellitesUsed?.let { append("  $it sats") }
            append("  |  GPS/wheel ${band.first}-${band.last}: ")
            append(s.refBandRho?.let { "%.4f (n %d)".format(it, s.refBandN) } ?: "-")
        }
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(text, color = MUTED, fontSize = k.sp(11), textAlign = TextAlign.Center)
        if (s.state == GpsRateAccumulator.State.NO_PERMISSION) {
            Spacer(Modifier.width(k.dp(8)))
            Button(
                onClick = onRequestGps,
                shape = RoundedCornerShape(5.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = Color(0xFF2E2E2E), contentColor = Color(0xFFDDDDDD)),
                contentPadding = PaddingValues(horizontal = k.dp(10), vertical = k.dp(0)),
                modifier = Modifier.height(k.dp(30)),
            ) { Text("ALLOW", fontSize = k.sp(11), fontWeight = FontWeight.Bold) }
        }
    }
}

/** The state chip plus its explanatory line. */
@Composable
private fun StateBlock(estimate: TpmsEstimate) {
    val k = LocalPageScale.current
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            text = estimate.state.chipText(),
            color = estimate.state.chipFg(),
            fontSize = k.sp(18),
            fontWeight = FontWeight.Bold,
            modifier = Modifier
                .background(estimate.state.chipBg(), RoundedCornerShape(5.dp))
                .padding(horizontal = k.dp(14), vertical = k.dp(6)),
        )
        val line = estimate.explain()
        if (line != null) {
            Spacer(Modifier.height(k.dp(8)))
            Text(line, color = MUTED, fontSize = k.sp(13), textAlign = TextAlign.Center)
        }
    }
}

/**
 * STALE deliberately sits off the OK/ADVISE/WARN severity ladder and takes a colour from outside
 * it. It is not a worse pressure reading -- it is a statement that the readings are invalid and the
 * user must recalibrate. Colouring it as a hotter red would file it under "tyre problem", which is
 * the wrong action.
 */
private fun TpmsState.chipBg(): Color = when (this) {
    TpmsState.LEARNING -> Color(0xFF2E2E2E)
    TpmsState.OK -> Color(0xFF1B5E20)
    TpmsState.ADVISE -> Color(0xFF8C5000)
    TpmsState.WARN -> Color(0xFFB00020)
    TpmsState.STALE -> Color(0xFF01579B)
}

private fun TpmsState.chipFg(): Color =
    if (this == TpmsState.LEARNING) Color(0xFFBBBBBB) else Color.White

private fun TpmsState.chipText(): String = when (this) {
    TpmsState.LEARNING -> "LEARNING"
    TpmsState.OK -> "OK"
    TpmsState.ADVISE -> "ADVISE"
    TpmsState.WARN -> "WARN"
    TpmsState.STALE -> "RECALIBRATE"
}

private fun TpmsEstimate.explain(): String? {
    val fixed = when (state) {
        TpmsState.STALE ->
            "A fill was detected that was not entered here, so the baseline no longer applies. " +
                "Gauge all four tyres and press SET."
        // Say plainly that nothing is being watched yet: until the baseline freezes neither path
        // can see a puncture, and this must not read like a clean bill of health.
        TpmsState.LEARNING -> "Learning - not yet monitoring"
        else -> null
    }
    return when {
        fixed != null && detail != null -> "%s (%s)".format(fixed, detail)
        fixed != null -> fixed
        else -> detail
    }
}

private fun TpmsEstimate.anyAbsolute(): Boolean =
    Corner.entries.any { this[it].absolutePsi != null }

/**
 * One corner. Renders a dash when there is no value, never `0.0`: a missing reading that looked
 * like zero would read as "this tyre is exactly on target", the opposite of the truth. Same rule
 * the specs page follows for absent signals.
 *
 * Under [TpmsState.STALE] the numbers are suppressed entirely. The baseline they were computed
 * against is dead, so they are not merely uncertain -- they are meaningless, and showing a precise
 * meaningless number is worse than showing none.
 */
@Composable
private fun EstimateCell(
    corner: Corner,
    estimate: TpmsEstimate,
    modifier: Modifier = Modifier,
) {
    val k = LocalPageScale.current
    // The corner is named once and both the label and the value derive from it, so the heading and
    // the number under it cannot disagree.
    val label = corner.label
    val reading = estimate[corner]
    // Absolute wins when present: it is the same four cells either way, which is what lets the
    // common-mode channel land without a UI change.
    val absolute = reading.absolutePsi
    val shown: String? = when {
        estimate.state == TpmsState.STALE -> null
        absolute != null -> "%.1f".format(absolute)
        reading.deltaPsi != null -> "%+.1f".format(reading.deltaPsi)
        else -> null
    }

    Column(
        modifier = modifier.fillMaxHeight(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(label, color = LABEL, fontSize = k.sp(13), fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(k.dp(5)))
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(k.dp(88))
                .background(BOX_BG, RoundedCornerShape(6.dp))
                .border(1.dp, BOX_BORDER, RoundedCornerShape(6.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = shown ?: "--",
                    color = if (shown == null) ABSENT else Color.White,
                    fontSize = k.sp(40),
                    fontWeight = FontWeight.Bold,
                )
                Text("psi", color = MUTED, fontSize = k.sp(12))
            }
        }
    }
}

// --- entry cell --------------------------------------------------------------

/**
 * A tyre pressure cell. The corner is named once and the label, the current value and the
 * write-back all derive from it, so a cell cannot display one wheel while editing another.
 */
@Composable
private fun CornerEntryCell(
    corner: Corner,
    psi: Map<Corner, Float?>,
    modifier: Modifier = Modifier,
    onChange: (Corner, Float?) -> Unit,
) {
    EntryCell(
        label = corner.label,
        unit = "psi",
        value = psi[corner],
        step = PSI_STEP,
        min = PSI_MIN,
        max = PSI_MAX,
        seed = CodaConstants.DEFAULT_TIRE_PSI,
        modifier = modifier,
    ) { onChange(corner, it) }
}

/**
 * One labelled value box with a minus/plus pair under it.
 *
 * `value == null` renders blank, and the first press of either button seeds [seed] rather than
 * stepping from an implied zero. Tapping the number turns the box into a keyboard entry.
 */
@Composable
private fun EntryCell(
    label: String,
    unit: String,
    value: Float?,
    step: Float,
    min: Float,
    max: Float,
    seed: Float,
    modifier: Modifier = Modifier,
    onValueChange: (Float?) -> Unit,
) {
    val k = LocalPageScale.current
    var editing by remember { mutableStateOf(false) }
    var draft by remember { mutableStateOf("") }
    // onFocusChanged fires once on attach with isFocused = false, before requestFocus has run.
    // Committing on that first callback closes the editor in the same frame it opened, so tapping
    // the number appeared to do nothing at all. Only a loss of focus that follows an actual gain
    // counts as the user leaving the field.
    var hadFocus by remember { mutableStateOf(false) }
    val focusRequester = remember { FocusRequester() }

    fun stepBy(delta: Float) {
        val base = value ?: seed
        val next = if (value == null) base else (base + delta)
        onValueChange(next.coerceIn(min, max).roundToStep(step))
    }

    fun commitDraft() {
        editing = false
        hadFocus = false
        val parsed = draft.trim().toFloatOrNull()
        // An unparseable or empty entry clears the box rather than keeping the old value. Leaving a
        // stale number behind after the user deliberately retyped it is the failure mode that would
        // silently submit the wrong pressure.
        onValueChange(parsed?.coerceIn(min, max)?.roundToStep(step))
    }

    Column(
        modifier = modifier.fillMaxHeight(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(label, color = LABEL, fontSize = k.sp(13), fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(k.dp(5)))

        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(k.dp(72))
                .background(BOX_BG, RoundedCornerShape(6.dp))
                .border(1.dp, if (editing) ACCENT else BOX_BORDER, RoundedCornerShape(6.dp)),
            contentAlignment = Alignment.Center,
        ) {
            if (editing) {
                BasicTextField(
                    value = draft,
                    onValueChange = { draft = it },
                    singleLine = true,
                    textStyle = TextStyle(
                        color = Color.White,
                        fontSize = k.sp(34),
                        fontWeight = FontWeight.Bold,
                        textAlign = TextAlign.Center,
                    ),
                    cursorBrush = SolidColor(ACCENT),
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Number,
                        imeAction = ImeAction.Done,
                    ),
                    keyboardActions = KeyboardActions(onDone = { commitDraft() }),
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = k.dp(6))
                        .focusRequester(focusRequester)
                        .onFocusChanged { st ->
                            if (st.isFocused) hadFocus = true
                            else if (hadFocus && editing) commitDraft()
                        },
                )
                LaunchedEffect(Unit) { focusRequester.requestFocus() }
            } else {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        text = value?.let { "%.1f".format(it) } ?: "--",
                        color = if (value == null) ABSENT else Color.White,
                        fontSize = k.sp(34),
                        fontWeight = FontWeight.Bold,
                    )
                    Text(text = unit, color = MUTED, fontSize = k.sp(12))
                }
                // A transparent tap target over the whole box, so tapping the number opens the
                // keyboard. Kept separate from the +/- buttons below so a mis-tap on the box never
                // changes the value. No indication: this is a hit region, not a button, and a ripple
                // over the value text reads as a glitch.
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .clickable(
                            interactionSource = remember { MutableInteractionSource() },
                            indication = null,
                        ) {
                            draft = value?.let { "%.1f".format(it) } ?: ""
                            editing = true
                        }
                )
            }
        }

        Spacer(Modifier.height(k.dp(8)))

        Row(horizontalArrangement = Arrangement.spacedBy(k.dp(10))) {
            RepeatButton(label = "−") { stepBy(-step) }
            RepeatButton(label = "+") { stepBy(+step) }
        }
    }
}

/**
 * A button that fires once on press and then repeats while held, accelerating after
 * [ACCEL_AFTER_REPS] repeats.
 *
 * Repeat matters here: 0.1 psi per press means correcting to a real gauge reading is tens of
 * presses, and it is done four times in a row.
 */
@Composable
private fun RepeatButton(label: String, onStep: () -> Unit) {
    val k = LocalPageScale.current
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    // The lambda is captured by a long-lived effect; without this the effect would keep calling the
    // version of onStep from the composition that started the press, which closes over a stale value.
    val step by rememberUpdatedState(onStep)

    // True once a hold has started repeating, so the click that arrives on release is swallowed
    // rather than adding an extra step on top of the repeats.
    var repeated by remember { mutableStateOf(false) }

    // The single step is driven by onClick, NOT by this effect.
    //
    // A quick tap emits Press and Release within one frame, so `pressed` goes false -> true ->
    // false without any composition ever observing true, and a LaunchedEffect keyed on it never
    // re-keys. Stepping from here alone means fast taps silently do nothing -- verified on the
    // head-unit AVD, where `input tap` produced no change at all while a 2 s hold worked.
    // onClick comes from the tap detector rather than from interaction state and is not subject to
    // that coalescing, so it is the reliable half. This effect owns only the repeat.
    LaunchedEffect(pressed) {
        if (!pressed) return@LaunchedEffect
        repeated = false
        delay(HOLD_DELAY_MS)
        var reps = 0
        while (true) {
            repeated = true
            step()
            reps++
            delay(if (reps < ACCEL_AFTER_REPS) SLOW_REPEAT_MS else FAST_REPEAT_MS)
        }
    }

    Button(
        onClick = { if (repeated) repeated = false else step() },
        interactionSource = interaction,
        shape = RoundedCornerShape(5.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = Color(0xFF2E2E2E),
            contentColor = Color.White,
        ),
        contentPadding = PaddingValues(0.dp),
        modifier = Modifier.size(width = k.dp(76), height = k.dp(52)),
    ) {
        Text(label, fontSize = k.sp(26), fontWeight = FontWeight.Bold)
    }
}

/** Snap to the step grid so repeated float addition cannot drift to 32.099998. */
private fun Float.roundToStep(step: Float): Float = Math.round(this / step) * step
