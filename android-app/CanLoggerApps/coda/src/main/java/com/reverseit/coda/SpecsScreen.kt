package com.reverseit.coda

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
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
import com.reverseit.display.widgets.ReferenceLine
import com.reverseit.display.widgets.SliderMarker
import com.reverseit.display.widgets.StatusWord

/**
 * Page 2 -- detailed vehicle specs, reached by swiping right from the green screen.
 *
 * Design rules, matching the Vtrux live display:
 *  - Sliders and status words, not numeric readouts. Scales carry axis labels so a
 *    marker position is readable, but live values are never printed as numbers.
 *  - Nothing here duplicates the instrument cluster (SoC and speedometer).
 *  - A signal that is not on the bus renders as an absent marker, never as zero.
 *
 * Layout is three columns, sized for the head unit's 1024x600 landscape panel:
 *
 *  +----------------+----------------+---------------------------+
 *  | BATTERY        | LOADS          | DRIVE  or  CHARGE         |
 *  | always visible | always visible | swaps on HVPowermode       |
 *  +----------------+----------------+---------------------------+
 */
@Composable
fun SpecsScreen(state: SpecsState, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .fillMaxSize()
            .background(Color.Black)
            .padding(horizontal = 8.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        SpecsColumn("Battery") { BatteryColumn(state) }
        SpecsColumn("Loads") { LoadsColumn(state) }
        SpecsColumn(if (state.isCharging) "Charge" else "Drive") {
            if (state.isCharging) ChargeColumn(state) else DriveColumn(state)
        }
    }
}

/**
 * One of the three columns: a pinned header with the content spread down the
 * remaining panel height. At 7 inches in a car the sliders need the vertical
 * room, but the headers must stay aligned across all three columns, so only the
 * content participates in the even distribution.
 */
@Composable
private fun RowScope.SpecsColumn(
    title: String,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(modifier = Modifier.weight(1f).fillMaxHeight()) {
        SectionTitle(title)
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.SpaceEvenly,
            content = content,
        )
    }
}

/** Bars are taller than the Vtrux phone default; this is a 7-inch panel at arm's length. */
private const val BAR_HEIGHT = 24
private val SLIDER_GAP = 14.dp

// --- battery ---------------------------------------------------------------

@Composable
private fun BatteryColumn(state: SpecsState) {
    ColorBandSlider(
        label = "Cell voltage",
        markers = listOf(
            SliderMarker(value = state.cellVMinV),
            SliderMarker(value = state.cellVMaxV),
        ),
        min = 2.5,
        max = 3.8,
        bands = cellVoltageBands,
        boundarySuffix = " V",
        barHeight = BAR_HEIGHT,
    )

    ColorBandSlider(
        label = "Cell temperature",
        markers = listOf(
            SliderMarker(value = state.cellTMinC),
            SliderMarker(value = state.cellTMaxC),
        ),
        min = -20.0,
        max = 60.0,
        bands = cellTempBands,
        boundarySuffix = " C",
        barHeight = BAR_HEIGHT,
    )

    // Pack current: discharge reads NEGATIVE and charge/regen POSITIVE -- verified
    // against a charge log (100% positive) and a drive log (0% positive under
    // motoring, 86% positive under regen). See notes/artifacts/packcurrent_sign_check.py.
    // The green band is bounded by the BMS's own limits, so the marker shows draw
    // and the band shows how much headroom the BMS is currently allowing.
    //
    // Both limits must be present before any red is drawn. Defaulting a missing
    // limit to 0 would paint the whole bar red and read as "way out of limits"
    // when the truth is simply that 0x275 has not arrived yet.
    val packMin = -400.0
    val packMax = 150.0
    val disLimit = state.dischargeLimitA
    val chgLimit = state.chargeLimitA
    val packBands = if (disLimit != null && chgLimit != null) {
        val dis = disLimit.coerceIn(0.0, -packMin)
        val chg = chgLimit.coerceIn(0.0, packMax)
        listOf(
            ColorBand(packMin, -dis, red),
            ColorBand(-dis, chg, green),
            ColorBand(chg, packMax, red),
        )
    } else {
        listOf(ColorBand(packMin, packMax, neutral))
    }
    ColorBandSlider(
        label = "Pack current",
        markers = listOf(SliderMarker(value = state.packCurrentA)),
        min = packMin,
        max = packMax,
        bands = packBands,
        referenceLines = listOf(ReferenceLine(0.0, "0")),
        boundarySuffix = " A",
        barHeight = BAR_HEIGHT,
    )

    // Fault state is absent unless the known RED-lamp byte is on the bus. There is
    // no defined enum for any other 0x270 value, so nothing else is claimed here.
    if (state.coldFault) {
        StatusWord(label = "", text = "BATT COLD FAULT", bgColor = amber)
    }

    val hi = state.cellVMaxId
    val lo = state.cellVMinId
    if (hi != null && lo != null) {
        Text(
            text = "Outlier cells   high $hi   low $lo",
            fontSize = 10.sp,
            color = Color(0xFF999999),
        )
    }
}

// --- accessory loads -------------------------------------------------------

@Composable
private fun LoadsColumn(state: SpecsState) {
    // The commanded ceiling from 0x410 is drawn as a live reference line, so the
    // slider reads as actual-against-allowed rather than just a bare level.
    val maxKw = state.acCompressorMaxKw
    ColorBandSlider(
        label = "A/C compressor",
        markers = listOf(SliderMarker(value = state.acCompressorKw)),
        min = 0.0,
        max = 6.0,
        bands = listOf(ColorBand(0.0, 6.0, blue)),
        referenceLines = buildList {
            add(ReferenceLine(2.0, "2"))
            add(ReferenceLine(4.0, "4"))
            if (maxKw != null && maxKw > 0.0 && maxKw < 6.0) add(ReferenceLine(maxKw, "max"))
        },
        boundarySuffix = " kW",
        barHeight = BAR_HEIGHT,
    )

    ColorBandSlider(
        label = "PTC heater",
        markers = listOf(SliderMarker(value = state.ptcHeaterKw)),
        min = 0.0,
        max = 6.0,
        bands = listOf(ColorBand(0.0, 6.0, orange)),
        referenceLines = listOf(ReferenceLine(2.0, "2"), ReferenceLine(4.0, "4")),
        boundarySuffix = " kW",
        barHeight = BAR_HEIGHT,
    )

    // 0x1D5 current is 2 A/count, so this steps in ~28 W increments at 14 V. That
    // coarseness is a further reason not to print it as a number.
    ColorBandSlider(
        label = "DC-DC (12V)",
        markers = listOf(SliderMarker(value = state.dcdcW)),
        min = 0.0,
        max = 2000.0,
        bands = listOf(ColorBand(0.0, 2000.0, teal)),
        referenceLines = listOf(
            ReferenceLine(500.0, "500"),
            ReferenceLine(1000.0, "1k"),
            ReferenceLine(1500.0, "1.5k"),
        ),
        boundarySuffix = " W",
        barHeight = BAR_HEIGHT,
    )
}

// --- drive mode ------------------------------------------------------------

@Composable
private fun DriveColumn(state: SpecsState) {
    // Green for negative (regen), blue for positive (motoring) -- the same
    // convention as the Vtrux drivetrain slider.
    ColorBandSlider(
        label = "Drivetrain torque",
        markers = listOf(SliderMarker(value = state.motorTorqueNm)),
        min = -310.0,
        max = 310.0,
        bands = listOf(
            ColorBand(-310.0, 0.0, green),
            ColorBand(0.0, 310.0, blue),
        ),
        referenceLines = listOf(ReferenceLine(0.0, "0")),
        boundarySuffix = " Nm",
        barHeight = BAR_HEIGHT,
    )

    // Unitless and unlabeled by design: 0x241's role is confirmed but its per-byte
    // assignment is not, so no marker claims to be rotor, stator or inverter.
    // See CodaConstants.MCM_THERMAL_BYTES.
    ColorBandSlider(
        label = "Drivetrain thermal",
        markers = state.drivetrainTempsC.map { SliderMarker(value = it) },
        min = 0.0,
        max = 120.0,
        bands = drivetrainThermalBands,
        barHeight = BAR_HEIGHT,
    )
}

// --- charge mode -----------------------------------------------------------

@Composable
private fun ChargeColumn(state: SpecsState) {
    // Two limits matter and either can bind: the station's J1772 offer and the
    // car's own ~6.7 kW onboard-charger ceiling. Green runs to whichever is lower,
    // so the display answers "what is limiting me" rather than showing a permanent
    // phantom gap on a station bigger than the car can use.
    val evse = state.evseMaxCurrentA
    val car = state.carLimitA
    val binding = listOfNotNull(evse, car).minOrNull()
    val scaleMax = maxOf(evse ?: 0.0, car ?: 0.0, state.acInputCurrentA ?: 0.0, 1.0) * 1.2

    ColorBandSlider(
        label = "AC input current",
        markers = listOf(SliderMarker(value = state.acInputCurrentA)),
        min = 0.0,
        max = scaleMax,
        bands = if (binding != null) listOf(
            ColorBand(0.0, binding, green),
            ColorBand(binding, scaleMax, Color(0xFF424242)),
        ) else listOf(ColorBand(0.0, scaleMax, Color(0xFF424242))),
        referenceLines = buildList {
            if (evse != null) add(ReferenceLine(evse, "EVSE"))
            if (car != null) add(ReferenceLine(car, "CAR"))
        },
        boundarySuffix = " A",
        barHeight = BAR_HEIGHT,
    )

    // AC in and DC out on one scale: the gap between the markers is the conversion
    // loss, shown as a distance rather than a computed efficiency figure.
    val acKw = state.acInputW?.div(1000.0)
    val dcKw = run {
        val v = state.hvOutputVoltage
        val i = state.hvOutputCurrentA
        if (v == null || i == null) null else v * i / 1000.0
    }
    ColorBandSlider(
        label = "Charge power   (AC in / DC out)",
        markers = listOf(
            SliderMarker(value = acKw, color = Color.White, below = false),
            SliderMarker(value = dcKw, color = teal, below = true),
        ),
        min = 0.0,
        max = 8.0,
        bands = listOf(ColorBand(0.0, 8.0, blue)),
        referenceLines = listOf(ReferenceLine(2.0, "2"), ReferenceLine(4.0, "4"),
            ReferenceLine(6.0, "6")),
        boundarySuffix = " kW",
        barHeight = BAR_HEIGHT,
    )

    ColorBandSlider(
        label = "Charger thermal",
        markers = state.chargerTempsC.map { SliderMarker(value = it) },
        min = 0.0,
        max = 100.0,
        bands = drivetrainThermalBands,
        boundarySuffix = " C",
        barHeight = BAR_HEIGHT,
    )

    val mode = chargeModeLabel(state.chargeMode)
    if (mode != null) {
        StatusWord(label = "", text = mode, bgColor = chargeModeColor(state.chargeMode))
    }
}

/** Per VAL_ 888 Chargemode in CODA-B-CAN.dbc. */
private fun chargeModeColor(mode: Int?): Color = when (mode) {
    3 -> green
    4 -> Color(0xFF1565C0)
    5 -> teal
    2 -> Color(0xFF00ACC1)
    else -> Color(0xFF424242)
}

// --- shared ----------------------------------------------------------------

@Composable
private fun SectionTitle(text: String) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFF1A1A1A))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    ) {
        Text(
            text = text,
            fontWeight = FontWeight.SemiBold,
            color = Color.White,
            fontSize = 12.sp,
            modifier = Modifier.align(Alignment.CenterStart),
        )
    }
    Spacer(Modifier.height(6.dp))
}

private val green = Color(0xFF2E7D32)
private val red = Color(0xFFC62828)
private val amber = Color(0xFFF9A825)
private val blue = Color(0xFF2196F3)
private val teal = Color(0xFF26C6DA)
private val orange = Color(0xFFFF9800)

/** Used when a band's bounds are unknown -- "no data", never "out of range". */
private val neutral = Color(0xFF424242)

// LFP: 2.5-3.65 V usable, with the practical operating band well inside that.
private val cellVoltageBands = listOf(
    ColorBand(2.5, 2.6, red),
    ColorBand(2.6, 3.0, amber),
    ColorBand(3.0, 3.6, green),
    ColorBand(3.6, 3.8, red),
)

private val cellTempBands = listOf(
    ColorBand(-20.0, 0.0, Color(0xFF1565C0)),
    ColorBand(0.0, 15.0, teal),
    ColorBand(15.0, 45.0, green),
    ColorBand(45.0, 55.0, amber),
    ColorBand(55.0, 60.0, red),
)

private val drivetrainThermalBands = listOf(
    ColorBand(0.0, 70.0, green),
    ColorBand(70.0, 85.0, amber),
    ColorBand(85.0, 120.0, red),
)
