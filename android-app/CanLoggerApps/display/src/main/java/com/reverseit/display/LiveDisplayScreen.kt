package com.reverseit.display

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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.reverseit.cancore.DataSourceStatus
import com.reverseit.display.widgets.ColorBand
import com.reverseit.display.widgets.ColorBandSlider
import com.reverseit.display.widgets.ReferenceLine
import com.reverseit.display.widgets.SliderMarker
import com.reverseit.display.widgets.StatusWord
import com.reverseit.display.widgets.Tachometer

/**
 * Vtrux live-display screen. Phone-portrait layout, black background, white
 * accents.
 *
 *  +-----------------------------------+
 *  | status banner                     |
 *  +------------------+----------------+
 *  | BATTERY          | GENERATOR      |
 *  |  V slider (min,  |   tach + torq  |
 *  |             max) |   EVAP word    |
 *  |  T slider (min,  |   coolant      |
 *  |             max) |   motor temps  |
 *  |  pack I slider   |     (D,G)      |
 *  |  contactor word  |                |
 *  |  status word     |                |
 *  +------------------+----------------+
 *  | mode block (drive/charge/export)  |
 *  +-----------------------------------+
 */
@Composable
fun LiveDisplayScreen(
    viewModel: LiveDisplayViewModel,
    modifier: Modifier = Modifier,
) {
    val status by viewModel.status.collectAsState()
    val signals by viewModel.signalValues.collectAsState()

    Column(
        modifier = modifier
            .fillMaxSize()
            .background(Color.Black)
            .verticalScroll(rememberScrollState()),
    ) {
        Row(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.weight(1f).padding(start = 8.dp, end = 4.dp)) {
                BatteryPanel(signals)
            }
            Column(modifier = Modifier.weight(1f).padding(start = 4.dp, end = 8.dp)) {
                GeneratorPanel(signals)
            }
        }

        Spacer(Modifier.height(12.dp))
        ModePanel(signals)
        // Reserve room above the bottom status banner + floating cog.
        Spacer(Modifier.height(100.dp))
    }
    // The status param is intentionally unused here -- the banner is now
    // rendered by the host (LiveDisplayActivity) at the bottom of the screen.
    @Suppress("UNUSED_EXPRESSION")
    status
}

// --- panels ---------------------------------------------------------------

@Composable
private fun BatteryPanel(signals: Map<String, Double>) {
    SectionTitle("Battery")

    ColorBandSlider(
        label = "Cell voltage",
        markers = listOf(
            SliderMarker(value = signals["bcm_cell_vmin"]),
            SliderMarker(value = signals["bcm_cell_vmax"]),
        ),
        min = 2.5,
        max = 3.8,
        bands = cellVoltageBands,
    )
    ColorBandSlider(
        label = "Cell temperature",
        markers = listOf(
            SliderMarker(value = signals["bcm_cell_tmin"]),
            SliderMarker(value = signals["bcm_cell_tmax"]),
        ),
        min = -20.0,
        max = 60.0,
        bands = cellTempBands,
    )

    // Pack current: hardcoded ±limits at -600 A (discharge) and +300 A (charge),
    // the realistic extremes for the Vtrux pack. The BMS reports a ~1024 A
    // "sentinel" when no real limit is computed; that would dominate a
    // dynamic scale and squash the actual operating range. With hardcoded
    // endpoints we just shrink the green band when current limits come in
    // below the hardware extremes and let the red regions cover the rest.
    val packMin = -600.0
    val packMax = 300.0
    val curChg = (signals["bcm_chg_max"] ?: 0.0).coerceAtLeast(0.0).coerceAtMost(packMax)
    val curDis = (signals["bcm_dis_max"] ?: 0.0).coerceAtLeast(0.0).coerceAtMost(-packMin)
    val packBands = listOf(
        ColorBand(packMin, -curDis, Color(0xFFC62828)),
        ColorBand(-curDis, curChg, Color(0xFF2E7D32)),
        ColorBand(curChg, packMax, Color(0xFFC62828)),
    )
    ColorBandSlider(
        label = "Pack current",
        markers = listOf(SliderMarker(value = signals["bcm_ibat"])),
        min = packMin,
        max = packMax,
        bands = packBands,
        referenceLines = listOf(ReferenceLine(0.0, "0")),
    )

    val mainc = signals["bcm_mainc_stat"]?.toInt()
    val (cName, cColor) = contactorStateLabel(mainc)
    val (fName, fColor) = faultStateLabel(signals, mainc)
    val isCharging = mainc == 12
    val balancing = signals["bcm_balancing"]?.toInt() ?: 0
    val balCount = signals["bcm_balancing_cnt"]?.toInt() ?: 0

    Spacer(Modifier.height(4.dp))
    Text(
        text = "Contactor status",
        fontSize = 11.sp,
        color = Color(0xFFAAAAAA),
    )
    StatusWord(label = "", text = cName, bgColor = cColor)
    Spacer(Modifier.height(4.dp))
    Text(
        text = "Battery status",
        fontSize = 11.sp,
        color = Color(0xFFAAAAAA),
    )
    StatusWord(label = "", text = fName, bgColor = fColor)

    if (isCharging) {
        Spacer(Modifier.height(2.dp))
        Text(
            text = if (balancing == 1) "Balancing: $balCount cells" else "Balancing: idle",
            fontSize = 11.sp,
            color = Color(0xFFBBBBBB),
        )
    }

    Spacer(Modifier.height(6.dp))
    PowerElectronicsTempSlider(signals)
}

/**
 * Hybrid power-electronics temperature slider. Absolute °C markers for
 * components that report a real temperature (DCDC, BelInverter overall),
 * plus synthetic-°C markers derived from EPRI cooling-flow demand
 * percentages (TRAC, GENE inverters -- raw temp not exposed on bus).
 */
@Composable
private fun PowerElectronicsTempSlider(signals: Map<String, Double>) {
    val dcdc = signals["DCDC_Temperature"]
    val bel = signals["BELINV_overAllInverterTemperature"]
    val tracPct = signals["TRAC_DrvCoolFlowReq_pct"]
    val genePct = signals["GENE_DrvCoolFlowReq_pct"]

    // % cool-flow demand mapped 1:1 to °C on the same 0-100 scale. Hacky
    // but visually consistent: 100% demand sits in the red band alongside
    // a real component reading 100 °C.
    fun pctToSynthetic(pct: Double?): Double? = pct

    ColorBandSlider(
        label = "Power electronics",
        markers = listOf(
            SliderMarker(value = dcdc, label = "D", color = Color(0xFFFFFFFF), below = false),
            SliderMarker(value = bel, label = "B", color = Color(0xFFEC407A), below = false),
            SliderMarker(value = pctToSynthetic(tracPct), label = "T",
                color = Color(0xFF2196F3), below = true),
            SliderMarker(value = pctToSynthetic(genePct), label = "G",
                color = Color(0xFFFF9800), below = true),
        ),
        min = 0.0,
        max = 100.0,
        bands = motorTempBands,
    )
}

@Composable
private fun GeneratorPanel(signals: Map<String, Double>) {
    SectionTitle("Generator")

    val genRpm = signals["GENE_RotSpd"]
    Tachometer(
        rpm = genRpm,
        maxRpm = 4000.0,
        torque = signals["GENE_Mot_Trq"],
        torqueRange = 400.0,
        throttlePct = if (genRpm != null && genRpm < 400.0) 0.0 else signals["Throttle_Position"],
    )

    // EVAP: vcm_evap_active (0x649 B4 bit 7) means "cycle pending or purging";
    // vcm_evap_counter separates the two -- 0 while pending, non-zero once the
    // purge is actually running. Both live on 0x649 so they arrive together and
    // cannot be transiently inconsistent. A missing counter degrades to PENDING.
    val evapActive = signals["vcm_evap_active"]?.toInt()
    val evapCounter = signals["vcm_evap_counter"]?.toInt()
    val (evapText, evapBg) = when {
        evapActive == null -> "—" to Color(0xFF424242)
        evapActive == 0 -> "COMPLETE" to Color(0xFF2E7D32)
        (evapCounter ?: 0) > 0 -> "PURGE" to Color(0xFF00ACC1)
        else -> "PENDING" to Color(0xFF1565C0)
    }
    val ethanolPct = signals["Fuel_Alcohol_Composition"]
    val ethanolText = ethanolPct?.let { "%.0f".format(it) } ?: "—"
    // U+1F33D corn emoji, written as a UTF-16 surrogate pair so the source
    // file stays ASCII-only.
    val cornEmoji = "\uD83C\uDF3D"
    Row(
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth(),
    ) {
        StatusWord(label = "EVAP", text = evapText, bgColor = evapBg)
        Spacer(Modifier.weight(1f))
        Text(
            text = "$cornEmoji%: $ethanolText",
            color = Color.White,
            fontSize = 12.sp,
        )
    }
    Spacer(Modifier.height(4.dp))

    ColorBandSlider(
        label = "Engine coolant",
        markers = listOf(SliderMarker(value = signals["Engine_Coolant_Temperature"])),
        min = 0.0,
        max = 130.0,
        bands = engineCoolantBands,
    )

    // Two Remy motor temps share one slider. D marker below the bar (blue),
    // G marker above (orange). Letter labels are implicit in marker color.
    ColorBandSlider(
        label = "Motor temps",
        markers = listOf(
            SliderMarker(value = signals["TRAC_ThermInd_pct"], label = "D",
                color = Color(0xFF2196F3), below = true),
            SliderMarker(value = signals["GENE_ThermInd_pct"], label = "G",
                color = Color(0xFFFF9800), below = false),
        ),
        min = 0.0,
        max = 100.0,
        bands = motorTempBands,
        boundarySuffix = "%",
    )
}

@Composable
private fun ModePanel(signals: Map<String, Double>) {
    val mode = currentMode(signals)
    SectionTitle("Mode: ${mode.name}")
    Column(modifier = Modifier.padding(horizontal = 12.dp)) {
        when (mode) {
            DisplayMode.DRIVING -> {
                // Drivetrain torque slider -- blue for positive (motoring),
                // green for negative (regen). Matches the Vtrux power-indicator
                // dial in the cab.
                val tracTrq = signals["TRAC_TrqFbk"]
                ColorBandSlider(
                    label = "Drivetrain torque",
                    markers = listOf(SliderMarker(value = tracTrq)),
                    min = -400.0,
                    max = 400.0,
                    bands = listOf(
                        ColorBand(-400.0, 0.0, Color(0xFF2E7D32)),
                        ColorBand(0.0, 400.0, Color(0xFF2196F3)),
                    ),
                )
            }
            DisplayMode.CHARGING -> ChargePanel(signals)
            DisplayMode.EXPORT -> {
                Text(
                    "Export: AC output legs — (BelInverter DBC not yet bundled)",
                    color = Color(0xFF888888),
                )
            }
            DisplayMode.IDLE -> {
                Text("Idle.", color = Color(0xFF888888))
            }
        }
    }
}

/**
 * Charge-mode block, per spec: J1772 advertised current limit, AC input
 * voltage, present AC input current. HV-side V/I is shown alongside so the
 * two ends of the charger can be compared at a glance.
 *
 * All values come from the BelInverter combi-charger. They are only broadcast
 * while the charger is awake, so every field degrades to a dash rather than
 * a zero when the message is absent -- a real 0 A and "no data" must not look
 * the same on a charging screen.
 */
@Composable
private fun ChargePanel(signals: Map<String, Double>) {
    val acVolts = signals["BELINV_chargerInputVoltage"]
    val acAmps = signals["BELINV_chargerInputCurrent"]
    val pilotDuty = signals["BELINV_pilotDuty"]
    val dcLimitAmps = signals["BELINV_maxAvailableChargingCurrent"]
    val hvVolts = signals["BELINV_hvBatteryVoltage"]
    val hvAmps = signals["BELINV_hvBatteryCurrent"]

    // The EVSE's offer is the pilot duty cycle, not a CAN signal. The Bel's
    // maxAvailableChargingCurrent is the DC/pack-side limit (it tracks HV
    // current, not AC draw) and is shown against the HV row instead.
    val advertised = j1772AdvertisedAmps(pilotDuty)

    // Scale runs to the EVSE offer with headroom, so the bar is mostly green
    // during a normal charge and the marker only enters red if the charger
    // draws more than the EVSE advertised.
    val scaleMax = maxOf(advertised ?: 0.0, acAmps ?: 0.0, 1.0) * 1.25
    val bands = if (advertised != null) listOf(
        ColorBand(0.0, advertised, Color(0xFF2E7D32)),
        ColorBand(advertised, scaleMax, Color(0xFFC62828)),
    ) else listOf(ColorBand(0.0, scaleMax, Color(0xFF424242)))

    ColorBandSlider(
        label = "AC input current",
        markers = listOf(SliderMarker(value = acAmps)),
        min = 0.0,
        max = scaleMax,
        bands = bands,
        referenceLines = advertised?.let { listOf(ReferenceLine(it, "J1772")) } ?: emptyList(),
        boundarySuffix = "A",
    )

    Spacer(Modifier.height(6.dp))
    ReadoutRow("AC input", fmtPair(acVolts, "V", acAmps, "A"))
    ReadoutRow("AC power", fmtKw(acVolts, acAmps))
    ReadoutRow("HV battery", fmtPair(hvVolts, "V", hvAmps, "A"))
    ReadoutRow("DC power", fmtKw(hvVolts, hvAmps))
    ReadoutRow(
        "J1772 offer",
        buildString {
            append(advertised?.let { "%.1f A".format(it) } ?: "—")
            if (pilotDuty != null) append("  (pilot %.0f%%)".format(pilotDuty))
        },
    )
    ReadoutRow("DC limit", dcLimitAmps?.let { "%.1f A".format(it) } ?: "—")
}

/**
 * EVSE advertised current from the J1772 control-pilot duty cycle, per SAE
 * J1772 Table - the EVSE encodes its rating in the pilot PWM rather than
 * broadcasting it on CAN.
 *
 *   10%..85%  ->  amps = duty * 0.6
 *   85%..96%  ->  amps = (duty - 64) * 2.5
 *
 * Below 10% the pilot is signalling "no power available" (or digital comms in
 * the 3-7% band), and above 96% is not a valid advertisement -- both return
 * null so the UI shows a dash rather than a fabricated current.
 */
private fun j1772AdvertisedAmps(duty: Double?): Double? {
    if (duty == null) return null
    return when {
        duty >= 10.0 && duty <= 85.0 -> duty * 0.6
        duty > 85.0 && duty <= 96.0 -> (duty - 64.0) * 2.5
        else -> null
    }
}

@Composable
private fun ReadoutRow(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth().padding(vertical = 1.dp)) {
        Text(label, color = Color(0xFFAAAAAA), fontSize = 12.sp)
        Spacer(Modifier.weight(1f))
        Text(value, color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
    }
}

private fun fmtPair(a: Double?, aUnit: String, b: Double?, bUnit: String): String {
    if (a == null && b == null) return "—"
    val left = a?.let { "%.1f $aUnit".format(it) } ?: "—"
    val right = b?.let { "%.1f $bUnit".format(it) } ?: "—"
    return "$left  x  $right"
}

private fun fmtKw(volts: Double?, amps: Double?): String {
    if (volts == null || amps == null) return "—"
    return "%.2f kW".format(volts * amps / 1000.0)
}

// --- helpers --------------------------------------------------------------

@Composable
private fun SectionTitle(text: String) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFF1A1A1A))
            .padding(horizontal = 8.dp, vertical = 2.dp),
    ) {
        Text(
            text = text,
            fontWeight = FontWeight.SemiBold,
            color = Color.White,
            fontSize = 12.sp,
        )
    }
}

@Composable
fun StatusBanner(status: DataSourceStatus, modifier: Modifier = Modifier) {
    val (text, bg) = when (status) {
        is DataSourceStatus.Idle -> "Idle" to Color(0xFF424242)
        is DataSourceStatus.Connecting -> "Connecting..." to Color(0xFF1565C0)
        is DataSourceStatus.Handshaking -> {
            val s = if (status.pendingBuses.isEmpty())
                "Handshaking (${status.activeSubscriptions} subs)"
            else
                "Waiting for buses: ${status.pendingBuses.joinToString(", ")}"
            s to Color(0xFF1565C0)
        }
        is DataSourceStatus.Streaming ->
            "Streaming: ${status.activeBuses.joinToString(", ")}" to Color(0xFF2E7D32)
        is DataSourceStatus.Failed -> "Failed: ${status.reason}" to Color(0xFFC62828)
    }
    Box(
        modifier = modifier.fillMaxWidth().background(bg).padding(10.dp),
    ) {
        Text(text, color = Color.White, fontWeight = FontWeight.SemiBold)
    }
}

// --- bands and state machines --------------------------------------------

private val cellVoltageBands = listOf(
    ColorBand(2.5, 2.6, Color(0xFFC62828)),
    ColorBand(2.6, 3.0, Color(0xFFF9A825)),
    ColorBand(3.0, 3.6, Color(0xFF2E7D32)),
    ColorBand(3.6, 3.8, Color(0xFFC62828)),
)

private val cellTempBands = listOf(
    ColorBand(-20.0, 0.0, Color(0xFF1565C0)),
    ColorBand(0.0, 15.0, Color(0xFF26C6DA)),
    ColorBand(15.0, 45.0, Color(0xFF2E7D32)),
    ColorBand(45.0, 55.0, Color(0xFFF9A825)),
    ColorBand(55.0, 60.0, Color(0xFFC62828)),
)

private val engineCoolantBands = listOf(
    ColorBand(0.0, 40.0, Color(0xFF1565C0)),
    ColorBand(40.0, 70.0, Color(0xFF26C6DA)),
    ColorBand(70.0, 100.0, Color(0xFF2E7D32)),
    ColorBand(100.0, 110.0, Color(0xFFF9A825)),
    ColorBand(110.0, 130.0, Color(0xFFC62828)),
)

private val motorTempBands = listOf(
    ColorBand(0.0, 70.0, Color(0xFF2E7D32)),
    ColorBand(70.0, 80.0, Color(0xFFF9A825)),
    ColorBand(80.0, 100.0, Color(0xFFC62828)),
)

private fun contactorStateLabel(value: Int?): Pair<String, Color> = when (value) {
    null -> "—" to Color(0xFF424242)
    0 -> "ALL_OPEN" to Color(0xFF000000)
    7 -> "WAIT_PRECHARGE" to Color(0xFF00ACC1)
    8 -> "CLOSE_MAINP" to Color(0xFF00ACC1)
    11 -> "DRIVE_CLOSED" to Color(0xFF2E7D32)
    12 -> "CHARGE_CLOSED" to Color(0xFF2E7D32)
    13 -> "SHUTDOWN_REQ" to Color(0xFF00ACC1)
    14 -> "ALL_OPEN_SD" to Color(0xFF000000)
    else -> "STATE_$value" to Color(0xFF424242)
}

/**
 * Fault state derivation per spec §"Fault state derivation".
 *
 * Interlock-fault suppression: HVIL is allowed to open whenever the BMS is
 * not actively maintaining the HV loop. Only states where contactors are
 * commanded closed (or transitioning to/from closed) treat HVIL=0 as a
 * fault. See `vtrux-live-display-ui.md` §"Interlock fault suppression".
 */
// HVIL-eligible states: HVIL break here is a real fault. State 13
// (SHUTDOWN_REQUEST) is intentionally excluded -- the BMS is in the
// process of opening contactors and a legitimate HVIL drop happens
// during normal truck-off. Same for state 14 and state 0.
private val hvilEligibleStates = setOf(7, 8, 11, 12)

private fun faultStateLabel(
    signals: Map<String, Double>,
    mainc: Int?,
): Pair<String, Color> {
    val hvil = signals["bcm_hvil_mon"]?.toInt()
    val epo = signals["bcm_epo"]?.toInt()
    val gfd = signals["bcm_gfd"]
    val alarm = signals["bcm_alarm"]?.toInt() ?: 0
    val red = Color(0xFFC62828)
    return when {
        hvil == 0 && mainc in hvilEligibleStates -> "FAULT: INTERLOCK" to red
        epo == 1 -> "FAULT: EPO" to red
        gfd != null && gfd < 500.0 -> "FAULT: ISOLATION" to red
        // Alarm level 2 is suppressed -- treated as normal informational
        // chatter. Levels 1 and 3 still surface as faults.
        alarm > 0 && alarm != 2 -> "ALARM L$alarm" to red
        mainc == 11 || mainc == 12 -> "OK" to Color(0xFF2E7D32)
        else -> "IDLE" to Color(0xFF000000)
    }
}

private enum class DisplayMode { DRIVING, CHARGING, EXPORT, IDLE }

/**
 * Mode detection. Default fallback is DRIVING so the most useful gauge
 * (drivetrain torque) is the resting view; we only swap to CHARGING when
 * we have positive evidence (BMS contactor closed-charge). EXPORT
 * detection will be added once the BelInverter DBC is bundled.
 */
private fun currentMode(signals: Map<String, Double>): DisplayMode {
    val mainc = signals["bcm_mainc_stat"]?.toInt()
    return when (mainc) {
        12 -> DisplayMode.CHARGING
        else -> DisplayMode.DRIVING
    }
}
