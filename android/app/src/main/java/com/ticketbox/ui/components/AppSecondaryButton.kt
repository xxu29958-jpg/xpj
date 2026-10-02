package com.ticketbox.ui.components

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import com.ticketbox.ui.design.AppIconSize
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
fun AppSecondaryButton(
    text: String,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    leadingIcon: ImageVector? = null,
    onClick: () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    FilledTonalButton(
        modifier = modifier.defaultMinSize(minHeight = AppSpacing.controlMinHeight),
        enabled = enabled,
        onClick = onClick,
        shape = RoundedCornerShape(AppRadius.small),
        contentPadding = PaddingValues(horizontal = AppSpacing.compactGap, vertical = AppSpacing.smallGap),
        colors = ButtonDefaults.filledTonalButtonColors(
            containerColor = visuals.surfaceSunken,
            contentColor = visuals.textDefault,
            disabledContainerColor = visuals.surfaceSunken,
            disabledContentColor = visuals.textMuted.copy(alpha = 0.48f),
        ),
    ) {
        leadingIcon?.let {
            Icon(it, contentDescription = null, modifier = Modifier.size(AppIconSize.compact))
            Spacer(modifier = Modifier.width(AppSpacing.smallGap))
        }
        Text(text = text, style = MaterialTheme.typography.labelLarge, textAlign = TextAlign.Center)
    }
}
