package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
fun AppFilterChip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    selectedContainerColor: Color? = null,
    leadingIcon: (@Composable () -> Unit)? = null,
    trailingIcon: (@Composable () -> Unit)? = null,
) {
    val density = LocalDensity.current
    val visuals = LocalThemeVisuals.current
    val shape = RoundedCornerShape(AppRadius.extraSmall)
    val metrics = appFilterChipMetrics(
        label = label,
        hasIcon = leadingIcon != null || trailingIcon != null,
        fontScale = density.fontScale,
    )
    val containerColor = if (selected) {
        selectedContainerColor ?: visuals.chipSelected.copy(alpha = AppAlpha.opaque)
    } else {
        visuals.chipUnselected.copy(alpha = AppAlpha.soft)
    }
    val contentColor = if (selected) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    val borderColor = if (selected) {
        MaterialTheme.colorScheme.primary.copy(alpha = AppAlpha.medium)
    } else {
        MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium)
    }
    Row(
        modifier = modifier
            .defaultMinSize(minHeight = metrics.minHeight)
            .alpha(if (enabled) 1f else AppAlpha.strong)
            .clip(shape)
            .background(containerColor)
            .border(width = 1.dp, color = borderColor, shape = shape)
            .selectable(
                selected = selected,
                enabled = enabled,
                role = Role.Button,
                onClick = onClick,
            )
            .padding(horizontal = metrics.horizontalPadding, vertical = metrics.verticalPadding),
        horizontalArrangement = Arrangement.spacedBy(metrics.iconGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CompositionLocalProvider(LocalContentColor provides contentColor) {
            leadingIcon?.invoke()
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                autoSize = TextAutoSize.StepBased(minFontSize = 11.sp, maxFontSize = 14.sp, stepSize = 1.sp),
                fontWeight = if (selected) AppTextHierarchy.heading.weight else FontWeight.Medium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                color = contentColor,
            )
            trailingIcon?.invoke()
        }
    }
}

private data class AppFilterChipMetrics(
    val minHeight: Dp,
    val horizontalPadding: Dp,
    val verticalPadding: Dp,
    val iconGap: Dp,
)

private fun appFilterChipMetrics(
    label: String,
    hasIcon: Boolean,
    fontScale: Float,
): AppFilterChipMetrics {
    val longLabel = label.length >= 5
    val enlargedText = fontScale >= 1.15f
    return AppFilterChipMetrics(
        minHeight = if (enlargedText) 44.dp else AppSpacing.controlMinHeight,
        horizontalPadding = when {
            longLabel && hasIcon -> AppSpacing.smallGap
            longLabel -> AppSpacing.contentGap
            else -> AppSpacing.compactGap
        },
        verticalPadding = if (enlargedText) AppSpacing.smallGap else AppSpacing.miniGap,
        iconGap = if (longLabel) AppSpacing.tinyGap else AppSpacing.miniGap,
    )
}
