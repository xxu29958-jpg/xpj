package com.ticketbox.ui.components

import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
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
    AppAutosizedSingleLineText(
        text = text,
        modifier = modifier,
        spec = AppAutosizedSingleLineSpec(
            color = color,
            style = style,
            minFontSize = minFontSize,
            maxFontSize = role.role.size,
        ),
    )
}

@Composable
fun AppEndAlignedAmountText(
    text: String,
    modifier: Modifier = Modifier,
    role: AppAmountRole = AppAmountRole.Medium,
    color: Color = MaterialTheme.colorScheme.onSurface,
    minFontSize: TextUnit = role.defaultMinFontSize,
) {
    val style = MaterialTheme.typography.titleLarge.asAmount(role)
    AppAutosizedSingleLineText(
        text = text,
        modifier = modifier,
        spec = AppAutosizedSingleLineSpec(
            color = color,
            style = style,
            minFontSize = minFontSize,
            maxFontSize = role.role.size,
            textAlign = TextAlign.End,
        ),
    )
}

@Composable
fun AppEndAlignedAmountStatusText(
    text: String,
    modifier: Modifier = Modifier,
    role: AppAmountRole = AppAmountRole.Compact,
    color: Color = MaterialTheme.colorScheme.onSurfaceVariant,
    minFontSize: TextUnit = role.defaultMinFontSize,
) {
    val style = MaterialTheme.typography.titleLarge.asAmount(role)
    AppAutosizedSingleLineText(
        text = text,
        modifier = modifier,
        spec = AppAutosizedSingleLineSpec(
            color = color,
            style = style,
            minFontSize = minFontSize,
            maxFontSize = role.role.size,
            textAlign = TextAlign.End,
        ),
    )
}

private data class AppAutosizedSingleLineSpec(
    val color: Color,
    val style: TextStyle,
    val minFontSize: TextUnit,
    val maxFontSize: TextUnit,
    val textAlign: TextAlign? = null,
)

@Composable
private fun AppAutosizedSingleLineText(
    text: String,
    modifier: Modifier,
    spec: AppAutosizedSingleLineSpec,
) {
    Text(
        text = text,
        modifier = modifier,
        color = spec.color,
        style = spec.style,
        autoSize = TextAutoSize.StepBased(
            minFontSize = spec.minFontSize,
            maxFontSize = spec.maxFontSize,
            stepSize = 1.sp,
        ),
        maxLines = 1,
        overflow = TextOverflow.Clip,
        textAlign = spec.textAlign,
    )
}

private val AppAmountRole.defaultMinFontSize: TextUnit
    get() = when (this) {
        AppAmountRole.Hero -> 18.sp
        AppAmountRole.Medium -> 14.sp
        AppAmountRole.Compact -> 11.sp
    }
