package com.reverseit.display.widgets

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * Top-half tachometer. RPM 0..[maxRpm], needle pointing up = full clockwise
 * sweep from the left endpoint (RPM=0 at 180°) to the right endpoint
 * (RPM=max at 0°), passing through 12 o'clock (= up) somewhere in the
 * middle.
 *
 * Optional torque overlay: a "circular bar" near the base. Positive torque
 * paints clockwise from the leftmost (CCW-most) endpoint in blue; negative
 * torque paints counter-clockwise from the rightmost (CW-most) endpoint
 * in orange. (User-spec wording: "needle direction upwards = clockwise"
 * is honoured by mapping RPM increase to clockwise sweep, i.e. left to
 * right across the top arc.)
 */
@Composable
fun Tachometer(
    rpm: Double?,
    maxRpm: Double = 4000.0,
    torque: Double? = null,
    torqueRange: Double = 200.0,
    throttlePct: Double? = null,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier.fillMaxWidth().aspectRatio(1.6f),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.fillMaxWidth().aspectRatio(1.6f)) {
            val w = size.width
            val h = size.height
            // Centre of the arc at the bottom-centre.
            val cx = w / 2f
            val cy = h * 0.92f
            val radius = minOf(w * 0.45f, h * 0.85f)

            // Tick marks every 500 RPM, longer at thousands. Major ticks
            // also get a numeric label inside the arc (e.g. "0", "1", "2"...
            // in thousands of RPM).
            // RPM=0 at 9 o'clock (angle = PI), RPM=max at 3 o'clock (angle = 0),
            // passing through 12 o'clock (angle = PI/2). Needle sweeps clockwise.
            val startAngle = PI
            val rpmStep = 500.0
            val totalSteps = (maxRpm / rpmStep).toInt()
            val labelPaint = android.graphics.Paint().apply {
                color = android.graphics.Color.WHITE
                textSize = 11.sp.toPx()
                textAlign = android.graphics.Paint.Align.CENTER
                isAntiAlias = true
                isFakeBoldText = true
            }
            for (i in 0..totalSteps) {
                val rpmAt = i * rpmStep
                val t = rpmAt / maxRpm
                val angle = startAngle * (1.0 - t)
                val isMajor = (i % 2 == 0)
                val r1 = radius
                val r2 = if (isMajor) radius * 0.85f else radius * 0.91f
                val x1 = cx + r1 * cos(angle).toFloat()
                val y1 = cy - r1 * sin(angle).toFloat()
                val x2 = cx + r2 * cos(angle).toFloat()
                val y2 = cy - r2 * sin(angle).toFloat()
                drawLine(
                    color = Color(0xFFAAAAAA),
                    start = Offset(x1, y1),
                    end = Offset(x2, y2),
                    strokeWidth = if (isMajor) 2.5.dp.toPx() else 1.dp.toPx(),
                )
                if (isMajor) {
                    val rLabel = radius * 0.74f
                    val lx = cx + rLabel * cos(angle).toFloat()
                    // Add half the text size so the label is vertically centred
                    // around its baseline (Canvas drawText draws above the y).
                    val ly = cy - rLabel * sin(angle).toFloat() + labelPaint.textSize / 3f
                    val label = (rpmAt / 1000.0).let {
                        if (it == it.toInt().toDouble()) it.toInt().toString()
                        else String.format("%.1f", it)
                    }
                    drawIntoCanvas { canvas ->
                        canvas.nativeCanvas.drawText(label, lx, ly, labelPaint)
                    }
                }
            }

            // Outer arc (top half: 9 o'clock through 12 o'clock to 3 o'clock).
            // Compose drawArc: startAngle and sweepAngle in degrees, 0° at 3
            // o'clock, positive sweep is clockwise on screen (which because
            // Y points down means visually going DOWN through the bottom).
            // We want the top half, so sweep from 180° through 270° (12) to
            // 360°, i.e. sweepAngle = +180° from startAngle=180°.
            drawArc(
                color = Color(0xFF606060),
                startAngle = 180f,
                sweepAngle = 180f,
                useCenter = false,
                topLeft = Offset(cx - radius, cy - radius),
                size = Size(radius * 2f, radius * 2f),
                style = Stroke(width = 2.dp.toPx()),
            )

            // Throttle arc -- engine throttle position (0-100%), green,
            // sweeps clockwise from 9 o'clock. Sits just inside the torque
            // arc so both can be read at a glance.
            if (throttlePct != null) {
                val throttleClamped = throttlePct.coerceIn(0.0, 100.0)
                val throttleRadius = radius * 0.40f
                val throttleStroke = 6.dp.toPx()
                val sweepDeg = (180.0 * (throttleClamped / 100.0)).toFloat()
                if (sweepDeg > 0f) {
                    drawArc(
                        color = Color(0xFF2E7D32),
                        startAngle = 180f,
                        sweepAngle = sweepDeg,
                        useCenter = false,
                        topLeft = Offset(cx - throttleRadius, cy - throttleRadius),
                        size = Size(throttleRadius * 2f, throttleRadius * 2f),
                        style = Stroke(width = throttleStroke),
                    )
                }
            }

            // Torque arc, painted near the pivot. Positive torque grows
            // clockwise from the CCW-most point (9 o'clock) in blue; negative
            // grows counter-clockwise from the CW-most point (3 o'clock) in
            // orange. Both arcs live on the top half.
            if (torque != null) {
                val torqueClamped = torque.coerceIn(-torqueRange, torqueRange)
                val torqueRadius = radius * 0.55f
                val torqueStroke = 8.dp.toPx()
                if (torqueClamped > 0) {
                    val sweepDeg = (180.0 * (torqueClamped / torqueRange)).toFloat()
                    drawArc(
                        color = Color(0xFF1976D2),
                        startAngle = 180f,
                        sweepAngle = sweepDeg,
                        useCenter = false,
                        topLeft = Offset(cx - torqueRadius, cy - torqueRadius),
                        size = Size(torqueRadius * 2f, torqueRadius * 2f),
                        style = Stroke(width = torqueStroke),
                    )
                } else if (torqueClamped < 0) {
                    val sweepDeg = (180.0 * (-torqueClamped / torqueRange)).toFloat()
                    drawArc(
                        color = Color(0xFFEF6C00),
                        startAngle = 0f,
                        sweepAngle = -sweepDeg,
                        useCenter = false,
                        topLeft = Offset(cx - torqueRadius, cy - torqueRadius),
                        size = Size(torqueRadius * 2f, torqueRadius * 2f),
                        style = Stroke(width = torqueStroke),
                    )
                }
            }

            // Needle
            if (rpm != null) {
                val rpmClamped = rpm.coerceIn(0.0, maxRpm)
                val t = rpmClamped / maxRpm
                val angle = startAngle * (1.0 - t)
                val needleLen = radius * 0.88f
                val tip = Offset(
                    cx + needleLen * cos(angle).toFloat(),
                    cy - needleLen * sin(angle).toFloat(),
                )
                drawLine(
                    color = Color(0xFFFF5252),
                    start = Offset(cx, cy),
                    end = tip,
                    strokeWidth = 4.dp.toPx(),
                )
                drawCircle(
                    color = Color(0xFFFF5252),
                    radius = 6.dp.toPx(),
                    center = Offset(cx, cy),
                )
            }
        }

        // Static "× 1000 rpm" unit label below the gauge centre, replacing
        // the previous live RPM readout (rpm value is shown on the tick
        // marks now).
        Box(
            modifier = Modifier.fillMaxWidth(),
            contentAlignment = Alignment.BottomCenter,
        ) {
            Text(
                text = "× 1000 rpm",
                fontWeight = FontWeight.SemiBold,
                fontFamily = FontFamily.Monospace,
                fontSize = 10.sp,
                color = Color(0xFFAAAAAA),
            )
        }
    }
}
