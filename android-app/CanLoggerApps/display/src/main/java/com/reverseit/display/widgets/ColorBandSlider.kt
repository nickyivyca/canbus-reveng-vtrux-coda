package com.reverseit.display.widgets

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.layout
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.roundToInt

/**
 * Horizontal coloured-band scale bar with one or more triangular markers
 * drawn around the bar (above by default, below if specified).
 *
 * The marker lane height is adaptive: lanes that have no markers in them
 * collapse, so a slider with only top markers takes less vertical room
 * than one with markers on both sides.
 */
data class ColorBand(val from: Double, val to: Double, val color: Color)

data class SliderMarker(
    val value: Double?,
    val label: String = "",
    val color: Color = Color.White,
    /** When true the marker sits beneath the bar with its tip pointing UP. */
    val below: Boolean = false,
)

/** Vertical reference tick + optional label beneath it. */
data class ReferenceLine(val value: Double, val label: String = "")

@Composable
fun ColorBandSlider(
    label: String,
    markers: List<SliderMarker>,
    min: Double,
    max: Double,
    bands: List<ColorBand>,
    modifier: Modifier = Modifier,
    barHeight: Int = 14,
    referenceLines: List<ReferenceLine> = emptyList(),
    /** Appended to the min/max boundary labels, e.g. "%" or " V". */
    boundarySuffix: String = "",
) {
    val hasTopMarkers = markers.any { it.value != null && !it.below }
    val hasBottomMarkers = markers.any { it.value != null && it.below }
    val hasRefLabels = referenceLines.any { it.label.isNotBlank() }

    Column(modifier = modifier.fillMaxWidth()) {
        if (label.isNotBlank()) {
            Text(
                text = label,
                fontWeight = FontWeight.SemiBold,
                color = Color.White,
                fontSize = 11.sp,
            )
        }
        val laneTop = if (hasTopMarkers) 12 else 2
        // Reference-line labels render in the boundary Row below the canvas
        // (same font/color/baseline as the min/max labels), so they don't
        // require any extra canvas space.
        val laneBottom = if (hasBottomMarkers) 12 else 2
        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .height((barHeight + laneTop + laneBottom).dp),
        ) {
            val w = size.width
            val barTop = laneTop.dp.toPx()
            val barBot = barTop + barHeight.dp.toPx()

            // Bands
            for (band in bands) {
                val x0 = remap(band.from, min, max, 0.0, w.toDouble()).toFloat().coerceIn(0f, w)
                val x1 = remap(band.to, min, max, 0.0, w.toDouble()).toFloat().coerceIn(0f, w)
                drawRect(
                    color = band.color,
                    topLeft = Offset(x0, barTop),
                    size = Size(x1 - x0, barBot - barTop),
                )
            }
            drawRect(
                color = Color(0xFF888888),
                topLeft = Offset(0f, barTop),
                size = Size(w, barBot - barTop),
                style = Stroke(width = 1.dp.toPx()),
            )

            // Reference tick marks (labels live in the boundary Row below
            // the canvas; see the Box at the bottom of this Column).
            for (ref in referenceLines) {
                if (ref.value < min || ref.value > max) continue
                val xRef = remap(ref.value, min, max, 0.0, w.toDouble()).toFloat()
                drawLine(
                    color = Color.White,
                    start = Offset(xRef, barTop - 2.dp.toPx()),
                    end = Offset(xRef, barBot + 2.dp.toPx()),
                    strokeWidth = 2.dp.toPx(),
                )
            }

            // Markers
            val triangleH = 8.dp.toPx()
            val triangleW = 10.dp.toPx()
            for (m in markers) {
                val v = m.value ?: continue
                val x = remap(v, min, max, 0.0, w.toDouble()).toFloat().coerceIn(0f, w)
                val (tipY, baseY) = if (m.below) {
                    barBot to (barBot + triangleH)
                } else {
                    barTop to (barTop - triangleH)
                }
                val p = Path().apply {
                    moveTo(x, tipY)
                    lineTo(x - triangleW / 2f, baseY)
                    lineTo(x + triangleW / 2f, baseY)
                    close()
                }
                drawPath(p, color = m.color)
                drawPath(
                    p,
                    color = Color.Black,
                    style = Stroke(width = 1.dp.toPx()),
                )
            }
        }
        // Boundary + reference labels. min sits at the left edge, max at
        // the right; any reference label is centred at its tick by mapping
        // its value through the same scale used inside the canvas. All
        // share the same font + color so they read as one labelling lane.
        Box(modifier = Modifier.fillMaxWidth()) {
            Text(
                text = formatBoundary(min) + boundarySuffix,
                fontSize = 9.sp,
                color = Color(0xFF888888),
                modifier = Modifier.align(Alignment.TopStart),
            )
            Text(
                text = formatBoundary(max) + boundarySuffix,
                fontSize = 9.sp,
                color = Color(0xFF888888),
                modifier = Modifier.align(Alignment.TopEnd),
            )
            for (ref in referenceLines) {
                if (ref.label.isBlank()) continue
                if (ref.value < min || ref.value > max) continue
                val t = ((ref.value - min) / (max - min)).coerceIn(0.0, 1.0)
                Text(
                    text = ref.label,
                    fontSize = 9.sp,
                    color = Color(0xFF888888),
                    modifier = Modifier.layout { measurable, constraints ->
                        val placeable = measurable.measure(constraints)
                        layout(placeable.width, placeable.height) {
                            val x = (constraints.maxWidth * t).roundToInt() -
                                placeable.width / 2
                            placeable.placeRelative(
                                x.coerceIn(0, constraints.maxWidth - placeable.width),
                                0,
                            )
                        }
                    },
                )
            }
        }
    }
}

private fun remap(x: Double, fromLo: Double, fromHi: Double, toLo: Double, toHi: Double): Double {
    if (fromHi == fromLo) return toLo
    val t = (x - fromLo) / (fromHi - fromLo)
    return toLo + t * (toHi - toLo)
}

private fun formatBoundary(v: Double): String =
    when {
        v == v.toLong().toDouble() && kotlin.math.abs(v) < 1e6 -> v.toLong().toString()
        else -> String.format("%.1f", v)
    }
