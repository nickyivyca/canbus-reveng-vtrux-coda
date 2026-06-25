package com.reverseit.display.widgets

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * A short highlighted text label. Used for contactor state, fault state,
 * EVAP, etc. -- the spec calls for "highlighted color coded words" with
 * specific background colours per state.
 */
@Composable
fun StatusWord(
    label: String,
    text: String,
    bgColor: Color,
    fgColor: Color = Color.White,
    modifier: Modifier = Modifier,
) {
    androidx.compose.foundation.layout.Row(modifier = modifier) {
        if (label.isNotBlank()) {
            Text(
                text = "$label ",
                color = Color.White,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Text(
            text = text,
            color = fgColor,
            fontWeight = FontWeight.Bold,
            modifier = Modifier
                .background(bgColor, shape = RoundedCornerShape(4.dp))
                .padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}
