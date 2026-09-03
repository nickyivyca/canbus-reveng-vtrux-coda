package com.reverseit.p914

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.reverseit.display.widgets.ColorBand
import com.reverseit.display.widgets.ColorBandSlider
import com.reverseit.display.widgets.FaultChip
import com.reverseit.display.widgets.ReferenceLine
import com.reverseit.display.widgets.SliderMarker
import com.reverseit.display.widgets.StatusWord
import com.reverseit.display.widgets.faultStateOf

/**
 * The 914's in-car display. Portrait, black, single column.
 *
 * ```
 *  +-----------------------------------------+
 *  | 914          SCHEMA 3.0 ok      * LIVE  |   integrity band
 *  +-----------------------------------------+
 *  |  BMS LATCHED                            |
 *  |   [ OV ] [ UV ] [ OT ] [ IMB ] [ PEC ]  |   fault chips
 *  +-----------------------------------------+
 *  |  MOTOR CURRENT                          |
 *  |   |------|---------|---------|-------|  |   one signed A scale
 *  +-----------------------------------------+
 *  |  OPMODE   [ RUN ]                       |
 *  |   * UDC<SW     * EMCY      * WAITSTART  |   three status lights
 *  +-----------------------------------------+
 * ```
 *
 * Deliberately sparse. The car already has a 20x4 UART LCD and a standard 914 dash, and this
 * screen carries only what those cannot show -- so a short list is the intended outcome, not an
 * unfinished one. See `notes/plans/914-app-ui-spec.md` for the full derivation of every number
 * and colour on this screen.
 */
@Composable
fun P914Screen(
    signals: Map<String, Double>,
    schema: SchemaCheck.Verdict,
    live: Boolean,
    opmodeNames: Map<Int, String>,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .background(Color.Black),
    ) {
        IntegrityBand(schema, live)

        // if/else, NOT an early `return@Column`. Returning out of a composable content lambda
        // leaves the composer's group stack unbalanced, and the crash surfaces later and
        // elsewhere -- `IndexOutOfBoundsException` inside `ComposerImpl.exitGroup` on a
        // subsequent recomposition, with nothing in the trace pointing back here. Written the
        // first way, and it took down the whole app the moment a quarantine actually happened.
        if (schema is SchemaCheck.Verdict.Quarantine) {
            // Blanked, not greyed. A greyed-out gauge still invites reading; a blank region
            // cannot be misread. This is the entire reason the schema hash exists -- a stale DBC
            // has to report a mismatch instead of quietly rendering plausible wrong numbers.
            QuarantineNotice(schema)
        } else {
            Spacer(Modifier.height(10.dp))
            FaultBlock(signals)
            Spacer(Modifier.height(14.dp))
            MotorCurrentBlock(signals)
            Spacer(Modifier.height(14.dp))
            InverterBlock(signals, opmodeNames)

            // Room for the floating cog and the status banner the host draws over the bottom.
            Spacer(Modifier.height(110.dp))
        }
    }
}

// --- integrity band -------------------------------------------------------

private val BAND_NEUTRAL = Color(0xFF888888)
private val BAND_WARN = Color(0xFFFFB300)
private val BAND_BAD = Color(0xFFFF1744)

private fun bandColor(v: SchemaCheck.Verdict): Color = when (v) {
    is SchemaCheck.Verdict.Match -> BAND_NEUTRAL
    is SchemaCheck.Verdict.NotYetSeen -> BAND_NEUTRAL
    is SchemaCheck.Verdict.NeverSeen -> BAND_WARN
    is SchemaCheck.Verdict.MinorDiffers -> BAND_WARN
    is SchemaCheck.Verdict.DbcUnstamped -> BAND_WARN
    is SchemaCheck.Verdict.Quarantine -> BAND_BAD
}

@Composable
private fun IntegrityBand(schema: SchemaCheck.Verdict, live: Boolean) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFF141414))
            .padding(horizontal = 10.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("914", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 14.sp)
        Spacer(Modifier.weight(1f))
        Text(
            text = SchemaCheck.bandText(schema),
            color = bandColor(schema),
            fontWeight = FontWeight.SemiBold,
            fontSize = 12.sp,
        )
        Spacer(Modifier.weight(1f))
        // Connection state, not per-signal freshness. Nothing in the stack expires a signal and
        // per-element staleness is a deferred decision (see the UI spec) -- so this dot says the
        // stream is up, and claims nothing about any individual value's age.
        Box(
            modifier = Modifier
                .size(8.dp)
                .background(
                    if (live) Color(0xFF00E676) else Color(0xFF555555),
                    shape = CircleShape,
                ),
        )
        Spacer(Modifier.width(6.dp))
        Text(
            text = if (live) "LIVE" else "--",
            color = if (live) Color.White else BAND_NEUTRAL,
            fontWeight = FontWeight.SemiBold,
            fontSize = 12.sp,
        )
    }
}

@Composable
private fun QuarantineNotice(v: SchemaCheck.Verdict.Quarantine) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(20.dp),
    ) {
        Text(
            "SCHEMA MISMATCH",
            color = BAND_BAD,
            fontWeight = FontWeight.Bold,
            fontSize = 20.sp,
        )
        Spacer(Modifier.height(10.dp))
        Text(
            SchemaCheck.detail(v),
            color = Color(0xFFCCCCCC),
            fontSize = 13.sp,
        )
        Spacer(Modifier.height(14.dp))
        Text(
            "Readings are hidden on purpose.",
            color = Color(0xFF888888),
            fontSize = 12.sp,
        )
    }
}

// --- element 1: BMS fault chips -------------------------------------------

/** label -> the signal stem both bits share. */
private val FAULT_CHIPS = listOf(
    "OV" to "Flt_CellOverVoltage",
    "UV" to "Flt_CellUnderVoltage",
    "OT" to "Flt_OverTemp",
    "IMB" to "Flt_StringImbalance",
    "PEC" to "Flt_Pec",
)

@Composable
private fun FaultBlock(signals: Map<String, Double>) {
    SectionTitle("BMS latched")
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        for ((label, stem) in FAULT_CHIPS) {
            FaultChip(
                label = label,
                state = faultStateOf(
                    latched = signals.isSet("${stem}_Latched"),
                    present = signals.isSet("${stem}_Now"),
                ),
            )
        }
    }
}

/**
 * A one-bit signal decodes to 0.0 or 1.0, so the midpoint is a safe threshold.
 *
 * Absent reads as clear. Before the first BmsStatus frame every chip is grey, which is correct:
 * "no fault reported" and "nothing heard yet" are both states in which there is no fault to show,
 * and the integrity band above already carries whether the stream is up.
 */
private fun Map<String, Double>.isSet(name: String): Boolean = (this[name] ?: 0.0) > 0.5

// --- element 2: motor current ---------------------------------------------

private const val CURRENT_MIN = -150.0
private const val CURRENT_MAX = 700.0

private val IQ_COLOR = Color(0xFF00E676)
private val ID_COLOR = Color(0xFF2196F3)
private val IFW_COLOR = Color(0xFFFF9800)

/**
 * Asymmetric on purpose. The scale runs to `ocurlim` (+700 A, the inverter's hardware overcurrent
 * comparator) at the top, but stops at -150 A rather than mirroring, because the configuration
 * cannot command regen past -110 A. A symmetric scale would leave braking barely moving the
 * needle -- reproducing, in the display built to improve visibility, the exact defect already
 * recorded against the LCD power bar.
 */
private val currentBands = listOf(
    ColorBand(CURRENT_MIN, 0.0, Color(0xFF00838F)),
    ColorBand(0.0, 550.0, Color(0xFF1B5E20)),
    ColorBand(550.0, 650.0, Color(0xFFF9A825)),
    ColorBand(650.0, CURRENT_MAX, Color(0xFFC62828)),
)

private val currentRefs = listOf(
    ReferenceLine(550.0, "full"),
    ReferenceLine(275.0, "bms"),
    ReferenceLine(-110.0, "regen"),
)

@Composable
private fun MotorCurrentBlock(signals: Map<String, Double>) {
    val iq = signals["InvIq"]
    val id = signals["InvId"]
    // Plotted negated, and labelled "-ifw" so the screen says what it is doing.
    //
    // Field weakening is negative d-axis current by convention, not because of anything about
    // this car: stm32-sine's `fwcurmax` is defined with the range [-1000, 0] and a default of
    // -100, so `ifw` can only ever be <= 0. Plotted as-is it would run down the short end of an
    // asymmetric -150..+700 A scale and fall off it -- a configured -100 A sits 2/3 of the way
    // to the floor before any of the drive envelope is used. Negated it climbs into the +700 A
    // side, where there is room. It is NOT flipped in the DBC, because the sign there is correct.
    val ifw = signals["InvIfw"]?.let { -it }

    SectionTitle("Motor current")
    Column(modifier = Modifier.padding(horizontal = 10.dp)) {
        ColorBandSlider(
            label = "",
            markers = listOf(
                // iq above the bar, id and ifw below: three triangles on one edge would overlap
                // near zero, which is where all three sit whenever the car is stationary.
                SliderMarker(value = iq, color = IQ_COLOR, below = false),
                SliderMarker(value = id, color = ID_COLOR, below = true),
                SliderMarker(value = ifw, color = IFW_COLOR, below = true),
            ),
            min = CURRENT_MIN,
            max = CURRENT_MAX,
            bands = currentBands,
            referenceLines = currentRefs,
            boundarySuffix = " A",
        )
        Spacer(Modifier.height(6.dp))
        // ColorBandSlider draws markers as bare triangles and never renders SliderMarker.label,
        // so the colour key has to be spelled out here or the three markers are unidentifiable.
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            CurrentLegend("iq", iq, IQ_COLOR)
            CurrentLegend("id", id, ID_COLOR)
            CurrentLegend("-ifw", ifw, IFW_COLOR)
        }
    }
}

@Composable
private fun CurrentLegend(name: String, value: Double?, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .background(color, shape = RoundedCornerShape(2.dp)),
        )
        Spacer(Modifier.width(5.dp))
        Text(name, color = Color(0xFFAAAAAA), fontSize = 11.sp)
        Spacer(Modifier.width(4.dp))
        Text(
            // An em dash, not "0.0": the inverter is unpowered for most bench work and a real
            // zero amps must not look the same as no data.
            //
            // The `+ 0.0` is not redundant. ifw is plotted negated, and negating a zero gives
            // IEEE-754 negative zero, which "%.1f" faithfully renders as "-0.0 A" -- read on the
            // car as a real, if tiny, negative current. Adding positive zero collapses it.
            text = value?.let { "%.1f A".format(it + 0.0) } ?: "—",
            color = Color.White,
            fontSize = 11.sp,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

// --- elements 3 and 4: opmode and status lights ---------------------------

@Composable
private fun InverterBlock(signals: Map<String, Double>, opmodeNames: Map<Int, String>) {
    SectionTitle("Inverter")
    Column(modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)) {
        val opmode = signals["InvOpmode"]?.toInt()
        val (opText, opColor) = opmodeLabel(opmode, opmodeNames)
        StatusWord(label = "OPMODE", text = opText, bgColor = opColor)

        Spacer(Modifier.height(10.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            // Only EMCY is red. Colouring all three alike would train the driver to ignore a red
            // that means something -- UDC<SW in particular is set on every bench session, because
            // it simply says HV is down.
            StatusLight("UDC<SW", signals.isSet("InvSts_UdcBelowUdcSw"), AMBER)
            StatusLight("EMCY", signals.isSet("InvSts_EmcyStop"), Color(0xFFC62828))
            StatusLight("WAITSTART", signals.isSet("InvSts_WaitStart"), AMBER)
        }
    }
}

private val AMBER = Color(0xFFF9A825)
private val LIGHT_OFF = Color(0xFF2A2A2A)

@Composable
private fun StatusLight(name: String, set: Boolean, onColor: Color) {
    StatusWord(
        label = "",
        text = name,
        bgColor = if (set) onColor else LIGHT_OFF,
        fgColor = if (set) Color.White else Color(0xFF888888),
    )
}

/**
 * Opmode text comes from the DBC's own `VAL_` table, so the app cannot drift from the firmware's
 * vocabulary. An unmapped value renders as the raw number rather than as anything invented.
 */
private fun opmodeLabel(value: Int?, names: Map<Int, String>): Pair<String, Color> {
    if (value == null) return "—" to Color(0xFF424242)
    val name = names[value] ?: "MODE $value"
    val color = when {
        names[value] == null -> AMBER
        value == 0 -> Color(0xFF424242)
        value == 1 -> Color(0xFF2E7D32)
        // Boost, Buck, Sine, AcHeat and ManualRun are not normal for this car. Their appearing at
        // all is itself information, so they get a colour that says "look at this".
        else -> AMBER
    }
    return name.uppercase() to color
}

// --- helpers --------------------------------------------------------------

@Composable
private fun SectionTitle(text: String) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFF1A1A1A))
            .padding(horizontal = 10.dp, vertical = 3.dp),
    ) {
        Text(
            text = text.uppercase(),
            fontWeight = FontWeight.SemiBold,
            color = Color.White,
            fontSize = 12.sp,
        )
    }
}
