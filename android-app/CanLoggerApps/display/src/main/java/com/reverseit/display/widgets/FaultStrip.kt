package com.reverseit.display.widgets

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.reverseit.display.FaultSeverity
import com.reverseit.display.FaultVerdict
import com.reverseit.display.LatchedFault
import com.reverseit.display.LatchPhase

/**
 * The fault statement. Sits below the mode panel and renders **nothing at all**
 * while the truck is healthy, so the display's resting state is unchanged.
 *
 * Collapsed it is one line: the cause the pack latched. Tapping expands to the
 * evidence rows and the raw records, which is the form meant to be read down a
 * phone by whoever is driving.
 *
 * [expanded] is hoisted so the screen can scroll the strip back into view when
 * it grows -- expanded, it is taller than the space left below the mode panel,
 * and the part that falls under the status banner is the code line, which is
 * the one thing the driver is being asked to read out.
 */
@Composable
fun FaultStrip(
    latched: LatchedFault?,
    expanded: Boolean,
    onToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    if (latched == null) return
    val v: FaultVerdict = latched.verdict
    if (v.severity == FaultSeverity.NONE) return

    val cleared = latched.phase == LatchPhase.CLEARED
    val warning = v.severity == FaultSeverity.WARNING
    val bg = when {
        cleared -> Color(0xFF37474F)
        warning -> Color(0xFFEF6C00)
        else -> Color(0xFFC62828)
    }
    val accent = when {
        cleared -> Color(0xFFB0BEC5)
        warning -> Color(0xFFFFE0B2)
        else -> Color(0xFFFFCDD2)
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .background(bg, RoundedCornerShape(8.dp))
            .clickable { onToggle() }
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    text = if (cleared) "CLEARED - ${v.headline}" else v.headline,
                    color = Color.White,
                    fontWeight = FontWeight.Bold,
                    fontSize = 18.sp,
                )
                // The elapsed line answers the driver's actual next question:
                // is this still happening, and how long ago did it start.
                Text(
                    text = latched.timingLine(),
                    color = accent,
                    fontSize = 12.sp,
                )
            }
            Text(if (expanded) "hide" else "details", color = accent, fontSize = 13.sp)
        }

        if (expanded) {
            Spacer(Modifier.height(8.dp))
            Text(v.detail, color = Color(0xFFFFF3E0), fontSize = 14.sp, lineHeight = 18.sp)
            Spacer(Modifier.height(8.dp))
            for ((label, value) in latched.liveEvidence) {
                Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                    Text(label, color = accent, fontSize = 13.sp,
                        modifier = Modifier.width(130.dp))
                    Text(value, color = Color.White, fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold)
                }
            }
            if (v.codes.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Text("Read this out:", color = accent, fontSize = 12.sp)
                Text(
                    text = v.codes.joinToString("   "),
                    color = Color.White,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 17.sp,
                    fontWeight = FontWeight.Bold,
                    // The host's floating settings cog sits over the lower right
                    // of this card; keep the codes clear of it.
                    modifier = Modifier.padding(end = 72.dp),
                )
            }
        }
    }
}
