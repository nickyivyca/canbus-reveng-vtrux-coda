package com.reverseit.display.widgets

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Three-state fault indicator: a short label whose *fill* and *outline* encode two different bits.
 *
 * [StatusWord] cannot express this. It carries a background and a foreground colour but has no
 * outline, and the whole point here is that "this fault is latched" and "this fault is happening
 * right now" are independent facts that must be visible at the same time.
 *
 * The distinction is not cosmetic. On the 914 a cell dipping under the limit for a single BMS
 * cycle latches the fault and halves throttle authority for the rest of the drive, while the
 * instantaneous bit clears again within a cycle. An indicator showing only the instantaneous bit
 * would flash and vanish; one showing only the latch could not say whether the condition is still
 * present. The outline persisting after the fill clears is exactly the "it happened and you are
 * still living with it" state the driver otherwise has no way to see.
 */
enum class FaultState {
    /** Neither bit set. */
    CLEAR,

    /** Latched, but the condition is not present right now. Outline only. */
    LATCHED,

    /** The condition is present right now. Filled. */
    PRESENT,
}

/**
 * Present outranks latched.
 *
 * In practice a set instantaneous bit implies the latch was set in the same cycle, so [PRESENT] is
 * a superset rather than an alternative -- but the ordering is written explicitly instead of
 * relying on that, because a producer that ever emits them out of step should degrade to the
 * louder state, not the quieter one.
 */
fun faultStateOf(latched: Boolean, present: Boolean): FaultState = when {
    present -> FaultState.PRESENT
    latched -> FaultState.LATCHED
    else -> FaultState.CLEAR
}

private val CHIP_CLEAR_FILL = Color(0xFF2A2A2A)
private val CHIP_CLEAR_OUTLINE = Color(0xFF555555)
private val CHIP_CLEAR_TEXT = Color(0xFF888888)
private val CHIP_FAULT = Color(0xFFFF1744)

@Composable
fun FaultChip(
    label: String,
    state: FaultState,
    modifier: Modifier = Modifier,
) {
    val fill = when (state) {
        FaultState.PRESENT -> CHIP_FAULT
        else -> CHIP_CLEAR_FILL
    }
    val outline = when (state) {
        FaultState.CLEAR -> CHIP_CLEAR_OUTLINE
        else -> CHIP_FAULT
    }
    val outlineWidth = if (state == FaultState.CLEAR) 1.dp else 2.dp
    val text = when (state) {
        FaultState.CLEAR -> CHIP_CLEAR_TEXT
        else -> Color.White
    }
    val shape = RoundedCornerShape(4.dp)

    Box(
        modifier = modifier
            .background(fill, shape = shape)
            .border(outlineWidth, outline, shape = shape)
            // Uniform padding regardless of border width: Compose draws the border inside the
            // layout bounds, so letting it vary would make a chip visibly twitch as it changed
            // state, and a row of five chips would reflow every time one of them tripped.
            .padding(horizontal = 8.dp, vertical = 5.dp),
    ) {
        Text(
            text = label,
            color = text,
            fontWeight = FontWeight.Bold,
            fontSize = 12.sp,
            textAlign = TextAlign.Center,
        )
    }
}
