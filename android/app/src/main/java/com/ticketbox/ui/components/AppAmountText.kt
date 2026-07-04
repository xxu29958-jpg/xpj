package com.ticketbox.ui.components

import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.asAmount

@Composable
fun AppAmountText(
    text: String,
    modifier: Modifier = Modifier,
    role: AppAmountRole = AppAmountRole.Medium,
    color: Color = MaterialTheme.colorScheme.onSurface,
    minFontSize: TextUnit = role.defaultMinFontSize,
) {
    val style = MaterialTheme.typography.titleLarge.asAmount(role)
    Text(
        text = text,
        modifier = modifier,
        color = color,
        style = style,
        autoSize = TextAutoSize.StepBased(
            minFontSize = minFontSize,
            maxFontSize = role.role.size,
            stepSize = 1.sp,
        ),
        maxLines = 1,
        overflow = TextOverflow.Clip,
    )
}

private val AppAmountRole.defaultMinFontSize: TextUnit
    get() = when (this) {
        AppAmountRole.Hero -> 18.sp
        AppAmountRole.Medium -> 14.sp
    }
