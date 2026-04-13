package com.reverseit.coda

import android.content.res.AssetManager
import android.graphics.BitmapFactory
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

// ---------------------------------------------------------------------------
// Overlay layout constants (as fractions of the canvas width/height).
// Adjust these once the app is running on device to align with the JPG content.
// All Y values measured from top; X values measured from left.
// The JPG is drawn with ContentScale.Fit (maintain aspect ratio, centered).
// ---------------------------------------------------------------------------

private object Layout {
    // ---- Top bar row (BATTERY / EXP RANGE / MAX RANGE) ----
    // Pixel coords measured on the 320x240 source JPG, converted to fractions.
    val battBarXFrac  = 0.044f to 0.309f  // x14..99 / 320
    val expBarXFrac   = 0.366f to 0.494f  // x117..158 / 320
    val maxBarXFrac   = 0.691f to 0.822f  // x221..263 / 320
    val topBarYFrac   = 0.12f             // vertical center of the top bar row

    // Text X for exp/max is biased left (number sits left of the "miles" label in the JPG).
    // Use 35% from left edge of each box rather than the centre.
    val expTextXFrac  = 0.366f + (0.494f - 0.366f) * 0.35f   // ~0.411
    val maxTextXFrac  = 0.691f + (0.822f - 0.691f) * 0.35f   // ~0.737

    // ---- Left slider bars (notch marker) ----
    // Pixel coords: x19..113 / 320 for all bars.
    val sliderXFrac = 0.059f to 0.353f

    val motorBarXFrac    = sliderXFrac
    val motorBarYFrac    = 0.263f   // y63 / 240

    val climateBarXFrac  = sliderXFrac
    val climateBarYFrac  = 0.467f   // y112 / 240

    val auxBarXFrac      = sliderXFrac
    val auxBarYFrac      = 0.658f   // y158 / 240

    val battTempBarXFrac = sliderXFrac
    val battTempBarYFrac = 0.854f   // y205 / 240

    // Notch size as fraction of canvas height
    val notchWidthFrac  = 0.006f
    val notchHeightFrac = 0.065f
}

// ---------------------------------------------------------------------------

/**
 * Full-screen green screen display for the Coda app.
 *
 * Renders the background JPG selected by [state] and draws overlays on top:
 * - Numeric text for SoC%, expected range, max range
 * - A notch marker on each slider bar (motor torque, climate, aux power, battery temp)
 *
 * All 36 JPGs are loaded from assets/greenscreen/ on first composition and cached.
 * Subsequent JPG switches are instant (bitmap cache lookup only).
 */
@Composable
fun GreenScreenView(state: GreenScreenState) {
    val context = LocalContext.current
    val assets = context.assets
    val measurer = rememberTextMeasurer()

    // Cache all 36 bitmaps keyed by the 4-char JPG name
    var bitmapCache by remember { mutableStateOf<Map<String, androidx.compose.ui.graphics.ImageBitmap>>(emptyMap()) }
    LaunchedEffect(Unit) {
        bitmapCache = withContext(Dispatchers.IO) { loadAllBitmaps(assets) }
    }

    val bitmap = bitmapCache[state.jpgKey()]

    Canvas(modifier = Modifier.fillMaxSize()) {
        // --- Background JPG ---
        if (bitmap != null) {
            // Stretch to fill the entire canvas (no letterbox)
            val drawW = size.width
            val drawH = size.height

            drawImage(
                image = bitmap,
                dstOffset = androidx.compose.ui.unit.IntOffset(0, 0),
                dstSize = androidx.compose.ui.unit.IntSize(drawW.toInt(), drawH.toInt())
            )

            // Draw overlays relative to the drawn image rect
            drawOverlays(state, measurer, 0f, 0f, drawW, drawH)
        }
    }
}

private fun DrawScope.drawOverlays(
    state: GreenScreenState,
    measurer: TextMeasurer,
    imgLeft: Float,
    imgTop: Float,
    imgW: Float,
    imgH: Float,
) {
    val battStyle = TextStyle(
        color      = Color.White,
        fontSize   = (imgH * 0.031f).sp,   // ~65% of previous 0.048
        fontWeight = FontWeight.Bold
    )
    val rangeStyle = battStyle.copy(fontSize = (imgH * 0.027f).sp)  // ~65% of previous 0.042

    // --- Numeric text overlays ---
    drawCenteredText(measurer, "%.0f%%".format(state.socPercent),
        battStyle, imgLeft, imgTop, imgW, imgH,
        xFrac = Layout.battBarXFrac.center(), yFrac = Layout.topBarYFrac)

    drawRightAlignedText(measurer, "%.0f".format(state.expRangeMiles),
        rangeStyle, imgLeft, imgTop, imgW, imgH,
        rightXFrac = Layout.expBarXFrac.second - 0.01f, yFrac = Layout.topBarYFrac)

    drawRightAlignedText(measurer, "%.0f".format(state.maxRangeMiles),
        rangeStyle, imgLeft, imgTop, imgW, imgH,
        rightXFrac = Layout.maxBarXFrac.second - 0.01f, yFrac = Layout.topBarYFrac)

    // --- Notch markers ---
    // Motor torque: bidirectional, center = 0, left = max-negative, right = max-positive
    val motorFrac = 0.5f + (state.motorTorqueNm / (2f * CodaConstants.MOTOR_TORQUE_DISPLAY_MAX_NM))
        .coerceIn(-0.5f, 0.5f)
    drawNotch(imgLeft, imgTop, imgW, imgH,
        barXFrac = Layout.motorBarXFrac, barYFrac = Layout.motorBarYFrac, posFrac = motorFrac)

    // Climate power: 0 = left, max = right
    val climateFrac = (state.climatePowerKw / CodaConstants.CLIMATE_POWER_DISPLAY_MAX_KW)
        .coerceIn(0f, 1f)
    drawNotch(imgLeft, imgTop, imgW, imgH,
        barXFrac = Layout.climateBarXFrac, barYFrac = Layout.climateBarYFrac, posFrac = climateFrac)

    // Aux power: 0 = left, max = right
    val auxFrac = (state.auxPowerW / CodaConstants.AUX_POWER_DISPLAY_MAX_W)
        .coerceIn(0f, 1f)
    drawNotch(imgLeft, imgTop, imgW, imgH,
        barXFrac = Layout.auxBarXFrac, barYFrac = Layout.auxBarYFrac, posFrac = auxFrac)

    // Battery temperature: min = left, max = right
    val battTempFrac = ((state.battTempC - CodaConstants.BATT_TEMP_DISPLAY_MIN_C) /
            (CodaConstants.BATT_TEMP_DISPLAY_MAX_C - CodaConstants.BATT_TEMP_DISPLAY_MIN_C))
        .coerceIn(0f, 1f)
    drawNotch(imgLeft, imgTop, imgW, imgH,
        barXFrac = Layout.battTempBarXFrac, barYFrac = Layout.battTempBarYFrac, posFrac = battTempFrac)
}

private fun DrawScope.drawCenteredText(
    measurer: TextMeasurer,
    text: String,
    style: TextStyle,
    imgLeft: Float, imgTop: Float, imgW: Float, imgH: Float,
    xFrac: Float, yFrac: Float
) {
    val result = measurer.measure(text, style)
    val x = imgLeft + imgW * xFrac - result.size.width / 2f
    val y = imgTop  + imgH * yFrac - result.size.height / 2f
    drawText(result, topLeft = Offset(x, y))
}

private fun DrawScope.drawRightAlignedText(
    measurer: TextMeasurer,
    text: String,
    style: TextStyle,
    imgLeft: Float, imgTop: Float, imgW: Float, imgH: Float,
    rightXFrac: Float, yFrac: Float
) {
    val result = measurer.measure(text, style)
    val x = imgLeft + imgW * rightXFrac - result.size.width
    val y = imgTop  + imgH * yFrac - result.size.height / 2f
    drawText(result, topLeft = Offset(x, y))
}

private fun DrawScope.drawNotch(
    imgLeft: Float, imgTop: Float, imgW: Float, imgH: Float,
    barXFrac: Pair<Float, Float>, barYFrac: Float,
    posFrac: Float  // 0.0 = left edge of bar, 1.0 = right edge
) {
    val barLeft  = imgLeft + imgW * barXFrac.first
    val barRight = imgLeft + imgW * barXFrac.second
    val barY     = imgTop  + imgH * barYFrac

    val notchW = imgW * Layout.notchWidthFrac
    val notchH = imgH * Layout.notchHeightFrac
    val notchX = barLeft + (barRight - barLeft) * posFrac - notchW / 2f
    val notchY = barY - notchH / 2f

    // White notch with a dark outline for visibility on any bar color
    drawRect(Color.Black.copy(alpha = 0.6f),
        topLeft = Offset(notchX - 1f, notchY - 1f),
        size    = Size(notchW + 2f, notchH + 2f))
    drawRect(Color.White,
        topLeft = Offset(notchX, notchY),
        size    = Size(notchW, notchH))
}

private fun Pair<Float, Float>.center() = (first + second) / 2f

private fun loadAllBitmaps(assets: AssetManager): Map<String, androidx.compose.ui.graphics.ImageBitmap> {
    val modes  = listOf("C", "D")
    val cabin  = listOf("B", "N", "R")
    val motor  = listOf("G", "N", "R")
    val batt   = listOf("B", "N", "R")
    val result = mutableMapOf<String, androidx.compose.ui.graphics.ImageBitmap>()

    for (m in modes) {
        for (c in cabin) {
            // C-mode only has N for motor
            val motorOptions = if (m == "C") listOf("N") else motor
            for (t in motorOptions) {
                for (b in batt) {
                    val key = "$m$c$t$b"
                    try {
                        val bmp = assets.open("greenscreen/$key.JPG").use {
                            BitmapFactory.decodeStream(it)
                        }
                        result[key] = bmp.asImageBitmap()
                    } catch (e: Exception) {
                        // Missing file -- will show blank for that state
                        android.util.Log.w("CodaGreen", "Missing asset: greenscreen/$key.JPG")
                    }
                }
            }
        }
    }
    return result
}
