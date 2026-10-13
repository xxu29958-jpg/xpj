package com.ticketbox.ui.components

import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.foundation.text.modifiers.TextAutoSizeLayoutScope
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.asAmount

@Composable
fun AppAmountText(
    text: String,
    modifier: Modifier = Modifier,
    role: AppAmountRole = AppAmountRole.Medium,
    color: Color = MaterialTheme.colorScheme.onSurface,
    minFontSize: TextUnit = role.autosizeMinFontSize,
) {
    val style = MaterialTheme.typography.titleLarge.asAmount(role)
    AppAutosizedAmountText(
        text = text,
        modifier = modifier,
        spec = AppAmountTextSpec(
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
    minFontSize: TextUnit = role.autosizeMinFontSize,
) {
    val style = MaterialTheme.typography.titleLarge.asAmount(role)
    AppAutosizedAmountText(
        text = text,
        modifier = modifier,
        spec = AppAmountTextSpec(
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
    minFontSize: TextUnit = role.autosizeMinFontSize,
) {
    val style = MaterialTheme.typography.titleLarge.asAmount(role)
    AppAutosizedAmountText(
        text = text,
        modifier = modifier,
        spec = AppAmountTextSpec(
            color = color,
            style = style,
            minFontSize = minFontSize,
            maxFontSize = role.role.size,
            textAlign = TextAlign.End,
        ),
    )
}

private data class AppAmountTextSpec(
    val color: Color,
    val style: TextStyle,
    val minFontSize: TextUnit,
    val maxFontSize: TextUnit,
    val textAlign: TextAlign? = null,
)

@Composable
private fun AppAutosizedAmountText(
    text: String,
    modifier: Modifier,
    spec: AppAmountTextSpec,
) {
    Text(
        text = text,
        modifier = modifier,
        color = spec.color,
        // Autosizing changes the glyph size; keep the role's line-height ratio with it.
        style = spec.style.copy(lineHeight = (spec.style.lineHeight.value / spec.maxFontSize.value).em),
        autoSize = AmountAutoSize(
            minFontSize = spec.minFontSize,
            maxFontSize = spec.maxFontSize,
        ),
        textAlign = spec.textAlign,
    )
}

/** Keep the existing one-line size ladder; amounts that exceed its floor can wrap in full. */
private data class AmountAutoSize(
    val minFontSize: TextUnit,
    val maxFontSize: TextUnit,
) : TextAutoSize {
    override fun TextAutoSizeLayoutScope.getFontSize(constraints: Constraints, text: AnnotatedString): TextUnit {
        var lower = 0
        var upper = (maxFontSize.value - minFontSize.value).toInt()
        var chosen = minFontSize
        while (lower <= upper) {
            val step = lower + (upper - lower) / 2
            val candidate = (minFontSize.value + step).sp
            val layout = performLayout(constraints, text, candidate)
            if (layout.lineCount <= 1 && !layout.hasVisualOverflow) {
                chosen = candidate
                lower = step + 1
            } else {
                upper = step - 1
            }
        }
        return chosen
    }
}

internal val AppAmountRole.autosizeMinFontSize: TextUnit
    get() = when (this) {
        AppAmountRole.Display -> 18.sp
        AppAmountRole.Hero -> 18.sp
        AppAmountRole.Medium -> 14.sp
        AppAmountRole.Compact -> 11.sp
    }
