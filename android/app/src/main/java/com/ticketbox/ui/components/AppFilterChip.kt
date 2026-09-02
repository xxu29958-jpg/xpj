package com.ticketbox.ui.components

import androidx.compose.foundation.background
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
import androidx.compose.runtime.compositionLocalOf
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

enum class AppChipDensity {
    Standard,
    Compact,
}

private val LocalAppChipDensity = compositionLocalOf { AppChipDensity.Standard }

data class AppFilterChipOptions(
    val enabled: Boolean = true,
    val selectedContainerColor: Color? = null,
    val leadingIcon: (@Composable () -> Unit)? = null,
    val trailingIcon: (@Composable () -> Unit)? = null,
)

@Composable
fun AppCompactChips(content: @Composable () -> Unit) {
    CompositionLocalProvider(LocalAppChipDensity provides AppChipDensity.Compact) {
        content()
    }
}

@Composable
fun AppFilterChip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    options: AppFilterChipOptions = AppFilterChipOptions(),
) {
    val density = LocalDensity.current
    val chipDensity = LocalAppChipDensity.current
    val visuals = LocalThemeVisuals.current
    val shape = RoundedCornerShape(AppRadius.extraSmall)
    val metrics = appFilterChipMetrics(
        label = label,
        hasIcon = options.leadingIcon != null || options.trailingIcon != null,
        fontScale = density.fontScale,
        chipDensity = chipDensity,
    )
    val containerColor = if (selected) {
        options.selectedContainerColor ?: visuals.chipSelected.copy(alpha = AppAlpha.opaque)
    } else {
        visuals.chipUnselected.copy(alpha = AppAlpha.soft)
    }
    val contentColor = if (selected) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    Row(
        modifier = modifier
            .defaultMinSize(minHeight = AppSpacing.controlMinHeight)
            .alpha(if (options.enabled) 1f else AppAlpha.strong)
            .clip(shape)
            .background(containerColor)
            .selectable(
                selected = selected,
                enabled = options.enabled,
                role = Role.Button,
                onClick = onClick,
            )
            .padding(horizontal = metrics.horizontalPadding, vertical = metrics.verticalPadding),
        horizontalArrangement = Arrangement.spacedBy(metrics.iconGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CompositionLocalProvider(LocalContentColor provides contentColor) {
            options.leadingIcon?.invoke()
            AppFilterChipLabel(
                label = label,
                selected = selected,
                contentColor = contentColor,
                chipDensity = chipDensity,
            )
            options.trailingIcon?.invoke()
        }
    }
}

@Composable
private fun AppFilterChipLabel(
    label: String,
    selected: Boolean,
    contentColor: Color,
    chipDensity: AppChipDensity,
) {
    Text(
        text = label,
        style = MaterialTheme.typography.labelMedium,
        autoSize = TextAutoSize.StepBased(
            minFontSize = 11.sp,
            maxFontSize = if (chipDensity == AppChipDensity.Compact) 13.sp else 14.sp,
            stepSize = 1.sp,
        ),
        fontWeight = if (selected) AppTextHierarchy.heading.weight else FontWeight.Medium,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        color = contentColor,
    )
}

private data class AppFilterChipMetrics(
    val horizontalPadding: Dp,
    val verticalPadding: Dp,
    val iconGap: Dp,
)

private fun appFilterChipMetrics(
    label: String,
    hasIcon: Boolean,
    fontScale: Float,
    chipDensity: AppChipDensity,
): AppFilterChipMetrics {
    val enlargedText = fontScale >= 1.15f
    return when (chipDensity) {
        AppChipDensity.Compact -> compactAppFilterChipMetrics(label = label, hasIcon = hasIcon, enlargedText = enlargedText)
        AppChipDensity.Standard -> standardAppFilterChipMetrics(label = label, hasIcon = hasIcon, enlargedText = enlargedText)
    }
}

private fun compactAppFilterChipMetrics(
    label: String,
    hasIcon: Boolean,
    enlargedText: Boolean,
): AppFilterChipMetrics {
    val longLabel = label.length >= 5
    return AppFilterChipMetrics(
        horizontalPadding = compactFilterChipHorizontalPadding(longLabel, hasIcon),
        verticalPadding = if (enlargedText) AppSpacing.miniGap else AppSpacing.tinyGap,
        iconGap = AppSpacing.tinyGap,
    )
}

private fun standardAppFilterChipMetrics(
    label: String,
    hasIcon: Boolean,
    enlargedText: Boolean,
): AppFilterChipMetrics {
    val longLabel = label.length >= 5
    return AppFilterChipMetrics(
        horizontalPadding = standardFilterChipHorizontalPadding(longLabel, hasIcon),
        verticalPadding = if (enlargedText) AppSpacing.smallGap else AppSpacing.miniGap,
        iconGap = if (longLabel) AppSpacing.tinyGap else AppSpacing.miniGap,
    )
}

private fun compactFilterChipHorizontalPadding(longLabel: Boolean, hasIcon: Boolean): Dp = when {
    longLabel && hasIcon -> AppSpacing.miniGap
    longLabel -> AppSpacing.smallGap
    else -> AppSpacing.contentGap
}

private fun standardFilterChipHorizontalPadding(longLabel: Boolean, hasIcon: Boolean): Dp = when {
    longLabel && hasIcon -> AppSpacing.smallGap
    longLabel -> AppSpacing.contentGap
    else -> AppSpacing.compactGap
}
